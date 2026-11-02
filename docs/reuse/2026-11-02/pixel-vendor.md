# Pixel vendor source reuse and version control

Audit: 2026-11-02, public source and host inspection only. No implementation,
build, boot, firmware download, device access or runtime improvement is claimed.

The largest saving in this area is to stop rediscovering hardware definitions
from mixed source generations. We already hold the useful vendor source. Pin
its provenance once, expose its permitted reusable pieces, and reject mismatched
tables automatically before a driver owner spends a phone attempt on them.

## What the sources actually establish

| Source | Verified pin or reference | Interpretation |
|---|---|---|
| GrapheneOS vendor 6.12 | `5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c` | Best local source family for the captured `6.12.81-android16` modules; exact owner-build identity remains unproved |
| Historical GrapheneOS vendor 6.6 | `e214813c0aeb5bef8dbe45f53390ada8aabe8054` | Useful historical DTS, but known bad generated UFS offsets; do not select by directory familiarity |
| GrapheneOS vendor 6.18 | `e3ce63ffa735fa809a9c3aa7171cbe7e31fb76c0` | Existing local comparison snapshot; not established to match the owner's firmware |
| Linux mainline | `cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a` | Existing local Tensor G5 topology/USB source snapshot, not a complete working Pixel driver stack |

The [6.12 public commit record](https://gitlab.com/api/v4/projects/grapheneos%2Fkernel_pixel_6.12/repository/commits/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c)
identifies a DP11.261002.005 import dated 2026-10-24. Local
`research/ios26-webscout-r1/dl-gos-6.12/repo` and
`research/ios26-hwmap-r1/dl-gos-6.12` both have that exact HEAD.
Matching kernel family and board properties is useful evidence; it does not
identify every binary module or prove the source has the owner's exact changes.

Current [GrapheneOS build documentation](https://grapheneos.org/build#10th-generation-pixels)
uses `kernel_pixel_6.18`, branch `17-muzel`, and maps blazer to muzel.
That is a discovery source for later fixes, not permission to replace the local
6.12 reference. The generic `kernel_manifest-6.18` describes a common-kernel
build; it is not itself the Pixel vendor module manifest.

The official [Google Pixel kernel guide](https://source.android.com/docs/setup/build/building-pixel-kernels#gki-supported-pixel-kernel-branches)
still lists production devices only through Pixel 9a in the inspected table.
Its Pixel 6 development 6.12 branch is not a Tensor G5 branch.

## Candidate 1: reuse the existing 6.12 source package map

**Priority high; confidence high; mostly source and interface reference.**

The pinned [LGA BUILD.bazel](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/devices/google/lga/BUILD.bazel)
and [Muzel BUILD.bazel](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/devices/google/muzel/BUILD.bazel)
provide the package names that connect board builds to source. For example,
Muzel names `bluetooth/broadcom:nitrous`,
`touch/synaptics/syna_gtd:syna_touch`,
`wlan/bcmdhd/bcm4390:bcmdhd4390`, and
`display/panels/muzel:panel-gs-bmea`.
LGA names the RDO mailbox, pinctrl, SPI, SPMI, UFS, cpufreq, DSU and USB packages.

This avoids searching every old Tensor/Exynos tree for a similarly named driver.
However, a Kconfig/package reference is not proof that a module was enabled,
loaded, or bound to this board. Use the captured module inventory and matching
FDT compatible/resource properties as separate checks.

Local overlap: `ios26-webscout-r1`, `ios26-hwmap-r1`, `ios26-firmware-r1`
already contain overlapping sparse subsets. Existing release files
`bsd/dev/blazer_cpmq*.c`, `osfmk/arm64/blazer_gov.c` and
`osfmk/arm64/blazer_usbcon.c` already consume independently implemented hardware
knowledge. Replacing them with Linux drivers would add a large Linux API port.

Licences vary per file. RDO runtime driver files inspected here are GPL-only or
GPL-or-later; follow this repository's existing facts/reference policy for those.
The public directory named `private` is a repository layout, not an access grant
or a declaration that its code has no licence.

**First task:** generate a static package-to-module/source index from the two
pinned BUILD files and the existing source receipts, without executing Bazel,
following submodules, or fetching prebuilt binaries. Add source-family, pin,
SPDX, local-path and known-local-consumer fields. This saves repeated discovery
across virtually every hardware owner; it does not implement their iOS adapters.

## Candidate 2: permitted panel and binding fragments

**Priority high for driver owners; confidence high; selected direct reuse.**

The actual [panel-gs-bmea.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/panels/muzel/panel-gs-bmea.c)
is MIT, including `bmea_set_brightness`, `bmea_mode_set`, DSC configurations and
the `google,gs-bzea` match. This is the correct source family despite the file's
BMEA name. It depends on DRM/gs_panel helpers, timing, panel revision and board
state; copying the whole driver does not make it usable in XNU.

The [LPCM power-domain IDs](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/include/dt-bindings/lpcm/pf_state.h)
and sibling clock/reset binding headers offer BSD-2-Clause alongside GPL.
They can replace manually recopied enumerations when their notices are retained.
Do not extend that permission to adjacent mailbox protocol headers:
`include/mailbox/protocols/mba/apc/cpm/thermal/thermal_service.h` is GPL-only.

Public GitLab file-API bytes matched both existing local files exactly:

| File | SHA-256 |
|---|---|
| `panel-gs-bmea.c` | `85509623505c411cc457c60e3a1a7b0777306d6723dc3688f5bc7bdc7dadf9f0` |
| `lpcm/pf_state.h` | `70595602c3ef7d6be47bdfb2be24feb9421e5acaf5477605558c593dddc44252` |

Local panel/brightness work already references this source. The useful next
change is a small attributed helper or checked table import replacing an actual
duplicated fragment, followed by host conversion/state-transition checks.
Do not duplicate completed refresh/brightness work or raise physical limits.
Expected saving: avoid transcription and rederivation of documented tables;
board sequencing and iOS brightness integration remain separate tasks.

## Candidate 3: mainline topology and binding validation

**Priority medium; confidence high; direct data reuse plus reference checks.**

The pinned [lga.dtsi](https://github.com/torvalds/linux/blob/cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a/arch/arm64/boot/dts/google/lga.dtsi)
and [lga-blazer.dts](https://github.com/torvalds/linux/blob/cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a/arch/arm64/boot/dts/google/lga-blazer.dts)
are GPL-or-BSD-3-Clause. They describe the Cortex core identities, MPIDRs,
PSCI/topology and board compatibility, and already exist under
`research/upstream-20261101-pixel10pro/linux`.

The [google,lga-dwc3 binding](https://github.com/torvalds/linux/blob/cbbddb6b08cc9900a87cccaa9b22bbe06aa4f50a/Documentation/devicetree/bindings/usb/google,lga-dwc3.yaml)
is GPL-or-BSD-2-Clause and specifies required clocks, four reset names, power
domains and wrapper properties. The neighboring `dwc3-google.c` is GPL-only.
Do not infer the binding's permissive option applies to the implementation.

**First proof:** compare the public topology against the existing generated ADT
inputs and compare named resources against the retained board facts. Report
missing/mismatched properties without changing either device state or the ADT.
This can catch a wrong source-generation literal cheaply, but the small upstream
Blazer DTS supplies no complete display, GPU, Wi-Fi or power implementation.

## Candidate 4: use 6.18 as a targeted differential reference

**Priority medium; confidence high on mismatch, unproved runtime value.**

The [saved 6.18 commit](https://gitlab.com/api/v4/projects/grapheneos%2Fkernel_pixel_6.18/repository/commits/e3ce63ffa735fa809a9c3aa7171cbe7e31fb76c0)
is publicly verifiable and already exists at
`research/ios26-webscout-r1/dl-gos-6.18/repo`.
Its `perf/core/irm_devfreq/google_irm_devfreq.c` is not interchangeable with
6.12: the inspected 6.12 path accepts `google,irm-client-name` and calls
`init_apc_irm_client`; the inspected 6.18 path requires numeric `irm-client-idx`.
Existing handoffs associate the owner's FDT with the named-client path.

Use narrow, pinned file diffs to find bug fixes, then check each against the
owner's bindings and already implemented XNU path. A bulk transplant or a
latest-branch checkout would discard this compatibility evidence.
Runtime source remains subject to its own per-file GPL terms.

## Concrete source-integrity task with a reproduced failure

The generated UFS header is a useful first fixture for a source lock/checker.
Public GitLab API bytes from the [historical 6.6 header](https://gitlab.com/grapheneos/kernel_pixel_6.6/-/blob/e214813c0aeb5bef8dbe45f53390ada8aabe8054/private/google-modules/soc/rdo/drivers/ufs/lga/ufs-regs-gen.h)
and [existing 6.12 header](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/drivers/ufs/lga/ufs-regs-gen.h)
differ in **44 matching `_OFFSET` enumeration values**.
For example, `UCCS_OFFSET` is `0x10` versus `0xa`, and `HCFES_OFFSET`
is `0x16` versus `0x10`.

A host static check compared each parsed offset to the least significant set bit
of its corresponding nonzero `_MASK`: **6.6: 53 mismatches/138 pairs;
6.12: 0 mismatches/114 pairs**. This is source consistency evidence, not a
controller experiment or proof that every 6.12 definition is correct.

Implement a bounded, original `source-lock` verifier using the standard library:
verify pinned file hashes, SPDX classifications, actual local checkout presence,
and offset/mask invariants; report missing files instead of implicit Git fetches.
Use three fixtures: good 6.12 header, bad historical header, deliberately changed
pin/hash. Keep downloaded inputs ignored; tracked output contains only public
source metadata and the verifier's original code. Require the verifier to fail
on wrong-version or changed-byte input before adding further driver candidates.

## Limits and dead ends

- The top-level `upstream-20261101-pixel10pro` README/index centers 6.6; its
  `kernel_pixel_6.6` checkout contains selected DTS/build metadata, not every
  referenced driver. Inventory checked-out files before assuming source exists.
- Several index links moved into `research/laguna-usb-fix/docs/`; stale links
  explain apparent missing resources without justifying another giant clone.
- AOSP module repositories can have an empty `main` commit: the inspected
  [BCM4390 landing page](https://android.googlesource.com/kernel/google-modules/wlan/bcmdhd/bcm4390/)
  shows this explicitly. Resolve a real branch/tag and a file, not just the repo.
- No source package here supplies the proprietary iOS kernel-driver ABI,
  native Metal frontend, DXT compiler, or a proven complete Pixel XNU port.
- No prior rejected AoC/firmware-lifetime work was resumed. No firmware binaries,
  device identifiers, raw dumps or Apple artifacts were written into this report.
