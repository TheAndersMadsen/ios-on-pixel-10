/* Host test for chooser.c: menu state machine, segment parse, checksum and
 * placement against the real A0 FDT (argv[1], optional). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "chooser.h"

static unsigned fails, checks;
#define CHECK(c, m) do { checks++; if (!(c)) { fails++; printf("FAIL %s\n", m); } } while (0)

static void put64(uint8_t *p, uint64_t v) { for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i)); }

static uint8_t *mkseg(uint64_t comp, uint64_t len, uint64_t isz, uint64_t flags, uint64_t *total)
{
	uint64_t pad = (comp + 7) & ~7ull;
	uint8_t *p = aligned_alloc(8, 64 + pad + 64);
	memset(p, 0, 64 + pad + 64);
	memcpy(p, "TGLLNX01", 8);
	put64(p + 8, comp); put64(p + 16, len); put64(p + 24, isz); put64(p + 32, flags);
	for (uint64_t i = 0; i < comp; i++) p[64 + i] = (uint8_t)(i * 7 + 1);
	put64(p + 40, tgl_chooser_csum64(p + 64, comp));
	put64(p + 48, tgl_chooser_csum64(p, 48));
	*total = 64 + pad;
	return p;
}

static void menu_tests(void)
{
	struct tgl_chooser_menu s;
	tgl_chooser_menu_init(&s, 1000, 0);
	CHECK(tgl_chooser_menu_step(&s, 1000, 0) == TGL_CHOOSE_PENDING, "pending at start");
	CHECK(tgl_chooser_menu_step(&s, 5999, 0) == TGL_CHOOSE_PENDING, "pending before 5 s");
	CHECK(tgl_chooser_menu_step(&s, 6000, 0) == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_TIMEOUT, "default Android at 5 s");
	CHECK(tgl_chooser_menu_step(&s, 9000, TGL_KEY_DOWN) == TGL_CHOOSE_ANDROID, "decision is final");
	/* iOS chosen without an iOS root: Android with the reason */
	tgl_chooser_menu_init(&s, 0, 0);
	tgl_chooser_menu_step(&s, 100, TGL_KEY_DOWN);
	CHECK(s.sel == 1, "down selects iOS");
	CHECK(tgl_chooser_menu_step(&s, 3099, TGL_KEY_DOWN) == TGL_CHOOSE_PENDING, "held key is no new edge; grace runs");
	CHECK(tgl_chooser_menu_step(&s, 5000, 0) == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_NO_IOS, "no iOS root -> Android");
	/* iOS available */
	tgl_chooser_menu_init(&s, 0, 1);
	tgl_chooser_menu_step(&s, 4500, TGL_KEY_DOWN);
	CHECK(tgl_chooser_menu_step(&s, 5000, 0) == TGL_CHOOSE_PENDING, "late key extends countdown");
	CHECK(tgl_chooser_menu_step(&s, 7500, 0) == TGL_CHOOSE_IOS && s.why == TGL_WHY_KEYS, "iOS after grace");
	/* back to Android */
	tgl_chooser_menu_init(&s, 0, 1);
	tgl_chooser_menu_step(&s, 10, TGL_KEY_DOWN);
	tgl_chooser_menu_step(&s, 20, 0);
	tgl_chooser_menu_step(&s, 30, TGL_KEY_UP);
	CHECK(s.sel == 0 && s.presses == 2, "up returns to Android");
	CHECK(tgl_chooser_menu_step(&s, 5000, 0) == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_KEYS, "Android by keys");
	/* chord ignored */
	tgl_chooser_menu_init(&s, 0, 1);
	tgl_chooser_menu_step(&s, 10, TGL_KEY_UP | TGL_KEY_DOWN);
	CHECK(s.sel == 0 && s.presses == 0, "chord ignored");
	CHECK(tgl_chooser_menu_step(&s, 5000, 0) == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_TIMEOUT, "chord then timeout");
}

static void seg_tests(void)
{
	struct tgl_chooser_seg o;
	uint64_t tot;
	uint8_t *p = mkseg(1001, 4000, 8192, 0xa, &tot);
	CHECK(!tgl_chooser_seg_parse(p, tot, &o) && o.comp_len == 1001 && o.data == p + 64, "valid segment");
	CHECK(tgl_chooser_csum64(o.data, o.comp_len) == o.csum, "data checksum matches");
	CHECK(tgl_chooser_seg_parse(p, tot - 8, &o) != 0, "segment past image refused");
	CHECK(tgl_chooser_seg_parse(p + 1, tot, &o) != 0, "unaligned refused");
	p[64 + 500] ^= 1;
	CHECK(tgl_chooser_csum64(p + 64, 1001) != o.csum, "flipped byte changes checksum");
	free(p);
	uint64_t cases[][3] = { {4000, 8192, 0xb}, {4000, 8192, 0x2}, {4000, 8192, 0xc}, {9000, 8192, 0xa}, {0, 8192, 0xa}, {4000, 1ull << 40, 0xa} };
	const char *names[] = { "big-endian", "not placeable", "16K pages", "len>image_size", "zero len", "huge image_size" };
	for (unsigned i = 0; i < 6; i++) {
		p = mkseg(64, cases[i][0], cases[i][1], cases[i][2], &tot);
		CHECK(tgl_chooser_seg_parse(p, tot, &o) != 0, names[i]);
		free(p);
	}
	p = mkseg(64, 100, 200, 0xa, &tot);
	p[3] = 'X';
	CHECK(tgl_chooser_seg_parse(p, tot, &o) != 0, "bad magic");
	p[3] = 'L'; p[20] ^= 1;
	CHECK(tgl_chooser_seg_parse(p, tot, &o) != 0, "header checksum");
	free(p);
	CHECK(tgl_chooser_csum64((const uint8_t *)"", 0) == 0xcbf29ce484222325ull, "empty checksum = seed");
}

static void place_tests(const char *dtb_path)
{
	struct tgl_fdt_memory m;
	memset(&m, 0, sizeof m);
	m.ram_count = 2;
	m.ram[0] = (struct tgl_range){ 0x80000000ull, 0x10000000ull };
	m.ram[1] = (struct tgl_range){ 0x880000000ull, 0x80000000ull };
	m.reserved_count = 1;
	m.reserved[0] = (struct tgl_range){ 0x81000000ull, 0x1000 };
	struct tgl_range live[1] = { { 0x80000000ull, 0x400000 } };
	uint64_t b = 0;
	CHECK(!tgl_chooser_place(&m, 0x2940000, live, 1, &b) && b == 0x81200000ull, "skips shim and reservation, 2 MiB aligned");
	CHECK(!tgl_chooser_place(&m, 0x20000000, live, 1, &b) && b == 0x880000000ull, "too big for bank 0 -> next bank");
	CHECK(tgl_chooser_place(&m, 0x100000000ull, live, 1, &b) != 0, "nothing fits");
	if (!dtb_path) return;
	FILE *f = fopen(dtb_path, "rb");
	if (!f) { perror(dtb_path); exit(2); }
	static uint8_t blob[TGL_FDT_MAX_SIZE];
	size_t n = fread(blob, 1, sizeof blob, f);
	fclose(f);
	memset(&m, 0, sizeof m);
	const char *e = tgl_fdt_memory(blob, n, &m);
	CHECK(!e, "A0 FDT parses");
	if (e) { printf("fdt: %s\n", e); return; }
	printf("A0 FDT: ram %u reserved %u pools %u alloc %u total %u initrd %llx-%llx\n", m.ram_count, m.reserved_count,
	    m.pool_count, m.alloc_count, m.total_size, (unsigned long long)m.initrd_start, (unsigned long long)m.initrd_end);
	CHECK(m.initrd_start == 0x86000000ull && m.initrd_end == 0x885f6875ull, "A0 initrd values");
	/* shim as ABL loads it (0x80000000, 46 MiB with the stock segment), FDT where fastboot boot put it (r1 stamp 0x8a000000) */
	struct tgl_range lv[4] = { { 0x80000000ull, 46ull << 20 }, { 0x8a000000ull, m.total_size },
		{ m.initrd_start, m.initrd_end - m.initrd_start }, { 0xf0000000ull, 1280ull * 4 * 2856 } };
	e = tgl_chooser_place(&m, 43253760ull, lv, 4, &b);
	printf("A0 placement for image_size 43253760: %s base 0x%llx\n", e ? e : "ok", (unsigned long long)b);
	CHECK(!e && (b & 0x1fffff) == 0, "A0 placement found, aligned");
	for (unsigned i = 0; i < 4; i++)
		CHECK(!(b < lv[i].base + lv[i].size && lv[i].base < b + 43253760ull), "A0 placement clear of live range");
	for (unsigned i = 0; i < m.reserved_count; i++)
		CHECK(!(b < m.reserved[i].base + m.reserved[i].size && m.reserved[i].base < b + 43253760ull), "A0 placement clear of reservation");
	/* with a 70 MiB shim the low gap closes: next fit must still be valid */
	lv[0].size = 70ull << 20;
	e = tgl_chooser_place(&m, 43253760ull, lv, 4, &b);
	printf("A0 placement with 70 MiB shim: %s base 0x%llx\n", e ? e : "ok", (unsigned long long)b);
	CHECK(!e && b >= 0x80000000ull + (70ull << 20), "placement moves past a larger shim");
}

int main(int argc, char **argv)
{
	menu_tests();
	seg_tests();
	place_tests(argc > 1 ? argv[1] : 0);
	printf("chooser host test: %u checks, %u failed\n", checks, fails);
	return fails != 0;
}
