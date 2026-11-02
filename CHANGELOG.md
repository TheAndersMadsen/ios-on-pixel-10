# Changelog

Notable changes and results, newest first, from git history and the attempt records. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There are no releases. Times are CET; every phone result is one boot of one phone unless it says otherwise.

## Unreleased

### Added
- Repository standards: CI, a check on tracked files with an optional pre-commit hook, issue and pull request templates, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `docs/LICENSING.md` and a docs index.
- README: badges, navigation, Quick start, and a roadmap generated from `docs/status.json`.

### Results on the phone, 2026-11-02
- `gpu-tipc-r1` 03:22: XNU reached the GPU app in Trusty over TIPC. The app connected and replied to a ping with a refusal (result 180). No firmware loaded.
- `wifi-stage3-r1` 03:17: BCM4390 firmware booted, rings in host memory, and `wlc_ver`, `GET_REVINFO` and `ver` answered with status 0. Probe boot, ended on purpose. No scan or join.
- `sensor-i2c-r1` 03:15: the motion chip answered its ID read, `0xe8` at address `0x68`. Rails were turned off again. No data stream.
- `gpu-stage1-r1` 03:07: the power firmware reported the GPU domain on. No GPU register read.
- `hold-high-r1` 03:03: cpu2 alone, before XNU, held each step up to 3052.8 MHz, measured by PMU, peak 36 C. Each step is under a second.
- `hold-pair-r2` 03:23: three A725s measured 1536 MHz together; the two domains ran apart. Short test.
- `hold-dsu-r1` 03:04: memory-path loop 2.85x faster with floors and the DSU at its highest tested level. cpu0, seconds, before XNU.
- `hold-dom2-r1` 03:01: the second A725 domain follows votes to 1536 MHz. Short test.
- `phone-all-r1` 02:51: five A725s at 533 MHz under iOS for about 8.5 minutes, to the owner's long press. Memory floors and the DSU step held under XNU for the first time, XNU saw 6.95 GiB, peak 37 C, thermal guard armed at 85 C. Touch opened an app.
- `ram-short-r1` 02:46: 6 GiB passed its test, kernel only.
- `floor-probe-r1` 02:43: memory and DSU floors took their steps, before XNU.
- `t2-p14-r1` 02:32: thermal guard read the temperature and its panic route worked, using a deliberately low limit.

### Changed
- `docs/status.json` and the README's figures now reflect the results above. Overall estimate unchanged at 36%: gains in CPU, memory, GPU power and Wi-Fi are offset by moving two rows, GPU firmware and haptics, from built to in progress.

## 2026-11-02

- Rewrote the README with animated hardware progress (`aae984f`).
- Brought the shim, tools and build docs up to the fleet's state, and added `docs/BUILD.md` (`fab03af`).
- Recorded the touch crash, and clock, core, keys and Wi-Fi probe results (`7b9aaf2`).
- **Real touch working on iOS 26 on the phone** (`220508c`).
- Recorded the first iOS boot's capture and the owner's hardware decisions (`82ddb11`).

## 2026-11-01

- **iOS 26 reached the home screen on the phone** (`e8cc6a0`), after the whole-image check passed (`daaab6d`) and the root was written with the owner's approval (`990f359`).
- iOS 26 reached the lock screen in QEMU with no GPU (`326875d`).
- Touch chip identified and reports flowing (`86ecfad`, `c17e7e4`).
- **XNU 12377 booted on the phone** (`31bdaa1`), and the kernel scanned out at full size (`ac63c2c`).
- Chose tegu's series as the iOS 26 kernel base (`712b7b1`, `03b60e6`), and first linked XNU 12377 (`bb56372`).
- Started the iOS 26 line from the proven hardware work (`eea95fc`).
- Earlier the same day, on iOS 16's kernel: launchd ran from the full root over UFS (`5b4fe81`), SpringBoard and backboardd ran (`5d25da7`), first native frames reached the panel (`7d3310d`, `78d0126`), HS gear 4 (`83c3279`), 16 KiB pages and 4 GiB (`fcd735a`), first UFS link and commands (`6bb84ba`, `861b983`).
- Organised the Pixel 10 Pro port along the lines of `ios-tegu` (`32364ce`).
