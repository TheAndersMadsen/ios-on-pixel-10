/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original DXT71 common resource initialization, see PROVENANCE.md.
 * Runtime has no vendor ELF/Mesa/compiler/device dependency; default off.
 */
#include "hm_shared.h"
#if defined(BLAZER) && BLAZER && defined(HMGPU_NATIVE_SHARED_INIT) && HMGPU_NATIVE_SHARED_INIT
#include <string.h>
static void put32(void *p,uint32_t x) { unsigned char *b=p; for(unsigned i=0;i<4;i++)b[i]=(unsigned char)(x>>(8*i)); }
static void put64(void *p,uint64_t x) { put32(p,(uint32_t)x); put32((char *)p+4,(uint32_t)(x>>32)); }
static int overlap(uint64_t a,uint64_t n,uint64_t b,uint64_t m) { return a<=b ? b-a<n : a-b<m; }
static int cpu_overlap(const void *a,size_t n,const void *b,size_t m) {
    if(!a || !b || n>UINTPTR_MAX-(uintptr_t)a || m>UINTPTR_MAX-(uintptr_t)b)return 1;
    return overlap((uintptr_t)a,n,(uintptr_t)b,m);
}
static unsigned up(unsigned n,unsigned unit) { return n/unit+(n%unit!=0); }
int hmsr_shared_control_encode(uint32_t word,uint32_t last,uint32_t *out) {
    uint32_t control; int e;
    if(!out)return HMS_E_ARGUMENT;
    if(word>=HMSR_MAX_SHARED_WORDS || (word&1))return HMS_E_RANGE;
    e=hms_pds_pointer_control_encode(word,last,&control); if(e)return e;
    *out=control|UINT32_C(0x10000000); return HMS_OK;
}
int hmsr_common_cdm_encode(uint64_t data,uint64_t code,uint32_t words,uint32_t shared,void *out,size_t n) {
    unsigned char b[32]={0};
    if(!out)return HMS_E_ARGUMENT;
    if((data|code)&15)return HMS_E_ALIGN;
    if(data>=UINT64_C(0x100000000)||code>=UINT64_C(0x100000000))return HMS_E_RANGE;
    if(!words || words>192 || (shared!=16 && shared!=32))return HMS_E_UNSUPPORTED;
    if(n<sizeof b)return HMS_E_CAPACITY;
    put32(b,up(words,4)<<1); put32(b+4,(uint32_t)data|2); put32(b+8,(uint32_t)code);
    /* For a1-instance common-init request of16/32 words the vendor slot
     * calculation gives max_instances1; K8.low11 is shared words /16. */
    put32(b+24,UINT32_C(0x02000000)|(shared/16));
    memcpy(out,b,sizeof b); return HMS_OK;
}
static int describe(const struct hmsr_desc *d,struct hmsr_layout *l,uint64_t *usc_va,uint32_t *image) {
    uint32_t assigned=0,np=0; uint64_t va; int e;
    if(!d || !l)return HMS_E_ARGUMENT;
    if(!d->shared_words || d->shared_words>HMSR_MAX_SHARED_WORDS || d->temps>254 || d->unified_words>254 || d->input_count>HMSR_MAX_INPUTS)return HMS_E_UNSUPPORTED;
    if(!d->code_bytes || (d->entry_offset&3) || d->entry_offset>=d->code_bytes)return HMS_E_SHADER;
    if(d->usc.access!=HMGPU_BO_READ)return HMS_E_ARGUMENT;
    e=hms_region_check(&d->heaps,&d->usc,HMS_USC,HMGPU_BO_READ,d->code_bytes,16,&va); if(e)return e;
    if(va-d->heaps.usc.base+d->entry_offset>=UINT64_C(0x100000000))return HMS_E_RANGE;
    if(usc_va)*usc_va=va;
    if(image)memset(image,0,HMSR_MAX_SHARED_WORDS*4);
    for(unsigned i=0;i<d->input_count;i++) {
        const struct hmsr_input *s=&d->inputs[i]; unsigned width=s->kind==HMSR_POINTER64?2:1;
        if(s->word>=d->shared_words || width>d->shared_words-s->word)return HMS_E_RANGE;
        if((s->kind!=HMSR_LITERAL32 && s->kind!=HMSR_POINTER64) || (width==2 && (s->word&1)))return HMS_E_UNSUPPORTED;
        uint32_t mask=(width==2?3u:1u)<<s->word;
        if(mask&assigned)return HMS_E_ALIAS;
        assigned|=mask;
        if(s->kind==HMSR_POINTER64) {
            if(s->literal || !s->min_bytes || ++np>HMS_MAX_POINTERS)return HMS_E_ARGUMENT;
            e=hms_region_check(&d->heaps,&s->buffer,HMS_GENERAL,s->buffer.access,s->min_bytes,4,&va); if(e)return e;
            if(image){image[s->word]=(uint32_t)va;image[s->word+1]=(uint32_t)(va>>32);}
        } else {
            struct hms_region zero={0};
            if(s->min_bytes || memcmp(&s->buffer,&zero,sizeof zero))return HMS_E_ARGUMENT;
            if(image)image[s->word]=s->literal;
        }
    }
    unsigned alloc=up(d->shared_words,16)*16;
    *l=(struct hmsr_layout){alloc,alloc*8,up(alloc/2*4,16)*16,16,16,HMSR_STREAM_BYTES,16,64};
    return HMS_OK;
}
int hmsr_plan(const struct hmsr_desc *d,struct hmsr_layout *out) {
    struct hmsr_layout l; if(!out)return HMS_E_ARGUMENT;
    int e=describe(d,&l,0,0); if(!e)*out=l; return e;
}
static int add_bo(struct hmsr_product *p,const struct hms_region *r) {
    for(unsigned i=0;i<p->bo_count;i++)if(p->bos[i].handle==r->bo.handle) {
        p->bos[i].access|=r->access; return HMS_OK;
    }
    if(p->bo_count>=HMSR_MAX_BOS)return HMS_E_CAPACITY;
    p->bos[p->bo_count++]=(struct hmgpu_bo_ref){r->bo.handle,r->access};return HMS_OK;
}
static int allocations(const struct hms_region *const *r,unsigned n,unsigned outputs) {
    for(unsigned i=0;i<n;i++)for(unsigned j=0;j<i;j++) {
        if(r[i]->bo.handle==r[j]->bo.handle) {
            if(r[i]->bo.gpu_va!=r[j]->bo.gpu_va || r[i]->bo.bytes!=r[j]->bo.bytes || r[i]->heap!=r[j]->heap)return HMS_E_ALIAS;
        } else if(overlap(r[i]->bo.gpu_va,r[i]->bo.bytes,r[j]->bo.gpu_va,r[j]->bo.bytes))return HMS_E_ALIAS;
        if((i<outputs || j<outputs) && overlap(r[i]->bo.gpu_va+r[i]->offset,r[i]->bytes,r[j]->bo.gpu_va+r[j]->offset,r[j]->bytes))return HMS_E_ALIAS;
    }
    return HMS_OK;
}
int hmsr_build(const struct hmsr_desc *d,const struct hmsr_storage *s,struct hmsr_product *out) {
    struct hmsr_layout l; uint32_t image[32]; uint64_t usc,va[5]; int e;
    struct hmsr_product p={0};
    unsigned char idata[256]={0},icode[64]={0},mdata[16]={0},mcode[16]={0},stream[68];
    if(!s || !out)return HMS_E_ARGUMENT;
    e=describe(d,&l,&usc,image); if(e)return e;
    if(cpu_overlap(out,sizeof *out,d,sizeof *d)||cpu_overlap(out,sizeof *out,s,sizeof *s))return HMS_E_ALIAS;
    const struct hmsr_segment *a[]={&s->init_data,&s->init_code,&s->main_data,&s->main_code,&s->stream};
    const uint32_t bytes[]={l.init_data_bytes,l.init_code_bytes,l.main_data_bytes,l.main_code_bytes,l.stream_bytes};
    const struct hms_region *regions[HMSR_MAX_BOS]; unsigned nr=0;
    for(unsigned i=0;i<5;i++) {
        if(!a[i]->cpu || a[i]->capacity<bytes[i])return HMS_E_CAPACITY;
        e=hms_region_check(&d->heaps,&a[i]->region,i==4?HMS_GENERAL:HMS_PDS,HMGPU_BO_READ,bytes[i],16,&va[i]);if(e)return e;
        if(a[i]->region.access!=HMGPU_BO_READ)return HMS_E_ARGUMENT;
        if(cpu_overlap(a[i]->cpu,bytes[i],d,sizeof *d)||cpu_overlap(a[i]->cpu,bytes[i],s,sizeof *s)||cpu_overlap(a[i]->cpu,bytes[i],out,sizeof *out))return HMS_E_ALIAS;
        for(unsigned j=0;j<i;j++)if(cpu_overlap(a[i]->cpu,bytes[i],a[j]->cpu,bytes[j]))return HMS_E_ALIAS;
        regions[nr++]=&a[i]->region;
    }
    /* Require the COMPLETE stream including terminate to stay before page guard. */
    uint64_t poff=va[4]&(d->heaps.page_size-1);
    if(poff>d->heaps.page_size-l.guard || l.stream_bytes>d->heaps.page_size-l.guard-poff)return HMS_E_RANGE;
    regions[nr++]=&d->usc;
    for(unsigned i=0;i<d->input_count;i++)if(d->inputs[i].kind==HMSR_POINTER64)regions[nr++]=&d->inputs[i].buffer;
    e=allocations(regions,nr,5);if(e)return e;
    for(unsigned i=0;i<l.shared_words_allocated/2;i++) {
        uint32_t control,inst;
        e=hmsr_shared_control_encode(i*2,i+1==l.shared_words_allocated/2,&control);if(e)return e;
        struct hms_pds_dout dout={HMS_DOUTW,i+1==l.shared_words_allocated/2,0,HMS_PDS_CONSTANT,i*4,HMS_PDS_CONSTANT,i*4+2};
        e=hms_pds_dout_encode(&dout,&inst);if(e)return e;
        put32(idata+i*16,image[i*2]);put32(idata+i*16+4,image[i*2+1]);put32(idata+i*16+8,control);put32(icode+i*4,inst);
    }
    uint64_t launch;
    e=hms_pds_launch_encode(usc-d->heaps.usc.base+d->entry_offset,d->temps,&launch);if(e)return e;
    put64(mdata,launch);
    struct hms_pds_dout dout={HMS_DOUTU,1,0,HMS_PDS_CONSTANT,0,HMS_PDS_CONSTANT,2}; uint32_t inst;
    e=hms_pds_dout_encode(&dout,&inst);if(e)return e;
    put32(mcode,inst);
    e=hmsr_common_cdm_encode(va[0]-d->heaps.pds.base,va[1]-d->heaps.pds.base,l.init_data_bytes/4,l.shared_words_allocated,stream,sizeof stream);if(e)return e;
    struct hms_cdm_direct cdm={va[2]-d->heaps.pds.base,va[3]-d->heaps.pds.base,4,0,d->unified_words,{1,1,1},{1,1,1}};
    e=hms_cdm_encode(&cdm,stream+32,36);if(e)return e;
    for(unsigned i=0;i<nr;i++){e=add_bo(&p,regions[i]);if(e)return e;}
    p.stream_va=va[4];p.stream_bytes=l.stream_bytes;
    /* All fallible work above. No allocation, callback, BO acquisition or
     * partial output is left behind on any error. Caller freezes descriptors. */
    const void *built[]={idata,icode,mdata,mcode,stream};
    for(unsigned i=0;i<5;i++)memcpy(a[i]->cpu,built[i],bytes[i]);
    *out=p;return HMS_OK;
}
#endif
