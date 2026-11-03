# AoC on blazer: current implementation, missing load/start path, and safe implementation plan

2026-11-03. Read-only investigation; no kernel edit, build, lock, checkout, or phone action. XNU references are to commit `823417c` unless another revision is named. Vendor references are to the Mac's read-only `research/ios26-hwmap-r1/dl-gos-6.12` at `5940a317`. Evidence labels are **SOURCE**, **HOST**, **PHYSICAL**, and **INFERENCE**. No firmware bytes, device dumps, or serials are included.

## 1. What it does today

### 1.1 The AoC kernel client is a rung-1 transport probe, not a loader

`bsd/dev/blazer_aoc.c` is compiled by `bsd/conf/files:122` and called after the clock monitor by `bsd/kern/bsd_init.c:732-734`. It is off without `blazer_aoc=1`, additionally requires `cpus=1`, and deliberately panics after reporting a result (`blazer_aoc.c:745-777`). Its own header is explicit: no LOAD, START, carve-out, AoC register, or rail access (`blazer_aoc.c:3-11`).

The useful, already implemented pieces are:

- A terminal-error latch in `aoc_stop` (`blazer_aoc.c:113-123`) and an SMC allowlist (`:168-195`). `ea64773` later added only an `AOC_SMC_EXTRA` hook; it did not add AoC firmware operations.
- DAIF-masked SMCs, bounded handling of interrupted/FIQ/idle/busy returns, and NOP polling (`:126-143`, `:197-254`).
- FF-A 1.0/1.1 page sharing with 4 KiB descriptors over 16 KiB XNU pages, intentionally never reclaimed (`:276-334`).
- Polled virtio rings and TIPC message receive/send (`:337-491`).
- Trusty identification, FF-A RX/TX mapping, resource-table parsing, and virtio startup (`:494-676`).
- Connection to `com.android.trusty.gsa.hwmgr.aoc` (`:79`, `:679-695`) and a strict 12-byte GET_STATE request/reply (`:698-721`). The request is `{1,0}`; the accepted states are 0 inactive, 1 loaded, and 2 running.
- `aoc_rung1` currently accepts only initial state 0 (`:724-742`). It is not a reusable multi-command state machine as written: `aoc_get_state` does not clear `reply_ready` before sending, so a second request can consume the first reply again.

**HOST:** the old rung-1 record says ARM64 objects and 32 fake-transport checks passed, but the client was not linked or booted for AoC (`research/ios26-fleet/handoffs/aoc.md:7-21`). There is no physical AoC hwmgr GET_STATE receipt in that record.

### 1.2 The same transport is proven on the phone through another TA

`bsd/dev/blazer_gpu_tipc.c` at `17e7a0b` includes `blazer_aoc.c` with a different port and log prefix (`:6-15`). It therefore reuses the FF-A/virtio/TIPC implementation rather than introducing a second transport design. Only one such static client may own Trusty virtio in a boot (`:85-97`).

**PHYSICAL:** attempt `research/laguna-usb-fix/attempts/20261102-101843-native-metal-send-p29-r1` reached FF-A 1.1, mapped RX/TX, started virtio, obtained `tipc online`, connected with status 0, exchanged PING in the earlier rung, and completed `SEND_FIRMWARE_IMAGE` with result 0 (`ramdump/kernel.log:113-133,171`; `reader.txt:150-168,206`). `research/ios26-gpu-r1/PLAN.md:36-38` summarizes the later physical START and firmware-health evidence separately. This proves the transport on this phone; it does **not** prove the AoC hwmgr port, mailbox command 90, AoC LOAD, or AoC START.

### 1.3 CPM and sensor-rail machinery already exists

`blazer_cpmq_call` is the single blocking XNU entry into the CPM queue (`bsd/dev/blazer_cpmq_xnu.c:98-115`). The owner maps only the global and request/response pages (`:23-30`), serializes clients with one mutex (`:20-21,69-72`), enforces thread context (`:102-115`), and checks exact request allowlists (`bsd/dev/blazer_cpmq.c:54-81,112-129`). Queue startup and reply correlation are implemented at `blazer_cpmq.c:175-217` and the following receive path.

For the two AoC sensor supplies, the allowlist already permits GET_ENABLED, GET_VSEL, and SET_ENABLE 0/1 for LDO7S `0x3d` (1.8 V) and LDO5S `0x3b` (3.3 V), with no voltage-setting command (`blazer_cpmq.c:64-77`). `rails_on` in `blazer_sensor_hw.c:326-360` implements the stock order: read state and selectors, enable 1.8 V then 3.3 V only if off, wait 100 ms, and read both back. The expected selectors are 60 and 210 (`:40-49,330-358`). This helper is currently static and tied to the direct-sensor state machine; it is not an AoC firmware API.

The queue's LPB SET allowlist currently permits only GPU, not AoC (`blazer_cpmq.c:121-123`). The first AoC implementation therefore must not emit an AoC LPB SET and pretend it succeeded. Reuse the read-only AoC-domain gate instead; if a later boot needs an explicit ON, add exactly `{LPB_SET, 0, 1}` and never an OFF.

### 1.4 Physical idle/power facts and the direct-sensor conflict

The FDT makes the 48 MiB region `[0x8d200000, 0x90200000)` a `no-map` AoC reservation (`research/ios26-dualboot-r8/truth/fdt.dts:838-842`). The AoC node names `sswrp_aoc_pd` and `aoc_core_pd`, GSA, both sensor rails, GNSS type 2, board ID `0x70403`, and board revision `0x10000` (`:1088-1123`). Both power domains are `on-at-init`; the core is subdomain 0 of SSWRP AoC (`:31984-31999`). USB also names `aoc_core_pd` (`:30471-30484`), so cycling it is forbidden.

**PHYSICAL:** the direct-sensor boot measured domain state 2, A32 `0x10`, control word 0, both rails initially off with the expected selectors, then enabled them through the queue (`research/laguna-usb-fix/attempts/20261102-091607-sensor-stream-r2/ramdump/kernel.log:4080-4092`). It subsequently read WHO_AM_I and streamed accel/gyro (`:4113-4126,4147-4148`). This proves the AP-owned idle-AoC path, not AoC firmware execution.

Direct sensors and touch deliberately detect an AoC takeover. `sns_still_idle` stops if either sensor pad leaves GPIO or the IPC word changes (`blazer_sensor_hw.c:741-753`). `g5t_still_ours` stops if touch MISO leaves AP_SSI or the IPC word changes (`blazer_g5t.c:954-983`). `blazer_touch_ipc=0` suppresses only the IPC-word check (`blazer_touch.c:161-165`); it does not negotiate ownership. Consequently, all initial AoC load/start boots must have touch and direct sensors off.

## 2. What is missing, and the exact required sequence

No committed XNU code currently performs firmware parsing/placement, GSA mailbox command 90, boot-parameter construction, hwmgr START, or IPC liveness validation. The required order below follows `aoc.c:619-687,708-723,777-844`, `aoc_firmware.c:177-195,399-424`, and `gsa_core.c:66-78,98-144` at `5940a317`.

### 2.1 Validate and place the pinned image

Use only the already approved stock image identified by hash prefix `89cb2071` and version `16164591-polygon`. `research/ios26-aoc-r1/tools/aoc_fw_info.py` reports metadata and a hash without printing or copying firmware bytes. Its expected facts are:

- format-1 authentication header size `0x1000`;
- total file size 24,808,128 bytes, hence body size 24,804,032 bytes;
- superbin `image_size`/IPC offset `0x1c00000`;
- signed `fw_start = 0x8d200000`, `fw_size = 0x1c00000`, release type 1;
- body, UUID table, and bootloader ranges all in bounds.

Refuse any mismatch before touching hardware. Copy the body, excluding the 4 KiB header, to `0x8d200000`; its end is `0x8e9a7ac0`, below the IPC area. Do not use the non-GSA `0x41`/`0x55` reset path, and do not read the body back after GSA LOAD: GSA may lock it (`gsa_aoc.h`; `aoc.c:792-817`).

A safe header location within the existing reservation is `0x8edff000 = IPC - 0x1000`. It is above the actual body end, does not overlap IPC, and avoids putting the header in an arbitrary XNU RAM page. Copy exactly the 4 KiB authentication header there. This location is intentionally disposable after command 90.

### 2.2 Power and initial-state gate

1. Bring up the existing Trusty client and require hwmgr GET_STATE == 0. Any state 1 or 2 means a predecessor; stop without LOAD or START.
2. Require the read-only LPB AoC-domain state == 2, A32 != `0x55`, and a static IPC control area that is not already `0xA0C00A0C`. Do not read `blk_aoc` `0x9000000` or AoC SRAM before liveness.
3. Write 0 to `lcpm + 0x480 = 0x0b4c0480` to deassert `fabstby_aoc`, as in `aoc_lga.c:277-280`. Do not write `0x41` to `lcpm + 0x400`.
4. Enable the two sensor rails through `blazer_cpmq_call`, in 1.8 V then 3.3 V order, and read both back. Keep them on after LOAD/START. Restore their entry state only for a failure **before** GSA LOAD; after LOAD, stop the boot rather than risking a power-off under firmware.
5. For the first implementation, hold rather than cycle the core domain: it is `on-at-init`, XNU has no runtime-PM teardown to drop it, and USB shares it. Do not invent a new subdomain mailbox frame. This is a deliberate bounded alternative to stock's `request_aoc_on` vote (`aoc_lga.c:301-340`), not proof that a vote is unnecessary on every future boot.

### 2.3 Zero the tail and send GSA mailbox command 90

Zero `[0x8ee00000, 0x90200000)` before LOAD to remove any stale IPC tables and to initialize the heaps. Keep the 4 KiB header at `0x8edff000` and body at `0x8d200000`; publish both with a system data barrier before the mailbox request.

The FDT's GSA AP client page is `0x0e010000` (`fdt.dts:15366-15375`). The legacy GSA protocol uses 16 shared registers at page offset `0x80`, response status at `INTMSR0 + 0x30`, clear at `INTCR0 + 0x24`, mask at `INTMR0 + 0x28`, and request generation at `INTGR1 + 0x40` (`gsa_mbox_legacy.c:24-54,282-319`). Implement one bounded transaction, with bit 0 as request/response:

| Shared-register index | Value for LOAD |
| --- | --- |
| SR0, page `+0x80` | `90` (`GSA_MB_CMD_LOAD_AOC_FW_IMG`, `gsa_mbox.h:65-68`) |
| SR1, `+0x84` | `4` arguments |
| SR2/SR3 | header PA low/high: `0x8edff000`, `0` |
| SR4/SR5 | body PA low/high: `0x8d200000`, `0` |
| SR6..SR15 | zero |

Clear response bit 0, unmask it, write request bit 0 to INTGR1, and poll for a bounded response. Require response command `90 | 0x80000000 = 0x8000005a`, error 0, and a valid argument count. Clear and mask the response bit on every exit. Timeout, SError, bad response, or authentication failure is terminal: no retry, no START, no body readback. Command 91 is not a substitute for hwmgr START; the prior source review found it can acknowledge without starting the core.

After successful command 90, issue a fresh hwmgr `{1,0}` and require state 1. This requires fixing the stale-reply issue noted in §1.1.

### 2.4 Program the 28-entry boot-parameter block at IPC

Write little-endian words at `0x8ee00000`: magic `0x0a0cda7a`, entry count 28, byte length `12 + 28*12 = 0x15c`, then 28 triples `{key, 4, value}` (`aoc.c:512-526`; keys in `aoc.h:279-310`). Use these exact entries and order:

| # | Key | Value | Reason/source |
| ---: | --- | ---: | --- |
| 1 | `kAOCBoardID` `0x1001` | `0x00070403` | FDT |
| 2 | `kAOCBoardRevision` `0x1002` | `0x00010000` | FDT |
| 3 | `kAOCSRAMRepaired` `0x1003` | `0` | LGA helper returns false |
| 4 | `kAOCCarveoutAddress` `0x1005` | `0x8d200000` | reservation base |
| 5 | `kAOCCarveoutSize` `0x1006` | `0x03000000` | 48 MiB |
| 6 | `kAOCSensorDirectHeapAddress` `0x1007` | `0x9abe0000` | layout below |
| 7 | `kAOCSensorDirectHeapSize` `0x1008` | `0x00400000` | 4 MiB |
| 8 | `kAOCPlaybackHeapAddress` `0x100c` | `0x9abdc000` | layout below |
| 9 | `kAOCPlaybackHeapSize` `0x100d` | `0x00004000` | 16 KiB |
| 10 | `kAOCCaptureHeapAddress` `0x100e` | `0x9abcc000` | layout below |
| 11 | `kAOCCaptureHeapSize` `0x100f` | `0x00010000` | 64 KiB |
| 12 | `kAOCTpuOffloadHeapAddress` `0x101b` | `0x9afe0000` | layout below |
| 13 | `kAOCTpuOffloadHeapSize` `0x101c` | `0x00020000` | 128 KiB, enabled on LGA |
| 14 | `kAOCForceVNOM` `0x1009` | `0` | no DT override |
| 15 | `kAOCDisableMM` `0x100a` | `0` | default |
| 16 | `kAOCEnableUART` `0x100b` | `0` | default |
| 17 | `kAOCForceSpeakerUltrasonic` `0x1010` | `0` | default |
| 18 | `kAOCRandSeed` `0x1011` | fresh nonzero `u32` | seed, not a key or secret |
| 19 | `kAOCChipRevision` `0x1012` | `0` | no `soc_compatible` child in captured FDT |
| 20 | `kAOCChipType` `0x1013` | `0` | LGA helper |
| 21 | `kAOCGnssType` `0x1014` | `2` | FDT |
| 22 | `kAOCVolteReleaseMif` `0x1015` | `0` | default |
| 23 | `kAOCChipProductId` `0x1016` | `0` | no `soc_compatible` child |
| 24 | `kAOCWifiChip` `0x1017` | `0` | property absent |
| 25 | `kAOCBtChip` `0x1018` | `0` | property absent |
| 26 | `kAOCContexthubSharedDataHeapAddress` `0x1019` | `0` | LGA size is zero |
| 27 | `kAOCContexthubSharedDataHeapSize` `0x101a` | `0` | `aoc.h:44-49` |
| 28 | `kAOCGsaEnabled` `0x101d` | `1` | FDT `gsa-enabled` |

The heap layout is stock's backward allocation from the reservation end (`aoc.c:2893-2957`):

| Heap | AP physical range, for zeroing/mapping only | Value placed in parameter block |
| --- | --- | ---: |
| capture, 64 KiB | `0x8fdcc000..0x8fddc000` | `0x9abcc000` |
| playback, 16 KiB | `0x8fddc000..0x8fde0000` | `0x9abdc000` |
| sensor direct, 4 MiB | `0x8fde0000..0x901e0000` | `0x9abe0000` |
| TPU offload, 128 KiB | `0x901e0000..0x90200000` | `0x9afe0000` |

This is not an invented address translation. `aoc_dram_translate_to_aoc` adds the carve-out offset to `carveout_paddr_from_aoc` (`aoc.c:242-254`); the captured FDT has no such property, so stock uses its default `0x98000000` (`:3135-3144`). Do not substitute the signed code mapping's `0x08000000` VA, and do not put the AP physical heap addresses into these parameter values. ContextHub gets no allocation on LGA.

Issue a system data barrier after writing all 348 bytes.

### 2.5 START and prove liveness

Send hwmgr state command `{1,1}` over the existing TIPC connection. Require the exact 12-byte reply `{0x80000001,0,2}`. Then poll IPC word 0 for `0xA0C00A0C` for at most 10 seconds. State 2 without that magic is a failure, not success; stop without an in-boot SMMU experiment or retry.

Once magic appears, bounds-check the packed control block (`aoc_ipc_core_internal.h`): service count, service size, and services offset must remain within the reservation. The next acceptance rung should find `control`, send `CMD_SYS_VERSION_GET_ID` 6, and require a correlated response matching the pinned version. A queue write followed by a bounded response is stronger proof than magic alone. Doorbell work belongs to the AoC AP clients beginning at `0x0b4a0000` (`fdt.dts:15126-15364`), not the GSA page.

## 3. Fix path for a careful builder

Ordered implementation units, keeping hardware-free logic testable and hardware access staged:

1. **Generalize the existing hwmgr command in `bsd/dev/blazer_aoc.c`.** Add `aoc_state_cmd(uint32_t cmd, uint32_t *state)` beside `aoc_get_state` (`:698-721`). It must clear `reply_ready` and `reply_len` before `aoc_send`, wait once, require length 12, response command `1 | 0x80000000`, error 0, and state <= 2. Implement GET_STATE and START as cmd 0 and cmd 1. Do not widen the SMC allowlist; no new SMC is needed. Refuse `blazer_gpu_tipc` and every other Trusty client for the boot.
2. **Add a hardware-free parser and parameter encoder.** Suggested files: `bsd/dev/blazer_aoc_fw.h` and `blazer_aoc_fw.c`, with `aoc_fw_parse`, `aoc_fw_layout`, and `aoc_fw_encode_params`. Return header size/body size/load address/IPC offset and checked ranges. Use 64-bit overflow-checked arithmetic and emit the 28 entries in §2.4. Keep all literals tied to the pinned FDT/source facts; reject a different image rather than silently relocating it.
3. **Supply the approved local firmware without committing it.** In the builder's image packaging, expose `{const void *data, size_t size}` to the parser and record the expected hash/version in the manifest. Only AoC images should carry the approximately 24.8 MiB payload. Update `tools/image_tool.py`'s AoC allowlist for explicit stages rather than letting an ordinary boot load firmware. The existing line already permits only `blazer_aoc=1` (`tools/image_tool.py:167`).
4. **Add `bsd/dev/blazer_aoc_up.c` as the hardware sequencer.** Suggested functions: `aoc_up_map`, `aoc_up_place`, `aoc_up_rails_on`, `aoc_gsa_load90`, `aoc_up_params`, `aoc_up_wait_magic`, and `aoc_up_down`. It should own only the GSA page, LCPM page, and the existing AoC reservation. Use device mappings and barriers; if a cached mapping is used for the body/header, clean it to the point of coherency before command 90. Do not call the direct-sensor thread or `sns_down`.
5. **Implement the exact memory layout in §2.1/§2.4.** Put the header at `0x8edff000`, body at `0x8d200000`, IPC at `0x8ee00000`, and zero the tail/heaps before LOAD. Do not allocate the header with `IOMallocAligned`: normal XNU RAM is above 4 GiB in this setup, while GSA supports a 36-bit DMA address, and GSA memory protection must not unexpectedly cover an XNU-owned page. Do not read or free the body after LOAD.
6. **Implement command 90 exactly as in §2.3.** Use a timeout and terminal error latch, validate response command/error/argc, then require fresh GET_STATE == 1. There is no mailbox START in this path.
7. **Encode parameters, send hwmgr START, and poll magic.** Require state 2 and magic within 10 seconds. Stop on every other outcome. Add control-service version verification only after the magic/service-table rung passes; do not combine first START with audio routing, USF, amp control, or touch negotiation.
8. **Keep independent boot stages.** A useful progression is `blazer_aoc=1` GET_STATE only; `=2` through LOAD/state 1 then deliberate panic; `=3` through START/magic then deliberate panic; `=4` control version then deliberate panic. Each physical attempt starts from a fresh boot and must again prove initial state 0. No retry within a boot and no normal Home boot until coexistence is designed.
9. **Add host tests and ARM64 object checks before any boot.** Tests should cover all 28 entries, `0x15c` length, every heap value/range, wrong hash/header/fw_start/IPC, overflow, stale replies, state 1/2 at entry, command-90 errors, no START after LOAD failure, state 2 without magic, and proof that touch/sensor paths cannot run. With `BLAZER` explicitly enabled, emit ARM64 objects and inspect for `_blazer_aoc_start`, the parser, command-90, and parameter symbols; an empty guarded translation unit or syntax-only check is insufficient.
10. **Integrate diagnostics.** Use `HK AOC:` lines for existing continuity, and update `docs/probes.yaml:831-840`, whose current lowercase `blazer-aoc|aoc: ` marker does not match that prefix. For attempts, use `hk logs --grep 'HK AOC'`, `python3 -I tools/probe_eval.py --row aoc <attempt>`, `hk report`, and `hk find --feature aoc`. After each physical temporary boot, the coordinator should run the normal Android return check (`hk back`); bootloaders, slots, partitions, and backups remain untouched.

Touch coexistence is a separate later patch: start AoC before touch's delayed thread, obtain a correlated `AP_REQUEST_BUS` grant from `com.google.tbn_service`, only then select AP_SSI, suppress the now-valid IPC-word change, and retain the MISO-mux stop. Sensor coexistence should move to USF rather than weakening `sns_still_idle`. Neither belongs in the first loader.

## 4. Risks and stop conditions

| Risk | Why it matters | Required mitigation |
| --- | --- | --- |
| **Carve-out overlap** | `0x8d200000` is Android's own 48 MiB `no-map` AoC reservation. Relocating firmware or using XNU RAM changes signed loading assumptions and can corrupt unrelated memory. | Treat the overlap as intentional and stay inside `[0x8d200000,0x90200000)`. Use the exact body, header, IPC, and heap layout above. Never write past `0x90200000`. |
| **GSA reads/protects the header and body** | An arbitrary high XNU page is outside GSA's 36-bit DMA model and could become protected unexpectedly. Successful LOAD can make the body inaccessible. | Use the low disposable header page `0x8edff000`, pass zero high dwords, barrier before LOAD, and never read/compare/free the body afterward. No arbitrary low DRAM scratch page either. |
| **IOMMU/SMMU assumptions** | The signed table includes a `0x08000000` mapping and entries overlapping USB/TPU/IIF-related low ranges. `amb_smmu` bypass evidence is from an older phone survey; GSA's path does not call stock's AP `aoc_configure_iommu`. | First implementation performs no SMMU writes. If state 2 arrives without magic, stop and investigate separately. Do not disturb USB SID `0x8100` or GSA SID `0x8201`; do not conflate parameter heap base `0x98000000` with the signed code VA. |
| **Early MMIO reads** | Reading AoC SRAM/`blk_aoc` while reset is asserted previously caused an SError on the sibling platform. A hung secure-world call can also outlast software deadlines. | Never read `0x9000000` or SRAM before magic. Bound every mailbox/hwmgr wait, log the last completed stage, and make any SError/reset/Secure OS panic terminal. |
| **Power-domain and rail ownership** | USB shares `aoc_core_pd`; AoC firmware needs the sensor rails and DRAM through boot. Direct-sensor teardown can turn rails off. | No domain cycling and no direct-sensor teardown in AoC boots. Use only the CPM owner for rails, keep them on after LOAD, and never emit an AoC OFF frame. |
| **Touch and sensor pad takeover** | AoC firmware can legitimately change IPC and pin ownership. Current drivers interpret those changes as fatal loss of ownership. | `blazer_touch=0`, direct sensors off, and no amp/mic work in rungs 1-4. Later require TBN for touch and USF for sensors; do not merely disable their guards. |
| **Stale or duplicated secure-world state** | A previous loader, a stale TIPC reply, or two Trusty clients can make results look successful or drive the wrong state transition. | Require initial state 0, clear reply state per command, permit one Trusty client and one new variable per boot, and use a fresh temporary boot for every rung. |
| **Magic is not full firmware acceptance** | State 2 only proves hwmgr accepted START; magic alone does not prove usable services or audio. | Require both state 2 and timely magic, then bounds-check services and complete the control-version rung before downstream work. |
| **Android recovery** | A hung secure-world call or firmware fault may require a long press, even though no persistent write is intended. | Owner-attended early attempts, one attempt per diagnosis, normal power recovery, and Android return check afterward. No slot change or persistent AoC reset/unload experiment. |

The implementation boundary is therefore narrow: reuse the physically proven transport, preserve Android's AoC reservation and power ownership, add only command 90 plus hwmgr state commands, and accept nothing less than a fresh state transition and IPC liveness.
