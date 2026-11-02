#pragma once
#include <stdint.h>

/* LZ4 legacy frame (magic 0x184C2102, the Linux "lz4 -l" kernel format):
 * repeated [u32 LE compressed block size][LZ4 block], each decoding to at
 * most 8 MiB; a block size equal to the magic restarts a concatenated frame. Freestanding, byte-granular accesses only
 * (safe on Device memory with the MMU off), every read and write bounded.
 * tick(), when non-null, runs about every 1 MiB of output (watchdog pat). */
#define TGL_LZ4_LEGACY_MAGIC UINT32_C(0x184c2102)
#define TGL_LZ4_LEGACY_BLOCK (UINT64_C(8) << 20)

enum {
	TGL_LZ4_OK = 0,
	TGL_LZ4_E_MAGIC = 1,	/* no legacy magic */
	TGL_LZ4_E_TRUNC = 2,	/* block header/body runs past the input */
	TGL_LZ4_E_OVERFLOW = 3,	/* output would exceed dst_cap */
	TGL_LZ4_E_OFFSET = 4,	/* match offset 0 or before the output start */
	TGL_LZ4_E_BLOCK = 5,	/* malformed block, or one decoding to > 8 MiB */
};

int tgl_lz4_legacy_decode(const uint8_t *src, uint64_t src_len,
	uint8_t *dst, uint64_t dst_cap, uint64_t *out_len, void (*tick)(void));
