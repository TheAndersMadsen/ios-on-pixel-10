/* SPDX-License-Identifier: MIT
 * display-frame-r1: one shim-only boot. DSI0 and panel as display-dcs-r2, then a DPU test pattern through DSC with a command-mode kick. No FE, SMMU, RAM fetch or panel reset.
 * Every MMIO goes through an allowlist and a write-ahead record, so a reset keeps the prefix. See EXPERIMENT.md. */
#ifndef TGL_DCS_H
#define TGL_DCS_H
#include <stdint.h>
/* Moved off the UFS route's READ_RECORD_PA. Display's stated free range, ends before the XNU msgbuf header. */
#define TGL_DCS_RECORD_PA UINT64_C(0x95438000)
#define TGL_DCS_RECORD_BYTES 0x6000u
#define TGL_DCS_ENTRY_BYTES 16u
#define TGL_DCS_HEADER_BYTES 64u
#define TGL_DCS_CAPACITY ((TGL_DCS_RECORD_BYTES - TGL_DCS_HEADER_BYTES) / TGL_DCS_ENTRY_BYTES)
#define TGL_DCS_STAGE_ID 0x00d0u /* stamp stage */
enum { DCS_K_STAGE = 1, DCS_K_RD_INTENT, DCS_K_RD, DCS_K_WR_INTENT, DCS_K_POLL, DCS_K_NOTE, DCS_K_STOP, DCS_K_END, DCS_K_SLOT };
enum { DCS_S_ADMIT = 0, DCS_S_A_TOP, DCS_S_B_DSI0, DCS_S_C_CLOCKS, DCS_S_D_FIRST_READ, DCS_S_E_HOST_PHY, DCS_S_F_PANEL, DCS_S_G_PANEL_READ, DCS_S_H_FE0, DCS_S_I_DPU_READ, DCS_S_J_ISOLATION, DCS_S_K_DPU_CONFIG, DCS_S_L_PANEL_DSC, DCS_S_M_FRAMES, DCS_S_N_DONE, DCS_S_T_TE_PAD, DCS_S_S_SMMU, DCS_S_F0_LAYER };
enum { DCS_C_OK = 0, DCS_C_REFUSED_PA, DCS_C_FAULT, DCS_C_SERROR, DCS_C_BUDGET, DCS_C_RECORD_FULL, DCS_C_MAGIC, DCS_C_MBA_TIMEOUT, DCS_C_TOP_REPLY, DCS_C_TOP_STATE,
       DCS_C_LPCM_REPLY, DCS_C_RATE, DCS_C_DEAD_REG, DCS_C_PHY_POLL, DCS_C_MODE, DCS_C_CRI_BUSY, DCS_C_NO_PANEL_REPLY, DCS_C_PANEL_ID, DCS_C_DCS_REFUSED, DCS_C_WDT, DCS_C_GUARD_FAULT, DCS_C_CHIP, DCS_C_ISOLATION, DCS_C_PPS, DCS_C_NO_FRAME_DONE, DCS_C_BAD_BUFFER, DCS_C_SMMU_ON, DCS_C_SMMU_ABORT, DCS_C_FE_BUS };
enum { DCS_N_TOP_STATE_BEFORE = 1, DCS_N_TOP_SET_STATUS, DCS_N_TOP_STATE_AFTER, DCS_N_RATE_PIX_BEFORE, DCS_N_RATE_REF_BEFORE, DCS_N_RATE_PIX, DCS_N_RATE_REF, DCS_N_CORE_ID, DCS_N_VERSION,
       DCS_N_PHY_STATUS, DCS_N_MODE_STATUS, DCS_N_TX_LP, DCS_N_POWER_MODE, DCS_N_POWER_MODE_AFTER, DCS_N_ERR_COUNT, DCS_N_ID_DA, DCS_N_ID_DB, DCS_N_ID_DC, DCS_N_ID_A1, DCS_N_ACK_REPORT,
       DCS_N_READ_FAIL, DCS_N_ESR, DCS_N_FAR, DCS_N_WDT_STOP, DCS_N_INT_MAIN, DCS_N_INT_ACK, DCS_N_INT_TO, DCS_N_INT_PHY, DCS_N_INT_CRI, DCS_N_MBA_R0, DCS_N_MBA_R1, DCS_N_MBA_R2, DCS_N_MBA_R3, DCS_N_ISR,
       DCS_N_COMPRESSION, DCS_N_BRIGHTNESS, DCS_N_PPS_BEFORE, DCS_N_PPS_AFTER, DCS_N_OPR, DCS_N_POST_OUT, DCS_N_ISO_BEFORE, DCS_N_ISO_AFTER, DCS_N_CHIP_ID, DCS_N_CHIP_REV, DCS_N_PRODUCT_ID, DCS_N_CUSTOMER, DCS_N_TE_SEEN, DCS_N_FRAME_STATUS, DCS_N_CRC, DCS_N_ERR_COUNT_AFTER, DCS_N_PAD_PARAM, DCS_N_PAD_DMUX, DCS_N_PAD_TXDATA, DCS_N_PAD_RXDATA, DCS_N_PAD_WRITTEN, DCS_N_TE_SEEN_AFTER, DCS_N_SMMU, DCS_N_FILL_MS, DCS_N_FE0_STATUS, DCS_N_PPS_BEFORE_SAME, DCS_N_PPS_BYTE89, DCS_N_SMMU_BYPASS_SET,
       DCS_N_BRIGHT_TARGET, DCS_N_BRIGHT_AT_WRITE, DCS_N_BRIGHT_SETTLED, DCS_N_BRIGHT_ERR_COUNT, DCS_N_BRIGHT_POWER, DCS_N_BRIGHT_RESULT };
enum { DCS_BR_OK = 1, DCS_BR_MISMATCH, DCS_BR_NO_READBACK, DCS_BR_PANEL_NOT_UP };
#ifndef TGL_FRAME_RUNG
#define TGL_FRAME_RUNG 2 /* 1: FE0 power and DPU reads only, no DPU write. 2: test-pattern frame. 3: FE0 layer scanout from RAM. */
#endif
#ifndef TGL_DCS_BRIGHT
#define TGL_DCS_BRIGHT 0 /* 1: stage G writes DCS 0x51 once, before any DPU access, and reads it back. ios26-bright-r1. */
#endif
#define TGL_FRAME_SLOTS 6u
#define TGL_FRAME_KICKS 3u
#define TGL_FRAME_GAP_MS 20u
#define TGL_FRAME_DWELL_MS 700u
/* Open the record. Call once, before any access. */
void tgl_dcs_begin(uint64_t stamp_nonce, const uint8_t record_nonce[16], uint64_t epoch);
/* Run A..H. Returns the stop code; the record holds the detail. */
int tgl_dcs_run(void);
void tgl_dcs_finish(int code, uint64_t esr, uint64_t far, uint64_t wdt_stop);
/* Record a refusal that happened before tgl_dcs_run could start. */
void tgl_dcs_refuse(int stage, int code, uint32_t detail);
/* TGL_DCS_MENU: kick the configured full-panel layer again (after the menu was redrawn). */
int tgl_dcs_present(void);
/* TGL_DCS_MENU: return the display domain to ABL's handoff state (off) before Linux. 0 or DCS_C_*. */
int tgl_dcs_release(void);
/* Nonce pattern: slots 2..5 of the frame sequence take their colour from the top 4 of these 6 bits. */
static inline uint32_t tgl_dcs_pattern(uint64_t stamp_nonce) { return (uint32_t)(stamp_nonce >> 58) & 0x3fu; }
#ifdef TGL_DCS_HOSTTEST
int dcs_port_read32(uintptr_t pa, uint32_t *v);
int dcs_port_write32(uintptr_t pa, uint32_t v);
uint64_t dcs_port_now_us(void);
void dcs_port_delay_us(uint32_t us);
uint64_t dcs_port_isr(void);
void dcs_port_store64(uint64_t pa, uint64_t v);
void dcs_port_civac(uint64_t pa, uint64_t len);
void dcs_port_service(void);
volatile uint8_t *dcs_port_record(void);
#else
unsigned tgl_dcs_guarded(void);
#endif
#endif
