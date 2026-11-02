/* The real release overlay and exec-rule headers; follows varfs_seed's selected
 * rule append order and kern_exec's environment iteration. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <miscfs/ramfs/varfs_overlay.h>
#include <kern/hk_exec_rules.h>
int main(int argc, char **argv) {
    assert(argc==3);
    FILE *f=fopen(argv[1],"rb"); assert(f);
    assert(!fseek(f,0,SEEK_END));long length=ftell(f);assert(length>24 && length<(48<<20));rewind(f);
    unsigned char *blob=malloc((size_t)length);assert(blob);
    assert(fread(blob,1,(size_t)length,f)==(size_t)length);fclose(f);
    unsigned long total,at=24;unsigned count,covers;unsigned long long hash;
    assert(!hkov_check(blob,(unsigned long)length,&total,&count,&hash));
    assert(!hkov_cover_check(blob,total,count,0xA0080081u,&covers) && covers==1);
    char rules[HK_RULES_MAX]={0};const char *why=NULL;unsigned library_files=0;
    for(unsigned i=0;i<count;++i) {
        struct hkov_entry e;assert(hkov_next(blob,total,&at,&e,&why)==1);
        if(!(0xA0080081u & (1u<<e.group)))continue;
        if(e.type=='c' && !strcmp(e.path,"hk_env")) {
            assert(!hk_rules_append(rules,sizeof rules,(const char *)e.data,e.data_len));
            assert(!hk_env_check(rules));
        }
        if(e.type=='f' && !strcmp(e.path,"/private/var/hk/hsampler.dylib"))library_files++;
    }
    const char *cursor=rules,*var;unsigned long len;int in_rule=0;
    unsigned dylib_vars=0,mode_vars=0;
    const char *want="DYLD_INSERT_LIBRARIES=/private/var/hk/hgltrack.dylib:/private/var/hk/hsampler.dylib";
    while(hk_env_next(&cursor,&in_rule,"backboardd",10,&var,&len)) {
        if(len>=22 && !strncmp(var,"DYLD_INSERT_LIBRARIES=",22)) {
            dylib_vars++;assert(len==strlen(want) && !strncmp(var,want,len));
        }
        if(len>=10 && !strncmp(var,"HKSAMPLER=",10)) {
            mode_vars++;assert(len==10+strlen(argv[2]) && !strncmp(var+10,argv[2],len-10));
        }
    }
    assert(library_files==1 && dylib_vars==1 && mode_vars==(!strcmp(argv[2],"off")?0u:1u));
    free(blob);
    puts("PASS: actual kernel overlay/rule append/exec iteration: exactly one complete dylib list, mode, file, cover");
    return 0;
}
