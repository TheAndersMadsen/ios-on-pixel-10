/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original implementation.
 * Resource decoding: immutable streams-r2, not a shader validation substitute.
 */
#include "hm_shared_bridge.h"
#if defined(BLAZER) && BLAZER && defined(HMGPU_NATIVE_SHARED_INIT) && HMGPU_NATIVE_SHARED_INIT
#include <string.h>
static int overlap(uintptr_t a,size_t n,uintptr_t b,size_t m) {
    if(n>UINTPTR_MAX-a || m>UINTPTR_MAX-b)return 1;
    return a<=b ? b-a<n : a-b<m;
}
static uint32_t mask(uint32_t n) { return n==32 ? UINT32_MAX : (UINT32_C(1)<<n)-1; }
int hmsr_validate_frozen(const struct hms_heaps *h,const struct hmgpu_job *job,
    const struct hms_frozen_bo *bos,uint32_t n,const struct hmsr_validation_ops *ops,
    struct hmsr_validated *out) {
    struct hmsr_validated v={0};int e;
    if(!out || !h || !job || !bos || !n || n>HMSR_MAX_BOS)return HMS_E_ARGUMENT;
    if(overlap((uintptr_t)out,sizeof *out,(uintptr_t)h,sizeof *h) ||
       overlap((uintptr_t)out,sizeof *out,(uintptr_t)job,sizeof *job) ||
       overlap((uintptr_t)out,sizeof *out,(uintptr_t)bos,n*sizeof *bos) ||
       (ops && overlap((uintptr_t)out,sizeof *out,(uintptr_t)ops,sizeof *ops)))return HMS_E_ALIAS;
    for(unsigned i=0;i<n;i++)if(bos[i].bo.bytes>SIZE_MAX ||
        overlap((uintptr_t)out,sizeof *out,(uintptr_t)bos[i].cpu,(size_t)bos[i].bo.bytes))return HMS_E_ALIAS;
    if(!ops || !ops->verify_stage || !ops->verify_order)return HMS_E_DEPENDENCY;
    e=hmsr_decode_resources(h,job,bos,n,&v.resources);if(e)return e;
    /* Trusted function must decode these ACTUAL immutable uploaded bytes.
     * It is called even when metadata/encoders would appear to agree. */
    e=ops->verify_stage(ops->cookie,&v.resources,bos,n,&v.stage);
    if(e)return e==HMS_E_DEPENDENCY ? e : HMS_E_SHADER;
    const struct hmsr_stage_usage *s=&v.stage;
    if(!s->code_bytes || (s->code_bytes&3) || s->code_bytes>v.resources.usc_bytes_available ||
       s->temps>254 || s->unified_words>254 || s->shared_words<2 || s->shared_words>32 ||
       ((s->temps+1)&~1u)!=v.resources.temps_allocated ||
       ((s->unified_words+1)&~1u)!=v.resources.unified_words_allocated ||
       ((s->shared_words+15)&~15u)!=v.resources.shared_words_allocated ||
       (s->shared_read_mask&~mask(s->shared_words)) || (s->shared_read_mask&3)!=3 ||
       !s->access_count || s->access_count>HMSR_MAX_MEMORY_ACCESSES)return HMS_E_SHADER;
    for(unsigned i=s->shared_words;i<v.resources.shared_words_allocated;i++)
        if(v.resources.shared_image[i])return HMS_E_FORMAT;
    uint32_t needed[HMSR_MAX_BOS]={0};v.bo_mask=v.resources.resource_bo_mask;
    for(unsigned i=0;i<n;i++)if(v.bo_mask&(1u<<i))needed[i]=HMGPU_BO_READ;
    for(unsigned a=0;a<s->access_count;a++) {
        const struct hmsr_memory_access *m=&s->accesses[a];
        if(m->shared_word!=0 || !m->bytes || ((m->offset|m->bytes)&3) || !m->access ||
           (m->access&~(HMGPU_BO_READ|HMGPU_BO_WRITE)))return HMS_E_SHADER;
        uint64_t pointer=(uint64_t)v.resources.shared_image[0]|(uint64_t)v.resources.shared_image[1]<<32;
        if((pointer&3) || m->offset>UINT64_MAX-pointer)return HMS_E_RANGE;
        uint64_t va=pointer+m->offset;unsigned b;
        for(b=0;b<n;b++)if(bos[b].heap==HMS_GENERAL && pointer>=bos[b].bo.gpu_va &&
            pointer-bos[b].bo.gpu_va<bos[b].bo.bytes && va>=pointer &&
            va-bos[b].bo.gpu_va<bos[b].bo.bytes && m->bytes<=bos[b].bo.bytes-(va-bos[b].bo.gpu_va))break;
        if(b==n)return HMS_E_RANGE;
        if(v.resources.resource_bo_mask&(1u<<b))return HMS_E_ALIAS;
        if((bos[b].access&m->access)!=m->access)return HMS_E_RANGE;
        needed[b]|=m->access;v.bo_mask|=1u<<b;
    }
    /* Every submitted reference is justified, and requested access is exact.
     * No extra mutable alias or unused staging BO is quietly accepted. */
    if(v.bo_mask!=mask(n))return HMS_E_FORMAT;
    for(unsigned i=0;i<n;i++)if(needed[i]!=bos[i].access)return HMS_E_FORMAT;
    e=ops->verify_order(ops->cookie,h,job,bos,n,&v.resources,s);
    if(e)return e==HMS_E_DEPENDENCY ? e : HMS_E_UNSUPPORTED;
    *out=v;return HMS_OK;
}
#endif
