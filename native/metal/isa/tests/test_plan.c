/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Actual typed AIR multi-ALU/negative tests.
 */
#include "hm_isa_air.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line%d: %s\n",__LINE__,#x); failed=1; goto done; } } while (0)
static hm_air_program *open_program(const char *path)
{
    FILE *file=fopen(path,"rb"); uint8_t *bytes=NULL; long n=0;
    hm_air_program *p=NULL; hm_air_diagnostic d={0};
    if (file && !fseek(file,0,SEEK_END) && (n=ftell(file))>0 && n<4194304 &&
        !fseek(file,0,SEEK_SET) && (bytes=malloc((size_t)n)) && fread(bytes,1,(size_t)n,file)==(size_t)n)
        (void)hm_air_open(bytes,(size_t)n,(const uint8_t *)"test",4,&p,&d);
    if (file) fclose(file); free(bytes); return p;
}
int main(int argc,char **argv)
{
    hm_air_program *p=NULL; struct hmisa_unlinked u,before; int failed=0;
    struct hmisa_pointer ptr={0,HMISA_SHARED,0,3,0,12}; uint32_t n=0,pending_d=0,pending_s=0;
    const uint32_t expected_dst[]={2,3,0},expected_lhs[]={0,2,3},expected_rhs[]={1,0,1};
    if (argc!=4) return 2;
    p=open_program(argv[1]); CHECK(p);
    CHECK(!hmisa_air_prepare(1,p,&ptr,1,4,&u));
    CHECK(u.fragment_count==12 && u.allocation.high_water==4 && u.allocation.peak_live==4);
    CHECK(u.allocation.values[0].last_use==3 && u.allocation.values[1].last_use==4);
    for (uint32_t i=0;i<u.fragment_count;i++) {
        struct hmisa_fragment *f=&u.fragments[i];
        if (f->kind==HMISA_FRAGMENT_FOP) {
            struct hmisa_fop op; CHECK(n<3 && !pending_s && !pending_d);
            CHECK(!hmisa_fop_decode(f->code,f->code_bytes,&op));
            CHECK(op.op==n+2 && op.dst==expected_dst[n] && op.lhs==expected_lhs[n] && op.rhs==expected_rhs[n]);
            CHECK(op.dst!=op.lhs && op.dst!=op.rhs); pending_s=1; n++;
        } else if (f->kind==HMISA_FRAGMENT_DMA) {
            struct hmisa_dma dma; CHECK(!pending_d && !pending_s);
            CHECK(!hmisa_dma_decode(f->code,f->code_bytes,&dma)); pending_d=1;
            if (dma.access==HMISA_WRITE) CHECK(dma.data_reg==0 && f->begin_byte==8 && n==3);
        } else {
            struct hmisa_ctrl c; CHECK(!hmisa_ctrl_decode(f->code,f->code_bytes,&c));
            CHECK(c.op==HMISA_NOP && c.wait_desched==pending_d && c.wait_sync==pending_s);
            CHECK(pending_d||pending_s); pending_d=pending_s=0;
        }
    }
    CHECK(n==3 && !pending_d && !pending_s);
    memset(&u,0xa5,sizeof u); before=u;
    CHECK(hmisa_air_prepare(1,p,&ptr,1,3,&u)==HMISA_E_CAPACITY && !memcmp(&u,&before,sizeof u));
    CHECK(!hmisa_air_prepare(1,p,&ptr,1,4,&u) && u.allocation.high_water==4);
    hm_air_release(p); p=NULL;
    puts("PASS real typed AIR multi-ALU liveness and actual4-word high-water/reuse");
    /* Frontend accepts exact constant bits; this native profile cannot yet
     * materialize them. Input is real typed IR, not a fake parser callback. */
    p=open_program(argv[2]); CHECK(p); memset(&u,0xa5,sizeof u); before=u;
    CHECK(hmisa_air_prepare(1,p,&ptr,1,4,&u)==HMISA_E_UNSUPPORTED && !memcmp(&u,&before,sizeof u));
    hm_air_release(p); p=NULL;
    puts("PASS actual parser constant plan refused transactionally");
    p=open_program(argv[3]); CHECK(p); CHECK(!hmisa_air_prepare(1,p,&ptr,1,3,&u));
    CHECK(u.fragment_count==8 && u.fragments[6].kind==HMISA_FRAGMENT_DMA &&
        u.fragments[6].access==HMISA_WRITE && u.fragments[6].begin_byte==0);
    CHECK(u.fragments[0].access==HMISA_READ && u.fragments[0].begin_byte==0);
    hm_air_release(p); p=NULL;
    puts("PASS actual aliased output buffer preserves load/ALU/store order");
done:
    hm_air_release(p); return failed;
}
