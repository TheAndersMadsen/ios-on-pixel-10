/*
 * Minimal text console on the ABL splash framebuffer. With the MMU off
 * every access is Device memory, so stay aligned (-mstrict-align).
 */
#include "console.h"
#include "font.h"
#include "laguna_usb.h"

#define SCALE		3
#define CH_W		(8 * SCALE)
#define CH_H		(16 * SCALE)
#define MARGIN		24
#define LABEL_COLS	8

/* Mirror the exact findings text into the EP0 log without changing pixels. */
static void usb_text(char *line, unsigned *n, const char *s)
{
	while (*s && *n < 255) line[(*n)++] = *s++;
}

static void usb_label(char *line, unsigned *n, const char *label)
{
	unsigned col = 0;
	*n = 0;
	while (*label && col < LABEL_COLS) {
		line[(*n)++] = *label++;
		col++;
	}
	while (col++ < LABEL_COLS) line[(*n)++] = ' ';
}

static void usb_hex32(char *line, unsigned *n, uint32_t value)
{
	static const char digits[] = "0123456789ABCDEF";
	for (int shift = 28; shift >= 0; shift -= 4)
		line[(*n)++] = digits[(value >> shift) & 15];
}

static void usb_finish(char *line, unsigned n)
{
	line[n++] = '\n';
	laguna_usb_write(line, n);
}

volatile uint32_t *con_fb;
uintptr_t con_fb_pa;
static uint32_t con_bg;
static int row;
/* Called by the paint loops every few rows/characters. shim.c points this at
 * a watchdog-pat so a multi-second Device-memory paint cannot exhaust the
 * armed firmware watchdog (the 2026-10-27 run measured 26.4 s of paint on
 * the bring-up path). NULL = no tick. */
void (*con_tick)(void);
/* con_clear covers the console text region only (24 rows): the remainder of
 * the panel keeps whatever the ABL splash had — painting less Device memory
 * is the single biggest bring-up latency lever, and stale splash pixels
 * below the text are diagnostic, not confusing. */
#define CON_CLEAR_ROWS	24

void con_init(uintptr_t fb_pa)
{
	con_fb_pa = fb_pa;
	con_fb = (volatile uint32_t *)fb_pa;
	row = 0;
}

void con_clear(uint32_t bg)
{
	con_bg = bg;
	row = 0;
	if (!con_fb) return;
	uint64_t bg2 = (uint64_t)bg << 32 | bg; /* fill two pixels per store */
	int rows = CON_CLEAR_ROWS * (CH_H) + 2 * MARGIN;
	if (rows > FB_H) rows = FB_H;
	for (int y = 0; y < rows; y++) {
		volatile uint64_t *line = (volatile uint64_t *)
		    ((volatile uint32_t *)con_fb + y * (FB_STRIDE / 4));
		for (int x = 0; x + 1 < FB_W; x += 2)
			line[x / 2] = bg2;
		if (con_tick && (y & 31) == 31) con_tick();
	}
	con_bg = bg;
	row = 0;
}

static void put_char(int col, char ch, uint32_t fg)
{
	static unsigned chars;
	if (!con_fb) return;
	if (con_tick && (++chars & 255) == 0) con_tick();
	if (ch < 0x20 || ch > 0x7e)
		ch = '?';
	const unsigned char *g = font8x16[ch - 0x20];
	int x0 = MARGIN + col * CH_W, y0 = MARGIN + row * CH_H;
	if (x0 + CH_W > FB_W || y0 + CH_H > FB_H)
		return;
	for (int gy = 0; gy < 16; gy++)
		for (int gx = 0; gx < 8; gx++) {
			uint32_t c = (g[gy] & (0x80 >> gx)) ? fg : con_bg;
			for (int sy = 0; sy < SCALE; sy++) {
				volatile uint32_t *p = con_fb + (y0 + gy * SCALE + sy) * (FB_STRIDE / 4)
						       + x0 + gx * SCALE;
				for (int sx = 0; sx < SCALE; sx++)
					p[sx] = c;
			}
		}
}

static int put_str(int col, const char *s, uint32_t fg)
{
	while (*s)
		put_char(col++, *s++, fg);
	return col;
}

static void fmt_hex(char *buf, uint64_t v, int digits)
{
	static const char hex[] = "0123456789ABCDEF";
	for (int i = 0; i < digits; i++)
		buf[i] = hex[(v >> (4 * (digits - 1 - i))) & 0xf];
	buf[digits] = 0;
}

void con_skip(void)
{
	row++;
}

void con_str(const char *label, const char *s)
{
	char line[256];
	unsigned n;
	usb_label(line, &n, label);
	usb_text(line, &n, s);
	usb_finish(line, n);
	put_str(0, label, YELLOW);
	put_str(LABEL_COLS, s, WHITE);
	row++;
}

void con_hex(const char *label, uint64_t v)
{
	char buf[17], line[256];
	unsigned n;
	fmt_hex(buf, v, 16);
	usb_label(line, &n, label);
	usb_text(line, &n, buf);
	usb_finish(line, n);
	con_str(label, buf);
}

void con_hex2(const char *label, const char *a, uint32_t va, const char *b, uint32_t vb)
{
	char buf[9], line[256];
	unsigned n;
	usb_label(line, &n, label);
	usb_text(line, &n, a);
	usb_hex32(line, &n, va);
	if (b) {
		usb_text(line, &n, " ");
		usb_text(line, &n, b);
		usb_hex32(line, &n, vb);
	}
	usb_finish(line, n);
	int col = put_str(0, label, YELLOW);
	col = col < LABEL_COLS ? LABEL_COLS : col + 1;
	col = put_str(col, a, YELLOW);
	fmt_hex(buf, va, 8);
	col = put_str(col, buf, WHITE);
	if (b) {
		col = put_str(col + 1, b, YELLOW);
		fmt_hex(buf, vb, 8);
		put_str(col, buf, WHITE);
	}
	row++;
}
