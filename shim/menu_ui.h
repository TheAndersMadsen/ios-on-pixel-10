#pragma once
#include <stdint.h>

/* Startup menu renderer for the 1280x2856 panel (XRGB8888). Freestanding,
 * integer-only (-mgeneral-regs-only), no libc; the same file renders the host
 * preview (menu_ui_preview.c) and runs in the shim. */
#define TGL_MENU_W 1280u
#define TGL_MENU_H 2856u

struct tgl_menu_view {
	unsigned sel;		/* 0 Android, 1 iOS */
	unsigned seconds;	/* countdown shown in the pill, 0..9 */
	unsigned ios_available;	/* 0: iOS tile dimmed, "Not installed yet" */
};

/* Full frame. */
void tgl_menu_draw(uint32_t *fb, unsigned stride_px, const struct tgl_menu_view *v);
/* Only the band that changes with selection or countdown. */
void tgl_menu_draw_band(uint32_t *fb, unsigned stride_px, const struct tgl_menu_view *v);
