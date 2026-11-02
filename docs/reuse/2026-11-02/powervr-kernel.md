# PowerVR kernel and firmware reuse audit

Audit date: 2026-11-02. Target: native XNU 12377 on Tensor G5, GPU BVNC
71.2.2448.1212. Research only: no implementation changes, builds, firmware
downloads, emulator/device operations, or new physical results.

The best donor is already on disk: Google's Pixel Volcanic DDK, mirrored by
GrapheneOS. Its reusable parts are much closer to this GPU than mainline
PowerVR's Rogue driver. The main saving now is finishing the missing adapters
from that code and sharing one verified ABI profile across existing workers.
Starting a second GPU stack would duplicate substantial work.

## Verified sources and limits

- [GrapheneOS kernel_pixel_6.12, 5940a317](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/tree/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr)
  is the local `research/ios26-metal-r1/dl-gos` source. Public GitLab API verified
  the commit and byte-for-byte equality of five local files: FWIF, MMU init,
  firmware utilities, compute submission, and BVNC table.
- That pin is current `17-qpr3-base`, DDK **26.1@6967606**. Current `17-base`
  is `aa48564c6ea302cd64fb3fc620c5ff79893d3165`, DDK **25.3@6908880**.
  The local 6.6 pin `e214813c0aeb5bef8dbe45f53390ada8aabe8054` also says 25.3.
  Verified from each pin's `pvrsrvkm/include/pvrversion.h`; an older/stable
  Android branch does not automatically match the TA's logged expected 24.2.
- GitLab HTML fetches returned 403 in the web reader; its public repository
  API worked. The pinned links below identify the inspected source, not an
  unverified search result or a guessed GitHub mirror.
- [Linux 6628e7d4, Linux 7.4-rc1](https://github.com/torvalds/linux/tree/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination)
  was resolved through GitHub's public commit API. Targeted raw reads verified
  `pvr_device.c`, `pvr_mmu.c`, `pvr_queue.c`, and the documentation entry point.
- Current [driver support documentation](https://docs.kernel.org/gpu/imagination/index.html)
  and pinned `pvr_drv.c` list AXE-1-16M, BXM-4-64 MC1 and BXS-4-64 MC1.
  They do not establish support for this DXT. Imagination's own
  [open-driver page](https://developer.imaginationtech.com/solutions/open-source-gpu-driver/)
  describes ongoing architecture expansion; that is not a DXT execution result.

## 1. Reuse the exact Volcanic MMU and memory-context logic

**Priority P0; high confidence in source relevance; direct code/format reuse
is feasible, while hardware operation remains unproved.**

- [rgxmmuinit.c: RGXMMUInit, MMU4 page configurations](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmmuinit.c)
  explicitly handles MMU4, including its absence of the old PDE page-size and
  PENDING fields. Its 16 KiB path is the relevant starting point for XNU.
- [rgxmem.c: RGXRegisterMemoryContext, RGXUnregisterMemoryContext](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmem.c)
  supplies the missing bridge between a page-catalogue address and an actual
  firmware-visible `RGXFWIF_FWMEMCONTEXT`, including initialization and flush.
- [Volcanic BVNC table](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/rgx_bvnc_table_km.h)
  contains the exact 71.2.2448.1212 errata row; its BNC feature row uses V=0.
  This distinction matters when deriving MMU version, widths and quirks.
- Licence: inspected Imagination file headers offer **MIT or GPLv2**. Preserve
  the MIT notices on copied or adapted portions. This does not cover every
  file in the surrounding Pixel directory.
- Already local: `ios26-metal-native-20261102/vm/src/hmg_dxt_mmu.c` implements
  16 KiB entry/range codecs; `vm/receipts/evidence.json` records MMU4, 40-bit
  PA/VA and the exact feature row. Its source and evidence agree with the
  inspected donor. Rewriting that codec would save no work.
- Missing seam: `hmg_vm` hardware `attach/invalidate/detach_quiesce` and queue's
  `hq_native_builders.fw_memory_context`. The real descriptor and firmware
  allocation must be retained; a GPU VA is not a firmware address.
- Smallest host proof: extend the existing vendor-header layout probe to
  emit `FWMEMCONTEXT` offsets and compare the actual adapter's initialized
  bytes against them, with guarded pages and allocation/cache-error injection.
  Exercise actual `hmg_vm_publish` through the concrete adapter; refuse on
  missing profile, bad live range readback, invalid root address or uncertain
  publication. Emit gated ARM64 objects and inspect their adapter symbols.
- Dependencies: genuine firmware heap, known matching ABI, live identity/IOVA
  route, real global range/USC/PDS-base verification and completed invalidation.
  Earlier SMMU bypass evidence does not satisfy current live-route checks.
- Labour saved: reuses documented DXT mapping and context initialization,
  avoiding another round of guessing table geometry and firmware pointers.

## 2. Reuse firmware MMU invalidation and acknowledged cleanup

**Priority P0; high confidence; adapt selected MIT-side routines and protocols.**

- [rgxfwutils.c: RGXMMUCacheInvalidate, RGXMMUCacheInvalidateKickAndWait](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c)
  accumulates PC/PD/PT/TLB flags, submits firmware cache commands and waits for
  the associated synchronization update. CPU DC clean/invalidate alone is
  not the GPU's MMU-cache completion.
- The same file's `RGXScheduleCleanupCommand` and
  `RGXFWRequestCommonContextCleanUp` give the actual command and reply flow.
  A cleanup BUSY result means retry/retain; consumption of a KCCB entry is
  not proof that a context's DMA has stopped.
- Licence: the inspected file is dual MIT/GPLv2. Its full dependency tree is
  much larger than the needed adapter; transplanting it wholesale would drag
  in power locking, Services memory objects, sync primitives and OS wrappers.
- Already local: p29 `bsd/dev/blazer_gpu_tipc.c` requires a fresh health return
  slot; `firmware/src/hmfw_lifecycle.c` implements a retained shared-allocation
  broker; `queue/src/hmg_queue_xnu.cpp` already constructs common-context
  cleanup and rejects anything other than its accepted raw execution result.
- Remaining value: implement the real VM invalidation backend and reconcile
  context-scoped cleanup with allocator reclamation. The current firmware
  allocator conservatively keeps exposed allocations until global quiescence;
  a successful per-context cleanup does not currently authorize arbitrary free.
- Smallest host proof: one concrete invalidation adapter, tested against
  delayed/wrong sync updates, lost KCCB publication and cleanup BUSY. Verify
  no retired table/backing is released after timeout or uncertain publish.
  Model tests check ownership/order; they cannot prove hardware coherency.
- Dependencies: serialized actual KCCB broker, real sync allocation/readback,
  generation identity and matching firmware ABI. A health command is neither
  an application engine fence nor proof of VM readiness.
- Labour saved: the driver already specifies ordering and retry semantics;
  adapting them is considerably smaller than designing another lifetime model.

## 3. Reuse compute-context and CCB construction, keep the native Metal route

**Priority P1; high source confidence; direct selected adaptation, substantial
local overlap, still blocked by shader/state and real backend integration.**

- [rgxcompute.c: PVRSRVRGXCreateComputeContextKM, PVRSRVRGXKickCDMKM](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxcompute.c)
  shows compute suspend state, common-context allocation and CDM KICK setup.
- [rgxfwcmnctx.c: FWCommonContextAllocate](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwcmnctx.c)
  is a more useful donor for native context initialization than the generated
  Linux ioctl bridge. These Services routines use dual MIT/GPLv2 headers.
- The KICK carries the firmware common-context address plus CCB write offset
  and wrap mask. It does not turn a userspace stream into a valid DXT shader.
- Already local: `queue/tools/layout.c` measures actual vendor structures;
  `queue/src/hmg_queue.c` builds CDM followed by an engine UFO UPDATE and
  distinguishes engine completion from KCCB acknowledgement. Its native
  adapter directly calls current firmware/UC/VM APIs rather than pretending
  an injected model is a hardware backend.
- Missing concrete callbacks are named in `queue/include/hmg_queue_xnu.h`:
  `fw_memory_context`, `init_compute_state`, `fini_compute_state`,
  `build_compute`. This is an integration list, not four new GPU projects.
- Smallest host proof: adapt only compute static/suspend-state initialization
  from the pinned donor, compare bytes and field offsets with the donor layout
  probe, then exercise that callback in actual queue context creation. Keep
  dispatch unavailable while shader/stream validation is incomplete.
- Dependencies: native executable USC/PDS/CDM, verified VM and firmware ABI,
  exclusive CPU/cache ownership of submitted BOs, real matching engine UFO.
- Labour saved: avoids rediscovering firmware context shape and publication
  flow. It does not remove the remaining DXT compiler or Metal ABI work.

## 4. Linux PowerVR supplies useful lifetime examples, not a DXT port

**Priority P2; high confidence as reference; low direct transplant value.**

- [pvr_queue.c: pvr_queue_process, pvr_queue_cleanup_fw_context](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination/pvr_queue.c)
  provides compact examples of UFO-backed job fences, queue retention and
  firmware context cleanup.
- [pvr_mmu.c: pvr_mmu_flush_exec](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination/pvr_mmu.c)
  is a useful cross-check on deferred flush and synchronization design.
- Both inspected files explicitly offer **GPL-2.0-only OR MIT**. Their Linux
  scheduler/GEM/GPUVM dependencies require separate licence checks and replacement
  on XNU. Their firmware/MMU includes are explicitly `pvr_rogue_*`.
- Already local: a linux-next donor exists at `bd1ecbb61afefc6a8b876ccbc31e9228b44e9eab`;
  native queue code already has reference and generation checks. Another clone
  is unnecessary. No Vulkan/Mesa production-path switch is recommended.
- Smallest useful task: compare our existing teardown/uncertain-publication
  cases with these source paths, adding only a missing failure scenario that
  reaches actual native queue code. Do not port `drm_sched` to get a fence.
- Labour saved: mature examples help avoid lifetime mistakes; they do not
  supply this DXT's page tables, firmware build, shader ISA or Metal driver.

## First integration-sized task

Consolidate existing firmware/queue/VM layout probes into one generated,
versioned profile manifest before expanding dispatch. Include donor commit,
per-file hashes, BVNC, DDK/build, conditional build defines, ABI/layout version,
FW/KCCB/context sizes and MMU/heap facts. Consume it from all three adapters
and reject disagreement. Retain donor notices on any adapted definitions.

This extends `firmware/tools/measure_vendor.py`, `queue/tools/layout.c` and
`vm/receipts/evidence.json`; it should not create a fourth set of constants.
The host acceptance is agreement of independently measured values plus
deliberate mismatch refusal in actual adapters. Physical compatibility and
execution still require the phone coordinator's separate test evidence.

## Dead ends and cautions

- Pixel `gpu_secure.c` and `gpu_secure_protocol.h` are **GPL-2.0**, not covered
  by the nearby Imagination dual licence. Read them as protocol references or
  handle their actual terms; do not label the whole vendor tree MIT.
- Generic SGX, MT6768 Rogue, Adreno HakiOS and Mali/Tensor G4 drivers do not
  provide DXT instruction/state formats. PowerVR branding alone is insufficient.
- The 25.3 and 26.1 source profiles differ. Signed firmware SEND acceptance
  does not establish host/FW layout compatibility, engine execution or support
  for mixing structures across releases. Do not change firmware on this evidence.
- No source examined supplies an already-working native iOS26 DXT Metal stack.
  No speedup, rendering result or device readiness is claimed by this audit.
