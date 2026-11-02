/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original implementation tests.
 */
#include "hm_isa_alloc.h"
#include <stdio.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line%d: %s\n",__LINE__,#x); return 1; } } while (0)
static int codec(void)
{
    struct hmisa_fop f={HMISA_FSUB,255,231,129,{HMISA_ISSUE_DESCHED,2,7,3}},back;
    uint32_t g[56],bad[56]; uint8_t code[13],before[13]; size_t n=999,unchanged;
    CHECK(!hmisa_fop_descriptor(&f,g)); CHECK(g[0x60/4]==129 && g[0x80/4]==231 && g[0x68/4]==0x100);
    CHECK(!hmisa_fop_from_descriptor(g,&back) && !memcmp(&f,&back,sizeof f));
    memset(code,0xa5,sizeof code);
    CHECK(!hmisa_fop_encode(1,&f,code+1,12,&n) && n==12 && code[0]==0xa5);
    CHECK(!hmisa_fop_decode(code+1,n,&back) && !memcmp(&f,&back,sizeof f));
    memcpy(before,code,sizeof code); unchanged=n;
    CHECK(hmisa_fop_encode(0,&f,code,12,&n)==HMISA_E_DISABLED);
    CHECK(hmisa_fop_encode(1,&f,code,11,&n)==HMISA_E_CAPACITY);
    CHECK(!memcmp(before,code,sizeof code) && n==unchanged);
    for (unsigned i=0;i<56;i++) {
        /* Every field is represented in the comparison, including zero ones.
         * Not every mutated descriptor is invalid: operand changes can be valid. */
        if (g[i]) continue;
        memcpy(bad,g,sizeof g); bad[i]=0x80000000;
        memset(&back,0x5a,sizeof back); struct hmisa_fop sentinel=back;
        CHECK(hmisa_fop_from_descriptor(bad,&back)!=0 && !memcmp(&back,&sentinel,sizeof back));
    }
    code[12]^=0x80;
    CHECK(hmisa_fop_decode(code+1,n,&back)!=0);
    f=(struct hmisa_fop){HMISA_FADD,0,0,0,{HMISA_ISSUE_SYNC,0,0,0}};
    CHECK(!hmisa_fop_encode(1,&f,code,12,&n) && n==4);
    f.rhs=127; CHECK(!hmisa_fop_encode(1,&f,code,12,&n) && n==8);
    f.rhs=128; CHECK(!hmisa_fop_encode(1,&f,code,12,&n) && n==12);
    f.op=HMISA_FMUL; CHECK(hmisa_fop_encode(1,&f,code,12,&n)==HMISA_E_UNSUPPORTED);
    f.rhs=1; f.schedule.wait_sync=1;
    CHECK(hmisa_fop_encode(1,&f,code,12,&n)==HMISA_E_UNSUPPORTED); /* issue/wait same SYNC */
    CHECK(hmisa_fop_encode(1,&f,code,12,(size_t *)code)!=0);
    f.schedule.wait_sync=0;
    CHECK(hmisa_fop_encode(1,&f,code,12,(size_t *)code)==HMISA_E_ALIAS);
    puts("PASS FOP noncommutative mapping, extensions, strict inverse and output atomics");
    return 0;
}
static int control(void)
{
    struct hmisa_ctrl c={HMISA_NOP,7,3},back;
    uint32_t g[56]; uint8_t bytes[12]; size_t n;
    CHECK(!hmisa_ctrl_encode(1,&c,bytes,12,&n) && n==8);
    CHECK(!hmisa_ctrl_decode(bytes,n,&back) && !memcmp(&back,&c,sizeof c));
    CHECK(!hmisa_ctrl_descriptor(&c,g) && g[12]==7 && g[13]==3 && g[14]==10);
    CHECK(!hmisa_ctrl_from_descriptor(g,&back) && !memcmp(&back,&c,sizeof c));
    bytes[0]|=1; CHECK(hmisa_ctrl_decode(bytes,n,&back)!=0);
    g[55]=2; CHECK(hmisa_ctrl_from_descriptor(g,&back)!=0);
    c.op=HMISA_END; CHECK(hmisa_ctrl_descriptor(&c,g)==HMISA_E_UNSUPPORTED);
    c.wait_desched=0; CHECK(!hmisa_ctrl_encode(1,&c,bytes,12,&n) && n==4);
    CHECK(!hmisa_ctrl_decode(bytes,n,&back) && back.op==HMISA_END && back.wait_sync==3);
    puts("PASS END/SYNC and NOP/DESCHED constraints and strict inverse"); return 0;
}
static int allocation(void)
{
    struct hmisa_input inputs[]={{100,0},{200,1}};
    struct hmisa_node nodes[]={
        {300,HMISA_FSUB,100,200},{400,HMISA_FMUL,300,300},
        {500,HMISA_FADD,400,400},{HMISA_NO_VALUE,HMISA_SSA_USE,500,HMISA_NO_VALUE}};
    struct hmisa_allocation a,before; uint32_t live[]={100,200};
    CHECK(!hmisa_allocate(1,inputs,2,nodes,4,NULL,0,3,&a));
    CHECK(a.node_reg[0]==2 && a.node_reg[1]==0 && a.node_reg[2]==1 && a.node_reg[3]==1);
    CHECK(a.high_water==3 && a.peak_live==3 && a.value_count==5);
    CHECK(a.values[0].last_use==0 && a.values[2].last_use==1);
    CHECK(inputs[0].reg==0 && nodes[0].id==300);
    CHECK(!hmisa_allocate(1,inputs,2,nodes,4,live,1,3,&a) && a.node_reg[1]==1);
    memset(&a,0xa5,sizeof a); before=a;
    CHECK(hmisa_allocate(1,inputs,2,nodes,4,NULL,0,2,&a)==HMISA_E_CAPACITY);
    CHECK(!memcmp(&a,&before,sizeof a));
    CHECK(hmisa_allocate(1,inputs,2,nodes,4,live,2,3,&a)==HMISA_E_CAPACITY);
    CHECK(!memcmp(&a,&before,sizeof a));
    inputs[1].reg=0; CHECK(hmisa_allocate(1,inputs,2,nodes,4,NULL,0,3,&a)==HMISA_E_ALIAS);
    CHECK(!memcmp(&a,&before,sizeof a)); inputs[1].reg=1;
    nodes[1].rhs=999; CHECK(hmisa_allocate(1,inputs,2,nodes,4,NULL,0,3,&a)==HMISA_E_ARGUMENT);
    CHECK(!memcmp(&a,&before,sizeof a)); nodes[1].rhs=300;
    nodes[1].id=300; CHECK(hmisa_allocate(1,inputs,2,nodes,4,NULL,0,3,&a)==HMISA_E_ARGUMENT);
    nodes[1].id=400;
    CHECK(!hmisa_allocate(1,inputs,2,nodes,4,NULL,0,3,&a) && a.node_reg[1]==0);
    CHECK(hmisa_allocate(1,(const struct hmisa_input *)&a,2,nodes,4,NULL,0,3,&a)==HMISA_E_ALIAS);
    CHECK(hmisa_allocate(0,inputs,2,nodes,4,NULL,0,3,&a)==HMISA_E_DISABLED);
    CHECK(hmisa_allocate(1,inputs,2,nodes,65,NULL,0,3,&a)==HMISA_E_BOUNDS);
    CHECK(!hmisa_allocate(1,NULL,0,NULL,0,NULL,0,1,&a) && a.high_water==0);
    puts("PASS SSA aliases, inclusive liveness, actual reuse, live-outs, pressure and recovery atomics");
    return 0;
}
int main(void) { return codec() || control() || allocation(); }
