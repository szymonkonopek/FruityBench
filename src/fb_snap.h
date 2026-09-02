/* fb_snap.h -- what the recorder tells the screen, and what the screen asks
 * of the recorder.
 *
 * Plain C POD so the C user interface (fb_ui.c) and the C++ message plumbing
 * (fb_msg.hpp) can share one definition. Kept small on purpose: it travels
 * through the kernel message pool once a second, so it carries the values of
 * the page currently on screen rather than all 32 measures.
 */
#ifndef FB_SNAP_H
#define FB_SNAP_H

#include <stdint.h>

#include "fb_measures.h"    /* FB_MEASURE_COUNT: the page count follows it */

#ifdef __cplusplus
extern "C" {
#endif

#define FB_PAGE_SIZE   4                            /* measures per screen  */
#define FB_PAGE_COUNT  ((FB_MEASURE_COUNT + FB_PAGE_SIZE - 1) / FB_PAGE_SIZE)
#define FB_FILE_CAP    32   /* activity_YYYYMMDDThhmmss.fit is 28 + NUL */

/* Recorder state, as shown on the panel. */
typedef enum {
    FB_STATE_IDLE = 0,
    FB_STATE_REC,
    FB_STATE_PAUSED,
    FB_STATE_SAVING,
    FB_STATE_SAVED,
    FB_STATE_ERROR
} fb_state_t;

/* Why the recording failed, if it did. */
typedef enum {
    FB_ERR_NONE = 0,
    FB_ERR_OPEN,        /* could not create Activity/YYYYMM/activity_*.fit  */
    FB_ERR_WRITE,       /* the FIT writer went not-ok mid-recording         */
    FB_ERR_FINISH       /* header back-patch, CRC or close failed           */
} fb_err_t;

/* Commands the screen sends to the recorder. */
typedef enum {
    FB_CMD_START = 0,   /* arg: unused (the recorder rolls a fresh seed)    */
    FB_CMD_PAUSE,
    FB_CMD_RESUME,
    FB_CMD_LAP,
    FB_CMD_STOP,        /* finish and save                                  */
    FB_CMD_DISCARD,     /* stop and delete                                  */
    FB_CMD_SET_RATE,    /* arg: activity seconds per real second (1/10/60)  */
    FB_CMD_SET_TARGET,  /* arg: target activity seconds, 0 = open ended     */
    FB_CMD_SET_PAGE,    /* arg: which 4 measures the snapshot should carry  */
    FB_CMD_RESET        /* leave the summary, back to idle                  */
} fb_cmd_t;

typedef struct {
    uint32_t seed;                  /* the session seed                     */
    uint32_t t;                     /* activity seconds recorded            */
    uint32_t target;                /* target activity seconds, 0 = open    */
    uint32_t records;               /* FIT record messages written          */
    uint32_t bytes;                 /* current size of the .fit file        */
    uint32_t steps;                 /* synthetic step count                 */
    float    dist_m;
    float    speed_ms;
    float    hr_bpm;
    float    alt_m;
    float    val[FB_PAGE_SIZE];     /* values of the measures on `page`     */
    uint16_t laps;
    uint8_t  state;                 /* fb_state_t                           */
    uint8_t  err;                   /* fb_err_t                             */
    uint8_t  page;                  /* which page `val` belongs to          */
    uint8_t  rate;                  /* activity seconds per real second     */
    uint8_t  pad[2];
    char     file[FB_FILE_CAP];     /* file name, once it exists            */
} fb_snapshot_t;

#ifdef __cplusplus
}
#endif

#endif /* FB_SNAP_H */
