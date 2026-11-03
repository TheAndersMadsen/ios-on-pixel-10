# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. Attended, owner present: `a7-ios-system-r2` = r1 with only `--phone-deadline 1800` (A7-READY step 6). The black
   screen was the 300 s deadline: Home came at about 10 min with deadline 1800 (2026-11-01). backboardd's
   CoreBrightness NULL read (unslid 0x1e2746924) is the same as in p32 and is not the blocker. `research/ios26-phaseb-r1/A7.md`.
2. Physical, attended: chooser volume keys (r8 line) and the iOS entry from the chooser (r11 display handback works).
3. After a visible A7 boot: a physical ios_data persist test (QEMU negative test PASS,
   `research/ios26-dualboot-r8/ios-data-persist/NEGATIVE-r1.md`); `image_tool` refuses `blazer_persist` until then.
4. Apps lane is stopped behind the AKS user-session keybag (owner decision,
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
