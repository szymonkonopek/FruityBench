/* fb_plat.h -- the whole surface between FruitBench's screen and the machine.
 *
 * Two implementations:
 *   src/fb_una_platform.cpp   the watch (UNA SDK: frame tick, panel, buttons,
 *                             and the messages to and from the recorder)
 *   host/fb_host.c            a laptop (a recorder simulated in-process, and
 *                             a PPM dump), used to check the layout and to
 *                             render the store previews
 *
 * fb_ui.c is plain C and knows neither -- the same split PEEK and UOOM use.
 */
#ifndef FB_PLAT_H
#define FB_PLAT_H

#include <stdint.h>

#include "fb_snap.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Block until the next kernel frame tick (~10 Hz on the watch); also where
 * STOP, SUSPEND and RESUME and the recorder's snapshots are serviced. */
void fb_plat_frame_wait(void);

/* Hand the finished 240x240 ABGR2222 buffer to the panel. */
void fb_plat_present(const uint8_t *fb);

/* Keep the backlight on while the app is in the foreground. */
void fb_plat_keep_awake(void);

/* Pop one raw button code (kernel ASCII press/release/click), 0 when empty.
 * Drain fully each frame. */
int fb_plat_poll_key(uint8_t *code);

/* Milliseconds since boot, for hold and auto-repeat timing. */
uint32_t fb_plat_ticks_ms(void);

/* Non-zero once the kernel asked us to stop. */
int fb_plat_should_quit(void);

/* End the process; does not return. */
void fb_plat_exit(void);

/* A line to the kernel log. */
void fb_plat_log(const char *msg);

/* Send one command to the recorder (fb_cmd_t plus its argument). */
void fb_plat_command(int cmd, uint32_t arg);

/* Copy the most recent snapshot from the recorder. Returns 1 if a new one has
 * arrived since the last call, 0 if `out` is simply the last known state. */
int fb_plat_snapshot(fb_snapshot_t *out);

#ifdef __cplusplus
}
#endif

#endif /* FB_PLAT_H */
