/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Host measurement program for the M3 S1 rung (blazer_gpu_tipc=7, coremem only;
 * research/ios26-gpu-native-r1/COREMEM-INIT.md). Same include set as m2/tools/fw_layout_r2.c and m3/tools/fw_layout_r3.c
 * (pinned lga production config_kernel.h, DDK at 5940a317). Emits only what S1 writes or counts: the sysinit coremem-data DMA
 * field, the raw firmware heap, the HWR flag bits, the FWCCB fault-type commands and the firmware log ids of an init fault.
 * No client context, CCB or KICK constant: those belong to a later lane. Numbers only; no vendor code is copied into the kernel. */
#include <stdio.h>
#include <stddef.h>
#include <stdbool.h>
#include "config_kernel.h"
#include "img_types.h"
#include "img_defs.h"
#include "rgx_fwif_km.h"
#include "rgx_heap_firmware.h"
#include "rgx_riscv.h"
#include "rgx_fwif_sf.h"
#define O(n, t, f) printf("#define HMFS1_%s 0x%zxu\n", n, offsetof(t, f))
#define S(n, t) printf("#define HMFS1_SZ_%s 0x%zxu\n", n, sizeof(t))
#define V(n, v) printf("#define HMFS1_%s 0x%llxULL\n", n, (unsigned long long)(v))
int main(void)
{
	S("SYSINIT", RGXFWIF_SYSINIT);
	S("FWCCB_CMD", RGXFWIF_FWCCB_CMD);
	/* RGXSetupFwSysData: RGXSetMetaDMAAddress(&sCorememDataStoreDeprecated, coremem data memdesc, 0) */
	O("SI_COREMEM_DATA_STORE", RGXFWIF_SYSINIT, sCorememDataStoreDeprecated);
	S("DMA_ADDR", RGXFWIF_DMA_ADDR);
	O("SI_FIRMWARE_PERF", RGXFWIF_SYSINIT, eFirmwarePerf);
	O("SI_MARKER", RGXFWIF_SYSINIT, ui32MarkerVal);
	V("RAW_HEAP_BASE", RGX_FIRMWARE_RAW_HEAP_BASE);
	V("RAW_HEAP_SIZE", RGX_FIRMWARE_RAW_HEAP_SIZE);
	/* sysdata ui32HWRStateFlags bits */
	V("HWR_HARDWARE_OK", RGXFWIF_HWR_HARDWARE_OK);
	V("HWR_RESET_IN_PROGRESS", RGXFWIF_HWR_RESET_IN_PROGRESS);
	V("HWR_GENERAL_LOCKUP", RGXFWIF_HWR_GENERAL_LOCKUP);
	V("HWR_DM_STALLING", RGXFWIF_HWR_DM_STALLING);
	V("HWR_FW_FAULT", RGXFWIF_HWR_FW_FAULT);
	V("HWR_RESTART_REQUESTED", RGXFWIF_HWR_RESTART_REQUESTED);
	/* FWCCB command types that report an init fault */
	V("FWCCB_DEBUG_DUMP", RGXFWIF_FWCCB_CMD_DEBUG_DUMP);
	V("FWCCB_CONTEXT_RESET", RGXFWIF_FWCCB_CMD_CONTEXT_RESET_NOTIFICATION);
	V("FWCCB_GPU_RESTART", RGXFWIF_FWCCB_CMD_REQUEST_GPU_RESTART);
	V("FWCCB_FW_PF", RGXFWIF_FWCCB_CMD_CONTEXT_FW_PF_NOTIFICATION);
	/* Firmware log: entry = id, timestamp hi, timestamp lo, RGXFW_SF_PARAMNUM(id) params; RGXFW_LOG_VALIDID */
	V("SF_IDMASK", RGXFW_LOG_IDMASK);
	V("SF_IDMARKER", RGXFW_LOG_IDMARKER);
	V("SF_PARAMNUM_SHIFT", 16U);
	V("SF_PARAMNUM_MASK", 0xfU);
	V("SF_MMU_FAULT_EVENT", RGXFW_SF_HWR_MMU_FAULT_EVENT);
	V("SF_CORE_MMU_FAULT", RGXFW_SF_HWR_CORE_MMU_FAULT);
	V("SF_CORE_MMU_FAULT_S7", RGXFW_SF_HWR_CORE_MMU_FAULT_S7);
	V("SF_HIT_LOCKUP", RGXFW_SF_MAIN_HWR_HIT_LOCKUP);
	V("SF_HIT_LOCKUP_DM", RGXFW_SF_MAIN_HWR_HIT_LOCKUP_DM);
	V("SF_HIT_LOCKUP_DEPRECATED", RGXFW_SF_MAIN_HWR_HIT_LOCKUP_DEPRECATED);
	V("SF_FAILED_HW_POLL", RGXFW_SF_HWR_FAILED_HW_POLL);
	V("SF_START_HW_RESET", RGXFW_SF_HWR_START_HW_RESET);
	V("SF_ASSERT_FAILED", RGXFW_SF_MAIN_ASSERT_FAILED);
	V("SF_KCCBCMD_EXEC", RGXFW_SF_MTS_KCCBCMD_EXEC);
	V("SF_KCCBCMD_RTN_VALUE", RGXFW_SF_MTS_KCCBCMD_RTN_VALUE);
	return 0;
}
