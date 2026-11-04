# Current project notes

Updated 2026-11-04 (Phase C live-debug run, m1box). This is the **only default project-state document**. Keep it
short and current; do not append a session journal here. The previous full journal
is `research/journal/NOTES-full-20261102.md` for explicit historical lookup only.

## Goal and current state

Goal: native iOS 26 on a self-contained Pixel 10 Pro, with Android preserved and
recoverable. QEMU and host tools support development; they are not phone results.

- **Best physical iOS result:** XNU 12377 and the real iOS userland reached
  human-confirmed Home and Settings in p32. Five A725 cores, 12.92 GiB RAM,
  display/touch, UFS reads, RTC publication and native battery samples have
  physical evidence. **Backboardd crash loop fixed (2026-11-04, int5-r2):** the
  `HK_FLATMAT=softblur` material corrupted QuartzCore CABackingStore free blocks
  (3-exec crash loop in int5); int5-r2 drops it and ran the full 900 s deadline at Home
  with 0 LIBMALLOC/usertrap crashes (frames flowing, touch/button clients up).
  FPS/speed acceptance still open.
- **Live-debug queue (2026-11-04 04:51-05:51 CET, PHYSICAL):** int5-r2 PASS (above);
  GPU rung 8 (gpu5) + rung 9 (gpu6) PASS - MMUCACHE executed in firmware, ordered UFO
  fence, 0 faults; aoc5 (first AoC phone run) PANICS: unaligned data abort at x0+0x40,
  ramdump kept, AoC lane open; modem2 rung 5 STOP (controller already live at survey,
  clean tidy, 0 errors); CA diagnostic answered: no AGXAccelerator in the IORegistry,
  MTLCreateSystemDefaultDevice nil, CA selects SWContext - the native-GPU path must
  publish the device first. All return checks PASS.
  Receipts: `research/ios26-phaseb-r1/goal-pool/receipts/queue-20261104.md`,
  `gpu5-20261104.md` (rungs 8-9), `int5-20261104.md` (regression). Built, not booted:
  int5-r3, int4-perf-r1 (governor fix), gpu7 (rung 10), int4-spotlight-r1,
  SweetSensorHub, nfc2; bt5-r2 (Mac-only) pending the owner's TX decision; periph-r1
  needs an attended rotate.
- **Android (2026-11-03, PHYSICAL):** slot b, Magisk 31.1 with its 7 modules active, owner data restored
  after the migration (files, apps, app data; exceptions and Keystore-bound apps in
  `research/android-backup-20261103/RESTORE.md`). Return check PASS against the new post-restore baseline
  (root sentinel, app count, /data size): `research/ios26-dualboot-r8/attempts/return-after-restore/`.
  Play Integrity passes BASIC only (keybox not revoked); not a dual-boot blocker.
- **iOS Home from ios_system (2026-11-03, PHYSICAL):** `a7-ios-system-r3` (5 cores, deadline 300) booted the
  flashed ios_system root to Home; the owner saw it, touch works and Settings opens. The earlier black screens were
  backboardd's CoreBrightness NULL read whenever `hk_bright=140` publishes an uncalibrated `AppleARMBacklight`; r3 drops it
  (0 traps). Only Settings is present (stock-app registration still blocked), no brightness control yet (calibration
  patch 0001 not built), nothing persists. Android return checks PASS after every boot. `research/ios26-phaseb-r1/A7.md`.
  Resolve disks by-name; `tools/image_tool.py` still refuses `userdata_exp.ai`.
- **Storage (2026-11-03, PHYSICAL):** migrated. After a no-op proof (identical bytes, reboot, return check
  PASS), the owner-approved GPT write made userdata 69.3 GiB (LBA 4,597,990..22,757,375), `ios_system` 24 GiB
  (sda36) and `ios_data` 8 GiB (sda37), project type GUID; `sgdisk --verify` clean; recovery factory reset;
  Android /data 77.3 GiB, nothing mounts ios_*. Rollback copies: `research/ios26-dualboot-r8/gpt-plan/option-a-ios24+8/`.
  Backup and restore receipt: `research/android-backup-20261103/`.
- **Dual boot (2026-11-03, PHYSICAL, temporary boot):** `chooser-ios-r2` (cab9d96e…; one image: menu + iOS payload + stock
  Android kernel, default Android) shows both systems; the owner picked iOS with the volume keys and iOS booted (C3a PASS).
  Keys fixed in r13 (sampling during redraws). C1 and C3b PASS. **Installed on boot_b 2026-11-03 19:17** (readback cab9d96e; rollback `fastboot flash boot_b research/ios26-dualboot-r8/truth/boot_b.img`): cold power-on shows the menu and Android works; iOS from the installed menu faults at the shim's usb-warm (USB not started on a cold boot), fix in progress (r3). `research/ios26-phaseb-r1/A7.md`.
- **Chooser (2026-11-03, PHYSICAL):** `fastboot boot` of the chooser (`shim/chooser.c`, stock boot vbmeta
  transplanted) chain-loads the stock Android kernel at EL2 (r3 x3, r4 in 42 s). **Display handback works:**
  chooser-v1-r11 showed the startup menu on the panel (owner saw it), released the DPU and booted Android in 42 s
  (kernel 0xc9c00000, return check PASS). r9/r10 had died on a CPM assert (`lpb.c:676 sswrp_id`) because the release's
  LPCM off frames put the command in the wrong byte; r11 uses the vendor `send_lpcm_mail` field order and the stock
  vs_drm.ko quiesce (89d1741, 69b84d7). Volume keys not run yet. Receipts: `research/ios26-dualboot-r8/attempts/`
  (chooser-v1-r10-t1, r11-t1), `display-handback/SUSPEND-ORDER.md`.
  Host only, not booted: volume-key poll (5bd6899) and `chooser-v1-r12` = r11 + `--keys --keys-poll`
  (bccd5cf0…4870; steps `research/ios26-dualboot-r8/keys/BOOT-r12.md`); the iOS branch, one image with the XNU
  payload and stock Android (291251d; `research/ios26-dualboot-r8/chooser-ios/DESIGN.md`, boots P0, C1-C4).
- **Apps (QEMU, 2026-11-03):** H3 rejected as stated. Booting the root as a normal boot (`rd=ufsroot0`; `rd=md0`
  is launchd's restore-like "ramdisk" mode) runs the stock creator `usermanagerd --init` and removes the type-6 persona
  errors, but the user still has no personas and lsd aborts (`INVALID_PERSONA` -> `Could not get user container URL!`).
  Removing the seeded persona.kb changed nothing (r15b). Lane stopped (two hypotheses); next blocker by static
  inference: per-user personas wait on `MKBUserSessionLoadKeybagForUser` (AKS user-session keybag), which is
  SEP-adjacent and needs an owner decision. `research/ios26-apps-r1/receipts/h3-static-r12/VERDICT.md`.
- **Compositor (2026-11-03):** the physical backboardd NSURL-nil abort is BaseBoard's
  `BSSystemSharedDirectoryForIdentifier` getting NULL from `container_system_path_for_identifier` (containermanagerd).
  QEMU never reproduces it (0 respawns in 15 min; the container path resolves), so it is a phone-side timing/
  availability effect; `research/ios26-apps-r1/receipts/l1-r16/LANE1.md`.
- **ios_data persist (QEMU, 2026-11-03):** XNU dd000c8 on a GPT-bearing fake LUN (kernel b228c4f) resolved ios_data,
  saved 12 times and changed only 20 blocks, all inside ios_data's table; nothing else on the medium changed
  (`research/ios26-dualboot-r8/ios-data-persist/NEGATIVE-r1.md`). Not physical.
  Physical plan ready, not run (`research/ios26-dualboot-r8/ios-data-persist/PHYSICAL-PLAN.md`): `image_tool
  --persist-ios-data` admits `blazer_persist=1` only for `kernel.rootview` (ddf874fb) on ios_system; `tools/persist_check.py`
  hashes partitions on the phone before and after. It needs a visible A7 Home first.
- **QEMU rig:** QEMU runs on m1box (`/data/hackios-qemu`, adopted in `research/ios26-apps-r1/tools/m1box/`): TCG matches
  the Mac's boot order and is faster; KVM does not boot XNU (`receipts/m1box-rig/CALIBRATION.md`).
- **Not complete:** native Metal, stable compositing, strict GPT, chooser volume keys and the iOS entry, a
  visible iOS boot from ios_system (compositor), higher-clock/A520 acceptance, stock-app registration and foreground launches, native Wi-Fi/
  Bluetooth/cellular service, audio, cameras, SEP/Apple identity and dual boot.
- The README's 48% is a weighted planning checklist, not release readiness.

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
