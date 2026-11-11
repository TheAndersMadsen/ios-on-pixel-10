# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

0. **2026-11-11, attended, owner present:** boot `a7-ios-system-knext-r1` (int5-r3 recipe, only the kernel swapped to
   `kernel.ios26-knext` ff1b4266…; `rd=ufsroot0`). Commands and accept rows: `/data/work/hk-knext/BUILD-RESULT.md`
   section 6 (m1box). Then A/B: skeleton overlay `int5-r3-skel-r1.ovl` (`hk_overlay=0xA1080081`), then the iOS-configured
   kernel after a Mac rebuild (`/data/work/hk-iosconf/RESULT.md`). Item 6 below (apps behind the keybag) is superseded:
   the blocker was varfs RENAME_SWAP. Items 1-5 date from 2026-11-04 and need re-confirmation by the owner.

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
5. Tools lane, pre-existing CI red (flagged 2026-11-04, not tonight's work):
   `tools/test_boot_summary.py` RealAttempts tests fail/errors against the old on-disk
   attempts (KeyError 'match') — `boot-summary.py` only sets `kernel["match"]` when a
   `--mach` kernel exists, and the November-1 HANDED_OFF attempts predate that. Expectation
   drift from `fab03af`. Not blocking docs commits (readme_status --check and check_tracked
   pass); the tools owner aligns the test or the summary key.
6. Apps lane is stopped behind the AKS user-session keybag (owner decision,
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
