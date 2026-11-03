# m1box QEMU rig calibration (2026-11-03)

Host evidence only: QEMU on m1box (Apple M1 Max, Asahi Linux, QEMU 11.1.3 from Arch Linux ARM packages in
`/data/hackios-qemu/prefix`). Says nothing about Tensor or the phone. Reference: the Mac's
`registration-umdinit-r12d` (QEMU 11.1.2 Homebrew, TCG, intent and console copied to `/data/hackios-qemu/ref-r12d/`).
All three m1box runs replay that intent: kernel `kernel.ios26-p29` (5aad8978…), root `apps-umdinit-r12.img`
(be81a0f9…), overlay `hgltrack-rebuilt.ovl` (61c38161…, guest hash 40ac50a794bda37b), `--window-gib 28 --ramdisk-root`,
the r12d boot-args (`ref-r12d/args-tail.txt`). A dry run had reproduced r12d's ADT byte for byte except
`chosen/random-seed`, and the same addresses and QEMU argv (rig README).

## Verdict

**KVM does not boot.** **TCG is equivalent in boot order to the Mac, and faster.** The loop runs on TCG; KVM is not used.

## KVM: `runs/cal-r12d-kvm` (accel kvm, timebase 24 MHz)

- Console (8 lines) ends at `TEGU-XNU EARLY 8: leaving bootstrap console mapping`; no `launchd` line, no panic text.
- No exception line is printed. At the end, every sampled PC (`pcs.txt`, 120 samples) is `0xfffffe000797e7d4`, which is
  `_el1_sp1_synchronous_vector_long_invalid_kstack` after `fleh_synchronous_sp1` (llvm-nm of
  `kernel.ios26-p29.unstripped`): a synchronous exception taken while already on the exception stack, with an invalid
  kernel stack. `registers.txt`: x1 = x15 = `0x96000006` (ESR shape: data abort, same EL, level-2 translation fault).
- Ended by the harness on `uart idle 120s` (exit 0). Time to first launchd line: never.
- First exception line: none printed; the stop is the nested-exception loop right after `arm_vm_init` leaves the
  bootstrap console mapping.

## TCG: `runs/cal-r12d-tcg` and `runs/cal-r12d-tcg-b`

`cal-r12d-tcg` booted (4,212 console lines) but the harness ended it at 120 s on `uart idle` (`uart.log` stays empty on
this rig; the console comes from ramoops). `cal-r12d-tcg-b` changed only `--idle 0 --runtime 420` (intent
`intent-cal-r12d-tcg-b.json`). Comparison by `/data/hackios-qemu/compare.py`, full output `compare-tcg-b.txt`:

| Measure | Mac r12d | m1box TCG (tcg-b) |
| --- | --- | --- |
| First launchd line (guest clock) | 5.0 s | 1.8 s (host 2.0 s) |
| usermanagerd / lsd / backboardd / SpringBoard first seen | 5.6 / 26.4 / 17.0 / 18.3 s | 2.0 / 15.3 / 2.6 / 3.1 s |
| Early kernel milestones in order | 18 | 18, same order (18/18 prefix) |
| First 20 launchd subjects (boot tasks, daemons) in order | list in compare output | identical list, same order |
| Boot tasks done / skipped | 10 / 50 | 10 / 50 (same names) |
| `Unable to find persona` lines up to guest 300 s | 141 | 281 |
| panic / exception lines up to 300 s | 0 / 0 | 0 / 0 |

The first 20 distinct milestones, in order, for both: `system, exclaves-boot, fsck, mount-phase-1, data-protection,
finish-obliteration, detect-installed-roots, select-boot-mode, commit-boot-mode, restore-datapartition, mount-phase-2,
init-with-data-volume, fixup-mobile-tmp, MSUEarlyBootTask, MobileAssetEarlyBootTask, fips, keybag, usermanagerd,
dirs_cleaner, dirs_cleaner-usr`.

Count markers within a fixed guest time are higher on m1box because the guest gets further per guest second (the
persona lookups repeat with time); compare causes and orders, not raw counts, across the two hosts.

## Caveats

- Harness version: `tools/qemu-ufsroot.py` was edited at 12:28:40, after `cal-r12d-tcg-b` started (12:27:37) and before
  r14 (12:33). The calibration ran sha256 `7f7acb2d…` (read 12:27); later runs use `448f6135…`, which is the version
  adopted into `tools/m1box/`. The change was not made by this run's owner thread and its diff is not recoverable.
- Console hashes: ref `8f9f01f0…`, tcg-b `0b75c72e…`, tcg `1dbb265c…`, kvm `b51b42dd…` (first 16 hex of sha256).
