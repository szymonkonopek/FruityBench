/* fb_gen.c -- see fb_gen.h.
 *
 * Every measure gets its own PRNG stream and its own randomised waveform
 * parameters, so a session looks different each time while staying inside the
 * envelope the catalogue declares -- a chart that leaves its declared range
 * would be a bug in the benchmark rather than a finding about the platform.
 *
 * No libm beyond sinf/expf/sqrtf: the waveforms are deliberately cheap, the
 * recorder runs them 32 times a second in fast-forward.
 */

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "fb_gen.h"

/* ---- PRNG --------------------------------------------------------------- */

static uint32_t xs32(uint32_t *s)
{
    uint32_t x = *s;

    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    if (x == 0u) {
        x = 0x9E3779B9u;
    }
    *s = x;
    return x;
}

/* uniform in [0, 1) */
static float rnd(uint32_t *s)
{
    return (float)(xs32(s) >> 8) * (1.0f / 16777216.0f);
}

/* uniform in [a, b) */
static float rnd_range(uint32_t *s, float a, float b)
{
    return a + (b - a) * rnd(s);
}

/* Roughly normal, mean 0, sd ~1: three uniforms is plenty for wiggle. */
static float rnd_norm(uint32_t *s)
{
    return (rnd(s) + rnd(s) + rnd(s) - 1.5f) * 1.1547f;
}

uint32_t fb_gen_make_seed(uint32_t a, uint32_t b, uint32_t c)
{
    uint32_t x = a * 0x9E3779B9u ^ (b + 0x85EBCA6Bu) ^ (c * 0xC2B2AE35u);

    x ^= x >> 15;
    x *= 0x2545F491u;
    x ^= x >> 13;
    return x ? x : 0x1234567u;
}

/* ---- helpers ------------------------------------------------------------ */

static float clampf(float v, float lo, float hi)
{
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

static void stat_reset(fb_stat_t *st)
{
    st->min = 0.0f;
    st->max = 0.0f;
    st->sum = 0.0f;
    st->count = 0u;
}

static void stat_add(fb_stat_t *st, float v)
{
    if (st->count == 0u) {
        st->min = v;
        st->max = v;
    } else if (v < st->min) {
        st->min = v;
    } else if (v > st->max) {
        st->max = v;
    }
    st->sum += v;
    ++st->count;
}

#define TWO_PI 6.28318530718f

/* ---- init --------------------------------------------------------------- */

void fb_gen_init(fb_gen_t *g, uint32_t seed)
{
    int i;

    memset(g, 0, sizeof(*g));
    g->seed = seed ? seed : 0xC0FFEEu;
    g->rng  = g->seed;

    for (i = 0; i < FB_MEASURE_COUNT; ++i) {
        const fb_measure_t *d = &fb_measures[i];
        fb_measure_state_t *m = &g->m[i];
        float span = d->hi - d->lo;

        /* One stream per measure, derived from the session seed so the whole
         * session still follows from that single number. */
        m->rng = fb_gen_make_seed(g->seed, (uint32_t)i + 1u, 0x5BD1E995u);

        /* A measure with no declared period still needs one: COUNTER, RAMP and
         * SPARSE are shaped by rate and hold time instead, but SINE-family
         * fallbacks want something sane. */
        m->period = d->period_s > 0.0f
                        ? d->period_s * rnd_range(&m->rng, 0.65f, 1.55f)
                        : rnd_range(&m->rng, 90.0f, 600.0f);
        m->phase  = rnd(&m->rng) * TWO_PI;

        /* Stay inside [lo, hi] even at the extremes of the waveform: amplitude
         * is at most half the span, and the midpoint is pulled in by it. */
        m->amp = span * 0.5f * rnd_range(&m->rng, 0.45f, 1.0f);
        m->mid = d->lo + span * 0.5f
                 + (span * 0.5f - m->amp) * rnd_range(&m->rng, -0.8f, 0.8f);

        m->drift = span * rnd_range(&m->rng, -0.15f, 0.15f) / 3600.0f;
        m->rate  = span > 0.0f ? span / rnd_range(&m->rng, 900.0f, 5400.0f)
                               : 0.0f;
        m->tau   = rnd_range(&m->rng, 8.0f, 40.0f);

        switch (d->wave) {
        case FB_WAVE_COUNTER:
            m->value = d->lo;
            break;
        case FB_WAVE_FLAT:
            /* A flat line still gets a random level when the envelope allows
             * one; lightbulb_hum declares lo == hi, so it is truly constant. */
            m->value = span > 0.0f ? rnd_range(&m->rng, d->lo, d->hi) : d->lo;
            break;
        case FB_WAVE_RAMP:
            m->value = d->lo;
            break;
        default:
            m->value = clampf(m->mid, d->lo, d->hi);
            break;
        }

        m->hold_value = m->value;
        m->hold_until = 0u;
        m->lap_inc = 0.0f;
        m->total = 0.0f;
        stat_reset(&m->stat);
    }

    /* Predefined metrics: a plausible-looking run somewhere in Krakow, which
     * is only a starting point -- the track wanders from there. */
    g->p.speed_ms    = rnd_range(&g->rng, 2.2f, 3.6f);
    g->p.hr_bpm      = rnd_range(&g->rng, 95.0f, 120.0f);
    g->p.cadence_spm = rnd_range(&g->rng, 150.0f, 176.0f);
    g->p.altitude_m  = rnd_range(&g->rng, 180.0f, 260.0f);
    g->p.lat         = 50.0614 + (double)rnd_range(&g->rng, -0.05f, 0.05f);
    g->p.lon         = 19.9366 + (double)rnd_range(&g->rng, -0.05f, 0.05f);
    g->p.heading     = rnd(&g->rng) * TWO_PI;
}

/* ---- one measure, one sample -------------------------------------------- */

static float wave_sample(const fb_measure_t *d, fb_measure_state_t *m,
                         uint32_t t, uint32_t dt)
{
    float lo = d->lo;
    float hi = d->hi;
    float span = hi - lo;
    float ft = (float)t;
    float fdt = (float)dt;
    float x, v;

    if (span <= 0.0f) {
        return lo;                    /* degenerate envelope: constant */
    }

    /* phase within the period, 0..1 */
    x = m->period > 0.0f ? (ft / m->period + m->phase / TWO_PI) : 0.0f;
    x -= (float)(int32_t)x;
    if (x < 0.0f) {
        x += 1.0f;
    }

    switch (d->wave) {

    case FB_WAVE_SINE:
        v = m->mid + m->amp * sinf(ft * TWO_PI / m->period + m->phase);
        break;

    case FB_WAVE_TRIANGLE:
        v = m->mid + m->amp * (x < 0.5f ? (4.0f * x - 1.0f)
                                        : (3.0f - 4.0f * x));
        break;

    case FB_WAVE_SAW:
        v = lo + span * x;
        break;

    case FB_WAVE_SQUARE:
        v = x < 0.5f ? (m->mid - m->amp) : (m->mid + m->amp);
        break;

    case FB_WAVE_WALK:
        /* Bounded random walk: reflect at the edges so it explores the whole
         * envelope instead of sticking to a rail. */
        v = m->value + rnd_norm(&m->rng) * span * 0.02f * (fdt > 4.0f ? 2.0f : 1.0f);
        if (v < lo) {
            v = lo + (lo - v);
        }
        if (v > hi) {
            v = hi - (v - hi);
        }
        break;

    case FB_WAVE_SPIKES:
        /* Quiet baseline with rare tall spikes -- the shape that shows whether
         * a chart renderer keeps its outliers. */
        v = lo + span * 0.06f * rnd(&m->rng);
        if (rnd(&m->rng) < 0.02f * (fdt < 1.0f ? 1.0f : fdt)) {
            v = lo + span * rnd_range(&m->rng, 0.55f, 1.0f);
        }
        break;

    case FB_WAVE_DECAY:
        /* Re-triggered exponential decay. */
        if (rnd(&m->rng) < fdt / m->period) {
            v = hi;
        } else {
            v = lo + (m->value - lo) * expf(-fdt / m->tau);
        }
        break;

    case FB_WAVE_STAIRS: {
        /* Eight levels; hold, then step, wrapping at the top. */
        float step = span / 8.0f;

        if (t >= m->hold_until) {
            m->hold_until = t + (uint32_t)(m->period / 8.0f) + 1u;
            m->hold_value += step;
            if (m->hold_value > hi) {
                m->hold_value = lo;
            }
        }
        v = m->hold_value;
        break;
    }

    case FB_WAVE_RAMP:
        /* One rise across the session, then a plateau. */
        v = lo + span * clampf(ft / (m->period * 6.0f), 0.0f, 1.0f);
        break;

    case FB_WAVE_NOISE:
        v = rnd_range(&m->rng, lo, hi);
        break;

    case FB_WAVE_PULSE:
        /* Narrow pulses: three seconds high out of every period. */
        v = (x < 3.0f / (m->period > 3.0f ? m->period : 4.0f)) ? hi : lo;
        break;

    case FB_WAVE_COUNTER:
        /* Monotonic: never decreases, clamps at the top of the envelope. */
        v = m->value + m->rate * fdt * rnd_range(&m->rng, 0.4f, 1.6f);
        if (v > hi) {
            v = hi;
        }
        break;

    case FB_WAVE_DRIFT:
        v = m->mid + m->amp * 0.75f * sinf(ft * TWO_PI / m->period + m->phase)
            + m->drift * ft;
        break;

    case FB_WAVE_BURST:
        /* Calm for half the period, agitated for the other half. */
        if (x < 0.5f) {
            v = m->mid + rnd_norm(&m->rng) * span * 0.02f;
        } else {
            v = m->mid + rnd_norm(&m->rng) * m->amp * 0.6f;
        }
        break;

    case FB_WAVE_FLAT:
        v = m->value;
        break;

    case FB_WAVE_SPARSE:
        /* Holds a quantised level for tens of seconds, then jumps: the series
         * a renderer is most likely to draw as a smooth curve by mistake. */
        if (t >= m->hold_until) {
            float levels = 5.0f;
            float k = (float)(int32_t)(rnd(&m->rng) * levels);

            m->hold_until = t + 20u + (uint32_t)(rnd(&m->rng) * 40.0f);
            m->hold_value = lo + span * (k / (levels - 1.0f));
        }
        v = m->hold_value;
        break;

    default:
        v = m->mid;
        break;
    }

    return clampf(v, lo, hi);
}

/* ---- predefined metrics -------------------------------------------------- */

static void predef_step(fb_gen_t *g, uint32_t dt)
{
    fb_predef_t *p = &g->p;
    float fdt = (float)dt;
    float d_alt;

    /* speed wanders between a walk and a decent run */
    p->speed_ms = clampf(p->speed_ms + rnd_norm(&g->rng) * 0.06f * fdt,
                         1.4f, 5.2f);
    p->distance_m += p->speed_ms * fdt;

    /* heart rate follows speed with lag and its own noise */
    p->hr_bpm = clampf(p->hr_bpm
                       + (90.0f + p->speed_ms * 16.0f - p->hr_bpm) * 0.05f * fdt
                       + rnd_norm(&g->rng) * 1.2f,
                       60.0f, 195.0f);

    p->cadence_spm = clampf(p->cadence_spm + rnd_norm(&g->rng) * 0.8f,
                            140.0f, 190.0f);
    p->steps += (uint32_t)(p->cadence_spm / 60.0f * fdt);

    d_alt = rnd_norm(&g->rng) * 0.35f * fdt;
    p->altitude_m = clampf(p->altitude_m + d_alt, 120.0f, 480.0f);
    if (d_alt > 0.0f) {
        p->ascent_m += d_alt;
    } else {
        p->descent_m -= d_alt;
    }

    /* Track: a wandering heading integrated at the current speed. One degree
     * of latitude is ~111.32 km; longitude is scaled by cos(lat), which at
     * these latitudes is close enough to a constant for a synthetic path. */
    p->heading += rnd_norm(&g->rng) * 0.06f * fdt;
    {
        double step_m = (double)(p->speed_ms * fdt);
        double dlat = step_m * (double)cosf(p->heading) / 111320.0;
        double dlon = step_m * (double)sinf(p->heading) / (111320.0 * 0.64);

        p->lat += dlat;
        p->lon += dlon;
    }
}

/* ---- public ------------------------------------------------------------- */

void fb_gen_step(fb_gen_t *g, uint32_t t)
{
    uint32_t dt = (t > g->t) ? (t - g->t) : 1u;
    int k;

    g->t = t;

    for (k = 0; k < FB_MEASURE_COUNT; ++k) {
        const fb_measure_t *d = &fb_measures[k];
        fb_measure_state_t *m = &g->m[k];

        /* An additive measure's series advances once per lap, in fb_gen_lap();
         * sampling it here as well would double-advance the waveform. */
        if (FB_HAS_LAP(d)) {
            continue;
        }

        m->value = wave_sample(d, m, t, dt);

        /* Only a time-based measure is folded: the rule confines
         * previewAggregation to those, and a session-only measure's value is
         * simply its last sample. */
        if (FB_IS_TIMED(d)) {
            stat_add(&m->stat, m->value);
        }
    }

    predef_step(g, dt);
}

void fb_gen_lap(fb_gen_t *g)
{
    int k;

    for (k = 0; k < FB_MEASURE_COUNT; ++k) {
        const fb_measure_t *d = &fb_measures[k];
        fb_measure_state_t *m = &g->m[k];

        if (!FB_HAS_LAP(d)) {
            continue;
        }
        /* Sampled in lap units -- a minute per lap -- so a declared period of
         * 240 s means a cycle of about four laps and consecutive laps differ
         * visibly. The result is this lap's increment, inside the envelope,
         * and the total is what the session message will carry. */
        m->lap_inc = wave_sample(d, m, g->lap_index * 60u, 60u);
        m->total += m->lap_inc;
        m->value = m->total;
    }
    ++g->lap_index;
}

float fb_gen_value(const fb_gen_t *g, int idx)
{
    if (idx < 0 || idx >= FB_MEASURE_COUNT) {
        return 0.0f;
    }
    return FB_HAS_LAP(&fb_measures[idx]) ? g->m[idx].total : g->m[idx].value;
}

float fb_gen_lap_value(const fb_gen_t *g, int idx)
{
    if (idx < 0 || idx >= FB_MEASURE_COUNT) {
        return 0.0f;
    }
    if (!FB_HAS_LAP(&fb_measures[idx])) {
        return fb_gen_session_value(g, idx);
    }
    return g->m[idx].lap_inc;
}

float fb_gen_session_value(const fb_gen_t *g, int idx)
{
    const fb_measure_t *d;
    const fb_measure_state_t *m;

    if (idx < 0 || idx >= FB_MEASURE_COUNT) {
        return 0.0f;
    }
    d = &fb_measures[idx];
    m = &g->m[idx];

    if (FB_HAS_LAP(d)) {
        return m->total;                    /* the sum of the increments */
    }
    if (!FB_IS_TIMED(d)) {
        return m->value;                    /* one value for the activity */
    }
    if (m->stat.count == 0u) {
        return m->value;                    /* nothing recorded yet */
    }

    /* The same fold the companion would have applied to the records. */
    switch (d->agg) {
    case FB_AGG_MIN:
        return m->stat.min;
    case FB_AGG_MAX:
        return m->stat.max;
    case FB_AGG_AVERAGE:
    default:
        return m->stat.sum / (float)m->stat.count;
    }
}
