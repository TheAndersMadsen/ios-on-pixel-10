# chooser-ios-r3: the iOS branch from a cold power-on (installed boot_b)

Status 2026-11-03: **host-built and checked on m1box only. Not booted, not flashed, and nothing here touched the phone.**
Labels: **physical** (quoted receipts), **source**, **host** (m1box tests), **ARM64** (compiled objects / the linked shim), **inference**.
Receipts: `receipts/r3/`. This supersedes BOOT-r2.md's C4 ("no separate r3 image"): r2 cannot be the installed image.

## 1. Evidence (physical)

- `chooser-ios-r2` (cab9d96e…f978) is flashed to boot_b. A cold power-on shows the menu, Android boots by timeout and the volume keys work.
- Picking iOS from the installed menu ends the boot almost at once: the bootloader shows red "Preparing for ram dump…" and reboots.
  The same bytes worked with `fastboot boot` (C3a: iOS reached Home). In that case fastboot was running the USB controller just before.
- Ramdump `research/laguna-usb-fix/attempts/20261103-193247-installed-ios-crash/kernel.log`,
  `python3 tools/decode-shim-stamps.py --dump-base 0x95200000 <kernel.log>`: nonce 0x5035f820cf598992 (= r2's `stamp_nonce`), 31 stamps, reason in-progress.
  The menu with key presses (0x00cf), the iOS branch (0x00bf ADMIT…HANDBACK), console-init, disp-record, disp-gate, console-paint-done (8150.5 ms),
  wdt-pat DONE (8155.9 ms), then **#30 usb-warm ENTER (8164.8 ms) is the last stamp**. No FAULT stamp, no later stage.

## 2. Cause (source + physical; mechanism partly inference)

`shim.c` step 6 calls `tgl_usb_console_start` (`tgl_usb_console.c:142`). After the usb-warm ENTER stamp (`:162`), its first access is
`probe_read32(0x0c450000)` (`:168`, the `usbcs_host_cfg_csr` of `usb3@c450000`). The next stamp in the source is `usb-pwr` with that read's
value (`:183`), and it never appears. So the boot ended **on the first USB register read**, before the warm/cold verdict.
The vendor FDT puts that block in `hsio_n_usb_psw_pd`/`hsio_n_usb_pd` (SSWRP 0x17, CPM-managed). Its clocks are `hsion_*` LPCM votes
(lpcm-id 5) and its resets come from `cpm_rst` (truth/fdt.dts ~30471, ~31698, ~2896, ~32027). On a cold power-on ABL never starts fastboot, so
nothing has powered or clocked the block. `probe_read32` only recovers from a synchronous abort, and none arrived. **Inference:** the read either
stalled on the interconnect or raised an error that firmware handled (the bootloader's ramdump screen). Both are consistent with "almost at once" and
with no shim fault stamp.

Physical, not inference: the fastboot path is warm. The warm probe exists because ABL leaves the controller running there (C2/C3a stamps).

## 3. Inherited-state assumptions after the chooser's iOS pick

| After the pick | Cold power-on vs `fastboot boot` | Evidence | r3 |
| --- | --- | --- | --- |
| **USB console** (shim step 6) | **Differs.** Warm only after fastboot. The first read ends a cold boot. | physical dump above; `tgl_usb_console.c:162-186` | **removed** (`--cold-safe`) |
| **Payload-admission USB drain** (shim step 7, `shim.c` 2nd `TGL_USB_DISABLE` gate) | Would touch USB only if the console runs (`laguna_usb_running()` is a RAM flag) | source `laguna_usb.c:915-929`, `tgl_usb_console.c:292-312` | compiled out |
| `loader_boot` / `reset()` USB service calls | RAM-only when the console never started: `tgl_usb_console_service` returns on `!laguna_usb_running()` | source; ARM64: the cold `shim.o` calls only `tgl_usb_console_service` | unchanged |
| **XNU `blazer_usbcon=1`** (on the iOS line, payload e28b35f7) | It reads the controller only after RAM stamps show the shim's DMA ADMIT + EP0 READY. Without them it refuses before any DWC3 read. | source `research/ios26-release-r1/work/xnu/osfmk/arm64/blazer_usbcon.c:160-197`; ARM64: the payload holds the refusal strings (`shim's gadget didn't come up`, `no shim stamps`) | unchanged (refuses cleanly, inference until booted) |
| **Watchdog quiesce** before XNU | Needed in both cases: the third WDT bites about 9 s after the last pat | source `shim.c` comment, v39-v43 history | **kept**. The old `TGL_USB_DISABLE` dropped it (see 4) |
| UFS route (`tgl_ufs_route`) | ABL reads UFS on both paths (it loads boot_b from UFS on a cold power-on). The route attests the three `psm_status_*` registers from the UFS DT node before touching pads (`tgl_ufs_route.c:94-101`, `tgl_ufs_link.c:513-515`). The whole ladder is fault-guarded (`shim.c` 6.5). A refusal falls back to the recovery line; it does not end the boot. | source; physical only on the fastboot path | unchanged. **Not proven cold** (inference: fail-closed, no park) |
| Display: console, DCS ladder after the menu's release | The menu, console init, disp-record/gate and console-paint all completed cold. The DCS ladder starts from the chooser's release, which is the same state on both paths. | physical: the cold dump stamps up to console-paint-done; menu seen | unchanged. Ladder **not proven cold** (inference) |
| Clocks/CPU (fastcore), keys, admission/layout | Same ABL-set state on both paths. Keys and admission ran cold (stamps 0x00cf, 0x00bf). | physical: the cold dump | unchanged |
| XNU drivers (touch, battery, display, UFS) | Proven only after `fastboot boot`; no cold evidence | none cold | unchanged. The cold boot of r3 is their first cold run |

The cold power-on FDT and kernel cmdline match the fastboot ones (attempts `chooser-ios-r2-c1` vs `install-boot_b-cold-android`: only the
secretkeeper key, UFS phy-cal-data and brightness differ). Bootconfig differs (`androidboot.vbmeta.boot.digest` only on a flash boot; `bootreason`).

## 4. Fix

**Preferred runtime check: not available with vendor evidence, so not used.** The stock driver has no MMIO status for this block. The only state query
in `google-modules/soc/rdo/power-controller/power_controller_main.c:428-461` is `LPB_CMD_SSWRP_STATE_GET` over the CPM mailbox. It reports SSWRP **power**
only, not the LPCM clock votes or resets, and it would be a new mailbox protocol on the iOS path. A malformed LPB frame already ended a boot on a CPM
assert (r9/r10, `lpb.c:676`). UFS differs: its DT node carries `psm_status_*` registers, which the route reads. A "came by fastboot" guess from bootconfig
is an inference about ABL, not hardware state, so it is also not used.

**Fallback, implemented: the installable image's shim is built with `TGL_USB_DISABLE`.**

- `shim/shim.c`: under `TGL_USB_DISABLE`, step 6 now stamps **usb-warm REFUSED, arg 0x555342534b495030** (ASCII `USBSKIP0`). It prints
  `USB: disabled at build time (cold-safe, no USB MMIO)` and **still runs the pre-handoff watchdog quiesce**. Before r3, that quiesce sat inside the
  `#ifndef TGL_USB_DISABLE` block, so a USB-disabled shim would have handed XNU an armed watchdog (ARM64: HEAD's `-DTGL_USB_DISABLE` `shim.o` has no
  `wdt_quiesce_late` call; r3's has one, `receipts/r3/object-identity.txt`). `bringup_gate("post-console"/"post-usb")` run in both builds.
  The default (USB console) build is unchanged: **ARM64, `shim.c` with r2's cflags, `.text/.rodata/.data` identical before and after.**
- `tools/chooser_ios_image.py --cold-safe`: adds `-DTGL_USB_DISABLE=1`. It records `cold_safe`/`usb_console` and the linked USB call graph
  (`usb-calls.txt`). It refuses the build unless the linked shim (whole `llvm-objdump -d`) reaches `tgl_usb_console_start`, `tgl_usb_console_wait`,
  `laguna_usb_start` and `laguna_usb_board_resume` from no function other than those themselves, and `shim_main` still calls `wdt_quiesce_late`.
  A console build must start the console from `shim_main`. **`installable` now requires `--cold-safe`**, and `check` refuses a manifest recorded
  installable without it. chooser-ios-r2 now fails `check` with that message (intended: do not re-flash it); r2-ios still checks OK.
- `tools/image_tool.py` is not changed: chooser images build their own shim, and image_tool images are `fastboot boot` only.
- Kept: every non-installable image (`--default-ios`, image_tool's A7 line) keeps the USB console on the `fastboot boot` dev path.
  The installable bytes must be the bytes tested by `fastboot boot` (C4 rule), so r3 has no USB console on either path.

## 5. chooser-ios-r3 (m1box, clang/LLD 23.1.4, `TGL_TOOLCHAIN=llvm`, tree 6618ef2 + the three files in `receipts/r3/SOURCES.sha256`)

`LLVM=~/.local/share/hackios-host/llvm/bin TGL_TOOLCHAIN=llvm python3 -I tools/chooser_ios_image.py image chooser-ios-r3 --ios-image research/images/a7-ios-system-r3 --stock-kernel research/ios26-dualboot-r8/truth/boot_b.img --stock-kernel-sha 3635317e93f67de2e6e75e38f892fe8604008bccd9717a369a590b7a35ce20f5 --fdt research/ios26-dualboot-r8/truth/fdt.dtb --keys --cold-safe`
(r2's recipe plus `--cold-safe`).

| | |
| --- | --- |
| boot.img | `3d11da924951a6df91094cb4f273c976890909062530f6400d8297ef6501e15e` (67,108,864 B), default Android, **installable, cold-safe** |
| kernel.bin | `dd270910bc2135eaab224962cf1308465401de4f5b996d155f15f5fa49ea6872` (49,134,064 B: the same size and `_end` as r2) |
| payload | `e28b35f7…5aab` (a7-ios-system-r3, = r2) · stock lz4 `a54c3b3d…` (= r2) · vbmeta `36ac3c0c…f217` (= r2) · stamp nonce `0x56a5c6baa495b7c6` |

The manifest differs from r2 only in name, cflags (`+ -DTGL_USB_DISABLE=1`), `cold_safe`/`usb_console`/`usb_calls`, nonce, shim tree, tool hashes and the
resulting image/kernel hashes. Budget, layout, payload, segment, text identity and tests are identical.
**ARM64, r2 vs r3 shim (`receipts/r3/r2-vs-r3-functions.txt`, normalised):** 323 of 325 functions identical, and no function added or removed. `shim_main`
differs. Its call multiset loses `tgl_usb_console_start`, `laguna_usb_running`, `con_hex2`, `laguna_usb_transfer_active` and 2× `tgl_usb_console_wait`.
It gains one `tgl_stamp` (USBSKIP0), and one `bringup_gate` call is now inlined (`tgl_stamp_over_deadline` + `tgl_stamp_reason`)
(`shim-main-calls.txt`). `tgl_stamp_boot_us` differs only by a trailing alignment `udf`. The linked cold path
(`shim-main-cold-path.txt`) is `tgl_stamp(0x23, REFUSED, USBSKIP0)`, the quiesce ENTER stamp, then `bl wdt_quiesce_late`.
r2-ios vs r3 adds only r2's known `tgl_chooser_run` 8-instruction default/nonce difference.
`usb-calls.txt`: the only edges are `tgl_usb_console_start` → `laguna_usb_board_resume`, `laguna_usb_start` (linked, never called).

Tests (host, m1box, in r3's build; `receipts/r3/`): chooser-ios 74/0 on the A0 FDT and the real payload (admission OK, Android at 0xc9c00000),
lz4 5/0 + 68/0, chooser 44/0 + 89/0, el2 mmu 12/0, ufs route 87/0 (20/20 mutants), ufs speed 55/0 (21/21), all-stage 9/0 (14/14),
dcs bright 1007/0, fast-start 40/0, quiesce 62/0, menu band shadow 41/0, chooser-ios tool 16/0 (4 new: installable needs cold-safe, the flag,
linked-USB check and refusals), `shim/test_keys.py` PASS, `tools/test_chooser_image.py` 10 OK. ARM64: no undefined symbols, every WANT_T/KEYS_T symbol,
the r13 loop and the quiesce constants checked by the build. `check`: `OK chooser-ios-r3 … installable cold-safe 3d11da92…`.

## 6. Tests (owner-attended; the coordinator runs them, nothing here was run)

A `fastboot boot` cannot make USB cold, because the image itself arrives over fastboot USB. But r3 never touches USB in either case, so the `fastboot boot`
test covers r3's whole iOS path except ABL's cold-boot state. Only a cold power-on covers that.

**T1, `fastboot boot` r3 (no flash; owner pre-approved temporary boot).** As BOOT-r2.md C3a with `research/images/chooser-ios-r3/boot.img`:
Vol Down → iOS → Home. Pass: Home on the panel. A ramdump (300 s deadline) decodes with r3's nonce 0x56a5c6baa495b7c6:
`… wdt-pat DONE, usb-warm REFUSED 0x555342534b495030, wdt-quiesce ENTER/DONE, UFS …, EL drop`, with no usb-pwr/preflight/cpm stamps. The XNU log says
`blazer-usbcon: refused: shim's gadget didn't come up`. Expect no USB console during the shim and no usbcon device. The shim no longer waits for a host
(up to 8 s), so XNU may start earlier. Then C1 (hands off → Android, kernel 0xc9c00000) and the return check.
**Stop:** any reset before Home, or a usb-* stamp after usb-warm REFUSED.

**T2, install (destructive; needs the owner's explicit confirmation, DESIGN.md 5.2).** Only after T1 passes:
`python3 -I tools/chooser_ios_image.py check research/images/chooser-ios-r3` and `sha256sum` must show 3d11da92…e15e. Then
`fastboot flash boot_b research/images/chooser-ios-r3/boot.img` and read it back. Cold power-on (force-fastboot off): C1 Android by timeout and C3b,
then **C3a from cold: Vol Down → iOS → Home**. A cold-boot ramdump must show the same trail as T1. Rollback is unchanged:
`fastboot flash boot_b research/ios26-dualboot-r8/truth/boot_b.img` (3635317e…).
**Stop / report:** a ramdump whose last stamp is in the UFS ladder or the DCS ladder means another cold-only difference (section 3, "not proven cold").
Decode it, and do not retry it unchanged.

## 7. NOTES section (for the coordinator)

Replace the Dual boot line's tail with: "iOS from the installed menu faulted at the shim's usb-warm (cold power-on: ABL never powers the USB block; the first
USB read ends the boot). `chooser-ios-r3` (3d11da92…, r2 + `--cold-safe`: no shim USB console, watchdog quiesce kept) host-built; not booted;
`check` now refuses r2 as installable. Next: `fastboot boot` r3 (T1), then flash it with the owner's approval (T2).
`research/ios26-dualboot-r8/chooser-ios/COLD-r3.md`."
