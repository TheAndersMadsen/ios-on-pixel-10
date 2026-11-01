/* R1: bounded goog-mba queue-mode DPU power votes.
 *
 * This is deliberately separate from tgl_cpm.c's ABL polling-mode LPCM client:
 * queue service frames (LPB top + LPCM genpd subdomains) and ABL cmd02/cmd04
 * clock/reset frames are different protocols on different channel geometry.
 * Never encode sswrp-id 5 as an ABL cmd02 clock id.
 */
#include "tgl_display.h"
#include "probe.h"
#include "tgl_stamp.h"

#define CPM_GLOBAL 0x05250000UL
#define CPM_TX 0x05260000UL
#define CPM_RX 0x05261000UL
#define MBA_DOORBELL 0x00u
#define MBA_IRQ_CFG 0x04u
#define MBA_IRQ_STATUS 0x08u
#define MBA_OUTSTANDING 0x10u
#define MBA_BUFFER_WORDS 0x34u
#define MBA_MSG(i) (0x100u + (i) * 4u)
#define MBA_IRQ_MESSAGE (1u << 0)
#define MBA_IRQ_ACK (1u << 8)
#define MBA_CFG (MBA_IRQ_ACK | (1u << 16) | (1u << 24))
#define CPM_WORDS 4u
#define CPM_TIMEOUT_MS 3000u
#define CPM_POLL_US 200u
#define CPM_POLL_MAX (CPM_TIMEOUT_MS * 1000u / CPM_POLL_US + 1u)

#define PWR_TOP 1u
#define PWR_DSI0 2u
#define PWR_FE0 3u

struct queue {
    unsigned attempted, failed, ready;
    uint32_t tx_words, rx_words, tx_cursor, rx_cursor;
};
static struct queue q;
#ifdef TGL_DISPLAY_HOSTTEST
void tgl_display_power_test_reset(void)
{
    volatile uint8_t *p = (volatile uint8_t *)&q;
    for (unsigned i = 0; i < sizeof(q); ++i) p[i] = 0;
}
#endif

static int rd(uintptr_t pa, uint32_t *v) { return probe_read32(pa, v) ? 0 : -1; }
static int wr(uintptr_t pa, uint32_t v) { return probe_write32(pa, v) ? 0 : -1; }

static uint64_t freq(void)
{
    uint64_t f = 0;
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(f));
#endif
    return f ? f : 38400000;
}
static uint64_t now(void)
{
    uint64_t n = 0;
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(n));
#endif
    return n;
}
static void delay200(void)
{
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    uint64_t f = freq(), n = now(), end = n + (f * CPM_POLL_US + 999999) / 1000000;
    uint64_t guard = 512 + CPM_POLL_US * 512;
    do { __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(n)); }
    while (now() < end && --guard);
#endif
}

static int fail(unsigned step, unsigned code, uint64_t evidence)
{
    q.failed = 1;
    q.ready = 0;
    tgl_stamp(TGL_STAGE_DISP_POWER, TGL_STAMP_F_REFUSED,
        ((uint64_t)step << 48) | ((uint64_t)code << 32) | evidence);
    return -1;
}

static int capacity(uintptr_t client, uintptr_t global, uint32_t *words)
{
    if (rd(client + MBA_BUFFER_WORDS, words)) return -1;
    if (*words && *words <= 256 && !(*words % CPM_WORDS)) return 0;
    uint32_t index = (uint32_t)((client & 0x1ffff) / 0x1000);
    if (rd(global + 0x10 + index * 4, words)) return -1;
    return *words && *words <= 256 && !(*words % CPM_WORDS) ? 0 : -1;
}

static int queue_geometry(void)
{
    if (capacity(CPM_TX, CPM_GLOBAL, &q.tx_words) ||
        capacity(CPM_RX, CPM_GLOBAL, &q.rx_words))
        return fail(0, 1, ((uint64_t)q.rx_words << 32) | q.tx_words);
    uint32_t outstanding = 0, rx_status = 0;
    if (rd(CPM_TX + MBA_OUTSTANDING, &outstanding) ||
        rd(CPM_RX + MBA_IRQ_STATUS, &rx_status))
        return fail(0, 2, 0);
    /* Refuse to invent ownership over queued work. Queue init does not drain
     * RX or cancel an older LPB event, so stale input is terminal, not ignored. */
    if (outstanding || (rx_status & MBA_IRQ_MESSAGE))
        return fail(0, 3, ((uint64_t)rx_status << 32) | outstanding);
    q.tx_cursor = q.rx_cursor = 0;
    return 0;
}

static int wait_tx(unsigned step)
{
    tgl_stamp(TGL_STAGE_DISP_POWER, TGL_STAMP_F_ENTER,
        ((uint64_t)step << 32) | MBA_IRQ_STATUS);
    uint64_t deadline = now() + freq() * CPM_TIMEOUT_MS / 1000;
    uint32_t status = 0;
    for (unsigned i = 0; i < CPM_POLL_MAX; ++i) {
        if (rd(CPM_TX + MBA_IRQ_STATUS, &status)) return fail(step, 4, i);
        if (status & MBA_IRQ_ACK) return 0;
        delay200();
        if (now() >= deadline) return fail(step, 5, status);
    }
    return fail(step, 5, status);
}

static int init_queue(void)
{
    if (queue_geometry()) return -1;
    if (wr(CPM_TX + MBA_IRQ_CFG, MBA_CFG)) return fail(0, 6, 0);
    if (wr(CPM_TX + MBA_IRQ_STATUS, MBA_IRQ_ACK)) return fail(0, 7, 0);
    const uint32_t init[4] = { 0x100, 0, 0, 0 };
    for (unsigned i = 0; i < 4; ++i)
        if (wr(CPM_TX + MBA_MSG(q.tx_cursor + i), init[i]))
            return fail(0, 8, i);
    q.tx_cursor = q.rx_cursor = 0;
    if (wr(CPM_TX + MBA_DOORBELL, 1)) return fail(0, 9, 0);
    if (wait_tx(0)) return -1;
    q.ready = 1;
    return 0;
}

struct transaction {
    unsigned step, top, tx_done, ack_done, event_done, wait_event;
    uint32_t sequence, token, destination;
};

static int receive_one(struct transaction *t, uint32_t *words_out)
{
    uint32_t w[4];
    for (unsigned i = 0; i < 4; ++i)
        if (rd(CPM_RX + MBA_MSG(q.rx_cursor + i), &w[i])) return -1;
    for (unsigned i = 0; i < 4; ++i) words_out[i] = w[i];
    q.rx_cursor += 4;
    if (q.rx_cursor >= q.rx_words) q.rx_cursor = 0;
    if (wr(CPM_RX + MBA_IRQ_STATUS, MBA_IRQ_MESSAGE)) return -1;
    uint32_t h = w[0], type = (h >> 29) & 3;
    if (!(h & 0x80000000u) || (h & 0x1f000000u) || type == 3) return -2;
    uint32_t src = (h >> 8) & 0xff, dst = h & 0xff, token = (h >> 20) & 0xf;
    if (dst != 7) return -3;
    if (type == 2) {
        if (src != t->destination || token != t->token || t->ack_done) return -3;
        if (t->top) {
            /* LPB response payload: result, command status, wire sswrp id. */
            if (w[1] != 15 || w[3] != 5) return -4;
            if (w[2] == 19) return -19; /* NO_EFFECT: indeterminate, stop. */
            if (w[2] == 15) {
                if (t->event_done) return -4; /* stale-event ambiguity */
                t->ack_done = 1;
            } else if (w[2] == 18) {
                t->ack_done = 1;
                t->wait_event = 1;
            } else return -4;
        } else {
            if (w[1] != 0) return -5;
            t->ack_done = 1;
        }
    } else if (type == 0) {
        /* Asynchronous LPB event {wire id,event,latency}. It has no request
         * identity; only this serialized fresh queue attempt may consume it. */
        if (!t->top || src != 5 || t->event_done || w[1] != 5 || w[2] != 0)
            return -3;
        t->event_done = 1;
    } else return -3;
    return 0;
}

static int transact(unsigned step, uint32_t sequence, uint32_t destination,
    const uint32_t payload[3])
{
    if (!q.ready || q.failed || sequence < 1 || sequence > 13) return -1;
    struct transaction t = { .step = step, .top = step == PWR_TOP,
        .sequence = sequence, .destination = destination };
    if (wr(CPM_TX + MBA_IRQ_STATUS, MBA_IRQ_ACK)) return fail(step, 10, 0);
    uint32_t outstanding = 0;
    if (rd(CPM_TX + MBA_OUTSTANDING, &outstanding)) return fail(step, 11, 0);
    if (outstanding >= q.tx_words / 4) return fail(step, 12, outstanding);
    uint32_t msg[4] = { 0xa0000000u | (t.token << 20) | (sequence << 16) |
        (7u << 8) | destination, payload[0], payload[1], payload[2] };
    for (unsigned i = 0; i < 4; ++i)
        if (wr(CPM_TX + MBA_MSG(q.tx_cursor + i), msg[i]))
            return fail(step, 13, msg[0]);
    q.tx_cursor += 4;
    if (q.tx_cursor >= q.tx_words) q.tx_cursor = 0;
    if (wr(CPM_TX + MBA_DOORBELL, 1)) return fail(step, 14, msg[0]);

    tgl_stamp(TGL_STAGE_DISP_POWER, TGL_STAMP_F_ENTER, msg[0]);
    uint64_t deadline = now() + freq() * CPM_TIMEOUT_MS / 1000;
    for (unsigned i = 0; i < CPM_POLL_MAX; ++i) {
        uint32_t tx_status = 0, rx_status = 0;
        if (rd(CPM_TX + MBA_IRQ_STATUS, &tx_status) ||
            rd(CPM_RX + MBA_IRQ_STATUS, &rx_status))
            return fail(step, 15, i);
        if (tx_status & MBA_IRQ_ACK) t.tx_done = 1;
        if (rx_status & MBA_IRQ_MESSAGE) {
            uint32_t response[4] = {0};
            int rr = receive_one(&t, response);
            if (rr == -19)
                return fail(step, 19, ((uint64_t)response[1] << 32) | response[2]);
            if (rr)
                return fail(step, 16,
                    ((uint64_t)(uint32_t)-rr << 32) | response[0]);
            /* Malformed, unrelated, duplicate and NACK responses are terminal;
             * none is allowed to postpone a deadline or complete a vote. */
        }
        if (t.tx_done && t.ack_done && (!t.wait_event || t.event_done)) {
            tgl_stamp(TGL_STAGE_DISP_POWER, TGL_STAMP_F_DONE,
                ((uint64_t)step << 32) | msg[0]);
            return 0;
        }
        delay200();
        if (now() >= deadline) return fail(step, 17,
            ((uint64_t)t.ack_done << 2) | ((uint64_t)t.event_done << 1) | t.tx_done);
    }
    return fail(step, 17, 0);
}

int tgl_display_power_on(uint32_t *proven_domains)
{
    if (!proven_domains) return -1;
    *proven_domains = 0;
    if (q.attempted || q.failed) return -1;
    q.attempted = 1; /* one queue epoch and one top-domain vote per boot */
    uint64_t daif = 0;
    (void)daif;
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    __asm__ volatile("mrs %0, daif; msr daifset, #0xf; isb" : "=r"(daif) :: "memory");
#endif
    int rc = init_queue();
    const uint32_t top[3] = { 2, 5, 1 };
    const uint32_t dsi0[3] = { 0x01020001, 0, 0 };
    const uint32_t fe0[3] = { 0x01000001, 0, 0 };
    if (!rc) rc = transact(PWR_TOP, 1, 5, top);
    if (!rc) {
        *proven_domains |= TGL_DISPLAY_DOMAIN_TOP;
        rc = transact(PWR_DSI0, 2, 8, dsi0);
    }
    if (!rc) {
        *proven_domains |= TGL_DISPLAY_DOMAIN_DSI0;
        rc = transact(PWR_FE0, 3, 8, fe0);
    }
    if (!rc) *proven_domains |= TGL_DISPLAY_DOMAIN_FE0;
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    __asm__ volatile("msr daif, %0; isb" :: "r"(daif) : "memory");
#endif
    return rc;
}
