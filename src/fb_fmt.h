/* fb_fmt.h -- one place that decides how a measure's value is written out.
 *
 * Shared by the screen and the generator so the number on the panel and the
 * number in a log line never disagree about decimals. Depends only on the
 * generated catalogue, which keeps the GUI process free of the generator.
 */
#ifndef FB_FMT_H
#define FB_FMT_H

#ifdef __cplusplus
extern "C" {
#endif

/* Writes `v` for measure `idx` into `out` (at most `cap` bytes, always NUL
 * terminated). The number of decimals comes from the measure's declared
 * envelope, not from its FIT type: a 0..0.05 measure is unreadable as an
 * integer and a 0..1.5e6 one is unreadable with decimals. */
void fb_fmt_value(int idx, float v, char *out, int cap);

#ifdef __cplusplus
}
#endif

#endif /* FB_FMT_H */
