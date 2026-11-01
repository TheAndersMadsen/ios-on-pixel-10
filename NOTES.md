# iOS 16 on blazer (Pixel 10 Pro, Tensor G5) - working notes

## Pixel 10 Pro port handoff (2026-11-01, current)

Workspace `/Users/andersmadsen/Developer/personal/hackios`. Evidence history: `BLAZER.md`.
Latest detail: `HANDOFF.md`.

- Goal: **Boot native iOS with visible interactive UI, working touch, stability and
  repeatable boots.** Current priority: UFS, so the full root can load.
- Reached on the phone: XNU, compact HFS+ root, pid 1 userspace, dyld to
  `M11.initializers`, then panic. Not reached: `launchd` main, UFS link, native
  display or touch, automatic recovery.
- Use temporary `fastboot boot`. Confirm each destructive step with the user.

Current blocker: UFS device not present after ABL's shutdown (HCS.DP=0).
Next concrete action: apply the review fixes to ufs-observe-r2, build it, boot it with `tools/bootios`. The
full sequence and ufs-link-r1's preconditions are in `HANDOFF.md`, which holds the handoff detail.

### How work runs

- One parent agent does the work, owns USB and runs the boots. It records results here and in
  `HANDOFF.md` as dated bullets, newest first.
- Use a helper only for independent work, a few at a time, named by purpose ("touch agent",
  "shader agent"). The parent checks each result itself and reruns its tests before relying on
  it, and writes what it found ("Parent reviewed ...: ...; requested ...").
- Experiments live in `research/<topic>-rN`, with N going up per retry. Say whether each is
  built, deployed or verified.
- `research/laguna-usb-fix/native-fleet-20261031/` holds older N-numbered work. Read it as
  history; do not add to it or use N-numbers.

### Hardware facts

- `google,lga-blazer`, "BLAZER MP based on LGA". Blazer device tree:
  `research/laguna-foundation/kernel-blazer/devices/blazer/fdt/laguna.dtb`.
- Log RAM: 4 MiB dump at `0x95200000`. ramoops `0x95200000..0x953FFFFF`, pmsg
  `0x95400000`, shim stamps at pmsg+0x30000. Decode with `--dump-base 0x95200000`.
- USB: DWC3 `0x0c400000`, wrapper `0x0c450000`.
- UFS: HC `0x3c400000`, pinctrl `0x3C590000` (pad 0 reset, pad 8 `AP2PMIC_UFS_EN`).
  Samsung KLUDG4UHGC, UFS 3.1, 4 LUNs, HS gear 4 under ABL.
- Source order for UFS: shipped `ufs.ko` (6.12.81), `kernel_pixel_6.12@5940a317`,
  kodiak, then `e214813c` (6.6). The `*_OFFSET` constants in the latter's
  `ufs-regs-gen.h` are wrong.
- Sizes: `system.apfs` 2,476,732,416 B; 20F66 shared cache 2,722,512,896 B. They do
  not fit the 64 MiB RAM-boot path.

### Local artifact locations

- Attempt ledger: `research/laguna-usb-fix/ATTEMPTS.md`. Captures:
  `research/laguna-usb-fix/attempts/`, `research/laguna-usb-fix/automation/state/device-attempts/`.
- Older agent work: `research/laguna-usb-fix/native-fleet-20261031/N*/`.
- Kernel tree and build: `research/laguna-foundation/kernel-blazer/`; port patches: `xnu/patches/`.
- Boot runner: `research/laguna-usb-fix/run-attempt.sh`, called by `tools/bootios`.
- Root images: `research/workspace/iosroot/`, `research/laguna-image/`,
  `research/laguna-usb-fix/root-upgrade/`.
- Vendor sources: `research/upstream-20261101-pixel10pro/`. Other sources: `research/upstream/`,
  `research/workspace/sources/`. Hardware dumps: `research/workspace/hardware/`.
- Old builds: `research/workspace/builds/`. Finished work: `research/archive/`.
- Earlier documents: `research/notes/`, `research/laguna-usb-fix/docs/`, `research/SESSION-STATE.md`.
  They are dated records and may link old paths.
- Every move: `research/legacy-root-20261101/PATH-MAP.json` and `path-maps/*.json`.

## 2026-11-01: documentation restructured

Root documents rewritten to the layout and working style of the Pixel 9a `ios-tegu`
repository, and the root and `research/` reorganised to match. No tegu code or hardware
facts were copied. Moved only, except 24 empty session folders removed. Stopped `loopapi`,
disabled the campaign state and deleted the old scheduled tasks. Boot through `tools/bootios`; it sets persistent
`fastboot oem force-fastboot on` and does not turn it off, so tell the user first.

Known leftovers, none used by the build chain: old October scripts and dated docs still
name old paths; some old git worktrees have stale `.git` pointers (fix with
`git worktree repair` before `git gc`); `tools/check_v3_integration.py` fails because its
fixture no longer matches `shim.c`; `tools/bootios` has not yet been run on the phone.
Tool tests pass.
