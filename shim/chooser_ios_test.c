/* Host test for chooser_ios.c: image layout (shim | TEGUPLD1 payload | TGLLNX01 segment),
 * iOS admission through the shim's own payload validator and handoff checks, the menu with a
 * live iOS entry, the pick -> action table, and chooser-v1-r13's redraw/key fix on the iOS menu
 * (tgl_chooser_ios_menu_tick and the shared chooser_menu_r13.h helpers). Optional real data:
 *   chooser_ios_test [A0 fdt.dtb [payload-usb.bin [stock lz4 bytes]]]
 * Build: cc -DTGL_CHOOSER_HOST -o chooser_ios_test chooser_ios.c fdt.c chooser_ios_test.c */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "chooser_ios.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#include "payload.h"
#pragma GCC diagnostic pop
/* chooser.c's r13 helpers, the same header the device loop uses; the record header is a fake here. */
static volatile uint32_t fake_dcs_entries;
#define CHOOSER_DCS_ENTRIES_P (&fake_dcs_entries)
#define TGL_MENU_ROW_HOOK 1
#include "chooser_menu_r13.h"

static unsigned fails, checks;
#define CHECK(c, m) do { checks++; if (!(c)) { fails++; printf("FAIL %s\n", m); } } while (0)

static void put64(uint8_t *p, uint64_t v) { for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i)); }
static uint64_t get64(const uint8_t *p) { uint64_t v = 0; for (int i = 0; i < 8; i++) v |= (uint64_t)p[i] << (8 * i); return v; }

/* A minimal TEGUXNU v2 payload the shim's validator accepts: one 64 KiB segment, ADT after it. */
static uint8_t *mkpayload(uint64_t phys_base, uint64_t mem_size, uint64_t *len)
{
	uint64_t table_end = sizeof(struct payload) + sizeof(struct payload_seg);
	uint64_t seg_off = (table_end + 7) & ~7ull, seg_size = 0x10000, adt_off = seg_off + seg_size, adt_size = 4096;
	*len = adt_off + adt_size;
	uint8_t *b = aligned_alloc(16, (*len + 15) & ~15ull);
	memset(b, 0, *len);
	struct payload *p = (struct payload *)b;
	memcpy(p->magic, "TEGUXNU", 8);
	p->version = TGL_PAYLOAD_VERSION; p->nsegs = 1;
	p->virt_base = 0xfffffe0006000000ull; p->entry_va = p->virt_base + 0x100;
	p->adt_off = adt_off; p->adt_size = adt_size; p->kernel_end = p->virt_base + 0x10000;
	p->phys_base = phys_base; p->mem_size = mem_size;
	strcpy(p->cmdline, "debug=0x8 cpus=5 rd=md0 blazer_ufs_mountroot=1 blazer_ufs_root=ios_system");
	p->segs[0] = (struct payload_seg){ p->virt_base, 0x10000, seg_off, seg_size };
	return b;
}

/* An Android segment as chooser_image.py writes it (chooser.c format). */
static uint64_t putseg(uint8_t *p, uint64_t comp, uint64_t image_len, uint64_t image_size)
{
	memcpy(p, "TGLLNX01", 8);
	put64(p + 8, comp); put64(p + 16, image_len); put64(p + 24, image_size); put64(p + 32, 0xa);
	for (uint64_t i = 0; i < comp; i++) p[64 + i] = (uint8_t)(i * 13 + 5);
	put64(p + 40, tgl_chooser_csum64(p + 64, comp));
	put64(p + 48, tgl_chooser_csum64(p, 48));
	put64(p + 56, 0);
	return 64 + ((comp + 7) & ~7ull);
}

/* [shim of end_off bytes][TEGUPLD1 n payload][pad 8][segment]; image_size at +16 covers all. */
static uint8_t *mkimage(uint64_t end_off, const uint8_t *pl, uint64_t n, uint64_t comp, uint64_t *isz, uint64_t *seg_at)
{
	uint64_t seg = end_off + 16 + n; seg += (8 - (seg & 7)) & 7;
	uint64_t total = seg + 64 + ((comp + 7) & ~7ull);
	uint8_t *b = aligned_alloc(16, (total + 15) & ~15ull);
	memset(b, 0, total);
	memcpy(b + end_off, "TEGUPLD1", 8); put64(b + end_off + 8, n);
	if (pl) memcpy(b + end_off + 16, pl, n);
	putseg(b + seg, comp, 4000, 8192);
	put64(b + 16, total);
	*isz = total; *seg_at = seg;
	return b;
}

/* chooser.c's own rule for the segment position (address-aligned skip of the envelope). */
static const uint8_t *chooser_c_seg(const uint8_t *head, uint64_t end_off)
{
	const uint8_t *p = head + end_off;
	if (!memcmp(p, "TEGUPLD1", 8)) { p += 16 + get64(p + 8); p += (8 - ((uintptr_t)p & 7)) & 7; }
	return p;
}

static void layout_tests(void)
{
	struct tgl_chooser_ios_layout o;
	struct tgl_chooser_seg s;
	uint64_t isz, at;
	for (uint64_t n = 1; n <= 17; n += 3) {	/* every payload length mod 8 */
		uint8_t pl[24] = { 0 };
		uint8_t *b = mkimage(4096, pl, n, 100, &isz, &at);
		const char *e = tgl_chooser_ios_layout(b, isz, 4096, &o);
		CHECK(!e && o.seg_off == at && o.payload_off == 4112 && o.payload_bytes == n, "layout finds payload and 8-aligned segment");
		CHECK(chooser_c_seg(b, 4096) == b + o.seg_off, "same segment offset as chooser.c's skip");
		CHECK(!tgl_chooser_seg_parse(b + o.seg_off, isz - o.seg_off, &s) && s.comp_len == 100, "segment after the envelope parses");
		free(b);
	}
	uint8_t pl[8] = { 0 };
	uint8_t *b = mkimage(4096, pl, 8, 64, &isz, &at);
	CHECK(tgl_chooser_ios_layout(b, isz, 4092, &o) != 0, "unaligned _end refused");
	CHECK(tgl_chooser_ios_layout(b + 1, isz, 4096, &o) != 0, "unaligned image refused");
	CHECK(tgl_chooser_ios_layout(b, 4096 + 8, 4096, &o) != 0, "image_size too short for the envelope");
	CHECK(tgl_chooser_ios_layout(b, at + 63, 4096, &o) != 0, "no room for the segment header");
	CHECK(tgl_chooser_ios_layout(b, isz, isz + 8, &o) != 0, "_end beyond image_size");
	put64(b + 4096 + 8, isz);	/* length runs past the image */
	CHECK(tgl_chooser_ios_layout(b, isz, 4096, &o) != 0, "envelope past image_size");
	put64(b + 4096 + 8, 0);
	CHECK(tgl_chooser_ios_layout(b, isz, 4096, &o) != 0, "empty envelope refused");
	b[4096] = 'X';
	CHECK(tgl_chooser_ios_layout(b, isz, 4096, &o) != 0, "no envelope -> no iOS entry");
	CHECK(chooser_c_seg(b, 4096) == b + 4096, "no envelope: chooser.c looks at _end (Android-only image)");
	free(b);
}

static void synthetic_memory(struct tgl_fdt_memory *m)
{
	memset(m, 0, sizeof *m);
	m->ram_count = 2;
	m->ram[0] = (struct tgl_range){ 0x80000000ull, 0x80000000ull };
	m->ram[1] = (struct tgl_range){ 0x880000000ull, 0x200000000ull };
	m->reserved_count = 1;
	m->reserved[0] = (struct tgl_range){ 0x90000000ull, 0x100000 };
	m->total_size = 0x40000;
	m->initrd_fields = 3; m->initrd_start = 0x86000000ull; m->initrd_end = 0x885f6875ull;
}

static void admit_tests(void)
{
	struct tgl_fdt_memory m;
	struct tgl_chooser_ios_layout o;
	uint64_t n, isz, at;
	synthetic_memory(&m);
	const uint64_t head_pa = 0x80000000ull, dtb = 0x8a000000ull;
	uint8_t *pl = mkpayload(0x882000000ull, 0x100000000ull, &n);
	uint8_t *b = mkimage(0x2a0000, pl, n, 4096, &isz, &at);
	const char *e = tgl_chooser_ios_admit(b, head_pa, isz, 0x2a0000, dtb, &m, &o);
	CHECK(!e, "valid payload admitted at window 0x882000000");
	if (e) printf("  admit: %s\n", e);
	m.initrd_fields = 0;
	CHECK(tgl_chooser_ios_admit(b, head_pa, isz, 0x2a0000, dtb, &m, &o) != 0, "no initrd extent -> refused (loader.c would)");
	synthetic_memory(&m);
	CHECK(tgl_chooser_ios_admit(b, 0x85f00000ull, isz, 0x2a0000, dtb, &m, &o) != 0, "shim code overlapping the initrd refused");
	b[0x2a0000 + 16] ^= 1;	/* TEGUXNU magic */
	CHECK(tgl_chooser_ios_admit(b, head_pa, isz, 0x2a0000, dtb, &m, &o) != 0, "corrupt payload header -> no iOS entry");
	free(b); free(pl);
	/* window over the shim's own image (low bank) */
	pl = mkpayload(0x80000000ull, 0x10000000ull, &n);
	b = mkimage(0x2a0000, pl, n, 4096, &isz, &at);
	CHECK(tgl_chooser_ios_admit(b, head_pa, isz, 0x2a0000, dtb, &m, &o) != 0, "window over the loaded image refused");
	free(b); free(pl);
	/* window over the ramoops zone (TSHIMST2) */
	pl = mkpayload(0x94000000ull, 0x4000000ull, &n);
	b = mkimage(0x2a0000, pl, n, 4096, &isz, &at);
	CHECK(tgl_chooser_ios_admit(b, head_pa, isz, 0x2a0000, dtb, &m, &o) != 0, "window over ramoops refused");
	free(b); free(pl);
	/* window outside RAM */
	pl = mkpayload(0xc80000000ull, 0x100000000ull, &n);
	b = mkimage(0x2a0000, pl, n, 4096, &isz, &at);
	CHECK(tgl_chooser_ios_admit(b, head_pa, isz, 0x2a0000, dtb, &m, &o) != 0, "window outside FDT RAM refused");
	free(b); free(pl);
}

static void menu_tests(void)
{
	struct tgl_chooser_menu s;
	/* attended test image: default iOS, no keys */
	tgl_chooser_menu_init(&s, 0, 1);
	s.sel = tgl_chooser_ios_initial_sel(1, 1);
	CHECK(tgl_chooser_menu_step(&s, 4999, 0) == TGL_CHOOSE_PENDING, "pending before timeout");
	unsigned r = tgl_chooser_menu_step(&s, 5000, 0);
	CHECK(r == TGL_CHOOSE_IOS && s.why == TGL_WHY_TIMEOUT && tgl_chooser_ios_action(r, 1) == TGL_IOS_ACT_XNU, "default-iOS image boots iOS on timeout");
	/* the same image with the entry refused at admission: Android */
	CHECK(tgl_chooser_ios_initial_sel(0, 1) == 0, "no admitted entry -> start on Android");
	tgl_chooser_menu_init(&s, 0, 0);
	s.sel = tgl_chooser_ios_initial_sel(0, 1);
	r = tgl_chooser_menu_step(&s, 5000, 0);
	CHECK(r == TGL_CHOOSE_ANDROID && tgl_chooser_ios_action(r, 0) == TGL_IOS_ACT_ANDROID, "refused entry -> Android");
	/* installable image: Android default, Volume Down picks iOS */
	tgl_chooser_menu_init(&s, 0, 1);
	s.sel = tgl_chooser_ios_initial_sel(1, 0);
	CHECK(s.sel == 0, "installable image starts on Android");
	tgl_chooser_menu_step(&s, 1000, TGL_KEY_DOWN);
	tgl_chooser_menu_step(&s, 1100, 0);
	CHECK(tgl_chooser_menu_step(&s, 3999, 0) == TGL_CHOOSE_PENDING, "grace after the key");
	r = tgl_chooser_menu_step(&s, 5000, 0);
	CHECK(r == TGL_CHOOSE_IOS && s.why == TGL_WHY_KEYS && tgl_chooser_ios_action(r, 1) == TGL_IOS_ACT_XNU, "Volume Down -> iOS");
	/* no keys at all (keys lane absent or faulted): Android */
	tgl_chooser_menu_init(&s, 0, 1);
	r = tgl_chooser_menu_step(&s, 5000, 0);
	CHECK(r == TGL_CHOOSE_ANDROID && tgl_chooser_ios_action(r, 1) == TGL_IOS_ACT_ANDROID, "no keys -> Android");
	/* defensive: an IOS result with no entry never becomes XNU */
	CHECK(tgl_chooser_ios_action(TGL_CHOOSE_IOS, 0) == TGL_IOS_ACT_ANDROID, "IOS without entry -> Android");
	CHECK(tgl_chooser_ios_action(TGL_CHOOSE_PENDING, 1) == TGL_IOS_ACT_ANDROID, "pending -> Android");
	CHECK(TGL_CHOOSER_PICKED_IOS != 0 && TGL_CHOOSER_PICKED_IOS[0], "handback sentinel is a non-null string");
}

/* chooser-v1-r13 on the iOS menu (keys/DIAG-r13.md). r12's loop sampled the keys only between ~3.97 s redraws;
 * here the loop sees "seen" (keys held at any row-hook sample during the last redraw). Times are ms from boot. */
static unsigned tick(struct tgl_chooser_menu *s, uint64_t start, uint64_t t, unsigned k, unsigned seen, unsigned *secs)
{
	return tgl_chooser_ios_menu_tick(s, start, t, k, seen, secs);
}

/* The loop at r12's speed: one sample per redraw of 3970 ms, starting at start+1000 (chooser.c's first redraw).
 * press_lo..press_hi is a key held during one redraw only (released before the next sample). */
static unsigned slow_loop(struct tgl_chooser_menu *s, uint64_t start, unsigned key, uint64_t press_lo, uint64_t press_hi,
	uint64_t *at)
{
	unsigned secs = 0, r = 0;
	uint64_t prev = start;
	for (uint64_t t = start; t < start + 60000; t = t == start ? start + 1000 : t + 3970) {
		unsigned seen = key && press_lo < t && press_hi > prev ? key : 0;	/* the hook saw it during [prev, t) */
		if ((r = tick(s, start, t, 0, seen, &secs))) { *at = t; return r; }
		prev = t;
	}
	*at = 0;
	return r;
}

static unsigned fake_keys_seq[8], fake_keys_n, fake_keys_i;
static unsigned fake_keys(void) { return fake_keys_i < fake_keys_n ? fake_keys_seq[fake_keys_i++] : 0; }

static void r13_tests(void)
{
	struct tgl_chooser_menu s;
	unsigned secs = 99, r;
	uint64_t at, start = 7800;	/* r9/r10: the menu came up ~7.8 s after shim entry */

	/* installable image (default Android, entry admitted): a Vol Down press that started and ended inside one redraw */
	tgl_chooser_menu_init(&s, start, 1);
	s.sel = tgl_chooser_ios_initial_sel(1, 0);
	r = slow_loop(&s, start, TGL_KEY_DOWN, start + 1500, start + 1700, &at);
	CHECK(r == TGL_CHOOSE_IOS && s.why == TGL_WHY_KEYS && s.presses == 1, "r13 iOS: Vol Down inside a 3.97 s redraw picks iOS");
	CHECK(tgl_chooser_ios_action(r, 1) == TGL_IOS_ACT_XNU, "r13 iOS: that pick hands back to the iOS path");
	/* r12's loop (no seen bits) on the same timing: the press is lost and the countdown boots Android */
	tgl_chooser_menu_init(&s, start, 1);
	r = slow_loop(&s, start, 0, 0, 0, &at);
	CHECK(r == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_TIMEOUT, "r13 iOS: hands off -> Android by timeout");
	CHECK(at >= start + TGL_CHOOSER_TIMEOUT_MS && at <= start + TGL_CHOOSER_MENU_MAX_MS, "r13 iOS: timeout pick inside the hard end");

	/* C3 sequence: Vol Down (iOS), then Vol Up (Android), each seen only during a redraw */
	tgl_chooser_menu_init(&s, start, 1);
	CHECK(!tick(&s, start, start + 100, 0, 0, &secs) && secs == 5, "r13 iOS: countdown shows 5 at the start");
	CHECK(!tick(&s, start, start + 1000, 0, TGL_KEY_DOWN, &secs) && s.sel == 1, "r13 iOS: Vol Down seen -> ring on iOS");
	CHECK(secs == 4, "r13 iOS: a press inside the countdown keeps the number");
	CHECK(!tick(&s, start, start + 2500, 0, TGL_KEY_UP, &secs) && s.sel == 0 && s.presses == 2, "r13 iOS: Vol Up seen -> ring on Android");
	CHECK(secs == 3, "r13 iOS: grace after the last press (3 s)");
	CHECK(!tick(&s, start, start + 5499, 0, 0, &secs), "r13 iOS: pending until the grace ends");
	r = tick(&s, start, start + 5500, 0, 0, &secs);
	CHECK(r == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_KEYS, "r13 iOS: Down then Up -> Android");
	/* a press held across two samples is one press, not two (seen and held together) */
	tgl_chooser_menu_init(&s, start, 1);
	tick(&s, start, start + 1000, TGL_KEY_DOWN, TGL_KEY_DOWN, &secs);
	tick(&s, start, start + 1100, TGL_KEY_DOWN, TGL_KEY_DOWN, &secs);
	tick(&s, start, start + 1200, 0, TGL_KEY_DOWN, &secs);
	CHECK(s.presses == 1 && s.sel == 1, "r13 iOS: a held key is one press");
	/* a chord seen during a redraw is ignored */
	tgl_chooser_menu_init(&s, start, 1);
	tick(&s, start, start + 1000, 0, TGL_KEY_DOWN | TGL_KEY_UP, &secs);
	CHECK(s.presses == 0 && s.sel == 0, "r13 iOS: chord ignored");

	/* default-iOS image: no press -> iOS; the number counts 5..1 and one redraw per number */
	tgl_chooser_menu_init(&s, start, 1);
	s.sel = tgl_chooser_ios_initial_sel(1, 1);
	unsigned shown = 5, redraws = 0;
	for (uint64_t t = start; ; t += 10) {
		if ((r = tick(&s, start, t, 0, 0, &secs))) break;
		if (secs != shown) { redraws++; shown = secs; }
	}
	CHECK(r == TGL_CHOOSE_IOS && s.why == TGL_WHY_TIMEOUT, "r13 iOS: default-iOS image -> iOS by timeout");
	CHECK(redraws == 4 && shown == 1, "r13 iOS: redraws only when the number changes (4 in 5 s)");
	/* default-iOS image, Vol Up seen -> Android */
	tgl_chooser_menu_init(&s, start, 1);
	s.sel = 1;
	r = slow_loop(&s, start, TGL_KEY_UP, start + 3000, start + 3200, &at);
	CHECK(r == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_KEYS, "r13 iOS: default iOS, Vol Up -> Android");
	/* entry refused at admission: Vol Down still moves the ring, the pick is Android (NO_IOS) */
	tgl_chooser_menu_init(&s, start, 0);
	r = slow_loop(&s, start, TGL_KEY_DOWN, start + 1500, start + 1700, &at);
	CHECK(r == TGL_CHOOSE_ANDROID && s.why == TGL_WHY_NO_IOS && tgl_chooser_ios_action(r, 0) == TGL_IOS_ACT_ANDROID,
	    "r13 iOS: refused entry, Vol Down -> Android (NO_IOS)");

	/* hard end: a press every 2 s never keeps the menu past start + 15 s */
	tgl_chooser_menu_init(&s, start, 1);
	r = 0;
	uint64_t t, end = 0;
	unsigned over = 0;
	for (t = start; t < start + 40000 && !r; t += 50) {
		unsigned k = ((t - start) / 2000) % 2 ? TGL_KEY_DOWN : TGL_KEY_UP;
		unsigned seen = (t - start) % 2000 == 1000 ? k : 0;
		r = tick(&s, start, t, 0, seen, &secs);
		if (r) end = t;
		else over += s.deadline_ms > start + TGL_CHOOSER_MENU_MAX_MS || secs > 5;
	}
	CHECK(over == 0, "r13 iOS: deadline and number stay inside the hard end");
	/* a press seen at the very sample of the hard end costs one more loop pass, as in chooser.c */
	CHECK(r && end >= start + TGL_CHOOSER_MENU_MAX_MS && end <= start + TGL_CHOOSER_MENU_MAX_MS + 50, "r13 iOS: menu ends at the 15 s hard end");

	/* the shared helpers (chooser_menu_r13.h) */
	fake_keys_seq[0] = 0; fake_keys_seq[1] = TGL_KEY_DOWN; fake_keys_seq[2] = 0; fake_keys_n = 3; fake_keys_i = 0;
	chooser_tick_keys = fake_keys; chooser_tick_seen = 0; chooser_ticks = 0;
	for (int i = 0; i < 5; i++) chooser_menu_tick();
	CHECK(chooser_ticks == 5 && chooser_tick_seen == TGL_KEY_DOWN, "r13 helper: row tick ORs the keys seen during a redraw");
	chooser_tick_keys = 0;
	chooser_menu_tick();
	CHECK(chooser_ticks == 6, "r13 helper: row tick without a key reader only counts");
	fake_dcs_entries = TGL_DCS_CAPACITY - 8u - TGL_CHOOSER_PRESENT_COST - TGL_CHOOSER_DCS_RESERVE - 1u;
	CHECK(chooser_dcs_room(), "r13 helper: present allowed while the release keeps its room");
	fake_dcs_entries++;
	CHECK(!chooser_dcs_room() && fake_dcs_entries == 1204u, "r13 helper: no present from 1204 record entries on");
	size_t px = (size_t)TGL_MENU_W * TGL_MENU_H;
	uint32_t *fb = malloc(px * 4), *sh = malloc(px * 4);
	for (size_t i = 0; i < px; i++) { fb[i] = 0x11111111u; sh[i] = (uint32_t)(i * 2654435761u); }
	chooser_band_copy(fb, sh);
	size_t bad = 0, lo = (size_t)TGL_MENU_BAND_Y0 * TGL_MENU_W, hi = (size_t)TGL_MENU_BAND_Y1 * TGL_MENU_W;
	for (size_t i = 0; i < px; i++) bad += i >= lo && i < hi ? fb[i] != sh[i] : fb[i] != 0x11111111u;
	CHECK(bad == 0, "r13 helper: band copy writes exactly the band rows");
	free(fb); free(sh);
}

static uint8_t *slurp(const char *path, uint64_t *n)
{
	FILE *f = fopen(path, "rb");
	if (!f) { perror(path); exit(2); }
	fseek(f, 0, SEEK_END); long l = ftell(f); rewind(f);
	uint8_t *b = aligned_alloc(16, ((uint64_t)l + 15) & ~15ull);
	if (fread(b, 1, (size_t)l, f) != (size_t)l) { perror(path); exit(2); }
	fclose(f);
	*n = (uint64_t)l;
	return b;
}

/* The real A0 FDT (ABL's tree for a normal Android boot, the chooser's case), the real payload,
 * the real stock lz4 size: admission at ABL's load address and the Android placement above it. */
static void real_tests(const char *dtb_path, const char *pl_path, uint64_t lz4_bytes, uint64_t shim_end)
{
	struct tgl_fdt_memory m;
	uint64_t fn, pn, isz, at;
	uint8_t *fdt = slurp(dtb_path, &fn);
	memset(&m, 0, sizeof m);
	const char *e = tgl_fdt_memory(fdt, fn, &m);
	CHECK(!e, "A0 FDT parses");
	if (e) return;
	if (!pl_path) return;
	uint8_t *pl = slurp(pl_path, &pn);
	uint8_t *b = mkimage(shim_end, pl, pn, lz4_bytes, &isz, &at);
	const uint64_t head_pa = 0x80000000ull, dtb = 0x8a000000ull;	/* chooser_test.c: ABL load, r1 FDT stamp */
	struct tgl_chooser_ios_layout o;
	e = tgl_chooser_ios_admit(b, head_pa, isz, shim_end, dtb, &m, &o);
	const struct payload *p = (const struct payload *)pl;
	printf("A0 admit: payload %llu B window 0x%llx+0x%llx image_size %llu: %s\n", (unsigned long long)pn,
	    (unsigned long long)p->phys_base, (unsigned long long)p->mem_size, (unsigned long long)isz, e ? e : "ok");
	CHECK(!e, "real payload admitted against the A0 FDT");
	struct tgl_range live[4] = { { head_pa, isz }, { dtb, m.total_size },
		{ m.initrd_start, m.initrd_end - m.initrd_start }, { 0xf0000000ull, 1280ull * 4 * 2856 } };
	uint64_t base = 0;
	e = tgl_chooser_place(&m, 43253760ull, live, 4, &base);
	printf("A0 Android placement above a %llu B image: %s base 0x%llx\n", (unsigned long long)isz, e ? e : "ok", (unsigned long long)base);
	CHECK(!e && base >= head_pa + isz, "Android Image placed above the combined image");
	CHECK(!(base < p->phys_base + p->mem_size && p->phys_base < base + 43253760ull), "Android Image clear of the XNU window");
	CHECK(head_pa + isz <= m.initrd_start, "combined image ends below ABL's initrd (0x86000000)");
	free(b); free(pl); free(fdt);
}

int main(int argc, char **argv)
{
	layout_tests();
	admit_tests();
	menu_tests();
	r13_tests();
	if (argc > 1)
		real_tests(argv[1], argc > 2 ? argv[2] : 0, argc > 3 ? strtoull(argv[3], 0, 0) : 20437225ull,
		    argc > 4 ? strtoull(argv[4], 0, 0) : 0x2a0000ull);
	printf("chooser-ios host test: %u checks, %u failed\n", checks, fails);
	return fails != 0;
}
