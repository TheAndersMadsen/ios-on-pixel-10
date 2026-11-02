/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original native composition test; resource fixture shape adapted from MIT
 * streams-r2/tests/test_shared.c. All BOs/VAs are explicit HOST MODELS.
 * Actual PDS/CDM builder + frozen decoder + AIR parser + C compiler execute.
 * No stage validator, shader dispatch, fake completion or GPU result exists.
 */
#include "hm_shared.h"
#include "hm_isa_air.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define PAGE 16384u
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line%d: %s\n",__LINE__,#x); goto done; } } while (0)
static unsigned char memory[4][PAGE];
static struct hms_frozen_bo bos[4];
static struct hms_region region(unsigned i,unsigned offset,unsigned bytes)
{
    return (struct hms_region){bos[i].bo,offset,bytes,bos[i].heap,bos[i].access};
}
int main(int argc,char **argv)
{
    struct hmsr_desc desc={0}; struct hmsr_storage storage; struct hmsr_product product;
    struct hmsr_frozen_resources frozen; struct hmgpu_job job={0};
    struct hmisa_unlinked compiled; struct hmisa_pointer pointer;
    hm_air_program *air=NULL; hm_air_diagnostic diagnostic={0};
    FILE *file=NULL; uint8_t *bytes=NULL; long count; int status=1;
    const uint64_t vas[]={UINT64_C(0x8000010000),UINT64_C(0x8000020000),UINT64_C(0xda00000000),UINT64_C(0xe000000000)};
    const unsigned heaps[]={HMS_GENERAL,HMS_GENERAL,HMS_PDS,HMS_USC};
    if (argc!=2) return 2;
    memset(memory,0xcc,sizeof memory);
    for (unsigned i=0;i<4;i++) bos[i]=(struct hms_frozen_bo){
        {sizeof(struct hmgpu_bo_out),i+1,vas[i],PAGE,0,0},heaps[i],
        i==1?HMGPU_BO_READ|HMGPU_BO_WRITE:HMGPU_BO_READ,memory[i],PAGE};
    desc.heaps=(struct hms_heaps){{UINT64_C(0x8000000000),0x10000000},
        {UINT64_C(0xe000000000),0x10000000},{UINT64_C(0xda00000000),0x10000000},PAGE};
    /* USC allocation is a resource-only fixture, never decoded/approved as a
     * stage. Counts are explicit MODEL resource inputs, not compiler authority. */
    desc.usc=region(3,0,64); desc.code_bytes=64; desc.temps=3; desc.shared_words=2;
    desc.input_count=1; desc.inputs[0]=(struct hmsr_input){.word=0,.kind=HMSR_POINTER64,
        .min_bytes=12,.buffer=region(1,32,12)};
    storage=(struct hmsr_storage){
        {region(2,0,256),memory[2],256}, {region(2,0x400,64),memory[2]+0x400,64},
        {region(2,0x800,16),memory[2]+0x800,16}, {region(2,0x900,16),memory[2]+0x900,16},
        {region(0,0,128),memory[0],128}};
    CHECK(hmsr_build(&desc,&storage,&product)==HMS_OK);
    job.size=sizeof job; job.type=HMGPU_JOB_COMPUTE; job.stream_va=product.stream_va;
    job.stream_bytes=product.stream_bytes; job.bo_count=product.bo_count;
    CHECK(hmsr_decode_resources(&desc.heaps,&job,bos,4,&frozen)==HMS_OK);
    CHECK(frozen.shared_words_allocated==16 && frozen.temps_allocated==4);
    uint64_t held=(uint64_t)frozen.shared_image[0]|(uint64_t)frozen.shared_image[1]<<32;
    CHECK(held==bos[1].bo.gpu_va+32 && held-bos[1].bo.gpu_va<=bos[1].bo.bytes-12);
    for (unsigned i=2;i<16;i++) CHECK(frozen.shared_image[i]==0);
    pointer=(struct hmisa_pointer){0,HMISA_SHARED,0,3,0,12};
    file=fopen(argv[1],"rb"); CHECK(file); CHECK(!fseek(file,0,SEEK_END)); count=ftell(file);
    CHECK(count>0 && count<4194304 && !fseek(file,0,SEEK_SET)); bytes=malloc((size_t)count); CHECK(bytes);
    CHECK(fread(bytes,1,(size_t)count,file)==(size_t)count); fclose(file); file=NULL;
    CHECK(!hm_air_open(bytes,(size_t)count,(const uint8_t *)"air_single_add",14,&air,&diagnostic));
    free(bytes); bytes=NULL;
    CHECK(!hmisa_air_prepare(1,air,&pointer,1,frozen.temps_allocated,&compiled));
    CHECK(compiled.allocation.high_water==3 && compiled.unresolved==31);
    uint32_t accesses=0;
    for (uint32_t i=0;i<compiled.fragment_count;i++) if (compiled.fragments[i].kind==HMISA_FRAGMENT_DMA) {
        struct hmisa_fragment *f=&compiled.fragments[i]; struct hmisa_dma dma;
        CHECK(!hmisa_dma_decode(f->code,f->code_bytes,&dma));
        CHECK(dma.address_bank==7 && dma.address_index==0 && f->begin_byte==accesses*4);
        CHECK(f->end_byte<=12 && (held-bos[1].bo.gpu_va)+f->end_byte<=bos[1].bo.bytes);
        accesses++;
    }
    CHECK(accesses==3);
    puts("PASS composed actual common-init PDS/CDM -> frozen SH0/1 -> typed AIR -> native allocation/LD/ALU/ST/waits");
    puts("HOST MODEL BO authority/resource counts; complete-stage verification and init order remain unavailable");
    status=0;
done:
    if (file) fclose(file); free(bytes); hm_air_release(air); return status;
}
