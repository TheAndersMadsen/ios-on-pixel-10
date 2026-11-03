/* Host: run hk-int1's own varfs_overlay.h checks (hkov_check, hkov_groups, hkov_cover_check) on an overlay blob.
   cc -I DIR_WITH_varfs_overlay.h check_overlay.c && ./a.out BLOB 0xA0080081 */
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include "varfs_overlay.h"
int
main(int argc, char **argv)
{
	FILE *f = fopen(argv[1], "rb");
	static unsigned char b[48 << 20];
	unsigned long n = fread(b, 1, sizeof(b), f), total = 0;
	unsigned int count = 0, covers = 0, mask = (unsigned int)strtoul(argv[2], 0, 0);
	unsigned long long hash = 0;
	const char *why = hkov_check(b, n, &total, &count, &hash);
	printf("hkov_check: %s, %u entries, %lu bytes, hash %016llx\n", why ? why : "ok", count, total, hash);
	if (why) return 1;
	unsigned int g = hkov_groups(b, total, count);
	printf("groups 0x%x, mask 0x%x, mask & ~groups = 0x%x\n", g, mask, mask & ~g);
	why = hkov_cover_check(b, total, count, mask, &covers);
	printf("hkov_cover_check: %s, covers %u\n", why ? why : "ok", covers);
	return why != NULL || (mask & ~g) != 0;
}
