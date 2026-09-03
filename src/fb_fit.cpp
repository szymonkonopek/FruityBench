/* fb_fit.cpp -- see fb_fit.hpp. */

#include <cmath>
#include <cstring>

#include "SDK/Fit/FitProfile.hpp"
#include "SDK/Fit/FitRecordCadence.hpp"

#include "fb_fit.hpp"

namespace fit = SDK::Fit;

namespace {

/* Seconds between the UNIX epoch and the FIT epoch (1989-12-31 00:00 UTC).
 * The SDK has no helper for this; every example carries its own copy. */
constexpr std::time_t kFitEpochOffset = 631065600;

uint32_t toFitTime(std::time_t t)
{
    return static_cast<uint32_t>(t - kFitEpochOffset);
}

int32_t toSemicircles(double deg)
{
    return static_cast<int32_t>(deg * (2147483648.0 / 180.0));
}

fit::BaseType baseTypeOf(uint8_t type)
{
    switch (type) {
    case FB_T_U8:  return fit::BaseType::UInt8;
    case FB_T_U16: return fit::BaseType::UInt16;
    case FB_T_U32: return fit::BaseType::UInt32;
    case FB_T_S16: return fit::BaseType::SInt16;
    case FB_T_S32: return fit::BaseType::SInt32;
    default:       return fit::BaseType::Float32;
    }
}

uint8_t sizeOf(uint8_t type)
{
    return fit::baseTypeSize(baseTypeOf(type));
}

/* localtime of a UTC instant, expressed as a UNIX timestamp -- what
 * activity.local_timestamp wants. Same approach as the SDK examples: convert
 * to a local tm, then treat those fields as if they were UTC. */
std::time_t epochToLocal(std::time_t utc)
{
    std::tm lt{};

#if defined(_WIN32)
    localtime_s(&lt, &utc);
#else
    localtime_r(&utc, &lt);
#endif

    /* Days since 1970 from the calendar fields, no library round-trip: the
     * watch's newlib timegm is not guaranteed and mktime would re-apply the
     * offset we are trying to measure. */
    static const int kCum[12] = {0, 31, 59, 90, 120, 151,
                                 181, 212, 243, 273, 304, 334};
    int year = lt.tm_year + 1900;
    long days = (long)(year - 1970) * 365 + ((year - 1969) / 4)
                - ((year - 1901) / 100) + ((year - 1601) / 400)
                + kCum[lt.tm_mon] + (lt.tm_mday - 1);
    bool leap = ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0);

    if (leap && lt.tm_mon > 1) {
        ++days;
    }
    return (std::time_t)days * 86400 + lt.tm_hour * 3600 + lt.tm_min * 60
           + lt.tm_sec;
}

/* The generated FB_*_DEV_LIST macros expand to FB_DEV(i) per developer field;
 * defineMessage takes an initializer_list, so these have to be literals. */
#define FB_DEV(i) fit::FitWriter::DevField{ fb_measures[i].field_num, \
                                            sizeOf(fb_measures[i].type), 0 }

}  /* namespace */

/* ---- construction ------------------------------------------------------- */

FbFitWriter::FbFitWriter(SDK::Interface::IFile &file)
    : mFit(file)
    , mOk(true)
    , mStartUtc(0)
    , mRecords(0)
    , mLaps(0)
    , mSession{}
    , mLap{}
{
}

uint32_t FbFitWriter::recordDevBytes()
{
    uint32_t n = 0;
    int i;

    for (i = 0; i < FB_RECORD_COUNT; ++i) {
        n += sizeOf(fb_measures[fb_record_idx[i]].type);
    }
    return n;
}

uint32_t FbFitWriter::lapDevBytes()
{
    uint32_t n = 0;
    int i;

    for (i = 0; i < FB_LAP_COUNT; ++i) {
        n += sizeOf(fb_measures[fb_lap_idx[i]].type);
    }
    return n;
}

uint32_t FbFitWriter::sessionDevBytes()
{
    uint32_t n = 0;
    int i;

    for (i = 0; i < FB_SESSION_COUNT; ++i) {
        n += sizeOf(fb_measures[fb_session_idx[i]].type);
    }
    return n;
}

/* ---- definitions -------------------------------------------------------- */

bool FbFitWriter::writeFieldDescription(const fb_measure_t &m)
{
    /* The name and units strings are fixed-size fields, so the definition is
     * rewritten for each measure with that measure's lengths. */
    const uint8_t nameLen  = (uint8_t)(std::strlen(m.id) + 1);
    const uint8_t unitsLen = (uint8_t)(std::strlen(m.unit) + 1);

    mFit.defineMessage(L_FIELD_DESC, fit::mesgNum(fit::MesgNum::FieldDescription),
        {fit::field::FieldDescription::DeveloperDataIndex,
         fit::field::FieldDescription::FieldDefinitionNumber,
         fit::field::FieldDescription::FitBaseTypeId,
         {fit::field::FieldDescription::kFieldNameNum, fit::BaseType::String, nameLen},
         {fit::field::FieldDescription::kUnitsNum, fit::BaseType::String, unitsLen}});

    return mFit.data(L_FIELD_DESC)
        .u8(0)
        .u8(m.field_num)
        .u8(fit::baseTypeId(baseTypeOf(m.type)))
        .str(m.id, nameLen)
        .str(m.unit, unitsLen)
        .write();
}

bool FbFitWriter::defineMessages()
{
    bool ok = true;

    /* record: the predefined metrics, then one developer field per time-based
     * measure -- the rule requires a value on every record. */
    ok = mFit.defineMessage(L_RECORD, fit::mesgNum(fit::MesgNum::Record),
        {fit::field::Record::Timestamp,
         fit::field::Record::PositionLat,
         fit::field::Record::PositionLong,
         fit::field::Record::EnhancedAltitude,
         fit::field::Record::EnhancedSpeed,
         fit::field::Record::Distance,
         fit::field::Record::HeartRate,
         fit::field::Record::Cadence,
         fit::field::Record::FractionalCadence},
        {FB_RECORD_DEV_LIST}) && ok;

    /* lap: the lap aggregates, then the additive measures' increments. Only
     * the additive ones appear here: a lap value describes that lap alone, so
     * a quantity that does not add up (a percentage) has none. */
    ok = mFit.defineMessage(L_LAP, fit::mesgNum(fit::MesgNum::Lap),
        {fit::field::Lap::MessageIndex,
         fit::field::Lap::Timestamp,
         fit::field::Lap::StartTime,
         fit::field::Lap::TotalElapsedTime,
         fit::field::Lap::TotalTimerTime,
         fit::field::Lap::TotalDistance,
         fit::field::Lap::AvgSpeed,
         fit::field::Lap::MaxSpeed,
         fit::field::Lap::AvgHeartRate,
         fit::field::Lap::MaxHeartRate,
         fit::field::Lap::TotalAscent,
         fit::field::Lap::TotalDescent},
        {FB_LAP_DEV_LIST}) && ok;

    ok = mFit.defineMessage(L_EVENT, fit::mesgNum(fit::MesgNum::Event),
        {fit::field::Event::Timestamp, fit::field::Event::EventField,
         fit::field::Event::EventType}) && ok;

    /* session: the activity summary, then every measure that owes the file one
     * value for the whole activity -- mandatory for measures that are not
     * time-based, optional (and authoritative) for the time-based ones that
     * declare it. */
    ok = mFit.defineMessage(L_SESSION, fit::mesgNum(fit::MesgNum::Session),
        {fit::field::Session::MessageIndex, fit::field::Session::Timestamp,
         fit::field::Session::StartTime, fit::field::Session::Sport,
         fit::field::Session::SubSport, fit::field::Session::TotalElapsedTime,
         fit::field::Session::TotalTimerTime, fit::field::Session::TotalDistance,
         fit::field::Session::AvgSpeed, fit::field::Session::MaxSpeed,
         fit::field::Session::AvgHeartRate, fit::field::Session::MaxHeartRate,
         fit::field::Session::TotalAscent, fit::field::Session::TotalDescent,
         fit::field::Session::NumLaps},
        {FB_SESSION_DEV_LIST}) && ok;

    ok = mFit.defineMessage(L_ACTIVITY, fit::mesgNum(fit::MesgNum::Activity),
        {fit::field::Activity::Timestamp, fit::field::Activity::TotalTimerTime,
         fit::field::Activity::LocalTimestamp,
         fit::field::Activity::NumSessions}) && ok;

    return ok;
}

/* ---- accumulators ------------------------------------------------------- */

void FbFitWriter::accumInit(Accum &a, std::time_t utc)
{
    /* Start of the session: the cumulative metrics are all still zero, so
     * there is no generator state to read yet. */
    a.hrSum = 0.0f;
    a.hrCount = 0u;
    a.hrMax = 0.0f;
    a.speedSum = 0.0f;
    a.speedCount = 0u;
    a.speedMax = 0.0f;
    a.distStart = 0.0f;
    a.ascentStart = 0.0f;
    a.descentStart = 0.0f;
    a.startUtc = utc;
}

void FbFitWriter::accumReset(Accum &a, const fb_gen_t &g, std::time_t utc)
{
    a.hrSum = 0.0f;
    a.hrCount = 0u;
    a.hrMax = 0.0f;
    a.speedSum = 0.0f;
    a.speedCount = 0u;
    a.speedMax = 0.0f;
    a.distStart = g.p.distance_m;
    a.ascentStart = g.p.ascent_m;
    a.descentStart = g.p.descent_m;
    a.startUtc = utc;
}

void FbFitWriter::accumAdd(Accum &a, const fb_gen_t &g)
{
    a.hrSum += g.p.hr_bpm;
    ++a.hrCount;
    if (g.p.hr_bpm > a.hrMax) {
        a.hrMax = g.p.hr_bpm;
    }
    a.speedSum += g.p.speed_ms;
    ++a.speedCount;
    if (g.p.speed_ms > a.speedMax) {
        a.speedMax = g.p.speed_ms;
    }
}

/* ---- values ------------------------------------------------------------- */

void FbFitWriter::putValue(fit::FitWriter::Data &d, const fb_measure_t &m,
                           float v)
{
    /* Clamp before the cast: the catalogue's envelope already keeps the value
     * in range, but a float that has drifted must not wrap an integer field
     * and pass a bad sample off as data. */
    switch (m.type) {
    case FB_T_U8:
        d.u8((uint8_t)(v < 0.0f ? 0.0f : (v > 254.0f ? 254.0f : v + 0.5f)));
        break;
    case FB_T_U16:
        d.u16((uint16_t)(v < 0.0f ? 0.0f : (v > 65534.0f ? 65534.0f : v + 0.5f)));
        break;
    case FB_T_U32:
        d.u32((uint32_t)(v < 0.0f ? 0.0f
                                  : (v > 4294967040.0f ? 4294967040.0f
                                                       : v + 0.5f)));
        break;
    case FB_T_S16:
        d.i16((int16_t)(v < -32767.0f ? -32767.0f
                                      : (v > 32766.0f ? 32766.0f
                                                      : (v >= 0.0f ? v + 0.5f
                                                                   : v - 0.5f))));
        break;
    case FB_T_S32:
        d.i32((int32_t)(v >= 0.0f ? v + 0.5f : v - 0.5f));
        break;
    default:
        d.f32(v);
        break;
    }
}

/* ---- lifecycle ---------------------------------------------------------- */

bool FbFitWriter::begin(std::time_t utc, const char *appId,
                        uint32_t serial)
{
    int i;

    mStartUtc = utc;
    mRecords = 0u;
    mLaps = 0u;

    mOk = mFit.begin(/*profileVersion=*/0);

    {
        /* Manufacturer/product identify the device, not the provenance of the
         * numbers: FitProfile.hpp reserves Development for tutorial code and
         * says to ship activity files as Una / UNA Watch, and every FIT
         * consumer keys device identity off these two fields. That the data is
         * synthetic is said in the store description and in the developer
         * field names, which is where a reader will look for it. */
        const uint8_t nameLen = (uint8_t)(std::strlen(fit::kProductName) + 1);

        mFit.defineMessage(L_FILE_ID, fit::mesgNum(fit::MesgNum::FileId),
            {fit::field::FileId::Type, fit::field::FileId::Manufacturer,
             fit::field::FileId::Product, fit::field::FileId::SerialNumber,
             fit::field::FileId::TimeCreated,
             {fit::field::FileId::kProductNameNum, fit::BaseType::String,
              nameLen}});
        mFit.data(L_FILE_ID)
            .u8((uint8_t)fit::File::Activity)
            .u16((uint16_t)fit::Manufacturer::Una)
            .u16((uint16_t)fit::Product::UnaWatch)
            .u32(serial)
            .u32(toFitTime(utc))
            .str(fit::kProductName, nameLen)
            .write();
    }

    mFit.defineMessage(L_DEV_ID, fit::mesgNum(fit::MesgNum::DeveloperDataId),
        {fit::field::DeveloperDataId::ApplicationId,
         fit::field::DeveloperDataId::DeveloperDataIndex});
    {
        uint8_t id[16];

        /* The App ID is 16 hex characters; the examples copy those characters
         * rather than the parsed number, so a reader can compare the field
         * with the manifest's `id` as text. */
        std::memset(id, 0, sizeof(id));
        if (appId) {
            std::strncpy((char *)id, appId, sizeof(id));
        }
        mFit.data(L_DEV_ID).bytes(id, sizeof(id)).u8(0).write();
    }

    /* One field_description per measure, including the per-lap ones: a reader
     * that ignores lap developer fields still learns the measure exists. */
    for (i = 0; i < FB_MEASURE_COUNT; ++i) {
        writeFieldDescription(fb_measures[i]);
    }

    defineMessages();

    accumInit(mSession, utc);
    accumInit(mLap, utc);

    addEvent(utc, /*start=*/true);

    mOk = mOk && mFit.ok();
    return mOk;
}

bool FbFitWriter::addEvent(std::time_t utc, bool start)
{
    return mFit.data(L_EVENT)
        .u32(toFitTime(utc))
        .u8((uint8_t)fit::Event::Timer)
        .u8((uint8_t)(start ? fit::EventType::Start : fit::EventType::Stop))
        .write();
}

bool FbFitWriter::addRecord(const fb_gen_t &g, std::time_t utc)
{
    SDK::FitRecordCadence::CadenceFitFields cad =
        SDK::FitRecordCadence::encodeCadenceSpm(g.p.cadence_spm);
    fit::FitWriter::Data d = mFit.data(L_RECORD);
    int i;

    d.u32(toFitTime(utc))
     .i32(toSemicircles(g.p.lat))
     .i32(toSemicircles(g.p.lon))
     .u32((uint32_t)((g.p.altitude_m + 500.0f) * 5.0f))   /* scale 5, off 500 */
     .u32((uint32_t)(g.p.speed_ms * 1000.0f))             /* mm/s             */
     .u32((uint32_t)(g.p.distance_m * 100.0f))            /* cm               */
     .u8((uint8_t)(g.p.hr_bpm + 0.5f))
     .u8(cad.cadence)
     .u8(cad.fractionalCadence);

    for (i = 0; i < FB_RECORD_COUNT; ++i) {
        int idx = fb_record_idx[i];

        putValue(d, fb_measures[idx], fb_gen_value(&g, idx));
    }

    if (!d.write()) {
        mOk = false;
        return false;
    }

    accumAdd(mSession, g);
    accumAdd(mLap, g);
    ++mRecords;
    return true;
}

bool FbFitWriter::addLap(const fb_gen_t &g, std::time_t utc)
{
    float dist;
    float ascent;
    float descent;
    uint32_t elapsed;
    int i;

    /* A lap with no time in it is not a lap: two presses in the same second,
     * or a press in the same second as the automatic lap, would otherwise
     * spend a message_index on a row of zeroes. */
    if (utc <= mLap.startUtc) {
        return true;
    }

    dist = g.p.distance_m - mLap.distStart;
    ascent = g.p.ascent_m - mLap.ascentStart;
    descent = g.p.descent_m - mLap.descentStart;
    elapsed = (uint32_t)(utc - mLap.startUtc);

    fit::FitWriter::Data d = mFit.data(L_LAP);

    d.u16(mLaps)
     .u32(toFitTime(utc))
     .u32(toFitTime(mLap.startUtc))
     .u32(elapsed * 1000u)
     .u32(elapsed * 1000u)
     .u32((uint32_t)(dist * 100.0f))
     .u16((uint16_t)(mLap.speedCount ? mLap.speedSum / (float)mLap.speedCount
                                          * 1000.0f
                                     : 0.0f))
     .u16((uint16_t)(mLap.speedMax * 1000.0f))
     .u8((uint8_t)(mLap.hrCount ? mLap.hrSum / (float)mLap.hrCount + 0.5f : 0.0f))
     .u8((uint8_t)(mLap.hrMax + 0.5f))
     .u16((uint16_t)(ascent > 0.0f ? ascent : 0.0f))
     .u16((uint16_t)(descent > 0.0f ? descent : 0.0f));

    /* The increment each additive measure accrued during the lap that just
     * ended -- never its running total. */
    for (i = 0; i < FB_LAP_COUNT; ++i) {
        int idx = fb_lap_idx[i];

        putValue(d, fb_measures[idx], fb_gen_lap_value(&g, idx));
    }

    if (!d.write()) {
        mOk = false;
        return false;
    }

    ++mLaps;
    accumReset(mLap, g, utc);
    return true;
}

bool FbFitWriter::finish(fb_gen_t &g, std::time_t utc)
{
    uint32_t elapsed;
    bool ok;

    /* A lap is always open, so the tail of the activity is never lost -- and
     * the generator closes it first, so the increments in the file add up to
     * the session totals written below. */
    if (utc > mLap.startUtc) {
        fb_gen_lap(&g);
        addLap(g, utc);
    }

    addEvent(utc, /*start=*/false);

    elapsed = (uint32_t)(utc - mStartUtc);

    {
        fit::FitWriter::Data d = mFit.data(L_SESSION);
        int i;

        d.u16(0)
         .u32(toFitTime(utc))
         .u32(toFitTime(mStartUtc))
         .u8((uint8_t)fit::Sport::Generic)
         .u8((uint8_t)fit::SubSport::Generic)
         .u32(elapsed * 1000u)
         .u32(elapsed * 1000u)
         .u32((uint32_t)(g.p.distance_m * 100.0f))
         .u16((uint16_t)(mSession.speedCount
                             ? mSession.speedSum / (float)mSession.speedCount
                                   * 1000.0f
                             : 0.0f))
         .u16((uint16_t)(mSession.speedMax * 1000.0f))
         .u8((uint8_t)(mSession.hrCount
                           ? mSession.hrSum / (float)mSession.hrCount + 0.5f
                           : 0.0f))
         .u8((uint8_t)(mSession.hrMax + 0.5f))
         .u16((uint16_t)g.p.ascent_m)
         .u16((uint16_t)g.p.descent_m)
         .u16(mLaps);

        /* One value for the whole activity per declaring measure. Written
         * after the final lap, so an additive measure's total is exactly the
         * sum of the increments the file already carries. */
        for (i = 0; i < FB_SESSION_COUNT; ++i) {
            int idx = fb_session_idx[i];

            putValue(d, fb_measures[idx], fb_gen_session_value(&g, idx));
        }

        ok = d.write();
    }

    ok = mFit.data(L_ACTIVITY)
        .u32(toFitTime(utc))
        .u32(elapsed * 1000u)
        .u32(toFitTime(epochToLocal(utc)))
        .u16(1)
        .write() && ok;

    ok = mFit.finish() && ok;
    mOk = mOk && ok && mFit.ok();
    return mOk;
}
