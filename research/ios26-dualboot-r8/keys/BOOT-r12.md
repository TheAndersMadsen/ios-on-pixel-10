# chooser-v1-r12: attended volume-key boot (owner present, one `fastboot boot`)

Status 2026-11-03: **host only.** The image is built and checked on m1box. It has not been booted. Nothing here
has run on the phone or in QEMU.

## Image

- `research/images/chooser-v1-r12/boot.img` sha256 **bccd5cf013af07179b8a37d374ebf051f3cdabebbcd7b44d2a87405891d04870**
  (67108864 B, stock vbmeta transplanted as in r11: 2368 B, sha256 36ac3c0c…f217, the same as r11).
- Switches: r11's (`--mmu --ui --display --quiesce`, `--fdt truth/fdt.dtb`, stock boot_b 3635317e…20f5)
  **plus `--keys --keys-poll`.** `--keys-poll` requires `--keys` (KEYS.md 5a), and r11 was built without `--keys`. So r12
  adds both key gates: r8's start check and raw reads (`TGL_CHOOSER_KEYS`) and the debounce (`TGL_KEYS_POLL`,
  `TGL_CHOOSER_KEYS_POLL`, `keys_laguna.c`).
- Build:
  `LLVM=~/.local/share/hackios-host/llvm/bin TGL_TOOLCHAIN=llvm python3 -I tools/chooser_image.py image chooser-v1-r12 --stock-kernel research/ios26-dualboot-r8/truth/boot_b.img --stock-kernel-sha 3635317e93f67de2e6e75e38f892fe8604008bccd9717a369a590b7a35ce20f5 --fdt research/ios26-dualboot-r8/truth/fdt.dtb --mmu --ui --display --quiesce --keys --keys-poll`.
  `chooser_image.py check research/images/chooser-v1-r12` returns OK. Host tests: lz4 68/0, chooser 75/0, el2 mmu 15/0, menu
  band-vs-full 0 px, quiesce 62/0 (`host-tests.txt`).
- ARM64 (`arm64-symbols.txt`): T `keys_init` 0x21c3c, T `keys_poll` 0x21c80, T `keys_raw_levels` 0x21f80,
  t `chooser_keys_db` 0x19e70, t `chooser_keys_start` 0x19da4. There are no undefined symbols. `release-disasm.txt` has all five quiesce
  marks with the same counts as r11 (`#0xef9, lsl #16` 2, `#0x107c` 2, `#0xee8, lsl #16` 3, `#-0xe001` 2, `#0xfff1, lsl #16` 2).
- Diff against r11 (`r12-diff/`):
  - The control `chooser-v1-r12ctl-nokeys` (r11's switches, today's tree, ffbfbc5b…4c57) against r11's `shim.elf`: the function set
    is the same, 274 = 274. Every changed instruction is a `mov/movk` of the per-build stamp nonce or UFS epoch (0 other lines). The 14
    changed .rodata bytes are the UFS record nonce, and .data is identical (`r11-vs-ctl-elf.txt`). Today's shim with r11's switches is therefore r11.
  - Control against r12, per object (`ctl-vs-r12-objects.txt`): `keys_laguna.o` is new. `chooser.o` differs. `stamp.o` and
    `tgl_ufs_route.o` differ only in nonce `mov/movk`. All 23 other objects are identical, including `tgl_dcs.o`, `menu_ui.o` and `shim.o`.
  - `chooser.c` preprocessed with fixed nonces, control flags against r12 flags (`chooser-preprocessed-ctl-vs-r12.diff`):
    the diff has 79 added lines and 0 removed. They are the `probe.h`/`keys_laguna.h` declarations, `chooser_keys`, `chooser_keys_start` and
    `chooser_keys_db`, and the hook block before the menu loop. Nothing else in the chooser changes.

## What the panel shows (host render of the shim's own `menu_ui.c`, `r12-panel/*.png`, `render_states.c`)

The menu is the r11 menu. On the phone `ios_available` is 0, so the iOS tile is always dimmed and reads "Not installed yet".
The countdown pill **always says "Starting Android in N"**, even when the ring is on iOS.
That is correct for this build: with no iOS root, picking iOS falls back to Android (`TGL_WHY_NO_IOS`).

| Moment | Ring | Pill | Render |
| --- | --- | --- | --- |
| Menu appears | white ring around **Android**, Android label bright | Starting Android in 5 | `0-start.png` |
| **Vol Down** (one press) | ring jumps to the **iOS** tile (still dimmed), Android label dims | Starting Android in max(left, 3) | `1-voldown.png` |
| **Vol Up** (one press) | ring jumps back to **Android** | Starting Android in max(left, 3) | `2-volup.png` |
| No input | ring stays where it is | counts 5, 4, 3, 2, 1 once a second | `3-timeout-near.png` |
| Timeout | menu disappears, panel goes dark (display handed back), then Android boots | n/a | n/a |

Timing (`chooser.h`, `tgl_chooser_menu_step`):
- The menu runs for 5 s (`TGL_CHOOSER_TIMEOUT_MS`).
- A press sets the deadline to **max(current deadline, press + 3 s)**
  (`TGL_CHOOSER_KEY_GRACE_MS`). A press in the first 2 s therefore does not change the number. A press later than that
  lifts it to 3. KEYS.md 5c ("countdown restarts at 3 s") is only true for presses after 2 s.
- The ring redraws as soon as the selection changes.
- A press that does not change the selection (Vol Up on Android, Vol Down on iOS) does not move the ring. Only the number may change, at the next 1 s redraw.
- Both keys together is a chord and is ignored.
- The debounce is 20 ms (`KEYS_DEBOUNCE_MS`), so a quick tap of about 0.1 s counts as one press.

## Attended steps (owner present; this is the only device work)

Precondition: the phone runs Android (slot b), `adb devices` shows it, and `ANDROID_SERIAL` is set. Nothing is flashed.
Slots, bootloader, partitions and backups are untouched. Force-fastboot is on (as for r11, `ff.txt`).

1. `adb reboot bootloader`, then wait for `fastboot devices`.
2. `fastboot boot research/images/chooser-v1-r12/boot.img` (expect `Sending 'boot.img' (65536 KB) OKAY`, `Booting OKAY`).
   Write down the wall-clock time.
3. **Keep your hands off both volume keys until the menu is on the panel.** If a key is held when the menu starts,
   r8's start check turns the keys off for the whole boot (`chooser_keys_start`: both pads must idle high).
4. The menu comes up with the ring on Android and "Starting Android in 5". **Within about 2 s**, press and release
   **Volume Down** once. Expected: the ring jumps to the dimmed iOS tile at once, and the pill still reads "Starting Android in …".
5. Press and release **Volume Up** once. Expected: the ring jumps back to Android.
6. Optional, in the same run: a quick tap (about 0.1 s) of Volume Down. Expected: the ring moves exactly once. Each press extends the
   countdown to at least 3 s, so the owner has time for steps 4 to 6.
7. Hands off. The countdown runs to 0, the menu disappears and the panel goes dark briefly. Android then boots as usual.
   Whatever the ring showed, Android is the outcome (`ios_entry=False`). With the ring on iOS, the stamped reason is NO_IOS.
8. Return check (Android, about 42 s after `fastboot boot` in r11-t1, kernel 0xc9c00000):
   `bash research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/chooser-v1-r12-t1/android`
   gives verdict PASS, `kernel_code_base` 0xc9c00000 (the chain-loaded stock kernel).
9. Back to a normal boot (as in r11-t1): `adb reboot bootloader`, `fastboot oem force-fastboot off`, `fastboot reboot`, then
   `bash research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/chooser-v1-r12-t1/return-after`,
   which gives PASS with kernel 0x80000000.

## Verdict rules

- **PASS:** each press moves the ring exactly once in the expected direction, and the tap moves it once. The ring never moves without a
  press, and the step 8 return check passes.
- **Ring never moves, countdown runs out normally, Android boots:** the keys are off. Either the start check refused (a key
  held or a pad not idle high) or `KEYS_FAULT` latched. The panel cannot tell these apart, and shim stamps 0x00cd, 0x00c4 and 0x00cf are not
  readable after a successful chain (r11-t1). The next step is a separate decision (a ramdump after a deliberate refusal,
  `tools/chooser_stamps.py`). Do not retry the same image unchanged.
- **Ring moves twice per press, or moves without a press:** debounce failure. FAIL, and record what was seen.
- **Panel stays dark, or the phone parks in fastboot / resets:** a regression against r11 (display or SError path). Force-fastboot
  parks it, so stop: capture, `fastboot oem force-fastboot off`, `fastboot reboot`, return check. Do not retry unchanged.
