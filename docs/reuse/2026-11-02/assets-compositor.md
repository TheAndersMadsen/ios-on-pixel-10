# Assets, compositor compatibility and symbolication reuse

Research date: 2026-11-02. Scope: read-only source and existing local evidence.
No implementation, compile, guest run, physical boot or performance measurement
was performed for this report. Upstream HEADs were resolved through the GitHub
API, then selected source files were read at the resulting immutable revisions.
Later API reads hit its unauthenticated rate limit; raw pinned source remained
available. This is a targeted audit, not complete coverage of every framework.

## What is actually missing

The physical p29 handoff records visible home and Settings, missing graphics,
heavy lag and an intermittent early backboardd `NSURL` nil-path exception.
It also records a surviving Settings/home transition after `hgltrack` installed
surface tracking. These are separate observations: an absent icon does not
establish a missing file, and a nil URL does not establish an asset-catalog bug.

The current `settings_assets` owner already has a useful investigation in
`research/ios26-opt-20261102/settings_assets/` and
`research/ios26-fleet/handoffs/opt-settings_assets.md`:

- Selected physical and QEMU CoreUI resources match; simply restoring those
  same overlay files is not a new fix.
- An older QEMU image also had a blank Battery row despite other icons drawing.
- The removed BatteryUsageUI catalog did not contain the expected battery glyph.
- The local host CoreUI probe found different results for a legacy battery
  name and its canonical name; the canonical glyph also depended on a rendition
  parameter. This was host macOS behavior, not iOS 26 execution or proof of cause.

Extend this existing work rather than introduce a competing asset loader.

## 1. Reuse ipsw's catalog inventory and variant resolver

Priority **P0 for diagnostics**; confidence high in source availability,
unproved against the complete local iOS 26 catalog set.

Pin: `blacktop/ipsw` at
[`a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388`](https://github.com/blacktop/ipsw/tree/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388).
Repository [licence](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/LICENSE):
MIT. Its third-party dependencies and native macOS renderers retain their own
terms; the MIT licence does not license Apple's input assets or frameworks.

Concrete code:

- [`pkg/car/car.go`](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/pkg/car/car.go):
  `Config.MetadataOnly`, `VariantQuery`, rendition database and diagnostics.
- [`pkg/car/catalog.go`](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/pkg/car/catalog.go):
  `Stats`, `VariantQuery.matches`, selection, deferred decode and BOM validation.
- [`pkg/car/reference.go`](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/pkg/car/reference.go):
  full-key indexing, internal-reference validation, dependency resolution and crop.
- [`cmd/ipsw/cmd/car.go`](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/cmd/ipsw/cmd/car.go):
  existing command boundary; use this externally before considering vendoring.

The [package guide](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/pkg/car/README.md)
documents metadata-only JSON, filterable variants and per-entry export outcomes.
Unknown or unsupported entries remain distinguishable from decoding failures.
It expressly does not implement Apple's runtime rendition fallback rules.
Modern effects, gradients, fonts, some codecs and other layouts are incomplete;
its tests do not establish universal CAR-version support.

**Direct reusable tool**, not a replacement iOS CoreUI implementation. It avoids
writing another BOM walker, compression suite, internal-reference resolver and
JSON inventory. Metadata-first use avoids decoding or copying artwork merely
to discover whether a named rendition exists. Parsing CAR files has no inherent
16 KiB XNU page dependency; format compatibility still needs actual-input checks.

**Integration-sized task:** add a host-only catalog audit adapter beside the
existing `settings_assets` tools. Take an explicit list of local catalog paths
and hashes, run a pinned `ipsw car <catalog> --metadata-only --json`, and produce
a normalized ignored manifest of names, full keys, references and unsupported
layouts. Compare full root, selected overlay and one deliberately missing
fixture. Distinguish missing catalog, missing name, missing exact variant,
unsupported parser layout and runtime lookup failure. Do not turn every
unsupported result into “missing artwork.”

Smallest proof: choose one known visible icon, the failing row's exact requested
name, its canonical alias and an intentionally nonexistent name. Compare the
manifest with the existing native CoreUI probe and retain discrepancies as
unknowns. No device write or image rebuild is needed. Store all catalog-derived
data under ignored `research/`; commit only the adapter and synthetic tests.

## 2. Use AssetCatalogTinkerer's host CoreUI path as a second oracle

Priority **P1**; confidence high for a diagnostic seam, limited for cross-OS
behavior. Pin: `insidegui/AssetCatalogTinkerer` at
[`f5208620695b1eec451d6943beeb4ac1bfd37c63`](https://github.com/insidegui/AssetCatalogTinkerer/tree/f5208620695b1eec451d6943beeb4ac1bfd37c63).
Its [licence](https://github.com/insidegui/AssetCatalogTinkerer/blob/f5208620695b1eec451d6943beeb4ac1bfd37c63/LICENSE)
is BSD-2-Clause; preserve notices if importing its implementation.

[`ACS/Source/AssetCatalogReader.m`](https://github.com/insidegui/AssetCatalogTinkerer/blob/f5208620695b1eec451d6943beeb4ac1bfd37c63/ACS/Source/AssetCatalogReader.m)
opens `CUICatalog`, enumerates theme-store keys and queries renditions.
Its theme-store reader has distinct SVG and bitmap branches, including glyph
weight/size/render-mode naming. It uses macOS CoreUI/CoreSVG rather than
providing an independent implementation of those frameworks.
[`act/AssetCatalogTinkererCLI.swift`](https://github.com/insidegui/AssetCatalogTinkerer/blob/f5208620695b1eec451d6943beeb4ac1bfd37c63/act/AssetCatalogTinkererCLI.swift)
already offers `info` and `extract`, avoiding GUI automation.

**Reusable host tool and API usage pattern.** The existing local
`tests/catalog_probe.m` already uses the same `CUICatalog` family and a more
specific vector-glyph selector. Do not replace that probe with a generic image
export that loses rendition parameters. Reuse the reader's key enumeration to
extend the probe only where it saves work.

Smallest proof: check whether the exact canonical glyph has a rendition under
the parameter tuple requested by IFSymbol; report lookup, decode and rendering
separately. Cross-check with ipsw's independent manifest. A host decoder finding
an SVG establishes readable input, not that iOS IconServices selected or drew it.
The [README](https://github.com/insidegui/AssetCatalogTinkerer/blob/f5208620695b1eec451d6943beeb4ac1bfd37c63/README.md)
also acknowledges unsupported modern asset types. No verified claim of complete
iOS 26 CAR compatibility was found in the inspected source.

## 3. Reuse ipsw symbolication selectively; an upgrade cannot create symbols

Priority **P1**, because manual PC attribution is limiting current profiling.
Same immutable pin and MIT terms as candidate 1; this is a different subsystem.

[`cmd/ipsw/cmd/dyld/dyld_a2s.go`](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/cmd/ipsw/cmd/dyld/dyld_a2s.go)
already handles ASLR slide removal and direct symbol lookup, with an optional
address-to-symbol cache.
[`pkg/dyld/symbols.go`](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/pkg/dyld/symbols.go)
builds that cache from public, local, stub-island and Objective-C information.

Important negative result:
[`pkg/dyld/file.go`, `Open` / `openSubCaches`](https://github.com/blacktop/ipsw/blob/a8f1f5219865f01c6d7a6ef9f29b61c5fbfb7388/pkg/dyld/file.go#L348)
still opens every declared cache member. If `SymbolFileUUID` is set, absence of
the matching `.symbols` member returns an error before symbol lookup. Do not
promise that installing a newer ipsw fixes the missing-file blocker in NOTES.
Nor can an address map reconstruct arbitrary stripped C++ function names.

Local overlap: the live-analysis proposal already has cache-header/image
mapping and QuartzCore disassembly-based labels under
`research/ios26-opt-20261102/live_analysis/proposal/tools/live_profile.py`.
Keep its reliable image/range attribution and known ARGB8 sampler labels.

**Integration-sized task:** make the profiler accept a versioned optional symbol
provider. Verify cache UUID, declared-member availability and tool pin before
invoking ipsw; retain image+offset and provenance when full lookup is impossible.
Where matching locally owned symbols are already available, use ipsw rather
than implement another ObjC/export-trie resolver. Check a known sampler PC,
a known export, an image-only PC and an unmapped PC, including wrong-slide and
wrong-UUID inputs. Do not download alternate proprietary symbol bundles or
silently label the nearest export as the containing function.

## Lower-value leads and rejected shortcuts

- **CARParser:** `Timac/CARParser`
  [`c62dd0f27abbf44c3aa9598551b4110d61f98755`](https://github.com/Timac/CARParser/tree/c62dd0f27abbf44c3aa9598551b4110d61f98755),
  [MIT](https://github.com/Timac/CARParser/blob/c62dd0f27abbf44c3aa9598551b4110d61f98755/LICENSE.txt).
  [`Car.h`](https://github.com/Timac/CARParser/blob/c62dd0f27abbf44c3aa9598551b4110d61f98755/CARParser/Car.h)
  and [`main.m`](https://github.com/Timac/CARParser/blob/c62dd0f27abbf44c3aa9598551b4110d61f98755/CARParser/main.m)
  are useful compact structure/TLV references. This pin is from 2018; they do
  not establish modern SF Symbols support. Prefer the maintained ipsw parser
  and keep this as a format reference, rather than another production decoder.
- **Inferno:** the current [local assessment](../../INFERNO.md) already identifies
  its software-rendering compatibility patches and AGPL-3.0-or-later patcher.
  Its `track_surface` work matches our physically exercised fix, so duplicating
  it adds no established capability. CoreImage/widget/software-wallpaper leads
  need exact 23G90 state comparison and one optional QEMU A/B each; none is yet
  a demonstrated cure for missing Settings icons or phone lag. Global forced
  software paths also interfere with native Metal tests.
- **Darling:** current
  [`3447ff5ab8e837ea54a13a506c60d34d77e2bd15`](https://github.com/darlinghq/darling/tree/3447ff5ab8e837ea54a13a506c60d34d77e2bd15)
  describes a macOS-on-Linux runtime, with mixed per-component licensing and
  active GUI development. That is no evidence for a drop-in iOS 26
  CoreUI/IconServices/FrontBoard replacement. No file-level compatible
  implementation was established here; do not schedule wholesale substitution.

The likely saving is substantial **diagnostic and parser development**, not
proven runtime acceleration. The first deliverable should be the catalog/variant
manifest adapter shared with the existing settings owner. Any icon fix must
then demonstrate the requested rendition actually drawing in the existing
guest route before it becomes a phone candidate.
