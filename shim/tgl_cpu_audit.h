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

#if TGL_CPU_AUDIT
#include <stdint.h>
/* Absent/0: off; exact 1: audit. Malformed, duplicate or unterminated: -1. */
int tgl_cpu_audit_configure(const char *line, unsigned max);
/* Called on cpu0 before starting the A725. 0 refuses the handoff. */
int tgl_cpu_audit_prepare(void);
#endif
