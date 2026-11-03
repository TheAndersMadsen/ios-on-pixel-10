/* Copyright (c) 2026 hackios contributors. MIT.
 *
 * hk_flatmat: flat materials for SpringBoard while CoreAnimation composites on the CPU (no Metal device).
 *
 * Why (cc/FIX.md): every Control Center module tile and the CC background are MaterialKit MTMaterialView's, whose
 * layer is CoreMaterial's MTMaterialLayer, a CABackdropLayer subclass. The tile recipe ("modules") is only a colour
 * matrix applied to the captured backdrop; it has no tint of its own. With the backdrop not rendered by the CPU path,
 * the tiles come out black/transparent. Reduce Transparency does not help: CoreMaterial then only "replaces blur with
 * average colour", which is still a backdrop filter. The glyphs that vanish are the ones styled with backdrop-aware
 * vibrancy (moduleFill.visualstyleset: vibrantColorMatrix, inputBackdropAware).
 *
 * What it does (SpringBoard only, gate HK_FLATMAT=1):
 *   1. After -[MTMaterialLayer layoutSublayers] and -_configureIfNecessaryWithSettingsInterpolator:, the material
 *      layer's backdrop is switched off (CABackdropLayer setEnabled:NO), each of its filters is switched off
 *      (CAFilter setEnabled:NO; the filters stay, so MaterialKit's "filters.<name>.<key>" key paths stay valid), and
 *      it gets a plain backgroundColor picked from its recipe name. Capture-only layers get no colour.
 *   2. -[CALayer setFilters:] / -setCompositingFilter: pass every value through unchanged, but a CAFilter whose type
 *      starts with "vibrant" is switched off first (the glyph then draws with its tint colour).
 * Every original IMP always runs first. Nothing is written except /dev/console lines:
 *   HKFLAT: SpringBoard[pid] hooks layout=1 configure=1 filters=1 compositing=1
 *   HKFLAT: flat N recipe=NAME capture=0 filters=K       (first 32 layers)
 *   HKFLAT: t=S flattened=N vibrant_off=N                 (every 30 s while it changes, at most 40 lines)
 * HK_FLATMAT_TEST builds accept any process and write to stderr.
 */
#include <dispatch/dispatch.h>
#include <fcntl.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef double hk_float; /* CGFloat on arm64 */
typedef void (*VoidIMP)(id, SEL);
typedef void (*ObjIMP)(id, SEL, id);

static VoidIMP orig_layout;
static ObjIMP orig_configure, orig_set_filters, orig_set_compositing;
static _Atomic unsigned flattened, vibrant_off, logged;
static _Thread_local int busy;
static SEL s_enabled_set, s_filters, s_count, s_at, s_type, s_utf8, s_recipe, s_capture, s_bg, s_set_bg, s_responds,
    s_iskind, s_enabled_get;
static Class c_filter, c_array;
static uint64_t start_ms;

static uint64_t now_ms(void) { return clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW) / 1000000ull; }

static void say(const char *format, ...) {
    char line[240];
    va_list args; va_start(args, format);
    int count = vsnprintf(line, sizeof line, format, args);
    va_end(args);
    if (count <= 0) return;
    if (count >= (int)sizeof line) count = (int)sizeof line - 1;
#ifdef HK_FLATMAT_TEST
    (void)write(2, line, (size_t)count);
#else
    int fd = open("/dev/console", O_WRONLY | O_NOCTTY);
    if (fd >= 0) { (void)write(fd, line, (size_t)count); close(fd); }
#endif
}

#define MSG(ret, ...) ((ret (*)(id, SEL, ##__VA_ARGS__))objc_msgSend)
static int responds(id o, SEL s) { return o && MSG(signed char, SEL)(o, s_responds, s); }
static int is_filter(id o) { return o && c_filter && MSG(signed char, Class)(o, s_iskind, c_filter); }
static int is_array(id o) { return o && c_array && MSG(signed char, Class)(o, s_iskind, c_array); }

/* Only ever switch off what is on: a setter that changes nothing still notifies MTMaterialLayer, which would ask for
 * another configure/layout pass, and that pass would land here again. */
static int enabled(id o) {
    if (responds(o, s_enabled_get)) return MSG(signed char)(o, s_enabled_get) != 0;
    SEL plain = sel_registerName("enabled");
    return responds(o, plain) && MSG(signed char)(o, plain) != 0;
}

static const char *cstring(id string) {
    return string && responds(string, s_utf8) ? MSG(const char *)(string, s_utf8) : NULL;
}

/* A CAFilter whose type starts with "vibrant" is switched off; returns 1 if it was. */
static int quiet_vibrant(id filter) {
    if (!is_filter(filter)) return 0;
    const char *type = cstring(MSG(id)(filter, s_type));
    if (!type || strncmp(type, "vibrant", 7) != 0) return 0;
    if (!enabled(filter)) return 0;
    MSG(void, signed char)(filter, s_enabled_set, 0);
    atomic_fetch_add(&vibrant_off, 1);
    return 1;
}

/* Colours: CGColorRef from +[UIColor colorWithWhite:alpha:], kept alive by retaining the UIColor. */
#ifdef HK_FLATMAT_TEST
extern void *CGColorCreateGenericGray(hk_float gray, hk_float alpha); /* macOS host only: no UIKit/AppKit there */
static void *color(hk_float white, hk_float alpha) { return CGColorCreateGenericGray(white, alpha); }
#else
static void *color(hk_float white, hk_float alpha) {
    Class ui = objc_getClass("UIColor");
    if (!ui) return NULL;
    id c = MSG(id, hk_float, hk_float)((id)ui, sel_registerName("colorWithWhite:alpha:"), white, alpha);
    if (!c) return NULL;
    MSG(id)(c, sel_registerName("retain"));
    return MSG(void *)(c, sel_registerName("CGColor"));
}
#endif

static void *pick(const char *recipe) {
    static void *bg, *module, *dock, *light, *dark, *other;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        bg = color(0.0, 0.55);     /* CC / folder backgrounds: dim what is behind */
        module = color(0.22, 0.92); /* CC module tiles: the Reduce Transparency look */
        dock = color(0.25, 0.60);
        light = color(0.94, 0.90);
        dark = color(0.16, 0.90);
        other = color(0.50, 0.50);
    });
    if (!recipe) return other;
    if (strstr(recipe, "ackground")) return bg;
    if (!strncmp(recipe, "modules", 7)) return module;
    if (!strncmp(recipe, "dock", 4)) return dock;
    if (strstr(recipe, "Dark")) return dark;
    if (strstr(recipe, "latters") || !strncmp(recipe, "platform", 8)) return light;
    return other;
}

static void flatten(id layer) {
    if (busy || !layer) return;
    busy = 1;
    if (enabled(layer)) MSG(void, signed char)(layer, s_enabled_set, 0);
    unsigned filters = 0;
    id list = responds(layer, s_filters) ? MSG(id)(layer, s_filters) : nil;
    if (is_array(list)) {
        unsigned long n = MSG(unsigned long)(list, s_count);
        for (unsigned long i = 0; i < n && i < 64; i++) {
            id f = MSG(id, unsigned long)(list, s_at, i);
            if (is_filter(f) && enabled(f)) { MSG(void, signed char)(f, s_enabled_set, 0); filters++; }
        }
    }
    int capture = responds(layer, s_capture) && MSG(signed char)(layer, s_capture);
    const char *recipe = responds(layer, s_recipe) ? cstring(MSG(id)(layer, s_recipe)) : NULL;
    void *want = capture ? NULL : pick(recipe);
    void *have = MSG(void *)(layer, s_bg);
    int first = !objc_getAssociatedObject(layer, &flattened);
    if (have != want) MSG(void, void *)(layer, s_set_bg, want);
    if (first) {
        objc_setAssociatedObject(layer, &flattened, (id)objc_getClass("NSObject"), OBJC_ASSOCIATION_ASSIGN);
        unsigned n = atomic_fetch_add(&flattened, 1) + 1;
        if (atomic_fetch_add(&logged, 1) < 32)
            say("HKFLAT: flat %u recipe=%s capture=%d filters=%u\n", n, recipe ? recipe : "?", capture, filters);
    }
    busy = 0;
}

static void hk_layout(id self, SEL cmd) { orig_layout(self, cmd); flatten(self); }
static void hk_configure(id self, SEL cmd, id interpolator) { orig_configure(self, cmd, interpolator); flatten(self); }

static void hk_set_filters(id self, SEL cmd, id list) {
    if (!busy && is_array(list)) {
        unsigned long n = MSG(unsigned long)(list, s_count);
        for (unsigned long i = 0; i < n && i < 64; i++) quiet_vibrant(MSG(id, unsigned long)(list, s_at, i));
    }
    orig_set_filters(self, cmd, list);
}

static void hk_set_compositing(id self, SEL cmd, id filter) {
    if (!busy) quiet_vibrant(filter);
    orig_set_compositing(self, cmd, filter);
}

/* Replace an IMP that the class itself defines (never an inherited one). Returns the original or NULL. */
static IMP swap(Class cls, const char *name, IMP replacement) {
    if (!cls) return NULL;
    SEL sel = sel_registerName(name);
    unsigned count = 0;
    Method *list = class_copyMethodList(cls, &count), found = NULL;
    for (unsigned i = 0; i < count; i++) if (method_getName(list[i]) == sel) { found = list[i]; break; }
    free(list);
    return found ? method_setImplementation(found, replacement) : NULL;
}

static int layer_hooks_done, material_hooks_done, tries;

static void install(void *unused) {
    (void)unused;
    if (!layer_hooks_done && objc_getClass("CALayer")) {
        Class layer = objc_getClass("CALayer");
        orig_set_filters = (ObjIMP)swap(layer, "setFilters:", (IMP)hk_set_filters);
        orig_set_compositing = (ObjIMP)swap(layer, "setCompositingFilter:", (IMP)hk_set_compositing);
        c_filter = objc_getClass("CAFilter");
        layer_hooks_done = 1;
    }
    Class material = objc_getClass("MTMaterialLayer");
    if (!material_hooks_done && material) {
        orig_layout = (VoidIMP)swap(material, "layoutSublayers", (IMP)hk_layout);
        orig_configure = (ObjIMP)swap(material, "_configureIfNecessaryWithSettingsInterpolator:", (IMP)hk_configure);
        material_hooks_done = 1;
        say("HKFLAT: %s[%d] hooks layout=%d configure=%d filters=%d compositing=%d\n", getprogname(), getpid(),
            orig_layout != NULL, orig_configure != NULL, orig_set_filters != NULL, orig_set_compositing != NULL);
        return;
    }
    if (++tries < 40) dispatch_after_f(dispatch_time(DISPATCH_TIME_NOW, 500 * NSEC_PER_MSEC), dispatch_get_main_queue(), NULL, install);
    else say("HKFLAT: %s[%d] MTMaterialLayer not found, material hooks off\n", getprogname(), getpid());
}

static void beat(void *unused) {
    (void)unused;
    static unsigned last_f = ~0u, last_v = ~0u, lines;
    unsigned f = atomic_load(&flattened), v = atomic_load(&vibrant_off);
    if ((f != last_f || v != last_v) && lines < 40) {
        lines++;
        say("HKFLAT: t=%llu flattened=%u vibrant_off=%u\n", (unsigned long long)((now_ms() - start_ms) / 1000), f, v);
    }
    last_f = f; last_v = v;
    if (lines < 40) dispatch_after_f(dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC),
                                     dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), NULL, beat);
}

__attribute__((constructor)) static void hk_flatmat_install(void) {
    const char *gate = getenv("HK_FLATMAT");
    if (!gate || strcmp(gate, "1") != 0) return;
#ifndef HK_FLATMAT_TEST
    if (strcmp(getprogname(), "SpringBoard") != 0) return;
#endif
    start_ms = now_ms();
    s_enabled_set = sel_registerName("setEnabled:"); s_filters = sel_registerName("filters");
    s_count = sel_registerName("count"); s_at = sel_registerName("objectAtIndex:"); s_type = sel_registerName("type");
    s_utf8 = sel_registerName("UTF8String"); s_recipe = sel_registerName("recipeName");
    s_capture = sel_registerName("captureOnly"); s_bg = sel_registerName("backgroundColor");
    s_set_bg = sel_registerName("setBackgroundColor:"); s_responds = sel_registerName("respondsToSelector:");
    s_iskind = sel_registerName("isKindOfClass:"); s_enabled_get = sel_registerName("isEnabled");
    c_array = objc_getClass("NSArray");
    install(NULL);
    dispatch_after_f(dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC), dispatch_get_global_queue(QOS_CLASS_UTILITY, 0),
                     NULL, beat);
}
