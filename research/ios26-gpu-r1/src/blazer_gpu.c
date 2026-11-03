#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * Stage 1 of the GPU work: the smallest physical proof. Off unless boot-arg blazer_gpu=1. One shot, 30 s after bsd_init, from a thread.
 * Order, and what each step stands on. Nothing of the GPU is mapped or touched before the step that powers it:
 *   1 CPM queue: SET sswrp GPU on. The frame the shim's DPU vote ran, physical, with id 20 for 5. Same order as power_controller_main.c send_power_request
 *   2 Wait for LPB's event: the domain is on. Only now is anything in it mapped: FDT power-domains of gpu_core_logic_pd and gpu_pf_state is sswrp_gpu_pd
 *   3 gpu_control 0x3480a000: write 0 (GATE_ON), poll bit 0|1, at most 10 ms: gpu_core_logic.c, "must be the first step". Its write comes before any read of it, as there
 *   4 pfsm status 0x34813008, read: gpu_pf_state.c P25 offsets. The core has a clock if STATE_VALID with no error. Without it, stop before the core: stock may have set a state first
 *   5 rgx 0x34f00020, high word then low, as OSReadUncheckedHWReg64: CORE_ID, rgx_cr_defs_km.h, read twice. rgx_bvnc_table_km.h: 71.2.2448.1212 is 0x00470002099004bc
 *   6 gpu_control write 8 (GATE_OFF), poll; SET off, wait for LPB's event
 * Left out on purpose, each stock does: TMSS and DTS (thermal sensors, gpu_core_logic.c v2: inferred not needed for a register read; GPU is idle and on for milliseconds), PF state write,
 * fabric vote 0x05361500 (memory traffic only, inferred; this reads CSRs), SMMU, interrupts, firmware, Trusty. No PMIC frame, polled or queued. No SMC.
 * Any failure: one line, nothing further goes out. A failed step 3 or later leaves the domain on until the boot's deadline: stock has no recovery for it either.
 * Facts from GPL-2.0 google-modules (GrapheneOS kernel_pixel_6.12 @5940a317) and Dual MIT/GPL pvrsrvkm: numbers only, no code copied.
 * blazer_gpu=3: stage 1, and between steps 5 and 6 a read-only survey (gpu_survey below): the registers stock's REE debug dump reads with plain
 * OSReadHWReg (rgxdebug_common.c RGXDumpRGXRegisters, volcanic/rgxdebug.c Clk/MMU/SLC parts; none of its DDLOGSECURE, FW core or RISC-V DM reads),
 * and RGX_CR_TIMER twice 1 ms apart: does the core's clock tick with our power-up. Reads only, a 64 KiB view of rgx, no write beyond stage 1's. */
#ifdef BLAZER_GPU_HOSTTEST
#include "blazer_gpu_test.h"
#else
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <machine/machine_routines.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include "blazer_cpmq_xnu.h"

extern void IOSleep(unsigned milliseconds);
extern kern_return_t thread_terminate(thread_t thread);
extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern void delay(int usec);
#endif

void blazer_gpu_start(void);

#define GPU_CONTROL_PA      0x3480a000ULL   /* FDT gpu_core_logic_pd reg gpu_control */
#define GPU_PFSM_PA         0x34813000ULL   /* FDT gpu0 reg pfsm, gpu_pf_state reg pfsm-ns */
#define GPU_SMMU_PA         0x34c00000ULL   /* FDT gpu_smmu. power-domains is sswrp_gpu_pd. blazer_gpu=2 only, reads only */
#define GPU_RGX_PA          0x34f00000ULL   /* FDT gpu0 reg rgx. Only its first page is mapped */
#define GPU_GATE_ON         0x0u            /* GPU_CONTROL_POWER_GATE_ON_VALUE */
#define GPU_GATE_OFF        0x8u            /* GPU_CONTROL_POWER_GATE_OFF_VALUE */
#define GPU_ACK_MASK        0x3u            /* POWER_OFF_ACK | POWER_GATE_ACK */
#define GPU_ACK_POLLS       100u            /* at 100 us: GPU_CONTROL_ACK_TIMEOUT_US */
#define PFSM_STATUS         0x8u            /* gpu_pf_state_dev_desc_p25 */
#define PFSM_VALID          (1u << 5)
#define PFSM_ERRORS         ((1u << 8) | (1u << 9))
#define RGX_CORE_ID         0x20u           /* RGX_CR_CORE_ID */
#define CORE_ID_EXPECT      0x00470002099004bcULL
#define LPB_OK              0xfu            /* CPM_COMMON_PROT_NO_ERR, and LPB_SERVICE_CMD_SUCCESS in the next word */
#define LPB_PWRDN_STARTED   0x11u
#define LPB_PWRUP_STARTED   0x12u
#define LPB_EVENT_ON        0u
#define LPB_EVENT_OFF       1u
#define LPB_TIMEOUT_MS      3000u           /* tgl_display_power.c, physical */

#ifdef BLAZER_GPU_HOSTTEST_BUS
/* Host test only: the test's bus model sees every access */
#define gpu_w32(va, value) blazer_gpu_test_w32((va), (value))
#define gpu_r32(va) blazer_gpu_test_r32(va)
#else
static inline void
gpu_w32(vm_offset_t va, uint32_t value)
{
	__asm__ volatile ("dsb sy" ::: "memory");
	*(volatile uint32_t *)va = value;
	__asm__ volatile ("dsb sy" ::: "memory");
}

static inline uint32_t
gpu_r32(vm_offset_t va)
{
	return *(volatile uint32_t *)va;
}
#endif

static unsigned gpu_mode = 1;

/* blazer_gpu=2. SMMUv3 registers as the non-secure view gives them, after the core has answered, so the domain and its bus are proved first. Writes nothing.
 * The question for firmware boot: does the GPU's traffic pass, as amb_smmu's does in global bypass, or abort? Offsets: Arm SMMUv3 */
static void
gpu_smmu_survey(void)
{
	static const struct { uint16_t off; const char *name; } regs[] = {
		{ 0x00, "IDR0" }, { 0x20, "CR0" }, { 0x24, "CR0ACK" }, { 0x28, "CR1" }, { 0x2c, "CR2" }, { 0x44, "GBPA" }, { 0x60, "GERROR" }, { 0x80, "STRTAB_BASE_LO" }, { 0x84, "STRTAB_BASE_HI" }, { 0x88, "STRTAB_BASE_CFG" },
	};
	vm_offset_t smmu = ml_io_map((vm_offset_t)GPU_SMMU_PA, 0x1000);

	if (smmu == 0) {
		printf("blazer-gpu: no SMMU map\n");
		return;
	}
	for (unsigned i = 0; i < sizeof(regs) / sizeof(regs[0]); i++) {
		printf("blazer-gpu: smmu %s 0x%x\n", regs[i].name, gpu_r32(smmu + regs[i].off));
	}
}

/* blazer_gpu=3. Offsets: volcanic/km/rgx_cr_defs_km.h at the pin; 71.V.2448.1212 has no ERYX_TOP_INFRASTRUCTURE (so CLK_CTRL0/1/2, BIF_*) and
 * no BRN72144 (so MMU_FAULT_STATUS1/2 are read unconditionally by stock). 64-bit ones as two words, high first, the access CORE_ID already passed with */
#define GPU_SURVEY_BYTES    0x10000u        /* every offset below is under it */
#define RGX_TIMER           0x160u          /* RGX_CR_TIMER: VALUE bits 0..47, bit 63 BIT31 */
#define RGX_TIMER_VALUE     0x0000ffffffffffffULL
#define GPU_TIMER_GAP_US    1000

struct gpu_survey_reg {
	uint16_t off;
	uint8_t wide;
	const char *name;
};

static const struct gpu_survey_reg gpu_survey_regs[] = {
	{ 0x0020, 1, "CORE_ID" },               /* RGXDumpCoreRegisters */
	{ 0x0000, 1, "CLK_CTRL0" },             /* RGXDumpClkRegisters, !ERYX_TOP */
	{ 0x0008, 1, "CLK_STATUS0" },
	{ 0x0080, 1, "CLK_CTRL1" },
	{ 0x0088, 1, "CLK_STATUS1" },
	{ 0x0090, 0, "CLK_CTRL2" },
	{ 0x0130, 0, "EVENT_STATUS" },          /* RGXDumpRGXRegisters */
	{ 0xe130, 1, "MMU_FAULT_STATUS_PM" },   /* RGXDumpMMURegisters */
	{ 0xe150, 1, "MMU_FAULT_STATUS1" },
	{ 0xe158, 1, "MMU_FAULT_STATUS2" },
	{ 0xe160, 1, "MMU_FAULT_STATUS_META" },
	{ 0xe170, 1, "MMU_STATUS" },
	{ 0xe210, 1, "SLC_STATUS1" },
	{ 0xe218, 1, "SLC_STATUS2" },
	{ 0xe238, 1, "SLC_STATUS3" },
	{ 0xe260, 1, "SLC_STATUS_DEBUG" },
	{ 0xe230, 0, "SLC_IDLE" },              /* RGXDumpSLCRegisters, no MTX_SLC */
	{ 0xe240, 0, "SLC_FAULT_STOP_STATUS" },
};

static uint64_t
gpu_r64(vm_offset_t base, uint32_t off)
{
	uint64_t high = gpu_r32(base + off + 4);

	return high << 32 | gpu_r32(base + off);
}

/* A 64-bit counter read as two words: take the low word only between two equal high words, at most three tries */
static int
gpu_timer(vm_offset_t rgx, uint64_t *out)
{
	for (unsigned n = 0; n < 3; n++) {
		uint32_t high = gpu_r32(rgx + RGX_TIMER + 4), low = gpu_r32(rgx + RGX_TIMER);

		if (gpu_r32(rgx + RGX_TIMER + 4) == high) {
			*out = ((uint64_t)high << 32 | low) & RGX_TIMER_VALUE;
			return 0;
		}
	}
	return -1;
}

/* Reads only. One line per register, then the clock verdict. Never stops the sequence: the power-down after it runs either way */
static void
gpu_survey(void)
{
	vm_offset_t rgx = ml_io_map((vm_offset_t)GPU_RGX_PA, GPU_SURVEY_BYTES);
	uint64_t t0 = 0, t1 = 0;

	if (rgx == 0) {
		printf("blazer-gpu: survey: no map\n");
		return;
	}
	for (unsigned i = 0; i < sizeof(gpu_survey_regs) / sizeof(gpu_survey_regs[0]); i++) {
		const struct gpu_survey_reg *r = &gpu_survey_regs[i];

		if (r->wide) {
			printf("blazer-gpu: reg %s +0x%x 0x%016llx\n", r->name, r->off, gpu_r64(rgx, r->off));
		} else {
			printf("blazer-gpu: reg %s +0x%x 0x%08x\n", r->name, r->off, gpu_r32(rgx + r->off));
		}
	}
	if (gpu_timer(rgx, &t0) != 0) {
		printf("blazer-gpu: TIMER UNSTABLE high word\n");
		return;
	}
	delay(GPU_TIMER_GAP_US);
	if (gpu_timer(rgx, &t1) != 0) {
		printf("blazer-gpu: TIMER UNSTABLE high word\n");
		return;
	}
	printf("blazer-gpu: %s timer 0x%llx -> 0x%llx, +%llu in %u us\n", t1 > t0 ? "CLOCK_RUNS" : "CLOCK_STOPPED", t0, t1,
	    t1 > t0 ? t1 - t0 : 0ULL, (unsigned)GPU_TIMER_GAP_US);
	printf("blazer-gpu: survey done, %u registers\n", (unsigned)(sizeof(gpu_survey_regs) / sizeof(gpu_survey_regs[0])));
}

static int
gpu_vote(uint32_t on)
{
	const uint32_t body[CPMQ_WORDS - 1] = { CPMQ_LPB_SET, CPMQ_LPB_GPU, on };
	uint32_t reply[CPMQ_WORDS] = { 0, 0, 0, 0 }, waits = 0, id = 0, event = 0;
	int rc;

	blazer_cpmq_lpb_arm();
	rc = blazer_cpmq_call(CPMQ_SRC_POWER, CPMQ_DST_LPB, body, reply, LPB_TIMEOUT_MS, &waits);
	if (rc != CPMQ_OK) {
		printf("blazer-gpu: STOP vote %u: %s\n", on, cpmq_rc_name(rc));
		return -1;
	}
	printf("blazer-gpu: vote %u reply 0x%x 0x%x 0x%x after %u ms\n", on, reply[1], reply[2], reply[3], waits);
	if (reply[1] != LPB_OK || reply[3] != CPMQ_LPB_GPU) {
		printf("blazer-gpu: STOP vote %u refused\n", on);
		return -1;
	}
	if (reply[2] == LPB_OK) {
		/* Stock takes this as done with no event. For on, it says something else held the domain: nothing here expects that, so stop rather than use it */
		printf("blazer-gpu: %s vote %u had no transition\n", on ? "STOP" : "note:", on);
		return on ? -1 : 0;
	}
	if (reply[2] != (on ? LPB_PWRUP_STARTED : LPB_PWRDN_STARTED)) {
		printf("blazer-gpu: STOP vote %u status 0x%x\n", on, reply[2]);
		return -1;
	}
	rc = blazer_cpmq_lpb_wait(&id, &event, LPB_TIMEOUT_MS);
	if (rc != CPMQ_OK || id != CPMQ_LPB_GPU || event != (on ? LPB_EVENT_ON : LPB_EVENT_OFF)) {
		printf("blazer-gpu: STOP vote %u event %s id %u value %u\n", on, cpmq_rc_name(rc), id, event);
		return -1;
	}
	return 0;
}

/* Two words, high first: OSReadUncheckedHWReg64 */
static uint64_t
gpu_core_id(vm_offset_t rgx)
{
	uint64_t high = gpu_r32(rgx + RGX_CORE_ID + 4);

	return high << 32 | gpu_r32(rgx + RGX_CORE_ID);
}

static int
gpu_gate(vm_offset_t control, uint32_t value, uint32_t *seen)
{
	gpu_w32(control, value);
	for (unsigned n = 0; n < GPU_ACK_POLLS; n++) {
		*seen = gpu_r32(control);
		if (*seen & GPU_ACK_MASK) {
			return 0;
		}
		delay(100);
	}
	printf("blazer-gpu: STOP gate 0x%x no ack, control 0x%x\n", value, *seen);
	return -1;
}

static void
gpu_proof(void)
{
	vm_offset_t control, pfsm, rgx;
	uint32_t seen = 0, status;
	uint64_t first, second;

	if (gpu_vote(1) != 0) {
		return;
	}
	control = ml_io_map((vm_offset_t)GPU_CONTROL_PA, 0x1000);
	pfsm = ml_io_map((vm_offset_t)GPU_PFSM_PA, 0x1000);
	rgx = ml_io_map((vm_offset_t)GPU_RGX_PA, 0x1000);
	if (control == 0 || pfsm == 0 || rgx == 0) {
		printf("blazer-gpu: STOP cannot map\n");
		return;
	}
	printf("blazer-gpu: domain on\n");
	if (gpu_gate(control, GPU_GATE_ON, &seen) != 0) {
		return;
	}
	printf("blazer-gpu: core logic on, control 0x%x\n", seen);
	status = gpu_r32(pfsm + PFSM_STATUS);
	printf("blazer-gpu: pfsm status 0x%x\n", status);
	if (!(status & PFSM_VALID) || (status & PFSM_ERRORS)) {
		/* Not known to have a clock. No read of the core. Power down as stock would */
		printf("blazer-gpu: NO_CLOCK core not read\n");
	} else {
		first = gpu_core_id(rgx);
		second = gpu_core_id(rgx);
		printf("blazer-gpu: %s core id 0x%llx 0x%llx, expected 0x%llx\n", first == CORE_ID_EXPECT && second == first ? "PASS" : "MISMATCH",
		    first, second, CORE_ID_EXPECT);
		if (gpu_mode == 2 && first == CORE_ID_EXPECT && second == first) {
			gpu_smmu_survey();
		}
		if (gpu_mode == 3 && first == CORE_ID_EXPECT && second == first) {
			gpu_survey();
		}
	}
	if (gpu_gate(control, GPU_GATE_OFF, &seen) != 0) {
		return;
	}
	printf("blazer-gpu: core logic off, control 0x%x\n", seen);
	if (gpu_vote(0) == 0) {
		printf("blazer-gpu: domain off, done\n");
	}
}

/* For blazer_gpu_tipc=4,5: the domain on, core logic on, the clock valid and the core identified, then left on. rgx's first page mapped. The boot ends with a panic: nothing powers this off */
int blazer_gpu_power_on(vm_offset_t *rgx_out);

int
blazer_gpu_power_on(vm_offset_t *rgx_out)
{
	vm_offset_t control, pfsm, rgx;
	uint32_t seen = 0, status;
	uint64_t id;

	if (gpu_vote(1) != 0) {
		return -1;
	}
	control = ml_io_map((vm_offset_t)GPU_CONTROL_PA, 0x1000);
	pfsm = ml_io_map((vm_offset_t)GPU_PFSM_PA, 0x1000);
	rgx = ml_io_map((vm_offset_t)GPU_RGX_PA, 0x1000);
	if (control == 0 || pfsm == 0 || rgx == 0 || gpu_gate(control, GPU_GATE_ON, &seen) != 0) {
		return -1;
	}
	status = gpu_r32(pfsm + PFSM_STATUS);
	printf("blazer-gpu: control 0x%x pfsm 0x%x\n", seen, status);
	if (!(status & PFSM_VALID) || (status & PFSM_ERRORS)) {
		return -1;
	}
	id = gpu_core_id(rgx);
	printf("blazer-gpu: core id 0x%llx\n", id);
	if (id != CORE_ID_EXPECT) {
		return -1;
	}
	*rgx_out = rgx;
	return 0;
}

#ifndef BLAZER_GPU_HOSTTEST
__dead2 static void
gpu_thread(void *arg __unused, wait_result_t wr __unused)
{
	IOSleep(30 * 1000);
	gpu_proof();
	thread_terminate(current_thread());
	__builtin_unreachable();
}

void
blazer_gpu_start(void)
{
	thread_t thread;
	unsigned mode = 0;

	if (!PE_parse_boot_argn("blazer_gpu", &mode, sizeof(mode)) || mode < 1 || mode > 3) {
		return;
	}
	gpu_mode = mode;
	if (kernel_thread_start(gpu_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
		printf("blazer-gpu: stage 1 in 30 s\n");
	}
}
#else
void gpu_proof_for_test(unsigned mode) { gpu_mode = mode; gpu_proof(); }
#endif
#endif /* BLAZER */
