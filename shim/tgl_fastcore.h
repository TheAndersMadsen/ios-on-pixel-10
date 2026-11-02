#pragma once
/*
 * fastcore: the shim's last jump runs on one fast core, cpu0 parks in the shim, XNU sees one CPU.
 * Off unless the shim is built with -DTGL_FASTCORE=1 and the payload's command line carries
 * blazer_bootcpu=, an admitted core: tgl_fastcore.c. Design and evidence: research/ios26-fastcore-r1/FINDINGS.md.
 */

#define TGL_FC_STAGE    0x00e6u  /* stamp stage */
#define TGL_FC_ARRIVED  1
#define TGL_FC_GO_RUN   1
#define TGL_FC_GO_STOP  2

/* struct tgl_fc offsets, for the assembly. Checked at compile time in tgl_fastcore.c. */
#define TGL_FC_O_ENTRY   0
#define TGL_FC_O_BA      8
#define TGL_FC_O_STACK   16
#define TGL_FC_O_ARRIVED 24
#define TGL_FC_O_GO      32
#define TGL_FC_O_MPIDR   40
#define TGL_FC_O_MIDR    48
#define TGL_FC_O_EL      56
#define TGL_FC_O_CNTFRQ  64
#define TGL_FC_O_ISR     72
#define TGL_FC_O_REVIDR  80

#ifndef __ASSEMBLER__
#include <stdint.h>

/* Both cores use this with the MMU off, so every access is an aligned 64-bit Device access. */
struct tgl_fc {
	uint64_t entry, ba, stack;      /* cpu0 writes before CPU_ON */
	uint64_t arrived, go;           /* one writer each: the target, then cpu0 */
	uint64_t mpidr, midr, el, cntfrq, isr, revidr;  /* target writes before arrived */
};

/* 0: no token. 1: *core is an admitted target. -1: malformed, repeated, or a core not admitted. */
int tgl_fastcore_parse(const char *cmdline, unsigned max, uint64_t *core);

/* Last step on cpu0. Doesn't return if the target took over: this core parks. A return is a
 * refusal: the boot hasn't left cpu0, the target is off or stopped, the caller resets. */
const char *tgl_fastcore_handoff(uint64_t core, uint64_t entry_pa, uint64_t ba_pa);

/* Assembly: PSCI CPU_ON target. x0 = PA of struct tgl_fc. */
void tgl_fc_entry(uint64_t context);
#endif
