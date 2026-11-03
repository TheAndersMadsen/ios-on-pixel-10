/* Host test for tgl_fast_start.c (TGL_FAST_START=1): the bounded USB window
 * on a fake clock and gadget, the FDT reuse rules, and the cached-copy plan
 * fed into the real EL2 map builder (el2_mmu.c). Built by build.sh with
 * -DTGL_FAST_HOST -DTGL_CHOOSER_HOST. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "tgl_fast_start.h"

static unsigned checks, failed;
#define CHECK(c) do { checks++; if (!(c)) { failed++; printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); } } while (0)

/* ---- fake gadget + clock ---- */
static uint64_t clk_us, step_us = 1000;	/* each service call costs 1 ms */
static bool f_running = true, f_dead_clock;
static uint64_t active_from = UINT64_MAX, active_until;	/* data stage in [from, until) */
static unsigned services, ticks;
static bool g_running(void) { return f_running; }
static void g_service(void) { services++; clk_us += step_us; }
static bool g_active(void) { return clk_us >= active_from && clk_us < active_until; }
static int g_now(uint64_t *o) { if (f_dead_clock) return -1; *o = clk_us; return 0; }
static void g_tick(void) { ticks++; }
static const struct tgl_fast_usb_ops ops = { g_running, g_service, g_active, g_now, g_tick };

static void reset_fake(void)
{
	clk_us = 5000000; step_us = 1000; f_running = true; f_dead_clock = false;
	active_from = UINT64_MAX; active_until = 0; services = ticks = 0;
}

static void test_usb(void)
{
	uint64_t r;
	/* No host: exactly the window, never the flag-off 8 s. */
	reset_fake();
	r = tgl_fast_usb_window(&ops, 500, 1000);
	CHECK((r & 0xffff) == 500);
	CHECK(!(r & TGL_FAST_USB_DRAINED) && !(r & TGL_FAST_USB_STILL));
	CHECK(ticks == services && services == 500);	/* WDT tick on every pass */
	/* Console never started: return at once, no service. */
	reset_fake(); f_running = false;
	CHECK(tgl_fast_usb_window(&ops, 500, 1000) == 0 && services == 0);
	/* Host mid-request at the window's end: wait for its data stage only. */
	reset_fake(); active_from = clk_us + 300000; active_until = clk_us + 820000;
	r = tgl_fast_usb_window(&ops, 500, 1000);
	CHECK((r & 0xffff) == 820 && (r & TGL_FAST_USB_DRAINED) && !(r & TGL_FAST_USB_STILL));
	/* A stage that never ends: bounded at window + drain, flagged STILL
	 * (shim.c's own active-transfer refusal then decides, as without the flag). */
	reset_fake(); active_from = 0; active_until = UINT64_MAX;
	r = tgl_fast_usb_window(&ops, 500, 1000);
	CHECK((r & 0xffff) == 1500 && (r & TGL_FAST_USB_STILL));
	/* Drain-only call (pre-payload): idle -> one service, out. */
	reset_fake();
	r = tgl_fast_usb_window(&ops, 0, 1000);
	CHECK(services == 1 && (r & 0xffff) == 1);
	reset_fake(); active_from = 0; active_until = clk_us + 40000;
	r = tgl_fast_usb_window(&ops, 0, 1000);
	CHECK((r & 0xffff) == 40 && (r & TGL_FAST_USB_DRAINED));
	/* Dead counter: the clock read fails -> leave, never spin. */
	reset_fake(); f_dead_clock = true;
	CHECK(tgl_fast_usb_window(&ops, 500, 1000) == 0 && services == 0);
	/* Frozen clock: the iteration guard ends it. */
	reset_fake(); step_us = 0;
	r = tgl_fast_usb_window(&ops, 500, 1000);
	CHECK(services == 100000 + 1500 * 100 && (r & 0xffff) == 0);
}

/* ---- FDT reuse ---- */
static void put_be32(unsigned char *p, uint32_t v) { p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v; }

static void test_fdt(void)
{
	static unsigned char tree[64] __attribute__((aligned(8)));
	static struct tgl_fdt_memory parsed, out;
	uintptr_t dtb = (uintptr_t)tree;
	memset(&parsed, 0, sizeof parsed);
	parsed.total_size = 0x1234; parsed.ram_count = 2; parsed.ram[1].base = 0x880000000;
	parsed.reserved_count = 3; parsed.reserved[2].size = 0x4000; parsed.psci_method = 1;
	strcpy(parsed.compatible, "google,lga-blazer");
	put_be32(tree, 0xd00dfeed); put_be32(tree + 4, 0x1234);
	CHECK(tgl_fast_fdt_reuse(dtb, &out) == TGL_FAST_FDT_NONE);	/* nothing recorded */
	tgl_fast_fdt_remember(dtb, &parsed);
	memset(&out, 0xa5, sizeof out);
	CHECK(tgl_fast_fdt_reuse(dtb, &out) == 0);
	CHECK(!memcmp(&out, &parsed, sizeof out));			/* the admission result, byte for byte */
	CHECK(tgl_fast_fdt_reuse(dtb + 8, &out) == TGL_FAST_FDT_PTR);	/* another tree pointer */
	put_be32(tree + 4, 0x1238);
	CHECK(tgl_fast_fdt_reuse(dtb, &out) == TGL_FAST_FDT_SIZE);	/* header changed size */
	put_be32(tree + 4, 0x1234); tree[0] = 0;
	CHECK(tgl_fast_fdt_reuse(dtb, &out) == TGL_FAST_FDT_MAGIC);
	tree[0] = 0xd0;
	parsed.total_size = 0; put_be32(tree + 4, 0);
	CHECK(tgl_fast_fdt_reuse(dtb, &out) == TGL_FAST_FDT_SIZE);	/* a zero-size record never counts */
}

/* ---- cached copy plan + EL2 map ---- */
#define M2 (UINT64_C(1) << 21)
static void ram_only(struct tgl_fdt_memory *m)
{
	memset(m, 0, sizeof *m);
	m->ram_count = 2;
	m->ram[0] = (struct tgl_range){ 0x80000000, 0x80000000 };	/* 2-4 GiB */
	m->ram[1] = (struct tgl_range){ 0x880000000, 0x300000000 };	/* 34-46 GiB */
}

static void test_cache(void)
{
	static struct tgl_el2_tables t __attribute__((aligned(4096)));
	static struct tgl_fdt_memory m;
	struct tgl_fast_cache c;
	ram_only(&m);
	/* The A7 r1 geometry: window 0x882000000, ba 0x884e14000 (top = +16 KiB);
	 * a 61 MiB shim image at 0x88001000 (unaligned on purpose); live FDT,
	 * console fb, ramoops and ABL initrd elsewhere. */
	uint64_t img = 0x88001000, img_end = img + 61 * (UINT64_C(1) << 20);
	uint64_t dst = 0x882000000, top = 0x884e18000;
	struct tgl_range avoid[4] = {
		{ 0x8a000000, 0x40000 }, { 0xf0000000, 5120 * 2856 }, { 0x95200000, 0x400000 }, { 0x86000000, 0x1000 },
	};
	CHECK(tgl_fast_cache_plan(&c, img, img_end, dst, top, avoid, 4) == TGL_FAST_C_AVOID);	/* image blocks reach the FDT */
	avoid[0].base = 0x9a000000;
	CHECK(tgl_fast_cache_plan(&c, img, img_end, dst, top, avoid, 4) == 0);
	CHECK(c.r[0].base == 0x88000000 && c.r[0].size == 31 * M2 && c.r[0].exec && c.r[0].kind == TGL_EL2_WB);
	CHECK(c.r[1].base == dst && c.r[1].base + c.r[1].size == 0x885000000 && !c.r[1].exec);
	CHECK((c.r[0].base | c.r[0].size | c.r[1].base | c.r[1].size) % M2 == 0);	/* whole blocks: maintenance covers the map */
	CHECK(tgl_el2_build(&t, &m, c.r, 2) == 0);
	CHECK(t.wb_blocks == 31 + 24 && t.refused_blocks == 0);
	CHECK(tgl_el2_kind_at(&t, img) == TGL_EL2_WB && tgl_el2_kind_at(&t, top - 8) == TGL_EL2_WB);
	CHECK(tgl_el2_kind_at(&t, 0x885000000) == TGL_EL2_DEV);		/* past the widened top */
	CHECK(tgl_el2_kind_at(&t, 0xf0000000) == TGL_EL2_DEV);		/* fb and MMIO stay Device */
	CHECK(tgl_el2_kind_at(&t, 0x95430000) == TGL_EL2_DEV);		/* stamps stay Device */
	CHECK(tgl_el2_kind_at(&t, 0x0c400000) == TGL_EL2_DEV);		/* DWC3 */
	/* A reservation inside the destination keeps that block Device (slower, correct). */
	m.reserved_count = 1; m.reserved[0] = (struct tgl_range){ 0x883000000, 0x1000 };
	CHECK(tgl_el2_build(&t, &m, c.r, 2) == 0 && t.refused_blocks == 1);
	CHECK(tgl_el2_kind_at(&t, 0x883000000) == TGL_EL2_DEV);
	/* A reservation under the executable image refuses the whole map: F4 falls back. */
	m.reserved[0] = (struct tgl_range){ 0x89000000, 0x1000 };
	CHECK(tgl_el2_build(&t, &m, c.r, 2) != 0);
	ram_only(&m);
	/* Image and destination sharing a block. */
	CHECK(tgl_fast_cache_plan(&c, img, img_end, 0x8bc00000, 0x8c000000, avoid, 4) == TGL_FAST_C_OVERLAP);
	/* Ramoops/stamps in a widened block. */
	CHECK(tgl_fast_cache_plan(&c, 0x95300000, 0x95380000, dst, top, avoid, 4) == TGL_FAST_C_AVOID);
	/* Console fb next to the destination. */
	CHECK(tgl_fast_cache_plan(&c, img, img_end, 0xf0200000, 0xf0300000, avoid, 4) == TGL_FAST_C_AVOID);
	/* Bad arguments. */
	CHECK(tgl_fast_cache_plan(&c, 0, 1, dst, top, avoid, 4) == TGL_FAST_C_ARG);
	CHECK(tgl_fast_cache_plan(&c, img, img, dst, top, avoid, 4) == TGL_FAST_C_ARG);
	CHECK(tgl_fast_cache_plan(&c, img, img_end, dst, UINT64_MAX, avoid, 4) == TGL_FAST_C_ARG);
	/* An empty avoid range is ignored; one wrapping the top still counts. */
	struct tgl_range wrap[2] = { { 0x882100000, 0 }, { UINT64_MAX - 0xfff, 0x10000 } };
	CHECK(tgl_fast_cache_plan(&c, img, img_end, dst, top, wrap, 2) == 0);
	CHECK(c.on == 0);	/* the plan never claims the MMU is on */
}

int main(void)
{
	test_usb();
	test_fdt();
	test_cache();
	printf("fast-start host test: %u checks, %u failed\n", checks, failed);
	return failed ? 1 : 0;
}
