/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original native AIR/ISA composition.
 * AIR dependency retains its peer-selected LGPL terms; no parser is copied.
 */
#ifndef HM_ISA_AIR_H
#define HM_ISA_AIR_H
#include "hm_isa_alloc.h"
#include "hm_air.h"
#ifdef __cplusplus
extern "C" {
#endif
#define HMISA_MAX_FRAGMENTS (2u*HMISA_MAX_NODES)
enum hmisa_fragment_kind { HMISA_FRAGMENT_DMA=1,HMISA_FRAGMENT_FOP=2,HMISA_FRAGMENT_WAIT=3 };
enum hmisa_unresolved {
    HMISA_NEEDS_END_RETIREMENT=1u,HMISA_NEEDS_TAIL_PADDING=2u,
    HMISA_NEEDS_FP_ENVIRONMENT=4u,HMISA_NEEDS_LAUNCH_RESOURCES=8u,
    HMISA_NEEDS_COMMON_ORDER=16u
};
struct hmisa_fragment {
    uint32_t air_index,kind,code_bytes,value_id,value_reg,binding,access,reserved;
    uint64_t begin_byte,end_byte;
    uint8_t code[16];
};
struct hmisa_unlinked {
    hm_air_info_t air; /* exact unchanged source/FP metadata */
    struct hmisa_allocation allocation;
    uint32_t fragment_count,memory_count,unresolved,reserved;
    struct hmisa_fragment fragments[HMISA_MAX_FRAGMENTS];
};
/* Real in-process parser access + allocation + memory/FOP/wait encoding.
 * One static invocation; f32 LOAD/ADD/SUB/MUL/one STORE/RETURN, <=64 AIR nodes,
 * <=16 memory accesses. CONSTANT/gid.x/unknown schema/mode fields refuse.
 * Every producer is followed by explicit same-namespace NOP wait before the
 * next node. No overlapping issue slots or read-instruction register reuse.
 *
 * Success returns UNLINKED FRAGMENTS, never a shader/ready/HAS_CODE result.
 * No END/padding is appended. unresolved is ALWAYS nonzero. This cannot be a
 * Metal compile_plan or streams validate_usc callback. No GPU VA is invented.
 * Canonical bank7 pointer pairs and caller budget are explicit external inputs;
 * hardware initialization/allocation/retirement must be proved elsewhere.
 * No heap allocation or partial outputs; disjoint output required. */
int hmisa_air_prepare(uint32_t enable,const hm_air_program *,
    const struct hmisa_pointer *,size_t,uint32_t budget,struct hmisa_unlinked *);
#ifdef __cplusplus
}
#endif
#endif
