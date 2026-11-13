# Current project notes

Updated 2026-11-11 (UniXNU-alignment run, m1box). This is the **only default project-state document**. Keep it
short and current; do not append a session journal here. The previous full journal
is `research/journal/NOTES-full-20261102.md` for explicit historical lookup only.

## Goal and current state

Goal: native iOS 26 on a self-contained Pixel 10 Pro, with Android preserved and
recoverable. QEMU and host tools support development; they are not phone results.

### Done-list status (2026-11-12 boots, receipts audited 2026-11-13: `/data/work/hk-score/AUDIT-20261113.md`; receipts = /data/work/hk-fleet/results/<req>/REPORT.md on m1box)

| # | Item | Status | Physical receipt |
|---|---|---|---|
| 1 | Daily image: Home <90 s, Wi-Fi joined, brightness slider, 15+ apps incl. Photos+Maps, touch, charging | **MET** (integ-5/-6; not repeated cleanly in integ-7) | `integ-5` (hk-base-3, r6 root): Home `UI_READY +80.6 s` (REPORT:163); walk `END PASS steps=83 pass=83` (:209), 15 different stock apps + Settings exec'd incl. Photos and Maps (run console; "drew" = the walk screenshots); Wi-Fi joined kernel-side, `HKWIFI: W2 PASS` (:30), Settings > Wi-Fi shows the joined row (run `ui/0016-016-wifi.png`); on USB with `chg=done` (:19; charge complete, not cc/cv; battery 90-94 %, the earlier "99 %" is in no receipt). `integ-6`: a `sent_dbv` write followed each of the 3 slider drags (2684 … 1791, rc 0, REPORT:6,:11; no panel readback; walk 87/89, the two misses are the rate-limited SWEET BL request line). `integ-7` (everything on together, hk-base-5): Home +76.0 s, Wi-Fi + one bluetoothd + LE scan held, but walk 78/93: 3 steps hit by physical input, 3 SWEET BL waits, both rotation waits, 7 refused after the end reset; translationd crashed 5 times |
| 2 | Bluetooth: attached, HCI both ways, no respawn | **MET** | run `live-20261112-070404-a7-bt11-tx2` console (kernel.bt11, gate level 2): `HKBT random-address PASS`, `HKBT le-scan-enable PASS: 0x200c status 0x00`, `HKBT le-scan PASS: 1000 LE advertising report events`; `bt-8` REPORT has only the 19 command-complete lines (:7-25) and `up 302 s … max execs 1` (:28), not the HKBT lines. Repeated in `integ-7`: REPORT:241 + `max execs 2` overall (:219). Not reached: controller powered on in bluetoothd (no `PowerState:1`, also after Settings > Bluetooth in integ-7), discovery, pairing |
| 3 | Sensors: CoreMotion accel/gyro + UI rotates | **MET one way** (3a met; 3b: to landscape seen once, back to portrait not seen) | 3a `sensors-3`: `HKMOTION … result PASS … accel=833 gyro=833` (REPORT:53; phone flat, `moved=0`; mag 92→184 in the second pass, :59-60). 3b `sensors-4` RAN (07:39, it was not held): the owner turned the phone, kernel `orientation 0x68` (865 mg on x; hkq `orient … last=0x68`, REPORT:122) and the Safari screenshot is drawn in landscape (run `ui/0006-006-safari-landscape.png`, `results/sensors4-sheet.png`); the phone stayed in landscape, so the return was not tested (walk step 9 FAIL). `integ-7` repeat: no landscape line inside the window (walk steps 39/42 FAIL, shot unchanged). Next: one attended turn there and back |
| 4 | GPU compute writes memory + Metal plugin answers QuartzCore without crashing backboardd | **MET** (also `metal-7`: 120 s, 10237 calls, no crash; `gpu-10`: render context rung 14a, 0 faults) | `gpu-5`: `R12 readback: MATCH (0x5ab1c0de)`; `gpu-7`/`gpu-9`: compute + transfer through HMGU SUBMIT/WAIT MATCH; `metal-5`: backboardd ran QuartzCore on HMNativeMetalDevice 120 s, 12162 calls, no crash (screen black: nothing drawn yet) |
| 5 | Audio: AoC running, service census | open — cause not known; socversion theory **refuted** (2026-11-14) | `audio-1`..`audio-8`: aoc.bin 16495511 authenticates (rungs 1-3 PASS), START→state 2, rung 4 FAILs (no IPC magic; the AoC wrote no word in the IPC area). Refuted: stock Android's own Trusty log prints the identical `ac_dt_socversion 0x0 (?)` / `sswrp_cpu … not enabled by socversion` / `52 drivers` with the AoC online (PHYS, truth 20261112-0034 `wifibt/dumpsys-wifi.txt:2369-2385`). **Divergences from stock, neither shown to be the cause:** (a) Trusty interrupt service: stock services INTID 13 `trusty` on all cores; ours disables it in `pe_fiq.c` and never asks Trusty for its list; our hwmgr calls complete by timeouts (GET_STATE 502 ms loaded, START 3008 ms = 6 × 501, 8 `uirq_ack_handled failed: -31` in audio-8; stock START ~12 ms) (PHYS+SRC); (b) AP parameter block: stock ChipRevision 0x1012 = 0x10, ChipProductId 0x1016 = 5, VolteReleaseMif 0x1015 non-zero; ours 0 (SRC, `/data/work/hk-audio/TRUTH-answer.md`). **Next (boots):** `audio-9` queued = aoc14 read-only Trusty-interrupt diagnostic (XNU hk-audio-14 4ca91ec, kernel.aoc14 b6e26e34; HOST 42/0; rung 4 FAIL expected, read `HKAOC tirq`); `audio-10` staged = forward + pump, only if audio-9 shows a listed interrupt or INTID 13 pending; (b) is a separate one-variable boot. Detail: `/data/work/hk-audio/STATUS.md`, `FINDING-socversion-REFUTED-20261114.md` |
| 6 | Modem: ROM handshake rung, no RF | **MET** | `modem-4`: `rom: the boot ROM waits for the doorbell (boot_stage 0xff) … verdict: PASS stage 8`; no doorbell, no firmware, no RF |
| 7 | devices/blazer passes hk_device check + UniXNU checker, status line per driver | **MET** (host) | `tools/hk_device.py check` 2026-11-14 at the committed tree: `hk_device OK: 28 drivers, 28 status lines (22 physical: 11 done, 11 with a limit; 10 proven in their ladder kernel, every quoted line found in the attempts), 10 configs`; `tools/unixnu_record.py --check <outdir>`: 23 areas |
| 8 | NOTES summary + phone back in Android, return check PASS | in progress — **blocked: phone offline** | Summary = this table (current). Return-to-Android + return check need the phone connected in fastboot; as of 2026-11-13 it is not. **Next:** reconnect phone → `tools/hk_session.py --return` (stock image) → return check. Same window serves item 3b (owner turns the phone for UI rotation) and an audio aoc14 boot (item 5) |

Other physical results 2026-11-11/12: root **r6 flashed to ios_system** (sha e798123a, GPT byte-identical; `/data/work/hk-storage/flash-r6-run/`);
Linux-built kernels boot the phone (`farm-1`); common bases hk-base-2/-3/-4 reach Home; HakiOS-method ladder: `port-1`
(6 drivers built in) draws Home at 64 fps; modem rungs 5-8; NFC discovery + clock output; camera PMIC id.
Built, not booted (2026-11-14, host/QEMU only; queue `/data/work/hk-fleet/queue/`): `modem-5` = rung 9, BL1 handoff, one doorbell, no RF
(hk-modem-5 8548f72; BL1 is read at boot from the phone's own modem_b, a raw TOC image; no firmware in any image or repo; first AP
access to cp_rmem); `audio-9` (item 5); `apps-4` (overlay: Spotlight deny off, fairplayd disabled, translationd config cover).
Modem rung 11 (main image = radio stack runs) is NOT built and needs the owner's decision.
`metal-9` queued: CPU-composited frame, not GPU (plugin gate mode 4: real texture memory, CoreAnimation draws run by a CPU executor;
HOST 59/0 + 19/0, QEMU reaches the Apple logo only). metal-8 issued no GPU job (`opens 0 submits 0`); the black screen was the plugin's
memory-less stand-in for the display IOSurface, the present path itself works. A GPU-composited frame needs a render job + shader path.
`wifi-3` queued: kernel hk-wifi-7 4268a84 (hk-base-5 + W5.4 + W7 = per-process Apple80211/IO80211 selector census, `blazer-wifi-census:` at 40/150 s;
HOST 625+343 checks; QEMU 840 s 0 panics but Home NOT drawn in QEMU, comparison runs cut by the m1box shutdowns). The W4 `wlan` entry + wifid start
was already physical in integ-7, so nothing was added for it. Transmits as integ-7.
**m1box thermal shutdowns 2026-11-14 00:34/00:42/00:51** (`SMC Thermal pressure initiated Sleep`, fans at max): no QEMU/builds there until checked.
Fleet coordination, method and per-lane state: `/data/work/hk-fleet/{BRIEF,FACTS}.md`, `/data/work/hk-<lane>/STATUS.md`.

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
  fence, 0 faults; **int5-r3 PASS (2026-11-04 09:50, queue 2 boot 1)**: 13/14 acceptance rows
  green - softblur-free Home 70 s→1080 s deadline, epoch= honored as the RTC floor
  (`source rtc … (floor image-epoch …)`, publish ok), settings-r1 disabled.plist 7397 B +
  22 applied + MobileSMS/SocialLayer prefs seeded, 0 backboardd/LIBMALLOC/MobileSMS/
  FaceTime/Preferences crashes, Spotlight denied (68). Misses: A4 medialibraryd did not exec
  (resolved 2026-11-14, not a fault: the job is on-demand only and execs within 0.5 s of its
  first client on 8 later boots, e.g. Music in integ-7; int5-r3 had no media client) and the
  R3 recipe's UI walk (Settings/Spotlight shots) was not in the queue argv - both open.
  Receipts: `research/ios26-phaseb-r1/goal-pool/receipts/queue-20261104.md`,
  `gpu5-20261104.md` (rungs 8-9), `int5-20261104.md` (regression),
  `research/ios26-phaseb-r1/int5-r3/receipts/r3-phone-20261104.md`. Built, not booted:
  int4-perf-r1 (governor fix, booting now), gpu7 (rung 10), int4-spotlight-r1,
  SweetSensorHub, nfc2; bt5-r2 (Mac-only) TX approved, bt5-r3 pending the lane
  (rate-limited until Nov 6 22:00 CET); periph-r1 needs an attended rotate.
- **aoc5 panic symbolized (2026-11-04):** panic is `_aoc_xnu_zero`+0x58 -> `_bzero`+0x44,
  DFSC 0x21 alignment fault, far = x->carve+0x40 with x->carve = 0xfffffe304bdd0000:
  bzero takes the DC-ZVA path on the 48 MiB carve and `ml_io_map_wcomb` maps the carve
  with a device-class attribute (DC ZVA to device memory -> alignment fault on the phone;
  TCG does not model it, which is why QEMU passed). Preferred fix: map the carve normal
  cacheable - it is DRAM, not a register window. Receipt:
  `research/ios26-aoc-r1/receipts/aoc5-panic-symbolized-20261104.md` (AoC lane owns aoc6).
- **modem2 rung 5 STOP interpreted (2026-11-04):** halt at `blazer_modem_core.c:1003`,
  detail 0x100106 = the endpoint's own command/status (memory space + bus master set,
  capabilities list present): after link training the modem endpoint configures itself, so
  the as-found survey refused before any BAR write. Rung 5 unexercised. Options for the
  modem lane: PERST re-cold-reset before survey, read-only survey, or scoped force.
  Receipt: `research/ios26-modem-r1/receipts/modem2-rung5-stop-20261104.md`.
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
- **Apps (QEMU, 2026-11-11):** personas were blocked by varfs refusing `renamex_np(RENAME_SWAP)` (errno 45), not by the
  AKS user-session keybag; no SEP decision is needed for this step. With the varfs fix (cc42295 = `ed186e2`, already in the
  int5 line) and `rd=ufsroot0`: INVALID_PERSONA 42 -> 0, lsd aborts 21 -> 0, Calculator/MobileTimer/MobileNotes register
  (`registration_verified:true`) and launch. Not physical. `/data/work/hk-apps-swap/RESULT.md` (m1box).
- **Next kernel `kernel.ios26-knext` (2026-11-11, HOST+QEMU, not booted on the phone):** int5-r3 base (48b121e) + backlight
  calibration v2 (4-byte 16.16 data keys), pmap 64-bit PA, ISB after `AT S1E1W`, `blazer_idle_latency_us` (off by default),
  GPT usable-range check for ios_data. sha256 ff1b4266…5dde, linked on the Mac, all changes verified in the linked binary;
  QEMU apps run PASS, app windows draw content. Owner boot commands: `/data/work/hk-knext/BUILD-RESULT.md` section 6.
  Skeleton overlay (14 missing `/private/var` dirs) and gated `/chosen/osenvironment=main`: `/data/work/hk-skel/RESULT.md`.
- **iOS-configured kernel (2026-11-11, QEMU):** the same source built as iPhoneOS (`CONFIG_JETSAM`, `XNU_TARGET_OS_IOS`)
  links and reaches Home in QEMU with 0 panics after three fixes (export lists, earlier MAC policy registration, `exec`
  console line). Built with upstream clang on m1box (Linux toolchain, 5 min/build); needs a Mac rebuild and a phone A/B
  before adoption. `/data/work/hk-iosconf/RESULT.md`. UniXNU comparison reports: `/data/work/unixnu-align-r1/`.
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
