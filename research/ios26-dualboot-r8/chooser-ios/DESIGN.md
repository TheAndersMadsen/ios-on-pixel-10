# Chooser iOS branch and persistence plan (design sub-agent, 2026-11-03, m1box, HOST ONLY)

Labels: **source** = read in this tree; **host** = ran on m1box (unit tests, real A0 data); **ARM64** = linked AArch64
shim inspected (symbols, disassembly, section hashes); **physical** = on the phone, quoted from receipts;
**inference** = not tested. Nothing in this lane touched the phone, the root Git index or QEMU.

Source lives in worktree `/srv/dev/.t3/worktrees/hackios/t3-06b9b643` (branch `t3/06b9b643`, fast-forwarded to
`ios26` b11f5e7). New files: `shim/chooser_ios.{c,h}`, `shim/chooser_ios_test.c`, `shim/tgl_dcs_menu.{c,h}`,
`tools/chooser_ios_image.py`, `tools/test_chooser_ios_image.py`. Glue edit: `shim/shim.c`, +13 lines, all under
`TGL_CHOOSER_IOS`. `chooser.c` and `tgl_dcs.c` are unchanged and are included or compiled as they are.

## 0. Short answer

- **One image.** The `boot_b` kernel blob is `[shim][TEGUPLD1 XNU payload][TGLLNX01 stock Android lz4]`.
  `image_size` covers all three. The boot header is stock `boot_b` with ramdisk 0, and the stock vbmeta is
  transplanted, as in chooser-v1-r11. Host-measured: blob 48.6 MB, 17.4 MB left in the 64 MiB partition, and
  52 MB left below ABL's initrd at 0x86000000.
- **After the menu**, the iOS branch gives the display back with the r11 release, turns the EL2 MMU and caches
  off, and returns to `shim_main`. From there the direct iOS path runs unchanged: console, USB, UFS, the
  `TGL_DCS_HANDOFF` display ladder, payload admission and the EL2->EL1 drop. These are the steps a7-ios-system-r1
  ran on the phone.
- **The display is handed to XNU** exactly as on a direct iOS boot: domain off, as ABL leaves it, then the iOS
  ladder publishes the takeover record. The menu instance never publishes one.
- **Persistence:** stay on `fastboot boot` until the attended ladder in section 6 passes. Then flash `boot_b` with
  the installable image (A8). The rollback is the A0 `boot_b` dump. The inactive-slot option is rejected
  (section 5.3).

## 1. Carrying the XNU payload

### 1.1 Embedded (chosen for v1)

Layout (source: `build.sh` embeds the envelope; `chooser.c` already skips it to find the segment;
`payload.h tgl_payload_embedded` allows bytes after the envelope):

```
_head ........ _end            shim Image (code, data, BSS, stacks, EL2 tables), image_size at +16
_end           "TEGUPLD1" u64 n
_end+16        n bytes TEGUXNU v2 payload = image_tool's payload-usb.bin, byte for byte
align 8        "TGLLNX01" 64-byte header + stock boot_b lz4 kernel (chooser_image.py segment())
```

`tools/chooser_ios_image.py image NAME --ios-image research/images/<A7-class image> --stock-kernel truth/boot_b.img
--stock-kernel-sha 3635317e… --fdt truth/fdt.dtb [--keys] [--default-ios]` does the following:

1. Re-verifies the iOS image against its manifest and reruns `contract_check`, the shim's own validator. The image
   must be bootable and `--phone-root`.
2. Builds the shim with **that image's own cflags and sources** plus `TGL_CHOOSER=1 TGL_CHOOSER_IOS=1` and the r11
   chooser gates (MMU, UI, DISPLAY). `build.sh` embeds the payload. The tool appends the segment and raises
   `image_size`.
3. Wraps the blob in the stock v4 header page with only `kernel_size` changed. Transplants the stock vbmeta.
4. Refuses the build unless all of these hold: blob and payload intact; offsets match the C rule; all host suites
   pass; the expected T/R symbols are present and the forbidden ones absent; the quiesce constants are in
   `tgl_dcsm_release` and GPCSR is absent from the iOS `tgl_dcs_run`; `shim_main` calls `tgl_chooser_run`; the
   section-identity checks in 2.3 hold.
5. Writes a manifest with the budget, the text identity, `default_entry` and `installable`.

`installable` = bootable, keys on and default Android. A `--default-ios` image is never installable. `check DIR`
re-verifies a finished image. `budget` prints the size table without building.

**Size budget** (host, `budget` and the real build `test-chooser-ios-r0`):

| Part | Bytes | Note |
| --- | --- | --- |
| shim (code+BSS, to `_end`) | 2,789,376 | iOS-line shim + chooser + 2nd DCS instance + keys_laguna |
| XNU envelope | 25,416,272 | rootview kernel ddf874fb… + 5-CPU window-882 ADT, **no /var overlay** (the A7 overlay is on the Mac) |
| Android segment | 20,437,296 | boot_b lz4 a54c3b3d…, 20,437,225 B |
| **kernel blob** | **48,642,944** | 46.4 MiB |
| boot image incl. header page | 48,648,192 | + 4,096 B vbmeta at the next 4 KiB, AVB footer in the last 64 B |
| partition 64 MiB − 1 MiB footer room | 66,060,288 | **margin 17,409,728** (≈ 17 MB more payload, e.g. the overlay) |
| ABL load gap 0x80000000..0x86000000 (inference) | 100,663,296 | **margin 52,020,352** |
| largest blob ABL has loaded for us | ≈ 28 MB (A7 iOS image) | this blob is **19.3 MB larger: proven only by step C1** |

The A7 image's overlay adds its own size to the envelope. If the payload ever passes about 42 MB, it no longer fits
(the `test_limits` test pins this).

### 1.2 Loaded from storage (designed, not built: v2 if C1 fails or the payload outgrows the margin)

- **Where:** the zero tail of `ios_system`, never `ios_data` (XNU's persist writer owns `ios_data`). The HFSX volume
  is 2,097,152 blocks of the 6,291,456. A slot at partition byte 8 GiB, block 2,097,152, would hold
  `"TGLXNUS1" | u32 version | u32 hdr_len | u64 payload_len | u64 csum64 | u8 sha256[32] | payload`.
  It is read only, and HFS never addresses it (inference: the volume header's block count bounds HFS).
- **How:** after the iOS pick, the shim's own UFS READ(10) path (`tgl_ufs_route`, "no WRITE ever built") reads
  the header, then `payload_len` bytes, into a RAM staging area below the XNU window and clear of every live range
  (`tgl_chooser_place`-style). It checks csum64, then `tgl_payload_validate`. `loader_boot` then takes the staged
  source instead of `tgl_payload_embedded`, which is a one-branch change in `loader.c`.
- **Gain:** the boot image falls to the proven r11 size (23 MB), and an iOS kernel update does not reflash `boot_b`.
- **Costs:** the UFS ladder must run before the payload is known, so the menu cannot dim the iOS tile honestly
  unless the read moves before the menu. Shim read speed for 25 MB is unmeasured. The ios_system whole-extent hash
  receipt (a95542a9…) changes, and the A7 readback recipe must learn the slot.
- **Not chosen:** the embedded layout fits with 17 MB to spare and changes nothing that A7 proved.

## 2. Jumping into the iOS path after the menu

### 2.1 Control flow (source, ARM64)

`shim_main` → WDT survey (pat posture) → FDT admission → `tgl_chooser_run` (chooser_ios.c):

1. EL2, SCTLR_EL2 M/C off, as chooser.c.
2. **Admit iOS** (`tgl_chooser_ios_admit`, pure):
   - layout;
   - `tgl_payload_validate` on the envelope bytes;
   - the same `tgl_handoff_inputs` / `tgl_handoff_window` calls `loader_boot` makes (shim code extent, FDT, initrd);
   - window clear of the whole loaded image and of ramoops 0x95200000+4M;
   - metadata clear of the initrd.
   A refusal only dims the iOS tile (`ios_available=0`). Android stays the default and the fallback, and its
   segment is still found (chooser.c's rule).
3. Segment parse, placement, the EL2 map (3 regions), csum, menu draw, the menu display ladder (`tgl_dcsm_*`),
   keys (keys_laguna if `TGL_KEYS_POLL`), menu loop. All are as chooser.c except `ios_available` and the initial
   selection (`TGL_CHOOSER_IOS_DEFAULT`).
4. Pick → `tgl_chooser_ios_action`. It returns XNU only when the result is iOS **and** the entry was admitted.
5. **Both branches** run the r11 display release first. A release failure or a pending SError is a refusal: the shim
   resets, and on an installed chooser the menu comes back.
6. **Android:** lz4 decode, header verify, `chain_jump_mmu_off`. This is chooser.c's code, and the binary path
   equals r11's apart from the admission and the stamp.
7. **iOS:** `cios_mmu_off(sctlr0, image, Android-region)` (2.2). Then SCTLR_EL2 is re-read and refused if M or C is
   still set. Then the stamps `0x00bf` RELEASE / MMU_OFF / HANDBACK, a WDT pat, and `return TGL_CHOOSER_PICKED_IOS`.

Back in `shim_main` (the `TGL_CHOOSER_IOS` hook): any other return → `stage_fail` (reset). The sentinel falls
through to `console init` and the rest of the direct iOS path. ARM64: `shim_main+0x1c68 bl tgl_chooser_run`, then
`cmp x0, tgl_chooser_picked_ios; b.ne stage_fail`.

### 2.2 CPU and cache state at the handback

- `el2_mmu.h` declares `tgl_el2_mmu_off`, but no file defines it. `chooser_ios.c` adds `cios_mmu_off`, a leaf with
  no stack frame. ARM64 disassembly at 0x23b00..0x23b8c:
  1. `dc civac` over the whole loaded image;
  2. `dsb`;
  3. `msr sctlr_el2` (the entry value);
  4. `isb`;
  5. `dc civac` over the image again and over the Android-placement WB region, to drop speculatively allocated
     clean lines so XNU's later cache-on cannot hit stale lines;
  6. `dsb; ic iallu; tlbi alle2; dsb; isb`.
  There are **no stores** between the first clean and the SCTLR write. The menu buffer is Normal-NC, so it has no
  dirty lines.
- Result: EL2, MMU/D-cache/I-cache as at ABL entry, DAIF masked, MAIR/TCR/TTBR0_EL2 left programmed (inert with
  M=0), watchdogs armed and patted. That is what `shim_main` has on a direct iOS fastboot boot.

### 2.3 Two display instances (source, ARM64)

`tgl_dcs.c` builds either `TGL_DCS_MENU` or `TGL_DCS_HANDOFF` (an `#ifdef/#elif` in `tgl_dcs_run`), and a second
`tgl_dcs_run` in one boot is refused (`d.started`). So:

- **iOS path instance:** `tgl_dcs.c` as image_tool builds it (`TGL_DCS_HANDOFF`, `TGL_DCS_BRIGHT=1`).
- **Menu instance:** `shim/tgl_dcs_menu.c` `#include`s `tgl_dcs.c` with r11's gates forced (`MENU`, `QUIESCE`,
  `BRIGHT=0`, `HANDOFF` undefined) and its seven external names renamed `tgl_dcsm_*`. `QUIESCE` stays local to
  this unit because it widens the allow-list (GPCSR).
- **Identity** (host, clang 23.1.4, recorded in the manifest's `text_identity`):
  - menu instance `.text` ca179987… and `.rodata` a777e742… equal tgl_dcs.c built with r11's chooser flags;
  - iOS instance `.text` c4cb75d6… and `.rodata` 603d1849… equal tgl_dcs.c built with the iOS line's flags alone.
  The chooser gates change neither.
- Both instances write the DCS record at 0x95438000. The iOS ladder's record replaces the menu's; the chooser
  stamps keep the release result.

## 3. Display state that the handback must leave for XNU

| Item | Must be at handback | How it is ensured | Evidence |
| --- | --- | --- | --- |
| DPU power (TOP/LPB_SSWRP_DPU, FE0, DSI0, pix/ref clocks) | **off, as ABL hands over**: the precondition of the iOS ladder and of XNU | `tgl_dcsm_release` with quiesce (layer idle, BE idle, BE IRQs reset, isolation on) then the LPCM off frames in vendor field order, polling TOP until off | physical: r11 release then Linux display up (Android path); **iOS ladder after a release: not yet (C2)** |
| Takeover record (`tgl_scanout_takeover_*`) | cleared at entry; published **only** by the iOS HANDOFF instance after its own run | `shim_main` clears it before the chooser; the MENU build has no publish call (ARM64: `tgl_scanout_takeover_publish` only in tgl_dcs.o) | source, ARM64 |
| Menu buffer 0xf0000000 | not scanned out; free for the console | layer off by quiesce and power-off; the console then reuses it (`con_init(TGL_FB_FALLBACK)`); boot_args Video points there as on direct boots | source |
| Panel | left as DSI0-off leaves it; the iOS ladder (stages A..L, S, one kick) re-initialises it | unchanged A7 ladder | **inference: C2 proves it** |
| DCS record | the iOS instance's | `tgl_dcs_begin` wipes it | source |
| SError | none pending | the chooser checks ISR.A after the ladder and after the release, and refuses otherwise | source |

Rejected for v1: keeping the panel lit through the handback (publishing a takeover record from the menu
state). It saves a blank and the second ladder, but it needs an edit to `tgl_dcs.c` (publish after `stage_menu`),
and XNU would receive an FE0-layer-configured DPU it has never seen. Reconsider after C2 passes.

## 4. Host and ARM64 evidence (this lane)

- `shim/chooser_ios_test.c` (host): **50 checks, 0 failed**. It covers:
  - layout at every payload length mod 8, with the same offset as chooser.c's skip, and seven refusals;
  - admission: valid; no initrd; shim on the initrd; corrupt payload; window over the image, over ramoops, or
    outside RAM;
  - the menu: default-iOS timeout; refused entry → Android; Volume Down → iOS; no keys → Android; defensive action
    table;
  - **real data:** the A0 FDT (ABL's tree for a normal boot, which is the chooser's case) with the real rootview
    payload at ABL's load PA 0x80000000. Admission OK at window 0x882000000+4 GiB. The Android Image places at
    **0xc9c00000**, the base r11 used physically. The combined image ends below the initrd.
- `tools/test_chooser_ios_image.py` (host): **5 tests, 0 failed** (layout mirror, assembly refusals, budget).
- Full image builds `research/images/test-chooser-ios-r0` (keys, default iOS) and `-r0b` (no keys, default Android)
  in the worktree. Both are host checks, `bootable=false`, because the payload is not from a checked image_tool
  directory and the link used GNU ld 2.46 (m1box has no ld.lld). For r0, `build.sh` suites: ufs route 87/0,
  ufs speed 55/0, all-stage 9/0, dcs bright 1007/0, chooser 30/0 and 75/0 with the A0 FDT, lz4 5/0 and 68/0 with
  the real kernel, el2 mmu 12/0, chooser-ios 50/0, test_dcs_quiesce 0 failed. Receipts: `receipts/`.
- ARM64 (r0 `shim.elf`):
  - present: T `tgl_chooser_run`, `tgl_chooser_ios_{admit,layout,action,initial_sel}`, `tgl_dcsm_{begin,run,
    guarded,present,release,finish,refuse}`, `tgl_dcs_{run,guarded}`, `loader_boot`, `tegu_el_drop_and_jump`,
    `tgl_fc_entry`, `keys_poll`, `keys_init`; R `tgl_chooser_picked_ios`;
  - absent: `tgl_dcs_release` and `tgl_dcs_present`;
  - no undefined symbols and no ABS64 relocations;
  - `tgl_dcsm_release` holds all five quiesce constants, and the iOS `tgl_dcs_run` has no GPCSR.

## 5. Persistence: normal power-on shows the menu, Android stays safe

Facts this rests on:

- **physical:** slot b active and successful; Magisk on `init_boot_b`; bootloader unlocked; `fastboot boot` of
  stock-header chooser images works (r3..r11).
- **source/A0:** `boot_b` is a 64 MiB partition, and A0's `truth/boot_b.img` is the whole partition (67,108,864 B,
  sha256 3635317e…20f5). `boot_a` holds a **different, older build** (b51511a2…). `super` holds only slot-b
  logical partitions.

### 5.1 Option A: `fastboot boot` only, stock untouched (now, and for every proof step)

- **Change:** none on disk.
- **Rollback:** none needed; a reboot without USB boots stock Android.
- **Brick risk:** none from this lane. `fastboot boot` writes nothing. The only persistent bootloader state is
  force-fastboot, which the boot tooling already manages (GOAL.md section 3).
- **Cost:** every iOS boot needs the PC. It is not dual boot for the owner.

### 5.2 Option B: chooser in `boot_b` (recommended end state = GOAL A8)

- **Change:** one attended write. The owner runs `fastboot flash boot_b research/images/<installable chooser-ios>/boot.img`.
  The image is 67,108,864 B, exactly the partition, and its stock vbmeta is transplanted.
- **Preconditions** (all attended, read-only except the flash):
  1. C1–C4 in section 6 have passed with this exact sha.
  2. Re-read today's `boot_b` on the phone:
     `adb exec-out su -c 'dd if=/dev/block/by-name/boot_b bs=4M' | sha256sum` must equal 3635317e…20f5, which
     proves the rollback file is today's partition.
  3. Check `fastboot getvar current-slot` = b, `slot-successful:b` = yes, `slot-retry-count:b`, and
     `fastboot oem force-fastboot` (recorded).
  4. P0 below: the hardware key combo reaches fastboot with nothing connected.
  5. Automatic system updates off; Magisk not told to "install to inactive slot".
- **Verify after:** read back `boot_b` (same dd) = the chooser image sha. Cold boot → menu → Android by timeout →
  return check. Cold boot → Vol-Down → iOS → Home → return check. Then GOAL A8's ten alternating cold boots and the
  interrupted-boot test.
- **Rollback (exact):** `fastboot flash boot_b research/ios26-dualboot-r8/truth/boot_b.img` (sha256
  3635317e93f67de2e6e75e38f892fe8604008bccd9717a369a590b7a35ce20f5), then `fastboot reboot` and the return check.
  Fastboot is reached by `adb reboot bootloader`, or with the phone off by Vol-Down + Power. ABL handles that
  before it reads `boot_b`.
- **What could brick, and why it does not:**
  - *Chooser hangs or resets before Android.* The watchdogs stay armed and patted, so a hang resets. The phone
    bootloops on slot b. Slot b is already marked successful, so ABL does not count down (inference from AOSP
    bootctrl; P0 records the getvars). Vol-Down + Power still reaches fastboot because ABL lives on its own
    partitions, so the rollback command works. **Not a brick.**
  - *Power loss during the flash.* `boot_b` is half-written and ABL cannot boot slot b. It may try slot a: an older
    build whose `super` has no `_a` logical partitions, so it fails. It lands in fastboot. Reflash. **Not a brick**,
    since ABL and the bootloader partitions are untouched.
  - *iOS boots consume the retry counter.* They do not touch slot metadata, and slot b stays successful. To verify,
    record `slot-retry-count:b` before and after an installed iOS boot (getvar, read-only).
  - *KeyMint / `/data` unlock.* The bytes are the r3+ contract (stock header, stock vbmeta), which unlocked `/data`
    on every fastboot boot. A flashed partition gives ABL the same hash mismatch, which an unlocked bootloader
    tolerates; Magisk's init_boot already runs this way (inference). The first installed Android boot's return
    check proves it.
  - *An Android failure path writes `misc` and the phone lands in recovery (seen before).* Choose "Try again",
    **never** "Factory data reset".
  - **Real brick risks, none taken:**
    - `fastboot flashing lock` with a non-stock `boot_b`: never run it.
    - Flashing `abl`, `bootloader`, `bl_*`, `vbmeta*`, `init_boot*`, `vendor_boot*` or the GPT: never part of this
      plan.
    - An OTA or bootloader update rewrites the GPT and drops `ios_*`: updates off, as since A6.

### 5.3 Option C: chooser in the inactive slot `boot_a` + `set_active a`, A/B fallback to b (rejected)

- **What happens:** ABL on slot a assembles `init_boot_a` (not Magisk), `vendor_boot_a`, `dtbo_a` and `vbmeta_a`,
  and Android would mount `_a` logical partitions that `super` does not hold. The chooser's Android branch would
  chain the slot-b kernel against slot-a ramdisks and modules, so Android **cannot** boot from slot a. "Android" in
  this option only means the ABL fallback after slot a's retries run out. Every iOS boot also counts down slot a's
  retries, because Android never marks slot a successful. After about 7 boots ABL marks it unbootable and the menu
  vanishes (safe, but it decays).
- **Extra risks:** `set_active` writes slot metadata (attended-only under GOAL). Android booted after a fallback
  might also see a "failed update" state. The ABL fallback order and count on this bootloader are unverified.
- **Rollback:** `fastboot set_active b` and `fastboot flash boot_a research/ios26-dualboot-r8/truth/boot_a.img`
  (b51511a2b2c35afc13e13ef933e871e6805799eaa1ef97291746ad0ed20ea4a2).
- **Brick risk:** low, since slot b is untouched. But the option does not deliver "the menu picks Android" at all.
  **Rejected.**

### 5.4 Other mechanisms considered

- **Android-side trigger** (Android reboots into iOS via kexec or a one-shot flag): it still needs a persisted
  chooser, the Pixel GKI kexec status is unknown, and it adds an Android-side component. Rejected.
- **The payload in storage** (1.2): changes how the iOS payload is carried, not where the chooser lives. It
  composes with Option B and shrinks the image to the proven size.

## 6. Attended boots that prove each step (all `fastboot boot`, bare, ANDROID_SERIAL set, return check after each)

One change per image. Run the next only if the previous one passed. Names are proposals; images are built by the
phone owner on the Mac with `chooser_ios_image.py image … --ios-image research/images/a7-ios-system-r2` (or the
current A7-class image), then `check`.

| Step | Image | Change | Proves | Discriminators (expected) | Stop |
| --- | --- | --- | --- | --- | --- |
| **P0** | none | – | the recovery path for Option B | phone off, Vol-Down+Power → fastboot screen; `getvar current-slot` b, `slot-successful:b` yes, `slot-retry-count:b` recorded; `fastboot reboot` → Android | no fastboot screen: no A8 |
| **C1** | chooser-ios-r1 (A7 payload, no keys, default Android) | r11 + embedded XNU payload + admission | ABL loads the 48.6 MB blob (19 MB above anything proven); admission passes on real ABL state; menu shows a **live iOS tile**; timeout → Android exactly as r11 | owner sees menu, iOS tile not dimmed; boot_completed ≈ 42 s; kernel 0xc9c00000; return check PASS | no menu, reset loop, iOS tile dimmed (admission refused: capture stamps 0x00bf via a forced-park variant), Android fails |
| **C2** | chooser-ios-r1-ios (= C1 + `--default-ios`) | countdown ends on iOS | the handback: r11 release, MMU off, then the A7 path **after** a release (USB console, UFS ladder, second DCS ladder, admission, EL drop), XNU from ios_system to Home | chooser stamps 0x00bf ADMIT/RELEASE/MMU_OFF/HANDBACK DONE and 0x00ce RELEASE DONE in the ramdump; shim stamps as A7 (DCS stage DONE, EL_DROP DONE); `blazer-ufs: "ios_system" on LUN 0 … read only`, `rooting on ufsroot0`; Home on the panel within ≈ 10 min (deadline 1800) | any chooser refusal stamp; DCS ladder refusal after release (new risk; split C2a = same with `TGL_ALL_DCS` off to isolate it, headless); `global bring-up deadline` (the chooser's ≈ 10–15 s count toward the shim's 90 s: measure, see 7); any panic but the deadline |
| **C3** | chooser-ios-r2 (= C1 + `--keys`) | volume keys via keys_laguna | only after the keys lane's own physical test. Two boots: no press → Android; Vol-Down → iOS (Home) | KEY / KEYS_DB stamps; the selection ring moves; result per press | wrong entry; any key-read SError |
| **C4** | chooser-ios-r3 (installable: keys, default Android) | none vs C3 except the manifest's `installable=true` | the exact bytes A8 would flash: Android by timeout, iOS by Vol-Down, Android by Vol-Up | as C1 and C2 | any difference from C1–C3 |
| **A8** | the C4 sha | attended `fastboot flash boot_b` (section 5.2) | persistence | readback sha; cold boots per 5.2; GOAL A8 list | any failed return check: roll back |

Every step's rollback is a reboot. With force-fastboot ON (bootios/run-attempt re-arm it), the phone parks in
fastboot after the deadline or PSCI reset. Then `fastboot oem force-fastboot off`, `fastboot reboot`, and the
return check.

## 7. Open risks and what settles them

- **ABL kernel size** (C1). Fallback: lz4-compress the payload inside the image (the shim has the decoder; this
  needs a staging buffer and the same `tgl_payload_validate`), or the storage route of 1.2.
- **Second DCS ladder after a release** (C2). Fallback: C2a isolates it; option "keep lit" in section 3.
- **The 90 s global bring-up deadline** (`bringup_gate`, `tgl_stamp_over_deadline(90)`) also counts the chooser's
  time (map, csum, menu ladder, 5 s, release) on top of the A7 shim's time. A miss resets cleanly. If C2 shows
  it, the owner of `stamp.c` decides between crediting the chooser time and skipping the second `con_clear`. Not
  changed here.
- **The FDT the iOS path sees** is now ABL's normal-boot tree: the real initrd at 0x86000000 (38 MB) and the stock
  bootargs, instead of the iOS image's 100-byte ramdisk. Host admission passes on the A0 tree. `DHO` flags come
  from bootargs (`tgl_fdt_display_bootargs`); the stock line unlocks nothing, which is the default path (source).
  C2 records them.
- **Stamp decoding:** `tools/chooser_stamps.py` does not know 0x00bf yet. `TGL_STAGE_CHOOSER_MENU` ENTER now
  carries `ios_available<<32 | sel<<33` above the timeout. Both belong to the decoder's owner.
- **The keys lane's interface** (`keys_laguna.h`) is in progress. `chooser_ios.c` uses `keys_init`/`keys_poll`
  as the keys lane's `chooser.c` hunk does. If that API changes, only `cios_keys*` change.
