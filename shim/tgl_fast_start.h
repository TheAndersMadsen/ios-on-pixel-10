#pragma once
/*
 * TGL_FAST_START=1: the fast normal-start profile (research/ios26-phaseb-r1/fast-start/PLAN.md).
 *
 * Removes waits a normal, unattended iOS start does not need. Nothing here
 * changes a safety mechanism: the watchdog survey/pat/quiesce posture, the
 * 90 s bring-up deadline, every refusal, the stamp channel and the panic
 * screens behave as without the flag. With the flag off nothing in this
 * file is compiled and the shim objects are byte-identical to the
 * pre-fast-start build.
 *
 *   F1  USB enumeration window: TGL_FAST_USB_WAIT_MS (500 ms) instead of
 *       TGL_USB_WAIT_SECONDS (8 s); the 1 s window before payload admission
 *       becomes a drain that only waits while an EP0 data stage is in flight
 *       (bounded 1 s). The handoff refusal on an active transfer stays.
 *   F2  FDT reuse: loader_boot takes shim_main's admission result for the
 *       same, unchanged tree instead of walking it a second time with the
 *       MMU off (2.5 s on the phone). Any mismatch falls back to the parse.
 *   F3  The informational DT framebuffer lookup (one more uncached walk;
 *       the stock tree has no fb node and the result is never adopted in
 *       the DER-safe posture) is skipped.
 *   F4  Cached payload copy: the EL2 write-back identity map the chooser
 *       already runs on the phone (el2_mmu.c, chooser-v1-r4) covers the shim
 *       image and the kernel destination only for the segment/ADT/boot_args
 *       writes, then everything is cleaned to PoC and the MMU and caches are
 *       off again before the USB drain, the deadline check and the EL1 drop.
 *       Any refusal keeps the proven uncached copy.
 */
#include <stdbool.h>
#include <stdint.h>
#include "fdt.h"
#include "el2_mmu.h"

#define TGL_STAGE_FAST		0x00f1u	/* arg = step<<56 | value */
#define TGL_FAST_STAMP(step, v)	((uint64_t)(step) << 56 | ((uint64_t)(v) & UINT64_C(0x00ffffffffffffff)))
enum {
	TGL_FAST_S_PROFILE = 1,		/* DONE, value = TGL_FAST_PROFILE bits */
	TGL_FAST_S_FDT = 2,		/* DONE reused; REFUSED, value = reason code -> full parse */
	TGL_FAST_S_CACHE_ON = 3,	/* DONE, value = wb blocks<<16 | refused blocks; REFUSED, value = reason code */
	TGL_FAST_S_CACHE_OFF = 4,	/* DONE, value = cached window in us */
};
#define TGL_FAST_F_USB		0x1u
#define TGL_FAST_F_FDT		0x2u
#define TGL_FAST_F_DTFB		0x4u
#define TGL_FAST_F_CACHE	0x8u
/* EXTRA_CFLAGS=-DTGL_FAST_CACHE=0 keeps F1-F3 and the proven uncached copy (bisection knob). */
#ifndef TGL_FAST_CACHE
#define TGL_FAST_CACHE		1
#endif
#define TGL_FAST_PROFILE	(TGL_FAST_F_USB | TGL_FAST_F_FDT | TGL_FAST_F_DTFB | (TGL_FAST_CACHE ? TGL_FAST_F_CACHE : 0))

/* usb-enum-wait (0x0011) args in this profile carry this tag in the top 32 bits,
 * so a decoder never reads a millisecond count as the 8 s seconds argument. */
#define TGL_FAST_USB_TAG	UINT64_C(0x4641535400000000)	/* "FAST" */
#ifndef TGL_FAST_USB_WAIT_MS
#define TGL_FAST_USB_WAIT_MS	500u
#endif
#ifndef TGL_FAST_USB_DRAIN_MS
#define TGL_FAST_USB_DRAIN_MS	1000u
#endif
#define TGL_FAST_USB_DRAINED	(UINT64_C(1) << 31)	/* DONE arg: a data stage was waited for */
#define TGL_FAST_USB_STILL	(UINT64_C(1) << 30)	/* DONE arg: still active at the bound */

/* F1. Service the console for window_ms, then keep servicing while a data
 * stage is in flight, at most drain_ms more. Returns the elapsed ms with the
 * DRAINED/STILL bits. Never blocks past the bound: a dead counter or an
 * iteration guard ends it too. The hooks exist for the host test. */
struct tgl_fast_usb_ops {
	bool (*running)(void);
	void (*service)(void);
	bool (*active)(void);
	int (*now_us)(uint64_t *out);	/* 0 on success */
	void (*tick)(void);		/* may be null */
};
uint64_t tgl_fast_usb_window(const struct tgl_fast_usb_ops *o, uint32_t window_ms, uint32_t drain_ms);
/* Device glue: the console ops, stamps usb-enum-wait ENTER/DONE with the tag. */
void tgl_fast_usb_wait(uint32_t window_ms, uint32_t drain_ms);

/* F2. shim_main records its admitted parse; loader_boot asks for it back.
 * Reuse needs the same dtb pointer, the same magic and totalsize in the tree
 * header now, and a recorded parse of that size. Returns 0 when *out holds
 * the recorded result, else a reason (the caller then parses as before). */
enum { TGL_FAST_FDT_NONE = 1, TGL_FAST_FDT_PTR = 2, TGL_FAST_FDT_MAGIC = 3, TGL_FAST_FDT_SIZE = 4 };
void tgl_fast_fdt_remember(uintptr_t dtb, const struct tgl_fdt_memory *m);
unsigned tgl_fast_fdt_reuse(uintptr_t dtb, struct tgl_fdt_memory *out);

/* F4. The plan is pure and host-tested: two write-back regions, each
 * widened to whole 2 MiB blocks (the map's granule, so maintenance covers
 * every byte a cacheable access could touch), refused if the two meet or if
 * any avoid range (live FDT, console fb, ramoops/stamps, ABL initrd) falls
 * inside a widened block. */
#define TGL_FAST_BLOCK		(UINT64_C(1) << 21)
enum {
	TGL_FAST_C_ARG = 1, TGL_FAST_C_OVERLAP = 2, TGL_FAST_C_AVOID = 3,
	TGL_FAST_C_MAP = 4, TGL_FAST_C_MMU = 5, TGL_FAST_C_OFF = 6,
};
struct tgl_fast_cache {
	struct tgl_el2_region r[2];	/* [0] shim image (exec), [1] kernel destination */
	uint64_t sctlr;			/* SCTLR_EL2 to restore */
	uint64_t t0_us;
	unsigned on, why;
};
unsigned tgl_fast_cache_plan(struct tgl_fast_cache *c, uint64_t img_lo, uint64_t img_hi,
	uint64_t dst_lo, uint64_t dst_hi, const struct tgl_range *avoid, unsigned navoid);
#ifndef TGL_FAST_HOST
/* Plan, build the tables and turn the map on. Stamps CACHE_ON. c->on says
 * whether the caller now runs cached; a refusal leaves the MMU off. */
void tgl_fast_cache_on(struct tgl_fast_cache *c, const struct tgl_fdt_memory *m,
	uint64_t img_lo, uint64_t img_hi, uint64_t dst_lo, uint64_t dst_hi,
	const struct tgl_range *avoid, unsigned navoid);
/* Clean+invalidate both widened regions to PoC, restore SCTLR_EL2, drop the
 * I-cache and EL2 TLBs, invalidate both regions again (no stale clean line
 * survives for XNU's first cacheable access). No-op when !c->on. Stamps CACHE_OFF. */
void tgl_fast_cache_off(struct tgl_fast_cache *c);
/* tgl_fast_start_s.S: registers only, no stack. */
void tgl_fast_mmu_off_asm(uint64_t sctlr, uint64_t lo0, uint64_t hi0, uint64_t lo1, uint64_t hi1);
#endif
