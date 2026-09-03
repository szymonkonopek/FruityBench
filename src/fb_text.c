/* fb_text.c -- 3x5 font renderer: clipped, scaled, one glyph at a time. */

#include <stddef.h>       /* size_t */

#include "fb_text.h"
#include "fb_font.h"
#include "fb_video.h"   /* FB_PANEL_W/H */

#define ADVANCE(scale)  ((FB_FONT_COLS + 1) * (scale))

static int glyph_index(char c)
{
    int i;

    for (i = 0; i < FB_FONT_COUNT; ++i) {
        if (fb_font_chars[i] == c) {
            return i;
        }
    }
    return -1;
}

int fb_text_width(const char *str, int scale)
{
    int n = 0;

    while (str[n] != '\0') {
        ++n;
    }
    if (n == 0) {
        return 0;
    }
    /* n glyphs, (n-1) inter-glyph gaps of one column. */
    return n * ADVANCE(scale) - scale;
}

void fb_text_draw(uint8_t *fb, int x, int y, const char *str,
                    int scale, uint8_t px)
{
    if (scale < 1) {
        scale = 1;
    }

    for (; *str != '\0'; ++str, x += ADVANCE(scale)) {
        int gi = glyph_index(*str);
        int col;

        if (gi < 0) {
            continue;
        }
        for (col = 0; col < FB_FONT_COLS; ++col) {
            uint8_t bits = fb_font_cols[gi][col];
            int row;

            for (row = 0; row < FB_FONT_ROWS; ++row) {
                int sx;

                if ((bits & (1u << row)) == 0u) {
                    continue;
                }
                for (sx = 0; sx < scale; ++sx) {
                    int sy;

                    for (sy = 0; sy < scale; ++sy) {
                        int fx = x + col * scale + sx;
                        int fy = y + row * scale + sy;

                        if (fx >= 0 && fx < FB_PANEL_W
                            && fy >= 0 && fy < FB_PANEL_H) {
                            fb[(size_t)fy * FB_PANEL_W + fx] = px;
                        }
                    }
                }
            }
        }
    }
}
