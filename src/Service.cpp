/* Service.cpp -- see Service.hpp. */

#include <cstdio>
#include <cstring>

#include "SDK/Messages/CommandMessages.hpp"
#include "SDK/Messages/MessageGuard.hpp"
#include "SDK/UnaLogger/Logger.h"

#include "Service.hpp"
#include "fb_msg.hpp"

namespace {

/* The directory the kernel scans for activity files. Relative to the app's
 * own sandbox, as everywhere else in the SDK. */
constexpr const char *kActivityDir = "Activity";

/* How often the loop wakes when nothing arrives. Fast enough that a 60x
 * recording still gets its records written in even batches, cheap enough that
 * an idle app is not spinning. */
constexpr uint32_t kPollMs = 50u;

/* One snapshot to the screen per second, and a flush plus marker update every
 * half minute of real time -- not of activity time, or a 60x recording would
 * flush every half second. */
constexpr uint32_t kPublishMs = 1000u;
constexpr uint32_t kFlushMs   = 30000u;

/* Auto lap in live recording. Fast recordings divide their target instead, so
 * that a 15 minute and a 60 minute session both come out with useful laps. */
constexpr uint32_t kLiveLapSec = 300u;
constexpr uint32_t kFastLaps   = 8u;

/* Never write more than this many records in one pass through the loop: at
 * 60x a stall would otherwise let the backlog grow without the message queue
 * ever getting a turn. */
constexpr uint32_t kMaxRecordsPerPass = 90u;

/* Fastest fast-forward the recorder accepts: the screen offers 1, 10 and 60. */
constexpr uint32_t kRateMax = 60u;

#ifndef APP_ID
#define APP_ID "0000000000000000"
#endif

}  /* namespace */

Service::Service(SDK::Kernel &kernel)
    : mKernel(kernel)
    , mMarker(kernel.fs, kActivityDir)
    , mFile()
    , mFit()
    , mGen{}
    , mSnap{}
    , mRunMsBase(0u)
    , mTBase(0u)
    , mLastPublishMs(0u)
    , mLastFlushMs(0u)
    , mNextLapT(0u)
    , mLapInterval(kLiveLapSec)
    , mUtcStart(0)
    , mPath{}
    , mMarkerArmed(false)
{
    mSnap.state = FB_STATE_IDLE;
    mSnap.rate  = 1u;
    mSnap.target = 0u;
    mSnap.seed  = fb_gen_make_seed((uint32_t)std::time(nullptr),
                                   mKernel.sys.getTimeMs(), 0u);
    fb_gen_init(&mGen, mSnap.seed);
}

/* ---- files -------------------------------------------------------------- */

bool Service::openActivityFile(std::time_t utc)
{
    char dir[64];
    std::tm lt{};
    int len;

#if defined(_WIN32)
    localtime_s(&lt, &utc);
#else
    localtime_r(&utc, &lt);
#endif

    /* Activity/YYYYMM/activity_YYYYMMDDThhmmss.fit -- the layout the SDK's
     * own activity apps use, and what the BLE file transfer service expects
     * to find under the app's directory. */
    len = snprintf(dir, sizeof(dir), "%s/%04u%02u/", kActivityDir,
                   (unsigned)(lt.tm_year + 1900), (unsigned)(lt.tm_mon + 1));
    if (len <= 0 || !mKernel.fs.mkdir(dir)) {
        LOG_ERROR("FB: cannot create %s\n", dir);
        return false;
    }

    snprintf(mPath, sizeof(mPath),
             "%sactivity_%04u%02u%02uT%02u%02u%02u.fit", dir,
             (unsigned)(lt.tm_year + 1900), (unsigned)(lt.tm_mon + 1),
             (unsigned)lt.tm_mday, (unsigned)lt.tm_hour,
             (unsigned)lt.tm_min, (unsigned)lt.tm_sec);

    mFile = mKernel.fs.file(mPath);
    if (!mFile || !mFile->open(/*wMode=*/true, /*override=*/true)) {
        LOG_ERROR("FB: cannot open %s\n", mPath);
        mFile.reset();
        return false;
    }
    return true;
}

/* ---- recording ---------------------------------------------------------- */

bool Service::startRecording()
{
    std::time_t now = std::time(nullptr);
    uint32_t ms = mKernel.sys.getTimeMs();

    /* A fresh seed for every session: the point of the benchmark is that two
     * recordings never look alike. */
    mSnap.seed = fb_gen_make_seed((uint32_t)now, ms, mSnap.seed);
    fb_gen_init(&mGen, mSnap.seed);

    /* Where activity second zero sits on the real clock. A fast recording is
     * a synthetic *past* activity: it is backdated by its target so the file
     * ends at about the moment the watch finishes writing it, instead of
     * claiming timestamps that are still in the future. */
    mUtcStart = now;
    if (mSnap.rate > 1u && mSnap.target > 0u) {
        mUtcStart = now - (std::time_t)mSnap.target;
    }

    /* Clear the counters before the first thing that can fail: a FAILED
     * summary showing the previous run's time, records and file name would
     * be worse than no summary at all. */
    mSnap.t = 0u;
    mSnap.laps = 0u;
    mSnap.records = 0u;
    mSnap.bytes = 0u;
    mSnap.file[0] = '\0';
    mMarkerArmed = false;

    if (!openActivityFile(mUtcStart)) {
        mSnap.state = FB_STATE_ERROR;
        mSnap.err = FB_ERR_OPEN;
        return false;
    }

    /* The SDK replaces global operator new with a noexcept malloc, so an
     * exhausted heap arrives as a null pointer, not an exception. */
    mFit.reset(new FbFitWriter(*mFile));
    if (!mFit) {
        LOG_ERROR("FB: no memory for the FIT writer\n");
        mFile->close();
        mFile->remove();
        mFile.reset();
        mSnap.state = FB_STATE_ERROR;
        mSnap.err = FB_ERR_WRITE;
        return false;
    }

    if (!mFit->begin(mUtcStart, APP_ID, mSnap.seed)) {
        LOG_ERROR("FB: FIT header failed\n");
        /* Leave nothing half-open: the next START would otherwise replace a
         * live file handle without closing it. */
        mFit.reset();
        mFile->close();
        mFile->remove();
        mFile.reset();
        mSnap.state = FB_STATE_ERROR;
        mSnap.err = FB_ERR_WRITE;
        return false;
    }

    /* The marker is what makes a power loss recoverable: without it,
     * FitWriter::recover() cannot find the file. Both steps are checked and
     * both failures are logged, and writeDueRecords retries later -- a
     * recording that silently has no marker would lose everything. */
    if (!mFile->flush()) {
        LOG_ERROR("FB: first flush failed\n");
    } else if (!mMarker.write(mFile->getPath(),
                              (uint32_t)mFile->getPosition())) {
        LOG_ERROR("FB: could not write the recording marker\n");
    } else {
        mMarkerArmed = true;
    }

    mRunMsBase = ms;
    mTBase = 0u;
    mLastFlushMs = ms;
    mLapInterval = (mSnap.rate > 1u && mSnap.target >= kFastLaps)
                       ? mSnap.target / kFastLaps
                       : kLiveLapSec;
    mNextLapT = mLapInterval;

    mSnap.err = FB_ERR_NONE;
    mSnap.state = FB_STATE_REC;
    {
        /* Only the name: it is 28 characters, the directory is fixed, and
         * the snapshot travels through the kernel message pool every
         * second, so every byte in it is worth arguing about. */
        const char *base = std::strrchr(mPath, '/');

        std::snprintf(mSnap.file, sizeof(mSnap.file), "%.31s",
                      base ? base + 1 : mPath);
    }

    LOG_INFO("FB: recording seed=%08lX rate=%ux target=%us -> %s\n",
             (unsigned long)mSnap.seed, (unsigned)mSnap.rate,
             (unsigned)mSnap.target, mPath);
    return true;
}

void Service::stopRecording(bool save)
{
    bool ok = false;

    if (!mFit || !mFile) {
        mSnap.state = FB_STATE_IDLE;
        return;
    }

    mSnap.state = FB_STATE_SAVING;
    publish();

    if (save) {
        ok = mFit->finish(mGen, mUtcStart + (std::time_t)mSnap.t);
        mSnap.records = mFit->records();
        mSnap.laps = mFit->laps();
    }
    mFit.reset();

    if (save) {
        ok = mFile->flush() && ok;
        mSnap.bytes = (uint32_t)mFile->size();
        /* The close is what registers the activity with the kernel, so it is
         * the last thing to go wrong and the first thing to check. */
        ok = mFile->close() && ok;
    } else {
        mFile->close();
        mFile->remove();
    }
    mFile.reset();

    if (save && ok) {
        mMarker.remove();
        notifyNewActivity();
        mSnap.state = FB_STATE_SAVED;
        mSnap.err = FB_ERR_NONE;
        LOG_INFO("FB: saved %s (%u records, %u laps, %u bytes)\n", mPath,
                 (unsigned)mSnap.records, (unsigned)mSnap.laps,
                 (unsigned)mSnap.bytes);
    } else if (save) {
        mSnap.state = FB_STATE_ERROR;
        mSnap.err = FB_ERR_FINISH;
        LOG_ERROR("FB: failed to finalize %s\n", mPath);
    } else {
        mMarker.remove();
        mSnap.state = FB_STATE_IDLE;
        LOG_INFO("FB: discarded %s\n", mPath);
    }
}

void Service::writeDueRecords()
{
    uint32_t ms = mKernel.sys.getTimeMs();
    uint32_t elapsed = ms - mRunMsBase;
    /* Activity seconds that should exist by now. */
    uint32_t due = mTBase + (uint32_t)((uint64_t)elapsed * mSnap.rate / 1000u);
    uint32_t written = 0u;

    if (mSnap.target > 0u && due > mSnap.target) {
        due = mSnap.target;
    }

    while (mSnap.t < due && written < kMaxRecordsPerPass) {
        uint32_t t = mSnap.t + 1u;

        fb_gen_step(&mGen, t);
        if (!mFit->addRecord(mGen, mUtcStart + (std::time_t)t)) {
            /* Throw the file away -- a FIT the encoder gave up on mid-record
             * is not worth syncing -- but report the failure rather than the
             * discard: stopRecording() ends at IDLE, and a benchmark that
             * hides a write error is useless. */
            stopRecording(/*save=*/false);
            mSnap.state = FB_STATE_ERROR;
            mSnap.err = FB_ERR_WRITE;
            publish();
            return;
        }
        mSnap.t = t;
        ++written;

        if (t >= mNextLapT) {
            /* Close the lap in the generator first: that is where each
             * additive measure draws the increment the lap message then
             * writes. */
            fb_gen_lap(&mGen);
            mFit->addLap(mGen, mUtcStart + (std::time_t)t);
            mNextLapT = t + mLapInterval;
            mSnap.laps = mFit->laps();
        }
    }

    mSnap.records = mFit->records();

    if (ms - mLastFlushMs >= kFlushMs) {
        mLastFlushMs = ms;
        if (mFile->flush()) {
            uint32_t pos = (uint32_t)mFile->getPosition();

            /* update() does nothing until a write() has established the
             * marker, so a start that failed to arm it retries here. */
            if (mMarkerArmed) {
                mMarker.update(pos);
            } else if (mMarker.write(mFile->getPath(), pos)) {
                mMarkerArmed = true;
            }
            mSnap.bytes = (uint32_t)mFile->size();
        }
    }

    if (mSnap.target > 0u && mSnap.t >= mSnap.target) {
        LOG_INFO("FB: target %us reached\n", (unsigned)mSnap.target);
        stopRecording(/*save=*/true);
    }
}

/* ---- reporting ---------------------------------------------------------- */

void Service::publish()
{
    int i;

    for (i = 0; i < FB_PAGE_SIZE; ++i) {
        int idx = (int)mSnap.page * FB_PAGE_SIZE + i;

        mSnap.val[i] = (idx < FB_MEASURE_COUNT) ? fb_gen_value(&mGen, idx)
                                                : 0.0f;
    }
    mSnap.dist_m = mGen.p.distance_m;
    mSnap.speed_ms = mGen.p.speed_ms;
    mSnap.hr_bpm = mGen.p.hr_bpm;
    mSnap.alt_m = mGen.p.altitude_m;
    mSnap.steps = mGen.p.steps;

    /* A snapshot that cannot be allocated is not fatal -- the recording is
     * unaffected -- but it would leave the screen showing stale values with
     * no explanation, so say it once. */
    if (!SDK::send_msg<FbMsg::Snapshot>(mKernel, mSnap)) {
        static bool sWarned = false;

        if (!sWarned) {
            sWarned = true;
            LOG_ERROR("FB: cannot send a %u-byte snapshot to the screen\n",
                      (unsigned)sizeof(FbMsg::Snapshot));
        }
    }
}

void Service::notifyNewActivity()
{
    auto *msg = mKernel.comm.allocateMessage<SDK::Message::CommandAppNewActivity>();

    if (!msg) {
        LOG_ERROR("FB: no message for the new-activity notification\n");
        return;
    }
    mKernel.comm.sendMessage(msg);
    mKernel.comm.releaseMessage(msg);
}

/* ---- commands ----------------------------------------------------------- */

void Service::onCommand(uint8_t cmd, uint32_t arg)
{
    switch (cmd) {

    case FB_CMD_START:
        if (mSnap.state == FB_STATE_IDLE || mSnap.state == FB_STATE_SAVED
            || mSnap.state == FB_STATE_ERROR) {
            startRecording();
        }
        break;

    case FB_CMD_PAUSE:
        if (mSnap.state == FB_STATE_REC) {
            /* Freeze the activity clock: the elapsed real time up to now is
             * banked, and the next resume starts counting from zero again. */
            mTBase = mSnap.t;
            mSnap.state = FB_STATE_PAUSED;
        }
        break;

    case FB_CMD_RESUME:
        if (mSnap.state == FB_STATE_PAUSED) {
            mRunMsBase = mKernel.sys.getTimeMs();
            mTBase = mSnap.t;
            mSnap.state = FB_STATE_REC;
        }
        break;

    case FB_CMD_LAP:
        if (mFit && (mSnap.state == FB_STATE_REC
                     || mSnap.state == FB_STATE_PAUSED)) {
            fb_gen_lap(&mGen);
            mFit->addLap(mGen, mUtcStart + (std::time_t)mSnap.t);
            mNextLapT = mSnap.t + mLapInterval;
            mSnap.laps = mFit->laps();
        }
        break;

    case FB_CMD_STOP:
        if (mSnap.state == FB_STATE_REC || mSnap.state == FB_STATE_PAUSED) {
            stopRecording(/*save=*/true);
        }
        break;

    case FB_CMD_DISCARD:
        if (mSnap.state == FB_STATE_REC || mSnap.state == FB_STATE_PAUSED) {
            stopRecording(/*save=*/false);
        }
        break;

    case FB_CMD_SET_RATE:
        if (mSnap.state == FB_STATE_IDLE || mSnap.state == FB_STATE_SAVED) {
            /* Clamp before the cast, not after: rate 0 stops the activity
             * clock dead, and 256 truncates to exactly that. */
            mSnap.rate = (uint8_t)((arg == 0u || arg > kRateMax) ? 1u : arg);
        }
        break;

    case FB_CMD_SET_TARGET:
        if (mSnap.state == FB_STATE_IDLE || mSnap.state == FB_STATE_SAVED) {
            mSnap.target = arg;
        }
        break;

    case FB_CMD_SET_PAGE:
        mSnap.page = (uint8_t)(arg % FB_PAGE_COUNT);
        break;

    case FB_CMD_RESET:
        if (mSnap.state == FB_STATE_SAVED || mSnap.state == FB_STATE_ERROR) {
            mSnap.state = FB_STATE_IDLE;
            mSnap.err = FB_ERR_NONE;
            mSnap.t = 0u;
            mSnap.records = 0u;
            mSnap.laps = 0u;
            mSnap.file[0] = '\0';
        }
        break;

    default:
        break;
    }

    publish();
}

/* ---- the loop ----------------------------------------------------------- */

void Service::tick()
{
    uint32_t ms = mKernel.sys.getTimeMs();

    if (mSnap.state == FB_STATE_REC && mFit && mFile) {
        writeDueRecords();
    }

    if (ms - mLastPublishMs >= kPublishMs) {
        mLastPublishMs = ms;
        publish();
    }
}

void Service::run()
{
    SDK::MessageBase *msg = nullptr;

    /* An activity interrupted by a power loss is finalised before anything
     * new is written, and the kernel is told about the file that appeared. */
    {
        SDK::Fit::RecordingMarker::RecoverResult res = mMarker.recover();

        if (res.recovered) {
            LOG_INFO("FB: recovered an interrupted activity\n");
            notifyNewActivity();
        }
    }

    for (;;) {
        if (mKernel.comm.getMessage(msg, kPollMs)) {
            switch (msg->getType()) {

            case SDK::MessageType::COMMAND_APP_STOP:
                /* The kernel is taking the app down: save what exists rather
                 * than leaving a half-written file for the recovery path. */
                if (mSnap.state == FB_STATE_REC
                    || mSnap.state == FB_STATE_PAUSED) {
                    stopRecording(/*save=*/true);
                }
                mKernel.comm.releaseMessage(msg);
                return;

            case SDK::MessageType::COMMAND_APP_NOTIF_GUI_RUN:
                /* The screen came up: give it something to draw at once
                 * rather than after the next publish tick. */
                publish();
                break;

            case SDK::MessageType::COMMAND_APP_NOTIF_GUI_STOP:
                /* Only a notification. The recorder stays resident either
                 * way, as Running and HRMonitor do: a recording must outlive
                 * the screen, and after one has finished the summary has to
                 * survive long enough for the screen to come back and show
                 * it. The kernel ends this process with COMMAND_APP_STOP. */
                break;

            case FbMsg::COMMAND: {
                auto *c = static_cast<FbMsg::Command *>(msg);

                onCommand(c->cmd, c->arg);
                break;
            }

            default:
                break;
            }

            if (msg->needsResponse()) {
                mKernel.comm.sendResponse(msg);
            }
            mKernel.comm.releaseMessage(msg);
        }

        tick();
    }
}
