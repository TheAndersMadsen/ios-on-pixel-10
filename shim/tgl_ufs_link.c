/* SPDX-License-Identifier: GPL-2.0-only */
/* Copyright (C) 2011-2013 Samsung India Software Operations
 * Copyright (c) 2013-2016, The Linux Foundation. All rights reserved.
 * Copyright 2022-2025 Google LLC
 * Adapted from Linux ufshcd.c HCE/UIC/LINK paths, ufs-google.c (polled UIC, set_device_on, link_startup_notify)
 * and pinctrl/google/common.{c,h}. Order per the shipped ufs.ko 6.12.81. Folded from the code that ran as
 * research/ufs-read-r2 pass B; see research/ufs-integrate-r1/DESIGN.md for what changed. */
#include "tgl_ufs_link.h"

#define TRY(x) do { int e_ = (x); if (e_) return e_; } while (0)

/* UFSHCI registers, Linux ufshci.h. HCLKDIV and TOP are the vendor's. */
enum {
    REG_CAP = 0x00, REG_IS = 0x20, REG_IE = 0x24, REG_HCS = 0x30, REG_HCE = 0x34, REG_UTRLDBR = 0x58,
    REG_UTMRLDBR = 0x78, REG_UIC_CMD = 0x90, REG_UIC_ARG1 = 0x94, REG_UIC_ARG2 = 0x98, REG_UIC_ARG3 = 0x9c,
    REG_HCLKDIV = 0xf8, HCLKDIV_VALUE = 0xc8, TOP_AWUSER_VC = 0x200, AWUSER_VC_VALUE = 0x101,
    IS_UCCS = 0x400, IS_ULL = 0x80, IS_FATAL = 0x80 | 0x800 | 0x10000 | 0x20000 | 0x40000,
    HCS_DP = 0x1, HCS_UCRDY = 0x8, HCE_ENABLE = 0x1, HCE_CGE = 0x2, CAP_CS = 0x10000000,
    UIC_OPCODE_MASK = 0xff, UIC_RESULT_MASK = 0xff, UIC_DME_GET = 0x01, UIC_DME_SET = 0x02, UIC_LINK_STARTUP = 0x16,
    /* ufshcd.c hba_enable_delay_us, retry_inner, retry_outer, stop 10 us/1 ms; UIC_CMD_TIMEOUT; ufs-google.c UCCS */
    HCE_DELAY_MIN_US = 1000, HCE_DELAY_MAX_US = 1100, HCE_POLLS = 50, HCE_STOP_INTERVAL_US = 10,
    HCE_STOP_TIMEOUT_US = 1000, HCE_OUTER_RETRIES = 3, LINK_RETRIES = 3, UCRDY_INTERVAL_US = 500,
    UCRDY_TIMEOUT_US = 500000, UCCS_INTERVAL_US = 10, UIC_MAX_TIMEOUT_US = 4000000,
    /* ufs-google.c: 500-600 us after LINK before any DME (b/456375140), device-on waits */
    POST_LINK_MIN_US = 500, POST_LINK_MAX_US = 600, PWR_EN_MIN_US = 1500, PWR_EN_MAX_US = 2000,
    REFCLK_MIN_US = 300, REFCLK_MAX_US = 310,
    /* unipro attributes */
    ATTR_CBULPH8 = 0x8118, ATTR_MPHY_CFG_UPD = 0xd085, ATTR_LAYER_EN = 0xd000, ATTR_TX_FSM = 0x41, ATTR_RX_FSM = 0xc1
};
_Static_assert(1u + LINK_RETRIES == TGL_UFS_LINK_MAX_ATTEMPTS, "record geometry");

/* Host-side failures of one operation, recorded as route_rc. Same values as the decoders' existing table. */
enum link_err {
    E_INPUT = 0x88101, E_NOT_PREPARED = 0x88104, E_LATCHED = 0x88105, E_BACKEND = 0x88109, E_CLOCK = 0x8810a,
    E_TIMEOUT = 0x8810b, E_IE_OWNED = 0x8810d, E_STALE_UCCS = 0x8810e, E_FATAL = 0x8810f, E_ACK = 0x88110,
    E_NO_DEVICE = 0x88111, E_HCE_STOP = 0x88112, E_DOORBELL = 0x88113, E_TAKEOVER = 0x88114, E_PRE_LINK = 0x88115,
    E_UIC_RESULT = 0x88200, E_DEVICE_ON = 0x88302, E_TOP = 0x88303, E_HCLKDIV = 0x88304,
    /* device-on, the first failure */
    E_PAD_PORT = -107, E_PAD_READBACK = -108, E_SMC = -109, E_WAIT = -104, E_PAD_TIME = -105
};
#define DIAG_GETS 5u

static struct {
    unsigned attempted, in_flight;
    uint64_t last, deadline, epoch, nonce, started;
    int rc, final_rc;
    uint32_t stage, psm[3];
    /* device-on */
    uint32_t pad_step; int pad_rc, pad_native; uint64_t smc_a0, smc_a1;
    uint64_t power_done, refclk_done; uint32_t power_to_refclk_us, refclk_to_resetb_us;
    uint32_t pre[3][3];
    uint8_t pads_before, pads_after;
    /* host */
    unsigned prepared, latched, failed_acked;
    int native_status;
    uint32_t cap, hce_before, hce_written, hce_after, is_before, ie_before, stops, starts;
    uint32_t last_is, last_hcs, last_arg2, last_polls;
    uint64_t cmd_t, uccs_t;
    /* LINK */
    uint32_t attempts, link_up, results[TGL_UFS_LINK_MAX_ATTEMPTS], polls[TGL_UFS_LINK_MAX_ATTEMPTS], link_us[TGL_UFS_LINK_MAX_ATTEMPTS];
    int route_rc;
    uint32_t route_stage, diag_ran, diag_hce[DIAG_GETS], diag_link[DIAG_GETS];
    int diag_hce_rc[DIAG_GETS], diag_link_rc[DIAG_GETS];
    uint64_t esr, far_value;
    uint8_t rec[TGL_UFS_LINK_RECORD_BYTES];
} w;

/* ---- record ---- */
static void put32(unsigned o, uint32_t v) { for (unsigned i = 0; i < 4; ++i) w.rec[o + i] = (uint8_t)(v >> (8 * i)); }
static void put64(unsigned o, uint64_t v) { put32(o, (uint32_t)v); put32(o + 4, (uint32_t)(v >> 32)); }
static void put16(unsigned o, uint32_t v) { w.rec[o] = (uint8_t)v; w.rec[o + 1] = (uint8_t)(v >> 8); }
static uint32_t crc(const uint8_t *p, unsigned n)
{
    uint32_t c = ~UINT32_C(0);
    for (unsigned i = 0; i < n; ++i) {
        c ^= p[i];
        for (unsigned j = 0; j < 8; ++j) c = (c >> 1) ^ (UINT32_C(0xedb88320) & (0u - (c & 1u)));
    }
    return ~c;
}
static int publish(void)
{
    uint64_t now = 0;
    (void)tgl_ufs_port_now(&now);
    for (unsigned i = 0; i < TGL_UFS_LINK_RECORD_BYTES; ++i) w.rec[i] = 0;
    put64(0, TGL_UFS_LINK_MAGIC); put32(8, TGL_UFS_LINK_RECORD_VERSION); put16(12, TGL_UFS_LINK_RECORD_BYTES);
    w.rec[14] = 0xb; /* the only pass, in pass B's slot */
    put64(16, w.nonce); put64(24, w.epoch);
    put32(40, (uint32_t)w.rc); put32(44, w.stage); put64(48, w.started);
    put32(56, now >= w.started ? (uint32_t)(now - w.started) : UINT32_MAX);
    put32(60, (uint32_t)w.route_rc);
    put32(72, w.pad_step); put32(76, (uint32_t)w.pad_rc); put32(84, (uint32_t)w.pad_native);
    put32(88, (uint32_t)w.smc_a0);
    put32(92, (w.psm[0] & 0xffu) | (w.psm[1] & 0xffu) << 8 | (w.psm[2] & 0xffu) << 16 | ((uint32_t)w.smc_a1 & 0xffu) << 24);
    for (unsigned p = 0; p < 3u; ++p) for (unsigned k = 0; k < 3u; ++k) put32(96 + p * 12 + k * 4, w.pre[p][k]);
    put32(132, w.power_to_refclk_us); put32(136, w.refclk_to_resetb_us);
    put32(140, w.cap); put32(144, w.hce_before); put32(148, w.hce_written); put32(152, w.hce_after);
    put32(156, w.is_before); put32(160, w.ie_before);
    w.rec[164] = (uint8_t)w.stops; w.rec[165] = (uint8_t)w.starts; w.rec[166] = w.pads_before; w.rec[167] = w.pads_after;
    w.rec[168] = (uint8_t)w.attempts; w.rec[169] = w.attempts ? 1 : 0; w.rec[170] = (uint8_t)w.link_up;
    w.rec[171] = (uint8_t)((tgl_ufs_port_isr() >> 6) & 7u);
    for (unsigned i = 0; i < TGL_UFS_LINK_MAX_ATTEMPTS; ++i) {
        w.rec[172 + i] = (uint8_t)w.results[i];
        w.rec[176 + i] = w.polls[i] > 255u ? 255u : (uint8_t)w.polls[i];
        put32(180 + i * 4, w.link_us[i]);
    }
    put32(196, w.last_hcs); put32(200, w.last_is); put32(204, w.last_arg2);
    uint32_t bad = w.diag_ran ? 0x8000u : 0u;
    for (unsigned i = 0; i < DIAG_GETS; ++i) {
        put16(208 + i * 2, w.diag_hce[i]); put16(218 + i * 2, w.diag_link[i]);
        if (w.diag_hce_rc[i]) bad |= 1u << i;
        if (w.diag_link_rc[i]) bad |= 0x100u << i;
    }
    put16(228, bad); w.rec[230] = (uint8_t)w.route_stage; w.rec[231] = (uint8_t)w.native_status;
    put64(232, w.esr); put64(240, w.far_value);
    put32(248, crc(w.rec, 248)); put32(252, TGL_UFS_LINK_COMMIT);
    return tgl_ufs_port_publish(w.rec);
}
static int stage(uint32_t s, int rc)
{
    w.stage = s; w.rc = rc;
    return publish() ? TGL_UFS_LINK_E_OUTPUT : 0;
}

/* ---- device-on: ufs_google_set_device_on then ufs_pm_up, stopping before the PHY reset release ---- */
#define PAD_PARAM 0u
#define PAD_DMUX 4u
#define PAD_TX 8u
#define PAD_RX 0x10u
#define TX_PUPD_MASK 0x3u
#define TX_DOUT (1u << 2)
#define TX_OE (1u << 3)
#define PARAM_DRV_MASK 0xfu
#define PARAM_IE (1u << 8)
#define CLK_REF_TCX0 3u  /* HSIOS_GPIO_REF_TCX0_CLK */
#define CLK_AUX 16u      /* HSIOS_AUX_CLK */
struct pad_cfg { unsigned which; uint32_t mux, param_mask, param_set, tx_mask, tx_set; };
enum { PAD_RESET, PAD_POWER, PAD_REFCLK };
static int on_time(void)
{
    uint64_t t;
    if (tgl_ufs_port_now(&t)) return E_PAD_TIME;
    if (t < w.last) return E_PAD_TIME;
    w.last = t;
    return t >= w.deadline ? E_PAD_TIME : 0;
}
static int pad_rd(unsigned which, uint32_t off, uint32_t *v)
{
    TRY(on_time());
    int rc = tgl_ufs_port_pad_rd(which, off, v);
    if (rc) { w.pad_native = rc; return E_PAD_PORT; }
    return 0;
}
static int pad_wr(unsigned which, uint32_t off, uint32_t v)
{
    TRY(on_time());
    int rc = tgl_ufs_port_pad_wr(which, off, v);
    if (rc) { w.pad_native = rc; return E_PAD_PORT; }
    return 0;
}
/* pinctrl_select_state order: mux, then PARAM, then TXDATA, each only if changed. DOUT is merged into the single
 * TXDATA write. The readbacks are stronger than the source, which trusts these writes. */
static int apply_pad(uint32_t mux, uint32_t param_mask, uint32_t param_set, uint32_t tx_mask, uint32_t tx_set, unsigned which)
{
    uint32_t param, dmux, tx, v, new_param, new_tx;
    TRY(pad_rd(which, PAD_PARAM, &param));
    TRY(pad_rd(which, PAD_DMUX, &dmux));
    TRY(pad_rd(which, PAD_TX, &tx));
    w.pre[which][0] = param; w.pre[which][1] = dmux; w.pre[which][2] = tx;
    TRY(pad_wr(which, PAD_DMUX, mux));
    new_param = (param & ~param_mask) | param_set;
    if (new_param != param) TRY(pad_wr(which, PAD_PARAM, new_param));
    new_tx = (tx & ~tx_mask) | tx_set;
    if (new_tx != tx) TRY(pad_wr(which, PAD_TX, new_tx));
    TRY(pad_rd(which, PAD_DMUX, &v));
    if (v != mux) return E_PAD_READBACK;
    TRY(pad_rd(which, PAD_PARAM, &v));
    if ((v & param_mask) != param_set) return E_PAD_READBACK;
    TRY(pad_rd(which, PAD_TX, &v));
#if TGL_UFS_REFCLK_RELAX
    /* Observed on the phone: this latch reads 0 after writing OE, and LINK still succeeds. The signal comes from
     * mux 2 and the SMC below. Cause unknown. Other pads stay strict. */
    if (which == PAD_REFCLK) { w.pre[which][2] = v; return 0; }
#endif
    return (v & tx_mask) == tx_set ? 0 : E_PAD_READBACK;
}
static int resetb_high(void)
{
    uint32_t tx, v;
    TRY(pad_rd(PAD_RESET, PAD_TX, &tx));
    if (!(tx & TX_OE) || (tx & TX_PUPD_MASK)) return E_PAD_READBACK;
    TRY(pad_wr(PAD_RESET, PAD_TX, tx | TX_DOUT));
    TRY(pad_rd(PAD_RESET, PAD_TX, &v));
    return (v & (TX_OE | TX_DOUT)) == (TX_OE | TX_DOUT) ? 0 : E_PAD_READBACK;
}
static int clock_on(uint32_t clock)
{
    uint64_t a0 = UINT64_MAX, a1 = UINT64_MAX;
    TRY(on_time());
    int rc = tgl_ufs_port_clk_on(clock, &a0, &a1);
    w.smc_a0 = a0; w.smc_a1 = a1;
    if (rc) { w.pad_native = rc; return E_PAD_PORT; }
    if (a0 || a1) return E_SMC;
    return on_time();
}
/* Six actions, in this order, one attempt each. The source's waits are observed, not assumed. */
static int device_on_seq(void)
{
    /* lga-pinctrl.dtsi: hsios_stby_ufs_refclk, hsios_ufs_resetb then output 0, hsios_ufs_pwr_en then output 1 */
    TRY(apply_pad(1u << 1, PARAM_DRV_MASK, 1, TX_PUPD_MASK | TX_OE, TX_OE, PAD_REFCLK)); w.pad_step = 1;
    TRY(apply_pad(1u << 0, PARAM_DRV_MASK | PARAM_IE, 1u | PARAM_IE, TX_PUPD_MASK | TX_OE | TX_DOUT, TX_OE, PAD_RESET)); w.pad_step = 2;
    TRY(apply_pad(1u << 0, PARAM_DRV_MASK | PARAM_IE, 0u | PARAM_IE, TX_PUPD_MASK | TX_OE | TX_DOUT, TX_OE | TX_DOUT, PAD_POWER));
    TRY(on_time()); w.power_done = w.last; w.pad_step = 3;
    if (tgl_ufs_port_delay(PWR_EN_MIN_US, PWR_EN_MAX_US)) return E_PAD_TIME;
    TRY(on_time());
    w.power_to_refclk_us = (uint32_t)(w.last - w.power_done);
    if (w.power_to_refclk_us < PWR_EN_MIN_US) return E_WAIT;
    TRY(clock_on(CLK_REF_TCX0)); w.refclk_done = w.last; w.pad_step = 4;
    if (tgl_ufs_port_delay(REFCLK_MIN_US, REFCLK_MAX_US)) return E_PAD_TIME;
    TRY(on_time());
    w.refclk_to_resetb_us = (uint32_t)(w.last - w.refclk_done);
    if (w.refclk_to_resetb_us < REFCLK_MIN_US) return E_WAIT;
    TRY(resetb_high()); w.pad_step = 5;
    TRY(clock_on(CLK_AUX)); w.pad_step = 6;
    return 0;
}
/* Bit 0 reset RX, 1 power RX, 2 reset DOUT, 3 power DOUT, 7 all four reads completed. */
static uint8_t pad_levels(void)
{
    uint32_t rx0 = 0, rx8 = 0, tx0 = 0, tx8 = 0;
    if (tgl_ufs_port_pad_rd(PAD_RESET, PAD_RX, &rx0) || tgl_ufs_port_pad_rd(PAD_POWER, PAD_RX, &rx8) ||
        tgl_ufs_port_pad_rd(PAD_RESET, PAD_TX, &tx0) || tgl_ufs_port_pad_rd(PAD_POWER, PAD_TX, &tx8)) return 0;
    return (uint8_t)(0x80u | (rx0 & 1u) | (rx8 & 1u) << 1 | ((tx0 >> 2) & 1u) << 2 | ((tx8 >> 2) & 1u) << 3);
}

/* ---- polled host operations ---- */
struct op { uint64_t start, last, limit; uint32_t fatal; unsigned effect; };
static int nat(int rc)
{
    if (!rc) return 0;
    w.native_status = rc;
    return E_BACKEND;
}
static int rd(uint32_t off, uint32_t *v) { return nat(tgl_ufs_port_hc_rd(off, v)); }
static int wr(uint32_t off, uint32_t v) { return nat(tgl_ufs_port_hc_wr(off, v)); }
static int tick(struct op *o)
{
    uint64_t now;
    TRY(nat(tgl_ufs_port_now(&now)));
    if (now < o->last) return E_CLOCK;
    o->last = now;
    return now - o->start >= o->limit ? E_TIMEOUT : 0;
}
static int nap(struct op *o, uint32_t min, uint32_t max)
{
    uint64_t before = o->last;
    if ((before - o->start) + max >= o->limit) return E_TIMEOUT;
    TRY(nat(tgl_ufs_port_delay(min, max)));
    TRY(tick(o));
    return o->last - before < min ? E_CLOCK : 0;
}
static int begin(struct op *o, uint64_t limit)
{
    o->start = o->last = 0; o->limit = limit; o->fatal = IS_FATAL; o->effect = 0;
    int rc = nat(tgl_ufs_port_now(&o->start));
    o->last = o->start;
    return rc;
}
static int refused(int rc) { return rc >= E_UIC_RESULT && rc <= (int)E_UIC_RESULT + (int)UIC_RESULT_MASK; }
/* After the first register effect, anything but a completed and acknowledged refusal leaves unknown state. */
static int finish(struct op *o, int rc)
{
    if (rc && o->effect && !refused(rc)) w.latched = 1;
    return rc;
}
static int wait_ucrdy(struct op *o)
{
    uint64_t t0 = o->last;
    for (uint32_t n = 0; n <= UCRDY_TIMEOUT_US / UCRDY_INTERVAL_US; ++n) {
        TRY(rd(REG_HCS, &w.last_hcs));
        if (w.last_hcs & HCS_UCRDY) return 0;
        if (o->last - t0 >= UCRDY_TIMEOUT_US) return E_TIMEOUT;
        TRY(nap(o, UCRDY_INTERVAL_US, UCRDY_INTERVAL_US));
    }
    return E_TIMEOUT;
}
static int issue(struct op *o, uint32_t opcode, uint32_t a1, uint32_t a3)
{
    uint32_t ie;
    TRY(wait_ucrdy(o));
    TRY(rd(REG_IE, &ie));
    if (ie & IS_UCCS) return E_IE_OWNED;
    TRY(rd(REG_IS, &w.last_is));
    if (w.last_is & IS_UCCS) return E_STALE_UCCS;
    if (w.last_is & o->fatal) return E_FATAL;
    o->effect = 1;
    TRY(wr(REG_UIC_ARG1, a1));
    TRY(wr(REG_UIC_ARG2, 0));
    TRY(wr(REG_UIC_ARG3, a3));
    TRY(wr(REG_UIC_CMD, opcode & UIC_OPCODE_MASK));
    return nat(tgl_ufs_port_now(&w.cmd_t));
}
/* Only UCCS is acknowledged. All other IS bits belong to their own consumers. */
static int complete(struct op *o, uint32_t *result)
{
    uint64_t t0;
    TRY(tick(o));
    t0 = o->last;
    w.last_polls = 0;
    for (uint64_t n = 0;; ++n) {
        TRY(rd(REG_IS, &w.last_is));
        ++w.last_polls;
        if (w.last_is & IS_UCCS) TRY(nat(tgl_ufs_port_now(&w.uccs_t)));
        if (w.last_is & o->fatal) return E_FATAL;
        if (w.last_is & IS_UCCS) break;
        if (o->last - t0 >= o->limit || n > o->limit / UCCS_INTERVAL_US) return E_TIMEOUT;
        TRY(nap(o, UCCS_INTERVAL_US, UCCS_INTERVAL_US));
    }
    TRY(wr(REG_IS, IS_UCCS));
    TRY(rd(REG_IS, &w.last_is));
    if (w.last_is & IS_UCCS) return E_ACK;
    if (w.last_is & o->fatal) return E_FATAL;
    TRY(rd(REG_UIC_ARG2, &w.last_arg2));
    *result = w.last_arg2 & UIC_RESULT_MASK;
    return 0;
}
/* ufshcd_init clears pending IS and writes IE=0 before HCE. IS is W1C: only bits already seen are acknowledged. */
static int takeover(struct op *o)
{
    uint32_t is, ie;
    TRY(rd(REG_IS, &is));
    TRY(rd(REG_IE, &ie));
    if (!w.starts) { w.is_before = is; w.ie_before = ie; }
    o->effect = 1;
    TRY(wr(REG_IS, is));
    TRY(wr(REG_IE, 0));
    TRY(rd(REG_IE, &ie));
    return ie ? E_TAKEOVER : 0;
}
/* ufshcd_hba_stop. Linux only logs a timeout; enabling a host that never reset is untested, so this refuses. */
static int hba_stop(struct op *o)
{
    uint32_t hce;
    o->effect = 1;
    ++w.stops;
    TRY(wr(REG_HCE, 0));
    for (unsigned n = 0; n <= HCE_STOP_TIMEOUT_US / HCE_STOP_INTERVAL_US; ++n) {
        TRY(rd(REG_HCE, &hce));
        if (!(hce & HCE_ENABLE)) return 0;
        TRY(nap(o, HCE_STOP_INTERVAL_US, HCE_STOP_INTERVAL_US));
    }
    return E_HCE_STOP;
}
/* ufshcd_hba_execute_hce with ufshcd_hba_start's value: crypto general enable follows CAP.CS. */
static int hba_enable(struct op *o)
{
    uint32_t hce, value;
    unsigned outer = HCE_OUTER_RETRIES;
    TRY(rd(REG_CAP, &w.cap));
    value = HCE_ENABLE | ((w.cap & CAP_CS) ? HCE_CGE : 0);
    for (;;) {
        TRY(rd(REG_HCE, &hce));
        if (!w.starts) w.hce_before = hce;
        if (hce & HCE_ENABLE) TRY(hba_stop(o));
        o->effect = 1;
        w.hce_written = value;
        ++w.starts;
        TRY(wr(REG_HCE, value));
        /* HCE reads 1->0->1 during init, so delay before the first readback. */
        TRY(nap(o, HCE_DELAY_MIN_US, HCE_DELAY_MAX_US));
        for (unsigned polls = HCE_POLLS;; --polls) {
            TRY(rd(REG_HCE, &hce));
            if (hce & HCE_ENABLE) { w.hce_after = hce; return wait_ucrdy(o); }
            if (!polls) break;
            TRY(nap(o, HCE_DELAY_MIN_US, HCE_DELAY_MAX_US));
        }
        if (!outer--) return E_TIMEOUT;
    }
}
/* A first-stage takeover must not reclaim outstanding requests, as Linux EH would. */
static int prepare(uint64_t budget)
{
    struct op o;
    uint32_t tr, tm;
    int rc;
    if (budget <= HCE_DELAY_MAX_US) return E_INPUT;
    rc = begin(&o, budget);
    if (!rc) rc = rd(REG_UTRLDBR, &tr);
    if (!rc) rc = rd(REG_UTMRLDBR, &tm);
    if (!rc && (tr || tm)) rc = E_DOORBELL;
    if (!rc) rc = takeover(&o);
    if (!rc) rc = hba_enable(&o);
    if (!rc) w.prepared = 1;
    return finish(&o, rc);
}
static int dme(uint32_t opcode, uint32_t arg1, uint32_t *arg3, uint32_t us, unsigned after_failed_link)
{
    struct op o;
    uint32_t result = 0;
    int rc;
    if (!w.prepared) return E_NOT_PREPARED;
    if (!after_failed_link && w.latched) return E_LATCHED;
    if (after_failed_link && !w.failed_acked) return E_LATCHED;
    if (!us || us > UIC_MAX_TIMEOUT_US) return E_INPUT;
    rc = begin(&o, us);
    if (after_failed_link) o.fatal &= ~(uint32_t)IS_ULL;
    if (!rc) rc = issue(&o, opcode, arg1, opcode == UIC_DME_SET ? *arg3 : 0);
    if (!rc) rc = complete(&o, &result);
    if (!rc && result) rc = E_UIC_RESULT + (int)result;
    if (!rc && opcode == UIC_DME_GET) rc = rd(REG_UIC_ARG3, arg3);
    rc = finish(&o, rc);
    if (after_failed_link && rc && !refused(rc)) w.failed_acked = 0;
    return rc;
}
#define MIB(a) ((uint32_t)(a) << 16)
#define MIBS(a, s) (((uint32_t)(a) << 16) | (s))
/* link_startup_notify(PRE_CHANGE) with phy_init_needed=0. pg_enabled is 0: route_admit refuses the FDT otherwise. */
static int pre_link(uint32_t us)
{
    uint32_t off = 0, on = 1;
    if (tgl_ufs_port_hc_wr(REG_HCLKDIV, HCLKDIV_VALUE)) return E_HCLKDIV;
    if (tgl_ufs_port_top_wr(TOP_AWUSER_VC, AWUSER_VC_VALUE)) return E_TOP;
    TRY(dme(UIC_DME_SET, MIB(ATTR_CBULPH8), &off, us, 0));
    return dme(UIC_DME_SET, MIB(ATTR_MPHY_CFG_UPD), &on, us, 0);
}
/* A failed GET is recorded, not terminal: LINK itself is the discriminator. */
static void diag(uint32_t us, uint32_t *v, int *rcs, unsigned after_failed_link)
{
    static const uint16_t attr[DIAG_GETS] = { ATTR_LAYER_EN, ATTR_TX_FSM, ATTR_TX_FSM, ATTR_RX_FSM, ATTR_RX_FSM };
    static const uint8_t sel[DIAG_GETS] = { 0, 0, 1, 4, 5 };
    for (unsigned n = 0; n < DIAG_GETS; ++n) rcs[n] = dme(UIC_DME_GET, MIBS(attr[n], sel[n]), &v[n], us, after_failed_link);
}
static int run_link(struct op *o, uint32_t *result)
{
    /* ufshcd.c: link-lost during LINK is the retry path, not fatal. */
    o->fatal = IS_FATAL & ~(uint32_t)IS_ULL;
    TRY(issue(o, UIC_LINK_STARTUP, 0, 0));
    TRY(complete(o, result));
    if (*result) return E_UIC_RESULT + (int)*result;
    TRY(rd(REG_HCS, &w.last_hcs));
    if (!(w.last_hcs & HCS_DP)) return E_NO_DEVICE;
    TRY(rd(REG_IS, &w.last_is));
    return (w.last_is & IS_FATAL) ? E_FATAL : 0;
}
/* The ufshcd_link_startup retry loop with the device active: one pass, 1 + retries, pre-link replayed each time. */
static int link_sequence(uint32_t us)
{
    int rc;
    for (unsigned retries = LINK_RETRIES;; --retries) {
        struct op o;
        uint32_t result = 0;
        if (pre_link(us)) { rc = E_PRE_LINK; break; }
        rc = begin(&o, us);
        w.cmd_t = w.uccs_t = 0;
        if (!rc) rc = run_link(&o, &result);
        rc = finish(&o, rc);
        w.link_us[w.attempts] = w.uccs_t >= w.cmd_t && w.uccs_t ? (uint32_t)(w.uccs_t - w.cmd_t) : UINT32_MAX;
        w.polls[w.attempts] = w.last_polls;
        w.results[w.attempts++] = result;
        if (!rc) { w.link_up = 1; return 0; }
        if (!refused(rc) || !retries) break;
        /* ufshcd_hba_enable on the retry path; the IS write stands in for the ISR's blanket ack. */
        if ((rc = begin(&o, us)) == 0) rc = takeover(&o);
        if (!rc) rc = hba_enable(&o);
        rc = finish(&o, rc);
        if (rc) break;
    }
    w.latched = 1;
    w.failed_acked = refused(rc) || rc == E_NO_DEVICE;
    return rc;
}
static int warm_link(uint32_t uic_us, uint64_t hce_us)
{
    w.route_stage = 1;
    w.pad_rc = device_on_seq();
    if (w.pad_rc) return E_DEVICE_ON;
    w.pads_before = pad_levels();
    /* Crumb before any HC write, so a hang inside the HC/UIC route is locatable. */
    if (stage(TGL_UFS_LINK_S_DEVICE_ON, 0)) return E_DEVICE_ON;
    w.route_stage = 2;
    TRY(prepare(hce_us));
    w.route_stage = 3;
    diag(uic_us, w.diag_hce, w.diag_hce_rc, 0);
    w.route_stage = 4;
    int rc = link_sequence(uic_us);
    if (rc) {
        /* Read-only GETs after a LINK the controller answered. An unanswered LINK gets no further command. */
        if (w.failed_acked && !tgl_ufs_port_delay(POST_LINK_MIN_US, POST_LINK_MAX_US)) {
            w.diag_ran = 1;
            diag(uic_us, w.diag_link, w.diag_link_rc, 1);
        }
        return rc;
    }
    w.route_stage = 5;
    if (!tgl_ufs_port_delay(POST_LINK_MIN_US, POST_LINK_MAX_US)) {
        w.diag_ran = 1;
        diag(uic_us, w.diag_link, w.diag_link_rc, 0);
    }
    return 0;
}
/* ---- route ---- */
static int route(const struct tgl_ufs_link_request *q)
{
    const struct tgl_ufs_link_facts *f = &q->facts;
    /* shipped ufs.ko would program power gating for these; this route has no such write. */
    if (f->ah8_pg || f->swh8_pg) return TGL_UFS_LINK_E_PG;
    if (f->decouple_ufs_en) return TGL_UFS_LINK_E_DECOUPLE;
    if (!f->named || f->hc != UINT64_C(0x3c400000) || f->hc_bytes != 0x1000u ||
        f->top != UINT64_C(0x3c410000) || f->top_bytes != 0x504u) return TGL_UFS_LINK_E_RESOURCE;
    if (tgl_ufs_port_now(&w.last) || w.last > UINT64_MAX - q->budget_us) return TGL_UFS_LINK_E_CLOCK;
    w.deadline = w.last + q->budget_us;
    if (stage(TGL_UFS_LINK_S_ADMITTED, 0)) return TGL_UFS_LINK_E_OUTPUT;
    /* Stock's no-PHY-init first boot presumes both UFS domains on. Read, never power. */
    for (unsigned i = 0; i < 3u; ++i) if (tgl_ufs_port_psm(i, &w.psm[i])) return TGL_UFS_LINK_E_PSM;
    if ((w.psm[0] & 0x1fu) != 0x10u || (w.psm[1] & 0x1fu) != 0x10u || (w.psm[2] & 0x1fu) != 0x10u) return TGL_UFS_LINK_E_PSM;
    if (stage(TGL_UFS_LINK_S_START, 0)) return TGL_UFS_LINK_E_OUTPUT;
    w.route_rc = warm_link(1000000u, 1000000u);
    w.pads_after = pad_levels();
    w.stage = TGL_UFS_LINK_S_ROUTE;
    if (!w.route_rc) return TGL_UFS_LINK_OK;
    return w.route_stage == 1 ? TGL_UFS_LINK_E_DEVICE_ON : TGL_UFS_LINK_E_LINK;
}
int tgl_ufs_link_run(const struct tgl_ufs_link_request *q)
{
    if (!q) return TGL_UFS_LINK_E_ARG;
    if (!q->enable) return TGL_UFS_LINK_OFF;
    if (q->enable != 1 || !q->epoch || !q->nonce || !q->budget_us || q->budget_us > TGL_UFS_LINK_MAX_BUDGET_US) return TGL_UFS_LINK_E_ARG;
    if (w.attempted) return TGL_UFS_LINK_E_ONCE;
    w.attempted = 1; /* before any import: no retry for this boot */
    w.epoch = q->epoch; w.nonce = q->nonce;
    tgl_ufs_port_invalidate();
    if (tgl_ufs_port_now(&w.started)) return w.final_rc = TGL_UFS_LINK_E_CLOCK;
    w.in_flight = 1;
    int rc = route(q);
    w.in_flight = 0;
    int o = stage(TGL_UFS_LINK_S_DONE, rc);
    return w.final_rc = rc ? rc : (o ? TGL_UFS_LINK_E_OUTPUT : TGL_UFS_LINK_OK);
}
int tgl_ufs_link_last_rc(void) { return w.final_rc; }
#if TGL_UFS_PWM_FALLBACK
int tgl_ufs_link_relink(void)
{
    static unsigned relinked;
    int rc;
    if (relinked || !w.attempted || w.final_rc != TGL_UFS_LINK_OK) return TGL_UFS_LINK_E_ONCE;
    relinked = 1;
    if (tgl_ufs_port_now(&w.last) || w.last > UINT64_MAX - UINT64_C(5000000)) return w.final_rc = TGL_UFS_LINK_E_CLOCK;
    w.deadline = w.last + UINT64_C(5000000); w.latched = 0; w.attempts = 0; w.link_up = 0; w.failed_acked = 0; w.route_stage = 1;
    w.in_flight = 1;
    /* The same reset-low write as device_on_seq, its wait, then high. The power and refclk pads and both clock votes are untouched. */
    rc = apply_pad(1u << 0, PARAM_DRV_MASK | PARAM_IE, 1u | PARAM_IE, TX_PUPD_MASK | TX_OE | TX_DOUT, TX_OE, PAD_RESET);
    if (!rc && tgl_ufs_port_delay(REFCLK_MIN_US, REFCLK_MAX_US)) rc = E_PAD_TIME;
    if (!rc) rc = resetb_high();
    w.pad_rc = rc;
    if (!rc) { w.route_stage = 2; rc = prepare(1000000u); }
    if (!rc) { w.route_stage = 4; rc = link_sequence(1000000u); }
    if (!rc && tgl_ufs_port_delay(POST_LINK_MIN_US, POST_LINK_MAX_US)) rc = E_PAD_TIME;
    w.route_stage = 5; w.route_rc = rc; w.pads_after = pad_levels();
    w.in_flight = 0;
    int o = stage(TGL_UFS_LINK_S_DONE, rc ? TGL_UFS_LINK_E_LINK : TGL_UFS_LINK_OK);
    return w.final_rc = rc ? TGL_UFS_LINK_E_LINK : (o ? TGL_UFS_LINK_E_OUTPUT : TGL_UFS_LINK_OK);
}
#endif
void tgl_ufs_link_note_fault(uint64_t esr, uint64_t far_value)
{
    if (!w.in_flight) return;
    w.in_flight = 0; w.esr = esr; w.far_value = far_value; w.final_rc = TGL_UFS_LINK_E_FAULT;
    (void)stage(TGL_UFS_LINK_S_FAULT, TGL_UFS_LINK_E_FAULT);
}
