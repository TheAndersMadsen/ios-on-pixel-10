# Stock apps, identity and Apple services

Scope: run stock iOS 26 apps and legitimate Apple services on a self-contained Pixel, without fake SEP/identity results or a Mac runtime bridge.

## Current result

- **Host:** the 20 GiB guest image restores all 49 missing staged apps and passes deep signature checks. `apps-full-r6.img` is current; `apps-full-r5.img` is the rollback image.
- **QEMU:** r8 ended normally after its 1200-second capture with the root unchanged. Calculator, Clock and Notes URL registration returned false and fresh readback did not list them.
- **QEMU:** r8 has no selected-app registration acceptance and no representative app exec, foreground UI or interaction acceptance.
- **Physical:** no apps image is deployed and no stock-app registration or launch is accepted on the phone.
- `SweetKeyStore` is fixed-state compatibility, not a SEP backend. Apple login, activation, attestation and native Apple services remain unaccepted; Mac tools are development-only.

## Remaining work

1. Diagnose the observed LaunchServices registration refusal at its real service boundary, then obtain accepted registration and fresh installed-path readback in QEMU.
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
