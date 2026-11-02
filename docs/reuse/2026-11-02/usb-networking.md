# USB, Mac services and USB networking reuse audit

Audit date: 2026-11-02. Source inspection only; no build, test run, device access,
host network change or implementation change. Public source snapshots and pins
are under ignored `research/reuse-audit-20261102/usb-networking/upstream/`.
GitHub REST returned rate-limit errors; upstream heads were verified with
read-only `git ls-remote`, then individual pinned source files were inspected.

## What already exists

- Physical p29 console acceptance is established by the current `NOTES.md`:
  1,533,021 USB bytes matched the RAM capture. Older usbcon handoffs saying
  "never booted" are stale. Preserve this controller implementation.
- The current release workspace already contains CDC-ECM descriptors, DWC3 bulk
  transfer code, notifications and an XNU `en2` bridge in
  `osfmk/arm64/blazer_usbcon_core.inc` and `bsd/dev/blazer_usbnet.c`.
  The latter also contains the `blazer_usbnet_bounds` integration from 1301;
  do not import the discarded alternate ECM prototype or reapply that patch.
- ECM bulk traffic, Mac driver binding, bidirectional ICMP and application DNS
  remain physically unproved. Console success is not bulk-DMA acceptance.
- The existing mux package has a real MIT device-side protocol core and XNU
  socket adapter. Its lifecycle repair is in
  `research/ios26-feature-usb_mac-r1/patches/0903-mux-transport-lifecycle.patch`.
  The current release gadget reserves mux endpoints but has no `bmx` callback
  wiring. Do not launch a second DWC3 owner to add that transport.
- Existing QEMU mux captures negotiate version 2 but return zero service
  payload bytes from real lockdownd. QueryType, pairing and Finder are not
  demonstrated. A fake lockdownd host test does not close this gap.

## Ranked candidates

| Priority | Candidate | Reuse mode | Main saving | Confidence |
|---|---|---|---|---|
| P1 | TinyUSB ECM plus Zephyr ECM | Small licensed adaptations | Transfer termination and control-request rules | High for source, untested on this gadget |
| P1 | usbmuxd + libusbmuxd + libimobiledevice | Independent host oracle and clients | Avoid another handwritten host/protocol/service stack | High for APIs; real iOS26 service acceptance pending |
| P2 | Linux DWC3 and ECM | Reference; GPL implementation only by explicit integration choice | Exact controller termination/cancellation contracts | High for generic DWC3, platform ownership still local |
| P3 | FreeBSD xHCI + USB core | Substantial BSD-licensed port | Avoid writing a host stack from scratch | High source availability, large adapter gap |

## 1. Reuse class logic without replacing the working gadget

**TinyUSB pin:** `925f77a192a3ace01fa3617fac9ceb328ca9b280`, MIT at file level.
Its [`netd_xfer_cb`](https://github.com/hathach/tinyusb/blob/925f77a192a3ace01fa3617fac9ceb328ca9b280/src/class/net/ecm_rndis_device.c#L344)
sends a zero-length transfer after a nonempty exact-maxpacket IN completion.
`netd_control_xfer_cb` contains the ECM packet-filter and alternate-interface
logic. This is small enough to adapt to existing queue/completion callbacks.
There are unresolved endpoint-close TODOs in that same implementation; importing
the whole state machine would not solve teardown.

**Zephyr pin:** `0534e997eacb94bae1df6c9a7dd4a9a6cbf1cecf`, Apache-2.0.
Its [`cdc_ecm_send` and `usbd_cdc_ecm_ctd`](https://github.com/zephyrproject-rtos/zephyr/blob/0534e997eacb94bae1df6c9a7dd4a9a6cbf1cecf/subsys/usb/device_next/class/usbd_cdc_ecm.c#L427)
provide an independent explicit-ZLP path and reject unsupported data-bearing
class requests. Zephyr buffer/semaphore/USB APIs are not XNU APIs; reuse the
small rules with notices, rather than adding an RTOS dependency.

**Local seam:** `un_setup` currently acknowledges any no-data class request with
type `0x21` and low byte of `wIndex` equal to zero. It does not require request
`0x43` or check the complete interface index. `un_tx_pump` adds one byte to
512-byte multiples. These are narrowly bounded places to improve.

Padding is not automatically proof of broken traffic: Linux deliberately
retains that fallback for controllers without ZLP support. Strict original
Ethernet-frame preservation and a real DWC3 ZLP path are the cleaner target.
No evidence connects this behavior to the prior macOS accessory-policy block.

**First task:** add an isolated ECM conformance change to the existing gadget:
exact supported control requests/full interface index, and explicit ZLP
completion with no extra Ethernet byte. Test actual-source descriptor/control
dispatch and TRB output for 511/512/513, 1023/1024/1025 and maximum frame sizes;
require original payload equality, ZLP after each exact-maxpacket frame, queue
capacity accounting and reset/unconfigure cancellation. Keep the console-only
and gate-off regression suites. These are host proofs; bulk DMA and Mac binding
still require the coordinator's separately scheduled physical acceptance.

**Not a DWC3 driver shortcut:** the inspected TinyUSB supported-controller list
and Zephyr's [UDC build manifest](https://github.com/zephyrproject-rtos/zephyr/blob/0534e997eacb94bae1df6c9a7dd4a9a6cbf1cecf/drivers/usb/udc/CMakeLists.txt)
include DWC2, not a DWC3 backend. The expected DWC3 source paths returned 404.
Do not equate Synopsys DWC2 with this phone's DWC3 hardware.

## 2. Stop maintaining both ends of the mux protocol by hand

**usbmuxd pin:** `3ded00c9985a5108cfc7591a309f9a23d57a8cba`.
The inspected [`device.c`](https://github.com/libimobiledevice/usbmuxd/blob/3ded00c9985a5108cfc7591a309f9a23d57a8cba/src/device.c#L186)
and `usb.c` are GPL version 2 or 3. `send_packet`, `device_data_input`,
`device_start_connect` and `connection_teardown` implement the host complement
to our MIT `bmx_*` core, including sequence fields and fragmented transfers.
Use them in a separate host test process or adapter, without copying GPL
implementation into the MIT kernel core.

**libusbmuxd pin:** `93eb168bf6b07472d17781328c21df0c60300524`, LGPL-2.1-or-later
in the inspected files. [`usbmuxd_connect`, `usbmuxd_send`, `usbmuxd_recv_timeout`](https://github.com/libimobiledevice/libusbmuxd/blob/93eb168bf6b07472d17781328c21df0c60300524/src/libusbmuxd.c#L1532)
are the host-client layer, not device bulk-gadget implementations.
`USBMUXD_SOCKET_ADDRESS=UNIX:<private path>` supports a private daemon/socket
fixture, avoiding interference with the Mac's system daemon.

**libimobiledevice pin:** `fa0f79190142bc309307967c058f89c1b36eb6b8`,
LGPL-2.1-or-later in the inspected library source. Its
[`lockdownd_query_type`](https://github.com/libimobiledevice/libimobiledevice/blob/fa0f79190142bc309307967c058f89c1b36eb6b8/src/lockdown.c#L358)
and higher-level clients replace hand-built plist framing and later pairing,
session, TLS and service requests. A constructed client alone is insufficient:
`lockdownd_client_new` logs a failed QueryType and can still return a client.
Acceptance must check the actual returned type and service bytes explicitly.

**First task:** connect the unchanged upstream host mux implementation to the
current actual `blazer_mux_core.c` via an in-memory/socket transport adapter.
Exercise deliberately unequal TX/ACK sequences, fragmented max-size messages,
window exhaustion, closed/refused sockets, version renegotiation and repeated
disconnect. This supplies independent coverage missing from two mutually
agreeing handwritten endpoints. Then run the existing coordinator-owned QEMU
real-lockdownd harness with corrected host lifecycle; require nonzero response
bytes and exactly `com.apple.mobile.lockdown`. If silent, instrument actual XNU
socket receive/send and lockdownd accept/read instead of guessing peer refusal.

**Missing dependencies:** current mux bulk callback wiring and cancellation,
XNU socket behavior, daemon registry matching and real service processing.
The upstream host [`usb.c`](https://github.com/libimobiledevice/usbmuxd/blob/3ded00c9985a5108cfc7591a309f9a23d57a8cba/src/usb.c#L754)
filters Apple VID/product ranges; it will not discover the current custom
console identity automatically. Test transport injection does not establish
native macOS discovery. USB networking is a separate ECM interface, not usbmuxd
tethering. This route saves host software work, not the device adapter.

## 3. Linux is an exact controller contract reference

**Pin:** `6628e7d4c6b25c8d18f1345e3a20d21829aae7e4`, verified upstream master.
[`ecm_setup` and `ecm_set_alt`](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/usb/gadget/function/f_ecm.c#L460)
check complete class request fields and manage active versus inactive data
interfaces. `f_ecm.c` and `u_ether.c` are GPL-2.0-or-later. The latter explicitly
distinguishes normal ECM ZLP framing from its padding fallback.
[`dwc3_needs_extra_trb`](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/usb/dwc3/gadget.c#L1428)
and nearby TRB preparation are GPL-2.0-only and document the controller side.
Read these alongside our existing TRB model; no Linux gadget framework port is
needed for the small class fix. Linux runtime-PM, DMA and platform callbacks
cannot replace local Tensor ownership/reserved-memory checks.

[FunctionFS](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/Documentation/usb/functionfs.rst)
supplies userspace functions on top of Linux's gadget/UDC/VFS infrastructure.
It does not provide the missing XNU device-controller layer.
TinyUSB/Zephyr NCM aggregation is a later optimization; native ECM correctness
and actual network packets should come first. No throughput benefit is claimed.

## 4. A host stack exists, but remains a separate project

The already discovered FreeBSD source is a real reusable alternative to writing
xHCI from scratch: [`xhci.c`](https://github.com/freebsd/freebsd-src/blob/584f44221f45c5c26ec2a2888a3815c6f34bfad0/sys/dev/usb/controller/xhci.c)
at `584f44221f45c5c26ec2a2888a3815c6f34bfad0`, BSD-2-Clause.
`xhci_init` checks 4K controller pages and derives layout/context/DMA widths;
the surrounding USB core, hub, transfers and process machinery are also needed.
XNU uses 16K VM pages, so a real suballocator plus busdma/cache synchronization,
locks/callouts and bus-space adapters must precede meaningful compilation.

Current `blazer_xhci_preflight` only parses saved capabilities; it is not that
adapter or an enumerating host stack. Apple's public IOUSBFamily directories
are not a shortcut: the prior pinned inventory found key controller files
empty, and old APIs do not establish iOS26 IOUSBHostFamily compatibility.
DP altmode also has independent Type-C/PHY/AUX/DPU dependencies and does not
intrinsically require xHCI enumeration.

## Shared integration prerequisite

App-level USB networking needs more than kernel `en2`: share one real-ifnet-bound
IONetworkStack/configd naming implementation with Wi-Fi. The current service
publishes a name but lacks the `IOConnectSetCFProperties` registration path;
see [the Darwin services audit](darwin-services.md). Kernel ARP/ICMP, configd
address/resolver setup, Safari traffic and Internet/NAT are separate acceptance
steps. No host network settings or security restrictions were changed here.
