# Tegu compositor branch: read-only reuse analysis for our CA/Metal milestone

Research date: 2026-11-04. Scope: read-only inspection of the private
`dgigantino/ios-tegu` repository (authenticated `gh` API), branch
`tegu-compositor-0157-r1` (head `da71b734`, 2026-10-21; pushed 2026-11-02), plus
the nine `tegu-compositor-*` branches, `NOTES.md`, `TEGU.md`, and patches
`0137`-`0158`. **No source was copied** (repository licence: none; see
`docs/NATIVE-METAL-UPSTREAM.md` policy). No build, guest run, phone operation
or performance measurement was performed here. The phone was busy with our own
queue 2 the whole time.

## What tegu is (and is not)

Tegu is a Pixel 9a (**Tensor G4, Mali GPU**) bring-up of **iOS 16** with a
custom kernel-side GPU driver: `iokit/Kernel/arm/TeguGPU.cpp` behind a
17-selector `IOUserClient`, plus `SweetSurface.cpp` IOSurface extensions.
Its GPU/compiler path is AIR -> SPIR-V -> **Mali** code via metal2vulkan —
none of which can drive our PowerVR DXT. Snapshots and the 2026-11-02 audit
already said this; the compositor branch does not change it.

Their own state, in their words (TEGU.md): "Native Metal draws, IOSurface
rendering and a small framebuffer presentation test have passed on the phone.
**System UI acceleration remains unfinished.**" Backboardd selected the
driver but crashed creating the `downsample_8_frag_lph` pipeline; no accepted
UI pass/draw. So tegu is *not* a working CA integration to copy — it is a
**partial one whose seams are mapped**.

## What they proved works (the transferable facts)

### 1. The publication seam: what Metal/CA actually queries

`0149` shows the capability advertisement their Metal framework consumed:
`scalarOutput[1]` bit-flags — compositor v6/v7, `COMPOSITOR_LOAD`,
`COMPOSITOR_IOSURFACE`, target-dimensions, RGBA16F source, load-action —
gated behind `renderReady`. Selector 17 imports a compositor surface with a
versioned target (metadataVersion 0 = legacy sel-13, 1 = compositor target),
`importCompositorSurface` validating id, import quota
(`nextImportedTarget > tgImportedTargetLast -> NoResources`), surface lookup
and per-plane layout (`width, bytesPerRow, offset, pixelFormat, allocSize,
planeCount, ...` — `0147`). `TEGU_GPU_CAP_*` bits are what the framework reads
to decide "can this device composite".

**For us:** our CA diagnostic (2026-11-04) answered the iOS 26 side — no
`AGXAccelerator` in the IORegistry, so CA picks SWContext. Tegu's client is
behavioural evidence for what a *published* device must answer: capability
bits gated on real readiness, an import selector with quota + strict per-field
validation, and versioned metadata. Our rung-11+ AGXAccelerator publication
should mirror that shape (our own code, verified against our real firmware).

### 2. The real first pipelines CA builds — plan for them, not triangles

Their r33 backboardd capture: CA's first pipelines are QuartzCore's actual AIR
shaders — `path_blit_vert_lph` + `attachment_clear_frag_lph` (descriptor slots
0/1 BGRA8, masks 0/15, blending off, AxisAlignedRect + matrix constbuffers, no
vertex attributes), then `downsample_8_frag_lph`. **The crash was on the third
one** — the first two had compiled.

**For us:** after rung 10 lands, the first real shader milestones should be
*these CA shaders*, not synthetic geometry: they are small, known-shaped, and
they are literally what backboardd builds first. And accept the lesson of
their failure: a milestone that proves one pipeline imports is not CA
integration — acceptance must enumerate the set CA actually builds (blit,
attachment-clear, downsample) or it will look green while backboardd loops.

### 3. MIG wraps large inputs — copy before parse (`0146`)

Large `IOConnectCallMethod` structure inputs arrive as an
`IOMemoryDescriptor`, not a pointer. Their import path copies the bytes into
kernel memory with `prepare`/`readBytes`/`complete` under exact min/max length
bounds before any parsing, and refuses anything but the two package imports.
**This is a generic IOKit fact** we will hit the moment our Metal user-client
accepts real pipeline packages bigger than the in-band buffer — our design
should assume descriptor-backed inputs from day one (bounds-checked copy,
RAII finish, no caller pointers surviving the call).

### 4. Large GPU surfaces need scatter allocation (`0157`, `0156`)

Their full-screen compositor target could not be one contiguous
`GPUShared` allocation: `0157` backs it with individually masked **16 KiB child
descriptors** plus an `IOMulti` aggregate, with per-child quota charge,
page-granularity checks (`bytes & (page_size-1)` refused) and a wired max.
`0156`/`0148` add import candidates, quotas and refusal tracing (`0158`).

**For us:** directly adjacent to our rung-10 memory-context work and to the
aoc5 carve panic (device-class mapping + zeroing): the pattern of
page-granular, per-child-validated, quota-charged GPU memory is how a
compositor-sized surface survives contact with a real driver.

### 5. Presentation acceptance: readback + release-after-match (`0142`)

Their panel proof is worth copying as *test design*: present -> PIXELS_MATCH
against a held framebuffer -> swap lifecycle with surfaces **retained until
the panel copy completes** -> release after match. "Offscreen PASS is not
panel proof" is their explicit rule; our R10.md already agrees ("It does not
prove that an engine translated through the tables"). Adopt the same wording
discipline at the CA milestone: tile/panel readback before "compositing works".

## What does NOT transfer

- Any Mali code: PSO formats, `native_package_v7`/`render_pipeline_v7` stages,
  tile allocators, l2 entries, the AIR->SPIR-V->Mali compiler. Our path is the
  real PowerVR firmware + our own CCB stream (rungs 8-9 executed on the phone
  2026-11-04; rung 10 built and queued — see NOTES.md).
- Their iOS 16 userland expectations: our iOS 26 CA answered differently
  (`AGXAccelerator` match, `MTLCreateSystemDefaultDevice` — HKCA diagnostic).
- Their `SweetSurface.cpp` patches: our tree already has its own newer
  implementation (the 2026-11-02 audit's section 2 stands).
- Licence: none. **Facts and design patterns only; no source into tracked
  code.** The existing per-file-MIT ASTC decoder exception from the 202-11-02
  audit is unchanged by this branch.

## Concrete next actions for our lanes

1. **GPU lane (after rung 10):** name the post-rung-10 milestone "CA's real
   first pipelines": import `path_blit_vert_lph` +
   `attachment_clear_frag_lph` (the shapes are documented above from their
   capture) through our rung-10 memory context, then downsample as the third.
   Acceptance = the *set* CA builds, with per-pipeline refusal handling —
   not one synthetic shader.
2. **AGXAccelerator publication design (rung 11+):** capability bits gated on
   real firmware readiness, an import selector with quota and per-field
   validation, versioned target metadata — all in our own DXT code, verified
   against our HKCA probes.
3. **User-client ABI:** assume descriptor-backed large inputs (MIG) from the
   first draft; bounds-checked copy + RAII complete before parse.
4. **Test design:** their present -> readback -> release-after-match panel
   acceptance becomes our CA-milestone acceptance template.

None of the above imports tegu source. This is an evidence note for our own
implementation decisions.

## Provenance

- Repository: `dgigantino/ios-tegu` (private), read via authenticated `gh`.
- Branch: `tegu-compositor-0157-r1` at `da71b734` (also 0133/0141/0146/0149/
  0151/0154-r1/r2/0155 branches exist; 0157-r1 is the newest).
- Files read: `README.md`, `NOTES.md` (2026-10-21 sections), `TEGU.md`,
  `xnu/patches/0137,0142,0146,0147,0148,0149,0156,0157,0158`, `tools/` listing.
- Licence: none found (repo-level LICENSE 404; `github_license_hint: null`).
  `docs/NATIVE-METAL-UPSTREAM.md` policy applies: read for facts, copy nothing.
- Local snapshots from the 202-11-02 refresh remain at
  `research/ios26-metal-native-20261102/upstream/snapshots/dgigantino__ios-tegu/`.