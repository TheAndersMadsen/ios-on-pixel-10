# Working on hackios

- Read `NOTES.md` for current truth, then `HANDOFF.md` and only the one task
  document named there. Do not recursively read `research/` or old journals;
  retrieve a named receipt or bounded log excerpt when verification is needed.
- Keep `NOTES.md` short: replace affected current statements after each milestone
  instead of appending session history. Put exact commits, attempt IDs, hashes and
  build/boot receipts in the named research directory and link them. Distinguish
  source/host/QEMU/physical evidence and observations from guesses.
- Commit completed changes. Local single-file cross-compiles are useful before
  spending a full kernel build or a boot.
- The coordination thread is the sole writer of the shared root Git index and
  commits. Other owners submit exact paths, tested hashes, a commit message and
  their own NOTES section; continue source work and private nested Git normally.
  Use `git --no-optional-locks` for root read-only checks. Do not stage, commit,
  reset, remove locks or consume another owner's staged changes. See
  `docs/COORDINATION.md` for the handoff and current commit holds.
- For local blazer XNU checks, explicitly enable the feature gates being tested.
  Guarded files can compile as empty translation units. Emit ARM64 objects and
  inspect their expected symbols before claiming the implementation compiles;
  syntax-only success is insufficient.
- Device bring-up uses temporary `fastboot boot` images. Preserve the Android
  installation and partition backups. Keep bootloaders, slots, firmware and the
  backups intact, and confirm each destructive step with the user before running it.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.
