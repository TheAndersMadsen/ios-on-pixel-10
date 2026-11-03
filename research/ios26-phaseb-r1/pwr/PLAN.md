# pwr1: battery %, real time, volume and power keys, tap haptics in one image (2026-11-03, HOST build, not booted)

Image **`a7-ios-system-pwr1`**, boot.img **`719f69d3534ddbc2cebfee55c1fd4b3d95e395c7f02fa7d213c4f19d12283f96`**
(m1box `research/images/`, copied to the Mac's, same hash). `image_tool.py check`: `OK a7-ios-system-pwr1 bootable`.
Nothing here has run on the phone. Evidence labels: PHYSICAL = an earlier phone log, HOST = m1box/Mac, INFERENCE = reasoning.

## What each 🟡/⏳ row lacked, and the change

| Row | ✅ means | What the logs already show | What was missing | Change in pwr1 |
| --- | --- | --- | --- | --- |
| Battery gauge | the status bar shows the percentage | PHYSICAL r9-apps-ufs (`20261103-185039`): gauge `89% 4334mV`; powerd `powerd_percent_post rc=0`, `percent=89`; SpringBoard `_UIBatteryView setChargePercent: 0.89` (`battery_view_set`, `ui_scope=unproved`) | nobody has looked. `SBShowBatteryPercentage=true` is already in the active SpringBoard plist | **none in code**: an attended look. `blazer_battery_receipt=1` left out, because the line has no room for it (below) |
| Real date and time | the lock screen shows the correct time | PHYSICAL r9: RTC `2026-11-03 17:51:10 UTC`, host start 18:50:39 +0100 → correct UTC; `publish … ok 1` | **time zone.** The root's `/private/var.skel.tsv` line 184 seeds `localtime -> …/US/Pacific`, so iOS shows Pacific time (UTC−8). tzinit only resets the zoneinfo link (`Unable to locate data; resetting to system partition`, r9) and keeps a valid localtime | overlay: `localtime -> /var/db/timezone/zoneinfo/Europe/Copenhagen` (the owner Mac's `/etc/localtime`; present in `zoneinfo.default`) |
| Volume keys | an IOHID consumer-page service in iOS; volume HUD | PHYSICAL r9: backboardd opens `SweetHIDButtons` (`open … -> 1`, twice: it respawns). The pad read passed in keys-probe-r1; the chooser reads the same pads (`shim/keys_laguna.c`: 51 down, 52 up, 48 power) | the native key thread was never on in an iOS boot. The old route also sends a lone UP to a new client after a backboardd respawn (buttons_integration host repro) | XNU `0001-native-buttons-delivery` (reviewed: 517 checks under ASan/UBSan and TSan, 11 mutants); `blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1`. Consumer page 0x0c: up 0xe9, down 0xea |
| Power key | power = lock screen | as above; power is usage 0x30 on the same service | `SBDontLockEver=true` in the active SpringBoard plist (group 0): SpringBoard never locks, so the side button cannot lock (handoff "Power UI follow-up is HELD"). The line was 1032 B with the full keys | overlay: `SBDontLockEver` removed. `SBAutoLockTime -1`, `SBDisableIdleSleep`, `SBDontDimOrLockOnAC` stay, so only the side button locks. Reviewed power lifecycle (30 ms stable, release-to-arm) |
| Haptics | a felt buzz on a tap | PHYSICAL haptic-3-r2 (`20261102-041955`): CS40L27 id 0x40a270 rev b2, `trigger rom 0, stop after 100 ms`, EINT1 changed (0x8e8000 new), `ends: ok`. Felt: unconfirmed (unattended, 45 s after boot) | one effect per boot, at a fixed time, with no tap trigger | 0832 ROM-effect service, plus a new `blazer_haptic_tap=1`: each new touch contact (`SweetHIDTouch::touch`, `!was && down`) wakes a worker that plays the same ROM 0 / 100 ms effect; ≥250 ms apart, ≤300 per boot; EBUSY skips, any other error turns it off |

The haptic is **kernel tap feedback**, not CoreHaptics/UIFeedbackGenerator: iOS apps cannot ask for a buzz. That needs an
Actuator/AppleHaptics service and waveform backend, a separate and larger job (`docs/reuse/2026-11-02/audio-haptics.md`).

## Sources and builds

**XNU** (Mac `research/ios26-release-r1/work/xnu`, nested Git): new branch **`hk-pwr1` (c798a68)** from `hk-touch-direct` e731e68:

```
6ec2724  pick 44689e0  SweetKeyStore AKS wrap            (r10's kernel has these three; its line uses blazer_aks_wrap=1)
23ea0a2  pick eb2d19b  AKS user-session selectors
ad12d3d  pick cc42295  ramfs RENAME_SWAP/EXCL
e1d1768  0001-native-buttons-delivery.patch   00ce0bf8…  (ios26-opt-20261102/buttons_integration, unchanged)
b9f96eb  0832-blazer-haptic-native-rom.patch  97353f86…  (ios26-feature-haptics-r1, unchanged)
52f0299  0003-blazer-haptic-tap.patch         48ac1e8e…  (this lane: blazer_haptic.c, blazer_haptic_tap.h, SweetHID.cpp hook)
c798a68  MakeInc.def: -DBLAZER_KEY_DELIVERY=1 -DBLAZER_HAPTIC_SERVICE=1   (both runtime-off without their boot-args)
```

- `tools/build_pwr1.py`: flock `/tmp/fleet/kernel-build-slot.lock` (it waited for the Wi-Fi r3 build), refuses a dirty tree or one not on p1,
  builds, copies, then **restores p1 (b228c4f) and rebuilds it** (rc 0; tree p1, clean: `receipts/xnu-branch.txt`).
  Attempts a1 and a2 failed to compile (missing `<os/atomic_private.h>`; a2 ran with the stale patch because the tar copy to the Mac did not apply).
  Both restored and rebuilt p1. Logs: Mac `logs/pwr1-build{-a1,-a2,}.log`; `receipts/build_pwr1.out`.
- **kernel.pwr1 `b0e2e2fd…`**, unstripped `c7227a7c…`, UUID B9D0EC84-1663-3832-B79A-7D59C6363B61 (`receipts/symbols.txt`):
  ARM64 objects `blazer_haptic.o`, `hakios.blazer_keys.o` and `SweetHID.cpo` have `(__TEXT,__text)` `_blazer_haptic_tap`,
  `_blazer_haptic_play_rom`, `_haptic_thread` (tap worker inlined: `assert_wait`/`clear_wait`/`thread_block` relocations),
  `_sweet_hid_key_checked`, `_sweet_hid_keys_epoch`, `SweetHIDButtons::physical{Gated,Reset,Stop,Start,Request}`,
  `SweetHIDTouch::touch` with a `BRANCH26 _blazer_haptic_tap` relocation. Linked kernel: all of them in `__TEXT_EXEC,__text`,
  plus `_hh_play_rom` and `_ramfs_renamex`, and **0 undefined**. Strings: `tap feedback on`, `native ROM service ready`,
  `delivery requires reviewed power lifecycle`, `blazer-power-key: armed`, `SWEET PHYSICAL`.
- Host tests (`receipts/host-tests.txt`, `tap-mutants.txt`): tap policy 28/28 under ASan/UBSan; mutants 3/4 caught (`no-budget`
  is equivalent: `hh_tap_done` enforces the same bound); the 0832 harnesses pass on the applied `blazer_haptic_hw.c`.
  The buttons patch's own 517-check proof is reused unchanged (it applied to e731e68 with line offsets only).

**Overlay `pwr-r1.ovl` d0804b36bb540b1e63eeda033654e252ff4da8359b5c0f1d6f6d1af631b27b97** (611,256 B, 50 records), base perf-r1
95701ed9… (`tools/pwr_overlay.py`, `receipts/overlay.json`): [0] springboard.plist −SBDontLockEver (24 → 23 keys, binary);
appended `l /private/var/db/timezone/localtime`. 48 records byte-identical. `tools/pwr_consumer.c` with the e731e68
`varfs_overlay.h`/`hk_exec_rules.h`: **PASS, 233 checks** (both written under 0xA0080081, not overridden, exec rules identical).

**Image** (`tools/mkimg_pwr1.sh`, m1box, clang/LLD 23.1.4 `~/.local/share/hackios-host/llvm`, `TGL_TOOLCHAIN=llvm`): r10-perf's recipe
(kernel route ufsroot, 5 cores, bootcpu 0x200, canvas 1125x2511, window 0x882000000, `--qemu-run overlay-1`) with the kernel, overlay and line changed.
Payload 5a48e102…, margin 39,997,680 B, entry 0xfffffe000798b488 (= r10), AVB OK. `receipts/manifest.json`.

**Command line 1015 → 1003 B** (limit 1023). Versus r10-perf:

- added `blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1`
- `blazer_deadline=300` → `900` (the tool's default for `--bootcpu` with 5 cores; it refuses 1800 there). Home comes at about 110 s, and
  300 s leaves too little time for the checklist.
- **diagnostics dropped:** `hk_fb_probe=1` (the six-colour DPU probe and its 4.1 s hold of pid 1; fast-start/PLAN.md: "needed for nothing"),
  `hk_top=30` (CPU-top lines), `blazer_aks_log=1` (per-call AKS log, ~2,500 lines in r9), `blazer_persona_log=1`,
  `blazer_aks_usersession=1` (r9 on the phone: 0 user-session selector calls, so it is inert). Kept: `hk_usertrace=1` (crash decode).
  Not added for lack of room: `blazer_battery_receipt=1` (+25 B).

**image_tool.py** (m1box copy; it already had another owner's uncommitted LLVM-path edit; `patches/image_tool-pwr1.patch`):
allow `blazer_power_key=1`, `blazer_key_delivery=1`, `blazer_haptic_tap=1` and, as in the Mac copy, `blazer_aks_wrap=1`;
refuse delivery without keys + power and a kernel that has it, and refuse tap with any `blazer_haptic=` or a kernel without the service;
new `--drop-diag` (only `hk_fb_probe=1`, recorded as `dropped_diag` in the manifest). `test_image_tool.py`: 93 OK.
The m1box and Mac copies differ (Wi-Fi/ustack/usbnet entries are Mac-only). Merging them is the coordination thread's job.
For the overlay-1 existence check, `exit.json` and `console.log` of the Mac's run were copied to m1box (no frames).

## Attended checklist (owner present, one boot)

Before: note the Android battery % and have a correct clock nearby. Phone in hand, the USB cable on as usual.

```
tools/bootios research/images/a7-ios-system-pwr1/boot.img a7-ios-system-pwr1 \
  --mach research/ios26-phaseb-r1/pwr/build/kernel.pwr1.unstripped --wait 1080
```

Expect a **lock screen** first, not Home: SpringBoard may now lock. No colour blinking at the start (probe dropped).

- [ ] **T1 time:** the lock screen clock (or status bar) shows the correct local time, ±1 min, and the right date.
- [ ] **B1 battery:** the status bar shows a battery percentage close to Android's (on the lock screen or Home). Write down the number.
- [ ] **U unlock:** swipe up from the bottom: Home appears (no passcode). If a passcode pad or a stuck lock screen appears, say so and do H/V on the lock screen.
- [ ] **H haptics** (≥1 min after power-on): tap an empty spot 3 times, ~1 s apart. A short buzz with each tap? (yes / weak / none)
- [ ] **V volume:** press Volume Up once (~0.5 s), wait 3 s, Volume Down once, wait 3 s; once more each. The volume HUD appears and its level goes up, then down.
- [ ] **P1 power lock:** one short press (~0.5 s) of the side key. The lock screen appears or the display goes dark.
- [ ] **P2 wake:** after 5 s, one short press again. The lock screen appears, with the right time (T2) and battery %.
- [ ] **P3:** swipe up: Home again, touch works.

Rules: never hold the side key longer than ~1 s; no chords. Never press power on a fastboot screen (it can select Android).
**Stop** (put the phone down and let the 900 s deadline end the boot) on: a panic, Home lost for good, the display dark and not waking
after P2 + 10 s, a key that acts held/stuck, or a buzz that does not stop. Rollback: deadline/PSCI reset to fastboot, then the
return check (`research/ios26-dualboot-r8/attempts/return-after-restore/`). Nothing is written to the phone: the root is read-only
and /private/var is in RAM.

## Read-out (ramdump `kernel.log`)

- T: `blazer-rtc: … publish … ok 1`; launchd `tzinit` with **no** `localtime link invalid; resetting` line.
- B: `HKBATT: event=battery_view_set … value=0.NN`. The owner's number must equal `percent=` within 1.
- V/P: `blazer-keys: legacy mode`, `blazer-keys: polling pads`, `blazer-power-key: armed after stable release`; per press
  `SWEET PHYSICAL: epoch=… key=1 usage=0xe9` / `key=2 usage=0xea` / `key=0 usage=0x30` with `clients=N≥1`, down then up.
  A callback line with no HUD means the kernel delivered and iOS did not show it: an audio/SpringBoard question, not a key one.
  `forced release` or `ignored sample` lines are faults.
- H: `blazer-haptic: native ROM service ready 1`, `tap feedback on: rom 0, 100 ms`, then `tap N rc 0` for the first 8 taps.
  A `tap N rc` other than 0 means the service is off for the rest of the boot. `rc 0` with no felt buzz means the command
  ran but the motor was not felt; next try another ROM index (`blazer_haptic_index`, needs an allow-list entry).

| Result | Row becomes |
| --- | --- |
| T1 and T2 right | Real date and time ✅ |
| B1 matches `percent` | Battery gauge ✅ (visible); fresh-receipt proof still separate |
| V HUD moves both ways, matching `SWEET PHYSICAL` | Volume keys ✅ |
| P1 locks, P2 wakes to the lock screen | Power key ✅ |
| buzz felt on the taps | Haptics ✅ (kernel tap feedback; app haptics still ❌) |

## Proposed NOTES.md line (for the coordination thread)

- **pwr1 (2026-11-03, HOST, not booted):** `a7-ios-system-pwr1` (719f69d3…) = r10-perf + XNU `hk-pwr1` c798a68 (keys 0001, haptics 0832 +
  tap feedback) + overlay pwr-r1 (lock on the side key, localtime Europe/Copenhagen; the seed said US/Pacific). Attended
  checklist in `research/ios26-phaseb-r1/pwr/PLAN.md`.

Commit request (coordination; nothing staged here): tracked change `tools/image_tool.py` (`patches/image_tool-pwr1.patch`, on top of the
existing uncommitted LLVM edit by another owner). Force-add the way other Phase B receipts are (research/ is ignored): `pwr/PLAN.md`, `pwr/tools/*`,
`pwr/tests/test_tap.c`, `pwr/src/*`, `pwr/patches/*`, `pwr/receipts/*` (hashes in `receipts/SHA256SUMS`). Not the kernels, the objects or the overlay.
Message: "pwr1: keys, power lock, local time zone and tap haptics in one image (a7-ios-system-pwr1 719f69d3, not booted)".
