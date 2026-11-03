# root-r5: phone root r4 + stock resources r3's prune removed (Phone/About/AX bundles + the int3 crash-stack set) (2026-11-03, m1box + Mac; no phone)

Labels: **HOST** (m1box/Mac build and checks), **QEMU** (m1box TCG), **PHYS** (the int3 live boot's console, read only; this
work did not touch the phone). Large files stay on m1box under `/data/hackios-qemu/research/ios26-apps-r1/root-r5/` (`$S`). This
directory holds the tools and the small receipts.

## 0. Result

| Item | Value |
| --- | --- |
| Raw root `$S/out/ios26-phone-r5.img` | **b7f41eedc29617b500100d2611f7013dbf9f14a3ecea33c02c2d15cc2bd01bbd**, 25,769,803,776 B = 6,291,456 × 4 KiB = the whole ios_system (r4 geometry) |
| Sparse `$S/out/ios_system-phone-r5.simg` | **8b0d2d8c8f960c134e86482a1bb32b10ab2232d0f469db540c82e28db8cacfd9**, 9,198,547,168 B, 21,957 chunks (RAW 2,245,664, FILL-0 4,045,792) |
| Expected readback of the whole extent (padded sha256) | **b7f41eed…1bbd** (= raw; tail 0) |
| Rollback | r4: `ios_system-phone-r4.simg` 00be36b1…21a1, readback a6574777…6abc. r4 is on the phone now (`ios26-dualboot-r8/attempts/a7r4-flash/readback.txt`) |
| Change vs r4 | +1,201 stock files (0 new dirs); 7 replaced files: 6 from the MobilePhone.app re-sign, plus `private/var.skel.tsv`; 0 removed. The other 292,544 r4 entries are identical in path, type, mode, uid, gid, size, nlink, mtime and sha256 (`receipts/verify-r5.json`, 0 problems). r4's 49 staged apps are unchanged |
| fsck.hfsplus -f -n | OK before and after the insert |
| GPT check | `option-a-ios24+8` unchanged. **OK**: entry 36, LBA 22,757,376..29,048,831, 6,291,456 blocks, tail 0, simg expands to b7f41eed… (`receipts/check-host-a7r4dump.txt`, against the 22:11 dump in `attempts/a7r4-flash/`) |
| QEMU (20 GiB twin `r5q20-logmirror.img` 5d8e1596…, = r5 + the 4 QEMU-only logmirror plists) | §5 |

A first build of r5 (v1: 510ff808…, the Phone/About/AX set only) was superseded the same evening by the int3 evidence. It is
kept in `$S/v1/` and its QEMU run is `runs/root-r5-q-r5q20v1`. Do not flash it.

## 1. Restore set, and the evidence for each part

Source: the stock 23G90 OS volume (`apple/23G90/094-95981-090.dmg`), attached on the Mac `-readonly -nobrowse -owners on`.
`tools/stage_r5_mac.py` copies data, owner, group, mode and mtime only (no xattrs, no compression). It writes `files.tsv`
with each file's sha256.

| Part | Files | Evidence |
| --- | --- | --- |
| A. Phone/About/AX bundles (`r5-files.tar` 2a9eed19…) | 141 (9.0 MB) | `ios26-phaseb-r1/about/receipts/r5-filelist.txt` (19 files; sha256 prefixes match), completed to every stock file missing from those 9 bundles (`receipts/inspect-r4.txt`). Includes `MobilePhone.app/Assets.car` and the Assets.car of CallsDialer/CallsAppUI/TelephonyUI/ConversationKit/CommunicationsUI/ContactsUI. Also includes MusicLibrary's `MLSortMapTables.plist` and `SortingDetails.plist` **at the framework root**, all its `*.lproj/MLSections.plist`, and AXSS's `.mom`/`.omo`/plists |
| B. MobileSMS (`r5b-files.tar` a5ee096a…) | `Frameworks/LinkPresentation.framework/Assets.car` (253,208 B) | PHYS int3: MobileSMS SIGABRT `Trying to create an LPImage with nil data` from a UIKit/CoreAutoLayout layout pass (`receipts/int3-stacks.txt`). This is LinkPresentation's only pruned file |
| C. FaceTime (same tar) | `PrivateFrameworks/OnBoardingKit.framework/Assets.car` (68,904 B) + every pruned file of `System/Library/OnBoardingBundles` (345 files, 178 MB: 115 Info.plist + each bundle's plist/loctable; `com.apple.onboarding.facetime.bundle` had only empty lproj dirs) | PHYS int3: FaceTime SIGABRT `-[__NSSetM addObject:]: object cannot be nil`, thrown in OnBoardingKit (+0x2328/+0x1bd0/+0x1a88/+0x3d740) after a notification post |
| D. AppPlaceholders class (same tar) | 713 files (75.7 MB) in 194 placeholder bundles: Info.plist, PlaceholderEntitlements.plist (stock 501:501), InfoPlist.loctable, Assets.car, icons, json | PHYS int3 HKL mirror: `lsd: Info.plist missing at /System/Library/AppPlaceholders/Music.app/Info.plist`. The prune left only directories |
| E. `/private/var/mobile/Media/iTunes_Control` (+`/iTunes`), as 2 rows in `private/var.skel.tsv` (`skel.tar`, `receipts/var-skel.diff`) | — | PHYS int3: **Preferences (About) SIGABRT `NSGenericException 'iTunesControlDoesNotExist /private/var/mobile/Media/iTunes_Control does not exist'`**, thrown in MusicLibrary under MediaPlayer, from GeneralSettingsUI. The stock OS volume has no such directory (it is made at runtime). varfs builds `/var` from `var.skel.tsv`, so the root carries it. Mode 755 and owner mobile:mobile (501) are INFERENCE |

- B, C and D: 1,060 files, 254 MB. 0 Mach-Os, 0 seal files, and no bundle with an executable gains a file (`tools/exe_check.py`), so nothing needs re-signing.
- Not restored: the 7 other apps INT3.md §6 names from int2 (Health, Photos, Freeform, Journal, VoiceMemos, Magnifier,
  AppleVisionProApp). They did **not** crash in the int3 boot, so there are no stacks naming a file. After r5, 351 framework
  Assets.car files (399 MB) remain pruned, plus about 181,800 other files (`receipts/still-missing-summary.txt`).
- Also not restored: the ExtensionKit appexes lsd reports (`BatterySettingsIntentsExtension` and others). The prune removed them
  whole, Mach-Os included, so they are code. Restoring them needs r3's macho stage.

## 2. Code signatures (Mac, `tools/reseal_r5_mac.py`, r3's `build-r3/tools/renegade/pacstrip.py` unmodified)

- In r3, the prune ran before the macho stage's re-sign, so r4's `MobilePhone.app` seal covers the pruned bundle (38 entries, no Assets.car). Stock iOS seals list almost nothing (stock MobilePhone `files2` = 2).
- r5 re-signs with `pacstrip.sign`, deepest first; identifier, entitlements and CS options are kept and checked:
  - `…/VoicemailMessageNotificationExtension.appex/Frameworks/CallsDialer.framework/CallsDialer`;
  - `VoicemailMessageNotificationExtension`;
  - `MobilePhone`.
- Changed files: these 3 Mach-Os and their 3 CodeResources (`changed.tar` 3f26ff94…).
- **`codesign -v --deep Applications/MobilePhone.app` passes** (`receipts/reseal-mac.json`). In r4 it fails ("a sealed resource is missing or invalid").
- **r3 hard-links one 1,798-byte `CodeResources` (sha 344242…) into about 4,880 paths** (nlink 4873–4879).
  - Every r3 re-sign rewrote that shared file, so the 7 ContactsUI appex/xpc bundles already fail `codesign -v` in r4.
    r4 boots to Home, so this seal state does not block the boot. r5 leaves those 7 bundles exactly as in r4.
  - A replace through a hard link on Linux hfsplus breaks the link count: the first build failed fsck with "Incorrect number of
    file hard links" (`receipts/build-attempt1-fsck-excerpt.txt`; image discarded).
  - `insert_r5.py` now refuses to replace any nlink > 1 file, and the reseal skips bundles whose seal is shared.

## 3. Build (m1box)

- `tools/build_r5.sh BASE BASE_SHA OUT` runs these steps:
  1. Check the hashes of r4 and the four tars.
  2. Reflink copy, then fsck.
  3. Mount rw (hfsplus, nls=utf8, noatime) in the privileged container.
  4. `insert_r5.py`:
     - creates each restored file, refusing any that already exists;
     - replaces the 7 files by unlink + create, with r4's owner and mode;
     - puts the touched parents' r4 times back.
  5. fsck again.
  6. `sync_alt_vh.py` (root-r4).
- `verify_r5.py` diffs the r4 and r5 censuses against the inputs.
- `ipf_r5.py` is `tools/ios_partition_flash.py` with its root pin set to r5. It runs `sparse` and `check`.
- Not byte-reproducible: HFS dates come from the build time.

## 4. Owner-approved flash of r5, with r4 as the rollback (attended; the only write is step 3)

Same steps as `root-r4/PLAN.md` §5, with r5's names and hashes. `N=research/ios26-dualboot-r8/attempts/a7r5-flash`.

0. Stage the sparse file on the flash host:
   ```sh
   rsync -a m1box:/data/hackios-qemu/research/ios26-apps-r1/root-r5/out/ios_system-phone-r5.simg research/ios26-dualboot-r8/a7/
   ```
   - sha256 must be 8b0d2d8c…cfd9. It needs about 9.2 GB free.
   - Keep `ios_system-phone-r4.simg` (00be36b1…) as the rollback.
1. In Android, `return-check.sh $N/before`. The ios_system readback must be **a6574777…6abc** (r4). Take fresh LBA 0-7 and tail dumps, as in r4 §5 step 1.
2. On m1box:
   ```sh
   python3 -I research/ios26-apps-r1/root-r5/tools/ipf_r5.py . check \
     --head $N/lba-0-7.bin --tail $N/lba-31146990-31147007.bin --tail-lba 31146990 --total-lbas 31147008 \
     --disk-guid 54494857-4345-4148-5045-4c204c554e31 \
     --root /data/hackios-qemu/research/ios26-apps-r1/root-r5/out/ios26-phone-r5.img \
     --plan research/ios26-dualboot-r8/gpt-plan/option-a-ios24+8 \
     --simg /data/hackios-qemu/research/ios26-apps-r1/root-r5/out/ios_system-phone-r5.simg --out $N/receipt.json
   ```
   Expect `OK` and padded_sha256 b7f41eed…1bbd.
3. Flash (attended):
   ```sh
   adb reboot bootloader
   fastboot getvar partition-size:ios_system   # 0x600000000
   fastboot getvar has-slot:ios_system         # no
   fastboot flash ios_system research/ios26-dualboot-r8/a7/ios_system-phone-r5.simg
   fastboot reboot
   ```
4. Readback in Android:
   ```sh
   adb exec-out su -c 'dd if=/dev/block/by-name/ios_system bs=4M 2>/dev/null | sha256sum'
   ```
   - Expect **b7f41eedc29617b500100d2611f7013dbf9f14a3ecea33c02c2d15cc2bd01bbd**.
   - The GPT head and tail must `cmp` equal to the dumps.
5. `return-check.sh $N/after-flash`. Then boot int3 (`hk_usertrace`+`crashinfo`) as a temporary `fastboot boot`.
   - Acceptance: no `usercrash:`/`userabort:` for Preferences (About), MobileSMS or FaceTime. Phone draws its keypad. AccessibilityUIServer does not abort.
   - Any remaining app crash gives the next stack-driven list.
   - The int2/int3 MusicLibrary and AXSS overlay covers become redundant.

**Rollback (r4):**
```sh
fastboot flash ios_system research/ios26-dualboot-r8/a7/ios_system-phone-r4.simg   # 00be36b1…
```
Readback should then be a6574777105ffd3ec6083cdac519e9b584f78092cab1aed4240ab81822e96abc. Either sparse image rewrites the whole extent.

## 5. QEMU (m1box TCG): QEMU results only

- Route: root-r4's `tools/qemu-launch.sh`, unchanged.
  - Kernel app2 b875e3e3…, overlay `qemu-app2-r1`, 1800 s.
  - Control: `runs/root-r4-q-r4q20`.
  - r5 run: `runs/root-r5-q-r5q20`.
  - The QEMU root is the 20 GiB twin, built by `build_r5.sh` from r4's twin `r4q20-logmirror.img` with the same four tars. Its
    census equals phone r5 except the 4 QEMU-only logmirror plists. The 24 GiB size does not run in QEMU (root-r4 §4).
  - Receipts: `receipts/qemu-intent.json`, `qemu-excerpts.txt`, `qemu-exit.json`, `qemu-home-r5q20.png`.

| | r4 control | **r5** |
| --- | --- | --- |
| root mount | `"ios_system" on LUN 0 … 20480 MiB, read only` | same |
| lsd `Scanned N apps in /Applications` | 253 | **253** (the 49 staged apps and MobilePhone.app, re-signed, still register) |
| lsd `Scanned N apps in /System/Library/AppPlaceholders` | 0 | **49** |
| `Info.plist missing` lines (AppPlaceholders) | 643 (147) | **496 (0)**; the rest are the ExtensionKit appexes (§1, code) |
| usertrap / userabort / usercrash / INVALID_PERSONA / panic(cpu | 0/0/0/0/0 | 0/0/0/0/0 |
| exit, root unchanged | 0, yes | 0, yes |
| Home at the end | 2 widgets, 15 icons, 4 in the dock | **the same layout** (`qemu-home-r5q20.png`) |

- The restored files are on the very image (host census, `verify-r5.json`), e.g. `Applications/MobilePhone.app/Assets.car` 2ef5ba3c….
- QEMU opens no app, so it cannot show whether Phone renders, or whether About, MobileSMS and FaceTime stop aborting. QEMU
  never showed those crashes. Only the phone boot (§4 step 5) answers this.
- Icon art is grey tiles in QEMU, as it was for r4.
- What QEMU does show: r5 boots like r4. lsd registers the same apps plus the 49 placeholders, and nothing new traps, aborts or panics.

## 6. Open

- PHYS only: whether B, C and E are each the whole cause of their crash. Each is the first missing resource on its stack's path. The exact resource name is INFERENCE, since the frames are redacted local symbols.
- The 7 int2-only crashers: they need another int3 boot after r5. The class-wide option (all 351 framework Assets.car files, 399 MB) fits in the 15 GiB free space if wanted.
- `ROOT_SHA` pin in `tools/ios_partition_flash.py`: still r3. Use `ipf_r5.py` until the coordination thread updates it.
- prune.py rule changes for a from-scratch root: see `root-r4/PLAN.md` "next". They are not applied here, since r5 is r4 plus inserted files.
