# Using Inferno for the Pixel port

Source assessment, 2026-11-02. Inferno offers useful iOS software-rendering
references and a possible independent Apple-device test guest. The closest
immediate match is its filesystem patcher's handling of QuartzCore surfaces.
The initial assessment added no runtime result. The exact-build follow-up below
records a bounded QEMU CoreImage experiment.

## Exact CoreImage follow-up, 2026-11-02

Audited the actual host r3 root, iOS 26.6.2 / 23G90, SHA256
`205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7`.
Its CoreImage image UUID is `6f5abd16-0e3c-3fc3-bcc7-ccefeafbca00`, matching the
stock SystemOS cache. All twelve functions targeted by Inferno's CoreImage
fallbacks match stock after our existing PAC transformations; none of the
requested return stubs was present. This is a binary comparison, not inference
from root recipes. Exact function addresses, spans and hashes are retained in
`research/ios26-inferno-coreimage-r1/audit/exact-r2.json`.

Selected only `_isWidget` at `0x19e041778`. In this build,
`-[CIContext initWithOptions:]` uses its result to select
`internalSWContextWithOptions:` directly. An independent branch selects that
same path for `software_renderer.intValue == 2`; the exported
`kCIContextUseSoftwareRenderer` points to that key. The probe uses value 2 as
a positive control, rather than assuming the usual Boolean option reaches it.

The experimental clone replaces this function's first eight bytes with
`mov w0, #1; ret` and changes one 32-byte signed-page hash. The complete image,
with those two ranges restored for hashing, equals the source SHA256; the source
was independently rehashed unchanged. An existing independent verifier checked
all 5,318 pages of the modified cache member, with zero invalid hashes. The
other eleven audited targets remain unchanged. Candidate image SHA256:
`6ba62469f05e553c21c965e092b356e7f2509406064d24299a0b0f9193915a8f`.

The p29 QEMU comparison uses the unchanged existing harness and identical
SpringBoard diagnostic library/overlay. In the final control probe, default,
GPU-request and Boolean software-request context creation returned nil. The
numeric-2 reference created a software context and correctly rendered every
pixel of a 4x4 red image and its cyan color inversion, including guard checks.
In the changed guest, all four cases created software contexts and passed those
same pixel/guard checks. Temporary constructor observers were restored.
Final runs: `control-r3` (235.242 host seconds) and `widget-r3` (244.994 host
seconds), both exited 0 with unchanged input images and no recorded console
loss. These durations are test windows, not a performance comparison.
`receipts/result.json` records the passing strict verifier; eight altered
failure receipts were rejected by its log checks.

Earlier runs remain in the receipts: `control-r1` rejected an observer type
check; r2 created contexts with the change but failed bitmap-backed pixel
checks. The revised constant-color input has an independent passing control.
The bitmap failure's cause is unisolated; it is not established as an IOSurface,
asset-catalog or codec defect. No missing-icon, frame-rate or phone improvement
is claimed, and the queued Settings/home script was not exercised by this
bounded comparison. The phone root and all physical gates remain untouched.

Original audit/clone/probe/strict-verifier source and reproduction details:
[tools/coreimage](../tools/coreimage/README.md). The Inferno patcher is
AGPL-3.0-or-later; no patcher implementation was imported. This follows the
reuse audit's [assets](reuse/2026-11-02/assets-compositor.md),
[Darwin services](reuse/2026-11-02/darwin-services.md) and
[CPU rendering](reuse/2026-11-02/cpu-rendering.md) ownership boundaries:
the Battery glyph, container-ready, cloudd and sampler candidates remain
separate, and the physical surface-tracking fix stays single-applied.

## Current sources

The [GitHub repository](https://github.com/ChefKissInc/Inferno) was archived on
2026-11-01 and points to the active
[ChefKiss repository](https://git.chefkiss.dev/AppleHax/Inferno).
Its older open GitHub issues are insufficient evidence of current support.
Reviewed source pins:

- Inferno: `26b36cc8d59535ed1d9963faab25ac576111edcb`.
- Website: `596403e772703cc8478a7444dec26a3203ff2a58`.

The public guide and Git web pages returned HTTP 403 to the fetch tools.
The official Git server's public API supplied the current guide and selected
source files. Ignored copies, URLs and SHA256 receipts are in
`research/ios26-inferno-r1/`. The recursive repository tree response was
truncated; relevant directories were listed separately. This was a selected
source review, not an exhaustive repository audit.

## What the current project documents

The [overview](https://chefkiss.dev/applehax/inferno/) lists an emulated iPhone
11 reaching SpringBoard, iOS 13 through 27, display, touch, SEP emulation and
HVF/KVM/WHPX support on suitable ARM hosts. These are upstream claims; we did
not build or boot Inferno. The
[running guide](https://chefkiss.dev/guides/inferno/running-restoring/) explicitly
describes incomplete Liquid Glass on iOS 26 with software rendering. The
overview also lists audio as WIP and passcode/biometrics and iServices as
unavailable.

## Concrete rendering leads

The current
[filesystem patcher](https://git.chefkiss.dev/AppleHax/Inferno/src/commit/26b36cc8d59535ed1d9963faab25ac576111edcb/fspatcher/main.cpp)
contains several relevant changes:

- `QuartzCorePatches::track_iosurface_surfaces` adds the missing
  `Context::track_surface` call to `SWContext::create_surface_from_iosurface`,
  addressing the same `push_surface` assertion we encountered. It validates
  a particular function layout before replacing its body.
- `CoreImagePatches` disables Metal/MPS and unavailable GL paths, and forces
  `_isWidget` true for its iOS 18/26 software-rendering route.
- `SpringBoardFoundationPatches` selects XPC wallpaper rendering;
  `NeutrinoCorePatches` constructs `NUSoftwareRenderer`.
- Other patches avoid Metal-dependent ClockKitUI/PosterBoard operations and
  camera shader precompilation. Some return no result rather than implementing
  a rendered replacement, so their presence does not establish visual fidelity.

Our `hgltrack` already wraps the affected SWContext method in backboardd.
Physical attempt `20261102-095609-phone-p29-live-r1` recorded surface tracking
and surviving Settings/home transitions; missing graphics and heavy lag
remained. Inferno corroborates the missing tracking call, but its source is
not additional physical validation of our implementation. Do not stack both
fixes without checking for duplicate tracking.

The extra CoreImage/framework paths are candidates for investigation, not
proven fixes for our missing logos or icons. Recipe searches alone do not
establish the exact patch state of the installed 23G90 cache.

## How to use it next

1. Inventory the patcher's relevant symbols and existing modifications in our
   exact host copy of the 23G90 cache. Record which changes already exist,
   which are absent, and which need different layouts.
2. Prepare one missing compatibility change at a time as an optional,
   reversible candidate. Exercise it in our existing iOS 26 QEMU harness,
   using the same root, scripted Settings/home transitions and asset checks.
   That harness already reached iOS 26 UI without a GPU; replacing it is not
   necessary to investigate these paths.
3. Use a separate Inferno guest only when comparison with Apple device models
   would answer a specific service/boot question. Its t8030 machine and Apple
   peripherals differ from our QEMU virt guest and physical Tensor hardware.
   Virtualization is an upstream capability, not a measured speedup here.
4. Return any tested phone candidate to the existing device coordinator.
   Preserve the current root and active physical attempts. No root rewrite,
   new firmware download, emulator restore or device operation was performed
   for this assessment.

Do not apply the filesystem patcher wholesale to the current root. It also
changes launchd and a Bluetooth audio plugin, and its global software-rendering
choices would interfere with native Metal acceptance. Isolate fallback tests
from native GPU tests and inspect licensing before importing implementation:
the filesystem patcher identifies itself as AGPL-3.0-or-later.

Inferno's Apple device models do not supply a native Tensor G5 PowerVR DXT
driver. Firmware execution, GPU memory, command submission, DXT shaders and
Metal remain the hardware work defined in [NATIVE-METAL.md](NATIVE-METAL.md).
