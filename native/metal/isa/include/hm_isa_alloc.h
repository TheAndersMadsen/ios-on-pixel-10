/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original bounded SSA allocator.
 */
#ifndef HM_ISA_ALLOC_H
#define HM_ISA_ALLOC_H
#include "hm_isa_alu.h"
#ifdef __cplusplus
extern "C" {
#endif
#define HMISA_MAX_VALUES 64u
#define HMISA_MAX_NODES 64u
#define HMISA_NO_VALUE UINT32_MAX
#define HMISA_SSA_LOAD 1u
#define HMISA_SSA_USE 5u
struct hmisa_input { uint32_t id,reg; };
/* LOAD: no sources, allocates a value. USE: id=NONE,rhs=NONE, reads lhs.
 * FADD/SUB/MUL: allocates id, reads lhs/rhs. IDs need not be dense. */
struct hmisa_node { uint32_t id,op,lhs,rhs; };
struct hmisa_assignment { uint32_t id,reg; int32_t definition,last_use; };
struct hmisa_allocation {
    uint32_t value_count,node_count,high_water,peak_live;
    struct hmisa_assignment values[HMISA_MAX_VALUES];
    uint32_t node_reg[HMISA_MAX_NODES];
};
/* No spilling, hidden inputs or caller mutation. Caller budget1..128 is an
 * encoding-profile restriction (multiply SRC1), not measured task capacity.
 * Sources cannot alias the destination at their last read. Reuse starts in a
 * LATER node. A physical producer must separately wait for asynchronous work
 * BEFORE advancing the allocator's node boundary. hmisa_air_prepare does so.
 */
int hmisa_allocate(uint32_t enable,const struct hmisa_input *,size_t,
    const struct hmisa_node *,size_t,const uint32_t *live_out,size_t,
    uint32_t budget,struct hmisa_allocation *);
#ifdef __cplusplus
}
#endif
#endif
