# GOAL.md — Pixel 10 Pro: on-device iOS 26 / Android chooser, isolated storage, then native iOS to 100%

Written 2026-11-02 from a review of all 24 T3 Code sessions since 2026-10-28, the
git history, read-only checks of the phone at 19:40 CET, and one adversarial review.
This is the single brief for an unattended `/goal` run. Where it conflicts with older
storage or dual-boot prose (`docs/DUALBOOT.md`, `research/ios26-dualboot-r5/`, the
GOAL.md trashed on 2026-11-02 19:22), this file wins. `AGENTS.md` still applies;
for this run the owner thread is the coordination thread it names.

## 0. How to start a run

Paste this in a new T3 thread (Claude Opus 5.5 or Fable 5.1, full access):

```text
/goal Follow /Users/andersmadsen/Developer/personal/hackios/GOAL.md as the single accountable owner of this run. Done means GOAL.md section 1 "Definition of done for one run" is satisfied: every Phase A stage marked UNATTENDED is complete with receipts under research/ios26-dualboot-r8/ or stopped under the stop rules of section 1, research/ios26-dualboot-r8/NEEDS-OWNER.md exists, NOTES.md and HANDOFF.md are updated, and the phone is in verified Android or at a reported safe state. After that, spend the remaining budget on Phase B in the order given. Never claim dual boot or any feature works without the acceptance evidence GOAL.md names.
```

Before leaving the phone: plug it into the Mac by USB (fastboot and adb), leave it
booted in normal Android, and unlock it once after plugging in. File-based
encryption keeps `/sdcard` and app data locked after any reboot until the owner
unlocks, so the backup stage (A1) must run before the first reboot. Wi-Fi adb alone
allows only the read-only Android stages; everything physical needs USB. Do not
start other agent threads on this repository while the run is active.

## 1. Mission and definition of done

**End state (several runs):**

1. Power on the phone and a selector screen appears: **Android** or **iOS**, chosen
   with the volume keys, confirmed by the countdown, defaulting to Android after 5 s.
2. Android boots exactly as today from slot b, with its root, apps and data.
3. iOS 26 boots natively from its own partitions, keeps settings and data across
   reboots, and is fast enough to use: Home, Settings, stock apps, touch, display.
4. Neither OS can write the other's storage. Every write path on the iOS side is
   bound to the `ios_*` partitions in code, not by convention.
5. After that, Phase B: native iOS to 100% of the README checklist, fastest first.

**Definition of done for ONE run** (what the goal hook checks; reachable without the
owner and without any destructive step). All of the following:

- Minimum deliverables, which have no stop clause: A2 chooser build with host tests
  passing and the enabled-gate ARM64 symbol list from `llvm-nm`; A4
  `tools/gpt_plan.py` with its tests; the `NEEDS-OWNER.md` packet with exact
  commands. A0 is also a minimum deliverable unless `adb devices` shows no device
  at all; in that case A2 tests its lz4 decoder against
  `backup/boot_b-backup.img` and marks the manifest "stale oracle", and A4 works
  from `research/ios26-dualboot-r7/` facts with the packet saying the dump is missing.
- A0 (phone unreachable only), A1 and A3 complete with receipts, or stopped. A stop
  is one line in `research/ios26-dualboot-r8/STOPS.md` quoting the failing command
  and its output, and never ends host work: after a stop, continue with the
  remaining stages.
- `NOTES.md` current-state lines and `HANDOFF.md` next actions replaced, not appended.
- The phone is booted into verified Android (section 9 return check) with
  force-fastboot OFF, or parked at a reported state (section 3) because the return
  check failed; no lingering QEMU, reader, lock or helper.
- Work completed on branch `ios26` is committed (section 10). No push.

A hard stop (section 3) ends **physical** work for the run and is reported; host work
continues to the budget. A run is never done by declaring the mission complete
without the acceptance evidence named in sections 6 and 7.

**Budget:** record the start time. Do not start new physical experiments after 8
hours of work; finish captures, return the phone to Android, write the packet.

## 2. Lessons from 24 sessions, as rules

What produced the real milestones (XNU 12377 boot, UFS link, panel scanout, touch,
Home screen, five cores, 15-minute runs) was always the same loop: inspect primary
evidence (device state, exact binaries, matching vendor source, the previous failure
capture), change **one** bounded variable, test it on the phone with a hash-bound
image and a timed way back to fastboot, decode the capture, record it. Reusing a
working port (tegu's kernel series) saved days. One operator at the keyboard with
one command per candidate kept the loop fast.

What burned tokens without moving the phone: fleets of 10 to 24 agents with peer
messaging, hash receipts, ownership holds and admission bureaucracy (2026-11-02
morning: five coordinators, fifteen workers, thousands of messages, no new working
feature); goals phrased as "any means necessary", "always 10 agents", or "done only
when X is 100%" (busywork, or an agent refusing in a loop while the goal hook
re-fires); documentation and repository restructuring as a substitute for progress;
reviews of reviews; broad research campaigns.

What caused the only real damage: one approved write of the iOS root into
`userdata_exp.ai` on 2026-11-01, a partition that is part of Android's `/data`,
with no backup of its bytes. Android could not mount `/data` and the phone had to be
factory reset. The rule that follows is absolute: **no write ever touches an extent
Android owns, and every write has a verified rollback before it runs.**

Rules for this run:

1. One owner thread. Helper agents only as short-lived bounded host tasks (section 8).
2. One blocker, one variable, one bounded physical test. Write the hypothesis,
   expected discriminator, acceptance and stop condition before building the image.
3. After FAIL or INCONCLUSIVE: diagnose from the capture. No unchanged retry.
4. Label every result: source, host test, ARM64 object, QEMU, or physical. Only
   physical counts for the README. Observation and inference stay separate.
5. Read what the task needs: this file, `NOTES.md`, `HANDOFF.md`, the one subsystem
   doc, the named receipt. Never ingest `research/` recursively.
6. Prefer the phone's own read-only facilities (root adb, `sgdisk -p`, `lpdump`,
   `/proc`, `/sys`) over building a new diagnostic image when they answer the question.

## 3. Safety (absolute, no exceptions, no reinterpretation)

- The phone is the owner's daily device. Android on slot b, `init_boot_b` (Magisk),
  `vendor_boot_b`, `vendor_kernel_boot_b`, `dtbo_b`, `vbmeta_*`, `super`,
  `userdata`, `userdata_exp.ai`, `metadata`, `misc`, `bl_data`, `frp`, `persist`,
  `efs*`, `modem*`, `trusty*`, `klog`, every `_a` partition, bootloaders, slot
  metadata and firmware are **never written** by an unattended run.
- Unattended physical access is limited to: `adb reboot`, `adb reboot bootloader`;
  `fastboot boot` of one freshly built, hash-bound image at a time; `fastboot
  getvar`; `fastboot reboot`; `fastboot oem force-fastboot on|off` under the rule
  below; read-only adb (`su -c` of `dd if=... | ...` streamed to the Mac through
  `adb exec-out`, `cat`, `ls`, `sgdisk -p`, `sgdisk -v`, `lpdump`, reads under
  `/metadata/ota`, `dumpsys`, `adb exec-out screencap -p > file`, `dmesg`, pulls).
  Never `dd of=`, `screencap <path>` or any redirection to a path on the phone.
  Nothing else.
- Force-fastboot is a persistent bootloader setting and the only bootloader state
  this run may change, because the project's boot tooling has always used it.
  `on` before any `fastboot boot` through `tools/bootios` (which re-arms it) so the
  phone parks in fastboot for capture; `off` only as
  the first step of a section 9 return check. Query it (`fastboot oem
  force-fastboot`) and record the output around each change. The run ends with it
  OFF and Android booted, or reports exactly: "parked in fastboot, force-fastboot ON,
  owner runs `fastboot oem force-fastboot off` then `fastboot reboot`".
- Attended-only, owner types the command after reading the packet: any `fastboot
  flash`, `fastboot -w`, `erase`, `format`, `set_active`, any GPT or raw block write,
  factory reset, OTA, bootloader or firmware change, Magisk or root-hiding changes,
  Android settings or app changes.
- Every physical boot has a timed way back: XNU deadline + PSCI reset, or the
  firmware watchdogs left armed across any chain-load. If the phone does not return
  within the bound, do not improvise: stop physical work, record the state, continue
  host work.
- Hard stops that end physical work for the run: an unexpected reset or write;
  identity mismatch (USB serial hash differs from the A0 baseline); a second adb or
  fastboot client, or another live agent session, on the device; a pending or
  merging Android update (A0); Android failing its return check; thermal guard or
  battery below 30%; any corruption warning.
- Never retry an unchanged candidate. Never substitute an artifact silently. Never
  relax a validator to make a capture pass. Never delete unfamiliar artifacts.
- Keep serials, IMEI, MACs, device dumps, backups, Apple artifacts and keys out of git
  (`.github/scripts/check_tracked.py` runs in the commit hook).

## 4. Authorizations (owner edits this block; agents read it literally)

```text
UNATTENDED, granted 2026-11-02:
  [x] read-only Android via adb root: streamed dd of partitions and GPT blocks to the
      Mac, /proc, /sys, /metadata/ota reads, sgdisk -p/-v, lpdump, dumpsys,
      screencap, dmesg, adb pull and streamed tar of /sdcard and app data for A1
  [x] adb reboot, adb reboot bootloader, fastboot reboot, fastboot getvar
  [x] fastboot oem force-fastboot on|off under the section 3 rule
  [x] fastboot boot of hash-bound images, one at a time, with deadline or watchdog
  [x] QEMU under /tmp/fleet/qemu-guest-slot.lock, one guest at a time
  [x] git add/commit of own completed, tested work on branch ios26 (no push)
  [x] up to 4 concurrent short-lived helper agents, host-only (section 8); zero is fine
ATTENDED, owner runs the command from the packet:
  [ ] GPT rewrite, userdata shrink, recovery factory reset, restore   (A6)
  [ ] fastboot flash ios_system / ios_data                             (A7)
  [ ] fastboot flash boot_b <chooser image>                            (A8)
STANDING GRANT (owner may tick after A7 passes once): writes to partitions named
  ios_system and ios_data are iOS-owned and may be re-flashed unattended.      [ ]
```

## 5. Verified facts (read-only, 2026-11-02 19:40 CET; re-verify cheaply before relying)

**Phone.** Pixel 10 Pro `blazer`, build `google/blazer_beta/blazer:17/DP11.261016.003`
(newer than the factory reference DP11.261002.005 in `research/ios26-dualboot-r4/`),
bootloader `deepspace-17.4-16424240`, slot `_b`. `/proc/bootconfig` says
`device_state=unlocked`, `verifiedbootstate=orange`; `getprop` reports a locked
state because of the owner's pre-existing root-hiding setup, which this project does
not change; trust bootconfig. Magisk 31.1, `su` works for adb shell. Kernel
`6.12.81-android16-6-g61789b3255c8-ab16116373-4k`. adb reachable over Wi-Fi
(192.168.1.228, port changes); USB was not connected at 19:35. `bootctl` is absent;
`sgdisk`, `lpdump`, `resize.f2fs`, `make_f2fs` exist in `/system/bin`;
`snapshotctl` and `bootctl` do not. No update is pending or merging (20:30 CET):
`/metadata/ota/state` is empty, `/metadata/ota/snapshots` is empty and no
`snapuserd` process runs; the `*-cow` entries that `lpdump` shows in `super` are
leftovers. A0 re-checks those three indicators before any reboot (hard stop if any
changes). Streamed reads work: `adb exec-out su -c 'dd if=/dev/block/sda bs=4096
count=1 2>/dev/null'` returned the 4096-byte protective MBR, and LBA 1 starts with
`EFI PART`. CE storage was unlocked (`dumpsys mount` printed `CE unlocked users: [0]`).

**LUN0 storage** (`/dev/block/sda`, **4096-byte GPT LBAs**): 31,147,008 LBAs =
127,578,144,768 B (118.8 GiB). Protective MBR LBA 0, primary header LBA 1, primary
entry array LBA 2..5, first usable LBA 6 (`persist` starts there: LBA 1..5 are the
only primary bytes that may ever be rewritten), last usable 31,147,002, backup array
31,147,003..31,147,006, backup header 31,147,007. 35 partitions in FBPT order
(`research/ios26-dualboot-r7/gpt-r5a-trace/fbpt-correlation.txt`): persist, klog,
misc, frp, efs, efs_backup, modem_userdata, trusty_persist, trusty_userdata,
metadata, the `_a` set (boot 64 MiB, init_boot 8, vendor_boot 64, vendor_kernel_boot
64, dtbo 16, vbmeta×3, pvmfw 1, modem 300), the same `_b` set, super (7.94 GiB),
ufs_internal (4 MiB), bl_data (1 MiB), **userdata_exp.ai (8 GiB), userdata
(101.3 GiB, FBPT-implied LBAs 4,597,990..31,147,002, ends at last usable)**. No
unallocated space. `super` holds only the slot-b logical partitions plus COW
snapshots, about 1.5 GiB free. sdb and sdc are 64 MiB boot LUNs, sdd 4 MiB. The
r5a strict-GPT failure has a leading explanation, not a proof (a packed entry copy
in the backup header block, `research/ios26-dualboot-r7/gpt-r5a-trace/diagnosis.json`);
the complete table has never been captured. A0 captures it with streamed `dd`.

**Android /data** is `dm-65`, f2fs; `/sys/block/dm-65/slaves` lists only `sda35`
(`userdata`), and the alias partition `userdata_exp.ai` (`sda34`) is attached by the
f2fs mount itself and appears as the alias file `/data/userdata_exp.ai` (8 GiB,
root-owned, created at the 15:18 reset). Both are Android's.
114,582,612 KiB total, 65,808,676 KiB used including the alias file, 48.7 GB free;
`/data/media` 28.5 GB, `/data/app` 16.9 GB, `/data/data` 4.1 GB. Mac free space
155 GiB. Backups: the owner's Google backup, the owner's own tools on this Mac
(Me0wdump, integritybox, HMA), and `research/factory-alias-restore-r1/HANDOFF.md`
for today's restore receipts. `backup/boot_b-backup.img` and `vendor_boot_b-backup.img`
are from 2026-10-22 and an older build (kernel_size differs): stale, do not use.

**ABL to kernel contract** (what makes the chooser cheap). ABL loads the `boot_b`
kernel and jumps to it at EL2 on this device (`shim/start.S:30`; the file's line 3
comment still says EL1 and is stale), `x0` = FDT; MMU and D-cache off at that entry
is inferred from the Linux boot protocol ABL honours, not measured (A3 records the
SCTLR_EL2 value in a stamp). Before that it has
assembled what Linux needs from `init_boot_b` (ramdisk 2,380,068 B, Magisk-patched),
`vendor_boot_b` (v4 header, vendor ramdisks, bootconfig) and `dtbo_b`: `/chosen`
carries `bootargs`, `kaslr-seed`, `linux,initrd-start`/`-end`, `display`, `config`,
`plat`; `reserved-memory` carries `abl@be000000`, `ramoops@95200000`,
`bldr_log_reserved@95600000`, `boot_metadata@543e000`, `gpu_fw@b9f00000`, aoc,
tpu, modem and other regions (A0 records all with addresses). Earlier `fastboot
boot` captures place the initrd at 0x86000000 inside the 0x80000000 window
(`shim/loader.c:200`). Inference to prove in A3, not a fact: for a `fastboot boot`
image whose boot header has `ramdisk_size` 0, ABL assembles the same generic
(`init_boot_b`) plus vendor ramdisks and bootconfig as for a normal boot. The
discriminator is `chosen/linux,initrd-start`/`-end` equal to the normal-boot values
captured in A0. Current project images carry a 100-byte ramdisk (`ramdisk_size`
100); the chooser image must carry none.

**Stock kernel.** `boot_b` is a v4 Android boot image: `kernel_size` 20,437,225 B,
`ramdisk_size` 0, kernel is an lz4-legacy stream (magic `02 21 4c 18`) of an arm64
`Image` with `text_offset` 0, `image_size` about 41.2 MiB on the stale backup (read
the field from the A0 dump; it includes BSS and is the placement size), header flags
bit 3 set (placeable at any 2 MiB-aligned address), KASLR via `kaslr-seed`. Android
expects entry at EL2 (pKVM: `kvm-arm.protected_modules=...` in bootargs). Use only
the kernel from the A0 `boot_b` dump; `boot_a` holds a different build whose
modules do not match slot b.

**Sizes.** The current project images are 64 MiB files (padded to the partition);
their kernel blob is 27,880,416 B with the XNU payload embedded in it (p32 kernel
25,402,136 B plus ADT and metadata; `tools/image_tool.py:586` checks the embedded
`TEGUPLD1` envelope; the shim reads it first, `shim/loader.c:102-107`). Adding the
19.5 MiB stock lz4 kernel gives about 46 MiB, inside the 64 MiB `boot_b` partition
with about 18 MiB to spare. Payload limits are in `tools/mkpayload.py`.

**Shim and tools.** `tools/image_tool.py` builds the root `shim/` (line 14;
`research/ios26-bootchain-r1/shim` is a diverged copy, ignore it). The shim has: FDT
parsing and memory map, `fdt_find_framebuffer`, 8×16 font console on the panel, DPU
scanout takeover, firmware watchdog survey, pat ladder and quiesce (`shim/shim.c:61`,
`wdt.h`: ABL hands over armed cluster watchdogs of roughly 24 s and 30 s), UFS link
and READ(10) with a deliberate "no WRITE ever built" rule (`shim/tgl_ufs.c:224`,
keep it), EL2 to EL1 drop and XNU payload loading, PSCI reset. The volume keys were
read in an XNU probe (`keys-probe-r1`: volume seen, power key not seen); the shim
needs its own pad read, and the power key is not a proven input. Every UFS image
recipe hardcodes `blazer_ufs_root=userdata_exp.ai` (`tools/image_tool.py:26,34,235,240`):
that must become a parameter bound to `ios_system`. XNU's persistence writer
(`blazer_persist`, `bsd/dev/hakios.blazer_persist_disk.inc` in
`research/ios26-release-r1/combined/ios26-p31r1-all-in-one.patch`) targets free
blocks of the root partition; it must be rebound to `ios_data` and hard-limited (A7).
Kernels: `research/ios26-release-r1/artifacts/kernel.ios26-p32` is the latest UI
kernel. `tools/bootios` boots, `tools/capture-fastboot.py` and
`tools/boot-summary.py` read. Canonical roots are listed in `NOTES.md`.
`tools/dualboot.py inspect-image` is the strict GPT validator (22 tests); it needs a
disk-sized sparse file (A0 shows how). `tools/test_bootplan.py` has one pre-existing
error unrelated to this work.

**Known unknowns to settle in A0 and A3, not to assume:** exact LBAs of every
partition from the real GPT; the FDT location and the kernel load base ABL used;
whether `chosen/display` or an FDT framebuffer node lets the shim draw the menu into
the buffer ABL already scans out (preferred: no DPU reprogramming) or whether the
existing scanout takeover is needed and whether Linux's display driver tolerates it;
whether the pending update in `super` is merging.

## 6. Phase A: dual boot

### Architecture (chosen because every step is reversible and Android is never touched)

- **Chooser** = the hackios shim, later installed as `boot_b`'s kernel (A8), first
  tested with `fastboot boot` (A3). At EL2, before any XNU-specific takeover, it draws
  "Android / iOS" on the panel, polls the volume keys, defaults to Android after 5 s.
  - **Android path:** decompress the stock lz4 `Image` carried inside the chooser
    image as an embedded segment that the XNU loader ignores, to a 2 MiB-aligned base
    chosen from the FDT memory map that does not overlap the FDT, the initrd,
    `reserved-memory`, the shim's own image or the copy loop, sized by the Image
    header's `image_size`; leave the FDT and initrd exactly as ABL built them; clean
    and invalidate caches; MMU off; interrupts masked; leave both cluster watchdogs in
    the ABL-entry state (never call the quiesce path on this branch) and pat once
    before the jump; jump with `x0` = FDT at EL2. ABL already did AVB, bootconfig,
    DTBO and ramdisk assembly for slot b: this is a kernel swap, not a bootloader.
  - **iOS path:** the existing payload route (`rd=md0 blazer_ufs_mountroot=1`) with
    `blazer_ufs_root=ios_system`, `/var` on `ios_data`.
  - The chooser image has `ramdisk_size` 0 and a boot-header cmdline equal to the A0
    `boot_b` header's; it is built without the USB console, UFS link, DPU/DCS
    takeover, fastcore CPU_ON and clock changes on the Android branch.
- **Storage:** shrink `userdata` once and append `ios_system` and `ios_data` in the
  freed tail (A6, attended). Nothing else moves. Android re-creates `/data` at the new
  size through its own recovery reset, which this phone did successfully today.
- **Isolation:** the shim never writes; XNU's UFS writer refuses any LBA outside the
  `ios_*` extents (allowlist by GPT name resolved at boot, checked on every write,
  panic on violation); Android never mounts `ios_*` (no fstab entry, project type GUID).
- **Recovery at every stage:** `fastboot boot` never changes the disk; A8's only
  change is `boot_b`, reversible with the A0 `boot_b` dump; A6 is reversible with the
  raw GPT dump, the factory image and the backups. A bootloader flash or an OTA
  rewrites the GPT from the bootloader's FBPT and would drop `ios_*`, after which
  Android's grow flag lets `/data` expand over them: the owner disables automatic
  updates before A6 and the packet states this.

### A0. Truth capture (UNATTENDED, read-only, Wi-Fi adb is enough; before any reboot)

Do, under `research/ios26-dualboot-r8/truth/`, streaming every block device read
through `adb exec-out` so nothing is written on the phone, for example:

```sh
adb exec-out su -c 'dd if=/dev/block/sda bs=4096 skip=0 count=8 2>/dev/null' > truth/lba-0-7.bin
adb exec-out su -c 'dd if=/dev/block/sda bs=4096 skip=31146990 count=18 2>/dev/null' > truth/lba-31146990-31147007.bin
adb exec-out su -c 'dd if=/dev/block/by-name/boot_b bs=4096 2>/dev/null' > truth/boot_b.img
```

Dump `boot_a`, `boot_b`, `init_boot_b`, `vendor_boot_b`, `vendor_kernel_boot_b`,
`dtbo_b`, `vbmeta_b`, `vbmeta_system_b`, `vbmeta_vendor_b`, `misc`, `bl_data`;
`/proc/device-tree` as a tar, `/proc/bootconfig`, `/proc/cmdline`, `/sys/firmware/fdt`;
`sgdisk -p /dev/block/sda`, `lpdump`, `ls -la /metadata/ota /metadata/ota/snapshots`
and `cat /metadata/ota/state` (both empty and no `snapuserd` process means no pending
update), every `/sys/block/sd*/size` and `/sys/block/sd*/queue/zoned`,
`/sys/block/dm-65/slaves`, `df -k /data`, `ls -la /data/userdata_exp.ai`,
`getprop ro.boot.slot_suffix`, `chosen/linux,initrd-start` and `-end` as hex, and
root `dmesg` lines about initrd, framebuffer, "Command line", pstore, watchdog and
"Protected nVHE". Verify the USB serial hash against
`research/ios26-dualboot-r7/android-baseline-r1/baseline.json` when USB is present.
Confirm CE storage is unlocked before A1: `dumpsys mount | grep 'CE unlocked users'`
must print `[0]`. Hash everything into `SHA256SUMS`; redact serials in anything tracked.

Then assemble a sparse disk for the validator and run it:

```sh
truncate -s 127578144768 truth/disk.sparse
dd if=truth/lba-0-7.bin of=truth/disk.sparse bs=4096 seek=0 conv=notrunc
dd if=truth/lba-31146990-31147007.bin of=truth/disk.sparse bs=4096 seek=31146990 conv=notrunc
python3 -I tools/dualboot.py inspect-image truth/disk.sparse
```

Evidence: strict validation of both headers and both arrays (first complete GPT
acceptance, or a documented media-padding FAIL kept as observation); a partition
table JSON with exact first and last LBA per entry; the boot-image headers parsed
(`kernel_size`, `ramdisk_size`, cmdline, lz4 magic, Image `image_size` and flags);
the FDT decoded (`chosen`, `memory`, `reserved-memory`, framebuffer nodes) into
`truth/boot-contract.json`; the three update indicators showing nothing pending.

Stop: a pending or merging update, a second device client, or a serial mismatch.
A strict GPT FAIL on real bytes is recorded and does not stop anything: the chooser
does not need GPT acceptance, and A4 handles the padding with an explicit choice.

### A1. Backup staging (UNATTENDED, read-only on the phone, before the first reboot)

Do: `adb pull /sdcard` and a root tar streamed through `adb exec-out` of
`/data/data`, `/data/user_de/0`, `/data/misc/adb`, `/data/adb` (Magisk modules and
config), plus the `_b` boot-chain dumps from A0, into
`research/android-backup-20261102/` with hashes and a manifest. Record what this
cannot cover (hardware-backed keys, apps that re-register per device). Use DE-only
canaries for later return checks: a `pm list packages -f` digest, sha256 of
`/data/system/packages.xml`, and three files under `/data/user_de/0`.

Stop: CE storage locked, free space on the Mac under 20 GiB after the pull, or a pull
that errors. Record the stop and continue with A2.

### A2. Chooser v1: Android chain-load (UNATTENDED, host)

Do, in `shim/` behind a new build gate (default off, `TGL_CHOOSER=1`):
`chooser.c` (menu state machine, countdown, volume-key polling through a shim pad
read derived from the pinned vendor pinctrl facts and the `keys-probe-r1` capture,
rendering with the existing font console into ABL's framebuffer or the existing
scanout path), `lz4.c` (lz4 block decompressor for the legacy frame, host-tested
against the real `boot_b` kernel with the system `lz4` as oracle), `linux_chain.c`
(placement check against the FDT memory map and reserved regions, copy or
decompress, cache maintenance, EL2 jump), plus `tools/image_tool.py image NAME
--chooser --stock-kernel truth/boot_b.img --stock-kernel-sha ... --ios-root
ios_system` that packages the stock kernel as an embedded segment next to the XNU
payload, sets `ramdisk_size` 0, copies the stock header cmdline, and refuses if the
result exceeds the 64 MiB partition or the payload limits. First candidate ships
with the iOS entry disabled (selecting it shows "no iOS root yet" and continues to
Android) so A3 tests one thing.

Evidence: host tests for the menu, lz4 and placement logic; enabled-gate ARM64
objects contain the expected symbols (`llvm-nm` list saved); `shim/build.sh` tests
pass; `image_tool check` PASS; `manifest.json` records the stock kernel hash. No
stop clause: this stage is host work and must be finished.

### A3. Chooser v1 on the phone (UNATTENDED if USB is connected)

Preflight: section 9 step 1. `adb reboot bootloader`, set force-fastboot ON,
`tools/bootios research/images/chooser-v1-r1/boot.img chooser-v1-r1 --wait 600`.

Test 1: menu renders, countdown picks Android, Android boots. Test 2: volume-key
selection works. Test 3: `fastboot oem force-fastboot off` with the query output
recorded, then a bare `fastboot boot` of the same hash-bound image (not `bootios`,
which re-arms the flag), confirm the Android chain and that a plain Android boot
follows the next reset. After each boot: section 9 return check.

Evidence (all physical): shim stamps for menu shown, key events, selection, kernel
placement, watchdog state, jump; then Android `sys.boot_completed=1`, slot `_b`,
`/data` mounted with the baseline size, DE canaries equal to A1, `dmesg` with the
stock kernel version, `chosen/linux,initrd-start`/`-end` equal to the A0 values,
"Protected nVHE mode initialized", the watchdog driver probe and its time after the
jump (refuse A8 later if that exceeds half the shorter cluster timeout),
`adb exec-out screencap -p` not black, adb over USB. Three consecutive Android chains without manual help.

Stop: a chain that hangs past the watchdog bound, any return-check mismatch, any
sign the shim wrote to UFS. Diagnose from the stamps; one variable per candidate; at
most four candidates per run.

### A4. Storage plan and runbook (UNATTENDED, host, no stop clause)

Do: `tools/gpt_plan.py` (tracked, tested): read the A0 dump, verify strictly, emit a
new table that keeps every entry byte-identical except `userdata` (same first LBA,
new last LBA) and two appended entries `ios_system` and `ios_data` with fresh unique
GUIDs, a project type GUID, 8 MiB alignment, both headers with CRCs, the backup copy
at its existing LBAs. Output bytes are allowed only in LBA 1..5 and
31,147,003..31,147,007; the tool refuses any byte inside 6..31,147,002. `--verify`
diffs old and new and refuses anything but the intended changes. Emit
`gpt-new-primary.bin` (LBA 1..5), `gpt-new-backup.bin` (LBA 31,147,003..31,147,007),
both padding variants for the backup header block (bytes as found on media, and the
UEFI zero tail) for the owner to choose, and the exact owner commands: re-dump and
byte-compare the target blocks immediately before each write; the no-op proof (write
the identical original LBA 1..5 and backup blocks, reboot, section 9 return check);
the real write with `dd of=/dev/block/sda bs=4096 seek=<lba> conv=fsync` as root, then
`sgdisk -v`; the recovery factory reset (the path proven on this phone today, not
`fastboot -w`); and the rollback (write the original dump back; worst case the
factory image `flash-all`, which also wipes). Propose the split with the real
numbers: `ios_system` ≥ 24 GiB (the 20 GiB apps root plus headroom), `ios_data` 8 to
16 GiB; Android currently holds about 55 GiB of real data. Give two concrete options,
for example Android 69 GiB / iOS 24 + 8, and Android 61 GiB / iOS 24 + 16.

Evidence: tests covering a valid rewrite, alignment, overlap, CRC, header mismatch,
truncated input, wrong disk GUID, a byte outside the allowed LBAs; `sgdisk -p` of
the proposed table reproduced on a loop image on the Mac.

### A5. The owner packet (UNATTENDED, host)

Write `research/ios26-dualboot-r8/NEEDS-OWNER.md` in the section 10 format, update
`NOTES.md`, `HANDOFF.md` and `docs/DUALBOOT.md`, commit. This is the end of the
unattended Phase A scope.

### A6. Migration (ATTENDED, owner runs each command from the packet)

Order: disable automatic updates; no-op GPT rewrite and return check; new GPT write
and `sgdisk -v`; `adb reboot recovery` and the recovery factory reset; first Android
boot; setup and restore; verify slot b, `/data` size equals the new `userdata` plus
alias, Magisk and root. Then a fresh A0-style dump of the new table becomes the new
baseline.

### A7. iOS on its own partitions (first flash ATTENDED, then standing grant)

Do: `fastboot flash ios_system` with the canonical phone root (or the apps r6 root
once it fits), whole-image readback check (`tools/fullcheck.py` recipe rebound to
`ios_system`), `fastboot boot` of the p32-class UI image with
`blazer_ufs_root=ios_system` and `/var` persistence rebound to `ios_data` **with the
allowlist enforced in the kernel** (ARM64 object and symbol check, and a QEMU
negative test that a write outside the allowlist panics, before the first physical
boot). Then: Home and Settings reached, a setting changed, reboot, setting persisted;
the Android return check passes after every iOS boot.

### A8. Install the chooser (ATTENDED flash of `boot_b` only)

Do: owner runs `fastboot flash boot_b research/images/chooser-vN/boot.img` after A3
and A7 both pass with the final image (iOS entry enabled). Rollback command in the
packet: `fastboot flash boot_b research/ios26-dualboot-r8/truth/boot_b.img`. Then
unattended: ten alternating cold boots Android/iOS/Android via the menu, each with
the return check; an interrupted-boot test (power held during iOS boot) ends in the
menu again.

### A9. Hardening (UNATTENDED, after A8)

Menu polish (battery guard, "hold Vol-Up for fastboot" hint), chooser self-test
stamps, `docs/DUALBOOT.md` rewritten to describe what exists, README status rows
updated only from physical evidence.

## 7. Phase B: native iOS 26 to 100%

Before A7 only lanes 1 and 4 are reachable, in QEMU. After A7, work in this order,
each as its own one-variable loop with physical acceptance (section 9), and stop a
lane after two materially different failed hypotheses:

1. **Stable compositor and startup.** The early `backboardd` NSURL-nil abort and
   respawn, the CoreBrightness Q16.16 lead (`research/ios26-opt-20261102/`), Spotlight
   hogging the CPU. Acceptance: 15 minutes at Home and Settings with zero respawns,
   measured frame completion, touch to Home under one second.
2. **Persistent, real settings on `ios_data`**: Wi-Fi list, wallpaper, clock, lock
   state survive reboot; `fsck` clean after ten reboots.
3. **Fast**: five A725 under the UI with the governor, then the CPU health gates in
   `docs/CPU.md` before any higher clock; report time-to-Home, app launch time and
   scripted tap latency as numbers in `docs/status.json`.
4. **Stock apps**: `docs/IOS-APPS-IDENTITY.md`; the H1 placeholder hypothesis was
   tested in `registration-h1-r9` (read its result first); next is the
   MobileInstallation path. QEMU first, phone after `ios_system` holds the apps root.
5. **USB networking to the Mac (ECM)**, then real time sync and a first TCP session
   from iOS; this unblocks many later lanes.
6. **Wi-Fi join**, Bluetooth pairing, then cellular (`docs/CONNECTIVITY.md`).
7. **GPU**: interpret the 112-byte `DEBUG_DUMP`, strict firmware health, one owned
   compute shader with readback, then Metal (`docs/NATIVE-METAL.md`). Long lane; do
   not let it starve lanes 1 to 6.
8. Sensors, audio, haptics, keys, display refresh, battery presentation, the rest of
   the README table in order of user value.

Out of scope, do not attempt: Apple activation, iMessage, App Store, SEP or identity
emulation, Face ID or fingerprint, cameras.

## 8. Helper agents

The owner thread does all phone, QEMU, git and integration work itself. It may run
up to four short-lived helper agents at a time, each with one bounded host-only
question or deliverable, the exact files and evidence to read, the output format and
a stop rule. Good uses: decode a capture against a format spec; write and run tests
for one module; trace one register sequence in pinned vendor source; review one
patch adversarially. Bad uses: "work on GPU", peer coordination, summaries of
summaries, anything that needs the device. Helpers end within the owner's turn,
report in plain language with file paths, and their claims are checked against raw
evidence before they are recorded. Zero helpers is a fine choice.

## 9. Physical experiment protocol

1. Preflight: one Pixel on USB, serial hash equals the A0 baseline, no other adb or
   fastboot client, no other live agent session touching the repo, battery ≥ 30%,
   no pending update (A0).
2. Bind before boot: source commit or patch hash, kernel hash, image hash, root or
   stock-kernel hash, exact argv, gates, CPU set, deadline, expected discriminators,
   stop condition, rollback. Write it to the attempt directory first.
3. Boot with `tools/bootios`; wait the bound; capture with the project readers; save
   raw before parsing; decode; label physical.
4. Return check after every boot that was meant to end in Android, and after every
   XNU boot once per run: `fastboot oem force-fastboot off` if it is on, `fastboot
   reboot` or the chooser default, `adb wait-for-device` over USB,
   `sys.boot_completed=1`, slot `_b`, `/data` mounted with the baseline size, DE
   canaries equal to A1, `/data/userdata_exp.ai` present, Magisk `su` works,
   `adb exec-out screencap -p` not black, `dmesg` shows "Protected nVHE mode initialized" and the
   watchdog probe. A mismatch is a hard stop.
5. Rest the phone 15 minutes after any run of 15 minutes or more. Thermal guard
   armed on every UI boot.
6. Record the attempt in `research/ios26-dualboot-r8/attempts/<name>/` (image, hashes,
   capture, verdict) and one line in `RESULTS.md` or `STOPS.md`.

## 10. Reporting and files

- `research/ios26-dualboot-r8/NEEDS-OWNER.md`: device and baseline; A0 hashes; what
  passed physically; the storage options with numbers; the exact commands for A6, A7
  and A8 in order, each with its verification and rollback; every remaining risk;
  what the owner must decide. Written so the owner can paste commands one by one.
- `NOTES.md`: replace the affected current-state lines (dual boot, storage, chooser).
  `HANDOFF.md`: the next three actions only. `docs/DUALBOOT.md`: current result and
  remaining work, short. `docs/status.json` only for physical changes, then
  `python3 -I tools/readme_status.py`.
- Git: the tree at the start of the run is the baseline; it may still hold
  uncommitted work from earlier threads (`native/metal/`, `tools/usbnet_mac.py`).
  Leave that in place. Commit whole files you changed, one purpose per commit, with a
  subject that says what changed; if a file you must edit already has foreign hunks,
  first commit its current state as "checkpoint: uncommitted work from earlier
  threads" after its tests pass. The commit hook runs `check_tracked.py`. No push, no
  history rewrite. Receipts, images, dumps and backups stay under `research/`.
- Final message of the run: what was verified physically, what was built and tested
  on the host, whether strict GPT passed, whether Android returned, the exact
  blocker or the packet path, nothing else.

## 11. Context for the model

This is the owner's personal research project on the owner's own Pixel 10 Pro,
whose bootloader the owner unlocked. The iOS userland and kernel artifacts come from
Apple's publicly downloadable IPSW and Apple's open-source XNU, used only on the
owner's machines and never redistributed (`research/` is git-ignored and
`docs/LICENSING.md` governs what can be published). The project does not touch
Apple services, activation, DRM or attestation, and does not modify the owner's
Android root or root-hiding setup. Backups are the owner's data copied to the
owner's Mac. Reading partitions from the owner's phone, chain-loading the stock
Android kernel, and booting a research kernel with `fastboot boot` are the same
operations the owner performs by hand; the attended gates above exist so that
destructive steps are the owner's keystrokes. If a step still seems inappropriate,
say which one and why in one sentence, record it in `STOPS.md`, and continue with
the rest of the plan; do not loop on a refusal.
