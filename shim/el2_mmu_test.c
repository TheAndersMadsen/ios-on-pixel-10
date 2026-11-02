/* Host test for el2_mmu.c table building. argv[1]: A0 FDT (optional). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "el2_mmu.h"
static unsigned fails, checks;
#define CHECK(c, m) do { checks++; if (!(c)) { fails++; printf("FAIL %s\n", m); } } while (0)
static struct tgl_el2_tables t __attribute__((aligned(4096)));
int main(int argc, char **argv)
{
	struct tgl_fdt_memory m;
	memset(&m, 0, sizeof m);
	m.ram_count = 2; m.ram[0] = (struct tgl_range){ 0x80000000ull, 0x80000000ull };
	m.ram[1] = (struct tgl_range){ 0x880000000ull, 0x80000000ull };
	m.reserved_count = 1; m.reserved[0] = (struct tgl_range){ 0x8af00000ull, 0xb4000 };
	struct tgl_el2_region r[3] = { { 0x80000000ull, 23ull << 20, TGL_EL2_WB, 1 },
		{ 0x8a000000ull, 0x2000000, TGL_EL2_WB, 0 }, { 0xf0000000ull, 1280u * 4 * 2856, TGL_EL2_NC, 0 } };
	CHECK(!tgl_el2_build(&t, &m, r, 3), "synthetic build");
	CHECK(tgl_el2_kind_at(&t, 0x80000000ull) == TGL_EL2_WB, "shim WB");
	CHECK(tgl_el2_kind_at(&t, 0x8ae00000ull) == TGL_EL2_DEV, "block holding a reservation stays Device");
	CHECK(tgl_el2_kind_at(&t, 0x8a000000ull) == TGL_EL2_WB, "clean block before it WB");
	CHECK(tgl_el2_kind_at(&t, 0x8b000000ull) == TGL_EL2_WB, "next block WB");
	CHECK(tgl_el2_kind_at(&t, 0xf0000000ull) == TGL_EL2_NC, "fb NC");
	CHECK(tgl_el2_kind_at(&t, 0x20000000ull) == TGL_EL2_DEV, "MMIO Device");
	CHECK(tgl_el2_kind_at(&t, 0x880000000ull) == TGL_EL2_DEV, "unclaimed RAM Device");
	CHECK(t.refused_blocks == 1, "one refused block");
	/* exec region touching a reservation refuses the whole map */
	struct tgl_el2_region bad = { 0x8ae00000ull, 0x400000, TGL_EL2_WB, 1 };
	CHECK(tgl_el2_build(&t, &m, &bad, 1) != 0, "exec over reservation refused");
	struct tgl_el2_region outside = { 0x10000000ull, 0x200000, TGL_EL2_WB, 1 };
	CHECK(tgl_el2_build(&t, &m, &outside, 1) != 0, "exec outside RAM refused");
	struct tgl_el2_region nc_exec = { 0x80000000ull, 0x200000, TGL_EL2_NC, 1 };
	CHECK(tgl_el2_build(&t, &m, &nc_exec, 1) != 0, "executable NC refused");
	if (argc > 1) {
		static uint8_t blob[TGL_FDT_MAX_SIZE];
		FILE *f = fopen(argv[1], "rb"); if (!f) { perror(argv[1]); return 2; }
		size_t n = fread(blob, 1, sizeof blob, f); fclose(f);
		memset(&m, 0, sizeof m);
		CHECK(!tgl_fdt_memory(blob, n, &m), "A0 FDT parses");
		struct tgl_el2_region a0[3] = { { 0x80000000ull, 22898992ull, TGL_EL2_WB, 1 },
			{ 0xc9c00000ull, 43253760ull, TGL_EL2_WB, 0 }, { 0xf0000000ull, 1280u * 4 * 2856, TGL_EL2_NC, 0 } };
		const char *e = tgl_el2_build(&t, &m, a0, 3);
		printf("A0 map: %s wb=%u nc=%u refused=%u l2=%u\n", e ? e : "ok", t.wb_blocks, t.nc_blocks, t.refused_blocks, t.l2_used);
		CHECK(!e && t.refused_blocks == 0, "A0 regions all cacheable");
		unsigned bad_wb = 0;
		for (unsigned i = 0; i < m.reserved_count; i++)
			for (uint64_t pa = m.reserved[i].base & ~0x1fffffull; pa < m.reserved[i].base + m.reserved[i].size; pa += 0x200000)
				bad_wb += tgl_el2_kind_at(&t, pa) != TGL_EL2_DEV;
		CHECK(bad_wb == 0, "every reserved region Device");
	}
	printf("el2 mmu host test: %u checks, %u failed\n", checks, fails);
	return fails != 0;
}
