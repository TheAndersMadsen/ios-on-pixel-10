/* SPDX-License-Identifier: MIT
 * Target binding of the UFS route. The allowlists below are the safety boundary: this file cannot reach PA outside
 * these HC words, TOP+0x200, three PSM words, three pads, the inf_smmu read window and the two record areas. */
#include "tgl_ufs_route.h"
#include "tgl_ufs_host.h"
#include "tgl_ufs_link.h"
#include "tgl_ufs_handoff.h"
#include "tgl_ufs.h"
#include "tgl_stamp.h"
#include "tgl_cpm.h"
#include "guard.h"
#include "probe.h"
#if !defined(__aarch64__)
#error "tgl_ufs_route.c is AArch64 target code"
#endif
extern int tgl_stamp_boot_us(uint64_t *);

#ifndef TGL_UFS_EPOCH
#error "TGL_UFS_EPOCH comes from build.sh"
#endif
#ifndef TGL_UFS_RECORD_NONCE
#error "TGL_UFS_RECORD_NONCE comes from build.sh"
#endif

#define HC_PA UINT64_C(0x3c400000)   /* NOTES.md; the FDT must agree, tgl_ufs_link.c */
#define TOP_PA UINT64_C(0x3c410000)
#define SMMU_PA UINT64_C(0x35100000) /* inf_smmu, read at ufs-observe-r2 */
/* In the ramoops zone XNU may not claim. Same PAs as ufs-read-r2, so its decoder applies. */
#define LINK_RECORD_PA UINT64_C(0x95427c00)
#define READ_RECORD_PA UINT64_C(0x9542a000)
_Static_assert(READ_RECORD_PA + TGL_UFSH_RECORD_BYTES <= UINT64_C(0x95430000), "record stays below the stamps");
#define BARRIER() __asm__ volatile("dsb sy" ::: "memory")

/* ---- link ports ---- */
static uint64_t last_us;
int tgl_ufs_port_now(uint64_t *t)
{
    uint64_t n;
    if (!t || tgl_stamp_boot_us(&n) || n < last_us) return -1;
    last_us = n; *t = n;
    return 0;
}
int tgl_ufs_port_delay(uint32_t lo, uint32_t hi)
{
    uint64_t a, b;
    (void)hi;
    if (lo > 2000000u || tgl_ufs_port_now(&a)) return -1;
    for (uint64_t i = 0; i < UINT64_C(100000000); ++i) {
        if (tgl_ufs_port_now(&b)) return -1;
        if (b - a >= lo) return 0;
    }
    return -1;
}
static int link_hc_read_ok(uint32_t o)
{
    switch (o) {
    case 0x00: case 0x20: case 0x24: case 0x30: case 0x34: case 0x58: case 0x78:
    case 0x90: case 0x94: case 0x98: case 0x9c: return 1;
    default: return 0;
    }
}
static int link_hc_write_ok(uint32_t o)
{
    switch (o) {
    case 0x20: case 0x24: case 0x34: case 0x90: case 0x94: case 0x98: case 0x9c: case 0xf8: return 1;
    default: return 0;
    }
}
int tgl_ufs_port_hc_rd(uint32_t o, uint32_t *v)
{
    if (!v || !link_hc_read_ok(o)) return -1;
    return probe_read32((uintptr_t)(HC_PA + o), v) ? 0 : -2;
}
int tgl_ufs_port_hc_wr(uint32_t o, uint32_t v)
{
    if (!link_hc_write_ok(o)) return -1;
    if (!probe_write32((uintptr_t)(HC_PA + o), v)) return -2;
    BARRIER();
    return 0;
}
int tgl_ufs_port_top_wr(uint32_t o, uint32_t v)
{
    if (o != 0x200u) return -1;
    if (!probe_write32((uintptr_t)(TOP_PA + o), v)) return -2;
    BARRIER();
    return 0;
}
int tgl_ufs_port_psm(unsigned which, uint32_t *v)
{
    static const uint32_t pa[3] = { 0x3c00b108u, 0x3c00d210u, 0x3c00e108u };
    if (which > 2u || !v) return -1;
    return probe_read32((uintptr_t)pa[which], v) ? 0 : -2;
}
/* Exactly the pad words ufs-observe-r2 read on the phone. Each access first attests its controller's power domain,
 * ON under the N879 mask: an unpowered CSR would fault. */
static int pad_addr(unsigned which, uint32_t off, uintptr_t *a)
{
    static const uint32_t pad[3] = { 0x3c590000u, 0x3c598000u, 0x3c569000u };
    uint32_t v;
    if (which > 2u || (off != 0u && off != 4u && off != 8u && !(off == 0x10u && which < 2u))) return -1;
    if (!probe_read32(which == 2u ? (uintptr_t)0x3c00d210u : (uintptr_t)0x3c00b108u, &v) || (v & 0x1fu) != 0x10u) return -3;
    *a = (uintptr_t)(pad[which] + off);
    return 0;
}
int tgl_ufs_port_pad_rd(unsigned which, uint32_t off, uint32_t *v)
{
    uintptr_t a;
    int rc = v ? pad_addr(which, off, &a) : -1;
    if (rc) return rc;
    return probe_read32(a, v) ? 0 : -2;
}
int tgl_ufs_port_pad_wr(unsigned which, uint32_t off, uint32_t v)
{
    uintptr_t a;
    int rc = off == 0x10u ? -1 : pad_addr(which, off, &a);
    if (rc) return rc;
    if (!probe_write32(a, v)) return -2;
    BARRIER();
    return 0;
}
int tgl_ufs_port_clk_on(uint32_t clock, uint64_t *a0, uint64_t *a1)
{
    static unsigned used;
    struct tgl_cpm_ufs_clock_reply r;
    unsigned bit = clock == 3u ? 1u : clock == 16u ? 2u : 0u;
    if (!a0 || !a1 || !bit || (used & bit)) return -1;
    used |= bit; /* pre-call intent survives a section unwind */
    int rc = tgl_cpm_ufs_clock_enable(clock, &r);
    /* The wrapper can reject an interrupted prior call; do not invent raw returns. */
    if (r.a0 == UINT64_MAX && r.a1 == UINT64_MAX) return -1;
    *a0 = r.a0; *a1 = r.a1;
    return rc ? -1 : 0;
}
void tgl_ufs_port_invalidate(void)
{
    *(volatile uint32_t *)(uintptr_t)(LINK_RECORD_PA + 252) = 0;
    BARRIER();
}
uint32_t tgl_ufs_port_isr(void)
{
    uint64_t v;
    __asm__ volatile("mrs %0, isr_el1" : "=r"(v));
    return (uint32_t)v;
}
int tgl_ufs_port_publish(const uint8_t b[TGL_UFS_LINK_RECORD_BYTES])
{
    volatile uint8_t *p = (volatile uint8_t *)(uintptr_t)LINK_RECORD_PA;
    *(volatile uint32_t *)(void *)(p + 252) = 0;
    BARRIER();
    for (unsigned i = 0; i < 252; ++i) p[i] = b[i];
    BARRIER();
    *(volatile uint32_t *)(void *)(p + 252) = (uint32_t)b[252] | (uint32_t)b[253] << 8 | (uint32_t)b[254] << 16 | (uint32_t)b[255] << 24;
    BARRIER();
    return 0;
}
unsigned tgl_ufs_route_link_guarded(const struct tgl_ufs_fdt_regions *f)
{
    /* Runtime stores: no ABS64 relocations in a static initializer. */
    static struct tgl_ufs_link_request q;
    q.enable = 1; q.epoch = TGL_UFS_EPOCH; q.nonce = TGL_STAMP_NONCE; q.budget_us = 20000000;
    if (f) {
        q.facts.hc = f->hc; q.facts.hc_bytes = f->hc_bytes; q.facts.top = f->top; q.facts.top_bytes = f->top_bytes;
        q.facts.named = f->named; q.facts.ah8_pg = f->ah8_pg; q.facts.swh8_pg = f->swh8_pg;
        q.facts.decouple_ufs_en = f->decouple_ufs_en;
    }
    tgl_guard_arm();
    if (!tgl_guard_esr) (void)tgl_ufs_link_run(&q); /* unwind resumes here with ESR recorded */
    tgl_guard_armed = 0;
    return tgl_guard_esr != 0;
}

/* ---- host ports ---- */
static uint8_t arena[TGL_UFSH_ARENA_BYTES] __attribute__((aligned(TGL_UFSH_ARENA_ALIGN)));
static struct tgl_ufsh_ports ports;
static struct tgl_ufsh_request req;
static struct tgl_ufsh_result res;

static void civac(uint64_t va, uint64_t bytes)
{
    uint64_t ctr, line, a;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
    line = UINT64_C(4) << ((ctr >> 16) & 0xfu);
    a = va & ~(line - 1u);
    BARRIER();
    for (; a < va + bytes; a += line) __asm__ volatile("dc civac, %0" :: "r"(a) : "memory");
    BARRIER();
}
static int hc_read_ok(uint32_t o)
{
    switch (o) {
    case 0x00: case 0x08: case 0x20: case 0x24: case 0x30: case 0x34: case 0x38: case 0x3c: case 0x40:
    case 0x44: case 0x48: case 0x58: case 0x60: case 0x78: case 0x80: case 0x98: case 0x9c: case 0xc0:
    case 0x300: return 1;
    default: return 0;
    }
}
static int hc_write_ok(uint32_t o)
{
    switch (o) {
    case 0x20: case 0x24: case 0x4c: case 0x50: case 0x54: case 0x58: case 0x5c: case 0x60: case 0x70: case 0x74:
    case 0x80: case 0x90: case 0x94: case 0x98: case 0x9c: case 0xc0: return 1;
    default: return 0;
    }
}
static int hc_rd(void *c, uint32_t o, uint32_t *v)
{
    (void)c;
    if (!hc_read_ok(o)) return -1;
    return probe_read32((uintptr_t)(HC_PA + o), v) ? 0 : -2;
}
static int hc_wr(void *c, uint32_t o, uint32_t v)
{
    (void)c;
    if (!hc_write_ok(o)) return -1;
    if (!probe_write32((uintptr_t)(HC_PA + o), v)) return -2;
    BARRIER();
    return 0;
}
static int smmu_rd(void *c, uint32_t o, uint32_t *v)
{
    (void)c;
    if (o != 0x20u && o != 0x24u && o != 0x44u && o != 0x60u && o != 0x64u) return -1;
    return probe_read32((uintptr_t)(SMMU_PA + o), v) ? 0 : -2;
}
static int now_us(void *c, uint64_t *t) { (void)c; return tgl_ufs_port_now(t); }
static int delay_us(void *c, uint32_t lo, uint32_t hi) { (void)c; return tgl_ufs_port_delay(lo, hi); }
static int sync_(void *c, unsigned for_device)
{
    (void)c; (void)for_device;
    civac((uint64_t)(uintptr_t)arena, TGL_UFSH_ARENA_BYTES);
    return 0;
}
static int rec_write(void *c, uint32_t off, const uint8_t *b, uint32_t n)
{
    volatile uint8_t *p = (volatile uint8_t *)(uintptr_t)READ_RECORD_PA;
    (void)c;
    if (off >= TGL_UFSH_RECORD_BYTES || n > TGL_UFSH_RECORD_BYTES - off) return -1;
    for (uint32_t i = 0; i < n; i++) p[off + i] = b[i];
    BARRIER();
    return 0;
}
#if TGL_UFS_PHY_CHECK || TGL_UFS_PWM_FALLBACK
#include "tgl_all.h"
static int top_rd(void *c, uint32_t o, uint32_t *v)
{
    (void)c;
    if (o != 0x100u || !v) return -1;
    return probe_read32((uintptr_t)(TOP_PA + o), v) ? 0 : -2; /* the word ufs-observe-r2 read on the phone */
}
static int pad_rd_(void *c, unsigned which, uint32_t o, uint32_t *v) { (void)c; return tgl_ufs_port_pad_rd(which, o, v); }
static int relink_(void *c) { (void)c; return tgl_ufs_link_relink(); }
static void mark_(void *c, unsigned id, unsigned state, int32_t val) { (void)c; tgl_all_mark(id, state, val); }
#endif
int tgl_ufs_route_must_park(void) { return (int)res.quarantined; }
int tgl_ufs_route_after_link(void)
{
    static const uint8_t nonce[16] = TGL_UFS_RECORD_NONCE;
    volatile struct tgl_ufsh_ports *v = &ports; /* runtime stores: no ABS64 relocations */
    uint64_t el, sctlr = 0, ctr;
    volatile int rc = TGL_UFSH_E_ARG;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
    if (((el >> 2) & 3u) == 2u) __asm__ volatile("mrs %0, sctlr_el2" : "=r"(sctlr));
    else __asm__ volatile("mrs %0, sctlr_el1" : "=r"(sctlr));
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
    v->ctx = 0; v->hc_rd = hc_rd; v->hc_wr = hc_wr; v->smmu_rd = smmu_rd; v->now_us = now_us;
    v->delay_us = delay_us; v->sync = sync_; v->rec_write = rec_write;
#if TGL_UFS_PHY_CHECK || TGL_UFS_PWM_FALLBACK
    v->top_rd = top_rd; v->pad_rd = pad_rd_; v->relink = relink_; v->mark = mark_;
#endif
    req.enable = 1; req.epoch = TGL_UFS_EPOCH;
    for (unsigned i = 0; i < 16; i++) req.nonce[i] = nonce[i];
    req.arena = arena; req.arena_bus = (uint64_t)(uintptr_t)arena; req.budget_us = UINT64_C(10000000);
    req.sctlr = (uint32_t)sctlr; req.currentel = (uint32_t)el; req.ctr = (uint32_t)ctr;
    civac(READ_RECORD_PA, TGL_UFSH_RECORD_BYTES);
    tgl_guard_esr = 0; tgl_guard_far = 0; tgl_guard_armed = 1; tgl_guard_arm();
    if (!tgl_guard_esr) rc = tgl_ufsh_run(&req, &ports, &res);
    tgl_guard_armed = 0;
    if (tgl_guard_esr || tgl_guard_far) {
        tgl_ufsh_note_fault(&ports, &res, tgl_guard_esr, tgl_guard_far);
        return TGL_UFSH_E_FAULT;
    }
    return rc;
}

/* ---- handoff ---- */
#if TGL_UFS_HANDOFF
static int h_read(void *c, uint32_t o, uint32_t *v)
{
    (void)c;
    if (o != UFSH_AHIT && !hc_read_ok(o)) return -1;
    return probe_read32((uintptr_t)(HC_PA + o), v) ? 0 : -2;
}
static int h_write(void *c, uint32_t o, uint32_t v)
{
    (void)c;
    if ((o != UFSH_UTRLRSR && o != UFSH_UTMRLRSR) || v) return -1;
    if (!probe_write32((uintptr_t)(HC_PA + o), v)) return -2;
    BARRIER();
    return 0;
}
/* The arena is image memory: once the lists are stopped and the doorbells idle, the host has no way to reach it.
 * finalize proves that before calling this. Clean it so no dirty line lands on memory XNU owns. */
static int h_close(void *c)
{
    (void)c;
    civac((uint64_t)(uintptr_t)arena, TGL_UFSH_ARENA_BYTES);
    return 0;
}
int tgl_ufs_route_handoff(unsigned link_faulted)
{
    static unsigned called;
    static struct ufsh_evidence e;
    static struct ufsh_record r;
    static struct ufsh_ports p;
    volatile struct ufsh_ports *vp = &p;
    int o = UFSH_HALT;
    if (!called++) {
        vp->ctx = 0; vp->read32 = h_read; vp->write32 = h_write; vp->arena_close = h_close;
        e.dma_opened = res.dma_started || res.phase >= TGL_UFSH_P_LISTS;
        e.read_match = res.rc == TGL_UFSH_OK && res.target_found == 1u && !res.target_dups && res.read_blocks;
        e.faulted = link_faulted || res.rc == TGL_UFSH_E_FAULT;
        e.quarantined = res.quarantined;
        e.retained = e.dma_opened && !res.lists_stopped;
        e.aux_clk_held = res.rc == TGL_UFSH_OK; /* nothing on this route releases a clock; the reads prove them on */
        e.lun = res.target_lun;
        o = ufsh_finalize(&e, &p, &r);
    }
    /* What a DOWN needs to explain itself: AHIT was never read on the phone before this. */
    tgl_stamp(TGL_STAGE_UFS_LIVE, o == UFSH_LIVE ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED, (uint64_t)r.ahit << 32 | r.is);
    tgl_ufs_handoff_commit(o, e.lun, r.step, r.hcs);
    return o;
}
#endif
