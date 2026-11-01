/* SPDX-License-Identifier: MIT
 * Order and values follow shipped ufs.ko c7697fd6 (link_startup_notify POST_CHANGE, .rodata+0xe1b8
 * CPORT table, IID quirk), then android16-6.12 ufshcd.c. N912 M1-M6 are addressed here:
 * M1 IID=1 on all UPIUs; M2 UA retried; M3 tag==slot==0; M4 OCS low nibble only and tolerant echoes;
 * M5 lists ready before run/stop; M6 fDeviceInit polled against a 1.5 s clock. */
#include "tgl_ufs_host.h"

/* UFSHCI registers. Checked against Linux ufshci.h by tests/run_all.py, not by this file. */
#define R_CAP 0x00u
#define R_IS 0x20u
#define R_IE 0x24u
#define R_HCS 0x30u
#define R_HCE 0x34u
#define R_UECPA 0x38u
#define R_UECDL 0x3cu
#define R_UECN 0x40u
#define R_UECT 0x44u
#define R_UECDME 0x48u
#define R_IAG 0x4cu
#define R_UTRLBA 0x50u
#define R_UTRLBAU 0x54u
#define R_UTRLDBR 0x58u
#define R_UTRLCLR 0x5cu
#define R_UTRLRSR 0x60u
#define R_UTMRLBA 0x70u
#define R_UTMRLBAU 0x74u
#define R_UTMRLDBR 0x78u
#define R_UTMRLRSR 0x80u
#define R_UICCMD 0x90u
#define R_UICARG1 0x94u
#define R_UICARG2 0x98u
#define R_UICARG3 0x9cu
#define R_BUSTHRTL 0xc0u
#define R_CONFIG 0x300u

#define HCS_DP 0x1u
#define HCS_READY 0xeu /* UTRLRDY|UTMRLRDY|UCRDY, UFSHCD_STATUS_READY */
#define HCS_UCRDY 0x8u
#define IS_UCCS 0x400u
#define IS_FATAL (0x80u | 0x800u | 0x1000u | 0x10000u | 0x20000u | 0x40000u)
#define IS_HOST_FATAL (0x10000u | 0x20000u | 0x40000u)
#define CAP_64AS (1u << 24)
/* shipped ufs_google_link_startup_notify +0x24c..0x280: both PG caps absent from the FDT. */
#define BUSTHRTL_CLEAR 0x30000u

/* inf_smmu, SMMUv3 */
#define SM_CR0 0x20u
#define SM_CR0ACK 0x24u
#define SM_GBPA 0x44u
#define SM_GERROR 0x60u
#define SM_GERRORN 0x64u
#define GBPA_UPDATE (1u << 31)
#define GBPA_ABORT (1u << 20)

/* Arena: same geometry as Linux's UCD: command 512, response 512, PRDT. */
#define A_UTRL 0x0000u
#define A_UTMRL 0x0400u
#define A_UCD 0x0800u
#define A_RSP (A_UCD + 0x200u)
#define A_PRD (A_UCD + 0x400u)
#define A_DATA 0x1000u
#define DATA_BYTES 4096u /* Linux scsi_report_lun_scan first length: (511+1)*8; also one UFS block */
_Static_assert(DATA_BYTES == TGL_UFSH_BLOCK_BYTES, "one block per doorbell fits the data buffer");
#define A_GUARD (A_DATA + DATA_BYTES) /* never in a PRD: any change here means DMA overran the buffer */
#define GUARD_BYTES 64u
_Static_assert(A_GUARD + GUARD_BYTES <= TGL_UFSH_ARENA_BYTES, "guard inside arena");
#define RC10_BYTES 8u /* Linux read_capacity_10 */
#define GBPA_EXPECT 0x2e1fu /* ufs-dma-r1: exact value ABL programs. Any other is a stop, never a repair */
#define GPT_ENTRY_BYTES 128u
#define GPT_HDR_MIN 92u
#define GPT_HDR_MAX 512u
#define WITNESS_ENTRIES 2u
#define WLUN_NONE_ABOVE 8u /* standard LUs the engine will address */

#define UPIU_NOP_OUT 0x00u
#define UPIU_COMMAND 0x01u
#define UPIU_QUERY 0x16u
#define UPIU_NOP_IN 0x20u
#define UPIU_RESPONSE 0x21u
#define UPIU_QUERY_RSP 0x36u
#define IID_ONE 0x10u
#define FLAGS_READ 0x40u
#define Q_READ 0x01u
#define Q_WRITE 0x81u
#define OP_READ_FLAG 0x05u
#define OP_SET_FLAG 0x06u
#define IDN_FDEVICEINIT 0x01u
#define WLUN_REPORT_LUNS 0x81u
#define SCSI_TUR 0x00u
#define SCSI_REPORT_LUNS 0xa0u
#define SCSI_READ_CAPACITY_10 0x25u
#define SCSI_READ_10 0x28u
#define RSP_U 0x20u
#define RSP_O 0x40u
#define MASK_OCS 0x0fu

#define NOP_TRIES 10u
#define NOP_TIMEOUT_US 50000u
#define QUERY_TRIES 3u
#define QUERY_TIMEOUT_US 1500000u
#define INIT_POLL_US 1500000u
#define SCSI_TIMEOUT_US 2000000u
#define SCSI_TRIES 8u
#define CLEAR_TIMEOUT_US 1000000u
#define UIC_TIMEOUT_US 500000u
#define UIC_POLLS_MAX 10000000u /* a stopped clock must not mean forever: these two loops have no delay port */
#define READY_TIMEOUT_US 100000u
#define LOG_FLAG_READS 4u
#define RSP_LOG_MAX 320u
#define ENTRY_MAX (24u + 40u + RSP_LOG_MAX + 16u)
#define DATA_LOG_MAX 512u

struct st {
    const struct tgl_ufsh_request *q;
    const struct tgl_ufsh_ports *p;
    struct tgl_ufsh_result *o;
    uint64_t start, deadline;
    uint32_t used;
    unsigned inflight;
    uint32_t stale_is;
    uint32_t polls, elapsed, is0, is1, dw2, rsp_bytes;
    uint32_t v1_dw2, v1_left, v2_left, guard_ok, dropped, witnesses;
    int cmd_rc;
    uint8_t v1[8], v2[8];
    uint8_t req[32], rsp[RSP_LOG_MAX], hdr[GPT_HDR_MAX], ent[GPT_ENTRY_BYTES];
#if TGL_UFS_POWER_MODE
    uint32_t target_lba[TGL_UFSH_HS_VERIFY_BLOCKS], target_crc[TGL_UFSH_HS_VERIFY_BLOCKS], target_n;
#if TGL_UFS_PWM_FALLBACK
    unsigned fb_quiet;
#endif
#endif
};
static unsigned attempted;
static struct st g;
static uint8_t ebuf[ENTRY_MAX + DATA_LOG_MAX];

static void le32(uint8_t *b, uint32_t v) { for (unsigned i = 0; i < 4; i++) b[i] = (uint8_t)(v >> (8 * i)); }
static void vle32(volatile uint8_t *b, uint32_t v) { for (unsigned i = 0; i < 4; i++) b[i] = (uint8_t)(v >> (8 * i)); }
static uint32_t be16(const uint8_t *b) { return (uint32_t)b[0] << 8 | b[1]; }
static uint32_t be32(const uint8_t *b) { return (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3]; }
static void bzero8(uint8_t *b, uint32_t n) { for (uint32_t i = 0; i < n; i++) ((volatile uint8_t *)b)[i] = 0; }
static uint32_t crc32_(const uint8_t *b, uint32_t n)
{
    uint32_t c = 0xffffffffu;
    for (uint32_t i = 0; i < n; i++) {
        c ^= b[i];
        for (unsigned k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return ~c;
}
static uint32_t crc_more(uint32_t c, const volatile uint8_t *b, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++) {
        c ^= b[i];
        for (unsigned k = 0; k < 8; k++) c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return c;
}
static uint32_t rdle32(const uint8_t *b) { return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 | (uint32_t)b[3] << 24; }
static uint64_t rdle64(const uint8_t *b) { return (uint64_t)rdle32(b) | (uint64_t)rdle32(b + 4) << 32; }
/* Position-dependent, so "untouched", "all zero" and "shifted" are three different failures. */
static uint8_t canary_at(uint32_t i) { return (uint8_t)(0xa5u ^ (i * 0x3du) ^ (i >> 8)); }
static uint32_t now32(struct st *s)
{
    uint64_t t = s->start;
    if (s->p->now_us(s->p->ctx, &t)) return 0;
    return (uint32_t)(t - s->start);
}
/* Each entry carries its own CRC, so a hang leaves a decodable prefix. */
static void append(struct st *s, unsigned type, unsigned step, const uint32_t *w, unsigned nw, const volatile uint8_t *bytes, uint32_t nb)
{
    uint32_t n = 8u + nw * 4u + nb, total = ((n + 3u) & ~3u) + 4u, at = 8;
    uint32_t reserve = type == TGL_UFSH_T_END ? 0u : ENTRY_MAX;
#if TGL_UFS_PWM_FALLBACK
    /* The first pass has filled most of the 8 KiB: after a failed change, notes, reads and the end only. */
    if (s->fb_quiet && type != TGL_UFSH_T_GATE && type != TGL_UFSH_T_READ && type != TGL_UFSH_T_END) return;
#endif
    if (total > sizeof(ebuf) || s->used + total + reserve > TGL_UFSH_RECORD_BYTES) { s->dropped++; return; }
    bzero8(ebuf, total);
    ebuf[0] = (uint8_t)total; ebuf[1] = (uint8_t)(total >> 8); ebuf[2] = (uint8_t)type; ebuf[3] = (uint8_t)step;
    le32(ebuf + 4, now32(s));
    for (unsigned i = 0; i < nw; i++, at += 4) le32(ebuf + at, w[i]);
    for (uint32_t i = 0; i < nb; i++) ebuf[at + i] = bytes[i];
    le32(ebuf + total - 4u, crc32_(ebuf, total - 4u));
    (void)s->p->rec_write(s->p->ctx, s->used, ebuf, total);
    s->used += total;
}
static int rd(struct st *s, uint32_t o, uint32_t *v) { return s->p->hc_rd(s->p->ctx, o, v) ? TGL_UFSH_E_PORT : 0; }
static int wr(struct st *s, uint32_t o, uint32_t v) { return s->p->hc_wr(s->p->ctx, o, v) ? TGL_UFSH_E_PORT : 0; }
static int clock_(struct st *s, uint64_t *t)
{
    if (s->p->now_us(s->p->ctx, t)) return TGL_UFSH_E_PORT;
    return *t >= s->deadline ? TGL_UFSH_E_BUDGET : 0;
}

/* ---- UIC: shipped link_startup_notify POST_CHANGE ---- */
static int uic_once(struct st *s, uint32_t op, uint32_t a1, uint32_t a3, uint32_t *out)
{
    uint64_t t0, t; uint32_t v; int r;
    if ((r = clock_(s, &t0))) return r;
    for (uint32_t n = 0;; n++) {
        if ((r = rd(s, R_HCS, &v))) return r;
        if (v & HCS_UCRDY) break;
        if ((r = clock_(s, &t))) return r;
        if (t - t0 >= UIC_TIMEOUT_US || n >= UIC_POLLS_MAX) return TGL_UFSH_E_UIC;
    }
    if ((r = wr(s, R_IS, IS_UCCS)) || (r = wr(s, R_UICARG1, a1)) || (r = wr(s, R_UICARG2, 0)) ||
        (r = wr(s, R_UICARG3, a3)) || (r = wr(s, R_UICCMD, op))) return r;
    for (uint32_t n = 0;; n++) {
        if ((r = rd(s, R_IS, &v))) return r;
        if (v & IS_UCCS) break;
        if ((r = clock_(s, &t))) return r;
        if (t - t0 >= UIC_TIMEOUT_US || n >= UIC_POLLS_MAX) return TGL_UFSH_E_UIC;
    }
    if ((r = wr(s, R_IS, IS_UCCS)) || (r = rd(s, R_UICARG2, &v))) return r;
    if (v & 0xffu) { if (out) *out = v; return TGL_UFSH_E_UIC; }
    return out ? rd(s, R_UICARG3, out) : 0;
}
static int uic(struct st *s, uint32_t op, uint32_t a1, uint32_t a3, uint32_t *out)
{
    /* ufshcd_dme_set_attr: peer sets retry, UFS_UIC_COMMAND_RETRIES tries in total. */
    unsigned tries = op == 4u || op == 3u ? 3u : 1u;
    int r = TGL_UFSH_E_UIC;
    for (unsigned i = 0; i < tries; i++) {
        uint32_t got = 0;
        r = uic_once(s, op, a1, a3, out ? out : &got);
        uint32_t w[6] = { op, a1, a3, out ? *out : got, i, (uint32_t)r };
        append(s, TGL_UFSH_T_UIC, TGL_UFSH_P_POST_CHANGE, w, 6, 0, 0);
        if (r != TGL_UFSH_E_UIC) break;
    }
    return r;
}
/* Same order and values as shipped .rodata+0xe1b8 (18 entries); run_all.py compares the live table. */
static const struct { uint16_t attr; uint8_t val, peer; } cport[18] = {
    {0x4020, 0, 0}, {0x3000, 0, 0}, {0x3001, 1, 0}, {0x4021, 1, 0}, {0x4022, 0, 0}, {0x4023, 0, 0},
    {0x4025, 6, 0}, {0x402b, 1, 0}, {0x4020, 1, 0},
    {0x4020, 0, 1}, {0x3000, 1, 1}, {0x3001, 1, 1}, {0x4021, 0, 1}, {0x4022, 0, 1}, {0x4023, 0, 1},
    {0x4025, 6, 1}, {0x402b, 1, 1}, {0x4020, 1, 1},
};
static int post_change(struct st *s)
{
    uint32_t v = 0; int r;
    if (s->p->delay_us(s->p->ctx, 500, 600)) return TGL_UFSH_E_PORT;
    if ((r = uic(s, 1, 0x15a80000u, 0, &v))) return r; /* PA_TACTIVATE get */
    if (v == UINT32_MAX) return TGL_UFSH_E_UIC;
    v += 1;
    if ((r = uic(s, 2, 0x15a80000u, v, 0))) return r;
    for (unsigned i = 0; i < 18; i++)
        if ((r = uic(s, cport[i].peer ? 4u : 2u, (uint32_t)cport[i].attr << 16, cport[i].val, 0))) return r;
    if ((r = rd(s, R_BUSTHRTL, &v)) || (r = wr(s, R_BUSTHRTL, v & ~BUSTHRTL_CLEAR))) return r;
    return rd(s, R_UECPA, &v); /* ufshcd_link_startup: clear-on-read once */
}

/* ---- UTP transfer ---- */
/* The only wire traffic this file can produce. Anything else is refused before the doorbell. */
static int wire_allowed(const uint8_t r[32], unsigned data_in, uint32_t alloc)
{
    if (r[3] != 0 || r[4] != IID_ONE) return 0;
    if (r[0] == UPIU_NOP_OUT) return !data_in && !r[1] && !r[5];
    if (r[0] == UPIU_QUERY) {
        if (data_in || r[1]) return 0;
        if (r[5] == Q_WRITE) return r[12] == OP_SET_FLAG && r[13] == IDN_FDEVICEINIT && !r[14] && !r[15];
        if (r[5] != Q_READ) return 0;
        return r[12] == OP_READ_FLAG && r[13] == IDN_FDEVICEINIT;
    }
    if (r[0] != UPIU_COMMAND) return 0;
    /* Exact frames: every CDB byte is pinned, so RDPROTECT, DPO, FUA, group, count and control cannot vary. */
    uint32_t edtl = be32(r + 12);
    unsigned lu = r[2] < WLUN_NONE_ABOVE, zero = 1;
    if (edtl != alloc) return 0;
    if (r[16] == SCSI_TUR) {
        for (unsigned i = 17; i < 32u; i++) if (r[i]) zero = 0;
        return zero && !data_in && !r[1] && !alloc && (lu || r[2] == WLUN_REPORT_LUNS);
    }
    if (r[16] == SCSI_REPORT_LUNS) { /* one exact frame, W-LUN only */
        for (unsigned i = 17; i < 32u; i++) if (r[i] && !(i >= 22u && i <= 25u)) zero = 0;
        return zero && data_in && r[1] == FLAGS_READ && alloc == DATA_BYTES && r[2] == WLUN_REPORT_LUNS && be32(r + 22) == alloc;
    }
    if (r[16] == SCSI_READ_CAPACITY_10) {
        for (unsigned i = 17; i < 32u; i++) if (r[i]) zero = 0;
        return zero && data_in && r[1] == FLAGS_READ && alloc == RC10_BYTES && lu;
    }
    if (r[16] == SCSI_READ_10) { /* one block, plain read: bytes 18-21 are the LBA, 23-24 the count */
        for (unsigned i = 26; i < 32u; i++) if (r[i]) zero = 0;
        return zero && data_in && r[1] == FLAGS_READ && alloc == TGL_UFSH_BLOCK_BYTES && lu && !r[17] && !r[22] && be16(r + 23) == 1u && !r[25];
    }
    return 0;
}
static int clear_slot(struct st *s)
{
    uint64_t t0, t; uint32_t v; int r;
    if (s->p->now_us(s->p->ctx, &t0)) return TGL_UFSH_E_PORT;
    if ((r = wr(s, R_UTRLCLR, ~UINT32_C(1)))) return r; /* ufshcd_utrl_clear: 0 clears a slot */
    for (;;) {
        if ((r = rd(s, R_UTRLDBR, &v))) return r;
        if (!(v & 1u)) return 0;
        if (s->p->now_us(s->p->ctx, &t)) return TGL_UFSH_E_PORT;
        if (t - t0 >= CLEAR_TIMEOUT_US) return TGL_UFSH_E_TIMEOUT;
        if (s->p->delay_us(s->p->ctx, 10, 10)) return TGL_UFSH_E_PORT;
    }
}
/* One doorbell, one slot, tag 0. Fills s->rsp; the caller interprets it. */
static int exchange_(struct st *s, unsigned data_in, uint32_t alloc, uint32_t timeout_us, unsigned expect)
{
    volatile uint8_t *a = s->q->arena;
    uint64_t t0, t, ucd = s->q->arena_bus + A_UCD, data = s->q->arena_bus + A_DATA;
    uint32_t v, n; int r;
    s->polls = s->elapsed = s->is0 = s->is1 = s->dw2 = s->rsp_bytes = 0;
    if (!wire_allowed(s->req, data_in, alloc)) return TGL_UFSH_E_DENIED;
    if (s->req[0] == UPIU_COMMAND && s->req[16] == SCSI_READ_10) {
        /* The bound on media reads. Sits here so no caller path can pass it. */
        if (s->o->read_blocks >= TGL_UFSH_MAX_READ_BLOCKS) return TGL_UFSH_E_DENIED;
        s->o->read_blocks++;
    }
    if ((r = clock_(s, &t0))) return r;
    for (uint32_t i = 0; i < 0x420u; i++) a[A_UCD + i] = 0;
    for (uint32_t i = 0; i < 32u; i++) { a[A_UTRL + i] = 0; a[A_UCD + i] = s->req[i]; }
    /* ufshcd_prepare_req_desc_hdr: UFS storage type, DD, interrupt bit with aggregation off. */
    vle32(a + A_UTRL, data_in ? UINT32_C(0x15000000) : UINT32_C(0x11000000));
    vle32(a + A_UTRL + 8u, 0x0fu); /* OCS invalid until completion */
    vle32(a + A_UTRL + 16u, (uint32_t)ucd);
    vle32(a + A_UTRL + 20u, (uint32_t)(ucd >> 32));
    vle32(a + A_UTRL + 24u, UINT32_C(0x00800080)); /* response length, offset in dwords */
    vle32(a + A_UTRL + 28u, data_in ? UINT32_C(0x01000001) : UINT32_C(0x01000000)); /* PRDT len, offset */
    if (data_in) {
        vle32(a + A_PRD, (uint32_t)data);
        vle32(a + A_PRD + 4u, (uint32_t)(data >> 32));
        vle32(a + A_PRD + 12u, alloc - 1u); /* zero-based byte count */
        for (uint32_t i = 0; i < DATA_BYTES + GUARD_BYTES; i++) a[A_DATA + i] = canary_at(i);
    }
    if (s->p->sync(s->p->ctx, 1)) return TGL_UFSH_E_PORT;
    if ((r = rd(s, R_IS, &s->is0))) return r;
    s->inflight = 1; s->o->dma_started = 1;
    if ((r = wr(s, R_UTRLDBR, 1))) return r;
    for (;;) {
        if ((r = rd(s, R_UTRLDBR, &v))) return r;
        s->polls++;
        if (!(v & 1u)) break;
        if (s->p->now_us(s->p->ctx, &t)) return TGL_UFSH_E_PORT;
        if (t - t0 >= timeout_us || t >= s->deadline) {
            s->elapsed = (uint32_t)(t - t0);
            if ((r = clear_slot(s))) return r; /* inflight stays set: quarantine */
            if (s->p->sync(s->p->ctx, 0)) return TGL_UFSH_E_PORT;
            /* No abort task went first, so a cleared data command may still land: stays quarantined. */
            if (!data_in) s->inflight = 0;
            return TGL_UFSH_E_TIMEOUT;
        }
        if (s->p->delay_us(s->p->ctx, 10, 10)) return TGL_UFSH_E_PORT;
    }
    if (data_in) { /* ufs-dma-r1 V1: DBR clear, no maintenance yet. Loads at M=0 allocate nothing */
        s->v1_dw2 = (uint32_t)a[A_UTRL + 8u] | (uint32_t)a[A_UTRL + 9u] << 8 | (uint32_t)a[A_UTRL + 10u] << 16 | (uint32_t)a[A_UTRL + 11u] << 24;
        s->v1_left = 0;
        for (uint32_t i = 0; i < DATA_BYTES; i++) { uint8_t x = a[A_DATA + i]; if (i < 8u) s->v1[i] = x; if (x == canary_at(i)) s->v1_left++; }
    }
    if (s->p->sync(s->p->ctx, 0)) return TGL_UFSH_E_PORT;
    s->inflight = 0;
    if (s->p->now_us(s->p->ctx, &t)) return TGL_UFSH_E_PORT;
    s->elapsed = (uint32_t)(t - t0);
    if ((r = rd(s, R_IS, &s->is1))) return r;
    s->dw2 = (uint32_t)a[A_UTRL + 8u] | (uint32_t)a[A_UTRL + 9u] << 8 |
             (uint32_t)a[A_UTRL + 10u] << 16 | (uint32_t)a[A_UTRL + 11u] << 24;
    for (uint32_t i = 0; i < 32u; i++) s->rsp[i] = a[A_RSP + i];
    n = be16(s->rsp + 10);
    s->rsp_bytes = 32u + n > RSP_LOG_MAX ? RSP_LOG_MAX : 32u + n;
    for (uint32_t i = 32; i < s->rsp_bytes; i++) s->rsp[i] = a[A_RSP + i];
    if ((s->is1 & ~s->is0) & IS_FATAL) { s->inflight = 1; return TGL_UFSH_E_FATAL; } /* keep quarantined */
    if (data_in) { /* V2: after DC CIVAC */
        s->v2_left = 0; s->guard_ok = 1;
        for (uint32_t i = 0; i < DATA_BYTES; i++) { uint8_t x = a[A_DATA + i]; if (i < 8u) s->v2[i] = x; if (x == canary_at(i)) s->v2_left++; }
        for (uint32_t i = DATA_BYTES; i < DATA_BYTES + GUARD_BYTES; i++) if (a[A_DATA + i] != canary_at(i)) s->guard_ok = 0;
        if (!s->guard_ok) { s->inflight = 1; return TGL_UFSH_E_GUARD; } /* DMA ignored the PRD: nothing else is safe */
    }
    if (s->dw2 & MASK_OCS) return TGL_UFSH_E_OCS;
    /* Linux checks transaction and tag only. Echoes of LUN, byte 4, byte 5 stay in the record. */
    if (s->rsp[0] != expect || s->rsp[3] != s->req[3]) return TGL_UFSH_E_PROTOCOL;
    return 0;
}
static void log_cmd(struct st *s, unsigned step, unsigned attempt)
{
    static uint8_t b[32 + RSP_LOG_MAX];
    uint32_t w[8] = { attempt, (uint32_t)s->cmd_rc, s->polls, s->elapsed, s->is0, s->is1, s->dw2, s->rsp_bytes };
    for (uint32_t i = 0; i < 32u; i++) b[i] = s->req[i];
    for (uint32_t i = 0; i < s->rsp_bytes; i++) b[32 + i] = s->rsp[i];
    append(s, TGL_UFSH_T_CMD, step, w, 8, b, 32u + s->rsp_bytes);
}
static int exchange(struct st *s, unsigned step, unsigned attempt, unsigned quiet, unsigned data_in, uint32_t alloc, uint32_t timeout_us, unsigned expect)
{
    int r = s->cmd_rc = exchange_(s, data_in, alloc, timeout_us, expect);
    if (!quiet || r) log_cmd(s, step, attempt);
    return r;
}
static void upiu_zero(struct st *s) { bzero8(s->req, 32); s->req[4] = IID_ONE; }
static void compose_query(struct st *s, unsigned fn, unsigned op, unsigned idn, unsigned index, unsigned len)
{
    upiu_zero(s);
    s->req[0] = UPIU_QUERY; s->req[5] = (uint8_t)fn;
    s->req[12] = (uint8_t)op; s->req[13] = (uint8_t)idn; s->req[14] = (uint8_t)index;
    s->req[18] = (uint8_t)(len >> 8); s->req[19] = (uint8_t)len;
}
static int nop(struct st *s)
{
    int r = TGL_UFSH_E_TIMEOUT;
    for (unsigned i = 0; i < NOP_TRIES; i++) {
        upiu_zero(s); s->req[0] = UPIU_NOP_OUT;
        r = exchange(s, TGL_UFSH_P_NOP, i, 0, 0, 0, NOP_TIMEOUT_US, UPIU_NOP_IN);
        /* ufshcd_verify_dev_init: stop on success or timeout, retry other errors. */
        if (!r || r == TGL_UFSH_E_TIMEOUT || r == TGL_UFSH_E_FATAL || r == TGL_UFSH_E_PORT || r == TGL_UFSH_E_BUDGET) break;
    }
    return r;
}
static int query(struct st *s, unsigned step, unsigned attempt, unsigned quiet, uint32_t timeout_us)
{
    int r = exchange(s, step, attempt, quiet, 0, 0, timeout_us, UPIU_QUERY_RSP);
    if (r) return r;
    if (s->rsp[6]) { s->cmd_rc = TGL_UFSH_E_QUERY; if (quiet) log_cmd(s, step, attempt); return TGL_UFSH_E_QUERY; }
    return 0;
}
static int device_init(struct st *s)
{
    uint64_t t0, t; int r = TGL_UFSH_E_QUERY;
    /* ufshcd_query_flag_retry: QUERY_REQ_RETRIES tries. */
    s->o->phase = TGL_UFSH_P_SET_INIT;
    for (unsigned i = 0; i < QUERY_TRIES; i++) {
        compose_query(s, Q_WRITE, OP_SET_FLAG, IDN_FDEVICEINIT, 0, 0);
        r = query(s, TGL_UFSH_P_SET_INIT, i, 0, QUERY_TIMEOUT_US);
        if (!r || r == TGL_UFSH_E_TIMEOUT || r == TGL_UFSH_E_FATAL || r == TGL_UFSH_E_PORT || r == TGL_UFSH_E_BUDGET) break;
    }
    if (r) return r;
    s->o->phase = TGL_UFSH_P_POLL_INIT;
    if (s->p->now_us(s->p->ctx, &t0)) return TGL_UFSH_E_PORT;
    for (;;) { /* ufshcd_complete_dev_init: FDEVICEINIT_COMPL_TIMEOUT 1500 ms, 500-1000 us pause */
        compose_query(s, Q_READ, OP_READ_FLAG, IDN_FDEVICEINIT, 0, 0);
        s->o->flag_reads++;
        unsigned quiet = s->o->flag_reads > LOG_FLAG_READS;
        r = query(s, TGL_UFSH_P_POLL_INIT, s->o->flag_reads, quiet, QUERY_TIMEOUT_US);
        if (r) return r;
        if (s->p->now_us(s->p->ctx, &t)) return TGL_UFSH_E_PORT;
        s->o->flag_us = (uint32_t)(t - t0);
        unsigned flag = (be32(s->rsp + 20) & 0xffu) & 1u;
        if (!flag) { if (quiet) log_cmd(s, TGL_UFSH_P_POLL_INIT, s->o->flag_reads); return 0; }
        if (t - t0 >= INIT_POLL_US) { if (quiet) log_cmd(s, TGL_UFSH_P_POLL_INIT, s->o->flag_reads); return TGL_UFSH_E_INIT; }
        if (s->p->delay_us(s->p->ctx, 500, 1000)) return TGL_UFSH_E_PORT;
    }
}
/* Fixed or descriptor sense, after the BE16 length at response byte 32. */
static int sense(struct st *s)
{
    uint32_t n = s->rsp_bytes >= 34u ? be16(s->rsp + 32) : 0, kind, key, asc, ascq;
    if (n < 8u || 34u + n > s->rsp_bytes) return TGL_UFSH_E_PROTOCOL;
    kind = s->rsp[34] & 0x7fu;
    if ((kind == 0x70u || kind == 0x71u) && n >= 14u) { key = s->rsp[36] & 15u; asc = s->rsp[46]; ascq = s->rsp[47]; }
    else if (kind == 0x72u || kind == 0x73u) { key = s->rsp[35] & 15u; asc = s->rsp[36]; ascq = s->rsp[37]; }
    else return TGL_UFSH_E_PROTOCOL;
    s->o->sense = key << 16 | asc << 8 | ascq;
    return 0;
}
/* One SCSI command, bounded retries on UNIT ATTENTION (M2) and NOT READY. Sense is kept; no data moves on a retry.
 * quiet: a GOOD reply is not logged, every other reply is. */
static int scsi_lu(struct st *s, unsigned step, unsigned lun, const uint8_t *cdb, unsigned cdb_len, unsigned data_in, uint32_t alloc, unsigned quiet)
{
    int r = TGL_UFSH_E_SCSI;
    for (unsigned i = 0; i < SCSI_TRIES; i++) {
        upiu_zero(s);
        s->req[0] = UPIU_COMMAND; s->req[2] = (uint8_t)lun;
        s->req[1] = data_in ? FLAGS_READ : 0;
        s->req[12] = (uint8_t)(alloc >> 24); s->req[13] = (uint8_t)(alloc >> 16);
        s->req[14] = (uint8_t)(alloc >> 8); s->req[15] = (uint8_t)alloc;
        for (unsigned k = 0; k < cdb_len; k++) s->req[16u + k] = cdb[k];
        if (step == TGL_UFSH_P_TUR) s->o->tur_attempts++;
        r = exchange(s, step, i, quiet, data_in, alloc, SCSI_TIMEOUT_US, UPIU_RESPONSE);
        if (r) return r;
#if !TGL_UFS_SCSI_STATUS_ONLY
        if (s->rsp[6]) { if (quiet) log_cmd(s, step, i); return TGL_UFSH_E_SCSI; }
#endif
        if (!s->rsp[7]) return 0;
        if (quiet) log_cmd(s, step, i);
        if (s->rsp[7] != 0x02u) return TGL_UFSH_E_SCSI;
        if ((r = sense(s))) return r;
        uint32_t key = s->o->sense >> 16;
        if (key == 6u) s->o->ua_seen++;
        else if (key != 2u) return TGL_UFSH_E_SCSI;
        r = TGL_UFSH_E_SCSI;
        if (s->p->delay_us(s->p->ctx, 10000, 10000)) return TGL_UFSH_E_PORT;
    }
    return r;
}
/* TUR and REPORT LUNS to the REPORT LUNS W-LUN: it does not depend on LU 0 being enabled. */
static int scsi(struct st *s, unsigned step, uint8_t opcode, unsigned data_in, uint32_t alloc)
{
    uint8_t cdb[12];
    bzero8(cdb, sizeof(cdb));
    cdb[0] = opcode;
    if (opcode == SCSI_REPORT_LUNS) { /* scsi_report_lun_scan, SELECT REPORT 0 */
        cdb[6] = (uint8_t)(alloc >> 24); cdb[7] = (uint8_t)(alloc >> 16);
        cdb[8] = (uint8_t)(alloc >> 8); cdb[9] = (uint8_t)alloc;
    }
    return scsi_lu(s, step, WLUN_REPORT_LUNS, cdb, opcode == SCSI_REPORT_LUNS ? 12u : 6u, data_in, alloc, 0);
}
static int report_luns(struct st *s)
{
    volatile uint8_t *d = s->q->arena + A_DATA;
    uint8_t h[8];
    uint32_t have = DATA_BYTES, resid = be32(s->rsp + 12), tail_ok = 1, n;
    int r = scsi(s, TGL_UFSH_P_REPORT_LUNS, SCSI_REPORT_LUNS, 1, DATA_BYTES);
    if (r) return r;
    resid = be32(s->rsp + 12);
    if (s->rsp[1] & RSP_O) return TGL_UFSH_E_PROTOCOL;
    if (s->rsp[1] & RSP_U) { if (resid > DATA_BYTES) return TGL_UFSH_E_PROTOCOL; have = DATA_BYTES - resid; }
    for (uint32_t i = have; i < DATA_BYTES; i++) if (d[i] != canary_at(i)) tail_ok = 0;
    uint32_t w[2] = { have, tail_ok };
    append(s, TGL_UFSH_T_DATA, TGL_UFSH_P_REPORT_LUNS, w, 2, d, have > DATA_LOG_MAX ? DATA_LOG_MAX : have);
    if (have < 8u) return TGL_UFSH_E_LUNS;
    for (unsigned i = 0; i < 8u; i++) h[i] = d[i];
    n = be32(h);
    s->o->list_len = n;
    if ((n & 7u) || n > DATA_BYTES - 8u || n + 8u > have) return TGL_UFSH_E_LUNS;
    for (uint32_t i = 0; i < n / 8u; i++) {
        uint8_t b0 = d[8u + i * 8u], b1 = d[9u + i * 8u];
        if (b0 || b1 >= 8u || s->o->lun_count >= 8u) continue; /* raw bytes are in the record */
        s->o->luns[s->o->lun_count++] = b1;
    }
    return 0;
}
/* ufs-dma-r1: read again right before DMA is asked for. Any change is a stop, never a repair. */
static int smmu_gate(struct st *s, unsigned where)
{
    void *c = s->p->ctx;
    uint32_t w[6] = { where, 0, 0, 0, 0, 0 };
    if (s->p->smmu_rd(c, SM_CR0, &w[1]) || s->p->smmu_rd(c, SM_CR0ACK, &w[2]) || s->p->smmu_rd(c, SM_GBPA, &w[3]) ||
        s->p->smmu_rd(c, SM_GERROR, &w[4]) || s->p->smmu_rd(c, SM_GERRORN, &w[5])) return TGL_UFSH_E_PORT;
    append(s, TGL_UFSH_T_GATE, s->o->phase, w, 6, 0, 0);
    return (w[1] || w[2] || w[3] != GBPA_EXPECT || (w[4] ^ w[5])) ? TGL_UFSH_E_SMMU : 0;
}
/* One READ(10) of one block into the data buffer. raw: also record the first bytes. Good means: full
 * transfer, no residual, and the canary is gone. */
static int read_block(struct st *s, unsigned step, unsigned lun, uint32_t lba, unsigned raw, uint32_t *crc_out)
{
    volatile uint8_t *d = s->q->arena + A_DATA;
    uint8_t cdb[10];
    static uint8_t b[16 + 64];
    uint32_t crc = 0, resid = 0, nb = 16;
    bzero8(cdb, sizeof(cdb));
    cdb[0] = SCSI_READ_10;
    cdb[2] = (uint8_t)(lba >> 24); cdb[3] = (uint8_t)(lba >> 16); cdb[4] = (uint8_t)(lba >> 8); cdb[5] = (uint8_t)lba;
    cdb[8] = 1; /* transfer length, big endian at 7-8 */
    s->v1_left = s->v2_left = s->v1_dw2 = 0;
    bzero8(s->v1, 8); bzero8(s->v2, 8);
    int r = scsi_lu(s, step, lun, cdb, 10, 1, TGL_UFSH_BLOCK_BYTES, s->o->read_blocks != 0u);
    if (!r) {
        resid = be32(s->rsp + 12);
        if ((s->rsp[1] & (RSP_O | RSP_U)) || resid) r = TGL_UFSH_E_PROTOCOL;
        else if (s->v2_left == TGL_UFSH_BLOCK_BYTES) r = TGL_UFSH_E_NODATA; /* GOOD, but nothing arrived */
        else crc = ~crc_more(0xffffffffu, d, TGL_UFSH_BLOCK_BYTES);
    }
    if (crc_out) *crc_out = crc;
    uint32_t w[13] = { lun, lba, (uint32_t)r, s->polls, s->elapsed, s->is1, s->dw2,
        (uint32_t)s->rsp[1] | (uint32_t)s->rsp[6] << 8 | (uint32_t)s->rsp[7] << 16, resid, crc, s->v1_left, s->v2_left, s->v1_dw2 };
    for (unsigned i = 0; i < 8u; i++) { b[i] = s->v1[i]; b[8u + i] = s->v2[i]; }
    if (raw && !r) { for (unsigned i = 0; i < 64u; i++) b[16u + i] = d[i]; nb = 80; }
#if TGL_UFS_POWER_MODE
    if (step == TGL_UFSH_P_HS_VERIFY) nb = 0; /* the CRC and the time are the point; the record holds 8 KiB */
#if TGL_UFS_PWM_FALLBACK
    if (step == TGL_UFSH_P_PWM_VERIFY) nb = 0;
#endif
#endif
    append(s, TGL_UFSH_T_READ, step, w, 13, b, nb);
    return r;
}
static int name_is_target(const uint8_t *utf16)
{
    static const char t[] = "userdata_exp.ai";
    for (unsigned i = 0; i < 36u; i++) {
        uint8_t want = i < sizeof(t) - 1u ? (uint8_t)t[i] : 0u;
        if (utf16[i * 2u] != want || utf16[i * 2u + 1u]) return 0;
    }
    return 1;
}
/* GPT header in s->hdr, against what READ CAPACITY said. Linux is_gpt_valid, block/partitions/efi.c. */
static int gpt_header_valid(struct st *s, struct tgl_ufsh_lu *L, uint32_t *array_crc, uint64_t *first_use, uint64_t *last_use, uint32_t *blocks)
{
    static const char sig[8] = { 'E', 'F', 'I', ' ', 'P', 'A', 'R', 'T' };
    uint8_t *h = s->hdr;
    for (unsigned i = 0; i < 8u; i++) if (h[i] != (uint8_t)sig[i]) return 0;
    uint32_t hs = rdle32(h + 12), stored = rdle32(h + 16);
    if (hs < GPT_HDR_MIN || hs > GPT_HDR_MAX) return 0;
    for (unsigned i = 16; i < 20u; i++) h[i] = 0;
    uint32_t crc = crc32_(h, hs);
    le32(h + 16, stored);
    if (crc != stored) return 0;
    uint64_t my = rdle64(h + 24), fu = rdle64(h + 40), lu = rdle64(h + 48), el = rdle64(h + 72);
    uint32_t n = rdle32(h + 80), sz = rdle32(h + 84);
    L->entry_lba = (uint32_t)el; L->num_entries = n; L->entry_size = sz;
    if (my != 1u || fu > lu || lu > L->max_lba || el < 2u || el > L->max_lba) return 0;
    if (sz != GPT_ENTRY_BYTES || !n || n > UINT32_C(0x100000)) return 0;
    uint32_t nb = (n * GPT_ENTRY_BYTES + TGL_UFSH_BLOCK_BYTES - 1u) / TGL_UFSH_BLOCK_BYTES;
    if (el + nb - 1u > L->max_lba) return 0;
    *array_crc = rdle32(h + 88); *first_use = fu; *last_use = lu; *blocks = nb;
    return 1;
}
static void log_part(struct st *s, unsigned lun, uint32_t index, uint64_t first, uint64_t last, unsigned target)
{
    uint8_t name[36];
    uint32_t w[7] = { lun, index, (uint32_t)first, (uint32_t)(first >> 32), (uint32_t)last, (uint32_t)(last >> 32), target };
    for (unsigned i = 0; i < 36u; i++) name[i] = s->ent[56u + i * 2u];
    append(s, TGL_UFSH_T_PART, TGL_UFSH_P_GPT, w, 7, name, 36);
}
static int lu_inner(struct st *s, struct tgl_ufsh_lu *L, unsigned first_lu)
{
    volatile uint8_t *d = s->q->arena + A_DATA;
    struct tgl_ufsh_result *o = s->o;
    unsigned lun = L->lun;
    uint8_t cdb[10];
    uint64_t fu = 0, lu = 0, cf = 0, cl = 0;
    uint32_t array_crc = 0, blocks = 0, crc = 0xffffffffu, left, have_cand = 0, index = 0;
    int r;
    L->stage = o->phase = TGL_UFSH_P_LU_TUR;
    bzero8(cdb, sizeof(cdb));
    if ((r = scsi_lu(s, TGL_UFSH_P_LU_TUR, lun, cdb, 6, 0, 0, !first_lu))) return r;
    L->stage = o->phase = TGL_UFSH_P_READ_CAP;
    cdb[0] = SCSI_READ_CAPACITY_10;
    if ((r = scsi_lu(s, TGL_UFSH_P_READ_CAP, lun, cdb, 10, 1, RC10_BYTES, !first_lu))) return r;
    if ((s->rsp[1] & RSP_O) || ((s->rsp[1] & RSP_U) && be32(s->rsp + 12))) return TGL_UFSH_E_CAP;
    if (s->v2_left == TGL_UFSH_BLOCK_BYTES) return TGL_UFSH_E_NODATA;
    if (s->v2_left < TGL_UFSH_BLOCK_BYTES - RC10_BYTES) return TGL_UFSH_E_CAP; /* wrote past 8 bytes */
    {
        uint8_t c8[8];
        for (unsigned i = 0; i < 8u; i++) c8[i] = d[i];
        L->max_lba = be32(c8); L->block_bytes = be32(c8 + 4);
    }
    /* 0xffffffff means READ CAPACITY(16) is needed. No LU on this 128 GB part can be that big, so it is a stop. */
    if (L->block_bytes != TGL_UFSH_BLOCK_BYTES || L->max_lba == UINT32_MAX || L->max_lba < 2u) return TGL_UFSH_E_CAP;
    L->stage = o->phase = TGL_UFSH_P_GPT;
    if (o->read_blocks >= TGL_UFSH_GPT_READ_BLOCKS) { L->truncated = 1; return TGL_UFSH_E_GPT; } /* target's share stays reserved */
    if ((r = read_block(s, TGL_UFSH_P_GPT, lun, 1, 0, 0))) return r;
    for (unsigned i = 0; i < GPT_HDR_MAX; i++) s->hdr[i] = d[i];
    {
        uint32_t w[1] = { lun };
        append(s, TGL_UFSH_T_HDR, TGL_UFSH_P_GPT, w, 1, s->hdr, GPT_HDR_MIN);
    }
    if (!gpt_header_valid(s, L, &array_crc, &fu, &lu, &blocks)) return TGL_UFSH_E_GPT;
    L->gpt_ok = 1;
    s->witnesses = 0;
    left = L->num_entries * GPT_ENTRY_BYTES;
    for (uint32_t b = 0; b < blocks; b++) {
        if (b >= TGL_UFSH_LU_ENTRY_BLOCKS || o->read_blocks >= TGL_UFSH_GPT_READ_BLOCKS) { L->truncated = 1; break; }
        if ((r = read_block(s, TGL_UFSH_P_GPT, lun, L->entry_lba + b, 0, 0))) return r;
        uint32_t n = left > TGL_UFSH_BLOCK_BYTES ? TGL_UFSH_BLOCK_BYTES : left;
        crc = crc_more(crc, d, n);
        left -= n;
        for (uint32_t off = 0; off < n; off += GPT_ENTRY_BYTES, index++) {
            unsigned used = 0, hit;
            for (unsigned i = 0; i < GPT_ENTRY_BYTES; i++) s->ent[i] = d[off + i];
            for (unsigned i = 0; i < 16u; i++) if (s->ent[i]) used = 1;
            if (!used) continue;
            L->used++;
            hit = name_is_target(s->ent + 56);
            uint64_t first = rdle64(s->ent + 32), last = rdle64(s->ent + 40);
            if (hit || s->witnesses < WITNESS_ENTRIES) { log_part(s, lun, index, first, last, hit); if (!hit) s->witnesses++; }
            if (hit && !have_cand) { have_cand = 1; cf = first; cl = last; }
            else if (hit) L->target_bad = 2; /* twice inside one table */
        }
    }
    /* A table is believed whole or not at all. A truncated or corrupt one yields no target. */
    if (L->truncated) return TGL_UFSH_E_GPT;
    if (~crc != array_crc) return TGL_UFSH_E_GPT;
    L->entries_crc_ok = 1;
    if (have_cand) {
        if (L->target_bad || cf < fu || cl > lu || cf > cl || cl > L->max_lba) { if (!L->target_bad) L->target_bad = 1; return TGL_UFSH_E_GPT; }
        if (o->target_found) o->target_dups++;
        else { o->target_found = 1; o->target_lun = lun; o->target_first = (uint32_t)cf; o->target_last = (uint32_t)cl; }
    }
    return 0;
}
/* A LU that fails leaves its reason here and the pass moves on: LU 0 being the data LU is only inferred. */
static int lu_survivable(int r)
{
    return r == TGL_UFSH_E_SCSI || r == TGL_UFSH_E_OCS || r == TGL_UFSH_E_PROTOCOL || r == TGL_UFSH_E_CAP || r == TGL_UFSH_E_GPT;
}
static int read_target_block(struct st *s, uint32_t lba, unsigned raw)
{
    uint32_t crc = 0;
    int r = read_block(s, TGL_UFSH_P_TARGET, s->o->target_lun, lba, raw, &crc);
#if TGL_UFS_POWER_MODE
    if (!r && s->target_n < TGL_UFSH_HS_VERIFY_BLOCKS) { s->target_lba[s->target_n] = lba; s->target_crc[s->target_n++] = crc; }
#endif
    return r;
}
static int read_target(struct st *s)
{
    volatile uint8_t *d = s->q->arena + A_DATA;
    struct tgl_ufsh_result *o = s->o;
    static const char nx[4] = { 'N', 'X', 'S', 'B' };
    static const char mg[8] = { 'U', 'F', 'S', 'S', 'T', 'G', '1', 0 };
    int r;
    o->phase = TGL_UFSH_P_TARGET;
    if ((r = smmu_gate(s, 0x100u))) return r;
    for (uint32_t i = 0; i < TGL_UFSH_TARGET_BLOCKS && o->target_first + i <= o->target_last; i++) {
        if ((r = read_target_block(s, o->target_first + i, 1))) return r;
        if (!i) {
            unsigned ok = 1;
            for (unsigned k = 0; k < 4u; k++) if (d[32u + k] != (uint8_t)nx[k]) ok = 0;
            o->target_nxsb = ok;
        }
    }
    if (o->target_last - o->target_first >= TGL_UFSH_MANIFEST_BLOCK) {
        unsigned ok = 1;
        if ((r = read_target_block(s, o->target_first + TGL_UFSH_MANIFEST_BLOCK, 1))) return r;
        for (unsigned k = 0; k < 8u; k++) if (d[k] != (uint8_t)mg[k]) ok = 0;
        o->target_manifest = ok;
    }
    {
        /* Same blocks as ufs-read-r2. Each boot's CRCs are the oracle for XNU's read test; no image is required. */
        static const uint32_t samp[TGL_UFSH_SAMPLE_BLOCKS] = { 4096u,65536u,131072u,262144u,400000u,524288u,604000u, };
        for (unsigned i = 0; i < TGL_UFSH_SAMPLE_BLOCKS; i++) {
            if (o->target_last - o->target_first < samp[i]) break;
            if ((r = read_target_block(s, o->target_first + samp[i], 1))) return r;
        }
    }
    return 0;
}
static int read_pass(struct st *s)
{
    struct tgl_ufsh_result *o = s->o;
    for (uint32_t i = 0; i < o->lun_count; i++) {
        struct tgl_ufsh_lu *L = &o->lu[i];
        uint32_t ua0 = o->ua_seen;
        int r;
        L->lun = o->luns[i];
        o->phase = TGL_UFSH_P_LU_TUR;
        if ((r = smmu_gate(s, i))) return r;
        o->sense = 0;
        r = L->rc = lu_inner(s, L, i == 0u);
        L->sense = o->sense; L->ua = o->ua_seen - ua0;
        uint32_t w[15] = { L->lun, L->stage, (uint32_t)L->rc, L->sense, L->ua, L->max_lba, L->block_bytes, L->gpt_ok, L->entries_crc_ok,
            L->truncated, L->entry_lba, L->num_entries, L->entry_size, L->used, L->target_bad };
        append(s, TGL_UFSH_T_LU, L->stage, w, 15, 0, 0);
        if (r && !lu_survivable(r)) return r;
    }
    if (!o->target_found) return TGL_UFSH_E_NOT_FOUND;
    return read_target(s);
}
#if TGL_UFS_POWER_MODE
/* unipro.h. Order: vendor PRE_CHANGE (ufs-google.c:1843-1853), then ufshcd_change_power_mode (ufshcd.c:4452-4499). */
#define PA_ACTIVETXDATALANES 0x1560u
#define PA_CONNECTEDTXDATALANES 0x1561u
#define PA_TXGEAR 0x1568u
#define PA_TXTERMINATION 0x1569u
#define PA_HSSERIES 0x156au
#define PA_PWRMODE 0x1571u
#define PA_ACTIVERXDATALANES 0x1580u
#define PA_CONNECTEDRXDATALANES 0x1581u
#define PA_RXGEAR 0x1583u
#define PA_RXTERMINATION 0x1584u
#define PA_MAXRXHSGEAR 0x1587u
#define PA_TACTIVATE 0x15a8u
#define PA_GRANULARITY 0x15aau
#define PA_PWRMODEUSERDATA0 0x15b0u
#define PA_TXHSADAPTTYPE 0x15d4u
#define DME_LOCALFC0 0xd041u
#define DME_LOCALTC0 0xd042u
#define DME_LOCALAFC0 0xd043u
#define PA_INITIAL_ADAPT 1u
#define PA_HS_MODE_B 2u
#define HS_GEAR 4u  /* ABL's log: "ufshc_power_mode_change HS gear 4"; device is UFS 3.1 */
#define HS_LANES 2u /* vendor google_pwr_mode */
#define PWR_FAST_BOTH 0x11u
#define IS_UPMS 0x10u
#define UPMCRS(hcs) (((hcs) >> 8) & 7u)
#define PWR_LOCAL 1u
#define UIC_GET 1u
#define UIC_SET 2u
#define UIC_PEER_GET 3u
#define UIC_PEER_SET 4u
#define PMC_TIMEOUT_US 500000u /* ufshcd.c UIC_CMD_TIMEOUT */
#define MIB(a) ((uint32_t)(a) << 16)
static void pmc_note(struct st *s, uint32_t where, uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e)
{
    uint32_t w[6] = { where, a, b, c, d, e };
    append(s, TGL_UFSH_T_GATE, TGL_UFSH_P_PMC, w, 6, 0, 0);
}
/* DME one entry each would overflow the 8 KiB record: values go in pmc_note, and only a failure gets its own T_UIC entry. */
static int dme_quiet(struct st *s, uint32_t op, uint32_t attr, uint32_t a3, uint32_t *out)
{
    /* ufshcd_dme_set_attr, ufshcd_dme_get_attr: peer commands retry, UFS_UIC_COMMAND_RETRIES tries in total. */
    unsigned tries = op == UIC_PEER_GET || op == UIC_PEER_SET ? 3u : 1u;
    int r = TGL_UFSH_E_UIC;
    for (unsigned i = 0; i < tries; i++) {
        uint32_t got = 0;
        r = uic_once(s, op, MIB(attr), a3, out ? out : &got);
        if (!r) return 0;
        uint32_t w[6] = { op, MIB(attr), a3, out ? *out : got, i, (uint32_t)r };
        append(s, TGL_UFSH_T_UIC, TGL_UFSH_P_PMC, w, 6, 0, 0);
        if (r != TGL_UFSH_E_UIC) break;
    }
    return r;
}
/* ufs_fixups: Samsung, UFS_DEVICE_QUIRK_HOST_PA_TACTIVATE. ufshcd_quirk_tune_host_pa_tactivate, ufshcd.c:8244. */
static int tune_peer_tactivate(struct st *s)
{
    static const uint8_t us[6] = { 1, 4, 8, 16, 32, 100 };
    uint32_t g = 0, pg = 0, t = 0, pt = 0, t_us, pt_us; int r;
    if ((r = dme_quiet(s, UIC_GET, PA_GRANULARITY, 0, &g)) || (r = dme_quiet(s, UIC_PEER_GET, PA_GRANULARITY, 0, &pg))) return r;
    if ((r = dme_quiet(s, UIC_GET, PA_TACTIVATE, 0, &t)) || (r = dme_quiet(s, UIC_PEER_GET, PA_TACTIVATE, 0, &pt))) return r;
    pmc_note(s, TGL_UFSH_PMC_WHERE_TACT, g, pg, t, pt, 0);
    if (g < 1u || g > 6u || pg < 1u || pg > 6u) return TGL_UFSH_E_PMC;
    t_us = t * us[g - 1u]; pt_us = pt * us[pg - 1u];
    if (t_us >= pt_us) return dme_quiet(s, UIC_PEER_SET, PA_TACTIVATE, t_us / us[pg - 1u] + 1u, 0);
    return 0;
}
/* ufshcd_uic_pwr_ctrl: completion is UPMS, then UPMCRS must say PWR_LOCAL. Only UCCS and UPMS are acknowledged. */
static int issue_power_mode(struct st *s)
{
    uint64_t t0, t; uint32_t v = 0, hcs = 0, polls = 0, us = 0; int r, rc = TGL_UFSH_E_PMC;
    if ((r = clock_(s, &t0))) return r;
    for (uint32_t n = 0;; n++) {
        if ((r = rd(s, R_HCS, &v))) return r;
        if (v & HCS_UCRDY) break;
        if ((r = clock_(s, &t))) return r;
        if (t - t0 >= UIC_TIMEOUT_US || n >= UIC_POLLS_MAX) return TGL_UFSH_E_UIC; /* boot-review-r1: a stopped clock must not mean forever */
    }
    if ((r = wr(s, R_IS, IS_UCCS | IS_UPMS)) || (r = wr(s, R_UICARG1, MIB(PA_PWRMODE))) || (r = wr(s, R_UICARG2, 0)) ||
        (r = wr(s, R_UICARG3, PWR_FAST_BOTH))) return r;
    s->o->pmc_state = 2;
    if ((r = wr(s, R_UICCMD, UIC_SET))) return r;
    if ((r = clock_(s, &t0))) return r;
    for (;;) {
        polls++;
        if ((r = rd(s, R_IS, &v))) return r;
        if (s->p->now_us(s->p->ctx, &t)) return TGL_UFSH_E_PORT;
        us = (uint32_t)(t - t0);
        if (v & IS_FATAL) break;
        if (v & IS_UCCS) {
            uint32_t a2;
            if ((r = rd(s, R_UICARG2, &a2))) return r;
            if (a2 & 0xffu) break; /* refused: no UPMS will come */
        }
        if (v & IS_UPMS) {
            if ((r = wr(s, R_IS, IS_UCCS | IS_UPMS)) || (r = rd(s, R_HCS, &hcs))) return r;
            if (UPMCRS(hcs) == PWR_LOCAL) rc = 0;
            break;
        }
        if (us >= PMC_TIMEOUT_US) break;
        if (s->p->delay_us(s->p->ctx, 10, 10)) return TGL_UFSH_E_PORT;
    }
    pmc_note(s, TGL_UFSH_PMC_WHERE_DONE, (uint32_t)rc, v, hcs, us, polls);
    return rc;
}
static int change_power_mode(struct st *s)
{
    /* Same order as source. UserData 0..5 and the local timeouts are the DL_* defaults. */
    static const struct { uint16_t attr, val; } set[] = {
        { PA_TXHSADAPTTYPE, PA_INITIAL_ADAPT }, { PA_RXGEAR, HS_GEAR }, { PA_ACTIVERXDATALANES, HS_LANES }, { PA_RXTERMINATION, 1 },
        { PA_TXGEAR, HS_GEAR }, { PA_ACTIVETXDATALANES, HS_LANES }, { PA_TXTERMINATION, 1 }, { PA_HSSERIES, PA_HS_MODE_B },
        { PA_PWRMODEUSERDATA0 + 0u, 8191 }, { PA_PWRMODEUSERDATA0 + 1u, 65535 }, { PA_PWRMODEUSERDATA0 + 2u, 32767 },
        { PA_PWRMODEUSERDATA0 + 3u, 8191 }, { PA_PWRMODEUSERDATA0 + 4u, 65535 }, { PA_PWRMODEUSERDATA0 + 5u, 32767 },
        { DME_LOCALFC0, 8191 }, { DME_LOCALTC0, 65535 }, { DME_LOCALAFC0, 32767 },
    };
    int r;
    for (unsigned i = 0; i < sizeof(set) / sizeof(set[0]); i++)
        if ((r = dme_quiet(s, UIC_SET, set[i].attr, set[i].val, 0))) return r;
    return issue_power_mode(s);
}
/* What the host now says, as DME GETs. Before the change these show the mode every earlier boot ran in. */
static int read_mode(struct st *s, uint32_t where)
{
    uint32_t got[5];
    static const uint16_t attr[5] = { PA_PWRMODE, PA_RXGEAR, PA_TXGEAR, PA_ACTIVERXDATALANES, PA_ACTIVETXDATALANES };
    int r;
    for (unsigned i = 0; i < 5u; i++) if ((r = dme_quiet(s, UIC_GET, attr[i], 0, &got[i]))) return r;
    pmc_note(s, where, got[0], got[1], got[2], got[3], got[4]);
    return 0;
}
/* Every block read at PWM, read again at HS. Same bytes or the link is not trusted with a root. */
static int hs_verify(struct st *s)
{
    struct tgl_ufsh_result *o = s->o;
    int r;
    o->phase = TGL_UFSH_P_HS_VERIFY;
    if ((r = smmu_gate(s, 0x500u))) return r;
    for (uint32_t i = 0; i < s->target_n; i++) {
        uint32_t crc = 0;
        if ((r = read_block(s, TGL_UFSH_P_HS_VERIFY, o->target_lun, s->target_lba[i], 0, &crc))) return r;
        if (crc != s->target_crc[i]) return TGL_UFSH_E_HS_CRC;
    }
    return 0;
}
#if TGL_UFS_PHY_CHECK || TGL_UFS_PWM_FALLBACK
static void mark(struct st *s, unsigned id, unsigned state, int32_t val)
{
    if (s->p->mark) s->p->mark(s->p->ctx, id, state, val);
}
#endif
#if TGL_UFS_PHY_CHECK
/* reuse-stability-r1. Recorded for the case HS ever fails, never a reason to refuse: the phone reached HS without these reads.
 * DME_GET only. The indirect PHY registers need DME_SET of the APB pointer, so they are not read here. */
static void phy_check(struct st *s)
{
    static const struct { uint16_t attr, sel; } get[6] = { {0x8101, 0}, {0x8115, 0}, {0x8019, 4}, {0x8019, 5}, {0x8013, 4}, {0x8013, 5} };
    uint32_t top = 0, param = 0, dmux = 0, tx = 0, v[6] = { 0 }, failed = 0;
    void *c = s->p->ctx;
    mark(s, TGL_UFSH_MARK_PHY, 1, 0);
    if (!s->p->top_rd || s->p->top_rd(c, 0x100u, &top)) failed |= 1u << 8;
    if (!s->p->pad_rd || s->p->pad_rd(c, 2u, 0u, &param) || s->p->pad_rd(c, 2u, 4u, &dmux) || s->p->pad_rd(c, 2u, 8u, &tx)) failed |= 1u << 9;
    pmc_note(s, TGL_UFSH_PMC_WHERE_PHY0, top, param, dmux, tx, 0);
    for (unsigned i = 0; i < 6u; i++)
        if (uic_once(s, UIC_GET, MIB(get[i].attr) | get[i].sel, 0, &v[i])) failed |= 1u << i;
    pmc_note(s, TGL_UFSH_PMC_WHERE_PHY1, v[0], v[1], v[2], v[3], v[4]);
    pmc_note(s, TGL_UFSH_PMC_WHERE_PHY2, v[5], failed, 0, 0, 0);
    mark(s, TGL_UFSH_MARK_PHY, 2, (int32_t)failed);
}
#endif
#if TGL_UFS_PWM_FALLBACK
static int stop_lists(struct st *s);
static int install_lists(struct st *s);
/* One device reset and link, the sequence that works at PWM, then the phone's own bring-up and the target blocks compared with the first PWM pass.
 * No DMA is live here: the caller checked inflight and quarantine, and lists stop first. Any failure returns the first error, and the handoff stays DOWN. */
static int pwm_fallback(struct st *s, int why)
{
    struct tgl_ufsh_result *o = s->o;
    uint32_t uec[2] = { 0, 0 }, is = 0, hcs = 0, stale = 0; int r; uint32_t n = 0;
    o->pmc_first_rc = why;
    (void)rd(s, R_UECPA, &uec[0]); (void)rd(s, R_UECDL, &uec[1]); (void)rd(s, R_IS, &is); (void)rd(s, R_HCS, &hcs);
    pmc_note(s, TGL_UFSH_PMC_WHERE_FAIL, (uint32_t)why, uec[0], uec[1], is, hcs);
    if (!s->p->relink) return why;
    mark(s, TGL_UFSH_MARK_RELINK, 1, why);
    s->fb_quiet = 1;
    o->phase = TGL_UFSH_P_PWM_RELINK;
    if ((r = stop_lists(s))) { o->quarantined = 1; goto out; }
    if ((r = s->p->relink(s->p->ctx))) { r = TGL_UFSH_E_PMC; goto out; }
    o->phase = TGL_UFSH_P_POST_CHANGE;
    if ((r = rd(s, R_IS, &stale)) || (r = wr(s, R_IS, stale)) || (r = wr(s, R_IE, 0)) || (r = post_change(s))) goto out;
    o->phase = TGL_UFSH_P_LISTS;
    if ((r = install_lists(s))) goto out;
    o->phase = TGL_UFSH_P_NOP;
    if ((r = smmu_gate(s, 0x600u)) || (r = nop(s)) || (r = device_init(s))) goto out;
    o->phase = TGL_UFSH_P_TUR;
    if ((r = scsi(s, TGL_UFSH_P_TUR, SCSI_TUR, 0, 0))) goto out;
    if ((r = read_mode(s, TGL_UFSH_PMC_WHERE_PWM))) goto out;
    o->phase = TGL_UFSH_P_PWM_VERIFY;
    for (uint32_t i = 0; i < s->target_n; i++, n++) {
        uint32_t crc = 0;
        if ((r = read_block(s, TGL_UFSH_P_PWM_VERIFY, o->target_lun, s->target_lba[i], 0, &crc))) goto out;
        if (crc != s->target_crc[i]) { r = TGL_UFSH_E_HS_CRC; goto out; }
    }
    o->pmc_state = 4;
out:
    pmc_note(s, TGL_UFSH_PMC_WHERE_FB_END, (uint32_t)r, n, 0, 0, 0);
    mark(s, TGL_UFSH_MARK_RELINK, r ? 3 : 2, r);
    return r ? why : 0;
}
#endif
/* The strong symbol tools/check.py looks for. Doorbells idle: every command above is synchronous, and this checks. */
int tgl_ufsh_power_mode(struct st *s)
{
    struct tgl_ufsh_result *o = s->o;
    uint32_t rx = 0, tx = 0, local = 0, peer = 0, a, b, reason = 0; int r;
    o->phase = TGL_UFSH_P_PMC;
    if ((r = rd(s, R_UTRLDBR, &a)) || (r = rd(s, R_UTMRLDBR, &b))) return r;
    if (a || b) return TGL_UFSH_E_STATE;
    if ((r = read_mode(s, TGL_UFSH_PMC_WHERE_BEFORE))) return r;
    if ((r = dme_quiet(s, UIC_GET, PA_CONNECTEDRXDATALANES, 0, &rx)) || (r = dme_quiet(s, UIC_GET, PA_CONNECTEDTXDATALANES, 0, &tx)) ||
        (r = dme_quiet(s, UIC_GET, PA_MAXRXHSGEAR, 0, &local)) || (r = dme_quiet(s, UIC_PEER_GET, PA_MAXRXHSGEAR, 0, &peer))) return r;
    pmc_note(s, TGL_UFSH_PMC_WHERE_CAPS, rx, tx, local, peer, 0);
#if TGL_UFS_PHY_CHECK
    phy_check(s);
#endif
    /* A device or host unable to do what ABL did: nothing was set, and the link still works at PWM. */
    if (rx != HS_LANES || tx != HS_LANES) reason = 1;
    else if (local < HS_GEAR || peer < HS_GEAR) reason = 2;
    if (reason) { o->pmc_state = 1; pmc_note(s, TGL_UFSH_PMC_WHERE_SKIP, reason, 0, 0, 0, 0); return 0; }
#if TGL_UFS_PHY_CHECK || TGL_UFS_PWM_FALLBACK
    mark(s, TGL_UFSH_MARK_PMC, 1, 0); /* sealed before the first SET: a reset from here names the change */
    o->pmc_state = 2;
#endif
    if ((r = tune_peer_tactivate(s)) || (r = change_power_mode(s))) return r == TGL_UFSH_E_PMC ? r : TGL_UFSH_E_PMC;
#if TGL_UFS_PHY_CHECK || TGL_UFS_PWM_FALLBACK
    mark(s, TGL_UFSH_MARK_PMC, 2, 0);
    mark(s, TGL_UFSH_MARK_HS_VERIFY, 1, 0);
#endif
    /* Recorded, not judged: the decoder compares them. UPMCRS and the CRCs below are what this route trusts. */
    if (read_mode(s, TGL_UFSH_PMC_WHERE_AFTER)) return TGL_UFSH_E_PMC;
    if ((r = hs_verify(s))) return r;
    o->pmc_state = 3;
    return 0;
}
#endif
static int stop_lists(struct st *s)
{
    uint32_t a, b; int r;
    s->o->phase = TGL_UFSH_P_STOP;
    if (s->inflight) return TGL_UFSH_E_STOP;
    if ((r = rd(s, R_UTRLDBR, &a)) || (r = rd(s, R_UTMRLDBR, &b))) return r;
    if (a || b) return TGL_UFSH_E_STOP;
    if ((r = wr(s, R_UTMRLRSR, 0)) || (r = wr(s, R_UTRLRSR, 0))) return r;
    if ((r = rd(s, R_UTMRLRSR, &a)) || (r = rd(s, R_UTRLRSR, &b))) return r;
    if ((a | b) & 1u) return TGL_UFSH_E_STOP;
    s->o->lists_stopped = 1;
    return 0;
}
static void seal(struct st *s, int rc)
{
    const struct tgl_ufsh_result *o = s->o;
    uint32_t e[5] = { 0 }, hcs = 0;
    if (o->phase >= TGL_UFSH_P_POST_CHANGE) {
        (void)rd(s, R_UECPA, &e[0]); (void)rd(s, R_UECDL, &e[1]); (void)rd(s, R_UECN, &e[2]);
        (void)rd(s, R_UECT, &e[3]); (void)rd(s, R_UECDME, &e[4]); (void)rd(s, R_HCS, &hcs);
    }
    uint32_t w[20] = { (uint32_t)rc, o->phase, o->dma_started, o->quarantined, o->lists_stopped,
        o->flag_reads, o->flag_us, o->tur_attempts, o->ua_seen, o->sense, o->list_len, o->lun_count,
        (uint32_t)o->luns[0] | (uint32_t)o->luns[1] << 8 | (uint32_t)o->luns[2] << 16 | (uint32_t)o->luns[3] << 24,
        (uint32_t)o->luns[4] | (uint32_t)o->luns[5] << 8 | (uint32_t)o->luns[6] << 16 | (uint32_t)o->luns[7] << 24,
        e[0], e[1], e[2], e[3], e[4], hcs };
    uint32_t x[30];
    for (unsigned i = 0; i < 20u; i++) x[i] = w[i];
    x[20] = o->read_blocks; x[21] = o->target_found; x[22] = o->target_lun; x[23] = o->target_first; x[24] = o->target_last;
    x[25] = o->target_dups; x[26] = o->target_nxsb; x[27] = o->target_manifest; x[28] = s->dropped; x[29] = o->quarantined;
    append(s, TGL_UFSH_T_END, o->phase, x, 30, 0, 0);
}
/* Reads only. Any refusal here leaves zero register writes and zero DMA. */
static int preflight(struct st *s)
{
    uint32_t w[20]; int r;
    uint32_t cap, ver = 0, is, ie, hcs, hce, cfg, thr, dbr, tdbr, rsr, trsr;
    uint32_t cr0, ack, gbpa, ge, gn, cr0b, gbpab;
    void *c = s->p->ctx;
    if ((r = rd(s, R_CAP, &cap)) || (r = rd(s, 0x08u, &ver)) || (r = rd(s, R_IS, &is)) || (r = rd(s, R_IE, &ie)) ||
        (r = rd(s, R_HCS, &hcs)) || (r = rd(s, R_HCE, &hce)) || (r = rd(s, R_CONFIG, &cfg)) ||
        (r = rd(s, R_BUSTHRTL, &thr)) || (r = rd(s, R_UTRLDBR, &dbr)) || (r = rd(s, R_UTMRLDBR, &tdbr)) ||
        (r = rd(s, R_UTRLRSR, &rsr)) || (r = rd(s, R_UTMRLRSR, &trsr))) return r;
    if (s->p->smmu_rd(c, SM_CR0, &cr0) || s->p->smmu_rd(c, SM_CR0ACK, &ack) || s->p->smmu_rd(c, SM_GBPA, &gbpa) ||
        s->p->smmu_rd(c, SM_GERROR, &ge) || s->p->smmu_rd(c, SM_GERRORN, &gn) ||
        s->p->smmu_rd(c, SM_CR0, &cr0b) || s->p->smmu_rd(c, SM_GBPA, &gbpab)) return TGL_UFSH_E_PORT;
    w[0] = cap; w[1] = ver; w[2] = is; w[3] = ie; w[4] = hcs; w[5] = hce; w[6] = cfg; w[7] = thr;
    w[8] = cr0; w[9] = ack; w[10] = gbpa; w[11] = ge; w[12] = gn;
    w[13] = s->q->sctlr; w[14] = s->q->currentel; w[15] = s->q->ctr;
    w[16] = (uint32_t)s->q->arena_bus; w[17] = (uint32_t)(s->q->arena_bus >> 32); w[18] = dbr | tdbr; w[19] = rsr | trsr << 1;
    append(s, TGL_UFSH_T_PRE, TGL_UFSH_P_PREFLIGHT, w, 20, 0, 0);
    if (s->q->sctlr & 1u) return TGL_UFSH_E_CPU;
    if (!(hcs & HCS_DP) || !(hcs & HCS_UCRDY) || !(hce & 1u)) return TGL_UFSH_E_NO_DEVICE;
    if ((cfg & 1u) || dbr || tdbr || (rsr & 1u) || (trsr & 1u) || (is & IS_HOST_FATAL)) return TGL_UFSH_E_STATE;
    if (!(cap & CAP_64AS) && (s->q->arena_bus >> 32)) return TGL_UFSH_E_STATE;
    /* result.json: CR0=0, GBPA=0x2e1f in the last boot. It is re-read here because it can change. */
    if ((cr0 & 1u) || (ack & 1u) || cr0 != cr0b || gbpa != gbpab || gbpa != GBPA_EXPECT || (gbpa & (GBPA_ABORT | GBPA_UPDATE)) || (ge ^ gn))
        return TGL_UFSH_E_SMMU;
    s->stale_is = is;
    return 0;
}
static int install_lists(struct st *s)
{
    volatile uint8_t *a = s->q->arena;
    uint64_t t0, t, u = s->q->arena_bus + A_UTRL, m = s->q->arena_bus + A_UTMRL;
    uint32_t v; int r;
    /* Before the first store: an old dirty line must not land on top of the descriptors. */
    if (s->p->sync(s->p->ctx, 1)) return TGL_UFSH_E_PORT;
    for (uint32_t i = 0; i < TGL_UFSH_ARENA_BYTES; i++) a[i] = 0;
    if (s->p->sync(s->p->ctx, 1)) return TGL_UFSH_E_PORT;
    if ((r = wr(s, R_IAG, 0)) || (r = wr(s, R_UTRLBA, (uint32_t)u)) || (r = wr(s, R_UTRLBAU, (uint32_t)(u >> 32))) ||
        (r = wr(s, R_UTMRLBA, (uint32_t)m)) || (r = wr(s, R_UTMRLBAU, (uint32_t)(m >> 32)))) return r;
    if ((r = clock_(s, &t0))) return r;
    for (;;) { /* M5: ufshcd_make_hba_operational wants the ready bits before run/stop */
        if ((r = rd(s, R_HCS, &v))) return r;
        if ((v & HCS_READY) == HCS_READY) break;
        if ((r = clock_(s, &t))) return r;
        if (t - t0 >= READY_TIMEOUT_US) return TGL_UFSH_E_STATE;
        if (s->p->delay_us(s->p->ctx, 10, 10)) return TGL_UFSH_E_PORT;
    }
    if ((r = wr(s, R_UTMRLRSR, 1)) || (r = wr(s, R_UTRLRSR, 1))) return r;
    if ((r = rd(s, R_UTRLRSR, &v))) return r;
    return (v & 1u) ? 0 : TGL_UFSH_E_STATE;
}
int tgl_ufsh_run(const struct tgl_ufsh_request *q, const struct tgl_ufsh_ports *p, struct tgl_ufsh_result *o)
{
    struct st *s = &g;
    int rc;
    if (!q || !p || !o) return TGL_UFSH_E_ARG;
    if (!q->enable) return o->rc = TGL_UFSH_OFF;
    if (attempted) return o->rc = TGL_UFSH_E_ONCE;
    attempted = 1;
    if (q->enable != 1u || !q->epoch || !q->arena || !q->arena_bus || (q->arena_bus & (TGL_UFSH_ARENA_ALIGN - 1u)) ||
        q->arena_bus < TGL_UFSH_ARENA_MIN || q->arena_bus + TGL_UFSH_ARENA_BYTES > TGL_UFSH_ARENA_END ||
        !q->budget_us || q->budget_us > TGL_UFSH_MAX_BUDGET_US || q->post_change_done > 1u ||
        !p->hc_rd || !p->hc_wr || !p->smmu_rd || !p->now_us || !p->delay_us || !p->sync || !p->rec_write)
        return o->rc = TGL_UFSH_E_ARG;
    s->q = q; s->p = p; s->o = o;
    if (p->now_us(p->ctx, &s->start)) return o->rc = TGL_UFSH_E_PORT;
    s->deadline = s->start + q->budget_us;
    /* Header. Entries follow from offset 64; the region holds old bytes, so zero it first. */
    {
        static uint8_t h[TGL_UFSH_RECORD_HEADER], z[256];
        for (uint32_t i = 0; i < TGL_UFSH_RECORD_BYTES; i += sizeof(z)) (void)p->rec_write(p->ctx, i, z, sizeof(z));
        for (unsigned i = 0; i < 8; i++) h[i] = (uint8_t)(TGL_UFSH_MAGIC >> (8 * i));
        le32(h + 8, TGL_UFSH_VERSION); le32(h + 12, TGL_UFSH_RECORD_BYTES);
        for (unsigned i = 0; i < 16; i++) h[16 + i] = q->nonce[i];
        for (unsigned i = 0; i < 8; i++) h[32 + i] = (uint8_t)(q->epoch >> (8 * i));
        for (unsigned i = 0; i < 8; i++) h[40 + i] = (uint8_t)(s->start >> (8 * i));
        le32(h + 60, crc32_(h, 60));
        (void)p->rec_write(p->ctx, 0, h, TGL_UFSH_RECORD_HEADER);
        s->used = TGL_UFSH_RECORD_HEADER;
    }
    o->phase = TGL_UFSH_P_PREFLIGHT;
    rc = preflight(s);
    /* ufshcd_init acks whatever IS holds at takeover and clears IE: this engine polls. Without this, a bit left by a failed first
     * LINK would hide the same bit during a command: exchange_ only sees bits that newly set. */
    if (!rc) { o->phase = TGL_UFSH_P_POST_CHANGE; rc = wr(s, R_IS, s->stale_is); if (!rc) rc = wr(s, R_IE, 0); }
    if (!rc && !q->post_change_done) rc = post_change(s);
    if (!rc) { o->phase = TGL_UFSH_P_LISTS; rc = install_lists(s); }
    if (!rc) { o->phase = TGL_UFSH_P_NOP; rc = smmu_gate(s, 0x200u); if (!rc) rc = nop(s); }
    if (!rc) rc = device_init(s);
    if (!rc) { o->phase = TGL_UFSH_P_TUR; rc = scsi(s, TGL_UFSH_P_TUR, SCSI_TUR, 0, 0); }
    if (!rc) { o->phase = TGL_UFSH_P_REPORT_LUNS; rc = report_luns(s); }
#if TGL_UFS_READ
    if (!rc) rc = read_pass(s);
#endif
#if TGL_UFS_POWER_MODE
    if (!rc) rc = tgl_ufsh_power_mode(s);
#if TGL_UFS_PWM_FALLBACK
    /* A READ that timed out quarantines or stays in flight: DMA may be live, so no reset of anything, as any READ timeout. */
    if (rc && o->pmc_state == 2 && !s->inflight && !o->quarantined) rc = pwm_fallback(s, rc);
    /* A failed read before any SET: the link is the PWM link the reads just used. */
    if (rc == TGL_UFSH_E_UIC && o->pmc_state == 0 && o->phase == TGL_UFSH_P_PMC && !s->inflight) { o->pmc_state = 1; pmc_note(s, TGL_UFSH_PMC_WHERE_SKIP, 3, 0, 0, 0, 0); rc = 0; }
#endif
#endif
    if (o->phase >= TGL_UFSH_P_NOP && !s->inflight) (void)smmu_gate(s, 0x300u); /* recorded: did it hold to the end */
    {
        unsigned failed_at = o->phase;
        if (o->phase >= TGL_UFSH_P_LISTS) {
            int st = stop_lists(s);
            if (st) o->quarantined = 1;
            if (!rc) rc = st;
        }
        if (rc) o->phase = failed_at;
        else o->phase = TGL_UFSH_P_DONE;
    }
    o->rc = rc;
    seal(s, rc);
    return rc;
}
void tgl_ufsh_note_fault(const struct tgl_ufsh_ports *p, struct tgl_ufsh_result *o, uint64_t esr, uint64_t far_value)
{
    struct st *s = &g;
    (void)esr; (void)far_value;
    if (!p || !o) return;
    /* A guard fault means register state is unknown, so seal() must not touch MMIO. */
    o->rc = TGL_UFSH_E_FAULT;
    o->quarantined = o->dma_started || o->phase >= TGL_UFSH_P_LISTS; /* lists may be running */
    if (s->p) {
        uint32_t w[4] = { (uint32_t)esr, (uint32_t)(esr >> 32), (uint32_t)far_value, (uint32_t)(far_value >> 32) };
        unsigned phase = o->phase;
        append(s, TGL_UFSH_T_CMD, phase, w, 4, 0, 0);
        o->phase = TGL_UFSH_P_NONE; /* seal skips the UEC reads */
        seal(s, TGL_UFSH_E_FAULT);
        o->phase = phase;
    }
}
