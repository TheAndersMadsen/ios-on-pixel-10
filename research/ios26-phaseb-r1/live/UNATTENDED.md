# Unattended UI test: live console, scripted input, framebuffer snapshot (2026-11-03)

Status: **host evidence only.** Nothing here touched the phone. The tools were exercised with test doubles. The kernel
change is compiled to ARM64 objects but not linked or booted. Evidence classes are marked: SOURCE, HOST, PHYSICAL (old
receipts re-read) and INFERENCE.

## 1. Can usbcon run beside run-attempt? Yes, no hand-off needed

- SOURCE: run-attempt's only USB reader is `tools/usb_log.py`. It opens **1209:0001** (the shim's gadget,
  `usb.core.find(idVendor=0x1209, idProduct=0x0001)`). `tools/usbcon.py` opens only **1209:0002/0003** (XNU's gadget,
  `PIDS`, "never select shim PID0001"). Neither claims an interface or sets a configuration; both use device-recipient
  EP0 control transfers. XNU's usbcon soft-disconnects the shim's gadget and re-enumerates
  (`UC_HOLD_MS` "long enough ... for usb_log to leave"), so the two readers are sequential owners of one controller.
  Their host processes still run side by side.
- PHYSICAL (old): p29 and p32 booted through run-attempt with usbcon live (README "Live console ✅": 879,706 live bytes
  equal to the RAM mirror). p31r1's `live.log` ends `Diagnostic disconnected.` when XNU takes over.
- usbcon allows one console reader (flock `/tmp/hackios-usbcon-UID.lock` on the Mac). Input and snapshot clients
  never open USB; they go through the reader's private Unix socket.
- `tools/live_boot.sh` starts the reader **before** the boot. If the reader dies at once (lock held, socket taken, no
  pyusb), the boot is not started (exit 3), and the phone is not touched.

## 2. `tools/live_boot.sh`

Runs `hackios-boot` (= `mac repo --back-attempt -- tools/bootios`) unchanged. Alongside it, it runs
`mac repo --force -- python3 -u tools/usbcon.py --output <run>/usbcon/usbcon.log --control-socket /tmp/hackios-live-<ts>-<pid>.sock`
in its own session, so stopping it closes ssh. The Mac's runner then SIGTERMs usbcon, which now finishes and writes
its `.json`. Output goes to `research/laguna-usb-fix/attempts/live-<ts>-<name>/`:

| file | content |
| --- | --- |
| `console.txt` | every console and usbcon line, prefixed with m1box wall time `HH:MM:SS.mmm` |
| `bootios.txt` | hackios-boot output, same stamps |
| `markers.txt` | `LIVEBOOT <wall> +<s since start> <MARK> <detail>`, plus the UI test's `UITEST ...` lines |
| `live.env` | `LIVE_SOCK`, `LIVE_RUN`, `LIVE_MAC_DIR`, `LIVE_MARKERS`, `LIVE_T0`, at the end `ATTEMPT`, `BOOT_RC` |
| `usbcon/` | raw stream (`.log`, `.times`, `.json`) and `usbcon.log.snaps/`, copied back from the Mac at the end |

Markers, each pattern checked against p31r1/r7 dumps:

- **Once:** `CONSOLE_WAITING`, `CONSOLE_CONNECTED`, `USB_CONFIGURED`, `DISPLAY` (tensor-dpu attached), `ROOT`, `LAUNCHD`,
  `BACKBOARDD`, `SPRINGBOARD`, `TOUCH_CLIENT`, `BUTTON_CLIENT`, `FRAMES` (HK TOP frames+N, or a nonzero SWEET FB swap
  rate), `UI_READY` (SpringBoard + both HID clients + frames).
- **Repeating:** `APP <name>`, `CRASH <proc>`, `EXIT <service> <signal|exit(n)>`, `INPUT <state> <command>`,
  `LIVE_DONE gen= result=`, `SNAPSHOT <png>`, `PANIC`, `DEADLINE`, `CONSOLE_GONE`, `CONSOLE_END`.
- **From the runner:** `ATTEMPT_DIR`, `EP0_LIVE`, `PARKED`, `ATTEMPT`, `BOOT_RC`.
- **With `--ui-test`:** `UI_TEST_STARTED` and `UI_TEST_STOPPED`.

HOST: dry runs with `fakepb/` replayed real p31r1 console lines. All markers fired, the boot path ran, and the reader
was stopped after the boot with its last line drained. The early-exit refusal also fired.

Caveats:

- hackios-boot keeps its same-commit check: m1box HEAD must equal the Mac's.
- `--sync-tools` overwrites the Mac checkout's `tools/usbcon.py` with m1box's. It is needed for KEY/SWIPE/snapshot
  until this file is committed and pulled on the Mac.

## 3. Why TAP "needed manual app recovery", and the fix

PHYSICAL (re-read `20261102-121918-phone-p31r1-live-diag-r1/ramdump/kernel.log`):

- 00:11:19: a physical tap at picture (210,295) highlighted the Settings icon (`SWEET FB ... changed 74,183 192x192`)
  and cold-launched Preferences.
- 711 s: live HOME, gen 2, dispatched.
- 791 s: live TAP, gen 3, canvas (210,295). The **same icon highlighted**, 24 frames followed, `HK LIVE done gen=3
  result=0`, and nothing launched (Preferences was still resident from the earlier launch).
- ~834 s: the owner tapped mid-screen, swiped up from the bottom edge, and tapped the icon physically (206,374).

So the TAP was delivered and hit-tested; the event pipeline worked.

The kernel-side defect is research/ios26-phaseb-r1/touch/FIX.md (`e731e68`, hk-touch-direct). SweetHID touch events,
**including the live tap path**, never set `kIOHIDEventFieldDigitizerIsDisplayIntegrated`, so UIKit treated every
touch as indirect, trackpad-style. SpringBoard's icon recognizer accepts indirect touches; in-app controls and the
system edge gestures do not. p31r1's kernel predates e731e68.

INFERENCE: the resume and recovery failure came from indirect touches plus the known presentation instability. It was
not a USB or HID delivery bug.

The fix is therefore to build on e731e68 or a descendant, which `0001` targets. The live TAP and the new SWIPE use the
same `sweet_touch_child_fields`/`sweet_touch_collection_fields` as the panel path.

Two host-side contributors are also fixed:

- **Coordinate spaces.** p31r1's TAP reused 210,295 from a `SWEET HID: touch` log line. Those lines print *picture*
  pixels; TAP takes *canvas* pixels (picture × 1125/1280 under `hk_fb_scale=1`). It still landed on the icon. The
  usbcon help and this document now say so.
- **No retries.** The test retries only clean refusals and never an ambiguous action. It allows one recorded
  recovery (HOME, then the same TAP) after a definite `dispatched` receipt with no app.

## 4. Input ABI additions: `0001-hk-live-key-swipe-snapshot.patch` (input/)

HLI1 is unchanged byte for byte: TAP/HOME, the wire struct and the arm/ticket/commit/receipt sequence. New ops are
advertised by capability bits, so older kernels refuse them before arming. The client checks the bits.

| req | name | wValue / wIndex | notes |
| --- | --- | --- | --- |
| 0x60..0x63 | STATUS, ARM, TAP, HOME | as before | |
| 0x64 | — | — | **hk_ustack's** (hk-ustack-dbg4); not HLI1 |
| 0x67 / 0x68 | SNAP_TAKE / SNAP_READ | step / 0; byte offset lo / hi | `blazer_usbcon_snap=1`, section 5 |
| 0x69 | KEY | key 0 power, 1 volup, 2 voldown, 3 home / 0 | cap 32; 80 ms press, the same usages as `sweet_hid_key` |
| 0x6a | SWIPE_FROM | x0 / y0 (canvas) | armed only; no event; the window stays armed with its 2 s expiry |
| 0x6b | SWIPE | x1 \| code<<12 / y1 | cap 64; duration 100 + 50·code ms (100..850) |

The core matches HLI1 explicitly (`HK_LIVE_IS_REQUEST`), so 0x64 still reaches hk_ustack.

SWIPE on the HID workloop:

1. One DOWN (Touch|Range|Identity|Position).
2. One MOVE every 16 ms (Position only), interpolated linearly to the end point.
3. One UP at the end point.

The UP is allocated before the DOWN is dispatched, as for TAP. A stop, cancel, failed allocation or timer error skips
straight to that UP. The edge bit is the start point's, so a swipe from x < 52 canvas px is an edge gesture. Physical
touches stay excluded while a live contact runs (`fLiveExclusive`).

HOST: `input/test_live_input.c` runs the real `blazer_usbcon_input.inc` against mocks: staging, refusals, the old-HID
capability path, expiry, re-arm, and the opcode map. It passes with and without ASan/UBSan. `tools/test_usbcon_tool.py`
gains a fake kernel input model (old and new kernel) and a fake snapshot device:

- tap, home, key and swipe dispatch in order;
- the swipe sends FROM between ARM and commit, and never sends 0x64;
- an old kernel refuses KEY/SWIPE before arming;
- out-of-canvas, notready and grammar refusals;
- snapshot chunking and the PNG writer;
- a real Unix-socket round trip.

37 tests pass. ARM64 objects and symbols are in `input/BUILD.txt`.

## 5. Framebuffer snapshot over usbcon (did not exist; now implemented)

`blazer_usbcon_snap=1`, off by default.

- **TAKE (0x67, wValue = step):** `sweet_scanout_snapshot()` reads every step-th pixel of the picture in the panel's
  own buffer and writes RGB565 into a kalloc'd 160 KiB buffer. The picture is at the buffer origin, src 1125x2511,
  under `hk_fb_scale`; otherwise the read covers the whole 1280x2856 buffer. Word loads only (device memory). The
  step is raised until the copy fits. The reply is a 64-byte `HFB1` header: boot identity, seq, result, w/h, step,
  src size, bytes, µs taken.
- **READ (0x68):** returns the copy by byte offset, 384 bytes per transfer (UC_DATA_BYTES).
- **Client:** `usbcon.py --snapshot` makes the reader write `usbcon.log.snaps/NNNN-name.{png,rgb565,json}`. It is
  read only, so the client may repeat it.

A step-8 snapshot is 141x314, 88,548 bytes, 231 transfers. INFERENCE: about 5 s at the kernel's 20 ms idle poll; the
reader does not idle while a request is in flight.

Limits:

- It reads only the panel buffer, which is the copy path that p32 and the A7 images use (`copy_ops`).
- On a flipped client surface it answers `unavailable`.
- A frame being copied in can tear.
- The BGRA byte order is from the `0x42475241` surfaces and the `0xff000000` black fill. INFERENCE: if colours look
  swapped, `rgb565_to_png(swap_rb=True)`.
- The TAKE runs inside the setup handler on usbcon's MAXPRI_KERNEL thread: 44k device reads, tens of ms (INFERENCE).

## 6. `tools/ui_settings_test.py`

All coordinates are canvas pixels.

1. Wait for `UI_READY`, then settle 20 s.
2. Read `--input-status`: capabilities and canvas.
3. Snapshot `start`.
4. HOME.
5. TAP Settings **170,279**. Expect `APP Preferences` and a screen change. On failure, one recovery: HOME, then the
   same TAP.
6. SWIPE 562,1900→562,800 (300 ms), then 562,800→562,2000.
7. TAP General **370,1008**.
8. Back: TAP **110,200**, or `--back swipe` for the left edge 8,1200→700,1200.
9. HOME.

After every step there is a snapshot and its changed-pixel fraction against the previous one. A step passes when it
was `dispatched` and, with snapshots, its change matches what is expected (≥ 2 % of pixels). Without snapshots, the
Settings launch must show `APP Preferences`.

The test writes `ui_test.log`, `ui_test.json` (PASS/FAIL/NOT_RUN, per-step receipts, LIVE_DONE, crashes and exits in
each window) and `ui/` (snapshots copied back). Without live SWIPE (an older kernel), the scroll steps are skipped and
noted.

Coordinate provenance (picture → canvas ×1125/1280):

- **Settings:** p31r1's highlight rect 74..266 × 183..375 (centre 170,279). r7's tap 196,331 → 172,291 agrees.
- **Back:** p31r1's back taps 124,218 / 143,242 / 238,225 → about 110..209, 192..213.
- **General: INFERENCE.** r7-touch's owner tap at picture 427,1324 (canvas 375,1164) started `AccessibilityUIServer`
  at once, so that row is Accessibility. General is one row (~156 px at 3×) above. The first snapshot decides: if it
  is wrong, rerun with `--general X,Y`.

HOST: a dry walk against a local owner passed all 7 steps: the real Console and ControlServer, the fake kernel and
snapshot, and real PNGs.

## 7. Image and kernel requirements

- **Kernel:** e731e68 or a descendant, plus `0001` (applies cleanly to hk-ustack-dbg4, hk-usbnet-dbg1, hk-bright-brt1
  and hk-pwr1). Then a full link, checking zero undefined (`_sweet_scanout_snapshot`).
- **Boot args:** `blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_usbcon_snap=1`, with no `hk_ui=`
  or `sweethidtest`, which make live input refuse. `hk_top=30` helps UI_READY.
- **image_tool:** its PHONE_ALLOWED lacks `blazer_usbcon_snap`. Add
  `'blazer_usbcon_snap': r'blazer_usbcon_snap=1'` next to `blazer_usbcon_input` (`tools/image_tool.py` line 151; that
  file has another owner's uncommitted edits, so it was not touched here).
- **Timing:** the deadline and `--wait` must cover time-to-Home plus about 4 minutes of walk. A7 reached Home within
  its 300 s in r3; b11f5e7 saw ~10 min, so use a deadline of 900 and `--wait 1200` or more.

## 8. Usage

```sh
cd /srv/dev/repos/personal/hackios
# one command: boot, live console, walk
LIVE_UI_ARGS="--general 370,1008" tools/live_boot.sh research/images/<image>/boot.img <name> \
    --mach <kernel>.unstripped --wait 1200 --sync-tools --ui-test
# or by hand, in a second terminal once live_boot printed "live_boot: run <dir>":
grep -E 'UI_READY|CRASH|PANIC|INPUT' <dir>/markers.txt
python3 -I tools/ui_settings_test.py <dir>
# single actions during a live boot (from m1box; LIVE_SOCK from <dir>/live.env):
mac --cd Developer/personal/hackios -- python3 -I tools/usbcon.py --control-socket "$LIVE_SOCK" --input-status
mac --cd Developer/personal/hackios -- python3 -I tools/usbcon.py --control-socket "$LIVE_SOCK" --tap 170 279
mac --cd Developer/personal/hackios -- python3 -I tools/usbcon.py --control-socket "$LIVE_SOCK" --swipe 562 1900 562 800 --ms 300
mac --cd Developer/personal/hackios -- python3 -I tools/usbcon.py --control-socket "$LIVE_SOCK" --key volup
mac --cd Developer/personal/hackios -- python3 -I tools/usbcon.py --control-socket "$LIVE_SOCK" --snapshot --snap-name now
# host tests
python3 -I tools/test_usbcon_tool.py
cc -std=c11 -Wall -Wextra -Werror -I research/ios26-phaseb-r1/live/input/xnu-src/osfmk/arm64 \
   research/ios26-phaseb-r1/live/input/test_live_input.c -o /tmp/tli && /tmp/tli
```

## 9. Not done

- No physical run.
- No full kernel link and no image built with `0001`.
- The General coordinate is inferred.
- The snapshot's R/B order is unverified on the phone.
- `--sync-tools` is needed until `tools/usbcon.py` is committed and pulled on the Mac.
- `research/` is gitignored: commit its files with `git add -f`.
