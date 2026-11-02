/* Fake bus for tgl_dcs.c: mailbox service, DSI host, PHY, panel, DPU (a reading of the sources, not the hardware). Rejects any access it doesn't know. Host only.
 * From research/display-frame-r1/tests/host_dcs.c, plus: the panel's 0x51/0x52 register, a bus trace, the phone's TGL_DCS_HANDOFF flow.
 * tgl_dcs_bright_test <scenario> [record-out [trace-out]]. Prints PASS/FAIL and an R line; exit 1 on any failure. A fake says nothing about hardware. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "tgl_dcs.h"
#include "frame_tables.h"
#ifndef TGL_DCS_BRIGHT
#define TGL_DCS_BRIGHT 0 /* the header before this gate existed: golden traces */
#endif
int dcs_test_pa_ok(uint64_t pa, int wr);
int dcs_test_set_buffer(uint64_t pa, uint32_t stride);
int dcs_test_bright_long(uint32_t di, uint32_t len, int other);
#ifdef TGL_DCS_HANDOFF
#include "tensor_takeover.h"
volatile uint32_t dcs_test_takeover[HAKIOS_TAKEOVER_BYTES / 4];
#endif
#define NONCE UINT64_C(0xb400000012345678) /* pattern top 6 bits = 0b101101 */
static uint8_t rec[TGL_DCS_RECORD_BYTES];
static uint32_t cdphy[0x18000 / 4], dsi[0x800 / 4], apb[0x50 / 4], msg[4], st_done, ctl;
static uint64_t now_us; static unsigned acc;
static const char *sc;
static int fails;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s: %s (line %d)\n", sc, #c, __LINE__); fails++; } } while (0)
/* knobs */
static int top_polls, phy_ready = 1, pll_lock = 1, panel_lp = 1, panel_hs = 1, first_ack, mode_stuck, cri_stuck_after = -1, core_id = 0x3130302a, wrong_id;
static int mba_silent, mba_nack_dsi0, prepare_nack, rate_ref = 38400000, top_set_err, serror_at = -1, fault_at = -1, die_at = -1, pix_neg, magic_bad, top_weird;
static unsigned fake_power_top, fake_dsi0, fake_pix, fake_ref;
static unsigned lpb_sets;
static uint32_t *dpu; static unsigned fake_fe0, dpu_writes, dpu_accesses, kicks, frames_ok, panel_shown[16], shown_n;
static uint32_t pad[5] = { 0, 1, 0, 0, 0 }; static unsigned pad_writes, pad_reads; static int te_needs_pad, pad_die, pad_is_te;
static uint64_t store_a, store_b; static uint64_t px_mid_a, px_bar_r, px_bar_b, px_mid_b; static int smmu_on, smmu_abort, smmu_stuck, fe_bus, no_fetch, underrun_first, underrun_later; static uint32_t smmu_gbpa = 0x2e1f; static unsigned civacs, kick_n; static uint64_t px_white_b;
static int pps_ff89, pps_bad88;
static int fe0_nack, chip_bad, iso_stuck, pps_stale, pps_silent, pps_wrong_after, no_done, serror_dpu, opr_silent, crc_stuck, crc_zero, opr_stuck, no_te, die_first_dpu;
static uint8_t pld[256]; static unsigned pld_n; static uint8_t panel_pps[128]; static int pps_got, comp_on = 1, f0_open, fc_open, b0_opr, opr_white; static uint32_t rx_pld[40]; static unsigned rx_pld_n;
static uint32_t rx_q[8]; static unsigned rx_n; static int cri_writes;
/* panel brightness: what the panel holds, what a late latch will make it, and the write's circumstances */
static uint32_t panel_dbv = 0x295e, pending_dbv, power_mode = 0x9f; static uint64_t pending_at; static int pending, br_writes, br_at_dpu, br_at_fe0, br_at_open, br_latch_us, br_ignored, br_long, br_short, br_read_fail, br_cri_stuck, br_fault, br_serror, br_int, br_err; static int reads_52, br_ack, br_fault_cmd = -1, br_fault_skip, fault_next;
static FILE *tracef;
static void die(void) { FILE *f = fopen("/tmp/dcs-die", "w"); if (f) fclose(f); }
static int inject(void)
{
    acc++;
    if (die_at >= 0 && (int)acc == die_at) { /* async reset: keep the prefix, end here */
        extern void finish_and_exit(void); finish_and_exit();
    }
    return fault_at >= 0 && (int)acc == fault_at;
}
static void mba_service(void)
{
    uint32_t r[4] = { 0x08c00000u, 0, 0, 0 };
    uint32_t w0 = msg[0], w1 = msg[1], w2 = msg[2];
    if (mba_silent) return;
    if (w0 == 0x05000003u) { CHECK(w1 == 5); r[0] = 0x05000000; r[1] = 15; r[2] = top_weird ? 77 : (fake_power_top ? 2 : 1); if (top_polls > 0 && fake_power_top) { top_polls--; r[2] = 1; } }
    else if (w0 == 0x05000002u) { lpb_sets++; CHECK(w1 == 5 && w2 == 1); fake_power_top = 1; r[0] = 0x05000000; r[1] = top_set_err ? 16 : 15; r[2] = 18; r[3] = 5; }
    else if (w0 == 0x08000000u) {
        switch (w1) {
        case 0x01020001u: CHECK(fake_power_top); fake_dsi0 = 1; r[1] = mba_nack_dsi0 ? (uint32_t)-8 : 0; break;
        case 0x01000001u: CHECK(fake_dsi0); fake_fe0 = 1; r[1] = fe0_nack ? (uint32_t)-8 : 0; break;
        case 0x03022302u: r[1] = pix_neg ? (uint32_t)-3 : (fake_pix ? 150000000u : 0); break;
        case 0x03010602u: r[1] = fake_ref ? (uint32_t)rate_ref : (uint32_t)-3; break;
        case 0x00022302u: CHECK(w2 == 1); fake_pix = 1; r[1] = prepare_nack ? (uint32_t)-24 : 0; break;
        case 0x00010602u: CHECK(w2 == 1); fake_ref = 1; break;
        default: CHECK(!"unknown LPCM frame");
        }
    } else CHECK(!"unknown frame");
    memcpy(msg, r, sizeof r);
    st_done = 1;
}
static int panel_answers(uint32_t hdr) { return (hdr & (1u << 24)) ? panel_lp : panel_hs; }
static void rx_long(const uint8_t *b, unsigned n)
{
    rx_q[rx_n++] = 0x1c | n << 8; rx_pld_n = 0;
    for (unsigned i = 0; i < n; i += 4) { uint32_t w = 0; for (unsigned k = 0; k < 4 && i + k < n; ++k) w |= (uint32_t)b[i + k] << (8 * k); rx_pld[rx_pld_n++] = w; }
}
static void dsi_tx(uint32_t h)
{
    uint32_t di = h & 0xff, cmd = (h >> 8) & 0xff;
    cri_writes++;
    if (di == 0x37) return;
    if (di == 0x06) {
        CHECK(h & (1u << 28));
        if (br_writes && (int)cmd == br_fault_cmd) { if (br_fault_skip) br_fault_skip--; else fault_next = 1; } /* the next read of the host faults */
        if (!panel_answers(h)) return;
        if (first_ack) { first_ack--; rx_q[rx_n++] = 0x02 | 0x20u << 16; return; }
        uint32_t b;
        switch (cmd) {
        case 0x0a: b = power_mode; break; case 0x05: b = br_err && br_writes ? (uint32_t)br_err : 0; break; case 0xda: b = 0x0a; break; case 0xdb: b = wrong_id ? 0x11 : 0xa0; break; case 0xdc: b = 0xa1; break; case 0xa1: b = 0x42; break;
        case 0x03: b = comp_on; break;
        case 0x52: {
            reads_52++;
            if (pending && now_us >= pending_at) { panel_dbv = pending_dbv; pending = 0; }
            if (br_ack && br_writes && reads_52 == 2) { rx_q[rx_n++] = 0x02 | 0x20u << 16; return; }
            /* read 1 is stage G's; br_read_fail: bit n set, read n+1 goes unanswered */
            if (br_read_fail & (1 << (reads_52 - 1))) return;
            if (br_short && br_writes) { rx_q[rx_n++] = 0x21 | (panel_dbv >> 8) << 8; return; }
            if (br_long) { uint8_t o[2] = { (uint8_t)(panel_dbv >> 8), (uint8_t)panel_dbv }; rx_long(o, 2); return; }
            rx_q[rx_n++] = 0x22 | (panel_dbv >> 8) << 8 | (panel_dbv & 0xff) << 16; return; }
        case 0xa2: {
            if (pps_silent) return;
            static uint8_t stale[90]; memset(stale, 0x77, sizeof stale);
            if (pps_got && pps_wrong_after) { memcpy(stale, panel_pps, 90); stale[17] ^= 1; rx_long(stale, 90); }
            else if (pps_ff89 || pps_bad88) { memcpy(stale, fr_pps, 90); if (pps_ff89) stale[89] = 0xff; if (pps_bad88 && pps_got) stale[88] ^= 1; rx_long(stale, 90); } /* as the phone: 0xff, before and after */
            else rx_long(pps_got ? panel_pps : (pps_stale ? stale : fr_pps), 90);
            return; }
        case 0x63: {
            CHECK(f0_open && fc_open && b0_opr); b0_opr = 0;
            if (opr_silent) return;
            uint32_t v = opr_stuck ? 0x123 : (opr_white ? 0x7ff : 0x010); uint8_t o[2] = { (uint8_t)(v >> 8), (uint8_t)v }; rx_long(o, 2);
            return; }
        default: CHECK(!"unexpected read cmd"); b = 0;
        }
        rx_q[rx_n++] = 0x21 | b << 8;
        return;
    }
    if (di == 0x15) { CHECK(cmd == 0x9d && ((h >> 16) & 0xff) == 1); CHECK(pps_got); comp_on = 1; return; }
    if (di == 0x39 || di == 0x0a) {
        unsigned len = (h >> 8) & 0xffff;
        CHECK(h & (1u << 29)); CHECK(len == pld_n || (len + 3) / 4 * 4 == pld_n);
        if (di == 0x0a) { CHECK(len == 128); memcpy(panel_pps, pld, 128); pps_got = 1; CHECK(!memcmp(panel_pps, fr_pps, 128)); CHECK(panel_pps[0] == 0x12 && panel_pps[6] == 0x0b && panel_pps[7] == 0x28 && panel_pps[8] == 0x05); }
        else if (pld[0] == 0xf0) { CHECK(pld[1] == pld[2] && (pld[1] == 0x5a || pld[1] == 0xa5)); f0_open = pld[1] == 0x5a; }
        else if (pld[0] == 0xfc) { CHECK(pld[1] == pld[2] && (pld[1] == 0x5a || pld[1] == 0xa5)); fc_open = pld[1] == 0x5a; }
        else if (pld[0] == 0xb0) { CHECK(f0_open && fc_open); CHECK(pld[1] == 1 && pld[2] == 0x1a && pld[3] == 0x63); b0_opr = 1; }
        else if (pld[0] == 0x51 && TGL_DCS_BRIGHT) {
            CHECK(len == 3); CHECK(pld_n == 4); CHECK(pld[3] == 0);
            br_writes++; br_at_dpu = (int)dpu_accesses; br_at_fe0 = (int)fake_fe0; br_at_open = f0_open || fc_open;
            uint32_t v = (uint32_t)pld[1] << 8 | pld[2];
            if (br_int) dsi[0x14 / 4] = 0x4; /* an error raised by the packet */
            if (!br_ignored) { if (br_latch_us) { pending = 1; pending_dbv = v; pending_at = now_us + (uint64_t)br_latch_us; } else panel_dbv = v; }
            if (br_cri_stuck) cri_stuck_after = 0;
            if (br_serror) serror_at = 0;
        }
        else CHECK(!"forbidden long write");
        pld_n = 0;
        return;
    }
    CHECK(!"unexpected packet");
}
static uint32_t D(uint32_t off) { return dpu[off / 4]; }
static void dpu_kick(void)
{
    kicks++;
    /* A frame runs only with the source's whole config in place. */
    if (D(FR_OUTPUT0) != 2 || !D(0xb60b4) || D(0xb6060) != 0xb || D(0xb6064) != 5 || D(0xb6024) != 1280 || D(0xb6038) != 2856 || D(0xb6020) != 80 || D(0xb602c) != 24 || D(0xb6028) != 46 || D(0xb6034) != 12 || D(0xb6040) != 4 || D(0xb603c) != 28) return;
#ifdef TGL_DCS_HANDOFF
    if (D(0x909cc) != 1280 || D(0x909d0) != 2856 || D(0x88294) != 1280 || D(0x88298) != 2856 || D(0xbc038) != 0 || D(0x8c028) != 0 || D(0x909bc) != 2) return;
#else
    if (D(0x909cc) != 1280 || D(0x909d0) != 2856 || D(0x88294) != 1280 || D(0x88298) != 2856 || D(0xbc034) != (TGL_FRAME_RUNG >= 3 ? 0 : 1) || D(0xbc038) != 0 || D(0x8c028) != 0 || D(0x909bc) != 2) return;
#endif
    if (D(0xf9134) != (2856u << 16 | 1280) || D(0xf9138) != (24u << 16 | 640)) return;
    if (D(FR_CLOCK_DOMAIN_ISOLATION) & 1) return;
    if (!(D(FR_PANEL0_CONFIG) & 1) || !(D(FR_OUTPUT0_CONFIG) & 1) || D(FR_OUTPUT0_CONFIG_COMMAND_OPT) & 3 || !D(FR_OUTPUT0_START) || D(FR_POST_PROCESS_OUT) != 0x4320) return;
    if (no_done) { dpu[FR_BE_INTR_STATUS / 4] |= FR_INT_FRM_START; return; }
#ifdef TGL_DCS_HANDOFF
    uint32_t r = 0; /* the test pattern; the kernel paints */
#elif TGL_FRAME_RUNG >= 3
    /* Layer in place: XR24 linear on, TP off, size, position, shadow on, path 0. */
    if (D(FR_SH_PANEL0_POST_PRO_TP_ENABLE) || (D(FR_SH_LAYER0_CONFIG) & 0x3f7f3801u) != 0x01000001u || D(FR_SH_LAYER0_SIZE) != (1428u << 16 | 640) || D(FR_SH_LAYER0_OUT_ROI_ORIGIN) != (714u << 16 | 320) || D(FR_SH_LAYER0_OUT_ROI_SIZE) != (1428u << 16 | 640) || !(D(FR_LAYER0_CONFIG) & 1) || D(FR_SH_LAYER0_STRIDE) != 2560 || D(FR_SH_LAYER0_HIGH_ADDRESS) || D(FR_SH_LAYER0_ALPHA_BLEND_CONFIG) & 1 || D(0xd7000)) return;
    if (D(FR_SH_LAYER0_ADDRESS) != 0xf0000000u && D(FR_SH_LAYER0_ADDRESS) != 0xf0e00000u) return;
    if (no_fetch) { dpu[FR_BE_INTR_STATUS / 4] |= FR_INT_FRM_START; return; }
    if (fe_bus) { dpu[FR_FE0_INTR_STATUS / 4] |= 1u << 14; return; }
    dpu[FR_FE0_INTR_STATUS / 4] |= FR_FE_LAYER_DONE;
    CHECK(store_a == 640u * 1428u / 2 && store_b == store_a); /* painted first */
    uint32_t r = D(FR_SH_LAYER0_ADDRESS) == 0xf0000000u ? 0xffff : 0;
#else
    uint32_t r = D(FR_SH_PANEL0_POST_PRO_TP_COLOR_RED); CHECK(r == D(FR_SH_PANEL0_POST_PRO_TP_COLOR_GREEN) && r == D(FR_SH_PANEL0_POST_PRO_TP_COLOR_BLUE)); CHECK(r == 0 || r == 0xffff);
#endif
    dpu[FR_BE_INTR_STATUS / 4] |= FR_INT_FRM_START | FR_INT_FRM_DONE;
    if ((underrun_first && kick_n % 3 == 0) || (underrun_later && kick_n % 3 == 2)) dpu[FR_BE_INTR_STATUS / 4] |= FR_INT_UNDERRUN;
    kick_n++;
    uint32_t base = crc_zero ? 0 : crc_stuck ? 0xabcd0000u : (r ? 0x11110000u : 0x22220000u);
    dpu[FR_PANEL0_OFIFO_INPUT_RED_CRC_VALUE / 4] = base + 1; dpu[FR_PANEL0_OFIFO_INPUT_GREEN_CRC_VALUE / 4] = base + 2; dpu[FR_PANEL0_OFIFO_INPUT_BLUE_CRC_VALUE / 4] = base + 3;
    dpu[FR_OUTPUT0_OFIFO_RED0_CRC_VALUE / 4] = base + 4; dpu[FR_OUTPUT0_OFIFO_GREEN0_CRC_VALUE / 4] = base + 5; dpu[FR_OUTPUT0_OFIFO_BLUE0_CRC_VALUE / 4] = base + 6;
    if (crc_zero) { dpu[FR_PANEL0_OFIFO_INPUT_RED_CRC_VALUE / 4] = dpu[FR_PANEL0_OFIFO_INPUT_GREEN_CRC_VALUE / 4] = dpu[FR_PANEL0_OFIFO_INPUT_BLUE_CRC_VALUE / 4] = 0; dpu[FR_OUTPUT0_OFIFO_RED0_CRC_VALUE / 4] = dpu[FR_OUTPUT0_OFIFO_GREEN0_CRC_VALUE / 4] = dpu[FR_OUTPUT0_OFIFO_BLUE0_CRC_VALUE / 4] = 0; }
    frames_ok++;
    if (comp_on && pps_got) opr_white = r != 0;
    if (shown_n < 16) panel_shown[shown_n++] = r;
}
static void dpu_access(void)
{
    dpu_accesses++;
    if (!(fake_power_top && fake_dsi0 && fake_fe0)) { printf("FAIL %s: DPU access before power\n", sc); fails++; }
}
static int read32_(uintptr_t pa, uint32_t *v);
int dcs_port_read32(uintptr_t pa, uint32_t *v)
{
    if (inject()) return -1;
    if (fault_next) { fault_next = 0; return -1; }
    now_us += 1;
    int rc = read32_(pa, v);
    if (tracef) fprintf(tracef, "R %lx %x\n", (unsigned long)pa, *v);
    return rc;
}
static int read32_(uintptr_t pa, uint32_t *v)
{
    if (pa == 0x05250000) { *v = magic_bad ? 0 : 0x004d4241; return 0; }
    if (pa == 0x05272008) { *v = st_done; return 0; }
    if (pa == 0x05272004) { *v = ctl; return 0; }
    if (pa >= 0x05272100 && pa < 0x05272110) { *v = msg[(pa - 0x05272100) / 4]; return 0; }
    if (pa >= 0x0ed80000 && pa < 0x0edc0000) {
        CHECK(fake_power_top); uint32_t o = (uint32_t)(pa - 0x0ed80000);
        *v = o == 0x24 || o == 0x20 ? (uint32_t)smmu_on : o == 0x44 ? smmu_gbpa : 0; return 0;
    }
    if (pa >= 0x0ec7e000 && pa < 0x0ec80000) {
        if (pad_die) { extern void finish_and_exit(void); finish_and_exit(); }
        CHECK(fake_power_top); pad_reads++; CHECK(pa < 0x0ec7e014); *v = pad[(pa - 0x0ec7e000) / 4]; return 0;
    }
    if (pa >= FR_DPU && pa < FR_DPU + 0x120000) {
        if (die_first_dpu) { extern void finish_and_exit(void); finish_and_exit(); }
        dpu_access();
        uint32_t o = (uint32_t)(pa - FR_DPU);
        if (o == FR_CHIP_ID) { *v = chip_bad ? 0 : 0x9400; return 0; }
        if (o == FR_CHIP_REV) { *v = 0x7002; return 0; }
        if (o == FR_PRODUCT_ID) { *v = 0x02094000; return 0; }
        if (o == FR_CHIP_CUSTOMER) { *v = 0x32a; return 0; }
        if (o == FR_POST_PROCESS_OUT && !dpu[o / 4]) { *v = 0x4320; return 0; }
        if (o == FR_BE_INTR_STATUS) { *v = dpu[o / 4] | ((no_te || (te_needs_pad && !(pad[1] == 2 && (pad[0] & 0x100) && (pad[2] & 0xb) == 1))) ? 0 : FR_INT_TE_RISE); return 0; }
        *v = dpu[o / 4]; return 0;
    }
    if (pa >= 0x0efd8000 && pa < 0x0efd8800) {
        CHECK(fake_dsi0); uint32_t o = (uint32_t)(pa - 0x0efd8000);
        if (o == 0x2cc) { CHECK(rx_pld_n > 0); *v = rx_pld_n ? rx_pld[0] : 0; if (rx_pld_n) memmove(rx_pld, rx_pld + 1, sizeof(uint32_t) * (--rx_pld_n)); return 0; }
        if (o == 0) { *v = (uint32_t)core_id; return 0; }
        if (o == 0x1c) { *v = mode_stuck ? 0 : (dsi[0x18 / 4] & 7); return 0; }
        if (o == 0x14) { *v = dsi[0x14 / 4]; dsi[0x14 / 4] = 0; return 0; } /* physical: 0x4 once in r1c, then 0 */
        if (o == 0x20) { uint32_t s = 0; if (cri_stuck_after >= 0 && cri_writes > cri_stuck_after) s |= 1u << 16; if (rx_n || rx_pld_n) s |= 1u << 18; *v = s; return 0; }
        if (o == 0x2c8) { CHECK(rx_n > 0); *v = rx_n ? rx_q[0] : 0; if (rx_n) { memmove(rx_q, rx_q + 1, sizeof(uint32_t) * (--rx_n)); } return 0; }
        *v = dsi[o / 4]; return 0;
    }
    if (pa >= 0x0efd8800 && pa < 0x0efd8850) {
        CHECK(fake_dsi0); uint32_t o = (uint32_t)(pa - 0x0efd8800);
        if (o == 0x24) { *v = (apb[0x28 / 4] & 3) == 3 ? (phy_ready ? 1u : 0) | (pll_lock ? 2u : 0) : 0; return 0; }
        *v = apb[o / 4]; return 0;
    }
    if (pa >= 0x0efc0000 && pa < 0x0efd8000) { CHECK(fake_dsi0); *v = cdphy[(pa - 0x0efc0000) / 4]; return 0; }
    printf("FAIL %s: forbidden read 0x%lx\n", sc, (unsigned long)pa); fails++; *v = 0; return -1;
}
static int write32_(uintptr_t pa, uint32_t v);
int dcs_port_write32(uintptr_t pa, uint32_t v)
{
    if (inject()) return -1;
    if (br_fault && pa == 0x0efd82c4 && (v & 0xff) == 0x51) return -1;
    now_us += 1;
    if (tracef) fprintf(tracef, "W %lx %x\n", (unsigned long)pa, v);
    return write32_(pa, v);
}
static int write32_(uintptr_t pa, uint32_t v)
{
    if (pa == 0x05272008) { st_done = 0; return 0; }
    if (pa == 0x05272004) { ctl = v; return 0; }
    if (pa >= 0x05272100 && pa < 0x05272110) { msg[(pa - 0x05272100) / 4] = v; return 0; }
    if (pa == 0x05272000) { CHECK(v == 1); mba_service(); return 0; }
    if (pa >= 0x0ed80000 && pa < 0x0edc0000) {
        CHECK(pa == 0x0ed80044); CHECK(v & (1u << 31)); CHECK(!(v & (1u << 20))); CHECK((v & 0xfff) == 0xe1f);
        if (!smmu_stuck) smmu_gbpa = v & ~(1u << 31);
        return 0;
    }
    if (pa >= 0x0ec7e000 && pa < 0x0ec80000) {
        CHECK(fake_power_top); pad_writes++; CHECK(pa == 0x0ec7e000 || pa == 0x0ec7e004 || pa == 0x0ec7e008);
        if (pa == 0x0ec7e008 && (v & 3) == 1 && (pad[2] & 3) != 0) CHECK(!"pull: open first, then down");
        pad[(pa - 0x0ec7e000) / 4] = v; return 0;
    }
    if (pa >= FR_DPU && pa < FR_DPU + 0x120000) {
        if (die_first_dpu) { extern void finish_and_exit(void); finish_and_exit(); }
        dpu_access(); dpu_writes++;
        uint32_t o = (uint32_t)(pa - FR_DPU);
        if (o == FR_BE_INTR_STATUS || o == FR_FE0_INTR_STATUS) { dpu[o / 4] &= ~v; return 0; }
        if (o == FR_CLOCK_DOMAIN_ISOLATION && iso_stuck) return 0;
        if (o == FR_OUTPUT0_SW_CONFIG) { CHECK(v == 1); dpu_kick(); return 0; }
        dpu[o / 4] = v; return 0;
    }
    if (pa >= 0x0efd8000 && pa < 0x0efd8800) {
        CHECK(fake_dsi0); uint32_t o = (uint32_t)(pa - 0x0efd8000);
        if (o == 0x2c4) { for (unsigned k = 0; k < 4; ++k) pld[pld_n++] = (uint8_t)(v >> (8 * k)); return 0; }
        if (o == 0x2c0) { dsi_tx(v); return 0; }
        dsi[o / 4] = v; return 0;
    }
    /* regmap_field_write only writes when the value changes */
    if (pa >= 0x0efd8800 && pa < 0x0efd8850) { CHECK(fake_dsi0); CHECK(apb[(pa - 0x0efd8800) / 4] != v); apb[(pa - 0x0efd8800) / 4] = v; return 0; }
    if (pa >= 0x0efc0000 && pa < 0x0efd8000) { CHECK(fake_dsi0); CHECK(cdphy[(pa - 0x0efc0000) / 4] != v); cdphy[(pa - 0x0efc0000) / 4] = v; return 0; }
    printf("FAIL %s: forbidden write 0x%lx\n", sc, (unsigned long)pa); fails++; return -1;
}
uint64_t dcs_port_now_us(void) { return now_us; }
void dcs_port_delay_us(uint32_t us) { now_us += us; }
uint64_t dcs_port_isr(void) { return (serror_at >= 0 && (int)acc >= serror_at) || (serror_dpu && dpu_accesses) ? 1u << 8 : 0; }
void dcs_port_store64(uint64_t pa, uint64_t v)
{
    const uint64_t A = 0xf0000000u, B = 0xf0e00000u, N = 2560u * 1428u; uint64_t row, col;
    if (pa & 7) CHECK(!"unaligned");
    if (pa >= A && pa < A + N) { store_a++; row = (pa - A) / 2560; col = (pa - A) % 2560 / 4; if (row == 700 && col == 320) px_mid_a = v; if (row == 10 && col == 0) px_bar_r = v; if (row == 300 && col == 638) px_bar_b = v; if (row == 200 && col == 2) px_white_b = v; CHECK(civacs >= 2 || store_a > 1 || civacs == 1); return; }
    if (pa >= B && pa < B + N) { store_b++; CHECK(civacs == 2); if (pa == B + 700 * 2560) px_mid_b = v; return; }
    CHECK(!"store outside the two test buffers");
}
void dcs_port_civac(uint64_t pa, uint64_t len) { CHECK(len == 2560u * 1428u); CHECK(pa == (civacs ? 0xf0e00000u : 0xf0000000u)); CHECK(!(civacs ? store_b : store_a)); civacs++; }
void dcs_port_service(void) { }
volatile uint8_t *dcs_port_record(void) { return rec; }
static const char *outp;
static void write_out(void) { if (outp) { FILE *f = fopen(outp, "wb"); if (f) { fwrite(rec, 1, sizeof rec, f); fclose(f); } } }
void finish_and_exit(void) { write_out(); if (tracef) fclose(tracef); printf("RESET-AT %u br_writes=%d\n", acc, br_writes); exit(fails ? 1 : 0); }
static const uint8_t RN[16] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16 };
static int want_code; static int want_frames = 1;
static void expect(int code, int frames) { want_code = code; want_frames = frames; }
int main(int argc, char **argv)
{
    sc = argv[1]; if (argc > 2) outp = argv[2];
    if (argc > 3) { tracef = fopen(argv[3], "w"); if (!tracef) return 3; }
    (void)die;
    dpu = calloc(0x120000 / 4, 4);
    dpu[FR_CLOCK_DOMAIN_ISOLATION / 4] = 0xf; dpu[FR_OUTPUT0 / 4] = 4; dpu[FR_OUTPUT0_CONFIG_COMMAND_OPT / 4] = 2;
    #define IS(x) (!strcmp(sc, x))
    expect(DCS_C_OK, 1);
    if (IS("ok") || IS("twice") || IS("allow")) { }
    else if (IS("br_dim")) { panel_dbv = 0x11b3; }
    else if (IS("br_zero")) { panel_dbv = 0; }
    else if (IS("br_long_reply")) { br_long = 1; }
    else if (IS("br_ignored")) { br_ignored = 1; }
    else if (IS("br_late")) { br_latch_us = 34000; }
    else if (IS("br_never_latches")) { br_latch_us = 2000000; }
    else if (IS("br_no_readback")) { br_read_fail = 0x6; }
    else if (IS("br_settled_read_fails")) { br_read_fail = 0x4; }
    else if (IS("br_at_write_read_fails")) { br_read_fail = 0x2; }
    else if (IS("br_before_read_fails")) { br_read_fail = 0x1; }
    else if (IS("br_short_reply")) { br_short = 1; }
    else if (IS("br_ack_then_ok")) { br_ack = 1; }
    else if (IS("br_int_flag")) { br_int = 1; }
    else if (IS("br_err_count")) { br_err = 3; }
    else if (IS("br_display_off")) { power_mode = 0x9b; }
    else if (IS("br_sleep_in")) { power_mode = 0x8f; }
    else if (IS("neg_br_cri_stuck")) { br_cri_stuck = 1; expect(DCS_C_CRI_BUSY, 0); }
    else if (IS("neg_br_fault")) { br_fault = 1; expect(TGL_DCS_BRIGHT ? DCS_C_FAULT : DCS_C_OK, TGL_DCS_BRIGHT ? 0 : 1); }
    else if (IS("neg_br_serror")) { br_serror = 1; expect(DCS_C_SERROR, 0); }
    else if (IS("neg_br_fault_at_write_read")) { br_fault_cmd = 0x52; expect(DCS_C_FAULT, 0); }
    else if (IS("neg_br_fault_settled_read")) { br_fault_cmd = 0x52; br_fault_skip = 1; expect(DCS_C_FAULT, 0); }
    else if (IS("neg_br_fault_err_read")) { br_fault_cmd = 0x05; expect(DCS_C_FAULT, 0); }
    else if (IS("neg_br_fault_power_read")) { br_fault_cmd = 0x0a; expect(DCS_C_FAULT, 0); }
    else if (IS("ok_top_already_on")) { fake_power_top = 1; }
    else if (IS("ok_slow_top")) { top_polls = 3; }
    else if (IS("ok_ref_76m")) { rate_ref = 76800000; }
    else if (IS("ok_hs_fallback")) { panel_lp = 0; }
    else if (IS("ok_first_ack")) { first_ack = 1; }
    else if (IS("neg_smmu_on")) { smmu_on = 1; expect(TGL_FRAME_RUNG >= 3 ? DCS_C_SMMU_ON : DCS_C_OK, 0); }
    else if (IS("ok_smmu_abort")) { smmu_abort = 1; smmu_gbpa = 0x2e1f | 1u << 20; }
    else if (IS("neg_smmu_abort")) { smmu_abort = 1; smmu_stuck = 1; smmu_gbpa = 0x2e1f | 1u << 20; expect(TGL_FRAME_RUNG >= 3 ? DCS_C_SMMU_ABORT : DCS_C_OK, 0); }
    else if (IS("ok_underrun_first")) { underrun_first = 1; }
    else if (IS("ok_underrun_later")) { underrun_later = 1; }
    else if (IS("neg_fe_bus")) { fe_bus = 1; expect(DCS_C_FE_BUS, 0); }
    else if (IS("neg_no_fetch")) { no_fetch = 1; expect(DCS_C_NO_FRAME_DONE, 0); }
    else if (IS("ok_phone_pps")) { pps_ff89 = 1; }
    else if (IS("neg_pps_byte88")) { pps_bad88 = 1; expect(DCS_C_PPS, 0); }
    else if (IS("ok_no_te")) { no_te = 1; }
    else if (IS("ok_te_needs_pad")) { te_needs_pad = 1; pad[2] = 0xa; }
    else if (IS("ok_pad_set_no_te")) { no_te = 1; pad_is_te = 1; pad[0] = 0x100; pad[1] = 2; pad[2] = 1; }
    else if (IS("die_pad_read")) { te_needs_pad = 1; pad_die = 1; }
    else if (IS("die_pad_late")) { pad_die = 1; }
    else if (IS("ok_stale_abl_pps")) { pps_stale = 1; }
    else if (IS("ok_no_pps_read")) { pps_silent = 1; }
    else if (IS("ok_no_opr")) { opr_silent = 1; }
    else if (IS("ok_opr_stuck")) { opr_stuck = 1; }
    else if (IS("ok_crc_stuck")) { crc_stuck = 1; }
    else if (IS("ok_crc_zero")) { crc_zero = 1; }
    else if (IS("neg_magic")) { magic_bad = 1; expect(DCS_C_MAGIC, 0); }
    else if (IS("neg_mba_silent")) { mba_silent = 1; expect(DCS_C_MBA_TIMEOUT, 0); }
    else if (IS("neg_top_reply")) { top_set_err = 1; expect(DCS_C_TOP_REPLY, 0); }
    else if (IS("neg_top_weird")) { top_weird = 1; expect(DCS_C_TOP_STATE, 0); }
    else if (IS("neg_top_never_on")) { top_polls = 100000; expect(DCS_C_TOP_STATE, 0); }
    else if (IS("neg_dsi0_nack")) { mba_nack_dsi0 = 1; expect(DCS_C_LPCM_REPLY, 0); }
    else if (IS("neg_prepare_nack")) { prepare_nack = 1; expect(DCS_C_LPCM_REPLY, 0); }
    else if (IS("neg_pix_minus3")) { pix_neg = 1; expect(DCS_C_RATE, 0); }
    else if (IS("neg_ref_rate")) { rate_ref = 19200000; expect(DCS_C_RATE, 0); }
    else if (IS("neg_dead_reg")) { core_id = 0; expect(DCS_C_DEAD_REG, 0); }
    else if (IS("neg_phy_ready")) { phy_ready = 0; expect(DCS_C_PHY_POLL, 0); }
    else if (IS("neg_pll")) { pll_lock = 0; expect(DCS_C_PHY_POLL, 0); }
    else if (IS("neg_mode")) { mode_stuck = 1; expect(DCS_C_MODE, 0); }
    else if (IS("neg_no_panel")) { panel_lp = panel_hs = 0; expect(DCS_C_NO_PANEL_REPLY, 0); }
    else if (IS("neg_wrong_id")) { wrong_id = 1; expect(DCS_C_PANEL_ID, 0); }
    else if (IS("neg_cri_stuck_start")) { cri_stuck_after = 0; expect(DCS_C_CRI_BUSY, 0); }
    else if (IS("neg_serror_dsi")) { serror_at = 90; expect(DCS_C_SERROR, 0); }
    else if (IS("neg_fault")) { fault_at = 95; expect(DCS_C_FAULT, 0); }
    else if (IS("neg_fe0_nack")) { fe0_nack = 1; expect(DCS_C_LPCM_REPLY, 0); }
    else if (IS("neg_chip")) { chip_bad = 1; expect(DCS_C_CHIP, 0); }
    else if (IS("neg_serror_dpu")) { serror_dpu = 1; expect(DCS_C_SERROR, 0); }
    else if (IS("neg_iso_stuck")) { iso_stuck = 1; expect(DCS_C_ISOLATION, 0); }
    else if (IS("neg_pps_mismatch")) { pps_wrong_after = 1; expect(DCS_C_PPS, 0); }
    else if (IS("neg_no_done")) { no_done = 1; expect(DCS_C_NO_FRAME_DONE, 0); }
    else if (IS("die_first_dpu")) { die_first_dpu = 1; }
    else if (!strncmp(sc, "die_", 4)) { die_at = atoi(sc + 4); }
    else { printf("unknown scenario\n"); return 2; }
    tgl_dcs_begin(NONCE, RN, UINT64_C(0x202611012000));
    if (IS("allow")) {
        CHECK(!dcs_test_pa_ok(FR_DPU + 0x18060, 0)); CHECK(!dcs_test_pa_ok(FR_DPU + 0x18060, 1)); /* FE0 layer address */
        CHECK(!dcs_test_pa_ok(0x0ed80004, 0)); CHECK(dcs_test_pa_ok(0x0ed80000, 0) == (TGL_FRAME_RUNG >= 3)); CHECK(!dcs_test_pa_ok(0x0ef90000, 0)); /* SMMU, gpcsr */
        CHECK(!dcs_test_pa_ok(FR_DPU + FR_CHIP_ID, 1)); CHECK(dcs_test_pa_ok(FR_DPU + FR_CHIP_ID, 0));
        CHECK(!dcs_test_pa_ok(FR_DPU + FR_POST_PROCESS_OUT + 4, 0)); CHECK(!dcs_test_pa_ok(FR_DPU + 0x80068, 1)); /* neighbour; BE reset */
        CHECK(dcs_test_pa_ok(FR_DPU + FR_OUTPUT0_START, 1) == (TGL_FRAME_RUNG >= 2));
        CHECK(dcs_test_pa_ok(FR_DPU + 0xb6024, 1) == (TGL_FRAME_RUNG >= 2));
        CHECK(dcs_test_pa_ok(0x0ed80044, 0) == (TGL_FRAME_RUNG >= 3)); CHECK(dcs_test_pa_ok(0x0ed80044, 1) == (TGL_FRAME_RUNG >= 3)); CHECK(!dcs_test_pa_ok(0x0ed80020, 1));
        CHECK(dcs_test_pa_ok(FR_DPU + FR_SH_LAYER0_ADDRESS, 1) == (TGL_FRAME_RUNG >= 3));
#if TGL_DCS_BRIGHT
        /* The one brightness packet goes through, only with this array, type and length. Refused before any access. */
        { unsigned a0 = acc; CHECK(dcs_test_bright_long(0x29, 3, 0) == DCS_C_DCS_REFUSED); CHECK(dcs_test_bright_long(0x39, 2, 0) == DCS_C_DCS_REFUSED); CHECK(dcs_test_bright_long(0x39, 4, 0) == DCS_C_DCS_REFUSED); CHECK(dcs_test_bright_long(0x39, 3, 1) == DCS_C_DCS_REFUSED); CHECK(acc == a0); }
#endif
        CHECK(dcs_test_pa_ok(0x0ec7e004, 1) == (TGL_FRAME_RUNG >= 2)); CHECK(dcs_test_pa_ok(0x0ec7e010, 0) == (TGL_FRAME_RUNG >= 2)); CHECK(!dcs_test_pa_ok(0x0ec7e010, 1)); CHECK(!dcs_test_pa_ok(0x0ec7f004, 1)); /* XDPU_TE1 */
#if TGL_FRAME_RUNG >= 3
        CHECK(dcs_test_set_buffer(UINT64_C(0xf0000010), 5120) == DCS_C_BAD_BUFFER); CHECK(dcs_test_set_buffer(UINT64_C(0x10000000000), 5120) == DCS_C_BAD_BUFFER);
        CHECK(dcs_test_set_buffer(UINT64_C(0xf0000000), 5121) == DCS_C_BAD_BUFFER); CHECK(dcs_test_set_buffer(UINT64_C(0xf0000000), 0) == DCS_C_BAD_BUFFER); CHECK(dpu_accesses == 0);
#endif
        printf("%s allow\n", fails ? "FAIL" : "PASS"); return fails ? 1 : 0;
    }
    int rc = tgl_dcs_run();
    if (IS("twice")) { unsigned a0 = acc; CHECK(tgl_dcs_run() == DCS_C_REFUSED_PA); CHECK(acc == a0); }
    tgl_dcs_finish(rc, 0, 0, 0);
    CHECK(rc == want_code);
    /* Gate off: the panel's level is never touched. Gate on: if written, before any DPU access or FE0 power, outside a test-key window. */
    if (!TGL_DCS_BRIGHT) CHECK(br_writes == 0);
    CHECK(br_writes <= 1);
    if (br_writes) { CHECK(br_at_dpu == 0); CHECK(!br_at_fe0); CHECK(!br_at_open); }
    if (IS("ok_top_already_on")) CHECK(lpb_sets == 0);
    CHECK(!f0_open && !fc_open);
    if (IS("ok_no_te") || IS("ok_te_needs_pad")) { CHECK(pad_writes >= 3); CHECK(pad[1] == 2 && (pad[0] & 0x100) && (pad[2] & 0xb) == 1); }
    if (IS("ok_pad_set_no_te") || IS("ok")) CHECK(pad_writes == 0);
#if TGL_FRAME_RUNG < 2
    CHECK(store_a == 0 && store_b == 0);
    CHECK(pad_reads == 0 && pad_writes == 0);
    CHECK(dpu_writes == 0); CHECK(kicks == 0); CHECK(!pps_got);
    if (want_frames == 1) CHECK(dpu_accesses >= 34);
#else
#ifndef TGL_DCS_HANDOFF
    if (IS("ok")) CHECK(pad_reads == 4);
#endif
    if (want_frames == 1) {
#ifdef TGL_DCS_HANDOFF
        /* One kick, then the record is the kernel's permission. Nothing painted, output left armed. */
        CHECK(frames_ok == 1); CHECK(pps_got); CHECK(comp_on); CHECK(store_a == 0 && store_b == 0); CHECK(D(FR_OUTPUT0_START) == 1);
        { const struct hakios_scanout_takeover *k = (const struct hakios_scanout_takeover *)(const void *)dcs_test_takeover; CHECK(k->magic == HAKIOS_TAKEOVER_MAGIC); CHECK(k->stages == HAKIOS_TK_REQUIRED); CHECK(k->crc32 == hakios_takeover_crc(k, sizeof(*k) - sizeof(k->crc32))); }
#else
        CHECK(frames_ok == TGL_FRAME_SLOTS * TGL_FRAME_KICKS); CHECK(pps_got); CHECK(comp_on);
#endif
        CHECK(now_us < 20000000u);
#ifndef TGL_DCS_HANDOFF
        /* NONCE pattern 0b101101: black, white, then 1,0,1,1 */
        static const uint32_t want[6] = { 0, 0xffff, 0xffff, 0, 0xffff, 0xffff };
        for (unsigned s = 0; s < 6; ++s) CHECK(panel_shown[s * TGL_FRAME_KICKS] == want[s]);
        CHECK(D(FR_OUTPUT0_START) == 0);
#endif
#if defined(TGL_DCS_HANDOFF)
#elif TGL_FRAME_RUNG >= 3
        CHECK(px_mid_a == UINT64_C(0xffffffffffffffff)); CHECK(px_bar_r == UINT64_C(0xffff0000ffff0000)); CHECK(px_white_b == UINT64_C(0xff00ff00ff00ff00)); CHECK(px_bar_b == UINT64_C(0xff0000ffff0000ff)); CHECK(px_mid_b == UINT64_C(0xff000000ff000000));
#else
        CHECK(store_a == 0 && store_b == 0);
#endif
    } else CHECK(frames_ok == 0);
#endif
    write_out();
    if (tracef) fclose(tracef);
    printf("%s %s rc=%d accesses=%u us=%llu\n", fails ? "FAIL" : "PASS", sc, rc, acc, (unsigned long long)now_us);
    printf("R rc=%d dbv=%#x writes=%d\n", rc, panel_dbv, br_writes);
    return fails ? 1 : 0;
}
