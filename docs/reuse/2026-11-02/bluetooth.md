# Bluetooth reuse audit — 2026-11-02

The useful imports are protocol diagnostics and independent transport tests.
No audited stack supplies the iOS 26 daemon-to-driver contract as a drop-in.
The existing AP UART and H4 bridge should remain the integration point.

## Local state checked

- Read `NOTES.md`, the BT/WLBT/feature-Bluetooth handoffs and actual release sources.
- Release checkout observed at `237e3889640333558525c8082593e68cc5401405`.
- `bsd/dev/blazer_bt_bridge.c` and `blazer_btuart.c` compare byte-identical with
  `research/ios26-feature-bluetooth-r1/src/`: the 1136 lifecycle work is already
  present. Do not assign an agent to reimplement it from the older handoff.
- The bridge already implements one-client ownership, stopped-state refusal,
  queue/partial-frame clearing and the existing Skywalk/kernel-control path.
- `blazer_bt_gate.c` already frames command, event, ACL, SCO and ISO packets;
  ISO lengths use the 14-bit field, and oversized packets are discarded whole.
- Mode 5 still serves for a bounded 120 seconds. Persistent service, restart
  after controller drain, nexus teardown and concurrent lifecycle proof remain.
- The transport names `com.apple.uart.sk.bluetooth`, a nexus UUID socket option
  and the H4 environment route come from existing local porting work. A generic
  BLE host does not replace these interfaces.
- Existing physical evidence establishes legitimate firmware, H4 responses and
  a clean bounded passive scan at 4 Mbaud with RTS/CTS. It does not establish
  Bluetooth Settings, pairing or an iOS profile working through this bridge.
- Existing source attributes bridge/control ancestry to dada/APSL. That comment
  is not a fresh provenance audit or permission to redistribute every derivative.

An important handoff correction: `research/ios26-bt-r1/runs/bt-3/` now contains
`console.log` and `exit.json`, unlike the earlier handoffs. The saved exit receipt
reports elapsed 1500.9 seconds, host exit 0 and unchanged root. Its 1.3 GB console
contains a `bluetoothd` exit(1) with return frames. The capture also reports about
1.034 GB of lost log bytes, so missing transport messages cannot prove a complete
absence of activity. No cause of the daemon exit was established by this audit.

## Priorities

| Priority | Candidate | Reuse class | Confidence | Labour saved |
|---|---|---|---|---|
| P0 | Existing bt-3 result and integrated 1136 | Already local | High | Avoid a redundant guest run and duplicate lifecycle work |
| P1 | BlueZ offline HCI decoding | Existing host tool | High | Avoid handwritten opcode/event dissectors |
| P1 | Zephyr H4 receive/stop behaviour | Independent test reference; selective Apache code | High | Avoid inventing framing and buffer-exhaustion cases |
| P2 | NimBLE socket transport | Licensed optional host fixture | Medium | Reuse a second implementation for stream tests |
| P2 | Linux BCM setup/lifecycle | Reference only for this plan | High for protocol, limited for board | Check known command sequencing without guessing |
| P3 | BTstack | Conditional personal-use reference | High mismatch confidence | Useful comparison; importing a second stack adds work |

## BlueZ: use the decoder outside the phone

Verified public `master` ref: `14bd6ab65f4a647302edbd6df27f6faa91bee8a8`.
The inspected [btsnoop implementation](https://github.com/bluez/bluez/blob/14bd6ab65f4a647302edbd6df27f6faa91bee8a8/src/shared/btsnoop.c)
provides `btsnoop_open`, `btsnoop_create` and record handling; its file licence is
LGPL-2.1-or-later. The much larger [packet decoder](https://github.com/bluez/bluez/blob/14bd6ab65f4a647302edbd6df27f6faa91bee8a8/monitor/packet.c)
also declares LGPL-2.1-or-later. The [official btmon documentation](https://github.com/bluez/bluez/blob/14bd6ab65f4a647302edbd6df27f6faa91bee8a8/doc/btmon.rst)
documents offline btsnoop reading and command-latency analysis.

Use the existing executable in a Linux host environment against synthetic HCI
fixtures first. A small host-side exporter can feed timestamps, direction and
whole packets to that tool; no decoder belongs in the kernel bridge. This saves
maintaining command/event names and completion interpretation. BlueZ's Linux
`bluetoothd` uses different kernel sockets and userspace services from Apple's
daemon. Replacing the iOS daemon would additionally require Settings/profile/API
adaptation and would abandon the existing transport contract.

First proof: export a fabricated Reset/Command Complete exchange and a refused
command, then require correct direction, opcode, status and ordering from the
external decoder. Keep actual captures under ignored research. Before adding
any capture path, retain existing identifier/payload handling rules; no real
device trace or address is part of this report. No host-tool build was attempted.

## Zephyr: good H4 oracle, unsuitable whole-driver transplant

Verified `main`: `0534e997eacb94bae1df6c9a7dd4a9a6cbf1cecf`.
The [H4 driver](https://github.com/zephyrproject-rtos/zephyr/blob/0534e997eacb94bae1df6c9a7dd4a9a6cbf1cecf/drivers/bluetooth/hci/h4.c)
declares Apache-2.0. Inspected routines include `h4_read_hdr`, `get_acl_hdr`,
`get_iso_hdr`, `read_payload`, `h4_discard`, `h4_stop`, `h4_open` and `h4_close`.
It handles partial headers, explicit discard counts, receive-buffer shortage,
event allocation and transport cleanup. Its newer setup also resets transport
lockstep state around controller startup.

The seam is the hardware-neutral `bg_feed` framing interface and bridge-stop
tests. Keep our command gate unchanged. Reuse Apache-licensed logic selectively
or compare independently derived packet boundaries and stop-state invariants.
The complete driver depends on Zephyr `net_buf`, FIFO/semaphore/thread, UART
interrupt and device-tree APIs; porting all of those to XNU would save little.
It does not implement Skywalk or Apple's daemon startup prerequisites.

First proof: a host-only differential harness with fragmented event/ACL/ISO
headers, zero and maximum payloads, ISO flag bits, oversize discard followed by a
valid event, buffer exhaustion and stop during a partial frame. Host and chip
directions need separate allowed-type expectations: a host-side H4 driver alone
is not an oracle for command packets flowing the other way. Existing local
tests already cover split streams and oversize discard; add only uncovered
invariants. A successful harness would validate framing, not native Bluetooth.

## NimBLE: useful optional socket-backed fixture, not the iOS host

Verified `master`: `58cbe9a20edfd1930a4df5d1e6f2cf6cfe747dd1`.
The inspected [socket transport](https://github.com/apache/mynewt-nimble/blob/58cbe9a20edfd1930a4df5d1e6f2cf6cfe747dd1/nimble/transport/socket/src/ble_hci_socket.c)
has the Apache-2.0 file notice. Relevant routines are `ble_hci_sock_rx_msg`,
`ble_hci_sock_cmdevt_tx`, `ble_hci_sock_config` and `ble_hci_trans_reset`.
It includes TCP and Linux/NuttX socket routes and H4 command/event/ACL/ISO paths.

This can provide an independently maintained host fixture over a loopback
stream. Its NimBLE portability layer, event queues, mbufs and configuration
macros still need an adapter. Restrict any first proof to a fabricated stream;
the TCP route is not the phone's kernel-control/Skywalk protocol. NimBLE's BLE
host is not a complete classic Bluetooth/A2DP host and supplies no iOS 26
bluetoothd, CoreBluetooth or Settings adapter.

Old `nimble/transport/uart/src/ble_hci_uart.c` URLs returned 404 at this pin.
Use the inspected socket path above rather than estimating support from stale
embedded-project links. Building a second BLE host is lower priority than
diagnosing the existing Apple daemon before it opens the transport.

## Linux BCM/H4: protocol sequencing reference with board dependencies

Verified Linux `master`: `6628e7d4c6b25c8d18f1345e3a20d21829aae7e4`.
The inspected [Broadcom UART driver](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/bluetooth/hci_bcm.c)
declares GPL-2.0-or-later. `bcm_set_baudrate` and the setup path distinguish the
controller's accepted baud change from changing the host UART rate. The
[H4 driver](https://github.com/torvalds/linux/blob/6628e7d4c6b25c8d18f1345e3a20d21829aae7e4/drivers/bluetooth/hci_h4.c)
connects framing to Linux HCI/TTY queues and exports `h4_recv_buf` through a GPL
export. These are source references, not permissively licensed XNU additions.

Current blazer code already performs the successful firmware/rate sequence.
There is little value in redoing it. The useful comparison is persistent
service lifecycle: runtime power/wake, drain, reset and host/controller rate
ordering. Linux's `serdev`, skb, regulator, GPIO and runtime-PM framework are
not XNU APIs; matching Broadcom family names do not establish BCM4390B1 board
support or the correct Tensor pads and Wi-Fi-before-BT prerequisite.

First proof: audit our existing simulated UART ordering against the documented
controller/host boundary and add a regression only for a demonstrated omission.
Do not copy GPIO tables, change proven baud settings or add H5 negotiation.
H5 is a different framing/session protocol, not a reliability patch for the
already demonstrated H4 fallback. No new firmware is needed for this audit.

## BTstack and Apple source: important negative findings

Verified BTstack `master`: `9edb5d82ea6ec4466a393415d65030929330acdf`.
The inspected [H4 transport](https://github.com/bluekitchen/btstack/blob/9edb5d82ea6ec4466a393415d65030929330acdf/src/hci_transport_h4.c)
and [BCM chipset helper](https://github.com/bluekitchen/btstack/blob/9edb5d82ea6ec4466a393415d65030929330acdf/chipset/bcm/btstack_chipset_bcm.c)
have file notices restricting use/modification/redistribution to personal benefit
without commercial purpose or monetary gain. Treat this as conditional-use
source, not BSD/MIT. No copy is recommended here. A complete dual-mode host is
useful for independent embedded projects, but still does not supply Apple's
daemon ABI; its Broadcom support also does not verify this board's power route.

The [Apple OSS IOBluetoothFamily repository URL](https://github.com/apple-oss-distributions/IOBluetoothFamily)
returned 404. That observation does not prove every historical source is
unavailable; it means this audit found no verified modern Apple iOS 26 driver
implementation to import. Public macOS Bluetooth APIs, USB dongle injectors and
firmware patchers are not evidence of the required native UART/Skywalk adapter.

## Concrete next task

Extract a bounded diagnostic from the **existing** bt-3 console: the first
bluetoothd exit record, a fixed number of return frames, its exec/load metadata
and relevant kernel-control events. Symbolicate with the existing local binary
and verified load slide; report unknown frames rather than guessing. Include
the capture's loss count. Do not scan-print or copy the whole 1.3 GB trace.

Acceptance: a reproducible, small ignored receipt identifies the pre-transport
exit site, or explicitly records why the saved capture cannot resolve it. Then
choose a concrete daemon prerequisite fix. If that evidence is insufficient,
the phone/QEMU coordinator can decide whether a bounded new capture is justified.
Only after that should native bridge acceptance be scheduled. This task reuses
work already paid for and avoids adding another Bluetooth host stack to debug.

This audit performed public-source and local-file reads only. It did not build,
run a guest, access a device, operate a radio, download firmware or test native
Bluetooth. GitHub API quota exhaustion was handled with verified public refs
and exact pinned source pages; no access restriction was bypassed.
