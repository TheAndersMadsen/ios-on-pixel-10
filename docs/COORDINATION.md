# Coordination and evidence policy

This file defines ownership, safety, queue authority and evidence rules only. [NOTES.md](../NOTES.md)
is current state; [HANDOFF.md](../HANDOFF.md) is immediate work. Old queues and attempt handoffs are not authorization.

## Ownership and handoffs

- The coordination thread owns priorities, this policy and the shared root Git
  index. The phone owner alone admits and runs physical device tests.
- Keep one accountable owner for each source or artifact scope. Do not create a
  parallel builder, boot runner, driver owner or storage owner for the same work.
- Source work, tests, captures and private nested Git continue within owned
  scopes. Deliver changed evidence to the existing owner at its next boundary.
- Other owners submit exact paths, tested hashes, validation receipts, a commit
  message and their own NOTES section or patch. Do not consume another owner's
  staged changes or pending review.

## Device and data safety

- Development boots use temporary `fastboot boot` images. Preserve Android,
  stock slots, bootloaders, firmware and all partition backups.
- **No iOS root is deployed.** Old aliases, root images, capacity assumptions,
  write approvals and dual-boot instructions are historical.
- A new deployment requires a fresh storage/recovery plan, a qualified backup
  and recovery path, fresh phone-owner review, and explicit user approval of the
  exact action. Never reuse an old approval or silently substitute an artifact.
- Destructive steps, partition writes, factory scripts, slot changes and firmware changes
  require separate concrete confirmation. Host or QEMU success grants no device permission.
- Use one attended physical reservation at a time. Preserve the complete capture
  and rollback evidence before reset or admission of another candidate.
- Keep device dumps, serial numbers, keys, firmware and downloaded Apple
  artifacts out of Git.

## Current queue authority

- The phone owner is the sole physical-queue authority. A candidate enters only
  after fresh binding review and explicit admission; HANDOFF priorities are not
  a standing boot queue. No unchanged retry or automatic core/image/nonce change.
- `/tmp/fleet/qemu-guest-slot.lock` is the shared QEMU admission authority. An
  admitted guest runs its planned bound without routine polling or interruption.
- QEMU release requires terminal capture, input checks, cleanup of its processes/backing
  files and normal lock-FD close. Notify the next owner; a relay authorizes no run or retry.

## Shared root Git safety

- Only coordination stages and commits in the shared root repository. Others use
  `git --no-optional-locks` for read-only checks.
- No other owner may run root `add`, `apply --cached`, `commit`, `reset`, remove
  locks, clean staged content or rewrite history. Coordination verifies current
  bytes, released scope and resulting commit scope before returning the commit.

## Build and physical evidence

- Explicitly enable tested feature gates. Emit ARM64 objects and inspect expected
  implementation symbols; guarded empty units and syntax-only checks are not
  implementation evidence. Local cross-compiles can precede a full kernel build.
- Before an expensive run, bind source/patches, kernel/image/overlay, embedded
  payload/ADT/nonce/placement, exact argv, gates, CPU context, workload and
  rollback. Preserve positive and negative receipts with the attempt.
- Label source, host test, enabled ARM64 object/image, QEMU and physical evidence
  separately. Distinguish observation from inference and upstream claims.
- Capture live overlap, loss/wrap and final tail accurately. Presentation counts are not FPS;
  software rendering is not native Metal; source and firmware SEND/START are not healthy execution.
- Accept each feature through positive execution evidence at its own scope. Do
  not transfer GPU, storage, app, connectivity or CPU acceptance across runs.
