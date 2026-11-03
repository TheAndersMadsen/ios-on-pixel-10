/* Copyright (c) 2026 hackios contributors. MIT.
 *
 * hk_mainwatch: a read-only main-thread watch for one app (Preferences), injected through the overlay's hk_env row.
 * It answers one question about the frozen Settings app: is the main thread blocked (and where), is the process
 * suspended, or is the main thread free while touches do or do not arrive?
 *
 *   heartbeat (every 10 s, at most 60):  HKMAIN: Preferences[pid] t=S pings=N wait=MS state=S ev touch=N press=N other=N stalls=N
 *   stall (main queue late >= 3 s; every 5 s while it lasts, at most 20 samples, 2 lines each):
 *       HKMAIN: stall MS ms pc PC lr LR sp SP dsc_slide SL main_slide MS
 *       HKMAIN: frames F0 F1 ... (fp chain, at most 12, PAC stripped, only inside the main thread's stack)
 *   gap (the watcher itself did not run for >= 3 s, i.e. the task was suspended):  HKMAIN: gap MS ms
 *
 * "wait" is how long the newest main-queue no-op has waited (0 when the main queue is draining). "state" is
 * -[UIApplication applicationState] read on the main thread (0 active, 1 inactive, 2 background, -1 unknown).
 * "ev" counts -[UIApplication sendEvent:] calls by UIEvent type (0 touches, 3 presses, other) through one
 * method_setImplementation on the class the app object uses; the original IMP is always called.
 *
 * Gates: HK_MAINWATCH=1 in the environment and getprogname() == "Preferences" (HK_MAINWATCH_TEST builds accept any
 * process and write to stderr). The main thread is suspended only for thread_get_state and the frame walk (no
 * allocation, no locks, no output while it is suspended). Nothing is written but /dev/console lines.
 */
#include <dispatch/dispatch.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <mach/mach.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#if __has_include(<ptrauth.h>)
#include <ptrauth.h>
#endif
#ifndef ptrauth_strip
#define ptrauth_strip(value, key) (value)
#endif

#define HKM_PERIOD_MS 1000ull
#define HKM_STALL_MS 3000ull
#define HKM_STALL_EVERY_MS 5000ull
#define HKM_BEAT_EVERY_MS 10000ull
#define HKM_GAP_MS 3000ull
#define HKM_MAX_STALLS 20u
#define HKM_MAX_BEATS 60u
#define HKM_MAX_FRAMES 12u
/* User addresses fit in 40 bits; the mask also clears PAC bits if the build ever keeps signed pointers (pacstrip
 * removes XPAC* along with the other PAC instructions, so ptrauth_strip alone is not enough). */
#define HKM_VA(x) ((uint64_t)(x) & 0x000000ffffffffffull)

static mach_port_t main_port = MACH_PORT_NULL;
static uintptr_t stack_lo, stack_hi;          /* main thread stack [lo, hi) */
static _Atomic uint64_t posted_at, ran_at;     /* ms; posted_at != 0 while a no-op is queued */
static _Atomic unsigned pings, stalls, ev_touch, ev_press, ev_other;
static _Atomic long app_state = -1;
static _Atomic int hooked;
typedef void (*SendIMP)(id, SEL, id);
static SendIMP original_send;

static uint64_t now_ms(void) { return clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) / 1000000ull; }

static void say(const char *format, ...) {
    char line[240];
    va_list args; va_start(args, format);
    int count = vsnprintf(line, sizeof line, format, args);
    va_end(args);
    if (count <= 0) return;
    if (count >= (int)sizeof line) count = (int)sizeof line - 1;
#ifdef HK_MAINWATCH_TEST
    (void)write(2, line, (size_t)count);
#else
    int fd = open("/dev/console", O_WRONLY | O_NOCTTY);
    if (fd >= 0) { (void)write(fd, line, (size_t)count); close(fd); }
#endif
}

static void hk_send_event(id self, SEL cmd, id event) {
    long type = event ? ((long (*)(id, SEL))objc_msgSend)(event, sel_registerName("type")) : -1;
    if (type == 0) atomic_fetch_add(&ev_touch, 1);
    else if (type == 3) atomic_fetch_add(&ev_press, 1);
    else atomic_fetch_add(&ev_other, 1);
    original_send(self, cmd, event);
}

/* Main thread only. */
static void hook_app(void) {
    Class base = objc_getClass("UIApplication");
    if (!base) return;
    id app = ((id (*)(id, SEL))objc_msgSend)((id)base, sel_registerName("sharedApplication"));
    if (!app) return;
    atomic_store(&app_state, ((long (*)(id, SEL))objc_msgSend)(app, sel_registerName("applicationState")));
    if (atomic_load(&hooked)) return;
    atomic_store(&hooked, 1);
    Class cls = object_getClass(app);
    Method method = class_getInstanceMethod(cls, sel_registerName("sendEvent:"));
    char ret[4] = {0}, arg[4] = {0};
    if (method) { method_getReturnType(method, ret, sizeof ret); method_getArgumentType(method, 2, arg, sizeof arg); }
    if (!method || ret[0] != 'v' || arg[0] != '@') { say("HKMAIN: sendEvent: not hooked (%s)\n", class_getName(cls)); return; }
    int inherited = method == class_getInstanceMethod(base, sel_registerName("sendEvent:"));
    original_send = (SendIMP)method_getImplementation(method);
    method_setImplementation(method, (IMP)hk_send_event);
    say("HKMAIN: sendEvent: counted for %s (%s)\n", class_getName(cls), inherited ? "UIApplication's" : "own override");
}

static void ping(void *unused) {
    (void)unused;
    atomic_fetch_add(&pings, 1);
    atomic_store(&ran_at, now_ms());
    atomic_store(&posted_at, 0);
    hook_app();
}

static uint64_t cache_slide(void) {
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const char *name = _dyld_get_image_name(i);
        if (name && !strcmp(name, "/usr/lib/libobjc.A.dylib")) return (uint64_t)_dyld_get_image_vmaddr_slide(i);
    }
    return 0;
}

static void sample(uint64_t late) {
    uint64_t frames[HKM_MAX_FRAMES]; unsigned n = 0;
    uint64_t pc = 0, lr = 0, sp = 0, fp = 0;
    arm_thread_state64_t st; mach_msg_type_number_t count = ARM_THREAD_STATE64_COUNT;
    if (thread_suspend(main_port) != KERN_SUCCESS) { say("HKMAIN: stall %llu ms, suspend failed\n", late); return; }
    kern_return_t kr = thread_get_state(main_port, ARM_THREAD_STATE64, (thread_state_t)&st, &count);
    if (kr == KERN_SUCCESS) {
#if __DARWIN_OPAQUE_ARM_THREAD_STATE64
        pc = HKM_VA(ptrauth_strip(st.__opaque_pc, ptrauth_key_asia));
        lr = HKM_VA(ptrauth_strip(st.__opaque_lr, ptrauth_key_asia));
        sp = HKM_VA(ptrauth_strip(st.__opaque_sp, ptrauth_key_asda));
        fp = HKM_VA(ptrauth_strip(st.__opaque_fp, ptrauth_key_asda));
#else
        pc = HKM_VA(st.__pc); lr = HKM_VA(st.__lr); sp = HKM_VA(st.__sp); fp = HKM_VA(st.__fp);
#endif
        /* fp chain: [fp] = caller fp, [fp+8] = return address. Read only inside the main stack, strictly upwards. */
        while (n < HKM_MAX_FRAMES && fp >= stack_lo && fp + 16 <= stack_hi && !(fp & 7)) {
            const uint64_t *pair = (const uint64_t *)(uintptr_t)fp;
            uint64_t next = HKM_VA(pair[0]), ret = pair[1];
            frames[n++] = HKM_VA(ptrauth_strip((void *)(uintptr_t)ret, ptrauth_key_asib));
            if (next <= fp) break;
            fp = next;
        }
    }
    thread_resume(main_port);
    if (kr != KERN_SUCCESS) { say("HKMAIN: stall %llu ms, get_state %d\n", late, kr); return; }
    say("HKMAIN: stall %llu ms pc 0x%llx lr 0x%llx sp 0x%llx dsc_slide 0x%llx main_slide 0x%llx\n", late, pc, lr, sp,
        cache_slide(), (uint64_t)_dyld_get_image_vmaddr_slide(0));
    char line[200]; int at = 0;
    for (unsigned i = 0; i < n && at < (int)sizeof line - 20; ++i) at += snprintf(line + at, sizeof line - (size_t)at, " 0x%llx", frames[i]);
    line[at < (int)sizeof line ? at : (int)sizeof line - 1] = 0;
    say("HKMAIN: frames%s\n", n ? line : " none");
}

static void *watch(void *unused) {
    (void)unused;
    uint64_t start = now_ms(), last = start, last_beat = start, last_stall = 0;
    unsigned beats = 0;
    for (;;) {
        struct timespec period = { (time_t)(HKM_PERIOD_MS / 1000ull), (long)(HKM_PERIOD_MS % 1000ull) * 1000000L };
        while (nanosleep(&period, &period) && period.tv_sec >= 0) {}  /* EINTR: sleep the rest */
        uint64_t t = now_ms();
        if (t - last >= HKM_PERIOD_MS + HKM_GAP_MS) say("HKMAIN: gap %llu ms\n", t - last - HKM_PERIOD_MS);
        last = t;
        uint64_t queued = atomic_load(&posted_at);
        if (!queued) {
            atomic_store(&posted_at, t);
            dispatch_async_f(dispatch_get_main_queue(), NULL, ping);
        } else if (t - queued >= HKM_STALL_MS && atomic_load(&stalls) < HKM_MAX_STALLS &&
                   (!last_stall || t - last_stall >= HKM_STALL_EVERY_MS)) {
            atomic_fetch_add(&stalls, 1);
            last_stall = t;
            sample(t - queued);
        }
        if (t - last_beat >= HKM_BEAT_EVERY_MS && beats < HKM_MAX_BEATS) {
            ++beats; last_beat = t;
            queued = atomic_load(&posted_at);
            say("HKMAIN: %s[%d] t=%llu pings=%u wait=%llu state=%ld ev touch=%u press=%u other=%u stalls=%u\n",
                getprogname(), getpid(), (t - start) / 1000, atomic_load(&pings), queued ? t - queued : 0ull,
                atomic_load(&app_state), atomic_load(&ev_touch), atomic_load(&ev_press), atomic_load(&ev_other),
                atomic_load(&stalls));
        }
    }
    return NULL;
}

__attribute__((constructor)) static void hk_mainwatch_install(void) {
    const char *gate = getenv("HK_MAINWATCH");
    const char *process = getprogname();
    if (!gate || strcmp(gate, "1") || !process) return;
#ifndef HK_MAINWATCH_TEST
    if (strcmp(process, "Preferences")) return;
#endif
    if (!pthread_main_np()) { say("HKMAIN: not on the main thread, off\n"); return; }
    pthread_t self = pthread_self();
    stack_hi = (uintptr_t)pthread_get_stackaddr_np(self);
    stack_lo = stack_hi - pthread_get_stacksize_np(self);
    main_port = mach_thread_self();  /* keeps a send right for the process lifetime */
    pthread_attr_t attr; pthread_t thread;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    int rc = pthread_create(&thread, &attr, watch, NULL);
    pthread_attr_destroy(&attr);
    say(rc ? "HKMAIN: %s[%d] watcher failed\n" : "HKMAIN: %s[%d] watching the main thread\n", process, getpid());
}
