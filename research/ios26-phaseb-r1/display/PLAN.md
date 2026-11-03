# Display path: measurements, ranked plan, r5-dsp (2026-11-03, HOST analysis + Mac build; nothing booted)

Labels: **M** = measured in a named log; **S** = read in source (release tree, IOMobileFramebuffer in dyld cache 0f1ee332);
**I** = inference, untested; **O** = owner observation. No phone, adb, fastboot or QEMU action in this work.

Inputs: A7 r3 ramdump `research/laguna-usb-fix/attempts/20261103-154441-a7-ios-system-r3/ramdump/kernel.log` (lines 1-20000 are
this boot; the ring repeats it from line ~20587), release tree p1 (b228c4f) `iokit/Kernel/arm/{SweetFramebuffer,SweetSurface,
sweet_present_trace}.*`, owner reports in `research/journal/HANDOFF-full-20261102.md:27` (p29: "missing logos/other rendering,
slow touch/heavy lag", 32 and 46 frames per 30 s).

## 1. Answer

**The kernel display path is not what makes the UI slow.** A frame costs the kernel ~15 ms end to end (CPU copy ~1.6 ms, DPU
fetch to the panel 7-13 ms), so it could carry ~60 fps. The UI ran at most **71 frames in a 30 s window (2.4 fps average), 8.4
swaps/s at the best moment**. Each frame costs **~200 ms of backboardd CPU**: CoreAnimation composites in software, because
there is no `IOAcceleratorES`. Frames do not queue in the kernel (queued − presented ≤ 1 all boot). Vsync is not the brake
either: backboardd never registers for vsync notifications (sel 72 is never called; it is still the iOS 26 selector, **S**), so
`hk_fb_period`/vsync changes cannot reach CoreAnimation. 60 Hz needs the GPU (native Metal lane), or at least a much cheaper
software frame (clock, pixels, effects). The kernel cannot fix that.

**Missing icons/logos is a separate, specific defect, and the kernel can act on it.** iconservicesagent draws every icon into
**RGhA** IOSurfaces (64-bit half-float RGBA). It created 19 of them in r3 and no other format (**M**). Prior art (ios-tegu
METAL-REARCH.md, our local copy) found that these icon surfaces never reach backboardd. **r5-dsp** refuses RGhA surface creation,
so the producer has to fall back to plain memory. It also logs which process imports which non-BGRA surface, so one boot
shows the icon path either way.

## 2. Measurements (A7 r3, 5 × A725, `blazer_gov_cap=16`, canvas 1125x2511 scaled to 1280x2856 by the DPU)

### 2.1 Frames (M: `HK TOP` + `HK PRESENT counters`)

| HK TOP t (s) | frames+ | queued total | presented (fetch_done) | backboardd CPU ms | SpringBoard ms | backboardd ms/frame |
|---|---|---|---|---|---|---|
| 81 | 0 | 0 | 0 | — (launch storm, 63.3 s CPU) | 1,746 | — |
| 111 | 25 | 25 | 25 | 2,464 | 24,742 | 99 (first frames, SpringBoard-bound) |
| 141 | **71** | 96 | 96 | 14,693 | 5,845 | **207** |
| 171 | 1 | 97 | 97 | 212 | 240 | — (idle Home) |
| 201 | 17 | 115 | 114 | 5,607 | 1,094 | 330 |
| 231 / 261 | 1 / 0 | 116 | 115 | 124 / 61 | | idle |
| 291 | **46** | 162 | 161 | 9,139 | 1,180 | **199** |
| 321 / 351 | 0 / 1 | 163 | 162 | 60 / 66 | | idle |

- First frame: `SWEET FB: display on` then swap 1 at us=96.15 s. Over 96-351 s that is 162 frames, 0.64 fps average. The UI is idle most of
  the time, so the busy windows are the measure: **71 and 46 frames/30 s** (p29 owner windows: 32 and 46).
- `SWEET FB: rate` lines (swaps/s per reporting span): 0.6, 0.8, **8.3**, 4.9, 0.3, 0.0, 0.7, 0.0, **8.4**. Damage is usually the whole canvas
  (`changed 0,0 1125x2511`). Small rectangles appear only on idle Home (e.g. `362,2472 402x15`, the clock), so CoreAnimation does pass damage.
- DPU: 5 `tensor-dpu: underrun` (frames 83, 111, 114, 143, 151) over 162 frames. They were not visible as faults, but a later item.

### 2.2 Where a frame spends its time in the kernel (M: `HK PRESENT event`, us timestamps, every 32nd frame plus swaps 1-4)

| swap | queue→begin (waits for the previous fetch) | begin→layer_copy done (CPU copy 11,299,500 B) | →submitted | submitted→fetch_layer0 (DMA to panel) |
|---|---|---|---|---|
| 1 | 0.07 ms | 2.07 ms | 0.07 ms | 13.3 ms |
| 2 | **5.85 ms** | 1.64 ms | 3.5 ms | 9.0 ms |
| 3 | 0.06 ms | 1.66 ms | 2.4 ms | 12.8 ms |
| 4 | 0.08 ms | 1.66 ms | 0.04 ms | 6.9 ms |
| 32 / 64 / 96 | 0.06 ms | 1.52 / 1.60 / 1.58 ms | 0.8 / 1.1 / 0.04 ms | 10.2 / 13.6 / 9.1 ms |
| 129 / 161 | 0.06 / 0.05 ms | 1.51 / 1.52 ms | 1.5 / 1.1 ms | 7.6 / 10.6 ms |

- **Yes, presentation is a CPU copy** (S: `AppleCLCD::vsyncFired` → `present()` → `sweet_fb_copy_rows`, `hk_fb_fast=1`). The copy goes from
  backboardd's cacheable BGRA surface (bpr 4608) into the write-combined panel buffer at 0xf0000000 (stride 5120), at **~7 GB/s, ~1.6 ms per frame**.
  Kernel path, swap to on-glass: ~12-17 ms. That is ≤ 10 % of a 200 ms frame.
- Queue: `queued − selected` is 0 or 1 at every counter line, and `copy_refused`, `uncertain`, `submit_not_ok` and `event_drops` are 0. The
  "queued presentations" in NOTES are not a kernel backlog in r3. The p32 `queued=0` lines were backboardd dying before any swap.
- Pacing: `hk_fb_refresh=60` turns on `fPace`. A swap arms the timer at once (`setTimeoutUS(1)`) and SwapWait (sel 6, 3 scalars) answers
  Busy only while that swap is queued or under the fetch. That costs nothing at 2-8 fps.

### 2.3 What backboardd uses from IOMobileFramebuffer (M: `SWEET FB: backboardd sel N`, mapped with `iomfb_sel.py`/`cbdis.py`, S)

Called: 3 GetLayerDefaultSurface, 4 SwapBegin, 5 SwapEnd, 6 SwapWait(id, x, 0), 12 RequestPowerChange, 15 SetDebugFlags, 17/27
Set/GetGammaTable (3,084 B = 3×257×4), 18 IsMainDisplay, 22 SetDisplayDevice, 25 GetDigitalOutState, 29, 33
EnableDisableVideoPowerSavings, 50 SetBrightnessCorrection, 57 GetColorRemapMode, 68 SetParameter, 74 (out 2 scalars + 64 B), 84, 88
(open-by-name limits). **Not called: 72** (Enable/Disable notifications; the iOS 26 framework still uses 72 at 0x22949b218/0x22949b2a0).
The kernel answers every unknown selector with success and zeros. That is harmless as far as these logs show. The gamma table that
backboardd sets (sel 17) is ignored. If Night Shift or white point ever matter, the DPU's gamma/CSC must take it.

### 2.4 Formats and colours (M: `SWEET SURF … create`)

- Framebuffers: backboardd id 3 and SpringBoard ids 18/25, all **1125x2511 BGRA** (0x42475241), bpr 4608. Swaps rotate surfaces 2/3/11. The panel
  layer is 1280x2856 BGRA. Format and channel order are right. Owner reports no colour fault besides the probe colours during bring-up.
- iconservicesagent: **RGhA** (0x52476841, 8 B/pixel) icons 49x49…156x156. Spotlight/Settings: **LA08** (0x4c413038) 240x240. `--gamut sRGB`
  is already on the phone line (image_tool `--phone-root`), and the icons are still RGhA.
- Canvas: 1125x2511 = 375x837 pt @3x. Aspect is 2.2320 against the panel's 2.2313 (0.03 %). The DPU scaler fills the panel at ×1.1378. Touch maps
  through `sweet_scanout_picture()` at run time (S, SweetHID.cpp:634), so touch and picture agree.

### 2.5 CPU and governor (S)

`blazer_gov` is per-domain, max-core-utilisation, 4 ms tick, and jumps on saturation (blazer_gov.c:868-873), so a busy render thread does
get the cap. The cap is L16 (~1075 MHz, docs/CPU.md: 533-1075 MHz physical). Lifting it is the CPU lane's call (thermal), not a display change.

## 3. Ranked plan (expected effect on the owner's complaints)

| # | Change | Targets | Evidence | Owner | Expected |
|---|---|---|---|---|---|
| 1 | **GPU compositing** (IOAcceleratorES + Metal, native-metal lane) | fps, lag | ~200 ms CPU per frame in backboardd (M), against a kernel path of ~15 ms (M) | Metal lane | the only route to 60 Hz (I) |
| 2 | **RGhA icon surfaces refused (r5-dsp, built)** | missing icons/logos | 19/19 iconservicesagent surfaces are RGhA (M); ios-tegu: they never reach backboardd (prior-art doc) | display (this) | icons on Home if the producer falls back to memory (I). The import log decides either way |
| 3 | Cheaper software frames: Reduce Transparency / Reduce Motion defaults in the var overlay (no blur/backdrop/glass passes) | fps, lag | whole-canvas damage at 200 ms/frame (M); blur cost is inference | overlay/root | 1.5-3× (I, to measure) |
| 4 | CPU cap above L16 for backboardd's bursts (`blazer_gov_hi`) | fps, lag | gov reaches cap on saturation (S) | CPU lane | up to ~1.5-2× (I) |
| 5 | Canvas: keep 1125x2511 while rendering is on the CPU. Native 1278x2856 (426x952 pt @3x) costs +29 % pixels, so +29 % per frame. A @2x canvas would cost −55 % but needs an @2x model identity (MobileGestalt) | resolution vs fps | pixel arithmetic; scaler is free (M: `scale attached … factor 0xe0f9`) | display | native only after #1 |
| 6 | Zero-copy flip (`hk_fb_flip`, built in the tree, never booted) and dirty copy | copy cost | 1.6 ms of ~200 ms (M) | display | < 1 % fps. Do it after #1, together with 120 Hz (`hk_fb_refresh=120`, allow-listed) |
| 7 | DPU underruns (5 per 162 frames) | glitches | M | display | QoS/bandwidth later |
| — | Vsync with period (`hk_fb_period`) / present-completion notify | "queued" | sel 72 never called; queue ≤ 1 (M/S) | — | **no effect: not doing it** |
| — | Brightness | control | agent I: `kernel.rootview-bl` / `a7-ios-system-r4-bl` (f24a98d), not booted | agent I | boot r4-bl first; fold into r5-dsp after it passes |
| — | Auto-rotation | | no orientation source yet; backboardd's sel 22/68 do not carry it | sensors agent | display side: none needed while the DPU layer stays portrait (CA rotates in software) |

## 4. What was built (HOST + Mac build; not booted)

- **XNU:** release tree `research/ios26-release-r1/work/xnu`, branch **`hk-dsp-icons`**, commit **1726b64** = 7227fe7 (kernel.rootview's
  source) + `0001-hk-dsp-icons.patch` (sha256 f5bb9cec…a606; `apply_dsp_icons.py` 93301246… makes the same edit):
  - `sweet_surface_format.h`: `hk_fmt=3` refuses `'RGhA'` and keeps every other format. **It is this kernel's default** (`SWEET_FMT_DEFAULT_MODE 3`),
    so the image needs no new boot-arg and image_tool's allow-list is untouched. `hk_fmt=0` restores the old answer (not allow-listed yet).
  - `SweetSurface.cpp`: logs `SWEET SURF: hk_fmt 3: RGhA refused` once. Refusals log as `SWEET SURF: <proc> format 52476841 WxH refused (refused N)`
    (first 16, then every 64th). The first 48 imports of non-BGRA surfaces log as `SWEET SURF: <proc> imports id N fmt X WxH by sel 4|34 -> rc`.
- Host test `test/test_fmt_mode3.c` (clang -Wall -Wextra -Werror, UBSan+ASan): **PASS**. Mode 3 refuses only RGhA, modes 0-2 are unchanged, default 3.
- Build: `tools/mk.sh -j8` under the build-slot lock, rc 0, recompiled `SweetSurface.cpo` (+ `hakios.blazer_ufs.o` for 7227fe7), log
  `research/ios26-release-r1/logs/dsp-icons-build.log`. Then the tree was put back on **p1 / b228c4f** and rebuilt
  (`logs/dsp-icons-restore-p1-build.log`, rc 0, obj kernel a47eee5a…).
- Kernel `research/ios26-dualboot-r8/rootview/kernel.rootview-dsp` (Mac) **0093486bba87f1ccc45ac57d90fb2505ecaab0b01b2d05bd666dce9ae15e1551**,
  unstripped d0e640ec76b357fc4f3a891fc79b85d13f21349296a1faccade31e7deb1dfeaf. Mach-O arm64, 0 undefined symbols.
  Each new string appears once (`RGhA refused`, `imports id %u fmt`, `SWEET SURF: hk_fmt`, `(refused %u)`), 0 times in kernel.rootview.
  `fmt_mode` moved from __bss to `__DATA,__data` 0xfffffe00081c4e8c = **3**. New `fmt_refused` is in __bss. `sweet_surf_import_log` is inlined.
- Image **`research/images/a7-ios-system-r5-dsp`** (Mac): boot.img **36f6d76dd2aa58c0769eaef6b8a72d3dd441a5b2d4d33b5a6923dc22d21a6325**, payload 2b70bfec…,
  ADT 28cb1ee2…. It uses A7-READY step 6 with r3's line (no `hk_bright`) and `--kernel kernel.rootview-dsp`. `image_tool.py check`: **OK, bootable**.
  **Cmdline diff vs r3: none** (identical tokens, 999 bytes). The manifest differs from r3 only in kernel/payload/image hashes, the
  per-build ADT seed and nonces, and the Mac's `tools/image_tool.py` hash (2bdc03e8… → 757f0465…, someone else's uncommitted edit made after r3; the
  cmdline and check are unaffected).

## 5. Attended boot (coordinator; owner present; bare `fastboot boot`, as r3)

Order: r4-bl (brightness, agent I) can go before or after this boot; they are independent one-variable tests on r3's line.

```sh
tools/bootios research/images/a7-ios-system-r5-dsp/boot.img a7-ios-system-r5-dsp \
  --mach research/ios26-dualboot-r8/rootview/kernel.rootview-dsp.unstripped --wait 480
# then: force-fastboot off, Android up, research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-r5-dsp-after-boot
```

Owner script after Home (~90-110 s from power-on): look at the Home icon (Settings), the dock/status bar glyphs and the Spotlight
search icons. Open Settings and scroll the main list for ~10 s. Go back Home. Pull down Spotlight. Say what is visible and whether it feels
smoother than r3.

Pass criteria (from `ramdump/kernel.log`, first copy of the boot only):
1. `SWEET SURF: hk_fmt 3: RGhA refused` once. `iconservicesagent format 52476841 … refused` lines, with no repeating crash of
   iconservicesagent (`exec iconservicesagent` count ≤ 2) and no `usertrap: backboardd`.
2. Home as in r3: `SWEET FB: display on`, first swap ≤ 120 s after XNU entry, backboardd pid stable across HK TOP.
3. **Logos/icons present (owner):** the Settings icon and the glyphs show. The log line that explains it: `SWEET SURF: backboardd imports …`
   (non-BGRA icon surfaces reaching the render server) or no RGhA imports at all (icons came as image data).
4. **Frames:** busy HK TOP windows reported with `frames+N` and backboardd ms/frame. Smoothness pass: no busy window worse than r3
   (≥ 46 frames/30 s while scrolling, backboardd ≤ 210 ms/frame). Icons not costing extra CPU counts as a pass. This change is not
   expected to raise fps (§3 #1). Owner-visible smoothness is recorded as observed, not claimed.
5. Return check PASS.

Fail/stop: iconservicesagent or SpringBoard crash loop, or Home missing where r3 had it. Rollback is r3 (identical line, old
kernel). If icons are still missing and `imports` shows no backboardd RGhA lookups but the creates are refused, the producer had no
fallback. Next is the LA08/`IOSurfaceAddress` path or a userland fix (the CA client must send image data), not the kernel.

Read-only adb the coordinator can run afterwards (Android, optional): none needed. The evidence is the ramdump.

## Files

- `PLAN.md` (this), `0001-hk-dsp-icons.patch`, `apply_dsp_icons.py`, `test/test_fmt_mode3.c`.
- `iomfb_sel.py`: lists IOMobileFramebuffer exports and the selector each loads. The selector→API mapping in §2.3 came from
  `cbdis.py` over IOMobileFramebuffer __TEXT 0x229473000+0x39600 (Apple code; regenerate, do not store).
