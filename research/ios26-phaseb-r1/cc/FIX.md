# Control Center tiles black/transparent: backdrop materials on the CPU renderer (2026-11-03, HOST fix, not booted)

Labels: **PHYSICAL** = owner observation on the phone (r10-perf, int1), **S** = read in the 23G90 dyld cache
(`/data/hackios-qemu/dsc-r6`) or in the root's CoreMaterial bundle (Mac's read-only mount `/private/tmp/hk-live-root`),
**HOST** = build/host test, **I** = inference, untested. Nothing here touched the phone.

Input (PHYSICAL, r10-perf and int1): pulling down Control Center shows black or see-through module tiles. Only a few glyphs
draw (the "+", power and the battery %). The perf-r1 Reduce Transparency/Motion plist (overlay [48]) made no visible difference.

## 1. Where iOS 26 reads Reduce Transparency: the perf-r1 plist is in the right place (S)

- `_AXSEnhanceBackgroundContrastEnabled` (libAccessibility 0x1868fb230) first asks an override singleton (`[X shared]
  reduceTransparency`, nil when there is no override). It then calls `_AXSGetCachedPreference` with key
  **`EnhancedBackgroundContrastEnabled`**, notify cache `com.apple.accessibility.cache.enhance.background.contrast` and change
  notification `com.apple.accessibility.enhance.background.contrast.status`.
- The value comes from domain **`com.apple.Accessibility`** (0x1868fc414). For euid ≠ 0 it uses `CFPreferencesCopyAppValue`
  (0x1868fc470), which reads `/var/mobile/Library/Preferences/com.apple.Accessibility.plist` for the mobile user.
  For root it uses `-[… accessibilityPreferenceAsMobile:domain:]` (0x1868fc5d8).
- So overlay [48] (0600 mobile:mobile, `EnhancedBackgroundContrastEnabled`, `ReduceMotionEnabled`, …) has the right key, domain
  and path. The same directory's `com.apple.springboard.plist` is read on the phone (battery % shows, PHYSICAL). There is no
  separate backboardd preference and no UIKit-domain key.
  **I:** Reduce Transparency was very likely on in r10/int1. It did not help, for the reason in §2.

## 2. Why the tiles are black: every CC material is a backdrop, and Reduce Transparency keeps the backdrop (S + I)

- The CC module background is `-[CCUIControlCenterMaterialView _moduleBackgroundMaterialView]` → `_darkMaterialView` →
  MTMaterialView with recipe `_controlCenterModulesRecipe` = 8 (`modules`) and group `ControlCenterModuleBackground`
  (ControlCenterUIKit 0x1d4757af8/0x1d4757b44/0x1d4757d68).
- MTMaterialView's layer is CoreMaterial's **`MTMaterialLayer` → CABackdropLayer → CALayer** (class chain read with
  `tools/objccls.py` at 0x1ecfabd20).
- The root's `CoreMaterial.framework/modules.materialrecipe` has **only a colour matrix** applied to the captured backdrop. It has
  no tint and no fill. `modulesBackground.materialrecipe` is blur 25, luminance and saturation, again with no tint. So **a tile's
  pixels are the backdrop capture and nothing else.**
- Reduce Transparency in CoreMaterial: `"%{public}@: Reduced transparency enabled, so replacing blur with average color"`
  (CoreMaterial cstring 0x1c2238651). The backdrop stays and only the blur becomes an average-colour filter, which is also a
  backdrop filter. The `modules` recipe has no blur, so for the tiles **nothing changes at all**. That explains the r10/int1 result.
- The glyph pattern fits. `moduleFill.visualstyleset` styles module glyphs (`secondary` = `moduleItemOff`, `highlight`) with
  `vibrantColorMatrix` and **`inputBackdropAware: true`**, and these are the glyphs that are missing. The ones that draw (status bar
  battery %, the CC header buttons) are plain-tinted.
- QuartzCore has a CPU renderer ("SW renderer invalid destination format …", "%d by %d image is too large for software
  renderer"), but no env switch that skips or flattens backdrops. The 288 `CA_*` keys include only debug/print/colour switches
  for backdrops: `CA_PRINT_BACKDROPS`, `CA_COLOR_BACKDROPS`, `CA_DUMP_BACKDROPS`, `CA_BACKDROP_SCALE`,
  `CA_DISABLE_BACKDROP_CACHE`. The last is already in the overlay's inactive groups 14/15.
- **I (not proven in the renderer):** on this CPU path a backdrop capture renders as nothing, so recipe-only materials come out
  transparent (or black over the dimmed CC background). The renderer's backdrop code is stripped C++ and was not read through.
  The proof is the boot below: if flat fills show, the backdrop was the cause.

## 3. Fix: `hk_flatmat.dylib` in SpringBoard (HOST built and tested)

`src/hk_flatmat.c` (a97d1f72…). It is injected through the existing SpringBoard hk_env rule (CC runs in SpringBoard) and gated by
`HK_FLATMAT=1` and `getprogname()=="SpringBoard"`. Every original IMP runs first.

1. After `-[MTMaterialLayer layoutSublayers]` and `-_configureIfNecessaryWithSettingsInterpolator:`, it does three things:
   - switches the backdrop off (`setEnabled:NO`);
   - switches each of the layer's CAFilters off (CAFilter has its own `enabled`). The filters stay in place, so MaterialKit's
     `filters.<name>.<key>` key paths keep resolving;
   - gives the layer a plain `backgroundColor` chosen by recipe name: `*ackground*` black 0.55 (dims Home behind CC), `modules*`
     grey 0.22/0.92 (tiles), `dock*` 0.25/0.60, `*Dark*` 0.16/0.90, platters/platform 0.94/0.90, otherwise 0.5/0.5. Capture-only
     layers get no colour.

   Setters run only when the value would change. A no-op setter would still notify MTMaterialLayer and start a
   configure/layout loop.
2. `-[CALayer setFilters:]` and `-setCompositingFilter:` pass every value through unchanged, but any CAFilter whose type starts
   with `vibrant` is switched off first. The glyph then draws with its tint colour (white for `moduleItemOff`).
3. Console lines (in the ramdump): `HKFLAT: SpringBoard[pid] hooks layout=1 configure=1 filters=1 compositing=1`, then
   `HKFLAT: flat N recipe=NAME capture=C filters=K` (first 32), and `HKFLAT: t=S flattened=N vibrant_off=N` every 30 s while
   either count changes (≤ 40 lines).

This applies to every MaterialKit material in SpringBoard (dock, folders, notifications, CC). They all become flat fills,
which is what Reduce Transparency should look like here. UIKit `UIVisualEffectView` backdrops are not touched.

Build (`tools/build_flatmat.sh`, Mac, `receipts/flatmat/`):
- **Host test** (macOS arm64, a fake MTMaterialLayer registered on the real CABackdropLayer, real CAFilter):
  `host-run.txt` **13/13 ok, RESULT PASS**. It checks that the original layout/configure ran, the tile backdrop and its filter
  are off but kept, the tile is grey 0.22/0.92 and the background 0.55, the second pass calls no setter and sends no change
  notification (no loop), `filters.colorMatrix` still resolves, capture-only gets no colour, vibrantColorMatrix/vibrantDark are
  off while gaussianBlur and string `plusD` are untouched. Gate off: `host-off.txt` **PASS, silent, IMPs untouched.**
- **Device dylib:** arm64e, iPhoneOS 27.1 SDK, min iOS 26.0, `pacstrip --sign` → "no PAC code", `codesign --verify --strict` clean.
  It links only libobjc and libSystem (`otool-L.txt`). **`out/hk_flatmat.dylib` 66f49f7bf4c456b1f937acae9cfdd281e3ce0b59cb01ff78ae05991f6f0f55c5**
  (69,312 B). Not run on iOS yet. It uses one `_Thread_local` (TLV) for the re-entry guard.

## 4. Overlay `cc1-r1.ovl` (`tools/cc_overlay.py`, `receipts/overlay.json`)

- Base **int1-r1** c440b6ea… (52 records, pinned), dylib hash pinned. Codec mkoverlay pack/fnv1a/env_ok. Postconditions are
  checked with the second walker (`restore_cloudd.decode`).
- Output **34b50aab9aab88335a0618b9069ba825db27b082fa635cfab35c915155d41e35** (731,104 B, 53 records). 51 records are byte-identical.
  - [39] hk_env: the SpringBoard rule only, `DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib` **`:/private/var/hk/hk_flatmat.dylib`**
    and **`;HK_FLATMAT=1`**. 868 B with NUL (≤ 1024), every other rule identical.
  - Appended [52] `/private/var/hk/hk_flatmat.dylib`, group 29, 0755 root:root, active under 0xA0080081.
  - [48] Accessibility plist is kept as it is (harmless; §1).
- `pwr_consumer.c int1-r1 → cc1-r1` (`receipts/consumer.txt`) fails on its own fixed `env == env` expectation. That is expected:
  the hk_env change is the point of this overlay, and the consumer is informational here. The release headers equal the pinned copies.

## 5. Image `a7-ios-system-cc1` (Mac `tools/mkimg_cc1.sh` = `int/tools/mkimg_int1.sh` with only N/OV/OVS/receipts changed)

- Same kernel (`kernel.int1` 0d0c99b2…), the same tool (`image_tool_int1.py` 728bdd21…) and the same phone-args and drop-diag as int1.
- **boot.img 0f29e113159585cc79a15670ff73bc6a1e25648420a9b3796022a1f2705ce261**, payload cd6633eb…, margin 39,860,000 B.
  `check` OK with image_tool_int1.py and the shared tool (Mac), and image_tool_int1.py on m1box (`research/images/a7-ios-system-cc1`, copied).
- **Cmdline vs int1: identical** (1018 B, 56 tokens). The manifest differs only in the overlay (661,680 → 731,104 B, kernel_end +0x10000,
  ADT/boot-args positions), payload/image/AVB size, and per-build ids (`receipts/manifest-diff.txt`).

## 6. Attended test (owner; bare `fastboot boot`, then the return check)

```sh
tools/bootios research/images/a7-ios-system-cc1/boot.img a7-ios-system-cc1 \
  --mach research/ios26-phaseb-r1/int/build/kernel.int1.unstripped --wait 1080
# then: Android up, research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-cc1-after-boot
```

1. Lock screen, then swipe up to Home (as int1). **Look at the dock and at Home**: say whether the dock is a flat grey band.
2. Swipe down from the top-right for **Control Center**. Say whether the tiles are now grey rounded squares on a dimmed
   background, and whether the Wi-Fi/Bluetooth/airplane/torch/timer glyphs and the brightness/volume slider glyphs show.
   Close it, open it once more.
3. Tap Settings, scroll once, go Home (a check that SpringBoard is still healthy).
4. Optional: pull down a notification/lock-screen platter if one exists.

Pass = tiles visible as solid grey (owner). Partial = the tiles show but the module glyphs are still missing; then the vibrancy
switch-off did not reach them (see read-out). Fail/stop = SpringBoard crash loop, Home lost, or a black screen where int1 had
Home. Rollback: deadline (900 s) or PSCI reset to fastboot, then `return-check.sh`. int1 is the identical line without the dylib.
Nothing is written (root read only, /private/var in RAM).

### Read-out (ramdump `kernel.log`, first copy of the boot)

| Line | Meaning |
| --- | --- |
| `HKFLAT: SpringBoard[N] hooks layout=1 configure=1 filters=1 compositing=1` | loaded and all four hooks in. `layout=0`/`configure=0`: that selector is not defined on MTMaterialLayer in this build. `MTMaterialLayer not found`: the class never appeared (20 s retry) |
| `HKFLAT: flat N recipe=modules …` / `recipe=modulesBackground …` when CC opens | the CC materials were flattened. If tiles are still black with these lines, the CPU path does not even draw a disabled backdrop layer's background. Next: put the fill on a plain sublayer of the MTMaterialView's superview |
| `vibrant_off=N` grows when CC opens | glyph filters switched off. Glyphs still missing with N > 0: they are not vibrancy-only (check CAPackage glyph states) |
| no `HKFLAT:` at all | dylib not loaded: check `hk_env: SpringBoard gets …` and that hkbattery's `HKBATT:` lines still appear |
| SpringBoard `exec` count > 1 | crash: compare with int1 (the same line without the dylib) |

## Files

- `FIX.md` (this file).
- `src/hk_flatmat.c`, `tests/test_flatmat.m`.
- `tools/build_flatmat.sh` (Mac), `tools/cc_overlay.py`, `tools/mkimg_cc1.sh` (Mac).
- Reading aids: `tools/ccsym.py` (images/symbols/strings/adrp xrefs in the cache) and `tools/objccls.py` (class chain and methods).
- `receipts/`: `flatmat/` (host test, pacstrip, codesign, otool, nm, SHA256SUMS), `overlay.json`, `inputs-verify.txt`,
  `release-headers.txt`, `consumer.txt`, `image_tool.sha256`, `image-build.txt`, `image-check.txt`, `manifest-diff.txt`, `SHA256SUMS`.
- Derived, not for git: `out/hk_flatmat.dylib`, `overlays/cc1-r1.ovl`, `research/images/a7-ios-system-cc1/` (Mac and m1box).

## Commit request (coordination; nothing staged here)

Force-add `research/ios26-phaseb-r1/cc/FIX.md`, `cc/src/*`, `cc/tests/*`, `cc/tools/*`, `cc/receipts/**`. Not `cc/out/` or `cc/overlays/`.
Message: "Control Center: CC materials are backdrops (Reduce Transparency keeps them); hk_flatmat in SpringBoard flattens them;
overlay cc1-r1 34b50aab, a7-ios-system-cc1 0f29e113 built, not booted".

Proposed NOTES line: **Control Center (2026-11-03, HOST, not booted):** the tiles are MTMaterialLayer backdrops whose recipe is only a
colour matrix, and Reduce Transparency keeps the backdrop. `a7-ios-system-cc1` (0f29e113…) = int1 + `hk_flatmat.dylib` in SpringBoard
(flat fills, vibrancy off). `research/ios26-phaseb-r1/cc/FIX.md`.
