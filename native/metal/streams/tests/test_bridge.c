/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. HOST ONLY model external boundaries.
 * NON-USC fixture bytes; stage/order/FW callbacks inject external results and
 * record actual inputs. They are NOT stage validators and never linked iOS.
 */
#include "hmn_streams.h"
#include "hm_shared_queue.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define PAGE 16384u
struct blob { struct hmusc_header h; unsigned char code[16]; };
struct fixture {
    struct blob blob;
    struct hmn_address_binding address;
    struct hmn_dispatch dispatch;
    struct hmn_stream_plan plan;
    struct hmn_segment segments[3];
    struct hms_heaps heaps;
    struct hms_frozen_bo bos[6];
    struct hq_bo refs[6];
    struct hmgpu_job job;
    struct hmsr_stage_usage usage;
    struct hmsr_validation_ops validation;
    unsigned native_calls,stage_calls,order_calls,emit_calls,view_calls;
    int native_error,stage_error,order_error,emit_error,view_error,bad_view,body_bytes;
    const void *seen_raw;
    unsigned char seen_byte;
    uint32_t words[32],unified[8];
};
static unsigned cases;
static int native_boundary(void *p,const struct hmn_compiled *c) {
    struct fixture *f=p;++f->native_calls;
    assert(c->hmusc==&f->blob && c->shared_bank==7);return f->native_error;
}
static int stage_boundary(void *p,const struct hmsr_frozen_resources *r,const struct hms_frozen_bo *bos,
    uint32_t n,struct hmsr_stage_usage *out) {
    struct fixture *f=p;++f->stage_calls;
    assert(n==f->job.bo_count && bos[0].bo.handle==f->bos[0].bo.handle);
    f->seen_raw=r->usc;f->seen_byte=*(const unsigned char *)r->usc;
    /* External ISA verdict/usage is modeled, not inferred from these bytes. */
    *out=f->usage;return f->stage_error;
}
static int order_boundary(void *p,const struct hms_heaps *h,const struct hmgpu_job *j,
    const struct hms_frozen_bo *b,uint32_t n,const struct hmsr_frozen_resources *r,
    const struct hmsr_stage_usage *s) {
    struct fixture *f=p;++f->order_calls;
    assert(h && j->stream_bytes==68 && b && n==f->job.bo_count && r->shared_words_allocated && s->access_count==3);
    return f->order_error; /* No schema or packet equality is called proof. */
}
static int view_boundary(void *p,const struct hq_bo *ref,struct hms_frozen_bo *out) {
    struct fixture *f=p;++f->view_calls;if(f->view_error)return f->view_error;
    for(unsigned i=0;i<f->job.bo_count;i++)if(ref->handle==f->bos[i].bo.handle) {
        *out=f->bos[i];if(f->bad_view)++out->bo.gpu_va;return 0;
    }
    return HQ_INVALID;
}
static int emit_boundary(void *p,struct hq_context *c,const struct hmgpu_job *j,
    const struct hmsr_validated *v,struct hq_body *body) {
    struct fixture *f=p;++f->emit_calls;
    assert(c && j->stream_va==f->job.stream_va && v->bo_mask==31 && v->stage.code_bytes==16);
    /* Synthetic body, NOT any DXT firmware structure. Queue-r2 owns that. */
    body->bytes=(uint32_t)f->body_bytes;memset(body->data,0x5e,sizeof body->data);
    return f->emit_error;
}
static struct hmn_buffer_view view(const struct hms_frozen_bo *b,uint64_t offset,uint64_t bytes) {
    return (struct hmn_buffer_view){b->bo.handle,b->access,b->bo.gpu_va+offset,bytes,b->bo.gpu_va,b->bo.bytes};
}
static void init(struct fixture *f,unsigned shared) {
    memset(f,0,sizeof *f);
    struct hmgpu_open_out info={sizeof info,HMGPU_ABI_VERSION,HMGPU_BACKEND_PVR,PAGE,
        UINT64_C(0x470002099004bc),UINT64_C(0x100000000),0x1000000,
        UINT64_C(0x200000000),0x1000000,UINT64_C(0x300000000),0x1000000,HMGPU_CAP_COMPUTE,1};
    assert(!hms_heaps_from_open(&info,&f->heaps));
    unsigned heaps[]={HMS_USC,HMS_GENERAL,HMS_PDS,HMS_PDS,HMS_GENERAL,HMS_GENERAL};
    uint64_t vas[]={info.usc_va_base,info.va_base,info.pds_va_base,info.pds_va_base+PAGE,info.va_base+PAGE,info.va_base+2*PAGE};
    for(unsigned i=0;i<6;i++) {
        void *cpu=calloc(1,PAGE);assert(cpu);
        f->bos[i]=(struct hms_frozen_bo){{sizeof(struct hmgpu_bo_out),i+1,vas[i],PAGE,0,0},heaps[i],i==1?3:1,cpu,PAGE};
        f->refs[i]=(struct hq_bo){cpu,vas[i],PAGE,i+1,f->bos[i].access};
    }
    struct hmusc_header *h=&f->blob.h;memcpy(h->magic,HMUSC_MAGIC,8);
    h->version=1;h->header_size=sizeof *h;h->target=HMUSC_TARGET_DXT71;h->bvnc[0]=71u<<16|2;h->bvnc[1]=2448u<<16|1212;
    h->stage=HMUSC_STAGE_COMPUTE;h->flags=HMUSC_F_HAS_CODE;h->temps=3;h->shareds=(uint16_t)shared;
    h->code_off=sizeof *h;h->code_len=sizeof f->blob.code;memset(f->blob.code,0xd3,sizeof f->blob.code);
    memcpy((void *)f->bos[0].cpu,f->blob.code,sizeof f->blob.code);
    f->address=(struct hmn_address_binding){.slot=0,.access=3,.byte_offset=16,.min_bytes=12,.placement=HMN_SHARED_WORDS};
    f->dispatch=(struct hmn_dispatch){.device=info,.shader={.hmusc=&f->blob,.hmusc_bytes=sizeof f->blob,
        .addresses=&f->address,.address_count=1,.shared_bank=7,.entry_offset=0,.execution_width=1,.max_threads=1,
        .cookie=f,.unified_words=3,.validate_native=native_boundary},.code=view(&f->bos[0],0,16),
        .usc_cpu=f->bos[0].cpu,.usc_cpu_bytes=16,.shared_words=f->words,.shared_count=shared,
        .unified_image=f->unified,.unified_count=3,.groups={1,1,1},.threads={1,1,1}};
    f->dispatch.slots[0]=view(&f->bos[1],64,256);
    uint64_t pointer=f->dispatch.slots[0].gpu_va+16;f->words[0]=(uint32_t)pointer;f->words[1]=(uint32_t)(pointer>>32);
    if(shared>2)f->words[2]=0x12345678;
    assert(!hmn_streams_plan(NULL,&f->dispatch,&f->plan));assert(f->plan.count==3 && f->plan.stream_index==2);
    unsigned owners[]={2,3,4};for(unsigned i=0;i<3;i++)f->segments[i]=(struct hmn_segment){
        view(&f->bos[owners[i]],0,f->plan.segments[i].bytes),(void *)f->bos[owners[i]].cpu,PAGE,0};
    assert(!hmn_streams_build(NULL,&f->dispatch,&f->plan,f->segments));
    f->job=(struct hmgpu_job){.size=sizeof f->job,.type=HMGPU_JOB_COMPUTE,.stream_va=f->bos[4].bo.gpu_va,.stream_bytes=68,.bo_count=5};
    f->usage=(struct hmsr_stage_usage){.code_bytes=16,.temps=3,.unified_words=3,.shared_words=shared,
        .shared_read_mask=shared>2?7:3,.access_count=3,.accesses={{0,1,0,4},{0,1,4,4},{0,2,8,4}}};
    f->validation=(struct hmsr_validation_ops){f,stage_boundary,order_boundary};f->body_bytes=16;
}
static void done(struct fixture *f) {
    for(unsigned i=0;i<6;i++)free((void *)f->bos[i].cpu);++cases;
}
static int validate(struct fixture *f,struct hmsr_validated *out) {
    return hmsr_validate_frozen(&f->heaps,&f->job,f->bos,f->job.bo_count,&f->validation,out);
}
static void refused(struct fixture *f) {
    struct hmsr_validated out,saved;memset(&out,0xad,sizeof out);saved=out;
    assert(validate(f,&out));assert(!memcmp(&out,&saved,sizeof out));
}
static void positive(unsigned shared) {
    struct fixture f;init(&f,shared);struct hmsr_validated out;
    assert(!validate(&f,&out));assert(f.stage_calls==1 && f.order_calls==1 && f.seen_raw==f.bos[0].cpu && f.seen_byte==0xd3);
    assert(out.resources.shared_image[0]==f.words[0] && out.resources.shared_image[1]==f.words[1]);
    assert(out.resources.shared_words_allocated==(shared<=16?16u:32u) && out.resources.temps_allocated==4 && out.resources.unified_words_allocated==4);
    for(unsigned i=shared;i<out.resources.shared_words_allocated;i++)assert(!out.resources.shared_image[i]);
    assert(f.segments[0].used==(shared<=16?144u:272u) && f.segments[1].used==(shared<=16?48u:80u) && f.segments[2].used==68);
    assert(out.bo_mask==31);done(&f);
}
static void external_refusals(void) {
    for(unsigned mode=0;mode<8;mode++) {
        struct fixture f;init(&f,3);
        switch(mode) {
        case 0:f.validation.verify_stage=NULL;break;
        case 1:f.validation.verify_order=NULL;break;
        case 2:f.stage_error=HMS_E_DEPENDENCY;break;
        case 3:f.stage_error=HMS_E_SHADER;break;
        case 4:f.order_error=HMS_E_DEPENDENCY;break;
        case 5:f.order_error=HMS_E_UNSUPPORTED;break;
        case 6:((unsigned char *)f.bos[0].cpu)[0]^=1;f.stage_error=HMS_E_SHADER;break;
        default:f.bos[0].cpu_bytes=15;break;
        }
        refused(&f);if(mode==6)assert(f.seen_byte==0xd2);done(&f);
    }
}
static void footprint_refusals(void) {
    for(unsigned mode=0;mode<16;mode++) {
        struct fixture f;init(&f,3);
        switch(mode) {
        case 0:f.usage.code_bytes=PAGE+4;break;
        case 1:f.usage.code_bytes=0;break;
        case 2:f.usage.code_bytes=15;break;
        case 3:f.usage.temps=5;break;
        case 4:f.usage.unified_words=1;break;
        case 5:f.usage.shared_words=17;break;
        case 6:f.usage.shared_read_mask|=1u<<3;break;
        case 7:f.usage.shared_read_mask=1;break;
        case 8:f.usage.access_count=17;break;
        case 9:f.usage.accesses[0].shared_word=2;break;
        case 10:f.usage.accesses[0].bytes=0;break;
        case 11:f.usage.accesses[0].offset=UINT64_MAX-3;break;
        case 12:f.usage.accesses[0].offset=PAGE;break;
        case 13:f.usage.accesses[0].bytes=3;break;
        case 14:f.usage.accesses[0].access=4;break;
        default:((uint32_t *)f.bos[2].cpu)[16+0]=9;break; /* SH8 padding in init data */
        }
        refused(&f);assert(!f.order_calls);done(&f);
    }
}
static void frozen_refusals(void) {
    for(unsigned mode=0;mode<12;mode++) {
        struct fixture f;init(&f,3);void *keep=NULL;
        switch(mode) {
        case 0:f.bos[1].access=HMGPU_BO_READ;break;
        case 1:f.bos[1].access=HMGPU_BO_WRITE;break;
        case 2:f.job.bo_count=6;break; /* unused extra BO */
        case 3:f.job.stream_bytes=64;break;
        case 4:f.job.fw_cmd[0]=1;break;
        case 5:f.bos[3].bo.handle=f.bos[2].bo.handle;break;
        case 6:f.bos[3].bo.gpu_va=f.bos[2].bo.gpu_va;break;
        case 7:keep=(void *)f.bos[3].cpu;f.bos[3].cpu=f.bos[2].cpu;break;
        case 8:f.bos[2].cpu_bytes=128;break;
        case 9:((uint32_t *)f.bos[2].cpu)[32+2]=1;break; /* main-data counted padding */
        case 10:((uint32_t *)f.bos[3].cpu)[8+1]=1;break; /* main-code counted padding */
        default:((uint32_t *)f.bos[2].cpu)[0]=(uint32_t)f.bos[4].bo.gpu_va;((uint32_t *)f.bos[2].cpu)[1]=(uint32_t)(f.bos[4].bo.gpu_va>>32);break;
        }
        refused(&f);if(keep)f.bos[3].cpu=keep;done(&f);
    }
}
static void builder_refusals(void) {
    for(unsigned mode=0;mode<12;mode++) {
        struct fixture f;init(&f,3);unsigned char before[3][512];struct hmn_segment saved[3];
        for(unsigned i=0;i<3;i++)memcpy(before[i],f.segments[i].cpu,512);
        switch(mode) {
        case 0:f.native_error=1;break;
        case 1:f.address.first_word=1;break;
        case 2:f.words[0]+=4;break;
        case 3:f.dispatch.shader.shared_bank=5;break;
        case 4:f.plan.segments[0].bytes++;break;
        case 5:f.segments[1].capacity=1;break;
        case 6:f.segments[1].buffer=f.segments[0].buffer;break;
        case 7:f.segments[1].cpu=f.segments[0].cpu;break;
        case 8:f.segments[0].cpu=&f.dispatch;break;
        case 9:((unsigned char *)f.bos[0].cpu)[0]^=1;break;
        case 10:f.address.min_bytes=PAGE+4;break;
        default:f.dispatch.groups.x=2;break;
        }
        memcpy(saved,f.segments,sizeof saved);
        assert(hmn_streams_build(NULL,&f.dispatch,&f.plan,f.segments));assert(!memcmp(saved,f.segments,sizeof saved));
        for(unsigned i=0;i<3;i++)assert(!memcmp(before[i],f.bos[2+i].cpu,512));done(&f);
    }
}
static void queue_composition(void) {
    for(unsigned mode=0;mode<10;mode++) {
        struct fixture f;init(&f,3);struct hq_context context={0};
        struct hmsr_queue_bridge b={f.heaps,f.validation,&f,view_boundary,emit_boundary};
        struct hq_body out,saved;memset(&out,0x71,sizeof out);saved=out;
        switch(mode) {
        case 0:break;
        case 1:b.emit_compute=NULL;break;
        case 2:f.stage_error=HMS_E_DEPENDENCY;break;
        case 3:f.order_error=HMS_E_DEPENDENCY;break;
        case 4:f.emit_error=HQ_UNAVAILABLE;break;
        case 5:f.body_bytes=513;break;
        case 6:f.body_bytes=7;break;
        case 7:f.bad_view=1;break;
        case 8:f.view_error=HQ_BUSY;break;
        default:b.frozen_view=NULL;break;
        }
        int e=hmsr_queue_build_compute(&b,&context,&f.job,f.refs,5,&out);
        if(!mode)assert(!e && out.bytes==16 && out.data[0]==0x5e && f.stage_calls==1 && f.order_calls==1 && f.emit_calls==1);
        else assert(e && !memcmp(&out,&saved,sizeof out));
        if(mode==1 || mode==9)assert(!f.stage_calls && !f.view_calls && !f.emit_calls);
        if(mode==2 || mode==3 || mode==7 || mode==8)assert(!f.emit_calls);
        done(&f);
    }
}
static void bounds_and_aliases(void) {
    for(unsigned mode=0;mode<7;mode++) {
        struct fixture f;init(&f,3);
        if(mode<4) {
            struct hmn_stream_plan out,saved;memset(&out,0x81,sizeof out);saved=out;
            switch(mode) {
            case 0:f.dispatch.shader.unified_words=f.dispatch.unified_count=UINT32_MAX;break;
            case 1:f.dispatch.shader.validate_native=NULL;break;
            case 2:f.dispatch.shared_count=2;break;
            default:f.unified[0]=1;break;
            }
            assert(hmn_streams_plan(NULL,&f.dispatch,&out));assert(!memcmp(&out,&saved,sizeof out));
        } else if(mode==4) {
            struct hmn_dispatch saved=f.dispatch;
            assert(hmn_streams_plan(NULL,&f.dispatch,(struct hmn_stream_plan *)&f.dispatch));
            assert(!memcmp(&saved,&f.dispatch,sizeof saved));
        } else if(mode==5) {
            struct hmsr_validated *out=(void *)f.bos[2].cpu;
            unsigned char saved[sizeof *out];memcpy(saved,out,sizeof saved);
            assert(hmsr_validate_frozen(&f.heaps,&f.job,f.bos,5,&f.validation,out)==HMS_E_ALIAS);
            assert(!memcmp(saved,out,sizeof saved));assert(!f.stage_calls);
        } else {
            struct hq_context context={0};struct hmsr_queue_bridge b={f.heaps,f.validation,&f,view_boundary,emit_boundary};
            struct hq_body *out=(void *)f.bos[4].cpu;unsigned char saved[sizeof *out];memcpy(saved,out,sizeof saved);
            assert(hmsr_queue_build_compute(&b,&context,&f.job,f.refs,5,out)==HQ_INVALID);
            assert(!memcmp(saved,out,sizeof saved) && !f.emit_calls);
        }
        done(&f);
    }
}
int main(void) {
    positive(2);positive(3);positive(17);positive(32);external_refusals();footprint_refusals();
    frozen_refusals();builder_refusals();queue_composition();bounds_and_aliases();
    printf("PASS %u focused resource/frozen/queue cases; ISA/order/FW verdicts MODELED, no shader approval or execution\n",cases);
}
