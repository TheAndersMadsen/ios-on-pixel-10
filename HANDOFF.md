# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. Done: phone back in Android, return check PASS (2026-11-03). pKVM prints "hVHE" on this kernel.
2. A3 accepted for r3 (3 chains, `research/ios26-dualboot-r8/attempts/A3-RESULT.md`). Next, owner present,
   one each: r4 (cached decode), r7 (visible menu), r8 (volume keys); boot with bare `fastboot boot`
   (the runner's AVB gate refuses the transplanted vbmeta).
3. Host: r4 (cached decode) and r6 (menu renderer) are built and QEMU-tested; next are the visible
   menu (r6 plus the `tgl_dcs_run` full-screen layer, `research/ios26-dualboot-r8/menu-ui/SCANOUT-PATH.md`),
   the volume-key pad read, and a kernel link plus QEMU negative test of XNU dd000c8 (ios_data persist).
   Apps lane (QEMU): registration is blocked behind a missing user session/persona
   (`research/ios26-apps-r1/receipts/lslog-r11/result-r11h.json`); next is a genuine user-session bootstrap.

## Latest completed maintenance

- Android restoration and its documented exceptions:
  `research/factory-alias-restore-r1/HANDOFF.md`.
- Research cleanup and current archive index: `research/README.md`.
- Removed paths, hashes and reasons: `research/CLEANUP-20261102.json`.

Previous physical milestone history is archived at
`research/journal/HANDOFF-full-20261102.md`; read it only for a named historical
attempt, never as current authorization.
