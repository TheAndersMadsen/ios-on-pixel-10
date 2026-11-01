#pragma once
#include <stddef.h>
#include <stdint.h>

/* TEGUXNU v1 offsets are relative to the matched payload, not to the
 * concatenated ABL ramdisk. This parser performs no destination writes.
 * It validates arithmetic and source/destination extents; it does not turn
 * a static RAM-window choice into a runtime reservation authority. */
#define TGL_BOOT_LINE_LENGTH 608
#define TGL_PAGE UINT64_C(0x4000)
#define TGL_MAX_SEGS 64
#define TGL_SCAN_LIMIT UINT64_C(0x4000000)

struct payload_seg { uint64_t vmaddr, vmsize, file_off, file_size; };
struct payload {
	char magic[8];
	uint32_t version, nsegs;
	uint64_t virt_base, entry_va, adt_off, adt_size, kernel_end;
	uint64_t phys_base, mem_size;
	char cmdline[TGL_BOOT_LINE_LENGTH];
	struct payload_seg segs[];
};

struct tgl_payload_view {
	const struct payload *payload;
	uintptr_t source;
	uint64_t available;
	uint64_t adt_pa, ba_pa, top, entry_pa;
};

_Static_assert(offsetof(struct payload, segs) == 0x2a8, "TEGUXNU v1 layout");

static int tgl_add(uint64_t a, uint64_t b, uint64_t *out)
{
	if (b > UINT64_MAX - a) return 0;
	*out = a + b;
	return 1;
}

static int tgl_within(uint64_t size, uint64_t offset, uint64_t length)
{
	return offset <= size && length <= size - offset;
}

static int tgl_overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{
	return n && m && (a <= b ? b - a < n : a - b < m);
}

static int tgl_magic(const char *m)
{
	return m[0] == 'T' && m[1] == 'E' && m[2] == 'G' && m[3] == 'U' &&
	    m[4] == 'X' && m[5] == 'N' && m[6] == 'U' && m[7] == 0;
}

static const char *tgl_payload_validate(uintptr_t source, uint64_t available,
    uint64_t rd_start, uint64_t rd_size, struct tgl_payload_view *out)
{
	(void)rd_start; (void)rd_size; /* window policy moved to loader.c (v2) */
	if (!source || (source & 7) || !out || available < sizeof(struct payload))
		return "truncated/misaligned payload";
	const struct payload *p = (const struct payload *)source;
	if (!tgl_magic(p->magic) || p->version != 1 || !p->nsegs || p->nsegs > TGL_MAX_SEGS)
		return "bad payload header";
	uint64_t table_end = sizeof(*p) + (uint64_t)p->nsegs * sizeof(struct payload_seg);
	if (table_end > available) return "truncated segment table";
	if (p->virt_base != UINT64_C(0xfffffff004000000) ||
	    !p->phys_base || (p->phys_base & UINT64_C(0x1ffffff)) ||
	    !p->mem_size || (p->mem_size & (TGL_PAGE - 1)) ||
	    p->mem_size > UINT64_C(0x180000000)) return "invalid kernel window";
	uint64_t window_end, virtual_end;
	if (!tgl_add(p->phys_base, p->mem_size, &window_end) ||
	    !tgl_add(p->virt_base, p->mem_size, &virtual_end)) return "kernel window overflow";
	/* v2: the ramdisk-vs-window overlap is policy, moved to loader.c — the
	 * proven device delivery has ABL's initrd INSIDE the kernel window and
	 * a blanket refusal there blocked every physical boot. loader.c gates
	 * the copy geometry (ascending-copy safety + metadata placement). */
	/* The v1 packer writes all segment bytes first and the ADT last.
	 * Use that boundary rather than permitting segment offsets into a
	 * later retained archive after the payload in the concatenated initrd. */
	if ((p->adt_off & 7) || p->adt_off < table_end || !p->adt_size ||
	    p->adt_size > UINT32_MAX || !tgl_within(available, p->adt_off, p->adt_size))
		return "ADT outside payload";
	unsigned terminated = 0;
	for (unsigned i = 0; i < TGL_BOOT_LINE_LENGTH; ++i)
		if (!p->cmdline[i]) { terminated = 1; break; }
	if (!terminated) return "unterminated command line";
	uint64_t high = p->virt_base;
	int entry_valid = 0;
	for (uint32_t i = 0; i < p->nsegs; ++i) {
		const struct payload_seg *s = &p->segs[i];
		if (!s->vmsize || (s->vmaddr & (TGL_PAGE - 1)) || (s->vmsize & 7) ||
		    s->vmaddr < p->virt_base ||
		    !tgl_within(p->mem_size, s->vmaddr - p->virt_base, s->vmsize) ||
		    s->file_size > s->vmsize || (s->file_off & 7) ||
		    s->file_off < table_end || !tgl_within(p->adt_off, s->file_off, s->file_size))
			return "segment outside source/kernel extent";
		for (uint32_t j = 0; j < i; ++j)
			if (tgl_overlap(s->vmaddr, s->vmsize, p->segs[j].vmaddr, p->segs[j].vmsize))
				return "overlapping kernel segments";
		uint64_t end = s->vmaddr + s->vmsize; /* bounded by virtual window above */
		if (end > high) high = end;
		if (!(p->entry_va & 3) && p->entry_va >= s->vmaddr &&
		    tgl_within(s->file_size, p->entry_va - s->vmaddr, 4)) entry_valid = 1;
	}
	if (!entry_valid) return "entry outside file-backed segments";
	if ((p->kernel_end & (TGL_PAGE - 1)) || p->kernel_end < high ||
	    p->kernel_end < p->virt_base || p->kernel_end > virtual_end)
		return "invalid kernel metadata placement";
	uint64_t adt_pa = p->phys_base + (p->kernel_end - p->virt_base), adt_end, ba_pa, top;
	if (!tgl_add(adt_pa, p->adt_size, &adt_end) ||
	    !tgl_add(adt_end, TGL_PAGE - 1, &ba_pa)) return "metadata overflow";
	ba_pa &= ~(TGL_PAGE - 1);
	if (!tgl_add(ba_pa, TGL_PAGE, &top) || top > window_end ||
	    window_end - top < UINT64_C(0x4000000)) return "insufficient kernel headroom";
	struct tgl_payload_view view = {
		.payload = p, .source = source, .available = available,
		.adt_pa = adt_pa, .ba_pa = ba_pa, .top = top,
		.entry_pa = p->phys_base + (p->entry_va - p->virt_base)
	};
	*out = view;
	return 0;
}

/* ABL's retained vendor archives can exceed 6 MiB before the boot ramdisk.
 * Bound the scan by the actual initrd extent AND a 64 MiB search budget.
 * Never round the start down or read a candidate header past initrd-end. */
static const char *tgl_payload_find(uintptr_t rd_start, uintptr_t rd_end,
    struct tgl_payload_view *out)
{
	if (!rd_start || (rd_start & 7) || rd_end <= rd_start || !out)
		return "invalid initrd extent";
	uint64_t size = rd_end - rd_start;
	uint64_t budget = size < TGL_SCAN_LIMIT ? size : TGL_SCAN_LIMIT;
	if (budget < sizeof(struct payload)) return "initrd too small";
	const char *invalid = 0;
	for (uint64_t offset = 0; offset <= budget - sizeof(struct payload); offset += 8) {
		uintptr_t source = rd_start + offset;
		if (!tgl_magic((const char *)source)) continue;
		invalid = tgl_payload_validate(source, size - offset, rd_start, size, out);
		if (!invalid) return 0;
	}
	return invalid ? invalid : "no TEGUXNU payload within scan budget";
}

/* B1 entry contract §5: tegu-proven delivery — a TEGUPLD1 envelope directly
 * after the shim image:
 *   _end+0  "TEGUPLD1"    _end+8  u64 payload length    _end+16  TEGUXNU blob
 * The packer must ALSO raise the Linux Image image_size field at _head+16 to
 * cover the envelope (tegu build.sh does; ours must match before the first
 * embedded build). When image_size == the code extent, the diagnostic build
 * has no envelope and this returns the NO_EMBEDDED sentinel WITHOUT reading
 * past _end. Validation is the same tgl_payload_validate used for the scan. */
#define TGL_PAYLOAD_NO_EMBEDDED ((const char *)0)

static const char *tgl_payload_embedded(uintptr_t *source_out,
    uint64_t *bytes_out)
{
	extern char _head[], _end[];
	uint64_t image_size = *(const uint64_t *)(_head + 16);
	uint64_t offset = (uint64_t)_end - (uint64_t)_head;
	if (image_size > UINT64_C(128) * 1024 * 1024 ||
	    offset > image_size || image_size - offset < 16)
		return TGL_PAYLOAD_NO_EMBEDDED;
	const char *env = _end;
	if (!(env[0] == 'T' && env[1] == 'E' && env[2] == 'G' && env[3] == 'U' &&
	      env[4] == 'P' && env[5] == 'L' && env[6] == 'D' && env[7] == '1'))
		return TGL_PAYLOAD_NO_EMBEDDED;
	uint64_t bytes = *(const uint64_t *)(_end + 8);
	if (bytes > image_size - offset - 16)
		return "embedded payload exceeds Image";
	*source_out = (uintptr_t)(_end + 16);
	*bytes_out = bytes;
	return "embedded";
}

/* Exact source reads with aligned destination stores. Callers validate an
 * 8-byte-aligned destination and a multiple-of-eight memory extent first.
 * A partial last source word is packed, never over-read; remaining BSS is zero.
 */
static void tgl_segment_copy(uintptr_t dst, uintptr_t src, uint64_t filesz, uint64_t memsz)
{
	volatile uint64_t *d = (volatile uint64_t *)dst;
	const volatile uint64_t *s = (const volatile uint64_t *)src;
	uint64_t words = filesz / 8;
	for (uint64_t i = 0; i < words; ++i) d[i] = s[i];
	if (filesz & 7) {
		const volatile uint8_t *tail = (const volatile uint8_t *)(src + words * 8);
		uint64_t value = 0;
		for (unsigned i = 0; i < (filesz & 7); ++i) value |= (uint64_t)tail[i] << (i * 8);
		d[words++] = value;
	}
	for (uint64_t i = words; i < memsz / 8; ++i) d[i] = 0;
}
