/* HOST ONLY: walk settings-btdisabled-r1 (r8) and perf-r1 (r10) with the release kernel consumers (varfs_overlay.h,
 * hk_exec_rules.h; the pinned copies in ios26-opt-20261102/combined_ui_overlay/inputs/r1) and check exactly the four
 * intended changes: [14] disabled.plist loses com.apple.bluetoothd, [39] hk_env gains the watch for Preferences only,
 * [42] hk_deny gains Spotlight, and two appended files (hk_mainwatch.dylib, com.apple.Accessibility.plist) that varfs
 * writes under the mask (not overridden). Adapted from settings/tools/settings_consumer.c. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>
#define MASK 0xA0080081u
#define DISABLED "/private/var/db/com.apple.xpc.launchd/disabled.plist"
#define LIB "/private/var/hk/hk_mainwatch.dylib"
#define AXP "/private/var/mobile/Library/Preferences/com.apple.Accessibility.plist"
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
static int has(const unsigned char *d, unsigned long n, const char *s) {
    unsigned long k = strlen(s);
    for (unsigned long i = 0; i + k <= n; ++i) if (!memcmp(d + i, s, k)) return 1;
    return 0;
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
        CHECK(ea.type == eb.type && ea.group == eb.group && ea.mode == eb.mode && ea.uid == eb.uid && ea.gid == eb.gid && !strcmp(ea.path, eb.path));
        CHECK(MASK & (1u << eb.group));
        CHECK(!hkov_overridden(b.blob, b.total, b.count, i, pb, &eb, MASK));
        if (i == 14) {
            CHECK(eb.type == 'f' && eb.group == 7 && !strcmp(eb.path, DISABLED));
            CHECK(has(ea.data, ea.data_len, "<key>com.apple.bluetoothd</key>") && !has(eb.data, eb.data_len, "<key>com.apple.bluetoothd</key>"));
            CHECK(ea.data_len == eb.data_len + strlen("\t<key>com.apple.bluetoothd</key>\n\t<true/>\n"));
        } else if (i == 39) {
            CHECK(eb.type == 'c' && !strcmp(eb.path, "hk_env"));
        } else if (i == 42) {
            CHECK(eb.type == 'c' && !strcmp(eb.path, "hk_deny"));
            CHECK(eb.data_len == strlen("bluetoothd,Spotlight") && !memcmp(eb.data, "bluetoothd,Spotlight", eb.data_len));
        } else CHECK(0);
        printf("CHANGED [%u] %c group %u %s: %lu -> %lu B, written under mask\n", i, eb.type, eb.group, eb.path,
               (unsigned long)ea.data_len, (unsigned long)eb.data_len);
        ++changed;
    }
    CHECK(pa == a.total && changed == 3);
    for (unsigned k = 0; k < 2; ++k) {
        unsigned long sb = pb; struct hkov_entry e; CHECK(hkov_next(b.blob, b.total, &pb, &e, &why) == 1); (void)sb;
        CHECK(e.type == 'f' && (MASK & (1u << e.group)));
        CHECK(!hkov_overridden(b.blob, b.total, b.count, a.count + k, pb, &e, MASK));
        if (k == 0) CHECK(!strcmp(e.path, LIB) && e.group == 29 && e.mode == 0755 && e.uid == 0 && e.gid == 0 && e.data_len > 4096 && !memcmp(e.data, "\xcf\xfa\xed\xfe", 4));
        else CHECK(!strcmp(e.path, AXP) && e.group == 0 && e.mode == 0600 && e.uid == 501 && e.gid == 501 && !memcmp(e.data, "bplist00", 8) &&
                   has(e.data, e.data_len, "EnhancedBackgroundContrastEnabled") && has(e.data, e.data_len, "ReduceMotionEnabled"));
        printf("APPENDED [%u] f group %u %o %u:%u %s %lu B, written under mask\n", a.count + k, e.group, e.mode, e.uid, e.gid, e.path, (unsigned long)e.data_len);
    }
    CHECK(pb == b.total);
    /* exec rules as the kernel reads them */
    CHECK(hk_list_has(b.deny, "Spotlight", 9) && hk_list_has(b.deny, "bluetoothd", 10));
    CHECK(!hk_list_has(b.deny, "SpotlightIndex", 14) && !hk_list_has(b.deny, "Spotligh", 8) && !hk_list_has(b.deny, "Preferences", 11));
    CHECK(!hk_list_has(a.deny, "Spotlight", 9));
    printf("PASS records: %u identical, %u replaced, 2 appended; hk_deny: %s -> %s\n", same, changed, a.deny, b.deny);
    const char *names[] = {"backboardd", "SpringBoard", "Preferences", "iconservicesagent", "powerd", "Spotlight", "audiomxd", "launchd", "unmatched_process"};
    for (unsigned k = 0; k < sizeof names / sizeof *names; ++k) {
        char x[64][HK_VAR_MAX], y[64][HK_VAR_MAX]; memset(x, 0, sizeof x); memset(y, 0, sizeof y);
        unsigned n = collect(a.env, names[k], x), m = collect(b.env, names[k], y);
        if (!strcmp(names[k], "Preferences")) {
            char want[HK_VAR_MAX];
            CHECK(n == 2 && m == 3);
            snprintf(want, sizeof want, "%s:%s", x[0], LIB);
            CHECK(!strcmp(y[0], want) && !strcmp(y[1], x[1]) && !strcmp(y[2], "HK_MAINWATCH=1"));
        } else { CHECK(m == n); for (unsigned j = 0; j < n; ++j) CHECK(!strcmp(x[j], y[j])); }
        for (unsigned j = 0; j < m; ++j) printf("EXEC %s %s\n", names[k], y[j]);
    }
    printf("PASS: release consumers; hk_env %lu B with NUL (max %d); only Preferences' environment changed; %u checks\n",
           strlen(b.env) + 1, HK_RULES_MAX, checks);
    free(a.blob); free(b.blob);
    return 0;
}
