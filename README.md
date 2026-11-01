# hackios

**Apple's XNU kernel and iOS 16 userland on the Google Pixel 10 Pro.** `launchd` runs natively from the full root; there is no UI yet.

This project ports Apple's open-source XNU kernel (`xnu-8796.121.2`, the iOS 16.5 generation) to the Pixel 10 Pro (`laguna`, board `blazer`, Tensor G5). The furthest native boot mounts the full iOS root from UFS and runs `launchd`, with no UI. Bring-up detail is in [BLAZER.md](BLAZER.md).

> Experimental bring-up, not a usable phone OS. Boots are temporary RAM boots; the boot tool leaves `force-fastboot` on. Apple's security model is mostly switched off.

## What works

| Area | State |
| --- | --- |
| Boot | Stock Google bootloader → `fastboot boot` of our shim → XNU. Nothing is flashed to the boot partitions |
| Logs | Shim stamps and XNU message buffer are read back over USB from the fastboot park |
| Root | HFS+ compact root delivered in the boot image mounts |
| Root | Full APFS root mounts read-only from UFS, with 16 KiB pages and 4 GiB of RAM |
| Userland | `launchd` main runs and spawns xpcproxy, on its Restore branch. Once so far |

## What does not work (yet)

- **No native display, touch or stable userland.**
- **No automatic recovery** has been qualified.
- **No normal boot:** `launchd` stays on its Restore branch and SpringBoard hasn't run.

Separate results, not native: the iOS 16.5 home screen with touch ran in a pKVM VM on this phone (2026-10-25), and QEMU has rendered the lock and home screens.

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
| `xnu/` | Kernel patches and build notes |
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
