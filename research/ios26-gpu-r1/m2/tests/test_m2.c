/* SPDX-License-Identifier: MIT
 * Host test for blazer_gpu_tipc=6 (M2). Includes the kernel file with BLAZER_AOC_HOSTTEST and a modelled firmware behind the shared heap and the MTS
 * kick. Models: STOCK (executes every command, writes return slots), P30 (what the phone showed: reads HEALTH_CHECK, never a return slot, posts DEBUG_DUMP),
 * EXEC_ONLY_WAITED (returns only for STATEFLAGS), DEAF (reads nothing), LATE (executes after 30 ms). Checks verdicts, the bytes rung 6 writes, the log lines. */
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

static uint8_t *heap;              /* GF_RAW_SIZE - GF_MAIN_HEAP_OFF bytes, the host's view of the uncached shared map */
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

enum model { STOCK, P30, EXEC_ONLY_WAITED, DEAF, LATE };
static enum model model;
static unsigned late_due;
static uint64_t late_at;

static uint32_t hr(uint32_t off) { return gs_r32(off); }
static void hw(uint32_t off, uint32_t v) { gs_w32(off, v); }
static void hstr(uint32_t off, const char *s) { for (size_t i = 0; i <= strlen(s); i++) heap[off - (uint32_t)GF_MAIN_HEAP_OFF + i] = (uint8_t)s[i]; }

/* What the firmware writes at START: started, OS 0 online, its log */
static uint32_t tb_ptr;
static void fw_log(uint32_t id, uint32_t a, uint32_t b)
{
	uint32_t w[5] = { id, 0, (uint32_t)now_ms, a, b };
	for (int i = 0; i < 5; i++) { hw(gsh.tbdata + 4u * (tb_ptr % GTA_TB_DW), w[i]); tb_ptr++; }
	hw(gsh.tbuf + HMFV2_TB_TRACE_POINTER0, tb_ptr % GTA_TB_DW);
}
static void fw_log2(uint32_t id, uint32_t a, uint32_t b, uint32_t c)
{
	uint32_t w[6] = { id, 0, (uint32_t)now_ms, a, b, c };
	for (int i = 0; i < 6; i++) { hw(gsh.tbdata + 4u * (tb_ptr % GTA_TB_DW), w[i]); tb_ptr++; }
	hw(gsh.tbuf + HMFV2_TB_TRACE_POINTER0, tb_ptr % GTA_TB_DW);
}
static void fw_start(void)
{
	hw(GTA_SH_SYSINIT + GF_SI_bFirmwareStarted, 1);
	hw(GTA_SH_SYSINIT + GF_SI_ui32FirmwareStartedTimeStamp, 0xadd);
	hw(gsh.sysdata + HMFV2_SYS_POW_STATE, 1);
	hw(gsh.sysdata + HMFV2_SYS_HWR_FLAGS, 1);
	hw(gsh.sysdata + HMFV2_SYS_OS_RUNTIME_FLAGS0, model == P30 ? 0 : 2);
	if (hr(gsh.tbuf + HMFV2_TB_LOG_TYPE) & 1u) fw_log(0x70000000u | 1u, 1, 2);
	if (model == P30) {
		hw(gsh.fccb, (uint32_t)HMFV_FC_DEBUG_DUMP);
		hw(gsh.fctl + GF_CCB_W, 1);
		hstr(gsh.tbuf + HMFV2_TB_ASSERT0_PATH, "fw/main.c");
		hstr(gsh.tbuf + HMFV2_TB_ASSERT0_INFO, "os not online");
		hw(gsh.tbuf + HMFV2_TB_ASSERT0_LINE, 1234);
		hw(gsh.sysdata + HMFV2_SYS_FW_FAULTS, 1);
		hstr(gsh.sysdata + HMFV2_SYS_FAULT_INFO0_PATH, "fw/fault.c");
		hw(gsh.sysdata + HMFV2_SYS_FAULT_INFO0_LINE, 77);
		hw(gsh.sysdata + HMFV2_SYS_CR_POLL_ADDR0, 0xe230);
	}
}
static void fw_exec(unsigned slot)
{
	uint32_t type = hr(gsh.kccb + slot * GF_SZ_RGXFWIF_KCCB_CMD);
	if (model == STOCK || model == LATE || (model == EXEC_ONLY_WAITED && type == GTA_CMD_STATEFLAGS)) hw(gsh.rtn + 4u * slot, 1);
	if (hr(gsh.tbuf + HMFV2_TB_LOG_TYPE) & 1u) fw_log2(0x70037013u, slot, type, 0);   /* RGXFW_SF_MTS_KCCBCMD_EXEC, 3 params */
}
static void model_kick(void)
{
	if (model == DEAF) return;
	uint32_t r = hr(gsh.kctl + GF_CCB_R), w = hr(gsh.kctl + GF_CCB_W);
	for (; r != w; r++) {
		hw(gsh.kctl + GF_CCB_R, r + 1);
		if (model == LATE) { late_due = r + 1; late_at = now_ms + 30; }
		else fw_exec(r);
	}
}
static void fw_tick(void)
{
	if (late_due && now_ms >= late_at) { fw_exec(late_due - 1); late_due = 0; }
}

static int failures, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { failures++; fprintf(stderr, "FAIL %s:%d: ", __FILE__, __LINE__); fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } } while (0)
static bool logged(const char *s) { return strstr(logbuf, s) != NULL; }

/* Rung 6 from shared init to verdict, START replaced by the model's start */
static int run(enum model m)
{
	memset(heap, 0, GF_RAW_SIZE - GF_MAIN_HEAP_OFF);
	loglen = 0; logbuf[0] = 0; kicks = kick_bad = surveys = 0; tb_ptr = 0; late_due = 0;
	aoc_stop_reason = NULL; aoc.dead = false;
	memset(&gsh, 0, sizeof(gsh));
	model = m;
	gta_diag_wanted = 1;
	CHECK(gta_shared_init(true) == 0, "shared init");
	fw_start();
	return gta_m2(0x1000);
}

int main(void)
{
	heap = calloc(1, GF_RAW_SIZE - GF_MAIN_HEAP_OFF);

	/* Layout facts the rung depends on: r2 agrees with r1 and the generated fwif header */
	CHECK(HMFV2_SZ_TRACEBUF == GF_SZ_RGXFWIF_TRACEBUF, "tracebuf size");
	CHECK(HMFV2_SZ_SYSDATA == GF_SZ_RGXFWIF_SYSDATA, "sysdata size");
	CHECK(HMFV2_SYS_FW_FAULTS == HMFV_SYS_FW_FAULTS && HMFV2_SYS_HWR_FLAGS == HMFV_SYS_HWR_FLAGS && HMFV2_SYS_POW_STATE == HMFV_SYS_POW_STATE, "anchors");
	CHECK(HMFV2_CMD_HEALTH == GF_CMD_HEALTH, "health type");
	CHECK(HMFV2_TB_ASSERT0_LINE - HMFV2_TB_ASSERT0_PATH == 2 * HMFV2_ASSERT_BYTES, "line offset");
	CHECK(HMFV2_SYS_FAULT_INFO0_LINE - HMFV2_SYS_FAULT_INFO0_PATH == 2 * HMFV2_ASSERT_BYTES, "fault line offset");
	CHECK(HMFV2_SYS_FAULT_INFO1 - HMFV2_SYS_FAULT_INFO0 == HMFV2_SZ_FWFAULTINFO, "fault stride");
	CHECK(HMFV2_SYS_OS_RUNTIME_FLAGS1 - HMFV2_SYS_OS_RUNTIME_FLAGS0 == 4, "os stride");
	CHECK(GTA_LOG_M2 == 0xc62fu, "log type 0x%x", GTA_LOG_M2);

	/* STOCK: PASS, both executed, the trace set up as stock does, nothing else changed */
	int rc = run(STOCK);
	CHECK(rc == GTA_PASS, "stock rc %d\n%s", rc, logbuf);
	CHECK(hr(gsh.tbuf + HMFV2_TB_LOG_TYPE) == 0xc62fu && hr(gsh.tbuf + HMFV2_TB_SIZE_DW) == 12000u, "trace ctl");
	CHECK(hr(gsh.tbuf + HMFV2_TB_BUFFER0) == (GTA_VA_UNCACHED | gsh.tbdata), "trace buffer fw address");
	CHECK(gsh.tbdata > gsh.tbuf && gsh.tbdata + 4u * 12000u <= gsh.sysdata, "trace buffer placed before sysdata");
	CHECK(gs_next <= (uint32_t)GF_CONFIG_HEAP_OFF, "main heap");
	CHECK(kicks == 2 && kick_bad == 0, "kicks %u bad %u", kicks, kick_bad);
	CHECK(hr(gsh.kctl + GF_CCB_W) == 2 && hr(gsh.kctl + GF_CCB_R) == 2, "ring at 2");
	CHECK(hr(gsh.kccb) == (uint32_t)GF_CMD_HEALTH && hr(gsh.kccb + GF_SZ_RGXFWIF_KCCB_CMD) == 0x2abc00ceu, "command types");
	for (uint32_t i = 4; i < GF_SZ_RGXFWIF_KCCB_CMD; i += 4) CHECK(hr(gsh.kccb + i) == 0 && hr(gsh.kccb + GF_SZ_RGXFWIF_KCCB_CMD + i) == 0, "cmd body zero at %u", i);
	CHECK(hr(gsh.fctl + GF_CCB_R) == 0, "FWCCB never acked");
	CHECK(surveys == 1, "survey once");
	CHECK(logged("M2 HEALTH PASS: STATEFLAGS_CTRL executed (CMD_EXECUTED), HEALTH_CHECK executed"), "pass line\n%s", logbuf);
	CHECK(logged("M2 boot: sys cfg 0x0 ext 0x0 pow 1; os0 rt 0x2 state ACTIVE"), "os line");
	CHECK(logged("M2 fwlog: ptr 17 wrap 0, 17 words from 0") && logged("M2 TB 0000: 70000001"), "fwlog\n%s", logbuf);
	CHECK(logged("M2 boot: assert0 empty"), "assert empty");
	if (getenv("M2_LOGFILE")) { FILE *f = fopen(getenv("M2_LOGFILE"), "w"); fputs(logbuf, f); fclose(f); }

	/* P30: what the phone showed. HEALTH consumed, STATEFLAGS read, not executed: FAIL with the firmware's own view printed */
	rc = run(P30);
	if (getenv("M2_SHOW")) fputs(logbuf, stdout);
	CHECK(rc == GTA_STOPPED, "p30 rc %d", rc);
	CHECK(aoc_stop_reason && !strcmp(aoc_stop_reason, "STATEFLAGS_CTRL read, not executed in 1 s"), "p30 reason %s", aoc_stop_reason ? aoc_stop_reason : "-");
	CHECK(logged("M2 boot: assert0 line 1234 path \"fw/main.c\" info \"os not online\""), "assert decode\n%s", logbuf);
	CHECK(logged("M2 boot: fault0 line 77 path \"fw/fault.c\""), "fault decode");
	CHECK(logged("cr poll addr 0xe230"), "cr poll");
	CHECK(logged("os0 rt 0x0 state OFFLINE"), "os offline");
	CHECK(logged("name=DEBUG_DUMP"), "fwccb capture before kick");
	CHECK(logged("M2 HEALTH FAIL: HEALTH_CHECK consumed, STATEFLAGS_CTRL read, not executed"), "fail line");
	CHECK(logged("M2 STATEFLAGS_CTRL: slot 1 read in 0 ms; return 0x0 after 1000 ms more"), "exec wait bounded\n%s", logbuf);
	CHECK(hr(gsh.fctl + GF_CCB_R) == 0, "FWCCB never acked");
	CHECK(logged("M2 HEALTH_CHECK: slot 0 read in 0 ms; return 0x0 after 50 ms more (stock waits on nothing)"), "health waits only the quiet time");

	rc = run(EXEC_ONLY_WAITED);
	CHECK(rc == GTA_PASS && logged("HEALTH_CHECK consumed"), "exec-only rc %d", rc);

	rc = run(DEAF);
	CHECK(rc == GTA_STOPPED && aoc_stop_reason && !strcmp(aoc_stop_reason, "HEALTH_CHECK not read in 1 s") && kicks == 1, "deaf: one kick, stop");
	CHECK(!logged("M2 STATEFLAGS_CTRL"), "no second command after an unread one");
	CHECK(surveys == 1 && logged("M2 fwlog"), "deaf still surveys and dumps");

	rc = run(LATE);
	CHECK(rc == GTA_PASS, "late rc %d\n%s", rc, logbuf);

	/* Ring not fresh: refuses before writing a command */
	memset(heap, 0, GF_RAW_SIZE - GF_MAIN_HEAP_OFF); loglen = 0; aoc_stop_reason = NULL; model = STOCK; kicks = 0;
	CHECK(gta_shared_init(true) == 0, "init");
	fw_start();
	hw(gsh.kctl + GF_CCB_W, 3); hw(gsh.kctl + GF_CCB_R, 3);
	CHECK(gta_m2(0x1000) == GTA_STOPPED && kicks == 0 && hr(gsh.kccb) == 0, "not fresh: no kick, no command");

	/* Rung 5's init unchanged: no trace buffer, log type 0 */
	memset(heap, 0, GF_RAW_SIZE - GF_MAIN_HEAP_OFF); memset(&gsh, 0, sizeof(gsh));
	CHECK(gta_shared_init(false) == 0 && gsh.tbdata == 0 && hr(gsh.tbuf + HMFV2_TB_LOG_TYPE) == 0 && hr(gsh.tbuf + HMFV2_TB_BUFFER0) == 0, "rung 5 init");
	CHECK(gsh.sysdata == gsh.tbuf + 0x1000u, "rung 5 sysdata right after tracebuf as before");

	fprintf(stderr, "%d checks, %d failed\n", checks, failures);
	return failures != 0;
}
