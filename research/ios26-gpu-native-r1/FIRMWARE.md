# PowerVR firmware runtime: boot, KCCB/FWCCB, proof logs, and HWR recovery

Date: 2026-11-04. Owner facet: GPU firmware runtime (agent 2). **Read-only research:** no XNU edit, build, build lock, Git index/repository mutation, or phone action was performed. The only file written is this document.

Evidence labels: **PHYSICAL** means the gpu2 phone receipt; **SOURCE** means XNU or the pinned PowerVR DDK; **HOST** means offline decoding; **DESIGN** means a proposed implementation, not a phone result. XNU references are to nested-XNU `hk-gpu-m2-r1` (`58f0893`) and the uncommitted M3 candidate named explicitly below. The matching vendor tree is GrapheneOS `kernel_pixel_6.12` at `5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`, DDK 26.1, lga production, BVNC 71.2.2448.1212.

## 0. Decision and readiness contract

Use the existing Trusty load/start path and M2 command shapes. Do not change signed firmware, invent a firmware protocol, or add an OS-online command. Agent 1's coremem-only correction is the next physical experiment; its clean S1 result gates every client KICK.

The firmware service has this state machine:

```text
OFF -> LOADING -> STARTED_UNVERIFIED -> FW_HEALTHY -> FW_UP <-> RECOVERING
                                          |             |              |
                                          |             |              +-> FW_UP (reproved) or LOST
                                          +-------------+-> STOPPING -> OFF
```

- `STARTED_UNVERIFIED`: `bFirmwareStarted=1` only. No client submission is allowed.
- `FW_HEALTHY`: clean init, HEALTH consumption/decode, no-op STATEFLAGS execution, no fault/assert, and valid trace evidence. This is the coremem-only S1 result; it still accepts no client submission.
- `FW_UP`: `FW_HEALTHY` plus a working FWCCB dispatcher. Only this state accepts agent 4's KCCB KICKs.
- `RECOVERING`: submissions frozen, waits invalidated, old work failed or explicitly proved complete, resources retained. It never reports readiness.
- `LOST`: recovery failed or repeated too often. No automatic retry loop and no Metal readiness.
- Give every full boot/restart a monotonically increasing `fw_epoch`, and every context-HWR recovery a `recovery_seq`. Include both in submission, fence, completion, and log records. A waiter from an older epoch/recovery must fail as stale, never complete from a newly reused slot or UFO value.

`FW_UP` is **firmware control-path readiness only**. It is not a client stream, GPU engine completion, compute, Metal, or Liquid Glass. Agent 10 must additionally require VM/context/stream/engine/cache readiness before publishing the native accelerator.

Companion documents read and cross-checked: [COREMEM-INIT.md](COREMEM-INIT.md), [MMU.md](MMU.md), [CCB-KICK.md](CCB-KICK.md), [FENCE-UFO.md](FENCE-UFO.md), [IOACCEL.md](IOACCEL.md), [METAL.md](METAL.md), [COMPOSITOR.md](COMPOSITOR.md), [PRIORART.md](PRIORART.md), [PLAN.md](PLAN.md), and [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md).

## 1. What gpu2 actually proved

Receipt: `research/laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/reader.txt`.

**PHYSICAL PASS:** Trusty connected; `SEND_FIRMWARE_IMAGE` returned `{cmd=1,result=0}`; shared data was accepted; GPU power/identity passed; SMC START returned zero; firmware set `bFirmwareStarted=1`; KCCB slot 0 HEALTH was consumed; slot 1 STATEFLAGS returned `0x1`; OS0 became ACTIVE with `rt=0xa`; `fw_faults=0`; assert was empty; timer ran (`reader.txt:162-177,201,247-319,440-442`).

**PHYSICAL QUALIFICATION:** this was recovery after a real init fault, not clean boot. Offline decoding of one 476-word trace gives this order (`reader.txt:345-419`):

1. `RGXFW_SF_HWR_MMU_FAULT_EVENT`, then `RGXFW_SF_HWR_CORE_MMU_FAULT` with status `0xa100000000000009`, request status `0x8200`.
2. `RGXFW_SF_MAIN_HWR_HIT_LOCKUP` (`GPU-0 has locked up`).
3. `RGXFW_SF_HWR_START_HW_RESET`; eight failed `RGXFW_SF_HWR_FAILED_HW_POLL` events and associated TEXAS/BIF poll-detail events; `RGXFW_SF_HWR_RESET_HW`; `RGXFW_SF_HWR_FINISH_HW_RESET`; DM1-DM5 `RGXFW_SF_HWR_DM_RECOVERED`.
4. Only then `KCCB Slot 0 Cmd=0x2abc006f` (HEALTH), and slot 1 `Cmd=0x2abc00ce` (STATEFLAGS) plus `Return value 1`.

Agent 1's [COREMEM-INIT.md](COREMEM-INIT.md) verifies the status decode as META DMA read at address zero and supplies the required `SYSINIT+0x150 = 0xE1C013C000` correction. That diagnosis remains a hypothesis until the fixed physical boot has no init fault. A final `hwr=0x1` and zero REE MMU registers after recovery do not erase the earlier trace.

At boot the FWCCB already held one unacknowledged 112-byte `DEBUG_DUMP` (`type=0x2abc006a`, zero payload). It remained pending throughout gpu2. This is consistent with the init failure and is a failure of clean S1, not a message to acknowledge blindly.

The TA's `24.2 expected / 26.1 found` message has a stock-side 26.1 workaround. `process_st_info() failed (278)` remains unresolved. Neither line is a health proof or, by itself, proof of the init-fault cause (`reader.txt:479-480`; `M2.md` §2).

## 2. Prior art: transferable structure, not Tensor constants

- **Asahi AGX:** [`fw/channels.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/fw/channels.rs) uses acquire/release ordering around shared ring read/write pointers. [`gpu.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/gpu.rs) publishes complete persistent init data, rings a doorbell only after publication, fails outstanding work on faults/crash, and performs explicit recovery. **Lesson:** memory ordering, persistent ownership, per-event error propagation, and a crashed/not-ready state are fundamental. AGX RTKit endpoints, messages, work queues, and values are unrelated to PowerVR KCCB/FWCCB and must not be transplanted.
- **Mainline Imagination PowerVR:** [`pvr_ccb.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_ccb.c) reserves one empty CCB slot, clears a waited return slot before publication, kicks MTS after the write-index barrier, and drains FWCCB by copying an entry and advancing the wrapped read index. [`pvr_power.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_power.c) serializes reset, freezes queues, uses bounded idle/off requests, falls back to hard reset, and marks the device lost after failed recovery. [`pvr_fw.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/imagination/pvr_fw.c) reinitializes persistent firmware objects on hard reset. **Lesson:** use a global recovery lock, bounded waits, reinitialized shared state, and no success after a stale completion. Its supported cores, default KCCB size, loader, and firmware ABI are not this Tensor implementation.
- **Matched Tensor PowerVR DDK:** [`rgxfwutils.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c), [`rgxkicksync.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxkicksync.c), and [`pixel/gpu_secure.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pixel/gpu_secure.c) are the authoritative behavior reference for this document. **Lesson:** native stock waits for STATEFLAGS' return slot, not HEALTH's; KICK completion is client work/UFO progress, not KCCB consumption; REQUEST_GPU_RESTART is a host power-cycle request. All numeric values below were checked against this exact pin, not inferred from the other prior art.
- **User-supplied [`dgigantino/ios-tegu`](https://github.com/dgigantino/ios-tegu) ZIP snapshot** (ZIP identity `ee8de4c00b369bbe6f21beb754a85e286b11227d`; public URL was 404, so only the attached snapshot was reviewed): this is Pixel 9a Arm `r54p3` CSF, not PowerVR. `xnu/patches/0109...persistent-queue` retries torn 64-bit producer/consumer reads and bounds them; `0111...ordered-stop` terminates the queue before firmware stop; `0151...queue-failure-diagnostics` takes a bounded pre-reset fault snapshot and quarantines uncertain resources. **Lesson:** use stable counter snapshots, pre-reset evidence, ordered queue teardown, and no memory reuse after uncertain completion. Its CSF queue, fault registers, doorbells, firmware, and reset values do not apply to KCCB/FWCCB/HWR and were not imported.
- **User-supplied `ios-tegu-ios26-bringup` ZIP snapshot** (identity `8e2d75bb19068be7cd157da46c13b2a4cf9ac689`): also Pixel 9a Mali/G715-class Valhall CSF, with persistent per-process GPU VM and native iOS/Metal work. It supplies useful production VM/submission/lifetime context but no PowerVR KCCB/FWCCB/Trusty ABI. **Lesson:** retain the mature architectural separation of persistent VM ownership and explicit completion; do not transfer its CSF firmware boot, MMU, command, or recovery values.

## 3. Boot and normal stop design

### 3.1 Load through Trusty and establish clean firmware

1. Keep one Trusty client per boot and `cpus=1` for experimental rungs. Validate the exact signed image: ABI 41, BVNC 71.2.2448.1212, DDK 26.1, and the pinned section sizes. Do not modify firmware bytes.
2. Connect to `com.android.trusty.pixel_gpu`, install the shared TA log, and send `SEND_FIRMWARE_IMAGE` exactly once. Require an 8-byte reply `{command=1,result=0}`. The TA retains the image; a second SEND in the same boot is refused, so a later firmware restart uses START again, not SEND again.
3. Build and retain all OSINIT/SYSINIT/KCCB/FWCCB/return/fault/trace/runtime objects in the uncached shared heap. Use 32-bit uncached firmware pointers for shared structures and raw device/DMA addresses only where the ABI requires them. Agent 1 writes the coremem raw DMA address before the final barrier; the Trusty request has section PA/FWVA descriptors, not the SYSINIT pointer. There is no evidence that the TA should rewrite SYSINIT.
4. Power the domain/core and issue SMC `0xC300000C`, subfunction START=1. Require result zero and `bFirmwareStarted=1` within the bounded start wait. `conn fw=0, os=1` is not a native-mode failure; stock's native `KM_GET_FW_CONNECTION` is constant ACTIVE.
5. **Before HEALTH**, snapshot FWCCB, HWR state/counters, fault/assert fields, and the trace from index zero. Require valid complete decode and zero MMU fault, lockup, failed poll, HWR reset, DEBUG_DUMP, firmware fault, and assert. A recovered trace is a STOP, even if later health would pass. Invalid/truncated trace is not a zero-count pass.
6. Post HEALTH (`0x2abc006f`) without waiting for a return slot; require consumption and its MTS decode/admission trace. Then post no-op STATEFLAGS (`0x2abc00ce`) with a waited, pre-zeroed return slot; require `CMD_EXECUTED` and no error flags. Recheck the entire trace and FWCCB. Only then enter `FW_HEALTHY`; enable the real FWCCB dispatcher before entering `FW_UP`.
7. Keep APM at the experimental 60 s until forced-idle/off handling exists. Do not enable sleep/DVFS on the current lifecycle. Polling is valid for bring-up; the unresolved GIC route must not be invented. Agent 5's [FENCE-UFO.md](FENCE-UFO.md) now supplies the later Tensor-specific OS0/INTID 162 design: dedicated OS0 status/clear `+0xbd0/+0xbe0` (mask `0x3`), OSDATA interrupt count `+0x230`, and strict UFO reaping after the real external-GIC/IOKit route exists. The IRQ counter remains only a wake hint.

The first boot after coremem must stop here with a distinct **S1 PASS**, as agent 1 specifies. S2-S4 client streams are a later image.

### 3.2 Normal stop

For a persistent driver, STOPPING first rejects new work and prevents new KCCB publication. Complete or fail all client work, drain FWCCB, and retain memory until firmware DMA is quiescent. If firmware is responsive, send KCCB POW (`0x2abc00c8`) with forced-idle/off as appropriate, wait for its execution/power synchronization, and require `ePowState=RGXFWIF_POW_OFF`. Then issue the same SMC with STOP=2, require result zero, and only then gate the core and remove the CPM domain vote. Clear the readiness lease before stopping. A timeout is not DMA quiescence and does not authorize freeing shared objects.

The current rung code implements none of this normal STOP path; its deliberate panic/reset remains the experimental teardown. Do not claim otherwise.

## 4. Exact KCCB producer and acknowledgement rules

### 4.1 Ring invariants

The pinned layout is 1024 KCCB entries (`GF_KCCB_LOG2=10`), each `0x70` bytes, plus 1024 32-bit return slots. Control fields are write offset `+0`, read offset `+4`, wrap mask `+8 = 0x3ff`. FWCCB has 32 entries of `0x70` bytes and wrap mask `0x1f`.

KCCB is host-producer/firmware-consumer. One slot stays empty: `next=(write+1)&0x3ff`; `next==read` means full. Serialize all producers with one KCCB lock, also held against power/recovery transitions. Lock order is global recovery/power → KCCB/client submission; the separate FWCCB lock is never held across a handler that can take those locks. The M3 helper's explicit `slot`, `W==R==slot`, and `slot+1` checks are valid only for a fresh experimental ring; production code must wrap and must not assume an empty ring after every command.

For each command:

1. Sample firmware read and host-local write; reserve the old write slot if `(write+1)&mask != read`. For the simple bring-up producer, allow only one KCCB command awaiting consumption at a time. Waited commands additionally retain their return slot until the return is observed, preventing reuse.
2. If the caller will wait, write `rtn[slot]=0` before publishing the command. This is mandatory for STATEFLAGS and any waited POW/cleanup/MMU command. Stock KICK and HEALTH pass no return-slot pointer.
3. Zero/fill the complete command and exact payload. Type is at `+0`, flags `+4`, data `+8`. Fixed `KICK_DATA` is `0x1c` bytes through cleanup count: context FW pointer `+0`, client CCB write offset `+4`, wrap mask `+8`, cleanup count `+0xc` (zero for KickSync). The meaningful KICK encoding in the `0x70` slot extends through `0x24`, including three zero cleanup pointers at `+0x10/+0x14/+0x18` relative to KICK data (`+0x18/+0x1c/+0x20` relative to the slot), as [CCB-KICK.md](CCB-KICK.md) §3.5 specifies.
4. Publish payload with the required write memory barrier, then publish the wrapped write index with another barrier, then write 32-bit GP value zero to RGX `+0xb00` (`RGX_CR_MTS_SCHEDULE`). The MTS write is a notification, never an acknowledgement. Uncached device mappings avoid cache maintenance but do not remove ordering requirements.
5. Wait bounded for consumption and, when requested, execution. Every wait also polls FWCCB/fault/recovery state so an HWR cannot leave a waiter spinning until it sees a stale or reused answer.

### 4.2 Three different acknowledgements

| Evidence | Meaning | What it does **not** mean |
|---|---|---|
| KCCB read index reaches/passes the command's next index | Firmware consumed the command | It executed or completed client work |
| `rtn[slot] & 1` (`CMD_EXECUTED`) | Firmware executed that KCCB command | A KICK's client stream or GPU engine job completed |
| Client CCB progress plus firmware-written UFO UPDATE / actual engine completion | Submitted client work reached the named operation | A later operation, correct pixels, or Metal readiness |

Return bits are `CMD_EXECUTED=0x1`, `CLEANUP_BUSY=0x2`, `POLL_FAILURE=0x4`. Accept success only with bit 0 set and no applicable error/unknown bits. In particular, a POLL_FAILURE with EXECUTED is not clean success. HEALTH has no stock return wait; its evidence is read movement plus `RGXFW_SF_MTS_KCCBCMD_EXEC` decode/admission, not a claimed return. STATEFLAGS must have return `0x1`. Stock KickSync does not wait on a KCCB return; KCCB decode plus client-CCB drain and UFO UPDATE is required.

Useful pinned command values (the same magic namespace is direction-specific):

| Command | Value | Purpose |
|---|---:|---|
| KCCB KICK | `0x2abc0065` | Publish a context's client-CCB write/wrap update |
| KCCB MMUCACHE | `0x2abc0066` | Later real-VM cache publication, not needed for empty KickSync |
| KCCB HEALTH_CHECK | `0x2abc006f` | Consumption/decode liveness only |
| KCCB POW | `0x2abc00c8` | Idle/off lifecycle |
| KCCB STATEFLAGS_CTRL | `0x2abc00ce` | No-op execution oracle in M2 |
| Client CCB NULL | `0x2abc80d2` | Empty DM body for KickSync |
| Client CCB FENCE | `0x2abc00d4` | Wait for UFO value |
| Client CCB UPDATE | `0x2abc00d5` | Firmware writes UFO value |

Client CCB headers are 16 bytes; `ui32CmdSize` excludes the header, total commands are 8-byte aligned, and job references correlate the stream. Publish the whole FENCE + NULL + UPDATE stream with barriers before constructing the KICK. Advance a host-local client write offset and carry its final value in `KICK.ui32CWoffUpdate`; normal stock submission does **not** store it to shared `CCCB_CTL.ui32WriteOffset`. Agent 4 owns those encodings and context pointers; agent 5 owns UFO lifetime and fence semantics. The host writes only the initial sentinel, never the expected completion values.

## 5. FWCCB dispatcher: mandatory before client work

FWCCB is firmware-producer/host-consumer. Leaving entries unacknowledged can fill all 32 slots and stall firmware (`RGXFW_SF_MAIN_WAITING_FOR_FWCCB`). Therefore the read-only M2 capture is diagnostic-only, not a persistent runtime design.

Use one dispatcher under a lock, invoked before submission, inside every bounded wait, and by the later real IRQ route:

1. Acquire-read the firmware write index and validate both indices `<=0x1f`. While read != write, copy the entire `0x70`-byte entry into host-owned memory before any callback or reset.
2. Publish `read=(read+1)&0x1f` with release ordering, freeing the slot. Dispatch the copied entry outside the FWCCB lock. This follows mainline's restart-safe structure and avoids holding the ring lock across a power cycle. Advancing read means the host accepted a copied notification, **not** that a requested operation succeeded.
3. Never write firmware entries or its write index. Preserve raw payloads and sequence numbers in the receipt.

Required actions:

| FWCCB type | Value | Runtime action |
|---|---:|---|
| CONTEXT_RESET_NOTIFICATION | `0x2abc0069` | Record context ID, reset reason, DM, reset job ref, PF/ALL_CTXS flags, PC/MMU status. Freeze affected submissions and enter context-HWR recovery; never treat it as normal completion. |
| DEBUG_DUMP | `0x2abc006a` | Capture bounded diagnostics, then consume. At clean boot it is an S1 failure. During runtime it is an error signal requiring cause correlation, not harmless noise. |
| UPDATE_STATS | `0x2abc006b` | Validate/account the copied update; never infer job completion from it. |
| REQUEST_GPU_RESTART | `0x2abc006d` | Freeze all submissions and enter full firmware restart (§7). |
| CONTEXT_FW_PF_NOTIFICATION | `0x2abc0070` | Record firmware fault VA and enter full restart; no client retry. |
| FREELIST_GROW / FREELISTS_RECONSTRUCTION | `0x2abc0067` / `0x2abc0068` | Real rendering requires the corresponding host memory operation and KCCB completion update. Until implemented, freeze and recover; never silently skip and continue. Agent 4/5 integration owns resource completion. |
| ZSBUFFER backing/unbacking | `0x2abc0065` / `0x2abc0066` | Same rule: implement before enabling the feature, otherwise terminal for the current epoch. |
| CORE_CLK_RATE_CHANGE | `0x2abc006c` | Do not enable until DVFS policy exists; treat unexpected input as unsupported, not permission to guess a clock. |

Unknown magic/type, malformed indices, or an overlarge count invalidates the epoch. Do not acknowledge-and-continue as though nothing happened.

## 6. Firmware trace: exact IDs and decoding rules

### 6.1 IDs that prove or disprove each stage

The IDs below are measured from the pinned `rgx_fwif_sf.h`; parameter count is encoded at bits 16+. They are not Linux tracepoint numbers.

| ID | Name / decoded text | Acceptance use |
|---:|---|---|
| `0x70037013` | `RGXFW_SF_MTS_KCCBCMD_EXEC`: `KCCB Slot %u: Cmd=..., Driver ID=%u` | Required decode/admission evidence for HEALTH slot 0, STATEFLAGS slot 1, later KICK slots 2/3. Offline firmware analysis shows it is emitted **before** the command-type switch; it is not execution/completion proof ([CCB-KICK.md](CCB-KICK.md) §1.2). |
| `0x70027011` | `RGXFW_SF_MTS_KCCBCMD_RTN_VALUE`: `KCCB Slot %u: Return value %u` | STATEFLAGS return 1; correlate other waited commands |
| `0x7003100e` | `RGXFW_SF_MAIN_CCCB_WOFF_UPDATE`: client CCB write-offset update, DM, firmware context | Require 64 then 128 for the two canonical KickSync streams |
| `0x70021010` | `RGXFW_SF_MAIN_UFO_CHECK_START` | Correlate fence checks to context and command offset |
| `0x70031011` | `RGXFW_SF_MAIN_UFO_CHECK` | Fence evaluated with actual address/current/required values |
| `0x70001012` | `RGXFW_SF_MAIN_UFO_CHECK_SUCCEEDED` | Fence passed, not UPDATE completion by itself |
| `0x7000103f` | `RGXFW_SF_MAIN_UFO_CHECK_FAILED` | Fail the stream |
| `0x70021053` | `RGXFW_SF_MAIN_NULLCMD`: `Kick Null cmd: FWCtx ... @ offset` | NULL parser/body evidence; not a GPU engine job |
| `0x70021016` | `RGXFW_SF_MAIN_UFO_UPDATE_START` | Update sequence began |
| `0x70021017` | `RGXFW_SF_MAIN_UFO_UPDATE`: `[addr] = value` | Independent firmware proof of UPDATE; host UFO read must agree |
| `0x7004b052` | `RGXFW_SF_HWR_CORE_MMU_FAULT` | Fatal for clean S1 and current submission epoch |
| `0x700110c5` | `RGXFW_SF_MAIN_HWR_HIT_LOCKUP` | Lockup/HWR trigger |
| `0x7003b00d` | `RGXFW_SF_HWR_FAILED_HW_POLL` | Failed hardware poll; never ignore because recovery later works |
| `0x7001b03d` | `RGXFW_SF_HWR_START_HW_RESET` | Internal HWR began |
| `0x7004b053` | `RGXFW_SF_HWR_RESET_HW` | Hardware reset attempt and poll-failure summary |
| `0x7001b03e` | `RGXFW_SF_HWR_FINISH_HW_RESET` | Hardware reset finished, not yet full health |
| `0x7001b019` | `RGXFW_SF_HWR_DM_RECOVERED` | Named DM recovered; health still required before resume |

Also record HWR state bits, not just the trace: `HARDWARE_OK=0x1`, `RESET_IN_PROGRESS=0x2`, `GENERAL_LOCKUP=0x8`, `DM_RUNNING_OK=0x10`, `DM_STALLING=0x20`, `FW_FAULT=0x40`, `RESTART_REQUESTED=0x80`. gpu2's boot `0xa` was reset-in-progress + general-lockup; later `0x1` was post-recovery OK. DM_STALLING alone starts a bounded investigation; reset/lockup/FW-fault/restart bits or a reset FWCCB enters recovery immediately.

### 6.2 Decoder acceptance rules

`research/ios26-gpu-r1/m2/tools/fwlog_decode.py` correctly interprets records as ID, timestamp high/low, then the ID's parameter count, and derives IDs/formats from the pinned header at runtime. Keep raw `M2 TB` lines as the lossless receipt.

For acceptance tooling:

- Decode exactly one current-boot `M2 fwlog ...` through its first `M2 fwlog: end`. The attempt contains mirrored duplicate console blocks; decoding all of them produced 960 words for a 476-word trace and duplicates every event.
- Preserve `ptr`, `wrap`, start, and count. Clean-init proof requires the early trace before it can wrap; a 4096-word print cap cannot prove init after the 12000-word buffer has wrapped.
- Add a strict sequential parser mode. The current decoder scans forward for any recognized ID, which is useful for damaged logs but can resynchronize inside payload. A strict acceptance pass must reject malformed/truncated records and report unknown gaps rather than silently converting them to zero failures.
- Snapshot the live ring with barriers and stable ptr/wrap validation. Never clear the trace to make a later health check look clean. Compare monotonically increasing event positions and HWR counters across the boot.
- REE MMU registers, `fw_faults`, assert text, and HWR flags are independent supporting evidence. They do not replace pre-health and final decoded traces.

## 7. HWR and lockup recovery

There are two different paths. Confusing them either powers the GPU unnecessarily or resumes after a firmware fault with stale state.

### 7.1 Firmware-managed context/hardware lockup

Trigger on CONTEXT_RESET, reset/lockup HWR flags, a new lockup/MMU trace event, or a submission that stops progressing past its bounded deadline. The firmware normally performs the hardware reset and DM recovery itself; the host must **not** simultaneously gate power or issue SMC START.

1. Under one global recovery lock, atomically change `FW_UP -> RECOVERING`, increment `recovery_seq`, and reject new KCCB posts. Wake all waiters with a distinct recovery error.
2. Snapshot FWCCB/KCCB/client CCB positions, UFOs, HWR info/counters, trace, fault/assert fields, and the 18 REE registers before any optional further reset. Preserve the raw initiating notification.
3. For CONTEXT_RESET, mark the named context and reset job failed; for ALL_CTXS, fail all affected work. Conservatively fail unresolved inflight submissions rather than replaying non-idempotent commands. Agent 5 must signal error fences, not manufacture successful UFOs. Keep contexts, CCBs, mappings, UFOs, and buffers pinned until firmware DM recovery plus context cleanup establishes DMA quiescence.
4. Drain copied FWCCB entries and wait bounded for reset finish/DM recovery and a stable non-reset HWR state. Do not send more client KICKs during this wait. Failed HW polls, a new MMU fault, no recovery before the deadline, FW_FAULT, or REQUEST_GPU_RESTART escalates to full restart.
5. After quiescence, tear down/recreate affected common contexts and client CCB state. Do not rewind a live CCB or reuse an old write offset as if no reset occurred. Establish fresh host/fence sequence state; completed pre-fault operations remain distinguishable by job refs and recovery sequence.
6. Reprove the control path with HEALTH consumption and no-op STATEFLAGS `return=0x1`, empty assert, zero firmware faults, no new HWR/FWCCB error, and valid trace. Only then change back to `FW_UP` and accept **new** submissions. Log the recovery generation so agent 10 can withdraw/reacquire readiness.

Use one recovery attempt per incident and escalate repeated lockups (for example two inside a short diagnostic window) to full restart rather than creating an endless HWR/health loop. The threshold is policy, not a firmware constant.

### 7.2 Host-driven full firmware restart

REQUEST_GPU_RESTART, CONTEXT_FW_PF, FW_FAULT/RESTART_REQUESTED, stalled KCCB, or failed context-HWR recovery requires a full restart.

1. Freeze submissions, increment `fw_epoch`, withdraw accelerator readiness, fail every unresolved job/fence, and retain all DMA resources. No old KCCB return, CCB offset, UFO, or completion may complete work in the new epoch.
2. Preserve diagnostics. If firmware is still responsive, make the bounded forced-idle/POW_OFF request; otherwise skip it after recording why. Issue secure STOP=2 and power off/gate off in the stock order. Do not wait forever on a faulted firmware to grant permission to recover. Require STOP result zero before gate/domain-off; a failed STOP enters LOST with allocations and clocks retained, not a fabricated DMA-quiescence result or forced gate-off.
3. Reinitialize every firmware-shared object from the retained initial template: zero KCCB/FWCCB/read/write/returns and reconstruct OSINIT/SYSINIT/runtime/trace, including agent 1's coremem value. Clear stale HWR/fault output state only as part of this deliberate reinitialization. Reinitialize client contexts/fences after firmware health.
4. Power on and issue START=1 using the image already installed by the earlier SEND. **Do not SEND the image a second time.** Require a completely clean boot trace and the same HEALTH + STATEFLAGS gate as initial boot.
5. Recreate VM/common contexts and agent 4/5 state, then increment/publish a new readiness generation only after their independent readiness checks pass. One failed full restart enters LOST; no automatic second restart and no unchanged phone retry.

This is deliberately stricter than stock's minimal OFF/clear-flags/ON sequence because this driver must also invalidate its own outstanding Metal/fence/resource state. It follows both stock's power-cycle intent and mainline's queue-reset/object-reinitialization structure.

## 8. Exact implementation sequence and proving logs

### Step F0 — host/model prerequisites (implementation owners)

- Reuse the generated M3 layout; add all IDs used by acceptance, including START/FINISH/RESET/DM_RECOVERED and RTN_VALUE. No hand-copied ABI from another DDK.
- Model ring wrap/full, one-slot-empty, return-slot zeroing, publication-before-doorbell, FWCCB copy/ack, malformed indices, return error bits, stale epoch, timeout, HWR during each wait, and full restart without a second SEND.
- Model firmware as the only writer of UPDATE values. Test that host success cannot be synthesized from KCCB consumption, a changed read offset, a DPU frame, or a rewritten trace.
- Keep all rung allocations through deliberate reset. For the persistent driver, release only after completion or proven DMA quiescence. Enabled-gate ARM64 object/symbol checks are required by implementation; syntax-only is insufficient.

### Step F1 — coremem-only physical S1

Use agent 1's one-variable image. Required existing lines:

```text
HK GPUTA: SEND_FIRMWARE_IMAGE len 8 cmd 0x1 result 0 ...
HK GPUTA: SMC START -> 0x0
HK GPUTA: M2 HEALTH_CHECK: slot 0 read ...
HK GPUTA: M2 STATEFLAGS_CTRL: slot 1 read ... return 0x1 ...
HK GPUTA: M2 HEALTH PASS: STATEFLAGS_CTRL executed (CMD_EXECUTED), HEALTH_CHECK consumed
```

Required new state/evidence line (values except the named zeros may vary):

```text
HK GPUTA: FWSTATE STARTED_UNVERIFIED FW_HEALTHY epoch=1 recovery=0 reason=clean-health mmu_fault=0 lockup=0 failed_poll=0 hwr_reset=0 debug_dump=0 fw_faults=0 assert_empty=1
HK GPUTA: M3 S1 PASS: clean firmware init and health; no client KICK issued
```

The decoder must independently show only normal initialization followed by slot-0 HEALTH and slot-1 STATEFLAGS/return 1, with none of the fault/HWR IDs in §6. No `M3 S4`, KICK, compute, or Metal claim.

### Step F2 — dispatcher plus first client KICK (agent 4), after F1

Bring up the FWCCB dispatcher and emit `FWSTATE FW_HEALTHY FW_UP ... reason=fwccb-dispatcher-ready` before the first KICK. For each KCCB post, emit a stable joinable sequence:

```text
HK GPUTA: FW KCCB post epoch=1 slot=2 type=0x2abc0065 ctx=0x... cwoff=0x... cwrap=0x1fff wait_rtn=0
HK GPUTA: FW KCCB read epoch=1 slot=2 next=3 elapsed_ms=...
MTS: KCCB Slot 2: Cmd=0x2abc0065, Driver ID=0
MAIN: UFO Check: [0x...] is 0xdead0000 requires 0xdead0000
MAIN: UFO Checks succeeded
MAIN: UFO Update: [0x...] = 0xc0de0001
HK GPUTA: FW CCB drain epoch=1 recovery=0 ctx=0x... w=64 r=64 d=64
HK GPUTA: FW UFO epoch=1 recovery=0 ctx=0x... value=0xc0de0001
```

Repeat for the second stream with slot 3, fence value `0xc0de0001`, and UPDATE `0xc0de0002`. Agent 4 supplies the exact client CCB offsets/job refs and S2-S4 stages; agent 5 verifies that stream 2 cannot pass before stream 1. S4 passes only with both ordered firmware UPDATEs, valid CCB progress, and no new fault/reset/debug notification. KCCB `read` or `KCCBCMD_EXEC` alone is never S4.

### Step F3 — induced/modelled recovery before relying on it

Host tests must inject context reset, ALL_CTXS, FW page fault, REQUEST_GPU_RESTART, FWCCB-full, KCCB stall, and recovery-during-wait. Required physical lines for a later deliberately induced, bounded lockup (not part of F1/F2):

```text
HK GPUTA: FWSTATE FW_UP RECOVERING epoch=1 recovery=1 reason=context-reset
HK GPUTA: FW HWR context=0x... job=0x... flags=0x... hwr=0x...
HK GPUTA: FW HWR recovered health_rtn=0x1 new_faults=0 assert_empty=1
HK GPUTA: FWSTATE RECOVERING FW_UP epoch=1 recovery=1 reason=health-reproved
```

For full restart, require `STOP -> 0x0`, exactly one SEND for the entire boot, a new `fw_epoch`, clean init/health, and explicit stale-waiter failure. No line may report recovery merely because `hwr=0x1` returned.

## 9. Coordination and risks

| Dependency / risk | Required contract / stop rule |
|---|---|
| **Agent 1: coremem/init** | F1 is coremem-only and must have zero pre-health/final HWR evidence. The TA gets section descriptors; host owns SYSINIT. Any init DEBUG_DUMP/MMU/HWR stops before KICK. |
| **Agent 3: MMU/contexts** | Follow [MMU.md](MMU.md): no separate memory-context-registration KCCB opcode exists. Keep page-catalogue DMA/PA, raw-heap device VA, and 32-bit firmware pointers distinct. Real engine work remains behind secure routing, MMUCACHE, and execution-base proof. |
| **Agent 4: CCB/KICK** | Consume this document's KCCB serialization, wrapped indices, FWCCB dispatcher, epoch gate, and three-level ack distinction. Follow [CCB-KICK.md](CCB-KICK.md) for common-context FW pointers, host-local client write/wrap values, job refs, and ordered S2-S4 evidence. No KICK before F1. |
| **Agent 5: fences/lifetimes** | Follow [FENCE-UFO.md](FENCE-UFO.md): only firmware writes UPDATEs and real output; require exact UFO plus `R=D=W`, then engine/cache readback for real work. Signal reset/timeout as errors, never success. Use per-job address+token+sequence+epoch to prevent same-word ABA. Retain UFOs/mappings/resources until completion or proven DMA quiescence; invalidate stale epochs and rebuild fence state after HWR. |
| **Agent 10: integration** | Follow [PLAN.md](PLAN.md) and [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md): publish readiness only in `FW_UP`, withdraw it on every recovery, and revalidate VM/context/engine/cache after restart. Keep S1, KickSync, compute, and Metal milestones separate. Coordinator retains sole build/phone/index control and Android return checks. |
| Trace loss or duplicate evidence | One current-boot group, strict complete decode, pre-health capture, no zero-on-invalid. Mirrored blocks are not two HWRs. |
| FWCCB starvation | Drain before and during every wait; a 32-entry pending ring can stall firmware. No permanent read-only/no-ack diagnostic in production. |
| Fault hidden by recovery | Never clear trace/counters merely to pass health. Compare event positions and HWR history, not only final `hwr=0x1` or final REE registers. |
| Timeout used as quiescence | Timeout enters recovery; it never authorizes resource free, power-off, or a successful fence. |
| Unsupported FWCCB request | Freeze/recover instead of skipping required freelist/ZS/clock work and continuing with corrupted firmware expectations. |
| TA/image lifecycle | SEND once per boot, START/STOP for power cycles. Do not change signed firmware or assume the TA rewrites shared host init. |
| IRQ/power maturity | Poll with bounded deadlines until the real GIC route exists. Keep 60 s APM until forced-idle/off is implemented; no speculative secure register pokes or DVFS. |

## 10. Live probe requested from the coordinator

After the implementation owner's host/object checks, run **one** coremem-only S1 boot exactly as agent 1 specifies, with this firmware instrumentation added only if it does not change the experiment: pre-health strict trace/FWCCB validation and the `FWSTATE ... reason=clean-health` line. Capture one current-boot decoded trace, all M2 states, the deliberate S1 panic, and Android return check.

If S1 is clean, the next separate probe should enable the FWCCB dispatcher and agent 4's two KickSync streams. Request the raw and decoded KCCB slot 2/3 decode/admission records, UFO check/update entries, CCB positions, both host UFO reads, and final fault/HWR snapshot. Do not combine coremem, a new recovery policy, and the first KICK into one unisolatable first boot.

All ten sibling documents were present at final review and are cross-linked above. Requests to other facets are implementation contracts, not claims that the corresponding physical milestone has run.
