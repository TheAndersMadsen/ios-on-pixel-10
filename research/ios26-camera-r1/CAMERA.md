# Cameras and flash: path map and first step (hk-cam1, 2026-11-04, m1box + Mac, no phone)

Labels: **SOURCE** (FDT `research/ios26-dualboot-r8/truth/fdt.dts`, our code), **DATASHEET** (TI SNVSA52E, read from the PDF),
**HOST** (tests on m1box), **ARM64** (objects/kernel built with the gate on), **PHYSICAL** (an earlier phone log, re-read),
**INFERENCE**. Nothing here touched the phone. Device dumps, the datasheet PDF and images stay out of git.

## Result

- **Reachable now:** the flash LED (TI **LM3644**, I2C) and, later, the camera PMIC and sensor ID registers. A capture pipeline
  (CSI receive, ISP, 3A, Apple's capture ABI) is a long stage plan, not a next step (section 4).
- **What blocked the existing probe (PHYSICAL):** `blazer_torch` (p1, stages 1-2, read-only) ran once, attempt
  `research/laguna-usb-fix/attempts/20261102-090454-torch-1-r1` (p26 kernel, `blazer_torch=1`): `lsio_e 2`, `lsio_s 2`,
  `cli was 2,1,1`, `stop cli, detail 0x2`. CLI7 is left in **UART** mode by the loader, so stage 1 and 2 never reach the I2C
  controller. Stock Linux selects I2C at probe time through the `default` pinctrl state (`cli7_i2c` word 0 = 1, plus the
  `xlsioe_cli7_pin0/1` mux). CLI7's UART personality (`uart@3a302000`) is `status = "disabled"`, so nothing else owns it (SOURCE).
- **hk-cam1 (SOURCE, HOST, ARM64 object):** two new stages on the same file.
  - `blazer_torch=3`: stage 2 plus CLI7 word 0 UART→I2C and SCL/SDA muxed to CLI7. It reads the ID (reg 0x0C) and the enable
    register (reg 0x01), makes no chip write, and puts everything back.
  - `blazer_torch=4`: stage 3 plus the torch. LED1 lights for `blazer_torch_ms` (default 2000) at code 0x08 (12.2 mA; 24.4 mA
    on LM3644TT), then standby, a 1 s gap, then the same for LED2. The saved torch codes go back, then EN drops.
- **Kernel (ARM64, Mac):** XNU branch **hk-cam1 2e8d77709c99ebab645cf919cb28dc9cd1947e40** = 7227fe7 (the A7-r3 Home kernel's
  source, kernel.rootview ddf874fb) + `xnu-src/0001-hk-cam1.patch` (da630c6c…). `kernel.cam1` **c4c47954…9a5f**, unstripped
  02f27329…d304; symbols `_bt_run _torch _chip_write _pad_mux _write_allowed _blazer_torch_init`, the hk-cam1 strings, no
  b228c4f fake-LUN code (`receipts/build_cam1.out`, `receipts/kernel-verify.txt`). The shared tree went back to p1 b228c4f and was
  rebuilt (no hk-cam1 string).
- **Image (HOST):** `a7-ios-system-cam1` boot.img **51900a1a…fb44**, check `OK bootable`. It is r3's recipe + `blazer_torch=4`
  (1014 B line; the only token difference from r3), built with `tools/image_tool_cam1.py` (= the Mac's image_tool acf48b98 + one
  allowlist line, `receipts/image_tool_cam1.diff`). Phone test: `PHONE-TEST.md`. Not booted.
- **QEMU (m1box TCG, driver off: preflight drops `blazer_torch`; QEMU has no CLI7/LM3644):** `cam1-q1` and the r3 baseline
  `cam1-q1-base-r3` (kernel.rootview, same harness) give the same verdict: 0 panics (deadline end at 302 s), backboardd and
  SpringBoard once, the same milestones (cam1 about 6 s later on TCG), and the same single FAIL (`home-daemons`: no PosterBoard
  within 300 s). That FAIL is therefore not cam1's. QEMU says nothing about the torch path (`receipts/qemu-cam1-q1.*`,
  `receipts/qemu-r3-baseline.*`).

## 1. Camera path (SOURCE: FDT)

| Part | FDT node / name | Bus, address | Reset / enable | Clock | Supplies |
| --- | --- | --- | --- | --- | --- |
| Rear wide sensor | `sensor@0` "sensor-boitata" (lwis-i3c-proxy) | **I3C** `i3c-master@3bf11000` (LSIO_S CLI1), 0x3d, DCR 0x82, 16/16-bit regs | `reset-gpios` LSIO_S pin 13 (AP2RCAM_RST_L); `ois_enable` da9188 GPIO 1 | MCLK2 24.576 MHz | RCAM_ANA, RCAM_VDIG, CAM_BB, PP1350, vio, SLG ldo4, ldo2 |
| Front sensor | `sensor@1` "sensor-taotie-front" | I2C `i2c@3a311000` (LSIO_E CLI8), 0x1a, 16/8-bit | LSIO_E pin 6 | MCLK3 | + SLG ldo8, ldo1, ldo3 |
| Ultra-wide | `sensor@2` "sensor-taotie-uw" | I2C `i2c@3a361000` (LSIO_E CLI13), 0x1a | LSIO_E pin 10 | MCLK1 | + SLG ldo6, ldo2, gpio4 |
| Tele | `sensor@3` "sensor-taotie-tele" | I2C `i2c@3bf31000` (LSIO_S CLI3), 0x33 | LSIO_S pin 21 (AP2RTCAM_RST_L), OIS reset pin 30 | MCLK6 | + SLG ldo7, ldo5, ldo4, gpio3 |
| Actuators, OIS, EEPROMs | act 0x0c/0x0c/0x0f, OIS djinn 0x24 (I3C bus) / humbaba 0x61, EEPROM 0x24/0x51/0x50/0x61 | as their sensor | as their sensor | — | as their sensor |
| **Flash** | `flash@0` "flash-lm3644" | **I2C `i2c@3a301000` (LSIO_E CLI7), 0x63**, 8/8-bit | `enable-gpios` LSIO_S pin 22 (AP2FLASH_EN = HWEN); strobe LSIO_S PWM_0 (pin 23), unused | — | none in the FDT (power-up sequence = EN only) |
| Camera PMIC | `slg51002@75` (Dialog SLG51002), LDO1-8 + 4 GPIO rails | same CLI7 bus, 0x75 | `dlg,cs-gpios` da9188 GPIO 8 (PMICS2CAM_PMIC_EN) | — | vin from CAM_BB / PP1350 |
| Buck-boost | `cam_supply@77` RT6160 "PP3200_CAM_BB" | same CLI7 bus, 0x77 | da9188 GPIO 9 (PMICS2CAM_BB_EN) | — | — |
| Fixed rails | PP1350_CAM, PP2200_RCAM_ANA, PP0950_RCAM | — | da9188 GPIO 15, 2, 5 | — | — |
| Camera IO | `vio` = da9188 `ldo_22s` (L22S_CAMIO) | PMIC via CPM | — | — | — |
| ToF | "tof-tarasque" (lwis-spi) | SPI | — | — | — |
| ISP | LWIS ioreg devices `isp-fe` (+ `csis-phy-link`), `be-btr/yuv/msa`, `ispbe-pdma`, `gsw-gwe/gse/pdma`, `flow-sync`, `slc`; `ispfe_freq`/`ispbe_freq` DVFS; ispfe/ispbe interrupt aggregators; per-context `csis_int_st_rx`/`deskew` events (8 contexts) | — | — | — | — |

Power sequences (`module_power_seq@0..4`): CAM_BB → PP1350 → RCAM_ANA → RCAM_VDIG → SLG LDOs → vio → reset → MCLK on →
VSYNC pinctrl → resume (reset release, 5-7 ms). The da9188 GPIO controller is reached through CPM (`mba-dest-channel 0x0a`),
the path `blazer_cpmq` already uses physically for touch reset (GPIO 17) and BT_REG_ON.

**INFERENCE:** the ISP has no kernel driver in the usual sense. LWIS exposes raw register windows to the Android camera HAL,
which writes the sensor mode tables, CSI/ISP configuration and tuning from vendor userspace. Datasheet register tables for
"boitata"/"taotie" are not public (codenames, not part numbers); `docs/reuse/2026-11-02/media-radios.md` already warns
that guessed public sensor models prove nothing about register programming.

## 2. Reachable now vs firmware/tuning-bound

| Step | Needs | State |
| --- | --- | --- |
| F1 Flash LM3644 ID + torch | CLI7 select + mux (stock pinctrl), EN GPIO. No PMIC rail (LM3644 VIN is not in the FDT; INFERENCE: battery) | **built (hk-cam1)**, phone test designed |
| F2 Camera PMIC IDs (SLG51002 0x75, RT6160 0x77) on the same CLI7 bus | F1's bus; SLG51002 answers only with CS high (da9188 GPIO 8, a new PMIC-GPIO frame) | next; read-only |
| S1 Sensor power-up | CPM PMIC frames for da9188 GPIO 9, 15, 2, 5, 8 (+ LDO22S), SLG51002 LDO writes, MCLKn (CPM clock), reset GPIO | plan only: the first rail writes in this lane; owner approval |
| S2 Sensor ID read | S1 + CLI8 (front) at 0x1a: the smallest bus. Chip-ID register address is sensor-specific (not public) | plan |
| C1 CSI receive / ISP / 3A | ISP register programming that only the vendor HAL has, plus Apple's camera stack expecting Apple's ISP (H16-class firmware) | long stage plan; not reachable |

iOS's consumers: `cameracaptured` (seen in launchd logs, `user/501/com.apple.cameracaptured`) and `dietapplecamerad`. Today
they find no camera service. Their logs are mirrored by adding them to obs1's `hk_logmirror` rule (section 6).

## 3. hk-cam1 safety (SOURCE, HOST)

- Allowlists: physical addresses (reads and writes by stage), CPM frames (LPB GET, LPCM clock/reset only, never a PMIC frame),
  `IC_TAR` = 0x63 only, `IC_DATA_CMD` words. A non-read data word is a readable register number, or the one armed write.
  Writes (`write_allowed`) are exactly: 0x01 ∈ {0x80, 0x89, 0x8a}, 0x05/0x06 ∈ {0x08, the saved value}. That means no flash
  mode, no IR mode, no both-LEDs, no full-scale torch, no software reset.
- Stage 4 lights only with ID 0x02/0x04 and the enable register at its reset value 0x80. Mode bits M1:M0 are bits 3:2; LED2 is
  bit 1, LED1 bit 0 (DATASHEET 8.6.1; a web summary had these wrong, so the PDF is the source).
- Every way out: standby (0x01 = 0x80) if a mode write might be live, the saved torch codes, controller off, then EN driven low
  and released. HWEN low = shutdown/reset (DATASHEET pin table), so the LED is off even if the I2C write fails. Pads and CLI words
  go back to as found, word 0 last.
- Torch has no hardware time-out (DATASHEET 8.3.2), so the bound is the code's `delay` (500..5000 ms, clamped) followed by
  standby. A panic during the hold would leave the LED on until the reset into fastboot. INFERENCE: the reset drops the AP GPIO,
  and HWEN has an internal pull-down.
- HOST: `tests/test_blazer_torch.c` runs the exact file against a model of the MBA page, CLI7, pads, DW I2C and an LM3644 with
  LED on-time accounting. **17/17 PASS**: stage 1/2 on torch-1-r1's state write nothing outside the MBA page; stage 3 lights
  nothing; stage 4 gives exactly the write list, 2000 ms per LED, never both; TT accepted; unknown ID, enable≠0x80, fault flag,
  no chip, lines low, unknown pad function, NAK while lit, flags-read NAK while lit (put_back's standby), CLI already I2C,
  LSIO off; gates. **`tests/mutants.py`: 16/16 mutants caught** (receipts/host-test.txt, receipts/mutants.txt).
- ARM64: `blazer_torch_hw.c` with `-DBLAZER` for arm64 Mach-O (local clang 23): `_bt_run _bt_init _torch _chip_write _pad_mux`,
  strings present (receipts/arm64-object.txt); the Mac kernel build's objects: blazer_torch.o 82b1307b…, blazer_torch_hw.o 4b5975d3…
  (build/obj, not for git).

## 4. Stage plan after F1

1. **F2** (read-only, one boot, can share F1's image line): add the CPM PMIC-GPIO frame for da9188 GPIO 8 (CS high) to
   `blazer_cpmq`'s exact list, then read SLG51002's ID/status and RT6160's ID on CLI7. Put CS back.
2. **S1/S2** (front camera first: CLI8, 8-bit registers, no I3C): CAM_BB (GPIO 9) → PP1350 (GPIO 15) → RCAM rails → SLG ldo8/1/3
   → LDO22S vio → MCLK3 at 24.576 MHz → release reset (LSIO_E pin 6) → read the sensor's chip-ID registers at 0x1a → reverse
   the sequence. The register address needs either the vendor's sensor table (not public) or a bounded read sweep of the
   common CCI ID locations (0x0000/0x0016, 16-bit). Owner approval first: these are the first PMIC rail writes in this lane.
3. **C1+:** CSI-2 receive needs the ISP FE `csis-phy-link` programming and sensor streaming tables, then ISP BE and 3A.
   Bridging that to iOS's capture stack (cameracaptured expects Apple's ISP) is research, not a stage.

## 5. Phone test (coordinator runs it; designed here)

See `PHONE-TEST.md`.

## 6. OBS

- Kernel lines: `blazer-torch:` prefix (hklog `--grep blazer-torch`). Proving lines are in `docs/probes.yaml` (`flash`, `camera-sensor`).
- Daemon mirror: append `cameracaptured+dietapplecamerad` to obs1's mirror rule (`obs_overlay.py BASE DYLIB OUT --programs
  …,cameracaptured,dietapplecamerad`; about 30 of the ~100 free bytes). The cam1 image uses r3's overlay (no mirror), because
  F1 is a kernel-only test. The mirror belongs on the next int/obs image.
