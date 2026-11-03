# chg1: charger state under iOS, read only (2026-11-03, HOST + QEMU, not booted)

Image **`a7-ios-system-chg1`**, boot.img **`b2898a105610eb437bec6354f377dfe0aa7a7426cf0cc43f66386ae474facd4a`** (Mac and m1box
`research/images/`). Nothing here has run on the phone. Labels: SOURCE, HOST, ARM64, QEMU, PHYSICAL.

## What it is

- **Charger IC** (SOURCE, FDT): max77779 `max77779chrg@3` on the AP's SPMI master `spmi@53f1000` (SID 3), the same controller
  and code path as the fuel gauge (SID 6, PHYSICAL: `blazer-battery: sample … SOC(89)`). Wireless receiver CPS4041 sits behind the
  max77779's own I2C master (SID 2, 0x30): not touched; a pad shows up through the charger's WCIN input. `REGISTERS.md`.
- **Already in every int1/obs1 kernel** (ARM64 strings of kernel.obs1): `blazer_battery_chg=1` reads 4 status bytes and feeds
  iOS's external/charging flags. No image has ever set it.
- **New (XNU `hk-chg1` ca39cb4 = hk-obs1 2841211 + `xnu-src/0001-hk-chg1.patch` 8fec96dc…):** `blazer_battery_chg=2`, report only.
  Per gauge sample (once a minute) it reads 15 more charger frames and prints one line; what iOS is told is exactly what it is
  without the argument. New `blazer_charger.h` decodes with the vendor driver's get_* steps; it has no value-to-register
  direction. Still one opcode (EXT_REG_READ), compile-time frames, `_Static_assert`ed register set, never CHG_INT/CHG_INT2.
- **No write of any kind.** The write design (limit-only CHGCC) is `CONTROL.md` and needs separate owner approval.

## Evidence

| Class | What | Receipt |
| --- | --- | --- |
| HOST | real `blazer_gauge.c` against a fake SPMI master (W1C IRQ_STATUS, frames recorded): 1,630 checks PASS under ASan/UBSan. chg=0 and chg=3 send no SID 3 frame; chg=1 only 0xb6..0xb9; chg=2 only the 15 named frames; chg=2 publishes the same state as chg=0; a charger frame error leaves the gauge sample and the controller alone; wireless decode; invalid CV code | `receipts/host-tests.txt`, `tests/test_charger.c` |
| HOST | decode == vendor get_* formulas for all 256 codes of CC, CV, CHGIN ILIM, WCIN ILIM | same |
| HOST | 10 mutants: 9 caught, 1 equivalent (66667 vs 66670 µA step: identical at mA for all 64 codes) | `receipts/mutants.txt` |
| ARM64 | `blazer_gauge.o` Mach-O arm64 (`_blazer_gauge_read`, `_spmi_frame`, `_blazer_gauge_frames`); linked kernel 0 undefined; the 22-word frame table decoded from kernel.chg1: all op 3, SIDs 6 and 3 only, no 0xb0-0xb4; the new strings present once | `receipts/kernel-verify.txt`, `receipts/frames-decoded.txt` |
| HOST | Mac build rc 0, shared tree restored to p1 b228c4f and rebuilt (restored kernel lacks the chg1 line) | `receipts/build_chg1.out` |
| HOST | image: obs1's recipe, cmdline 1005 B: `+blazer_battery_chg=2 −hk_ustack=Preferences,MobilePhone` (room); `check`: bootable | `receipts/manifest-diff.txt`, `image-check.txt`, `SHA256SUMS.image` |
| QEMU | preflight qf-a7-ios-system-chg1-1103-233015, 600 s TCG: VERDICT PASS, 0 panics, Home-equivalent at 266 s, UI stable; battery args dropped (QEMU has no SPMI/charger), so this is a kernel no-regression check only | `receipts/qemu-preflight.txt`, `.json` |
| HOST | probe rows `charging` and `wireless-charging` on synthetic lines (`tests/usb.log`, `tests/wlc.log`, written by hand, not phone output) | probe_eval output in this file's history |

## Phone test C1 (coordinator runs it; unattended; owner admission; NO charger write)

Phone in fastboot, on the usual USB cable for the whole boot (expect `in=usb`). Note Android's battery % first if convenient.

```
hk queue add research/images/a7-ios-system-chg1 --mach research/ios26-phaseb-r1/chg/build/kernel.chg1.unstripped \
  --note "chg1: read-only charger line (blazer_battery_chg=2)"
# or directly:
tools/live_boot.sh research/images/a7-ios-system-chg1/boot.img a7-ios-system-chg1 \
  --mach research/ios26-phaseb-r1/chg/build/kernel.chg1.unstripped --wait 1080
```

Success lines (console and ramdump `kernel.log`):

```
blazer-battery: mapping 0x53f1000 size 0x300, mode 1, charger reads report only
blazer-battery: sample 1 SOC(NN), VCELL(NNNN), …                      (gauge unchanged)
blazer-battery: charger 1 in=usb chg=cc|cv|topoff|done mode=5|4 cp=0 wdt=0|1 cc=NNNN mA cv=NNNN mV icl=NNNN mA wicl=NNN mA ichgin=NNN mA …
blazer-battery: charger 2 in=usb …                                     (one per minute, ~13 by the 900 s deadline)
```

Read-out: `python3 -I tools/probe_eval.py --row charging --row wireless-charging <attempt>` → Charging control 🟡 (state read).
Look at: `cv` (FDT `max77779,chg-term-voltage` is 0x1130 = 4400 mV; a value far above it is a finding), `cc`, `wdt`; `chg=off-watchdog` after ~80 s would
mean ABL's watchdog stops charging under iOS (a finding for CONTROL.md, not a fault of this test). Faults: `charger report N unread`,
`leaving the controller alone` (gauge also stops: SweetBattery falls back as today), any unplanned panic. Rollback: deadline → fastboot,
`hk back` return check. Nothing is written to the charger, the phone, or its partitions.

## Phone test W1 (attended, after C1, optional; owner with a Qi pad)

Same image. ≥2 min after Home: owner unplugs USB, puts the phone on a Qi pad for ~3 min, takes it off, replugs USB well before the
deadline (live console will drop and may not come back; the ramdump after the deadline is the record). Expect lines with
`in=wireless`, `vwcin` ≈5000-9000 mV and, if the receiver negotiates on its own (unknown: its driver never runs under iOS),
`chg=cc` with `iwcin` > 50 mA → Wireless charging ✅ on owner confirmation; `in=wireless` alone → 🟡 (pad detected).
Unknown risk: whether XNU's USB gadget re-enumerates after a replug; if the owner prefers, run W1 with `--no-console`.

## Proposed NOTES.md line (for coordination)

- **Charger (2026-11-03, HOST/QEMU, not booted):** max77779 on SPMI SID 3 (same reader as the gauge); wireless RX CPS4041 behind
  the max77779 I2C master. `a7-ios-system-chg1` (b2898a10…, XNU hk-chg1 ca39cb4) logs a read-only charger line per minute
  (`blazer_battery_chg=2`); writes designed, not built, need owner approval. `research/ios26-phaseb-r1/chg/PLAN.md`.
