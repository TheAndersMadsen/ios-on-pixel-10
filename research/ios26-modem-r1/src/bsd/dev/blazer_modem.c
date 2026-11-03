/* SPDX-License-Identifier: APSL-2.0
 * The S5400 modem ladder's kernel side: maps the windows, gives blazer_modem_core.c its ops, runs it once on a thread.
 * Off unless asked:
 *   blazer_modem=N            N = 1 read (rung 0's question, plus the PCIe0 pads and four LPB GETs), 2 ctrl, 3 phy, 4 link
 *   hk_dbg bits 24..27 = N    the same without a new token (the int line is 1018 of 1023 bytes); bit 28 = hold
 *   blazer_modem_hold=1       on success leave the CP in its boot ROM with the link up
 *   blazer_modem_force=1      go on though the controller reads as started or the CP pads as not off (never by default)
 * Console prefix "blazer-modem: ". Design and the stock sources: research/ios26-modem-r1/MODEM.md. */
#include <kern/clock.h>
#include <kern/thread.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include <stdarg.h>
#include "blazer_cpmq_xnu.h"
#include "blazer_modem_core.h"

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern kern_return_t thread_terminate(thread_t thread);
extern uint32_t hk_dbg_bits(void);     /* osfmk/kern/hk_dbg.h: not on bsd/'s include path */

#define HK_DBG_MODEM_STAGE(b)   (((b) >> 24) & 0xfu)
#define HK_DBG_MODEM_HOLD       0x10000000u

/* laguna_pcie_phy_fw.bin's values. pcie-google.c requests this one file for every controller; same data as Wi-Fi's copy */
static const uint16_t modem_phy_table[] = {
#include "blazer_wifi_phyfw.inc"
};
_Static_assert(sizeof(modem_phy_table) / sizeof(modem_phy_table[0]) == 20480, "PHY table size");

/* Every page the core may name, nothing else. None of the CP's reserved memory is mapped */
static struct {
	uint64_t pa;
	uint32_t size;
	vm_offset_t va;
} windows[] = {
	{ 0x05250000ULL, 0x1000, 0 }, { 0x05272000ULL, 0x1000, 0 },     /* CPM mailbox magic, LPCM/LPB page */
	{ 0x3c592000ULL, 0x6000, 0 },                                   /* hsios pads 2..7: the CP's six AP2CP lines */
	{ 0x3a20e000ULL, 0x1000, 0 },                                   /* lsioe pad 0x0e: AP2CP_PARTIAL_RST_N */
	{ 0x3be26000ULL, 0x1000, 0 },                                   /* lsios pad 0x26: AP2CP_WAKEUP (read) */
	{ 0x0528b000ULL, 0x1000, 0 }, { 0x05299000ULL, 0x2000, 0 },     /* cpm pads 0x0b, 0x19..0x1a: CP2AP lines (read) */
	{ 0x0c580000ULL, 0x3000, 0 },                                   /* hsion pads 0..2: PCIe0 CLKREQ, PERST (pad 1 is NFC's: never named) */
	{ 0x0c500000ULL, 0x1000, 0 }, { 0x0c520000ULL, 0x1000, 0 }, { 0x0c550000ULL, 0xa000, 0 },       /* sii, top, phy_sram */
	{ 0x0c800000ULL, 0x1000, 0 }, { 0x0cb00000ULL, 0x1000, 0 }, { 0x40000000ULL, 0x1000, 0 },       /* dbi, atu, first page of config */
};

static uint32_t boot_delay_s = 30;
static struct m0_cfg boot_cfg;
static struct m0 modem;
volatile uint32_t blazer_modem_phase;   /* 0 off, 1 waiting, 2 running, 3 ended */

static volatile void *
at(uint64_t pa)
{
	for (unsigned i = 0; i < sizeof(windows) / sizeof(windows[0]); i++) {
		if (windows[i].va != 0 && pa >= windows[i].pa && pa - windows[i].pa < windows[i].size) {
			return (volatile void *)(windows[i].va + (pa - windows[i].pa));
		}
	}
	return NULL;
}

static int
k_read32(__unused void *ctx, uint64_t pa, uint32_t *value)
{
	volatile uint32_t *p = (volatile uint32_t *)at(pa);

	if (p == NULL) {
		return -1;
	}
	*value = *p;
	return 0;
}

static int
k_write32(__unused void *ctx, uint64_t pa, uint32_t value)
{
	volatile uint32_t *p = (volatile uint32_t *)at(pa);

	if (p == NULL) {
		return -1;
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	*p = value;
	__asm__ volatile ("dsb sy" ::: "memory");
	return 0;
}

static int
k_write16(__unused void *ctx, uint64_t pa, uint16_t value)
{
	volatile uint16_t *p = (volatile uint16_t *)at(pa);

	if (p == NULL || pa < 0x0c550000ULL || pa >= 0x0c55a000ULL) {
		return -1;      /* PHY SRAM only */
	}
	*p = value;
	return 0;
}

static void k_barrier(__unused void *ctx) { __asm__ volatile ("dsb sy" ::: "memory"); }
static void k_cpm_enter(__unused void *ctx) { blazer_cpmq_enter(); }
static void k_cpm_exit(__unused void *ctx) { blazer_cpmq_exit(); }
static void k_delay_us(__unused void *ctx, uint32_t us) { delay_for_interval(us, NSEC_PER_USEC); }

static uint64_t
k_now_us(__unused void *ctx)
{
	uint64_t ns;

	absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
	return ns / 1000;
}

static void
k_log(__unused void *ctx, const char *format, ...)
{
	va_list args;

	printf("blazer-modem: ");
	va_start(args, format);
	vprintf(format, args);
	va_end(args);
}

static void
modem_thread(__unused void *arg, __unused wait_result_t wr)
{
	static const struct m0_ops ops = { .read32 = k_read32, .write32 = k_write32, .write16 = k_write16, .barrier = k_barrier, .delay_us = k_delay_us,
		                           .now_us = k_now_us, .log = k_log, .cpm_enter = k_cpm_enter, .cpm_exit = k_cpm_exit };
	int rc;

	printf("blazer-modem: stage %u (%s), hold %d, force %d, starts in %u s\n", boot_cfg.stage,
	    boot_cfg.stage == M0_STAGE_READ ? "read" : boot_cfg.stage == M0_STAGE_CTRL ? "ctrl" : boot_cfg.stage == M0_STAGE_PHY ? "phy" : "link",
	    boot_cfg.hold, boot_cfg.force, boot_delay_s);
	delay_for_interval(boot_delay_s * 1000, NSEC_PER_MSEC);
	blazer_modem_phase = 2;
	for (unsigned i = 0; i < sizeof(windows) / sizeof(windows[0]); i++) {
		windows[i].va = ml_io_map((vm_offset_t)windows[i].pa, windows[i].size);
		if (windows[i].va == 0) {
			printf("blazer-modem: cannot map 0x%llx\n", windows[i].pa);
			blazer_modem_phase = 3;
			thread_terminate(current_thread());
			return;
		}
	}
	boot_cfg.phy = modem_phy_table;
	boot_cfg.phy_words = sizeof(modem_phy_table) / sizeof(modem_phy_table[0]);
	m0_init(&modem, &ops, &boot_cfg);
	rc = m0_run(&modem);
	blazer_modem_phase = 3;
	if (rc == 0 && modem.ep_id != 0) {
		printf("blazer-modem: verdict: PASS stage %u, at %s: PCIe0 link gen %u x%u, endpoint %04x:%04x%s, frames %u\n", boot_cfg.stage, m0_at_name(modem.at),
		    modem.lnksta & 0xfu, (modem.lnksta >> 4) & 0x3fu, modem.ep_id & 0xffffu, modem.ep_id >> 16, boot_cfg.hold ? ", held" : ", CP off again", modem.frames);
	} else if (rc == 0) {
		printf("blazer-modem: verdict: PASS stage %u, at %s, CP as found %s, frames %u\n", boot_cfg.stage, m0_at_name(modem.at), modem.cp_off_found ? "off" : "not off", modem.frames);
	} else {
		printf("blazer-modem: verdict: STOP stage %u, at %s: %s, detail 0x%x, frames %u\n", boot_cfg.stage, m0_at_name(modem.at), m0_stop_name(modem.stop), modem.stop_detail,
		    modem.frames);
	}
	thread_terminate(current_thread());
}

/* For an HKOBS provider ("modem:"): one line of state, no lock (counts and flags only). Not hooked into hk_obs.c by this change */
void blazer_modem_obs(char *buf, size_t size);
void
blazer_modem_obs(char *buf, size_t size)
{
	if (blazer_modem_phase == 0) {
		snprintf(buf, size, "off (no blazer_modem / hk_dbg stage)");
		return;
	}
	snprintf(buf, size, "phase %s, stage %u, at %s, stop %s 0x%x, cp %s, link %s gen %u, id %04x:%04x, frames %u",
	    blazer_modem_phase == 1 ? "waiting" : blazer_modem_phase == 2 ? "running" : "ended", boot_cfg.stage, m0_at_name(modem.at), m0_stop_name(modem.stop),
	    modem.stop_detail, modem.cp_on ? "on" : "off", modem.link_up ? "up" : "down", modem.lnksta & 0xfu, modem.ep_id & 0xffffu, modem.ep_id >> 16, modem.frames);
}

void
blazer_modem_init(void)
{
	unsigned stage = 0, hold = 0, force = 0;
	uint32_t dbg = hk_dbg_bits();
	thread_t t;

	if (!PE_parse_boot_argn("blazer_modem", &stage, sizeof(stage))) {
		stage = HK_DBG_MODEM_STAGE(dbg);
	}
	if (stage == 0) {
		return;
	}
	(void)PE_parse_boot_argn("blazer_modem_hold", &hold, sizeof(hold));
	(void)PE_parse_boot_argn("blazer_modem_force", &force, sizeof(force));
	boot_cfg.stage = stage > M0_STAGE_MAX ? M0_STAGE_MAX : stage;
	boot_cfg.hold = hold == 1 || (dbg & HK_DBG_MODEM_HOLD) != 0;
	boot_cfg.force = force == 1;
	blazer_modem_phase = 1;
	if (kernel_thread_start(modem_thread, NULL, &t) == KERN_SUCCESS) {
		thread_deallocate(t);
	}
}
