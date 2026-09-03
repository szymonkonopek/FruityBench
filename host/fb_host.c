/* fb_host.c -- run FruitBench's screen on a laptop.
 *
 * Links the same fb_ui.c / fb_video.c / fb_text.c / fb_gen.c the watch runs and
 * stands in for the two things only the watch has: the frame tick with its
 * button queue, and the recorder process. The recorder is simulated in-process
 * here -- the real one writes FIT, which is C++ and has its own host test
 * (tools/fit_host_test.cpp) -- but the generator behind it is the real one, so
 * a screenshot from here shows real values with real waveforms.
 *
 * Used for two things: checking a layout change without flashing a watch, and
 * rendering the store previews (tools/gen_previews.py).
 *
 *   cc -I../src fb_host.c ../src/fb_ui.c ../src/fb_video.c ../src/fb_text.c \
 *      ../src/fb_gen.c ../src/fb_fmt.c ../src/fb_measures.c -lm -o fb_host
 *   ./fb_host --frames 60 --script "5:e,6:d" --dump shot.ppm
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "fb_gen.h"
#include "fb_plat.h"
#include "fb_ui.h"
#include "fb_video.h"

/* ---- the fake machine --------------------------------------------------- */

#define MAX_KEYS 256

static int      gFrames = 60;         /* how many ticks to run   */
static int      gFrame;
static char     gDumpPath[512];
static uint8_t  gKeyQ[MAX_KEYS];
static int      gKeyHead, gKeyTail;
static int      gQuit;

/* frame:code pairs, replayed as the loop reaches each frame */
static int      gScriptFrame[MAX_KEYS];
static uint8_t  gScriptCode[MAX_KEYS];
static int      gScriptCount;

/* ---- the simulated recorder --------------------------------------------- */

static fb_snapshot_t gSnap;
static fb_gen_t      gGen;
static int           gSnapFresh;
static uint32_t      gNextLapT;
static uint32_t      gLapInterval = 300u;

static void sim_publish(void)
{
    int i;

    for (i = 0; i < FB_PAGE_SIZE; ++i) {
        int idx = (int)gSnap.page * FB_PAGE_SIZE + i;

        gSnap.val[i] = (idx < FB_MEASURE_COUNT) ? fb_gen_value(&gGen, idx) : 0.0f;
    }
    gSnap.dist_m = gGen.p.distance_m;
    gSnap.speed_ms = gGen.p.speed_ms;
    gSnap.hr_bpm = gGen.p.hr_bpm;
    gSnap.alt_m = gGen.p.altitude_m;
    gSnap.steps = gGen.p.steps;
    gSnapFresh = 1;
}

/* One frame of recording. The watch derives activity seconds from the real
 * clock; here a frame is simply worth `rate` seconds, which fills a sparkline
 * fast enough to photograph. */
static void sim_tick(void)
{
    uint32_t k;

    if (gSnap.state != FB_STATE_REC) {
        return;
    }
    for (k = 0; k < gSnap.rate; ++k) {
        ++gSnap.t;
        fb_gen_step(&gGen, gSnap.t);
        ++gSnap.records;
        gSnap.bytes += 96u;
        if (gSnap.t >= gNextLapT) {
            fb_gen_lap(&gGen);          /* draws this lap's increments */
            gNextLapT = gSnap.t + gLapInterval;
            ++gSnap.laps;
        }
        if (gSnap.target && gSnap.t >= gSnap.target) {
            gSnap.state = FB_STATE_SAVED;
            snprintf(gSnap.file, sizeof(gSnap.file),
                     "activity_20260902T101500.fit");
            break;
        }
    }
    sim_publish();
}

/* ---- fb_plat ------------------------------------------------------------ */

void fb_plat_command(int cmd, uint32_t arg)
{
    switch (cmd) {
    case FB_CMD_START:
        gSnap.seed = fb_gen_make_seed(gSnap.seed, (uint32_t)gFrame + 7u, 0x51ED27u);
        fb_gen_init(&gGen, gSnap.seed);
        gSnap.t = 0u;
        gSnap.records = 0u;
        gSnap.laps = 0u;
        gSnap.bytes = 0u;
        gSnap.state = FB_STATE_REC;
        gLapInterval = (gSnap.rate > 1u && gSnap.target >= 8u)
                           ? gSnap.target / 8u : 300u;
        gNextLapT = gLapInterval;
        /* The recorder puts only the name in the snapshot -- the directory is
         * fixed and the 32 bytes are budgeted. */
        snprintf(gSnap.file, sizeof(gSnap.file),
                 "activity_20260902T101500.fit");
        break;
    case FB_CMD_PAUSE:   gSnap.state = FB_STATE_PAUSED; break;
    case FB_CMD_RESUME:  gSnap.state = FB_STATE_REC;    break;
    case FB_CMD_LAP:
        fb_gen_lap(&gGen);
        ++gSnap.laps;
        gNextLapT = gSnap.t + gLapInterval;
        break;
    case FB_CMD_STOP:    gSnap.state = FB_STATE_SAVED;  break;
    case FB_CMD_DISCARD: gSnap.state = FB_STATE_IDLE;   break;
    case FB_CMD_SET_RATE:   gSnap.rate = (uint8_t)(arg ? arg : 1u); break;
    case FB_CMD_SET_TARGET: gSnap.target = arg; break;
    case FB_CMD_SET_PAGE:   gSnap.page = (uint8_t)(arg % FB_PAGE_COUNT); break;
    case FB_CMD_RESET:
        gSnap.state = FB_STATE_IDLE;
        gSnap.t = 0u;
        gSnap.records = 0u;
        gSnap.laps = 0u;
        gSnap.file[0] = '\0';
        break;
    default: break;
    }
    sim_publish();
}

int fb_plat_snapshot(fb_snapshot_t *out)
{
    int fresh = gSnapFresh;

    gSnapFresh = 0;
    memcpy(out, &gSnap, sizeof(*out));
    return fresh;
}

void fb_plat_frame_wait(void)
{
    int i;

    ++gFrame;
    for (i = 0; i < gScriptCount; ++i) {
        if (gScriptFrame[i] == gFrame) {
            gKeyQ[gKeyTail] = gScriptCode[i];
            gKeyTail = (gKeyTail + 1) % MAX_KEYS;
        }
    }
    sim_tick();
    if (gFrame >= gFrames) {
        gQuit = 1;
    }
}

int fb_plat_poll_key(uint8_t *code)
{
    if (gKeyHead == gKeyTail) {
        return 0;
    }
    *code = gKeyQ[gKeyHead];
    gKeyHead = (gKeyHead + 1) % MAX_KEYS;
    return 1;
}

/* The watch's tick is about 10 Hz; report the same so hold timing behaves as
 * it does there (a 800 ms hold is eight frames). */
uint32_t fb_plat_ticks_ms(void) { return (uint32_t)gFrame * 100u; }

int  fb_plat_should_quit(void) { return gQuit; }
void fb_plat_keep_awake(void)  {}
void fb_plat_log(const char *msg) { fputs(msg, stderr); }
void fb_plat_exit(void) { gQuit = 1; }

/* Keep only the last frame: a scripted shot parks the screen in the wanted
 * state and the dump is what it looks like there. */
void fb_plat_present(const uint8_t *fb)
{
    static uint8_t last[FB_PANEL_BYTES];

    memcpy(last, fb, sizeof(last));

    if (gQuit && gDumpPath[0] != '\0') {
        FILE *f = fopen(gDumpPath, "wb");
        int i;

        if (!f) {
            perror(gDumpPath);
            return;
        }
        fprintf(f, "P6\n%d %d\n255\n", FB_PANEL_W, FB_PANEL_H);
        for (i = 0; i < FB_PANEL_BYTES; ++i) {
            uint8_t r, g, b;

            fb_unpack_rgb(last[i], &r, &g, &b);
            fputc(r, f);
            fputc(g, f);
            fputc(b, f);
        }
        fclose(f);
        gDumpPath[0] = '\0';
    }
}

/* ---- entry -------------------------------------------------------------- */

static void parse_script(const char *s)
{
    while (*s != '\0' && gScriptCount < MAX_KEYS) {
        int frame = atoi(s);
        const char *colon = strchr(s, ':');

        if (!colon) {
            break;
        }
        gScriptFrame[gScriptCount] = frame;
        gScriptCode[gScriptCount] = (uint8_t)colon[1];
        ++gScriptCount;
        s = strchr(colon, ',');
        if (!s) {
            break;
        }
        ++s;
    }
}

int main(int argc, char **argv)
{
    int i;

    gSnap.rate = 1u;
    gSnap.seed = 0x51ED27A3u;
    fb_gen_init(&gGen, gSnap.seed);
    sim_publish();

    for (i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--frames") && i + 1 < argc) {
            gFrames = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--dump") && i + 1 < argc) {
            snprintf(gDumpPath, sizeof(gDumpPath), "%s", argv[++i]);
        } else if (!strcmp(argv[i], "--script") && i + 1 < argc) {
            parse_script(argv[++i]);
        } else if (!strcmp(argv[i], "--seed") && i + 1 < argc) {
            gSnap.seed = (uint32_t)strtoul(argv[++i], NULL, 0);
            fb_gen_init(&gGen, gSnap.seed);
        } else {
            fprintf(stderr,
                    "usage: %s [--frames N] [--script F:CODE,...] "
                    "[--dump out.ppm] [--seed N]\n", argv[0]);
            return 2;
        }
    }

    fb_ui_run();
    return 0;
}
