/* HOST ONLY: walk the r7-touch overlay and the r8-settings overlay with the release kernel consumers (varfs_overlay.h,
 * hk_exec_rules.h; the pinned copies in ios26-opt-20261102/combined_ui_overlay/inputs/r1) and check that the only change
 * is the active group-7 disabled.plist record, that it is the record varfs writes under the mask (not overridden), and
 * that every process gets the same exec environment and deny rules as before. Adapted from accel-wait/accel_consumer.c. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>
#define MASK 0xA0080081u
#define DISABLED "/private/var/db/com.apple.xpc.launchd/disabled.plist"
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
    CHECK(b.count == a.count);
    unsigned long pa = HKOV_HEADER_SIZE, pb = HKOV_HEADER_SIZE; const char *why = NULL; unsigned same = 0, changed = 0;
    for (unsigned i = 0; i < a.count; ++i) {
        unsigned long sa = pa, sb = pb; struct hkov_entry ea, eb;
        CHECK(hkov_next(a.blob, a.total, &pa, &ea, &why) == 1); CHECK(hkov_next(b.blob, b.total, &pb, &eb, &why) == 1);
        if (pa - sa == pb - sb && !memcmp(a.blob + sa, b.blob + sb, pa - sa)) { ++same; continue; }
        /* the one change: the group-7 disabled.plist, same metadata, the record varfs writes under MASK */
        CHECK(ea.type == 'f' && eb.type == 'f' && ea.group == 7 && eb.group == 7 && eb.mode == 0644 && eb.uid == 0 && eb.gid == 0);
        CHECK(!strcmp(ea.path, DISABLED) && !strcmp(eb.path, DISABLED));
        CHECK(!hkov_overridden(b.blob, b.total, b.count, i, pb, &eb, MASK));
        CHECK(!has(ea.data, ea.data_len, "<key>com.apple.bluetoothd</key>"));
        CHECK(has(eb.data, eb.data_len, "<key>com.apple.bluetoothd</key>\n\t<true/>"));
        CHECK(eb.data_len == ea.data_len + strlen("\t<key>com.apple.bluetoothd</key>\n\t<true/>\n"));
        printf("CHANGED [%u] %c group %u %s: %lu -> %lu B, written under mask, gains com.apple.bluetoothd\n", i, eb.type,
               eb.group, eb.path, (unsigned long)ea.data_len, (unsigned long)eb.data_len);
        ++changed;
    }
    CHECK(pa == a.total && pb == b.total && changed == 1);
    CHECK(!strcmp(a.env, b.env) && !strcmp(a.deny, b.deny));
    printf("PASS records: %u identical, %u changed; hk_env identical (%lu B with NUL); hk_deny identical: %s\n",
           same, changed, strlen(b.env) + 1, b.deny);
    const char *names[] = {"backboardd", "SpringBoard", "Preferences", "iconservicesagent", "powerd", "bluetoothd", "launchd", "unmatched_process"};
    for (unsigned k = 0; k < sizeof names / sizeof *names; ++k) {
        char x[64][HK_VAR_MAX], y[64][HK_VAR_MAX]; memset(x, 0, sizeof x); memset(y, 0, sizeof y);
        unsigned n = collect(a.env, names[k], x), m = collect(b.env, names[k], y);
        CHECK(m == n); for (unsigned j = 0; j < n; ++j) CHECK(!strcmp(x[j], y[j]));
        for (unsigned j = 0; j < m; ++j) printf("EXEC %s %s\n", names[k], y[j]);
    }
    printf("PASS: release consumers; only the active disabled.plist changed; %u checks\n", checks);
    return 0;
}
