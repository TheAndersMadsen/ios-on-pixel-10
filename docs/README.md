# Documentation

## Here

| Document | What |
| --- | --- |
| [BUILD.md](BUILD.md) | Build a phone image and boot it; every local input and its pin |
| [COORDINATION.md](COORDINATION.md) | Active owners, priorities, test batching, readiness and the phone queue |
| [CONNECTIVITY.md](CONNECTIVITY.md) | Native Wi-Fi, Bluetooth and cellular evidence, dependencies, reusable sources and acceptance |
| [REUSE.md](REUSE.md) | 24-agent source audit: reusable code, exact pins, compatibility limits and next integration tasks |
| [DUALBOOT.md](DUALBOOT.md) | Android/iOS storage isolation, chooser acceptance and read-only bring-up |
| [IOS-APPS-IDENTITY.md](IOS-APPS-IDENTITY.md) | Missing stock apps, LaunchServices restoration, GitHub SEP and Apple-service implementations |
| [LICENSING.md](LICENSING.md) | What each path is, what must be audited before a public release |
| [status.json](status.json) | Source of the README's progress, figures and roadmap. Rebuild with `python3 -I tools/readme_status.py` |
| `assets/` | README images, generated. Don't edit by hand |

## Elsewhere in the repository

| Document | What |
| --- | --- |
| [README](../README.md) | Overview, progress, quick start |
| [NOTES.md](../NOTES.md) | Goal, hardware facts, artifact locations, active handoff |
| [HANDOFF.md](../HANDOFF.md) | Latest state and next step, newest first |
| [BLAZER.md](../BLAZER.md) | Pixel 10 Pro bring-up status and evidence history |
| [AGENTS.md](../AGENTS.md) | Rules for working on this repository |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | How boots are run, safety rules, what never gets committed |
| [SECURITY.md](../SECURITY.md) | The security position and how to report a problem |
| [CHANGELOG.md](../CHANGELOG.md) | Changes and results by date |
| [xnu/README.md](../xnu/README.md) | Notes on the iOS 16 kernel build, the parts source |

## Not in git

`research/` holds the evidence and the current state: attempt captures, agents' handoffs, the iOS 26 kernel series and sources. So some links in `NOTES.md` and `HANDOFF.md` are dead on a clean clone. `research/ios26-fleet/STATUS.md` and `research/ios26-fleet/HARDWARE.md` are the fuller records on the owner's machine.
