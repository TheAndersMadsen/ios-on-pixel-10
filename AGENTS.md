# Working on hackios

- Read `NOTES.md` before starting; it contains the project goal, hardware facts,
  current blocker, local artifact locations and the next concrete action.
- The user switches agents frequently. Update the active handoff in `NOTES.md`
  after each milestone and before stopping. Record commits, attempt IDs, exact
  build/boot results and unfinished work. Distinguish observations from guesses.
- Commit completed changes. Local single-file cross-compiles are useful before
  spending a full kernel build or a boot.
- For local blazer XNU checks, explicitly enable the feature gates being tested.
  Guarded files can compile as empty translation units. Emit ARM64 objects and
  inspect their expected symbols before claiming the implementation compiles;
  syntax-only success is insufficient.
- Device bring-up uses temporary `fastboot boot` images. Preserve the Android
  installation and partition backups. Keep bootloaders, slots, firmware and the
  backups intact, and confirm each destructive step with the user before running it.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.
