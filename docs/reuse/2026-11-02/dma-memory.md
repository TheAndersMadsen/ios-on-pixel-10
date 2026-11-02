# DMA, memory ownership and IOMMU reuse audit

Reviewed 2026-11-02, host/static research only. No builds, guests, device access,
firmware operations or implementation changes were performed by this audit.

The strongest saving is to **compose the allocator and surface work already
written**, using upstream formats and tests as independent checks. A second
generic DMA allocator or a wholesale Linux dma-buf port would duplicate work.
Native rendering and physical DMA coherency remain unproved.

## Current local overlap

Observed release source: `research/ios26-release-r1/work/xnu`, commit
`237e3889640333558525c8082593e68cc5401405` (p29).

- `iokit/Kernel/arm/SweetSurface.cpp` already retains the surface/table slot,
  prepares its descriptor, walks real physical segments and keeps an import
  cookie. `sweet_surface_gpu_sync` enforces an exclusive cache owner; release
  refuses that owner while device access is outstanding. It does not freeze
  arbitrary existing user mappings or implement engine completion.
- `research/ios26-metal-native-20261102/vm/src/hmg_vm_xnu.cpp` already adapts
  IOBufferMemoryDescriptor, constrains actual allocations, balances
  prepare/complete and supplies explicit cache operations. Its adjacent core
  owns mappings, pinning, quarantine and teardown. This is newer host work,
  not evidence it is integrated into p29 or runs on the phone.
- The native `surfaces` worker already uses XNU UPL access blocking and a
  temporary kernel alias, with authority tied to a retained client reference.
  Read `surfaces/PROVENANCE.md` and the exact implementation before designing
  another CPU-exclusion mechanism. Its tests model XNU internals.
- The VM header explicitly requires genuine attach, MMU invalidation completion,
  DMA quiescence and GPU/SLC data visibility. Missing callbacks remain errors.
  These obligations are not supplied by IOBuffer allocation or a CPU barrier.

## 1. Matching Imagination Volcanic MMU code: high priority, high confidence

**Class:** directly adaptable, permissively licensed source; key formats are
already incorporated into the native VM worker. Reuse the existing consumer.

Local authoritative tree is GrapheneOS `kernel_pixel_6.12`, commit
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`, under
`private/google-modules/powervr/pvrsrvkm/`. The checked files carry individual
Dual MIT/GPLv2 notices permitting the MIT selection with notices preserved.

Exact source links:

- [Volcanic MMU definitions](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/rgxmmudefs_km.h).
- [rgxmmuinit.c, including the 16 KiB layout](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmmuinit.c).
- [MMU common management](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/common/mmu_common.c).
- [RGXRegisterMemoryContext](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmem.c).
- [RGXMMUCacheInvalidateKickAndWait](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c).

Observed exact profile in the native worker's source-backed evidence is BVNC
71.2.2448.1212, MMU4, 40-bit PA/VA. Its 16 KiB format has a 1024-entry 32-bit
catalogue, 512-entry 64-bit directory and 128-entry 64-bit table. MMU4 directory
entries do not encode the Rogue PAGE_SIZE/PENDING fields; ordered global page
size ranges select granules. This saves format rediscovery and prevents a
plausible but incorrect generic ARM/Rogue page-table implementation.

**Integration seam:** finish the existing `hmg_vm_hw_ops.attach`,
`invalidate_wait` and `detach_quiesce` composition with the queue/firmware owners.
Reuse vendor definitions and established completion rules rather than importing
the entire Services OS abstraction, PMR allocator and Linux integration.

**Smallest host proof:** compare actual emitted native PC/PD/PT bytes and range
selection against independently extracted vendor masks, including the tenth
catalogue index bit, 40-bit boundary, overlapping earlier ranges and absent
Rogue PDE fields. Existing `vm/tools/check-evidence.py`, `tests/test_vm.c` and
mutation receipts already cover several of these; extend them only for actual
remaining gaps. Do not claim that a source-profile check programs hardware.

**Missing:** live system DMA route, firmware memory-context publication,
authentic invalidation and visibility completion. GPU output addresses are not
automatically CPU physical addresses. Historical SMMU bypass is insufficient.
Web access to GitLab returned 403; the pin, code and licences were inspected in
the existing local git checkout, with its recorded remote, rather than guessed.

## 2. Apple OSS memory descriptors: high priority, already available

**Class:** use existing XNU APIs and reference tests; avoid another allocation,
pinning, scatter/gather or UPL implementation. Files retain APSL-2.0 notices.
Public reference pin verified through Apple's Git API: `xnu-12377.121.6`,
`ac9718fb1af618d5ce8678d0dc6e8a58f252216f`. This is a same-generation reference,
not a claim that p29 has every change from that release.

- [IOBufferMemoryDescriptor.cpp](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/iokit/Kernel/IOBufferMemoryDescriptor.cpp): existing constrained backing allocation.
- [IOMemoryDescriptor.cpp](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/iokit/Kernel/IOMemoryDescriptor.cpp): prepare/complete, physical segments and mapping redirection.
- [IODMACommand.cpp](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/iokit/Kernel/IODMACommand.cpp): segment constraints and output encoders.
- [TestIOMemoryDescriptor.cpp](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/iokit/Tests/TestIOMemoryDescriptor.cpp): `IODMACommandForceDoubleBufferTest`, `IODMACommandLocalMappedNonContig` and descriptor-boundary cases already exist locally.

**Useful seam:** retain the existing native VM's IOBuffer adapter. If another
driver needs bounded segment iteration, evaluate IODMACommand instead of writing
a parallel scatter/gather cursor. Its output encoders do not produce DXT PTEs.
Choose the physical/unmapped route explicitly until a real Tensor IOMapper
exists; default mapper discovery is not a Tensor implementation.

**Important compatibility limit:** adopting noncoherent IODMACommand does not
by itself prove actual cache maintenance on this port. Its prepare/complete
call IOMemoryDescriptor cache operations. The source contains coherent-Apple
paths that return success after barriers, and assembly has Apple-family gates.
Inspect effective BLAZER configuration and emitted cache instructions before
replacing the current explicit CTR_EL0-sized DC loops. This audit did not
establish the effective macro state or diagnose a physical cache failure.
[Apple cache backend](https://github.com/apple-oss-distributions/xnu/blob/ac9718fb1af618d5ce8678d0dc6e8a58f252216f/osfmk/arm/caches.c).

**Smallest host proof:** resolve the actual BLAZER cache macros and inspect an
explicitly gated ARM64 object before adopting the cursor's cache mode. Reuse
the existing descriptor tests as adapter fault scenarios. A subsequent
guest-only test using real descriptors should validate prepare/complete
balance, fragmented segments, failed completion retention, several existing
aliases and UPL block/unblock. A host stub cannot establish
that a real user alias faults/blocks. The surface worker already checks that
successful redirect actually produced a full-size `fRedirUPL`; preserve that
check because the return code alone does not establish exclusion.

## 3. Linux reservation tests: medium priority, useful independent coverage

**Class:** adaptable MIT test code/algorithms, rather than a full Linux port.
Verified stable reference: Linux v6.12,
`adc218676eef25575469234709c2d87185ca223a`.

- [st-dma-fence.c](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/drivers/dma-buf/st-dma-fence.c) is MIT; tests include callbacks added/removed before and after signal, timeout and callback/signal races.
- [st-dma-resv.c](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/drivers/dma-buf/st-dma-resv.c) is MIT; reservation usage, fence enumeration and iterator restart tests are reusable scenarios.
- [dma-resv.c](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/drivers/dma-buf/dma-resv.c) is itself MIT, but depends on Linux fencing, RCU and wound/wait locking; copying it whole is substantial adaptation.
- [dma-fence.c](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/drivers/dma-buf/dma-fence.c) is GPL-2.0-only. The test-file licence does not cover that implementation.

**Actionable task:** adapt the MIT test scenarios to the existing `hq_*`, VM
retain/pin and surface job APIs in one composed host harness. Include duplicate
and stale completion, wrong context/epoch, client close before completion,
failed handback and timeout followed by eventual completion. Keep real worker
source in the harness; replace only hardware/XNU boundaries with models.
This reduces manually invented concurrency cases without adding a new runtime
framework. Missing are a real interrupt/completion backend and device evidence.

## 4. ARM SMMU and cache sources: reference only, not a DXT shortcut

Linux v6.12 [arm-smmu-v3-test.c](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/drivers/iommu/arm/arm-smmu-v3/arm-smmu-v3-test.c)
(GPL-2.0) tests safe descriptor transitions and synchronization using an
instrumented writer. Its test pattern can inform an independent system-IOMMU
model later. It does not supply Tensor integration, clock/reset/stream routing
or the proprietary GPU MMU format.

[io-pgtable-arm.c](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/drivers/iommu/io-pgtable-arm.c)
is GPL-2.0-only ARM LPAE implementation. ARM system page tables cannot replace
DXT MMU4 PC/PD/PT encoders. Porting Linux IOMMU APIs first would add dependencies
without satisfying the current native driver seam.

[ARM64 cache.S](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/arch/arm64/mm/cache.S)
is GPL-2.0-only. Its invalidate routine preserves partial boundary cache lines
by cleaning them. Our page-aligned, whole-owned-buffer restriction avoids that
case; do not extend IVAC to arbitrary byte ranges without equivalent semantics.
CPU clean/invalidate still cannot establish GPU/SLC data writeback or a job's
completion. Linux's [DMA API guide](https://github.com/torvalds/linux/blob/adc218676eef25575469234709c2d87185ca223a/Documentation/core-api/dma-api-howto.rst)
also separates CPU physical, bus/DMA and virtual addresses.

## Recommended next bounded assignment

Keep the current allocator, native UPL authority and MMU4 encoder owners.
Assign one integration task to compose their actual APIs with queue lifetime
and the MIT callback/reservation test scenarios. Record every ownership
transition and inject errors after each publication/cleanup boundary. This is
the clearest labour saving in this topic. Hardware attach, GPU data visibility
and matching completion remain separate acceptance requirements.
