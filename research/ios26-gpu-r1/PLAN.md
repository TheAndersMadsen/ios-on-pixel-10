# GPU acceleration for iOS on blazer: state, ranked paths, next milestone (2026-11-03)

Labels: **physical** = phone log; **source** = code or vendor header read; **host** = built or run on m1box/Mac;
**inference** = not tested. No phone, adb, fastboot or QEMU action was taken for this document.

## 0. Where iOS is today

- **Physical:** `a7-ios-system-r3` reaches Home. CoreAnimation renders in software and the kernel copies frames to the DPU layer
  (`research/ios26-phaseb-r1/A7.md`).
- **Source/physical:** QuartzCore polls `IOAcceleratorES` 301 times before `MTLCreateSystemDefaultDevice()`, and the call
  returns nil. Metal accepts an `IOAcceleratorES` only when it has a `MetalPluginName` property
  (`research/ios26-phaseb-r1/accel-wait/FINDINGS.md` §2.3).
- **Source:** the kernel already has `hk_accel=1`, which publishes a bare `IOAcceleratorES` with no Metal properties
  (`iokit/Kernel/arm/sweet_services.cpp`). It ends the 30 s poll; Metal ignores the service.

## 1. State of the art, with evidence

### 1.1 Which GPU: Imagination PowerVR DXT, BVNC 71.2.2448.1212

| Evidence | Kind | Where |
| --- | --- | --- |
| `RGX_CR_CORE_ID` = `0x00470002099004bc` read twice on the phone. That is B=0x47 (71), V=2, N=0x0990 (2448), C=0x04bc (1212) | physical | `research/laguna-usb-fix/attempts/20261102-033623-gpu-stage1-r2/ramdump/kernel.log` (Mac), lines 508-526: `PASS core id 0x470002099004bc 0x470002099004bc` |
| The same ID on every later firmware boot | physical | `research/laguna-usb-fix/attempts/20261102-102719-native-metal-health-p29-r1/reader.txt:182` |
| The vendor tree has a core file `rgxcore_km_71.2.2448.1212.h` and a config file `rgxconfig_km_71.V.2448.1212.h` under `hwdefs/volcanic` (Volcanic = the DXT generation): `RISCV_FW_PROCESSOR`, `NUM_SPU 2`, `MMU_VERSION 4`, `PHYS_BUS_WIDTH 40`, `HOST_SECURITY_VERSION 4`, SLC 1536 KiB, no `ERYX_TOP_INFRASTRUCTURE`. BRNs 74812 and 77899 | source | GrapheneOS `google-modules/powervr` @5940a317 (Mac: `research/ios26-metal-r1/dl-gos/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/`) |
| FDT: `gpu0` reg `rgx` 0x34f00000 (1 MiB), GIC SPI 130 level-high; `gpu_core_logic_pd` control 0x3480a000; pfsm 0x34813000; gpu_smmu 0x34c00000; power domain `sswrp_gpu_pd` (sswrp-id 0x14) | source (pinned DT) | `bsd/dev/blazer_gpu.c` header; `research/ios26-metal-native-20261102/firmware-r3/HANDOFF.md` |
| Firmware `rgx.fw.71.2.2448.1212` (344,068 bytes, signed, ABI 41, DDK 26.1@6967606). Trusty TA `com.android.trusty.pixel_gpu` loads it (`gpu-secure-trusty`) | source/physical | `research/ios26-metal-native-20261102/integration/HANDOFF.md`; `integration/CONTRACT.md:13` |
| GPU SMMU (SMMUv3) at boot: `CR0 0`, `GBPA 0` (no ABORT bit, so GPU traffic bypasses the SMMU), `IDR0 0x80f361f` | physical | stage1-r2 kernel.log lines 514-523 |

So the GPU is not Mali and not Apple AGX. It is a 2-SPU PowerVR DXT with a RISC-V firmware core. The firmware is signed, and only
the TEE loads and starts it (`SUPPORT_TRUSTED_DEVICE`: "FW Core Registers not available to REE", `rgxdebug_common.c`).

### 1.2 What the project's GPU and Metal work achieves

| Layer | Achieved | Kind | Where |
| --- | --- | --- | --- |
| Power and identity | CPM vote for sswrp GPU, core-logic gate on, pfsm valid, CORE_ID PASS, gate off, domain off, all during an iOS boot | **physical** | `blazer_gpu=1/2` (`bsd/dev/blazer_gpu.c`), stage1-r2 |
| Trusty transport | Connects to the GPU TA. PING works. `SEND_FIRMWARE_IMAGE` result 0 (the TA took the image). Our shared data written. `SMC START` -> 0 | **physical** | `blazer_gpu_tipc=1..5` (`bsd/dev/blazer_gpu_tipc.c`); attempts `…-native-metal-send-p29-r1`, `…-health-p29-r1`, `…-health-p30-a725-diag-r1` |
| Firmware boot | `bFirmwareStarted 1` with a timestamp. The firmware **reads** the KCCB health command (`kccb w 1 r 1`) but never **executes** it. FW connection state stays **0 (OFFLINE)**; the OS side is 1 (READY). `sys.pow 1`, `fw_faults 0`, `hwr_flags 0x1` (HARDWARE_OK). One FWCCB entry is pending: `DEBUG_DUMP`, payload zero. The TA logs `RGXValidateFWHeaderVersion2: KM and FW version mismatch (expected: 24.2, found: 26.1)` / `process_st_info() failed (278)` on every SEND boot | **physical, FAIL** | `docs/NATIVE-METAL.md`; p29 health reader.txt:200-241; p30 diag reader.txt:204-221 |
| Kernel driver pieces (IRQ/MISR, DXT MMU v4 page tables, VA heaps, KCCB/queue/fences, HMGU user client, IOSurface import) | gated ARM64 objects and host tests on models; never run against firmware | host | `research/ios26-metal-native-20261102/{firmware-r3,vm-r3,queue-r5,uc-r5,kernel-release-integration-r1}` |
| Shader toolchain | AIR/metallib frontend; owned DXT ISA encoding for a compute subset (`native/metal/isa`, owner's uncommitted work in progress); PDS/CDM control streams (`native/metal/streams`) | host | `native/metal/*/README.md` |
| Metal runtime | `HMNativeMetal.bundle` (principal class `HMNativeMetalDevice`, loader, HMGU IOKit transport, compiler glue) builds for iOS arm64 | host link only; never loaded by iOS | `native/metal/runtime` (untracked) |
| Render/compositor | none on the GPU. hgltrack (`research/ios26-gpugl-r1`, Mac) is CPU-side GL/CA tracking and sampling, not GPU execution | — | — |

No GPU job has ever run. No shader result has been read back.

### 1.3 What is missing between that and iOS's Metal/IOAccelerator stack

1. **Firmware health.** This is the blocker for everything below. The firmware boots but never moves its connection out of
   OFFLINE and never executes a KCCB command. The cause is not known yet. Inferred candidates, none tested: (i) the OS-online
   handshake, i.e. the firmware's view of our OS in `aui32OsRuntimeFlagsMirror[0]`; stock sends `OS_ONLINE_STATE_CONFIGURE`
   in some modes (`RGXFWSetFwOsState`, rgxfwutils.c:6121); (ii) something we leave zero that stock fills: config flags, the
   trace buffer, register config, the fabric vote and SLC setup, all listed in `blazer_gpu_tipc.c:240`; (iii) the TA's
   failed `process_st_info`; (iv) a firmware poll stuck on a register we never powered (`aui32CrPollAddr`).
2. **Interrupts.** GIC SPI 130 has no IOKit route: SweetPlatformExpert excludes the GIC nub, so `IOAcceleratorES` has no
   interrupt array (firmware-r3 HANDOFF). Polling is possible, interrupts are not.
3. **GPU MMU and memory.** The TEE premaps the firmware heaps. Per-context DXT MMU v4 page tables (16 KiB pages, 40-bit) are
   host-tested only. Their publication to the firmware (memory context registration over the KCCB) has never run.
4. **Command submission.** The KCCB kick is proven to be consumed, not executed. The CDM compute context, CCB, fence and
   completion path are host models (queue-r5).
5. **The Metal ABI iOS expects.** Metal loads the bundle named by `MetalPluginName` on an `IOAcceleratorES`-class service
   (source, FINDINGS §2.3). Inference, not checked in this repo: the device then runs Apple's private
   `MTLIOAccelDevice`/IOGPU user-client protocol (device, shared and command-queue user clients, resource and shmem
   selectors). Our HMGU is a private ABI of its own, so either the bundle supplies its own `MTLDevice` class that Metal
   accepts, or the kernel speaks Apple's selectors.
6. **IOSurface sharing with the display.** Today CA draws into IOSurfaces in software and the kernel CPU-copies them to the DPU
   layer (`hk_fb_*`). GPU rendering needs IOSurface pages mapped into the GPU MMU (HMGU surfaces: host only; IOSurface 1202
   returns int/BUSY) and then either a scanout of the surface itself (DPU SMMU in bypass, physically contiguous or
   DPU-translated) or a GPU blit into the scanout buffer. Fences must order the GPU write before the DPU read.
7. **Power management.** DVFS through CPM, APM idle and power-off handshakes, thermal throttling. Today: `blazer_gov`
   (CPU only).

## 2. Ranked paths

| Rank | Path | Effort | Risk | What it buys | Next milestone |
| --- | --- | --- | --- | --- | --- |
| **1** | **(b) Real GPU kernel driver**, ported from the stock module's behaviour (TEE firmware start, then the shared-data contract, KCCB, contexts, MMU, CDM) | Very high: months of single-shot physical boots. Power, Trusty transport and firmware start run on the phone; IRQ, VM, queue and user-client pieces exist only as host-tested code | High: the firmware and TEE are black boxes; we only see the shared memory and the REE-visible registers; every attempt ends its boot | The only path to real acceleration; (c) depends on it | **Firmware health PASS.** First this survey (M1, built), then the rung-5 shared-memory decode (M2) to learn why the connection stays OFFLINE, then one evidence-driven fix |
| 2 | (c) Native Metal driver bundle mapping the ISA work | Very high: compute first, then render (VDM/PPP/ISP, formats, FBCDC) and CA's whole shader set | Medium on host; high for compatibility with Apple's private Metal runtime | Metal for apps, and later for CA | Keep it host-side: an owned compute kernel compiled and encoded end to end on the host and checked against an oracle. It is not provable on the GPU before (b) passes health |
| 3 | (a) Minimal IOAccelerator/IOGPU service with a software or limited backend so that `MTLCreateSystemDefaultDevice()` succeeds | Medium for a device that exists, very high for one that works (a CPU Metal implementation of CA's shaders) | High: once the device is non-nil, CA moves compositing onto it, and any unimplemented selector crashes backboardd (black screen, as with the CoreBrightness crash) | No speed-up (CPU either way). Plumbing only | Do not expose one to CA. Keep `hk_accel=1`/`hk_accel_once` for the 30 s. Revisit as the transport for (c) once (b) runs a job |

Why (b) comes first: (a) without a GPU only moves the software rasterizer into a worse place, and (c) has nothing to run on.
The ISA and runtime work keeps its value, but its acceptance (`docs/NATIVE-METAL.md`) needs a GPU completion that only (b) can
give.

## 3. The milestone built here: M1 `blazer_gpu=3`, a read-only register survey during a normal Home boot

Stage 1 (power on, read the ID registers, power off) already passed on the phone, so this milestone takes the next safe step.
While the core is up and identified, the kernel reads the registers that stock's **REE** debug dump reads with plain
`OSReadHWReg`, and reads `RGX_CR_TIMER` twice 1 ms apart. Then it powers down exactly as stage 1 does.

- What it answers (physical, once run):
  - Does the core's timer tick with our power-up? `CLOCK_RUNS` or `CLOCK_STOPPED`. The firmware's scheduler needs it.
  - Cold-state CLK_CTRL/CLK_STATUS, MMU fault and status, and SLC status. These form the baseline for M2's after-timeout
    snapshot.
  - Can these offsets be read from the REE at all on this boot path? If a read faults, the SError panics the boot (inference).
    That would also show they are not safe for M2.
- What it never does: firmware, Trusty, SMC, a KCCB, a write other than stage 1's two gate writes, the secure bank,
  FWCORE/RISC-V DM registers, MTS registers, or a page beyond the first 64 KiB of rgx.
- Register list and provenance (`src/blazer_gpu.c` `gpu_survey_regs`). Offsets are from `volcanic/km/rgx_cr_defs_km.h`
  @5940a317. Stock reads are in `rgxdebug_common.c` `RGXDumpRGXRegisters` and `volcanic/rgxdebug.c`:
  CORE_ID 0x20; CLK_CTRL0 0x0, CLK_STATUS0 0x8, CLK_CTRL1 0x80, CLK_STATUS1 0x88, CLK_CTRL2 0x90 (`RGXDumpClkRegisters`,
  !ERYX_TOP); EVENT_STATUS 0x130; TIMER 0x160; MMU_FAULT_STATUS_PM 0xe130, MMU_FAULT_STATUS1 0xe150 and 2 0xe158 (no BRN72144
  on this core), MMU_FAULT_STATUS_META 0xe160, MMU_STATUS 0xe170, SLC_STATUS1/2/3 0xe210/0xe218/0xe238, SLC_STATUS_DEBUG
  0xe260 (`RGXDumpMMURegisters`); SLC_IDLE 0xe230, SLC_FAULT_STOP_STATUS 0xe240 (`RGXDumpSLCRegisters`). 64-bit registers
  are read as two 32-bit words, high first, the access CORE_ID already passed with. TIMER is read high, low, high and retried
  at most 3 times.

### Evidence (host)

| Item | Result |
| --- | --- |
| Host test `tests/test_survey.c` (ASan+UBSan, modelled bus that fails on any write but the gate, any access with the domain off, any rgx access gated or before a valid pfsm, any offset outside the reviewed list or the 64 KiB view) | **820 checks, 0 failed, 8 cases** (`receipts/host-test.txt`) |
| Mutants `tests/mutants.sh` (extra offset, rgx write, survey in mode 1, no ID guard, survey after gate-off, timer retry 1 or 9, `>=` for the clock, no delay, wrong width, continue after unstable) | **11/11 caught** |
| XNU branch `hk-gpu-survey-r1` = 7227fe7 (kernel.rootview's commit) + **d30f785** (only `bsd/dev/blazer_gpu.c`), Mac nested repo `research/ios26-release-r1/work/xnu` | committed |
| Build `tools/mk.sh -j8` under the fleet build slot (`tools/with_slot.py`); recompiled `hakios.blazer_ufs.o` (back to 7227fe7) and `blazer_gpu.o` | rc 0, 20 s (`receipts/build-r1.log`) |
| `blazer_gpu.o`: Mach-O arm64; `_gpu_survey` (`__TEXT,__text` 0x720), `_gpu_survey_regs` (`__DATA,__const`), `_blazer_gpu_start`, `_blazer_gpu_power_on`; undefined only the existing kernel imports | `receipts/blazer_gpu.o.nm.txt` |
| Disassembly of `_gpu_survey`: only 32-bit `ldr w` device loads; TIMER as `[x19,#0x164]`, `#0x160`, `#0x164` | `receipts/gpu_survey.dis.txt` |
| Kernel vs kernel.rootview (unstripped `nm`): only `+_gpu_survey`, `+_gpu_survey_regs`; `__TEXT`, `__DATA_CONST` and `__TEXT_EXEC` segment sizes identical | `receipts/symbols-vs-rootview.diff` |
| Release tree restored: p1 b228c4f, clean, rebuilt (obj kernel 2bed2ad6…, not byte-identical to before: the link is not reproducible) | `receipts/restore-p1.sha256` |

Artifacts (Mac `research/ios26-gpu-r1/artifacts/`, not in git):
- `kernel.gpu-survey-r1` `361315b02a60732a19a6769528ab0ab41c005c9e2ae734998b9954553635526d`
- `kernel.gpu-survey-r1.unstripped` `ce69d914417f0b48d4ab68f0177fceb4a403100da42c60ff85da69d4005f80e1`
- `blazer_gpu.o` `796ea99b2cfff7374ef0b6682aea9ae9f54b44a7676f3e099729224b2bcf3abc`

Image `research/images/a7-ios-system-r6-gpu` (Mac and m1box):
- `boot.img` `25ca24fa280176847e9c0fd7cc90f3a28046447fa1ed099edb1aa4f3c679b75d`; `image_tool.py check` OK.
- Recipe `tools/image_r6.sh`: r3's (A7-READY step 6 without `hk_bright=140`) with only `--kernel`/`--kernel-sha` changed and
  `blazer_gpu=3` appended. Manifest diff against r3: cmdline differs only by `+blazer_gpu=3` (999 -> 1012 bytes, same order).
  The other differences are the build's own: kernel, payload, nonce, epoch, ADT seed, and the image_tool hash.
- image_tool needed one allowlist line, `PHONE_ALLOWED.update({'blazer_gpu': r'blazer_gpu=3'})`
  (`receipts/image_tool-allow-blazer_gpu.diff`). The image was built with HEAD 8934a65 plus that hunk only (sha 757f0465,
  reproduced). A Wi-Fi owner edited the same file after the build. That edit is not in the image.

### Attended boot (coordinator; owner present; one variable vs r3)

```sh
# Mac checkout, ANDROID_SERIAL set, Android up, owner present
adb reboot bootloader
tools/bootios research/images/a7-ios-system-r6-gpu/boot.img a7-ios-system-r6-gpu \
  --mach research/ios26-gpu-r1/artifacts/kernel.gpu-survey-r1.unstripped --wait 480
fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-r6-gpu-after-boot
python3 -I tools/all_decode.py <attempt>/ramdump/kernel.log research/images/a7-ios-system-r6-gpu/manifest.json
grep -a 'blazer-gpu' <attempt>/ramdump/kernel.log
```

Pass, all of:
1. `blazer-gpu: stage 1 in 30 s`, then `vote 1 … 0x12`, `domain on`, `core logic on`, `pfsm status 0x2b` (as in stage1-r2),
   `PASS core id 0x470002099004bc 0x470002099004bc`.
2. 18 lines `blazer-gpu: reg <NAME> +0x<off> 0x…`, then `blazer-gpu: CLOCK_RUNS timer A -> B, +N in 1000 us` with N > 0,
   then `survey done, 18 registers`.
3. `core logic off`, `vote 0 … 0x11`, `domain off, done`.
4. The owner sees Home as in r3 (touch works, Settings opens). The only panic is the designed `blazer-root: deadline 300 s`.
   Return check PASS.

Results that are a finding, not a failure: `CLOCK_STOPPED` (the timer does not tick with our power-up, a lead for the firmware
stall); `TIMER UNSTABLE`. Stop and do not repeat: any other panic or SError during the survey (an offset is not readable from
the REE on this path), no `domain off, done`, Home lost compared with r3, or a failed return check. Rollback: the PSCI
reset at the deadline goes back to fastboot; nothing is written anywhere.

Decode the `reg` lines with `rgx_cr_defs_km.h` (CLK_STATUS0 RUNNING/GATED bits, MMU_FAULT_STATUS1 fault bit, SLC_IDLE). Keep
raw values and meaning apart.

## 4. Next milestones (not built)

- **M2: rung-5 shared-memory decode** (host first, then the p30-a725-diag line at cpus=1). The rung requires cpus=1, so this
  cannot ride on the r3 line. At the existing health timeout, before the existing panic, also print the firmware-written fields
  the diagnostic does not read yet. Offsets were measured from the pinned headers by `tools/fw_layout_r1.c`
  (`receipts/fw-layout-r1.h`), and they agree with the existing anchors FW_FAULTS 0xdb0 and HWR_FLAGS 0xde8:
  SYSDATA `aui32OsRuntimeFlagsMirror[0]` +0xc (OS state = bits 0..2), `aui32CrPollAddr/Mask/Count[0]` +0xdb4/+0xdb8/+0xdbc,
  `sFaultInfo[0]` path +0x48, info +0x110, line +0x1d8; TRACEBUF `sAssertBuf` path +0x18, info +0xe0, line +0x1a8,
  `ui32TracePointer` +0x8; sizes SYSDATA 0xf30, TRACEBUF 0x1b8. Add the M1 survey after the timeout (MMU_FAULT_STATUS1 shows
  a GPU MMU fault by the firmware). These are reads of memory our kernel allocated and of registers M1 proved readable. One boot
  answers: is the firmware stuck in a CR poll (address), did it assert (file:line), or does it see our OS as offline?
- **M3:** one evidence-driven fix from M2. Then health PASS, then `docs/NATIVE-METAL.md` acceptance (owned compute shader,
  real GPU VM, completion, readback).
- **Read-only Android comparison** (coordinator, below): stock's debug dump and the Trusty log on a running Android. Do they
  also log `process_st_info() failed (278)`? If they do, that line is benign.

## 5. Read-only adb commands for the coordinator (Android up, rooted; nothing written)

```sh
adb shell su -c 'dmesg' | grep -iE 'gpu-secure|ValidateFWHeader|process_st_info|pixel_gpu|pvr|rgx' | head -200
adb shell su -c 'for f in $(find /proc/device-tree -name compatible | grep -iE "gpu|rgx"); do echo "$f: $(tr "\0" " " < "$f")"; done'
adb shell su -c 'cat /proc/modules | grep -iE "pvr|pixel_gpu"; cat /sys/module/pvrsrvkm/version /sys/module/pvrsrvkm/srcversion 2>/dev/null'
adb shell su -c 'ls /sys/kernel/debug/pvr/ 2>&1; cat /sys/kernel/debug/pvr/version /sys/kernel/debug/pvr/status 2>&1 | head -80'
adb shell su -c 'cat /sys/kernel/debug/pvr/debug_dump 2>&1 | head -400'
adb shell ls -la /vendor/firmware | grep -iE 'rgx|gpu'
```

The `debug_dump` read makes the stock driver run its own debug dump: it reads the live GPU registers and the firmware
state, and writes nothing to storage. It gives stock's running values for the same 18 registers and the firmware's OS
connection state, the reference for M1 and M2. Skip it if the coordinator treats a driver-side dump as too active.

## Files

- `src/blazer_gpu.c` (= Mac branch commit d30f785), `src/blazer_gpu.c.base` (7227fe7), `receipts/blazer_gpu.c.diff`.
- `tests/blazer_gpu_test.h`, `tests/test_survey.c`, `tests/mutants.sh`.
- `tools/build_r1.sh`, `tools/with_slot.py` (fleet build slot, non-blocking), `tools/image_r6.sh`, `tools/fw_layout_r1.c`,
  `tools/measure_fw_layout.py` (Mac).
- `receipts/` : build, nm, disassembly, symbol diff, layout, host test, image log, sha256 lists.
