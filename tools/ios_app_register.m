/* Stock-app registration for the research root. No signer/identity overrides.
 * Uses URL registration and fresh LaunchServices enumeration as described by
 * vphone-cli's MIT-licensed VPhoneDaemon/Native/vphoned_apps.m at fd1610d7.
 * This is an independent, deliberately smaller implementation. Registration
 * is never reported as proof that an app launched or that Apple services work.
 */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
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

@interface NSObject (HKContainerManager)
+ (id)containerWithIdentifier:(NSString *)identifier createIfNecessary:(BOOL)create
    existed:(BOOL *)existed error:(NSError **)error;
- (NSURL *)url;
@end

static void progress(const char *, NSString *);
#if defined(HK_STOCK_APPS_LSLOG) && !defined(HK_STOCK_APPS_HOST_FIXTURE)
static void hkDumpLaunchServicesLog(NSDate *since);
static NSDate *hkLsLogSince;
static BOOL hkLsLogDone;
#endif
static void fileReadProbe(NSString *);
static id readPlist(NSString *path) {
    fileReadProbe(path);
    progress("plist_data_read_enter", nil);
    NSData *data = [NSData dataWithContentsOfFile:path options:0 error:NULL];
    progress(data ? "plist_data_read_return" : "plist_data_read_failed", nil);
    if (!data) return nil;
    progress("plist_parse_enter", nil);
    id value = [NSPropertyListSerialization propertyListWithData:data
        options:NSPropertyListImmutable format:NULL error:NULL];
    progress(value ? "plist_parse_return" : "plist_parse_failed", nil);
    return value;
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

/* Diagnostic only (H2, registration-h2-r10): ask the real MobileContainerManager
 * for the app's data container exactly as an installer would, and record its
 * actual answer. Never synthesizes a container, path or success. */
static void containerProbe(NSString *identifier) {
    progress("container_probe_enter", identifier);
#if defined(HK_STOCK_APPS_HOST_FIXTURE)
    Class mcm = Nil;
#else
    dlopen("/System/Library/PrivateFrameworks/MobileContainerManager.framework/MobileContainerManager", RTLD_NOW);
    Class mcm = NSClassFromString(@"MCMAppDataContainer");
#endif
    if (![mcm respondsToSelector:@selector(containerWithIdentifier:createIfNecessary:existed:error:)]) {
        receipt(@{@"event": @"container_probe", @"bundle_id": identifier, @"available": @NO});
        return;
    }
    BOOL existed = NO; NSError *error = nil;
    id container = [mcm containerWithIdentifier:identifier createIfNecessary:YES existed:&existed error:&error];
    NSString *path = [container respondsToSelector:@selector(url)] ? [container url].path : nil;
    NSString *text = error.description ?: @"";
    if (text.length > 400) text = [text substringToIndex:400];
    receipt(@{@"event": @"container_probe", @"bundle_id": identifier, @"available": @YES,
              @"returned": @(container != nil), @"existed": @(existed),
              @"path": path ?: [NSNull null], @"error_domain": error.domain ?: [NSNull null],
              @"error_code": error ? [NSString stringWithFormat:@"%ld", (long)error.code] : [NSNull null], @"error": text});
    progress("container_probe_return", identifier);
}

static void progress(const char *phase, NSString *identifier) {
    // The nil-identifier startup stages use only C, including before the first
    // framework load. A logging framework cannot hide the API's entry receipt.
    struct JSONLine line = {0}; token(&line, "HKAPPS: {\"event\":\"phase\",\"phase\":", 33);
    stringValue(&line, phase); token(&line, ",\"pid\":", 7); numberValue(&line, (unsigned)getpid());
    token(&line, ",\"bundle_id\":", 13); stringValue(&line, identifier ? identifier.UTF8String : NULL);
    finishLine(&line);
}

static void fileReadProbe(NSString *path) {
    // Observe only the existing manifest/Info.plist path. Retain the original
    // Foundation read/parser below; no alternate data, permission or success.
    progress("plist_path_encode_enter", nil);
    const char *name = path.fileSystemRepresentation;
    progress("plist_path_encode_return", nil);
    int openError = 0, statError = 0, readError = 0;
    unsigned long long size = 0; ssize_t bytes = -1; char header[8] = {0};
    int fd = name ? open(name, O_RDONLY | O_CLOEXEC) : -1;
    if (fd < 0) openError = name ? errno : EINVAL;
    else {
        struct stat st;
        if (fstat(fd, &st)) statError = errno; else size = (unsigned long long)st.st_size;
        bytes = read(fd, header, sizeof(header)); if (bytes < 0) readError = errno;
        close(fd);
    }
    struct JSONLine line = {0};
    const char prefix[] = "HKAPPS: {\"event\":\"plist_posix_read\",\"path\":";
    token(&line, prefix, sizeof(prefix) - 1); stringValue(&line, name);
    token(&line, ",\"open_errno\":", 14); numberValue(&line, (unsigned)openError);
    token(&line, ",\"stat_errno\":", 14); numberValue(&line, (unsigned)statError);
    token(&line, ",\"read_errno\":", 14); numberValue(&line, (unsigned)readError);
    token(&line, ",\"file_bytes\":", 14); numberValue(&line, size);
    token(&line, ",\"header_bytes\":", 16); numberValue(&line, bytes < 0 ? 0 : (unsigned long long)bytes);
    token(&line, ",\"binary_plist\":", 16);
    token(&line, bytes == 8 && !memcmp(header, "bplist00", 8) ? "true" : "false",
        bytes == 8 && !memcmp(header, "bplist00", 8) ? 4 : 5);
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
    progress("all_applications_enter", identifier);
    id applications = [workspace allApplications];
    progress("all_applications_return", identifier);
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

static NSArray *exerciseEntries(NSArray *apps, NSArray *smokeIDs) {
    // The caller validated distinct IDs and their membership in the manifest.
    // Keep every entry, scheduling the explicitly selected UI checks first.
    NSMutableArray *ordered = [NSMutableArray arrayWithCapacity:apps.count];
    NSSet *selected = [NSSet setWithArray:smokeIDs];
    for (NSString *identifier in smokeIDs) {
        for (NSDictionary *entry in apps) {
            if ([entry[@"bundle_id"] isEqual:identifier]) { [ordered addObject:entry]; break; }
        }
    }
    for (NSDictionary *entry in apps) {
        if (![selected containsObject:entry[@"bundle_id"]]) [ordered addObject:entry];
    }
    return ordered;
}

static void exerciseVerified(id workspace, NSString *identifier, NSSet *selected,
                             NSMutableSet *requested, BOOL verified) {
    if (!verified || ![selected containsObject:identifier] || [requested containsObject:identifier]
        || ![workspace respondsToSelector:@selector(openApplicationWithBundleID:)]) return;
    progress("launch_request", identifier);
    // A returned request is not actual exec, foreground UI or Apple-service success.
    [workspace openApplicationWithBundleID:identifier];
    [requested addObject:identifier];
#if defined(HK_STOCK_APPS_HOST_FIXTURE)
    const unsigned settleSeconds = 0; // Fake workspace only; never host apps.
#else
    const unsigned settleSeconds = 20;
#endif
    receipt(@{@"event": @"launch_request_returned", @"bundle_id": identifier,
              @"launch_verified": @NO, @"settle_seconds": @(settleSeconds)});
    if (settleSeconds) sleep(settleSeconds);
}

#if defined(HK_STOCK_APPS_HOST_FIXTURE)
NSArray *hkStockAppOrderFixture(NSArray *apps, NSArray *smokeIDs) {
    return exerciseEntries(apps, smokeIDs);
}
void hkStockAppExerciseFixture(id workspace, NSString *identifier, NSSet *selected,
                              NSMutableSet *requested, BOOL verified) {
    exerciseVerified(workspace, identifier, selected, requested, verified);
}
#endif

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
    NSArray *scheduledApps = exercising ? exerciseEntries(apps, smokeIDs) : apps;
    NSSet *selected = exercising ? [NSSet setWithArray:smokeIDs] : [NSSet set];
    NSMutableSet *complete = [NSMutableSet set], *requested = [NSMutableSet set];
    for (unsigned attempt = 1; attempt <= attempts; attempt++) {
        for (NSDictionary *entry in scheduledApps) {
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
                    containerProbe(identifier);
                    progress("register_url", identifier);
                    NSURL *bundleURL = [NSURL fileURLWithPath:path isDirectory:YES];
                    progress("register_url_call_enter", identifier);
                    accepted = [workspace registerApplication:bundleURL];
                    progress(accepted ? "register_url_call_return_accepted" : "register_url_call_return_refused", identifier);
#if defined(HK_STOCK_APPS_LSLOG) && !defined(HK_STOCK_APPS_HOST_FIXTURE)
                    /* r11c never reached the end of the loop in 1200 s: read lsd's account at the first refusal. */
                    if (!accepted && !hkLsLogDone) { hkLsLogDone = YES; usleep(500000); hkDumpLaunchServicesLog(hkLsLogSince); }
#endif
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
            if (exercising) exerciseVerified(workspace, identifier, selected, requested, verified);
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
            if (![requested containsObject:identifier]) {
                receipt(@{@"event": @"launch_skipped", @"bundle_id": identifier,
                          @"reason": @"registration_not_verified", @"launch_verified": @NO});
            }
        }
    }
    return complete.count == apps.count ? 0 : 1;
}

#if defined(HK_STOCK_APPS_LSLOG) && !defined(HK_STOCK_APPS_HOST_FIXTURE)
/* Diagnostic only (lane 4 after H1/H2): lsd's own account of each refusal. Reads the
 * system unified-log store (OSLog SPI, entitlement com.apple.logging.local-store) for
 * entries since `since` from lsd or the LaunchServices/containermanager subsystems, and
 * emits them as receipts. Changes no registration behaviour; read-only. */
static void hkDumpLaunchServicesLog(NSDate *since) {
    progress("lslog_enter", nil);
    if (!dlopen("/System/Library/Frameworks/OSLog.framework/OSLog", RTLD_NOW)) {
        receipt(@{@"event": @"lslog", @"available": @NO, @"reason": @"oslog_framework_unavailable"}); return;
    }
    Class storeClass = NSClassFromString(@"OSLogStore");
    SEL local = NSSelectorFromString(@"localStoreAndReturnError:");
    if (!storeClass) {
        receipt(@{@"event": @"lslog", @"available": @NO, @"reason": @"oslogstore_class_missing"}); return;
    }
    {   /* r11e: which class methods this build has, so a failure still says what exists. */
        unsigned n = 0; Method *ms = class_copyMethodList(object_getClass(storeClass), &n);
        NSMutableArray *names = [NSMutableArray array];
        for (unsigned i = 0; i < n && i < 64; i++) [names addObject:NSStringFromSelector(method_getName(ms[i]))];
        free(ms);
        receipt(@{@"event": @"lslog_methods", @"count": @(n), @"names": [names componentsJoinedByString:@" "]});
    }
    NSError *error = nil;
    id store = nil;
    NSString *route = @"local_store";
    if ([storeClass respondsToSelector:local]) {
        id (*localStore)(id, SEL, NSError **) = (void *)objc_msgSend;
        store = localStore(storeClass, local, &error);
    } else if ([storeClass respondsToSelector:NSSelectorFromString(@"storeWithURL:error:")]) {
        /* r11e: system scope returned nil with no error. r11f: open the raw store directly. */
        id (*withURL)(id, SEL, NSURL *, NSError **) = (void *)objc_msgSend;
        route = @"url_var_db_diagnostics";
        store = withURL(storeClass, NSSelectorFromString(@"storeWithURL:error:"),
                        [NSURL fileURLWithPath:@"/private/var/db/diagnostics" isDirectory:YES], &error);
    } else {
        receipt(@{@"event": @"lslog", @"available": @NO, @"reason": @"no_store_entry_point"}); return;
    }
    receipt(@{@"event": @"lslog_route", @"route": route, @"opened": @(store != nil)});
    if (!store) {
        receipt(@{@"event": @"lslog", @"available": @NO, @"reason": @"local_store_refused",
                  @"error_domain": error.domain ?: @"", @"error_code": [NSString stringWithFormat:@"%ld", (long)error.code],
                  @"error": error.description ?: @""});
        return;
    }
    id (*positionAt)(id, SEL, NSDate *) = (void *)objc_msgSend;
    id position = positionAt(store, NSSelectorFromString(@"positionWithDate:"), since);
    NSPredicate *predicate = [NSPredicate predicateWithFormat:
        @"process == 'lsd' OR process == 'containermanagerd' OR subsystem BEGINSWITH 'com.apple.launchservices' "
        @"OR subsystem BEGINSWITH 'com.apple.containermanager' OR subsystem BEGINSWITH 'com.apple.LaunchServices'"];
    id (*enumerate)(id, SEL, NSUInteger, id, NSPredicate *, NSError **) = (void *)objc_msgSend;
    NSEnumerator *entries = enumerate(store, NSSelectorFromString(@"entriesEnumeratorWithOptions:position:predicate:error:"),
                                      0, position, predicate, &error);
    if (!entries) {
        receipt(@{@"event": @"lslog", @"available": @NO, @"reason": @"enumerator_refused",
                  @"error_code": [NSString stringWithFormat:@"%ld", (long)error.code], @"error": error.description ?: @""});
        return;
    }
    unsigned emitted = 0, seen = 0;
    for (id entry in entries) {
        seen++;
        if (emitted >= 600) continue;
        NSString *message = [entry respondsToSelector:@selector(composedMessage)] ? [entry performSelector:@selector(composedMessage)] : @"";
        if (message.length > 600) message = [message substringToIndex:600];
        NSString *process = [entry respondsToSelector:NSSelectorFromString(@"process")] ? [entry valueForKey:@"process"] : @"";
        NSString *subsystem = [entry respondsToSelector:NSSelectorFromString(@"subsystem")] ? [entry valueForKey:@"subsystem"] : @"";
        NSString *category = [entry respondsToSelector:NSSelectorFromString(@"category")] ? [entry valueForKey:@"category"] : @"";
        NSNumber *level = [entry respondsToSelector:NSSelectorFromString(@"level")] ? [entry valueForKey:@"level"] : @0;
        NSDate *date = [entry respondsToSelector:NSSelectorFromString(@"date")] ? [entry valueForKey:@"date"] : nil;
        receipt(@{@"event": @"lslog_entry", @"ms": @((unsigned long long)(MAX(0.0, [date timeIntervalSinceDate:since]) * 1000)),
                  @"process": process ?: @"", @"subsystem": subsystem ?: @"", @"category": category ?: @"",
                  @"level": level ?: @0, @"message": message ?: @""});
        emitted++;
    }
    receipt(@{@"event": @"lslog", @"available": @YES, @"seen": @(seen), @"emitted": @(emitted)});
}
#endif

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
#if defined(HK_STOCK_APPS_LSLOG) && !defined(HK_STOCK_APPS_HOST_FIXTURE)
        hkLsLogSince = [[NSDate date] dateByAddingTimeInterval:-2.0];
        int status = hkRegisterStockApps(@(argv[1]), @(argv[2]), (unsigned)attempts);
        if (!hkLsLogDone) { hkLsLogDone = YES; hkDumpLaunchServicesLog(hkLsLogSince); }
        return status;
#else
        return hkRegisterStockApps(@(argv[1]), @(argv[2]), (unsigned)attempts);
#endif
    } @catch (NSException *exception) {
        (void)exception;
        receipt(@{@"event": @"error", @"reason": @"workspace_exception"}); return 3;
    } }
}
#endif
#endif
