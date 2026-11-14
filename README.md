<!-- status:begin -->

<p align="center"><img src="docs/assets/hero.svg" alt="iOS 26 on Pixel 10 Pro: 59% of reachable hardware" width="100%"></p>

<p align="center"><img src="docs/assets/badge-progress.svg" alt="progress: 59%"> <img src="docs/assets/badge-target.svg" alt="device: Pixel 10 Pro"> <img src="docs/assets/badge-software.svg" alt="running: XNU 12377 · iOS 26"></p>
<p align="center"><a href="#progress">Progress</a> · <a href="#quick-start">Quick start</a> · <a href="#roadmap">Roadmap</a> · <a href="#how-it-boots">How it boots</a> · <a href="#documentation">Docs</a> · <a href="#contributing">Contributing</a> · <a href="#licensing">Licensing</a> · <a href="#credits">Credits</a></p>

<p align="center"><img src="docs/assets/stats.svg" alt="Measured on the phone" width="100%"></p>

<a id="progress"></a>
<h2 align="center">Every block. Tracked.</h2>
<p align="center"><b>59%</b> of 50 reachable features · updated 2026-11-14</p>

<p align="center"><img src="docs/assets/blocks.svg" alt="Progress by hardware block" width="100%"></p>

<p align="center"><sub>✅ Works on the phone 22 · 🟡 Partly working 9 · 🔧 Built, not run 1 · ⏳ In progress 8 · ❌ Not started 10 · 🚫 Likely out of reach 5</sub></p>

<details><summary><b>Every feature</b></summary>

| Block | Feature | Status |
| --- | --- | --- |
| **CPU** | 5 A725 cores | ✅ Ran 15 min under iOS at 1075 MHz, no kernel crash |
|  | CPU clock control | ✅ Governor clocks change under iOS; power-5 wrote 1536 MHz on both A725 domains and measured about 1535 MHz on all five cores |
|  | Higher clocks, up to the 3052 MHz top | 🟡 1536 MHz written and measured under iOS (power-5); higher sustained clocks remain unqualified. The old 3052 MHz probe was under one second, outside iOS |
|  | 2 A520 cores | 🟡 cpu0 audit found CAS workaround bit9 clear; both A520s remain excluded. Firmware query/reference sources pinned |
|  | X4 core | 🚫 For now: its errata aren't fixed |
|  | Idle sleep | ✅ WFI idling observed in power-5; full system suspend remains unproved |
| **Memory** | Memory and shared cluster clocks | ✅ Raised under iOS for 15 min; memory path up to 2.85x in a short test |
|  | RAM | ✅ 12.92 GiB under iOS for 15 min; memory test passed |
|  | The rest of the 16 GiB | ❌ Remaining RAM has not been qualified |
| **Display** | Full 1280x2856 picture | ✅ Scaled from 1125x2511 |
|  | 120 Hz | 🟡 120 Hz panel mode observed; completed iOS frame rate remains unmeasured |
|  | 60 Hz mode and frame sync | 🔧 Latest phone profile uses 60 Hz; actual frame cadence and completed-frame timing remain unmeasured |
|  | Variable refresh down to low rates | ❌ Automatic idle rate isn't built |
|  | Brightness | ✅ Owner saw the slider change brightness; integ-6 links three drags to successful DBV writes, without panel readback |
|  | HDR, peak brightness, colour calibration | ❌ Not assigned |
|  | Always-on display, self-refresh | ❌ Not assigned |
| **Graphics** | GPU power-on and ID | ✅ GPU answers: core id read from XNU, clean power-off |
|  | GPU firmware through Trusty | ✅ Firmware health, memory-writing compute and transfer jobs passed on the phone; rung 14a scheduled a render context with no faults (gpu-10), without rendering geometry |
|  | Metal drawing | ⏳ QuartzCore uses HMNativeMetalDevice without crashing backboardd for 120 s (metal-5), but the screen stays black. No GPU-composited frame; metal-9 is a built CPU compositor, not yet phone-tested |
|  | Video encode and decode | ❌ Not assigned |
| **Storage** | Reading | ✅ Multi-block reads, 0 errors |
|  | Writing (persistent /var) | 🟡 Old-root save/restore was physical; the GPT-resolved ios_data writer has host/QEMU bounds checks only, with no persistence boot on that partition |
|  | Maximum speed | ⏳ Patches being measured |
|  | Android/iOS boot chooser | ✅ Historical phone tests booted Android and iOS from the installed menu (r3); a current deployment requires fresh review under docs/COORDINATION.md |
|  | Isolated iOS partitions | ✅ Historical phone tests used 24 GiB ios_system and 8 GiB ios_data; the r6 root was flashed, hash-verified and booted. No current deployment is authorized by those receipts |
| **Input** | Touch | ✅ Owner taps open apps from Home; Settings responds at once (configd fix, int1) |
|  | Scripted taps and keys | ✅ integ-5 passed 83/83 UI-walk steps across 15 stock apps plus Settings; integ-7 passed 78/93, with physical input interference and other misses |
|  | Volume keys | ✅ Owner: volume keys work under iOS (pwr1) and switch the chooser menu |
|  | Power key | ✅ Owner: locks and wakes the phone under iOS (pwr1) |
|  | Tap to wake, palm rejection | ❌ Not assigned |
| **Connectivity** | Wi-Fi | 🟡 Kernel-initiated WPA2 join, gateway ICMP, DNS and HTTP passed; Settings shows the joined row (integ-5). Choosing and joining a network from Settings is unproved |
|  | Bluetooth | 🟡 bluetoothd exchanged HCI commands and received 1000 LE advertising events with no respawn in bt-8; controller power-on, device discovery in Settings and pairing remain unproved |
|  | Cellular | ⏳ S5400 PCIe link and ROM handshake passed through rung 8, with no firmware loaded or RF. BL1 handoff (modem-5) is built, not phone-tested; no cellular service |
|  | SIM, eSIM | ⏳ No qualified SIM access or native cellular service yet; depends on modem transport and boot |
|  | GPS | ❌ Not assigned |
|  | NFC | 🟡 Controller discovery runs and the 19.2 MHz clock output was tested; no tag was read, including the attended test. Apple Pay remains out of reach |
|  | UWB | ❌ Not assigned; presence unconfirmed |
| **USB** | Fastboot and logs | ✅ |
|  | Live console | ✅ Combined p32: 879,706 live bytes matched the final RAM mirror, zero mismatches/loss; final tail retained separately |
|  | Link to the Mac | ⏳ Console/input transport works; native mux pairing and app-service connection remain unproved |
|  | Network over USB | ⏳ The IONetworkStack stand-in ran on the phone; the ECM interface has no physical RX/TX evidence. Host-interactive USB-net and KDP are parked |
|  | USB host, video out | 🚫 No host stack in open XNU |
| **Audio** | Speakers, microphones | ⏳ No physical audio output or capture. The QEMU device has no sink; phone audio depends on AoC IPC and service discovery |
|  | Haptics | ✅ Owner: a buzz on touch under iOS (pwr1) |
| **Sensors** | Accelerometer, gyro, proximity, light, barometer | 🟡 CoreMotion read 833 accel and 833 gyro samples (sensors-3). Safari drew in landscape once; the return to portrait is unproved. Proximity/light/barometer only acknowledged on I2C |
|  | Always-on chip | ⏳ Firmware authenticates through rung 3, but rung 4 has no IPC response or service census. Cause unknown; the socversion theory was refuted. audio-9 is a built interrupt diagnostic, not phone-tested |
| **Power** | Temperature and thermal guard | ✅ Live temperatures; guard panic verified at a test limit. SweetSensorHub: thermalmonitord binds all 19 published services incl. battery TG0B (32.7 °C) |
|  | Battery gauge | ✅ Owner: 95% shown in the status bar and Control Center (pwr1) |
|  | Charging control | ❌ Read-only reporting saw USB cc and done states on the phone; changing charge limits remains unimplemented |
|  | Wireless charging | ❌ Not assigned |
|  | Real date and time | ✅ Owner: correct local time shown (8.20 at 20:20, pwr1) |
| **Cameras** | Cameras, flash | 🟡 Flash torch lit for 2000 ms on the phone; camera PMIC ID read. No image sensor ID or camera frame |
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

**Updated 2026-11-14; latest physical results are from November 11–12.** iOS 26 reaches Home and runs stock apps on the Pixel 10 Pro. In [integ-5](devices/blazer/evidence/a7-integ-r5.txt), Home was ready in 80.6 seconds and the scripted walk passed all 83 steps across 15 stock apps plus Settings, including Photos and Maps. That boot still logged translationd and bluetoothd crashes. The later combined run, integ-7, reached Home in 76 seconds but passed 78/93 steps; it did not repeat the clean walk.

**Connectivity and sensors.** Wi-Fi now completes WPA2 join and passes gateway, DNS and HTTP checks; Settings shows the joined network. The kernel initiates that join, so joining a different network from Settings remains unproved. [bt-8](devices/blazer/evidence/a7-bt11-tx2.txt) received 1000 LE advertising events with one bluetoothd execution and no crash, but Settings discovery and pairing remain unproved. [CoreMotion read 833 accelerometer and 833 gyro samples](devices/blazer/evidence/a7-sensors3-r1.txt). Safari drew in landscape once; the return to portrait still needs an attended check. The CPU governor [wrote 1536 MHz and measured about 1535 MHz on all five A725 cores](devices/blazer/evidence/a7-power5-cap13-r1.txt); higher clocks and A520 admission remain unqualified.

**GPU / Liquid Glass.** The PowerVR GPU executes memory-writing compute and transfer jobs, and its firmware has scheduled a render context. The custom Metal device is visible to QuartzCore: [metal-5](devices/blazer/evidence/metal-probe-r5.txt) ran backboardd for 120 seconds without a crash, but drew a black screen. No GPU-rendered geometry or composited frame has been demonstrated. The built metal-9 candidate gives textures real memory and executes CoreAnimation draws on the CPU; it has host/QEMU checks only, and has not drawn Home on the phone. GPU compositing still needs a render job and a shader path.

**Still open.** AoC firmware authenticates, but never answers in its IPC area; there is no service census or audio. The cause is unknown, and the earlier socversion theory was refuted by stock Android logs. The modem reached its ROM handshake without loading firmware or emitting RF; BL1 handoff is built but untested on the phone. NFC discovery runs without a tag read. The flash torch works, but no camera frame has been captured. Persistence on ios_data, round-trip rotation, and a fresh Android return check remain open.

The latest candidates — apps-4, audio-9, modem-5, metal-9 and wifi-3 — have **no new physical results**. Prior boot and storage receipts describe historical tests; they do not establish the phone's current installation or authorize another deployment. Read [NOTES.md](NOTES.md) for the result audit and [docs/COORDINATION.md](docs/COORDINATION.md) for current admission and storage rules.

Driver status and bounded physical receipts live in [devices/blazer/](devices/blazer/); [docs/scoreboard.yaml](docs/scoreboard.yaml) tracks each subsystem's next missing rung. The percentage above is a weighted planning checklist, not release readiness or a claim that every feature worked together in one boot.

<!-- latest-checkpoint:end -->

## Quick start

Everything here runs on a clean clone and never touches a phone:

```sh
git clone --branch ios26 https://github.com/TheAndersMadsen/ios-on-pixel-10.git
cd ios-on-pixel-10
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

- Repeat the daily-image UI walk without translationd crashes or input interference; integ-5 passed 83/83 steps, integ-7 passed 78/93
- Test the built metal-9 CPU compositor on the phone; GPU compositing still needs a render job and a shader path
- Read the audio-9 Trusty interrupt diagnostic; AoC authentication passes, but no IPC or service census has appeared
- Take Bluetooth from chip-level LE scan reports to controller power-on, a Settings device list and pairing
- Verify a Wi-Fi join initiated from Settings; kernel-initiated WPA2 join, DNS and HTTP already pass
- Finish the attended landscape-to-portrait rotation check and return-to-Android check

**Next**

- Test the built modem-5 BL1 handoff; the proven ROM handshake has loaded no modem firmware and emitted no RF
- Verify persistent real settings on ios_data across reboots; the GPT-bounded writer has host/QEMU evidence only
- Validate display sleep and wake, completed-frame timing, and USB ECM networking
- Qualify sustained higher CPU clocks; 1536 MHz was written and measured, higher sustained clocks under iOS remain unqualified

**Later**

- Complete GPU rendering, shader compilation and CoreAnimation compositing on the GPU
- Bring up speaker and microphone transport after AoC IPC and service discovery work
- Qualify A520 cores and RAM beyond the working 12.92 GiB
- Bring up cellular service, SIM/eSIM and GPS; loading the main modem image needs a separate owner decision
- Read an NFC tag, capture a camera frame, and qualify the remaining sensors and standby behavior

**Likely out of reach**

- X4 core, USB host, video out, Fingerprint, Face ID, Secure enclave, Activation, iMessage, App Store purchases

<!-- roadmap:end -->

<!--
Screenshots: intentionally empty. Frames of iOS show Apple's UI, which is Apple's copyright, so none are committed.
Add one here only if the owner provides it or it is a QEMU frame, and only after checking it holds no Apple UI,
serial number, IMEI, MAC address or account name.
-->

## How it boots

This project ports Apple's open-source XNU kernel to the Pixel 10 Pro (`laguna`, board `blazer`, Tensor G5), running XNU 12377 and the iOS 26 userland. Development uses temporary RAM boots through `fastboot boot`. The chooser design below was exercised in earlier phone tests; it does not describe a current deployment:

```
ABL (stock Google bootloader, unlocked)
  -> temporary boot image (fastboot boot)
     -> shim chooser: menu, volume keys, 5 s default to Android        (shim/chooser.c)
        |- Android: decompress the stock kernel carried in the image,
        |           jump at EL2 with ABL's own FDT, ramdisk and bootconfig
        `- iOS:     XNU Mach-O + Apple Device Tree + boot-args
                    -> tested root on ios_system
                       /var writer restricted to ios_data; physical persistence unproved
                       -> dyld + shared cache -> launchd -> daemons -> UI
```

The shim and XNU are designed to leave Android's partitions untouched. New deployment or storage changes require a fresh reviewed plan, verified backups and explicit owner approval under [docs/COORDINATION.md](docs/COORDINATION.md); [docs/DUALBOOT.md](docs/DUALBOOT.md) records the storage design.

A live USB console streams kernel and injected userland diagnostics during iOS boots. Screenshots, crash probes, user stacks and per-driver queries support the in-image debug loop; [docs/DEBUG-LOOP.md](docs/DEBUG-LOOP.md) describes the tools. Reserved log RAM at `0x95200000` supplies post-boot diagnostics after the phone returns to fastboot.

## Repository layout

| Path | What |
| --- | --- |
| `AGENTS.md` | How to work on this repository |
| `NOTES.md` | Short current state, blockers, canonical artifacts and task routes |
| `HANDOFF.md` | Immediate next actions only |
| `BLAZER.md` | Pointer to current notes and archived hardware history |
| `docs/` | Build guide, licensing, coordination rules, subsystem scoreboard and generated README images |
| `devices/blazer/` | Per-driver status, incremental kernel configs and bounded physical receipts |
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

Start at [docs/README.md](docs/README.md). [NOTES.md](NOTES.md) holds current results; [devices/blazer/device.conf](devices/blazer/device.conf) records each driver's proof and limits. See [docs/DEBUG-LOOP.md](docs/DEBUG-LOOP.md) for live debugging and [docs/UNIXNU.md](docs/UNIXNU.md) for the independent UniXNU-compatible device record. Changes and results by date are in [CHANGELOG.md](CHANGELOG.md).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) covers how boots are run and what must never be committed. Conduct: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Security: [SECURITY.md](SECURITY.md).

## Licensing

**No repository-wide licence is granted.** It holds code from several origins, some with no licence at all, so there is no `LICENSE` file. [docs/LICENSING.md](docs/LICENSING.md) says which paths are what, and what must be audited before any public release.

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
