<!-- status:begin -->

<p align="center"><img src="docs/assets/hero.svg" alt="iOS 26 on Pixel 10 Pro: 56% of reachable hardware" width="100%"></p>

<p align="center"><img src="docs/assets/badge-progress.svg" alt="progress: 56%"> <img src="docs/assets/badge-target.svg" alt="device: Pixel 10 Pro"> <img src="docs/assets/badge-software.svg" alt="running: XNU 12377 · iOS 26"></p>
<p align="center"><a href="#progress">Progress</a> · <a href="#quick-start">Quick start</a> · <a href="#roadmap">Roadmap</a> · <a href="#how-it-boots">How it boots</a> · <a href="#documentation">Docs</a> · <a href="#contributing">Contributing</a> · <a href="#licensing">Licensing</a> · <a href="#credits">Credits</a></p>

<p align="center"><img src="docs/assets/stats.svg" alt="Measured on the phone" width="100%"></p>

<a id="progress"></a>
<h2 align="center">Every block. Tracked.</h2>
<p align="center"><b>56%</b> of 49 reachable features · updated 2026-11-04</p>

<p align="center"><img src="docs/assets/blocks.svg" alt="Progress by hardware block" width="100%"></p>

<p align="center"><sub>✅ Works on the phone 21 · 🟡 Partly working 7 · 🔧 Built, not run 1 · ⏳ In progress 9 · ❌ Not started 11 · 🚫 Likely out of reach 6</sub></p>

<details><summary><b>Every feature</b></summary>

| Block | Feature | Status |
| --- | --- | --- |
| **CPU** | 5 A725 cores | ✅ Ran 15 min under iOS at 1075 MHz, no kernel crash |
|  | CPU clock control | ✅ Governor ran 15 min under iOS: 533–1075 MHz on demand, 125 clock reads within 2%, 33–35 °C |
|  | Higher clocks, up to the 3052 MHz top | 🟡 Governor frames stage proven under UI load: 98% of a busy window at the proven 1075 MHz cap (perf1). Above-1075 acceptance and A520 admission still pending |
|  | 2 A520 cores | 🟡 cpu0 audit found CAS workaround bit9 clear; both A520s remain excluded. Firmware query/reference sources pinned |
|  | X4 core | 🚫 For now: its errata aren't fixed |
|  | Idle sleep | ✅ By code reading: cores already idle in WFI |
| **Memory** | Memory and shared cluster clocks | ✅ Raised under iOS for 15 min; memory path up to 2.85x in a short test |
|  | RAM | ✅ 12.92 GiB under iOS for 15 min; memory test passed |
|  | The rest of the 16 GiB | ❌ Not assigned |
| **Display** | Full 1280x2856 picture | ✅ Scaled from 1125x2511 |
|  | 120 Hz | 🟡 120 Hz panel mode observed; completed iOS frame rate remains unmeasured |
|  | 60 Hz mode and frame sync | 🔧 Latest phone profile uses 60 Hz; actual frame cadence and completed-frame timing remain unmeasured |
|  | Variable refresh down to low rates | ❌ Automatic idle rate isn't built |
|  | Brightness | ✅ Owner: the Settings slider visibly changes the panel brightness (pwr1) |
|  | HDR, peak brightness, colour calibration | ❌ Not assigned |
|  | Always-on display, self-refresh | ❌ Not assigned |
| **Graphics** | GPU power-on and ID | ✅ GPU answers: core id read from XNU, clean power-off |
|  | GPU firmware through Trusty | ✅ Health PASS (gpu2); rungs 8-9 executed on the phone: MMUCACHE 0x807 ran in firmware, UFO fence in order, 0 faults (gpu5/gpu6). Rung 10 built and queued |
|  | Metal drawing | ⏳ CA diagnostic: no AGXAccelerator exists in the IORegistry, so CoreAnimation selects the software context. Native path mapped; coremem S1 and rung 10 (page tables, MMUCACHE, first memory-writing job) built, booting |
|  | Video encode and decode | ❌ Not assigned |
| **Storage** | Reading | ✅ Multi-block reads, 0 errors |
|  | Writing (persistent /var) | 🟡 Saves and restore across reset verified on the old root; writer now bound to the GPT-resolved ios_data (host-tested), not yet run there |
|  | Maximum speed | ⏳ Patches being measured |
|  | Android/iOS boot chooser | ✅ Installed on boot_b (int1, readback verified): Android by timeout PASS; owner booted iOS from a real power-on through the installed menu (r3) |
|  | Isolated iOS partitions | ✅ ios_system 24 GiB and ios_data 8 GiB on the phone; ios_system flashed, read back on the phone (hash match) and booted to Home (r3) |
| **Input** | Touch | ✅ Owner taps open apps from Home; Settings responds at once (configd fix, int1) |
|  | Scripted taps and keys | 🟡 Remote HOME visibly worked; TAP dispatched but required manual app recovery. No automatic retry or clean TAP acceptance |
|  | Volume keys | ✅ Owner: volume keys work under iOS (pwr1) and switch the chooser menu |
|  | Power key | ✅ Owner: locks and wakes the phone under iOS (pwr1) |
|  | Tap to wake, palm rejection | ❌ Not assigned |
| **Connectivity** | Wi-Fi | 🟡 BCM4390 under iOS: scan found 26 networks, authentication and association OK; the WPA2 4-way handshake fails. No packet traffic yet |
|  | Bluetooth | 🟡 Native HCI attached on the phone (HCI 6.0 Broadcom, 4 Mbaud RTS/CTS, Read Local Version status 0); keychain wrap/unwrap PASS (B1). Settings pairing needs radio transmit: owner-approved, pairing image pending |
|  | Cellular | ⏳ S5400 identified; pad probe only. PCIe0, modem boot and native CommCenter service remain unfinished |
|  | SIM, eSIM | ⏳ No qualified SIM access or native cellular service yet; depends on modem transport and boot |
|  | GPS | ❌ Not assigned |
|  | NFC | ❌ Reading tags possible at most; Apple Pay is out of reach |
|  | UWB | ❌ Not assigned; presence unconfirmed |
| **USB** | Fastboot and logs | ✅ |
|  | Live console | ✅ Combined p32: 879,706 live bytes matched the final RAM mirror, zero mismatches/loss; final tail retained separately |
|  | Link to the Mac | ⏳ Console/input transport works; native mux pairing and app-service connection remain unproved |
|  | Network over USB | ⏳ ECM source integrated and host-tested; review and physical binding/traffic gates remain open |
|  | USB host, video out | 🚫 No host stack in open XNU |
| **Audio** | Speakers, microphones | ⏳ QEMU test queued; depends on always-on chip |
|  | Haptics | ✅ Owner: a buzz on touch under iOS (pwr1) |
| **Sensors** | Accelerometer, gyro, proximity, light, barometer | ⏳ Physical: accel and gyro samples through 2400, changing orientation; proximity/light/barometer and app integration unproved. SweetSensorHub publishes 19 temperature services, all bound by thermalmonitord |
|  | Always-on chip | ⏳ First phone run panicked in the carve zeroing (DC-ZVA alignment fault on the device-class map); root-caused, the aoc6 fix is next |
| **Power** | Temperature and thermal guard | ✅ Live temperatures; guard panic verified at a test limit. SweetSensorHub: thermalmonitord binds all 19 published services incl. battery TG0B (32.7 °C) |
|  | Battery gauge | ✅ Owner: 95% shown in the status bar and Control Center (pwr1) |
|  | Charging control | ❌ Left at the bootloader's settings |
|  | Wireless charging | ❌ Not assigned |
|  | Real date and time | ✅ Owner: correct local time shown (8.20 at 20:20, pwr1) |
| **Cameras** | Cameras, flash | 🚫 Likely months: sensor details aren't public |
| **Security** | Fingerprint, Face ID | 🚫 Tied to Apple's security chip |
|  | Secure enclave | 🚫 Apple SEP is absent; a software key store now wraps and unwraps keys on the phone (B1). Native data-protection support remains incomplete |
| **Apple services** | Activation, iMessage, App Store purchases | 🚫 Need a real iPhone's identity |

<sub>Scores: works on the phone 100%, partly working 60%, built, not run 35%, in progress 20%, not started 0%. A planning estimate, not a benchmark. Rebuild with `python3 -I tools/readme_status.py` after editing `docs/status.json`.</sub>

</details>

> **What this is.** An experimental research bring-up on the owner's own phone, not a product. Not affiliated with or endorsed by Apple or Google. No Apple software or firmware is distributed here. Apple's security model is largely switched off, so the phone isn't safe for real data.

<!-- status:end -->

---

<!-- latest-checkpoint:begin -->

## Current checkpoint

**Updated 2026-11-04 (second session).** Dual boot is installed (Android untouched), and iOS 26 is usable by hand — touch, full-screen scaling, the volume and power keys, haptics, the brightness slider, and the real battery level and clock. A structured live-debug platform now drives the bring-up: a streaming kernel console, unattended screenshots, a user-stack sampler, per-daemon log mirroring, automatic crash triage (`tools/crashdoc.py`), evidence-based status probes (`tools/probe_eval.py`), a QEMU pre-flight, and one CLI over it all (`tools/hk`) feeding a shared, auto-generated backlog (`docs/debug/BACKLOG.md`).

**Proven on the phone this session:** 120 Hz ProMotion (65 completed frames/s during scroll, past the old ~40 cap); the Settings>About, Messages/BlastDoor and AccessibilityUIServer crashes fixed live; a restored root (r5) that puts back the stock app resources an earlier prune removed (Phone, About, Messages, FaceTime, Spotlight), flashed and verified on the partition; a consolidated image (int4) carrying the crash fixes, 120 Hz, the full 16 GiB memory map and a read-only charger reporter in one boot; **and, in the second session:** the backboardd crash loop fixed by dropping the soft-blur compositor material (int5-r2: 0 LIBMALLOC/usertrap crashes over a full 18-minute window at Home, where int5 crashed in 3 execs); the CPU governor's new frames stage holding the proven 1075 MHz cap for 98% of a busy window under sustained UI load (int4-perf1, with SpringBoard's telephony-restart error flood down 96%); and SweetSensorHub's 19 published temperature services all bound and polled by thermalmonitord, including the battery gauge TG0B (sensorhub1). Bluetooth attached its native HCI on the phone (HCI 6.0 Broadcom, 4 Mbaud RTS/CTS).

**GPU / Liquid Glass.** The GPU is an Imagination PowerVR DXT (BVNC 71.2.2448.1212). Its firmware boots and passes health, and the first real command-stream steps are now executed on the phone: MMUCACHE 0x807 ran in firmware with the UFO fence advancing in order and zero faults (rungs 8–9, gpu5/gpu6). A CA diagnostic answered why the iOS 26 glass still renders flat: no `AGXAccelerator` exists in the IORegistry, so CoreAnimation selects the software context. The mapped native path — coremem init -> command stream -> a custom `AGXAccelerator` with a native Metal plugin -> CoreAnimation compositing — has its next rung (10: client page tables, MMUCACHE, the first memory-writing job) built and queued for its on-phone boot.

**Built and queued for on-phone tests:** NFC (the reset pulse and I2C open), Bluetooth pairing in Settings (radio transmit owner-approved), the Spotlight spin fix (root-caused this session: an `aks_get_device_state` poll at 175/s when the device reads unlocked), the camera flash LED, USB host mode and audio stage one. The first AoC phone run panicked in the carve zeroing (a DC-ZVA alignment fault on the device-class mapping) — root-caused, the aoc6 fix is next; the modem's rung 5 stopped safely because the endpoint configures itself after link training. Native Metal, Wi-Fi traffic, cellular and audio are still incomplete.

Read [NOTES.md](NOTES.md) for current state and [HANDOFF.md](HANDOFF.md) for next actions. The
percentage above is a planning checklist, not release readiness.

<!-- latest-checkpoint:end -->

## Quick start

Everything here runs on a clean clone and never touches a phone:

```sh
git clone https://github.com/TheAndersMadsen/ios-on-pixel-10.git && cd ios-on-pixel-10
.github/scripts/check_tracked.py      # no dumps, firmware, Apple files or identifiers
.github/scripts/ci-tests.sh           # what CI runs: host tests and a README freshness check
python3 -I tools/readme_status.py     # rebuild the README's status and images from docs/status.json
```

Python 3.12 or newer and a C compiler at `/usr/bin/cc`.

A phone image is a different matter. It needs inputs that are never committed, such as Apple artifacts, the kernel series and the phone's own device tree, so **a clean clone can't build one.** [docs/BUILD.md](docs/BUILD.md) lists each input and its pinned hash, then the build and boot commands. Read [CONTRIBUTING.md](CONTRIBUTING.md) before any boot.

## Roadmap

Generated from `docs/status.json`. Order can change with each physical result.

<!-- roadmap:begin -->

**Now**

- Backboardd crash loop fixed live (softblur material removed, int5-r2); the Spotlight spin is root-caused (aks_get_device_state poll) - ship its fix and measure frame completion
- GPU command stream: rungs 8-9 executed on the phone; land rung 10 (page tables + first memory-writing job), then publish the AGXAccelerator for Metal
- Qualify interactive scripted TAP/HOME behavior; screenshots already run unattended
- Get the Wi-Fi WPA2 handshake through (RX-starvation fix built, boot pending) and pair Bluetooth in Settings (transmit owner-approved, image pending)
- Make the Phone app (now opens, partly) and Settings > About fully usable, then more stock-app launches

**Next**

- Verify persistent real settings on ios_data across reboots
- Validate display sleep and wake
- Repair and physically qualify USB ECM networking, then native mux pairing
- Complete CPU health and thermal step-down before higher clocks or A520 admission

**Later**

- Complete GPU command execution, shader compilation and Metal rendering
- Integrate audio (speakers, microphones) with actual transport and physical acceptance
- Establish ownership of RAM beyond the working 12.92 GiB
- Complete Wi-Fi association, Bluetooth, cellular and GPS
- Validate sleep, standby and remaining peripherals

**Likely out of reach**

- X4 core, USB host, video out, Cameras, flash, Fingerprint, Face ID, Secure enclave, Activation, iMessage, App Store purchases

<!-- roadmap:end -->

<!--
Screenshots: intentionally empty. Frames of iOS show Apple's UI, which is Apple's copyright, so none are committed.
Add one here only if the owner provides it or it is a QEMU frame, and only after checking it holds no Apple UI,
serial number, IMEI, MAC address or account name.
-->

## How it boots

This project ports Apple's open-source XNU kernel to the Pixel 10 Pro (`laguna`, board `blazer`, Tensor G5), running XNU 12377 and the iOS 26 userland. Development uses temporary RAM boots through `fastboot boot`. The dual-boot design adds a chooser in front of both systems:

```
ABL (stock Google bootloader, unlocked)
  -> boot image (fastboot boot today; boot_b once installed)
     -> shim chooser: menu, volume keys, 5 s default to Android        (shim/chooser.c)
        |- Android: decompress the stock kernel carried in the image,
        |           jump at EL2 with ABL's own FDT, ramdisk and bootconfig
        `- iOS:     XNU Mach-O + Apple Device Tree + boot-args
                    -> root on ios_system, /var persistence on ios_data only
                       -> dyld + shared cache -> launchd -> daemons -> UI
```

Android's partitions are never written by the shim or by XNU. Storage changes are made only by the owner, from a reviewed plan with byte-exact rollback copies ([docs/DUALBOOT.md](docs/DUALBOOT.md)).

There is no serial console. The diagnostics live in reserved RAM at `0x95200000` and are read from fastboot after the phone returns there.

## Repository layout

| Path | What |
| --- | --- |
| `AGENTS.md` | How to work on this repository |
| `NOTES.md` | Short current state, blockers, canonical artifacts and task routes |
| `HANDOFF.md` | Immediate next actions only |
| `BLAZER.md` | Pointer to current notes and archived hardware history |
| `docs/` | Build guide, licensing, status data and README images |
| `shim/` | Boot shim |
| `tools/` | Build, boot and log tools |
| `xnu/` | Build notes; `ios16-base/patches` is the parts source for the 12377 port |
| `.github/` | CI, the check on tracked files, and issue and pull request templates |
| `backup/` | Stock boot images; not committed |
| `research/` | Evidence, sources, the iOS 26 kernel series and earlier documents; not committed |

## Key hardware facts

- SoC Tensor G5 (`google,lga-blazer`). Boot-state truth is in `/proc/bootconfig` (`device_state=unlocked`), not `getprop`.
- UFS: Samsung KLUDG4UHGC (128 GB), host controller at `0x3c400000`.
- USB: DWC3 at `0x0c400000`, wrapper at `0x0c450000`.
- Log RAM: ramoops at `0x95200000`, pmsg at `0x95400000`.

More in [`NOTES.md`](NOTES.md).

## Documentation

Start at [docs/README.md](docs/README.md). Changes and results by date are in [CHANGELOG.md](CHANGELOG.md).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers how boots are run and what must never be committed. Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security: [SECURITY.md](SECURITY.md).

## Licensing

**This repository is private and no licence is granted.** It holds code from several origins, some with no licence at all, so there is no `LICENSE` file. [docs/LICENSING.md](docs/LICENSING.md) says which paths are what, and what must be audited before any public release.

## Credits

This work stands on other people's, and listing a project here doesn't mean it endorses this one.

- **Apple:** the XNU open-source releases, and dyld's during the iOS 16 work. The iOS userland is proprietary and stays out of this repository.
- **[ios-tegu](https://github.com/dgigantino/ios-tegu):** the base of the local iOS 26 kernel series, and the origin of the shim's EL2 to EL1 entry sequence, payload format and USB diagnostic protocol. It has no licence, which is the main reason this one can't go public as it stands.
- **HakiOS** (`oosexgang/hackios-xnu-kernel`, `hackios-xnu-userland`): upstream porting base, in the iOS 16 patches and tools.
- **dada:** a parts source for the local kernel series, which isn't tracked here.
- **felix:** the loader work behind a pinned local copy of `avbtool`, and the shim's panic screen style.
- **Google and the Android Open Source Project:** `tools/mkbootimg.py` (Apache-2.0), and Pixel kernel sources.
- **GrapheneOS** kernel trees and **Linux:** vendor sources read for hardware facts and used to generate tables in `shim/`; `shim/tgl_ufs_link.c` carries Linux and Google's UFS code under GPL-2.0-only.

Origins, per path: [docs/LICENSING.md](docs/LICENSING.md).
