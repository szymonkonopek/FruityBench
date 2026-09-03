/* fb_fit.hpp -- FruitBench's activity recorder.
 *
 * Writes one FIT activity file with, on top of the ordinary record and lap
 * content, one developer field per declared custom measure:
 *
 *   time-based measures (isTimeBased: true)  -> developer fields on `record`
 *   per-lap measures    (isTimeBased: false) -> developer fields on `lap`
 *
 * That split is the documented shape of the activity report: a time-based
 * metric is a series of [time, value] pairs, a non-time-based one is one value
 * per lap. The developer field's `field_name` is the manifest's measure `id`
 * verbatim and its `units` is `unitMetric`, which is the only join between the
 * two halves that exists to be tested -- the SDK defines no mapping from the
 * manifest to FIT, so FruitBench asserts the obvious one and lets the
 * companion app agree or disagree visibly.
 *
 * Takes an SDK::Interface::IFile rather than the kernel, so the same code
 * writes to the watch filesystem and to a plain file in the host test
 * (tools/fit_host_test.cpp).
 */
#ifndef FB_FIT_HPP
#define FB_FIT_HPP

#include <ctime>
#include <cstdint>

#include "SDK/Fit/FitWriter.hpp"
#include "SDK/Interfaces/IFileSystem.hpp"

extern "C" {
#include "fb_gen.h"
}

class FbFitWriter {
public:
    /* Local message types. Eight of the sixteen FIT slots; the field
     * description slot is redefined once per measure because the name and
     * units strings differ in length. */
    enum : uint8_t {
        L_FILE_ID    = 0,
        L_DEV_ID     = 1,
        L_FIELD_DESC = 2,
        L_EVENT      = 3,
        L_RECORD     = 4,
        L_LAP        = 5,
        L_SESSION    = 6,
        L_ACTIVITY   = 7
    };

    explicit FbFitWriter(SDK::Interface::IFile &file);

    /* Header, file_id, developer_data_id, all 32 field descriptions, every
     * message definition and the timer START event. `appId` must be the
     * 16-character hex App ID; it is copied verbatim into
     * developer_data_id.application_id, as the SDK examples do. `serial`
     * becomes file_id.serial_number, and FruitBench passes the session seed:
     * it is the one number a whole recording can be reproduced from, so the
     * file carries it. */
    bool begin(std::time_t utc, const char *appId, uint32_t serial);

    /* One record message: the predefined metrics plus every time-based
     * measure's current value. */
    bool addRecord(const fb_gen_t &g, std::time_t utc);

    /* Close a lap: writes the lap message with its aggregates and every
     * per-lap measure's value, then resets the lap accumulators. A lap that
     * would have zero duration is refused rather than written. */
    bool addLap(const fb_gen_t &g, std::time_t utc);

    /* Timer STOP, the final lap if one is open, session, activity, then the
     * header back-patch and file CRC. Leaves the file open -- the caller
     * flushes and closes it, which is what registers the activity.
     *
     * `g` is non-const because closing the final lap draws the last
     * increments: without them the session totals would not match the sum of
     * the lap values in the file. */
    bool finish(fb_gen_t &g, std::time_t utc);

    bool     ok() const { return mOk && mFit.ok(); }
    uint32_t records() const { return mRecords; }
    uint16_t laps() const { return mLaps; }

    /* Sum of the sizes of all developer fields on each definition -- the
     * record number is what decides how big an hour of this activity is. */
    static uint32_t recordDevBytes();
    static uint32_t lapDevBytes();
    static uint32_t sessionDevBytes();

private:
    struct Accum {
        float    hrSum;
        uint32_t hrCount;
        float    hrMax;
        float    speedSum;
        uint32_t speedCount;
        float    speedMax;
        float    distStart;
        float    ascentStart;
        float    descentStart;
        std::time_t startUtc;
    };

    bool writeFieldDescription(const fb_measure_t &m);
    bool defineMessages();
    bool addEvent(std::time_t utc, bool start);
    void accumInit(Accum &a, std::time_t utc);
    void accumReset(Accum &a, const fb_gen_t &g, std::time_t utc);
    void accumAdd(Accum &a, const fb_gen_t &g);
    /* Appends one measure's value to a data record in the field's base type. */
    void putValue(SDK::Fit::FitWriter::Data &d, const fb_measure_t &m, float v);

    SDK::Fit::FitWriter      mFit;
    bool                     mOk;
    std::time_t              mStartUtc;
    uint32_t                 mRecords;
    uint16_t                 mLaps;
    Accum                    mSession;
    Accum                    mLap;
};

#endif /* FB_FIT_HPP */
