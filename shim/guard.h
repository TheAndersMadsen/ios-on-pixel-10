#pragma once
#include <stdint.h>

/*
 * tgl_guard — section-level fault guard (v3.9b, U1 lane).
 *
 * probe.c recovers ONE fault-gated access; some sections need more: a fault
 * ANYWHERE inside them must return control to the caller with a verdict, so
 * a bring-up experiment can never take the shim down with it. The UFS probe
 * ladder is the first user (device truth 2026-10-28 attempt
 * 20261028-100405-v3p9-ufs1: a synchronous external abort on the first
 * UFSHCI read hit the pre-EL-aware recovery gap and took the whole boot to
 * the FAULT screen; the honest md0 fallback never ran).
 *
 * Contract (call pattern, shim.c):
 *   tgl_guard_esr = 0; tgl_guard_far = 0;
 *   tgl_guard_armed = 1;
 *   if (tgl_guard_arm_body())   <- wrapper fn; see below
 *           ...
 * The arm helper spills the FULL register file (x0..x30, sp) of the frame
 * that calls it. If a non-recoverable exception happens while armed,
 * exc_handler records ESR/FAR and calls tgl_guard_unwind(): registers,
 * SP and ELR are restored to the arm point and eret resumes the wrapper
 * right after the arm call — i.e. as if the risky call had instantly
 * returned. The wrapper then returns "faulted" and the caller finishes
 * its own fail path (stamp, honest fallback). A probe-armed single access
 * inside the section is still handled by probe_recover first (finer
 * grain); the guard catches everything else: unprobed MMIO, wild branch,
 * misaligned stack access, any EC.
 *
 * EL symmetry: the unwind writes ELR_EL1 or ELR_EL2 by CurrentEL, matching
 * the v3.9b EL-aware exception path (device runs the shim at EL2).
 */

/* 1 while a guarded section is executing; exc_handler checks it. */
extern volatile unsigned tgl_guard_armed;
/* ESR/FAR of the fault that triggered the unwind (0 = no fault). */
extern volatile uint64_t tgl_guard_esr, tgl_guard_far;

/* Spill the caller's register file. Call at the top of a tiny wrapper
 * function immediately before the risky call; the saved LR (the wrapper's
 * own return-continuation) is where the unwind resumes. */
void tgl_guard_arm(void);

/* exc_handler escape: restore + eret. Never returns. Call only when
 * tgl_guard_armed != 0 and ESR/FAR have already been recorded. */
void tgl_guard_unwind(void) __attribute__((noreturn));
