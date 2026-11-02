/* SPDX-License-Identifier: MIT
 * Copyright (c) 2026 hackios contributors. Real AIR frontend/link composition.
 */
#include "hm_isa_program.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr,"line %d: %s\n",__LINE__,#x); goto done; } } while (0)
static int run(const char *path,const char *entry,uint32_t fops,uint32_t hw,int multi)
{
    hm_air_program *p=NULL; hm_air_diagnostic d={0};
    struct hmisa_pointer ptrs[3]={{0,7,0,3,0,12},{1,7,2,1,0,12},{2,7,4,2,0,16}};
    size_t np=multi?3u:1u; uint32_t sh=multi?6u:2u,mask=multi?63u:3u;
    if (multi) { ptrs[0].access=1; ptrs[0].bytes_available=8; }
    struct hmisa_stage_body body,before; struct hmisa_unlinked u,bad; hm_air_info_t info;
    FILE *file=fopen(path,"rb"); uint8_t *buf=NULL; long n; int ok=0;
    CHECK(file && !fseek(file,0,SEEK_END)); n=ftell(file); CHECK(n>0 && n<4194304 && !fseek(file,0,SEEK_SET));
    buf=malloc((size_t)n); CHECK(buf && fread(buf,1,(size_t)n,file)==(size_t)n); fclose(file); file=NULL;
    CHECK(!hm_air_open(buf,(size_t)n,(const uint8_t *)entry,strlen(entry),&p,&d));
    memset(buf,0,(size_t)n); free(buf); buf=NULL; CHECK(!hm_air_info(p,&info));
    CHECK(!hmisa_air_prepare(1,p,ptrs,np,hw,&u));
    CHECK(!hmisa_air_link(1,p,ptrs,np,hw,sh,0,&body));
    CHECK(!memcmp(&info,&body.air,sizeof info) && body.facts.temps==hw);
    CHECK(body.facts.obligations==63 && !body.facts.end_count && body.facts.shared_read_mask[0]==mask);
    CHECK(body.facts.fop_count==fops && body.facts.access_count==3 && body.facts.groups==u.fragment_count);
    CHECK(body.facts.shared_words==sh);
    if (multi) for (unsigned j=0;j<3;j++) {
        CHECK(body.facts.accesses[j].binding==j && body.facts.accesses[j].index==2*j);
        CHECK(body.facts.accesses[j].begin_byte==4*(j+1) && body.facts.accesses[j].end_byte==4*(j+2));
    }
    for (uint32_t j=0;j<body.entry_count;j++) {
        const struct hmisa_layout_entry *e=&body.entries[j];
        CHECK(e->fragment==j && e->air_index==u.fragments[j].air_index);
        CHECK(!memcmp(body.code+e->offset,u.fragments[j].code,e->bytes));
    }
    for (uint32_t j=body.facts.code_bytes;j<sizeof body.code;j++) CHECK(!body.code[j]);
    /* Metadata/source hash is never permission to skip real code analysis. */
    memset(&body,0x55,sizeof body); before=body;
    bad=u; bad.fragments[0].end_byte++;
    CHECK(hmisa_stage_link(1,&bad,ptrs,np,hw,sh,0,&body)==HMISA_E_FORMAT && !memcmp(&body,&before,sizeof body));
    bad=u; bad.fragments[0].value_reg++;
    CHECK(hmisa_stage_link(1,&bad,ptrs,np,hw,sh,0,&body)==HMISA_E_FORMAT && !memcmp(&body,&before,sizeof body));
    bad=u; bad.allocation.high_water++;
    CHECK(hmisa_stage_link(1,&bad,ptrs,np,hw,sh,0,&body)==HMISA_E_FORMAT && !memcmp(&body,&before,sizeof body));
    bad=u; bad.fragments[1].code[0]^=0x40;
    CHECK(hmisa_stage_link(1,&bad,ptrs,np,hw,sh,0,&body)!=0 && !memcmp(&body,&before,sizeof body));
    bad=u; bad.fragments[0].code[0]^=0x80;
    CHECK(hmisa_stage_link(1,&bad,ptrs,np,hw,sh,0,&body)==HMISA_E_FORMAT && !memcmp(&body,&before,sizeof body));
    bad=u; bad.fragments[0].code_bytes=12;
    CHECK(hmisa_stage_link(1,&bad,ptrs,np,hw,sh,0,&body)==HMISA_E_FORMAT && !memcmp(&body,&before,sizeof body));
    CHECK(hmisa_air_link(0,p,ptrs,np,hw,sh,0,&body)==HMISA_E_DISABLED && !memcmp(&body,&before,sizeof body));
    CHECK(hmisa_air_link(1,p,ptrs,np,hw-1,sh,0,&body)==HMISA_E_CAPACITY && !memcmp(&body,&before,sizeof body));
    ptrs[np-1].bytes_available--;
    CHECK(hmisa_air_link(1,p,ptrs,np,hw,sh,0,&body)==HMISA_E_BOUNDS && !memcmp(&body,&before,sizeof body));
    ptrs[np-1].bytes_available++; CHECK(!hmisa_air_link(1,p,ptrs,np,hw,sh,0,&body));
    printf("PASS actual AIR %s -> allocation/LD/FOP/ST/waits -> layout/raw analysis, bytes%u temps%u obligations%u\n",
        path,body.facts.code_bytes,body.facts.temps,body.facts.obligations); ok=1;
done:
    if (!ok && d.message[0]) fprintf(stderr,"AIR %s\n",d.message);
    free(buf); if (file) fclose(file); hm_air_release(p); return !ok;
}
int main(int argc,char **argv)
{
    if (argc!=7) return 2;
    return run(argv[1],"air_single_add",1,3,0)||run(argv[2],"test",1,3,0)||run(argv[3],"test",1,3,0)||
        run(argv[4],"test",1,3,0)||run(argv[5],"test",3,4,0)||run(argv[6],"multi",1,3,1);
}
