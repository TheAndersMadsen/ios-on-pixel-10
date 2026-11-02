# CPU completion

The CPU's 84% in `docs/status.json` is a feature estimate: three working entries
at 100 and two partial entries at 60, averaged over five. The excluded X4 is
listed separately. Host builds and probes do not change those scores.

Physical evidence already records five A725s, multicore coherency/self-tests,
and a 900-second iOS governor run at 533–1075 MHz. The remaining counted gaps
are sustained higher-clock operation and both A520s under XNU. Idle sleep's
existing score rests on code inspection of WFI; physical idle/wake instrumentation
and power evidence remain useful validation, not a measured power-saving claim.

## First A520 prerequisite: cpu0 firmware audit

Physical attempt `20261102-110932-cpu0-audit-p29-r1` completed and captured.
The audit read succeeded, but the prerequisite **failed**: cpu0 MIDR410fd801,
REVIDR3, CPUACTLR0x4000000000 has bit38 set and bit9 clear. The five A725s
passed their SMP tests and the run reached its intended deadline. A520
bring-up is stopped; no unchanged retry, CPU1/OFF/re-entry or register write.
The CPU score remains84.

This also affects prepared single-core recipes that use `cpus=1` without
`blazer_bootcpu`: they enter XNU on cpu0 A520. The p30 GPU diagnostic and old
GPT-readback image are held for explicit CPU/phone/feature-owner context
review. No automatic substitution of an A725 follows from this observation.
The existing phone-owner context review also found a GPU memory-layout change:
p30 image `d8925f4f…` uses RAM base `0x882000000`, while the earlier p29 GPU
health image used `0xa00000000`. Source/link/image checks pass, but CPU, Trusty
and full placement acceptance remain separate. That review owns reconciliation;
neither a core nor a RAM-window change is automatic. The GPT profile stays frozen
and held, including its own source, image, nonce, LU0 transport and `--mach`.
A distinct parent-built one-A725 derivative, `01eae6c8…`, now matches the existing
reviewed proposal: one running ADT reg0x200,492-byte line and the same window882.
CPU host artifact checks pass, including reconstruction of the pinned payload.
The CPU source/guard/IRQ design conditionally accepts that exact bounded
one-A725 experiment. Powered parked cpu0, the existing barriers and single-core
transport guards remain required. Native's existing reservation/placement
check and the phone owner's attended P1/300-second admission remain. Live
CPU/Trusty/IRQ/cache/full-map and firmware acceptance are unobserved; this is
not a slot. The original cpu0 image's hold is unchanged.
The exact GPT r5 proposal SHA256
`feb2b799e9a5afdfb083a118e5b2e8b217b4b437299d02ef922286114dc4fa35`
has CPU **build-only composition acceptance**: all77 source pins checked,
same readback K30db07c5/U0ce50d8b, a000/4GiB window,528-byte line and one
running logical0/reg0x200. It remains unbuilt at this checkpoint. Actual new
image/shim/nonces/LU0/transport/own-U binding and exact-context admission are
separate; no GPU acceptance transfers to GPT. The old21cba/profile34a stays held.
One current source/artifact/acceptance/shareability handoff is retained in
`research/ios26-cpu-complete-r1/acceptance/CPU-NEXT.md`; it keeps ordinary UI
health observations separate from the existing lowered-trip R1/R2 tests.
The completed sampler OFF/FAST comparison is confounded by FAST's initial
BaseBoard NSURL-nil abort and establishes no speed improvement. The active phone
test is the owner's distinct combined p32 UI profile, with CPU-health gates
off. The CPU-health candidate is held for checker repair and final admission;
isolated thermal R1/R2 and higher clocks retain their existing gates.

`shim/tgl_cpu_audit.c` supplies a read-only, default-off precursor. It checks
cpu0's identity, EL2, and disabled MMU/data/instruction caches, records REVIDR,
and reads CPUACTLR (`S3_0_C15_C1_0`). It then continues the existing fastcore
handoff. Audit completion means the read succeeded, including when the relevant
bits are clear. The host verifier separately refuses progression with missing
bits. An ENTER before the implementation-register read identifies a trap or
unfinished read without presenting it as a result.

Register and bit meanings are independently checked against Arm's BSD-licensed
[Trusted Firmware-A A520 source](https://gbmc.googlesource.com/trusted-firmware-a/+/62844b5a4a706dab67b68b9588dd44605597aa17/lib/cpus/aarch64/cortex_a520.S)
and [register definitions](https://gbmc.googlesource.com/trusted-firmware-a/+/62844b5a4a706dab67b68b9588dd44605597aa17/include/lib/cpus/aarch64/cortex_a520.h),
accessed 2026-11-02: bit9 is the CAS/CASP workaround for 3685825; bit38 is the
powerdown workaround for 2630792. This audit neither writes those bits nor
establishes that every applicable A520 erratum is handled. The cpu1 firmware
power-transition prerequisite, per-core checks, and mixed-core execution remain
separate work.

The successful EL2 read does not prove write permission. Arm's
[exact r0p1 A520 TRM](https://developer.arm.com/documentation/102517/0001),
102517_0001_04_en A.1.7, pages183–185, permits the EL2 read but can trap an EL2
write to EL3. A.1.23, pages226–228, defines ACTLR_EL3.ACTLREN bit0 with reset
value0 and makes ACTLR_EL3 inaccessible from EL2. Firmware may change that
reset value before the shim runs; its actual permission and reset persistence
remain unknown. The pinned PDF SHA256 is
`69b35057028bc4f04e1acf552ec2959a1705625a31f715272d94a9583db06981`;
source metadata and extracted-text receipts remain in ignored research.
The source review establishes no safe write path. No write probe or new A520
workaround is admitted, and this audit authorizes no register/firmware change.

There is a firmware query path to investigate before a register-write experiment:
TF-A's [Errata Management ABI handler](https://gbmc.googlesource.com/trusted-firmware-a/+/62844b5a4a706dab67b68b9588dd44605597aa17/services/std_svc/errata_abi/errata_abi_main.c)
and [interface definitions](https://gbmc.googlesource.com/trusted-firmware-a/+/62844b5a4a706dab67b68b9588dd44605597aa17/include/services/errata_abi_svc.h)
provide version, support and per-erratum queries. They report firmware policy;
they do not install a workaround or prove the observed bit9 clear is harmless.
Support on this phone remains unknown. The matching Google6.12 towerci
`SMC_CMD_PRIV_REG` path instead accesses interconnect MMIO; it is not evidence
for a CPUACTLR write service. Pinned reference files, licences and hashes are
retained in `research/ios26-cpu-complete-r3/resources/`, with no vendor code imported.

Two gates are required: compile `TGL_CPU_AUDIT=1` with `TGL_FASTCORE=1`, and
runtime exact `blazer_cpu0_audit=1`. Missing/0 leaves the audit off; malformed,
duplicate or unterminated tokens refuse the loader path. Only the dedicated
`tools/image_tool.py image … --cpu-audit` profile admits the token. It requires
the established `--bootcpu 0x200 --cpus 5` topology, phone-root route,
deadline300, armed thermal70 and SMP report/self-test. Other experiments,
touch/overlays and alternative topologies are refused. Its ADT still excludes
cpu0/cpu1. There is no CPU_OFF or A520 CPU_ON in this implementation.

Host commands:

```sh
python3 -I tools/test_cpu_audit.py
python3 -I tools/test_image_tool.py
python3 -I tools/test_decode_shim_stamps.py
```

The first suite compiles the actual audit + fastcore C with ASan/UBSan and
models registers/PSCI. It exercises strict parsing, ordering before CPU_ON,
identity/cache refusals, raw missing-bit reporting and the unchanged handoff.
Its capture tests reject a different nonce, missing/repeated/reordered records,
wrong identity, missing workaround bits and incomplete handoff. These are host
tests, not execution of the new register read on a phone.

After the phone coordinator has booted and captured a specific built image:

```sh
python3 -I tools/image_tool.py check research/images/CPU_AUDIT_IMAGE
python3 -I tools/cpu_audit.py ATTEMPT/ramdump/kernel.log research/images/CPU_AUDIT_IMAGE/manifest.json
```

The verifier requires one undropped v2 stamp trail bound to that image's nonce,
ordered identity/register records and subsequent fastcore/EL-drop/XNU handoff.
Its `ok` is **only the cpu0 audit prerequisite**; `a520_support_accepted` stays
false. Separately verify fresh five-core alive/SGI/timer/atomic/lock/TLB tests,
zero errors, captured deadline reset, temperatures and the existing run limits.
A missing bit, trap, refusal or unexpected reset stops this stage. Do not retry
unchanged or write workaround registers speculatively.

The ignored `research/ios26-cpu-complete-r1/` handoff contains the immutable
candidate name, command arrays, hashes, ARM64 objects/symbol/disassembly proof
and scheduling state. No dump, firmware, identifier or Apple artifact belongs
in git. The existing phone coordinator retains exclusive USB/boot ownership.

## Remaining acceptance toward 100%

The first thermal/governor common-configuration candidate is
`research/images/cpu-health-p30-r2/boot.img`, SHA256
`463ffa618a39174fc4252894f312e650f89aea9e81e081e04b03ac69cd57e776`.
It has **not booted**. `tools/image_tool.py image … --cpu-health` is a dedicated profile
for the exact reviewed p30 kernel and existing overlay. It supplies the existing
1,000-byte plan: five A725s at cap16, guard70, verification, bounded floor
releases, required mask262 and thermal-owner health. High clocks and the
lowered-trip probe remain off. The general phone-token allowlist is unchanged.

The profile checks the CPU count, boot core, RAM/ADT placement, overlay and
kernel identities and reconstructs the payload sidecar. A later independent
review found two admission gaps: `check` accepted a different signed boot image
beside that sidecar, and manifest nonces could contradict the compiled shim.
The original candidate's actual bytes still agree. The phone owner owns the
narrow checker repair and affected refusal tests; CPU makes no overlapping
image-tool edit. Boot admission stays held until that repair and final review.
The original shim has six named ARM64 executable-text entries and zero undefined
symbols; the existing p30 kernel text receipt is retained. Prior tests were82
image-tool methods,7 audit methods and7 real-data refusals; those totals did
not cover the two new findings. The existing DCS unused-variable warning remains.
No new kernel build or runtime acceptance is claimed.

Exact build/boot argv, matching unstripped hash, nonce, PASS/FAIL/STOP and
rollback are in the single current `acceptance/CPU-NEXT.md` handoff. The phone
owner repairs/rechecks it and decides admission after its current capture.
It stays outside the active combined p32 profile. This common baseline
changes fail-stop/release policy; it is not an extra passive flag for a UI A/B.
Current p30 is probe0 and cannot run the separate existing R1/R2 tests.

The verified same-build DP11 factory vendor files now supply the previously
missing stock skin policy reference. It uses eight board thermistors, history
and a model; the current XNU guard reads ten Tj zones and does not implement
skin or battery protection. Pinned Google6.12 NTC calibration/protocol sources
and Apache-2.0 AOSP merge/unit references are recorded with exact hashes in
`research/ios26-cpu-complete-r3/thermal-policy/README.md`. Live policy selection,
NTC readiness and model behavior remain unobserved. These resources remove a
source-information gap, not the physical higher-clock prerequisite or cap hold.

Before higher-clock testing, `tools/cpu_dvfs_check.py` extends the existing
99-row literal check with strict saved-table identity, explicit-level and unit
checks. It reuses the existing nonce/epoch/seal-aware clock-probe decoder at its
recorded hash; changed decoder code must be reviewed before reuse. It compares
the complete saved CPU tables to the selected governor source and the retained
decompiled FDT. It changes no governor source, runtime gate or operating point.

Firmware IDs34/35 (`cpu1g0`/`cpu1g1`) and MMIO vote domains1/2 are different
namespaces. Duplicate IDs/names/levels, missing entries, unsupported OPPs,
override-only OPPs, incorrect units and changed existing domain ceilings are
refused. List position never substitutes for an explicit ID/level. OPP table
availability is not permission to execute every entry; the receipt separately
marks rows above each existing domain ceiling. The tool does not certify every
queue-protocol detail or replace physical clock/thermal measurements.

Source references at vendor pin `5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c`:
[DVFS helper](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/drivers/soc/google/dvfs-helper/dvfs_helper.c)
and [cpufreq](https://gitlab.com/grapheneos/kernel_pixel_6.12/-/blob/5940a3171fc6f6aa48c24fcc97c98b80d3fdde7c/private/google-modules/soc/rdo/cpufreq/google_cpufreq.c),
both GPL-2.0-only. The checker is original host code using protocol facts. An
isolated comparison harness compiles unchanged GPL lookup functions in ignored
research storage with their notices; no vendor implementation is copied into
XNU or tracked sources. The vendor cpufreq table sorts by frequency and stores
the explicit OPP level separately. Its helper exposes integer wire MHz; exact
AMU clocks can differ by fractional MHz and require the existing tolerance.

```sh
python3 -I tools/test_cpu_dvfs_check.py
python3 -I tools/cpu_dvfs_check.py --capture CLOCK_ATTEMPT/ramdump/kernel.log \
  --ids research/ios26-dramclk-r1/run/boot/ufs-ids.json \
  --source research/ios26-release-r1/work/xnu/osfmk/arm64/blazer_gov.c \
  --dts research/ios26-dramclk-r1/work/laguna.dts
```

The ignored CPU handoff's `dvfs/` receipts bind actual input hashes and the
vendor comparison. `physical_acceptance` and `clock_cap_change_authorized`
remain false even when this source/table check passes.

1. Capture this audit and review all applicable A520 errata/firmware state.
   A cpu0 result does not cover cpu1. Resolve the parked-cpu0/GICR dependency
   before any CPU_OFF/re-entry route, or review the alternative boot-on-cpu0
   topology. Validate cpu1's startup and per-core workaround state before
   mixed-core LSE execution. No admission of X4 follows from either route.
2. Show both A520 MPIDRs 0x000/0x100 doing work under XNU alongside the five
   A725s: exact per-core identity, successful startup, SGI/timer/atomic/lock/TLB
   self-tests with zero stale/missed/timeouts/backwards clocks, required thermal
   sensor coverage and a sustained bounded run. A generated seven-node ADT or
   modeled PSCI result is insufficient.
3. Higher clocks first require the pending baseline-only thermal-health and
   real downvote/floor-release tests. Verify actual per-domain clock transitions
   and fail-stop behavior before lifting the current cap. Then measure bounded
   and sustained higher-clock iOS runs, including the intended domain1 top,
   within separately reviewed run limits. The existing subsecond shim 3052 MHz
   reading cannot satisfy that requirement; domain2 retains its measured ceiling.
4. Update feature statuses only after the corresponding physical captures pass.
   Keep the definition of the score unchanged.
