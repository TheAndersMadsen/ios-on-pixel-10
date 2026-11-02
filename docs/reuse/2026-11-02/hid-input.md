# Touch, keys and HID reuse audit

Assessment date: 2026-11-02. Research and static inspection only; no build,
test execution, device command or new physical result belongs to this audit.

The best saving is to extend the working TouchComm decoder with vendor metadata
and reuse the existing palm policy, then verify the HID cancellation boundary.
Replacing the whole touch driver would repeat work already completed here.

## Evidence and source pins

| Source | Verified revision | Use and licence |
|---|---|---|
| [Synaptics official tcm-v2](https://github.com/SYNA-TouchSW/tcm-v2/tree/294ffa2339415a1ce2dbf5959578535106e40dc9) | `294ffa2339415a1ce2dbf5959578535106e40dc9`, current public HEAD when checked | Protocol/parser reference; selected C/header files explicitly GPL-2.0-or-later |
| [Matched Pixel vendor tree](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/tree/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/touch) | `5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`, existing captured-kernel reference | Pixel custom report semantics; driver header says GPL-2.0, parser SPDX says GPL-2.0-only |
| [Apple IOHIDFamily](https://github.com/apple-oss-distributions/IOHIDFamily/tree/777ccd9698845aadf711e32d843c8c9b777431d9) | `777ccd9698845aadf711e32d843c8c9b777431d9`, IOHIDFamily-2238.100.59 | Event semantics and serialization oracle; inspected driver/service files carry APSL-2.0 notices |

GitHub API verified the Synaptics and Apple pins. Vendor raw-file retrieval at
the pinned GitLab URL returned HTTP 200; its HTML page returned 403 through the
web tool. Local vendor objects were inspected with `git show` at the pinned
revision. An unauthenticated GitHub tree API call later reached the shared rate
limit; no unavailable tree contents are claimed as inspected.

The local release inspected was `research/ios26-release-r1/work/xnu`, HEAD
`237e3889640333558525c8082593e68cc5401405`. Its sources already contain
`touch_round`, polling/idle pacing, SweetHID digitizer collections and queue-drop
logging. A prior handoff saying touch never reached iOS is historical: the
newer physical handoff confirms working home/Settings touch with heavy lag.

## 1. Keep the working parser; reuse the complete report model

**Priority high; confidence high for source overlap, unmeasured runtime benefit.**

Exact upstream seams:

- [`syna_tcm_parse_touch_report`](https://github.com/SYNA-TouchSW/tcm-v2/blob/294ffa2339415a1ce2dbf5959578535106e40dc9/sources/synaptics_tcm2/tcm/synaptics_touchcom_func_touch.c#L286)
  decodes configured fields into a complete report object.
- [`syna_tcm_preserve_touch_report_config`](https://github.com/SYNA-TouchSW/tcm-v2/blob/294ffa2339415a1ce2dbf5959578535106e40dc9/sources/synaptics_tcm2/tcm/synaptics_touchcom_func_touch.c#L872)
  records heading, loop and trailing bit lengths.
- [Report enums/data declarations](https://github.com/SYNA-TouchSW/tcm-v2/blob/294ffa2339415a1ce2dbf5959578535106e40dc9/sources/synaptics_tcm2/tcm/synaptics_touchcom_func_touch.h)
  describe timestamp, classification, pressure, widths and gesture fields.

Already present: local `bsd/dev/blazer_tcm.c:hakios_tcm_touch_report` walks
the chip's configuration, handles active-object loops, normalizes coordinates,
and releases missing contacts. Reimplementing framing or the basic parser is
unlikely to save work. The existing real-capture fixture already covers this
phone's configuration, including custom tags absent from an older tegu fixture.

Missing seam: the local parser preserves classification/position but discards
timestamp, gesture ID/data, pressure and width metadata. Its event callback
publishes contacts individually, losing the complete-frame boundary needed by
the existing `blazer_wake_palm_report` contract. Preserve that boundary before
converting contacts into ordinary DOWN/MOVE/UP events.

Smallest host-only task: decode the unchanged real-capture fixture into a new
internal frame result while retaining the old sink path. Compare every old
contact, coordinate and emitted event; independently check newly exposed fields.
Add zero-active, ten-contact, unknown-field and heading/trailing-field cases.
Retain unknown custom fields as skipped metadata unless their meaning is known.

Do not use either implementation as a strict malformed-packet oracle: Synaptics
`syna_tcm_get_touch_data` returns zero successfully for a field beyond the buffer;
the current local helper can return a partial value. A new complete-frame result
should explicitly distinguish valid complete data from truncated input.

Labour saved: field definitions, loop accounting and an existing fixture replace
guessing a second report grammar. A host differential harness can use the GPL
reference without introducing it wholesale into the XNU runtime.

## 2. Use the matched Pixel custom metadata, not generic gesture IDs

**Priority high for palm/wake correctness; confidence high for source facts.**

The matched vendor path is
[`synaptics/syna_gtd/syna_tcm2.c`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/touch/synaptics/syna_gtd/syna_tcm2.c).
Its `syna_dev_parse_custom_gesture_cb` decodes a seven-byte gesture record
(x/y plus major/minor/angle). `syna_dev_report_input_events` preserves sensing
timestamps and reports classified contacts; `syna_dev_free_input_events` releases
all slots. These are useful reference seams, not Linux adapters usable unchanged.

The critical version trap is in
[`syna_gtd/syna_tcm2.h`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/touch/synaptics/syna_gtd/syna_tcm2.h):
Pixel defines single tap `6` and long press `11`; the generic Synaptics enum has
double tap `1`, active single tap `6` and tap-and-hold `7`. A generic guide cannot
establish this phone's wake gesture or successful low-power configuration.

Local overlap: `research/ios26-feature-wake_palm-r1` already delivers a host-tested
ten-slot policy and quarantine-until-lift behavior. Handoff patch `1270` has no
runtime caller/build registration. It deliberately rejects every native wake
gesture until a verified nonzero ID is supplied. Integrate that policy rather
than writing a new palm classifier or coordinate-based double-tap detector.

Smallest task: map the complete report from task 1 to the existing `bwp_frame`,
with exact classification, sequence, host receipt time and invalid-frame status.
Keep native wake disabled. Replay finger→palm→finger→lift, display changes and
transport failure through the actual policy; normal accepted contacts must match
the previous sink. Resolve contact cancellation with task 4 before runtime use.

Deferred dependencies: confirmed controller mode/gesture capture, IRQ ownership,
display-transition serialization and parent integration. None is established by
a vendor enum. The generic driver's low-power code is a lifecycle reference;
it is not a justification to send new controller commands now.

## 3. Reuse vendor timing semantics for measurement first

**Priority medium-high; source confidence high, clock alignment unproved.**

`syna_dev_report_input_events` expands controller timestamp deltas by `1000`
before passing sensing time into
[`goog_input_set_sensing_timestamp`](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/touch/common/v2/goog_touch_interface.c#L1715).
That supplies a concrete vendor software timing contract in place of guessing
units from touch intervals. It is not a new physical clock measurement.

The same file's `goog_input_set_timestamp` separately aligns host/controller
time, limits correction and checks monotonicity; the clocks are not inherently
synchronized. This file declares the imprecise `SPDX-License-Identifier: GPL`;
do not silently upgrade that to a verified version. Treat it as a reference
until its exact grant is clarified. Reuse the measurement model first, before
considering any correction algorithm or importing Linux timing machinery.

Current `SweetHIDTouch::touch` stamps each callback with `mach_absolute_time()`;
the controller timestamp has already been discarded. Existing `hk_ui_trace`
measures scripted callback/injection time, and scripted canvas input bypasses
the physical parser. It therefore cannot measure physical touch-to-glass delay.

Smallest task: expose controller timestamp and host receive/publication time in
a bounded optional trace, with wrap/reset-aware deltas and explicit clock domains.
Use host fixtures for wrap, reset, duplicate and backward-time cases. A later
coordinated physical run must correlate input with presentation/glass separately.
Do not change touch polling or apply smoothing on the strength of this audit.

Labour saved: vendor timestamp handling supplies an existing measurement design,
so performance work can separate chip cadence, poll delay, queue delay and rendering.

## 4. Use Apple HID cancellation as a narrow semantic oracle

**Priority high for completing existing policy; confidence medium for iOS ABI.**

[`IOHIDEventDriver::handleDigitizerCollectionReport`](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDFamily/IOHIDEventDriver.cpp#L3647)
handles collection cancellation. The same source's
[`handleDigitizerTransducerReport`](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDFamily/IOHIDEventDriver.cpp#L3788)
sets cancellation and touch/range/position masks. These APSL-2.0 functions offer
an authoritative semantic reference instead of guessing event flags.

Local `SweetHIDTouch::touch` currently accepts a boolean down state, constructs
a hand collection with finger children and has no explicit cancellation input.
The local `kIOHIDDigitizerEventCancel` constant already exists. The existing
`tegu_hid_wire.h` converts inherited kernel event layout into iOS26 queue layout;
replacing the full IOHID family would risk that working ABI boundary.

Smallest task: define an internal cancel operation for an already active slot,
verify parent/child masks and identity through the actual `thw_convert` boundary,
and assert one cancellation with no synthetic re-DOWN before lift. Use known
ordinary tap/drag/multifinger events as unchanged serialization controls.
Apple's macOS OSS release is a reference, not proof that every iOS26 private
wire field or consumer behavior matches. Runtime acceptance still belongs to
backboardd on the phone, after parent review and the normal build checks.

## Other leads and rejected shortcuts

- Google `common/v2/gti_sim*` supplies touch replay/timing models, but depends on
  Linux input, kthreads and hrtimers. Existing scripted-UI and real-capture tests
  already cover much of its value; adapt selected fixture ideas only if missing.
- Linux Synaptics RMI/PS2 drivers and generic touchpad palm filters target other
  transports or devices. They do not supersede TouchComm classification here.
- Apple HIDDriverKit is a macOS user-driver interface, not an iOS kernel adapter
  that can be dropped into XNU12377. Avoid a DriverKit migration for this task.
- Key debounce/volume/power lifecycle patches `0656`/`0657` already exist locally.
  Review their integration and attended acceptance before searching for another
  GPIO polling implementation. Source pin reads alone do not prove iOS key use.
- Report batching may reduce duplicate allocations for multifinger frames, but
  no measured profile here establishes it as the cause of the user's heavy lag.
  The sampled renderer hot path remains a separate, higher-impact investigation.

No licence-free XNU TouchComm driver or proven Pixel-native low-power wake
implementation was found. The practical route is narrow vendor-reference reuse
plus the already implemented local policy and existing HID bridge.
