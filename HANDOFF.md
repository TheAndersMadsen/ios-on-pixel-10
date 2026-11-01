# Current — 2026-11-01: iOS 26 boots to the home screen on the phone

- **Physical, owner's eyes, `20261101-234344-phone-root-r1`, image `e49b93ca…`, kernel p2 `9ffbe445…`, root r3 `205cb0e2…`, `rd=md0 blazer_ufs_mountroot=1`, read-only, `varfs=1`, one CPU, no GPU: Apple logo about 3.5 min after the boot started at 23:43:44; owner reported the home screen at 23:54:43 CET at the latest (about 11 min). Log capture comes after the boot ends. Touch is off in this boot, so it isn't interactive yet.**

- Same boot, capture: ended at its own `blazer_deadline=1800`, `classify_reset` 10 of 10 PASS, no timer. 493,098 reads, 93.9 s UFS busy, `SWEET FB: display on`, no display off seen, probe fills 8684-8759 us, 0 underruns, SoC 41 C after reset, battery 89%, thermal breadcrumb 0, about 133 nits (`research/ios26-fleet/handoffs/bright.md`). Ring wrapped: 1.89 MB of log lost.
- Owner's decisions, 2026-11-02 00:13: battery SPMI reads yes; kernel writes to free blocks in `userdata_exp.ai` for a persistent `/var` yes, build and run; Wi-Fi firmware and GPL PHY table in local boot images yes.
- Next boots: `phone-touch-r2` (p4, touch, brightness cap), `clk-probe-r1`, `speed-probe-r3`, then p5. Plan and order: `research/ios26-fleet/PLAN.md`.

- **Physical, owner, `phone-touch-r2` (kernel p4, `blazer_touch=1`, brightness cap), 00:33:17: touch works on iOS 26 on the phone, very slow.** Picture still 1125x2436 with bars.

## Earlier today: XNU 12377 boots on the phone

- Physical, attempt `20261101-215924-first-boot-r1`, image `169a5b85…`, kernel `89489d52…` (tegu series, blazer layer). Compact HFS root `3cd4dcb5…` in md0, no md1, no display, no touch, `cpus=1`. Same nonce shim to XNU, entry 6.6 ms after handoff.
- Observed, in order: `EARLY 1`..`20`, Darwin 25.5.0, 16 KiB, 4 GiB at `0xa00000000`, `hfs: mounted iOSRoot`, UFS takeover with SMMU GBPA `2e1f`, `blazer-ufs-test: done, 0 errors`, `exec launchd`, `EXECOK6` first userspace SVC. Then `initproc failed to start`, namespace 2 subcode 0xb, the same as QEMU on this iOS 16 root; PSCI reset path ran, park 82 s, `0xbab9`.
- This is not iOS 26 and has no UI. It's the old compact root on the new kernel. The panic is expected from that root; its cause isn't established (no user PC).
- `tools/boot-summary.py` misreads this kernel: its "region says" text is stale residue. Read panics with `tools/read-ramdump.py --dump-base 0x95200000 --mach <unstripped>`. `research/ui-integrate-r1/all_decode.py` doesn't fit bootchain's manifest (no `features`).
- Physical, `20261101-220659-second-boot-r1`, image `c776b80d…`, kernel `72624577…`: the kernel took over the DPU from the shim and scanned out at full size. `tensor-dpu: attached` 1280x2856, first probe (black) fill 8893 us, 1 kick, 1 done, underrun 0, frame 10083 us. launchd's panic on the compact root reset the phone after that first probe, so the six-colour sequence wasn't seen. Next: hold pid 1 until the probe finishes.
- Physical, `20261101-221612-colour-r1`, image `24ee2462…`, kernel `252b3cbe…`: six full-screen colours scanned out by the kernel; 6 kicks, 6 dones, underrun 0, frames 8.1-9.3 ms, fills 8.7-8.8 ms for every colour (about 2.4 ns per pixel), pid 1 released after 4324 ms. Glass not yet reported by the owner.
- Physical, `20261101-221852-ssi-probe-r4b`, image `8891e264…`: touch chip powered and identified: rails AVDD 3.3 V and VDD 1.8 V on, read back, `IDENTIFIED`, part `S3916TGA1A0`, TouchComm proto 1, mode 1, build 4542708, rails off at end, 0 faults. Reports not enabled. Earlier `20261101-221308-ssi-probe-r4` stopped itself on a full record before rails. Next: r5, raw reports.
- **QEMU go, not the phone:** `research/ios26-qemu-r1/runs/go-5`: iOS 26.6.2 drew a lock screen with no GPU by 437 s under TCG, 1 vCPU, kernel `1694947e…`, light root plus `persona.kb` and `CAEnableMedina=false`, `rd=md0`. backboardd swapped 1125x2436 BGRA 17 times, 0 panics in 684 s. Frame goes black after about 467 s, unexplained. Not shown: phone root, `rd=ufsroot0`, unlock, frame rate, anything on Tensor. Next: `kernel.ios26-c1` `ef94ff4a…` on the phone route in QEMU, `ios26-phone-r2`, then the owner's approval to write.
- Owner's approval, 2026-11-01: **one** write of the verified iOS 26 phone root to `userdata_exp.ai`, once it reaches the lock screen in QEMU through the phone's own route. Not spent. A second write needs new approval. Owner wasn't watching the colour test, so glass is unconfirmed; rerun when the owner can watch.
- Physical, `20261101-224823-ssi-probe-r5`, image `647a5451…`: touch reports work. `TOUCHES_SEEN`, 773 reports, 0 bad, attention toggling, rails off, 0 faults, owner touching. Coordinates decode out of range (report layout wrong, not hardware); touch agent fixing from this capture.
- Owner's decision, 2026-11-01 23:30, after being told `userdata_exp.ai` is a second device of Android's `/data` with no backup (`research/ios26-fleet/handoffs/android-partition.md`): write once the gate passes, Android risk accepted. Not spent yet.
- **The one approved write is spent:** 2026-11-01 23:36-23:39, `fastboot flash userdata_exp.ai research/ios26-flash-r1/out/ios26-phone-r3-c.simg` (`44388c62…`, expands to r3 `205cb0e2…`): 32 pieces, 64 OKAY, rc=0, 205.9 s, log `research/ufs-stage-r3-flash.log`. **Whole-image check PASS, physical, `20261101-233933-fullcheck-r3b-after`, image `d6d6164c…`: 128 of 128 spans equal r3, done line, 139 s, 20 samples PASS, GPT row correct.** A second write needs new approval. Gate: `research/ios26-blazer-r1/runs/gate-p2-r3` (QEMU): home at 713 s, kernel p2 `9ffbe445…`, `rd=md0 blazer_ufs_mountroot=1`, no RAMDisk, read-only.
- Physical, `20261101-232934-phone-preflight-r1`, image `938461aa…`: p2 with the final phone line, ADT and no RAMDisk: `blazer-root: md0, rooting on ufsroot0`, UFS attach, `cannot mount ufsroot0` on iOS 16 as expected, reset, park.
- Physical, `20261101-233231-soak-p2-r1`, image `c3c903db…`: p2 + passes patch panicked at 82 s, before root: `cpu_common.c:634` assert in `cpu_signal_handler_internal`, flags 0. Cause not established; stale SGI is a guess. No watchdog result.
- One combined kernel patch: `research/ios26-integrate-r1/combined/ios26-p2-all-in-one.patch` `dd1b16ac…`, pristine xnu-12377.121.6 to kernel `ios26-p2`'s tree `7bfe7df9…`, verified by applying. Outside git: contains unlicensed tegu code.
- Merged bootchain's tested patches into `shim/` and `tools/`: 12377 boot contract, D421AP ADT, payload.

## 2026-11-01: moved to iOS 26

- The owner dropped iOS 16. Branch `ios26` is the working line; `ios16` and tag `ios16-final` hold the frozen line, indexed by `IOS16.md` there. `main` stays at `78d0126`, the shared base. `research/` isn't in git and stays on disk.
- iOS 26 has not been built or booted here. Host checks: shim, stage and route tests pass, tool tests pass, `tgl_dcs.o` compiled for ARM64 with rung 3. The combined shim has not been built into an image or booted.
- Latest physical result: RAM scanout on the panel, `20261101-211212-display-frame-r1d`, below.
- Tegu `d807098` (2026-11-01): its owner reports a buggy but working iOS 26 UI on the 9a, using a Mali Metal driver. We can't run that driver. Owner told us to base on tegu's series, overriding `research/ios26-route-r1/PLAN.md`'s own-tree port; the plan's stages and stop conditions otherwise hold.
- Fleet order, roster, sharing rules and current status: `research/ios26-fleet/STATUS.md`, `PLAN.md`, `ROSTER.md` (not in git). Running: kernel, root, blazer, bootchain, touch, dada, QEMU, scout. Display patch finished; compiles, not linked.
- Tegu-based XNU 12377 **links** on this Mac: `0661fcb3…`, TEGU config, never booted (`research/ios26-fleet/handoffs/kernel-base.md`).
- Tegu's log records the iOS interface on its phone before its Metal driver: no-GPU state inferred, not on our hardware (`research/ios26-root-r1/FINDINGS.md`). Findings: `research/tegu-branches-r1/FINDINGS.md`, `research/patch-scout-chips-r1/FINDINGS.md`.

## 2026-11-01: native frames on the panel; SpringBoard runs; iOS not yet on the panel

- Physical, attempt `20261101-210249-display-frame-r1c`, image `0b668164…`, capture `c78f5a31…`. The owner saw the screen flash white (order not reported). Panel OPR per slot 0, 2028, 0, 0, 2028, 2028 for black, white, black, black, white, white. Verdict `PANEL_REPORTS_PIXELS`.
- Frame-done seen, TE seen, panel error count 0, no reset. DPU test pattern through DSC, command mode kick, no RAM fetch.
- Caveats: UNDERRUN seen, CRC registers read 0, so the CRC proof didn't work. The test pattern doesn't use FE0, so RAM scanout is unproved. PPS write effect unknown: ABL's PPS already matched.
- Next: rung 3, RAM scanout, then the kernel backend.

### 2026-11-01: ssi-probe-r3, touch bus and PMIC queue work

Physical, `20261101-215211-ssi-probe-r3`, image `7fad8732…`. `PMIC_STATE_READ`, final OK, 0 faults. SSI FIFO depth 256; SRL loopback 4 of 4 bytes matched. Stock PMIC queue initialised and acked; GETs replied: VDD 0, AVDD 0, AVDD selector 210, reset dir 0, val 0. So touch rails are off. No rail, pad or controller write. Next: r4, rails, reset, pads, IDENTIFY.

### 2026-11-01: ssi-probe-r2, touch bus answers

Physical, `20261101-213902-ssi-probe-r2`, image `b4121617…`. `SSI_ID_READ`, final OK, 0 faults. No SSI read before the votes; LSIO_N `pd_on`, cfg and SPI clock PREPARE, CLI `4,0,0` and reset release all replied. SSI VERSION `0x3430332a` ("403*"), IDR `0xffffffff`, CTRLR0 `0x1070000`. Reset class afterwards is the image's own software reset (`0xbab9`). Inferred from three boots: a guarded read of the unvoted SSI leaves an error that kills the phone at the next state change; `pd_on` itself is safe, and so is status read `0x5272008`. Hard rule: no SSI access before votes reply. Controller not touched yet. Next: FIFO and config, rails, identify.

### 2026-11-01: ssi-probe, second touch bus probe

Physical, `20261101-213642-ssi-probe`, image `d8d6cf4e…`. Same reset `0xc00e` at the same `pd_on` frame, with completion from the message window and 0 reads of `0x5272008`. Observed: that status read isn't the cause; window completion works for read frames. This image still ran the guarded SSI read first, so the fault remains a candidate. Next: same with no SSI read before the votes.

Other ports found (`research/patch-scout-ports-r1/FINDINGS.md`): `superboyyy/hakios-arm64e-dada`, APSL, 12377, our lineage, and `nhansp/ios-husky`, Tensor G3, no license, both record iOS 26 on CPU rendering. Author records, unverified.

Decision: tegu's series is the kernel base. Dada's kernel links (`fb9baee0…`) but has 4 KiB pages, no HFS and needs a PAC-signing loader; it stays a parts source. QEMU, not the phone: tegu-based kernel `e4f43487…` reaches launchd exec on the old iOS 16 root with no kernel panic before it (`research/ios26-fleet/handoffs/qemu.md`).

### 2026-11-01: ssi-id-r1, touch bus probe

Physical, `20261101-213232-ssi-id-r1`, image `85a0bc31…`, no XNU, no chip traffic. SSI read at `0xdb33058` faulted and the guard caught it. Read frames LPB, SPI rate and cfg rate replied. Then a hardware reset during the first state-changing frame, LSIO_N `pd_on` `0x01000401`: `NO_END`, `0xc00e`, Fatal Error HW, last access status read `0x5272008`. That status read worked through the earlier frames. Guess, untested: the frame resets the phone, or the guarded SSI fault leaves a RAS error that goes fatal; touch-r1 had the same order. Next: same probe with no SSI read before the votes.

### 2026-11-01: display-frame-r1d

Physical, `20261101-211212-display-frame-r1d`, image `34183971…`. RAM scanout reached the panel through FE0 layer 0: `PANEL_REPORTS_PIXELS`, `fe0_fetched`, `ram_scanout_reached_panel`. Only the layer address changed: OPR 0, 423, 423, 0, 0, 0 as the nonce said, above the expected 380. Underrun on the first kick only, later kicks 0. DPU SMMU `CR0` 0, not enabled, GBPA 0. CRC registers still read 0. Colours and geometry on glass unconfirmed: nothing filmed, owner has not reported. `all-r1` and `all-r1-safe` built, not booted, and won't be: the owner dropped iOS 16.

### 2026-11-01: display and touch probes

- r1a, `20261101-205339-display-frame-r1a`: display domain powered, DPU read, chip `0x9400`, no reset.
- r1b, `20261101-205525-display-frame-r1b`: DPU writes survived, TE seen; stopped by its own PPS check at byte 89, so no frame. Owner saw only bootloader screens.
- touch-r1, `20261101-205756-touch-r1`, capture `764854df…`: AoC on, no control block at the probed address, pads on GPIO. SSI read faulted; last access PMIC mailbox `0x5272008`, then hardware reset `0xc00e`. Touch controller not reached.

### 2026-11-01: ufs-speed-r1, HS gear 4 on the phone

- Physical, attempt `20261101-204627-ufs-speed-r1`, image `3efffef6…`, capture `6b08424f…`: PWM-G1 (mode 0x55) to HS gear 4, 2 lanes (mode 0x11), change rc 0 in 3.7 ms, no firmware or calibration sent. 12 of 12 blocks read equal at both speeds, 0 UIC errors.
- XNU then read the root: 10295 reads, busy 1340 ms, 0.13 ms per block, 30.05 MiB/s (from 7.41 ms, 0.53 MiB/s). Ended by the 300 s deadline panic, as designed.
- This image still had the 6-job md1. `shim/` doesn't have the gate yet; the shim copy is in `research/ufs-speed-r1`.

### 2026-11-01: phone-r1 (attempt ufs-ui-r1), first UI processes on the phone

- Physical, attempt `20261101-203354-ufs-ui-r1`, image `8aa00893…`, kernel `b4a0efad…`, capture `7dd5f456…`, md1 `de340c95`, `/product` in the ADT. No storage write.
- Observed: launchd main; SpringBoard (pid 8) and backboardd (pid 13) ran; backboardd opened `MiniIOMobileFramebuffer`, created a 1125x2436 BGRA surface and made 3 swaps (first at 1083 s log time, about 200 ms each in the driver).
  Also seen: runningboardd, lsd, configd, powerd, usermanagerd, mediaserverd, others. Search for panic, usertrap, userabort, exit reason: 0 hits. No BoundingPath abort line.
- It ended because the owner held the power button after about 11 minutes, thinking it was stuck (owner confirmed; capture: 0xccca, `manual-longpress`). Reads were still rising: 75280 at t=590 s, 562.9 s busy, last line 1155.9 s. Free memory 3316 MB.
- Not shown: pixels on the panel, whether SpringBoard reached its first screen, how long it stays up. systrace was off, so launchd's text is not in this log.
- Frames only reach RAM: the panel path is `research/display-frame-r1`, then the `research/xnu-fb-r1` backend. Storage takes 95% of the time: `research/ufs-speed-r1`.
- For the owner: the screen stays dark on these boots, so wait up to the deadline.

### 2026-11-01: ufs-root-r2, launchd from the full root on the phone

- Physical, attempt `20261101-201914-ufs-root-r2`, image `1a78080e…`, kernel `b4a0efad…`, capture `4bda1ae3…`, nonce matched, no storage write.
  Decoded: `research/ufs-root-r1/run/root/decoded-r2.json`.
- Observed, every decoder stage: 16 KiB pages, 4 GiB at `0xa00000000`, XNU took over UFS with DMA above 4 GiB, APFS `System` mounted, md1, init, launchd.ios, cache mapped,
  `hello` at 225.6 s, xpcproxy. Reader: `launchd main=yes`, first time. 0 usertraps, 0 refusals. 10287 reads, 40.2 MiB, 7.4 ms per block, about 0.5 MiB/s.
- The end is our own timer: `blazer-root: deadline 300 s` panic. Not a crash. Reads stop at about the same count as QEMU; launchd is on its Restore branch, so this is not the normal UI boot.
- Attempts `20261101-201242-ufs-root-r1` and `20261101-201517-ufs-root-r1b` were refused with `USB transfer active at XNU handoff`; their panic text is residue of an earlier boot. Admission's hash blocks USB
  service, so a host read was pending. Fix in `shim/loader.c`: finish that transfer, bounded to 1 s, then check. Works in r2.
- Not shown: normal launchd branch, daemons healthy, UI, touch, and repeat of this boot. Storage reads look slow: link is unoptimised.
- Next: launchd to SpringBoard (`research/fullroot-ui-qemu-r1`), faster UFS link, scanout (`research/display-frame-r1`, `research/xnu-fb-r1`).

### 2026-11-01: page16k-r1, 16 KiB pages and 4 GiB on the phone

- Physical, attempt `20261101-200840-page16k-r1`, image `62a4e41e…`, kernel `b4a0efad…`, capture `92e3df04…`, compact root, no UFS: 254874 free + 7270 wired =
  262144 16 KiB pages at `0xa00000000`. No shift-14 signature refusal, `EXECOK6`, same fault at pc `0x3009c7b48`, same `initproc` panic.
- Not shown: cache and TLB behaviour under load (one process, one CPU), firmware's use of the top 3 GiB (not filled), the shared cache, UFS at this page size.
- Next: full root from UFS on this kernel (`research/ufs-root-r1`).

### 2026-11-01: display-dcs-r1 and r2, first native panel commands

- Physical, r2 attempt `20261101-195242-display-dcs-r2`, image `c88b7ce7…`, capture `e97bbd3a…`: DSI registers read (core `0x30313030`), PHY up,
  panel replied in LP mode. Power mode `0x9f` before and after (booster, awake, normal, display on). Full ID DA,DB,DC,A1 = `0a a0 a1 42`, matching
  stock id `0x42a1a00a` little-endian. Err count 0. All flash commands sent: 1000, 250, 750, 750, 750, 250, 750 ms. No reset, no fault.
- Not known: whether the panel visibly changed; no film was taken. All-pixels-on `0x23` is in no source. This is not a frame.
- r1 attempt `20261101-194928-display-dcs-r1` stopped at the ID check, because the expected byte order was wrong. Fixed in r2.
- Next for display: DPU test pattern or framebuffer path, per `research/ui-touch-r1/FINDINGS.md`.

### 2026-11-01: ufs-shim-r1 and ufs-xnu-r1

- Physical, `shim/` route (no pass A), attempt `20261101-192655-ufs-shim-r1`, image `6307a6fb…`, capture `1637a007…`: link, commands and 21 READs.
- Physical, attempt `20261101-192828-ufs-xnu-r1`, image `842365a8…`, kernel `d3a4d6c7…`, capture `55f2e02e…`: XNU took over from the shim, found
  `userdata_exp.ai` (8192 MiB, read only), read 3 raw and 12 partition blocks with CRCs equal to the shim's and staging.img, a 16-block multi-read result 0.
  `blazer-ufs-test: done, 0 errors`, HCS 0xf, GBPA `0x2e1f` at start and end. Decoded: `research/ufs-integrate-r1/run/xnu-r1/decoded.json`.
- Same boot then went through the compact root to the known `launchd` panic. Parent reran route test: 87 checks, 20/20 mutants.
- Observed AHIT 0. Not shown: APFS mounted over UFS, `launchd` from the full root, 16 KiB on the phone.
- `shim/build.sh` needs `research/ufs-read-r2/run/decoded.json` and `research/ufs-link-r2/decoded.json`, so a fresh clone can't run its tests.
- Next: full root from UFS (`research/ufs-root-r1`), first panel test (`research/display-dcs-r1`); agents running.

### 2026-11-01: ufs-stage-r1 and ufs-read-r3

- User approved one write, 2026-11-01: `fastboot flash userdata_exp.ai research/ufs-stage-r1/staging.simg`, 19:22-19:23 CET, rc 0.
  Only that partition; previous content overwritten. Slot b unchanged. Log: `research/ufs-stage-r1/flash.log`. This approval is spent.
- `staging.simg` is new: expands to the pinned region `b4b25792…`, independently checked before flashing.
- Found: `ufs-staging/staging-sparse.img` from Oct 28 has a non-standard header. Guess: this may be why that write isn't there. Do not use it.
- Physical readback, attempt `20261101-192343-ufs-read-r3`, image `5920fffc…`, capture `dbb42dd4…`: 12 of 12 sampled blocks match
  `staging.img`, NXSB at offset 32, UFSSTG1 manifest and seal match. Samples only: 12 of 604,672 blocks, not the whole image.
- Next: read the root through XNU (`research/ufs-integrate-r1`, agent running). Then 16 KiB pages and 4 GiB window on the phone.

### 2026-11-01: ufs-read-r1 and r2, first storage reads

- Physical, read-only. r1 `20261101-184625-ufs-read-r1` capture `07d1304c…`; r2 `20261101-185202-ufs-read-r2` capture `39d4de77…`.
  Decoded: `research/ufs-read-r2/run/decoded.json`. No write command sent.
- Observed: READ CAPACITY and READ(10) on 4 LUs, 4096-byte blocks, GPT headers and entries CRC-valid. LU0 max LBA 31147007.
  `userdata_exp.ai`: LU0, LBA 2500838..4597989, 8 GiB. Canary test: data landed after CIVAC. GBPA stayed `0x2e1f` at every gate.
- Observed: 11 of 12 sampled partition blocks differ from `ufs-staging/staging.img`; the 1 match is an all-zero block.
  Blocks repeat between boots. No NXSB and no UFSSTG1 manifest. Inference: the Oct 28 image was overwritten. Cause unknown; the
  phone has run Android since, and the new content looks like zeros plus encrypted data. Do not assume the partition is unused.
- ufs-read-r2's tests have 6 stale count expectations (more blocks read by design); mutants 97/97 caught. Not updated.
- Phone: parked, slot b, force-fastboot on.
- Next, not blocked: fold link, post-link and read into `shim/`, then XNU takeover (`research/ufs-integrate-r1`, agent running).

### 2026-11-01: ufs-postlink-r2, first device commands

- Physical, attempt `20261101-182305-ufs-postlink-r2`, image `49e5c6a1…`, capture `4232121c…`, nonce matched.
  Decoded: `research/ufs-postlink-r2/run/decoded.json`. No READ, no write command, no user data.
- Observed: NOP IN; fDeviceInit set and cleared in 4.3 ms; TUR gave UNIT ATTENTION (6/29/00, response=1), then GOOD;
  REPORT LUNS to W-LUN 0x81 returned 4 LUs (0,1,2,3), 40 bytes landed by DMA. HCS 0xf, no UIC errors, lists stopped.
- Link: LINK result 0 after device-on on 3 of 3 boots (ufs-link-r2, ufs-postlink-r1, r2), 9.3-9.9 ms.
- r1 (`20261101-181939`) stopped at TUR: the phone sends response=1 with CHECK CONDITION, and the engine treated it as
  fatal. Linux uses SCSI status only (`ufshcd.c:5378-5384`). Fixed in `research/ufs-postlink-r2/src/ufspl.c`.
- Not shown: READ, LU sizes, which LU has `userdata_exp.ai`, XNU taking over. Same `launchd` panic later in boot.
- Fixes live in `research/ufs-postlink-r2/run/scope`, not yet in `shim/`.
- Next: read-only READ CAPACITY and READ(10) to find the GPT (`research/ufs-read-r1`, agent running).

### 2026-11-01: high-window-r1, 1 GiB at `0xa00000000`

- Physical: attempt `20261101-184019-high-window-r1` (image `a1838c58…`, capture `00802647…`): 233393 free + 28751 wired =
  262144 pages, shift 12, shift-14 signature refusal still prints, `EXECOK6`, same `initproc` panic. Compact root, no UFS.
- Physical: attempt `20261101-184200-high-window-fill-r1` (image `0e6cb769…`, capture `b14c5313…`): same, plus every free page
  filled with `0x5a5aa5a5`, no fault. Writes silently ignored or later overwrites are not excluded.
- Parent lifted N552's HOLD: its gate could never pass, and this test writes RAM only.
- Not shown: above `0xa40000000`, shift 14 on real hardware, signatures accepted on the phone.

### 2026-11-01: ufs-link-r2, LINK result 0

- Physical, one boot, attempt `20261101-181514-ufs-link-r2`, image `df5d7e3d…`, capture `3688d5bb…`, nonce matched.
  Decoded: `research/ufs-link-r2/decoded.json`. No storage access, doorbell, DMA or READ.
- Pass A, no device-on: LINK result 1 on 4 of 4, about 50 ms each, HCS 0x8, DP=0. TX FSM 1→2.
- Pass B, device-on (reset low, power, refclk SMC, reset high, aux SMC, all `smc_a0`=0): pads read high, RX FSM 7
  after HCE, LINK result 0 on the first try in 9.3 ms, **HCS=0xf (DP=1, UTRLRDY, UTMRLRDY, UCRDY)**, FSMs after link
  [0,2,1,2,1], no fault, ISR 0.
- Observation: device-on is what made the difference. Inference: the device was unpowered or held in reset, and
  the "local refusal" alternative is refuted for this route. Rail voltage still unmeasured.
- Observed: the refclk pad's TX write doesn't stick (reads 0 after writing OE), yet link came up. Cause unknown.
- One boot only: not yet shown repeatable. `is_ulss`=0 in the record because IS was cleared by the sequence; DP=1 and
  result 0 are the evidence. Not READ10, not working UFS.
- ufs-link-r1 (`20261101-181009-ufs-link-r1`) stopped at that pad's strict readback, so device-on never ran.
- Boot continued to XNU, root mount, launchd exec, then the same panic. Phone parked, slot b, force-fastboot on.
- Next: post-link on this route: NOP OUT, fDeviceInit, TUR, REPORT LUNS (`research/ufs-postlink-r1`, agent running).

### 2026-11-01: ufs-observe-r2 read power, pads and SMMU on the phone

- Physical, attempt `20261101-174259-ufs-observe-r2b`, image `a7fd3cbd…`, capture `261fa855…`,
  fresh stamp nonce. All 22 + 13 read-only reads committed, rc 0, ISR 0, in 33 ms. Values:
  `research/ufs-observe-r2/result.json`. No storage or register writes; no UFS link attempted.
- Observed: PSM_HSIOS, PSM_UFS_HC and PSM_UFS_PHY all ON (0x10). PWR_CTRL `0x23c4c24` matches warm
  mode 2. HCLKDIV 0x190, TOP+0x200 0, HCS 0x108 (DP=0, same as r1). Last UIC command was
  HIBERNATE_ENTER, result 0. Pad 8 (`AP2PMIC_UFS_EN`) reads low. Pad 0 (reset) reads low.
- Observed, `inf_smmu`: CR0=0, CR0ACK=0, GERROR=0, STRTAB_BASE=0, GBPA=0x2e1f with ABORT clear.
  First read of this SMMU. By my reading of SMMUv3 fields, it is disabled and bypassing, not
  aborting. Confirm against the Arm spec before relying on it for DMA.
- Guess, not measured: pad 8 low means the device has no power. No rail voltage was read. Refclk
  dout/oe fields from the decoder are undefined (known defect); use the raw words.
- Link preconditions hold, so ufs-link-r1 may run. It will be the first boot that writes UFS
  registers. Next: build it from the host code, with both LINKs in one boot.
- Same boot continued to XNU, root mount, launchd exec and dyld, then panic. `launchd` main no.
- Failed first boot, `20261101-174018-ufs-observe-r2`: refused with -11 before any UFS read, because
  I changed nonce/epoch without updating `n742_generated_binding.h`. Fixed, no phone effect. Phone
  parks by itself within about 2 minutes; `tools/bootios` now waits for that and captures.
- Phone: parked in fastboot, slot b, force-fastboot on.

### 2026-11-01: first UFS read, link plan reviewed, work now run the tegu way

- Parent alone owns USB. No helpers running.
- Last UFS boot, ufs-observe-r1: eight read-only reads at `0x3c400000`, no writes. HCE=0x3,
  HCS=0x108 (UCRDY=1, **DP=0**), doorbells 0, run-stop 1/1. Controller enabled, device not
  present. Values: `research/laguna-usb-fix/native-fleet-20261031/N900-root-current-ufs-observation/CURRENT-UFS-OBSERVATION.json`.
- Last native boot: I-cache transition and 16 KiB baseline captured, still compact root and
  panic. `launchd` main not reached.
- ABL fully initializes UFS, then logs `[UFS] shutdown complete` about 30 s before our reads.
  The old "device dead at DME level" conclusion was a misread of the status column; corrected
  in the ledger.
- Hypothesis, not proven: the shim never runs the stock pre-link sequence after ABL's shutdown.
  Sequence from the shipped `ufs.ko` (Linux 6.12.81):
  1. reset=0, power=1 (pad 8), wait 8 ms, refclk on, wait ~300 µs, reset=1 (pad 0)
  2. cycle HCE 1→0→1, keeping crypto bit 1
  3. HCLKDIV=0xc8, TOP+0x200=0x101
  4. DME 0x8118=0, DME 0xd085=1
  5. DME_LINKSTARTUP, check IS.ULSS and HCS.DP
  Expected: DP=1 and ULSS. Refuted if LINK still gives result 1 with pads verified high and
  HCE cycled.
- Review of this plan found nothing unsafe, but "device unpowered" is not supported. Strongest
  alternative: LINK result 1 in ~80 µs is a local UIC refusal, independent of device state. So
  ufs-link-r1 runs both LINKs in one boot, with per-LINK duration. Review:
  `research/laguna-usb-fix/native-fleet-20261031/N916-verify-o2-w1/VERDICTS.json`.
- Next: ufs-observe-r2. Read-only: power domains, pads, PWR_CTRL, HCS, then `inf_smmu`. Four
  review fixes first: record ISR_EL1.A after the SMMU reads, a checkpoint after each pad group,
  twelve SMMU words instead of three, and read the 8-byte STRTAB_BASE as two 32-bit words. Then
  ufs-link-r1 only if both UFS domains and HSIOS are ON and PWR_CTRL shows warm mode 2.
- Host-only and unapplied: ufs-observe, ufs-link and post-link code link but have not run:
  `research/laguna-usb-fix/native-fleet-20261031/N914-integration-next-candidate/`. READ(10) stays blocked until `inf_smmu`
  (`0x35100000`, SID 0x8100) is measured; treat UFS as non-coherent.
- Full root gaps: 23 (4 delivered, 8 partial, 10 missing, 1 unknown). First stops are the
  shim-to-XNU handoff and `rd=ufsroot0` with libignition:
  `research/laguna-usb-fix/native-fleet-20261031/N915-ios-from-fullroot/`. No physical window above 1 GiB yet.
- Decisions (user delegated 2026-11-01): parent runs temporary boots through `tools/bootios`
  and leaves the phone in fastboot with force-fastboot on. Read-only LUN discovery approved.
  Kodiak's platform file stays unfetched. No GitHub remote until `xnu/patches/` licensing is
  fixed. Storage writes and destructive steps still need the user's confirmation.

Previous handover: `research/legacy-root-20261101/handover.md`.
