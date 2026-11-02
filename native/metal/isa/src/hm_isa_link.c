/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original native stage-body linker.
 * Reuses the immutable AIR/allocator/memory/ALU APIs; no END/tail policy guessed.
 */
#include "hm_isa_program.h"
#include <string.h>
static int overlap(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return an && bn && (x<=y?y-x<an:x-y<bn);
}
static int value(const struct hmisa_allocation *a,uint32_t id,uint32_t reg)
{
    if (a->value_count>HMISA_MAX_VALUES) return 0;
    for (uint32_t j=0;j<a->value_count;j++) if (a->values[j].id==id) return a->values[j].reg==reg;
    return 0;
}
int hmisa_stage_link(uint32_t enable,const struct hmisa_unlinked *u,
    const struct hmisa_pointer *p,size_t np,uint32_t temps,uint32_t shared,uint32_t inputs,
    struct hmisa_stage_body *out)
{
    struct hmisa_stage_body b; uint32_t offset=0,ma=0; int r;
    if (enable!=HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!u || !out || !p || !np || np>HMISA_MAX_ACCESSES) return HMISA_E_ARGUMENT;
    if (overlap(out,sizeof *out,u,sizeof *u)||overlap(out,sizeof *out,p,np*sizeof *p)) return HMISA_E_ALIAS;
    if (!u->fragment_count || u->fragment_count>HMISA_MAX_FRAGMENTS || u->reserved ||
        u->memory_count>HMISA_MAX_ACCESSES || u->unresolved!=31 || u->air.version!=1 ||
        u->air.instruction_count>HMISA_MAX_NODES || !u->air.instruction_count) return HMISA_E_FORMAT;
    memset(&b,0,sizeof b); b.air=u->air;
    for (uint32_t j=0;j<u->fragment_count;j++) {
        const struct hmisa_fragment *f=&u->fragments[j]; struct hmisa_raw_group g;
        if (!f->code_bytes || f->code_bytes>sizeof f->code || f->reserved ||
            f->air_index>=u->air.instruction_count || offset>HMISA_PROGRAM_BYTES-f->code_bytes) return HMISA_E_FORMAT;
        if ((r=hmisa_raw_decode(f->code,f->code_bytes,&g))) return r;
        if (g.bytes!=f->code_bytes || g.kind!=f->kind) return HMISA_E_FORMAT;
        if (g.kind==HMISA_RAW_CTRL) {
            if (g.u.ctrl.op!=HMISA_NOP || f->value_id!=HMISA_NO_VALUE ||
                f->value_reg!=HMISA_NO_VALUE || f->binding!=HM_AIR_NONE ||
                f->access || f->begin_byte || f->end_byte) return HMISA_E_FORMAT;
        } else {
            if (!value(&u->allocation,f->value_id,f->value_reg)) return HMISA_E_FORMAT;
            if (g.kind==HMISA_RAW_DMA) {
                if (g.u.dma.data_reg!=f->value_reg || g.u.dma.access!=f->access) return HMISA_E_FORMAT;
            } else if (g.u.fop.dst!=f->value_reg || f->binding!=HM_AIR_NONE ||
                f->access || f->begin_byte || f->end_byte) return HMISA_E_FORMAT;
        }
        b.entries[j]=(struct hmisa_layout_entry){j,offset,f->code_bytes,f->kind,f->air_index};
        memcpy(b.code+offset,f->code,f->code_bytes); offset+=f->code_bytes;
    }
    if ((r=hmisa_program_analyze(b.code,offset,p,np,temps,shared,inputs,&b.facts))) return r;
    if (b.facts.end_count || b.facts.temps!=u->allocation.high_water ||
        b.facts.access_count!=u->memory_count) return HMISA_E_FORMAT;
    for (uint32_t j=0;j<u->fragment_count;j++) {
        const struct hmisa_fragment *f=&u->fragments[j];
        if (f->kind!=HMISA_FRAGMENT_DMA) continue;
        const struct hmisa_program_access *a=&b.facts.accesses[ma++];
        if (a->code_offset!=b.entries[j].offset || a->binding!=f->binding ||
            a->access!=f->access || a->begin_byte!=f->begin_byte || a->end_byte!=f->end_byte) return HMISA_E_FORMAT;
    }
    b.entry_count=u->fragment_count; *out=b; return HMISA_OK;
}
int hmisa_air_link(uint32_t enable,const hm_air_program *program,const struct hmisa_pointer *p,size_t np,
    uint32_t temps,uint32_t shared,uint32_t inputs,struct hmisa_stage_body *out)
{
    struct hmisa_unlinked u; int r;
    if (!out || !p || !np || np>HMISA_MAX_ACCESSES) return HMISA_E_ARGUMENT;
    if (overlap(out,sizeof *out,p,np*sizeof *p)) return HMISA_E_ALIAS;
    r=hmisa_air_prepare(enable,program,p,np,temps,&u);
    return r?r:hmisa_stage_link(enable,&u,p,np,temps,shared,inputs,out);
}
