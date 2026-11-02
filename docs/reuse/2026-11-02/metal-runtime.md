# Metal runtime and AIR reuse audit

2026-11-02. Source inspection only; no build, guest, phone command, deployment,
or hardware performance test. Public heads were resolved through GitHub's API
before its shared unauthenticated quota was exhausted. Files below were then
inspected at those exact commits through raw URLs. No upstream code was copied.

The largest opportunity is **reusing an AIR frontend independently of its
Vulkan backend**. A complete Metal-on-Vulkan runtime would add another missing
driver dependency. No project inspected supplies the native DXT backend,
HMGU transport, genuine engine completion, or iOS 26 private driver integration.

| Priority | Candidate | Reuse boundary | Confidence |
|---|---|---|---|
| P1 | `metal2vulkan-air` | Direct frontend dependency or separate host oracle | High source evidence; integration untested |
| P2 | Darling Metal | Selected Objective-C adapters and API coverage reference | High source evidence; private ABI mismatch |
| P2 | Indium/Iridium | Public API/lifecycle reference; selected permissive code | High source evidence; old LLVM assumptions |
| P2 | MetalLibraryArchive | Existing format reference, additional differential tests | High; mostly overlaps existing work |

**Local baseline and duplication check.**

`research/ios26-metal-native-20261102/air/airfront/` already implements an
original MIT scalar compute frontend. Its README deliberately refuses control
flow, most vectors/intrinsics, and threadgroup memory. `metallib.py` invokes
host `llvm-dis`; its provenance already credits MetalLibraryArchive's layout.
The handoff reports substantial CPU semantic tests, but the Python frontend
has no native in-process Metal compile callback. Those are existing results,
not rerun by this audit.

`research/ios26-metal-native-20261102/metal/src/HMNativeMetal.m`, `hmn.c`,
`hmn_streams.c`, and `include/hmn.h` already define a stricter native path.
They require reviewed compiler and stream peers, immutable stage bytes,
binding metadata, a native-stage validator, and exact completion/cache handback.
The old `research/ios26-metaldrv-r1/src/drv/hm_iokit.c` already calls real
IOKit; copying another runtime cannot replace its kernel-side dependencies.
The current production design preserves Apple's Metal framework and implements
device/queue/encoder subclasses; a replacement public framework has a different seam.

**1. `steelbrain/metal2vulkan`: the strongest new candidate.**

Verified `master` at `219f01365dc4c8eb346816c405b5b17403793764`, committed
2026-10-29. The current frontend package is version 0.2.0. Search results also
show an older LGPL-only, single-package layout; do not use those stale facts.
The pinned [workspace manifest](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/Cargo.toml)
declares Rust 1.98 and **GPL-2.0-or-later OR LGPL-3.0-or-later**; the
[licence notice](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/LICENSE)
confirms that choice. This is reusable copyleft code, not an MIT component.
Select and record its intended dependency/licensing arrangement before promotion.

The [frontend manifest](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/Cargo.toml)
has no Vulkan or LLVM dependency: `sha2`, plus optional `serde`; no binary or
build script is enabled. The backend separation is real source structure.
Host LLVM tools appear in test/dev tooling, rather than the frontend's normal
dependency list. Rust/iOS target compilation has not been checked here.

The useful entry points are [the public crate API](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/lib.rs),
[bitcode decoding](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/bitcode/mod.rs),
and [container parsing](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/container/mod.rs).
`container::parse` accepts metallib, universal AIR slices, wrappers and raw
bitcode. `bitcode::decode` returns typed IR and checked metadata; public
`specialize`, `specialize_linked` and `specialize_dynamic` select and normalize
an entry. This could remove substantial parser and specialization maintenance.

The [AIR ABI decoder](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/abi/mod.rs)
checks argument roles, address spaces, metadata keys and structural consistency.
Its [argument parser](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/abi/args.rs)
also covers argument-buffer member layouts. Those are useful beyond the first
three-buffer compute test; we should stop independently rediscovering them.

The [canonicalizer](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/canon/mod.rs)
contains function-constant binding, linking, inlining, pointer normalization,
constant propagation and pruning. It operates on this project's IR, so importing
individual routines into our Python parser is less attractive than adopting
the frontend boundary. Its IR still needs explicit lowering into our limited
scalar/ISA plan; accepting more AIR must never advertise unsupported DXT work.

[Per-attempt budgets](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/budget/mod.rs)
and [API surface tests](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/tests/api_surface.rs)
are useful infrastructure too. Input-scale allocation, cancellation and work
limits exist in source. Their desktop-scale defaults are not suitable phone
budgets by assumption; choose limits for our supported shader subset.

Concrete first task: create a separately pinned **host-only frontend adapter**
which reads our own `buffer_add.metallib`, `single_add.metallib`, and validation
shader, then emits our existing `hackios.air.f32-buffer-plan.v1` contract.
Compare bindings, address spaces, operation ordering, offsets and refusals with
the existing frontend. Include half rounding, poison, malformed containers and
the existing denorm-mode refusal. Use no extracted Apple shader corpus.
This test is recommended, not performed. Its success would justify evaluating
a C ABI wrapper for `hmn_peer_ops.compile` and `release_compiled`.
It would not satisfy the native-stage validator or supply USC/PDS/CDM code.

**2. `darlinghq/darling-metal`: useful adapters, wrong drop-in boundary.**

Verified `main` at `a55b9507a97fab22a927fe007de46fc9924f9b47`, committed
2026-10-24. GitHub's repository metadata reports no single licence, but inspected
implementation and header files explicitly carry **MPL-2.0** SPDX notices.
Use file notices, not the repository badge; other files have other licences.

Its [device implementation](https://github.com/darlinghq/darling-metal/blob/a55b9507a97fab22a927fe007de46fc9924f9b47/src/Metal/MTLDevice.mm)
wraps `Indium::Device` and exposes public library, queue, buffer and pipeline
methods. Its [compute encoder](https://github.com/darlinghq/darling-metal/blob/a55b9507a97fab22a927fe007de46fc9924f9b47/src/Metal/MTLComputeCommandEncoder.mm)
translates buffer bindings and dispatch dimensions. Its
[command buffer](https://github.com/darlinghq/darling-metal/blob/a55b9507a97fab22a927fe007de46fc9924f9b47/src/Metal/MTLCommandBuffer.mm)
bridges retained Objective-C completion blocks into C++ callbacks.
These are actual implementations, not merely stub headers.

The [build](https://github.com/darlinghq/darling-metal/blob/a55b9507a97fab22a927fe007de46fc9924f9b47/CMakeLists.txt)
constructs replacement Metal/MetalKit frameworks for Darling and optionally
includes Indium. It does not subclass our installed iOS 26 `_MTLDevice` ABI,
implement HMGU, or establish iOS 26 private selectors such as
`commitWithDeadline:`. Replacing the whole framework would expand scope and
lose the current integration boundary.

Concrete task: use its public method implementations as an API coverage
checklist against `HMNativeMetal.m`, then port only an independently useful
descriptor/block-lifetime helper if a gap is demonstrated. Preserve MPL notices
for copied files. Test descriptor copying, buffer-offset changes and callback
retention under host mocks. This saves API bookkeeping, not GPU execution work.
Its own comments leave resource-retention questions unresolved; do not import
completion/lifetime policy over our stricter native queue contract.

**3. `darlinghq/indium`: permissive code with important limitations.**

Verified default `main` at `8423a7d2f053167030d2bc4a227f96243c740667`, committed
2023-04-11. The [root licence](https://github.com/darlinghq/indium/blob/8423a7d2f053167030d2bc4a227f96243c740667/LICENSE)
is **0BSD**. `iridium` is a subdirectory here; a separate
`darlinghq/iridium` repository returned 404. Darling Metal's exact Indium
submodule revision was not resolved before API throttling; these are separate
verified heads, not a claim they constitute a tested matched build.

Its [command buffer](https://github.com/darlinghq/indium/blob/8423a7d2f053167030d2bc4a227f96243c740667/src/indium/command-buffer.cpp)
uses Vulkan allocation/submission and a condition-variable completion path.
It explicitly delays scheduled handlers until completion as a TODO. Treat it
as a lifecycle reference, not a correct replacement for native completion.
The [build](https://github.com/darlinghq/indium/blob/8423a7d2f053167030d2bc4a227f96243c740667/CMakeLists.txt)
requires Vulkan and LLVM; its runtime cannot operate atop HMGU unchanged.

The [AIR implementation](https://github.com/darlinghq/indium/blob/8423a7d2f053167030d2bc4a227f96243c740667/src/iridium/air.cpp)
uses LLVM's C bitcode API, then emits SPIR-V. It contains typed-pointer
`LLVMGetElementType` assumptions and aborts on some parse failures. This is a
poor candidate to replace the current stricter frontend wholesale.
Selected sampler/descriptor translations in
[library.cpp](https://github.com/darlinghq/indium/blob/8423a7d2f053167030d2bc4a227f96243c740667/src/indium/library.cpp)
are lower-risk reuse when the corresponding native feature is implemented.

**4. `YuAo/MetalLibraryArchive`: useful, already partly consumed.**

Verified `master` at `de573ba4a7b986bbecb3e4ce2464945d266a28e9`, committed
2023-05-24; [MIT licence](https://github.com/YuAo/MetalLibraryArchive/blob/de573ba4a7b986bbecb3e4ce2464945d266a28e9/LICENSE).
Its [Archive parser](https://github.com/YuAo/MetalLibraryArchive/blob/de573ba4a7b986bbecb3e4ce2464945d266a28e9/Sources/MetalLibraryArchive/Archive.swift)
exposes functions, platform, library type and extension tags. Hash verification
is conditional on importing `Crypto`; the normal
[package configuration](https://github.com/YuAo/MetalLibraryArchive/blob/de573ba4a7b986bbecb3e4ce2464945d266a28e9/Package.swift)
supplies Swift Crypto, whereas its WASM mode omits it. Do not treat every build
as a hash-checking oracle. It neither translates AIR nor generates GPU code.

Its [tests](https://github.com/YuAo/MetalLibraryArchive/blob/de573ba4a7b986bbecb3e4ce2464945d266a28e9/Tests/MetalLibraryArchiveTests/Tests.swift)
compile authored source under different SDK/library/source-recording options.
Adapt that matrix to our own sources and compare metadata with our parser.
The local frontend already used its layout as a reference; report this as
incremental test coverage rather than a new compiler discovery.

**Directions that do not solve this task.**

[MoltenVK](https://github.com/KhronosGroup/MoltenVK) consumes working Metal to
implement Vulkan. [ANGLE](https://github.com/google/angle) implements OpenGL ES,
including backends which themselves consume Metal or Vulkan. Neither supplies
our missing native Metal driver. Apple's
[Metal shader converter](https://developer.apple.com/metal/shader-converter/)
produces Metal libraries from shader IR; it is no DXT code generator.
The installed Metal compiler already supplies our owned AIR test inputs.

The actionable order is the pinned AIR host adapter, a measured decision about
its native dependency boundary, then selected API helpers only when a real gap
appears. Keep the native ISA/VM/stream/completion owners on their current work.
No finding here establishes native rendering, iOS private ABI compatibility,
hardware correctness, or a phone speedup.
