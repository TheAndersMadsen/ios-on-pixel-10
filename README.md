<!-- status:begin -->

<p align="center"><img src="docs/assets/hero.svg" alt="iOS 26 on Pixel 10 Pro: 36% of reachable hardware" width="100%"></p>

<h2 align="center">A phone that was never meant to do this.</h2>
<p align="center">Apple's open-source kernel. iOS 26's own userland. Google's Tensor G5.<br>Custom drivers, written block by block, for one extraordinary piece of hardware.</p>

<p align="center"><img src="docs/assets/stats.svg" alt="Measured on the phone" width="100%"></p>

<h2 align="center">Every block. Tracked.</h2>
<p align="center"><b>36%</b> across 46 reachable features. Updated 2026-11-02.</p>

<p align="center"><img src="docs/assets/blocks.svg" alt="Progress by hardware block" width="100%"></p>

| | Status | Features | Counts as |
| --- | --- | ---: | ---: |
| ✅ | Works on the phone | 6 | 100% |
| 🟡 | Partly working | 9 | 60% |
| 🔧 | Built, not run | 8 | 35% |
| ⏳ | In progress | 11 | 20% |
| ❌ | Not started | 12 | 0% |
| 🚫 | Likely out of reach | 6 | not counted |

<details><summary><b>See every feature</b></summary>

| Block | Feature | Status |
| --- | --- | --- |
| **CPU** | 5 A725 cores | 🟡 Up under XNU and iOS, no full run yet |
|  | CPU clock control | 🟡 Up to 1536 MHz in a short test; not yet under iOS |
|  | Higher clocks, up to the 3052 MHz top | ⏳ Short tests being built, limited by heat |
|  | 2 A520 cores | 🟡 cpu0 parked in the shim; cpu1 unused |
|  | X4 core | 🚫 For now: its errata aren't fixed |
|  | Idle sleep | ✅ By code reading: cores already idle in WFI |
| **Memory** | Memory and shared cluster clocks | 🟡 Up to 2.25x in a short test; first iOS run in progress |
|  | RAM | 🟡 4 GiB works, 6 GiB passed its short test; 12.92 GiB is the target |
|  | The rest of the 16 GiB | ❌ Not assigned |
| **Display** | Full 1280x2856 picture | ✅ Scaled from 1125x2511 |
|  | 120 Hz | 🟡 Panel runs at 120, iOS draws about 20–31 fps |
|  | 60 Hz mode and frame sync | 🔧 Next test |
|  | Variable refresh down to low rates | ❌ Automatic idle rate isn't built |
|  | Brightness | 🟡 Capped at about 140 nits; no user control yet |
|  | HDR, peak brightness, colour calibration | ❌ Not assigned |
|  | Always-on display, self-refresh | ❌ Not assigned |
| **Graphics** | GPU power-on and ID | 🔧 Next test |
|  | GPU firmware through Trusty | 🔧 Ping and load tests built |
|  | Metal drawing | ⏳ Months away; everything is CPU-drawn now |
|  | Video encode and decode | ❌ Not assigned |
| **Storage** | Reading | ✅ Multi-block reads, 0 errors |
|  | Writing (persistent /var) | 🔧 First write awaits approval |
|  | Maximum speed | ⏳ Patches being measured |
| **Input** | Touch | ✅ Works; feel unconfirmed |
|  | Volume keys | 🟡 Read in a probe |
|  | Power key | ⏳ Retry needs someone at the phone |
|  | Tap to wake, palm rejection | ❌ Not assigned |
| **Connectivity** | Wi-Fi | 🟡 Firmware runs; no network yet (stage 3 in progress) |
|  | Bluetooth | ⏳ QEMU test queued, needs Wi-Fi firmware running first |
|  | Cellular | ⏳ Modem identified; first check built |
|  | SIM, eSIM | ⏳ Part of cellular |
|  | GPS | ❌ Not assigned |
|  | NFC | ❌ Reading tags possible at most; Apple Pay is out of reach |
|  | UWB | ❌ Not assigned; presence unconfirmed |
| **USB** | Fastboot and logs | ✅ |
|  | Live console | 🔧 Next tests |
|  | Link to the Mac | ⏳ mux-1 test in QEMU |
|  | Network over USB | ❌ Not assigned |
|  | USB host, video out | 🚫 No host stack in open XNU |
| **Audio** | Speakers, microphones | ⏳ QEMU test queued; depends on always-on chip |
|  | Haptics | 🔧 Read-only stage ready |
| **Sensors** | Accelerometer, gyro, proximity, light, barometer | ⏳ Depend on always-on chip |
|  | Always-on chip | ⏳ First test built |
| **Power** | Temperature and thermal guard | ✅ |
|  | Battery gauge | 🔧 Probe ready |
|  | Charging control | ❌ Left at the bootloader's settings |
|  | Wireless charging | ❌ Not assigned |
|  | Real date and time | 🔧 Ready to test |
| **Cameras** | Cameras, flash | 🚫 Likely months: sensor details aren't public |
| **Security** | Fingerprint, Face ID | 🚫 Tied to Apple's security chip |
|  | Secure enclave | 🚫 Stand-ins only, so the passcode doesn't encrypt anything |
| **Apple services** | Activation, iMessage, App Store purchases | 🚫 Need a real iPhone's identity |

</details>

<sub>Percentages are a progress estimate from the table above, not a benchmark. Measured figures come from single test boots of one phone, and their notes say which were short tests or estimates. Rebuild with `python3 -I tools/readme_status.py` after editing `docs/status.json`.</sub>

> **What this is.** An experimental research bring-up on the owner's own phone, not a usable phone OS and not a product. Nothing here is for sale. It isn't affiliated with or endorsed by Apple or Google. No Apple software or firmware is distributed here. Apple's security model is largely switched off, so the phone isn't safe for real data.

<!-- status:end -->

---

## The details

This project ports Apple's open-source XNU kernel to the Pixel 10 Pro (`laguna`, board `blazer`, Tensor G5), running XNU 12377 and the iOS 26 userland. Boots are temporary RAM boots through `fastboot boot`; the boot tool leaves `force-fastboot` on. The root image is on `userdata_exp.ai`.

## How it boots

```
ABL (stock Google bootloader, unlocked)
  -> fastboot boot <image>                    (temporary; nothing is flashed to boot)
     -> shim: own MMU setup, reads the live FDT, loads the payload from the ramdisk
        -> XNU Mach-O + generated Apple Device Tree (ADT) + boot-args
           -> XNU -> compact root (today) / UFS root in userdata_exp.ai (goal)
              -> dyld + shared cache -> launchd -> daemons -> UI
```

There is no serial console. The diagnostics live in reserved RAM at `0x95200000` and are read from fastboot after the phone returns there.

## How to build it

```sh
research/laguna-foundation/kernel-blazer/xnu-build.sh          # kernel, -j8 -k
R4_MACHO=<kernel> tools/build-next-boot.sh                     # boot image
tools/bootios <image> <name>                                   # temporary boot and capture
tools/decode-shim-stamps.py                                    # read the result
tools/read-ramdump.py --mach <booted kernel> --dump-base 0x95200000
```

More in [xnu/README.md](xnu/README.md).

## Repository layout

| Path | What |
| --- | --- |
| `AGENTS.md` | How to work on this repository |
| `HANDOFF.md` | Latest state and next step, newest first |
| `NOTES.md` | Goal, hardware facts, artifact locations and dated working notes |
| `BLAZER.md` | Pixel 10 Pro bring-up status and evidence history |
| `shim/` | Boot shim |
| `tools/` | Build, boot and log tools |
| `xnu/` | Build notes; `ios16-base/patches` is the parts source for the 12377 port |
| `backup/` | Stock boot images; not committed |
| `research/` | Evidence, sources and earlier documents; not committed |

## Key hardware facts

- SoC Tensor G5 (`google,lga-blazer`). Boot-state truth is in `/proc/bootconfig` (`device_state=unlocked`), not `getprop`.
- UFS: Samsung KLUDG4UHGC (128 GB), host controller at `0x3c400000`.
- USB: DWC3 at `0x0c400000`, wrapper at `0x0c450000`.
- Log RAM: ramoops at `0x95200000`, pmsg at `0x95400000`.

More in [`NOTES.md`](NOTES.md).

## Credits

- Apple: XNU and dyld open-source releases; iOS userland is proprietary and stays out of the repository.
- HakiOS (`oosexgang/hackios-xnu-kernel`, `hackios-xnu-userland`): upstream porting base.

Origins and licenses: `research/legacy-root-20261101/PROJECT-COMPOSITION.md`.
