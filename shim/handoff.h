#pragma once
#include "fdt.h"
/* Shared production planning functions: no memory writes or CPU state changes. */
static inline int tgl_ranges_overlap(struct tgl_range a, struct tgl_range b)
{
	return a.base < b.base + b.size && b.base < a.base + a.size;
}
static inline const char *tgl_handoff_inputs(const struct tgl_fdt_memory *m,
	uint64_t dtb, struct tgl_range shim, struct tgl_range *rd)
{
	struct tgl_range tree = { dtb, m->total_size };
	if (!tgl_range_in_ram(m, tree)) return "FDT source outside RAM";
	if (!tgl_range_in_ram(m, shim)) return "resident shim outside RAM";
	if (m->initrd_fields != 3 || m->initrd_end <= m->initrd_start)
		return "missing/invalid initrd extent";
	rd->base = m->initrd_start; rd->size = m->initrd_end - m->initrd_start;
	if (!tgl_range_in_ram(m, *rd)) return "initrd source outside RAM";
	if (tgl_ranges_overlap(*rd, tree) || tgl_ranges_overlap(*rd, shim) ||
	    tgl_ranges_overlap(tree, shim)) return "resident inputs overlap";
	return 0;
}
static inline const char *tgl_handoff_window(const struct tgl_fdt_memory *m,
	struct tgl_range window, uint64_t dtb, struct tgl_range shim, struct tgl_range rd,
	struct tgl_range console)
{
	struct tgl_range live[4] = { {dtb, m->total_size}, shim, rd, console };
	return tgl_window_check(m, window, live, console.size ? 4 : 3);
}

static inline int tgl_qemu_profile(const char *s)
{
	const char expected[] = "linux,dummy-virt";
	unsigned i = 0;
	while (expected[i] && s[i] == expected[i]) ++i;
	return !expected[i] && !s[i];
}
