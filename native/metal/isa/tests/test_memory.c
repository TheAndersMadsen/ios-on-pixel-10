/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original focused native tests.
 * Model canonical register assignments/resource budgets only; no GPU claims.
 */
#include "hm_isa_memory.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); exit(1); } } while (0)
static const struct hmisa_schedule load = {HMISA_ISSUE_DESCHED, 0, 0, 0};
static const struct hmisa_schedule store = {HMISA_ISSUE_SYNC, 1, 0, 1};
static struct hmisa_pointer pointer(void)
{
    struct hmisa_pointer p = {0, HMISA_VERTEX_INPUT, 2, 3, 0, 4096};
    return p;
}
static struct hmisa_memory_request request(uint32_t access, uint32_t reg, uint64_t offset)
{
    struct hmisa_memory_request r = {0, access, reg, 0, offset};
    return r;
}

static void scalar_offsets(void)
{
    struct hmisa_pointer p = pointer();
    struct hmisa_memory_request requests[3] = {request(1,0,0),request(1,1,4),request(2,2,8)};
    struct hmisa_schedule schedules[3] = {load,load,store};
    struct hmisa_memory_product out[3];
    struct hmisa_dma decoded;
    uint32_t desc[56];
    unsigned i;
    CHECK(hmisa_memory_lower_many(1,&p,1,requests,schedules,3,3,out,3)==0);
    for (i=0;i<3;i++) {
        CHECK(out[i].begin_byte==4*i && out[i].end_byte==4*i+4);
        CHECK(out[i].dma.data_reg==i && out[i].dma.x_bytes==4 && out[i].dma.y_count==1);
        CHECK(out[i].dma.address_bank==HMISA_VERTEX_INPUT && out[i].dma.address_index==2);
        CHECK(out[i].dma.stride==(i ? 4*i : 1) && out[i].dma.add_first==(i!=0));
        CHECK(hmisa_dma_decode(out[i].code,16,&decoded)==0 && !memcmp(&decoded,&out[i].dma,sizeof decoded));
        CHECK(hmisa_dma_descriptor(&decoded,desc)==0 && desc[0x90/4]==0);
        CHECK(hmisa_dma_from_descriptor(desc,&decoded)==0);
    }
    puts("PASS scalar load0/load4/store8: native bytes, exact ranges, strict inverses");
}

static void bounds_and_recovery(void)
{
    struct hmisa_pointer p=pointer();
    struct hmisa_memory_request r=request(1,0,2044);
    struct hmisa_memory_product out,sentinel;
    memset(&sentinel,0xa5,sizeof sentinel); out=sentinel;
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&out)==0 && out.dma.stride==2044);
    out=sentinel; r.byte_offset=2048;
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&out)==HMISA_E_BOUNDS && !memcmp(&out,&sentinel,sizeof out));
    r.byte_offset=4; p.bytes_available=7;
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&out)==HMISA_E_BOUNDS && !memcmp(&out,&sentinel,sizeof out));
    p.bytes_available=8;
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&out)==0 && out.end_byte==8);
    p.byte_origin=UINT64_MAX-3; p.bytes_available=8; r.byte_offset=p.byte_origin;
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&out)==HMISA_E_BOUNDS);
    p=pointer(); p.byte_origin=16; p.bytes_available=16; r.byte_offset=20;
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&out)==0 && out.dma.stride==4 && out.begin_byte==20);
    r.byte_offset=4;
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&out)==HMISA_E_BOUNDS);
    puts("PASS byte bounds/origin/overflow and successful recovery");
}

static void failed_bundle_is_atomic(void)
{
    struct hmisa_pointer p=pointer();
    struct hmisa_memory_request r[3]={request(1,0,0),request(1,1,4),request(2,2,8)};
    struct hmisa_schedule s[3]={load,load,store};
    struct hmisa_memory_product out[3],sentinel[3];
    memset(sentinel,0x6c,sizeof sentinel); memcpy(out,sentinel,sizeof out);
    CHECK(hmisa_memory_lower_many(1,&p,1,r,s,3,2,out,3)==HMISA_E_BOUNDS);
    CHECK(!memcmp(out,sentinel,sizeof out));
    p.access=HMISA_READ;
    CHECK(hmisa_memory_lower_many(1,&p,1,r,s,3,3,out,3)==HMISA_E_ARGUMENT);
    CHECK(!memcmp(out,sentinel,sizeof out));
    p.access=3;
    CHECK(hmisa_memory_lower_many(1,&p,1,r,s,3,3,out,3)==0 && out[2].access==HMISA_WRITE);
    puts("PASS later failure leaves all output untouched; pressure/access recovery");
}

static void unknown_bits_and_descriptors(void)
{
    struct hmisa_pointer p=pointer();
    struct hmisa_memory_request r=request(1,1,4);
    struct hmisa_memory_product m;
    struct hmisa_dma out,sentinel;
    uint32_t d[56]; uint8_t b[16];
    memset(&sentinel,0x3c,sizeof sentinel); out=sentinel;
    CHECK(hmisa_memory_lower(1,&p,&r,3,&load,&m)==0);
    CHECK(hmisa_dma_descriptor(&m.dma,d)==0); d[0xd8/4]=1;
    CHECK(hmisa_dma_from_descriptor(d,&out)==HMISA_E_FORMAT && !memcmp(&out,&sentinel,sizeof out));
    memcpy(b,m.code,16); b[3]|=0x80;
    CHECK(hmisa_dma_decode(b,16,&out)==HMISA_E_FORMAT && !memcmp(&out,&sentinel,sizeof out));
    memcpy(b,m.code,16); b[15]^=0x80;
    CHECK(hmisa_dma_decode(b,16,&out)==HMISA_E_FORMAT);
    memcpy(b,m.code,16); b[14]^=1; /* absent robust field cannot become shared0 */
    CHECK(hmisa_dma_decode(b,16,&out)==HMISA_E_FORMAT);
    CHECK(hmisa_dma_decode(m.code,12,&out)==HMISA_E_FORMAT);
    CHECK(hmisa_dma_decode(m.code,16,&out)==0);
    puts("PASS unknown descriptor fields, framing, robust operand and truncation");
}

static void banks_schedule_and_capacity(void)
{
    struct hmisa_pointer p=pointer();
    struct hmisa_memory_request r=request(1,0,0);
    struct hmisa_memory_product m;
    uint8_t b[16],sentinel[16];
    CHECK(hmisa_memory_lower(1,&p,&r,1,&load,&m)==0);
    memset(sentinel,0x96,sizeof sentinel); memcpy(b,sentinel,sizeof b);
    CHECK(hmisa_dma_encode(0,&m.dma,b,16)==HMISA_E_DISABLED && !memcmp(b,sentinel,16));
    CHECK(hmisa_dma_encode(1,&m.dma,b,15)==HMISA_E_CAPACITY && !memcmp(b,sentinel,16));
    m.dma.address_bank=HMISA_SHARED; m.dma.address_index=1;
    CHECK(hmisa_dma_encode(1,&m.dma,b,16)==HMISA_E_UNSUPPORTED);
    m.dma.address_index=510;
    CHECK(hmisa_dma_encode(1,&m.dma,b,16)==0);
    m.dma.address_bank=HMISA_VERTEX_INPUT; m.dma.address_index=128;
    CHECK(hmisa_dma_encode(1,&m.dma,b,16)==HMISA_E_UNSUPPORTED);
    m.dma.address_bank=HMISA_HWTEMP; m.dma.address_index=255;
    CHECK(hmisa_dma_encode(1,&m.dma,b,16)==0);
    m.dma.schedule.issue_kind=HMISA_ISSUE_SYNC;
    CHECK(hmisa_dma_encode(1,&m.dma,b,16)==HMISA_E_UNSUPPORTED); /* load cannot issue sync */
    m.dma.access=HMISA_WRITE; m.dma.schedule.wait_sync=1;
    CHECK(hmisa_dma_encode(1,&m.dma,b,16)==HMISA_E_UNSUPPORTED);
    m.dma.schedule.issue_index=1;
    CHECK(hmisa_dma_encode(1,&m.dma,b,16)==0);
    puts("PASS distinct banks, explicit issue forms, capacity and default-off generation");
}

static void aliases_and_missing_bindings(void)
{
    struct hmisa_pointer p[2]={pointer(),pointer()};
    struct hmisa_memory_request r=request(1,0,0);
    struct hmisa_memory_product out;
    CHECK(hmisa_memory_lower_many(1,p,2,&r,&load,1,1,&out,1)==HMISA_E_ALIAS);
    p[1].binding=1;
    CHECK(hmisa_memory_lower_many(1,p,2,&r,&load,1,1,&out,1)==HMISA_E_ALIAS);
    p[1].index=4; r.binding=2;
    CHECK(hmisa_memory_lower_many(1,p,2,&r,&load,1,1,&out,1)==HMISA_E_ARGUMENT);
    r.binding=0;
    CHECK(hmisa_memory_lower_many(1,p,2,&r,&load,1,1,&out,1)==0);
    CHECK(hmisa_dma_encode(1,&out.dma,&out.dma,16)==HMISA_E_ALIAS);
    puts("PASS canonical pointer aliases, missing bindings and successful retry");
}

int main(void)
{
    scalar_offsets(); bounds_and_recovery(); failed_bundle_is_atomic();
    unknown_bits_and_descriptors(); banks_schedule_and_capacity(); aliases_and_missing_bindings();
    puts("PASS 6 focused native test groups; host model only; no complete-stage claim");
    return 0;
}
