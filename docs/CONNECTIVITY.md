# Native connectivity

Scope: deliver independent native Wi-Fi, Bluetooth and cellular service on the self-contained Pixel iOS 26 port.

## Current result

- **Wi-Fi — physical:** BCM4390 firmware startup, DMA/ioctl and passive scanning have evidence; association, Settings join and packet service do not. The source adapter remains GET-only.
- **Wi-Fi — host/source:** the 23G90 scan/result/event layouts are statically characterized, but producer execution, cursor ownership, cancellation and event delivery remain unproved.
- **Bluetooth — physical/QEMU:** firmware/H4 replies and passive reception are physical evidence. QEMU observed real Security return statuses through interposition, but used a synthetic nub and proves neither daemon-to-chip attachment nor pairing.
- **Cellular — physical/source:** saved stock evidence identifies S5400 and XNU reads modem pads; CPIF references and a copied-RAM receive primitive are source/host work only. CP ownership, modem boot, SIM and data service are unverified.
- Passive scans, firmware responses, registered interfaces and source integration are not connectivity service.

## Remaining work

1. **Wi-Fi:** implement and validate the live scan producer/event contract, then station SET operations, association, address acquisition and reconnect.
2. **Bluetooth:** diagnose the observed daemon prerequisite without bypassing keychain semantics, then establish persistent daemon/chip attachment and real profile traffic.
3. **Cellular:** establish CP power/platform ownership and PCIe/DMA/MSI boot before RFS/GEMS, SIM, CommCenter and packet service.
4. Test each radio independently through native iOS Settings/services, preserving complete runtime evidence and Android firmware.

## Acceptance before expanding scope

- **Wi-Fi:** Settings discovers and joins a real network; DHCP, bidirectional traffic, DNS/TLS and disconnect/rejoin work repeatedly.
- **Bluetooth:** the real daemon and chip support Settings state, pairing, an owned peripheral/profile and clean reconnect.
- **Cellular:** native services report real SIM/network/data state before call, SMS and audio acceptance.
- Every result distinguishes physical from QEMU/host/source and binds a complete capture to its image and enabled gates.

## Evidence and source

- [Wi-Fi ABI host proof](../research/ios26-connectivity-r1/wifi-abi-r1/contract.json)
- [Bluetooth QEMU status result](../research/ios26-connectivity-r1/keychain-guest-r3/result.json)
- [Cellular reference manifest](../research/ios26-connectivity-r1/resources/manifest.json)
- [Wi-Fi integration handoff](../research/ios26-opt-20261102/handoffs/opt-wifi_scan_integration.md)
- [Bluetooth integration handoff](../research/ios26-opt-20261102/handoffs/opt-bluetooth_integration.md)
- [Bounded Bluetooth evidence](../research/ios26-connectivity-r1/bt3-evidence/)
