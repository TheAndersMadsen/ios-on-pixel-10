# Tegu and the same-generation XNU base

Audit date: 2026-11-02. Research only: no source import, build, guest run,
phone operation or performance measurement was performed.

## Verdict

Tegu already supplied much of our XNU 12377 compatibility layer. Re-importing
its whole series would mostly repeat completed work and introduce Tensor G4
hardware and Mali dependencies. The best additional code candidate found is
a small ASTC decoder with an explicit permissive file header. Its larger
Metal implementation is useful as a source of behavioural cases, rather than
an executable DXT driver.

The public `dgigantino/ios-tegu` page, repository API and raw pinned README
each returned HTTP 404 during this audit. This does not establish whether it
was deleted, renamed or made private. No assertion about its newest upstream
commit is possible from those responses. Findings below use the local clean
snapshot at `d807098535581ce6ed958bd3b1afd9e33f8d10f5` and identify that limit.

The public Bergamota `ios26` branch was independently verified through GitHub
at `3ec24cae2d5126a4f5211853a3532c360a3bdc04`. Its repository metadata reported
no licence and `LICENSE` returned 404. Two exact patch files were also read
from the pinned raw source. A subsequent tree request hit the unauthenticated
GitHub API rate limit; no bulk fetch was attempted.

## 1. Compact ASTC LDR decoder: concrete code candidate

- Source: Tegu snapshot above,
  [astc_ldr_decode.inc](https://github.com/dgigantino/ios-tegu/blob/d807098535581ce6ed958bd3b1afd9e33f8d10f5/tools/tegu/metal/astc_ldr_decode.inc)
  (upstream URL unavailable during audit; exact file inspected locally).
- Local source: `research/upstream/ios-tegu-gh-20261101/tools/tegu/metal/astc_ldr_decode.inc`.
- Entry points: `tegu_astc_block` and `tegu_astc_decode_bgra8`; 337 lines.
- Licence: this individual file carries the MIT permission and warranty text,
  with Philip Taylor and AMD copyright notices, and identifies its Mesa ASTC
  decoder origin. This is a useful exception to the missing repository licence;
  preserve the complete header and review any separately imported wrappers.
- Capability: CPU decode of 2D LDR ASTC into BGRA8, block parsing, endpoint and
  weight reconstruction, edge clipping, padded output rows and repeated-block
  reuse. It does not supply HDR ASTC, a Metal device, or GPU execution.
- Current overlap: targeted searches of `ios26-metaldrv-r1/src`, the native
  Metal source and AIR frontend found no ASTC decoder or `tegu_astc_*` entry.
  This is a source search result, not proof that every runtime path lacks one.
- Integration seam: a compressed-texture staging/upload boundary in our
  eventual Metal texture implementation; decode once into owned BGRA8 backing,
  then use the existing resource upload and lifetime contract.
- First host proof: an owned bounded wrapper validates block dimensions,
  source/destination strides, complete spans and overflow before calling it.
  Compare all 14 standard 2D footprints with the original Mesa reference,
  including odd dimensions, padding, illegal blocks and guard bytes.
- Tegu also has `astc_ldr_decode_host_test.cpp`; it exercises random blocks
  and a padded 157×154 whole-level case. That test has no explicit licence
  header, so recreate those test categories or obtain permission before copying
  its source. Its assertions were read, not rerun here.
- Labour saved: avoids writing an ASTC bitstream/endpoint/weight decoder.
  It would still require our wrapper, tests and texture plumbing.
- Priority: medium, high confidence in the available implementation and file
  header. Promote only after a real asset/texture request requires ASTC.
  No evidence links unsupported ASTC to today's missing Settings logos.

## 2. IOSurface metadata: already implemented locally

- Tegu source:
  [0433 surface values hunks](https://github.com/dgigantino/ios-tegu/blob/d807098535581ce6ed958bd3b1afd9e33f8d10f5/patches/tegu-ios26/0433-tegu-hotfix-destinations-surface-diag.patch).
- Relevant contract: selectors 9/10/11, value generation at state-page offset
  `0x20`, serialized size at `0x28`, and the 12-byte request/reply header.
- Local counterpart: `research/ios26-release-r1/work/xnu/iokit/Kernel/arm/SweetSurface.cpp`,
  `IOSurfaceRootUserClient::values`, `sweet_surface_values_publish`, and
  `sweet_surface_values_serialize`; `SweetSurface.h` contains the dictionary.
- Our code already handles array-wrapped set requests, key-based copy/remove,
  release publication of generation, output sizing and rollback on serialization
  failure. Tegu's older mixed patch is not a replacement for this newer path.
- Its original `0433` patch had the values switch disabled; `0434` enables it.
  Seeing the old patch on the exclusion list does not establish a present gap.
- Licence: no new licence found on these additions. Existing Apple-derived
  file notices do not automatically grant rights to every third-party addition.
- Smallest useful action: retain an independent ABI regression for a set,
  cross-client lookup/copy, undersized output retry, removal and generation
  publication, against the exact local implementation.
- Priority: no new import. High confidence in overlap from actual functions.
  Savings come from avoiding duplicated IOSurface implementation work.

## 3. Default-surface alignment fix: conditional reference

- Tegu source:
  [0434, AppleCLCD::defaultSurface](https://github.com/dgigantino/ios-tegu/blob/d807098535581ce6ed958bd3b1afd9e33f8d10f5/patches/tegu-ios26/0434-tegu-gpu-kernel-driver-update.patch).
- It returns an ordinary aligned render surface when the logical and panel
  dimensions match but the physical framebuffer row is not 64-byte aligned.
  Its comment records repeated CPU shadow copies for a 1080-pixel-wide panel
  whose 4320-byte row could not be imported by its Mali driver.
- Current overlap: our `kSweetFBGetLayerDefaultSurface` still returns `fSurface`.
  However, our current 1280-pixel BGRA panel row is 5120 bytes before any extra
  padding, already divisible by 64; the current 1125×2511 logical canvas also
  differs from the physical panel. Tegu's stated trigger does not follow here.
- Missing dependencies: native GPU import eligibility, exact physical stride,
  ownership until scanout completion and a measured shadow-copy path.
  Its Mali physical-window/S2MPU policy is not portable to DXT.
- First proof: record whether the actual requested default surface is imported
  or shadowed, its row stride and its logical size; build an owned geometry
  decision test before changing the selector return.
- Licence: reference only for the unlicensed Tegu additions.
- Priority: low now; medium once native Metal uses CoreAnimation surfaces.
  Confidence high that a blind import would not establish a current speedup.

## 4. Same-generation ABI fixes: baseline, not new acceleration

The public Bergamota branch provides an independently accessible cross-check:

- [0135 dyld pager arm64e handling](https://github.com/ry-diffusion/Bergamota/blob/3ec24cae2d5126a4f5211853a3532c360a3bdc04/xnu/patches-12377/0135-ios18-dyld-pager-arm64e-nopac.patch)
  exposes the non-PAC pager path. Tegu's composition script maps it to `0302`.
- [0157 IOSurface limits v2](https://github.com/ry-diffusion/Bergamota/blob/3ec24cae2d5126a4f5211853a3532c360a3bdc04/xnu/patches-12377/0157-ios18-iosurface-limits-v2.patch)
  changes the limits reply from `0x18` to `0x28` bytes and publishes its client
  version. Tegu maps it to `0317`; it is already in our base applied series.
- Tegu `0418` adds authenticated shared-cache slide handling; our actual
  `vm_shared_region_slide_page_v3/v5` contain the corresponding decoding.
- Tegu `0420/0421` supply the iOS 26 digitizer and child queue wire conversion;
  our release contains `hid/tegu_hid_wire.h` and the existing touch path.

Its two small host test scripts are valuable test designs: extracting the
actual shared-cache slide function bodies, and checking the actual HID wire
converter with hostile lengths and output guard bytes. Those are already
relevant to our code, but this audit did not compile or execute them.

Licence: distinguish Apple's source notices from authorship of new patch
material. Neither repository-level permission nor an explicit header was
found for these new test scripts. Record provenance and obtain permission
before copying new code. Priority: existing regression coverage, high confidence.

## 5. Metal behavioural test corpus: reference, not a DXT backend

Tegu's `tools/tegu/metal/` contains focused frontend cases for indexed resource
lifetime, zero-count draws, viewports, texture layout versus backing stride,
attachment clears, asynchronous completion and IOSurface ownership.
[CODE_ONLY_RENDER_FIXES.md](https://github.com/dgigantino/ios-tegu/blob/d807098535581ce6ed958bd3b1afd9e33f8d10f5/tools/tegu/metal/CODE_ONLY_RENDER_FIXES.md)
explains the before/after cases and explicitly separates host checks from
uninstalled device candidates. These are useful requirements for our API layer.

`air_bridge.rs` imports the `metal2vulkan` crate. The renderer also depends on
Mali compiler/command formats, AFBC/tiler state and Tegu kernel selectors.
Consequently a large source copy would not provide our DXT ISA emitter,
PDS/CDM streams, GPU VM or completion path. Some compiler infrastructure also
comes with separate upstream licence obligations. The current non-Mesa native
GPU decision is preserved.

First useful task: recreate three implementation-independent Metal frontend
cases in our own harness: deferred index-buffer mutation, zero-count draw
preserving an earlier clear, and padded texture upload with odd widths.
Use generated owned inputs. Gate unsupported functionality explicitly.
Priority: medium after first native compute; high confidence in the test value,
low confidence in copying its driver as a labour-saving shortcut.

## Concrete next actions

1. Put an ASTC decoder adapter on the native Metal texture backlog, with the
   bounded interface and differential acceptance above. Do not present it as
   a diagnosed icon fix or put it in the boot path yet.
2. Add a provenance-aware baseline checklist linking the already present
   pager, IOSurface and HID contracts to current local tests. Avoid reapplying
   Tegu's mixed hardware/GPU patches to recover a generic hunk.
3. Borrow behavioural requirements from the Metal corpus in our own tests;
   keep DXT hardware integration with the current native owners.

No code candidate in this report has been imported, build-verified or deployed.
The public availability failure and licence boundaries remain explicit limits.
