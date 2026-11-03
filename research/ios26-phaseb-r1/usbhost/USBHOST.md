# USBHOST: USB host mode and the DisplayPort alt-mode map (2026-11-03; HOST + ARM64 object only, not booted)

Status: **ready for a kernel build and one attended boot.** The host-mode code is written and host-tested against an
xHCI model (48 checks, 12/12 mutants killed). It compiles to a real arm64 kernel object with the release kernel's own
compile line. It has never run on the phone, so there is no physical evidence. Video out is mapped, and its first
read-only step (D0) is in the same kernel. Nothing beyond D0 is written.

| Evidence | What it shows | Receipt |
| --- | --- | --- |
| SOURCE | FDT and Google lga sources: DWC3 at 0x0c400000 with xHCI at offset 0; the eUSB2 repeater needs no change for host; VBUS comes from the TCPC and charger; DP runs over the TCPC SBU switch, the combo-PHY TCA and dwc_dptx | this file, *Hardware map* |
| HOST | the core under ASan/UBSan against a DWC3 + xHCI model: role switch, rings, port reset, Address Device, FS EP0 fix-up, descriptors, failure paths, ring wraps | `receipts/tests.txt` (48 checks, 0 failed; mutants 12/12) |
| ARM64 object | `blazer_usbhost.o`, Mach-O arm64, built with the XNU build's argv for `blazer_usbcon.o` (`-D BLAZER=1 -mkernel`) and the source swapped; `_blazer_usbhost_start` (T), `_usbhost_thread` (t, 9948-byte `__text`, the core inlined), every phase string present | `receipts/obj-arm64.txt` (f1fe36bb…) |
| HOST tools | probe rows evaluate the simulated console correctly; `hk`/`hklog` know `usbhost` | `receipts/tools-tests.txt` |
| QEMU | none: QEMU has no Tensor DWC3 | — |
| PHYSICAL | none | — |

## Hardware map (FDT `research/ios26-dualboot-r8/truth/fdt.dts`, Google lga sources; facts only)

**USB data path.** Connector → max77759 TCPC (SPMI SID 4: CC, PD, the USB D+/D- switch `USBSW_CTRL` 0x93, the SBU
crossbar `SBUSW_CTRL` 0x94) → TI TUSB2E11 eUSB2 repeater (I2C cli10 `0x3a331000`, address 0x3e, on the same bus as the
haptics chip) → USB2 PHY → DWC_usb31 `dwc3@c400000` (GSNPSID 0x33313130, `usb-role-switch`, default role peripheral,
`maximum-speed super-speed`) inside the glue `google,dwc3-lga` at `0x0c450000` (`usbcs_host_cfg_csr`, `usbint`,
`usb_top_cfg`). SuperSpeed lanes go through the USB/DP combo PHY `usb_phy@c410000`: `dptx_tca_regs` 0x0c430000 (Synopsys
Type-C Assist), `dp_top_csr` 0x0c637000, `phy_sram` (firmware `usb_phy_fw_2.27.0.bin`), `orientation-switch`, `mode-switch`.

**What host mode needs, by component:**
- **DWC3:** GCTL.PRTCAPDIR = host (1), after a GCTL.CORESOFTRESET (DWC_usb31 before 1.90a; Linux `__dwc3_set_mode`). The
  xHCI registers are at DWC3 offset 0x0..0x7fff (Linux `DWC3_XHCI_REGS_END`). This kernel does this.
- **eUSB2 repeater:** nothing. In `google-eusb2-repeater.c`, `role_switch_set` maps both `USB_ROLE_DEVICE` and
  `USB_ROLE_HOST` to "power on". The repeater is on because ABL's fastboot gadget used it, so no I2C write is needed.
- **Combo PHY:** for host, Google's `u3phy_usb_role_switch_set` clears `sys_vbusvalid` (dp_top_csr+0x28 bit 17) and
  `phy_lane0_power_present` (+0x2c bit 16). They are 1 for device. This kernel only **reads** them. Clearing them is the
  next variable if USB2 attach fails.
- **Glue:** `usbcs_host_cfg_csr` HC_STATUS/HOST_CFG1 hold the host power-state handshake (D0/D3, for hibernation). This
  kernel reads them only, before and after the switch.
- **VBUS:** the phone sources it only through the TCPC/charger. Google's direct-OTG path is an SPMI write to SID 3, reg
  0xbc (`MAX77779_BUCK_BOOST_OP`), value 0x0a (`MAX777x9_BUCK_BOOST_SOURCE`). That is a PMIC write and **out of scope**
  (owner decision). So the test device has to be powered by something else; see the test setup.
- **Not reserved memory owned by Android/AoC:** the FDT's `xhci_dma@9010000`, `xhci_dma_buffer@9050000` and
  `xhci_dma_dram@97000000` belong to AoC USB-audio offload. The arena used here is 64 KiB at `0xbee00000` inside
  `abl@be000000`, the reservation blazer_usbcon and blazer_usbnet already use; usbnet's arena is the last MiB, at 0xbef00000.

**DisplayPort alt-mode path.** DT connector `altmodes/displayport { svid = 0xff01; vdo = 0x1cc6; }` → PD Discover/Enter
Mode/DP Configure on the max77759 (SPMI) → SBU crossbar `SBUSW_CTRL` 0x94 = 0x80 (normal) / 0xC0 (reversed) on max77779 +
AUX pull-up supply (`pullup-supply`, the same rail as the repeater's vdd33) → combo PHY TCA mux (`TCA_TCPC` 0x14: [2:0] 0
none / 1 USB / 2 DP / 3 USB+DP, [3] orientation, [4] valid; `TCA_GCFG`; ack `TCA_INTR_STS.xa_ack_evt`) with the DT's
`dp_tune_params` swing/pre-emphasis tables → `dwc_dptx@c600000` (Synopsys DPTX, power domains dp_top_pd + dpu_dp_pd +
sswrp_dpu_pd, clocks gpcm_pll_dp_clk + hsion/dpu pixel clocks 0/1) ← DPU `dp_encoder` (verisilicon, mux-id 2,
`dc_port1_dp_out`/`dc_port2_dp_out`). DP shares the combo PHY's lanes with USB3. USB2 host and 4-lane DP (pin assignment C)
can coexist.

## What the kernel does (`xnu-src/blazer_usbhost.c` + `blazer_usbhost_core.inc`)

`blazer_usbhost=1`. Off without it: no map, no MMIO, no thread, no line. With it:

1. **Admission (RAM and boot-args only).** It is refused when `blazer_usbcon` is non-zero (one controller, one port, one
   owner) and when this boot's shim stamps do not show the shim's gadget up and handed off. The stamps are the proof that
   the controller is powered and clocked (as usbcon). It is also refused if the arena overlaps the stamped console arena.
2. **Wait** `blazer_usbhost_wait` s (default 90). It prints `host mode in N s: unplug the Mac, plug the device` every 30 s.
3. **Survey (read only):** DWC3 GSNPSID/GCTL/DCTL/DSTS/GUSB2PHYCFG, GHWPARAMS0/GUCTL/GFLADJ, glue HC_STATUS/HOST_CFG1,
   TCA CLK_RST/INTR_STS/GCFG/TCPC/PSTATE, dp_top CFG1/CFG2/DP_CONFIG/AUX_CTRL. This is DP stage D0 and the role-switch baseline.
4. **Role switch:** RUN_STOP off, then wait ≤ 100 ms for DEVCTRLHLT while acking events. **No halt: stop there**, with
   nothing reset (the shim's DMA could still be live). Then DEVTEN 0, device event buffer retired (GEVNTSIZ masked,
   GEVNTADR 0), GUSB2PHYCFG.SUSPHY off, GCTL.CORESOFTRESET for 100 ms, PRTCAPDIR = host.
5. **xHCI:** sanity checks on CAPLENGTH/HCIVERSION/slots/ports/DBOFF/RTSOFF; Supported Protocol capabilities give the USB2
   and USB3 root ports; scratchpad buffers (≤ 12 pages); CNR, HCRST, MaxSlotsEn 4, DCBAA, command ring, one-segment event
   ring, IMAN.IE 0 (polled), RS.
6. **Enumerate:** port power on the **USB2 root ports only** (USB3 PORTSC is never written). It waits up to
   `blazer_usbhost_window` s (default 150) for CCS, then debounces 100 ms, does a port reset and an Enable Slot, then an Address Device
   (EP0 MPS 8/64/64/512 by speed). At full speed it reads 8 bytes and runs Evaluate Context if bMaxPacketSize0 ≠ 64.
   Then it reads the device, configuration and product-string descriptors.
7. **Report** one line per step, ending in `blazer-usbhost: PASS, port N enumerated VVVV:PPPP …` or `blazer-usbhost: stop: <why>`.
   The controller stays in host mode until the boot ends. The deadline panic resets the SoC, and ABL's ramdump/fastboot path
   initialises USB as a device again. That last part is inference: every boot already ends this way, but none has
   ended from host mode.

Never written: GUSB3PIPECTL, USB3 PORTSC, PHY/TCA/dp_top_csr, repeater, TCPC, charger, clocks, resets, power domains, CPM.

Lines (from the model; the values are the model's, not the phone's):

```
blazer-usbhost: mode 1, wait 90 s, window 150 s, arena 0xbee00000
blazer-usbhost: host mode in 90 s: unplug the Mac, plug the device
blazer-usbhost: survey GSNPSID 33313130 GCTL 2004 DCTL 80000000 DSTS 0 GUSB2PHYCFG 48
blazer-usbhost: survey GHWPARAMS0 … GUCTL … GFLADJ … glue hc_status … host_cfg1 …
blazer-usbhost: survey TCA clk_rst … intr_sts … gcfg … tcpc … pstate … … …
blazer-usbhost: survey dp_top cfg1 … cfg2 … dp_config … aux_ctrl …
blazer-usbhost: gadget halted in 3 ms
blazer-usbhost: host mode, GCTL 1004, glue hc_status … host_cfg1 …
blazer-usbhost: xhci 110 caplen 32 slots 64 ports 2 scratch 2 csz 32 ac64 1 ppc 1 db 1000 rt 800
blazer-usbhost: root ports usb2 1+1 usb3 2+1
blazer-usbhost: running, USBSTS 0
blazer-usbhost: port 1 connect after 1500 ms, PORTSC 20e01
blazer-usbhost: port 1 reset done, enabled 1, speed high, PORTSC 200e03
blazer-usbhost: slot 1 address device: ok, cc 1, address 5
blazer-usbhost: ENUM port 1 speed high dev 0781:5581 usb 2.00 class 00/00/00 mps0 64 configs 1
blazer-usbhost: ENUM port 1 interfaces 1, first 08/06/50, config bytes 32
blazer-usbhost: ENUM port 1 product "…"
blazer-usbhost: PASS, port 1 enumerated 0781:5581, events 5, controller left in host mode until the end of the boot
```

## Why the console is safe, and why this boot has none

The live console, ECM and input all run on this one DWC3 in device mode, and the USB-C port is a single port: while a
device is plugged in, the Mac is not. Coexistence is physically impossible. So host mode is **a separate boot-gated mode**:
- the kernel refuses `blazer_usbhost` with any non-zero `blazer_usbcon`;
- `tools/image_tool_usbhost.py` refuses an image that has both, or one whose wait + window + 45 s runs past the deadline;
- normal images are unaffected: without `blazer_usbhost` the code returns on its first line, and the patch adds only a
  call next to `blazer_usbcon_start()`.

The result comes back through the **ramdump path**: msgbuf → deadline panic → force-fastboot park → the runner pulls
the ramdump when the Mac cable is plugged back in.

## The attended test (coordinator runs it; the owner handles the cable; never cold-reset mid-boot)

**Hardware:** a **USB-C hub with a PD charging input**, its charger already plugged into the hub, and a USB flash drive
(or keyboard) in one of its ports. The hub sources VBUS from its charger, so the phone is a sink (as with any charger), and
the hub's upstream port sees VBUS and connects. The phone itself sources nothing. First expected ENUM: the **hub's own
USB2 controller** (class 09; for example Genesys 05e3:06xx or VIA 2109:28xx). Devices behind the hub need the hub-class
step (rung H2), which is not written yet. If no PD hub is at hand, any self-powered USB device that pulls D+ up without VBUS
also works.

**Build and image (Mac, repo root, when the shared XNU tree is back on p1):**
```sh
python3 -I research/ios26-phaseb-r1/usbhost/tools/build_usbhost.py a4b2aa08d8836aa155ae5d6d35730cc67c8930f62294156737b754c8cf770432
sh research/ios26-phaseb-r1/usbhost/tools/mkimg_usbhost.sh      # a7-ios-system-usbhost1, cmdline 999 bytes (obs1 1018)
```
Image = a7-ios-system-obs1's recipe with `-blazer_usbcon=1 -blazer_usbcon_ch9=1 +blazer_usbhost=1`, deadline 300.

**Boot (phone lease held by the coordinator; force-fastboot armed by the runner):**
```sh
tools/bootios research/images/a7-ios-system-usbhost1/boot.img a7-ios-system-usbhost1 \
  --mach research/ios26-phaseb-r1/usbhost/build/kernel.usbhost1.unstripped --wait 900
```
Owner timeline from the `fastboot boot` OKAY:
- **0–60 s:** unplug the Mac cable from the phone and plug in the powered hub with the device. Host mode starts about
  90 s after XNU entry; plugging late, up to about 240 s, still counts (window 150 s).
- **after about 300 s** (the deadline; the panel shows nothing new): unplug the hub and plug the Mac cable back in. The
  phone is parked in fastboot. The runner pulls the ramdump. With both hosts on the bus and no device, nothing happens
  electrically, so re-plugging early is harmless.
- Then `hk back` (force-fastboot off, reboot, return check) and `hk ingest`. Record the device and hub with `hk note <id> "…"`.

**Success:** in `<attempt>/ramdump/kernel.log`: `blazer-usbhost: ENUM port N speed S dev VVVV:PPPP …` and
`blazer-usbhost: PASS, port N enumerated VVVV:PPPP`. The VID:PID must match the hub or device the owner names
(`docs/owner_confirmations.txt` line). The return check must pass.
`python3 -I tools/probe_eval.py --row usb-host --row usb-host-enumerate --row dp-video-out <attempt>` then gives
`usb-host` **partial** (USB host, no video) and `usb-host-enumerate` **works** (after owner confirmation).

**Failure table (stop, no unchanged retry; one variable next):**

| Last line | Meaning | Next variable |
| --- | --- | --- |
| `refused: …` | admission failed, no register written | fix the image (stamps, cmdline) |
| `gadget no halt after 100 ms` | the shim's gadget did not halt; nothing was reset | read DSTS in the survey; ABL/shim handoff state |
| `host mode, GCTL` without `xhci …` or `stop: xHCI registers implausible` / `CNR` / `HCRST stuck` | the core did not come up as a host | the glue `hc_status` power state; GCTL soft-reset length |
| `running` then `stop: no device` | no USB2 connect | is the hub's charger on? Then clear dp_top `sys_vbusvalid` (Google's host value); TCPC `USBSW_CTRL` 0x93 read (D1) |
| `port N reset done, enabled 0` / `reset timeout` | link did not enable after reset | port speed in PORTSC; repeater state (I2C read only) |
| `address device: … cc 4` (USB transaction error) | the device did not answer SET_ADDRESS | GFLADJ (the FDT quirk 0xa0) |
| `device descriptor: transfer timeout` | EP0 IN stalled | as above |
| no `blazer-usbhost` line at all | kernel or image wrong | `hk report`; check the kernel strings |

**Recovery if host mode wedges USB:** every iOS boot here ends in its own deadline panic, and force-fastboot parks the
phone in ABL fastboot. ABL reinitialises the DWC3 as a device, as it does after every boot. If no fastboot device shows up
on the Mac about 10 minutes after the boot, *only then* hold Power + Volume Down (cold reset, which loses the ramdump). The phone
comes back in the bootloader; then `hk back`. Android is never touched: this image mounts `ios_system` read only, has no
`blazer_persist`, and no partition, slot, firmware or reserved region is written. The arena is ABL's own reservation.

## DisplayPort video out: stages (only D0 exists)

| Stage | What | Writes | Line (probe `dp-video-out`) | Status |
| --- | --- | --- | --- | --- |
| D0 | read TCA (mux state, orientation, PSTATE) and dp_top (DP_CONFIG, AUX_CTRL) | none | `blazer-usbhost: survey TCA … tcpc X` | in hk-usbhost1, host-tested |
| **D1 (first step)** | read the TCPC over SPMI SID 4 with blazer_gauge's read-only EXT_REG_READ transport: VENDOR_ID 0x00..0x03, TCPC_CONTROL 0x19 (bit 0 plug orientation), ROLE_CONTROL 0x1A, POWER_CONTROL 0x1C, CC_STATUS 0x1D, POWER_STATUS 0x1E, FAULT_STATUS 0x1F, USBSW_CTRL 0x93, SBUSW_CTRL 0x94 | none (ABL itself reads SID 4 reg 0x94: its last REQ_COMMAND in the battery receipt is 0x004a020e) | `blazer-dp: tcpc …` (planned) | proposal to the power owner (a new slave id on the bus needs their and the owner's word) |
| D2 | PD message engine on TCPCI TRANSMIT/RX_BUFFER: Discover Identity/SVIDs/Modes, Enter Mode 0xff01, DP Status/Configure (pin C/D, our VDO 0x1cc6) | TCPC writes (PD transmit) | `blazer-dp: altmode entered, pin assignment C` | owner decision. An adapter powered from the phone also needs VBUS (charger OTG) |
| D3 | SBU crossbar 0x94 by orientation; AUX pull-up; TCA mux → DP (xa_ack); DPTX power/clocks via CPM LPCM; AUX DPCD read | TCPC, PHY, CPM | `blazer-dp: sink DPCD rev 1.4` | after D2 |
| D4 | link training (TPS1-3), swing/pre-emphasis from `dp_tune_params` | DPTX/PHY | `blazer-dp: link trained HBR2 x4` | |
| D5 | DPU dp_encoder (mux-id 2) stream; SweetFramebuffer clone | DPU | `blazer-dp: video out 1920x1080@60` | |

DP does not need xHCI enumeration (usb-networking audit). It shares the PD/TCPC prerequisites with VBUS sourcing.

## Next rungs (USB)

- **H1 (this):** enumerate the device on the root port.
- **H2:** hub class: GET_HUB_DESCRIPTOR, port power, port reset, Address Device with a route string (and TT fields for
  FS/LS behind an HS hub), then the device behind the hub. Same core, host-testable the same way.
- **H3:** VBUS sourcing (owner decision; SPMI SID 3 0xbc = 0x0a, Google's direct-OTG value) so that bus-powered devices work.
- **Later:** a real host stack for iOS (IOUSBHostFamily) is a separate project. FreeBSD xHCI is the reuse candidate
  (`docs/reuse/2026-11-02/usb-networking.md` §4).

## References (facts only; GPL sources, nothing copied)

- Linux `torvalds/linux` @ `05441d697f7f9a927264f4058cbbc6a03dfcac9d`: [drivers/usb/dwc3/core.c](https://github.com/torvalds/linux/blob/05441d697f7f9a927264f4058cbbc6a03dfcac9d/drivers/usb/dwc3/core.c)
  (`dwc3_set_prtcap`, `__dwc3_set_mode`: CORESOFTRESET 100 ms, SUSPHY off during the switch),
  [core.h](https://github.com/torvalds/linux/blob/05441d697f7f9a927264f4058cbbc6a03dfcac9d/drivers/usb/dwc3/core.h) (xHCI 0x0..0x7fff),
  [phy-fsl-imx8mq-usb.c](https://github.com/torvalds/linux/blob/05441d697f7f9a927264f4058cbbc6a03dfcac9d/drivers/phy/freescale/phy-fsl-imx8mq-usb.c)
  (Synopsys TCA register names), [tcpci.h](https://github.com/torvalds/linux/blob/05441d697f7f9a927264f4058cbbc6a03dfcac9d/include/linux/usb/tcpci.h).
- Pixel 10 (lga) vendor kernel, unofficial GitHub mirror `azagramac/pixel10-kernel-aosp` @ `6f689be7fa23ce6c6a30a5895e290c3892706486`.
  Its facts were checked against our FDT (compatibles, addresses, I2C address, SPMI SIDs):
  [dwc3-google.c](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/soc/rdo/usb/dwc3-google.c),
  [google-usb-phy-driver.c](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/soc/rdo/phy/google-usb-phy-driver.c)
  (`set_vbus_valid`, TCA), [google-usb-phy-internal.h](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/soc/rdo/phy/google-usb-phy-internal.h),
  [google-eusb2-repeater.c](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/soc/rdo/phy/google-eusb2-repeater.c),
  [tcpci_max77759.c](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/soc/gs/drivers/usb/typec/tcpm/google/tcpci_max77759.c)
  (`max77759_set_vbus`, the SBU switch), [tcpci_max777x9_spmi.c](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/soc/gs/drivers/usb/typec/tcpm/google/tcpci_max777x9_spmi.c)
  (direct OTG: SID 3), [tcpci_max77759_vendor_reg.h](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/soc/gs/drivers/usb/typec/tcpm/google/tcpci_max77759_vendor_reg.h),
  `private/google-modules/display/vsi-drm/dwc_dptx/` (the DPTX driver, for D3-D5).
- xHCI 1.2 specification (rings, contexts, PORTSC, Supported Protocol capability); USB 2.0 §7.1.7.3 (attach debounce).
- Local: `osfmk/arm64/blazer_usbcon*.{c,inc}` (stamp admission, halt sequence, abl@be000000), `iokit/Kernel/arm/blazer_gauge.c`
  (the SPMI read transport for D1), `bsd/dev/blazer_haptic_hw.c` (cli10 I2C bring-up, for repeater reads), `live/NET.md`.

## Files (`research/ios26-phaseb-r1/usbhost/`)

`xnu-src/` (blazer_usbhost.c, blazer_usbhost_core.inc), `patches/0001-…patch` (applies to hk-obs1 284121116f),
`patches/docs-*.patch` / `tools-*.patch` (only this lane's hunks in shared files), `tests/` (test_usbhost.c, mutants.sh,
run.sh, fixtures/), `tools/` (obj_usbhost.py, build_usbhost.py, mk_image_tool_usbhost.py, image_tool_usbhost.py,
mkimg_usbhost.sh), `receipts/`. `build/` (objects, kernels) stays out of git. Hashes: `receipts/SHA256SUMS`.
