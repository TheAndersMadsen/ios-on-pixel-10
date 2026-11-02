/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original implementation, derived from documented/observed DXT format facts.
 * See PROVENANCE.md. No licensed stock code or shader bytes are copied here.
 */
#include "hm_streams.h"
#include "hmusc.h"
#include <string.h>

#define HMS_VA_LIMIT (UINT64_C(1) << 40)
#define HMS_OFFSET_LIMIT (UINT64_C(1) << 32)
#define HMS_ACCESS (HMGPU_BO_READ | HMGPU_BO_WRITE)
#define HMS_DATA_WORDS (4u * HMS_MAX_POINTERS + 4u)
#define HMS_CODE_BYTES (((HMS_MAX_POINTERS + 1u) * 4u + 15u) & ~15u)

static uint32_t load32(const void *p)
{
    const uint8_t *b = p;
    return (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 | (uint32_t)b[3] << 24;
}
static void store32(void *p, uint32_t v)
{
    uint8_t *b = p;
    b[0]=(uint8_t)v; b[1]=(uint8_t)(v>>8); b[2]=(uint8_t)(v>>16); b[3]=(uint8_t)(v>>24);
}
static uint64_t load64(const void *p)
{
    return load32(p) | (uint64_t)load32((const uint8_t *)p+4) << 32;
}
static void store64(void *p, uint64_t v)
{
    store32(p,(uint32_t)v); store32((uint8_t *)p+4,(uint32_t)(v>>32));
}
static uint32_t div_up(uint32_t n, uint32_t d) { return n/d + (n%d != 0); }
static int power2(uint64_t n) { return n && !(n & (n-1)); }
static int contains(uint64_t base, uint64_t size, uint64_t va, uint64_t bytes)
{
    return bytes && va >= base && va-base < size && bytes <= size-(va-base);
}
static int overlaps(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{
    return a <= b ? b-a < n : a-b < m;
}
static int host_overlap(const void *a, size_t n, const void *b, size_t m)
{
    if (!a || !b || n > UINTPTR_MAX-(uintptr_t)a || m > UINTPTR_MAX-(uintptr_t)b) return 1;
    return overlaps((uintptr_t)a,n,(uintptr_t)b,m);
}

int hms_pds_dout_encode(const struct hms_pds_dout *d, uint32_t *out)
{
    if (!d || !out || d->end > 1 || d->conditional > 1) return HMS_E_ARGUMENT;
    if (d->kind != HMS_DOUTW && d->kind != HMS_DOUTU) return HMS_E_UNSUPPORTED;
    if (d->src0_bank != HMS_PDS_CONSTANT || d->src1_bank != HMS_PDS_CONSTANT) return HMS_E_UNSUPPORTED;
    if ((d->src0_word & 1)) return HMS_E_ALIGN;
    if (d->src0_word >= HMS_PDS_CONST_WORDS-1 || d->src1_word >= HMS_PDS_CONST_WORDS) return HMS_E_RANGE;
    *out = UINT32_C(0xf0000000) | d->end<<26 | d->conditional<<27 |
           d->src1_word<<11 | (d->src0_word/2)<<3 | d->kind;
    return HMS_OK;
}

int hms_pds_dout_decode(uint32_t word, struct hms_pds_dout *out)
{
    struct hms_pds_dout d;
    if (!out) return HMS_E_ARGUMENT;
    if ((word & UINT32_C(0xf3f00000)) != UINT32_C(0xf0000000)) return HMS_E_FORMAT;
    d.kind=word&7; d.end=(word>>26)&1; d.conditional=(word>>27)&1;
    if (d.kind != HMS_DOUTW && d.kind != HMS_DOUTU) return HMS_E_UNSUPPORTED;
    d.src0_word=((word>>3)&255)*2; d.src1_word=(word>>11)&511;
    if (d.src0_word+1 >= HMS_PDS_CONST_WORDS || d.src1_word >= HMS_PDS_CONST_WORDS) return HMS_E_UNSUPPORTED;
    d.src0_bank=HMS_PDS_CONSTANT; d.src1_bank=HMS_PDS_CONSTANT;
    *out=d;
    return HMS_OK;
}

int hms_pds_launch_encode(uint64_t offset, uint32_t temps, uint64_t *word)
{
    if (!word) return HMS_E_ARGUMENT;
    if (offset & 3) return HMS_E_ALIGN;
    if (offset >= HMS_OFFSET_LIMIT || temps > 254) return HMS_E_RANGE;
    *word=(offset>>2) | (uint64_t)div_up(temps,2)<<33;
    return HMS_OK;
}
int hms_pds_launch_decode(uint64_t word, uint64_t *offset, uint32_t *temps)
{
    if (!offset || !temps) return HMS_E_ARGUMENT;
    if (word & ~UINT64_C(0x000000fe3fffffff)) return HMS_E_UNSUPPORTED;
    *offset=(word&UINT64_C(0x3fffffff))*4;
    *temps=(uint32_t)((word>>33)&127)*2;
    return HMS_OK;
}

int hms_pds_pointer_control_encode(uint32_t input, uint32_t last, uint32_t *out)
{
    uint32_t lane;
    if (!out || last > 1) return HMS_E_ARGUMENT;
    if (input > 252) return HMS_E_RANGE;
    if ((input & 3) == 3) return HMS_E_UNSUPPORTED; /* would cross a 128-bit destination quad */
    lane=input&3;
    *out=(last<<31) | (input/4)<<13 | 3u<<lane | 1u<<(4+2*(lane+1));
    return HMS_OK;
}
int hms_pds_pointer_control_decode(uint32_t word, uint32_t *input, uint32_t *last)
{
    uint32_t mask=word&15, lane, swizzle=(word>>4)&255, first;
    if (!input || !last) return HMS_E_ARGUMENT;
    if (word & UINT32_C(0x7c001000)) return HMS_E_UNSUPPORTED;
    if (mask == 3) lane=0;
    else if (mask == 6) lane=1;
    else if (mask == 12) lane=2;
    else return HMS_E_UNSUPPORTED;
    if (swizzle != (1u<<(2*(lane+1)))) return HMS_E_UNSUPPORTED;
    first=((word>>13)&8191)*4+lane;
    if (first > 252) return HMS_E_RANGE;
    *input=first; *last=word>>31;
    return HMS_OK;
}

static int direct_check(const struct hms_cdm_direct *d, uint32_t *volume)
{
    uint32_t n=1;
    if (!d || !volume) return HMS_E_ARGUMENT;
    if ((d->pds_data_offset | d->pds_code_offset) & 15) return HMS_E_ALIGN;
    if (d->pds_data_offset >= HMS_OFFSET_LIMIT || d->pds_code_offset >= HMS_OFFSET_LIMIT) return HMS_E_RANGE;
    if (!d->pds_data_words || d->pds_data_words > HMS_PDS_CONST_WORDS ||
        d->pds_temp_words > HMS_PDS_TEMP_WORDS || d->usc_unified_words > 254) return HMS_E_RANGE;
    for (unsigned j=0;j<3;j++) {
        if (!d->groups[j] || !d->local[j] || d->local[j] > 1024) return HMS_E_RANGE;
        if (d->local[j] > 128/n) return HMS_E_UNSUPPORTED;
        n*=d->local[j];
    }
    *volume=n;
    return HMS_OK;
}
int hms_cdm_encode(const struct hms_cdm_direct *d, void *bytes, size_t cap)
{
    uint8_t local[HMS_CDM_BYTES];
    uint32_t volume;
    int e=direct_check(d,&volume);
    if (e) return e;
    if (!bytes) return HMS_E_ARGUMENT;
    if (cap < sizeof local) return HMS_E_CAPACITY;
    store32(local,div_up(d->usc_unified_words,2)<<12 | div_up(d->pds_temp_words,8)<<7 |
                  div_up(d->pds_data_words,4)<<1 | 1u); /* target ANY */
    store32(local+4,(uint32_t)d->pds_data_offset);
    store32(local+8,(uint32_t)d->pds_code_offset);
    for (unsigned j=0;j<3;j++) store32(local+12+4*j,d->groups[j]-1);
    store32(local+24,(volume*8 < 128 ? volume*8 : 0)<<25);
    store32(local+28,(d->local[0]-1)<<20 | (d->local[1]-1)<<10 | (d->local[2]-1));
    store32(local+32,UINT32_C(0x80000000));
    memcpy(bytes,local,sizeof local);
    return HMS_OK;
}

int hms_cdm_decode(const void *bytes, size_t len, struct hms_cdm_decoded *out)
{
    struct hms_cdm_decoded d;
    const uint8_t *b=bytes;
    uint32_t k0,k1,k2,k8,k9,volume=1;
    if (!b || !out) return HMS_E_ARGUMENT;
    if (len != HMS_CDM_BYTES) return HMS_E_FORMAT;
    k0=load32(b); k1=load32(b+4); k2=load32(b+8); k8=load32(b+24); k9=load32(b+28);
    if ((k0 & UINT32_C(0xfff80001)) != 1 || (k1&15) || (k2&15) ||
        (k8 & UINT32_C(0x01ffffff)) || (k9&UINT32_C(0xc0000000)) ||
        load32(b+32) != UINT32_C(0x80000000)) return HMS_E_UNSUPPORTED;
    d.pds_data_words_allocated=((k0>>1)&63)*4;
    d.pds_temp_words_allocated=((k0>>7)&31)*8;
    d.usc_unified_words_allocated=((k0>>12)&127)*2;
    if (!d.pds_data_words_allocated || d.pds_data_words_allocated>192 || d.pds_temp_words_allocated>32) return HMS_E_RANGE;
    d.pds_data_offset=k1; d.pds_code_offset=k2;
    d.max_instances=k8>>25;
    for (unsigned j=0;j<3;j++) {
        uint32_t v=load32(b+12+j*4);
        if (v == UINT32_MAX) return HMS_E_RANGE; /* API's maximum count is UINT32_MAX */
        d.groups[j]=v+1;
        d.local[j]=((k9 >> (20-10*j))&1023)+1;
        if (d.local[j] > 128/volume) return HMS_E_UNSUPPORTED;
        volume*=d.local[j];
    }
    if (d.max_instances != (volume*8 < 128 ? volume*8 : 0)) return HMS_E_UNSUPPORTED;
    *out=d;
    return HMS_OK;
}

static const struct hms_heap_span *heap_at(const struct hms_heaps *h, uint32_t which)
{
    if (which==HMS_GENERAL) return &h->general;
    if (which==HMS_USC) return &h->usc;
    if (which==HMS_PDS) return &h->pds;
    return 0;
}
static int heaps_check(const struct hms_heaps *h)
{
    if (!h || h->page_size != 16384) return HMS_E_UNSUPPORTED;
    for (uint32_t i=1;i<=3;i++) {
        const struct hms_heap_span *s=heap_at(h,i);
        if (!s->base || !s->bytes || s->base >= HMS_VA_LIMIT || s->bytes > HMS_VA_LIMIT-s->base) return HMS_E_RANGE;
        if ((s->base|s->bytes) & (h->page_size-1)) return HMS_E_ALIGN;
        if (i!=HMS_GENERAL && s->bytes > HMS_OFFSET_LIMIT) return HMS_E_RANGE;
        for (uint32_t j=1;j<i;j++) {
            const struct hms_heap_span *t=heap_at(h,j);
            if (overlaps(s->base,s->bytes,t->base,t->bytes)) return HMS_E_ALIAS;
        }
    }
    return HMS_OK;
}
int hms_heaps_from_open(const struct hmgpu_open_out *o, struct hms_heaps *out)
{
    struct hms_heaps h;
    int e;
    if (!o || !out || o->size!=sizeof *o || o->abi_version!=HMGPU_ABI_VERSION) return HMS_E_ARGUMENT;
    if (o->backend!=HMGPU_BACKEND_PVR || o->gpu_id!=UINT64_C(0x470002099004bc) || !(o->caps&HMGPU_CAP_COMPUTE)) return HMS_E_DEPENDENCY;
    h.general=(struct hms_heap_span){o->va_base,o->va_size};
    h.usc=(struct hms_heap_span){o->usc_va_base,o->usc_va_size};
    h.pds=(struct hms_heap_span){o->pds_va_base,o->pds_va_size};
    h.page_size=o->page_size;
    e=heaps_check(&h);
    if (!e) *out=h;
    return e;
}
int hms_region_check(const struct hms_heaps *h, const struct hms_region *r,
                     uint32_t heap, uint32_t access, uint64_t required, uint64_t alignment,
                     uint64_t *va)
{
    const struct hms_heap_span *s;
    uint64_t a;
    int e=heaps_check(h);
    if (e) return e;
    if (!r || !va || !required || !power2(alignment) || !access || (access&~HMS_ACCESS)) return HMS_E_ARGUMENT;
    s=heap_at(h,heap);
    if (!s || r->heap!=heap || !r->bo.handle || r->bo.size!=sizeof r->bo ||
        r->bo.row_bytes || r->bo.format || !r->access || (r->access&~HMS_ACCESS) || (r->access&access)!=access) return HMS_E_ARGUMENT;
    if (!r->bo.bytes || (r->bo.gpu_va|r->bo.bytes)&(h->page_size-1)) return HMS_E_ALIGN;
    if (!contains(s->base,s->bytes,r->bo.gpu_va,r->bo.bytes) || !r->bytes ||
        r->offset>=r->bo.bytes || r->bytes>r->bo.bytes-r->offset || required>r->bytes) return HMS_E_RANGE;
    a=r->bo.gpu_va+r->offset;
    if (a & (alignment-1)) return HMS_E_ALIGN;
    *va=a;
    return HMS_OK;
}

static int desc_check(const struct hms_compute_desc *d, struct hms_compute_layout *l)
{
    struct hmusc_header h;
    uint64_t va;
    int e;
    if (!d || !l || !d->hmusc || d->hmusc_bytes<sizeof h) return HMS_E_ARGUMENT;
    if (hmusc_check(d->hmusc,d->hmusc_bytes,HMUSC_TARGET_DXT71,0)) return HMS_E_SHADER;
    memcpy(&h,d->hmusc,sizeof h);
    if (h.stage!=HMUSC_STAGE_COMPUTE || h.flags!=HMUSC_F_HAS_CODE || h.shareds || h.bind_count || h.inputs || h.outputs) return HMS_E_UNSUPPORTED;
    if (d->entry.profile!=HMS_PROFILE_SINGLE_COMPUTE || d->entry.temps!=h.temps ||
        d->entry.pointer_count>HMS_MAX_POINTERS || d->entry.temps>254 || d->entry.unified_words>254) return HMS_E_UNSUPPORTED;
    if ((d->entry.entry_offset&3) || d->entry.entry_offset>=h.code_len) return HMS_E_SHADER;
    for (unsigned j=0;j<3;j++) if (d->groups[j]!=1 || d->local[j]!=1) return HMS_E_UNSUPPORTED;
    e=hms_region_check(&d->heaps,&d->usc,HMS_USC,HMGPU_BO_READ,h.code_len,16,&va);
    if (e) return e;
    if (va-d->heaps.usc.base+d->entry.entry_offset>=HMS_OFFSET_LIMIT) return HMS_E_RANGE;
    for (unsigned i=0;i<d->entry.pointer_count;i++) {
        const struct hms_pointer_arg *p=&d->entry.pointers[i];
        if (!p->min_bytes || !p->access || (p->access&~HMS_ACCESS) ||
            (p->input_word&1) || p->input_word>252 || p->input_word+2>d->entry.unified_words) return HMS_E_SHADER;
        for (unsigned j=0;j<i;j++) if (d->entry.pointers[j].input_word==p->input_word) return HMS_E_ALIAS;
        e=hms_region_check(&d->heaps,&d->buffers[i],HMS_GENERAL,p->access,p->min_bytes,4,&va);
        if (e) return e;
    }
    if (!d->validate_usc) return HMS_E_DEPENDENCY;
    e=d->validate_usc(d->validate_cookie,d->hmusc,d->hmusc_bytes,&d->entry);
    if (e) return HMS_E_SHADER;
    l->pds_data_bytes=(4*d->entry.pointer_count+4)*4;
    l->pds_code_bytes=((d->entry.pointer_count+1)*4+15)&~15u;
    l->stream_bytes=HMS_CDM_BYTES;
    l->pds_alignment=16; l->stream_alignment=16; l->stream_guard=HMS_STREAM_GUARD;
    return HMS_OK;
}
int hms_compute_plan(const struct hms_compute_desc *d, struct hms_compute_layout *out)
{
    struct hms_compute_layout l;
    int e;
    if (!out) return HMS_E_ARGUMENT;
    e=desc_check(d,&l);
    if (!e) *out=l;
    return e;
}

static int storage_check(const struct hms_compute_desc *d, const struct hms_compute_storage *s,
                          const struct hms_compute_layout *l, uint64_t va[3])
{
    const struct hms_region *r[3];
    const void *cpu[3];
    uint32_t need[3];
    size_t cap[3];
    int e;
    if (!s) return HMS_E_ARGUMENT;
    r[0]=&s->pds_data; r[1]=&s->pds_code; r[2]=&s->stream;
    need[0]=l->pds_data_bytes; need[1]=l->pds_code_bytes; need[2]=l->stream_bytes;
    cpu[0]=s->data_cpu; cpu[1]=s->code_cpu; cpu[2]=s->stream_cpu;
    cap[0]=s->data_capacity; cap[1]=s->code_capacity; cap[2]=s->stream_capacity;
    for (unsigned i=0;i<3;i++) {
        if (!cpu[i]) return HMS_E_ARGUMENT;
        if (cap[i]<need[i]) return HMS_E_CAPACITY;
        e=hms_region_check(&d->heaps,r[i],i==2?HMS_GENERAL:HMS_PDS,HMGPU_BO_READ,need[i],16,&va[i]);
        if (e) return e;
        if (host_overlap(cpu[i],need[i],d,sizeof *d) || host_overlap(cpu[i],need[i],s,sizeof *s) ||
            host_overlap(cpu[i],need[i],d->hmusc,d->hmusc_bytes)) return HMS_E_ALIAS;
        for (unsigned j=0;j<i;j++) {
            if (overlaps(va[i],r[i]->bytes,va[j],r[j]->bytes) || host_overlap(cpu[i],need[i],cpu[j],need[j])) return HMS_E_ALIAS;
        }
        if (i==2) for (unsigned j=0;j<d->entry.pointer_count;j++) {
            const struct hms_region *b=&d->buffers[j];
            if (r[i]->bo.handle==b->bo.handle || overlaps(va[i],r[i]->bytes,b->bo.gpu_va+b->offset,b->bytes)) return HMS_E_ALIAS;
        }
    }
    /* Terminate cannot be in the last 64 bytes of a valid GPU page. No links or
     * cross-page streams in this deliberately small profile.
     */
    if ((va[2]&(d->heaps.page_size-1))+l->stream_bytes>d->heaps.page_size-HMS_STREAM_GUARD) return HMS_E_RANGE;
    return HMS_OK;
}

static int append_ref(struct hms_compute_product *p, const struct hms_region *r)
{
    for (unsigned i=0;i<p->bo_count;i++) if (p->bos[i].handle==r->bo.handle) {
        p->bos[i].access|=r->access;
        return HMS_OK;
    }
    if (p->bo_count>=HMS_MAX_POINTERS+4) return HMS_E_CAPACITY;
    p->bos[p->bo_count++]=(struct hmgpu_bo_ref){r->bo.handle,r->access};
    return HMS_OK;
}
static int product_make(const struct hms_compute_desc *d, const struct hms_compute_storage *s,
                         uint64_t stream, struct hms_compute_product *p)
{
    const struct hms_region *r[HMS_MAX_POINTERS+4];
    unsigned n=4+d->entry.pointer_count;
    r[0]=&s->stream; r[1]=&s->pds_data; r[2]=&s->pds_code; r[3]=&d->usc;
    for (unsigned i=0;i<d->entry.pointer_count;i++) r[4+i]=&d->buffers[i];
    /* A handle must identify one immutable allocation even across heap slices. */
    for (unsigned i=0;i<n;i++) for (unsigned j=0;j<i;j++) {
        if ((r[i]->bo.handle==r[j]->bo.handle) &&
            (r[i]->bo.gpu_va!=r[j]->bo.gpu_va || r[i]->bo.bytes!=r[j]->bo.bytes || r[i]->heap!=r[j]->heap)) return HMS_E_ALIAS;
        if (r[i]->bo.handle!=r[j]->bo.handle &&
            overlaps(r[i]->bo.gpu_va,r[i]->bo.bytes,r[j]->bo.gpu_va,r[j]->bo.bytes)) return HMS_E_ALIAS;
    }
    memset(p,0,sizeof *p);
    p->stream_va=stream; p->stream_bytes=HMS_CDM_BYTES;
    for (unsigned i=0;i<n;i++) {
        int e=append_ref(p,r[i]);
        if (e) return e;
    }
    return HMS_OK;
}

int hms_compute_build(const struct hms_compute_desc *d, const struct hms_compute_storage *s,
                      struct hms_compute_product *out)
{
    struct hms_compute_layout l;
    struct hms_compute_product p;
    struct hms_cdm_direct c;
    uint8_t data[HMS_DATA_WORDS*4]={0},code[HMS_CODE_BYTES]={0},stream[HMS_CDM_BYTES];
    uint64_t va[3],launch;
    uint32_t word,argc;
    int e;
    if (!out) return HMS_E_ARGUMENT;
    e=desc_check(d,&l); if (e) return e;
    e=storage_check(d,s,&l,va); if (e) return e;
    if (host_overlap(out,sizeof *out,s->data_cpu,l.pds_data_bytes) ||
        host_overlap(out,sizeof *out,s->code_cpu,l.pds_code_bytes) ||
        host_overlap(out,sizeof *out,s->stream_cpu,l.stream_bytes) ||
        host_overlap(out,sizeof *out,d,sizeof *d) || host_overlap(out,sizeof *out,s,sizeof *s) ||
        host_overlap(out,sizeof *out,d->hmusc,d->hmusc_bytes)) return HMS_E_ALIAS;
    e=product_make(d,s,va[2],&p); if (e) return e;
    argc=d->entry.pointer_count;
    for (unsigned i=0;i<argc;i++) {
        struct hms_pds_dout inst={HMS_DOUTW,0,0,HMS_PDS_CONSTANT,4*i,HMS_PDS_CONSTANT,4*i+2};
        uint64_t pointer=d->buffers[i].bo.gpu_va+d->buffers[i].offset;
        e=hms_pds_pointer_control_encode(d->entry.pointers[i].input_word,i+1==argc,&word); if (e) return e;
        store64(data+16*i,pointer); store32(data+16*i+8,word);
        e=hms_pds_dout_encode(&inst,&word); if (e) return e;
        store32(code+4*i,word);
    }
    e=hms_pds_launch_encode(d->usc.bo.gpu_va+d->usc.offset-d->heaps.usc.base+d->entry.entry_offset,d->entry.temps,&launch);
    if (e) return e;
    store64(data+16*argc,launch);
    {
        struct hms_pds_dout inst={HMS_DOUTU,1,0,HMS_PDS_CONSTANT,4*argc,HMS_PDS_CONSTANT,4*argc+2};
        e=hms_pds_dout_encode(&inst,&word); if (e) return e;
        store32(code+4*argc,word);
    }
    memset(&c,0,sizeof c);
    c.pds_data_offset=va[0]-d->heaps.pds.base; c.pds_code_offset=va[1]-d->heaps.pds.base;
    c.pds_data_words=l.pds_data_bytes/4; c.usc_unified_words=d->entry.unified_words;
    for (unsigned j=0;j<3;j++) { c.groups[j]=d->groups[j]; c.local[j]=d->local[j]; }
    e=hms_cdm_encode(&c,stream,sizeof stream); if (e) return e;
    memcpy(s->data_cpu,data,l.pds_data_bytes); memcpy(s->code_cpu,code,l.pds_code_bytes);
    memcpy(s->stream_cpu,stream,l.stream_bytes); *out=p;
    return HMS_OK;
}

int hms_compute_validate(const struct hms_compute_desc *d, const struct hms_compute_storage *s,
                         const struct hms_compute_product *product)
{
    struct hms_compute_layout l;
    struct hms_compute_product expected;
    struct hms_cdm_decoded c;
    struct hms_pds_dout inst;
    uint64_t va[3],offset;
    uint32_t input,last,temps,argc;
    const uint8_t *data,*code;
    int e;
    if (!product) return HMS_E_ARGUMENT;
    e=desc_check(d,&l); if (e) return e;
    e=storage_check(d,s,&l,va); if (e) return e;
    e=product_make(d,s,va[2],&expected); if (e) return e;
    if (product->stream_va!=expected.stream_va || product->stream_bytes!=expected.stream_bytes || product->bo_count!=expected.bo_count) return HMS_E_FORMAT;
    for (unsigned i=0;i<expected.bo_count;i++) if (product->bos[i].handle!=expected.bos[i].handle || product->bos[i].access!=expected.bos[i].access) return HMS_E_FORMAT;
    e=hms_cdm_decode(s->stream_cpu,l.stream_bytes,&c); if (e) return e;
    if (c.pds_data_offset!=va[0]-d->heaps.pds.base || c.pds_code_offset!=va[1]-d->heaps.pds.base ||
        c.pds_data_words_allocated!=l.pds_data_bytes/4 || c.pds_temp_words_allocated ||
        c.usc_unified_words_allocated!=div_up(d->entry.unified_words,2)*2) return HMS_E_FORMAT;
    for (unsigned j=0;j<3;j++) if (c.groups[j]!=d->groups[j] || c.local[j]!=d->local[j]) return HMS_E_FORMAT;
    data=s->data_cpu; code=s->code_cpu; argc=d->entry.pointer_count;
    for (unsigned i=0;i<argc;i++) {
        e=hms_pds_dout_decode(load32(code+4*i),&inst); if (e) return e;
        if (inst.kind!=HMS_DOUTW || inst.end || inst.conditional || inst.src0_word!=4*i || inst.src1_word!=4*i+2) return HMS_E_FORMAT;
        if (load64(data+16*i)!=d->buffers[i].bo.gpu_va+d->buffers[i].offset || load32(data+16*i+12)) return HMS_E_FORMAT;
        e=hms_pds_pointer_control_decode(load32(data+16*i+8),&input,&last); if (e) return e;
        if (input!=d->entry.pointers[i].input_word || last!=(i+1==argc)) return HMS_E_FORMAT;
    }
    e=hms_pds_dout_decode(load32(code+4*argc),&inst); if (e) return e;
    if (inst.kind!=HMS_DOUTU || !inst.end || inst.conditional || inst.src0_word!=4*argc || inst.src1_word!=4*argc+2) return HMS_E_FORMAT;
    e=hms_pds_launch_decode(load64(data+16*argc),&offset,&temps); if (e) return e;
    if (offset!=d->usc.bo.gpu_va+d->usc.offset-d->heaps.usc.base+d->entry.entry_offset || temps!=div_up(d->entry.temps,2)*2) return HMS_E_FORMAT;
    if (load64(data+16*argc+8)) return HMS_E_FORMAT;
    for (unsigned i=(argc+1)*4;i<l.pds_code_bytes;i++) if (code[i]) return HMS_E_FORMAT;
    return HMS_OK;
}

int hms_compute_job(const struct hms_compute_product *p, uint32_t first, struct hmgpu_job *out)
{
    struct hmgpu_job j;
    if (!p || !out || !p->stream_va || (p->stream_va&15) || p->stream_va>=HMS_VA_LIMIT ||
        p->stream_bytes!=HMS_CDM_BYTES || !p->bo_count || p->bo_count>HMS_MAX_POINTERS+4 ||
        first>UINT32_MAX-p->bo_count) return HMS_E_ARGUMENT;
    for (unsigned i=0;i<p->bo_count;i++) {
        if (!p->bos[i].handle || !p->bos[i].access || (p->bos[i].access&~HMS_ACCESS)) return HMS_E_ARGUMENT;
        for (unsigned k=0;k<i;k++) if (p->bos[i].handle==p->bos[k].handle) return HMS_E_ARGUMENT;
    }
    memset(&j,0,sizeof j);
    j.size=sizeof j; j.type=HMGPU_JOB_COMPUTE; j.stream_va=p->stream_va;
    j.stream_bytes=p->stream_bytes; j.bo_first=first; j.bo_count=p->bo_count;
    *out=j;
    return HMS_OK;
}

static int frozen_span(const struct hms_frozen_bo *bos, uint32_t nbo, uint32_t heap,
                        uint64_t va, uint64_t bytes, const struct hms_frozen_bo **bo,
                        const uint8_t **cpu)
{
    for (unsigned i=0;i<nbo;i++) if (bos[i].heap==heap &&
        contains(bos[i].bo.gpu_va,bos[i].bo.bytes,va,bytes)) {
        if (!(bos[i].access&HMGPU_BO_READ)) return HMS_E_ARGUMENT;
        *bo=&bos[i]; *cpu=(const uint8_t *)bos[i].cpu+(size_t)(va-bos[i].bo.gpu_va);
        return HMS_OK;
    }
    return HMS_E_RANGE;
}

int hms_compute_validate_frozen(const struct hms_heaps *heaps, const struct hmgpu_job *job,
    const struct hms_frozen_bo *bos, uint32_t nbo, hms_validate_frozen_usc_fn verify, void *cookie,
    struct hms_frozen_dispatch *out)
{
    struct hms_frozen_dispatch f;
    struct hms_cdm_decoded c;
    struct hms_pds_dout inst;
    const struct hms_frozen_bo *stream_bo,*data_bo,*code_bo,*usc_bo;
    const uint8_t *stream,*data,*code,*usc;
    uint32_t argc,code_bytes;
    uint64_t data_va,code_va,usc_offset;
    int e=heaps_check(heaps);
    if (e) return e;
    if (!job || !bos || !out || !nbo || nbo>HMS_MAX_POINTERS+4 || job->size!=sizeof *job ||
        job->bo_count!=nbo || job->bo_first>UINT32_MAX-nbo || job->type!=HMGPU_JOB_COMPUTE || job->flags || job->hwrt || job->pad ||
        job->fw_geom_bytes || job->fw_frag_bytes || job->stream_bytes!=HMS_CDM_BYTES || (job->stream_va&15)) return HMS_E_ARGUMENT;
    if (host_overlap(out,sizeof *out,job,sizeof *job) || host_overlap(out,sizeof *out,heaps,sizeof *heaps) ||
        host_overlap(out,sizeof *out,bos,nbo*sizeof *bos)) return HMS_E_ALIAS;
    for (unsigned i=0;i<sizeof job->fw_cmd;i++) if (job->fw_cmd[i]) return HMS_E_UNSUPPORTED;
    for (unsigned i=0;i<nbo;i++) {
        struct hms_region r={.bo=bos[i].bo,.offset=0,.bytes=bos[i].bo.bytes,.heap=bos[i].heap,.access=bos[i].access};
        uint64_t va;
        if (!bos[i].cpu || bos[i].bo.bytes>bos[i].cpu_bytes) return HMS_E_CAPACITY;
        e=hms_region_check(heaps,&r,r.heap,r.access,r.bytes,heaps->page_size,&va); if (e) return e;
        if (host_overlap(out,sizeof *out,bos[i].cpu,(size_t)bos[i].bo.bytes)) return HMS_E_ALIAS;
        for (unsigned j=0;j<i;j++) if (bos[i].bo.handle==bos[j].bo.handle ||
            overlaps(va,bos[i].bo.bytes,bos[j].bo.gpu_va,bos[j].bo.bytes) ||
            host_overlap(bos[i].cpu,(size_t)bos[i].bo.bytes,bos[j].cpu,(size_t)bos[j].bo.bytes)) return HMS_E_ALIAS;
    }
    if ((job->stream_va&(heaps->page_size-1))+job->stream_bytes>heaps->page_size-HMS_STREAM_GUARD) return HMS_E_RANGE;
    e=frozen_span(bos,nbo,HMS_GENERAL,job->stream_va,HMS_CDM_BYTES,&stream_bo,&stream); if (e) return e;
    e=hms_cdm_decode(stream,HMS_CDM_BYTES,&c); if (e) return e;
    for (unsigned j=0;j<3;j++) if (c.groups[j]!=1 || c.local[j]!=1) return HMS_E_UNSUPPORTED;
    if (c.pds_temp_words_allocated || c.pds_data_words_allocated<4 || c.pds_data_words_allocated>HMS_DATA_WORDS) return HMS_E_UNSUPPORTED;
    argc=c.pds_data_words_allocated/4-1;
    code_bytes=((argc+1)*4+15)&~15u;
    data_va=heaps->pds.base+c.pds_data_offset; code_va=heaps->pds.base+c.pds_code_offset;
    e=frozen_span(bos,nbo,HMS_PDS,data_va,c.pds_data_words_allocated*4,&data_bo,&data); if (e) return e;
    e=frozen_span(bos,nbo,HMS_PDS,code_va,code_bytes,&code_bo,&code); if (e) return e;
    if (overlaps(data_va,c.pds_data_words_allocated*4,code_va,code_bytes)) return HMS_E_ALIAS;
    (void)data_bo; (void)code_bo;
    memset(&f,0,sizeof f); f.pointer_count=argc; f.unified_words_allocated=c.usc_unified_words_allocated;
    for (unsigned i=0;i<argc;i++) {
        uint32_t input,last;
        const struct hms_frozen_bo *target=0;
        uint64_t ptr=load64(data+16*i);
        e=hms_pds_dout_decode(load32(code+4*i),&inst); if (e) return e;
        if (inst.kind!=HMS_DOUTW || inst.end || inst.conditional || inst.src0_word!=4*i || inst.src1_word!=4*i+2 || load32(data+16*i+12)) return HMS_E_FORMAT;
        e=hms_pds_pointer_control_decode(load32(data+16*i+8),&input,&last); if (e) return e;
        if ((input&1) || input+2>f.unified_words_allocated || last!=(i+1==argc) || (ptr&3)) return HMS_E_FORMAT;
        for (unsigned k=0;k<i;k++) if (f.pointers[k].input_word==input) return HMS_E_ALIAS;
        for (unsigned k=0;k<nbo;k++) if (bos[k].heap==HMS_GENERAL && contains(bos[k].bo.gpu_va,bos[k].bo.bytes,ptr,1)) target=&bos[k];
        if (!target) return HMS_E_RANGE;
        /* A writable pointer cannot name the same allocation as the stream,
         * even when the initial byte ranges happen not to overlap. The ISA
         * verifier cannot authorize writes into the control stream this way.
         */
        if (target==stream_bo) return HMS_E_ALIAS;
        f.pointers[i]=(struct hms_frozen_pointer){ptr,target->bo.bytes-(ptr-target->bo.gpu_va),input,target->bo.handle,target->access};
    }
    e=hms_pds_dout_decode(load32(code+argc*4),&inst); if (e) return e;
    if (inst.kind!=HMS_DOUTU || !inst.end || inst.conditional || inst.src0_word!=4*argc || inst.src1_word!=4*argc+2 || load64(data+16*argc+8)) return HMS_E_FORMAT;
    e=hms_pds_launch_decode(load64(data+16*argc),&usc_offset,&f.temps_allocated); if (e) return e;
    f.usc_entry_va=heaps->usc.base+usc_offset;
    e=frozen_span(bos,nbo,HMS_USC,f.usc_entry_va,4,&usc_bo,&usc); if (e) return e;
    f.usc=usc; f.usc_handle=usc_bo->bo.handle;
    f.usc_bytes_available=(size_t)(usc_bo->bo.bytes-(f.usc_entry_va-usc_bo->bo.gpu_va));
    for (unsigned i=(argc+1)*4;i<code_bytes;i++) if (code[i]) return HMS_E_FORMAT;
    if (!verify) return HMS_E_DEPENDENCY;
    if (verify(cookie,&f)) return HMS_E_SHADER;
    *out=f;
    return HMS_OK;
}

const char *hms_status_string(int e)
{
    switch (e) {
    case HMS_OK:return "format built/validated; no GPU execution claim";
    case HMS_E_ARGUMENT:return "invalid argument or BO descriptor";
    case HMS_E_RANGE:return "range, count, heap or guard overflow";
    case HMS_E_ALIGN:return "invalid alignment";
    case HMS_E_UNSUPPORTED:return "unsupported DXT form/resource/bank";
    case HMS_E_CAPACITY:return "output capacity too small";
    case HMS_E_FORMAT:return "stream differs from declared semantics";
    case HMS_E_DEPENDENCY:return "native capability or complete USC validator unavailable";
    case HMS_E_SHADER:return "unvalidated USC entry or metadata";
    case HMS_E_ALIAS:return "overlapping output/VA or inconsistent BO identity";
    default:return "unknown stream status";
    }
}
