/* fb_gen.h -- the synthetic activity generator.
 *
 * FruitBench records an activity without a sensor: every value it writes comes
 * from here. One seed, drawn at start, fixes the whole session, so a recording
 * is reproducible from its seed (shown on the watch and stored in the summary)
 * yet different every time.
 *
 * Plain C and free of platform dependencies on purpose: the same object file
 * feeds the watch recorder and the desktop test that validates the FIT output.
 */
#ifndef FB_GEN_H
#define FB_GEN_H

#include <stdint.h>

#include "fb_measures.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    /* randomised waveform parameters, rolled once per session */
    float    amp;
    float    mid;
    float    phase;
    float    period;
    float    drift;
    float    rate;         /* COUNTER: units per second                     */
    float    tau;          /* DECAY: time constant                          */
    uint32_t rng;          /* the measure's own stream                      */

    /* running state */
    float    value;        /* current value, always inside [lo, hi]         */
    uint32_t hold_until;   /* SPARSE/STAIRS: activity second the hold ends  */
    float    hold_value;
} fb_measure_state_t;

/* The predefined metrics the manifest advertises (supportsDistance, ...).
 * Synthesised alongside the custom ones so the standard half of the pipeline
 * is exercised by the same recording. */
typedef struct {
    float    speed_ms;     /* current speed                                 */
    float    distance_m;   /* cumulative                                    */
    float    hr_bpm;       /* current heart rate                            */
    float    cadence_spm;  /* steps per minute                              */
    float    altitude_m;   /* current altitude                              */
    float    ascent_m;     /* cumulative gain                               */
    float    descent_m;    /* cumulative loss                               */
    uint32_t steps;        /* cumulative                                    */
    double   lat;          /* synthetic track, degrees                      */
    double   lon;
    float    heading;      /* radians, wanders                              */
} fb_predef_t;

typedef struct {
    uint32_t seed;                 /* the session seed                       */
    uint32_t rng;                  /* session stream                         */
    uint32_t t;                    /* activity seconds elapsed               */
    uint32_t lap_index;            /* 0-based, current lap                   */
    fb_measure_state_t m[FB_MEASURE_COUNT];
    fb_predef_t        p;
} fb_gen_t;

/* Roll a fresh session. `seed` of 0 is replaced by a fixed non-zero value so
 * the generator is never stuck on a degenerate PRNG state. */
void  fb_gen_init(fb_gen_t *g, uint32_t seed);

/* Advance one activity second: updates every measure and the predefined
 * metrics. `t` is the activity second this sample belongs to (it may jump by
 * more than one in fast-forward mode). */
void  fb_gen_step(fb_gen_t *g, uint32_t t);

/* Note the lap boundary. Every measure keeps evolving across it; the only
 * thing a lap changes is which sample the per-lap measures are read at, which
 * is whatever fb_gen_value returns when the lap message is written. */
void  fb_gen_lap(fb_gen_t *g);

/* The measure's current value. A per-lap measure is not a different series --
 * it is the same series read once per lap, at the boundary. */
float fb_gen_value(const fb_gen_t *g, int idx);

/* Value formatted for the panel: `out` gets at most `cap` chars, uppercase,
 * with a sensible number of decimals for the measure's range. */
void  fb_gen_format(const fb_gen_t *g, int idx, char *out, int cap);

/* A random seed from whatever entropy the caller can supply (time, tick,
 * an address); mixed so that adjacent timestamps give unrelated sessions. */
uint32_t fb_gen_make_seed(uint32_t a, uint32_t b, uint32_t c);

#ifdef __cplusplus
}
#endif

#endif /* FB_GEN_H */
