/* HOST test (macOS arm64) for hk_mainwatch.c built with -DHK_MAINWATCH_TEST. MIT.
 * A fake UIApplication/UIEvent pair stands in for UIKit. The test loads the dylib after setting HK_MAINWATCH=1 (the
 * constructor runs on the main thread at dlopen), lets the main queue drain, sends 3 touch events, 1 press and 1 other
 * through -[UIApplication sendEvent:], then blocks the main thread in block_main() for 8 s, then drains again for 12 s.
 * check_mainwatch.py reads stderr: watching line, hook line, >=1 stall whose frames include block_main, heartbeat with
 * touch=3 press=1 other=1, ORIG 5 (the original IMP ran for every event), and a gap line when the runner SIGSTOPs us. */
#import <Foundation/Foundation.h>
#include <objc/runtime.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static unsigned orig_calls;
@interface UIEvent : NSObject { @public long t; }
- (long)type;
@end
@implementation UIEvent
- (long)type { return t; }
@end
@interface UIApplication : NSObject
+ (instancetype)sharedApplication;
- (long)applicationState;
- (void)sendEvent:(id)event;
@end
@implementation UIApplication
+ (instancetype)sharedApplication { static UIApplication *app; if (!app) app = [UIApplication new]; return app; }
- (long)applicationState { return 1; }
- (void)sendEvent:(id)event { (void)event; ++orig_calls; }
@end

__attribute__((noinline)) void block_main(void) { sleep(8); __asm__ volatile("" ::: "memory"); }

static void drain(double seconds) { CFRunLoopRunInMode(kCFRunLoopDefaultMode, seconds, false); }

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 2 && argc != 3) return 2;
        if (argc == 3) {  /* "off": gate absent, the dylib must stay silent and leave sendEvent: alone */
            unsetenv("HK_MAINWATCH");
            IMP before = class_getMethodImplementation([UIApplication class], @selector(sendEvent:));
            if (!dlopen(argv[1], RTLD_NOW)) return 1;
            drain(1.5);
            UIEvent *e = [UIEvent new]; [[UIApplication sharedApplication] sendEvent:e];
            IMP after = class_getMethodImplementation([UIApplication class], @selector(sendEvent:));
            fprintf(stderr, "OFF orig %u imp-unchanged %d\n", orig_calls, before == after);
            return 0;
        }
        setenv("HK_MAINWATCH", "1", 1);
        if (!dlopen(argv[1], RTLD_NOW)) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
        fprintf(stderr, "BLOCK_FN %p\n", (void *)block_main);
        drain(2.5);
        long types[] = {0, 0, 0, 3, 7};
        for (unsigned i = 0; i < 5; ++i) { UIEvent *e = [UIEvent new]; e->t = types[i]; [[UIApplication sharedApplication] sendEvent:e]; }
        fprintf(stderr, "ORIG %u\n", orig_calls);
        block_main();
        drain(12.5);
        fprintf(stderr, "READY_FOR_STOP\n");
        drain(14.0);
        fprintf(stderr, "DONE\n");
    }
    return 0;
}
