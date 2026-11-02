# Bluetooth keychain status diagnostic

Original MIT observer for a concrete native `bluetoothd` startup hypothesis.
It changes no Security API arguments, returned status, result object or `errno`.
It never starts a Security operation itself and logs no queries, keys, device
addresses, account names or returned data. Real API calls remain with the daemon.

Both gates are required: compile `HKBTKC_ENABLED=1`, then load into exactly
`bluetoothd` with `HK_BT_KEYCHAIN_TRACE=1`. Default behavior emits nothing and
does not open a console. The v2 constructor searches loaded ARM64 Mach-O images
for a unique executable and verifies its UUID and file-backed TEXT/slide relation.
It reports explicit known/unknown identity and the UUID; an inserted dylib at
image index zero is never assumed to be the executable. Four interposers observe
CopyMatching/Add/Update/Delete.
At most 64 call records per process contain operation, caller and return status,
with matching PID/ID entry/return pairs. A missing return is incomplete evidence,
including a possibly blocked API. Raw caller addresses may need PAC handling.

Logs go to a nonblocking `/dev/console`, falling back to stderr if open fails.
Partial/error writes have bounded retries and loss accounting; logs can still
interleave. Neither a missing line nor an unobserved call proves absence.
The observer adds temporary diagnostic overhead; no speed claim is made.

Build and validate without editing a root, starting a guest or using a device:

```sh
python3 -I runtime/bt_keychain_trace/check.py \
  --output research/ios26-connectivity-r1/keychain-check-NEW
```

This executes the actual wrappers against host mocks with ASan/UBSan and TSan.
It checks default/exact-process opt-in, original calls/results/output pointers,
`errno` preservation, write failures and 32 concurrent callers exhausting the
64-record budget. Loaded-image fixtures check both image orders, malformed load
commands/extents, missing/duplicate UUIDs, executable ambiguity, image churn,
slide overflow and explicit unknown logging. Five mutations must fail, including
the image-zero regression and ignored command extent. These mocks do not execute
iOS Security or prove interposition.

The native check emits ARM64e objects for enabled/disabled gates, checks all
four real text definitions and original Security references, links the iOS26
dylib, applies the existing private PAC rewriter and verifies the final signature
and executable instructions. The gate-off object has no executable body.
SDK27.1/iOS26 deployment compatibility of v2 remains a real-loader acceptance step.

The sole frozen v1 guest completed 420.009 seconds with unchanged inputs/root.
Its final receipt is `research/ios26-connectivity-r1/keychain-guest-r3/result.json`:
26 constructor records and 150 matched PID/ID API pairs. CopyMatching/update
returned -25300; add returned -25291. Delete was not observed. All recorded loss
counters were zero; 808,417 streamed bytes match the final mirror, with a separate
3,130-byte final tail and no capture loss. This is positive native interposition
and status evidence, with the guest's synthetic nub only.

V1 incorrectly labelled dyld image zero as the main executable under injection.
Its header/slide identity claim is rejected; no guessed replacement slide is
accepted. V2 fixes that observed diagnostic defect and passes host sanitizers,
the five mutations, gated ARM64e objects and signature/PAC checks. It has not
run in a guest or on the phone, and the frozen v1 package remains unchanged.
An additional private check runs the actual v2 parser over retained bluetoothd
load commands and UUID `da7adf0004fa3ee08782e336e0982712`, and rejects the real
observer dylib as an executable. This validates header parsing, not guest loading.

The linker moves the interposition pairs to `__AUTH_CONST,__interpose`, with a
regular section type. This is accepted by the explicit predicate in Apple's
[dyld1376.6 section walker](https://github.com/apple-oss-distributions/dyld/blob/dyld-1376.6/mach_o/UnsafeHeader.cpp).
Its [interposition implementation](https://github.com/apple-oss-distributions/dyld/blob/dyld-1376.6/dyld/DyldRuntimeState.cpp)
also preserves the interposer's call through to the original implementation.
The existing local source bytes were independently fetched from that tag and
matched. This source reference does not prove this guest permits interposing.
No Apple implementation is copied into this package.

Prepare one concrete QEMU candidate, without running it:

```sh
python3 -I runtime/bt_keychain_trace/prepare.py \
  --dylib-receipt research/ios26-connectivity-r1/keychain-check-NEW/receipt.json \
  --output research/ios26-connectivity-r1/keychain-guest-NEW
```

The preparer pins the working p29 kernel, unchanged r3 root and known hgltrack
overlay. It extends the sole selected environment rule, preserves unrelated
records and hgltrack, and adds the signed observer in volatile `/private/var`.
Only the existing Bluetooth deny bit is unselected so the stock daemon runs.
Actual XNU overlay and exec-rule consumers validate the final bytes under
ASan/UBSan. An isolated frozen guest harness adds the already used synthetic
Bluetooth discovery nub. That address is a guest fixture, never phone identity.

`plan.json` contains exact input/tool hashes and argv. The proposed guest lasts
420 seconds and uses immediate shared-lock admission (`--wait 0`). Run only
after the shared guest owner's release event. No retry, hardware model, fake HCI,
radio token, BlueTool substitute or old exit-trace kernel is enabled. The root
is mapped read-only/copy-on-write. No phone image is prepared by this package.

First acceptance: a real verified executable-header/UUID receipt, matching PID/ID API entry and
return, exact actual statuses, retained capture and unchanged root. Confirm the
relevant call path before changing any keychain prerequisite. A constructor
alone does not prove API interposition. Native Bluetooth still needs the real
chip, daemon attachment, Settings, pairing/profiles and stable reconnect.

Original sources/tests/build helpers are scoped by LICENSE. Generated dylibs,
overlays, XNU headers, PAC tools, harness snapshots and Apple references remain
outside that licence in ignored research directories.
