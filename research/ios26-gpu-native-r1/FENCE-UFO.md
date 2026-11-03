# GPU completion and synchronization: UFO fences, polling, and the native interrupt route

Date: 2026-11-04. Owner: agent 5 (completion/synchronization). **READ-ONLY research:** no XNU edit, build, build lock, Git operation, phone action, or device-state change was performed. The only repository file written is this document.

Evidence labels: **PHYSICAL** is the named gpu2 phone receipt; **SOURCE** is exact source/layout inspection; **HOST** is an existing host-only implementation/model; **EXTERNAL** is linked prior art; **DESIGN** is a proposed implementation, not a physical result.

Cross-references: agent 10's [PLAN](PLAN.md) and [LIVE-EVIDENCE](LIVE-EVIDENCE.md), agent 1's [COREMEM-INIT](COREMEM-INIT.md), agent 2's [FIRMWARE](FIRMWARE.md), agent 3's [MMU](MMU.md), agent 4's [CCB-KICK](CCB-KICK.md), agent 6's [IOACCEL](IOACCEL.md), agent 7's [METAL](METAL.md), agent 8's [COMPOSITOR](COMPOSITOR.md), and agent 9's [PRIORART](PRIORART.md). Agent 4 owns the CCB/KICK implementation; this document fixes its completion contract. The interrupt route remains gated on agent 10's real GIC/IOKit integration.

Two cross-document corrections are explicit. First, stock advances a **host-local** client write offset and carries it in KICK; normal submission does not store it to shared `CCCB_CTL.ui32WriteOffset`. Second, [CCB-KICK §4](CCB-KICK.md) labels its UPDATE headers at `0x30/0x70`, but its own FENCE/NULL positions and correct final offsets `0x40/0x80` prove the labels should be **`0x28/0x68`**. This document uses the corrected labels and the stock host-local-write rule.

## 0. Decision and evidence boundary

1. **Do not issue a client KICK until clean S1 is physically established and agent 2's FWCCB dispatcher is present.** The sequence is agent 1's coremem-only S1 boot first, then a separate client-stream boot with the dispatcher and epoch/recovery gates (`FW_UP`). A recovered HEALTH PASS does not open the gate.
2. For M3, use one 32-bit UFO in uncached shared firmware memory. The host writes only `0xdead0000` once. Firmware executes stream 1 = `FENCE(0xdead0000) + NULL + UPDATE(0xc0de0001)`, then stream 2 = `FENCE(0xc0de0001) + NULL + UPDATE(0xc0de0002)`.
3. Each stream is exactly **64 bytes**: 24-byte FENCE + 16-byte NULL + 24-byte UPDATE. The two KICK write offsets are **`0x40` and `0x80`**. A one-UFO FENCE or UPDATE header has `ui32CmdSize=8`; NULL has size zero. Payload size excludes the 16-byte header.
4. Polling is the first completion route. A host DONE record requires the exact firmware-written UFO value **and** client `R=D=W` at the expected stream end, with clean fault/FWCCB state. KCCB consumption or execution is submission evidence only.
5. The independent proof is the decoded firmware trace: KCCB KICK slot 2/3, UFO_CHECK with the expected current/required values, UFO_CHECK_SUCCEEDED, and UFO_UPDATE with `0xc0de0001/2`, in that order. Do not search for the magic values alone: they also occur in the host-written CCB.
6. M3 proves firmware context admission, CCB parsing, equality checking, update writes, and ordering. It does **not** execute a GPU engine job. A real compute/render completion additionally needs an engine UPDATE with a unique job identity, SLC/cache handback, CPU readback, and guards.
7. Interrupts stay out of the first rung. The later route is FDT GIC SPI 130 / INTID 162 → existing `sleh_irq` Group-1 dispatch → a real external-GIC `IOInterruptController` → provider LISR → workloop MISR → strict UFO reaping. The IRQ counter is only a wake hint, never a completion counter.

## 1. What gpu2 establishes—and what it does not

PHYSICAL attempt: `research/laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/reader.txt`.

| Observation | Correct completion/IRQ interpretation |
|---|---|
| HEALTH consumed at line 284; STATEFLAGS return `0x1` at 314 | A waited KCCB command executed. Neither line proves a client CCB command or GPU engine completion. |
| Trace at 345-419 has `0x7004b052` CORE_MMU_FAULT and `0x700110c5` HIT_LOCKUP before HEALTH | Firmware faulted and recovered before health. S1 must reject this history, not just inspect final health. |
| `hwr 0xa` at boot becomes `hwr 0x1`; `fw_faults 0`, assert empty | Final state does not erase the earlier HWR. |
| FWCCB remains `w=1,r=0`, type DEBUG_DUMP `0x2abc006a` | It is pending diagnostic evidence, not completion and not an acknowledgement. M3 must not advance `r` without a real dispatcher. |
| `EVENT_STATUS +0x130 = 0` at line 428 | This is the generic core event register, **not** dedicated OS0 IRQ status. It says nothing about the OS0 source at `+0xbd0`. |
| MMU fault/status registers read zero at 429-433; timer runs | Supporting post-recovery state only. Zero final registers do not make initialization clean. |
| No external-SPI registration or IRQ-counter sample exists | gpu2 provides no physical interrupt-delivery proof. |

The first complete firmware-log group contains 476 words. The mirrored text duplicates it; decode one group or stop at the first `M2 fwlog: end`, not the concatenation as if it were new activity ([COREMEM-INIT §1.3](COREMEM-INIT.md)).

## 2. Prior art: transferable rules, non-transferable ABI

### 2.1 Asahi AGX completion and notification

- [`event.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/event.rs) allocates event slots backed by shared monotonically advancing stamps, reads stamps with acquire ordering, and signals the owning work queue.
- [`channel.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/channel.rs) handles the firmware receive doorbell by polling event/log/statistics rings. Event flags wake slot owners; channel errors and faults take separate paths.
- [`workqueue.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/workqueue.rs) validates the current stamp against ordered pending work, retires completed commands, advances the CPU free pointer, and fails pending work on device errors.
- [`gpu.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/gpu.rs) separates submission doorbells from receive notifications and fault/timeout recovery.

**Reuse:** notification wakes validation; validation retires in order; resources remain owned until completion; faults fail rather than fabricate success. **Do not transplant:** AGX stamps, RTKit endpoints, channels, event values, or firmware layouts are unrelated to PowerVR UFOs.

### 2.2 Exact Tensor PowerVR source (authoritative for this design)

Pinned GrapheneOS `kernel_pixel_6.12` commit `5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`, DDK 26.1@6967606, lga production:

- [`rgx_fwif_shared.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/volcanic/rgx_fwif_shared.h): eight-byte `RGXFWIF_UFO { puiAddrUFO, ui32Value }`, address mask `0xfffffffc`, and CCCB `W/R/D/wrap` meaning.
- [`rgxccb.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxccb.c): command-size calculation, 16-byte header, eight-byte packet alignment, and FENCE/DM/UPDATE encoder.
- [`rgxkicksync.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxkicksync.c): KICK names the common context, host CCB write offset, wrap mask, and zero cleanup count.
- [`rgxinit_common.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxinit_common.c): STATUS test → CLEAR → CLEAR readback → firmware IRQ-counter sample.
- [`volcanic/rgxinit.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/volcanic/rgxinit.c): LISR schedules MISR after acknowledged source/counter activity; MISR handles FWCCB and notifies command completion.
- [`rgx_fwif_sf.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/include/rgx_fwif_sf.h): independent trace formats `UFO Check: [addr] is X requires Y`, `UFO Checks succeeded`, and `UFO Update: [addr] = value`.

### 2.3 Mainline IMG/Rogue comparison

- Mainline [`pvr_rogue_fwif_shared.h`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_rogue_fwif_shared.h) has the same conceptual eight-byte UFO and `W/R/D` dependency model.
- [`pvr_device.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_device.c) uses a hard IRQ to wake a threaded handler, then clears pending firmware events, processes FWCCB, wakes KCCB waiters, and processes active queues.
- [`pvr_fw_riscv.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_fw_riscv.c) supplies the RISC-V OS0 pending/clear concept; [`pvr_queue.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_queue.c) distinguishes UFO-backed job fences from other fence types.

**Warning:** mainline register offsets/masks differ (`+0xbd8/+0xbe8`, one source bit there versus the pinned Tensor `+0xbd0/+0xbe0`, two source bits). Use mainline for structure only, never for Tensor constants.

### 2.4 Attached `ios-tegu-ios26-bringup (1).zip`: bounded polling on a different GPU

The user-supplied archive's `shim/tegu/gpu_queue.inc` waits with a bounded counter loop for an exact GPU-written token, then checks extraction progress, output words/guards, and stream/fault state. Its `0434-tegu-gpu-kernel-driver-update.patch` explicitly describes polling a GPU-written sequence word when no GPU IRQ is routed, with a separate completion thread and oldest-first retirement; `docs/METAL-REARCH.md` records queued submissions completing through a GPU-written sequence word.

**Reuse:** bounded polling is a valid first physical proof, exact tokens beat inferred progress, and output/fault checks plus resource retention belong after the token. **Do not transplant:** this is Mali CSF queue/doorbell/scoreboard machinery, not PowerVR UFO layout or evidence for Tensor's GIC route. The archive changes no constant or step in this document.

## 3. Exact M3 UFO, CCB, and KICK layout

### 3.1 Storage and address forms

Allocate zeroed objects in the shared carve-out and retain them through the deliberate reset. Agent 3's address correction governs: page-catalogue DMA is **not** the firmware-heap device VA.

| Item | Exact form |
|---|---|
| UFO backing | At least one aligned 32-bit word; reserve its containing page/allocation so no other agent writes it. Initial host store: `0xdead0000`. |
| UFO address in FENCE/UPDATE | 32-bit uncached RISC-V pointer: `ufo_fw = 0x40000000 | ufo_raw_offset`; require `(ufo_fw & 3) == 0`. It is not a CPU VA, CPU PA, or 40-bit `0xe1...` device VA. |
| `RGXFWIF_UFO` | 8 bytes: `+0x0 puiAddrUFO=ufo_fw`, `+0x4 ui32Value`. Low address bits are masked by `0xfffffffc`; bit 0 must remain clear for this ordinary sync-prim test. |
| CCB/control/context pointers | 32-bit uncached firmware pointers: `0x40000000 | raw_offset`. |
| `sCCBMetaDMAAddr` | 64-bit raw firmware-heap device VA: `0xe1c0000000 + ccb_raw_offset`. |
| Page catalogue in `FWMEMCONTEXT+0x0` | 64-bit backing DMA/physical address. For this carve-out/identity-DMA experiment: `0xb9f00000 + pc_raw_offset`, not `0xe1c0000000 + pc_raw_offset`. See [MMU §0/§3](MMU.md). |
| Client CCB control | Initially `W=0`, `R=0`, `D=0`, wrap mask `0x1fff` for 8 KiB. Host separately tracks `host_write=0`; normal submission carries the new offset in KICK rather than storing shared `W`. |
| Common context | GP DM 0, `HAS_DEFER_COUNT=0x2`, memory-context pointer at `+0x68`, `sLastFailedUFO` at `+0x60`; all unlisted fields remain the measured zero/default values. |

For the canonical allocation fixture in [CCB-KICK §2.3](CCB-KICK.md), use `ctx_fw=0x4023e000`, `ccb_fw=0x40240000`, `ccb_dma=0xe1c0240000`, `pc_dma=0xba139000`, and `ufo_fw=0x40242000`. Job refs are `E1=0x1001/I1=1` and `E2=0x1002/I2=2`. Assert that the M2 allocator ended at `0x239000`; if allocation order changes, regenerate every address instead of reusing these values.

`D` (`ui32DepOffset`) separates runnable commands from commands whose fence dependencies are unmet. `R==W` alone means consumed; `D==W` means no remaining dependency block. Neither replaces reading the UPDATE target.

### 3.2 CCB command header and concrete bytes

Every header is 16 bytes:

| Offset | Field | Rule |
|---:|---|---|
| `+0x0` | `eCmdType` | FENCE `0x2abc00d4`, NULL `0x2abc80d2`, UPDATE `0x2abc00d5`. |
| `+0x4` | `ui32CmdSize` | Payload bytes only: 8 for one-UFO FENCE/UPDATE, 0 for NULL. |
| `+0x8` | `ui32ExtJobRef` | Same bounded external reference across all three packets of one stream; distinct between streams. |
| `+0xc` | `ui32IntJobRef` | Same bounded internal reference across all three packets of one stream; distinct/monotonic between streams. |

Let `E1/I1` and `E2/I2` be the two job-reference pairs. All integer fields are little-endian 32-bit words.

| CCB offset | Packet contents |
|---:|---|
| `0x00` | FENCE header: type `0x2abc00d4`, size 8, refs `E1/I1`. |
| `0x10` | UFO descriptor: `ufo_fw`, expected `0xdead0000`. |
| `0x18` | NULL header: type `0x2abc80d2`, size 0, refs `E1/I1`. |
| `0x28` | UPDATE header: type `0x2abc00d5`, size 8, refs `E1/I1`. |
| `0x38` | UFO descriptor: `ufo_fw`, new value `0xc0de0001`. |
| **`0x40`** | **End of stream 1; KICK 1 `ui32CWoffUpdate=0x40`.** |
| `0x40` | FENCE header: type `0x2abc00d4`, size 8, refs `E2/I2`. |
| `0x50` | UFO descriptor: `ufo_fw`, expected `0xc0de0001`. |
| `0x58` | NULL header: type `0x2abc80d2`, size 0, refs `E2/I2`. |
| `0x68` | UPDATE header: type `0x2abc00d5`, size 8, refs `E2/I2`. |
| `0x78` | UFO descriptor: `ufo_fw`, new value `0xc0de0002`. |
| **`0x80`** | **End of stream 2; KICK 2 `ui32CWoffUpdate=0x80`.** |

There is no padding inside these two streams. Eight-byte packet alignment is sufficient; do not add a zero UFO or extra 16-byte alignment padding. All unused CCB bytes stay zero.

### 3.3 KCCB KICK slots

After M2's HEALTH slot 0 and STATEFLAGS slot 1, use KCCB slots 2 and 3. Each command is `0x70` bytes:

| Command offset | Value |
|---:|---|
| `+0x00` | `eCmdType=0x2abc0065` (KICK) |
| `+0x04` | flags 0 |
| `+0x08` | common-context 32-bit uncached firmware pointer |
| `+0x0c` | `ui32CWoffUpdate`: `0x40` for slot 2, `0x80` for slot 3 |
| `+0x10` | `ui32CWrapMaskUpdate=0x1fff` |
| `+0x14` | `ui32NumCleanupCtl=0` |
| `+0x18..+0x6f` | zero |

Reset the selected return slot before publication and record its result, but do not require a KICK return to certify stream completion. `PVRSRVRGXKickSyncKM` submits without the stock waited-return completion used for STATEFLAGS. The UFO is the completion oracle.

### 3.4 Publication and host wait algorithm

For each stream, with no prior unread KICK:

1. Verify `FW_UP` (clean S1 plus dispatcher), live firmware epoch/recovery sequence, free CCB capacity, expected previous UFO value (`0xdead0000` then `0xc0de0001`), and initial/final offsets.
2. Write the complete 64-byte stream with aligned 32-bit stores. `aoc_barrier()` (`DSB SY`) makes producer writes complete on the device mapping. Advance the **host-local** `host_write` to `0x40` or `0x80`; do not store it to shared `CCCB_CTL.W`. Construct the KCCB slot carrying that offset, publish KCCB `W` after a barrier, then write GP MTS doorbell `RGX+0xb00=0`. Firmware applies the KICK's client write-offset update.
3. Bound KCCB consumption independently. Slot 2 must reach `kccb_r=3`; slot 3 must reach `kccb_r=4`. Record return value and CCB `W/R/D`, but label this S2 admission/consumption only.
4. Poll once per 1 ms for at most `GTA_M3_FENCE_MS=1000` ms. On each pass read the UFO and fault/FWCCB state, issue an appropriate visibility barrier (`aoc_dmb()` for dependent host observations; existing uncached Device map needs no cache clean/invalidate), then read `W/R/D` again.
5. DONE only if all are true:
   - UFO equals the expected new value exactly (`0xc0de0001` or `0xc0de0002`);
   - CCB `W=R=D=0x40` for stream 1 or `0x80` for stream 2;
   - the value remains unchanged across a second read after the barrier;
   - no stale firmware epoch, new DEBUG_DUMP, context reset, FW page fault, GPU restart, assert, firmware fault, CORE_MMU_FAULT, HIT_LOCKUP, FAILED_HW_POLL, or unplanned panic.
6. Only after stream 1 DONE may stream 2 be encoded/published. S4 PASS requires stream 2 DONE and the independent trace criteria below.

Unexpected values are failures, not progress: stream 1 accepts only sentinel→`0xc0de0001`; stream 2 accepts only `0xc0de0001`→`0xc0de0002`. The host must never write either expected new value after initialisation, including in logging, timeout recovery, test success paths, or cache maintenance.

On timeout, print the current UFO, `W/R/D`, KCCB `W/R`, return slot, common-context `sLastFailedUFO` (`+0x60`), FWCCB producer/consumer and fault/HWR state. Timeout is not DMA quiescence: retain the catalogue, contexts, control, CCB, UFO, and trace allocations through reset; do not retry unchanged.

## 4. Proving records and independent firmware confirmation

### 4.1 Host console records

Use stable fields; pointer/timing values vary, offsets and values do not. `S2` is admission, `S3/S4` are firmware-only command completion, not engine completion.

```text
HK GPUTA: M3 S2 submit cmd=1 epoch=1 recovery=0 kccb_slot=2 ctx=0x4023e000 host_write=0x40 wrap=0x1fff ext=0x1001 int=1 ufo_fw=0x40242000 before=0xdead0000 want=0xc0de0001
HK GPUTA: M3 S2 admitted cmd=1 epoch=1 recovery=0 kccb_r=3 rtn=<raw> read_ms=<N> ccb_w=<W> ccb_r=<R> ccb_d=<D>
HK GPUTA: M3 S3 FW command complete cmd=1 epoch=1 recovery=0 source=POLL_UFO ufo=0xc0de0001 poll_ms=<N> ccb_w=0x40 ccb_r=0x40 ccb_d=0x40 fw_faults=0
HK GPUTA: M3 S4 submit cmd=2 epoch=1 recovery=0 kccb_slot=3 ctx=0x4023e000 host_write=0x80 wrap=0x1fff ext=0x1002 int=2 ufo_fw=0x40242000 before=0xc0de0001 want=0xc0de0002
HK GPUTA: M3 S4 admitted cmd=2 epoch=1 recovery=0 kccb_r=4 rtn=<raw> read_ms=<N> ccb_w=<W> ccb_r=<R> ccb_d=<D>
HK GPUTA: M3 S4 FW command complete cmd=2 epoch=1 recovery=0 source=POLL_UFO ufo=0xc0de0002 poll_ms=<N> ccb_w=0x80 ccb_r=0x80 ccb_d=0x80 fw_faults=0
HK GPUTA: M3 S4 PASS: epoch=1 recovery=0 two ordered firmware KickSync commands; no GPU engine job
```

A timeout uses an explicit negative record, never a DONE/PASS line:

```text
HK GPUTA: M3 TIMEOUT cmd=<N> epoch=<E> recovery=<R> ufo=<actual> want=<expected> ccb_w=<W> ccb_r=<R> ccb_d=<D> kccb_w=<W> kccb_r=<R> rtn=<raw> last_failed_ufo=<addr/value> resources=RETAINED
```

### 4.2 Firmware-log records required in the same boot

Decode the first complete current-boot `M2 fwlog` group with `m2/tools/fwlog_decode.py` and the pinned `rgx_fwif_sf.h`. Despite its name, `KCCBCMD_EXEC` is emitted before the firmware's command-type switch: use it as KCCB decode/admission evidence, never as proof that client work executed. The relevant decoded text and trace IDs are:

```text
KCCB Slot 2: Cmd=0x2abc0065, Driver ID=0                    [RGXFW_SF_MTS_KCCBCMD_EXEC, id 0x70037013]
UFO Check: [0x40242000] is 0xdead0000 requires 0xdead0000  [RGXFW_SF_MAIN_UFO_CHECK, id 0x70031011]
UFO Checks succeeded                                      [RGXFW_SF_MAIN_UFO_CHECK_SUCCEEDED, id 0x70001012]
UFO Update: [0x40242000] = 0xc0de0001                     [RGXFW_SF_MAIN_UFO_UPDATE, id 0x70021017]
KCCB Slot 3: Cmd=0x2abc0065, Driver ID=0                    [RGXFW_SF_MTS_KCCBCMD_EXEC, id 0x70037013]
UFO Check: [0x40242000] is 0xc0de0001 requires 0xc0de0001  [RGXFW_SF_MAIN_UFO_CHECK, id 0x70031011]
UFO Checks succeeded                                      [RGXFW_SF_MAIN_UFO_CHECK_SUCCEEDED, id 0x70001012]
UFO Update: [0x40242000] = 0xc0de0002                     [RGXFW_SF_MAIN_UFO_UPDATE, id 0x70021017]
```

`cCCB Woff update = 64` and later `= 128` with DM 0/context `0x4023e000` (trace `0x7003100e`), plus NULL task `0x70021053` and MTS client-header records when present, are supporting evidence. The acceptance wrapper should parse trace IDs and parameter counts, not rely only on text matching. A strict sequential acceptance pass must reject malformed/truncated records and unknown gaps; the current scan-forward decoder is useful navigation but cannot turn an invalid trace into a zero-fault PASS. Preserve raw trace indices/timestamps; firmware and host clocks need not share an epoch, so ordering is the join.

The proof matrix is:

| Claim | Host evidence | Independent firmware evidence |
|---|---|---|
| KICK admitted | KCCB `r=3/4`, expected slot/context/W/wrap | KCCB slot 2/3 decode/admission (`KCCBCMD_EXEC` before the type switch) |
| Command 1 complete | Exact `0xc0de0001`, `R=D=W=0x40` | Check sentinel→succeeded→UPDATE 1 |
| Command 2 ordered after 1 | Stream 2 sent only after S3 | Slot 3/check value 1 after UPDATE 1 |
| Command 2 complete | Exact `0xc0de0002`, `R=D=W=0x80` | Check value 1→succeeded→UPDATE 2 |
| No hidden fault | Clean S1/S3/S4 shared state | No new fault/reset/lockup/failed poll/DEBUG_DUMP in the same complete trace |

### 4.3 What the two streams do not prove

Because stream 2 is sent after value 1 is already visible, its FENCE is satisfied when checked. This proves the equality check and ordering but **not a temporal stall**. A separate later negative control may use two GP contexts sharing the UFO:

1. Context A executes `FENCE(0xc0de00a1)+NULL+UPDATE(0xc0de00a2)` while the word is `0xc0de0002`; require A's `D` to remain at its FENCE and no A UPDATE for a bounded window.
2. Context B executes a valid stream whose firmware UPDATE writes `0xc0de00a1`.
3. Require A then to log `UFO Check ... is 0xc0de00a1 requires 0xc0de00a1`, succeed, and write `0xc0de00a2`.

That is the correct proof of an actually blocked fence; do not add it to the minimal first S4 boot.

## 5. Persistent completion, cache, and WAIT semantics

The existing HOST queue model in `uc-r4/tree/iokit/Kernel/arm/hmg_queue.c` supplies the right production contract, but has no physical execution evidence:

- Give each job a distinct nonzero token and UFO slot (`sync_fw + batch/job*4`) rather than reusing M3's one word. A completion identity is `(firmware generation, context epoch, sequence, context handle, UFO address, token)`.
- Reap oldest sequence first. Strict equality rejects stale, future, wrong-address, duplicate, and out-of-order events. An interrupt or KCCB return cannot call `hq_engine_event`; only `HQ_SOURCE_ENGINE_UFO` may do so.
- Engine DONE is not CPU visibility. Before CPU readback/unpin, complete the separate context-fenced SLC operation and receipt, then the required CPU cache/alias handback. In the HOST candidate the SLC KCCB is `0x2abc0068`, context at `+8`, `bInvalidate=0` at `+12`, DM-context byte=1 at `+13`, return `0x1`; this still requires physical validation.
- `WAIT(seq)` first checks actual completed state. Poll/wake, then recheck. A timeout changes only the wait result to TIMEOUT; it does not complete/fail the job or release resources. Closing, reset, missing completion, stale epoch, and handback failure retain mappings and pins until authentic completion or proven DMA quiescence.
- Presentation uses the same identity: `submit → engine UFO → SLC receipt → CPU/surface handback → DPU present`. DPU ownership ends separately; GPU completion alone does not permit DPU reading.

This matches agent 6's required `HMGU: done registry=<R> context=<ctx> seq=<S> engine=<proof> cache=<proof>` line and agent 10's readiness rule. KickSync S4 is never sufficient for IOAccelerator readiness.

## 6. Native GPU interrupt design

### 6.1 Current XNU gap and exact hardware facts

SOURCE:

- FDT [`lga-base.dtsi`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/devices/google/lga/dts/lga-base.dtsi) describes GICD `0x05880000`, GICR `0x05900000`, and GPU `GIC_SPI 130 IRQ_TYPE_LEVEL_HIGH`.
- `pexpert/arm/pe_fiq.c` maps GICD/GICR, enables Group 1 and the CPU interface, but only configures timer/IPI sources. It has no external-SPI registration path.
- `osfmk/arm64/sleh.c:sleh_irq` acknowledges `ICC_IAR1_EL1`; for a non-timer/non-SGI source it calls `cdp->interrupt_handler(..., intid)` and then writes `ICC_EOIR1_EL1`.
- `SweetPlatformExpert.cpp` explicitly excludes the GIC nub. The native provider has no resolved `IOInterruptControllers`/`IOInterruptSpecifiers` route. Existing `firmware-r3/hmfw_irq_xnu.cpp` correctly returns unavailable instead of guessing one.
- `IOService::resolveInterrupt` resolves a named controller and stores its OSData vector. `IOInterruptController::registerInterrupt` interprets the first native `uint32_t` as the vector number. Therefore vectorData must be the resolved native value **162**, not the raw four-cell FDT tuple `<0,130,4,0>` and not an invented virtual IRQ.
- The generic `IOCPUInterruptController` indexes its vector array by source and is for CPU-local sources; it is not a safe external-SPI 162 dispatcher. Agent 10 must supply the real external-GIC dispatch/controller before unmasking this interrupt.

SPI 130 corresponds to GIC INTID `130+32=162`. This arithmetic is authoritative; IOKit route publication and delivery still require physical proof.

### 6.2 GIC registers for agent 10's controller

These are standard GICv3 register calculations applied to the pinned GICD base/INTID. They are a **DESIGN checklist**, not evidence that REE writes are currently safe or effective. Read back group, type, route, priority, mask, and RWP state and prove actual delivery.

| Purpose | Register / address | Required value or check |
|---|---|---|
| Group | `GICD_IGROUPR5`, GICD `+0x094` (`0x05880094`) | Bit 2 set for Group 1; confirm non-secure Group-1 semantics because TrustZone owns Group 0. |
| Trigger | `GICD_ICFGR10`, `+0xc28` (`0x05880c28`) | Bits `[5:4]=00`, level-high. Preserve other bits. |
| Priority | `GICD_IPRIORITYR40`, `+0x4a0` | Byte 2 (bits 23:16) a valid unmasked priority, consistent with the existing `0xa0` policy; CPU `ICC_PMR_EL1=0xff` already permits it. |
| Route | `GICD_IROUTER162`, `+0x6510` (`0x05886510`) | Actual target PE/1-of-N policy selected by the controller. For the one-A725 probe, MPIDR `0x200` is a candidate only after readback; do not hard-code blindly. |
| Mask | `GICD_ICENABLER5`, `+0x194` (`0x05880194`) | Write bit 2 (`0x4`) to mask before configuration/drain. |
| Pending clear | `GICD_ICPENDR5`, `+0x214` (`0x05880214`) | Write bit 2 to clear stale pending state while masked, if the controller's route contract requires it. |
| Enable | `GICD_ISENABLER5`, `+0x114` (`0x05880114`) | Write bit 2 only after provider registration, OS0 clear/readback, and all route checks. |

Honor GICD RWP where applicable and preserve unrelated bits. Existing Group-1 CPU-interface enable and `sleh_irq` EOIR handling remain in use; do not add a second EOI.

### 6.3 Bind and kick sequence

1. Keep polling while the route is absent. For the IRQ proof, publish a real external-GIC controller with a vector array covering INTID 162 and a `handleInterrupt` method compatible with `sleh_irq`/`IOInterruptController`.
2. Publish exactly one controller name and one specifier on the actual GPU provider/backend. Specifier OSData is native `uint32_t 162`; DT options identify level-high. Resolve `_interruptSources[0].interruptController` and `vectorData` before registration. `getInterruptType(0)` must report level.
3. Mask INTID 162, configure and read back group/type/priority/route, and clear stale pending state. Register provider source 0 with the existing `HMFWInterrupt` LISR before enabling it. The AGX registry object and the GPU hardware provider may be different IOService objects, but they must reference the same native backend/epoch—not two backends.
4. Clear the GPU's dedicated OS0 source while the GPU is powered: read `RGX_CR_IRQ_OS0_EVENT_STATUS +0xbd0`; if `status & 0x3`, write `0x3` to `RGX_CR_IRQ_OS0_EVENT_CLEAR +0xbe0`, read CLEAR back, then `OSSynchronizeIO()`/`DSB SY`. Do not use generic `EVENT_STATUS +0x130` as a substitute.
5. Enable provider source 0, then unmask GICD ISENABLER5 bit 2. Submit one command. In the proving boot disable completion polling so an IRQ-path MISR is required to reap it; retain the bounded timeout.

### 6.4 LISR/MISR and completion handoff

The existing HOST `firmware-r3` ISR order is the correct starting point:

**LISR, finite/no sleeping/no queue reentry:**

1. Read OS0 STATUS. If no source bits, record spurious and do not sample/claim work.
2. Write CLEAR mask `0x3`, read CLEAR back, and execute the device visibility barrier. CLEAR readback orders acknowledgement before shared-counter sampling, avoiding a stale-count race.
3. Read firmware thread-0 `RGXFWIF_OSDATA.aui32InterruptCount[0]` at OSDATA `+0x230`. Assign the actual value to `host_sample`; never increment a fabricated counter and never compare with `>=` (wrap is legal).
4. If the counter changed or an error needs diagnosis, schedule the IOInterruptEventSource MISR. Return so `sleh_irq` can EOIR. The IRQ/counter is only a wake hint.

**MISR/workloop:**

1. Read current UFOs, CCB `W/R/D`, KCCB/FWCCB and fault/HWR state. Process fault/reset indications before normal reaping and stop new admission. Do not ACK FWCCB without its real dispatcher.
2. For each pending job, require the full generation/epoch/sequence/context/UFO/token match in order. Only now mark engine DONE and issue the separate SLC/cache handback. If no valid UFO changed, leave the job pending; counter movement alone completes nothing.
3. After cache handback, mark HMGU completion and wake WAIT/notify sleepers. Emit the captured LISR/MISR evidence from process/workloop context rather than doing unbounded logging in the hard ISR.
4. Polling may remain a diagnostic fallback in production, but the IRQ acceptance run must show `source=IRQ_UFO`, not merely a poller winning after an unrelated IRQ.

### 6.5 Required IRQ proving lines

The LISR fields are captured atomically and printed with the MISR record:

```text
blazer-gic: gpu route epoch=<E> spi=130 intid=162 level=high group=1 source=0 vector=162 router=<readback> enabled=1
blazer-gpu: IRQ LISR seq=<N> epoch=<E> intid=162 status=<raw> clear=0x3 clear_rb=<raw> fw_irq_count=<actual>
blazer-gpu: IRQ MISR seq=<N> epoch=<E> fw_irq_count=<actual> ccb_w=<W> ccb_r=<R> ccb_d=<D> fwccb_w=<W> fwccb_r=<R>
HMGQ: engine ctx=<ctx> seq=<S> ufo=<ufo_fw> token=<T> source=IRQ_UFO complete=1
HMGQ: slc ctx=<ctx> seq=<S> receipt=0x1 inval=0 dm_context=1
HMGU: done registry=<R> context=<ctx> seq=<S> engine=IRQ_UFO cache=<receipt>
```

The independent firmware trace must still contain the matching `UFO Update: [<ufo_fw>] = <T>`. If only the GIC/LISR lines appear, interrupt delivery passed but completion did not. If only the UFO appears, the command completed but the IRQ route failed. Do not merge those milestones.

### 6.6 Mask/drain/stop

Close new submissions first. Complete or genuinely quiesce pending work; mask GICD ICENABLER5 bit 2 and disable provider source 0; synchronize the actual controller callback; unregister it; then verify stable OS0 status, firmware IRQ count, and FWCCB state across two complete observations before secure STOP/power-off. `IOInterruptController::disableInterrupt` can spin on `interruptActive` without a timeout, so the new controller's mask/synchronize contract itself needs review/proof. Timeout, an empty ring, or a written host counter never establishes drain.

## 7. Stop rules and risk ledger

| Risk | Required stop/mitigation |
|---|---|
| Recovered init fault presented as clean | Require agent 1's clean pre-health and final trace before any KICK. Stop on CORE_MMU_FAULT/HIT_LOCKUP/FAILED_HW_POLL/HWR/init DEBUG_DUMP. |
| Wrong address family | UFO/context pointers are `0x40......`; CCB DMA is `0xe1c...`; page catalogue is backing DMA/PA. Byte-test all three. |
| Host-forged completion | Host writes only `0xdead0000`; reject any later host store to `0xc0de0001/2`. Independent proof must come from structured firmware trace, not CCB bytes. |
| Arithmetic/encoder regression | Require 64-byte fixtures with `W=0x40/0x80`, UPDATE at `0x28/0x68`, one-UFO payload size 8, no padding. |
| Ring movement mistaken for completion | Require exact UFO plus `R=D=W`; KCCB read/return and CCB movement alone never suffice. |
| Same-word ABA in a persistent driver | M3 reuses a word only for two ordered values. Production uses per-job address+token and full identity/epoch/order checks. |
| Timeout frees live DMA | Retain all objects through reset or proven quiescence. No timeout unpin, no automatic retry/reset. |
| FWCCB mistaken for completion/ACK | Never advance FWCCB `r` without a dispatcher. Reset/page-fault/restart/new DEBUG_DUMP is failure. |
| Mainline IRQ constants used on Tensor | Use pinned `+0xbd0/+0xbe0`, mask `0x3`, OSDATA counter `+0x230`; not mainline `+0xbd8/+0xbe8`. |
| IRQ enabled without a real route | No GIC unmask until controller/vectorData/provider/source/level/route/mask/synchronize are resolved and read back. |
| IRQ counter mistaken for job completion | Counter only schedules MISR. Strict UFO identity + cache handback is required for HMGU DONE. |
| Combined boot hides a failed S1 | Prefer coremem-only S1 first. Any combined rung must emit no KICK after an S1 failure. |
| Evidence duplication/inflation | Decode the first complete trace group once. Keep S1, KickSync S4, engine C1, IRQ delivery, and Metal rendering as separate milestones. |

## 8. Needs from other owners and live probes

### Agent 4 — CCB/KICK

- Consume the corrected 64-byte fixtures: stream ends `0x40/0x80`, UPDATE offsets `0x28/0x68`; supply `ctx_fw`, `ufo_fw`, `ufo_raw_offset`, job refs, and the exact KCCB slot/return records.
- Publish the full stream with barriers, advance host-local `host_write`, and carry it in KICK; do not store normal submissions to shared CCCB `W`. Then publish KCCB `W` and the GP doorbell. Do not send stream 2 before stream 1 DONE. Preserve every allocation on timeout.
- Dump CCB `W/R/D` and `sLastFailedUFO` on failure; keep host test firmware—not host production code—as the only writer of expected UPDATE values.
- If the temporal-fence negative control is later scheduled, supply the second independent GP context; do not complicate the first S4 boot.

### Agent 2 — firmware/HWR/lifecycle

- Confirm clean-S1 trace/FWCCB acceptance, the meaning of any new HWR/reset notification, and the secure STOP/domain-off sequence needed after the IRQ drain.
- Keep the TA 24.2/26.1 and `process_st_info(278)` findings separate from completion. Supply any firmware-side caveat about OS0 source bits/counter behavior; no firmware byte change is requested here.

### Agent 10 — integration/GIC and evidence

- Preserve the narrow coremem-only S1 gate before the combined/stream recipe. Capture host S2-S4 records and the first complete decoded firmware trace with exact CCB/UFO offsets.
- Supply the actual external-GIC controller and resolved provider route: controller name, native vectorData 162, level/affinity, mask/synchronize/drain implementation, and readback. Do not enable SPI 130 against the current absent route.
- For the IRQ proof, disable completion polling and join `route → LISR → MISR → engine UFO → SLC → HMGU done` to the same firmware trace. Return to Android and run the normal return check after every attempt.

### Requested live probes, in order

1. **Next completion probe (after S1):** a separate rung-7 temporary boot with agent 2's FWCCB dispatcher and the two polled streams. Require the exact S3/S4 host lines and the independent KICK/CHECK/UPDATE trace above; no IRQ writes and no engine/Metal claim.
2. **Later fence-blocking control:** two GP contexts as in §4.3, proving `D` stalls before B's firmware UPDATE and resumes afterward. This is optional and follows basic S4.
3. **Much later IRQ probe:** one owned command with completion polling disabled. Accept only if INTID 162 LISR evidence, strict IRQ_UFO completion, cache receipt, and the independent firmware UPDATE all appear. This waits for agent 10's real controller and agent 2's lifecycle support.

The immediate live request is **probe 1 only**. There is no request to boot the current partial M3 source unchanged or to enable the GPU interrupt yet.
