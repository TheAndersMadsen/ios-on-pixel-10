#pragma once
#include <stdint.h>
/* The chooser's display instance: tgl_dcs.c built a second time, as chooser-v1-r11 built it
 * (TGL_DCS_MENU, TGL_DCS_QUIESCE, TGL_FRAME_RUNG 3, TGL_DCS_BRIGHT 0), with its seven external
 * names renamed tgl_dcsm_*. The iOS path's own instance (TGL_DCS_HANDOFF, tgl_dcs_*) stays as
 * image_tool builds it. Both are file-static inside, so their state never mixes; both write the
 * same DCS record PA, so the iOS ladder's record replaces the menu's (the chooser stamps keep the
 * release result). tgl_dcs_menu.c. */
void tgl_dcsm_begin(uint64_t stamp_nonce, const uint8_t record_nonce[16], uint64_t epoch);
int tgl_dcsm_run(void);
void tgl_dcsm_finish(int code, uint64_t esr, uint64_t far, uint64_t wdt_stop);
void tgl_dcsm_refuse(int stage, int code, uint32_t detail);
int tgl_dcsm_present(void);
int tgl_dcsm_release(void);
unsigned tgl_dcsm_guarded(void);
