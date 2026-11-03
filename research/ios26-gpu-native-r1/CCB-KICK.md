# Client CCB and KICK: exact submission design for Tensor G5 / PowerVR DXT

Date: 2026-11-04. Facet: agent 4, client circular command buffer (CCCB/CCB), KCCB KICK, publication, and first-command evidence. Scope: Pixel 10 Pro, BVNC `71.2.2448.1212`, signed firmware ABI 41, matching downstream DDK `26.1@6967606`, RISC-V firmware.

This is a read-only source/evidence review. No XNU source, build, Git index, phone, or device state was changed. **SOURCE** means measured declarations or matched driver source; **PHYSICAL** means the existing gpu2 phone capture; **DESIGN** means the proposed next experiment, not something already executed. No new GPU execution is claimed.

Companion contracts cross-checked for this revision: [COREMEM-INIT.md](COREMEM-INIT.md), [FIRMWARE.md](FIRMWARE.md), [MMU.md](MMU.md), [FENCE-UFO.md](FENCE-UFO.md), [IOACCEL.md](IOACCEL.md), [METAL.md](METAL.md), [COMPOSITOR.md](COMPOSITOR.md), [PRIORART.md](PRIORART.md), [PLAN.md](PLAN.md), and [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md). **The next physical boot is coremem-only S1 with no client KICK.** This document governs the separate, later S2-S4 client-stream boot after S1 passes and a real FWCCB dispatcher is present.

## 0. Submission contract in one page

A submission has two rings and one context:

1. The host writes complete, inline client-CCB commands into an 8 KiB byte ring belonging to an `RGXFWIF_FWCOMMONCONTEXT`.
2. The host retains a host-local client write offset. It does **not** publish that offset by storing `CCCB_CTL.ui32WriteOffset` in the normal stock submission path.
3. The host writes a 0x70-byte KCCB slot whose meaningful KICK payload is 0x24 bytes. The KICK names the 32-bit firmware pointer to the common context, the new client write offset, the wrap mask, and zero cleanup pointers.
4. The host publishes the KCCB write index after a release barrier, then writes `0` (`RGXFWIF_DM_GP`) to RGX `+0xb00` (`RGX_CR_MTS_SCHEDULE`). The doorbell is GP even when the client command targets CDM.
5. KCCB read-index movement is consumption only. Trace ID `0x70037013` is emitted before the firmware switches on the KCCB command type, so it is decode evidence, not client-work completion.
6. For a sync-only parser proof, firmware must change a host-seeded UFO from `0xdead0000` to `0xc0de0001`, then execute a second stream fenced on value 1 and change it to `0xc0de0002`. CCB read/dependency offsets must drain to each submitted write offset.
7. For a real CDM clear/fill, the envelope changes from `FENCE + NULL + UPDATE` to `FENCE + CDM + UPDATE`. Success additionally requires cache-synchronized output and guard-word readback. A KCCB return bit, CCB movement, or completion UFO alone is not a correct-pixels result.

Two corrections to ambiguous earlier notes are important:

- `RGXReleaseCCB` advances `RGX_CLIENT_CCB.ui32HostWriteOffset`; the new value travels in `KICK.ui32CWoffUpdate`. Do not add a host store to shared `CCCB_CTL.ui32WriteOffset` and call it the stock path.
- `RGXFWIF_FWMEMCONTEXT.sPCDevPAddr` is the page catalogue's device-physical address from `MMU_AcquireBaseAddr`, not the firmware heap's 40-bit device VA. The CCB META DMA address, in contrast, **is** the firmware-heap device VA.

## 1. Evidence and prior art

### 1.1 What the phone actually established

Existing PHYSICAL attempt `20261103-205316-a7-ios-system-gpu2` established all of the following, after an earlier init fault and recovery:

- KCCB slot 0 (`HEALTH_CHECK`, type `0x2abc006f`) was consumed after 378 ms; stock does not wait for its return slot.
- KCCB slot 1 (`STATEFLAGS_CTRL`, type `0x2abc00ce`) was consumed and its return slot became `0x1` (`CMD_EXECUTED`). This is the valid health-execution gate.
- Firmware trace contains `0x70037013` for slot 0/type `0x2abc006f` and slot 1/type `0x2abc00ce`.
- No client CCB, KICK, CDM/3D engine command, shader, fill, or render was submitted. gpu2 is not evidence that this design has run.

The boot trace starts with `0x7004b052` (`CORE_MMU_FAULT`), `0x700110c5` (`HIT_LOCKUP`), and failed hardware polls before recovery. The coremem correction is therefore a prerequisite, not an optional cleanup.

### 1.2 What the pending FWCCB does and does not say

The captured FWCCB entry is exactly 112 bytes / 28 little-endian dwords:

- word 0: type `0x2abc006a` (`DEBUG_DUMP`);
- word 1: flags `0`;
- words 2..27: all zero, i.e. 26 zero dwords / 104 zero bytes after the 8-byte type+flags prefix.

It was already pending at boot (`w=1,r=0`) before HEALTH, and remained pending after STATEFLAGS. It contains no context pointer, PC, MMU address, job reference, or hidden completion token. It is a diagnostic notification associated with the init failure, not a reply to HEALTH and not a command-completion mechanism. The read-only M2 diagnostic correctly did not acknowledge it. The coremem-fixed S1 rung must have no init DEBUG_DUMP. The later client-stream rung needs a real dispatcher: copy each complete entry, advance the read index with release ordering, then handle the copy outside the ring lock. Any new DEBUG_DUMP, context reset, firmware page fault, or GPU restart is a stop after that copy/ack, not success and not something to leave pending indefinitely.

Offline firmware evidence in `integration/physical-a725-analysis-r1/firmware-init-facts.json` shows the KCCB dispatcher issuing `0x70037013` before its command-type switch. This matches the raw gpu2 trace and explains why that ID cannot be promoted to execution completion.

### 1.3 Prior art: useful architecture, exact constants only from the matched Tensor DDK

| Reference | Useful finding | What not to import |
| --- | --- | --- |
| [Asahi AGX `workqueue.rs` at `c8ec9be8`](https://github.com/AsahiLinux/linux/blob/c8ec9be8ec2cae78b0e7affe7044607c2531b005/drivers/gpu/drm/asahi/workqueue.rs), plus [AGX driver notes](https://asahilinux.org/docs/hw/soc/agx/) | AGX publishes ring entries with release ordering, submits a work-queue message containing queue pointer + latest write pointer + event information, and retires resources from firmware-originated progress/events. This is the same high-level discipline needed here. | AGX work queues are rings of pointers to work items, not Rogue's inline byte-command CCB. AGX channel messages, stamps, UAT layouts, doorbells, and constants do not apply to DXT. |
| [Mainline Imagination `pvr_ccb.c` at `6628e7d4`](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination/pvr_ccb.c) and [`pvr_rogue_fwif.h`](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/gpu/drm/imagination/pvr_rogue_fwif.h) | Independently corroborates fixed-size KCCB slots, slot-index wrap with one unusable slot, optional per-slot return status, barrier before KCCB write index, and GP MTS schedule. | Mainline is not the Pixel 26.1 ABI/profile and does not supply this facet's exact client stream or context layout. Do not copy its structure sizes or feature-dependent KICK tail. |
| [Tensor GrapheneOS mirror `kernel_pixel_6.12@5940a317`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/commit/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c): [`rgxkicksync.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxkicksync.c), [`rgxccb.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxccb.c), [`rgxfwcmnctx.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwcmnctx.c), [`rgxfwutils.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c) | Exact KickSync construction, CCB acquire/release/padding, common-context defaults, KCCB publication, and GP doorbell for the target source family. | Linux allocation, locking, deferred-work, PDump, and platform code are not drop-in XNU code. Numbers were measured under the pinned lga production configuration rather than copied from another config. |
| Same pin: [`rgxmem.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmem.c), [`mmu_common.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/common/mmu_common.c) | Memory-context registration and the crucial `sPCDevPAddr = sBaseLevelInfo.sMemDesc.sDevPAddr` address form. | A firmware-heap device VA is not a substitute for a page-table device-physical address. Real mappings still need agent 3's secure routing and MMU-cache proof. |

The numeric source of truth for this document is `research/ios26-gpu-r1/m3/receipts/fw-layout-r3.h`, measured by `m3/tools/fw_layout_r3.c` against that same pin. All multi-byte values below are little-endian.

## 2. Ring types and address forms

### 2.1 Do not confuse the three rings

| Ring | Element / indexing | Producer → consumer | Purpose |
| --- | --- | --- | --- |
| KCCB | 1024 slots, 0x70 bytes each; control wrap mask `0x3ff` | host → firmware | HEALTH, STATEFLAGS, KICK, cache/cleanup and other control commands. Return slots are separate dwords. |
| Client CCB / CCCB | 8192 bytes, byte offsets; wrap mask `0x1fff` | host → firmware, for one common context | Inline FENCE/CDM/NULL/UPDATE/PADDING commands. |
| FWCCB | 32 slots, 0x70 bytes each; wrap mask `0x1f` | firmware → host | Reset, fault, restart, debug/stat notifications. It is not the client completion ring. |

### 2.2 The three address representations

Let `off` be a byte offset within the 33 MiB carve-out whose CPU physical base is `0xb9f00000`.

| Representation | Formula | Used for |
| --- | --- | --- |
| 32-bit RISC-V uncached firmware pointer | `0x40000000 \| off` | `psCCB`, `psCCBCtl`, `psFWMemContext`, KICK `psContext`, and UFO addresses. Never a host VA. |
| 40-bit firmware raw-heap device VA | `0xe1c0000000 + off` | `sCCBMetaDMAAddr` and SYSINIT coremem DMA address. Stored as 64-bit little-endian. |
| Device-physical address | `0xb9f00000 + off` for objects in this carve-out | `FWMEMCONTEXT.sPCDevPAddr`. Stored as 64-bit little-endian. This is what `MMU_AcquireBaseAddr` supplies; do not substitute the raw-heap device VA. |

The coremem field is independently fixed at SYSINIT `+0x150` to `0xe1c013c000` (`off=0x13c000`) before the final pre-START barrier. A different firmware/layout identity requires a new measurement and fixture, not silent reuse.

### 2.3 Canonical rung-7 allocation fixture

This exact fixture is valid when the existing M2 allocator ends at `0x239000`, as in gpu2. Assert that starting value and the allocation order. If the allocator changes, regenerate every derived value using §2.2; never mix this fixture with new offsets.

| Object | Carve-out offset | Actual size | Firmware pointer | Device PA (when relevant) | Raw-heap device VA (when relevant) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Zeroed page catalogue | `0x239000` | `0x4000` | `0x40239000` | `0xba139000` | — (not `sPCDevPAddr`) |
| `RGXFWIF_FWMEMCONTEXT` | `0x23d000` | `0x40` | `0x4023d000` | `0xba13d000` | — |
| `RGXFWIF_FWCOMMONCONTEXT` | `0x23e000` | `0x1e0` | `0x4023e000` | `0xba13e000` | — |
| `RGXFWIF_CCCB_CTL` | `0x23f000` | `0x20` | `0x4023f000` | `0xba13f000` | — |
| Client CCB | `0x240000` | `0x2000` | `0x40240000` | `0xba140000` | `0xe1c0240000` |
| UFO page / first dword | `0x242000` | page / 4 bytes | `0x40242000` | `0xba142000` | — |

The Device PA column identifies each backing object; only the page catalogue PA is written into a structure field in this fixture. All allocations are zeroed and retained through the deliberate reset. The page catalogue remains entirely zero/invalid for KickSync; any real engine work requires a different, agent-3-approved memory context.

## 3. Exact structures

### 3.1 Firmware memory context (`0x40` bytes)

For the sync-only fixture, every byte is zero except:

| Offset | Width | Value |
| ---: | ---: | --- |
| `+0x00` `sPCDevPAddr` | 8 | `0x00000000ba139000` |
| `+0x08` `uiPageCatBaseRegSet` | 4 | `0xffffffff` (`RGXFW_BIF_INVALID_PCSET`) |

`uiBreakpointAddr`, `uiBPHandlerAddr`, `uiBreakpointCtl`, FBC mask, spill address, flags, and cross-DM flags remain zero. Zero page-table entries are intentional invalid translations, not a real mapping.

### 3.2 GP firmware common context (`0x1e0` bytes)

Every byte is zero except the following. This is the stock shape: priority 0, priority sequence 0, maximum deadline 0 for KickSync, no context-state or framework buffer, and compat `HAS_DEFER_COUNT`.

| Offset | Width | Field | Value |
| ---: | ---: | --- | --- |
| `+0x00` | 4 | `psCCBCtl` | `0x4023f000` |
| `+0x04` | 4 | `psCCB` | `0x40240000` |
| `+0x08` | 8 | `sCCBMetaDMAAddr` | `0x000000e1c0240000` |
| `+0x24` | 4 | `ui32CompatFlags` | `0x2` |
| `+0x68` | 4 | `psFWMemContext` | `0x4023d000` |
| `+0x6c` | 4 | `ui32ServerCommonContextID` | `1` (fixture correlation ID) |
| `+0x78` | 16 | `szProcName` | ASCII `hk-kicksync\0`, remaining bytes zero |
| `+0xe0` | 4 | `sRangeCheckBeforeUse.eDM` | `0` (`RGXFWIF_DM_GP`) |

`ui32PID` is zero in this kernel fixture. `ui32PipelinedKicks` starts at zero and is firmware-owned afterward. List nodes, failed-UFO state, statistics, cancel ranges, and DM-specific storage stay zero initially.

For a CDM context, `eDM` becomes `4`; its context-state/framework/DM-specific initialization and deadline are integration-owned and must not be copied from this GP-zero fixture.

### 3.3 Client CCB control (`0x20` bytes)

| Offset | Field | Initial value | Owner / meaning |
| ---: | --- | ---: | --- |
| `+0x00` | `ui32WriteOffset` | `0` | Firmware-visible submitted byte offset. The KICK carries its update; normal host submission does not store it here. |
| `+0x04` | `ui32ReadOffset` | `0` | Firmware progress: next runnable command. |
| `+0x08` | `ui32DepOffset` | `0` | Firmware fence-dependency progress. |
| `+0x0c` | `ui32WrapMask` | `0x1fff` | Capacity minus one. |
| `+0x10..0x1c` | AGP read offsets / reserved | all `0` | Not used by this fixture. |

The host separately keeps `host_write`, initially zero. A submission's final `host_write` must be 16-byte aligned; individual packets are 8-byte aligned.

### 3.4 Client command header and UFO

Each command begins with a 0x10-byte header:

| Offset | Field | Rule |
| ---: | --- | --- |
| `+0x00` | `eCmdType` | Exact 32-bit command value below. |
| `+0x04` | `ui32CmdSize` | Payload bytes after this 16-byte header, including any payload alignment bytes; not total packet size. |
| `+0x08` | `ui32ExtJobRef` | External correlation ID, repeated across FENCE + task + UPDATE of one submission. |
| `+0x0c` | `ui32IntJobRef` | Monotonic internal correlation ID, also repeated across that submission. |

One UFO is 8 bytes: 32-bit firmware address at `+0`, expected/update value at `+4`. The address mask is `0xfffffffc`; this fixture uses an ordinary, 4-byte-aligned sync word with low type bits zero. FENCE checks equality; UPDATE writes the value.

| Type | Value | Payload here |
| --- | ---: | --- |
| NULL | `0x2abc80d2` | Empty for KickSync; no GPU engine job. |
| FENCE | `0x2abc00d4` | One or more UFOs. |
| UPDATE | `0x2abc00d5` | One or more UFOs. |
| PADDING | `0x2abc00dd` | Skip to ring start at wrap. |
| CDM | `0x2abc80cd` | Integration-owned compute command body for real fill. |

Packet sizes use 8-byte `RGXFWIF_FWALLOC_ALIGN`. One-UFO FENCE and UPDATE packets are each `16+8=24` bytes. Empty NULL is 16 bytes.

### 3.5 KCCB KICK slot

A KCCB slot is 0x70 bytes and should be zero-filled before these fields are written. The meaningful KICK encoding ends at `0x24`; the rest remains zero.

| Slot offset | Width | Field | Value |
| ---: | ---: | --- | --- |
| `+0x00` | 4 | `eCmdType` | `0x2abc0065` (`KCCB_CMD_KICK`) |
| `+0x04` | 4 | `ui32KCCBFlags` | `0` |
| `+0x08` | 4 | `sCmdKickData.psContext` | 32-bit common-context firmware pointer |
| `+0x0c` | 4 | `ui32CWoffUpdate` | New host-local client write offset |
| `+0x10` | 4 | `ui32CWrapMaskUpdate` | `0x1fff` |
| `+0x14` | 4 | `ui32NumCleanupCtl` | `0` |
| `+0x18` | 4 | `apsCleanupCtl[0]` | `0` |
| `+0x1c` | 4 | `apsCleanupCtl[1]` | `0` |
| `+0x20` | 4 | `apsCleanupCtl[2]` | `0` |

KCCB control uses write/read slot indices, not byte offsets. Reserve old slot `s=KCCB.write`, compute `next=(s+1)&0x3ff`, and keep `next != KCCB.read`. Clear return slot `s` only if it will be used diagnostically. Write the command, barrier, publish `KCCB.write=next`, then GP MTS doorbell `0`.

Stock KickSync passes no return-slot pointer and does not wait for KICK completion. If a KICK return slot happens to acquire `CMD_EXECUTED`, treat it only as KCCB handling evidence. It cannot prove that a fenced client stream drained or an engine produced correct output.

## 4. Canonical sync-only byte fixture

Use one UFO at `0x40242000`, initially host-written once to `0xdead0000`. The host must never write either completion value. Submission 1 uses external job `0x1001`, internal job `1`; submission 2 uses `0x1002`, `2`.

Each stream is exactly 64 bytes. Values below are 32-bit words in memory order; their byte representation is little-endian.

### 4.1 Stream 1 at CCB `0x00..0x3f`

| CCB offset | Header words | Payload words |
| ---: | --- | --- |
| `0x00` FENCE | `2abc00d4 00000008 00001001 00000001` | `40242000 dead0000` |
| `0x18` NULL | `2abc80d2 00000000 00001001 00000001` | none |
| `0x30` UPDATE | `2abc00d5 00000008 00001001 00000001` | `40242000 c0de0001` |

KCCB slot 2's first nine dwords are:

```text
2abc0065 00000000 4023e000 00000040 00001fff 00000000 00000000 00000000 00000000
```

Publish KCCB `write=3`; wait for `read=3`, not for a claimed render result.

### 4.2 Stream 2 at CCB `0x40..0x7f`

| CCB offset | Header words | Payload words |
| ---: | --- | --- |
| `0x40` FENCE | `2abc00d4 00000008 00001002 00000002` | `40242000 c0de0001` |
| `0x58` NULL | `2abc80d2 00000000 00001002 00000002` | none |
| `0x70` UPDATE | `2abc00d5 00000008 00001002 00000002` | `40242000 c0de0002` |

KCCB slot 3's first nine dwords are:

```text
2abc0065 00000000 4023e000 00000080 00001fff 00000000 00000000 00000000 00000000
```

Publish KCCB `write=4`; wait for `read=4`. Do not send stream 2 behind an unread first KICK, and do not prewrite value 1 to make the second FENCE pass.

This is the first **firmware client-parser** milestone. It is deliberately not a clear, shader, MMU-mapping, or Metal result. Because stream 2 is submitted only after value 1 is visible, its FENCE is already satisfied: this proves equality evaluation and ordering, not a temporal stall. A later optional two-GP-context control must hold A at a mismatched FENCE (`D` stops there, no A UPDATE), let B's firmware UPDATE satisfy it, and only then require A to resume. Do not add that control to the minimal first S4 boot.

## 5. Exact submission procedure

### 5.1 Gate and construct once

1. In the first boot, apply only the coremem value before START. Require HEALTH consumption, STATEFLAGS return `0x1`, no pre-health `CORE_MMU_FAULT`, `HIT_LOCKUP`, or `FAILED_HW_POLL`, no init DEBUG_DUMP, zero new firmware faults, and empty assert. Stop there with the distinct `M3 S1 PASS`; issue no client KICK.
2. In the later S2-S4 image, before the first KICK, install the FWCCB dispatcher and a `fw_epoch`/`recovery_seq` gate. Invoke the dispatcher before submission and inside every bounded wait. It must validate indices, copy each 0x70-byte entry, publish `read=(read+1)&0x1f` with release ordering, and only then handle the copied entry outside the FWCCB lock. Unknown/malformed input invalidates the epoch; reset/fault/restart entries freeze submissions and enter recovery. A full FWCCB left in M2's read-only mode is not a persistent-runtime design.
3. Allocate and initialize §2.3. Verify all pointer forms and byte fixtures before any KICK. Initialize CCB control and the UFO sentinel, then issue the final construction barrier.
4. Keep one lock covering client-CCB planning/publication and KCCB ordering. For the bounded rung, permit only one outstanding step and no retry. Every submission and completion record carries the current `fw_epoch` and `recovery_seq`; stale records fail rather than completing new work.

### 5.2 Plan client space, including wrap

For a submission of `bytes` at host offset `w`, with capacity `N=8192` and firmware read offset `r`:

```text
free = (r - w + N - 1) & (N - 1)
wrap_needed = (w + bytes + 16 > N)
```

Reject `bytes + 16 + 1 > N`. Without wrap require `free > bytes`. With wrap, let `remain=N-w` and require `free > remain + bytes`; write a PADDING header at `w` with `ui32CmdSize=remain-16`, then place the submission at offset 0. The final KICK offset is `(start + bytes) & 0x1fff`, where `start=0` after padding and `start=w` otherwise.

PADDING is a real 16-byte-minimum header, not zero filler. Zero its job references and payload for deterministic fixtures. The two canonical streams need no wrap.

### 5.3 Write and publish

1. Write all CCB headers and payloads completely. Initialize any completion UFO before the commands can become visible.
2. Flush the CCB byte range as required by its memory type; on the current uncached device mapping, use the existing `aoc_barrier()` publication ordering. Do not substitute a compiler-only barrier.
3. Advance the host-local `host_write` to the computed final offset. Do not store it to `CCCB_CTL.ui32WriteOffset`.
4. Reserve/fill the next KCCB slot with the common-context pointer, that same final offset, wrap mask, and zero cleanup fields. Reset its return slot only for optional diagnostics.
5. Barrier after the complete KCCB command, publish KCCB write index, perform the stock write/readback ordering appropriate to the mapping, then write `0` to RGX `+0xb00`. The existing `gta_mts_kick()` also has a system `dsb` after the device store.
6. Only now may work become visible. Keep the context, CCB, control, memory context, page catalogue, UFOs, and all engine resources pinned.

### 5.4 Wait in evidence order

1. Bound KCCB read-index arrival at the new index. Timeout is failure.
2. Record `0x70037013` with the expected slot and `0x2abc0065`, but label it `KCCB decoded`, never `command complete`.
3. Bound client `CCCB_CTL.write/read/dep` progress and the expected firmware UFO value. Require `R=D=W` at the stream end and the exact value to remain unchanged across a second read after the visibility barrier. Dispatch FWCCB and check firmware fault/HWR state throughout. Any copied reset/page-fault/restart notification, new MMU fault/lockup/assert, stale `fw_epoch`/`recovery_seq`, or unplanned panic is failure; acknowledgement of the copied notification is not permission to continue.
4. Only after value 1 and CCB drain to `0x40`, construct and submit stream 2. PASS only after value 2 and drain to `0x80`, with value 1 observed first and no failure evidence.
5. Timeout never means DMA quiescence. Dump the actual UFO, `W/R/D`, KCCB `W/R`, advisory return slot, and common-context `sLastFailedUFO` (`+0x60`). Do not free, reuse, rewrite completion values, or blindly resubmit after timeout. M3 reuses one UFO only for its two ordered values; a persistent driver needs per-job address+token identity and oldest-sequence-first reaping.

For a production deferred-KCCB path, preserve the same order under the KCCB lock: client bytes may be released before a deferred KICK is sent, but no later KICK may overtake it. The minimal rung avoids that complexity by reserving one slot and having one outstanding submission.

## 6. First real clear/fill: same transport, different task and proof

The simplest first hardware job is a CDM constant-fill into an owned, GPU-mapped output page. It should follow, not replace, the sync-only parser proof.

Let `B` be the integration-owned CDM payload size. For the fenced first job choose `B` as a positive multiple of 16. The stream is:

```text
FENCE (24 bytes)
CDM   (16 + B bytes; type 0x2abc80cd, ui32CmdSize=B)
UPDATE(24 bytes)
Total = 64 + B bytes, hence 16-byte aligned
```

All three headers carry the same external/internal job IDs. The KICK is unchanged except for its new final offset. The common context uses `eDM=4`, a real agent-3 memory context, valid mappings and required MMU-cache publication, plus integration-owned CDM state/framework/body. The GP MTS doorbell value remains `0`.

The host seeds a separate submission UFO with its initial value; the engine-ordered UPDATE writes the done token. Completion acceptance requires all of:

1. KCCB consumption and matching KICK decode;
2. CCB drain to the submitted offset;
3. firmware UPDATE to the expected done token;
4. no fault/reset/restart/HWR evidence;
5. required cache handback, then output dwords equal the fill value, both guard dwords retain their sentinels, and no output/guard location was written by the host after submission.

A render clear is a later engine-specific milestone (3D/VDM/PDS/PPP resources and render-target/cache rules), not something the NULL sync test proves. Metal publication remains gated behind real compute/render readback.

## 7. Proving log lines

### 7.1 Firmware trace IDs and expected correlation

`M2 TB` decoding uses `id, timestamp_hi, timestamp_lo, parameters`; the parameter count is bits 16..22 of the ID. Decode only the first complete current-boot `M2 fwlog` group (the mirrored console repeats it), reject malformed/truncated records, and never turn an invalid trace into a zero-fault PASS. Useful exact IDs are:

| ID | Meaning / required use |
| ---: | --- |
| `0x70037013` | MTS `KCCB Slot %u: Cmd=0x%08x, Driver ID=%u`; decode/admission evidence only. |
| `0x7003100e` | MAIN `cCCB Woff update = %u, DM = %u, FWCtx = 0x%08x`; expect 64 then 128, DM 0, context `0x4023e000`. |
| `0x70021010` | UFO check start for context and command offset. |
| `0x70031011` | `UFO Check: [address] is current requires expected`; correlate address and sentinel/value 1. |
| `0x70001012` | UFO checks succeeded. |
| `0x7000103f` | UFO checks failed; failure. |
| `0x70021053` | NULL task decoded for this context. It is still not a GPU engine job. |
| `0x70021016` | UPDATE start for context and offset. |
| `0x70021017` | `UFO Update: [address] = value`; require `0x40242000 = 0xc0de0001`, then value 2. |
| `0x7004b052` | Core MMU fault; failure if new. |
| `0x700110c5` | Lockup; failure if new. |
| `0x7003b00d` | Failed HW poll; failure if new. |

For a CDM fill, additionally require the matching engine kick trace from `RGXFW_SF_MAIN_KICK_COMPUTE*`, correlated to the same context/job references. Its presence is submission evidence; output readback is still mandatory.

### 7.2 Proposed kernel receipts for sync-only S1–S4

These are proposed new log lines, not lines gpu2 already emitted:

```text
HK GPUTA: M3 S1 clean health: init_faults=0 debug_dump=0 assert=empty; HEALTH consumed; STATEFLAGS_CTRL return 0x1; no KICK
HK GPUTA: M3 S2 kick1: epoch=1 recovery=0 slot 2 read; ctx 0x4023e000; ccb w 64 r 64 d 64 wrap 8191; rtn 0x0 (advisory)
HK GPUTA: M3 S3 ufo1: epoch=1 recovery=0 0x40242000 0xdead0000 -> 0xc0de0001 after <ms> ms; no faults
HK GPUTA: M3 S4 ufo2: epoch=1 recovery=0 0x40242000 0xc0de0001 -> 0xc0de0002 after <ms> ms; ccb w 128 r 128 d 128; ordered; no faults
HK GPUTA: rung 7 S4 PASS, firmware client streams complete (smcs <n>)
```

Only S4 authorizes rung-7 S4 PASS. [FENCE-UFO.md](FENCE-UFO.md) §4.1 gives the more detailed `S2 submit/admitted`, `S3 FW command complete`, and `S4 submit/admitted/FW command complete` host-receipt format; the abbreviated lines above do not replace that joinable record. The decoded trace must independently contain the slot-2/3 KICKs, write-offset updates, checks, NULL tasks, and firmware UPDATEs described above. Missing optional trace output must be reported as missing corroboration, not fabricated from host state.

### 7.3 Proposed first-fill receipts

```text
HK GPUTA: FILL submit epoch=<E> recovery=<R> seq=<seq> ctx=<fwctx> ccb <start>..<end> kccb_slot <slot> ext <ext> int <int>
HK GPUTA: FILL engine epoch=<E> recovery=<R> seq=<seq> ufo <addr>=<token> ccb r=<end> d=<end> faults=0
HK GPUTA: FILL readback epoch=<E> recovery=<R> seq=<seq> value <expected> words <n> guard0 <g0> guard1 <g1> cache_handback=ok PASS
```

The readback line may be emitted only after actual uncached/cache-synchronized reads. A host model may test formatting and fixtures but may never emit these as physical evidence.

## 8. Required negative checks and stop rules

Host byte-fixture tests should reject every one of these before a boot:

- wrong header size (total packet size placed in `ui32CmdSize`), wrong endian, wrong command type, or NULL given a payload;
- shared client write store used instead of KICK `ui32CWoffUpdate`;
- host PA or raw-heap device VA used as a 32-bit firmware pointer; raw-heap device VA incorrectly used as `sPCDevPAddr`;
- wrong coremem value/offset, CCB META DMA address, wrap mask, or context pointer;
- unaligned final write offset, zero-UFO FENCE/UPDATE, more than 64 UFOs, payload overflow, or CCB command crossing ring end without PADDING;
- KCCB slot wrap/full error, stale return slot, KCCB read accepted as execution, or `0x70037013` accepted as completion;
- host writes value 1 or 2 after publication, second stream sent before the first is read, value 2 accepted without value 1;
- missing CCB drain, missing UFO, new DEBUG_DUMP/reset/page fault/restart, assert, MMU fault, lockup, or failed poll;
- missing FWCCB dispatcher, invalid FWCCB index, stale `fw_epoch`/`recovery_seq`, or acknowledgement treated as permission to continue after an error notification;
- timeout treated as quiescence, resource freed while firmware can still reference it, or an uncertain submission retried as though unpublished.

On the phone, stop rather than retry unchanged on any new fault, unexpected panic, malformed notification, missing bounded completion, or failed Android return check. M2's read-only diagnostic does not acknowledge FWCCB; the later runtime dispatcher must copy and acknowledge entries without treating acknowledgement as success.

## 9. Cross-facet inputs and the live probe to request

### Needed from the other owners

- **Agent 2 (firmware/KCCB):** confirm the coremem-only S1 fix, FWCCB copy/ack dispatcher, epoch/recovery gate, and exact KCCB return-slot behavior for KICK. Preserve the stock HEALTH/STATEFLAGS gate and GP doorbell ordering. Flag any KICK return-bit semantics beyond advisory handling.
- **Agent 3 (MMU):** review the corrected `sPCDevPAddr=0xba139000` form and the 0x4000 all-invalid page catalogue for the sync fixture. Supply real MMU-v4 mappings, secure stream authority, and cache invalidation before CDM; do not let the empty catalogue become an engine-work shortcut.
- **Agent 5 (fences/completion):** [FENCE-UFO.md](FENCE-UFO.md) agrees on the 64-byte fixtures, exact UFO+`R=D=W` acceptance, stable second read, timeout dump, and optional blocked-fence control. One publication wording conflict needs alignment: its §3.4/§8 says to publish shared `CCCB_CTL.W`, whereas matched `RGXReleaseCCB` keeps the write host-local and KICK carries `ui32CWoffUpdate`; use the stock KICK rule in this document, not a direct host store. Supply UPDATE-after-CDM ordering, stale/timeout/reset handling, cache handback, and resource-quiescence rules for output and guards.
- **Agent 10 (integration):** supply CDM context-state/framework/body, `B`, actual fill ISA/streams and output layout, and join submit/KICK/UFO/readback under one sequence identity. Do not publish `AGXAccelerator` from KickSync alone.

### Requested live probes

1. **First, coremem-only S1:** after the implementation owner's host fixtures and enabled-gate ARM64 object/symbol checks pass, run the single gpu2-recipe rung-7 S1 variant from LIVE-EVIDENCE §6. It issues no client KICK. Capture the pre-SMC coremem line/readback, first complete current-boot decoded trace, read-only FWCCB, M2 health, 18-register survey, deliberate S1 panic, and Android return check. Stop on any init fault or invalid trace; do not retry unchanged.
2. **Only after clean S1, a separate S2-S4 boot:** enable the FWCCB dispatcher and the two exact streams above. Capture the complete console and first trace group, copied FWCCB entries, KCCB read/write and advisory return slots, CCB `W/R/D/wrap`, all context/address-form values, and the UFO transition from sentinel to value 1 to value 2. Stop on any new fault/reset/debug notification or stale epoch; do not combine this boot with the coremem-only proof.
3. **After S4, a separate CDM fill probe:** use agent-3 mappings and agent-10 body. Acceptance is the submit/drain/UPDATE trace plus separate SLC/CPU cache handback and output/two-guard-word readback, with an explicit receipt. Keep S1, KickSync S4, and real compute as three distinct physical milestones.

## 10. Primary repository evidence

- `research/ios26-gpu-r1/m3/receipts/fw-layout-r3.h` — measured structure sizes, offsets, command values, address constants, and trace IDs.
- `research/ios26-gpu-r1/m3/tools/fw_layout_r3.c` — provenance for each measurement.
- `research/ios26-gpu-r1/m3/src/blazer_gpu_tipc.c` — existing KCCB publisher, shared heap helpers, and unfinished M3 hooks; not a runnable client-stream implementation.
- `research/laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/reader.txt:254-344,400-418` — physical health, pending FWCCB, raw KCCB/firmware trace.
- `research/ios26-metal-native-20261102/integration/physical-a725-analysis-r1/pending-report.json` — lossless 112-byte FWCCB evidence and its limits.
- `research/ios26-metal-native-20261102/integration/physical-a725-analysis-r1/firmware-init-facts.json` — KCCB dispatcher trace-before-switch evidence.
- `research/ios26-hw-investigation-r1/GPU.md` — current physical/source distinction and M3 gap list.
- `research/ios26-metal-native-20261102/queue/src/hmg_queue.c` — existing host-only queue model; useful for invariants, not physical proof or a replacement for the matched source review above.
