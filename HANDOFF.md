# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. Attended, owner present: `a7-ios-system-r3` = r1 (5 cores, deadline 300) without `hk_bright=140`; Home expected about 90 s after power-on (`research/ios26-phaseb-r1/home-budget/BUDGET.md`). The black
   screen is backboardd's CoreBrightness NULL read, which happens only when the kernel publishes `AppleARMBacklight`
   (hk_bright) without `backlight-calibration-parameters`: 0 crashes in every boot without it, including the 11-01 Home
   boot; 14-18 in every boot with it (`research/ios26-phaseb-r1/corebrightness/FINDINGS.md`). r2 (deadline 1800) still drew
   0 frames. The proper fix, the 0001 kernel patch publishing the calibration, still needs the XNU compile.
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
