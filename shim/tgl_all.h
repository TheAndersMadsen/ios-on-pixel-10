/* SPDX-License-Identifier: MIT
 * all-r1: the sealed stage record. A mark is written and cleaned to DRAM before the step it names, so a reset leaves the last stage entered.
 * Zone: pmsg+0x1f0000, above XNU's 1 MiB msgbuf ring (pmsg+0x40000..0x140000) and clear of every other record. */
#ifndef TGL_ALL_H
#define TGL_ALL_H
#include <stdint.h>
#define TGL_ALL_RECORD_PA UINT64_C(0x955f0000)
#define TGL_ALL_RECORD_BYTES 0x1000u
#define TGL_ALL_MAGIC UINT64_C(0x31304754534c4c41)
enum { TGL_ALL_S_UFS = 1, TGL_ALL_S_UFS_DONE = 2, TGL_ALL_S_PHY = 3, TGL_ALL_S_PMC = 4, TGL_ALL_S_HS_VERIFY = 5, TGL_ALL_S_RELINK = 6, TGL_ALL_S_TOUCH = 8, TGL_ALL_S_DPU = 9, TGL_ALL_S_XNU_JUMP = 10 };
enum { TGL_ALL_ENTER = 1, TGL_ALL_DONE = 2, TGL_ALL_FAILED = 3, TGL_ALL_FELL_THROUGH = 5 };
void tgl_all_begin(uint64_t stamp_nonce, const uint8_t record_nonce[16], uint64_t epoch);
void tgl_all_mark(unsigned id, unsigned state, int32_t val);
#endif
