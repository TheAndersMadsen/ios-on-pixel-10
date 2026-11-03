/* Chooser with the iOS branch (gate TGL_CHOOSER_IOS=1; chooser_ios.h, DESIGN.md in
 * research/ios26-dualboot-r8/chooser-ios/). Replaces chooser.c in the source list of a
 * chooser-ios image: chooser.c is included here for its pure helpers only (segment, checksum,
 * placement, menu state machine), byte for byte; its device tgl_chooser_run is not compiled.
 *
 * Device contract, Android branch: as chooser.c (chooser-v1-r11 + keys): FDT and initrd as ABL
 * built them, watchdogs patted never quiesced, the r11 display release before the jump, stock
 * Image at EL2 with MMU and D-cache off, x0 = FDT.
 *
 * Device contract, iOS branch (new): the menu's display instance gives the DPU domain back
 * exactly as for Android (r11 release: quiesce, FE0/clock/DSI0/TOP off), then the EL2 MMU and
 * caches go off with every line of the loaded image cleaned to PoC and every cacheable range
 * invalidated, and tgl_chooser_run returns TGL_CHOOSER_PICKED_IOS. shim_main then runs the
 * direct iOS path: the CPU state (EL2, SCTLR_EL2 as at entry), watchdogs (armed, patted), DPU
 * (off, as ABL hands over), UFS (untouched) and memory (nothing written outside the shim's own
 * image and the menu buffer at 0xf0000000, which the console reuses) are what that path
 * starts from on a fastboot boot of the iOS image. Nothing here writes storage. */
#if defined(TGL_CHOOSER_HOST) || (defined(TGL_CHOOSER_IOS) && TGL_CHOOSER_IOS)
#ifndef TGL_CHOOSER_HOST
#define TGL_CHOOSER_HOST 1
#define CIOS_DEVICE 1
#endif
#include "chooser.c"
#ifdef CIOS_DEVICE
#undef TGL_CHOOSER_HOST
#endif
#include "chooser_ios.h"
#include "handoff.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-function"
#include "payload.h"
#pragma GCC diagnostic pop

const char tgl_chooser_picked_ios[] = "chooser: iOS picked; handed back to the iOS path";

#define RAMOOPS_BASE UINT64_C(0x95200000)	/* loader.c: TSHIMST2 and the kexec marker page */
#define RAMOOPS_SIZE UINT64_C(0x400000)

const char *tgl_chooser_ios_layout(const uint8_t *head, uint64_t isz, uint64_t end_off,
	struct tgl_chooser_ios_layout *o)
{
	if (!head || ((uintptr_t)head & 7)) return "image not 8-byte aligned";
	if (end_off & 7) return "_end not 8-byte aligned";
	if (end_off > isz || isz - end_off < 16) return "no room for an XNU envelope";
	const uint8_t *p = head + end_off;
	if (!memeq(p, "TEGUPLD1", 8)) return "no XNU envelope after _end";
	uint64_t n = le64(p + 8);
	/* Same bound as chooser.c and tgl_payload_embedded. */
	if (!n || n > isz - end_off - 16) return "XNU envelope past image_size";
	uint64_t seg = end_off + 16 + n;
	seg += (8 - (seg & 7)) & 7;
	if (seg > isz || isz - seg < TGL_CHOOSER_SEG_HDR) return "no Android segment after the XNU envelope";
	o->env_off = end_off;
	o->payload_off = end_off + 16;
	o->payload_bytes = n;
	o->seg_off = seg;
	return 0;
}

const char *tgl_chooser_ios_admit(const uint8_t *head, uint64_t head_pa, uint64_t isz,
	uint64_t end_off, uint64_t dtb, const struct tgl_fdt_memory *m,
	struct tgl_chooser_ios_layout *o)
{
	const char *e = tgl_chooser_ios_layout(head, isz, end_off, o);
	if (e) return e;
	/* loader.c's shim range is the code extent [_head, _end); the envelope is checked apart. */
	struct tgl_range code = { head_pa, end_off }, rd, none = { 0, 0 };
	if ((e = tgl_handoff_inputs(m, dtb, code, &rd))) return e;
	struct tgl_payload_view v;
	if ((e = tgl_payload_validate((uintptr_t)(head + o->payload_off), o->payload_bytes,
	    rd.base, rd.size, &v))) return e;
	const struct payload *p = v.payload;
	struct tgl_range win = { p->phys_base, p->mem_size };
	if ((e = tgl_handoff_window(m, win, dtb, code, rd, none))) return e;
	struct tgl_range image = { head_pa, isz }, ramoops = { RAMOOPS_BASE, RAMOOPS_SIZE };
	if (tgl_ranges_overlap(image, win)) return "XNU window overlaps the loaded image";
	if (tgl_ranges_overlap(win, ramoops)) return "payload window overlaps ramoops zone";
	uint64_t src_pa = head_pa + o->payload_off;
	if (tgl_ranges_overlap(rd, win) && src_pa <= p->phys_base)
		return "ramdisk below kernel window; ascending copy unsafe";
	struct tgl_range meta = { v.adt_pa, v.top - v.adt_pa };
	if (tgl_ranges_overlap(meta, rd)) return "metadata placement overlaps ramdisk";
	return 0;
}

unsigned tgl_chooser_ios_action(unsigned result, unsigned ios_available)
{
	return result == TGL_CHOOSE_IOS && ios_available ? TGL_IOS_ACT_XNU : TGL_IOS_ACT_ANDROID;
}

unsigned tgl_chooser_ios_initial_sel(unsigned ios_available, unsigned default_ios)
{
	return ios_available && default_ios ? 1u : 0u;
}

#if defined(CIOS_DEVICE) && TGL_CHOOSER_IOS
#if !TGL_CHOOSER_MMU || !TGL_CHOOSER_UI || !TGL_CHOOSER_DISPLAY
#error "TGL_CHOOSER_IOS builds on the chooser-v1-r11 line: TGL_CHOOSER_MMU, _UI and _DISPLAY must be 1"
#endif
#if TGL_CHOOSER_KEYS
#error "TGL_CHOOSER_IOS reads keys through keys_laguna (TGL_KEYS_POLL), not chooser.c's TGL_CHOOSER_KEYS"
#endif
#include "console.h"
#include "tgl_stamp.h"
#include "el2_mmu.h"
#include "menu_ui.h"
#include "tgl_dcs_menu.h"
#include "tgl_dcs.h"
#include "guard.h"
#include "probe.h"
#ifndef TGL_KEYS_POLL
#define TGL_KEYS_POLL 0
#endif
#if TGL_KEYS_POLL
#include "keys_laguna.h"
#endif

extern char _head[], _end[];
static struct tgl_el2_tables el2t __attribute__((aligned(4096)));

#define SCTLR_M (UINT64_C(1) << 0)
#define SCTLR_C (UINT64_C(1) << 2)
#define CHOOSER_FB UINT64_C(0xf0000000)	/* shim.c TGL_FB_FALLBACK: plain DRAM, the console's buffer too */
#define IOS_STAMP(step, v) ((uint64_t)(step) << 56 | ((uint64_t)(v) & UINT64_C(0x00ffffffffffffff)))

static uint64_t now_ms(void)
{
	uint64_t f, t;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(f));
	__asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(t));
	if (!f) f = 38400000;
	return t / (f / 1000);
}

static uint64_t text8(const char *s)
{
	uint64_t v = 0;
	for (int i = 0; s && i < 7 && s[i]; i++) v |= (uint64_t)(uint8_t)s[i] << (8 * i);
	return v;
}

static void (*chooser_pat)(void);
static void lz4_tick(void) { if (chooser_pat) chooser_pat(); }

#if TGL_KEYS_POLL
/* keys_laguna.c (owner: keys lane): debounced pads 51/52, read-only. Same use as chooser.c's
 * TGL_CHOOSER_KEYS_POLL path; a fault leaves the countdown alone in charge (default entry). */
static struct keys_state cios_ks;
static unsigned cios_ks_last = ~0u;
static unsigned cios_keys(void)
{
	unsigned r = keys_poll(&cios_ks, now_ms());
	if (r != cios_ks_last) {
		cios_ks_last = r;
		tgl_stamp(KEYS_STAGE_DB, r & KEYS_FAULT ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (uint64_t)r << 48 | (uint64_t)keys_raw_levels(&cios_ks) << 40 |
		    (uint64_t)(cios_ks.bad & 0xffu) << 32 | cios_ks.samples);
	}
	return r & KEYS_FAULT ? 0u : r & (KEYS_VOL_UP | KEYS_VOL_DOWN);
}
/* As chooser.c chooser_keys_start: one masked read of both pads; a pending SError ends the boot. */
static const char *cios_keys_start(int *ok, uint64_t *arg)
{
	uint32_t dn = 0, up = 0;
	uint64_t isr;
	__asm__ volatile("msr daifset, #0xf; isb" ::: "memory");
	int r1 = probe_read32((uintptr_t)KEYS_PAD_PA(KEYS_PAD_VOL_DOWN), &dn);
	int r2 = r1 && probe_read32((uintptr_t)KEYS_PAD_PA(KEYS_PAD_VOL_UP), &up);
	__asm__ volatile("dsb sy; isb; mrs %0, isr_el1" : "=r"(isr) :: "memory");
	*arg = (uint64_t)dn << 32 | up;
	if (isr & 0x100) return "chooser: key pad read left an SError pending";
	*ok = r1 && r2 && dn != KEYS_UNREADABLE && up != KEYS_UNREADABLE;
	return 0;
}
#endif

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

/* chooser.c chain_jump_mmu_off, unchanged. */
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

/* iOS branch: the EL2 MMU and caches off, returning (el2_mmu.h declares tgl_el2_mmu_off but no
 * file defines it). [lo, hi) is the loaded image: it holds the stack, BSS and el2t, the only
 * lines this boot dirtied (the menu buffer is Normal non-cacheable). Between its clean and the
 * SCTLR_EL2 write this block makes no store, so no line can be dirtied after the clean; after the
 * write both cacheable ranges are cleaned+invalidated again to drop lines that speculation
 * allocated meanwhile (all clean, nothing lost), so a later cache-on (XNU) never hits a stale
 * line. Then I-cache and EL2 TLBs. Interrupts stay masked, as on the direct iOS path. */
static void __attribute__((noinline)) cios_mmu_off(uint64_t sctlr, uint64_t lo, uint64_t hi,
	uint64_t lo2, uint64_t hi2)
{
	register uint64_t x0 __asm__("x0") = sctlr;
	register uint64_t x1 __asm__("x1") = lo;
	register uint64_t x2 __asm__("x2") = hi;
	register uint64_t x3 __asm__("x3") = lo2;
	register uint64_t x4 __asm__("x4") = hi2;
	__asm__ volatile(
	    "msr daifset, #0xf\n\t"
	    "mrs x9, ctr_el0\n\t"
	    "ubfx x9, x9, #16, #4\n\t"
	    "mov x10, #4\n\t"
	    "lsl x10, x10, x9\n\t"
	    "sub x11, x10, #1\n\t"
	    "bic x5, x1, x11\n"
	    "1:\tdc civac, x5\n\t"
	    "add x5, x5, x10\n\t"
	    "cmp x5, x2\n\t"
	    "b.lo 1b\n\t"
	    "dsb sy\n\t"
	    "msr sctlr_el2, x0\n\t"
	    "isb\n\t"
	    "bic x5, x1, x11\n"
	    "2:\tdc civac, x5\n\t"
	    "add x5, x5, x10\n\t"
	    "cmp x5, x2\n\t"
	    "b.lo 2b\n\t"
	    "bic x5, x3, x11\n"
	    "3:\tcmp x5, x4\n\t"
	    "b.hs 4f\n\t"
	    "dc civac, x5\n\t"
	    "add x5, x5, x10\n\t"
	    "b 3b\n"
	    "4:\tdsb sy\n\t"
	    "ic iallu\n\t"
	    "tlbi alle2\n\t"
	    "dsb sy\n\t"
	    "isb"
	    :: "r"(x0), "r"(x1), "r"(x2), "r"(x3), "r"(x4) : "x5", "x9", "x10", "x11", "memory");
}

static void inval_dcache(uint64_t lo, uint64_t hi)
{
	uint64_t ctr;
	__asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
	uint64_t line = UINT64_C(4) << ((ctr >> 16) & 0xf);
	for (uint64_t a = lo & ~(line - 1); a < hi; a += line)
		__asm__ volatile("dc ivac, %0" :: "r"(a) : "memory");
	__asm__ volatile("dsb sy\n\tic iallu\n\tdsb sy\n\tisb" ::: "memory");
}

/* The r11 release, the same for both branches. 0 or a refusal. */
static const char *display_release(void (*pat)(void), unsigned *code_ms)
{
	uint64_t isr, tr = now_ms();
	unsigned rrc = (unsigned)tgl_dcsm_release();
	__asm__ volatile("dsb sy; isb; mrs %0, isr_el1" : "=r"(isr) :: "memory");
	tgl_stamp(TGL_STAGE_CHOOSER_RELEASE, rrc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
	    (now_ms() - tr) << 32 | (uint64_t)(isr & 0x100) << 8 | rrc);
	*code_ms = (unsigned)(((now_ms() - tr) & 0xffffu) << 16 | (rrc & 0xffffu));
	if (pat) pat();
	if (isr & 0x100) return "chooser: display release left an SError pending";
	if (rrc) return "chooser: display domain could not be returned to off";
	return 0;
}

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

	const uint8_t *head = (const uint8_t *)_head;
	uint64_t isz = *(const volatile uint64_t *)(const void *)(head + 16);
	uint64_t end_off = (uint64_t)((const uint8_t *)_end - head);
	if (end_off > isz) return "chooser: image_size below _end";

	/* iOS entry: offered only if the envelope is there and passes the checks loader.c makes later.
	 * A refusal here only dims the iOS tile; Android stays the default and the fallback. */
	struct tgl_chooser_ios_layout lay;
	const char *iw = tgl_chooser_ios_admit(head, (uint64_t)(uintptr_t)head, isz, end_off, dtb, m, &lay);
	unsigned ios_ok = iw == 0;
	tgl_stamp(TGL_STAGE_CHOOSER_IOS, ios_ok ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED,
	    IOS_STAMP(TGL_IOS_STEP_ADMIT, ios_ok ? lay.payload_bytes : text8(iw)));

	/* Android segment: after the envelope when one exists (chooser.c's rule), else at _end. */
	const uint8_t *p = head + end_off;
	if (ios_ok) p = head + lay.seg_off;
	else if (memeq(p, "TEGUPLD1", 8)) {
		uint64_t n = le64(p + 8);
		if (n > isz - end_off - 16) return "chooser: XNU envelope past image";
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

	uint64_t sctlr0 = sctlr;
	int cached;
	struct tgl_el2_region rg[3] = {
		{ (uint64_t)(uintptr_t)head, isz, TGL_EL2_WB, 1 },
		{ base, seg.image_size, TGL_EL2_WB, 0 },
		{ CHOOSER_FB, (uint64_t)FB_STRIDE * FB_H, TGL_EL2_NC, 0 },
	};
	{
		const char *mw = tgl_el2_build(&el2t, m, rg, 3);
		if (!mw) mw = tgl_el2_mmu_on(&el2t, rg, 3, &sctlr0);
		cached = !mw;
		tgl_stamp(TGL_STAGE_CHOOSER_MMU, mw ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (uint64_t)el2t.wb_blocks << 32 | (uint64_t)el2t.nc_blocks << 16 | el2t.refused_blocks);
	}
	uint64_t t0 = now_ms();
	uint64_t c = tgl_chooser_csum64(seg.data, seg.comp_len);
	tgl_stamp(TGL_STAGE_CHOOSER_CSUM, c == seg.csum ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED,
	    (now_ms() - t0) << 32 | (uint32_t)c);
	if (c != seg.csum) return "chooser: stock kernel checksum mismatch";
	if (pat) pat();

	struct tgl_menu_view view = { tgl_chooser_ios_initial_sel(ios_ok, TGL_CHOOSER_IOS_DEFAULT),
	    TGL_CHOOSER_TIMEOUT_MS / 1000, ios_ok };
	uint32_t *fb = (uint32_t *)(uintptr_t)CHOOSER_FB;
	t0 = now_ms();
	tgl_menu_draw(fb, FB_W, &view);
	tgl_stamp(TGL_STAGE_CHOOSER_UI, TGL_STAMP_F_DONE, (now_ms() - t0) << 32 | (uint32_t)cached);
	if (pat) pat();
	int shown = 0;
	{
		static const uint8_t dn[16] = TGL_UFS_RECORD_NONCE;
		uint64_t isr;
		t0 = now_ms();
		__asm__ volatile("dsb sy" ::: "memory");
		tgl_dcsm_begin(TGL_STAMP_NONCE, dn, TGL_UFS_EPOCH);
		unsigned drc = tgl_dcsm_guarded();
		tgl_dcsm_finish((int)drc, tgl_guard_esr, tgl_guard_far, 0);
		if (pat) pat();
		__asm__ volatile("mrs %0, isr_el1" : "=r"(isr));
		tgl_stamp(TGL_STAGE_CHOOSER_DISPLAY, drc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (now_ms() - t0) << 32 | (uint64_t)(isr & 0x100) << 8 | drc);
		if (isr & 0x100) return "chooser: display left an SError pending";
		shown = drc == 0;
	}
	(void)keys;	/* shim.c passes 0; the keys come from keys_laguna when built in */
	unsigned (*kf)(void) = 0;
#if TGL_KEYS_POLL
	{
		uint64_t karg = 0;
		int kok = 0;
		const char *kw = cios_keys_start(&kok, &karg);
		tgl_stamp(TGL_STAGE_CHOOSER_KEYS, kw || !kok ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE, karg);
		if (kw) return kw;
		if (kok) {
			keys_init(&cios_ks, probe_read32, KEYS_VOL_UP | KEYS_VOL_DOWN, now_ms(), TGL_CHOOSER_TIMEOUT_MS);
			kf = cios_keys;
		}
	}
#endif
	struct tgl_chooser_menu s;
	uint64_t start = now_ms(), last_pat = start, last_line = start;
	tgl_chooser_menu_init(&s, start, ios_ok);
	s.sel = view.sel;
	unsigned shown_sel = s.sel;
	tgl_stamp(TGL_STAGE_CHOOSER_MENU, TGL_STAMP_F_ENTER, TGL_CHOOSER_TIMEOUT_MS | (uint64_t)ios_ok << 32 | (uint64_t)s.sel << 33);
	unsigned r, held = 0;
	for (;;) {
		uint64_t t = now_ms();
		unsigned k = kf ? kf() : 0;
		if (k != held) {
			tgl_stamp(TGL_STAGE_CHOOSER_KEY, TGL_STAMP_F_DONE, (t - start) << 8 | k);
			held = k;
		}
		r = tgl_chooser_menu_step(&s, t, k);
		if (r) break;
		if (t - last_pat >= 1000) { if (pat) pat(); last_pat = t; }
		if (t - last_line >= 1000 || s.sel != shown_sel) {
			shown_sel = s.sel;
			view.sel = s.sel;
			view.seconds = (unsigned)((s.deadline_ms - t + 999) / 1000);
			tgl_menu_draw_band(fb, FB_W, &view);
			if (shown) {
				__asm__ volatile("dsb sy" ::: "memory");
				int prc = tgl_dcsm_present();
				if (prc) {
					shown = 0;
					tgl_stamp(TGL_STAGE_CHOOSER_DISPLAY, TGL_STAMP_F_REFUSED, (uint64_t)1 << 40 | (uint32_t)prc);
				}
			}
			last_line = t;
		}
		for (volatile unsigned d = 0; d < 20000; d++) { }
	}
	unsigned act = tgl_chooser_ios_action(r, ios_ok);
	tgl_stamp(TGL_STAGE_CHOOSER_PICK, TGL_STAMP_F_DONE,
	    (now_ms() - start) << 8 | (act == TGL_IOS_ACT_XNU ? TGL_CHOOSE_IOS : TGL_CHOOSE_ANDROID) << 4 | s.why);

	unsigned rel = 0;
	why = display_release(pat, &rel);
	if (act == TGL_IOS_ACT_XNU)
		tgl_stamp(TGL_STAGE_CHOOSER_IOS, why ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    IOS_STAMP(TGL_IOS_STEP_RELEASE, rel));
	if (why) return why;

	if (act == TGL_IOS_ACT_XNU) {
		/* The direct iOS path starts with the MMU and caches off: undo the chooser's map. */
		uint64_t after = 0;
		if (cached) {
			cios_mmu_off(sctlr0, (uint64_t)(uintptr_t)head, (uint64_t)(uintptr_t)head + isz,
			    base, base + seg.image_size);
		}
		__asm__ volatile("mrs %0, sctlr_el2" : "=r"(after));
		tgl_stamp(TGL_STAGE_CHOOSER_IOS, (after & (SCTLR_M | SCTLR_C)) ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    IOS_STAMP(TGL_IOS_STEP_MMU_OFF, after));
		if (after & (SCTLR_M | SCTLR_C)) return "chooser: EL2 MMU or D-cache still on for the iOS path";
		if (pat) pat();
		tgl_stamp(TGL_STAGE_CHOOSER_IOS, TGL_STAMP_F_DONE, IOS_STAMP(TGL_IOS_STEP_HANDBACK, now_ms()));
		return TGL_CHOOSER_PICKED_IOS;
	}

	/* Android: chooser.c from here, unchanged in logic. */
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

	if (pat) pat();
	tgl_stamp(TGL_STAGE_CHOOSER_JUMP, TGL_STAMP_F_ENTER, base | (uint64_t)cached << 63);
	if (cached) chain_jump_mmu_off(sctlr0, base, base + seg.image_size, base, dtb);
	inval_dcache(base, base + seg.image_size);
	chain_jump(base, dtb);
}
#endif
#endif /* TGL_CHOOSER_HOST || TGL_CHOOSER_IOS */
