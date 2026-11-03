# chooser-ios-r2: the iOS chooser with working volume keys (C1, C3, C4; attended, `fastboot boot` only)

Status 2026-11-03: **host-built and checked on m1box only.** Neither image has been booted. No QEMU. Nothing here touched the
phone. Receipts are in `receipts/r2/`. Labels: **source**, **host** (m1box unit tests), **ARM64** (the linked shim inspected),
**physical** (quoted from earlier receipts), **inference**.

## What changed against chooser-ios-r1 (the C2 image that reached Home)

`shim/chooser_ios.c` redrew the menu exactly as chooser-v1-r12 did (`chooser_ios.c:433` in DIAG-r13.md): the band was blended
straight into the Normal-NC panel buffer (≈ 3.97 s per redraw on the phone) and the keys were read only between redraws.
chooser-ios-r1 had no keys, so the symptom did not show. With keys it would have shown r12's dead keys.

r2 takes chooser-v1-r13's fix (6cc2966) and **reuses r13's code instead of copying it**:

- `shim/chooser_menu_r13.h` (new) holds r13's `chooser_menu_tick`, `chooser_dcs_entries`/`chooser_dcs_room`, `chooser_band_copy`
  and constants (15 s hard end, 300-entry release reserve). These were moved out of `chooser.c` byte for byte. `chooser.c` now includes the
  header. **ARM64: chooser.o `.text/.rodata/.data` with r12, r13 and r13-diag flags is identical before and after the move**, and so is
  `chooser_ios.o` with r1's flags (`receipts/r2/object-identity.txt`, 8/8 configurations).
- `chooser_ios.c`, gate `TGL_CHOOSER_KEYS_FIX`: r13's loop with the menu instance's present. menu_ui's row hook calls
  `chooser_menu_tick` once per drawn row. The pure `tgl_chooser_ios_menu_tick` does chooser.c's `tgl_chooser_menu_feed`, then
  the 15 s hard end, then the countdown number. The band is drawn into the cached Android destination and only stored to the panel.
  It redraws only when the ring or the number changes, and presents (quiet, 2 record entries) only while the record keeps the release's room.
  New for the iOS branch: the shadow lines are cleaned (`dc civac`) before `cios_mmu_off`, so the MMU-off sequence again finds
  only the loaded image dirty.
- `tools/chooser_ios_image.py --keys` now means keys_laguna **plus** r13's gates (`TGL_CHOOSER_KEYS_FIX`, `TGL_MENU_ROW_HOOK`,
  `TGL_DCS_PRESENT_QUIET`; the same gate string as chooser-v1-r13). The menu display instance must equal tgl_dcs.c built with r11's flags
  + `TGL_DCS_PRESENT_QUIET`, and must differ from plain r11. The linked `tgl_chooser_run` must form `chooser_menu_tick`'s address,
  store it to `tgl_menu_row_hook`, draw the band two ways, call `tgl_dcsm_present` and carry 15000 ms. `check` also refuses a manifest
  whose keys and r13 gates disagree. A keys image without the r13 loop can no longer be built.

Not changed: the admission, layout, display release (`tgl_dcsm_release`, 557 instructions, identical to r1), `cios_mmu_off`, the
handback and the whole direct iOS path. ARM64, r1-ios against r2-ios after address normalisation (`receipts/r2/r1ios-vs-r2ios-functions.txt`):
**310 of 316 common functions are identical.** The 6 that differ are the four menu_ui renderers (row hook), `tgl_chooser_run` and `tgl_dcsm_present`
(quiet). The new functions are `chooser_menu_tick`, `cios_keys`, `cios_keys_start`, `keys_init`, `keys_poll`, `keys_raw_levels`, `text_c`,
`tgl_chooser_ios_menu_tick` and `tgl_chooser_menu_feed`. r2 against r2-ios: same 325 functions; only `tgl_chooser_run` differs in 8 instructions
(initial `sel` 0 vs the admitted-entry flag, plus the per-build nonce `mov/movk`).

## Images (m1box, clang/LLD 23.1.4, `TGL_TOOLCHAIN=llvm`, tree e8d9805 + the uncommitted changes listed in the hand-off)

| Image | boot.img sha256 | Default | installable |
| --- | --- | --- | --- |
| `research/images/chooser-ios-r2/` | `cab9d96e14f8acead4c752dde71e4e9d12ae04f32b439a004640e46a92b2f978` | Android | **true** (C1, C3, C4 candidate) |
| `research/images/chooser-ios-r2-ios/` | `929a660cfbaf5bb6b55403822e0b47fa8ac3c059a6cb26a21b14bb68f8df807e` | iOS | false |

- Both: 67,108,864 B, kernel blob 49,134,064 B, which is **the same size as chooser-ios-r1-ios, which ABL loaded on the phone (C2, physical)**. The iOS payload
  is a7-ios-system-r3's `payload-usb.bin` (e28b35f7…, iOS image 4a32afe0…, the same as r1). The stock boot_b lz4 is a54c3b3d…. The stock vbmeta is transplanted (2368 B at
  49139712, 36ac3c0c…f217, the same as r11/r12/r1). The image margin is 16,918,208 B and the blob margin 51,529,232 B.
- kernel.bin: r2 `ba84f804…6ffb`, r2-ios `9c9f2535…8843`. Full lists: `receipts/r2/*-SHA256SUMS.txt`.
- Build (for r2-ios add `--default-ios`):
  `LLVM=~/.local/share/hackios-host/llvm/bin TGL_TOOLCHAIN=llvm python3 -I tools/chooser_ios_image.py image chooser-ios-r2 --ios-image research/images/a7-ios-system-r3 --stock-kernel research/ios26-dualboot-r8/truth/boot_b.img --stock-kernel-sha 3635317e93f67de2e6e75e38f892fe8604008bccd9717a369a590b7a35ce20f5 --fdt research/ios26-dualboot-r8/truth/fdt.dtb --keys`
- `chooser_ios_image.py check`: `OK chooser-ios-r2 … default android installable` and `OK chooser-ios-r2-ios … default ios not installable`.
  The r1-ios image still checks OK.

Host tests in each build (`receipts/r2/*-host-tests.txt`, `*-buildsh-suites.txt`): chooser-ios 74/0 (the A0 FDT and the real r3 payload:
admission OK, window 0x882000000+4 GiB, Android at 0xc9c00000), lz4 5/0 and 68/0, chooser 44/0 and 89/0, el2 mmu 12/0, ufs route 87/0,
ufs speed 55/0 (21/21 mutants), all-stage 9/0, dcs bright 1007/0, fast-start 40/0, quiesce 62/0, menu band shadow 41/0, and the tool test 12/0.
Also `shim/test_keys.py` PASS and `tools/test_chooser_image.py` OK. The chooser-ios host test gained 19 r13 checks. These cover a press that starts and ends inside a 3.97 s redraw, which still
picks iOS; Down then Up giving Android; a held key counting as one press; a chord being ignored; the default-iOS timeout with exactly 4 redraws in 5 s; Vol Up on the default-iOS image;
a refused entry giving NO_IOS; the 15 s hard end; and the shared helpers (row tick ORs the keys, record room up to 1203 entries, band copy writes only the band rows).
ARM64 (`receipts/r2/*-symbols.txt`, `r13-loop-linked.txt`): no undefined symbols; `tgl_dcs_release`, `tgl_dcs_present` and `tgl_dcsm_handoff` absent;
`chooser_menu_tick` 0x23d50 stored to `tgl_menu_row_hook` 0x298060 in `tgl_chooser_run`; the same check refuses r1-ios.

## What the owner sees (source; menu_ui.c, chooser.h)

- About 8 s after `fastboot boot` (r9/r10: the display came up 7.8 s after shim entry), the menu shows **two live tiles**: Android and iOS, the iOS tile not dimmed.
  The ring is on Android, and the pill reads **"Starting Android in 5"**.
- Vol Down moves the ring to iOS, and the pill reads "Starting iOS in N". Vol Up moves it back to Android. The ring should move within about 0.1 s of the press (inference:
  host band redraw 11.8 ms in cached memory; DIAG-r13). A press sets the deadline to at least 3 s after it. The menu always ends by 15 s after it appeared. Both keys together are ignored.
- At the end the panel goes dark (display handed back). Android then boots. Or, on iOS, the USB shim console starts, the panel comes back with the iOS
  ladder, and Home appears (C2: XNU console 21 s after the shim diagnostic, Home on the panel, then the designed 300 s deadline reset).

## Preconditions (every step)

Android on slot b, `adb devices` shows it, `ANDROID_SERIAL` set, force-fastboot ON (as for r11/r12/C2). Nothing is flashed, and slots, bootloader,
partitions and backups are untouched. **Use plain `fastboot boot` exactly as below**, not `tools/bootios` or a run-attempt wrapper.
run-attempt's AVB gate refuses a transplanted stock vbmeta (whose hash descriptor intentionally mismatches the boot image), so C2 was also booted with plain
`fastboot boot` (A7.md). Each attempt directory: `research/ios26-dualboot-r8/attempts/<name>/`. A photo of the panel is the best report.

## C1: chooser-ios-r2, hands off → Android

1. `adb reboot bootloader`, wait for `fastboot devices`.
2. `fastboot boot research/images/chooser-ios-r2/boot.img`. Expect `Sending 'boot.img' (65536 KB) OKAY` and `Booting OKAY`. Note the time.
3. **Hands off both volume keys.** The menu appears with both tiles live, the ring on Android and "Starting Android in 5". It counts down once per second: 5, 4, 3, 2, 1.
4. The panel goes dark and Android boots.
5. `bash research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/chooser-ios-r2-c1/android`.
6. `adb reboot bootloader`, `fastboot oem force-fastboot off`, `fastboot reboot`, then
   `bash research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/chooser-ios-r2-c1/return-after`.

**Pass:** all of
- the menu shows, iOS tile **not** dimmed (admission passed on real ABL state);
- the ring stays on Android, and the number counts down in 1 s steps without a press (the redraw-on-change loop presents);
- Android boots: step 5 verdict PASS, **`kernel_code_base` 0xc9c00000** (the chain-loaded stock kernel), boot_completed in about 42 s (r11-t1);
- step 6 return check PASS with kernel 0x80000000 (normal boot).

**Stop:** no menu, a reset loop, the iOS tile dimmed (admission refused on the phone: report, do not retry unchanged), the number frozen, a park in fastboot,
or any return check other than PASS.

## C3: chooser-ios-r2 with the keys (one boot each; run only after C1 passed)

### C3a: Vol Down → iOS → Home

1. As C1 steps 1–2 (same image, `chooser-ios-r2/boot.img`).
2. Hands off until the menu is on the panel. **Then press and release Volume Down once** (any time in the first ~4 s).
3. Expected at once: the ring jumps to iOS, and the pill reads "Starting iOS in N" (N ≥ 3).
4. **Press and release Volume Up once.** Expected: the ring returns to Android ("Starting Android in N").
5. **Press and release Volume Down once more**, then hands off. Expected: the ring on iOS. About 3 s later the panel goes dark.
6. iOS path as in C2: USB shim diagnostic, XNU console, the iOS display ladder lights the panel, and Home appears (A7-r3: frames from about t=111 s; C2: Home seen by the owner well inside the 300 s deadline).
   Note when Home appears and whether Settings opens.
7. The 300 s deadline ends the iOS boot (the designed panic, PSCI reset). With force-fastboot ON the phone parks in fastboot. Then
   `fastboot oem force-fastboot off`, `fastboot reboot`, and
   `bash research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/chooser-ios-r2-c3a/return-after`.

**Pass:** the ring follows **every** press within a moment (Down → iOS, Up → Android, Down → iOS); the menu ends about 3 s after the last press and
never later than 15 s after it appeared; iOS reaches **Home** on the panel (owner); return check PASS (kernel 0x80000000).

### C3b: Vol Down then Vol Up → Android

1. As C1 steps 1–2.
2. After the menu shows: Volume Down once (the ring to iOS), then Volume Up once (the ring to Android), then hands off.
3. The panel goes dark about 3 s after the last press, and Android boots.
4. Return checks as in C1 steps 5–6, attempt `chooser-ios-r2-c3b` (`android`, then `return-after`).

**Pass:** the ring moved twice; Android boots with `kernel_code_base` **0xc9c00000** (the chooser's Android branch, not a fallback); both return checks PASS.

**Stop (C3):** the ring never moves (the r12 symptom: the fix did not take; report the time, then boot `chooser-v1-r13-diag` per DIAG-r13.md for the pad words);
the ring moves late, about 4 s after a press (the redraw is still slow: report); a wrong entry (iOS picked but Android boots, or the reverse); a reset or park before Home
or Android; any return check other than PASS.

## C4: the installable bytes

C4 is **chooser-ios-r2 itself** (`cab9d96e…f978`, `installable: true`): the image a later `fastboot flash boot_b` would write is the exact
file booted in C1 and C3 (DESIGN.md section 5.2 precondition 1: "C1–C4 have passed with this exact sha"). There is no separate r3 image. Before any flash, re-run
`python3 -I tools/chooser_ios_image.py check research/images/chooser-ios-r2` and `sha256sum research/images/chooser-ios-r2/boot.img`;
both must still show cab9d96e…f978. **C4 passes when C1, C3a and C3b all passed with that sha.** The flash itself (A8) is a separate, destructive step that needs the owner's
explicit confirmation and DESIGN.md 5.2's preconditions (boot_b readback = 3635317e…20f5, getvars, P0). It is not part of this document.

## Optional: chooser-ios-r2-ios

`chooser-ios-r2-ios` (`929a660c…807e`) is C2 with keys: the countdown ends on iOS. Use it only if C3a fails between the menu and Home, to separate
"keys/menu" from "handback". Hands off → iOS → Home (as C2); Vol Up → Android with kernel 0xc9c00000. It is never installed.

## Not covered here

The ring's reaction time on the phone is not measured (host only). The 90 s bring-up deadline now also counts a longer menu (up to 15 s): r1-ios's 5 s menu
reached Home, so a 5–8 s keyed menu is inside the margin seen in C2 (inference). A miss resets cleanly (DESIGN.md section 7).
