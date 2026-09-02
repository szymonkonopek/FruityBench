/* Service.hpp -- FruitBench's recorder process.
 *
 * The SDK's service entry point (Libs/Source/AppSystem/EntryPoint/Service/
 * main.cpp) #includes this header, placement-news the object into static
 * storage and calls run(), so the class must be complete here and take
 * SDK::Kernel&.
 *
 * Everything that ends up in the file lives here: the generator, the FIT
 * writer, the lap schedule and the clock. The screen is a client -- it sends
 * commands and receives one snapshot a second -- which is what lets a
 * recording carry on while the GUI is suspended.
 */
#ifndef FB_SERVICE_HPP
#define FB_SERVICE_HPP

#include <ctime>
#include <memory>

#include "SDK/Kernel/Kernel.hpp"
#include "SDK/Fit/RecordingMarker.hpp"

#include "fb_fit.hpp"

extern "C" {
#include "fb_gen.h"
#include "fb_snap.h"
}

class Service
{
public:
    explicit Service(SDK::Kernel &kernel);
    ~Service() = default;

    void run();

private:
    /* commands from the screen */
    void onCommand(uint8_t cmd, uint32_t arg);

    /* recording lifecycle */
    bool startRecording();
    void stopRecording(bool save);
    void tick();                     /* called from the loop, drives the clock */
    void writeDueRecords();
    void publish();                  /* one snapshot to the GUI               */
    void notifyNewActivity();        /* tell the kernel a .fit appeared       */

    bool openActivityFile(std::time_t utc);

    SDK::Kernel                          &mKernel;
    SDK::Fit::RecordingMarker             mMarker;

    std::unique_ptr<SDK::Interface::IFile> mFile;
    std::unique_ptr<FbFitWriter>           mFit;

    fb_gen_t     mGen;
    fb_snapshot_t mSnap;

    /* clock: activity seconds are derived from real milliseconds and the rate,
     * so a pause is simply a stretch of real time that is not counted. */
    uint32_t     mRunMsBase;         /* kernel ms at the last resume          */
    uint32_t     mTBase;             /* activity seconds at the last resume   */
    uint32_t     mLastPublishMs;
    uint32_t     mLastFlushMs;
    uint32_t     mNextLapT;          /* activity second of the next auto lap  */
    uint32_t     mLapInterval;
    std::time_t  mUtcStart;          /* UTC of activity second zero           */
    char         mPath[128];
    bool         mMarkerArmed;       /* the crash marker exists for this file */
};

#endif /* FB_SERVICE_HPP */
