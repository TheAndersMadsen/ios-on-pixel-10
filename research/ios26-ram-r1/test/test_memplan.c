/*
 * Host test of ref/blazer_memplan.h (the exact header in XNU hk-ram-full) against this phone's map.
 *   cc -Wall -Wextra -Werror -I../ref test_memplan.c -o t && ./t     (reserved.h from gen_reserved.py)
 */
#include <stdio.h>
#include <stdlib.h>
#include "blazer_memplan.h"
#include "reserved.h"

#define N(a) (sizeof(a) / sizeof((a)[0]))
#define GIB (1ULL << 30)
#define MIB (1ULL << 20)
#define BASE 0x882000000ULL          /* the phone loader's window (image_tool --window-base) */
#define OLD  0x100000000ULL          /* loader memSize and memSizeActual: the live line's "was" */
#define MTE_BASE 0xbe0f83000ULL      /* ABL: "MTE addr : 0xbe0f83000", "tag base: 0xbe0f83000" */
#define ANDROID_TOP_FIRST 0xbbd1f8000ULL /* iomem: first reserved span at the high bank's top */

static unsigned checks, fails;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static uint64_t
overlap(uint64_t a, uint64_t b, uint64_t c, uint64_t d)
{
	uint64_t lo = a > c ? a : c, hi = b < d ? b : d;
	return hi > lo ? hi - lo : 0;
}

/* The pre-change kernel's blazer_mem_apply (b228c4f/484717f arm_init.c), as a function. */
static int
legacy(uint64_t base, uint64_t old, uint64_t old_actual, uint32_t gib, int fake, int report, uint64_t *end, uint64_t *actual)
{
	uint64_t top = 0xbbd000000ULL;
	if ((uint64_t)gib <= (old >> 30)) return BLAZER_MEM_KEEP;
	if (fake) top = base + ((uint64_t)gib << 30);
	if (base < 0x882000000ULL || base >= top || gib > 64) return BLAZER_MEM_REFUSE;
	*end = base + ((uint64_t)gib << 30) < top ? base + ((uint64_t)gib << 30) : top;
	if (*end <= base + old) return BLAZER_MEM_KEEP;
	*actual = report ? *end - base : old_actual;
	return BLAZER_MEM_GROW;
}

static void
exact(uint32_t gib, int report, int want_rc, uint64_t want_end, uint64_t want_actual)
{
	uint64_t e = 0, a = 0;
	int rc = blazer_mem_plan(BASE, OLD, OLD, gib, 0, report, &e, &a);
	CHECK(rc == want_rc, "gib %u report %d: rc %d want %d", gib, report, rc, want_rc);
	if (rc == BLAZER_MEM_GROW) {
		CHECK(e == want_end, "gib %u: end 0x%llx want 0x%llx", gib, (unsigned long long)e, (unsigned long long)want_end);
		CHECK(a == want_actual, "gib %u: actual 0x%llx want 0x%llx", gib, (unsigned long long)a, (unsigned long long)want_actual);
	}
}

int
main(void)
{
	uint64_t e, a, e2, a2;

	/* 1. Exact phone values. 13 = int1's line, must equal the live log: window + 0x33b000000, hw.memsize 0x100000000. */
	exact(0, 0, BLAZER_MEM_KEEP, 0, 0);
	exact(4, 0, BLAZER_MEM_KEEP, 0, 0);
	exact(5, 0, BLAZER_MEM_GROW, BASE + 5 * GIB, OLD);
	exact(13, 0, BLAZER_MEM_GROW, 0xbbd000000ULL, OLD);
	CHECK(0xbbd000000ULL - BASE == 0x33b000000ULL, "13 GiB window size is the live line's");
	exact(13, 1, BLAZER_MEM_GROW, 0xbbd000000ULL, 0x33b000000ULL);
	for (uint32_t g = 14; g <= 64; g++) {
		exact(g, 0, BLAZER_MEM_GROW, 0xbe0f80000ULL, 0x400000000ULL);
		exact(g, 1, BLAZER_MEM_GROW, 0xbe0f80000ULL, 0x400000000ULL);
	}
	exact(65, 0, BLAZER_MEM_REFUSE, 0, 0);
	CHECK(blazer_mem_plan(0x880000000ULL, OLD, OLD, 16, 0, 0, &e, &a) == BLAZER_MEM_REFUSE, "base below bottom refused");
	CHECK(blazer_mem_plan(0xbe0f80000ULL, 0, 0, 16, 0, 0, &e, &a) == BLAZER_MEM_REFUSE, "base at the full top refused");

	/* 2. Below the full map the new code is the old code, every input combination. */
	for (uint32_t g = 0; g < BLAZER_MEM_FULL_GIB; g++)
	for (int fake = 0; fake < 2; fake++)
	for (int rep = 0; rep < 2; rep++)
	for (uint64_t base = 0x880000000ULL; base <= 0xbc0000000ULL; base += 0x22000000ULL)
	for (uint64_t old = 0; old <= 8 * GIB; old += GIB) {
		int r1, r2;
		e = a = e2 = a2 = 0;
		r1 = blazer_mem_plan(base, old, 0x1234000ULL + old, g, fake, rep, &e, &a);
		r2 = legacy(base, old, 0x1234000ULL + old, g, fake, rep, &e2, &a2);
		CHECK(r1 == r2 && e == e2 && a == a2, "legacy differs: gib %u fake %d rep %d base 0x%llx old 0x%llx",
		    g, fake, rep, (unsigned long long)base, (unsigned long long)old);
	}

	/* 3. Every phone window (no fake) against the map. */
	for (uint32_t g = 0; g <= 70; g++)
	for (int rep = 0; rep < 2; rep++) {
		int rc = blazer_mem_plan(BASE, OLD, OLD, g, 0, rep, &e, &a);
		if (rc != BLAZER_MEM_GROW) continue;
		CHECK(e <= BLAZER_RAM_TOP_TAGS && e < MTE_BASE, "gib %u: end 0x%llx at or past the MTE tag base", g, (unsigned long long)e);
		CHECK((e & 0x3fffULL) == 0, "gib %u: end not 16 KiB aligned", g);
		CHECK(a >= e - BASE || (g < BLAZER_MEM_FULL_GIB && !rep), "gib %u: hw.memsize below managed", g);
		/* inside one contiguous run of banks */
		uint64_t covered = 0;
		for (size_t i = 0; i < N(banks); i++) covered += overlap(BASE, e, banks[i].pa, banks[i].end);
		CHECK(covered == e - BASE, "gib %u: window leaves the FDT memory banks", g);
		for (size_t i = 0; i < N(fixed); i++)
			CHECK(!overlap(BASE, e, fixed[i].pa, fixed[i].end), "gib %u: window over fixed carve-out %s", g, fixed[i].name);
		for (size_t i = 0; i < N(iomem_reserved); i++) {
			uint64_t o = overlap(BASE, e, iomem_reserved[i].pa, iomem_reserved[i].end);
			if (g < BLAZER_MEM_FULL_GIB)
				CHECK(!o, "gib %u: window over Android iomem reserved 0x%llx", g, (unsigned long long)iomem_reserved[i].pa);
			else
				CHECK(!o || iomem_reserved[i].pa >= ANDROID_TOP_FIRST, "gib %u: full map over iomem reserved 0x%llx below the top spans",
				    g, (unsigned long long)iomem_reserved[i].pa);
		}
		for (size_t i = 0; i < N(android_dynamic); i++) {
			uint64_t o = overlap(BASE, e, android_dynamic[i].pa, android_dynamic[i].end);
			CHECK(!o || g >= BLAZER_MEM_FULL_GIB, "gib %u: window over %s", g, android_dynamic[i].name);
			CHECK(!o || android_dynamic[i].end <= 0xbfd000000ULL || android_dynamic[i].pa >= MTE_BASE,
			    "gib %u: over non-reusable %s", g, android_dynamic[i].name);
		}
	}

	/* 4. The breakdown for blazer_mem=16 on the phone. */
	blazer_mem_plan(BASE, OLD, OLD, 16, 0, 0, &e, &a);
	{
		uint64_t inst = 0, low = banks[0].end - banks[0].pa, fixed_low = 0, fixed_high = 0, dyn = 0, tail = 0;
		for (size_t i = 0; i < N(banks); i++) inst += banks[i].end - banks[i].pa;
		for (size_t i = 0; i < N(fixed); i++) {
			fixed_low += overlap(banks[0].pa, banks[0].end, fixed[i].pa, fixed[i].end);
			fixed_high += overlap(0x880000000ULL, 0xc00000000ULL, fixed[i].pa, fixed[i].end);
		}
		for (size_t i = 0; i < N(android_dynamic); i++) dyn += overlap(BASE, e, android_dynamic[i].pa, android_dynamic[i].end);
		tail = 0xc00000000ULL - e;
		CHECK(inst == BLAZER_RAM_INSTALLED, "FDT banks %llu GiB, header says 16", (unsigned long long)(inst >> 30));
		CHECK(a == inst, "hw.memsize is the installed DRAM");
		CHECK(fixed_high == 0, "no fixed carve-out in the high bank");
		printf("blazer_mem=16 on the phone (base 0x%llx, loader + 0x%llx):\n", (unsigned long long)BASE, (unsigned long long)OLD);
		printf("  installed (8 FDT banks)            0x%09llx  %6.2f GiB  -> hw.memsize\n", (unsigned long long)inst, (double)inst / GIB);
		printf("  managed window 0x%llx..0x%llx 0x%09llx %6.2f GiB  -> max_mem (was 0x33b000000, 12.92 GiB)\n",
		    (unsigned long long)BASE, (unsigned long long)e, (unsigned long long)(e - BASE), (double)(e - BASE) / GIB);
		printf("    of which Android places its own dynamic pools there at its boot: %llu MiB (vstream/vframe/pkvm_iommu_cma, map reusable)\n",
		    (unsigned long long)(dyn / MIB));
		printf("  unmanaged high, bottom 0x880000000..0x%llx: %llu MiB (16 MiB iomem reserved, owner unknown, + loader alignment)\n",
		    (unsigned long long)BASE, (unsigned long long)((BASE - 0x880000000ULL) / MIB));
		printf("  unmanaged high, top 0x%llx..0xc00000000: %llu MiB (MTE tag store from 0x%llx; faprev, faceauth above)\n",
		    (unsigned long long)e, (unsigned long long)(tail / MIB), (unsigned long long)MTE_BASE);
		printf("  unmanaged low bank 0x80000000..0x100000000: %llu MiB, of which fixed DT carve-outs %llu MiB, the rest shim/ABL/panel/USB/UFS and blazer_low (denied)\n",
		    (unsigned long long)(low / MIB), (unsigned long long)(fixed_low / MIB));
		printf("  managed / installed = %.1f %%\n", 100.0 * (double)(e - BASE) / (double)inst);
	}
	printf("%u checks, %u failed\n", checks, fails);
	return fails != 0;
}
