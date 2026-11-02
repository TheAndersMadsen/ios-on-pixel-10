/* EL2 identity map with caches for the chooser (see el2_mmu.h). Policy as in
 * mmu.c: nothing is cacheable except memory the shim owns, so no firmware
 * carve-out can see a speculative cacheable read. */
#include "el2_mmu.h"

#define BLK2M (UINT64_C(1) << 21)
#define GB (UINT64_C(1) << 30)
#define D_BLOCK UINT64_C(1)
#define D_TABLE UINT64_C(3)
#define D_ATTR(i) ((uint64_t)(i) << 2)
#define D_AP1 (UINT64_C(1) << 6)	/* RES1 in single-EL regimes */
#define D_SH_INNER (UINT64_C(3) << 8)
#define D_AF (UINT64_C(1) << 10)
#define D_XN (UINT64_C(1) << 54)
#define DEV_DESC (D_ATTR(TGL_EL2_DEV) | D_AP1 | D_AF | D_XN | D_BLOCK)

static int overlap(uint64_t a, uint64_t as, uint64_t b, uint64_t bs)
{
	return a < b + bs && b < a + as;
}

static int block_ok(const struct tgl_fdt_memory *m, uint64_t b)
{
	struct tgl_range r = { b, BLK2M };
	if (!tgl_range_in_ram(m, r)) return 0;
	for (unsigned i = 0; i < m->reserved_count; i++)
		if (overlap(b, BLK2M, m->reserved[i].base, m->reserved[i].size)) return 0;
	return 1;
}

const char *tgl_el2_build(struct tgl_el2_tables *t, const struct tgl_fdt_memory *m,
	const struct tgl_el2_region *r, unsigned n)
{
	t->l2_used = t->wb_blocks = t->nc_blocks = t->refused_blocks = 0;
	for (unsigned i = 0; i < TGL_EL2_L1_ENTRIES; i++)
		t->l1[i] = i < TGL_EL2_MAP_GB ? ((uint64_t)i << 30) | DEV_DESC : 0;
	for (unsigned k = 0; k < n; k++) {
		if (!r[k].size || r[k].kind == TGL_EL2_DEV || r[k].kind > TGL_EL2_NC) return "bad region";
		if (r[k].exec && r[k].kind != TGL_EL2_WB) return "executable region must be write-back";
		uint64_t lo = r[k].base & ~(BLK2M - 1), hi = r[k].base + r[k].size;
		if (hi < r[k].base || hi > (uint64_t)TGL_EL2_MAP_GB * GB) return "region outside the map";
		for (uint64_t b = lo; b < hi; b += BLK2M) {
			unsigned gi = (unsigned)(b >> 30);
			uint64_t *l2;
			if ((t->l1[gi] & 3) == D_TABLE) {
				l2 = (uint64_t *)(uintptr_t)(t->l1[gi] & ~UINT64_C(0xfff) & ((UINT64_C(1) << 48) - 1));
			} else {
				if (t->l2_used >= TGL_EL2_L2_TABLES) return "out of L2 tables";
				l2 = t->l2[t->l2_used++];
				for (unsigned j = 0; j < 512; j++)
					l2[j] = (((uint64_t)gi << 30) + ((uint64_t)j << 21)) | DEV_DESC;
				t->l1[gi] = (uint64_t)(uintptr_t)l2 | D_TABLE;
			}
			unsigned j = (unsigned)((b >> 21) & 511);
			if (!block_ok(m, b)) {
				if (r[k].exec) return "executable block touches a reservation or lies outside RAM";
				t->refused_blocks++;
				continue;	/* stays Device: correct, only slower */
			}
			uint64_t d = b | D_ATTR(r[k].kind) | D_AP1 | D_AF | D_SH_INNER | D_BLOCK;
			if (!r[k].exec) d |= D_XN;
			if ((l2[j] & (7u << 2)) != D_ATTR(TGL_EL2_DEV) && l2[j] != d)
				return "regions disagree on one block";
			if ((l2[j] & (7u << 2)) == D_ATTR(TGL_EL2_DEV)) {
				if (r[k].kind == TGL_EL2_WB) t->wb_blocks++; else t->nc_blocks++;
			}
			l2[j] = d;
		}
	}
	return 0;
}

int tgl_el2_kind_at(const struct tgl_el2_tables *t, uint64_t pa)
{
	unsigned gi = (unsigned)(pa >> 30);
	if (gi >= TGL_EL2_MAP_GB) return -1;
	uint64_t e = t->l1[gi];
	if ((e & 3) == D_TABLE)
		e = ((const uint64_t *)(uintptr_t)(e & ~UINT64_C(0xfff) & ((UINT64_C(1) << 48) - 1)))[(pa >> 21) & 511];
	return (int)((e >> 2) & 7);
}

#ifndef TGL_CHOOSER_HOST
#define SCTLR_M (UINT64_C(1) << 0)
#define SCTLR_A (UINT64_C(1) << 1)
#define SCTLR_C (UINT64_C(1) << 2)
#define SCTLR_I (UINT64_C(1) << 12)
#define SCTLR_WXN (UINT64_C(1) << 19)
#define HCR_E2H (UINT64_C(1) << 34)
/* TCR_EL2 (E2H=0): T0SZ=25, IRGN0/ORGN0 WBWA, SH0 inner, TG0 4K, PS 36-bit, RES1 23 and 31. */
#define TCR_VAL (UINT64_C(25) | UINT64_C(1) << 8 | UINT64_C(1) << 10 | UINT64_C(3) << 12 | \
	UINT64_C(1) << 16 | UINT64_C(1) << 23 | UINT64_C(1) << 31)
#define MAIR_VAL UINT64_C(0x44ff00)

static void inval_range(uint64_t lo, uint64_t hi)
{
	uint64_t ctr;
	__asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
	uint64_t line = UINT64_C(4) << ((ctr >> 16) & 0xf);
	for (uint64_t a = lo & ~(line - 1); a < hi; a += line)
		__asm__ volatile("dc ivac, %0" :: "r"(a) : "memory");
}

const char *tgl_el2_mmu_on(struct tgl_el2_tables *t, const struct tgl_el2_region *r,
	unsigned n, uint64_t *sctlr_before)
{
	uint64_t el, hcr, s;
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
	if (((el >> 2) & 3) != 2) return "EL2 map needs EL2";
	__asm__ volatile("mrs %0, hcr_el2" : "=r"(hcr));
	if (hcr & HCR_E2H) return "HCR_EL2.E2H set: VHE regime not supported";
	__asm__ volatile("mrs %0, sctlr_el2" : "=r"(s));
	*sctlr_before = s;
	if (s & SCTLR_M) return "MMU already on";
	/* Our own stores went to memory uncached; drop any stale line first. */
	for (unsigned k = 0; k < n; k++) inval_range(r[k].base, r[k].base + r[k].size);
	inval_range((uint64_t)(uintptr_t)t, (uint64_t)(uintptr_t)t + sizeof(*t));
	__asm__ volatile("dsb sy" ::: "memory");
	__asm__ volatile("msr mair_el2, %0" :: "r"(MAIR_VAL));
	__asm__ volatile("msr tcr_el2, %0" :: "r"(TCR_VAL));
	__asm__ volatile("msr ttbr0_el2, %0" :: "r"((uint64_t)(uintptr_t)t->l1));
	__asm__ volatile("isb; tlbi alle2; dsb sy; ic iallu; dsb sy; isb" ::: "memory");
	uint64_t ns = (s & ~(SCTLR_A | SCTLR_WXN)) | SCTLR_M | SCTLR_C | SCTLR_I;
	__asm__ volatile("msr sctlr_el2, %0; isb" :: "r"(ns) : "memory");
	return 0;
}
#endif
