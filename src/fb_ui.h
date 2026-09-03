/* fb_ui.h -- FruitBench's screen.
 *
 * One entry point: the GUI process hands over its thread and the loop runs
 * until the kernel asks the app to stop -- or until the user exits, which
 * leaves the recorder running (see fb_ui.c).
 */
#ifndef FB_UI_H
#define FB_UI_H

#ifdef __cplusplus
extern "C" {
#endif

void fb_ui_run(void);

#ifdef __cplusplus
}
#endif

#endif /* FB_UI_H */
