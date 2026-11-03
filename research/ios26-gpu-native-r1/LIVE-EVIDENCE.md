# Native GPU live evidence and the next instrumented boot

Integration snapshot: 2026-11-04. Evidence reviewed: the named physical boots from 2026-11-03 only. **No new boot, phone action, XNU edit, build, or Git operation was performed for this document.** SOURCE/HOST statements are supporting evidence; PHYSICAL statements below come from the named phone captures. Inference is labelled separately.

## 1. Evidence identity

| Artifact | Identity / SHA-256 | Scope |
| --- | --- | --- |
| `research/images/a7-ios-system-gpu2/manifest.json` | manifest `556901efa0caba14513619fd80ba1978dbf97268b08e1c4f96bef6d0069d2832`; image `6dc9b62798903c9c8f18592b878ca7bd485e41e8ec2d074e49282b03b36641e7`; kernel `039204c0b23201b76d99e6c99d5465fe5274600537a91e665ff52e2b8911faaf`; unstripped kernel `eb385d7c83c48bbebf41da58001470606d18306b09515c2e4b78ddc4d5301883` | PHYSICAL rung 6, `cpus=1`, `blazer_gpu_tipc=6`; stopped before launchd |
| gpu2 `reader.txt` | `d1ab227f2b47766d2f2bd5d5df9a71cf31b3c62ae51d8c21aac89f71603c0a12` | Freshness-gated decode of the same boot |
| gpu2 `ramdump/kernel.log` | `b8cc7fe8432372f7242f8ca677181934d036018c7f6021a451089a8ef2c13ff7` | Raw PHYSICAL console/mirror evidence |
| `research/images/a7-ios-system-int3/manifest.json` | manifest `826466058cebee3a0ee4461e47bd34fc721ab84c064a7fec4b89675be89a2283`; image `eff0ed9ffac0e57512746409d0327711f9b91ac6fa0b25da395ed0504c89e0f5`; kernel `648b9f62c2a6b6b2086add8178fc1f8a7943347604a1bc9e1f2f81e9e1049641` | PHYSICAL five-A725 userland boot, `rd=ufsroot0`, 1000-byte command line |
| int3 `console.txt` | `2190170bcc12961604e71b931aef5e3716c59496de884a56f16c01a83ed4f8a7` | Live USB console through 23:37:22; 19,181 newline-delimited records including interleaved/NUL-containing text |

The int3 image has **no** `blazer_gpu` or `blazer_gpu_tipc` argument and its console has zero `HK GPUTA` / `blazer-gpu` records. It therefore supplies a userland/scanout baseline, not another firmware-health result.

## 2. gpu2: firmware transport and post-recovery health are PHYSICAL PASS

Attempt: `research/laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/`.

| Time/order in `reader.txt` | Observation | Meaning and limit |
| --- | --- | --- |
| 162-177 | Trusty build/API/FFA/vring setup completed; `tipc online`; log channel `add -> 0`; `conn_rsp status 0 remote 1000 max_size 4096` | The GPU TA transport worked. |
| 201, 247 | Firmware carve-out body/header written; `SEND_FIRMWARE_IMAGE ... result 0 in 1207 ms` | The TA accepted the pinned image. This is not execution proof by itself. |
| 249-252 | GPU vote reply `0xf 0x12 0x14`; `control 0x1 pfsm 0x2b`; CORE_ID `0x470002099004bc`; `SMC START -> 0x0` | Power/identity/start transport passed. BVNC is PowerVR DXT 71.2.2448.1212, not Apple AGX/Mali. |
| 253-258 | Initial shared state: started=1, OS0 ACTIVE, `pow 1`, `fw_faults 0`, `hwr 0xa`, empty assert; FWCCB slot 0 is unacknowledged `DEBUG_DUMP` type `0x2abc006a` | Shared memory is readable. The pending dump is a warning, not readiness. |
| 284-290 | HEALTH_CHECK slot 0 consumed in 378 ms; return remains 0; post-health `hwr 0x1` | Stock does not wait for HEALTH_CHECK's return slot. Consumption alone is not command-execution proof. |
| 314-319 | STATEFLAGS_CTRL slot 1 read in 1 ms, return `0x1`; KCCB w/r=2/2 | A waited firmware command executed (`CMD_EXECUTED`). |
| 344-419 | 476 firmware trace words emitted | Enables independent offline decode. |
| 420-441 | 18 reviewed registers read; sampled MMU fault/status registers all zero; SLC idle `0x01ffffff`; timer +1855/1000 us | This is the **post-recovery REE snapshot**, not a clean-init result. |
| 442-443 | `M2 HEALTH PASS`; `kccb w 2 r 2`; `fwccb w 1 r 0` | Post-recovery health passed; FWCCB remains deliberately unacknowledged. |
| 479-492 | TA reports expected-24.2/found-26.1 and `process_st_info() failed (278)`; rung 6 PASS; intentional panic at `gta_thread+0x4fc` | The TA messages remain unexplained here, but the boot did not die from them. The only panic was designed. |
| 4, 23 | root mounted; launchd not executed; last milestone ROOT-MOUNT | No userland, Metal, or rendering evidence can be inferred from this boot. |

The attempt metadata records a temporary-boot-only device contract. No gpu2-specific Android return receipt was found in this review; do not borrow one from another attempt.

## 3. gpu2: the firmware trace proves an init MMU fault, lockup, and HWR before health

I ran the repository decoder:

```sh
python3 -I research/ios26-gpu-r1/m2/tools/fwlog_decode.py \
  research/laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/reader.txt \
  research/ios26-metal-r1/dl-gos/private/google-modules/powervr/pvrsrvkm/include/rgx_fwif_sf.h
```

At review time `research/ios26-gpu-r1/m3/` contains layout/source helpers but no separate decoder; the M2 decoder is the applicable tool. The decoded sequence is:

1. Driver/CCB initialization and firmware configuration complete; APM latency is 60000 ms.
2. `RGXFW_SF_HWR_MMU_FAULT_EVENT`, then `RGXFW_SF_HWR_CORE_MMU_FAULT`: core 0 MMU status `0xa100000000000009 0x00008200`.
3. `RGXFW_SF_MAIN_HWR_HIT_LOCKUP`: `GPU-0 has locked up`.
4. `RGXFW_SF_HWR_START_HW_RESET`, failed hardware polls at `0xf0b8`, `0xf0c8`, `0xf7c0`, `0xf7c8`, and TEXAS/BIF PFS poll failures.
5. Reset completes; DM1-DM5 report recovery; power/MTS activity resumes.
6. Only then does KCCB slot 0 execute command `0x2abc006f` (HEALTH_CHECK), followed by slot 1 command `0x2abc00ce` (STATEFLAGS_CTRL) with return value 1.

`docs/debug/backlog-notes.json:65` additionally identifies the fault as META DMA at address 0. That identification and the coremem diagnosis below are SOURCE-backed analysis; the raw decoder line quoted above is the direct PHYSICAL observation.

**Important reconciliation:** zero `MMU_FAULT_STATUS_*` values at `reader.txt:429-433` do not contradict the earlier firmware trace. They were sampled after HWR recovery. A final `fw_faults 0`, empty assert, active OS state, and successful STATEFLAGS command similarly do not erase the init fault.

### Coremem hypothesis to test, not a completed fix

SOURCE/HOST layout evidence puts `sCorememDataStoreDeprecated` at SYSINIT `+0x150` (`m3/receipts/fw-layout-r3.h:5`). M2 leaves it zero; stock fills it. The coremem data section is at carve-out offset `0x13c000`, and the measured raw heap base is `0xE1C0000000`, so the candidate 64-bit device address is:

```text
0xE1C0000000 + 0x13c000 = 0xE1C013C000
```

This is the strongest current explanation for the address-0 META DMA fault. It remains **unverified** until a fresh boot has no init MMU fault, lockup, failed polls, HWR, or init DEBUG_DUMP before health.

## 4. int3: the complete GPU-to-display evidence map

Attempt: `research/laguna-usb-fix/attempts/live-20261103-232046-a7-int3/console.txt`.

### 4.1 Instrumentation actually enabled

- `HK DBG: hk_dbg=0x1e1e1f` at line 72 = input, snapshot, usertrace, default USTACK, crashinfo, screen=30, top=30.
- `HK USTACK` line 108 selects **Preferences,MobilePhone**, every 5 s, 240 rounds/pid, 12000 lines. There are **zero** backboardd/SpringBoard USTACK records.
- `HK SCREEN` line 145 enables 360-pixel RGB565 records every 30 s and at deadline/panic. Captures occur at lines 1300, 3192, 4524, and 12419.
- backboardd receives `hgltrack`, `hk_container_ready`, and `hk_accel_once`; `HK_ACCEL_ONCE=skip` (lines 222, 720-722).
- IOK tracing defaults to backboardd,SpringBoard and has a global 400-line budget in `hk-int3:iokit/Kernel/IOUserClient.cpp`. HKL also reports dropped lines, so absence of a later userspace message is not proof of absence of activity.

### 4.2 Accelerator/Metal chain

| Line(s) | PHYSICAL observation | Interpretation |
| --- | --- | --- |
| 889 | `HGLTRACK: SWContext slot wrapped, slide 0x1f0f0000, reprotect 0` | The tracked software-context path is active. This is not a GPU context or GPU execution receipt. |
| 890 | `HKACCEL: IOAcceleratorES wait skipped, pred 0 -> 0xa5e` | The 30-second wait was skipped by instrumentation; no service was created by this hook. |
| 1423 | backboardd `IOProviderClass=IOAcceleratorES -> 0 found` | No IOAcceleratorES service is published. |
| 1459, 1490 | backboardd `IOProviderClass=AGXAccelerator -> none` twice | Both backboardd AGX queries fail. Apple's AGX driver is not a valid DXT backend; a native service must satisfy this class query. |
| 2244 | SpringBoard `AGXAccelerator -> none` | SpringBoard also finds no accelerator. |
| 2323 | SpringBoard `IOAcceleratorES -> 0 found` | The base-class query fails too. |
| 2329 | `SUICOrbView ... Failed to get Metal device for GPU rendering` | The concrete Metal-device creation failure follows the missing service; it is not a shader/compiler failure. |

Required future correlated evidence: one ready native object matches both class names and carries `MetalPluginName`; an owned probe creates `HMNativeMetalDevice`; actual GPU submissions complete; only then should the SUICOrbView failure disappear. Flipping only the registry lines is insufficient.

### 4.3 Display, IOSurface, and presentation baseline

| Line(s) | Observation | Limit |
| --- | --- | --- |
| 107, 125 | `IOCoreSurfaceRoot registered`; AppleCLCD published at 1280x2856, stride 5120, presented as 1125x2511 | Display/surface services exist independently of a GPU accelerator. |
| 1393-1416 | backboardd opens AppleCLCD type 0 -> 0; AppleCLCD match succeeds; selectors 88/57/18/15/22/29/33/74 return 0 | Scanout and its user-client path are alive. AppleCLCD is not the accelerator. |
| 1434, 1439, 3091 | Further AppleCLCD opens return 0 | Repeated scanout access, not Metal. |
| 1470-1473, 2325-2328 | IOCoreSurfaceRoot matches once and opens successfully in backboardd and SpringBoard | IOSurface IPC exists despite zero accelerator services. |
| 1494, 1521, 2938 | backboardd creates 1125x2511 BGRA (`0x42475241`) surfaces, bpr 4608, size 11583488 | Exact software-composition buffer baseline. |
| 1516-1518 | swap 1 uses surface 2; first DPU `kicks 1 dones 1`, no underrun/nofetch | CPU/compositor-to-DPU presentation works. It says nothing about GPU completion. |
| 1522 onward | swaps continue; later samples reach `kicks=dones` (for example 257/257, 513/513, 5121/5121) | Ordinary DPU frames must not be promoted to native GPU/Metal evidence. Underruns rise later; these counts are not FPS or clean-compositor acceptance. |
| 2881-3596 | SpringBoard/iconservicesagent create additional BGRA/RG/A8 surfaces | Useful future GPU import/pinning/cache test corpus; currently CPU-side surfaces. |

The terminal USB record says `device gone` after 2,216,595 bytes, one connect, zero timeouts/lost records. This establishes capture continuity, not GPU health.

## 5. Stack symbolication result and evidence gaps

`ustack_sym.py` was run against the int3 console with cache `/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e` (UUID `0f1ee33235db30f38f5fbd4b954138d5`), separately with `--proc backboardd` and `--proc SpringBoard`. Both produced only the cache header: **there are no relevant stacks to symbolicate**. HGLTRACK supplies a slide but no PC/LR/fp chain, so `dsc_sym.py` cannot add information. The many Preferences/MobilePhone stacks are unrelated and were not substituted.

The resulting instrumentation requirement for later CA/Metal boots is explicit `hk_ustack=backboardd,SpringBoard`; `hk_dbg` bit 3 must be cleared so it does not install the default Preferences/MobilePhone list. A fitting int3-derived line is obtained by replacing `blazer_haptic_tap=1` with `hk_ustack=backboardd,SpringBoard` and changing `hk_dbg=0x1e1e1f` to `hk_dbg=0x1e1e17`; the result is 1014 bytes including NUL. That is a **later stage-8 instrumentation template**, not the next firmware boot.

## 6. Single recommended next GPU-instrumented live boot

### Recommendation

Run **one new coremem-only M3/rung-7 S1 temporary boot after agent 1 lands a runnable, reviewed implementation**: gpu2's exact image/argument baseline with only `blazer_gpu_tipc=6` changed to `blazer_gpu_tipc=7`. This boot tests only the coremem correction and existing M2 health; **it issues no client KICK**. Agents 1 and 3 independently require this physical clean-init gate before agents 4/5 construct or submit a client stream. It is the shortest safe path to the evidence every downstream facet lacks.

**Do not boot the current partial M3 source unchanged.** At review time it does not assign `gta_m3_coremem`, accepts only rungs 1-6, enables M2 setup only for rung 6, and has no context/CCB/KICK/UFO implementation. There is no gpu3 image yet.

### Required implementation/instrumentation before image creation

- Agent 1: write `0xE1C013C000` at SYSINIT `+0x150` before the final barrier/SMC START; read back both volatile words before START and emit the pre-start `M3 COREMEM` line from COREMEM-INIT §5. Enable M2 tracing/state dumps for rungs 7/8 and dispatch rung 7 through real M2 health, never a vacuous PASS.
- Agent 1: parse the trace before HEALTH and again after STATEFLAGS for `CORE_MMU_FAULT` (`0x7004b052`), `HIT_LOCKUP` (`0x700110c5`), `FAILED_HW_POLL` (`0x7003b00d`), `START_HW_RESET` (`0x7001b03d`), assert, and DEBUG_DUMP. Any nonzero/invalid/truncated/unknown-gap result stops the boot. Acceptance needs a strict sequential parser; the existing review decoder scans/resynchronizes and must not turn malformed input into a zero-count PASS. Keep S1's result distinct (`M3 S1 PASS`), always dump the final trace/survey, and issue **no client KICK**.
- Agents 4/5 have no implementation prerequisite for this S1 image. Their later S2-S4 work remains behind this physical gate and agent 2's real FWCCB dispatcher. It must use agent 3's corrected address contract: page-catalogue `sPCDevPAddr` is backing DMA/PA (`GTA_CARVEOUT_PA + pc_offset` in the carve-out case), not `GTA_DEVVA_HEAP + pc_offset`; the host-local CCB write offset travels in KICK rather than a normal-path store to shared `CCCB_CTL.ui32WriteOffset`.
- Keep `cpus=1`, the thermal 70 C guard, deadline/panic reset, and all other gpu2 arguments unchanged. **No `hk_dbg` token is needed**: this rung ends before launchd, so USTACK/HGLTRACK/CA probes cannot run. Preserve the existing live USB console and full M2 firmware-log/register dumps.
- HOST gates first: M2+M3 tests, malformed/timeout/no-host-success mutants, enabled-gate ARM64 objects and expected symbols, and a gpu2→gpu3 manifest diff showing only the rung token plus expected kernel/build-generated identity changes.

### Concrete coordinator recipe

Recommended names below are planned artifacts, not claims that they exist:

```sh
# Coordinator only, from Android with ANDROID_SERIAL set; temporary fastboot boot only.
# Build/check research/images/a7-ios-system-gpu3 from gpu2 with exactly:
#   blazer_gpu_tipc=6  ->  blazer_gpu_tipc=7
# and the reviewed M3 kernel. No other boot-argument changes; no hk_dbg token.
adb reboot bootloader
tools/bootios research/images/a7-ios-system-gpu3/boot.img a7-ios-system-gpu3 \
  --mach research/ios26-gpu-r1/artifacts/kernel.gpu-m3-r1.unstripped --wait 480

A=research/laguna-usb-fix/attempts/<returned-a7-ios-system-gpu3-attempt>
python3 -I tools/all_decode.py "$A/ramdump/kernel.log" \
  research/images/a7-ios-system-gpu3/manifest.json
grep -a -E 'HK GPUTA|blazer-gpu' "$A/ramdump/kernel.log" > "$A/gpu3.txt"
python3 -I research/ios26-gpu-r1/m2/tools/fwlog_decode.py "$A/ramdump/kernel.log" \
  research/ios26-metal-r1/dl-gos/private/google-modules/powervr/pvrsrvkm/include/rgx_fwif_sf.h \
  > "$A/fwlog.txt"
```

The raw/mirrored text contains duplicate M2 trace groups (the decoder reports 960 collected words while the firmware header says 476). Decode/compare the **first complete `M2 fwlog` group**, not the concatenation as if it were new firmware activity.

Accept only this S1 chain:

1. Pre-SMC `M3 COREMEM` reports field `0x150`, raw heap `0xe1c0000000`, section `0x13c000`, device VA `0x000000e1c013c000`, and the two readback words match.
2. Pre-health trace is valid and has zero MMU fault/lockup/failed-poll/HWR-reset/DEBUG_DUMP; `fw_faults=0`, assert empty, and no pending init dump.
3. HEALTH is consumed and STATEFLAGS executes with return 1; final trace counts remain zero.
4. All four MMU survey values are zero, the timer advances, all 18 registers are captured, and only the deliberate `rung 7 S1 PASS` panic occurs. **No client KICK, context, UFO, compute, or Metal result belongs to this boot.**

Stop immediately on any fault/HWR/assert/unexpected panic, malformed/truncated trace, missing fastboot return, or failed Android return check. After the attempt, return using the normal coordinator flow and run `research/ios26-dualboot-r8/return-check.sh`. A clean S1 permits design of the separate S2-S4 KickSync boot; it is not itself a shader, compute, Metal, or Liquid Glass result.

## 7. Gaps this boot does not fill

- Separate S2-S4 GP common-context/KICK/UFO proof (agents 3/4/5), using the corrected page-catalogue DMA address form.
- Real GPU VM mappings/security ownership, global 16 KiB range verification, and execution-base evidence (agent 3).
- Actual CDM engine work, cache handback, guarded compute output (agents 4/5/7).
- IRQ/mask/drain and secure STOP/power lifecycle (agents 2/5/10). Later proof needs native INTID162, OS0 `+0xbd0/+0xbe0` mask `0x3`, OSDATA counter `+0x230`, completion polling disabled, and strict `IRQ_UFO` plus SLC/cache evidence.
- AGX/IOAcceleratorES publication and the Metal plugin (agents 6/7); the rung panics before userland by design.
- Render streams, IOSurface GPU mapping, CA context selection, blur/vibrancy pixels (agents 7/8).
- Vendor/prior-art confirmation of every disputed layout and lifetime rule (agent 9).
