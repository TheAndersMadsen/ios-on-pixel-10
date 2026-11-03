# backboardd's 30 s `IOAcceleratorES` wait: what loops, why, and how to skip it (2026-11-03, HOST analysis)

Labels: **observed** = read in a phone log, the release XNU source or the dyld cache; **host** = built or run on m1box;
**inference** = not tested. No phone, QEMU, image or root-index action in this work. Cache:
`/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e`, uuid 0f1ee332… (the phone's cache by the CoreBrightness PC match in
`../corebrightness/FINDINGS.md`; the dylib checks the QuartzCore UUID at run time anyway).

## Answer

- **Who loops: QuartzCore**, not Metal, IOSurface, IOMobileFramebuffer or BackBoardServices. Before CoreAnimation creates
  its Metal device, it runs a `dispatch_once` block. The block polls
  `IOServiceGetMatchingServices(IOServiceMatching("IOAcceleratorES"))`, **at most 301 times, with `usleep(100000)` between
  tries**, and stops at the first service found. The block discards the result. The device is created afterwards with
  `MTLCreateSystemDefaultDevice()`, which returns nil on our phone. CoreAnimation then takes the path it takes today in every
  Home boot.
- **No defaults key or env var is read on this path** (observed). The fix with the fewest side effects: **mark that once
  predicate done before QuartzCore uses it**. `src/hk_accel_once.c` (backboardd only, `HK_ACCEL_ONCE=probe|skip`) follows the
  existing `runtime/ca_sampler/src/hs_hook.c` constructor pattern. It writes no code. Its only write is libdispatch's own
  `dispatch_once_f()` on QuartzCore's predicate.
- **Expected gain: 30.0 s of sleep for each backboardd process** (code). Measured spans are 28.4–29.9 s on four phone boots.
  First frame and Home on 5 cores come an estimated **~15–25 s** sooner (inference, §5). The gain repeats on every backboardd
  respawn.
- An `__interpose` of `IOServiceGetMatchingServices` or `usleep` **would not work**. QuartzCore calls IOKit through a
  cache-internal branch island, not through a GOT that dyld can rebind (observed, §2.4).

## 1. Log evidence (observed; `research/laguna-usb-fix/attempts/<id>/ramdump/kernel.log`, `polltime.py`)

The kernel prints these lines from `internal_io_service_get_matching_services()`
(`research/ios26-release-r1/work/xnu/iokit/Kernel/IOUserClient.cpp:2806-2819`, `sweet_iolog_dict(..., "matching", ...)`). The
key `IOServiceNotificationUser` appears in every user dictionary; it is not specific to this call. Logging is limited to
`backboardd,SpringBoard` (`sweetiolog` default) and to **400 IOK lines per boot** (`sweet_iolog_lines >= 400`). After a
respawn, the later polls are therefore not logged.

| Attempt | Polls per burst | Kernel axis (s) | launchd clock across the burst | Next backboardd IOK line |
|---|---|---|---|---|
| `20261102-111800-sampler-off-p29-r1` (5 CPU, Home) | 302 | 10 → 40 | 29.1 s | `matching1 AGXAccelerator -> none`, then `SWEET FB: display on` |
| `20261102-101134-phone-p29-profile-r1` (5 CPU) | 302 | 10 → 40 | 28.5 s | same |
| `20261102-095609-phone-p29-live-r1` (5 CPU, Home seen by the owner) | 567 (msgbuf wrapped) | 10 → 40 | 29.9 s | same |
| `20261103-135606-a7-ios-system-r1` (5 CPU, black) | 302, then 16 after the respawn (log cap) | 10 → 40, 40 → | 28.4 s | `usertrap: backboardd` (CoreBrightness), `exec backboardd`, polling again |
| `20261101-234344-phone-root-r1` (1 CPU, Home) | 302 | 40 → 70 | (launchd stamps lag on 1 CPU) | `display on` at 70.1 s |

The ramdumps usually hold the boot twice (msgbuf and persistent console), so the per-boot totals in A7.md and BUDGET.md
(604, 610, 636) are about 2 × 302. Of each 302, **301 come from the QuartzCore loop** (code). The extra one is most likely
Metal's `-[MTLIOAccelServiceGlobalContext init]` inside `MTLCreateSystemDefaultDevice()`, which matches the same class once
(§2.3). Its position fits: it comes right before `matching1 AGXAccelerator` (inference).

Context just before the first poll (sampler-off): `open AppleCLCD`, IOMFB selectors, `backlight-control -> none`,
`path IODeviceTree:/core-brightness -> none`, then the first `IOAcceleratorES -> 0 found`. Only `IOK backboardd` lines ever
match `IOAcceleratorES`: 42,213 lines across all local attempts, and no SpringBoard line.

## 2. Disassembly (observed; `strfind.py`, `xref.py`, `blref.py`, `ptrref.py`, `../corebrightness/cbdis.py`)

### 2.1 Where the string is used

`strfind.py` finds `"IOAcceleratorES"` in 13 images. The two loaded in backboardd that matter are QuartzCore `0x18427f670`
and Metal `0x1862f3cec`. `xref.py` gives one code reference each: QuartzCore `0x184215a80`
and Metal `0x186115d80`.

### 2.2 QuartzCore: the wait (block invoke `0x184215a0c`, QuartzCore `__TEXT+0x342a0c`, 0xe8 bytes)

```
0x184215a48: bl   IOMainPort(0, &port)            ; error -> return
0x184215a7c: mov  w21, #0                          ; tries = 0
0x184215a80: adrp/add x19 -> "IOAcceleratorES"
0x184215a90: bl   IOServiceMatching
0x184215aa0: bl   IOServiceGetMatchingServices(port, m, &it)
0x184215aa4: cbnz w0, return                       ; kr != 0 -> leave at once
0x184215aa8: mov  w20, #0                          ; found = 0
0x184215ab0: bl   IOIteratorNext ; IOObjectRelease ; found = 1   (loop over the iterator)
0x184215ac8: bl   IOObjectRelease(it)
0x184215acc: cmp  w21, #0x12b                      ; tries > 299 ?
0x184215ad4: orr  w8, found, (tries > 299)
0x184215ad8: tbnz w8, #0, return                   ; found or exhausted -> return
0x184215adc: add  w21, w21, #1
0x184215ae0: mov/movk w0, #100000 ; bl usleep      ; 0.1 s
0x184215aec: b    0x184215a88
```

Exit conditions: a service is found, `IOServiceGetMatchingServices` fails, `IOMainPort` fails, or 301 tries have run (300
sleeps = 30.0 s). The function has no output. It writes only its own stack slots (no global store), so **the result is
discarded**.

### 2.3 Call graph

- The wait is the invoke of a global block literal at `0x1ee991a20` (QuartzCore `__AUTH_CONST,__const`: flags
  `0x50000000`, invoke `0x8014000004215a0c` → `0x184215a0c`). `ptrref.py` and `blref.py` find exactly one pointer to the wait
  function, the one in this literal, and one code reference to the literal: `0x1842159e8`.
- **`0x184215998`** (QuartzCore `__TEXT+0x342998`, local, called "create device" here):
  ```
  objc_autoreleasePoolPush
  ldr x8, [pred @ 0x1e9ccc3d0] ; cmn x8, #1 ; b.ne -> dispatch_once(&pred, ^wait)   ; pred in QuartzCore __DATA,__bss
  bl  MTLCreateSystemDefaultDevice
  objc_autoreleasePoolPop ; return device
  ```
- `0x184215998` has 10 callers (`blref.py`). Every one caches the device and handles nil. Two checked in full:
  `0x1842131d8` (`com.apple.coreanimation.IOMFBDisplay`) and `0x183f37de8` (`com.apple.coreanimation.AccelServer`) both run
  `ldr x0,[obj,#0x138]; cbnz; bl 0x184215998; str x0,[obj,#0x138]; cbz x0 -> skip the Metal setup`. The other 8 are
  `sdf_generator`, `CACoding`, `async`, `VirtualServer`, `CompressionReadbackConverter`, two in `CAWindowServerSurface`
  setup, and `0x1841d6964`. The once makes the 30 s a single cost per process, paid by whichever caller runs first.
- Metal `-[MTLIOAccelServiceGlobalContext init]` (`0x186115d08`) matches `IOAcceleratorES` once with no retry. If
  `IOServiceGetMatchingServices` fails, it does `NSLog("%s: IOServiceGetMatchingServices failed %x")` and returns **nil**. On
  success it builds an NSMutableArray and adds a service only if `0x186115e54` returns a class. That function returns nil
  when the service has no `MetalPluginName` property (`IORegistryEntryCreateCFProperty` → `cbz` → `mov x20,#0`).

### 2.4 Why an interposer on IOKit/libc does not work

`bl 0x186bea460` in QuartzCore jumps to an island: `adrp x16; add x16,#0x7fc; br x16` →
`0x197ecb7fc` = IOKit `_IOServiceGetMatchingServices` (its `pacibsp`). The call does not go through a GOT slot, so dyld has
nothing to rebind for `__DATA,__interpose`. `usleep` is reached the same way (`0x186bec500`). IOKit's own
`IOServiceGetMatchingServices` returns the MIG `kr` unchanged and has no fallback (`0x197ecb7fc..0x197ecb954`).

### 2.5 No preference or environment gate

`0x184215998` and `0x184215a0c` call no `CFPreferences*`, `getenv`, `os_variant` or `NSUserDefaults`. The only branch before
the wait is the once predicate. The callers checked only test their cached device pointer. A defaults key or env var could
only work as the carrier for an inserted library.

## 3. Options

| Option | Effect on the loop (observed) | Side effects | Verdict |
|---|---|---|---|
| Defaults/preferences key | none read | n/a | **rejected**: there is none (§2.5) |
| Env var alone | none read | n/a | **rejected**. Used only to carry `DYLD_INSERT_LIBRARIES` + `HK_ACCEL_ONCE` |
| `__interpose` IOServiceGetMatchingServices/usleep | not reached (§2.4) | n/a | **rejected** |
| **Pre-complete the once predicate (hs_hook pattern)** | the wait block never runs; `0x184215998` goes straight to `MTLCreateSystemDefaultDevice()` | none on the code path: what follows is the path that runs today after the 30 s (§4) | **recommended** |
| Kernel: `io_service_get_matching_services` returns an error for `IOAcceleratorES` | `cbnz w0` → leaves on the first try | Metal's GlobalContext then logs an error and returns **nil instead of an empty context**. Not traced further; this hits every process that uses Metal | second best; needs proof of the nil path |
| Kernel: publish a stub `IOAcceleratorES` service | `found = 1` → leaves on the first try | Metal skips it (no `MetalPluginName`, §2.3). Not checked: the other 11 images that name the class (IOAccelMemoryInfo, GPURawCounter, OpenGLES …). Needs a kernel class of that name | **not proven safe**; do not do it first |
| Patch QuartzCore's `cmp w21,#0x12b` in memory | loop bound 0 | writes code pages (`vm_protect` COPY), larger blast radius | rejected in favour of the data write |

## 4. The artifact: `hk_accel_once` (host; not wired into any image)

- `src/hka_decide.h`: the constants and a pure decision function. `src/hk_accel_once.c`: the constructor.
  Gates: `getprogname() == "backboardd"` and `HK_ACCEL_ONCE` ∈ {`probe`, `skip`}. Otherwise it does nothing and logs
  nothing. Any other value logs `invalid` and leaves the process untouched.
- Checks, in order (any failure logs `HKACCEL: mode=… verdict=<reason> …, untouched`):
  1. QuartzCore is loaded (`_dyld_get_image_name` ends in `/QuartzCore.framework/QuartzCore`).
  2. Its `LC_UUID` is `8f1e0b3fadd63710a790009333597ab4`.
  3. header == `0x183ed3000` + slide.
  4. The block literal's invoke pointer, masked with `0x7fffffffff` as `hs_hook.c` does, equals `0x184215a0c` + slide.
  5. FNV-1a of the wait loop (0xe8 bytes) is `0xfb4e10f62002b5fb` and of the create function (0x74 bytes) is
     `0xe36463c047268227`.
  6. The predicate is 0. If it is `~0`, the verdict is `already`; any other value is `busy`, untouched.
- `skip` then calls `dispatch_once_f(pred, NULL, noop)` and logs
  `HKACCEL: IOAcceleratorES wait skipped, pred 0 -> 0xffffffffffffffff, slide …`. QuartzCore's inline fast path
  (`cmn x8,#1`) then never enters the block. `probe` logs `verdict=apply` and writes nothing.
- Host evidence:
  - `check_cache.py`: **PASS**. It re-derives every constant from the cache: UUID; predicate in `__DATA,__bss`; block flags
    and invoke; both fingerprints; the create function's adrp+add to the predicate and the literal; `cmp w21,#0x12b`; and
    `mov/movk #100000`.
  - `test/test_hka_decide.c` (clang `-Wall -Wextra -Werror -fsanitize=undefined,address`): **PASS**. 4 slides × 10 cases (apply,
    already, busy, each refusal, unsigned pointer) and the FNV reference vector.
  - `build.sh`: `build/hk_accel_once.o` is a **Mach-O ARM64 E PAC00** object (sha256 `3ce4a383…`). It defines
    `_hka_start` (in `__mod_init_func`) and `_hka_noop`, with `pacibsp`/`autibsp`/`paciza`. Its undefined symbols are only
    `_dyld_*`, `dispatch_once_f`, `getprogname`, `getenv`, `open/write/close`, `snprintf` and `str*/memcmp`.
  - lld 23 (`-flavor darwin`) cannot link arm64e. Its `build/hk_accel_once.inspect-only.dylib` is `ARM64 ALL` and unsigned,
    so it serves only to inspect load commands (`LC_ID_DYLIB /private/var/hk/hk_accel_once.dylib`, `LC_LOAD_DYLIB
    libSystem.B`, `LC_BUILD_VERSION ios 26.0`). **Do not deploy it.**
  - The deployable dylib is built on the Mac with the ca_sampler recipe (`runtime/ca_sampler/tools/build.py:95-142`):
    `xcrun clang -arch arm64e -isysroot <iphoneos> -miphoneos-version-min=26.0 -dynamiclib -install_name
    /private/var/hk/hk_accel_once.dylib src/hk_accel_once.c -Isrc`, then `pacstrip --sign`, then `codesign --verify --strict`.
    Before that, drop the hand-written prototypes in favour of the SDK headers, or keep them; they match libSystem.
- Delivery (not done): the backboardd `hk_env` row already carries `DYLD_INSERT_LIBRARIES` (hgltrack, hk_container_ready;
  `research/ios26-apps-r1/receipts/l1-r16/LANE1.md`). Append `:/private/var/hk/hk_accel_once.dylib` and add `HK_ACCEL_ONCE=probe`
  first, then `skip`, with `runtime/ca_sampler/tools/compose.py`-style single-record extension (not a same-length edit).
  Physical evidence that the hs_hook pattern installs in backboardd: `runtime/ca_sampler/README.md` (sampler-verify-p29-r1).

## 5. Seconds saved (from the timestamps)

- Per backboardd process, **30.0 s of sleep plus 301 MIG round trips** (code). Measured spans: 28.4, 28.5, 29.1 and 29.9 s on
  four 5-CPU boots. On the 1-CPU Home boot the axis runs from 40 to 70 s.
- First frame on 5 CPUs (inference): today `display on` comes at axis 40 s, right after the last poll, in all three p29
  boots. backboardd starts polling before axis 10 s (exec at 4.2 s). Without the wait it would be limited by the launch
  storm, which runs to ~20–30 s on 5 cores (BUDGET.md §3). Expect first frame at ~15–25 s and Home at ~25–35 s after root
  instead of ~50 s: **≈ 15–25 s saved** (BUDGET's 20–30 s upper bound holds only if the storm does not slow backboardd).
- 1 CPU (inference): the wait is a sleep, so the single core does other launch work meanwhile. First frame may move by up to
  30 s, but Home (~590 s, CPU-bound) probably moves much less.
- Respawns: each new backboardd pays the 30 s again (new process, new once; observed: polling restarts right after
  `exec backboardd` in A7 r1). With the CoreBrightness crash still present, `skip` only makes the crash loop faster. It
  removes no crash.

## 6. Risks and what to verify (inference unless noted)

- What runs after the wait is unchanged. What changes is **timing**: backboardd reaches device creation and its first frame
  ~30 s earlier, while the launch storm still runs. The phone-only NSURL-nil abort (`container_system_path_for_identifier`
  returning NULL early; `LANE1.md`) is a timing effect. Ship this with `HK_CONTAINER_READY=retry`, not before it.
- Land BUDGET change #1 first (CoreBrightness). Otherwise this cannot be measured on the ios_system line.
- One attended boot, one variable (a Home-reaching recipe plus `HK_ACCEL_ONCE=probe`, then `skip`). Pass criteria in
  `kernel.log`:
  - `hk_env: backboardd gets … HK_ACCEL_ONCE=skip`;
  - `HKACCEL: IOAcceleratorES wait skipped` (it goes to `/dev/console`, which the capture may miss, as with HKCONTAINER);
  - **≤ 2 `IOAcceleratorES` lines per backboardd process** (Metal's one, and none from QuartzCore);
  - `display on` before axis 40 s;
  - no new `usertrap: backboardd`.
- Not shown: that no later QuartzCore code depends on time having passed. Nothing in `0x184215998` does.

## Files here

- `FINDINGS.md`: this file.
- `strfind.py` (string occurrences by image), `xref.py` (adrp+add/ldr code references), `blref.py` (b/bl and adrp+add to a
  target), `ptrref.py` (cache pointers to a target in an image's data): new host reading aids built on `dsc_sym.py`.
- `polltime.py`: poll bursts per backboardd process with the launchd clock (§1).
- `check_cache.py`: re-derives and asserts every constant against the cache.
- `src/hka_decide.h`, `src/hk_accel_once.c`, `src/libSystem.tbd` (link stub for m1box), `test/test_hka_decide.c`, `build.sh`.
- `build/` (derived; not for git): the arm64e object, the inspect-only dylib, nm/headers/disassembly text.
- To regenerate the Apple disassembly quoted above: `../corebrightness/cbdis.py <cache> 0x184215998 0x15c`. It is Apple code,
  so it is not stored here.
