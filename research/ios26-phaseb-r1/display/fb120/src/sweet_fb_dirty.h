/* CoreAnimation's dirty rectangle and the sums on it. No XNU types: host-tested. research/ios26-render-r1/FINDINGS.md. */
#ifndef SWEET_FB_DIRTY_H
#define SWEET_FB_DIRTY_H
#include <stdint.h>
#include <stdbool.h>
#include <string.h>

/* IOMobileFramebufferSwapDirtyRegion, 23G90 (static): client +0x2b0 x, y, w, h as int32, +0x2e4 a set flag. SwapEnd sends client +0x18. */
#define SWEET_FB_IN_DIRTY_RECT 0x298u
#define SWEET_FB_IN_DIRTY_FLAG 0x2ccu

struct sweet_fb_rect { int32_t x, y, w, h; };

static inline bool
sweet_fb_rect_empty(const struct sweet_fb_rect *r)
{
	return r->w <= 0 || r->h <= 0;
}

static inline void
sweet_fb_rect_union(struct sweet_fb_rect *a, const struct sweet_fb_rect *b)
{
	if (sweet_fb_rect_empty(b)) return;
	if (sweet_fb_rect_empty(a)) { *a = *b; return; }
	int64_t x0 = a->x < b->x ? a->x : b->x, y0 = a->y < b->y ? a->y : b->y;
	int64_t x1 = (int64_t)a->x + a->w > (int64_t)b->x + b->w ? (int64_t)a->x + a->w : (int64_t)b->x + b->w;
	int64_t y1 = (int64_t)a->y + a->h > (int64_t)b->y + b->h ? (int64_t)a->y + a->h : (int64_t)b->y + b->h;
	a->x = (int32_t)x0; a->y = (int32_t)y0; a->w = (int32_t)(x1 - x0); a->h = (int32_t)(y1 - y0);
}

/* Inside 0,0,w,h. False if nothing is left. */
static inline bool
sweet_fb_rect_clip(struct sweet_fb_rect *r, int32_t w, int32_t h)
{
	int64_t x0 = r->x, y0 = r->y, x1 = x0 + r->w, y1 = y0 + r->h;
	if (sweet_fb_rect_empty(r)) { r->w = r->h = 0; return false; }
	if (x0 < 0) x0 = 0;
	if (y0 < 0) y0 = 0;
	if (x1 > w) x1 = w;
	if (y1 > h) y1 = h;
	if (x1 <= x0 || y1 <= y0) { r->w = r->h = 0; return false; }
	r->x = (int32_t)x0; r->y = (int32_t)y0; r->w = (int32_t)(x1 - x0); r->h = (int32_t)(y1 - y0);
	return true;
}

/* From a SwapEnd record. False: this swap said nothing, so treat the whole surface as changed. */
static inline bool
sweet_fb_swap_dirty(const uint8_t *in, uint32_t in_size, struct sweet_fb_rect *out)
{
	if (in_size < SWEET_FB_IN_DIRTY_FLAG + 1 || in[SWEET_FB_IN_DIRTY_FLAG] == 0) return false;
	memcpy(out, in + SWEET_FB_IN_DIRTY_RECT, sizeof(*out));
	return !sweet_fb_rect_empty(out);
}

#endif
