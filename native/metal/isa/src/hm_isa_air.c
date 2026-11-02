/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original native composition using immutable AIR-r2 and ISA-r2 C APIs.
 */
#include "hm_isa_air.h"
#include <string.h>
_Static_assert(HM_AIR_LOAD==HMISA_SSA_LOAD && HM_AIR_STORE==HMISA_SSA_USE,"AIR op mapping");
_Static_assert((int)HM_AIR_FADD==(int)HMISA_FADD && (int)HM_AIR_FSUB==(int)HMISA_FSUB &&
    (int)HM_AIR_FMUL==(int)HMISA_FMUL,"AIR ALU mapping");
static int overlaps(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t av=(uintptr_t)a,bv=(uintptr_t)b;
    return an && bn && (av<=bv?bv-av<an:av-bv<bn);
}
static uint32_t regof(const struct hmisa_allocation *a,uint32_t id)
{
    for (uint32_t j=0;j<a->value_count;j++) if (a->values[j].id==id) return a->values[j].reg;
    return HMISA_NO_VALUE;
}
int hmisa_air_prepare(uint32_t enable,const hm_air_program *program,
    const struct hmisa_pointer *ptrs,size_t np,uint32_t budget,struct hmisa_unlinked *output)
{
    struct hmisa_unlinked u; hm_air_instruction_t inst[HMISA_MAX_NODES];
    hm_air_buffer_t buffers[HMISA_MAX_ACCESSES]; struct hmisa_node nodes[HMISA_MAX_NODES];
    struct hmisa_schedule dma_schedule={HMISA_ISSUE_DESCHED,0,0,0};
    struct hmisa_schedule fop_schedule={HMISA_ISSUE_SYNC,0,0,0};
    uint32_t i,j,stores=0,loads=0; int r;
    if (enable!=HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!program || !ptrs || !output || !np || np>HMISA_MAX_ACCESSES) return HMISA_E_ARGUMENT;
    if (overlaps(ptrs,np*sizeof *ptrs,output,sizeof *output)) return HMISA_E_ALIAS;
    memset(&u,0,sizeof u);
    if (hm_air_info(program,&u.air)!=HM_AIR_OK) return HMISA_E_ARGUMENT;
    if (u.air.version!=1 || u.air.reserved || u.air.pointer_bits!=64 || u.air.uses_grid_x ||
        u.air.contraction || u.air.rounding_rne!=1 || u.air.denorm_mode>1 ||
        u.air.instruction_count<3 || u.air.instruction_count>HMISA_MAX_NODES ||
        u.air.buffer_count!=np) return HMISA_E_UNSUPPORTED;
    /* SH is the established PDS shared-store route. Bank5 input numbering is
     * still unresolved for complete stages. Raw memory codec keeps all banks. */
    for (i=0;i<np;i++) {
        if (hm_air_buffer(program,i,&buffers[i])!=HM_AIR_OK) return HMISA_E_ARGUMENT;
        if (buffers[i].binding>30 || !buffers[i].access || buffers[i].access>3 ||
            (buffers[i].address_space!=1 && buffers[i].address_space!=2) ||
            (buffers[i].address_space==2 && buffers[i].access!=HMISA_READ) ||
            buffers[i].alignment<4 || (buffers[i].alignment&(buffers[i].alignment-1)))
            return HMISA_E_UNSUPPORTED;
        for (j=0;j<i;j++) if (buffers[j].binding==buffers[i].binding ||
            buffers[j].argument==buffers[i].argument) return HMISA_E_ALIAS;
    }
    for (i=0;i<np;i++) {
        if (ptrs[i].bank!=HMISA_SHARED || (ptrs[i].index&1) || ptrs[i].index>510)
            return HMISA_E_UNSUPPORTED;
        for (j=0;j<i;j++) if (ptrs[i].binding==ptrs[j].binding || ptrs[i].index==ptrs[j].index)
            return HMISA_E_ALIAS;
        for (j=0;j<np && buffers[j].binding!=ptrs[i].binding;j++) {}
        if (j==np || ptrs[i].access!=buffers[j].access) return HMISA_E_ARGUMENT;
    }
    /* Copy and validate the complete typed plan. No reordering across memory,
     * substitution of constants, metadata erasure or partial output on failure. */
    for (i=0;i<u.air.instruction_count;i++) {
        hm_air_instruction_t *s=&inst[i];
        if (hm_air_instruction(program,i,s)!=HM_AIR_OK) return HMISA_E_ARGUMENT;
        if (s->id!=i || s->reserved || s->constant_bits || s->thread_stride) return HMISA_E_UNSUPPORTED;
        if (s->opcode==HM_AIR_LOAD || s->opcode==HM_AIR_STORE) {
            if (stores || s->alignment<4 || (s->alignment&(s->alignment-1)) ||
                (s->byte_offset&3) || s->rhs!=HM_AIR_NONE ||
                (s->opcode==HM_AIR_LOAD && s->lhs!=HM_AIR_NONE) ||
                (s->opcode==HM_AIR_STORE && s->lhs==HM_AIR_NONE)) return HMISA_E_UNSUPPORTED;
            for (j=0;j<np && buffers[j].binding!=s->binding;j++) {}
            if (j==np || !(buffers[j].access&(s->opcode==HM_AIR_LOAD?1u:2u))) return HMISA_E_ARGUMENT;
            u.memory_count++; if (u.memory_count>HMISA_MAX_ACCESSES) return HMISA_E_CAPACITY;
            if (s->opcode==HM_AIR_LOAD) loads++; else stores++;
        } else {
            if (s->binding!=HM_AIR_NONE || s->alignment || s->byte_offset) return HMISA_E_UNSUPPORTED;
            if (s->opcode==HM_AIR_RETURN) {
                if (i+1!=u.air.instruction_count || stores!=1 || !loads ||
                    s->lhs!=HM_AIR_NONE || s->rhs!=HM_AIR_NONE) return HMISA_E_UNSUPPORTED;
                continue;
            }
            if (stores || (s->opcode!=HM_AIR_FADD && s->opcode!=HM_AIR_FSUB && s->opcode!=HM_AIR_FMUL))
                return HMISA_E_UNSUPPORTED;
        }
        nodes[i]=(struct hmisa_node){s->opcode==HM_AIR_STORE?HMISA_NO_VALUE:s->id,s->opcode,s->lhs,s->rhs};
    }
    if (inst[u.air.instruction_count-1].opcode!=HM_AIR_RETURN) return HMISA_E_UNSUPPORTED;
    r=hmisa_allocate(enable,NULL,0,nodes,u.air.instruction_count-1,NULL,0,budget,&u.allocation);
    if (r) return r;
    for (i=0;i+1<u.air.instruction_count;i++) {
        hm_air_instruction_t *s=&inst[i]; struct hmisa_ctrl wait={HMISA_NOP,0,0}; size_t n=0;
        struct hmisa_fragment *f=&u.fragments[u.fragment_count++];
        f->air_index=i; f->value_id=s->opcode==HM_AIR_STORE?s->lhs:s->id;
        f->value_reg=u.allocation.node_reg[i]; f->binding=HM_AIR_NONE;
        if (s->opcode==HM_AIR_LOAD || s->opcode==HM_AIR_STORE) {
            struct hmisa_memory_product product;
            struct hmisa_memory_request req={s->binding,s->opcode==HM_AIR_LOAD?1u:2u,f->value_reg,0,s->byte_offset};
            for (j=0;j<np && ptrs[j].binding!=s->binding;j++) {}
            if (j==np) return HMISA_E_ARGUMENT;
            r=hmisa_memory_lower(enable,&ptrs[j],&req,budget,&dma_schedule,&product);
            if (r) return r;
            f->kind=HMISA_FRAGMENT_DMA; f->code_bytes=HMISA_DMA_BYTES;
            memcpy(f->code,product.code,sizeof product.code);
            f->binding=product.binding; f->access=product.access;
            f->begin_byte=product.begin_byte; f->end_byte=product.end_byte;
            wait.wait_desched=1; /* never reuse pending DMA issue0 or its value */
        } else {
            struct hmisa_fop op={s->opcode,f->value_reg,regof(&u.allocation,s->lhs),regof(&u.allocation,s->rhs),fop_schedule};
            if ((r=hmisa_fop_encode(enable,&op,f->code,sizeof f->code,&n))) return r;
            f->kind=HMISA_FRAGMENT_FOP; f->code_bytes=(uint32_t)n; wait.wait_sync=1;
        }
        /* This explicit wait is part of the emitted fragment sequence. It is
         * not a host assertion that the GPU executed/retired anything. */
        f=&u.fragments[u.fragment_count++]; f->kind=HMISA_FRAGMENT_WAIT;
        f->air_index=i; f->value_id=HMISA_NO_VALUE; f->value_reg=HMISA_NO_VALUE; f->binding=HM_AIR_NONE;
        if ((r=hmisa_ctrl_encode(enable,&wait,f->code,sizeof f->code,&n))) return r;
        f->code_bytes=(uint32_t)n;
    }
    u.unresolved=HMISA_NEEDS_END_RETIREMENT|HMISA_NEEDS_TAIL_PADDING|HMISA_NEEDS_FP_ENVIRONMENT|
        HMISA_NEEDS_LAUNCH_RESOURCES|HMISA_NEEDS_COMMON_ORDER;
    *output=u; return HMISA_OK;
}
