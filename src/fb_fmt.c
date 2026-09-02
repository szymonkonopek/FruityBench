/* fb_fmt.c -- see fb_fmt.h. */

#include <stdio.h>

#include "fb_fmt.h"
#include "fb_measures.h"

void fb_fmt_value(int idx, float v, char *out, int cap)
{
    const fb_measure_t *d;
    float span;

    if (cap <= 0) {
        return;
    }
    out[0] = '\0';
    if (idx < 0 || idx >= FB_MEASURE_COUNT) {
        return;
    }
    d = &fb_measures[idx];
    span = d->hi - d->lo;

    if (span >= 10000.0f) {
        snprintf(out, (size_t)cap, "%ld", (long)(v + 0.5f));
    } else if (span >= 50.0f) {
        snprintf(out, (size_t)cap, "%ld",
                 (long)(v >= 0.0f ? v + 0.5f : v - 0.5f));
    } else if (span >= 5.0f) {
        snprintf(out, (size_t)cap, "%.1f", (double)v);
    } else if (span >= 0.5f) {
        snprintf(out, (size_t)cap, "%.2f", (double)v);
    } else {
        snprintf(out, (size_t)cap, "%.4f", (double)v);
    }
}
