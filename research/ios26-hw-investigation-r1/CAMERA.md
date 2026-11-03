# Cameras and flash — read-only investigation

Date: 2026-11-03. Scope: source/FDT/receipt inspection only; this investigation did not build, modify XNU, or touch the phone.
Evidence labels below are **SOURCE**, **HOST**, **ARM64**, **PHYSICAL**, and **INFERENCE**. `xnu/` means
`research/ios26-release-r1/work/xnu`; camera line references are to its `hk-cam1` branch. No firmware, device dumps, or serials are included.

## Executive finding

This lane is **not blank**. The pre-existing `hk-cam1` work already has a gated LM3644 flash driver, host tests, an ARM64 object check,
and a linked kernel (`research/ios26-camera-r1/CAMERA.md`). Its stage 3 reads the flash ID without writing a chip register; stage 4 can
pulse LED1 then LED2 at low torch current. Those newest stages have **no physical result yet**. The only physical flash probe was the older
p1 stage-1 kernel, which stopped before I2C because the loader left CLI7 in UART mode. No Tensor sensor, CSI, ISP, or iOS capture-service
driver exists in the scoped Blazer source. The backlog still assigns `probe:cameras` to CAMERA with no test run (`docs/debug/BACKLOG.md:34`).

# 1. What it does today

## 1.1 Kernel code

**SOURCE:** `xnu/bsd/dev/blazer_torch.c` and `blazer_torch_hw.c` implement a one-shot, delayed kernel-thread probe, compiled only for
BLAZER and off unless `blazer_torch=N` is present. Registration is in `xnu/bsd/conf/files:138-139`; startup calls
`blazer_torch_init()` at `xnu/bsd/kern/bsd_init.c:735-736`.

- XNU glue maps only the named MMIO pages (`blazer_torch.c:20-27`), supplies bounded read/write/SMC/delay/log operations, and takes the
  shared CPM lock (`blazer_torch.c:30-94`). `torch_thread()` runs once and prints a summary (`:97-113`);
  `blazer_torch_init()` parses `blazer_torch`, `blazer_torch_delay`, and `blazer_torch_ms` (`:116-132`).
- The hardware file's stage contract is at `blazer_torch_hw.c:1-17`:
  - **Stage 1:** read domain state, vote clocks, and inventory CLI/controller/pads; no chip traffic.
  - **Stage 2:** temporarily set CLI pad pulls and flash EN, then attempt ID/enable reads; restore everything.
  - **Stage 3:** additionally change CLI7 word 0 from the observed UART selection to I2C and mux SCL/SDA to CLI7, then read LM3644
    ID register `0x0c` and enable register `0x01`. It writes **no chip register**, although it does temporarily change pads/EN.
  - **Stage 4:** only after ID `0x02`/`0x04` and reset enable value `0x80`, pulse LED1 and LED2 separately in torch mode, then restore
    standby, saved current codes, controller, EN, pads, and CLI selection. Default is 2000 ms per LED, clamped to 500–5000 ms.
- Important implementation points: physical-address/frame/write allowlists (`blazer_torch_hw.c:154-227`), CPM/frame voting
  (`:269-378`), CLI7 selection and pad mux (`look()` at `:424`, `pad_mux()` at `:391`), EN handling (`en_raise()` at `:511`),
  DesignWare I2C setup (`bus_up()` at `:549`), bounded register read/write (`one_read()` `:600`, `one_write()` `:662`,
  `chip_write()` `:696`), the two-LED sequence (`torch()` `:722`), and unconditional restoration (`put_back()` `:803`,
  `bt_run()` `:886`).
- This follows the proven haptics structure: a gated one-shot XNU thread (`xnu/bsd/dev/blazer_haptic.c:95-126`) plus a host-testable
  hardware file. The haptics file records the physical LSIO_E vote/pad precedent (`blazer_haptic_hw.c:3-11`). Torch adds LSIO_S and
  the LM3644; it does not reuse haptics' I2C address or registers.

**HOST:** the exact hardware file passes 17/17 model cases, including UART restoration, ID reads, both LEDs, unknown ID, non-standby,
faults, NAK while lit, low lines, bad pads, and gate/refusal checks (`research/ios26-camera-r1/receipts/host-test.txt:1-236`).
The mutation receipt is cited in `research/ios26-camera-r1/CAMERA.md:77-83`.

**ARM64:** the gated hardware file produced an ARM64 Mach-O with `_bt_init`, `_bt_run`, `_torch`, `_chip_write`, and `_pad_mux`
(`research/ios26-camera-r1/receipts/arm64-object.txt:1-27`); the linked kernel also contains the expected symbols
(`research/ios26-camera-r1/receipts/kernel-verify.txt:1-17`). These are compile/host facts, not phone acceptance.

**PHYSICAL:** the older p1 probe, attempt `20261102-090454-torch-1-r1`, found LSIO_E/LSIO_S already on but CLI7 selected as UART;
it stopped with `chip answered 0`, before controller or chip access. See the bounded summary in
`research/ios26-camera-r1/CAMERA.md:11-20`. Stage 3 was written specifically to close that mux gap. There is no physical LM3644 ID,
torch, sensor-ID, or capture result today.

## 1.2 Device-tree hardware map

All nodes in this section are **SOURCE** from `research/ios26-dualboot-r8/truth/fdt.dts` (abbreviated below as `fdt.dts`).

### Sensors and companion devices

| Function | Node and bus | Register format / address | Reset, enable, clock | Power |
|---|---|---|---|---|
| Rear wide | `sensor@0`, `sensor-boitata`; `i3c-master@3bf11000` / LSIO_S CLI1 (`fdt.dts:36139-36182`, controller `:14257-14295`) | I3C-enabled, static/I2C address `0x3d`, DCR `0x82`; 16-bit address, 16-bit value | Reset LSIO_S pin 13 `AP2RCAM_RST_L`; OIS enable da9188 GPIO1; MCLK2 at 24.576 MHz | CAM_BB, PP1350, RCAM_ANA, RCAM_VDIG, vio, SLG LDO4/LDO2 |
| Front | `sensor@1`, `sensor-taotie-front`; `i2c@3a311000` / LSIO_E CLI8 (`:36184-36212`, controller `:12784-12804`) | I2C `0x1a`; 16-bit address, 8-bit value | Reset LSIO_E pin 6 `AP2FCAM_RST_L`; MCLK3 at 24.576 MHz | Common rails plus SLG LDO1/LDO8/LDO3 and vio |
| Ultra-wide | `sensor@2`, `sensor-taotie-uw`; `i2c@3a361000` / LSIO_E CLI13 (`:36214-36249`, controller `:12941-12961`) | I2C `0x1a`; 16-bit address, 8-bit value | Reset LSIO_E pin 10 `AP2RUWCAM_RST_L`; MCLK1 at 24.576 MHz | Common rails plus SLG LDO6/LDO2/GPIO4 and vio |
| Tele | `sensor@3`, `sensor-taotie-tele`; `i2c@3bf31000` / LSIO_S CLI3 (`:36251-36288`, controller `:12564-12584`) | I2C `0x33`; 16-bit address, 8-bit value | Reset LSIO_S pin 21 `AP2RTCAM_RST_L`; OIS reset pin 30; MCLK6 at 24.576 MHz | Common rails plus SLG LDO7/LDO5/LDO4/GPIO3 and vio |

The LSIO_E names/reset pins are at `fdt.dts:21502-21517`; LSIO_S MCLK/reset/flash names are at `:22730-22747`.
Actuators, OIS, and EEPROMs share the corresponding sensor bus and power sequence (`:36290-36528`). They add no independent capture
path and should remain untouched during the first sensor-ID test. The rear I3C bus also contains actuator/OIS placeholders
(`:14278-14294`), one reason not to make it the first bus.

### Flash, camera PMIC, and rails

- **Flash:** `flash@0` / `flash-lm3644` is a generic LWIS I2C-device node at `0x63`, 8-bit registers and values, on
  `i2c@3a301000` / LSIO_E CLI7 (`fdt.dts:36530-36544`; bus `:12637-12652`). Its only declared power sequence is EN high/low on
  LSIO_S pin 22 `AP2FLASH_EN`; pin 23 is `AP2FLASH_STROBE`, but the flash node does not declare a strobe property. The kernel reads
  but never drives strobe. No camera PMIC rail is declared for the LM3644.
- **Shared CLI7 power parts:** SLG51002 is at `0x75`, with CS on da9188 GPIO8 `PMICS2CAM_PMIC_EN`, eight LDOs and four GPIO rails
  (`fdt.dts:12654-12768`). RT6160 `PP3200_CAM_BB` is at `0x77`, enabled by da9188 GPIO9 (`:12770-12781`). Thus the first flash
  probe and later camera-power work share a controller but not the same power requirements.
- **Other rails:** PP1350_CAM uses da9188 GPIO15 (`:35818-35827`), PP2200_RCAM_ANA GPIO2 and PP0950_RCAM/RCAM_VDIG GPIO5
  (`:36075-36096`). `vio` is the da9188 LDO22S rail named `L22S_CAMIO` (`:16555-16559`). The da9188 GPIO controller uses CPM MBA
  destination `0x0a` and names these lines at `:16635-16644`.
- **Exact sequences:** `module_power_seq@0`, `@2`, `@3`, and `@4` are at `fdt.dts:36099-36137`. Front uses `@4`:
  `pp3200_bb → pp1350 → rcam_vana → rcam_vdig → ldo1 → ldo8 → vio → ldo3 → reset → mclk_on → vsync_on → resume`,
  with the listed delays, then the declared reverse/power-down order (`:36129-36136`). These sequences, not an abbreviated rail list,
  are the implementation contract.

### CSI / ISP inventory

The FDT describes Google **LWIS ioreg devices**, not an XNU driver:

- ISP FE and CSI PHY link: `lwis_isp_fe`, register windows `isp-fe` and `csis-phy-link`, power domains, clocks, DVFS, IOMMUs and a
  large per-context interrupt space (`fdt.dts:9742-9761`). The FE interrupt/event inventory begins around `:6503`; CSIS event entries
  begin at `:8484`.
- ISP BE: `be-btr`, `be-yuv`, `be-msa`, and `ispbe-pdma`, with their own valid ranges, IRQs and IOMMU streams
  (`:10081-10158`; parent window `:9765-9769`).
- GSW: `gsw-gwe`, `gsw-gse`, and `gsw-pdma` (`:10364-10420`), plus `flow-sync` (`:10423-10434`).
- DVFS domains `ispfe`, `ispbe`, and `gsw` are declared at `:3700-3718`.

**INFERENCE:** LWIS exposes register/I/O machinery to Android camera userspace; these nodes do not supply sensor mode tables, CSI/ISP
programming, tuning/3A, or an Apple capture ABI. The reuse audit reaches the same conclusion and warns against guessing public sensor
models from the codenames (`docs/reuse/2026-11-02/media-radios.md:154-159`). No `blazer_cam`, sensor, LWIS, or ISP implementation was
found in the scoped Blazer XNU paths.

# 2. What is missing

## 2.1 Gap to an LM3644 flash LED result

The code gap for the smallest win is already closed on `hk-cam1`; the remaining gap is **physical validation**:

1. Prove stage 3 selects CLI7 as I2C, reads a valid ID and reset/standby enable value, and restores everything.
2. Only then run stage 4 with an owner watching. Accept two separate dim pulses, clean standby, zero relevant fault flags, and clean
   restoration. This is still a kernel self-test, not an iOS flashlight/camera service.

Do not treat host LED accounting as light on the phone. If stage 3 stops on unexpected CLI/pad ownership, low lines, NAK, or a
non-reset enable value, the correct action is diagnosis—not widening the write allowlist or retrying stage 4.

## 2.2 Gap to a sensor ID read

No camera-sensor driver or `blazer-cam:` producer exists yet; the probe rows are explicitly planned (`docs/probes.yaml:981-999`).
The missing pieces, in dependency order, are:

1. **A safe second transport client.** The torch code's DesignWare engine is LM3644-specific and 8-bit-register-only. A camera client
   needs CLI8 setup plus two-byte register-address writes and one-byte data reads for the front sensor.
2. **PMIC/CPM operations.** Current `pmic_allowed()` covers touch, sensors, BT, and RTC only (`xnu/bsd/dev/blazer_cpmq.c:49-91`).
   It has no camera CS, fixed-rail GPIO, SLG51002 LDO, or camera clock operations. All requests share the single CPM queue and its lock
   (`blazer_cpmq_xnu.c:98-141`), so camera must use that owner rather than initialize a second queue.
3. **Camera PMIC identification.** SLG51002 needs CS asserted before its ID/status read. RT6160 has an enable GPIO; do not assume it
   answers while disabled. Their exact ID/status register addresses must come from matching vendor drivers/documentation, not a sweep.
4. **Front sensor power and clock.** Implement the complete `module_power_seq@4`, including SLG LDOs, LDO22S/vio, MCLK3, reset and
   delays. A controller clock alone is insufficient.
5. **The actual sensor ID location.** `taotie-front` is a codename; the FDT gives bus geometry but no chip-ID register. Recover the
   matching vendor sensor table. The common CCI locations `0x0000` and `0x0016` are only **INFERENCE** and must not be presented as
   confirmed; any bounded fallback read needs explicit approval and must remain read-only.
6. **Power-down proof.** Log the ID and then restore reset, clock, every rail, CS, pads and controller. A response without clean
   power-down is not a completed milestone.

Flash, camera PMIC ID, and sensor ID do **not** require ISP firmware. They are bus/power/reset tasks.

## 2.3 Gap to capture

A raw frame and a shipping iOS camera are separate, much larger stages:

- **Sensor streaming:** confirmed sensor mode, lane, frame-timing, gain/exposure and start/stop tables for the exact modules.
- **CSI receive:** CSI PHY/ISP-FE power/clock/reset, lane configuration, valid register sequences, IRQ handling, IOMMU/SMMU mappings,
  DMA buffer ownership, frame completion/error accounting, and a raw-frame consumer.
- **Image processing:** ISP BE/GSW/flow-sync programming, format conversion, lens/module calibration, AE/AF/AWB and tuning. The FDT
  register windows alone provide none of these.
- **Apple-facing service:** stock `cameracaptured`/camera clients need a compatible capture/ISP driver and userspace ABI. A full iOS
  pipeline therefore needs Apple-compatible ISP firmware/driver services **or a replacement capture provider**; neither exists here.
  Tensor's Google-facing LWIS path instead depends on vendor userspace register programming and tuning, so loading an unrelated ISP
  blob would not solve it. No firmware artifact is needed or proposed for the early ID/flash milestones.

# 3. Fix path — ordered and concrete

## F1: validate the existing flash driver first

1. **Coordinator, attended phone run:** use the `hk-cam1` kernel with `blazer_torch=3` first. Confirm the ID/enable line, `ends: ok`,
   and restored CLI/pads. There are no LM3644 register writes at this stage, though EN/mux changes still require the normal owner-approved
   phone-test process and Android return check.
2. **Then stage 4:** use the already-prepared cam1 recipe (`blazer_torch=4`) with the owner watching at the delayed run time. Accept only
   the two independent low-current torch pulses followed by standby and `ends: ok`; stop on faults or cleanup failure. Do not add flash
   mode, both-LED mode, software reset, higher current, or a longer unbounded hold.
3. **Debug/acceptance tools:** collect with `hk logs --grep 'blazer-torch:'`; find attempts with `hk find --feature cameras`; evaluate
   `python3 -I tools/probe_eval.py --row cameras <attempt>`. The exact success/failure regexes and owner question already live at
   `docs/probes.yaml:952-979`. Use `hk back` for the standard Android return path/check after the run. `hk report` remains the general
   attempt summary tool (`docs/debug/MAP.md:12-23`). Host reruns, if code changes later, are
   `research/ios26-camera-r1/tests/test_blazer_torch.c` and `tests/mutants.py`.

## F2: camera PMIC IDs on the already-understood CLI7 bus

4. Add a separate, default-off `blazer_cam=1` client in planned files `xnu/bsd/dev/blazer_camera.c` and
   `blazer_camera_hw.c/.h`, registered beside torch in `xnu/bsd/conf/files` and called beside `blazer_torch_init()` in
   `xnu/bsd/kern/bsd_init.c`. Keep the XNU/thread and host-testable hardware split. Reuse the bounded DesignWare sequence represented by
   `bus_up()`, `one_read()`, `read_retry()`, and `put_back()` (`blazer_torch_hw.c:549-655`, `:803-873`) without changing F1 behavior.
5. Extend **only** `pmic_allowed()` in `xnu/bsd/dev/blazer_cpmq.c:64-92` with exact da9188 GPIO direction/get/set frames for camera
   PMIC CS, called through `blazer_cpmq_call()` (`blazer_cpmq_xnu.c:109-115`). The existing encoding uses `T_GPIO`; the vendor rule
   noted for BT is `19 + FDT GPIO`, making GPIO8 candidate ID `0x1b`—**verify this against the matching da9188 source and host-test it
   before any phone use**. Save direction/value, assert CS, read only the recovered SLG51002 ID/status registers, then restore CS.
   Treat this as a state-changing test requiring owner approval, not as a read-only boot.
6. Handle RT6160 separately: recover its ID register and determine whether CAM_BB must be enabled. If enable is required, fold it into
   S1's approved rail sequence rather than silently energizing it during an “ID-only” run. Emit the planned `blazer-cam: pmic ...`
   result expected at `docs/probes.yaml:987-990` and run the host refusal/restoration tests plus an ARM64 object/symbol check before a boot.

## S1/S2: front sensor power and ID, then stop

7. Implement planned `camera_power_front()` / `camera_power_down_front()` using the exact `@4` order and delays
   (`fdt.dts:36129-36136`): CAM_BB, PP1350, RCAM_ANA, RCAM_VDIG, SLG LDO1/LDO8, vio, SLG LDO3, reset, MCLK3, VSYNC/resume.
   Add only the corresponding exact CPM GPIO/regulator and clock frames to `pmic_allowed()`/the clock allowlist. Read back every state
   where possible; any unknown reply stops and invokes the reverse sequence. Do not enable OIS, actuators, EEPROMs, or other cameras.
8. Implement CLI8 transport in `blazer_camera_hw.c`: LSIO_E/CLI8 votes and reset, front SCL/SDA mux, reset LSIO_E pin 6, the FDT's
   1 MHz controller configuration (`fdt.dts:12784-12804`), and 16-bit-register/8-bit-value read at address `0x1a`
   (`:36184-36212`). Prefer the vendor-supplied chip-ID address. If none is recoverable, a separate owner-approved fallback may read
   only the two explicitly documented candidate addresses, with no register writes or broad scan.
9. Log one `blazer-cam: sensor taotie-front bus cli8 addr 0x1a id ...` line and a matching powered-down line, then evaluate with
   `hk logs --grep 'blazer-cam:'`, `hk find --feature camera-sensor`, and
   `python3 -I tools/probe_eval.py --row camera-sensor <attempt>` (`docs/probes.yaml:981-999`). Repeat the sequence for ultra-wide or
   tele only after front passes. Leave rear I3C until a dedicated I3C proxy/dynamic-address implementation and shared-bus ownership
   review exist.

## C1+: staged capture research, not the next phone test

10. Recover the exact front sensor's mode/streaming tables and CSI lane/timing contract from matching vendor userspace/source. If those
    cannot be identified, stop at sensor ID rather than guessing a public sensor model.
11. Build a raw CSI still capture as its own milestone: ISP-FE/`csis-phy-link` setup, bounded register allowlists, IRQs, IOMMU mappings,
    one statically owned raw buffer, one frame, then stream-off and power-down. Validate error/timeout/ownership paths on host first.
12. Only after a raw frame is physically credible, stage ISP BE/GSW processing and 3A/tuning. Finally choose between an Apple-compatible
    ISP/capture service stack and a replacement userspace capture provider. That Apple-facing firmware/driver ABI work is a separate
    research project; F1/F2/S2 success says nothing about Camera.app readiness.

# 4. Risks and stop conditions

- **Evidence risk:** 17/17 host cases and ARM64 symbols prove implementation mechanics only. There is no physical hk-cam1 result, no
  sensor response, no frame, and no iOS camera service. Keep SOURCE/HOST/ARM64/PHYSICAL claims separate.
- **Torch safety:** torch mode has no relied-upon hardware timeout in this driver. Normal exits write standby and drop EN, but a panic
  during the timed hold can bypass cleanup. Use only the existing low-current bounded stage 4, attended; never increase current or add
  flash/both-LED modes. A cleanup failure is a failed run even if EN appears off.
- **Ownership/restoration:** CLI7 starts as UART, and pads/rails may be left by the loader or shared with other hardware. Refuse unknown
  values and busy buses; restore protocol word 0 last as `put_back()` does. Do not force a bus that another agent owns.
- **PMIC danger:** CPM firmware behavior is closed; an allowlist limits mistakes but does not prove a frame harmless. Wrong GPIO IDs,
  LDO writes, voltages, or power-down order can affect shared camera rails or hang the SoC. First CS/rail writes need explicit owner
  approval, exact vendor values, host mutants, and a reliable return path.
- **“Read-only” is not automatically side-effect-free:** LM3644 flag reads clear stale flags by design, and an unknown sensor register
  read may have device-specific effects. Prefer recovered ID registers; no broad I2C/I3C/MMIO scans.
- **I3C complexity:** rear-wide shares its bus with companion devices and adds I3C proxy/dynamic-address behavior. It is not a drop-in
  extension of front I2C and must not be the first sensor test.
- **ISP/DMA risk:** incorrect ISP power, SMMU, interrupt, or buffer setup can cause bus faults or memory corruption. No DMA or streaming
  write belongs in the flash/ID lane. Raw capture requires independently reviewed ownership, mappings, timeouts, and stream-off.
- **Integration risk:** a torch pulse or sensor ID is not capture, and even a raw frame is not an iOS camera. Sensor tables, calibration,
  3A, ISP programming, and the Apple-facing service/firmware ABI remain independent blockers.
