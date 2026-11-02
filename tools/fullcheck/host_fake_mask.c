/* host_fake.c with the mask the persist kernel adds. argv: IMAGE ERROR_AT_BLOCK(-1 for none) FIRST:COUNT ... */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static FILE *img; static long long err_at = -1, base; static uint8_t buf[16 * 4096]; static unsigned reads, mask_n, mask_total;
static struct { uint64_t a, n; } mask[64];
#define FC_LOG printf
#define FC_NOW_MS() ((uint64_t)0)
#define FC_DONE_READ() ((void)0)
static int fc_read(uint64_t lba, uint32_t count, const uint8_t **out) {
	if (count == 0 || count > 16) { printf("FAKE: bad count %u\n", count); exit(3); }
	for (unsigned m = 0; m < mask_n; m++) if ((lba - base) < mask[m].a + mask[m].n && (lba - base) + count > mask[m].a) { printf("FAKE: read a masked block at %llu\n", (unsigned long long)(lba - base)); exit(4); }
	if (err_at >= 0 && (long long)(lba - base) <= err_at && err_at < (long long)(lba - base + count)) return 5;
	if (fseeko(img, (off_t)(lba - base) * 4096, SEEK_SET) || fread(buf, 4096, count, img) != count) return 6;
	reads++; *out = buf; return 0;
}
static uint32_t mask_run(uint64_t lba, uint32_t count, int *skip) {
	uint64_t run = count; *skip = 0;
	for (unsigned m = 0; m < mask_n; m++) {
		if (lba >= mask[m].a && lba < mask[m].a + mask[m].n) { *skip = 1; return (uint32_t)(mask[m].a + mask[m].n - lba < run ? mask[m].a + mask[m].n - lba : run); }
		if (mask[m].a > lba && mask[m].a - lba < run) run = mask[m].a - lba;
	}
	return (uint32_t)run;
}
#define FC_READ fc_read
#define FC_MASK_RUN mask_run
#define FC_MASK_LINE() printf("blazer-ufs-fullcheck: masked %u blocks, table crc %08x\n", mask_total, 0xdf77bc20u)
#include "hakios.blazer_fullcheck.inc"
int main(int c, char **v) {
	img = fopen(v[1], "rb"); if (!img) return 2; err_at = atoll(v[2]);
	for (int i = 3; i < c; i++) { unsigned long long a, n; if (sscanf(v[i], "%llu:%llu", &a, &n) != 2) return 2; mask[mask_n].a = a; mask[mask_n].n = n; mask_n++; mask_total += (unsigned)n; }
	fseeko(img, 0, SEEK_END); uint64_t n = ftello(img) / 4096; base = 2500838;
	return ufs_fc_run(base, n);
}
