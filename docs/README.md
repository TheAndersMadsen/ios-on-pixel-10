# Documentation

## Here

| Document | What |
| --- | --- |
| [BUILD.md](BUILD.md) | Build a phone image and boot it; every local input and its pin |
| [COORDINATION.md](COORDINATION.md) | Active owners, priorities, test batching, readiness and the phone queue |
| [CONNECTIVITY.md](CONNECTIVITY.md) | Native Wi-Fi, Bluetooth and cellular evidence, dependencies, reusable sources and acceptance |
| [REUSE.md](REUSE.md) | Ranked reusable sources, exact pins, licences and adaptation boundaries |
| [DUALBOOT.md](DUALBOOT.md) | Android/iOS storage isolation, chooser acceptance and read-only bring-up |
| [IOS-APPS-IDENTITY.md](IOS-APPS-IDENTITY.md) | Missing stock apps, LaunchServices restoration, GitHub SEP and Apple-service implementations |
| [LICENSING.md](LICENSING.md) | What each path is, what must be audited before a public release |
| [status.json](status.json) | Source of the README's progress, figures and roadmap. Rebuild with `python3 -I tools/readme_status.py` |
| `assets/` | README images, generated. Don't edit by hand |

## Elsewhere in the repository

| Document | What |
| --- | --- |
| [README](../README.md) | Overview, progress, quick start |
| [NOTES.md](../NOTES.md) | Short current truth, blockers, canonical artifacts and task routes |
| [HANDOFF.md](../HANDOFF.md) | Immediate next actions only; older physical journals are in ignored research |
| [BLAZER.md](../BLAZER.md) | Pointer to current notes and the archived hardware history |
| [AGENTS.md](../AGENTS.md) | Rules for working on this repository |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | How boots are run, safety rules, what never gets committed |
| [SECURITY.md](../SECURITY.md) | The security position and how to report a problem |
| [CHANGELOG.md](../CHANGELOG.md) | Changes and results by date |
| [xnu/README.md](../xnu/README.md) | Notes on the iOS 16 kernel build, the parts source |

## Not in git

`research/` holds attempt captures, agent handoffs, kernel series, sources and
canonical artifacts on the owner's machine. Start with `research/README.md` for
the current index, historical classifications and retention policy; the old
`research/ios26-fleet/` board and plan are not live state. The 2026-11-02 cleanup
manifest records removed intermediate/duplicate artifacts and their hashes, so
some old reproduction paths now require deliberate rebinding to canonical inputs.
