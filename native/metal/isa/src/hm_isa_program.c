/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original whole-program analysis.
 * Structural dependency/resource facts only; no GPU/runtime proof supplied.
 */
#include "hm_isa_program.h"
#include <string.h>
struct slot {
    uint8_t active,memory,reads[256],writes[256];
};
struct state { uint8_t defined[256]; struct slot slots[5]; };
static int overlap(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return an && bn && (x<=y?y-x<an:x-y<bn);
}
static uint32_t max(uint32_t a,uint32_t b) { return a>b?a:b; }
static int pointers(const struct hmisa_pointer *p,size_t n,uint32_t sh,uint32_t in)
{
    for (size_t j=0;j<n;j++) {
        uint32_t words=2;
        if (!p[j].access || p[j].access>3 || p[j].binding>30) return HMISA_E_ARGUMENT;
        if (p[j].bank==HMISA_SHARED) {
            if ((p[j].index&1u) || p[j].index>510 || p[j].index+words>sh) return HMISA_E_BOUNDS;
        } else if (p[j].bank==HMISA_VERTEX_INPUT) {
            /* Bank5 canonical index is NOT assigned a two-word SH/PDS meaning.
             * Bounds are its own operand index high-water only. */
            words=1;
            if (p[j].index>127 || p[j].index+words>in) return HMISA_E_BOUNDS;
        } else return HMISA_E_UNSUPPORTED;
        if ((p[j].byte_origin&3u) || p[j].bytes_available<4 ||
            p[j].bytes_available>UINT64_MAX-p[j].byte_origin) return HMISA_E_BOUNDS;
        for (size_t k=0;k<j;k++) {
            uint32_t kw=p[k].bank==HMISA_SHARED?2u:1u;
            if (p[j].binding==p[k].binding || (p[j].bank==p[k].bank &&
                p[j].index<p[k].index+kw && p[k].index<p[j].index+words)) return HMISA_E_ALIAS;
        }
    }
    return HMISA_OK;
}
static void waits(struct state *s,uint32_t wd,uint32_t ws,struct hmisa_program_facts *f)
{
    f->wait_desched_mask|=wd; f->wait_sync_mask|=ws;
    for (unsigned j=0;j<5;j++)
        if ((j<3 && (wd&(1u<<j))) || (j>=3 && (ws&(1u<<(j-3)))))
            memset(&s->slots[j],0,sizeof s->slots[j]);
}
static int readable(const struct state *s,uint32_t reg,uint32_t limit)
{
    if (reg>=limit) return HMISA_E_BOUNDS;
    if (!s->defined[reg]) return HMISA_E_DATAFLOW;
    for (unsigned j=0;j<5;j++) if (s->slots[j].active && s->slots[j].writes[reg]) return HMISA_E_SCHEDULE;
    return HMISA_OK;
}
static int writable(const struct state *s,uint32_t reg,uint32_t limit)
{
    if (reg>=limit) return HMISA_E_BOUNDS;
    for (unsigned j=0;j<5;j++) if (s->slots[j].active &&
        (s->slots[j].reads[reg] || s->slots[j].writes[reg])) return HMISA_E_SCHEDULE;
    return HMISA_OK;
}
static int issue(const struct state *s,const struct hmisa_schedule *q,uint32_t *slot)
{
    if (q->issue_kind==HMISA_ISSUE_DESCHED && q->issue_index<3) *slot=q->issue_index;
    else if (q->issue_kind==HMISA_ISSUE_SYNC && q->issue_index<2) *slot=3+q->issue_index;
    else return HMISA_E_UNSUPPORTED; /* NONE latency/dependencies unresolved */
    if (s->slots[*slot].active) return HMISA_E_SCHEDULE;
    return HMISA_OK;
}
static int memory(const struct hmisa_dma *d,const struct hmisa_pointer *p,size_t np,
    struct hmisa_program_facts *f)
{
    const struct hmisa_pointer *ptr=NULL; struct hmisa_program_access a={0};
    if (d->x_bytes!=4 || d->y_count!=1 || (!d->add_first && d->stride!=1) ||
        (d->add_first && (!d->stride || (d->stride&3u) || d->stride>2044))) return HMISA_E_UNSUPPORTED;
    if (d->address_bank==HMISA_HWTEMP) return HMISA_E_UNSUPPORTED;
    for (size_t j=0;j<np;j++) if (p[j].bank==d->address_bank && p[j].index==d->address_index) ptr=&p[j];
    if (!ptr) return HMISA_E_ARGUMENT;
    a.displacement=d->add_first?d->stride:0;
    if (!(ptr->access&d->access)) return HMISA_E_ARGUMENT;
    if (a.displacement>ptr->bytes_available-4) return HMISA_E_BOUNDS;
    if (f->access_count==HMISA_MAX_ACCESSES) return HMISA_E_CAPACITY;
    a.group=f->groups; a.code_offset=f->code_bytes; a.binding=ptr->binding;
    a.access=d->access; a.bank=d->address_bank; a.index=d->address_index;
    a.begin_byte=ptr->byte_origin+a.displacement; a.end_byte=a.begin_byte+4;
    f->accesses[f->access_count++]=a;
    if (d->address_bank==HMISA_SHARED) {
        f->shared_words=max(f->shared_words,d->address_index+2);
        for (unsigned j=0;j<2;j++) {
            uint32_t v=d->address_index+j;
            f->shared_read_mask[v/32]|=1u<<(v%32);
        }
    } else f->input_index_high_water=max(f->input_index_high_water,d->address_index+1);
    if (d->access==HMISA_READ) f->load_count++; else f->store_count++;
    return HMISA_OK;
}
int hmisa_program_analyze(const void *code,size_t bytes,const struct hmisa_pointer *p,size_t np,
    uint32_t temp_limit,uint32_t shared_limit,uint32_t input_limit,struct hmisa_program_facts *out)
{
    struct hmisa_program_facts f; struct state s; int r;
    if (!code || !out || (np && !p) || np>HMISA_MAX_ACCESSES) return HMISA_E_ARGUMENT;
    if (overlap(code,bytes,out,sizeof *out)||overlap(p,np*sizeof *p,out,sizeof *out)) return HMISA_E_ALIAS;
    if (!bytes || bytes>HMISA_PROGRAM_BYTES || (bytes&3u) || !temp_limit ||
        temp_limit>256 || shared_limit>512 || input_limit>128) return HMISA_E_BOUNDS;
    if ((r=pointers(p,np,shared_limit,input_limit))) return r;
    memset(&f,0,sizeof f); memset(&s,0,sizeof s);
    while (f.code_bytes<bytes) {
        struct hmisa_raw_group g; struct hmisa_schedule q; uint32_t k;
        if (f.groups==HMISA_PROGRAM_GROUPS) return HMISA_E_CAPACITY;
        if ((r=hmisa_raw_decode((const uint8_t *)code+f.code_bytes,bytes-f.code_bytes,&g))) return r;
        if (g.kind==HMISA_RAW_CTRL) {
            waits(&s,g.u.ctrl.wait_desched,g.u.ctrl.wait_sync,&f);
            if (g.u.ctrl.op==HMISA_END) {
                if ((size_t)f.code_bytes+g.bytes!=bytes) return HMISA_E_FORMAT;
                f.end_count++;
            }
        } else {
            q=g.kind==HMISA_RAW_DMA?g.u.dma.schedule:g.u.fop.schedule;
            waits(&s,q.wait_desched,q.wait_sync,&f);
            if ((r=issue(&s,&q,&k))) return r;
            if (g.kind==HMISA_RAW_DMA) {
                const struct hmisa_dma *d=&g.u.dma;
                /* Conservative ordered-memory profile. Different pointer
                 * bindings do not prove nonaliasing of actual GPU VAs. */
                for (unsigned j=0;j<5;j++) if (s.slots[j].active && s.slots[j].memory) return HMISA_E_SCHEDULE;
                if ((r=memory(d,p,np,&f))) return r;
                if (d->access==HMISA_READ) {
                    if ((r=writable(&s,d->data_reg,temp_limit))) return r;
                    s.defined[d->data_reg]=1; s.slots[k].writes[d->data_reg]=1;
                } else {
                    if ((r=readable(&s,d->data_reg,temp_limit))) return r;
                    s.slots[k].reads[d->data_reg]=1;
                }
                f.temps=max(f.temps,d->data_reg+1); s.slots[k].memory=1;
            } else {
                const struct hmisa_fop *v=&g.u.fop;
                if ((r=readable(&s,v->lhs,temp_limit)) || (r=readable(&s,v->rhs,temp_limit)) ||
                    (r=writable(&s,v->dst,temp_limit))) return r;
                if (v->dst==v->lhs || v->dst==v->rhs) return HMISA_E_ALIAS;
                s.defined[v->dst]=1; s.slots[k].writes[v->dst]=1;
                s.slots[k].reads[v->lhs]=1; s.slots[k].reads[v->rhs]=1;
                f.temps=max(f.temps,max(v->dst,max(v->lhs,v->rhs))+1); f.fop_count++;
            }
            s.slots[k].active=1;
            if (k<3) f.issue_desched_mask|=1u<<k; else f.issue_sync_mask|=1u<<(k-3);
        }
        f.code_bytes+=g.bytes; f.groups++;
    }
    for (unsigned j=0;j<5;j++) if (s.slots[j].active) return HMISA_E_SCHEDULE;
    f.obligations=HMISA_PROOF_END_RETIREMENT|HMISA_PROOF_TAIL_PREFETCH|
        HMISA_PROOF_FP_ENVIRONMENT|HMISA_PROOF_LAUNCH_MAPPING|HMISA_PROOF_COMMON_ORDER_RELEASE;
    if (!f.end_count) f.obligations|=HMISA_MISSING_END;
    *out=f; return HMISA_OK;
}
