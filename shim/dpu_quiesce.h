/* DPU quiesce before the chooser gives the display domains back to CPM (gate TGL_DCS_QUIESCE).
 *
 * Every value below is read from the phone's own display module, not from source and not guessed:
 *   vs_drm.ko from vendor_kernel_boot_b (A0 truth, bytes equal to the phone's partition on 2026-11-03),
 *   sha256 92e482bead3a12611f8fd890b8e60727d6875a973b79a1a71239268da110cf40,
 *   vermagic 6.12.81-android16-6-g8b0f75aa713d-ab16512655-4k.
 * The addresses in brackets are instruction offsets in that module's .text (llvm-objdump -d -r); the full
 * derivation, register names and the stock call order are in
 * research/ios26-dualboot-r8/display-handback/SUSPEND-ORDER.md.
 *
 * Stock order (vs_crtc_enter_power_off -> vs_dc_disable -> runtime PM -> vs_dc_pm_runtime_suspend, with
 * vs_dc_res_disable inlined; GrapheneOS 6.12 vs_dc.c:148-180 and vs_dc_post.c:832 for structure only):
 *   1. dc_hw_disable_trigger -> online_trigger(false): OUTPUT<n>_START = 0
 *   2. wait for frame done; layers idle (dc_hw_fe_is_all_layers_idle)
 *   3. dc_hw_is_be_idle: GPCSR debug select, poll the BE Q-channel status
 *   4. (stock only if not idle or after bus errors: FE0/FE1/BE software reset; not done here, see below)
 *   5. dc_hw_reset_all_be_interrupts: enables 0, output clocks 0, statuses and overflows cleared
 *   6. dc_hw_enable_clock_domain_iso(true): all four isolation bits
 *   7. only then genpd powers the FE/DSI/top domains off.
 * The software resets of step 4 complete through the sw_rst_done interrupt (readb_poll_timeout of
 * hw->reset_status set by the ISR). The shim has no interrupt path, so it does not reset: a layer or BE that is
 * not idle stops the release instead (DCS_C_Q_LAYER_BUSY / DCS_C_Q_BE_BUSY) and the chooser does not jump. */
#ifndef DPU_QUIESCE_H
#define DPU_QUIESCE_H

/* dpu-gpcsr: FDT sswrp_dpu ranges 0xec00000 + dc9x00 reg[1] 0x390000 (truth/fdt.dts:3777-3778).
 * vs_drm.ko keeps it at dc_hw+0x28 (dc_hw_is_be_idle [37324]); struct dc_hw places gpcsr_reg_base there. */
#define Q_GPCSR UINT64_C(0x0ef90000)

/* dc_hw_is_be_idle [37354..373c4] */
#define Q_BE_DBG_CTL      0x107cu      /* writel 0x01000002: DBG_EN | DBG_STATUS_SEL 2 [37358-37368] */
#define Q_BE_DBG_CTL_VAL  0x01000002u
#define Q_BE_DBG_STATUS   0x1084u      /* readl, busy while bit 14 is set [37374-37384, 373c4] */
#define Q_BE_DBG_BUSY     (1u << 14)
#define Q_BE_IDLE_US      100000u      /* timeout 0x5f5e100 ns [37388-37390]; sleep 26..100 us [373a4-373b0] */
#define Q_BE_POLL_US      100u

/* dc_hw_is_layer_idle, layer hw_id 0 [35878-35904]: DEBUG_DMA_ST, then DEBUG_DMA_OUT_COORD = ST + 4.
 * Idle when (ST & 0x1f) == 0x18 (STATE 0, REQ_DONE, DMA_DONE) or the layer is off (ST | COORD) == 0. */
#define Q_L0_DMA_ST       0x018a54u
#define Q_L0_DMA_COORD    0x018a58u
#define Q_L0_ST_MASK      0x1fu
#define Q_L0_ST_IDLE      0x18u
#define Q_FRAME_US        100000u      /* own bound for the idle wait; stock uses vs_dc_get_framedone_timeout() */

/* online_trigger(false) via dc_hw_disable_trigger: OUTPUT0_START = 0 (the shim's frames use output 0). */
#define Q_OUTPUT0_START   0x0b6000u

/* dc_hw_disable_all_be_interrupts [32b44-32b80] and dc_hw_reset_all_be_interrupts [32c70-32cb8] */
#define Q_BE_INTR_ENABLE     0x080004u   /* 0 */
#define Q_BE_INTR_ENABLE1    0x080018u   /* 0 */
#define Q_SH_OUTPUT0_CLK_EN  0x0b60b4u   /* 0 */
#define Q_SH_OUTPUT1_CLK_EN  0x0b6178u   /* 0 */
#define Q_BE_INTR_STATUS     0x080008u   /* 0xffff1fff (mov w2, #-0xe001) */
#define Q_BE_INTR_STATUS1    0x08001cu   /* 0xfff1ff3f */
#define Q_BE_INTR_OVERFLOW   0x080014u   /* 0xffff1fff */
#define Q_BE_INTR_OVERFLOW1  0x080028u   /* 0xfff1ff3f */
#define Q_BE_W0_MASK         0xffff1fffu
#define Q_BE_W1_MASK         0xfff1ff3fu

/* dc_hw_enable_clock_domain_iso(true) [30e80-30ea4]: dc_write(0x80248, 1|6|8) */
#define Q_CLOCK_DOMAIN_ISOLATION 0x080248u
#define Q_ISO_ALL                0xfu

#endif
