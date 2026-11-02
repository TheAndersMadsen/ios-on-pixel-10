/*
 * fastcore, the target's half. PSCI CPU_ON enters here: x0 = PA of struct tgl_fc, MMU and caches
 * off. It says who it is, waits for cpu0 and continues into the same drop and jump cpu0 used to
 * take. No new register setup for EL1 or EL2: tegu_el_drop_and_jump in start.S does all of it.
 */
#include "tgl_fastcore.h"

	.text
	.balign 8
	.globl tgl_fc_entry
tgl_fc_entry:
	msr	daifset, #0xf
	mov	x19, x0
	msr	spsel, #1
	ldr	x1, [x19, #TGL_FC_O_STACK]
	mov	sp, x1
	adrp	x1, vectors
	add	x1, x1, :lo12:vectors
	mrs	x2, CurrentEL
	cmp	x2, #8
	b.ne	1f
	msr	vbar_el2, x1
	b	2f
1:	msr	vbar_el1, x1
2:	isb
	str	x2, [x19, #TGL_FC_O_EL]
	mrs	x1, midr_el1
	str	x1, [x19, #TGL_FC_O_MIDR]
	mrs	x1, mpidr_el1
	str	x1, [x19, #TGL_FC_O_MPIDR]
	mrs	x1, revidr_el1
	str	x1, [x19, #TGL_FC_O_REVIDR]
	mrs	x1, cntfrq_el0
	str	x1, [x19, #TGL_FC_O_CNTFRQ]
	mrs	x1, isr_el1
	str	x1, [x19, #TGL_FC_O_ISR]
	dsb	sy
	mov	x1, #TGL_FC_ARRIVED
	str	x1, [x19, #TGL_FC_O_ARRIVED]
	dsb	sy
	/* cpu0 is a few stamps away from go, and if it dies the owner's long press ends this. */
3:	ldr	x1, [x19, #TGL_FC_O_GO]
	cmp	x1, #TGL_FC_GO_RUN
	b.eq	5f
	cmp	x1, #TGL_FC_GO_STOP
	b.ne	3b
4:	wfe
	b	4b
5:	ldr	x0, [x19, #TGL_FC_O_ENTRY]
	ldr	x1, [x19, #TGL_FC_O_BA]
	b	tegu_el_drop_and_jump
