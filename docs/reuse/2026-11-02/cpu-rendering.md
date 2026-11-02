# CPU rendering reuse audit

Audit date: 2026-11-02. Research only; no build, upstream native-code execution,
emulator, phone operation, deployment or performance measurement in this audit.

The best immediate saving is to finish the existing guarded sampler worker,
then borrow a small proven row kernel only if coverage and timings justify it.
A whole software renderer does not attach to iOS 26's current compositor API.

## Current local overlap

- `NOTES.md` records physical profile PCs in QuartzCore's `ARGB8_Host`
  `image_sampler`; this establishes a hot family, not every caller's operation.
- `research/ios26-opt-20261102/sampler/src/hsampler.c` already implements an
  original four-pixel NEON interior path, with scalar-original borders and
  refusal for unsupported transforms, layouts, overflow and aliasing.
- Its `hs_prepare` currently admits `dx == 65536`, positive stride and a known
  8-bit format. `hs_render` performs vertical rounded interpolation followed
  by horizontal rounded interpolation. Both-zero fractions use `memcpy`.
- `sampler/src/hs_hook.c` already fingerprints the exact local framework,
  checks its dispatch table, self-checks, and exposes observe/verify/fast modes.
  Verification retains original output and latches fallback on a mismatch.
- `sampler/tests/differential.c` already runs the actual locally supplied
  original ARM64 leaf as its oracle. It contains fraction-grid, border,
  extreme-coordinate, guarded-page, tail, alias and wrapper checks.
  This audit read those sources; it did not rerun that harness or certify it.
- `research/ios26-metaldrv-r1/src/rt/airrt.c` is a separate own CPU AIR runtime
  with float sampling, mip/LOD, swizzles and sRGB conversion. Its handoff says
  there is no compositor integration. Optimizing it does not automatically
  accelerate the physically profiled QuartzCore path.

Do not commission another sampler from scratch or replace the current worker
with an upstream library before its real call coverage is known.

## Verified source pins

Current refs were resolved through the primary Gitiles/GitLab APIs and the
listed source files were read at those commits. Pins are observations from this
audit, not promises that these commits are release tags or build on iOS.

| Project | Verified commit | File-level licence examined | Role here |
|---|---|---|---|
| libyuv | `79ca9187e540faaaca47b34622e110d07f335d05` | BSD 3-Clause; preserve notices and accompanying patent grant | Conditional small row-kernel reuse |
| pixman | `8bbb12a7b29bd48ef57764102f4f278e1e22b7c0` | MIT-style notices in the inspected ARM64 files; preserve each author | Tests, bounded fast-path architecture; not exact sampling replacement |
| Skia | `e5ad3868b8dbc2d3b5d4048232af74041a04a595` | BSD 3-Clause in the inspected raster-pipeline files | SIMD/blend reference and independent tests |
| SwiftShader | `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5` | Apache-2.0 in `SamplerCore.cpp`; dependencies have separate licences | AIR-runtime sampling reference only |

Source copies and the equation-check receipt remain in ignored
`research/reuse-audit-20261102/cpu-rendering/`. No external implementation or
proprietary framework bytes are included in this report.

## 1. libyuv: a compatible single-axis primitive, incompatible full scaler

**Priority P1, high confidence in arithmetic fit; speed benefit unmeasured.**
The useful exact symbol is
[`InterpolateRow_NEON` in `source/row_neon64.cc`](https://chromium.googlesource.com/libyuv/libyuv/+/79ca9187e540faaaca47b34622e110d07f335d05/source/row_neon64.cc#3655).
It processes two byte rows with an 8-bit fraction, a copy case and a half-way
rounded-average case. Its general unsigned multiply/add/round formula matches
the local sampler's single-axis signed-difference rounded lerp for byte inputs.

I exhaustively compared the two scalar equations for all 256 × 256 × 256
channel/fraction combinations: **16,777,216 cases, zero mismatches**. The receipt
is `equation-check.json` in the ignored source-copy directory. This proves the
equations used in this comparison; it is not execution of libyuv assembly,
proof of the hook ABI, or phone evidence.

The smallest seam is an optional backend inside the existing `hs_render`:

1. For `fx == 0`, use the admitted top/bottom rows and `fy >> 7` as the byte
   interpolation fraction. Width is **bytes**, so pass four times pixel count.
2. For `fy == 0`, the same operation can blend a row against its one-pixel
   offset using `fx >> 7`, only within the already validated interior.
3. Keep `memcpy` when both fractions are zero, and retain the current fused
   two-axis path rather than introducing scratch-row traffic for all spans.

The raw NEON loop processes complete blocks. A partial final block must use
the existing safe local tail or the inspected
[`InterpolateRow_Any_NEON` wrapper family](https://chromium.googlesource.com/libyuv/libyuv/+/79ca9187e540faaaca47b34622e110d07f335d05/source/row_any.cc).
Do not call it with zero bytes or assume padding beyond the source allocation.
The BSD licence and patent grant are available in
[`LICENSE`](https://chromium.googlesource.com/libyuv/libyuv/+/79ca9187e540faaaca47b34622e110d07f335d05/LICENSE)
and [`PATENTS`](https://chromium.googlesource.com/libyuv/libyuv/+/79ca9187e540faaaca47b34622e110d07f335d05/PATENTS).

**Important negative result:** `ScaleARGBFilterCols_NEON` is not a substitute.
The inspected
[`scale_neon64.cc`](https://chromium.googlesource.com/libyuv/libyuv/+/79ca9187e540faaaca47b34622e110d07f335d05/source/scale_neon64.cc#1295)
and [`ScaleARGBFilterCols_C`](https://chromium.googlesource.com/libyuv/libyuv/+/79ca9187e540faaaca47b34622e110d07f335d05/source/scale_common.cc#1035)
use seven-bit horizontal weights with a documented `127 ^ f` formulation.
A constant channel of 255 yields 253 under that formula; our local lerp yields
255. Naming both operations bilinear does not make their pixels equivalent.

Also reject `ARGBBlendRow_NEON` for general transparent surfaces: the inspected
routine writes opaque output alpha. libyuv's
[`format documentation`](https://chromium.googlesource.com/libyuv/libyuv/+/79ca9187e540faaaca47b34622e110d07f335d05/docs/formats.md)
states that ARGB is BGRA in little-endian memory and blending expects
premultiplied channels. Those conditions need an explicit caller contract.

**Labour saved:** row assembly, block handling and upstream differential-test
patterns can be reused rather than authored. The existing sampler already does
much of this; the marginal saving is small until another compatible hot span is
identified. No claim that this backend is faster than the current intrinsics.

## 2. pixman: mature compositing/test infrastructure, different interpolation

**Priority P2, high confidence as a reference; conditional code reuse.**
The actual AArch64 paths are named `arma64`, not `arm-a64` or the ARMv7 files:

- [`pixman-arma64-neon-asm.S`](https://gitlab.freedesktop.org/pixman/pixman/-/blob/8bbb12a7b29bd48ef57764102f4f278e1e22b7c0/pixman/pixman-arma64-neon-asm.S)
  contains generated format/operation-specific composite routines.
- [`pixman-arma64-neon-asm-bilinear.S`](https://gitlab.freedesktop.org/pixman/pixman/-/blob/8bbb12a7b29bd48ef57764102f4f278e1e22b7c0/pixman/pixman-arma64-neon-asm-bilinear.S)
  separates fetch, interpolation, mask, destination combine and store macros.
- [`pixman-arm-neon.c`](https://gitlab.freedesktop.org/pixman/pixman/-/blob/8bbb12a7b29bd48ef57764102f4f278e1e22b7c0/pixman/pixman-arm-neon.c)
  binds fast paths by operator, source, mask and destination format.

This architecture is useful for expanding **our own** future image/blend
dispatch without creating a generic per-pixel switch in the inner loop.
The inspected private header sets seven interpolation bits, and assembly keeps
vertical precision before final combined truncation. It is not the local
sampler's two eight-bit rounded lerps. Do not install its bilinear output as an
exact QuartzCore replacement.

Best reusable assets now are
[`test/scaling-test.c`](https://gitlab.freedesktop.org/pixman/pixman/-/blob/8bbb12a7b29bd48ef57764102f4f278e1e22b7c0/test/scaling-test.c)
and [`test/affine-test.c`](https://gitlab.freedesktop.org/pixman/pixman/-/blob/8bbb12a7b29bd48ef57764102f4f278e1e22b7c0/test/affine-test.c):
borrow geometry, transform and repeat-mode case generation, then use the actual
local original as the numerical oracle. Reuse case generators with their
notices; do not relax exact comparisons to pixman's numerical rules.

Dependencies include its generated configuration, private macros and source
formats. Its assembler helper does support configurable leading underscores
and excludes ELF directives on non-ELF targets; that is encouraging, not an
iOS assembly-build result. Compare it in an isolated host harness first.

**Labour saved:** broader adversarial geometry coverage and mature bounded
dispatch patterns. A whole-library compositor transplant adds an API adapter
project and does not remove Apple's private software-renderer ABI work.

## 3. Skia: useful SIMD/color kernels, substantial pipeline coupling

**Priority P2, high confidence in reference value; low confidence in immediate
runtime integration.** The inspected
[`SkRasterPipeline_opts.h`](https://skia.googlesource.com/skia/+/e5ad3868b8dbc2d3b5d4048232af74041a04a595/src/opts/SkRasterPipeline_opts.h)
contains NEON lane operations, `div255_accurate`, premultiplied `srcover`,
format conversion and fused clamp/non-sRGB bilinear stages.
Its byte-rounding and float/high-precision stages are different contracts;
select a single operation with explicit alpha and colour-space semantics.

The smallest useful experiment is a standalone opaque/transparent blend kernel
for a future **own** renderer, tested against `airrt.c` format packing and a
separate scalar premultiplied reference. It is not a reason to replace the
currently sampled image leaf. Keep sRGB decoding/encoding in the correct order.

[`SkRasterPipelineTest.cpp`](https://skia.googlesource.com/skia/+/e5ad3868b8dbc2d3b5d4048232af74041a04a595/tests/SkRasterPipelineTest.cpp)
has tail and load/store coverage worth adapting. Pulling the header unchanged
also pulls context structures, Skia types, skcms and stage-dispatch machinery;
the BSD notice does not make that integration free. Save manual work by
reusing narrowly scoped algorithms and cases, not adopting the entire pipeline.

## 4. SwiftShader and LLVMpipe: reference renderers, not drop-in acceleration

**Priority P3 for immediate UI lag.** SwiftShader's
[`SamplerCore.cpp`](https://swiftshader.googlesource.com/SwiftShader/+/cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5/src/Pipeline/SamplerCore.cpp)
has useful LOD, addressing, mip and format logic for auditing our AIR sampler.
It emits Reactor/JIT operations and depends on Vulkan sampler/image state;
it is not a plain row function callable from the current hook.

The pinned
[`README`](https://swiftshader.googlesource.com/SwiftShader/+/cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5/README.md)
describes a CPU Vulkan implementation. Its Apple CMake branch enables Vulkan
Metal-surface integration, not an implementation of native iOS Metal drivers.
An AIR/Metal adapter and presentation path would still need to be written.
LLVMpipe is likewise not a ready native Metal ABI implementation; it was not
deeply inspected in this audit and is not counted as a verified reuse find.
Neither is a demonstrated shortcut to the required native PowerVR path.

## Concrete next task and acceptance

First consume the active sampler worker's result and observe actual eligible
calls/fraction classes. If one-axis spans are common, compare one isolated
libyuv row-backend candidate against the current candidate and actual original
using the existing host harness. Cover every byte fraction, odd widths,
guarded final pixels, strides, overlap refusal and unaligned buffers; require
exact bytes, emitted ARM64 text symbols and no disabled-gate empty object.
Record host time per eligible pixel alongside fallback/call coverage.

Keep only a measured improvement; a passed mathematical identity alone does
not justify replacing the existing code. The parent's existing reversible
runtime verification and later controlled physical profile remain necessary.
This task can reuse an existing adapter and oracle instead of creating another
rendering stack. All phone impact and overall frame-rate gain remain unproved.
