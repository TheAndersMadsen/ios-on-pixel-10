/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original native C DXT71 DMA encoder/inverse + byte-address memory lowerer.
 * No copied vendor implementation or shader template. See PROVENANCE.md.
 */
#include "hm_isa_memory.h"
#include <string.h>

static int overlap(const void *a, size_t an, const void *b, size_t bn)
{
    uintptr_t av = (uintptr_t)a, bv = (uintptr_t)b;
    /* Difference comparisons avoid pointer-end overflow and C pointer ordering. */
    if (!an || !bn) return 0;
    return av <= bv ? bv - av < an : av - bv < bn;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static uint32_t get32(const uint8_t *p)
{
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static int valid(const struct hmisa_dma *d)
{
    const struct hmisa_schedule *s;
    if (!d) return HMISA_E_ARGUMENT;
    if ((d->access != HMISA_READ && d->access != HMISA_WRITE) ||
        d->data_reg > 255 || d->x_bytes > 511 || d->y_count > 2047 ||
        d->stride > 2047 || d->add_first > 1) return HMISA_E_UNSUPPORTED;
    switch (d->address_bank) {
    case HMISA_SHARED:
        if (d->address_index > 510 || (d->address_index & 1)) return HMISA_E_UNSUPPORTED;
        break;
    case HMISA_VERTEX_INPUT:
        if (d->address_index > 127) return HMISA_E_UNSUPPORTED;
        break;
    case HMISA_HWTEMP:
        if (d->address_index > 255) return HMISA_E_UNSUPPORTED;
        break;
    default: return HMISA_E_UNSUPPORTED;
    }
    s = &d->schedule;
    if (s->wait_desched > 7 || s->wait_sync > 3) return HMISA_E_UNSUPPORTED;
    if (s->issue_kind == HMISA_ISSUE_DESCHED) {
        if (s->issue_index > 2) return HMISA_E_UNSUPPORTED;
    } else if (s->issue_kind == HMISA_ISSUE_SYNC) {
        if (d->access != HMISA_WRITE || s->issue_index > 1 ||
            (s->wait_sync & (1u << s->issue_index))) return HMISA_E_UNSUPPORTED;
    } else return HMISA_E_UNSUPPORTED;
    return HMISA_OK;
}

int hmisa_dma_descriptor(const struct hmisa_dma *d, uint32_t output[56])
{
    uint32_t g[56] = {0};
    int r;
    if (!output) return HMISA_E_ARGUMENT;
    if ((r = valid(d))) return r;
    if (overlap(d, sizeof *d, output, sizeof g)) return HMISA_E_ALIAS;
#define G(off, value) g[(off) / 4] = (value)
    G(0x28, 6); G(0x2c, 1); G(0x30, d->schedule.issue_kind);
    G(0x34, d->schedule.issue_index); G(0x38, d->schedule.wait_desched);
    G(0x3c, d->schedule.wait_sync); G(0x40, d->access == HMISA_READ ? 5 : 4);
    if (d->access == HMISA_WRITE) { G(0x4c, 4); G(0x50, d->data_reg); }
    G(0x5c, d->address_bank); G(0x60, d->address_index);
    if (d->access == HMISA_READ) { G(0x6c, 4); G(0x70, d->data_reg); }
    G(0x74, 12); G(0x78, d->y_count); G(0x7c, 12); G(0x80, d->x_bytes);
    G(0x84, 12); G(0x88, d->stride); G(0x8c, d->add_first); G(0xdc, 1);
#undef G
    memcpy(output, g, sizeof g);
    return HMISA_OK;
}

int hmisa_dma_encode(uint32_t enable, const struct hmisa_dma *d, void *out, size_t cap)
{
    uint32_t w[4], bank_bits, issue;
    uint8_t bytes[16];
    unsigned i;
    int r;
    if (enable != HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!out) return HMISA_E_ARGUMENT;
    if ((r = valid(d))) return r;
    if (cap < sizeof bytes) return HMISA_E_CAPACITY;
    if (overlap(d, sizeof *d, out, sizeof bytes)) return HMISA_E_ALIAS;
    bank_bits = d->address_bank == HMISA_SHARED ? 0 :
        d->address_bank == HMISA_HWTEMP ? 0x80000 : 0xc0000;
    issue = d->schedule.issue_index +
        (d->schedule.issue_kind == HMISA_ISSUE_SYNC ? 4u : 1u);
    w[0] = 0xe | 1u << 6 | issue << 8 | d->schedule.wait_desched << 11 |
        d->schedule.wait_sync << 14 | (d->access == HMISA_READ ? 5u : 4u) << 16;
    w[1] = 0x18000200 | bank_bits | d->address_index << 10;
    if (d->access == HMISA_READ) {
        w[1] |= 0x1e | (d->data_reg & 3) << 29;
        w[2] = 0x180 | d->data_reg >> 2;
    } else {
        w[0] |= (d->data_reg & 63) << 25;
        w[1] |= 0x18 | d->data_reg >> 6;
        w[2] = 0x1f0;
    }
    w[2] |= d->y_count << 9 | d->x_bytes << 21;
    /* Absent ROBUST argument is an explicit encoding (bank0/index0), not SH0. */
    w[3] = 0x83000000 | d->stride << 2 | d->add_first << 14;
    for (i = 0; i < 4; ++i) put32(bytes + i * 4, w[i]);
    memcpy(out, bytes, sizeof bytes);
    return HMISA_OK;
}

int hmisa_dma_from_descriptor(const uint32_t input[56], struct hmisa_dma *out)
{
    struct hmisa_dma d;
    uint32_t expected[56], g[56];
    int r;
    if (!input || !out) return HMISA_E_ARGUMENT;
    if (overlap(input, sizeof g, out, sizeof *out)) return HMISA_E_ALIAS;
    memcpy(g, input, sizeof g);
    if (g[0x40 / 4] != 4 && g[0x40 / 4] != 5) return HMISA_E_UNSUPPORTED;
    memset(&d, 0, sizeof d);
    d.access = g[0x40 / 4] == 5 ? HMISA_READ : HMISA_WRITE;
    d.data_reg = g[(d.access == HMISA_READ ? 0x70 : 0x50) / 4];
    d.address_bank = g[0x5c / 4]; d.address_index = g[0x60 / 4];
    d.y_count = g[0x78 / 4]; d.x_bytes = g[0x80 / 4];
    d.stride = g[0x88 / 4]; d.add_first = g[0x8c / 4];
    d.schedule.issue_kind = g[0x30 / 4]; d.schedule.issue_index = g[0x34 / 4];
    d.schedule.wait_desched = g[0x38 / 4]; d.schedule.wait_sync = g[0x3c / 4];
    if ((r = hmisa_dma_descriptor(&d, expected))) return r;
    if (memcmp(expected, g, sizeof g)) return HMISA_E_FORMAT;
    *out = d;
    return HMISA_OK;
}

int hmisa_dma_decode(const void *code, size_t n, struct hmisa_dma *out)
{
    const uint8_t *p = code;
    struct hmisa_dma d;
    uint32_t w[4], issue, tag;
    uint8_t expected[16];
    unsigned i;
    int r;
    if (!code || !out) return HMISA_E_ARGUMENT;
    if (n != 16) return HMISA_E_FORMAT;
    if (overlap(code, n, out, sizeof *out)) return HMISA_E_ALIAS;
    for (i = 0; i < 4; ++i) w[i] = get32(p + i * 4);
    memset(&d, 0, sizeof d);
    if (((w[0] >> 16) & 7) == 5) d.access = HMISA_READ;
    else if (((w[0] >> 16) & 7) == 4) d.access = HMISA_WRITE;
    else return HMISA_E_UNSUPPORTED;
    d.data_reg = d.access == HMISA_READ ?
        ((w[1] >> 29) & 3) | (w[2] & 63) << 2 :
        ((w[0] >> 25) & 63) | (w[1] & 3) << 6;
    tag = (w[1] >> 19) & 1;
    if (!tag) { d.address_bank = HMISA_SHARED; d.address_index = (w[1] >> 10) & 511; }
    else if (w[1] & 0x40000) {
        d.address_bank = HMISA_VERTEX_INPUT; d.address_index = (w[1] >> 10) & 127;
    } else { d.address_bank = HMISA_HWTEMP; d.address_index = (w[1] >> 10) & 255; }
    issue = (w[0] >> 8) & 7;
    if (issue >= 4 && issue <= 5) {
        d.schedule.issue_kind = HMISA_ISSUE_SYNC; d.schedule.issue_index = issue - 4;
    } else if (issue >= 1 && issue <= 3) {
        d.schedule.issue_kind = HMISA_ISSUE_DESCHED; d.schedule.issue_index = issue - 1;
    } else return HMISA_E_UNSUPPORTED;
    d.schedule.wait_desched = (w[0] >> 11) & 7;
    d.schedule.wait_sync = (w[0] >> 14) & 3;
    d.y_count = (w[2] >> 9) & 2047; d.x_bytes = (w[2] >> 21) & 511;
    d.stride = (w[3] >> 2) & 2047; d.add_first = (w[3] >> 14) & 1;
    /* Independent extraction; exact re-encoding checks every unrepresented bit,
     * absent robust argument, predicate, address offset, class and group length.
     * External whole-descriptor oracle tests catch encoder/inverse shared bugs.
     */
    if ((r = hmisa_dma_encode(HMISA_ENABLE_GROUPS, &d, expected, sizeof expected))) return r;
    if (memcmp(code, expected, sizeof expected)) return HMISA_E_FORMAT;
    *out = d;
    return HMISA_OK;
}

int hmisa_memory_lower(uint32_t enable, const struct hmisa_pointer *ptr,
    const struct hmisa_memory_request *req, uint32_t temps,
    const struct hmisa_schedule *schedule, struct hmisa_memory_product *out)
{
    struct hmisa_memory_product result;
    uint64_t delta;
    int r;
    if (enable != HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!ptr || !req || !schedule || !out) return HMISA_E_ARGUMENT;
    if (overlap(out, sizeof *out, ptr, sizeof *ptr) ||
        overlap(out, sizeof *out, req, sizeof *req) ||
        overlap(out, sizeof *out, schedule, sizeof *schedule)) return HMISA_E_ALIAS;
    if (req->reserved || req->binding != ptr->binding ||
        (req->access != HMISA_READ && req->access != HMISA_WRITE) ||
        !ptr->access || (ptr->access & ~3u) || (req->access & ptr->access) != req->access)
        return HMISA_E_ARGUMENT;
    if (ptr->bank != HMISA_SHARED && ptr->bank != HMISA_VERTEX_INPUT)
        return HMISA_E_UNSUPPORTED; /* no unproven temp-address/read alias rule */
    if (!temps || temps > 256 || req->value_reg >= temps) return HMISA_E_BOUNDS;
    if ((ptr->byte_origin & 3) || (req->byte_offset & 3) ||
        ptr->byte_origin > UINT64_MAX - ptr->bytes_available ||
        req->byte_offset < ptr->byte_origin) return HMISA_E_BOUNDS;
    delta = req->byte_offset - ptr->byte_origin;
    if (ptr->bytes_available < 4 || delta > ptr->bytes_available - 4 ||
        delta > 2044) return HMISA_E_BOUNDS;
    memset(&result, 0, sizeof result);
    result.dma.access = req->access; result.dma.data_reg = req->value_reg;
    result.dma.address_bank = ptr->bank; result.dma.address_index = ptr->index;
    result.dma.x_bytes = 4; result.dma.y_count = 1;
    /* The byte stride is added BEFORE the sole Y iteration. With zero offset
     * use ordinary stride1/ADD-FIRST0; never confuse stride0's special2048 form.
     */
    result.dma.add_first = delta != 0;
    result.dma.stride = delta ? (uint32_t)delta : 1;
    result.dma.schedule = *schedule;
    result.binding = req->binding; result.access = req->access;
    result.begin_byte = req->byte_offset; result.end_byte = req->byte_offset + 4;
    if ((r = hmisa_dma_encode(enable, &result.dma, result.code, sizeof result.code))) return r;
    *out = result;
    return HMISA_OK;
}

int hmisa_memory_lower_many(uint32_t enable, const struct hmisa_pointer *ptrs, size_t np,
    const struct hmisa_memory_request *reqs, const struct hmisa_schedule *schedules,
    size_t nr, uint32_t temps, struct hmisa_memory_product *out, size_t capacity)
{
    struct hmisa_memory_product results[HMISA_MAX_ACCESSES];
    size_t i, j;
    int r;
    if (enable != HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!ptrs || !reqs || !schedules || !out || !np || !nr ||
        np > HMISA_MAX_ACCESSES || nr > HMISA_MAX_ACCESSES) return HMISA_E_ARGUMENT;
    if (capacity < nr) return HMISA_E_CAPACITY;
    if (overlap(out, nr * sizeof *out, ptrs, np * sizeof *ptrs) ||
        overlap(out, nr * sizeof *out, reqs, nr * sizeof *reqs) ||
        overlap(out, nr * sizeof *out, schedules, nr * sizeof *schedules)) return HMISA_E_ALIAS;
    /* Ambiguous/aliased canonical pointer assignments must not select whichever
     * happens to appear first. Two distinct bindings cannot share the same pair.
     */
    for (i = 0; i < np; ++i) for (j = 0; j < i; ++j)
        if (ptrs[i].binding == ptrs[j].binding ||
            (ptrs[i].bank == ptrs[j].bank && ptrs[i].index == ptrs[j].index)) return HMISA_E_ALIAS;
    for (i = 0; i < nr; ++i) {
        for (j = 0; j < np && reqs[i].binding != ptrs[j].binding; ++j) {}
        if (j == np) return HMISA_E_ARGUMENT;
        r = hmisa_memory_lower(enable, &ptrs[j], &reqs[i], temps, &schedules[i], &results[i]);
        if (r) return r;
    }
    memcpy(out, results, nr * sizeof *out);
    return HMISA_OK;
}
