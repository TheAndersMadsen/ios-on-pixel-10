/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. HOST ONLY test of blazer_gpu=3 (bsd/dev/blazer_gpu.c) on a modelled bus.
 * The model records every register access and fails on: a write other than gate on/off to gpu_control, any access while the domain is off,
 * an rgx access with the core logic gated or before a valid pfsm status, an offset outside the 64 KiB view or unaligned, and a survey read of an
 * offset not in the reviewed list. Modelled hardware: passing here says the code does what PLAN.md says, not what the GPU does. */
#include <stdarg.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include "blazer_gpu_test.h"
#undef printf

void gpu_proof_for_test(unsigned mode);

#define PA_CONTROL 0x3480a000u
#define PA_PFSM    0x34813000u
#define PA_SMMU    0x34c00000u
#define PA_RGX     0x34f00000u
#define CORE_ID    0x00470002099004bcULL

static _Alignas(4096) uint8_t page_control[4096], page_pfsm[4096], page_smmu[4096], page_rgx[0x10000];

static struct {
	bool domain_on, gate_on, pfsm_read_ok;
	unsigned votes_on, votes_off, maps_rgx_small, maps_rgx_survey, fail_survey_map;
	unsigned writes, rgx_reads, failures, torn_left, unstable;
	uint32_t pfsm_status;
	uint64_t timer, timer_rate, core_id;
	unsigned read_count[0x10000 / 4];
	char out[16384];
	size_t out_len;
} bus;

static unsigned checks, failed;
#define CHECK(c) do { checks++; if (!(c)) { failed++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static void
reset(void)
{
	memset(&bus, 0, sizeof(bus));
	bus.pfsm_status = 1u << 5;   /* STATE_VALID, no error */
	bus.timer = 0x123456789aULL;
	bus.timer_rate = 38;         /* ticks per us: any non-zero rate */
	bus.core_id = CORE_ID;
}

int
blazer_gpu_test_printf(const char *fmt, ...)
{
	va_list ap;
	int n;

	va_start(ap, fmt);
	n = vsnprintf(bus.out + bus.out_len, sizeof(bus.out) - bus.out_len, fmt, ap);
	va_end(ap);
	if (n > 0 && bus.out_len + (size_t)n < sizeof(bus.out)) {
		bus.out_len += (size_t)n;
	}
	return n;
}

static unsigned
count(const char *needle)
{
	unsigned n = 0;

	for (const char *p = bus.out; (p = strstr(p, needle)) != NULL; p += strlen(needle)) {
		n++;
	}
	return n;
}

void blazer_cpmq_lpb_arm(void) {}

static uint32_t last_on;

int
blazer_cpmq_call(uint32_t src, uint32_t dst, const uint32_t *body, uint32_t *reply, uint32_t ms, uint32_t *waits)
{
	CHECK(src == CPMQ_SRC_POWER && dst == CPMQ_DST_LPB && body[0] == CPMQ_LPB_SET && body[1] == CPMQ_LPB_GPU && body[2] <= 1 && ms == 3000);
	last_on = body[2];
	reply[1] = 0xf;
	reply[2] = body[2] ? 0x12 : 0x11;
	reply[3] = CPMQ_LPB_GPU;
	*waits = 1;
	return CPMQ_OK;
}

int
blazer_cpmq_lpb_wait(uint32_t *id, uint32_t *event, uint32_t ms)
{
	CHECK(ms == 3000);
	*id = CPMQ_LPB_GPU;
	*event = last_on ? 0 : 1;
	if (last_on) {
		bus.domain_on = true;
		bus.votes_on++;
	} else {
		CHECK(!bus.gate_on);   /* core logic gated before the domain goes */
		bus.domain_on = false;
		bus.votes_off++;
	}
	return CPMQ_OK;
}

const char *cpmq_rc_name(int rc) { (void)rc; return "MODEL"; }

vm_offset_t
ml_io_map(vm_offset_t pa, vm_size_t size)
{
	CHECK(bus.domain_on || pa == PA_SMMU);
	if (pa == PA_CONTROL && size == 4096) return (vm_offset_t)page_control;
	if (pa == PA_PFSM && size == 4096) return (vm_offset_t)page_pfsm;
	if (pa == PA_SMMU && size == 4096) return (vm_offset_t)page_smmu;
	if (pa == PA_RGX && size == 4096) { bus.maps_rgx_small++; return (vm_offset_t)page_rgx; }
	if (pa == PA_RGX && size == 0x10000) {
		bus.maps_rgx_survey++;
		return bus.fail_survey_map ? 0 : (vm_offset_t)page_rgx;
	}
	CHECK(!"unexpected map");
	return 0;
}

void
delay(int us)
{
	CHECK(us == 100 || us == 1000);
	bus.timer += bus.timer_rate * (uint64_t)us;
}

void
blazer_gpu_test_w32(vm_offset_t va, uint32_t value)
{
	bus.writes++;
	CHECK(bus.domain_on);
	CHECK(va == (vm_offset_t)page_control);   /* the only register this code may write */
	CHECK(value == 0 || value == 8);
	bus.gate_on = value == 0;
}

uint32_t
blazer_gpu_test_r32(vm_offset_t va)
{
	CHECK(bus.domain_on);
	if (va == (vm_offset_t)page_control) {
		return bus.gate_on ? 0x1u : 0xau;
	}
	if (va == (vm_offset_t)page_pfsm + 8) {
		CHECK(bus.gate_on);
		bus.pfsm_read_ok = (bus.pfsm_status & (1u << 5)) && !(bus.pfsm_status & 0x300u);
		return bus.pfsm_status;
	}
	if (va >= (vm_offset_t)page_rgx && va < (vm_offset_t)page_rgx + sizeof(page_rgx)) {
		const uint32_t off = (uint32_t)(va - (vm_offset_t)page_rgx);

		CHECK(bus.gate_on && bus.pfsm_read_ok);
		CHECK((off & 3u) == 0);
		bus.rgx_reads++;
		bus.read_count[off / 4]++;
		if (off == 0x20) return (uint32_t)bus.core_id;
		if (off == 0x24) return (uint32_t)(bus.core_id >> 32);
		if (off == 0x160) return (uint32_t)bus.timer;
		if (off == 0x164) {
			uint32_t high = (uint32_t)(bus.timer >> 32);

			if (bus.unstable) {
				return high + (bus.read_count[off / 4] & 1u);
			}
			if (bus.torn_left && (bus.read_count[off / 4] % 2) == 0) {
				bus.torn_left--;
				return high + 1;   /* the second high read of a pair differs once */
			}
			return high;
		}
		return 0xa5000000u | off;
	}
	CHECK(!"read outside the mapped pages");
	return 0;
}

/* The reviewed list, as offsets (low word; high word +4 for 64-bit ones) */
static const struct { uint32_t off; bool wide; } want[] = {
	{ 0x0020, 1 }, { 0x0000, 1 }, { 0x0008, 1 }, { 0x0080, 1 }, { 0x0088, 1 }, { 0x0090, 0 }, { 0x0130, 0 },
	{ 0xe130, 1 }, { 0xe150, 1 }, { 0xe158, 1 }, { 0xe160, 1 }, { 0xe170, 1 }, { 0xe210, 1 }, { 0xe218, 1 },
	{ 0xe238, 1 }, { 0xe260, 1 }, { 0xe230, 0 }, { 0xe240, 0 },
};

static bool
allowed(uint32_t off)
{
	if (off == 0x160 || off == 0x164) return true;   /* TIMER */
	for (unsigned i = 0; i < sizeof(want) / sizeof(want[0]); i++) {
		if (off == want[i].off || (want[i].wide && off == want[i].off + 4)) return true;
	}
	return false;
}

static void
common_power_checks(void)
{
	CHECK(bus.votes_on == 1 && bus.votes_off == 1 && !bus.domain_on && !bus.gate_on);
	CHECK(count("blazer-gpu: domain off, done") == 1);
	CHECK(bus.writes == 2);   /* gate on, gate off */
}

static void
t_mode3_pass(void)
{
	reset();
	gpu_proof_for_test(3);
	common_power_checks();
	CHECK(count("PASS core id") == 1);
	CHECK(count("blazer-gpu: reg ") == 18);
	CHECK(count("CLOCK_RUNS") == 1 && count("CLOCK_STOPPED") == 0);
	CHECK(count("+38000 in 1000 us") == 1);
	CHECK(count("survey done, 18 registers") == 1);
	CHECK(count("reg MMU_FAULT_STATUS1 +0xe150 0xa500e154a500e150") == 1);
	CHECK(count("reg SLC_IDLE +0xe230 0xa500e230") == 1);
	CHECK(bus.maps_rgx_survey == 1);
	for (uint32_t off = 0; off < sizeof(page_rgx); off += 4) {
		if (bus.read_count[off / 4]) CHECK(allowed(off));
	}
	for (unsigned i = 0; i < sizeof(want) / sizeof(want[0]); i++) {
		CHECK(bus.read_count[want[i].off / 4] >= 1);
		if (want[i].wide) CHECK(bus.read_count[(want[i].off + 4) / 4] >= 1);
	}
	CHECK(bus.read_count[0x160 / 4] == 2 && bus.read_count[0x164 / 4] == 4);   /* two clean hi/lo/hi samples */
	CHECK(strstr(bus.out, "survey done") < strstr(bus.out, "core logic off"));
}

static void
t_mode1_unchanged(void)
{
	reset();
	gpu_proof_for_test(1);
	common_power_checks();
	CHECK(count("PASS core id") == 1 && count("blazer-gpu: reg ") == 0 && count("survey") == 0);
	CHECK(bus.rgx_reads == 4 && bus.maps_rgx_survey == 0);   /* CORE_ID twice, two words each */
}

static void
t_timer_stopped(void)
{
	reset();
	bus.timer_rate = 0;
	gpu_proof_for_test(3);
	common_power_checks();
	CHECK(count("CLOCK_STOPPED") == 1 && count("CLOCK_RUNS") == 0 && count("+0 in 1000 us") == 1);
}

static void
t_timer_torn_once(void)
{
	reset();
	bus.torn_left = 1;
	gpu_proof_for_test(3);
	common_power_checks();
	CHECK(count("CLOCK_RUNS") == 1 && count("UNSTABLE") == 0);
	CHECK(bus.read_count[0x160 / 4] == 3);   /* one retried sample */
}

static void
t_timer_unstable(void)
{
	reset();
	bus.unstable = 1;
	gpu_proof_for_test(3);
	common_power_checks();
	CHECK(count("TIMER UNSTABLE") == 1 && count("CLOCK_") == 0 && count("survey done") == 0);
	CHECK(bus.read_count[0x160 / 4] == 3);   /* bounded: three tries, then stop */
}

static void
t_no_clock(void)
{
	reset();
	bus.pfsm_status = 1u << 8;   /* an error bit, not valid */
	gpu_proof_for_test(3);
	common_power_checks();
	CHECK(count("NO_CLOCK") == 1 && bus.rgx_reads == 0 && bus.maps_rgx_survey == 0);
}

static void
t_id_mismatch(void)
{
	reset();
	bus.core_id = 0x0047000209900000ULL;
	gpu_proof_for_test(3);
	common_power_checks();
	CHECK(count("MISMATCH") == 1 && count("blazer-gpu: reg ") == 0 && bus.maps_rgx_survey == 0);
}

static void
t_survey_map_fails(void)
{
	reset();
	bus.fail_survey_map = 1;
	gpu_proof_for_test(3);
	common_power_checks();
	CHECK(count("survey: no map") == 1 && count("blazer-gpu: reg ") == 0 && bus.rgx_reads == 4);
}

int
main(void)
{
	t_mode3_pass();
	t_mode1_unchanged();
	t_timer_stopped();
	t_timer_torn_once();
	t_timer_unstable();
	t_no_clock();
	t_id_mismatch();
	t_survey_map_fails();
	printf("blazer_gpu=3 host test: %u checks, %u failed (8 cases)\n", checks, failed);
	if (failed) {
		fputs(bus.out, stderr);
	}
	return failed ? 1 : 0;
}
