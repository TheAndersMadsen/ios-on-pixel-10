# Cellular, SIM and GNSS on the Pixel 10 Pro: the modem map and the first rungs

Owner: modem lane (agent CELL). Scope: README rows **Cellular**, **SIM, eSIM**, **GPS**. Evidence classes are labelled
SOURCE (FDT, vendor GPL source), PHYSICAL (Android on this phone), HOST, QEMU. "Inference" means not checked.

## 1. What the modem is (answers "which modem, which transport")

| Item | Value | Evidence |
| --- | --- | --- |
| Modem | **Samsung Exynos Modem S5400**, a separate chip (`cpif { compatible = "samsung,exynos-cp"; mif,name = "s5400"; }`), vendor driver `google-modules/radio/samsung/s5400` ("CPIF-20220408R1") | SOURCE `research/ios26-dualboot-r8/truth/fdt.dts:35242`; PHYSICAL dmesg `cpif: create_modemctl_device: s5400 is created` |
| Transport | **PCIe**: AP root port `pcie0` = `pcie@c500000` (google,lga-pcie, HSIO_N, 1 lane, max gen 4), endpoint bus 1. Boot ROM enumerates as **`144d:a5a5` class 0x028000** at gen 1 x1 | SOURCE fdt.dts:30889; PHYSICAL `chooser-v1-r3-t1/android/dmesg.txt` 8.305563 `c500000.pcie: Link up`, 8.314724 `[144d:a5a5]`, 8.324753 `PCIe gen1 linkup with CP ROM succeed.` |
| Shared memory | four `exynos,modem_if` reserved regions: `cp_rmem` 0xea400000 12 MiB (IPC 8 MiB + **GNSS_FW** 4 MiB), `cp_msi_rmem` 0xf6200000 4 KiB (MSI/boot-stage registers), `cp_rmem_1` 0xe8000000 32 MiB (pktproc DL/UL rings), `cp_aoc_rmem` 0x0900c000 12 KiB (VSS_AOC, voice) | SOURCE fdt.dts:950-975, 35686; PHYSICAL `cpif: cp_shmem_probe` lines |
| Control GPIOs | AP2CP on hsios pads 2..7 (NRESET, DUMP_NOTI, AP_ACTIVE, PM_WRST_N, CP_PWR_ON, CP_WRST_N), AP2CP_PARTIAL_RST_N lsioe 0x0e, AP2CP_WAKEUP lsios 0x26; CP2AP on cpm pads 0x0b ACTIVE, 0x19 WAKEUP, 0x1a CP_WRST_N; CP_PS_HOLD gdmc 2 | SOURCE fdt.dts cpif node + pinctrl states 0x8f5..0x900 + hsios gpio-line-names |
| Power | CP PMIC on a **bit-banged SPMI** (lsios pads 0x20/0x21, `s5910_bb`), **S5910** RF clock buffer on the same bus; rail VSYS_PWR_MODEM | SOURCE fdt.dts:35747; PHYSICAL `s5910_spmi_driver 1-05: on: …`, `cp_pmic_driver 1-00: PMIC otp reg: 0x30e` |
| Control channel | **Samsung IPC (SIPC 5, `mif,ipc_version 0x32`), not QMI, not MBIM, not AT.** Link frames start 0xABCD (`include/exynos_ipc.h`); channels from `iodevs`: `umts_ipc0/1` ch 0xf5 (RIL: `rild_exynos`), `umts_rfs0` 0x29 (remote file system for NV: `rfsd`), `umts_router` 0x15, `umts_dm0` 0x51 (diag), `rmnet0..29` 0xb5 (raw IP over pktproc DMA), `umts_boot0` 0xf1 (boot/dump), `oem_ipc0..7`, `umts_rcs*`/`umts_wfc*` (IMS), `gnss_boot` 0xf0, `gnss_dump` 0xef, `esim_tracer` 0x54 | SOURCE fdt.dts:35517-35685, `research/ios26-connectivity-r1/resources/s5400/include/exynos_ipc.h`; PHYSICAL `create_io_device` lines and the openers |
| Firmware | `modem.bin` from the **`modem_a/_b`** partition (ext4 at `/mnt/vendor/modem_img`), loaded by userspace `cbd` through `/dev/umts_boot0`: BL1 (0xB400 B) and bootloader (0x16800 B) staged at 0xEA410000 in `cp_rmem`, boot_stage polled in `cp_msi_rmem` (3FFF → 7FFF → FFFF), then the main image and `IOCTL_COMPLETE_NORMAL_BOOTUP` → INIT_START/PHONE_START → ONLINE. CP secure boot (`otp_version: 3`): the images are Samsung-signed | PHYSICAL dmesg 8.022–9.972 |
| SIM / eSIM | Read by the CP firmware only (`get_ds_detect: Dual SIM detect = 2`). The AP sees SIM state and APDUs through RIL IPC; eSIM through the same plus `esim_tracer`. No AP-side SIM hardware | PHYSICAL dmesg; SOURCE iodevs |
| GNSS | Samsung LSI **"KEPLER"** GNSS (`gnssif { device,name = "KEPLER" }`), IPC over **SPI** (`lsios_cli6_spi` 0x3bf61000, `gnss@0`, 50 MHz) plus GNSS2AP/AP2GNSS request lines and CP2AOC time sync; **its firmware is loaded through the CP's link** (`gnss_boot: IOCTL_LOAD_GNSS_IMAGE` into `GNSS_FW` = cp_rmem + 8 MiB) by `lal_*`/`slsi_gnss_service`/`gnssd`. Inference: the GNSS core is in the S5400 package; it cannot run before the CP does | SOURCE fdt.dts:13685, 35777; PHYSICAL dmesg 10.95–11.71 |

## 2. What iOS expects (CommCenter, locationd)

- The userland is iOS 26.6.2 for **iPhone12,3** (iPhone 11 Pro, D421AP). That phone's baseband is an Intel modem, and
  CommCenter talks to Intel basebands with **ARI** (Apple Remote Invocation); Qualcomm ones with QMI
  ([seemoo-lab/aristoteles](https://github.com/seemoo-lab/aristoteles) README, saved in
  `research/ios26-connectivity-r1/resources/aristoteles-readme.txt`). Its kernel side is Apple's baseband PCIe/manager kexts
  (not in our XNU), firmware by `abm-helper`/BBUpdater. Inference, not checked on this root: the names of those kexts and
  services, and that CommCenter loads the Intel/ICE plug-in when no baseband is present.
- PHYSICAL: `CommCenter[69]` already runs on the phone (reader logs, `research/laguna-usb-fix/attempts/20261102-021907-wifi-stage2-r1/reader.txt`)
  and `com.apple.locationd` is on-demand.
- So there is **no native path**: an S5400 speaks SIPC to Samsung's RIL, and CommCenter speaks ARI to Apple's Intel stack.
  Cellular on iOS needs our own CP driver *and* a translation layer between SIPC and what CommCenter consumes. GPS needs the
  Kepler stack and a feed into locationd. Both are large; neither is reachable without the CP booting its firmware.

## 3. What is reachable now, what needs proprietary firmware

| Step | Needs | Reachable |
| --- | --- | --- |
| Read the CP pads, power domains, PCIe0 state | nothing | **now** (stage 1) |
| PCIe0 controller power, resets, PHY table, root port | the PHY table (`laguna_pcie_phy_fw.bin`, Google firmware already in the kernel for Wi-Fi) | **now** (stages 2, 3) |
| CP power-on GPIO sequence; boot ROM's gen 1 link; `144d:a5a5` | nothing: the ROM is in the chip | **now** (stage 4) |
| BL1 / bootloader / main image | `modem.bin` (Samsung, signed) from the phone's own `modem_b` partition, read only | proprietary: read from the phone at run time, never copied into git |
| NV (IMEI, calibration, carrier) | the CP's EFS/NV partitions via `umts_rfs0` (RFS protocol) | proprietary data; **never written**, read-only service only, IMEI never logged |
| RIL control, SIM, registration | SIPC message set (Samsung RIL is closed); the open `exynos_ipc.h` covers framing only | reverse engineering; translation to ARI |
| Data | pktproc rings in `cp_rmem_1`, `rmnet` | open (GPL CPIF source) once the CP runs |
| GNSS | Kepler firmware from the modem image + Samsung LAL protocol over SPI | proprietary firmware + closed protocol |

## 4. Rungs implemented here (stages 1..4)

Code: `src/bsd/dev/blazer_modem_core.{c,h}` (hardware-free, MIT) and `src/bsd/dev/blazer_modem.c` (XNU glue, replaces rung 0).
XNU branch `hk-modem1` = hk-int3 3dc7fec + this source (`tools/build_modem1.py`, patch `xnu-src/0001-hk-modem1.patch`).

Switch: `blazer_modem=N`, or **`hk_dbg` bits 24..27 = N** (no new token: int's line is 1018 of 1023 bytes), bit 28 = hold.
`blazer_modem=1` keeps rung 0's meaning (reads only) and is a superset of it.

1. **read**: mailbox magic; LPB GET HSIO_N (0x17), HSIO_S (0x18), LSIO_E (0x1c), LSIO_S (0x1e); then every pad whose domain is
   ON (PARAM/DMUX/TX/RX). Verdict `read: CP as found: off|NOT off`. Writes: the mailbox only.
2. **ctrl**: phy_fw clock put (lpcm 5 clock 3, the shim's USB put form), PCIe0 power vote `0x01010201` (HSIO_N = LPCM sswrp 2
   per `lga_cpm_mappings.c`, `hsio_n_pcie_pd` subdomain 1), resets init 2, power_up 3, perst 0 (hsion_resets lpcm 5); PHY SRAM ready.
3. **phy**: the 20480-word PHY table (pcie-google.c requests one `laguna_pcie_phy_fw.bin` for every controller), app_hold_phy 1,
   root port set up for gen 1 x1 (stock's `LINK_MODE_MIN_SPEED_BOOTING`), posted credits 0x51, equalisation off.
4. **link**: PERST low; refuse unless the CP was found off; stock `power_on_cp` from off (AP_ACTIVE 1, DUMP_NOTI 0, PARTIAL_RST_N 1;
   then PM_WRST_N 1, CP_PWR_ON 1, NRESET 1 at 10 ms each, CP_WRST_N 1, as Android's 32 ms); CLKREQ to the controller; PERST high
   after 20 ms; LTSSM; up to 4 × 100 ms; ATU region 0 onto bus 1; config **reads** of 0x00, 0x08, 0x2c and the PCIe capability.
   Then, unless hold: PERST low, LTSSM off, CP off in `gpio_power_off_cp` order (CP_WRST, NRESET, CP_PWR + 30 ms, PM_WRST + 50 ms),
   every driven pad back to what it was found as.

Never: firmware, CP reserved memory, endpoint config writes, BARs, bus master, SPMI (CP PMIC, S5910), a power-off vote, UFS's
or Wi-Fi's or NFC's pads, IMEI/serial reads. The S5910 sequence is skipped as stock skips it on a first power-on
(`cp_ever_powered_on` false).

### Evidence so far

- HOST: `tests/run.sh` (ASan/UBSan), 97 checks: stage write sets, frame list, stock on/off order, PERST before power, refusal when the
  CP is found on, HSIO_N/LSIO_E off, silent CP (4 attempts, all restored), wrong vendor, refused addresses (CP memory, UFS/Wi-Fi/NFC pads,
  endpoint config). 12 mutations, 11 caught; the survivor removes a redundant CP-memory guard (the allowlist already refuses). Receipt
  `receipts/host-tests.txt`.
- ARM64 object (m1box clang, `-DBLAZER`): `m0_run m0_read_allowed m0_write_allowed …` present; without the gate the unit is empty.
- Kernel build on the Mac: `build/receipts.txt` (objects, symbols, strings, `bsd_init → _blazer_modem_init`).
- QEMU (`receipts/QEMU.md`): with `hk_dbg=0x4000000` the thread arms, stops at the mailbox magic (QEMU has no CPM) with 0 frames, no panic,
  boot continues to SpringBoard. With the modem off (pre-flight): all milestones and int3's expect rows pass; the two crash-loop findings
  (fairplayd.H2, datamigrator) are in int3's own run too. Not a modem result.
- Image `research/images/a7-ios-system-modem1` (boot.img a4384d11…): int3 + kernel.modem1 + `hk_dbg=0x41e1e1f`; both image tools say OK.
- PHYSICAL: none yet. Rung 0 (`blazer_modem=1`, 659b370) was never booted.

## 5. Phone test (the coordinator boots; never this lane)

One unattended boot answers rungs 1..4 in order, because each stage stops at its own named failure and tidies:
image = the current int3/obs image with **only `hk_dbg` changed: OR in `0x04000000`** (stage 4, no hold). See `PHONE-TEST.md`.

## 6. Staged plan to cellular attach and GNSS

| Rung | Goal | New kind of change | Proprietary? | Proof line |
| --- | --- | --- | --- | --- |
| 5 | CP ROM boot handshake: MSI region, doorbell BAR0, `boot_stage` read in `cp_msi_rmem` | first BAR assignment, bus master, CP shared memory (Android's region, only while iOS runs) | no | `blazer-modem: rom: boot_stage 0x…` |
| 6 | BL1 + bootloader from the phone's `modem_b` (read-only ext4 via UFS) into `cp_rmem`+0x10000 | firmware load | **yes** (read from the phone at run time) | `boot_stage 3FFF`, then `FFFF` |
| 7 | Main image, INIT_START/PHONE_START, link at gen 4 | firmware load, SIPC link layer | yes | `cp: ONLINE` |
| 8 | RFS server read-only (the CP asks for NV files) | NV data, read only, never written; IMEI masked | yes (data) | `rfs: open/read n files, 0 writes` |
| 9 | RIL: power on radio, SIM status, registration state over umts_ipc0 | SIPC message set (reverse engineered) | protocol closed | `cell: SIM ready`, `cell: registered <rat>` |
| 10 | Data: pktproc DL/UL rings, one PDP context, rmnet as an iOS interface | DMA rings, an IONetworkInterface | no (GPL ring layout) | `cell: the data session is up`, ping |
| 11 | CommCenter: translation SIPC ↔ the ARI that iPhone12,3's CommCenter expects (or a CoreTelephony-level shim) | userland + kernel interface | Apple stack closed | status bar carrier |
| G1 | GNSS: firmware via `gnss_boot` into GNSS_FW; Kepler SPI link up (`gif`) | firmware, SPI | **yes** | `gnss: KEPLER ready` |
| G2 | Position: LAL protocol, NMEA/fix to locationd (a CLLocation feed) | closed protocol | yes | `gnss: fix` |

Each rung keeps the Android installation, the modem partitions and NV untouched; firmware and NV are read on the phone at run time and
never enter git. Rungs 6+ need an owner decision on loading Samsung's signed modem firmware under iOS.

## 7. References (summaries; local copies are the receipts)

- `kernel/google-modules/radio/samsung/s5400` (GPL, AOSP tag android-16.0.0_r0.10): `modem_ctrl_s5100.c` (power on/off, boot), `s51xx_pcie.c`,
  `link_device_*` (pktproc, legacy IPC). Local reference copies: `research/ios26-connectivity-r1/resources/s5400/` (manifest.json).
- Google `soc/rdo`: `pci/pcie-google.c` (one PHY file for both controllers), `drivers/pinctrl/google/pinctrl-lga.c` (hsion pad functions),
  `power-controller/lga_cpm_mappings.c` (HSIO_N = LPCM sswrp 2). Mac copy under `research/ios26-webscout-r1/dl-gos-6.12/`.
- [pixel-mainline/exynos-modem](https://git.deusch.me/pixel-mainline/exynos-modem): mainline bring-up tools for the Pixel 9a's Exynos 5300
  (same family); reference only, not imported.
- [seemoo-lab/aristoteles](https://github.com/seemoo-lab/aristoteles): ARI (Intel baseband ↔ CommCenter) dissector; QMI for Qualcomm.
