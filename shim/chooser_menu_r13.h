/* chooser-v1-r13's menu-loop helpers (research/ios26-dualboot-r8/keys/DIAG-r13.md), moved out of chooser.c
 * unchanged so that chooser.c and chooser_ios.c run the same code. Included inside their TGL_CHOOSER_KEYS_FIX
 * blocks; the host tests (chooser_ios_test.c, menu_band_shadow_test.c) include it too.
 *
 * r12's ring never moved: r7/r9/r10 stamps show the 5 s menu picking after ~8.94 s with only 2 redraws
 * (3 FRAME_STATUS notes), i.e. one band redraw ~3.97 s, and the keys were sampled only between redraws.
 * The band blends over its own pixels, and the framebuffer is Normal-NC. The fix: the row hook samples the keys
 * during every redraw (chooser_menu_tick), the band is drawn in cached memory and only stored to the panel
 * buffer (chooser_band_copy), and a present happens only while the DCS record keeps room for the release
 * (chooser_dcs_room). The callers redraw only when the ring or the countdown number changes. */
#pragma once
#include <stdint.h>
#include "menu_ui.h"
#include "tgl_dcs.h"
#if !TGL_MENU_ROW_HOOK
#error "chooser_menu_r13.h needs TGL_MENU_ROW_HOOK=1 (menu_ui.c calls the hook once per drawn row)"
#endif

#define TGL_CHOOSER_MENU_MAX_MS 15000u	/* hard end of the menu: the DCS budget (25 s from the display start) covers the release */
#define TGL_CHOOSER_DCS_RESERVE 300u	/* record entries kept for the release (187 on the host fake, plus the TOP state polls) */
#define TGL_CHOOSER_PRESENT_COST 20u	/* a quiet present logs 2; budget it as a loud one (~18 in r10) */
#define DCS_HDR_ENTRIES 44u		/* struct hdr (tgl_dcs.c): magic 8, stamp_nonce 8, record_nonce 16, epoch 8, pattern 4 */
#ifndef CHOOSER_DCS_ENTRIES_P		/* the host tests point this at a fake record header */
#define CHOOSER_DCS_ENTRIES_P ((volatile uint32_t *)(uintptr_t)(TGL_DCS_RECORD_PA + DCS_HDR_ENTRIES))
#endif

static unsigned (*chooser_tick_keys)(void);
static unsigned chooser_tick_seen, chooser_ticks;
static void __attribute__((unused)) chooser_menu_tick(void)
{
	chooser_ticks++;
	if (chooser_tick_keys) chooser_tick_seen |= chooser_tick_keys();
}

/* Room for one more present and still the release: the record header's live entry count (written after every entry). */
static unsigned __attribute__((unused)) chooser_dcs_entries(void)
{
	return *CHOOSER_DCS_ENTRIES_P;
}
static int __attribute__((unused)) chooser_dcs_room(void)
{
	return chooser_dcs_entries() + 8u + TGL_CHOOSER_PRESENT_COST + TGL_CHOOSER_DCS_RESERVE < TGL_DCS_CAPACITY;
}

/* Band rows from the cached shadow to the panel buffer: stores only, never a read of Normal-NC. volatile keeps the
 * compiler from turning the loop into a memcpy call (the shim has none). Both buffers have stride TGL_MENU_W. */
static void __attribute__((unused)) chooser_band_copy(uint32_t *fb, const uint32_t *sh)
{
	volatile uint64_t *d = (volatile uint64_t *)(void *)(fb + (uint64_t)TGL_MENU_BAND_Y0 * TGL_MENU_W);
	const uint64_t *p = (const uint64_t *)(const void *)(sh + (uint64_t)TGL_MENU_BAND_Y0 * TGL_MENU_W);
	for (uint64_t n = (uint64_t)(TGL_MENU_BAND_Y1 - TGL_MENU_BAND_Y0) * TGL_MENU_W / 2; n; n--) *d++ = *p++;
}
