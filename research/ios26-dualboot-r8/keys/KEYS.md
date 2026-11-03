# Chooser volume keys: wiring, register table, test, attended verification

Status 2026-11-03: **host and ARM64 object only.** Nothing here ran on the phone or in QEMU.
Code: `shim/keys_laguna.{h,c}` (gate `TGL_KEYS_POLL`), hook in `shim/chooser.c` (gate `TGL_CHOOSER_KEYS_POLL`,
needs `TGL_CHOOSER_KEYS`). Tests: `shim/keys_laguna_test.c`, `shim/test_keys.py`.

## 1. Wiring evidence

| Source | Kind | What it says |
| --- | --- | --- |
| `truth/fdt.dts` (from `truth/fdt.dtb` sha256 88bb3e4e…415c), node `/gpio_keys` | stock DT | `compatible = "gpio-keys"`. `button-voldn`: `gpios = <0x440 0x33 0x01>`, KEY_VOLUMEDOWN. `button-volup`: `<0x440 0x34 0x01>`, KEY_VOLUMEUP. `button-power`: `<0x440 0x30 0x01>`, KEY_POWER. Flag 1 = GPIO_ACTIVE_LOW. No `debounce-interval`, so Linux uses the gpio-keys default of 5 ms. |
| same file, `cpm_pinctrl: pinctrl@5280000` | stock DT | phandle 0x440, `compatible = "google,lga-cpm-pinctrl"`, `reg = <0 0x5280000 0 0x39000>`, `gpio-ranges = <0x440 0 0 0x39>` (57 pins). `gpio-line-names[48/51/52]` = `PMICM2AP_GSC_PWRON_OD_L`, `VOL_DN_L`, `VOL_UP_L`. The node has no `power-domains` and no `clocks`. |
| same node, pin groups | stock DT | `vol_dn_l`: pins `XCPM_GPI1`, bias-pull-up, input-enable, output-disable. `vol_up_l`: `XCPM_EINT_12`, **bias-disable** (no internal pull), input. `pmicm2ap_gsc_pwron_od_l`: `XCPM_GPI0`, pull-up, input. All three use `function = "cpm_int"`. |
| stock `pinctrl.ko` (sha256 12a0698c…b47f) from `truth/vendor_boot_b.img` (06a40d4c…fe2b), 16K vendor ramdisk | stock binary | `google_gpio_get` reads `base + pin.index * stride + reg2offset(4)` and returns `& 1`. reg2offset[4] = **0x10**, which is RXDATA in the driver's own column order (PARAM DMUX TXDATA RXGATE RXDATA …). For cpm the stride is **0x1000**, npins is 57, and the indices of pins 48/51/52 are 48/51/52 (`XCPM_GPI0`, `XCPM_GPI1`, `XCPM_EINT_12`, which match the DT pin groups). Excerpt: `pinctrl-ko-excerpt.txt`. |
| `research/laguna-usb-fix/attempts/20261102-004645-keys-probe-r1` (image efc820cc…d147) | physical | Summary in `research/journal/HANDOFF-full-20261102.md:44`: "pads read safely, volume keys seen, power not seen". The reads used no CPM request. The receipt's own reader text marks the probe lines stale/unkeyed (`reader.txt:11`), so the only per-key record is the journal line. |
| `research/ios26-release-r1/work/xnu/bsd/dev/hakios.blazer_keys.c` | project source (XNU) | Same pads and the same RXDATA/bit-0 read. Ignores samples where every pad reads 0xffffffff or all three read low ("unclocked block"). |

The keys are therefore plain CPM pinctrl input pads. Polling reads the RXDATA level, so no PMIC/SPMI access
is needed. The `cpm_int` function and `irq-pad-mapping` route these pads to interrupts as well, but the shim
does not use them.

Not established:
- Power (pad 48) has never been seen pressed on the phone. Its line name `PMICM2AP_GSC_PWRON_OD_L` suggests the PMIC
  passes it through the GSC, but that is inference. The chooser hook therefore never reads pad 48 (`want` is the two
  volume keys only).
- Volume Up has `bias-disable`, so the board must pull it up. The idle-high reading comes from keys-probe-r1 and r8's
  start check, not from a schematic.
- `google_gpio_get` takes `google_pinctrl_get_csr_pd` (a power-domain vote) and has a second, CSR-mapped base path
  (`pctl+0x2e0`). For cpm, the DT has no power domain and a single `reg`, so the plain path is the one taken. That
  conclusion comes from the DT. The C of the vote function was not read.

## 2. Register table (read only; the module writes nothing)

| Key | cpm pin | SoC pin | Pad PA | Register | Bit | Pressed | Read by chooser hook |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Power | 48 | XCPM_GPI0 | 0x052b0000 | RXDATA +0x10 = **0x052b0010** | 0 | 0 (active low) | no |
| Volume Down | 51 | XCPM_GPI1 | 0x052b3000 | RXDATA +0x10 = **0x052b3010** | 0 | 0 | yes |
| Volume Up | 52 | XCPM_EINT_12 | 0x052b4000 | RXDATA +0x10 = **0x052b4010** | 0 | 0 | yes |

PA = 0x05280000 (DT reg) + pin * 0x1000 (pinctrl.ko stride) + 0x10 (pinctrl.ko reg2offset[4]). The pins are inside the
DT window, since 56 * 0x1000 + 0x14 < 0x39000. The r8 code (`chooser_keys`, chooser.c) already reads exactly the two
volume words through `probe_read32`.

## 3. Module behaviour (`keys_poll`)

- `keys_init(s, rd, want, now_ms, timeout_ms)`; `keys_poll(s, now_ms)` returns the debounced held bits
  (`KEYS_VOL_UP` 1, `KEYS_VOL_DOWN` 2, `KEYS_POWER` 4; the first two equal chooser.h `TGL_KEY_UP/DOWN`), plus
  `KEYS_TIMEOUT` 0x100 and `KEYS_FAULT` 0x200.
- Reads go only through the injected `rd` (`probe_read32` on the phone, a mock on the host), and only for the keys in `want`.
- Debounce: a level must hold for 20 ms (`KEYS_DEBOUNCE_MS`), timed by the clock rather than by sample count.
- A key held when polling starts, or a pad stuck low, counts as no press until it has been seen released for 20 ms.
- Garbage: 0xffffffff on any pad, or all three pads low when three are read, is ignored and restarts the debounce.
  64 garbage samples in a row latch `KEYS_FAULT`. Two volume keys low together is a chord, not garbage.
- A failed guarded read latches `KEYS_FAULT` at once, and that pad is never read again.
- Timeout: with `timeout_ms` set, `KEYS_TIMEOUT` is reported once nothing has been held or changed for that long, or
  once the module has faulted. The caller then takes the default, Android. Holding a key never times out.
- Chooser hook: `keys_init(..., probe_read32, VOL_UP|VOL_DOWN, now, TGL_CHOOSER_TIMEOUT_MS)` runs only after r8's
  `chooser_keys_start` has accepted the pads (both idle high, no SError). The menu gets only the volume bits; its
  own countdown still decides the timeout. Every change of the result writes stamp **0x00cf**
  (`KEYS_STAGE_DB`, previously unused): arg = result<<48 | raw levels<<40 | bad run<<32 | clean samples, with flag
  REFUSED on a fault. r8's stamps 0x00cd (pad words at start) and 0x00c4 (key bits on change) are unchanged.

## 4. Tests (m1box, 2026-11-03, clang 23.1.4 from ~/.local/share/hackios-host/llvm/bin)

- `python3 -I shim/test_keys.py`: **PASS**, 14/14. It covers:
  - the host test on mocked MMIO with ASan/UBSan, `keys_laguna_test: 120 checks, 0 failures`
  - an AArch64 `keys_laguna.o` with `TGL_KEYS_POLL=1`: it defines T `keys_init`/`keys_poll`/`keys_raw_levels`, has no
    undefined symbols and no ABS64 relocation, and reads only through `blr`. It builds 0x052b0010 (`mov #0x10; movk #0x52b, lsl 16`).
  - with the gate off, the object is empty
  - `chooser.o` with the hook defines `chooser_keys_db` and references `keys_init`/`keys_poll`
  - the hook without `TGL_CHOOSER_KEYS` hits `#error`
  - with the hook gate off, `chooser.o` has no keys_laguna reference
- With the hook gate off, chooser.c `.text` is byte-identical to HEAD 7c3d243 (`-DTGL_CHOOSER=1 -DTGL_CHOOSER_KEYS=1`, cmp of the objcopied `.text`).
- `bash shim/build.sh` with `TGL_TOOLCHAIN=llvm` and the r11 flags plus `-DTGL_CHOOSER_KEYS=1 -DTGL_KEYS_POLL=1
  -DTGL_CHOOSER_KEYS_POLL=1`, with `keys_laguna.c` in `TGL_EXTRA_SRC`. All objects compiled, the ABS64 check passed,
  and `shim.elf`, `Image` and `shim-boot-laguna.img` were linked. `shim.elf` has T `keys_init` 0x21c3c, `keys_poll`
  0x21c80, `keys_raw_levels` 0x21f80 and t `chooser_keys_db` 0x19e70. Host stamp tests passed. build.sh then exited 1
  in `test_ufs_route.py`, because this worktree has no `research/ufs-read-r2/run/decoded.json` (local data, unrelated
  to keys). The chooser host test passes separately (30 checks, 0 failed).
- This is not a chooser boot image. `tools/chooser_image.py` has no switch for the new gate yet (see 5a).

## 5. The attended boot that verifies it (one `fastboot boot`, owner present)

The chooser runs **before** USB init. shim.c:340-342 says the Android branch must run before any console, USB, UFS
or CPM work, so there is no USB console during the menu. r11-t1 also showed that the shim stamps cannot be read after a
successful chain to Android. So the verification is what the owner sees on the panel, plus the Android outcome.
Stamps 0x00cd/0x00c4/0x00cf can only be read from a refusal/reset ramdump
(`python3 -I tools/chooser_stamps.py <attempt>/ramdump/kernel.log`).

a. **Done 2026-11-03:** `--keys-poll` is in `tools/chooser_image.py` (test `tools/test_chooser_image.py`), and chooser-v1-r12 is built.
   Steps, panel renders and the diff against r11 are in `BOOT-r12.md`. Note on 5c: a press sets the countdown to max(left, 3 s), not always 3 s.
   Original plan: build (host). This needs a two-line `--keys-poll` switch in `tools/chooser_image.py`, which belongs to the tools
   owner (the coordinator or agent D):
   `cflags += ' -DTGL_KEYS_POLL=1 -DTGL_CHOOSER_KEYS_POLL=1'` and `src += ' keys_laguna.c'` when `a.keys_poll`; refuse
   it without `--keys`; record `keys='pads 51/52 RXDATA, keys_laguna debounce'` in the manifest. Then:
   `python3 -I tools/chooser_image.py image chooser-v1-r12 --stock-kernel <stock boot_b.img> --stock-kernel-sha 3635317e…20f5 --mmu --ui --display --quiesce --keys --keys-poll`
   followed by `python3 -I tools/chooser_image.py check research/images/chooser-v1-r12`.
b. Owner present, phone in fastboot, `ANDROID_SERIAL` set. Run bare `fastboot boot research/images/chooser-v1-r12/boot.img`.
   This is the only device step. Nothing is flashed, and slots, force-fastboot and bootloader stay as they are.
c. Hands off the keys until the menu shows. The owner then presses **Volume Down** once: the ring moves to iOS ("Not
   installed yet") and the countdown restarts at 3 s. **Volume Up** once moves it back to Android. One run should also
   include a quick tap, about a tenth of a second, which should move the ring once (the debounce is 20 ms).
d. With no further input the menu times out. Android boots either way, because the iOS entry is off and `ios_available=0`.
   Expect boot_completed in about 42 s, kernel 0xc9c00000, then `research/ios26-dualboot-r8/return-check.sh` PASS.
e. PASS means: the ring follows each press exactly once, there is no move without a press, and the Android return check passes.
   If the ring never moves, either r8's start check refused (pads not idle high) or `KEYS_FAULT` latched. Neither shows
   on the panel. The next step for that case is a ramdump capture after a deliberate refusal, a separate decision.
   An SError makes the chooser refuse and reset, and force-fastboot parks the phone.
