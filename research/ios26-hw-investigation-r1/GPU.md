# GPU investigation: the Liquid Glass render path, from firmware to Metal

Date: 2026-11-03. Scope: Tensor G5 / Pixel 10 Pro, PowerVR DXT BVNC 71.2.2448.1212 (not AGX/Mali).
This is a read-only source and receipt review. No kernel source, build, phone, Git index, or device state was changed.

Evidence labels are **SOURCE**, **HOST**, **QEMU**, and **PHYSICAL**. Source line references prefixed `xnu/` are at nested-XNU branch `hk-gpu-m2-r1` (`58f0893`), the branch used for the gpu2 kernel; the nested checkout is currently on another branch. M3 references are to the uncommitted files under `research/ios26-gpu-r1/m3/`.

## 0. RENDER PRIORITY — the owner's visible outcome

The highest-value chain is not “run a shader” in isolation. It is:

**firmware up (done, with an init fault to remove) → coremem `0x150` fix → client command ring/KICK → real render submission/completion → publish a working `AGXAccelerator` with a Metal plugin → backboardd/SpringBoard obtain a Metal device → CoreAnimation/QuartzCore executes the glass/blur/vibrancy passes on the GPU → DPU presents the completed IOSurface.**

Live int3 evidence localizes the visible gap precisely:

- Scanout is alive: `AppleCLCD` initializes and backboardd opens/matches it (`research/laguna-usb-fix/attempts/live-20261103-232046-a7-int3/console.txt:125,1393-1416`). Text and glyphs can therefore render on the CPU while the GPU path is absent.
- No accelerator service exists: backboardd gets `IOAcceleratorES -> 0 found` and `AGXAccelerator -> none` (`:1423,1459,1490`); SpringBoard also gets `AGXAccelerator -> none` and `IOAcceleratorES -> 0 found` (`:2244,2323`).
- Metal creation fails: SpringBoard logs `SUICOrbView ... Failed to get Metal device for GPU rendering` (`:2329`).
- The renderer falls back to software: `HGLTRACK: SWContext slot wrapped` (`:889`). This is the flat-glass path, not evidence that blur/vibrancy executed on a GPU.

The required end-state is **three correlated changes**, not three cosmetic log edits:

1. `AGXAccelerator` and `IOAcceleratorES` matches resolve to the same ready native service, with `MetalPluginName` present.
2. The Metal-device failure disappears and an owned probe plus backboardd/SpringBoard report a real `HMNativeMetalDevice`; context tracking names the actual GPU-backed context rather than selecting `SWContext` for composition.
3. That context submits and completes real render work before AppleCLCD/DPU presents it. Known-pixel tests and the owner's glass/blur/vibrancy check confirm correctness. A non-nil device, a changed context log, or ordinary DPU frames alone is not success.

## 1. WHAT IT DOES TODAY

### 1.1 Kernel entry points, power, identity, and register health

- `xnu/bsd/kern/bsd_init.c:765-769` calls both `blazer_gpu_start()` and `blazer_gpu_tipc_start()`. Both are off unless their boot argument is present. The Trusty rung requires `cpus=1` and refuses to coexist with `blazer_aoc` or `blazer_gpu`, so there is one Trusty client and one GPU experiment per boot (`xnu/bsd/dev/blazer_gpu_tipc.c:944-974`).
- `xnu/bsd/dev/blazer_gpu.c` owns the REE-visible hardware sequence:
  - `gpu_vote()` sends the CPM/LPB GPU domain request and waits for its event (`:192-234`).
  - `gpu_gate()` controls the core-logic gate (`:236-249`). `gpu_proof()` maps the PFSM/RGX views, checks PFSM validity, reads CORE_ID twice, and powers back down (`:251-296`).
  - `blazer_gpu_power_on()` is the firmware rung's leave-powered-on variant (`:299-329`). `gpu_survey()` reads 18 reviewed clock/MMU/SLC registers and checks that the timer advances (`:107-188`); `blazer_gpu_survey_live()` exposes it after firmware execution (`:331-340`).
- The pinned FDT agrees with those constants: RGX `0x34f00000`/1 MiB, PFSM `0x34813000`, GIC SPI 130 level-high, GPU SMMU `0x34c00000`, SSWRP id `0x14`, core-logic control `0x3480a000`, and a 33 MiB no-map firmware carve-out at `0xb9f00000` (`research/ios26-dualboot-r8/truth/fdt.dts:939-943,15680-15692,31484-31517,31675-31689`). The FDT also describes APM/DVFS capabilities; those are not implemented by the current XNU path.

**PHYSICAL PASS:** stage1-r2 powered the domain, read the expected CORE_ID twice, found the GPU SMMU in global bypass (`CR0=0`, `GBPA=0`), and powered down cleanly (`research/laguna-usb-fix/attempts/20261102-033623-gpu-stage1-r2/ramdump/kernel.log:508-526`). M1 later repeated the ID check, completed all 18 reads with no REE-visible MMU fault, measured `CLOCK_RUNS +1763/ms`, and powered down cleanly (`research/laguna-usb-fix/attempts/20261103-193846-a7-ios-system-r6-gpu/ramdump/kernel.log:4666-4694`; ledger verdict at `research/ios26-phaseb-r1/LEDGER.md:38`).

### 1.2 Firmware image and Trusty transport

- `xnu/bsd/dev/blazer_gpu_fw.c:3-15` embeds the pinned, signed firmware with `.incbin`; it is passed to Trusty unmodified. No firmware bytes belong in research documents.
- `gta_fw_check()` validates the container, ABI, BVNC, version, and section layout before anything is sent (`xnu/bsd/dev/blazer_gpu_tipc.c:121-172`).
- The Trusty implementation reuses the polled AOC transport with port `com.android.trusty.pixel_gpu` (`xnu/bsd/dev/blazer_gpu_tipc.c:15-22`). `gta_ping()` checks the reply shape and result (`:53-74`). `gta_log_add()` / `gta_log_dump()` expose the TA's shared log without making another secure call during failure handling (`:826-891`).
- `gta_send_firmware()` zeroes only the private firmware area, copies the image/header, constructs `SEND_FIRMWARE_IMAGE`, and requires the matching result-0 reply (`:196-241`). `gta_rung4()` then initializes shared memory, powers the GPU, issues SMC START, and waits for `bFirmwareStarted` (`:708-788`).

**PHYSICAL PASS:** gpu2 connected to the TA, installed its log channel, sent the firmware successfully, powered and identified the core, and received `SMC START -> 0x0` (`research/laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/reader.txt:162-177,201,247-253`). The TA still reports its known 24.2/26.1 validation message and `process_st_info() failed (278)` (`:479-480`). M2 source comparison shows the version message has a stock-side 26.1 workaround; neither TA message has been shown to cause the init fault (`research/ios26-gpu-r1/M2.md:48-54`).

### 1.3 Shared firmware data, KCCB health, and diagnostics

- `gta_shared_init()` creates the connection, OSINIT/SYSINIT, KCCB/FWCCB rings and return slots, fault/trace buffers, runtime configuration, and firmware pointers in the uncached shared heap (`xnu/bsd/dev/blazer_gpu_tipc.c:314-392`).
- M2 deliberately follows native stock behavior rather than the old rung-5 criterion: HEALTH_CHECK is judged by consumption; the following no-op STATEFLAGS_CTRL must write `CMD_EXECUTED` in its return slot (`gta_kccb()` and `gta_m2()`, `:635-706`). Each KCCB publication ends with the GP MTS doorbell at RGX `+0xb00` (`:40,263,654-655`). Connection-field values and HEALTH_CHECK consumption alone are not execution proof.
- `gta_m2_state()` prints OS runtime flags, power/fault/HWR state, CR polls, asserts, ring positions, and return slots (`:569-602`). `gta_m2_fwlog()` emits the firmware trace for offline decoding (`:604-630`). The read-only FWCCB diagnostic never acknowledges or advances the firmware ring (`:417-465`).
- Every rung ends in a deliberate panic after the result; it does not return to a running iOS userland (`:925-938`). There is no normal firmware STOP, GPU gate-off, or domain-off on this path.

**PHYSICAL PASS, with an important qualification:** gpu2 consumed HEALTH_CHECK, executed STATEFLAGS_CTRL with return `0x1`, reported OS0 ACTIVE, zero firmware faults, empty assert, and a running timer, then panicked on purpose (`reader.txt:284-319,440-442,481-492`). This proves firmware command execution after recovery. It does **not** prove clean firmware initialization, a client command stream, GPU engine work, or Metal. The boot stopped before launchd (`reader.txt:4,23`).

### 1.4 The init fault is real even though health eventually passes

The gpu2 firmware log starts with an MMU fault and lockup before the successful health commands. The raw entries are at `reader.txt:345-419`; decoding them with `research/ios26-gpu-r1/m2/tools/fwlog_decode.py` yields, in order:

1. `RGXFW_SF_HWR_CORE_MMU_FAULT`: MMU page fault (the backlog's decode identifies META DMA at address 0).
2. `RGXFW_SF_MAIN_HWR_HIT_LOCKUP`: GPU-0 locked up.
3. Hardware reset and repeated failed hardware polls, followed by DM recovery.
4. Only afterward, KCCB slot 0 HEALTH_CHECK and slot 1 STATEFLAGS_CTRL execute.

The concise finding is recorded at `docs/debug/backlog-notes.json:65`; the PHYSICAL health verdict is at `research/ios26-phaseb-r1/LEDGER.md:43`. Therefore “firmware health PASS” and “firmware had no init fault” are different claims.

The strongest source-backed explanation is the zero coremem data-store DMA address. M2 zeroes SYSINIT and never fills `sCorememDataStoreDeprecated`; stock fills it in `RGXSetupFwSysData`. The pinned-layout measurement places it at SYSINIT `+0x150` (`research/ios26-gpu-r1/m3/receipts/fw-layout-r3.h:1-6`) and the coremem data section at carve-out offset `0x13c000` (`m3/src/blazer_gpu_tipc.c:86-120`). The required raw-heap device address is therefore `0xE1C0000000 + 0x13c000 = 0xE1C013C000`. This is a well-supported diagnosis, but remains unverified until a fixed boot has no init MMU fault/HWR.

### 1.5 Userland acceleration and `AGXAccelerator` today

- There is no GPU work in the Home path; CoreAnimation uses software rendering and the existing DPU scanout/copy path (`research/ios26-gpu-r1/PLAN.md:6-14`). AppleCLCD is the display driver, not the accelerator.
- `hk_accel=1` can publish a bare `IOAcceleratorES`, but it has no `MetalPluginName` and no user client (`xnu/iokit/Kernel/arm/sweet_services.cpp:1-27` at `hk-int3`). Metal ignores it. QuartzCore otherwise polls for the class and `MTLCreateSystemDefaultDevice()` returns nil (`research/ios26-phaseb-r1/accel-wait/FINDINGS.md:12-17,100-103`). The int3 image also uses `HK_ACCEL_ONCE=skip`, which skips the 30-second poll but does not create a device (`console.txt:222,720,889-890`).
- On Apple hardware, `AGXAccelerator` belongs to Apple's proprietary `AppleAGXGraphics` driver family. That driver targets Apple's AGX firmware/hardware contract and cannot drive this PowerVR DXT. **No implementation or personality in this XNU tree publishes `AGXAccelerator`**. It must come from our native built-in accelerator driver, not from loading Apple's AGX kext or renaming AppleCLCD.
- The intended native publication code already exists as a HOST-reviewed candidate: `sweet_accel_publish_native()` in `research/ios26-metal-native-20261102/metal-r2/integration/sparse/iokit/Kernel/arm/sweet_services.cpp` creates one service, and `hmnp_publish_service()` in `metal-r2/src/hmnp_xnu.cpp:48-64` sets `MetalPluginName` / `MetalPluginClassName` only after a readiness lease. Its readiness contract requires live firmware, usable VM/context/builders, authentic engine completion/cache handback, and a complete native-stage validator—not merely a HEALTH or KICK result (`metal-r2/notes/INTEGRATION.md:16-39`).
- The matching runtime is `HMNativeMetal.bundle`, principal class `HMNativeMetalDevice` (`native/metal/runtime/Info.plist:4-10`). Metal's normal loader opens the named bundle and calls `initWithAcceleratorPort:`; no swizzle or manual `MTLAddDevice` is needed (`metal-r2/notes/INTEGRATION.md:41-45`). The current runtime is explicitly compute-only/headless (`native/metal/runtime/src/HMNativeMetal.m:144-187`), so it is not yet a CoreAnimation renderer.
- VM, queue, ISA/stream, HMGU, runtime-bundle, IRQ, and surface work has HOST tests and enabled-gate ARM64 object checks, not physical execution. The accepted next requirements are an owned compute shader, real GPU VM, actual completion/cache synchronization, and output/guard-word readback (`docs/NATIVE-METAL.md:12-24`).

## 2. WHAT'S MISSING

### 2.1 M3 is a design and partial helper delta, not a runnable rung 7

The comments in `research/ios26-gpu-r1/m3/src/blazer_gpu_tipc.c:11-17` describe the right next experiment, but the implementation is not wired:

- The only coremem store is conditional on `gta_m3_coremem` (`:400-403`), and nothing assigns that flag.
- `blazer_gpu_tipc_start()` still accepts only rungs 1 through 6 (`:977-1005`).
- `gta_rung4()` still enables M2 shared data only for `rung == 6` and calls `gta_m2()` only for rung 6 (`:775,801-803`). Merely raising the argument limit would disable the trace setup and could produce an empty/misleading PASS.
- `gta_kccb_cmd()` can now carry a KCCB payload (`:657-705`), but no caller constructs a KICK. There is no `gta_m3()` implementation, memory/common-context construction, client CCB encoder, UFO wait, or S1-S4 result path. `m3/tests/` is empty.
- The measured constants needed for that implementation do exist: firmware memory/common context layouts, CCB/UFO/KICK fields, command values, invalid PC register-set value, raw heap base, and relevant trace IDs (`m3/receipts/fw-layout-r3.h:7-85`; provenance for each is in `m3/tools/fw_layout_r3.c:21-114`).

### 2.2 Gap from health to the first firmware client command stream

After clean health, the minimum useful proof is a GP-DM KickSync stream, not a shader. It needs all of the following in `m3/src/blazer_gpu_tipc.c`:

1. A firmware memory context referencing an allocated, zeroed page catalogue (all translations invalid), with `uiPageCatBaseRegSet = RGXFW_BIF_INVALID_PCSET`.
2. A GP-DM firmware common context with firmware pointers to that memory context, an 8 KiB client CCB and its control block, the META DMA address of the CCB, and the stock compatibility/DM fields.
3. Correct address forms: raw device/DMA addresses for page catalogue and CCB DMA fields; uncached firmware-region pointers for CCB/control/context pointers. These must use the measured RISC-V address conventions, not host virtual or physical addresses.
4. FENCE + NULL + UPDATE client commands with 16-byte headers, payload sizes excluding the header, 8-byte alignment, bounded job references, and the CCB write offset/wrap mask published only after the complete stream is visible.
5. KCCB KICK payloads naming the common context and updated CCB write/wrap values, followed by the existing GP MTS doorbell. KCCB consumption is not enough.
6. Firmware-only evidence of execution: a UFO begins as a host-written sentinel; firmware UPDATE changes it to value 1. A second stream's FENCE depends on value 1 and its UPDATE writes value 2. Timeouts, FWCCB reset/page-fault/debug notifications, and trace HWR events are failures, not completion.

That experiment deliberately executes no GPU hardware job and maps no user buffer. It proves firmware context admission, client-ring parsing, fence evaluation, update writes, and ordering only.

### 2.3 Gap from KickSync to compute, `AGXAccelerator`, and Liquid Glass

- **Real compute:** a CDM context, real DXT MMU-v4 mappings and MMU-cache publication, owned PDS/CDM control streams, resource lifetime, cache synchronization, engine completion, and sentinel/output/guard readback. Existing host models do not supply physical proof.
- **Real rendering:** compute does not imply rasterization. The renderer needs VDM/PPP/PDS vertex and fragment stages, render-target layout and cache rules, texture/transfer paths, render completion, and readback. The existing first render contract is deliberately narrow: clear, triangle, and quad into BGRA8, then texture-to-buffer readback with exact pixels and guards (`research/ios26-metal-native-20261102/validation-r3/messages.md:8-43`).
- **Interrupts:** polling is sufficient for the bounded rung. A service-quality driver needs the actual GIC/IOKit route. SweetPlatformExpert currently lacks the resolved GIC nub/provider and IOAcceleratorES interrupt arrays; the IRQ implementation explicitly returns unavailable rather than inventing a vector (`research/ios26-metal-native-20261102/firmware-r3/HANDOFF.md:59-75`).
- **Live VM/security authority:** FDT SID/idmapped properties and REE SMMU bypass do not prove secure-world stream ownership. VM-r3 keeps production route admission unavailable pending live NS/SID/exclusion and legitimate execution-base evidence (`research/ios26-metal-native-20261102/vm-r3/HANDOFF.md:77-99`). Do not bypass that gate with a success callback.
- **Service identity and Metal ABI:** the current candidate publishes only `IOAcceleratorES`; the int3 logs prove backboardd/SpringBoard also look for `AGXAccelerator`. One native service must satisfy both lookups, carry `MetalPluginName`, and implement the HMGU user client. The runtime must provide a Metal-accepted `_MTLDevice`; a stub would expose unimplemented selectors to backboardd (`research/ios26-gpu-r1/PLAN.md:60-80`).
- **Compiler/runtime readiness:** `HMNativeMetalDevice` refuses initialization without configured compiler/streams and a successful HMGU OPEN/capability negotiation (`native/metal/runtime/src/HMNativeMetal.m:144-164`). It currently has compute buffers/queues only and reports `isHeadless=YES`; concrete render PSOs, textures, render/blit encoders, and IOSurface presentation remain unavailable (`validation-r3/HANDOFF.md:13-32`).
- **Presentation:** IOSurface pages must be mapped/pinned for GPU use, completion must precede DPU reads, and known rendered pixels must reach scanout. A sync-only UFO plus ordinary DPU frames is not Metal drawing.
- **Lifecycle/power:** malformed-input rejection, missing-completion handling, pending-work teardown, repeated create/destroy, secure STOP/reset, DVFS/APM/thermal policy, and Android-return validation remain unproved.

### 2.4 Is a minimal accelerator reachable before a full Metal pipeline?

**Yes as a staged render profile, but not immediately after the command ring, and not as a device-only stub.** There are two different minimals:

1. **Compute device minimal:** after clean firmware, KickSync, real VM/CDM submission, authentic completion/cache handback, and the runtime compiler/readiness contract, the existing native service could hand out a compute-only Metal device. This is useful for owned validation and can prove the registry/plugin loader. It is not safe to advertise to CoreAnimation: `SUICOrbView` may stop logging “failed to get Metal device,” only to fail later on render/texture/encoder selectors.
2. **Basic-compositing minimal:** before implementing all of Metal, implement the exact CA path incrementally: command queues and fences; shared/private buffers and BGRA8 textures; vertex/fragment PSOs; clear/store, viewport/scissor, triangle/quad draws; texture upload/sampling and blending; offscreen color attachments; blit/readback; IOSurface import and completion ordering. First pass the existing clear/triangle/quad oracle, then add the measured QuartzCore shader/passes needed for blur and vibrancy. Unsupported selectors must return an explicit error rather than crash or silently draw flat. This is a viable intermediate target, but it still requires real render execution and a working compiler—not just firmware, KCCB, or a non-nil device.

The safe publication order is **owned compute probe → owned render probe → CA in a test/owned process → backboardd/SpringBoard**. Do not use backboardd as the first render test.

`docs/probes.yaml:363-380` currently calls a generic “command stream done” plus DPU completions a possible Metal works/partial row. For this investigation, the stricter `docs/NATIVE-METAL.md:19-24` acceptance governs: rung-7 KickSync must not be reported as native Metal.

## 3. FIX PATH

### Step 1 — Make and verify the coremem-only correction before any client kick

Files/functions: `research/ios26-gpu-r1/m3/src/blazer_gpu_tipc.c`: `blazer_gpu_tipc_start()`, `gta_shared_init()`, `gta_rung4()`, `gta_m2()`; keep `hmfw_m3_layout.h` generated from the pinned layout probe.

1. Set `gta_m3_coremem = (on == 7)` before starting the thread. Rung 8, if needed as a regression control, is the same command-stream path with this flag false.
2. Keep M2 tracing/shared setup active for rungs 6-8 (`gta_shared_init(rung >= 6)`), and dispatch rungs 7/8 through `gta_m2()` rather than letting them fall through to a vacuous PASS. Defer the final trace/register dump until after the client-stream result only when health passed.
3. In `gta_shared_init()`, write the 64-bit value `GTA_DEVVA_HEAP + GTA_OFF_CDATA` at `HMFV3_SI_COREMEM_DATA_STORE` before the final barrier and before SMC START. Assert at build/host-test time that the offset is `0x150`, raw heap base is `0xE1C0000000`, coremem offset is `0x13c000`, and the result is `0xE1C013C000`; refuse a different firmware/layout identity.
4. Add host tests in the currently empty `m3/tests/`: field value and write ordering, rung-7 versus rung-8 behavior, M2 trace still enabled, no KICK after failed health, bounded payload/ring offsets, and no success on timeout. Re-run M2 tests. Then emit enabled-gate ARM64 objects and inspect expected symbols; syntax-only or an empty guarded translation unit is insufficient.

**Physical gate S1 (must pass before S2):** one short rung-7 boot must show HEALTH consumption and STATEFLAGS execution, and its decoded pre-health trace must contain no CORE_MMU_FAULT, HIT_LOCKUP, or FAILED_HW_POLL. Expect no init DEBUG_DUMP, zero firmware faults, and empty assert. A health PASS after another HWR is a failure of this fix; stop rather than proceeding to a client stream or retrying unchanged.

**Proof tools:** `tools/live_boot.sh` / `hk boot` captures timestamped console and panic evidence; `hk logs --grep 'HK GPUTA|blazer-gpu'` extracts it. Decode the current boot's `M2 TB` records with `m2/tools/fwlog_decode.py` and the pinned `rgx_fwif_sf.h`. `hk crash` / `tools/crashdoc.py` must classify only the deliberate rung-PASS panic as intended. `qemu_preflight` cannot test this step: it drops `blazer_gpu*` as phone-only and QEMU has no Tensor GPU/Trusty firmware (`tools/qemu_preflight.py:1-28,54-66,162-179`).

### Step 2 — Build the empty-memory-context GP common context and CCB

Files/functions: add a bounded `gta_m3_context()` helper in `m3/src/blazer_gpu_tipc.c`, using `gs_alloc()`, `gs_ptr()`, `gs_w32()/gs_w64()` and constants from `hmfw_m3_layout.h`.

1. Allocate and retain for the whole rung: a zeroed `GTA_PC_BYTES` page catalogue, `RGXFWIF_FWMEMCONTEXT`, `RGXFWIF_FWCOMMONCONTEXT`, `RGXFWIF_CCCB_CTL`, 8 KiB CCB, and the UFO word/page.
2. Fill the memory context's page-catalogue device address and invalid register-set value. Fill the common context's CCB/control/context firmware pointers, CCB META DMA address, GP DM, `HAS_DEFER_COUNT`, bounded process name, and zero/default priority, state, cleanup, and framework fields according to the measured layout.
3. Set CCB read/write/dependency offsets to zero and wrap mask to `0x1fff`. Initialize the UFO once to `GTA_UFO_SENTINEL`; after publication the host must never write the two expected completion values itself.
4. Keep every translation invalid. This is intentional containment: any attempt to turn the sync-only context into engine work without real VM mappings must fail closed.

Host proof: byte-exact fixtures for every structure and both address forms; invalid offsets/wrap masks and overflow must be rejected. Model firmware, not the host test, performs UPDATEs. Test retained ownership on every timeout/failure exit.

### Step 3 — Emit and kick the two ordered client streams

Files/functions: add `gta_m3_ccb_cmd()` and `gta_m3()` in `m3/src/blazer_gpu_tipc.c`; reuse `gta_kccb_cmd()` for KCCB slots 2 and 3 after M2's slots 0 and 1.

1. For stream 1 encode FENCE(expect sentinel) + NULL + UPDATE(write `GTA_M3_V1`). Publish the complete CCB and barriers, then its control write offset. Construct KICK with the common-context firmware pointer, updated write offset, wrap mask, and zero cleanup count; publish KCCB and ring the GP MTS doorbell.
2. Bound both KCCB consumption and execution. Read back the client CCB's firmware progress and wait at most `GTA_M3_FENCE_MS` for UFO value 1. Do not send stream 2 behind an unread first KICK.
3. For stream 2 encode FENCE(expect value 1) + NULL + UPDATE(write `GTA_M3_V2`), then repeat the publication. PASS only when value 2 arrives after value 1 and no context-reset/FW-page-fault/GPU-restart notification, new MMU fault, lockup, assert, or unplanned panic occurred.
4. Print distinct S1-S4 evidence: S1 clean health; S2 context/first KICK consumed; S3 first UPDATE; S4 fenced second UPDATE. Only S4 may produce `rung 7 PASS`. Dump the trace and register survey on both success and failure. Do not acknowledge FWCCB messages without a real dispatcher.

**Proof tools:** live console supplies KCCB/CCB/UFO stages and the intentional final panic; the firmware-log decoder supplies independent KCCB execution, UFO_CHECK/UFO_UPDATE, and HWR evidence. crashdoc distinguishes an intentional PASS panic from a STOP or unrelated crash. HK USTACK is not applicable to this pre-launchd rung. QEMU is not evidence for this step. After the boot, the coordinator must return to Android and run the normal return check.

If rung 7 regresses, rung 8 (same stream, coremem left zero) isolates the two changes. If rung 7 passes, no control boot is needed before host work on compute.

### Step 4 — Convert the proven firmware path into one owned compute job

1. Integrate the reviewed VM/queue/lifecycle sources as one composition; do not mix unreviewed UC profiles or treat host callbacks as hardware facts.
2. Add CDM context creation, actual page tables/mappings, MMU-cache commands, and owned compute ISA/PDS/CDM control data. Keep resources pinned until completion or proven DMA quiescence.
3. Require actual engine completion plus cache-synchronized output, sentinel, and guard words. A KCCB return, CCB movement, firmware PING, or sync-only UFO is insufficient.
4. Add bounded missing-completion, malformed-stream, reset, teardown, and repeated-lifetime tests. Polling can establish the first job; implement and validate the real GIC route before relying on interrupt-driven service operation.

**Proof tools:** kernel/live console and firmware log for submission/completion/faults; explicit readback receipt for output and guards; crashdoc for user/kernel failures. `qemu_preflight` may check that added boot arguments/overlays do not regress the software boot, but its result remains QEMU-only and cannot establish GPU execution.

### Step 5 — Publish one real `AGXAccelerator`, then bring up Metal and the CA render profile

#### 5A. Implement the service identity without creating a second backend

Files/functions: `xnu/iokit/Kernel/arm/sweet_services.cpp` (`IOAcceleratorES`, `sweet_accel_publish_native()`), the UC provider/`newUserClient` composition, and `research/ios26-metal-native-20261102/metal-r2/src/hmnp_xnu.cpp` (`hmnp_publish_service()`).

1. Add a C++ `AGXAccelerator` derived from the project's `IOAcceleratorES`, and instantiate that single derived service in `sweet_accel_publish_native()`. `hmnp_publish_service()` already requires `s->metaCast("IOAcceleratorES")` (`hmnp_xnu.cpp:52`), so the derived service preserves that gate. Install the real HMGU `newUserClient` on the same object before registration.
2. Add an IOKit/host registry test proving that `IOProviderClass=AGXAccelerator` matches the derived class **and** `IOProviderClass=IOAcceleratorES` matches through its base class. Do not publish separate AGX and IOAcceleratorES objects with independent state, and do not rely on `setName()` to satisfy an `IOProviderClass` match.
3. Acquire/recheck the real readiness lease before setting `MetalPluginName=../../../private/var/hk/HMNativeMetal`, `MetalPluginClassName=HMNativeMetalDevice`, and `registerService()`. The ready ops must reference actual firmware epoch, VM/context, validated streams, engine completion, and cache handback (`metal-r2/notes/INTEGRATION.md:16-39`). HEALTH, coremem, or KickSync alone must return not-ready.
4. Keep the CA-facing registration disabled during compute-only tests. When it is finally registered, emit one kernel line containing class, plugin, firmware epoch, and readiness generation so registry evidence can be joined to the same backend.

**Live proof when eligible:** the two current `AGXAccelerator -> none` queries become `-> AGXAccelerator` at `console.txt:1459/1490` and `:2244`; `IOAcceleratorES -> 0 found` at `:1423` and `:2323` becomes one found. Also capture the native publication line and properties. These matches prove registry identity only, not execution.

#### 5B. Complete the plugin/device path in an owned process first

1. Stage the reviewed `HMNativeMetal.bundle` at the RAM-overlay path named by the property, with the real principal class and complete compiler/streams provider. No Apple framework replacement, fake readiness marker, or test provider belongs in the production image (`metal-r2/notes/INTEGRATION.md:101-129`).
2. Make `HMNativeMetalDevice.initWithAcceleratorPort` succeed through real HMGU OPEN and capability negotiation. First run the owned explicit-registry compute validation with output/guard readback; do not use system-default device creation as the initial test.
3. Add a runtime line such as `HMNativeMetal: device ready class=HMNativeMetalDevice registry=<id> capabilities=<bits>` after OPEN, and a failure reason on every refusal. Use `hk_ustack=<testproc>,backboardd,SpringBoard` / `hk stacks` to locate any private-selector or IOKit wait; crashdoc must show no new backboardd/SpringBoard abort.

**Live proof:** an owned probe returns a non-nil device and completes guarded compute; the runtime prints its ready line. Only at the later CA-enabled stage should the current `SUICOrbView ... Failed to get Metal device` line at `console.txt:2329` disappear and SpringBoard report successful device creation. A non-nil device with no completed job remains a loader milestone, not a render result.

#### 5C. Prove the minimum render profile before exposing it to CoreAnimation

1. Implement concrete native render PSOs, BGRA8 textures, render/blit encoders, VDM/PPP/PDS streams, render-target/cache handling, completion, and transfer readback. Compute capabilities must not auto-authorize render capabilities.
2. Run the existing owned clear/zero-count, triangle, and two-triangle quad tests with changing colors, full-pixel/guard checks, and texture-to-buffer readback (`validation-r3/messages.md:8-43`; the unified case is `validation-r8/.../notes/cases.json:135`). Require actual render and blit completion, stale-event rejection, and retained ownership on timeout.
3. Add the measured compositor requirements incrementally: texture upload/sampling, alpha blending, offscreen attachments, viewport/scissor variants, IOSurface import/pinning, and GPU-write-before-DPU-read fencing. Inventory and implement the exact QuartzCore shader/passes used by the target glass, blur, and vibrancy views; do not claim full Metal or use a CPU production renderer as a substitute.
4. Extend `hgltrack` to record the **actual selected context class**, device name, and submission/completion identifiers. A useful new receipt is `HGLTRACK: context=<actual GPU-backed class> device=HMNativeMetalDevice submit=<id> done=<id>`. Do not merely suppress the `SWContext` log: software contexts may legitimately remain for CPU operations, so the requirement is that the compositing path selects the GPU-backed context and has real completions.

**Live proof:** owned render tests produce exact pixels and guards, and the context tracker names a GPU-backed context with joined submit/done IDs. Only then enable the CA-facing AGX service.

#### 5D. Flip CoreAnimation to hardware and validate Liquid Glass

1. Start backboardd/SpringBoard against the ready AGX service. Confirm all three live changes together: AGX/IOAcceleratorES matches resolve; Metal-device creation succeeds (including no `SUICOrbView` failure); the compositor chooses a GPU-backed context rather than the `SWContext` fallback seen at `console.txt:889`.
2. Join a CA render submission through firmware/engine completion and cache handback to IOSurface presentation on AppleCLCD/DPU. AppleCLCD opening remains only the scanout baseline (`console.txt:1393-1439`).
3. Require known rendered pixels for the targeted blur/vibrancy materials and an owner/screenshot check of Liquid Glass. Check flat rectangles, missing backdrop samples, wrong alpha/colors, stale surfaces, and frame ordering; then exercise repeated present, app switching, malformed inputs, missing completion, teardown, and power/idle behavior.
4. Use live_boot console for the correlated chain, HK USTACK for blocked Metal/QuartzCore calls, and crashdoc for regressions. `qemu_preflight` can test bundle/overlay/startup regressions but cannot prove any Tensor render step. Do not promote until physical GPU completion and correct pixels agree with the visual result.

## 4. RISKS

| Risk | Why it matters here | Required mitigation / stop rule |
|---|---|---|
| Wrong coremem address or layout | Can repeat the META DMA fault, HWR, lockup, and DEBUG_DUMP before health. | Pin the exact layout; host-check the full 64-bit value; S1 requires no init fault. Stop on any new MMU fault/HWR and do not retry unchanged. |
| Malformed context/CCB/KICK | Can cause firmware page faults, context resets, watchdog/HWR, or a persistent GPU lockup. | Empty page catalogue, byte fixtures, bounded offsets/counts, one outstanding ordered step, short timeouts. Stop on FWCCB reset/page fault/restart, assert, new DEBUG_DUMP, or unexpected panic. |
| Host writes its own success | A forged UFO or inferred completion would invalidate the central experiment. | Host writes only the initial sentinel; firmware must produce both updates and compute output/guards. Never promote KCCB consumption or DPU activity to GPU completion. |
| DMA/resource lifetime | Firmware can access a freed/reused context, CCB, UFO, mapping, or compute buffer after a timeout. | Retain all rung allocations through the deliberate reset. For a persistent driver, retain until actual completion or established DMA quiescence; timeout alone is not quiescence. |
| GPU reset and error handling | gpu2 already demonstrated an init HWR with failed polls before later health success. | Compare pre-health and post-stream traces, not just final health. Preserve logs before reset. Do not add an automatic retry/reset loop. |
| Power/thermal/idle | Firmware rungs leave the GPU on and rely on the final reset; APM is forced to 60 s while FDT advertises 1 ms. There is no normal secure STOP/domain-off or DVFS path. | Keep experiments short and one-CPU; retain thermal/deadline guards. Do not run CA or idle/sleep on this lifecycle. Implement/test secure STOP, gate/domain off, reset and thermal handling first. |
| SMMU/secure routing | REE global bypass and FDT idmapped entries do not prove secure-world stream ownership or safe real mappings. | Keep rung 7 translation-empty. Require VM-r3's unresolved NS/SID/exclusion and execution-base facts before real engine mappings. |
| Missing IRQ route | Inventing SPI/vector data or an IOKit provider can hang or misroute interrupts. | Use bounded polling for rung 7/first compute. Resolve the real GIC controller, level/affinity, mask/synchronize, and drain semantics before enabling IRQs. |
| Premature AGX/Metal publication | A name-only `AGXAccelerator` or compute-only device makes the first two lookups flip, then CoreAnimation can crash on unimplemented render selectors or silently produce flat/wrong materials. | One derived service with a real readiness lease; owned compute and render first; CA-facing registration only after the measured render subset and IOSurface fencing pass. Never load Apple's AGX driver on DXT. |
| False hardware-context evidence | Removing `SWContext` text or obtaining a Metal device does not prove that blur/vibrancy ran on the GPU. | Log the actual context class and join submit/done IDs to physical engine completion and presented pixels. Require known-pixel and owner glass checks; CPU glyph rendering may continue legitimately. |
| Android dual boot | A failed experiment must not damage Android, chooser, partitions, firmware, or backups. | Coordinator-only temporary `fastboot boot`; no flash/erase/slot/firmware changes. Preserve the no-map GPU carve-out and all backups/slots. Return to fastboot/Android and run `research/ios26-dualboot-r8/return-check.sh` after every boot; stop on failure. No gpu2-specific return receipt was found in this review, so do not infer one from other boots. |
| Misleading acceptance | gpu2's post-HWR health PASS and a future sync-only stream can look like “GPU works” or “Metal works.” | Record clean-init, KickSync, compute, and Metal as separate milestones. Follow `docs/NATIVE-METAL.md`, not merely the broad probe regexes. |

## Minimal command/evidence checklist for the implementing owner

- Before any boot: M2+M3 host tests, negative/malformed cases, layout identity, enabled-gate ARM64 objects and symbols, image manifest diff limited to the intended rung.
- During/after S1-S4: live console (`HK GPUTA`, `blazer-gpu`), decoded current-boot firmware log, crashdoc census, deliberate panic identity, fastboot recovery, Android return check.
- Before compute: actual VM/security authority and lifetime review; before Metal: physical compute readback; before CA-facing AGX publication: exact BGRA render readback and the measured blend/sampling/offscreen subset; before drawing: known pixels and ordered IOSurface presentation.
- For the int3 regression comparison, require the correlated flip: `AGXAccelerator` matched → Metal device obtained → GPU-backed context selected with submit/done evidence → correct glass/blur/vibrancy pixels. AppleCLCD and CPU glyphs are the unchanged baseline.
- Never use QEMU, host models, ARM64 linking, a non-nil Metal device, a KCCB read counter, a changed context string, or a DPU frame as a substitute for physical GPU execution.
