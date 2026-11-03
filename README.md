<!-- status:begin -->

<p align="center"><img src="docs/assets/hero.svg" alt="iOS 26 on Pixel 10 Pro: 47% of reachable hardware" width="100%"></p>

<p align="center"><img src="docs/assets/badge-progress.svg" alt="progress: 47%"> <img src="docs/assets/badge-target.svg" alt="device: Pixel 10 Pro"> <img src="docs/assets/badge-software.svg" alt="running: XNU 12377 · iOS 26"></p>
<p align="center"><a href="#progress">Progress</a> · <a href="#quick-start">Quick start</a> · <a href="#roadmap">Roadmap</a> · <a href="#how-it-boots">How it boots</a> · <a href="#documentation">Docs</a> · <a href="#contributing">Contributing</a> · <a href="#licensing">Licensing</a> · <a href="#credits">Credits</a></p>

<p align="center"><img src="docs/assets/stats.svg" alt="Measured on the phone" width="100%"></p>

<a id="progress"></a>
<h2 align="center">Every block. Tracked.</h2>
<p align="center"><b>47%</b> of 49 reachable features · updated 2026-11-03</p>

<p align="center"><img src="docs/assets/blocks.svg" alt="Progress by hardware block" width="100%"></p>

<p align="center"><sub>✅ Works on the phone 12 · 🟡 Partly working 14 · 🔧 Built, not run 1 · ⏳ In progress 11 · ❌ Not started 11 · 🚫 Likely out of reach 6</sub></p>

<details><summary><b>Every feature</b></summary>

| Block | Feature | Status |
| --- | --- | --- |
| **CPU** | 5 A725 cores | ✅ Ran 15 min under iOS at 1075 MHz, no kernel crash |
|  | CPU clock control | ✅ Governor ran 15 min under iOS: 533–1075 MHz on demand, 125 clock reads within 2%, 33–35 °C |
|  | Higher clocks, up to the 3052 MHz top | 🟡 533–1075 MHz under iOS; p30 health image bytes agree, checker repairs/admission pending. Sustained higher-clock acceptance still pending |
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
|  | Brightness | 🟡 140-nit cap retained; brightness source integrated, slider/transport acceptance still unproved |
|  | HDR, peak brightness, colour calibration | ❌ Not assigned |
|  | Always-on display, self-refresh | ❌ Not assigned |
| **Graphics** | GPU power-on and ID | ✅ GPU answers: core id read from XNU, clean power-off |
|  | GPU firmware through Trusty | 🟡 A725 diagnostic reached SEND/START and captured a 112-byte firmware DEBUG_DUMP; strict health still fails |
|  | Metal drawing | ⏳ Native GPU rendering remains incomplete; sampler pixel checks pass, while startup crashes confound speed claims |
|  | Video encode and decode | ❌ Not assigned |
| **Storage** | Reading | ✅ Multi-block reads, 0 errors |
|  | Writing (persistent /var) | 🟡 Saves and restore across reset verified on the old root; writer now bound to the GPT-resolved ios_data (host-tested), not yet run there |
|  | Maximum speed | ⏳ Patches being measured |
|  | Android/iOS boot chooser | 🟡 Android booted through the chooser 3x in a row (42 s); menu shown on the panel; display handback and iOS entry pending |
|  | Isolated iOS partitions | ⏳ Partition plan built and verified (ios_system 24 GiB, ios_data 8 GiB); one-time Android migration in progress |
| **Input** | Touch | ✅ Owner confirmed Home and Settings in the combined p32 phone test; backboardd respawns and UI stability remain unresolved |
|  | Scripted taps and keys | 🟡 Remote HOME visibly worked; TAP dispatched but required manual app recovery. No automatic retry or clean TAP acceptance |
|  | Volume keys | 🟡 Read in a probe |
|  | Power key | ⏳ Retry needs someone at the phone |
|  | Tap to wake, palm rejection | ❌ Not assigned |
| **Connectivity** | Wi-Fi | 🟡 BCM4390 passive scan proven; native discovery source integrated and iOS 26 scan ABI checked. Settings join and packet traffic unproved |
|  | Bluetooth | 🟡 Firmware/H4 proven; QEMU daemon capture shows keychain errors. Native HCI attachment, Settings pairing and profiles unproved |
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
|  | Haptics | 🟡 Chip found; one effect commanded; felt buzz unconfirmed |
| **Sensors** | Accelerometer, gyro, proximity, light, barometer | ⏳ Physical: accel and gyro samples through 2400, changing orientation; proximity/light/barometer and app integration unproved |
|  | Always-on chip | ⏳ First test built |
| **Power** | Temperature and thermal guard | ✅ Live temperatures; guard panic verified at a test limit |
|  | Battery gauge | 🟡 Native powerd consumed five fresh samples at 89% / 4332 mV and posted percentage notifications; visible percentage unverified |
|  | Charging control | ❌ Left at the bootloader's settings |
|  | Wireless charging | ❌ Not assigned |
|  | Real date and time | 🟡 Physical RTC GET_TIME and OS calendar publication succeeded; visible date/time acceptance remains pending |
| **Cameras** | Cameras, flash | 🚫 Likely months: sensor details aren't public |
| **Security** | Fingerprint, Face ID | 🚫 Tied to Apple's security chip |
|  | Secure enclave | 🚫 Apple SEP is absent; the current key-store provider cannot wrap keys. Native data-protection support remains incomplete |
| **Apple services** | Activation, iMessage, App Store purchases | 🚫 Need a real iPhone's identity |

<sub>Scores: works on the phone 100%, partly working 60%, built, not run 35%, in progress 20%, not started 0%. A planning estimate, not a benchmark. Rebuild with `python3 -I tools/readme_status.py` after editing `docs/status.json`.</sub>

</details>

> **What this is.** An experimental research bring-up on the owner's own phone, not a product. Not affiliated with or endorsed by Apple or Google. No Apple software or firmware is distributed here. Apple's security model is largely switched off, so the phone isn't safe for real data.

<!-- status:end -->

---

<!-- latest-checkpoint:begin -->

## Current checkpoint

**Dual boot is under way.** A boot chooser built into the project's shim now starts the phone's own
Android kernel: Android booted through it three times in a row (42 s with caches on). Plain boots are
unaffected. The chooser's startup menu has been shown on the panel. Handing the display back to Android
after the menu, the iOS entry and volume-key selection are still open.

iOS storage is being moved off Android's extents for good. A one-time migration gives iOS its own
`ios_system` and `ios_data` partitions. The kernel's only write path is locked to `ios_data` by GPT
name, type and position, and checked before every write. No iOS root is deployed until that migration is done.

Native iOS 26 reached human-confirmed Home and Settings earlier; the UI is still unstable, and native
Metal, radios and stock-app launches remain incomplete.

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

- Migrate storage to isolated ios_system/ios_data partitions and install the Android/iOS chooser
- Resolve startup/compositor crashes and measure frame completion before promoting sampler speed
- Analyze the captured GPU firmware DEBUG_DUMP and complete strict health
- Qualify native battery/clock presentation and interactive TAP/HOME behavior
- Finish native Wi-Fi scan delivery and the Bluetooth keychain prerequisite on existing transports
- Complete stock-app registration, readbacks and representative foreground launches

**Next**

- Verify persistent real settings on ios_data across reboots; finish the on-screen chooser menu
- Validate volume and power keys, display sleep and wake
- Verify visible battery percentage, real date/time and brightness control
- Repair and physically qualify USB ECM networking, then native mux pairing
- Complete CPU health and thermal step-down before higher clocks or A520 admission

**Later**

- Complete native GPU firmware execution, shader compilation and Metal rendering
- Integrate audio and haptics with actual transport and physical acceptance
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
