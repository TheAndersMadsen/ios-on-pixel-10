/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Host measurement program for M2 (research/ios26-gpu-r1/M2.md), same include set as
 * tools/fw_layout_r1.c (pinned lga production config, DDK at 5940a317). r1's fields plus what rung 6 reads or writes:
 * the trace buffer pointer and size, the per-OS runtime-flag stride, sysdata config flags, the KCCB command types. Numbers only. */
#include <stdio.h>
#include <stddef.h>
#include <stdbool.h>
#include "config_kernel.h"
#include "img_types.h"
#include "img_defs.h"
#include "rgx_fwif_km.h"
#define O(n, t, f) printf("#define HMFV2_%s 0x%zxu\n", n, offsetof(t, f))
#define S(n, t) printf("#define HMFV2_SZ_%s 0x%zxu\n", n, sizeof(t))
#define V(n, v) printf("#define HMFV2_%s 0x%llxULL\n", n, (unsigned long long)(v))
int main(void)
{
	S("SYSDATA", RGXFWIF_SYSDATA);
	S("TRACEBUF", RGXFWIF_TRACEBUF);
	S("FILE_INFO_BUF", RGXFWIF_FILE_INFO_BUF);
	S("FWFAULTINFO", RGX_FWFAULTINFO);
	S("TRACEBUF_SPACE", RGXFWIF_TRACEBUF_SPACE);
	O("SYS_CONFIG_FLAGS", RGXFWIF_SYSDATA, ui32ConfigFlags);
	O("SYS_CONFIG_FLAGS_EXT", RGXFWIF_SYSDATA, ui32ConfigFlagsExt);
	O("SYS_POW_STATE", RGXFWIF_SYSDATA, ePowState);
	O("SYS_OS_RUNTIME_FLAGS0", RGXFWIF_SYSDATA, aui32OsRuntimeFlagsMirror[0]);
	O("SYS_OS_RUNTIME_FLAGS1", RGXFWIF_SYSDATA, aui32OsRuntimeFlagsMirror[1]);
	O("SYS_FAULT_INFO0", RGXFWIF_SYSDATA, sFaultInfo[0]);
	O("SYS_FAULT_INFO1", RGXFWIF_SYSDATA, sFaultInfo[1]);
	O("SYS_FAULT_INFO0_PATH", RGXFWIF_SYSDATA, sFaultInfo[0].sFaultBuf.szPath);
	O("SYS_FAULT_INFO0_INFO", RGXFWIF_SYSDATA, sFaultInfo[0].sFaultBuf.szInfo);
	O("SYS_FAULT_INFO0_LINE", RGXFWIF_SYSDATA, sFaultInfo[0].sFaultBuf.ui32LineNum);
	O("SYS_FAULT_INFO0_DATA", RGXFWIF_SYSDATA, sFaultInfo[0].ui64Data);
	O("SYS_FW_FAULTS", RGXFWIF_SYSDATA, ui32FWFaults);
	O("SYS_CR_POLL_ADDR0", RGXFWIF_SYSDATA, aui32CrPollAddr[0]);
	O("SYS_CR_POLL_MASK0", RGXFWIF_SYSDATA, aui32CrPollMask[0]);
	O("SYS_CR_POLL_COUNT0", RGXFWIF_SYSDATA, aui32CrPollCount[0]);
	O("SYS_TS_MIRROR0", RGXFWIF_SYSDATA, aui32TSMirror[0]);
	O("SYS_HWR_FLAGS", RGXFWIF_SYSDATA, ui32HWRStateFlags);
	O("SYS_FLAGS", RGXFWIF_SYSDATA, ui32FwSysDataFlags);
	O("TB_LOG_TYPE", RGXFWIF_TRACEBUF, ui32LogType);
	O("TB_TRACE_POINTER0", RGXFWIF_TRACEBUF, sTraceBuf[0].ui32TracePointer);
	O("TB_WRAP0", RGXFWIF_TRACEBUF, sTraceBuf[0].ui32WrapCount);
	O("TB_BUFFER0", RGXFWIF_TRACEBUF, sTraceBuf[0].pui32RGXFWIfTraceBuffer);
	O("TB_ASSERT0_PATH", RGXFWIF_TRACEBUF, sTraceBuf[0].sAssertBuf.szPath);
	O("TB_ASSERT0_INFO", RGXFWIF_TRACEBUF, sTraceBuf[0].sAssertBuf.szInfo);
	O("TB_ASSERT0_LINE", RGXFWIF_TRACEBUF, sTraceBuf[0].sAssertBuf.ui32LineNum);
	O("TB_SIZE_DW", RGXFWIF_TRACEBUF, ui32TraceBufSizeInDWords);
	O("TB_FLAGS", RGXFWIF_TRACEBUF, ui32TracebufFlags);
	O("KC_FLAGS", RGXFWIF_KCCB_CMD, ui32KCCBFlags);
	V("ASSERT_BYTES", RGXFW_TRACE_BUFFER_ASSERT_SIZE);
	V("THREAD_NUM", RGXFW_THREAD_NUM);
	V("OS_STATE_MASK", ~RGXFWIF_OS_RUNTIME_FLAGS_OS_STATE_CLRMSK);
	V("MAX_NUM_OSIDS", RGXFW_MAX_NUM_OSIDS);
	V("FAULTINFO_MAX", RGXFWIF_FWFAULTINFO_MAX);
	V("TB_DEFAULT_DW", RGXFW_TRACE_BUF_DEFAULT_SIZE_IN_DWORDS);
	V("TB_MIN_DW", RGXFW_TRACE_BUF_MIN_SIZE_IN_DWORDS);
	V("LOG_TYPE_TRACE", RGXFWIF_LOG_TYPE_TRACE);
	V("LOG_TYPE_GROUP_MASK", RGXFWIF_LOG_TYPE_GROUP_MASK);
	V("LOG_M2_GROUPS", RGXFWIF_LOG_TYPE_GROUP_MAIN | RGXFWIF_LOG_TYPE_GROUP_MTS | RGXFWIF_LOG_TYPE_GROUP_CLEANUP | RGXFWIF_LOG_TYPE_GROUP_BIF |
	    RGXFWIF_LOG_TYPE_GROUP_POW | RGXFWIF_LOG_TYPE_GROUP_HWR | RGXFWIF_LOG_TYPE_GROUP_MISC | RGXFWIF_LOG_TYPE_GROUP_VZ);
	V("CMD_HEALTH", RGXFWIF_KCCB_CMD_HEALTH_CHECK);
	V("CMD_STATEFLAGS", RGXFWIF_KCCB_CMD_STATEFLAGS_CTRL);
	V("RTN_EXECUTED", RGXFWIF_KCCB_RTN_SLOT_CMD_EXECUTED);
	V("RTN_POLL_FAILURE", RGXFWIF_KCCB_RTN_SLOT_POLL_FAILURE);
	V("INICFG_ALL", RGXFWIF_INICFG_ALL);
	return 0;
}
