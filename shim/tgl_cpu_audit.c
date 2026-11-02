/*
 * Audit cpu0's firmware state at EL2, then keep the existing five-A725 route.
 * CPUACTLR bits 9/38 are prerequisites, not a complete A520 errata verdict.
 * Source for the register/bit meanings: docs/CPU.md. Never writes CPUACTLR,
 * requests CPU_OFF, starts an A520, or changes clocks or topology.
 */
#include "tgl_cpu_audit.h"
#include "tgl_stamp.h"

#if TGL_CPU_AUDIT
static unsigned audit_enabled;

#ifdef TGL_CPU_AUDIT_HOST
uint64_t tgl_cpu_audit_read(unsigned reg);
#else
static uint64_t tgl_cpu_audit_read(unsigned reg)
{
	uint64_t v;
	switch (reg) {
	case TGL_CPU_AUDIT_STAGE: __asm__ volatile("mrs %0, mpidr_el1" : "=r"(v)); break;
	case TGL_CPU_AUDIT_MIDR: __asm__ volatile("mrs %0, midr_el1" : "=r"(v)); break;
	case TGL_CPU_AUDIT_EL: __asm__ volatile("mrs %0, CurrentEL" : "=r"(v)); break;
	case TGL_CPU_AUDIT_SCTLR: __asm__ volatile("mrs %0, sctlr_el2" : "=r"(v)); break;
	case TGL_CPU_AUDIT_REVIDR: __asm__ volatile("mrs %0, revidr_el1" : "=r"(v)); break;
	case TGL_CPU_AUDIT_ACTLR: __asm__ volatile("mrs %0, S3_0_C15_C1_0" : "=r"(v)); break;
	default: return 0;
	}
	return v;
}
#endif

int tgl_cpu_audit_configure(const char *line, unsigned max)
{
	static const char key[] = "blazer_cpu0_audit";
	unsigned i = 0, found = 0, value = 0;
	audit_enabled = 0;
	while (i < max && line[i]) {
		if (line[i] == ' ') { ++i; continue; }
		unsigned j = 0;
		while (key[j] && i + j < max && line[i + j] == key[j]) ++j;
		if (!key[j]) {
			unsigned v = i + j;
			if (found || v + 2 >= max || line[v] != '=' ||
			    (line[v + 1] != '0' && line[v + 1] != '1') ||
			    (line[v + 2] && line[v + 2] != ' ')) return -1;
			found = 1;
			value = (unsigned)(line[v + 1] - '0');
		}
		while (i < max && line[i] && line[i] != ' ') ++i;
	}
	if (i >= max) return -1;
	audit_enabled = value;
	return (int)value;
}

int tgl_cpu_audit_prepare(void)
{
	if (!audit_enabled) return 1;
	uint64_t mpidr = tgl_cpu_audit_read(TGL_CPU_AUDIT_STAGE);
	tgl_stamp(TGL_CPU_AUDIT_STAGE, TGL_STAMP_F_ENTER, mpidr);
	/* Do not read an implementation-specific register on an unexpected core. */
	if ((mpidr & UINT64_C(0xff00ffffff)) != 0) goto refused;
	uint64_t midr = tgl_cpu_audit_read(TGL_CPU_AUDIT_MIDR);
	tgl_stamp(TGL_CPU_AUDIT_MIDR, TGL_STAMP_F_DONE, midr);
	if (midr != UINT64_C(0x410fd801)) goto refused;
	uint64_t el = tgl_cpu_audit_read(TGL_CPU_AUDIT_EL);
	tgl_stamp(TGL_CPU_AUDIT_EL, TGL_STAMP_F_DONE, el);
	if (el != 8) goto refused;
	uint64_t sctlr = tgl_cpu_audit_read(TGL_CPU_AUDIT_SCTLR);
	tgl_stamp(TGL_CPU_AUDIT_SCTLR, TGL_STAMP_F_DONE, sctlr);
	if (sctlr & ((UINT64_C(1) << 12) | 5)) goto refused;
	tgl_stamp(TGL_CPU_AUDIT_REVIDR, TGL_STAMP_F_DONE,
	    tgl_cpu_audit_read(TGL_CPU_AUDIT_REVIDR));
	/* If the MRS traps, ENTER survives and cannot be mistaken for a result. */
	tgl_stamp(TGL_CPU_AUDIT_ACTLR, TGL_STAMP_F_ENTER, 0);
	uint64_t actlr = tgl_cpu_audit_read(TGL_CPU_AUDIT_ACTLR);
	tgl_stamp(TGL_CPU_AUDIT_ACTLR, TGL_STAMP_F_DONE, actlr);
	tgl_stamp(TGL_CPU_AUDIT_STAGE, TGL_STAMP_F_DONE, 0);
	return 1;
refused:
	tgl_stamp(TGL_CPU_AUDIT_STAGE, TGL_STAMP_F_REFUSED, 0);
	return 0;
}
#endif
