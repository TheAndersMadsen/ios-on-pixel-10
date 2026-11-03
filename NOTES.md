# Current project notes

Updated 2026-11-02. This is the **only default project-state document**. Keep it
short and current; do not append a session journal here. The previous full journal
is `research/journal/NOTES-full-20261102.md` for explicit historical lookup only.

## Goal and current state

Goal: native iOS 26 on a self-contained Pixel 10 Pro, with Android preserved and
recoverable. QEMU and host tools support development; they are not phone results.

- **Best physical iOS result:** XNU 12377 and the real iOS userland reached
  human-confirmed Home and Settings in p32. Five A725 cores, 12.92 GiB RAM,
  display/touch, UFS reads, RTC publication and native battery samples have
  physical evidence. Backboardd respawns and queued presentations mean the UI is
  interactive but unstable; there is no clean-compositor, FPS or speed acceptance.
- **Android:** restored on slot b (exceptions: `research/factory-alias-restore-r1/HANDOFF.md`).
  After chooser t1 the owner returned it via recovery "Try again" (2026-11-03, return check PASS,
  `research/ios26-dualboot-r8/attempts/return-after-t1/`); force-fastboot off. A1 backup: `research/android-backup-20261102/`.
- **No iOS root is deployed.** `userdata_exp.ai` is a member of Android's multi-device
  F2FS `/data`; every XNU recipe now binds `blazer_ufs_root=ios_system` and
  `tools/image_tool.py` refuses `userdata_exp.ai` and `blazer_persist` (b1d2971, ff9261d).
  XNU dd000c8 (release tree) writes persistence only to the GPT-resolved `ios_data`
  (type GUID, no overlap, above userdata, sealed guard); host and ARM64 object only.
- **Storage (r8, 2026-11-02):** A0 captured the full LUN0 GPT read-only: both copies CRC-valid,
  phone `sgdisk --verify` clean, 0 free LBAs. Strict `dualboot.py` still refuses it because
  the backup header block repeats the entry array after byte 92 (observed on real bytes, kept
  as a FAIL). `tools/gpt_plan.py` emits the attended shrink plan (userdata keeps its first LBA;
  `ios_system`/`ios_data` appended; options 69/24+8 and 61/24+16 GiB; sgdisk-verified on a 4K
  loop). Nothing written. Receipts: `research/ios26-dualboot-r8/`.
- **Chooser (r8):** `shim/chooser.c` (gate `TGL_CHOOSER=1`) chain-loads the stock Android
  kernel. Physical t1: EL2 entry with MMU off, placement 0xc9c00000, stock 6.12.81 boots with
  ABL's Magisk init_boot ramdisk, but vold gets KeyMint -33 on the /data key (test-key boot
  footer) and Android requests recovery. Candidate chooser-v1-r3 transplants the stock boot
  vbmeta; not yet booted. lz4 decode with caches off takes 122 s. No visible menu yet.
- **Apps (QEMU, 2026-11-02):** LaunchServices refuses every container-requiring
  restored app. App-Placeholder (H1) and MCM-container (H2) causes were tested and
  rejected; see `docs/IOS-APPS-IDENTITY.md`. With lsd's os_log mirrored to the console
  (r11g/r11h), no user persona exists. usermanagerd finds no user session (no
  `/var/keybags/usersession.kb`). Leading hypothesis H3: registration waits on a genuine
  user-session/AKS bootstrap. Not yet tested.
- **Not complete:** native Metal, stable compositing, strict GPT, a working Android chain
  and visible menu, higher-clock/A520 acceptance, stock-app registration and foreground launches, native Wi-Fi/
  Bluetooth/cellular service, audio, cameras, SEP/Apple identity and dual boot.
- The README's 47% is a weighted planning checklist, not release readiness.

## Read only what the task needs

| Task | Primary document | Local evidence/source when required |
| --- | --- | --- |
| GPU/Metal | `docs/NATIVE-METAL.md` | `research/ios26-metal-native-20261102/`; physical p32/GPU records in `research/ios26-opt-20261102/` |
| CPU/thermal | `docs/CPU.md` | `research/ios26-cpu-complete-r3/` |
| Dual-boot goal run | `GOAL.md` | `research/ios26-dualboot-r8/` receipts, `NEEDS-OWNER.md` packet |
| Storage/dual boot | `docs/DUALBOOT.md` | `research/ios26-dualboot-r6/` for GPT; `research/ios26-dualboot-r4/` for factory references |
| Apps/identity | `docs/IOS-APPS-IDENTITY.md` | `research/ios26-apps-r1/` |
| Connectivity | `docs/CONNECTIVITY.md` | `research/ios26-connectivity-r1/` |
| Android recovery | `research/factory-alias-restore-r1/HANDOFF.md` | Final restoration section and named receipts only |
| Reuse | `docs/REUSE.md` | `reports/REUSE-STRATEGY.md`; one relevant topic audit only |
| Archive/retention | `research/README.md` | `research/CLEANUP-20261102.json` for removed paths and hashes |
| Historical reproduction | Name the exact attempt first | `research/journal/` and the attempt's own receipts; never browse the whole archive |

## Canonical local artifacts

- Canonical phone root: `research/ios26-root-r1/build-r3/ios26-phone-r3.img`
- Canonical light source root: `research/ios26-root-r1/build/ios26-light-r1.img`
- Apps current/rollback: `research/ios26-apps-r1/artifacts/apps-full-r6.img` and
  `apps-full-r5.img`; older r1-r4 intermediate roots were removed.
- Accepted CoreImage root: `research/ios26-inferno-coreimage-r1/artifacts/root-widget.img`
- Verified factory reference: `research/ios26-dualboot-r4/factory-google-dp11/`

Do not recursively ingest `research/`, raw logs, images, third-party source trees,
old fleet plans or full reports. Retrieve a named file or bounded excerpt instead.
Distinguish source, host, QEMU and physical evidence, and observation from inference.

## Maintenance

At each milestone, **replace the affected current statements** and keep one next
action per blocker. Put detailed attempt receipts in the appropriate `research/`
directory and link them. Do not duplicate full hashes, chronology or other task
summaries here. `HANDOFF.md` contains only the immediate next actions.
