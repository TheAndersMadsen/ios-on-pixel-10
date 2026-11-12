# UniXNU and hackios

[UniXNU](https://unixnu.com/) runs iOS and macOS on non-Apple ARM64 boards through a device UEFI
(usually Mu-Silicium), its boot manager and the DarwinBoot loader, then a patched XNU with shared
components. hackios is **not built on the UniXNU tree** and does not depend on it. This file says what
we take from it and how our records map onto theirs. Read at UniXNU `6b24c06c` (2026-11-11); details,
pins and the comparison are in `research/unixnu-align-r1/structure/REPORT.md`.

## Position

- **Independent, compatible record.** We keep our boot chain (ABL `fastboot boot` -> `shim/` -> XNU),
  our ADT generator (`tools/mkadt.py`) and our drivers. We can describe the board in UniXNU's record
  format without adopting its build, the way `Scion-Project/scion-starlte` (HakiOS, S9) does.
- **No UniXNU component is selected.** Their catalog targets Qualcomm SM8550 and virtual platforms.
  None of its controllers match Tensor G5 (PowerVR DXT GPU, DC9x00 display, Google UFS/pinctrl).
- **No Tensor G5 port exists there.** The closest is `Trijal08/UniXNU-komodo` (Pixel 9 Pro XL,
  Tensor G4): menu, payload and borrowed-kernel entry probes on hardware; no native platform, storage
  or root. Its G4 Exynos IP (UFS at 0x13200000, DECON, Mali) differs from ours.
- Nothing is filed upstream. The GitHub repository is public (checked 2026-11-11), so a pushed commit
  is published. UniXNU's catalog scan (`scripts/sync-devices.py`) lists any public repository with
  `unixnu` in its name or description or the `unixnu` topic, and reads root `board.toml` and
  `porting.toml`. Keep the record out of the root and the word and topic out of the repository
  metadata until the owner decides, after the licensing audit in [LICENSING.md](LICENSING.md).

## What we take

| From UniXNU | Use here | Status |
| --- | --- | --- |
| Porting-record format (`board.toml` v2, `porting.toml` v1, 13 required areas) | `tools/unixnu_record.py` emits both into `devices/blazer/` from `docs/status.json` and bound physical receipts | Checker-accepted (host); not published |
| Completion levels `planned`/`implemented`/`host-verified`/`device-verified`/`not-applicable` | Mapping below; our labels stay primary | Adopted for the record only |
| Bring-up stage order (firmware, menu, payload, loader, kernel entry, root, userland) | Reference for boot-summary stages | Not adopted |
| Component, SoC and device split (`UniXNU-<soc>-common`, `UniXNU-<device>`) | Not adopted: one board, one repository | Revisit with a second Tensor G5 board |

No UniXNU code is copied. Their repositories are BSD-2-Clause-Patent; record repo, commit and
licence in [REUSE.md](REUSE.md) before adapting any file.

## Status mapping

| hackios | UniXNU |
| --- | --- |
| Source | evidence `source` |
| Host test, enabled ARM64 object, QEMU | evidence `host` (UniXNU has no QEMU kind) |
| Physical | evidence `device`; needs command, 40-character revision and an accessible log |
| ✅ works, with a bound physical receipt | area `device-verified` |
| ✅ 🟡 🔧 with a bound host receipt | area `host-verified` |
| ✅ 🟡 🔧 without a bound receipt | area `implemented` |
| ⏳ ❌ 🚫 only | area `planned`; reasons in `limits` |

A UniXNU area status is one level per area. The README's weighted percentage stays ours and is not
exported. Physical receipts live under `research/`, outside git, so `device-verified` appears only
when `--evidence` binds a receipt.

## Generate the record

The record lives in `devices/blazer/` beside the port lane's `device.conf` (one device directory for
both vocabularies), not at the repository root, so UniXNU's catalog scan does not read it.

| File | Content |
| --- | --- |
| `devices/blazer/receipts.toml` | `[[claim]]` per area (level, findings, limits, next action) and `[[evidence]]` physical receipts |
| `devices/blazer/evidence/*.txt` | Bounded, scrubbed excerpts of each physical boot: device, firmware, image and kernel hashes, XNU commit, command, hk_score table, decisive lines |
| `devices/blazer/board.toml`, `porting.toml` | Generated; do not edit |

```sh
python3 -I tools/unixnu_record.py devices/blazer            # reads devices/blazer/receipts.toml
python3 -I tools/unixnu_record.py devices/blazer --check    # exit 1 if stale
python3 -I tools/test_unixnu_record.py
```

A claim of `device-verified` needs a bound `device` receipt (command, 40-character XNU commit, an
evidence file). Areas are `device-verified` only when the area's complete operation (request,
hardware completion, iOS-visible result) was seen on the phone; hardware-only rungs stay `implemented`
with their receipts attached. The method and the per-area gap list are in
`/data/work/hk-unixnu-port/METHOD.md` (lane work directory).

UniXNU's checker (`scripts/porting-record.py check --device DIR`) resolves evidence paths against DIR,
so check a copy that holds `board.toml`, `porting.toml` and `evidence/` and links `docs/`, `shim/`,
`tools/`, `adt/`, `NOTES.md` and `README.md`, or set `UNIXNU_CHECKER` for the test.

## Blockers to adopting their build

- **UEFI.** UniXNU needs a device UEFI (Mu-Silicium or another). No Tensor G5 UEFI exists; the only
  Pixel one is a Mu-Silicium fork for Pixel 9 (`caimitoPkg`, S5P9875). Our shim boots without it.
- **Kernel.** UniXNU builds XNU for the BCM2837 machine configuration with 4 KiB pages and patches
  16 KiB assumptions. Our kernel series uses 16 KiB pages. Their iPadOS 26.5.2 profile pins XNU
  12377.121.6 with iPad17,3 identity; we run XNU 12377 with an iPhone12,3 ADT and iOS 26.6.2.
- **Boot image.** Not a blocker: `scripts/unixnu/bootimg.py` verifies v3/v4 headers at `6b24c06c`
  (komodo's note that it handles only v0..v2 predates this). Its payload is a UniXNU FAT volume, not ours.