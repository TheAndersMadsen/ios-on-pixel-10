# int4: one test image = int3 debug base + fb120 (120 Hz) + ram-full (16 GiB) + chg1 (read-only charger) (2026-11-04, HOST + ARM64 + QEMU; not booted)

Labels: **SRC**, **HOST** (built on the Mac / m1box), **ARM64** (symbols and disassembly of the linked kernel), **QEMU** (m1box TCG,
read-only phone root r3), **PHYSICAL** (earlier phone logs, re-read only). This agent did not touch the phone. Kernels, objects,
overlays and images are not for git.

## Result

| Artifact | sha256 / id |
| --- | --- |
| XNU branch **`hk-int4`** (Mac nested repo) | **`f6c8a68909fd979104228e8495f5465fd545c5d5`** = hk-int3 3dc7fec + fb120 cd60b8d (→ a66c542) + ram-full 476c253 (→ d988f08) + chg1 ca39cb4 (→ f6c8a68). All three picks clean; `git patch-id --stable` identical to the originals (3113e502 / 2a12f232 / eb0cbe0b). Diff hk-int3..hk-int4: 9 files, +418 −46 |
| `build/kernel.int4` / `.unstripped` | `7b5e63287f2da99f346f634175f81c1fc5d1e68cd23e29ebe551b1fa6ada8c86` / `5c896caeff96920daba4e9981ae1e58dfaee406aa16d301cb8742bc5a45ae8be` |
| overlay | **int3-r1.ovl unchanged** `898740adf222a87498e7331860f47ed9b020ac84d8ff496c4d99e04c616db2f3` (65 records, 4 covers + obs1 mirror). fb120, ram-full and chg1 are kernel-only, and the overlays they were built with (int1-r1, obs1-r1) are subsets of int3-r1. |
| **`a7-ios-system-int4`** boot.img | **`78627bd97fa57c3f62f39eb01efa777c8a5749c3b7c15f1c01247305ddba1b59`** (payload 11616376…, 26,166,160 B, margin 39,894,128 B; manifest 1d4b97fb…) |
| boot-arg line | **1022 bytes, 57 tokens** (limit 1023; 1 B left) |

`check`: `OK a7-ios-system-int4 bootable 78627bd9…` with `tools/image_tool_int4.py` **and** with the Mac's shared `tools/image_tool.py`
(acf48b98; not edited). The manifest differs from int3 only in the line, kernel, ADT, payload, image, sizes, ids and the tool hash
(`receipts/manifest-diff.txt`).

## 1. Boot line (reconciled)

int3's line (1000 B) with exactly three changes, no collisions (each feature owns a different token):

| change | bytes | from |
| --- | --- | --- |
| `hk_fb_refresh=60` → `hk_fb_refresh=120` | +1 | fb120 |
| `blazer_mem=13` → `blazer_mem=16` | +0 | ram-full |
| `+blazer_battery_chg=2` after `blazer_battery=1` (chg1's position) | +21 | chg1 |

1000 + 1 + 0 + 21 = **1022**. Kept as in int3: `hk_bright=140` (int3/int4 kernels carry the 0001 backlight calibration, string
`SWEET BL: calibration %u table entries`, so the r2 CoreBrightness crash does not apply), `sweetfb_hz=60` (the fb120 phone boot ran with it
and still reached 65.3 kicks/s). Not added: `blazer_mem_test=4096` (21 B, no room; RAM.md step 2 is a separate boot), `hk_fb_refresh=121`
(fb120v's LTPO drop stays a later boot, FB120.md).

| token | what it does |
| --- | --- |
| `debug=0x8` `serial=3` | XNU debug flags; serial console |
| `cpus=5` | five A725 cores |
| `rd=ufsroot0` | root on the UFS LUN as a normal (non-ramdisk) boot |
| `msgbuf=1048576` | 1 MiB kernel log buffer |
| `varfs=1` | RAM /private/var with the image's overlay |
| `blazer_ufs=2` `blazer_ufs_live=1` `blazer_ufs_root=ios_system` `blazer_ufs_lun=0` | UFS driver, live mode, root partition by name `ios_system` on LUN 0 |
| `blazer_deadline=900` | planned panic → fastboot after 900 s |
| `launchd_unsecure_cache=1` `unentitled_ios_sim_launch=1` `ignition_level=1` `launchd_disable_all_timeouts=1` | launchd/boot policy relaxations |
| `sweetarm64e=1` | arm64e userland on the A725 |
| `autounlock=0` | no automatic keybag unlock |
| `interrupt-masked-debug-mode=0` | no panic on long interrupt-masked spans |
| `blazer_panic=1` | panic path into ramoops |
| `hk_fb_scanout=1` `sweetfb_noconsole=1` `sweetfb_hz=60` | framebuffer scanout to the panel, no text console, legacy console rate |
| `blazer_touch=1` `blazer_touch_bars=1` | touch controller (Laguna SPI) |
| `atm_diagnostic_config=0x400` | ATM diagnostics |
| `blazer_ufs_multi=1` `blazer_ufs_spin_us=300` `blazer_ufs_hold=1` | UFS queueing, polling, link hold |
| `blazer_ssbs=3` | Tensor CPU SSBS errata |
| `hk_fb_scale=1` `hk_fb_fast=1` | DPU scaler; fast 1.5-2.1 ms copy |
| **`hk_fb_refresh=120`** | **fb120**: 120 Hz by fast copy, publishes `displayMinRefreshInterval = 2^32/120`, 250-500 µs FRM_DONE poll |
| `hk_overlay=0xA0080081` | overlay group mask (int3-r1: covers + mirror) |
| `blazer_battery=1` | fuel gauge on SPMI SID 6 |
| **`blazer_battery_chg=2`** | **chg1**: read-only charger line per gauge sample (SID 3, 15 named frames, no write) |
| **`blazer_mem=16`** | **ram-full**: window to the MTE tag base 0xbe0f80000 (13.48 GiB managed), `hw.memsize` = installed 16 GiB |
| `blazer_thermal=2` `blazer_thermal_fast=1` `blazer_thermal_panic_c=70` | thermal monitor, fast sampling, 70 °C panic |
| `blazer_gov=1` `blazer_gov_cap=16` `blazer_gov_stages=15` `blazer_gov_b=40` | CPU frequency governor and its limits |
| `blazer_usbcon=1` `blazer_usbcon_ch9=1` | USB gadget console (live console, input, snapshots) |
| `blazer_rtc=1` `blazer_rtc_bounds=1` | RTC time publication with bounds check |
| `blazer_battery_status=1` | battery status to iOS |
| `hk_bright=140` | backlight 140 (calibrated AppleARMBacklight) |
| `blazer_aks_wrap=1` | software AKS wrap/unwrap (B1) |
| `blazer_keys=1` `blazer_power_key=1` `blazer_key_delivery=1` | volume/power keys into iOS |
| `blazer_haptic_tap=1` | haptic on tap |
| `blazer_netstack=1` | configd IONetworkStack stand-in |
| `hk_dbg=0x1e1e1f` | **int3 debug**: input, snap, usertrace, ustack (Preferences, MobilePhone), crashinfo, hk_screen 30 s, hk_top 30 s |
| `blazer_bootcpu=0x200` | boot CPU (added by image_tool) |

## 2. Kernel (HOST on the Mac, ARM64 verify on m1box)

- Branch made in a throwaway Mac worktree (`/tmp/hk-int4-wt`, removed; the shared tree stayed on p1): `git worktree add -b hk-int4 … hk-int3`,
  `cherry-pick cd60b8d 476c253 ca39cb4`, all clean. fb120 touches the framebuffer/scanout/DPU policy, ram-full `arm_init.c` +
  `blazer_memplan.h` + `SWEET.h`, chg1 `blazer_gauge.c` + `blazer_charger.h`; chg1 was cut on hk-obs1 2841211, whose content int3 carries
  as 25d3978, and applied unchanged.
- `tools/build_int4.py` (= int3's): exclusive `/tmp/fleet/kernel-build-slot.lock`, p1 clean check, `mk.sh -j8` **rc 0 (72 s)**, then
  **p1 b228c4f restored and rebuilt, rc 0**; the restored p1 kernel lacks all four feature strings. `receipts/build_int4.out`.
- **ARM64** (`receipts/kernel-verify.txt`): Mach-O arm64, NOUNDEFS, **`llvm-nm -u` = 0**. Present for every feature:
  - int3 debug: `_hk_dbg _hk_dbg_bits _hk_dbg_log _hk_ustack_start _hk_top_start _user_exception_trace`, `SweetHIDButtons::liveStart/
    liveSubmit/…`, strings `HK DBG: hk_dbg=`, `HK USTACK: every`, `HK SCREEN` ×5, `HK LIVE tap gen=`.
  - obs1: `_hk_obs_start/_exec/_exit/_console/_tick/_final/_panic _blazer_usbcon_obs`, `HKOBS %u %s t=%llu %s: %s`, `rules' libraries in one DYLD_INSERT_LIBRARIES`.
  - ABOUT: `_sweet_sandbox_syscall _sweet_sandbox_self_logged`, `self-check: sandboxed`; DBG1 `_blazer_usbnet_mode`.
  - fb120: `_sweet_fb_fast`; `AppleCLCD::paceNextUS` `cmp #0x78` + `mov #0xfa` / `#0x1f4` (250/500 µs); `sweet_scanout_attach` `sub #0x79`
    (121/122); strings `refresh 120 by copy: fast`, `fence on for hk_fb_refresh`.
  - ram-full: `_arm_init` with `_max_mem _max_mem_actual`, the plan's `csel` chain; `blazer-mem: full map` ×2, `blazer-mem: vm max_mem`.
  - chg1: `_blazer_gauge_read _spmi_frame _blazer_gauge_frames`, `blazer-battery: charger %u in=`, the mapping line's `charger reads %s`
    with literal `report only`.
  - Backlight calibration `SWEET BL: calibration` (keeps `hk_bright=140` safe).

## 3. Image (HOST, Mac)

`tools/mkimg_int4.sh` = int3's recipe with the int4 kernel, int3-r1 unchanged and `tools/image_tool_int4.py`. That tool is int2-ui's
`image_tool_int2.py` (91fd06ee, the hk_dbg allow-list) plus the three allow-list widenings that fb120/ram-full/chg1 made to their own copies
(`hk_fb_refresh=(60|120|121|122)`, `blazer_mem=([5-9]|1[0-6])`, `blazer_battery_chg=[12]`) and their kernel-string checks. One check is
new: `hk_fb_refresh=120` now requires the fb120 kernel, because an older kernel silently runs 120 as 60. The shared `tools/image_tool.py`
was not edited. `receipts/image-build.txt`, `image-check.txt`, `manifest-diff.txt`, `inputs-verify.txt`, `image_tool.sha256`, `SHA256SUMS`.

## 4. QEMU proof (m1box TCG, read-only phone root r3, 600 s each)

**qf-int4-r1: VERDICT PASS, 0 findings** (`receipts/qf-int4-r1.txt/.json`; run `/data/hackios-qemu/research/ios26-apps-r1/runs/qf-int4-r1`).
`qemu_preflight.py --keep hk_dbg=0x1e1e1f --keep hk_fb_fast=1 --keep hk_fb_refresh=120`, expect = `tools/qemu_preflight.expect.yaml` +
`qemu_int4.expect.yaml`.
- Home-equivalent at host 179 s (PosterBoard and iconservicesagent spawned; backboardd and SpringBoard each exec once, never respawned or
  crashed). **panics: 0.** TCG draws no Home frame.
- All base rows PASS (root on UFS, overlay, launchd, usermanagerd, backboardd, SpringBoard, Home daemons, no lsd abort, no NSURL-nil, no
  panic, netstack).
- int3: `overlay-65`, `about-covers` (4 of 4), `obs-dyld-merge`, `obs-hkobs`, `obs-mirror` (HKL SpringBoard mirror on), `no-blastdoor-sandbox-crash`,
  `no-ax-crash` (zero-event in TCG), `hk_dbg-screen` (HK SCREEN every 30 s, ≥3 captures), `hk_dbg-ustack`: PASS.
- fb120: `fb120-running` PASS: `SWEET FB: refresh asked 120, running 120, flip 0, interval 35791394` + `refresh 120 by copy: fast 1`.
- PHONE_ONLY: `hk_dbg-parsed` (usbcon line), `mem-full-map` (the standard rig drops blazer_mem), `charger-report` (no SPMI).
- Respawns only fairplayd.H2 (40) and com.apple.datamigrator (6), both within the base file's `respawn_allow` (rig without FairPlay hardware).
- `receipts/qf-int4-r1-int4only.txt` is the same run analysed with only the int4 file. It FAILs on those two respawns, because `--expect` replaces the
  default file instead of adding to it. Always pass both files.

**qg-int4-r1 (mem grow logic): VERDICT PASS, 0 findings** (`receipts/qg-int4-r1.txt/.json`, `qg-int4-r1-blazer-mem.txt`, args
`qg-int4-r1-args.txt`). RAM.md's harness variant `research/ios26-ram-r1/tools/qemu-ufsroot-ram.py --window-gib 15 --loader-gib 10`, run on
the **int4 kernel** with int4's translated line (incl. hk_dbg, hk_fb_fast/refresh=120) + `blazer_mem=15 blazer_mem_test=4096`:

    blazer-mem: window 0xa00000000 + 0x3c0000000, was + 0x280000000, hw.memsize 0x400000000
    blazer-mem: full map (QEMU fake), installed 0x400000000, managed 0xa00000000..0xdc0000000
    blazer-mem: vm max_mem 0x3c0000000, hw.memsize 0x400000000
    blazer-mem: test start 0xc80000000..0xdc0000000 stride 4096 / test written / test pass

Same lines as ramfull-grow1, plus every int3/fb120 row above PASS, Home-equivalent 218 s, 0 panics. QEMU's address map is not the phone's: this
proves the grow, readback and test path, not the phone's top range.

Not QEMU-provable: the phone window (0x882000000 + 0x35ef80000), the charger, the 120 Hz kick rate, live input/snapshots, the
BlastDoor/AX launches. Those are checked by `int4.probes.yaml` on the phone boot.

## 5. One probe file for the phone boot: `int4.probes.yaml`

    python3 -I tools/probe_eval.py --probes research/ios26-phaseb-r1/int4/int4.probes.yaml \
        research/laguna-usb-fix/attempts/<YYYYMMDD-HHMMSS-a7-int4> research/laguna-usb-fix/attempts/live-<…>-a7-int4

Nine milestone rows (never touch status.json): `int4-boot-line` (all four tokens; the HK DBG line stands in for the launchd boot-args line,
which is cut off before `hk_dbg`), `int4-home` (touch, buttons, frames, no SpringBoard/backboardd crash, no unplanned panic; owner or screenshot confirm),
`int4-hk-dbg`, `int4-live-input` (HK LIVE tap/swipe, done result=0, usbcon snapshot), `int4-obs-mirror` (65-entry overlay, 4 covers, HKL,
HKOBS), `int4-crash-fixes` (BlastDoor `self-check: sandboxed`, AccessibilityUIServer exec, no BlastDoor/AX CRASH), `int4-hz120` (running 120
+ `kicks ≥ 60.4/s`), `int4-ram16` (`window 0x882000000 + 0x35ef80000 … hw.memsize 0x400000000`, full map, `vm max_mem 0x35ef80000`),
`int4-charger` (`charger reads report only`, gauge sample, ≥2 `charger N in=…` lines).

Validation (`test/`): on the real int3 phone boot it scores debug/live-input/mirror/crash-fixes **works** and ram16 **fails** (12.92 GiB window). On
the real fb120 phone boot it scores hz120 **works** (65.3 kicks/s) and flags that boot's BlastDoor/AX crashes. On the hand-assembled
`test/expected-phone.synthetic.log` (SYNTHETIC, not phone output) all rows reach works, and Home is pending confirmation
(`test/expected-phone.synthetic.out`). On qf-int4-r1 with `--qemu`, the obs-mirror row is **works** and the Home row is pending confirmation
(`receipts/probe_eval-qf-int4-r1.txt`).
Expected and **not** int4 scope: Preferences/MobileSMS/FaceTime/Freeform… prewarm SIGABRTs (root r5 prune, INT3.md §6).

## 6. Phone test (coordinator; owner present; bare `fastboot boot`, return check after)

    tools/live_boot.sh research/images/a7-ios-system-int4/boot.img a7-int4 \
      --mach research/ios26-phaseb-r1/int4/build/kernel.int4.unstripped --wait 1080 --sync-tools --ui-script ui/settings_about_phone.ui
    # then research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-int4-after-boot

Phone on the USB cable for the whole boot (charger expects `in=usb`). While the UI script runs, or after it, the owner scrolls Settings for
~20 s so the 120 Hz row can see kicks above 60/s. Failure readings and rollbacks are the per-feature ones:
- 16 GiB: a panic in arm_vm_init means the top range is not ours. Fall back to `blazer_mem=13` (RAM.md §3).
- 120 Hz: `running 120` with kicks ≤ 60 means CoreAnimation is still at 60 (FB120.md §7).
- Charger: `unread` or `leaving the controller alone` (chg/PLAN.md).
- Any int4 fault: int3 eff0ed9f is the debug-only rollback.

## Files

`INT4.md`, `int4.probes.yaml`, `qemu_int4.expect.yaml`; `tools/build_int4.py`, `tools/image_tool_int4.py`, `tools/mkimg_int4.sh`;
`receipts/` (build, kernel-verify, image, manifest-diff, qf/qg preflight text+json, blazer-mem lines, probe_eval output, SHA256SUMS*);
`test/expected-phone.synthetic.log/.out`. Derived, not for git: `build/`, `research/images/a7-ios-system-int4/`.
