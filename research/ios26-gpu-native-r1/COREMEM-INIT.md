# GPU firmware init: coremem `SYSINIT+0x150` correction and clean-boot proof

Date: 2026-11-04. Owner facet: firmware init / coremem only. **Read-only research:** no XNU edit, XNU build, build lock, Git staging/commit, or phone action was performed. The only repository file written is this document.

Evidence labels: **PHYSICAL** is the gpu2 phone receipt; **SOURCE** is XNU or the pinned PowerVR tree; **HOST** is a host tool run; **DESIGN** is not yet physical proof. XNU line references are nested-XNU `hk-gpu-m2-r1` commit `58f0893`, read with `mac repo --force -- git show`. The M3 file is the uncommitted candidate in `research/ios26-gpu-r1/m3/src/`.

## 0. Decision

Make the first next boot a **coremem-only S1 boot**, not a coremem-plus-client-KICK boot. Preserve every M2 value except the one 64-bit field below, keep M2 tracing and health checks enabled, and require a clean pre-health trace before allowing any later client stream.

At `gta_shared_init()` in `xnu/bsd/dev/blazer_gpu_tipc.c`, after the `SYSINIT` zero/allocation sequence and before the final publication barrier, GPU power-on, and SMC START, write:

```c
gs_w64(si + HMFV3_SI_COREMEM_DATA_STORE,
       GTA_DEVVA_HEAP + GTA_OFF_CDATA);
```

For the pinned firmware/layout this is exactly:

```text
offsetof(RGXFWIF_SYSINIT, sCorememDataStoreDeprecated) = 0x150
RGX_FIRMWARE_RAW_HEAP_BASE                            = 0x000000E1C0000000
COREMEM_DATA carve-out offset                        = 0x000000000013C000
SYSINIT+0x150 (RGXFWIF_DMA_ADDR, 8 bytes)            = 0x000000E1C013C000
little-endian words                                  = lo 0xC013C000, hi 0x000000E1
little-endian bytes                                  = 00 c0 13 c0 e1 00 00 00
```

Do **not** substitute either of the other two address forms:

| Meaning | Correct value | Where it belongs |
|---|---:|---|
| Raw GPU/META-DMA device VA | `0x000000E1C013C000` | **`SYSINIT+0x150`** |
| RISC-V cached firmware VA sent to Trusty | `0xC013C000` | `SEND_FIRMWARE_IMAGE` COREMEM_DATA `fw_va` |
| Carve-out physical address | `0xBA03C000` | `SEND_FIRMWARE_IMAGE` COREMEM_DATA `pa`; **not** SYSINIT |

The diagnosis is strong but remains a **hypothesis until S1 is physically clean**. A later HEALTH PASS after another HWR is failure, exactly as in `research/ios26-hw-investigation-r1/GPU.md` §1.4 and §3 step 1.

## 1. Verification of the offset, address, and fault

### 1.1 Layout tool reproduction — HOST

I compiled and ran `research/ios26-gpu-r1/m3/tools/fw_layout_r3.c` in a temporary directory against `/data/hackios-gpu-ref/powervr` with the include set from `measure_fw_layout_r3.sh`. I did not run the wrapper because it would rewrite receipts. The generated output was byte-identical to `m3/receipts/fw-layout-r3.h`:

```text
sha256 03627db117dc624bb98f3723f1ec3b09b04424c143ceddc589a7491ab0da6ff1
cc (GCC) 16.1.1 20260430
HMFV3_SZ_SYSINIT             0x3b8
HMFV3_SI_COREMEM_DATA_STORE  0x150
HMFV3_SZ_DMA_ADDR            0x8
HMFV3_RAW_HEAP_BASE          0xe1c0000000
HMFV3_RAW_HEAP_SIZE          0x2000000
```

This independently agrees with XNU `58f0893:bsd/dev/blazer_gpu_fwif.h`: `GF_SZ_RGXFWIF_SYSINIT=0x3b8`, timestamp at `+0x14c`, and `eFirmwarePerf` at `+0x158`. Thus the 8-byte coremem field fits exactly at `+0x150..+0x157`. The vendor struct declaration is `pvrsrvkm/include/volcanic/rgx_fwif_km.h:1740`; `RGXFWIF_DMA_ADDR` contains one aligned `IMG_DEV_VIRTADDR` (`rgx_fwif_shared.h:103-106`).

The raw base is not inferred from the fault: `rgx_heap_firmware.h:60-64` defines high=`0xE1`, low=`0xC0000000`, hence `(0xE1 << 32) | 0xC0000000 = 0xE1C0000000`. `m3/src/blazer_gpu_tipc.c:94,227-231` places COREMEM_DATA at `GTA_OFF_CDATA=0x13c000`, with real size `0x4840`, rounded Trusty mapping size `0x5000`.

### 1.2 Why stock fills the field — SOURCE

The pinned driver establishes all three links needed for this fix:

1. `volcanic/rgxinit.c:2208-2240` allocates the COREMEM_DATA region and acquires its raw device VA when the firmware section is nonempty.
2. `rgxfwutils.c:2792-2799`, inside `RGXSetupFwSysData`, calls `RGXSetMetaDMAAddress` for `sCorememDataStoreDeprecated`; `:935-949` shows that this copies the descriptor's device VA plus offset zero. The word `Deprecated` in the field name is not a reason to leave it zero.
3. `pixel/gpu_secure.c:762-802` separately derives the RISC-V firmware VA from `raw_device_va XOR raw_heap_base` and sends that with the COREMEM_DATA section. This is why `0xC013C000` is correct in the Trusty request but wrong in SYSINIT.

M2 zeroed the entire `0x3b8`-byte SYSINIT and never replaced this field (`58f0893:bsd/dev/blazer_gpu_tipc.c:325-328,349-382`). The M3 candidate already has the right two-line store at `m3/src/blazer_gpu_tipc.c:400-403`, but its enable flag is never assigned.

### 1.3 Fault decode — PHYSICAL plus SOURCE decode

Running the repository decoder against the gpu2 log confirms this sequence before either KCCB command:

```text
RGXFW_SF_HWR_MMU_FAULT_EVENT: MMU fault event: 0x00000200
RGXFW_SF_HWR_CORE_MMU_FAULT:  MMU page fault detected
                              (Core 0 MMU Status: 0xa100000000000009 0x00008200)
RGXFW_SF_MAIN_HWR_HIT_LOCKUP: GPU-0 has locked up
RGXFW_SF_HWR_START_HW_RESET:  Begin hardware reset (HWR Counter=0)
... failed HW polls ... DM recovery ...
RGXFW_SF_MTS_KCCBCMD_EXEC:    KCCB Slot 0: Cmd=0x2abc006f  # HEALTH
RGXFW_SF_MTS_KCCBCMD_EXEC:    KCCB Slot 1: Cmd=0x2abc00ce  # STATEFLAGS
RGXFW_SF_MTS_KCCBCMD_RTN_VALUE: KCCB Slot 1: Return value 1
```

Receipt: `research/laguna-usb-fix/attempts/20261103-205316-a7-ios-system-gpu2/reader.txt:345-419`, with health at `:284-319,442`. The decoder is `research/ios26-gpu-r1/m2/tools/fwlog_decode.py`, using the pinned `rgx_fwif_sf.h`.

**Decoder limitation to keep explicit:** the current Python decoder prints the raw status; it does not itself print the string `META DMA, addr 0x0`. Applying the vendor MMU decode to `0xa100000000000009` gives:

```text
requester ID = 33 -> META DMA       (volcanic/rgxdebug.c:486-487)
address      = 0x0                  (address bits 47:4)
RNW          = 1 -> read
FAULT        = 1
MMU level    = 2
```

The bitfields are `rgx_cr_defs_km.h:9018-9035`; address/requester decoding is `volcanic/rgxdebug.c:594-628`. This verifies the backlog's shortened “META DMA, addr 0x0” wording rather than pretending the Python script emitted it. Agent 3 owns any deeper MMU interpretation.

Also, the attempt files contain mirrored duplicate console blocks. The decoder reported 960 words although the trace header says 476. For acceptance, decode **one** `M2 fwlog` group (or teach the summary tool to stop at the first `M2 fwlog: end`); do not count the mirror as two faults.

## 2. Prior art: lessons, not code to transplant

- **Asahi Linux AGX init:** [`drivers/gpu/drm/asahi/initdata.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/initdata.rs) builds a zeroed nested InitData graph, fills required hardware configuration and buffer/ring pointers, and can compare the result with reference calibration blobs. [`gpu.rs`](https://github.com/AsahiLinux/linux/blob/asahi/drivers/gpu/drm/asahi/gpu.rs) boots RTKit/start endpoints and then sends the InitData GPU address; its channel and mapping objects retain the backing memory. **Lesson:** publish a complete, persistent init graph before firmware start and validate its exact address forms. AGX's RTKit messages, layouts, and values are unrelated to PowerVR and supply no coremem constant.
- **PowerVR Rogue/Volcanic host init:** the public Tensor mirror's [`rgxfwutils.c`](https://github.com/0xnullsect0r/android_kernel_google_gs-6.12_google-modules/blob/lineage-24.0/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c) shows the same stock sequencing reviewed in the pinned tree: construct OSINIT/SYSINIT and runtime data, set the coremem META-DMA address, then publish SYSINIT with a write barrier. **Lesson:** this is a required host-init field, not an MMU workaround or a post-start repair. The mirror is a navigation convenience; all offsets and values here were verified against the project's pinned 5940a317 tree, not taken from that different branch.
- **Tensor secure firmware loading:** [`pixel/gpu_secure.c`](https://github.com/0xnullsect0r/android_kernel_google_gs-6.12_google-modules/blob/lineage-24.0/powervr/pixel/gpu_secure.c) separates secure section PA/FWVA descriptors from the shared init structures. **Lesson:** Trusty accepting COREMEM_DATA does not populate the host's SYSINIT pointer. Keep the raw device VA, firmware VA, and PA distinct. Agent 2 owns the secure/HWR side; do not change firmware bytes or Trusty protocol for this fix.

## 3. Exact XNU implementation and rung wiring

### 3.1 Minimal coremem change

Implementation owner: apply the M3 delta to nested XNU `bsd/dev/blazer_gpu_tipc.c`; do not edit `blazer_gpu_fw.c`, firmware bytes, the MMU code, or `blazer_gpu.c` for S1.

In `gta_shared_init()` (`58f0893` lines 314-390; M3 lines 332-412):

1. Keep `gs_zero(si, GF_SZ_RGXFWIF_SYSINIT)` and all existing M2 allocations/writes unchanged.
2. After `ui32MarkerVal=1`, write the 64-bit value at `si+0x150` using `gs_w64`, as shown in §0. This is before `GTA_SH_CONN.OS=READY`, the final `aoc_barrier()`, `gta_power_on()`, and SMC START.
3. Add compile-time/host-checked identities: SYSINIT size `0x3b8`, field `0x150`, DMA size 8, raw base `0xE1C0000000`, coremem offset `0x13c000`, result `0xE1C013C000`, actual cdata size `0x4840`, and cdata within the raw 32 MiB heap. `gta_fw_check()` must continue to refuse any different ABI/BVNC/version/section sizes.
4. After the publication barrier and before power-on, read the two volatile words back. STOP before SMC if either differs. Emit the required pre-start line from §5. A readback proves the host published the value, not that firmware used it; the trace supplies the latter evidence.

### 3.2 Wire the existing M3 candidate without losing M2 evidence

The current candidate is not runnable as written (`GPU.md` §2.1). For S1 and the later M3 stages, the implementation must make all of these changes together:

- In `blazer_gpu_tipc_start()` (`58f0893:977-1005`), admit rungs 7/8, assign `gta_m3_coremem = (on == 7)` before thread creation, and enable diagnostics for rungs 6-8. Rung 8 is the negative control with coremem left zero; do not use it first.
- In `gta_rung4()`, call `gta_shared_init()` with tracing enabled for rungs **6-8**, not only `rung == 6`; dispatch rungs 6-8 through the M2 health path, not only rung 6. Otherwise rung 7 can silently lose tracing or produce a vacuous PASS.
- For the **S1 image**, stop after clean health and issue no client KICK. Set `gta_m2_defer_tail` only when a real later stage will dump the trace/survey; S1 must always dump them. Later S2-S4 may defer the tail as M3 intended.
- Add an S1 trace checker before the first HEALTH command and again after STATEFLAGS. Count at least `CORE_MMU_FAULT (0x7004b052)`, `HIT_LOCKUP (0x700110c5)`, `FAILED_HW_POLL (0x7003b00d)`, and `START_HW_RESET` (add its measured ID to the layout tool). Check FWCCB DEBUG_DUMP separately. Any nonzero count stops the boot before further commands; do not rely on eventual recovery.
- Reserve the existing `rung 7 PASS` / S4 wording for the later ordered client streams. S1 gets a distinct `M3 S1 PASS` result so clean init cannot be reported as command-stream, compute, or Metal success.

### 3.3 Required host validation before any phone boot

M3's `tests/` is empty. Add byte-level tests for the field value and bytes, rung 7 versus rung 8, no write before the initial zero, write before barrier/power/SMC, wrong-layout refusal, trace retained for 6-8, no HEALTH/KICK after an init-fault signature, and no S4/PASS on timeout. Test that a mirrored log is decoded once. Re-run M2's tests/mutants and M1 survey tests. Then build enabled-gate ARM64 objects and inspect expected symbols; syntax-only success is insufficient. These are implementation steps, **not work performed for this read-only document**.

## 4. Complete pre-SMC boot-parameter contract

The safest S1 rule is: **zero the same structures as M2, then make only the nonzero writes listed here, with `SYSINIT+0x150` as the sole new value.** Any field not listed remains zero before START. Do not bundle speculative OPP, register-config, signature, BVNC, timer-array, fabric, or SLC changes into this boot.

### 4.1 Fixed config heap and allocation map

`GF_CONFIG_HEAP_OFF=0x1fd0000`, granularity `0x10000`, main heap offset `0x200000`, raw size `0x2000000`:

| Object | Carve-out/raw offset | Raw device VA (where useful) |
|---|---:|---:|
| CONNECTION_CTL, size `0x10` | `0x1fd0000` | `0xE1C1FD0000` |
| OSINIT, size `0x80` | `0x1fe0000` | `0xE1C1FE0000` |
| SYSINIT, size `0x3b8` | `0x1ff0000` | `0xE1C1FF0000` |

M2's deterministic main-heap allocations, all 4 KiB aligned and zeroed, must remain:

| Object | Raw offset | 32-bit uncached FW pointer |
|---|---:|---:|
| HWR info `0x9a0` | `0x200000` | `0x40200000` |
| KCCB ctl `0x10` | `0x201000` | `0x40201000` |
| KCCB `1024 * 0x70` | `0x202000` | `0x40202000` |
| KCCB returns `1024 * 4` | `0x21e000` | `0x4021e000` |
| FWCCB ctl `0x10` | `0x21f000` | `0x4021f000` |
| FWCCB `32 * 0x70` | `0x220000` | `0x40220000` |
| FW OS data `0x448` | `0x221000` | `0x40221000` |
| GPU util `0x2810` | `0x222000` | `0x40222000` |
| HWPerf runtime cfg `0x18` | `0x225000` | `0x40225000` |
| HWPerf data `0x28` | `0x226000` | `0x40226000` |
| HWPerf ctl `0x10` | `0x227000` | `0x40227000` |
| Fault page `0x1000` | `0x228000` | `0x40228000` |
| Trace ctl `0x1b8` | `0x229000` | `0x40229000` |
| Trace data `12000 * 4 = 0xbb80` | `0x22a000` | `0x4022a000` |
| FW system data `0xf30` | `0x236000` | `0x40236000` |
| Alignment data `0x278` | `0x237000` | `0x40237000` |
| Runtime cfg `0x98` | `0x238000` | `0x40238000` |
| **End** | **`0x239000`** | below config heap `0x1fd0000` |

This map agrees with gpu2's decoded CCB pointers and `shared data written: main heap to +0x239000`.

### 4.2 CONNECTION_CTL and OSINIT before START

CONNECTION_CTL is zero except `OS=READY` at `+0x4` value 1; firmware initially sees `FW=0` at `+0x0`. Native stock does not require an OS-online KCCB command (`M2.md` §2).

OSINIT is zero except:

| Offset | Field | Value |
|---:|---|---:|
| `+0x00` | `psKernelCCBCtl` | `0x40201000` |
| `+0x04` | `psKernelCCB` | `0x40202000` |
| `+0x08` | `psKernelCCBRtnSlots` | `0x4021e000` |
| `+0x0c` | `psFirmwareCCBCtl` | `0x4021f000` |
| `+0x10` | `psFirmwareCCB` | `0x40220000` |
| `+0x1c` | `sRGXFWIfHWRInfoBufCtl` | `0x40200000` |
| `+0x20` | `ui32HWRDebugDumpLimit` | `1` |
| `+0x24` | `sFwOsData` | `0x40221000` |
| `+0x70` | `sHwPerfData` | `0x40226000` |
| `+0x74` | `sHwPerfRuntimeCfg` | `0x40225000` |
| `+0x78` | `sGpuUtilFWCtl` | `0x40222000` |
| `+0x7c` | `sHWPerfCtl` | `0x40227000` |

Work-estimation pointers (`+0x14/+0x18`) and the native-unused compatibility block remain zero. KCCB ctl starts `W=R=0`, wrap mask `0x3ff`; FWCCB ctl starts `W=R=0`, wrap mask `0x1f`; all commands and return slots start zero.

### 4.3 SYSINIT: every nonzero host-written field

| Offset | Field | Pre-START value |
|---:|---|---:|
| `+0x00` | `sFaultPhysAddr` | `0x00000000BA128000` (`0xB9F00000 + 0x228000`) |
| `+0x08` | `sPDSExecBase` | `0x000000DA00000000` |
| `+0x10` | `sUSCExecBase` | `0x000000E000000000` |
| `+0x18` | `sFBCDCStateTableBase` | `0x000000EC00000000` |
| `+0x20` | `sFBCDCLargeStateTableBase` | `0x000000EC40000000` |
| `+0x28` | `sTextureHeapBase` | `0x000000F000000000` |
| `+0x30` | `sPDSIndirectHeapBase` | `0x000000ED00000000` |
| `+0x98` | `sRuntimeCfg` | `0x40238000` |
| `+0x9c` | `sTraceBufCtl` | `0x40229000` |
| `+0xa0` | `sFwSysData` | `0x40236000` |
| `+0xb0` | `sAlignChecks` | `0x40237000` |
| `+0xb4` | initial core clock | `0x11E1A300` = 300,000,000 Hz |
| `+0xb8` | initial SoC clock | `0x0249F000` = 38,400,000 Hz |
| `+0xbc` | initial APM latency | `0x0000EA60` = 60,000 ms |
| `+0x148` | `ui32MarkerVal` | `1` |
| **`+0x150`** | **`sCorememDataStoreDeprecated`** | **`0x000000E1C013C000`** |

Everything else is zero before START, including `sRegCfg (+0xa4)`, `bFirmwareStarted (+0xc0)`, timestamp `(+0x14c)`, and `eFirmwarePerf (+0x158)`. Firmware later writes output fields; do not mistake those for host inputs.

The pointees must also match M2:

- Fault page: all `0xdeadbeef` words.
- FW system data (`0xf30`) and FW OS data (`0x448`): zero.
- Trace ctl: log type `0xc62f` at `+0x0`, trace pointer/wrap zero at `+0x8/+0xc`, thread-0 buffer `0x4022a000` at `+0x10`, **size 12000 (`0x2ee0`) at `+0x1b0`, flags zero at `+0x1b4`**, assert buffers zero. (The latter two offsets follow `hmfw_m2_layout.h:36-37`.)
- Runtime cfg (`0x98`): APM=60000 at `+0x0`; persistent=1 at `+0x8`; core=300000000 at `+0xc`; SoC=38400000 at `+0x10`; power-unit mask=3 at `+0x14`; RAC mask=3 at `+0x18`; HCS deadline=`0xffffffff` at `+0x20`; watchdog=2000000 (`0x1e8480`) at `+0x24`. Other fields remain zero, preserving M2's deliberate long APM interval and lack of power-off handling.
- Alignment data: first word 28, followed by the generated `GF_ALIGN_KM` words, remaining bytes zero. Use the generated array, not a hand-maintained layout copy:

```text
0x3b8,0x0,0x10,0x50,0x9c,0xa0,0x80,0x0,0x4,0xc,0x10,0x24,0x28,0x3c0,
0x0,0x1e0,0x1e0,0x0,0x1e0,0x0,0x1e0,0x68,0x58,0x4,0xc,0x0,0x4,0x8
```

### 4.4 Trusty firmware-section parameters relevant to the pointer

Keep `gta_fw_check()` and SEND unchanged. The request uses TF-A=1, host page shift 12, and these existing rows:

| Section | Carve-out PA | Firmware VA in request | Size sent |
|---|---:|---:|---:|
| image body | `0xB9F3C000` | 0 | `0x53000` |
| image header | `0xB9F90000` | 0 | `0x1000` |
| CODE | `0xB9F00000` | 0 | `0x30000` |
| DATA | `0xBA030000` | 0 | `0xa000` |
| RODATA | `0xBA0E0000` | 0 | `0x3000` |
| COREMEM_CODE | `0xB9F30000` | `0xC0030000` | `0xc000` |
| **COREMEM_DATA** | **`0xBA03C000`** | **`0xC013C000`** | real `0x4840`, sent rounded **`0x5000`** |

Required order: validate firmware → SEND succeeds → construct/zero all shared data and write `SYSINIT+0x150` → publication barrier and coremem readback → CPM/core power on → SMC START → wait `bFirmwareStarted` → **S1 clean-trace gate** → M2 HEALTH consumption and STATEFLAGS execution → final clean-trace gate and register survey → deliberate S1 panic. No client stream belongs in this first proof.

## 5. Proof: required log lines and acceptance

### 5.1 New exact evidence lines

Add lines with these stable field names (timings/pointer values may vary only where shown):

```text
HK GPUTA: M3 COREMEM: sysinit_off=0x150 raw_heap=0xe1c0000000 section_off=0x13c000 devva=0x000000e1c013c000 lo=0xc013c000 hi=0x000000e1
HK GPUTA: M3 S1 boot: mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 0 debug_dump 0 fw_faults 0 assert_empty 1
HK GPUTA: M3 S1 final: mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 0 debug_dump 0 fw_faults 0 assert_empty 1
HK GPUTA: M3 S1 PASS: clean firmware init and health; no client KICK issued
```

`M3 COREMEM` must occur before `SMC START`. `boot` counts cover the trace available before HEALTH; `final` covers the complete current trace after STATEFLAGS. A scanner must parse entries, not simply print constants. If an entry is truncated or the trace pointer/wrap is invalid, print `trace_valid 0` and FAIL, never zero.

### 5.2 Existing lines that must agree

```text
HK GPUTA: SEND_FIRMWARE_IMAGE len 8 cmd 0x1 result 0 in ... ms
HK GPUTA: shared data written: main heap to +0x239000
HK GPUTA: SMC START -> 0x0
HK GPUTA: M2 boot: started 1 ...; kccb w 0 r 0 ...; fwccb w 0 r 0 ...
HK GPUTA: M2 boot: sys fw_faults 0; ... hwr 0x1; ...
HK GPUTA: M2 boot: assert0 empty
HK GPUTA DIAG: boot result=0 FWCCB w=0 r=0 ... pending=0 ...
HK GPUTA: M2 HEALTH_CHECK: slot 0 read in ... ms; ...
HK GPUTA: M2 STATEFLAGS_CTRL: slot 1 read in ... ms; return 0x1 ...
HK GPUTA: M2 HEALTH PASS: STATEFLAGS_CTRL executed (CMD_EXECUTED), HEALTH_CHECK consumed
blazer-gpu: reg MMU_FAULT_STATUS_PM +0xe130 0x0000000000000000
blazer-gpu: reg MMU_FAULT_STATUS1 +0xe150 0x0000000000000000
blazer-gpu: reg MMU_FAULT_STATUS2 +0xe158 0x0000000000000000
blazer-gpu: reg MMU_FAULT_STATUS_META +0xe160 0x0000000000000000
blazer-gpu: CLOCK_RUNS ...
blazer-gpu: survey done, 18 registers
panic(...): HK GPUTA: rung 7 S1 PASS, boot ended on purpose
```

The zero REE registers are supporting evidence only: gpu2 also read zero **after** its HWR recovery. The pre-health and final trace counts are mandatory. Conversely, HEALTH consumption/STATEFLAGS return alone cannot repair a failed S1.

For independent host confirmation, run the existing decoder against one current-boot `M2 fwlog` group and the pinned header. Its output must contain no `MMU fault event`, `MMU page fault`, `locked up`, `Begin hardware reset`, `failed`, or `DEBUG_DUMP`; it must contain the slot-0 HEALTH execution and slot-1 STATEFLAGS execution/return 1. A small acceptance wrapper may print `mmu_fault 0 lockup 0`, but that wrapper must parse the decoded entries and reject malformed/truncated input.

### 5.3 S1 pass/fail gate

PASS requires every item:

1. Exact pre-start coremem line and readback; pinned firmware accepted; SEND result 0.
2. `bFirmwareStarted=1`; pre-health trace valid with all counts zero; `fw_faults=0`, `hwr=0x1`, empty assert, no pending DEBUG_DUMP.
3. HEALTH consumed, STATEFLAGS executed with return `0x1`; final counts remain zero.
4. All four MMU survey values zero, timer running, 18-register survey complete.
5. Only the deliberate S1 panic; no KICK, compute, or Metal claim; normal coordinator Android return check PASS.

STOP without an unchanged retry on any MMU/HWR/lockup/failed-poll/DEBUG_DUMP signature, a different fault address, an assert, a nonzero firmware fault, a missing/invalid trace, an unexpected panic, or a failed return check. If a new fault appears, preserve its pre-reset trace and re-triage; do not “fix” it by adding a client command or accepting recovered health.

## 6. Risks and coordination boundaries

| Risk | Mitigation / owner boundary |
|---|---|
| Writing PA or cached FWVA instead of raw DMA device VA | Use only `0xE1C013C000` at `+0x150`; log all three forms to prevent regressions. Agent 3 reviews MMU meaning. |
| Header/config skew | Reproduce `fw-layout-r3.h`, pin firmware identity and size/offset asserts, refuse mismatch. No guessed offset for another DDK. |
| Flag/wiring omission | Set `gta_m3_coremem` before thread start; enable M2 shared trace and health for 6-8. Rung 8 remains an explicit zero-field control. |
| Post-HWR health mistaken for clean init | Check the trace **before HEALTH** and again at the end. Final MMU registers and HEALTH PASS are insufficient alone. Agent 2 owns HWR analysis. |
| Two changes in the first boot | S1 is coremem + existing M2 health only. Agent 10 must keep S2-S4 client KICKs behind this physical gate. |
| Duplicate mirrored trace | Decode one group or stop at the first `M2 fwlog: end`; malformed/truncated traces are not zero-count passes. |
| Resource lifetime/reset | Retain all shared allocations through the deliberate reset. No automatic HWR retry, normal STOP, power-off, or Metal publication is added by S1. |
| Scope/acceptance inflation | Clean init is not a client command, GPU engine completion, compute, Metal, or Liquid Glass. Keep the milestones separate as in `GPU.md` and agent 10's PLAN. |

## 7. Requests to the other agents / coordinator live probe

- **Agent 2 (firmware/HWR):** cross-check the COREMEM_DATA Trusty descriptor (`PA=0xBA03C000`, FWVA=`0xC013C000`, real/sent sizes `0x4840/0x5000`) and state whether the TA can legitimately alter SYSINIT. No firmware change is proposed here.
- **Agent 3 (MMU):** independently confirm requester 33 = META DMA, address bits = 0, and the four post-run register masks. Link your MMU doc rather than duplicating the register survey design here.
- **Agent 10 (integration):** sequence one coremem-only S1 image before M3 client contexts/KICKs and preserve the S1/S4 naming distinction. This document supplies the init block; it does not duplicate the client-stream plan.
- **Coordinator's specific live probe:** after the implementation owner's host/object checks, boot **one** gpu2-recipe variant whose only functional change is `SYSINIT+0x150=0xE1C013C000` (rung 7 S1, cpus=1, M2 tracing/health unchanged). Capture the pre-start `M3 COREMEM` line, the pre-health and final decoded traces, all M2 states, FWCCB, 18-register survey, deliberate S1 panic, and Android return check. Do not issue a client KICK and do not boot rung 8 unless S1 regresses and a control is needed.

At the time of writing, no sibling documents were present in `research/ios26-gpu-native-r1/`; cross-references above name the owning facets without inventing their filenames or findings.
