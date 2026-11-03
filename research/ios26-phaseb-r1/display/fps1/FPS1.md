# fps1: what caps the sustained frame rate, and a double-buffered copy (2026-11-04, HOST + Mac build + QEMU; not booted on the phone)

Labels: **M** = measured in a named phone log, **S** = source/static (XNU tree, QuartzCore in the 23G90 dyld cache `/data/hackios-qemu/dsc-r6`),
**H** = host test/model, **Q** = QEMU (TCG, no Tensor DPU), **I** = inference.

## 1. Answer

**Short of the GPU, the sustained rate is set by how long backboardd's software CoreAnimation renders a frame, not by the kernel.**
The kernel had one real serialization (the panel copy waited for the previous transfer). fps1 removes it. That gains only when frames render in
under about 10 ms. Whole-canvas scrolling at today's clocks stays about 25-30 swaps/s. "Well above 60 sustained" during a full-screen scroll
needs frames about 2× cheaper. The largest lever left is the CPU cap (`blazer_gov_cap=16`, 533-1075 MHz physical, docs/CPU.md), which is the
PERF-GOV lane. fps1 is what lets a faster CPU turn into 100-120/s instead of stopping near 80-100.

Live evidence: `research/laguna-usb-fix/attempts/live-20261103-234014-a7-fb120/console.txt` (M), SWEET FB rate lines (one per >= 5 s window):

| window | swaps/s | kicks/s | damage | reading (closed-loop model, section 3) |
| --- | --- | --- | --- | --- |
| scroll, partial | 69.5 / 67.9 | 58.7 / 65.3 | 977x792 | ~12-14 ms per frame |
| scroll, whole canvas | 20.3-35.5 | 20.3-33.1 | 1125x2511 | ~30-45 ms per frame |
| idle Home | ~10.0 | ~10.0 | ~120x90 (clock/spinner) | a 10 Hz animation, not a cap |

The four questions:

1. **CA target and advertised interval: already right.** 69.5 swaps/s and 65.3 kicks/s are impossible on CA's literal 1/60 heartbeat, so CA reads
   fb120's `IOMFBDisplayRefresh/displayMinRefreshInterval = 2^32/120` and runs above 60 (M + S, FB120.md §1). Nothing further to advertise.
2. **Pacing loop: not the cap.** With a frame waiting, fb120 polls FRM_DONE every 250-500 µs and copies plus kicks at once (S). The wait that
   matters is (3).
3. **Single swap path: yes, it serialized.** One panel buffer means the 1.6-2.1 ms copy (A7 r3, M) can start only after FRM_DONE. SwapWait answers
   Busy to CA while its swap is queued or being copied (S). So a frame that arrives during a transfer waits for that transfer plus the copy. If it
   misses the TE, it waits a whole TE. Fixed by fps1 (section 2).
4. **Scheduling/clocks: this is the cap.** Render time per frame follows damage area (whole canvas ~2.6× the time of a 977x792 rect, M), as a CPU
   compositor does. The cores are capped at L16 under every A7 line (S: the boot args). No change in this agent's scope; see section 7.

Also found (S, for later experiments; nothing shipped): QuartzCore reads its 260 boolean and 93 float `CA_*` options once, by name, through
`getenv` → `atof`, falling back to a preferences dictionary (`0x183f99ec4` loops over the name tables at `0x1e61fede8` / `0x1e61ff608`;
`0x183fc9050` does the lookup). So the overlay's `hk_env` rows reach them. Candidates related to frame pacing:
`CA_FORCE_TRIPLE_BUFFERED_LATENCY`, `CA_DISABLE_THROTTLE`, `CA_DISABLE_FAST_SWAP_WAIT`, `CA_MINIMUM_FRAME_DURATION`, `CA_FRAME_RATE_POLICY`,
plus `CA_PRINT_FRAME_INFO` / `CA_PRINT_PERF` to measure render ms per frame. Their effects are unverified (I).

## 2. Change (XNU `hk-fps1` = **e505e6e** = hk-int4 f6c8a68 + 2 commits; `0001-hk-fps1.patch` is the cumulative diff, 4 files +219/−17)

- **`hk_fb_fast=2`** = the fast copy (as 1) **plus a second panel buffer**. It reuses an existing token: **+0 boot-arg bytes**. The buffer is
  the flip pool's first slot, 0xf0e00000, 14.6 MB (5120×2856). It is in the unmanaged low bank also under blazer_mem=16
  (`research/ios26-ram-r1/RAM.md`: "panel/flip pool … not managed"), and the DPU fetched from there in r1d. It is mapped write-combined like the
  panel buffer, filled black at start, and kept for the boot.
- Workloop (`vsyncFired`, policy in `sweet_fb_refresh.h`, `sweet_fb_dbuf_step`): with a frame in flight, a waiting frame is **copied into the idle
  buffer** (STAGE). FRM_DONE then **only kicks it** (KICK). With nothing in flight and nothing staged, the frame is copied and kicked (COPY_KICK).
  A staged frame is never overwritten, so every copied frame is shown, in order. If the fetch ends during the copy, the kick happens at once.
  The surfaces are released right after the copy, so SwapWait stops answering Busy about 2 ms after the swap, not after the transfer.
  `paceNextUS` stages at once (1 µs) and otherwise polls as fb120.
- On the exact edges: a swap that presents the panel's own surface is composed in the panel buffer, as with one buffer, with nothing in flight.
  A swap that copies nothing resends the buffer shown. Power-off's black frame resets to the panel buffer and drops a staged frame.
- `sweet_scanout_use_buffer(0|1)` selects the buffer before a copy-path kick. The blazer_usbcon snapshot and hk_screen read **the buffer last
  kicked**, so ui_run screenshots keep working.
- Refused, with `SWEET FB: dbuf off: <why>; one buffer`, unless 120 runs by copy (`hk_fb_refresh=120`) on a scaled scanout. Also refused with
  flip, dirty copy, VRR (121/122) or sweetfb_hz < 60. On: `SWEET FB: dbuf on: second buffer at 0xf0e00000, 14630912 bytes; copy while the last frame is sent`.
- The rate line gains **`busy N staged N`**: SwapWait Busy answers (CA held back by the kernel) and frames copied while the previous one was still
  being sent. Appended at the end, so existing regexes still match.
- `sweet_fb_refresh_decide` takes `sweet_fb_fast != 0`, so 2 still means fast copy.

## 3. Host test (`test/test_fps1.c`, ASan+UBSan, `-Werror`): **PASS, 16,521 checks** (`test/test_fps1.out`)

Gate truth table for fast 0..999 × refresh; exhaustive step table (never a kick with a frame in flight, never overwrites a staged frame); poll
bounds; rate counters. Plus a **closed-loop TE model**: TE 8291 µs, transfer 5370 µs from TE, copy 1.8 ms, 300 µs wakeup jitter. CA renders R ms
±10 % and then either polls SwapWait every 1 ms (coupled), or also starts only on its 120 Hz heartbeat, or never waits (open). kicks/s:

| render | coupled 1 buf | coupled 2 buf | heartbeat 1 | heartbeat 2 | open 1 | open 2 |
| --- | --- | --- | --- | --- | --- | --- |
| 4 ms | 120.6 | 120.6 | 93.8 | **120.0** | 120.6 | 120.6 |
| 6 ms | 118.2 | 120.6 | 79.9 | **97.4** | 120.6 | 120.6 |
| 8 ms | 80.8 | **99.8** | 60.0 | 60.0 | 120.4 | 120.5 |
| 10 ms | 79.7 | 83.3 | 60.0 | 60.0 | 99.9 | 99.8 |
| 12 / 15 ms | 70.1 / 58.8 | 71.3 / 58.8 | 60 / 46 | 60 / 46 | 83 / 67 | 83 / 66 |
| 25 / 35 ms | 37.0 / 26.9 | 37.1 / 26.9 | 31 / 24 | 31 / 24 | 40 / 29 | 40 / 29 |

At 2.1 ms copies and 6 ms frames: 1 buffer ~90/s, 2 buffers ~111/s. **Reading:** the measured ~25-30/s whole-canvas and ~65/s partial-damage
windows sit where two buffers change nothing (render ≥ 12 ms). Two buffers matter once frames get to 6-10 ms. Which CA model is right is what the
new `busy` counter tells on the phone.

## 4. Build (Mac, `tools/build_fps1.py` = int4's, renamed; `receipts/build_fps1.out`)

Exclusive `/tmp/fleet/kernel-build-slot.lock`, tree p1 b228c4f clean, `mk.sh -j8` rc 0. Restored to p1 and rebuilt (rc 0, obj kernel
201a1860…; none of the hk_ustack/fb120/fps1 strings). First commit 4bda055 was also built (`receipts/build_fps1-r0-4bda055.out`); it is superseded.

| artifact | sha256 |
| --- | --- |
| `build/kernel.fps1` | `8a9f2f68dcacc1c39cf800db4d8095075b3040ce2f16583ab00b2455984c1cac` |
| `build/kernel.fps1.unstripped` | `396ea50a7af4673dd8f2f90e3c6a2ccdaedeadf1f55efe1423d0466a462504a4` |
| `obj/SweetFramebuffer.cpo` / `sweet_scanout.cpo` | `3eea997a…` / `b97485cd…` |

ARM64 (`receipts/kernel-verify.txt`): Mach-O arm64 NOUNDEFS, `llvm-nm -u` = 0. Present: `AppleCLCD::dbufStart`, `AppleCLCD::pendingUsesPanel`,
`AppleCLCD::present(…, unsigned long)`, `_sweet_scanout_use_buffer`, `_sweet_scanout_back_attach`. `dbufStart` compares `sweet_fb_fast` with
`#0x2` and calls `withPhysicalAddress`. `vsyncFired` calls `present` → `_sweet_scanout_ready` → `_sweet_scanout_use_buffer` →
`_sweet_scanout_kick_traced` → `paceNextUS`. The strings `dbuf on: second buffer`, `dbuf off: %s; one buffer` and `busy %u staged %u` occur
once in kernel.fps1 and 0 times in kernel.int4.

## 5. Image (Mac, `tools/mkimg_fps1.sh`; tool `tools/image_tool_fps1.py` = int4's + `hk_fb_fast=2` + a kernel-string check)

| image | boot.img sha256 | line |
| --- | --- | --- |
| **`a7-ios-system-fps1`** | **`95e112551c18f4dd261401d7d8c5bc2559f25af7aee3dced873dd1c3160e0782`** | int4's with `hk_fb_fast=1` → `2`: **1022 B** (int4 1022, int1 1018, limit 1023), 57 tokens |

`check` OK with image_tool_fps1.py and with the shared tools/image_tool.py, which was not edited (`receipts/image-check*.txt`). The manifest
differs from int4 only in kernel/payload/ADT/image hashes, ids, the token and the tool hash (`receipts/manifest-diff.txt`). The r0 image on
4bda055 (`a7-ios-system-fps1-r0`, 423b7daa…, never booted) and its receipts are under `receipts/r0`.

## 6. QEMU (m1box rig, `tools/qemu_preflight.py --keep hk_fb_fast=2 --keep hk_fb_refresh=120`, 600 s TCG)

| run | kernel | verdict | lines |
| --- | --- | --- | --- |
| qf-a7-ios-system-fps1-1104-002121 (`receipts/qemu-r0/`) | 4bda055 | **PASS**, 0 findings, 0 panics, Home-equivalent 187 s, backboardd/SpringBoard never respawned | `refresh asked 120, running 120`; `refresh 120 by copy: fast 2`; **`dbuf off: no scaled scanout; one buffer`** (correct: no DPU); rate line ends `busy 0 staged 0` |
| **qf-a7-ios-system-fps1-1104-003433** (`receipts/qemu/`) | **e505e6e** | **PASS**, 0 findings, 0 panics, Home-equivalent 422 s, backboardd/SpringBoard never respawned | same lines: `fast 2`, **`dbuf off: no scaled scanout; one buffer`**, rate line `… busy 0 staged 0` |

QEMU has no DPU, so it can only show the gate refusing and no regression. The double buffer itself can be proved on the phone alone.
fairplayd.H2's 28-38 respawns come from the rig (as in fb120). Home-equivalent 422 s against r0's 187 s is TCG timing on a shared rig: the same path runs (dbuf is refused at start in QEMU), and no daemon respawned or crashed differently. I.

## 7. Phone test (coordinator; owner present; bare `fastboot boot`, return check after)

```
tools/live_boot.sh research/images/a7-ios-system-fps1/boot.img a7-fps1 \
  --mach research/ios26-phaseb-r1/display/fps1/build/kernel.fps1.unstripped --wait 1080 --sync-tools \
  --ui-script research/ios26-phaseb-r1/display/fps1/test/scroll_fps.ui
# then research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-fps1-after-boot
```

`test/scroll_fps.ui` (85 steps, `ui_run.py --check` OK): wait_home; 12 Home-page flings; Settings; 40 vertical flings (~45 s, whole-canvas);
10 × 900 ms drags; Home; 30 s idle. `mark` lines bracket each phase in markers.txt. Rollback: int4 (`hk_fb_fast=1`).

Read, between `fps-scroll-start` and `fps-scroll-end`:

1. Gate: `SWEET FB: dbuf on: second buffer at 0xf0e00000, 14630912 bytes; copy while the last frame is sent`.
2. **The success rate line:** `SWEET FB: rate swaps N/s kicks K/s … busy B staged S`, with **K > 60.5 in at least 2 consecutive windows**
   (probe hz120 partial). The target is **K ≥ 100 in 3 consecutive windows** (hz120 works). `staged` > 0 proves copies overlapped transfers.
3. No regression: `tensor-dpu: frames … refusal 0`; no `kick failed`, `latched` or `no FRM_DONE`; later underruns not above fb120's (~4 % of
   frames); no panic; ui_run screenshots not black; the owner sees no tearing, flicker of an older frame, or stale tiles.

Reading the result. Expected (I): partial-damage windows ~65 → ~70/s; whole-canvas windows unchanged at ~25-35/s.
- High `busy` (≈ swaps or more) with K well below 120 means CA is held by the kernel, so a deeper queue would help.
- `busy` ≈ 0 with K ≈ swaps means CA is render-bound, and only cheaper frames help: clocks (PERF-GOV, `blazer_gov_cap`), or CA work reduction via
  the overlay env above.
- Pair the rate lines with `HK TOP` backboardd CPU ms per 30 s ÷ frames for ms/frame.

## 8. Probes (`probes-hz.patch` for docs/probes.yaml; applies to HEAD and the current working copy; `tools/probe_eval.py` gains `sustain`)

- New check option `sustain: N` (with `group` and `ge`): N consecutive matching lines, in log order within one source, all ≥ `ge`.
  `{group}` reports the run's lowest value and `{group}_windows` its length. Tests in `tools/test_probe_eval.py`: 24 OK, 5 of them new.
- **hz120:** works = `running 120` + **kicks ≥ 100 sustained 3 windows (≥ 15 s)**; partial = kicks **> 60.5 sustained 2 windows**; built = `running 120`.
- **hz60:** works = `running 60|120` + **kicks ≥ 55 sustained 3 windows**; partial as before, on kicks.
- On the fb120 boot (`receipts/probe-fb120-boot.txt`): hz120 **built** (was partial on the mode line alone: 65.3 held one window only), hz60 **partial**.
