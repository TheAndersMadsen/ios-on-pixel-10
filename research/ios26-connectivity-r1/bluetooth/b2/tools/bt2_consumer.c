/* SPDX-License-Identifier: MIT
 * HOST ONLY: walk perf-r1 (r10) and bt2 overlays with the release kernel consumers (varfs_overlay.h, hk_exec_rules.h from
 * cc42295) and check the B2 changes: bluetoothd off the active deny list, Spotlight still on it, bluetoothd gets exactly
 * BT_HCI_TRANSPORT and BT_CHIP, every other program's environment unchanged. Adapted from perf/tools/perf_consumer.c. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>
#define MASK 0xA0080081u
#define CHECK(x) do { ++checks; if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
static unsigned checks;
struct ov { unsigned char *blob; unsigned long total; unsigned count, covers; char env[HK_RULES_MAX], deny[HK_RULES_MAX]; };
static unsigned char *rd(const char *p, unsigned long *n) {
    FILE *f = fopen(p, "rb"); CHECK(f); CHECK(!fseek(f, 0, SEEK_END)); long l = ftell(f); CHECK(l > 0 && l < HKOV_TOTAL_MAX);
    rewind(f); unsigned char *b = calloc((size_t)l + 1, 1); CHECK(b && fread(b, 1, (size_t)l, f) == (size_t)l); fclose(f);
    *n = (unsigned long)l; return b;
}
static struct ov load(const char *p) {
    struct ov o; memset(&o, 0, sizeof o); unsigned long n; unsigned long long h; const char *why = NULL; unsigned envs = 0;
    o.blob = rd(p, &n);
    CHECK(!hkov_check(o.blob, n, &o.total, &o.count, &h) && o.total == n);
    CHECK(!(MASK & ~hkov_groups(o.blob, o.total, o.count)));
    CHECK(!hkov_cover_check(o.blob, o.total, o.count, MASK, &o.covers) && o.covers == 1);
    unsigned long at = HKOV_HEADER_SIZE;
    for (unsigned i = 0; i < o.count; ++i) {
        struct hkov_entry e; CHECK(hkov_next(o.blob, o.total, &at, &e, &why) == 1);
        if (!(MASK & (1u << e.group)) || e.type != 'c') continue;
        if (!strcmp(e.path, "hk_env")) { ++envs; CHECK(!hk_rules_append(o.env, sizeof o.env, (const char *)e.data, e.data_len)); CHECK(!hk_env_check(o.env)); }
        else { CHECK(!strcmp(e.path, "hk_deny")); CHECK(!hk_rules_append(o.deny, sizeof o.deny, (const char *)e.data, e.data_len)); CHECK(!hk_deny_check(o.deny)); }
    }
    CHECK(envs == 1 && at == o.total);
    return o;
}
static unsigned collect(const char *rules, const char *name, char v[64][HK_VAR_MAX]) {
    const char *c = rules, *var; unsigned long len; int in = 0; unsigned n = 0;
    while (hk_env_next(&c, &in, name, strlen(name), &var, &len)) { CHECK(n < 64 && len < HK_VAR_MAX); memcpy(v[n], var, len); v[n][len] = 0; ++n; }
    return n;
}
static __attribute__((unused)) int has(const unsigned char *d, unsigned long n, const char *s) {
    unsigned long k = strlen(s);
    for (unsigned long i = 0; i + k <= n; ++i) if (!memcmp(d + i, s, k)) return 1;
    return 0;
}

static void same_env(const char *a, const char *b, const char *prog) {
    char va[64][HK_VAR_MAX], vb[64][HK_VAR_MAX]; unsigned na = collect(a, prog, va), nb = collect(b, prog, vb);
    CHECK(na == nb); for (unsigned i = 0; i < na; ++i) CHECK(!strcmp(va[i], vb[i]));
}
int main(int argc, char **argv) {
    CHECK(argc == 3);
    struct ov a = load(argv[1]), b = load(argv[2]);
    CHECK(hk_list_has(a.deny, "bluetoothd", 10) && hk_list_has(a.deny, "Spotlight", 9));
    CHECK(!hk_list_has(b.deny, "bluetoothd", 10) && hk_list_has(b.deny, "Spotlight", 9));
    CHECK(!hk_list_has(b.deny, "bluetooth", 9) && !hk_list_has(b.deny, "BlueTool", 8) && !hk_list_has(b.deny, "audiomxd", 8));
    char v[64][HK_VAR_MAX];
    CHECK(collect(a.env, "bluetoothd", v) == 0);
    unsigned n = collect(b.env, "bluetoothd", v);
    CHECK(n == 2 && !strcmp(v[0], "BT_HCI_TRANSPORT=H4:POSIX") && !strcmp(v[1], "BT_CHIP=ACI~BT"));
    const char *others[] = { "backboardd", "Preferences", "iconservicesagent", "powerd", "SpringBoard", "BlueTool", "audiomxd", "bluetoothd2", "launchd" };
    for (unsigned i = 0; i < sizeof others / sizeof *others; ++i) same_env(a.env, b.env, others[i]);
    CHECK(a.count == b.count && a.covers == b.covers);
    free(a.blob); free(b.blob);
    printf("PASS: %u checks; bluetoothd allowed, env %s;%s\n", checks, v[0], v[1]);
    return 0;
}
