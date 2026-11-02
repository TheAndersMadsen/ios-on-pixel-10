# Stock apps, identity and Apple services

Scope: run stock iOS 26 apps and legitimate Apple services on a self-contained Pixel, without fake SEP/identity results or a Mac runtime bridge.

## Current result

- **Host:** the 20 GiB guest image restores all 49 missing staged apps and passes deep signature checks. `apps-full-r6.img` is current; `apps-full-r5.img` is the rollback image.
- **QEMU:** r8, h1-r9 and h2-r10b each ended normally after 1200 s with the root unchanged. `registerApplication:` returned NO for every restored app it was called on. Fresh readback lists only the 6 bundles carrying `com.apple.private.security.no-container` (Preferences, AegirProxyApp, Camera and three posters); none of 20+ container-requiring apps appear.
- **Rejected (QEMU):** H1, the same-identifier App Placeholders: removing them changed nothing ([r9](../research/ios26-apps-r1/receipts/placeholder-h1-r9/result.json)). H2, MobileContainerManager provisioning: real MCM returned containers for 28/28 apps without error, and registration still failed ([r10b](../research/ios26-apps-r1/receipts/container-h2-r10/result-r10b.json)). r10 was inconclusive: the registrar was built without `pacstrip.py` and hit SIGILL on `braa`.
- **QEMU (r11c/r11d, 2026-11-02):** with `atm_diagnostic_config=0x400` (XNU ATM_TRACE_OFF, which disabled os_log in every earlier run) removed, registration is unchanged (6 listed). The registrar loop does not finish in 1200 s. Reading lsd's log in-guest through `OSLogStore localStoreAndReturnError:` fails: the SPI is missing on this build ([receipts](../research/ios26-apps-r1/receipts/lslog-r11/)).
- **QEMU:** r8 has no selected-app registration acceptance and no representative app exec, foreground UI or interaction acceptance.
- **Physical:** no apps image is deployed and no stock-app registration or launch is accepted on the phone.
- `SweetKeyStore` is fixed-state compatibility, not a SEP backend. Apple login, activation, attestation and native Apple services remain unaccepted; Mac tools are development-only.

## Remaining work

1. Obtain lsd's own refusal reason before any further registration variant: next try `OSLogStore storeWithScope:` (system) or host-side parsing of the guest's `/var/db/diagnostics` after a run with ATM tracing on (no `atm_diagnostic_config=0x400`). Placeholder and container hypotheses are rejected. Every registrar artifact must go through `pacstrip.py`.
2. After readback, prove selected app exec, foreground rendering and interaction; expand to every restored stock app and repair actual framework, container or service failures.
3. Establish networking, real time, securityd/keychain and supported AKS behavior before designing an on-device SEP/identity path; never substitute fabricated credentials or skipped checks.
4. Consider physical deployment only after guest acceptance and a fresh approved storage/recovery plan.

## Acceptance before expanding scope

- All intended apps register at their real paths and remain visible through fresh LaunchServices enumeration.
- Representative apps execute, reach the foreground and survive interaction; ultimately each restored stock app passes this sequence.
- Physical app results are captured separately from QEMU and bound to an approved, deployable image.
- Identity and each Apple service work entirely on the Pixel with genuine security semantics; a model string, profile or compatibility keystore is not acceptance.

## Evidence and source

- [Current r6 image](../research/ios26-apps-r1/artifacts/apps-full-r6.img)
- [Rollback r5 image](../research/ios26-apps-r1/artifacts/apps-full-r5.img)
- [r8 console: registration/readback results](../research/ios26-apps-r1/runs/registration-r8/console.log)
- [r8 terminal status](../research/ios26-apps-r1/runs/registration-r8/exit.json)
- [r8 frozen-input receipt](../research/ios26-apps-r1/receipts/freeze-r8.json)
- [Registrar source](../tools/ios_app_register.m)
