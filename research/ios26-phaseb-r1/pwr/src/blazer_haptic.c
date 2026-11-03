#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * XNU's part: boot args, mappings, one thread that runs once. Off unless blazer_haptic=N.
 * Polled CPM frames take blazer_cpmq_enter/exit, the lock touch and thermal hold. The start delay is only to keep clear of bring-up: blazer_haptic_delay=, default 45 s, minimum 30. */
#ifndef BLAZER_HAPTIC_SERVICE
#define BLAZER_HAPTIC_SERVICE 0
#endif
#include <kern/locks.h>
#include <sys/errno.h>
#include "blazer_haptic_service.h"
#include <kern/clock.h>
#include <kern/sched_prim.h>
#include <kern/thread.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include "blazer_haptic_hw.h"
#include "blazer_cpmq_xnu.h"
#include "blazer_haptic_tap.h"
#include <os/atomic_private.h>

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern kern_return_t thread_terminate(thread_t thread);

static struct {
	uint64_t pa;
	vm_offset_t va;
} windows[] = {
	{ 0x05250000ULL, 0 }, { 0x05272000ULL, 0 }, { 0x3a330000ULL, 0 }, { 0x3a331000ULL, 0 }, { 0x3a210000ULL, 0 }, { 0x3a211000ULL, 0 }, { 0x3a21f000ULL, 0 },
};
static struct hh haptic;
#if BLAZER_HAPTIC_SERVICE
static LCK_GRP_DECLARE(haptic_group, "blazer-haptic");
static LCK_MTX_DECLARE(haptic_lock, &haptic_group);
static unsigned service_on;
static bool service_ready;
/* blazer_haptic_tap=1: one ROM effect per new touch contact (SweetHIDTouch::touch), from a worker thread. */
static uint32_t tap_on;
static uint32_t tap_armed;      /* set once the ID stage has made the service ready */
static uint32_t tap_pending;
static struct hh_tap tap;
#endif

/* SweetHIDTouch::touch on a new contact, under its IOLock: no wait and no bus work here, only a wakeup. */
void blazer_haptic_tap(void);
void
blazer_haptic_tap(void)
{
#if BLAZER_HAPTIC_SERVICE
	if (os_atomic_load(&tap_armed, acquire) == 0) {
		return;
	}
	os_atomic_store(&tap_pending, 1, release);
	thread_wakeup((event_t)&tap_pending);
#endif
}

/* Thread context only, synchronous, at most 100ms effect + bounded bus polls.
 * No user client/PCM endpoint: Actuator waveforms need a real waveform backend. */
int
blazer_haptic_play_rom(uint32_t index, uint32_t amplitude, uint32_t duration_ms)
{
#if BLAZER_HAPTIC_SERVICE
 int rc;
 if (service_on != 1) return ENXIO;
 if (!lck_mtx_try_lock(&haptic_lock)) return EBUSY;
 if (!service_ready) { lck_mtx_unlock(&haptic_lock); return ENXIO; }
 rc = hh_play_rom(&haptic, index, amplitude, duration_ms);
 if (rc > 0) service_ready = false; /* any hardware fault requires a fresh boot */
 lck_mtx_unlock(&haptic_lock);
 return rc == HHS_INVALID ? EINVAL : rc == HHS_UNSUPPORTED ? ENOTSUP :
     rc == HHS_NOT_READY ? ENXIO : rc > 0 ? EIO : 0;
#else
 (void)index; (void)amplitude; (void)duration_ms;
 return ENXIO;
#endif
}
static struct hh_cfg boot_cfg;
static uint32_t boot_delay_s = 45;

static volatile uint32_t *
at(uint64_t pa)
{
	for (unsigned i = 0; i < sizeof(windows) / sizeof(windows[0]); i++) {
		if (windows[i].va != 0 && pa >= windows[i].pa && pa < windows[i].pa + 0x1000) {
			return (volatile uint32_t *)(windows[i].va + (pa - windows[i].pa));
		}
	}
	return NULL;
}

static int
k_read32(__unused void *ctx, uint64_t pa, uint32_t *value)
{
	volatile uint32_t *p = at(pa);

	if (p == NULL) {
		return -1;
	}
	*value = *p;
	return 0;
}

static int
k_write32(__unused void *ctx, uint64_t pa, uint32_t value)
{
	volatile uint32_t *p = at(pa);

	if (p == NULL) {
		return -1;
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	*p = value;
	__asm__ volatile ("dsb sy" ::: "memory");
	return 0;
}

static void
k_smc(__unused void *ctx, uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t r[2])
{
	register uint64_t x0 __asm__("x0") = fn;
	register uint64_t x1 __asm__("x1") = a1;
	register uint64_t x2 __asm__("x2") = a2;
	register uint64_t x3 __asm__("x3") = a3;

	__asm__ volatile ("dsb sy\n\tsmc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3) : :
	    "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory", "cc");
	r[0] = x0;
	r[1] = x1;
}

static void k_delay_us(__unused void *ctx, uint32_t us) { delay_for_interval(us, NSEC_PER_USEC); }

static void
k_log(__unused void *ctx, const char *format, ...)
{
	va_list args;

	printf("blazer-haptic: ");
	va_start(args, format);
	vprintf(format, args);
	va_end(args);
}

static void k_cpm_enter(__unused void *ctx) { blazer_cpmq_enter(); }
static void k_cpm_exit(__unused void *ctx) { blazer_cpmq_exit(); }

#if BLAZER_HAPTIC_SERVICE
static uint64_t
tap_now_ms(void)
{
	uint64_t ns = 0;

	absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
	return ns / NSEC_PER_MSEC;
}

/* Runs on the haptic thread after the ID stage. Never returns while tap feedback is on. */
static void
tap_worker(void)
{
	/* The physically commanded effect of haptic-3-r2 unless blazer_haptic_index/_ms say otherwise; the service caps at 100 ms */
	uint32_t index = boot_cfg.rom_index < 39 ? boot_cfg.rom_index : 0;
	uint32_t ms = boot_cfg.effect_ms >= 1 && boot_cfg.effect_ms <= 100 ? boot_cfg.effect_ms : 100;

	printf("blazer-haptic: tap feedback on: rom %u, %u ms, gap %u ms, at most %u\n", index, ms, HH_TAP_GAP_MS, HH_TAP_MAX);
	os_atomic_store(&tap_armed, 1, release);
	for (;;) {
		assert_wait((event_t)&tap_pending, THREAD_UNINT);
		if (os_atomic_xchg(&tap_pending, 0, acq_rel) == 0) {
			(void)thread_block(THREAD_CONTINUE_NULL);
			continue;
		}
		clear_wait(current_thread(), THREAD_AWAKENED);
		uint64_t now = tap_now_ms();
		if (!hh_tap_due(&tap, now)) {
			if (tap.off) {
				break;
			}
			continue;
		}
		int rc = blazer_haptic_play_rom(index, 10000, ms);
		hh_tap_done(&tap, now, rc);
		if (tap.sent <= 8 || tap.sent % 25 == 0 || rc != 0) {
			printf("blazer-haptic: tap %u rc %d (skipped %u)\n", tap.sent, rc, tap.skipped);
		}
		if (tap.off) {
			break;
		}
	}
	os_atomic_store(&tap_armed, 0, release);
	printf("blazer-haptic: tap feedback off: sent %u skipped %u refused %u last rc %d\n", tap.sent, tap.skipped, tap.refused, tap.last_rc);
}
#endif

static void
haptic_thread(__unused void *parameter, __unused wait_result_t result)
{
	static const struct hh_ops ops = { .read32 = k_read32, .write32 = k_write32, .smc = k_smc, .delay_us = k_delay_us, .log = k_log, .cpm_enter = k_cpm_enter, .cpm_exit = k_cpm_exit };

	printf("blazer-haptic: stage %u, starts in %u s\n", boot_cfg.stage, boot_delay_s);
	delay_for_interval(boot_delay_s * 1000, NSEC_PER_MSEC);
	for (unsigned i = 0; i < sizeof(windows) / sizeof(windows[0]); i++) {
		windows[i].va = ml_io_map((vm_offset_t)windows[i].pa, 0x1000);
	}
	hh_init(&haptic, &ops, &boot_cfg);
	(void)hh_run(&haptic);
	printf("blazer-haptic: ends: %s, sent %d stopped %d\n", hh_stop_name(haptic.stop), haptic.effect_sent, haptic.effect_stopped);
#if BLAZER_HAPTIC_SERVICE
	lck_mtx_lock(&haptic_lock);
	service_ready = service_on == 1 && haptic.stop == HH_OK;
	if (service_on == 1) printf("blazer-haptic: native ROM service ready %u, nominal only\n", service_ready);
	bool tap_go = tap_on == 1 && service_ready;
	lck_mtx_unlock(&haptic_lock);
	if (tap_go) {
		tap_worker();
	}
#endif
	(void)thread_terminate(current_thread());
	thread_block(THREAD_CONTINUE_NULL);
}

void
blazer_haptic_init(void)
{
	thread_t thread;

#if BLAZER_HAPTIC_SERVICE
	/* blazer_haptic_tap=1 alone is the whole profile: the ID-only stage (no boot buzz) plus the service. */
	if (PE_parse_boot_argn("blazer_haptic_tap", &tap_on, sizeof(tap_on)) && tap_on == 1) {
		uint32_t stage = HH_STAGE_ID, service = 1;
		if ((PE_parse_boot_argn("blazer_haptic", &stage, sizeof(stage)) && stage != HH_STAGE_ID) ||
		    (PE_parse_boot_argn("blazer_haptic_service", &service, sizeof(service)) && service != 1)) {
			printf("blazer-haptic: tap needs stage 1 and service 1, off\n");
			return;
		}
		boot_cfg.stage = HH_STAGE_ID;
		service_on = 1;
	} else {
		tap_on = 0;
	}
#endif
	if (boot_cfg.stage == 0 && (!PE_parse_boot_argn("blazer_haptic", &boot_cfg.stage, sizeof(boot_cfg.stage)) || boot_cfg.stage == 0)) {
		return;
	}
#if BLAZER_HAPTIC_SERVICE
	if (tap_on != 1) {
		(void)PE_parse_boot_argn("blazer_haptic_service", &service_on, sizeof(service_on));
	}
	/* Service activation never creates a boot buzz. Explicit ID-only stage required. */
	if (service_on != 0 && (service_on != 1 || boot_cfg.stage != HH_STAGE_ID)) return;
#endif
	(void)PE_parse_boot_argn("blazer_haptic_ms", &boot_cfg.effect_ms, sizeof(boot_cfg.effect_ms));
	(void)PE_parse_boot_argn("blazer_haptic_index", &boot_cfg.rom_index, sizeof(boot_cfg.rom_index));
	(void)PE_parse_boot_argn("blazer_haptic_delay", &boot_delay_s, sizeof(boot_delay_s));
	if (boot_delay_s < 30 || boot_delay_s > 600) {
		boot_delay_s = 45;
	}
	if (kernel_thread_start(haptic_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}
#endif /* BLAZER */
