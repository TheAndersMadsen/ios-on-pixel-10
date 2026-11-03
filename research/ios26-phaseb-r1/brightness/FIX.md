# Brightness requests to the panel: brt1 (2026-11-03, HOST build, not booted)

Labels: **physical** = read in a phone ramdump that is already local; **host** = built or run on m1box or the Mac; **inference** =
not tested. No phone access and no QEMU run in this work. QEMU cannot exercise this path because it publishes no `backlight-control`
(corebrightness/FINDINGS.md §2).

## Answer

**"queue only" decides nothing.** It is a fixed suffix of the log line in `sweet_bl_result()` (`iokit/Kernel/arm/SweetFramebuffer.cpp:270`
on `hk-touch-direct`). `rc 0` means the request was validated and stored as the brightness target. The DCS path is **already wired**
behind it, and it **runs on the phone**:

```
AppleARMBacklight::setProperties -> sweet_bl_set -> AppleCLCD::queueBrightness (workloop) -> brightnessAction
  -> sweet_scanout_bright_nits(q16) -> hkb_nits: target = hkb_dbv_q16(q16, cap)      (clamped to 10..cap nits)
vsyncFired (scanout thread, nothing in flight) -> sweet_scanout_bright_service -> hkb_step (at most every 16 ms)
  -> tdpu_panel_acl_off (DCS 0x55 0x00, once, below DBV 3726) and tdpu_panel_dbv (DCS 0x39 long: 0x51, DBV high byte, low byte)
```

`tdpu_panel_dbv` sends the same packet as the shim's stage G brightness write (`shim/tgl_dcs.c:518`, high byte first). The shim's
write is the one proven physically, with readback: "Brightness cap settled at DBV 4637 from 0x295e" (`research/journal/HANDOFF-full-20261102.md:43`).
The difference is timing. The shim writes before the DPU starts. The kernel writes between frames while video runs. The kernel
has no DCS read, so it cannot read the level back.

**What the phone did (physical, ramdumps already local).** In each of r4-bl, r5-accel, r7-touch, r8-settings and r9-apps-ufs:

| boot | `brightness-nits` requests | nits asked | `bright transport` lines | DBV sent | rc |
| --- | --- | --- | --- | --- | --- |
| r4-bl | 46 | 131.7 – 140.0 | 64 | 4635 → 4343 | all 0 |
| r5-accel | 46 | 131.7 – 140.0 | 64 | 4635 → 4371 | all 0 |
| r7-touch | 48 | 131.1 – 140.0 | 64 | 4635 → 4348 | all 0 |
| r8-settings | 24 | 130.3 – 140.0 | 32 | 4635 → 4392 | all 0 |
| r9-apps-ufs | 48 | 131.1 – 140.0 | 64 | 4635 → 4303 | all 0 |

(Each ramdump ring holds the boot twice, so the raw counts are double the figures above.) So the requests were not stuck in a
queue. They were sent: CoreBrightness's own boot ramp from 140 down to about 131 nits, about 6%, a change nobody would notice. Then
the log went quiet by design. Requests stop logging after 80 lines and successful sends after 64. **Any later request, including a
slider move, was sent without a trace**, so "never applied" cannot be read from those logs. No boot has had a working slider
in front of the owner yet. r4-bl predates the direct-touch fix. On r8 the Control Center was black. The "applied?" question in A7.md
was never answered.

A third of backboardd's calls (`route unknown rc 0xe00002c7`) use keys that no route accepts. The old log did not print the key
names. brt1 prints them (see below), and those calls stay refused.

**Not established:** whether DCS 0x51 sent during video changes the glass. Only the owner's eye can settle that in the attended
test. The rc says only that the DSI CRI went idle and raised no SError. Inference: it should land, because the packet is the same
one Android's driver sends while video runs.

## Change: XNU `hk-bright-brt1` commit 4480b5a7fb2500eae78aeeb155f45b2a6051f91a (Mac release tree, host build)

Base `hk-touch-direct` e731e68. On top of it, cherry-picked unchanged: 44689e0 (AKS wrap), eb2d19b (AKS user session) and cc42295
(varfs renamex). With those three, the r10-perf recipe's `blazer_aks_*` / `blazer_persona_log` args keep working. Without them the
image would lose what r10's kernel `kernel.rootview-bl-aks-us2` (d7f47431, `hk-aks-usersession` = cc42295) had. Picked commits:
d2f4d47, 7343d9a, 2fbe8f1. Then the patch `0001-hk-bright-brt1-dcs-log-q16-max-nits.patch`
(sha256 af861b022ca4ee05ad0e535555339f18ef0067a751c19bd31aeb88014ffbf777; 3 files, +59 −7):

1. **16.16 max nits.** `user-accessible-max-nits` and `edr-max-nits` are now `(uint64_t)cap << 16` instead of raw `cap`. CoreBrightness
   reads both with `loadFixedFloat:` (int / 65536), so raw 140 read as 0.0021 nits. They now read 140.0, matching the calibration's
   Lmax and the `brightness-nits` max.
2. **Truthful request log.** The suffix is now `(queued for DCS)` for rc 0 and `(refused)` otherwise. The 80-line cap is unchanged.
3. **Unknown keys named.** For a request no route accepts: `SWEET BL: unknown request keys <count>: k1 k2 k3 k4`. Only top-level
   names are printed, never values and never nested keys, for at most 8 calls a boot. The request is still refused with
   `kIOReturnUnsupported`.
4. **The transport log keeps the slider visible.** `hk_bright_map.h` gains `hkb_log_due()`, which logs every failure and the first 64 sends,
   then any send 128 DBV or more from the last one logged, up to 1024 lines. It also gains `hkb_dbv_nits_x10()`, the inverse curve, used
   only for the log. The new line is `tensor-dpu: bright transport sent_dbv 2904 (~50.0 nits) cap 140 acl_off 1 rc 0 n 71 (no panel readback)`.
   A full slider sweep from 10 to 140 nits is about 25 lines.

**Unchanged, and still the safety boundary.** `hkb_cap_ok` limits cap to 10..140 (`HKB_MAX_CAP 140`). `hkb_dbv_q16` clamps every
request to 10..cap nits before any DBV exists. The ceiling is DBV 4636, about 140 nits on the inferred curve. `tdpu_panel_dbv`
refuses anything above 13418. Zero, negative and non-32-bit values are refused, and the `brightness` fraction route stays refused.
Nothing can reach the panel above 140 nits, and nowhere near the "860 nits under UI: never" limit.

## Evidence

- **Host test:** `test/test_brt1.c` against `ref/hk_bright_map.h`, the exact patched header. It passes under clang `-Wall -Wextra -Werror`
  and again with ASan/UBSan: **9142 checks, 0 failed** (`test/RESULT.txt`). It covers:
  - Every 32-bit request (step 9973, plus INT32_MAX) goes through the real `hkb_nits`/`hkb_step`. The highest DBV sent is 4636, and hk_bright stays alive.
  - `140 << 16` / 65536 = 140.0 and fits in a signed 32-bit value.
  - `hkb_dbv_nits_x10` inverts `hkb_dbv_q16` to within 0.2 nits on 10..140 and is monotone.
  - The log policy: the boot ramp gives 64 lines; two full slider sweeps give 96 lines, each end logged within one step; failures log
    past the cap; and `acl_off` is sent once on the way below DBV 3726.
- **Kernel build** (Mac, `build/build_brt1.py`, `build/build_brt1.out`): `mk.sh -j8` under the exclusive lock
  `/tmp/fleet/kernel-build-slot.lock`. The tree started on `p1` b228c4f, clean, with no other build running. Build rc 0 in 53 s
  (log `research/ios26-release-r1/logs/brt1-build.log`, Mac). The tree was then put back on **p1 b228c4f** and rebuilt, rc 0
  (`logs/brt1-restore-p1-build.log`; obj kernel b5e388d5…, the link is not reproducible).
  - `kernel.rootview-bl-touch-aks-us2-brt1` **1bd71e9c51cdd1013bc0ee0b4ff1530159eec5cba2f81718905c22b0a8db3dd7**,
    Mach-O 64-bit arm64, UUID 87487ADD-7276-323B-BD5D-A5F2E3866BA3.
  - `.unstripped` 815900ca0b079856391260cbaac609d8738e9138c7e72f69ea90d23a77613364. Both stay on the Mac in
    `research/ios26-phaseb-r1/brightness/build/`.
- **Binary** (`build/binary-verify.txt`, `build/publishBacklight-disasm.txt`):
  - Strings in both kernels:
    - present: `queued for DCS`, `unknown request keys`, `nits) cap %u acl_off`, `sweet_touch_indirect` (touch), `SWEET AKS: wrap/unwrap on`,
      `blazer_aks_usersession` and `SWEET BL: calibration`;
    - gone: `queue only` (0).
  - `AppleCLCD::publishBacklight` computes `ubfiz x22, x20, #16, #32` (cap << 16) and passes x22 with `w3 = 32` to three `setProperty`
    calls: the two max-nits properties on the backlight (x19), then `IOMFBBrightnessLevel` on the framebuffer (x21).
  - `sweet_bl_set` now calls `OSCollectionIterator::withCollection`, so the unknown-key logger is inlined, and it still reaches
    `AppleCLCD::queueBrightness`.

## Image `a7-ios-system-brt1` (Mac `research/images/`, host build)

- Recipe: `a7-ios-system-r10-perf`'s, exactly as in `perf/tools/run_mac.sh` step 3. That means perf overlay 95701ed9…,
  `--phone-route ufsroot`, 5 cores, bootcpu 0x200, canvas 1125x2511, deadline 300 and the same phone args, including **`hk_bright=140`**.
  Only `--kernel`/`--kernel-sha` change. Script: `build/mkimg_brt1.sh`.
- **boot.img 8a7d453d3fd1760e8880c76bc7b0339b37af71a7e4ece571a121f3dc0bf7d6cd**, payload 1af0737c…, margin 39,999,120 B.
  `image_tool.py check` gives `OK a7-ios-system-brt1 bootable`.
- **Cmdline: identical to r10-perf, 1015 bytes (≤ 1023), 57 tokens.** The manifest diff (`build/manifest-diff.txt`) shows only:
  - the kernel (mach) and what follows from it: payload, image, margin −208 B;
  - the per-build ADT seed, nonces and epoch;
  - `tools.image_tool.py`: the Mac copy is now b4909202… where r10 used 45eadfe3…. Someone else's uncommitted edits added
    allow-list entries (Wi-Fi join, usbnet, gpu) and nothing this image uses.
  
  `kernel_end`, segs and the overlay placement are unchanged.

## Attended test (owner, bare `fastboot boot`, then the return check)

`tools/bootios research/images/a7-ios-system-brt1/boot.img a7-ios-system-brt1 --mach research/ios26-phaseb-r1/brightness/build/kernel.rootview-bl-touch-aks-us2-brt1.unstripped --wait 480`

1. Wait for Home, as r9/r10 did on `rd=ufsroot0`. The panel starts at about 140 nits, CoreBrightness's start, then eases about 6% lower.
2. **Control Center:** swipe down from the top-right. If the brightness slider shows, drag it **all the way down**, hold 3 s, then
   **all the way up**, then to the middle. Repeat once.
3. If Control Center does not open or stays black (as on r8): open **Settings > Display & Brightness** and drag that slider the same way.
4. The owner says whether **the panel visibly dimmed and brightened**. At the bottom it should be clearly dim, about 10 nits (DBV 1397).
   At the top it should be as bright as the boot, never brighter.

Read from `ramdump/kernel.log`:

- `SWEET BL: AppleARMBacklight published, cap 140 nits` and `calibration 7 table entries`, with 0 backboardd usertraps.
- `SWEET BL: request backboardd route brightness-nits raw … (queued for DCS)`.
- While the slider moves: `tensor-dpu: bright transport sent_dbv … (~N nits) … rc 0`, falling toward `1397 (~10.0 nits)` and rising
  back to about `4636 (~140.0 nits)`, about 25 lines per sweep. The maximum `sent_dbv` must be ≤ 4636. Any rc ≠ 0 ends hk_bright for
  the boot and is logged.
- `SWEET BL: unknown request keys …`: record the names for the next change.

Outcomes:

- **Log sweeps and the panel visibly changes:** brightness works. Update README "Brightness" to ✅ at the 140-nit cap.
- **Log sweeps but the panel does not change:** the in-video DCS write does not land. The next step is a panel readback
  (0x52, as in the shim's `bright_read`) or sending in LP mode (`tx_lp`). The cause is in the transport, not in iOS.
- **No transport lines after the boot ramp while sliding:** the slider does not reach `AppleARMBacklight`. Look at the request and
  unknown-key lines.

There is no flash, no partition write and no slot change. The phone was not touched in this work.

## Files

- `FIX.md`: this file.
- `0001-hk-bright-brt1-dcs-log-q16-max-nits.patch`: the XNU change, applied on hk-touch-direct plus the three picks.
- `ref/hk_bright_map.h`: the patched header, an exact copy of what the test includes.
- `test/test_brt1.c` and `test/RESULT.txt`: the host test and its output.
- `build/build_brt1.py`, `build/build_brt1.out`: the kernel build and the p1 restore (Mac).
- `build/mkimg_brt1.sh`, `image-build.txt`, `image-check.txt`, `manifest-diff.txt`, `SHA256SUMS`: the image (Mac).
- `build/binary-verify.txt`, `build/publishBacklight-disasm.txt`: the binary checks.
