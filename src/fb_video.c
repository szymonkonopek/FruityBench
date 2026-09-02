/* fb_video.c -- panel buffer + ABGR2222 packing. FRUITBENCH needs none of UOOM's
 * palette/dither machinery, only solid colours for text. */

#include <string.h>

#include "fb_video.h"

/* ABGR2222: A[7:6] B[5:4] G[3:2] R[1:0], each channel 0..3, alpha 3 = opaque. */
#define A_SHIFT 6
#define B_SHIFT 4
#define G_SHIFT 2
#define R_SHIFT 0
#define OPAQUE  3u
#define LSTEP   85u   /* 255 / 3 */

static uint8_t sPanel[FB_PANEL_BYTES];

uint8_t *fb_present_buffer(void)
{
    return sPanel;
}

static uint8_t q2(uint8_t v)
{
    unsigned q = ((unsigned)v * 3u + 127u) / 255u;
    return (uint8_t)(q > 3u ? 3u : q);
}

uint8_t fb_pack_rgb(uint8_t r, uint8_t g, uint8_t b)
{
    return (uint8_t)((OPAQUE << A_SHIFT)
                   | ((unsigned)q2(b) << B_SHIFT)
                   | ((unsigned)q2(g) << G_SHIFT)
                   | ((unsigned)q2(r) << R_SHIFT));
}

void fb_unpack_rgb(uint8_t px, uint8_t *r, uint8_t *g, uint8_t *b)
{
    *r = (uint8_t)(((px >> R_SHIFT) & 3u) * LSTEP);
    *g = (uint8_t)(((px >> G_SHIFT) & 3u) * LSTEP);
    *b = (uint8_t)(((px >> B_SHIFT) & 3u) * LSTEP);
}

void fb_fill(uint8_t px)
{
    memset(sPanel, px, sizeof(sPanel));
}
