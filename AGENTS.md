# Working on hackios

- Read `NOTES.md` before starting; it contains the project goal, hardware facts,
  current blocker, local artifact locations and the next concrete action.
- The user switches agents frequently. Update the active handoff in `NOTES.md`
  after each milestone and before stopping. Record commits, attempt IDs, exact
  build/boot results and unfinished work. Distinguish observations from guesses.
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
