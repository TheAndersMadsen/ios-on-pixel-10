/* HOST ONLY: walk base and new overlay with the release kernel consumers (varfs_overlay.h, hk_exec_rules.h; the pinned
 * copies in combined_ui_overlay/inputs/r1) and print what each process gets at exec. Adapted from
 * combined_ui_overlay/tests/release_consumers.c; target: backboardd gains the accel library and gate only. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>
#define MASK 0xA0080081u
#define LIB "/private/var/hk/hk_accel_once.dylib"
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
int main(int argc, char **argv) {
    CHECK(argc == 4); const char *mode = argv[3];
    struct ov a = load(argv[1]), b = load(argv[2]);
    CHECK(b.count == a.count + 1);
    unsigned long pa = HKOV_HEADER_SIZE, pb = HKOV_HEADER_SIZE; const char *why = NULL; unsigned same = 0, changed = 0;
    for (unsigned i = 0; i < a.count; ++i) {
        unsigned long sa = pa, sb = pb; struct hkov_entry ea, eb;
        CHECK(hkov_next(a.blob, a.total, &pa, &ea, &why) == 1); CHECK(hkov_next(b.blob, b.total, &pb, &eb, &why) == 1);
        if ((MASK & (1u << ea.group)) && ea.type == 'c' && !strcmp(ea.path, "hk_env")) {
            CHECK(eb.type == 'c' && eb.group == ea.group && eb.mode == ea.mode && eb.uid == ea.uid && eb.gid == ea.gid && !strcmp(eb.path, "hk_env"));
            ++changed;
        } else { CHECK(pa - sa == pb - sb && !memcmp(a.blob + sa, b.blob + sb, pa - sa)); ++same; }
    }
    struct hkov_entry last; CHECK(hkov_next(b.blob, b.total, &pb, &last, &why) == 1);
    CHECK(pb == b.total && last.type == 'f' && last.mode == 0755 && last.uid == 0 && last.gid == 0 && !strcmp(last.path, LIB));
    CHECK(MASK & (1u << last.group));
    CHECK(!hkov_overridden(b.blob, b.total, b.count, b.count - 1, pb, &last, MASK));
    CHECK(!strcmp(a.deny, b.deny));
    printf("PASS records: %u identical, %u hk_env replaced, 1 file appended (%s, group %u, %lu B)\n", same, changed, last.path, last.group, (unsigned long)last.data_len);
    const char *names[] = {"backboardd", "SpringBoard", "Preferences", "iconservicesagent", "powerd", "launchd", "unmatched_process"};
    for (unsigned k = 0; k < sizeof names / sizeof *names; ++k) {
        char x[64][HK_VAR_MAX], y[64][HK_VAR_MAX]; memset(x, 0, sizeof x); memset(y, 0, sizeof y);
        unsigned n = collect(a.env, names[k], x), m = collect(b.env, names[k], y);
        if (!strcmp(names[k], "backboardd")) {
            char want[HK_VAR_MAX], gate[64];
            CHECK(n == 2 && m == 3);
            snprintf(want, sizeof want, "%s:%s", x[0], LIB); snprintf(gate, sizeof gate, "HK_ACCEL_ONCE=%s", mode);
            CHECK(!strcmp(y[0], want) && !strcmp(y[1], x[1]) && !strcmp(y[2], gate));
        } else { CHECK(m == n); for (unsigned j = 0; j < n; ++j) CHECK(!strcmp(x[j], y[j])); }
        for (unsigned j = 0; j < m; ++j) printf("EXEC %s %s\n", names[k], y[j]);
    }
    printf("PASS: release hk_env_next; only backboardd changed; cumulative_with_NUL=%lu; %u checks\n", strlen(b.env) + 1, checks);
    return 0;
}
