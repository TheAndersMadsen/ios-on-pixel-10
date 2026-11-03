/*
 * blazer_mem: how far the kernel-managed window grows, and what hw.memsize reports.
 * No XNU types: the host test compiles this file as it stands.
 *
 * This phone (FDT d7c27fdc..., ABL "DRAM size : 0x400000000") has 16 GiB in two banks:
 *   low   0x080000000..0x100000000   2 GiB. Every fixed DT carve-out (AoC, GPU/TPU/GXP firmware,
 *         GSA, bl31, sec_dram/trusty, modem, ramoops, ABL) and our shim, panel and USB/UFS arenas.
 *         Not managed here; blazer_low (arm/pmap/blazer_lowbank.h) is the only route, and it
 *         stays denied on the phone.
 *   high  0x880000000..0xc00000000  14 GiB. No fixed DT carve-out. Android's iomem and dmesg
 *         (attempts/final-return) reserve only its two ends:
 *           0x880000000 + 16 MiB                    reserved, owner unknown
 *           0xbbd1f8000..0xbd5600000                Linux's own early allocations (memblock)
 *           0xbd5c00000..0xbfb800000 vstream, vframe   dynamic CMA, "map reusable"
 *           0xbfb800000..0xbfc000000 pkvm_iommu_cma     dynamic CMA, "map reusable"
 *           0xbfc000000..0xbfd000000 faprev             dynamic CMA, "map reusable"
 *           0xbfd000000..0xc00000000 faceauth_tpu/_dsp  dynamic, "map non-reusable"
 *         Every one of these is placed by Android's kernel at its own boot (no fixed reg), so
 *         none exists while iOS runs. ABL also names "MTE addr 0xbe0f83000" (16 GiB / 33 below
 *         the top) and "MTE S: 1, NS: 0": secure MTE may tag from there up. Never past it.
 *
 * Bottom is rounded up and the old top down to the 32 MiB the loader wants of a base.
 */
#ifndef _BLAZER_MEMPLAN_H_
#define _BLAZER_MEMPLAN_H_
#include <stdint.h>

#define BLAZER_RAM_BOTTOM         0x882000000ULL
/* blazer_mem=5..13: stop below Android's first top reservation (iomem 0xbbd1f8000). */
#define BLAZER_RAM_TOP            0xbbd000000ULL
/* blazer_mem=14..16, the full map: up to the MTE tag base, page aligned down. */
#define BLAZER_RAM_TOP_TAGS       0xbe0f80000ULL
/* Installed DRAM: ABL's "DRAM size", eight FDT 2 GiB banks. What hw.memsize reports in the full map. */
#define BLAZER_RAM_INSTALLED      0x400000000ULL
#define BLAZER_MEM_FULL_GIB       14u
#define BLAZER_MEM_MAX_GIB        64u

enum {
	BLAZER_MEM_REFUSE = -1,
	BLAZER_MEM_KEEP   = 0,          /* no change: arg absent or not above the loader's size */
	BLAZER_MEM_GROW   = 1,
};

/*
 * base/old/old_actual: the loader's physBase, memSize, memSizeActual. gib: blazer_mem.
 * fake: QEMU's blazer_ufs_fake (its RAM ends at base + gib GiB, not at the phone's top).
 * report: blazer_mem_report=1 (hw.memsize = the managed size; the full map ignores it).
 * On GROW, *end is the new window end and *actual the new memSizeActual (hw.memsize).
 * The full map reports the installed DRAM, as iBoot does: memSizeActual >= memSize,
 * max_mem stays what the VM manages. Below it, hw.memsize keeps the loader's value
 * unless report: what earlier kernels did, unchanged.
 */
static inline int
blazer_mem_plan(uint64_t base, uint64_t old, uint64_t old_actual, uint32_t gib, int fake, int report,
    uint64_t *end, uint64_t *actual)
{
	uint64_t want, top, size;
	int full = gib >= BLAZER_MEM_FULL_GIB;

	if ((uint64_t)gib <= (old >> 30)) {
		return BLAZER_MEM_KEEP;
	}
	top = full ? BLAZER_RAM_TOP_TAGS : BLAZER_RAM_TOP;
	if (gib > BLAZER_MEM_MAX_GIB || base < BLAZER_RAM_BOTTOM) {
		return BLAZER_MEM_REFUSE;
	}
	want = base + ((uint64_t)gib << 30);
	if (fake) {
		top = want;
	}
	if (base >= top) {
		return BLAZER_MEM_REFUSE;
	}
	*end = want < top ? want : top;
	if (*end <= base + old) {
		return BLAZER_MEM_KEEP;
	}
	size = *end - base;
	if (full) {
		*actual = size > BLAZER_RAM_INSTALLED ? size : BLAZER_RAM_INSTALLED;
	} else {
		*actual = report ? size : old_actual;
	}
	return BLAZER_MEM_GROW;
}
#endif /* _BLAZER_MEMPLAN_H_ */
