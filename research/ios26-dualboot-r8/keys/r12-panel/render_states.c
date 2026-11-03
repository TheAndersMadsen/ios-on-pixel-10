/* Phone states of chooser-v1-r12's menu (ios_available = 0 on the phone), with the shim's own menu_ui.c. */
#include <stdio.h>
#include <stdlib.h>
#include "menu_ui.h"
int main(int argc, char **argv)
{
	static uint32_t fb[TGL_MENU_W * TGL_MENU_H];
	const struct tgl_menu_view v[] = { {0, 5, 0}, {1, 3, 0}, {0, 3, 0}, {0, 1, 0} };
	const char *n[] = { "0-start", "1-voldown", "2-volup", "3-timeout-near" };
	char p[512];
	tgl_menu_draw(fb, TGL_MENU_W, &v[0]);
	for (unsigned i = 0; i < 4; i++) {
		if (i) tgl_menu_draw_band(fb, TGL_MENU_W, &v[i]); /* what the chooser loop does after the first frame */
		snprintf(p, sizeof p, "%s/%s.raw", argv[1], n[i]);
		FILE *f = fopen(p, "wb"); fwrite(fb, 4, (size_t)TGL_MENU_W * TGL_MENU_H, f); fclose(f);
	}
	return 0;
}
