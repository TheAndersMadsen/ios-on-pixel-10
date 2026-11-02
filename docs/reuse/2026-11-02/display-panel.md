# Display, panel and presentation reuse audit

Assessed 2026-11-02, read-only. No build, guest, phone command, panel write,
firmware download or boot was performed. Proposed tests below have not run.

The largest remaining display reuse opportunity is Google's MIT-licensed panel
support and its revision-aware command machinery. Baseline zero-copy, damage,
fixed-rate VRR and completion quarantine are already in our current release
source; recommending those implementations again would duplicate work.
Native GPU rendering remains separate from scanout and panel control.

| Candidate | Classification | Priority / confidence | Work avoided |
|---|---|---|---|
| Google panel brightness/idle state transitions | Adapt selected MIT source | High / high source fit; physical behavior unproved | Reconstructing panel behavior from individual commands |
| Google command-set and revision helpers | Adapt selected MIT source | High / high | Hand-maintained per-revision sequencing and transport flags |
| VeriSilicon frame-completion/disable path | GPL reference under current project policy | High / high hardware fit | Guessing completion versus timeout and shutdown ordering |
| Google TE2 interrupt accounting | MIT reference/adaptation after interrupt prerequisites | Medium / high source fit | Inventing enable/disable ownership and diagnostics |
| DC9400 revision-specific capabilities | GPL reference under current project policy | Medium / high revision fit | Rechecking alignment and plane limits from unrelated chips |

**Source and hardware identity.** The main vendor pin is GrapheneOS
`kernel_pixel_6.12@5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`.
Its local sparse checkout is
`research/ios26-webscout-r1/dl-gos-6.12/repo`; HEAD, origin and relevant file
headers were inspected. Public raw files at that pin were independently opened.
This is a strong source match, not proof of identity with the phone's firmware.
The correct display controller reference is DC9400 revision `0x32a`, as recorded
in the existing physical display handoff; older Tensor DPU and Qualcomm MDP
tables are unsuitable. Google's older 6.6 snapshot is not our default authority.

**1. Adapt the existing panel implementation instead of reconstructing it.**
[`panel-gs-bmea.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/panels/muzel/panel-gs-bmea.c)
is MIT and serves `google,gs-bzea`; the BMEA filename does not mean a sibling
panel. Its BZEA native mode is 1280×2856. Useful functions include
[`bmea_set_brightness`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/panels/muzel/panel-gs-bmea.c#L2273),
`bmea_acl_modes_manager`, `bmea_get_idle_mode`, `bmea_get_min_idle_vrefresh`,
`bmea_change_frequency` and `bmea_set_self_refresh`. These preserve distinctions
between operating modes, dimming, idle eligibility, TE behavior and committed
hardware state. Selected logic is directly adaptable; the Linux driver is not
drop-in XNU code. Its prerequisites include a matching panel revision, explicit
software/hardware state, serialized DCS transport and completion-aware workloop.

Local counterparts already exist in `tensor_dpu.c::tdpu_panel_rate`,
`tdpu_panel_dbv`, `tdpu_panel_acl_off`, `hk_bright_map.h` and
`SweetFramebuffer.cpp::vrrRun`. The brightness curve remains an inferred model,
not measured calibration. The source handoffs already identify MP revision;
do not regress to the older note that revision was assumed.

Concrete first task: extract the smallest panel policy/transcript adapter for
the already-supported normal mode and known revision. Record commanded and
confirmed state separately. Compare its fake-transport transcript with the
current implementation for unchanged state, pending frame, dark panel, dimming,
rapid activity and command failure. Start with existing brightness limits and
fixed rates; defer auto-LTPO/AOD expansion. This saves manual protocol work while
leaving our transport, caps and physical acceptance with their current owners.

**2. Reuse revision-aware command machinery as a small library seam.**
[`gs_dsi_dcs_helper.c::gs_dsi_send_cmdset`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/common/gs_panel/gs_dsi_dcs_helper.c#L28)
is MIT. It selects commands by revision, finds the last applicable entry,
restricts transferable message flags and observes per-command delays.
The current `tensor_dpu.c` uses short, fixed `dcs_cmd` arrays; its transport
functions already return errors. Adapt selection and scheduling, retaining
explicit error propagation rather than copying the upstream `void` interface.
Linux `mipi_dsi_device`, tracing and sleep APIs need a narrow host/XNU adapter.
`EXPORT_SYMBOL_GPL` does not replace the file's explicit MIT licence.

[`gs_panel_funcs_defaults.c::gs_panel_get_panel_rev_full`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/common/gs_panel/gs_panel_funcs_defaults.c#L98)
and `gs_panel_get_panel_rev_no_variant` are also MIT. They provide the revision
decode instead of another handwritten mapping. Unknown input falls back to
the upstream latest revision; our adapter should refuse unknown hardware for
new command programming until its applicability is established.

Smallest proof: a host-only fake sink, representative revision fixtures,
empty/no-match/all-match lists, invalid transport flags, command failure and
delay/order capture. Verify exactly which requests are suppressed. Keep the
selected Google notices and the
[`common/LICENSE`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/common/LICENSE)
with copied portions, and record their origins in `docs/LICENSING.md`.

**3. Use the matching completion and shutdown driver as a contract reference.**
[`verisilicon/vs_crtc.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/vsi-drm/verisilicon/vs_crtc.c)
is GPL-2.0. Inspect `vs_crtc_wait_for_flip_done`,
`vs_crtc_handle_flip_error`, `vs_crtc_enter_power_off` and
`vs_crtc_atomic_disable`. It separates frame/event completion, error reporting,
pipeline disable and power transitions. Error fences do not establish successful
presentation. Linux atomic-state objects, IRQs, recovery and power votes prevent
direct reuse; preserve it as reference under the existing project policy.
[`9x00/vs_dc.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/vsi-drm/verisilicon/9x00/vs_dc.c)
is likewise GPL-2.0 and supplies matching frame timeout and interrupt context.

Current source has completion quarantine, but `presentFlip` still returns a
boolean, while `AppleCLCD::stop` calls a void scanout stop and then releases held
surface references. The display-sync handoff explicitly leaves uncertain
admission and teardown incomplete. Reuse the existing patches and tests;
finish these two contracts rather than writing a second framebuffer stack.

Concrete first task: define refused-before-submit / submitted /
completion-uncertain results at flip admission, plus a drain outcome at stop.
An original fake-DPU test should verify reference ownership across pre-submit
refusal, accepted submit, late completion, fetch fault, timeout and stop.
No surface may be returned on an uncertain outcome. This is an integration-sized
prerequisite for enabling zero-copy; it is not a new physical finding or a
prediction of a large frame-rate gain.

**4. TE2 diagnostics are reusable, but are not a presentation fence.**
[`gs_panel_irq.c::gs_panel_enable_te2_irq`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/common/gs_panel/gs_panel_irq.c#L66)
is MIT and reference-counts interrupt enable/disable; its TE2 ISR records a pulse.
That is useful for ownership and measured refresh diagnostics, not evidence that
a surface fetch completed. Our scanout currently has TE polling/classification
and timer-driven presentation. Real interrupt integration still needs GPIO/GIC
routing, serialization and the recorded GIC erratum prerequisites.

Smallest proof: host tests for balanced/nested enable-disable ownership,
underflow, stale callbacks and removal while enabled. Only after the existing
IRQ prerequisites are met should the phone owner compare pulse timestamps with
the established polling route, separately from rate changes or flip enablement.

**5. Keep the correct capability table as a pinned reference.**
[`vs_dc_info_9400_0x32a.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/display/vsi-drm/verisilicon/9x00/info/vs_dc_info_9400_0x32a.c)
is GPL-2.0. It is the relevant plane/capability table; its address/pitch
alignment and scaler restrictions have already informed local work. Use it to
validate a small original layout-admission function against boundary cases.
Do not copy register arrays or scaler coefficients into an assumed permissive
source file. A different revision's similarly named table is insufficient.

**Already present / rejected shortcuts.** Local 0840–0845 work covers damage
epochs, baseline zero-copy policy, fixed-rate idle VRR and fault quarantine.
Inspection of the release checkout found that source already integrated,
contrary to older topic handoffs. Additional imports need a fresh diff.
Google's `panel_tests/gs-panel-common-test.c` is a mutable debugfs panel exerciser,
not a host unit-test suite; its name does not justify running it as a safe test.
Tegu's older display path targets different hardware and has no recorded licence.
Wholesale DRM import would add a large compatibility layer. Partial DSI/DSC
updates, HDR and automatic LTPO are not obtained by enabling our dirty-copy gate.

**Local source receipts.** Read-only release snapshot:
`research/ios26-release-r1/work/xnu@237e3889640333558525c8082593e68cc5401405`;
the three inspected files had no local modifications at inspection.
`SweetFramebuffer.cpp` SHA256 `ed38b53ca672260eeccf9bc96a50965e789a31af8e8c1732bb6f6a9ca7ebe14b`;
`sweet_scanout.cpp` SHA256 `7327a3fe194552e2f4f54fe49687940b5555f9bbc154a68ef894fa4d3bb5e31f`;
`tensor_dpu.c` SHA256 `d32a871ba106aacb039037fb3571312cf05723801677452ede41573d8898bdc3`.
These are host source receipts, not proof of what any new phone boot executed.

The smallest useful next change is the explicit flip-admission/stop contract,
followed by a MIT panel command/transcript adapter. Future XNU validation must
enable BLAZER and the tested gates, emit ARM64 objects and inspect the expected
symbols; host model success alone cannot establish panel or DMA behavior.
Any later physical test remains a separate coordinator-owned temporary RAM boot.
