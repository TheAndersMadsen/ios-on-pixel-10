/* SPDX-License-Identifier: MIT
 * Host test for blazer_gpu_tipc=7/8 (M3 S1, coremem only). Includes the kernel file with BLAZER_AOC_HOSTTEST and a modelled firmware behind the
 * shared heap and the MTS kick, as m2/tests/test_m2.c does. Checks the exact sysinit bytes rung 7 and rung 8 publish, the readback, and the strict
 * trace gate: clean init PASS; a gpu2-shaped init fault, a late fault, malformed/truncated/wrapped/empty/moving traces, asserts, fw faults, bad HWR
 * flags and FWCCB fault commands all FAIL, and a boot-time fault sends no command at all. Optional: S1_GPU2_READER=<gpu2 reader.txt> replays the
 * phone's first M2 fwlog group (boot slice 120 words, then all 476) and requires the gate to see its fault. */
#define BLAZER 1
#define BLAZER_AOC_HOSTTEST 1
#define BLAZER_GPU_FW_DIAGNOSTIC 1
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;

static char logbuf[1 << 20];
static size_t loglen;
static int tprintf(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	int n = vsnprintf(logbuf + loglen, sizeof(logbuf) - loglen, fmt, ap);
	va_end(ap);
	if (n > 0 && loglen + (size_t)n < sizeof(logbuf)) loglen += (size_t)n;
	return n;
}
#define printf tprintf

static uint64_t now_ms;
static void fw_tick(void);
static uint64_t aoc_now_ms(void) { return now_ms; }
static void aoc_sleep_ms(unsigned ms) { now_ms += ms; fw_tick(); }
static void aoc_smc8(uint64_t r[8]) { (void)r; }
static void *aoc_page_alloc(uint32_t len) { return aligned_alloc(4096, len); }
#define aoc_pa(va) ((uint64_t)(uintptr_t)(va))
#define aoc_barrier() __sync_synchronize()
#define aoc_dmb() __sync_synchronize()
static void IOSleep(unsigned ms) { (void)ms; }

static uint8_t *heap;
static unsigned kicks, kick_bad, surveys;
static void model_kick(void);
#define gta_shared_map() ((volatile uint8_t *)heap)
#define gta_power_on(rgx) (*(rgx) = 0x1000, 0)
#define gta_mts_kick(rgx, v) do { if ((rgx) != 0x1000 || (v) != 0) kick_bad++; kicks++; model_kick(); } while (0)
#define gta_survey() (surveys++)
#define gta_carveout_map() ((volatile uint32_t *)NULL)
static const uint8_t blazer_gpu_fw[16];

#include "../src/blazer_gpu_tipc.c"
#include "inc/hmfw_diagnostic.c"

enum model { CLEAN, GPU2, LOCKUP, POLL, RESET, LATE_FAULT, MALFORMED, TRUNCATED, WRAPPED, EMPTY, MOVING, ASSERT, FWFAULT, HWRBAD, DUMP, PF, REPLAY };
static enum model model;
static uint32_t replay[12000], replay_n, replay_ptr;

static uint32_t hr(uint32_t off) { return gs_r32(off); }
static void hw(uint32_t off, uint32_t v) { gs_w32(off, v); }
static void hstr(uint32_t off, const char *s) { for (size_t i = 0; i <= strlen(s); i++) heap[off - (uint32_t)GF_MAIN_HEAP_OFF + i] = (uint8_t)s[i]; }

static uint32_t tb_ptr;
static void tb_word(uint32_t w) { hw(gsh.tbdata + 4u * (tb_ptr % GTA_TB_DW), w); tb_ptr++; }
static void tb_publish(void) { hw(gsh.tbuf + HMFV2_TB_TRACE_POINTER0, tb_ptr % GTA_TB_DW); }
/* One well-formed entry: id, ts hi, ts lo, PARAMNUM(id) params */
static void fw_log(uint32_t id, const uint32_t *a)
{
	uint32_t n = (id >> 16) & 0xfu;
	tb_word(id); tb_word(0); tb_word((uint32_t)now_ms);
	for (uint32_t i = 0; i < n; i++) tb_word(a ? a[i] : i);
	tb_publish();
}
static void fw_start(void)
{
	static const uint32_t mmu[4] = { 0, 0xa1000000u, 0x00000009u, 0x00008200u };
	hw(GTA_SH_SYSINIT + GF_SI_bFirmwareStarted, 1);
	hw(GTA_SH_SYSINIT + GF_SI_ui32FirmwareStartedTimeStamp, 0xb52);
	hw(gsh.sysdata + HMFV2_SYS_POW_STATE, 1);
	hw(gsh.sysdata + HMFV2_SYS_HWR_FLAGS, 1);
	hw(gsh.sysdata + HMFV2_SYS_OS_RUNTIME_FLAGS0, 0xa);
	if (model == REPLAY) {
		for (uint32_t i = 0; i < replay_n; i++) hw(gsh.tbdata + 4u * i, replay[i]);
		hw(gsh.tbuf + HMFV2_TB_TRACE_POINTER0, replay_ptr);
		hw(gsh.sysdata + HMFV2_SYS_HWR_FLAGS, 0xa);
		return;
	}
	fw_log(0x70000001u, NULL);              /* 0 params */
	fw_log(0x70020002u, NULL);              /* 2 params */
	switch (model) {
	case GPU2:
		fw_log((uint32_t)HMFS1_SF_MMU_FAULT_EVENT, (const uint32_t[]){ 0x200 });
		fw_log((uint32_t)HMFS1_SF_CORE_MMU_FAULT, mmu);
		fw_log((uint32_t)HMFS1_SF_HIT_LOCKUP, (const uint32_t[]){ 0 });
		fw_log((uint32_t)HMFS1_SF_START_HW_RESET, (const uint32_t[]){ 0 });
		hw(gsh.sysdata + HMFV2_SYS_HWR_FLAGS, 0xa);
		hw(gsh.fccb, (uint32_t)HMFS1_FWCCB_DEBUG_DUMP);
		hw(gsh.fctl + GF_CCB_W, 1);
		break;
	case LOCKUP: fw_log((uint32_t)HMFS1_SF_HIT_LOCKUP_DM, NULL); break;
	case POLL: fw_log((uint32_t)HMFS1_SF_FAILED_HW_POLL, (const uint32_t[]){ 1, 0xf0c8, 0 }); break;
	case RESET: fw_log((uint32_t)HMFS1_SF_START_HW_RESET, (const uint32_t[]){ 0 }); break;
	case MALFORMED: tb_word(0x12345678u); tb_word(0); tb_word(0); tb_publish(); break;
	case TRUNCATED: tb_word(0x70030003u); tb_word(0); tb_word(0); tb_word(1); tb_publish(); break;  /* 3 params, 1 present */
	case WRAPPED: hw(gsh.tbuf + HMFV2_TB_WRAP0, 1); break;
	case EMPTY: tb_ptr = 0; tb_publish(); break;
	case ASSERT: hstr(gsh.tbuf + HMFV2_TB_ASSERT0_PATH, "fw/main.c"); hw(gsh.tbuf + HMFV2_TB_ASSERT0_LINE, 12); break;
	case FWFAULT: hw(gsh.sysdata + HMFV2_SYS_FW_FAULTS, 1); break;
	case HWRBAD: hw(gsh.sysdata + HMFV2_SYS_HWR_FLAGS, 0x9); break;
	case DUMP: hw(gsh.fccb, (uint32_t)HMFS1_FWCCB_DEBUG_DUMP); hw(gsh.fctl + GF_CCB_W, 1); break;
	case PF: hw(gsh.fccb, (uint32_t)HMFS1_FWCCB_FW_PF); hw(gsh.fctl + GF_CCB_W, 1); break;
	default: break;
	}
}
static void fw_exec(unsigned slot)
{
	uint32_t type = hr(gsh.kccb + slot * GF_SZ_RGXFWIF_KCCB_CMD);
	hw(gsh.rtn + 4u * slot, 1);
	fw_log((uint32_t)HMFS1_SF_KCCBCMD_EXEC, (const uint32_t[]){ slot, type, 0 });
	if (model == LATE_FAULT && type == GTA_CMD_STATEFLAGS) {
		fw_log((uint32_t)HMFS1_SF_FAILED_HW_POLL, (const uint32_t[]){ 1, 0xf0b8, 0 });
	}
}
static void model_kick(void)
{
	uint32_t r = hr(gsh.kctl + GF_CCB_R), w = hr(gsh.kctl + GF_CCB_W);
	for (; r != w; r++) { hw(gsh.kctl + GF_CCB_R, r + 1); fw_exec(r); }
}
static void fw_tick(void)
{
	if (model == MOVING && gsh.tbdata) fw_log(0x70000004u, NULL);   /* never quiet */
}

static int failures, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { failures++; fprintf(stderr, "FAIL %s:%d: ", __FILE__, __LINE__); fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } } while (0)
static bool logged(const char *s) { return strstr(logbuf, s) != NULL; }

static void reset(enum model m, unsigned rung)
{
	memset(heap, 0xa5, GF_RAW_SIZE - GF_MAIN_HEAP_OFF);   /* stale bytes: init must zero what it publishes */
	loglen = 0; logbuf[0] = 0; kicks = kick_bad = surveys = 0; tb_ptr = 0;
	aoc_stop_reason = NULL; aoc.dead = false;
	memset(&gsh, 0, sizeof(gsh));
	model = m; gta_diag_wanted = 1; gta_s1_coremem = rung == 7;
}
/* Rung 7/8 from shared init to verdict, START replaced by the model's start */
static int run(enum model m, unsigned rung)
{
	reset(m, rung);
	CHECK(gta_shared_init(true) == 0, "shared init");
	CHECK(gta_s1_coremem_check(rung) == 0, "readback");
	fw_start();
	return gta_m2(0x1000, true);
}

/* Every nonzero 32-bit word of SYSINIT before START, COREMEM-INIT.md section 4.3 */
static void check_sysinit(unsigned rung)
{
	struct { uint32_t off, v; } want[] = {
		{ 0x00, 0xba128000u }, { 0x0c, 0xda }, { 0x14, 0xe0 }, { 0x1c, 0xec }, { 0x20, 0x40000000u }, { 0x24, 0xec }, { 0x2c, 0xf0 }, { 0x34, 0xed },
		{ 0x98, 0x40238000u }, { 0x9c, 0x40229000u }, { 0xa0, 0x40236000u }, { 0xb0, 0x40237000u }, { 0xb4, 0x11e1a300u }, { 0xb8, 0x0249f000u },
		{ 0xbc, 0xea60u }, { 0x148, 1 }, { 0x150, 0xc013c000u }, { 0x154, 0xe1u },
	};
	for (uint32_t off = 0; off < GF_SZ_RGXFWIF_SYSINIT; off += 4) {
		uint32_t v = 0;
		for (unsigned i = 0; i < sizeof(want) / sizeof(want[0]); i++) if (want[i].off == off) v = want[i].v;
		if (rung != 7 && (off == 0x150 || off == 0x154)) v = 0;
		CHECK(hr(GTA_SH_SYSINIT + off) == v, "rung %u sysinit +0x%x = 0x%x, want 0x%x", rung, off, hr(GTA_SH_SYSINIT + off), v);
	}
}

static int load_replay(const char *path, uint32_t ptr)
{
	FILE *f = fopen(path, "r");
	char line[512];
	bool in = false;
	replay_n = 0;
	if (!f) return -1;
	while (fgets(line, sizeof(line), f)) {
		char *p;
		if (strstr(line, "M2 fwlog: ptr")) { if (in) break; in = true; continue; }
		if (in && strstr(line, "M2 fwlog: end")) break;
		if (in && (p = strstr(line, "M2 TB "))) {
			unsigned off, w[8];
			if (sscanf(p, "M2 TB %4x: %x %x %x %x %x %x %x %x", &off, &w[0], &w[1], &w[2], &w[3], &w[4], &w[5], &w[6], &w[7]) == 9)
				for (int i = 0; i < 8 && replay_n < 12000; i++) replay[replay_n++] = w[i];
		}
	}
	fclose(f);
	replay_ptr = ptr;
	return replay_n >= ptr ? 0 : -1;
}

int main(void)
{
	int rc;
	heap = calloc(1, GF_RAW_SIZE - GF_MAIN_HEAP_OFF);

	/* Value and bytes */
	CHECK(GTA_S1_COREMEM_VA == 0xe1c013c000ULL && GTA_S1_SI_COREMEM == 0x150u, "devva");
	CHECK(GTA_S1_COREMEM_VA != GTA_FWVA_HEAP + GTA_OFF_CDATA && GTA_S1_COREMEM_VA != GTA_CARVEOUT_PA + GTA_OFF_CDATA, "not fwva, not pa");
	reset(CLEAN, 7);
	CHECK(gta_shared_init(true) == 0, "init 7");
	{
		static const uint8_t b[8] = { 0x00, 0xc0, 0x13, 0xc0, 0xe1, 0x00, 0x00, 0x00 };
		CHECK(!memcmp(heap + (GTA_SH_SYSINIT - (uint32_t)GF_MAIN_HEAP_OFF) + 0x150, b, 8), "little-endian bytes at +0x150");
	}
	check_sysinit(7);
	CHECK(gta_s1_coremem_check(7) == 0 && logged("M3 COREMEM: sysinit_off=0x150 raw_heap=0xe1c0000000 section_off=0x13c000 devva=0x000000e1c013c000 lo=0xc013c000 hi=0x000000e1\n"),
	    "coremem line\n%s", logbuf);
	CHECK(logged("trusty fw_va 0xc013c000 and pa 0xba03c000") && logged("readback match"), "forms line");
	/* Readback mismatch: STOP before START */
	hw(GTA_SH_SYSINIT + 0x154, 0);
	CHECK(gta_s1_coremem_check(7) == -1 && aoc_stop_reason && !strcmp(aoc_stop_reason, "sysinit coremem readback differs"), "hi word lost -> stop");
	/* Rung 8: the field stays 0, everything else as rung 7 */
	reset(CLEAN, 8);
	CHECK(gta_shared_init(true) == 0, "init 8");
	check_sysinit(8);
	CHECK(gta_s1_coremem_check(8) == 0 && logged("M3 COREMEM: control, sysinit_off=0x150 left 0"), "control line");
	/* Rung 6's init unchanged: the flag is off there, and the whole heap equals rung 8's */
	{
		uint8_t *h8 = malloc(GF_RAW_SIZE - GF_MAIN_HEAP_OFF);
		memcpy(h8, heap, GF_RAW_SIZE - GF_MAIN_HEAP_OFF);
		reset(CLEAN, 6);
		CHECK(gta_shared_init(true) == 0, "init 6");
		CHECK(!memcmp(h8, heap, GF_RAW_SIZE - GF_MAIN_HEAP_OFF), "rung 6 == rung 8 shared heap");
		reset(CLEAN, 7);
		CHECK(gta_shared_init(true) == 0, "init 7 again");
		size_t diff = 0, at = 0;
		for (size_t i = 0; i < GF_RAW_SIZE - GF_MAIN_HEAP_OFF; i++) if (h8[i] != heap[i]) { diff++; at = i; }
		CHECK(diff == 4 && at == GTA_SH_SYSINIT - GF_MAIN_HEAP_OFF + 0x154, "rung 7 differs from rung 8 in 4 bytes, the field only (%zu, last 0x%zx)", diff, at);
		free(h8);
	}

	/* CLEAN: S1 PASS, both commands executed, boot and final lines zero */
	rc = run(CLEAN, 7);
	CHECK(rc == GTA_PASS, "clean rc %d\n%s", rc, logbuf);
	CHECK(logged("M3 S1 boot: mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 0 debug_dump 0 fw_faults 0 assert_empty 1; trace_valid 1 words 8 entries 2"), "boot line\n%s", logbuf);
	CHECK(logged("M3 S1 final: mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 0 debug_dump 0 fw_faults 0 assert_empty 1; trace_valid 1 words 20 entries 4"), "final line\n%s", logbuf);
	CHECK(logged("M2 HEALTH PASS") && logged("M3 S1 PASS: clean firmware init and health; no client KICK issued\n"), "pass lines");
	CHECK(kicks == 2 && kick_bad == 0 && surveys == 1, "two kicks, one survey");
	CHECK(strstr(logbuf, "M3 S1 boot") < strstr(logbuf, "M2 HEALTH_CHECK: slot 0") && strstr(logbuf, "M2 STATEFLAGS_CTRL") < strstr(logbuf, "M3 S1 final") &&
	    strstr(logbuf, "M3 S1 final") < strstr(logbuf, "M2 fwlog: ptr"), "gate order");
	if (getenv("S1_LOGFILE")) { FILE *f = fopen(getenv("S1_LOGFILE"), "w"); fputs(logbuf, f); fclose(f); }

	/* Boot-time faults: STOP, no command sent, the pre-command trace and survey kept */
	static const struct { enum model m; const char *line; } bad[] = {
		{ GPU2, "mmu_fault 2 lockup 1 failed_hw_poll 0 hwr_reset 1 debug_dump 1 fw_faults 0 assert_empty 1; trace_valid 1" },
		{ LOCKUP, "mmu_fault 0 lockup 1 failed_hw_poll 0 hwr_reset 0 debug_dump 0 fw_faults 0 assert_empty 1; trace_valid 1" },
		{ POLL, "mmu_fault 0 lockup 0 failed_hw_poll 1 hwr_reset 0 debug_dump 0" },
		{ RESET, "mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 1 debug_dump 0" },
		{ MALFORMED, "trace_valid 0 words 8" },
		{ TRUNCATED, "trace_valid 0 words 8" },
		{ WRAPPED, "trace_valid 0" },
		{ EMPTY, "trace_valid 0 words 0" },
		{ MOVING, "trace_valid 0" },
		{ ASSERT, "assert_empty 0; trace_valid 1" },
		{ FWFAULT, "fw_faults 1 assert_empty 1; trace_valid 1" },
		{ HWRBAD, "hwr 0x9 BAD" },
		{ DUMP, "debug_dump 1" },
		{ PF, "fault_cmds 1" },
	};
	for (unsigned i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
		rc = run(bad[i].m, 7);
		CHECK(rc == GTA_STOPPED && kicks == 0, "model %d: rc %d kicks %u\n%s", bad[i].m, rc, kicks, logbuf);
		CHECK(aoc_stop_reason && !strcmp(aoc_stop_reason, "S1 init not clean before HEALTH_CHECK"), "model %d reason %s", bad[i].m, aoc_stop_reason ? aoc_stop_reason : "-");
		CHECK(logged("M3 S1 boot: ") && logged(bad[i].line), "model %d line '%s'\n%s", bad[i].m, bad[i].line, logbuf);
		CHECK(!logged("M3 S1 PASS") && !logged("M2 HEALTH PASS") && !logged("M2 HEALTH_CHECK"), "model %d no health", bad[i].m);
		CHECK(logged("M3 S1 FAIL: firmware init not clean before HEALTH_CHECK; no command sent") && logged("M2 fwlog: ptr") && surveys == 1, "model %d tail kept", bad[i].m);
	}
	if (getenv("S1_SHOW")) { run(GPU2, 7); fputs(logbuf, stdout); }

	/* A fault after STATEFLAGS: M2 health passes, S1 does not */
	rc = run(LATE_FAULT, 7);
	CHECK(rc == GTA_STOPPED && aoc_stop_reason && !strcmp(aoc_stop_reason, "S1 trace not clean after STATEFLAGS_CTRL"), "late rc %d", rc);
	CHECK(logged("M3 S1 boot: mmu_fault 0") && logged("M3 S1 final: mmu_fault 0 lockup 0 failed_hw_poll 1") && logged("M3 S1 FAIL: firmware trace not clean after STATEFLAGS_CTRL") && !logged("M3 S1 PASS"), "late lines\n%s", logbuf);

	/* Rung 8 under the same gate: clean model passes (the gate, not the field, decides) */
	rc = run(CLEAN, 8);
	CHECK(rc == GTA_PASS && logged("M3 S1 PASS") && hr(GTA_SH_SYSINIT + 0x150) == 0, "rung 8 clean");

	/* Rung 6 path untouched by S1: no gate lines */
	reset(CLEAN, 6);
	CHECK(gta_shared_init(true) == 0, "init");
	fw_start();
	rc = gta_m2(0x1000, false);
	CHECK(rc == GTA_PASS && !logged("M3 S1") && hr(GTA_SH_SYSINIT + 0x150) == 0, "rung 6 unchanged");

	/* The phone's own gpu2 trace (optional fixture, out of git) */
	if (getenv("S1_GPU2_READER")) {
		CHECK(load_replay(getenv("S1_GPU2_READER"), 120) == 0, "replay load");
		rc = run(REPLAY, 7);
		CHECK(rc == GTA_STOPPED && kicks == 0 && logged("M3 S1 boot: mmu_fault 2 lockup 1 failed_hw_poll 0 hwr_reset 1") && logged("trace_valid 1 words 120"), "gpu2 boot slice\n%s", logbuf);
		CHECK(load_replay(getenv("S1_GPU2_READER"), 476) == 0, "replay load 476");
		rc = run(REPLAY, 7);
		CHECK(rc == GTA_STOPPED && logged("mmu_fault 2 lockup 1 failed_hw_poll 8 hwr_reset 1") && logged("trace_valid 1 words 476"), "gpu2 full\n%s", logbuf);
		fprintf(stderr, "gpu2 replay: done\n");
	}

	fprintf(stderr, "%d checks, %d failed\n", checks, failures);
	return failures != 0;
}
