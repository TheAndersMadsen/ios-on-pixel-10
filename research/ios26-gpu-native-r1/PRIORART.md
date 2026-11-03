# Native GPU prior-art map — Tensor G5 / iOS 26

Date: 2026-11-04. Owner: agent 9, GitHub/open-source prior art. Scope: read-only source and web research; no XNU edits, builds, build locks, Git mutations, phone actions, firmware bytes, or copied third-party code. The only repository file written is this document.

Evidence labels: **PHYSICAL** = our named phone evidence; **SOURCE** = our pinned DT/source or a linked external source; **EXTERNAL-REPORT** = another project's own claim, not our physical proof; **INFERENCE** = a design conclusion requiring our tests. All constants for our implementation must still be checked against the pinned DDK/firmware layout.

## 0. Executive map

**GPU identity is Imagination PowerVR DXT (Volcanic), BVNC `71.2.2448.1212`, not Apple AGX and not ARM Mali.** The closest hardware/firmware reference is therefore the matching Pixel `lga` PowerVR DDK, not Asahi's AGX driver and not the mainline Rogue driver alone.

| Area | Best references | What transfers | What does not transfer |
| --- | --- | --- | --- |
| Exact firmware/init/CCB/MMU | [Pinned Laguna DDK `5940a317`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/tree/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr) | Address forms, layouts, command sequencing, Trusty/TF-A split, KCCB/FWCCB/CCCB, UFO, cache rules | Any constant from another BVNC/DDK without re-measurement |
| Mainline PowerVR | [`drm/imagination`](https://github.com/torvalds/linux/tree/master/drivers/gpu/drm/imagination), [UAPI](https://docs.kernel.org/gpu/imagination/uapi.html), [Mesa PowerVR](https://docs.mesa3d.org/drivers/powervr.html) | Driver layering, ring completion, VM/flush lifetime, explicit sync, generated control streams | DXT probe/support, old Rogue PTEs/opcodes/stream layouts |
| Apple AGX | [AGX notes](https://asahilinux.org/docs/hw/soc/agx/), [`drm/asahi`](https://github.com/AsahiLinux/linux/tree/asahi/drivers/gpu/drm/asahi), [UAPI](https://github.com/AsahiLinux/linux/blob/asahi/include/uapi/drm/asahi_drm.h) | Firmware-broker design, per-VM ownership, queue/completion architecture, stable UAPI, proof strategy | RTKit/UAT/work-item/microsequence/stamp formats and AGX ISA |
| Metal on foreign GPUs | [UniXNU AdrenoMetal](https://github.com/UniXNU/AdrenoMetal), [metal2vulkan](https://github.com/steelbrain/metal2vulkan), [HakiOS Metal](https://github.com/oosexgang/hakios-metal/tree/9d52b5142542a253b7263a0d7889ad278e5c7693), [NullMoth](https://github.com/nullmoth/nvidia-macos-driver), [WTLIntelGfx](https://github.com/watchthelight-labs/WTLIntelGfx), [ios-tegu](https://github.com/dgigantino/ios-tegu) | Custom accelerator/plugin discovery, `_MTLDevice` and private objects, AIR translation, IOSurface ownership, staged CA acceptance | Adreno/NVIDIA/Intel backends, Turnip/ANV/NVK as a working DXT driver, macOS ABI assumed identical to iOS 26 |
| Virtualization | [Asahi UAPI](https://github.com/AsahiLinux/linux/blob/asahi/include/uapi/drm/asahi_drm.h), [metal2vulkan runtime](https://github.com/steelbrain/metal2vulkan/tree/master/crates/metal2vulkan-runtime) | Flat pointer-free submission, explicit consumer/backend split | No reviewed drop-in virtio-gpu implementation that runs Apple's iOS Metal stack on Tensor DXT |

The immediate implementation order remains the one in [PLAN.md](PLAN.md): clean coremem/init → contexts/MMU → CCB/KICK → authentic fences/completion → readiness-gated IOAccel → Metal → compositor. Prior art supplies comparisons, not permission to skip a physical gate.

## 1. GPU identity established

### 1.1 Three independent identities agree

1. **Pinned DT, SOURCE:** [`gpu0`](../ios26-dualboot-r8/truth/fdt.dts#L31484) has `compatible = "google,lga-gpu", "img,gpu"`; RGX is `0x34f00000`/1 MiB, PFSM is `0x34813000`, the interrupt tuple is SPI 130 level-high, the two IOMMU stream IDs are 0 and 1 with `iommu-idmapped`, and `init-frequency-hz` is 300 MHz. The [`gpu_smmu`](../ios26-dualboot-r8/truth/fdt.dts#L15680) is SMMUv3 at `0x34c00000`; the [`gpu_fw` reserved region](../ios26-dualboot-r8/truth/fdt.dts#L939) is 33 MiB at `0xb9f00000`, `no-map`; [`sswrp_gpu_pd`](../ios26-dualboot-r8/truth/fdt.dts#L31675) has id `0x14`, and the core-logic control is at `0x3480a000`.
2. **Phone CORE_ID, PHYSICAL:** the twice-read value `0x00470002099004bc` splits into four 16-bit BVNC fields: B=`0x47`=71, V=2, N=`0x0990`=2448, C=`0x04bc`=1212. See [GPU investigation §1.1](../ios26-hw-investigation-r1/GPU.md) and [PLAN §1.1](../ios26-gpu-r1/PLAN.md).
3. **Matching vendor configuration, SOURCE:** [`rgxconfig_km_71.V.2448.1212.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/configs/rgxconfig_km_71.V.2448.1212.h) names that exact BVNC and defines `RISCV_FW_PROCESSOR`, `NUM_SPU=2`, `NUM_CLUSTERS=6`, `MMU_VERSION=4`, 40-bit physical bus and virtual address space, `HOST_SECURITY_VERSION=4`, 1536 KiB SLC, and no `ERYX_TOP_INFRASTRUCTURE`. [`rgxcore_km_71.2.2448.1212.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/cores/rgxcore_km_71.2.2448.1212.h) is the matching core file. The production config selects those headers and `SUPPORT_TRUSTED_DEVICE`, with one native driver ([`config_kernel.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/lga/production/config_kernel.h)).

The signed image is `rgx.fw.71.2.2448.1212`, ABI 41, DDK 26.1@6967606. Our measured firmware name is `rgx.fw.71.2.2448.1212`; do not replace it with a mainline firmware or infer a marketing model from a different BVNC.

### 1.2 What this means for prior-art selection

- The relevant ISA/control-stream family is PowerVR: USC/PDS, VDM/geometry, fragment/3D, CDM/compute, transfer, PM/HWRT/freelists and TBDR resource management.
- The host does **not** directly load/start firmware through the mainline register path. Pixel uses `SUPPORT_TRUSTED_DEVICE`, a Trusty TA at `com.android.trusty.pixel_gpu`, `SEND_FIRMWARE_IMAGE`, and TF-A SMC `0xC300000C` for START/STOP. See [`gpu_secure_protocol.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure_protocol.h) and [`gpu_secure.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure.c).
- REE observations that GPU SMMU `CR0=0` and `GBPA=0` mean bypass do not establish the secure world's stream ownership or a safe client mapping policy. Keep [MMU.md](MMU.md)'s live NS/SID/exclusion and execution-base gates closed.
- Apple's `AGXAccelerator` name is a userspace discovery requirement, not evidence of AGX hardware. Apple's AGX kext/firmware contract cannot drive this part.

## 2. Primary reference: the matched Laguna PowerVR DDK

The authoritative source pin is GrapheneOS `kernel_pixel_6.12` **`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`**, `lga` production, DDK 26.1. [COREMEM-INIT.md](COREMEM-INIT.md) and [MMU.md](MMU.md) verify their layouts against that local pin. A useful independent navigation mirror is [`0xnullsect0r/android_kernel_google_gs-6.12_google-modules` at `94d467217db3`](https://github.com/0xnullsect0r/android_kernel_google_gs-6.12_google-modules/tree/94d467217db3a10362aa3277dff8d347919497c6/powervr); its branch/history is different, so it is not silently substituted for the pinned DDK. A second current mirror is [`hdpk/google-modules_powervr`](https://gitlab.com/hdpk/google-modules_powervr).

### 2.1 DT-to-driver cross-check

| DT fact | Matching driver behavior / source | Consequence |
| --- | --- | --- |
| `img,gpu`, RGX/PFSM and IRQ resources | [`SysDevInit`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/sysconfig.c) obtains `rgx`, IRQ, initial frequency and installs trusted-device callbacks | Use vendor sequencing, not generic AGX/Mali bring-up |
| `memory-region` 33 MiB | [`gpu_secure_init`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure.c) caps the carve-out to `0x2100000`; `rgx_heaps_configure` lays out secure/private/shared/page-table heaps | Preserve the no-map carve-out and its address forms |
| Power/APM properties | [`init_pixel_of`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/of.c) reads core-logic PD, firmware-managed SPU power, APM and autosuspend latencies | FDT APM=1 ms versus our 60 s is a real configuration difference, not a cosmetic one |
| `init-frequency-hz` | `SysDevInit` puts it into core-clock timing | Our 300 MHz initial value agrees with DT; DVFS/OPP remains separate work |
| `SUPPORT_TRUSTED_DEVICE` and premaps | `sysconfig.c` wires SEND/START/STOP/FAULT and obtains `PVRSRV_PHYS_HEAP_FW_PREMAP_PT` | Do not rewrite the TEE firmware premap while creating client roots |

### 2.2 Firmware image, shared init and health

Read these first:

- [`rgxfwutils.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c): `RGXSetupFwOsData`, `RGXSetupFwSysData`, `RGXSetFirmwareAddress`, `RGXSetMetaDMAAddress`, KCCB submission, MTS doorbell, MMU-cache commands and FWCCB handling.
- [`rgxpower.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxpower.c): `_RGXDoStart`, power/idle/stop and native versus virtualization behavior.
- [`rgxinit.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/volcanic/rgxinit.c): firmware allocations, coremem section allocation, IRQ/MISR and safety events.
- [`gpu_secure.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure.c): image body/header and CODE/DATA/RODATA/COREMEM_CODE/COREMEM_DATA descriptors; PA and 32-bit firmware VA are distinct from the shared-init raw device VA.

Extracted rules:

1. **Coremem is host init, not a post-start MMU workaround.** `rgxinit.c` allocates the section; `RGXSetupFwSysData` fills `sCorememDataStoreDeprecated` through `RGXSetMetaDMAAddress`. Our measured value is `0xE1C013C000` at SYSINIT `+0x150`; the Trusty section instead carries PA `0xBA03C000` and FWVA `0xC013C000`. [COREMEM-INIT.md](COREMEM-INIT.md) has the complete proof contract.
2. **Native health order is not “wait for HEALTH_CHECK's return.”** Stock consumes HEALTH_CHECK without a return-slot wait; a waited command such as STATEFLAGS_CTRL establishes `CMD_EXECUTED`. Native single-driver mode does not require an OS-online command or the guest compatibility block. See [M2.md §2](../ios26-gpu-r1/M2.md).
3. **Publication precedes the doorbell.** `RGXSendCommandRaw` copies the actual command payload, publishes the KCCB write offset and issues `RGX_CR_MTS_SCHEDULE`; ring consumption is not command execution. Return-slot waiting is command-specific.
4. **Keep diagnostics independent.** Firmware trace/assert/FWCCB reset/page-fault/debug notifications and pre-health HWR history must be inspected even if later health passes. The 24.2/26.1 TA message has a stock 26.1 workaround; `process_st_info(278)` remains unresolved rather than automatically fatal or benign.

### 2.3 Firmware memory contexts, client CCB, KICK and UFO

Primary files:

- [`rgx_fwif_shared.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgx_fwif_shared.h): UFO, CCCB control, common context and reset framework.
- [`rgx_fwif_km.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgx_fwif_km.h): firmware memory context, KCCB commands, KICK data, client command types and MMUCACHE flags.
- [`rgxfwcmnctx.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwcmnctx.c): common-context lifecycle, CCB state, cleanup and stall handling.
- [`rgxkicksync.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxkicksync.c): GP/KickSync submission shape.
- [`rgxta3d.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/volcanic/rgxta3d.c): TA/3D streams, fence/update lists, write-offset/wrap updates and cleanup references.
- [`rgxcompute.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxcompute.c): CDM common context and compute submission.
- [`rgxccb.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxccb.c): client-ring write/dependency/read offset operations.

The reusable model is **firmware common context + firmware memory context + client circular command buffer + KCCB KICK**. The KICK names the common-context firmware pointer and the just-published client write offset/wrap mask. FENCE/NULL/UPDATE operate on UFOs; the client control has read, write and dependency offsets. Cleanup references retain resources after submission.

**Address-form correction that all facets must keep:** `RGXFWIF_FWMEMCONTEXT.sPCDevPAddr` is an `IMG_DEV_PHYADDR`, so the empty M3 catalogue uses its backing DMA/physical address (`GTA_CARVEOUT_PA + pc_offset` while the route is identity), **not** `GTA_DEVVA_HEAP + pc_offset`. Coremem and `sCCBMetaDMAAddr` do use the raw firmware-heap GPU VA. `psCCB`, `psCCBCtl`, `psFWMemContext`, KICK `psContext` and UFO addresses use 32-bit RISC-V firmware pointers. [MMU.md §0/§3](MMU.md) is the current correction; do not resurrect the older raw-heap-for-everything shortcut.

There is no separate “register memory context” KCCB opcode in the matched source: `RGXRegisterMemoryContext` creates/initializes the object and the common context references it. See [`rgxmem.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmem.c) and [MMU.md §5](MMU.md).

### 2.4 MMU/cache, render and compute resources

- Exact Volcanic definitions: [`rgxmmudefs_km.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/rgxmmudefs_km.h), [`rgxheapconfig.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgxheapconfig.h), [`rgxmmuinit.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmmuinit.c), and [`mmu_common.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/common/mmu_common.c).
- MMU v4 is not the old Rogue encoder: 40-bit walks use PC/PD/PT and global range selection for 16 KiB pages. Publish child data/tables, parents, catalogue, then a completed firmware MMUCACHE sync before KICK; unmap requires another completed invalidation before release. MMUCACHE is not an SLC/output-data flush.
- Rendering needs more than VDM bytes: TA/3D common contexts, PDS programs/static state, HWRT data, PM region headers/tail-pointer cache, freelists, context-switch state, attachment/cache handling and completion. Compute needs its own CDM/PDS/USC state and must not imply render readiness.
- TEE premap reference: [`rgxhal_fw_premap.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/hal/env/tee/rgxhal_fw_premap.c). Keep firmware mappings separate from client mappings.

## 3. Mainline Imagination `drm/pvr` and Mesa PowerVR

### 3.1 Mainline driver: excellent design reference, not a DXT driver

The current [support list](https://docs.kernel.org/gpu/imagination/index.html) is AXE-1-16M (33.15.11.3), BXM-4-64 MC1 (36.52.104.182), and BXS-4-64 MC1 (36.53.104.796). It does **not** list BVNC 71.2.2448.1212. [Mesa's hardware table](https://docs.mesa3d.org/drivers/powervr.html) likewise covers older Rogue cores, not Volcanic DXT. Therefore upstream `pvr` and Mesa cannot simply probe our phone.

Useful files and facts:

- [`pvr_fw.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_fw.c): validates firmware BVNC/layout, builds OSINIT/SYSINIT and creates KCCB/FWCCB before boot. [`pvr_fw_riscv.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_fw_riscv.c) is useful RISC-V background, but Pixel's secure start path remains authoritative.
- [`pvr_ccb.c`](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination/pvr_ccb.c): ring reservation, return-slot waiting and firmware-message dispatch. [`pvr_rogue_fwif_shared.h`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_rogue_fwif_shared.h) documents read/write/dependency offsets and runnable versus fence-blocked commands.
- [`pvr_vm.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_vm.c) and [`pvr_mmu.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_mmu.c): explicit VM handles, mapping rollback, firmware memory contexts, cache flush before jobs, immediate flush/wait after unmap, and device-loss on failed invalidation. Use these ownership rules, not its old PTE encoding.
- [`pvr_queue.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_queue.c), [`pvr_job.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_job.c), [`pvr_sync.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_sync.c): geometry/fragment/compute/transfer jobs, syncobj/timeline dependencies and completion/resource release.
- [`pvr_free_list.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_free_list.c), [`pvr_hwrt.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_hwrt.c), [`pvr_stream.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_stream.c): TBDR freelists/HWRT and static VDM/PDS/EOT/support streams.
- The [UAPI](https://docs.kernel.org/gpu/imagination/uapi.html) exposes BVNC, runtime quirks, VA heaps, BOs, VM map/unmap, typed contexts, HWRT and explicit sync operations. The [Asahi UAPI review](https://lkml.indiana.edu/2503.2/10227.html) explicitly says several canonical names were taken from this driver, making it a useful ABI-design cross-reference.

### 3.2 Mesa and open hardware descriptions

[Mesa PowerVR](https://docs.mesa3d.org/drivers/powervr.html) supplies a Rogue Vulkan driver and `drm-shim` for offline compiler/control-stream testing. [CSBGEN](https://docs.mesa3d.org/drivers/powervr/csbgen.html) documents generated CDM, CR, IPF, LLS, PBESTATE, PDS, PPP, TEXSTATE and VDM structures, including stream termination/link rules, context state, PM and cache-related registers. This is a good model for owned packet generation, disassembly and negative tests.

It is not a DXT compiler. A Metal-on-Vulkan design would need a new DXT Vulkan backend or an equivalent direct DXT stream writer; `metal2vulkan` does not remove that work. Do not infer shader/ISA compatibility from the shared PowerVR name or reuse Rogue PDE page-size/pending fields, opcodes, packet generators or workarounds without Volcanic evidence.

## 4. Asahi AGX: closest architectural analog to `AGXAccelerator`

### 4.1 Firmware, MMU and command path

Start with [Lina's AGX notes](https://asahilinux.org/docs/hw/soc/agx/) and the [`drm/asahi` driver](https://github.com/AsahiLinux/linux/tree/asahi/drivers/gpu/drm/asahi):

- AGX is heavily PowerVR-inspired but bespoke, brokered by an ARM64 ASC running Apple firmware. Communication uses shared-memory channel rings and mailbox doorbells.
- [`initdata.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/initdata.rs) constructs the persistent nested init graph; [`gpu.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/gpu.rs) starts RTKit and publishes it. The useful rule is to complete and retain all init objects before start, not any AGX value.
- UAT is ARM64-like with 16 KiB pages and a firmware/kernel split. [`mmu.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/mmu.rs) manages per-VM roots, context slots, cached-to-uncached remap, TLB/firmware flush and deferred teardown. DXT MMU v4 and firmware memory contexts are different; use only the ownership model.
- [`workqueue.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/workqueue.rs) implements typed vertex/fragment/compute queues as rings of pointers to work items. A channel message carries queue pointer, new write pointer, completion event slot and first-submission flag. [`microseq.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/microseq.rs) supplies start/timestamp/wait/finish operations; tiler resources and partial-render handling are firmware-assisted.
- [`event.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/event.rs) uses monotonically increasing shared-memory stamps. Queue completion reaps work and releases resources only after the corresponding stamp; faults distinguish timeout, MMU fault, killed work and device loss.
- The [`m1n1` AGX structures](https://github.com/AsahiLinux/m1n1/tree/main/proxyclient/m1n1/fw/agx) (`initdata.py`, `channels.py`, `cmdqueue.py`, `microsequence.py`) are useful independently inspectable models for the same stages.

These are process analogies to SYSINIT/KCCB/CCCB/UFO, not source-compatible contracts. Do not transplant UAT PTEs, TTBAT, RTKit, work-item layouts, microsequences, stamp increments, tiler heaps or AGX ISA.

### 4.2 UAPI and explicit-sync lessons

The [`asahi_drm.h` UAPI](https://github.com/AsahiLinux/linux/blob/asahi/include/uapi/drm/asahi_drm.h) provides VM create/bind, GEM create, queue create and submit. Its flat submission buffer contains no CPU pointers and was deliberately made suitable for a virtgpu wire protocol. Queues belong to VMs; jobs use binary/timeline sync objects and in-command VDM/CDM barriers; render and compute carry VDM/CDM control-stream addresses and pass-scoped state.

Two design rules apply strongly:

1. **Hide unstable firmware ABI behind a stable owned ABI.** The kernel marshals pass state instead of exposing firmware-private layouts to every client. HMGU should similarly validate/version its own BO/context/submit ABI rather than leaking arbitrary firmware pointers.
2. **Completion is not submission.** [Paving the Road to Vulkan](https://asahilinux.org/2023/03/road-to-vulkan/) explains explicit in/out sync objects, bridging implicit buffer sharing, retaining submitted batches until actual completion, and retroactively attaching fences when a buffer becomes shared after submission. Those are exactly IOSurface/compositor hazards.

The [Mesa Asahi documentation](https://docs.mesa3d.org/drivers/asahi.html) supplies VDM/CDM vocabulary, background/end-of-tile programs, image layouts and a `wrap.dylib` reverse-engineering method. [AsahiLinux/gpu](https://github.com/AsahiLinux/gpu) is the userspace compiler/control-stream reference. AGX's fixed-function interpolation differs from PowerVR's PDS-based approach, so use its proof and packaging methods rather than packets.

## 5. Apple's Metal/iOS graphics on non-Apple GPUs

There **is** relevant prior art. It is not a drop-in DXT solution, but it disproves the idea that a custom Metal backend is unprecedented.

### 5.1 UniXNU AdrenoMetal — closest iOS/compositor precedent

[`UniXNU/AdrenoMetal`](https://github.com/UniXNU/AdrenoMetal) (MIT) implements a Metal frontend through `metal2vulkan` and Mesa Turnip. **EXTERNAL-REPORT:** GPU composition is verified on `sheng` with Adreno 740. Its [documentation](https://unixnu.com/drivers/adreno-metal) describes AIR→SPIR-V→Turnip, single-sample policy, resource aliasing, swizzles, copies, function constants, queue priorities and shared shader caches.

Important extracted facts:

- [`NativeAdrenoMetalPlugin.mm`](https://github.com/UniXNU/AdrenoMetal/blob/243d63cf43305a85c8119b66b49cb7df4b30b019/NativeAdrenoMetalPlugin.mm) explicitly uses our discovery chain: `IOAcceleratorES → MetalPluginName → NSBundle → principal class → initWithAcceleratorPort:`. It dynamically subclasses the target `_MTLDevice`, adds `MTLDeviceSPI`, keeps the registry ID, and rejects an unexpected private-base size. This is a custom driver, not Apple AGX emulation.
- [`NativeAdrenoAccelerator.cpp`](https://github.com/UniXNU/Adreno740/blob/6fa7bae2a5b3b523e790eb3e0348af4d98969e4d/NativeAdrenoAccelerator.cpp) defines a foreign `AGXAccelerator : IOAcceleratorES`; [`GpuPowerProbe.cpp`](https://github.com/UniXNU/UniXNU-sheng/blob/965460a9ac1715636c769634fd0d69f58b2bd0f9/package/GpuPowerProbe.cpp) publishes the plugin properties under the platform. [IOACCEL.md](IOACCEL.md) maps the useful parts and why we keep one object rather than its split backend/registry arrangement.
- [`NativeBridgeMetalFrontend.mm`](https://github.com/UniXNU/AdrenoMetal/blob/main/NativeBridgeMetalFrontend.mm) separates device/resource/encoder objects, IOSurface imports, event/fence behavior, completion and presentation. It retains no-copy/surface owners through completion, hashes sampled surfaces before/after GPU work for validation, and uses real completion rather than a fabricated status.
- [`GpuScanoutPresenter.h`](https://github.com/UniXNU/AdrenoMetal/blob/main/GpuScanoutPresenter.h) copies completed BGRA frames or converts half-float frames into scanout memory. This validates our initial CPU-copy/blit presentation route if fenced; it is not a zero-copy shortcut.
- The project has focused host tests for [QuartzCore blur, surface import/flush, present, selector coverage and resource lifetime](https://github.com/UniXNU/AdrenoMetal/tree/main/bridge). Its [frame diagnostics](https://unixnu.com/porting/gpu-diagnostics) join allocation, encoding, submission, completion, GPU pass and display timing while explicitly excluding pixel capture from ordinary tracing.

Use its frontend patterns and tests where licensing/provenance allows. Turnip is Adreno-specific and supplies nothing for Tensor DXT firmware, VM, CDM/VDM or shaders.

### 5.2 `metal2vulkan`: reusable frontend/validation architecture

[`steelbrain/metal2vulkan`](https://github.com/steelbrain/metal2vulkan) parses Metal AIR/metallib, translates pipelines to SPIR-V, and provides a Metal-shaped runtime over Vulkan. Its [runtime README](https://github.com/steelbrain/metal2vulkan/blob/master/crates/metal2vulkan-runtime/README.md) covers queues, encoders, buffers, textures, heaps, events, hazard tracking, host-memory imports and explicit typed failures.

Especially relevant:

- [RUNTIME-PORTING](https://github.com/steelbrain/metal2vulkan/blob/master/docs/RUNTIME-PORTING.md) is a large Metal-selector-to-runtime map, including private calls. Unsupported inputs fail typed rather than silently substituting behavior.
- The runtime requires Vulkan 1.2 and timeline semaphores. It tracks resources used by each command buffer until completion and supports host-memory/no-copy imports, fences/events and explicit Vulkan semaphore interop.
- **IOSurface, Mach VM, drawables and presentation are deliberately consumer responsibilities**, not provided by the runtime. This confirms our HMGU/IOSurface/AppleCLCD work remains necessary even if the frontend is reused.
- [VALIDATION](https://github.com/steelbrain/metal2vulkan/blob/master/docs/VALIDATION.md) compares authored cases against Apple Metal, uses bounded waits, a GPU-hang tripwire, known outputs and explicit stale-result rules. [METAL-COVERAGE](https://github.com/steelbrain/metal2vulkan/blob/master/docs/METAL-COVERAGE.md) shows this is substantial but not full Metal—do not advertise completeness from the frontend alone.
- [NATIVE-METAL-UPSTREAM](../../docs/NATIVE-METAL-UPSTREAM.md) already selects the independent AIR crate for our native adapter. Preserve the existing review/pin rather than importing the whole Vulkan stack incidentally.

### 5.3 HakiOS Metal: early selector/discovery and failure lessons

[HakiOS Metal at `9d52b514`](https://github.com/oosexgang/hakios-metal/tree/9d52b5142542a253b7263a0d7889ad278e5c7693), particularly [`plugin/HakiosMetal.m`](https://github.com/oosexgang/hakios-metal/blob/9d52b5142542a253b7263a0d7889ad278e5c7693/plugin/HakiosMetal.m), is another direct custom-plugin precedent. The [project narrative](https://hackios-web.vercel.app/en/docs/metal-plan) records:

- `_MTLAddDevice` checks both public `MTLDevice` and private `MTLDeviceSPI` conformance.
- Early calls include `featureProfile`, `maxBufferLength`, command-queue creation, `setCompletionQueue:`, `setGPUPriority:` and `newDepthStencilStateWithDescriptor:`.
- A property/device stub moved backboardd from “no Metal device” to failure on the next missing object. Restricting which process sees the device is necessary during bring-up.
- CoreAnimation next required its own `default.metallib`; frontend presence is not a compositor renderer.

This directly supports our owned-process-first rule and explicit unsupported-selector failures.

### 5.4 NullMoth and WTLIntelGfx: macOS foreign-GPU integration

[`nullmoth/nvidia-macos-driver`](https://github.com/nullmoth/nvidia-macos-driver) implements NVIDIA kernel/display/accelerator drivers and an `NVMTLDriver.bundle`: AIR→SPIR-V→Mesa NVK. Its [architecture document](https://github.com/nullmoth/nvidia-macos-driver/blob/main/docs/HOW-IT-WORKS.md) separates `NVRM`, `NVRMFB`, `NVAccel` and `NVRMAGDC`, with IOSurface and WindowServer integration. [`NVMTLDevice.m`](https://github.com/nullmoth/nvidia-macos-driver/blob/main/plugin/NVMTLDevice.m) subclasses `MTLIOAccelDevice`, which is a different/larger path than our custom HMGU plugin. Its event/sync code joins IOSurface dirty state, GPU completion, publication and presentation.

[`WTLIntelGfx`](https://github.com/watchthelight-labs/WTLIntelGfx) ports Linux i915 through FreeBSD drm-kmod/LinuxKPI onto XNU, adds Mesa ANV and a NullMoth-derived Metal plugin. **EXTERNAL-REPORT:** its [status/milestone log](https://labs.watchthelight.org/WTLIntelGfx/) records guarded compute and triangle readback, WindowServer on Intel, and Dock Liquid Glass on macOS 26. Relevant lessons:

- Sandboxed WindowServer could not open `/dev/dri`; it needed the accelerator's IOKit user client. Our process entitlements/sandbox must be tested separately from registry matching.
- Host-visible cache attributes and non-writable/no-copy WindowServer buffers caused real failures. Do not assume every imported IOSurface is writable, contiguous or suitable for zero-copy.
- A copy into the firmware framebuffer was a valid correctness path while full display-pipe integration was absent. Presentation still had to wait for GPU completion.
- The XNU compatibility-shim approach is possible but large; it does not make mainline `pvr` DXT-compatible or remove the Metal/IOSurface contract.

These projects use different OS ABIs and mixed licenses (including PolyForm Noncommercial for NullMoth-derived components). Read for behavior and proof design; do not copy their code into our tree under an assumed MIT license.

### 5.5 ios-tegu — closest iOS 26 / XNU 12377 foreign-Metal implementation

[`dgigantino/ios-tegu`](https://github.com/dgigantino/ios-tegu) (private repository; supplied archive at commit [`8e2d75bb`](https://github.com/dgigantino/ios-tegu/commit/8e2d75bb19068be7cd157da46c13b2a4cf9ac689)) targets Pixel 9a/Tensor G4 with Mali G715-class Valhall CSF (`GPU_ID=0xb8a21030`), XNU 12377 and an iPhone 11 Pro/iOS 26.6.2 userland. **EXTERNAL-REPORT:** its [status document](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/TEGU.md) says iOS 26 reaches a working but buggy UI using the ported Metal driver; Liquid Glass correctness/completeness and sustained full acceleration remain unverified. This is important OS-ABI prior art, not DXT hardware evidence.

High-value extracted lessons:

- [`METAL-REARCH.md`](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/docs/METAL-REARCH.md) moves to persistent per-process GPU VAs: buffers/textures/IOSurfaces map once at creation, ownership is checked at submission, and a Metal render encoder becomes a pass-level tiler/fragment job chain rather than one job per draw. Later phases add async submission/completion, native RGBA16F/MRT/MSAA, threadgroup-memory compute and pipeline packs. Keep those architecture/resource ideas; use none of the Mali CSF words or formulas.
- The iOS 26 compatibility work includes FAT-metallib AIR selection, private device-limit/queue/resource updates and shared-buffer texture views. Deep/compressed framebuffer preferences are disabled so the display gets plain BGRA rather than an unsupported Apple layout. That matches [METAL.md](METAL.md)'s plain-BGRA-first policy.
- [`VERIFICATION.md`](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/docs/VERIFICATION.md) records concrete failure mechanisms rather than just success: IOSurface CPU-shadow fallbacks for unsupported rows/formats; memoryless attachment state lost across split passes; GPU-write marks cleared only at actual job completion so unfinished frames are held from scanout; and shader plan cache keys that must preserve each resource's real offset/length rather than presence alone. These are direct test cases for agents 5/7/8.
- Commit [`8e2d75bb`](https://github.com/dgigantino/ios-tegu/commit/8e2d75bb19068be7cd157da46c13b2a4cf9ac689) addresses a 1 GiB-per-client VA-pressure failure: a 320 MiB pool allowed roughly 889–905 MiB mapped, new targets could not map and their draws became black squares. The fix lowers the pool to 192 MiB and drains/retries failed maps. It also tightens late transfer-edge rejection. The lesson is to account VA pressure and drop/refusal counters before adding more rendering features, not to equate pool size with correctness.
- [`IOSURFACE_PLAN.md`](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/tools/tegu/metal/IOSURFACE_PLAN.md) requires eligible backing, per-page validation, retention through submission and uncertain-completion quarantine, then the existing CPU SwapEnd after a fence. [`RENDER_PASS_PLAN.md`](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/tools/tegu/metal/RENDER_PASS_PLAN.md) requires checked width/height/stride/span, all target pages mapped, tiler resources derived from target features, and explicit load/store semantics across repeated draws. [`CODE_ONLY_RENDER_FIXES.md`](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/tools/tegu/metal/CODE_ONLY_RENDER_FIXES.md) adds viewport/scissor, empty-draw, indexed-resource, ordered mip-source and producer/consumer hazard cases.

No root `LICENSE` is present in the supplied repository archive. Read its findings and compare behavior only; do not copy unlicensed source. Its Mali CSF firmware, MMU, CSF queues, tiler heap formulas, hardware words and driver code are inapplicable to PowerVR DXT. Existing inventory in [NATIVE-METAL-UPSTREAM](../../docs/NATIVE-METAL-UPSTREAM.md) reaches the same conclusion.

### 5.6 Virtio-gpu and virtualization: no shortcut found

- Asahi's UAPI is intentionally easy to serialize for virtgpu, but that is a wire-format design, not an iOS Metal driver.
- `metal2vulkan-runtime` explicitly documents a paravirtualized-GPU consumer seam, but its consumer still owns IOSurface, identifiers, drawables and presentation. It is not a stock `virtio-gpu` implementation for iOS.
- Gfxstream/MoltenVK and Apple Virtualization.framework solve different problems: host API translation or Apple's own GPU-backed virtual machine contract. Neither supplies a native PowerVR DXT backend for Apple's iOS Metal/QuartzCore stack.

Within the reviewed public work, no project removes the need for our real `_MTLDevice`, DXT compiler/control streams, VM, firmware submission, fences and presentation. Native is not improved by inserting a virtual GPU protocol.

## 6. Facet-by-facet reading and application guide

### Agent 1 — coremem / init

**Read first:** [`rgxfwutils.c` `RGXSetupFwSysData`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c), [`rgxinit.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/volcanic/rgxinit.c), [`gpu_secure.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure.c), and [COREMEM-INIT.md](COREMEM-INIT.md).

**Apply:** write `0xE1C013C000` at `+0x150` before barrier/SMC; keep PA/FWVA/raw device VA distinct; make S1 fail closed on pre-health fault/HWR. Asahi `initdata.rs` reinforces persistent complete init graphs only.

### Agent 2 — firmware / Trusty / lifecycle / IRQ

**Read first:** [`gpu_secure_protocol.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure_protocol.h), [`gpu_secure.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure.c), [`rgxpower.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxpower.c), [`rgxinit.c` LISR/MISR](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/volcanic/rgxinit.c), and [M2.md](../ios26-gpu-r1/M2.md).

**Apply:** SEND → shared init → power/start → started flag → stock health; HEALTH consumption is not execution, STATEFLAGS return is. Keep TA version/`278` as separate unresolved evidence. Implement secure STOP/gate/domain-off and actual IRQ mask/ack/drain before service use; polling is for bounded rungs only.

### Agent 3 — MMU / contexts / surfaces

**Read first:** [MMU.md](MMU.md), exact [`rgxmem.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmem.c), [`rgxmmudefs_km.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/rgxmmudefs_km.h), [`rgxheapconfig.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgxheapconfig.h), then mainline [`pvr_mmu.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_mmu.c) and Asahi [`mmu.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/mmu.rs).

**Apply:** root DMA versus firmware-heap GPU VA versus 32-bit firmware pointer; MMU-v4 ranges; completed invalidation before job/unmap release; per-page IOSurface ownership and separate SLC/CPU handback. Reject old Rogue PTEs and AGX UAT mechanics. Do not treat sync-only catalogue success as a real engine VM.

### Agent 4 — CCB / KICK / data-master streams

**Read first:** [`rgx_fwif_shared.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgx_fwif_shared.h), [`rgx_fwif_km.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgx_fwif_km.h), [`rgxkicksync.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxkicksync.c), [`rgxta3d.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/volcanic/rgxta3d.c), [`rgxcompute.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxcompute.c), and [`pvr_ccb.c`](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination/pvr_ccb.c).

**Apply:** common context + memory context + CCB + KICK; full stream before write offset, KCCB before MTS; payload size excludes 16-byte header; write/wrap in KICK; one outstanding ordered step and retained allocations. Asahi `workqueue.rs` is useful for typed queue/resource state only. No inferred CDM/VDM/PPP opcodes from mainline.

### Agent 5 — fences / completion / cache / lifetime

**Read first:** [`rgxta3d.c` fence/update handling](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/volcanic/rgxta3d.c), [`rgxccb.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxccb.c), [`pvr_queue.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_queue.c), [`event.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/event.rs), [Asahi explicit sync](https://asahilinux.org/2023/03/road-to-vulkan/), and [ios-tegu's verification record](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/docs/VERIFICATION.md).

**Apply:** host writes only sentinel; firmware UPDATE proves ordering; separate KCCB consumption, CCB parsing, engine completion, SLC writeback, CPU alias handback and release. Use timeline dependencies but do not let a host/API callback certify hardware. Preserve every resource through actual quiescence; late sharing needs the correct fence retroactively attached. Track ios-tegu's additional cases: clear write marks at real job completion, retain memoryless attachments across split passes, and bound VA/pool pressure before map failures silently drop targets.

### Agent 6 — IOAccel / service identity / user client

**Read first:** [IOACCEL.md](IOACCEL.md), [UniXNU accelerator](https://github.com/UniXNU/Adreno740/blob/6fa7bae2a5b3b523e790eb3e0348af4d98969e4d/NativeAdrenoAccelerator.cpp), [publication](https://github.com/UniXNU/UniXNU-sheng/blob/965460a9ac1715636c769634fd0d69f58b2bd0f9/package/GpuPowerProbe.cpp), [plugin](https://github.com/UniXNU/AdrenoMetal/blob/243d63cf43305a85c8119b66b49cb7df4b30b019/NativeAdrenoMetalPlugin.mm), and [Project Zero's IOGPU/AGX analysis](https://projectzero.google/2023/10/an-analysis-of-an-in-the-wild-ios-safari-sandbox-escape.html).

**Apply:** one real derived `AGXAccelerator` under the platform, same pointer for registry/HMGU/readiness, exact two properties, no duplicate bare service. Custom HMGU is sufficient; a guessed IOGPU selector surface is not. Capture sandbox/OPEN errors independently and keep CA off until the intended profile is ready.

### Agent 7 — Metal / AIR / render runtime

**Read first:** [METAL.md](METAL.md), [UniXNU frontend](https://github.com/UniXNU/AdrenoMetal), [metal2vulkan runtime/porting](https://github.com/steelbrain/metal2vulkan/blob/master/docs/RUNTIME-PORTING.md), [HakiOS plugin](https://github.com/oosexgang/hakios-metal/blob/9d52b5142542a253b7263a0d7889ad278e5c7693/plugin/HakiosMetal.m), [ios-tegu Metal re-architecture](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/docs/METAL-REARCH.md), [Mesa CSBGEN](https://docs.mesa3d.org/drivers/powervr/csbgen.html), and [NATIVE-METAL-UPSTREAM](../../docs/NATIVE-METAL-UPSTREAM.md).

**Apply:** custom `_MTLDevice` plus real queues/resources/encoders and typed unsupported behavior; reuse reviewed AIR parsing where useful; validate known compute/render outputs before CA. Preserve actual resource offsets/lengths and stage/pool identities in plan caches, and test unsupported surface formats with explicit shadow/refusal policy. `metal2vulkan` is an architectural option, not a DXT backend. Mainline Mesa and AGX packets are not compatible with Volcanic.

### Agent 8 — compositor / Liquid Glass / presentation

**Read first:** [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md), [METAL.md](METAL.md), [UniXNU diagnostics](https://unixnu.com/porting/gpu-diagnostics), [`GpuScanoutPresenter.h`](https://github.com/UniXNU/AdrenoMetal/blob/main/GpuScanoutPresenter.h), [UniXNU blur/present tests](https://github.com/UniXNU/AdrenoMetal/tree/main/bridge), [NullMoth sync](https://github.com/nullmoth/nvidia-macos-driver/blob/main/plugin/NVMTLEventSync.m), [WTLIntelGfx lessons](https://labs.watchthelight.org/WTLIntelGfx/), [ios-tegu verification and presentation findings](https://github.com/dgigantino/ios-tegu/blob/8e2d75bb19068be7cd157da46c13b2a4cf9ac689/docs/VERIFICATION.md), and [Asahi explicit sync](https://asahilinux.org/2023/03/road-to-vulkan/).

**Apply:** plain BGRA first, exact shader/pass inventory, real context class and joined submit/done IDs, surface ownership until GPU+DPU finish, and known blur/vibrancy pixels. A CPU-copy/blit to scanout is valid initially only after the same completion/cache fence; ordinary DPU frames and a non-nil Metal device prove nothing by themselves. Include ios-tegu's split-pass attachment retention, stale vertex-offset, unsupported-row shadow, VA-exhaustion and held-unfinished-frame cases in the compositor oracle.

## 7. Practical recommendations for this composition

1. **Do not add another backend.** Continue the current native HMGU/HMNativeMetal design. Use the matched DDK for every firmware/VM/opcode/layout question.
2. **Use prior art to strengthen tests, not to inflate milestones.** S1 clean init, S4 KickSync, C1 compute, R1 registry, M1 device, M2 render and G1 compositor are distinct. No external project's success substitutes for our phone receipt.
3. **Prefer the existing reviewed AIR reuse path.** The AIR crate is separable from Vulkan. If Metal-on-Vulkan is reconsidered later, first price a DXT Vulkan backend honestly: mainline `pvr`/Mesa do not support BVNC 71.
4. **Copy proof techniques:** byte fixtures, packet disassembly, typed refusals, malformed inputs, bounded waits, timeout quarantine, stale-epoch rejection, guard words, exact pixels, and correlated submit/done/present traces.
5. **Keep security authority and cache/lifetime gates explicit.** REE SMMU bypass, a clean cache, KCCB progress, IOSurfaceLock, API `Completed`, and DPU activity are each only one part of the chain.
6. **Respect provenance.** Preserve the existing inventory in [NATIVE-METAL-UPSTREAM](../../docs/NATIVE-METAL-UPSTREAM.md): matched DDK, UniXNU MIT, reviewed AIR crate, Linux PowerVR. Do not import NullMoth/WTL/noncommercial code or a different DDK merely because it is newer. Vendor files vary between dual MIT/GPL and GPL-only; preserve per-file terms if anything is ever adapted.

## 8. Reference index by purpose

- **Exact hardware contract:** [Laguna DDK tree](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/tree/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr), [independent GitHub mirror](https://github.com/0xnullsect0r/android_kernel_google_gs-6.12_google-modules/tree/94d467217db3a10362aa3277dff8d347919497c6/powervr).
- **Open PowerVR implementation:** [Linux `drm/imagination`](https://github.com/torvalds/linux/tree/master/drivers/gpu/drm/imagination), [kernel UAPI](https://docs.kernel.org/gpu/imagination/uapi.html), [Mesa PowerVR/CSBGEN](https://docs.mesa3d.org/drivers/powervr/csbgen.html), [Imagination documentation portal](https://docs.imgtec.com/).
- **Open AGX implementation:** [AGX notes](https://asahilinux.org/docs/hw/soc/agx/), [kernel driver](https://github.com/AsahiLinux/linux/tree/asahi/drivers/gpu/drm/asahi), [UAPI](https://github.com/AsahiLinux/linux/blob/asahi/include/uapi/drm/asahi_drm.h), [m1n1 models](https://github.com/AsahiLinux/m1n1/tree/main/proxyclient/m1n1/fw/agx), [Mesa docs](https://docs.mesa3d.org/drivers/asahi.html), [userspace compiler](https://github.com/AsahiLinux/gpu).
- **Foreign Metal implementations:** [UniXNU AdrenoMetal](https://github.com/UniXNU/AdrenoMetal), [metal2vulkan](https://github.com/steelbrain/metal2vulkan), [HakiOS Metal](https://github.com/oosexgang/hakios-metal/tree/9d52b5142542a253b7263a0d7889ad278e5c7693), [NullMoth](https://github.com/nullmoth/nvidia-macos-driver), [WTLIntelGfx](https://github.com/watchthelight-labs/WTLIntelGfx), [ios-tegu](https://github.com/dgigantino/ios-tegu).
- **Our current facet contracts:** [PLAN.md](PLAN.md), [COREMEM-INIT.md](COREMEM-INIT.md), [MMU.md](MMU.md), [IOACCEL.md](IOACCEL.md), [METAL.md](METAL.md), [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md), [GPU investigation](../ios26-hw-investigation-r1/GPU.md).
