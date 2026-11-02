/* SPDX-License-Identifier: MIT
 * display-frame-r1, from display-dcs-r2. Stages A-F are r2's, observed on the phone. G on is new. DPU offsets are only in frame_tables.h (generated).
 * Literal sources, checked by tools/check_literals.py:
 *   dsi/PHY tables   generated from the vendor functions, GrapheneOS 8880355265bb
 *   LPB frames       lpb_service.h "Polling Mode": word0 = polling header<<16 | cmd
 *   LPCM frames      power_controller_main.c, clk-cpm.c: REQ | SSWRP/LPCM<<8 | ID<<16 | OP<<24
 *   polled channel   tgl_cpm.c's sender; this exact channel answered on the phone (N93 attempt a3e42dd0)
 *   addresses        captured FDT d7c27fdc: /sswrp_dpu@ec00000 ranges, dsi2host@3d8000, dw_mipi_cdphy@3c0000
 * No ABL file offset is used, and nothing runs out of ABL. */
#include "tgl_dcs.h"
#include "dcs_tables.h"
#include "frame_tables.h"
#ifndef TGL_DCS_HOSTTEST
#include "probe.h"
#include "guard.h"
#include "tgl_usb_console.h"
#endif

#define MBA_MAGIC_PA UINT64_C(0x05250000)
#define MBA_MAGIC 0x004d4241u
#define MBA_PAGE UINT64_C(0x05272000) /* 0x05250000 + 0x10000 + 0x12 * 0x1000 */
#define MBA_GO 0x00u
#define MBA_CTL 0x04u
#define MBA_ST 0x08u
#define MBA_MSG 0x100u
#define MBA_CTL_BIT24 0x01000000u
#define MBA_POLL_MAX 1001u
#define MBA_POLL_US 200u

#define DSI UINT64_C(0x0efd8000)
#define APB UINT64_C(0x0efd8800)
#define CDPHY UINT64_C(0x0efc0000)
#define DSI_CORE_ID 0x000u
#define DSI_VERSION 0x004u
#define DSI_INT_MAIN 0x014u
#define DSI_MODE_STATUS 0x01cu
#define DSI_CORE_STATUS 0x020u
#define DSI_PHY_STATUS 0x108u
#define DSI_CRI_TX_HDR 0x2c0u
#define DSI_CRI_RX_HDR 0x2c8u
#define DSI_CRI_RX_PLD 0x2ccu
#define DSI_CRI_TX_PLD 0x2c4u
#define DSI_INT_IPI 0x430u
#define HDR_LONG (1u << 29)
#define DSI_INT_PHY 0x400u
#define DSI_INT_TO 0x410u
#define DSI_INT_ACK 0x420u
#define DSI_INT_CRI 0x450u
#define CORE_CRI_BUSY (1u << 16)
#define CORE_CRI_AVAIL (1u << 18)
#define HDR_LP (1u << 24)
#define HDR_RD (1u << 28)
#define MODE_DATA_STREAM 4u
#define CRI_BUSY_US 25000u
#define CRI_AVAIL_US 50000u
#define BUDGET_US UINT64_C(25000000)

#define LPCM_HDR 0x08000000u
#define LPB_GET 0x05000003u
#define LPB_SET 0x05000002u
#define LPB_SSWRP_DPU 5u
#define PROT_NO_ERR 15u
#define LPB_SUCCESS 15u
#define LPB_PWRUP_STARTED 18u
#define LPB_NO_EFFECT 19u
#define LPCM_DSI0_ON 0x01020001u
#define LPCM_FE0_ON 0x01000001u
#define VS_CHIP_ID_9400 0x9400u
#define FORCE_BE_CSR_RD_CNT 30u
/* Compare PPS 0-88. Physical, r1a and r1b: byte 89 (second_line_bpg_offset, native 4:2:0 only) reads 0xff before and after we write 0. Recorded, not compared. */
#define PPS_COMPARE_BYTES 89u
#if TGL_DCS_BRIGHT
/* panel-gs-bmea.c, bmea_brt_configs for PANEL_REV_GE(EVT1), which holds this panel (id 42a1a00a, rev MP): default_brightness = 4637, "dbv_for_140_nits". FDT /chosen/display/panel@0 says the same.
 * Below 3726 (BMEA_ACL_ENHANCED_THRESHOLD_DBV) the vendor driver also turns ACL off, a path this write doesn't take. */
#define TGL_DCS_BRIGHT_DBV 4637u
_Static_assert(TGL_DCS_BRIGHT_DBV >= 3726u && TGL_DCS_BRIGHT_DBV <= 4637u, "low, and above the ACL threshold");
#define BRIGHT_SETTLE_US 50000u /* three TE periods at 60 Hz; dbv_extra_frame means the level may land a vsync late */
#define DCS_PM_UP 0x14u /* get_power_mode: sleep out, display on */
#endif
/* FDT pinctrl@EC7E000, pin 0 XDPU_TE0; pinctrl-lga.c offsets, stride 0x1000; common.h fields. Stock Linux doesn't bind this block: status "disabled". */
/* FDT dpu_smmu; arm-smmu-v3.h. Read only. Registers restart with the top domain, so ABL's state doesn't apply. */
#define DPU_SMMU UINT64_C(0x0ed80000)
#define SMMU_IDR0 0x00u
#define SMMU_CR0 0x20u
#define SMMU_CR0ACK 0x24u
#define SMMU_GBPA 0x44u
#define SMMU_GERROR 0x60u
#define SMMU_GERRORN 0x64u
#define SMMU_STRTAB_BASE 0x80u
#define SMMU_CR0_EN 1u
#define SMMU_GBPA_ABORT (1u << 20)
#define SMMU_GBPA_UPDATE (1u << 31)
/* Rung 3 test buffers. A is the record's framebuffer. B has no reservation in the FDT (reuse-display-r1 item 4). A quarter-panel layer, because the shim paints Device memory at about 14 us per store. */
#define FB_A UINT64_C(0xf0000000)
#define MENU_FB UINT64_C(0xf0000000)   /* chooser menu: shim/menu_ui.c, 1280x2856 XRGB8888 */
#define MENU_W 1280u
#define MENU_H 2856u
#define MENU_STRIDE (MENU_W * 4u)
#define FB_B UINT64_C(0xf0e00000)
#define LAYER_W 640u
#define LAYER_H 1428u
#define LAYER_X 320u
#define LAYER_Y 714u
#define LAYER_STRIDE (LAYER_W * 4u)
#define TE_PAD UINT64_C(0x0ec7e000)
#define PAD_PARAM 0x00u
#define PAD_DMUX 0x04u
#define PAD_TXDATA 0x08u
#define PAD_RXDATA 0x10u
#define PAD_DMUX_DPU_TE 0x2u /* BIT(1): dpu_gpio, dpu_te */
#define PAD_IE (1u << 8)
#define PAD_OE (1u << 3)
#define PAD_PUPD_MASK 0x3u
#define PAD_PUPD_PD 0x1u
#define PAD_OPEN_SETTLE_US 10u
#define FRAME_DONE_US 200000u
#define PIX_GET 0x03022302u
#define REF_GET 0x03010602u
#define PIX_PREPARE 0x00022302u
#define REF_PREPARE 0x00010602u

struct hdr { uint8_t magic[8]; uint64_t stamp_nonce; uint8_t record_nonce[16]; uint64_t epoch; uint32_t pattern, entries; uint32_t final, final_seal, version, reserved; };
_Static_assert(sizeof(struct hdr) == TGL_DCS_HEADER_BYTES, "header");
#ifdef TGL_DCS_HOSTTEST
#define BARRIER() do { } while (0)
#else
#define BARRIER() __asm__ volatile("dsb sy" ::: "memory")
static volatile uint8_t *dcs_port_record(void) { return (volatile uint8_t *)(uintptr_t)TGL_DCS_RECORD_PA; }
static int dcs_port_read32(uintptr_t pa, uint32_t *v) { return probe_read32(pa, v) ? 0 : -1; }
static int dcs_port_write32(uintptr_t pa, uint32_t v) { if (!probe_write32(pa, v)) return -1; BARRIER(); return 0; }
static uint64_t dcs_port_now_us(void)
{
    uint64_t f, n;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(f));
    if (!f) f = 38400000;
    __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(n));
    return n / (f / 1000000u);
}
static void dcs_port_delay_us(uint32_t us)
{
    uint64_t a = dcs_port_now_us();
    for (uint32_t g = 0; g < 100000000u && dcs_port_now_us() - a < us; ++g) { }
}
static void dcs_port_store64(uint64_t pa, uint64_t v) { *(volatile uint64_t *)(uintptr_t)pa = v; }
__attribute__((unused)) static void dcs_port_civac(uint64_t pa, uint64_t len)
{
    for (uint64_t a = pa & ~UINT64_C(63); a < pa + len; a += 64) __asm__ volatile("dc civac, %0" :: "r"(a) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
}
static uint64_t dcs_port_isr(void) { uint64_t v; __asm__ volatile("mrs %0, isr_el1" : "=r"(v)); return v; }
static void dcs_port_service(void) { tgl_usb_console_service(); }
#endif

static struct {
    uint32_t seq, seal, stop, started, quiet; uint64_t t0;
    uint32_t tx_mode; /* HDR_LP or 0 */
    int stage;
} d;

static void rec32(uint32_t off, uint32_t v) { *(volatile uint32_t *)(void *)(dcs_port_record() + off) = v; }

static void entry(uint32_t kind, uint32_t a, uint32_t b)
{
    if (d.seq >= TGL_DCS_CAPACITY) return;
    uint32_t off = TGL_DCS_HEADER_BYTES + d.seq * TGL_DCS_ENTRY_BYTES;
    uint32_t w0 = d.seq << 16 | kind << 8 | (uint32_t)d.stage;
    rec32(off + 12, 0); BARRIER();
    rec32(off, w0); rec32(off + 4, a); rec32(off + 8, b); BARRIER();
    rec32(off + 12, w0 ^ a ^ b ^ d.seal); BARRIER();
    d.seq++;
    rec32(__builtin_offsetof(struct hdr, entries), d.seq); BARRIER();
}
static void note(uint32_t id, uint32_t v) { entry(DCS_K_NOTE, id, v); }
static int stop_with(int code, uint32_t detail)
{
    if (!d.stop) { d.stop = (uint32_t)code; entry(DCS_K_STOP, (uint32_t)code, detail); }
    return code;
}
static void stage(int s) { d.stage = s; entry(DCS_K_STAGE, (uint32_t)s, 0); }

/* DPU registers: exactly the generated names, nothing else. Rung 1 may not write any of them. */
static int frame_off_ok(uint32_t off, int wr)
{
    static const uint32_t ro[] = { FR_CHIP_ID, FR_CHIP_REV, FR_PRODUCT_ID, FR_CHIP_CUSTOMER, FR_SH_OUTPUT0_CURRENT_COORD, FR_DSC_GEN_STATUS, FR_DSC_HSLICE_STATUS, FR_DSC_OUT_STATUS, FR_DSC_INT_STAT,
        FR_OUTPUT0_OFIFO_RED0_CRC_VALUE, FR_OUTPUT0_OFIFO_GREEN0_CRC_VALUE, FR_OUTPUT0_OFIFO_BLUE0_CRC_VALUE, FR_PANEL0_OFIFO_INPUT_RED_CRC_VALUE, FR_PANEL0_OFIFO_INPUT_GREEN_CRC_VALUE, FR_PANEL0_OFIFO_INPUT_BLUE_CRC_VALUE };
    static const uint32_t rw[] = { FR_POST_PROCESS_OUT, FR_CLOCK_DOMAIN_ISOLATION, FR_BE_INTR_ENABLE, FR_BE_INTR_STATUS, FR_PANEL0_CONFIG, FR_OUTPUT0_CONFIG, FR_OUTPUT0_START, FR_OUTPUT0_SW_CONFIG, FR_OUTPUT0, FR_OUTPUT0_CONFIG_COMMAND_OPT,
        FR_SH_PANEL0_POST_PRO_TP_COLOR_RED, FR_SH_PANEL0_POST_PRO_TP_COLOR_GREEN, FR_SH_PANEL0_POST_PRO_TP_COLOR_BLUE, FR_OUTIF_OFIFO_CRC_START, FR_PANEL0_CRC_START };
    static const uint32_t rw3[] = { FR_LAYER0_CONFIG, FR_SH_LAYER0_ADDRESS, FR_SH_LAYER0_HIGH_ADDRESS, FR_SH_LAYER0_STRIDE, FR_SH_LAYER0_SIZE, FR_SH_LAYER0_CONFIG, FR_SH_LAYER0_OUT_ROI_ORIGIN, FR_SH_LAYER0_OUT_ROI_SIZE, FR_SH_LAYER0_ALPHA_BLEND_CONFIG, FR_FE0_INTR_ENABLE, FR_FE0_INTR_STATUS, FR_SH_PANEL0_POST_PRO_TP_ENABLE };
    if (TGL_FRAME_RUNG >= 3) {
        for (unsigned i = 0; i < sizeof rw3 / sizeof rw3[0]; ++i) if (off == rw3[i]) return 1;
        for (unsigned i = 0; i < sizeof fr_fe0 / sizeof fr_fe0[0]; ++i) if (off == fr_fe0[i].off) return 1;
    }
    if (TGL_FRAME_RUNG < 2) {
        if (wr) return 0;
        return off == FR_POST_PROCESS_OUT || off == FR_CLOCK_DOMAIN_ISOLATION || off == FR_CHIP_ID || off == FR_CHIP_REV || off == FR_PRODUCT_ID || off == FR_CHIP_CUSTOMER;
    }
    if (!wr) for (unsigned i = 0; i < sizeof ro / sizeof ro[0]; ++i) if (off == ro[i]) return 1;
    for (unsigned i = 0; i < sizeof rw / sizeof rw[0]; ++i) if (off == rw[i]) return 1;
    for (unsigned i = 0; i < sizeof fr_dsc / sizeof fr_dsc[0]; ++i) if (off == fr_dsc[i].off) return 1;
    for (unsigned i = 0; i < sizeof fr_cfg / sizeof fr_cfg[0]; ++i) if (off == fr_cfg[i].off) return 1;
    return 0;
}
static int pa_ok(uint64_t pa, int wr)
{
    if (pa & 3) return 0;
    if (TGL_FRAME_RUNG >= 2 && (pa == TE_PAD + PAD_PARAM || pa == TE_PAD + PAD_DMUX || pa == TE_PAD + PAD_TXDATA)) return 1;
    if (TGL_FRAME_RUNG >= 2 && pa == TE_PAD + PAD_RXDATA) return !wr;
    if (TGL_FRAME_RUNG >= 3 && !wr && (pa == DPU_SMMU + SMMU_IDR0 || pa == DPU_SMMU + SMMU_CR0 || pa == DPU_SMMU + SMMU_CR0ACK || pa == DPU_SMMU + SMMU_GBPA || pa == DPU_SMMU + SMMU_GERROR || pa == DPU_SMMU + SMMU_GERRORN || pa == DPU_SMMU + SMMU_STRTAB_BASE)) return 1;
    if (TGL_FRAME_RUNG >= 3 && wr && pa == DPU_SMMU + SMMU_GBPA) return 1;
    if (pa >= FR_DPU && pa < FR_DPU + 0x120000) return frame_off_ok((uint32_t)(pa - FR_DPU), wr);
    if (pa == MBA_MAGIC_PA) return !wr;
    if (pa == MBA_PAGE + MBA_GO || pa == MBA_PAGE + MBA_CTL || pa == MBA_PAGE + MBA_ST) return 1;
    if (pa >= MBA_PAGE + MBA_MSG && pa < MBA_PAGE + MBA_MSG + 16) return 1;
    if (pa >= DSI && pa < DSI + 0x800) return 1;
    if (pa >= APB && pa < APB + 0x50) return 1;
    if (pa >= CDPHY && pa < CDPHY + 0x18000) return 1;
    return 0;
}
static int checks(uint64_t pa, int wr)
{
    if (d.stop) return d.stop;
    if (!pa_ok(pa, wr)) return stop_with(DCS_C_REFUSED_PA, (uint32_t)pa);
    if (d.seq + 8 >= TGL_DCS_CAPACITY) return stop_with(DCS_C_RECORD_FULL, d.seq);
    if (dcs_port_now_us() - d.t0 > BUDGET_US) return stop_with(DCS_C_BUDGET, (uint32_t)pa);
    return 0;
}
static int after(uint64_t pa)
{
    uint64_t isr = dcs_port_isr();
    if (isr & (1u << 8)) { note(DCS_N_ISR, (uint32_t)isr); return stop_with(DCS_C_SERROR, (uint32_t)pa); }
    return 0;
}
static int rdq(uint64_t pa, uint32_t *v)
{
    int rc = checks(pa, 0);
    if (rc) return rc;
    if (dcs_port_read32((uintptr_t)pa, v)) return stop_with(DCS_C_FAULT, (uint32_t)pa);
    return after(pa);
}
static int rd(uint64_t pa, uint32_t *v)
{
    int rc = checks(pa, 0);
    if (rc) return rc;
    if (!d.quiet) entry(DCS_K_RD_INTENT, (uint32_t)pa, 0);
    if (dcs_port_read32((uintptr_t)pa, v)) return stop_with(DCS_C_FAULT, (uint32_t)pa);
    if (!d.quiet) entry(DCS_K_RD, (uint32_t)pa, *v);
    return after(pa);
}
static int wr(uint64_t pa, uint32_t v)
{
    int rc = checks(pa, 1);
    if (rc) return rc;
    if (!d.quiet) entry(DCS_K_WR_INTENT, (uint32_t)pa, v);
    if (dcs_port_write32((uintptr_t)pa, v)) return stop_with(DCS_C_FAULT, (uint32_t)pa);
    return after(pa);
}
/* Poll until (v & mask) == want. Logs the first value and the last. */
static int poll(uint64_t pa, uint32_t mask, uint32_t want, uint32_t timeout_us, uint32_t *out, int *hit)
{
    uint32_t v = 0; int rc = rd(pa, &v);
    uint64_t a = dcs_port_now_us();
    *hit = 0;
    for (uint32_t n = 0; !rc; ++n) {
        if ((v & mask) == want) { *hit = 1; break; }
        if (dcs_port_now_us() - a >= timeout_us || n > timeout_us) break;
        dcs_port_delay_us(50);
        rc = rdq(pa, &v);
    }
    if (out) *out = v;
    if (!rc && (!d.quiet || !*hit)) entry(DCS_K_POLL, (uint32_t)pa, v);
    return rc;
}

/* ---- polled LPCM/LPB channel: tgl_cpm.c's mba_send, register for register. Reply words are kept raw. ---- */
static int mba(uint32_t w0, uint32_t w1, uint32_t w2, uint32_t w3, uint32_t r[4])
{
    uint32_t v = 0, ctl = 0; int rc;
    if ((rc = wr(MBA_PAGE + MBA_ST, 1)) || (rc = rd(MBA_PAGE + MBA_ST, &v)) || (rc = rd(MBA_PAGE + MBA_CTL, &ctl)) || (rc = wr(MBA_PAGE + MBA_CTL, ctl | MBA_CTL_BIT24))) return rc;
    if ((rc = wr(MBA_PAGE + MBA_MSG, w0)) || (rc = wr(MBA_PAGE + MBA_MSG + 4, w1)) || (rc = wr(MBA_PAGE + MBA_MSG + 8, w2)) || (rc = wr(MBA_PAGE + MBA_MSG + 12, w3))) return rc;
    if ((rc = wr(MBA_PAGE + MBA_GO, 1))) return rc;
    if ((rc = rd(MBA_PAGE + MBA_ST, &v))) return rc;
    unsigned n = 0;
    while (!(v & 1u)) {
        if (++n >= MBA_POLL_MAX) { entry(DCS_K_POLL, (uint32_t)(MBA_PAGE + MBA_ST), v); return stop_with(DCS_C_MBA_TIMEOUT, w1); }
        dcs_port_delay_us(MBA_POLL_US);
        if ((rc = rdq(MBA_PAGE + MBA_ST, &v))) return rc;
    }
    entry(DCS_K_POLL, (uint32_t)(MBA_PAGE + MBA_ST), n);
    for (unsigned i = 0; i < 4; ++i) if ((rc = rd(MBA_PAGE + MBA_MSG + 4 * i, &r[i]))) return rc;
    if ((rc = wr(MBA_PAGE + MBA_ST, 1)) || (rc = rd(MBA_PAGE + MBA_ST, &v))) return rc;
    return 0;
}
static int lpcm(uint32_t cmd, uint32_t aux, uint32_t r[4]) { return mba(LPCM_HDR, cmd, aux, 0, r); }

/* Sources disagree: lpb_service.h says polled reply word1 is the state with ON=2, OFF=1; power_controller_main.c reads
 * payload[1] with ON=3, OFF=0. So: word1 == NO_ERR means the state is word2. 2 or 3 is on, 0 or 1 off, anything else stops. */
static int lpb_state(uint32_t *st)
{
    uint32_t r[4] = {0}; int rc = mba(LPB_GET, LPB_SSWRP_DPU, 0, 0, r);
    if (rc) return rc;
    if (!d.quiet) { note(DCS_N_MBA_R0, r[0]); note(DCS_N_MBA_R1, r[1]); note(DCS_N_MBA_R2, r[2]); note(DCS_N_MBA_R3, r[3]); }
    *st = r[1] == PROT_NO_ERR ? r[2] : r[1];
    return 0;
}
static int state_is(uint32_t s, int *on)
{
    if (s == 2 || s == 3) { *on = 1; return 0; }
    if (s == 0 || s == 1) { *on = 0; return 0; }
    return stop_with(DCS_C_TOP_STATE, s);
}
static int stage_a(void)
{
    uint32_t v = 0, r[4] = {0}, st = 0; int rc, on = 0;
    stage(DCS_S_A_TOP);
    if ((rc = rd(MBA_MAGIC_PA, &v))) return rc;
    if (v != MBA_MAGIC) return stop_with(DCS_C_MAGIC, v);
    if ((rc = lpb_state(&st))) return rc;
    note(DCS_N_TOP_STATE_BEFORE, st);
    if ((rc = state_is(st, &on))) return rc;
    if (on) return 0;
    if ((rc = mba(LPB_SET, LPB_SSWRP_DPU, 1, 0, r))) return rc;
    note(DCS_N_MBA_R0, r[0]); note(DCS_N_MBA_R1, r[1]); note(DCS_N_MBA_R2, r[2]); note(DCS_N_MBA_R3, r[3]);
    note(DCS_N_TOP_SET_STATUS, r[2]);
    if (r[1] != PROT_NO_ERR || (r[2] != LPB_SUCCESS && r[2] != LPB_PWRUP_STARTED && r[2] != LPB_NO_EFFECT) || r[3] != LPB_SSWRP_DPU) return stop_with(DCS_C_TOP_REPLY, r[1] << 8 | (r[2] & 0xff));
    for (unsigned i = 0; i < 400; ++i) {
        d.quiet = i >= 2; /* identical frames; the record keeps two in full, then one line per poll */
        if (d.quiet) entry(DCS_K_POLL, (uint32_t)(MBA_PAGE + MBA_MSG), i);
        rc = lpb_state(&st);
        d.quiet = 0;
        if (rc) return rc;
        if ((rc = state_is(st, &on))) return rc;
        if (on) { note(DCS_N_TOP_STATE_AFTER, st); return 0; }
        dcs_port_delay_us(5000);
    }
    note(DCS_N_TOP_STATE_AFTER, st);
    return stop_with(DCS_C_TOP_STATE, st);
}
static int stage_b(void)
{
    uint32_t r[4] = {0}; int rc;
    stage(DCS_S_B_DSI0);
    if ((rc = lpcm(LPCM_DSI0_ON, 0, r))) return rc;
    note(DCS_N_MBA_R0, r[0]); note(DCS_N_MBA_R1, r[1]);
    if (r[1] != 0) return stop_with(DCS_C_LPCM_REPLY, r[1]);
    return 0;
}
static uint32_t ref_hz;
static int stage_c(void)
{
    uint32_t r[4] = {0}; int rc;
    stage(DCS_S_C_CLOCKS);
    if ((rc = lpcm(PIX_GET, 0, r))) return rc;
    note(DCS_N_RATE_PIX_BEFORE, r[1]);
    if ((rc = lpcm(REF_GET, 0, r))) return rc;
    note(DCS_N_RATE_REF_BEFORE, r[1]);
    if ((rc = lpcm(PIX_PREPARE, 1, r))) return rc;
    if (r[1] != 0) return stop_with(DCS_C_LPCM_REPLY, r[1]);
    if ((rc = lpcm(REF_PREPARE, 1, r))) return rc;
    if (r[1] != 0) return stop_with(DCS_C_LPCM_REPLY, r[1]);
    if ((rc = lpcm(PIX_GET, 0, r))) return rc;
    note(DCS_N_RATE_PIX, r[1]);
    if ((int32_t)r[1] < 0) return stop_with(DCS_C_RATE, r[1]);
    if ((rc = lpcm(REF_GET, 0, r))) return rc;
    note(DCS_N_RATE_REF, r[1]);
    if (r[1] != 38400000u && r[1] != 76800000u) return stop_with(DCS_C_RATE, r[1]);
    ref_hz = r[1];
    return 0;
}
static int stage_d(void)
{
    uint32_t v = 0; int rc;
    stage(DCS_S_D_FIRST_READ);
    if ((rc = rd(DSI + DSI_CORE_ID, &v))) return rc;
    note(DCS_N_CORE_ID, v);
    if (v == 0 || v == 0xffffffffu) return stop_with(DCS_C_DEAD_REG, v);
    if ((rc = rd(DSI + DSI_VERSION, &v))) return rc;
    note(DCS_N_VERSION, v);
    if ((rc = rd(DSI + DSI_CORE_STATUS, &v))) return rc;
    if ((rc = rd(DSI + DSI_PHY_STATUS, &v))) return rc;
    return rd(APB + 0x24, &v);
}
static int stage_e(void)
{
    const struct dcs_op *t = ref_hz == 76800000u ? dcs_ops_76800000 : dcs_ops_38400000;
    uint32_t n = ref_hz == 76800000u ? DCS_OPS_76800000_N : DCS_OPS_38400000_N, v, old; int rc, hit;
    stage(DCS_S_E_HOST_PHY);
    for (uint32_t i = 0; i < n; ++i) {
        const struct dcs_op *o = &t[i];
        switch (o->kind) {
        case DCS_OP_FIELD: /* regmap_field_write: read, and write only if the value changes */
            if ((rc = rdq(o->pa, &old))) return rc; /* r2 logged these and read fine on the phone; the record needs the room */
            v = (old & ~o->mask) | o->val;
            if (v != old && (rc = wr(o->pa, v))) return rc;
            break;
        case DCS_OP_RAW:
            if ((rc = wr(o->pa, o->val))) return rc;
            break;
        case DCS_OP_POLL:
            if ((rc = poll(o->pa, o->mask, o->mask, o->val, 0, &hit))) return rc;
            if (!hit) return stop_with(DCS_C_PHY_POLL, o->mask);
            break;
        case DCS_OP_DELAY:
            dcs_port_delay_us(o->val);
            break;
        default:
            return stop_with(DCS_C_REFUSED_PA, i);
        }
    }
    /* dw_opt_mode_select: the mode_ctrl write is the table's last op. */
    if ((rc = poll(DSI + DSI_MODE_STATUS, 0xffffffffu, MODE_DATA_STREAM, 1000, &v, &hit))) return rc;
    note(DCS_N_MODE_STATUS, v);
    if (!hit) return stop_with(DCS_C_MODE, v);
    dcs_port_delay_us(200); /* LP-11 before the first packet */
    if ((rc = rd(DSI + DSI_PHY_STATUS, &v))) return rc;
    note(DCS_N_PHY_STATUS, v);
    return 0;
}

/* ---- DCS over CRI: dw_mipi_dsi2h_host_write_msg and dw_mipi_dsi2h_cri_read ---- */
static int cri_idle(void)
{
    uint32_t q = d.quiet; d.quiet = 1;
    int hit, rc = poll(DSI + DSI_CORE_STATUS, CORE_CRI_BUSY, 0, CRI_BUSY_US, 0, &hit);
    d.quiet = q;
    if (rc) return rc;
    return hit ? 0 : stop_with(DCS_C_CRI_BUSY, 0);
}
static int int_status(void)
{
    uint32_t v; int rc;
    if ((rc = rd(DSI + DSI_INT_MAIN, &v))) return rc;
    note(DCS_N_INT_MAIN, v);
    if (!v) return 0;
    if ((rc = rd(DSI + DSI_INT_CRI, &v))) return rc;
    note(DCS_N_INT_CRI, v);
    if ((rc = rd(DSI + DSI_INT_ACK, &v))) return rc;
    note(DCS_N_INT_ACK, v);
    if ((rc = rd(DSI + DSI_INT_TO, &v))) return rc;
    note(DCS_N_INT_TO, v);
    if ((rc = rd(DSI + DSI_INT_PHY, &v))) return rc;
    note(DCS_N_INT_PHY, v);
    return 0;
}
static int read_cmd_ok(uint32_t c) { return c == 0x0a || c == 0x05 || c == 0xda || c == 0xdb || c == 0xdc || c == 0xa1 || c == 0x03 || c == 0x52 || c == 0xa2 || c == 0x63; }
/* 0: *n bytes in out. -1: nothing usable. >0: stopped. dw_mipi_dsi2h_cri_read. */
static int dcs_read(uint32_t cmd, uint8_t *out, uint32_t want, uint32_t *n, uint32_t mode)
{
    uint32_t v = 0, h; int rc, hit;
    *n = 0;
    if (!read_cmd_ok(cmd)) return stop_with(DCS_C_DCS_REFUSED, cmd);
    if ((rc = cri_idle())) return rc;
    for (unsigned i = 0; i < 8; ++i) { /* a leftover from an earlier failed read must not answer this one */
        if ((rc = rd(DSI + DSI_CORE_STATUS, &v))) return rc;
        if (!(v & CORE_CRI_AVAIL)) break;
        if ((rc = rd(DSI + DSI_CRI_RX_HDR, &h))) return rc;
    }
    if ((rc = wr(DSI + DSI_CRI_TX_HDR, 0x37u | want << 8 | mode))) return rc; /* SET_MAXIMUM_RETURN_PACKET_SIZE */
    if ((rc = wr(DSI + DSI_CRI_TX_HDR, 0x06u | cmd << 8 | HDR_RD | mode))) return rc; /* DCS_READ */
    int got = 0;
    for (unsigned pkt = 0; pkt < 4 && !got; ++pkt) {
        if ((rc = poll(DSI + DSI_CORE_STATUS, CORE_CRI_AVAIL, CORE_CRI_AVAIL, CRI_AVAIL_US, 0, &hit))) return rc;
        if (!hit) break;
        if ((rc = rd(DSI + DSI_CRI_RX_HDR, &h))) return rc;
        uint32_t dt = h & 0x3f, wc_lsb = (h >> 8) & 0xff, wc_msb = (h >> 16) & 0xff;
        if (dt == 0x21 || dt == 0x11) { out[0] = (uint8_t)wc_lsb; *n = 1; got = 1; }
        else if (dt == 0x22 || dt == 0x12) { out[0] = (uint8_t)wc_lsb; *n = 1; if (want > 1) { out[1] = (uint8_t)wc_msb; *n = 2; } got = 1; }
        else if (dt == 0x1c || dt == 0x1a) {
            uint32_t len = wc_msb << 8 | wc_lsb, w = 0, q = d.quiet;
            d.quiet = 1;
            for (uint32_t off = 0; off < len && off < 128; off += 4) {
                rc = poll(DSI + DSI_CORE_STATUS, CORE_CRI_AVAIL, CORE_CRI_AVAIL, CRI_AVAIL_US, 0, &hit);
                if (rc || !hit) break;
                if ((rc = rdq(DSI + DSI_CRI_RX_PLD, &w))) break;
                for (uint32_t k = 0; k < 4 && off + k < len && off + k < want; ++k) { out[off + k] = (uint8_t)(w >> (8 * k)); *n = off + k + 1; }
                got = 1;
            }
            d.quiet = q;
            if (rc) return rc;
        } else if (dt == 0x02) note(DCS_N_ACK_REPORT, h);
        else if (dt != 0x08) note(DCS_N_READ_FAIL, h);
    }
    if ((rc = int_status())) return rc;
    if (!got) note(DCS_N_READ_FAIL, cmd << 8 | mode >> 24);
    return got ? 0 : -1;
}
static int dcs_read1(uint32_t cmd, uint8_t *out, uint32_t mode) { uint32_t n; return dcs_read(cmd, out, 1, &n, mode); }
/* Exact byte strings from panel-gs-bmea.c: bmea_get_opr and bmea_enable. Nothing else can be sent. */
static const uint8_t k_f0u[3] = { 0xf0, 0x5a, 0x5a }, k_f0l[3] = { 0xf0, 0xa5, 0xa5 }, k_fcu[3] = { 0xfc, 0x5a, 0x5a }, k_fcl[3] = { 0xfc, 0xa5, 0xa5 }, k_b0opr[4] = { 0xb0, 0x01, 0x1a, 0x63 };
#if TGL_DCS_BRIGHT
/* bmea_set_brightness: swab16, then mipi_dsi_dcs_set_display_brightness sends low byte first. So the level's high byte goes first on the wire, as in bmea_enable and bmea_lp_*_cmds. */
static const uint8_t k_bright[3] = { 0x51, TGL_DCS_BRIGHT_DBV >> 8, TGL_DCS_BRIGHT_DBV & 0xff };
#define DCS_LONG_BRIGHT(di, b, len) ((b) == k_bright && (len) == 3 && (di) == 0x39)
#else
#define DCS_LONG_BRIGHT(di, b, len) 0
#endif
static int dcs_long(uint32_t di, const uint8_t *b, uint32_t len)
{
    int rc;
    if (!(((b == k_f0u || b == k_f0l || b == k_fcu || b == k_fcl) && len == 3 && di == 0x39) || (b == k_b0opr && len == 4 && di == 0x39) || (b == fr_pps && len == 128 && di == 0x0a && TGL_FRAME_RUNG >= 2) || DCS_LONG_BRIGHT(di, b, len))) return stop_with(DCS_C_DCS_REFUSED, di);
    if ((rc = cri_idle())) return rc;
    for (uint32_t off = 0; off < len; off += 4) {
        uint32_t w = 0;
        for (uint32_t k = 0; k < 4 && off + k < len; ++k) w |= (uint32_t)b[off + k] << (8 * k);
        if ((rc = wr(DSI + DSI_CRI_TX_PLD, w))) return rc;
    }
    if ((rc = wr(DSI + DSI_CRI_TX_HDR, di | len << 8 | HDR_LONG | d.tx_mode))) return rc;
    return cri_idle();
}
#if TGL_DCS_BRIGHT
static uint32_t panel_power;
#endif
static int stage_f(void)
{
    static const uint8_t ids[4] = { 0xda, 0xdb, 0xdc, 0xa1 };
    static const uint8_t want[4] = { 0x0a, 0xa0, 0xa1, 0x42 }; /* r2: phone read DA=0x0a; id 0x42a1a00a is little-endian, gs_panel.c:2334 */
    uint8_t b = 0; int rc = -1;
    stage(DCS_S_F_PANEL);
    /* Stock reads in HS; the first read after handoff can raise ack errors (dw_dsi2h_suppress_errors_workaround). LP first, needs less. */
    static const uint32_t modes[4] = { HDR_LP, HDR_LP, 0, 0 };
    for (unsigned i = 0; i < 4 && rc == -1; ++i) { d.tx_mode = modes[i]; rc = dcs_read1(0x0a, &b, modes[i]); }
    if (rc > 0) return rc;
    if (rc < 0) return stop_with(DCS_C_NO_PANEL_REPLY, 0x0a);
    note(DCS_N_TX_LP, d.tx_mode ? 1 : 0);
    note(DCS_N_POWER_MODE, b);
#if TGL_DCS_BRIGHT
    panel_power = b;
#endif
    rc = dcs_read1(0x05, &b, d.tx_mode);
    if (rc > 0) return rc;
    if (!rc) note(DCS_N_ERR_COUNT, b);
    for (unsigned i = 0; i < 4; ++i) {
        rc = dcs_read1(ids[i], &b, d.tx_mode);
        if (rc > 0) return rc;
        if (rc < 0) return stop_with(DCS_C_NO_PANEL_REPLY, ids[i]);
        note(DCS_N_ID_DA + i, b);
        if (b != want[i]) return stop_with(DCS_C_PANEL_ID, (uint32_t)ids[i] << 8 | b);
    }
    return 0;
}
__attribute__((unused)) static void wait_ms(uint32_t ms)
{
    uint64_t a = dcs_port_now_us();
    for (uint32_t g = 0; g < 10000000u && dcs_port_now_us() - a < (uint64_t)ms * 1000u; ++g) {
        dcs_port_service();
        dcs_port_delay_us(500);
    }
}
static uint32_t pattern;
/* bmea_get_opr: unlock, B0 offset, read 2 bytes, lock. Always locks. val = 0x7ff is 100%. */
static int opr_read(uint32_t *val, int *ok)
{
    uint8_t b[2] = { 0, 0 }; uint32_t n = 0; int rc, rr;
    *ok = 0;
    if ((rc = dcs_long(0x39, k_f0u, 3)) || (rc = dcs_long(0x39, k_fcu, 3)) || (rc = dcs_long(0x39, k_b0opr, 4))) return rc;
    rr = dcs_read(0x63, b, 2, &n, d.tx_mode);
    if (rr > 0) return rr;
    if ((rc = dcs_long(0x39, k_fcl, 3)) || (rc = dcs_long(0x39, k_f0l, 3))) return rc;
    if (!rr && n == 2) { *val = (uint32_t)b[0] << 8 | b[1]; *ok = 1; note(DCS_N_OPR, *val); }
    return 0;
}
static uint8_t pps_buf[90];
static uint32_t pps_before_n, pps_before_same;
static int pps_read(uint32_t id, uint32_t *n)
{
    int rr = dcs_read(0xa2, pps_buf, 90, n, d.tx_mode);
    if (rr > 0) return rr;
    if (rr) *n = 0;
    for (uint32_t i = 0; i < *n; i += 4) note(id, (uint32_t)pps_buf[i] | (uint32_t)(i + 1 < *n ? pps_buf[i + 1] : 0) << 8 | (uint32_t)(i + 2 < *n ? pps_buf[i + 2] : 0) << 16 | (uint32_t)(i + 3 < *n ? pps_buf[i + 3] : 0) << 24);
    return 0;
}
#if TGL_DCS_BRIGHT
static int bright_read(uint32_t id, uint32_t *v, int *ok)
{
    uint8_t b[2] = { 0, 0 }; uint32_t n = 0;
    int rc = dcs_read(0x52, b, 2, &n, d.tx_mode);
    *ok = 0;
    if (rc > 0) return rc;
    if (!rc && n == 2) { *v = (uint32_t)b[0] << 8 | b[1]; *ok = 1; note(id, *v); }
    return 0;
}
/* ABL leaves a level that differs by boot, up to about 860 nits (inferred). One write, no DPU touched yet, the same packet shape and state as opr_read's long writes. A wrong read-back is logged, not a stop. */
static int bright_set(void)
{
    uint32_t v = 0, n = 0; uint8_t b = 0; int rc, ok = 0;
    note(DCS_N_BRIGHT_TARGET, TGL_DCS_BRIGHT_DBV);
    if ((panel_power & DCS_PM_UP) != DCS_PM_UP) { note(DCS_N_BRIGHT_RESULT, DCS_BR_PANEL_NOT_UP); return 0; }
    if ((rc = dcs_long(0x39, k_bright, 3))) return rc;
    if ((rc = bright_read(DCS_N_BRIGHT_AT_WRITE, &v, &ok))) return rc;
    dcs_port_delay_us(BRIGHT_SETTLE_US);
    if ((rc = bright_read(DCS_N_BRIGHT_SETTLED, &v, &ok))) return rc;
    if ((rc = dcs_read(0x05, &b, 1, &n, d.tx_mode)) > 0) return rc;
    if (!rc) note(DCS_N_BRIGHT_ERR_COUNT, b);
    if ((rc = dcs_read(0x0a, &b, 1, &n, d.tx_mode)) > 0) return rc;
    if (!rc) note(DCS_N_BRIGHT_POWER, b);
    note(DCS_N_BRIGHT_RESULT, !ok ? DCS_BR_NO_READBACK : v == TGL_DCS_BRIGHT_DBV ? DCS_BR_OK : DCS_BR_MISMATCH);
    return 0;
}
#endif
/* Read-only unless TGL_DCS_BRIGHT, panel side. Nothing here may stop the boot except a stop from the bus. */
static int stage_g(void)
{
    uint8_t b[2] = { 0, 0 }; uint32_t n = 0, v = 0; int rc, ok;
    stage(DCS_S_G_PANEL_READ);
    if ((rc = dcs_read(0x03, b, 1, &n, d.tx_mode)) > 0) return rc;
    if (!rc) note(DCS_N_COMPRESSION, b[0]);
    if ((rc = dcs_read(0x52, b, 2, &n, d.tx_mode)) > 0) return rc;
    if (!rc) note(DCS_N_BRIGHTNESS, (uint32_t)b[0] << 8 | (n > 1 ? b[1] : 0));
#if TGL_DCS_BRIGHT
    if ((rc = bright_set())) return rc;
#endif
    if ((rc = pps_read(DCS_N_PPS_BEFORE, &n))) return rc;
    pps_before_n = n; pps_before_same = n == 90;
    for (unsigned i = 0; pps_before_same && i < PPS_COMPARE_BYTES; ++i) if (pps_buf[i] != fr_pps[i]) pps_before_same = 0;
    return opr_read(&v, &ok);
}
static int stage_h(void)
{
    uint32_t r[4] = { 0 }; int rc;
    stage(DCS_S_H_FE0);
    if ((rc = lpcm(LPCM_FE0_ON, 0, r))) return rc;
    note(DCS_N_MBA_R0, r[0]); note(DCS_N_MBA_R1, r[1]);
    if (r[1] != 0) return stop_with(DCS_C_LPCM_REPLY, r[1]);
    return 0;
}
#ifdef TGL_DCS_HANDOFF
#include "tgl_scanout_takeover.h"
static uint32_t handoff_rev;
#endif
/* The first DPU access on this boot. Each one is on the record before it happens. dc_hw_force_be_csr_read, then the IDs of dc_hw_init. */
static int stage_i(void)
{
    uint32_t v = 0; int rc;
    stage(DCS_S_I_DPU_READ);
    for (unsigned i = 0; i < FORCE_BE_CSR_RD_CNT; ++i) {
        d.quiet = i > 0 && i + 1 < FORCE_BE_CSR_RD_CNT;
        rc = rd(FR_DPU + FR_POST_PROCESS_OUT, &v);
        d.quiet = 0;
        if (rc) return rc;
    }
    note(DCS_N_POST_OUT, v);
    if ((rc = rd(FR_DPU + FR_CLOCK_DOMAIN_ISOLATION, &v))) return rc;
    note(DCS_N_ISO_BEFORE, v);
    if ((rc = rd(FR_DPU + FR_CHIP_ID, &v))) return rc;
    note(DCS_N_CHIP_ID, v);
    if (v != VS_CHIP_ID_9400) return stop_with(DCS_C_CHIP, v);
    if ((rc = rd(FR_DPU + FR_CHIP_REV, &v))) return rc;
    note(DCS_N_CHIP_REV, v);
#ifdef TGL_DCS_HANDOFF
    handoff_rev = v;
#endif
    if ((rc = rd(FR_DPU + FR_PRODUCT_ID, &v))) return rc;
    note(DCS_N_PRODUCT_ID, v);
    if ((rc = rd(FR_DPU + FR_CHIP_CUSTOMER, &v))) return rc;
    note(DCS_N_CUSTOMER, v);
    return 0;
}
#if TGL_FRAME_RUNG >= 2
static int rmw_q(uint32_t off, uint32_t clear, uint32_t set)
{
    uint32_t v = 0; int rc;
    if ((rc = rdq(FR_DPU + off, &v))) return rc;
    return wr(FR_DPU + off, (v & ~clear) | set);
}
static int reg_switch(int on)
{
    int rc;
#if TGL_FRAME_RUNG >= 3
    if ((rc = rmw_q(FR_LAYER0_CONFIG, FR_REG_SWITCH, on ? FR_REG_SWITCH : 0))) return rc;
#endif
    if ((rc = rmw_q(FR_PANEL0_CONFIG, FR_REG_SWITCH, on ? FR_REG_SWITCH : 0))) return rc;
    return rmw_q(FR_OUTPUT0_CONFIG, FR_REG_SWITCH, on ? FR_REG_SWITCH : 0);
}
/* Stock writes 0 to all four bits. DSI1 and DP are unpowered here, so only DSI0's isolation is lifted. */
static int stage_j(void)
{
    uint32_t v = 0; int rc;
    stage(DCS_S_J_ISOLATION);
    if ((rc = rd(FR_DPU + FR_CLOCK_DOMAIN_ISOLATION, &v))) return rc;
    if ((v & FR_ISO_DSI0) && (rc = wr(FR_DPU + FR_CLOCK_DOMAIN_ISOLATION, v & ~FR_ISO_DSI0))) return rc;
    if ((rc = rd(FR_DPU + FR_CLOCK_DOMAIN_ISOLATION, &v))) return rc;
    note(DCS_N_ISO_AFTER, v);
    if (v & FR_ISO_DSI0) return stop_with(DCS_C_ISOLATION, v);
    return 0;
}
/* vs_dc_enable: shadow off, dc_hw_config_dsc, display_set_mode, dc_hw_enable_frame_irqs, dc_hw_enable_vblank_irqs' arming. */
static int stage_k(void)
{
    int rc;
    stage(DCS_S_K_DPU_CONFIG);
    if ((rc = reg_switch(0))) return rc;
    for (unsigned i = 0; i < sizeof fr_dsc / sizeof fr_dsc[0]; ++i) if ((rc = wr(FR_DPU + fr_dsc[i].off, fr_dsc[i].val))) return rc;
    for (unsigned i = 0; i < sizeof fr_cfg / sizeof fr_cfg[0]; ++i) if ((rc = wr(FR_DPU + fr_cfg[i].off, fr_cfg[i].val))) return rc;
    if ((rc = rmw_q(FR_OUTPUT0_CONFIG_COMMAND_OPT, FR_CMD_OPT_MASK, 0))) return rc;
    if ((rc = wr(FR_DPU + FR_OUTPUT0, FR_OUTPUT0_WORK_MODE_CMD))) return rc;
    if ((rc = rmw_q(FR_BE_INTR_ENABLE, 0, FR_INT_FRM_START | FR_INT_FRM_DONE | FR_INT_UNDERRUN | FR_INT_TE_RISE))) return rc;
    if ((rc = wr(FR_DPU + FR_OUTPUT0_START, 1))) return rc;
    if ((rc = wr(FR_DPU + FR_BE_INTR_STATUS, FR_INT_TE_RISE))) return rc;
    return 0;
}
static int te_seen(uint32_t id, int *hit)
{
    uint32_t v = 0; int rc = poll(FR_DPU + FR_BE_INTR_STATUS, FR_INT_TE_RISE, FR_INT_TE_RISE, 50000, &v, hit);
    if (!rc) note(id, *hit ? 1 : 0);
    return rc;
}
static int pad_read(uint32_t *param, uint32_t *dmux, uint32_t *tx)
{
    uint32_t rx = 0; int rc;
    if ((rc = rd(TE_PAD + PAD_PARAM, param))) return rc;
    note(DCS_N_PAD_PARAM, *param);
    if ((rc = rd(TE_PAD + PAD_DMUX, dmux))) return rc;
    note(DCS_N_PAD_DMUX, *dmux);
    if ((rc = rd(TE_PAD + PAD_TXDATA, tx))) return rc;
    note(DCS_N_PAD_TXDATA, *tx);
    if ((rc = rd(TE_PAD + PAD_RXDATA, &rx))) return rc;
    note(DCS_N_PAD_RXDATA, rx);
    return 0;
}
static int te_found; /* TE arrived untouched: the pad is left alone, and only read after the frames */
/* One new variable. The block has never been touched and stock Linux doesn't bind it, so it is only opened if TE is absent. Writes only the
 * fields of the FDT's disp0_2_ap_te state that differ, in the driver's order: mux, then input, output off, pull open then down. Never a gate. */
static int stage_t(void)
{
    uint32_t p = 0, m = 0, tx = 0; int rc, hit = 0;
    stage(DCS_S_T_TE_PAD);
    if ((rc = te_seen(DCS_N_TE_SEEN, &hit))) return rc;
    te_found = hit;
    if (hit) return 0;
    if ((rc = pad_read(&p, &m, &tx))) return rc;
    if (m == PAD_DMUX_DPU_TE && (p & PAD_IE) && !(tx & PAD_OE) && (tx & PAD_PUPD_MASK) == PAD_PUPD_PD) { note(DCS_N_PAD_WRITTEN, 0); return 0; }
    note(DCS_N_PAD_WRITTEN, 1);
    if (m != PAD_DMUX_DPU_TE && (rc = wr(TE_PAD + PAD_DMUX, PAD_DMUX_DPU_TE))) return rc;
    if (!(p & PAD_IE) && (rc = wr(TE_PAD + PAD_PARAM, p | PAD_IE))) return rc;
    if ((tx & PAD_OE) || (tx & PAD_PUPD_MASK) != PAD_PUPD_PD) {
        if ((rc = wr(TE_PAD + PAD_TXDATA, tx & ~(PAD_OE | PAD_PUPD_MASK)))) return rc;
        dcs_port_delay_us(PAD_OPEN_SETTLE_US);
        if ((rc = wr(TE_PAD + PAD_TXDATA, (tx & ~(PAD_OE | PAD_PUPD_MASK)) | PAD_PUPD_PD))) return rc;
    }
    if ((rc = pad_read(&p, &m, &tx))) return rc;
    if ((rc = wr(FR_DPU + FR_BE_INTR_STATUS, FR_INT_TE_RISE))) return rc;
    return te_seen(DCS_N_TE_SEEN_AFTER, &hit);
}
/* bmea_enable: PPS, then 0x9D 0x01. Then read the PPS back, because it must match what the encoder just got. */
static int stage_l(void)
{
    uint32_t n = 0; int rc;
    stage(DCS_S_L_PANEL_DSC);
    note(DCS_N_PPS_BEFORE_SAME, pps_before_same); /* 1: ABL's PPS already equals the source in 0-88, so a read-back can't show that our write landed */
    if ((rc = dcs_long(0x0a, fr_pps, 128))) return rc;
    if ((rc = cri_idle())) return rc;
    if ((rc = wr(DSI + DSI_CRI_TX_HDR, 0x15u | 0x9du << 8 | 0x01u << 16 | d.tx_mode))) return rc;
    if ((rc = cri_idle()) || (rc = int_status())) return rc;
    if ((rc = pps_read(DCS_N_PPS_AFTER, &n))) return rc;
    if (n == 90) for (unsigned i = 0; i < PPS_COMPARE_BYTES; ++i) if (pps_buf[i] != fr_pps[i]) return stop_with(DCS_C_PPS, i);
    if (n == 90) note(DCS_N_PPS_BYTE89, pps_buf[89]);
    return 0;
}
static int diag(void)
{
    static const uint32_t regs[] = { FR_BE_INTR_STATUS, FR_SH_OUTPUT0_CURRENT_COORD, FR_DSC_GEN_STATUS, FR_DSC_HSLICE_STATUS, FR_DSC_OUT_STATUS, FR_DSC_INT_STAT };
    uint32_t v = 0; int rc;
    for (unsigned i = 0; i < sizeof regs / sizeof regs[0]; ++i) { if ((rc = rd(FR_DPU + regs[i], &v))) return rc; }
    if ((rc = rd(DSI + DSI_CORE_STATUS, &v)) || (rc = rd(DSI + DSI_MODE_STATUS, &v))) return rc;
    return rd(DSI + DSI_INT_IPI, &v);
}
#if TGL_FRAME_RUNG >= 3
/* Portable part, for the kernel backend: frame_layer_config once, frame_set_buffer whenever the address changes, inside the shadow window. plane_set_fb, _pos, _std_bld, _sram, _outpath. */
static int frame_layer_config(uint32_t x, uint32_t y, uint32_t w, uint32_t h)
{
    int rc;
    for (unsigned i = 0; i < sizeof fr_fe0 / sizeof fr_fe0[0]; ++i) if ((rc = wr(FR_DPU + fr_fe0[i].off, fr_fe0[i].val))) return rc;
    if ((rc = wr(FR_DPU + FR_SH_LAYER0_SIZE, w | h << FR_SIZE_H_SHIFT))) return rc;
    if ((rc = wr(FR_DPU + FR_SH_LAYER0_OUT_ROI_ORIGIN, x | y << FR_ROI_Y_SHIFT))) return rc;
    if ((rc = wr(FR_DPU + FR_SH_LAYER0_OUT_ROI_SIZE, w | h << FR_ROI_H_SHIFT))) return rc;
    if ((rc = rmw_q(FR_SH_LAYER0_ALPHA_BLEND_CONFIG, FR_ALPHA_BLEND_BIT, 0))) return rc;
    if ((rc = rmw_q(FR_SH_LAYER0_CONFIG, FR_LAYER_CFG_MASK, FR_LAYER_CFG_XR24))) return rc;
    return wr(FR_DPU + FR_FE0_INTR_ENABLE, FR_FE0_INTR_MASK);
}
/* vs_dc_info: 40-bit address, 256-aligned. xnu-fb-r1's admission: stride 64-aligned. */
static int frame_set_buffer(uint64_t pa, uint32_t stride)
{
    int rc;
    if ((pa & 0xff) || (pa >> 40) || (stride & 0x3f) || !stride) return stop_with(DCS_C_BAD_BUFFER, (uint32_t)pa);
    if ((rc = wr(FR_DPU + FR_SH_LAYER0_ADDRESS, (uint32_t)pa)) || (rc = wr(FR_DPU + FR_SH_LAYER0_HIGH_ADDRESS, (uint32_t)(pa >> 32)))) return rc;
    return wr(FR_DPU + FR_SH_LAYER0_STRIDE, stride);
}
/* The record says what the fetch will meet. No write: if the SMMU is on or aborting, stop, and the next image is that one variable. */
static int stage_s(void)
{
    static const uint32_t regs[] = { SMMU_IDR0, SMMU_CR0, SMMU_CR0ACK, SMMU_GBPA, SMMU_GERROR, SMMU_GERRORN, SMMU_STRTAB_BASE };
    uint32_t v = 0, ack = 0, gbpa = 0; int rc;
    stage(DCS_S_S_SMMU);
    for (unsigned i = 0; i < sizeof regs / sizeof regs[0]; ++i) {
        if ((rc = rd(DPU_SMMU + regs[i], &v))) return rc;
        note(DCS_N_SMMU, v);
        if (regs[i] == SMMU_CR0ACK) ack = v;
        if (regs[i] == SMMU_GBPA) gbpa = v;
    }
    if (ack & SMMU_CR0_EN) return stop_with(DCS_C_SMMU_ON, ack);
    if (gbpa & SMMU_GBPA_ABORT) {
        /* Only if it would abort the fetch. arm_smmu_update_gbpa, with the SMMU disabled: clear ABORT, set UPDATE, wait for UPDATE to clear. */
        int hit = 0;
        note(DCS_N_SMMU_BYPASS_SET, gbpa);
        if ((rc = poll(DPU_SMMU + SMMU_GBPA, SMMU_GBPA_UPDATE, 0, 10000, 0, &hit))) return rc;
        if (!hit) return stop_with(DCS_C_SMMU_ABORT, gbpa);
        if ((rc = wr(DPU_SMMU + SMMU_GBPA, (gbpa & ~SMMU_GBPA_ABORT) | SMMU_GBPA_UPDATE))) return rc;
        if ((rc = poll(DPU_SMMU + SMMU_GBPA, SMMU_GBPA_UPDATE, 0, 10000, &gbpa, &hit))) return rc;
        note(DCS_N_SMMU, gbpa);
        if (!hit || (gbpa & SMMU_GBPA_ABORT)) return stop_with(DCS_C_SMMU_ABORT, gbpa);
    }
    return 0;
}
/* A: red, green, blue stripes over white, a centred rectangle that no test pattern makes. Bands are 119 rows, so at least 3/16 of the panel stays white for OPR. B: black.
 * Clean and invalidate first: the shim writes past the cache, and a dirty line left by ABL could later land on top. */
static int fill(uint64_t pa, int white)
{
    uint64_t t0 = dcs_port_now_us();
    dcs_port_civac(pa, (uint64_t)LAYER_H * LAYER_STRIDE);
    for (uint32_t y = 0; y < LAYER_H; ++y) {
        if (dcs_port_now_us() - d.t0 > BUDGET_US) return stop_with(DCS_C_BUDGET, y);
        uint64_t v = UINT64_C(0xff000000ff000000);
        if (white) { uint32_t c = y < 119u ? 0xffff0000u : y < 238u ? 0xff00ff00u : y < 357u ? 0xff0000ffu : 0xffffffffu; v = (uint64_t)c << 32 | c; }
        for (uint32_t x = 0; x + 1 < LAYER_W; x += 2) dcs_port_store64(pa + y * LAYER_STRIDE + x * 4u, v);
        if (!(y & 31)) dcs_port_service();
    }
    BARRIER();
    note(DCS_N_FILL_MS, (uint32_t)((dcs_port_now_us() - t0) / 1000u));
    return 0;
}
#ifdef TGL_DCS_MENU
/* ios26-dualboot-r8 chooser: the menu the shim already drew at MENU_FB, as one full-panel XR24 layer. No fill here. */
static int stage_menu(void)
{
    int rc;
    stage(DCS_S_F0_LAYER);
    if ((rc = reg_switch(0))) return rc;
    if ((rc = wr(FR_DPU + FR_SH_PANEL0_POST_PRO_TP_ENABLE, 0))) return rc;
    if ((rc = frame_layer_config(0, 0, MENU_W, MENU_H))) return rc;
    return frame_set_buffer(MENU_FB, MENU_STRIDE);
}
#endif
__attribute__((unused)) static int stage_f0(void)
{
    int rc;
    stage(DCS_S_F0_LAYER);
    if ((rc = fill(FB_A, 1)) || (rc = fill(FB_B, 0))) return rc;
    if ((rc = reg_switch(0))) return rc;
    if ((rc = wr(FR_DPU + FR_SH_PANEL0_POST_PRO_TP_ENABLE, 0))) return rc;
    if ((rc = frame_layer_config(LAYER_X, LAYER_Y, LAYER_W, LAYER_H))) return rc;
    return frame_set_buffer(FB_B, LAYER_STRIDE);
}
#endif
/* dc_hw_start_trigger for command mode: shadow off, values, shadow on, clear start, mux, OUTPUT_START, SW_CONFIG. Then wait for done. */
static int kick(uint32_t colour)
{
    uint32_t v = 0; int rc, hit;
    if ((rc = reg_switch(0))) return rc;
#if TGL_FRAME_RUNG >= 3 && defined(TGL_DCS_MENU)
    (void)colour;
    if ((rc = frame_set_buffer(MENU_FB, MENU_STRIDE))) return rc;
#elif TGL_FRAME_RUNG >= 3
    if ((rc = frame_set_buffer(colour ? FB_A : FB_B, LAYER_STRIDE))) return rc;
#else
    if ((rc = wr(FR_DPU + FR_SH_PANEL0_POST_PRO_TP_COLOR_RED, colour)) || (rc = wr(FR_DPU + FR_SH_PANEL0_POST_PRO_TP_COLOR_GREEN, colour)) || (rc = wr(FR_DPU + FR_SH_PANEL0_POST_PRO_TP_COLOR_BLUE, colour))) return rc;
#endif
    if ((rc = reg_switch(1))) return rc;
    if ((rc = wr(FR_DPU + FR_BE_INTR_STATUS, FR_INT_FRM_START | FR_INT_FRM_DONE | FR_INT_UNDERRUN))) return rc;
    if ((rc = wr(FR_DPU + FR_OUTIF_OFIFO_CRC_START, 1)) || (rc = wr(FR_DPU + FR_PANEL0_CRC_START, 1))) return rc;
    if ((rc = wr(FR_DPU + FR_POST_PROCESS_OUT, FR_POST_RESET))) return rc;
    if ((rc = wr(FR_DPU + FR_OUTPUT0_START, 1)) || (rc = wr(FR_DPU + FR_OUTPUT0_SW_CONFIG, 1))) return rc;
    { uint32_t q = d.quiet; d.quiet = 1;
    rc = poll(FR_DPU + FR_BE_INTR_STATUS, FR_INT_FRM_DONE, FR_INT_FRM_DONE, FRAME_DONE_US, &v, &hit);
    d.quiet = q; }
    if (rc) return rc;
    note(DCS_N_FRAME_STATUS, v);
#if TGL_FRAME_RUNG >= 3
    { uint32_t fe = 0;
      if ((rc = rdq(FR_DPU + FR_FE0_INTR_STATUS, &fe))) return rc;
      note(DCS_N_FE0_STATUS, fe);
      if (fe && (rc = wr(FR_DPU + FR_FE0_INTR_STATUS, fe))) return rc;
      if (fe & FR_FE_BUS_ERRORS) { (void)diag(); return stop_with(DCS_C_FE_BUS, fe); } }
#endif
    if (!hit) { (void)diag(); return stop_with(DCS_C_NO_FRAME_DONE, v); }
    return 0;
}
static uint32_t slot_white(unsigned i) { return i == 0 ? 0 : i == 1 ? 1 : (pattern >> (7u - i)) & 1u; } /* i 2..5: the nonce's top 4 pattern bits */
__attribute__((unused)) static int stage_m(void)
{
    static const uint32_t crcs[] = { FR_PANEL0_OFIFO_INPUT_RED_CRC_VALUE, FR_PANEL0_OFIFO_INPUT_GREEN_CRC_VALUE, FR_PANEL0_OFIFO_INPUT_BLUE_CRC_VALUE, FR_OUTPUT0_OFIFO_RED0_CRC_VALUE, FR_OUTPUT0_OFIFO_GREEN0_CRC_VALUE, FR_OUTPUT0_OFIFO_BLUE0_CRC_VALUE };
    uint32_t v = 0, n; int rc, ok; uint8_t b = 0;
    stage(DCS_S_M_FRAMES);
    for (unsigned s = 0; s < TGL_FRAME_SLOTS; ++s) {
        uint32_t c = slot_white(s) ? 0xffffu : 0;
        entry(DCS_K_SLOT, s, c);
        for (unsigned f = 0; f < TGL_FRAME_KICKS; ++f) {
#if TGL_FRAME_RUNG >= 3
            d.quiet = s >= 2 || f > 0; /* the record keeps the first full kick of the first two slots; the rest would fill it */
            rc = kick(c);
            d.quiet = 0;
            if (rc) return rc;
#else
            if ((rc = kick(c))) return rc;
#endif
            wait_ms(TGL_FRAME_GAP_MS);
        }
        for (unsigned i = 0; i < sizeof crcs / sizeof crcs[0]; ++i) {
            if ((rc = rdq(FR_DPU + crcs[i], &v))) return rc;
            note(DCS_N_CRC, v);
        }
        wait_ms(TGL_FRAME_DWELL_MS);
        if ((rc = opr_read(&v, &ok))) return rc;
    }
    if ((rc = diag())) return rc;
    if (te_found) { uint32_t p, m, tx; if ((rc = pad_read(&p, &m, &tx))) return rc; }
    if ((rc = wr(FR_DPU + FR_OUTPUT0_START, 0))) return rc;
    if ((rc = dcs_read(0x0a, &b, 1, &n, d.tx_mode)) > 0) return rc;
    if (!rc) note(DCS_N_POWER_MODE_AFTER, b);
    if ((rc = dcs_read(0x05, &b, 1, &n, d.tx_mode)) > 0) return rc;
    if (!rc) note(DCS_N_ERR_COUNT_AFTER, b);
    return 0;
}
#endif

#ifdef TGL_DCS_HOSTTEST
int dcs_test_pa_ok(uint64_t pa, int wr) { return pa_ok(pa, wr); }
#if TGL_FRAME_RUNG >= 3
int dcs_test_set_buffer(uint64_t pa, uint32_t stride) { int rc = frame_set_buffer(pa, stride); d.stop = 0; return rc; }
#endif
#if TGL_DCS_BRIGHT
int dcs_test_bright_long(uint32_t di, uint32_t len, int other) { static const uint8_t x[3] = { 0x51, 0x12, 0x1d }; int rc = dcs_long(di, other ? x : k_bright, len); d.stop = 0; return rc; }
#endif
#endif
void tgl_dcs_begin(uint64_t stamp_nonce, const uint8_t record_nonce[16], uint64_t epoch)
{
    static const uint8_t magic[8] = { 'F', 'R', 'M', 'R', '1', 'L', 'O', 'G' };
    volatile uint8_t *p = dcs_port_record();
    d.seq = 0; d.stop = 0; d.quiet = 0; d.stage = DCS_S_ADMIT; d.tx_mode = HDR_LP; d.started = 0; ref_hz = 0;
    d.seal = (uint32_t)stamp_nonce;
    pattern = tgl_dcs_pattern(stamp_nonce);
    for (unsigned i = 0; i < TGL_DCS_RECORD_BYTES; i += 4) rec32(i, 0);
    BARRIER();
    rec32(8, (uint32_t)stamp_nonce); rec32(12, (uint32_t)(stamp_nonce >> 32));
    for (unsigned i = 0; i < 16; ++i) p[16 + i] = record_nonce[i];
    rec32(32, (uint32_t)epoch); rec32(36, (uint32_t)(epoch >> 32));
    rec32(40, pattern); rec32(56, 2); rec32(60, TGL_FRAME_RUNG);
    BARRIER();
    for (unsigned i = 0; i < 8; ++i) p[i] = magic[i];
    BARRIER();
    d.t0 = dcs_port_now_us();
    stage(DCS_S_ADMIT);
}
int tgl_dcs_run(void)
{
    int rc;
    if (d.started) return stop_with(DCS_C_REFUSED_PA, 0xffffffffu);
    d.started = 1;
    if ((rc = stage_a()) || (rc = stage_b()) || (rc = stage_c()) || (rc = stage_d()) || (rc = stage_e()) || (rc = stage_f()) || (rc = stage_g()) || (rc = stage_h()) || (rc = stage_i())) return rc;
#if TGL_FRAME_RUNG >= 2
    if ((rc = stage_j()) || (rc = stage_k()) || (rc = stage_t()) || (rc = stage_l())) return rc;
#ifdef TGL_DCS_HANDOFF
    /* ios26-display-r1: leave the panel configured for XNU. One test-pattern kick proves the path, then the record is the kernel's permission. No paint, no slots, no OUTPUT0_START=0. */
    if ((rc = stage_s())) return rc;
    if ((rc = kick(0))) return rc;
    tgl_scanout_takeover_publish(HAKIOS_TK_REQUIRED, ref_hz, d.tx_mode == HDR_LP, (uint32_t)te_found, 1, VS_CHIP_ID_9400, handoff_rev);
#elif defined(TGL_DCS_MENU) && TGL_FRAME_RUNG >= 3
    /* chooser: one kick shows the menu; tgl_dcs_present() kicks again after each redraw. */
    if ((rc = stage_s()) || (rc = stage_menu()) || (rc = kick(1))) return rc;
#else
#if TGL_FRAME_RUNG >= 3
    if ((rc = stage_s()) || (rc = stage_f0())) return rc;
#endif
    if ((rc = stage_m())) return rc;
#endif
#endif
    return 0;
}
#if defined(TGL_DCS_MENU) && TGL_FRAME_RUNG >= 3
int tgl_dcs_present(void)
{
    if (!d.started || d.stop) return DCS_C_REFUSED_PA;
    return kick(1);
}
#endif
void tgl_dcs_refuse(int s, int code, uint32_t detail) { d.stage = s; (void)stop_with(code, detail); }
void tgl_dcs_finish(int code, uint64_t esr, uint64_t far, uint64_t wdt_stop)
{
    if (esr) { note(DCS_N_ESR, (uint32_t)esr); note(DCS_N_FAR, (uint32_t)far); }
    note(DCS_N_WDT_STOP, (uint32_t)wdt_stop);
    d.stage = DCS_S_N_DONE;
    entry(DCS_K_END, (uint32_t)code, d.seq);
    rec32(__builtin_offsetof(struct hdr, final), (uint32_t)code);
    rec32(__builtin_offsetof(struct hdr, final_seal), (uint32_t)code ^ d.seal ^ 0x444f4e45u);
    BARRIER();
}
#ifndef TGL_DCS_HOSTTEST
unsigned tgl_dcs_guarded(void)
{
    static volatile int result;
    uint64_t was;
    __asm__ volatile("mrs %0, daif\n\tmsr daifset, #0xf\n\tisb" : "=r"(was) :: "memory"); /* an SError stays pending; after() sees ISR.A */
    (void)was;
    result = 0;
    tgl_guard_esr = 0; tgl_guard_far = 0; tgl_guard_armed = 1;
    tgl_guard_arm();
    if (!tgl_guard_esr) result = tgl_dcs_run();
    tgl_guard_armed = 0;
    if (tgl_guard_esr) return DCS_C_GUARD_FAULT;
    return (unsigned)result;
}
#endif
