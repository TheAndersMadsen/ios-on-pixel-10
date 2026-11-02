#include "hsampler.h"
#if HK_SAMPLER_NEON
#include <arm_neon.h>
#include <limits.h>
#include <string.h>

static int64_t bound(int64_t v, int64_t hi) { return v < 0 ? 0 : v > hi ? hi : v; }
int hs_projective_axes(const hs_data *d) {
    if (!d || ((const uint8_t *)d)[0x30] || d->dx != 65536 ||
        ((uint32_t)d->x & 127) || ((uint32_t)d->y & 127)) return 0;
    int32_t dy; const uint8_t *q, *dq; uint32_t qw, dqw;
    memcpy(&dy, (const uint8_t *)d + 0x40, sizeof dy);
    memcpy(&q, (const uint8_t *)d + 0x10, sizeof q);
    memcpy(&dq, (const uint8_t *)d + 0x18, sizeof dq);
    if (dy || !q || !dq) return 0;
    memcpy(&qw, q + 12, sizeof qw); memcpy(&dqw, dq + 12, sizeof dqw);
    /* Integers divisible by 128 are exact in binary32 throughout int32's
     * range. Without this guard SCVTF+FCVTZS can round across an 8-bit filter
     * weight boundary, even with q=1. No reciprocal approximation is used. */
    return qw == 0x3f800000u && !(dqw & 0x7fffffffu);
}
enum hs_reason hs_prepare(const hs_data *d, unsigned n, uint32_t *out, hs_plan *p) {
    if (!d || !n || !out || !p) return HS_SPAN;
    if (d->dx != 65536) return HS_TRANSFORM;
    const hs_image *im = d->image;
    if (!im || !im->pixels || im->width < 2 || im->width > 32767 ||
        !im->height || im->height > 32767 ||
        im->xmax != (int32_t)((im->width << 16) - 1) ||
        im->ymax != (int32_t)((im->height << 16) - 1) ||
        im->stride < (int64_t)im->width * 4) return HS_LAYOUT;
    /* The original advances a 32-bit signed fixed-point coordinate. Do not
     * reinterpret its wrap behavior, negative strides or oversized surfaces. */
    int64_t end = (int64_t)d->x + (int64_t)(n - 1) * 65536;
    if (end > INT32_MAX) return HS_SPAN;
    uint64_t rows = im->height - 1, stride = (uint64_t)im->stride;
    if (rows && stride > (UINT64_MAX - (uint64_t)im->width * 4) / rows) return HS_LAYOUT;
    uint64_t bytes = rows * stride + (uint64_t)im->width * 4;
    uintptr_t base = (uintptr_t)im->pixels, dst = (uintptr_t)out;
    uint64_t outbytes = (uint64_t)n * 4;
    if (bytes > UINTPTR_MAX - base || outbytes > UINTPTR_MAX - dst) return HS_LAYOUT;
    if (dst < base + bytes && base < dst + outbytes) return HS_ALIAS;
    uintptr_t data = (uintptr_t)d, image = (uintptr_t)im;
    if ((dst < data + sizeof *d && data < dst + outbytes) ||
        (dst < image + sizeof *im && image < dst + outbytes)) return HS_ALIAS;
    int64_t first = d->x >= 32768 ? 0 : (32768 - (int64_t)d->x + 65535) / 65536;
    int64_t high = (int64_t)im->xmax - 32768;
    if (d->x > high || first >= n) return HS_SPAN;
    int64_t last = (high - d->x) / 65536 + 1;
    if (last > n) last = n;
    if (last - first < 4) return HS_SPAN;
    int64_t x = (int64_t)d->x + first * 65536 - 32768;
    int64_t lo = bound((int64_t)d->y - 32768, im->ymax);
    int64_t hi = bound((int64_t)d->y + 32768, im->ymax);
    p->top = im->pixels + (lo >> 16) * stride + (x >> 16) * 4;
    p->bottom = im->pixels + (hi >> 16) * stride + (x >> 16) * 4;
    p->first = (unsigned)first; p->count = (unsigned)(last - first);
    p->fx = (int16_t)((x >> 1) & 0x7f80);
    p->fy = (int16_t)((lo >> 1) & 0x7f80);
    return HS_OK;
}

/* QuartzCore uses SQRDMULH on signed channel differences. In particular it
 * rounds after vertical interpolation, then again after horizontal. Reordering
 * these operations, floating-point interpolation or a /255 weight changes pixels. */
static inline int16x8_t lerp8(int16x8_t a, int16x8_t b, int16_t f) {
    return vaddq_s16(a, vqrdmulhq_n_s16(vsubq_s16(b, a), f));
}
static inline int16x8_t widen(uint8x8_t a) { return vreinterpretq_s16_u16(vmovl_u8(a)); }
static inline uint8x16_t batch(const uint8_t *a, const uint8_t *b, int16_t fx, int16_t fy) {
    uint8x16_t tl = vld1q_u8(a), bl = vld1q_u8(b);
    int16x8_t l0 = lerp8(widen(vget_low_u8(tl)), widen(vget_low_u8(bl)), fy);
    int16x8_t l1 = lerp8(widen(vget_high_u8(tl)), widen(vget_high_u8(bl)), fy);
    if (!fx) return vcombine_u8(vmovn_u16(vreinterpretq_u16_s16(l0)), vmovn_u16(vreinterpretq_u16_s16(l1)));
    uint8x16_t tr = vld1q_u8(a + 4), br = vld1q_u8(b + 4);
    int16x8_t r0 = lerp8(widen(vget_low_u8(tr)), widen(vget_low_u8(br)), fy);
    int16x8_t r1 = lerp8(widen(vget_high_u8(tr)), widen(vget_high_u8(br)), fy);
    l0 = lerp8(l0, r0, fx); l1 = lerp8(l1, r1, fx);
    return vcombine_u8(vmovn_u16(vreinterpretq_u16_s16(l0)), vmovn_u16(vreinterpretq_u16_s16(l1)));
}
void hs_render(const hs_plan *p, uint32_t *out) {
    uint8_t *dst = (uint8_t *)(out + p->first);
    const uint8_t *a = p->top, *b = p->bottom;
    unsigned n = p->count;
    if (!p->fx && !p->fy) { memcpy(dst, a, (size_t)n * 4); return; }
    while (n >= 4) {
        vst1q_u8(dst, batch(a, b, p->fx, p->fy));
        dst += 16; a += 16; b += 16; n -= 4;
    }
    /* At most three pixels. Use the same intrinsics on a padded local batch so
     * there is no wide load past the last valid source pixel or destination. */
    if (n) {
        uint8_t ta[20] = {0}, tb[20] = {0}, tmp[16];
        memcpy(ta, a, (size_t)(n + 1) * 4); memcpy(tb, b, (size_t)(n + 1) * 4);
        vst1q_u8(tmp, batch(ta, tb, p->fx, p->fy));
        memcpy(dst, tmp, (size_t)n * 4);
    }
}
unsigned hs_try(const hs_data *d, unsigned n, uint32_t *out, unsigned arg, hs_original original) {
    hs_plan p;
    if (!original || hs_prepare(d, n, out, &p) != HS_OK) return 0;
    if (p.first) original(d, p.first, out, arg);
    hs_render(&p, out);
    unsigned tail = p.first + p.count;
    if (tail < n) {
        hs_data td = *d;
        td.x = (int32_t)((int64_t)d->x + (int64_t)tail * 65536);
        original(&td, n - tail, out + tail, arg);
    }
    return p.count;
}
int hs_selfcheck(hs_original original) {
    uint32_t pixels[32 * 3], want[32], got[32];
    for (unsigned i = 0; i < 96; ++i) pixels[i] = i * 0x9e3779b9u ^ (i << 24);
    hs_image im = {(const uint8_t *)pixels, 0, 128, 32, 3, (32 << 16)-1, (3 << 16)-1};
    hs_data d = {.image = &im, .dx = 65536};
    const int32_t xs[] = {32768, -32768, 32768 + 0x7f80, 32768 + 0xff80};
    const int32_t ys[] = {-1, 32768, 65536 + 12345, 4 * 65536};
    for (unsigned i = 0; i < 4; ++i) {
        d.x = xs[i]; d.y = ys[i];
        original(&d, 32, want, 0);
        if (!hs_try(&d, 32, got, 0, original) || memcmp(want, got, sizeof want)) return 0;
    }
    return 1;
}
int hs_projective_selfcheck(hs_original projective, hs_original axis) {
    uint32_t pixels[96], want[32], got[32];
    for (unsigned i = 0; i < 96; ++i) pixels[i] = i * 0x9e3779b9u ^ (i << 24);
    hs_image im = {(const uint8_t *)pixels, 0, 128, 32, 3, (32 << 16)-1, (3 << 16)-1};
    hs_projective_data pd = {.base={.image=&im,.dx=65536}};
    uint32_t q[4] = {0,0,0,0x3f800000}, dq[4] = {0};
    const void *qp=q, *dp=dq;
    memcpy((uint8_t *)&pd + 0x10, &qp, sizeof qp);
    memcpy((uint8_t *)&pd + 0x18, &dp, sizeof dp);
    for (unsigned i=0;i<4;++i) {
        pd.base.x = 32768 + (int32_t)i*128;
        pd.base.y = i ? 32768 + (int32_t)i*65536 : -65536;
        projective(&pd.base,32,want,0);
        if (!hs_projective_axes(&pd.base) || !hs_try(&pd.base,32,got,0,axis) || memcmp(want,got,sizeof want)) return 0;
    }
    return 1;
}
#endif
