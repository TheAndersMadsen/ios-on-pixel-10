/* Run the unmodified reference ARM64 leaf extracted locally, and our actual
 * compiled candidate on identical inputs. No reimplementation as the oracle. */
#include "hsampler.h"
#include "fingerprint.h"
#include <assert.h>
#include <fcntl.h>
#include <libkern/OSCacheControl.h>
#include <mach-o/loader.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

void hs_backboardd_sampler(const hs_data *, unsigned, uint32_t *, unsigned);
void hs_backboardd_projective(const hs_data *, unsigned, uint32_t *, unsigned);
void hs_test_bind(hs_original, int);
void hs_test_bind_projective(hs_original);
uint64_t hs_test_verified(void), hs_test_mismatches(void);
int hs_test_latched(void);
void hs_test_reset(void);
static hs_original ref, pref;
static unsigned long spans, optimized;
static uint32_t rng = 0x68a1d9efu;
static uint32_t random32(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static hs_original load_reference(const char *path) {
    int fd = open(path, O_RDONLY); assert(fd >= 0);
    struct stat st; assert(!fstat(fd, &st));
    uint8_t *file = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    assert(file != MAP_FAILED); close(fd);
    struct mach_header_64 *h = (void *)file;
    assert(h->magic == MH_MAGIC_64);
    const uint8_t *p = (const void *)(h + 1), *code = NULL;
    for (unsigned i = 0; i < h->ncmds; ++i) {
        const struct load_command *lc = (const void *)p;
        if (lc->cmd == LC_SEGMENT_64) {
            const struct segment_command_64 *s = (const void *)p;
            if (s->vmaddr <= HS_FN_UNSLID && HS_FN_UNSLID + HS_FN_SIZE <= s->vmaddr + s->filesize)
                code = file + s->fileoff + HS_FN_UNSLID - s->vmaddr;
        }
        p += lc->cmdsize;
    }
    assert(code);
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    for (size_t i = 0; i < HS_FN_SIZE; ++i) hash = (hash ^ code[i]) * UINT64_C(0x100000001b3);
    assert(hash == HS_FN_FNV);
    const uint8_t *projective_code = code - (HS_FN_UNSLID - HS_PROJECTIVE_FN_UNSLID);
    hash = UINT64_C(0xcbf29ce484222325);
    for (size_t i=0;i<HS_PROJECTIVE_FN_SIZE;++i) hash=(hash^projective_code[i])*UINT64_C(0x100000001b3);
    assert(hash == HS_PROJECTIVE_FN_FNV);
    /* Map the complete text segment at a page-aligned slide. Original ADRP
     * references in the projective function then reach the original constants.
     * No instructions, constants or branch targets are rewritten. */
    p = (const void *)(h + 1); const struct segment_command_64 *text = NULL;
    for (unsigned i=0;i<h->ncmds;++i) {
        const struct load_command *lc=(const void *)p;
        if(lc->cmd==LC_SEGMENT_64 && !strcmp(((const struct segment_command_64 *)p)->segname,"__TEXT")) text=(const void *)p;
        p+=lc->cmdsize;
    }
    assert(text);
    uint8_t *exec = mmap(NULL, (size_t)text->vmsize, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE, -1, 0);
    assert(exec != MAP_FAILED); memcpy(exec, file+text->fileoff, (size_t)text->filesize);
    assert(!mprotect(exec, (size_t)text->vmsize, PROT_READ | PROT_EXEC));
    sys_icache_invalidate(exec, (size_t)text->vmsize);
    uint64_t va=text->vmaddr;
    pref=(hs_original)(exec+HS_PROJECTIVE_FN_UNSLID-va);
    munmap(file, (size_t)st.st_size);
    return (hs_original)(exec+HS_FN_UNSLID-va);
}
static void compare(hs_image *im, int32_t x, int32_t y, unsigned n, int32_t dx) {
    hs_data d = {.image = im, .x = x, .dx = dx, .y = y};
    uint32_t a[1200], b[1200]; assert(n < 1198);
    for (unsigned i = 0; i < 1200; ++i) a[i] = b[i] = 0xdeddbabbu;
    ref(&d, n, a + 1, 0xa123);
    unsigned fast = hs_try(&d, n, b + 1, 0xa123, ref);
    if (fast) { optimized++; assert(!memcmp(a, b, sizeof a)); }
    else { for (unsigned i = 0; i < 1200; ++i) assert(b[i] == 0xdeddbabbu); }
    spans++;
}
static void differential(void) {
    uint32_t data[1200 * 7];
    for (unsigned i = 0; i < 1200 * 7; ++i) data[i] = random32();
    const unsigned widths[] = {2, 3, 4, 5, 17, 37, 257, 1125};
    const unsigned lens[] = {0, 1, 3, 4, 5, 7, 8, 15, 16, 31, 1130};
    const int32_t xs[] = {-262144, -32769, -32768, -1, 0, 1, 32767, 32768, 65535, 65536, 98303, 98304};
    const int32_t ys[] = {INT32_MIN, -65537, -1, 0, 32767, 32768, 98304, 196607, INT32_MAX};
    for (unsigned w = 0; w < sizeof widths / sizeof *widths; ++w) {
        hs_image im = {(const uint8_t *)data, 0, 1200 * 4, widths[w], 7, (int32_t)(widths[w] << 16)-1, (7 << 16)-1};
        for (unsigned l = 0; l < sizeof lens / sizeof *lens; ++l)
            for (unsigned x = 0; x < sizeof xs / sizeof *xs; ++x)
                for (unsigned y = 0; y < sizeof ys / sizeof *ys; ++y)
                    compare(&im, xs[x], ys[y], lens[l], 65536);
    }
    hs_image im = {(const uint8_t *)data, 0, 1200 * 4, 37, 7, (37 << 16)-1, (7 << 16)-1};
    /* Exhaust all 256x256 quantized bilinear weights and low discarded bits.
     * Covers signed rounding, arbitrary alpha/channel bytes, and both tails. */
    for (unsigned fx = 0; fx < 256; ++fx)
        for (unsigned fy = 0; fy < 256; ++fy)
            compare(&im, 32768 + (int32_t)(fx << 8) + (fx & 255),
                    32768 + (int32_t)(fy << 8) + ((255-fy) & 255), 11, 65536);
    for (unsigned i = 0; i < 5000; ++i) {
        im.width = 5 + random32() % 1121; im.xmax = (int32_t)(im.width << 16)-1;
        compare(&im, (int32_t)(random32() % ((im.width + 8) << 16)) - (4 << 16),
                (int32_t)random32(), 1 + random32() % 1130, 65536);
    }
    puts("PASS: exact original ARM64 differential (weight grid, random channels, borders, fixed-point extremes, widths/strides/tails)");
}
static void guard_and_refusals(void) {
    size_t page = (size_t)getpagesize();
    uint8_t *mem = mmap(NULL, page * 2, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    assert(mem != MAP_FAILED && !mprotect(mem + page, page, PROT_NONE));
    for (unsigned width = 5; width < 21; ++width) {
        uint32_t *data = (void *)(mem + page - width * 4);
        for (unsigned i = 0; i < width; ++i) data[i] = random32();
        hs_image im = {(const uint8_t *)data, 0, width * 4, width, 1, (int32_t)(width << 16)-1, 65535};
        compare(&im, 32768 + 123, INT32_MAX, width, 65536);
        compare(&im, 32768, -5000, width, 65536);
        hs_data d = {.image=&im, .x=32768, .y=32768, .dx=65536}; hs_plan p;
        uint32_t out[40]; memset(out, 0xa5, sizeof out); uint32_t before[40]; memcpy(before,out,sizeof out);
        assert(hs_prepare(&d,width,data,&p) == HS_ALIAS);
        const int32_t deltas[] = {0,-65536,32768,65535,65537,131072,INT32_MAX};
        for (unsigned i=0;i<sizeof deltas/sizeof *deltas;++i) {
            d.dx=deltas[i]; assert(!hs_try(&d,width,out,0,ref)); assert(!memcmp(out,before,sizeof out));
        }
        d.dx=65536; im.xmax--; assert(!hs_try(&d,width,out,0,ref)); im.xmax++;
        im.stride--; assert(!hs_try(&d,width,out,0,ref)); im.stride++;
        im.stride=INT64_MAX; im.height=3; im.ymax=(3<<16)-1;
        assert(!hs_try(&d,width,out,0,ref));
    }
    munmap(mem, page * 2);
    puts("PASS: guard page at final source pixel, alias/transform/layout/overflow refusal without writes");
}
static void corrupt_reference(const hs_data *d, unsigned n, uint32_t *out, unsigned arg) {
    ref(d,n,out,arg); if(n) out[0] ^= 1;
}
static void wrapper(void) {
    uint32_t data[64]; for(unsigned i=0;i<64;++i)data[i]=random32();
    hs_image im={(const uint8_t *)data,0,128,32,2,(32<<16)-1,(2<<16)-1};
    hs_data d={.image=&im,.dx=65536,.x=32768+300,.y=32768+123}; uint32_t a[32],b[32];
    ref(&d,32,a,0);
    for(int mode=1;mode<=3;++mode) { hs_test_bind(ref,mode); hs_backboardd_sampler(&d,32,b,0); assert(!memcmp(a,b,sizeof a)); }
    assert(hs_test_verified()==32 && !hs_test_mismatches());
    hs_test_bind(corrupt_reference,2); hs_backboardd_sampler(&d,32,b,0);
    assert(hs_test_latched() && hs_test_mismatches()==1 && b[0]==(a[0]^1));
    hs_test_bind(corrupt_reference,3); hs_backboardd_sampler(&d,32,b,0);
    assert(b[0]==(a[0]^1)); hs_test_reset();
    puts("PASS: actual hook wrapper observe/verify/fast, forced differential mismatch retains original and latches fallback");
}
static void projective(void) {
    assert(hs_projective_selfcheck(pref,ref));
    uint32_t *data=malloc(4608*4); assert(data); for(unsigned i=0;i<4608;++i)data[i]=random32();
    hs_image im={(const uint8_t *)data,0,4608,1125,4,(1125<<16)-1,(4<<16)-1};
    hs_projective_data pd={.base={.image=&im,.dx=65536}};
    uint32_t q[4]={0,0,0,0x3f800000},dq[4]={0}; const void *qp=q,*dp=dq;
    memcpy((uint8_t *)&pd+0x10,&qp,sizeof qp);memcpy((uint8_t *)&pd+0x18,&dp,sizeof dp);
    uint32_t a[1130],b[1130];
    hs_test_bind(ref,3); hs_test_bind_projective(pref);
    hs_backboardd_sampler(NULL,0,NULL,0);hs_backboardd_projective(NULL,0,NULL,0);
    for(unsigned i=0;i<1000;++i) {
        pd.base.x=(int32_t)((random32()%65536)&~127u)-32768;
        pd.base.y=(int32_t)(random32()&0x7fffff80u);
        pref(&pd.base,1130,a,0); hs_backboardd_projective(&pd.base,1130,b,0);
        assert(!memcmp(a,b,sizeof a));
    }
    pd.base.x=32768;pd.base.y=32768;
    for(unsigned mode=1;mode<=3;++mode) {
        hs_test_bind(ref,(int)mode); pref(&pd.base,1130,a,0);hs_backboardd_projective(&pd.base,1130,b,0);assert(!memcmp(a,b,sizeof a));
    }
    pd.base.x++; assert(!hs_projective_axes(&pd.base)); pd.base.x--;
    /* Reproduce a real reason for the representability guard: SCVTF rounds
     * this large fixed coordinate across a quantized weight boundary. */
    pd.base.x=(1024<<16)+32768+65535;
    pref(&pd.base,8,a,0);ref(&pd.base,8,b,0);assert(memcmp(a,b,8*4));
    assert(!hs_projective_axes(&pd.base));
    hs_backboardd_projective(&pd.base,8,b,0);assert(!memcmp(a,b,8*4));
    pd.base.x=32768;
    pd.base.y++; assert(!hs_projective_axes(&pd.base)); pd.base.y--;
    pd.dy=1;assert(!hs_projective_axes(&pd.base));pd.dy=0;
    dq[3]=0x3a800000;assert(!hs_projective_axes(&pd.base));dq[3]=0;
    q[3]=0x3f7fffff;assert(!hs_projective_axes(&pd.base));q[3]=0x3f800000;
    ((uint8_t *)&pd)[0x30]=5;assert(!hs_projective_axes(&pd.base));
    free(data);
    puts("PASS: unmodified projective ARM64 oracle, exact-W/representability specialization and real wrapper modes/refusals");
}
static uint64_t ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC_RAW,&t);return (uint64_t)t.tv_sec*1000000000+(uint64_t)t.tv_nsec; }
static void benchmark(void) {
    uint32_t *data=malloc(4608*4); assert(data); for(unsigned i=0;i<4608;++i)data[i]=random32();
    hs_image im={(const uint8_t *)data,0,4608,1125,4,(1125<<16)-1,(4<<16)-1};
    hs_data d={.image=&im,.dx=65536,.x=32768+12345,.y=32768+45678}; uint32_t out[1125];
    const unsigned reps=20000; uint64_t start=ns();
    for(unsigned i=0;i<reps;++i)ref(&d,1125,out,0);
    uint64_t original_ns=ns()-start; start=ns();
    for(unsigned i=0;i<reps;++i)assert(hs_try(&d,1125,out,0,ref));
    uint64_t candidate_ns=ns()-start;
    printf("HOST MICROBENCH only: fractional 1125px row, original=%llu ns, candidate=%llu ns, reps=%u (not phone FPS)\n",(unsigned long long)original_ns,(unsigned long long)candidate_ns,reps);
    free(data);
}
int main(int argc,char **argv) {
    assert(argc==2); ref=load_reference(argv[1]); assert(hs_selfcheck(ref));
    differential(); guard_and_refusals(); wrapper(); projective(); benchmark();
    printf("PASS: %lu differential spans, %lu eligible spans; no phone test\n",spans,optimized);
    return 0;
}
