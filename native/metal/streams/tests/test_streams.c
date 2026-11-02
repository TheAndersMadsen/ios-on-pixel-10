/* SPDX-License-Identifier: MIT
 * Original 2026 hackios streams tests. All VAs/BOs and USC fixture are MODELED.
 * The marker is not USC machine code and the test callback is not production
 * shader authority. Positive results establish host format/lifetime behavior.
 */
#include "hm_streams.h"
#include "hmusc.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned tests;
#define CHECK(x) do { tests++; if (!(x)) { fprintf(stderr,"FAIL %s:%d: %s\n",__FILE__,__LINE__,#x); exit(1); } } while (0)
static uint32_t rd(const void *p) { uint32_t w; memcpy(&w,p,4); return w; }
struct fixture {
    uint8_t blob[80], data[160], code[64], stream[64];
    struct hms_compute_desc desc;
    struct hms_compute_storage storage;
    struct hms_compute_product product;
    unsigned validated;
};
static int model_usc(void *cookie, const void *bytes, size_t length, const struct hms_entry *entry)
{
    unsigned *counter=cookie;
    (*counter)++;
    return length!=80 || rd((const uint8_t *)bytes+64)!=0x4d4f444c || entry->profile!=1;
}
static struct hms_region region(uint32_t handle,uint64_t va,uint32_t heap,uint32_t access,uint64_t off,uint64_t bytes)
{
    struct hms_region r;
    memset(&r,0,sizeof r);
    r.bo=(struct hmgpu_bo_out){sizeof r.bo,handle,va,16384,0,0};
    r.heap=heap; r.access=access; r.offset=off; r.bytes=bytes;
    return r;
}
static void init(struct fixture *f)
{
    struct hmusc_header h={0};
    uint32_t marker=0x4d4f444c;
    memset(f,0,sizeof *f);
    memcpy(h.magic,HMUSC_MAGIC,8); h.version=1; h.header_size=64; h.target=1;
    h.bvnc[0]=(71u<<16)|2; h.bvnc[1]=(2448u<<16)|1212;
    h.stage=HMUSC_STAGE_COMPUTE; h.flags=HMUSC_F_HAS_CODE;
    h.temps=3; h.code_off=64; h.code_len=16;
    memcpy(f->blob,&h,64); memcpy(f->blob+64,&marker,4);
    f->desc.heaps=(struct hms_heaps){{UINT64_C(0x8000000000),UINT64_C(0x2000000000)},
        {UINT64_C(0xe000000000),UINT64_C(0xfe000000)},
        {UINT64_C(0xda00000000),UINT64_C(0x100000000)},16384};
    f->desc.hmusc=f->blob; f->desc.hmusc_bytes=sizeof f->blob;
    f->desc.entry=(struct hms_entry){.profile=1,.temps=3,.unified_words=2,.pointer_count=1,
        .pointers={{0,12,HMGPU_BO_READ|HMGPU_BO_WRITE}}};
    f->desc.validate_usc=model_usc; f->desc.validate_cookie=&f->validated;
    f->desc.usc=region(1,UINT64_C(0xe000210000),HMS_USC,HMGPU_BO_READ,0,16);
    f->desc.buffers[0]=region(4,UINT64_C(0x8000020000),HMS_GENERAL,3,4,12);
    for (unsigned i=0;i<3;i++) f->desc.groups[i]=f->desc.local[i]=1;
    f->storage.pds_data=region(2,UINT64_C(0xda00010000),HMS_PDS,1,0,160);
    f->storage.pds_code=region(2,UINT64_C(0xda00010000),HMS_PDS,1,256,64);
    f->storage.stream=region(3,UINT64_C(0x8000010000),HMS_GENERAL,1,0,64);
    f->storage.data_cpu=f->data; f->storage.code_cpu=f->code; f->storage.stream_cpu=f->stream;
    f->storage.data_capacity=sizeof f->data; f->storage.code_capacity=sizeof f->code; f->storage.stream_capacity=sizeof f->stream;
}
static void refusals_unchanged(struct fixture *f)
{
    struct hms_compute_product old;
    uint8_t data[160],code[64],stream[64];
    memset(f->data,0x91,sizeof f->data); memset(f->code,0x92,sizeof f->code); memset(f->stream,0x93,sizeof f->stream);
    memset(&f->product,0x94,sizeof f->product);
    memcpy(data,f->data,sizeof data); memcpy(code,f->code,sizeof code); memcpy(stream,f->stream,sizeof stream); old=f->product;
    CHECK(hms_compute_build(&f->desc,&f->storage,&f->product)!=0);
    CHECK(!memcmp(data,f->data,sizeof data) && !memcmp(code,f->code,sizeof code) &&
          !memcmp(stream,f->stream,sizeof stream) && !memcmp(&old,&f->product,sizeof old));
}
static void raw_formats(void)
{
    uint32_t w,input,last,temps;
    uint64_t q,offset;
    struct hms_pds_dout i={HMS_DOUTU,1,0,1,0,1,2},j;
    CHECK(hms_pds_dout_encode(&i,&w)==0 && w==0xf4001002);
    CHECK(hms_pds_dout_decode(0xf4002812,&j)==0 && j.src0_word==4 && j.src1_word==5 && j.kind==2 && j.end);
    CHECK(hms_pds_dout_decode(0xf4001002,&j)==0 && !memcmp(&i,&j,sizeof i));
    i.src0_word=190; i.src1_word=191;
    CHECK(hms_pds_dout_encode(&i,&w)==0 && hms_pds_dout_decode(w,&j)==0 && !memcmp(&i,&j,sizeof i));
    i.src0_word=191; w=0x12345678;
    CHECK(hms_pds_dout_encode(&i,&w)==HMS_E_ALIGN && w==0x12345678);
    i.src0_word=192; CHECK(hms_pds_dout_encode(&i,&w)==HMS_E_RANGE);
    i.src0_word=0; i.src1_bank=2; CHECK(hms_pds_dout_encode(&i,&w)==HMS_E_UNSUPPORTED);
    CHECK(hms_pds_dout_decode(0xf4101002,&j)==HMS_E_FORMAT);
    CHECK(hms_pds_dout_decode(0xf4001302,&j)==HMS_E_UNSUPPORTED); /* temp-bank src0 */
    CHECK(hms_pds_dout_decode(0xf4001800,&j)==HMS_E_UNSUPPORTED); /* DOUTD absent */
    CHECK(hms_pds_launch_encode(0x12345678,3,&q)==0 && q==UINT64_C(0x4048d159e));
    CHECK(hms_pds_launch_decode(q,&offset,&temps)==0 && offset==0x12345678 && temps==4);
    CHECK(hms_pds_launch_encode(0xfffffffc,254,&q)==0 && q==UINT64_C(0xfe3fffffff));
    CHECK(hms_pds_launch_encode(UINT64_C(0x100000000),0,&q)==HMS_E_RANGE);
    CHECK(hms_pds_launch_encode(2,0,&q)==HMS_E_ALIGN);
    CHECK(hms_pds_launch_encode(0,255,&q)==HMS_E_RANGE);
    CHECK(hms_pds_launch_decode(UINT64_C(1)<<32,&offset,&temps)==HMS_E_UNSUPPORTED);
    CHECK(hms_pds_pointer_control_encode(0,1,&w)==0 && w==0x80000043);
    CHECK(hms_pds_pointer_control_encode(2,1,&w)==0 && w==0x8000040c);
    CHECK(hms_pds_pointer_control_encode(125,1,&w)==0 && w==0x8003e106);
    for (input=0;input<253;input++) if ((input&3)!=3) {
        uint32_t actual;
        CHECK(hms_pds_pointer_control_encode(input,0,&w)==0 && hms_pds_pointer_control_decode(w,&actual,&last)==0 && actual==input && !last);
    }
    CHECK(hms_pds_pointer_control_encode(3,1,&w)==HMS_E_UNSUPPORTED);
    CHECK(hms_pds_pointer_control_decode(0x90000043,&input,&last)==HMS_E_UNSUPPORTED); /* common store */
    CHECK(hms_pds_pointer_control_decode(0x800000c3,&input,&last)==HMS_E_UNSUPPORTED); /* bad swizzle */
}
static void cdm_formats(void)
{
    struct hms_cdm_direct d={0x1000,0x2000,12,0,2,{1,1,1},{1,1,1}};
    struct hms_cdm_decoded decoded;
    uint32_t expected[]={0x1007,0x1000,0x2000,0,0,0,0x10000000,0,0x80000000};
    uint8_t b[37],old[37];
    CHECK(hms_cdm_encode(&d,b+1,36)==0 && !memcmp(b+1,expected,36));
    CHECK(hms_cdm_decode(b+1,36,&decoded)==0 && decoded.usc_unified_words_allocated==2 && decoded.max_instances==8);
    d.pds_data_words=192; d.pds_temp_words=32; d.usc_unified_words=253;
    d.groups[0]=UINT32_MAX; d.local[0]=16; d.local[1]=8;
    CHECK(hms_cdm_encode(&d,b,36)==0 && hms_cdm_decode(b,36,&decoded)==0 && decoded.max_instances==0 && decoded.groups[0]==UINT32_MAX && decoded.usc_unified_words_allocated==254);
    memset(b,0xa5,sizeof b); memcpy(old,b,sizeof b); d.pds_data_offset=1;
    CHECK(hms_cdm_encode(&d,b,36)==HMS_E_ALIGN && !memcmp(b,old,sizeof b));
    d.pds_data_offset=0; d.local[2]=2;
    CHECK(hms_cdm_encode(&d,b,36)==HMS_E_UNSUPPORTED);
    d.local[2]=1; d.groups[1]=0; CHECK(hms_cdm_encode(&d,b,36)==HMS_E_RANGE);
    d.groups[1]=1; d.pds_temp_words=33; CHECK(hms_cdm_encode(&d,b,36)==HMS_E_RANGE);
    d.pds_temp_words=32; d.pds_data_offset=UINT64_C(0x100000000); CHECK(hms_cdm_encode(&d,b,36)==HMS_E_RANGE);
    CHECK(hms_cdm_decode(expected,35,&decoded)==HMS_E_FORMAT);
    expected[6]|=1; CHECK(hms_cdm_decode(expected,36,&decoded)==HMS_E_UNSUPPORTED); /* unknown shared allocation */
    expected[6]=0x10000000; expected[0]|=0x20000000; CHECK(hms_cdm_decode(expected,36,&decoded)==HMS_E_UNSUPPORTED); /* indirect */
}
static void success_and_relocation(void)
{
    struct fixture f;
    struct hms_compute_layout layout;
    struct hmgpu_job job;
    uint8_t no_fw[1024]={0};
    uint32_t expected[]={0x1005,0x10000,0x10100,0,0,0,0x10000000,0,0x80000000};
    init(&f);
    CHECK(hms_compute_plan(&f.desc,&layout)==0 && layout.pds_data_bytes==32 && layout.pds_code_bytes==16 && layout.stream_bytes==36);
    CHECK(hms_compute_build(&f.desc,&f.storage,&f.product)==0);
    CHECK(f.product.bo_count==4 && f.product.bos[1].handle==2 && f.product.bos[3].handle==4 && f.product.bos[3].access==3);
    CHECK(!memcmp(f.stream,expected,36) && rd(f.data)==0x20004 && rd(f.data+4)==0x80 && rd(f.data+8)==0x80000043);
    CHECK(rd(f.code)==0xf0001001 && rd(f.code+4)==0xf4003012 && rd(f.data+16)==0x84000 && rd(f.data+20)==4);
    CHECK(hms_compute_validate(&f.desc,&f.storage,&f.product)==0 && f.validated==3);
    CHECK(hms_compute_job(&f.product,5,&job)==0 && job.size==sizeof job && job.type==1 && job.bo_first==5 && job.bo_count==4 &&
          job.stream_va==f.product.stream_va && job.stream_bytes==36 && !job.flags && !job.hwrt && !job.fw_geom_bytes && !job.fw_frag_bytes && !memcmp(job.fw_cmd,no_fw,1024));
    CHECK(hms_compute_job(&f.product,UINT32_MAX,&job)==HMS_E_ARGUMENT);
    f.desc.usc.bo.gpu_va+=16384; f.desc.usc.offset=16; f.desc.usc.bytes=16; f.desc.entry.entry_offset=4;
    f.storage.pds_data.offset=16; f.storage.pds_code.offset=512;
    CHECK(hms_compute_build(&f.desc,&f.storage,&f.product)==0 && rd(f.data+16)==0x85005 && rd(f.stream+4)==0x10010 && rd(f.stream+8)==0x10200);
    CHECK(hms_compute_validate(&f.desc,&f.storage,&f.product)==0);
    f.desc.entry.pointer_count=2; f.desc.entry.unified_words=4; f.desc.entry.pointers[1]=(struct hms_pointer_arg){2,12,1};
    f.desc.buffers[1]=f.desc.buffers[0]; f.desc.buffers[1].access=1;
    CHECK(hms_compute_build(&f.desc,&f.storage,&f.product)==0 && f.product.bo_count==4 && rd(f.data+8)==0x43 && rd(f.data+24)==0x8000040c);
    CHECK(hms_compute_validate(&f.desc,&f.storage,&f.product)==0);
    f.desc.entry.pointer_count=8; f.desc.entry.unified_words=16;
    for (unsigned i=1;i<8;i++) {
        f.desc.entry.pointers[i]=(struct hms_pointer_arg){2*i,12,1};
        f.desc.buffers[i]=f.desc.buffers[0]; f.desc.buffers[i].offset+=i*16; f.desc.buffers[i].access=1;
    }
    CHECK(hms_compute_build(&f.desc,&f.storage,&f.product)==0 && hms_compute_validate(&f.desc,&f.storage,&f.product)==0 && f.product.bo_count==4);
    CHECK(hms_compute_plan(&f.desc,&layout)==0 && layout.pds_data_bytes==144 && layout.pds_code_bytes==48);
    f.desc.entry.pointer_count=0; f.desc.entry.unified_words=0;
    CHECK(hms_compute_build(&f.desc,&f.storage,&f.product)==0 && hms_compute_validate(&f.desc,&f.storage,&f.product)==0 && f.product.bo_count==3);
}
static void failure_atomicity(void)
{
    struct fixture f;
    struct hmusc_header h;
    init(&f); f.desc.validate_usc=0; refusals_unchanged(&f);
    init(&f); f.blob[64]=0; refusals_unchanged(&f);
    init(&f); f.desc.usc.offset=16380; refusals_unchanged(&f);
    init(&f); f.desc.entry.pointer_count=9; refusals_unchanged(&f);
    init(&f); f.desc.entry.temps=2; refusals_unchanged(&f);
    init(&f); f.desc.entry.unified_words=1; refusals_unchanged(&f);
    init(&f); f.desc.entry.pointers[0].input_word=1; refusals_unchanged(&f);
    init(&f); f.desc.entry.pointers[0].access=8; refusals_unchanged(&f);
    init(&f); f.desc.buffers[0].bytes=8; refusals_unchanged(&f);
    init(&f); f.desc.buffers[0].offset=UINT64_MAX; refusals_unchanged(&f);
    init(&f); f.desc.buffers[0].bo.gpu_va=UINT64_MAX-16383; refusals_unchanged(&f);
    init(&f); f.desc.buffers[0].access=1; refusals_unchanged(&f);
    init(&f); f.desc.buffers[0].bo.size=0; refusals_unchanged(&f);
    init(&f); f.storage.pds_code.offset=16; refusals_unchanged(&f);
    init(&f); f.storage.code_cpu=f.data; refusals_unchanged(&f);
    init(&f); f.storage.pds_data.bo.handle=4; refusals_unchanged(&f);
    init(&f); f.storage.stream=f.desc.buffers[0]; refusals_unchanged(&f);
    init(&f); f.storage.stream.offset=16320; f.storage.stream.bytes=64; refusals_unchanged(&f);
    init(&f); f.storage.data_capacity=31; refusals_unchanged(&f);
    init(&f); f.desc.local[0]=2; refusals_unchanged(&f);
    init(&f); f.desc.heaps.pds.base=f.desc.heaps.usc.base; refusals_unchanged(&f);
    init(&f); memcpy(&h,f.blob,64); h.shareds=1; memcpy(f.blob,&h,64); refusals_unchanged(&f);
    init(&f); memcpy(&h,f.blob,64); h.target=HMUSC_TARGET_ROGUE; memcpy(f.blob,&h,64); refusals_unchanged(&f);
    init(&f); CHECK(hms_compute_build(&f.desc,&f.storage,(struct hms_compute_product *)f.data)==HMS_E_ALIAS);
    init(&f); f.desc.entry.pointer_count=2; f.desc.entry.pointers[1]=f.desc.entry.pointers[0]; f.desc.buffers[1]=f.desc.buffers[0]; refusals_unchanged(&f);
}
static void validator_corruptions(void)
{
    struct fixture f;
    struct hms_compute_layout l;
    unsigned mutations=0;
    uint8_t *areas[3]; uint32_t lens[3];
    init(&f); CHECK(hms_compute_plan(&f.desc,&l)==0 && hms_compute_build(&f.desc,&f.storage,&f.product)==0);
    areas[0]=f.data; areas[1]=f.code; areas[2]=f.stream;
    lens[0]=l.pds_data_bytes; lens[1]=l.pds_code_bytes; lens[2]=l.stream_bytes;
    for (unsigned a=0;a<3;a++) for (unsigned b=0;b<lens[a];b++) for (unsigned bit=0;bit<8;bit++) {
        areas[a][b]^=(uint8_t)(1u<<bit);
        if (!hms_compute_validate(&f.desc,&f.storage,&f.product)) {
            fprintf(stderr,"accepted corruption area=%u byte=%u bit=%u\n",a,b,bit); exit(1);
        }
        areas[a][b]^=(uint8_t)(1u<<bit); mutations++;
    }
    CHECK(mutations==672 && hms_compute_validate(&f.desc,&f.storage,&f.product)==0);
    f.product.bo_count--; CHECK(hms_compute_validate(&f.desc,&f.storage,&f.product)==HMS_E_FORMAT);
    f.product.bo_count++; f.product.bos[3].access=1; CHECK(hms_compute_validate(&f.desc,&f.storage,&f.product)==HMS_E_FORMAT);
    printf("672 single-bit data/code/CDM corruptions rejected (separate from case count)\n");
}
static void heap_contract(void)
{
    struct fixture f;
    struct hms_heaps h;
    struct hmgpu_open_out o={0};
    init(&f); o.size=sizeof o; o.abi_version=1; o.backend=2; o.page_size=16384;
    o.gpu_id=UINT64_C(0x470002099004bc); o.caps=HMGPU_CAP_COMPUTE;
    o.va_base=f.desc.heaps.general.base; o.va_size=f.desc.heaps.general.bytes;
    o.usc_va_base=f.desc.heaps.usc.base; o.usc_va_size=f.desc.heaps.usc.bytes;
    o.pds_va_base=f.desc.heaps.pds.base; o.pds_va_size=f.desc.heaps.pds.bytes;
    CHECK(hms_heaps_from_open(&o,&h)==0 && h.pds.base==o.pds_va_base);
    o.caps=0; CHECK(hms_heaps_from_open(&o,&h)==HMS_E_DEPENDENCY);
    o.caps=2; o.backend=1; CHECK(hms_heaps_from_open(&o,&h)==HMS_E_DEPENDENCY);
    o.backend=2; o.va_size=UINT64_MAX; CHECK(hms_heaps_from_open(&o,&h)==HMS_E_RANGE);
}
static int model_frozen_usc(void *cookie,const struct hms_frozen_dispatch *f)
{
    unsigned *called=cookie;
    (*called)++;
    return f->usc_bytes_available<4 || rd(f->usc)!=0x4d4f444c || f->pointer_count!=1 ||
        f->temps_allocated!=4 || f->unified_words_allocated!=2 || f->pointers[0].va!=UINT64_C(0x8000020004) ||
        f->pointers[0].bytes_available<12 || f->pointers[0].access!=3;
}
static void frozen_hmgu_closure(void)
{
    struct fixture f;
    struct hmgpu_job job;
    struct hms_frozen_bo bos[4];
    struct hms_frozen_dispatch result,old;
    unsigned calls=0;
    init(&f); CHECK(hms_compute_build(&f.desc,&f.storage,&f.product)==0 && hms_compute_job(&f.product,0,&job)==0);
    memset(bos,0,sizeof bos);
    bos[0].bo=f.storage.stream.bo; bos[0].heap=HMS_GENERAL; bos[0].access=1;
    bos[1].bo=f.storage.pds_data.bo; bos[1].heap=HMS_PDS; bos[1].access=1;
    bos[2].bo=f.desc.usc.bo; bos[2].heap=HMS_USC; bos[2].access=1;
    bos[3].bo=f.desc.buffers[0].bo; bos[3].heap=HMS_GENERAL; bos[3].access=3;
    for (unsigned i=0;i<4;i++) { bos[i].cpu=calloc(1,16384); bos[i].cpu_bytes=16384; CHECK(bos[i].cpu); }
    memcpy((void *)bos[0].cpu,f.stream,36); memcpy((void *)bos[1].cpu,f.data,32);
    memcpy((uint8_t *)bos[1].cpu+256,f.code,16); memcpy((void *)bos[2].cpu,f.blob+64,16);
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==0 && calls==1 && result.usc_entry_va==f.desc.usc.bo.gpu_va && result.usc_handle==1);
    memset(&result,0xad,sizeof result); old=result;
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,0,0,&result)==HMS_E_DEPENDENCY && !memcmp(&old,&result,sizeof old));
    ((uint8_t *)bos[2].cpu)[0]^=1;
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==HMS_E_SHADER && !memcmp(&old,&result,sizeof old));
    ((uint8_t *)bos[2].cpu)[0]^=1;
    ((uint8_t *)bos[1].cpu)[256]^=0x80;
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==HMS_E_FORMAT);
    ((uint8_t *)bos[1].cpu)[256]^=0x80;
    { uint64_t ptr=f.storage.stream.bo.gpu_va+1024; memcpy((void *)bos[1].cpu,&ptr,8); }
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==HMS_E_ALIAS);
    memcpy((void *)bos[1].cpu,f.data,8);
    bos[2].cpu_bytes=15; CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==HMS_E_CAPACITY);
    bos[2].cpu_bytes=16384; job.fw_cmd[1023]=1;
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==HMS_E_UNSUPPORTED);
    job.fw_cmd[1023]=0; bos[2].access=2;
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==HMS_E_ARGUMENT);
    bos[2].access=1;
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,(struct hms_frozen_dispatch *)bos[0].cpu)==HMS_E_ALIAS);
    CHECK(hms_compute_validate_frozen(&f.desc.heaps,&job,bos,4,model_frozen_usc,&calls,&result)==0);
    for (unsigned i=0;i<4;i++) free((void *)bos[i].cpu);
}
int main(void)
{
    raw_formats(); cdm_formats(); success_and_relocation(); failure_atomicity(); validator_corruptions(); heap_contract(); frozen_hmgu_closure();
    printf("streams host modeled format suite: %u checks PASS; no GPU execution\n",tests);
    return 0;
}
