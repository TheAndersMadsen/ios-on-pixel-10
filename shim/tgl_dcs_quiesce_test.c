/* Host test of tgl_dcs_release() with and without TGL_DCS_QUIESCE (chooser-v1-r10), on a fake bus.
 * A fake says nothing about hardware: it checks the order and values the shim writes against dpu_quiesce.h,
 * which cites the phone's vs_drm.ko. Build: see test_dcs_quiesce.py. Usage: tgl_dcs_quiesce_test SCENARIO */
#include "tgl_dcs.c"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

volatile uint32_t dcs_test_takeover[64];
static uint8_t rec[TGL_DCS_RECORD_BYTES];
static uint64_t now_us = 1000;
static uint32_t msg[4], st_done, ctl;
static int fails;
static const char *sc;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s: %s (line %d)\n", sc, #c, __LINE__); fails++; } } while (0)

/* access log */
struct acc { char k; uint64_t pa; uint32_t v; };
static struct acc log_[4096]; static unsigned n_;
static void logit(char k, uint64_t pa, uint32_t v) { if (n_ < sizeof log_ / sizeof log_[0]) log_[n_++] = (struct acc){ k, pa, v }; }

/* fake state */
static uint32_t dpu_iso, be_en = 0x30000u, be_en1 = 0x100000u, l0_st = 0x18, l0_co = 0x02c80500u, gp_status;
static int l0_busy_reads, be_busy_reads, be_busy_forever, top_on = 1, dsi0_on = 1, fe0_on = 1;
static unsigned lpcm_offs, top_offs, top_ons;

static void mba_service(void)
{
    uint32_t r[4] = { 0x08c00000u, 0, 0, 0 };
    if (msg[0] == LPB_GET) { r[0] = 0x05000000u; r[1] = PROT_NO_ERR; r[2] = top_on ? 2 : 1; }
    else if (msg[0] == LPB_SET && msg[2] == 1) { CHECK(msg[1] == LPB_SSWRP_DPU); top_on = 1; top_ons++; r[0] = 0x05000000u; r[1] = PROT_NO_ERR; r[2] = LPB_SUCCESS; r[3] = LPB_SSWRP_DPU; }
    else if (msg[0] == LPB_SET) { CHECK(msg[1] == LPB_SSWRP_DPU && msg[2] == 0); top_on = 0; top_offs++; r[0] = 0x05000000u; r[1] = 15; r[2] = 0; }
    else if (msg[0] == LPCM_HDR) {
        lpcm_offs++;
        if (msg[1] == LPCM_FE0_OFF) fe0_on = 0;
        else if (msg[1] == LPCM_DSI0_OFF) dsi0_on = 0;
    } else CHECK(!"unknown mailbox frame");
    memcpy(msg, r, sizeof r);
    st_done = 1;
}
int dcs_port_read32(uintptr_t pa, uint32_t *v)
{
    now_us += 1;
    *v = 0;
    if (pa == MBA_MAGIC_PA) *v = MBA_MAGIC;
    else if (pa == MBA_PAGE + MBA_ST) *v = st_done;
    else if (pa == MBA_PAGE + MBA_CTL) *v = ctl;
    else if (pa >= MBA_PAGE + MBA_MSG && pa < MBA_PAGE + MBA_MSG + 16) *v = msg[(pa - MBA_PAGE - MBA_MSG) / 4];
    else if (pa == Q_GPCSR + Q_BE_DBG_STATUS) { CHECK(top_on); *v = (be_busy_forever || be_busy_reads-- > 0) ? Q_BE_DBG_BUSY | 0x3 : 0x3; }
    else if (pa >= FR_DPU && pa < FR_DPU + 0x120000) {
        uint32_t o = (uint32_t)(pa - FR_DPU);
        CHECK(fe0_on && top_on);
        if (o == Q_L0_DMA_ST) *v = l0_busy_reads-- > 0 ? 0x01u : l0_st;
        else if (o == Q_L0_DMA_COORD) *v = l0_co;
        else if (o == Q_BE_INTR_ENABLE) *v = be_en;
        else if (o == Q_BE_INTR_ENABLE1) *v = be_en1;
        else if (o == Q_CLOCK_DOMAIN_ISOLATION) *v = dpu_iso;
    } else CHECK(!"read outside the fake");
    logit('R', pa, *v);
    return 0;
}
int dcs_port_write32(uintptr_t pa, uint32_t v)
{
    now_us += 1;
    logit('W', pa, v);
    if (pa == MBA_PAGE + MBA_ST) { st_done = 0; return 0; }
    if (pa == MBA_PAGE + MBA_CTL) { ctl = v; return 0; }
    if (pa >= MBA_PAGE + MBA_MSG && pa < MBA_PAGE + MBA_MSG + 16) { msg[(pa - MBA_PAGE - MBA_MSG) / 4] = v; return 0; }
    if (pa == MBA_PAGE + MBA_GO) { CHECK(v == 1); mba_service(); return 0; }
    if (pa == Q_GPCSR + Q_BE_DBG_CTL) { CHECK(top_on); gp_status = v; return 0; }
    if (pa >= FR_DPU && pa < FR_DPU + 0x120000) {
        uint32_t o = (uint32_t)(pa - FR_DPU);
        CHECK(fe0_on && top_on); /* never touch the DPU once a domain went off */
        if (o == Q_CLOCK_DOMAIN_ISOLATION) dpu_iso = v;
        if (o == Q_BE_INTR_ENABLE) be_en = v;
        if (o == Q_BE_INTR_ENABLE1) be_en1 = v;
        return 0;
    }
    CHECK(!"write outside the fake");
    return -1;
}
uint64_t dcs_port_now_us(void) { return now_us; }
void dcs_port_delay_us(uint32_t us) { now_us += us; }
uint64_t dcs_port_isr(void) { return 0; }
void dcs_port_store64(uint64_t pa, uint64_t v) { (void)pa; (void)v; CHECK(!"store"); }
void dcs_port_civac(uint64_t pa, uint64_t len) { (void)pa; (void)len; }
void dcs_port_service(void) { }
volatile uint8_t *dcs_port_record(void) { return rec; }

static int first(char k, uint64_t pa, int match_v, uint32_t v)
{
    for (unsigned i = 0; i < n_; ++i) if (log_[i].k == k && log_[i].pa == pa && (!match_v || log_[i].v == v)) return (int)i;
    return -1;
}
static int first_lpcm_off(void)
{   /* the message word written just before a doorbell that carried an LPCM off */
    for (unsigned i = 0; i < n_; ++i) if (log_[i].k == 'W' && log_[i].pa == MBA_PAGE + MBA_MSG + 4 && (log_[i].v == LPCM_FE0_OFF || log_[i].v == LPCM_DSI0_OFF)) return (int)i;
    return -1;
}
static int dpu_writes(void) { int n = 0; for (unsigned i = 0; i < n_; ++i) if (log_[i].k == 'W' && log_[i].pa >= FR_DPU && log_[i].pa < FR_DPU + 0x120000) n++; return n; }

int main(int argc, char **argv)
{
    if (argc < 2) return 2;
    sc = argv[1];
    if (!strncmp(sc, "entry_", 6)) {
        /* chooser-ios WARM-r1: stage A of the menu instance with the DPU domain ABL hands over off (every proven
         * handoff) or on. With TGL_CHOOSER_WARM a live domain is refused before any request but the state query,
         * and the release then sends nothing. */
        int live = !strcmp(sc, "entry_top_on");
        top_on = live; fe0_on = 0; dsi0_on = 0;
        d.t0 = now_us; d.started = 1;
        int rc = stage_a();
        int refuse = 0;
#if defined(TGL_DCS_MENU) && defined(TGL_CHOOSER_WARM) && TGL_CHOOSER_WARM
        refuse = live;
#endif
        if (refuse) {
            CHECK(rc == DCS_C_TOP_LIVE && d.stop == DCS_C_TOP_LIVE);
            CHECK(d.held == 0 && top_ons == 0 && top_offs == 0 && lpcm_offs == 0);
            CHECK(dpu_writes() == 0 && first('W', MBA_PAGE + MBA_MSG, 1, LPB_SET) < 0);
            unsigned before = n_;
            CHECK(tgl_dcs_release() == 0);
            CHECK(n_ == before && top_on); /* nothing given back: the domain stays as ABL left it */
        } else {
            CHECK(rc == 0);
            CHECK(live ? (d.held == 0 && top_ons == 0) : ((d.held & HELD_TOP) && top_ons == 1 && top_on));
        }
        printf("%s %s rc=%d accesses=%u held=%u\n", fails ? "FAIL" : "PASS", sc, rc, n_, d.held);
        return fails ? 1 : 0;
    }
    int want = DCS_C_OK, expect_quiesce = 1;
    uint32_t held = HELD_TOP | HELD_DSI0 | HELD_CLK | HELD_FE0;
#define IS(x) (!strcmp(sc, x))
    if (IS("ok")) { }
    else if (IS("layer_off")) { l0_st = 0; l0_co = 0; }
    else if (IS("layer_settles")) { l0_busy_reads = 40; }
    else if (IS("layer_busy")) { l0_busy_reads = 1 << 30; want = DCS_C_Q_LAYER_BUSY; }
    else if (IS("be_settles")) { be_busy_reads = 20; }
    else if (IS("be_busy")) { be_busy_forever = 1; want = DCS_C_Q_BE_BUSY; }
    else if (IS("no_fe0")) { held = HELD_TOP | HELD_DSI0 | HELD_CLK; fe0_on = 0; expect_quiesce = 0; }
    else { printf("unknown scenario %s\n", sc); return 2; }
#ifndef TGL_DCS_QUIESCE
    if (want != DCS_C_OK) want = DCS_C_OK; /* gate off: the busy fakes are never read */
    expect_quiesce = 0;
#endif
    d.started = 1; d.held = held; d.t0 = now_us;
    int rc = tgl_dcs_release();
    CHECK(rc == want);
    int lp = first_lpcm_off();
    if (!expect_quiesce) {
        CHECK(dpu_writes() == 0);
        CHECK(first('W', Q_GPCSR + Q_BE_DBG_CTL, 0, 0) < 0);
        CHECK(rc != DCS_C_OK || !top_on);
    } else if (want == DCS_C_OK) {
        /* stock order, stock values */
        int t = first('W', FR_DPU + Q_OUTPUT0_START, 1, 0);
        int l = first('R', FR_DPU + Q_L0_DMA_ST, 0, 0);
        int g = first('W', Q_GPCSR + Q_BE_DBG_CTL, 1, Q_BE_DBG_CTL_VAL);
        int gs = first('R', Q_GPCSR + Q_BE_DBG_STATUS, 0, 0);
        int e0 = first('W', FR_DPU + Q_BE_INTR_ENABLE, 1, 0), e1 = first('W', FR_DPU + Q_BE_INTR_ENABLE1, 1, 0);
        int c0 = first('W', FR_DPU + Q_SH_OUTPUT0_CLK_EN, 1, 0), c1 = first('W', FR_DPU + Q_SH_OUTPUT1_CLK_EN, 1, 0);
        int s0 = first('W', FR_DPU + Q_BE_INTR_STATUS, 1, 0xffff1fffu), s1 = first('W', FR_DPU + Q_BE_INTR_STATUS1, 1, 0xfff1ff3fu);
        int o0 = first('W', FR_DPU + Q_BE_INTR_OVERFLOW, 1, 0xffff1fffu), o1 = first('W', FR_DPU + Q_BE_INTR_OVERFLOW1, 1, 0xfff1ff3fu);
        int iso = first('W', FR_DPU + Q_CLOCK_DOMAIN_ISOLATION, 1, 0xf);
        CHECK(t == 0); /* the trigger stops before anything else */
        CHECK(t < l && l < g && g < gs);
        CHECK(gs < e0 && e0 < e1 && e1 < c0 && c0 < c1 && c1 < s0 && s0 < s1 && s1 < o0 && o0 < o1 && o1 < iso);
        CHECK(lp > iso); /* isolation on before the first domain power-off request */
        CHECK(dpu_writes() == 10);
        CHECK(dpu_iso == 0xf && be_en == 0 && be_en1 == 0);
        CHECK(!top_on && !fe0_on && !dsi0_on && top_offs == 1);
    } else {
        /* a busy DPU stops the release before any power-off: the chooser then does not jump */
        CHECK(lp < 0); CHECK(top_offs == 0); CHECK(top_on && fe0_on && dsi0_on);
        CHECK(first('W', FR_DPU + Q_CLOCK_DOMAIN_ISOLATION, 0, 0) < 0);
        CHECK(now_us < 1000 + 2 * (Q_FRAME_US + Q_BE_IDLE_US));
    }
    printf("%s %s rc=%d accesses=%u us=%llu\n", fails ? "FAIL" : "PASS", sc, rc, n_, (unsigned long long)now_us);
    return fails ? 1 : 0;
}
