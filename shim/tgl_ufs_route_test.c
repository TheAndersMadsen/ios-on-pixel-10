/* Host test of the UFS route: real engines, fake controller with separate CPU and device memory, so a missing clean
 * or invalidate fails. Replies are real bytes from research/ufs-read-r2/run/decoded.json wherever the phone's record
 * kept them (generated out/ufs_replay.h); what is synthetic is labelled there. Driven by test_ufs_route.py.
 * argv: scenario out.record out.linkrecord. Prints "R ..." and any "V ..." violation; a violation exits nonzero. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "tgl_ufs_link.h"
#include "tgl_ufs_host.h"
#include "tgl_ufs_handoff.h"
#include "ufs_replay.h"

#define TX_DOUT 4u
#define BUS UINT64_C(0x80a74000)
static uint8_t cpu[TGL_UFSH_ARENA_BYTES], dram[TGL_UFSH_ARENA_BYTES], rec[TGL_UFSH_RECORD_BYTES], linkrec[256];
static const char *sc;
static int bad;
static int is(const char *n) { return !strcmp(sc, n); }
static void V(const char *f, ...)
{
    va_list a; va_start(a, f); printf("V "); vprintf(f, a); printf("\n"); va_end(a); bad = 1;
}
/* ---- controller, seeded with the phone's values at ufs-link-r2 pass B ---- */
static uint32_t reg[0x400 / 4], hce = 3, top200, ahit;
static uint64_t clk = 33000000;
static unsigned linked, wire, hc_writes_before_link, doorbells;
static struct { uint32_t param, dmux, tx; } pad[3] = {
    { 0x1100, 1, 8 }, { 0x1100, 0, 0xc }, { 0x1001, 2, 0 } /* reset, power, refclk */
};
static unsigned clocks, refclk_before_reset, reset_was_low, power_was_on;
static uint64_t refclk_t;
/* The event trace the test compares with the shipped order. */
#define TRACE_MAX 512
static char trace[TRACE_MAX][48];
static unsigned ntrace;
static void T(const char *f, ...)
{
    va_list a; va_start(a, f);
    if (ntrace < TRACE_MAX) vsnprintf(trace[ntrace++], 48, f, a);
    va_end(a);
}
static uint32_t device_rx(unsigned which) { return (pad[which].tx >> 2) & 1u; }
int tgl_ufs_port_now(uint64_t *t) { *t = clk++; return 0; }
int tgl_ufs_port_delay(uint32_t a, uint32_t b) { (void)b; clk += a; return 0; }
int tgl_ufs_port_psm(unsigned w_, uint32_t *v) { (void)w_; *v = is("psm_off") ? 0 : 0x10; return 0; }
int tgl_ufs_port_pad_rd(unsigned w_, uint32_t o, uint32_t *v)
{
    if (w_ > 2) { V("pad %u", w_); return -1; }
    *v = o == 0 ? pad[w_].param : o == 4 ? pad[w_].dmux : o == 8 ? pad[w_].tx : device_rx(w_);
    return 0;
}
#if TGL_UFS_PWM_FALLBACK
static unsigned relinking, relinks, verify_at;
#endif
int tgl_ufs_port_pad_wr(unsigned w_, uint32_t o, uint32_t v)
{
#if TGL_UFS_PWM_FALLBACK
    if (linked && !relinking) V("pad write after link");
    if (relinking && w_ != 0) V("relink wrote pad %u", w_);
    if (relinking && o == 8 && !(v & TX_DOUT)) reset_was_low = 2;
#else
    if (linked) V("pad write after link");
#endif
    T("PAD %u %x %x", w_, o, v);
    if (o == 0) pad[w_].param = v;
    else if (o == 4) pad[w_].dmux = v;
    else if (o == 8) {
        /* Phone: the refclk latch reads 0 after the OE write. */
        if (w_ != 2) pad[w_].tx = v;
    } else V("pad write %x", o);
    if (w_ == 0 && o == 8 && (v & TX_DOUT)) {
        /* reset high: everything before it has to have happened, with the source's waits */
#if TGL_UFS_PWM_FALLBACK
        if (relinking && reset_was_low != 2) V("relink: reset never went low");
#endif
        reset_was_low = 1; power_was_on = pad[1].dmux == 1 && (pad[1].tx & TX_DOUT) && (clocks & 1);
        refclk_before_reset = (clocks & 1) && clk - refclk_t >= 300;
    }
    return 0;
}
int tgl_ufs_port_clk_on(uint32_t c, uint64_t *a0, uint64_t *a1)
{
    T("SMC %u", c);
    if (c != 3 && c != 16) V("clock %u", c);
    if (c == 3) { clocks |= 1; refclk_t = clk; }
    if (c == 16) clocks |= 2;
    *a0 = 0; *a1 = 0;
    return 0;
}
int tgl_ufs_port_top_wr(uint32_t o, uint32_t v) { T("TOP %x %x", o, v); if (o == 0x200) top200 = v; else V("top %x", o); return 0; }
#if TGL_UFS_POWER_MODE
/* The change as ufshcd_uic_pwr_ctrl sees it. Values the phone has never reported are this model's, not measurements. */
static unsigned hs, upmcrs, pmc_seen, peer_tact = 7, peer_sets;
static uint32_t set_attr[0x10000];
static int pmc(uint32_t mode)
{
    static const struct { uint16_t a; uint32_t v; } need[] = { {0x15d4,1},{0x1583,4},{0x1580,2},{0x1584,1},{0x1568,4},{0x1560,2},{0x1569,1},{0x156a,2},
        {0x15b0,8191},{0x15b1,65535},{0x15b2,32767},{0x15b3,8191},{0x15b4,65535},{0x15b5,32767},{0xd041,8191},{0xd042,65535},{0xd043,32767} };
    pmc_seen++;
    if (is("pmc_refused")) return 1;
#if TGL_UFS_PWM_FALLBACK
    if (is("relink_fail") || is("fb_crc")) return 1;
#endif
    if (is("pmc_no_upms")) return 0;
    if (is("pmc_link_lost")) { reg[0x20 / 4] |= 0x80; return 0; }
    if (is("pmc_upmcrs_bad")) { upmcrs = 5; reg[0x20 / 4] |= 0x10; return 0; }
    for (unsigned i = 0; i < sizeof need / sizeof need[0]; i++)
        if (set_attr[need[i].a] != need[i].v) { V("PMC with attr %x = %u, want %u", need[i].a, set_attr[need[i].a], need[i].v); return 1; }
    if (mode != 0x11) { V("PMC mode %x", mode); return 1; }
    if (reg[0x58 / 4]) V("PMC with a doorbell set");
    hs = 1; upmcrs = 1; reg[0x20 / 4] |= 0x10;
    return 0;
}
static uint32_t pm_get(uint32_t attr, uint32_t peer)
{
    if (peer) {
        if (attr == 0x1587) return is("gear3") ? 3 : 4;
        if (attr == 0x15aa) return 4;
        if (attr == 0x15a8) return is("tact_peer_low") ? 1 : peer_tact;
        return 0;
    }
    switch (attr) {
    case 0x1581: case 0x1561: return is("one_lane") ? 1 : 2;
    case 0x1587: return 5;
    case 0x15aa: return 4;
    case 0x1571: return hs ? 0x11 : 0x55;
    case 0x1583: case 0x1568: return hs ? set_attr[attr] : 1;
    case 0x1580: case 0x1560: return hs ? set_attr[attr] : 1;
    default: return set_attr[attr];
    }
}
#endif
static void uic(uint32_t op)
{
    uint32_t a1 = reg[0x94 / 4], a3 = reg[0x9c / 4], res = 0;
    T("UIC %x %x %x", op, a1 >> 16, a3);
#if TGL_UFS_POWER_MODE
    {
        uint32_t attr = a1 >> 16;
        if (op == 2) {
            if (attr == 0x1571) {
                res = (uint32_t)pmc(a3);
                reg[0x98 / 4] = res; reg[0x20 / 4] |= 0x400;
                return;
            }
            set_attr[attr] = a3;
        } else if (op == 4 && attr == 0x15a8) { peer_sets++; peer_tact = a3; }
        else if (op == 3) {
            if (is("peer_get_fail") && attr == 0x1587) res = 8;
            else reg[0x9c / 4] = pm_get(attr, 1);
            reg[0x98 / 4] = res; reg[0x20 / 4] |= 0x400;
            return;
        } else if (op == 1 && attr != 0x15a8 && attr != 0xd000 && attr != 0x41 && attr != 0xc1) {
            reg[0x9c / 4] = pm_get(attr, 0);
            reg[0x98 / 4] = 0; reg[0x20 / 4] |= 0x400;
            return;
        } else if (op == 1 && attr == 0x15a8 && pmc_seen == 0 && set_attr[0x15a8]) {
            reg[0x9c / 4] = set_attr[0x15a8];
            reg[0x98 / 4] = 0; reg[0x20 / 4] |= 0x400;
            return;
        }
    }
#endif
    if (op == 0x16) {
        if (reset_was_low && power_was_on && refclk_before_reset && (clocks & 3) == 3 && top200 == 0x101 && reg[0xf8 / 4] == 0xc8) linked = 1;
        else res = 1;
    } else if (op == 1) {
        uint32_t attr = a1 >> 16;
        /* Same as the phone: 0x15a8 reads 2 after link. FSM values from ufs-link-r2 pass B. */
        reg[0x9c / 4] = attr == 0x15a8 ? 2 : attr == 0xd000 ? (linked ? 0 : 1) : attr == 0x41 ? (linked ? 2 : 1) : attr == 0xc1 ? (linked ? 2 : 7) : 0;
    }
    reg[0x98 / 4] = res;
    reg[0x20 / 4] |= 0x400;
}
int tgl_ufs_port_hc_rd(uint32_t o, uint32_t *v)
{
    if (o == 0x00) { *v = REPLAY_CAP; return 0; }
    if (o == 0x34) { *v = hce; return 0; }
#if TGL_UFS_POWER_MODE
    if (o == 0x30 && linked) { *v = 0xf | upmcrs << 8; return 0; }
#endif
    if (o == 0x30) { *v = linked ? 0xf : (hce & 1 ? 0x108 : 0); return 0; }
    *v = reg[o / 4];
    return 0;
}
int tgl_ufs_port_hc_wr(uint32_t o, uint32_t v)
{
    if (!linked) hc_writes_before_link++;
    if (o == 0x20) { reg[o / 4] &= ~v; return 0; }
    if (o == 0x34) { T("HCE %x", v); hce = v; if (!v) linked = 0; return 0; }
    if (o == 0xf8) { T("HCLKDIV %x", v); reg[o / 4] = v; return 0; }
    if (o == 0x90) { uic(v); return 0; }
    reg[o / 4] = v;
    return 0;
}
int tgl_ufs_port_publish(const uint8_t r[256]) { memcpy(linkrec, r, 256); return 0; }
void tgl_ufs_port_invalidate(void) {}
uint32_t tgl_ufs_port_isr(void) { return 0; }

/* ---- device ---- */
static unsigned real_at, read_at, lu_ua[8], wlun_tur, hang_reads;
static const uint8_t *block_for(unsigned lun, uint32_t lba)
{
    for (unsigned i = 0; i < REPLAY_NBLOCKS; i++)
        if (replay_blocks[i].lun == lun && replay_blocks[i].lba == lba)
            return is("strict_headers") ? replay_blocks[i].real : replay_blocks[i].fixed;
    return 0;
}
static void put_le32(uint8_t *b, uint32_t v) { for (int i = 0; i < 4; i++) b[i] = (uint8_t)(v >> (8 * i)); }
static void device(void)
{
    uint8_t *u = dram, *q = dram + 0x800, *r = dram + 0xa00, *d = dram + 0x1000;
    uint32_t ocs = 0;
    wire++; doorbells++;
    if (!linked) V("doorbell before link");
    if (reg[0x50 / 4] != (uint32_t)BUS || !(reg[0x60 / 4] & 1)) V("doorbell before list running");
    if (u[8] != 0x0f) V("stale OCS at doorbell");
    memset(r, 0, 512);
    /* A recorded frame must be sent exactly, in the recorded order. Others must be the phone's unlogged kinds. */
    if (real_at < REPLAY_NCMDS && !memcmp(q, replay_cmds[real_at].req, 32)) {
        memcpy(r, replay_cmds[real_at].rsp, replay_cmds[real_at].rsp_len);
        real_at++;
    } else if (q[0] == 1 && (q[16] == 0 || q[16] == 0x25 || q[16] == 0x28) && q[2] < 8) {
        memcpy(r, REPLAY_GOOD, 32); r[2] = q[2];
    } else {
        char h[65]; for (int i = 0; i < 32; i++) sprintf(h + i * 2, "%02x", q[i]);
        V("frame not on the phone's record: %s (next recorded %u)", h, real_at);
        r[0] = 0x21; r[2] = q[2];
    }
    if (q[0] == 1 && q[16] == 0x25) {
        for (unsigned i = 0; i < REPLAY_NLUS; i++) if (replay_lus[i].lun == q[2]) {
            uint32_t m = replay_lus[i].max_lba, b = replay_lus[i].block_bytes;
            uint8_t c8[8] = { (uint8_t)(m >> 24), (uint8_t)(m >> 16), (uint8_t)(m >> 8), (uint8_t)m, (uint8_t)(b >> 24), (uint8_t)(b >> 16), (uint8_t)(b >> 8), (uint8_t)b };
            memcpy(d, c8, 8);
        }
    } else if (q[0] == 1 && q[16] == 0xa0) {
        memcpy(d, REPLAY_RL, sizeof REPLAY_RL);
    } else if (q[0] == 1 && q[16] == 0x28) {
        uint32_t lba = (uint32_t)q[18] << 24 | (uint32_t)q[19] << 16 | (uint32_t)q[20] << 8 | q[21];
#if TGL_UFS_POWER_MODE
        /* After the change: the phone's TARGET reads again, in order. Before it: PWM only. */
#if TGL_UFS_PWM_FALLBACK
        if (relinks ? hs : hs != (read_at >= REPLAY_NREADS)) V("READ %u in the wrong mode, hs=%u", read_at, hs);
#else
        if (hs != (read_at >= REPLAY_NREADS)) V("READ %u in the wrong mode, hs=%u", read_at, hs);
#endif
        if (read_at >= REPLAY_NREADS) {
#if TGL_UFS_PWM_FALLBACK
            unsigned at = REPLAY_NREADS - 12u + verify_at++;
#else
            unsigned at = REPLAY_NREADS - 12u + (read_at - REPLAY_NREADS);
#endif
            if (at >= REPLAY_NREADS || replay_reads[at].lun != q[2] || replay_reads[at].lba != lba) V("HS READ %u: LU %u LBA %u", read_at, q[2], lba);
            read_at++;
            if (is("hs_timeout") && read_at == REPLAY_NREADS + 3u) { hang_reads = 1; return; }
            const uint8_t *hb = block_for(q[2], lba);
            if (hb) memcpy(d, hb, 4096); else V("no block for LU %u LBA %u", q[2], lba);
            if (is("hs_crc") && read_at == REPLAY_NREADS + 5u) d[100] ^= 1;
#if TGL_UFS_PWM_FALLBACK
            if (is("fb_crc") && relinks && verify_at == 3u) d[100] ^= 1;
#endif
            put_le32(u + 8, ocs);
            return;
        }
#endif
        if (!is("strict_headers")) {
            if (read_at >= REPLAY_NREADS || replay_reads[read_at].lun != q[2] || replay_reads[read_at].lba != lba)
                V("READ %u out of the phone's order: LU %u LBA %u", read_at, q[2], lba);
        }
        read_at++;
        if (is("read_timeout") && read_at == 3) { hang_reads = 1; return; }
        if (is("read_short") && read_at == 2) { r[1] = 0x20; r[14] = 0x10; }
        const uint8_t *s = block_for(q[2], lba);
        if (s) memcpy(d, s, 4096); else V("no block for LU %u LBA %u", q[2], lba);
        if (is("bad_hdr_crc") && lba == 1) d[60] ^= 1;
    }
    put_le32(u + 8, ocs);
}
static int h_rd(void *c, uint32_t o, uint32_t *v)
{
    (void)c;
    if (o == 0x18) { *v = ahit; return 0; }
    if (o == 0x08) { *v = 0x400; return 0; }
    return tgl_ufs_port_hc_rd(o, v);
}
static int h_wr(void *c, uint32_t o, uint32_t v)
{
    (void)c;
    if (o == 0x58) {
        reg[o / 4] = v;
        if (v) { device(); if (!hang_reads) reg[o / 4] = 0; }
        return 0;
    }
    if (o == 0x5c) { if (!(v & 1)) reg[0x58 / 4] = 0; return 0; }
    if (o == 0x20) { reg[o / 4] &= ~v; return 0; }
    return tgl_ufs_port_hc_wr(o, v);
}
static int sm_rd(void *c, uint32_t o, uint32_t *v) { (void)c; *v = o == 0x44 ? (is("smmu_drift") && read_at >= 3 ? 0x2e0f : 0x2e1f) : 0; return 0; }
static int p_now(void *c, uint64_t *t) { (void)c; return tgl_ufs_port_now(t); }
static int p_delay(void *c, uint32_t a, uint32_t b) { (void)c; return tgl_ufs_port_delay(a, b); }
static int p_sync(void *c, unsigned dev)
{
    (void)c;
    if (dev) memcpy(dram, cpu, sizeof dram); else memcpy(cpu, dram, sizeof cpu);
    return 0;
}
static int p_rec(void *c, uint32_t off, const uint8_t *b, uint32_t n)
{
    (void)c;
    if (off + n > sizeof rec) { V("record overflow"); return -1; }
    memcpy(rec + off, b, n);
    return 0;
}
/* The handoff's ports: stop-only writes. */
static int f_rd(void *c, uint32_t o, uint32_t *v) { return h_rd(c, o, v); }
static int f_wr(void *c, uint32_t o, uint32_t v) { (void)c; if ((o != 0x60 && o != 0x80) || v) { V("handoff write %x %x", o, v); return -1; } reg[o / 4] = v; return 0; }
static int f_close(void *c) { (void)c; return 0; }
static void write_file(const char *p, const void *b, size_t n)
{
    FILE *f = fopen(p, "wb");
    if (!f) exit(3);
    fwrite(b, 1, n, f);
    fclose(f);
}
#if TGL_UFS_PWM_FALLBACK || TGL_UFS_PHY_CHECK
static int p_top(void *c, uint32_t o, uint32_t *v)
{
    (void)c;
    if (o != 0x100) { V("TOP read %x", o); return -1; }
    T("TOPRD %x", o);
    *v = is("phy_init_clear") ? 0x204c24 & ~0x300000u : 0x23c4c24;
    return is("top_fault") ? -2 : 0;
}
static int p_pad(void *c, unsigned w_, uint32_t o, uint32_t *v) { (void)c; return tgl_ufs_port_pad_rd(w_, o, v); }
static unsigned marks;
static void p_mark(void *c, unsigned id, unsigned state, int32_t val) { (void)c; T("MARK %u %u", id, state); (void)val; marks++; }
static int p_relink(void *c)
{
    (void)c;
    verify_at = 0; real_at = 0; hang_reads = 0; hs = 0; upmcrs = 0; relinks++;
    if (is("relink_fail")) { top200 = 0; return -1; }
    if (reg[0x60 / 4] & 1) V("relink with the list running");
    relinking = 1;
    int r = tgl_ufs_link_relink();
    relinking = 0;
    return r;
}
#endif
int main(int ac, char **av)
{
    if (ac < 4) return 4;
    sc = av[1];
    static struct tgl_ufs_link_request lq;
    lq.enable = 1; lq.epoch = 0x202611012500ULL; lq.nonce = 0x2df5ab6e1c7d9dbeULL; lq.budget_us = 20000000;
    lq.facts.hc = 0x3c400000; lq.facts.hc_bytes = 0x1000; lq.facts.top = 0x3c410000; lq.facts.top_bytes = 0x504; lq.facts.named = 1;
    if (is("pg")) lq.facts.ah8_pg = 1;
    if (is("decouple")) lq.facts.decouple_ufs_en = 1;
    if (is("bad_top")) lq.facts.top_bytes = 0x514;
    reg[0x20 / 4] = 0x4; reg[0x24 / 4] = 0xe0000000; /* phone: is_before, ie_before */
    reg[0xc0 / 4] = REPLAY_BUSTHRTL;
    if (is("ahit")) ahit = 0x1001;
    if (is("stale_doorbell")) reg[0x58 / 4] = 1;
    int lrc = tgl_ufs_link_run(&lq);
    unsigned hc_before = hc_writes_before_link;
    printf("L rc=%d attempts=%u up=%u smc=%x again=%d\n", lrc, linkrec[168], linkrec[170], clocks, tgl_ufs_link_run(&lq));
    printf("H %u\n", hc_before);
    static struct tgl_ufsh_ports p = { 0, h_rd, h_wr, sm_rd, p_now, p_delay, p_sync, p_rec };
#if TGL_UFS_PWM_FALLBACK || TGL_UFS_PHY_CHECK
    p.top_rd = p_top; p.pad_rd = p_pad; p.relink = p_relink; p.mark = p_mark;
#endif
    static struct tgl_ufsh_request q;
    static struct tgl_ufsh_result o;
    q.enable = 1; q.epoch = lq.epoch; memcpy(q.nonce, "\xbd\xf5\x82\xb4\x5d\x69\x80\x0a\xf5\x1a\x51\x93\x54\x95\x83\x06", 16);
    q.arena = cpu; q.arena_bus = BUS; q.budget_us = 10000000;
    q.sctlr = 0x30c50a90; q.currentel = 8; q.ctr = 0x94448004;
    memset(rec, 0x5a, sizeof rec);
    int rc = tgl_ufsh_run(&q, &p, &o);
    printf("R rc=%d phase=%u dma=%u quar=%u stopped=%u flag_reads=%u tur=%u ua=%u list=%u luns=%u reads=%u wire=%u found=%u tlun=%u first=%u last=%u real_at=%u/%u read_at=%u\n",
        rc, o.phase, o.dma_started, o.quarantined, o.lists_stopped, o.flag_reads, o.tur_attempts, o.ua_seen, o.list_len, o.lun_count, o.read_blocks, wire, o.target_found, o.target_lun, o.target_first, o.target_last, real_at, REPLAY_NCMDS, read_at);
    for (unsigned i = 0; i < o.lun_count; i++) printf("Z %u rc=%d gpt=%u crc=%u used=%u max=%u\n", o.lu[i].lun, o.lu[i].rc, o.lu[i].gpt_ok, o.lu[i].entries_crc_ok, o.lu[i].used, o.lu[i].max_lba);
    {
        static struct ufsh_ports fp = { 0, f_rd, f_wr, f_close };
        static struct ufsh_evidence e;
        static struct ufsh_record r;
        if (is("fatal_is")) reg[0x20 / 4] |= 0x800;
        e.dma_opened = o.dma_started || o.phase >= TGL_UFSH_P_LISTS;
        e.read_match = o.rc == TGL_UFSH_OK && o.target_found == 1u && !o.target_dups && o.read_blocks;
        e.quarantined = o.quarantined; e.retained = e.dma_opened && !o.lists_stopped;
        e.aux_clk_held = o.rc == TGL_UFSH_OK; e.lun = o.target_lun;
        int out = ufsh_finalize(&e, &fp, &r);
        printf("F outcome=%d step=%u ahit=%x hcs=%x\n", out, r.step, r.ahit, r.hcs);
    }
#if TGL_UFS_POWER_MODE
    printf("P state=%u hs=%u pmc=%u peer_sets=%u peer_tact=%u\n", o.pmc_state, hs, pmc_seen, peer_sets, peer_tact);
#if TGL_UFS_PWM_FALLBACK
    printf("B relinks=%u first=%d marks=%u\n", relinks, o.pmc_first_rc, marks);
#endif
#endif
    for (unsigned i = 0; i < ntrace; i++) printf("T %s\n", trace[i]);
    write_file(av[2], rec, sizeof rec);
    write_file(av[3], linkrec, sizeof linkrec);
    return bad ? 2 : 0;
}
