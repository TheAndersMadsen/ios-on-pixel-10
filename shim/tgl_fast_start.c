/* TGL_FAST_START=1 profile: see tgl_fast_start.h for what each part does and keeps. */
#include "tgl_fast_start.h"
#ifndef TGL_FAST_HOST
#include "console.h"
#include "laguna_usb.h"
#include "tgl_stamp.h"
#include "tgl_usb_console.h"
#endif

/* ---- F1: bounded console window ---------------------------------------- */

uint64_t tgl_fast_usb_window(const struct tgl_fast_usb_ops *o, uint32_t window_ms, uint32_t drain_ms)
{
	uint64_t t0, now;
	if (!o->running() || o->now_us(&t0)) return 0;
	now = t0;
	uint64_t window = (uint64_t)window_ms * 1000, limit = window + (uint64_t)drain_ms * 1000;
	/* Dead-counter cap, the same order as tgl_usb_console_wait's. */
	uint64_t guard = 100000 + ((uint64_t)window_ms + drain_ms) * 100;
	uint64_t flags = 0;
	for (;;) {
		o->service();
		if (o->tick) o->tick();
		if (o->now_us(&now) || !--guard) break;
		uint64_t dt = now - t0;
		if (dt < window) continue;
		if (!o->active()) break;	/* nothing in flight: leave now */
		flags |= TGL_FAST_USB_DRAINED;
		if (dt >= limit) break;
	}
	if (o->active()) flags |= TGL_FAST_USB_STILL;
	uint64_t ms = (now - t0) / 1000;
	return flags | (ms > 0xffff ? 0xffff : ms);
}

#ifndef TGL_FAST_HOST
static bool dev_running(void) { return laguna_usb_running(); }
static bool dev_active(void) { return laguna_usb_transfer_active(); }
static void dev_tick(void) { if (con_tick) con_tick(); }
extern int tgl_stamp_boot_us(uint64_t *);

void tgl_fast_usb_wait(uint32_t window_ms, uint32_t drain_ms)
{
	static const struct tgl_fast_usb_ops ops = {
		dev_running, tgl_usb_console_service, dev_active, tgl_stamp_boot_us, dev_tick,
	};
	if (!laguna_usb_running()) return;
	tgl_stamp(TGL_STAGE_USB_WAIT, TGL_STAMP_F_ENTER, TGL_FAST_USB_TAG | (uint64_t)window_ms << 16 | drain_ms);
	uint64_t r = tgl_fast_usb_window(&ops, window_ms, drain_ms);
	tgl_stamp(TGL_STAGE_USB_WAIT, TGL_STAMP_F_DONE, TGL_FAST_USB_TAG | r);
}
#endif

/* ---- F2: one FDT admission per boot ------------------------------------- */

static uintptr_t fdt_seen;
static const struct tgl_fdt_memory *fdt_parsed;

void tgl_fast_fdt_remember(uintptr_t dtb, const struct tgl_fdt_memory *m)
{
	fdt_seen = dtb;
	fdt_parsed = m;
}

static uint32_t be32(const volatile unsigned char *p)
{
	return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

unsigned tgl_fast_fdt_reuse(uintptr_t dtb, struct tgl_fdt_memory *out)
{
	if (!fdt_parsed || !fdt_seen) return TGL_FAST_FDT_NONE;
	if (dtb != fdt_seen || !dtb || (dtb & 7)) return TGL_FAST_FDT_PTR;
	const volatile unsigned char *h = (const volatile unsigned char *)dtb;
	if (be32(h) != 0xd00dfeedU) return TGL_FAST_FDT_MAGIC;
	if (be32(h + 4) != fdt_parsed->total_size || !fdt_parsed->total_size) return TGL_FAST_FDT_SIZE;
	/* Word copy through volatile: no libc memcpy in this image, and the
	 * compiler must not turn the loop into one. */
	_Static_assert(sizeof(*out) % 8 == 0, "fdt memory struct is 8-byte sized");
	const volatile uint64_t *s = (const volatile uint64_t *)fdt_parsed;
	volatile uint64_t *d = (volatile uint64_t *)out;
	for (unsigned i = 0; i < sizeof(*out) / 8; i++) d[i] = s[i];
	return 0;
}

/* ---- F4: cached copy window --------------------------------------------- */

static int span(uint64_t lo, uint64_t hi, uint64_t *blo, uint64_t *bhi)
{
	if (!lo || hi <= lo || hi > UINT64_MAX - TGL_FAST_BLOCK) return 0;
	*blo = lo & ~(TGL_FAST_BLOCK - 1);
	*bhi = (hi + TGL_FAST_BLOCK - 1) & ~(TGL_FAST_BLOCK - 1);
	return 1;
}

static int meets(uint64_t a, uint64_t ae, uint64_t b, uint64_t be)
{
	return a < be && b < ae;
}

unsigned tgl_fast_cache_plan(struct tgl_fast_cache *c, uint64_t img_lo, uint64_t img_hi,
	uint64_t dst_lo, uint64_t dst_hi, const struct tgl_range *avoid, unsigned navoid)
{
	uint64_t il, ih, dl, dh;
	c->on = 0;
	c->why = 0;
	if (!span(img_lo, img_hi, &il, &ih) || !span(dst_lo, dst_hi, &dl, &dh))
		return c->why = TGL_FAST_C_ARG;
	if (meets(il, ih, dl, dh)) return c->why = TGL_FAST_C_OVERLAP;
	for (unsigned i = 0; i < navoid; i++) {
		uint64_t b = avoid[i].base, s = avoid[i].size;
		if (!s) continue;
		uint64_t e = b + s < b ? UINT64_MAX : b + s;
		if (meets(b, e, il, ih) || meets(b, e, dl, dh)) return c->why = TGL_FAST_C_AVOID;
	}
	c->r[0] = (struct tgl_el2_region){ il, ih - il, TGL_EL2_WB, 1 };
	c->r[1] = (struct tgl_el2_region){ dl, dh - dl, TGL_EL2_WB, 0 };
	return 0;
}

#ifndef TGL_FAST_HOST
static struct tgl_el2_tables fast_tables __attribute__((aligned(4096)));

void tgl_fast_cache_on(struct tgl_fast_cache *c, const struct tgl_fdt_memory *m,
	uint64_t img_lo, uint64_t img_hi, uint64_t dst_lo, uint64_t dst_hi,
	const struct tgl_range *avoid, unsigned navoid)
{
	unsigned why = TGL_FAST_CACHE ? tgl_fast_cache_plan(c, img_lo, img_hi, dst_lo, dst_hi, avoid, navoid) : TGL_FAST_C_OFF;
	if (!why && tgl_el2_build(&fast_tables, m, c->r, 2)) why = TGL_FAST_C_MAP;
	uint64_t sctlr = 0;
	/* el2_mmu_on refuses below EL2, with VHE, or with the MMU already on. */
	if (!why && tgl_el2_mmu_on(&fast_tables, c->r, 2, &sctlr)) why = TGL_FAST_C_MMU;
	if (why) {
		c->on = 0;
		c->why = why;
		tgl_stamp(TGL_STAGE_FAST, TGL_STAMP_F_REFUSED, TGL_FAST_STAMP(TGL_FAST_S_CACHE_ON, why));
		return;
	}
	c->sctlr = sctlr;
	c->on = 1;
	c->t0_us = 0;
	(void)tgl_stamp_boot_us(&c->t0_us);
	tgl_stamp(TGL_STAGE_FAST, TGL_STAMP_F_DONE, TGL_FAST_STAMP(TGL_FAST_S_CACHE_ON,
	    (uint64_t)fast_tables.wb_blocks << 16 | (fast_tables.refused_blocks & 0xffffu)));
}

void tgl_fast_cache_off(struct tgl_fast_cache *c)
{
	if (!c->on) return;
	/* Copy everything the asm needs into locals first: after it returns the
	 * stack is uncached again and every cached store has reached PoC. */
	uint64_t s = c->sctlr, l0 = c->r[0].base, h0 = c->r[0].base + c->r[0].size;
	uint64_t l1 = c->r[1].base, h1 = c->r[1].base + c->r[1].size;
	tgl_fast_mmu_off_asm(s, l0, h0, l1, h1);
	c->on = 0;
	uint64_t now = 0;
	uint64_t us = !tgl_stamp_boot_us(&now) && now >= c->t0_us ? now - c->t0_us : 0;
	tgl_stamp(TGL_STAGE_FAST, TGL_STAMP_F_DONE, TGL_FAST_STAMP(TGL_FAST_S_CACHE_OFF, us));
}
#endif
