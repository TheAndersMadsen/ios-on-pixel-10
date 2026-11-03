/* HOST ONLY: walk perf-r1 (r10) and app2-r1 with the release kernel consumers (varfs_overlay.h, hk_exec_rules.h, pinned
 * copies in ios26-opt-20261102/combined_ui_overlay/inputs/r1, compared with hk-sandbox-token by run_mac.sh) and check
 * exactly the intended changes: [39] hk_env gains a tccd rule only, and two appended records (the TCC dir, the
 * stderr dylib) that varfs writes under the mask. Adapted from ios26-phaseb-r1/perf/tools/perf_consumer.c. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>
#define MASK 0xA0080081u
#define LIB "/private/var/hk/hk_stderr_console.dylib"
#define TCC "/private/var/mobile/Library/TCC"
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
    CHECK(argc == 3);
    struct ov a = load(argv[1]), b = load(argv[2]);
    CHECK(b.count == a.count + 2);
    unsigned long pa = HKOV_HEADER_SIZE, pb = HKOV_HEADER_SIZE; const char *why = NULL; unsigned same = 0, changed = 0;
    for (unsigned i = 0; i < a.count; ++i) {
        unsigned long sa = pa, sb = pb; struct hkov_entry ea, eb;
        CHECK(hkov_next(a.blob, a.total, &pa, &ea, &why) == 1); CHECK(hkov_next(b.blob, b.total, &pb, &eb, &why) == 1);
        if (pa - sa == pb - sb && !memcmp(a.blob + sa, b.blob + sb, pa - sa)) { ++same; continue; }
        CHECK(i == 39 && eb.type == 'c' && !strcmp(eb.path, "hk_env") && ea.type == eb.type && ea.group == eb.group);
        CHECK(eb.data_len > ea.data_len && !memcmp(ea.data, eb.data, ea.data_len) && eb.data[ea.data_len] == ',');
        printf("CHANGED [%u] c group %u hk_env: %lu -> %lu B (one rule appended)\n", i, eb.group, (unsigned long)ea.data_len, (unsigned long)eb.data_len);
        ++changed;
    }
    CHECK(pa == a.total && changed == 1);
    for (unsigned k = 0; k < 2; ++k) {
        struct hkov_entry e; CHECK(hkov_next(b.blob, b.total, &pb, &e, &why) == 1);
        CHECK(MASK & (1u << e.group));
        CHECK(!hkov_overridden(b.blob, b.total, b.count, a.count + k, pb, &e, MASK));
        if (k == 0) CHECK(e.type == 'd' && !strcmp(e.path, TCC) && e.group == 0 && e.mode == 0755 && e.uid == 501 && e.gid == 501 && e.data_len == 0);
        else CHECK(e.type == 'f' && !strcmp(e.path, LIB) && e.group == 29 && e.mode == 0755 && e.uid == 0 && e.gid == 0 && e.data_len > 4096 && !memcmp(e.data, "\xcf\xfa\xed\xfe", 4));
        printf("APPENDED [%u] %c group %u %o %u:%u %s %lu B, written under mask\n", a.count + k, e.type, e.group, e.mode, e.uid, e.gid, e.path, (unsigned long)e.data_len);
    }
    CHECK(pb == b.total);
    CHECK(!strcmp(a.deny, b.deny));
    printf("PASS records: %u identical, %u replaced, 2 appended; hk_deny unchanged: %s\n", same, changed, b.deny);
    const char *names[] = {"tccd", "backboardd", "SpringBoard", "Preferences", "iconservicesagent", "powerd", "Spotlight", "MobilePhone", "launchd", "unmatched_process"};
    for (unsigned k = 0; k < sizeof names / sizeof *names; ++k) {
        char x[64][HK_VAR_MAX], y[64][HK_VAR_MAX]; memset(x, 0, sizeof x); memset(y, 0, sizeof y);
        unsigned n = collect(a.env, names[k], x), m = collect(b.env, names[k], y);
        if (!strcmp(names[k], "tccd")) {
            CHECK(n == 0 && m == 3);
            CHECK(!strcmp(y[0], "DYLD_INSERT_LIBRARIES=" LIB) && !strcmp(y[1], "HK_STDERR_CONSOLE=1") && !strcmp(y[2], "OS_ACTIVITY_DT_MODE=YES"));
        } else { CHECK(m == n); for (unsigned j = 0; j < n; ++j) CHECK(!strcmp(x[j], y[j])); }
        for (unsigned j = 0; j < m; ++j) printf("EXEC %s %s\n", names[k], y[j]);
    }
    printf("PASS: release consumers; hk_env %lu B with NUL (max %d); only tccd's environment changed; %u checks\n",
           strlen(b.env) + 1, HK_RULES_MAX, checks);
    free(a.blob); free(b.blob);
    return 0;
}
