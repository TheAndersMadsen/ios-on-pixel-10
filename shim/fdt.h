#pragma once
#include <stdint.h>
#define TGL_FDT_MAX_SIZE (2U * 1024U * 1024U)
#define TGL_FDT_MAX_RAM 32
#define TGL_FDT_MAX_RESERVED 256
#define TGL_FDT_MAX_POOLS 32
#define TGL_FDT_MAX_ALLOC 128
struct tgl_range { uint64_t base, size; };
struct tgl_pool {
	char name[64];
	uint64_t size, alignment;
	unsigned first_range, range_count, unresolved;
};
struct tgl_fdt_memory {
	struct tgl_range ram[TGL_FDT_MAX_RAM];
	struct tgl_range reserved[TGL_FDT_MAX_RESERVED];
	struct tgl_range alloc[TGL_FDT_MAX_ALLOC];
	struct tgl_pool pools[TGL_FDT_MAX_POOLS];
	unsigned ram_count, reserved_count, pool_count, alloc_count;
	uint32_t total_size;
	uint64_t initrd_start, initrd_end;
	unsigned initrd_fields, psci_method; /* PSCI: 0 unknown, 1 SMC, 2 HVC. */
	unsigned display_flags; /* TGL_FDT_DISP_* from /chosen/bootargs, default 0. */
	char compatible[64];
};
#define TGL_FDT_DISP_SNAP (1u << 0)
#define TGL_FDT_DISP_REVIVE (1u << 1)
/* Pure bounded token parser, exported for host gate regression tests. */
unsigned tgl_fdt_display_bootargs(const void *data, uint32_t size);
/* Caller supplies genuinely readable bytes. A bootloader's readable x0 is
 * still a boot-protocol precondition, not established by parsing. */
const char *tgl_fdt_memory(const void *blob, uint64_t available,
	struct tgl_fdt_memory *out);
int tgl_range_in_ram(const struct tgl_fdt_memory *m, struct tgl_range range);
/* Gate the ENTIRE XNU allocator window, not only segment destination bytes.
 * Dynamic pools describe allocation requests, NOT proven occupied memory.
 * Pending an authoritative placement plan, reject possible conflicts. */
const char *tgl_window_check(const struct tgl_fdt_memory *m,
	struct tgl_range window, const struct tgl_range *live, unsigned live_count);
int fdt_chosen_u64(uintptr_t fdt, const char *prop, uint64_t *out);
int fdt_valid(uintptr_t fdt);
int fdt_root_compatible(uintptr_t fdt, char *out, unsigned size);
/* v2: bounded scan of the ABL FDT for a framebuffer node (named "fb" or
 * "framebuffer", or a compatible containing that word); returns the node's
 * first reg address as the candidate ABL scanout PA, or 0 when the tree has
 * none (the captured laguna live DT has none - DPU readback is then the
 * only live-scanout source). */
int fdt_find_framebuffer(uintptr_t fdt, uint64_t *out, const char **which);

/* v3.9b (U1): bounded scan for the UFS host-controller node. Matches any
 * node named "ufs"/"ufshc" (optionally @unit) or advertising a compatible
 * containing "ufshc" or "jedec,ufs"; skips status!="okay" nodes. Fills the
 * positional reg tuples of the real laguna layout (reg-names: ufs_hc,
 * ufs_top, ufs_phy_sram, psm_status_hsios, psm_status_ufs_hc,
 * psm_status_ufs_phy — reg-names and reg are always in matching order in
 * the blazer DT). Returns 1 with hc != 0, 0 when the tree has no UFS node
 * (the caller keeps its build-time fallback constants). */
struct tgl_ufs_fdt_regions {
	uint64_t hc, top, phy_sram;	/* reg tuples 0..2 */
	uint64_t psm[3];		/* reg tuples 3..5 (0 when absent) */
	unsigned reg_tuples;		/* tuples parsed (up to 6) */
	unsigned named;			/* first reg-names string is "ufs_hc" */
	uint64_t hc_bytes, top_bytes;	/* sizes of the first two tuples */
	unsigned ah8_pg, swh8_pg;	/* google,enable-hc-{ah8,swh8}-pg present */
	unsigned decouple_ufs_en;	/* google,decouple-ufs-en present */
};
int fdt_find_ufs(uintptr_t fdt, struct tgl_ufs_fdt_regions *out);
