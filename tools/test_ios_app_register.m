// Real registrar read-back and input policy with fixture LaunchServices objects.
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdio.h>
extern BOOL hkStockAppIsListed(id, NSString *, NSString *);
extern BOOL hkStockAppEntryValid(id);
#if defined(HK_STOCK_APPS_HOST_FIXTURE)
extern void hkStockAppReceiptFixture(void);
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
        assert(hkStockAppEntryValid(@{@"bundle_id":identifier, @"path":path}));
        for (id bad in @[
            NSNull.null, @{}, @{@"bundle_id":@5, @"path":path},
            @{@"bundle_id":identifier, @"path":@"/Applications/../Clock.app"},
            @{@"bundle_id":identifier, @"path":@"/Applications/Clock.app/Other.app"},
            @{@"bundle_id":identifier, @"path":@"/private/var/Clock.app"},
            @{@"bundle_id":identifier, @"path":@"/Applications/Clock"}]) {
            assert(!hkStockAppEntryValid(bad));
        }
        puts("PASS: fresh LS enumeration, placeholder/install/path checks, manifest path policy (fixtures only)");
    }
}
