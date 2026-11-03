# Read-only Android queries for the sensors lane (coordinator runs them)

All read-only: no writes, no setprop, no service restarts, no sensor enable. Run on Android slot b with
`ANDROID_SERIAL` set; save each output under `research/ios26-sensors-r1/android/out/<name>.txt` (keep the
serial number out of git: `sed -E 's/[0-9A-Z]{10,}/<serial>/g'` before saving).

| Name | Command | Why |
|---|---|---|
| sensorservice | `adb shell dumpsys sensorservice` | Sensor list with vendor/name/version/range/resolution, and the recent-event ring: reference values for accel (m/s^2), mag (uT), baro (hPa), light (lux), prox (cm) to check iOS conversions against |
| contexthub | `adb shell dumpsys contexthub` | Whether CHRE runs on AoC and which nanoapps; confirms the hub path Android uses |
| sensors-hal | `adb shell 'ls -l /vendor/lib64/hw/ \| grep -i sensor; cat /vendor/etc/sensors/hals.conf; getprop \| grep -iE "sensor\|chre\|usf\|aoc"'` | Which HAL (USF, eldi, dynamic) is live |
| buses | `adb shell su -c 'ls /sys/bus/i2c/devices /sys/bus/i3c/devices /sys/bus/iio/devices /sys/bus/spi/devices 2>&1'` | Confirms the AP kernel binds no IMU/mag/ALS/baro driver (sensors are AoC-side) |
| modules | `adb shell su -c 'lsmod \| grep -iE "aoc\|usf\|sensor\|i3c\|chre\|iio\|ldaf\|tof"'` | Same, from the module list |
| aoc-dt | `adb shell su -c 'for f in compatible sensor_power_list chre-supported status; do printf "%s: " $f; tr "\\0" " " < /proc/device-tree/aoc@9000000/$f 2>&1; echo; done'` | Live DT matches the captured laguna.dts |
| aoc-pins | `adb shell su -c 'cat /sys/kernel/debug/pinctrl/b400000.pinctrl*/pinmux-pins 2>/dev/null \| sed -n "30,40p;64,72p;84,90p"'` | Owner and function of pads 33-36, 67-68, 85-86 while Android runs (expect AoC functions) |
| aoc-state | `adb shell su -c 'ls /sys/devices/platform/*aoc*/ 2>&1; cat /sys/devices/platform/*aoc*/aoc_*/revision 2>/dev/null'` | AoC firmware/driver state names for the plan's hub option |
| persist-cal | `adb shell su -c 'ls -lR /mnt/vendor/persist/sensors 2>&1 \| head -80'` | Per-unit factory calibration files (prox baseline, ALS coefficients, mag/baro cal): names and sizes only |
| display-lux | `adb shell dumpsys display \| grep -iE "lux\|ambient\|AutomaticBrightness" \| head -40` | Android's lux and brightness mapping, a reference for CoreBrightness later |
| sensor-ids | `adb shell dumpsys sensorservice \| grep -iE "icm45631\|mmc5616\|tmd3743\|spl07\|vd6282\|mlx90632"` | Confirms the registry's part names are the live ones |

Optional, only if the coordinator agrees (it enables sensors briefly; still read-only on disk):
`adb shell dumpsys sensorservice` once with the phone face up on the desk and once in portrait upright, to
fix the accelerometer sign convention against Android's (Android +9.8 m/s^2 on z face up; iOS -1 g).
