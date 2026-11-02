# Sensor and RTC reuse audit

Audited 2026-11-02; research only. No build, boot, bus transaction, firmware
download or implementation change was performed. Public heads were checked with
`git ls-remote`; individual source files and local counterparts were inspected.
GitHub's unauthenticated API was rate-limited, so it was not used to infer pins.

The largest immediate saving is to reuse the **existing MotionProbe acceptance
app**, then diagnose the failing boundary. Replacing working IMU transport would
repeat completed work. Two newly verified resources remove older research gaps:
the manufacturer now publishes the MMC5616WA register map, and Betaflight has
actual SPL07-003 compensation code under a file-level MPL option.

## Local state and boundaries

- Physical attempt `20261102-091607-sensor-stream-r2` captured accel/gyro samples
  and orientation changes; HID clients opened. CoreMotion callbacks, calibrated
  gyro gain and visible application rotation remain unproved.
- The p29 source inspected is under `research/ios26-release-r1/work/xnu/`.
  `bsd/dev/blazer_sensor_hw.c::sns_read_imu` decodes twelve little-endian bytes;
  its first plausible gravity sample chooses 8192 or 16384 LSB/g.
  `sns_gyro_mdps` infers gyro full scale from that accel choice.
- `iokit/Kernel/arm/hid/SweetHID.cpp` already creates accel, gyro and orientation
  services. Accel converts mg to 16.16 g; gyro converts mdps to 16.16 rad/s.
  Each vector obtains a separate host dispatch timestamp. Sampling is a fixed
  100 ms sleep plus work in `blazer_sensors_stream`, not hardware timestamped FIFO.
- The same file's generic `IOHIDEventService::setProperties` accepts any dictionary
  without applying settings. Thus property success does not establish requested
  sensor rate, batching or power policy. Do not change this shared implementation
  blindly: touch and keys also use it.
- `research/ios26-feature-motion-r1/src/MotionProbe.m` is already a native UIKit /
  CoreMotion callback-and-rotation probe. Its handoff records a built ARM64 app
  and host-tested acceptance logic, but no app execution. RAM-overlay packaging,
  registration, signing/trust and motion permission remain prerequisites.
- RTC bounds work is also already delivered locally in
  `research/ios26-feature-rtc-r1/patches/0657-blazer-rtc-bounds.patch`; the inspected
  release RTC source lacks the new `blazer_rtc_bounds` gate. Review/integrate that
  existing patch before inventing another epoch/calendar implementation.

## Candidates ranked by useful savings

| Candidate | Reuse class | Priority / confidence | Work avoided |
|---|---|---|---|
| Existing MotionProbe + Apple HID source contracts | Already present / selective comparison | P0 / high | Another sensor test app and blind daemon patches |
| Betaflight SPL07-003 compensation | Source extraction or host oracle | P1 / high for math, hardware unknown | Packed coefficient and compensation rediscovery |
| MEMSIC MMC5616WA datasheet | Hardware reference, original implementation | P1 / high for document, part match unknown | Guessing the compass register family |
| TDK ICM456xx HAL | Selective source / differential oracle | P2 / medium | FIFO, endian and configuration mechanics |
| Fusion remap/calibration | Optional host/userspace library | P2 / medium | Handwritten axis-remap and later fusion math |

### 1. Apple HID contracts: compare what is already embedded

Verified head: `apple-oss-distributions/IOHIDFamily`
`777ccd9698845aadf711e32d843c8c9b777431d9`.
The inspected files carry **APSL-2.0** headers. Exact references:
[`IOHIDEvent.cpp`, `_motionEvent`, `accelerometerEvent`, `gyroEvent`, `atmosphericPressureEvent`](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDFamily/IOHIDEvent.cpp),
[`IOHIDEventService.cpp::setProperties`](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDFamily/IOHIDEventService.cpp#L627), and
[`IOHIDEventDriver.cpp::setProperties`](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDFamily/IOHIDEventDriver.cpp#L1661).

Local `arm/hid/IOHIDEvent.cpp` already contains these event constructors and
motion-sequence serialization. Reimporting them is low value. Useful work is a
field/size/default comparison against the **actual embedded iOS 26 consumer**,
followed by sensor-subclass property handling only where observed client requests
require it. Public macOS IOHIDFamily is a contract reference, not proof of the
proprietary iOS 26 daemon's matching or calibration expectations.

Smallest proof: reuse MotionProbe packaging and add a host event-serialization
check for extrema, unit conversions, sequence and timestamps using the real
constructors. No new service or guessed usage page is necessary. A future
physical callback test distinguishes service discovery, delivery and orientation.

### 2. Betaflight actually implements SPL07-003

Verified `betaflight/betaflight` head:
`5fbd06144d75998d9c1a94d5ae8b7afb188c6669`.
[`barometer_dps310.c`](https://github.com/betaflight/betaflight/blob/5fbd06144d75998d9c1a94d5ae8b7afb188c6669/src/main/drivers/barometer/barometer_dps310.c)
and its corresponding header offer **MPL-2.0 or GPL-3.0-or-later** at file level;
do not assume the repository's broad GPL description is the only option.

The file distinguishes SPL07-003 from DPS310, reads the longer coefficient block,
decodes additional signed coefficients, and applies a different compensation
polynomial. Relevant symbols: `getTwosComplement`, `deviceConfigure`,
`dps310GetUP`, `baroDPS310IsSPL07_003`. This is a real source path for the stock
registry's `spl07003`, not an assumption that related Infineon parts are identical.

First task: extract the packed-coefficient decoder and compensation as an
MPL-noticed **host oracle**, with signed-boundary and malformed-input vectors.
Keep Betaflight bus/platform wrappers out. Its floating-point compensation belongs
in a host/userspace proof; direct kernel reuse needs an explicit numerical/FPU
design and must not silently introduce floating point into XNU kernel code.
Bus ownership, the reserved pad34, exact chip identity and native pressure-service
delivery remain unresolved. This audit authorizes no bus access.

### 3. Manufacturer MMC5616WA map replaces the old missing-map lead

Primary document:
[`MMC5616WA datasheet v1.7, 2025-12-22`](https://www.memsic.com/Public/Uploads/uploadfile/files/20251224/MMC5616WADatasheetv1.7forrelease20251222.pdf).
It was retrieved from MEMSIC and inspected as text; this is a manufacturer
reference, **not licensed driver source to copy wholesale**.

Pages 9-16 provide the register map and details. Product ID is at `0x39`, with
documented reset value `0x11`; the static I2C address is normally `0x30`.
The document distinguishes output packing, offset and sensitivity by resolution.
Its I3C discussion also contains explicitly unresolved editorial assumptions;
do not promote those statements into verified Pixel facts.

The local handoff previously had only MMC5603 family information. The new map
can support an original host decoder and bounded state-model specification for
the existing compass census path, without guessing from another part. First
confirm that the phone's `mmc5616` denotes this exact WA variant and bus mode.
No compass sample, ID or calibration success was observed in this audit.

### 4. TDK provides a permissive C HAL, but not an established ICM45631 match

Verified `tdk-invn-oss/zephyr.hal_tdk` head:
`330218a1f25cd58eab3b81eda7510e73525c2e76`.
Repository licence and inspected driver headers are **BSD-3-Clause**.
[`inv_imu_transport.h`](https://github.com/tdk-invn-oss/zephyr.hal_tdk/blob/330218a1f25cd58eab3b81eda7510e73525c2e76/icm456xx/imu/inv_imu_transport.h)
has explicit register-read/write callbacks;
[`inv_imu_driver.c`](https://github.com/tdk-invn-oss/zephyr.hal_tdk/blob/330218a1f25cd58eab3b81eda7510e73525c2e76/icm456xx/imu/inv_imu_driver.c)
contains `icm456xx_get_register_data`, FIFO configuration and 8/16/20-byte frame
decoding; `inv_imu_defs.h` supplies the types.

This can save future FIFO/parser work after matching the exact part. The existing
phone answers WHO_AM_I `0xe8`, while its stock name is `icm45631`; the audited HAL
does not establish that identity. Current polling already works, so no immediate
transport replacement is justified. Start with a callback-backed **host** model:
compare endian decoding and error propagation on captured-format vectors; reject
short reads before consuming samples. Audit signed-shift arithmetic and frame-size
bounds rather than treating vendor code as already hardened. Exclude embedded
eDMP/APEX binaries and optional algorithm/firmware paths entirely.

### 5. Fusion is a later math component, not native CoreMotion plumbing

Verified `xioTechnologies/Fusion` head:
`a8d7224f36a0ec82345ef49a3db50e65f8d3bab8`; inspected
[`LICENSE.md`](https://github.com/xioTechnologies/Fusion/blob/a8d7224f36a0ec82345ef49a3db50e65f8d3bab8/LICENSE.md) is **MIT**.
[`FusionRemap.h::FusionRemap`](https://github.com/xioTechnologies/Fusion/blob/a8d7224f36a0ec82345ef49a3db50e65f8d3bab8/Fusion/FusionRemap.h)
enumerates the 24 rigid axis alignments. This is useful as a host oracle for a
documented sensor-to-body transform; any accel gravity/sign convention remains
separate from physical mounting and must be measured. Current accel negation and
unchanged gyro signs are local hypotheses, not a reason to select a new remap.

Keep fusion in userspace or an isolated reference harness. Its floating-point
AHRS does not satisfy iOS private sensor matching, timestamps, calibration state
or deviceMotion delivery. Confirm raw callbacks and gyro scale first; importing
an AHRS now would add another unproved layer.

## Leads that do not presently save integration work

- Mainline `inv_icm45600` is already a local reference. The inspected linux-next
  pin `bd1ecbb61afefc6a8b876ccbc31e9228b44e9eab` has no `0xe8` / ICM45631 entry.
  Its FIFO and
  [`inv_sensors_timestamp.c`](https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git/tree/drivers/iio/common/inv_sensors/inv_sensors_timestamp.c?id=bd1ecbb61afefc6a8b876ccbc31e9228b44e9eab)
  are GPL-2.0-or-later references with Linux/IIO/interrupt dependencies. That
  timestamp estimator cannot infer hardware timing from our delayed 10 Hz polling.
- Bosch BMP/BMI and STM IMU drivers do not identify the fitted IMU, light or
  pressure parts. No exact TMD3743 driver/map was verified; APDS/TMD family names
  alone are insufficient. Generic IIO cannot provide the missing iOS adapter.
- Preserve the already reviewed RTC bounds implementation and read-only GET
  protocol. A generic Linux RTC driver does not replace the platform CPM owner.
- Existing raw-stream proof does not require AoC firmware. No stopped AoC task
  was reopened, and no alternative firmware-execution route was investigated.

## First integration-sized task

Package the existing MotionProbe into the established reversible RAM overlay,
verify registration/trust/permission on the host, and give the phone coordinator
one app-facing acceptance candidate. In parallel, implement a standalone
SPL07-003 coefficient/compensation host oracle from the verified MPL source and
an original MMC5616WA output decoder from the manufacturer map. These tasks
consume available code and documentation while leaving working transport intact.
Any XNU change later needs enabled BLAZER/feature gates, real ARM64 objects and
symbol inspection; no compile, native-app or physical success is claimed here.
