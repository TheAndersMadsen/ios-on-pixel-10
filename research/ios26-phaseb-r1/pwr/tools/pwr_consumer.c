/* HOST ONLY: walk perf-r1 (r10) and pwr-r1 (pwr1) with the kernel's own consumers (varfs_overlay.h, hk_exec_rules.h from
 * XNU e731e68, the pwr1 kernel's base) and check exactly the intended changes: [0] springboard.plist (written under the
 * mask, not overridden, SBDontLockEver gone is checked in pwr_overlay.py) and one appended l entry for
 * /private/var/db/timezone/localtime, written and not overridden. Every other entry and both exec rule sets identical.
 *   cc -std=c11 -fsanitize=address,undefined -I <e731e68>/bsd pwr_consumer.c && ./a.out perf-r1.ovl pwr-r1.ovl */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>
#define MASK 0xA0080081u
#define SB "/private/var/mobile/Library/Preferences/com.apple.springboard.plist"
#define LT "/private/var/db/timezone/localtime"
#define TARGET "/var/db/timezone/zoneinfo/Europe/Copenhagen"
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
static unsigned checks;
struct ov { unsigned char *blob; unsigned long total; unsigned count, covers; char env[HK_RULES_MAX], deny[HK_RULES_MAX]; };
static unsigned char *rd(const char *p, unsigned long *n) {
	FILE *f = fopen(p, "rb"); CHECK(f); CHECK(!fseek(f, 0, SEEK_END)); long l = ftell(f); CHECK(l > 0 && l < HKOV_TOTAL_MAX);
	rewind(f); unsigned char *b = calloc((size_t)l + 1, 1); CHECK(b && fread(b, 1, (size_t)l, f) == (size_t)l); fclose(f);
	*n = (unsigned long)l; return b;
}
static struct ov load(const char *p) {
	struct ov o; memset(&o, 0, sizeof o); unsigned long n; unsigned long long h; const char *why = NULL;
	o.blob = rd(p, &n);
	CHECK(!hkov_check(o.blob, n, &o.total, &o.count, &h) && o.total == n);
	CHECK(!(MASK & ~hkov_groups(o.blob, o.total, o.count)));
	CHECK(!hkov_cover_check(o.blob, o.total, o.count, MASK, &o.covers) && o.covers == 1);
	unsigned long at = HKOV_HEADER_SIZE;
	for (unsigned i = 0; i < o.count; ++i) {
		struct hkov_entry e; CHECK(hkov_next(o.blob, o.total, &at, &e, &why) == 1);
		if (!(MASK & (1u << e.group)) || e.type != 'c') continue;
		if (!strcmp(e.path, "hk_env")) { CHECK(!hk_rules_append(o.env, sizeof o.env, (const char *)e.data, e.data_len)); CHECK(!hk_env_check(o.env)); }
		else { CHECK(!strcmp(e.path, "hk_deny")); CHECK(!hk_rules_append(o.deny, sizeof o.deny, (const char *)e.data, e.data_len)); CHECK(!hk_deny_check(o.deny)); }
	}
	CHECK(at == o.total);
	return o;
}
int main(int argc, char **argv) {
	CHECK(argc == 3);
	struct ov a = load(argv[1]), b = load(argv[2]);
	CHECK(b.count == a.count + 1);
	CHECK(!strcmp(a.env, b.env) && !strcmp(a.deny, b.deny));
	unsigned long oa = HKOV_HEADER_SIZE, ob = HKOV_HEADER_SIZE; const char *why = NULL;
	unsigned changed = 0, written_sb = 0, written_lt = 0;
	for (unsigned i = 0; i < b.count; ++i) {
		struct hkov_entry ea, eb; unsigned long sa = oa, sb = ob;
		CHECK(hkov_next(b.blob, b.total, &ob, &eb, &why) == 1);
		int live = (MASK & (1u << eb.group)) && eb.type != 'c' && !hkov_is_cover(&eb) &&
		    !hkov_overridden(b.blob, b.total, b.count, i, ob, &eb, MASK);
		if (i < a.count) {
			CHECK(hkov_next(a.blob, a.total, &oa, &ea, &why) == 1);
			int same = oa - sa == ob - sb && !memcmp(a.blob + sa, b.blob + sb, oa - sa);
			if (!same) {
				changed++;
				CHECK(i == 0 && eb.type == 'f' && eb.group == 0 && !strcmp(eb.path, SB) && eb.mode == 0600 && eb.uid == 501 && eb.gid == 501);
			}
			if (i == 0) { CHECK(live); written_sb = 1; }
		} else {
			CHECK(eb.type == 'l' && eb.group == 0 && !strcmp(eb.path, LT) && eb.mode == 0755 && eb.uid == 0 && eb.gid == 0);
			CHECK(eb.data_len == strlen(TARGET) && !memcmp(eb.data, TARGET, eb.data_len));
			CHECK(live); written_lt = 1;
		}
	}
	CHECK(changed == 1 && written_sb && written_lt && ob == b.total);
	free(a.blob); free(b.blob);
	printf("PASS: kernel consumers (e731e68); one record changed (springboard.plist), one appended (localtime -> %s), exec rules identical; %u checks\n", TARGET, checks);
	return 0;
}
