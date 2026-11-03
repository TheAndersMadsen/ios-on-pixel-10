# backboardd SIGSEGV in CoreBrightness (phone only): cause and fix (2026-11-03, HOST analysis)

Labels: **observed** = read in a log, a source tree or the dyld cache; **host** = built or run on m1box; **inference** = not
tested. No QEMU run and no device access in this work. The phone logs used are already local.

## Answer

Display init in CoreBrightness, `__TEXT+0x164c1c`, wraps the matched `backlight-control` service in a
`CBBacklightNode` and asks it for `-getBacklightCalibration:`. That call reads the IORegistry property
`backlight-calibration-parameters`. Our kernel's `AppleARMBacklight` (published by `AppleCLCD::publishBacklight()` when
`hk_bright=140`) does not have that property, so the call returns NO. The NO branch then calls the marketing-table lookup
`__TEXT+0x169810` three times. The table (Display `+0x48`) is still NULL at that point, because it is loaded later
(`copyMarketingTable` at `0x1e2742c4c`, stored at `0x1e274324c`). The lookup checks the pointer and then reads `table[0]` anyway,
at `0x1e2746924`. The result is a deterministic NULL read on every respawn.

QEMU does not crash because it publishes **no** `backlight-control` service. `initWithService:0` logs "Service is null" and
returns nil, so Display init stops at "Cannot initialize Display.m without backlight configuration" and never reaches the
lookup.

**Fix:** have `publishBacklight()` also publish `backlight-calibration-parameters` and `backlight-marketing-table`
(patch `0001-hk-bright-backlight-calibration.patch`). A zero-build alternative is to drop `hk_bright=140`. That gives up iOS
brightness control and goes back to the configuration of the 73 phone boots that did not crash.

## 1. Disassembly (observed; dyld cache `/data/hackios-qemu/dsc-r6`, uuid 0f1ee332, `cbdis.py`)

Crash frames: `pc 0x201efa924 lr 0x201ef6298` with slide `0x1f7b4000` give pc `0x1e2746924` and lr `0x1e2742298`. In
`reader.txt:221` the exception is 1 (EXC_BAD_ACCESS), code `0x1 0x0`, so the fault address is 0.

**Faulting function** `0x1e2746810` (CoreBrightness `__TEXT+0x169810`, local symbol). It is `float lut(Display *d, float x)`:

```
0x1e2746838: ldur  x8, [x29, #-0x8]        ; d
0x1e274683c: cbz   x8, 0x1e2746914         ; d == NULL  -> skip interpolation
0x1e2746848: ldr   x8, [x8, #0x48]         ; d->table
0x1e274684c: cbz   x8, 0x1e2746914         ; table == NULL -> skip interpolation ...
0x1e274685c: ldr   w8, [x8, #0x40]         ; d->count  (index = x * (count - 1), linear between entries)
   ...
0x1e2746914: ldur  s0, [x29, #-0x14]       ; ... but the join point is unconditional:
0x1e2746920: ldr   x8, [x8, #0x48]         ;   d->table (NULL)
0x1e2746924: ldr   s0, [x8]                ;   table[0]   <-- FAULT, address 0
0x1e274692c: ldr   s1, [x8, #0x528]        ;   compared with d->Lmin_panel
```

**Caller** `0x1e2741c1c` (Display init, `__TEXT+0x164c1c`; 4,817 instructions). Called from `0x1e2672d3c`, `0x1e2672e40` and `0x1e2673570`.

```
0x1e2741cc8: bl  0x1e2746760                      ; _CFRuntimeCreateInstance + memset 0: d->table = NULL, d->count = 0
0x1e2741dd8: add x0, x8, #0xfb8                   ; class CBBacklightNode
0x1e2741ddc: bl  objc_alloc
0x1e2741de8: bl  objc_msgSend [initWithService:]  ; w2 = backlight service (io_service_t, arg w0 of Display init)
0x1e2741df0: str x0, [x8, #0x32f0]                ; d->node
0x1e2741e20: cbnz x8, ...                         ; node == nil -> "Cannot initialize Display.m without backlight configuration", return NULL
0x1e2741fb4: "Initializing Display.m without an AARMBL service"     (service == 0; logged only)
0x1e2742114: IORegistryEntryCreateCFProperty(service, @"IODisplayParameters") -> brightness {value,min,max}
0x1e2742228: ldr x0, [x8, #0x32f0]
0x1e2742230: add x2, x8, #0x508                   ; &d->calib
0x1e2742234: bl  objc_msgSend [getBacklightCalibration:]
0x1e2742240: tbnz w8, #0, 0x1e27422f4             ; YES -> skip the fallback
0x1e2742248: fallback: Lmin/Lmid/Lmax = 5/140/400 nits (d+0x528/0x524/0x520, product copies at 0x51c/0x518/0x514)
0x1e2742294: bl  0x1e2746810  (x = 0.0)            ; <-- lr 0x1e2742298: crashes here
0x1e27422b0: bl  0x1e2746810  (x = 0.5)
0x1e27422cc: bl  0x1e2746810  (x = 1.0)
   ...
0x1e2742c4c: bl  objc_msgSend [copyMarketingTable]; nil -> "Failed to load marketing table from the device", table stays NULL
0x1e274324c: str x8, [x9, #0x48]                  ; d->table is set only here, after the rescale loop
0x1e2743258: str w8, [x9, #0x40]                  ; d->count
```

**What the node reads** (observed in the methods; class names from the ObjC metadata, `objcmeth.py`):

- `-[CBBacklightNode initWithService:]` `0x1e272ee04`. If service == 0 it logs "Service is null" and returns nil. Otherwise it builds
  `CBIORegistryReader initWithService:` (plane "IOService", options 3) and `CBIORegistryParser parserWithReader:`.
- `-[CBIORegistryReader copyProperty:]` `0x1e26bd4b4` = `IORegistryEntrySearchCFProperty(service, "IOService", key,
  kCFAllocatorDefault, 3)`. Options 3 = recursive | parents, so the property may sit on `AppleARMBacklight` or on any provider above it.
- `-[CBBacklightNode getBacklightCalibration:]` `0x1e2731760`: `[reader copyProperty:@"backlight-calibration-parameters"]`.
  If the value is absent or not an NSDictionary, it returns **NO**. Otherwise it fills calib+0x00..0x20 from `integerValue / 65536` of
  `current-for-max-backlight`, `current-for-mid-backlight`, `hardware-max-current-limit`, `lMaxProduct`, `lMidProduct`,
  `lMinProduct`, `lMaxPanel`, `lMidPanel` and `lMinPanel`. calib+0x24 defaults to lMaxPanel and is overridden by
  `milliAmps2NitsScaleFactor` when that is > 0. It then returns **YES**. Missing keys read as 0. Only the dictionary itself is required.
- `-[CBBacklightNode copyMarketingTable]` `0x1e2731ad8` → `loadIOFixedArray:@"backlight-marketing-table"`. The value must be
  CFData whose length is a multiple of 4. Each little-endian int32 is divided by 65536 (`0x1e2638a84`, `0x1e26c1280`).

## 2. Kernel publication, phone vs QEMU (observed, IOK lines)

| | phone A7 r1 (`kernel.log` 462c8368…) | QEMU `backboardd-15m-retry-r17` (console 929b1e53…) |
| --- | --- | --- |
| `IOPropertyMatch backlight-control` | `-> AppleARMBacklight` (4×), `-> 1 found` | `-> none`, `-> 0 found` |
| `SWEET BL: AppleARMBacklight published` | `cap 140 nits` (boot-args `hk_bright=140`) | absent |
| `IODeviceTree:/core-brightness` | none | none |
| `IOAcceleratorES` | 610× `-> 0 found` (the 636 in A7.md counts all lines) | 302× `-> 0 found` |
| backboardd usertrap | 14 in kernel.log, 16 in reader.txt; all unslid pc `0x1e2746924` | 0 (only appprotectiond traps) |
| CoreBrightness | crashes in Display init | `[Backlight] ... backlight ready in 0.0036 s` |

`IOAcceleratorES` returns 0 on both, and only the phone crashes, so it is ruled out. The difference is the backlight service.

**All local phone attempts** (`research/laguna-usb-fix/attempts/*/ramdump/kernel.log`, 78 that log the backlight-control match):

- 73 boots match `-> none`. All of them show 0 backboardd usertraps and 0 SIGSEGV exits. They include the owner-confirmed Home boot
  `20261101-234344-phone-root-r1`.
- 5 boots match `-> AppleARMBacklight`: p32-combined-ui-r1, native-metal-health-p30-a725-diag-r1, dualboot-gpt-a725-r5a,
  a7-ios-system-r1 and a7-ios-system-r2. Each shows 14–18 backboardd usertraps, every one at unslid pc `0x1e2746924`,
  lr `0x1e2742298`.

`kernel-release-integration-r1/candidate/.../SweetFramebuffer.cpp` and the release tree on the Mac (`research/ios26-release-r1/work/xnu`,
HEAD b228c4f, `iokit/Kernel/arm/SweetFramebuffer.cpp` sha256 6004d76e…, lines 393–425) give `AppleARMBacklight` only these:
`IODisplayParameters {brightness, brightness-nits}`, `backlight-control`, `user-accessible-max-nits` and `edr-max-nits`.

## 3. Observation vs inference

- Observed: the NULL source is Display `+0x48` (the marketing table), which `_CFRuntimeCreateInstance` zeroed and which has not yet been
  assigned at `0x1e2742294`. The branch is reached only when `getBacklightCalibration:` returns NO. In the cache, that happens only
  when `backlight-calibration-parameters` is missing or is not a dictionary.
- Observed: our `AppleARMBacklight` lacks that property and the marketing table. It sits under `AppleCLCD`, which also lacks them.
- Inference (strong, by elimination plus the 73/5 split): the search returned nil on the phone. The other way to get NO, a non-dictionary
  value, would need someone to publish the key, and nothing in our sources does.
- Inference: the crash is in CoreBrightness's own fallback (the NULL check does not cover the final read). With a real calibration
  dictionary the fallback is skipped. But the lookup has 15 call sites (`0x1e25f6c64` … `0x1e274af9c`), and all of them would hit
  the same NULL if the table were missing. So the **marketing table is needed too**, not only the dictionary.
- Not shown: whether a crash-free backboardd is enough for frames on the panel. A7 r2 (`20261103-144712`, deadline 1800, cpus=1,
  hk_bright=140) logs `frames+0` in all 38 HK TOP lines up to t=622 and 18 crashes. Its owner has not recorded a result yet.
  The p32 ramdump has nonzero-frame lines with the crash present, but the ring may hold earlier boots, so do not lean on either.
- Side observation, not part of the fix: Display init loads `user-accessible-max-nits` with `loadFixedFloat:` (int / 65536,
  `0x1e26bdbec`). The kernel publishes it as raw `140`, so CoreBrightness would read 0.0021 nits. If brightness then looks pinned to
  the floor after the fix, this is the next property to change to `cap << 16`. `edr-max-nits` is probably the same. Keep it as a
  separate one-variable change.

## 4. Proposed fix (smallest, in the hk_bright style)

`0001-hk-bright-backlight-calibration.patch` is for the release tree. `git apply --check` passes on a copy of `SweetFramebuffer.cpp`
(sha256 6004d76e…, host).

- New `iokit/Kernel/arm/hk_bright_calib.h`, with no XNU types, like `hk_bright_map.h`:
  - The marketing table is ascending 16.16 nits: `HKB_FLOOR_NITS`, then the `hkb_curve` points strictly between the floor and the cap,
    then the cap. For cap 140 that is `10 20 35 50 75 100 140`.
  - Calibration: Lmin/Lmid/Lmax are the table's values at 0, 0.5 and 1, which is what CoreBrightness's fallback would derive
    (Lmid = 50). Product equals panel. The currents are a linear model: I_max = Ihw_max = 20 mA, I_mid = I_max·Lmid/Lmax = 7.14 mA.
  - `milliAmps2NitsScaleFactor` is left out, so CoreBrightness's own default (lMaxPanel) applies.
  - These values are a self-consistent model, not panel data. The panel path only consumes `brightness-nits` / `brightness`, so they
    only shape CoreBrightness's curve.
- `SweetFramebuffer.cpp`: `sweet_bl_calibration(bl, cap)` sets `backlight-marketing-table` (OSData) and
  `backlight-calibration-parameters` (an OSDictionary of nine 32-bit OSNumbers) on the `AppleARMBacklight`, before
  `backlight-control` and `registerService()`. It logs `SWEET BL: calibration <n> table entries, mid <q16>/65536 nits`.
  Nothing changes when `hk_bright` is 0.

Rejected options:

- An env tweak or a CoreBrightness defaults change: the values come from the IORegistry, and no defaults key bypasses `getBacklightCalibration:`.
- An interposer à la `hk_container_ready`: it would have to swizzle a method and also fake the table. That is a bigger change in a
  less transparent layer, for the same effect.
- Dropping `hk_bright`: zero build, and proven by 73/73 boots, but brightness control is lost. Use it if the next boot must reach Home
  regardless.

## 5. Host evidence for the artifact

- `test/test_hk_bright_calib.c`, with host clang `-Wall -Wextra -Werror`, then again with `-fsanitize=undefined,address`: **PASS caps 11..140**.
  For every cap it checks that the table is ascending, runs from floor to cap and has n ≥ 2, that Lmin/Lmid/Lmax equal CoreBrightness's own
  lookup at 0/0.5/1, and that all values are > 0.
  Output for cap 140: `0x140000 0x72492 0x140000 0x8c0000 0x320000 0xa0000 0x8c0000 0x320000 0xa0000` (key order as above).
- `test/mock_kext.cpp` takes the patch's `sweet_bl_calibration()` verbatim, against stand-in libkern signatures, and builds with
  `clang++ -target arm64e-apple-ios26.0 -ffreestanding -fno-exceptions -fno-rtti -O2 -Werror`. The object is a Mach-O arm64e
  (sha256 c1080328…). Symbols: `__Z20sweet_bl_calibrationP9IOServicej` defined. Branch relocations: `OSData::withBytes` ×1,
  `OSDictionary::withCapacity` ×1, `OSNumber::withNumber` ×9, `OSDictionary::setObject` ×9, `IOService::setProperty` ×2,
  `OSObject::release` ×11, `IOLog` ×1. The cstrings hold both property names and all nine keys.
  **This is not the XNU build:** the real single-file cross-compile and the link are still to do on the Mac.

## 6. Verify in one attended boot

1. Mac, release tree: `git apply 0001-…patch`. Do a single-file ARM64 compile of `SweetFramebuffer.cpp` and check that the object
   defines `sweet_bl_calibration` (or that it is inlined into `AppleCLCD::publishBacklight`) and contains both property strings.
   Then link the kernel the same way as `kernel.rootview` (`research/ios26-dualboot-r8/rootview/RESULT.md`).
2. Optional, when the rig is free: QEMU exercises this only if `sweet_scanout_bright_cap()` is nonzero there. In this run's console it
   is not (no `SWEET BL`), so QEMU cannot test the fix. Do not count a QEMU pass.
3. Image `a7-ios-system-r3` is a7-ios-system-r2 with only the kernel changed. Keep the same `--phone-args` (with `hk_bright=140`),
   `--phone-deadline 1800`, `fastboot boot`, then the return check.
4. The boot passes if `ramdump/kernel.log` shows all of these:
   - `SWEET BL: AppleARMBacklight published, cap 140 nits` and `SWEET BL: calibration 7 table entries, mid 3276800/65536 nits`.
   - **Zero** `usertrap: backboardd` lines with unslid pc `0x1e2746924`, and no `com.apple.backboardd ... exited due to SIGSEGV`.
   - The backboardd pid is unchanged across the HK TOP lines.
   - `SWEET BL: request ...` lines appear: CoreBrightness now drives the service.
   - Separately, and not the pass criterion for this fix: `frames+N` and what the owner sees.
5. If backboardd traps at a **different** PC: `dsc_sym.py <cache> <slide> <pc> <lr>`, then `cbdis.py` on the function. That is the next
   missing property; there was no other way to see past this one.
6. If the patched boot cannot be attended soon: the control is r2 with `hk_bright=140` removed. Expect `backlight-control -> none` and
   0 backboardd traps. It confirms the attribution with no build, but not the patch.

## Files here

- `FINDINGS.md`: this file.
- `0001-hk-bright-backlight-calibration.patch`: for the release tree (adds `hk_bright_calib.h` and changes `SweetFramebuffer.cpp`).
- `hk_bright_calib.h`: the same header, in its patched form.
- `ref/hk_bright_map.h`: a read-only copy of the release tree's header the test includes (sha256 5549a5c4…).
- `test/test_hk_bright_calib.c` and `test/mock_kext.cpp`: the host checks in §5. Build commands:
  `clang -std=c11 -Wall -Wextra -Werror -I. -Iref test/test_hk_bright_calib.c` and
  `clang++ -target arm64e-apple-ios26.0 -std=gnu++17 -ffreestanding -fno-exceptions -fno-rtti -fno-builtin -Wall -Wextra -Werror -Wno-unused-function -O2 -I. -Iref -c test/mock_kext.cpp`
  (`~/.local/share/hackios-host/llvm/bin`).
- `cbdis.py`: fixed-range dyld-cache disassembler. It resolves arm64e branch islands to exports, `objc_msgSend` selector stubs to
  selectors, and CFStrings; it uses the 34-bit cache-pointer mask.
- `objcmeth.py`: an ObjC class's method list → IMPs. The relative-selector base for cache 0f1ee332 is `0x1fa27fde0`.
- Full disassembly of Display init and the lookup can be regenerated with
  `cbdis.py /data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e 0x1e2741c1c 0x4b44` and `… 0x1e2746810 0x1d4`. It is Apple code,
  so it is not stored here.
