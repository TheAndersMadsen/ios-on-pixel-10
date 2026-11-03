// Host test for hk_flatmat (macOS arm64). test_flatmat DYLIB [off]
// A fake MTMaterialLayer (subclass of the real CABackdropLayer) is registered before the dylib is loaded, the same
// order as on the phone (CoreMaterial is mapped before the inserted library's constructor runs).
#import <Foundation/Foundation.h>
#import <QuartzCore/QuartzCore.h>
#import <dlfcn.h>
#import <objc/message.h>
#import <objc/runtime.h>

static int layouts, configures, changes, fails;
static void check(int ok, const char *what) { printf("%s %s\n", ok ? "ok  " : "FAIL", what); if (!ok) fails++; }
static void fake_layout(id self, SEL _cmd) { (void)self; (void)_cmd; layouts++; }
static void fake_configure(id self, SEL _cmd, id x) { (void)self; (void)_cmd; (void)x; configures++; }
static id fake_recipe(id self, SEL _cmd) { (void)_cmd; return objc_getAssociatedObject(self, "r"); }
static void fake_did_change(id self, SEL _cmd, NSString *key) {
    (void)key; changes++;
    struct objc_super sup = {self, class_getSuperclass(object_getClass(self))};
    ((void (*)(struct objc_super *, SEL, id))objc_msgSendSuper)(&sup, _cmd, key);
}

static BOOL isOn(id o) { return ((BOOL (*)(id, SEL))objc_msgSend)(o, sel_registerName("isEnabled")); }
static id filter(NSString *type) { return ((id (*)(id, SEL, id))objc_msgSend)(NSClassFromString(@"CAFilter"), sel_registerName("filterWithType:"), type); }

int main(int argc, char **argv) {
    @autoreleasepool {
        Class backdrop = NSClassFromString(@"CABackdropLayer");
        if (!backdrop || !NSClassFromString(@"CAFilter")) { puts("FAIL no CABackdropLayer/CAFilter on this host"); return 1; }
        if (objc_getClass("MTMaterialLayer")) { puts("FAIL host already has MTMaterialLayer loaded"); return 1; }
        Class mt = objc_allocateClassPair(backdrop, "MTMaterialLayer", 0);
        class_addMethod(mt, @selector(layoutSublayers), (IMP)fake_layout, "v@:");
        class_addMethod(mt, sel_registerName("_configureIfNecessaryWithSettingsInterpolator:"), (IMP)fake_configure, "v@:@");
        class_addMethod(mt, sel_registerName("recipeName"), (IMP)fake_recipe, "@@:");
        class_addMethod(mt, @selector(didChangeValueForKey:), (IMP)fake_did_change, "v@:@");
        objc_registerClassPair(mt);
        IMP layout0 = method_getImplementation(class_getInstanceMethod(mt, @selector(layoutSublayers)));
        IMP filters0 = method_getImplementation(class_getInstanceMethod([CALayer class], @selector(setFilters:)));
        int off = argc > 2 && !strcmp(argv[2], "off");
        if (off) unsetenv("HK_FLATMAT"); else setenv("HK_FLATMAT", "1", 1);
        if (!dlopen(argv[1], RTLD_NOW)) { printf("FAIL dlopen %s\n", dlerror()); return 1; }
        if (off) {
            int same = layout0 == method_getImplementation(class_getInstanceMethod(mt, @selector(layoutSublayers))) &&
                       filters0 == method_getImplementation(class_getInstanceMethod([CALayer class], @selector(setFilters:)));
            printf("OFF imp-unchanged %d\n", same);
            return same ? 0 : 1;
        }
        CALayer *tile = [mt new];
        objc_setAssociatedObject(tile, "r", @"modules", OBJC_ASSOCIATION_RETAIN);
        id cm = filter(@"colorMatrix");
        tile.filters = @[cm];
        check(isOn(tile) && isOn(cm), "before: backdrop and filter on");
        [tile layoutSublayers];
        check(layouts == 1, "original layoutSublayers ran");
        check(!isOn(tile), "tile backdrop off");
        check(!isOn(tile.filters[0]), "tile filter off but kept");
        check(tile.filters.count == 1, "filter array unchanged");
        const CGFloat *c = tile.backgroundColor ? CGColorGetComponents(tile.backgroundColor) : NULL;
        check(c && fabs(c[0] - 0.22) < 0.01 && fabs(CGColorGetAlpha(tile.backgroundColor) - 0.92) < 0.01, "tile grey 0.22/0.92");
        int before = changes;
        [tile layoutSublayers];
        check(layouts == 2 && changes == before, "second pass: no setter, no change notification (no layout loop)");
        id kv = [tile valueForKeyPath:@"filters.colorMatrix"];
        check(kv != nil, "key path filters.colorMatrix still resolves");

        CALayer *bg = [mt new];
        objc_setAssociatedObject(bg, "r", @"modulesBackground", OBJC_ASSOCIATION_RETAIN);
        ((void (*)(id, SEL, id))objc_msgSend)(bg, sel_registerName("_configureIfNecessaryWithSettingsInterpolator:"), nil);
        check(configures == 1, "original configure ran");
        check(bg.backgroundColor && fabs(CGColorGetAlpha(bg.backgroundColor) - 0.55) < 0.01, "background dim 0.55");

        if ([backdrop instancesRespondToSelector:sel_registerName("setCaptureOnly:")]) {
            CALayer *cap = [mt new];
            ((void (*)(id, SEL, BOOL))objc_msgSend)(cap, sel_registerName("setCaptureOnly:"), YES);
            [cap layoutSublayers];
            check(cap.backgroundColor == NULL && !isOn(cap), "capture-only: off, no colour");
        } else puts("skip capture-only (no setCaptureOnly: on this host)");

        CALayer *glyph = [CALayer layer];
        id vib = filter(@"vibrantColorMatrix"), blur = filter(@"gaussianBlur"), dark = filter(@"vibrantDark");
        glyph.compositingFilter = vib;
        check(glyph.compositingFilter == vib && !isOn(vib), "compositing vibrantColorMatrix kept, switched off");
        glyph.filters = @[dark, blur];
        check(!isOn(dark) && isOn(blur) && glyph.filters.count == 2, "filters: vibrantDark off, gaussianBlur untouched");
        glyph.compositingFilter = @"plusD";
        check([glyph.compositingFilter isEqual:@"plusD"], "string compositing filter passes through");
        printf("RESULT %s %d fail\n", fails ? "FAIL" : "PASS", fails);
    }
    return fails != 0;
}
