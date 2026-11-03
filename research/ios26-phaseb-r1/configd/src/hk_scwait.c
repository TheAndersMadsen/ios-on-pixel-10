/* Copyright (c) 2026 hackios contributors. MIT.
 *
 * hk_scwait: QEMU probe for one question: does configd's InterfaceNamer answer SystemConfiguration's
 * __waitForInterfaces, the wait that holds Settings' main thread in a7-ios-system-r10-perf? Injected through the
 * overlay's hk_env row into one daemon (powerd in qemu-cfg1 overlays). Read-only: it never writes the store.
 *
 *   HKSC: powerd[pid] watching Plugin:InterfaceNamer
 *   HKSC: t=S keys=K1,K2,...        (each time the set of *...* keys in Plugin:InterfaceNamer changes; "none" = no value)
 *   HKSC: SCNetworkInterfaceCopyAll returned after S s, N interfaces    (the call Settings makes, on its own thread)
 *   HKSC: t=S still waiting         (every 60 s while the call has not returned, for 15 min)
 *
 * Gates: HK_SCWAIT=1 in the environment (HK_SCWAIT_TEST builds write to stderr). /dev/console lines only.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* Exported by SystemConfiguration on iOS too (23G90 cache: _SCDynamicStoreCreate, _SCDynamicStoreCopyValue); the iOS SDK
 * headers mark them unavailable, so they are declared here. kSCDynamicStoreDomainPlugin is "Plugin:". */
typedef const struct __SCDynamicStore *SCDynamicStoreRef;
extern SCDynamicStoreRef SCDynamicStoreCreate(CFAllocatorRef, CFStringRef, void *, void *);
extern CFPropertyListRef SCDynamicStoreCopyValue(SCDynamicStoreRef, CFStringRef);
extern int SCError(void);
extern const char *SCErrorString(int);
extern CFArrayRef SCNetworkInterfaceCopyAll(void);

static uint64_t t0;
static _Atomic int returned;

static uint64_t now_ms(void) { return clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) / 1000000ull; }

static void say(const char *format, ...) {
    char line[240];
    va_list args; va_start(args, format);
    int count = vsnprintf(line, sizeof line, format, args);
    va_end(args);
    if (count <= 0) return;
    if (count >= (int)sizeof line) count = (int)sizeof line - 1;
#ifdef HK_SCWAIT_TEST
    (void)write(2, line, (size_t)count);
#else
    int fd = open("/dev/console", O_WRONLY | O_NOCTTY);
    if (fd >= 0) { (void)write(fd, line, (size_t)count); close(fd); }
#endif
}

static double secs(void) { return (double)(now_ms() - t0) / 1000.0; }

/* "*QUIET*,*COMPLETE*" etc.: the keys of the InterfaceNamer value that start with '*', in a fixed order. */
static void keys_of(CFDictionaryRef d, char *out, size_t n) {
    static const char *const known[] = { "*STACK*", "*QUIET*", "*QUIET&NAMED*", "*COMPLETE*", "*TIMEOUT*", "*TIMEOUT&NAMED*" };
    out[0] = 0;
    if (d == NULL || CFGetTypeID(d) != CFDictionaryGetTypeID()) { strlcpy(out, d == NULL ? "none" : "not-a-dict", n); return; }
    for (size_t i = 0; i < sizeof known / sizeof known[0]; i++) {
        CFStringRef k = CFStringCreateWithCString(NULL, known[i], kCFStringEncodingASCII);
        if (k != NULL && CFDictionaryContainsKey(d, k)) {
            if (out[0]) strlcat(out, ",", n);
            strlcat(out, known[i], n);
        }
        if (k != NULL) CFRelease(k);
    }
    if (!out[0]) strlcpy(out, "no-*-keys", n);
}

static void *copy_all(void *arg) {
    (void)arg;
    CFArrayRef all = SCNetworkInterfaceCopyAll();
    long n = all ? (long)CFArrayGetCount(all) : -1;
    atomic_store(&returned, 1);
    say("HKSC: SCNetworkInterfaceCopyAll returned after %.1f s, %ld interfaces\n", secs(), n);
    if (all) CFRelease(all);
    return NULL;
}

static void *watch(void *arg) {
    (void)arg;
    char last[160] = "", cur[160];
    SCDynamicStoreRef store = SCDynamicStoreCreate(NULL, CFSTR("hk_scwait"), NULL, NULL);
    CFStringRef key = CFSTR("Plugin:InterfaceNamer");
    if (store == NULL || key == NULL) { say("HKSC: no dynamic store (%s)\n", SCErrorString(SCError())); return NULL; }
    for (unsigned i = 0; i < 900 * 2; i++) {          /* every 0.5 s for 15 min */
        CFPropertyListRef v = SCDynamicStoreCopyValue(store, key);
        keys_of((CFDictionaryRef)v, cur, sizeof cur);
        if (v) CFRelease(v);
        if (strcmp(cur, last) != 0) { say("HKSC: t=%.1f keys=%s\n", secs(), cur); strlcpy(last, cur, sizeof last); }
        if (i % 120 == 119 && !atomic_load(&returned)) say("HKSC: t=%.1f still waiting\n", secs());
        if (atomic_load(&returned) && strstr(last, "*COMPLETE*") != NULL) break;
        usleep(500000);
    }
    CFRelease(store);
    return NULL;
}

__attribute__((constructor)) static void hk_scwait_install(void) {
    const char *gate = getenv("HK_SCWAIT");
    pthread_t a, b;
    if (gate == NULL || strcmp(gate, "1") != 0) return;
    t0 = now_ms();
    say("HKSC: %s[%d] watching Plugin:InterfaceNamer\n", getprogname(), getpid());
    if (pthread_create(&a, NULL, watch, NULL) == 0) pthread_detach(a);
    if (pthread_create(&b, NULL, copy_all, NULL) == 0) pthread_detach(b);
}
