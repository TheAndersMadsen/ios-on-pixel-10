/* Host test for lz4.c: decode the real boot_b kernel and compare with the
 * system lz4 output (oracle), then malformed-input cases. argv: lz4 image. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lz4.h"

static unsigned fails, checks, ticks;
#define CHECK(c, m) do { checks++; if (!(c)) { fails++; printf("FAIL %s\n", m); } } while (0)
static void tick(void) { ticks++; }

static unsigned char *slurp(const char *p, long *n)
{
	FILE *f = fopen(p, "rb");
	if (!f) { perror(p); exit(2); }
	fseek(f, 0, SEEK_END); *n = ftell(f); fseek(f, 0, SEEK_SET);
	unsigned char *b = malloc(*n ? *n : 1);
	if (fread(b, 1, *n, f) != (size_t)*n) exit(2);
	fclose(f);
	return b;
}

int main(int argc, char **argv)
{
	uint64_t out;
	if (argc == 3) {
		long ns, ne;
		unsigned char *s = slurp(argv[1], &ns), *e = slurp(argv[2], &ne);
		unsigned char *d = malloc(ne + 4096);
		memset(d, 0xa5, ne + 4096);
		int rc = tgl_lz4_legacy_decode(s, ns, d, ne + 4096, &out, tick);
		CHECK(rc == TGL_LZ4_OK, "real kernel decodes");
		CHECK(out == (uint64_t)ne, "real kernel length equals oracle");
		CHECK(!memcmp(d, e, ne), "real kernel bytes equal oracle");
		CHECK(d[ne] == 0xa5, "no write past output");
		CHECK(ticks >= (unsigned)(ne >> 20) - 8, "tick about every MiB");
		/* exact capacity works, one byte short overflows */
		rc = tgl_lz4_legacy_decode(s, ns, d, ne, &out, 0);
		CHECK(rc == TGL_LZ4_OK && out == (uint64_t)ne, "exact capacity");
		rc = tgl_lz4_legacy_decode(s, ns, d, ne - 1, &out, 0);
		CHECK(rc == TGL_LZ4_E_OVERFLOW, "capacity-1 overflows");
		/* truncated input at many points never succeeds or overruns */
		long cuts[] = { 3, 4, 7, 8, 100, ns / 2, ns - 1 };
		for (unsigned i = 0; i < sizeof cuts / sizeof cuts[0]; i++) {
			memset(d + ne, 0x5a, 4096);
			rc = tgl_lz4_legacy_decode(s, cuts[i], d, ne, &out, 0);
			CHECK(rc != TGL_LZ4_OK, "truncated input refused");
			CHECK(out <= (uint64_t)ne, "truncated: bounded output");
		}
		/* corrupt magic */
		unsigned char m0 = s[0]; s[0] ^= 1;
		CHECK(tgl_lz4_legacy_decode(s, ns, d, ne, &out, 0) == TGL_LZ4_E_MAGIC, "bad magic");
		s[0] = m0;
		/* corrupt bytes throughout block 0 must never write past cap */
		for (long at = 8; at < 4000000; at += 99991) {
			unsigned char sv = s[at]; s[at] ^= 0xff;
			unsigned char *small = malloc(1 << 20);
			memset(small, 0, 1 << 20);
			rc = tgl_lz4_legacy_decode(s, ns, small, (1 << 20) - 64, &out, 0);
			CHECK(rc != TGL_LZ4_OK && out <= (1 << 20) - 64, "corrupt stream bounded");
			free(small); s[at] = sv;
		}
		free(s); free(e); free(d);
	}
	/* hand-made blocks */
	{
		unsigned char blk[] = { 0x02,0x21,0x4c,0x18, 7,0,0,0,
			0x11, 'a', 0x01, 0x00,	/* 1 literal, off 1, len 1+4=5 -> "aaaaaa" */
			0x20, 'b', 'c' };	/* last: 2 literals */
		unsigned char d[32];
		int rc = tgl_lz4_legacy_decode(blk, sizeof blk, d, sizeof d, &out, 0);
		CHECK(rc == 0 && out == 8 && !memcmp(d, "aaaaaabc", 8), "overlap match replicates");
		unsigned char bad[] = { 0x02,0x21,0x4c,0x18, 4,0,0,0, 0x01, 0x05, 0x00, 0x00 };
		rc = tgl_lz4_legacy_decode(bad, sizeof bad, d, sizeof d, &out, 0);
		CHECK(rc == TGL_LZ4_E_OFFSET, "offset before output start");
		unsigned char zero[] = { 0x02,0x21,0x4c,0x18, 0,0,0,0 };
		CHECK(tgl_lz4_legacy_decode(zero, sizeof zero, d, sizeof d, &out, 0) == TGL_LZ4_E_TRUNC, "zero block size");
		unsigned char cat[] = { 0x02,0x21,0x4c,0x18, 2,0,0,0, 0x10,'x', 0x02,0x21,0x4c,0x18, 2,0,0,0, 0x10,'y' };
		rc = tgl_lz4_legacy_decode(cat, sizeof cat, d, sizeof d, &out, 0);
		CHECK(rc == 0 && out == 2 && d[0] == 'x' && d[1] == 'y', "concatenated frame");
		CHECK(tgl_lz4_legacy_decode(cat, sizeof cat, d, 1, &out, 0) == TGL_LZ4_E_OVERFLOW, "literal overflow");
	}
	printf("lz4 host test: %u checks, %u failed\n", checks, fails);
	return fails != 0;
}
