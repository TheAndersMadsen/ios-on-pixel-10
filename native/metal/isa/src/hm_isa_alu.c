/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors.
 * Original C implementation; bit facts reuse immutable original MIT isa/
 * measurements, extended with fresh bounded codec and named fence conversions.
 * No proprietary source/function body or executable stage template copied.
 */
#include "hm_isa_alu.h"
#include <string.h>

struct pos { uint8_t word,bit; };
static const struct pos dstpos[]={{0,4},{0,16},{0,24},{1,1},{1,10},{1,13},{0,18},{0,8}};
static const struct pos src0pos[]={{0,6},{0,12},{0,20},{0,19},{0,29},{0,28},{1,14},{2,0}};
static const struct pos src1pos[]={{0,22},{1,0},{1,6},{1,8},{1,18},{1,26},{2,7}};
static const struct pos src2pos[]={{0,14},{0,21},{0,25},{0,27},{1,5},{1,7},{1,19},{2,2}};
static int overlaps(const void *a,size_t an,const void *b,size_t bn)
{
    uintptr_t av=(uintptr_t)a,bv=(uintptr_t)b;
    return an && bn && (av<=bv ? bv-av<an : av-bv<bn);
}
static void insert(uint32_t w[3],const struct pos *p,size_t n,uint32_t v)
{
    for (size_t i=0;i<n;i++) {
        uint32_t mask=1u<<p[i].bit;
        w[p[i].word]=(w[p[i].word]&~mask)|(((v>>i)&1u)<<p[i].bit);
    }
}
static uint32_t extract(const uint32_t w[3],const struct pos *p,size_t n)
{
    uint32_t v=0;
    for (size_t i=0;i<n;i++) v|=((w[p[i].word]>>p[i].bit)&1u)<<i;
    return v;
}
static void put(uint8_t *p,uint32_t v)
{
    for (unsigned i=0;i<4;i++) p[i]=(uint8_t)(v>>(8*i));
}
static uint32_t get(const uint8_t *p)
{
    return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static int fvalid(const struct hmisa_fop *f)
{
    const struct hmisa_schedule *s;
    if (!f) return HMISA_E_ARGUMENT;
    if ((f->op!=HMISA_FADD && f->op!=HMISA_FSUB && f->op!=HMISA_FMUL)||
        f->dst>255 || f->lhs>255 || f->rhs>(f->op==HMISA_FMUL?127u:255u))
        return HMISA_E_UNSUPPORTED;
    s=&f->schedule;
    if (s->wait_desched>7 || s->wait_sync>3) return HMISA_E_UNSUPPORTED;
    if (s->issue_kind==HMISA_ISSUE_SYNC) {
        if (s->issue_index>1 || (s->wait_sync&(1u<<s->issue_index))) return HMISA_E_UNSUPPORTED;
    } else if (s->issue_kind==HMISA_ISSUE_DESCHED) {
        if (s->issue_index>2) return HMISA_E_UNSUPPORTED;
    } else if (s->issue_kind!=HMISA_ISSUE_NONE || s->issue_index) return HMISA_E_UNSUPPORTED;
    return HMISA_OK;
}
int hmisa_fop_descriptor(const struct hmisa_fop *f,uint32_t out[56])
{
    uint32_t g[56]={0}; int r;
    if (!out) return HMISA_E_ARGUMENT;
    if ((r=fvalid(f))) return r;
    if (overlaps(f,sizeof *f,out,sizeof g)) return HMISA_E_ALIAS;
#define G(o,v) g[(o)/4]=(v)
    G(0x2c,1); G(0x30,f->schedule.issue_kind); G(0x34,f->schedule.issue_index);
    G(0x38,f->schedule.wait_desched); G(0x3c,f->schedule.wait_sync);
    G(0x40,4); G(0x44,f->dst); G(0x50,2); G(0x5c,4);
    G(0x60,f->op==HMISA_FSUB?f->rhs:f->lhs); G(0x64,2); G(0x74,2); G(0x84,2);
    if (f->op==HMISA_FMUL) { G(0x6c,4); G(0x70,f->rhs); G(0x7c,8); G(0x8c,1); }
    else {
        G(0x6c,8); G(0x7c,4); G(0x80,f->op==HMISA_FSUB?f->lhs:f->rhs); G(0x8c,2);
        if (f->op==HMISA_FSUB) G(0x68,0x100);
    }
    G(0xdc,1);
#undef G
    memcpy(out,g,sizeof g); return HMISA_OK;
}
int hmisa_fop_encode(uint32_t enable,const struct hmisa_fop *f,void *out,size_t cap,size_t *written)
{
    uint32_t w[3]; uint8_t bytes[12]; size_t n; int r;
    if (enable!=HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!out || !written) return HMISA_E_ARGUMENT;
    if ((r=fvalid(f))) return r;
    w[0]=f->op==HMISA_FMUL?0x0480868d:0x0480a60b; w[1]=0x00400808; w[2]=0x400;
    insert(w,dstpos,8,f->dst); insert(w,src0pos,8,f->op==HMISA_FSUB?f->rhs:f->lhs);
    insert(w,f->op==HMISA_FMUL?src1pos:src2pos,f->op==HMISA_FMUL?7u:8u,
        f->op==HMISA_FSUB?f->lhs:f->rhs);
    if (f->op==HMISA_FSUB) w[1]|=1u<<15;
    /* Issue-none differs from the old implicit SYNC0. Two distinct fence
     * namespaces are explicit, including their noncontiguous extension bits. */
    if (f->schedule.issue_kind!=HMISA_ISSUE_SYNC) w[0]&=~(1u<<23);
    if ((f->schedule.issue_kind==HMISA_ISSUE_SYNC && f->schedule.issue_index==1)||
        (f->schedule.issue_kind==HMISA_ISSUE_DESCHED && f->schedule.issue_index!=1)) w[1]|=1u<<9;
    if (f->schedule.issue_kind==HMISA_ISSUE_DESCHED && f->schedule.issue_index) w[2]|=1u<<21;
    w[1]|=f->schedule.wait_sync<<23;
    w[2]|=(f->schedule.wait_desched&1u)<<1|(f->schedule.wait_desched&6u)<<3;
    n=w[2]!=0x400?3u:w[1]!=0x400808?2u:1u;
    if (cap<4*n) return HMISA_E_CAPACITY;
    if (overlaps(out,4*n,f,sizeof *f)||overlaps(written,sizeof *written,f,sizeof *f)||
        overlaps(out,4*n,written,sizeof *written)) return HMISA_E_ALIAS;
    w[n-1]|=0x80000000;
    for (size_t i=0;i<n;i++) put(bytes+4*i,w[i]);
    memcpy(out,bytes,4*n); *written=4*n; return HMISA_OK;
}
int hmisa_fop_from_descriptor(const uint32_t input[56],struct hmisa_fop *out)
{
    uint32_t g[56],expected[56]; struct hmisa_fop f; int r;
    if (!input || !out) return HMISA_E_ARGUMENT;
    if (overlaps(input,sizeof g,out,sizeof *out)) return HMISA_E_ALIAS;
    memcpy(g,input,sizeof g); memset(&f,0,sizeof f);
    f.op=g[0x8c/4]==1?HMISA_FMUL:g[0x68/4]==0x100?HMISA_FSUB:HMISA_FADD;
    f.dst=g[0x44/4]; f.lhs=g[(f.op==HMISA_FSUB?0x80:0x60)/4];
    f.rhs=g[(f.op==HMISA_FMUL?0x70:f.op==HMISA_FSUB?0x60:0x80)/4];
    f.schedule=(struct hmisa_schedule){g[12],g[13],g[14],g[15]};
    if ((r=hmisa_fop_descriptor(&f,expected))) return r;
    if (memcmp(g,expected,sizeof g)) return HMISA_E_FORMAT;
    *out=f; return HMISA_OK;
}
int hmisa_fop_decode(const void *code,size_t n,struct hmisa_fop *out)
{
    uint32_t w[3]={0,0x400808,0x400}; struct hmisa_fop f;
    uint8_t bytes[12]; size_t size; int r;
    if (!code || !out) return HMISA_E_ARGUMENT;
    if (n!=4 && n!=8 && n!=12) return HMISA_E_FORMAT;
    if (overlaps(code,n,out,sizeof *out)) return HMISA_E_ALIAS;
    for (size_t i=0;i<n/4;i++) {
        w[i]=get((const uint8_t *)code+4*i);
        if (((w[i]>>31)!=0)!=(i==n/4-1)) return HMISA_E_FORMAT;
    }
    w[n/4-1]&=0x7fffffff;
    if ((w[0]&15)!=0xb && (w[0]&15)!=0xd) return HMISA_E_UNSUPPORTED;
    memset(&f,0,sizeof f);
    f.op=(w[0]&15)==0xd?HMISA_FMUL:w[1]&(1u<<15)?HMISA_FSUB:HMISA_FADD;
    f.dst=extract(w,dstpos,8);
    uint32_t s0=extract(w,src0pos,8),s1=extract(w,f.op==HMISA_FMUL?src1pos:src2pos,f.op==HMISA_FMUL?7u:8u);
    f.lhs=f.op==HMISA_FSUB?s1:s0; f.rhs=f.op==HMISA_FSUB?s0:s1;
    if (w[0]&(1u<<23)) { f.schedule.issue_kind=HMISA_ISSUE_SYNC; f.schedule.issue_index=(w[1]>>9)&1; }
    else if ((w[2]&(1u<<21))||(w[1]&(1u<<9))) {
        f.schedule.issue_kind=HMISA_ISSUE_DESCHED;
        f.schedule.issue_index=w[2]&(1u<<21)?1u+((w[1]>>9)&1):0;
    } else f.schedule.issue_kind=HMISA_ISSUE_NONE;
    f.schedule.wait_sync=(w[1]>>23)&3;
    f.schedule.wait_desched=((w[2]>>1)&1)|((w[2]>>3)&6);
    if ((r=hmisa_fop_encode(HMISA_ENABLE_GROUPS,&f,bytes,sizeof bytes,&size))) return r;
    if (size!=n || memcmp(bytes,code,n)) return HMISA_E_FORMAT;
    *out=f; return HMISA_OK;
}
static int cvalid(const struct hmisa_ctrl *c)
{
    if (!c) return HMISA_E_ARGUMENT;
    if ((c->op!=HMISA_END && c->op!=HMISA_NOP)||c->wait_sync>3||c->wait_desched>7||
        (c->op==HMISA_END && c->wait_desched)) return HMISA_E_UNSUPPORTED;
    return HMISA_OK;
}
int hmisa_ctrl_descriptor(const struct hmisa_ctrl *c,uint32_t out[56])
{
    uint32_t g[56]={0}; int r;
    if (!out) return HMISA_E_ARGUMENT;
    if ((r=cvalid(c))) return r;
    if (overlaps(c,sizeof *c,out,sizeof g)) return HMISA_E_ALIAS;
    g[10]=14; g[12]=c->wait_desched; g[13]=c->wait_sync; g[14]=c->op;
    g[16]=2; g[27]=7; g[31]=7; g[55]=1;
    memcpy(out,g,sizeof g); return HMISA_OK;
}
int hmisa_ctrl_encode(uint32_t enable,const struct hmisa_ctrl *c,void *out,size_t cap,size_t *written)
{
    uint32_t w[2]; uint8_t bytes[8]; size_t n; int r;
    if (enable!=HMISA_ENABLE_GROUPS) return HMISA_E_DISABLED;
    if (!out || !written) return HMISA_E_ARGUMENT;
    if ((r=cvalid(c))) return r;
    w[0]=0x1c|c->op<<6|c->wait_sync<<10;
    w[1]=(c->wait_desched&1u)<<18|(c->wait_desched&6u)<<19;
    n=c->wait_desched?2u:1u;
    if (cap<4*n) return HMISA_E_CAPACITY;
    if (overlaps(out,4*n,c,sizeof *c)||overlaps(written,sizeof *written,c,sizeof *c)||
        overlaps(out,4*n,written,sizeof *written)) return HMISA_E_ALIAS;
    w[n-1]|=0x80000000;
    for (size_t i=0;i<n;i++) put(bytes+4*i,w[i]);
    memcpy(out,bytes,4*n); *written=4*n; return HMISA_OK;
}
int hmisa_ctrl_from_descriptor(const uint32_t input[56],struct hmisa_ctrl *out)
{
    uint32_t g[56],expected[56]; struct hmisa_ctrl c; int r;
    if (!input || !out) return HMISA_E_ARGUMENT;
    if (overlaps(input,sizeof g,out,sizeof *out)) return HMISA_E_ALIAS;
    memcpy(g,input,sizeof g); c=(struct hmisa_ctrl){g[14],g[12],g[13]};
    if ((r=hmisa_ctrl_descriptor(&c,expected))) return r;
    if (memcmp(g,expected,sizeof g)) return HMISA_E_FORMAT;
    *out=c; return HMISA_OK;
}
int hmisa_ctrl_decode(const void *code,size_t n,struct hmisa_ctrl *out)
{
    uint32_t w[2]={0,0}; struct hmisa_ctrl c; uint8_t bytes[8]; size_t size; int r;
    if (!code || !out) return HMISA_E_ARGUMENT;
    if (n!=4 && n!=8) return HMISA_E_FORMAT;
    if (overlaps(code,n,out,sizeof *out)) return HMISA_E_ALIAS;
    for (size_t i=0;i<n/4;i++) w[i]=get((const uint8_t *)code+4*i);
    c=(struct hmisa_ctrl){(w[0]>>6)&15,((w[1]>>18)&1)|((w[1]>>19)&6),(w[0]>>10)&3};
    if ((r=hmisa_ctrl_encode(HMISA_ENABLE_GROUPS,&c,bytes,sizeof bytes,&size))) return r;
    if (size!=n || memcmp(bytes,code,n)) return HMISA_E_FORMAT;
    *out=c; return HMISA_OK;
}
