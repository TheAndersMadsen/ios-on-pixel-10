# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. Attended, owner present: chooser-v1-r10 (stock DPU quiesce before the display release) and/or A7 (flash
   ios_system, read back, boot `a7-ios-system-r1`). Paste-ready commands and stop rules:
   `research/ios26-dualboot-r8/NEEDS-OWNER.md` sections 4 and A7. Bare `fastboot boot`, ANDROID_SERIAL set.
2. Apps lane (QEMU): repeat r13's route (`rd=ufsroot0`, `research/ios26-apps-r1/receipts/h3-static-r12/result-r13.json`)
   with the r11g/r11h os_log mirror for lsd and usermanagerd (one diagnostic change) to read why lsd aborts and
   whether `usersession.kb` was saved (ios-sweet: HFS has no RENAME_SWAP, errno 45, already seen in dirs_cleaner).
3. Host: the visible menu (r6 + `tgl_dcs_run` full-screen layer, `menu-ui/SCANOUT-PATH.md`), the volume-key pad
   read, and a kernel link plus QEMU negative test of XNU dd000c8 (ios_data persist).

## Latest completed maintenance

- Android restore after the migration, exceptions and the new return-check baseline:
  `research/android-backup-20261103/RESTORE.md`.
- Research cleanup and current archive index: `research/README.md`.
- Removed paths, hashes and reasons: `research/CLEANUP-20261102.json`.

Previous physical milestone history is archived at
`research/journal/HANDOFF-full-20261102.md`; read it only for a named historical
attempt, never as current authorization.
