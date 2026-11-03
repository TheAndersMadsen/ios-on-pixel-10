# ios_data persist: first physical test, plan r1 (2026-11-03). Status: READY ON THE HOST; NOT RUN

Goal: an iOS setting changed in one boot is still set in the next boot. The only phone writes are the kernel's own, to
`ios_data` blocks 2..4099, plus the force-fastboot flag the boot runner already toggles. Before and after, the phone hashes
everything else, and those hashes must match. Android is not touched: it never reads `ios_data`, and no `fastboot flash`
or `erase` appears below. Everything in this file is host work or inference until the receipts below exist.

## What is admitted, and why this kernel

- `tools/image_tool.py image ... --persist-ios-data` admits `blazer_persist=1` and `blazer_persist_period=15..3600`
  (the kernel's own range; outside it the kernel silently uses 60). The kernel is pinned to
  `research/ios26-dualboot-r8/rootview/kernel.rootview` (sha256 `ddf874fb41cf4871f39336a1bb3a7c77686d6f075e2fd8b7260a86707bd0b5f3`).
  The line must hold `blazer_ufs_root=ios_system` exactly once, on `blazer_ufs_lun=0`. The flag works only with `--phone-root`
  and no other profile. Every other case is refused: no flag, persist mode 2/3/0, `_fresh`, `_selftest`, `_stable`,
  any other kernel, a test, fake, rw or readback token, or another root. `image_tool.py check` refuses an image whose line
  carries `blazer_persist` but whose manifest lacks the gate's record. Tests: `tools/test_image_tool.py` `PersistIosData`.
- **The kernel is not `kernel.p32-iosdata-dd000c8` (052d00f8…).** That build is dd000c8 alone. It predates 7227fe7, so its
  root view is still pinned to the 8 GiB `userdata_exp.ai` extent and it cannot root on ios_system (A7-READY section 3).
  The gate refuses it by name. `kernel.rootview` is release tree 7227fe7 = dd000c8 + the root-view fix
  (`git diff dd000c8 7227fe7` touches only `hakios.blazer_ufs.c` attach/naming and `n913_n892_bridge.inc`; neither
  `hakios.blazer_persist_disk.inc` nor `varfs_persist*.{inc,h}` changes). Evidence for it:
  - SOURCE: dd000c8 writes only to the GPT-resolved, sealed `ios_data`.
  - QEMU: NEGATIVE-r1 ran 7227fe7 + the fake-LUN patch (`kernel.fakelun-b228c4f`, also refused for the phone). It made
    12 saves and 0 changed blocks outside ios_data blocks 2..11 and 2051..2060.
  - PHYSICAL: A7 r1 booted this exact kernel from ios_system, read-only and without persist tokens.
  - Strings checked in the binary: `blazer-persist: ios_data at LBA`, `refused root "%s": userdata`, and no
    `blazer_ufs_fake_lun`.
- What is saved: `/private/var/preferences`, `/private/var/mobile/Library/Preferences`, `/private/var/root/Library/Preferences`
  and the boot-count marker. Nothing named MobileGestalt (`varfs_persist_core.h`). There is a save every period
  (15 s here) and at a clean shutdown. The deadline panic is not a clean shutdown, so the setting must be changed at least
  two minutes before the deadline.

## Checker: `tools/persist_check.py` (read-only; tests `tools/test_persist_check.py`, fake adb)

`snapshot` runs in Android over adb with su. It hashes on the phone (`dd | sha256sum`, so only digests and dd's byte
counts cross USB). Each region command resolves its partition again via `/dev/block/by-name`, prints the extent it found,
and is refused if that extent or the byte count differs from the layout read at the start. LUN 0's table must be the A6
table exactly. Regions:

| Region | Class |
| --- | --- |
| GPT head/tail of every disk with by-name partitions (LUN 0: LBA 0..5 and 31147003..31147007) | must |
| boot, init_boot, vendor_boot, vendor_kernel_boot, dtbo, vbmeta, vbmeta_system, vbmeta_vendor, pvmfw (both slots), super, ios_system (24 GiB, whole) | must |
| ios_data block 0, block 1 (test block), blocks 4100..end | must |
| ios_data blocks 2..4099 (the two slots) | persist: the only blocks allowed to change |
| userdata and userdata_exp.ai: first and last 64 MiB | observed |
| every other partition, whole (persist, misc, metadata, efs, modem, bootloader LUNs, ...) | observed |

`compare` exits 0 (PASS), 1 (FAIL: a must region, the layout or the control's must/persist regions changed) or 2
(REVIEW: an observed region changed and the Android-only control run does not explain it). It also prints whether
the slots were written. A full snapshot reads about 42 GiB (A7 rate: about 5-6 min). `--dry-run` prints every adb
command and runs none.

A7's tail range (LBA 31146990..31147007) includes ios_data's last 13 blocks. This checker's GPT tail starts after
the last partition, so the two never overlap.

## Prerequisites (stop if one is missing)

1. `a7-ios-system-r2` showed Home on the panel and its return check passed (HANDOFF item 1). Without a visible Home the
   setting cannot be changed.
2. The Mac checkout has the commit with this change: `python3 -I tools/test_image_tool.py` and
   `python3 -I tools/test_persist_check.py` both end `OK`.
3. Android is booted on slot b, force-fastboot is off, `adb shell su -c id` prints uid=0, `ANDROID_SERIAL` is set.

## The attended sequence (Mac, `~/Developer/personal/hackios`; about 90 min, two 30-min iOS boots)

```sh
export ANDROID_SERIAL=<serial>
A=research/ios26-dualboot-r8/attempts/persist-r1; mkdir -p $A
K=research/ios26-dualboot-r8/rootview/kernel.rootview

# 1. Build (host only). r2's exact line plus two tokens. --phone-deadline 1800: Home takes about 10 min.
python3 -I tools/image_tool.py image persist-iosdata-r1 --kernel $K \
  --kernel-sha ddf874fb41cf4871f39336a1bb3a7c77686d6f075e2fd8b7260a86707bd0b5f3 --persist-ios-data \
  --phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --canvas 1125x2511 \
  --var-overlay research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl \
  --var-overlay-sha 7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58 \
  --phone-args "blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 hk_present_trace=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_battery_receipt=1 hk_bright=140 blazer_aks_log=1 blazer_persist=1 blazer_persist_period=15" \
  --phone-deadline 1800
python3 -I tools/image_tool.py check research/images/persist-iosdata-r1      # expect "persist ios_data: ..." then OK ... bootable
python3 -I -c 'import json,sys; m=[json.load(open(f"research/images/{n}/manifest.json")) for n in ("a7-ios-system-r2","persist-iosdata-r1")]; a,b=(set(x["cmdline"].split()) for x in m); d=(sorted(b-a),sorted(a-b)); print(d); sys.exit(0 if d==(["blazer_persist=1","blazer_persist_period=15"],[]) and all(m[0][k]==m[1][k] for k in ("mach","var_overlay","window_base")) else 1)'
#    expect (['blazer_persist=1', 'blazer_persist_period=15'], []) and exit 0: the same image as r2 plus the two tokens

# 2. Pre snapshot (Android, read-only, ~6 min)
python3 -I tools/persist_check.py snapshot --out $A/pre.json

# 3. Android-only control: the same bootloader round trip without iOS, so Android's own writes are known
adb reboot bootloader
fastboot oem force-fastboot on && fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh $A/control-return          # expect PASS
python3 -I tools/persist_check.py snapshot --out $A/control.json
python3 -I tools/persist_check.py compare --before $A/pre.json --after $A/control.json   # expect PASS or REVIEW (Android churn); FAIL: stop

# 4. iOS boot 1 (temporary; parks in fastboot after the deadline)
adb reboot bootloader
tools/bootios research/images/persist-iosdata-r1/boot.img persist-iosdata-r1-b1 --mach $K.unstripped --wait 2100
#    Owner, at Home (~10 min): Settings > Display & Brightness > Appearance: Dark. Keep it on screen for 2 min. Do not touch it again.
grep -a 'blazer-persist\|blazer-ufs: "ios_system"' <attempt printed by bootios>/ramdump/kernel.log

# 5. iOS boot 2, same image (the phone is in fastboot, force-fastboot on)
tools/bootios research/images/persist-iosdata-r1/boot.img persist-iosdata-r1-b2 --mach $K.unstripped --wait 2100
#    Owner, at Home: is Appearance still Dark? (say so; the log is the second proof)
grep -a 'blazer-persist' <attempt printed by bootios>/ramdump/kernel.log

# 6. Back to Android, then the post snapshot and the return check
fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh $A/after                    # expect PASS
python3 -I tools/persist_check.py snapshot --out $A/post.json
python3 -I tools/persist_check.py compare --before $A/pre.json --after $A/post.json --control $A/control.json
#    expect PASS | ios_data slots WRITTEN
```

### Expected kernel lines (from the source; numbers from the A6 table)

Boot 1:
```
blazer-ufs: "ios_system" on LUN 0: first block 15b4000, 24576 MiB, read only, ...
blazer-persist: mode 1, target ios_data, 4099 blocks in 1 extents, table a71bd369, slot 2049 blocks
blazer-persist: ios_data at LBA 29048832, 2098171 blocks, above userdata's 22757375, seal ........, armed
blazer-persist: slot 0: no valid header / slot 1: no valid header / no saved state     (the old Android bytes there)
blazer-persist: boot count 1
blazer-persist: saved slot ., generation 1, ... ; later generations after the setting change
```
Boot 2: `restoring slot S, generation G` (G = boot 1's last generation), `restored generation G, ...`, `boot count 2`.
`boot count 2` is the no-touch proof: the counter only goes up through a save and a restore.

## Stop rules (each: stop, then go to rollback)

- Step 1: any refusal, `check` not OK, or the manifest diff is not exactly the two tokens.
- Step 3: control compare FAIL (a must or persist region changed without iOS). Either the classification is wrong or
  something else writes there. Do not boot iOS.
- Boot 1, before boot 2 (read the log first):
  - `ios_data at LBA` is not 29048832, 2098171 blocks, above 22757375;
  - any `blazer-persist: refused`, `save failed`, `save refused` or `couldn't be read`;
  - any panic other than `blazer-root: deadline 1800 s`, and above all one naming `n882_port_write_guard`, the seal,
    or `blazer-persist`;
  - no `saved slot` line, or a reset before the deadline.
  Any of these: skip boot 2, go straight to step 6.
- Boot 2: a `restoring generation ... errno` panic. That is a saved state that breaks the boot; rollback below.
- Step 6: return check not PASS, or compare FAIL. Do not boot the persist image again. Keep Android as it is and record.
  REVIEW: list the regions; a change in a bootloader or Android partition that the control did not show must be
  explained before another persist boot.
- The setting not kept while `boot count 2` and PASS hold is a userland finding (cfprefsd, a path outside the
  whitelist), not a safety stop.

## Rollback

- Android: nothing to undo. Android does not read `ios_data` and nothing above writes Android partitions. If the return
  check fails, follow `research/factory-alias-restore-r1/HANDOFF.md` and the A1/A6 backups. Bootloaders, slots, firmware
  and backups are not touched.
- iOS state: any image without `blazer_persist` (for example `a7-ios-system-r2`) ignores `ios_data` completely.
  To erase the saved state, zero the store from Android. This is a write to `ios_data` only, bounded by the partition
  node: **confirm with the owner first**.
  ```sh
  adb shell "su -c 'P=\$(readlink -f /dev/block/by-name/ios_data); dd if=/dev/zero of=\$P bs=4096 seek=1 count=4099 conv=fsync'"
  adb shell "su -c 'P=\$(readlink -f /dev/block/by-name/ios_data); dd if=\$P bs=4096 skip=1 count=4099 | sha256sum'"
  #   expect 3407dbf48740c4d12ee7d7ec6de53f3563d420091e28b0952fbf519ecbd9e9b6 (4099 zero blocks)
  ```
  After zeroing, the next persist boot logs `no saved state` and starts from the seed.
- ios_system is read-only on this line. If its hash ever differs, re-flash the same sparse file (A7) after review.

## Receipts to write after the run

`$A/{pre,control,post}.json` and their compare outputs, both bootios attempt directories (kernel.log `blazer-persist`
lines), both return checks, the owner's yes/no on the setting. Replace this file's status line and NOTES' persistence
statement with the result.
