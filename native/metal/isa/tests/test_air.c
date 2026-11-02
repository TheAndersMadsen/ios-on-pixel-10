/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Actual native parser/compiler test.
 * AIR-r2's Rust dependency uses its retained LGPL research licence selection.
 */
#include "hm_isa_air.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr,"line%d: %s\n",__LINE__,#x); goto fail; } } while (0)
static int run(const char *path,const char *entry,uint32_t expected_op)
{
    hm_air_program *p=NULL; hm_air_diagnostic d={0}; hm_air_info_t info;
    struct hmisa_unlinked u,before; struct hmisa_pointer pointer={0,HMISA_SHARED,0,3,0,12};
    uint8_t *bytes=NULL; FILE *file=NULL; long size; int success=0;
    uint32_t dma_count=0,alu_count=0,wait_count=0,pending_d=0,pending_s=0;
    file=fopen(path,"rb"); REQUIRE(file); REQUIRE(!fseek(file,0,SEEK_END)); size=ftell(file);
    REQUIRE(size>0 && size<4194304); REQUIRE(!fseek(file,0,SEEK_SET)); bytes=malloc((size_t)size); REQUIRE(bytes);
    REQUIRE(fread(bytes,1,(size_t)size,file)==(size_t)size); fclose(file); file=NULL;
    REQUIRE(!hm_air_open(bytes,(size_t)size,(const uint8_t *)entry,strlen(entry),&p,&d));
    memset(bytes,0,(size_t)size); free(bytes); bytes=NULL;
    REQUIRE(!hm_air_info(p,&info)); REQUIRE(!hmisa_air_prepare(1,p,&pointer,1,3,&u));
    REQUIRE(!memcmp(&info,&u.air,sizeof info) && info.denorm_mode==1 && info.rounding_rne==1 && !info.contraction);
    REQUIRE(u.unresolved==31 && u.fragment_count==8 && u.memory_count==3);
    REQUIRE(u.allocation.high_water==3 && u.allocation.peak_live==3);
    for (uint32_t i=0;i<u.fragment_count;i++) {
        const struct hmisa_fragment *f=&u.fragments[i]; uint32_t desc[56];
        REQUIRE(f->code_bytes<=16 && !(f->code_bytes&3));
        if (f->kind==HMISA_FRAGMENT_DMA) {
            struct hmisa_dma dma;
            REQUIRE(!pending_d && !pending_s && !hmisa_dma_decode(f->code,f->code_bytes,&dma));
            REQUIRE(dma.x_bytes==4 && dma.y_count==1 && dma.address_bank==7 && dma.address_index==0);
            REQUIRE(dma.schedule.issue_kind==HMISA_ISSUE_DESCHED && dma.schedule.issue_index==0);
            REQUIRE(!hmisa_dma_descriptor(&dma,desc) && !desc[0x90/4] && !desc[0x94/4]);
            REQUIRE(f->begin_byte==dma_count*4 && f->end_byte==dma_count*4+4);
            REQUIRE(dma.add_first==(dma_count!=0) && dma.stride==(dma_count?dma_count*4:1));
            REQUIRE(f->value_reg==dma_count); dma_count++; pending_d=1;
        } else if (f->kind==HMISA_FRAGMENT_FOP) {
            struct hmisa_fop op;
            REQUIRE(!pending_d && !pending_s && !hmisa_fop_decode(f->code,f->code_bytes,&op));
            REQUIRE(op.op==expected_op && op.lhs==0 && op.rhs==1 && op.dst==2);
            REQUIRE(op.schedule.issue_kind==HMISA_ISSUE_SYNC && op.schedule.issue_index==0);
            REQUIRE(!hmisa_fop_descriptor(&op,desc));
            if (expected_op==HMISA_FSUB) REQUIRE(desc[0x60/4]==1 && desc[0x80/4]==0 && desc[0x68/4]==0x100);
            alu_count++; pending_s=1;
        } else {
            struct hmisa_ctrl wait;
            REQUIRE(f->kind==HMISA_FRAGMENT_WAIT && !hmisa_ctrl_decode(f->code,f->code_bytes,&wait));
            REQUIRE(wait.op==HMISA_NOP && wait.wait_desched==pending_d && wait.wait_sync==pending_s);
            REQUIRE(pending_d || pending_s); pending_d=pending_s=0; wait_count++;
        }
        printf("FRAGMENT %u kind%u air%u bytes",i,f->kind,f->air_index);
        for (uint32_t j=0;j<f->code_bytes;j++) printf("%02x",f->code[j]);
        puts("");
    }
    REQUIRE(dma_count==3 && alu_count==1 && wait_count==4 && !pending_d && !pending_s);
    memset(&u,0xa5,sizeof u); before=u;
    pointer.bytes_available=11;
    REQUIRE(hmisa_air_prepare(1,p,&pointer,1,3,&u)==HMISA_E_BOUNDS && !memcmp(&u,&before,sizeof u));
    pointer.bytes_available=12;
    REQUIRE(hmisa_air_prepare(1,p,&pointer,1,2,&u)==HMISA_E_CAPACITY && !memcmp(&u,&before,sizeof u));
    pointer.index=1;
    REQUIRE(hmisa_air_prepare(1,p,&pointer,1,3,&u)==HMISA_E_UNSUPPORTED && !memcmp(&u,&before,sizeof u));
    pointer.index=0;
    REQUIRE(hmisa_air_prepare(0,p,&pointer,1,3,&u)==HMISA_E_DISABLED && !memcmp(&u,&before,sizeof u));
    REQUIRE(!hmisa_air_prepare(1,p,&pointer,1,3,&u) && u.allocation.high_water==3);
    printf("PASS actual native AIR -> allocation/LD/%s/ST/explicit waits; FP metadata unchanged, unresolved31\n",expected_op==2?"FADD":expected_op==3?"FSUB":"FMUL");
    success=1;
fail:
    if (!success && d.message[0]) fprintf(stderr,"AIR %s\n",d.message);
    if (file) fclose(file); free(bytes); hm_air_release(p); return success?0:1;
}
int main(int argc,char **argv)
{
    if (argc!=5) { fprintf(stderr,"usage: test_air OWN.metallib add.bc sub.bc mul.bc\n"); return 2; }
    return run(argv[1],"air_single_add",HMISA_FADD)||run(argv[2],"test",HMISA_FADD)||
        run(argv[3],"test",HMISA_FSUB)||run(argv[4],"test",HMISA_FMUL);
}
