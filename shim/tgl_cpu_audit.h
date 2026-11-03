#pragma once
/* Read-only cpu0 prerequisite for future A520 support. No CPU_OFF or register writes. */
#ifndef TGL_CPU_AUDIT
#define TGL_CPU_AUDIT 0
#endif
#if TGL_CPU_AUDIT && !TGL_FASTCORE
#error "cpu0 audit requires the established fastcore handoff"
#endif

#define TGL_CPU_AUDIT_STAGE 0x00e7u
#define TGL_CPU_AUDIT_MIDR 0x00e8u
#define TGL_CPU_AUDIT_EL 0x00e9u
#define TGL_CPU_AUDIT_SCTLR 0x00eau
#define TGL_CPU_AUDIT_REVIDR 0x00ebu
#define TGL_CPU_AUDIT_ACTLR 0x00ecu
#define TGL_CPU_AUDIT_EM_VERSION 0x00edu  /* mode 2: DONE arg = sign-extended EM_VERSION result */
#define TGL_CPU_AUDIT_EM_ERRATUM 0x00eeu  /* mode 2: ENTER arg = id; DONE arg = id << 32 | (u32)result */
#define TGL_CPU_AUDIT_EM_FEATURES 0x00efu /* mode 2: DONE arg = sign-extended EM_FEATURES(0x840000F2) */

/* Arm Errata Management ABI (DEN0100), queries only. */
#define TGL_EM_VERSION UINT64_C(0x840000F0)
#define TGL_EM_FEATURES UINT64_C(0x840000F1)
#define TGL_EM_CPU_ERRATUM_FEATURES UINT64_C(0x840000F2)
/*
 * Cortex-A520 r0p1: every erratum the pinned TF-A cortex_a520.S applies to r0p1 (2677201 is r0p0 only),
 * plus 4615642 from tools/bootplan_release_fixture.md (absent from that pin: UNKNOWN(-3) is expected there).
 * 3685825 first: it is the CPUACTLR[9] CAS workaround the p29 audit found clear.
 */
#define TGL_CPU_AUDIT_N_ERRATA 7u
#define TGL_CPU_AUDIT_ERRATA {3685825u, 4615642u, 3631357u, 2938996u, 2900952u, 2858100u, 2630792u}

#if TGL_CPU_AUDIT
#include <stdint.h>
extern const uint32_t tgl_cpu_audit_errata[TGL_CPU_AUDIT_N_ERRATA];
/* Absent/0: off; exact 1: audit; exact 2: audit + Errata ABI queries. Malformed, duplicate or unterminated: -1. */
int tgl_cpu_audit_configure(const char *line, unsigned max);
/* Called on cpu0 before starting the A725. 0 refuses the handoff. */
int tgl_cpu_audit_prepare(void);
#endif
