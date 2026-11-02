/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Original independent byte decoder.
 * Numeric fields measured by earlier MIT ISA work and pure stock codec calls;
 * no vendor body, template, encoder call or descriptor roundtrip. See provenance.
 */
#include "hm_isa_program.h"
#include <string.h>
static int overlap(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return an && bn && (x<=y?y-x<an:x-y<bn);
}
static uint32_t word(const uint8_t *p)
{ return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static uint32_t bit(uint32_t w,unsigned n) { return (w>>n)&1u; }
static int dma(const uint32_t w[4],struct hmisa_raw_group *g)
{
    struct hmisa_dma *d=&g->u.dma;
    uint32_t mode=(w[0]>>16)&7u,slot=(w[0]>>8)&7u;
    uint32_t bank_mask,index_mask,wm0,wm1,wm2;
    if (mode!=4 && mode!=5) return HMISA_E_UNSUPPORTED;
    d->access=mode==5?HMISA_READ:HMISA_WRITE;
    if (slot>=1 && slot<=3) {
        d->schedule.issue_kind=HMISA_ISSUE_DESCHED; d->schedule.issue_index=slot-1;
    } else if (slot>=4 && slot<=5 && mode==4) {
        d->schedule.issue_kind=HMISA_ISSUE_SYNC; d->schedule.issue_index=slot-4;
    } else return HMISA_E_UNSUPPORTED;
    d->schedule.wait_desched=(w[0]>>11)&7u;
    d->schedule.wait_sync=(w[0]>>14)&3u;
    if (d->schedule.issue_kind==HMISA_ISSUE_SYNC &&
        (d->schedule.wait_sync&(1u<<d->schedule.issue_index))) return HMISA_E_UNSUPPORTED;
    if (!(w[1]&0x80000u)) {
        d->address_bank=HMISA_SHARED; index_mask=0x7fc00u; bank_mask=0;
        d->address_index=(w[1]>>10)&511u;
        if (d->address_index&1u) return HMISA_E_UNSUPPORTED;
    } else if (w[1]&0x40000u) {
        d->address_bank=HMISA_VERTEX_INPUT; index_mask=0x1fc00u; bank_mask=0xc0000u;
        d->address_index=(w[1]>>10)&127u;
    } else {
        d->address_bank=HMISA_HWTEMP; index_mask=0x3fc00u; bank_mask=0x80000u;
        d->address_index=(w[1]>>10)&255u;
    }
    /* Opcode, issue/waits, scalar source and address-bank bits are the ONLY
     * variable bits. In particular, early final bits, predicate/ROBUST and
     * unrepresented address modifiers cannot escape these masks. */
    wm0=0x0007ff00u | (mode==4?0x7e000000u:0u);
    if ((w[0]&~wm0)!=0x4eu) return HMISA_E_FORMAT;
    wm1=index_mask|(mode==5?0x60000000u:3u);
    if ((w[1]&~wm1)!=(0x18000200u|bank_mask|(mode==5?0x1eu:0x18u))) return HMISA_E_FORMAT;
    wm2=0x3feffe00u|(mode==5?63u:0u);
    if ((w[2]&~wm2)!=(mode==5?0x180u:0x1f0u)) return HMISA_E_FORMAT;
    if ((w[3]&~0x5ffcu)!=0x83000000u) return HMISA_E_FORMAT;
    d->data_reg=mode==5?((w[1]>>29)&3u)|((w[2]&63u)<<2):
        ((w[0]>>25)&63u)|((w[1]&3u)<<6);
    d->y_count=(w[2]>>9)&2047u; d->x_bytes=(w[2]>>21)&511u;
    d->stride=(w[3]>>2)&2047u; d->add_first=bit(w[3],14);
    g->kind=HMISA_RAW_DMA; g->bytes=16; return HMISA_OK;
}
static int fop(uint32_t w[4],uint32_t n,struct hmisa_raw_group *g)
{
    struct hmisa_fop *f=&g->u.fop;
    uint32_t mul=(w[0]&15u)==13u,base=mul?0x0480868du:0x0480a60bu;
    uint32_t m0,m1,m2,s0,s1;
    /* Direct independently extracted fields. Fixed masks include ALL remaining
     * bits. Defaults are the measured omitted-extension words, not padding. */
    m0=mul?0x31dd1150u:0x3bbd5150u;
    m1=mul?0x05846743u:0x0188e6a2u;
    m2=mul?0x002000b3u:0x00200037u;
    if ((w[0]&~m0)!=(base&~m0) || (w[1]&~m1)!=(0x400808u&~m1) ||
        (w[2]&~m2)!=(0x400u&~m2)) return HMISA_E_FORMAT;
    if ((n==2 && w[1]==0x400808u)||(n==3 && w[2]==0x400u)) return HMISA_E_FORMAT;
    f->op=mul?HMISA_FMUL:bit(w[1],15)?HMISA_FSUB:HMISA_FADD;
    f->dst=bit(w[0],4)|bit(w[0],16)<<1|bit(w[0],24)<<2|bit(w[1],1)<<3|
        bit(w[1],10)<<4|bit(w[1],13)<<5|bit(w[0],18)<<6|bit(w[0],8)<<7;
    s0=bit(w[0],6)|bit(w[0],12)<<1|bit(w[0],20)<<2|bit(w[0],19)<<3|
        bit(w[0],29)<<4|bit(w[0],28)<<5|bit(w[1],14)<<6|bit(w[2],0)<<7;
    s1=mul?bit(w[0],22)|bit(w[1],0)<<1|bit(w[1],6)<<2|bit(w[1],8)<<3|
        bit(w[1],18)<<4|bit(w[1],26)<<5|bit(w[2],7)<<6:
        bit(w[0],14)|bit(w[0],21)<<1|bit(w[0],25)<<2|bit(w[0],27)<<3|
        bit(w[1],5)<<4|bit(w[1],7)<<5|bit(w[1],19)<<6|bit(w[2],2)<<7;
    f->lhs=f->op==HMISA_FSUB?s1:s0; f->rhs=f->op==HMISA_FSUB?s0:s1;
    if (bit(w[0],23)) {
        /* SYNC issue with DESCHED high selector set has no supported meaning. */
        if (bit(w[2],21)) return HMISA_E_FORMAT;
        f->schedule.issue_kind=HMISA_ISSUE_SYNC; f->schedule.issue_index=bit(w[1],9);
    } else if (bit(w[2],21)||bit(w[1],9)) {
        f->schedule.issue_kind=HMISA_ISSUE_DESCHED;
        f->schedule.issue_index=bit(w[2],21)?1u+bit(w[1],9):0;
    } else f->schedule.issue_kind=HMISA_ISSUE_NONE;
    f->schedule.wait_sync=(w[1]>>23)&3u;
    f->schedule.wait_desched=bit(w[2],1)|bit(w[2],4)<<1|bit(w[2],5)<<2;
    if (f->schedule.issue_kind==HMISA_ISSUE_SYNC &&
        (f->schedule.wait_sync&(1u<<f->schedule.issue_index))) return HMISA_E_UNSUPPORTED;
    g->kind=HMISA_RAW_FOP; g->bytes=n*4; return HMISA_OK;
}
int hmisa_raw_decode(const void *code,size_t bytes,struct hmisa_raw_group *out)
{
    uint32_t w[4]={0,0x400808,0x400,0},n=0; struct hmisa_raw_group g; int r;
    const uint8_t *p=code;
    if (!code || !out) return HMISA_E_ARGUMENT;
    if (overlap(code,bytes,out,sizeof *out)) return HMISA_E_ALIAS;
    if (bytes<4) return HMISA_E_FORMAT;
    memset(&g,0,sizeof g); w[0]=word(p);
    if ((w[0]&15u)==14u) {
        if (bytes<16) return HMISA_E_FORMAT;
        for (unsigned j=1;j<4;j++) w[j]=word(p+4*j);
        r=dma(w,&g);
    } else {
        uint32_t max=(w[0]&15u)==12u?2u:3u;
        for (unsigned j=0;j<max;j++) {
            if (bytes<4u*(j+1u)) return HMISA_E_FORMAT;
            w[j]=word(p+4*j);
            if (w[j]&0x80000000u) { n=j+1u; w[j]&=0x7fffffffu; break; }
        }
        if (!n) return HMISA_E_FORMAT;
        if ((w[0]&15u)==11u || (w[0]&15u)==13u) r=fop(w,n,&g);
        else if ((w[0]&15u)==12u) {
            struct hmisa_ctrl *c=&g.u.ctrl;
            if (n==1) w[1]=0;
            if ((w[0]&~0xfc0u)!=0x1cu || (w[1]&~0x340000u)) return HMISA_E_FORMAT;
            c->op=(w[0]>>6)&15u; c->wait_sync=(w[0]>>10)&3u;
            c->wait_desched=bit(w[1],18)|bit(w[1],20)<<1|bit(w[1],21)<<2;
            if ((c->op!=HMISA_NOP && c->op!=HMISA_END) ||
                (c->op==HMISA_END && c->wait_desched)) return HMISA_E_UNSUPPORTED;
            if ((n==2)!=(c->wait_desched!=0)) return HMISA_E_FORMAT;
            g.kind=HMISA_RAW_CTRL; g.bytes=n*4; r=HMISA_OK;
        } else return HMISA_E_UNSUPPORTED;
    }
    if (r) return r;
    *out=g; return HMISA_OK;
}
