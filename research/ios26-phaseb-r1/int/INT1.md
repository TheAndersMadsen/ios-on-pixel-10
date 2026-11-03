# int1: every Phase B fix in one kernel, one overlay, one image (2026-11-03, HOST build, not booted)

Labels: **PHYSICAL** = an earlier phone boot of a source image (LEDGER line named), **QEMU**, **HOST** (build, host test,
symbol/disassembly check), **INFERENCE**. Nothing in this work touched the phone. Wi-Fi (`hk-wifi-join2`) and Bluetooth are
left out on purpose. Receipts: `receipts/` (hashes in `receipts/SHA256SUMS`, Mac-side `receipts/SHA256SUMS.mac`).

## Result

| Artifact | sha256 | Where |
| --- | --- | --- |
| XNU branch **`hk-int1`** | `484717fc194d599cfd28985012b19e7bf0be9748` (15 commits on 7227fe7) | Mac `research/ios26-release-r1/work/xnu` |
| `kernel.int1` | `0d0c99b2cd7b1c71509c9cf52af34ca29c1856001fd077df41b6386bf243e9bf` | `build/` (Mac and m1box, not in git) |
| `kernel.int1.unstripped` | `531b12eb0976e553ed8464949bb8ca962227bbb14342bd905ac2acb948fb160f` | same |
| overlay `int1-r1.ovl` (661,680 B, 52 records) | `c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e` | `overlays/` (Mac and m1box) |
| **`a7-ios-system-int1`** boot.img | **`f67220f8fada32b0795548bb4974a875c9801a6936d9ac6ed03307df947b066c`** | `research/images/` (built on the Mac, copied to m1box) |
| a7-ios-system-int1 payload-usb.bin | `af0acf49e3d43ccf38d1846f883c4e293ebd7f7b59a79268833f473b484bdcd6` (margin 39,929,424 B) | |
| **`chooser-ios-int1`** boot.img | **`aca7c0fc1c61d0a813c8ba0b08381974aef5b0766e0245105e932db5126fd98c`** (default Android, installable, cold-safe) | `research/images/` (built on m1box, copied to the Mac) |
| chooser-ios-int1 kernel.bin | `a6db699094308ff00084752308f646e2f028780a9f333b7dcf0708b3f61c7eb5`, stamp nonce `0x470ece9a3bf5dcc0` | |

`image_tool_int1.py check`: `OK a7-ios-system-int1 bootable f67220f8…`. The Mac's shared `tools/image_tool.py check` gives the same result.
`chooser_ios_image.py check` (m1box): `OK chooser-ios-int1 chooser-ios bootable default android installable cold-safe aca7c0fc…`.

## 1. Branch log (`receipts/xnu-branch.txt`)

`hk-int1` was made in a throwaway worktree (`/tmp/hk-int1-wt`, removed), so the shared tree stayed on p1 throughout.
Every pick is `git cherry-pick -x` (it records the source commit) and none conflicted.

| # | hk-int1 | picked | from branch | change |
| --- | --- | --- | --- | --- |
| 1 | 71a45a3 | f24a98d | hk-bright-calib-bl | backlight calibration + marketing table on AppleARMBacklight |
| 2 | 4092d03 | e731e68 | hk-touch-direct | touch events IsDisplayIntegrated=1 (direct touches) |
| 3 | f69a083 | 44689e0 | hk-aks-wrap | SweetKeyStore AKS wrap/unwrap (`blazer_aks_wrap=1`) |
| 4 | cc79fc1 | eb2d19b | hk-aks-usersession | AKS user-session selectors, persona log (both boot-arg gated) |
| 5 | ed186e2 | cc42295 | hk-aks-usersession | varfs RENAME_SWAP/EXCL (`ramfs_renamex`, always on): personas |
| 6 | 2cabedd | 093ca86 | hk-netstack-cfg1 | `blazer_netstack=1` IONetworkStack stand-in; counted hk_deny |
| 7 | 0f57607 | 237a8b5 | hk-sandbox-token | sandbox op 5 writes `"invalid"` into word 4 |
| 8 | db92b8c | e1d1768 | hk-pwr1 | native buttons delivery + power-key lifecycle (0001) |
| 9 | 9d6c25c | b9f96eb | hk-pwr1 | haptic ROM-effect service (0832) |
| 10 | 0cf628e | 52f0299 | hk-pwr1 | `blazer_haptic_tap=1` |
| 11 | 38de7f8 | c798a68 | hk-pwr1 | `-DBLAZER_KEY_DELIVERY=1 -DBLAZER_HAPTIC_SERVICE=1` |
| 12 | 7bc06c1 | 4480b5a | hk-bright-brt1 | 16.16 max nits, truthful DCS log, unknown keys, slider-visible transport log |
| 13 | 0ff6cc4 | cac047f | hk-ustack-dbg4 | hk_ustack sampler |
| 14 | 6acfe5b | 2d640f1 | hk-ustack-dbg4 | EP0 request 0x70 |
| 15 | 484717f | d30f785 | hk-gpu-survey-r1 | `blazer_gpu=3` read-only survey (not on the int1 line) |

**De-duplication.** hk-pwr1 (6ec2724, 23ea0a2, ad12d3d) and hk-bright-brt1 (d2f4d47, 7343d9a, 2fbe8f1) each carry their own
copies of 44689e0/eb2d19b/cc42295. All three of each set have the same `git patch-id --stable` (2fee0a88…, d9f63d27…, 5ad114fb…).
Only the originals are picked, once, and none of the copies.

**No cross-branch overlap.** The only files touched by more than one pick are touched within one lineage, in that lineage's order:
SweetFramebuffer.cpp (calib → brt1), SweetKeyStore.cpp and MakeInc.def (wrap → usersession → pwr1 flags), SweetHID.cpp/hk_live_hid.inc
(touch → keys → tap), blazer_haptic.c (0832 → tap), and the ustack files (cac047f → 2d640f1). Check: every one of the 33 files hk-int1
changes against 7227fe7 is **byte-identical to the same file at some source branch tip** (receipt's last table). For each source branch, its
files differ from hk-int1 only where a later lineage member changed them. hk-gpu-survey-r1 is identical outright. MakeInc.def equals hk-pwr1's:
`-DBLAZER_AKS_WRAP=1 -DBLAZER_AKS_USERSESSION=1 -DBLAZER_KEY_DELIVERY=1 -DBLAZER_HAPTIC_SERVICE=1` on the BLAZER line.

**Build** (`tools/build_int1.py`, `receipts/build_int1.out`):
- Took the exclusive `/tmp/fleet/kernel-build-slot.lock` with no make running. The tree was p1 b228c4f and clean; the script refuses
  hk-int1 at any commit but 484717f.
- `mk.sh -j8`, rc 0 in 69 s (Mac `logs/int1-build.log`).
- Then **restored p1 b228c4f and rebuilt it**, rc 0. The obj kernel is now f7a4cf4b…, and that restored p1 kernel has no hk_ustack string.
  The tree is p1, clean.

## 2. Feature matrix

"int1 HOST" is this build: `receipts/kernel-verify.txt` (llvm-nm/objdump 23.1.4 on the unstripped kernel, **0 undefined symbols**), the
overlay decode-diff and consumer, and the image line. "Earlier evidence" is what a source image already showed, not int1.

| Feature | Gate on the int1 line | int1 HOST evidence | Earlier evidence | Attended check |
| --- | --- | --- | --- | --- |
| Backlight calibration (f24a98d) | `hk_bright=140` | strings `SWEET BL: calibration`, `backlight-calibration-parameters`, `backlight-marketing-table` | PHYSICAL r4-bl: 0 backboardd traps with hk_bright=140 | brightness slider (B) |
| brt1 DCS/16.16 nits (4480b5a) | `hk_bright=140` | `queued for DCS`, `unknown request keys`, `nits) cap %u acl_off`; `queue only` = 0; publishBacklight `ubfiz x22, x20, #16, #32` | HOST only. PHYSICAL pwr1 (LEDGER 20:32, no brt1): "brightness slider in Settings works" | B |
| Direct touch (e731e68) | always (A/B `sweet_touch_indirect=1` not set) | SweetHIDTouch::touch `add w1, w22, #0x14` (0xb0005+0x14 = 0xb0019), collection `add w1, w25, #0x18` (0xb0001+0x18); `gSweetTouchDirect` in __DATA | PHYSICAL pwr1 (kernel has it): Settings responds | S |
| AKS wrap (44689e0) | `blazer_aks_wrap=1` | `SWEET AKS: wrap/unwrap on` | PHYSICAL b1-aks: sel 10 ok 28 / fail 0 | (keychain users run) |
| AKS user session (eb2d19b) | **not on the line** (inert on the phone, r9: 0 calls) | `blazer_aks_usersession`, `blazer_persona_log` strings present | QEMU r22: never called | — |
| varfs RENAME_SWAP (cc42295) | always on | `_ramfs_renamex` (vnop table reference) | PHYSICAL r9-apps-ufs: INVALID_PERSONA 0, Phone on Home | Ph (Home shows Phone) |
| configd netstack (093ca86) | `blazer_netstack=1` | `blazer-netstack: published alone`, `IONetworkStack opened by`, `IONetworkStackUserClient::initWithTask`, `blazer_net_busy_leaves`, `blazer_net_quiet_watch`, `refusal %`; the image tool refuses the arg on a kernel without the string | QEMU A/B: `*COMPLETE*` at t=143 vs `*TIMEOUT*` at 449; CopyAll returns. Not physical | **S: Settings immediately** |
| Sandbox op 5 token (237a8b5) | always on | `_sweet_sandbox_syscall`: `copyin` 0x38, `copyout` | HOST test + QEMU r26 (0 traps). Not physical | A (About / Safari-data screens), Ph |
| Volume/power keys (0001) | `blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1` | `_sweet_hid_key_checked`, `_sweet_hid_keys_epoch`, 6 `SweetHIDButtons::physical*`; strings `SWEET PHYSICAL`, `blazer-power-key: armed`, `delivery requires reviewed power lifecycle`, `blazer-keys: polling pads` | PHYSICAL pwr1: volume keys work, lock button works | K |
| Tap haptics (0832 + tap) | `blazer_haptic_tap=1` | `_blazer_haptic_tap` (one `bl` from SweetHIDTouch::touch), `_blazer_haptic_play_rom`, `_haptic_thread`, `_hh_play_rom`; `tap feedback on`, `native ROM service ready` | PHYSICAL pwr1: vibration on touch | H |
| hk_ustack (cac047f, 2d640f1) | `hk_ustack=Preferences,MobilePhone` | `_hk_ustack_start`, `_hk_ustack_control` (called from `_usbcon_thread`), `HK USTACK: every %u s`; image tool requires it | HOST only | read-out (frames of Settings/Phone) |
| GPU survey (d30f785) | **not on the line** (`blazer_gpu=3` is a survey) | `MMU_FAULT_STATUS_META`, `SLC_STATUS1` | PHYSICAL r6-gpu PASS | — |
| Spotlight deny (perf-r1) | overlay [42] `hk_deny bluetoothd,Spotlight` | byte-identical to perf-r1 | PHYSICAL r10: deny applied, 0 `Spotlight[N]` | (no Home search) |
| Reduce Transparency/Motion (perf-r1) | overlay [48] Accessibility plist | byte-identical | PHYSICAL r10: CC glyphs and battery % visible, tiles black | CC look |
| HKMAIN watch (perf-r1) | overlay [39] Preferences rule, [47] dylib | [47] identical; [39] = app2's (perf's rules + one tccd rule) | PHYSICAL r10: HKMAIN lines named the configd wait | read-out |
| Time zone (pwr1) | overlay [51] localtime → Europe/Copenhagen | byte-identical to pwr-r1's (moved 49 → 51) | PHYSICAL pwr1: clock 8.20 correct | T |
| SBDontLockEver removed (pwr1) | overlay [0] springboard.plist | byte-identical to pwr-r1's [0] | PHYSICAL pwr1: lock button works | K (P1/P2) |
| TCC dir + tccd mirror (app2) | overlay [49] dir, [50] dylib, [39] tccd rule | byte-identical to app2-r1's | QEMU r26: TCC.db created, AddressBook granted. Not physical | Ph read-out |
| Battery % | (kernel battery chain, `SBShowBatteryPercentage`) | unchanged | PHYSICAL pwr1: 95% shown | Bt |

Not included (not among the listed branches/overlays): accel-wait's `hk_accel_once` (FINDINGS.md: its dylib is not built and not in any
overlay), Wi-Fi, Bluetooth. Stock apps beyond Settings and Phone need the phone root r4 (app2/FIX.md §3): Calculator cannot appear.

## 3. Overlay merge (`tools/int_overlay.py`, `receipts/overlay.json`, `receipts/decode-diff.txt`)

Both sources are perf-r1 (95701ed9, 49 records) with in-place replacements and appended records. pwr-r1 (d0804b36) changes [0] and appends
the localtime link. app2-r1 (0eb06481) changes [39] and appends the TCC dir and the dylib. The tool pins all three hashes and decodes them
with the second walker (`restore_cloudd.decode`). It refuses a record changed by both sources, a changed type/group/path, and an appended key
that collides. Then it packs **app2-r1's 51 records with pwr-r1's [0] and pwr-r1's appended localtime last**. By construction, int1 is pwr's
own transform applied to app2-r1. Postconditions: every record is the bytes of exactly the source that owns it.

Decode-diff, keyed by (type, group, path):

| vs | identical | differing / extra |
| --- | --- | --- |
| perf-r1 | 47 | DIFF [0] springboard.plist 793 → 774 B; DIFF [39] hk_env 710 → 821 B; ONLY-int1 [49] TCC dir, [50] hk_stderr_console.dylib (a630a41b…), [51] localtime |
| pwr-r1 | 49 (localtime byte-identical, moved 49 → 51) | DIFF [39] hk_env (app2's tccd rule); ONLY-int1 [49], [50] |
| app2-r1 | 50 | DIFF [0] springboard.plist (pwr's −SBDontLockEver); ONLY-int1 [51] localtime |

Release-header consumers (Mac, `receipts/release-headers.txt`, `consumer.txt`):
- `varfs_overlay.h`, `hk_exec_rules.h` and `varfs_tsv.h` in hk-int1 equal the pinned copies.
- `pwr/tools/pwr_consumer.c` (ASan/UBSan) on **app2-r1 → int1-r1**: **PASS, 241 checks**. One record changed (springboard.plist), one
  appended (localtime) and live under 0xA0080081, exec rules (hk_env, hk_deny) identical to app2-r1's.
- app2's own consumer already passed on perf-r1 → app2-r1 (292 checks). int1's records 1..50 are those bytes.

## 4. Image `a7-ios-system-int1` (Mac, `tools/mkimg_int1.sh`, `receipts/image-build.txt`, `manifest-diff.txt`)

- **Recipe: pwr1's.** The r9-apps-ufs route `rd=ufsroot0`, 5 cores, bootcpu 0x200, canvas 1125x2511, window 0x882000000,
  `--qemu-run overlay-1`, and **`blazer_deadline=900`** (the tool's default with `--bootcpu`). Only the kernel, overlay and line change.
- **Image tool:** `tools/image_tool_int1.py` (728bdd21…). It is the Mac's current `tools/image_tool.py` (acf48b98…, which holds other owners'
  uncommitted edits, saved as `tools/image_tool.mac-before.py`) plus:
  - pwr1's changes, by hand, since the patch did not apply to the diverged Mac copy: the `blazer_power_key`, `blazer_key_delivery` and
    `blazer_haptic_tap` allow-list entries and their kernel/combination checks, and `--drop-diag` with `dropped_diag` in the manifest;
  - `blazer_netstack=1`, with a kernel-string check and a refusal next to usbnet/wifi_net;
  - `hk_usertrace=1` in DROP_DIAG;
  - repo-relative paths, and the manifest records the tool that ran.

  Diff: `receipts/image_tool_int1.patch`. The shared Mac and m1box copies were not touched.
- **Command line 1018 B (limit 1023), 56 tokens.** Versus pwr1: `+blazer_netstack=1 +hk_ustack=Preferences,MobilePhone`,
  `−blazer_usbcon_input=1 −hk_usertrace=1`, otherwise the same tokens in the same order. Full line in `receipts/manifest-diff.txt`. It holds
  `rd=ufsroot0`, `blazer_deadline=900`, `blazer_netstack=1`, `blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1`,
  `hk_bright=140`, `blazer_aks_wrap=1`, `hk_ustack=Preferences,MobilePhone`, `hk_overlay=0xA0080081`.
- **Diagnostics dropped**, relative to the r10-perf/r9-apps-ufs line:

  | token | bytes | why it can go | dropped in |
  | --- | --- | --- | --- |
  | `hk_fb_probe=1` | 14 | six-colour DPU probe, 4.1 s hold of pid 1 | pwr1 (kept) |
  | `hk_top=30` | 10 | CPU-top lines | pwr1 (kept) |
  | `blazer_aks_log=1` | 17 | per-call AKS log (~2,500 lines) | pwr1 (kept) |
  | `blazer_aks_usersession=1` | 25 | inert on the phone (r9: 0 calls) | pwr1 (kept) |
  | `blazer_persona_log=1` | 21 | persona alloc/free lines | pwr1 (kept) |
  | **`hk_usertrace=1`** | 15 | crash-trace lines (`usertrap:`), off by default on the phone build | **int1** |
  | **`blazer_usbcon_input=1`** | 22 | live USB input: HID injection (HLI1) and the hk_ustack 0x70 live request. The `hk_ustack=` sampler runs without it (hk_ustack.c starts on names alone) | **int1** |

  Never added: `blazer_battery_receipt=1`. The cost: no `usertrap:` decode of a crash. MobilePhone and Preferences still get their user
  stacks every 5 s from hk_ustack, and the Phone trap is already decoded (crashes-r9). Without `blazer_usbcon_input`, no host-driven
  taps or keys and no `ustack_ctl.py`. The usbcon console (`blazer_usbcon=1 blazer_usbcon_ch9=1`) stays.
- Results:
  - **boot.img f67220f8…**, payload af0acf49…, entry 0xfffffe000798d488, AVB OK, margin 39,929,424 B.
  - `check` OK with both tools.
  - The manifest differs from pwr1 only in the kernel and what follows from it, the overlay (611,256 → 661,680 B), the line, `dropped_diag`,
    per-build ids, tool hashes and `shim_copy`.
  - Shim provenance: the Mac checkout is at e96cb64 (m1box at 66fa691), so `shim_copy` is 395a7752… (the Mac tree r10-perf/app2/cfg1 were built from).
    pwr1 was built on m1box (4846c047…). The m1box-only commits add the fast-start shim (gated `TGL_FAST_START`, not used here).

## 5. Chooser `chooser-ios-int1` (m1box, `receipts/chooser/`)

`LLVM=~/.local/share/hackios-host/llvm/bin TGL_TOOLCHAIN=llvm python3 -I tools/chooser_ios_image.py image chooser-ios-int1 --ios-image research/images/a7-ios-system-int1 --stock-kernel research/ios26-dualboot-r8/truth/boot_b.img --stock-kernel-sha 3635317e… --fdt research/ios26-dualboot-r8/truth/fdt.dtb --keys --cold-safe`
(chooser-ios-r3's recipe, COLD-r3.md §5, with the int1 payload).

- **boot.img aca7c0fc…**, default Android, installable, cold-safe (`-DTGL_USB_DISABLE=1`, `usb_console false`).
- Linked USB graph: only `tgl_usb_console_start → laguna_usb_board_resume, laguna_usb_start`, which is never called.
- Payload = a7-ios-system-int1's af0acf49 exactly. The recorded iOS cmdline equals the image's.
- The shim tree is m1box's 4846c047, the same as r3. As in r3, the chooser's iOS branch runs a shim built from that tree with the iOS
  image's cflags, so its shim is not byte-identical to the standalone a7-ios-system-int1's (Mac tree).
- Host tests in the build: chooser-ios 74/0. A0 admission: payload 26,130,864 B, image_size 49,357,552. Android placement 0xc9c00000.
- Image margin 16,692,928 B; blob margin 51,305,744 B. Versus r3: only name, payload, sizes/offsets, nonce, hashes.
- Copied to the Mac (`research/images/chooser-ios-int1`, boot.img hash verified). `check` there fails only because the chooser manifest
  stores absolute m1box paths. Run `check` on m1box.
- Under cold-safe, `blazer_usbcon=1` on the iOS line has no shim gadget. It should refuse with `blazer-usbcon: refused: shim's gadget didn't
  come up` (COLD-r3 §3, inference until booted). The usbcon console and any usbcon capture are therefore absent on the chooser path.
  Read the ramdump instead.

## 6. Attended checklist (owner; first `fastboot boot` of the standalone image, then the return check)

```
tools/bootios research/images/a7-ios-system-int1/boot.img a7-ios-system-int1 \
  --mach research/ios26-phaseb-r1/int/build/kernel.int1.unstripped --wait 1080
```

Before you start, note Android's battery %. Expect the lock screen first (SBDontLockEver removed). The boot ends itself at 900 s.

- [ ] **T time:** the lock screen shows the correct local time (±1 min) and date.
- [ ] **Bt battery:** the status bar % is close to Android's. Write down the number.
- [ ] **U:** swipe up to reach Home (no passcode). Icons: Settings and Phone.
- [ ] **S Settings immediately:** tap Settings as soon as Home is up. Scroll within ~10 s, tap General, go back. **Pass = responds at once**,
      not after configd's 300 s timeout as in pwr1. Note the clock time of the first response.
- [ ] **A About:** Settings > General > About. Opens and lists data? (pwr1: did not open.) Wait 10 s if blank.
- [ ] **K keys:** Volume Up ×2, then Down ×2, 3 s apart. The HUD moves both ways. One short side-key press locks (dark or lock screen),
      a second wakes it, swipe up returns to Home.
- [ ] **H haptics:** tap an empty spot 3 times, ~1 s apart. A short buzz each time?
- [ ] **B brightness:** Settings > Display & Brightness (or Control Center). Slider all the way down, hold 3 s, then all the way up. The panel visibly dims,
      then returns no brighter than the boot.
- [ ] **Ph Phone:** tap Phone, wait 10 s. Window, or back to Home? (Expected: it may still trap; the read-out names why.)

Rules: never hold the side key longer than ~1 s, no chords, never press power on a fastboot screen.
**Stop** (put the phone down; the deadline ends the boot) on: a panic, Home lost for good, a backboardd/SpringBoard/tccd crash loop, a key
that acts stuck, a buzz that does not stop. Rollback: deadline/PSCI reset to fastboot, then `return-check.sh`. Nothing is written: the root is
read only and /private/var is in RAM.

Afterwards, if the owner wants the menu path: `fastboot boot research/images/chooser-ios-int1/boot.img`, Vol Down → iOS → Home (COLD-r3 T1).
Then C1 (hands off → Android, 0xc9c00000). Flashing it to boot_b is a separate destructive step that needs the owner's explicit approval
(rollback `fastboot flash boot_b research/ios26-dualboot-r8/truth/boot_b.img`, 3635317e…).

### Read-out (ramdump `kernel.log`, up to the first older boot's banner)

| Item | Lines |
| --- | --- |
| S | `blazer-netstack: published alone`, then `IONetworkStack opened by configd[N] … IOKit root busy B`. B = 0: InterfaceNamer answers at once. B > 0: `busy leaf …` and `IOKit quiet N ms after the open` give the wait. HKMAIN `pings` +~10 per beat with `ev touch` growing = interactive; repeated `stall` frames = the next blocking call (dsc_sym.py) |
| A / Ph | `HK USTACK: Preferences[N] …` / `MobilePhone[N] …` main-thread `st`/`pc`/`fp` (ustack_sym.py). `SWEET Sandbox: containermanager op 5`. `HKSTDERR: tccd[N]` then `AUTHREQ_*` / `Granting … via entitlement` for `com.apple.mobilephone` (app2/FIX.md §2.3 decision). No `usertrap:` lines this time (hk_usertrace dropped) |
| K | `SWEET PHYSICAL: … usage=0xe9/0xea/0x30 clients=N`, `blazer-power-key: armed after stable release`; `forced release` = fault |
| H | `native ROM service ready 1`, `tap feedback on: rom 0, 100 ms`, `tap N rc 0` |
| B | `SWEET BL: … (queued for DCS)`; `tensor-dpu: bright transport sent_dbv … (~N nits)` falling to ~1397 and back, max ≤ 4636; `unknown request keys` names |
| T / Bt | `blazer-rtc: … publish … ok 1`, no `localtime link invalid`; `HKBATT: … battery_view_set value=0.NN` = the owner's number |

## Files

- `INT1.md`: this file.
- `tools/build_int1.py`: kernel build under the lock, then p1 restore.
- `tools/int_overlay.py`: merge and `--diff`.
- `tools/image_tool_int1.py` and `tools/image_tool.mac-before.py`: the image tool as run, and its base.
- `tools/mkimg_int1.sh`: image, consumers, manifest diff.
- `receipts/`:
  - `xnu-branch.txt`, `build_int1.out`, `kernel-verify.txt`;
  - `overlay.json`, `decode-diff.txt`, `release-headers.txt`, `consumer.txt`, `inputs-verify.txt`;
  - `image_tool_int1.patch`, `image_tool.sha256`, `image-build.txt`, `image-check.txt`, `manifest-diff.txt`;
  - `chooser/`, `SHA256SUMS`, `SHA256SUMS.mac`.
- `build/` (kernels, object copies) and `overlays/int1-r1.ovl`: derived, not for git.

## Commit request (coordination; nothing staged here)

Force-add, as the other Phase B receipts: `research/ios26-phaseb-r1/int/INT1.md`, `int/tools/*`, `int/receipts/**`. Not `build/` or
`overlays/`. Message: "int1: hk-int1 484717f (all Phase B kernel fixes, de-duplicated) + merged overlay c440b6ea; a7-ios-system-int1
f67220f8 and chooser-ios-int1 aca7c0fc built, not booted".

Proposed NOTES line: **int1 (2026-11-03, HOST, not booted):** `a7-ios-system-int1` (f67220f8…) = pwr1's recipe +
XNU `hk-int1` 484717f (calib, touch, AKS wrap, varfs swap, netstack, sandbox token, keys/haptics, brt1, ustack, gpu survey) + overlay
int1-r1 (perf + pwr + app2), deadline 900. Cold-safe menu image `chooser-ios-int1` (aca7c0fc…) carries it. Checklist in
`research/ios26-phaseb-r1/int/INT1.md`.
