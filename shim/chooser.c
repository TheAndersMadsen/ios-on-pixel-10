/* A2 boot chooser: menu state machine, stock-kernel segment, placement and
 * the EL2 chain-load into the stock Android kernel. Gate TGL_CHOOSER=1.
 *
 * Contract (GOAL.md section 6, Architecture): the Android branch leaves the
 * FDT and initrd exactly as ABL built them, never quiesces a watchdog (pats
 * only), never touches display/USB/UFS/CPM/clock hardware, and enters the
 * stock Image at EL2 with MMU and D-cache off, interrupts masked, x0 = FDT,
 * x1..x3 = 0 (Documentation/arch/arm64/booting.rst). The decompressed Image
 * goes to the lowest 2 MiB-aligned base that the FDT memory map, every
 * reservation, the FDT, the initrd, the shim image and the console buffer
 * all allow (tgl_chooser_place). Nothing here writes storage. */
#include "chooser.h"
#include "lz4.h"

#define CSUM_SEED UINT64_C(0xcbf29ce484222325)
#define CSUM_MUL  UINT64_C(0x00000100000001b3)

static uint64_t ld64(const uint8_t *p, uint64_t n)
{
	/* p is 8-byte aligned; n < 8 only for the zero-padded last word. */
	if (n >= 8) return *(const volatile uint64_t *)(const void *)p;
	uint64_t w = 0;
	for (uint64_t i = 0; i < n; i++) w |= (uint64_t)p[i] << (8 * i);
	return w;
}

/* FNV-1a over little-endian u64 words (last one zero-padded), then the
 * length: an integrity check against truncated or shifted loads, not a
 * security boundary (the image hash is bound on the host). Word loads keep
 * it under a second on Device memory. tools/chooser_image.py mirrors it. */
uint64_t tgl_chooser_csum64(const uint8_t *p, uint64_t n)
{
	uint64_t h = CSUM_SEED;
	for (uint64_t i = 0; i < n; i += 8) {
		h ^= ld64(p + i, n - i < 8 ? n - i : 8);
		h *= CSUM_MUL;
	}
	return h ^ n;
}

static int memeq(const uint8_t *a, const char *b, unsigned n)
{
	for (unsigned i = 0; i < n; i++)
		if (a[i] != (uint8_t)b[i]) return 0;
	return 1;
}

static uint64_t le64(const uint8_t *p)
{
	uint64_t v = 0;
	for (unsigned i = 0; i < 8; i++) v |= (uint64_t)p[i] << (8 * i);
	return v;
}

const char *tgl_chooser_seg_parse(const uint8_t *p, uint64_t avail,
	struct tgl_chooser_seg *o)
{
	if (((uintptr_t)p & 7) != 0) return "segment not 8-byte aligned";
	if (avail < TGL_CHOOSER_SEG_HDR) return "no room for a segment header";
	if (!memeq(p, TGL_CHOOSER_SEG_MAGIC, 8)) return "no TGLLNX01 segment";
	o->comp_len = le64(p + 8);
	o->image_len = le64(p + 16);
	o->image_size = le64(p + 24);
	o->image_flags = le64(p + 32);
	o->csum = le64(p + 40);
	if (le64(p + 48) != tgl_chooser_csum64(p, 48)) return "segment header checksum";
	if (le64(p + 56) != 0) return "segment reserved word nonzero";
	if (!o->comp_len || o->comp_len > avail - TGL_CHOOSER_SEG_HDR)
		return "segment runs past the loaded image";
	if (!o->image_len || o->image_len > o->image_size) return "Image length above image_size";
	if (o->image_size > TGL_CHOOSER_MAX_IMAGE) return "Image image_size implausible";
	/* Linux header flags: bit0 BE (must be 0), bits1-2 page size (1 = 4K),
	 * bit3 placeable anywhere (required: we choose the base). */
	if (o->image_flags & 1) return "big-endian Image";
	if (((o->image_flags >> 1) & 3) != 1) return "Image is not 4K-page";
	if (!(o->image_flags & 8)) return "Image not placeable at any 2 MiB base";
	o->data = p + TGL_CHOOSER_SEG_HDR;
	return 0;
}

const char *tgl_chooser_place(const struct tgl_fdt_memory *m, uint64_t size,
	const struct tgl_range *live, unsigned live_count, uint64_t *base)
{
	uint64_t best = 0;
	int found = 0;
	if (!size) return "zero placement size";
	for (unsigned r = 0; r < m->ram_count; r++) {
		uint64_t lo = m->ram[r].base, hi = lo + m->ram[r].size;
		if (hi < lo) continue;
		uint64_t c = (lo + TGL_CHOOSER_ALIGN - 1) & ~(TGL_CHOOSER_ALIGN - 1);
		for (; c >= lo && c + size > c && c + size <= hi; c += TGL_CHOOSER_ALIGN) {
			if (found && c >= best) break;
			struct tgl_range w = { c, size };
			if (!tgl_window_check(m, w, live, live_count)) {
				best = c;
				found = 1;
				break;
			}
		}
	}
	if (!found) return "no 2 MiB-aligned RAM window fits the stock Image";
	*base = best;
	return 0;
}

void tgl_chooser_menu_init(struct tgl_chooser_menu *s, uint64_t now_ms,
	unsigned ios_available)
{
	s->sel = 0;
	s->ios_available = ios_available;
	s->result = TGL_CHOOSE_PENDING;
	s->why = TGL_WHY_NONE;
	s->presses = 0;
	s->deadline_ms = now_ms + TGL_CHOOSER_TIMEOUT_MS;
	s->last_key_ms = 0;
	s->prev_keys = 0;
}

unsigned tgl_chooser_menu_step(struct tgl_chooser_menu *s, uint64_t now_ms,
	unsigned keys)
{
	if (s->result != TGL_CHOOSE_PENDING) return s->result;
	unsigned edges = keys & ~s->prev_keys;
	s->prev_keys = keys;
	/* Never two keys at once: a chord is ignored, not interpreted. */
	if (edges == TGL_KEY_UP || edges == TGL_KEY_DOWN) {
		s->sel = edges == TGL_KEY_DOWN ? 1u : 0u;
		s->presses++;
		s->last_key_ms = now_ms;
		uint64_t d = now_ms + TGL_CHOOSER_KEY_GRACE_MS;
		if (d > s->deadline_ms) s->deadline_ms = d;
	}
	if (now_ms < s->deadline_ms) return TGL_CHOOSE_PENDING;
	if (s->sel == 1 && !s->ios_available) {
		s->result = TGL_CHOOSE_ANDROID;
		s->why = TGL_WHY_NO_IOS;
	} else {
		s->result = s->sel ? TGL_CHOOSE_IOS : TGL_CHOOSE_ANDROID;
		s->why = s->presses ? TGL_WHY_KEYS : TGL_WHY_TIMEOUT;
	}
	return s->result;
}

#ifndef TGL_CHOOSER_HOST
#include "console.h"
#include "tgl_stamp.h"
#if TGL_CHOOSER_MMU
#include "el2_mmu.h"
static struct tgl_el2_tables el2t __attribute__((aligned(4096)));
#endif
#if TGL_CHOOSER_UI
#include "menu_ui.h"
#endif
#if TGL_CHOOSER_DISPLAY
#include "tgl_dcs.h"
#include "guard.h"
#endif

extern char _head[], _end[];

#define SCTLR_M (UINT64_C(1) << 0)
#define SCTLR_C (UINT64_C(1) << 2)
#define CHOOSER_FB UINT64_C(0xf0000000)	/* shim.c TGL_FB_FALLBACK: plain DRAM */
#define BLACK 0xff000000U

static uint64_t now_ms(void)
{
	uint64_t f, t;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(f));
	__asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(t));
	if (!f) f = 38400000;
	return t / (f / 1000);
}

static void (*chooser_pat)(void);
static void lz4_tick(void) { if (chooser_pat) chooser_pat(); }

static void __attribute__((noreturn)) chain_jump(uint64_t entry, uint64_t fdt)
{
	register uint64_t x0 __asm__("x0") = fdt;
	register uint64_t x1 __asm__("x1") = 0;
	register uint64_t x2 __asm__("x2") = 0;
	register uint64_t x3 __asm__("x3") = 0;
	register uint64_t x4 __asm__("x4") = entry;
	__asm__ volatile("msr daifset, #0xf\n\tdsb sy\n\tisb\n\tbr x4"
	    :: "r"(x0), "r"(x1), "r"(x2), "r"(x3), "r"(x4) : "memory");
	__builtin_unreachable();
}

#if TGL_CHOOSER_MMU
/* Registers only: clean+invalidate the decoded Image to PoC, restore the entry
 * SCTLR_EL2 (MMU and caches off), drop I-cache and EL2 TLBs, enter Linux. */
static void __attribute__((noreturn)) chain_jump_mmu_off(uint64_t sctlr, uint64_t lo,
	uint64_t hi, uint64_t entry, uint64_t fdt)
{
	register uint64_t x0 __asm__("x0") = sctlr;
	register uint64_t x1 __asm__("x1") = lo;
	register uint64_t x2 __asm__("x2") = hi;
	register uint64_t x3 __asm__("x3") = entry;
	register uint64_t x4 __asm__("x4") = fdt;
	__asm__ volatile(
	    "msr daifset, #0xf\n\t"
	    "mov x5, x3\n\t"
	    "mrs x9, ctr_el0\n\t"
	    "ubfx x9, x9, #16, #4\n\t"
	    "mov x10, #4\n\t"
	    "lsl x10, x10, x9\n\t"
	    "sub x11, x10, #1\n\t"
	    "bic x1, x1, x11\n"
	    "1:\tdc civac, x1\n\t"
	    "add x1, x1, x10\n\t"
	    "cmp x1, x2\n\t"
	    "b.lo 1b\n\t"
	    "dsb sy\n\t"
	    "msr sctlr_el2, x0\n\t"
	    "isb\n\t"
	    "ic iallu\n\t"
	    "tlbi alle2\n\t"
	    "dsb sy\n\t"
	    "isb\n\t"
	    "mov x0, x4\n\t"
	    "mov x1, xzr\n\t"
	    "mov x2, xzr\n\t"
	    "mov x3, xzr\n\t"
	    "br x5"
	    :: "r"(x0), "r"(x1), "r"(x2), "r"(x3), "r"(x4) : "x5", "x9", "x10", "x11", "memory");
	__builtin_unreachable();
}
#endif

/* Our stores went straight to memory (SCTLR_EL2.C=0); any line ABL left
 * for these addresses is stale, so discard it rather than clean it. */
static void inval_dcache(uint64_t lo, uint64_t hi)
{
	uint64_t ctr;
	__asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
	uint64_t line = UINT64_C(4) << ((ctr >> 16) & 0xf);
	for (uint64_t a = lo & ~(line - 1); a < hi; a += line)
		__asm__ volatile("dc ivac, %0" :: "r"(a) : "memory");
	__asm__ volatile("dsb sy\n\tic iallu\n\tdsb sy\n\tisb" ::: "memory");
}

#if !TGL_CHOOSER_UI
static void con_dec(const char *label, uint64_t v)
{
	char b[24];
	int i = 23;
	b[i] = 0;
	do { b[--i] = (char)('0' + v % 10); v /= 10; } while (v && i);
	con_str(label, b + i);
}
#endif

const char *tgl_chooser_run(uint64_t dtb, const struct tgl_fdt_memory *m,
	void (*pat)(void), unsigned (*keys)(void))
{
	uint64_t el, sctlr = 0;
	chooser_pat = pat;
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
	el = (el >> 2) & 3;
	if (el == 2) __asm__ volatile("mrs %0, sctlr_el2" : "=r"(sctlr));
	tgl_stamp(TGL_STAGE_CHOOSER_ENTER, TGL_STAMP_F_ENTER, el << 32 | (uint32_t)sctlr);
	if (el != 2) return "chooser: Android needs EL2 entry";
	if (sctlr & (SCTLR_M | SCTLR_C)) return "chooser: MMU or D-cache on at entry";

	/* The segment follows _end, after the XNU envelope when one exists. */
	const uint8_t *head = (const uint8_t *)_head;
	uint64_t isz = *(const volatile uint64_t *)(const void *)(head + 16);
	const uint8_t *p = (const uint8_t *)_end;
	if ((uint64_t)(p - head) > isz) return "chooser: image_size below _end";
	if (memeq(p, "TEGUPLD1", 8)) {
		uint64_t n = le64(p + 8);
		if (n > isz - (uint64_t)(p - head) - 16) return "chooser: XNU envelope past image";
		p += 16 + n;
		p += (8 - ((uintptr_t)p & 7)) & 7;
	}
	struct tgl_chooser_seg seg;
	uint64_t avail = isz > (uint64_t)(p - head) ? isz - (uint64_t)(p - head) : 0;
	const char *why = tgl_chooser_seg_parse(p, avail, &seg);
	tgl_stamp(TGL_STAGE_CHOOSER_SEG, why ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
	    why ? (uint64_t)(uintptr_t)p : seg.comp_len);
	if (why) return why;
	struct tgl_range live[4];
	unsigned nl = 0;
	live[nl++] = (struct tgl_range){ (uint64_t)(uintptr_t)head, isz };
	live[nl++] = (struct tgl_range){ dtb, m->total_size ? m->total_size : TGL_FDT_MAX_SIZE };
	if ((m->initrd_fields & 3) == 3 && m->initrd_end > m->initrd_start)
		live[nl++] = (struct tgl_range){ m->initrd_start, m->initrd_end - m->initrd_start };
	live[nl++] = (struct tgl_range){ CHOOSER_FB, (uint64_t)FB_STRIDE * FB_H };
	uint64_t base = 0;
	why = tgl_chooser_place(m, seg.image_size, live, nl, &base);
	tgl_stamp(TGL_STAGE_CHOOSER_PLACE, why ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE, base);
	if (why) return why;

	int cached = 0;
	uint64_t sctlr0 = sctlr;
#if TGL_CHOOSER_MMU
	{
		struct tgl_el2_region rg[3] = {
			{ (uint64_t)(uintptr_t)head, isz, TGL_EL2_WB, 1 },
			{ base, seg.image_size, TGL_EL2_WB, 0 },
			{ CHOOSER_FB, (uint64_t)FB_STRIDE * FB_H, TGL_EL2_NC, 0 },
		};
		const char *mw = tgl_el2_build(&el2t, m, rg, 3);
		if (!mw) mw = tgl_el2_mmu_on(&el2t, rg, 3, &sctlr0);
		cached = !mw;
		tgl_stamp(TGL_STAGE_CHOOSER_MMU, mw ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (uint64_t)el2t.wb_blocks << 32 | (uint64_t)el2t.nc_blocks << 16 | el2t.refused_blocks);
		/* A refusal keeps the proven uncached path (chooser-v1-r1-t1). */
	}
#endif
	uint64_t t0 = now_ms();
	uint64_t c = tgl_chooser_csum64(seg.data, seg.comp_len);
	tgl_stamp(TGL_STAGE_CHOOSER_CSUM, c == seg.csum ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED,
	    (now_ms() - t0) << 32 | (uint32_t)c);
	if (c != seg.csum) return "chooser: stock kernel checksum mismatch";
	if (pat) pat();

#if TGL_CHOOSER_UI
	struct tgl_menu_view view = { 0, TGL_CHOOSER_TIMEOUT_MS / 1000, 0 };
	uint32_t *fb = (uint32_t *)(uintptr_t)CHOOSER_FB;
	t0 = now_ms();
	tgl_menu_draw(fb, FB_W, &view);
	tgl_stamp(TGL_STAGE_CHOOSER_UI, TGL_STAMP_F_DONE, (now_ms() - t0) << 32 | (uint32_t)cached);
	if (pat) pat();
#if TGL_CHOOSER_DISPLAY
	/* Show it: the display-frame-r1d ladder, full-panel layer at the menu buffer (SCANOUT-PATH.md). A refusal
	 * leaves the panel dark and the chain unchanged; a pending SError would reach Linux, so that resets. */
	int shown = 0;
	{
		static const uint8_t dn[16] = TGL_UFS_RECORD_NONCE;
		uint64_t isr;
		t0 = now_ms();
		__asm__ volatile("dsb sy" ::: "memory");
		tgl_dcs_begin(TGL_STAMP_NONCE, dn, TGL_UFS_EPOCH);
		unsigned drc = tgl_dcs_guarded();
		tgl_dcs_finish((int)drc, tgl_guard_esr, tgl_guard_far, 0);
		if (pat) pat();
		__asm__ volatile("mrs %0, isr_el1" : "=r"(isr));
		tgl_stamp(TGL_STAGE_CHOOSER_DISPLAY, drc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (now_ms() - t0) << 32 | (uint64_t)(isr & 0x100) << 8 | drc);
		if (isr & 0x100) return "chooser: display left an SError pending";
		shown = drc == 0;
	}
#endif
#else
	con_tick = pat;
	con_init((uintptr_t)CHOOSER_FB);
	con_clear(BLACK);
	con_str("BOOT", "Vol-Up: Android   Vol-Down: iOS");
	con_str("IOS", "no iOS root yet: Android only");
	con_hex("LINUX", base);
#endif
	struct tgl_chooser_menu s;
	uint64_t start = now_ms(), last_pat = start, last_line = start;
	tgl_chooser_menu_init(&s, start, 0);
	tgl_stamp(TGL_STAGE_CHOOSER_MENU, TGL_STAMP_F_ENTER, TGL_CHOOSER_TIMEOUT_MS);
	unsigned r, held = 0;
	for (;;) {
		uint64_t t = now_ms();
		unsigned k = keys ? keys() : 0;
		if (k != held) {
			tgl_stamp(TGL_STAGE_CHOOSER_KEY, TGL_STAMP_F_DONE, (t - start) << 8 | k);
			held = k;
		}
		r = tgl_chooser_menu_step(&s, t, k);
		if (r) break;
		if (t - last_pat >= 1000) { if (pat) pat(); last_pat = t; }
		if (t - last_line >= 1000) {
#if TGL_CHOOSER_UI
			view.sel = s.sel;
			view.seconds = (unsigned)((s.deadline_ms - t + 999) / 1000);
			tgl_menu_draw_band(fb, FB_W, &view);
#if TGL_CHOOSER_DISPLAY
			if (shown) {
				__asm__ volatile("dsb sy" ::: "memory");
				int prc = tgl_dcs_present();
				if (prc) {
					shown = 0;
					tgl_stamp(TGL_STAGE_CHOOSER_DISPLAY, TGL_STAMP_F_REFUSED, (uint64_t)1 << 40 | (uint32_t)prc);
				}
			}
#endif
#else
			con_dec(s.sel ? "iOS T-" : "ANDROID T-", (s.deadline_ms - t + 999) / 1000);
#endif
			last_line = t;
		}
		for (volatile unsigned d = 0; d < 20000; d++) { }
	}
	tgl_stamp(TGL_STAGE_CHOOSER_PICK, TGL_STAMP_F_DONE,
	    (now_ms() - start) << 8 | r << 4 | s.why);
	if (r != TGL_CHOOSE_ANDROID) return "chooser: iOS entry not built in this image";
#if !TGL_CHOOSER_UI
	con_str("PICK", s.why == TGL_WHY_NO_IOS ? "Android (no iOS root yet)" : "Android");
#endif

	if (pat) pat();
	t0 = now_ms();
	tgl_stamp(TGL_STAGE_CHOOSER_LZ4, TGL_STAMP_F_ENTER, base);
	uint64_t out = 0;
	int rc = tgl_lz4_legacy_decode(seg.data, seg.comp_len, (uint8_t *)(uintptr_t)base,
	    seg.image_size, &out, lz4_tick);
	tgl_stamp(TGL_STAGE_CHOOSER_LZ4, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
	    (now_ms() - t0) << 32 | (uint32_t)out);
	if (rc || out != seg.image_len) return "chooser: stock kernel decode failed";

	const uint8_t *img = (const uint8_t *)(uintptr_t)base;
	uint32_t magic = (uint32_t)(le64(img + 56) & 0xffffffffu);
	int hdr_ok = magic == UINT32_C(0x644d5241) && le64(img + 16) == seg.image_size &&
	    le64(img + 24) == seg.image_flags;
	tgl_stamp(TGL_STAGE_CHOOSER_VERIFY, hdr_ok ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED,
	    (uint64_t)magic << 32 | (uint32_t)le64(img + 16));
	if (!hdr_ok) return "chooser: decoded Image header mismatch";

#if !TGL_CHOOSER_UI
	con_str("JUMP", "stock Android kernel, EL2");
#endif
	if (pat) pat();
	tgl_stamp(TGL_STAGE_CHOOSER_JUMP, TGL_STAMP_F_ENTER, base | (uint64_t)cached << 63);
#if TGL_CHOOSER_MMU
	if (cached) chain_jump_mmu_off(sctlr0, base, base + seg.image_size, base, dtb);
#endif
	(void)cached; (void)sctlr0;
	inval_dcache(base, base + seg.image_size);
	chain_jump(base, dtb);
}
#endif
