# max77779 charger: what hk-chg1 reads, and from where (SOURCE)

Sources (GPL-2.0, GrapheneOS mirror of Google's `private/google-modules/bms`, commit 5940a317, the same tree
`docs/reuse/2026-11-02/power-clocks.md` already cites). Downloaded to `/tmp/chg-ref-dl/` for reading only, **not in git**:

- [max77779_charger.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/bms/max77779_charger.c)
  (get_* conversions: CC 937-965, CV 719-738, CHGIN ILIM 1011-1033, WCIN ILIM 1111-1131; ADC units 508, 1458, 1951;
  `max77779_is_online` 1701; `max77779_chg_is_reg` 2776; CHG_DTLS names 50-62)
- [max77779_v20240115_regs.h](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/bms/max77779_v20240115_regs.h)
  (addresses and field masks), [max77779_regs.h](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/bms/max77779_regs.h) (MODE values)

No public Maxim datasheet for the max77779 exists; the vendor driver is the register map.

## Where the charger is (SOURCE, `research/ios26-dualboot-r8/truth/fdt.dts`)

| Node | Bus | Role |
| --- | --- | --- |
| `max77779chrg@3` (14937) `maxim,max77779chrg-spmi` | SPMI `spmi@53f1000`, SID 3 | main charger: CHGIN (USB) and WCIN (wireless) inputs, buck, the limits below |
| `max77779fg@6` (14866) | same SPMI, SID 6 | fuel gauge, already read (PHYSICAL, `blazer-battery: sample`) |
| `max77779pmic@f`, `sp@1`, `vimon@5` | same SPMI | PMIC core, scratch, voltage/current monitor: not touched |
| `max77779i2cm@2` (I2C master inside the max77779, SPMI SID 2) → `cps4041@30` | max77779's own I2C | **wireless receiver** (CPS4041, `google,wlc-firmware = "CPS4041_A0_01.bin"`) |
| same I2C master → `pca9468@57` | | direct (charge-pump) charger, `dc-mains` |

So the charger is **not on an AP I2C bus** (the haptics pattern does not apply). It sits on the SPMI master the gauge
already uses, and hk-chg1 reuses that reader unchanged. Reaching the CPS4041 would mean driving the max77779's I2C master
(register writes to SID 2): out of scope. A pad is visible read-only through the charger's WCIN input.

## The frames (all EXT_REG_READ, SID 3, `blazer_battery_chg=2`)

| Reg | Name | Decoded as | Vendor conversion |
| --- | --- | --- | --- |
| 0xb6 | CHG_INT_OK | raw `ok=` | bit 6 CHGIN_OK, 5 WCIN_OK, 4 CHG_OK, 3 BAT_OK |
| 0xb7 | DETAILS_00 | `in=`: CHGIN_DTLS [6:5], WCIN_DTLS [4:3]; 2 or 3 = valid | `max77779_is_online` |
| 0xb8 | DETAILS_01 | `chg=` CHG_DTLS [3:0], `bat=` BAT_DTLS [6:4] | CHGR_DTLS_* names |
| 0xb9, 0xba | DETAILS_02/03 | raw (`dtls=`): BYP, CHGIN/WCIN_STS; THM/JEITA | |
| 0xbc | CNFG_00 | `mode=` [3:0] (0 off, 4 buck, 5 charge+buck, 0xe/0xf OTG combos), `cp=` bit 5 | |
| 0xbe | CNFG_02 | `cc=` mA: 0→0, <3→133, ≥0x3c→4000, else 133 + (v−2)·66.67 | get_charger_current_max_ua |
| 0xc0 | CNFG_04 | `cv=` mV: <0x38→4000+10v, 0x38→3800, 0x39→3900, else invalid (line says so) | get_regulation_voltage_uv |
| 0xc5 | CNFG_09 | `icl=` mA: 0→0, ≤3→100, else 100+(v−3)·25 | chgin_get_ilim_max_ua |
| 0xc6 | CNFG_10 | `wicl=` mA: 0→0, <4→100, else 125+(v−4)·25 | wcin_get_ilim_max_ua |
| 0xcb | CNFG_15 | `wdt=` WDTEN bit 0 (vendor: tWD = 80 s) | |
| 0x00/01 | CHGIN_I_ADC | `ichgin=` raw·166 µA ("only valid in mode 1,5,6,7,c,d") | CHGIN_RAW_TO_UA |
| 0x02/03 | CHGIN_V_ADC | `vchgin_raw=` (no unit in the vendor source) | |
| 0x04/05 | WCIN_I_ADC | `iwcin=` raw·166 µA ("only valid in mode e, f") | WCIN_RAW_TO_UA |
| 0x06/07 | WCIN_V_ADC | `vwcin=` raw·625 µV | WCIN_RAW_TO_UV |

Never read: CHG_INT 0xb0, CHG_INT2 0xb1 (interrupt latches), the masks 0xb3/0xb4, CNFG_06 (CHGPROT) and every other register.
`_Static_assert` per frame enforces the set; the linked kernel's table is decoded in `receipts/frames-decoded.txt`.

Unknowns (open, to be read on the phone): whether ABL leaves WDTEN on (if it does, the charger stops after 80 s without a
kick: `chg=off-watchdog` would show it), and whether the ADCs convert without `JEITA_CTRL.IN_ADC_FORCE` in this mode.
