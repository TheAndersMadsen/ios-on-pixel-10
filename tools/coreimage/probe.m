/* Copyright (c) 2026 hackios contributors. MIT.
 * Diagnostic observer for the 23G90 CoreImage fallback experiment.
 * Both QEMU arms load this identical library. It changes no rendering options.
 */
#import <Foundation/Foundation.h>
#import <CoreImage/CoreImage.h>
#import <objc/runtime.h>
#include <fcntl.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

extern const char *getprogname(void);
typedef void *(*ContextIMP)(id, SEL, id);
static ContextIMP saved_sw, saved_gl;
static _Thread_local unsigned observing, sw_calls, gl_calls;

static void report(const char *format, ...) {
    char buf[768]; va_list ap;
    va_start(ap, format); int n = vsnprintf(buf, sizeof buf, format, ap); va_end(ap);
    int fd = open("/dev/console", O_WRONLY | O_NOCTTY);
    if (fd >= 0) {
        if (n > 0) (void)write(fd, buf, (size_t)n < sizeof buf ? (size_t)n : sizeof buf - 1);
        close(fd);
    }
}

static void *observe_sw(id self, SEL cmd, id options) {
    if (observing) ++sw_calls;
    return saved_sw(self, cmd, options);
}

static void *observe_gl(id self, SEL cmd, id options) {
    if (observing) ++gl_calls;
    return saved_gl(self, cmd, options);
}

static BOOL correct_image(intptr_t *slide) {
    static const unsigned char uuid[16] = {
        0x6f,0x5a,0xbd,0x16,0x0e,0x3c,0x3f,0xc3,0xbc,0xc7,0xcc,0xef,0xea,0xfb,0xca,0x00
    };
    const char *path = "/System/Library/Frameworks/CoreImage.framework/CoreImage";
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const char *name = _dyld_get_image_name(i);
        if (!name || strcmp(name, path)) continue;
        const struct mach_header_64 *mh = (const void *)_dyld_get_image_header(i);
        if (mh->magic != MH_MAGIC_64) return NO;
        const unsigned char *p = (const void *)(mh + 1);
        const unsigned char *end = p + mh->sizeofcmds;
        for (uint32_t j = 0; j < mh->ncmds; ++j) {
            if ((size_t)(end - p) < sizeof(struct load_command)) return NO;
            const struct load_command *lc = (const void *)p;
            if (lc->cmdsize < sizeof(*lc) || lc->cmdsize > (size_t)(end - p)) return NO;
            if (lc->cmd == LC_UUID && lc->cmdsize >= sizeof(struct uuid_command)) {
                if (memcmp(((const struct uuid_command *)lc)->uuid, uuid, sizeof uuid)) return NO;
                *slide = _dyld_get_image_vmaddr_slide(i);
                return YES;
            }
            p += lc->cmdsize;
        }
    }
    return NO;
}

static BOOL observe_method(const char *name, IMP observer, ContextIMP *saved) {
    Method method = class_getClassMethod([CIContext class], sel_registerName(name));
    if (!method || method_getNumberOfArguments(method) != 3) return NO;
    char type[16]; method_getReturnType(method, type, sizeof type);
    if (type[0] != '@' && type[0] != '^') {
        report("HKCI: observer %s return=%s\n", name, type); return NO;
    }
    method_getArgumentType(method, 2, type, sizeof type);
    if (type[0] != '@') return NO;
    *saved = (ContextIMP)method_setImplementation(method, observer);
    return *saved != NULL;
}

static BOOL check_pixels(CIContext *context, CIImage *input, CGColorSpaceRef space, BOOL invert) {
    unsigned char output[16 + 64 + 16]; memset(output, 0xa5, sizeof output);
    CIImage *image = invert ? [input imageByApplyingFilter:@"CIColorInvert"] : input;
    if (!image) return NO;
    [context render:image toBitmap:output + 16 rowBytes:16 bounds:CGRectMake(0, 0, 4, 4)
             format:kCIFormatRGBA8 colorSpace:space];
    for (unsigned i = 0; i < 16; ++i)
        if (output[i] != 0xa5 || output[80 + i] != 0xa5) {
            report("HKCI: PIXELS invert=%d guard changed\n", invert); return NO;
        }
    const unsigned char expected[4] = {invert ? 0 : 255, invert ? 255 : 0, invert ? 255 : 0, 255};
    for (unsigned i = 0; i < 16; ++i)
        if (memcmp(output + 16 + 4 * i, expected, sizeof expected)) {
            report("HKCI: PIXELS invert=%d first_bad=%u rgba=%02x%02x%02x%02x\n", invert, i,
                output[16+4*i], output[17+4*i], output[18+4*i], output[19+4*i]);
            return NO;
        }
    return YES;
}

__attribute__((constructor)) static void coreimage_probe(void) {
    if (strcmp(getprogname(), "SpringBoard")) return;
    @autoreleasepool {
        intptr_t slide = 0;
        if (!correct_image(&slide)) { report("HKCI: REFUSED unknown CoreImage UUID\n"); return; }
        const unsigned char *entry = (const void *)(0x19e041778ULL + slide);
        static const unsigned char stock[8] = {0x68,0x81,0x27,0xf0,0x08,0x59,0x44,0xf9};
        static const unsigned char patched[8] = {0x20,0x00,0x80,0x52,0xc0,0x03,0x5f,0xd6};
        BOOL changed = !memcmp(entry, patched, 8);
        if (!changed && memcmp(entry, stock, 8)) { report("HKCI: REFUSED unknown isWidget entry\n"); return; }
        if (!observe_method("internalSWContextWithOptions:", (IMP)observe_sw, &saved_sw) ||
            !observe_method("internalGLContextWithOptions:", (IMP)observe_gl, &saved_gl)) {
            if (saved_sw) method_setImplementation(class_getClassMethod([CIContext class],
                sel_registerName("internalSWContextWithOptions:")), (IMP)saved_sw);
            report("HKCI: REFUSED context observer signature\n"); return;
        }
        BOOL (*is_widget)(void) = (void *)entry;
        report("HKCI: BEGIN pid=%d patched=%d isWidget=%d\n", getpid(), changed, is_widget());
        CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
        CIImage *input = [[CIImage imageWithColor:[CIColor colorWithRed:1 green:0 blue:0 alpha:1]]
            imageByCroppingToRect:CGRectMake(0, 0, 4, 4)];
        report("HKCI: INPUT constant_red=%d space=%d format=%d\n", input != nil, space != NULL, kCIFormatRGBA8);
        // 23G90's initWithOptions: compares software_renderer.intValue with 2
        // before calling internalSWContextWithOptions:. This is the independent
        // positive control for the same route, without changing isWidget.
        NSArray *options = @[[NSNull null], @{kCIContextUseSoftwareRenderer:@NO},
            @{kCIContextUseSoftwareRenderer:@YES}, @{kCIContextUseSoftwareRenderer:@2}];
        const char *labels[] = {"default", "request_gpu", "request_cpu", "reference_cpu_2"};
        for (unsigned i = 0; i < 4; ++i) {
            sw_calls = gl_calls = 0; observing = 1;
            @try {
                CIContext *context = [CIContext contextWithOptions:i ? options[i] : nil];
                BOOL identity = context && check_pixels(context, input, space, NO);
                BOOL invert = context && check_pixels(context, input, space, YES);
                report("HKCI: CASE %s context=%d sw=%u gl=%u identity=%d invert=%d\n",
                    labels[i], context != nil, sw_calls, gl_calls, identity, invert);
            } @catch (NSException *exception) {
                report("HKCI: CASE %s EXCEPTION %s sw=%u gl=%u\n", labels[i],
                    [[exception name] UTF8String], sw_calls, gl_calls);
            }
            observing = 0;
        }
        CGColorSpaceRelease(space);
        method_setImplementation(class_getClassMethod([CIContext class],
            sel_registerName("internalSWContextWithOptions:")), (IMP)saved_sw);
        method_setImplementation(class_getClassMethod([CIContext class],
            sel_registerName("internalGLContextWithOptions:")), (IMP)saved_gl);
        report("HKCI: END observers restored\n");
    }
}
