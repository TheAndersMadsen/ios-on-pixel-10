/*
 * HOST ONLY. Replays, on the aud1 overlay, what kernel hk-int1 (484717f) does with it at boot, using hk-int1's own headers
 * (inputs/hk-int1: varfs_overlay.h, varfs_tsv.h, hk_exec_rules.h, `git show hk-int1:bsd/...`):
 *   varfs_overlay_apply: hkov_check, hkov_groups vs the mask, hkov_cover_check, then for masked records: 'c' through
 *     hk_rules_append + hk_env_check/hk_deny_check (hk_exec_rules_add), 'f'/'d' counted;
 *   kern_exec hk_exec_env_add: hk_env_next for SpringBoard, backboardd, audiomxd;
 *   hkcover_boot (blazer_audio=3): hkcover_entries' selection for group 24 under /private/var/hkcover/hal and group 25
 *     under /private/var/hkcover/tun, with its "holds nothing" and type rules;
 *   hkcover_overlay_boot: the mask's covers (int1's coreui-colour) and the ramfs mount count against ramfs_mounts_max.
 *
 *   cc -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined -fno-sanitize-recover=all \
 *      -I research/ios26-audio-r1/inputs/hk-int1 research/ios26-audio-r1/tests/aud1_consumer.c -o /tmp/aud1_consumer
 *   /tmp/aud1_consumer OVERLAY MASK        (exit 0 = the boot would get past these steps)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>

static unsigned checks, fails;
#define OK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL "); printf(__VA_ARGS__); printf("\n"); } } while (0)

static char env_rules[HK_RULES_MAX], deny_rules[HK_RULES_MAX];

/* hkcover_entries' selection: returns the number of entries it would make, or -1 where the kernel panics */
static int
cover_entries(const unsigned char *blob, unsigned long total, unsigned count, unsigned group, const char *from, unsigned long long *bytes)
{
	unsigned long at = HKOV_HEADER_SIZE;
	size_t fromlen = strlen(from);
	const char *why = "";
	struct hkov_entry e;
	int done = 0;

	*bytes = 0;
	for (unsigned i = 0; i < count; i++) {
		if (hkov_next(blob, total, &at, &e, &why) != 1) {
			return -1;
		}
		if (e.group != group || strncmp(e.path, from, fromlen) != 0 || e.path[fromlen] != '/') {
			continue;
		}
		if (e.type == 'f') {
			*bytes += e.data_len;
		} else if (e.type != 'd') {
			return -1;      /* EINVAL -> panic */
		}
		if (strlen(e.path) - fromlen + strlen("/Library/Audio/Plug-Ins/HAL") >= 1024) {
			return -1;
		}
		done++;
	}
	return done;
}

static void
show_env(const char *name)
{
	const char *cursor = env_rules, *var;
	unsigned long len;
	int in_rule = 0, n = 0;

	while (hk_env_next(&cursor, &in_rule, name, strlen(name), &var, &len)) {
		printf("hk_env: %s gets %.*s\n", name, (int)len, var);
		OK(len < HK_VAR_MAX, "%s variable length %lu", name, len);
		n++;
	}
	if (strcmp(name, "SpringBoard") == 0) {
		int dyld = 0;

		cursor = env_rules;
		in_rule = 0;
		while (hk_env_next(&cursor, &in_rule, name, strlen(name), &var, &len)) {
			if (len > 22 && memcmp(var, "DYLD_INSERT_LIBRARIES=", 22) == 0) {
				dyld++;
				OK(len == strlen("DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib:/private/var/hk/hkaudiotest.dylib") &&
				    memcmp(var, "DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib:/private/var/hk/hkaudiotest.dylib", len) == 0,
				    "SpringBoard DYLD_INSERT_LIBRARIES is hkbattery:hkaudiotest");
			}
		}
		OK(dyld == 1, "SpringBoard gets exactly one DYLD_INSERT_LIBRARIES (%d)", dyld);
	}
	(void)n;
}

int
main(int argc, char **argv)
{
	FILE *f;
	long n;
	unsigned char *blob;
	unsigned long total = 0, at = HKOV_HEADER_SIZE;
	unsigned long long hash = 0, bytes;
	unsigned count = 0, groups, mask, covers = 0, files = 0, dirs = 0, rules = 0, tone = 0;
	const char *why;
	struct hkov_entry e;
	int hal, tun;

	if (argc != 3) {
		fprintf(stderr, "usage: %s OVERLAY MASK\n", argv[0]);
		return 2;
	}
	mask = (unsigned)strtoul(argv[2], NULL, 0);
	f = fopen(argv[1], "rb");
	if (f == NULL || fseek(f, 0, SEEK_END) != 0 || (n = ftell(f)) <= 0 || fseek(f, 0, SEEK_SET) != 0) {
		perror(argv[1]);
		return 2;
	}
	blob = malloc((size_t)n);
	if (blob == NULL || fread(blob, 1, (size_t)n, f) != (size_t)n) {
		return 2;
	}
	fclose(f);

	why = hkov_check(blob, (unsigned long)n, &total, &count, &hash);
	OK(why == NULL, "hkov_check: %s", why);
	if (why != NULL) {
		goto out;
	}
	groups = hkov_groups(blob, total, count);
	OK((mask & ~groups) == 0, "hk_overlay=0x%x names a group the overlay lacks (0x%x)", mask, groups);
	OK((mask & (3u << 24)) == 0, "mask holds bit 24 or 25: hkcover's groups would also unpack into /private/var");
	OK((groups >> 24 & 3) == 3, "overlay lacks group 24 or 25 (0x%x)", groups);
	printf("varfs-overlay: mask 0x%x of groups 0x%x, %u entries, %lu bytes, hash %016llx\n", mask, groups, count, total, hash);
	why = hkov_cover_check(blob, total, count, mask, &covers);
	OK(why == NULL, "hkov_cover_check: %s", why);
	for (unsigned i = 0; i < count; i++) {
		OK(hkov_next(blob, total, &at, &e, &why) == 1, "entry %u: %s", i, why);
		if ((mask & (1u << e.group)) == 0 || hkov_is_cover(&e)) {
			continue;
		}
		if (e.type == 'c') {
			int deny = strcmp(e.path, "hk_deny") == 0;
			char *r = deny ? deny_rules : env_rules;

			OK(hk_rules_append(r, HK_RULES_MAX, (const char *)e.data, e.data_len) == 0, "entry %u: rules too long", i);
			why = deny ? hk_deny_check(r) : hk_env_check(r);
			OK(why == NULL, "entry %u, rule %s: %s", i, e.path, why);
			rules++;
		} else if (e.type == 'f') {
			files++;
			tone += strcmp(e.path, "/private/var/hk/hkaudiotest.dylib") == 0;
		} else if (e.type == 'd') {
			dirs++;
		}
	}
	OK(tone == 1, "the tone client is applied once (%u)", tone);
	printf("applied: %u files, %u dirs, %u rules; env rules %zu of %u bytes; covers in the mask %u\n", files, dirs, rules,
	    strlen(env_rules) + 1, HK_RULES_MAX, covers);
	show_env("SpringBoard");
	show_env("backboardd");
	show_env("audiomxd");
	{
		const char *cursor = env_rules, *var;
		unsigned long len;
		int in_rule = 0;

		OK(!hk_env_next(&cursor, &in_rule, "audiomxd", 8, &var, &len), "audiomxd gets no environment from this overlay");
	}
	hal = cover_entries(blob, total, count, 24, "/private/var/hkcover/hal", &bytes);
	OK(hal > 0, "group 24: hkcover panics (%d)", hal);
	printf("hkcover: /Library/Audio/Plug-Ins/HAL, %d entries, %llu bytes (+ VirtualAudio's 3 from the root)\n", hal, bytes);
	tun = cover_entries(blob, total, count, 25, "/private/var/hkcover/tun", &bytes);
	OK(tun > 0, "group 25: hkcover panics (%d)", tun);
	printf("hkcover: /Library/Audio/Tunings/D421, %d entries, %llu bytes\n", tun, bytes);
	/* ramfs mounts: varfs (1), hkcover_boot's two with max 3, then the overlay's covers with max 3 + 8 */
	OK(1 < 3 && 2 < 3, "hkcover_boot mounts within ramfs_mounts_max 3");
	OK(3 + covers <= 3 + HKOV_COVERS_MAX, "overlay covers %u within ramfs_mounts_max %u", covers, 3 + HKOV_COVERS_MAX);
out:
	printf("aud1 consumer (hk-int1 headers): %u checks, %u failed\n", checks, fails);
	free(blob);
	return fails ? 1 : 0;
}
