/* fb_msg.hpp -- the two app-private messages FruitBench uses.
 *
 * MessageTypes.hpp reserves 0x0000_0000-0x0000_FFFF for messages exchanged
 * between an app's own GUI and Service processes, which is the whole traffic
 * here: the screen sends commands, the recorder sends a snapshot a second.
 *
 * Both carry plain data and know nothing about the kernel -- SDK::send_msg
 * allocates, sends and releases them.
 */
#ifndef FB_MSG_HPP
#define FB_MSG_HPP

#include "SDK/Messages/MessageBase.hpp"

extern "C" {
#include "fb_snap.h"
}

namespace FbMsg {

constexpr SDK::MessageType::Type COMMAND  = 0x00000101;  /* GUI -> Service */
constexpr SDK::MessageType::Type SNAPSHOT = 0x00000102;  /* Service -> GUI */

/* One button press, translated. */
struct Command : public SDK::MessageBase {
    uint32_t arg;
    uint8_t  cmd;          /* fb_cmd_t */
    uint8_t  pad[3];

    Command()
        : SDK::MessageBase(COMMAND)
        , arg(0)
        , cmd(0)
        , pad{}
    {
    }

    Command(uint8_t command, uint32_t argument)
        : Command()
    {
        cmd = command;
        arg = argument;
    }
};

/* The recorder's once-a-second report. */
struct Snapshot : public SDK::MessageBase {
    fb_snapshot_t snap;

    Snapshot()
        : SDK::MessageBase(SNAPSHOT)
        , snap{}
    {
    }

    explicit Snapshot(const fb_snapshot_t &s)
        : Snapshot()
    {
        snap = s;
    }
};

}  /* namespace FbMsg */

#endif /* FB_MSG_HPP */
