# Home budget: power-on to Home, and what keeps the 5-core profile from it (2026-11-03, host analysis only)

No phone, QEMU or root-index action. Inputs: eight existing physical attempts in
`research/laguna-usb-fix/attempts/` (the phone ramdumps), decoded on m1box with
`tools/read-ramdump.py --logs --tail 2000000`. `a7-ios-system-r2` was fetched from the Mac
(`hackios-fetch`, 5.3 MB). Per-boot extracts: `data/<attempt>.json`, made by `timeline.py` (exec/spawn/exit/throttle,
`blazer-root` watch series, `HK TOP`). `kaxis.py` prints any regex on the kernel axis.

**Kernel axis.** Each line gets the time of the closest *preceding* `blazer-root: watch|stage t` tick, i.e. seconds
since the root watch started (resolution 10 s, an upper bound for the event). Watch start is XNU entry +0.35-0.5 s
on the p29/p32/rootview kernels (HK TOP `t` = cntvct seconds vs XNU entry stamp) and about +2.5 s on p2 (launchd
`hello` at calendar 99.6 s = cntvct, XNU entry 92.46 s). launchd's own log lines lag badly on one CPU (the
"spawned SpringBoard" line of the Home boot is emitted at axis ~530 s; the kernel's `exec SpringBoard` is at 4.6 s),
so kernel `exec`, `usertrap`, `SWEET FB` and `blazer-root` lines are the timing source. launchd timestamps are used only
for durations ("ran for N ms") and throttle amounts.

Labels: **M** = measured in the named log; **O** = owner's observation; **I** = inference.

## 1. Headline

1. **The 5-core profile already reaches Home in about 50 s after root, about 90 s from power-on, when backboardd
   survives** (M+O): `20261102-095609-phone-p29-live-r1`, 5 A725, deadline 300. Owner saw Home and Settings. First
   frame (`SWEET FB: display on`, swap 1) at axis 40 s, Spotlight exec 50 s, `HK TOP` frames+30 in the window that
   ends at 50 s. Two other 5-core p29 boots repeat this to the 10 s tick (display on at 40.0 s, Spotlight 40 s,
   Preferences 60/120 s).
2. **The current p32/rootview line never presents a frame, on 5 cores or 1, at any deadline** (M). This holds for p32
   (5 CPU, 300 s), A7 r1 (5 CPU, 300 s) and **A7 r2 (1 CPU, 1800 s, ended by the owner's long press at ~10 min)**. All
   three have 0 `SWEET FB: swap` lines, 0 `display on` and `HK PRESENT queued=0`, and backboardd SIGSEGVs at
   CoreBrightness unslid 0x1e2746924 every ~30 s (7, 7 and 9 times). **The 300 s deadline is not why A7 r1 was black.**
   r2 removed the deadline and stayed black, which refutes A7.md's "the deadline is the black screen".
3. The one-CPU Home boot's 10 min is a CPU problem, not a UFS one (M+I). UFS was busy for 54 s of the first 600 s;
   the p2 kernel issues one 4 KiB block per command, has no governor and 4 GiB. The 5-core boots do the same
   launch work, 62-63 CPU-seconds in the first window, on 2-4 busy cores.

## 2. Boots analysed

| Attempt | Kernel | CPUs | Deadline | Root | `hk_bright` / AppleARMBacklight | End | Frames |
|---|---|---|---|---|---|---|---|
| `20261101-234344-phone-root-r1` (Home, O) | p2 | 1 | 1800 | userdata_exp.ai | no | deadline 1800 s | display on 70 s; Home burst 590-610 s |
| `20261103-144712-a7-ios-system-r2` | rootview | 1 | 1800 | ios_system | yes (`hk_bright=140`) | owner long press, park 619 s | **0** |
| `20261103-135606-a7-ios-system-r1` | rootview | 5 | 300 | ios_system | yes | deadline 300 s | **0** |
| `20261102-132258-phone-p32-combined-ui-r1` | p32 | 5 | 300 | userdata_exp.ai | yes | deadline 300 s | **0** (journal: owner "Home + Settings", unresolved) |
| `20261102-095609-phone-p29-live-r1` (Home, O) | p29 | 5 | 300 | userdata_exp.ai | no | deadline 300 s | display on 40 s |
| `20261102-111800-sampler-off-p29-r1` | p29 | 5 | 300 | userdata_exp.ai | no | deadline 300 s | display on 40 s, frames+162 at t=402 |
| `20261102-101134-phone-p29-profile-r1` | p29 | 5 | 300 | userdata_exp.ai | no | deadline 300 s | display on 40 s |

p29-live's msgbuf wrapped (1.53 MB written, 1 MiB kept): its first ~25 s are lost, so its early rows come from the
two other p29 boots. The Home boot's msgbuf also wrapped. Its first ~1370 s come from the persistent_ram console
zone, whose watch counters continue those of the msgbuf monotonically (472k to 476k reads).

## 3. Power-on to Home budget: best measured 5-core boot (p29 line)

| # | Phase | Axis / time | Duration | Evidence |
|---|---|---|---|---|
| 0 | Reset, ABL, fastboot, host `fastboot boot` (0.2-1.5 s transfer) up to shim entry | cntvct 0 to 13.5 s | **13.5 s** (25.8 s in r2) | M: shim `t0` of A7 r1 (13.47 s) and r2. Lowest seen; includes the fastboot path, not the chooser path |
| 1 | Shim: FDT parse, console init and paint | 0 to 4.42 s | 4.4 s | M: TSHIMST2 stamps, all 6 boots 4.41-4.56 s |
| 2 | Shim: USB console enumeration waits (`TGL_USB_WAIT_SECONDS=8` + 1) | | **9.0 s** | M: `usb-enum-wait` 8.0 s + 1.0 s in every boot |
| 3 | Shim: UFS ladder, post-link route (stage 0xe5), 0xd0 | 12.5 to 16.5 s | 4.0 s | M (stage 0xe5 alone 2.1 s) |
| 4 | Shim: payload admission steps 1-5 | 17.5 to 20.0 s | 2.5 s | M |
| 5 | Shim: `loader_boot` segment copy to entry | 20.0 to 26.4 s | **6.4 s** | M (`payload-admit` step 6 to `entry_pa`); I: MMU-off copy |
| | **Shim total** | | **26.2-26.4 s** (24.8 on p2) | M, 6 boots |
| 6 | XNU entry to root watch start | | 0.4 s | M |
| 7 | Root mount (takeover to overlay) | 0 to 0.13 s | 0.1 s | M: `stage t` lines |
| 8 | DPU probe holds pid 1 (`hk_fb_probe=1`) | 0.1 to 4.2 s | **4.1 s** | M: `tensor-dpu: pid 1 released after 4109 ms` |
| 9 | launchd main, ~100 daemons spawned (SpringBoard[5], backboardd[22], lsd, logd, cfprefsd ...) | 4.2 s | | M: launchd pids; kernel `exec` at 4.2-4.3 s |
| 10 | Launch storm, CPU-bound: 62-63 CPU-s (lsd 10.7, launchd 8.8, UserEventAgent 3.3, passd 1.6, SpringBoard 1.5 ...) | 4.2 to ~20-30 s | ~16-26 s | M: first `HK TOP` window, 3 boots |
| 11 | **backboardd polls `IOAcceleratorES` (~10/s, 0 found), then gives up** | 10 to 40 s | **30 s** | M: 318/302/314 `IOAcceleratorES -> 0 found` lines per boot, ticks 10-40 (Home boot 40-70) |
| 12 | First frame: `display on`, swap 1, PosterBoard/SpringBoard surfaces | 40 s | | M |
| 13 | SpringBoard renders Home (20-26 CPU-s), Spotlight exec | 40 to ~50 s | ~10 s | M: `HK TOP` window ending at 50 s: SpringBoard 25.6 s CPU, frames+27/30 |
| | **Home (O on p29-live)** | axis ~50 s | | |
| | **Power-on to Home** | **≈ 13.5 + 26.4 + 0.4 + 50 ≈ 90 s** | | M phases; Home time to ±10 s |

Same table for the **owner-confirmed one-CPU Home boot** (p2): shim 24.8 s; watch start XNU+2.5 s; pid1 4.6 s (DPU probe
4.3 s); SpringBoard exec 4.6 s, logd 10, backboardd/lsd/cfprefsd 20, iconservicesagent 50; IOAcceleratorES poll at 40-70 s;
**display on and swaps 1-2 at 70-90 s; swaps 3-8 at 590-610 s and Spotlight exec at 590 s = Home**. Wall: 23:43:44 +
1.5 + 24.8 + 2.5 + 590 ≈ 23:54:03, consistent with the owner's "at 23:54:43 at the latest" (O). The owner's "Apple logo
at about 3.5 min" does not match the first swap at axis 70 s (≈ 1.7 min wall); what was on the panel then is not logged.

## 4. Key daemons (kernel axis, s; `n` = exec count over the boot)

| Daemon | Home p2 1-CPU | r2 1-CPU | A7 r1 5-CPU | p32 5-CPU | p29 sampler 5-CPU |
|---|---|---|---|---|---|
| launchd exec / pid1 | 0.1 / 4.6 | 0.3 / 4.7 | 0.1 / 4.3 | 0.1 / 4.3 | 0.1 / 4.2 |
| SpringBoard | 4.6, n=1 | 4.7, n=5 | 4.3 (pid 5), n=4 | 4.3, n=5 | 4.2 (pid 5), n=1 |
| backboardd | 20.0, n=1 | 20.0, **n=9** | 4.3, **n=8** | 4.3, **n=8** | 4.2, n=1 |
| lsd | 20.0 | (launchd) | 4.3 | 4.3 | 4.2 |
| logd | 10.0 | 10.0 | 4.3 | 4.3 | 4.2 |
| PosterBoard | (not logged) | 200, n=2 | 10.0, n=4 | 10.0, n=5 | 10.0, n=1 |
| iconservicesagent | 50 | 50 | 10 | 10 | 4.2 |
| backboardd `backlight-control` match | 40 → 70 (0 found) | 30 → 60 | 10 → 40 (**AppleARMBacklight found**) | 10 → 40 (found) | 10 → 40 (none, 0 found) |
| backboardd SIGSEGV at CoreBrightness 0x1e2746924 | 0 | 9 (kernel `usertrap` first at 60, then ~every 30-70 s) | 7 (first at 40, ran 39.2 s, then ~30.7 s each) | 7 + 1 early SIGABRT | 0 |
| SpringBoard / PosterBoard exit(255) with each backboardd death | no | yes | yes (3/3) | yes (4/4) | no |
| First frame / Home | 70 / ~590 | none | none | none | 40 / ~40-50 |

## 5. UFS totals and I/O versus CPU

| Boot | Cmds | 4 KiB blocks (MB) | Busy | Blocks/cmd | µs/cmd | By first frame / Home | Share of wall |
|---|---|---|---|---|---|---|---|
| Home p2, 1 CPU, single-block | 493,098 | 493,098 (2,020) | 93.9 s / 1800 s | 1.0 | 190 | 57,852 cmds, 8.0 s busy by 30 s; **389,780 cmds, 1.6 GB, 54.4 s busy by 600 s (Home)** | 9 % of the first 600 s |
| r2, 1 CPU, multi 16 | 42,678 | 237,885 (974) | 11.6 s / 580 s | 5.6 | 271 | no frame | 3.8 % of 300 s |
| A7 r1, 5 CPU, multi 16 | 43,389 | 241,721 (990) | 7.3 s / 300 s | 5.6 | 167 | 7.1 s busy by 30 s | 24 % of the first 30 s, then ~0 |
| p32, 5 CPU | 43,394 | 241,759 (990) | 5.5 s | 5.6 | 126 | | |
| p29 sampler, 5 CPU | 52,775 | 302,979 (1,241) | 6.9 s | 5.7 | 130 | 5.4 s busy by 30 s; 1.24 GB by 90 s, then flat | 18 % of the first 30 s |

p29 `blazer-ufs-cost` (M): 52,779 commands, busy 6.87 s, device wait 5.45 s (min 26 µs, max 10.8 ms), spins 4.13 s,
sync 0.28 s. That is ≈ 180 MB/s while busy. Driver (source, `research/ios26-release-r1/work/xnu`
`bsd/dev/hakios.blazer_ufs.c`, `n892_xnu_strategy.inc`): one slot (queue depth 1), polled, synchronous inside
`ufs_strategy` under `blazer_ufs_lock`, at most `N892_MULTI_BLOCKS` = 16 blocks per command (`blazer_ufs_multi_blocks`
can raise it to 256), 300 µs spin with preemption off (`blazer_ufs_hold=1`).

CPU (`HK TOP cpu_ms` per 30 s window, M):

| Boot | Window 1 (launch) | Window 2 | Later windows | Reading |
|---|---|---|---|---|
| p29 sampler 5-CPU | 62.0 s CPU (lsd 10.7, launchd 8.8) | 46.0 s (SpringBoard 25.6) | 3-55 s, backboardd dominant (rendering) | launch is CPU-bound on 2-4 cores; then Home render |
| A7 r1 5-CPU | 63.2 s (same mix) | **2.8 s** | 0.5-2.4 s | idle: SpringBoard waits for a backboardd that keeps dying |
| r2 1-CPU | 25.7 s | 29.7 s | 28.8-29.1 s each until axis 330 s, then 0.7-6.8 s | one core 96-99 % busy for 330 s (launch storm, slower, plus 9 crash/respawn rounds) |
| Home p2 1-CPU | no HK TOP on p2 | | | I: CPU-bound. UFS busy is only 9 %; 1 core at 533 MHz (no `blazer_gov`), 4 GiB |

## 6. Respawn and throttle waits (launchd "Pushing respawn out by N seconds", M)

| Boot | Throttle events (sum of push-outs) | On the Home path? |
|---|---|---|
| Home p2 1-CPU | 199 (5,894 s): bluetoothd 51, PerfPowerServices 50, wifip2pd 41, fairplayd.H2 43, imagent 4, healthd 4, gamed, homed, axassetsd | No, but ~185 failed respawns each cost a dyld/launch on the only core (I) |
| r2 1-CPU, A7 r1, p32 | fairplayd.H2 30 (~297 s) + **backboardd 2-4 (60-193 s, growing 10 → 50 s)** | **Yes: backboardd**. Each death also takes SpringBoard and PosterBoard (exit 255) |
| p29 5-CPU | fairplayd.H2 30 (298 s) only | No; fairplayd runs ~60 ms each time |

## 7. One CPU versus five (same root, same kernel family)

| | 1 CPU | 5 CPU | Ratio |
|---|---|---|---|
| Launch work (first-window CPU) | r2: saturated 30 s windows to axis ~330 s | 62-63 CPU-s finished by axis ~20-30 s | ≈ 10× longer wall (M) |
| First frame, working backboardd | 70 s (p2) | 40 s (p29) | 30 s of each is the IOAcceleratorES poll (M) |
| Home, working backboardd | ~590 s (p2) | ~50 s (p29) | ~12× (M; Home ±10 s) |
| UFS | p2 single-block: 54 s busy to Home | 6.9 s busy in total | multi-block alone removes ~45 s on one CPU (M: r2 11.6 s vs p2) |

The one-CPU line has a single A725 (533 MHz on p2), the 5-CPU line has a governor at 533-1075 MHz (cap L16,
`research/ios26-fleet/handoffs/limits.md`: P4/P5 profile). L13/1536 MHz on 5 cores is "don't run yet" (P7); none of the
changes below needs a higher clock.

## 8. Changes ranked by expected seconds saved on the 5-core 300 s profile

| Rank | Change | Saves (5-core) | Evidence | Confidence |
|---|---|---|---|---|
| **1** | **Stop the backboardd CoreBrightness crash loop.** Quickest A/B: the A7 recipe without `hk_bright=140` (cap 0 makes `AppleCLCD::publishBacklight` return early, as on p29 and p2). Real fix: make `AppleARMBacklight` (SweetFramebuffer.cpp:393) carry whatever CoreBrightness reads after it matches `backlight-control`. | **From "never" to Home at ~50 s after root** (≈ 90 s from power-on). No other change matters until this one lands | M: every boot that publishes `SWEET BL: AppleARMBacklight` (p32, A7 r1, A7 r2) matches it at 10/30 s and SIGSEGVs at the same CoreBrightness PC ~30 s later, every respawn. Every boot without it (3 × p29, p2) keeps backboardd pid 22/38 for the whole run and presents at 40/70 s | **Correlation, not yet causation (I).** p32 also added `blazer_rtc=1` and the kernel changed p29 → p32/rootview. The p30 hit was p32 residue in the dump (its own msgbuf: no BL, no crash), so the RTC is not yet ruled out. One boot with only `hk_bright` dropped decides it |
| **2** | **Remove the 30 s `IOAcceleratorES` wait in backboardd** (first frame comes when the poll gives up) | **20-30 s** off first frame and Home | M: 30 s of ~10/s polling with 0 found in all 7 boots (10 → 40 s; p2 40 → 70 s), and `display on` is at the end of it every time | Mechanism I: options are a stub accelerator service that answers "none" quickly, or the defaults key/timeout CoreAnimation uses (to find). Not every one of the 30 s is reclaimable: the launch storm runs to ~20-30 s on 5 cores |
| **3** | **Shim diagnostics off for a normal start**: USB-console enumeration waits (9.0 s), console init/paint (4.4 s), and a cached-MMU or no-copy payload admission (6.4 s) | **9-15 s** (9 s certain; console and copy are best-effort) | M: identical in all 6 boots (stamps). The chooser r4 "cached decode" already cut its own decode time | Wait times M; copy cost cause I |
| 4 | DPU probe off (`hk_fb_probe=1` holds pid 1) | 4.1 s | M: `pid 1 released after 4109-4328 ms` | High |
| 5 | Persistent `/var` caches (lsd database, icon cache, cfprefs) instead of the ramfs `varfs=1` that is rebuilt each boot | ~3-8 s wall (lsd alone is 10.7 CPU-s in the storm) | M: lsd/iconservicesagent CPU; persistence gate in HANDOFF item 3 | I |
| 6 | Trim launch daemons that only fail or respawn (fairplayd.H2, bluetoothd, PerfPowerServices, wifip2pd, magicswitchd, DumpPanic ...) | 5-CPU: ≤ 2-5 s. 1-CPU: tens of s | M: throttle table; 62 CPU-s storm over 2-4 cores | I |
| 7 | UFS: queue depth > 1 / async strategy, larger commands, readahead | ≤ 1-4 s on 5 cores (upper bound: 5.4 s busy in the first 30 s; over the whole boot 4.1 of the 6.9 s busy is the 300 µs spin) | M: 5.7 blocks/cmd average, well under the 16-block cap, so a larger cap helps little; device wait 103 µs/cmd. On 1 CPU the single-block p2 path costs ~45 s, already fixed by `blazer_ufs_multi=1` | I for gains |

**Projected 5-core start with changes 1-4 (I):** 13.5 (ABL/fastboot) + ~12-17 (shim) + 0.4 + 0.1 (root) + first
frame at the end of the launch storm (~15-25) + ~10 (Home render) ≈ **50-65 s power-on to Home**. With change 1 only:
≈ 90 s, already well inside 300 s and the P4/P5 thermal window.

## 9. Open items and contradictions

- **p32 "Home + Settings" (journal, O) vs the p32 log** (M: 0 swaps, `HK PRESENT queued=0` ×10, 8 backboardd deaths).
  The journal itself calls this unresolved. If the owner's sighting belongs to another boot, p32 fits the pattern
  above; if not, the frame counters miss a presentation path. That is worth one question to the owner, not a boot.
- `HK TOP frames+N` and `SWEET FB: swap` lines: swaps are logged only up to 16 per boot, so use `frames+N` for rate.
- Chooser path: power-on → chooser → shim entry is not measured. The 13.5 s here is the fastboot path (lowest of 6).
- **Next (one variable, attended, owner's call):** `a7-ios-system-r3` = A7 r1 recipe (5 CPU, 300 s) minus `hk_bright=140`.
  Expect `display on` at axis ≈ 40 s and no `usertrap: backboardd`. If it still crashes, drop `blazer_rtc=1 blazer_rtc_bounds=1` next.

## Files

- `timeline.py`: per-boot JSON extractor (watch series, exec/spawn/exit/throttle, HK TOP).
- `kaxis.py`: regex lines on the kernel axis.
- `data/*.json`: the seven extracts behind every table. Derived timings only; no dumps, serials or Apple artifacts.
