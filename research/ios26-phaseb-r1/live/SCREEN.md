# Seeing the iOS screen without the owner (DBG5, 2026-11-03)

Status: **HOST evidence plus a Mac kernel and image build. Nothing has been booted.** The phone was not touched. Evidence
classes: SOURCE (read in the tree), HOST (run on m1box or the Mac), INFERENCE (not yet measured).

Two paths:

| | when | kernel side | host side | size |
|---|---|---|---|---|
| **Post-mortem** | after a boot parks in fastboot | `hk_screen=N` writes an HKSCR1 record into the ramoops zone that every park already dumps | `tools/fb_png.py` / `tools/screenshot.sh --dump` | 360x803 RGB565, 2x2 box |
| **Live** | during a `tools/live_boot.sh` boot | DBG3's usbcon snapshot, requests 0x67/0x68 (`blazer_usbcon_snap=1`), unchanged | `tools/screenshot.sh` | step 6: 188x419 RGB565 |

## 1. Can ABL's ramdump staging read the framebuffer? No, under the project's rules

- SOURCE: `tools/capture-fastboot.py` and `research/laguna-usb-fix/run-attempt.sh` read five **named** regions with
  `oem ramdump stage_file NAME` + `get_staged`: RAMDUMP_MSG.txt, `kernel.log` (4 MiB, PA 0x95200000..0x955fffff), bootreason.log,
  abl.log, abl_last.log. run-attempt's device-write contract says "never a raw ap_* bank, never a bare listing". The bare
  listing once hung ABL and left every later fastboot command timing out (capture-fastboot.py docstring).
- So the panel buffer at 0xf0000000 (1280x2856 BGRA, stride 5120, 14.6 MB) cannot be pulled. Raw-bank staging is the only
  ABL path that might reach it, and it is excluded. The kernel copy below is the only option within the contract.
- Free space inside `kernel.log` (SOURCE: tools/read-ramdump.py, tegu_early.c, tensor_takeover.h, shim/tgl_*.h): the pmsg half
  holds the msgbuf ring at +0x40000..+0x140000, the legacy PAN2 decode at +0x140000..~+0x142040, and the TGL_ALL record at
  +0x1f0000. **+0x150000..+0x1f0000 (640 KiB) is unused.** A 360x803 RGB565 picture plus header is 578,288 bytes.

## 2. Kernel: `hk_screen` (XNU branch `hk-screen-dbg5`, Mac release tree)

- `hk-screen-dbg5` = `hk-touch-direct` e731e68 + **c74c9cb** (DBG3's `input/0001-hk-live-key-swipe-snapshot.patch` d93bec9b…,
  unchanged) + **8f019a8** (`screen/0002-hk-screen.patch` 6e392956…). Built by `screen/build_screen.py` under
  `/tmp/fleet/kernel-build-slot.lock`, then p1 (b228c4f) was checked out and rebuilt, both rc 0 (`screen/receipts/build.txt`).
  Afterwards another owner took the slot: the tree is now on `hk-gpu-m2-r1`, clean. That is theirs, not mine.
- `osfmk/arm64/hk_screen.c`, `hk_screen_pure.inc` (the sampler and record writer, no kernel headers):
  - `hk_screen=0` (default) off. `=1` captures at the blazer deadline and at panic. `=N` (N ≥ 10) also captures every N s from
    the blazer-root watch thread, which ticks every 10 s. `hk_screen_box=0` takes point samples instead of 2x2 averages.
  - Source: `sweet_scanout_picture_buffer()` (new, in sweet_scanout.cpp). It returns the same picture DBG3's snapshot reads:
    backboardd's 1125x2511 canvas at the panel buffer's origin under `hk_fb_scale=1`, else the whole panel buffer. It still
    answers after the scanout latched off (the buffer keeps the last frame) and refuses on a flipped client surface.
    It takes no locks.
  - Output: 360 px wide, 16.16 step (1125/360 = 3.125 → 360x803), word loads only, RGB565 little endian, B in the lowest byte
    of BGRA. The record goes to PA **0x95550000** (pmsg+0x150000, `ml_io_map`ped at init). It has a 128-byte header (magic
    `HKSCR1`, seq, reason 1 panic/2 periodic/3 deadline, w/h, flags, src size and stride, step, took_us, crc32 of the rows,
    CNTVCT, and **this boot's XNUENT1 nonce/entry/handoff**, copied from the msgbuf v2 header at 0x9543f840), then the rows.
    The magic is cleared first and written last.
  - Hooks: `hakios_blazer_watch_start` → `hk_screen_init` (maps the record, logs `HK SCREEN: on, …`). `ufs_root_watch` →
    `hk_screen_tick` every 10 s, and `hk_screen_deadline` (thread context, logged) right before the deadline `panic()`. In
    `debugger_collect_diagnostics`, `hk_screen_panic` runs once, before `PEHaltRestartInternal(kPEPanicBegin)` (no lock, no
    allocation; a deadline capture is kept, not overwritten).
- HOST (Mac, `screen/receipts/kernel-verify.txt`): `kernel.dbg5-screen` **8e22c1ff59caaef03cf0408c3ba8d3ad3e748513ad8eff807277b867ef565d82**,
  unstripped 84246fa915269667c1e9ebba2b03a5510fb0b8ed85ca2ac8aa6702b274adf33d. Mach-O arm64, **0 undefined**. `_hk_screen_{init,
  tick,deadline,panic}`, `_hk_scr_capture`, `_sweet_scanout_picture_buffer` and `_sweet_scanout_snapshot` are present, as are
  the TUNABLEs `hk_screen`/`hk_screen_box` and the `HK SCREEN:` strings. Call sites: `_ufs_root_watch` calls `_hk_screen_tick`,
  then `_hk_screen_deadline` before `_panic`. `_handle_debugger_trap` (debugger_collect_diagnostics inlined) calls
  `_hk_screen_panic` at …aa64, before `_PEHaltRestartInternal` at …aa84 (`receipts/panic-hook-order.txt`). `_hk_scr_capture`
  calls `_sweet_scanout_picture_buffer` and `_crc32` (bsd/libkern/crc32.c, zlib-compatible: SOURCE). No compiler diagnostics
  for hk_screen.o. `sweet_touch_indirect` (e731e68) is present.
- Not measured (INFERENCE): the cost of one capture. It is 289k 2x2 taps = 1.16 M word reads of the write-combined panel
  buffer plus 145 k stores. Expect ~0.1-0.3 s on the watch thread (one of 5 cores), every 30 s in the image below. The first 3
  periodic captures log `… N us`. If that is too slow, use `hk_screen_box=0` (4x fewer reads) or a longer N.

## 3. Image `a7-ios-system-dbg5-screen` (HOST build on the Mac, copied to m1box `research/images/`)

- `screen/mkimg_screen.sh` uses a7-ios-system-r10-perf's recipe, exactly as `ustack/mkimg_ustack.sh` does (overlay perf-r1
  95701ed9, `--phone-deadline 300`, 5 cores, canvas 1125x2511), with `--kernel kernel.dbg5-screen`. It drops the three AKS-branch tokens
  e731e68 does not read (as dbg1-net and dbg4-ustack do) and adds `blazer_usbcon_snap=1 hk_screen=30`.
- **boot.img 7a7337a841eca05106fb2b6eb759e52f1f21c4ff7ec984e7b09c6efa3f06da6d**, payload f68ef754…, `image_tool.py check`: **OK, bootable**.
  The cmdline is **985 bytes** (r10-perf: 1015). `receipts/manifest-diff.txt`: -blazer_aks_usersession/aks_wrap/persona_log,
  +blazer_usbcon_snap=1 hk_screen=30. Otherwise only kernel/payload/ADT seed/nonces and the image_tool hash differ.
- image_tool: the Mac's `tools/image_tool.py` (uncommitted, already carrying DBG4's hk_ustack edit) got the additive
  allow-list from `screen/tools/allow_screen.py`: `hk_screen`, `hk_screen_box`, `blazer_usbcon_snap`, plus refusals for a kernel
  without them (`screen/tools/image_tool-screen.patch`, ffbaf2d5… → acf48b98…). m1box's image_tool.py has other owners'
  uncommitted edits, so it was not changed. The coordinator should fold the patch in when committing image_tool.py.
- Same base caveat as dbg4-ustack: e731e68 has touch-direct but not the AKS wrap/user-session commits that r10-perf's kernel
  had.

## 4. Host tools and tests (m1box)

- `tools/fb_png.py`: (a) `DUMP` = kernel.log or attempt dir → decodes HKSCR1. It checks magic, version, size and crc. It
  refuses a record whose XNUENT1 identity differs from the dump's own XNUENT1, or that was captured before entry (previous
  boot residue), exit 4 unless `--allow-stale`. (b) `--rgb565 --size WxH` (usbcon snapshots). (c) `--bgra` (a raw panel buffer,
  e.g. a QEMU memory dump; it is downscaled with a Python model of the kernel's sampler). `--scale`, `--swap-rb`, `--json`.
  No dependencies.
- `tools/screenshot.sh`: live mode asks the running usbcon reader through `LIVE_SOCK` (from a live_boot run's `live.env`;
  default: the newest `research/laguna-usb-fix/attempts/live-*`). It copies the reader's `.png/.rgb565/.json` back with
  `mac repo --back` and writes `RUN/screens/NAME-HHMMSS.png`. `--dump` runs fb_png. It never opens USB itself (usbcon allows one
  reader) and never touches the device beyond the reader's read-only snapshot request.
- Tests: `python3 -I tools/test_fb_png.py`: **20 tests OK** (`screen/receipts/host-test.txt`):
  - the sampler's dims and channel order and the box rounding;
  - fresh, stale, captured-before-entry, absent, torn (crc) and no-picture records, the attempt-dir default, `--rgb565`, `--bgra`;
  - **KernelWriter:** it compiles `screen/test/test_hk_screen.c`, which includes the kernel's own `hk_screen_pure.inc`, under
    ASan/UBSan. It writes 4 MiB synthetic kernel.log images from a synthetic 1280x2856 stride-5120 panel buffer (a 1125x2511
    picture at the origin, junk outside). The decoded PNGs equal fb_png's Python model **bit for bit**, box and point, and
    another boot's identity reads as stale;
  - screenshot.sh against a fake `mac` (`SCREENSHOT_MAC`): the right socket, step and name, the copy-back, the PNG; refusal → 4;
    bad args → 2; `--dump` fresh/stale.
  - The C test passes on its own with and without sanitizers. `receipts/synthetic-box.png` is the decoded synthetic frame
    (gradients, checkerboard, a white bar, and red/blue blocks in the expected corners: channel order right).

## 5. Usage (coordinator)

Boot (attended or not; bare `fastboot boot` through the usual runner, as dbg4-ustack). For live screenshots, use live_boot:

```sh
cd /srv/dev/repos/personal/hackios
tools/live_boot.sh research/images/a7-ios-system-dbg5-screen/boot.img a7-dbg5-screen \
    --mach research/ios26-phaseb-r1/live/screen/build/kernel.dbg5-screen.unstripped --wait 480 --sync-tools
# live, any time after "SWEET FB: display on" / UI_READY (second terminal):
tools/screenshot.sh --name home            # newest live run; prints the PNG path
tools/screenshot.sh <run-dir> --step 8 --scale 2 -o /tmp/x.png
# after the park (run-attempt has pulled ramdump/kernel.log):
tools/screenshot.sh --dump research/laguna-usb-fix/attempts/<attempt>    # -> <attempt>/screen.png
python3 -I tools/fb_png.py research/laguna-usb-fix/attempts/<attempt> --json   # header, identity, t since entry
```

`tools/bootios` / `hackios-boot` works the same for the post-mortem alone (no live reader needed). The deadline is 300 s, as
in r10-perf, so the deadline capture shows the screen at 300 s. The periodic record keeps the last 30 s slot whatever ends
the boot (hang, watchdog, reset). Only the last capture survives.

Pass criteria for the first boot, from `ramdump/kernel.log`:
1. `HK SCREEN: on, record 0x95550000 (640 KiB), 360 px wide, 2x2 box, at deadline/panic and every 30 s` once.
2. `HK SCREEN: capture 1..3 periodic 360x803, 578288 bytes, N us`, which gives the cost. `capture … deadline` before the
   deadline panic.
3. `fb_png.py` says `fresh` and the PNG matches what the owner saw (or the r10-perf Home). If colours are swapped:
   `--swap-rb`. That would mean the BGRA assumption is wrong for this buffer, and the kernel side is unchanged.
4. Live: `tools/screenshot.sh` returns a 188x419 PNG within ~10 s (INFERENCE: ~400 EP0 reads).
5. Nothing else changes against r10-perf apart from the e731e68 base (the AKS commits are missing, as in dbg4).

Fail/stop: a panic or hang inside `hk_scr_capture` (it would show as a missing deadline line or the watch thread stalling).
Rollback: the same image line without `hk_screen` (kernel unchanged, hk_screen=0 is off).

## 6. Not done / open

- No physical run, so capture cost, R/B order on the glass and live latency are unmeasured.
- Live uses DBG3's step-N RGB565 (160 KiB cap). A full 360x803 live read is 1,506 EP0 transfers (~30 s, INFERENCE), so it
  was not added, and no new USB request was taken. 0x71+ remain free as far as this work knows (0x60..0x6b HLI1/snapshot, 0x70
  hk_ustack).
- The DBG1 network path does not exist yet. A snapshot over it would reuse `sweet_scanout_snapshot`/`_picture_buffer`.
- `tools/usbcon.py` (DBG3's snapshot client) is uncommitted on m1box. Live screenshots need it on the Mac (`live_boot.sh
  --sync-tools`) until it is committed.
- Cosmetic, in the built kernel: with `hk_screen=1` the init line ends `at deadline/panic0` (an empty `%u` slot prints 0). The
  image uses `hk_screen=30`, which prints correctly. Fix it in the next rebuild; it was not rebuilt only for this.
- Temp file on the Mac: `/tmp/hk-screen-check-<pid>.idx`, a git index from the apply check. It is harmless and can be
  removed.

## Files

`screen/0002-hk-screen.patch`, `screen/build_screen.py`, `screen/mkimg_screen.sh`, `screen/xnu-src/` (edited files plus
`base/` = e731e68 copies; sweet_scanout.* start from DBG3's patched copies), `screen/test/test_hk_screen.c`,
`screen/tools/allow_screen.py`, `screen/tools/image_tool-screen.patch`, `screen/receipts/`. These are not for git:
`screen/build/` (kernels and objects, also on the Mac) and `screen/tools/image_tool.before.py` (a copy of the Mac's
image_tool.py).
