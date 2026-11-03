# r8 slowness: launchd and Spotlight spin, Control Center black, Settings frozen (2026-11-03, HOST fix, not booted)

**Physical input:** `a7-ios-system-r8-settings`, attempt `research/laguna-usb-fix/attempts/20261103-183626-a7-ios-system-r8-settings`
(ramdump `kernel.log`; the boot is in it twice; numbers below are from the first copy, lines 1..23700). Owner: Settings draws
but takes no taps or scrolls; Control Center draws black/transparent. Bounded extract: `receipts/r8-evidence.txt`.

## 1. launchd at ~28 s CPU per 30 s: audiomxd's Bluetooth audio lookup storm, caused by r8 itself (PHYSICAL log, host reading)

- **485,871 failed lookups of `com.apple.BTAudioHALPlugin.xpc` by audiomxd** (2,236 logged lines plus 483,635 "Last log
  repeated"), about 1,900 per second for the whole boot, plus 249 of `com.apple.bluetooth.xpc`. Every other client together
  makes a few hundred. launchd answers every one (`error = 3`) and logs it: launchd 25.5 / 31.2 / 28.3 … s per 30 s window,
  audiomxd 5.5–7.0 s.
- **r8 caused it.** r8's one change was moving `com.apple.bluetoothd` into launchd's disabled set, so its 15 Mach names stopped
  being registered. audiomxd's BT HAL plugin retries the missing name in a tight loop. Every boot with bluetoothd still loaded
  and refused at exec (hk_deny) has **0** BTAudioHALPlugin lines and a quiet launchd (after start-up 0.1–0.3 s per window,
  audiomxd ≤0.2 s): p29 ×7, r3, r4-bl, b1-aks, r7-touch and r9-apps-ufs.
- r8 also disproved the reason for its change: Preferences made **0** bluetooth lookups (the FIX.md "decisive line" is
  absent), so Settings never asked bluetoothd. Following settings/FIX.md's Read-out, the "Fail without one" branch applies.
- **Fix:** take `com.apple.bluetoothd` out of the disabled set again (160 → 159 labels). The record is byte-identical to the
  r7/r9 one (6930d06f…). bluetoothd stays refused at exec by the hk_deny row that was never removed.

## 2. Spotlight at ~31 s per 30 s: the Spotlight search app spins after the Home pull-down (PHYSICAL log; cause unproved)

- `Spotlight[136]` is the UIKit app `com.apple.Spotlight`. SpringBoard pre-launches it, and it is idle until the owner pulls down on Home
  (touches 657,1402→759,2296 and 705,2297→826,1271, ~t=105). Then it uses a full core in every window: 30.98 / 30.97 / 30.94 /
  30.94 / 30.89 / 30.93 s. Its memory passes the 300 MB soft limit (`crossed memory high watermark (300 MB)`), and the kernel
  reports `thread 1458 caught burning CPU! … more than 50% CPU over 180 seconds`. Its AKS sel-17 calls (MKBGetDeviceLockState)
  go from 498 to 33,234 (~130/s).
- This is the same spin as in p29 (sampler-verify-p29-r1 and p29-live-r1: Spotlight ~30.6 s per 30 s after search UI was used).
  There the sampled chain was `-[SPUISearchHeader updateDictationButtonEnabledStatus]` → `+[UIDictationController
  dictationIsFunctional]` → `deviceStateIsLocked` → MKB → AKS sel 17
  (`research/ios26-opt-20261102/handoffs/opt-spotlight_runtime.md`). That handoff left the cause of the loop unknown, and it still is.
  It does not need bluetoothd to be disabled (p29 had it loaded).
- **Fix (disable):** add `Spotlight` to the overlay's hk_deny row (`bluetoothd,Spotlight`). Its exec then fails with EBADARCH, the same
  route as bluetoothd. Cost: no Home search. Risk: SpringBoard may retry the launch. That is in the read-out below.

CPU was not the limit in r8: 5 cores give 150 s per window and the system used 55–85 s. So neither spin "starves" Settings
directly (see 4).

## 3. Control Center black/transparent: Reduce Transparency and Reduce Motion defaults (inference)

There is no GPU (no `IOAcceleratorES`). Control Center's modules are blur and vibrancy materials (backdrop layers), and these
come out black or transparent here. The overlay's `CA_DISABLE_BACKDROP_CACHE`/`CA_DISABLE_FILTER_MERGING` rows for backboardd are in
inactive groups (14, 15) and stay off.
**Change:** a new `/private/var/mobile/Library/Preferences/com.apple.Accessibility.plist` (group 0, 0600 mobile:mobile, binary
plist, 158 B) with `EnhancedBackgroundContrastEnabled` (Reduce Transparency: materials become opaque fills),
`ReduceMotionEnabled` and `ReduceMotionReduceSlideTransitionsPreference` (cross-fades instead of zoom/slide: fewer animated
frames for backboardd) set to true. The key names are read from libAccessibility's preference-key table in the 23G90 dyld cache
(`/data/hackios-qemu/dsc-r6`, subcache .01, next to `ReduceMotionAutoplay…`, `DarkenSystemColors`). That the domain is read from this
file at boot is the standard iOS layout. It is not proven on this root.

## 4. Settings: not starved, not waiting on bluetoothd; blocked vs. touches-not-delivered still open, so r10 measures it

What the logs show (r7 and r8):
- **Not CPU-starved.** r7 froze the same way with an idle system (after t=211 the whole system used <1.3 s per 30 s), and r8
  had 65–95 s of spare CPU per window. Preferences used 2.6–2.7 s in its launch window, then less than the 8th process
  (<81 ms) while the owner scrolled.
- **Not launchd latency, as far as visible.** Preferences' 30 failed lookups (duetexpertd, spotlight, wifi.manager ×14 …) were
  answered within the same second as its spawn, under r8's storm. r7 froze without any storm.
- **Not bluetoothd.** r8: 0 bluetooth lookups by Preferences.
- What is left: (a) the main thread is blocked on something else, (b) the app's scene never gets the touches
  (backboardd/SpringBoard touch gating, touch/FIX.md "Fail"), or (c) it handles them but its commits are not shown.
  Nothing in the kernel log tells these apart, because no userland stack is recorded.

**Change: PERF's `hk_mainwatch.dylib` in Preferences** (hk_env row: `+:/private/var/hk/hk_mainwatch.dylib`, `+HK_MAINWATCH=1`;
no other process's environment changes). It is a read-only watch, `src/hk_mainwatch.c` (2811dd02…):
- a no-op is posted to the main queue every second. Every 10 s (up to 60 lines):
  `HKMAIN: Preferences[pid] t= pings= wait= state= ev touch= press= other= stalls=`. `ev` counts `-[UIApplication sendEvent:]`
  by event type (the original method always runs), and `state` is `applicationState`;
- if the main queue is ≥3 s late (sampled every 5 s, up to 20 samples) it prints `HKMAIN: stall … pc lr sp dsc_slide main_slide`
  and `HKMAIN: frames …` (fp chain, PAC bits masked). These can be symbolized with `ios26-apps-r1/tools/m1box/dsc_sym.py`;
- `HKMAIN: gap N ms` if the process itself was frozen (RunningBoard suspension).
- The PERF agent's bug fix (nanosleep took 1e9 ns, which is invalid → busy loop) was already in the Mac copy and is kept. Host test on macOS
  (fake UIApplication, 8 s main-thread block, SIGSTOP 5 s): `receipts/mainwatch/host-check.txt` **14/14 PASS** (stall frame in
  `block_main`, touch=3 press=1 other=1, gap 4091 ms, ~1 ping/s); gate off: silent and sendEvent: untouched.
  Device dylib: arm64e, iphoneos SDK, `pacstrip --sign` ("no PAC code"), `codesign --verify --strict` clean
  (`receipts/mainwatch/`, dylib f06b9a00…). Not run on iOS yet. It writes to /dev/console, the route hkart already uses from Preferences
  (`HKART: Battery lookup fallback installed` appears in r8).

| r10 HKMAIN result while the owner taps/scrolls in Settings | Meaning |
| --- | --- |
| `wait` grows, `stall` lines repeat with the same frames | **blocked**: symbolize the frames; that names the call |
| `pings` +~10 per beat, `wait=0`, `ev touch` does not grow | **touches not delivered** to the app (scene/touch gating) |
| `pings` normal, `ev touch` grows, screen does not change | the app handles input; **its commits are not shown** (render server side) |
| `gap` lines, or beats stop | **suspended/starved** by the system (RunningBoard), not by CPU |

## Overlay `perf-r1.ovl`

- Base: `settings/overlays/settings-btdisabled-r1.ovl` ee7554b9… (as instructed). Tool `tools/perf_overlay.py` (ed1ba4bd…; mkoverlay
  pack/fnv1a/env_ok/deny_ok, restore_cloudd decode as second walker, pinned base hash, refuses to overwrite).
- Output **95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55** (611,168 B, 49 records).
- vs ee7554b9 (`receipts/decode-diff.txt`): 44 identical; [14] disabled.plist 7484 → 7442 B (= r7/r9 record, 6930d06f…);
  [39] hk_env Preferences rule only (711 B with NUL, max 1024); [42] hk_deny `bluetoothd` → `bluetoothd,Spotlight`;
  appended [47] `/private/var/hk/hk_mainwatch.dylib` (group 29, 0755 root, 69,024 B) and [48] the Accessibility plist.
- vs r9-apps-ufs's own overlay f5d4c367 (`receipts/decode-diff-vs-r9.txt`): 45 identical; only [39], [42], [47], [48].
- Release consumers (`tools/perf_consumer.c` f3fc62d0…, ASan/UBSan, pinned headers == live: `receipts/release-headers.txt`):
  hkov_check/cover/groups pass; every changed or appended record is the one varfs writes under 0xA0080081 (not overridden);
  `hk_list_has` matches `Spotlight` and `bluetoothd` and not `SpotlightIndex`/`Spotligh`/`Preferences`; only Preferences'
  exec environment changes. `receipts/consumer.txt`: **PASS, 291 checks**.

## Image `a7-ios-system-r10-perf` (Mac `research/images/`, HOST build)

- Recipe: `a7-ios-system-r9-apps-ufs` exactly (`ios26-apps-r1/usersession/mkimg.sh`, ufs variant: kernel
  `kernel.rootview-bl-aks-us2` d7f47431…, `--phone-route ufsroot`, 5 cores, bootcpu 0x200, canvas 1125x2511, deadline 300, the same
  phone-args incl. `hk_bright=140 blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_persona_log=1`). Only `--var-overlay`/`--var-overlay-sha`
  differ. Script `tools/run_mac.sh` (0ab00626…); image_tool.py 45eadfe3… (the same as r9).
- **boot.img b851cd25e20a1885a5262746a39cb05a0af23d669556b7d204eeabcc85de061d**, payload 8a800cd7…, margin 39,999,328 B.
  `image_tool.py check`: `OK a7-ios-system-r10-perf bootable`.
- **Cmdline diff vs r9-apps-ufs: none** (1015 → 1015 bytes, 57 tokens, identical). Manifest diff (`receipts/manifest-diff.txt`):
  var_overlay (path, sha, 541,768 → 611,168 B, placed size 0x88000 → 0x98000), and what follows from it: kernel_end +0x10000,
  the ADT/boot-args positions (plan), payload, image and AVB size. The rest are per-build values (ADT seed, nonces, epoch). Entry is unchanged.
- No XNU build was needed (overlay-only), so the kernel-build-slot lock was not taken and the Mac's nested XNU repo and p1 were not
  touched. Mac scratch (host-test binaries, dSYMs, consumer) was deleted. Only the image dir and `perf/out/hk_mainwatch*` stay.

## Attended test (owner, bare `fastboot boot`, then the return check)

`tools/bootios research/images/a7-ios-system-r10-perf/boot.img a7-ios-system-r10-perf --mach research/ios26-apps-r1/usersession/build/kernel.rootview-bl-aks-us2.unstripped --wait 480`

1. Wait for Home (r9-apps-ufs reached it on `rd=ufsroot0`). Do **not** pull down on Home first.
2. Swipe down from the top-right for **Control Center**: say whether the tiles are now opaque grey/dark (not black/see-through),
   then close it.
3. Tap **Settings**, wait ~5 s, then, with a few seconds between steps: scroll the list down and up; tap **General**; tap the
   back button; tap **Accessibility** > **Motion** (Reduce Motion should show ON) if it responds. Note the time of the first
   gesture.
4. Keep using Settings for ~30 s even if frozen (the watch prints every 10 s), then go home.
5. Last: pull down on the middle of Home (Spotlight search). Expected: nothing opens, no hang.
6. The owner says what worked in 2, 3 and 5.

Stop: a panic other than the 300 s deadline, Home lost, a backboardd SIGSEGV loop, a SpringBoard crash loop, or Spotlight
spawn failures fast enough to keep launchd busy (see read-out). Rollback: deadline/PSCI reset to fastboot, then
`return-check.sh`. Nothing is written (root read only, `/private/var` in RAM).

## Read-out (ramdump)

- **launchd/audiomxd:** `HK TOP` launchd back to ≤~0.3 s per window after start-up and audiomxd ≤~0.2 s. 0 or a few
  `BTAudioHALPlugin` failed lookups. `hk_deny: bluetoothd refused` and the bluetoothd penalty box are back, as in r3–r7/r9.
- **Spotlight:** `hk_deny: Spotlight refused` (expected once at SpringBoard's pre-launch, and once more per Home pull-down). No `Spotlight[N]` in
  HK TOP. If `UIKitApplication:com.apple.Spotlight` spawn/failed lines repeat faster than about once per 10 s, or SpringBoard
  respawns, the deny is wrong: next try is leaving Spotlight loaded and suppressing the dictation button instead.
- **Accessibility:** CC look (owner). On the log side, no new crash in SpringBoard/backboardd.
- **Settings:** the `HKMAIN:` lines, read with the table in section 4. `HKMAIN: Preferences[N] watching the main thread` and
  `sendEvent: counted for …` must appear; if they are missing, the dylib did not load (check `hk_env: Preferences gets …`).
