/* Stock-app registration for the research root. No signer/identity overrides.
 * Uses URL registration and fresh LaunchServices enumeration as described by
 * vphone-cli's MIT-licensed VPhoneDaemon/Native/vphoned_apps.m at fd1610d7.
 * This is an independent, deliberately smaller implementation. Registration
 * is never reported as proof that an app launched or that Apple services work.
 */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <fcntl.h>
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
- (void)openApplicationWithBundleID:(NSString *)identifier;
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

static void consoleBytes(const void *bytes, size_t size) {
    // iOS launchd stdout wiring is not itself evidence that a marker reached
    // the console. Open the same explicit console used by the existing probes.
    // Fixture builds never write to the host's real console.
#if defined(HK_STOCK_APPS_HOST_FIXTURE)
    int fd = STDERR_FILENO;
#else
    int fd = open("/dev/console", O_WRONLY | O_NOCTTY | O_CLOEXEC);
    if (fd < 0) fd = STDERR_FILENO;
#endif
    const char *cursor = bytes;
    while (size) {
        ssize_t n = write(fd, cursor, size);
        if (n <= 0) break;
        cursor += n; size -= (size_t)n;
    }
    if (fd != STDERR_FILENO) close(fd);
}

#ifndef HK_STOCK_APPS_NO_MAIN
static void entryMarker(void) {
    // Runs before the first Objective-C/autorelease/JSON operation in main.
    char line[128];
    int n = snprintf(line, sizeof(line), "HKAPPS: {\"event\":\"main_entry_c\",\"pid\":%u}\n", (unsigned)getpid());
    if (n > 0 && (size_t)n < sizeof(line)) consoleBytes(line, (size_t)n);
}
#endif

struct JSONLine { char bytes[4096]; size_t used; int overflow; };
static void token(struct JSONLine *line, const char *text, size_t length) {
    if (line->overflow || length > sizeof(line->bytes) - line->used) {
        line->overflow = 1; return;
    }
    memcpy(line->bytes + line->used, text, length); line->used += length;
}
static void stringValue(struct JSONLine *line, const char *text) {
    if (!text) { token(line, "null", 4); return; }
    token(line, "\"", 1);
    for (const unsigned char *p = (const unsigned char *)text; *p && !line->overflow; p++) {
        if (*p == '"' || *p == '\\') {
            char escaped[2] = {'\\', (char)*p}; token(line, escaped, 2);
        } else if (*p < 0x20) {
            char escaped[7]; (void)snprintf(escaped, sizeof(escaped), "\\u%04x", *p);
            token(line, escaped, 6);
        } else token(line, (const char *)p, 1);
    }
    token(line, "\"", 1);
}
static void numberValue(struct JSONLine *line, unsigned long long value) {
    char text[32]; int n = snprintf(text, sizeof(text), "%llu", value);
    if (n > 0 && (size_t)n < sizeof(text)) token(line, text, (size_t)n);
}
static void finishLine(struct JSONLine *line) {
    token(line, "}\n", 2);
    if (line->overflow) {
        const char failure[] = "HKAPPS: {\"event\":\"error\",\"reason\":\"receipt_too_large\"}\n";
        consoleBytes(failure, sizeof(failure) - 1);
    } else consoleBytes(line->bytes, line->used);
}
static void receipt(NSDictionary *record) {
    // Logging must not require NSJSONSerialization's initialization or services.
    struct JSONLine line = {0}; token(&line, "HKAPPS: {", 9); int separator = 0;
    for (NSString *key in record) {
        if (separator++) token(&line, ",", 1);
        stringValue(&line, key.UTF8String); token(&line, ":", 1);
        id value = record[key];
        if (value == (__bridge id)kCFBooleanTrue) token(&line, "true", 4);
        else if (value == (__bridge id)kCFBooleanFalse) token(&line, "false", 5);
        else if ([value isKindOfClass:NSString.class]) stringValue(&line, [value UTF8String]);
        else if ([value isKindOfClass:NSNumber.class]) numberValue(&line, [value unsignedLongLongValue]);
        else token(&line, "null", 4);
    }
    finishLine(&line);
}

static void progress(const char *phase, NSString *identifier) {
    // The nil-identifier startup stages use only C, including before the first
    // framework load. A logging framework cannot hide the API's entry receipt.
    struct JSONLine line = {0}; token(&line, "HKAPPS: {\"event\":\"phase\",\"phase\":", 33);
    stringValue(&line, phase); token(&line, ",\"pid\":", 7); numberValue(&line, (unsigned)getpid());
    token(&line, ",\"bundle_id\":", 13); stringValue(&line, identifier ? identifier.UTF8String : NULL);
    finishLine(&line);
}

#if defined(HK_STOCK_APPS_HOST_FIXTURE)
void hkStockAppReceiptFixture(void) {
    receipt(@{@"event": @"escape_fixture", @"text": @"quote\" slash\\ newline\n control\001 æ",
              @"positive": @YES, @"negative": @NO, @"integer": @51});
    receipt(@{@"event": @"overflow_fixture", @"text": [@"\001" stringByPaddingToLength:4096 withString:@"\001" startingAtIndex:0]});
}
#endif

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
    progress("manifest_read", nil);
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
    BOOL exercising = [action isEqual:@"exercise"];
    id smokeIDs = manifest[@"smoke_bundle_ids"];
    if (exercising) {
        if (![smokeIDs isKindOfClass:NSArray.class] || ![smokeIDs count] || [smokeIDs count] > 8) {
            receipt(@{@"event": @"error", @"reason": @"invalid_smoke_plan"}); return 2;
        }
        NSMutableSet *seen = [NSMutableSet set];
        for (id identifier in smokeIDs) {
            if (![identifier isKindOfClass:NSString.class] || ![identifiers containsObject:identifier]
                || [seen containsObject:identifier]) {
                receipt(@{@"event": @"error", @"reason": @"invalid_smoke_plan"}); return 2;
            }
            [seen addObject:identifier];
        }
    }
    BOOL registering = ![action isEqual:@"query"];
    progress("workspace_connect", nil);
#if defined(HK_STOCK_APPS_HOST_FIXTURE)
    Class cls = Nil; // A fixture CLI must never contact the Mac's workspace.
#else
    Class cls = NSClassFromString(@"LSApplicationWorkspace");
#endif
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
                progress("registration_readback", identifier);
                verified = hkStockAppIsListed(workspace, identifier, path);
                if (!verified && registering) {
                    progress("register_url", identifier);
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
    if (exercising) {
        if (![workspace respondsToSelector:@selector(openApplicationWithBundleID:)]) {
            receipt(@{@"event": @"error", @"reason": @"launch_selector_unavailable"}); return 3;
        }
        for (NSString *identifier in smokeIDs) {
            if (![complete containsObject:identifier]) {
                receipt(@{@"event": @"launch_skipped", @"bundle_id": identifier,
                          @"reason": @"registration_not_verified", @"launch_verified": @NO});
                continue;
            }
            progress("launch_request", identifier);
            // This selector's return type differs in historical headers. Its
            // return value is deliberately unused. Only actual exec/UI evidence
            // from the guest can establish a launch and surviving foreground UI.
            [workspace openApplicationWithBundleID:identifier];
            receipt(@{@"event": @"launch_request_returned", @"bundle_id": identifier,
                      @"launch_verified": @NO, @"settle_seconds": @20});
            sleep(20);
        }
    }
    return complete.count == apps.count ? 0 : 1;
}

#ifndef HK_STOCK_APPS_NO_MAIN
int main(int argc, const char *argv[]) {
    entryMarker();
    @autoreleasepool { @try {
        progress("autorelease_pool_entered", nil);
        if ((argc != 3 && argc != 4) || (strcmp(argv[1], "register") && strcmp(argv[1], "query") && strcmp(argv[1], "exercise"))) {
            fprintf(stderr, "usage: hk_app_register query|register|exercise MANIFEST.plist [ATTEMPTS 1..12]\n"); return 2;
        }
        char *end = NULL;
        unsigned long attempts = argc == 4 ? strtoul(argv[3], &end, 10) : 1;
        if (attempts < 1 || attempts > 12 || (argc == 4 && (!argv[3][0] || *end))) return 2;
        if (strcmp(argv[1], "query") == 0 && attempts != 1) return 2;
        // Test host supplies a fixture workspace, never a host application registrar.
#if !defined(HK_STOCK_APPS_HOST_FIXTURE)
        progress("framework_load", nil);
        if (!dlopen("/System/Library/Frameworks/MobileCoreServices.framework/MobileCoreServices", RTLD_NOW)) {
            receipt(@{@"event": @"error", @"reason": @"framework_unavailable"}); return 3;
        }
        progress("framework_loaded", nil);
#endif
        return hkRegisterStockApps(@(argv[1]), @(argv[2]), (unsigned)attempts);
    } @catch (NSException *exception) {
        (void)exception;
        receipt(@{@"event": @"error", @"reason": @"workspace_exception"}); return 3;
    } }
}
#endif
#endif
