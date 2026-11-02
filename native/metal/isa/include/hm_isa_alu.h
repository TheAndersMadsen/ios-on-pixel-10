/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original DXT71 native scalar ALU/control API. See notes/SEMANTICS.md.
 */
#ifndef HM_ISA_ALU_H
#define HM_ISA_ALU_H
#include "hm_isa_memory.h" /* immutable isa-r2 API; no second status/wire ABI */
#ifdef __cplusplus
extern "C" {
#endif
enum hmisa_fop_op { HMISA_FADD=2, HMISA_FSUB=3, HMISA_FMUL=4 };
#define HMISA_ISSUE_NONE 2u
struct hmisa_fop {
    uint32_t op,dst,lhs,rhs;
    struct hmisa_schedule schedule;
};
enum hmisa_ctrl_op { HMISA_NOP=10, HMISA_END=12 };
struct hmisa_ctrl { uint32_t op,wait_desched,wait_sync; };
/* Raw group encoding facts, NOT full-stage or floating-point conformance.
 * All outputs, including *written, remain unchanged on every failure. Output
 * regions must be disjoint from inputs and one another. Unaligned code is OK.
 * FOP rhs <=127 for multiply; other indices <=255. Caller owns resource limits.
 * NOP supports both wait namespaces. END cannot encode a desched wait here.
 */
int hmisa_fop_descriptor(const struct hmisa_fop *,uint32_t descriptor[56]);
int hmisa_fop_encode(uint32_t enable,const struct hmisa_fop *,void *,size_t,size_t *written);
int hmisa_fop_from_descriptor(const uint32_t descriptor[56],struct hmisa_fop *);
int hmisa_fop_decode(const void *,size_t,struct hmisa_fop *);
int hmisa_ctrl_descriptor(const struct hmisa_ctrl *,uint32_t descriptor[56]);
int hmisa_ctrl_encode(uint32_t enable,const struct hmisa_ctrl *,void *,size_t,size_t *written);
int hmisa_ctrl_from_descriptor(const uint32_t descriptor[56],struct hmisa_ctrl *);
int hmisa_ctrl_decode(const void *,size_t,struct hmisa_ctrl *);
#ifdef __cplusplus
}
#endif
#endif
