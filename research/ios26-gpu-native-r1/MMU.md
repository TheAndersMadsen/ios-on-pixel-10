# Tensor G5 GPU MMU and memory model

Date: 2026-11-04. Agent 3 (MMU/contexts), read-only research deliverable.
Evidence labels: **PHYSICAL** is the Pixel 10 Pro, **SOURCE** is exact source/layout
inspection, **HOST** is an existing host model/test, and **INFERENCE** is a design
conclusion that still needs physical proof. No XNU/source edit, build, Git mutation,
phone/USB action, or new execution was performed for this document.

## 0. Decisions and corrections

1. The gpu2 init fault is in the **firmware's own, TEE-premapped address space**, not
   evidence that a client page table should contain address zero. The immediate fix is
   to publish the coremem data-store **GPU device VA** `0xE1C013C000` at SYSINIT
   `+0x150` before SMC START. The firmware kernel context translates that VA through
   the TEE premap; no client mapping can repair a null coremem pointer.
2. Keep three address families distinct: CPU physical/DMA addresses, 40-bit GPU device
   VAs, and 32-bit RISC-V firmware pointers. In particular, **do not use
   `GTA_DEVVA_HEAP + pc_offset` for `RGXFWIF_FWMEMCONTEXT.sPCDevPAddr`**.
   That field is `IMG_DEV_PHYADDR`: for an M3 catalogue allocated in the carve-out it
   must be `GTA_CARVEOUT_PA + pc_offset` (while the identity-DMA route is valid),
   whereas coremem and `sCCBMetaDMAAddr` really do use `GTA_DEVVA_HEAP + offset`.
   This distinction must be fixed in the M3 implementation/fixtures before a kick.
3. The DXT client walk is three levels over 40 bits: 1024 32-bit PC entries, 512
   64-bit PD entries, and 128 64-bit PT entries for 16 KiB pages. MMU v4 selects page
   size using global range registers, **not** the old Rogue PDE page-size bits.
   Reuse the existing exact DXT codec, not the mainline Rogue encoder.
4. `RGXRegisterMemoryContext` allocates and initializes a 64-byte firmware object;
   there is **no separate memory-context registration KCCB opcode**. A common
   context points to that object and a KICK makes it visible. M3 can prove GP-DM
   fence/update parsing with an all-invalid catalogue, but that proves no engine VA.
5. Before real compute, retain the existing hard gates: authenticate the live secure
   GPU DMA route, observe effective 16 KiB ranges in every client heap, and obtain a
   legitimate readback/acknowledgement of programmed USC/PDS execution bases.
   REE SMMU global bypass and requested SYSINIT values alone are not those proofs.
6. Buffer publication is child tables/data -> parent tables -> catalogue -> completed
   firmware MMUCACHE sync -> KICK. Completion is engine event -> separate SLC/cache
   handback -> CPU alias handback -> unmap/release. A KCCB return, a clean CPU cache,
   or a timeout is never a substitute for any of those stages.

## 1. Prior art: useful structure, non-transferable constants

### Asahi AGX

- [Asahi `mmu.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/mmu.rs)
  separates a shared firmware/kernel VM from user VMs, binds user roots into a
  64-entry TTBAT, retains BO mappings, and coordinates invalidation with firmware.
- [Asahi `pgtable.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/pgtable.rs)
  uses 16 KiB pages and three ARM64-like levels with firmware/GPU permission and
  cache attributes. Its unmap path reprotects cached mappings, flushes, unmaps,
  and flushes again rather than freeing reachable pages immediately.
- [Tales of the M1 GPU](https://asahilinux.org/2022/11/tales-of-the-m1-gpu) explains
  the shared firmware/GPU page-table model and the firmware/kernel versus client
  address-space split.

**Reuse:** per-client roots, explicit cache/TLB publication, and deferred teardown.
**Do not transplant:** AGX's ARM-like PTE encoding, 39-bit input address space,
TTBAT/context slots, firmware handoff, permissions, or TLB operations. Tensor is not
AGX and has a different firmware memory-context contract.

### Mainline PowerVR/Rogue

- [Linux `pvr_mmu.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_mmu.c)
  and [`pvr_rogue_mmu_defs.h`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_rogue_mmu_defs.h)
  provide the useful PC/PD/PT shape, scatter-gather pinning, child-to-parent sync,
  and immediate invalidation after unmap.
- [Mesa PowerVR](https://docs.mesa3d.org/drivers/powervr.html) is useful userspace
  architecture background, not a source of this DXT kernel MMU ABI.

**Reuse:** table ownership, sparse allocation, mapping rollback, and flush-before-job.
**Do not transplant:** the old Rogue PDE page-size/pending fields or its leaf flag
model. Exact Volcanic MMU v4 has global ranges and AXCACHE bits instead.

### Exact Tensor/Volcanic source

The authoritative reference is GrapheneOS `kernel_pixel_6.12` commit
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`, DDK 26.1@6967606, lga production,
BVNC 71.2.2448.1212. A [GitHub Tensor/PowerVR mirror](https://github.com/0xnullsect0r/android_kernel_google_gs-6.12_google-modules/tree/lineage-24.0/powervr/pvrsrvkm)
is useful for navigation; every value below was checked against the pinned tree,
not taken from that different branch:

- [`rgxmmudefs_km.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/rgxmmudefs_km.h): walk indices, entry widths, AXCACHE, valid/read-only bits.
- [`rgxheapconfig.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgxheapconfig.h): 40-bit application heaps and firmware-heap reservation.
- [`rgxmem.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmem.c): firmware memory-context initialization; no registration opcode.
- [`rgxhal_fw_premap.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/hal/env/tee/rgxhal_fw_premap.c): TEE-built firmware mappings.
- [`rgxfwutils.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c): firmware-pointer conversion, coremem DMA address, and MMUCACHE-with-sync sequencing.

## 2. What gpu2 actually proves

**PHYSICAL:** `reader.txt:355-356` contains trace ID `0x7004b052`
(`RGXFW_SF_HWR_CORE_MMU_FAULT`) with status words
`0xa100000000000009 0x00008200`, immediately followed by `0x700110c5`
(`GPU-0 has locked up`). Decoding the first status using the exact register header:

- address bits [47:4] are zero and RNW is set: a **read from device VA 0**;
- FAULT is set and TYPE is zero: a page fault, not a read-only or PM/FW-protection fault;
- MMU level is 2: page catalogue;
- context is 0, requester ID is 33 (`META DMA` in the vendor core-requester table),
  and the second word is `0x8200`.

The current Python decoder prints the raw status but not the requester label;
applying the six-bit requester field from the exact vendor header/decode yields 33
and confirms the backlog's "META DMA" wording. The subsequent HWR reset, failed
polls, DM recovery, executed HEALTH/STATEFLAGS, and zero final MMU registers are
also facts. The final zeroes do not erase the earlier fault because the survey
happens after recovery.

**SOURCE + INFERENCE:** M2 zeroes SYSINIT and leaves
`sCorememDataStoreDeprecated` (`+0x150`) null. Stock fills it with
`RGXSetMetaDMAAddress`, i.e. the coremem memdesc's **device VA**. The M3 measured
layout fixes raw heap base `0xE1C0000000`, coremem-data offset `0x13c000`, and field
offset `0x150`; therefore the expected value is:

```text
0xE1C0000000 + 0x13c000 = 0xE1C013C000
```

This is the strongest source-backed explanation and the correct one-variable S1 test,
but it remains unproved until a boot has no pre-health MMU fault/lockup/HWR.

## 3. Address spaces and the firmware premap

### 3.1 Required address forms

| Field/use | Address form | Construction / caution |
| --- | --- | --- |
| CPU access to shared carve-out | XNU device-mapping VA | `ml_io_map(PA, ...)`; never publish this host pointer. |
| Firmware root and page-table entries | 64-bit device physical/DMA address | Actual backing DMA address. With identity bypass this may equal CPU PA; with translated SMMU it is IOVA, not CPU PA. |
| `FWMEMCONTEXT.sPCDevPAddr` | 64-bit device physical/DMA address | M3 carve-out case: `0xB9F00000 + pc_offset`, **not** `0xE1C0000000 + pc_offset`. |
| `sCorememDataStoreDeprecated` | 64-bit GPU device VA | `0xE1C0000000 + 0x13c000 = 0xE1C013C000`. |
| `FWCOMMONCONTEXT.sCCBMetaDMAAddr` | 64-bit GPU device VA | `0xE1C0000000 + ccb_offset`. |
| `psCCB`, `psCCBCtl`, `psFWMemContext`, KICK `psContext`, UFO/sync addresses | 32-bit RISC-V firmware pointer | Uncached shared object: `0x40000000 \| raw_offset`; cached shared object: `0xC0000000 \| raw_offset`. Use the measured object cache mode. |
| PDS/USC/FBCDC/texture/PDS-indirect SYSINIT bases | 40-bit GPU device VAs | Use exact heap bases; requests are not observed programmed-register readback. |
| Application BO/command/IOSurface references | 40-bit GPU device VAs | Allocate in the exact GENERAL/PDS/USC heap, map through the client root, never truncate to a firmware pointer. |

The RISC-V region bases come from 256 MiB remap regions. For example gpu2's
`kCCB@0x40202000` is uncached region 4 plus raw offset `0x202000`; it is not a CPU
physical address and not a 40-bit client VA.

### 3.2 Firmware carve-out layout

**SOURCE:** the signed image layout and generated `blazer_gpu_fwif.h` establish:

| Raw offset | Purpose |
| --- | --- |
| `0x000000` | firmware code area |
| `0x030000` | coremem code |
| `0x130000` | private data |
| `0x13c000` | coremem data (`0x4840` bytes, sent rounded to 4 KiB) |
| `0x1e0000` | private read-only data |
| `0x200000` | main shared heap: OSINIT/SYSINIT, rings, contexts, M3 objects |
| `0x1fd0000` | config heap, 64 KiB granularity: connection, OSINIT, SYSINIT |

Raw heap device VA is `0xE1C0000000`, size 32 MiB. The FDT no-map carve-out starts
at CPU PA `0xB9F00000`. The TEE creates the firmware kernel MMU context and premaps
code, private data, main heap, and config heap. Stock obtains the firmware kernel
page-catalogue base from `PVRSRV_PHYS_HEAP_FW_PREMAP_PT`; it is not the per-client
root we allocate.

**Consequence:** do not rebuild, zero, or replace the TEE firmware mappings when
fixing client VM. `RGXGetFwMapping` also has firmware-specific walk rules (non-MIPS
firmware defaults to 4 KiB, and gpu2 advertises host shift 12). Client 16 KiB range
requirements must not be used to rewrite the firmware premap.

## 4. Exact DXT client page tables

### 4.1 Walk for 16 KiB data pages

```text
39                30 29             21 20       14 13            0
+-------------------+-----------------+-----------+---------------+
| PC index (10 bits)| PD index (9 bits)| PT (7 bit)| page offset   |
+-------------------+-----------------+-----------+---------------+
```

| Level | Entries / width | Hardware bytes used | Coverage per entry | Encoded valid entry |
| --- | ---: | ---: | ---: | --- |
| PC / page catalogue, root | 1024 x 32-bit | 4096 | 1 GiB | `((PD_DMA >> 12) << 4) \| 1` |
| PD / page directory | 512 x 64-bit | 4096 | 2 MiB | `PT_DMA \| 1` |
| PT / page table | 128 x 64-bit | 1024 | 16 KiB | `PA \| AXCACHE \| valid \| optional RO` |

All VA/PA/DMA values must be below `1 << 40`. PC child tables are 4 KiB aligned;
PD child tables need only 1 KiB alignment for 16 KiB pages, and leaf backing is
16 KiB aligned. The existing implementation sensibly uses dedicated zeroed 16 KiB
backing pages for every table even though PT hardware use is only 1 KiB. Unallocated
entries are zero/invalid; guard pages stay unmapped.

`AXCACHE = 0x3c00000000000000` selects write-back read/write allocate in the exact
Volcanic header. Bit 1 is read-only; bit 0 is valid. There is no per-PTE execute bit:
USC/PDS execution placement is controlled by their heaps and global execution bases.
Use read-only mappings for immutable code where practical and RW for output/data;
do not mark an allocation coherent merely to avoid the required cache protocol.

### 4.2 MMU v4 ranges and heaps

The default is 4 KiB. Each nonzero `MMU_PAGE_SIZE_RANGE_{ONE..FOUR}` (`0xe350`,
`0xe358`, `0xe360`, `0xe368`) describes a 2 MiB-aligned inclusive range and overrides
its page size. Ordered decoding must be checked at both heap ends **and every
interior range boundary**, not only at heap starts.

Existing client profile (`vm/src/hmg_vm.c`, **HOST**, not physical):

| Heap | Base | Size | Required effective page |
| --- | --- | --- | --- |
| GENERAL_NON4K | `0xB800000000` | 32 GiB | 16 KiB |
| PDSCODEDATA | `0xDA00000000` | 4 GiB | 16 KiB |
| USCCODE | `0xE000000000` | 4 GiB - 32 MiB | 16 KiB |

Other exact heaps needed later include PDS-indirect `0xED00000000`/16 MiB,
FBCDC `0xEC00000000`/2 MiB, FBCDC-large `0xEC40000000`/2 MiB, and texture state
`0xF000000000`/4 GiB. Do not allocate ordinary BOs in the firmware reservation
`0xE1C0000000` or in the reserved USC breakpoint tail.

## 5. Firmware memory and common contexts

### 5.1 Empty GP-DM M3 context

Allocate and retain until reset: root catalogue, 64-byte `RGXFWIF_FWMEMCONTEXT`,
`0x1e0`-byte `RGXFWIF_FWCOMMONCONTEXT`, 32-byte client CCB control, 8 KiB CCB,
and UFO storage. Zero every object and all padding.

Initialize only the measured fields:

- memory context `+0x0`: root **DMA/physical address**, as corrected above;
- `+0x8`: `uiPageCatBaseRegSet = 0xffffffff` (`RGXFW_BIF_INVALID_PCSET`);
- common `+0x0/+0x4`: uncached firmware pointers to CCB control/CCB;
- `+0x8`: CCB raw firmware-heap device VA;
- `+0x24`: `HAS_DEFER_COUNT` (`0x2`);
- `+0x68`: uncached firmware pointer to the memory context;
- `+0xe0`: GP DM (0), plus bounded process name and zero/default remaining fields;
- CCB control: write/read/dependency offsets zero, wrap mask `0x1fff`.

`psContextState` and `psRFCmd` remain null for this GP sync-only context. No host VA,
no page-table GPU VA, no KCCB "register" command, and no client buffer mapping is
needed. Publish the complete FENCE + NULL + UPDATE stream before the KICK's
`ui32CWoffUpdate`; normal stock submission does not store that new host-local write
offset into shared `CCCB_CTL.ui32WriteOffset`. [CCB-KICK.md](CCB-KICK.md) owns the
exact encoding, publication, and completion rules and independently confirms the
`0xba139000` root-DMA fixture for the canonical M3 allocation order.

### 5.2 Compute and render contexts

- Compute wraps one CDM common context in `RGXFWIF_FWCOMPUTECONTEXT`; the common
  context references the client memory context, CCB/control, DM type, and any real
  compute suspend/framework state. Its CCB task body and immutable PDS/CDM/USC
  buffers contain **client GPU VAs**, so all of them require valid mappings.
- Rasterization wraps two common contexts, TA and 3D, in
  `RGXFWIF_FWRENDERCONTEXT`. They may share one client memory context but have
  separate scheduling/CCB state. Render targets, context-switch state, freelists,
  PM catalogs and framework resources are additional retained GPU-visible objects,
  not part of the empty GP sync experiment.
- A render job's buffer lifetime covers every TA/3D reference through both engine
  completion and PM/cache quiescence. A single CDM completion must not be generalized
  into proof that TA+3D+PM are quiescent.

## 6. Setup sequence and proving logs

### S0 — Freeze identity and refuse unsafe routes

Confirm BVNC `0x00470002099004bc`, ABI41/layout3, exact 26.1 donor layout, MMU4,
40-bit PA/VA, and two META DMA channels. Authenticate actual mapping PA/NS/Device
attributes and hold secure configuration exclusion. Read SMMU IDR/CR0/ACK/GBPA/
GERROR twice without changing them. If the live GPU stream's DMA route is not known
identity, stop: there is no IOVA mapper in the current native path.

Proposed line:

```text
HMGVM: identity bvnc=... mmu=4 pa_bits=40 va_bits=40 route=identity smmu_cr0=... gbpa=... epoch=...
```

### S1 — Fix coremem only, before START

Write `0xE1C013C000` at SYSINIT `+0x150`, then the final shared-memory barrier,
then power-on/SMC START. Keep M2 tracing enabled. Do not mix this boot with a client
KICK or real mappings.

```text
HK GPUTA: MMU coremem sysinit+0x150=0x000000e1c013c000 raw=0xe1c0000000 off=0x13c000
HK GPUTA: S1 clean health=1 core_mmu_fault=0 hit_lockup=0 failed_hw_poll=0 fw_faults=0 assert=empty debug_dump=0
blazer-gpu: reg MMU_FAULT_STATUS1 +0xe150 0x0000000000000000
blazer-gpu: reg MMU_FAULT_STATUS_META +0xe160 0x0000000000000000
```

PASS requires HEALTH consumption and STATEFLAGS execution **and no pre-health
CORE_MMU_FAULT/HIT_LOCKUP/FAILED_HW_POLL/DEBUG_DUMP**. A later health pass after HWR
is still S1 failure. Decode only the first complete `M2 fwlog` group: the attempt's
mirrored console repeats the same trace and must not be counted as a second fault.

### S2 — Prove the empty memory/common context

Host fixtures must byte-check the full objects, especially root DMA versus CCB/coremem
GPU VA versus 32-bit firmware pointers. On device, print the values before KICK:

```text
HK GPUTA: S2 memctx_fw=0x40...... pc_dma=0x00000000........ pcset=0xffffffff entries_valid=0
HK GPUTA: S2 common_fw=0x40...... ccb_fw=0x40...... ccb_dma=0x000000e1........ wrap=0x1fff
```

`pc_dma` must be a carve-out/backing DMA address, never `0xE1...`. GP UFO updates
prove firmware CCB execution only; all-invalid translation remains intentional.

### S3 — Validate global translation before the first engine job

Read the four range registers and require effective 16 KiB across all three current
client heaps and every interior boundary. Separately require a source-legitimate
observation/acknowledgement of programmed USC/PDS bases. VM-r4 found no such
readback in exact available sources; until agent 10 supplies one, native engine
publication remains unavailable rather than "probably ready."

```text
HMGVM: ranges 0=... 1=... 2=... 3=... general=16K pds=16K usc=16K
HMGVM: exec_bases pds=0xda00000000 usc=0xe000000000 source=<authoritative-readback>
```

The second line is a requirement template, not permission to print requested SYSINIT
values as though they were read back.

### S4 — Build and publish real mappings

1. Allocate zeroed root and BO backing; reserve 16 KiB-aligned VA in the correct heap.
2. Pin physical segments. Reject zero, unaligned, overlapping, out-of-40-bit, aliased
   table/backing pages and overflow. Fill PT leaves, then PD entries, then PC entry.
3. Clean leaf data/tables, then parent tables, then root. Existing native operations
   are `DC CVAC` for tables and `DC CIVAC` for owned BO TO_DEVICE with `DSB SY`.
4. Create the 64-byte memory context with root DMA and INVALID_PCSET, reference it
   from the CDM common context, and make producer writes visible.
5. Send MMUCACHE with `PT|PD|PC|CTX_ALL = 0x807`, a real firmware sync pointer and
   nonwrapping update value. Wait for the exact firmware-written sync before KICK.
   Pre-kick cache command and KICK must be serialized so no job overtakes invalidation.

```text
HMGVM: map ctx=... va=0x........ bytes=0x... pa_pages=... ro=... pc=... pd=... pt=...
HMGVM: publish ctx=... root_dma=0x... table_clean=1 data_clean=1 fwmem=0x40......
HMGVM: mmucache flags=0x807 sync_fw=0x40...... want=... got=... kccb_rtn=0x1
```

A missing/wrong/stale sync quarantines the VM and retains every allocation.

### S5 — Submit and hand back one owned compute job

Pin shader, PDS/CDM control, input, output, sentinel and guards in the same VM until
authentic completion. Require matching engine update, then separate context-fenced
SLC flush/invalidate and its fresh receipt, then CPU `DC IVAC` through the verified
safe alias, then UPL unblock and result comparison.

```text
HMGQ: engine ctx=... seq=... ufo=... token=... complete=1
HMGQ: slc ctx=... seq=... receipt=0x1 inval=0 dm_context=1
HMGVM: handback ctx=... seq=... cpu_ivac=1 alias_removed=1 pins=0
HMGT: output expected=... actual=... guards=PASS faults=0
```

No engine fault, stale token, KCCB-only completion, host-written output, or DPU frame
may promote this to compute/render success.

### S6 — Unmap/destroy only after quiescence

Close admission; drain all common contexts and queue leases; prove same-epoch DMA
quiescence. Clear PTEs, wait for another real MMUCACHE sync, then release VA/backing.
Empty table pages stay linked until no stale translation can reach them. Failure
restores exposed entries where possible and otherwise quarantines everything.

```text
HMGVM: detach ctx=... queue_leases=0 dma_quiescent=1 mmucache_seq=... tables_released=1
```

Timeout is not quiescence and must leave root, tables, BO pages, UPL and aliases owned.

## 7. Host buffers and IOSurfaces

### Owned buffers

Use the existing `IOBufferMemoryDescriptor` wired/prepared physical-segment path and
actual PA walker, not `malloc` pointers. One VM may give two clients the same numeric
VA only when they have different roots; aliases in one root are rejected. Keep CPU
canonical mappings blocked while GPU access is active and use a verified kernel safe
alias for cache operations. A successful pin alone does not prove all existing or
future user aliases fault.

### IOSurface import and presentation

1. Authorize the numeric surface ID against the calling task's **actual registered
   IOSurface reference**; the ID alone is not authority. Retain the IOSurface
   root/table use and live prepare pin, then walk every physical segment. Surfaces
   are not assumed physically contiguous.
2. Create a VM BO referencing those pages with surface-owned lifetime; reserve a
   16 KiB-aligned GENERAL VA and map each page with the required read/write policy.
   Keep the surface reference, BO reference, prepare pin, and GPU pin through job
   completion and handback.
3. Before GPU writes, perform surface/CPU exclusion and TO_DEVICE cache synchronization
   through the surface's own identity/safe-alias path. Do not export a raw CPU pointer.
4. On render/blit completion, require the separate SLC/data writeback receipt before
   TO_CPU invalidation and surface unblocking. Only then may DPU read the surface.
5. Join the same surface/job ID through `GPU submit -> engine done -> SLC done ->
   CPU/surface handback -> DPU present`. If DPU uses physical pages rather than the
   GPU VA, retain an explicit GPU-to-DPU fence; ordinary DPU completion alone proves
   no GPU work. A copy/blit to a separate scanout buffer needs the equivalent ordering.

Surfaces-r4 also requires the sticky-UNKNOWN checks on the legacy 1202 importer and
retryable partial CPU handback. Those review fixes belong in integration before real
surface acceptance; they are not GPU proof themselves.

Proposed joined lines:

```text
HMGS: import surface=... bo=... va=0x... pages=... prepare_pin=1 cpu_blocked=1
HMGS: present surface=... submit=... engine=... slc=... handback=... dpu=... order=PASS
```

## 8. Risks and stop rules

| Risk | Why it matters | Stop/mitigation |
| --- | --- | --- |
| Confusing root DMA with firmware-heap GPU VA | Firmware walks a bogus catalogue and may lock up before any job. | Byte fixture every address form; `sPCDevPAddr` is physical/DMA, coremem/CCB DMA are device VAs. |
| Treating init fault as a client mapping problem | Adds irrelevant mappings while the null firmware pointer remains. | Coremem-only S1; TEE premap stays untouched. |
| Rogue encoder transplanted to MMU v4 | Wrong PDE/PTE bits cause translation/protection faults. | Use exact `hmg_dxt_mmu.c`; no PDE page-size bits; check global ranges. |
| Requested bases mistaken for actual configuration | Shader fetches from an unprogrammed/incorrect heap base. | Keep VM-r3/r4 execution-base gate closed until authoritative observation exists. |
| SMMU bypass mistaken for secure route ownership | CPU PA may not be valid for the actual GPU stream or may change with secure config. | Live NS/SID/GBPA/exclusion proof; otherwise UNAVAILABLE, never cast PA to IOVA. |
| CPU clean without firmware invalidation | Stale PC/PD/PT/TLB entries access old pages. | Child-to-parent cleans + completed MMUCACHE sync before KICK/unmap release. |
| MMUCACHE mistaken for data flush | CPU sees stale output even with valid translations. | Separate engine and SLC receipts, then CPU invalidation/safe alias handback. |
| Premature free on timeout | Firmware/PM can DMA into reused contexts, tables, BOs, or surfaces. | Retain until authentic completion or proven same-epoch DMA quiescence. |
| GP KickSync advertised as VM/compute | Empty catalogue executes no shader and maps no host buffer. | Separate S2, S4, S5 acceptance; require output and guards. |
| IOSurface/DPU race | Scanout reads unfinished or stale pixels. | Join engine + SLC + surface handback before DPU present; verify known pixels. |

## 9. Coordination and requested live probe

- **Agent 1 / [coremem](COREMEM-INIT.md):** use the exact S1 value and clean-trace
  criteria above. Do not generalize `GTA_DEVVA_HEAP` to the future page-catalogue
  field. Capture the raw pre-health trace even when final health passes.
- **Agent 4 / [CCB](CCB-KICK.md):** memory-context registration is object
  initialization + common context reference, not a new KCCB opcode. Include byte
  fixtures distinguishing `pc_dma` from `ccb_dma` and all `0x40......` firmware
  pointers, and preserve its host-local-write/KICK publication rule.
- **Agent 7 / [Metal/IOSurface](METAL.md):** consume the per-page import/pin/cache/
  fence sequence, including the 707-page plain-BGRA live shape; a surface ID or DPU
  completion is not mapping or completion authority.
- **Agent 10 / [integration](PLAN.md):** VM-r3's live secure-route gate and VM-r4's
  execution-base observability gate remain explicit dependencies. Integrate one
  VM/root and one firmware broker; do not mix the M3 empty-context shortcut with
  real client VA work. [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md) owns the boot correlation.

**One requested live probe (after agent 1's coremem-only image is ready):** run the
short coremem-only rung with the two S1 lines, complete current-boot decoded trace,
and existing MMU survey. If clean, a second read-only diagnostic may sample
`0xe350/0xe358/0xe360/0xe368` plus SMMU CR0/GBPA/GERROR twice. Do not combine the
first proof with client mappings or a KICK. The desired result is no init fault/HWR,
executed STATEFLAGS, and a stable range/SMMU baseline for the later S3 review.

## 10. Local evidence index

- [GPU investigation](../ios26-hw-investigation-r1/GPU.md), [M2](../ios26-gpu-r1/M2.md),
  [M3 measured layout](../ios26-gpu-r1/m3/receipts/fw-layout-r3.h), and
  [M3 layout probe](../ios26-gpu-r1/m3/tools/fw_layout_r3.c).
- [gpu2 raw physical capture](../laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/reader.txt), especially lines 284-319, 345-419, and 429-442.
- [Existing DXT codec](../ios26-metal-native-20261102/vm/src/hmg_dxt_mmu.c),
  [VM heaps/profile](../ios26-metal-native-20261102/vm/src/hmg_vm.c), and
  [VM handoff](../ios26-metal-native-20261102/vm/HANDOFF.md).
- [Firmware memory-context adapter](../ios26-metal-native-20261102/vm-r2/HANDOFF.md),
  [platform route gates](../ios26-metal-native-20261102/vm-r3/HANDOFF.md), and
  [execution-base evidence gap](../ios26-metal-native-20261102/vm-r4/HANDOFF.md).
- [Surface handback/import review](../ios26-metal-native-20261102/surfaces-r4/HANDOFF.md)
  and [native acceptance](../../docs/NATIVE-METAL.md).
