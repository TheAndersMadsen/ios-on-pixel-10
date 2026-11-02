# Wi-Fi reuse audit — 2026-11-02

The shortest route is to finish the existing BCM4390 transport and reuse the
HakiOS Darwin-facing station interface. Replacing the radio driver with bwfm,
brcmfmac or itlwm would add substantial work and lose working hardware support.
The smallest useful first change is registry discovery, which needs no new
radio operation. These are research findings; no code was integrated or run.

## Current implementation, checked against source

Target: BCM4390 revision 5, PCI vendor/device `14e4:4438`, NCI backplane,
firmware IPC version 9. The recorded physical result is firmware startup,
working DMA/ioctls and a passive scan. There is no verified association,
packet exchange, Settings join or internet result on this phone.

Source inspected under `research/ios26-release-r1/work/xnu/` at local release
commit `237e3889640333558525c8082593e68cc5401405`:

- `bsd/dev/blazer_bcm4390_ring.c`: existing IPC9 rings, request identifiers,
  flow-ring creation, TX and RX. This implementation already works far beyond
  PCI discovery; do not redo that work.
- `bsd/dev/blazer_bcm4390_join.c` and `blazer_wifi_net.c`: kernel-controlled
  join, firmware security setup, `en0`, mbufs and DHCP/packet scaffolding.
  Built source does not establish a successful physical join.
- `bsd/dev/blazer_apple80211.c` and `blazer_wifi_ios.h`: actual GET-only adapter,
  already integrated as release series `1156`, originating in feature `1136`.
  The request envelope is 40 bytes, with its user pointer at offset 32.
  Every SET fails with `EOPNOTSUPP`; capabilities do not claim scan or join.
  Its observed link state requires the existing fully keyed native callback.
- `iokit/Kernel/arm/BlazerWiFiServices.cpp`: existing interface discovery objects;
  `BlazerNetServices.cpp` owns the shared, once-published `IONetworkStack`.
  Do not introduce a second copy of these class names for Wi-Fi.

The older `handoffs/wifi.md` and `handoffs/wlbt.md` say the entire Apple80211
adapter is missing. `handoffs/feature-wifi.md` and current source supersede that
claim. The remaining work is a serialized station service, complete scan
snapshots/events, implemented SET operations, repeatable teardown/rejoin and
runtime verification. No new build or boot was performed for this audit.

## 1. HakiOS discovery contract: high priority, high source confidence

Verified current upstream: `oosexgang/hakios-xnu-kernel` main at
`96ffbc532e970f3540885755d457e401e04d4707`.
Its [directory-specific licence](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/LICENSE)
assigns `drivers/` and kernel files to APSL-2.0; the tools' MIT licence does
not apply to these driver files.

[HakiosWLANStart and its class hierarchy](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/drivers/wifi/hakios.wlan.cpp)
provide a concrete missing delta: `IO80211Controller` derives through
`IOEthernetController` and `IONetworkController`; it attaches under the real
`wlan` device-tree service and writes the radio's `local-mac-address` there.
Current Blazer derives directly from `IOService`, attaches at the root and
only sets `IOMACAddress` on its controller.

Upstream comments connect this contract to MobileGestalt address lookup and
LaunchServices waits. That is an upstream diagnosis, not measured evidence of
our current lag. It nevertheless gives a small, testable improvement without
implementing association or adding a fake identity.

**Integration task:** extend the existing Blazer class hierarchy and publication
routine, preserving its failure cleanup. Resolve the actual `wlan` service,
publish its observed address and attach the controller below it. Coordinate
any shared class names with USB networking. If no suitable node/address is
available, report that state; do not fabricate successful discovery.

**First host proof:** extend the existing `feature-wifi-r1` IOKit shim test to
check class ancestry, parent attachment and byte-exact property placement,
including missing-node and allocation/attach failures. Later emit gated ARM64
objects and inspect symbols. A separate runtime check must establish actual
IORegistry matching and whether lookup waits change. Labour saved: reuse a
known Darwin discovery shape rather than rediscovering each consumer's query.

## 2. HakiOS station/Apple80211 interface: high priority, medium port confidence

The same pin supplies [hakios.sta.c](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/drivers/wifi/hakios.sta.c),
[the plain-C station contract](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/xnu/files/bsd/sys/hakios.sta.h)
and [hakios.apple80211.c](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/drivers/wifi/hakios.apple80211.c).
These are APSL-2.0 candidates for adaptation, not a hardware driver to transplant.

`hakios_sta_ops` separates `scan`, `heard`, `join`, `leave`, `state`, `power`
and supported channels. `sta_runs` serializes potentially blocking operations;
`hakios_sta_ask_scan` queues requests. The Apple80211 side supplies request
conversion, bounded user-memory transfers, scan iteration and event reporting.
That structure can save handwritten Darwin protocol work.

It cannot call our `b4_ioctl` directly from the HakiOS worker: the existing
BCM4390 polling thread owns all hardware state, and the transport has one
in-flight ioctl. Put a bounded mailbox between the generic station layer and
that owner. Keep user copying outside device/state locks, and report actual
operation completion rather than treating request acceptance as a finished scan.

The current scan parser's `on_network` retains deduplication BSSIDs and the
chosen join target, not a full list of SSID/security information elements.
Expose a bounded snapshot callback before records are discarded. HakiOS's BSS
contract requires frequency, RSSI, beacon interval, capability and bounded IEs.
Version-114 Broadcom records must be validated and converted; never cast them
to Apple80211 or HakiOS structures. iOS16.5 request layouts remain a compatibility
check against the current iOS26 GET adapter and observed requests.

**First host task:** implement only mailbox ordering/cancellation plus a passive
scan snapshot converter, using synthetic Broadcom records. Exercise malformed
lengths, duplicate BSSIDs, IE truncation, full queues, timeout/teardown and
out-of-order completion. Keep association and unsupported active scans refused.
Then enable only the scan selectors whose ABI and completion path are proven.
Missing pieces include an enduring service loop and trustworthy supported-channel
data. Full network control must also coordinate configd naming; see the
Darwin-services audit. This avoids a wholesale networking-family port.

## 3. Matching Broadcom DHD: protocol reference, not a drop-in XNU library

Verified source: GrapheneOS **GitLab** `kernel_pixel_6.12` at
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`.
Its [dhd_msgbuf.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/wlan/bcmdhd/bcm4390/dhd_msgbuf.c)
and [dhd_pcie.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/wlan/bcmdhd/bcm4390/dhd_pcie.c)
contain NCI/IPC9 support. The public GitLab file API supplied the actual bytes;
`include/bcmmsgbuf.h` and `include/bcmpcie.h` matched our local downloaded headers
byte for byte. The similarly named GitHub repository returned 404: use GitLab.

The inspected files carry GPLv2 plus Broadcom's independent-module linking
exception. That does not turn modified DHD code into MIT/APSL. Existing Blazer
transport deliberately uses newly written code and protocol facts; maintain
that boundary unless an explicitly attributed/licensed import is selected.

`dhd_prot_flow_ring_delete`, its completion handler and
`dhd_bus_flow_ring_delete_request/response` describe the missing rejoin lifecycle:
stop accepting packets, publish deletion, retain resources until a valid
completion, then reclaim. The source includes phase/epoch handling and optional
fast-delete completion semantics. Use the negotiated protocol, not every option.

**Integration task:** extend the existing `b4_flow_create` state machine with
delete-pending/confirmed-deleted states before allowing a subsequent join.
First host proof: modeled delayed/wrong-ring/duplicate completions and deletion
with pending TX must never free live DMA buffers or acknowledge a missing
completion. Labour saved: derive the missing lifecycle from the matching vendor
protocol rather than rediscovering it on repeated phone boots.

An older local vendor mirror is
`research/upstream/patch-scout-chips/pixel10-aosp`,
`azagramac/pixel10-kernel-aosp@6f689be7fa23ce6c6a30a5895e290c3892706486`.
Its [4390 PCI code](https://github.com/azagramac/pixel10-kernel-aosp/blob/6f689be7fa23ce6c6a30a5895e290c3892706486/private/google-modules/wlan/bcmdhd/bcm4390/dhd_pcie.c)
also explicitly handles NCI and IPC9. The primary Google [BCM4390 repository](https://android.googlesource.com/kernel/google-modules/wlan/bcmdhd/bcm4390/)
provides another cross-check: its `android-16.0.0_r0.10` tag resolves to
`2f66b21f47d4f6ab5bd87511c894b1782d04e742`, verified through Gitiles.
That historical tag is not proof of identity with the current phone firmware;
prefer the existing verified 6.12 header/source pin over an unrelated newer tree.

## 4. OpenBSD bwfm: permissive lifecycle reference, incompatible whole driver

Verified pin: `openbsd/src@f02979fb6bb9b62f36ddab3241c07c258c7c5e66`.
[if_bwfm_pci.c](https://github.com/openbsd/src/blob/f02979fb6bb9b62f36ddab3241c07c258c7c5e66/sys/dev/pci/if_bwfm_pci.c)
and [its header](https://github.com/openbsd/src/blob/f02979fb6bb9b62f36ddab3241c07c258c7c5e66/sys/dev/pci/if_bwfm_pci.h)
carry ISC-style permissions in the files. `bwfm_pci_flowring_delete` and its
callback illustrate request/closing/completion/free separation.

However, `BWFM_SHARED_INFO_MAX_VERSION` is **7**, and the PCI match table lacks
BCM4390. Our actual firmware is IPC9/NCI. Raising a constant or adding the PCI ID
does not implement its chip initialization or changed shared structures.
OpenBSD bus_dma, net80211 and firmware infrastructure also do not exist in our
XNU port. Reuse a small attributed helper only if its exact semantics match;
otherwise use it as an independent review reference for the existing lifecycle.
This is lower priority than the matching DHD description.

## 5. brcmfmac and AirportItlwm: useful negative results

Current Linux pin `6628e7d4c6b25c8d18f1345e3a20d21829aae7e4` still defines
maximum shared IPC version 7 in [brcmfmac/pcie.c](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c).
That file is ISC, but permission does not supply IPC9/NCI support. The local
linux-next copy agrees. Porting its Linux bus/net stack is a worse first step
than completing the existing successful transport.

Verified `OpenIntelWireless/itlwm` master pin:
`53c51c2cdd6e4b69beb91f310d74c53422b0f8bd`.
[AirportItlwm.cpp](https://github.com/OpenIntelWireless/itlwm/blob/53c51c2cdd6e4b69beb91f310d74c53422b0f8bd/AirportItlwm/AirportItlwm.cpp)
is GPL-2.0-or-later and depends on functional macOS IO80211 controller/workloop
methods plus an Intel/OpenBSD backend. It does not supply a BCM4390 driver or
our iOS26 socket-fallback contract. Avoid importing legacy macOS private-class
headers expecting them to implement the absent networking families.

Tegu's BCM4383 driver is an AI-backplane reference, not our NCI chip driver,
and its absent licence prevents copying. The local Rotten Apple patch bundle
targets MediaTek and has unresolved origin/licence; neither its hardware half
nor unlicensed Apple80211 fragments should replace the licensed HakiOS seam.

All proposed radio-bearing runtime checks remain with the phone coordinator.
This audit performed source/network reads only: no device operation, association,
transmission, firmware download, executable test, build or deployment.
