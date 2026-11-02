/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original internal compiler API.
 * No HMGU/HMUSC wire additions. See notes/CONSTRAINTS.md and PROVENANCE.md.
 */
#ifndef HM_ISA_PROGRAM_H
#define HM_ISA_PROGRAM_H
#include "hm_isa_air.h"
#ifdef __cplusplus
extern "C" {
#endif
#define HMISA_PROGRAM_BYTES (16u * HMISA_MAX_FRAGMENTS)
#define HMISA_PROGRAM_GROUPS HMISA_MAX_FRAGMENTS
#define HMISA_SH_MASK_WORDS 16u
enum hmisa_analysis_error {
    HMISA_E_DATAFLOW=-8, HMISA_E_SCHEDULE=-9
};
enum hmisa_group_kind { HMISA_RAW_DMA=1, HMISA_RAW_FOP=2, HMISA_RAW_CTRL=3 };
struct hmisa_raw_group {
    uint32_t kind, bytes;
    union { struct hmisa_dma dma; struct hmisa_fop fop; struct hmisa_ctrl ctrl; } u;
};
/* Independent prefix decoder. Consumes the first canonical group, never calls
 * an encoder/inverse; checks every bit and framing/extension length. Trailing
 * bytes belong to subsequent groups and are checked by program_analyze.
 * Unaligned code is supported. Output is unchanged on failure; no aliases.
 */
int hmisa_raw_decode(const void *,size_t,struct hmisa_raw_group *);
enum hmisa_obligation {
    HMISA_PROOF_END_RETIREMENT=1u, HMISA_PROOF_TAIL_PREFETCH=2u,
    HMISA_PROOF_FP_ENVIRONMENT=4u, HMISA_PROOF_LAUNCH_MAPPING=8u,
    HMISA_PROOF_COMMON_ORDER_RELEASE=16u, HMISA_MISSING_END=32u
};
struct hmisa_program_access {
    uint32_t group, code_offset, binding, access, bank, index;
    uint64_t displacement, begin_byte, end_byte;
};
struct hmisa_program_facts {
    uint32_t code_bytes, groups, end_count, obligations;
    uint32_t temps, unified_words, shared_words, input_index_high_water;
    uint32_t shared_read_mask[HMISA_SH_MASK_WORDS];
    uint32_t access_count, load_count, store_count, fop_count;
    uint32_t issue_desched_mask, issue_sync_mask, wait_desched_mask, wait_sync_mask;
    struct hmisa_program_access accesses[HMISA_MAX_ACCESSES];
};
/* Closed single-entry straight-line scalar-body analysis. Explicit assignments
 * are symbolic authorities; they establish no actual SH initialization, VA,
 * BO ownership or launch visibility. SH/vertex pointers accepted, temp-held
 * pointers refused until value provenance is implemented. Budgets are caller
 * limits, never claimed available hardware resources (temps<=256, SH<=512).
 *
 * Tracks async destination writes AND source reads through their exact issue
 * slots. Applies waits before uses/defs; prohibits reuse while work is pending.
 * Scalar DMA only, absent ROBUST, ordered memory operations. A terminal END is
 * allowed only as the last group with no pending work. EVERY byte is consumed;
 * bytes after END (even another END/zeros/NOP) refuse. Nonterminal bodies must
 * also have no pending work at their boundary. No END/tail bytes are invented.
 *
 * Success is STRUCTURAL FACTS ONLY and ALWAYS has proof obligations. It is NOT
 * hmsr_verify_stage_fn, an executable certificate, ready or compile_plan.
 * Output is transactional. Inputs/output must not overlap.
 */
int hmisa_program_analyze(const void *,size_t,const struct hmisa_pointer *,size_t,
    uint32_t temp_limit,uint32_t shared_limit,uint32_t input_limit,
    struct hmisa_program_facts *);
struct hmisa_layout_entry { uint32_t fragment,offset,bytes,kind,air_index; };
struct hmisa_stage_body {
    hm_air_info_t air;
    struct hmisa_program_facts facts;
    uint32_t entry_count;
    struct hmisa_layout_entry entries[HMISA_MAX_FRAGMENTS];
    uint8_t code[HMISA_PROGRAM_BYTES];
};
/* Link prepared fragments in their existing order; zero trailing allocation,
 * independently decode complete body, compare semantic memory records and
 * assignment high-water. DOES NOT append END/padding or authorize execution.
 * It rejects stale/tampered producer metadata instead of trusting it.
 */
int hmisa_stage_link(uint32_t,const struct hmisa_unlinked *,
    const struct hmisa_pointer *,size_t,uint32_t,uint32_t,uint32_t,
    struct hmisa_stage_body *);
/* Actual AIR -> allocator -> LD/FOP/ST/waits -> link -> raw analysis. In process,
 * no heap allocation/subprocess. Same explicit limits and non-executable result.
 */
int hmisa_air_link(uint32_t,const hm_air_program *,const struct hmisa_pointer *,size_t,
    uint32_t,uint32_t,uint32_t,struct hmisa_stage_body *);
#ifdef __cplusplus
}
#endif
#endif
