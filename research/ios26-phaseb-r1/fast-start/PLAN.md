# Fast start: a gated shim profile for normal iOS starts (2026-11-03, host only)

No phone, QEMU or root-index action. Source: `shim/` at e1bb8f3 plus this change. Timings: TSHIMST2 stamps of
`research/laguna-usb-fix/attempts/20261103-135606-a7-ios-system-r1/stamps-decode.txt` (A7 r1) and
`20261102-095609-phone-p29-live-r1/stamps-decode.txt` (p29-live); ms since shim entry. Labels: **M** measured in those
stamps, **S** read from source, **H** host test or ARM64 object, **I** inference. BUDGET.md ranked change #3 and #4.

## 1. What each wait is

| Interval (A7 r1 / p29-live) | Cost | What runs there (S) |
|---|---|---|
| `usb-enum-wait` ENTER 0x8 4499.3 → DONE 12499.4 / 4498.4 → 12498.5 | **8000.1 / 8000.1 ms** (M) | `tgl_usb_console_wait(TGL_USB_WAIT_SECONDS=8)`: a fixed window that polls the EP0 gadget and pats the WDT so the host's `usb_log` can enumerate and read the shim log. It has no early exit, with or without a host. The watchdogs are already quiesced before it (`wdt_quiesce_late`, stamp 0x14 at 4499.1 ms). The only safety duty it carries is servicing a host that is mid-request |
| `usb-enum-wait` ENTER 0x1 16494.1 → DONE 17494.3 / 16393.9 → 17394.1 | **1000.2 / 1000.2 ms** (M) | `tgl_usb_console_wait(1)` before payload admission: "do not abandon an active EP0 transfer". The guard that matters is the `laguna_usb_transfer_active()` refusal after it, plus the loader's own ≤ 1 s drain before the jump |
| `payload-admit` step 0 (after the 1 s window) → step 1: 17494.3 → 19970.2 / 17394.1 → 19817.5 | **2475.9 / 2423.4 ms** (M) | `loader_boot` parses the live FDT a **second** time (`tgl_fdt_memory`). The first parse (fdt-parse 1.7 → console-init 2459.1) costs the same 2.46 s. With the MMU off, every byte read and every stack access of the parser is a Device access. Nothing in the shim writes the tree in between: USB DMA admission avoids it, the UFS DMA arena is in the shim image and is closed before the handoff (S) |
| `console-init` 2459.1 → `disp-record` 3832.4 / 2462.5 → 3831.8 | **1373 / 1369 ms** (M) | `fdt_find_framebuffer` (another full uncached walk), `con_init`, and the display record build. On the DER-safe default the DT framebuffer is never adopted; it only fills a `DTFB` banner line. The stock laguna tree has no fb node (S) |
| `payload-admit` step 6 19987.4 → DONE (entry) 26394.4 / 19834.6 → 26183.5 | **6407 / 6349 ms** (M) | `tgl_segment_copy` of every kernel segment from the embedded payload, the ADT copy, boot_args and the display ADT publish, all with the MMU off. Destination [0x882000000, ba 0x884e14000 + 16 KiB) ≈ 46 MiB, so ≈ 7 MB/s: Device reads and writes, 8 bytes each (M for time, I for the split) |
| kernel `tensor-dpu: pid 1 held for the probe` → `released after 4113 ms` (A7 r1), 4109 ms (p29) | **4.1 s** (M) | `hk_fb_probe=1` in `PHONE_ARGS`: `sweet_scanout.cpp` `probe()` fills and kicks six full-panel colours, 700 ms each, while `sweet_scanout_probe_wait` holds pid 1. It is a diagnostic (the owner's "colour blinking"). It is **not the shim**, and with `hk_fb_probe` absent both the probe and the hold return at once (S) |

Answers: the 8 s window can be bounded to 0.5 s. The 1 s window becomes a drain that waits only while a data stage
is in flight. The copy's cost is the uncached MMU-off path, not memcpy. The cached EL2 map that the chooser already
runs on the phone (`el2_mmu.c`; chooser-v1-r3 → r4 took the decode from 122 s to under 1 s, Android at 167 s → 42 s, PHYSICAL)
is the fix, not an in-place scheme: the destination window and the embedded source are different memory by validation.
The DPU probe is needed for nothing on a normal start. Dropping `hk_fb_probe=1` removes both the probe and the hold.

## 2. What changes (one flag: `TGL_FAST_START=1`; `image_tool.py image ... --fast-start`)

| Part | Change | Files |
|---|---|---|
| F1 | 8 s window → `TGL_FAST_USB_WAIT_MS` 500 ms, then a drain only while a data stage is active, ≤ 1 s. The pre-admission 1 s window → drain only (0 ms when idle). Stamps keep stage 0x0011, args tagged `FAST` | `shim.c`, `tgl_fast_start.c` |
| F2 | `loader_boot` reuses shim_main's admission when the dtb pointer, magic and totalsize match. Otherwise (stamped) it parses as before | `shim.c`, `loader.c`, `tgl_fast_start.c` |
| F3 | Skip the informational `fdt_find_framebuffer` (DTFB banner line) | `shim.c` |
| F4 | Cached copy: EL2 identity map, write-back over the shim image (exec) and [phys_base, top), both widened to whole 2 MiB blocks, everything else Device. On for the segment/ADT/boot_args/display-ADT writes only. Then `tgl_fast_mmu_off_asm` does clean+invalidate to PoC, restores SCTLR_EL2, `ic iallu`, `tlbi alle2`, and invalidates both regions again. This all happens before the USB drain, the deadline check and the EL1 drop (or fastcore). The console is not serviced while cached. A refusal (an avoid range in a cached block, a reservation under the image, not at EL2 / VHE / MMU already on) keeps the uncached copy | `loader.c`, `tgl_fast_start.c`, `tgl_fast_start_s.S`, `el2_mmu.c` (unchanged, reused) |
| kernel | `--fast-start` drops exactly the one `hk_fb_probe=1` token from the `--phone-root` line (refuses if there is not exactly one, or without `--phone-root`) | `tools/image_tool.py` |
| decode | stage 0x00f1 `fast-start` and readable notes for fast/slow `usb-enum-wait` args | `tools/decode-shim-stamps.py` |

New stamp 0x00f1 (arg = step<<56 | value): 1 profile (0xf), 2 fdt-reuse (REFUSED = reason, parsed), 3 cache-on
(DONE = wb blocks<<16 | blocks left Device; REFUSED = reason, 6 = off at build time), 4 cache-off (DONE = cached window µs).
`-DTGL_FAST_CACHE=0` turns F4 alone off (profile 0x7) for bisection.

## 3. What stays (unchanged code paths with the flag on, S)

- Watchdogs: the early survey, the pat through console/USB bring-up, `wdt_quiesce_late` before the window, the UFS WDT
  guard bracket (`wdt_ufs_guard_start/stop`) and its fatal stop check.
- Bring-up deadline: every `bringup_gate(90)` and the loader's `tgl_stamp_over_deadline(90)` refusal.
- Refusals: FDT, payload validation, window/reservation/ramoops checks, cmdline UFS admission, the active-USB-transfer
  refusals (shim.c and loader.c), the display ADT publish failure. The first USB console start is still fatal on failure.
- Panic capture: stage_fail/exc_handler HANG/FAULT screens, the 40 s photograph window with USB service, PSCI reset to
  fastboot, the TSHIMST2 trail (Device memory in the map too). The kernel's `blazer_deadline`, `blazer_panic`,
  `blazer_thermal*` and the governor cap are kernel arguments, untouched (only `hk_fb_probe=1` is removed).
- Console: con_clear/banner and every `con_*` line still paint. Only the DTFB line loses its source.
- Flag off: all 22 shim objects are **byte-identical** to e1bb8f3 (H, §5).

## 4. Seconds saved, per item (A7 r1 → expected)

| Item | Now (M) | Fast start | Saved |
|---|---|---|---|
| F1 main window | 8000 ms | 500 ms (no host); ≤ 1500 ms with a host mid-request (H) | **7.5 s** (6.5 s worst) |
| F1 pre-admission | 1000 ms | ~0 ms idle, ≤ 1000 ms if a data stage is in flight (H) | **~1.0 s** |
| F2 FDT re-parse | 2476 ms | an 8.3 KiB volatile word copy, ≪ 0.1 s (I) | **~2.4 s** |
| F3 DT fb walk | ≤ 1373 ms interval | walk removed. `con_init` and the record build stay (I: the walk dominates; the full parse costs 2.46 s and `fdt_find_ufs` 1.7 s) | **~1.3 s** (I) |
| F4 cached copy | 6407 ms | ~46 MiB cached plus 3 maintenance passes over ~110 MiB, 0.1-0.3 s (I; the chooser's cached decode on the phone is the evidence of scale) | **~6.1 s** (I) |
| Shim total | 26.39 s to `pre-xnu-handoff` | **≈ 7.5-8.5 s** | **≈ 18 s** |
| `hk_fb_probe` hold (kernel) | 4113 ms | 0 | **4.1 s** |
| **Total, power-on to pid 1** | | | **≈ 22 s** (BUDGET.md had 9-15 s + 4.1 s) |

What remains in the shim (M): first FDT parse 2.46 s, console paint ~0.6 s, `fdt_find_ufs` walk ~1.7 s, UFS post-link
route 0xe5 2.1 s, 0xd0 0.13 s. The next candidates, deliberately not in this change: one FDT walk that also returns
the UFS regions (~1.7 s, touches shared `fdt.c`), and the cached map from entry for the first parse (~2.4 s; needs a
coherency review of the in-image UFS arena while its DMA is live).

## 5. Host and object evidence (H)

- `shim/tgl_fast_start_test.c` (run by build.sh): 40 checks, 0 failed. Window on a fake gadget and clock (idle 500 ms,
  no console, mid-request drain 820 ms, never-ending stage bounded at 1500 ms, drain-only, dead clock, frozen clock and
  iteration guard), FDT reuse (byte-identical copy, pointer/magic/size/zero refusals), cached plan on the A7 geometry
  through the real `tgl_el2_build` (31 + 24 blocks WB, fb/stamps/DWC3 Device, a reservation keeps one block Device, a
  reservation under the image refuses the map, overlap/avoid/argument refusals). 13 of 13 hand mutants caught
  (one by hanging, the iteration guard).
- `tools/test_decode_shim_stamps.py` 17 tests OK (3 new). The real A7 r1 dump decodes identically except two new notes.
- `tools/test_image_tool.py` 93 tests OK (1 new: `--fast-start` drops only `hk_fb_probe=1`, refuses twice or without `--phone-root`).
- ARM64 objects (LLVM clang, image_tool's `--phone-root` flags, fixed nonce/epoch): flag off, 22/22 objects
  byte-identical to e1bb8f3. Flag on: `tgl_fast_*`, `tgl_el2_build/mmu_on`, `tgl_fast_mmu_off_asm` (dc civac/msr
  SCTLR_EL2/tlbi alle2/dc ivac) present. shim.o no longer calls `fdt_find_framebuffer` or `tgl_usb_console_wait`.
  No ABS64 in C objects.
- Full `build.sh` (TGL_TOOLCHAIN=llvm) in scratch copies: both link, `nm -u` empty, every build.sh host test passes. In the
  linked flag-on `loader_boot` the order is `tgl_fast_fdt_reuse` … `tgl_fast_cache_on` → `tgl_segment_copy`… →
  `tgl_display_adt_publish` → `tgl_fast_cache_off` → USB drain → `tgl_stamp_over_deadline` → `tegu_el_drop_and_jump`.

Not shown anywhere yet: the cached copy on the phone (QEMU cannot show cache coherency; the chooser's physical r4
proves the map builder and `tgl_el2_mmu_on` on this ABL handoff, but not the return-to-C MMU-off path or an XNU consumer).

## 6. Risks

1. **F4 coherency** (the only part with new physical risk). If a dirty or stale line survived, XNU would run a
   corrupted image: an early XNU panic or silent hang before the root watch. Mitigations: whole-block maintenance,
   avoid ranges, no USB service while cached, a second invalidate after MMU off, uncached fallback on any refusal. A
   hang before XNU's own deadline needs a long press (attended boot only).
2. **F4 may simply refuse** on the phone (the image's 2 MiB blocks touch a reservation or the FDT/initrd): no saving,
   the stamp names why (`cache-on refused: …`). That is not a failure.
3. **F1 and the host console**: with a cable attached the Mac may not enumerate within 0.5 s, so `live.log` can stay
   empty and `run-attempt.sh` may report `ep0_live_watch_s: never`. The watch still runs to `--wait` and the park
   capture is unchanged. Failure paths keep their 40 s USB-serviced photograph window.
4. **F2** trusts that nothing changes the tree between the two parses (S: no shim writer). Any header change refuses
   the reuse.
5. **`hk_fb_probe` off**: no boot of this kernel line has run without it. The first DPU kick moves from the probe
   to backboardd's first present, and the owner loses the colour sequence as an "XNU alive" signal (S: the probe only
   fills, kicks, polls and sleeps; no later code reads its state except `s_on=false` on a probe failure).

## 7. The one attended boot that measures it

Owner present, phone-owner admission first. One variable against the boot it follows: build `a7-fast-r1` with the
exact recipe of the next admitted A7 boot (HANDOFF item 1, `a7-ios-system-r3` = A7 r1 recipe without `hk_bright=140`)
plus `--fast-start`. Before the jump the shim stamps do not depend on kernel arguments, so they compare directly with
A7 r1 (and r3).

```sh
python3 -I tools/image_tool.py image a7-fast-r1 <the r3 arguments, A7-READY.md step 6 minus hk_bright=140> --fast-start
python3 -I tools/image_tool.py check research/images/a7-fast-r1
tools/bootios research/images/a7-fast-r1/boot.img a7-fast-r1 --mach <K>.unstripped --wait 480
python3 -I tools/decode-shim-stamps.py <attempt>/ramdump/kernel.log > <attempt>/stamps-decode.txt
```

Bare `fastboot boot` only, ANDROID_SERIAL set, force-fastboot on (the runner refuses otherwise), return check after.

Read off (stamps vs A7 r1 26394.5 ms `pre-xnu-handoff` ENTER):

| Check | Expect | A7 r1 |
|---|---|---|
| `fast-start` profile | `profile: 0xf` | absent |
| `usb-enum-wait` #1 DONE − ENTER | ~500 ms (≤ 1500 with a host request) | 8000.1 |
| `usb-enum-wait` #2 | ~0-40 ms | 1000.2 |
| `fdt-reuse` | `reused`; payload step 0 → 1 < 0.1 s | 2475.9 |
| `cache-on` / `cache-off` | DONE, wb blocks reported, window < 0.5 s; step 6 → payload DONE < 0.5 s | 6407.0 |
| `console-init` → `disp-record` | ≪ 1373 ms | 1373.3 |
| `pre-xnu-handoff` ENTER | **≈ 7.5-8.5 s** | 26394.5 |
| kernel | no `pid 1 held for the probe`; launchd exec at watch +0.1-0.3 s; root mount and launchd as r3 | held 4113 ms |

Pass: handoff at ≤ 9 s and XNU reaches its root watch (a kernel log in the ramdump at all means the cached copy
delivered an intact kernel). Partial: `cache-on refused` (F1-F3 still measured, F4 needs a placement look). Stop: any
XNU panic before the root watch, a HANG/FAULT screen, or no park within `--wait`. Rollback: the deadline/PSCI reset
parks in fastboot (force-fastboot on), then `return-check.sh`. A stop with `cache-on DONE` points at F4 first: rebuild
the same image without it (`EXTRA_CFLAGS=-DTGL_FAST_CACHE=0` added to the shim flags: profile `0x7`, stamp
`cache-on refused: off at build time`, uncached copy) before any other change.
