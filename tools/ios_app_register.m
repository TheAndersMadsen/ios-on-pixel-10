/* Stock-app registration for the research root. No signer/identity overrides.
 * Uses URL registration and fresh LaunchServices enumeration as described by
 * vphone-cli's MIT-licensed VPhoneDaemon/Native/vphoned_apps.m at fd1610d7.
 * This is an independent, deliberately smaller implementation. Registration
 * is never reported as proof that an app launched or that Apple services work.
 */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef HK_STOCK_APPS_BUILD
#define HK_STOCK_APPS_BUILD 0
#endif

#if HK_STOCK_APPS_BUILD
@interface NSObject (HKAppWorkspace)
+ (id)defaultWorkspace;
- (BOOL)registerApplication:(NSURL *)url;
- (NSArray *)allApplications;
- (NSString *)applicationIdentifier;
- (NSURL *)bundleURL;
- (BOOL)isInstalled;
- (BOOL)isPlaceholder;
@end

static id readPlist(NSString *path) {
    NSData *data = [NSData dataWithContentsOfFile:path options:0 error:NULL];
    return data ? [NSPropertyListSerialization propertyListWithData:data
        options:NSPropertyListImmutable format:NULL error:NULL] : nil;
}

static void receipt(NSDictionary *record) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingSortedKeys error:NULL];
    if (data) {
        // Prefix permits extraction from interleaved kernel/daemon console logs.
        fprintf(stdout, "HKAPPS: %.*s\n", (int)data.length, (const char *)data.bytes);
        fflush(stdout);
    }
}

static void progress(NSString *phase, NSString *identifier) {
    receipt(@{@"event": @"phase", @"phase": phase, @"pid": @(getpid()),
              @"bundle_id": identifier ?: (id)NSNull.null});
}

BOOL hkStockAppEntryValid(id entry) {
    if (![entry isKindOfClass:NSDictionary.class]) return NO;
    NSString *identifier = entry[@"bundle_id"], *path = entry[@"path"];
    if (![identifier isKindOfClass:NSString.class] || !identifier.length
        || ![path isKindOfClass:NSString.class]) return NO;
    NSArray *parts = path.pathComponents;
    return parts.count == 3 && [parts[0] isEqual:@"/"]
        && [parts[1] isEqual:@"Applications"]
        && [path.pathExtension isEqual:@"app"]
        && [path isEqual:path.stringByStandardizingPath];
}

BOOL hkStockAppIsListed(id workspace, NSString *identifier, NSString *path) {
    // A proxy created by applicationProxyForIdentifier: can outlive its record.
    // Enumerating again verifies the actual current path and excludes placeholders.
    id applications = [workspace allApplications];
    if (![applications isKindOfClass:NSArray.class]) return NO;
    for (id app in applications) {
        if (![app respondsToSelector:@selector(applicationIdentifier)]
            || ![app respondsToSelector:@selector(bundleURL)]
            || ![app respondsToSelector:@selector(isInstalled)]
            || ![app respondsToSelector:@selector(isPlaceholder)]) continue;
        if ([[app applicationIdentifier] isEqual:identifier] && [app isInstalled]
            && ![app isPlaceholder]
            && [[app bundleURL].path.stringByStandardizingPath isEqual:path]) return YES;
    }
    return NO;
}

int hkRegisterStockApps(NSString *action, NSString *manifestPath, unsigned attempts) {
    progress(@"manifest_read", nil);
    id manifest = readPlist(manifestPath);
    if (![manifest isKindOfClass:NSDictionary.class]
        || ![manifest[@"schema"] isEqual:@"hackios-stock-apps-v1"]
        || ![manifest[@"apps"] isKindOfClass:NSArray.class]
        || ![manifest[@"apps"] count] || [manifest[@"apps"] count] > 256) {
        receipt(@{@"event": @"error", @"reason": @"invalid_manifest"}); return 2;
    }
    NSArray *apps = manifest[@"apps"];
    NSMutableSet *identifiers = [NSMutableSet set], *paths = [NSMutableSet set];
    for (id entry in apps) {
        if (!hkStockAppEntryValid(entry) || [identifiers containsObject:entry[@"bundle_id"]]
            || [paths containsObject:entry[@"path"]]) {
            receipt(@{@"event": @"error", @"reason": @"invalid_or_duplicate_entry"}); return 2;
        }
        [identifiers addObject:entry[@"bundle_id"]]; [paths addObject:entry[@"path"]];
    }
    BOOL registering = [action isEqual:@"register"];
    progress(@"workspace_connect", nil);
    Class cls = NSClassFromString(@"LSApplicationWorkspace");
    id workspace = [cls respondsToSelector:@selector(defaultWorkspace)] ? [cls defaultWorkspace] : nil;
    if (![workspace respondsToSelector:@selector(allApplications)]
        || (registering && ![workspace respondsToSelector:@selector(registerApplication:)])) {
        receipt(@{@"event": @"error", @"reason": @"workspace_unavailable"}); return 3;
    }
    NSMutableSet *complete = [NSMutableSet set];
    for (unsigned attempt = 1; attempt <= attempts; attempt++) {
        for (NSDictionary *entry in apps) {
            NSString *identifier = entry[@"bundle_id"], *path = entry[@"path"];
            if ([complete containsObject:identifier]) continue;
            id info = readPlist([path stringByAppendingPathComponent:@"Info.plist"]);
            NSString *exe = [info isKindOfClass:NSDictionary.class] ? info[@"CFBundleExecutable"] : nil;
            NSString *reason = @"not_listed";
            BOOL accepted = NO, verified = NO;
            if (![info isKindOfClass:NSDictionary.class] || ![info[@"CFBundleIdentifier"] isEqual:identifier]) {
                reason = @"missing_or_mismatched_bundle";
            } else if (![path isEqual:path.stringByResolvingSymlinksInPath]
                       || ![exe isKindOfClass:NSString.class] || !exe.length
                       || ![exe isEqual:exe.lastPathComponent] || [exe isEqual:@".."] || [exe isEqual:@"."]
                       || ![[NSFileManager.defaultManager attributesOfItemAtPath:[path stringByAppendingPathComponent:exe]
                           error:NULL][NSFileType] isEqual:NSFileTypeRegular]
                       || ![NSFileManager.defaultManager isExecutableFileAtPath:[path stringByAppendingPathComponent:exe]]) {
                reason = @"invalid_executable_or_path";
            } else {
                progress(@"registration_readback", identifier);
                verified = hkStockAppIsListed(workspace, identifier, path);
                if (!verified && registering) {
                    progress(@"register_url", identifier);
                    accepted = [workspace registerApplication:[NSURL fileURLWithPath:path isDirectory:YES]];
                    // Allow an asynchronous registration to appear; re-enumerate each time.
                    for (unsigned poll = 0; poll < 10 && !verified; poll++) {
                        usleep(100000); verified = hkStockAppIsListed(workspace, identifier, path);
                    }
                }
                if (verified) { [complete addObject:identifier]; reason = @"listed_at_expected_path"; }
            }
            receipt(@{@"event": @"app", @"action": action, @"bundle_id": identifier,
                      @"path": path, @"attempt": @(attempt), @"api_accepted": @(accepted),
                      @"registration_verified": @(verified), @"reason": reason,
                      @"launch_verified": @NO});
        }
        if (complete.count == apps.count || !registering) break;
        if (attempt < attempts) sleep(5);
    }
    receipt(@{@"event": @"summary", @"expected": @(apps.count),
              @"registration_verified": @(complete.count), @"launch_verified": @0,
              @"all_registered": @(complete.count == apps.count)});
    return complete.count == apps.count ? 0 : 1;
}

#ifndef HK_STOCK_APPS_NO_MAIN
int main(int argc, const char *argv[]) {
    @autoreleasepool { @try {
        if ((argc != 3 && argc != 4) || (strcmp(argv[1], "register") && strcmp(argv[1], "query"))) {
            fprintf(stderr, "usage: hk_app_register query|register MANIFEST.plist [ATTEMPTS 1..12]\n"); return 2;
        }
        char *end = NULL;
        unsigned long attempts = argc == 4 ? strtoul(argv[3], &end, 10) : 1;
        if (attempts < 1 || attempts > 12 || (argc == 4 && (!argv[3][0] || *end))) return 2;
        if (strcmp(argv[1], "query") == 0 && attempts != 1) return 2;
        // Test host supplies a fixture workspace, never a host application registrar.
#if !defined(HK_STOCK_APPS_HOST_FIXTURE)
        progress(@"framework_load", nil);
        if (!dlopen("/System/Library/Frameworks/MobileCoreServices.framework/MobileCoreServices", RTLD_NOW)) {
            receipt(@{@"event": @"error", @"reason": @"framework_unavailable"}); return 3;
        }
        progress(@"framework_loaded", nil);
#endif
        return hkRegisterStockApps(@(argv[1]), @(argv[2]), (unsigned)attempts);
    } @catch (NSException *exception) {
        (void)exception;
        receipt(@{@"event": @"error", @"reason": @"workspace_exception"}); return 3;
    } }
}
#endif
#endif
