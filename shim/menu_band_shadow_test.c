/* Host test for chooser-v1-r13 (research/ios26-dualboot-r8/keys/DIAG-r13.md): the band rendered into a separate shadow
 * buffer and copied over the panel buffer gives the same pixels as r12's direct redraw, the row hook does not change the
 * output, and it fires often enough to sample the keys during a redraw. Build: see test_chooser_r13.py. */
#define TGL_MENU_ROW_HOOK 1
#include "menu_ui.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned ticks, fails, checks;
#define CHECK(c, m) do { checks++; if (!(c)) { fails++; printf("FAIL %s\n", m); } } while (0)
static void tick(void) { ticks++; }

/* the device's own band copy (chooser_menu_r13.h, used by chooser.c and chooser_ios.c); no record read here */
#define CHOOSER_DCS_ENTRIES_P ((volatile uint32_t *)0)
#include "chooser_menu_r13.h"
#define band_copy chooser_band_copy

int main(void)
{
	size_t px = (size_t)TGL_MENU_W * TGL_MENU_H;
	uint32_t *direct = malloc(px * 4), *viacopy = malloc(px * 4), *shadow = malloc(px * 4);
	if (!direct || !viacopy || !shadow) return 2;
	for (unsigned sel0 = 0; sel0 < 2; sel0++)
		for (unsigned sel1 = 0; sel1 < 2; sel1++)
			for (unsigned secs = 0; secs <= 12; secs += 3) {
				struct tgl_menu_view v0 = { sel0, 5, 0 }, v1 = { sel1, secs, 0 };
				tgl_menu_row_hook = 0;
				tgl_menu_draw(direct, TGL_MENU_W, &v0);
				memcpy(viacopy, direct, px * 4);
				tgl_menu_draw_band(direct, TGL_MENU_W, &v1);	/* r12 */
				memset(shadow, 0xa5, px * 4);			/* the kernel destination holds anything */
				ticks = 0;
				tgl_menu_row_hook = tick;
				tgl_menu_draw_band(shadow, TGL_MENU_W, &v1);	/* r13 */
				band_copy(viacopy, shadow);
				size_t diff = 0;
				for (size_t i = 0; i < px; i++) diff += direct[i] != viacopy[i];
				char m[96];
				snprintf(m, sizeof m, "shadow band equals direct band (sel %u->%u, %u s): %zu px differ", sel0, sel1, secs, diff);
				CHECK(diff == 0, m);
				snprintf(m, sizeof m, "row hook fired %u times in one band redraw", ticks);
				CHECK(ticks >= TGL_MENU_BAND_Y1 - TGL_MENU_BAND_Y0, m);
			}
	/* hook off: the full frame equals the hook-on full frame */
	struct tgl_menu_view v = { 1, 4, 0 };
	tgl_menu_row_hook = 0;
	tgl_menu_draw(direct, TGL_MENU_W, &v);
	tgl_menu_row_hook = tick;
	tgl_menu_draw(viacopy, TGL_MENU_W, &v);
	CHECK(!memcmp(direct, viacopy, px * 4), "row hook leaves the full frame unchanged");
	printf("menu band shadow test: %u checks, %u failed (last band redraw %u row ticks)\n", checks, fails, ticks);
	free(direct); free(viacopy); free(shadow);
	return fails ? 1 : 0;
}
