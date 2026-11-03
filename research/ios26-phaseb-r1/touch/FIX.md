# Touch inside apps: the events were indirect touches (2026-11-03, HOST fix, not booted)

**Physical symptom** (`a7-ios-system-r5-accel`, attempt `research/laguna-usb-fix/attempts/20261103-162351-a7-ios-system-r5-accel`,
owner present). Home → Settings works. Nothing inside Settings responds to a tap. Pulling down from the top shows no
Control Center.

**Cause (static, from the iOS 26 dyld cache; not yet proven on the phone):** UIKit routes each digitizer collection by the
event field `kIOHIDEventFieldDigitizerIsDisplayIntegrated` (0xb0019): 0 means an indirect touch (trackpad-style), 1 means a
direct finger. SweetHIDTouch published only the *service property* `DisplayIntegrated`. Its events never set the *field*
(`IOHIDEvent::digitizerEvent()` leaves `options.displayIntegrated` at 0). So every physical tap reached UIKit as an indirect
touch. The touch driver's decode and scaling are correct.

## Evidence

### Kernel log (physical observation, r5-accel ramdump `kernel.log`)

- The touch path is clean: `tcm: panel 12799 x 28559, up to 10 objects`; `1750 messages, 1750 reports, 16 touches, 0 bad`; 16 downs,
  each followed by one up. In-app taps show no movement: `down at 590,1648` then `up at 590,1648`, and the same at 893,1811
  and 1022,2296.
- **The "out-of-range x" is not out of range.** `tcm: finger 0 down at X, Y` prints the value *after* `blazer_tcm.c` scales
  it to 0..65535 (`x * 65535 / scale_x`, with `scale_x = max_x = 12799`). So `59395, 383` is raw panel 11600/12799, 167/28559,
  and `65535` is the clamp at the bottom row. The next line agrees: `SWEET HID: touch 0 down at 1159,16` = 59395·1279/65535 in
  panel pixels. Every one of the 16 logged pairs comes back exactly from an in-range raw value (host test below). This is not a
  sign bug, a 16-bit decode bug or a different report type.
- **The touches never reached Settings.** HK TOP t=188..218 covers 12 owner gestures (taps, scrolls, left-edge back swipe, two
  top-right pull-downs). In that window `Preferences[141]=42` ms CPU, while `SpringBoard[5]=3717`, `backboardd[22]=30661` and
  `frames+439`. Settings was alive (it launched with 2543 ms at t=68..98, no exit). Something on SpringBoard's side animated;
  the app did no work.
- Not the cause: the coordinates (Home taps land on the icon, so the mapping is right) and the timestamps (`mach_absolute_time`,
  the same for SpringBoard and apps). Touch-up is not missing either: every down has an up, with Range/Touch cleared and the
  Touch|Range mask set. All of this is shared by the Home taps that work, so it cannot explain a failure only inside apps.

### UIKitCore (iOS 26 cache `/data/hackios-qemu/dsc-r6`, cbdis.py; static reading)

| Address | What it does |
| --- | --- |
| 0x18923b208 | Picks the touch handler slot for an incoming event. Slot 0 if field 0x6 ≠ 0 or the type is not digitizer. Slot 0 if `IsDisplayIntegrated` (0xb0019) == 0. Otherwise slot 1, or slot 2 when 0x189136238 finds a stylus child (transducer type 0). An empty slot falls back to slot 0. |
| 0x18a761c18 | UIKit builds its own digitizer events with `IsDisplayIntegrated = !app._supportsIndirectInputEvents`. So slot 0 is indirect input, slot 1 the finger, slot 2 the pencil. |
| 0x18ac69b78 | A focus-system gesture recognizer reads `IsDisplayIntegrated` from the touch's `_hidEvent`. With 0 it moves to state 3 (recognized, so it claims the touch); with 1 it moves to state 5 (failed, so it lets go). |

UIKit's indirect handling explains why scroll views, table rows and switches inside Settings ignore the touches. Why
SpringBoard's icon tap still works with indirect touches is inference: its recognizer evidently accepts them. That the missing
Control Center has the same cause (SpringBoard's screen-edge gesture wants direct touches) is likely but not proven. The phone
test below decides it.

## Change

Release tree `research/ios26-release-r1/work/xnu` (Mac), **new branch `hk-touch-direct`, commit `e731e68`** on
`hk-bright-calib-bl` (f24a98d). Patch copy: `0001-sweethid-touch-display-integrated.patch` (sha256 48f15ebe…b5b7).

- New `iokit/Kernel/arm/hid/sweet_touch_event.h`: the per-event fields of a touch event in one place. Each child gets Index,
  Identity, Touch, EventMask and **IsDisplayIntegrated=1**. The collection gets Collection, X, Y, Range, Touch, EventMask,
  ButtonMask and **IsDisplayIntegrated=1**.
- `SweetHIDTouch::touch()` (the panel) and `sweet_live_touch_event()` (`hk_live_hid.inc`, scripted taps) both use it. Every
  other field and value is unchanged.
- Boot-arg `sweet_touch_indirect=1` restores the old shape for an A/B boot. image_tool may need it added to its allow-list
  first; it is not in r7.
- The start log now says which shape is active: `SWEET HID: touch registered, canvas 1125x2511, centred at 77,172, direct touches`.

## Host and binary evidence

- `test/run.sh <xnu tree>` against the committed e731e68 bytes: `touch shape host test: 49 checks, 0 failed`,
  `tcm decode host test: 133 checks, 0 failed` (`test/RESULT-e731e68.txt`).
  - `test_touch_shape.cpp` runs the real header (the real IOHID field ids, through a 5-line `IOKit/IOTypes.h` stub) against
    UIKit's slot rule transcribed above. Direct mode gives slot 1 for down, up, move and edge events; the old shape gives slot 0.
    Every other field matches the pre-fix values.
  - `test_tcm_decode.c` runs the real `blazer_tcm.c` (-DBLAZER). For all 16 logged phone pairs it finds the in-range raw panel
    value, sends it as a TouchComm report, and checks the logged 0..65535 value and panel pixel exactly. It also checks the up
    at the last position and the max → last pixel case.
  - Mutants: forcing IsDisplayIntegrated to 0 gives 13 failures; scaling with 12800 instead of `scale_x` gives 30 failures.
- Build: `research/ios26-release-r1/tools/mk.sh -j8` under an exclusive non-blocking lock on `/tmp/fleet/kernel-build-slot.lock`.
  No other build was running. Incremental, rc 0, 22 s. Recompiled: `SweetHID.cpo` (plus `SweetFramebuffer.cpo` and
  `hakios.blazer_ufs.o` from the f24a98d base), then LD. Log: `research/ios26-release-r1/logs/touch-direct-build.log`.
  - Afterwards the tree went back to `p1` (b228c4f), clean, and was rebuilt (rc 0, `logs/touch-direct-restore-p1-build.log`).
    The obj kernel is now b6820748…; the link is not reproducible.
- Kernel (Mac `research/ios26-dualboot-r8/rootview/`):
  - `kernel.rootview-bl-touch` **cf9065990b76d038d4ca94d1bdda3d4a2f2f4d615edc9dbb7c67f9543d7b1452** (Mach-O arm64,
    UUID 88B90E94-FC59-3D70-AEA3-9649DF295D13).
  - `kernel.rootview-bl-touch.unstripped` 1ea8e211f9860fa8f83b67575374787c8b8bfe9944269071a1b4517b5f5feb9e.
  - Strings `sweet_touch_indirect` and `…%s touches` are present (0 in kernel.rootview-bl).
- ARM64 disassembly (unstripped, llvm-objdump):
  - `SweetHIDTouch::touch` sets field `0xb0005+0x14` = 0xb0019 on each child, behind the direct flag.
  - The out-of-line `sweet_touch_collection_fields<IOHIDEvent>` sets `0xb0001+0x18` = 0xb0019 on the collection, behind
    `cbz w20`.
  - `sweet_live_touch_event` sets `0xb0007+0x12` = 0xb0019 twice (child and collection).
  - `gSweetTouchDirect` is in __DATA.

## Image `a7-ios-system-r7-touch` (Mac `research/images/`, HOST build)

- Recipe: r5-accel's exact recipe (A7-READY step 6, accel-skip overlay f5d4c367…, `hk_bright=140`, deadline 300, 5 cores,
  canvas 1125x2511). Only the kernel is swapped: `--kernel research/ios26-dualboot-r8/rootview/kernel.rootview-bl-touch
  --kernel-sha cf906599…`.
- **boot.img 5e71f94a1b5b9d3fbb653d9931d427078ca1ea2e1cf76740c12abef8a5d5873d**; payload dcf31506…; ADT 8c626a40…;
  manifest 9c2ac151…. `image_tool.py check`: `OK a7-ios-system-r7-touch bootable`. avb verify OK. The build's host tests all PASS.
- **Cmdline diff vs r5-accel: none** (1013 → 1013 bytes, token lists identical).
- Manifest diffs:
  - The kernel (mach) and what follows from it: payload, image, kernel_end +0x4000, segs (`__TEXT_EXEC` 0xa48000 → 0xa4c000),
    plan (+0x4000), overlay placement 0x884d98000 → 0x884d9c000 (same overlay sha).
  - Per-build values: ADT seed, nonces, epoch.
  - `tools.image_tool.py`: the Mac's copy is now b56ae2bd… (r5 used 2bdc03e8…; someone else's later edits). The cmdline it
    produced is byte-identical anyway.

## Attended test (owner, bare `fastboot boot`, then the return check)

`tools/bootios research/images/a7-ios-system-r7-touch/boot.img a7-ios-system-r7-touch --mach research/ios26-dualboot-r8/rootview/kernel.rootview-bl-touch.unstripped --wait 480`

1. Log: `SWEET HID: touch registered, … direct touches`; touch bring-up as in r5 (`tcm: … ready`, `0 bad`).
2. On Home, tap Settings (it should still open).
3. Inside Settings, in this order, with a few seconds between steps:
   1. Scroll the main list up and down.
   2. Tap a row, e.g. General; the next page should appear.
   3. Tap the back button (top left); you should return to the list.
   4. Open a row again and go back with a swipe from the left edge.
   5. Flip a toggle (e.g. Airplane Mode or a switch inside General) twice.
4. Pull down from the top-right corner (Control Center). If it shows, try the brightness slider. Also try a pull-down from
   the top middle (Notification Center), and a swipe up from the bottom edge (Home).
5. The owner says which steps worked.

The log should show HK TOP `Preferences[N]` CPU in the tens to hundreds of ms in the window with the in-app taps (r5: 42 ms
for 12 gestures).

- **Pass:** steps 3.1 to 3.5 respond.
- **Partial:** in-app taps work but Control Center does not. Then the Control Center problem is separate; next step is
  SpringBoard's edge-gesture requirements.
- **Fail:** nothing in the app responds and Preferences CPU stays near 0. Then the slot rule is not the whole story; next step
  is backboardd's per-scene touch gating (`BKSSceneHostTouchBehaviorInactive/Foreground` in BackBoardServices).

Stop: any panic, a backboardd SIGSEGV loop, or no Home by the 300 s deadline. Rollback: deadline/PSCI reset to fastboot, then
`return-check.sh`. Nothing is written; the root is read only.
