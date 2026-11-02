# Build a phone image and boot it

From a clean checkout of branch `ios26`. The image tool never touches the device. `tools/bootios` does, and only `fastboot boot`: nothing is flashed, but it sets `fastboot oem force-fastboot on` and leaves it on.

`research/` is not in git. A clean checkout needs the inputs below in place at these paths. Every tool checks pinned files by hash and refuses a wrong one.

## Host

macOS with `/usr/bin/cc`, Homebrew `llvm` at `/opt/homebrew/opt/llvm/bin`, Python 3, `fastboot`. USB console tools need `pyusb`, by `TEGU_PYTHON`.

## Inputs, under `research/`

| Needed for | Path | Pin or source |
|---|---|---|
| Any image | `native-20261024/reuse/felix-working-source/baremetal_loader/avbtool.py` | `e5a664a3…`, in `image_tool.py` |
| Any image | `laguna-usb-fix/keys/test-rsa4096.pem` | `4ef896cb…`, test key, in `image_tool.py` |
| Any image | `ios26-root-r1/apple/dt/DeviceTree.d421ap.bin` | `6bb98998…`, in `mkadt.py`. Apple artifact |
| Any image: shim tests in `build.sh` | `ufs-read-r2/decode_read.py`, `ufs-read-r2/run/decoded.json`, `ufs-link-r2/decoded.json` | Earlier captures and decoder |
| Same | `laguna-foundation/kernel-blazer/devices/blazer/fdt/laguna.dtb` | Phone's device tree |
| Same | `laguna-usb-fix/native-fleet-20261031/N881-g5-ufs-core-uic-ports/independent/linux-v6.6`, `laguna-usb-fix/native-fleet-20261031/N873-g5-ufs-cold-start-source-port/vendor/private/google-modules/soc/rdo/drivers/ufs` | Source the literals are checked against |
| DPU images: `test_dcs_bright.py` | `display-frame-r1/sources/gs_panel.c`, `display-frame-r1/sources/gs_panel_funcs_defaults.c`, `workspace/sources/linux-next/drivers/gpu/drm/drm_mipi_dsi.c`, `workspace/sources/reference/grapheneos-panel-bmea-20261025/panel-gs-bmea.c`, `upstream/patch-scout-chips/pixel10-aosp/private/google-modules/display/panels/muzel/panel-gs-bmea.c` | Same |
| `--phone-root` | A kernel from `ios26-release-r1/artifacts/`, and a QEMU run the parent accepted, such as `ios26-blazer-r1/runs/gate-p2-r3` | Hash given on the command line |
| `--var-overlay` | `ios26-overlay-r1/overlays/p5-first.ovl` | Hash given on the command line |
| `--first-boot` only | `laguna-usb-fix/native-fleet-20261031/N419-ioctl-phone-package/admission/artifacts/root.hfs` | `3cd4dcb5…`, in `image_tool.py` |
| Booting | `laguna-usb-fix/run-attempt.sh`, which also uses `laguna-usb-console/tools/` and `laguna-ramdump/reader/` | Called by `tools/bootios` |
| `all_decode.py` | `ufs-read-r2/decode_read.py`, `ufs-root-r1/tools/decode_root.py`, `ufs-speed-r1/tools/decode_speed.py`, `display-frame-r1/tools/decode_dcs.py` | Reports only |
| `phone_write.py` | `ufs-read-r3/decode_read.py` | Reports only |
| Tests only | `ios26-release-r1/artifacts/kernel.ios26-p4`, `ios26-kernel-r1/work/xnu/pexpert/pexpert/arm64/boot.h`, `workspace/hardware/analyze_dtb.py`, `workspace/hardware/bootchain-20261022/live-fdt.dtb`, `laguna-usb-console/tools/build-next-boot.sh` | Tests of captures skip when absent |

The phone must already hold root `ios26-phone-r3` in `userdata_exp.ai`. Writing it is a separate step that needs the owner's approval.

## Build

```
K=research/ios26-release-r1/artifacts/kernel.ios26-pN
python3 -I tools/image_tool.py image NAME --kernel $K --kernel-sha $(shasum -a 256 $K | cut -d' ' -f1) \
  --phone-root --phone-route md0-mountroot --qemu-run gate-p2-r3 --phone-args "blazer_touch=1 blazer_touch_bars=1 hk_top=30"
python3 -I tools/image_tool.py check research/images/NAME
```

Output is `research/images/NAME/`: `boot.img`, payload, ADT, `manifest.json`, `SHA256SUMS`. An image is never rebuilt: use a new name. `--phone-args` takes only tokens on the tool's list. Other options: `--bootcpu`, `--cpus`, `--cpu-order`, `--window-base`, `--phone-deadline`, `--canvas`, `--var-overlay` with `--var-overlay-sha`. Payload version 2 carries a line of up to 1023 B.

## Boot

Ask the owner first. One boot at a time.

```
tools/bootios research/images/NAME/boot.img NAME --mach $K.unstripped --wait 2100
tools/boot-summary.py research/laguna-usb-fix/attempts/<attempt>
```

Use `--wait 1200` with `--bootcpu`, whose deadline is 900 s. Live console: `tools/usbcon.py`, with `blazer_usbcon=` on the line. Order of boots and verdicts: `tools/bootplan.py list`, `next`, `verdict ATTEMPT`. It prints commands and never reaches the phone. Its results log stays in `research/ios26-runner-r1/results.jsonl`, and its list names images and readers under `research/`.

## Read the result

Use `boot-summary.py` for how a boot ended. `tools/all_decode.py`'s `end of boot` row searches the raw dump and can show an earlier boot's line.

## Tests

```
cd tools && for t in test_*.py; do python3 $t; done
```

With all inputs present, `test_boot_tools.py`'s two old-path symlink tests pass only in the main checkout.
