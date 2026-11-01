/* SPDX-License-Identifier: MIT
 * See tgl_ufs_handoff.h. Host test: tgl_ufs_handoff_test.c. */
#include "tgl_ufs_handoff.h"

enum { S_START = 1, S_PRECHECK, S_STOP, S_VERIFY, S_CLOSE, S_ATTEST, S_DONE };

static int rd(const struct ufsh_ports *p, uint32_t off, uint32_t *v)
{
    return p->read32(p->ctx, off, v);
}

int ufsh_finalize(const struct ufsh_evidence *e, const struct ufsh_ports *p,
    struct ufsh_record *r)
{
    unsigned i;

    if (!r)
        return UFSH_HALT;
    for (i = 0; i < sizeof(*r); ++i)
        ((volatile uint8_t *)r)[i] = 0;
    r->step = S_START;
    if (!e || !p || !p->read32 || !p->write32 || !p->arena_close)
        return UFSH_HALT;
    if (!e->dma_opened)
        return UFSH_NO_DMA;
    /* A fault or doubtful command leaves DMA unknown. N882 has no way to end
     * it without a reset, so touching the host further proves nothing. */
    if (e->faulted || e->quarantined || e->retained)
        return UFSH_HALT;

    r->step = S_PRECHECK;
    if (rd(p, UFSH_UTRLDBR, &r->utrldbr) || rd(p, UFSH_UTMRLDBR, &r->utmrldbr) ||
        r->utrldbr || r->utmrldbr)
        return UFSH_HALT;

    /* Task list first: ufs_take_over moves only the transfer list, so nothing
     * later would stop UTMRLBA naming this arena. */
    r->step = S_STOP;
    if (p->write32(p->ctx, UFSH_UTMRLRSR, 0) || p->write32(p->ctx, UFSH_UTRLRSR, 0))
        return UFSH_HALT;

    r->step = S_VERIFY;
    if (rd(p, UFSH_UTMRLRSR, &r->utmrlrsr) || rd(p, UFSH_UTRLRSR, &r->utrlrsr) ||
        (r->utmrlrsr & 1u) || (r->utrlrsr & 1u) ||
        rd(p, UFSH_UTRLDBR, &r->utrldbr) || rd(p, UFSH_UTMRLDBR, &r->utmrldbr) ||
        r->utrldbr || r->utmrldbr)
        return UFSH_HALT;

    r->step = S_CLOSE;
    if (p->arena_close(p->ctx))
        return UFSH_HALT;
    r->arena_closed = 1;

    /* From here DMA is proven over, so a refusal only loses the UFS root. */
    r->step = S_ATTEST;
    if (rd(p, UFSH_AHIT, &r->ahit) || rd(p, UFSH_HCS, &r->hcs) || rd(p, UFSH_IS, &r->is))
        return UFSH_DOWN;
    r->step = S_DONE;
    if (e->read_match != 1 || e->lun >= 8 || r->ahit || e->aux_clk_held != 1 ||
        (r->hcs & UFSH_HCS_READY) != UFSH_HCS_READY || (r->is & UFSH_IS_FATAL))
        return UFSH_DOWN;
    return UFSH_LIVE;
}

/* Exact token match. Value is the text after name, or 0 if the token is absent. */
static const char *token(const char *s, const char *name)
{
    while (*s) {
        const char *a = s, *b = name;
        while (*s == ' ')
            ++s;
        a = s;
        while (*b && *a == *b) {
            ++a;
            ++b;
        }
        if (!*b)
            return a;
        while (*s && *s != ' ')
            ++s;
    }
    return 0;
}

static int value_is(const char *v, const char *want)
{
    if (!v)
        return 0;
    while (*want)
        if (*v++ != *want++)
            return 0;
    return !*v || *v == ' ';
}

int ufsh_cmdline_ok(const char *c, unsigned lun)
{
    const char *v;
    char digit[2];

    if (!c || lun >= 8)
        return 0;
    digit[0] = (char)('0' + lun);
    digit[1] = 0;
    if (!value_is(token(c, "blazer_ufs="), "2") || !value_is(token(c, "blazer_ufs_live="), "1"))
        return 0;
    v = token(c, "blazer_ufs_root=");
    if (!v || !*v || *v == ' ')
        return 0;
    v = token(c, "rd=");
    if (!value_is(v, "ufsroot0") && !value_is(v, "md0"))
        return 0;
    v = token(c, "blazer_ufs_lun=");
    return v ? value_is(v, digit) : lun == 0;
}
