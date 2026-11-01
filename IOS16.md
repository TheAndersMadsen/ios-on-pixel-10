# iOS 16 line: frozen

Frozen on 2026-11-01 at the owner's request; work moved to branch `ios26`. Nothing here gets new work. Target was iOS 16.5 20F66 on `xnu-8796.121.2`.

Furthest native state: SpringBoard and backboardd running from the full root over UFS (`20261101-203354-ufs-ui-r1`), frames in RAM only. Separately, DPU RAM scanout reached the panel (`20261101-211212-display-frame-r1d`). iOS's own frames never reached the panel, and there was no touch.

`research/` is gitignored and stays on disk, so this branch doesn't contain it. iOS 16-only items there, not to be deleted without asking the owner:

| Item | Path |
|---|---|
| Kernel tree, 8796 | `research/laguna-foundation/kernel-blazer/xnu-src/xnu-8796.121.2` |
| Kernel used on the phone | `research/ufs-root-r1/run/kernel/` |
| Phone image builder, phone-r1 | `research/fullroot-ui-qemu-r1/build-phone.py` |
| QEMU lock screen | `research/fullroot-ui-qemu-r1/run-003/fb-01212.png` |
| Combined images, never booted | `research/ui-integrate-r1/run/all-r1`, `all-r1-safe` |
| Staged root `637103e1…` | On the phone: LU0 `userdata_exp.ai`, LBA 2500838 |
