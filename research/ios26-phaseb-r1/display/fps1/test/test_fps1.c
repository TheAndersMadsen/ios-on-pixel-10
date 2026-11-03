/* Host test for hk-fps1 (hk_fb_fast=2): sweet_fb_refresh.h gate, step and poll policy, rate counters, and a closed-loop TE timeline model.
 * cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../src test_fps1.c -o /tmp/test_fps1 && /tmp/test_fps1 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sweet_fb_refresh.h"

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #c); } } while (0)

/* ---- model. Physical numbers: TE 8291 us, transfer 5370 us from TE (phone-fast-r2), copy 1600-2100 us (A7 r3). 1 us steps, 10 s.
 * DPU: a kick waits for the next TE edge, the transfer ends 5370 us later. Kernel: one workloop; a tick at its timer; a copy occupies it.
 * Poll policy is the header's (fb120 for one buffer, dbuf for two), each wakeup 0..jitter late. CoreAnimation: renders R us (+-10 %), SwapEnd,
 * then coupled = polls SwapWait every ca_poll us until its swap is not Busy (queued or being copied) before the next render; open = renders on. */
static uint32_t lcg;
static uint32_t rnd(uint32_t n) { lcg = lcg * 1103515245u + 12345u; return n ? (lcg >> 8) % n : 0; }
struct res { double kicks, swaps, busy; };
/* coupled 2: as 1, and a render only starts on CoreAnimation's own 120 Hz heartbeat (8333 us grid), the other reading of QuartzCore's loop. */
static uint64_t render_from(int coupled, uint64_t t) { return coupled == 2 ? ((t + 8332) / 8333) * 8333 : t; }
static struct res model(int dbuf, uint32_t render_us, int coupled, uint32_t copy_us, uint32_t jitter, uint32_t ca_poll)
{
	const uint64_t te = 8291, xfer = 5370, span = 10000000;
	uint64_t t, kick_at = 0, done_at = 0, last_frame = 9000, timer = 1, copy_end = 0, render_end, ca_next = 0;
	bool inflight = false, dirty = false, staged = false, copying = false, copy_stage = false, waiting = false;
	uint32_t pending = 0, busy_id = 0, my_id = 0, cur_id = 0, kicks = 0, swaps = 0, busy = 0;
	lcg = 777u + render_us + (uint32_t)coupled * 13u + (uint32_t)dbuf * 7u;
	render_end = render_us;
	for (t = 1; t < span; t++) {
		/* producer */
		if (!waiting && t >= render_end) {
			my_id = ++cur_id; pending = my_id; dirty = true; swaps++;
			if (timer > t + 1) timer = t + 1;            /* swap(): setTimeoutUS(1) */
			if (coupled) { waiting = true; ca_next = t; }
			else render_end = t + render_us * 9 / 10 + rnd(render_us / 5 + 1);
		}
		if (waiting && t >= ca_next) {
			bool b = (dirty && pending == my_id) || (busy_id == my_id);
			if (b) { busy++; ca_next = t + ca_poll; }
			else { waiting = false; render_end = render_from(coupled, t) + render_us * 9 / 10 + rnd(render_us / 5 + 1); }
		}
		/* DPU */
		bool ready = !inflight || t >= done_at;
		/* a copy in progress */
		if (copying) {
			if (t < copy_end) continue;
			copying = false; busy_id = 0;
			if (!dbuf || !copy_stage) {                   /* one buffer, or copy into the idle one with nothing in flight: kick now */
				uint64_t k = t; kick_at = k; done_at = ((k + te - 1) / te) * te + xfer; inflight = true; kicks++; staged = false;
			} else {
				staged = true;
				if (ready) { if (inflight) { inflight = false; last_frame = t - kick_at; }
					kick_at = t; done_at = ((t + te - 1) / te) * te + xfer; inflight = true; kicks++; staged = false; }
			}
			timer = t + 1;
			continue;
		}
		if (t < timer) continue;
		if (inflight && t >= done_at) { inflight = false; last_frame = t - kick_at; }
		ready = !inflight;
		if (!dbuf) {
			if (ready && dirty) { dirty = false; busy_id = pending; copying = true; copy_stage = false; copy_end = t + copy_us; continue; }
		} else {
			enum sweet_fb_dbuf_act a = sweet_fb_dbuf_step(ready, dirty, staged);
			if (a == SWEET_FB_DBUF_KICK) { kick_at = t; done_at = ((t + te - 1) / te) * te + xfer; inflight = true; kicks++; staged = false; }
			else if (a == SWEET_FB_DBUF_COPY_KICK || a == SWEET_FB_DBUF_STAGE) {
				dirty = false; busy_id = pending; copying = true; copy_stage = a == SWEET_FB_DBUF_STAGE; copy_end = t + copy_us; continue;
			}
		}
		/* rearm (paceNextUS) */
		uint32_t next;
		if (inflight) {
			uint64_t el = t - kick_at;
			uint32_t left = el >= last_frame ? 1 : (uint32_t)(last_frame - el);
			next = dbuf ? sweet_fb_dbuf_poll_us(left, dirty, staged) : sweet_fb_pace_poll_us(left, 120, dirty);
		} else next = (dirty || staged) ? 1 : 0;
		timer = next ? t + next + rnd(jitter) : (uint64_t)-1;
	}
	struct res r = { kicks / 10.0, swaps / 10.0, busy / 10.0 };
	return r;
}

int main(void)
{
	/* gate */
	CHECK(sweet_fb_dbuf_refusal(2, 120, false, false, false, true) == 0);
	CHECK(sweet_fb_dbuf_refusal(1, 120, false, false, false, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(0, 120, false, false, false, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(3, 120, false, false, false, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(2, 60, false, false, false, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(2, 0, false, false, false, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(2, 120, true, false, false, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(2, 120, false, true, false, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(2, 120, false, false, true, true) != 0);
	CHECK(sweet_fb_dbuf_refusal(2, 120, false, false, false, false) != 0);
	for (uint32_t f = 0; f < 1000; f++) for (uint32_t r = 0; r < 200; r += 60)
		CHECK((sweet_fb_dbuf_refusal(f, r, false, false, false, true) == 0) == (f == 2 && r == 120));
	/* hk_fb_fast=2 still means the fast copy for the refresh decision (kernel passes sweet_fb_fast != 0) */
	for (uint32_t a = 0; a < 1000; a++) {
		CHECK(sweet_fb_refresh_decide(a, false, 2 != 0) == sweet_fb_refresh_decide(a, false, 1 == 1));
	}
	/* step: exhaustive */
	for (int r = 0; r < 2; r++) for (int d = 0; d < 2; d++) for (int s = 0; s < 2; s++) {
		enum sweet_fb_dbuf_act a = sweet_fb_dbuf_step(r, d, s);
		if (r) CHECK(a == (s ? SWEET_FB_DBUF_KICK : d ? SWEET_FB_DBUF_COPY_KICK : SWEET_FB_DBUF_NONE));
		else CHECK(a == ((d && !s) ? SWEET_FB_DBUF_STAGE : SWEET_FB_DBUF_NONE));
		CHECK(!(s && (a == SWEET_FB_DBUF_STAGE || a == SWEET_FB_DBUF_COPY_KICK)));   /* a staged frame is never overwritten */
		CHECK(!(!r && (a == SWEET_FB_DBUF_KICK || a == SWEET_FB_DBUF_COPY_KICK)));   /* never a kick with a frame in flight */
	}
	/* poll: a waiting unstaged frame is staged at once; otherwise never longer than fb120's waiting bound, never shorter than its minimum */
	for (uint32_t left = 1; left < 20000; left += 7) for (int d = 0; d < 2; d++) for (int s = 0; s < 2; s++) {
		uint32_t p = sweet_fb_dbuf_poll_us(left, d, s);
		if (d && !s) CHECK(p == 1);
		else if (d || s) CHECK(p >= SWEET_FB_POLL_WAITING_MIN_US && p <= SWEET_FB_POLL_WAITING_MAX_US);
		else CHECK(p == sweet_fb_pace_poll_us(left, 120, false));
	}
	/* rate counters clear */
	struct sweet_fb_rate rt; memset(&rt, 0xff, sizeof rt);
	sweet_fb_rate_clear(&rt, 5);
	CHECK(rt.busy == 0 && rt.staged == 0 && rt.swaps == 0 && rt.kicks == 0 && rt.since_us == 5);

	/* model */
	const uint32_t renders[] = { 4000, 6000, 8000, 10000, 12000, 15000, 20000, 25000, 35000 };
	printf("closed-loop model, kicks/s (swaps/s): TE %.1f Hz, copy 1800 us, jitter 300 us, CA SwapWait poll 1000 us\n", 1e6 / 8291.0);
	printf("render_us | coupled 1 buf | coupled 2 buf | heartbeat 1 buf | heartbeat 2 buf | open 1 buf | open 2 buf\n");
	for (unsigned i = 0; i < sizeof renders / sizeof renders[0]; i++) {
		struct res c1 = model(0, renders[i], 1, 1800, 300, 1000), c2 = model(1, renders[i], 1, 1800, 300, 1000);
		struct res h1 = model(0, renders[i], 2, 1800, 300, 1000), h2 = model(1, renders[i], 2, 1800, 300, 1000);
		struct res o1 = model(0, renders[i], 0, 1800, 300, 1000), o2 = model(1, renders[i], 0, 1800, 300, 1000);
		printf("%9u | %5.1f (%5.1f) | %5.1f (%5.1f) | %5.1f (%5.1f) | %5.1f (%5.1f) | %5.1f (%5.1f) | %5.1f (%5.1f)\n", renders[i], c1.kicks, c1.swaps,
		    c2.kicks, c2.swaps, h1.kicks, h1.swaps, h2.kicks, h2.swaps, o1.kicks, o1.swaps, o2.kicks, o2.swaps);
		CHECK(h2.kicks + 0.5 >= h1.kicks);
		CHECK(c2.kicks + 0.5 >= c1.kicks);           /* never worse */
		CHECK(o2.kicks + 0.5 >= o1.kicks);
		CHECK(c2.kicks <= 120.7 && o2.kicks <= 120.7);  /* one frame per TE at most */
		CHECK(c2.kicks <= c2.swaps + 0.2);              /* no frame shown twice */
	}
	/* the decisive cases */
	/* The decisive cases (what the model supports; the rest is equal within noise): frames that render in 6-8 ms. */
	struct res fast2 = model(1, 6000, 1, 1800, 300, 1000);
	CHECK(fast2.kicks > 120.0);                       /* a 6 ms producer, SwapWait-coupled: one frame on every TE */
	struct res e1 = model(0, 8000, 1, 1800, 300, 1000), e2 = model(1, 8000, 1, 1800, 300, 1000);
	CHECK(e2.kicks > e1.kicks + 15.0);                /* 8 ms: the copy no longer waits for FRM_DONE */
	struct res l1 = model(0, 6000, 1, 2100, 300, 1000), l2 = model(1, 6000, 1, 2100, 300, 1000);
	CHECK(l2.kicks > l1.kicks + 15.0);                /* a long copy (2.1 ms) no longer costs a TE */
	struct res hb1 = model(0, 8000, 2, 1800, 300, 1000), hb2 = model(1, 8000, 2, 1800, 300, 1000);
	CHECK(hb2.kicks >= hb1.kicks);
	for (uint32_t c = 1500; c <= 2100; c += 300) for (uint32_t j = 0; j <= 500; j += 250) {
		struct res a = model(0, 6000, 1, c, j, 1000), b = model(1, 6000, 1, c, j, 1000);
		printf("copy %u jitter %u: 1 buf %.1f, 2 buf %.1f\n", c, j, a.kicks, b.kicks);
		CHECK(b.kicks + 0.5 >= a.kicks);
	}
	printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
