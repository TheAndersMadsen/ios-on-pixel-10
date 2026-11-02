/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Actual hmn + hmsr, HMGU MODEL ONLY.
 * NON-USC compiler fixture, modeled events; no shader execution in shared mode.
 */
#include "model.h"
#include "hmn_streams.h"
#include "hm_shared.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct fixture { struct model m;struct hmn_device *d;struct hmn_pipeline *p;struct hmn_queue *q;
    struct hmn_buffer *data,*constants;struct hmn_command *c;struct hmn_binding bindings[HMN_SLOTS]; };
static unsigned cases;
static void begin(struct fixture *f) {
    memset(f,0,sizeof *f);model_init(&f->m);f->m.stream_profile=2;
    f->m.ops.plan=hmn_streams_plan;f->m.ops.build=hmn_streams_build;
    assert(!hmn_device_create(&f->m.transport,&f->m.info,&f->m.ops,1,&f->d));
    assert(!hmn_pipeline_create(f->d,"owned-fixture",13,"single_add",&f->p));
    assert(!hmn_buffer_create(f->d,128,&f->data));assert(!hmn_buffer_create(f->d,32,&f->constants));
    struct {float f;uint32_t i;uint16_t h;} constants={4,0x80000001,0x3800};
    assert(!hmn_buffer_write(f->constants,4,&constants,sizeof constants));
    f->bindings[0]=(struct hmn_binding){f->data,16};f->bindings[1]=(struct hmn_binding){f->constants,4};
    assert(!hmn_queue_create(f->d,&f->q));assert(!hmn_command_create(f->q,&f->c));
    assert(!hmn_command_encode(f->c,f->p,f->bindings,(struct hmn_dimensions){1,1,1},(struct hmn_dimensions){1,1,1}));
}
static void end(struct fixture *f) {
    if(f->c && hmn_command_pending(f->c))assert(!hmn_queue_quiesce(f->q));
    if(f->c)assert(!hmn_command_destroy(&f->c));
    if(f->p)hmn_pipeline_release(f->p);if(f->data)hmn_buffer_release(f->data);if(f->constants)hmn_buffer_release(f->constants);
    if(f->q)hmn_queue_release(f->q);assert(!hmn_device_destroy(&f->d));model_dispose(&f->m);++cases;
}
static void exact_refs_and_retention(void) {
    struct fixture f;begin(&f);uint64_t const_va=hmn_buffer_gpu_address(f.constants);
    assert(!hmn_command_commit(f.c));assert(f.m.submitted.stream_bytes==68 && f.m.ref_count==5 && model_live(&f.m)==6);
    unsigned general=0,pds=0,usc=0;
    for(unsigned i=0;i<f.m.ref_count;i++)for(unsigned j=0;j<MODEL_BOS;j++)if(f.m.bos[j].handle==f.m.refs[i].handle) {
        assert(f.m.bos[j].va!=const_va);assert(f.m.refs[i].access==((f.m.bos[j].va==hmn_buffer_gpu_address(f.data))?3u:1u));
        if(f.m.bos[j].flags&HMGPU_BO_HEAP_USC)++usc;else if(f.m.bos[j].flags&HMGPU_BO_HEAP_PDS)++pds;else ++general;
    }
    assert(general==2 && pds==2 && usc==1);
    float nine=9;assert(!hmn_buffer_write(f.constants,4,&nine,4)); /* CPU-only snapshot donor */
    assert(hmn_buffer_write(f.data,0,&nine,4)==HMN_BUSY);
    hmn_pipeline_release(f.p);f.p=NULL;hmn_buffer_release(f.constants);f.constants=NULL;hmn_buffer_release(f.data);f.data=NULL;
    unsigned live=model_live(&f.m);assert(hmn_command_wait(f.c,1)==HMN_TIMEOUT && hmn_command_pending(f.c));
    assert(hmn_command_destroy(&f.c)==HMN_BUSY && model_live(&f.m)==live);
    assert(model_event(&f.m,8,f.m.epoch,f.m.seq));assert(model_event(&f.m,f.m.context,f.m.epoch+1,f.m.seq));
    assert(!model_event(&f.m,f.m.context,f.m.epoch,f.m.seq)); /* injected external lifetime event, no arithmetic */
    f.m.cache_error=1;assert(hmn_command_wait(f.c,1)==HMN_TRANSPORT && model_live(&f.m)==live);
    f.m.cache_error=0;assert(!hmn_command_wait(f.c,1));assert(!hmn_command_pending(f.c));
    end(&f);
}
static void allocation_cleanup(void) {
    for(unsigned i=1;i<=3;i++) {
        struct fixture f;begin(&f);f.m.create_fail_at=f.m.calls[HMGPU_SEL_BO_CREATE]+i;
        assert(hmn_command_commit(f.c)==HMN_TRANSPORT && !f.m.calls[HMGPU_SEL_SUBMIT]);
        assert(!hmn_command_pending(f.c));end(&f);
    }
    for(unsigned i=1;i<=3;i++) {
        struct fixture f;begin(&f);f.m.map_fail_at=f.m.maps+i;
        assert(hmn_command_commit(f.c)==HMN_TRANSPORT && !f.m.calls[HMGPU_SEL_SUBMIT]);end(&f);
    }
}
static void failed_release_retries(void) {
    struct fixture f;begin(&f);assert(!hmn_command_commit(f.c));
    assert(hmn_command_wait(f.c,1)==HMN_TIMEOUT);f.m.quiesce_fail=1;
    assert(hmn_queue_quiesce(f.q)==HMN_TRANSPORT && hmn_command_destroy(&f.c)==HMN_BUSY);
    unsigned live=model_live(&f.m);f.m.quiesce_fail=0;assert(!hmn_queue_quiesce(f.q));
    assert(hmn_command_status(f.c)!=HMN_COMPLETED && hmn_command_result(f.c)!=HMN_OK);
    f.m.unmap_fail=1;assert(!hmn_command_destroy(&f.c));assert(model_live(&f.m)==live);
    hmn_pipeline_release(f.p);f.p=NULL;hmn_buffer_release(f.data);f.data=NULL;hmn_buffer_release(f.constants);f.constants=NULL;
    assert(hmn_device_collect(f.d)==HMN_TRANSPORT && model_live(&f.m));
    f.m.unmap_fail=0;f.m.destroy_fail=1;assert(hmn_device_collect(f.d)==HMN_TRANSPORT && model_live(&f.m));
    f.m.destroy_fail=0;assert(!hmn_device_collect(f.d));end(&f);
}
int main(void) {
    exact_refs_and_retention();allocation_cleanup();failed_release_retries();
    printf("PASS %u actual shared pipeline/BO lifetime cases; HMGU/engine/cache external MODEL, no shader execution\n",cases);
}
