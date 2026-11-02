# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

1. **Owner:** return the phone per `research/ios26-dualboot-r8/NEEDS-OWNER.md` section 0
   (force-fastboot off, reboot, recovery "Try again", never factory reset), then the return check.
2. With the owner present: boot chooser-v1-r3 (stock vbmeta transplanted) once; the
   discriminator is vold mounting /data and `Kernel code` at 0xc9c00000 in `/proc/iomem`.
3. Host: an EL2 cached identity map for the chooser's lz4 decode (122 s now), then the visible
   startup menu (renderer plus scanout path) and the volume-key pad read; then the in-kernel
   `ios_*` write allowlist for A7. GOAL.md still governs runs.

## Latest completed maintenance

- Android restoration and its documented exceptions:
  `research/factory-alias-restore-r1/HANDOFF.md`.
- Research cleanup and current archive index: `research/README.md`.
- Removed paths, hashes and reasons: `research/CLEANUP-20261102.json`.

Previous physical milestone history is archived at
`research/journal/HANDOFF-full-20261102.md`; read it only for a named historical
attempt, never as current authorization.
