# Existing code worth reusing

Ranked by expected remaining work avoided, hardware/source fit and relevance to
current blockers. Savings are qualitative, not time estimates or predictions of
physical success. The [research report](../reports/REUSE-STRATEGY.md)
explains the strategy; this file is the implementation shortlist.

Licences below apply only to the named files or components. Preserve notices and
review adjacent files independently. A source-family pin is not proof of the
installed firmware build or a private iOS ABI.

## Ranked shortlist

1. **Pixel Volcanic DDK firmware, MMU, contexts and queues.** Closest donor for
   BVNC 71.2.2448.1212; avoids rederiving firmware-layout and lifetime rules.
   - Sources/licence: pinned [BVNC table](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/hwdefs/volcanic/km/rgx_bvnc_table_km.h), [MMU4 init](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmmuinit.c), [firmware memory contexts](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxmem.c) and [invalidation/cleanup](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/powervr/pvrsrvkm/services/server/devices/rgxfwutils.c); reviewed Imagination files offer MIT or GPLv2 per file.
   - Boundary: adapt selected routines behind the versioned native ABI profile;
     replace Linux allocation, locking, DMA and fault handling. No complete DXT
     compiler or native Metal stack is supplied; strict firmware health precedes dispatch.
   - Local start: `research/ios26-metal-native-20261102/`, `docs/NATIVE-METAL.md`.

2. **Board-matched FDT/ADT manifest and ARM64 helpers.** Reuse hardware topology
   and small parsers instead of rediscovering every platform relationship.
   - Sources/licence: mainline [`lga.dtsi`](https://github.com/torvalds/linux/blob/cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a/arch/arm64/boot/dts/google/lga.dtsi) and [`lga-blazer.dts`](https://github.com/torvalds/linux/blob/cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a/arch/arm64/boot/dts/google/lga-blazer.dts) are GPL-2.0 OR BSD-3-Clause; [PongoOS](https://github.com/checkra1n/PongoOS) is MIT with third-party notices; m1n1 v1.9.9 is MIT and its [`adt.c`](https://github.com/AsahiLinux/m1n1/blob/v1.9.9/src/adt.c) separately permits BSD-2-Clause.
   - Boundary: emit a reviewed stock-FDT-to-ADT mapping, not an automatic semantic
     conversion. Apple AIC/DART/PMGR assumptions do not become Tensor GIC/SMMU support.
   - Local start: `research/ios26-webscout-r1/`, `research/upstream-20261101-pixel10pro/`.

3. **AOSP boot, DTBO, AVB and recovery tooling.** Reuse mature parsers and
   verifiers for offline recovery evidence rather than writing another toolset.
   - Sources/licence: [`mkbootimg`](https://android.googlesource.com/platform/system/tools/mkbootimg/), [`libufdt`](https://android.googlesource.com/platform/system/libufdt/) and [`external/avb`](https://android.googlesource.com/platform/external/avb/); `mkbootimg.py` is Apache-2.0, while AVB and neighboring files retain their per-file terms.
   - Boundary: build pinned host tools unmodified and test wrong-key, mixed-build,
     malformed-DTBO and truncation negatives. They do not establish live rollback
     state, encryption-key recovery, safe allocation or permission to flash.
   - Local start: `docs/DUALBOOT.md`, `research/ios26-dualboot-r4/factory-google-dp11/`, `research/ios26-dualboot-r6/`.

4. **Native LaunchServices registration and readback with icli.** Reuse a concrete
   in-process iOS plan/register/diff/readback contract for the app-registration seam.
   - Sources/licence: MIT icli at vphone's pinned revision, especially [`AppRegistration.m`](https://github.com/owngoal-dev/icli/blob/2fbdb5ee61d8c320732deb9768b22506f5e3d411/Sources/IcliPrivate/AppRegistration.m) and [`AppRegistration.swift`](https://github.com/owngoal-dev/icli/blob/2fbdb5ee61d8c320732deb9768b22506f5e3d411/Sources/IcliKit/Apps/AppRegistration.swift).
   - Boundary: use original QEMU fixtures and real app metadata; require LS record
     and URL-handler readback before separate exec/foreground tests. Do not copy
     bootstrap signing fields, the full entitlement profile or foreign-app bypasses.
   - Local start: `research/ios26-apps-r1/`, `docs/IOS-APPS-IDENTITY.md`.

5. **Apple open class families plus Laguna DWC3.** Reduce Apple-side ECM, block,
   SCSI and HID adaptation while retaining the existing native controller work.
   - Sources/licence: APSL-2.0 [CDC-ECM](https://github.com/apple-oss-distributions/AppleUSBCDCDriver/tree/main/AppleUSBCDCECM), [`IOStorageFamily`](https://github.com/apple-oss-distributions/IOStorageFamily), [`IOSCSIArchitectureModelFamily`](https://github.com/apple-oss-distributions/IOSCSIArchitectureModelFamily) and [`IOHIDFamily`](https://github.com/apple-oss-distributions/IOHIDFamily); mainline [`dwc3-google.c`](https://github.com/torvalds/linux/blob/cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a/drivers/usb/dwc3/dwc3-google.c) is GPL-only reference.
   - Boundary: reimplement Laguna clocks, resets, PHY firmware, DMA and role switching
     behind native contracts. Acceptance requires real IP traffic or HID events, not descriptors.
   - Local start: `docs/reuse/2026-11-02/usb-networking.md`, `docs/CONNECTIVITY.md`.

6. **BCM4390 Wi-Fi and Nitrous Bluetooth contracts.** Reuse board-matched protocol
   behavior and small Darwin-facing adapters around the existing transports.
   - Sources/licence: Broadcom [`dhd_msgbuf.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/wlan/bcmdhd/bcm4390/dhd_msgbuf.c) is GPLv2 with Broadcom notices; [`nitrous.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/bluetooth/broadcom/nitrous.c) is GPL-2.0; [HakiOS WLAN](https://github.com/oosexgang/hakios-xnu-kernel/blob/96ffbc532e970f3540885755d457e401e04d4707/drivers/wifi/hakios.wlan.cpp) uses its APSL-2.0 drivers licence.
   - Boundary: translate ring, association, registry and scan semantics into the
     single existing owners; do not substitute generic Broadcom stacks. Association,
     packets, daemon-to-HCI attachment and pairing remain separate physical gates.
   - Local start: `research/ios26-connectivity-r1/`, `docs/reuse/2026-11-02/wifi.md`.

7. **Blazer panel tables and Synaptics touch protocols.** Reuse exact panel data
   and report/recovery behavior where display and touch already have a native base.
   - Sources/licence: [`panel-gs-bmea.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/panels/muzel/panel-gs-bmea.c) is MIT; [`syna_tcm2.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/touch/synaptics/syna_gtd/syna_tcm2.c) is GPL-2.0 reference.
   - Boundary: adapt only matching revision-aware commands and touch reports behind
     current DPU/DSI and Apple-event owners. Neither donor fixes compositor stability.
   - Local start: `docs/reuse/2026-11-02/display-panel.md`, `research/ios26-opt-20261102/`.

8. **Typed AIR frontend from `metal2vulkan-air`.** Reuse metallib/bitcode parsing,
   typed IR, metadata and canonicalization without adopting a Vulkan backend.
   - Sources/licence: pinned [public crate API](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/crates/metal2vulkan-air/src/lib.rs) and [licence](https://github.com/steelbrain/metal2vulkan/blob/219f01365dc4c8eb346816c405b5b17403793764/LICENSE): GPL-2.0-or-later OR LGPL-3.0-or-later.
   - Boundary: evaluate first as a host oracle or explicit dependency against the
     existing MIT scalar frontend; make the licensing/packaging choice before promotion.
     It emits no DXT code and supplies no firmware or Metal execution.
   - Local start: `research/ios26-metal-native-20261102/air/airfront/`, `docs/reuse/2026-11-02/metal-runtime.md`.
