/* SYNTHETIC HOST ONLY: a register array, no device. */
#include "tgl_ufs_handoff.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint32_t reg[0x100];
static unsigned reads, writes, closes, ops, fail_at, close_rc, close_after_write_count;
static uint32_t order[8]; static unsigned sticky_rsr, bell_rises;
static int fails(void) { return fail_at && ++ops == fail_at; }
static int r32(void *c, uint32_t o, uint32_t *v) { (void)c; if (fails()) return -1; reads++; *v = reg[o/4]; return 0; }
static int w32(void *c, uint32_t o, uint32_t v) {
    (void)c; if (fails()) return -1;
    assert(o == UFSH_UTRLRSR || o == UFSH_UTMRLRSR); assert(v == 0);
    order[writes++] = o;
    if (!sticky_rsr) reg[o/4] = v;
    if (bell_rises && o == UFSH_UTRLRSR) reg[UFSH_UTRLDBR/4] = 1;
    return 0;
}
static int cl(void *c) { (void)c; if (fails()) return -1; closes++; close_after_write_count = writes; return close_rc; }
static struct ufsh_ports P = {0, r32, w32, cl};
static struct ufsh_evidence good(void) { struct ufsh_evidence e = {1,1,0,0,0,1,0}; return e; }
static void reset(void) {
    memset(reg, 0, sizeof reg); reg[UFSH_UTRLRSR/4] = 1; reg[UFSH_UTMRLRSR/4] = 1; reg[UFSH_HCS/4] = 0x10b;
    reads = writes = closes = ops = fail_at = close_rc = close_after_write_count = sticky_rsr = bell_rises = 0;
}
static unsigned n;
#define CASE(name, setup, want, wr, cls) do { reset(); struct ufsh_evidence e = good(); struct ufsh_record r; setup; \
    int o = ufsh_finalize(&e, &P, &r); if (o != (want) || writes != (wr) || closes != (cls)) { \
    printf("FAIL %s: outcome %d writes %u closes %u\n", name, o, writes, closes); return 1; } n++; } while (0)
int main(void) {
    CASE("clean read match", , UFSH_LIVE, 2, 1);
    assert(order[0] == UFSH_UTMRLRSR && order[1] == UFSH_UTRLRSR && close_after_write_count == 2);
    assert(reg[UFSH_UTRLRSR/4] == 0 && reg[UFSH_UTMRLRSR/4] == 0);
    CASE("no dma: no mmio", e.dma_opened = 0, UFSH_NO_DMA, 0, 0); assert(!reads);
    CASE("no dma, fault: no mmio", e.dma_opened = 0; e.faulted = 1, UFSH_NO_DMA, 0, 0); assert(!reads);
    CASE("fault with dma: no mmio", e.faulted = 1, UFSH_HALT, 0, 0); assert(!reads);
    CASE("quarantined: no mmio", e.quarantined = 1, UFSH_HALT, 0, 0); assert(!reads);
    CASE("retained: no mmio", e.retained = 1, UFSH_HALT, 0, 0); assert(!reads);
    CASE("transfer doorbell busy", reg[UFSH_UTRLDBR/4] = 1, UFSH_HALT, 0, 0);
    CASE("task doorbell busy", reg[UFSH_UTMRLDBR/4] = 1, UFSH_HALT, 0, 0);
    CASE("run bit stuck", sticky_rsr = 1, UFSH_HALT, 2, 0);
    CASE("doorbell rises after stop", bell_rises = 1, UFSH_HALT, 2, 0);
    CASE("close refuses", close_rc = -5, UFSH_HALT, 2, 1);
    CASE("no match, clean", e.read_match = 0, UFSH_DOWN, 2, 1);
    CASE("AHIT set", reg[UFSH_AHIT/4] = 0x1001, UFSH_DOWN, 2, 1);
    CASE("device gone", reg[UFSH_HCS/4] = 0x108, UFSH_DOWN, 2, 1);
    CASE("list not ready", reg[UFSH_HCS/4] = 0x109, UFSH_DOWN, 2, 1);
    CASE("fatal IS: controller", reg[UFSH_IS/4] = 1u << 16, UFSH_DOWN, 2, 1);
    CASE("fatal IS: device", reg[UFSH_IS/4] = 1u << 11, UFSH_DOWN, 2, 1);
    CASE("benign IS", reg[UFSH_IS/4] = 0x400, UFSH_LIVE, 2, 1);
    CASE("aux not held", e.aux_clk_held = 0, UFSH_DOWN, 2, 1);
    CASE("lun out of range", e.lun = 8, UFSH_DOWN, 2, 1);
    CASE("lun 3 ok", e.lun = 3, UFSH_LIVE, 2, 1);
    /* A failed access at every position. Before the arena closes it must halt. */
    for (unsigned at = 1; at <= 13; at++) {
        reset(); fail_at = at; struct ufsh_evidence e = good(); struct ufsh_record r;
        int o = ufsh_finalize(&e, &P, &r);
        if (at <= 9) { if (o != UFSH_HALT) { printf("FAIL access %u: %d\n", at, o); return 1; } }
        else if (at <= 12) { if (o != UFSH_DOWN || !r.arena_closed) { printf("FAIL late %u: %d\n", at, o); return 1; } }
        else assert(o == UFSH_LIVE);
        n++;
    }
    { struct ufsh_record r; struct ufsh_evidence e = good(); reset();
      assert(ufsh_finalize(0, &P, &r) == UFSH_HALT && ufsh_finalize(&e, 0, &r) == UFSH_HALT && ufsh_finalize(&e, &P, 0) == UFSH_HALT);
      struct ufsh_ports q = P; q.arena_close = 0; assert(ufsh_finalize(&e, &q, &r) == UFSH_HALT); assert(!reads); n += 4; }
    static const struct { const char *c; unsigned lun; int ok; } C[] = {
        {"rd=ufsroot0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=userdata_exp.ai blazer_ufs_lun=0", 0, 1},
        {"debug=0x8 rd=md0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x", 0, 1},
        {"rd=ufsroot0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x blazer_ufs_lun=3", 3, 1},
        {"rd=ufsroot0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x blazer_ufs_lun=0", 3, 0},
        {"rd=ufsroot0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x", 3, 0},
        {"rd=ufsroot0 blazer_ufs=1 blazer_ufs_live=1 blazer_ufs_root=x", 0, 0},
        {"rd=ufsroot0 blazer_ufs=2 blazer_ufs_root=x", 0, 0},
        {"rd=ufsroot0 blazer_ufs=2 blazer_ufs_live=1", 0, 0},
        {"rd=ufsroot0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=", 0, 0},
        {"rd=sd0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x", 0, 0},
        {"blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x", 0, 0},
        {"rd=md01 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x", 0, 0},
        {"rd=ufsroot0 blazer_ufs=22 blazer_ufs_live=1 blazer_ufs_root=x", 0, 0},
        {"xrd=ufsroot0 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=x", 0, 0},
        {"", 0, 0},
    };
    for (unsigned i = 0; i < sizeof C / sizeof *C; i++, n++)
        if (ufsh_cmdline_ok(C[i].c, C[i].lun) != C[i].ok) { printf("FAIL cmdline %u: %s\n", i, C[i].c); return 1; }
    printf("PASS %u cases\n", n);
    return 0;
}
