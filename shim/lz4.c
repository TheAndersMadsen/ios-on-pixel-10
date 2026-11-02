/* LZ4 legacy-frame decoder for the chooser's stock-kernel chain (A2).
 * Byte-granular, bounds-checked, no libc. Host-tested against the system
 * lz4 on the real boot_b kernel (lz4_test.c). */
#include "lz4.h"

static uint32_t rd32(const uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
	    (uint32_t)p[3] << 24;
}

/* One LZ4 block into dst[pos..]; the window is the whole output so far
 * (legacy blocks are independent, but a back-reference into earlier output
 * never occurs in their encoding; allowing it costs nothing and stays safe). */
static int block(const uint8_t *s, uint64_t n, uint8_t *dst, uint64_t cap,
	uint64_t *pos, uint64_t block_start, void (*tick)(void), uint64_t *next_tick)
{
	uint64_t i = 0, o = *pos;
	const uint64_t limit = block_start + TGL_LZ4_LEGACY_BLOCK;
	for (;;) {
		if (i >= n) return TGL_LZ4_E_BLOCK;
		unsigned token = s[i++];
		uint64_t lit = token >> 4;
		if (lit == 15) {
			unsigned b;
			do {
				if (i >= n) return TGL_LZ4_E_BLOCK;
				b = s[i++];
				lit += b;
			} while (b == 255);
		}
		if (lit > n - i) return TGL_LZ4_E_BLOCK;
		if (lit > cap - o || o + lit > limit) return lit > cap - o ? TGL_LZ4_E_OVERFLOW : TGL_LZ4_E_BLOCK;
		for (uint64_t k = 0; k < lit; k++) dst[o + k] = s[i + k];
		i += lit;
		o += lit;
		if (i == n) break;		/* last sequence: literals only */
		if (n - i < 2) return TGL_LZ4_E_BLOCK;
		uint64_t off = (uint64_t)s[i] | (uint64_t)s[i + 1] << 8;
		i += 2;
		if (!off || off > o) return TGL_LZ4_E_OFFSET;
		uint64_t len = token & 15;
		if (len == 15) {
			unsigned b;
			do {
				if (i >= n) return TGL_LZ4_E_BLOCK;
				b = s[i++];
				len += b;
			} while (b == 255);
		}
		len += 4;
		if (len > cap - o) return TGL_LZ4_E_OVERFLOW;
		if (o + len > limit) return TGL_LZ4_E_BLOCK;
		/* Forward byte copy: overlapping matches (off < len) replicate. */
		for (uint64_t k = 0; k < len; k++) dst[o + k] = dst[o - off + k];
		o += len;
		if (tick && o >= *next_tick) {
			tick();
			*next_tick = o + (UINT64_C(1) << 20);
		}
	}
	*pos = o;
	return TGL_LZ4_OK;
}

int tgl_lz4_legacy_decode(const uint8_t *src, uint64_t src_len,
	uint8_t *dst, uint64_t dst_cap, uint64_t *out_len, void (*tick)(void))
{
	uint64_t i, o = 0, next_tick = UINT64_C(1) << 20;
	*out_len = 0;
	if (src_len < 4 || rd32(src) != TGL_LZ4_LEGACY_MAGIC) return TGL_LZ4_E_MAGIC;
	i = 4;
	while (i < src_len) {
		if (src_len - i < 4) return TGL_LZ4_E_TRUNC;
		uint32_t bs = rd32(src + i);
		i += 4;
		if (bs == TGL_LZ4_LEGACY_MAGIC) continue;	/* concatenated frame */
		if (!bs || bs > src_len - i) return TGL_LZ4_E_TRUNC;
		int rc = block(src + i, bs, dst, dst_cap, &o, o, tick, &next_tick);
		if (rc) { *out_len = o; return rc; }
		i += bs;
	}
	*out_len = o;
	return o ? TGL_LZ4_OK : TGL_LZ4_E_TRUNC;	/* magic alone is no kernel */
}
