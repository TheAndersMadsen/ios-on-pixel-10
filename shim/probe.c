/* Fault-gated probe machinery — see probe.h. */
#include <stdint.h>
#include "probe.h"

volatile int probe_hit;
volatile uint64_t probe_esr, probe_far, probe_pa;
volatile unsigned probe_wr;
static volatile int probe_armed;

/* v3.9b (U1): ABL releases the shim at EL2 (device-measured cpu-state
 * 0x80d01998 = EL2, MMU off; start.S installs VBAR_EL2 for exactly this
 * case). A fault taken at EL2 is recorded in ESR_EL2/ELR_EL2 — reading
 * ESR_EL1 there returns STALE EL1 registers, so the pre-v3.9b recover
 * never matched EC 0x25 on silicon and every probe fault (WDT/DPU/USB/
 * UFSHCI) fell through to the panic screen. QEMU never saw this because
 * its guest probes run at EL1. Read/advance the ELR of the level the
 * fault was actually taken at. */
static void probe_elr_read(uint64_t *elr)
{
	uint64_t el;
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
	if (el == 0x8)
		__asm__ volatile("mrs %0, elr_el2" : "=r"(*elr));
	else
		__asm__ volatile("mrs %0, elr_el1" : "=r"(*elr));
}

static void probe_elr_advance(uint64_t elr)
{
	uint64_t el;
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
	if (el == 0x8)
		__asm__ volatile("msr elr_el2, %0" :: "r"(elr + 4));
	else
		__asm__ volatile("msr elr_el1, %0" :: "r"(elr + 4));
}

/* Called from exc_handler (shim.c) BEFORE the panic path. Returns 1 when the
 * fault belonged to an armed probe and execution was resumed past it. */
int probe_recover(uint64_t esr, uint64_t far_el1)
{
	if (!probe_armed || ((esr >> 26) & 0x3f) != 0x25) /* data abort, current EL */
		return 0;
	probe_esr = esr;
	probe_far = far_el1;
	probe_hit = 1;
	probe_armed = 0;
	uint64_t elr;
	probe_elr_read(&elr);
	probe_elr_advance(elr); /* skip the access */
	return 1;
}

static int probe_begin(uintptr_t pa, unsigned wr)
{
	probe_hit = 0;
	probe_wr = wr;
	probe_pa = pa;
	probe_armed = 1;
	__asm__ volatile("dsb sy" ::: "memory");
	return 1;
}

static int probe_end(void)
{
	__asm__ volatile("dsb sy" ::: "memory");
	probe_armed = 0;
	return !probe_hit;
}

int probe_read32(uintptr_t pa, uint32_t *out)
{
	uint32_t v;
	probe_begin(pa, 0);
	v = *(volatile uint32_t *)pa;
	*out = v;
	return probe_end();
}

int probe_read64(uintptr_t pa, uint64_t *out)
{
	uint64_t v;
	probe_begin(pa, 0);
	v = *(volatile uint64_t *)pa;
	*out = v;
	return probe_end();
}

int probe_write32(uintptr_t pa, uint32_t v)
{
	probe_begin(pa, 1);
	*(volatile uint32_t *)pa = v;
	return probe_end();
}

void probe_dpu(struct tgl_dpu_state *st)
{
	uint32_t v;
	uintptr_t b = (uintptr_t)TGL_DPU_BASE;
	st->probed = 0; st->id_ok = 0; st->enabled = 0; st->candidate = 0;
	st->esr = 0; st->far = 0;
	if (!probe_read32(b + TGL_DPU_CHIP_ID, &v)) {
		st->esr = probe_esr; st->far = probe_far;
		return; /* DPU inaccessible (power/protection): state unknown */
	}
	st->probed = 1;
	st->chip_id = v;
	st->id_ok = 1;
	if (!probe_read32(b + TGL_DPU_CONFIG, &v)) goto fault;
	st->config = v;
	st->enabled = v & 1U;
	if (!probe_read32(b + TGL_DPU_ADDR_LO, &v)) goto fault;
	st->addr_lo = v;
	if (!probe_read32(b + TGL_DPU_ADDR_HI, &v)) goto fault;
	st->addr_hi = v;
	if (!probe_read32(b + TGL_DPU_STRIDE, &v)) goto fault;
	st->stride = v;
	if (!probe_read32(b + TGL_DPU_SIZE, &v)) goto fault;
	st->size = v;
	/* Output0 CURRENT_COORD twice, ~100 ms apart: if the packed x/y moves,
	 * scanout is live (60 Hz frame = 16.7 ms). */
	if (!probe_read32(b + TGL_DPU_OUT0_COORD, &v)) goto fault;
	st->coord0_a = v;
	for (volatile uint64_t i = 0; i < UINT64_C(100000000); ++i) ;
	if (!probe_read32(b + TGL_DPU_OUT0_COORD, &v)) goto fault;
	st->coord0_b = v;
	if (st->enabled && st->addr_lo && !st->addr_hi && !(st->addr_lo & 3U))
		st->candidate = st->addr_lo;
	return;
fault:
	st->esr = probe_esr; st->far = probe_far;
}
