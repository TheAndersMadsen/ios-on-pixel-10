# What iOS 26 consumes: sensor HID service shapes (host, static)

Sources: dyld cache `/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e` (the cache the A7 analysis used, 0f1ee332),
locationd copied read-only from `research/ios26-apps-r1/artifacts/apps-full-r6.img` (image sha256 aff3ebbe…f80,
unchanged after the read-only loop mount; binary kept on the rig at `/data/hackios-qemu/research/ios26-sensors-r1/bin/locationd`,
not in git). Tools: `../tools/ios/` (dsc_cstr.py, dsc_xref.py, conforms.py, objc_dicts.py, macho_usage_calls.py) plus
`research/ios26-phaseb-r1/corebrightness/cbdis.py`. Everything below is static reading, not a run.

## CoreBrightness (ALS, auto-brightness)

`IOHIDServiceClientConformsTo(service, page, usage)` call sites in CoreBrightness `__text` (27 calls, cbdis listing):

| Page/usage | Calls | Meaning (Apple usage tables) | Nearby strings |
|---|---|---|---|
| 0xff00 / 0x04 | 10 | AppleVendor AmbientLightSensor | `ALSServiceReady`, `DeviceUsagePairs`, `AODALSMode`, `AABSensorOverrideOrientation` |
| 0x20 / 0x41 | 7 | HID sensor page, Ambient Light | same functions: either pair is accepted |
| 0xff00 / 0x08 | 2 | AppleVendor ProximitySensor | `SuperFastModeReportInterval` |
| 0xff00 / 0x62, 0x0f; 0xff12 / 0x01 | 1 each | not decoded | `Placement`, `DFRWhitepointSupport` |
| 0x0d / 0x04, 0x0d / 0x0c | 2 each | digitizer touch screen / pad | `Placement` (touch-based ALS filtering) |

Properties CoreBrightness reads from the ALS service (`IOHIDServiceClientCopyProperty`, in order of first use):
`PrimaryUsagePage`, `PrimaryUsage`, `Built-In`, `DeviceUsagePairs`, `Orientation`, `Placement`, `ALSSensorType`,
`FDRCalibration`, `ALSSuperFastIntegrationTime`, `ALSFastIntegrationTime`, `ALSSlowIntegrationTime`, `ALSSensorMin`,
`ALSSensorMax`, `FastModeFilter`, `SlowModeReportInterval`, `FastModeReportInterval`, `SuperFastModeReportInterval`,
`SensorLocation`, `crgb`, `VendorID`, `ColorSupport`. It sets `ALSLPannelValues`, `ReportInterval`, `ALSIntegrationMode`,
`AODALSMode`, `IOHIDALSContinuousMode`, `IOHIDALSTestMode`, `IOHIDBacklightLevel`.

Event fields read (event type 12, kIOHIDEventTypeAmbientLightSensor): `0xc0000` Level (integer and float),
`0xc0007..0xc0009` colour components, `0xc000a` colour temperature, `0xc000b` Illuminance (double). So a minimal ALS
event fills Level and Illuminance with lux; colour fields are optional. Inferred minimum service: 0xff00/4 with the
0x20/0x41 pair, `Built-In`, `ReportInterval` settable, `Placement`/`ALSSensorType` present (values not decoded yet).

Separate blocker (known, `research/ios26-phaseb-r1/corebrightness/FINDINGS.md`): brightness control needs
`backlight-calibration-parameters` on AppleARMBacklight (patch 0001, not built). Without it an ALS changes nothing visible.

## backboardd (orientation)

Physical (sensor-stream-r2, 2026-11-02): backboardd opened SweetHIDAccel, SweetHIDGyro and SweetHIDOrientation
(`open … type 1702065507 -> 0x0`) and matched SweetHIDAccel by registry ID. The orientation shape in use is ios-tegu's
record (0x20/0x8A, kIOHIDOrientationTypeCMUsage, child vendor event 0xff15/2 with a rising 64-bit stamp). Not checked
on our root: whether UIKit rotates. iPhone Settings and the iPhone12,3 Home screen are portrait-only, so a visible test
needs a landscape-capable app.

## locationd / CoreMotion (motion, compass, pressure, proximity)

- CoreMotion.framework talks to IOHID mostly through `IOHIDEventSystemClientSetMatchingMultiple` (2 sites, 0xff00-page
  dictionaries built at runtime, not decoded) and the SPU fast path; the main consumer is locationd.
- locationd's `CLIoHidInterface` adds devices by usage pair at runtime (`Adding match entry for usage pair {%d, %d}`),
  through a wrapper; the pairs are not readable statically in reasonable time. Its constant literal matching
  dictionaries are only: `{PrimaryUsagePage 0x20, PrimaryUsage 0x73, ProductID 0x450}` (an accessory accelerometer),
  a keyboard/pointer set, and `{IOProviderClass AppleSPUHIDDevice, 0xff0c/0x2e}`.
- Two compass implementations exist: **CLCompass6** (`onMagnetometerData(CLMagnetometer::Sample)`, AP-side calibration
  `CLCompassCalibrator`/`CLCompassCalibratorAKM`) and **CLCompass7** (`onDeviceMotionServiceIohidEvent`, "CLCompass7
  requires deviceMotionService": fusion on the SPU). Which one iPhone12,3 selects is decided at runtime (inferred: by
  platform capability). If it is CLCompass7, a raw magnetometer service alone gives no heading: a host-side
  device-motion service (0xff00/0x0E Motion or the SPU fast path) would be needed. **Open; the S2 boot's logs decide.**
- Pressure: `CLAltimeterInterface`, `CLPressureDataManager`, `CLPressureBias` exist; usage pair not decoded.
- Proximity: `CLProximityNotifier`, `CLProxPDPAndALSPhoneNotifier`; entitlement `com.apple.backboardd.proximityDetection`:
  proximity is backboardd's (and CoreBrightness's 0xff00/8 use).

## Usage values used by our services

| Service | Primary | Pair | Event | Source of the numbers |
|---|---|---|---|---|
| SweetHIDAccel (exists) | 0xff00/0x03 | 0x20/0x73 | accelerometerEvent, 16.16 g | tegu record; Apple tables |
| SweetHIDGyro (exists) | 0xff00/0x09 | 0x20/0x76 | gyroEvent, 16.16 rad/s | same |
| SweetHIDOrientation (exists) | 0x20/0x8A | — | orientationEvent CM usage + 0xff15/2 child | tegu record |
| SweetHIDCompass (0930) | 0xff00/0x0A | 0x20/0x83 | compassEvent, 16.16 µT (units inferred) | Apple tables (0x0A Compass); HID sensor page Compass 3D |
| ALS (planned) | 0xff00/0x04 | 0x20/0x41 | ambientLightSensorEvent, Level + Illuminance | CoreBrightness ConformsTo above |
| Proximity (planned) | 0xff00/0x08 | — | proximityEvent | CoreBrightness ConformsTo above |
| Pressure (planned) | not decoded | 0x20/0x31 likely | atmosphericPressureEvent | open |
