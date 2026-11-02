/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. HOST-ONLY synthetic transport model.
 * None of these addresses, shader bytes, or engine events are physical facts.
 */
#ifndef HMN_TEST_MODEL_H
#define HMN_TEST_MODEL_H
#include "hmn.h"
#define MODEL_BOS 128
struct model_bo { uint32_t handle,flags; uint64_t va,size; void *cpu,*gpu; int mapped; };
struct model {
    struct model_bo bos[MODEL_BOS];
    struct hmn_transport transport;
    struct hmn_peer_ops ops;
    struct hmgpu_open_out info;
    unsigned calls[HMGPU_SEL_COUNT],created,destroyed,maps,unmaps,compiles,compiled_freed;
    unsigned create_fail_at,map_fail_at,unmap_fail,destroy_fail,ctx_fail,quiesce_fail;
    unsigned plan_fail,build_fail,bad_plan,bad_compiler,bad_bo_reply,bad_submit_reply,submit_error;
    unsigned wait_error,cache_error,wait_override;
    struct hmgpu_wait_out reply;
    uint32_t next_handle,context,epoch;
    uint64_t heap_next[3],next_seq,seq;
    int ready,pending,engine_done,handbacks,auto_event,stream_profile;
    struct hmgpu_job submitted;
    struct hmgpu_bo_ref refs[40];
    unsigned ref_count,event_rejections;
    uint32_t expected_half;
};
void model_init(struct model *);
void model_dispose(struct model *);
int model_event(struct model *,uint32_t context,uint32_t epoch,uint64_t seq);
unsigned model_live(const struct model *);
int model_main(void);
#endif
