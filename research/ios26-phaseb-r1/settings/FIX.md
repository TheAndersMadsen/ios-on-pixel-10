# Settings frozen after launch: bluetoothd's names stay registered with no server (2026-11-03, HOST fix, not booted)

**Physical symptom** (`a7-ios-system-r7-touch`, attempt `research/laguna-usb-fix/attempts/20261103-170531-a7-ios-system-r7-touch`,
kernel.log bb2ffea0…). Home works, and Settings opens and draws its list. After that it is frozen: no scrolling, and taps do
nothing. System gestures (going home) still work. Touch reaches the system as direct touches (`SWEET HID: touch registered, …
direct touches`), and the touch FIX's event-type fix is in.

## Evidence (physical log, host reading)

The ramdump holds the boot twice (lines 1..17150 and a second copy). Positions below are from the first copy.

| t (HK TOP) / wall clock | What happens |
| --- | --- |
| 16:06:43.09 (t≈125) | Owner taps Settings at 196,331. `hk_env: Preferences gets …hkart.dylib`, `Preferences[141]` spawned. |
| 43.3 to 45.36 | Preferences' failed lookups, **all `error = 3: No such process`**: duetexpertd.SettingsActions, uiintelligencesupport.agent, identityservicesd.embedded.auth, spotlight Search/IndexAgent, familycircle.agent, softwareupdateservicesd, wifi.manager ×4 (×8 counting the duplicate copy), identityservicesd.nsxpc ×2, corewifi.internal-xpc. The last one is at 45.36. |
| 45.9 to t=151 | 4 gestures: scroll up 346,1986→207,829; scroll down 299,835→241,2186; tap 427,1324; top-right pull-down. |
| t=121..151 | `Preferences[141]=2621` ms (launch and first draw, plus these gestures). |
| t=151..181 | 4 more gestures (515,888→312,11; 464,1938→175,222; 238,225→0,89; tap 435,1278). `Preferences[141]=56` ms, while backboardd used 6750 ms, SpringBoard 1400 ms and `frames+118` (system animations). |
| t≥211 | No more touches. Preferences is not in the top 8 (<~15 ms per 30 s). `frames+0/1` (clock only). The 300 s deadline ends the boot. |

What the log shows:

1. **None of the listed failed lookups can block.** Each is `error = 3` (the name is not registered). The client's
   connection is invalidated at once, and a reply-sync call returns `XPC_ERROR_CONNECTION_INVALID` without waiting. Every one
   of them is a label in the overlay's active `disabled.plist` (identityservicesd, softwareupdateservicesd, familycircled,
   duetexpertd, searchd …; group 7, 159 labels). wifid is not loaded at all: `Failed to bootstrap path: …com.apple.wifid.plist,
   error = 138: Service cannot be loaded on this hardware` (its `_LimitLoadToDeviceTree` wants a `wlan`-type ADT node).
   CommCenter is loaded and **running** (pid 43, `job state = running`, making its own lookups). A stuck CommCenter is not ruled out, but nothing in the log points at it.
2. **bluetoothd is the one service whose names are registered with nothing behind them.** The overlay refuses it at exec
   (`hk_deny: bluetoothd refused, EBADARCH`). launchd therefore keeps the job loaded: `Service could not initialize:
   posix_spawn(/usr/sbin/bluetoothd) EBADARCH`, then `Service setup event to handle failure and will not launch until it
   fires`, then at 16:06:30 `cannot spawn: service is in penalty box`. Its plist (root, `com.apple.bluetoothd.plist`) registers
   15 MachServices, among them `com.apple.server.bluetooth`, `.general.xpc`, `.classic.xpc`, `.le.att.xpc`,
   `com.apple.bluetooth.xpc` and `com.apple.BTAudioHALPlugin.xpc`. A lookup of these names **succeeds silently** (no log
   line), and the message waits in a queue nobody drains. A reply-sync or semaphore-wait caller never returns. Penalty-box and
   failed-init services in the whole boot: only bluetoothd. AccessibilityUIServer respawns every ~10 s (SIGABRT) and
   fairplayd.H2 exits on each demand, but in both cases connections break or get served; neither stays registered and
   silent.
3. **Settings talks to Bluetooth from its root list.** `/Applications/Preferences.app/Preferences` (root image, same
   userland) links CoreBluetooth, WiFiKit, CoreTelephony, AppleAccount(UI) and HeadphoneSettings. It has
   `BluetoothListItemProvider` and `WiFiListItemProvider`, an `So12CBControllerCSg` (`CBController?`) `bluetoothController`
   with `bluetoothState`/`setBluetoothStateChangedHandler:`/`activateWithCompletion:`, and CoreTelephony
   `getSubscriptionInfo:`. In the dyld cache, `bluetoothStateChangedHandler` belongs to CoreBluetooth's CBController.
4. Preferences made no further lookups after 45.36 and used ~0 CPU from then on. A bluetoothd lookup leaves no line
   (it succeeds), so this pattern fits a main thread parked on a bluetoothd reply. It does not prove it.

**Cause (inference; not proven):** Settings' main thread waits for a reply from a bluetoothd Mach service that launchd
registered but can never start. The rest of the system keeps working (SpringBoard handles home gestures), which is
the observed picture. What is not shown: the blocking call itself. `activateWithCompletion:` is async, so the waiting
frame is either a sync getter in the CBController/HeadphoneSettings path or a SwiftUI/Swift-concurrency wait on it. No
userland stack sampler exists in the project. `runtime/ca_sampler` samples pixels in backboardd's QuartzCore, and
`runtime/exit_trace` fires only at exit, so the frame could not be read from this boot.

**Competing explanation (the touch FIX's "fail" branch):** the touches never reach the app. backboardd's per-scene touch
gating (`BKSSceneHostTouchBehavior*`) can hold an app whose scene did not become foreground-active. That also gives
"draws but frozen, system gestures work, ~0 app CPU". The r8 boot below tells the two apart (see Read-out).

**QEMU:** cannot check this. The m1box TCG guest (r16, 15 min) is still on the Apple logo, SpringBoard is not on Home, and
there is no Settings launch. Scripted taps (`sweethidtest`/`tegu_gesturetest`) need a Home first. No run was spent.

## Fix options, ranked by the evidence

| Option | Verdict |
| --- | --- |
| (a) start the missing daemon | wifid: refused by launchd (no `wlan` ADT node, error 138), and its lookups already fail fast. bluetoothd: it would exit (1) on keychain adds (`connectivity-r1/bluetooth/PLAN.md`, needs the software AKS wrap and B2/B3). Neither is possible now. |
| **(a′) unload bluetoothd instead of denying its exec (chosen)** | Put `com.apple.bluetoothd` in the disabled set the overlay already uses. launchd then does not load the job and registers none of its 15 names. Every bluetooth lookup fails at once (`error = 3`), like the other services Settings asks for. One plist key, no code. |
| (b) stub service | Not needed for (a′). It is the fallback if a client cannot cope with an absent name, i.e. it crashes instead of waiting. |
| (c) timeout interposer in Preferences | Only after a sampled boot names the call (see below). |
| (d) defaults that hide cells | Not looked for. Hiding a cell would leave the dead names registered for every other client (audiomxd's BT HAL plugin, SpringBoard). |

## Change: overlay `settings-btdisabled-r1.ovl`

- Base: `research/ios26-phaseb-r1/accel-wait/build-mac/overlays/artwork-container-battery-observe-accel-skip-r1.ovl`
  f5d4c3676d1cf78c1b21036b784819d66425ce6bb55c27a46eee17f277412a97 (r7-touch's overlay).
- Tool: `tools/disable_bluetoothd.py` (695ca8ff…), pinned to that base. It decodes with
  `ios26-overlay2-r1/tools/restore_cloudd.py`, adds `com.apple.bluetoothd = true` to record 14 (group 7, the active
  `/private/var/db/com.apple.xpc.launchd/disabled.plist`, 159 → 160 labels, 7442 → 7484 B; XML sorted, so the plist text diff
  is exactly those two lines), and recomputes the FNV-1a body hash. The other 46 records are byte-identical,
  including `hk_deny bluetoothd`, which now never fires because launchd no longer spawns the job.
- Output: **ee7554b9aba04d437992e3dbea73a9bdd5c444273b6cecd6fa3d9cfbf950a3ca** (541,808 B, 47 records).
- `receipts/decode-diff.txt`: 46 identical, 1 differing ([14] disabled.plist, 6930d06f… → 0524b78c…).
- `receipts/consumer.txt` (`tools/settings_consumer.c`, built with ASan/UBSan against the release kernel's own
  `varfs_overlay.h`/`hk_exec_rules.h`, pinned copies == live tree): `hkov_check`/cover check pass; the changed record is the
  one varfs writes under 0xA0080081 (not overridden); hk_env (661 B) and hk_deny are identical; every process gets the same
  exec environment. `PASS … 268 checks`.

## Image `a7-ios-system-r8-settings` (Mac `research/images/`, HOST build)

- Recipe: r7-touch's exact recipe (A7-READY step 6, `kernel.rootview-bl-touch` cf906599…, 5 cores, bootcpu 0x200, deadline 300,
  canvas 1125x2511, the same phone-args). Only `--var-overlay`/`--var-overlay-sha` changed. Script `tools/run_mac.sh`.
- **boot.img 73a1311d466d0ee58e6ea18cf187a9c98693b8e03f7447036074bb24177a53b6**, payload efa31d80…. `image_tool.py check`:
  `OK a7-ios-system-r8-settings bootable`. image_tool.py b56ae2bd… (the same as r7).
- **Cmdline diff vs r7-touch: none** (1013 → 1013 bytes, 57 tokens, identical). Manifest diff (`receipts/manifest-diff.txt`):
  var_overlay (path, sha, bytes +40), and the payload and image that follow from it. The rest are per-build values: ADT seed,
  nonces, epoch. mach, segs, plan and placement are unchanged.

## Attended test (owner, bare `fastboot boot`, then the return check)

`tools/bootios research/images/a7-ios-system-r8-settings/boot.img a7-ios-system-r8-settings --mach research/ios26-dualboot-r8/rootview/kernel.rootview-bl-touch.unstripped --wait 480`

1. Wait for Home, then tap Settings.
2. Inside Settings, with a few seconds between steps:
   1. Scroll the main list down to the bottom and back up.
   2. Open **General**, then **About**. The About page should show (name, iOS version, model).
   3. Go back with the top-left back button, then once more with a swipe from the left edge.
   4. Toggle something twice, e.g. **Airplane Mode** on the root list, or General > Keyboard > Auto-Capitalisation.
   5. Open the **Bluetooth** row. It may show an empty or "unavailable" page; say what it shows.
3. Go home and open Settings again; say whether it still responds.
4. The owner says which steps worked.

Stop: any panic other than the 300 s deadline, a backboardd SIGSEGV loop, Home lost, or a SpringBoard/audiomxd crash loop
(new risk: they now see the bluetooth names fail instead of hang). Rollback: the deadline/PSCI reset returns to fastboot,
then `return-check.sh`. Nothing is written: the root is read only and `/private/var` is in RAM.

## Read-out (from the ramdump)

- Expected new lines: no `hk_deny: bluetoothd refused` and no `com.apple.bluetoothd` spawn/penalty-box lines.
  `failed lookup: name = com.apple.server.bluetooth…` / `com.apple.bluetooth.xpc` with `error = 3`.
- **Decisive line:** a `failed lookup … bluetooth… requestor = Preferences[N]`. It shows Settings did ask bluetoothd. In r7
  that request was a silent success into a dead queue.
- `HK TOP Preferences[N]` in the windows with in-app gestures: hundreds of ms when it responds (r7: 56 ms for 4 gestures).
- **Pass:** steps 2.1 to 2.4 respond. Cause confirmed.
- **Fail with a Preferences bluetooth failed-lookup line:** bluetooth was asked but was not the only wait. Next is the
  sampled boot.
- **Fail without one:** Settings never asked bluetoothd. Then the touch-gating explanation leads
  (`BKSSceneHostTouchBehavior*`, touch/FIX.md "Fail"), plus the sampled boot.

## Proposed sampled boot (not built; only if r8 fails)

No userland sampler exists. Proposal: `hk_mainwatch.dylib`, injected into Preferences through the existing hk_env row,
the same way as hkart. A constructor starts one thread. Every 2 s it posts a no-op to the main queue. If the no-op has not
run after 3 s, the thread suspends the main thread, reads its pc/lr/fp with `thread_get_state`, walks up to 16 frames, and
prints `HKMAIN: stall N ms pc … lr … frames … slide …` to /dev/console. It uses the mach_header slide, as `hk_exittrace_v2`
does, and stops after 20 records. Symbolication uses `dsc_sym.py`. Building it follows accel-wait/build-mac: an arm64e
dylib, codesign, `decode_diff.py` and the consumer, and the overlay gets the dylib plus one hk_env edit for Preferences.
