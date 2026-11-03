# root-r4: phone root r3 + the 49 stock app bundles, for ios_system (2026-11-03, m1box + Mac; no phone)

Labels: **HOST** (m1box/Mac build and checks), **QEMU** (m1box TCG), **PHYS** (earlier phone receipts only; nothing
here touched the phone). Large files stay on m1box under `/data/hackios-qemu/research/ios26-apps-r1/root-r4/`
(`$S` below); this directory holds the tools and the small receipts.

## 0. Result

| Item | Value |
| --- | --- |
| Raw root `ios26-phone-r4.img` (`$S/out/`) | **a6574777105ffd3ec6083cdac519e9b584f78092cab1aed4240ab81822e96abc**, 25,769,803,776 B = 6,291,456 × 4 KiB = the whole ios_system |
| Sparse for `fastboot flash ios_system` (`$S/out/ios_system-phone-r4.simg`) | **00be36b117381ec8111a06591efd85ea216fb29429bdd1a91434e78542de21a1**, 8,930,000,700 B, 21,927 chunks (RAW 2,180,101 blocks, FILL-0 4,111,355) |
| Expected on-phone readback of the whole extent (padded sha256) | **a6574777…6abc**: the same as the raw image, since the volume fills the partition and there is no zero tail |
| Base | r3 `ios26-phone-r3.img` 205cb0e2… (pulled from the Mac, hash checked) |
| Change | volume 2,097,152 → 6,291,456 blocks (free 528 MiB → 15.4 GiB); 49 bundles in `/Applications` (18,438 entries: 12,498 dirs, 5,940 files, 0 links) |
| Everything r3 ships | **unchanged**: 274,113 of 274,113 r3 entries identical in path, type, mode, uid, gid, size, nlink, mtime and sha256; 0 removed; attributes B-tree 259,471 records in both (no xattr added) |
| fsck.hfsplus -f -n | OK after the grow, OK after the insert |
| QEMU (20 GiB twin, same content) | lsd: 253 apps in /Applications (r3: 204); Home shows the full stock grid (r3: Settings + Phone only); 0 traps/panics |

## 1. What r3 lacked and where the bundles come from (HOST)

- r3's prune policy (`ios26-root-r1/scripts/prune.py`, TREES) drops `private/var/staged_system_apps` and the files of
  `System/Library/AppPlaceholders`. That is why only Settings and Phone are on Home (app2/FIX.md §3).
- Source: the IPSW OS volume `apple/23G90/094-95981-090.dmg` (BuildManifest `OS`), attached read-only on the Mac
  (`hdiutil -readonly -nobrowse -owners on`); `/private/var/staged_system_apps`: 49 bundles.
- **apps-full-r6's copies were not used.** The QEMU roots carry a Mac-copy artifact: owners 501:501, 501:20 and 0:0
  mixed by accident, a `com.apple.provenance` xattr on every entry, and `codesign --deep` reseals.

## 2. Build (HOST): r3's own semantics, tools in `tools/`

1. `stage_apps_mac.py` (Mac): copies with r3's `prune_copy` semantics (data and mode only, no xattrs, no HFS
   compression, hard links kept), but **without** `prune.decide()` and **without** loctable slimming, so every bundle
   is complete (icons in `Assets.car`, all lproj). Then r3's macho stage, verbatim: the `mkroot-full.py` worker with
   r3's own `build-r3/tools/renegade/pacstrip.py`.
   - 236 Mach-Os: 231 rewritten, 5 clean, 0 failed, 0 identity (identifier/team) mismatches.
   - The dry re-scan finds nothing left to rewrite. `receipts/macho.json`, `stage-mac.log`.
2. `reseal_mac.py` (Mac): the parallel pool had sealed some outer apps before their PlugIns were re-signed, so 29 of 49
   bundles failed `codesign -v`. I re-signed the 231 rewritten Mach-Os once more, sequentially, deepest path first.
   pacstrip.sign keeps identifier, entitlements and CS options. Result: **49/49 pass `codesign -v --deep`**
   (`receipts/reseal.json`).
3. Owners and modes: lstat of the owners-on mount (`apps/src-owners.tsv`, 18,438 rows) equals r3's own build map
   `build-r3/research/ios26/full/owners.tsv` rows `private/var.skel/staged_system_apps/*`: **0 differences**.
   - 17,857 entries are 501:501 and 581 are 0:0 (the loctables). These are the IPSW's owners for these bundles, kept as shipped.
   - r3's own /Applications bundles are 0:80. I did not normalise the new bundles to that; one line in `insert_apps.py` would change it.
4. Transfer: tar (`--no-mac-metadata --no-xattrs`, 0 `LIBARCHIVE.xattr` headers) fb7dd3d4…, sha256 checked on both ends.
5. `build_r4.sh` (m1box):
   - Verifies r3's hash and makes a reflink copy.
   - `hfs_grow.py` grows the volume in place. Nothing moves: the bitmap gains a second extent at block 2,097,152
     (+128 blocks); the old alternate-header block is freed; the new last block is marked used; the primary and
     alternate headers are rewritten.
   - fsck, then mount rw (hfsplus, nls=utf8, noatime) in the privileged container.
   - `insert_apps.py`: refuses name clashes; owner and mode from the map; mtimes from the tar; keeps /Applications' own times.
   - fsck again.
   - `sync_alt_vh.py`: Linux leaves the alternate header flagged inconsistent, so it gets a copy of the primary.
     The first build applied this as a separate step; it is now in the script.
   - Not byte-reproducible: HFS create dates and the header dates come from the build time.
6. Checks (`receipts/`):
   - `verify-r4.json`: census r3 vs r4 (`census.py`, both mounted read-only) plus every added entry against the owner
     map and the tar's bytes: 0 problems.
   - `btree-counts.json`: catalog +36,876 records = 2 × 18,438; attributes unchanged; extents-overflow 16 → 337
     (fragmented new files; valid, fsck OK).
7. Sparse image and receipt: `ipf_r4.py` is `tools/ios_partition_flash.py` with its root pin set to r4; the repo file is
   unchanged. `sparse` gives 00be36b1…. `check` against the A6 GPT dump and plan `option-a-ios24+8`:
   **OK**, entry 36, LBA 22,757,376..29,048,831, 6,291,456 blocks, root_blocks = blocks, tail 0. `phone_write.walk`
   expands the simg to a6574777… (`receipts/receipt-host-a6dump.json`, `check-host-a6dump.txt`).

Boot images need no rebuild. `image_tool.PHONE_ROOT_SHA` is defined but not used, and the manifests carry only
`phone_root: true`. Kernel `kernel.rootview` and its descendants take ios_system's real size (7227fe7; physical A7
log: `24576 MiB`).

**Owner/coordination: one repo change is needed:** `tools/ios_partition_flash.py` `ROOT_SHA` (and the
`image_tool.PHONE_ROOT_SHA` comment) pin r3. Until that line names r4 or accepts both, run `check` and `sparse` for r4
through `tools/ipf_r4.py REPO …`. `verify-stream` reads only its receipt and works unchanged.

## 3. Space and the Mac

- r4 holds 9.2 GB of used blocks, with 15.4 GiB free in the volume.
- The Mac had **12–14 GiB free** at 20:45. The simg (8.9 GB) is therefore **not** staged there yet.
- Copy it to the flash host just before the flash, or attach the phone to m1box (§5 step 0).
- My Mac scratch (`~/hackios-root-r4-work`, 2.2 GB) was removed after the transfer.

## 4. QEMU (m1box TCG): QEMU results only

Route: r23/r26 (rd=ufsroot0, `blazer_ufs_root=ios_system`, r26's tail + `blazer_persona_log=1`), with the app2 fixes:
- kernel `kernel.rootview-bl-app2` b875e3e3…;
- overlay `qemu-app2-r1` f5603849….

Both roots got r14's lsd/usermanagerd console mirror (`edits/logmirror_lsd_umd.py`; QEMU-only variants; the same 4
plists changed in both). Intent: `receipts/qemu-intent.json`; launcher: `tools/qemu-launch.sh`; run dirs:
`$S/../runs/root-r4-q-*`.

- **24 GiB r4 does not run in QEMU** (`root-r4-q-r4`). The fake LUN lives in guest RAM, so the UFS DMA arena landed at
  0x10073b0000 and the kernel panicked before userland: `blazer-ufs: DMA at 10073b0000 is not usable` → `live handoff
  failed: 12`.
  - This is a property of the QEMU layout. On the phone the arena is at 0x889e6c000 (A7 log).
  - So QEMU ran a **20 GiB twin** instead: `build_r4q20.sh`, the same steps with the grow to 5,242,880 blocks
    (e7d8c319…). Its census is identical to r4 (292,551 entries, 0 differences).
- The first pair of guests was killed when my session ended (`*-killed` dirs). I relaunched both detached; both ran
  the full 1800 s (guest t≈1771), exit 0, root unchanged (`receipts/qemu-exit.json`).

| | r3 control (`root-r4-q-r3ctl`) | **r4 (`root-r4-q-r4q20`)** |
| --- | --- | --- |
| root mount | `"ios_system" on LUN 0 … 8192 MiB` | `"ios_system" on LUN 0 … 20480 MiB` |
| lsd `Scanned N apps in /Applications` | **204** | **253** (+49) |
| lsd on Calculator | only the placeholder (`Info.plist missing at /System/Library/AppPlaceholders/Calculator.app`) | also the real bundle (filters `com.apple.calculator.CalculatorWidget`) |
| INVALID_PERSONA / usertrap / userabort / kernel panic | 0 / 0 / 4 / 0 | 0 / 0 / 0 / 0 |
| **Home at the end** (`receipts/qemu-home-*.png`) | Settings + Phone (dock), nothing else | **2 widgets, 15 icons on page 1, 4 in the dock**: the same layout as r24 on apps-full |

- In QEMU, icon artwork renders as grey tiles, except the live Clock face. It looked the same in r24, so this is not an r4 effect.
- So in QEMU, lsd registers the 49 bundles and SpringBoard lays them out on Home. The phone boot (§5 step 6) remains
  the physical question: artwork, launches, and timing against the 300 s deadline.

## 5. Owner-approved flash of r4, with rollback (attended; the only write is step 3)

Run from the repo root on the host the phone is attached to. `N=research/ios26-dualboot-r8/attempts/a7r4-flash`,
`mkdir -p $N`.

**Step 0. Stage and check the sparse file (host).**
```sh
rsync -a m1box:/data/hackios-qemu/research/ios26-apps-r1/root-r4/out/ios_system-phone-r4.simg research/ios26-dualboot-r8/a7/
shasum -a 256 research/ios26-dualboot-r8/a7/ios_system-phone-r4.simg   # 00be36b117381ec8111a06591efd85ea216fb29429bdd1a91434e78542de21a1
shasum -a 256 research/ios26-dualboot-r8/a7/ios_system-phone-r3.simg   # e2f4ad1d597d1c692462ac9c20236e3bcb998d0c982c71324f69cb04a2b2e8ef (the rollback)
```
- Needs ~9 GB free; the Mac had 12–14 GiB at 20:45.
- Stop if either hash differs.
- Rollback: none (host only).

**Step 1. Android baseline and fresh GPT dump (read only, Android booted).**
```sh
research/ios26-dualboot-r8/return-check.sh $N/before
adb exec-out su -c 'dd if=/dev/block/by-name/ios_system bs=4M 2>/dev/null | sha256sum'   # a95542a9…34bc (r3 still there)
P=$(adb shell su -c 'readlink -f /dev/block/by-name/ios_system' | tr -d '\r'); D=${P%36}; echo $P   # /dev/block/sdX36
adb exec-out su -c "dd if=$D bs=4096 count=8 2>/dev/null" > $N/lba-0-7.bin
adb exec-out su -c "dd if=$D bs=4096 skip=31146990 count=18 2>/dev/null" > $N/lba-31146990-31147007.bin
```
- Expected: return check PASS; the r3 hash; 32,768 and 73,728 bytes.
- Stop on any mismatch.

**Step 2. Host check of the fresh dump (on m1box, where the raw image is).**
```sh
python3 -I research/ios26-apps-r1/root-r4/tools/ipf_r4.py . check --head $N/lba-0-7.bin --tail $N/lba-31146990-31147007.bin \
  --tail-lba 31146990 --total-lbas 31147008 --disk-guid 54494857-4345-4148-5045-4c204c554e31 \
  --root /data/hackios-qemu/research/ios26-apps-r1/root-r4/out/ios26-phone-r4.img --plan research/ios26-dualboot-r8/gpt-plan/option-a-ios24+8 \
  --simg /data/hackios-qemu/research/ios26-apps-r1/root-r4/out/ios_system-phone-r4.simg --out $N/receipt.json | tee $N/check.txt
```
- Expected: `OK`, first_lba 22757376, blocks 6291456, entry_index 36, padded_sha256 a6574777…6abc, tail_blocks 0.
- Stop on any `refused:`.

**Step 3. Preflight and the ATTENDED flash (owner types it).**
```sh
adb reboot bootloader
fastboot getvar partition-size:ios_system   # expect 0x600000000
fastboot getvar has-slot:ios_system         # expect no
fastboot flash ios_system research/ios26-dualboot-r8/a7/ios_system-phone-r4.simg
fastboot reboot
```
- Expected: every sparse piece `OKAY`, then `Finished`. r3's 7.75 GB took 30 pieces in 269 s, so expect ~5 min.
- Stop before the flash if the size is not 0x600000000, `has-slot` says yes, or getvar fails.
- After the flash, a piece that is not OKAY: do not retry blindly; go to step 4.
- The write is bounded to ios_system by the bootloader; Android's extents are not addressed.

**Step 4. Readback (read only, Android booted).** As A7, only the hash crosses USB.
```sh
P=$(adb shell su -c 'readlink -f /dev/block/by-name/ios_system' | tr -d '\r'); B=${P#/dev/block/}; D=${P%36}
adb shell su -c "cat /sys/class/block/$B/start /sys/class/block/$B/size"     # 182059008 and 50331648
adb exec-out su -c 'dd if=/dev/block/by-name/ios_system bs=4M 2>/dev/null | sha256sum' | tee $N/readback.txt
#   expect a6574777105ffd3ec6083cdac519e9b584f78092cab1aed4240ab81822e96abc  (whole 24 GiB extent; A7 took 176 s)
adb exec-out su -c "dd if=$D bs=4096 count=8 2>/dev/null" | cmp - $N/lba-0-7.bin && echo GPT-HEAD-SAME
adb exec-out su -c "dd if=$D bs=4096 skip=31146990 count=18 2>/dev/null" | cmp - $N/lba-31146990-31147007.bin && echo GPT-TAIL-SAME
```
- Optional, to name the first bad block: `adb exec-out su -c "dd if=$D bs=1048576 skip=88896 count=24576 2>/dev/null" |
  python3 -I tools/ios_partition_flash.py verify-stream --receipt $N/receipt.json`. It needs the raw image on that host.
- Stop on a hash mismatch: do not boot iOS; record it and roll back.
- A GPT difference is a hard stop (A6 rollback analysis first).

**Step 5. Android return check:** `research/ios26-dualboot-r8/return-check.sh $N/after-flash` → PASS.

**Step 6. iOS boot (temporary `fastboot boot`, nothing written).**
- One variable versus a physical Home run: the root route that registered apps on the phone, `a7-ios-system-r9-apps-ufs`
  (rd=ufsroot0; persona/varfs fix; Home and the Phone icon in PHYS 18:56).
```sh
tools/bootios research/images/a7-ios-system-r9-apps-ufs/boot.img a7-ios-system-r9-apps-ufs \
  --mach research/ios26-apps-r1/usersession/build/kernel.rootview-bl-aks-us2.unstripped --wait 480
```
- Look for: Home with more icons than Settings and Phone (Calculator, Safari, Messages, Clock, Notes, Camera, Photos …);
  tap Calculator once. Report what appears.
- Read-out (ramdump): `blazer-ufs: "ios_system" … 24576 MiB`, `hfs: mounted iOSRoot`, and lsd/SpringBoard lines.
  `usertrap` lines for the new apps are expected per launch; Phone's Contacts trap is a known item (app2).
- That image's deadline is 300 s. If lsd's first scan of 49 more bundles pushes Home past it, the remedy is the same
  image recipe with `--phone-deadline 1800`. That is a new build, not part of this plan.
- Alternative after that: `a7-ios-system-app2` (b06e271f…, sandbox token + tccd mirror; built, never booted).
- Stop: any panic other than the deadline, Home lost, or a crash loop of backboardd/SpringBoard.

**Step 7. Android return check:** `return-check.sh $N/after-boot` → PASS.

### Rollback: re-flash r3
```sh
adb reboot bootloader
fastboot flash ios_system research/ios26-dualboot-r8/a7/ios_system-phone-r3.simg     # e2f4ad1d…, 30 pieces
fastboot reboot
adb exec-out su -c 'dd if=/dev/block/by-name/ios_system bs=4M 2>/dev/null | sha256sum'   # a95542a96381b40aaeaa19bde8586090528582307bfd43d972737de6863a34bc
research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7r4-rollback
```
- r3's sparse rewrites the whole 24 GiB extent (root + FILL zeros), so no r4 bytes remain.
- Android never reads ios_system. Bootloaders, slots, boot_b (chooser) and the GPT are untouched by either flash.

## 6. Open

- Owner decision: the flash (section 5).
- `ROOT_SHA`/`PHONE_ROOT_SHA` pin update (coordination thread).
- If wanted, normalise the new bundles' owners to r3's /Applications (0:80); kept as the IPSW ships them here.
- Registration and launches on the phone: answered only by step 6.

## next: files for a root r5 (from research/ios26-phaseb-r1/about/FIX.md; HOST, 2026-11-03)

r4 keeps r3's prune, so these stay missing. Source: the stock 23G90 system volume (`apple/23G90/094-95981-090.dmg`), same
paths. Sizes and sha256 prefixes: `research/ios26-phaseb-r1/about/receipts/r5-filelist.txt`.

- **Covered by the int2 overlay already (no r5 needed, keep them in r5 so the covers can go):**
  `MusicLibrary.framework/{MLSortMapTables.plist, SortingDetails.plist, en.lproj/MLSections.plist}` (About abort),
  `AccessibilitySharedSupport.framework/{AXSSPunctuationModel.momd/AXSSPunctuationModel.mom, VOPronunciationModel.momd/VOPronunciationModel.mom}`
  (AccessibilityUIServer abort).
- **Need r5 (too many directories for the 8 overlay covers; Phone app white screen, INFERENCE):** the `Assets.car` of
  `Applications/MobilePhone.app` (1,829,272 B), `Applications/MobilePhone.app/PlugIns/VoicemailMessageNotificationExtension.appex/Frameworks/CallsDialer.framework`,
  and `System/Library/PrivateFrameworks/{CallsDialer, CallsAppUI, TelephonyUI, ConversationKit, CommunicationsUI}.framework`,
  `System/Library/Frameworks/ContactsUI.framework` (about 4.5 MB together).
- **Also missing, same rule, low priority:** `MusicLibrary.framework/com.apple.Music.artworkConfig`; AccessibilitySharedSupport's
  `AXLanguageToLocale.plist`, `SynthesizerLanguageMap.plist`, `FullKeyboardAccessStandardCommands-Default.plist`.
- **Prune rule changes (scripts/prune.py)**, so the next root does not lose them again: `deny-framework-data` keeps a `*.momd/*.mom`
  and `*.omo` whenever it keeps the `.momd/VersionInfo.plist` (it now keeps the plist and deletes the model, which is what
  aborts CoreData); `DENY` does not match `MusicLibrary.framework` or `AccessibilitySharedSupport.framework`; `KEEP_CAR` adds
  `MobilePhone|CallsDialer|CallsAppUI|TelephonyUI|ConversationKit|CommunicationsUI|ContactsUI`.
