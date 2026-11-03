/*
 * HOST test for hk-obs1's pure kernel headers: hk_env_merge.h (one DYLD_INSERT_LIBRARIES per program, over int1's real
 * hk_env text plus the mirror rule), hk_obs.h (respawn table, console budget, bounded status text).
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I ../xnu-src/bsd/kern test_hk_obs.c && ./a.out
 * Mutation hook: -DMUT=n breaks one thing on purpose; the test must fail (tests/run.sh checks).
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hk_exec_rules.h"
#include "hk_env_merge.h"
#include "hk_obs.h"

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

struct got {
	char var[16][HK_VAR_MAX];
	int n;
};

static int
emit(void *ctx, const char *var, unsigned long len)
{
	struct got *g = ctx;

	if (g->n >= 16 || len >= HK_VAR_MAX) {
		return 7;
	}
	memcpy(g->var[g->n], var, len);
	g->var[g->n][len] = 0;
	g->n++;
	return 0;
}

static const char *
get(const struct got *g, const char *key)        /* getenv: the first */
{
	size_t k = strlen(key);

	for (int i = 0; i < g->n; i++) {
		if (strncmp(g->var[i], key, k) == 0 && g->var[i][k] == '=') {
			return g->var[i] + k + 1;
		}
	}
	return NULL;
}

static int
count_key(const struct got *g, const char *key)
{
	size_t k = strlen(key);
	int c = 0;

	for (int i = 0; i < g->n; i++) {
		c += strncmp(g->var[i], key, k) == 0 && g->var[i][k] == '=';
	}
	return c;
}

static void
run(const char *rules, const char *name, struct got *g, int *mirror, int *ndyld, unsigned *lost)
{
	char dyld[HK_VAR_MAX];
	int count, rc;

	memset(g, 0, sizeof(*g));
	rc = hk_env_for_program(rules, name, strlen(name), dyld, sizeof(dyld), emit, g, &count, mirror, ndyld, lost);
	CHECK(rc == 0);
	CHECK(count == g->n);
}

/* int1-r1.ovl record 39, verbatim (tccd's old mirror rule last), and obs1's rule */
#define INT1_39 "backboardd:DYLD_INSERT_LIBRARIES=/private/var/hk/hgltrack.dylib:/private/var/hk/hk_container_ready.dylib:/private/var/hk/hk_accel_once.dylib;HK_CONTAINER_READY=probe;HK_ACCEL_ONCE=skip,Preferences:DYLD_INSERT_LIBRARIES=/private/var/hk/hkart.dylib:/private/var/hk/hk_mainwatch.dylib;HK_SETTINGS_ARTWORK=1;HK_MAINWATCH=1,iconservicesagent:DYLD_INSERT_LIBRARIES=/private/var/hk/hkart.dylib;HK_SETTINGS_ARTWORK=1,powerd:DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib;HK_BATTERY_TRACE=1,SpringBoard:FEATUREFLAGS_DISABLED=SpringBoard/Autobahn:SpringBoard/AutobahnLegacyMigration:SpringBoard/AutobahnLegacyMigrationSupportingDistinctHome;DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib;HK_BATTERY_TRACE=1"
#define MIRROR "wifid+configd+bluetoothd+WirelessRadioManagerd+CommCenter+locationd+tccd+lsd+SpringBoard+MobilePhone+Preferences:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_logmirror.dylib;HK_LOGMIRROR=1;OS_ACTIVITY_DT_MODE=YES"
#define ML "/private/var/hk/hk_logmirror.dylib"

static void
test_merge(void)
{
	static const char rules[] = INT1_39 "," MIRROR;
	struct got g;
	int mirror, ndyld;
	unsigned lost;

	CHECK(hk_env_check(rules) == NULL);
	CHECK(strlen(rules) + 1 <= HK_RULES_MAX);
	/* Preferences: its own two libraries first, then the mirror's; one variable; the others kept */
	run(rules, "Preferences", &g, &mirror, &ndyld, &lost);
	CHECK(ndyld == 2 && lost == 0 && mirror == 1);
	CHECK(count_key(&g, "DYLD_INSERT_LIBRARIES") == 1);
	CHECK(get(&g, "DYLD_INSERT_LIBRARIES") != NULL &&
	    strcmp(get(&g, "DYLD_INSERT_LIBRARIES"), "/private/var/hk/hkart.dylib:/private/var/hk/hk_mainwatch.dylib:" ML) == 0);
	CHECK(get(&g, "HK_MAINWATCH") && strcmp(get(&g, "HK_MAINWATCH"), "1") == 0);
	CHECK(get(&g, "HK_LOGMIRROR") && get(&g, "OS_ACTIVITY_DT_MODE") && strcmp(get(&g, "OS_ACTIVITY_DT_MODE"), "YES") == 0);
	CHECK(g.n == 5);
	CHECK(strncmp(g.var[0], "DYLD_INSERT_LIBRARIES=", 22) == 0);  /* at its first place */
	/* SpringBoard: FEATUREFLAGS stays first, DYLD second and merged */
	run(rules, "SpringBoard", &g, &mirror, &ndyld, &lost);
	CHECK(ndyld == 2 && mirror == 1 && g.n == 5);
	CHECK(strncmp(g.var[0], "FEATUREFLAGS_DISABLED=", 22) == 0);
	CHECK(strcmp(get(&g, "DYLD_INSERT_LIBRARIES"), "/private/var/hk/hkbattery.dylib:" ML) == 0);
	/* configd: only the mirror's rule, its value untouched */
	run(rules, "configd", &g, &mirror, &ndyld, &lost);
	CHECK(ndyld == 1 && mirror == 1 && g.n == 3);
	CHECK(strcmp(g.var[0], "DYLD_INSERT_LIBRARIES=" ML) == 0);
	/* backboardd: not in the list, exactly as before (3 libraries, no mirror) */
	run(rules, "backboardd", &g, &mirror, &ndyld, &lost);
	CHECK(ndyld == 1 && mirror == 0 && g.n == 3 && get(&g, "HK_LOGMIRROR") == NULL);
	CHECK(strcmp(get(&g, "DYLD_INSERT_LIBRARIES"),
	    "/private/var/hk/hgltrack.dylib:/private/var/hk/hk_container_ready.dylib:/private/var/hk/hk_accel_once.dylib") == 0);
	/* names: prefix and suffix do not match; a name nobody lists gets nothing */
	run(rules, "Preference", &g, &mirror, &ndyld, &lost);
	CHECK(g.n == 0 && mirror == 0);
	run(rules, "tccdx", &g, &mirror, &ndyld, &lost);
	CHECK(g.n == 0);
	run(rules, "WirelessRadioManagerd", &g, &mirror, &ndyld, &lost);
	CHECK(g.n == 3 && mirror == 1);
	/* the same library twice: once */
	run("a:DYLD_INSERT_LIBRARIES=/x.dylib:/y.dylib,a:DYLD_INSERT_LIBRARIES=/y.dylib:/z.dylib", "a", &g, &mirror, &ndyld, &lost);
	CHECK(ndyld == 2 && g.n == 1 && strcmp(g.var[0], "DYLD_INSERT_LIBRARIES=/x.dylib:/y.dylib:/z.dylib") == 0);
	/* does not fit: whole libraries dropped, never cut, NUL ended, under HK_VAR_MAX */
	{
		char big[2048], path[361];

		memset(path, 'p', sizeof(path) - 1);
		path[0] = '/';
		path[sizeof(path) - 1] = 0;
		snprintf(big, sizeof(big), "a:DYLD_INSERT_LIBRARIES=/first.dylib,a:DYLD_INSERT_LIBRARIES=%s,a:DYLD_INSERT_LIBRARIES=/last.dylib", path);
		CHECK(hk_env_check(big) == NULL);
		run(big, "a", &g, &mirror, &ndyld, &lost);
		CHECK(ndyld == 3 && lost == 1 && g.n == 1);
		CHECK(strcmp(g.var[0], "DYLD_INSERT_LIBRARIES=/first.dylib:/last.dylib") == 0);
	}
	/* an emit error stops the walk and comes back */
	{
		char dyld[HK_VAR_MAX];
		int count, m, nd;
		unsigned lo;
		struct got full = { .n = 16 };

		CHECK(hk_env_for_program(rules, "configd", 7, dyld, sizeof(dyld), emit, &full, &count, &m, &nd, &lo) == 7 && count == 0);
	}
}

static void
test_table(void)
{
	static struct hk_obs_table t;
	char name[40];

	memset(&t, 0, sizeof(t));
	hk_obs_note_exec(&t, "lsd", 3, 1);
	hk_obs_note_exec(&t, "lsd", 3, 1);
	hk_obs_note_exec(&t, "configd", 7, 1);
	hk_obs_note_exec(&t, "backboardd", 10, 0);
	CHECK(t.n == 3 && t.slot[0].execs == 2 && t.slot[0].mirror == 1 && t.slot[2].mirror == 0);
	hk_obs_note_exit(&t, "lsd", 3, 6);              /* SIGABRT */
	hk_obs_note_exit(&t, "lsd", 3, 78 << 8);        /* exit(78) */
	hk_obs_note_exit(&t, "nobody", 6, 9);
	CHECK(t.slot[0].exits == 2 && t.slot[0].signalled == 1 && t.slot[0].last_status == (78u << 8));
	CHECK(hk_obs_find(&t, "lsd", 3) == 0 && hk_obs_find(&t, "ls", 2) == -1 && hk_obs_find(&t, "lsdx", 4) == -1);
	CHECK(hk_obs_signalled(11) && !hk_obs_signalled(0) && !hk_obs_signalled(0x7f) && !hk_obs_signalled(1 << 8));
	/* 32 bytes fit (p_name), 33 do not; full table counted */
	memset(name, 'n', 32);
	hk_obs_note_exec(&t, name, 32, 0);
	CHECK(t.n == 4 && strlen(t.slot[3].name) == 32);
	hk_obs_note_exec(&t, name, 33, 0);
	CHECK(t.n == 4 && t.other_execs == 1);
	for (int i = 0; i < 40; i++) {
		snprintf(name, sizeof(name), "p%d", i);
		hk_obs_note_exec(&t, name, strlen(name), 0);
	}
	CHECK(t.n == HK_OBS_SLOTS && t.other_execs == 1 + 40 - (HK_OBS_SLOTS - 4));
}

static void
test_bucket(void)
{
	struct hk_bucket b = { .rate = 1000, .burst = 4000 };
	uint64_t t = 5000000;
	uint32_t got = 0;

	CHECK(hk_bucket_take(&b, t, 4000) == 1);       /* burst */
	CHECK(hk_bucket_take(&b, t, 1) == 0);
	CHECK(hk_bucket_take(&b, t + 500000, 500) == 1);   /* 0.5 s: 500 B */
	CHECK(hk_bucket_take(&b, t + 500000, 1) == 0);
	/* 10 s of 100-byte writes every 10 ms: what passes is rate * 10 s (no burst left), +-1 write */
	for (int i = 1; i <= 1000; i++) {
		got += hk_bucket_take(&b, t + 500000 + (uint64_t)i * 10000, 100) ? 100 : 0;
	}
#if MUT == 1
	got += 5000;
#endif
	CHECK(got >= 9900 && got <= 10100);
	/* idle refills to the burst, never past it */
	CHECK(hk_bucket_take(&b, t + 100000000, 4000) == 1 && hk_bucket_take(&b, t + 100000000, 1) == 0);
	/* tiny writes at a fine grain still refill (no lost fractions) */
	{
		struct hk_bucket s = { .rate = 100, .burst = 100 };
		uint32_t n = 0;

		(void)hk_bucket_take(&s, 1, 100);
		for (uint64_t us = 1; us <= 10000000; us += 1000) {
			n += hk_bucket_take(&s, us, 1);
		}
		CHECK(n >= 990 && n <= 1001);
	}
	/* rate 0: no limit */
	{
		struct hk_bucket z = { .rate = 0, .burst = 0 };
		CHECK(hk_bucket_take(&z, 1, 0xffffffffu) == 1);
	}
	/* time going back does not refill or crash */
	{
		struct hk_bucket r = { .rate = 1000, .burst = 1000 };
		CHECK(hk_bucket_take(&r, 2000000, 1000) == 1 && hk_bucket_take(&r, 1000000, 1) == 0);
	}
}

static void
test_line(void)
{
	char b[64];
	struct hk_line l;
	struct hk_obs_slot s;

	CHECK(hk_obs_is_tagged("HKL x", 5) && !hk_obs_is_tagged("HKL", 3) && !hk_obs_is_tagged("HKOB", 4) && !hk_obs_is_tagged("hkl ", 4));
	hk_line_init(&l, b, sizeof(b));
	hk_line_str(&l, "a ");
	hk_line_u64(&l, 0);
	hk_line_str(&l, " ");
	hk_line_u64(&l, 18446744073709551615ull);
	hk_line_str(&l, " ");
	hk_line_hex(&l, 0x0c03, 4);
	CHECK(strcmp(b, "a 0 18446744073709551615 0x0c03") == 0 && !l.full);
	/* never past cap - 1 */
	hk_line_init(&l, b, 8);
	hk_line_str(&l, "0123456789");
	CHECK(strcmp(b, "0123456") == 0 && l.full && l.len == 7);
	hk_line_init(&l, b, sizeof(b));
	hk_line_printable(&l, "ok\x01\x7f\xff end", 64);
	CHECK(strcmp(b, "ok... end") == 0);
	hk_line_init(&l, b, sizeof(b));
	hk_line_printable(&l, "unterminated-but-bounded", 5);
	CHECK(strcmp(b, "unter") == 0);
	memset(&s, 0, sizeof(s));
	strcpy(s.name, "lsd");
	s.execs = 3;
	s.exits = 2;
	s.last_status = 6;
	s.mirror = 1;
	s.lines = 120;
	s.dropped = 4;
	hk_line_init(&l, b, sizeof(b));
	CHECK(hk_line_slot(&l, &s) == 1 && strcmp(b, " lsd 3/2 s6 l120 d4") == 0);
	s.last_status = 78 << 8;
	s.mirror = 0;
	CHECK(hk_line_slot(&l, &s) == 1 && strcmp(b, " lsd 3/2 s6 l120 d4 lsd 3/2 e78") == 0);
	s.exits = 0;
	hk_line_init(&l, b, sizeof(b));
	CHECK(hk_line_slot(&l, &s) == 1 && strcmp(b, " lsd 3/0 -") == 0);
	/* a slot that does not fit leaves the line as it was */
	hk_line_init(&l, b, 14);
	CHECK(hk_line_slot(&l, &s) == 1);
	CHECK(hk_line_slot(&l, &s) == 0 && strcmp(b, " lsd 3/0 -") == 0 && !l.full);
}

int
main(void)
{
	test_merge();
	test_table();
	test_bucket();
	test_line();
	printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
