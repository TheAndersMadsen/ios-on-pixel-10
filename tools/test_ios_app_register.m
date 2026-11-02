// Real registrar read-back and input policy with fixture LaunchServices objects.
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdio.h>
#if !defined(HK_STOCK_APPS_HOST_FIXTURE)
#error Build host fixtures with HK_STOCK_APPS_HOST_FIXTURE=1; logging must use stderr.
#endif
extern BOOL hkStockAppIsListed(id, NSString *, NSString *);
extern BOOL hkStockAppEntryValid(id);
#if defined(HK_STOCK_APPS_HOST_FIXTURE)
extern void hkStockAppReceiptFixture(void);
extern NSArray *hkStockAppOrderFixture(NSArray *, NSArray *);
extern void hkStockAppExerciseFixture(id, NSString *, NSSet *, NSMutableSet *, BOOL);
#endif

@interface AppRecord : NSObject
@property NSString *applicationIdentifier;
@property NSURL *bundleURL;
@property BOOL isInstalled;
@property BOOL isPlaceholder;
@end
@implementation AppRecord
@end
@interface Workspace : NSObject
@property id allApplications;
@end
@implementation Workspace
@end
@interface ThrowingWorkspace : NSObject
- (id)allApplications;
@end
@implementation ThrowingWorkspace
- (id)allApplications {
    @throw [NSException exceptionWithName:@"EnumerationFixture" reason:@"fixture" userInfo:nil];
}
@end
@interface LaunchWorkspace : Workspace
@property NSMutableArray *opened;
- (void)openApplicationWithBundleID:(NSString *)identifier;
@end
@implementation LaunchWorkspace
- (void)openApplicationWithBundleID:(NSString *)identifier { [self.opened addObject:identifier]; }
@end

int main(void) {
    @autoreleasepool {
#if defined(HK_STOCK_APPS_HOST_FIXTURE)
        hkStockAppReceiptFixture();
#endif
        NSString *identifier = @"example.clock", *path = @"/Applications/Clock.app";
        AppRecord *record = [AppRecord new];
        record.applicationIdentifier = identifier;
        record.bundleURL = [NSURL fileURLWithPath:path];
        record.isInstalled = YES;
        Workspace *workspace = [Workspace new]; workspace.allApplications = @[record];
        assert(hkStockAppIsListed(workspace, identifier, path));
        assert(!hkStockAppIsListed(workspace, @"example.other", path));
        assert(!hkStockAppIsListed(workspace, identifier, @"/Applications/Other.app"));
        record.isPlaceholder = YES;
        assert(!hkStockAppIsListed(workspace, identifier, path));
        record.isPlaceholder = NO; record.isInstalled = NO;
        assert(!hkStockAppIsListed(workspace, identifier, path));
        record.isInstalled = YES; workspace.allApplications = @[];
        assert(!hkStockAppIsListed(workspace, identifier, path));
        workspace.allApplications = @[NSNull.null];
        assert(!hkStockAppIsListed(workspace, identifier, path));
        workspace.allApplications = NSNull.null;
        assert(!hkStockAppIsListed(workspace, identifier, path));
        BOOL propagated = NO;
        @try {
            (void)hkStockAppIsListed([ThrowingWorkspace new], identifier, path);
        } @catch (NSException *exception) {
            propagated = [exception.name isEqual:@"EnumerationFixture"];
        }
        assert(propagated); // A missing API return must not emit a return receipt.
        assert(hkStockAppEntryValid(@{@"bundle_id":identifier, @"path":path}));
        for (id bad in @[
            NSNull.null, @{}, @{@"bundle_id":@5, @"path":path},
            @{@"bundle_id":identifier, @"path":@"/Applications/../Clock.app"},
            @{@"bundle_id":identifier, @"path":@"/Applications/Clock.app/Other.app"},
            @{@"bundle_id":identifier, @"path":@"/private/var/Clock.app"},
            @{@"bundle_id":identifier, @"path":@"/Applications/Clock"}]) {
            assert(!hkStockAppEntryValid(bad));
        }
        NSArray *entries = @[@{@"bundle_id":@"example.phone"}, @{@"bundle_id":@"example.clock"},
                             @{@"bundle_id":@"example.settings"}, @{@"bundle_id":@"example.notes"}];
        NSArray *ordered = hkStockAppOrderFixture(entries, @[@"example.notes", @"example.clock"]);
        assert(([ordered isEqual:@[entries[3], entries[1], entries[0], entries[2]]]));
        assert(ordered.count == entries.count && [[NSSet setWithArray:ordered] isEqual:[NSSet setWithArray:entries]]);
        LaunchWorkspace *launcher = [LaunchWorkspace new]; launcher.opened = [NSMutableArray array];
        NSSet *selected = [NSSet setWithArray:@[identifier, @"example.notes"]];
        NSMutableSet *requested = [NSMutableSet set];
        hkStockAppExerciseFixture(launcher, identifier, selected, requested, NO);
        hkStockAppExerciseFixture(launcher, @"example.other", selected, requested, YES);
        assert(launcher.opened.count == 0 && requested.count == 0);
        hkStockAppExerciseFixture(launcher, identifier, selected, requested, YES);
        hkStockAppExerciseFixture(launcher, identifier, selected, requested, YES);
        hkStockAppExerciseFixture(launcher, @"example.notes", selected, requested, YES);
        assert(([launcher.opened isEqual:@[identifier, @"example.notes"]] && requested.count == 2));
        NSMutableSet *unsupported = [NSMutableSet set];
        hkStockAppExerciseFixture([NSObject new], identifier, selected, unsupported, YES);
        assert(unsupported.count == 0);
        puts("PASS: fresh LS readback, propagated enumeration exception, retained entry order, verified selected one-time requests (fixtures only)");
    }
}
