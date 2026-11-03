# chooser-v1-r12 keys: cause, fix (chooser-v1-r13) and diagnostic (chooser-v1-r13-diag)

Status 2026-11-03: **cause found from older physical receipts. The fix and the diagnostic are host-built and checked only.**
Neither image has been booted. No QEMU. Receipts are in `r13/`.

## Physical result being explained

`chooser-v1-r12` (bccd5cf0…, 2026-11-03 16:01, owner present): the menu showed and the owner pressed Vol Down and Vol Up.
The ring never moved. The countdown ran out and Android booted, and the return checks passed. The shim stamps cannot be
read after a successful chain.

## Cause (proven from physical stamps; r12's own stamps are unreadable)

**The menu loop samples the keys only between redraws, and one band redraw takes about 3.97 s on the phone.** For r12 that
means dense sampling only in the first ~1 s of the menu, then one sample at ~5.0 s and one at ~8.9 s. keys_poll's
debounce needs two agreeing samples at least 20 ms apart, so a press after the first second can never register.
A press inside the first second would have moved the ring about 4 s later, after the next redraw.

| Evidence | Kind | What it shows |
| --- | --- | --- |
| r7/r9/r10 stamps (`r13/menu-timing.txt`): `menu ENTER 0x1388` (5000 ms), then `pick DONE after 8940 / 8943 / 8949 ms` | PHYSICAL | The 5 s menu ends at ~8.94 s |
| The same runs' DCS records: 3 `FRAME_STATUS` notes each. Every successful `kick()` writes one (tgl_dcs.c `note(DCS_N_FRAME_STATUS)`) | PHYSICAL | 1 kick in the display ladder plus **only 2 menu presents** in 8.9 s |
| The loop (chooser.c): first redraw at t ≥ 1000 ms, then each redraw starts as soon as the previous one ends. Pick = 1000 + 2 × D = 8940, so **D ≈ 3970 ms** per redraw (draw_band plus present; the present's frame-done wait is capped at 200 ms) | source + PHYSICAL | One redraw ≈ 3.8–4.0 s of drawing |
| `r12-diff/ctl-vs-r12-objects.txt`: `menu_ui.o`, `tgl_dcs.o` and `shim.o` are identical in r11 and r12, and r12's chooser diff adds only the key code. r7/r9/r10 used the same `--mmu --ui --display` path (`cached=1`) | host | r12 runs the same menu loop at the same speed |

Why a redraw is so slow (inference; the diagnostic measures it): `tile()`, `pill()` and `mask_at()` blend over
`row[x]`, so they **read** the framebuffer, and the framebuffer is mapped Normal-NC (`el2_mmu`, `CHOOSER_FB`). On the host
(cached memory) the band costs 11.8 ms and the full frame 20.5 ms, a ratio of 1.7 (`r13/host-band-bench.txt`). On the phone
it is ~3970 ms against 4125 ms for the full frame (`ui DONE full draw 4125 ms`), a ratio of 1.04. The 2.6 M extra
write-only pixels of the full frame cost only ~155 ms, so the band's time goes into the ~0.6 M pixels that read the NC
buffer (~6 µs each).

### Checked and not the cause

| Item | Result | Basis |
| --- | --- | --- |
| Pad mapping, stride, RXDATA, polarity | **Correct.** | PHYSICAL `keys-probe-r1` (attempt 20261102-004645, image efc820cc…). Decoded now (`r13/keys-probe-r1-decode.json`) from its ramdump with its own `decode_probe.py` (copied from the Mac's `research/ios26-stability-r1/keys-probe-r1/tools/`): RXDATA at rest is exactly `0x1` on pads 48/51/52. 18 events alternate `0x0`/`0x1` on pad 52 (Vol Up) and pad 51 (Vol Down) at the owner's one-per-second rhythm, 2169 samples, 0 faults. DMUX (+4) = 0x1 and RXGATE (+0xc) = 0x0 on all three. Same PAs as `keys_laguna.h` (0x052b3010 / 0x052b4010; r12 `chooser_keys_start` builds 0x052b3010, +0x1000) |
| Power domain, clock or pad-config write needed first | **Not needed.** | Same probe: the first pad read (pad 48, K_FIRST) came **before** its LSIO_N `pd_on` and read 0x1. The probe wrote no pad register. The FDT node has no `power-domains` or `clocks`. Caveat: the probe ran ~12–21 s after shim start and the chooser reads at ~7.8 s. r13-diag shows the chooser-time values |
| stock `google_gpio_get` CSR branch | Not taken for these reads in practice. | The excerpt shows that when `pctl+0x2e0` (a CSR base) is non-zero and the pin's CSR index is ≥ 1, registers at or above DMUX's offset (RXDATA included) are read from the CSR base. Whether cpm has one was not settled from code, but the physical probe read the plain path and got correct levels |
| Start check (both pads idle high) | Unlikely to have refused. | The probe's rest value is 0x1 on both. r13 no longer needs it: a pad low at start no longer turns the keys off, because keys_laguna ignores a key until it has been seen released. Faulted or all-ones reads still do |
| 64-garbage latch, guarded-read fault | Unlikely. | The probe saw 0 faults and no 0xffffffff in 2169 samples. The diagnostic shows both |
| Menu consumes keys_poll's result | Yes. | `chooser_keys_db` returns `r & 3`, and `tgl_chooser_menu_step` takes edges of it. Host tests pass |

## Second latent problem, fixed in r13: present cost against the release

DCS record (capacity 1532 entries; `r13/dcs-record-usage.txt`): the display ladder ends at entry 941 in both r9 and r10.
Each menu present costs **~18 entries** (36 for 2). A full release costs **187** on the host fake
(`r13/release-entries-hostfake.txt`), plus one entry per extra TOP-state poll on the phone. `checks()` refuses at
`seq + 8 ≥ 1532`, and a refused release makes the chooser return an error. A once-per-second present (what a fast
redraw would do) would therefore have exhausted the release's room after about 20 presents. The DCS budget is also 25 s
from the display start.

## The fix (chooser-v1-r13, gates `TGL_CHOOSER_KEYS_FIX`, `TGL_MENU_ROW_HOOK`, `TGL_DCS_PRESENT_QUIET`)

1. **Keys sampled during redraws.** `menu_ui.c` calls `tgl_menu_row_hook` once per drawn row (≥ 775 calls per band, host
   test). The chooser hook runs `keys()` (keys_poll) and ORs the held bits. The new pure `tgl_chooser_menu_feed` turns
   a press that started and ended inside a redraw into exactly one press (host tests in `chooser_test.c`).
2. **Band rendered in cached memory.** The band is drawn into the kernel destination (`base`, mapped WB, free until the
   lz4 decode, cleaned by `chain_jump_mmu_off`), then its 775 rows are copied with 64-bit stores only (no NC reads). Host:
   identical pixels to r12's direct redraw for all 20 state pairs (`menu_band_shadow_test.c`, 41 checks).
   ARM64: the copy loop moves 0x510400 → 0xf0510400, 496000 words.
3. **Redraw only on change** (ring position or the countdown number), and **quiet presents**: `tgl_dcs_present` logs only
   its 2 notes. Before every present the chooser reads the record's live entry count (header +44) and presents only
   while it is below 1204, keeping 300 entries plus a margin for the release. A stop is still logged in full.
4. **Menu hard end at 15 s** after it starts, inside the 25 s DCS budget. A press still extends the countdown to at least 3 s.
5. **The start check no longer turns the keys off when a pad is low**, as described above.

Unchanged against r12 after address normalisation (`r13/r12-vs-r13*-functions.txt`): `tgl_dcs_release` (557
instructions), `tgl_dcs_run`, `kick`, `mba`, `lpb_state`, `keys_poll`, `keys_init` and `tgl_menu_draw_band`. **The r11 display
handback is unchanged.** Only `tgl_dcs_present` (quiet) and `chooser_keys_start` (one extra flag) differ.
With r11's and r12's own flags, the edited `chooser.c`, `menu_ui.c` and `tgl_dcs.c` give byte-identical `.text` to HEAD
(`r13/control-r11-r12-flags.txt`).

## The diagnostic (chooser-v1-r13-diag = r13 + `TGL_CHOOSER_KEYS_DIAG`)

A black box at the top of the panel, above the "title" line, with 8 text lines and two squares. It is redrawn when a key
level, the ring or a fault changes (at most every 80 ms) and with each countdown step. It uses stores only.
The menu starts at 12 s; the pill shows 9 until 9 s remain. The hard end is 15 s.

| Line | Shows |
| --- | --- |
| `KEYS DIAG r13  T 4.2` | seconds since the menu started (only advances when the panel is redrawn) |
| `LIVE DN 1  UP 1  ok` | live RXDATA bit 0 of pad 51 / pad 52 (1 idle, 0 pressed, X all ones, - not read); `RDFAULT` if a live read faulted |
| `RAW 00000001 00000001` | the live RXDATA words (Vol Down, Vol Up) |
| `START OK 00000001 00000001` | r8's start check: `OK` both idle high, `LOW` read fine but a pad low (keys still on in r13), `BAD` a faulted or all-ones read (keys off). Then the two start words |
| `POLL ON  RES 000 nofault BAD 0` | keys_poll on/off, its last result (hex: 1 up, 2 down, 200 fault, 100 its own 5 s idle timeout, which the menu ignores, fff none yet), FAULT latch, garbage run |
| `N 1234 RD 567 TICK 8910` | keys_poll clean samples, live diag reads, row-hook calls |
| `HELD -- SEL 0 PRESS 0` | debounced held keys (D, U), ring position (0 Android, 1 iOS), accepted presses |
| `DRAW 123ms FR 7 REC 960` | last band redraw time, presents so far, DCS record entries |
| squares | **left = Vol Down, right = Vol Up**: green = pad high (idle), red = low (pressed), magenta = all ones or a faulted read, grey = never read |

## Images (host-built on m1box, clang 23.1.4, `TGL_TOOLCHAIN=llvm`, tree HEAD 40b2e46 + the changes below)

| Image | boot.img sha256 | Switches |
| --- | --- | --- |
| `research/images/chooser-v1-r13-diag/boot.img` | `2e9a02dc91f24b71faf6225364772058858989208a2b09cd4859249747112eda` | r12's plus `--keys-fix --keys-diag` |
| `research/images/chooser-v1-r13/boot.img` | `2dc72399b1be8ae38ba88b37fe542d642517c74ddded14ac70681005e717b569` | r12's plus `--keys-fix` |

Both are 67108864 B with the stock vbmeta transplanted as in r11/r12, and `chooser_image.py check` returns OK for both. Host tests
(`r13/*-host-tests.txt`): lz4 68/0, chooser 89/0, el2 mmu 15/0, band-vs-full 0 px, quiesce 62/0, band shadow 41/0. There are no
undefined symbols, and the ARM64 symbols are in `r13/*-symbols.txt` (`tgl_chooser_menu_feed`, `chooser_menu_tick`, B
`tgl_menu_row_hook`; diag: `diag_sample`, `diag_line`, `diag_draw`). Build:
`LLVM=~/.local/share/hackios-host/llvm/bin TGL_TOOLCHAIN=llvm python3 -I tools/chooser_image.py image <name> --stock-kernel research/ios26-dualboot-r8/truth/boot_b.img --stock-kernel-sha 3635317e93f67de2e6e75e38f892fe8604008bccd9717a369a590b7a35ce20f5 --fdt research/ios26-dualboot-r8/truth/fdt.dtb --mmu --ui --display --quiesce --keys --keys-poll --keys-fix [--keys-diag]`.
Also passing: `shim/test_keys.py` PASS, `tools/test_chooser_image.py` 10/10, `tools/test_chooser_ios_image.py` 5/0.

**Same bug elsewhere (not changed here):** `shim/chooser_ios.c:433` redraws the band directly into the NC buffer and
samples keys only between redraws, so the iOS chooser will show the same symptom. It should take the same fix.

## Attended diag boot (owner present; one `fastboot boot`, nothing flashed)

Precondition, as for r12: Android on slot b, `adb devices` shows it, `ANDROID_SERIAL` is set, and force-fastboot is on (`ff.txt`).
Have a second phone or camera ready: **a photo of the panel is the best report.**

1. `adb reboot bootloader`, wait for `fastboot devices`.
2. `fastboot boot research/images/chooser-v1-r13-diag/boot.img` (expect `Sending 'boot.img' (65536 KB) OKAY`, `Booting OKAY`).
   Note the time.
3. **Hands off both volume keys until the menu is on the panel** (r9/r10: the display came up 7.8 s after shim entry). A black box with white text and
   two squares is at the top.
4. **Photo 1** right away, hands off. Expected: both squares green, `START OK`, `POLL ON`, `DRAW` well under 1000 ms.
5. **Hold Volume Down for about 2 s**, take **photo 2** while holding, then release. Expected: left square red while held, the
   ring jumps to the iOS tile, `PRESS 1`.
6. **Hold Volume Up for about 2 s**, **photo 3** while holding, release. Expected: right square red, the ring back on Android.
7. Then one quick tap of Volume Down (about 0.1 s). Expected: the ring moves once.
8. Hands off. The menu ends 12 s after it appeared, or 3 s after the last press if that is later, and never later than 15 s. The panel
   goes dark and Android boots (`ios_entry=False`; with the ring on iOS the reason is NO_IOS).
9. Return checks exactly as BOOT-r12 steps 8–9, with attempt directory `research/ios26-dualboot-r8/attempts/chooser-v1-r13-diag-t1/`
   (`android` after the boot, then force-fastboot off, `fastboot reboot`, `return-after`).

What to report: the photos, or else for each moment the colours of the two squares and the `START`, `POLL`, `HELD`/`SEL`/`PRESS` and
`DRAW … FR … REC …` lines. Also whether the ring moved, and roughly when the menu ended.

| Seen | Means | Next |
| --- | --- | --- |
| Squares go red on press, ring follows, `DRAW` < ~500 ms | Fix confirmed, NC-read cause confirmed | Boot `chooser-v1-r13` once as the clean verdict (BOOT-r12 steps, attempt `chooser-v1-r13-t1`) |
| Squares go red, ring follows, `DRAW` ~3000–4000 ms | Keys fixed; the redraw is compute-bound rather than read-bound. The ring lags by a redraw | r13 is usable; making the redraw faster is separate work |
| Squares go red, ring never moves, `POLL OFF` or `START BAD` | Start check refused (fault or all ones at start) | Report the START words |
| Squares go red, `RES 200`/`FAULT`, or `BAD` > 0 | keys_poll latched a fault | Report the RAW words |
| Squares stay green while pressing, `RAW` unchanged | The pads do not change at chooser time (unlike keys-probe-r1 at ~12 s) | Run the Android-side checks below while holding a key; next would be a timed later read |
| Magenta or `RDFAULT` | The read faults at chooser time | Stop and report |
| Panel dark, parks in fastboot, or resets | Regression | Capture, `fastboot oem force-fastboot off`, `fastboot reboot`, return check. Do not retry unchanged |

## Android-side read-only checks (for the coordinator, if the diag is not clear)

Under `adb shell`. Only `su -c cat`/`ls` of debugfs and procfs, plus `getevent`. No writes.

1. `getevent -lp 2>/dev/null | grep -B2 -A12 -i 'gpio[-_]keys'`. Need the device node and that it lists `KEY_VOLUMEDOWN`/`KEY_VOLUMEUP`.
2. `su -c 'cat /sys/kernel/debug/gpio' | grep -i -B3 -A3 'vol\|gpio[-_]keys\|5280000'`. Need the gpiochip base for cpm_pinctrl and the
   lines for volume down/up with in/hi/lo and IRQ.
3. `su -c 'ls /sys/kernel/debug/pinctrl/'`, then for the directory containing `5280000`:
   `su -c 'cat /sys/kernel/debug/pinctrl/<that dir>/pins' | head -3; su -c 'cat /sys/kernel/debug/pinctrl/<that dir>/pins' | grep -E 'XCPM_GPI0|XCPM_GPI1|XCPM_EINT_12'`.
   Need the header line and the three pin lines, **once with hands off and once while the owner holds Volume Down** (repeat holding Volume Up).
   This is the stock driver's own register dump (PARAM DMUX TXDATA RXGATE RXDATA …) and confirms RXDATA with the keys held.
4. `su -c 'cat /sys/kernel/debug/pinctrl/<that dir>/pinmux-pins /sys/kernel/debug/pinctrl/<that dir>/pinconf-pins' | grep -E 'XCPM_GPI1|XCPM_EINT_12'`.
5. `ls /proc/device-tree/gpio_keys/; for k in button-voldn button-volup; do xxd /proc/device-tree/gpio_keys/$k/gpios; done`.
   Need `0440 0033 0001` / `0440 0034 0001` (live DT equals truth/fdt.dtb).
6. `timeout 8 getevent -l /dev/input/eventN` (N from 1) while the owner presses each volume key once. Need the
   `EV_KEY KEY_VOLUMEDOWN DOWN/UP` lines.

## Changed files (not staged; HEAD 40b2e46)

| Path | sha256 |
| --- | --- |
| `shim/chooser.c` | `91a749c2f1412ee11d4e0c84b8bdecf4ea6674d6a12d0aaaeeeb2730040bc114` |
| `shim/chooser.h` | `ec859d4d7fe05f6ae428ad78394abdc2bd7827b5dd9587a529783b1a13cb6726` |
| `shim/chooser_test.c` | `488130da066ac4919b1dfcbe4cbed1ffa84bbf45cbc87e54fd14cc10b9f63b5d` |
| `shim/menu_ui.c` | `2471646c47e79aaba2d83b87fcd27329c1eeb3d67748ec8bf5ae2107211c00e4` |
| `shim/menu_ui.h` | `b3168f3ac886f210e585defda4b6807179f2e20950fd231b4739e92f8c6792ee` |
| `shim/tgl_dcs.c` | `3efe8a9e09a7bffbc7fb9ca05a15197b8fc946fbc73bced8eb720e6e38e4edda` |
| `shim/menu_band_shadow_test.c` (new) | `fd86d3f83afc2fe32219f96310da4ec52f6ba605ee3536c45ac27ab5ef07f170` |
| `tools/chooser_image.py` | `084581d562ec0e3bbdfcb6f2e849b7859f9abdb7b36fa8c6dd64542bfa9405ef` |
| `tools/test_chooser_image.py` | `576efc9b07a234fdede21fe8675f94d770cb7471bf0e1f94cc9f50d794f5461c` |
| `research/ios26-dualboot-r8/keys/DIAG-r13.md` and `keys/r13/` (receipts) | this file; see `r13/` |
