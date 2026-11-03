/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Host measurement program, same include set as
 * research/ios26-metal-native-20261102/firmware/tools/measure_vendor.py (pinned lga production config, DDK at 5940a317).
 * Prints offsets of the firmware-written diagnostic fields in RGXFWIF_SYSDATA and RGXFWIF_TRACEBUF that the current
 * rung-5 diagnostic does not read yet. Numbers only; no vendor code is distributed. */
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
	O("SYS_POW_STATE", RGXFWIF_SYSDATA, ePowState);
	O("SYS_OS_RUNTIME_FLAGS0", RGXFWIF_SYSDATA, aui32OsRuntimeFlagsMirror[0]);
	O("SYS_FAULT_INFO0", RGXFWIF_SYSDATA, sFaultInfo[0]);
	O("SYS_FAULT_INFO0_PATH", RGXFWIF_SYSDATA, sFaultInfo[0].sFaultBuf.szPath);
	O("SYS_FAULT_INFO0_INFO", RGXFWIF_SYSDATA, sFaultInfo[0].sFaultBuf.szInfo);
	O("SYS_FAULT_INFO0_LINE", RGXFWIF_SYSDATA, sFaultInfo[0].sFaultBuf.ui32LineNum);
	O("SYS_FW_FAULTS", RGXFWIF_SYSDATA, ui32FWFaults);
	O("SYS_CR_POLL_ADDR0", RGXFWIF_SYSDATA, aui32CrPollAddr[0]);
	O("SYS_CR_POLL_MASK0", RGXFWIF_SYSDATA, aui32CrPollMask[0]);
	O("SYS_CR_POLL_COUNT0", RGXFWIF_SYSDATA, aui32CrPollCount[0]);
	O("SYS_HWR_FLAGS", RGXFWIF_SYSDATA, ui32HWRStateFlags);
	O("SYS_FLAGS", RGXFWIF_SYSDATA, ui32FwSysDataFlags);
	O("TB_LOG_TYPE", RGXFWIF_TRACEBUF, ui32LogType);
	O("TB_TRACE_POINTER0", RGXFWIF_TRACEBUF, sTraceBuf[0].ui32TracePointer);
	O("TB_WRAP0", RGXFWIF_TRACEBUF, sTraceBuf[0].ui32WrapCount);
	O("TB_ASSERT0_PATH", RGXFWIF_TRACEBUF, sTraceBuf[0].sAssertBuf.szPath);
	O("TB_ASSERT0_INFO", RGXFWIF_TRACEBUF, sTraceBuf[0].sAssertBuf.szInfo);
	O("TB_ASSERT0_LINE", RGXFWIF_TRACEBUF, sTraceBuf[0].sAssertBuf.ui32LineNum);
	O("TB_SIZE_DW", RGXFWIF_TRACEBUF, ui32TraceBufSizeInDWords);
	O("TB_FLAGS", RGXFWIF_TRACEBUF, ui32TracebufFlags);
	V("ASSERT_BYTES", RGXFW_TRACE_BUFFER_ASSERT_SIZE);
	V("THREAD_NUM", RGXFW_THREAD_NUM);
	V("OS_STATE_MASK", ~RGXFWIF_OS_RUNTIME_FLAGS_OS_STATE_CLRMSK);
	V("MAX_NUM_OSIDS", RGXFW_MAX_NUM_OSIDS);
	return 0;
}
