/* Own implementation; offsets derived from the local 23G90 QuartzCore leaf.
 * This ABI is private and must be fingerprinted before use. */
#ifndef HSAMPLER_H
#define HSAMPLER_H
#include <stddef.h>
#include <stdint.h>
#ifndef HK_SAMPLER_NEON
#define HK_SAMPLER_NEON 0
#endif
typedef struct {
    const uint8_t *pixels;                    /* 0x00 */
    uint64_t unused08;
    int64_t stride;                           /* 0x10 */
    uint32_t width, height;                   /* 0x18 */
    int32_t xmax, ymax;                       /* 0x20: (dimension << 16)-1 */
} hs_image;
typedef struct {
    const hs_image *image;                    /* 0x00 */
    uint8_t unused08[0x2c];
    int32_t x, dx, y;                         /* 0x34, 0x38, 0x3c */
} hs_data;
typedef void (*hs_original)(const hs_data *, unsigned, uint32_t *, unsigned);
typedef struct { hs_data base; int32_t dy; } hs_projective_data;
_Static_assert(offsetof(hs_image, xmax) == 0x20, "image ABI");
_Static_assert(offsetof(hs_data, x) == 0x34 && sizeof(hs_data) == 0x40, "data ABI");
enum hs_reason { HS_OK, HS_TRANSFORM, HS_LAYOUT, HS_SPAN, HS_ALIAS, HS_REASON_COUNT };
typedef struct {
    const uint8_t *top, *bottom;
    unsigned first, count;
    int16_t fx, fy;
} hs_plan;
#if HK_SAMPLER_NEON
enum hs_reason hs_prepare(const hs_data *, unsigned, uint32_t *, hs_plan *);
/* Specialize the projective sampler only for exactly representable identity W. */
int hs_projective_axes(const hs_data *);
void hs_render(const hs_plan *, uint32_t *);
/* Full call: original on borders, NEON on interior. No writes when refused. */
unsigned hs_try(const hs_data *, unsigned, uint32_t *, unsigned, hs_original);
int hs_selfcheck(hs_original);
int hs_projective_selfcheck(hs_original, hs_original);
#endif
#endif
