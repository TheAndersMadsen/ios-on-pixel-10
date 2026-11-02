/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Host resource tests, not USC shaders.
 * Every VA/BO is an explicitly modeled host allocation. No marker validator.
 */
#include "hm_shared.h"
#include "hm_isa_memory.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define PAGE 16384u
static unsigned cases;
#define REQUIRE(x) do { if(!(x)){fprintf(stderr,"FAIL line%d: %s\n",__LINE__,#x);exit(1);} }while(0)
static unsigned char mem[4][PAGE];
static struct hmsr_desc d;
static struct hmsr_storage s;
static struct hmsr_product p;
static struct hms_frozen_bo bos[4];
static struct hmgpu_job job;
static uint32_t u32(const void *p) { const unsigned char *b=p;return (uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24; }
static void w32(void *p,uint32_t v){unsigned char *b=p;for(unsigned i=0;i<4;i++)b[i]=(unsigned char)(v>>(8*i));}
static struct hms_region region(unsigned index,unsigned off,unsigned bytes) {
    return (struct hms_region){bos[index].bo,off,bytes,bos[index].heap,bos[index].access};
}
static void init(void) {
    memset(mem,0xcc,sizeof mem);memset(&d,0,sizeof d);memset(&s,0,sizeof s);memset(&p,0,sizeof p);
    d.heaps=(struct hms_heaps){{UINT64_C(0x8000000000),0x10000000},{UINT64_C(0xe000000000),0x10000000},{UINT64_C(0xda00000000),0x10000000},PAGE};
    const uint64_t vas[]={UINT64_C(0x8000010000),UINT64_C(0x8000020000),UINT64_C(0xda00000000),UINT64_C(0xe000000000)};
    const unsigned heaps[]={HMS_GENERAL,HMS_GENERAL,HMS_PDS,HMS_USC};
    for(unsigned i=0;i<4;i++)bos[i]=(struct hms_frozen_bo){{sizeof(struct hmgpu_bo_out),i+1,vas[i],PAGE,0,0},heaps[i],i==1?HMGPU_BO_READ|HMGPU_BO_WRITE:HMGPU_BO_READ,mem[i],PAGE};
    /* Resource layout fixture only. USC bytes deliberately stay arbitrary.
     * No validator accepts them, and this test never submits/claims code. */
    d.usc=region(3,0,64);d.code_bytes=64;d.entry_offset=4;d.temps=5;d.unified_words=0;d.shared_words=6;
    d.input_count=3;
    d.inputs[0]=(struct hmsr_input){.word=0,.kind=HMSR_POINTER64,.min_bytes=12,.buffer=region(1,32,64)};
    d.inputs[1]=(struct hmsr_input){.word=2,.kind=HMSR_LITERAL32,.literal=0x3f800000};
    d.inputs[2]=(struct hmsr_input){.word=5,.kind=HMSR_LITERAL32,.literal=0xffffffff};
    s.init_data=(struct hmsr_segment){region(2,0,256),mem[2],256};
    s.init_code=(struct hmsr_segment){region(2,0x400,64),mem[2]+0x400,64};
    s.main_data=(struct hmsr_segment){region(2,0x800,16),mem[2]+0x800,16};
    s.main_code=(struct hmsr_segment){region(2,0x900,16),mem[2]+0x900,16};
    s.stream=(struct hmsr_segment){region(0,0,128),mem[0],128};
    memset(&job,0,sizeof job);job.size=sizeof job;job.type=HMGPU_JOB_COMPUTE;job.stream_va=vas[0];job.stream_bytes=HMSR_STREAM_BYTES;job.bo_count=4;
}
static void resource_success(void) {
    struct hmsr_layout l;struct hmsr_frozen_resources r;
    REQUIRE(hmsr_plan(&d,&l)==HMS_OK);REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);
    REQUIRE(l.shared_words_allocated==16 && l.init_data_bytes==128 && l.init_code_bytes==32 && l.stream_bytes==68);
    REQUIRE(p.bo_count==4 && p.stream_va==job.stream_va && p.stream_bytes==68);
    REQUIRE(hmsr_decode_resources(&d.heaps,&job,bos,4,&r)==HMS_OK);
    REQUIRE(r.shared_words_allocated==16 && r.temps_allocated==6 && r.unified_words_allocated==0);
    REQUIRE(r.usc_entry_va==bos[3].bo.gpu_va+4 && r.usc==(unsigned char *)bos[3].cpu+4 && r.usc_bytes_available==PAGE-4 && r.resource_bo_mask==13);
    REQUIRE(((uint64_t)r.shared_image[0]|(uint64_t)r.shared_image[1]<<32)==bos[1].bo.gpu_va+32);
    REQUIRE(r.shared_image[2]==0x3f800000 && r.shared_image[5]==0xffffffff);
    for(unsigned i=6;i<16;i++)REQUIRE(r.shared_image[i]==0);
    REQUIRE(r.shared_image[3]==0 && r.shared_image[4]==0);
    REQUIRE(u32(mem[0])==0x10 && u32(mem[0]+4)==2 && u32(mem[0]+24)==0x02000001);
    REQUIRE(u32(mem[2]+8)==0x10000043 && u32(mem[2]+7*16+8)==0x9000640c);
    REQUIRE(mem[0][68]==0xcc && mem[2][128]==0xcc && mem[2][0x420]==0xcc);
    cases++;
}
static void reject_build(void) {
    unsigned char before[sizeof mem];struct hmsr_product previous=p;
    memcpy(before,mem,sizeof mem);int e=hmsr_build(&d,&s,&p);
    REQUIRE(e!=HMS_OK && !memcmp(before,mem,sizeof mem) && !memcmp(&p,&previous,sizeof p));cases++;
}
static void reject_decode(void) {
    struct hmsr_frozen_resources r,old;memset(&r,0xa6,sizeof r);old=r;
    int e=hmsr_decode_resources(&d.heaps,&job,bos,4,&r);
    REQUIRE(e!=HMS_OK && !memcmp(&r,&old,sizeof r));cases++;
}
static void isa_shared_bridge(void) {
    init();struct hmsr_frozen_resources frozen;
    REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK && hmsr_decode_resources(&d.heaps,&job,bos,4,&frozen)==HMS_OK);
    uint64_t pointer_va=(uint64_t)frozen.shared_image[0]|(uint64_t)frozen.shared_image[1]<<32;
    REQUIRE(pointer_va>=bos[1].bo.gpu_va && pointer_va-bos[1].bo.gpu_va<bos[1].bo.bytes);
    struct hmisa_pointer ptr={.binding=0,.bank=HMISA_SHARED,.index=0,.access=bos[1].access,
        .byte_origin=0,.bytes_available=bos[1].bo.bytes-(pointer_va-bos[1].bo.gpu_va)};
    struct hmisa_memory_request req[]={{0,HMISA_READ,0,0,0},{0,HMISA_READ,1,0,4},{0,HMISA_WRITE,2,0,8}};
    /* Explicit individual group schedules, not a whole-stage scheduler. There
     * is deliberately no ALU/END concatenation or runnable-stage assertion. */
    struct hmisa_schedule schedule[]={{HMISA_ISSUE_DESCHED,0,0,0},{HMISA_ISSUE_DESCHED,1,0,0},{HMISA_ISSUE_SYNC,0,3,0}};
    struct hmisa_memory_product fragments[3];
    REQUIRE(hmisa_memory_lower_many(HMISA_ENABLE_GROUPS,&ptr,1,req,schedule,3,frozen.temps_allocated,fragments,3)==HMISA_OK);
    for(unsigned i=0;i<3;i++) {
        struct hmisa_dma raw;REQUIRE(hmisa_dma_decode(fragments[i].code,16,&raw)==HMISA_OK);
        REQUIRE(raw.address_bank==HMISA_SHARED && raw.address_index==0 && raw.data_reg==i && raw.x_bytes==4 && raw.y_count==1);
        REQUIRE(raw.stride==(i?i*4:1) && raw.add_first==(i!=0) && fragments[i].begin_byte==i*4 && fragments[i].end_byte==i*4+4);
    }
    cases++;
    struct hmisa_memory_product before[3];memset(fragments,0x6e,sizeof fragments);memcpy(before,fragments,sizeof before);
    ptr.bytes_available=8;
    REQUIRE(hmisa_memory_lower_many(HMISA_ENABLE_GROUPS,&ptr,1,req,schedule,3,frozen.temps_allocated,fragments,3)==HMISA_E_BOUNDS && !memcmp(before,fragments,sizeof before));cases++;
    ptr.bytes_available=12;ptr.index=1;
    REQUIRE(hmisa_memory_lower_many(HMISA_ENABLE_GROUPS,&ptr,1,req,schedule,3,frozen.temps_allocated,fragments,3)!=HMISA_OK && !memcmp(before,fragments,sizeof before));cases++;
}
int main(void) {
    init();resource_success();
    init();d.shared_words=32;d.unified_words=11;d.temps=254;d.inputs[2].word=31;
    struct hmsr_frozen_resources r;REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);REQUIRE(hmsr_decode_resources(&d.heaps,&job,bos,4,&r)==HMS_OK);
    REQUIRE(r.shared_words_allocated==32 && r.shared_image[31]==0xffffffff && r.unified_words_allocated==12 && r.temps_allocated==254 && r.shared_image[30]==0);cases++;
    init();d.input_count=0;d.shared_words=1;d.temps=0;REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);job.bo_count=3;
    struct hms_frozen_bo empty_bos[]={bos[0],bos[2],bos[3]};
    REQUIRE(hmsr_decode_resources(&d.heaps,&job,empty_bos,3,&r)==HMS_OK);for(unsigned i=0;i<16;i++)REQUIRE(r.shared_image[i]==0);REQUIRE(p.bo_count==3);cases++;
    init();d.inputs[3]=d.inputs[0];d.inputs[3].word=4;d.input_count=4;d.inputs[2].word=3;
    REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK && p.bo_count==4);cases++;
    init();d.shared_words=0;reject_build();init();d.shared_words=33;reject_build();init();d.temps=255;reject_build();
    init();d.unified_words=255;reject_build();init();d.entry_offset=64;reject_build();init();d.entry_offset=3;reject_build();
    init();d.inputs[0].word=1;reject_build();init();d.inputs[0].word=5;reject_build();
    init();d.inputs[1].word=1;reject_build();init();d.inputs[1].word=31;reject_build();init();d.inputs[1].kind=77;reject_build();
    init();d.inputs[0].min_bytes=65;reject_build();init();d.inputs[0].buffer.offset=PAGE;reject_build();
    init();d.inputs[0].buffer.access=0;reject_build();init();d.inputs[0].buffer.heap=HMS_PDS;reject_build();
    init();d.inputs[1].min_bytes=1;reject_build();init();d.inputs[1].buffer=d.inputs[0].buffer;reject_build();
    init();s.init_data.capacity=127;reject_build();init();s.main_code.cpu=s.init_data.cpu;reject_build();
    init();s.stream.cpu=&p;reject_build();init();s.init_data.cpu=&d;reject_build();init();s.init_code.cpu=&s;reject_build();
    init();s.main_code.region.offset=0;reject_build();init();s.main_data.region.bo.gpu_va+=PAGE;reject_build();
    init();s.stream.region.offset=PAGE-128;s.stream.cpu=mem[0]+PAGE-128;s.stream.capacity=128;reject_build();
    init();d.heaps.usc.base=d.heaps.pds.base;reject_build();
    init();d.usc.access|=HMGPU_BO_WRITE;reject_build();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[0][4]^=2;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[0][24]^=1;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[0][36]^=2;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][8]^=0x10;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][11]^=0x10;reject_decode(); /* shared -> unified */
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][11]^=0x80;reject_decode(); /* early LAST */
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][12]=1;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][0x403]^=4;reject_decode(); /* early END */
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][0x900]^=1;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][0x904]=1;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);mem[2][0x808]=1;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);w32(mem[2]+0x800,0x10000);reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);job.fw_cmd[0]=1;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);job.stream_bytes=36;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);bos[2].access|=HMGPU_BO_WRITE;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);bos[3].cpu=bos[2].cpu;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);bos[1].bo.handle=bos[0].bo.handle;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);bos[2].cpu_bytes=100;reject_decode();
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);w32(mem[0]+40,0);reject_decode(); /* main code aliases init data */
    /* Literal bytes are data, not executable-validation markers. The resource
     * decoder must faithfully return changes; only ISA knows their meaning. */
    init();REQUIRE(hmsr_build(&d,&s,&p)==HMS_OK);w32(mem[2]+16,17);
    REQUIRE(hmsr_decode_resources(&d.heaps,&job,bos,4,&r)==HMS_OK && r.shared_image[2]==17);cases++;
    /* Repeated success/failure proves output preservation and reuse, with no
     * acquired runtime resources to leak or erroneous completion to clean up. */
    init();struct hmsr_desc saved_desc=d;unsigned char saved_mem[sizeof mem];memcpy(saved_mem,mem,sizeof mem);
    REQUIRE(hmsr_build(&d,&s,(struct hmsr_product *)(void *)&d)==HMS_E_ALIAS && !memcmp(&d,&saved_desc,sizeof d) && !memcmp(mem,saved_mem,sizeof mem));cases++;
    isa_shared_bridge();
    unsigned original_cases=cases;
    for(unsigned i=0;i<16;i++){init();resource_success();s.init_data.capacity=1;reject_build();}
    cases=original_cases;
    printf("PASS %u distinct resource cases +16 repeated success/failure transactions; ASan/UBSan; no stage validator, shader, GPU or device execution\n",cases);
    return 0;
}
