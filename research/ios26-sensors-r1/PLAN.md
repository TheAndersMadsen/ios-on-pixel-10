# Sensors on iOS 26 (blazer): attachment, iOS shapes, staged plan, first step built

2026-11-03, m1box, implementation sub-agent. No phone access in this work. Labels: **PHYSICAL** (read on this phone),
**FDT/FILE** (stock DT decompile / stock vendor file), **SOURCE** (our code), **HOST** (host test or static reading),
**INFERRED** (my reasoning). Earlier design and stop conditions of the bus code: `DESIGN.md` (sensor-i2c-r1).

## 1. How each sensor is attached

All motion and environment sensors hang off the **AoC** (always-on compute) sensor buses, not off AP I2C/SPI.
Android drives them through AoC firmware: `vendor/etc/sensors/hals.conf` lists `sensors.usf.so` (Google USF on AoC),
`sensors.eldi.so`, `sensors.dynamic_sensor_hal.so` (FILE); the DT's `aoc@9000000` has `chre-supported`, and
`sensor_1v8-supply`/`sensor_3v3-supply` (PMIC LDO7S 0x3d / LDO5S 0x3b) with `sensor_power_list` (FDT). The AP kernel
binds no IMU/ALS/baro driver (INFERRED from the HAL list; the adb `buses`/`modules` queries below confirm it).

Parts and buses, from `vendor/etc/sensors/registry/blazer_common.reg` (FILE) and the AoC pinctrl `gpio-line-names` (FDT):

| Sensor | Part | AoC bus | Address | AoC pads (line names) | IRQ line | Status |
|---|---|---|---|---|---|---|
| Accel + gyro | TDK ICM-45631 | i3c4 (I2C fallback 400 kHz) | 0x68 (I3C 0x0a) | 35/36 `AOC_SNS_I3C4_SCL/SDA` | 55 `IMU2AOC_INT_OD_L` | **PHYSICAL: WHO_AM_I 0xe8, streaming** |
| Magnetometer | MEMSIC MMC5616WA | i3c0 | 0x30 (I3C 0x14) | 67/68 `AOC_SNS_I3C0_SCL/SDA_1V2` | — | first step built here (0930) |
| ALS + proximity (+ colour, spectral) | ams TMD3743 | i2c2 | 0x39 | 33/34 `AOC_SNS_I2C2_SCL/SDA` | 86 `PROX0_2_AOC_INT_OD_L` | census code exists, never run |
| Barometer (+ temp) | SPL07-003 | i2c2 | 0x77 | 33/34 | 85 `BARO2AOC_INT_OD_L` | census code exists, never run |
| Rear spectral/flicker ("rainbow") | ST VD6282 | i2c2 (+PDM 4) | 0x20 | 33/34 | — | census only |
| IR thermometer | Melexis MLX90632 | i2c2 | 0x3b | 33/34 | — | census only |

Registry transforms: accel/gyro `1 2 3`, mag `-2 -1 -3`. ALS is under the OLED: the registry's `pwm_hz=240 480`,
`vsync_delay_us`, `is_te2_node_enabled=1`, `leakage_model_type=3` say AoC synchronises ALS integration with the panel's
PWM/TE and subtracts display leakage (FILE; meaning INFERRED). Pad 34 (i2c2 SDA) is in the AoC pinctrl's
`gpio-reserved-ranges` (`0x22`) (FDT); pads 33, 35, 36, 67, 68 are not reserved or shared.

**PHYSICAL evidence for the direct path** (`research/laguna-usb-fix/attempts/20261102-091607-sensor-stream-r2`, Mac,
kernel p26, image 1a935985…): with AoC not started, the AP bit-bangs I2C on pads 35/36 (pads in GPIO mode, pull-ups from
the pads, rails through the CPM queue owner): `who am i: 0xe8 at address 0x68`, `accel and gyro on`, samples 0..2400
(about 4 min at 10 Hz) with gravity ≈ -990 mg face up, orientation changes `0x69 → 0x68 → 0x65`, and backboardd opened
SweetHIDAccel/Gyro/Orientation. App-level rotation and CoreMotion callbacks were not shown.

**Hub (CHRE/USF on AoC) path: not chosen.** Starting AoC needs the Trusty/GSA loader, an AoC firmware image and
Google's USF protocol (`research/ios26-fleet/handoffs/aoc.md`: rung 1 only reaches GET_STATE). It is the right long-term
owner (FIFOs, interrupts, ALS leakage compensation, power) but is weeks of unknown protocol work. The two paths exclude
each other: once AoC firmware runs it owns these pads; the direct code already stops if a pad leaves GPIO or AoC's
control block moves (`sns_still_idle`).

## 2. What iOS 26 expects

Full receipt: `ios/CONSUMERS.md` (HOST, static). Summary:
- **Motion**: Apple vendor page 0xff00, accel 0x03, gyro 0x09, compass 0x0A, each with an HID-sensor-page pair (0x73,
  0x76, 0x83). Orientation 0x20/0x8A as the tegu record has it (already physical: backboardd opens it).
- **ALS → CoreBrightness**: matches 0xff00/0x04 or 0x20/0x41; reads `Built-In`, `Placement`, `ALSSensorType`,
  `Orientation`, integration times, `ALSSensorMin/Max`; sets `ReportInterval`, `ALSIntegrationMode`; consumes event type
  12 fields Level (0xc0000) and Illuminance (0xc000b). Brightness control also needs patch 0001 (calibration).
- **Proximity → backboardd/CoreBrightness**: 0xff00/0x08, proximityEvent.
- **locationd** registers usage pairs at runtime. It has two compass paths: CLCompass6 (raw magnetometer + AP-side
  calibration) and CLCompass7 (needs the SPU device-motion service). Which one iPhone12,3 picks is open.

## 3. Prior art (web)

No public Darwin/iOS port on non-Apple phones exposes real sensors: Corellium simulates sensors in its own
hypervisor (closed), QEMU iOS ports have none, winocm's XNU-on-other-hardware work never reached iOS UI. Apple's
open-source IOHIDFamily (`AppleHIDUsageTables.h`, `AppleEmbeddedHIDEventService`) is the only public contract:
it confirms AmbientLightSensor 0x04, ProximitySensor 0x08, Compass 0x0A on page 0xff00 and the accel/gyro/proximity/ALS
dispatch methods. The in-project ios-tegu record (Tensor G4) is the only port-level precedent. References are in the
final summary; `docs/reuse/2026-11-02/sensors.md` audits the driver-side sources (Betaflight SPL07-003, MEMSIC map,
TDK HAL, Fusion).

## 4. Staged plan

| Stage | What | Effort | Risk | Evidence now | Needs |
|---|---|---|---|---|---|
| S0 | IMU accel+gyro over AoC pads, SweetHID accel/gyro/orientation | done | — | PHYSICAL (sensor-stream-r2) | — |
| S1 | Same on the ios_system Home line (r3 + `blazer_sensors=2`) | boot only | low | kernel ddf874fb has the code (symbols, strings checked) | attended boot |
| S2 | **Compass**: MMC5616WA on pads 67/68 in the IMU loop, SweetHIDCompass (patch 0930) | built (host) | low-med | HOST: 301+bench+22 mutants; ARM64 objects with the build's flags; applies to b228c4f | kernel link + QEMU smoke + image_tool admission + attended boot |
| S3 | Census of i2c2 (pads 33/34): who answers at 0x39/0x77/0x20/0x3b, id bytes | boot only | med (pad 34 reserved) | census code in ddf874fb | **owner decision on pad 34**, image_tool `[1-5]` |
| S4 | Barometer SPL07-003: integer compensation (from Betaflight MPL-2.0 host oracle), SweetHIDPressure | 2-3 days | med | none | S3 ack at 0x77; pressure usage from locationd |
| S5 | IMU quality: 50-100 Hz, FIFO + IRQ pad 55 timestamps, gyro scale check | 2-4 days | med | polling works | turn test with Android reference values |
| S6 | ALS TMD3743 → CoreBrightness | 1-2 weeks | **high** | none: no public register map; under-OLED leakage | S3 id, family map (TMD37xx) or AoC firmware reading, DPU TE sync, patch 0001 |
| S7 | Proximity TMD3743 | 3-5 days after S6 | med | none | S6 bus work, IR LED drive; useful with telephony |
| S8 | Device-motion fusion service (if locationd uses CLCompass7) or app-visible proof | 1 week | med | open | S2 logs, app registration (apps lane) for a landscape/compass app |
| L | AoC/CHRE hub instead of direct pads | weeks | high | rung 1 only | Trusty/GSA load, USF protocol |

App-visible acceptance (rotation in an app, Compass, CMMotionManager callbacks via `research/ios26-feature-motion-r1`
MotionProbe) is blocked on the apps lane (stock-app registration, AKS user keybag); until then acceptance is kernel and
service-level.

## 5. First step built: patch 0930 (compass)

`mag-r1/patches/0930-blazer-sensor-compass.patch` against release `b228c4f` (`git apply --check` OK on the Mac tree,
`mag-r1/receipts/apply-check.txt`). Off unless `blazer_sensors=2 blazer_sensors_mag=1`.

- `bsd/dev/blazer_mag_hw.{c,h}` (new, hardware-free): product id 0x39 must be 0x11; one SET (`0x1B=0x08`), 1 ms
  (tSR), then on-demand measurements with automatic SET/RESET (`0x1B=0x21`), pipelined: each 100 ms loop reads the nine
  output bytes of the previous trigger (≥ 6.6 ms tTM at BW=00) and starts the next. 20-bit unsigned, null 524288,
  16384 counts/G → nT (3125/512 per count). Registry transform -2 -1 -3 → iOS axes (sign convention INFERRED; flip arg).
  Stops for good on bus error, wrong id, all-00/ff output, or 50 identical samples. Status1's "done" bit is ambiguous
  in the datasheet (table bit 6 vs text bit 1): logged, never decided on. Address 0x7e (the I3C switch) is never sent.
  Datasheet: MEMSIC MMC5616WA v1.7, 2025-12-22, pages 2, 9-17, 27 (fetched from memsic.com; not in git).
- `bsd/dev/blazer_sensor_hw.{c,h}`: `SNS_MODE_STREAM_MAG` on pads 67/68; exact allowlists (reads 0x39/1, 0x18/1, 0x00/9;
  writes 0x1B with 0x08 or 0x21; address 0x30 only; IMU address refused in that mode and vice versa);
  `sns_bus_read/sns_bus_write`. Rails on at entry (the IMU's) stay the IMU's.
- `bsd/dev/blazer_sensors.c`: second `struct sns` and pad windows; compass in the same thread after the IMU starts;
  a compass stop puts its pads back and the IMU goes on; at stream end the compass goes down before the IMU's rails.
- `SweetHID.cpp` + `KernelConfigTables.cpp`: `SweetHIDCompass` 0xff00/0x0A + pair 0x20/0x83, compassEvent in 16.16 µT
  (units INFERRED), IOResources match entry.

Tests (HOST, `mag-r1/receipts/host-tests.txt`, `python3 -I mag-r1/tools/run_tests.py <patched bsd/dev copy>`):
`host_mag.c` 301 checks (register model from the datasheet), the unchanged existing `tests/bench.c` passes on the patched
file, `bench_mag.c` bit-level on pads 67/68 (I2C bytes, allowlists, pad restore, rails ownership, wrong id, absent part,
muxed pad, AoC wake), and 22/22 mutants caught. ARM64: local arm64e objects of the two hardware-free files (no undefined
symbols), and all five changed files compiled on the Mac with the release build's exact per-object commands
(`*.o.json`) into /tmp copies: `mag-r1/receipts/mac-objects.txt` (SweetHIDCompass vtable/start/sample, `_sweet_hid_compass`,
`_sns_bus_read/_write`, `_mag_*`; blazer_sensors.o's undefined `_mag_*`, `_sns_bus_*`, `_sweet_hid_compass` are all defined
by the other objects). **Not linked, not QEMU-run, not booted.**

## 6. Attended boots (coordinator runs; bare `fastboot boot`, ANDROID_SERIAL set, return check after each)

Base for all: r3's recipe (`research/ios26-dualboot-r8/A7-READY.md` step 6, `hk_bright=140` removed; r3 manifest
`research/images/a7-ios-system-r3/manifest.json`, cmdline 999 bytes; limit 1023).

**S1 `sensors-rot-r1`** (no build; kernel ddf874fb `research/ios26-dualboot-r8/rootview/kernel.rootview`):
r3's exact `image_tool image` command with `--phone-args "<r3 phone-args> blazer_sensors=2"` (1016 bytes), then
`image_tool check`, `tools/bootios … --mach research/ios26-dualboot-r8/rootview/kernel.rootview.unstripped --wait 480`.
Owner: after Home (~110 s), lay the phone flat 10 s, hold upright 10 s, turn landscape left and right 10 s each.
PASS: `blazer-sensors: who am i: 0xe8`, `accel and gyro on`, `SWEET HID: accel registered` (and gyro, orientation),
`SweetHIDOrientation open by IOHIDEventServiceUserClient`, `orientation 0x69`, `0x65`, `0x67`/`0x68` in the owner's order,
Home still drawn, touch still works. FAIL/stop: any `blazer-sensors: stopped:`, `stream ends`, or loss of touch/Home vs r3.
Rotation on screen is NOT expected (Settings and Home are portrait-only).

**S2 `sensors-mag-r1`** (needs: coordinator links the A7 kernel's tree + 0930 on the Mac, QEMU smoke with the args
present (expect `blazer-sensors: mode 2` and a gate stop, no panic), and image_tool admitting `blazer_sensors_mag=1`,
`blazer_sensors_mag_flip=[0-7]`): S1's args with `hk_present_trace=1` removed and `blazer_sensors_mag=1` added (1018 bytes).
Owner: as S1, then turn the phone flat through north/east/south/west, 10 s each.
PASS: S1's lines plus `compass bus ready on pads 67, 68`, `mag product id 0x11 at 0x30`, `compass on`, `compass 0..7: x y z nT`
not constant, each axis within ±3,000,000 nT (30 G range), and the horizontal components changing by tens of µT with the
turns (raw values include the phone's own hard-iron offset, so |B| need not be Earth's 25-65 µT; locationd calibrates), `SWEET HID: compass registered`
and `SweetHIDCompass open by IOHIDEventServiceUserClient`. Stops that are not failures of the boot: `compass not started`
(then report its detail; the IMU must keep streaming). FAIL: IMU stops when the compass starts, or `pads restored 0`.

**S3 `sensors-census-i2c2-r1`** (owner decision first: pad 34 is gpio-reserved in the FDT): kernel ddf874fb, image_tool
admitting `blazer_sensors=[1-5]`, `--phone-args "<r3 phone-args> blazer_sensors=5"` (1016 bytes). Ends ~25 s after the
sensor thread starts with `panic("blazer-sensors: end of probe…")` (deliberate; `blazer_panic=1` resets). PASS: four
`census … at 0x..: ack|no ack` lines, id bytes for tmd3743 (reg 0x92) and spl07003 (reg 0x0d), `pads restored 1`,
`rails off 1`. Any `SCL/SDA low with the bus idle` or `pad not GPIO at entry` = stop, no retry.

Proposed `tools/image_tool.py` PHONE_ALLOWED change (bootchain owner's file, not edited here):
```
-'blazer_sensors': r'blazer_sensors=[123]', 'blazer_sensors_flip': r'blazer_sensors_flip=[0-7]',
+'blazer_sensors': r'blazer_sensors=[1-5]', 'blazer_sensors_flip': r'blazer_sensors_flip=[0-7]',
+'blazer_sensors_mag': r'blazer_sensors_mag=1', 'blazer_sensors_mag_flip': r'blazer_sensors_mag_flip=[0-7]',
```
(`=4`/`=5` only for the census boots; `=5` only after the owner's word on pad 34.)

## 7. Android queries wanted (read-only)

`android/ADB-REQUEST.md`: sensorservice list and recent events (reference values for units and signs), contexthub,
HAL list, I2C/I3C/IIO buses and modules, live AoC DT and pinmux of pads 33-36/67-68/85-86, AoC state, persist
calibration file names, display lux.

## 8. Open questions

- locationd on iPhone12,3: CLCompass6 (raw) or CLCompass7 (SPU device motion)? S2 shows whether the service is opened; a
  locationd log mirror (as `edit_logmirror_backboardd.py`) would show `Adding match entry for usage pair {65280, 10}`.
- Compass units µT in 16.16 and the iOS sign convention: inferred; check against `dumpsys sensorservice` µT.
- TMD3743 register map and AoC's display-leakage model: no public source; S3 gives the id byte first.
- Pressure usage pair; SPL07-003 compensation in integer arithmetic (kernel has no FPU use).
