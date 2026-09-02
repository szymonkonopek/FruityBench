/* fb_ui.c -- FruitBench's screen: three pages of it.
 *
 *   HOME     pick the rate and the span, start
 *   REC      the recording: four measures at a time, with sparklines
 *   SUMMARY  what was written, and where
 *
 * The recorder is a separate process, so this file holds no activity state of
 * its own beyond what a snapshot carries plus the little history it needs to
 * draw a sparkline. Everything here is plain C against fb_plat.h, which is
 * what lets host/fb_host.c render the same screens on a laptop.
 *
 * The panel is 240x240 and round: a glyph row outside the circle is simply not
 * there, so every y below was chosen against the radius rather than by eye.
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "fb_fmt.h"
#include "fb_measures.h"
#include "fb_plat.h"
#include "fb_text.h"
#include "fb_ui.h"
#include "fb_video.h"

/* ---- layout ------------------------------------------------------------- */

#define ROW_COUNT   FB_PAGE_SIZE      /* four measures per screen */
#define ROW_Y0      44
#define ROW_H       32
#define SPARK_W     48
#define SPARK_H     14
#define SPARK_X     158
#define HIST_LEN    SPARK_W           /* one sample per sparkline column */

/* ---- palette ------------------------------------------------------------ */

static uint8_t sBg, sInk, sDim, sAccent, sWarn, sGood, sGrid;

static void palette_init(void)
{
    sBg     = fb_pack_rgb(10, 12, 16);
    sInk    = fb_pack_rgb(255, 255, 255);
    sDim    = fb_pack_rgb(130, 140, 150);
    sAccent = fb_pack_rgb(250, 205, 70);     /* banana yellow, the app colour */
    sWarn   = fb_pack_rgb(240, 90, 90);
    sGood   = fb_pack_rgb(110, 210, 120);
    sGrid   = fb_pack_rgb(45, 50, 60);
}

/* ---- primitives --------------------------------------------------------- */

static void px(uint8_t *fb, int x, int y, uint8_t c)
{
    if (x >= 0 && x < FB_PANEL_W && y >= 0 && y < FB_PANEL_H) {
        fb[(size_t)y * FB_PANEL_W + x] = c;
    }
}

static void rect(uint8_t *fb, int x, int y, int w, int h, uint8_t c)
{
    int i, j;

    for (j = 0; j < h; ++j) {
        for (i = 0; i < w; ++i) {
            px(fb, x + i, y + j, c);
        }
    }
}

static void line(uint8_t *fb, int x0, int y0, int x1, int y1, uint8_t c)
{
    int dx = x1 > x0 ? x1 - x0 : x0 - x1;
    int dy = y1 > y0 ? y1 - y0 : y0 - y1;
    int sx = x0 < x1 ? 1 : -1;
    int sy = y0 < y1 ? 1 : -1;
    int err = (dx > dy ? dx : -dy) / 2;

    for (;;) {
        px(fb, x0, y0, c);
        if (x0 == x1 && y0 == y1) {
            break;
        }
        {
            int e2 = err;

            if (e2 > -dx) {
                err -= dy;
                x0 += sx;
            }
            if (e2 < dy) {
                err += dx;
                y0 += sy;
            }
        }
    }
}

static void text_c(uint8_t *fb, int y, const char *s, int scale, uint8_t c)
{
    fb_text_draw(fb, (FB_PANEL_W - fb_text_width(s, scale)) / 2, y, s, scale, c);
}

/* The 3x5 font is uppercase ASCII with a little punctuation. Fold what we
 * have into it rather than dropping glyphs: a measure's unit may be
 * lowercase ("bananas") or carry a UTF-8 middle dot ("N-m"), and both must
 * still read as something on the panel. */
static void ascii_up(char *out, int cap, const char *in)
{
    int n = 0;

    while (in[0] != '\0' && n < cap - 1) {
        unsigned char ch = (unsigned char)*in++;

        if (ch >= 'a' && ch <= 'z') {
            ch = (unsigned char)(ch - 'a' + 'A');
        } else if (ch >= 0x80u) {
            /* Any multi-byte sequence collapses to one dot. */
            while ((unsigned char)*in >= 0x80u && ((unsigned char)*in & 0xC0u) == 0x80u) {
                ++in;
            }
            ch = '.';
        }
        out[n++] = (char)ch;
    }
    out[n] = '\0';
}

static void fmt_clock(char *out, int cap, uint32_t sec)
{
    unsigned h = (unsigned)(sec / 3600u);
    unsigned m = (unsigned)((sec / 60u) % 60u);
    unsigned s = (unsigned)(sec % 60u);

    if (h > 0u) {
        snprintf(out, (size_t)cap, "%u:%02u:%02u", h, m, s);
    } else {
        snprintf(out, (size_t)cap, "%02u:%02u", m, s);
    }
}

/* ---- screen state ------------------------------------------------------- */

enum { SCR_HOME = 0, SCR_REC, SCR_SUMMARY };

/* Rate and span presets. A fast recording is backdated by its span, so it
 * needs one; OPEN is offered for live recording only, where the user stops it
 * by hand. */
static const uint8_t  kRates[] = { 1u, 10u, 60u };
static const uint32_t kSpans[] = { 0u, 900u, 1800u, 3600u };
#define RATE_COUNT ((int)(sizeof(kRates) / sizeof(kRates[0])))
#define SPAN_COUNT ((int)(sizeof(kSpans) / sizeof(kSpans[0])))

static const char *kSpanName[SPAN_COUNT] = { "OPEN", "15 MIN", "30 MIN", "60 MIN" };
static const char *kRateName[RATE_COUNT] = { "LIVE 1X", "FAST 10X", "TURBO 60X" };

static int           sScreen;
static int           sRateIdx;
static int           sSpanIdx;
static int           sPage;
static fb_snapshot_t sSnap;

/* Sparkline history: one ring per row, cleared when the page changes. */
static float    sHist[ROW_COUNT][HIST_LEN];
static uint8_t  sHistCount[ROW_COUNT];
static uint16_t sHistHead[ROW_COUNT];

/* buttons */
enum { BTN_L1, BTN_R1, BTN_L2, BTN_R2, BTN_COUNT };
static uint8_t  sDown[BTN_COUNT];
static uint32_t sR2HoldAt;
static uint8_t  sR2Fired;
static uint32_t sNow;

#define HOLD_MS 800u

static void hist_clear(void)
{
    memset(sHistCount, 0, sizeof(sHistCount));
    memset(sHistHead, 0, sizeof(sHistHead));
}

static void hist_push(const fb_snapshot_t *s)
{
    int r;

    for (r = 0; r < ROW_COUNT; ++r) {
        sHist[r][sHistHead[r]] = s->val[r];
        sHistHead[r] = (uint16_t)((sHistHead[r] + 1u) % HIST_LEN);
        if (sHistCount[r] < HIST_LEN) {
            ++sHistCount[r];
        }
    }
}

/* ---- rows --------------------------------------------------------------- */

static void draw_spark(uint8_t *fb, int row, int x, int y, int w, int h)
{
    int n = sHistCount[row];
    float lo = 0.0f;
    float hi = 0.0f;
    int i, prev_x = 0, prev_y = 0;

    /* The frame is drawn even with no data, so a measure that has not
     * reported yet is visibly empty rather than missing. */
    rect(fb, x, y + h, w, 1, sGrid);

    if (n < 2) {
        return;
    }

    for (i = 0; i < n; ++i) {
        int k = (sHistHead[row] - n + i + 2 * HIST_LEN) % HIST_LEN;
        float v = sHist[row][k];

        if (i == 0 || v < lo) {
            lo = v;
        }
        if (i == 0 || v > hi) {
            hi = v;
        }
    }
    if (hi - lo < 1e-6f) {
        /* A flat series would divide by zero; centre it instead, which is
         * also the honest picture of a constant measure. */
        lo -= 1.0f;
        hi += 1.0f;
    }

    for (i = 0; i < n; ++i) {
        int k = (sHistHead[row] - n + i + 2 * HIST_LEN) % HIST_LEN;
        float v = sHist[row][k];
        int cx = x + (w - 1) * i / (n - 1);
        int cy = y + h - (int)((v - lo) / (hi - lo) * (float)h);

        if (cy < y) {
            cy = y;
        }
        if (cy > y + h) {
            cy = y + h;
        }
        if (i > 0) {
            line(fb, prev_x, prev_y, cx, cy, sAccent);
        }
        prev_x = cx;
        prev_y = cy;
    }
}

static void draw_row(uint8_t *fb, int row, int idx)
{
    const fb_measure_t *m;
    int y = ROW_Y0 + row * ROW_H;
    char buf[24];

    if (idx >= FB_MEASURE_COUNT) {
        return;
    }
    m = &fb_measures[idx];

    /* Which measure: the generated six-character tag, plus a marker for the
     * ones the manifest declares as per-lap rather than time-based -- those
     * only reach the file once a lap, and the difference should be visible
     * while recording, not only afterwards. */
    ascii_up(buf, (int)sizeof(buf), m->short_tag);
    fb_text_draw(fb, 30, y, buf, 1, sDim);
    if (!m->timed) {
        fb_text_draw(fb, 30 + fb_text_width(buf, 1) + 4, y, "LAP", 1, sGrid);
    }

    /* The value, big, then its unit at the size of an annotation. The page
     * is checked first: a snapshot already in flight when the page changed
     * carries the previous page's values, and showing those under this
     * page's labels would be a lie, however briefly. */
    if (sSnap.page == (uint8_t)sPage) {
        fb_fmt_value(idx, sSnap.val[row], buf, (int)sizeof(buf));
    } else {
        snprintf(buf, sizeof(buf), "--");
    }
    fb_text_draw(fb, 30, y + 9, buf, 2, sInk);
    {
        int vx = 30 + fb_text_width(buf, 2) + 5;

        ascii_up(buf, (int)sizeof(buf), m->unit);
        fb_text_draw(fb, vx, y + 14, buf, 1, sDim);
    }

    draw_spark(fb, row, SPARK_X, y, SPARK_W, SPARK_H);
}

/* ---- screens ------------------------------------------------------------ */

static void draw_home(uint8_t *fb)
{
    char buf[40];

    text_c(fb, 28, "FRUITBENCH", 3, sAccent);
    text_c(fb, 50, "ACTIVITY PIPELINE BENCHMARK", 1, sDim);

    snprintf(buf, sizeof(buf), "%d MEASURES  %d REC  %d LAP",
             FB_MEASURE_COUNT, FB_TIMED_COUNT, FB_LAP_COUNT);
    text_c(fb, 62, buf, 1, sDim);

    snprintf(buf, sizeof(buf), "MODE  %s", kRateName[sRateIdx]);
    text_c(fb, 92, buf, 2, sInk);

    snprintf(buf, sizeof(buf), "SPAN  %s", kSpanName[sSpanIdx]);
    text_c(fb, 112, buf, 2, sInk);

    snprintf(buf, sizeof(buf), "SEED %08lX", (unsigned long)sSnap.seed);
    text_c(fb, 134, buf, 1, sDim);
    text_c(fb, 146, "NEW SEED EVERY START", 1, sGrid);

    text_c(fb, 168, "R1 START", 2, sGood);
    text_c(fb, 190, "L2 MODE   L1 SPAN", 1, sDim);
    text_c(fb, 202, "R2 EXIT", 1, sDim);
}

static void draw_rec(uint8_t *fb)
{
    char buf[40];
    int r;

    fmt_clock(buf, (int)sizeof(buf), sSnap.t);
    text_c(fb, 12, buf, 2, sInk);

    if (sSnap.state == FB_STATE_PAUSED) {
        text_c(fb, 28, "PAUSED", 1, sWarn);
    } else if (sSnap.state == FB_STATE_SAVING) {
        text_c(fb, 28, "SAVING", 1, sWarn);
    } else {
        snprintf(buf, sizeof(buf), "REC %uX", (unsigned)sSnap.rate);
        text_c(fb, 28, buf, 1, sGood);
    }

    for (r = 0; r < ROW_COUNT; ++r) {
        draw_row(fb, r, sPage * FB_PAGE_SIZE + r);
    }

    snprintf(buf, sizeof(buf), "PG %d/%d   LAP %u   REC %lu",
             sPage + 1, FB_PAGE_COUNT, (unsigned)sSnap.laps,
             (unsigned long)sSnap.records);
    text_c(fb, 180, buf, 1, sDim);

    snprintf(buf, sizeof(buf), "%.1f KM   %u BPM",
             (double)(sSnap.dist_m / 1000.0f),
             (unsigned)(sSnap.hr_bpm + 0.5f));
    text_c(fb, 192, buf, 1, sDim);

    /* Hold R2 to finish. The bar is the feedback that makes a hold discover-
     * able; a tap does nothing, so the file cannot be closed by accident. */
    if (sDown[BTN_R2] && !sR2Fired) {
        uint32_t held = sNow + HOLD_MS - sR2HoldAt;
        int w = (int)(held * 120u / HOLD_MS);

        if (w > 120) {
            w = 120;
        }
        rect(fb, 60, 206, 120, 6, sGrid);
        rect(fb, 60, 206, w, 6, sWarn);
        text_c(fb, 216, "FINISH", 1, sWarn);
    } else {
        text_c(fb, 204, "L2 PAGE  L1 LAP  R1 PAUSE", 1, sDim);
        text_c(fb, 216, "R2 HOLD=FINISH", 1, sDim);
    }
}

static void draw_summary(uint8_t *fb)
{
    char buf[64];
    int err = (sSnap.state == FB_STATE_ERROR);

    text_c(fb, 26, err ? "FAILED" : "SAVED", 3, err ? sWarn : sGood);

    if (err) {
        const char *why = "UNKNOWN";

        switch (sSnap.err) {
        case FB_ERR_OPEN:   why = "CANNOT CREATE FILE"; break;
        case FB_ERR_WRITE:  why = "WRITE FAILED";       break;
        case FB_ERR_FINISH: why = "FINALIZE FAILED";    break;
        default: break;
        }
        text_c(fb, 56, why, 1, sWarn);
    }

    {
        char clock[12];

        fmt_clock(clock, (int)sizeof(clock), sSnap.t);
        snprintf(buf, sizeof(buf), "TIME %s", clock);
        text_c(fb, 74, buf, 2, sInk);
    }

    snprintf(buf, sizeof(buf), "RECORDS %lu", (unsigned long)sSnap.records);
    text_c(fb, 96, buf, 1, sDim);
    snprintf(buf, sizeof(buf), "LAPS %u", (unsigned)sSnap.laps);
    text_c(fb, 108, buf, 1, sDim);
    snprintf(buf, sizeof(buf), "SIZE %lu KB", (unsigned long)(sSnap.bytes / 1024u));
    text_c(fb, 120, buf, 1, sDim);
    snprintf(buf, sizeof(buf), "DIST %.2f KM", (double)(sSnap.dist_m / 1000.0f));
    text_c(fb, 132, buf, 1, sDim);
    snprintf(buf, sizeof(buf), "SEED %08lX", (unsigned long)sSnap.seed);
    text_c(fb, 144, buf, 1, sDim);

    /* The file name carries characters the panel font does not have, so show
     * the part that identifies it: the date and time it was stamped with. */
    if (sSnap.file[0] != '\0') {
        const char *p = strrchr(sSnap.file, '/');
        char stamp[24];

        p = p ? p + 1 : sSnap.file;
        p = strchr(p, '_');
        /* activity_YYYYMMDDThhmmss.fit: the date and the time are all that
         * identifies the file, and the font has no underscore anyway. The
         * length is checked rather than assumed. */
        if (p && strlen(p + 1) >= 15u) {
            snprintf(stamp, sizeof(stamp), "%.8s %.6s", p + 1, p + 10);
            snprintf(buf, sizeof(buf), "FIT %s", stamp);
            text_c(fb, 160, buf, 1, sGrid);
        }
    }

    text_c(fb, 180, "32 CHARTS ON THE PHONE", 1, sAccent);
    text_c(fb, 198, "R1 AGAIN", 2, sGood);
    text_c(fb, 216, "R2 EXIT", 1, sDim);
}

static void render(void)
{
    uint8_t *fb = fb_present_buffer();

    fb_fill(sBg);

    switch (sScreen) {
    case SCR_REC:     draw_rec(fb);     break;
    case SCR_SUMMARY: draw_summary(fb); break;
    default:          draw_home(fb);    break;
    }

    fb_plat_present(fb);
}

/* ---- input -------------------------------------------------------------- */

static void set_page(int page)
{
    sPage = ((page % FB_PAGE_COUNT) + FB_PAGE_COUNT) % FB_PAGE_COUNT;
    hist_clear();
    fb_plat_command(FB_CMD_SET_PAGE, (uint32_t)sPage);
}

static void home_start(void)
{
    /* A fast recording must know how long it is: it is backdated by its span
     * so the file lands in the past rather than the future, which cannot be
     * done for an open-ended one. */
    if (kRates[sRateIdx] > 1u && kSpans[sSpanIdx] == 0u) {
        sSpanIdx = 2;                                  /* 30 minutes */
    }
    fb_plat_command(FB_CMD_SET_RATE, kRates[sRateIdx]);
    fb_plat_command(FB_CMD_SET_TARGET, kSpans[sSpanIdx]);
    set_page(0);
    fb_plat_command(FB_CMD_START, 0u);
    sScreen = SCR_REC;
}

static void on_press(int btn)
{
    sDown[btn] = 1u;

    switch (sScreen) {

    case SCR_HOME:
        if (btn == BTN_R1) {
            home_start();
        } else if (btn == BTN_L2) {
            sRateIdx = (sRateIdx + 1) % RATE_COUNT;
            if (kRates[sRateIdx] > 1u && kSpans[sSpanIdx] == 0u) {
                sSpanIdx = 2;
            }
        } else if (btn == BTN_L1) {
            sSpanIdx = (sSpanIdx + 1) % SPAN_COUNT;
            if (kRates[sRateIdx] > 1u && kSpans[sSpanIdx] == 0u) {
                sSpanIdx = 1;                          /* skip OPEN when fast */
            }
        } else if (btn == BTN_R2) {
            fb_plat_exit();
        }
        break;

    case SCR_REC:
        if (btn == BTN_R1) {
            fb_plat_command(sSnap.state == FB_STATE_PAUSED ? FB_CMD_RESUME
                                                           : FB_CMD_PAUSE, 0u);
        } else if (btn == BTN_L1) {
            fb_plat_command(FB_CMD_LAP, 0u);
        } else if (btn == BTN_L2) {
            set_page(sPage + 1);
        } else if (btn == BTN_R2) {
            /* Decided on the hold threshold, never on the press. */
            sR2HoldAt = sNow + HOLD_MS;
            sR2Fired = 0u;
        }
        break;

    default:                                            /* SCR_SUMMARY */
        if (btn == BTN_R1) {
            fb_plat_command(FB_CMD_RESET, 0u);
            sScreen = SCR_HOME;
        } else if (btn == BTN_R2) {
            fb_plat_exit();
        }
        break;
    }
}

static void feed_code(uint8_t c)
{
    /* Kernel button codes: press q/e/w/r, release a/d/s/f, click 1/3/2/4 for
     * L1/R1/L2/R2. The clicks are ignored throughout -- a short tap emits
     * press, click and release, so acting on both press and click would fire
     * every action twice. */
    switch (c) {
    case 'q': on_press(BTN_L1); break;
    case 'e': on_press(BTN_R1); break;
    case 'w': on_press(BTN_L2); break;
    case 'r': on_press(BTN_R2); break;

    case 'a': sDown[BTN_L1] = 0u; break;
    case 'd': sDown[BTN_R1] = 0u; break;
    case 's': sDown[BTN_L2] = 0u; break;
    case 'f': sDown[BTN_R2] = 0u; break;

    /* L1+R2 chord: leave the screen. The recorder keeps recording -- that is
     * the point of it being a separate process. */
    case 'z': fb_plat_exit(); break;

    default: break;
    }
}

static void pump_hold(void)
{
    if (sScreen == SCR_REC && sDown[BTN_R2] && !sR2Fired
        && (int32_t)(sNow - sR2HoldAt) >= 0) {
        sR2Fired = 1u;
        fb_plat_command(FB_CMD_STOP, 0u);
    }
}

/* ---- entry -------------------------------------------------------------- */

void fb_ui_run(void)
{
    fb_plat_log("FRUITBENCH: screen up\n");

    palette_init();
    hist_clear();
    sRateIdx = 0;
    sSpanIdx = 0;
    sScreen = SCR_HOME;

    /* First tick before drawing: writeDisplayFrameBuffer is a no-op until a
     * RESUME has been dequeued, which happens inside the frame wait. */
    fb_plat_frame_wait();
    fb_plat_keep_awake();

    /* The page is the recorder's state, not the screen's: it decides which
     * four values a snapshot carries. A screen that starts while a recording
     * is already running must adopt it, or every row would read "--" until
     * the user happened to press L2. */
    fb_plat_snapshot(&sSnap);
    sPage = (int)(sSnap.page % FB_PAGE_COUNT);

    while (!fb_plat_should_quit()) {
        uint8_t code;

        fb_plat_frame_wait();
        sNow = fb_plat_ticks_ms();

        while (fb_plat_poll_key(&code)) {
            feed_code(code);
        }
        pump_hold();

        if (fb_plat_snapshot(&sSnap)) {
            /* Only while actually recording: the recorder keeps publishing
             * once a second when paused, and 48 of those would replace the
             * whole sparkline with one frozen value. */
            if (sSnap.state == FB_STATE_REC
                && sSnap.page == (uint8_t)sPage) {
                hist_push(&sSnap);
            }
            /* The recorder owns the state; the screen follows it, so a
             * recording that stops on its own (a span that ran out, or a
             * write that failed) lands on the summary without a keypress. */
            if (sSnap.state == FB_STATE_SAVED
                || sSnap.state == FB_STATE_ERROR) {
                sScreen = SCR_SUMMARY;
            } else if ((sSnap.state == FB_STATE_REC
                        || sSnap.state == FB_STATE_PAUSED)
                       && sScreen == SCR_HOME) {
                sScreen = SCR_REC;
            }
        }

        render();
        fb_plat_keep_awake();
    }

    fb_plat_log("FRUITBENCH: screen down\n");
}
