/* Host regression test for the global bring-up deadline (stamp.c).
 *
 * Bug class (parkqual1/2, 2026-10-28): tgl_stamp_over_deadline() measured
 * from the ring HEADER t0, which belongs to the first boot of a nonce and
 * survives a reset together with the trail. Every same-nonce re-entry then
 * failed its first bringup_gate: fdt-parse FAULT arg=&"post-wdt-survey"
 * (0x80011f77). The deadline must run from THIS boot's entry.
 *
 * Every case drives the real stamp.c through the shim_main prefix up to its
 * first gate (start.S:62, shim.c:273/301/303/313, bringup_gate shim.c:92-99,
 * stage_fail shim.c:154-165). The counters are captured values from the
 * failing runs (research/laguna-usb-fix/attempts/20261028-*-lwave-l2-*).
 * oracle_over_deadline() is the pre-fix logic. It must fire on P1/P2, which
 * proves these inputs can detect the regression.
 *
 * Build: -DTGL_STAMP_HOST -DTGL_STAMP_HOST_CLOCK (stamp.c reads the arch
 * timer from tgl_stamp_host_cntvct/_cntfrq). -DTGL_STAMP_DEADLINE_TEST_MAIN
 * adds a standalone main(). With -DTGL_STAMP_DEADLINE_SUT_ORACLE the gate
 * under test becomes the oracle, so the suite must FAIL (self-check).
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "tgl_stamp.h"

uint64_t tgl_stamp_host_cntvct, tgl_stamp_host_cntfrq;

#define DL_RING		(64u + TGL_STAMP_SLOTS * 24u)
#define DL_FREQ		UINT64_C(38400000)	/* captured header freq */
#define DL_SEC(s)	((uint64_t)(s) * DL_FREQ)
#define DL_SECONDS	90u	/* bringup_gate and loader.c pre-jump */
#define DL_WHERE	UINT64_C(0x80011f77)	/* &"post-wdt-survey" */

/* A = 20261028-155953-lwave-l2-pan2 (completed boot, header owner).
 * B = 20261028-161259-lwave-l2-parkqual1 (first same-nonce re-boot).
 * C = 20261028-161726-lwave-l2-parkqual2 (counter epoch below A's t0). */
#define A_T0		UINT64_C(0x44ec6467d)	/* 481.81 s */
#define A_TLAST		UINT64_C(0x48407adb1)
#define A_COUNT		115u
static const uint64_t b_t[6] = {	/* B slots 115..120 */
	UINT64_C(0x678798563), UINT64_C(0x6787987e9), UINT64_C(0x678798a30),
	UINT64_C(0x678799c76), UINT64_C(0x678799f02), UINT64_C(0x67879a2e0),
};
#define C_NOW		UINT64_C(0x203dbde84)	/* ~225.4 s < A_T0: wraps */
#define OTHER_NONCE	UINT64_C(0x3e7f0ceba0aeb501)	/* l1-postdme */

static uint8_t dl_ring[DL_RING];

static uint64_t rd64(unsigned off)
{
	uint64_t v;
	memcpy(&v, dl_ring + off, 8);
	return v;
}

static uint32_t rd32(unsigned off)
{
	uint32_t v;
	memcpy(&v, dl_ring + off, 4);
	return v;
}

static void wr64(unsigned off, uint64_t v) { memcpy(dl_ring + off, &v, 8); }
static void wr32(unsigned off, uint32_t v) { memcpy(dl_ring + off, &v, 4); }

/* A completed boot's surviving trail: header as captured in A, slots empty
 * (slot contents never feed the deadline). */
static void residue(uint64_t nonce, uint32_t count, uint32_t reason)
{
	memset(dl_ring, 0, sizeof(dl_ring));
	wr64(0x00, TGL_STAMP_MAGIC);
	wr64(0x08, nonce);
	wr32(0x10, count);
	wr32(0x14, count);
	wr32(0x18, TGL_STAGE_EL_DROP);
	wr32(0x1c, TGL_STAMP_F_DONE);
	wr64(0x20, DL_FREQ);
	wr64(0x28, A_T0);
	wr64(0x30, A_TLAST);
	wr32(0x3c, reason);
}

/* Pre-fix tgl_stamp_over_deadline (stamp.c before
 * stamp-deadline-per-boot.patch): origin = ring header t0/freq. */
static unsigned oracle_over_deadline(unsigned seconds)
{
	if (rd64(0x00) != TGL_STAMP_MAGIC || rd64(0x08) != TGL_STAMP_NONCE)
		return 0;
	uint64_t freq = rd64(0x20), t0 = rd64(0x28);
	if (!freq) return 0;
	return (tgl_stamp_host_cntvct - t0) / freq >= seconds;
}

#ifdef TGL_STAMP_DEADLINE_SUT_ORACLE
#define sut_over_deadline oracle_over_deadline
#else
#define sut_over_deadline tgl_stamp_over_deadline
#endif

struct dl_verdict { unsigned sut, oracle; };

/* shim_main prefix to the first gate. t[0..4] are the counters of the five
 * stamps (the gate reads t[4]); t[5] is the counter of the FAULT stamp.
 * The fault path follows the oracle when oracle_path is set (fidelity). */
static struct dl_verdict boot_prefix(const uint64_t t[6], int oracle_path)
{
	struct dl_verdict v;
	tgl_stamp_host_cntfrq = DL_FREQ;
	tgl_stamp_host_cntvct = t[0];
	tgl_stamp_boot_entry();
	tgl_stamp_host_cntvct = t[1];
	tgl_stamp(TGL_STAGE_CPU_STATE, TGL_STAMP_F_DONE, 0x80d01998);
	tgl_stamp_host_cntvct = t[2];
	tgl_stamp(TGL_STAGE_WDT_SURVEY, TGL_STAMP_F_ENTER, 0);
	tgl_stamp_host_cntvct = t[3];
	tgl_stamp(TGL_STAGE_WDT_SURVEY, TGL_STAMP_F_DONE, 3);
	tgl_stamp_host_cntvct = t[4];
	tgl_stamp(TGL_STAGE_FDT_PARSE, TGL_STAMP_F_ENTER, 0x8a000000);
	v.oracle = oracle_over_deadline(DL_SECONDS);
	v.sut = sut_over_deadline(DL_SECONDS);
	if (oracle_path ? v.oracle : v.sut) {
		tgl_stamp_reason(TGL_STAMP_R_TIMEOUT);
		tgl_stamp_host_cntvct = t[5];
		tgl_stamp_fail_current(DL_WHERE);
		if (!tgl_stamp_reason_get())
			tgl_stamp_reason(TGL_STAMP_R_TIMEOUT);
	}
	return v;
}

static void flat(uint64_t t[6], uint64_t entry, uint64_t gate)
{
	for (int i = 0; i < 5; i++) t[i] = entry;
	t[4] = t[5] = gate;
}

/* No FAULT slot and five appended stamps after `from`. */
static int clean_append(uint32_t from)
{
	if (rd32(0x10) != from + 5) return 0;
	for (uint32_t i = from; i < from + 5; i++)
		if (dl_ring[0x40 + i * 24 + 6] & TGL_STAMP_F_FAULT) return 0;
	return rd32(0x18) == TGL_STAGE_FDT_PARSE;
}

static int fails, cases;

static void check(const char *name, int ok, struct dl_verdict v,
    const char *what)
{
	cases++;
	fails += !ok;
	printf("%s %s: sut=%u oracle(header-t0)=%u  %s\n", ok ? "PASS" : "FAIL",
	    name, v.sut, v.oracle, what);
}

int tgl_stamp_deadline_selftest(void)
{
	struct dl_verdict v;
	uint64_t t[6];

	tgl_stamp_set_sink(dl_ring);
	fails = cases = 0;

	/* P1: B's boot on A's surviving same-nonce trail, B's own counters. */
	residue(TGL_STAMP_NONCE, A_COUNT, TGL_STAMP_R_HANDOFF);
	v = boot_prefix(b_t, 0);
	check("P1 A-residue + B counters (241.9 s past header t0)",
	    !v.sut && v.oracle && clean_append(A_COUNT), v,
	    "expect sut=0, oracle=1, 5 clean stamps");

	/* P2: C's boot on B's trail; C's counter is below A's t0, so the
	 * header-based subtraction wraps. */
	residue(TGL_STAMP_NONCE, A_COUNT + 6, TGL_STAMP_R_TIMEOUT);
	flat(t, C_NOW, C_NOW);
	v = boot_prefix(t, 0);
	check("P2 B-residue + C counter (< header t0, unsigned wrap)",
	    C_NOW < A_T0 && !v.sut && v.oracle && clean_append(A_COUNT + 6),
	    v, "expect sut=0, oracle=1");

	/* P3: the deadline still fires 90 s after THIS boot's entry, on a
	 * same-nonce re-entry (a fix that disables the gate fails here). */
	residue(TGL_STAMP_NONCE, A_COUNT, TGL_STAMP_R_HANDOFF);
	flat(t, b_t[0], b_t[0] + DL_SEC(DL_SECONDS) - 1);
	v = boot_prefix(t, 0);
	check("P3a same-nonce re-entry, gate at entry+90 s-1 tick", !v.sut,
	    v, "expect sut=0");
	residue(TGL_STAMP_NONCE, A_COUNT, TGL_STAMP_R_HANDOFF);
	flat(t, b_t[0], b_t[0] + DL_SEC(DL_SECONDS));
	v = boot_prefix(t, 0);
	check("P3b same-nonce re-entry, gate at entry+90 s", v.sut &&
	    rd32(0x3c) == TGL_STAMP_R_TIMEOUT &&
	    rd64(0x40 + (A_COUNT + 5) * 24 + 16) == DL_WHERE, v,
	    "expect sut=1, reason=TIMEOUT, FAULT arg=&post-wdt-survey");

	/* P4: fresh channel at C's low counter epoch, gate at entry+90 s. */
	memset(dl_ring, 0, sizeof(dl_ring));
	flat(t, C_NOW, C_NOW + DL_SEC(DL_SECONDS));
	v = boot_prefix(t, 0);
	check("P4 fresh channel, gate at entry+90 s", v.sut && v.oracle, v,
	    "expect sut=1, oracle=1");

	/* G5/G6 (A1 gate-alive geometry): same-nonce residue, re-entry at a
	 * counter BELOW the header t0 (C-epoch wrap), gate shortly after
	 * re-entry (quiet) and at entry+90 s (fires). Covers the deferred
	 * gate after a wrap re-entry, which P2/P3 do not. */
	residue(TGL_STAMP_NONCE, A_COUNT, TGL_STAMP_R_HANDOFF);
	flat(t, C_NOW, C_NOW + DL_SEC(1));
	v = boot_prefix(t, 0);
	check("G5 wrap re-entry, gate at entry+1 s", !v.sut && v.oracle, v,
	    "expect sut=0, oracle=1");
	residue(TGL_STAMP_NONCE, A_COUNT, TGL_STAMP_R_HANDOFF);
	flat(t, C_NOW, C_NOW + DL_SEC(DL_SECONDS));
	v = boot_prefix(t, 0);
	check("G6 wrap re-entry, gate at entry+90 s", v.sut, v,
	    "expect sut=1");

	/* N1: residue of another build (nonce mismatch) at A's t0. */
	residue(OTHER_NONCE == TGL_STAMP_NONCE ? ~OTHER_NONCE : OTHER_NONCE,
	    A_COUNT, TGL_STAMP_R_HANDOFF);
	flat(t, A_T0, A_T0);
	v = boot_prefix(t, 0);
	check("N1 other-nonce residue at A t0", !v.sut && !v.oracle &&
	    rd64(0x08) == TGL_STAMP_NONCE && rd64(0x28) == A_T0 &&
	    clean_append(0), v, "expect 0/0, header re-armed");

	/* N2: same-nonce re-entry within 90 s of the header t0. */
	residue(TGL_STAMP_NONCE, A_COUNT, TGL_STAMP_R_HANDOFF);
	flat(t, A_T0 + DL_SEC(60), A_T0 + DL_SEC(60));
	v = boot_prefix(t, 0);
	check("N2 A-residue, re-entry at t0+60 s", !v.sut && !v.oracle, v,
	    "expect 0/0");

	/* N3: zeroed channel (power-cycle-cleared DRAM) at B's counter. */
	memset(dl_ring, 0, sizeof(dl_ring));
	v = boot_prefix(b_t, 0);
	check("N3 zeroed channel at B counter", !v.sut && !v.oracle &&
	    clean_append(0), v, "expect 0/0");

	printf("RESULT: %s (%d/%d cases)\n", fails ? "FAIL" : "PASS",
	    cases - fails, cases);
	return fails;
}

#ifdef TGL_STAMP_DEADLINE_TEST_MAIN
/* Optional fidelity check against captured rings: argv = A B kernel.log
 * captures. The oracle-driven fault path must reproduce B byte-for-byte. */
static int fidelity(const char *pa, const char *pb)
{
	static uint8_t a[DL_RING], b[DL_RING];
	FILE *fa = fopen(pa, "rb"), *fb = fopen(pb, "rb");
	int ok = fa && fb && !fseek(fa, 0x230000, SEEK_SET) &&
	    !fseek(fb, 0x230000, SEEK_SET) &&
	    fread(a, 1, DL_RING, fa) == DL_RING &&
	    fread(b, 1, DL_RING, fb) == DL_RING;
	if (fa) fclose(fa);
	if (fb) fclose(fb);
	if (!ok) { printf("FAIL F1 cannot read captures\n"); return 1; }
	memcpy(dl_ring, a, DL_RING);
	if (rd64(0x08) != TGL_STAMP_NONCE) {
		printf("FAIL F1 capture nonce %#llx != TGL_STAMP_NONCE\n",
		    (unsigned long long)rd64(0x08));
		return 1;
	}
	struct dl_verdict v = boot_prefix(b_t, 1);
	int oracle_same = !memcmp(dl_ring, b, DL_RING);
	memcpy(dl_ring, a, DL_RING);
	struct dl_verdict w = boot_prefix(b_t, 0);
	int sut_same = !memcmp(dl_ring, b, DL_RING);
	ok = v.oracle && oracle_same && !w.sut && !sut_same;
	printf("%s F1 capture fidelity: oracle path ring==B(3136 B) %s; "
	    "sut path ring==B %s (expect IDENTICAL / DIFFERS)\n",
	    ok ? "PASS" : "FAIL", oracle_same ? "IDENTICAL" : "DIFFERS",
	    sut_same ? "IDENTICAL" : "DIFFERS");
	return !ok;
}

int main(int argc, char **argv)
{
	int rc = tgl_stamp_deadline_selftest() != 0;
	if (argc == 3) {
		tgl_stamp_set_sink(dl_ring);
		rc |= fidelity(argv[1], argv[2]);
	}
	return rc;
}
#endif
