# Ordered native-GPU bring-up plan — Tensor G5 / iOS 26

Owner: agent 10, integration/live probe. Snapshot: 2026-11-04. Target: the owner's Pixel 10 Pro, PowerVR DXT BVNC 71.2.2448.1212, native iOS 26. This plan preserves Android and uses temporary `fastboot boot` images only. **No source edit, build, Git operation, or phone action is authorized by this document.** The coordinator alone integrates and runs physical attempts.

Companion evidence/recipe: [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md). Governing acceptance: `docs/NATIVE-METAL.md`. Prior detailed analysis: `research/ios26-hw-investigation-r1/GPU.md` and `research/ios26-gpu-r1/{M2.md,PLAN.md,m3/}`.

## 1. Current truth and non-negotiable order

PHYSICAL already establishes power/identity, Trusty firmware upload/start, and **post-recovery** KCCB health. gpu2 also establishes an **init MMU fault → lockup → failed-poll/HWR → recovery** before health. The final zero REE fault registers do not make initialization clean. No client command stream, GPU engine job, shader, rendered pixel, or native Metal device has run physically.

The dependency order is:

**clean firmware/coremem (1, fed by 2/9) → MMU/contexts (3) → CCB/KICK (4) → fences/authentic completion (5) → readiness-gated IOAccelerator publication (6) → Metal device/runtime (7) → CoreAnimation/Liquid Glass/presentation (8).**

Agent 2 supplies firmware/Trusty/lifecycle facts throughout; agent 9 supplies pinned prior art throughout; agent 10 owns live correlation and this integration. Do not skip a physical gate because a host model passes. Do not treat KCCB consumption, a UFO alone, a non-nil Metal device, an HGLTRACK string, or an ordinary DPU frame as native rendering.

### Publication rule that prevents a false milestone

There are two distinct exposures:

1. **Owned engineering probe:** after real compute works, a compute-only registration may be used only in a controlled/headless boot where backboardd/SpringBoard cannot select it. This validates registry/plugin/compute, not compositing.
2. **CA-facing service:** publish the system-visible `AGXAccelerator`/`IOAcceleratorES` object with Metal properties only after the minimum real render profile, completion/cache handback, IOSurface fencing, and owned known-pixel tests pass. A compute-only device must never be offered to CoreAnimation.

The safe execution order is **owned kernel/backend checks → owned compute → owned render → owned CA test process → backboardd/SpringBoard**.

## 2. Ordered stage gates

Each stage lists the accountable facet, required acceptance, and the next coordinator/owner action. “Physical” means a fresh phone receipt, not SOURCE/HOST/QEMU.

### Stage 0 — Freeze one composition and its evidence identity

**Owners:** agent 10 integration; all facet owners supply exact source hashes/tests; agent 9 checks provenance ([PRIORART.md](PRIORART.md)).

- Use one reviewed XNU composition and one runtime/overlay composition. Record nested-XNU branch/commit, feature gates, image/kernel/unstripped hashes, overlay hash, boot-args, and exact donor/prior-art pins.
- Re-run existing focused host tests plus negative/malformed/timeout/lifetime cases. Emit ARM64 objects with each tested feature gate explicitly enabled and inspect expected text symbols; empty guarded translation units and syntax-only checks do not count.
- Keep firmware bytes, device dumps/serial numbers, and downloaded Apple artifacts out of Git. Do not mix unreviewed UC profiles or host success callbacks into the physical path. Mainline `pvr`/Mesa does not support this BVNC; metal2vulkan is not a DXT backend. Do not import NullMoth/WTL/noncommercial code or newer mismatched DDK constants.
- Manifest diff against the preceding physical image must contain only the intended experiment and expected build-generated identity changes.

**Accept:** coordinator has a reproducible evidence packet and a single-variable boot candidate.  
**Action:** coordinator integrates; facet owner with a failing/unknown dependency stops promotion. QEMU may check generic boot regressions only; it has no Tensor GPU/Trusty evidence.

### Stage 1 — Firmware up with clean coremem/init (S1)

**Owners:** agent 1 (coremem/init/rung wiring; exact contract in [COREMEM-INIT.md](COREMEM-INIT.md)); agent 2 (firmware/Trusty/shared-data/lifecycle; runtime contract in [FIRMWARE.md](FIRMWARE.md)); agent 9 (stock comparison).

Current M3 gap: `gta_m3_coremem` is not assigned, rung argument/setup still stops at 6, and there is no runnable rung-7 stream. Agent 1 must not merely raise the rung limit, which could disable tracing and produce a false PASS. The first next boot is **coremem-only S1 with no client KICK**, as independently required by agents 1 and 3.

Required implementation/evidence:

- Write the measured 64-bit coremem device address `0xE1C013C000` at SYSINIT `+0x150` before the final barrier and SMC START. Read both words back before START and emit agent 1's exact `M3 COREMEM` line. Refuse a different firmware/layout identity.
- Preserve M2 state/trace/FWCCB/register diagnostics for rungs 7/8 and use the stock health order: HEALTH consumption, then STATEFLAGS_CTRL return `CMD_EXECUTED` (1).
- Parse the trace before HEALTH and after STATEFLAGS; fail closed on `CORE_MMU_FAULT` (`0x7004b052`), `HIT_LOCKUP` (`0x700110c5`), `FAILED_HW_POLL` (`0x7003b00d`), `START_HW_RESET` (`0x7001b03d`), assert, or DEBUG_DUMP, and on malformed/truncated/unknown-gap trace data. The existing decoder is useful for review but scans/resynchronizes; S1 acceptance needs a strict sequential parser that rejects bad input rather than converting it to zero failures. A recovered health PASS is not S1. S1 always dumps its tail and has a distinct `M3 S1 PASS`; issue no client KICK.
- Agent 2 verifies TA/image/shared-data ordering and documents the still-unexplained 24.2/26.1 and `process_st_info(278)` messages separately; do not label them fatal or benign without evidence.

**Accept (PHYSICAL):** exact pre-SMC coremem line/readback; valid pre-health and final traces with no init fault/lockup/failed poll/HWR/init dump; HEALTH consumed; STATEFLAGS returns 1; OS active; assert empty; complete first-copy fwlog and 18-register survey; only the deliberate `rung 7 S1 PASS` panic; no KICK.  
**Action:** coordinator runs the single coremem-only gpu3 recipe in LIVE-EVIDENCE §6, decodes the first full trace, returns to Android, and runs return-check. On any fault, agent 1 stops and compares with agent 2/9; no unchanged retry and no client KICK.

### Stage 2 — MMU and firmware contexts (S2 preparation)

**Owners:** agent 3 (full contract in [MMU.md](MMU.md)); agent 9 supplies exact layouts/address forms; agent 4 consumes the frozen byte specification.

Split two milestones that must not be conflated:

1. **Sync-only context:** zeroed page catalogue/all translations invalid; `uiPageCatBaseRegSet=RGXFW_BIF_INVALID_PCSET` (`0xffffffff`); GP-DM common context; CCCB control and 8 KiB CCB. `FWMEMCONTEXT.sPCDevPAddr` is a 64-bit backing **DMA/physical address**—for the M3 carve-out case `GTA_CARVEOUT_PA + pc_offset` (`0xB9F00000 + pc_offset`), not `GTA_DEVVA_HEAP + pc_offset`. CCB `sCCBMetaDMAAddr` and coremem instead use the raw firmware-heap device VA (`0xE1C0000000 + offset`); CCB/control/context pointers use the measured 32-bit uncached firmware form. Memory-context registration is object initialization plus common-context reference, not a new KCCB opcode.
2. **Real engine VM:** exact three-level DXT MMU-v4 page tables/mappings (PC 1024x32-bit, PD 512x64-bit, PT 128x64-bit for 16 KiB pages), firmware memory-context publication, MMU-cache commands, VA/resource ownership, CPU/GPU cache aliases, and retained mapping lifetime. Read `0xe350/0xe358/0xe360/0xe368` and require effective 16 KiB over every current heap and interior boundary. Publish child tables/data → parent tables → catalogue → completed MMUCACHE sync (`PT|PD|PC|CTX_ALL = 0x807`) → KICK. Before real engine mappings, resolve live NS/SID/exclusion/secure-stream authority and legitimate USC/PDS execution-base evidence. REE SMMU bypass, requested SYSINIT bases, and FDT `idmapped` properties do not prove secure-world ownership or programmed execution bases.

**Accept:** byte-exact host fixtures for every structure/address form and bounds rejection; for sync-only, physical context admission without a fault in stage 3. For real VM, a separate physical mapping/readback proof with explicit security authority—never inferred from KickSync.  
**Action:** agent 3 hands agent 4 a frozen layout/address/lifetime spec. If secure routing/execution-base facts remain unavailable, stop before CDM/render engine jobs; do not install a success callback or guess MMIO.

### Stage 3 — Client CCB and KICK (S2/S3) — CLASSIFIER-RISK

**Owners:** agent 4 (encoding contract in [CCB-KICK.md](CCB-KICK.md)); agent 3 supplies contexts; agent 1 supplies clean S1; agent 2 supplies KCCB/FWCCB serialization and a real dispatcher; agent 9 verifies stock `PVRSRVRGXKickSyncKM` shape.

Before the first client KICK, agent 2 must move beyond M2's read-only FWCCB diagnostic: implement a bounded dispatcher that copies each complete entry, advances read with release ordering, handles reset/page-fault/restart/debug requests, and runs before/during waits. Give each boot/restart a `fw_epoch` and each context recovery a `recovery_seq`; stale waits fail rather than completing from reused slots/UFOs. S1 needs no dispatcher because it issues no client work.

Required precise spec before coding:

- `RGXFWIF_FWMEMCONTEXT` 0x40, `RGXFWIF_FWCOMMONCONTEXT` 0x1e0, `RGXFWIF_CCCB_CTL` 0x20, CCB command header 0x10, UFO 0x8, KCCB command 0x70. KICK data is 0x1c bytes after the type/flags; the meaningful slot encoding through three zero cleanup pointers ends at slot `+0x24`.
- CCB read/write/dependency offsets start at 0; wrap mask `0x1fff`; GP DM=0; `HAS_DEFER_COUNT=0x2`; bounded process name/job references and zero/default state, priority, cleanup, and framework fields as measured. Print `pc_dma`, `ccb_dma`, and all `0x40......` pointers before KICK so the address families cannot be confused. The canonical fixture has `pc_dma=0xba139000`, common `0x4023e000`, CCB `0x40240000`, `ccb_dma=0xe1c0240000`, UFO `0x40242000`.
- FENCE `0x2abc00d4`, NULL `0x2abc80d2`, UPDATE `0x2abc00d5`, KCCB KICK `0x2abc0065`; payload sizes exclude the 16-byte header; packets are 8-byte aligned and final host write is 16-byte aligned. Publish the complete stream with barriers, advance only the host-local write offset, and carry that new offset in KICK `ui32CWoffUpdate`; normal stock submission does **not** store it to shared `CCCB_CTL.ui32WriteOffset`. Then publish KCCB write index and ring the GP MTS doorbell.
- One outstanding ordered step. Bound KCCB consumption and execution independently. Reject overflow, bad wrap/offset/count, stale firmware epoch, and unread prior KICK. Retain every context/CCB/UFO allocation through completion or proven DMA quiescence (through deliberate reset for the bounded rung).

**Accept (PHYSICAL):** S1 clean, intended context admitted, first KCCB KICK consumed/decoded with expected CCB values, CCB write/read/dependency offsets drain to `0x40`, and firmware writes UFO value 1; no reset/page fault/restart/assert/new MMU fault. Trace `0x70037013` occurs before command-type dispatch and is decode evidence, not completion.  
**Action:** agent 4 owns only the command-stream implementation and its host/mutant evidence; coordinator runs one boot. Any malformed-stream/firmware fault stops the line for exact trace/layout review by agents 3/4/9. **This command-stream code is a known classifier-risk area: no speculative encoders, inferred constants, or unreviewed implementation.**

### Stage 4 — Fences, completion, cache, and first real compute (S4 then COMPUTE)

**Owners:** agent 5 (completion/lifetime contract in [FENCE-UFO.md](FENCE-UFO.md)); agents 3/4 (VM/CDM submission); agent 7 (owned ISA/runtime); agent 2 (IRQ/lifecycle support); agent 10 (real GIC/IOKit integration).

#### 4A. Ordered firmware-only KickSync

- Host writes only the initial sentinel `0xdead0000`. Stream 1 = FENCE(sentinel) + NULL + UPDATE(`0xc0de0001`), exactly 64 bytes. Stream 2 = FENCE(value 1) + NULL + UPDATE(`0xc0de0002`), sent only after value 1 and CCB drain to `0x40`.
- Treat FWCCB context reset/page fault/GPU restart, new DEBUG_DUMP, HWR, timeout, stale epoch/recovery, or host-written expected values as failure. Polling is acceptable for this bounded proof.

**Accept (PHYSICAL S4):** value 1 then value 2 in order, CCB offsets drain to `0x40` then `0x80`, independent UFO check/update trace evidence, and no faults. This proves firmware context admission/client parsing/fence/update ordering only—not GPU hardware work. Because stream 2 starts after value 1 is visible, its FENCE is already satisfied: a genuinely blocking fence needs the later two-GP-context control, not this first boot.

#### 4B. First owned compute job

- Create a CDM context over the proven real VM; publish MMU-cache operations; submit owned PDS/CDM/ISA control data. Keep all input/output/context/stream allocations pinned until actual completion or established DMA quiescence.
- Require actual engine completion and SLC/CPU cache handback before reading. Give each job a unique identity `(firmware generation, context epoch, sequence, context handle, UFO address, token)` and reap oldest first with strict equality; M3's reused two-value UFO is not production ABA protection. Validate changing sentinel/input, expected output, and every guard/canary word; include absent-completion, stale-event, malformed-input, reset, pending teardown, and repeated create/destroy controls. The candidate SLC KCCB is `0x2abc0068`, `bInvalidate=0`, DM-context=1, return=1, but requires physical validation.
- Resolve the real external-GIC/IOKit route before interrupt-driven service operation. FDT SPI 130 maps to native INTID/vectorData 162, but the raw four-cell tuple is not vectorData and no current provider route exists. Use dedicated OS0 status/clear `+0xbd0/+0xbe0`, mask `0x3`, and firmware interrupt count at OSDATA `+0x230`; generic `EVENT_STATUS +0x130` is not OS0 proof. The IRQ counter is only a wake hint. For the acceptance run, disable completion polling and require route → LISR → MISR → strict `IRQ_UFO` → SLC/cache → HMGU done plus the independent firmware UPDATE. Bounded polling remains the initial route.
- Add normal lifecycle before long-running/idle/CA use: close admissions, complete/fail work and drain FWCCB; when responsive use KCCB POW `0x2abc00c8` and require `RGXFWIF_POW_OFF`, then secure STOP=2, gate/core/domain off in stock order. On full restart SEND only once per boot, reinitialize shared state including coremem, START again with a new epoch, and reprove health. Timeout is not quiescence.

**Accept (PHYSICAL COMPUTE):** owned compute readback is exact and joined to the same firmware epoch/VM/context/submission/engine/cache receipt; all guards pass and negative controls cannot certify success.  
**Action:** only after COMPUTE may agent 6 prepare an owned compute-only publication. Agent 5 blocks promotion on any unproved completion/cache/lifetime link.

### Stage 5 — Publish one native IOAccelerator/AGX service (R1)

**Owners:** agent 6 (registry/UC contract in [IOACCEL.md](IOACCEL.md)); readiness supplied by 1/3/4/5/7; agent 9 checks IOKit behavior/prior art.

- Implement a C++ `AGXAccelerator` derived from the project's `IOAcceleratorES`, instantiated once under `IOService::getPlatform()` with the real HMGU `newUserClient`. Both `IOProviderClass=AGXAccelerator` and `IOProviderClass=IOAcceleratorES` must match that same object and registry ID. Suppress the legacy bare `sgx` service. Do not use two backends, rename AppleCLCD, or load Apple's AGX driver on DXT.
- Acquire/recheck a readiness lease covering the live firmware epoch, usable VM/context/builders, validated streams, authentic engine completion, cache handback, and native-stage validator. HEALTH/coremem/KickSync alone returns not-ready.
- Set `MetalPluginName=../../../private/var/hk/HMNativeMetal` and `MetalPluginClassName=HMNativeMetalDevice` only under that lease. Roll back partial properties/lease on failure; withdrawal closes new OPENs and retains live resources until actual quiescence.
- Use HMGU open type `0x484d4755` on the same provider; Apple's IOGPU/AGX user-client ABI is deliberately not emulated. Capture OPEN/selector/map return codes and make only evidence-driven narrow sandbox admissions, never a blanket grant.
- Emit one publication line with registry ID/provider/class/plugin/firmware epoch/readiness generation/UC type/capabilities. Preserve native properties in a registry receipt. The int3 `IOK` global 400-line budget is not sufficient as the sole late-stage evidence channel.
- Keep CA-facing registration disabled for compute-only tests. For those tests use an explicit registry ID in a controlled/headless boot; never let backboardd/SpringBoard be the first Metal client. For the normal discovery proof, remove `HK_ACCEL_ONCE=skip` and publish before backboardd starts so the normal poll succeeds.

**Accept (PHYSICAL R1):** both class queries resolve to one ready native object and registry ID; properties and user client are present; readiness cannot be forged by a marker. Registry success alone is not OPEN or rendering.  
**Action:** agent 7 stages the trusted runtime and runs the owned device/OPEN checks in stage 6. CA-facing registration remains blocked until stage 6 render acceptance.

### Stage 6 — Metal device and minimum render profile (M1/M2)

**Owners:** agent 7 (runtime/cache/IOSurface contract in [METAL.md](METAL.md)); agent 6 supplies service; agents 3/4/5/9 supply stream/cache contracts. **ISA/PDS/CDM/VDM/PPP command-stream code is also classifier-risk and needs exact per-stage specifications and review.**

#### M1. Owned compute Metal device

- Stage the reviewed signed `HMNativeMetal.bundle` and real compiler/streams provider in the temporary RAM overlay with the chosen pointer-auth/library-validation policy; no Apple framework replacement, test provider, fake marker, or persistent root write. Supply `org.hackios.hmgpu.client` to the owned calling process (and later CA processes) or a separately reviewed authorization design; bundle loading, process entitlement, sandbox, HMGU OPEN, and capabilities are independent fail points.
- `HMNativeMetalDevice.initWithAcceleratorPort:` must pass real HMGU OPEN/capability negotiation. Emit `device ready` with class/registry/capabilities/headless or a precise compiler/codesign/OPEN/capability refusal reason. Use explicit registry selection first, then have the controlled probe call `MTLCreateSystemDefaultDevice()` and require exactly one device. Keep `isHeadless=YES` until presentation exists.
- Repeat COMPUTE through the public Metal path with guarded readback. A non-nil device without the job is only a loader milestone.

#### M2. Owned native rendering

- Add concrete BGRA8 textures, vertex/fragment PSOs, render/blit encoders, VDM/PPP/PDS streams, render-target layout/cache rules, actual render/transfer completion, and CPU readback. COMPUTE capability must not authorize RENDER/TRANSFER.
- Pass the existing 32x24 clear/zero-count, one-triangle, and two-triangle quad cases with changing colors, full-pixel/guard checks, and texture→buffer copy at the prescribed offsets/row strides. Add malformed/zero-count, absent completion, stale event, and teardown controls.
- Then add texture upload/sampling, alpha blending, offscreen attachments, viewport/scissor variants, IOSurface import/pinning, and GPU-write-before-DPU-read fencing. Start with a 64x64 plain BGRA owned surface, then import the live 1125x2511/bpr4608/11583488-byte (707-page) shape. Authorize the caller's actual registered IOSurface reference, not a numeric ID alone. Order transfer readback after render with `wait_ctx_seq`; CPU-copy presentation is acceptable initially only after the same completion/cache fence and without a zero-copy/performance claim. Unsupported selectors must fail explicitly, not crash or silently draw flat.

**Accept (PHYSICAL M1/M2):** owned Metal compute readback passes; then exact rendered pixels/blit/guards and completion/cache evidence pass.  
**Action:** agent 7 certifies the minimal render profile; only then may agent 6 enable CA-facing publication and agent 8 begin an owned CA-process test.

### Stage 7 — CoreAnimation, Liquid Glass, and scanout (G1)

**Owners:** agent 8 (QuartzCore/render-server contract in [COMPOSITOR.md](COMPOSITOR.md)); agents 6/7 supply ready service/runtime; agent 5 supplies presentation fences; agent 10 correlates live evidence.

- First run a separate diagnostic-only software-compositor boot with `hk_flatmat` off and read-only observers for `capture_backdrop`, `filter_backdrop`, `SWContext::blur_surface`, Gaussian/vibrant/glass filters. This identifies whether capture/lifetime or blur/filter/blend is broken; it is not native acceptance and does not share the firmware S1 boot.
- Extend HGLTRACK/CA observation to record the **actual selected context class**, device, registry/epoch/context/submission/surface/present IDs, pipeline/AIR variant, and completion ID. Software contexts may remain for legitimate CPU operations; suppressing `SWContext` text is not success. Keep Inferno/forced-software patches and `hk_flatmat` out of native runs.
- **C1 owned offscreen QuartzCore:** after agent 7's basic render oracle, use `CARenderer rendererWithMTLTexture:options:` on an owned queue, deterministic quadrants/image/alpha scene and guard border, explicit worker transactions, then blit/readback after actual engine completion. `endFrame` alone is not synchronization. Require exact pixels/guards and no fallback/unsupported selector.
- **C2 minimum on-screen GPU compositor:** host an owned remote CA context in backboardd, with plain BGRA and no competing presenter. Join destination surface F → submission S → engine/cache done S → `IOMFBDisplay::finish_update`/`swap_set_layer` → `SWEET FB: swap` with present P. Compare raw BGRA pixels and `hk shot`; repeat 100 alternating presents plus timeout/stale controls. IOSurface pages remain pinned through GPU completion and DPU retirement.
- **C3 real backdrop:** offscreen then on-screen `CABackdropLayer` over deterministic high-contrast boundaries. Test disabled/radius-zero/nonzero controls, far fields, two-sided spread, fine-detail attenuation, edges, guards, and current-parent capture. Add in-place, colour/luma, vibrant, variable/mip routes one at a time; a Gaussian alone is not Liquid Glass.
- **C4 owner-visible Liquid Glass:** inventory and implement the actual `GlassBackgroundFilter`/`GlassForegroundFilter`, variable-blur, vibrancy, and MaterialKit variants. Open Control Center over two colourful backgrounds and require background-dependent blur with stable sharp foreground, raw pixels plus screenshots, and the full C2 chain. No flat rectangles, recursive screenshot blur, missing backdrop samples, wrong alpha/colors, stale surfaces, or frame reordering. Exercise app switching, malformed inputs, missing completion, teardown, and idle/power transitions.
- Use explicit `hk_ustack=backboardd,SpringBoard` with `hk_dbg=0x1e1e17` for later hangs; retain screen snapshots/crashinfo and native publication/completion lines. The int3-derived replacement of `blazer_haptic_tap=1` with that USTACK token fits in 1014 bytes including NUL. Calibrate screenshot RGB565/channel order against software control; raw BGRA is authoritative.

**Accept (PHYSICAL G1), all correlated:** AGX and IOAcceleratorES matches resolve; no SUICOrbView Metal-device failure; real non-headless `HMNativeMetalDevice`; C1/C2/C3/C4 pixel gates; GPU-backed CA context with joined submit/done/present; completed surface precedes DPU presentation; owner-confirmed background-dependent glass/blur/vibrancy; no new backboardd/SpringBoard crash; Android return-check passes.  
**Action:** agent 8 owns compositor acceptance and remaining shader work; agent 10 supplies owned CARenderer/remote-context harness and records the evidence chain. Only after stability/lifetime/power soak should the coordinator discuss performance or “native Metal complete.” Frame/presentation counts are not FPS.

## 3. Facet gap/conflict ledger

| Facet | Current concrete gap or conflict to resolve |
| --- | --- |
| **1 — coremem/init** | [COREMEM-INIT.md](COREMEM-INIT.md) resolves the first-boot conflict: run coremem-only rung-7 S1, no KICK. Implementation still needs flag/rung/trace wiring, readback, parsed S1 checks, and tests. |
| **2 — firmware** | [FIRMWARE.md](FIRMWARE.md) supplies `FW_UP`/recovery epochs, strict trace rules, mandatory pre-client FWCCB dispatcher, and STOP/restart design. TA version/`278` remains unresolved; normal STOP/domain-off is not implemented; APM stays 60 s for experiments; IRQ route remains open. |
| **3 — MMU/contexts** | [MMU.md](MMU.md) corrects the earlier generic address wording: catalogue root is DMA/PA, coremem/CCB DMA are firmware-heap device VAs. Real VM remains blocked on live NS/SID/exclusion, all-heap range checks, and USC/PDS execution-base authority. |
| **4 — CCB/KICK** | [CCB-KICK.md](CCB-KICK.md) supplies exact fixtures and corrects shared-write-offset handling. No runnable implementation exists; it stays behind physical S1 and agent 2's dispatcher. Classifier-risk: byte-exact layouts plus negative/malformed/lifetime tests are mandatory. |
| **5 — fences/completion** | [FENCE-UFO.md](FENCE-UFO.md) supplies strict UFO+`R=D=W` acceptance, per-job production identity, and the INTID162 IRQ design. Its §3.4 host store to shared `CCCB_CTL.W` conflicts with agent 4's stock-path KICK-only update; integration uses agent 4's rule and agent 5 must align its tests. First S4 does not prove a temporal stall. |
| **6 — IOAccelerator publish** | [IOACCEL.md](IOACCEL.md) specifies one platform-root derived object, same-ID HMGU/readiness, no legacy `sgx`, and no `HK_ACCEL_ONCE=skip` for the proof. Its reference to an S1-S4 next boot is superseded by agent 1/3's coremem-only S1 decision. |
| **7 — Metal device** | [METAL.md](METAL.md) verifies the custom loader in the iOS 26 cache and separates compiler/signing/entitlement/OPEN/capability failures. Production provider and render/transfer/IOSurface paths remain absent; compute must not auto-advertise render, and default-device count must be one. |
| **8 — compositor/Liquid Glass** | [COMPOSITOR.md](COMPOSITOR.md) sets C1 offscreen CARenderer → C2 known panel frame → C3 real backdrop → C4 MaterialKit/glass. It also requests an independent software-capture diagnostic after the firmware boot. `hk_flatmat`/Inferno forced software must stay off for native acceptance. |
| **9 — prior art** | [PRIORART.md](PRIORART.md) confirms the matched `5940a317` DDK as authoritative, mainline's lack of DXT support, foreign-Metal proof patterns, and no second/virtio backend. The user-supplied `ios-tegu` archive (`8e2d75bb…`) is Pixel 9a/Tensor G4 **Mali G715-class CSF**, not DXT: exclude its GPU packets/constants and reuse only externally reported iOS 26 lessons (plain-BGRA policy, larger shader bounds, NoPerspective/base-instance handling, persistent VM/lifetime, and the need for RGBA16F/MSAA/CA selector coverage). Preserve licence boundaries; external success is never our physical evidence. |
| **10 — integration/live** | Maintain this plan and LIVE-EVIDENCE; decode first-copy fwlog, correlate registry→device→context→engine→surface→DPU, name missing evidence. No relevant backboardd/SpringBoard stacks exist in int3. |

## 4. Cross-cutting stop rules and biggest risks

1. **Clean-init risk:** the coremem diagnosis is strong but unproved. Any new MMU fault/HWR/lockup/assert stops the boot line; never call recovered health clean or retry unchanged.
2. **Command-stream/classifier risk:** wrong CCB/KICK/CDM/VDM/PPP layout, address form, barrier, or lifetime can fault firmware or hang the GPU. Require frozen byte specs, bounded one-step experiments, malformed/timeout tests, retained ownership, and specialist review.
3. **Secure routing/VM risk:** REE bypass does not establish secure-world stream ownership. No real engine mappings until NS/SID/exclusion and execution-base authority are proven.
4. **False completion/cache risk:** KCCB reads, CCB progress, UFO sync, firmware PING, and DPU frames are not shader completion. Require authentic engine + cache handback + guarded readback.
5. **Premature AGX/Metal risk:** a name-only or compute-only service can move CoreAnimation onto missing selectors and crash backboardd or silently flatten materials. Gate CA publication on owned render evidence.
6. **IRQ/power/lifetime risk:** no proven GIC route or normal secure STOP/domain-off exists; timeout is not DMA quiescence. Keep initial tests short, one-CPU, polled, thermally bounded, and out of idle/CA until lifecycle is fixed.
7. **Evidence risk:** int3 has no relevant USTACK samples and its IOK/HKL budgets drop messages. Add native correlated lines and explicit USTACK targets; never infer success from missing errors.
8. **Android/recovery risk:** coordinator-only temporary boot; no flash/erase/slot/firmware changes. Preserve backups/no-map carve-out and run return-check after every physical attempt; gpu2 has no located attempt-specific return receipt.

## 5. Prioritized physical boot queue

Status labels: **EXISTING** means the named image already exists; **NEW KERNEL** means XNU work is still required; **NEW OVERLAY** means the int3 kernel can stay but the RAM overlay/probe must change; **NEW STACK** means a new kernel plus signed native runtime/probe composition. No later row authorizes skipping an earlier physical gate.

### 0. Current userland baseline — EXISTING, already running; do not duplicate

- **Image:** `research/images/a7-ios-system-int3/boot.img`, being run as `a7-int3-gpuprobe`; exact stock int3 manifest args (`cpus=5`, `rd=ufsroot0`, `hk_dbg=0x1e1e1f`, no GPU/native-publication args).
- **Facets:** 6/7/8/10.
- **Look for:** the established AGX/IOAcceleratorES misses, SUICOrbView Metal failure, SWContext, AppleCLCD/IOSurface/DPU baseline. Current capture `live-20261104-001321-a7-int3-gpuprobe` is only at 6.47 s and has not reached those later events yet.
- **Other existing images:** gpu2/rung6 and r6-gpu already have sufficient baseline receipts. **Do not rerun gpu2's known-faulty rung6 unchanged.** Rung8 is only a later negative control if coremem S1 regresses.

### 1. Coremem-only S1 — NEW KERNEL; next boot after the current one

- **Image:** planned `research/images/a7-ios-system-gpu3`; gpu2 manifest with exactly `blazer_gpu_tipc=6` → `blazer_gpu_tipc=7`, `cpus=1`, no `hk_dbg`, every other arg unchanged. Full recipe: LIVE-EVIDENCE §6.
- **Facets:** 1/2/10; prerequisite for 3/4/5.
- **Look for:** pre-SMC coremem `0xE1C013C000` readback, valid strict pre-health/final traces with zero MMU/lockup/failed-poll/HWR-reset/DEBUG_DUMP, HEALTH consumption, STATEFLAGS return 1, 18-register survey, deliberate `rung 7 S1 PASS`, **no KICK**, Android return PASS.

### 2. Read-only MMU range/SMMU diagnostic — NEW KERNEL; after clean S1

- **Image:** planned `a7-ios-system-gpu3-mmuru-r1`; same coremem-fixed rung-7/cpus=1/no-KICK args, with agent 3's read-only instrumentation. Do not use the existing 18-register survey as a substitute.
- **Facet:** 3, with 2/9.
- **Look for:** two samples of `0xe350/0xe358/0xe360/0xe368` and SMMU CR0/GBPA/GERROR; effective 16 KiB across GENERAL/PDSCODEDATA/USCCODE and every interior boundary; route identity evidence. Do not read unknown USC/PDS MMIO or issue mappings/KICKs. Execution-base admission remains closed without a legitimate observation path.

### 3. Polled KickSync S2-S4 — NEW KERNEL + dispatcher; after S1 and fixture review

- **Image:** planned `a7-ios-system-gpu4-kicksync-r1`; same gpu2-derived args with `blazer_gpu_tipc=7`, `cpus=1`, no `hk_dbg`, no IRQ writes. Agent 2's real FWCCB dispatcher and agents 3/4/5's fixtures/tests are mandatory.
- **Facets:** 2/3/4/5/9.
- **Look for:** catalogue `pc_dma=0xba139000` (not `0xe1…`), common `0x4023e000`, CCB `0x40240000`, `ccb_dma=0xe1c0240000`, UFO `0x40242000`; host-local write offsets in KICK (not normal-path shared-W stores); KCCB slots 2/3; `0xdead0000` → `0xc0de0001` → `0xc0de0002`; CCB `R=D=W=0x40` then `0x80`; independent KICK/UFO_CHECK/UFO_UPDATE trace; no faults. This is not engine compute or a temporal-stall proof.

### 4. Software backdrop/capture diagnosis — NEW OVERLAY, int3 kernel reusable; independent of rows 2-3 but after row 0

- **Images:** `a7-ios-system-int3-swbackdrops-r1` and `...-nocache-r1`; int3 args with `blazer_haptic_tap=1` replaced by `hk_ustack=backboardd,SpringBoard` and `hk_dbg=0x1e1e17` (1013-byte command line, 1014 including NUL). No native accelerator.
- **Overlay/env:** agent 8's read-only capture/filter observers, `hk_flatmat` off. Case A `CA_PRINT_BACKDROPS=1`; case B `CA_BACKDROP_SCALE=1 CA_DISABLE_BACKDROP_CACHE=1`.
- **Facet:** 8, with 10. **Not runnable on the unmodified int3 overlay** because the new observers/env are absent; the current gpuprobe already covers the unchanged baseline.
- **Look for:** whether `capture_backdrop` returns a current valid parent surface and whether `SWContext::blur_surface` / Gaussian/vibrant/glass filters execute, with bounds/format/result. This locates capture/lifetime versus filter/blend failure; it is not native acceptance.

### 5. Owned backend COMPUTE — NEW STACK, controlled/headless; after rows 1-3 and real-VM gates

- **Image:** planned `a7-ios-system-native-compute-r1`; int3-derived args with the USTACK replacement/hk_dbg change, `blazer_aks_wrap=1` and `blazer_key_delivery=1` removed for automated headless probing, and `blazer_hmgu=1 blazer_native_metal=1` added (1009-byte command line, 1010 including NUL). No `hk_accel`; overlay prevents backboardd/SpringBoard from consuming the service and removes `HK_ACCEL_ONCE=skip`.
- **Facets:** 3/4/5/7; 6 prepares but does not CA-publish.
- **Look for:** real secure VM/contexts, MMUCACHE sync, owned CDM work, actual engine completion + SLC/CPU handback, exact output/sentinel/guards, stale/timeout/teardown controls. KickSync alone never reaches this row.

### 6. Registry + owned Metal compute — NEW STACK, controlled/headless; after row 5

- **Image:** planned `a7-ios-system-native-metal-compute-r1`; same 1009-byte native-compute args, one derived AGX/IOAcceleratorES object, trusted signed bundle/compiler provider, process entitlement. No duplicate bare `sgx`, no CA consumer, normal non-skipped accelerator poll.
- **Facets:** 6/7/10.
- **Look for:** both class matches at one registry ID and exact plugin properties; explicit HMGU OPEN then `MTLCreateSystemDefaultDevice()` with exactly one device; `HMNativeMetalDevice headless=1`; same registry/epoch/ctx/seq through guarded compute and transfer readback. Separate compiler/codesign/sandbox/OPEN/capability failures.

### 7. Owned render + IOSurface — NEW STACK; after row 6

- **Image:** planned `a7-ios-system-native-render-r1`; start from row 6 args and add `hk_gpumem=2` (1021-byte command line, 1022 including NUL). Require the surface-native authority/block/sync path and signed render-capable runtime.
- **Facets:** 3/4/5/7/8.
- **Look for:** exact clear/zero-count/triangle/quad pixels and guards; real render+transfer completion; 64x64 plain BGRA first, then the 1125x2511/bpr4608/11583488-byte (707-page) import; authorized registered surface reference; cross-engine `wait_ctx_seq`; no CPU production renderer. Only now may CA-facing registration be enabled.

### 8. CA offscreen C1, then on-screen C2 — NEW STACK; after row 7

- **Images:** planned `a7-ios-system-native-ca-c1-r1` and `...-c2-r1`; same 1021-byte native-render args, `hk_flatmat` off, no Inferno/forced-software patches, no `HK_ACCEL_ONCE=skip`.
- **Facet:** 8, with 6/7/10.
- **Look for:** C1 exact owned CARenderer pixels/guards after actual completion (not just `endFrame`); C2 destination F → submit S → engine/cache done S → `IOMFBDisplay::finish_update`/`swap_set_layer` → `SWEET FB: swap` present P, exact raw BGRA plus `hk shot`, 100 alternating presents and stale/timeout controls. C2 is the minimum GPU-compositor milestone.

### 9. Real backdrop C3, then MaterialKit/C4 — NEW STACK; after row 8

- **Images:** planned `a7-ios-system-native-ca-c3-r1` and `...-c4-r1`; same args and clean native overlay.
- **Facet:** 8, with 7/10.
- **Look for:** disabled/radius-zero/nonzero CABackdropLayer controls, current-parent capture, far-field/edge/guard correctness; variable/vibrant/glass variants one at a time; Control Center over two colourful backgrounds with background-dependent blur, stable sharp foreground, and the C2 chain. A Gaussian or pretty screenshot alone is not Liquid Glass.

### 10. IRQ-driven completion — NEW STACK; only after polling completion is solid

- **Image:** planned `a7-ios-system-native-irq-r1`; native-render args, real external-GIC controller/provider route, and the probe's completion polling disabled in code. No extra legacy GPU boot arg is admitted today; the implementation must freeze any new opt-in before image creation.
- **Facets:** 2/5/10.
- **Look for:** native INTID/vectorData 162 (not raw FDT tuple), level/route/mask/synchronize readback, OS0 `+0xbd0/+0xbe0` mask `0x3`, OSDATA counter `+0x230`, LISR→MISR, strict `IRQ_UFO`, SLC/cache→HMGU done, independent firmware UPDATE. Counter/IRQ activity alone completes nothing.

### 11. Lifecycle/recovery soak — NEW STACK; last before any performance claim

- **Image:** planned `a7-ios-system-native-lifecycle-r1`; native-render args, repeated controlled reset/teardown/CA present cycles.
- **Facets:** 2/5/6/7/8/10.
- **Look for:** closed admission, drained FWCCB, POW_OFF then STOP=2/gate/domain-off; one SEND per boot, new epoch/recovery generation on restart, coremem preserved, stale waits rejected, resources retained until actual quiescence, no second backend or cached-device use-after-free, Android return PASS after every attempt.

**Immediate coordinator action:** let row 0 finish and capture its later GPU signals; do not boot a second copy. Row 1 is next only when agent 1 supplies the built/tested gpu3 kernel. Rows 2+ are not runnable on existing images as their required instrumentation/backend does not exist yet; row 4 reuses the int3 kernel but still needs agent 8's new overlay. Every temporary boot ends with the normal Android return check.
