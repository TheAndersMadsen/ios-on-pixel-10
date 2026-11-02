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
- **Android:** restored on slot b. The Mac-backup restore, module-enabled reboot
  and BASIC/DEVICE/STRONG integrity checks completed. Exceptions are listed in
  `research/factory-alias-restore-r1/HANDOFF.md`.
- **No iOS root is deployed.** `userdata_exp.ai` is now a member of Android's
  multi-device F2FS `/data`. Old root, alias, capacity, write-approval and
  dual-boot instructions are historical.
- **Storage (2026-11-02):** strict GPT is still not accepted. The r5a backup-header
  padding matches the factory FBPT LUN0 entries (31/31), so it is most likely
  device-written media content. The capture tool now saves the full metadata plan
  raw before the unchanged strict parse. FBPT and Android observations indicate
  no unallocated LUN0 space: isolated iOS storage requires an attended Android
  shrink/migration. No physical GPT candidate is admissible, because every readback
  recipe binds `userdata_exp.ai`. See `research/ios26-dualboot-r7/STORAGE-DECISION.json`.
- **Apps (QEMU, 2026-11-02):** LaunchServices refuses every container-requiring
  restored app. App-Placeholder (H1) and MCM-container (H2) causes were tested and
  rejected; see `docs/IOS-APPS-IDENTITY.md`. The lane is stopped until lsd's
  refusal reason is observable.
- **Not complete:** native Metal, stable compositing, strict GPT, higher-clock/
  A520 acceptance, stock-app registration and foreground launches, native Wi-Fi/
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
