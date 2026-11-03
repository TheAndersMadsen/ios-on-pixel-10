/* Startup menu: two frosted tiles (Android, iOS) on a dark gradient with a soft
 * glow, a selection ring, labels, a countdown pill and a hint line. All math is
 * integer fixed point (Q4 = 1/16 px) so the shim's -mgeneral-regs-only build can
 * run it; assets come from menu_assets.h (gen_menu_assets.py). */
#include "menu_ui.h"
#include "menu_assets.h"

#define W TGL_MENU_W
#define H TGL_MENU_H

/* Layout (px). Tiles sit a little above the optical centre of the tall panel. */
#define TILE	344
#define TILE_R	86
#define TILE_GAP 120
#define TILE_CY	1300
#define TILE_Y0	(TILE_CY - TILE / 2)
#define TILE_Y1	(TILE_CY + TILE / 2)
#define TILE0_X0 ((W - 2 * TILE - TILE_GAP) / 2)
#define TILE1_X0 (TILE0_X0 + TILE + TILE_GAP)
#define RING_IN	12		/* ring starts this far outside the tile */
#define RING_W	5
#define GLOW	70
#define LABEL_BASE (TILE_Y1 + 104)
#define SUB_BASE (LABEL_BASE + 56)
#define PILL_CY	(LABEL_BASE + 190)
#define PILL_H	76
#define TITLE_BASE (TILE_Y0 - 170)
#define HINT_BASE (H - 250)
#define BAND_Y0	(TILE_Y0 - RING_IN - RING_W - GLOW - 4)
#define BAND_Y1	(PILL_CY + PILL_H / 2 + 8)
_Static_assert(BAND_Y0 == TGL_MENU_BAND_Y0 && BAND_Y1 == TGL_MENU_BAND_Y1, "menu_ui.h band rows");

#if TGL_MENU_ROW_HOOK
void (*tgl_menu_row_hook)(void);
#define ROW_HOOK() do { if (tgl_menu_row_hook) tgl_menu_row_hook(); } while (0)
#else
#define ROW_HOOK() do { } while (0)
#endif

static unsigned isqrt64(uint64_t v)
{
	uint64_t r = 0, b = UINT64_C(1) << 62;
	while (b > v) b >>= 2;
	while (b) {
		if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1;
		b >>= 2;
	}
	return (unsigned)r;
}

static int imax(int a, int b) { return a > b ? a : b; }
static int imin(int a, int b) { return a < b ? a : b; }
static int iabs(int a) { return a < 0 ? -a : a; }

/* Signed distance (Q4) from pixel (x, y)'s centre to a rounded rectangle. */
static int rr_dist(int x, int y, int x0, int y0, int x1, int y1, int r)
{
	int cx = x * 16 + 8, cy = y * 16 + 8;
	int mx = (x0 + x1) * 8, my = (y0 + y1) * 8;
	int qx = iabs(cx - mx) - ((x1 - x0) * 8 - r * 16);
	int qy = iabs(cy - my) - ((y1 - y0) * 8 - r * 16);
	int ox = imax(qx, 0), oy = imax(qy, 0);
	int out = (int)isqrt64((uint64_t)ox * ox + (uint64_t)oy * oy);
	return out + imin(imax(qx, qy), 0) - r * 16;
}

/* Coverage 0..256 of "distance <= 0" with a one-pixel anti-aliased edge. */
static int cov(int d) { return imax(0, imin(256, (8 - d) * 16)); }

static uint32_t blend(uint32_t c, uint32_t rgb, int a /* 0..256 */)
{
	if (a <= 0) return c;
	if (a >= 256) return 0xff000000u | rgb;
	uint32_t o = 0xff000000u;
	for (int s = 0; s < 24; s += 8) {
		int d = (int)((c >> s) & 255), t = (int)((rgb >> s) & 255);
		o |= (uint32_t)(d + (((t - d) * a) >> 8)) << s;
	}
	return o;
}

/* Dark graphite gradient with a cool glow behind the tiles. */
static uint32_t background(int x, int y)
{
	int t = y * 256 / H;				/* 0 top .. 256 bottom */
	int r = 22 - (16 * t >> 8), g = 24 - (17 * t >> 8), b = 30 - (21 * t >> 8);
	int dx = x - W / 2, dy = (y - TILE_CY) * 3 / 4;
	uint64_t d2 = (uint64_t)((int64_t)dx * dx + (int64_t)dy * dy);
	const uint64_t R2 = 1000ull * 1000ull;
	if (d2 < R2) {
		int k = (int)(256 - (d2 * 256 / R2));	/* 0..256 */
		k = k * k >> 8;
		r += 30 * k >> 8; g += 36 * k >> 8; b += 52 * k >> 8;
	}
	/* faint vignette at the very top and bottom */
	if (y < 200) { int v = (200 - y) * 10 / 200; r -= v; g -= v; b -= v; }
	if (r < 0) r = 0; if (g < 0) g = 0; if (b < 0) b = 0;
	return 0xff000000u | (uint32_t)r << 16 | (uint32_t)g << 8 | (uint32_t)b;
}

static void fill_bg(uint32_t *fb, unsigned stride, int y0, int y1)
{
	for (int y = y0; y < y1; y++) {
		uint32_t *row = fb + (unsigned)y * stride;
		ROW_HOOK();
		for (int x = 0; x < (int)W; x++) row[x] = background(x, y);
	}
}

static void mask_at(uint32_t *fb, unsigned stride, int mi, int left, int top,
	uint32_t rgb, int alpha /* 0..256 */)
{
	const struct tgl_menu_mask *m = &menu_assets[mi];
	for (int j = 0; j < m->h; j++) {
		int y = top + j;
		if (y < 0 || y >= (int)H) continue;
		ROW_HOOK();
		uint32_t *row = fb + (unsigned)y * stride;
		const uint8_t *a = menu_blob + m->off + (unsigned)j * m->w;
		for (int i = 0; i < m->w; i++) {
			int x = left + i;
			if (x < 0 || x >= (int)W || !a[i]) continue;
			row[x] = blend(row[x], rgb, (a[i] * alpha) >> 8);
		}
	}
}

/* Text centred on cx with its baseline at base. */
static void text_c(uint32_t *fb, unsigned stride, int mi, int cx, int base,
	uint32_t rgb, int alpha)
{
	const struct tgl_menu_mask *m = &menu_assets[mi];
	mask_at(fb, stride, mi, cx - m->w / 2, base - m->baseline, rgb, alpha);
}

static void tile(uint32_t *fb, unsigned stride, int x0, int selected, int dim)
{
	int x1 = x0 + TILE, y0 = TILE_Y0, y1 = TILE_Y1;
	int pad = RING_IN + RING_W + GLOW;
	for (int y = imax(0, y0 - pad); y < imin((int)H, y1 + pad); y++) {
		uint32_t *row = fb + (unsigned)y * stride;
		ROW_HOOK();
		for (int x = x0 - pad; x < x1 + pad; x++) {
			int d = rr_dist(x, y, x0, y0, x1, y1, TILE_R);
			uint32_t c = row[x];
			if (d <= 16) {
				/* frosted fill, brighter towards the top edge */
				int lift = (y1 - y) * 22 / TILE;
				int fa = (selected ? 40 : 24) + lift - (dim ? 10 : 0);
				c = blend(c, 0xffffff, fa * cov(d) >> 8);
				/* hairline border */
				int edge = cov(d) - cov(d + 24);
				c = blend(c, 0xffffff, (selected ? 120 : 52) * edge >> 8);
			}
			if (selected) {
				int din = d - RING_IN * 16, dout = d - (RING_IN + RING_W) * 16;
				int ring = imin(256 - cov(din), cov(dout));
				if (ring > 0) c = blend(c, 0xffffff, 230 * ring >> 8);
				if (dout > 0 && dout < GLOW * 16) {
					int k = 256 - dout * 256 / (GLOW * 16);
					c = blend(c, 0x9ec4ff, (k * k >> 8) * 34 >> 8);
				}
			}
			row[x] = c;
		}
	}
}

static void pill(uint32_t *fb, unsigned stride, int cx, int w)
{
	int x0 = cx - w / 2, x1 = cx + w / 2, y0 = PILL_CY - PILL_H / 2, y1 = PILL_CY + PILL_H / 2;
	for (int y = y0 - 2; y < y1 + 2; y++) {
		uint32_t *row = fb + (unsigned)y * stride;
		ROW_HOOK();
		for (int x = x0 - 2; x < x1 + 2; x++) {
			int d = rr_dist(x, y, x0, y0, x1, y1, PILL_H / 2);
			row[x] = blend(row[x], 0xffffff, 30 * cov(d) >> 8);
		}
	}
}

static void band(uint32_t *fb, unsigned stride, const struct tgl_menu_view *v)
{
	unsigned sel = v->sel ? 1 : 0;
	int dim_ios = !v->ios_available;
	int c0 = TILE0_X0 + TILE / 2, c1 = TILE1_X0 + TILE / 2;
	tile(fb, stride, TILE0_X0, sel == 0, 0);
	tile(fb, stride, TILE1_X0, sel == 1, dim_ios);
	const struct tgl_menu_mask *ia = &menu_assets[MENU_ICON_ANDROID], *ii = &menu_assets[MENU_ICON_IOS];
	mask_at(fb, stride, MENU_ICON_ANDROID, c0 - ia->w / 2, TILE_CY - ia->h / 2, 0xffffff, sel == 0 ? 256 : 200);
	mask_at(fb, stride, MENU_ICON_IOS, c1 - ii->w / 2, TILE_CY - ii->h / 2, 0xffffff,
	    dim_ios ? 110 : (sel == 1 ? 256 : 200));
	text_c(fb, stride, MENU_LABEL_ANDROID, c0, LABEL_BASE, 0xffffff, sel == 0 ? 248 : 170);
	text_c(fb, stride, MENU_LABEL_IOS, c1, LABEL_BASE, 0xffffff, dim_ios ? 110 : (sel == 1 ? 248 : 170));
	if (dim_ios) text_c(fb, stride, MENU_NO_IOS, c1, SUB_BASE, 0xffffff, 96);
	/* Countdown pill under the selection: "Starting Android in 5" */
	int pm = sel && v->ios_available ? MENU_COUNT_IOS : MENU_COUNT_ANDROID;
	int dm = MENU_DIGIT_0 + (int)(v->seconds > 9 ? 9 : v->seconds);
	const struct tgl_menu_mask *p = &menu_assets[pm], *dg = &menu_assets[dm];
	int space = 11, tw = p->w + space + dg->w;
	pill(fb, stride, (int)W / 2, tw + 72);
	int left = (int)W / 2 - tw / 2, base = PILL_CY + 13;
	mask_at(fb, stride, pm, left, base - p->baseline, 0xffffff, 225);
	mask_at(fb, stride, dm, left + p->w + space, base - dg->baseline, 0xffffff, 255);
}

void tgl_menu_draw_band(uint32_t *fb, unsigned stride, const struct tgl_menu_view *v)
{
	fill_bg(fb, stride, BAND_Y0, BAND_Y1);
	band(fb, stride, v);
}

void tgl_menu_draw(uint32_t *fb, unsigned stride, const struct tgl_menu_view *v)
{
	fill_bg(fb, stride, 0, (int)H);
	text_c(fb, stride, MENU_TITLE, (int)W / 2, TITLE_BASE, 0xffffff, 150);
	band(fb, stride, v);
	text_c(fb, stride, MENU_HINT, (int)W / 2, HINT_BASE, 0xffffff, 105);
}
