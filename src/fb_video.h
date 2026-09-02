/* fb_video.h -- the 240x240 ABGR2222 panel buffer and colour packing.
 *
 * Pure C, no platform dependency, so the host harness draws with the exact
 * same code the watch does.
 */
#ifndef FB_VIDEO_H
#define FB_VIDEO_H

#include <stdint.h>

#define FB_PANEL_W      240
#define FB_PANEL_H      240
#define FB_PANEL_BYTES  (FB_PANEL_W * FB_PANEL_H)

/* The buffer handed to the panel each frame. */
uint8_t *fb_present_buffer(void);

/* Pack a 24-bit colour into one opaque ABGR2222 pixel. */
uint8_t fb_pack_rgb(uint8_t r, uint8_t g, uint8_t b);

/* Expand a pixel back to RGB -- host harness only, for PPM output. */
void fb_unpack_rgb(uint8_t px, uint8_t *r, uint8_t *g, uint8_t *b);

/* Fill the whole panel with one packed pixel. */
void fb_fill(uint8_t px);

#endif /* FB_VIDEO_H */
