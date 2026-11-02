/*
 * fastcore, cpu0's half. See tgl_fastcore.h. Touches no peripheral: PSCI, system registers, and RAM
 * inside the shim. Assumes what speed-probe-r3 has to show first: EXPERIMENT.md, FINDINGS.md.
 *
 * Admitted: the A725s speed-probe-r3 runs, 0x200, 0x300, 0x500. Not 0x700: an X4 alone needs a decision on
 * erratum 4118414, and it has four times cpu5's modelled power. Not 0x400, 0x600: never probed.
 *
 * Order matters and the host test checks it:
 *  - Nothing is decided on the target until it says who it is.
 *  - cpu0 writes its last stamp before go, so the stamp channel has one writer at a time.
 *  - After go, cpu0 writes nothing.
 */
#include <stddef.h>
#include "tgl_fastcore.h"
#include "tgl_stamp.h"

#define PSCI_FEATURES     UINT64_C(0x8400000A)
#define PSCI_CPU_ON_64    UINT64_C(0xC4000003)
#define PSCI_AFFINITY_64  UINT64_C(0xC4000004)
#define AFF_OFF           1
#define MPIDR_AFF_MASK    UINT64_C(0xff00ffffff)
#define EL2               8u      /* CurrentEL's raw value */
#define ISR_A             (1u << 8)
#define ARRIVAL_SECONDS   5u      /* speed-probe-r3's own limit */

_Static_assert(offsetof(struct tgl_fc, entry) == TGL_FC_O_ENTRY, "asm offset");
_Static_assert(offsetof(struct tgl_fc, ba) == TGL_FC_O_BA, "asm offset");
_Static_assert(offsetof(struct tgl_fc, stack) == TGL_FC_O_STACK, "asm offset");
_Static_assert(offsetof(struct tgl_fc, arrived) == TGL_FC_O_ARRIVED, "asm offset");
_Static_assert(offsetof(struct tgl_fc, go) == TGL_FC_O_GO, "asm offset");
_Static_assert(offsetof(struct tgl_fc, mpidr) == TGL_FC_O_MPIDR, "asm offset");
_Static_assert(offsetof(struct tgl_fc, midr) == TGL_FC_O_MIDR, "asm offset");
_Static_assert(offsetof(struct tgl_fc, el) == TGL_FC_O_EL, "asm offset");
_Static_assert(offsetof(struct tgl_fc, cntfrq) == TGL_FC_O_CNTFRQ, "asm offset");
_Static_assert(offsetof(struct tgl_fc, isr) == TGL_FC_O_ISR, "asm offset");
_Static_assert(offsetof(struct tgl_fc, revidr) == TGL_FC_O_REVIDR, "asm offset");

volatile struct tgl_fc tgl_fc;

extern char _head[], _bss_start[], _end[];

#ifdef TGL_FC_HOST
/* tools/test_fastcore.c supplies these. */
int64_t fc_smc(uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3);
uint64_t fc_now(void);
uint64_t fc_freq(void);
uint64_t fc_mpidr(void);
void fc_clean(void);
void fc_sync(void);
void fc_park(void) __attribute__((noreturn));
#else
static int64_t fc_smc(uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3)
{
	register uint64_t x0 __asm__("x0") = a0, x1 __asm__("x1") = a1, x2 __asm__("x2") = a2, x3 __asm__("x3") = a3;
	__asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) ::
	    "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
	return (int64_t)x0;
}

static uint64_t fc_now(void)
{
	uint64_t t;
	__asm__ volatile("isb\n\tmrs %0, cntpct_el0" : "=r"(t));
	return t;
}

static uint64_t fc_freq(void)
{
	uint64_t f;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(f));
	return f;
}

static uint64_t fc_mpidr(void)
{
	uint64_t m;
	__asm__ volatile("mrs %0, mpidr_el1" : "=r"(m));
	return m;
}

/* The target fetches with the MMU and caches off, so what it runs must be at PoC. Everything ABL
 * loaded: code, vectors and the data the stamp path reads. Same operation as speed-probe-r3's. */
static void fc_clean(void)
{
	uint64_t p = (uint64_t)_head & ~UINT64_C(63), e = (uint64_t)_bss_start;
	for (; p < e; p += 64)
		__asm__ volatile("dc cvac, %0" :: "r"(p) : "memory");
	__asm__ volatile("dsb sy\n\tisb");
}

static void fc_sync(void)
{
	__asm__ volatile("dsb sy" ::: "memory");
}

/* WFE, not WFI: a masked interrupt that stays pending wakes WFI every time and doesn't wake WFE. */
static void __attribute__((noreturn)) fc_park(void)
{
	__asm__ volatile("msr daifset, #0xf");
	for (;;)
		__asm__ volatile("wfe");
}
#endif

int tgl_fastcore_parse(const char *c, unsigned max, uint64_t *core)
{
	static const char name[] = "blazer_bootcpu", form[] = "=0x?00";
	unsigned i = 0, core_digit = 0;
	int found = 0;

	*core = 0;
	while (i < max && c[i]) {
		unsigned j = 0;
		if (c[i] == ' ') {
			++i;
			continue;
		}
		while (name[j] && i + j < max && c[i + j] == name[j])
			++j;
		if (!name[j]) {
			unsigned k = 0, v = i + j;
			if (found)
				return -1;
			for (; form[k]; ++k) {
				if (v + k >= max)
					return -1;
				if (form[k] == '?') {
					if (c[v + k] != '2' && c[v + k] != '3' && c[v + k] != '5')
						return -1;
					core_digit = (unsigned)(c[v + k] - '0');
				} else if (c[v + k] != form[k]) {
					return -1;
				}
			}
			if (v + k >= max || (c[v + k] && c[v + k] != ' '))
				return -1;
			found = 1;
		}
		while (i < max && c[i] && c[i] != ' ')
			++i;
	}
	if (i >= max)
		return -1;
	if (found)
		*core = (uint64_t)core_digit << 8;
	return found;
}

const char *tgl_fastcore_handoff(uint64_t core, uint64_t entry_pa, uint64_t ba_pa)
{
	volatile struct tgl_fc *f = &tgl_fc;
	uint64_t own_freq = fc_freq(), limit = (own_freq ? own_freq : 38400000u) * ARRIVAL_SECONDS, t0;
	int64_t rc;

	tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_ENTER, core);
	if ((fc_mpidr() & MPIDR_AFF_MASK) == core) {
		tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_REFUSED, fc_mpidr());
		return "fc-self";
	}
	rc = fc_smc(PSCI_FEATURES, PSCI_CPU_ON_64, 0, 0);
	if ((int32_t)rc < 0) {
		tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_REFUSED, (uint64_t)rc);
		return "fc-feat";
	}
	rc = fc_smc(PSCI_AFFINITY_64, core, 0, 0);
	if ((int32_t)rc != AFF_OFF) {
		tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_REFUSED, (uint64_t)rc);
		return "fc-busy";
	}

	f->entry = entry_pa;
	f->ba = ba_pa;
	f->stack = (uint64_t)_end; /* _sec_stacks, 32 KiB, unused by anything else: shim.ld */
	fc_clean();
	fc_sync();
	t0 = fc_now();
	rc = fc_smc(PSCI_CPU_ON_64, core, (uint64_t)&tgl_fc_entry, (uint64_t)f);
	if ((int32_t)rc != 0) {
		tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_REFUSED, (uint64_t)rc);
		return "fc-cpuon";
	}
	while (f->arrived != TGL_FC_ARRIVED) {
		if (fc_now() - t0 > limit) {
			tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_TIMEOUT, fc_now() - t0);
			return "fc-silent";
		}
	}

	tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_DONE, fc_now() - t0);
	tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_DONE, f->midr);
	tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_DONE, f->mpidr);
	/* Logged, never a refusal: A725 r0p1 erratum 3114823 is fixed only where bit 0 is set (cpudeep). Parent decides. */
	tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_DONE, f->revidr);
	tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_DONE, f->el << 32 | (f->isr & 0xffffffffu));
	if ((f->mpidr & MPIDR_AFF_MASK) != core || f->el != EL2 || f->cntfrq != own_freq || (f->isr & ISR_A)) {
		f->go = TGL_FC_GO_STOP;
		fc_sync();
		tgl_stamp(TGL_FC_STAGE, TGL_STAMP_F_REFUSED, f->cntfrq);
		return "fc-wrong";
	}

	f->go = TGL_FC_GO_RUN;
	fc_sync();
	fc_park();
}
