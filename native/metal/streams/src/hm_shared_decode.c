/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Independent frozen resource decoder.
 * No encoder/re-encoding, shader validator, readiness or completion assertion.
 */
#include "hm_shared.h"
#if defined(BLAZER) && BLAZER && defined(HMGPU_NATIVE_SHARED_INIT) && HMGPU_NATIVE_SHARED_INIT
#include <string.h>
static uint32_t get32(const void *p) { const unsigned char *b=p; return (uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24; }
static int overlap(uint64_t a,uint64_t n,uint64_t b,uint64_t m) { return a<=b ? b-a<n : a-b<m; }
static int cpu_overlap(const void *a,size_t n,const void *b,size_t m) {
    if(!a || !b || n>UINTPTR_MAX-(uintptr_t)a || m>UINTPTR_MAX-(uintptr_t)b)return 1;
    return overlap((uintptr_t)a,n,(uintptr_t)b,m);
}
int hmsr_shared_control_decode(uint32_t control,uint32_t *word,uint32_t *last) {
    uint32_t mask=control&15, lane, index, swizzle=(control>>4)&255;
    if(!word || !last)return HMS_E_ARGUMENT;
    /* mode must be precisely shared1, no flags besides LAST, quad, swizzle. */
    if((control&UINT32_C(0x7c001000))!=UINT32_C(0x10000000))return HMS_E_UNSUPPORTED;
    if(mask==3)lane=0;else if(mask==12)lane=2;else return HMS_E_UNSUPPORTED;
    if(swizzle!=(1u<<(2*(lane+1))))return HMS_E_FORMAT;
    index=((control>>13)&8191)*4+lane;
    if(index+1>=HMSR_MAX_SHARED_WORDS)return HMS_E_RANGE;
    *word=index;*last=control>>31;return HMS_OK;
}
int hmsr_common_cdm_decode(const void *bytes,size_t n,struct hmsr_common_decoded *out) {
    const unsigned char *b=bytes;struct hmsr_common_decoded d;
    if(!b || !out)return HMS_E_ARGUMENT;
    if(n!=32)return HMS_E_FORMAT;
    uint32_t k0=get32(b),k1=get32(b+4),k2=get32(b+8),k8=get32(b+24);
    if((k0&~UINT32_C(0x7e)) || (k1&15)!=2 || (k2&15) ||
        get32(b+12)||get32(b+16)||get32(b+20)||get32(b+28))return HMS_E_UNSUPPORTED;
    d.data_words_allocated=((k0>>1)&63)*4;
    if(!d.data_words_allocated || d.data_words_allocated>192)return HMS_E_RANGE;
    /* Exact inspected subset: max_instances1, no local memory,16/32 shared. */
    if(k8!=UINT32_C(0x02000001) && k8!=UINT32_C(0x02000002))return HMS_E_UNSUPPORTED;
    d.shared_words_allocated=(k8&2047)*16; d.data_offset=k1&~15u;d.code_offset=k2;
    *out=d;return HMS_OK;
}
static int span(const struct hms_frozen_bo *bos,unsigned n,unsigned heap,uint64_t va,size_t bytes,
    const unsigned char **cpu,unsigned *index) {
    for(unsigned i=0;i<n;i++)if(bos[i].heap==heap && va>=bos[i].bo.gpu_va &&
        va-bos[i].bo.gpu_va<bos[i].bo.bytes && bytes<=bos[i].bo.bytes-(va-bos[i].bo.gpu_va)) {
        if(bos[i].access!=HMGPU_BO_READ)return HMS_E_ALIAS;
        *cpu=(const unsigned char *)bos[i].cpu+(size_t)(va-bos[i].bo.gpu_va);*index=i;return HMS_OK;
    }
    return HMS_E_RANGE;
}
int hmsr_decode_resources(const struct hms_heaps *h,const struct hmgpu_job *job,
    const struct hms_frozen_bo *bos,uint32_t nbo,struct hmsr_frozen_resources *out) {
    struct hmsr_frozen_resources r={0};struct hmsr_common_decoded common;
    struct hms_cdm_decoded main; const unsigned char *b,*id,*ic,*md,*mc,*usc;
    unsigned stream_bo,idi,ici,mdi,mci,usci;int e;
    if(!h || !job || !bos || !out || !nbo || nbo>HMSR_MAX_BOS || job->size!=sizeof *job ||
       job->bo_count!=nbo || job->bo_first>UINT32_MAX-nbo || job->type!=HMGPU_JOB_COMPUTE ||
       job->flags || job->hwrt || job->pad || job->fw_geom_bytes || job->fw_frag_bytes ||
       job->stream_bytes!=HMSR_STREAM_BYTES || (job->stream_va&15))return HMS_E_ARGUMENT;
    if(cpu_overlap(out,sizeof *out,job,sizeof *job)||cpu_overlap(out,sizeof *out,h,sizeof *h)||
       cpu_overlap(out,sizeof *out,bos,nbo*sizeof *bos))return HMS_E_ALIAS;
    for(unsigned i=0;i<sizeof job->fw_cmd;i++)if(job->fw_cmd[i])return HMS_E_UNSUPPORTED;
    for(unsigned i=0;i<nbo;i++) {
        struct hms_region region={.bo=bos[i].bo,.offset=0,.bytes=bos[i].bo.bytes,.heap=bos[i].heap,.access=bos[i].access}; uint64_t va;
        if(!bos[i].cpu || bos[i].bo.bytes>bos[i].cpu_bytes)return HMS_E_CAPACITY;
        e=hms_region_check(h,&region,region.heap,region.access,region.bytes,h->page_size,&va);if(e)return e;
        if(cpu_overlap(out,sizeof *out,bos[i].cpu,(size_t)region.bytes))return HMS_E_ALIAS;
        for(unsigned j=0;j<i;j++)if(bos[i].bo.handle==bos[j].bo.handle ||
            overlap(va,region.bytes,bos[j].bo.gpu_va,bos[j].bo.bytes)||cpu_overlap(bos[i].cpu,(size_t)region.bytes,bos[j].cpu,(size_t)bos[j].bo.bytes))return HMS_E_ALIAS;
    }
    if((job->stream_va&(h->page_size-1))+job->stream_bytes>h->page_size-64)return HMS_E_RANGE;
    e=span(bos,nbo,HMS_GENERAL,job->stream_va,68,&b,&stream_bo);if(e)return e;
    e=hmsr_common_cdm_decode(b,32,&common);if(e)return e;
    e=hms_cdm_decode(b+32,36,&main);if(e)return e;
    for(unsigned j=0;j<3;j++)if(main.groups[j]!=1||main.local[j]!=1)return HMS_E_UNSUPPORTED;
    if(main.pds_temp_words_allocated || main.pds_data_words_allocated!=4 ||
        common.data_words_allocated!=common.shared_words_allocated*2)return HMS_E_UNSUPPORTED;
    uint64_t iva=h->pds.base+common.data_offset,icva=h->pds.base+common.code_offset;
    uint64_t mva=h->pds.base+main.pds_data_offset,mcva=h->pds.base+main.pds_code_offset;
    size_t ilen=common.data_words_allocated*4,iclen=common.shared_words_allocated*2;
    const uint64_t pvas[]={iva,icva,mva,mcva};const size_t lengths[]={ilen,iclen,16,16};
    for(unsigned i=0;i<4;i++)for(unsigned j=0;j<i;j++)if(overlap(pvas[i],lengths[i],pvas[j],lengths[j]))return HMS_E_ALIAS;
    e=span(bos,nbo,HMS_PDS,iva,ilen,&id,&idi);if(e)return e;
    e=span(bos,nbo,HMS_PDS,icva,iclen,&ic,&ici);if(e)return e;
    e=span(bos,nbo,HMS_PDS,mva,16,&md,&mdi);if(e)return e;
    e=span(bos,nbo,HMS_PDS,mcva,16,&mc,&mci);if(e)return e;
    r.shared_words_allocated=common.shared_words_allocated;
    for(unsigned i=0;i<r.shared_words_allocated/2;i++) {
        struct hms_pds_dout inst;uint32_t word,last;
        e=hms_pds_dout_decode(get32(ic+i*4),&inst);if(e)return e;
        if(inst.kind!=HMS_DOUTW || inst.conditional || inst.end!=(i+1==r.shared_words_allocated/2)||
            inst.src0_word!=i*4 || inst.src1_word!=i*4+2 || get32(id+i*16+12))return HMS_E_FORMAT;
        e=hmsr_shared_control_decode(get32(id+i*16+8),&word,&last);if(e)return e;
        if(word!=i*2 || last!=(i+1==r.shared_words_allocated/2))return HMS_E_FORMAT;
        r.shared_image[word]=get32(id+i*16);r.shared_image[word+1]=get32(id+i*16+4);
    }
    struct hms_pds_dout inst;uint64_t usc_offset;
    e=hms_pds_dout_decode(get32(mc),&inst);if(e)return e;
    if(inst.kind!=HMS_DOUTU || !inst.end || inst.conditional || inst.src0_word || inst.src1_word!=2 || get32(md+8)||get32(md+12))return HMS_E_FORMAT;
    for(unsigned i=4;i<16;i++)if(mc[i])return HMS_E_FORMAT;
    e=hms_pds_launch_decode((uint64_t)get32(md)|(uint64_t)get32(md+4)<<32,&usc_offset,&r.temps_allocated);if(e)return e;
    r.usc_entry_va=h->usc.base+usc_offset;
    e=span(bos,nbo,HMS_USC,r.usc_entry_va,4,&usc,&usci);if(e)return e;
    r.usc=usc;r.usc_handle=bos[usci].bo.handle;
    r.usc_bytes_available=(size_t)(bos[usci].bo.bytes-(r.usc_entry_va-bos[usci].bo.gpu_va));
    r.unified_words_allocated=main.usc_unified_words_allocated;
    r.resource_bo_mask=(1u<<stream_bo)|(1u<<idi)|(1u<<ici)|(1u<<mdi)|(1u<<mci)|(1u<<usci);
    *out=r;return HMS_OK;
}
#endif
