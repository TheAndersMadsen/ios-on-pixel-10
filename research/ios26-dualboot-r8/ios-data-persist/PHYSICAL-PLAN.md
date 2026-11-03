# ios_data persist: first physical test, plan r2 for int1 (2026-11-03). Status: IMAGE BUILT AND CHECKED ON THE HOST; NOT RUN

Goal: an iOS setting changed in one boot (Dark mode, the brightness slider) is still set in the next boot. The only phone
writes are the kernel's own, to `ios_data` blocks 2..4099, plus the force-fastboot flag the boot runner already toggles.
Before and after, the phone hashes everything else, and those hashes must match. Android is not touched: it never reads
`ios_data`, and no `fastboot flash` or `erase` appears below. Everything in this file is host work or inference until the
receipts below exist. r1 (pinned to `kernel.rootview`, image `persist-iosdata-r1`, never built) is superseded: int1 is the
current all-fixes image and is the one that reaches a usable Settings on the phone.

## What is admitted, and why this kernel

- **Image `a7-ios-system-int1-persist`**, boot.img sha256 **`84f993b65fb24f2c98af106f49b5265d57677a9fe54eed75ce42c7ce6fbf519a`**
  (payload 958765289e138a3d…, manifest db98427011dc332b…). Built on the Mac, copied to m1box (`research/images/`, not in git).
  The build receipt is `INT1-PERSIST.md`.
- **The image is a7-ios-system-int1 (f67220f8…) with three line changes**, and the same kernel, overlay, route, cores, bootcpu,
  canvas, window, deadline (900 s) and `--drop-diag`. The manifest diff checks this (`receipts/int1-persist/manifest-diff.txt`,
  `MANIFEST-DIFF OK`). The changes:
  - `+ blazer_persist=1 blazer_persist_period=15`;
  - `− blazer_usbcon=1 blazer_usbcon_ch9=1`: the live USB console. bootios needs no console: it detects the park by
    polling fastboot and then pulls the ramdump;
  - `hk_ustack=Preferences,MobilePhone → hk_ustack=Preferences`: Settings' stacks are still sampled.

  The line is 1012 B (limit 1023). The two persist tokens add 42 B to int1's 1018. Dropping hk_ustack alone (34 B) or the
  usbcon pair alone (36 B) is not enough.
- **Kernel `kernel.int1`** (0d0c99b2…) = XNU `hk-int1` 484717f. Evidence (`receipts/int1-persist/xnu-ancestry.txt`,
  `kernel-strings.txt`):
  - **SOURCE:** dd000c8 (the ios_data writer) is an ancestor of 7227fe7, and 7227fe7 is an ancestor of 484717f. The 15 picks
    change 33 files. None of them is a persist, ufs, n882 or n913 file, and no diff line names persist, write_guard, ios_data
    or bp_part. `varfs_persist.inc`, `varfs_persist_core.h`, `hakios.blazer_persist_disk.inc` and `hakios.blazer_ufs.c` have
    the same blob ids at 7227fe7 and 484717f. So the writer, the GPT resolve, the seal and the write guard are 7227fe7's,
    which is the code QEMU NEGATIVE-r1 ran (b228c4f = 7227fe7 + dd000c8 + the fake-LUN patch).
  - **HOST:** the binary has `blazer-persist: ios_data at LBA`, `refused root "%s": userdata` and `n882_port_write_guard`, and
    no `blazer_ufs_fake_lun`.
  - **PHYSICAL:** a7-ios-system-int1 booted this exact kernel from ios_system read-only, with Settings usable at once
    (LEDGER 21:11).
  - **Not covered by QEMU:** hk-int1 also carries cc42295 (varfs RENAME_SWAP/EXCL), which changes how files reach
    `/private/var`, the tree the save reads. Safety is unaffected, since the writer and its guard are unchanged. Whether a
    renamed prefs file is the one saved is only shown by this test.
- **Gate:** `tools/image_tool.py image ... --persist-ios-data` now admits two pinned kernels, `kernel.rootview` (ddf874fb…) and
  `kernel.int1` (0d0c99b2…), under the same conditions as before:
  - `blazer_persist=1`, plus at most one `blazer_persist_period=15..3600`;
  - `blazer_ufs_root=ios_system` exactly once, on `blazer_ufs_lun=0`;
  - `--phone-root` and no other profile;
  - the kernel file's sha256 must equal the claimed pin, and the kernel needs the writer and refusal strings and no fake-LUN
    mode.

  Everything else is refused: no flag, mode 2/3/0, `_fresh`, `_selftest`, `_stable`, any other kernel (p32-iosdata-dd000c8
  and fakelun-b228c4f by name), a test, fake, rw or readback token, or another root. `check` refuses a line with
  `blazer_persist` unless the manifest's record names the image's own kernel and that kernel is pinned. Tests
  (`tools/test_image_tool.py` `PersistIosData`, 11 tests, 95/95 overall) include `test_real_int1_kernel` on the real file.
  The int1 build used `tools/image_tool_int1_persist.py` (int1's tool plus the same gate patch). The persist tests pass
  against that copy too.
- **What is saved:** `/private/var/preferences`, `/private/var/mobile/Library/Preferences`,
  `/private/var/root/Library/Preferences` and the boot-count marker. Nothing named MobileGestalt (`varfs_persist_core.h`).
  - There is a save every 15 s and at a clean shutdown. A save whose bytes equal the newest copy writes nothing.
  - The deadline panic is not a clean shutdown: change the setting at least 2 minutes before the 900 s deadline.
  - Restore order (SOURCE, `varfs_persist.inc`): seed, then overlay, then the saved copy, last. int1's overlay seeds
    `.GlobalPreferences.plist`, `com.apple.springboard.plist`, `com.apple.Accessibility.plist` and FeatureFlags/SpringBoard.plist.
    In boot 2 the saved copies win, and the log says `the saved copy overrules overlay …` and `overruled N overlay entries`.
    This is expected.
  - **INFERENCE:** Dark mode lives in a `mobile/Library/Preferences` plist (UIKit's interface style) and the brightness level in
    backboardd's prefs. Dark mode is the primary check because it is binary and visible. Brightness is secondary: `hk_bright=140`
    sets the boot level before backboardd applies its own.

## Checker: `tools/persist_check.py` (read-only; tests `tools/test_persist_check.py`, fake adb)

`snapshot` runs in Android over adb with su. It hashes on the phone (`dd | sha256sum`), so only digests and dd's byte counts
cross USB. Each region command resolves its partition again via `/dev/block/by-name`, prints the extent it found, and is
refused if that extent or the byte count differs from the layout read at the start. LUN 0's table must be the A6 table exactly.

| Region | Class |
| --- | --- |
| GPT head/tail of every disk with by-name partitions (LUN 0: LBA 0..5 and 31147003..31147007) | must |
| boot, init_boot, vendor_boot, vendor_kernel_boot, dtbo, vbmeta, vbmeta_system, vbmeta_vendor, pvmfw (both slots; boot_b holds chooser-ios-int1 aca7c0fc), super, ios_system (24 GiB, whole) | must |
| ios_data block 0, block 1 (test block), blocks 4100..end | must |
| ios_data blocks 2..4099 (the two slots) | persist: the only blocks allowed to change |
| userdata and userdata_exp.ai: first and last 64 MiB | observed |
| every other partition, whole (persist, misc, metadata, efs, modem, bootloader LUNs, ...) | observed |

`compare` exits 0 (PASS), 1 (FAIL: a must region, the layout, or the control's must/persist regions changed) or 2 (REVIEW: an
observed region changed and the Android-only control run does not explain it). It also prints whether the slots were written.
A full snapshot reads about 42 GiB (about 5-6 min). `--dry-run` prints every adb command and runs none.

## Prerequisites (stop if one is missing)

1. Android is booted on slot b (boot_b = chooser-ios-int1, Android by timeout) and force-fastboot is off. `adb shell su -c id`
   prints uid=0, and `ANDROID_SERIAL` is set.
2. m1box has this change: `python3 -I tools/test_image_tool.py` and `python3 -I tools/test_persist_check.py` both end `OK`, and
   `python3 -I tools/image_tool.py check research/images/a7-ios-system-int1-persist` prints `persist ios_data: blazer_persist=1
   blazer_persist_period=15 kernel 0d0c99b2cd7b1c71` and `OK … 84f993b6…`. The Mac's shared tool predates the gate change and
   refuses this image: run `check` on m1box, or with `research/ios26-dualboot-r8/ios-data-persist/tools/image_tool_int1_persist.py`.
3. The Mac has the same image: `research/images/a7-ios-system-int1-persist/boot.img` = 84f993b6… (built there).

## The attended sequence (m1box, repo root; about 75 min, two ~18-min iOS boots)

The `adb`/`fastboot` wrappers reach the phone through the Mac. bootios runs on the Mac via `mac repo`. Rules: bare `fastboot boot`
only, disks by-name, never hold the side key longer than ~1 s, no chords, never press power on a fastboot screen.

```sh
export PATH=$HOME/.local/share/phone-bridge/bin:$PATH ANDROID_SERIAL=<serial>
A=research/ios26-dualboot-r8/attempts/persist-int1-r1; mkdir -p $A
IMG=research/images/a7-ios-system-int1-persist; K=research/ios26-phaseb-r1/int/build/kernel.int1

# 0. Host checks (nothing touches the phone)
python3 -I tools/test_image_tool.py 2>&1 | tail -1; python3 -I tools/test_persist_check.py 2>&1 | tail -1     # OK, OK
python3 -I tools/image_tool.py check $IMG                      # persist ios_data: ... kernel 0d0c99b2cd7b1c71 / OK ... 84f993b6...
mac repo --force -- shasum -a 256 $IMG/boot.img $K.unstripped  # 84f993b6... and 531b12eb...

# 1. Pre-hash (Android, read-only, ~6 min)
python3 -I tools/persist_check.py snapshot --out $A/pre.json

# 2. Android-only control: the same bootloader round trip without iOS, so Android's own writes are known
adb reboot bootloader
fastboot oem force-fastboot on && fastboot oem force-fastboot off && fastboot reboot      # chooser -> Android by timeout
research/ios26-dualboot-r8/return-check.sh $A/control-return                              # expect PASS
python3 -I tools/persist_check.py snapshot --out $A/control.json
python3 -I tools/persist_check.py compare --before $A/pre.json --after $A/control.json    # PASS or REVIEW (Android churn); FAIL: stop

# 3. iOS boot 1 (temporary; runs 900 s, then parks in fastboot and the ramdump is pulled)
adb reboot bootloader
mac repo --force --back-attempt -- tools/bootios $IMG/boot.img persist-int1-b1 --mach $K.unstripped --wait 1080
#    Owner, at Home (lock screen first: swipe up):
#      a. Settings > Display & Brightness > Appearance: Dark.
#      b. Same screen: brightness slider to about one quarter (clearly below the boot level).
#      c. Go back to Home; touch nothing for 2 min. All of this must end before ~12 min after the fastboot boot.
#    Write down the clock time of (a) and (b).
grep -a 'blazer-persist\|blazer-ufs: "ios_system"\|blazer-root: deadline' <attempt>/ramdump/kernel.log

# 4. iOS boot 2, same image (the phone is parked in fastboot, force-fastboot on). Only if every boot-1 stop rule passed.
mac repo --force --back-attempt -- tools/bootios $IMG/boot.img persist-int1-b2 --mach $K.unstripped --wait 1080
#    Owner, at Home, touching nothing first: Is Home/Settings dark? Settings > Display & Brightness: Appearance Dark selected?
#    Slider where it was left? Say yes or no for each. Change nothing in this boot.
grep -a 'blazer-persist' <attempt>/ramdump/kernel.log

# 5. Back to Android, return check, post-hash and compare
fastboot oem force-fastboot off && fastboot reboot                                         # chooser -> Android by timeout
research/ios26-dualboot-r8/return-check.sh $A/after                                       # expect PASS
python3 -I tools/persist_check.py snapshot --out $A/post.json
python3 -I tools/persist_check.py compare --before $A/pre.json --after $A/post.json --control $A/control.json
#    expect PASS | ios_data slots WRITTEN
```

Hands off on the chooser menu: the menu's iOS entry is plain int1 (no persist tokens), which ignores `ios_data`.

### Expected kernel lines (from the source; numbers from the A6 table)

Boot 1:
```
blazer-ufs: "ios_system" on LUN 0: first block 15b4000, 24576 MiB, read only, ...
blazer-persist: mode 1, target ios_data, 4099 blocks in 1 extents, table a71bd369, slot 2049 blocks
blazer-persist: ios_data at LBA 29048832, 2098171 blocks, above userdata's 22757375, seal ........, armed
blazer-persist: slot 0: no valid header / slot 1: no valid header / no saved state     (the old Android bytes there)
blazer-persist: boot count 1
blazer-persist: saved slot ., generation 1, ... ; later generations after the setting change
blazer-root: deadline 900 s ...
```
Boot 2:
- `restoring slot S, generation G`, where G is boot 1's last generation;
- `the saved copy overrules overlay …` lines and `overruled N overlay entries` (expected, see above);
- `restored generation G, ...`;
- `boot count 2`, the no-touch proof: the counter only goes up through a save and a restore;
- new saves continue at G+1, …

## Stop rules (each: stop, then go to rollback)

- Step 0: a test not OK, `check` not OK, or the boot.img hash is not 84f993b6….
- Step 2: control compare FAIL (a must or persist region changed without iOS). Either the classification is wrong or something
  else writes there. Do not boot iOS.
- Boot 1, before boot 2 (read the log first). Any of these: skip boot 2 and go straight to step 5.
  - `ios_data at LBA` is not 29048832, 2098171 blocks, above 22757375;
  - any `blazer-persist: refused`, `WRITE refused`, `store refused`, `save failed`, `save refused`, `snapshot failed` or
    `couldn't be read`;
  - any panic other than `blazer-root: deadline 900 s`, and above all one naming `n882_port_write_guard`, the seal, or
    `blazer-persist`;
  - no `saved slot` line after the setting change, or a reset before the deadline.
- Boot 2: a `restoring generation ... errno` panic means a saved state that breaks the boot: rollback below.
- Step 5: return check not PASS, or compare FAIL. Do not boot the persist image again. Keep Android as it is and record.
  REVIEW: list the regions. A change in a bootloader or Android partition that the control did not show must be explained
  before another persist boot.
- The setting not kept while `boot count 2` and PASS hold is a userland finding (cfprefsd, a path outside the whitelist, the
  RENAME_SWAP path), not a safety stop.

## Rollback

- **Android:** nothing to undo. Android does not read `ios_data` and nothing above writes Android partitions. If the return
  check fails, follow `research/factory-alias-restore-r1/HANDOFF.md` and the A1/A6 backups. Bootloaders, slots, firmware and
  backups are not touched.
- **iOS state:** any image without `blazer_persist` (a7-ios-system-int1, the chooser's iOS entry) ignores `ios_data` completely.
  - To erase the saved state, zero the store's table (ios_data blocks 1..4099) from Android. This writes to `ios_data` only,
    bounded by the partition node: **confirm with the owner first**.
    ```sh
    adb shell "su -c 'P=\$(readlink -f /dev/block/by-name/ios_data); dd if=/dev/zero of=\$P bs=4096 seek=1 count=4099 conv=fsync'"
    adb shell "su -c 'P=\$(readlink -f /dev/block/by-name/ios_data); dd if=\$P bs=4096 skip=1 count=4099 | sha256sum'"
    #   expect 3407dbf48740c4d12ee7d7ec6de53f3563d420091e28b0952fbf519ecbd9e9b6 (4099 zero blocks, checked on the host)
    python3 -I tools/persist_check.py snapshot --out $A/after-zero.json
    python3 -I tools/persist_check.py compare --before $A/post.json --after $A/after-zero.json   # only ios_data:slots (and block 1) may differ
    ```
    After zeroing, the next persist boot logs `no saved state` and starts from the seed. The `compare` after zeroing reports
    ios_data block 1 too: it held old Android bytes, and the zero writes it.
  - A saved state that breaks a boot can also be left in place: one boot with `blazer_persist_fresh=1`. The gate refuses that
    token today, so it would need its own admitted build.
- **ios_system** is read-only on this line. If its hash ever differs, re-flash the same sparse file (A7) after review.

## Receipts to write after the run

- `$A/{pre,control,post}.json` and their compare outputs;
- both bootios attempt directories (kernel.log `blazer-persist` lines) and both return checks;
- the owner's yes/no for Dark mode and the slider, and the clock times.

Then replace this file's status line and NOTES' persistence statement with the result.
