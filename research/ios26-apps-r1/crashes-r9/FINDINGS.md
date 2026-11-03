# r9 app crashes: MobilePhone launch trap, Preferences NULL read (2026-11-03, m1box, no phone)

Evidence labels: **PHYS** (phone ramdump log), **STATIC** (disassembly of dsc-r6 / the stock binary), **SRC** (our
XNU source). Inferences are marked. Dyld cache `/data/hackios-qemu/dsc-r6` (uuid 0f1ee332…), the same cache the phone's
slides resolve against (every frame lands at a function boundary or a call return).

Inputs:
- r9 log `research/laguna-usb-fix/attempts/20261103-185039-a7-ios-system-r9-apps-ufs/ramdump/kernel.log` (sha256 f78032ae…).
- MobilePhone taken from `apps-logmirror-r14.img` (`/Applications/MobilePhone.app/MobilePhone`, sha256 a9d66eb7…). It is the
  stock Apple binary, assumed identical on ios_system. The extraction was deleted after use.
- Tools: `research/ios26-apps-r1/tools/m1box/dsc_sym.py`, `research/ios26-phaseb-r1/corebrightness/cbdis.py`,
  `llvm-objdump --macho`. The metaclass method lists of CNContactStore/CNAuthorizationContext are *list-of-lists*
  (low bit set on the `class_ro` methods pointer), which `objcmeth.py` does not decode. A 40-line variant handled them.

## 0. Log hygiene (PHYS)

The r9 ramdump holds two boots, each copied twice (lines 1-20976 = lines 20977-end):
- Lines 1-4295 are r9 (launchd 17:51 UTC, slide **0xc50c000**).
- Lines 4296-20976 are leftovers from the earlier boot `a7-wifi-join-r2` (launchd 17:44-17:47 UTC, slide **0xb6a8000**).
  That attempt's own dump shows the identical `usertrap: Preferences[185]` line.
- So the Preferences SIGSEGV is **not an r9 event**, and its slide is 0xb6a8000, not 0xc50c000.
- In r9 itself Preferences[178] was killed by runningboard with `0x8badf00d` (launch watchdog).
  Preferences[195] was still alive at t=259 s (`HK TOP`, 3949 ms CPU).
- In wifi-join-r2, four launches died on 0x8badf00d and one on the SIGSEGV below.

## 1. MobilePhone: Contacts not authorized, so `+[CNContactStore contactStore]` returns nil

Trap `MobilePhone[174] exception 6 (EXC_BREAKPOINT) pc main+0x1e2bc0`. It is the same in all three r9 launches,
and it happens in `applicationDidFinishLaunching:`, not on a tap.

STATIC chain:
1. `main` → UIApplicationMain → `-[MobilePhoneApplication applicationDidFinishLaunching:]` (+0x9f608) →
   `ApplicationServices.favoritesDataSource_Objc` (+0x1e2acc) → **`ApplicationServices.favoritesDataSource.getter`**
   (`$s11MobilePhone19ApplicationServicesC19favoritesDataSource…vg`, 0x1001e2b24).
2. In that getter, `[self contactStore]` is followed by `cbz x0, 0x1001e2bc0`, and 0x1001e2bc0 is `brk #1`.
   That is a Swift force-unwrap of a nil `CNContactStore`.
3. `-[PHApplicationServices contactStore]` returns an ivar set by the init block `-[PHApplicationServices init]_block_invoke`:
   `setContactStore:[CNContactStore contactStore]`.
4. `+[CNContactStore contactStore]` is a category method. CallsDialer 0x249999868 and PhoneKit 0x268c709a8 have the same body:
   `if (![CNContactStore phoneKit_isAuthorized]) { log error; return nil; }`. Otherwise it returns
   `[[CNContactStore alloc] initWithConfiguration:(includeLocalContacts=1)]`.
5. `+phoneKit_isAuthorized` is `[CNContactStore authorizationStatus] == 3` (CNAuthorizationStatusAuthorized).
   `+authorizationStatus` is `authorizationStatusForEntityType:0`. That goes through `CNAuthorization`
   (ContactsFoundation `CNAuthorizationContext`), first checking `isAccessRestrictedForEntityType:`.
6. Then `CNTCCVersion2 checkAuthorizationStatusOfAuditToken:assumedIdentity:` builds
   `tcc_credential_singleton_for_self` and calls `requestAuthorizationWithCredential:messageOptions:` with
   `messageOptionsForSyncNoPrompt`.
   - That is a synchronous TCC v2 request to **tccd** for kTCCServiceAddressBook.

**Failed precondition: tccd does not report kTCCServiceAddressBook = authorized for MobilePhone.** The cause is not
telephony, CommCenter or callservicesd. They are never reached before this trap.

What is known about why:
- MobilePhone *is* entitled. Its XML entitlements (14380 bytes, plus a DER blob 0xfade7172 of 10278 bytes) contain
  `com.apple.private.tcc.allow` = [Microphone, Camera, Calendar, **AddressBook**, FaceID] and `…allow.overridable` = [AddressBook, Photos].
  - SWEET AMFI did not log "unreadable entitlements" for it. It did for chronod (14343 bytes) and deviceaccessd.
  - The kernel serves both the XML (`CS_OPS_ENTITLEMENTS_BLOB`) and the DER (`CS_OPS_DER_ENTITLEMENTS_BLOB`) blob (SRC kern_proc.c).
- tccd ran (r9 line 751, `UserName mobile`). `/private/var` is varfs, built from `private/var.skel.tsv`.
  - The skeleton has **no `/private/var/mobile/Library/TCC`**, so tccd must create the directory and TCC.db at every boot.
  - `/private/var/mobile/Library` is 711 mobile:mobile, so creating them should be allowed.
- *Inference*: the entitlement alone should give "allowed". So the likely failure is inside tccd: database
  creation or open on varfs, identifying the client from its audit token, or the restriction check (step 5,
  ManagedConfiguration). This is not proven. tccd's os_log is not mirrored, and the PhoneKit error line goes to os_log too.

## 2. Preferences (wifi-join-r2): NULL sandbox token from our Sandbox stand-in

`Preferences[185] exception 1 (EXC_BAD_ACCESS) addr 0x0 pc 0x2afab3090 lr 0x2afabbfac, slide 0xb6a8000`, `x1 -> "invalid"`.

STATIC symbolication (unslid = addr - 0xb6a8000):
| frame | location |
| --- | --- |
| pc 0x2a440b090 | libsystem_platform, redacted function +0x40: the string compare that libsandbox calls through its GOT with x1 = `"invalid"`. Strcmp is inferred, because the GOT target is not resolved by our tools. It faults reading x0 = NULL. |
| lr 0x2a4413fac | `sandbox_extension_consume` +0x24: `strcmp(token, "invalid")` |
| 0x1bab5834c | SafariCore `WBSSetUpAccessToAppDataContainerWithIdentifier` +0x15c |
| 0x1c4ef0128 | AuthenticationServicesCore `-[ASFeatureManager init]`: `WBSSetUpAccessToAppDataContainerWithIdentifier(@"com.apple.mobilesafari")` |
| 0x1c4ef0060 / libdispatch | the ASFeatureManager `dispatch_once` |
| 0x113ec45a4, 0x113ec4a30 | not in the cache: a Settings plug-in bundle (not identified) |
| 0x18b7f0b1c, 0x189147c60 | Preferences.framework, UIKitCore |

What `WBSSetUpAccessToAppDataContainerWithIdentifier` does:
1. `container_query_create`, then `set_class(2)`, `set_identifiers([id])`, `operation_set_flags(0x900000000)`,
   `set_persona_unique_string`, `get_single_result`.
2. If there is a result: `token = container_copy_sandbox_token(result)` and `sandbox_extension_consume(token)`.
   There is no NULL check.
3. containermanagerd returned the Safari container **without a token**.

The cause is in our kernel (SRC `bsd/kern/sweet_amfi.c`, `sweet_sandbox_syscall`):
- `case 5: /* extension issue */` and `case 6: /* consume */` return ENOENT by design.
- The log shows `SWEET Sandbox: containermanager op 5`. So every container token containermanagerd hands out is NULL.

The libsystem_sandbox ABI (STATIC):
- `__sandbox_ms("Sandbox", 5, args)` for issue. `args` is 7 u64 words; **word 4 = the user output buffer** (malloc 0x3ff0).
  On failure libsandbox frees that buffer and returns NULL.
- When the caller passes flag bit 0, libsandbox writes the literal token `"invalid"` without a syscall.
- `sandbox_extension_consume` returns 0 without a syscall for `"invalid"`. Otherwise it calls op 6 with
  {token, strlen+1, &handle_out} and returns handle_out, or -1.
- So `"invalid"` is libsandbox's own no-op token. It is exactly the right answer for a kernel that enforces no sandbox.

## 3. Proposed fixes (smallest first)

**F1, Preferences (kernel, ~15 lines, always on). Replaces the NULL token with libsandbox's no-op token.**
In `sweet_sandbox_syscall`, `case 5`:
- `copyin` the 7-word args;
- `copyoutstr("invalid", args[4], 0x3ff0, …)`;
- return 0.

Keep `case 6` (consume) as is (it is never reached for "invalid"). Or make it `copyout` handle 1 to args[2] and return 0.

Effects:
- Every `container_copy_sandbox_token` user gets a non-NULL token: SafariCore, and probably others that
  were silently failing.
- Security trade-off: none beyond today's (nothing is enforced).

Test: host test of the args decode, then the attended boot (`SWEET Sandbox: containermanager op 5` stays, no SIGSEGV).
Does not address the separate Preferences 0x8badf00d launch watchdog (no stack in the log; next step is a spindump
or a mirror of Preferences' main-thread stall).

**F2, MobilePhone, diagnostic first (overlay, no code).** Use the existing logmirror pattern
(`tools/m1box/edit_logmirror_lsd_umd.py`) on label `com.apple.tccd`: set `OS_ACTIVITY_DT_MODE=YES`,
`StandardErrorPath=/dev/console` in `launchd.plist` and the job plist. On the next attended boot, open the Phone app once.
- tccd's AUTHREQ lines name the decision and its reason (DB error, client identity, or restriction).
- Optionally add `/private/var/mobile/Library/TCC` (`d 755 501 501`) to `var.skel.tsv` at the same time.
  It is one line and mirrors stock iOS, but it changes two variables at once. Do it in a second run if F2 alone explains nothing.

**F3, MobilePhone fix, chosen by F2's output:**
- If the database is the problem, seed the directory (above), or seed a TCC.db with an allow row for
  `kTCCServiceAddressBook` / `com.apple.mobilephone` in the varfs skeleton. Build the DB from tccd's own schema,
  not from memory.
- If tccd fails to read the client's entitlements, fix that in the kernel path (csops_audittoken) instead.
- *Not recommended*: patching MobilePhone or Contacts. That breaks the signature and only hides the TCC state that
  Contacts, Phone, Messages and FaceTime all share.

Not causes (STATIC): telephony/CommCenter, callservicesd and the `TUCallProviderManager` / `TUMetadataCache` setup.
They run in the same init block but are not on the trap path.
