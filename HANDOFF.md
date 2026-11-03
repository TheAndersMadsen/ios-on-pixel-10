# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. Done: `a7-ios-system-r3` reached Home from ios_system (owner confirmed). Next attended boots, all bare
   `fastboot boot`: chooser `chooser-v1-r12` volume keys (`research/ios26-dualboot-r8/keys/BOOT-r12.md`), then the
   chooser-iOS image built from r3's recipe (`research/ios26-dualboot-r8/chooser-ios/DESIGN.md`, C1 Android by timeout,
   C2 iOS picked). Host: build the 0001 backlight calibration kernel patch and hk_accel_once on the Mac.
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
