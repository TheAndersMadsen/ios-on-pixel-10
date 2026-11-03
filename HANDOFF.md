# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. Done: phone back in Android, return check PASS (2026-11-03). pKVM prints "hVHE" on this kernel.
2. A3 accepted (r3 x3, r4 in 42 s). Menu visible on the panel (r7), but the display handback to Linux
   fails (r7 panic, r9 CPM hang on FE0 off). Next run, host first: take the vs_dc suspend order
   (BE idle, `dc_hw_do_reset`, clock-domain isolation on; vs_dc.c:201-230) with register values from the
   stock vs_dc module disassembly, never guessed, then r10 with the owner present. Bare `fastboot boot`, ANDROID_SERIAL set.
3. Host: r4 (cached decode) and r6 (menu renderer) are built and QEMU-tested; next are the visible
   menu (r6 plus the `tgl_dcs_run` full-screen layer, `research/ios26-dualboot-r8/menu-ui/SCANOUT-PATH.md`),
   the volume-key pad read, and a kernel link plus QEMU negative test of XNU dd000c8 (ios_data persist).
   A7 boot blocker (source): XNU `n892_xnu_selected_view` (n913_n892_bridge.inc) requires an exactly
   2,097,152-block root named userdata_exp.ai; rebind to ios_system at its GPT size, link, QEMU with the real size.
   Flash/readback side is ready: `tools/ios_partition_flash.py`, `research/ios26-dualboot-r8/A7-READY.md`.
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
