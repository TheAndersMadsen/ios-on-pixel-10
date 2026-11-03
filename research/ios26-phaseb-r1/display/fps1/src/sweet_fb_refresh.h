/*
 * hk_fb_refresh=60|120|121|122: the rate CoreAnimation is told, and the numbers to see what it does with it. No XNU types: host-tested. research/ios26-fps-r1/FINDINGS.md.
 * QuartzCore 23G90 (static): AppleDisplay::update_display_limits reads dict IOMFBDisplayRefresh, key displayMinRefreshInterval, as 2^-32 s;
 * without it heartbeat_rate is the literal 1/60. phone-fast-r2 (physical): a transfer starts at TE and takes 5370 us of 8291, so 2.9 ms is free per TE. A copy into the
 * buffer being sent can't overlap the transfer. It took about 5 ms then; with hk_fb_fast=1 it takes ~1.6 ms (r3), which fits the 2.9 ms, so 120 also runs by copy.
 */
#ifndef SWEET_FB_REFRESH_H
#define SWEET_FB_REFRESH_H
#include <stdint.h>
#include <stdbool.h>
#include "sweet_fb_dirty.h"
#include "sweet_dpu_policy.h"

#define SWEET_FB_RATE_EVERY_US 5000000u

/*
 * hk_fb_refresh=60|120|121|122. 121/122: 120 Hz busy plus the LTPO idle drop (hk_dpu VRR, idle 30 or 10 Hz), in the same token: no extra boot-arg bytes.
 * 0: off. Otherwise what will run: 120 needs flip or the fast copy, and falls to 60 without.
 * Fast copy (hk_fb_fast=1, physical r3: 1.5-2.1 ms for the whole 11.3 MB canvas) fits in what a TE leaves free after the transfer (8291 - 5370 us = 2.9 ms),
 * so a frame that is waiting when FRM_DONE lands is copied and kicked before the next TE.
 */
static inline bool
sweet_fb_refresh_is_120(uint32_t asked)
{
	return asked == 120 || asked == 121 || asked == 122;
}

static inline uint32_t
sweet_fb_refresh_decide(uint32_t asked, bool flip, bool fast_copy)
{
	if (asked == 60) return 60;
	if (sweet_fb_refresh_is_120(asked)) return (flip || fast_copy) ? 120 : 60;
	return 0;
}

/* The hk_dpu VRR bits that 121/122 stand for, only when 120 runs. hk_dpu's own bits still count. */
static inline uint32_t
sweet_fb_refresh_vrr_bits(uint32_t asked, uint32_t running)
{
	if (running != 120) return 0;
	if (asked == 121) return HK_DPU_VRR;
	if (asked == 122) return HK_DPU_VRR | HK_DPU_VRR10;
	return 0;
}

/* VRR sends DCS between frames, so it needs the completion quarantine (hk_fb_fence=1); 121/122 imply it. */
static inline bool
sweet_fb_refresh_wants_fence(uint32_t asked)
{
	return asked == 121 || asked == 122;
}

/* The nominal rate: UIScreen rounds 1/interval, and TE's real 120.6 Hz would read 121. Each frame still starts on TE, in hardware. 0: publish nothing, CA's own 1/60 stands. */
static inline uint32_t
sweet_fb_refresh_ticks(uint32_t running)
{
	return running == 120 ? (uint32_t)((1ULL << 32) / 120) : 0;
}

/* For a client that does ask for vsync notifications. */
static inline uint32_t
sweet_fb_refresh_tick_us(uint32_t running, uint32_t off_us)
{
	return running == 120 ? 8333u : off_us;
}

/*
 * When to look for FRM_DONE. Off: when the last frame took that long, at least 1 ms. On, that guess is wrong by up to a TE period, because a frame's wait for TE
 * depends on when it was kicked, and sleeping past FRM_DONE loses a TE. So never sleep over the poll's bound.
 * 120 with a frame waiting: every 250-500 us, so detection (<= 0.5 ms) + fast copy (~1.6 ms) still lands before the next TE (2.9 ms free).
 */
#define SWEET_FB_POLL_WAITING_MIN_US 250u
#define SWEET_FB_POLL_WAITING_MAX_US 500u
static inline uint32_t
sweet_fb_pace_poll_us(uint32_t left, uint32_t running, bool waiting)
{
	if (running == 120 && waiting) {
		if (left < SWEET_FB_POLL_WAITING_MIN_US) return SWEET_FB_POLL_WAITING_MIN_US;
		return left > SWEET_FB_POLL_WAITING_MAX_US ? SWEET_FB_POLL_WAITING_MAX_US : left;
	}
	uint32_t bound = running == 120 ? 1000u : 2000u;
	if (left < 1000u) return 1000u;
	if (running != 0 && left > bound) return bound;
	return left;
}

/* One line every 5 s with swaps in it: what CA sent, what reached the DPU, and where it changed.
 * busy: SwapWait answers of Busy (CoreAnimation held back by the kernel). staged: frames copied while the previous one was still being sent (hk_fb_fast=2). */
struct sweet_fb_rate {
	uint64_t since_us, last_us;
	uint32_t swaps, kicks, unsaid, max_gap_us;
	uint32_t busy, staged;
	struct sweet_fb_rect changed;
};

/* Lock held. True: copy it out, log it, and call sweet_fb_rate_clear. */
static inline bool
sweet_fb_rate_swap(struct sweet_fb_rate *r, uint64_t now_us, const struct sweet_fb_rect *changed)
{
	if (r->since_us == 0) r->since_us = now_us;
	if (r->last_us != 0 && now_us > r->last_us && now_us - r->last_us > r->max_gap_us) {
		uint64_t gap = now_us - r->last_us;
		r->max_gap_us = gap > UINT32_MAX ? UINT32_MAX : (uint32_t)gap;
	}
	r->last_us = now_us;
	r->swaps++;
	if (changed != 0) sweet_fb_rect_union(&r->changed, changed);
	else r->unsaid++;
	return now_us >= r->since_us && now_us - r->since_us >= SWEET_FB_RATE_EVERY_US;
}

static inline void
sweet_fb_rate_clear(struct sweet_fb_rate *r, uint64_t now_us)
{
	r->since_us = now_us;
	r->swaps = r->kicks = r->unsaid = r->max_gap_us = 0;
	r->busy = r->staged = 0;
	r->changed.x = r->changed.y = r->changed.w = r->changed.h = 0;
}

/* Frames per second times ten. */
static inline uint32_t
sweet_fb_rate_dfps(uint32_t n, uint64_t span_us)
{
	return span_us == 0 ? 0 : (uint32_t)((uint64_t)n * 10000000ULL / span_us);
}
/*
 * hk_fb_fast=2: the fast copy (as 1) plus a second panel buffer. A copy can't go into the buffer being sent, so with one buffer every frame waits for
 * FRM_DONE before its 1.6-2.1 ms copy, and SwapWait holds CoreAnimation all that time (physical fb120: kicks <= 65/s while swaps reached 69.5/s, then
 * ~25/s for whole-canvas motion). With two, the next frame is copied into the idle buffer while the last one is sent, and FRM_DONE only kicks it.
 * Only with 120 by copy: not with flip (the pool's first slot is the second buffer), dirty copy (one damage history), or VRR (DCS only with nothing in flight).
 */
#define SWEET_FB_FAST_DBUF 2u
static inline const char *
sweet_fb_dbuf_refusal(uint32_t fast, uint32_t running, bool flip, bool dirty, bool vrr, bool scanout)
{
	if (fast != SWEET_FB_FAST_DBUF) return "not asked";
	if (running != 120) return "refresh not 120";
	if (flip) return "flip on";
	if (dirty) return "dirty copy on";
	if (vrr) return "vrr on";
	if (!scanout) return "no scaled scanout";
	return 0;
}

/* What the workloop does on a tick. Frames go out in order: a frame already staged is never replaced, so none is copied and then dropped. */
enum sweet_fb_dbuf_act {
	SWEET_FB_DBUF_NONE = 0,
	SWEET_FB_DBUF_KICK,         /* the staged frame goes out now */
	SWEET_FB_DBUF_COPY_KICK,    /* nothing in flight, nothing staged: copy into the idle buffer and kick it */
	SWEET_FB_DBUF_STAGE,        /* a frame is in flight: copy the waiting one into the idle buffer */
};
static inline enum sweet_fb_dbuf_act
sweet_fb_dbuf_step(bool ready, bool dirty, bool staged)
{
	if (ready) return staged ? SWEET_FB_DBUF_KICK : dirty ? SWEET_FB_DBUF_COPY_KICK : SWEET_FB_DBUF_NONE;
	return dirty && !staged ? SWEET_FB_DBUF_STAGE : SWEET_FB_DBUF_NONE;
}

/* paceNextUS with a frame in flight: stage a waiting frame at once, else poll for FRM_DONE as 120 by copy does (a staged frame counts as waiting). */
static inline uint32_t
sweet_fb_dbuf_poll_us(uint32_t left, bool dirty, bool staged)
{
	if (dirty && !staged) return 1;
	return sweet_fb_pace_poll_us(left, 120, dirty || staged);
}
#endif
