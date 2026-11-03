/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors
 * Original diagnostic implementation; normal DDK layout/enum facts only.
 * No firmware or vendor driver implementation copied. PROVENANCE.md.
 */
#if defined(BLAZER) && BLAZER && defined(BLAZER_GPU_FW_DIAGNOSTIC) && BLAZER_GPU_FW_DIAGNOSTIC
#include "hmfw_diagnostic.h"
#include "hmfw_vendor_layout.h"
#include "blazer_gpu_fwif.h"
#if defined(KERNEL)
#include <sys/systm.h>
#else
#include <stdio.h>
#endif

static int range(uint32_t off, uint32_t size, uint32_t bytes)
{
    return !(off & 3) && off <= bytes && size <= bytes - off;
}
int hmfd_capture(const struct hmfd_reader *r, const struct hmfd_layout *l, struct hmfd_snapshot *s)
{
    if (!s) return HMFD_INVALID;
    *s = (struct hmfd_snapshot){0};
    s->result = HMFD_INVALID;
    if (!r || !r->read32 || !l || l->slots != (1u << GF_FWCCB_LOG2) ||
        GF_SZ_RGXFWIF_FWCCB_CMD != HMFV_FC_BYTES || GF_SZ_RGXFWIF_FWCCB_CMD != HMFD_WORDS*4 ||
        !range(l->fctl, GF_SZ_RGXFWIF_CCB_CTL, l->bytes) ||
        !range(l->fccb, l->slots * GF_SZ_RGXFWIF_FWCCB_CMD, l->bytes) ||
        ((uint64_t)l->fctl < (uint64_t)l->fccb + l->slots * GF_SZ_RGXFWIF_FWCCB_CMD &&
         (uint64_t)l->fccb < (uint64_t)l->fctl + GF_SZ_RGXFWIF_CCB_CTL)) return HMFD_INVALID;
#define READ(off, out) do { if (r->read32(r->ctx, (off), &(out))) { s->result = HMFD_IO; return HMFD_IO; } } while (0)
    READ(l->fctl + GF_CCB_W, s->write); READ(l->fctl + GF_CCB_R, s->read); READ(l->fctl + GF_CCB_MASK, s->mask);
    if (s->mask != l->slots - 1 || s->write >= l->slots || s->read >= l->slots) return HMFD_INVALID;
    s->pending = (s->write - s->read) & s->mask;
    s->truncated = s->pending > HMFD_MAX_ENTRIES;
    const uint32_t count = s->truncated ? HMFD_MAX_ENTRIES : s->pending;
    for (uint32_t i = 0; i < count; i++) {
        struct hmfd_entry *e = &s->entries[i];
        e->slot = (s->read + i) & s->mask;
        uint32_t off = l->fccb + e->slot * GF_SZ_RGXFWIF_FWCCB_CMD;
        /* Capture the WHOLE entry before decoding. A producer racing this
         * read is reported by the second control sample, never hidden. */
        for (uint32_t j = 0; j < HMFD_WORDS; j++) READ(off + j*4, e->words[j]);
        s->captured++;
    }
    READ(l->fctl + GF_CCB_W, s->write_after); READ(l->fctl + GF_CCB_R, s->read_after); READ(l->fctl + GF_CCB_MASK, s->mask_after);
#undef READ
    s->result = s->write == s->write_after && s->read == s->read_after && s->mask == s->mask_after ? HMFD_OK : HMFD_RACED;
    return (int)s->result;
}
const char *hmfd_command_name(uint32_t type)
{
    switch (type) {
    case HMFV_FC_ZS_BACK: return "ZSBUFFER_BACKING";
    case HMFV_FC_ZS_UNBACK: return "ZSBUFFER_UNBACKING";
    case HMFV_FC_FREELIST_GROW: return "FREELIST_GROW";
    case HMFV_FC_FREELIST_RECON: return "FREELISTS_RECONSTRUCTION";
    case HMFV_FC_CONTEXT_RESET: return "CONTEXT_RESET_NOTIFICATION";
    case HMFV_FC_DEBUG_DUMP: return "DEBUG_DUMP";
    case HMFV_FC_UPDATE_STATS: return "UPDATE_STATS";
    case HMFV_FC_CLK_CHANGE: return "CORE_CLK_RATE_CHANGE";
    case HMFV_FC_RESTART: return "REQUEST_GPU_RESTART";
    case HMFV_FC_PAGEFAULT: return "CONTEXT_FW_PF_NOTIFICATION";
    default: return "UNKNOWN_UNACKNOWLEDGED";
    }
}
static uint64_t word64(const struct hmfd_entry *e, uint32_t off)
{
    return (uint64_t)e->words[off/4] | (uint64_t)e->words[off/4+1] << 32;
}
void hmfd_dump(const struct hmfd_snapshot *s, const char *reason)
{
    if (!s) return;
    printf("HK GPUTA DIAG: %s result=%u FWCCB w=%u r=%u mask=0x%x after=%u/%u/0x%x pending=%u captured=%u truncated=%u; read-only/no-ack\n",
        reason ? reason : "unspecified", s->result, s->write, s->read, s->mask,
        s->write_after, s->read_after, s->mask_after, s->pending, s->captured, s->truncated);
    for (uint32_t i = 0; i < s->captured && i < HMFD_MAX_ENTRIES; i++) {
        const struct hmfd_entry *e = &s->entries[i];
        const uint32_t type = e->words[HMFV_FC_TYPE/4];
        printf("HK GPUTA DIAG: slot=%u type=0x%x name=%s flags=0x%x (uninterpreted)\n",
            e->slot, type, hmfd_command_name(type), e->words[HMFV_FC_FLAGS/4]);
        for (uint32_t j = 0; j < HMFD_WORDS; j += 4)
            printf("HK GPUTA DIAG: raw[%02u]=%08x %08x %08x %08x\n", j,
                e->words[j], e->words[j+1], e->words[j+2], e->words[j+3]);
        if (e->words[HMFV_FC_FLAGS/4] != 0) {
            printf("HK GPUTA DIAG: payload decode unavailable: unknown nonzero FWCCB flags; raw retained/no-ack\n");
            continue;
        }
        switch (type) {
        case HMFV_FC_ZS_BACK: case HMFV_FC_ZS_UNBACK:
            printf("HK GPUTA DIAG: zs_buffer_id=%u\n", e->words[HMFV_FC_ZS_ID/4]); break;
        case HMFV_FC_FREELIST_GROW:
            printf("HK GPUTA DIAG: freelist_id=0x%llx\n", (unsigned long long)word64(e, HMFV_FC_FREELIST_ID)); break;
        case HMFV_FC_FREELIST_RECON:
            printf("HK GPUTA DIAG: reconstruction count=%u hwr=%u (raw IDs above; no follow)\n",
                e->words[HMFV_FC_RECON_COUNT/4], e->words[HMFV_FC_RECON_HWR/4]); break;
        case HMFV_FC_CONTEXT_RESET:
            printf("HK GPUTA DIAG: reset context=%u reason=%u dm=%u job=%u flags=0x%x\n",
                e->words[HMFV_FC_RESET_CONTEXT/4], e->words[HMFV_FC_RESET_REASON/4],
                e->words[HMFV_FC_RESET_DM/4], e->words[HMFV_FC_RESET_JOB/4], e->words[HMFV_FC_RESET_FLAGS/4]); break;
        case HMFV_FC_UPDATE_STATS:
            printf("HK GPUTA DIAG: stats element=%u pid=%u adjustment=%d\n", e->words[HMFV_FC_STATS_ELEMENT/4],
                e->words[HMFV_FC_STATS_PID/4], (int32_t)e->words[HMFV_FC_STATS_ADJUST/4]); break;
        case HMFV_FC_CLK_CHANGE:
            printf("HK GPUTA DIAG: requested core_clock_hz=%u (not applied)\n", e->words[HMFV_FC_CORE_HZ/4]); break;
        case HMFV_FC_PAGEFAULT:
            printf("HK GPUTA DIAG: fw_fault_addr=0x%llx (not dereferenced)\n",
                (unsigned long long)word64(e, HMFV_FC_PAGEFAULT_ADDR)); break;
        default: break;
        }
    }
}
#endif
