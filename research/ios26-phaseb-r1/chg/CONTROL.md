# Charging control: write design (NOT IMPLEMENTED, owner approval required)

Status: **design only.** No kernel in this lane contains a charger write. hk-chg1 is read-only by construction (one opcode,
static-asserted register set). Nothing here may be built into a phone image until (1) the chg1 read-only boot has given real
register values and (2) the owner has approved this exact write, in writing, for one named image.

## Why read first

What ABL leaves is unknown: CHGCC, CV, input limits, MODE, the 80 s charger watchdog (CNFG_15 WDTEN). Under iOS nothing
programs the charger, so today iOS charges at whatever ABL left (probes row note: "Left at the bootloader settings").
That is a safe state as long as the charger's own protections (thermal regulation, JEITA, top-off/done) run, which the
DETAILS lines show. The first chg1 boot answers: is it charging (`chg=cc|cv`), at what limits, and does the watchdog stop it.

## The only write considered: lower the fast-charge current (CNFG_02 CHGCC)

- **Limit-only:** the new CHGCC code must be ≤ the code read at boot (ABL's) and ≤ a fixed cap (proposal: code 0x0f = 133 + 13·66.67
  ≈ 999 mA). It can only reduce charge current. A lower charge current cannot overcharge
  (termination is set by CV, which is never written) and produces less heat.
- **Never written:** CNFG_04 (CV, the overcharge risk), CNFG_09/10 (input limits), CNFG_00 MODE (OTG/boost/off), CP_EN,
  watchdog, JEITA, thermal, COP, anything on SID 2 (I2C master / wireless RX) or the PMIC.
- **Sequence (vendor `max77779_set_charger_current_max_ua`):** CHGCC is write-protected by CNFG_06 CHGPROT. Unlock (CNFG_06 0xc2
  CHGPROT [3:2] = 0b11, vendor `max77779_chg_prot`), write CNFG_02 with only CHGCC [5:0] changed, relock (CHGPROT = 0), read back CNFG_02 and CNFG_06. One
  attempt per boot; any mismatch logs and stops all further charger writes. Each write prints
  `blazer-charge: limit applied cc=N mA readback M mA` (the `charging` probe's planned `works` pattern) and the before value.
- **Guards (the pure planner blazer_charge_policy.c from fleet patch 0699; not built into any kernel, its tests not rerun here):** only with a fresh valid gauge sample,
  CHGIN valid and WCIN absent, CP off, battery 0..55 °C, VCELL < 4.5 V; otherwise no write. Thermal guard (blazer-thermal,
  PHYSICAL) stays the backstop.
- **Reversal:** Android's charger driver reprograms CHGCC at its own start, so a return to Android restores normal charging;
  the return check would confirm (charging in Android after the boot). A power-on reset of the max77779 also restores it.
- **Not done here, on purpose:** raising current, enabling charging ABL left off, kicking the watchdog (that is "keep
  charging without supervision": refuse until the read-only boot shows what ABL does), wireless RX control.

## What needs the owner

1. Approval of the read-only chg1 boot is the coordinator's normal admission (no write; same bus and slave the gauge already
   uses, plus SID 3 which `blazer_battery_chg=1` was allowed to read).
2. A **separate explicit approval** before any image with a charger write: name the image, the cap (mA), and the one register.
