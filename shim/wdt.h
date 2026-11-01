#pragma once
#include <stdint.h>

/*
 * laguna firmware watchdog quiesce (v2) — the verified Google WDT contract.
 *
 * Register map and stop sequence are source-pinned (GrapheneOS kernel_pixel_6.6
 * fac4effc829311dabd53d2d0e8cc3090318e6453
 * private/google-modules/soc/rdo/watchdog/google_wdt_local.h / google_wdt.c)
 * and verified against the actual stock module disassembly
 * (research/reuse-audit-20261024/boot/google-wdt-stop.asm.txt: KEY+0x10,
 * VALUE+0xc, CONTROL+0x8, clearing bit0). Live DT
 * (hardware/bootchain-20261022/live-fdt.dtb) fixes the two bases, the unlock
 * key 0xc0ffee, the lock key 0 and the 38.4 MHz /oscillator clock:
 *   watchdog_cl0@200c4000 timeout 24 s expiry-action 0 (irq)
 *   watchdog_cl1@200c5000 timeout 30 s expiry-action 1 (reset)
 *
 * Posture change vs the observe-only audit lane: the parent task orders the
 * felix pattern — quiesce BOTH cluster watchdogs EARLY so a payload fault
 * cannot become reboot-reason 0xbab9 before the console is up. Recovery on
 * the flash path stays with the ABL's own 60 s watchdog
 * (NEXT-TEGULOAD-FLASH.sh step 0: fastboot oem watchdog enable).
 *
 * Every access is fault-gated (probe.h); an unexpected ID or a faulting
 * register leaves that watchdog untouched and records the finding.
 * Build-time fallback: EXTRA_CFLAGS=-DTGL_WDT_KEEP skips the quiesce
 * (observe-only, the audit lane posture) for lab runs.
 */

#define TGL_WDT_BASE0	UINT64_C(0x200c4000)	/* watchdog_cl0 */
#define TGL_WDT_BASE1	UINT64_C(0x200c5000)	/* watchdog_cl1 */
#define TGL_WDT_ID_VALUE	UINT32_C(0x00574454)	/* "WDT" part number */
#define TGL_WDT_KEY_UNLOCK	UINT32_C(0xc0ffee)	/* live DT key-unlock */
#define TGL_WDT_KEY_LOCK	UINT32_C(0x00000000)	/* live DT key-lock */
#define TGL_WDT_CONTROL_ENABLE	UINT32_C(0x1)		/* CONTROL bit0 */
#define TGL_WDT_VALUE_MAX	UINT32_C(0xffffffff)	/* ~111.8 s at 38.4 MHz */

struct tgl_wdt_state {
	uintptr_t base;
	unsigned id_ok, disabled, faulted, skipped, patted;
	uint32_t was, now, value;
	uint64_t esr, far;
};

/* v3.2 hang-proofing policy (default build): survey EARLY (read-only, no
 * writes at the very first device interaction), PAT the armed watchdogs at
 * every stage boundary and inside long waits so any bring-up hang — including
 * a hung MMIO bus no software timeout can observe — self-recovers through the
 * ~24/30 s firmware reset, then QUIESCE both just before the XNU handoff so
 * no reset can fire mid-handoff or while the payload owns the machine.
 * Build-time variants for the bisection record:
 *   -DTGL_WDT_EARLY  legacy v3.1: quiesce both FIRST (the posture that left
 *                    the 18:37 USB-dark boot with nothing to reset it).
 *   -DTGL_WDT_KEEP   observe-only audit lane: survey, never write. */
void wdt_survey_early(struct tgl_wdt_state out[2]);
int wdt_pat(struct tgl_wdt_state out[2]);
void wdt_quiesce_late(struct tgl_wdt_state out[2]);

/* Legacy v3.1 combined quiesce (survey + stop, first interaction). */
void wdt_quiesce_early(struct tgl_wdt_state out[2]);

/* J1: independent one-shot UFS-only reset guard. Default-off preserves
 * existing bring-up. The ordinary path quiesces before enumeration; this
 * explicit guard rearms CL1 only for UFS and verifies stop before handoff. */
#ifndef TGL_UFS_WDT_GUARD
#define TGL_UFS_WDT_GUARD 0
#endif
#if TGL_UFS_WDT_GUARD != 0 && TGL_UFS_WDT_GUARD != 1
#error "TGL_UFS_WDT_GUARD must be 0 or 1"
#endif
#if TGL_UFS_WDT_GUARD && (defined(TGL_WDT_KEEP) || defined(TGL_WDT_EARLY))
#error "UFS WDT guard cannot mix with legacy KEEP/EARLY watchdog profiles"
#endif
#if TGL_UFS_WDT_GUARD
#define TGL_WDT_UFS_RESET_ACTION UINT32_C(8)
#define TGL_WDT_UFS_KEY_ENABLED UINT32_C(4)
#define TGL_WDT_UFS_SECONDS 30u
#define TGL_WDT_UFS_CLOCK_HZ UINT32_C(38400000)
#define TGL_WDT_UFS_RELOAD (TGL_WDT_UFS_SECONDS * TGL_WDT_UFS_CLOCK_HZ)
/* Local fail-closed startup tolerance, not an assumed countdown semantic. */
#define TGL_WDT_UFS_MIN_REMAINING (29u * TGL_WDT_UFS_CLOCK_HZ)
struct tgl_ufs_wdt_guard {
 unsigned attempted, identity_verified, needs_stop, armed;
 unsigned stop_attempted, stopped, arm_step, stop_step;
 uint32_t id_after, control_before, control_after, value_after;
 uint64_t esr, far;
};
/* Requires the already-surveyed and positively disabled CL1 state. Always
 * call stop after start, including start failure: partial writes may have
 * armed/unlocked the block. No reset guarantee exists until start succeeds. */
int wdt_ufs_guard_start(struct tgl_ufs_wdt_guard *g,
    const struct tgl_wdt_state *cl1);
/* Zero means verified disabled+locked, or an identity-gated no-write start
 * failure. Nonzero blocks payload handoff. No stale VALUE snapshot is used. */
int wdt_ufs_guard_stop(struct tgl_ufs_wdt_guard *g);
#endif
