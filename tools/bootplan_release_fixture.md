# release (`research/ios26-release-r1`)

Updated 2026-11-02 01:3x. **State: `kernel.ios26-p11` is the newest kernel, LINKED (host, observed), never run. p4 is the newest kernel that has run on the phone (`phone-touch-r2`). Phone boots are on hold at the owner's word.** **p12 is queued, not linked: 1070..1074 are in the tree, HEAD `1e3d7bd6`, tree `fad38f82`. It links once smp reports and the parent names `0722`, `0724` and fastcore's `0703`.** The line for it is in "Next try".

## The plan (parent)

- One kernel carries every patch that's ready, each behind its own boot arg. Boots turn things on a few at a time, so a failure can be traced.
- A patch that fails to apply or link stays out, and the parent hears why at once. It doesn't hold the others.
- Each relink gets a new number (p5, p6, …): a pN is never rebuilt.

## Kernels

| Kernel | Is | SHA-256, `research/ios26-release-r1/artifacts/` | Unstripped, same path `.unstripped` | Run |
|---|---|---|---|---|
| **p11** | p10 + 1065..1069. Tag `p11`, HEAD `f00cd91e`, tree `4646aa32` | `666f744edc2936a4056ad9e1abd321b09e125aa0415190e91e66b5d5f4af5f22` | `1f0c5b2464fa75a94f94529db26b0a658ffeae773cd5138463d705e9b4491daa` | Never |
| p10 | p9 + 1063, 1064. Tag `p10`, HEAD `fec2d415`, tree `3777916b` | `5b4cb14a8b33f84d6bcc28caa95efa18c1a8cc8dc877dcee1b3715dc12bf2454` | `6a23f36d00dd452d137654bae80bcead17ab8b4a5146f1ebf6dbd14a3b5f290f` | Never |
| p9 | p8 + 1062. Tag `p9`, HEAD `4c83e99f`, tree `25405c53` | `e02f0bf5293655a666536ef969931099c312ef789433906c302ea48af9ac351c` | `badec63dab233a230177482bd3a8803c3077ea4b105adce8c694c0fb48a243f5` | Never |
| p8 | p7 + 1051..1061. Tag `p8`, HEAD `35dc2e88`, tree `e54322a2`. **No fast-core boot: lacks 0702** | `b593f5e2fe93195ad4852c5cd39e5b6828ab0145ce55d4f7b8c6ab4bcd7c8e5f` | `9242c2bbcd3ef984ec5693f599a14af1d3b9ab0ece14faa1c26a08c8d11d21b7` | Never |
| p7 | p6 + 1049, 1050. Tag `p7`, HEAD `c826d23f`, tree `f942e47f` | `30ceecda247d0c58caf109ab7dcd49897abbef730e911e9b77fd784401f8af73` | `abe82463f6d4cc18522cb6ba1fea0c9d7de394602414035606dec5803fca22ff` | Never |
| p6 | p5 + 1043..1048. Tag `p6`, HEAD `6888a1f3`, tree `93edc593` | `961e4e0a993f70ce15c84b11f2af3f9c2dde37bcd1d4ff791ecdd83902ec0a7a` | `d04eacf35f91a28b7a3779b3ac963f9e799ba563530dd6ad4e6aa74259afdca9` | Never |
| p5 | p4 + 1040..1042. Tag `p5`, HEAD `b9e4f0ac`, tree `cd2c785d` | `7c8cc82f8a03b11c32b816414b1e101058068235f06fbaf74014be4b3bcd904b` | `e797bf08e6b65eda0f281b28e5dad9ff5a4cfc25c4f2ca267e07e0dde05cd844` | QEMU `overlay-1`: passes |
| p4 | p2 + 1037..1039. Tag `p4`, HEAD `c58b0b1d`, tree `3a26f74e` | `22022cdadbaef0980b2c1378cb5c81025a6993c0c7e60fd4797ccac1f5157a91` | `e6843e8ecca7a788997d4f668efc6da1efea51be2eed604451b480507a9dccba` | **Physical, `phone-touch-r2`** |

**Combined patch:** `combined/ios26-p11-all-in-one.patch`, SHA-256 `20c185fbe22750856194cd0da0a962f24cde1b77f54b2b0e0cd0629bac49fd7d`, against pristine xnu-12377.121.6, gives p11's tree (proved). Apply with `git apply`. Only the newest is kept. For an older kernel: `git -C work/xnu diff --full-index --binary 1642d88 pN`.

**Series:** `series/1000..1069` are released; `1070..1074` are queued for p12, and those numbers are final only once linked. Origin and hash of each in `series/PROVENANCE.tsv`. 1000..1036 byte-identical to integrate's.

## Next try

**Decision: one boot of p12 with every "On" row below, 763 B of 1023.** This is the owner's plan: finish CPU work, one image, then boot. XNU boots on A725 `0x200` and `0722` adds the other four A725s, `--bootcpu 0x200 --cpus 5` (`fastcore.md` section 0). No image is built, and it can't be built yet: see "Before it can be built". QEMU can't run this line either, because its boot core is MPIDR 0 (fastcore), so the first run is the phone's. Only touch and `hk_top` have run on the phone; the rest of the rows and the combination are new there.

**Order** is the order to take things off if the boot fails with no clear cause: one step per boot, the same p12, a new image name each time. SMP goes first. A failure that matches the last column goes straight to that row. **Keep** rows stay to the end. Bytes include the leading space. "Line then" is the length once that step and those before it are off, measured with the tool's own `cmdline()`.

| Order | Feature | Exact arg | Bytes | Next boot | Line then | Why, and evidence | Take it off first if |
|---|---|---|---|---|---|---|---|
| 1 | SMP, all five A725s | `cpus=5`, by `--cpus 5` with `--bootcpu`. Off is `--cpus 1` and a new image, because the ADT changes | 0 net | **On** | 725, with the next two | Never run on the phone. Nodes `0x200, 0x300, 0x400, 0x500, 0x600`, logical 0-4, cluster-type 0. Parked cpu0, cpu1 (A520 errata) and X4 stay out. CPU_ON is physical on `0x200`, `0x300`, `0x500`, low entries only: **XNU's entry above 4 GiB is untested, and `cpu4`, `cpu6` have never been started**. No driver on this line has had a second CPU: UFS, the CPM queue and ramfs take locks; `blazer_touch.c`, `tensor_dpu.c` and `sweet_scanout.cpp` take none of their own (grep only, not reviewed) | `SWEET CPU: cpu=1 NOT alive: PSCI CPU_ON rc=-9`, a hang after `cpu=1` starts, or a spinlock or ticket-lock timeout. Line 1 or 2 of `ios26-smp-r1/EXPERIMENT.md` with no `rc`: stop, no retry until it's read |
| 1 | Cross-core self-test | `blazer_smp_test=1` | 18 | **On** | With SMP | Stops the boot by name on any SGI, timer, atomic, clock or TLB failure, and costs seconds. Fastcore: first image only. Never run on the phone | Its panic names the failure: SMP comes off |
| 1 | Fast first | `blazer_fast_first=1` | 20 | **On, as the parent asked. Recommend off: then 743 B** | With SMP | 0724. Fastcore: five identical cores, nothing to place, leave it off. By source it also costs here: foreground goes to the lowest idle core over its own last core, and leaves at quantum end for a lower one, losing its L2 (inferred, not measured). Never run. **On no list today:** see below | A panic in `sched_prim.c`, or threads bouncing between cores in `hk_top`. It can come off alone |
| 2 | One fast core, cpu2, A725 | `blazer_bootcpu=0x200`, by `--bootcpu 0x200`, which also sets `blazer_deadline=900` | 20 net | **On** | 705 | Model 3.45x at the same 533 MHz, the biggest gain. CPU_ON, EL drop and reset physical in `speed-probe-r3`. XNU has never run on it | `fc-*` in the REFUSED stamp, HANDOFF with no kernel lines, `cpu=0 startup timeout`, any failure before `SWEET CPU: boot core`. Then `--wait 2100` |
| 3 | Picture fills the panel | `hk_fb_scale=1`, with `--canvas 1125x2511` | 14 | **On** | 691 | Canvas passes QEMU `native-1`, without the scaler. Scaler registers have never run anywhere (`render.md`) | Panel black or wrong while the log runs, `tensor-dpu: latched`, rc -2 or -3. The canvas then shows centred with bars |
| 4 | Hold the CPU through a read | `blazer_ufs_hold=1` | 18 | **On** | 673 | One CPU turn per read. Physical basis: 2-3.4 ms a read in 28 of the 10 s intervals, against 139 us elsewhere (`mine.md`). At `cpus=5` most of that reason goes, as others have their own core (inferred). It's for when SMP comes off. Never run. Host: released on all 7 slow and failure paths | Any panic in a UFS thread, or under `lck_mtx_unlock` |
| 5 | Spin on short UFS polls | `blazer_ufs_spin_us=300` | 23 | **On** | 650 | Goes with row 4, which does nothing without it. Never run | As row 4, once row 4 is off |
| 6 | Whole UFS blocks per command | `blazer_ufs_multi=1` | 19 | **On** | 631 | Up to 45 s of the 64 s UFS busy before home (`mine.md`, inferred). 16-block reads physical in the whole-image check; this path never run. Mine's order is one UFS arg per boot: this try takes them together | `blazer-root: READ failed`, or a code-signing kill in `hk_usertrace` |
| 7 | Faster copy to the panel | `hk_fb_fast=1` | 13 | **On** | 618 | Up to 4x on the copy (`cpudeep.md`). The probe's `fill_us` measures it against 8.7 ms. Host only | Torn picture, or a fault in the copy |
| 8 | Store bypass | `blazer_ssbs=3` | 14 | **On** | 604 | Loads on A725 stop waiting on older stores. Gain unmeasured, and can't be measured alone here (fastcore). `PFR1` SSBS 2 physical on all cores. Set per core in `cpu_machine_init` (read) | Unexplained user crashes that started with it |
| 9 | DRAM and fabric levels | `hk_clk=30` | 10 | **On** | 594 | Shows if memory is the limit. The read is physical from the shim, `clk-probe-r1`; never from XNU | Touch or the queue misbehaves, `HK CLK: stopped` |
| 10 | Prefs, 12 jobs fewer | `hk_overlay=3`, with `--var-overlay research/ios26-overlay-r1/overlays/p5-first.ovl --var-overlay-sha f649fc383cf00e3537697aa6925b2bf2a21f7a9843e55592cc0939624203cf08` | 13 | **On** | 581 | QEMU `overlay-1` on p5 passes (parent), lower risk than the rows above. **Speed gain not shown:** SpringBoard still took 10-21 s of most 30 s windows there, read from its `HK TOP` lines, against sbload's target of about 3 s. Never on the phone | A `varfs-overlay:` panic names it. SpringBoard or backboardd don't come up |
| 11 | Debug checks off | `validation_disables=0x39d64` | 28 | **On** | 553 | 1-5% (`kconfig.md`, estimate) | **Any crash with no name once SMP is off: this comes off next, out of order,** so the asserts name it |
| 12 | Quieter userland logging | `atm_diagnostic_config=0x400` | 28 | **On** | 525 | 2-6% (`kconfig.md`, estimate). Kernel lines and panics unaffected (read) | A userland log is needed to explain a failure |
| Keep | Touch | `blazer_touch=1` | 15 | **On** | | Physical on p4: 3109 reports, 0 bad, axes right. Trace equal to p4's on the p12 queue | `stopped:` names why, and the boot goes on |
| Keep | Bars clamp | `blazer_touch_bars=1` | 20 | **On** | | Arg on in p4's boot. Nothing to clamp while row 3 is on, but it's needed the moment row 3 comes off | |
| Keep | CPU per task | `hk_top=30` | 10 | **On** | | Physical on p4. Shows what to fix next. It sums CPU across five cores now, so a window can exceed 30 s (inferred) | |
| Keep | UFS cost lines | `blazer_ufs_cost=1` | 18 | **On** | | Read-only timers; `decode_cost.py` splits lost CPU from slow device (`mine.md`). Never run | |
| Keep | Panel's real rate | `hk_fb_te=1` | 11 | **On** | | Parent: it only measures. 60 Hz is unproved, and this settles it. One spin on a status register at attach, bound 1.5 s, and it labels late underruns (read). Never run. Without `hk_fb_pace=1` it gives the rate, not screen's verdict on whether underruns are false | Only if the log stops at `tensor-dpu: te` |
| Keep | Per-core report | `blazer_smp_report=1` | 20 | **On** | | Identity and REVIDR per core, what EL3 set, real clock by AMU. `cpu4`'s and `cpu6`'s REVIDR is unread: NOT FIXED goes to the owner (fastcore). First AMU read from XNU | `reading AMU` is the last line, then a button: drop it, boot again |
| Keep | Base line, `--phone-root --phone-route md0-mountroot` | Fixed by the tool | 431 | **On** | | Physical on p2: home screen | |
| Keep | Payload version 2 | None: every new image | 0 | **On** | | Needed past 607 B. Host only, never run on the phone (`PHONE-ROOT.md`) | `XNU not entered`, or the shim refuses the payload. Bootchain |
| | Skip page hashes | `blazer_cs_nohash=1` | 19 | Off, first to add | | Up to 80 s of 660 s (`mine.md`, inferred). Hashes are what would catch a bad read from rows 4-6, so one clean boot with those comes first | |
| | Vsync period | `hk_fb_period=1` | 15 | Off until tested | | Screen: looks like a no-op for CA, since nothing sets `+0x5be` bit 1 and selector 72 wasn't seen. Harmless off (parent) | |
| | Start transfers inside TE's window | `hk_fb_te=2` | 11 | Off | | Needed only at 120 Hz (`screen.md`) | |
| | Pacing | `hk_fb_pace=1` | 13 | Can't: not on the tool's list | | Screen's first test pairs it with `hk_fb_te=1`, to tell false underruns from real. Next, once this boot shows the rate | |
| | Panel rate, panel off | `hk_panel_hz=60\|30\|120\|10`, `hk_panel_off=1` | 15-16 | Off, own boots (parent) | | First DSI commands from XNU. A fault may reset the phone. `hk_panel_off` needs a wake input first, or the panel stays off (`screen.md`) | |
| | GPU power proof | `blazer_gpu=1` | 13 | Off, own boot. Not on the tool's list | | Metal stage 1. **A state change:** a vote for a domain nothing has voted for from XNU | |
| | More RAM | `blazer_mem=GIB` | 13+ | Off, no boot slot. Not on the tool's list | | Ram: about 0% for speed | |
| | Clock vote | None | | Can't: no patch exists | | `ios26-dramclk-r1/VOTE-PROPOSAL.md` asks for shim-only `vote-read-r1`, `vote-write-r1` first. Registers never accessed. Goes in p12 only if the patch arrives | |
| | SMP tuning | `slto_us=`, `tlto_us=`; `blazer_smp_imp=1`, `blazer_smp_report=2`, `blazer_smp_panic=N`, `blazer_smp_stuck=K` | | Can't: not on the tool's list | | Timeouts are smp's answer to a lock-timeout panic: a slow core could trip 78 or 156 ms. The rest are smp's experiments | |
| | cpu0, cpu1, X4 as XNU cores | None | | Can't: fastcore's tool patch refuses | | cpu0 is parked and on. cpu1: A520 4615642, 3685825. X4: 3076789, 2957258 not fixed | |
| | More overlay groups | `hk_overlay=` with bit `4` glass, `8` low power, `0x10` jobs2, `0x40` jobs3. `0x100` jobs-big and later need `p5-second.ovl` or `p5-third.ovl` | 0-4 more | Off, later | | One variable each, after `=3`. jobs-big next in a guest (`overlay.md`) | |
| | Real date | `blazer_rtc=1` | 13 | Off | | AP's RTC read has never been sent, and a real date is new for iOS. After core and touch settle (`keysclock.md`) | |
| | Temperature log, then guard | `blazer_thermal=1`, then `blazer_thermal=2`, `blazer_thermal_panic_c=N` | 17, 43 | Off, own boot | | GET_TEMP has never been sent on the phone. This line runs with no temperature reading: see "Limits" | |
| | Live USB console | `blazer_usbcon=2` | 16 | Off, own boot | | First DWC3 read from XNU. A wrong guess resets at about 20 s, losing the whole try. It's the fix for the lost ring, so test it soon | |
| | Keys | `blazer_keys=1` | 14 | Can't: compiled out | | Needs 0651 `91f440db…`, not named. `keys-probe-r1`: pads read safely, volume seen, power not seen. Wake also needs overlay bit `0x800` | |
| | Accelerometer | `blazer_sensors=1`, then `=2` | 17 | Off, own boot | | p12's queue has cpmlock's lines (0635b). Whether the sensor answers is unknown | |
| | Fuel gauge | `blazer_battery=2`, then `=1` | 17 | Off, own boot | | Probe image `batt-probe-r4` first | |
| | Haptics | `blazer_haptic=1`, then `=3` | 16 | Off, own boots | | First touch of LSIO_E, on the USB repeater's bus (`haptics.md`) | |
| | CPU counters and benches | `hk_amu=1`, `hk_pmu=1\|2`, `hk_bench=1`, `hk_fb_bench=2` | 9-14 | Off, measuring boots | | The per-core report already takes one AMU read; these read it per task | |
| | I-cache by VA | `blazer_ic_va=1` | 15 | Off, no use | | 0723 already works by line | |
| | Filter | `hk_fb_filter=1` | 15 | Off | | Only if text looks wrong with the default | |
| | Scripted input | `hk_ui=…` | Varies | Off | | Owner has real touch | |
| | Touch axes | `touch_flip=1\|2\|3` | 13 | Off, not needed | | Axes physical and right | |
| | Zero copy | `hk_fb_flip=1`, `hk_fb_dirty=1`, `hk_fb_stats=1` | 13-14 | Can't: not on the tool's list | | `render.md`: no boots on it now | |
| | Fallback for row 10 | `hk_deny=NAMES`; `-no_corpses disable_exc_resource=1` | Varies | Off | | `overlay-1` shows `disabled.plist` works, so not needed | |
| | Others in the kernel | `hk_env=`, `exec_env=`, `regtrace=`, `hk_net_delegate=`, `hk_fmt=`, `hk_accel=`, `hk_scaler=`, `hk_dpu_qos=` | | Off | | No use on this boot. `hk_dpu_qos=1` only if underruns appear; not on the list | |
| | Wi-Fi | `blazer_wifi=1` and others | 14+ | Can't: not in the kernel | | No patch named yet | |

**The line, 763 B, 260 spare:**

`debug=0x8 serial=3 cpus=5 rd=md0 blazer_ufs_mountroot=1 msgbuf=1048576 varfs=1 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=userdata_exp.ai blazer_ufs_lun=0 blazer_deadline=900 launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 launchd_disable_all_timeouts=1 sweetarm64e=1 autounlock=0 interrupt-masked-debug-mode=0 blazer_panic=1 hk_usertrace=1 hk_fb_scanout=1 hk_fb_probe=1 sweetfb_noconsole=1 sweetfb_hz=60 blazer_touch=1 blazer_touch_bars=1 validation_disables=0x39d64 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_cost=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_te=1 hk_overlay=3 hk_top=30 hk_clk=30 blazer_smp_report=1 blazer_smp_test=1 blazer_fast_first=1 blazer_bootcpu=0x200`

Measured with `image_tool.py`'s `cmdline()` and the edits `--bootcpu --cpus` makes under fastcore's tool patch, in a scratch copy. That copy refused one token, `blazer_fast_first=1`, which I added to its list to measure. Bootchain's folder is untouched.

**Before it can be built:**

| # | What | Who | State |
|---|---|---|---|
| 1 | smp's `0722`, `0724`, fastcore's `0703` `c24ee961…` in p12 | Parent names them, release links | All three pass a dry run in that order on the queue, HEAD `1e3d7bd6`. `0722` `d358b5a3…` may change: smp has a rebuild queued. smp's condition stands: not for a boot until its QEMU tests pass and its final update is in |
| 2 | `tools-bootcpu-cpus.patch` `53ac7f8f…`: `--bootcpu --cpus`, nodes in that order, `blazer_smp_report=1`, `blazer_smp_test=1` on the list | Bootchain | In `ios26-fastcore-r1/patches/`, not applied. It refuses without `0703` and `0722` in the kernel |
| 3 | `blazer_fast_first=1` on the list, if it stays on the line | Bootchain | Only in smp's `tools/0001-bootchain-cpu-order.patch` `db75acc2…`, whose `--cpu-order` this image doesn't use, and refuses with `--bootcpu`. Fastcore's list leaves it out, as `0724` is optional and off. The two tool patches also change the same lines of `mkadt.py`, so they don't stack: this image needs fastcore's |
| 4 | `--qemu-run <run>`: `--phone-root` needs a QEMU run the parent accepted | Parent | No guest has run p12. A guest can run p12 at `cpus=1` on cpu0, or smp's matrix on its own ADT, not this line |

**The command,** for after those, with p12's hash, the image's name and `--qemu-run` for the parent to set. Run from the repo root:

```
python3 -I research/ios26-bootchain-r1/image_tool.py image phone-full-p12-r1 --kernel research/ios26-release-r1/artifacts/kernel.ios26-p12 --kernel-sha <p12> --phone-root --phone-route md0-mountroot --qemu-run <run> --bootcpu 0x200 --cpus 5 --canvas 1125x2511 --var-overlay research/ios26-overlay-r1/overlays/p5-first.ovl --var-overlay-sha f649fc383cf00e3537697aa6925b2bf2a21f7a9843e55592cc0939624203cf08 --phone-args "blazer_touch=1 blazer_touch_bars=1 validation_disables=0x39d64 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_cost=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_te=1 hk_overlay=3 hk_top=30 hk_clk=30 blazer_smp_report=1 blazer_smp_test=1 blazer_fast_first=1"
tools/bootios research/ios26-bootchain-r1/run/phone-full-p12-r1/boot.img phone-full-p12-r1 --mach research/ios26-release-r1/artifacts/kernel.ios26-p12.unstripped --wait 1200
```

**SMP's off step:** the same command with `--cpus 1`, without `blazer_fast_first=1 blazer_smp_test=1`, and a new name: 725 B, the same boot core, so one variable changes.

**Limits while row 2 is on (`fastcore.md`):** attended, 15 min, capped brightness, hard stop at 20 min. The tool's 900 s deadline ends the session even if the UI is up. Without row 2: `--wait 2100`, 1800 s, 35 min. **SMP raises this:** by EM the five cores at 533 MHz are 330 units at full load against cpu0's 69, units unverified (fastcore), and nothing on this line reads a temperature. Time and the owner's hand are the only limit. `blazer_thermal=1` is on the tool's list and fits, but GET_TEMP has never been sent on the phone, and cpmlock's order gives it its own boot, so it stays off.

**What the rows can't switch off.** All of these run for the first time together: 0714's UFS fix, smp's 0720, 0721, 0723 on cache maintenance, 0722's no-arg parts, 0700b, native's 0810, and touch on 0635's queue owner. If the boot still fails with only the Keep rows on, at 525 B, those are next: a kernel without 0720, 0721 and 0723 takes one relink. p4 is the last known good, but it lacks 0714, so it can still die with `READ failed` under load.
