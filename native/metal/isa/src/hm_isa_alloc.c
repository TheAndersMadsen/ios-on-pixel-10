/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original C allocation algorithm.
 */
#include "hm_isa_alloc.h"
#include <string.h>
static int overlaps(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t av=(uintptr_t)a,bv=(uintptr_t)b;
    return an && bn && (av<=bv?bv-av<an:av-bv<bn);
}
static uint32_t find(const struct hmisa_allocation *a,uint32_t id)
{
    for (uint32_t i=0;i<a->value_count;i++) if (a->values[i].id==id) return i;
    return HMISA_NO_VALUE;
}
int hmisa_allocate(uint32_t enable,const struct hmisa_input *inputs,size_t ni,
    const struct hmisa_node *nodes,size_t nn,const uint32_t *outs,size_t no,
    uint32_t budget,struct hmisa_allocation *output)
{
    struct hmisa_allocation a; uint32_t i,j,k,vi,live,reg;
    uint8_t used[128];
    if (enable!=HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!output || (!inputs && ni)||(!nodes && nn)||(!outs && no)) return HMISA_E_ARGUMENT;
    if (ni>HMISA_MAX_VALUES || nn>HMISA_MAX_NODES || no>HMISA_MAX_VALUES ||
        !budget || budget>128) return HMISA_E_BOUNDS;
    if (overlaps(output,sizeof *output,inputs,ni*sizeof *inputs)||
        overlaps(output,sizeof *output,nodes,nn*sizeof *nodes)||
        overlaps(output,sizeof *output,outs,no*sizeof *outs)) return HMISA_E_ALIAS;
    memset(&a,0,sizeof a); a.node_count=(uint32_t)nn;
    for (i=0;i<HMISA_MAX_NODES;i++) a.node_reg[i]=HMISA_NO_VALUE;
    for (i=0;i<ni;i++) {
        if (inputs[i].id==HMISA_NO_VALUE || find(&a,inputs[i].id)!=HMISA_NO_VALUE)
            return HMISA_E_ARGUMENT;
        if (inputs[i].reg>=budget) return HMISA_E_BOUNDS;
        for (j=0;j<i;j++) if (inputs[i].reg==inputs[j].reg) return HMISA_E_ALIAS;
        a.values[a.value_count++]=(struct hmisa_assignment){inputs[i].id,inputs[i].reg,-1,-1};
        if (inputs[i].reg+1>a.high_water) a.high_water=inputs[i].reg+1;
    }
    /* Complete def/use validation and last-use computation precede allocation.
     * No caller sees a partially allocated block, even on late pressure. */
    for (i=0;i<nn;i++) {
        const struct hmisa_node *n=&nodes[i];
        if (n->op==HMISA_SSA_LOAD) {
            if (n->lhs!=HMISA_NO_VALUE || n->rhs!=HMISA_NO_VALUE) return HMISA_E_ARGUMENT;
        } else if (n->op==HMISA_FADD || n->op==HMISA_FSUB || n->op==HMISA_FMUL || n->op==HMISA_SSA_USE) {
            vi=find(&a,n->lhs); if (vi==HMISA_NO_VALUE) return HMISA_E_ARGUMENT;
            a.values[vi].last_use=(int32_t)i;
            if (n->op!=HMISA_SSA_USE) {
                vi=find(&a,n->rhs); if (vi==HMISA_NO_VALUE) return HMISA_E_ARGUMENT;
                a.values[vi].last_use=(int32_t)i;
            } else if (n->id!=HMISA_NO_VALUE || n->rhs!=HMISA_NO_VALUE) return HMISA_E_ARGUMENT;
        } else return HMISA_E_UNSUPPORTED;
        if (n->op==HMISA_SSA_USE) continue;
        if (n->id==HMISA_NO_VALUE || find(&a,n->id)!=HMISA_NO_VALUE) return HMISA_E_ARGUMENT;
        if (a.value_count==HMISA_MAX_VALUES) return HMISA_E_CAPACITY;
        a.values[a.value_count++]=(struct hmisa_assignment){n->id,HMISA_NO_VALUE,(int32_t)i,(int32_t)i};
    }
    for (i=0;i<no;i++) {
        for (j=0;j<i;j++) if (outs[j]==outs[i]) return HMISA_E_ARGUMENT;
        vi=find(&a,outs[i]); if (vi==HMISA_NO_VALUE) return HMISA_E_ARGUMENT;
        a.values[vi].last_use=(int32_t)nn;
    }
    for (i=0;i<nn;i++) {
        memset(used,0,sizeof used); live=0;
        for (j=0;j<a.value_count;j++) {
            const struct hmisa_assignment *v=&a.values[j];
            if (v->definition<(int32_t)i && v->last_use>=(int32_t)i) {
                if (v->reg>=budget) return HMISA_E_FORMAT;
                used[v->reg]=1; live++;
            }
        }
        if (nodes[i].op==HMISA_SSA_USE) {
            vi=find(&a,nodes[i].lhs); a.node_reg[i]=a.values[vi].reg;
        } else {
            for (reg=0;reg<budget && used[reg];reg++) {}
            if (reg==budget) return HMISA_E_CAPACITY;
            k=find(&a,nodes[i].id); a.values[k].reg=reg; a.node_reg[i]=reg;
            if (reg+1>a.high_water) a.high_water=reg+1;
            live++;
        }
        if (live>a.peak_live) a.peak_live=live;
    }
    /* An empty block with caller live-outs still reports actual live inputs. */
    if (!nn) { live=0; for (i=0;i<ni;i++) if (a.values[i].last_use>=0) live++; a.peak_live=live; }
    *output=a; return HMISA_OK;
}
