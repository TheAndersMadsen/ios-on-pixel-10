/* The chooser's menu/release display instance (tgl_dcs_menu.h): tgl_dcs.c, unmodified, compiled
 * with the r11 chooser gates and renamed external symbols, next to the iOS path's own
 * TGL_DCS_HANDOFF instance in the same shim. Gate TGL_CHOOSER_IOS (empty unit otherwise). */
#if defined(TGL_CHOOSER_IOS) && TGL_CHOOSER_IOS
#if !defined(TGL_FRAME_RUNG) || TGL_FRAME_RUNG != 3
#error "the chooser menu layer needs TGL_FRAME_RUNG=3"
#endif
/* chooser-v1-r11's tgl_dcs.c gates, whatever the iOS line set globally. */
#undef TGL_DCS_HANDOFF
#undef TGL_DCS_MENU
#define TGL_DCS_MENU 1
#undef TGL_DCS_QUIESCE
#define TGL_DCS_QUIESCE 1
#undef TGL_DCS_BRIGHT
#define TGL_DCS_BRIGHT 0
#define tgl_dcs_begin tgl_dcsm_begin
#define tgl_dcs_run tgl_dcsm_run
#define tgl_dcs_finish tgl_dcsm_finish
#define tgl_dcs_refuse tgl_dcsm_refuse
#define tgl_dcs_present tgl_dcsm_present
#define tgl_dcs_release tgl_dcsm_release
#define tgl_dcs_guarded tgl_dcsm_guarded
#include "tgl_dcs.c"
#endif
