## What and why

<!-- One or two sentences. -->

## Evidence

<!-- Attempt names for anything claimed on the phone. Say what was observed and what was inferred. Short tests are called short tests. -->

## Tested

- [ ] `.github/scripts/ci-tests.sh` passes
- [ ] If this changes hardware state: `docs/status.json` updated and `python3 -I tools/readme_status.py` rerun
- [ ] If this adds blazer XNU or shim code: built as ARM64 objects with the feature gate on, symbols inspected. Syntax-only success doesn't count
- [ ] `NOTES.md` handoff updated, and `CHANGELOG.md` for a milestone

## Safety

- [ ] No dumps, images, firmware, Apple files, serials or IMEIs. `.github/scripts/check_tracked.py` passes
- [ ] No new copied third-party code, or `docs/LICENSING.md` is updated with its origin and licence
- [ ] Nothing here flashes, erases or changes slots, bootloaders, firmware or backups
- [ ] Any new write to the phone's storage is named here, and needs the owner's confirmation before it runs
