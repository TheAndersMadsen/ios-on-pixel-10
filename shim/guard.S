/* tgl_guard — section-level fault guard (see guard.h; that header holds
 * the contract and the C-side declarations — deliberately NOT included
 * here: this file goes through the assembler, and C declarations in the
 * preprocessed output are fatal).
 *
 * No libc, no absolute relocations (ADR-form addressing only, matching the
 * shim image contract checked by build.sh).
 *
 * Register-file image layout (tgl_guard_save, 264 B):
 *   +0   x0  +8   x1  ... +232 x29 +240 x30 +248 sp   (8 B each, 33 slots)
 */

	.data
	.balign 8
	.globl tgl_guard_armed
	.globl tgl_guard_esr
	.globl tgl_guard_far
	.globl tgl_guard_save
tgl_guard_armed:
	.word	0
	.balign 8
tgl_guard_esr:
	.quad	0
	.balign 8
tgl_guard_far:
	.quad	0
tgl_guard_save:
	.space	264

	.text
	.balign 8

/*
 * void tgl_guard_arm(void)
 * x30 on entry = the wrapper's continuation after this call — exactly the
 * resume point. Spills x0..x30 + sp; clobbers only x8/x9 (dead across the
 * risky call by AAPCS anyway, and restored by the unwind regardless).
 */
	.globl tgl_guard_arm
tgl_guard_arm:
	adrp	x8, tgl_guard_save
	add	x8, x8, :lo12:tgl_guard_save
	mov	x9, sp
	str	x9, [x8, #248]
	stp	x0, x1, [x8, #0]
	stp	x2, x3, [x8, #16]
	stp	x4, x5, [x8, #32]
	stp	x6, x7, [x8, #48]
	str	x8, [x8, #64]			/* x8 (holds the table base) */
	stp	x9, x10, [x8, #72]
	stp	x11, x12, [x8, #88]
	stp	x13, x14, [x8, #104]
	stp	x15, x16, [x8, #120]
	stp	x17, x18, [x8, #136]
	stp	x19, x20, [x8, #152]
	stp	x21, x22, [x8, #168]
	stp	x23, x24, [x8, #184]
	stp	x25, x26, [x8, #200]
	stp	x27, x28, [x8, #216]
	stp	x29, x30, [x8, #232]
	dsb	sy
	ret

/*
 * void tgl_guard_unwind(void) — noreturn, called from exc_handler with
 * tgl_guard_armed != 0 and tgl_guard_esr/far already recorded.
 * Restores the spilled register file, sets ELR (current EL) = saved x30,
 * eret. armed is cleared FIRST so a fault after resume is never
 * misattributed to this guard.
 */
	.globl tgl_guard_unwind
tgl_guard_unwind:
	adrp	x8, tgl_guard_armed
	add	x8, x8, :lo12:tgl_guard_armed
	str	wzr, [x8]			/* armed = 0 */
	adrp	x8, tgl_guard_save
	add	x8, x8, :lo12:tgl_guard_save
	ldr	x9, [x8, #248]
	mov	sp, x9
	ldp	x0, x1, [x8, #0]
	ldp	x2, x3, [x8, #16]
	ldp	x4, x5, [x8, #32]
	ldp	x6, x7, [x8, #48]
	ldp	x9, x10, [x8, #72]
	ldp	x11, x12, [x8, #88]
	ldp	x13, x14, [x8, #104]
	ldp	x15, x16, [x8, #120]
	ldp	x17, x18, [x8, #136]
	ldp	x19, x20, [x8, #152]
	ldp	x21, x22, [x8, #168]
	ldp	x23, x24, [x8, #184]
	ldp	x25, x26, [x8, #200]
	ldp	x27, x28, [x8, #216]
	ldp	x29, x30, [x8, #232]
	/* x30 now = the saved continuation; x8 still = table base. */
	mrs	x9, CurrentEL
	cmp	x9, #0x8			/* 8 = EL2 */
	b.eq	1f
	msr	elr_el1, x30
	b	2f
1:	msr	elr_el2, x30
2:	ldr	x9, [x8, #72]			/* restore x9 */
	ldr	x8, [x8, #64]			/* restore x8 last */
	dsb	sy
	isb
	eret
