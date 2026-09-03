/* FbMain.cpp -- the GUI process entry point.
 *
 * The GUI process without a TouchGFX Designer project: do not link the SDK's
 * TouchGFX GUI source group (it owns `main` and does not compile without a
 * Designer project), keep UNA_SDK_SOURCES_COMMON for
 * startup/system.cpp/KernelBuilder, and compile the one TouchGFX-free file
 * that carries the kernel-side GUI protocol -- TouchGFXCommandProcessor.cpp
 * -- by path. This file then supplies main() itself.
 *
 * An activity app must still ship a GUI ELF (the packer only makes it optional
 * for glances), so this is the whole screen half of FruitBench: a framebuffer,
 * the button queue, and the recorder's snapshots.
 */

#include "SDK/Kernel/Kernel.hpp"
#include "SDK/Kernel/KernelBuilder.hpp"
#include "SDK/Kernel/KernelProviderGUI.hpp"
#include "SDK/Interfaces/IKernel.hpp"
#include "SDK/UnaLogger/Logger.h"

/* TouchGFX-free despite the name; brings in the lifecycle/message interfaces. */
#include "SDK/Port/TouchGFX/TouchGFXCommandProcessor.hpp"

#include "fb_msg.hpp"

extern "C" {
#include "fb_ui.h"
}

/* fb_una_platform.cpp */
void fb_una_set_quit(int q);
void fb_una_set_suspended(int s);
void fb_una_set_snapshot(const fb_snapshot_t &s);

/* Patched in by the loader; declared in system.cpp's .sys_calls section. */
extern const SDK::Interface::IKernel *gIKernel;

namespace {

class FbAppCb : public SDK::Interface::IGuiLifeCycleCallback,
                public SDK::Interface::ICustomMessageHandler
{
public:
    void onStart()   override {}
    void onStop()    override { fb_una_set_quit(1); }
    void onSuspend() override { fb_una_set_suspended(1); }
    void onResume()  override { fb_una_set_suspended(0); }
    void onFrame()   override {}

    bool customMessageHandler(SDK::MessageBase *msg) override
    {
        if (msg && msg->getType() == FbMsg::SNAPSHOT) {
            fb_una_set_snapshot(static_cast<FbMsg::Snapshot *>(msg)->snap);
            return true;
        }
        /* Anything else is not ours: returning false lets the SDK mark it
         * FAIL rather than silently swallowing it. */
        return false;
    }
};

}  /* namespace */

int main()
{
    SDK::Kernel kernel = SDK::KernelBuilder::make(gIKernel);

    SDK::KernelProviderGUI::CreateInstance(&kernel);
    Logger_init(kernel.log);

    static FbAppCb cb;
    auto &cmd = SDK::TouchGFXCommandProcessor::GetInstance();

    cmd.setAppLifeCycleCallback(&cb);
    cmd.setCustomMessageHandler(&cb);

    fb_ui_run();

    kernel.sys.exit(0);
    for (;;) {
    }
}
