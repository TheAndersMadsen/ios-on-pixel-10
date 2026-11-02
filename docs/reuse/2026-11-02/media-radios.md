**Media, cameras, cellular, GNSS, NFC and UWB reuse audit — 2026-11-02.**

The strongest new finding is that the exact local vendor repository already
contains the Codec3P/Wave6 and Samsung U100 source that earlier handoffs could
not locate. This removes a substantial source-discovery and protocol-recovery
step. Neither source establishes working video, cameras, cellular or UWB in iOS.

This audit read public source and saved local evidence only. No build, device
command, firmware download, radio operation or implementation change occurred.
The current GPU health failure recorded at the top of `NOTES.md` remains a
failure; it is unrelated to the source opportunities below.

| Candidate | Classification | Priority / confidence | Work it can remove |
|---|---|---|---|
| Exact Codec3P/Wave6 register header and driver | BSD header directly reusable; GPL driver reference | High for source recovery / high | Hand-disassembling named command registers and lifecycle |
| Exact Samsung U100 SPI/link source | GPL implementation/reference, platform port required | High for source recovery / high | Inventing UCI transfer framing and GPIO/IRQ ordering |
| AOSP UCI packet schemas, parser and tests | Apache-2.0 host-library reuse | Medium / high | Handwriting protocol enums, packet parsing and golden vectors |
| AOSP CHPP GNSS transport/client | Apache-2.0, conditional protocol match | Medium / medium | ARQ, fragmentation, service discovery and GNSS conversion |

**1. Recover Codec3P/Wave6 from the matching vendor tree before more disassembly.**

Verified repository: `https://gitlab.com/grapheneos/kernel_pixel_6.12.git`,
commit `5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`. Its local object database is
`research/ios26-webscout-r1/dl-gos-6.12/repo`; the files need not be checked out.
Public pinned raw URLs below were successfully fetched. The corresponding
`raw.githubusercontent.com/GrapheneOS/...` URLs return 404, which explains a
misleading discovery dead end without demonstrating that the source is absent.

The 788-line [wave6_regdefine.h](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/video/cnm/wave6_regdefine.h)
has a dual BSD-3-Clause / LGPL-2.1-only notice. Its BSD option permits source
reuse with retained notices. It names create-instance, bitstream, framebuffer,
decode, encode, result and timestamp registers, beyond wake/sleep alone.
This can replace manually recovered register naming and provide a checked
declarative command inventory. Offsets alone do not document every bit field,
required buffer layout or firmware-specific codec sequence.

The surrounding [vpu_ioctl.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/video/cnm/vpu_ioctl.c)
is GPL-2.0-only. `vpu_send_fw_cmd_locked`, `vpu_load_fw`, `vpu_reload_fw`,
DMA attachment/synchronization and `vpu_isr` provide concrete lifecycle contracts.
[vpu_pm.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/video/cnm/vpu_pm.c)
is also GPL-2.0-only: `vpu_sleep_wakeup` and busy/idle handling include surrounding
state save/restore missing from our limited control planner. Use these as
reference or an explicitly licensed port, not as BSD code because of the header.

Local overlap: `research/ios26-feature-video-r1/src/blazer_video_control.{c,h}`
already has host-tested bounded wake/sleep plans and observation. It has no
runtime submission hook. `handoffs/feature-video.md` still says the public CNM
URL returned 404 and frame-command ABI is unknown. The discovered source narrows
that unknown; it does not invalidate the handoff's hardware prerequisites.

**First task:** make a pinned, read-only symbol/register inventory from the BSD
header; compare existing `bv_plan_control` values and generate command-specific
host fixtures. Review full save/restore ordering from the GPL PM source before
extending the planner. Do not equate overlapping register addresses in different
command banks with a schema conflict. Acceptance: exact wake/sleep agreement,
unsupported-command refusal and explicit identification of undocumented fields.

Missing: lawful protected firmware initialization, exclusive power/clock/SMMU
ownership, IRQ binding, real frame-buffer management and an iOS VideoToolbox
integration. The existing stock evidence points to Wave6 Codec3P, so BigWave,
Samsung MFC and Wave5 are not drop-in drivers. Newer public Wave6 patches may
help later but are not needed to recover this exact available Google source.

**2. Use the actual Samsung U100 source; do not port Qorvo DW3000 by name alone.**

Same verified vendor pin, `private/google-modules/uwb/slsi/u100/`.
[uwb_link.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/uwb/slsi/u100/uwb_link.c)
and [uwb_spi.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/uwb/slsi/u100/uwb_spi.c)
carry GPL-2.0 notices. This is real configured-controller source rather than
an inferred generic UWB protocol. `get_uci_payload_len`, `handle_receive_only`,
`handle_full_duplex` and `link_check_uci` identify header/payload handling,
four-byte transfer alignment and simultaneous receive during transmit.
The SPI source defaults runtime UCI transfers to 5 MHz; the DT's 20 MHz is a
maximum, not evidence that the working driver chooses that rate. Receive clocks
use dummy transmit bytes, which matters when defining future adapter semantics.

The source also includes retries, GPIO transitions and automatic reset on
timeout. Those are separate lifecycle decisions, not requirements to copy into
an initial inventory test. Linux mutex/skbuff/SPI code is not XNU-ready.

Local overlap: `research/ios26-feature-uwb-r1` already validates the configured
U100 FDT identity. Its handoff explicitly asks to locate this exact transport
source. No current UCI decoder or physical ranging proof is supplied there.

**First task:** extend that owner's design with a bounded copied-RAM UCI transfer
decoder and independent fixtures for control/data lengths, alignment padding,
zero-length payload, truncated header/body and all-zero/all-ones idle patterns.
Do not perform SPI, GPIO, reset or firmware actions in this host milestone.
Use the GPL implementation as a wire-contract reference or retain its licence
if porting code. Acceptance is byte preservation and strict length/error behavior.

Missing: verified live controller/firmware revision, platform SPI/GPIO ownership,
bounded IRQ/lifetime handling, calibration and Apple's nearbyd/Nearby Interaction
ABI. DT presence proves configuration, not live identity or working ranging.

**3. Reuse AOSP's UCI schema and host parser instead of hand-maintaining enums.**

Verified AOSP `platform/external/uwb` main resolves to
`ac502199f0ae0960baed4e43363bdfcee7e49c9b` during this audit; its commit date is
2025-03-21. Main's age is recorded rather than described as newest Android17 code.
[uci_packets.pdl](https://android.googlesource.com/platform/external/uwb/+/ac502199f0ae0960baed4e43363bdfcee7e49c9b/src/rust/uwb_uci_packets/uci_packets.pdl)
contains 77 test blocks and distinguishes four-byte HAL packets from the larger
internal unfragmented representation. [lib.rs](https://android.googlesource.com/platform/external/uwb/+/ac502199f0ae0960baed4e43363bdfcee7e49c9b/src/rust/uwb_uci_packets/src/lib.rs)
provides `PacketDefrager`, `UciDefragPacket`, diagnostics parsing and tests.
File notices and the repository's `Android.bp` identify Apache-2.0 coverage;
retain the separate FiRa rights/certification notice too.

The crate has host support in `src/Android.bp`. Its Cargo build requires a
compatible `pdlc` or pre-generated Rust packet source plus Rust dependencies;
it is not a freestanding XNU kernel library. This makes it a good independent
host oracle for candidate native C framing, not a reason to add Rust/std to XNU.
Standard UCI coverage does not establish Samsung vendor command compatibility.

**First task:** pin a matching PDL generator, generate a host decoder and replay
the standard golden vectors against the bounded C decoder proposed above.
Test that HAL and internal headers cannot be confused, and cap fragment/cache
growth in our adapter rather than assuming upstream's allocation is bounded.
No RF/session commands need to be sent to gain this testing benefit.

**4. CHPP can save GNSS protocol work only after the actual wire format matches.**

Verified AOSP `platform/system/chre` main:
`77beed6007208e42009a789eab55df13f9069e0b`, commit dated 2025-03-08.
[chpp/transport.c](https://android.googlesource.com/platform/system/chre/+/77beed6007208e42009a789eab55df13f9069e0b/chpp/transport.c),
[clients/gnss.c](https://android.googlesource.com/platform/system/chre/+/77beed6007208e42009a789eab55df13f9069e0b/chpp/clients/gnss.c),
and [test/transport_test.cpp](https://android.googlesource.com/platform/system/chre/+/77beed6007208e42009a789eab55df13f9069e0b/chpp/test/transport_test.cpp)
have Apache-2.0 notices. CHPP supplies transport reliability and fragmentation,
service discovery and GNSS event conversion. `QUICKSTART.md` documents allocator,
notification, mutex, time and link adapters, including single-threaded operation.

Local `blazer_gnss_rx` already preserves 64-byte SPI transfers and partial-read
tails; do not replace it. Saved `gps.cfg` mentions CHPP/BETP, but neither that nor
CPIF's `gnss_boot` channel proves runtime batches contain bare CHPP. The KEPLER
runtime SPI stream is distinct from the modem's outer SIT framing.

**First task:** prepare a host-only CHPP recognition/decoder experiment behind
the existing opaque receive stage. Feed no synthetic location as hardware proof.
Adoption requires independently validated framing/version, then real captured
bytes obtained by the phone owner under a separate reviewed transport plan.
Do not revive blocked AoC firmware-lifetime work to obtain those bytes.

**Other domains: useful references and concrete negative results.**

- **Cellular:** exact vendor `private/google-modules/radio/samsung/s5400/` exists
  at the same pin. CPIF framing/queues are stronger references than Qualcomm
  MHI/MBIM or an unrelated MediaTek transport. Existing `blazer_modem_rx` already
  extracts bounded copied-RAM SIT outer frames. This is not a SIT service catalog,
  CP firmware startup, SIM integration or CommCenter/ARI implementation.
- **NFC:** exact `private/google-modules/nfc/st21nfc.c` was already recovered by
  the NFC owner; its GPL byte transport should not be rediscovered. Existing
  `bnfc_rx` handles NCI framing but has no runtime hook. Shared CLI10 transport,
  chip lifecycle, command credits, NDEF and Apple's Stockholm ABI remain. Generic
  PN53x/libnfc or Qorvo UWB drivers do not match these ST/Samsung controllers.
- **Cameras:** exact Google LWIS source is GPL-2.0-only, including
  `lwis_io_entry_process` and I3C proxy support at the same vendor pin. It explains
  generic I/O execution, not sensor streaming tables, ISP tuning/3A or Apple's
  capture-server ABI. Existing DT inventory is useful, but guessed public sensor
  models are not proof of correct register programming. A wholesale camera port
  is therefore lower return than the source recovery and host decoders above.
- **Software video:** iOS's own software codecs are already present in saved
  evidence. A bounded local playback/decode measurement is an integration test,
  not a reason to import FFmpeg as a substitute for native media support.

Recommended first delivery is the Codec3P register inventory plus U100 transport
contract/test-fixture package. Both use sources already available at a verified
pin and close explicitly recorded discovery gaps without touching the phone.
