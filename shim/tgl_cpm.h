#pragma once

#include "laguna_usb.h"

/* Read/validate the CPM clients and perform the queue-mode 0x100 handshake.
 * Every access uses probe_read32/probe_write32; errors stop all later writes. */
int tgl_cpm_init(void);

/* Board callbacks for laguna_usb_start(). Clock/reset requests use the exact
 * Google LPCM service at destination 0x8, one correlated request at a time. */
const struct laguna_usb_board_ops *tgl_cpm_board_ops(void);

/* Display R2 clock/reset pairs, one attempt per boot: pixel_ck0 put 01 then
 * reset 07 deassert, pixel_ck1 put 02 then reset 08 deassert (ABL dual ids). */
int tgl_cpm_display_pixel_clocks(void);

/* Legacy HSIO_N/selector-5 wrappers. These retain their existing behavior
 * for current callers; they DO NOT select the UFS HSIO_S domain. Use the
 * explicit UFS APIs below for new, separately gated UFS bring-up work. */
int tgl_cpm_lpcm_put(uint32_t id);
int tgl_cpm_lpcm_reset_deassert(uint32_t id);


/* I2: UFS HSIO_S clocks use the DT use-smc route, not USB's mailbox puts.
 * Google clk-cpm.c @6f689be7: SMC 0x82000702(lpcm=6,id,enable=1,0,0,0,0).
 * Only the actual UFS clock ids 3 (gpio_ref) and 0x10 (aux) are admitted.
 * Caller must stamp before/after and invoke only from an explicit candidate
 * gate with the watchdog active: a synchronous firmware call cannot itself
 * enforce a timeout. Acceptance from this shim's EL2 context is unproven.
 * The reply preserves raw a0/a1. This shim conservatively requires BOTH zero
 * (Linux WARNs on a0 but returns failure only for a1). No implicit fallback.
 * One firmware request per clock per boot; repeated success is cached. Any
 * failure or interrupted/incomplete call latches further UFS secure-clock
 * requests off. Only a completed success is cached. Returns 0 on success,
 * -1 on refusal/unsupported; no host SMC. */
struct tgl_cpm_ufs_clock_reply { uint64_t a0, a1; };
int tgl_cpm_ufs_clock_enable(uint32_t id,
    struct tgl_cpm_ufs_clock_reply *reply);

/* UFS PHY reset only: LPCM cmd04, selector6, resetid3, deassert=1.
 * ABL descriptor @+0x1b90b0 has index1 and rst3; seq_table[1]=6.
 * The descriptor has no paired put id. Requires successful tgl_cpm_init()
 * beforehand; uses the existing bounded mailbox sender, no SMC/reset of USB.
 * One request per boot, with cached result. Not automatically called.
 * 0 = reply success; nonzero = refusal/failure. */
int tgl_cpm_ufs_phy_reset_deassert(void);
