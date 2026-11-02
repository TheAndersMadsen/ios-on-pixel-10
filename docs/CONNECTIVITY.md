# Native connectivity on Pixel 10 Pro

Goal: the self-contained Pixel runs iOS 26 with native Wi-Fi, Bluetooth and
cellular services. Host tests, model packets, registered interfaces and firmware
responses are intermediate evidence. The goal remains active and incomplete.
The existing phone owner controls USB, full release builds and all boot slots;
see [COORDINATION.md](COORDINATION.md) and the newest [NOTES.md](../NOTES.md).

## Current evidence and next dependencies

| Domain | Existing physical evidence | Next missing native behavior |
| --- | --- | --- |
| Wi-Fi | BCM4390 rev5, NCI/IPC9 firmware startup, DMA/ioctl path and passive scan | Complete iOS 26 scan-result/event contract, serialized station operations, Settings join, packet exchange and repeatable disconnect/rejoin |
| Bluetooth | BCM4390B1 firmware and H4 replies; passive reception at 4 Mbaud with RTS/CTS | Reliable daemon startup, actual daemon-to-chip attachment, persistent lifecycle, Settings and real pairing/profile traffic |
| Cellular | S5400 identity from saved stock evidence; XNU read of nine modem pads | Verified CP power/platform ownership, PCIe0/DMA/MSI/boot, RFS/GEMS, SIM and data service, then native CommCenter integration |

Wi-Fi's current Apple80211 adapter is GET-only; every SET is explicitly
unsupported. Scan selector 11 is identified in 23G90, but the complete result
layout, iterator/lifetime and event contract are not proved. Do not substitute
an older macOS/iOS layout or advertise native scan/join support.

Consume these existing deliveries once, through their release owner:

- Wi-Fi discovery/MAC failure cleanup:
  `research/ios26-opt-20261102/handoffs/opt-wifi_scan_integration.md`, patch
  `42f5d7193de9d5513f9484a5bade750581ab968e4ec02ce25be92b8579a9e27f`.
  It attaches the existing controller below the real wlan nub and includes
  a GET-only diagnostic. It does not deliver scans or events.
- Bluetooth Skywalk lifecycle:
  `research/ios26-opt-20261102/handoffs/opt-bluetooth_integration.md`, patch
  `f47768854b810e33770a2a07421c1ce17611ca524584020a64c2d365af8f3204`.
  Independent review is with the phone owner; concurrent in-flight ownership
  remains unproved. Integrated 1135/1136 must not be imported again.
- Cellular copied-RAM receive primitive: existing feature-cellular 0931.
  It has no live transport consumer or hardware rung and does not justify a
  modem boot. `PWR_ON=1` with `PHONE_ACTIVE=0` does not prove the CP is off.

## Bluetooth startup investigation

The old `bt-3` capture is retained, not rerun. Its exact kernel disassembly
proves a broken exit diagnostic: a misplaced `noreturn` annotation removes
the tracer's bounds and normal process exit continuation. See the original
[bounded replacement](../runtime/exit_trace/README.md).

The worker's existing bounded extraction was reused and independently checked
against the capture, exit receipt and binary hashes. The capture lost over a
billion bytes, so missing control-open/HCI messages cannot establish absence.

Seven saved return addresses admit one 16 KiB-aligned call-site candidate
slide, `0x248c000`, within the explicitly enumerated range. Its direct branches
and local binary analysis point to LE root-key/keychain initialization and
the force-restart path. **This is an inference, not a runtime slide or proven
failure cause.** The old trace has no main-header proof. Do not change security
state or turn errors into success on this basis.

Evidence, bounded disassembly, exact commands, source/binary hashes and local
analysis are in ignored `research/ios26-connectivity-r1/bt3-evidence/`.
Next: actual load-address evidence and bounded Security API return statuses,
then repair the specific observed prerequisite while retaining real keychain
and daemon semantics.

The original [Security status observer](../runtime/bt_keychain_trace/README.md)
now has host forwarding/concurrency/sanitizer checks, enabled/disabled ARM64e
objects and a signed iOS26 diagnostic dylib. A concrete existing-p29 guest can
collect the missing statuses without a new kernel link. Native loading,
interposition and the actual failure status still require its queued run.

## Reuse sources selected for this hardware

The [Wi-Fi](reuse/2026-11-02/wifi.md) and
[Bluetooth](reuse/2026-11-02/bluetooth.md) audits remain the starting inventory.
HakiOS's APSL station/discovery interface is a useful Darwin boundary; matching
BCM4390 DHD describes NCI/IPC9. Older bwfm/brcmfmac IPC7 drivers are not a direct
replacement for the demonstrated transport.

For cellular, 14 exact CPIF source files (193,074 bytes) were recovered from the
existing local GrapheneOS 6.12 repository at
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`. They cover SIT framing, legacy queues,
snapshot handling, Google PCIe glue, CP power and packet processors. These are
GPL references kept private; no vendor implementation was imported into XNU.
The immutable file URLs and per-file hashes are in
`research/ios26-connectivity-r1/resources/manifest.json`.

Google's [S5400 source](https://android.googlesource.com/kernel/google-modules/radio/samsung/s5400/+/a64b2a318d7dde50d66df89ed456c6e00c4ff34d/)
is present at the peeled Android 16 tag commit above; `main` is an empty
placeholder. Its `exynos_ipc.h` differs from the local donor only in the relative
include path. This independently corroborates the outer framing; neither
source is proved identical to this phone's shipped driver/firmware.

[pixel-mainline/exynos-modem](https://git.deusch.me/pixel-mainline/exynos-modem)
is a source for sibling-chip boot/RFS/GEMS/SIT research, requiring S5400-specific
adaptation. [ARIstoteles](https://github.com/seemoo-lab/aristoteles) is an MIT
ARI dissector, not a CommCenter-to-SIT adapter. Its README and licence were
retained at the existing `25cb9bb5` pin. Both endpoints were reachable during
this checkpoint. A full pin/licence/ABI check is required before code adoption.

## Completion evidence

Wi-Fi needs real Settings discovery and join, address acquisition, bidirectional
traffic/DNS/TLS, and repeatable disconnect/rejoin through the native service.
Bluetooth needs the actual daemon and chip, Settings state, pairing and an
owned peripheral/profile, including disconnect/reconnect without stale traffic.
Cellular needs real SIM/network/data state through native iOS services, followed
by the supported call/SMS/audio paths. A packet interface alone is insufficient.

Bind each result to an immutable image, enabled gates, attempt ID and complete
capture. Preserve Android, firmware, slots and backups; each destructive action
still requires the user's specific approval. No new device/radio operation,
full kernel link or native-connectivity acceptance occurred in this checkpoint.
