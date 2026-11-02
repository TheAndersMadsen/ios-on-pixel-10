# CPU and thermal completion

Scope: physical XNU CPU, DVFS, thermal, and idle validation on Pixel 10 Pro, with source and host checks used only as supporting evidence.

## Current result

- **Physical baseline:** five A725 cores run under XNU with multicore coherency/self-test evidence and a 900-second governor run at 533–1075 MHz.
- **Physical A520 prerequisite:** the cpu0 audit found the required ACTLR bit 9 clear. A520 bring-up remains stopped; no unchanged retry, speculative register write, or cpu1/OFF/re-entry experiment is authorized by that read.
- **Common health:** no terminal common-health result was found. A built/host-checked candidate and any nonterminal capture do not establish thermal, DVFS, or governor acceptance.
- **Held scope:** higher-clock operation and both A520s remain unaccepted. The existing subsecond high-clock reading is not sustained XNU evidence.
- **Source/host:** DVFS table checks and thermal-policy references improve validation, but do not authorize a cap change; WFI code inspection is not measured idle-power evidence.

## Remaining work

1. Obtain and review a terminal five-A725 common-health result with fresh per-core clocks, required thermal sensors, transaction verification, guard behavior, and an intended bounded end.
2. Validate real downvote, floor-release, and fail-stop behavior under the reviewed baseline before considering any higher operating point.
3. Investigate firmware errata policy and a safe A520 path without speculative writes; cpu0 evidence alone cannot accept cpu1 or mixed-core execution.
4. Only after those gates pass, test sustained higher clocks and both A520s in separately reviewed physical runs; add idle/wake instrumentation without claiming power savings from WFI alone.

## Acceptance before expanding scope

- Preserve the established five-A725 baseline: fresh SMP self-tests, actual per-core AMU clocks within reviewed tolerances, coherent health state, required sensors, zero unexpected resets, and a terminal verdict.
- Prove real clock/floor transitions and fail-stop behavior before lifting existing ceilings; source tables, accepted writes, or host models are insufficient.
- Accept A520s only after applicable errata, startup, coherency, and thermal review plus sustained work by both cores alongside the five A725s; this admits no X4 work.
- Keep source, host, and QEMU results distinct from physical acceptance, and update feature status only after the corresponding physical capture passes.

## Evidence and source

- [Current CPU acceptance handoff](../research/ios26-cpu-complete-r3/frozen-dad0979/CPU-NEXT.md) — established baseline, A520 stop, and exact common-health gates.
- [CPU evidence and receipts](../research/ios26-cpu-complete-r3/) — source/host checks, physical audit receipts, and artifact context.
- [Common-health physical records](../research/ios26-opt-20261102/cpu_health_physical/) — retained capture material; no terminal verdict was found.
- [Thermal-policy references](../research/ios26-cpu-complete-r3/thermal-policy/) — stock-policy source facts and their physical-validation limits.
- [A520/TF-A references](../research/ios26-cpu-complete-r3/resources/) — pinned register and errata evidence; no established safe write path.
- [DVFS host checker](../tools/cpu_dvfs_check.py) — strict source/table comparison, not physical clock or cap acceptance.
