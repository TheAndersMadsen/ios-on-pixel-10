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

`shim/tgl_cpu_audit.c` supplies a read-only, default-off precursor. It checks
cpu0's identity, EL2, and disabled MMU/data/instruction caches, records REVIDR,
and reads CPUACTLR (`S3_0_C15_C1_0`). It then continues the existing fastcore
handoff. Audit completion means the read succeeded, including when the relevant
bits are clear. The host verifier separately refuses progression with missing
bits. An ENTER before the implementation-register read identifies a trap or
unfinished read without presenting it as a result.

Register and bit meanings are independently checked against Arm's BSD-licensed
[Trusted Firmware-A A520 source](https://github.com/TrustedFirmware-A/trusted-firmware-a/blob/master/lib/cpus/aarch64/cortex_a520.S)
and [register definitions](https://github.com/TrustedFirmware-A/trusted-firmware-a/blob/master/include/lib/cpus/aarch64/cortex_a520.h),
accessed 2026-11-02: bit9 is the CAS/CASP workaround for 3685825; bit38 is the
powerdown workaround for 2630792. This audit neither writes those bits nor
establishes that every applicable A520 erratum is handled. The cpu1 firmware
power-transition prerequisite, per-core checks, and mixed-core execution remain
separate work.

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
