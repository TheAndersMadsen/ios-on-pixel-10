# Current handoff

Read `NOTES.md` for current state. This file is only the short next-action brief;
it is not a second project journal.

## Next actions

0. Unattended dual-boot runs follow `GOAL.md` (section 0 holds the `/goal` prompt;
   receipts go to `research/ios26-dualboot-r8/`). It supersedes the storage and
   chooser prose below and in `docs/DUALBOOT.md`.
1. Continue host-only p32 compositor, Volcanic GPU and saved-GPT diagnosis.
2. In QEMU, require LaunchServices record/readback before app exec or foreground
   acceptance. Keep physical and QEMU results separate.
3. Storage is blocked at owner decisions (`research/ios26-dualboot-r7/STORAGE-DECISION.json`):
   approve a readback bind that exposes no Android partition before one complete
   read-only GPT capture; decide the media-padding policy; and qualify a backup
   destination before any attended Android `/data` shrink. No unallocated region exists.
4. Run new phone candidates only through the phone owner after fresh review and
   explicit approval. Do not reuse old aliases, images, approvals or boot queues.

## Latest completed maintenance

- Android restoration and its documented exceptions:
  `research/factory-alias-restore-r1/HANDOFF.md`.
- Research cleanup and current archive index: `research/README.md`.
- Removed paths, hashes and reasons: `research/CLEANUP-20261102.json`.

Previous physical milestone history is archived at
`research/journal/HANDOFF-full-20261102.md`; read it only for a named historical
attempt, never as current authorization.
