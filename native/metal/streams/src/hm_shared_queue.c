/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original queue-resource bridge.
 */
#include "hm_shared_queue.h"
#if defined(BLAZER) && BLAZER && defined(HMGPU_NATIVE_SHARED_INIT) && HMGPU_NATIVE_SHARED_INIT && defined(BLAZER_HMG_QUEUE) && BLAZER_HMG_QUEUE
#include <string.h>
static int alias(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    if(n>UINTPTR_MAX-x || m>UINTPTR_MAX-y)return 1;
    return x<=y ? y-x<n : x-y<m;
}
int hmsr_queue_build_compute(void *cookie,struct hq_context *c,const struct hmgpu_job *job,
    const struct hq_bo *refs,uint32_t n,struct hq_body *out) {
    struct hmsr_queue_bridge *b=cookie;
    struct hms_frozen_bo bos[HMSR_MAX_BOS];struct hmsr_validated validated;struct hq_body body={0};
    if(!b || !c || !job || !refs || !out || !n || n>HMSR_MAX_BOS)return HQ_INVALID;
    if(!b->frozen_view || !b->emit_compute || !b->validation.verify_stage || !b->validation.verify_order)return HQ_UNAVAILABLE;
    if(alias(out,sizeof *out,b,sizeof *b) || alias(out,sizeof *out,c,sizeof *c) ||
       alias(out,sizeof *out,job,sizeof *job) || alias(out,sizeof *out,refs,n*sizeof *refs))return HQ_INVALID;
    for(unsigned i=0;i<n;i++) {
        memset(&bos[i],0,sizeof bos[i]);int e=b->frozen_view(b->cookie,&refs[i],&bos[i]);if(e)return e;
        if(bos[i].bo.handle!=refs[i].handle || bos[i].bo.gpu_va!=refs[i].va || bos[i].bo.bytes!=refs[i].bytes ||
           bos[i].access!=refs[i].access || refs[i].bytes>SIZE_MAX ||
           alias(out,sizeof *out,bos[i].cpu,(size_t)refs[i].bytes))return HQ_INVALID;
    }
    int e=hmsr_validate_frozen(&b->heaps,job,bos,n,&b->validation,&validated);
    if(e)return e==HMS_E_DEPENDENCY ? HQ_UNAVAILABLE : e==HMS_E_UNSUPPORTED ? HQ_UNSUPPORTED : HQ_INVALID;
    e=b->emit_compute(b->cookie,c,job,&validated,&body);if(e)return e;
    if(!body.bytes || body.bytes>HQ_BODY_MAX || (body.bytes&7))return HQ_UNSUPPORTED;
    *out=body;return HQ_OK;
}
#endif
