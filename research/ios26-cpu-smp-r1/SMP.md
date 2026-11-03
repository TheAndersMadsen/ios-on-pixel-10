# Why XNU runs five of eight cores, and the next read-only step (2026-11-03)

Owner: CPU/SMP lane. Evidence classes are marked: SOURCE, HOST, PHYSICAL (earlier attempts only). This lane booted nothing.

## 1. Finding: `SWEET CPU: 5/5` is the built topology, not a failed startup

- **SOURCE, DT** (`research/ios26-dualboot-r8/truth/fdt.dts`, `cpus` node): one `cluster0` with eight cores, all `enable-method = "psci"`.
  A520 "hayes" `reg` 0x0 and 0x100 (capacity 0x102), A725 "hunter" 0x200-0x600 (0x37b/0x37c), X4 "hunterELP" 0x700.
  Every core uses the same PSCI CPU_ON. No second cluster, spin table or other enable method exists that XNU could be missing.
- **SOURCE, XNU** (`xnu/iokit/Kernel/arm/SweetCPU.cpp`): `startAll` starts every ADT cpu node and prints
  `N/N CPUs initialized` with N = `topology->num_cpus`, the ADT's node count. `SWEET_SMP_MAX_CPUS` is 8 and the MPIDR check
  admits 0x0..0x700. The kernel has no 5-core limit. The image tool writes five A725 nodes (0x200..0x600), so 5/5 is everything
  that was asked for.
- **SOURCE, image/shim**: `tools/image_tool.py` `CPU_ORDER_MAX_CORE = 6` refuses the X4. The `--cpu-audit`/`--cpu-health`
  profiles require `--cpus 5 --bootcpu 0x200`. `shim/tgl_fastcore.c` admits only A725 targets.

Each excluded core is excluded for its own reason. None of them is a PSCI address or DT bug:

| Core | MPIDR | Why it is out today | Evidence |
| --- | --- | --- | --- |
| A520 cpu0 | 0x0 | It runs the shim. Under `blazer_bootcpu=0x200` it hands XNU to 0x200 and stays **parked in the shim, ON**. A PSCI CPU_ON on it would return ALREADY_ON (-4). Adding it needs a shim release path (park loop to XNU entry) or CPU_OFF and re-entry. Neither is authorized (docs/CPU.md). | SOURCE: tgl_fastcore.c, SweetCPU.cpp comment "cpu0 parked in the shim" |
| A520 cpu1 | 0x100 | Erratum **3685825** (CAS; workaround CPUACTLR_EL1[9]). The p29 audit read cpu0 at EL2: **bit 9 clear**, bit 38 set. The firmware does not apply the workaround. Writing it from EL2 may trap (ACTLREN, TRM A.1.7/A.1.23). Also 4615642. | PHYSICAL: attempt 20261102-110932-cpu0-audit-p29-r1, CPU-NEXT.md |
| X4 | 0x700 | Errata 3076789 and 2957258 (bootplan fixture); 4118414 (tgl_fastcore.c). It also has about 4x the modelled power of an A725. | SOURCE only |

XNU uses LSE atomics (CAS) everywhere. Running an A520 with an unmitigated CAS erratum risks silent lock and refcount corruption,
which is worse than a panic. That is why "start cpu1 and see" is not a test that can pass. A clean 900 s boot would not show the
erratum absent (CPU-NEXT.md: "Historical one-core boots do not prove an open silicon erratum absent").

**8/8 is therefore not reachable by an XNU code fix.** Each missing core needs a firmware fact or an owner decision first (section 4).

## 2. What this lane built: the firmware's own errata answer, read only

`blazer_cpu0_audit=2` (shim `TGL_CPU_AUDIT=1`): the existing cpu0 audit plus the Arm Errata Management ABI (SMCCC standard service).
These are queries, not setters (TF-A pin 62844b5a, `include/services/errata_abi_svc.h`, `services/std_svc/errata_abi/errata_abi_main.c`):

1. `EM_VERSION` 0x840000F0. Unless it reports 1.x, stop here: one call, and an unknown SMC returns -1 by SMCCC.
2. `EM_FEATURES(0x840000F2)` 0x840000F1. Unless it returns 0, stop.
3. `EM_CPU_ERRATUM_FEATURES(id, forward 0)` 0x840000F2 for the calling PE (cpu0, A520 r0p1), in this order: 3685825, 4615642,
   3631357, 2938996, 2900952, 2858100, 2630792. These are every pinned TF-A A520 erratum that applies to r0p1, plus 4615642, which
   is absent from the pin, so UNKNOWN(-3) is expected for it there.
   Answers: 3 higher-EL mitigation, 2 not affected, 1 affected, -1 not supported, -2 invalid, -3 unknown.

Each call is preceded by an ENTER stamp, so a hang names the call. Everything runs before the A725 CPU_ON. The handoff, the five-A725
topology, clocks and the ADT are unchanged. There is no MSR, no CPU_OFF and no A520 CPU_ON.

| Item | Evidence |
| --- | --- |
| `shim/tgl_cpu_audit.c/.h`: mode 2, `audit_errata_abi`, stamps 0x00ed/0x00ee/0x00ef | HOST: `tools/test_cpu_audit.c` (actual C, ASan/UBSan) covers mode 1 making 0 EM calls; mode 2 order, all before CPU_ON; EM absent (-1) / 2.0 / 0.1 → 1 call; features -1 → 0 erratum calls; refused identity → 0 calls; negative answers kept as s32 |
| ARM64 object, gcc and clang, `-DTGL_FASTCORE=1 -DTGL_CPU_AUDIT=1` | HOST: T `tgl_cpu_audit_configure`/`_prepare`, R `tgl_cpu_audit_errata`; 0 `msr`; 6 `mrs` (MPIDR, MIDR, CurrentEL, SCTLR_EL2, REVIDR, S3_0_C15_C1_0); smc only for EM. `TGL_CPU_AUDIT=0`: empty object |
| `tools/cpu_audit.py`: mode 1 or 2 manifest; `errata_abi` decode; mode mismatch refused; a hang (ENTER only) is incomplete | HOST: `tools/test_cpu_audit.py` 8 tests OK, including the actual C's mode-2 trace |
| `tools/decode-shim-stamps.py`: names + notes `EM 1.0`, `erratum 3685825: affected` | HOST: 17 tests OK |
| `docs/probes.yaml` a520-cores / x4-core rows | HOST: `tools/test_probe_eval.py` 19 OK; synthetic 8-core log → both works; mode-2 stamps → A520 active; p29 audit → not exercised |
| Wrapper `tools/image_tool_em.py`: shared tool's source + exactly two literal swaps (`=1`→`=2`, manifest mode 1→2), refuses if either does not match once | HOST |
| Image `research/images/a7-cpu0-em-r1` (not in git), boot.img sha256 `22da13ca3a120dc0d9fa95de4749d834c17775b7600758069c8b303f25ceb0bc` | HOST: `tools/image_tool.py check` OK bootable; cmdline 565 B ends `blazer_bootcpu=0x200 blazer_cpu0_audit=2`; manifest cpu_audit mode 2; shim.elf `audit_errata_abi` holds 9 smc (2 + 7, unrolled), handoff's 3 PSCI unchanged. **Not booted.** |

Build: kernel.int1 `0d0c99b2…`, base `tools/image_tool.py` sha256 `81552455…` (the m1box working copy), `TGL_TOOLCHAIN=llvm`:

```
TGL_TOOLCHAIN=llvm python3 -I research/ios26-cpu-smp-r1/tools/image_tool_em.py image a7-cpu0-em-r1 \
  --kernel research/ios26-phaseb-r1/int/build/kernel.int1 --kernel-sha 0d0c99b2cd7b1c71509c9cf52af34ca29c1856001fd077df41b6386bf243e9bf \
  --phone-root --phone-route ufsroot --qemu-run overlay-1 --canvas 1125x2511 --window-base 0x882000000 \
  --bootcpu 0x200 --cpus 5 --phone-deadline 300 --cpu-audit \
  --phone-args "blazer_thermal=2 blazer_thermal_panic_c=70 blazer_smp_report=1 blazer_smp_test=1 blazer_usbcon=1 blazer_usbcon_ch9=1"
```

QEMU: not used. The change is shim-only, and the shim does not run in the QEMU rig. XNU is unchanged.

## 3. Phone test (coordinator runs it; owner admission: this is a new firmware call)

Unattended, 300 s, five A725s, no UI. The question it answers: does the firmware itself say the A520 errata are mitigated?

```
hk queue add research/images/a7-cpu0-em-r1 --mode cycle --note "cpu0 Errata ABI query (read only), research/ios26-cpu-smp-r1/SMP.md"
# or: tools/live_boot.sh research/images/a7-cpu0-em-r1 a7-cpu0-em-r1 --mach research/ios26-phaseb-r1/int/build/kernel.int1.unstripped --wait 600
python3 -I tools/cpu_audit.py <attempt>/ramdump/kernel.log research/images/a7-cpu0-em-r1/manifest.json
python3 -I tools/probe_eval.py --row a520-cores <attempt>
```

Success (complete capture), in `stamps-decode.txt`, in this order after `cpu0-actlr DONE`:
`cpu0-em-version DONE … (EM x.y | EM not-supported)`, then, if 1.x, `cpu0-em-features DONE`, then seven
`cpu0-em-erratum DONE … (erratum N: <answer>)`, then `cpu0-audit DONE`, the five `0x00e6 DONE`, and in the console
`SWEET CPU: 5/5 CPUs initialized` and `blazer-root: deadline 300 s`. `cpu_audit.py` gives `errata_abi` with every answer.
`ok` stays false while bit 9 reads clear: that is the prerequisite verdict, unchanged.
Stop lines: last stamp `cpu0-em-* ENTER` (the SMC did not return; no retry), any unplanned panic, return check FAIL.

## 4. Decision tree after the answer (owner decisions, not automatic)

- **3685825 = higher-EL-mitigation (3)** while bit 9 reads clear: the firmware claims a mitigation the register does not show.
  Reconcile first (e.g. the mitigation is applied at power-on of cpu1 only). It is not acceptance by itself.
- **3685825 = affected (1)**: the firmware knows the erratum and does not fix it. The only route is an EL2 write of
  CPUACTLR[9] on each A520 before it runs XNU code. Whether EL3's ACTLREN allows it is unknown, and a trap is likely to be fatal.
  That is a register-write experiment that needs owner approval (docs/CPU.md forbids it today).
- **EM not supported (-1)** (likely for a vendor BL31): no firmware answer exists. A520 stays out unless the owner accepts the
  register-write experiment above.
- **cpu0** in any case: XNU on cpu0 needs a shim release mechanism (the parked loop jumps to XNU's secondary entry when SweetCPU
  "CPU_ON"s 0x0), or PSCI CPU_OFF on cpu0 after the handoff. Both are new shim and XNU work plus a design review. The partial probe
  credits cpu1 alone.
- **X4**: the EM query answers only for the calling PE, so an X4 answer needs code running on the X4 (a fastcore-style CPU_ON of
  0x700 into a shim stub). fastcore excludes the X4 by the parent's rule, so this is an owner decision too, made after the A520 path.

Reference: Arm Errata Management ABI (DEN0100); TF-A pin and A520 TRM/SDEN hashes in `research/ios26-cpu-complete-r3/resources/sources.json`.
No new web material was fetched for this lane.
