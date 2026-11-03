# hackios QEMU rig on m1box (/data/hackios-qemu), set up 2026-11-03

QEMU runs for the iOS 26 lanes no longer need the Mac. Everything here is host-side evidence only; it says nothing
about Tensor or the phone.

## What is here

- `prefix/`: QEMU 11.1.3 (Arch Linux ARM packages extracted, no root). Run it with
  `LD_LIBRARY_PATH=/data/hackios-qemu/prefix/usr/lib QEMU_MODULE_DIR=/data/hackios-qemu/prefix/usr/lib/qemu`.
  Accelerators: tcg and kvm (`/dev/kvm` is world-accessible; Apple M1 Max, no EL2 for guests, CNTFRQ 24 MHz).
- `research/`: a mirror of only what a run needs, same relative layout as the repo:
  `ios26-bootchain-r1/tools` (mkadt, mkpayload, adt), `ios26-qemu-r1/tools/stub.bin`, `ios26-root-r1/apple/dt`,
  `ios26-release-r1/artifacts/kernel.ios26-p29`, `ios26-apps-r1/artifacts/*.img`, `ios26-apps-r1/runs/`.
- `research/ios26-apps-r1/tools/qemu-ufsroot.py`: Linux port of the Mac harness (same guest layout, ADT, boot-args,
  stub, framebuffer PNGs, ramoops console capture). Extra flags: `--accel kvm`, `--slots N` (parallel guests;
  default 1, env `HACKIOS_QEMU_SLOTS`), `--timebase`, `--dry`. Intent records host, qemu version, accel, timebase,
  overlay sha. A dry run against the Mac's `registration-umdinit-r12d` reproduced its ADT byte for byte except
  `chosen/random-seed`, and the same boot-args, addresses and QEMU argv (`ref-r12d/`).
- `calibrate.sh` and `calibrate.log`: the r12d replay in KVM and TCG side by side (`runs/cal-r12d-kvm`, `runs/cal-r12d-tcg`).
- `mkvariant.sh BASE NEW EDIT.py`: build a root-image variant here: btrfs reflink copy, HFS+ mounted read-write in a
  privileged container (hfsplus.ko, loop), `EDIT.py MOUNT` with python3/plistlib as root, fsck.hfsplus. No hdiutil.
- `sync-variant.sh`: pull a Mac-built variant as an rsync delta over a reflink of a base already here (minutes, not 35 min).

## Rules that still apply

One variable per run, the intent written before the run, the result recorded whatever it is (GOAL.md section 9 for
the protocol; section 7 for the lane order). Disk: `/data` has ~740 GiB free; each guest holds ~8 GiB of backing
files while it runs and deletes them afterwards. RAM: 62 GiB; a guest is 3 GiB plus the shared page cache of its root.
Keep `HACKIOS_QEMU_SLOTS` at or below 4 on TCG (one core each) and check `free -g` before raising it.
