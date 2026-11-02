/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original host-only native C cross-owner consumer. AIR peer remains read-only.
 * The research test links air-r2's LGPL-selected upstream parser dependency;
 * hm_isa_memory.c itself has no AIR/Rust dependency. No production compile API.
 */
#include "hm_air.h"
#include "hm_isa_memory.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr,"line%d: %s\n",__LINE__,#x); goto fail; } } while (0)

int main(int argc, char **argv)
{
    hm_air_program *program=NULL;
    hm_air_diagnostic diag={0};
    hm_air_info_t info;
    hm_air_buffer_t buffer;
    hm_air_instruction_t inst;
    struct hmisa_memory_request reqs[3];
    struct hmisa_schedule schedules[3];
    struct hmisa_memory_product products[3];
    /* Explicit HOST MODEL allocation. NOT a proven launch resource count. */
    struct hmisa_pointer pointer={0,HMISA_SHARED,0,3,0,12};
    uint64_t lengths[31]={12};
    uint32_t grid[3]={1,1,1}, regs[16], next_reg=0, nr=0, i;
    unsigned char *bytes=NULL; FILE *file=NULL; long size;
    int success=0;
    if (argc!=2) { fprintf(stderr,"usage: test_air_memory OWN.metallib\n"); return 2; }
    file=fopen(argv[1],"rb"); REQUIRE(file);
    REQUIRE(fseek(file,0,SEEK_END)==0); size=ftell(file); REQUIRE(size>0 && size<1048576);
    REQUIRE(fseek(file,0,SEEK_SET)==0); bytes=malloc((size_t)size); REQUIRE(bytes);
    REQUIRE(fread(bytes,1,(size_t)size,file)==(size_t)size); fclose(file); file=NULL;
    REQUIRE(hm_air_open(bytes,(size_t)size,(const uint8_t *)"air_single_add",14,&program,&diag)==0);
    free(bytes); bytes=NULL;
    REQUIRE(hm_air_info(program,&info)==0 && info.buffer_count==1 && info.instruction_count==5);
    REQUIRE(!info.uses_grid_x && info.denorm_mode==1 && info.rounding_rne==1 && !info.contraction);
    REQUIRE(hm_air_buffer(program,0,&buffer)==0 && buffer.binding==0 && buffer.access==3);
    REQUIRE(hm_air_check_dispatch(program,lengths,grid,&diag)==0);
    for (i=0;i<16;i++) regs[i]=UINT32_MAX;
    for (i=0;i<info.instruction_count;i++) {
        REQUIRE(hm_air_instruction(program,i,&inst)==0 && inst.id<16);
        if (inst.opcode==HM_AIR_LOAD) {
            REQUIRE(nr<3 && next_reg<3 && !inst.thread_stride && inst.alignment==4);
            regs[inst.id]=next_reg++;
            reqs[nr]=(struct hmisa_memory_request){inst.binding,HMISA_READ,regs[inst.id],0,inst.byte_offset};
            schedules[nr++]=(struct hmisa_schedule){HMISA_ISSUE_DESCHED,0,0,0};
        } else if (inst.opcode==HM_AIR_FADD) {
            REQUIRE(next_reg==2 && inst.lhs<16 && inst.rhs<16 && regs[inst.lhs]==0 && regs[inst.rhs]==1);
            regs[inst.id]=next_reg++;
        } else if (inst.opcode==HM_AIR_STORE) {
            REQUIRE(nr<3 && inst.lhs<16 && regs[inst.lhs]==2 && !inst.thread_stride && inst.alignment==4);
            reqs[nr]=(struct hmisa_memory_request){inst.binding,HMISA_WRITE,regs[inst.lhs],0,inst.byte_offset};
            schedules[nr++]=(struct hmisa_schedule){HMISA_ISSUE_SYNC,1,0,1};
        } else REQUIRE(inst.opcode==HM_AIR_RETURN);
    }
    REQUIRE(nr==3 && next_reg==3);
    REQUIRE(hmisa_memory_lower_many(1,&pointer,1,reqs,schedules,3,3,products,3)==0);
    for (i=0;i<3;i++) {
        REQUIRE(products[i].begin_byte==4*i && products[i].end_byte==4*i+4);
        printf("MEMORY %u %s bank%u:index%u range[%llu,%llu) bytes=",i,
            products[i].access==HMISA_READ?"load":"store",products[i].dma.address_bank,
            products[i].dma.address_index,(unsigned long long)products[i].begin_byte,
            (unsigned long long)products[i].end_byte);
        for (unsigned j=0;j<16;j++) printf("%02x",products[i].code[j]);
        puts("");
    }
    lengths[0]=11;
    REQUIRE(hm_air_check_dispatch(program,lengths,grid,&diag)!=0);
    lengths[0]=12;
    REQUIRE(hm_air_check_dispatch(program,lengths,grid,&diag)==0);
    puts("PASS native AIR typed parser -> C scalar memory lowerer, no subprocess");
    puts("HOST MODEL: bank7 pointer/3 temps/explicit schedules; denorm mode preserved opaque");
    puts("NOT a complete stage: no ALU bytes/END/launch validity/HAS_CODE/completion claim");
    success=1;
fail:
    if (file) fclose(file);
    free(bytes);
    hm_air_release(program);
    if (!success && diag.message[0]) fprintf(stderr,"AIR diagnostic: %s\n",diag.message);
    return success ? 0 : 1;
}
