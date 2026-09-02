/* fb_una_platform.cpp -- fb_plat for the UNA Watch.
 *
 * Trimmed from PEEK's platform layer -- frame pump, panel push, button queue,
 * backlight -- plus the two calls this app adds: commands out to the recorder
 * and snapshots in from it.
 */

#include <cstring>

#include "SDK/Kernel/Kernel.hpp"
#include "SDK/Kernel/KernelProviderGUI.hpp"
#include "SDK/Messages/CommandMessages.hpp"
#include "SDK/Messages/MessageGuard.hpp"
#include "SDK/Port/TouchGFX/TouchGFXCommandProcessor.hpp"

#include "fb_msg.hpp"

extern "C" {
#include "fb_plat.h"
}

namespace {

const SDK::Kernel &kernel()
{
    return SDK::KernelProviderGUI::GetInstance().getKernel();
}

SDK::TouchGFXCommandProcessor &cmd()
{
    return SDK::TouchGFXCommandProcessor::GetInstance();
}

bool gQuit;
bool gSuspended;

/* The recorder's latest report, filled in by the message handler in
 * FbMain.cpp and read by the screen once a frame. */
fb_snapshot_t gSnap;
bool          gSnapFresh;

/* waitForFrameTick only queues application-specific messages; nothing in the
 * SDK drains them, so an app that owns its own loop must call the drain
 * itself -- which is how the snapshots get delivered. */
void pumpOneTick()
{
    cmd().waitForFrameTick();
    cmd().callCustomMessageHandler();
}

}  /* namespace */

/* ---- called from FbMain.cpp -------------------------------------------- */

void fb_una_set_quit(int q)      { gQuit = (q != 0); }
void fb_una_set_suspended(int s) { gSuspended = (s != 0); }

void fb_una_set_snapshot(const fb_snapshot_t &s)
{
    gSnap = s;
    gSnapFresh = true;
}

/* ---- frame pacing / display / input ------------------------------------- */

extern "C" void fb_plat_frame_wait(void)
{
    pumpOneTick();
}

extern "C" int fb_plat_should_quit(void)
{
    return gQuit ? 1 : 0;
}

extern "C" void fb_plat_exit(void)
{
    gQuit = true;
    kernel().sys.exit(0);
    for (;;) {
    }
}

extern "C" void fb_plat_present(const uint8_t *fb)
{
    if (!gSuspended) {
        cmd().writeDisplayFrameBuffer(fb);
    }
}

extern "C" void fb_plat_keep_awake(void)
{
    static bool sArmed;

    if (sArmed) {
        return;
    }
    sArmed = true;

    if (auto msg = SDK::make_msg<SDK::Message::RequestBacklightSet>(kernel())) {
        msg->brightness       = 100;
        msg->autoOffTimeoutMs = 0;   /* stay lit while the screen is up */
        msg.send(100);
    }
}

extern "C" int fb_plat_poll_key(uint8_t *code)
{
    uint8_t k = 0;

    if (cmd().getKeySample(k)) {
        *code = k;
        return 1;
    }
    return 0;
}

extern "C" uint32_t fb_plat_ticks_ms(void)
{
    return kernel().sys.getTimeMs();
}

extern "C" void fb_plat_log(const char *msg)
{
    kernel().log.printf("%s", msg);
}

/* ---- the recorder ------------------------------------------------------- */

extern "C" void fb_plat_command(int cmd_id, uint32_t arg)
{
    /* Fire and forget: the recorder answers with a snapshot, which is the
     * only acknowledgement the screen needs. */
    SDK::send_msg<FbMsg::Command>(kernel(), (uint8_t)cmd_id, arg);
}

extern "C" int fb_plat_snapshot(fb_snapshot_t *out)
{
    int fresh = gSnapFresh ? 1 : 0;

    gSnapFresh = false;
    std::memcpy(out, &gSnap, sizeof(*out));
    return fresh;
}
