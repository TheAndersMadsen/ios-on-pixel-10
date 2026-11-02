## Active fleet handoff, 2026-11-02 09:22 CET (Codex)

User renewed the goal: native iOS 26 on Pixel 10 Pro, optimized non-Mesa GPU and broad hardware completion. **11 Codex agents launched**, replacing usage-limited Claude work; roster with task IDs and links: `research/ios26-fleet/resume-20261102/fleet.json` (local, ignored). Owners: gpudrv, gpucc, metaldrv, gpumem, dpu, performance, wlbt, audio_sensors, power_input, peripherals, overlay_perf. All read and append BOARD.md; parent alone handles USB, phone boots, release integration and commits. Earlier native resume agents were interrupted; new owners recover their partial files.

**Verified in this recovery:** old fleet failed on Claude usage; existing source/artifacts preserved. Last completed physical UI benchmark remains `20261102-084446-bench-g1-r1` (Settings launched; home transition abort). The queued `/tmp/fleet/bench3.sh` requests p26 + hgltrack + cap13 (1536 MHz), but **no completion result verified**. `20261102-091607-sensor-stream-r2` has no captured result verified yet. At 09:20 process inventory found no matching bootios/run-attempt/fleet shell; reconcile device and attempt state before another boot. Do not assume interrupted host jobs imply phone reset.

**Immediate integration priorities:** verify compositor hgltrack and IOSurface 1200 fixes; finish/test UFS adaptive waiting and governor idle tick; measure a controlled speed benchmark. Depth recovery identified that allowing `blazer_ufs_step_us < N882_POLL_US` invalidates the poll bound: excluded pending correction. Higher clock limits must follow measured guard prerequisites; existing notes disagree in age, so read gov.md and exact captures before use. GPU firmware execution, DXT compiler and real Metal acceleration remain unproved.

No new physical test, root write or flash performed by this recovery. Destructive steps still require explicit approval. Research, firmware, Apple artifacts and dumps stay out of git. Older handoffs below contain stale running-agent and boot-state claims; dated physical captures take precedence.

## Handoff, 2026-11-02 09:15 (parent): read `research/ios26-fleet/STATUS.md` first

Tracked tree: status refreshed after `0e91414`; this note's commit is the newest on `origin/ios26`. `research/` stays git-ignored.

**Physical since 07:58** (captures under `research/laguna-usb-fix/attempts/`, kernel p26):
- `gov-g1-r1`, image `91fbe420…`: PASS, deadline end at 900 s. 125 `blazer-clock` reads, 0 off by more than 2%; cores step 533<->1075 MHz; Tj 33-35 C; about 240 mW idle (estimate). `handoffs/gov.md`.
- `20261102-084446-bench-g1-r1` (p26 + gov + fallback `hk_ui`): all 22 script tokens ran; scripted tap 147,274 -> `exec Preferences` pid 177, Settings launched from a script for the first time. Home key -> backboardd new surface 1125x2511 -> `push_surface` assertion (`ogl-context.cpp:1186`) -> SIGABRT; SpringBoard, Preferences, Spotlight respawned. Owner's long press ended it at 480 s, Tj max 35 C. `handoffs/bench.md`.

**QEMU or host only, not phone evidence:** `colour-1` (QEMU, p26, `qemu-test5.ovl`): cover works, Settings draws its titles, text and coloured icons; a sampler dylib injected into SpringBoard ran. `hgltrack.dylib` overlay `p5-merged-r2-gltrack.ovl` `61c38161…` (bench-g2-r1) is built, host-checked, not run: unknown whether our kernel allows `vm_protect` copy on shared-cache data. `hk_panel_hz=120|60|30|10` is compiled (release 1074), never run. `handoffs/gpugl.md`, `overlay.md`, `release.md`.

**Agents running (host or QEMU, none commits; parent alone boots):** GPU kernel driver, shader compiler, Metal user driver, GPU memory/IOSurface, Mesa hardware route, display DPU, Wi-Fi/BT iOS integration, depth tuning, gpugl (p3 in QEMU, detached pid 78844), bench.

**Next:** bench-g2-r1 on the phone with `hgltrack` (look for `HGLTRACK: SWContext slot wrapped`, then the home key without a backboardd abort); gov on the daily line; Settings' colours on the phone; GPU ID read; Wi-Fi regulatory then join (owner's transmit decision). Open owner decisions unchanged from `STATUS.md`.
`README.md` status comes from `docs/status.json`: edit it, run `python3 -I tools/readme_status.py`.

# iOS 26 on blazer (Pixel 10 Pro, Tensor G5) - working notes

## Pixel 10 Pro port handoff (2026-11-01, current)

**Active state, 2026-11-02 01:15:** iOS 26 root r3 is on the phone (one approved write, spent); home screen and touch work physically (`HANDOFF.md` top). Owner holds phone boots until they say. Order and owners: `research/ios26-fleet/PLAN.md`, state `research/ios26-fleet/STATUS.md`, next boot table: `research/ios26-fleet/handoffs/release.md`, section "Next try". Newest kernel: `research/ios26-release-r1/artifacts/`. Don't boot Android: it may destroy the root (`handoffs/android-partition.md`). A root change needs new owner approval.


Workspace `/Users/andersmadsen/Developer/personal/hackios`. Evidence history: `BLAZER.md`.
Latest detail: `HANDOFF.md`.

- Goal: **Boot native iOS 26 with visible interactive UI, working touch, stability and
  repeatable boots.** The owner dropped iOS 16 on 2026-11-01; that line is frozen on branch `ios16`, tag
  `ios16-final`. Work here on branch `ios26`. Dated notes below are iOS 16 history, but their hardware facts hold.
- Reached on the phone, all with iOS 16 and `xnu-8796.121.2`: UFS at HS gear 4, 16 KiB pages, 4 GiB, launchd and SpringBoard from the full root,
  RAM scanout to the panel from the shim. Not reached: anything on iOS 26 or XNU 12377, iOS's frames on the panel, touch, automatic recovery.
- Use temporary `fastboot boot`. Confirm each destructive step with the user.

Current blocker: can iOS 26 draw without a GPU driver? Tegu reports a buggy iOS 26 UI on its Pixel 9a, but through its Mali Metal driver; our GPU is Imagination. Open: no recorded UI without Metal.
Next concrete action: read `research/ios26-root-r1/FINDINGS.md` (go/no-go) and `research/ios26-kernel-r1/FINDINGS.md` (tegu series plus blazer hardware layer).
Detail in `HANDOFF.md`.

### Carried from iOS 16 to this branch

- `shim/`: HS gear 4, PHY check, PWM fallback, stage marks (gates off by default) and the DPU code `tgl_dcs.c` from r1d, built with `TGL_ALL_STAGES`, `TGL_ALL_DCS`, `TGL_FRAME_RUNG=3`.
- `tgl_dcs.h` keeps r1d's record address `0x9542a000`, which is also the UFS record's. Before enabling the DPU stage with UFS on, move it to `0x955e0000`, as `research/ui-integrate-r1/snapshot/` does.
- `frame_tables.h` holds offsets and PPS generated from GPL-2.0 vendor source; decide its license before publishing.
- `xnu/ios16-base/patches/`: 8796 drivers, the parts source for a 12377 port. They don't apply to 12377 as they stand.
- Kernel base: `research/upstream/ios-tegu-gh-20261101`, branch `ios26-bringup`, `d807098` (Pixel 9a, Tensor G4), at the owner's instruction. No license: local use only, nothing published without the author's permission. Its hardware values don't apply here.

### 2026-11-01: ufs-observe-r2

Physical read-only boot succeeded, 35 reads. Link preconditions hold. Detail in `HANDOFF.md`.

### 2026-11-01: helpers running

Parent started link, post-link, SMMU, handoff, APFS, dyld, launchd, display and tools agents,
host-only, in `research/<topic>-r1`. Not yet reviewed. Parent boots ufs-link-r1 after review.

### 2026-11-01: tools agent reviewed

Parent reran tool tests. `capture-fastboot.py --named-only` no longer needs a lease; `tools/bootios`
waits for park and captures. Neither has run on the phone since the change.

### 2026-11-01: SMMU, dyld, launchd and display agents reviewed

Parent spot-checked; none of this ran on the phone except the capture it reads.
- Parent confirmed in the r2b capture at offset `0x1000ca`: `initproc failed to start -- exit reason
  namespace 2 subcode 0xb`. Parent decoded GBPA `0x2e1f`: bypass, Outer Shareable, cacheable. Inference: keep
  cache maintenance; refuse DMA unless GBPA still matches. Plan: `research/ufs-dma-r1/FINDINGS.md`.
- Launchd agent: the panic is a compact-root defect (stale ADRP, 8,572 sites by static scan; cause inferred).
  Do not patch sites one at a time. Reader's "no panic string" and `run-attempt.sh`'s default `--mach` are
  wrong for current boots. `research/launchd-panic-r1/FINDINGS.md`.
- Dyld agent: cache needs 16 KiB signatures accepted and a window above 1 GiB; 4 KiB-hardware behaviour
  untested. `research/dyld-cache-r1/FINDINGS.md`.
- Display agent: cheapest visible test is display-dcs-r1, one DSI0 boot, user films. Specified, not built.
  Its ABL reading is from slot a. `research/ui-touch-r1/FINDINGS.md`.
- An earlier firmware-lifetime task was stopped by a platform safety flag (N520 `STOP-RECORD.md`). Do not
  reroute it. SMMU and display agents read small ABL sections; no further ABL disassembly is requested.
- Started: qemu agent, `research/fullroot-qemu-r1`, to test the full root in a guest.

### 2026-11-01: handoff agent reviewed

Host only, unapplied: XNU takes over UFS from the shim, gated off by `TGL_UFS_HANDOFF`, `rd=md0` then switch root.
Not linked, not booted; needs a working link and READ first. `research/ufs-root-handoff-r1/DESIGN.md`.

### 2026-11-01: QEMU agent reviewed

QEMU only, parent checked the log: full 20F66 root, `rd=md0`, 16 KiB pages: cache maps and launchd says `hello`, no
panic in 290 guest seconds. Supports that the phone's panic is a compact-root defect; not isolated. Phone still
needs a physical window above 1 GiB and 16 KiB signatures. `research/fullroot-qemu-r1/FINDINGS.md`.

### 2026-11-01: APFS agent reviewed

Host only; parent checked receipts. Reader reads staged root `637103e1…`: 45,044 files, 5.64 GB, 0 errors. Not run under real
XNU VFS or UFS. Unapplied: `requests` race fix, short-read check before UFS. `research/apfs-reader-r1/FINDINGS.md`.

### 2026-11-01: input agent reviewed

Host only, unapplied: keys are AP pads on `cpm_pinctrl`, not AoC; battery gauge max77779 on SPMI. No service stubs known to be required for a first UI
boot, resting on a QEMU run. `research/buttons-power-r1/{FINDINGS,STUBS}.md`. Probe keyprobe-r1 not run; it needs someone pressing keys.

### 2026-11-01: page16k-r1

Physical: XNU ran at shift 14 with 4 GiB at `0xa00000000`, same compact-root panic. Detail in `HANDOFF.md`.

### 2026-11-01: userland agent's lead, phone-r1 booting

QEMU, not the phone: with md1 `de340c95` (407 jobs) the same root spawned SpringBoard and backboardd, and drew the boot logo. The Restore branch is not the wall.
SpringBoard aborts on a bounding path bitmap; suspect missing `/product`. Stability agent's tool fixes applied: `tools/bootios --mach --wait`, `tools/boot-summary.py`.

### 2026-11-01: ufs-speed-r1

Physical: HS gear 4, 30 MiB/s, up from 0.53. Detail in `HANDOFF.md`.

### 2026-11-01: display-frame-r1c

Physical: native test pattern on the panel. The owner saw it flash. Detail in `HANDOFF.md`.

### How work runs

- One parent agent does the work, owns USB and runs the boots. It records results here and in
  `HANDOFF.md` as dated bullets, newest first.
- Use helpers for independent work, as many as the work supports, named by purpose ("touch agent",
  "shader agent"). The parent checks each result itself and reruns its tests before relying on
  it, and writes what it found ("Parent reviewed ...: ...; requested ...").
- Experiments live in `research/<topic>-rN`, with N going up per retry. Say whether each is
  built, deployed or verified.
- `research/laguna-usb-fix/native-fleet-20261031/` holds older N-numbered work. Read it as
  history; do not add to it or use N-numbers.

### Hardware facts

- `google,lga-blazer`, "BLAZER MP based on LGA". Blazer device tree:
  `research/laguna-foundation/kernel-blazer/devices/blazer/fdt/laguna.dtb`.
- Log RAM: 4 MiB dump at `0x95200000`. ramoops `0x95200000..0x953FFFFF`, pmsg
  `0x95400000`, shim stamps at pmsg+0x30000. Decode with `--dump-base 0x95200000`.
- USB: DWC3 `0x0c400000`, wrapper `0x0c450000`.
- UFS: HC `0x3c400000`, pinctrl `0x3C590000` (pad 0 reset, pad 8 `AP2PMIC_UFS_EN`).
  Samsung KLUDG4UHGC, UFS 3.1, 4 LUNs, HS gear 4 under ABL.
- Source order for UFS: shipped `ufs.ko` (6.12.81), `kernel_pixel_6.12@5940a317`,
  kodiak, then `e214813c` (6.6). The `*_OFFSET` constants in the latter's
  `ufs-regs-gen.h` are wrong.
- Sizes: `system.apfs` 2,476,732,416 B; 20F66 shared cache 2,722,512,896 B. They do
  not fit the 64 MiB RAM-boot path.

### Local artifact locations

- Attempt ledger: `research/laguna-usb-fix/ATTEMPTS.md`. Captures:
  `research/laguna-usb-fix/attempts/`, `research/laguna-usb-fix/automation/state/device-attempts/`.
- Older agent work: `research/laguna-usb-fix/native-fleet-20261031/N*/`.
- Kernel tree and build: `research/laguna-foundation/kernel-blazer/`; iOS 16 port patches: `xnu/ios16-base/patches/`.
- Boot runner: `research/laguna-usb-fix/run-attempt.sh`, called by `tools/bootios`.
- Root images: `research/workspace/iosroot/`, `research/laguna-image/`,
  `research/laguna-usb-fix/root-upgrade/`.
- Vendor sources: `research/upstream-20261101-pixel10pro/`. Other sources: `research/upstream/`,
  `research/workspace/sources/`. Hardware dumps: `research/workspace/hardware/`.
- Old builds: `research/workspace/builds/`. Finished work: `research/archive/`.
- Earlier documents: `research/notes/`, `research/laguna-usb-fix/docs/`, `research/SESSION-STATE.md`.
  They are dated records and may link old paths.
- Every move: `research/legacy-root-20261101/PATH-MAP.json` and `path-maps/*.json`.

## 2026-11-01: documentation restructured

Root documents rewritten to the layout and working style of the Pixel 9a `ios-tegu`
repository, and the root and `research/` reorganised to match. No tegu code or hardware
facts were copied. Moved only, except 24 empty session folders removed. Stopped `loopapi`,
disabled the campaign state and deleted the old scheduled tasks. Boot through `tools/bootios`; it sets persistent
`fastboot oem force-fastboot on` and does not turn it off, so tell the user first.

Known leftovers, none used by the build chain: old October scripts and dated docs still
name old paths; some old git worktrees have stale `.git` pointers (fix with
`git worktree repair` before `git gc`); `tools/check_v3_integration.py` fails because its
fixture no longer matches `shim.c`.
Tool tests pass.
