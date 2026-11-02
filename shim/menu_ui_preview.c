/* Host preview: render the startup menu to raw XRGB frames. argv: out_prefix */
#include <stdio.h>
#include <stdlib.h>
#include "menu_ui.h"
static void dump(const char *path, const uint32_t *fb)
{
	FILE *f = fopen(path, "wb");
	if (!f) { perror(path); exit(1); }
	fwrite(fb, 4, (size_t)TGL_MENU_W * TGL_MENU_H, f);
	fclose(f);
}
int main(int argc, char **argv)
{
	static uint32_t fb[TGL_MENU_W * TGL_MENU_H];
	if (argc < 2) return 2;
	char p[512];
	const struct tgl_menu_view views[] = { {0, 5, 0}, {1, 3, 1}, {0, 2, 1} };
	for (unsigned i = 0; i < 3; i++) {
		tgl_menu_draw(fb, TGL_MENU_W, &views[i]);
		snprintf(p, sizeof p, "%s-%u.raw", argv[1], i);
		dump(p, fb);
	}
	/* band redraw must equal a full redraw */
	static uint32_t a[TGL_MENU_W * TGL_MENU_H];
	tgl_menu_draw(a, TGL_MENU_W, &views[0]);
	tgl_menu_draw_band(a, TGL_MENU_W, &views[1]);
	tgl_menu_draw(fb, TGL_MENU_W, &views[1]);
	unsigned long diff = 0;
	for (unsigned long i = 0; i < (unsigned long)TGL_MENU_W * TGL_MENU_H; i++) diff += a[i] != fb[i];
	printf("menu preview: band-vs-full differing pixels %lu\n", diff);
	return diff != 0;
}
