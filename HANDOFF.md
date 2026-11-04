# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. Owner decision pending: Bluetooth transmit (bt5-r2 is receive-only gate level 1; pairing in
   Settings needs TX gate 2-3). bt5-r2's image is Mac-only (carries the Wi-Fi password).
2. Next unattended `fastboot boot` queue, owner to admit (all built, QEMU-checked, none booted):
   int5-r3 (settings + epoch), int4-perf-r1 (governor demand-rule fix), gpu7 (GPU rung 10:
   carve-out page tables + MMUCACHE + 2 KICKs), int4-spotlight-r1 (Spotlight spin fix),
   SweetSensorHub, nfc2 (ID + NCI). One at a time, return check PASS between boots.
3. Attended: periph-r1 boot needs the owner to rotate the phone on request.
4. Lanes open: aoc5 panicked on its first phone run (unaligned data abort, ramdump in
   `attempts/20261104-051235-a7-aoc5/`, AoC lane symbolizes `kernel.aoc5.unstripped`);
   modem2 rung 5 stopped because the controller was already live at survey (modem lane
   interprets); CA diagnostic answered - no AGXAccelerator, CA selects SWContext
   (`research/ios26-phaseb-r1/goal-pool/receipts/queue-20261104.md`).
5. Apps lane is stopped behind the AKS user-session keybag (owner decision,
   `research/ios26-apps-r1/receipts/h3-static-r12/VERDICT.md`).

Bare `fastboot boot` only, ANDROID_SERIAL set, disks resolved by-name, return check after every boot.

## Latest completed maintenance

- Android restore after the migration, exceptions and the new return-check baseline:
  `research/android-backup-20261103/RESTORE.md`.
- Research cleanup and current archive index: `research/README.md`.
- Removed paths, hashes and reasons: `research/CLEANUP-20261102.json`.

Previous physical milestone history is archived at
`research/journal/HANDOFF-full-20261102.md`; read it only for a named historical
attempt, never as current authorization.
