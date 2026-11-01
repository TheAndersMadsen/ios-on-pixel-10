/* Minimal CPM client for the laguna USB resume — v3.7 LPCM transport.
 *
 * v3.5 device evidence + A-ABL2's instruction-level trace
 * (ABL-MBA-PROTOCOL.md) resolved all three DEVICE-VALIDATE placeholders and
 * explained the v3.5 wedge: the cold path was talking to mbox[0] (GDMC-only,
 * 6 channels — exactly what our stamps read, including the "MBA" magic at
 * +0x00) while the LPCM clock/reset service lives in mailbox idx 2.
 *
 * Wire truth (all instruction-proven in ABL-USB-STATE/ABL-MBA-PROTOCOL):
 *   - mailbox idx 2 base 0x05250000, single channel, channel record +0x08
 *     QID = 0x12, max 4 dwords, poll step 200 µs;
 *   - channel page = base + 0x10000 + QID*0x1000 = 0x05272000;
 *       GO        page+0x00  (write 1 AFTER the message copy)
 *       ctl       page+0x04  (bit24 SET — LPCM header 0x08000000 has bit21=0)
 *       doorbell  page+0x08  (write 1; read-back; dsb sy; completion = bit0)
 *       rx status page+0x0c  (poll client only; not used here)
 *       message   page+0x100 ..+16
 *   - send order (ABL mba_send 0xbe04fb90): doorbell(1) → ctl bit24 set →
 *     copy message → GO(1) → poll completion (200 µs × 1001 ≈ 200 ms,
 *     timeout err -13) → copy reply IN-PLACE over the message → doorbell(1);
 *   - message = {0x08000000, cmd_dword, aux, 0}; clock gate cmd_dword =
 *     0x04 | (seq<<8) | (gate_id<<16) | ((1^enable)<<24); LPCM success =
 *     reply dword1 == 0 (reply dword0 byte0 is a type tag ∈ {0,2,3});
 *   - the (w&0x7f400000)==0x1a400000 + bit23 validation is the GDMC
 *     mbox[0] convention — REMOVED from this path.
 * Reset deasserts use the ABL release/put builder shape
 * (0xbe03159c): cmd_dword = 0x02 | (seq<<8) | (id<<16) | ((1^state)<<24),
 * aux = 1 — DEVICE-VALIDATE for our lpcm5 reset ids (0x06..0x0d): the
 * cpm-rst stamps carry id<<8|reply so the device confirms or corrects the
 * id space. mbox[0]/mbox[1] probes stay as liveness/geometry diagnostics.
 *
 * Bounded everywhere (felix discipline): hard 1001-iteration completion
 * count (≈200 ms at 200 µs/step, matching ABL exactly) PLUS a cntvct
 * deadline; one attempt per boot; failures latch cpm.failed and refuse all
 * later sends (fail closed -> paint + photograph window + PSCI reset).
 */
#include "tgl_cpm.h"
#include "probe.h"
#include "tgl_stamp.h"

/* ABL-proven mailbox bases (ABL-USB-STATE.md §5): mbox[0] GDMC (6ch) and
 * mbox[1] stay as liveness diagnostics; mbox[2] is the LPCM service. */
#define MBA_MBOX0_PA 0x06250000UL
#define MBA_MBOX1_PA 0x0e000000UL
#define MBA_MBOX2_PA 0x05250000UL
#define MBA_LPCM_PA  MBA_MBOX2_PA
#define MBA_LPCM_QID 0x12u

/* Channel page arithmetic (ABL-USB-PROTOCOL ops +0x50): 0x10000+QID*0x1000,
 * message window at page+0x100. */
#define MBA_PAGE(base, qid) ((uintptr_t)(base) + 0x10000UL + \
    (uintptr_t)(qid) * 0x1000UL)
#define LPCM_GO_OFF     0x00u
#define LPCM_CTL_OFF    0x04u
#define LPCM_ST_OFF     0x08u
#define LPCM_MSG_OFF    0x100u
#define LPCM_MSG_WORDS  4u
#define LPCM_CTL_BIT24  0x01000000u
#define LPCM_ST_DONE    0x1u
#define LPCM_POLL_MAX   1001u   /* ABL: 0x3e9 iterations -> err -13 */
#ifndef MBA_POLL_US
#define MBA_POLL_US     200u    /* ch[+0x18]; host tests override to 0 */
#endif
#define MBA_TIMEOUT_MS  400u    /* 1001 x 200 µs + margin (belt over the
				 * hard iteration bound; both must fire) */

#define CPM_USB_POWER_STATUS_PA 0x0c450000UL

/* Corrected LPCM frame fields (ABL-LPCM-REQUEST.md §2/§4, byte-verified):
 * msg[1] = cmd | seq<<8 | id<<16 | (1^en)<<24 with byte1 = 0x05 (static
 * per-descriptor seq; every hsio_n row carries desc+8 = 0), cmd 0x02 byte2
 * = the DT lpcm5 CLOCK numbers (+0x30 column), cmd 0x04 byte2 = the RESET
 * ids (+0x34 column); gate frames carry aux = 1; byte3 = 0 = ON/assert-release-off
 * per class (put: 0=ON, rst: 1=DEASSERT). */
#define LPCM_HDR        0x08000000u
#define LPCM_CMD_PUT    0x02u   /* gate/put, +0x30 id column (DT clock numbers) */
#define LPCM_CMD_RST    0x04u   /* reset ctrl, +0x34 id column */
#define LPCM_SEQ_HSIO   0x05u   /* seq_table[0]; every hsio_n row has desc+8=0 */
#define LPCM_AUX_PUT    1u      /* gate frames carry aux=1 */

/* USB2 resources (A-DT DT numbers = cmd-0x02 put column; cmd-0x04 reset
 * column per ABL-LPCM-REQUEST §2.4 — the two derivations agree). */
#define CPM_CLK_USBC_NON_STICKY 0x07u
#define CPM_CLK_USBC_STICKY     0x08u
#define CPM_CLK_U2PHY_APB       0x0eu
#define CPM_CLK_USB2_PHY_RESET  0x11u
#define CPM_RST_USBC_NON_STICKY 0x0au
#define CPM_RST_USBC_STICKY     0x0bu
#define CPM_RST_USBC_DRD_BUS    0x0cu
#define CPM_RST_U2PHY_APB       0x09u
#define CPM_RST_USB_TOP_CSR     0x06u
#define CPM_RST_USB2_PHY        0x0du

static struct {
    int ready, failed;
    int phy_revived; /* v3.9: the warm-path revive is once per boot */
    unsigned first_send; /* v3.6 wedge forensics: first send only */
} cpm;

/* v3.9: forensics stamps are first-send-only (ring budget). */
static unsigned mba_first_send = 1;

static void cpm_barrier(void)
{
#ifdef __aarch64__
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}

static int rd(uintptr_t pa, uint32_t *out)
{
    return probe_read32(pa, out) ? 0 : -1;
}

static int wr(uintptr_t pa, uint32_t value)
{
    return probe_write32(pa, value) ? 0 : -1;
}

static uint64_t counter_frequency(void)
{
    uint64_t freq = 0;
#if defined(__aarch64__) && !defined(TGL_STAMP_HOST)
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
#endif
    return freq ? freq : 38400000;
}

static uint64_t counter_now(void)
{
    uint64_t now = 0;
#if defined(__aarch64__) && !defined(TGL_STAMP_HOST)
    __asm__ volatile("isb\n\tmrs %0, cntpct_el0" : "=r"(now));
#endif
    return now;
}

/* 200 µs-class sleep between completion polls. Iteration-guarded: a frozen
 * counter must not become an infinite spin (it also exits immediately for
 * MBA_POLL_US == 0 in host tests). */
static void lpcm_delay_us(unsigned us)
{
#if defined(__aarch64__) && !defined(TGL_STAMP_HOST)
    if (!us) return;
    uint64_t freq, now, end;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
    if (!freq) freq = 38400000;
    __asm__ volatile("mrs %0, cntpct_el0" : "=r"(now));
    end = now + (freq * us + 999999) / 1000000;
    uint64_t guard = 512 + (uint64_t)us * 512;
    do {
        __asm__ volatile("isb\n\tmrs %0, cntpct_el0" : "=r"(now));
    } while (now < end && --guard);
#else
    (void)us;
#endif
}

/* tgl_cpm_init: liveness + geometry stamps (mbox[0] GDMC diagnostics per
 * ABL-USB-STATE §5, mbox[2] LPCM magic per ABL-MBA-PROTOCOL §5 — the LPCM
 * base should read the same 0x004D4241 'MBA' magic). */
int tgl_cpm_init(void)
{
    cpm.failed = 0;
    cpm.ready = 0;
    cpm.phy_revived = 0;
    tgl_stamp(TGL_STAGE_CPM_GEO, TGL_STAMP_F_ENTER, 0);
    uint32_t live = 0, v0 = 0, v1 = 0, v2 = 0xffffffffu;
    if (rd(MBA_MBOX0_PA, &v0)) {
        tgl_stamp(TGL_STAGE_MBA_LIVE, TGL_STAMP_F_FAULT,
            (1u << 24) | (MBA_MBOX0_PA & 0xffff));
        tgl_stamp(TGL_STAGE_CPM_GEO, TGL_STAMP_F_FAULT, live);
        cpm.failed = 1;
        return -1;
    }
    live |= 1u; /* mbox[0] readable (hard requirement) */
    if (!rd(MBA_MBOX1_PA, &v1)) live |= 2u; /* absent is diagnostic, not fatal */
    if (!rd(MBA_MBOX2_PA, &v2)) live |= 4u; /* LPCM magic record below */
    else v2 = 0xffffffffu;
    tgl_stamp(TGL_STAGE_MBA_LIVE, TGL_STAMP_F_DONE,
        (uint64_t)live << 32 | v0);
    /* LPCM magic record: the doc predicts 0x004D4241 at mbox[2]+0x00. */
    tgl_stamp(TGL_STAGE_CPM_GEO2, v2 == 0x004d4241u ? TGL_STAMP_F_DONE :
        TGL_STAMP_F_FAULT, v2);
    tgl_stamp(TGL_STAGE_CPM_GEO, TGL_STAMP_F_DONE,
        (uint32_t)6 << 16 | live); /* mbox[0] static channel count */
    cpm.ready = 1;
    return 0;
}

/* One blocking LPCM request (ABL mba_send §4, register-for-register):
 * doorbell(1)+readback+dsb -> ctl bit24 set -> copy message -> GO(1) ->
 * poll completion (hard 1001-iteration bound) -> copy reply in-place ->
 * doorbell(1). *response = reply dword1 (0 = OK for clock gates). */
static int mba_send(uint32_t msg[4], int32_t *response)
{
    /* One attempt per boot: after any failure the client is latched and
     * refuses without touching the wire (felix/CPM-FIRST §4.6). */
    if (!cpm.ready || cpm.failed) return -1;
    uint32_t failure = 0;
    uint32_t id = (msg[1] >> 16) & 0xffu;
    uintptr_t page = MBA_PAGE(MBA_LPCM_PA, MBA_LPCM_QID);
    int first = mba_first_send;
    mba_first_send = 0;
    tgl_stamp(TGL_STAGE_MBA_SEND, TGL_STAMP_F_ENTER, msg[1]);
    /* step 4: doorbell(1), read-back, dsb — BEFORE the message copy. */
    if (first)
        tgl_stamp(TGL_STAGE_MBA_SEND, TGL_STAMP_F_ENTER,
            id << 8 | 0xf0u); /* pre-doorbell marker */
    if (wr(page + LPCM_ST_OFF, 1)) failure = 1;
    else {
        uint32_t rb;
        if (rd(page + LPCM_ST_OFF, &rb)) failure = 2;
        else cpm_barrier();
    }
    /* step 6: LPCM header bit21 = 0 -> ctl bit24 is SET. */
    if (!failure) {
        uint32_t ctl;
        if (rd(page + LPCM_CTL_OFF, &ctl)) failure = 3;
        else if (wr(page + LPCM_CTL_OFF, ctl | LPCM_CTL_BIT24)) failure = 4;
    }
    /* step 7: copy the message into page+0x100. */
    if (!failure) {
        for (unsigned i = 0; i < LPCM_MSG_WORDS; i++)
            if (wr(page + LPCM_MSG_OFF + i * 4, msg[i])) { failure = 5; break; }
    }
    /* step 8: GO(1) after the copy. */
    if (!failure && wr(page + LPCM_GO_OFF, 1)) failure = 6;
    if (failure) {
        tgl_stamp(TGL_STAGE_MBA_SEND, TGL_STAMP_F_FAULT,
            id << 8 | failure);
        cpm.failed = 1;
        cpm.ready = 0;
        return -1;
    }
    /* v3.8 wire evidence: echo the request words (A-ABL3 diffs these
     * against ABL's builder output — the v37 clock request was NACKed
     * with reply dword1 = 0xfffffff8-truncated, cause unknown until the
     * request/reply pair is on the record for every send). */
    tgl_stamp(TGL_STAGE_LPCM_REQ0, TGL_STAMP_F_DONE, msg[0]);
    tgl_stamp(TGL_STAGE_LPCM_REQ1, TGL_STAMP_F_DONE, msg[1]);
    /* step 9: poll completion, hard 1001-iteration bound (~200 ms) plus a
     * cntvct deadline — the v3.5 wedge was in the writes, but the wait is
     * belt-and-braces bounded against both a stuck register and a frozen
     * counter. */
    struct deadline { uint64_t value; uint32_t budget; };
    uint64_t freq = counter_frequency();
    struct deadline dl = { counter_now() + freq * MBA_TIMEOUT_MS / 1000,
                           LPCM_POLL_MAX + 1 };
    uint32_t w = 0;
    int done = 0;
    for (unsigned i = 0; i < LPCM_POLL_MAX; i++) {
        if (rd(page + LPCM_ST_OFF, &w)) {
            tgl_stamp(TGL_STAGE_MBA_ACK, TGL_STAMP_F_FAULT, 0);
            failure = 7;
            break;
        }
        if (i == 0 && first)
            tgl_stamp(TGL_STAGE_MBA_RESP0, TGL_STAMP_F_DONE, w);
        if (w & LPCM_ST_DONE) { done = 1; break; }
        lpcm_delay_us(MBA_POLL_US);
        if (counter_now() >= dl.value || !dl.budget--) { failure = 8; break; }
    }
    if (!failure && !done) {
        /* ABL's timeout err -13. */
        tgl_stamp(TGL_STAGE_MBA_ACK, TGL_STAMP_F_TIMEOUT, w);
        failure = 8;
    }
    /* step 10: reply is IN-PLACE — copy it back over msg (our buffer). */
    uint32_t reply0 = 0, reply1 = 0;
    if (!failure && done) {
        for (unsigned i = 0; i < LPCM_MSG_WORDS; i++)
            if (rd(page + LPCM_MSG_OFF + i * 4, &msg[i])) { failure = 9; break; }
        reply0 = msg[0];
        reply1 = msg[1];
        /* v3.8: full reply evidence, every request. */
        tgl_stamp(TGL_STAGE_LPCM_REPLY0, TGL_STAMP_F_DONE, reply0);
        tgl_stamp(TGL_STAGE_LPCM_REPLY1, TGL_STAMP_F_DONE, reply1);
    }
    /* step 11: post-reply doorbell(1) (LPCM is a type-0 channel: no 0x100
     * ack variant). */
    if (!failure) {
        if (wr(page + LPCM_ST_OFF, 1)) failure = 10;
        else {
            uint32_t rb;
            if (rd(page + LPCM_ST_OFF, &rb)) failure = 11;
            else cpm_barrier();
        }
    }
    /* ABL accepts LPCM reply type tags 0/2/3 only. Validate the envelope as
     * well as dword1; a zero status in a malformed reply is not a power proof. */
    if (!failure && (reply0 & 0xffu) != 0 && (reply0 & 0xffu) != 2 &&
        (reply0 & 0xffu) != 3) failure = 12;
    if (failure == 8) {
        cpm.failed = 1;
        cpm.ready = 0;
        return -1;
    }
    if (failure) {
        tgl_stamp(TGL_STAGE_MBA_ACK, TGL_STAMP_F_FAULT,
            (uint32_t)reply0 << 16 | failure);
        cpm.failed = 1;
        cpm.ready = 0;
        return -1;
    }
    /* First send only: the full reply words are the transport proof; later
     * requests carry theirs via the cpm-clk/cpm-rst value stamps (ring
     * budget). */
    if (first)
        tgl_stamp(TGL_STAGE_MBA_ACK, TGL_STAMP_F_DONE,
            (uint64_t)reply0 << 32 | reply1);
    *response = (int32_t)reply1;
    return 0;
}

static int board_power_on(void *context)
{
    (void)context;
    uint32_t status;
    /* The A-DT canary read: the wrapper CSR region shares the USB clock
     * domain, so this read is also the "did CPM clocking take" probe. */
    tgl_stamp(TGL_STAGE_USB_PWR, TGL_STAMP_F_ENTER, 0);
    if (rd(CPM_USB_POWER_STATUS_PA, &status)) {
        tgl_stamp(TGL_STAGE_USB_PWR, TGL_STAMP_F_FAULT, 0);
        return -1;
    }
    /* USB2 PMU D0 is required; USB3/DP power state is irrelevant to EP0 HS. */
    if ((status & 3) != 0) {
        tgl_stamp(TGL_STAGE_USB_PWR, TGL_STAMP_F_REFUSED, status);
        return -1;
    }
    tgl_stamp(TGL_STAGE_USB_PWR, TGL_STAMP_F_DONE, status);
    return 0;
}

/* A-ABL3 dual-id table (ABL-LPCM-REQUEST.md §2.4): reset id (cmd 0x04,
 * +0x34 column) -> the paired clock's put id (cmd 0x02, +0x30 column).
 * ABL never sends a cmd-0x04 without its cmd-0x02 put first. */
static const uint8_t cpm_rst_pair[][2] = {
    { 0x0au, 0x07u },   /* usbc_non_sticky: rst 0x0a, put 0x07 */
    { 0x0bu, 0x08u },   /* usbc_sticky:    rst 0x0b, put 0x08 */
    { 0x09u, 0x0eu },   /* u2phy_apb:      rst 0x09, put 0x0e */
    { 0x0du, 0x11u },   /* usb2_phy_reset: rst 0x0d, put 0x11 */
    { 0x06u, 0x0bu },   /* usb_top_csr:    rst 0x06, put 0x0b */
    { 0x0cu, 0x09u },   /* usb_drd_bus:    rst 0x0c, put 0x09 */
};
static int lpcm_put(uint32_t id)
{
    uint32_t msg[4] = {
        0x08000000u,
        0x02u | (LPCM_SEQ_HSIO << 8) | ((id & 0xff) << 16),
        LPCM_AUX_PUT, 0u,
    };
    int32_t response = -1;
    if (mba_send(msg, &response)) {
        tgl_stamp(TGL_STAGE_CPM_CLK, TGL_STAMP_F_FAULT,
            (id & 0xff) << 8 | 0xff);
        return -1;
    }
    tgl_stamp(TGL_STAGE_CPM_CLK,
        response ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)((id & 0xff) << 8 | ((uint32_t)response & 0xff)));
    return response;
}

int tgl_cpm_lpcm_put(uint32_t id) { return lpcm_put(id); }

static int board_clock_enable(void *context, uint32_t id)
{
    (void)context;
    if (id != LAGUNA_USB_CLOCK_USBC_NON_STICKY &&
        id != LAGUNA_USB_CLOCK_USBC_STICKY &&
        id != LAGUNA_USB_CLOCK_U2PHY_APB &&
        id != LAGUNA_USB_CLOCK_USB2_PHY_RESET) return -1;
    /* ABL sets hsio_n_phy_fw_clk (put id 0x03) to 400 MHz on the way into
     * USB init (set_rate builder 0xbe03163c, ABL-LPCM-REQUEST.md §2.3). */
    static int rate_done;
    if (!rate_done) {
        uint32_t msg[4] = {
            0x08000000u,
            0x50000002u | (0x03u << 16),
            0x17d78400u, 0u,          /* 400 MHz */
        };
        int32_t response = -1;
        rate_done = 1;
        if (mba_send(msg, &response))
            tgl_stamp(TGL_STAGE_CPM_CLK, TGL_STAMP_F_FAULT, 0x03f8);
        else
            tgl_stamp(TGL_STAGE_CPM_CLK,
                response ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
                (uint32_t)(0x03u << 8 | ((uint32_t)response & 0xff)));
    }
    /* Gate/put builder 0xbe03159c: byte0=0x02, byte1=seq 0x05 (static;
     * desc+8=0 on every hsio_n row), byte2=DT lpcm5 clock id (+0x30),
     * byte3=0 = ON, aux=1 (ABL-LPCM-REQUEST.md §2.2). */
    return lpcm_put(id);
}

static int lpcm_reset_deassert(uint32_t id)
{
    /* Reset-control builder 0xbe031514: byte0=0x04, byte1=seq 0x05,
     * byte2=reset id (+0x34), byte3=1 = DEASSERT (en=0), aux=0
     * (ABL-LPCM-REQUEST.md §2.1). The caller must complete the paired put. */
    uint32_t msg[4] = {
        0x08000000u,
        0x04u | (LPCM_SEQ_HSIO << 8) | ((id & 0xff) << 16) | (1u << 24),
        0u, 0u,
    };
    int32_t response = -1;
    if (mba_send(msg, &response)) {
        tgl_stamp(TGL_STAGE_CPM_RST, TGL_STAMP_F_FAULT,
            (id & 0xff) << 8 | 0xff);
        return -1;
    }
    tgl_stamp(TGL_STAGE_CPM_RST,
        response ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)((id & 0xff) << 8 | ((uint32_t)response & 0xff)));
    return response;
}

static int board_reset_deassert(void *context, uint32_t id)
{
    uint32_t pair_clk = 0;
    (void)context;
    for (uint32_t i = 0; i < sizeof(cpm_rst_pair)/sizeof(cpm_rst_pair[0]); i++) {
        if (cpm_rst_pair[i][0] == (id & 0xff)) {
            pair_clk = cpm_rst_pair[i][1];
            break;
        }
    }
    if (!pair_clk) return -1;
    /* ABL pairs every cmd-0x04 deassert with its cmd-0x02 put; the reset
     * id column (+0x34) carries A-DT's DT reset numbers directly. */
    if (lpcm_put(pair_clk)) return -1;
    return lpcm_reset_deassert(id);
}

int tgl_cpm_lpcm_reset_deassert(uint32_t id) { return lpcm_reset_deassert(id); }


/* I2: HSIO_S domain derived from live ABL descriptor+8=1 and
 * seq_table[1]=6, independently matching the DT reset controller. This
 * reset descriptor has put id UINT32_MAX, so do not invent a USB-style pair.
 * Existing USB wrappers and board callbacks retain selector 5 unchanged. */
int tgl_cpm_ufs_phy_reset_deassert(void)
{
    static unsigned attempted;
    static int result = -1;
    uint32_t msg[4] = {
        0x08000000u, 0x01030604u, 0u, 0u,
    };
    int32_t response = -1;
    if (attempted) return result;
    if (!cpm.ready || cpm.failed) return -1;
    attempted = 1;
    if (mba_send(msg, &response)) {
        tgl_stamp(TGL_STAGE_CPM_RST, TGL_STAMP_F_FAULT, 0x603ffu);
        return -1;
    }
    tgl_stamp(TGL_STAGE_CPM_RST,
        response ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        0x60300u | ((uint32_t)response & 0xffu));
    result = response;
    return result;
}

/* Test hook cannot be enabled in a device build. This seam receives the
 * same register array used by the native wrapper, not a separate frame model. */
#if defined(TGL_CPM_SMC_HOST_TEST) && !defined(TGL_STAMP_HOST)
#error TGL_CPM_SMC_HOST_TEST requires TGL_STAMP_HOST
#endif
static void ufs_clock_smc(uint64_t args[8])
{
#if defined(TGL_CPM_SMC_HOST_TEST)
    extern void tgl_cpm_smc_host_call(uint64_t args[8]);
    tgl_cpm_smc_host_call(args);
#elif defined(__aarch64__) && !defined(TGL_STAMP_HOST)
    register uint64_t x0 __asm__("x0") = args[0];
    register uint64_t x1 __asm__("x1") = args[1];
    register uint64_t x2 __asm__("x2") = args[2];
    register uint64_t x3 __asm__("x3") = args[3];
    register uint64_t x4 __asm__("x4") = args[4];
    register uint64_t x5 __asm__("x5") = args[5];
    register uint64_t x6 __asm__("x6") = args[6];
    register uint64_t x7 __asm__("x7") = args[7];
    __asm__ volatile("smc #0"
        : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3),
          "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
        : : "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15",
            "x16", "x17", "cc", "memory");
    args[0] = x0;
    args[1] = x1;
#else
    args[0] = args[1] = UINT64_MAX; /* host unsupported, never execute SMC */
#endif
}

/* DT use-smc clocks: derive the route from Google's clk-cpm.c rather than
 * turning the DT domain number into a guessed mailbox command. No caller
 * is added here. The UFS owner must admit this as its own device hypothesis.
 * A synchronous SMC has no software timeout; keep watchdog+section guard. */
int tgl_cpm_ufs_clock_enable(uint32_t id,
    struct tgl_cpm_ufs_clock_reply *reply)
{
    static unsigned attempted;
    static unsigned completed;
    static unsigned failed;
    static struct tgl_cpm_ufs_clock_reply cached[2];
    struct tgl_cpm_ufs_clock_reply result = { UINT64_MAX, UINT64_MAX };
    uint64_t args[8] = { UINT64_C(0x82000702), 6u, id, 1u, 0, 0, 0, 0 };
    unsigned index, bit;

    if (reply) *reply = result;
    if (id == 3u) index = 0u;
    else if (id == 0x10u) index = 1u;
    else return -1;
    bit = 1u << index;
    /* A section-guard unwind can bypass the post-SMC return path. An
     * attempted request is not cached success until it completed. Refuse
     * ANY later clock request after such an interrupted call. */
    if (failed || attempted != completed) { failed = 1; return -1; }
    if (attempted & bit) {
        if (reply) *reply = cached[index];
        return 0; /* idempotent success, no duplicate firmware request */
    }
    attempted |= bit;
    ufs_clock_smc(args);
    result.a0 = args[0];
    result.a1 = args[1];
    if (reply) *reply = result;
    if (result.a0 || result.a1) { failed = 1; return -1; }
    cached[index] = result;
    completed |= bit;
    return 0;
}

int tgl_cpm_display_pixel_clocks(void)
{
    static unsigned attempted;
    if (attempted) return -1;
    attempted = 1; /* display revive gets one clock/reset attempt per boot */
    /* ABL-LPCM-REQUEST §2.4 rows 0x3a/0x3b: hsio_n_pixel_ck0/1.
     * These are cmd-02 PUT ids 01/02, paired with distinct cmd-04 RESET ids
     * 07/08. Never reuse the DT sswrp-id or treat reset id 07 as a clock id. */
    if (lpcm_put(0x01) || lpcm_reset_deassert(0x07)) return -1;
    if (lpcm_put(0x02) || lpcm_reset_deassert(0x08)) return -1;
    return 0;
}

static int board_repeater(void *context)
{
    (void)context;
    /* The ABL has just used this exact peripheral path. Preserve its Type-C
     * orientation, TUSB2E11 configuration and PLL/tuning; no I2C writes. */
    return cpm.ready && !cpm.failed ? 0 : -1;
}

const struct laguna_usb_board_ops *tgl_cpm_board_ops(void)
{
    /* Runtime initialization keeps the image free of absolute pointer relocs. */
    static struct laguna_usb_board_ops ops;
    ops.power_on = board_power_on;
    ops.clock_enable = board_clock_enable;
    ops.reset_deassert = board_reset_deassert;
    ops.repeater_peripheral = board_repeater;
    return &ops;
}
