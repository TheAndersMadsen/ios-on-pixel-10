#pragma once
#include <stdint.h>
#include "fdt.h"

/* EL2 stage-1 identity map for the chooser (4K granule, 39-bit VA, 36-bit PA).
 * Everything is Device-nGnRnE and execute-never except 2 MiB blocks the caller
 * owns: Normal write-back (the shim image and the kernel destination; only the
 * shim image is executable) or Normal non-cacheable (the framebuffer). A block
 * that touches any FDT reservation or alloc pool stays Device, so no carve-out
 * is ever reachable by a speculative cacheable access. */
#define TGL_EL2_L1_ENTRIES 512u
#define TGL_EL2_L2_TABLES 8u
#define TGL_EL2_MAP_GB 48u		/* 0 .. 48 GiB, covers blazer DRAM */

enum { TGL_EL2_DEV = 0, TGL_EL2_WB = 1, TGL_EL2_NC = 2 };

struct tgl_el2_tables {
	uint64_t l1[TGL_EL2_L1_ENTRIES] __attribute__((aligned(4096)));
	uint64_t l2[TGL_EL2_L2_TABLES][512] __attribute__((aligned(4096)));
	unsigned l2_used, wb_blocks, nc_blocks, refused_blocks;
};

struct tgl_el2_region { uint64_t base, size; unsigned kind, exec; };

/* Pure: fill tables. Returns 0 or a refusal. Host-tested (el2_mmu_test.c). */
const char *tgl_el2_build(struct tgl_el2_tables *t, const struct tgl_fdt_memory *m,
	const struct tgl_el2_region *r, unsigned n);
/* Descriptor attribute index of the 2 MiB block holding pa (host test helper). */
int tgl_el2_kind_at(const struct tgl_el2_tables *t, uint64_t pa);

#ifndef TGL_CHOOSER_HOST
/* Device: invalidate the cacheable ranges, program MAIR/TCR/TTBR0_EL2, enable M|C|I.
 * Returns the SCTLR_EL2 value it replaced. Refuses unless at EL2 with HCR_EL2.E2H=0. */
const char *tgl_el2_mmu_on(struct tgl_el2_tables *t, const struct tgl_el2_region *r,
	unsigned n, uint64_t *sctlr_before);
/* Device: clean+invalidate [lo, hi) to PoC, restore sctlr (MMU/caches off),
 * invalidate I-cache and EL2 TLBs. Runs from identity-mapped code. */
void tgl_el2_mmu_off(uint64_t sctlr, uint64_t lo, uint64_t hi);
#endif
