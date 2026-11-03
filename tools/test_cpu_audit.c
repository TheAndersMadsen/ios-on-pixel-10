/* Actual shim C with modeled registers/PSCI. These tests never access a device. */
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "tgl_cpu_audit.h"
#include "tgl_fastcore.h"
#include "tgl_stamp.h"

extern volatile struct tgl_fc tgl_fc;
char _head[64], _bss_start[1], _end[64];
void tgl_fc_entry(uint64_t c) { (void)c; }
static uint64_t regs[6], ticks;
static unsigned reads[6], on_calls, done_before_on, audit_done, stamp_count;
static struct { unsigned stage, flags; uint64_t arg; } stamps[64];
/* Modeled Errata ABI firmware: version, features, per-erratum answer. */
static int64_t em_version, em_features, em_answer;
static unsigned em_calls, em_erratum_calls, em_after_on;

static jmp_buf parked;
uint64_t tgl_cpu_audit_read(unsigned reg)
{
	assert(reg >= TGL_CPU_AUDIT_STAGE && reg <= TGL_CPU_AUDIT_ACTLR);
	unsigned n = reg - TGL_CPU_AUDIT_STAGE;
	++reads[n];
	return regs[n];
}
void tgl_stamp(unsigned stage, unsigned flags, uint64_t arg)
{
	assert(stamp_count < 64);
	stamps[stamp_count].stage = stage; stamps[stamp_count].flags = flags;
	stamps[stamp_count++].arg = arg;
	if (stage == TGL_CPU_AUDIT_STAGE && flags == TGL_STAMP_F_DONE) ++audit_done;
}
int64_t fc_smc(uint64_t op, uint64_t core, uint64_t entry, uint64_t context)
{
	(void)entry;
	if (op == UINT64_C(0x8400000a)) return core == UINT64_C(0xc4000003) ? 0 : -1;
	if (op == UINT64_C(0xc4000004)) { assert(core == 0x200); return 1; }
	assert(op == UINT64_C(0xc4000003)); /* Refuse any unexpected PSCI, including OFF. */
	assert(core == 0x200 && context == (uint64_t)&tgl_fc);
	++on_calls; done_before_on = audit_done;
	tgl_fc.mpidr = 0x200; tgl_fc.midr = 0x410fd871; tgl_fc.el = 8;
	tgl_fc.cntfrq = 38400000; tgl_fc.revidr = 1; tgl_fc.isr = 0;
	tgl_fc.arrived = TGL_FC_ARRIVED;
	return 0;
}
int64_t tgl_cpu_audit_smc(uint64_t fid, uint64_t x1)
{
	++em_calls; if (on_calls) ++em_after_on;
	if (fid == TGL_EM_VERSION) { assert(x1 == 0); return em_version; }
	if (fid == TGL_EM_FEATURES) { assert(x1 == TGL_EM_CPU_ERRATUM_FEATURES); return em_features; }
	assert(fid == TGL_EM_CPU_ERRATUM_FEATURES); /* Nothing but the three EM queries. */
	assert(x1 == tgl_cpu_audit_errata[em_erratum_calls]);
	++em_erratum_calls;
	return x1 == 3685825u ? em_answer : 2;
}
uint64_t fc_now(void) { return ++ticks; }
uint64_t fc_freq(void) { return 38400000; }
uint64_t fc_mpidr(void) { return regs[0]; }
void fc_clean(void) {}
void fc_sync(void) {}
void fc_park(void) { longjmp(parked, 1); }

static void reset(void)
{
	memset((void *)&tgl_fc, 0, sizeof(tgl_fc)); memset(reads, 0, sizeof(reads));
	memset(stamps, 0, sizeof(stamps));
	regs[0] = 0x81000000; regs[1] = 0x410fd801; regs[2] = 8;
	regs[3] = 0x30c50830; regs[4] = 3; regs[5] = (UINT64_C(1) << 9) | (UINT64_C(1) << 38);
	on_calls = done_before_on = audit_done = stamp_count = 0; ticks = 0;
	em_version = 0x10000; em_features = 0; em_answer = 1; em_calls = em_erratum_calls = em_after_on = 0;
	assert(tgl_cpu_audit_configure("", 1) == 0);
}
static const char *handoff(void)
{
	if (!setjmp(parked)) return tgl_fastcore_handoff(0x200, 0xa015bf000, 0xa02000000);
	return NULL;
}
static void parser(void)
{
	static const struct { const char *line; int result; } cases[] = {
		{"", 0}, {"debug=1", 0}, {"blazer_cpu0_audit=0", 0}, {"blazer_cpu0_audit=1", 1},
		{"  debug=1 blazer_cpu0_audit=1  cpus=5 ", 1},
		{"xblazer_cpu0_audit=1", 0}, {"blazer_cpu0_audit", -1},
		{"blazer_cpu0_audit=", -1}, {"blazer_cpu0_audit=2", 2}, {"blazer_cpu0_audit=3", -1},
		{"blazer_cpu0_audit=01", -1}, {"blazer_cpu0_audit=1x", -1},
		{"blazer_cpu0_audit_extra=1", -1}, {"blazer_cpu0_audit=1\t", -1},
		{"blazer_cpu0_audit=0 blazer_cpu0_audit=1", -1},
		{"blazer_cpu0_audit=1 blazer_cpu0_audit=1", -1},
	};
	for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
		reset(); assert(tgl_cpu_audit_configure(cases[i].line, (unsigned)strlen(cases[i].line) + 1) == cases[i].result);
		if (cases[i].result < 1) { assert(tgl_cpu_audit_prepare()); assert(stamp_count == 0); }
	}
	char bounded[] = "blazer_cpu0_audit=1";
	for (unsigned n = 0; n < sizeof(bounded); ++n) {
		reset(); assert(tgl_cpu_audit_configure(bounded, n) == -1);
		assert(tgl_cpu_audit_prepare() && stamp_count == 0);
	}
}
int main(void)
{
	parser();
	reset(); assert(handoff() == NULL); assert(on_calls == 1 && !audit_done);
	for (unsigned i = 0; i < 6; ++i) assert(reads[i] == 0);
	reset(); assert(tgl_cpu_audit_configure("blazer_cpu0_audit=1", sizeof("blazer_cpu0_audit=1")) == 1);
	assert(handoff() == NULL && on_calls == 1 && done_before_on == 1);
	for (unsigned i = 0; i < 6; ++i) assert(reads[i] == 1);
	assert(tgl_fc.go == TGL_FC_GO_RUN);
	assert(stamps[7].stage == TGL_CPU_AUDIT_ACTLR && stamps[7].arg == regs[5]);
	/* Feed the actual emitted C records to the Python verifier, not just a hand-written fixture. */
	printf("TRACE [");
	for (unsigned i = 0; i < stamp_count; ++i)
		printf("%s[%u,%u,%llu]", i ? "," : "", stamps[i].stage, stamps[i].flags,
		    (unsigned long long)stamps[i].arg);
	puts("]");
	/* A missing workaround is a reported value; it never silently changes hardware. */
	reset(); regs[5] = 0; assert(tgl_cpu_audit_configure("blazer_cpu0_audit=1", sizeof("blazer_cpu0_audit=1")) == 1);
	assert(handoff() == NULL && on_calls == 1 && done_before_on == 1);
	assert(stamps[7].arg == 0);
	for (unsigned i = 0; i < 6; ++i) {
		reset(); assert(tgl_cpu_audit_configure("blazer_cpu0_audit=1", sizeof("blazer_cpu0_audit=1")) == 1);
		if (i == 0) regs[0] = 0x100;
		if (i == 1) regs[1] = 0x410fd871;
		if (i == 2) regs[2] = 4;
		if (i >= 3) regs[3] |= UINT64_C(1) << (i == 3 ? 0 : i == 4 ? 2 : 12);
		assert(strcmp(handoff(), "fc-audit") == 0);
		assert(!on_calls && !audit_done && !reads[5]);
		assert(stamps[stamp_count - 1].flags == TGL_STAMP_F_REFUSED);
	}
	assert(em_calls == 0); /* Mode 1 never makes an Errata ABI call. */
	/* Mode 2: the same eight records, the EM queries between ACTLR DONE and the audit DONE, all before CPU_ON. */
	static const char m2[] = "blazer_cpu0_audit=2";
	reset(); assert(tgl_cpu_audit_configure(m2, sizeof(m2)) == 2);
	assert(handoff() == NULL && on_calls == 1 && done_before_on == 1);
	assert(em_calls == 2 + TGL_CPU_AUDIT_N_ERRATA && em_erratum_calls == TGL_CPU_AUDIT_N_ERRATA && !em_after_on);
	assert(stamps[8].stage == TGL_CPU_AUDIT_EM_VERSION && stamps[8].flags == TGL_STAMP_F_ENTER);
	assert(stamps[9].stage == TGL_CPU_AUDIT_EM_VERSION && stamps[9].arg == 0x10000);
	assert(stamps[11].stage == TGL_CPU_AUDIT_EM_FEATURES && stamps[11].arg == 0);
	assert(stamps[12].stage == TGL_CPU_AUDIT_EM_ERRATUM && stamps[12].flags == TGL_STAMP_F_ENTER && stamps[12].arg == 3685825u);
	assert(stamps[13].arg == ((uint64_t)3685825u << 32 | 1u));
	unsigned last = 12 + 2 * TGL_CPU_AUDIT_N_ERRATA;
	assert(stamps[last].stage == TGL_CPU_AUDIT_STAGE && stamps[last].flags == TGL_STAMP_F_DONE);
	assert(tgl_fc.go == TGL_FC_GO_RUN);
	printf("TRACE2 [");
	for (unsigned i = 0; i < stamp_count; ++i)
		printf("%s[%u,%u,%llu]", i ? "," : "", stamps[i].stage, stamps[i].flags,
		    (unsigned long long)stamps[i].arg);
	puts("]");
	/* Negative answers are recorded as 32-bit two's complement and never stop the handoff. */
	reset(); em_answer = -3; assert(tgl_cpu_audit_configure(m2, sizeof(m2)) == 2);
	assert(handoff() == NULL && on_calls == 1 && stamps[13].arg == ((uint64_t)3685825u << 32 | 0xfffffffdu));
	/* No EM 1.x (unknown SMC = -1, or another major): one call, then the audit ends normally. */
	static const int64_t versions[] = {-1, 0x20000, 0x00001};
	for (unsigned i = 0; i < 3; ++i) {
		reset(); em_version = versions[i]; assert(tgl_cpu_audit_configure(m2, sizeof(m2)) == 2);
		assert(handoff() == NULL && on_calls == 1 && done_before_on == 1 && em_calls == 1);
		assert(stamps[9].arg == (uint64_t)versions[i] && stamps[10].stage == TGL_CPU_AUDIT_STAGE);
	}
	/* EM present but the erratum query not offered: two calls, no erratum query. */
	reset(); em_features = -1; assert(tgl_cpu_audit_configure(m2, sizeof(m2)) == 2);
	assert(handoff() == NULL && on_calls == 1 && em_calls == 2 && !em_erratum_calls);
	/* A refused identity makes no EM call either. */
	reset(); regs[1] = 0x410fd871; assert(tgl_cpu_audit_configure(m2, sizeof(m2)) == 2);
	assert(strcmp(handoff(), "fc-audit") == 0 && !em_calls && !on_calls);
	puts("cpu audit actual-C parser, ordering, refusal, no-OFF, Errata ABI read-only mode 2 and unchanged handoff: PASS");
	return 0;
}
