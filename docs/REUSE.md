# Existing code worth reusing

Audit completed 2026-11-02 by **24 specialist agents**, followed by parent
source checks and reconciliation against the p29 release. The largest savings
are in selected vendor routines, format parsers, generated definitions and
independent test tools. Much of the older porting backlog is already integrated.

Start with the table below. Each linked report names exact files, symbols,
commits, licences, existing counterparts, missing dependencies and a first test.
[Next tasks](reuse/2026-11-02/next-tasks.json) are also machine-readable;
[fleet.json](reuse/2026-11-02/fleet.json) records the 24 completed assignments.
The [communication record](reuse/2026-11-02/communications.md) shows targeted
delivery to the active implementation coordinators and subagents.

## Highest-value opportunities

| Area | Reuse and work avoided | Concrete next step | Limit |
|---|---|---|---|
| [Native GPU](reuse/2026-11-02/powervr-kernel.md) | Pixel Volcanic DDK has MIT-selectable MMU, firmware-context, invalidation and cleanup code. Avoid reconstructing these interfaces. | Consolidate existing firmware/VM/queue layout probes into one versioned ABI profile; finish the named native callbacks from the matching donor. | Firmware health failed. No inspected project supplies a complete DXT compiler or native Metal stack. |
| [Display](reuse/2026-11-02/display-panel.md) | Google's matching panel driver and revision-aware command helpers are MIT. Avoid reconstructing brightness/idle command policy. | Adapt a small command/transcript helper to existing `tdpu_panel_*`; first complete flip admission and stop/drain ownership. | Keep current brightness/rate limits. Linux framework and display-completion code have separate licences/dependencies. |
| [Missing graphics](reuse/2026-11-02/assets-compositor.md) | MIT `ipsw` CAR inventory/resolver and BSD AssetCatalogTinkerer can replace manual catalog parsing. | Add metadata-only, full-rendition-key manifests to the existing settings-assets investigation. | Parser support and runtime rendition selection differ; missing logos are not yet diagnosed. |
| [Wi-Fi](reuse/2026-11-02/wifi.md) | Licensed HakiOS registry and station interfaces supply Darwin-side discovery, request conversion and scan reporting. | Add the observed-address/`wlan` ancestry delta, then a bounded mailbox and scan-snapshot converter around the working BCM4390 owner. | Existing Apple80211 is GET-only. iOS26 ABI, association, packets and teardown still need acceptance. |
| [Video](reuse/2026-11-02/media-radios.md) | The exact vendor tree contains Wave6 source. Its register header offers BSD reuse, removing a recorded missing-source/reverse-engineering step. | Generate a pinned command/register inventory and compare the existing wake/sleep planner. | Surrounding driver is GPL; buffers, firmware lifecycle, IRQ and VideoToolbox integration remain. |
| [UWB](reuse/2026-11-02/media-radios.md) | Exact Samsung U100 transport source exists; Apache AOSP UCI schemas/parser include 77 packet test blocks. Avoid inventing framing and enums. | Build a bounded host decoder and compare with the AOSP parser/golden vectors. | U100 transport is GPL reference under current policy. Live identity, calibration and nearbyd are unproved. |
| [AIR frontend](reuse/2026-11-02/metal-runtime.md) | `metal2vulkan-air` separates metallib/bitcode/typed AIR/metadata/canonicalization from Vulkan. | Evaluate as a host oracle/extension against our existing MIT scalar frontend and f32 plan. | GPL-2.0-or-later OR LGPL-3.0-or-later, Rust 1.98; adopting a runtime dependency needs an explicit licensing/packaging choice. No DXT output. |
| [Compressed textures](reuse/2026-11-02/tegu.md) | A compact file-level MIT ASTC decoder and Apache Arm astcenc can remove decoder authoring/debugging. | Use Arm's decompressor as an independent oracle before adding a bounded texture-upload adapter. | Conditional on actual ASTC demand. No evidence ties today's missing icons to ASTC. |
| [Development loop](reuse/2026-11-02/development-tooling.md) | Installed LLVM object tools and official `qemu.qmp` replace repeated object inspection and copied monitor clients. | Require implementation text symbols in per-file prechecks; preserve asynchronous QMP events in one existing harness. | These validate host tooling, not hardware functionality. Current ipsw still requires declared `.symbols` files. |

The [Pixel source audit](reuse/2026-11-02/pixel-vendor.md) is a prerequisite
across these areas. Use the existing 6.12 vendor pin
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c` as the current source-family
reference. It is not proved identical to the owner's firmware build. Historical
6.6 has inconsistent generated UFS offsets; current 6.18 is not an automatic
replacement. Nearby files can have different licences.

## Work already available locally

The [local backlog audit](reuse/2026-11-02/local-backlog.md) compares actual
release source and provenance with the older handoffs. It confirms that p29
already contains UFS adaptive waiting, battery hold/status, audio RT/PCM ring,
IOSurface imports, DPU damage/quarantine/VRR, USB network bounds, the GET-only
Wi-Fi adapter and Bluetooth lifecycle changes. Re-importing them saves no work.
Source inclusion, runtime enablement and physical acceptance are separate facts.

The best existing pieces to finish or compose are:

- The active guarded NEON sampler and its original-output differential harness.
  [libyuv](reuse/2026-11-02/cpu-rendering.md) offers a compatible single-axis row
  primitive, but its complete scaler and pixman bilinear produce different
  pixels. Compare a narrow backend only if actual call coverage justifies it.
- The original MIT scalar AIR frontend, current DXT emitter/allocator and
  stream builder. Compose them before commissioning another parser/compiler.
- RTC bounds patch `0657`, wake/palm policy `1270`, and the built MotionProbe.
  These have existing owner receipts; RTC integration, complete-frame wiring
  and app packaging respectively remain. Native wake stays disabled pending
  controller evidence.
- The existing cloudd-only overlay, diagnosed container-path call and current
  bounded readiness worker. Use one controlled comparison, with dependencies
  observed, before changing service policy.
- The completed `bt-3` guest capture. Extract and symbolicate its bounded
  bluetoothd exit record before repeating a costly run. Its substantial log
  loss must remain explicit.

## Recommended integration order

1. **Reduce repeated reconciliation.** Extend existing receipts into a feature
   ledger: release/source hash, adapter, compile gate, runtime token, selected
   image and bound result. Add a source-file lock and reject known bad UFS
   offset/mask pairs. Reuse the existing build/provenance tools.
2. **Keep the UI workers on their measured paths.** Finish the sampler's
   eligibility/correctness checks, feed the asset owner CAR manifests, and
   complete the existing container/overlay experiment. These target observed
   lag and missing graphics with small reversible candidates.
3. **Unblock native GPU integration.** Use the already-captured failed health
   result, establish one matching ABI profile, and fill the existing native
   context/invalidation/queue callbacks from the MIT-side vendor code. Keep
   dispatch unavailable until executable stages and genuine completion exist.
4. **Finish small OS-facing adapters.** Start Wi-Fi registry discovery, passive
   scan conversion and ECM conformance. Share the existing IONetworkStack.
   Trace actual configd registration calls before adding an unproven handler.
5. **Harvest the newly located peripheral source.** Prepare Wave6 and U100/UCI
   host inventories/decoders. These remove discovery work without competing
   with the current phone coordinator or requiring speculative device tests.

The [task list](reuse/2026-11-02/next-tasks.json) gives bounded acceptance for
these steps and the remaining useful host-tool pilots. No task requires a new
boot runner, another renderer, a whole Linux compatibility layer or a new
bootloader platform merely to begin.

## Shortcuts to avoid

- **Mesa PCO/PDSc is not a DXT compiler by target substitution.** Inspected
  launch fields and instruction formats differ. MIT Volcanic packet schemas
  remain useful as independent host packing checks; the native non-Mesa
  production route is unchanged.
- **Metal-on-Vulkan needs Vulkan; MoltenVK needs Metal.** Neither supplies the
  missing native DXT driver. Use frontend/API pieces at their actual boundaries.
- **Generic Broadcom drivers do not imply BCM4390 support.** Inspected bwfm
  and brcmfmac accept IPC through 7; this transport uses IPC9/NCI. Keep the
  existing working chip transport and finish its lifetime/OS adapter.
- **Qualcomm UEFI is not Tensor support.** AOSP image unpacking and MIT libavb
  can save offline parser work. HakiOS installation recipes and a menu alone
  do not establish safe dual boot or Android storage integrity.
- **Do not replace iOS daemons/frameworks with historical OSS stubs.** Public
  launchd/CF and Darling configd have different contracts. Use precise source
  references and the existing service planner/probes.
- **Repository badges are insufficient provenance.** Some unlicensed ports
  have individually licensed files; some Apple files are APSL1.1, not APSL2;
  current m1n1 changed licensing. Record the exact selected file and notice.

## Coverage and evidence

All 24 assignments completed. This was a broad targeted audit, not an exhaustive
review of every line or every internet repository. The reports distinguish
verified source, upstream claims, existing local results and untested proposals.
GitHub's shared unauthenticated API quota was exhausted during the search;
agents used pinned raw files, public refs, GitLab/Gitiles and existing snapshots.
Tegu's public URLs returned 404, so its audit uses the identified local snapshot.

The parent independently fetched **11 pinned source/manifest/licence files**
and checked the relevant declarations. Panel and GPU MMU bytes matched the local
donors. [sources.json](reuse/2026-11-02/sources.json) preserves public URLs,
hashes and these selected checks; ignored receipts/source copies remain under
`research/reuse-audit-20261102/parent-verification/`. This spot check is not a
complete licence or implementation audit.

This fleet performed research only. No runtime code was imported, kernel built,
device commanded, firmware sent/downloaded, radio joined or partition changed.
The latest physical health test failed; SEND and KCCB consumption do not prove
GPU execution. No FPS, boot-time or other runtime improvement is claimed.

| Topic | Report |
|---|---|
| Same-generation Pixel base | [Tegu](reuse/2026-11-02/tegu.md) |
| HakiOS, dada and community ports | [Ports](reuse/2026-11-02/hakios-ports.md) |
| Pixel source families and versions | [Vendor sources](reuse/2026-11-02/pixel-vendor.md) |
| PowerVR MMU, firmware and contexts | [GPU kernel](reuse/2026-11-02/powervr-kernel.md) |
| DXT ISA, AIR and packet generators | [Compiler/streams](reuse/2026-11-02/powervr-compiler.md) |
| Metal APIs and AIR frontend | [Metal runtime](reuse/2026-11-02/metal-runtime.md) |
| Software rendering | [CPU kernels](reuse/2026-11-02/cpu-rendering.md) |
| Icons, catalogs and compositor diagnostics | [Assets](reuse/2026-11-02/assets-compositor.md) |
| DMA, cache and memory ownership | [Memory](reuse/2026-11-02/dma-memory.md) |
| Panel, brightness and presentation | [Display](reuse/2026-11-02/display-panel.md) |
| Touch, keys, palm and wake | [Input](reuse/2026-11-02/hid-input.md) |
| BCM4390 and Apple80211 | [Wi-Fi](reuse/2026-11-02/wifi.md) |
| H4 transport and daemon integration | [Bluetooth](reuse/2026-11-02/bluetooth.md) |
| HAL, PCM and haptic lifecycle | [Audio/haptics](reuse/2026-11-02/audio-haptics.md) |
| Motion, pressure, compass and RTC | [Sensors](reuse/2026-11-02/sensors.md) |
| Governor, thermal, gauge and sleep | [Power](reuse/2026-11-02/power-clocks.md) |
| UFS, GPT, F2FS and compression | [Storage](reuse/2026-11-02/storage-filesystems.md) |
| Chooser and Android image metadata | [Dual boot](reuse/2026-11-02/dualboot-loaders.md) |
| DWC3, ECM, mux and USB host | [USB](reuse/2026-11-02/usb-networking.md) |
| Build, QMP, profiling and property tests | [Tooling](reuse/2026-11-02/development-tooling.md) |
| Services, configd and DNS | [Darwin](reuse/2026-11-02/darwin-services.md) |
| Video, cameras and remaining radios | [Media/radios](reuse/2026-11-02/media-radios.md) |
| Unintegrated versus already linked work | [Local backlog](reuse/2026-11-02/local-backlog.md) |
| ASTC, semantic matching and provenance tools | [Additional tools](reuse/2026-11-02/broad-discovery.md) |
