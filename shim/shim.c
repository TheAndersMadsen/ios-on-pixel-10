/*
 * teguload v3 ("noras") — surgical bisection of the v2 DER Event 20 crash.
 *
 * Device truth (2026-10-25, research/tgl-console-v2.txt): the v2 image was
 * ACCEPTED by ABL, but ~3 s into the shim the SoC crash-reset itself —
 * reboot reason 0xc00e "Crash reset for DER Event 20" after "SEM: ECC RAS
 * error". v1 (no scanout probe, same payload window 0x80000000+256M)
 * reached the kernel, so the only new MMIO path in v2 — the DC9x00
 * scanout-probe readback — is the prime suspect: its fault gate catches
 * SYNCHRONOUS aborts (proven in QEMU), but on laguna silicon the same DPU
 * readback is an ASYNC SError classified RAS-uncorrectable, which no
 * exception hook can intercept.
 *
 * v3 therefore DEFAULTS THE SCANOUT PROBE OFF:
 *
 *   - DPU/DC9x00 MMIO readback: compiled out unless TGL_SCANOUT_PROBE=1
 *     (explicit lab build; the fault-gated probe code stays in probe.c).
 *   - Console goes straight to the v1-proven placeholder PA 0xf0000000
 *     (plain DRAM — v1 reached the kernel with exactly this fb posture);
 *     the banner prints FBSRC probe-skipped (DER-safe).
 *   - KEPT from v2 (all v1/v2-proven or memory-only): early WDT quiesce
 *     (source-verified google,wdt contract), runtime MPIDR, VBAR-first
 *     start.S, the visible findings console, live-FDT admission and the
 *     kexec-proven 0x80000000+256M handoff window.
 *
 * Bisection contract: if v3 STILL crash-resets 0xc00e ~3 s in, the WDT
 * quiesce writes are the trigger (v4 gates them too, TGL_WDT_KEEP posture);
 * if v3 survives past 3 s, the scanout probe is confirmed as the DER
 * trigger and we then watch for v1's 0xbab9 early kernel panic — with the
 * firmware WDTs now quiesced, WHEN that panic lands vs v1's is the
 * discriminator.
 */
#include <stdint.h>
#include "console.h"
#include "fdt.h"
#include "handoff.h"
#include "loader.h"
#include "probe.h"
#include "wdt.h"
#include "tgl_stamp.h"
#include "tgl_usb_console.h"
#include "tgl_display.h"
#include "tgl_ufs.h"
#include "tgl_ufs_route.h"
#include "tgl_ufs_link.h"
#include "guard.h"
#include "tgl_scanout_takeover.h"
#if defined(TGL_CHOOSER) && TGL_CHOOSER
#include "chooser.h"
#if defined(TGL_CHOOSER_IOS) && TGL_CHOOSER_IOS
#include "chooser_ios.h"
#endif
#endif
#if TGL_ALL_STAGES
#include "tgl_all.h"
#endif
#if TGL_ALL_DCS
#include "tgl_dcs.h"
#endif
#if TGL_ALL_TOUCH
#include "tgl_tp.h"
#endif

#define PSCI_SYSTEM_RESET UINT64_C(0x84000009)
#define TGL_VERSION	"laguna teguload v3.2 noras + USB console + TSHIMST1"
#define TGL_FB_FALLBACK	UINT64_C(0xf0000000)
/* v3.2 WDT posture ladder (wdt.h): PAT is the hang-proofing default — the
 * firmware watchdogs stay armed and patted through bring-up (the only
 * recovery that survives a hung MMIO bus) and are quiesced just before the
 * XNU handoff. EARLY is the legacy v3.1 first-thing quiesce (kept for the
 * DER bisection record); KEEP is the observe-only audit lane. */
#if !defined(TGL_WDT_EARLY) && !defined(TGL_WDT_KEEP)
#define TGL_WDT_PAT 1
#endif
#ifndef TGL_USB_WAIT_SECONDS
#define TGL_USB_WAIT_SECONDS 8
#endif
static unsigned reset_method = 1; /* saved Blazer /psci uses SMC */
static volatile int in_exception;
static const char *stage;
static unsigned stage_id; /* TSHIMST1 id matching the stage string */
/* This is an in-image diagnostic record, NOT persisted execution evidence. */
volatile uint64_t tgl_failure_record[8];

static uint64_t mpidr_boot; /* runtime boot CPU id; never assume CPU0 */
static struct tgl_wdt_state wdt[2];
/* v3: the DPU state (and the whole DC9x00 readback) exist only in the
 * explicit TGL_SCANOUT_PROBE=1 lab build; the DER-safe default never
 * declares or touches them. */
#if !defined(TGL_QEMU_TEST) && defined(TGL_SCANOUT_PROBE)
static struct tgl_dpu_state dpu;
#endif
static const char *fdt_error;

/* Paint-loop tick: keep the armed firmware watchdogs alive while the
 * console clears/paints thousands of Device-memory pixels. */
static void shim_con_tick(void)
{
	(void)wdt_pat(wdt);
}

/* v3.6 global bring-up deadline: armed by tgl_stamp_boot_entry (reason
 * IN-PROGRESS + t0), checked at every stage boundary. The firmware watchdog
 * is patted through bring-up, so an alive-but-stuck loop would otherwise run
 * forever; a wedged bus still resets via the watchdog, whose reset now
 * decodes as reason=in-progress + last_stage instead of reason=none. */
static void __attribute__((noreturn)) stage_fail(unsigned reason,
    const char *why, uint64_t code);

static void bringup_gate(const char *where)
{
	if (tgl_stamp_over_deadline(90)) {
		tgl_stamp_reason(TGL_STAMP_R_TIMEOUT);
		stage_fail(TGL_STAMP_R_TIMEOUT, "global bring-up deadline",
		    (uint64_t)(uintptr_t)where);
	}
}

static uint64_t psci_call(uint64_t fn)
{
	register uint64_t x0 __asm__("x0") = fn;
	register uint64_t x1 __asm__("x1") = 0;
	register uint64_t x2 __asm__("x2") = 0;
	register uint64_t x3 __asm__("x3") = 0;
	if (reset_method == 2)
		__asm__ volatile("hvc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) ::
		    "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
		    "x14", "x15", "x16", "x17", "memory");
	else
		__asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) ::
		    "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13",
		    "x14", "x15", "x16", "x17", "memory");
	return x0;
}

/* PSCI reset, spec'd not to return. */
static void __attribute__((noreturn)) reset_now(void)
{
	__asm__ volatile("dsb sy" ::: "memory");
	tgl_failure_record[7] = psci_call(PSCI_SYSTEM_RESET);
	for (;;) __asm__ volatile("wfe");
}

void tgl_usb_reset_now(void)
{
	reset_now();
}

/* ~40 s photograph window (cntvct), then PSCI reset so the phone returns to
 * ABL/fastboot. Bounded by an iteration guard as well: a dead arch timer
 * must not turn the recovery path itself into an infinite dark hang (the
 * wfe-based v3.1 loop could block forever on a never-delivered event). */
static void __attribute__((noreturn)) reset(void)
{
	uint64_t freq, t0;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
	if (!freq) freq = 38400000;
	__asm__ volatile("mrs %0, cntvct_el0" : "=r"(t0));
	uint64_t t = t0;
	uint64_t guard = freq * 40 / 64 + 4096; /* ~64 ticks/iter worst case */
	while (t - t0 < freq * 40 && --guard) {
		tgl_usb_console_service();
		__asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(t));
	}
	reset_now();
}

/* Terminal bring-up failure: stamp it, paint it, photograph window, reset.
 * This is the contract that keeps the phone from EVER hanging USB-dark: the
 * stage string stays on the panel for a human, the TSHIMST1 trail stays in
 * DRAM for the ramdump, and PSCI reset returns the phone to fastboot. */
static void __attribute__((noreturn)) stage_fail(unsigned reason,
    const char *why, uint64_t code)
{
	/* v3.8: the terminal record carries the CURRENTLY FAILING stage (the
	 * granular last_stage the failing phase already stamped), not a
	 * coarse section label — the v37 dump showed usb-warm [FAULT] for a
	 * phy-resume failure. */
	tgl_stamp_fail_current(code);
	/* Preserve a more specific reason an earlier phase already recorded
	 * (e.g. TGL_STAMP_R_CPM from the CPM/USB bring-up lane). */
	if (!tgl_stamp_reason_get())
		tgl_stamp_reason(reason);
	if (con_fb) {
		con_clear(RED);
		con_str("HANG", stage ? stage : "early entry");
		con_str("WHY", why);
		con_hex("CODE", code);
		con_hex("STAGE", stage_id);
		con_hex("ESRFAR", (probe_esr << 32) | (probe_far & 0xffffffffu));
		con_str("STAMPS", "pmsg+0x30000 survives reset; ramdump it");
		con_str("NEXT", "returning to ABL/fastboot in 40s");
	}
	reset();
}

void exc_handler(uint64_t slot, uint64_t *regs)
{
	uint64_t esr, elr, far, el;
	/* v3.9b (U1): the device releases the shim at EL2 (cpu-state stamp
	 * 0x80d01998), so the fault's syndrome lives in ESR_EL2/ELR_EL2/
	 * FAR_EL2 — the pre-v3.9b EL1 reads returned stale registers, which
	 * defeated probe recovery AND printed garbage on the panic screen.
	 * QEMU runs the same code at EL1; both levels are handled here. */
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
	if (el == 0x8) {
		__asm__ volatile("mrs %0, esr_el2" : "=r"(esr));
		__asm__ volatile("mrs %0, elr_el2" : "=r"(elr));
		__asm__ volatile("mrs %0, far_el2" : "=r"(far));
	} else {
		__asm__ volatile("mrs %0, esr_el1" : "=r"(esr));
		__asm__ volatile("mrs %0, elr_el1" : "=r"(elr));
		__asm__ volatile("mrs %0, far_el1" : "=r"(far));
	}
	/* v2: a faulting probe is a FINDING, not a crash — resume past the
	 * access; the probe site records ESR/FAR and continues. */
	if (probe_recover(esr, far)) return;
	/* v3.9b (U1): a fault inside a guarded section (the UFS probe
	 * ladder) unwinds to the section's caller instead of dying: the
	 * caller stamps FAULT(esr)+FAULT(far), fails its ladder honestly,
	 * and the boot continues on the recovery profile. A probe-armed
	 * single access was already handled above (finer grain). */
	if (tgl_guard_armed) {
		tgl_guard_esr = esr;
		tgl_guard_far = far;
		tgl_guard_unwind();
	}
	tgl_stamp_fail_current(slot); /* failing stage = last granular stamp */
	tgl_stamp_reason(TGL_STAMP_R_FAULT);
	if (in_exception) reset_now(); /* fault while painting: report nothing more */
	in_exception = 1;
	tgl_failure_record[0] = UINT64_C(0x54474c4641554c54);
	tgl_failure_record[1] = slot;
	tgl_failure_record[2] = esr;
	tgl_failure_record[3] = elr;
	tgl_failure_record[4] = far;
	tgl_failure_record[5] = regs[0];
	/* felix-style panic screen: red, text + registers + boot CPU id. */
	con_clear(RED);
	con_str("FAULT", stage ? stage : "early entry");
	con_hex("ESR", esr);
	con_hex("ELR", elr);
	con_hex("FAR", far);
	con_hex("MPIDR", mpidr_boot);
	con_hex("X0", regs[0]);
	con_hex("X1", regs[1]);
	con_hex("X2", regs[2]);
	con_hex("X3", regs[3]);
	con_hex("PA", probe_pa); /* last probed PA (0 if none) */
	reset();
}

void secondary_main(uint64_t idx)
{
	(void)idx;
	/* No CPU_ON occurs in this loader. Leave unexpected secondaries parked. */
	for (;;) __asm__ volatile("wfe");
}

/* Fault-gated read-only acceptance of a framebuffer PA: base, middle and
 * last line must read before this shim writes a single pixel.
 * v3: used ONLY by the TGL_SCANOUT_PROBE=1 lab build — the DER-safe
 * default performs no probe reads at all (an async SError cannot be
 * recovered, so "fault-gated" is not safety on silicon). */
#ifdef TGL_SCANOUT_PROBE
static int fb_probe_pa(uint64_t pa)
{
	uint32_t v;
	if (!pa || (pa & 3)) return 0;
	uint64_t mid = pa + (uint64_t)(FB_H / 2) * FB_STRIDE;
	uint64_t last = pa + (uint64_t)(FB_H - 1) * FB_STRIDE + (FB_W - 1) * 4;
	return probe_read32((uintptr_t)pa, &v) &&
	       probe_read32((uintptr_t)mid, &v) &&
	       probe_read32((uintptr_t)last, &v);
}
#endif /* TGL_SCANOUT_PROBE */

void shim_main(uint64_t dtb)
{
	static struct tgl_fdt_memory memory;
	/* Every boot, before any display work: a record from an earlier boot must never
	 * give XNU permission to touch the DPU (display-patch contract). */
	tgl_scanout_takeover_clear();
	/* Boot CPU id at runtime — v2 prints it and carries it onto every
	 * panic screen instead of assuming ABL released us on CPU0. */
	__asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr_boot));
	/* CPU-state evidence stamp: this loader's handoff contract is MMU-off
	 * EL1 (loader.c refuses anything else), so the "MMU on" record of the
	 * bring-up checklist is the measured ENTRY state instead. */
	{
		uint64_t el, sctlr;
		__asm__ volatile("mrs %0, CurrentEL; mrs %1, sctlr_el1"
		    : "=r"(el), "=r"(sctlr));
		tgl_stamp(TGL_STAGE_CPU_STATE, TGL_STAMP_F_DONE,
		    (el << 28) | (sctlr & 0x0fffffffu));
	}

	/* 1. Watchdog policy (v3.2): SURVEY first (fault-gated reads only —
	 * the first device interaction stays read-only), then KEEP them armed
	 * and patted through bring-up so any hang — including a wedged MMIO
	 * bus no software timeout can observe — self-recovers through the
	 * ~24/30 s firmware reset instead of hanging USB-dark. The full
	 * quiesce moved to just before the XNU handoff (below), so no WDT
	 * reset can fire mid-handoff. */
#if defined(TGL_WDT_EARLY)
	stage = "WDT quiesce (legacy early)";
	stage_id = TGL_STAGE_WDT_QUIESCE;
	tgl_stamp(stage_id, TGL_STAMP_F_ENTER, 0);
	wdt_quiesce_early(wdt);
	tgl_stamp(stage_id, TGL_STAMP_F_DONE,
	    (uint64_t)wdt[0].disabled | ((uint64_t)wdt[1].disabled << 1));
#elif defined(TGL_WDT_KEEP)
	stage = "WDT survey (keep)";
	stage_id = TGL_STAGE_WDT_SURVEY;
	tgl_stamp(stage_id, TGL_STAMP_F_ENTER, 0);
	wdt_survey_early(wdt);
	tgl_stamp(stage_id, TGL_STAMP_F_DONE,
	    (uint64_t)wdt[0].id_ok | ((uint64_t)wdt[1].id_ok << 1));
#else /* TGL_WDT_PAT */
	stage = "WDT survey (pat)";
	stage_id = TGL_STAGE_WDT_SURVEY;
	tgl_stamp(stage_id, TGL_STAMP_F_ENTER, 0);
	wdt_survey_early(wdt);
	tgl_stamp(stage_id, TGL_STAMP_F_DONE,
	    (uint64_t)wdt[0].id_ok | ((uint64_t)wdt[1].id_ok << 1) |
	    ((uint64_t)wdt[0].faulted << 2) | ((uint64_t)wdt[1].faulted << 3));
#endif

	/* 2. Live-FDT admission parse up front (read-only): its framebuffer
	 * node feeds the candidate chain; an invalid tree must still be
	 * SHOWABLE on a working console instead of vanishing (v1 behavior). */
	stage = "FDT admission";
	stage_id = TGL_STAGE_FDT_PARSE;
	tgl_stamp(stage_id, TGL_STAMP_F_ENTER, dtb);
	bringup_gate("post-wdt-survey");
	if (!dtb || (dtb & 7))
		fdt_error = "missing/alignment";
	else
		fdt_error = tgl_fdt_memory((const void *)(uintptr_t)dtb,
		    TGL_FDT_MAX_SIZE, &memory);
	if (!fdt_error && memory.psci_method) reset_method = memory.psci_method;

#if defined(TGL_CHOOSER) && TGL_CHOOSER
	/* A2 chooser: the Android branch must run before any console, display
	 * record, USB, UFS or CPM work and must never quiesce a watchdog. It
	 * returns only with a refusal; a refusal resets (force-fastboot parks). */
	stage = "chooser";
	stage_id = TGL_STAGE_CHOOSER_ENTER;
	if (fdt_error)
		stage_fail(TGL_STAMP_R_REFUSED, fdt_error, dtb);
#if defined(TGL_CHOOSER_IOS) && TGL_CHOOSER_IOS
	{
		/* chooser_ios.c: iOS picked returns with the display off as ABL left it, the EL2 MMU
		 * and caches off and the watchdogs patted; continue on the direct iOS path below. */
		const char *chosen = tgl_chooser_run(dtb, &memory, shim_con_tick, 0);
		if (chosen != TGL_CHOOSER_PICKED_IOS)
			stage_fail(TGL_STAMP_R_REFUSED, chosen, 0);
	}
#else
	stage_fail(TGL_STAMP_R_REFUSED,
	    tgl_chooser_run(dtb, &memory, shim_con_tick, 0), 0);
#endif
#endif

	stage = "console init";
	stage_id = TGL_STAGE_CONSOLE_INIT;
	tgl_stamp(stage_id, TGL_STAMP_F_ENTER, 0);
	bringup_gate("post-fdt");
	/* 3. Console framebuffer.
	 * v3 DEFAULT (this build): NO DPU/DC9x00 MMIO and no probe reads —
	 * the console takes the v1-proven placeholder PA directly and the
	 * banner logs FBSRC probe-skipped (DER-safe). The memory-only DTFB
	 * scan stays purely informational (the stock laguna tree has no fb
	 * node; an unprobed DT candidate is deliberately NOT adopted in
	 * this posture).
	 * TGL_SCANOUT_PROBE=1 restores the v2 lab posture: the full
	 * candidate chain (DT fb node -> DC9x00 live-scanout readback ->
	 * placeholder), every candidate probe-read at base/middle/last
	 * line before any write — for explicit display-contract lab runs
	 * only, never the flash default. */
	uint64_t cand[3];
	const char *csrc[3];
	unsigned ncand = 0;
	uint64_t dtfb = 0;
#ifdef TGL_QEMU_TEST
	if (!fdt_error && tgl_qemu_profile(memory.compatible)) {
		cand[ncand] = TGL_FB_FALLBACK; csrc[ncand++] = "qemu-scratch";
	}
#elif defined(TGL_SCANOUT_PROBE)
	{
		const char *which = 0;
		if (!fdt_error && fdt_find_framebuffer(dtb, &dtfb, &which) && dtfb) {
			cand[ncand] = dtfb; csrc[ncand++] = which;
		}
		probe_dpu(&dpu); /* read-only, fault-gated */
		if (dpu.candidate) {
			cand[ncand] = dpu.candidate; csrc[ncand++] = "dpu-scanout";
		}
		cand[ncand] = TGL_FB_FALLBACK; csrc[ncand++] = "placeholder";
	}
#else
	{
		const char *which = 0;
		if (!fdt_error) (void)fdt_find_framebuffer(dtb, &dtfb, &which);
		cand[ncand] = TGL_FB_FALLBACK;
		csrc[ncand++] = "probe-skipped (DER-safe)";
	}
#endif
	int con_ready = 0;
#ifdef TGL_SCANOUT_PROBE
	for (unsigned i = 0; i < ncand && !con_ready; i++)
		if (fb_probe_pa(cand[i])) {
			con_init((uintptr_t)cand[i]);
			con_ready = 1;
		}
#else
	/* Single pre-agreed candidate (qemu-scratch or the placeholder):
	 * both are RAM-backed in their environments — no reads first. */
	if (ncand) {
		con_init((uintptr_t)cand[0]);
		con_ready = 1;
	}
#endif
	if (!con_ready) {
		/* No probeable framebuffer: record and bounce so the ABL slot
		 * ladder retries promptly (no 40 s wait — nothing to read). */
		tgl_failure_record[0] = 3;
		tgl_stamp_reason(TGL_STAMP_R_REFUSED);
		reset_now();
	}
	const char *fbsrc = "none";
	for (unsigned i = 0; i < ncand; i++)
		if ((uint64_t)con_fb_pa == cand[i]) { fbsrc = csrc[i]; break; }

#ifndef TGL_QEMU_TEST
	/* Build the fail-closed 128-byte display record on every physical boot.
	 * Only exact FDT bootargs may unlock the one-shot CPM/snapshot/revive
	 * ladder; the default path performs no display or CPM MMIO here. */
	tgl_display_console_init(&memory, con_fb_pa);
#endif

	/* 4. Findings console: one cumulative screen; panic screens paint over.
	 * The paint itself can cost seconds of Device-memory stores (the
	 * 2026-10-27 run measured 26.4 s on this path), so the tick hook pats
	 * the armed firmware watchdog while pixels go out. */
	con_tick = &shim_con_tick;
	con_clear(BLUE);
	tgl_stamp(TGL_STAGE_CONSOLE_CLS, TGL_STAMP_F_DONE, 0);
	con_str("SHIM", TGL_VERSION);
	con_hex("MPIDR", mpidr_boot);
#if defined(TGL_WDT_EARLY)
	con_str("WDTPOS", "legacy early quiesce (DER bisection)");
#elif defined(TGL_WDT_KEEP)
	con_str("WDTPOS", "keep: survey only, never written");
#else
	con_str("WDTPOS", "armed+pat during bring-up; quiesce pre-handoff");
	/* First pat now that the evidence channels (screen + stamps) exist;
	 * every later stage boundary and long wait re-pats. */
	stage_id = TGL_STAGE_WDT_PAT;
	tgl_stamp(stage_id, TGL_STAMP_F_DONE, (unsigned)wdt_pat(wdt));
#endif
	for (unsigned i = 0; i < 2; i++) {
		char lbl[5] = { 'W', 'D', 'T', (char)('0' + i), 0 };
		if (wdt[i].faulted)
			con_str(lbl, "quiesce fault");
		else if (wdt[i].skipped)
			con_str(lbl, wdt[i].id_ok ? "kept (lab posture)" :
			    wdt[i].esr ? "absent (probe fault)" :
			    "absent (unexpected ID)");
		else
			con_hex2(lbl, "was=", wdt[i].was, "now=", wdt[i].now);
		if (wdt[i].faulted || (wdt[i].skipped && wdt[i].esr)) {
			con_hex("WESR", wdt[i].esr);
			con_hex("WFAR", wdt[i].far);
		}
	}
#ifndef TGL_QEMU_TEST
#ifdef TGL_SCANOUT_PROBE
	if (!dpu.probed) {
		con_str("DPU", "inaccessible (probe fault)");
		con_hex("DESRC", dpu.esr);
		con_hex("DFAR", dpu.far);
	} else {
		con_hex2("DPU", "cid=", dpu.chip_id, "cfg=", dpu.config);
		con_hex2("DFB", "lo=", dpu.addr_lo, "hi=", dpu.addr_hi);
		con_hex2("DST", "stride=", dpu.stride, "size=", dpu.size);
		con_hex2("OP0", "a=", dpu.coord0_a, "b=", dpu.coord0_b);
	}
#else
	/* v3 DER-safe default: the readback that DER-crashed v2 never runs;
	 * the banner states the posture instead of a DPU register dump. */
	con_str("DPU", "probe-skipped (DER-safe)");
#endif
#endif
	if (dtfb) con_hex("DTFB", dtfb);
	con_hex("FBPA", con_fb_pa);
#ifndef TGL_QEMU_TEST
	con_hex("DHO", tgl_display_record()->flags);
#endif
	con_str("FBSRC", fbsrc);
	con_hex("DTB", dtb);

	/* 5. FDT refusal is now VISIBLE (v1 reset silently here). */
	if (fdt_error) {
		tgl_failure_record[0] = 1;
		con_str("REFUSED", fdt_error);
		tgl_stamp_reason(TGL_STAMP_R_REFUSED);
		reset();
	}
	if (memory.psci_method) reset_method = memory.psci_method;
	con_str("DTCOMPAT", memory.compatible);

#ifndef TGL_USB_DISABLE
	/* 6. EP0 console. On DEVICE builds any bring-up failure is now
	 * terminal WITH evidence: paint the failing stage, leave the TSHIMST1
	 * trail, photograph window, PSCI reset -> the phone returns to
	 * ABL/fastboot instead of handing off to XNU dark (the 18:37 boot
	 * taught us that a "diagnostic" failure that continues is exactly
	 * what produces an unrecoverable-looking state). QEMU builds keep the
	 * advisory posture so the payload smoke path still runs. */
	stage = "USB diagnostic";
	stage_id = TGL_STAGE_USB_WARM; /* v3.5: the bring-up starts at the warm
	 * probe (CPM only on the cold fallback); a terminal failure labels
	 * usb-warm, and the granular stamps carry the detail */
	bringup_gate("post-console");
	int usb_status = tgl_usb_console_start(&memory);
	con_hex2("USB", "init=", (uint32_t)(int32_t)usb_status,
	    "run=", laguna_usb_running());
#ifndef TGL_QEMU_TEST
	if (usb_status)
		stage_fail(TGL_STAMP_R_USBFATAL, "usb console bring-up failed",
		    (uint32_t)(int32_t)usb_status);
#endif
	/* Quiesce the watchdogs BEFORE the diagnostic enumeration wait: the
	 * survey finds THREE WDTs but the pat path services only two, and an
	 * unpatted instance bites ~9 s after the last pat — exactly where the
	 * v39-v43 runs died (13.4 s = pat@4.4 s + 9.0 s). From here the only
	 * recovery tool that matters is the 90 s stamped deadline. */
	{
		stage = "WDT quiesce (pre-handoff)";
		stage_id = TGL_STAGE_WDT_QUIESCE;
		tgl_stamp(stage_id, TGL_STAMP_F_ENTER, 0);
		wdt_quiesce_late(wdt);
		tgl_stamp(stage_id, TGL_STAMP_F_DONE,
		    (uint64_t)wdt[0].disabled | ((uint64_t)wdt[1].disabled << 1));
	}
	tgl_usb_console_wait(TGL_USB_WAIT_SECONDS);
	bringup_gate("post-usb");
#else
	con_str("USB", "disabled at build time");
#endif

	/* 6.5 UFS probe ladder (v3.9, P2 lane): U0-U9, one attempt per boot,
	 * side-effect-light, fail-closed. Evidence lands in the stamp
	 * channel (ids 0x0048-0x0054, reason 8) + the EP0 console. The
	 * result is consumed by the honest-handoff cmdline gate in
	 * loader_boot(): without the U8 LIVE stamp the payload cmdline is
	 * rewritten to the recovery profile (no blazer_ufs tokens, rd=md0)
	 * before anything reaches XNU. QEMU builds skip it (no UFS). */
#ifndef TGL_QEMU_TEST
#ifndef TGL_UFS_DISABLE
	{
		static struct tgl_ufs_result ufs_result;
		unsigned guard_fault = 0;
		stage = "UFS probe ladder";
		stage_id = TGL_STAGE_UFS_FIRST;
#if TGL_ALL_STAGES
		{
			static const uint8_t all_nonce[16] = TGL_UFS_RECORD_NONCE;
			tgl_all_begin(TGL_STAMP_NONCE, all_nonce, TGL_UFS_EPOCH);
			tgl_all_mark(TGL_ALL_S_UFS, TGL_ALL_ENTER, 0);
		}
#endif
		/* v3.9b (U1, fix A): drive the UFSHCI base + the PSM status
		 * trio from the ABL FDT's ufs node (reg[0..5], the real
		 * laguna ufs@3c400000 layout) instead of trusting build-time
		 * constants; the constants remain the fallback when the tree
		 * carries no UFS node. The setter refuses misaligned/zero
		 * bases and keeps the fallback. */
		static struct tgl_ufs_fdt_regions ufr;
		{
			if (fdt_find_ufs(dtb, &ufr)) {
				const uint64_t psm[3] = {
					ufr.psm[0], ufr.psm[1], ufr.psm[2]
				};
				tgl_ufs_set_regions(ufr.hc, psm);
				con_hex("UFSB", ufr.hc);
			}
		}
		tgl_stamp(stage_id, TGL_STAMP_F_ENTER, 0);
		bringup_gate("pre-ufs");
		/* v3.9b (U1, fix B): the ENTIRE ladder is fault-guarded.
		 * Device truth 20261028-100405-v3p9-ufs1: the first HCI read
		 * (DT-correct 0x3c400000, host powered down after ABL) took
		 * a synchronous external abort the pre-EL-aware recovery
		 * could not match, and the boot died on the FAULT screen
		 * with no honest md0 fallback. From this build ANY fault
		 * inside the ladder unwinds HERE, is stamped, and the boot
		 * continues to the recovery handoff. A probe never parks
		 * the phone. */
		/* J1_UFS_WDT_BRACKET_BEGIN: host tests execute this exact block. */
#if TGL_UFS_WDT_GUARD
		static struct tgl_ufs_wdt_guard ufs_wdt_guard;
		void (*saved_con_tick)(void) = con_tick;
		con_tick = 0; /* never reload the stale early-survey VALUE */
		tgl_stamp(TGL_STAGE_WDT_PAT, TGL_STAMP_F_ENTER, TGL_WDT_BASE1);
		tgl_stamp(TGL_STAGE_WDT_PAT, TGL_STAMP_F_ENTER,
		    UINT64_C(0x5744543100000000) | TGL_WDT_UFS_RELOAD);
		int ufs_wdt_rc = wdt_ufs_guard_start(&ufs_wdt_guard, &wdt[1]);
		tgl_stamp(TGL_STAGE_WDT_PAT, ufs_wdt_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (uint64_t)ufs_wdt_guard.id_after << 32 | ufs_wdt_guard.control_before);
		tgl_stamp(TGL_STAGE_WDT_PAT, ufs_wdt_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (uint64_t)ufs_wdt_guard.arm_step << 32 | ufs_wdt_guard.control_after);
		tgl_stamp(TGL_STAGE_WDT_PAT, ufs_wdt_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
		    (uint64_t)ufs_wdt_guard.value_after << 32 | TGL_WDT_UFS_RELOAD);
		if (ufs_wdt_rc) {
			if (ufs_wdt_guard.esr) {
				tgl_stamp(TGL_STAGE_WDT_PAT, TGL_STAMP_F_FAULT, ufs_wdt_guard.esr);
				tgl_stamp(TGL_STAGE_WDT_PAT, TGL_STAMP_F_FAULT, ufs_wdt_guard.far);
			}
			tgl_stamp(TGL_STAGE_UFS_FIRST, TGL_STAMP_F_REFUSED,
			    UINT64_C(0x5744543100000000) | ufs_wdt_guard.arm_step);
			tgl_stamp_reason(TGL_STAMP_R_UFS);
		}
		if (!ufs_wdt_rc) {
#endif
		tgl_guard_esr = 0;
		tgl_guard_far = 0;
		tgl_guard_armed = 1;
#if TGL_UFS_ROUTE
		/* Link, then post-link, READ. Never branches boot flow on the result, only on doubt about DMA. */
		guard_fault = tgl_ufs_route_link_guarded(&ufr);
		tgl_guard_armed = 0;
		if (guard_fault)
			tgl_ufs_link_note_fault(tgl_guard_esr, tgl_guard_far);
		tgl_stamp(TGL_STAGE_UFS_FIRST, guard_fault ? TGL_STAMP_F_FAULT : TGL_STAMP_F_DONE,
		    (uint64_t)(int64_t)tgl_ufs_link_last_rc());
#if TGL_UFS_POST_LINK
		if (!guard_fault) {
			tgl_stamp(0x00e5, TGL_STAMP_F_ENTER, 0);
			int ufs_route_rc = tgl_ufs_route_after_link();
			tgl_stamp(0x00e5, ufs_route_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE, (uint64_t)(int64_t)ufs_route_rc);
			/* The arena would be live under memory XNU owns. */
			if (tgl_ufs_route_must_park())
				stage_fail(TGL_STAMP_R_UFS, "UFS post-link DMA uncertain", (uint64_t)(int64_t)ufs_route_rc);
		}
#endif
#if TGL_UFS_HANDOFF
		if (tgl_ufs_route_handoff(guard_fault) < 0)
			stage_fail(TGL_STAMP_R_UFS, "UFS DMA not quiesced", 0);
		ufs_result = *tgl_ufs_result();
#endif
#else
		guard_fault = tgl_ufs_guarded_ladder(&ufs_result);
		tgl_guard_armed = 0;
		if (guard_fault)
			tgl_ufs_trap_fail(tgl_guard_esr, tgl_guard_far);
#endif
#if TGL_UFS_WDT_GUARD
		}
		tgl_stamp(TGL_STAGE_WDT_QUIESCE, TGL_STAMP_F_ENTER, TGL_WDT_BASE1);
		if (wdt_ufs_guard_stop(&ufs_wdt_guard)) {
			tgl_stamp(TGL_STAGE_WDT_QUIESCE, TGL_STAMP_F_FAULT,
			    (uint64_t)ufs_wdt_guard.stop_step << 32 | ufs_wdt_guard.control_after);
			stage = "UFS watchdog stop";
			stage_id = TGL_STAGE_WDT_QUIESCE;
			stage_fail(TGL_STAMP_R_FAULT, "UFS watchdog stop failed", ufs_wdt_guard.stop_step);
		}
		tgl_stamp(TGL_STAGE_WDT_QUIESCE, TGL_STAMP_F_DONE, ufs_wdt_guard.control_after);
		con_tick = saved_con_tick; /* restore only after verified safe stop */
#endif
		/* J1_UFS_WDT_BRACKET_END */
		con_hex2("UFS", "steps=", ufs_result.steps,
		    "live=", ufs_result.live);
		bringup_gate("post-ufs");
	}
#endif
#endif

#if TGL_ALL_STAGES
	/* all-r1. Order is ascending chance of losing what follows: a reset here costs this boot's root, so UFS, already proven, went first
	 * and the first DPU writes go last. A stage's own failure falls through to XNU; only a pending SError or a watchdog that will not stop ends the boot, by name. */
	{
		void (*all_saved_tick)(void) = con_tick;
		tgl_all_mark(TGL_ALL_S_UFS_DONE, TGL_ALL_DONE, 0);
#if TGL_ALL_TOUCH
		{
			static struct tgl_ufs_wdt_guard tp_wdt;
			static const uint8_t tp_nonce[16] = TGL_UFS_RECORD_NONCE;
			uint64_t all_daif, all_isr;
			stage = "touch-r1";
			stage_id = TGL_TP_STAGE_ID;
			con_tick = 0;
			tgl_all_mark(TGL_ALL_S_TOUCH, TGL_ALL_ENTER, 0);
			tgl_stamp(TGL_TP_STAGE_ID, TGL_STAMP_F_ENTER, 0);
			tgl_tp_begin(TGL_STAMP_NONCE, tp_nonce, TGL_UFS_EPOCH, reset_method);
			int tp_rc = wdt_ufs_guard_start(&tp_wdt, &wdt[1]);
			tgl_stamp(TGL_STAGE_WDT_PAT, tp_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE, (uint64_t)tp_wdt.arm_step << 32 | tp_wdt.control_after);
			__asm__ volatile("mrs %0, daif" : "=r"(all_daif));
			if (tp_rc) {
				tgl_tp_refuse(TP_S_ADMIT, TP_C_WDT, tp_wdt.arm_step);
				tp_rc = TP_C_WDT;
			} else {
				tp_rc = (int)tgl_tp_guarded();
			}
			uint64_t tp_esr = tgl_guard_esr, tp_far = tgl_guard_far;
			int tp_stop = wdt_ufs_guard_stop(&tp_wdt);
			tgl_tp_finish(tp_rc, tp_esr, tp_far, (uint64_t)(uint32_t)tp_stop << 8 | tp_wdt.stop_step);
			tgl_stamp(TGL_TP_STAGE_ID, tp_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE, (uint32_t)tp_rc);
			__asm__ volatile("mrs %0, isr_el1" : "=r"(all_isr));
			tgl_all_mark(TGL_ALL_S_TOUCH, tp_rc ? TGL_ALL_FELL_THROUGH : TGL_ALL_DONE, tp_rc);
			if (tp_stop) stage_fail(TGL_STAMP_R_FAULT, "touch watchdog stop failed", tp_wdt.stop_step);
			if (all_isr & (1u << 8)) stage_fail(TGL_STAMP_R_FAULT, "touch left an SError pending", all_isr);
			__asm__ volatile("msr daif, %0\n\tisb" :: "r"(all_daif));
			bringup_gate("post-touch");
		}
#endif
#if TGL_ALL_DCS
		{
			static struct tgl_ufs_wdt_guard dcs_wdt;
			static const uint8_t dcs_nonce[16] = TGL_UFS_RECORD_NONCE;
			uint64_t all_daif, all_isr;
			stage = "display-frame-r1";
			stage_id = TGL_DCS_STAGE_ID;
			con_tick = 0;
			tgl_all_mark(TGL_ALL_S_DPU, TGL_ALL_ENTER, 0);
			tgl_stamp(TGL_DCS_STAGE_ID, TGL_STAMP_F_ENTER, 0);
			tgl_dcs_begin(TGL_STAMP_NONCE, dcs_nonce, TGL_UFS_EPOCH);
			int dcs_rc = wdt_ufs_guard_start(&dcs_wdt, &wdt[1]);
			tgl_stamp(TGL_STAGE_WDT_PAT, dcs_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE, (uint64_t)dcs_wdt.arm_step << 32 | dcs_wdt.control_after);
			__asm__ volatile("mrs %0, daif" : "=r"(all_daif));
			if (dcs_rc) {
				tgl_dcs_refuse(DCS_S_ADMIT, DCS_C_WDT, dcs_wdt.arm_step);
				dcs_rc = DCS_C_WDT;
			} else {
				dcs_rc = (int)tgl_dcs_guarded();
			}
			uint64_t dcs_esr = tgl_guard_esr, dcs_far = tgl_guard_far;
			int dcs_stop = wdt_ufs_guard_stop(&dcs_wdt);
			tgl_dcs_finish(dcs_rc, dcs_esr, dcs_far, (uint64_t)(uint32_t)dcs_stop << 8 | dcs_wdt.stop_step);
			tgl_stamp(TGL_DCS_STAGE_ID, dcs_rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE, (uint32_t)dcs_rc);
			__asm__ volatile("mrs %0, isr_el1" : "=r"(all_isr));
			tgl_all_mark(TGL_ALL_S_DPU, dcs_rc ? TGL_ALL_FELL_THROUGH : TGL_ALL_DONE, dcs_rc);
			if (dcs_stop) stage_fail(TGL_STAMP_R_FAULT, "display watchdog stop failed", dcs_wdt.stop_step);
			if (all_isr & (1u << 8)) stage_fail(TGL_STAMP_R_FAULT, "display left an SError pending", all_isr);
			__asm__ volatile("msr daif, %0\n\tisb" :: "r"(all_daif));
			bringup_gate("post-display");
		}
#endif
		con_tick = all_saved_tick;
	}
#endif
#ifdef TGL_QEMU_TEST
	/* Explicitly opt-in scratch pixels, never selected by a physical splash
	 * node name. RAM/reservations and all resident inputs must admit it. */
	if (tgl_qemu_profile(memory.compatible)) {
		extern char _head[], _end[];
		struct tgl_range shim = {(uintptr_t)_head, (uintptr_t)_end - (uintptr_t)_head};
		struct tgl_range rd;
		const char *err = tgl_handoff_inputs(&memory, dtb, shim, &rd);
		struct tgl_range fb = { con_fb_pa, FB_STRIDE * FB_H }, none = {0, 0};
		if (!err) err = tgl_handoff_window(&memory, fb, dtb, shim, rd, none);
		con_str(err ? "QEMUGATE" : "QEMU", err ? err : "test profile admitted scratch fb");
	}
#endif

	/* 7. Payload admission + handoff. Do not abandon an active EP0 transfer;
	 * the XNU-side msgbuf mirror is an independent telemetry channel. */
	stage = "payload admission";
	stage_id = TGL_STAGE_PAYLOAD;
	tgl_stamp(stage_id, TGL_STAMP_F_ENTER, dtb);
	bringup_gate("post-usb-wait");
#ifndef TGL_USB_DISABLE
	tgl_usb_console_wait(1);
	if (laguna_usb_transfer_active()) {
		con_str("USB", "busy; refusing handoff");
		stage_fail(TGL_STAMP_R_REFUSED, "usb transfer active at handoff", 0);
	}
#endif
	/* 8. WDT quiesce moves HERE (v3.2): all bounded waits are behind us,
	 * so stopping the firmware watchdogs now cannot leave a hang
	 * unrecovered, and nothing between this point and the jump runs long
	 * enough to trip anything. Guarantees (a) no WDT reset mid-handoff
	 * and (b) any earlier hang already self-recovered. */
#if TGL_ALL_STAGES
	tgl_all_mark(TGL_ALL_S_XNU_JUMP, TGL_ALL_ENTER, 0);
#endif
	const char *why = loader_boot((uintptr_t)dtb);
	tgl_failure_record[0] = 2;
	{
		/* The refusal text lands only on the dead-panel console —
		 * pack the first 8 bytes into the stamp channel so the dump
		 * names the exact refusing check, and record the shim's own
		 * load PA so the payload window can be placed around it. */
		extern char _head[];
		uint64_t txt = 0;
		if (why) for (int i = 0; i < 8 && why[i]; ++i)
			txt |= (uint64_t)(uint8_t)why[i] << (8 * i);
		tgl_stamp(TGL_STAGE_PAYLOAD, TGL_STAMP_F_REFUSED, txt);
		tgl_stamp(TGL_STAGE_PAYLOAD, TGL_STAMP_F_REFUSED,
		    (uint64_t)(uintptr_t)_head);
	}
	tgl_stamp_reason(TGL_STAMP_R_REFUSED);
	con_str("REFUSED", why ? why : "returned");
	stage = "rejected/returned payload";
	reset();
}
