/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Actual implementation tests.
 * Encoders create test inputs only. Assertions target independently analyzed
 * raw bytes, dataflow and transactional results, not an encoder replica.
 */
#include "hm_isa_program.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); exit(1); } } while (0)
struct bytes { uint8_t p[HMISA_PROGRAM_BYTES]; size_t n; };
static struct hmisa_pointer ptr={0,HMISA_SHARED,0,3,0,12};
static void control(struct bytes *b,uint32_t op,uint32_t wd,uint32_t ws)
{
    struct hmisa_ctrl c={op,wd,ws}; size_t n=0;
    CHECK(!hmisa_ctrl_encode(1,&c,b->p+b->n,sizeof b->p-b->n,&n)); b->n+=n;
}
static void alu(struct bytes *b,uint32_t op,uint32_t dst,uint32_t lhs,uint32_t rhs,
    uint32_t kind,uint32_t index)
{
    struct hmisa_fop f={op,dst,lhs,rhs,{kind,index,0,0}}; size_t n=0;
    CHECK(!hmisa_fop_encode(1,&f,b->p+b->n,sizeof b->p-b->n,&n)); b->n+=n;
}
static void mem(struct bytes *b,uint32_t access,uint32_t reg,uint32_t offset,uint32_t index)
{
    struct hmisa_memory_product m;
    struct hmisa_schedule q={HMISA_ISSUE_DESCHED,index,0,0};
    struct hmisa_memory_request req={ptr.binding,access,reg,0,offset};
    CHECK(!hmisa_memory_lower(1,&ptr,&req,256,&q,&m));
    memcpy(b->p+b->n,m.code,16); b->n+=16;
}
static int analyze(const struct bytes *b,struct hmisa_program_facts *f)
{ return hmisa_program_analyze(b->p,b->n,&ptr,1,256,512,128,f); }
static void rejected(const struct bytes *b,int status)
{
    struct hmisa_program_facts f,before; memset(&f,0xa5,sizeof f); before=f;
    CHECK(analyze(b,&f)==status); CHECK(!memcmp(&f,&before,sizeof f));
}
static struct bytes inputs(void)
{
    struct bytes b={{0},0}; mem(&b,1,0,0,0); control(&b,10,1,0);
    mem(&b,1,1,4,0); control(&b,10,1,0); return b;
}
static struct bytes body(void)
{
    struct bytes b=inputs(); alu(&b,2,2,0,1,0,0); control(&b,10,0,1);
    mem(&b,2,2,8,0); control(&b,10,1,0); return b;
}
static void positives(void)
{
    struct bytes b=body(); struct hmisa_program_facts f;
    CHECK(!analyze(&b,&f)); CHECK(f.code_bytes==b.n && f.groups==8 && !f.end_count);
    CHECK(f.temps==3 && !f.unified_words && f.shared_words==2 && !f.input_index_high_water);
    CHECK(f.shared_read_mask[0]==3 && f.access_count==3 && f.obligations==63);
    CHECK(f.load_count==2 && f.store_count==1 && f.fop_count==1);
    CHECK(f.issue_desched_mask==1 && f.issue_sync_mask==1 && f.wait_desched_mask==1 && f.wait_sync_mask==1);
    for (unsigned j=0;j<3;j++) {
        CHECK(f.accesses[j].begin_byte==j*4 && f.accesses[j].end_byte==j*4+4);
        CHECK(f.accesses[j].displacement==j*4 && f.accesses[j].index==0);
    }
    /* Explicit test END, NOT a producer policy. Terminal structure still has
     * ALL FIVE unresolved proof obligations and does not authorize a shader. */
    control(&b,12,0,0); CHECK(!analyze(&b,&f)); CHECK(f.end_count==1 && f.obligations==31);
    b=inputs(); alu(&b,4,2,0,0,1,2); control(&b,10,4,0);
    mem(&b,2,2,0,1); control(&b,10,2,0);
    CHECK(!analyze(&b,&f) && f.fop_count==1 && f.store_count==1); /* x*x, real output alias */
    ptr.index=510; b=body(); CHECK(!analyze(&b,&f));
    CHECK(f.shared_words==512 && f.shared_read_mask[15]==0xc0000000u && !f.shared_read_mask[0]); ptr.index=0;
    ptr.bank=5; ptr.index=127; b=body(); CHECK(!analyze(&b,&f));
    CHECK(f.input_index_high_water==128 && !f.shared_words && !f.shared_read_mask[0]); ptr.bank=7; ptr.index=0;
    b=(struct bytes){{0},0}; mem(&b,1,255,0,0); control(&b,10,1,0);
    mem(&b,1,254,4,0); control(&b,10,1,0); alu(&b,2,253,255,254,0,1); control(&b,10,0,2);
    mem(&b,2,253,8,2); control(&b,10,4,0); CHECK(!analyze(&b,&f) && f.temps==256);
    /* The matching wait is applied BEFORE same-slot reuse in a DMA group. END
     * consumes a known SYNC mask, while retirement remains an obligation. */
    b=(struct bytes){{0},0}; mem(&b,1,0,0,0);
    struct hmisa_dma d={1,1,7,0,4,1,4,1,{1,0,1,0}};
    CHECK(!hmisa_dma_encode(1,&d,b.p+b.n,sizeof b.p-b.n)); b.n+=16;
    control(&b,10,1,0); alu(&b,2,2,0,1,0,1); control(&b,12,0,2);
    CHECK(!analyze(&b,&f) && f.end_count && f.obligations==31 && f.temps==3);
    printf("PASS scalar body/terminal structure, source alias, separate banks, SH510/511, temp255, exact accesses\n");
}
static void dataflow(void)
{
    struct bytes b={{0},0};
    mem(&b,2,0,8,0); control(&b,10,1,0); rejected(&b,HMISA_E_DATAFLOW);
    b=(struct bytes){{0},0}; alu(&b,2,2,0,1,0,0); control(&b,10,0,1); rejected(&b,HMISA_E_DATAFLOW);
    b=inputs(); alu(&b,2,0,0,1,0,0); control(&b,10,0,1); rejected(&b,HMISA_E_ALIAS);
    b=inputs(); alu(&b,2,2,0,1,2,0); rejected(&b,HMISA_E_UNSUPPORTED);
    b=(struct bytes){{0},0}; mem(&b,1,0,0,0); control(&b,10,0,1);
    mem(&b,2,0,8,1); control(&b,10,2,0); rejected(&b,HMISA_E_SCHEDULE); /* wrong namespace */
    /* Each hazard has later matching waits. Omission of the actual hazard
     * check must not be hidden by an unrelated pending-at-boundary failure. */
    b=inputs(); alu(&b,2,2,0,1,0,0); mem(&b,2,2,8,1); control(&b,10,2,1); rejected(&b,HMISA_E_SCHEDULE);
    b=inputs(); alu(&b,2,2,0,1,0,0); mem(&b,1,0,0,1); control(&b,10,2,1); rejected(&b,HMISA_E_SCHEDULE); /* pending FOP read */
    b=inputs(); mem(&b,2,0,8,0); alu(&b,2,0,1,1,0,0); control(&b,10,1,1); rejected(&b,HMISA_E_SCHEDULE); /* pending store read */
    b=inputs(); alu(&b,2,2,0,1,0,0); alu(&b,3,3,0,1,0,0); control(&b,10,0,1); rejected(&b,HMISA_E_SCHEDULE); /* issue reuse */
    b=inputs(); alu(&b,2,2,0,1,0,0); alu(&b,3,2,0,1,0,1); control(&b,10,0,3); rejected(&b,HMISA_E_SCHEDULE); /* pending destination */
    b=(struct bytes){{0},0}; mem(&b,1,0,0,0); mem(&b,1,1,4,1); control(&b,10,3,0); rejected(&b,HMISA_E_SCHEDULE);
    b=inputs(); mem(&b,2,0,8,0); control(&b,12,0,0); rejected(&b,HMISA_E_SCHEDULE);
    b=body(); b.n-=8; rejected(&b,HMISA_E_SCHEDULE); /* store remains pending at fragment boundary */
    b=body(); control(&b,12,0,0); control(&b,12,0,0); rejected(&b,HMISA_E_FORMAT);
    b=body(); control(&b,12,0,0); control(&b,10,0,0); rejected(&b,HMISA_E_FORMAT);
    printf("PASS undefined/alias/dependency/fence-slot/memory-order errors and transactional recovery\n");
}
static void resources(void)
{
    struct bytes b=body(); struct hmisa_program_facts f,before;
    struct hmisa_pointer p[2]={ptr,ptr}; memset(&f,0x55,sizeof f); before=f;
    CHECK(hmisa_program_analyze(b.p,b.n,p,1,2,2,0,&f)==HMISA_E_BOUNDS && !memcmp(&f,&before,sizeof f));
    CHECK(hmisa_program_analyze(b.p,b.n,p,1,3,1,0,&f)==HMISA_E_BOUNDS);
    p[0].access=1; CHECK(hmisa_program_analyze(b.p,b.n,p,1,3,2,0,&f)==HMISA_E_ARGUMENT);
    p[0]=ptr; p[0].bytes_available=11;
    CHECK(hmisa_program_analyze(b.p,b.n,p,1,3,2,0,&f)==HMISA_E_BOUNDS);
    p[0]=ptr; p[0].byte_origin=UINT64_MAX-3;
    CHECK(hmisa_program_analyze(b.p,b.n,p,1,3,2,0,&f)==HMISA_E_BOUNDS);
    p[0]=ptr; p[1].binding=1; CHECK(hmisa_program_analyze(b.p,b.n,p,2,3,2,0,&f)==HMISA_E_ALIAS);
    p[0]=ptr; p[0].index=2; CHECK(hmisa_program_analyze(b.p,b.n,p,1,3,4,0,&f)==HMISA_E_ARGUMENT);
    ptr.byte_origin=16; ptr.bytes_available=2048;
    b=(struct bytes){{0},0}; mem(&b,1,0,2060,0); control(&b,10,1,0);
    CHECK(!analyze(&b,&f) && f.accesses[0].begin_byte==2060 && f.accesses[0].end_byte==2064);
    ptr=(struct hmisa_pointer){0,7,0,3,0,12};
    CHECK(!analyze(&(struct bytes){.p={0x1c,0x03,0,0x80},.n=4},&f) && f.end_count && f.obligations==31);
    printf("PASS exact authority/span/overflow/access/budget checks; END alone proves no execution\n");
}
static void corruptions(void)
{
    struct bytes b=body(),m; struct hmisa_program_facts f;
    struct hmisa_raw_group g,before; memset(&g,0xa5,sizeof g); before=g;
    CHECK(hmisa_raw_decode(b.p,15,&g)==HMISA_E_FORMAT && !memcmp(&g,&before,sizeof g));
    /* Reserved/predicate/ROBUST bits in every DMA word, direct byte mutations. */
    const unsigned byte[]={0,7,11,13}; const uint8_t mask[]={0x80,0x80,0x40,0x80};
    for (unsigned j=0;j<4;j++) { m=b; m.p[byte[j]]^=mask[j]; CHECK(analyze(&m,&f)!=0); }
    m=b; m.p[3]|=0x80; rejected(&m,HMISA_E_FORMAT); /* DMA early final */
    m=b; m.p[15]&=0x7f; rejected(&m,HMISA_E_FORMAT); /* absent DMA final */
    m=b; m.p[9]^=4; rejected(&m,HMISA_E_UNSUPPORTED); /* Y=3, known raw bits, unsupported span */
    m=b; m.p[m.n-12]^=0x10; rejected(&m,HMISA_E_BOUNDS); /* ST stride8 ->12: actual out-of-range bytes */
    m=b; m.p[m.n++]=0; CHECK(analyze(&m,&f)==HMISA_E_BOUNDS);
    /* Noncanonical CTRL extension and reserved fixed bits. */
    const uint8_t ctrl[]={0x9c,0x02,0,0,0,0,0,0x80};
    CHECK(hmisa_raw_decode(ctrl,sizeof ctrl,&g)==HMISA_E_FORMAT);
    m=(struct bytes){{0x9c,0x12,0,0x80},4}; CHECK(analyze(&m,&f)==HMISA_E_FORMAT);
    b=body(); CHECK(!analyze(&b,&f) && f.access_count==3); /* no retained failure state */
    union { struct hmisa_raw_group raw; uint8_t p[64]; } alias;
    memset(&alias,0,sizeof alias); memcpy(alias.p,b.p,16);
    CHECK(hmisa_raw_decode(alias.p,16,&alias.raw)==HMISA_E_ALIAS);
    union { struct hmisa_program_facts facts; uint8_t p[sizeof(struct hmisa_program_facts)]; } palias;
    memset(&palias,0,sizeof palias); memcpy(palias.p,b.p,b.n);
    CHECK(hmisa_program_analyze(palias.p,b.n,&ptr,1,3,2,0,&palias.facts)==HMISA_E_ALIAS);
    printf("PASS raw framing/reserved/width/tail corruption rejection and successful retry\n");
}
int main(void) { positives(); dataflow(); resources(); corruptions(); return 0; }
