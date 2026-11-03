/*
 * TGL_FAST_START=1, F4: leave the cached copy window. Registers only, no
 * stack, no stores: every cached line of both regions is cleaned and
 * invalidated to PoC before SCTLR_EL2 goes back to its entry value (MMU and
 * caches off), then both regions are invalidated once more so no line a
 * speculative fill brought in between survives to XNU's first cacheable
 * access. Same maintenance as chooser.c chain_jump_mmu_off, but it returns.
 *
 *   x0 = SCTLR_EL2 to restore, x1/x2 = region 0 [lo, hi), x3/x4 = region 1 [lo, hi)
 */
	.text
	.balign 8
	.globl tgl_fast_mmu_off_asm
	.type tgl_fast_mmu_off_asm, %function
tgl_fast_mmu_off_asm:
	mrs	x9, ctr_el0
	ubfx	x9, x9, #16, #4		/* DminLine, log2 words */
	mov	x10, #4
	lsl	x10, x10, x9		/* smallest D-cache line, bytes */
	sub	x11, x10, #1
	bic	x5, x1, x11
1:	cmp	x5, x2
	b.hs	2f
	dc	civac, x5
	add	x5, x5, x10
	b	1b
2:	bic	x5, x3, x11
3:	cmp	x5, x4
	b.hs	4f
	dc	civac, x5
	add	x5, x5, x10
	b	3b
4:	dsb	sy
	msr	sctlr_el2, x0
	isb
	ic	iallu
	tlbi	alle2
	dsb	sy
	isb
	bic	x5, x1, x11
5:	cmp	x5, x2
	b.hs	6f
	dc	ivac, x5
	add	x5, x5, x10
	b	5b
6:	bic	x5, x3, x11
7:	cmp	x5, x4
	b.hs	8f
	dc	ivac, x5
	add	x5, x5, x10
	b	7b
8:	dsb	sy
	isb
	ret
	.size tgl_fast_mmu_off_asm, . - tgl_fast_mmu_off_asm
