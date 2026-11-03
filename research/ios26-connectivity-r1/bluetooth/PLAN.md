# Bluetooth on the Pixel 10 Pro (iOS 26): path and first step

Written 2026-11-03 on m1box by the Bluetooth sub-agent. Host work and log reading only: no adb, fastboot or boot ran.
Evidence labels used throughout: **DT** (the stock tree), **SRC** (source), **HOST** (host tests or objects), **QEMU**,
**PHYS** (a log from an earlier phone boot). Anything inferred is marked *inference*.

## 0. Summary

- The controller is the **BCM4390B1**, the Bluetooth half of the Wi-Fi combo chip. It talks **H4 over the AP's LSIO_E
  CLI12 UART** (`uart@3a351000`, registers at 0x3a352000) with RTS/CTS. Power-on is DA9188 PMIC vGPIO `VBR_ON_IN` (REG_ON)
  after Wi-Fi's firmware is up. Earlier work already **brought the chip up on the phone**: ROM HCI Reset, firmware download
  (824,184 B, 3199 records), Launch RAM, 4 Mbaud with RTS/CTS, and a passive LE scan that received reports (PHYS, 2026-11-02).
- The kernel side bluetoothd needs also exists in the release XNU (SRC): the `com.apple.uart.sk.bluetooth` kernel control, a
  Skywalk kernel-pipe nexus and an H4 bridge with a transmit gate (`blazer_bt=5`). Its host and ARM64 tests pass. It has never
  run on the phone with bluetoothd attached.
- **The blocker sits above the transport, in the keychain.** The SWEET AppleKeyStore stub does not implement
  `aks_wrap_key` (selector 10) or `aks_unwrap_key` (11). Every keychain add on the phone fails: 33× `securityd sel 10 … ->
  0xe00002c7` in the A7 r3 Home boot, 40× in bt-fast-r1 (PHYS). bluetoothd's adds return errSecNotAvailable (-25291) and it
  exits(1) (QEMU). The Home boot also denies bluetoothd outright (`hk_deny: bluetoothd refused, EBADARCH`, PHYS).
- **First step, built (HOST):** a software `aks_wrap_key`/`aks_unwrap_key` (HMAC-SHA256 SIV on XNU's own corecrypto,
  per-boot secret, system bag only). It is default-off behind a compile gate and a boot-arg. It passes host tests, a
  known-answer cross-check, 6 rejected mutations, and ARM64 kernel objects for gate ON and OFF (OFF disassembly = baseline).
  The fix is system-wide: every daemon that writes the keychain needs it, not only bluetoothd.

## 1. Controller, transport, firmware, pins, regulators

| Fact | Evidence |
| --- | --- |
| BT node `/odm/btbcm`, `compatible = "goog,nitrous"` (Google's BT power/LPM driver), pinctrl `bt-dev-wake` (XAOC_GPIO1) + `bt-host-wake` (XAOC_GPIO2), function `aoc_cpm_eint` | DT `research/ios26-dualboot-r8/truth/fdt.dts:32241-32252`, 26894-26904 |
| `shutdown-gpios = <&da9188_vgpio 0x13>` = `DA9188_GPIO_VBR_ON_IN` (REG_ON); `bt-ble-dbo-le-gpios = <&da9188_vgpio 0x14>` = `VBR_ON_LE` | DT 32248-32249, `da9188-vgpio` line names at 16703-16712 (phandle 0x73c) |
| `device-wakeup-gpios = <&aoc_pinctrl 0x0d>`, `host-wakeup-gpios = <&aoc_pinctrl 0x16>`, `timesync-gpios = <&hsios_pinctrl 0x0e>` | DT 32245-32247; phandle 0x3d8 = `pinctrl@B400000` (AoC), 0x43e = `pinctrl@3C590000` (HSIOS) |
| UART `lsioe_cli12_uart: uart@3a351000`, `goog,goog-dw-apb-uart`, reg 0x3a352000/0x100, reg-shift 2, reset `<lsioe_resets 0x16>`, power-domain 0x71; `status = "disabled"` in this tree | DT 13338-13355; alias `uart12`/`serial1` (12444, 12499) |
| The same pins can be muxed to AoC (`BT2AOC_AP_UART_*_LOGI`, AoC pads 14-17) | DT 25922-25948; the Android HAL refers to a "CHRE BT UART" (strings) |
| Regulator `ldo_4m` "L4M_BT_AON", subsystem BT, 1.2 V, `monitor-only` (PMIC-managed, nothing to switch) | DT 15932-15939 |
| BT audio uses AoC I2S (`AOC2BT_I2S_*`, `BT2AOC_I2S_*`), not the UART | DT 25242, 25786-25824 |
| ROM answers: `HCI 13, manufacturer 15 (Broadcom), LMP subversion 0x4208`; after firmware: `BCM4390B1 P25 G7BB_BZ5 …`, HCI 14 | PHYS `research/laguna-usb-fix/attempts/20261102-071336-bt-fast-r1/ramdump/kernel.log` |
| Firmware: Android `/vendor/firmware/brcm/BCM_%d.hcd` / `BTFW_D.hcd`, config `/vendor/etc/bluetooth/firmware_config.json` (transport 101, 4 Mbaud); local copy `research/ios26-bt-r1/fw/BCM.hcd` (Mac, owner-approved, never in git) | strings of `research/ios26-bt-r1/vendor/bin/hw/android.hardware.bluetooth-service.bcmbtlinux`; `blazer_btuart_fw.c` |
| Proven sequence: Wi-Fi firmware up first, LSIO_E vote, CLI12 clocks (200 MHz), pads 24-27 to CLI12, 115200 8N1, vGPIO 39=1, REG_ON (vGPIO 38) low ≥30 ms then high, HCI Reset, Read Version, 0xfc79, Download Minidriver 0xfc2e, records, Launch RAM, Reset, 0xfc18 to 4,000,000 with DLF 2/16, RTS/CTS | PHYS bt-uart-r1, bt-fw-r1, bt-scan-r1, bt-fast-r1, bt-stream-r1 (`blazer_bt=1..4`); SRC `bsd/dev/blazer_btuart_hw.c` |

So this is **not** a serdev/tty problem left to solve. The AP UART driver, firmware loader, baud switch and REG_ON
sequence exist and work on the phone (`blazer_btuart_hw.c`, `blazer_btuart.c`). It is a combo chip, and the Wi-Fi side
must have its firmware up first (the code waits for `blazer_wifi_state == 1`).

## 2. What iOS 26 bluetoothd expects

| Item | Evidence |
| --- | --- |
| `BT_HCI_TRANSPORT` env, else "Attempting to read from plist"; `BT_CHIP`; prior runs set `BT_HCI_TRANSPORT=H4:POSIX;BT_CHIP=ACI~BT` via overlay `hk_env` | bluetoothd strings (`research/ios26-bt-r1/bluetoothd.strings`); `runtime/bt_keychain_trace/prepare.py` |
| Device paths present: `/dev/uart.bluetooth`, `/dev/cu.bluetooth`, `/dev/btwake`, `/dev/uart.log`; the modern UART path is the kernel control `com.apple.uart.sk.bluetooth` + `IOSkywalkNexusUUID` (socket option 0x40105412) and a Skywalk channel | strings; SRC `bsd/dev/blazer_bt_bridge.c` header (dada's reading), `hk_btsk.c` |
| PCIe chips go through `AppleConvergedIPCOLYBTControl` / `AppleBluetoothModule` / `ACIPCInterfaceTransport`. Not this chip | strings |
| `IODeviceTree` `local-mac-address`, `transport-encoding` on a `bluetooth` node. The phone ADT has none; QEMU used a synthetic nub (`compatible bluetooth,n88`, `transport-encoding 7`) | strings; `prepare.py`; `strings laguna.adt` (only `bluetooth-le` capability names) |
| Before opening the port, bluetoothd asks `com.apple.BlueTool` over XPC to run its "boot"/"init" script. Stock BlueTool answers "Unknown platform/chipset/manufacturer combination" here; a stand-in exists (`research/ios26-bt-r1/bluetool/bluetool.c`, dada, APSL) | its header comment; bluetoothd strings `BlueTool failed to run %s script` |
| Keychain at startup: 100 CopyMatching and 25 Update return -25300, **25 Add return -25291**, then exit(1) after ~1.7 s, respawn loop | QEMU `keychain-guest-r3/result.json`, its console (`exited due to exit(1), ran for 1750ms`) |
| The -25291 comes from the kernel: `SWEET AKS: securityd sel 10 arg0 0 in 2/32 out 1/128 -> 0xe00002c7` | QEMU same console (33×); PHYS bt-fast-r1 (40×), a7-ios-system-r3 (33×) |
| iOS 26 libaks: `aks_wrap_key` = `IOConnectCallMethod(c, 10, {handle, class}, 2, key, len, &class_out, 1, wrapped, &wlen)`; `aks_unwrap_key` = selector 11, scalars `{handle, class}`, wrapped in, key out | HOST disassembly of `_aks_wrap_key` (0x1e4ae4d80) and `_aks_unwrap_key` (0x1e4ae4b60) in `/data/hackios-qemu/dsc-r6` AppleKeyStore; securityd imports both (`llvm-nm -m`) |

**Minimal working path:** (a) keychain writes succeed (step 1, below); (b) bluetoothd runs (drop the `hk_deny` bit, add the
`hk_env` transport); (c) BlueTool's boot script succeeds (stand-in or env); (d) a `bluetooth` ADT node with
`local-mac-address`; (e) `blazer_bt=5` brings the chip up and hands the UART to bluetoothd through the bridge; (f) the gate
lets bluetoothd's init commands through. **Main risk at (f):** bluetoothd speaks Broadcom vendor commands (manufacturer 15) at
init, and the gate returns Unknown HCI Command for every vendor opcode. An explicit, reviewed VSC allowlist will probably be
needed (*inference*; the first B3 log will list them, because the bridge logs held opcodes).

## 3. Prior art (web and the 2026-11-02 reuse audit)

- **BrcmPatchRAM** (acidanthera): uploads Broadcom firmware (.hcd records, Download Minidriver, Launch RAM) to USB "RAMUSB"
  chips at boot and on wake; since macOS 12, BlueToolFixup patches the userspace stack instead of the kernel. Reusable: the
  firmware sequence, already done in `blazer_btuart_hw.c`; and the lesson that **userspace gating (board-id/chipset checks
  in bluetoothd/BlueTool) is the real obstacle once the HCI transport works**. Not reusable: USB transport, Lilu patching.
  [repo](https://github.com/acidanthera/BrcmPatchRAM), [README](https://github.com/acidanthera/BrcmPatchRAM/blob/master/README-Mac.md),
  [Monterey change](https://github.com/acidanthera/bugtracker/issues/1669).
- **IntelBluetoothFirmware / IntelBTPatcher**: firmware upload plus spoofing the host controller name to pass bluetoothd's
  and bluetool's board-id checks; also works around an iOS-derived bluetoothd crash on LE Scan Stop (status 718).
  Reusable: expect chipset/board checks in BlueTool/bluetoothd, and patch around them at the identity layer, not in HCI.
  [FAQ](https://openintelwireless.pages.dev/IntelBluetoothFirmware/FAQ), [releases](https://github.com/OpenIntelWireless/IntelBluetoothFirmware/releases),
  [#316](https://github.com/OpenIntelWireless/IntelBluetoothFirmware/issues/316), [#437](https://github.com/OpenIntelWireless/IntelBluetoothFirmware/issues/437).
- **Darwin serial HCI / iOS ports**: no public iOS port that runs bluetoothd over UART was found. The local dada/hakios work
  (Skywalk nexus, kctl, BlueTool stand-in) is the only Darwin-side prior art and is already integrated
  (`docs/reuse/2026-11-02/bluetooth.md`). Zephyr's H4 driver is an Apache-2.0 framing oracle; BlueZ btmon decodes captures
  offline; Linux `hci_bcm.c` is a GPL sequencing reference only. Frankenstein (QEMU emulation of Broadcom BT firmware) is a
  possible fake controller for QEMU, but heavy. [paper](https://arxiv.org/pdf/2006.09809.pdf)

## 4. Staged plan

| Stage | What | Effort | Risk | Acceptance (deciding line) |
| --- | --- | --- | --- | --- |
| **B1 (built)** | Software AKS wrap/unwrap, `0001` + `0002` | done on host; 1 Apple-clang kernel build + 1 boot | Low: off unless both gates are set; refuses everything but the system bag; boot only adds a token | `SWEET AKS: wrap/unwrap on`; `securityd sel 10 … -> 0x0`; no `wrap refused`; Home and touch as r3 |
| Q1 (optional, cheaper first proof) | QEMU keychain-guest re-run with a wrap kernel (prepare.py pins p29: needs p29+0001/0002 built on the Mac) | 1 build + 7 min guest | Low | trace shows `add` status 0 (not -25291); bluetoothd's next exit site (or no exit) |
| B2 | QEMU: bluetoothd unblocked (overlay env `H4:POSIX`, deny bit cleared), BlueTool stand-in, synthetic nub, `blazer_bt=5` bridge without a chip | 1-2 days | Medium: BlueTool XPC, unknown later prerequisites | `btsk:` channel connected; bridge counts bluetoothd's HCI Reset in `to_chip` |
| B3 | PHYS: Wi-Fi firmware + `blazer_bt=5 blazer_bt_tx=0` + B2's overlay/nub on the r3 line | 2-3 days + 2 boots | Medium-high: VSC allowlist, the 120 s serve bound, a boot-line budget of 1023 B (Wi-Fi + BT tokens ≈ +80 B: drop diagnostics) | bluetoothd's own Reset/Read Version reach the chip and its events come back (bridge counters), no exit(1) |
| B4 | Settings shows Bluetooth on; LE scan through bluetoothd (`blazer_bt_tx=1`) | 2-4 days | Medium | Settings device list fills from a real scan |
| B5 | Pairing/profiles (`blazer_bt_tx=2/3`, owner's word to transmit), persistent keys (a persistent AKS secret on ios_data: **owner decision**, see section 6), serve beyond 120 s, LPM via dev-wake/host-wake (AoC eint), suspend, SCO/A2DP over AoC I2S | weeks | High | owned peripheral pairs, reconnects after reboot |

## 5. Step 1 as built: `aks-wrap/`

Files (all MIT, original):
- `aks-wrap/src/blazer_aks_wrap.inc`: the core; no XNU types; compiles as C (host) and as C++ (kernel). Format and rules in its
  header comment. Deterministic AEAD: tag = HMAC(mac_key, "HKW1" | hdr | handle | class | key)[:16], key XOR HMAC(enc_key,
  tag | i). Blob 4+16+n bytes (52 for the observed 32-byte keys, under the 128-byte capacity). Class is echoed in `class_out`
  and bound into the tag. Handle must be 0 (system bag). Output is untouched on failure. Temporaries are zeroed. Keys are
  never logged.
- `aks-wrap/0001-sweet-aks-wrap-unwrap.patch`: release `iokit/Kernel/arm/SweetKeyStore.cpp` (+ the new `.inc`). Under
  `#if defined(BLAZER) && BLAZER_AKS_WRAP` it adds `kAKSWrapKey`/`kAKSUnwrapKey` cases. `start()` reads `blazer_aks_wrap=1`
  and draws a 32-byte `read_random` secret. HMAC is `cchmac(&ccsha256_ltc_di)` with C linkage. Unwrap writes its output
  without the `BLAZER_AKS_TRACE` copy, so key bytes never reach the trace. Without the boot-arg, both selectors still
  return kIOReturnUnsupported.
- `aks-wrap/0002-blazer-aks-wrap-build-on.patch`: adds `-DBLAZER_AKS_WRAP=1` to `MACHINE_FLAGS_ARM64_BLAZER`.
- `aks-wrap/image_tool-aks-wrap.patch`: admits `blazer_aks_wrap=1` in `tools/image_tool.py` `PHONE_ALLOWED` (dry-run
  applies to HEAD and to the current working copy). Not applied: `tools/` is the coordinator's.
- `aks-wrap/tests/test_aks_wrap.c`, `tests/reference.py`, `tools/check.py`, `receipts/check.json`, `receipts/commands.json`.

`python3 -I research/ios26-connectivity-r1/bluetooth/aks-wrap/tools/check.py` (HOST, PASS):
1. Host test under ASan/UBSan: round trips for classes 1-31 with flag bits and key sizes 1-64; every single-bit tamper of a
   blob fails; wrong class, handle, length or secret fails; output untouched on failure.
2. Known answer `686b0120…6497bcd` recomputed by an independent Python implementation written from the format comment.
3. Mutations, each built and then failing at run time: skipped tag compare, class not bound, handle not checked, class 0
   accepted, one keystream block only, length unchecked.
4. `0001` applies to release XNU 7227fe7 (`SweetKeyStore.cpp` 90c98eb4…) and reproduces `candidate/` byte for byte.
5. ARM64 Mach-O objects from the release build's own compile_commands entry (Mac paths mapped; upstream LLVM 23 instead of
   Apple clang, 3 kalloc_type builtins shimmed identically for all three objects, Apple-only flags dropped; listed in
   `check.json` `toolchain_shims`). ON: `sweet_aks_hmac` text, the wrap strings, undefined `_cchmac`, `_ccsha256_ltc_di`,
   `_read_random`, `cmp w22, #0xa`. OFF: none of them, and its disassembly hash equals the baseline's (61559d35…).
   The checker caught two real bugs before PASS: the block came before the selector enum, and `cchmac` had C++ linkage.

**Not proved:** a full kernel link (Apple clang, Mac); that securityd accepts the blob at runtime (it treats the wrapped key
as opaque bytes plus a length: *inference* from the `ks_crypt` strings); that bluetoothd gets past startup (B2); anything
about the phone.

### Exact attended boot B1 (coordinator; one variable: the AKS wrap)

Build on the Mac: the release XNU at the commit that produced the A7 r3 kernel `ddf874fb…` (kernel.rootview, release HEAD
7227fe7 "root view…"), plus `git apply aks-wrap/0001-sweet-aks-wrap-unwrap.patch aks-wrap/0002-blazer-aks-wrap-build-on.patch`.
Same build as kernel.rootview, giving kernel `K` (unstripped `K.unstripped`, sha `KSHA`). Before booting, check:
`nm K | grep -E '_cchmac$|_ccsha256_ltc_di$'` both defined, and `strings K | grep 'SWEET AKS: wrap/unwrap on'`.
Apply `aks-wrap/image_tool-aks-wrap.patch` to `tools/image_tool.py`.

```sh
python3 -I tools/image_tool.py image b1-aks-wrap-r1 --kernel K --kernel-sha KSHA \
 --phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl \
 --var-overlay-sha 7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58 \
 --phone-args "blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_battery_receipt=1 blazer_aks_log=1 blazer_aks_wrap=1" \
 --phone-deadline 300
python3 -I tools/image_tool.py check research/images/b1-aks-wrap-r1
# accept only if manifest.json cmdline == research/ios26-connectivity-r1/bluetooth/b1-cmdline.txt
#   (998 bytes, sha256 296b3c0f491497f1751b4ff9acce83dc5200d0ba22bc308cd673e234c05adabd: r3's line minus hk_present_trace=1, plus blazer_aks_wrap=1)
tools/bootios research/images/b1-aks-wrap-r1/boot.img b1-aks-wrap-r1 --mach K.unstripped --wait 480
# then: force-fastboot off, reboot, return-check.sh attempts/b1-after-boot   (bare fastboot boot, ANDROID_SERIAL set)
```

Read from `ramdump/kernel.log`:
- PASS: `SWEET AKS: wrap/unwrap on` once; `securityd sel 10 arg0 0 in 2/32 out 1/128 -> 0x0`, and the count of `-> 0xe00002c7`
  for sel 10 is 0 (r3: 33); no `SWEET AKS: wrap refused` / `unwrap refused`; any `securityd sel 11 … -> 0x0` is a bonus
  (read-back); Home visible, touch and Settings as in r3 (owner); Android return check PASS.
- STOP and keep the capture: any `refused`, a securityd crash loop, Home lost, a panic other than the 300 s deadline.
- Expected and unchanged: `hk_deny: bluetoothd refused` (bit 31 stays on, deliberately; bluetoothd is B2/B3).
- Rollback: boot r3's image again (nothing persists: root read-only, `/private/var` in RAM).

## 6. Decisions and holds

- **Owner decision before B5:** this AKS is software. Data-protection classes are all "available" (as the existing stub
  already reports: no passcode, unlocked). With a per-boot secret nothing outlives a boot, which matches the volatile
  `/private/var`. Persistent pairing keys need the secret stored somewhere (ios_data). Anyone who can read that partition can
  then read the keychain. That trade-off is the owner's call; the apps lane's AKS user-session keybag
  (`research/ios26-apps-r1/receipts/h3-static-r12/VERDICT.md`) is the same question.
- Transmitting levels (`blazer_bt_tx=2/3`) need the owner's word, as the gate says.
- Keep `bt_addr` (stock DT), serials and `BCM.hcd` out of git.

## 7. Read-only Android commands for the coordinator (B3 preparation)

All read-only (`su -c` as Magisk root). Output that holds addresses (`dumpsys`) goes to ignored research only.

```sh
adb shell su -c 'ls /proc/device-tree/odm/btbcm/; cat /proc/device-tree/odm/btbcm/compatible; echo; cat /proc/device-tree/uart@3a351000/status; echo'
adb shell su -c 'ls -l /sys/bus/platform/devices/ | grep -i -E "3a351000|btbcm|nitrous|odm"; ls -l /sys/bus/platform/devices/*3a351000*/driver 2>&1'
adb shell su -c 'ls -l /dev | grep -i -E "ttys|tty[A-Z]|bt|lpm|nitrous|aoc"'
adb shell su -c 'p=$(pidof android.hardware.bluetooth-service.bcmbtlinux); echo pid $p; ls -l /proc/$p/fd | grep /dev/'
adb shell su -c 'lsmod | grep -i -E "nitrous|bluetooth|bt|serial|uart|aoc"'
adb shell su -c 'ls -l /vendor/firmware/brcm/ /vendor/etc/bluetooth/; sha256sum /vendor/firmware/brcm/*.hcd'
adb shell su -c 'cat /vendor/etc/bluetooth/firmware_config.json'
adb shell su -c 'getprop | grep -i -E "bluetooth|\.bt\.|hci"'
adb shell su -c 'dmesg | grep -i -E "nitrous|btbcm|bluetooth|3a35|uart|lpm" | head -80'
adb shell dumpsys bluetooth_manager | head -40
```

The decisive questions: which `/dev` node the HAL holds open (AP CLI12 tty or an AoC/CHRE path), whether the DTBO turns
`uart@3a351000` on, and the transport fields in `firmware_config.json` (LPM, baud, the CHRE handover).
