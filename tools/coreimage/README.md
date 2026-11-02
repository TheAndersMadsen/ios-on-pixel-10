# 23G90 CoreImage fallback experiment

This is a bounded host/QEMU experiment for the existing iOS 26.6.2 root.
It is separate from the native Metal test path. No tool here operates a phone.

- `audit.py` compares Inferno's twelve CoreImage targets with the matching
  stock symbols and our root bytes, accounting for existing PAC rewriting.
- `patch_root.py` accepts the exact shared-cache/CoreImage UUIDs and function
  fingerprint, clones the HFS root, writes eight instruction bytes and updates
  their signed-page hash. It checks the complete output for unrelated changes.
  The input is read-only; existing outputs are refused. Omitting `--output`
  writes only a plan receipt.
- `probe.m` runs only when explicitly injected into SpringBoard. It checks
  the CoreImage UUID and function entry, observes two context constructors,
  tests a constant-red image and color inversion, checks all output pixels and
  guard bytes, then restores both observer methods. Both comparison arms use
  the identical library. It forces no rendering options except those explicitly
  requested by each diagnostic case.
- `verify.py` requires the completed pair, unchanged inputs, matching kernel
  and boot arguments, valid signature receipt, positive control, correct pixel
  outputs and restored observers. Context creation alone is insufficient.

Behavioral reference: Inferno `26b36cc8d59535ed1d9963faab25ac576111edcb`,
`fspatcher/main.cpp`, `CoreImagePatches::apply`. That patcher is AGPL-3.0-or-later.
These helpers are original implementations; no Inferno implementation or Apple
cache/function body is included. Required local readers and signing utilities
remain in their existing research tree, with their own provenance.

## Local reproduction

Use fresh output/report names. All Apple images, symbols and generated results
belong under ignored `research/`.

```sh
python3 -I tools/coreimage/audit.py \
  --reader research/ios26-root-r1/build-r3/tools/renegade/pacstrip_cache.py \
  --symbols research/ios26-inferno-coreimage-r1/audit/stock-coreimage-symbols.txt \
  --stock research/ios26-overlay-r1/work/mnt-stock/System/Library/Caches/com.apple.dyld \
  --root research/ios26-inferno-coreimage-r1/mnt-root/System/Library/Caches/com.apple.dyld \
  --output research/ios26-inferno-coreimage-r1/audit/new-audit.json

python3 -I tools/coreimage/patch_root.py \
  research/ios26-root-r1/build-r3/ios26-phone-r3.img \
  --source-sha256 205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7 \
  --hfs-reader research/ios26-root-r1/build-r3/tools/renegade/hfsx.py \
  --output research/ios26-inferno-coreimage-r1/artifacts/new-widget.img \
  --report research/ios26-inferno-coreimage-r1/receipts/new-widget.json
```

The symbol input is the installed `ipsw dyld symaddr STOCK_CACHE --image
CoreImage` stdout. Redirect stdout explicitly; this CLI's image dump does not
use its JSON output option. Our pruned cache lacks its declared `.symbols`
member, so use the matching stock mount for symbol lookup. Match UUIDs before
using any addresses.

Build the probe using the installed iPhoneOS SDK, preserving an object for
inspection:

```sh
xcrun clang -arch arm64e -isysroot "$(xcrun --sdk iphoneos --show-sdk-path)" \
  -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror -c \
  tools/coreimage/probe.m -o research/ios26-inferno-coreimage-r1/artifacts/new-probe.o
xcrun clang -arch arm64e -isysroot "$(xcrun --sdk iphoneos --show-sdk-path)" \
  -miphoneos-version-min=26.0 -dynamiclib \
  -install_name /private/var/hk/coreimage_probe.dylib \
  research/ios26-inferno-coreimage-r1/artifacts/new-probe.o \
  -framework Foundation -framework CoreImage -framework CoreGraphics \
  -o research/ios26-inferno-coreimage-r1/artifacts/new-probe.raw.dylib
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --sign \
  -o research/ios26-inferno-coreimage-r1/artifacts/new-probe.dylib \
  research/ios26-inferno-coreimage-r1/artifacts/new-probe.raw.dylib
```

The tested local `tools/prepare_overlay.py` adds the probe to the pinned
hgltrack overlay, preserving its 43 records. `receipts/launch-r3.json` contains
the exact two launch commands. They use the existing QEMU harness without
changes, p29, the same probe/overlay/boot arguments, and separate root clones
mapped copy-on-write. Both stop before the queued UI script: this comparison
tests CoreImage context/pixels, not Settings/home transitions or frame rate.
The local mounts are read-only; do not detach another owner's stock mount.
The existing file backend opens its private backing file for writing, so only
the two owned clones had writable host permissions during the runs. They were
returned to mode 0444 after the input-hash checks. Never change the canonical
source's permissions to run the experiment.

```sh
python3 -I tools/coreimage/verify.py research/ios26-inferno-coreimage-r1
```

The `_isWidget` change is global inside the test clone. It intentionally forces
the software context even for a GPU request. It must remain absent from native
Metal acceptance. The earlier bitmap-backed input check failed and its cause
is unresolved; constant-color success does not establish bitmap/import support,
missing-icon repair, UI performance or physical correctness.
