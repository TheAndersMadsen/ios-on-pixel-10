# about: Settings > About abort, AccessibilityUIServer and MessagesBlastDoorService crash loops, Phone white screen (2026-11-03, HOST, not booted)

Labels: **PHYSICAL** = the int1 phone boots (live console `research/laguna-usb-fix/attempts/live-20261103-213954-a7-int1-live/console.txt`,
earlier ramdumps named below), **STATIC** = disassembly of the 23G90 dyld cache (`/data/hackios-qemu/dsc-r6`, uuid 0f1ee332…) or files
of the r3 root / stock 23G90 system volume, **HOST** = builds and host tests, **INFERENCE** = not observed. Nothing here touched the phone.

## Result

| Artifact | sha256 / id |
| --- | --- |
| XNU branch **`hk-int2-about`** (Mac nested repo) | **`48b613bae1245516ef8197f9c0f4ddbc09963836`**, one commit on hk-int1 484717f |
| `kernel.int2-about` / `.unstripped` | `c2ec7b75cd67a48f8839ea5590d7b0f4f7362b775b9f45da9bfdbce76d0b5861` / `56ebe555577c8977018f9042dbf0ad4c8fadebc0ac868d5fd7dacbac1ba281d4` |
| overlay **`int2-about-r1.ovl`** (675,432 B, 65 records = int1-r1's 52 + 13) | `edbd799a3bc1651b03e3e4eb0bec0024aac69a80a663541104052543a3f795af` |
| **`a7-ios-system-int2`** boot.img | **`d4e3f129f4959fb48e66b588307443d987b76ae635ec47bc2d498d7d07ed7951`** (payload b048defe…, margin 39,915,616 B) |

`check`: `OK a7-ios-system-int2 bootable d4e3f129…` with `image_tool_int1.py` and the shared `tools/image_tool.py` (Mac), and the shared
tool on m1box. Boot-arg line **identical to int1's** (1018 B, 56 tokens): **0 bytes added**. Manifest differs from int1 only in kernel,
overlay, sizes/offsets and per-build ids (`receipts/manifest-diff.txt`).

| Problem | Cause | Fix | Evidence |
| --- | --- | --- | --- |
| About: `CRASH Preferences reason ns 2 code 0x6` | MusicLibrary asserts `Unable to load MLSortMapTables.plist at %@` (ML3MusicLibrary.m:2192); r3's prune deleted the plist | overlay cover `ml-en` | PHYSICAL timing (3 of 3 About taps) + STATIC; abort stack not captured |
| AccessibilityUIServer, every ~10 s, SIGABRT | uncaught `NSInvalidArgumentException` "Cannot create an NSPersistentStoreCoordinator with a nil model": prune deleted `AXSSPunctuationModel.mom` | overlay covers `ax-punct`, `ax-vopron` | PHYSICAL (earlier `usercrash:` text + `userabort:` stack) + STATIC |
| MessagesBlastDoorService, every 10 s, SIGTRAP | `BlastDoor/Sandbox.swift`: `sandbox_check(getpid(), NULL, 0) != 1` → `fatalError("BlastDoor cannot run unsandboxed.")`; the SWEET stub never reports "sandboxed" | kernel 48b613b (op 2 self-query) | STATIC + host test; crash only since int1 (callservicesd/CallKit now get that far) |
| Phone: white screen, no dialer, no recents | **not TCC, not sandbox.** Main thread idle in the run loop; the prune's `car` rule deleted the Assets.car of MobilePhone.app and of the 5 Calls/Telephony UI frameworks it draws from | **root r5** (too many directories for the 8 covers); list in `research/ios26-apps-r1/root-r4/PLAN.md` §next | PHYSICAL (stacks, TCC grants) + STATIC (files); cause INFERENCE |

## 1. Settings > About abort

**Verified:** ns 2 = `OS_REASON_SIGNAL`, code = signal number, so 0x6 = SIGABRT (and BlastDoor's 0x5 = SIGTRAP).

**PHYSICAL, int1 live boot.** Preferences[184] starts at 41.16 (`HKMAIN … watching the main thread`). The owner's About tap is at 50.21.
Then tccd logs a `TCCAccessRequest` from pid 184 for **`kTCCServiceMediaLibrary`** (preflight). It is granted by entitlement
(`com.apple.private.tcc.allow`, `auth_value=2`, `issuing both generic and file extension due to policy`,
`generic_extension="invalid"`). `REPLY` is at 50.75, and `CRASH Preferences reason ns 2 code 0x6` at 50.75, in the same millisecond.
The second About visit in this boot (Preferences[1385], console line 6161) and the earlier int1 boot (20261103-205514, pid 1646) show the
same sequence: MediaLibrary request, grant, SIGABRT. The About page's first and only TCC request is MediaLibrary, for the
Songs/Videos/Photos counts.

**hk_ustack:** Preferences' main thread is idle in `GSEventRunModal` → `mach_msg2_trap` in rounds 1 and 2 (43.12, 48.21). The abort
falls between two 5 s samples, so there is no stack of the aborting thread. int1 dropped `hk_usertrace=1`, which also gates the
`userabort:` trace in `__pthread_kill(SIGABRT)` (hk-int1 `osfmk/arm64/hk_user_trace.c`).

**Not TCC.** `TCC.framework`'s reply handler (0x1b3928ba8) consumes `extension` and `generic_extension` with `sandbox_extension_consume`.
A failure (`cmn x0, #1`) becomes a CFError, never an abort, and libsandbox consumes `"invalid"` with no syscall (app2/FIX.md §1).
**No TCC rule is needed.**

**STATIC, the abort.** MusicLibrary 0x2331b2fc0 runs `[[NSBundle bundleForClass:] pathForResource:@"MLSortMapTables" ofType:@"plist"]`
and `dictionaryWithContentsOfFile:`. On nil it calls `[NSAssertionHandler handleFailureIn…:@"ML3MusicLibrary.m" lineNumber:2192
description:@"Unable to load MLSortMapTables.plist at %@"]`. The cfstrings are 0x284260f80/fa0/3e0/fc0. The result is an uncaught
`NSInternalInconsistencyException`, then abort, then SIGABRT. On the r3 root (Mac `/tmp/hk-live-root`, read only),
`MusicLibrary.framework` holds only `Info.plist`, `Support/medialibraryd`, `_CodeSignature` and empty `*.lproj`. Stock 23G90 also has
`MLSortMapTables.plist` (1,218 B), `SortingDetails.plist` (93 B; 0x2330722f8 loads it the same way) and `en.lproj/MLSections.plist`.
Cause: `research/ios26-root-r1/scripts/prune.py` `DENY` matches `Frameworks/Music…` and deletes every non-Mach-O file except
Info/version plists (`deny-framework-data`). INFERENCE, not observed: that MediaPlayer reaches ML3MusicLibrary within that millisecond.
Which call failed comes from the code and the file, not from a stack.

**Fix (overlay):** cover `ml-en` mounts a ramfs over `MusicLibrary.framework/en.lproj` holding the three stock files. NSBundle's
`pathForResource:ofType:` searches the current localisation's lproj, and the overlay's `.GlobalPreferences.plist` sets
`AppleLanguages` to en. Covering the framework directory itself would hide `Support/medialibraryd`, which launchd starts from there.

## 2. Phone white screen

- **PHYSICAL:** MobilePhone[216] is exec'd at 52.04. tccd **grants** both `kTCCServiceAddressBook` requests (216.1, 216.2) by
  entitlement; there is no denial and no sandbox failure. hk_ustack rounds 1-8 (53.16 → 88+ s): the main thread is in
  `_UIApplicationMain` → `GSEventRunModal` → `mach_msg2_trap`, `PortReceive`, cpu +0 from round 3. It is **idle, not blocked**
  on CallHistory, Contacts, CommCenter or InCallService. One worker in round 1 runs TipKit → libswiftCore. Threads 12 → 3. No crash.
- **STATIC:** relative to stock, the r3 root lacks `Applications/MobilePhone.app/Assets.car` (1,829,272 B) and the `Assets.car` of
  `CallsDialer` (629,896), `CallsAppUI` (31,768), `TelephonyUI` (60,584), `ConversationKit` (974,296), `CommunicationsUI` (71,928)
  and `ContactsUI` (288,712), all linked by MobilePhone (`otool -L`). It also lacks the appex's own `CallsDialer.framework/Assets.car`.
  The prune's `car` rule deletes every `.car` not in `KEEP_CAR`; Settings survives because `Preferences|Settings` is in it.
- **INFERENCE:** an app whose images and named colours all come from missing catalogs draws white: keypad glyphs, tab icons, the
  recents cell styling. That matches "no dialer, no recents" with an idle main thread. **Not TCC, not sandbox.**
- **Fix: root r5.** Six directories plus the app would need 7 covers, and only 4 are free after this overlay. Each would also have to
  carry the directory's other files. The list is in `research/ios26-apps-r1/root-r4/PLAN.md` §next, with the prune-rule change.

## 3. AccessibilityUIServer loop

- **PHYSICAL**, 10× in this boot and 20-46 per boot since r3. Earlier boots with `hk_usertrace=1 hk_crashinfo=1` (e.g.
  20261102-084446-bench-g1-r1, 20261102-115426-phone-p29-…) print `usercrash: AccessibilityUIS[N] CoreFoundation: "*** Terminating app
  due to uncaught exception 'NSInvalidArgumentException', reason: 'Cannot create an NSPersistentStoreCoordinator with a nil model'"`.
- **pwr1's `userabort:` stack** (slide 0xec70000), symbolicated: `abort` ← libc++abi terminate ← `objc_exception_throw` ← CoreData
  0x185bff6c0 ← AccessibilitySharedSupport 0x1c3bc1e6c (the function logging `Set up database for punctuation: %@`) ← dispatch_once
  ← AccessibilityUIService 0x24482eba8.
- **STATIC:** the model is `AXSSPunctuationModel` (`URLForResource:withExtension:` "momd"). On r3 the `.momd` directory holds only
  `VersionInfo.plist` (byte-identical to stock); `AXSSPunctuationModel.mom` (4,658 B) is gone, and so is `VOPronunciationModel.mom`.
  The cause is the same `deny-framework-data` rule: it keeps `*version*.plist` and deletes the model.
- **Fix:** covers `ax-punct` and `ax-vopron`, each with the momd's two stock files. VOPronunciation is the same pattern, covered so that it
  does not become the next abort.

## 4. MessagesBlastDoorService loop

- **PHYSICAL:** `exec MessagesBlastDoorService`, `EXC_GUARD AST: type=0x1 flavor=0x0 …`, `CRASH MessagesBlastDoo reason ns 2 code 0x5`,
  every 10 s. It happens **0 times in every boot r3 … gpu2 and 20 in int1 (205514)**: int1 is the first image where callservicesd and
  CallKit request it (launchd `Service stub initialized … callservicesd`).
- **STATIC, BlastDoor 0x218a63fb4:** `getpid()` → `sandbox_check(pid, NULL, 0)` (0x218a6414c). `!= 1` → `fatalError("BlastDoor cannot run
  unsandboxed.", BlastDoor/Sandbox.swift)` → `brk #1` = SIGTRAP, matching code 5. Then `sandbox_enable_state_flag("blastdoor-post-launch",
  audit token)` = `__sandbox_ms("Sandbox", 0x41)`, which SWEET already answers 0 (= success).
- **libsystem_sandbox:** `sandbox_check` 0x2a4413b70 → 0x2a44138e8 passes `{&result, (s64)pid, op, type, …}` to op 2 and returns
  `result != 0`. SWEET's op 2 returned 0 without writing, so every process looks unsandboxed.
- The binary's entitlements (r3 root, `codesign`) include `com.apple.private.sandbox.profile:embedded = blastdoor-messages`.
- **Fix (kernel 48b613b, `bsd/kern/sweet_amfi.c`, `sweet_sandbox_check.h`):** op 2 writes 1 only for a self-query (op NULL, type 0, the
  caller's own pid) from a process whose embedded profile starts with `blastdoor`. Every other check is unchanged. It logs once per
  process, 16 lines at most.
- **HOST:** `tools/test_sandbox_check.c` (ASan/UBSan) PASS 11/0, 5/5 mutations killed. Single-file ARM64 compile with the kernel's own
  command line (`receipts/cc_amfi.txt`). Linked kernel: `_sweet_sandbox_syscall` has the `cmp w19,#2` path → `copyin` → pid compare →
  `_IOCurrentTaskGetEntitlement` → "blastdoor" byte compares. The symbol delta vs int1 is only `_sweet_sandbox_self_logged` plus two
  line-renamed startup entries; 0 undefined; every int1 feature string present (`receipts/kernel-verify.txt`).
- **Open:** EXC_GUARD flavor 0 (no `kGUARD_EXC_*`) goes through the IPC security-policy path. It is non-fatal in these boots (the signal is
  the SIGTRAP), may keep logging, and is not addressed.

## 5. Build

- **XNU:** branch `hk-int2-about` was made in a throwaway worktree (`/tmp/hk-int2-about-wt`, since removed).
  `tools/build_int2_about.py` is build_int1.py with the names changed: it took the exclusive `/tmp/fleet/kernel-build-slot.lock`, ran
  `mk.sh -j8` (rc 0), then **restored p1 b228c4f and rebuilt it** (rc 0, obj kernel 2743529f…, no hk_ustack string).
  Receipt: `receipts/build_int2_about.out`.
- **Overlay:** `tools/about_overlay.py` pins int1-r1 c440b6ea, keeps its 52 records byte for byte and in order, and appends 13 records in
  group 19. That group is already in `hk_overlay=0xA0080081` and already holds int1's `coreui-colour` cover, which works on the phone:
  `hkcover: 1 of 1 covers from the overlay`. Stock inputs are hash-pinned; they come from the read-only stock volume
  `apple/23G90/094-95981-090.dmg`, copied into `build/stock/` (not for git).
  hk-int1's own `hkov_check` / `hkov_groups` / `hkov_cover_check` (`tools/check_overlay.c`): ok, 65 entries, covers 4 (int1: 1),
  mask ⊆ groups (`receipts/overlay-check.txt`). Covers used: **4 of 8** (`HKOV_COVERS_MAX`).
- **Image:** `tools/mkimg_int2.sh` is mkimg_int1.sh with only the kernel and overlay changed (same tool `image_tool_int1.py` 728bdd21…,
  same flags, line and `--drop-diag`).

Overlay rows added (for the int2 merge; they go after int1-r1's 52 records; renaming the cover heads is free):
```
l g19 /private/var/hkcover/ml-en.cover -> /System/Library/PrivateFrameworks/MusicLibrary.framework/en.lproj
d g19 /private/var/hkcover/ml-en
f g19 /private/var/hkcover/ml-en/MLSortMapTables.plist 1218 B 148e53436ca9
f g19 /private/var/hkcover/ml-en/SortingDetails.plist 93 B 03bd240165c5
f g19 /private/var/hkcover/ml-en/MLSections.plist 286 B 94b84f64a659
l g19 /private/var/hkcover/ax-punct.cover -> /System/Library/PrivateFrameworks/AccessibilitySharedSupport.framework/AXSSPunctuationModel.momd
d g19 /private/var/hkcover/ax-punct
f g19 /private/var/hkcover/ax-punct/VersionInfo.plist 515 B 8c47bb03b7c5
f g19 /private/var/hkcover/ax-punct/AXSSPunctuationModel.mom 4658 B be65ed3dbb69
l g19 /private/var/hkcover/ax-vopron.cover -> /System/Library/PrivateFrameworks/AccessibilitySharedSupport.framework/VOPronunciationModel.momd
d g19 /private/var/hkcover/ax-vopron
f g19 /private/var/hkcover/ax-vopron/VersionInfo.plist 447 B aaeadeb44b04
f g19 /private/var/hkcover/ax-vopron/VOPronunciationModel.mom 5346 B a222edc158c5
```

## 6. Expected log lines (first boot of a7-ios-system-int2)

- `varfs-overlay: mask 0xa0080081 of groups 0xf8ffffff, 65 entries, 675432 bytes, hash 9e729b7e3b9355bf`
- `hkcover: /System/Library/PrivateFrameworks/MusicLibrary.framework/en.lproj, 3 entries, 1597 bytes`;
  `hkcover: …/AXSSPunctuationModel.momd, 2 entries, 5173 bytes`; `hkcover: …/VOPronunciationModel.momd, 2 entries, 5793 bytes`;
  `hkcover: 4 of 4 covers from the overlay`. These follow the format of int1's coreui line; INFERENCE until booted.
- `SWEET Sandbox: MessagesBlastDoorService[N] self-check: sandboxed (profile blastdoor-messages)`, then **no**
  `CRASH MessagesBlastDoo`. `EXC_GUARD AST … flavor=0x0` may stay.
- **No** `CRASH AccessibilityUIS` (int1: 10 in about 4 min). AccessibilityUIServer stays up (one `exec`, not one per ~10 s).
- About: after the tccd `REPLY … msgID=<Preferences pid>.1` for `kTCCServiceMediaLibrary`, **no** `CRASH Preferences`. The page lists
  Name/Version/Model; the Songs/Videos counts read 0. hk_ustack keeps sampling Preferences.
- Phone: unchanged white screen expected (needs r5). The read-out is MobilePhone's idle main thread, as in int1.
- If About still aborts, the next boot needs `hk_usertrace=1 hk_crashinfo=1` (29 B) for the `userabort:`/`usercrash:` text; the line has
  5 B left, so another token must go.

## Files

`FIX.md`; `src/sweet_sandbox_check.h` (the copy committed in 48b613b); `tools/`: `apply_ssc.py`, `test_sandbox_check.c`, `cc_amfi.py`,
`build_int2_about.py`, `about_overlay.py`, `check_overlay.c`, `mkimg_int2.sh`; `receipts/`: `test_sandbox_check.txt`, `cc_amfi.txt`,
`xnu-commit-msg.txt`, `build_int2_about.out`, `kernel-verify.txt`, `overlay.json`, `overlay-check.txt`, `r5-filelist.txt`,
`inputs-verify.txt`, `image_tool.sha256`, `image-build.txt`, `image-check.txt`, `manifest-diff.txt`, `SHA256SUMS`.
`build/` (kernels, objects, overlay, stock Apple files) is derived and not for git.
