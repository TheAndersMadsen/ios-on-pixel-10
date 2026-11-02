#include "hsampler.h"
#if HK_SAMPLER_NEON
#include "fingerprint.h" /* generated from LOCAL QuartzCore, hashes/offsets only */
#include <dlfcn.h>
#include <dispatch/dispatch.h>
#include <fcntl.h>
#include <mach/mach.h>
#include <mach-o/loader.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern const char *getprogname(void);
enum { HS_OBSERVE = 1, HS_VERIFY = 2, HS_FAST = 3 };
static hs_original original;
static hs_original projective_original;
static int mode;
static _Atomic int mismatch_latch;
static _Atomic uint64_t calls, pixels, eligible, fast_pixels, verified, mismatches;
static _Atomic uint64_t projective_calls, projective_identity;
static _Atomic uint64_t refused[HS_REASON_COUNT], verify_long;
static dispatch_source_t timer;
static void say(const char *fmt, ...) {
    char b[768]; va_list ap; va_start(ap, fmt);
    int n = vsnprintf(b, sizeof b, fmt, ap); va_end(ap);
    if (n <= 0) return;
    int fd = open("/dev/console", O_WRONLY | O_NOCTTY);
    if (fd >= 0) { (void)write(fd, b, (size_t)n < sizeof b ? (size_t)n : sizeof b - 1); close(fd); }
}
#define ADD(v, n) atomic_fetch_add_explicit(&(v), (n), memory_order_relaxed)
#define GET(v) atomic_load_explicit(&(v), memory_order_relaxed)
static void report(void *unused) {
    (void)unused;
    say("HKSAMPLER: mode=%d calls=%llu pixels=%llu eligible=%llu fast=%llu verified=%llu mismatch=%llu latch=%d refuse(transform/layout/span/alias)=%llu/%llu/%llu/%llu verify_long=%llu projective=%llu identity=%llu\n",
        mode, (unsigned long long)GET(calls), (unsigned long long)GET(pixels),
        (unsigned long long)GET(eligible), (unsigned long long)GET(fast_pixels),
        (unsigned long long)GET(verified), (unsigned long long)GET(mismatches), GET(mismatch_latch),
        (unsigned long long)GET(refused[HS_TRANSFORM]), (unsigned long long)GET(refused[HS_LAYOUT]),
        (unsigned long long)GET(refused[HS_SPAN]), (unsigned long long)GET(refused[HS_ALIAS]),
        (unsigned long long)GET(verify_long), (unsigned long long)GET(projective_calls), (unsigned long long)GET(projective_identity));
}
/* Verification always publishes Apple's output, including after a mismatch.
 * Limit is explicit and reported; never pretend skipped long spans were checked. */
__attribute__((noinline)) static void verify(const hs_data *d, unsigned n, uint32_t *out, unsigned arg, hs_original reference) {
    reference(d, n, out, arg);
    if (n > 4096) { ADD(verify_long, 1); return; }
    if (GET(mismatch_latch)) return;
    uint32_t scratch[4096];
    if (!hs_try(d, n, scratch, arg, original)) return;
    ADD(verified, n);
    if (memcmp(out, scratch, (size_t)n * 4)) {
        ADD(mismatches, 1); atomic_store_explicit(&mismatch_latch, 1, memory_order_relaxed);
        say("HKSAMPLER: MISMATCH n=%u x=%d dx=%d y=%d; original output retained, candidate disabled\n", n, d->x, d->dx, d->y);
    }
}
/* Installed in the real format-1, selector-10 sampler table entry. */
static void sample(const hs_data *d, unsigned n, uint32_t *out, unsigned arg, hs_original reference, int projective) {
    uint64_t seen = ADD(calls, 1); ADD(pixels, n);
    if (!n) { reference(d,n,out,arg); return; }
    if (seen < 8 && d && d->image)
        say("HKSAMPLER: sample kind=%s n=%u size=%ux%u stride=%lld x=%d dx=%d y=%d\n",
            projective ? "projective" : "axis", n, d->image->width, d->image->height,
            (long long)d->image->stride, d->x, d->dx, d->y);
    if (projective) {
        ADD(projective_calls, 1);
        if (!hs_projective_axes(d)) { ADD(refused[HS_TRANSFORM], 1); reference(d,n,out,arg); return; }
        ADD(projective_identity, 1);
    }
    hs_plan plan;
    enum hs_reason reason = hs_prepare(d, n, out, &plan);
    if (reason != HS_OK) { ADD(refused[reason], 1); reference(d, n, out, arg); return; }
    ADD(eligible, plan.count);
    if (mode == HS_OBSERVE || GET(mismatch_latch)) { reference(d, n, out, arg); return; }
    if (mode == HS_VERIFY) { verify(d, n, out, arg, reference); return; }
    unsigned rendered = hs_try(d, n, out, arg, original);
    if (rendered) ADD(fast_pixels, rendered); else reference(d, n, out, arg);
}
void hs_backboardd_sampler(const hs_data *d, unsigned n, uint32_t *out, unsigned arg) { sample(d,n,out,arg,original,0); }
void hs_backboardd_projective(const hs_data *d, unsigned n, uint32_t *out, unsigned arg) { sample(d,n,out,arg,projective_original,1); }

static uint64_t fingerprint(const void *p, size_t n) {
    const uint8_t *b = p; uint64_t h = UINT64_C(0xcbf29ce484222325);
    for (size_t i = 0; i < n; ++i) h = (h ^ b[i]) * UINT64_C(0x100000001b3);
    return h;
}
static int known_image(const void *header) {
    const struct mach_header_64 *h = header;
    if (!h || h->magic != MH_MAGIC_64 || h->ncmds > 4096 || h->sizeofcmds > (1u << 20)) return 0;
    const uint8_t *p = (const uint8_t *)(h + 1), *end = p + h->sizeofcmds;
    for (unsigned i = 0; i < h->ncmds && (size_t)(end - p) >= sizeof(struct load_command); ++i) {
        const struct load_command *lc = (const void *)p;
        if (lc->cmdsize < sizeof *lc || lc->cmdsize > (size_t)(end - p)) return 0;
        if (lc->cmd == LC_UUID && lc->cmdsize >= sizeof(struct uuid_command))
            return memcmp(((const struct uuid_command *)lc)->uuid, hs_qc_uuid, 16) == 0;
        p += lc->cmdsize;
    }
    return 0;
}
#ifndef HS_HOOK_TEST
__attribute__((constructor)) static void start(void) {
    if (strcmp(getprogname(), "backboardd")) return;
    const char *v = getenv("HKSAMPLER");
    if (!v) return;
    if (!strcmp(v, "observe")) mode = HS_OBSERVE;
    else if (!strcmp(v, "verify")) mode = HS_VERIFY;
    else if (!strcmp(v, "fast")) mode = HS_FAST;
    else { say("HKSAMPLER: invalid mode, untouched\n"); return; }
    void *entry = dlsym(RTLD_DEFAULT, "CARenderOGLNew");
    void *n = __builtin_ptrauth_strip(entry, 0);
    Dl_info info;
    if (!n || !dladdr(n, &info) || !known_image(info.dli_fbase)) {
        say("HKSAMPLER: QuartzCore UUID refused, untouched\n"); return;
    }
    uintptr_t slide = (uintptr_t)n - HS_NEW_UNSLID;
    uintptr_t *table = (void *)(HS_FORMAT_TABLE_UNSLID + slide);
    for (unsigned i = 0; i < 16; ++i) {
        /* Match the proven hgltrack route: XPACI becomes a NOP in pacstrip,
         * so strip high auth bits arithmetically for this pinned userspace. */
        uintptr_t value = table[i] & UINT64_C(0x0000007fffffffff);
        if (value != hs_expected_functions[i] + slide) {
            say("HKSAMPLER: table[%u] refused, untouched\n", i); return;
        }
    }
    original = (hs_original)(HS_FN_UNSLID + slide);
    projective_original = (hs_original)(HS_PROJECTIVE_FN_UNSLID + slide);
    if (fingerprint((const void *)original, HS_FN_SIZE) != HS_FN_FNV ||
        fingerprint((const void *)projective_original, HS_PROJECTIVE_FN_SIZE) != HS_PROJECTIVE_FN_FNV ||
        !hs_selfcheck(original) || !hs_projective_selfcheck(projective_original, original)) {
        say("HKSAMPLER: code/selfcheck refused, untouched\n"); return;
    }
    uintptr_t *slot = table + HS_SLOT_INDEX;
    uintptr_t pg = (uintptr_t)slot & ~(uintptr_t)0x3fff;
    uintptr_t old[5] = {*slot, table[12], table[13], table[14], table[15]};
    kern_return_t k = vm_protect(mach_task_self(), pg, 0x4000, 0, VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY);
    if (k) { say("HKSAMPLER: vm_protect %d, untouched\n", k); return; }
    __atomic_store_n(slot, (uintptr_t)__builtin_ptrauth_strip((void *)hs_backboardd_sampler, 0), __ATOMIC_RELEASE);
    for (unsigned i=12;i<16;++i)
        __atomic_store_n(table+i, (uintptr_t)__builtin_ptrauth_strip((void *)hs_backboardd_projective, 0), __ATOMIC_RELEASE);
    k = vm_protect(mach_task_self(), pg, 0x4000, 0, VM_PROT_READ);
    if (k) {
        __atomic_store_n(slot, old[0], __ATOMIC_RELEASE);
        for (unsigned i=12;i<16;++i) __atomic_store_n(table+i, old[i-11], __ATOMIC_RELEASE);
        kern_return_t rollback = vm_protect(mach_task_self(), pg, 0x4000, 0, VM_PROT_READ);
        say("HKSAMPLER: reprotect %d; hook rolled back, protect=%d\n", k, rollback); return;
    }
    say("HKSAMPLER: installed 23G90 ARGB8_Host axis+identity-projective mode=%d slot=%#lx slide=%#lx selfcheck=PASS reprotect=0\n",
        mode, (unsigned long)slot, (unsigned long)slide);
    dispatch_queue_t queue = dispatch_queue_create("hackios.sampler.stats", NULL);
    if (queue) {
        timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, queue);
        if (timer) {
            dispatch_source_set_timer(timer, dispatch_time(DISPATCH_TIME_NOW, 10 * NSEC_PER_SEC), 10 * NSEC_PER_SEC, NSEC_PER_SEC);
            dispatch_source_set_event_handler_f(timer, report); dispatch_resume(timer);
        } else say("HKSAMPLER: stats timer unavailable\n");
    } else say("HKSAMPLER: stats queue unavailable\n");
}
#else
/* Host harness exercises the exact wrapper, not an alternate sampler. */
void hs_test_bind(hs_original fn, int value) { original = fn; mode = value; }
void hs_test_bind_projective(hs_original fn) { projective_original = fn; }
void hs_test_report(void) { report(NULL); }
uint64_t hs_test_verified(void) { return GET(verified); }
uint64_t hs_test_mismatches(void) { return GET(mismatches); }
int hs_test_latched(void) { return GET(mismatch_latch); }
void hs_test_reset(void) { atomic_store(&mismatch_latch, 0); }
#endif
#endif
