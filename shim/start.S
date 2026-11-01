/*
 * tegu boot shim entry: arm64 Linux Image header so Qualcomm ABL treats
 * us like a kernel. ABL enters at EL1, MMU/D-cache off, x0 = DTB pointer.
 */
	.section .text.head, "ax"
	.globl _head
_head:
	b	_start			/* code0 */
	.long	0			/* code1 */
	.quad	0			/* text_offset */
	.quad	_end			/* image_size (linked at 0) */
	.quad	0xa			/* flags: LE, 4K pages, place anywhere */
	.quad	0			/* res2 */
	.quad	0			/* res3 */
	.quad	0			/* res4 */
	.ascii	"ARM\x64"		/* magic */
	.long	0			/* res5 (PE offset) */

	.text
	.globl _start
_start:
	msr	daifset, #0xf
	/* VBAR FIRST: any fault below lands in our handler instead of
	 * vectoring through vbar=0 into a physical 0x200 exception storm
	 * (observed on QEMU when the register capture below took an
	 * alignment fault before the old vbar setup). */
	adr	x1, vectors
	msr	vbar_el1, x1
	/* Device evidence (2026-10-27 v2b dump, cpu-state arg 0x80d01998):
	 * ABL releases us at EL2, where exceptions vector through VBAR_EL2 —
	 * our EL1 vectors would never run, so probe recovery and the
	 * paint+reset failure path silently depend on this. Install the same
	 * vector table for the EL2 case (msr vbar_el2 traps from EL1). */
	mrs	x5, CurrentEL
	cmp	x5, #0x8		/* CurrentEL: 4=EL1, 8=EL2, 12=EL3 */
	b.ne	1f
	msr	vbar_el2, x1
1:	isb
	mov	x19, x0			/* DTB pointer from ABL */
	adr	x4, boot_regs		/* preserve raw x1 before choosing scratch regs */
	stp	x0, x1, [x4]
	stp	x2, x3, [x4, #16]
	str	x5, [x4, #32]		/* [4] = entry CurrentEL (B1 entry contract) */
	msr	spsel, #1
	adrp	x1, _stack_top
	add	x1, x1, :lo12:_stack_top
	mov	sp, x1
	isb
	/* zero .bss */
	adrp	x1, _bss_start
	add	x1, x1, :lo12:_bss_start
	adrp	x2, _bss_end
	add	x2, x2, :lo12:_bss_end
1:	cmp	x1, x2
	b.hs	2f
	str	xzr, [x1], #8
	b	1b
2:	/* Earliest safe evidence point: stack+bss live, physical addressing,
	 * MMU still off. Initializes the TSHIMST1 channel (pmsg+0x30000) and
	 * stamps ENTRY; everything after this leaves a trail in DRAM. */
	bl	tgl_stamp_boot_entry
	mov	x0, x19
	bl	shim_main
3:	wfe
	b	3b

/* #4: raw ABL entry registers, .data so the .bss zeroing keeps them. */
	.data
	.balign 16
	.globl boot_regs
boot_regs:
	.quad	0, 0, 0, 0, 0		/* [4] = entry CurrentEL (B1 entry contract) */
	.text

/* PSCI CPU_ON target. x0 = context id = cpu index (1..7). */
	.globl secondary_entry
secondary_entry:
	msr	daifset, #0xf
	msr	spsel, #1
	adrp	x1, _sec_stacks
	add	x1, x1, :lo12:_sec_stacks
	add	x1, x1, x0, lsl #12
	add	x1, x1, #0x1000
	mov	sp, x1
	adr	x1, vectors
	msr	vbar_el1, x1
	isb
	bl	secondary_main
4:	wfe
	b	4b

/*
 * B1 entry contract (XNU-ENTRY-CONTRACT.md §1.2): the tegu-proven
 * EL2->EL1 drop (research/tegu-ios/shim/tegu/start.S:68-171, the handoff
 * that physically reached XNU PID1), executed at the FINAL jump so the
 * whole diagnostic bring-up composes with v3.5+ at EL2. XNU's __start is
 * EL1-only (VBAR_EL1/TTBR1_EL1/SCTLR_EL1, no CurrentEL check on the boot
 * path) — this eret is what makes loader.c's EL1 gate pass honestly.
 *
 * x0 = XNU entry PA, x1 = boot_args PA. Never returns.
 */
	.globl tegu_el_drop_and_jump
tegu_el_drop_and_jump:
	mov	x21, x0			/* XNU entry PA (survives eret) */
	mov	x22, x1			/* boot_args PA */
	mov	x20, sp			/* current stack for the EL1 side */
	mrs	x5, CurrentEL
	cmp	x5, #0x8		/* 4=EL1, 8=EL2, 12=EL3 */
	b.eq	20f
	cmp	x5, #0x4
	b.eq	el1_continuation	/* already EL1: no EL2 register writes */
	wfe
	b	tegu_el_drop_and_jump
20:	/* ---- tegu start.S:73-167, register-for-register ---- */
	adr	x1, vectors
	msr	vbar_el2, x1
	mov	x1, #(1 << 31)		/* HCR_EL2.RW: AArch64 EL1, no stage 2 */
	msr	hcr_el2, x1
	mov	x1, #3			/* EL1 physical counter/timer access */
	msr	cnthctl_el2, x1
	msr	cntvoff_el2, xzr
	mov	x1, #0x33ff		/* no FP/SIMD/trace traps (tegu :83-84) */
	msr	cptr_el2, x1
	msr	hstr_el2, xzr
	msr	vttbr_el2, xzr
	mrs	x1, midr_el1
	msr	vpidr_el2, x1
	mrs	x1, mpidr_el1
	msr	vmpidr_el2, x1
	mrs	x1, id_aa64pfr0_el1
	ubfx	x1, x1, #24, #4		/* GICv3? */
	cbz	x1, 23f
	mrs	x1, S3_4_C12_C9_5	/* ICC_SRE_EL2 */
	orr	x1, x1, #1		/* SRE */
	orr	x1, x1, #8		/* Enable */
	msr	S3_4_C12_C9_5, x1
	isb
	mrs	x1, S3_4_C12_C9_5
	tbz	x1, #0, 23f
	msr	S3_4_C12_C11_0, xzr	/* ICH_HCR_EL2 */
23:	/* FEAT_FGT, feature-guarded (tegu :103-130) */
	mrs	x1, id_aa64mmfr0_el1
	ubfx	x1, x1, #56, #4
	cbz	x1, 26f
	mov	x2, #0
	mrs	x1, id_aa64dfr0_el1
	ubfx	x1, x1, #32, #4		/* PMSVer */
	cmp	x1, #3
	b.lt	24f
	mov	x2, #(1 << 62)		/* nPMSNEVFR_EL1 */
24:	msr	S3_4_C3_C1_4, x2	/* HDFGRTR_EL2 */
	msr	S3_4_C3_C1_5, x2	/* HDFGWTR_EL2 */
	mov	x2, #0
	mrs	x1, S3_0_C0_C4_1	/* ID_AA64PFR1_EL1 */
	ubfx	x1, x1, #24, #4		/* SME */
	cbz	x1, 25f
	mov	x2, #(3 << 54)		/* nSMPRI_EL1 | nTPIDR2_EL0 */
25:	msr	S3_4_C1_C1_4, x2	/* HFGRTR_EL2 */
	msr	S3_4_C1_C1_5, x2	/* HFGWTR_EL2 */
	msr	S3_4_C1_C1_6, xzr	/* HFGITR_EL2 */
	mrs	x1, id_aa64pfr0_el1
	ubfx	x1, x1, #44, #4		/* AMU */
	cbz	x1, 26f
	msr	S3_4_C3_C1_6, xzr	/* HAFGRTR_EL2 */
26:	/* MDCR_EL2: Linux v6.1 __init_el2_debug (tegu :132-158) */
	mov	x2, #0
	mrs	x1, id_aa64dfr0_el1
	sbfx	x3, x1, #8, #4		/* PMUVer, 0xf = absent */
	cmp	x3, #1
	b.lt	27f
	mrs	x3, pmcr_el0
	ubfx	x2, x3, #11, #5		/* HPMN = PMCR.N */
27:	ubfx	x3, x1, #32, #4		/* PMSVer */
	cbz	x3, 29f
	mrs	x3, S3_0_C9_C10_7	/* PMBIDR_EL1 */
	tbnz	x3, #4, 28f
	mov	x3, #0x50		/* PMSCR_EL2.PCT | PA */
	msr	S3_4_C9_C9_0, x3
28:	orr	x2, x2, #(3 << 12)	/* MDCR_EL2.E2PB */
29:	ubfx	x3, x1, #44, #4		/* TraceBuffer */
	cbz	x3, 30f
	mrs	x3, S3_0_C9_C11_7	/* TRBIDR_EL1 */
	tbnz	x3, #4, 30f
	orr	x2, x2, #(3 << 24)	/* MDCR_EL2.E2TB */
30:	msr	mdcr_el2, x2
	mov	x1, #0x0800
	movk	x1, #0x30d0, lsl #16	/* SCTLR_EL1 RES1; M/C/I off */
	msr	sctlr_el1, x1
	mov	x1, #0x3c5		/* masked DAIF, EL1h */
	msr	spsr_el2, x1
	adr	x1, el1_continuation
	msr	elr_el2, x1
	isb
	eret

el1_continuation:
	msr	spsel, #1
	mov	sp, x20			/* keep the bring-up stack across the drop */
	adr	x1, vectors
	msr	vbar_el1, x1
	isb
	bl	tgl_stamp_el_drop_done	/* EL_DROP DONE, arg = new EL << 28 */
	bl	tgl_stamp_reason_handoff /* the final "jumping" stamp */
	dsb	sy
	ic	iallu
	dsb	sy
	isb
	mov	x0, x22			/* x0 = boot_args PA */
	br	x21			/* branch to XNU entry PA */


/*
 * Exception vectors. Each slot stashes x29/x30, loads its slot number
 * and jumps to the common path, which saves x0-x28 and calls
 * exc_handler(slot, regs). IRQs return; everything else ends in the
 * on-screen panic.
 */
.macro vent slot
	.balign	0x80
	stp	x29, x30, [sp, #-16]!
	mov	x29, #\slot
	b	exc_common
.endm

	.balign	0x800
	.globl vectors
vectors:
	vent 0
	vent 1
	vent 2
	vent 3
	vent 4
	vent 5
	vent 6
	vent 7
	vent 8
	vent 9
	vent 10
	vent 11
	vent 12
	vent 13
	vent 14
	vent 15

exc_common:
	sub	sp, sp, #(30 * 8)
	stp	x0, x1, [sp, #0]
	stp	x2, x3, [sp, #16]
	stp	x4, x5, [sp, #32]
	stp	x6, x7, [sp, #48]
	stp	x8, x9, [sp, #64]
	stp	x10, x11, [sp, #80]
	stp	x12, x13, [sp, #96]
	stp	x14, x15, [sp, #112]
	stp	x16, x17, [sp, #128]
	stp	x18, x19, [sp, #144]
	stp	x20, x21, [sp, #160]
	stp	x22, x23, [sp, #176]
	stp	x24, x25, [sp, #192]
	stp	x26, x27, [sp, #208]
	str	x28, [sp, #224]
	mov	x0, x29
	mov	x1, sp
	bl	exc_handler
	ldp	x0, x1, [sp, #0]
	ldp	x2, x3, [sp, #16]
	ldp	x4, x5, [sp, #32]
	ldp	x6, x7, [sp, #48]
	ldp	x8, x9, [sp, #64]
	ldp	x10, x11, [sp, #80]
	ldp	x12, x13, [sp, #96]
	ldp	x14, x15, [sp, #112]
	ldp	x16, x17, [sp, #128]
	ldp	x18, x19, [sp, #144]
	ldp	x20, x21, [sp, #160]
	ldp	x22, x23, [sp, #176]
	ldp	x24, x25, [sp, #192]
	ldp	x26, x27, [sp, #208]
	ldr	x28, [sp, #224]
	add	sp, sp, #(30 * 8)
	ldp	x29, x30, [sp], #16
	eret
