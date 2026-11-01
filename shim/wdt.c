/* laguna firmware watchdog policy — see wdt.h.
 *
 * v3.2 posture (S1 hang-proofing): the firmware cluster watchdogs are the
 * only recovery that survives a hung MMIO bus (no software timeout can fire
 * while a bus read never returns), so bring-up KEEPS them armed and pats
 * them at stage boundaries instead of quiescing first. The full quiesce
 * moves to just before the XNU handoff, so (a) no WDT reset can fire
 * mid-handoff and (b) any bring-up hang self-recovers through the ABL/slot
 * ladder instead of hanging USB-dark. Every access stays fault-gated
 * (probe.h); an unexpected ID or a faulting register leaves that block
 * untouched and records the finding.
 */
#include <stdint.h>
#include "probe.h"
#include "wdt.h"

/* Fault-gated ID + CONTROL + VALUE reads; NO writes. */
static void survey_one(struct tgl_wdt_state *w)
{
	uint32_t v;
	w->id_ok = 0; w->disabled = 0; w->faulted = 0; w->skipped = 0;
	w->patted = 0;
	w->was = 0; w->now = 0; w->value = 0; w->esr = 0; w->far = 0;

	/* Hardware gate: the ID register identifies the google,wdt block.
	 * On a foreign platform (QEMU virt) this read faults -> skipped. */
	if (!probe_read32(w->base + 0x00U, &v)) {
		w->skipped = 1;
		w->esr = probe_esr; w->far = probe_far;
		return;
	}
	if (v != TGL_WDT_ID_VALUE) {
		w->skipped = 1; /* unexpected ID: leave the block untouched */
		return;
	}
	w->id_ok = 1;
	if (!probe_read32(w->base + 0x08U, &v)) goto fault;
	w->was = v;
	if (!probe_read32(w->base + 0x0cU, &v)) goto fault;
	w->value = v;
	return;
fault:
	w->faulted = 1;
	w->esr = probe_esr; w->far = probe_far;
}

/* KEY unlock -> VALUE refresh -> KEY lock, CONTROL untouched: reloads the
 * surveyed budget without changing enable state or expiry action. */
static int pat_one(struct tgl_wdt_state *w)
{
	uint32_t v;
	if (!w->id_ok || w->faulted) return -1;
	if (!probe_write32(w->base + 0x10U, TGL_WDT_KEY_UNLOCK)) goto fault;
	if (!probe_write32(w->base + 0x0cU, w->value)) goto fault;
	if (!probe_write32(w->base + 0x10U, TGL_WDT_KEY_LOCK)) goto fault;
	if (!probe_read32(w->base + 0x08U, &v)) goto fault;
	w->now = v;
	w->patted = 1;
	return 0;
fault:
	w->faulted = 1;
	w->esr = probe_esr; w->far = probe_far;
	return -1;
}

/* Stock google_wdt stop: unlock KEY, refresh VALUE, clear ENABLE, write
 * CONTROL, lock KEY. Requires a successful survey: never touch a block we
 * could not identify. */
static int stop_one(struct tgl_wdt_state *w)
{
	uint32_t v;
	if (!w->id_ok || w->faulted) return -1;
	if (!probe_write32(w->base + 0x10U, TGL_WDT_KEY_UNLOCK)) goto fault;
	if (!probe_write32(w->base + 0x0cU, TGL_WDT_VALUE_MAX)) goto fault;
	if (!probe_write32(w->base + 0x08U, w->was & ~TGL_WDT_CONTROL_ENABLE))
		goto fault;
	if (!probe_write32(w->base + 0x10U, TGL_WDT_KEY_LOCK)) goto fault;
	if (!probe_read32(w->base + 0x08U, &v)) goto fault;
	w->now = v;
	w->disabled = !(w->now & TGL_WDT_CONTROL_ENABLE);
	return 0;
fault:
	w->faulted = 1;
	w->esr = probe_esr; w->far = probe_far;
	return -1;
}

void wdt_survey_early(struct tgl_wdt_state out[2])
{
	out[0].base = TGL_WDT_BASE0;
	out[1].base = TGL_WDT_BASE1;
	survey_one(&out[0]);
	survey_one(&out[1]);
}

int wdt_pat(struct tgl_wdt_state out[2])
{
	int ok = 0;
	for (unsigned i = 0; i < 2; i++)
		if (!pat_one(&out[i])) ok++;
	return ok;
}

void wdt_quiesce_late(struct tgl_wdt_state out[2])
{
	for (unsigned i = 0; i < 2; i++) {
		out[i].disabled = 0;
		if (!stop_one(&out[i]) && out[i].disabled) continue;
		/* Untouched (no ID) or failed: report via the existing flags;
		 * the console shows skipped/faulted for that watchdog. */
	}
}

/* Legacy v3.1 posture, kept for the DER bisection A/B (-DTGL_WDT_EARLY):
 * survey then immediately stop both watchdogs as the FIRST interaction. */
void wdt_quiesce_early(struct tgl_wdt_state out[2])
{
	wdt_survey_early(out);
	for (unsigned i = 0; i < 2; i++) {
		struct tgl_wdt_state *w = &out[i];
		if (!w->id_ok) continue; /* survey already recorded skip/fault */
		(void)stop_one(w);
	}
}

#if TGL_UFS_WDT_GUARD
_Static_assert(TGL_WDT_UFS_RELOAD == UINT32_C(0x44aa2000), "30s at DT 38.4MHz");

static int ufs_wdt_fault(struct tgl_ufs_wdt_guard *g)
{
 if (!g->esr) { g->esr = probe_esr; g->far = probe_far; }
 return -1;
}

int wdt_ufs_guard_start(struct tgl_ufs_wdt_guard *g,
    const struct tgl_wdt_state *cl1)
{
 uint32_t id = 0, control = 0;
 if (!g || g->attempted) return -1;
 g->attempted = 1;
 if (!cl1 || cl1->base != TGL_WDT_BASE1 || !cl1->id_ok ||
     cl1->faulted || cl1->skipped || !cl1->disabled) return -1;
 /* Fresh identity/control proof: the early survey alone is insufficient. */
 g->arm_step = 1;
 if (!probe_read32(TGL_WDT_BASE1, &id)) return ufs_wdt_fault(g);
 g->id_after = id;
 if (id != TGL_WDT_ID_VALUE) return -1;
 g->identity_verified = 1;
 g->arm_step = 2;
 if (!probe_read32(TGL_WDT_BASE1 + 8, &control)) return ufs_wdt_fault(g);
 g->control_after = control;
 g->control_before = control;
 if (control & (TGL_WDT_CONTROL_ENABLE | TGL_WDT_UFS_KEY_ENABLED)) {
  g->needs_stop = 1; /* do not knowingly pass an unexpectedly armed WDT */
  return -1;
 }
 g->needs_stop = 1; /* even a faulting first write can have side effects */
 g->arm_step = 3;
 if (!probe_write32(TGL_WDT_BASE1 + 0x10, TGL_WDT_KEY_UNLOCK)) return ufs_wdt_fault(g);
 g->arm_step = 4;
 if (!probe_read32(TGL_WDT_BASE1 + 8, &control)) return ufs_wdt_fault(g);
 g->control_after = control;
 if (!(control & TGL_WDT_UFS_KEY_ENABLED)) return -1;
 g->arm_step = 5;
 if (!probe_write32(TGL_WDT_BASE1 + 0xc, TGL_WDT_UFS_RELOAD)) return ufs_wdt_fault(g);
 g->arm_step = 6;
 if (!probe_read32(TGL_WDT_BASE1 + 8, &control)) return ufs_wdt_fault(g);
 g->control_after = control;
 control |= TGL_WDT_UFS_RESET_ACTION | TGL_WDT_CONTROL_ENABLE;
 g->arm_step = 7;
 if (!probe_write32(TGL_WDT_BASE1 + 8, control)) return ufs_wdt_fault(g);
 g->arm_step = 8;
 if (!probe_write32(TGL_WDT_BASE1 + 0x10, TGL_WDT_KEY_LOCK)) return ufs_wdt_fault(g);
 g->arm_step = 9;
 if (!probe_read32(TGL_WDT_BASE1 + 8, &control)) return ufs_wdt_fault(g);
 g->control_after = control;
 g->control_after = control;
 if ((control & (TGL_WDT_CONTROL_ENABLE | TGL_WDT_UFS_RESET_ACTION)) !=
     (TGL_WDT_CONTROL_ENABLE | TGL_WDT_UFS_RESET_ACTION) ||
     (control & TGL_WDT_UFS_KEY_ENABLED)) return -1;
 g->arm_step = 10;
 if (!probe_read32(TGL_WDT_BASE1 + 0xc, &g->value_after)) return ufs_wdt_fault(g);
 /* VALUE readback is not assumed to be a live down-counter; Google's
  * public test model returns the programmed reload value. */
 if (g->value_after < TGL_WDT_UFS_MIN_REMAINING ||
     g->value_after > TGL_WDT_UFS_RELOAD) return -1;
 g->armed = 1;
 return 0;
}

int wdt_ufs_guard_stop(struct tgl_ufs_wdt_guard *g)
{
 uint32_t control = 0;
 if (!g) return -1;
 if (g->stopped) return 0;
 if (g->stop_attempted) return -1;
 g->stop_attempted = 1;
 if (!g->needs_stop) { g->stopped = 1; return 0; }
 if (!g->identity_verified) return -1;
 /* Google stop sequence uses CURRENT CONTROL, not the early survey's
  * stale was/value. Cleanup is attempted even after a partial arm fault. */
 g->stop_step = 1;
 if (!probe_write32(TGL_WDT_BASE1 + 0x10, TGL_WDT_KEY_UNLOCK)) return ufs_wdt_fault(g);
 g->stop_step = 2;
 if (!probe_read32(TGL_WDT_BASE1 + 8, &control)) return ufs_wdt_fault(g);
 g->control_after = control;
 if (!(control & TGL_WDT_UFS_KEY_ENABLED)) return -1;
 g->stop_step = 3;
 if (!probe_write32(TGL_WDT_BASE1 + 0xc, TGL_WDT_UFS_RELOAD)) return ufs_wdt_fault(g);
 g->stop_step = 4;
 if (!probe_read32(TGL_WDT_BASE1 + 8, &control)) return ufs_wdt_fault(g);
 g->control_after = control;
 g->stop_step = 5;
 if (!probe_write32(TGL_WDT_BASE1 + 8, control & ~TGL_WDT_CONTROL_ENABLE)) return ufs_wdt_fault(g);
 g->stop_step = 6;
 if (!probe_write32(TGL_WDT_BASE1 + 0x10, TGL_WDT_KEY_LOCK)) return ufs_wdt_fault(g);
 g->stop_step = 7;
 if (!probe_read32(TGL_WDT_BASE1 + 8, &control)) return ufs_wdt_fault(g);
 g->control_after = control;
 g->control_after = control;
 if (control & (TGL_WDT_CONTROL_ENABLE | TGL_WDT_UFS_KEY_ENABLED)) return -1;
 g->armed = 0;
 g->stopped = 1;
 return 0;
}
#endif
