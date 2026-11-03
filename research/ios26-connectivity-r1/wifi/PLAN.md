# Wi-Fi on the Pixel 10 Pro under iOS 26: chip, prior art, staged plan, first step (2026-11-03, m1box, HOST)

Labels: **physical** = phone log or Android capture; **source** = release XNU tree
`research/ios26-release-r1/work/xnu` (HEAD 7227fe7; no Wi-Fi/overlay file changed since before dd000c8);
**host** = built/run on m1box; **inference** = untested. Nothing here touched the phone, QEMU or the root index.

## 1. The chip: Broadcom/Synaptics BCM4390 rev 5 ("b1"), PCIe gen-1 x1 on the second Tensor controller

| Fact | Evidence |
|---|---|
| Bus: PCIe, controller `pcie1: pcie@3c500000` (`google,lga-pcie`, `linux,pci-domain = 1`, `max-link-speed 3`, 1 lane, `iommu-idmapped`, MSI + `link_down`), child node `wlan { compatible = "android,bcmdhd_wlan"; wl_reg_on = <&gpio 0x0d>; wl_dev_wake = <&gpio 0x0c>; wl_host_wake = <&gpio(0x440) 0x20>; ch-num = 1 }` | stock DT `research/ios26-dualboot-r8/truth/fdt.dtb` (dtc), lines ~30915-30965 of the decompiled DTS; also `wlan-device { compatible = "android,bcmdhd_wlan-wonder" }` bound by `google,wonder-drv-v1` |
| Pads on that GPIO bank (phandle 0x43e): `WLAN2AP_PCIE_CLKREQ0_L`, `AP2WLAN_PCIE_PERST0_L` (pcie1 `perstn-gpios` 0x0b), `AP2WLAN_DEV_WAKE` (0x0c), `AP2WLAN_REG_ON` (0x0d) | same DT, `gpio-line-names` |
| PCI ID `14e4:4438`, class 0x028000, at `0001:01:00.0`; BARs 0 (64 KiB), 2 (4 MiB), 4 (1 MiB pref) | Android dmesg `research/ios26-dualboot-r8/attempts/return-after-restore/dmesg.txt` t=5.75 (physical) |
| Module **`bcmdhd4390`** (`dhd_wifi_comp_ops [bcmdhd4390]`), `dhdpcie` driver, `chipid=0x4390`, `chiprev:0x5` -> "b1", buscorerev 133, `hw_sku GEHN3`, `ROW` | same dmesg t=5.71-6.07 |
| Firmware `fw_bcmdhd.bin_4390_b1`, NVRAM `bcmdhd.cal_USI_G7BB_7311_V11` (module USI, OTP vendor 0x11/0x73, board 0x19), map `fw_bcmdhd.map_4390_b1`, CLM `bcmdhd_clm.blob_4390_b1`, txcap `bcmdhd_txcap.blob_ROW` | same dmesg t=6.07-7.69 |
| Android's running firmware now: `27.10.1121.57.31 (g4159d38 b1 release2) FWID 01-765a5017`, Sep 23 2026 | same dmesg t=7.52 |
| iOS side reads the same: link gen1 x1, id `0x443814e4`, chip `0x4390 rev 5`, 29 cores, PCIe rev 133, OTP NVRAM 7311, firmware **`.57.30` FWID 01-800a0c25** (the kernel's pinned copy, older than Android's `.31`), IPC 9 | physical `research/laguna-usb-fix/attempts/20261102-065234-wifi-stage5-dry-r1/ramdump` |

It is not SDIO and not a Google/Samsung part: a PCIe FullMAC Broadcom part with firmware-side 802.11, MLME and
supplicant (`idsup`, `sae` in its cap list). Bluetooth is a separate UART function of the same combo (out of scope).

## 2. What already exists (do not redo)

Physical, iOS kernel, Nov 2 (`research/laguna-usb-fix/attempts/*wifi-stage{1..5}*`): power vote, PHY table, link up,
BARs, backplane walk, OTP, FLR, 2.5 MB firmware load + readback, NVRAM/seed, doorbell, IPC9 rings, ioctls
(`wlc_ver`, `GET_REVINFO`, `ver`), CLM/txcap load, country, `WLC_UP`, **passive scan: 25 networks**, rx buffers posted,
and a **stage-8 dry run**: every join setting accepted by the firmware (`wpa_auth`, `wsec`, PMK, `roam_off`), `en0`
attached, the join itself refused by the gate, transmit counters 0. No frame was ever transmitted.

Source (all in the A7-r3 kernel `ddf874fb`, checked below): `blazer_wifi.c` (gates), `blazer_pcie1.c`,
`blazer_bcm4390{,_ring,_scan,_join}.c` (join over the firmware supplicant, flow ring, **in-kernel DHCP, ARP, one ping**),
`blazer_wifi_net.c` (`en0` ifnet, IEEE80211 media word, network secret read from overlay group 26 and wiped),
`blazer_apple80211.c` (GET-only Apple80211 ioctl adapter), `BlazerWiFiServices.cpp`/`BlazerNetServices.cpp` (registry,
shared IONetworkStack). Host tests/mutants for these live on the Mac (`research/ios26-wifi-r1/tools`). USB:
`blazer_usbnet.c` (ECM `en2`, 192.168.77.2/24) exists; ECM bulk traffic and Mac binding are not physically proven.
Audits: `docs/reuse/2026-11-02/{wifi,usb-networking,darwin-services}.md`, `wifi-abi-r1/` (23G90 selector table).

The gap is therefore not a driver: **nothing has ever been sent**, the A7 tooling cannot express a join, and iOS
userland (configd, DNS, nw, Settings) knows nothing about `en0`.

## 3. Prior art (web + earlier audits)

- **itlwm / AirportItlwm** (OpenIntelWireless): two kexts over one OpenBSD-derived backend. `itlwm` is an
  `IOEthernetController`: Wi-Fi *spoofed as Ethernet*, joins driven by its own app (HeliPort); the project calls it
  the more stable one. `AirportItlwm` subclasses `IO80211Family` controller classes so the native Wi-Fi menu works,
  is less stable, per-macOS-release fragile, and cannot join hidden networks
  ([FAQ](https://openintelwireless.github.io/itlwm/FAQ)). Reusable: the **order** (Ethernet first, IO80211 later) and
  the split "our own joiner + Ethernet-like interface". Not reusable: GPL code, macOS-only IO80211 headers, Intel backend.
- **iOS in QEMU** (qemu-t8030 and forks): networking is USB, via a companion VM over a USB/TCP bridge; iOS's USB
  Ethernet is a thin Ethernet-over-bulk protocol (`AppleUSBEthernetDevice`, [Synacktiv](https://synacktiv.com/publications/ios-a-journey-in-the-usb-networking-stack),
  [NixOS wiki](https://wiki.nixos.org/wiki/IOS_Emulation)). Analogue of our ECM `en2`, not of Wi-Fi.
- **vphone-cli** (iOS 26 on Virtualization.framework): "touch, networking, and apps work", using Apple's own
  paravirtual vphone kernel/drivers ([repo](https://github.com/lakr233/vphone-cli)). Inference: not transferable to
  hardware; its service-profile planner is (darwin-services audit).
- **HakiOS** (`oosexgang/hakios-xnu-kernel`, APSL-2.0): `IO80211Controller` under `IOEthernetController`, attached to
  the DT `wlan` nub, plus a plain-C station ops table and an Apple80211 request layer. The best seam for step (c);
  already audited (`docs/reuse/2026-11-02/wifi.md` §1-2).
- **brcmfmac / OpenBSD bwfm**: shared-IPC max 7, no BCM4390/NCI; useful lifecycle references only (wifi.md §4-5).
- **Darling configd**: framework stubs, not an iOS network-state implementation (darwin-services.md).

What iOS 26 userland expects (source/static, `wifi-abi-r1`, darwin-services.md): configd's InterfaceNamer names
IONetworkInterfaces via IONetworkStack (`IOConnectSetCFProperties`, unimplemented here); IPConfiguration runs DHCP
for configured services; IPMonitor picks the primary service from `State:/Network/Service/*/IPv4` and writes the
resolver configuration (dnsinfo) that mDNSResponder serves; `nw`/NECP evaluate paths against kernel routes and that
state. wifid/WiFiManager and Settings additionally need Apple80211 SET operations, IO80211 events and the
IO80211 registry classes. "Wi-Fi as Ethernet" needs only the first three.

## 4. Staged plan

| Step | What | Effort | Risk | Evidence today |
|---|---|---|---|---|
| **W1** (a, first) | First transmit: stage 8 join of one owner WPA2-PSK network, firmware supplicant, flow ring, kernel DHCP, ARP, one gateway ping, on the A7-r3 line (Home, 5 cores) | **built here** (host tooling); 1 attended boot ~10 min | Medium: first ever TX; owner decision (it transmits); WPA2-PSK/transition only, not hidden, not WPA3-only; one lease, chip off after 120 s | dry run physical (all settings accepted); code in `ddf874fb`; composer + kernel-reader oracle host PASS |
| **W2** (a) | "Wi-Fi as Ethernet" for apps: keep kernel DHCP (mode 1); add DHCP option 6/15 capture to `take_dhcp`, expose the lease read-only (sysctl), and a small root daemon (same Mac build/sign/overlay pipeline as `hk_accel_once`) that writes `State:/Network/Service/hk-wifi/{IPv4,DNS}` with `InterfaceName=en0` to configd; `blazer_wifi_run=0`; lease renewal timer | 3-5 days host + 2 boots | Medium: IPMonitor accepting a State-only service is inference (VPN plugins do it); signing via existing renegade path; probe first with read-only `scutil`-style receipt (darwin-services §3) | none for userland yet |
| W2-alt | mode 2: configd's own DHCP on en0 | 1-2 weeks | High: needs IONetworkStack `setProperties` naming, a Setup service, IPConfiguration's Wi-Fi SSID checks via Apple80211 GET | source gap documented |
| USB | ECM `en2` over the existing gadget (`blazer_usbnet=1/2`, `tools/usbnet_mac.py`) | 1-2 boots + Mac binding | Medium-low: bulk DMA unproven, macOS accessory approval; no radio | console path physical (p29); ECM unproven |
| **W3** (b) | Production driver on the existing transport: interrupts or a lighter poll, lease renew, flow-ring delete/rejoin lifecycle (DHD `dhd_prot_flow_ring_delete`), disconnect/reconnect, roaming, power save, update the pinned firmware to Android's `.57.31` with its CLM, optional SAE (needs password or firmware SAE offload) | 2-4 weeks | Medium: lifecycle bugs leak DMA buffers; firmware update is a file swap but re-verify every boot fact | transport/scan/join physical up to dry run |
| **W4** (c) | Settings > Wi-Fi: HakiOS-style `IO80211Controller` under the DT `wlan` nub, station ops mailbox to the poll thread, scan snapshots + KEV events, Apple80211 SETs (SCAN_REQ 10, ASSOCIATE, DISASSOCIATE, POWER 19), wifid/WiFiManager + keychain for saved networks | 1-3 months | High: iOS 26 scan result/event layout unproven, wifid entitlements/keychain (cf. Bluetooth keychain lane) | selector table and GET adapter only |

Recommendation: W1 now (it is the only step whose result unblocks everything else, and its code is already in the
booted kernel), then W2 so Safari can resolve and fetch, then W3; W4 last. USB ECM is worth one boot as a
non-radio developer channel but does not lead to Wi-Fi.

## 5. W1, built on the host

Why tooling and not kernel code: the A7-r3 kernel `ddf874fb` already contains the join path, but (1) the A7 overlay
holds no network record, so the kernel would print `this image's overlay holds no network` and refuse; (2)
`tools/image_tool.py` admits only `blazer_wifi_stage=[0-3]` and no `blazer_wifi_join`; (3) the r3 line is 999 bytes
and the shim/XNU limit is 1023 (`pexpert/arm64/boot.h` `BOOT_LINE_LENGTH 1024`), so 50 bytes of join tokens do not fit.

Files (this directory):

- `tools/compose_wifi_join.py`: `overlay` appends one record (group 26, `f`, 0600 root:root,
  `/private/var/hkcover/wifi/net`, mkwifisecret's 108-byte BWN1 blob: PMK, never the password) to the pinned A7-r3
  overlay `artwork-container-battery-observe-r1.ovl` (7d610456…), every base record byte-identical and in order,
  header recomputed; output 0600 in `research/ios26-wifi-r1/secret/`, refuses overwrite, prints only hashes.
  `cmdline` derives the W1 line from the pinned r3 manifest: drops `hk_present_trace=1` and `blazer_battery_receipt=1`
  (both IOLog/receipt only: `sweet_present_trace.inc:59`, `SweetBattery.cpp:441`), adds `blazer_wifi=1
  blazer_wifi_stage=8 blazer_wifi_join=1` before `blazer_bootcpu=0x200`: **1008 bytes**, `receipts/w1-cmdline.txt`.
- `tests/kernel_oracle.c`: compiles the release tree's real `varfs_overlay.h` and real `blazer_bcm4390_join.c`
  (`b4_net_parse`) and walks the blob exactly as `blazer_wifi_net_secret` does (ASan/UBSan).
- `tests/test_compose_wifi_join.py` (14 tests, synthetic networks only): base accepted with 0 networks; composed blob
  accepted by the real reader (`ssid_len 11, open 0, country DK/DK, mode 0600`); base records byte-identical; password
  absent, PMK present; open+MAC variant; a flipped PMK byte -> `hash differs`; bad key/country/flags/length ->
  `network unusable`; secret readable by others refused; overwrite refused; cmdline limits and order.
  **Finding (host, real kernel code):** a mask that selected group 26 makes `hkov_cover_check` reject the *whole*
  overlay (`cover entry with no head before it in its group`), which on the phone is a varfs panic before launchd:
  bit 26 must never be in `hk_overlay`. Both the composer and the image_tool patch refuse it.
- `image_tool-w1.patch` (for `tools/image_tool.py`, not applied: that file has another owner's uncommitted edit;
  `git apply --check` passes on the current tree): admits `blazer_wifi_stage=[0-8]`, `blazer_wifi_join=1`,
  `blazer_wifi_run=[0-9]{1,3}`; `blazer_wifi_join=1` requires `blazer_wifi=1 blazer_wifi_stage=8`, an overlay holding
  group 26, a mask without bit 26 and a kernel with the network reader. `blazer_wifi_net`, `_ios`, `_idx_tcm`,
  `_mem_atu`, `blazer_usbnet` stay refused. `tests/test_image_tool_w1.py` (2 tests) PASS on a patched scratch copy
  and fail on HEAD as expected; HEAD's own `tools/test_image_tool.py` stays OK with the patch.
- `tests/run.sh`: builds and runs all of the above; ARM64 object `blazer_bcm4390_join.arm64e.o` (MH_MAGIC_64 ARM64
  E PAC00, defines `_b4_net_parse _b4_join_run _b4_join_heard _b4_join_event _b4_net_rx _b4_on_flow_created
  _b4_join_pre_up _b4_join_pre_clm`); A7-r3 unstripped kernel (de01876e…, stripped = ddf874fb) has
  `_b4_net_parse _b4_join_run _blazer_wifi_net_{secret,ready,addr} _b4_img_{fw,clm,txcap,nv_7311}` and the strings
  `blazer_wifi_join`, `blazer_wifi_stage`, `blazer_wifi_net`, `blazer_wifi_run`, `join: dry run done`,
  `en0 address err`, `the image holds a network`, `HKVarOverlay`. Receipts: `receipts/{tests,objects,image_tool-suite,image_tool-w1}.txt`, `receipts/SHA256SUMS`.

## 6. W1 attended boot (coordinator; owner present and has agreed that this boot transmits)

Owner, on the Mac only: `research/ios26-wifi-r1/secret/wifi.secret`, mode 600, `ssid=`, `password=` (WPA2-PSK,
8-63 chars), `country=DK` (where the phone is), optionally `mac=` from `mkwifisecret.py mac`. The network must be
visible (not hidden), WPA2 or WPA2/WPA3 transition, 2.4/5 GHz, with DHCP. Nothing secret enters git or a log.

```sh
# Mac checkout, after syncing research/ios26-connectivity-r1/wifi/ and applying image_tool-w1.patch
python3 -I research/ios26-wifi-r1/tools/mkwifisecret.py check
python3 -I research/ios26-connectivity-r1/wifi/tools/compose_wifi_join.py overlay      # prints sha256 = $OVL_SHA
python3 -I research/ios26-connectivity-r1/wifi/tools/compose_wifi_join.py check research/ios26-wifi-r1/secret/a7-r3-wifi-join.ovl
sh research/ios26-connectivity-r1/wifi/tests/run.sh   # needs the Mac's LLVM via LLVM=; or rely on the m1box receipts
python3 -I tools/image_tool.py image a7-wifi-join-r1 --kernel research/ios26-dualboot-r8/rootview/kernel.rootview \
  --kernel-sha ddf874fb41cf4871f39336a1bb3a7c77686d6f075e2fd8b7260a86707bd0b5f3 <a7-ios-system-r3 flags, with:> \
  --var-overlay research/ios26-wifi-r1/secret/a7-r3-wifi-join.ovl --var-overlay-sha $OVL_SHA \
  --phone-args '<r3 phone-args minus hk_present_trace=1 blazer_battery_receipt=1, plus blazer_wifi=1 blazer_wifi_stage=8 blazer_wifi_join=1>'
python3 -I tools/image_tool.py check research/images/a7-wifi-join-r1
# accept the image only if manifest.json cmdline == receipts/w1-cmdline.txt (sha256 913ab8d9…669459, 1008 bytes)
adb reboot bootloader
ANDROID_SERIAL=<serial> tools/bootios research/images/a7-wifi-join-r1/boot.img a7-wifi-join-r1 \
  --mach research/ios26-dualboot-r8/rootview/kernel.rootview.unstripped --wait 480
fastboot oem force-fastboot off && fastboot reboot
research/ios26-dualboot-r8/return-check.sh research/ios26-dualboot-r8/attempts/a7-wifi-join-r1-after-boot
python3 -I research/ios26-wifi-r1/tools/mkwifisecret.py wipe     # removes the composed overlay and image copies
```
The boot image itself embeds the PMK: keep `research/images/a7-wifi-join-r1/` local and delete it after the run.

Read in `ramdump/kernel.log` (`grep blazer-wifi`), in order: `the image holds a network`, `stage 8`, `fw: UP`,
`country DK`, `scan: ended … networks`, `join: next: try 1`, **`join: joined in N ms`**, `en0 attached, mode 1`,
**`net: address a.b.c.d … gateway …`**, **`en0 address err 0, default route err 0`**, **`net: gateway answered a ping
in N ms`**, `net: … frames in, … out`, `tidy: … errors 0x0` at ~120 s; Home still drawn (owner); return check PASS.
PASS = joined + address + ping. Stop/diagnose on `join: the 4-way handshake failed` (password/PMK), `the network was
heard on 0 records` (hidden, out of range or WPA3-only), `join: refused`, any panic other than the 300 s deadline.

## 7. Read-only Android commands wanted (coordinator runs them; root via Magisk `su` where noted)

```sh
adb shell 'ls -l /vendor/firmware | grep -iE "bcmdhd|4390|laguna_pcie"'
adb shell 'sha256sum /vendor/firmware/fw_bcmdhd.bin_4390_b1 /vendor/firmware/fw_bcmdhd.map_4390_b1 /vendor/firmware/bcmdhd.cal_USI_G7BB_7311_V11 /vendor/firmware/bcmdhd_clm.blob_4390_b1 /vendor/firmware/bcmdhd_txcap.blob_ROW'
adb shell 'strings /vendor/firmware/fw_bcmdhd.bin_4390_b1 | grep -m3 -E "FWID|version 27"'
adb shell 'su -c "lsmod | grep -iE \"bcmdhd|wlan|wonder\""'
adb shell 'su -c "ls /vendor_dlkm/lib/modules | grep -iE \"bcmdhd|wonder\""'
adb shell 'su -c "cat /sys/bus/pci/devices/0001:01:00.0/{vendor,device,revision,class}"'
adb shell 'su -c "cat /sys/module/bcmdhd4390/parameters/firmware_path /sys/module/bcmdhd4390/parameters/nvram_path" 2>/dev/null'
adb shell 'su -c "dmesg | grep -E \"Firmware version|fw path|clm|txcap|country\" | head -20"'
```
Purpose: compare Android's current `.57.31` files with the kernel's pinned `.57.30` copies
(`research/ios26-firmware-r1` MANIFEST on the Mac) before W3 updates them. W1 does not depend on the answers.

## 8. Suggested NOTES line (replaces nothing; Connectivity row stays)

- **Wi-Fi (2026-11-03, HOST):** chip BCM4390 rev 5 (b1) on PCIe `0001:01:00.0`; the A7-r3 kernel `ddf874fb` already
  holds the join + kernel DHCP path (stage-8 dry run physical). First transmit `a7-wifi-join-r1` is built on the
  host side (overlay composer, 1008-byte line, image_tool patch, kernel-reader oracle):
  `research/ios26-connectivity-r1/wifi/PLAN.md`. Needs the owner's network file and transmit consent.
