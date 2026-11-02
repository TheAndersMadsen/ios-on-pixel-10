# Reuse audit: code already on disk

2026-11-02; host-only inspection. No implementation changes, test runs, builds,
device operations or new physical results in this audit. Test totals below are
the delivering owners' recorded receipts, not tests rerun by this auditor.

## Snapshot and strongest conclusion

The current release source is `research/ios26-release-r1/work/xnu` at
`237e3889640333558525c8082593e68cc5401405` (p29). Its series and provenance
already incorporate much of the material described as pending by older handoffs.
The best immediate saving is to compose and test this work, avoiding replacement
drivers and duplicate patch imports. A feature being linked does not establish
that its runtime gate was enabled or that its hardware acceptance passed.

Primary local evidence: `series/PROVENANCE.tsv`,
`research/ios26-fleet/resume-20261102/p29-{integration,dependencies}.json`,
current source, the two p29 UI image manifests, and the latest entries in
`NOTES.md`. Older top paragraphs of `handoffs/release.md`, `perfreuse.md` and
several feature handoffs conflict with these newer records.

The latest recorded GPU health attempt, `20261102-102719-native-metal-health-p29-r1`,
failed: KCCB consumption was observed, but FW connection was zero, a FWCCB
message remained pending, and no successful execution return was recorded.
Do not proceed on the earlier SEND-only success or retry an unchanged image.

## Already integrated: do not import again

| Existing deliverable | p29 series entry | What is actually left |
|---|---|---|
| perfreuse 0780–0783: iOS tuning, clutch, adaptive tasks, VM telemetry | 1086–1089 | Select controlled gates and measure; old “not linked” label is stale |
| UFS interval learner 0992 | 1139 | Read-only workload acceptance after its adaptive prerequisites |
| Governor verification 0771; required thermal health 0640c | 1140–1141 | Validate in the exact chosen runtime recipe |
| Battery hold/status 0697–0698 | 1142–1143 | Real gauge/UI lifecycle evidence |
| Audio bootstrap 0903 and native PCM ring 0904 | 1144–1145 | Actual sample delivery and blocked hardware dependencies |
| IOSurface import/cache ownership 1200–1202 | 1146–1148 | Native producer/consumer, UPL and completion composition |
| DPU 0840–0843, fence quarantine 0844, VRR 0845 | 1149–1151 | Admission/teardown lifetime gaps and physical acceptance |
| Touch rounding 1260 and scripted tracing 0663 | 1152–1153 | Measured real touch-to-display response |
| USB Chapter 9 0974 and network bounds 1301 | 1154–1155 | Actual ECM endpoint/Mac binding and bidirectional packets |
| Wi-Fi observed station adapter 1136 | 1156 | Existing GET-only interface cannot perform missing SET operations |
| Persistence stability/cache deny 1240 | 1159 | Real setting restore and unchanged-root checks |
| Charging policy 0699; display120 planner 1300 | 1160–1161 | Hardware adapters and explicitly permitted actions, not planner success |
| GPU SEND/start/health 0916b/0922/0924 | 1162–1164 | Diagnose the captured failed health result before progression |
| BT UART/H4/lifecycle 1133–1136 | 1165–1168 | Correct iOS stack attachment and real completion/lifecycle evidence |

Source spot-checks confirm `blazer_usbnet_bounds` and `hk_fb_fence` are present.
The current UI manifests do not enable most of the corresponding new gates.
Do not infer readiness from a count of patches, feature agents or host assertions.

## Concrete backlog 1: integrate the existing read-only RTC bounds

**Priority:** small, well-bounded correctness task; high confidence in reuse,
unknown performance benefit. This avoids another RTC implementation.

* File: `research/ios26-feature-rtc-r1/patches/0657-blazer-rtc-bounds.patch`.
* Independently rehashed SHA256:
  `98cd438027001cf09c2d08807b12d56053d9c10a08242646ca60e59c366dbbd4`.
* Candidate source has an MIT SPDX notice. It extends the existing native
  `hakios.blazer_rtc.c`, preserving its read-only CPM GET_RTC_TIME path.
* The p29 source lacks `blazer_rtc_bounds`; both current p29 UI manifests also
  omit the existing `blazer_rtc=1`. A linked old RTC path is not a tested clock.
* Owner receipts report 4,767 sanitizer checks, 5,478 civil-date comparisons,
  four detected regressions and a BLAZER-enabled ARM64 object with real symbols.

Integration seam: review/apply this one-file patch, preserve CPM single-owner
serialization, and add only the exact new image token after its policy review.
The first host proof is to rerun the existing `tools/validate.py` in that topic
and compare actual gate-on/gate-off object symbols, rather than author new tests.
Phone acceptance remains with the coordinator: actual advancing calendar,
bounded conversion and date-correct userspace startup. Accurate RTC may remove
date-driven daemon work, but that effect is a hypothesis for this phone.

## Concrete backlog 2: reuse the completed native AIR frontend

**Priority:** large avoided rewrite; high confidence in the bounded frontend,
low confidence in end-to-end native execution until missing layers exist.

* `research/ios26-metal-native-20261102/air/airfront/` is newly authored MIT code.
* Source package `patches/0001-airfront.patch` SHA256 at this snapshot:
  `81ca037a84903e1ff08b8a7ca5f384a3990f6ed212bd644300ef2824e192b4e9`.
* `metallib.py`, `frontend.py`, `semantics.py` and `isa_plan.py` provide bounded
  container parsing, scalar SSA semantics and an explicit f32 buffer plan.
* Owner receipts report 79,944 defined-input comparisons with compiled LLVM
  oracles and 17,592 separately rejected poison-domain cases.
* Its actual `single_add` plan loads offsets 0/4, adds, and stores at offset8;
  this is an offline semantic plan, not executable DXT or a Metal callback.

Reuse seam: consume the existing `hackios.air.f32-buffer-plan.v1` in the ISA
owner's `src/plan_alu.py`, then implement a reviewed native compiler bridge into
Metal's existing `HMN_PEER_VERSION=2` contract. The host proof must compose the
actual AIR output, allocator/emitter and streams validator, preserving opaque
FP mode and refusing unsupported instructions. Do not build a second parser.
Missing: complete DXT memory/termination/resource rules, a trustworthy full-stage
validator, actual native callback/packer, firmware acceptance and real engine
completion/cache handback. External AIR frontends are extension/oracle candidates,
not automatic replacements for this already-tested subset.

## Concrete backlog 3: wire the existing wake/palm policy, without guessing wake

**Priority:** useful bounded input correctness work; high confidence in the
host policy, unknown physical gesture/low-power compatibility.

* `research/ios26-feature-wake_palm-r1/patches/1270-blazer-wake-palm-policy.patch`.
* Independently rehashed SHA256:
  `00c5bb368ddb22726bb5e8741a1cd78f93983ea266667a81acbc157ec0ae842e`.
* New C/header files are MIT; `BLAZER_WAKE_PALM` defaults off.
* It has no caller or build registration, and is absent from p29 source.
* Its three APIs are `blazer_wake_palm_init`, `_display` and `_report`.
* Owner receipts cover actual parser replay of 32 reports, cancellation and
  quarantine, nine rejected behavior mutations, and gate-on/off ARM64 objects.

Integration seam: normalize a complete decoded frame before the existing path
loses classifications, call the policy on decode/transport failures and actual
display transitions, and consume cancellation/up masks using agreed iOS HID
semantics. Keep verified gesture ID zero until authoritative evidence exists.
The first proof reuses existing captured-frame replay and adds the real adapter
to that harness. This can save writing policy and fault tests from scratch;
it cannot supply missing gesture IDs, low-power acknowledgements or IRQ wake.

## Concrete backlog 4: reuse the cloudd A/B artifact and nil-path diagnosis

**Priority:** low integration cost diagnostic; benefit unresolved.

`research/ios26-feature-daemon_perf-r1/artifacts/p5-gltrack-cloudd-r1.ovl`
rehashes to `02437877f216eec98514d596176d7e7247a7df2e22111efc2a0a2bbf3b5fc333`.
It changes only the disabled-job list to restore cloudd; 42 other overlay records
remain identical. Current p29 live/profile manifests instead select the original
`61c38161…` hgltrack overlay, so this candidate is not silently already deployed.

Existing owner tests validate the actual release overlay parser and failed-lookup
audit. The same handoff already traced the startup throw through
`BSSystemContainerForCurrentProcessPathProvider` to a failed system-container
lookup; no evidence identifies a missing image filename as the throw's cause.
Use that chain and the active `boot_services` worker's actual readiness wrapper,
rather than inventing a broad nil-URL suppression or arbitrary startup delay.
The next proof is the existing controlled QEMU comparison after container
readiness is understood, with identical inputs and a changed overlay only.
No speedup, endpoint success or missing-icon fix is established by this artifact.

## Preserve current owners and unfinished boundaries

The active optimization sampler already has `hsampler.c`, `hs_hook.c`, a source
fingerprint, composition tooling and a differential harness. Its operation order
explicitly preserves signed SQRDMULH rounding; replacing it with a generic image
library is not equivalent. Let that owner finish its bounded hook and proof.

Native Metal UC/VM/surfaces workers already compose real descriptor/UPL APIs,
an encoded MMU walker and explicit cache ownership. The newer surface consumer
patch rehashes to `7a0ea441021cb28f37222b9920883d8fa9b3fe47d6feb15ab64e0be57973311a`.
Its original additions are MIT, but whole sparse snapshots and diff context retain
the existing mixed/unlicensed provenance. Do not publish them wholesale or
claim another SPDX marker relicenses the base.

The real backlog is joint lifecycle testing: blocked CPU aliases, publication,
authentic completion, cache handback, timeout and retained resources. A host
fake backend, KCCB consumer or successful descriptor allocation cannot prove it.

## Small automation task that prevents repeated manual audits

Add a host-only feature ledger generated from existing provenance, source gates,
image manifests and bound capture receipts. Each entry should record patch hash,
release commit, compile gate, runtime token, adapter presence, tested image hash,
attempt ID and acceptance state. Keep `integrated`, `enabled`, `host-tested` and
`physically-passed` separate. Reject a “passed” entry with no bound image/receipt.
Do not derive current agent status from historical rosters or stale prose.

Smallest acceptance: recover the already-integrated table above from p29,
recognize RTC0657 and wake1270 as absent, detect their missing runtime wiring,
and classify the captured GPU health failure despite the host runner's exit0.
This saves recurring reconciliation work without creating another boot runner
or claiming implementation progress from metadata alone.
