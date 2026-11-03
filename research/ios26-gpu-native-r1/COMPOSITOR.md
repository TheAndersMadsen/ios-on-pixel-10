# CoreAnimation / backboardd compositor and Liquid Glass

Date: 2026-11-04. Owner: agent 8 (compositor / QuartzCore / render-server path). **Read-only research:** no XNU edit, build, build lock, Git operation, phone/USB action, or device-state change was performed. The only repository file written is this document.

Evidence labels: **PHYSICAL** = the named Pixel 10 Pro capture; **SOURCE** = exact source, cache, symbols, or recipes read; **HOST** = existing host-only test; **EXTERNAL** = linked prior art, not a result on this phone; **DESIGN** = proposed work requiring the stated proof. This expands [PLAN.md](PLAN.md) stage 7 and uses [METAL.md](METAL.md), [IOACCEL.md](IOACCEL.md), [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md), [MMU.md](MMU.md), [COREMEM-INIT.md](COREMEM-INIT.md), and [PRIORART.md](PRIORART.md).

## 0. Decision and minimum outcome

Do **not** write a replacement compositor and do **not** expose a compute-only Metal device to backboardd. Implement the existing QuartzCore `CA::OGL::MetalContext` consumer profile in stages:

1. Agent 7's owned clear/triangle/quad render oracle with exact pixels and guards.
2. An **owned offscreen `CARenderer` frame** with known solid/blended pixels and a real completion/readback.
3. A **backboardd GPU-composited known frame to the panel**, with the same surface/submission/completion/present ID chain.
4. An offscreen `CABackdropLayer` blur with a deterministic high-contrast source.
5. Real MaterialKit/Control Center glass with the measured variable-blur, vibrancy, and iOS 26 glass filters. A Gaussian blur alone is **not** full Liquid Glass.

The minimum GPU-compositor milestone is **stage 3**, not “Metal device non-nil,” a `MetalContext` constructor, a changed `HGLTRACK` string, or an ordinary DPU swap. The final visible acceptance is a **real render-server-captured, blurred backdrop on the panel**, confirmed by `hk shot` screenshots plus objective pixel evidence and GPU completion before the presented IOSurface reaches the DPU.

For a cheap interim, first repair/probe QuartzCore's existing **software** backdrop path. The pinned cache contains substantial software blur and vibrancy code; “the CPU cannot blur” is not established. An improved `hk_flatmat` can supply dynamic average-colour materials, but that is explicitly not glass and must be disabled for all native acceptance.

## 1. Current physical truth and what the screenshots do/do not prove

The int3 boot is [live-20261103-232046-a7-int3](../laguna-usb-fix/attempts/live-20261103-232046-a7-int3/console.txt), image `eff0ed9f…`, console SHA-256 `2190170b…` as pinned in [LIVE-EVIDENCE.md](LIVE-EVIDENCE.md).

| Evidence | Established fact | Limit |
|---|---|---|
| `HGLTRACK: SWContext slot wrapped` at console `:889` | The tracked QuartzCore software-context path is active. `hgltrack` wraps `SWContext::create_surface_from_iosurface` and then calls `Context::track_surface` when needed. | It is not a GPU context or proof of GPU work. It also does not name every later context by itself. |
| backboardd `IOAcceleratorES -> 0 found` at `:1423`; `AGXAccelerator -> none` at `:1459,1490` | No accelerator matching either required class is registered. | Apple's AGX driver is not a valid PowerVR DXT backend. |
| SpringBoard `AGXAccelerator -> none` at `:2244`, `IOAcceleratorES -> 0 found` at `:2323` | The discovery failure affects SpringBoard too. | Registry matches alone would not establish rendering. |
| `SUICOrbView ... Failed to get Metal device` at `:2329` | A concrete Metal consumer cannot create a device. | This is presently a discovery/device failure, not a shader failure. |
| AppleCLCD opens/matches at `:1393-1416`; BGRA surface 2 is 1125x2511, bpr 4608 at `:1494`; swaps follow | CPU composition, IOSurface IPC, and DPU scanout work independently of an accelerator. | A swap/kick/done count is not Metal execution or FPS. |
| [Home screenshot](../laguna-usb-fix/attempts/live-20261103-232046-a7-int3/ui/0008-008-home.png) | The dock is a flat grey band; two widget placeholders are white while text/icons render. | **Consistent with** flat/missing materials, but not a controlled blur oracle: the wallpaper is mostly black and this script did not open Control Center. Do not use this image alone to prove that a software Gaussian routine is broken. |

The Control Center material investigation is [cc/FIX.md](../ios26-phaseb-r1/cc/FIX.md):

- `MTMaterialLayer` derives from `CABackdropLayer`. The `modules` recipe has only a colour matrix over the captured backdrop and no independent fill; `modulesBackground` specifies blur 25 plus luminance/saturation operations. Thus a missing capture produces black/transparent tiles rather than a useful opaque material.
- Reduce Transparency replaces blur with average colour **but retains a backdrop filter**, so the earlier preference change was not a fallback around capture.
- `hk_flatmat` disables the backdrop and filters and supplies static colours; it also disables filters whose type starts `vibrant`, allowing plain glyph tint to show. Its host suite is 13/13 PASS, but the cited document marks the built image **not booted**. Treat physical effectiveness separately from that HOST result.
- `hk_flatmat` changes SpringBoard's layer tree, not backboardd's renderer. It cannot repair render-server capture and must be **off** for blur/vibrancy/native Metal acceptance.

## 2. The actual render-server architecture

**SOURCE + DESIGN:** the relevant path is:

```text
SpringBoard/app CALayer tree and MaterialKit recipes
  -> CATransaction serialization, remote CAContext IDs, fences
  -> backboardd's CA::Render::Server / CA::WindowServer
  -> CA::Render layer/update/backdrop groups
  -> CA::OGL::Renderer collect/prepare/render
  -> CA::OGL::MetalContext (target) or SWContext (current fallback)
  -> command buffer + shared event/fence completion and cache handback
  -> IOSurface destination
  -> CA::WindowServer::IOMFBDisplay finish_update / swap_set_layer
  -> AppleCLCD / SweetSurface / DPU panel read
```

CPU glyph/vector rasterization may legitimately remain in applications or in software contexts. The required flip is the **composition of the target frame and its backdrop passes**, not a claim that every pixel in the system must henceforth be GPU-rasterized.

The exported `CAContext` interface confirms the cross-process model: remote contexts have a `contextId`, image slots, and Mach/fence-port operations ([runtime header](https://github.com/nst/iOS-Runtime-Headers/blob/master/Frameworks/QuartzCore.framework/CAContext.h)). The `CABackdropLayer` interface supplies `groupName`, `scale`, `backdropRect`, `captureOnly`, `allowsInPlaceFiltering`, `enabled`, luma/statistics properties, and filter-bearing `CALayer` behavior ([runtime header](https://github.com/nst/iOS-Runtime-Headers/blob/master/Frameworks/QuartzCore.framework/CABackdropLayer.h)). These headers are navigation aids; the exact 23G90 cache below governs this design.

## 3. Exact 23G90 QuartzCore inventory

Cache: `/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e`, UUID `0f1ee33235db30f38f5fbd4b954138d5`. `dsc_sym.py` maps the addresses below to QuartzCore; its exported-symbol limitation is why the retained full demangled map [qc.syms.dem](../ios26-gpugl-r1/qc.syms.dem) is needed for C++ local methods. Addresses are unslid and are **not** runtime hook authorizations by themselves. A hook must verify UUID, instruction bytes, vtable/slot, PAC behavior, and original-output behavior as `hgltrack`/`hk_accel_once` already do.

### 3.1 Device, CA renderer, command, destination, and present

| Symbol / unslid address | Contract it establishes |
|---|---|
| `_CAMetalContextCreate` `0x184215998`; wait block `0x184215a0c` | Polls `IOAcceleratorES`, then calls `MTLCreateSystemDefaultDevice`; nil skips Metal setup. See [accel-wait/FINDINGS.md](../ios26-phaseb-r1/accel-wait/FINDINGS.md). |
| `CA::OGL::new_metal_context` `0x1841560c0`; `sw_new_context` `0x184105ac4` | Real distinct GPU and software constructors exist. A non-nil device is still not proof that the former was selected. |
| `+[CARenderer rendererWithMTLTexture:options:]` `0x18422960c`; `setDestination:` `0x184229294`; `render` `0x18422864c`; `endFrame` `0x1842285bc` | The exact cache supports an owned offscreen QuartzCore acceptance before backboardd. |
| `MetalContext::create_pipeline_state` `0x183fd2ea0`; `create_fragment_shader` `0x183fef17c`; `compile_shader` `0x1841546b4`; `load_pipeline` `0x18415432c` | QuartzCore compiles/loads its own pipeline variants. The native runtime must support those artifacts and specializations, not just our simple shaders. |
| `start_command_buffer` `0x183f1d674`; `start_render_encoder` `0x183f035b8`; `draw_elements` `0x183f08c6c`; `flush(bool)` `0x183f5a620` | The basic submission/encoder/draw/flush sequence to trace. |
| `set_destination_iosurface` `0x184155204`; `alloc_destination_texture` `0x184154e18`; `create_surface_from_iosurface` `0x184151254` | IOSurface import and destination setup are explicit CA operations. |
| `shared_event_submit` `0x183f4a0b8`; `shared_event_signal_write` `0x183f503c0`; `shared_event_wait_write` `0x183efb4c8`; `add_completed_callback` `0x184150abc` | Completion is event/callback based; CPU return from encoding is insufficient. |
| `IOMFBDisplay::finish_update` `0x183f5631c`; `swap_set_layer` `0x184201614`; `fb_swap_set_layer` `0x183f5474c` | The presentation seam to join to surface ID and DPU read. |
| `SWContext::create_surface_from_iosurface` `0x1841092c8` | Existing `hgltrack` fixes surface lifetime/tracking in the software path. Keep it single-applied; do not stack Inferno's equivalent patch. |

### 3.2 Backdrop, blur, vibrancy, and iOS 26 glass

| Symbol / unslid address | Why it matters |
|---|---|
| `_CARenderBackdropCollect` `0x184101024`; `capture_backdrop` `0x183f2ae04`; `filter_backdrop` `0x183f29a8c` | Backdrop collection/capture/filtering is render-server work, not a screenshot taken in SpringBoard. |
| `prepare_blur_mipmap` `0x183f5e0b0`; `create_variable_blur_mip_surface` `0x18414c4fc` | The GPU path has offscreen mip/pyramid preparation for variable blur. |
| `GaussianBlurFilter::render` `0x1840f66b8`; `VariableBlurFilter::render` `0x1840f6bf0`; `gaussian_expansion_factor` `0x1840f7e0c` | Gaussian and variable blur are distinct filters; capture/damage bounds must expand with the filter. |
| `tile_downsample_surface` `0x183ff6e88`; `tile_simd_blur_surface` `0x183ff7da4`; `bind_gaussian` `0x1841527cc` | Dedicated tiled downsample/blur routes exist alongside generic pipelines. Measure which route the target uses. |
| `render_vibrant_filter` `0x1840fc63c`; `render_vibrant_color_matrix` `0x183f2f3a8`; `calculate_average_luma` `0x18414fa3c` | Vibrancy consumes filtered backdrop/luma information; it is not merely a bright foreground tint. |
| `GlassBackgroundFilter::render` `0x1840f7ed4`; `GlassForegroundFilter::render` `0x1840f9258` | **iOS 26 has specialized glass filters.** Full Liquid Glass acceptance must inventory and execute whichever of these the target material selects. |
| `AverageColorFilter::render` `0x1840fc950`; `update_backdrop_luma` `0x183f503f4` | A reduced-cost average-colour fallback can reuse existing semantics if capture works. |
| `SWContext::blur_surface` `0x184108974`; `SW::gaussian_sampler<true/false>` `0x184114764/0x1841147e8` | Substantial software blur routines exist. The current defect must be isolated to capture, format, filtering, or blending rather than asserted to be “no CPU blur.” |
| `SW::tex_vibrant_color_matrix/dark/light` `0x18410f9f4/0x18410fad0/0x18410fd10` | Software vibrancy also exists. Missing glyphs can follow missing/incorrect backdrop input. |

**DESIGN pass order to verify by tracing, not a claim of complete disassembly:**

1. Collect backdrop groups and render lower/behind content into the parent surface.
2. Capture the required source rectangle into `BackdropBuffer`, expanded for blur/edge bleed and respecting group, scale, protected-content, and clipping semantics.
3. Prepare filter DAG/offscreen surfaces and any blur mip chain.
4. Execute the selected Gaussian/variable/tiled blur, colour/luminance transforms, glass background/foreground operations, and vibrant foreground filtering in their actual serialized order.
5. Composite the transformed backdrop and then sharp foreground content with correct premultiplied-alpha/blend modes and rounded/masked clips.
6. Flush, signal authentic engine completion, hand back caches, then publish the destination IOSurface to IOMFB/DPU. Never let the DPU race the last blur/composite write.

## 4. Staged implementation and acceptance

### C0 — Prerequisites and instrumentation contract

**Needs from agents 6/7/10:**

- Agent 6 publishes one derived `AGXAccelerator`/`IOAcceleratorES` object with separate readiness for compute, basic CA, and glass. A controlled/headless boot may register it for the owned probe, but normal-int3 CA registration remains blocked until C2's required IOSurface fence exists. There must be exactly one Metal-bearing default device. Remove `HK_ACCEL_ONCE=skip` in the proof boot so the normal poll succeeds immediately.
- Agent 7 changes `isHeadless` only for an actually render-capable device and supplies exact completion/cache evidence. The current [HMNativeMetal.m](../../native/metal/runtime/src/HMNativeMetal.m) is explicitly compute-only/headless.
- Agent 10 stages the trusted bundle/compiler before registration, supplies an owned CA test process, and joins logs by `registry R / firmware epoch E / context C / submission S / surface F / present P`.

Add non-mutating observation before adding hooks that change output:

```text
CA: context=MetalContext device=HMNativeMetalDevice registry=R epoch=E context=C
CA: destination surface=F format=BGRA8 size=1125x2511
CA: submit context=C seq=S passes=<names/ids> surface=F
HMGU: done context=C seq=S engine=<authentic> cache=<handback>
CA: present surface=F seq=S present=P
SWEET FB: swap layer=0 surface=F ... present=P
```

Record `create_pipeline_state` variant identity, AIR/metallib hash, compile duration, destination formats, and every unsupported selector. Do not merely suppress `SWContext` messages; software contexts can coexist for legitimate work. `hk_ustack=backboardd,SpringBoard` with `hk_dbg=0x1e1e17` is the later hang-instrumentation template from LIVE-EVIDENCE, not something to add to the pre-launchd firmware rung.

### C1 — Minimum **offscreen** GPU-composited CA frame

**DESIGN, owned process in the controlled/headless boot only:**

1. After agent 7's explicit-registry and system-default loader checks plus exact 32x24 clear/triangle/quad oracle pass, create a plain, uncompressed BGRA8 `MTLTexture` with `ShaderRead | RenderTarget` usage and an owned command queue. `CARenderer` may use Metal's system-default device internally, so the single ready device must already be visible to this owned process; backboardd/SpringBoard remain absent.
2. Create `CARenderer rendererWithMTLTexture:options:` with `kCARendererMetalCommandQueue` set to that queue. Build the layer tree on a worker thread with explicit disabled actions/transactions; do not depend on the main thread's implicit transaction.
3. Use a 256x256 target divided into four opaque colour quadrants, a CPU-generated 32x32 two-colour image placed at a known origin, and one 50%-alpha white rectangle over a known quadrant. Include an 8-pixel guard border initialized to a poison colour.
4. Set renderer bounds/layer, `beginFrameAtTime`, `addUpdateRect` for the full target, `render`, then `endFrame`.
5. On the same queue, encode a blit/synchronize and texture-to-buffer readback, commit, and wait for **actual API and engine completion**. `endFrame` alone is not synchronization. Compare every pixel, all guards, and premultiplied-alpha results exactly. Repeat with changed colours and a zero-update negative control.

**Accept:** exact basic/composited pixels and guards, one real `MetalContext`, matching submit/done, no fallback, no unsupported selector, and no resource released early. This is the smallest **QuartzCore** frame, but it is not yet an on-screen compositor result.

The public prior-art pattern [carenderer-yuv](https://github.com/jrmuizel/carenderer-yuv/blob/main/main.mm) independently shows the same queue option, explicit worker-thread transactions, and post-render blit synchronization/readback. It is a macOS reference, not phone evidence.

### C2 — Minimum **on-screen** GPU-composited frame

1. Enable the normal-int3 CA-facing service only after C1 plus plain, uncompressed IOSurface import/pinning and agent 5's GPU-write-before-CPU/DPU-read fence pass. Keep `isHeadless=NO` only now that presentation exists.
2. Have agent 10 host an owned remote context containing the same deterministic layer tree in backboardd. Keep `hk_flatmat` off and do not use a custom presenter that fights backboardd for AppleCLCD.
3. Require `set_destination_iosurface(F)` → actual draw/flush submission `S` → engine/cache done `S` → `IOMFBDisplay::finish_update`/`swap_set_layer(F)` → `SWEET FB: swap` with the same `F,S,P`. The first correctness route may call `sweet_surface_native_present_begin/end` **after** authentic GPU completion and CPU-copy the finished surface to the existing scanout. That is valid GPU composition but **not** a zero-copy or performance claim; direct DPU scanout needs separate physical-layout/fence proof.
4. Read back the raw BGRA IOSurface after GPU completion and compare exact pixels/guards. Also take `hk shot` and compare the owner-visible result. Calibrate the screenshot's RGB565/channel order against the known software control; MAP explicitly says R/B order is unverified, so screenshot colour alone is not the raw oracle.
5. Repeat 100 presents with alternating colours, then a timeout and stale-completion negative control. No backboardd/SpringBoard crash, stale surface, CPU/DPU read before GPU completion, or ordinary `SWContext` composition of the target is allowed. Add the direct-DPU variant only after its own layout and retirement-fence acceptance.

**Accept:** a known frame reaches the physical panel with exact raw pixels and a screenshot, with the complete ID-correlated GPU-to-DPU chain. **This is the minimal GPU compositor milestone.**

### C3 — Real blurred backdrop, deterministic offscreen then on-screen

1. In the owned `CARenderer` scene, draw large red/green/blue constant regions separated by a one-pixel vertical boundary and a fine-line/high-frequency patch.
2. Add a sibling `CABackdropLayer` over that boundary. Set an explicit `groupName`, `enabled=YES`, `allowsInPlaceFiltering=NO` for the first case, `scale=0.5`, and a `gaussianBlur` filter with a fixed nonzero `inputRadius`. Start without vibrancy or specialized glass filters.
3. Render three controls: backdrop disabled (identity), radius zero (identity), and the chosen radius (blur). Verify far-field pixels remain unchanged, the boundary spreads into the expected two-sided transition, fine detail attenuates, the blur does not wrap at edges, guards remain intact, and source/destination surfaces remain leased until completion. Use a stock-Apple Metal reference for numerical tolerance if available; otherwise use semantic bounds/profile checks rather than inventing byte-exact Gaussian weights.
4. Repeat with in-place filtering, colour matrix/saturation, vibrant colour matrix/dark/light, variable blur, and luma tracking **one feature at a time**. Journal which generic/tiled/mip route each takes.
5. Only after those pass, enable the same effects in backboardd and require the C2 present chain plus a screenshot. Then add the actual `GlassBackgroundFilter`/`GlassForegroundFilter` variants used by the target recipe; unsupported filters fail closed and block CA_GLASS readiness.

**Accept:** the blurred region is derived from the current render-server parent capture, not the previous displayed frame, and real submit/done/present evidence accompanies the expected pixel profile.

### C4 — Owner-visible Liquid Glass / MaterialKit

1. Inventory live MaterialKit recipe/filter/pipeline names for dock, `modules`, and `modulesBackground`, including variable blur, luma, vibrant, and specialized glass filters. Implement every selector/PSO/texture format those paths request; do not approximate them with a different shader and call it full Liquid Glass.
2. Boot with `HK_FLATMAT=0`, the normal accelerator poll, and no Inferno forced-software/CoreImage patches in the native image. Open Control Center over the colourful Home icon grid, close it, and reopen it. Repeat over a different background.
3. Capture **before/after screenshots in both background cases** plus raw surface/pixel receipts. The blurred backdrop must change with the background while sharp foreground controls remain stable; this defeats a static-tint false positive. Check edges, rounded masks, glyph vibrancy, colour/alpha, and update behavior while the underlying content changes.
4. Require zero new backboardd/SpringBoard crashes and the complete C2 ID chain for the glass frame. Exercise repeated open/close, app switching, missing completion, teardown, and idle/power transitions before long-running use.

**Final acceptance:** the owner sees a genuinely blurred Control Center/material backdrop in `hk shot`, objective pixels confirm it is not a flat fill, and the receipt proves that backdrop/filter/composite GPU work completed before the same IOSurface was presented. A pretty screenshot without that chain, or a chain without the pixels, is not acceptance.

## 5. Cheap interim before full Metal

### I0 — Better flat fallback: dynamic average colour, explicitly not glass

Add a separate `HK_FLATMAT=stats` mode; do not change the proven static default silently.

1. Keep the backdrop/capture enabled and request `statisticsType`/luma updates on `MTMaterialLayer`; observe `statisticsValues` or the backdrop-luma delegate. Disable only expensive blur/glass/vibrant filters, then choose the layer's fill from the sampled average/luma and recipe contrast rules.
2. Alternatively, retain CoreMaterial's own Reduce Transparency **average-colour** filter while removing Gaussian/variable/glass filters. This tests whether capture and `AverageColorFilter` work without solving blur.
3. Fall back to the current static recipe colours when statistics never arrive. Bound logging and avoid setters when values have not changed, preserving the existing configure/layout-loop guard.

**Accept:** tiles/glyphs remain readable and tint follows the backdrop when statistics change. **Not acceptance for Liquid Glass or native Metal.** This is the lowest-risk improvement to `hk_flatmat`.

### I1 — Real interim blur by repairing the existing SW renderer

This is the recommended true-blur interim because the functions already exist.

1. Run with `hk_flatmat` off. Observe `capture_backdrop`, `filter_backdrop`, `SWContext::blur_surface`, `GaussianBlurFilter::render`, vibrant render, and both glass filters with entry/return, context, surface pointer, bounds, format, and result. Do not change output in the observation build.
2. First use `CA_PRINT_BACKDROPS=1`. In a separate comparison use `CA_BACKDROP_SCALE=1` and `CA_DISABLE_BACKDROP_CACHE=1` to remove scale/cache variables. `CA_COLOR_BACKDROPS=1` is a separate diagnostic visualization only, never an acceptance screenshot.
3. Branch on evidence:
   - capture absent/null: fix `capture_backdrop`, parent/destination format, surface lifetime, or group selection—not Gaussian arithmetic;
   - capture valid but blur output empty/wrong: inspect `SWContext::blur_surface`, sampler input, row stride, pixel format, and destination bounds;
   - blur valid on an offscreen surface but panel flat: inspect filter application, premultiplied blending, vibrancy, clipping, and present ordering.
4. If a small arithmetic repair is needed, operate on the **current render-server capture**, downsample to 1/4 resolution, run a bounded separable CPU blur (vImage/NEON is a reasonable approximation), then composite with the existing SW path. Preserve premultiplied alpha, clamp edges, retain source/destination through completion, and expand dirty regions by the blur radius.
5. A native-compute-only blur with CPU readback is possible after agent 7 compute works, but it still requires the same capture hook and round trip. It is not a GPU-composited frame and is not simpler than repairing SW unless that repair is blocked.

**Do not** blur `hk_screen` output, the previous presented frame, or `CALayer.render(in:)` from SpringBoard and call it a real backdrop. Those approaches omit remote content or recursively include the glass itself, producing ghosts/feedback. A static wallpaper-only blur may be a visual mockup, but must be labelled as such.

**Accept:** a real blurred backdrop is visible in a screenshot with `MTLCreateSystemDefaultDevice` still nil and an explicit CPU-blur receipt. This can satisfy an interim visual goal only; it remains separate from C2/C4 native acceptance and has no 120 Hz claim.

## 6. Sustained-120 coordination

The FPS lane owns the sustained-120 verdict. Compositing supplies the following constraints and measurements; presentation counts alone remain invalid.

- At 1125x2511 BGRA8, one active-pixel surface is 11,303,100 B (10.78 MiB). At 120 Hz, **each** full-screen read or write stream is 1.356 GB/s (1.263 GiB/s). A simple source read + target write is already 2.713 GB/s before destination reads, blur taps, mip chains, vibrancy, or scanout. The frame interval is 8.33 ms.
- Record per-frame CA collect/prepare/encode time, authentic GPU completion time, blur pass count, submitted/completed/present timestamps, DPU done, missed-vsync reason, and pipeline-cache hit/miss. Report distributions and missed frames, not just average swaps/s. Initial target for design is p99 GPU glass work below 4 ms to leave CPU/present headroom; this is a budget, not a measured result.
- Test cold and warm pipelines separately. QuartzCore has many specialized variants; cold compilation may dominate startup and must never silently fall back to flat. Use a content-addressed persistent cache keyed by shader bytes/specialization/runtime/driver/firmware identity. Prewarm only variants actually proven valid.
- Cache filtered backdrops only while source damage, group, recipe, luma, scale, and filter parameters are unchanged. Expand damage by the blur's actual reach; do not reuse across changing content. Use backdrop scale/dual-Kawase only as a separately evaluated approximation, not as a bit/fidelity-equivalent replacement for Apple's filters.
- On the TBDR GPU, avoid unnecessary full-target load/store and transient round trips; batch compatible passes and keep transient surfaces leased. Production frames need no CPU readback. Readback is for probes only.
- Use explicit capture→blur→vibrancy/composite→present dependencies and keep each IOSurface pinned until both GPU completion and DPU retirement. SimRun's EXTERNAL experience shows that rotating buffers without viewer ownership tears even when present callbacks continue.
- Sustained test: after correctness, animate/open-close glass for at least 30 s with cold-start results reported separately and warm p50/p95/p99 frame/GPU times plus every miss. Any fallback, timeout, stale surface, or incorrect frame invalidates the run even if average FPS is 120.

## 7. Prior art: lessons and boundaries

- **[SimRun render server](https://github.com/unixzii/SimRun/blob/main/docs/render.md) (EXTERNAL):** starts real `CAWindowServer`, hosts remote `CAContext`s, renders through sim Metal into real IOSurfaces, and reaches PNGs. It also documents shader-service startup and framebuffer ownership/tearing. **Reuse:** offscreen-first staging, real CA consumers, explicit presentation ownership. **Do not transplant:** sim/host MTLSim services or fake SimFramebuffer; our backboardd/AppleCLCD already exist.
- **[UniXNU AdrenoMetal](https://github.com/UniXNU/AdrenoMetal) and [NativeBridgeMetalFrontend.mm](https://github.com/UniXNU/AdrenoMetal/blob/main/NativeBridgeMetalFrontend.mm) (EXTERNAL, MIT):** a foreign Metal frontend drives actual CA GPU composition on Adreno, with IOSurfaces/events/fences/pipeline archives and a frame journal. Its [GpuScanoutPresenter.h](https://github.com/UniXNU/AdrenoMetal/blob/main/GpuScanoutPresenter.h) also supplies a fenced completed-frame copy/convert presentation precedent. **Reuse:** expect a broad private Metal selector surface, trace pipeline variants, cache carefully, correlate frames, and allow a fenced CPU-copy first present. **Do not transplant:** Turnip/Vulkan/A740 ABI, Apple-family claims, or its backend. Upstream composition is not our physical proof.
- **[WebKit PlatformCAFiltersCocoa.mm](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/platform/graphics/ca/cocoa/PlatformCAFiltersCocoa.mm) (EXTERNAL):** maps blur to `kCAFilterGaussianBlur`, colour operations to CA filters, and distinguishes backdrop edge normalization/hard edges. **Reuse:** preserve filter ordering and edge semantics. It does not implement QuartzCore's renderer.
- **[Chromium cc architecture](https://github.com/chromium/chromium/blob/main/docs/how_cc_works.md) (EXTERNAL):** ordered render passes/quads, offscreen surfaces for effects, and back-to-front composition. **Reuse:** make backdrop capture/pass dependencies explicit and treat present as a separate stage. It is architectural guidance, not CA ABI.
- **[KWin blur](https://github.com/KDE/kwin/blob/master/src/plugins/blur/blur.cpp) (EXTERNAL, GPL):** downsample/upsample dual-Kawase pyramid, clamp-to-edge, expanded repaint regions, and premultiplied blending. **Reuse as performance/fallback ideas only; do not copy code or claim identical output to Apple's Gaussian/glass.**
- **[Asahi AGX driver notes](https://github.com/AsahiLinux/docs/blob/main/docs/sw/agx-driver-notes.md) and [Road to Vulkan](https://asahilinux.org/2023/03/road-to-vulkan) (EXTERNAL):** explicit in/out sync objects, command completion feedback, and the high cost of splitting tile-based rendering into many tiny passes. **Reuse:** fence every cross-producer dependency and minimize render-pass transitions. **Do not transplant:** AGX firmware/IOCTL/ISA/tile layouts. Asahi is not a CoreAnimation or Apple-Metal compositor implementation and does not make Apple's AGX driver usable on DXT.
- **[Inferno assessment](../../docs/INFERNO.md) (SOURCE/EXTERNAL):** corroborates the SW surface-tracking fix and forces software rendering for emulation. **Reuse:** lifetime fix only, single-applied. **Boundary:** its forced software paths and incomplete-Liquid-Glass mode must not contaminate native acceptance; its patcher is AGPL and no code is imported here.

## 8. Requested live probe (before any native CA publication)

Request one attended **diagnostic-only int3-derived** boot from agent 10, after the firmware lane's independent next boot—not bundled with it:

1. Keep the current software renderer and `hk_flatmat` off. Add read-only observers for `capture_backdrop`, `filter_backdrop`, `SWContext::blur_surface`, `GaussianBlurFilter::render`, `render_vibrant_filter`, `GlassBackgroundFilter::render`, and `GlassForegroundFilter::render`. Log context/surface/bounds/format/result without altering pixels.
2. Set `CA_PRINT_BACKDROPS=1`; open Control Center over Home and capture before/after `hk shot` plus console. Then repeat with `CA_BACKDROP_SCALE=1 CA_DISABLE_BACKDROP_CACHE=1` as a second controlled case.
3. In SpringBoard, log each `MTMaterialLayer` recipe/group/scale/filter and whether `statisticsValues` ever changes. This decides whether I0 dynamic average colour is viable.
4. Report the first failing seam using the I1 decision tree. Do not add a native accelerator, change renderer output, or claim glass from this probe.

**Most valuable result:** whether `capture_backdrop` returns a valid current parent surface and whether `SWContext::blur_surface` is entered for Control Center. That single distinction chooses between capture/lifetime work and blur/filter work.

## 9. Needs from other agents

- **Agent 6 (IOAccel):** staged readiness bits (`compute`, `CA_BASIC`, `CA_GLASS`), no normal-int3 publication before C1+fence, normal non-skipped poll, same registry/epoch in every line. Do not expose `isHeadless=YES` to CA.
- **Agent 7 (Metal):** per [METAL.md](METAL.md), the exact basic and expanded CA profiles: one default device; queues; plain BGRA8 with no unsupported compression plus measured R8/RGBA16F formats; texture upload/authorized IOSurface import; private/shared/memoryless resources as requested; vertex/fragment PSOs and QuartzCore AIR/metallib specializations; render/blit encoders; alpha/blend/clip; offscreen/mip surfaces; shared events; authentic completion/cache; readback; persistent variant cache. Fail unsupported selectors explicitly and journal them. `endFrame`/`commit` must not be reported as engine completion.
- **Agents 4/5 (submission/fences):** join `S` to actual engine completion/cache and a present lease that survives until DPU retirement; supply timeout/stale-event negative controls.
- **Agent 10 (integration):** controlled/headless `CARenderer` harness followed by the normal-int3 remote-context harness, raw BGRA surface readback plus `hk shot`, ID-correlated evidence, `hk_flatmat` off for all native tests, and the diagnostic probe above. The first present may use the fenced CPU-copy route from METAL.md; label it and make no zero-copy/FPS claim. Keep Inferno/software-only patches out of the native image and run Android return-check after every physical boot.
- **FPS lane:** define final sustained-120 soak criteria and use the per-pass/timing/missed-vsync records above; do not infer FPS from `SWEET FB` counts or panel mode.

## 10. Stop rules / risks

| Risk | Stop / mitigation |
|---|---|
| Compute-only or name-only device reaches CA | Stop publication. Owned compute and C1/C2 must pass first; no “see what backboardd requests” experiment on the production UI process. |
| A non-nil device or changed log is called rendering | Require C1 exact pixels or C2 exact raw surface + screenshot + submit/done/present chain. |
| Full Liquid Glass reduced to one Gaussian | Inventory and implement the actual variable/vibrant/glass filter path; block `CA_GLASS` on any unimplemented requested variant. |
| Screenshot blur used as backdrop capture | Reject recursive/stale design. Capture the current render-server parent before the glass draws. |
| Pipeline returns but pixels are stale/wrong | Join engine completion and cache handback; read raw surface; never promote command-buffer status alone. |
| DPU reads while GPU writes or surface is reused | Pin through GPU completion and DPU retirement; explicit shared-event/fence ordering and negative controls. |
| Filter/cache produces ghosts or double blur | Key on source damage and all recipe parameters; expand dirty regions; disable cache for the diagnostic control. |
| Cold shader compilation stalls or falls back | Fail explicitly, prewarm validated variants, separate cold correctness from warm FPS. |
| RGB565/channel order hides errors | Raw BGRA readback is authoritative; calibrate `hk shot` against a known software frame. |
| Fallback contaminates native result | `hk_flatmat`, forced CoreImage software, and Inferno patches off in native runs; CPU fallback evidence is reported separately. |
| 120 Hz claim hides missed frames | Use completed/presented timestamps, p99 and misses; average swap counts are not sustained FPS. |
| Physical/device safety | Coordinator-only temporary `fastboot boot`; no partition/firmware/slot changes; preserve Android and run return-check after every boot. |
