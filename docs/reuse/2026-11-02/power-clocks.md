# Power, clocks, thermal, battery and sleep reuse audit

Reviewed 2026-11-02. Research only: no build, phone command, new boot or power
measurement. The current physical baseline is five A725s governed between
533 and 1075 MHz for 15 minutes, with 125 clock checks within 2% and logged
33–35 C temperatures. Those observations come from `NOTES.md` and
`research/ios26-fleet/handoffs/gov.md`; the earlier host-only wording in that
handoff is superseded by its physical-result addendum. No higher clock,
charger programming, additional CPU, or deeper idle state is recommended here.

## Findings in priority order

| Priority | Reuse | What work it avoids | Classification / confidence |
|---|---|---|---|
| 1 | Vendor DVFS/OPP decoder as an offline oracle | Repeated manual translation of domain/level/frequency/units | Reference + generated validation; high |
| 2 | Vendor thermal helper tests and protocol layouts | Inventing another collection of malformed-message and shared-memory fixtures | GPL host-test reuse; high |
| 3 | MAX77779 conversion helpers + existing XNU battery publication | Reimplementing units, signed current and battery property notification | Mostly already present; high |
| 4 | ODPM energy conversion and sample-state rules | Guessing rail power from undocumented integer fields | Reference, substantial existing overlap; medium |
| 5 | CPU idle statistics and WFI example | Some residency-accounting design, little actual sleep bring-up | Reference only; low immediate return |

The largest saving is an authoritative host-side source of truth for existing
drivers. There is no verified drop-in Tensor G5 power-management driver for
XNU in the reviewed sources. Linux subsystem registration, Android policy,
device-tree parsing, and kernel workqueues are dependencies, not portable ABI.

## Source identity and availability

The matching local donor is
`research/ios26-webscout-r1/dl-gos-6.12/repo`, a sparse clone whose actual origin
is `https://gitlab.com/grapheneos/kernel_pixel_6.12.git`, pinned at
`5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`. The parent directory is **not** that
repository: running git there finds the hackios checkout instead.

Pinned GitLab **raw** files below were fetched successfully during this audit.
The corresponding GitLab HTML page returned 403 and the attempted GitHub
mirror URL could not be fetched; that does not invalidate the verified local
pin or public raw source. No current branch HEAD is asserted. The donor commit
message identifies an October 2026 release and is not proof that every source
file exactly matches the phone's captured 6.12.81 module build. Match module
build IDs and firmware protocol before implementing any new transport.

## 1. Generate DVFS invariants instead of transcribing tables

Primary sources at the pin above:

- [google_cpufreq.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/cpufreq/google_cpufreq.c): `google_init_cpufreq_table`, `google_cpufreq_find_freq`, `google_cpufreq_set_target`, `google_cpufreq_fast_switch`, `init_cpufreq_em_table`.
- [dvfs_helper.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/drivers/soc/google/dvfs-helper/dvfs_helper.c): `dvfs_helper_round_rate`, `dvfs_helper_lvl_to_freq_exact`, `dvfs_helper_freq_to_lvl_exact` and the bounded DVFS reply records.

Both files explicitly carry GPL-2.0-only. Reusing their source requires retaining
those terms; do not silently merge a copied Linux implementation into an
APSL/MIT-labelled file. An isolated GPL host oracle is a much smaller integration
than transplanting the driver.

The cpufreq code pairs the OPP frequency with its explicit OPP level. An array
index is not a universal hardware level; frequency is converted from Hz to kHz.
The DVFS helper separately respects supported entries and domain-specific level
tables. The Linux driver also blocks frequency changes until prerequisite votes
have been established. These are useful invariants; they do not authorize more
operating points or prove that the requested clock physically took effect.

Current counterpart: `osfmk/arm64/blazer_gov.c` in
`research/ios26-release-r1/work/xnu`, the existing captured clock-table work,
`research/ios26-gov-r1/receipts/literals.txt` and its 99-row validation. The
governor already handles per-domain votes, memory floors, thermal gates, touch
boost and idle waits. Replacing it with the Linux driver would discard tested
XNU integration and add dependencies on regmap, OPP, PM QoS and vote-manager APIs.

**Integration-sized task:** add a host-only oracle that consumes the saved DVFS
replies and matching public DTS OPP records, then emits a comparison receipt
against the governor's existing tables. Reject duplicate levels, unsupported
levels, unit overflow, frequency/level disagreement and accidental use of a
domain-1 row for domain 2. Include malformed/truncated responses and every
existing allowed rung. Keep all device-derived inputs under ignored research.
This extends existing validation rather than adding a second governor.

**Acceptance:** current cap16 and all current allowlists are unchanged, and a
deliberately swapped domain, Hz/kHz error or one-level shift fails. No phone
access is needed. Savings: repeated table investigation and transcription;
confidence high. It produces correctness evidence, not a speed improvement.

## 2. Borrow the thermal fixtures before adding telemetry

- [thermal_sm_helper.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/perf/thermal/utils/thermal_sm_helper.c), GPL-2.0: `thermal_sm_initialize_section`, `thermal_sm_get_tmu_cdev_state`, `get_data_from_sm_section`.
- [thermal_sm_helper_tests.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/perf/thermal/test/thermal_sm_helper_tests.c), GPL-2.0: `thermal_sm_init_failure_test`, `thermal_sm_get_tmu_cdev_state_test`, `thermal_sm_thermal_stats_test` and mocked memory/mailbox operations.

The donor tests already separate protocol version, section identity, address,
size, mapping failure and offline initialization. That structure saves work
when building offline fixtures for future thermal statistics. Adapt fixtures
and assertions in a GPL host harness; do not port KUnit or Linux I/O plumbing
into XNU merely to run them.

Current `bsd/dev/hakios.blazer_thermal.c` already has a stronger project-specific
health contract: one queue owner, reply matching, per-zone miss counts, required
zone masks and sequence age. Its comments record an actual phone reply that
does **not** echo the vendor C structure as originally expected. Retain that
physical interpretation. A copied vendor struct is not a substitute for it.

**Concrete task:** extend the existing thermal host suite with donor-style
version/section/truncation fixtures and sequence-staleness cases. For any future
shared-memory decoder, test `size > capacity - offset` after validating offset,
unaligned packed records, an unsupported version, and count-driven arrays.
The existing guard remains the active thermal path.

**Donor caveat:** the reviewed helper checks bounds using `offset + size`, which
needs overflow analysis. Its function named `thermal_sm_set_thermal_stats_thresholds`
calls the read helper. Do not transplant either behavior unquestioned. No
shared-memory mapping, new thermal firmware command or trip write is proposed.
Savings: reusable failure taxonomy and test structure; confidence high for
host validation, unverified for firmware availability on this phone.

## 3. Keep the battery transport; reuse conversion oracles

- [max77779_fg.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/bms/max77779_fg.c), GPL-2.0-or-later: `reg_to_twos_comp_int`, `reg_to_micro_amp`, `max77779_fg_read_rsense`, `max77779_fg_get_battery_status`.
- [maxfg_common.h](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/bms/maxfg_common.h), SPDX GPL-2.0: shared gauge unit helpers.
- [Apple IOPMPowerSource.cpp, xnu-12377.1.9](https://github.com/apple-oss-distributions/xnu/blob/xnu-12377.1.9/iokit/Kernel/IOPMPowerSource.cpp), APSL-2.0: `setPSProperty`, `updateStatus` and battery setters. This is a verified release tag, not a newly resolved commit SHA.

The donor current conversion uses signed samples, a configurable sense resistor
and integer scaling; its default sense value corresponds to 2 mOhm. Several
Linux property paths reverse current sign for their own API. The XNU adapter
must follow its own stated convention, not copy the sign from an arbitrary
Linux caller. A zero sense value must be rejected in a standalone oracle.

Local `iokit/Kernel/arm/blazer_gauge.c` already derives voltage/current/temp/SOC
from these definitions through an explicitly bounded read-only SPMI transport.
`SweetBattery.cpp` already uses IOPMPowerSource, calls `updateStatus`, retains
last-good data behind its hold gate, and distinguishes charger-state validity.
The current publication code also records a 5020 mAh design capacity; the old
sleep handoff's 4707 mAh energy model must not be treated as current fact.

**Concrete task:** compare all 65,536 signed raw-current values and representative
voltage/temperature/SOC boundary values against an isolated donor-helper oracle,
including final milliamp rounding and negative truncation. Reuse the existing
hold/publication harness for validity and recovery; do not build another fake
battery feed. No additional register or charger access is required.

Savings: a trusted independent unit/sign check. Immediate driver-code savings
are modest because the core implementation already exists. No new charger
policy, calibrated capacity, cable detection or accurate battery lifetime is
established by these source files.

## 4. ODPM: reuse state and units, not initialization writes

[google_odpm.c](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/raw/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/odpm/google_odpm.c)
is GPL-2.0-only. Useful symbols are `google_odpm_mba_resp_hdl`,
`google_read_shared_memory`, `energy_value_read` and
`energy_value_update_acc_power`. The paired local `google_odpm.h` defines
channel/sample layout and different buck/LDO conversion factors.

This donor includes version matching, configuration readiness, sample readiness,
bounded waits, per-channel rail types, coefficients and separate internal versus
external sample rates. Energy calculation needs that metadata; a raw counter
or one shared-memory value cannot independently establish board watts.

`research/ios26-power2-r1` patch0695 and current `blazer_power` work already
contain a restricted ODPM investigation. The handoff explicitly says the meter
may not be running without Linux's initialization. Recommending a fresh ODPM
driver would duplicate that work and conceal the same dependency.

**Next useful host task:** differential-test a decoder against donor arithmetic
using synthetic buck/LDO/disabled channels, zero rates, counter rollover,
coefficient overflow and mismatched versions. Label unknown configuration as
unmeasured. Do not import the probe's measurement, shunt, channel or sampling
configuration writes. Savings are moderate for telemetry decoding; physical
availability and power accuracy remain unknown.

## Lower-return leads and rejected shortcuts

- Local donor `soc/rdo/experimental/cpuidle/wfi_only.c` is GPL-2.0-only and explicitly a testing driver. It enters WFI only; XNU already has WFI. It supplies no deep Tensor suspend implementation.
- `soc/rdo/cpu-lpm-stats/google_cpu_lpm_stats.c` and its header are GPL-2.0-only residency/latency accounting references. They depend on Linux runtime-PM/notifiers and firmware timing data. The reviewed average path can still divide after a zero count, so copy neither it nor its assumptions blindly.
- Current `blazer_sleep.c` and patch0988 already slow polls and coordinate display/touch. Governor idle coalescing0991 is present in current release source; it is not a new finding. A source audit does not establish lower measured power or working wake.
- `powercap_weights_algo.c` is GPL-2.0-only, with useful allocation logic but a much larger Linux powercap/workqueue/DT dependency graph. Our power inputs remain partly estimated; a more elaborate budget algorithm would not make them measured. Defer.
- Android charger/use-case drivers perform substantial state changes and rely on PD, battery models, thermal rules and charging companions. They are useful dependency references, not a shortcut for enabling charging. Leave the existing bootloader configuration and approvals unchanged.
- Samsung older-Tensor ACPM/cpufreq drivers, Qualcomm PMIC drivers, and desktop ACPI battery drivers have different transports or OS contracts. None bypasses the already-working Tensor G5 transport and iOS publication seam.

No implementation, source import or physical result is claimed by this audit.
