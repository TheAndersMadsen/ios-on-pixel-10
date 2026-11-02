/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Host model only, never linked iOS.
 * Separate CPU/GPU byte arrays exercise actual upload/WAIT cache ownership.
 * Synthetic "code" is NOT USC; modeled engine math is NOT native acceleration.
 */
#include "model.h"
#include "hmn_streams.h"
#include "hm_streams.h"
#include "hm_shared_bridge.h"
#include "hm_shared_queue.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
struct model_code { struct hmusc_header h; struct hmusc_binding b[3]; unsigned char code[16]; };
struct model_artifact { struct model_code blob; struct hmn_address_binding address; };
struct model_cdm { uint64_t magic,code,shared; uint32_t shared_count,reserved; };
static const uint64_t magic=UINT64_C(0x544553542d43444d);
static struct model_bo *find_handle(struct model *m,uint32_t h)
{ for(unsigned i=0;i<MODEL_BOS;++i)if(m->bos[i].handle==h)return &m->bos[i]; return NULL; }
static struct model_bo *find_va(struct model *m,uint64_t va)
{ for(unsigned i=0;i<MODEL_BOS;++i)if(m->bos[i].handle && va>=m->bos[i].va && va-m->bos[i].va<m->bos[i].size)return &m->bos[i]; return NULL; }
static int shared_stage_boundary(void *p,const struct hmsr_frozen_resources *r,
    const struct hms_frozen_bo *b,uint32_t n,struct hmsr_stage_usage *out)
{
    (void)p;assert(r->usc && r->usc_bytes_available>=16 && n==5 && b);
    /* This injects a modeled external whole-stage verdict. It does NOT decode
     * USC and never calls a magic/encoder/metadata check a stage validator. */
    *out=(struct hmsr_stage_usage){.code_bytes=16,.temps=4,.shared_words=5,.shared_read_mask=7,
        .access_count=3,.accesses={{0,1,0,4},{0,1,4,4},{0,2,8,4}}};return 0;
}
static int shared_order_boundary(void *p,const struct hms_heaps *h,const struct hmgpu_job *j,
    const struct hms_frozen_bo *b,uint32_t n,const struct hmsr_frozen_resources *r,
    const struct hmsr_stage_usage *s)
{
    (void)p;assert(h && j->stream_bytes==68 && b && n==5 && r->shared_words_allocated==16 && s->shared_words==5);
    return 0; /* Missing hardware init/main/deallocation semantics MODELED ONLY. */
}
static int shared_frozen_view(void *p,const struct hq_bo *ref,struct hms_frozen_bo *out)
{
    struct model *m=p;struct model_bo *b=find_handle(m,ref->handle);assert(b);
    unsigned heap=(b->flags&HMGPU_BO_HEAP_USC)?HMS_USC:(b->flags&HMGPU_BO_HEAP_PDS)?HMS_PDS:HMS_GENERAL;
    *out=(struct hms_frozen_bo){{sizeof out->bo,b->handle,b->va,b->size,0,0},heap,ref->access,b->gpu,b->size};return 0;
}
static int shared_body_boundary(void *p,struct hq_context *c,const struct hmgpu_job *j,
    const struct hmsr_validated *v,struct hq_body *out)
{
    struct model *m=p;assert(c->handle==m->context && j->stream_bytes==68 && v->bo_mask==31);
    /* NOT a firmware body, never published to firmware. */
    out->bytes=16;memset(out->data,0x93,16);return 0;
}
static int call(void *ctx,uint32_t sel,const void *in,size_t ni,void *out,size_t *no)
{
    struct model *m=ctx; assert(sel<HMGPU_SEL_COUNT); ++m->calls[sel];
    if(sel==HMGPU_SEL_OPEN) {
        const struct hmgpu_open_in *a=in;
        assert(ni==sizeof *a && a->size==ni && a->abi_version==1 && !a->flags && !a->pad);
        assert(*no==sizeof m->info); *(struct hmgpu_open_out *)out=m->info; return 0;
    }
    if(sel==HMGPU_SEL_BO_CREATE) {
        const struct hmgpu_bo_create_in *a=in; assert(ni==sizeof *a && a->size==ni && *no==sizeof(struct hmgpu_bo_out));
        if(m->create_fail_at==m->calls[sel])return -1;
        unsigned i; for(i=0;i<MODEL_BOS && m->bos[i].handle;++i){} assert(i<MODEL_BOS);
        struct model_bo *b=&m->bos[i];
        b->handle=++m->next_handle; b->flags=a->flags; b->size=(a->bytes+16383)&~UINT64_C(16383);
        unsigned heap=(a->flags&HMGPU_BO_HEAP_USC)?1:(a->flags&HMGPU_BO_HEAP_PDS)?2:0;
        b->va=m->heap_next[heap]; m->heap_next[heap]+=b->size;
        b->cpu=malloc((size_t)b->size); b->gpu=malloc((size_t)b->size); assert(b->cpu && b->gpu);
        memset(b->cpu,0xa5,(size_t)b->size); memset(b->gpu,0xcd,(size_t)b->size); ++m->created;
        *(struct hmgpu_bo_out *)out=(struct hmgpu_bo_out){sizeof(struct hmgpu_bo_out),b->handle,b->va,b->size,0,0};
        if(m->bad_bo_reply==1)((struct hmgpu_bo_out *)out)->gpu_va=m->info.usc_va_base;
        if(m->bad_bo_reply==2)*no-=1;
        if(m->bad_bo_reply==3)((struct hmgpu_bo_out *)out)->bytes+=16384;
        return 0;
    }
    if(sel==HMGPU_SEL_BO_DESTROY) {
        const struct hmgpu_handle *a=in; assert(ni==sizeof *a && *no==0);
        struct model_bo *b=find_handle(m,a->handle); assert(b && !b->mapped);
        if(m->pending) for(unsigned i=0;i<m->ref_count;++i)assert(m->refs[i].handle!=a->handle);
        if(m->destroy_fail)return -1;
        free(b->cpu); free(b->gpu); memset(b,0,sizeof *b); ++m->destroyed; return 0;
    }
    if(sel==HMGPU_SEL_CTX_CREATE) {
        const struct hmgpu_ctx_create_in *a=in;
        assert(ni==sizeof *a && a->engine==HMGPU_ENGINE_COMPUTE && !a->priority && !a->flags && !a->pad);
        assert(!a->static_state_va && !a->static_state_bytes && !m->context);
        if(!m->ready || m->ctx_fail)return -1;
        m->context=7;
        *(struct hmgpu_handle *)out=(struct hmgpu_handle){sizeof(struct hmgpu_handle),m->context}; return 0;
    }
    if(sel==HMGPU_SEL_CTX_DESTROY) {
        const struct hmgpu_handle *a=in; assert(ni==sizeof *a && a->handle==m->context && !*no);
        if(m->quiesce_fail)return -1;
        m->pending=0; m->context=0; return 0;
    }
    if(sel==HMGPU_SEL_SUBMIT) {
        const struct hmgpu_submit_in *a=in; assert(ni==sizeof *a && a->ctx==m->context && a->job_count==1);
        assert(!m->pending && a->user_tag && !a->wait_ctx_seq[0] && !a->wait_ctx_seq[1] && !a->wait_ctx_seq[2] && !a->wait_ctx_seq[3]);
        assert(a->bo_count>0 && a->bo_count<=32);
        m->submitted=*(const struct hmgpu_job *)(uintptr_t)a->jobs_uaddr;
        const struct hmgpu_job *j=&m->submitted;
        assert(j->size==sizeof *j && j->type==HMGPU_JOB_COMPUTE && !j->flags && !j->hwrt && !j->pad);
        assert(!j->fw_geom_bytes && !j->fw_frag_bytes && !j->bo_first && j->bo_count==a->bo_count);
        for(unsigned i=0;i<sizeof j->fw_cmd;++i)assert(!j->fw_cmd[i]);
        struct model_bo *stream=find_va(m,j->stream_va); assert(stream && !(stream->flags&(HMGPU_BO_HEAP_USC|HMGPU_BO_HEAP_PDS)));
        assert(!(j->stream_va&15) && j->stream_bytes==(m->stream_profile==2?HMSR_STREAM_BYTES:m->stream_profile?HMS_CDM_BYTES:sizeof(struct model_cdm)));
        m->ref_count=a->bo_count; memcpy(m->refs,(const void *)(uintptr_t)a->bos_uaddr,a->bo_count*sizeof m->refs[0]);
        int has_stream=0;
        for(unsigned i=0;i<m->ref_count;++i) {
            struct model_bo *b=find_handle(m,m->refs[i].handle); assert(b && m->refs[i].access && !(m->refs[i].access&~3));
            for(unsigned k=0;k<i;++k)assert(m->refs[k].handle!=m->refs[i].handle);
            /* Modeled kernel cache clean, independently observable. */
            memcpy(b->gpu,b->cpu,(size_t)b->size);
            if(b==stream)has_stream=1;
        }
        assert(has_stream);
        if(m->stream_profile==2) {
            struct hmsr_queue_bridge bridge={.validation={m,shared_stage_boundary,shared_order_boundary},
                .cookie=m,.frozen_view=shared_frozen_view,.emit_compute=shared_body_boundary};
            assert(!hms_heaps_from_open(&m->info,&bridge.heaps));
            struct hq_bo refs[32];
            for(unsigned i=0;i<m->ref_count;i++) {
                struct model_bo *b=find_handle(m,m->refs[i].handle);assert(b);
                refs[i]=(struct hq_bo){b,b->va,b->size,b->handle,m->refs[i].access};
            }
            struct hq_context context={.handle=m->context};struct hq_body body;
            assert(!hmsr_queue_build_compute(&bridge,&context,j,refs,m->ref_count,&body));
        }
        m->pending=1; m->engine_done=0; m->seq=++m->next_seq;
        *(struct hmgpu_submit_out *)out=(struct hmgpu_submit_out){sizeof(struct hmgpu_submit_out),0,m->seq};
        if(m->bad_submit_reply==1)((struct hmgpu_submit_out *)out)->seq=0;
        if(m->bad_submit_reply==2)*no-=1;
        if(m->bad_submit_reply==3)((struct hmgpu_submit_out *)out)->seq=UINT64_C(1)<<48;
        if(m->bad_submit_reply==4)((struct hmgpu_submit_out *)out)->pad=1;
        return m->submit_error ? -1 : 0; /* deliberately ambiguous after publish */
    }
    if(sel==HMGPU_SEL_WAIT) {
        const struct hmgpu_wait_in *a=in; assert(ni==sizeof *a && a->ctx==m->context && a->seq==m->seq);
        if(m->wait_error)return -1;
        if(m->wait_override) { *(struct hmgpu_wait_out *)out=m->reply; return 0; }
        if(m->auto_event && !m->engine_done)(void)model_event(m,m->context,m->epoch,m->seq);
        struct hmgpu_wait_out *b=out; *b=(struct hmgpu_wait_out){sizeof *b,HMGPU_TIMEOUT,0,0};
        if(!m->ready) { b->status=HMGPU_FAULT; return 0; }
        if(m->pending && m->engine_done) {
            if(m->cache_error)return -1;
            for(unsigned i=0;i<m->ref_count;++i) if(m->refs[i].access&HMGPU_BO_WRITE) {
                struct model_bo *bo=find_handle(m,m->refs[i].handle); assert(bo);
                memcpy(bo->cpu,bo->gpu,(size_t)bo->size);
            }
            ++m->handbacks; m->pending=0; b->status=HMGPU_DONE; b->completed_seq=m->seq;
        }
        return 0;
    }
    assert(!"unmodeled selector"); return -1;
}
static int map(void *ctx,uint32_t handle,void **out,uint64_t *bytes)
{
    struct model *m=ctx; ++m->maps;
    if(m->map_fail_at==m->maps)return -1;
    struct model_bo *b=find_handle(m,handle); assert(b && !b->mapped); b->mapped=1;
    *out=b->cpu; *bytes=b->size; return 0;
}
static int unmap(void *ctx,uint32_t handle,void *address)
{
    struct model *m=ctx; struct model_bo *b=find_handle(m,handle); assert(b && b->mapped && b->cpu==address); ++m->unmaps;
    if(m->unmap_fail)return -1;
    b->mapped=0; return 0;
}
static int validate_model(void *cookie,const struct hmn_compiled *c)
{
    const struct model_artifact *a=cookie;
    /* Lifetime/identity model only: these bytes are explicitly NON-USC.
     * This external compiler boundary never supplies production approval. */
    return c->hmusc!=&a->blob || c->hmusc_bytes!=sizeof a->blob;
}
static int compile(void *ctx,const void *air,size_t bytes,const char *entry,struct hmn_compiled *out)
{
    struct model *m=ctx; ++m->compiles; assert(bytes && air && !strcmp(entry,"single_add"));
    struct model_artifact *a=calloc(1,sizeof *a); assert(a);
    struct hmusc_header *h=&a->blob.h; memcpy(h->magic,HMUSC_MAGIC,8);
    h->version=HMUSC_VERSION; h->header_size=sizeof *h; h->target=HMUSC_TARGET_DXT71;
    h->bvnc[0]=71u<<16|2; h->bvnc[1]=2448u<<16|1212;
    h->stage=HMUSC_STAGE_COMPUTE; h->flags=HMUSC_F_HAS_CODE; h->temps=4; h->shareds=5;
    h->code_off=offsetof(struct model_code,code); h->code_len=16; h->bind_off=sizeof *h; h->bind_count=3;
    for(unsigned i=0;i<3;++i) a->blob.b[i]=(struct hmusc_binding){HMUSC_B_CONST,0,1,7,1,(uint16_t)(2+i),4*i,i==1?2u:i==2?1u:0u};
    memset(a->blob.code,0x5a,16); a->address=(struct hmn_address_binding){0,0,HMGPU_BO_READ|HMGPU_BO_WRITE,0,12,HMN_SHARED_WORDS};
    *out=(struct hmn_compiled){.hmusc=&a->blob,.hmusc_bytes=sizeof a->blob,.addresses=&a->address,
        .address_count=1,.shared_bank=7,.execution_width=1,.max_threads=1,.cookie=a,.validate_native=validate_model};
    if(m->stream_profile==1) {
        h->shareds=0; h->bind_count=0; h->bind_off=0; h->temps=3;
        a->address.placement=HMN_UNIFIED_INPUT_WORDS;
        out->shared_bank=0; out->unified_words=2; out->unified_bank=77; /* TEST bank, not hardware */
    }
    if(m->bad_compiler==1)a->address.first_word=2; /* register alias with CONST */
    if(m->bad_compiler==2)h->shareds=6; /* unfilled register */
    if(m->bad_compiler==3)h->flags|=HMUSC_F_PARTIAL;
    if(m->bad_compiler==4)out->execution_width=0;
    if(m->bad_compiler==5)return HMN_UNAVAILABLE; /* partial artifact release */
    return 0;
}
static void release_compiled(void *ctx,struct hmn_compiled *out)
{
    struct model *m=ctx;
    if(out->cookie) {
        struct model_artifact *a=out->cookie;
        /* Catch a driver overwriting compiler-owned pointer metadata before
         * release: compiler ownership must remain intact. */
        assert(out->addresses==&a->address); free(a); ++m->compiled_freed;
    }
    memset(out,0,sizeof *out);
}
static int plan(void *ctx,const struct hmn_dispatch *d,struct hmn_stream_plan *out)
{
    struct model *m=ctx; assert(d->code.handle && d->shared.handle && d->shared_count==5);
    assert(d->groups.x && d->groups.y && d->groups.z && d->threads.x==1);
    assert(d->slots[0].handle && d->slots[0].access==3 && d->slots[1].access==HMGPU_BO_READ);
    uint64_t addr=(uint64_t)d->shared_words[0]|(uint64_t)d->shared_words[1]<<32;
    assert(addr==d->slots[0].gpu_va);
    assert(d->shared_words[3]==0x80000001 && d->shared_words[4]==m->expected_half);
    if(m->plan_fail)return HMN_UNAVAILABLE;
    *out=(struct hmn_stream_plan){.count=2,.stream_index=1,.segments={
        {16,HMGPU_BO_HEAP_PDS|HMGPU_BO_GPU_READONLY,16},
        {sizeof(struct model_cdm),HMGPU_BO_GPU_READONLY,16}}};
    if(m->bad_plan==1)out->count=HMN_SEGMENTS+1;
    if(m->bad_plan==2)out->segments[1].alignment=3;
    if(m->bad_plan==3)out->segments[1].flags=HMGPU_BO_HEAP_USC;
    return 0;
}
static int build(void *ctx,const struct hmn_dispatch *d,const struct hmn_stream_plan *p,struct hmn_segment *segments)
{
    struct model *m=ctx; assert(p->count==2);
    if(m->build_fail)return HMN_ENCODING;
    assert(segments[0].buffer.gpu_va>=m->info.pds_va_base);
    memset(segments[0].cpu,0xd5,16); segments[0].used=16;
    struct model_cdm cdm={magic,d->code.gpu_va,d->shared.gpu_va,5,0};
    memcpy(segments[1].cpu,&cdm,sizeof cdm); segments[1].used=sizeof cdm;
    return 0;
}
void model_init(struct model *m)
{
    memset(m,0,sizeof *m);
    m->transport=(struct hmn_transport){m,call,map,unmap};
    m->ops=(struct hmn_peer_ops){HMN_PEER_VERSION,m,compile,release_compiled,plan,build};
    /* Synthetic per-test heaps. They are NOT hardware addresses or firmware VAs. */
    m->info=(struct hmgpu_open_out){sizeof m->info,HMGPU_ABI_VERSION,HMGPU_BACKEND_PVR,16384,
        UINT64_C(0x470002099004bc),0x100000000,0x10000000,0x200000000,0x10000000,0x300000000,0x10000000,HMGPU_CAP_COMPUTE,1};
    m->heap_next[0]=m->info.va_base; m->heap_next[1]=m->info.usc_va_base; m->heap_next[2]=m->info.pds_va_base;
    m->ready=1; m->epoch=3; m->expected_half=0x3f000000;
}
int model_event(struct model *m,uint32_t context,uint32_t epoch,uint64_t seq)
{
    if(!m->ready || !m->pending || m->engine_done || context!=m->context || epoch!=m->epoch || seq!=m->seq) {
        ++m->event_rejections; return -1;
    }
    /* A deliberately separate test-only engine interprets the test-only packet.
     * It exercises shared pointer/constant materialization and cache timing. */
    struct model_bo *stream=find_va(m,m->submitted.stream_va); assert(stream);
    uint64_t va=0; float b=0;
    if(m->stream_profile==2) {
        struct hms_heaps heaps;assert(!hms_heaps_from_open(&m->info,&heaps));
        struct hms_frozen_bo frozen[32];
        for(unsigned i=0;i<m->ref_count;i++) {
            struct model_bo *bo=find_handle(m,m->refs[i].handle);assert(bo);
            unsigned heap=(bo->flags&HMGPU_BO_HEAP_USC)?HMS_USC:(bo->flags&HMGPU_BO_HEAP_PDS)?HMS_PDS:HMS_GENERAL;
            frozen[i]=(struct hms_frozen_bo){{sizeof frozen[i].bo,bo->handle,bo->va,bo->size,0,0},heap,m->refs[i].access,bo->gpu,bo->size};
        }
        struct hmsr_frozen_resources resource;
        assert(!hmsr_decode_resources(&heaps,&m->submitted,frozen,m->ref_count,&resource));
        /* No USC validation or CPU shader execution here. Engine event and
         * later cache handback are explicit external lifetime MODEL events. */
        assert(resource.shared_words_allocated==16);
        va=(uint64_t)resource.shared_image[0]|(uint64_t)resource.shared_image[1]<<32;
        assert(find_va(m,va));m->engine_done=1;return 0;
    } else if(m->stream_profile) {
        struct hms_cdm_decoded decoded;
        assert(!hms_cdm_decode((unsigned char *)stream->gpu+(m->submitted.stream_va-stream->va),HMS_CDM_BYTES,&decoded));
        uint64_t pds_va=m->info.pds_va_base+decoded.pds_data_offset;
        struct model_bo *pds=find_va(m,pds_va); assert(pds);
        uint32_t words[2]; memcpy(words,(unsigned char *)pds->gpu+(pds_va-pds->va),sizeof words);
        va=(uint64_t)words[0]|(uint64_t)words[1]<<32;
        struct model_bo *data=find_va(m,va); assert(data);
        memcpy(&b,(unsigned char *)data->gpu+(va-data->va)+4,4);
    } else {
        struct model_cdm cdm; memcpy(&cdm,(unsigned char *)stream->gpu+(m->submitted.stream_va-stream->va),sizeof cdm);
        assert(cdm.magic==magic && cdm.shared_count==5);
        struct model_bo *code=find_va(m,cdm.code),*shared=find_va(m,cdm.shared); assert(code && shared);
        for(unsigned i=0;i<16;++i)assert(((unsigned char *)code->gpu)[i]==0x5a);
        uint32_t words[5]; memcpy(words,(unsigned char *)shared->gpu+(cdm.shared-shared->va),sizeof words);
        va=(uint64_t)words[0]|(uint64_t)words[1]<<32; memcpy(&b,&words[2],4);
    }
    struct model_bo *data=find_va(m,va); assert(data);
    float a; memcpy(&a,(unsigned char *)data->gpu+(va-data->va),4);
    float sum=a+b; memcpy((unsigned char *)data->gpu+(va-data->va)+8,&sum,4);
    m->engine_done=1; return 0;
}
unsigned model_live(const struct model *m) { return m->created-m->destroyed; }
void model_dispose(struct model *m)
{
    assert(!m->pending && !m->context && !model_live(m));
    assert(m->compiles==m->compiled_freed);
}
