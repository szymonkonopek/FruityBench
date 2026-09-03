/* fb_text.h -- the 3x5 text renderer. Pure C, clipped to the 240x240 panel. */
#ifndef FB_TEXT_H
#define FB_TEXT_H

#include <stdint.h>

/* Draw `str` at (x, y) in panel pixels, scaled `scale`x. Characters not in the
 * font are skipped but still advance x, so columns stay aligned. `px` is a
 * packed ABGR2222 pixel. */
void fb_text_draw(uint8_t *fb, int x, int y, const char *str,
                    int scale, uint8_t px);

/* Width in pixels fb_text_draw would consume. */
int fb_text_width(const char *str, int scale);

#endif /* FB_TEXT_H */
