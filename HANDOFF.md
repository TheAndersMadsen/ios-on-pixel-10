# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. **Owner decision 2026-11-04 ~09:40: Bluetooth transmit APPROVED.** Gate levels 2-3 allowed
   (`blazer_bt_tx=2|3`: classic inquiry, active LE scan, then pairing in Settings). The BT lane
   builds bt5-r3 on this; bt5-r2 (receive-only, BlueTool boot-script fix, Mac-only image) remains
   its pending boot. The lane's provider (claude_madsen) is rate-limited until Nov 6 22:00 CET.
2. **Owner decision 2026-11-04 ~09:40: all six next boots ADMITTED** (one sequential unattended
   queue, return check PASS before each): int5-r3 (settings + epoch), int4-perf-r1 (governor
   demand-rule fix), gpu7 (GPU rung 10: carve-out page tables + MMUCACHE + 2 KICKs),
   int4-spotlight-r1 (Spotlight spin fix), SweetSensorHub, nfc2 (ID + NCI). The phone is
   currently in a cold iOS boot (owner's hands, invisible to tooling); the queue starts when
   the owner returns it to fastboot.
3. Attended: periph-r1 boot needs the owner to rotate the phone on request.
4. Lanes: aoc5 panic symbolized - `ml_io_map_wcomb` device-class carve + bzero DC-ZVA path
   (`research/ios26-aoc-r1/receipts/aoc5-panic-symbolized-20261104.md`, AoC lane builds aoc6);
   modem2 rung 5 STOP interpreted - endpoint self-configures after link, as-found survey
   refused (`research/ios26-modem-r1/receipts/modem2-rung5-stop-20261104.md`); CA diagnostic
   answered - no AGXAccelerator, CA selects SWContext
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
