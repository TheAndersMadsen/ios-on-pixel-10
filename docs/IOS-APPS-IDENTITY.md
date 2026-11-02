# Stock apps, device identity and Apple services

2026-11-02. Active goal: all stock apps running on the native Pixel iOS 26
port, with device identity and Apple services. This milestone establishes the
missing app content and concrete upstream implementations. It does not
establish phone app launches, Apple account login or SEP-backed security.

## What is actually missing

Read-only inventories of the stock 23G90 OS volume and constructed r3 root
confirm that both contain **206 top-level `/Applications` bundles**, mostly
services. The stock OS also contains **49 staged app bundles**. All 49 are
absent from r3, including Safari, Clock, Calculator, Notes, Contacts and Files.
The first-boot recipe's `auto()` explicitly skips app registration, even if its
feature flag is enabled. A Settings-only home screen therefore has two
concrete prerequisites: app content restoration and LaunchServices registration.
Registration and SpringBoard visibility still require runtime observation.

The missing staged files total **1,166,707,757 bytes**. The existing 8 GiB
root has **553,840,640 bytes available**. That is insufficient before block
rounding, filesystem metadata and the framework resources also pruned from r3.
Do not shrink the restored apps by dropping their resources or overwrite
Android storage to make the image fit. Coordinate the eventual image size
with the isolated-storage work in [DUALBOOT.md](DUALBOOT.md).

`tools/ios_app_inventory.py` reads two mounted roots and writes a local JSON
inventory and optional registration manifest. It checks bundle identifiers,
executables, partial resource trees and capacity. It reports malformed internal
bundles separately. The current stock source has two `.app` directories without
Info.plist (DisplayCal and RepairCal); they are not silently counted as usable
apps. A filesystem result never counts as a launch test.

## How other projects implement the security and service pieces

### OpenSEP: an actual firmware boot path, requiring a SEP execution environment

Verified [OpenSEP ead61b7](https://github.com/owngoal-dev/OpenSEP/tree/ead61b7b31013bb983348be69bf6a91f69d03b56)
and its MIT licence. Its
[README](https://github.com/owngoal-dev/OpenSEP/blob/ead61b7b31013bb983348be69bf6a91f69d03b56/README.md)
reports iOS 26/27 boots on vphone and an activation screen on a QEMU iPhone
model. This is a real SEP boot-ROM replacement that hands over to SEP firmware.
It is useful evidence that SEP emulation is possible.

Its [external contract](https://github.com/owngoal-dev/OpenSEP/blob/ead61b7b31013bb983348be69bf6a91f69d03b56/docs/external-contract.md)
requires a separate AArch64 core execution context, prescribed memory, mailbox
events, device blocks and a firmware handoff. It is not an XNU keybag driver or
a port for Tensor's Trusty hardware. A Pixel adoption would first need an
isolated SEP emulation backend and an AP-side transport; none is implemented
here. Booting firmware would still not establish Apple manufacturing identity.

### vphone: virtual SEP storage and research activation

Verified [vphone fd1610d7](https://github.com/Lakr233/vphone-cli/tree/fd1610d7928aacd6cbc060722bb27fd7d2c76315),
MIT. Its [machine-identity experiments](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/Research/Host/machine_identity_and_clone.md)
show that SEPStorage, NVRAM and the guest disk must be retained together;
regenerating SEPStorage independently panics the guest. This is an important
persistence contract for a future emulator backend, not a transplantable device
credential.

Its [activation patch](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/VPhoneExecutable/VPhoneCommand/FirmwarePatcher/CustomFirmware/ExecutablePatches/MobileActivation/CustomFirmwareMobileActivation.swift)
selects research self-activation. Its
[UDID hook](https://github.com/Lakr233/vphone-cli/blob/fd1610d7928aacd6cbc060722bb27fd7d2c76315/VPhoneGuestComponents/MISFix/MISFixDeviceIdentity.c)
affects provisioning/profile checks, with documented limits. Neither proves
Apple server recognition. On October 8 the maintainer explicitly said
[iCloud is not supported](https://github.com/Lakr233/vphone-cli/issues/629).

### OpenBubbles/rustpush: working service clients with Mac-backed validation

Verified [OpenBubbles eed1b633](https://github.com/OpenBubbles/openbubbles-app/tree/eed1b6332efbb17adbf5ebfa2263ad770169f75e),
whose Apache-2.0 [README](https://github.com/OpenBubbles/openbubbles-app/blob/eed1b6332efbb17adbf5ebfa2263ad770169f75e/README.md)
documents iMessage, FaceTime, Find My and shared albums, requiring access to a
Mac and an Apple account. This is a concrete route to some Apple services on
non-Apple clients.

The [hardware setup](https://github.com/OpenBubbles/openbubbles-app/blob/eed1b6332efbb17adbf5ebfa2263ad770169f75e/lib/app/layouts/setup/pages/rustpush/hw_inp.dart)
actually fetches validation data through a Mac bridge. The reviewed
[rustpush macOS implementation](https://github.com/OpenBubbles/rustpush/blob/b3c96c23e1aae78d1229ebaccb12027624f1eaff/src/macos.rs)
constructs a Mac-specific activation description and performs the validation
session with `open_absinthe::nac::ValidationCtx`. It does not attach a SEP to the
Android client. Its service implementations may inform a separate client, but
are not a drop-in backend for stock iOS Messages, AuthKit, securityd or iCloud
Settings. rustpush has a separate licence and an OpenBubbles-specific exception;
the app's Apache licence does not cover the library automatically. No source,
hardware credentials or account data were imported into this port.

### Anisette and pypush: separate, narrower prerequisites

[Dadoum's Anisette server](https://github.com/Dadoum/anisette-v3-server/tree/684895737aaf1a1c4586fcd5b67509ffd500a36c)
provides authentication metadata used by sideloading clients. Its
[October 2026 issue](https://github.com/Dadoum/anisette-v3-server/issues/61)
documents changed server checks and platform consistency failures. A successful
Anisette request does not establish complete iCloud, IDS or activation support.

[pypush 71aa2e44](https://github.com/JJTech0130/pypush/tree/71aa2e4442061596f75e6b02dfad613330127b5b)
currently documents APNs client support during a rewrite, with iMessage features
temporarily removed. Its SSPL licence and the distinction between an APNs
certificate and full iPhone activation rule out treating it as a ready identity
package. No activation requests were sent in this investigation.

Inferno also has a real SEP emulation reference; its current guide explicitly
lists iServices and passcode/biometrics as unavailable. Its active source moved
away from GitHub. See [INFERNO.md](INFERNO.md) for current pins and limitations.

## Implementation and next acceptance

`tools/ios_app_register.m` is an independent registrar using URL registration,
informed by vphone's public LaunchServices API usage. It reads the source-derived
manifest and verifies each identifier at its actual installed path using fresh
enumeration. Placeholders, wrong paths and missing executables fail. It never
overrides signer identities, alters a UDID or treats API acceptance as a launch.
It is default-off at compilation (`HK_STOCK_APPS_BUILD=1` enables it).
Phase receipts precede framework loading, workspace connection, enumeration and
URL registration, so an unfinished synchronous API call remains identifiable.
Attempt counts limit retries; they do not cancel or time out Apple's APIs.

The private `research/ios26-apps-r1/` candidate uses an APFS clone of the existing
20 GiB light root. All 49 app bundles are relocated into `/Applications`; all
staged regular files are present. The original r3 and light images remain
unchanged. A first-boot job calls the registrar with the explicit 51-app manifest
(49 staged plus Settings and Phone). The candidate is larger than the phone's
current root allocation and is for guest tests only. Package verification and
guest results must be recorded in that directory's handoff, never inferred from
this document. Legacy resource envelopes need validation after relocation.

Guest integration must retain the **current r3** `/var` seed and preferences,
including `persona.kb` and `CAEnableMedina=false`, plus its launchd baseline.
The old light root predates those requirements. Its first full-RAMDisk guest
demonstrated a missing-persona startup abort, not lost persona support on the
physical r3. The corrected candidate copies all 55 r3 seed files byte-for-byte,
preserves its 676 launchd jobs, and adds only the own registrar job. Its 245 seed
entries are parsed and source paths checked with the actual p29 consumer.

Use the whole-RAMDisk backend for this 20 GiB guest. The fake UFS test path
deliberately retains the physical 8 GiB view; a real seed file at offset
17,532,928,000 was refused with EINVAL. An actual-reader host reproduction
confirmed that bound. Neither seed deletion nor a widened physical partition
view is an appropriate correction. All 49 restored bundles have since passed
deep resource/signature verification in the private clones.

Next acceptance is sequential: valid code/resource signatures and PAC rewriting
on the candidate, fresh guest LaunchServices read-back, then an actual launch
and representative interaction for each app. Required framework data, extension
registration, MCM and AKS failures must be repaired at their actual seams. The
phone owner alone schedules a physically suitable candidate after its existing
sampler work. No new storage or root write is authorized by this document.

The local `SweetKeyStore` currently supplies fixed unlocked-state compatibility,
not a SEP backend. Before account work: verify network, real time, actual
securityd/keychain results, supported AKS operations and each required service.
Mac-backed service clients offer a possible additional route, while stock-iOS
integration and legitimate Apple attestation remain unproved. Apple's
[SEP description](https://support.apple.com/en-gb/guide/security/sec59b0b31ff/web)
and [attestation requirements](https://support.apple.com/guide/security/managed-device-attestation-sec8a37b4cb2/web)
explain the hardware-bound identity boundary. A compatibility model string,
skipped setup screen or profile is not acceptance for those requirements.
