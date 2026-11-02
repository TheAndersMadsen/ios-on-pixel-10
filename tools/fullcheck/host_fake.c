/* The kernel's loop against a file instead of the disk. argv: IMAGE [ERROR_AT_BLOCK] */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
static FILE *img; static long long err_at = -1, base; static uint8_t buf[16 * 4096]; static unsigned reads;
#define FC_LOG printf
#define FC_NOW_MS() ((uint64_t)0)
#define FC_DONE_READ() ((void)0)
static int fc_read(uint64_t lba, uint32_t count, const uint8_t **out) {
	if (count == 0 || count > 16) { printf("FAKE: bad count %u\n", count); exit(3); }
	if (err_at >= 0 && (long long)(lba - base) <= err_at && err_at < (long long)(lba - base + count)) return 5;
	if (fseeko(img, (off_t)(lba - base) * 4096, SEEK_SET) || fread(buf, 4096, count, img) != count) return 6;
	reads++; *out = buf; return 0;
}
#define FC_READ fc_read
#include "hakios.blazer_fullcheck.inc"
int main(int c, char **v) {
	img = fopen(v[1], "rb"); if (!img) return 2; if (c > 2) err_at = atoll(v[2]);
	fseeko(img, 0, SEEK_END); uint64_t n = ftello(img) / 4096; base = 2500838;
	return ufs_fc_run(base, n);
}
