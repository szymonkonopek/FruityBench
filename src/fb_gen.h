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

/* The fold a time-based measure's explicit session summary needs. The rule
 * says previewAggregation tells the companion how to fold the records; when
 * the app also writes a session value it must be that same fold, so the
 * recorder keeps the three numbers it could possibly need. */
typedef struct {
    float    min;
    float    max;
    float    sum;
    uint32_t count;
} fb_stat_t;

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
    float    value;        /* current sample, always inside [lo, hi]        */
    uint32_t hold_until;   /* SPARSE/STAIRS: activity second the hold ends  */
    float    hold_value;

    fb_stat_t stat;        /* time-based only: the session fold             */

    /* Additive measures (FB_ON_LAP): the increment of the lap that just
     * closed, and the sum of every closed increment. The rule is explicit
     * that a lap value is the increment for that segment and never a running
     * total, and that the session value is what the increments add up to. */
    float    lap_inc;
    float    total;
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

/* Close a lap. Every additive measure draws this lap's increment here and adds
 * it to its total, so the value written on the lap message describes that lap
 * alone. Call this BEFORE writing the lap message, and the message then reads
 * the increment back with fb_gen_lap_value(). */
void  fb_gen_lap(fb_gen_t *g);

/* The measure's current value: the sample for a time-based measure, and the
 * accumulated total for an additive one (which is what the session will
 * report, and the only live number worth showing for it). */
float fb_gen_value(const fb_gen_t *g, int idx);

/* The increment of the lap that fb_gen_lap() just closed. Only meaningful for
 * a measure with FB_ON_LAP; anything else returns its session value. */
float fb_gen_lap_value(const fb_gen_t *g, int idx);

/* The value for the whole activity, which the session message must carry:
 *   time-based        the records folded per previewAggregation
 *   additive per-lap  the sum of the lap increments
 *   anything else     the final sample
 */
float fb_gen_session_value(const fb_gen_t *g, int idx);

/* A random seed from whatever entropy the caller can supply (time, tick,
 * an address); mixed so that adjacent timestamps give unrelated sessions. */
uint32_t fb_gen_make_seed(uint32_t a, uint32_t b, uint32_t c);

#ifdef __cplusplus
}
#endif

#endif /* FB_GEN_H */
