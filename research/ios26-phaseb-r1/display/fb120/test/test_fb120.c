/* Host test for hk-fb120: sweet_fb_refresh.h decisions, VRR bits, poll bounds, and a TE timeline model.
 * cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I../src test_fb120.c -o /tmp/test_fb120 && /tmp/test_fb120 */
#include <stdio.h>
#include <stdlib.h>
#include "sweet_fb_refresh.h"
#include "sweet_idle_vrr.h"

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #c); } } while (0)

/* Old policy (hk-int1), for the model's comparison. */
static uint32_t old_decide(uint32_t a, bool flip) { if (a == 60) return 60; if (a == 120) return flip ? 120 : 60; return 0; }
static uint32_t old_poll(uint32_t left, uint32_t running)
{ uint32_t b = running == 120 ? 1000u : 2000u; if (left < 1000u) return 1000u; if (running != 0 && left > b) return b; return left; }

/*
 * Model (physical numbers): TE every 8291 us, transfer 5370 us from TE, copy copy_us, producer always has a frame waiting.
 * Kick at k: transfer starts at the first TE >= k and ends 5370 us later. The timer polls per the policy, each wakeup 0-jitter_us late
 * (LCG, fixed seed). On done: copy, then kick. Returns kicks per second over 10 s. Kernel side only: what CA sends is not modelled.
 */
static uint32_t lcg = 12345u;
static uint32_t rnd(uint32_t n) { lcg = lcg * 1103515245u + 12345u; return n ? (lcg >> 8) % n : 0; }
static double model(int newpol, uint32_t running, uint32_t copy_us, uint32_t jitter_us)
{
	const uint64_t te = 8291, xfer = 5370, span = 10000000;
	uint64_t t = 0, kicks = 0, last_frame = 9000;
	lcg = 12345u;
	while (t < span) {
		uint64_t kick = t;
		uint64_t start = ((kick + te - 1) / te) * te, done = start + xfer;
		kicks++;
		uint64_t now = kick;
		for (;;) {
			uint64_t el = now - kick;
			uint32_t left = el >= last_frame ? 1 : (uint32_t)(last_frame - el);
			uint32_t d = newpol ? sweet_fb_pace_poll_us(left, running, true) : old_poll(left, running);
			now += d + rnd(jitter_us);
			if (now >= done) break;
		}
		last_frame = done - kick;
		t = now + copy_us;
	}
	return kicks * 1e6 / (double)span;
}

/* Worst case: done is seen at most one poll bound (+ jitter) late; the next kick must be in before the next TE. */
static bool fits_one_te(uint32_t poll_bound_us, uint32_t jitter_us, uint32_t copy_us)
{
	return 5370u + poll_bound_us + jitter_us + copy_us < 8291u;
}

int main(void)
{
	/* decide */
	CHECK(sweet_fb_refresh_decide(60, false, false) == 60);
	CHECK(sweet_fb_refresh_decide(60, true, true) == 60);
	CHECK(sweet_fb_refresh_decide(120, false, false) == 60);
	CHECK(sweet_fb_refresh_decide(120, true, false) == 120);
	CHECK(sweet_fb_refresh_decide(120, false, true) == 120);
	CHECK(sweet_fb_refresh_decide(121, false, true) == 120);
	CHECK(sweet_fb_refresh_decide(122, false, true) == 120);
	CHECK(sweet_fb_refresh_decide(121, false, false) == 60);
	for (uint32_t a = 0; a < 1000; a++) {
		uint32_t r = sweet_fb_refresh_decide(a, false, true);
		CHECK(r == 0 || r == 60 || r == 120);
		if (a != 60 && a != 120 && a != 121 && a != 122) CHECK(r == 0);
		/* Old answers unchanged wherever the fast copy is off. */
		CHECK(sweet_fb_refresh_decide(a, false, false) == (a == 121 || a == 122 ? 60u : old_decide(a, false)));
		CHECK(sweet_fb_refresh_decide(a, true, false) == (a == 121 || a == 122 ? 120u : old_decide(a, true)));
	}
	CHECK(sweet_fb_refresh_ticks(120) == (uint32_t)((1ULL << 32) / 120));
	CHECK(sweet_fb_refresh_ticks(60) == 0);

	/* VRR bits */
	CHECK(sweet_fb_refresh_vrr_bits(120, 120) == 0);
	CHECK(sweet_fb_refresh_vrr_bits(121, 120) == HK_DPU_VRR);
	CHECK(sweet_fb_refresh_vrr_bits(122, 120) == (HK_DPU_VRR | HK_DPU_VRR10));
	CHECK(sweet_fb_refresh_vrr_bits(121, 60) == 0);
	CHECK(sweet_fb_refresh_vrr_bits(60, 60) == 0);
	CHECK(sweet_fb_refresh_wants_fence(121) && sweet_fb_refresh_wants_fence(122));
	CHECK(!sweet_fb_refresh_wants_fence(120) && !sweet_fb_refresh_wants_fence(60) && !sweet_fb_refresh_wants_fence(0));
	{
		struct hk_vrr v;
		hk_vrr_init(&v, 0 | sweet_fb_refresh_vrr_bits(121, 120), 0, 1000);
		CHECK(v.on && v.high_hz == 120 && v.low_hz == 30);
		hk_vrr_init(&v, 0 | sweet_fb_refresh_vrr_bits(122, 120), 0, 1000);
		CHECK(v.on && v.high_hz == 120 && v.low_hz == 10);
		hk_vrr_init(&v, 0 | sweet_fb_refresh_vrr_bits(120, 120), 0, 1000);
		CHECK(!v.on);
		/* idle -> low after 1.5 s, swap -> high */
		hk_vrr_init(&v, HK_DPU_VRR, 0, 0);
		CHECK(hk_vrr_step(&v, 10, true, false, false) == SWEET_VRR_GO_HIGH);   /* restore first */
		hk_vrr_done(&v, SWEET_VRR_GO_HIGH, 0, 10, v.epoch);
		CHECK(hk_vrr_step(&v, HK_VRR_IDLE_US + 20, true, false, false) == SWEET_VRR_GO_LOW);
		hk_vrr_done(&v, SWEET_VRR_GO_LOW, 0, HK_VRR_IDLE_US + 20, v.epoch);
		CHECK(hk_vrr_hz(&v, SWEET_VRR_GO_LOW) == 30);
		hk_vrr_activity(&v, HK_VRR_IDLE_US + 100);
		CHECK(hk_vrr_step(&v, HK_VRR_IDLE_US + 101, true, true, false) == SWEET_VRR_GO_HIGH);
	}

	/* poll bounds */
	for (uint32_t left = 0; left < 20000; left += 7) {
		uint32_t w = sweet_fb_pace_poll_us(left, 120, true);
		CHECK(w >= SWEET_FB_POLL_WAITING_MIN_US && w <= SWEET_FB_POLL_WAITING_MAX_US);
		CHECK(sweet_fb_pace_poll_us(left, 120, false) == old_poll(left, 120));
		CHECK(sweet_fb_pace_poll_us(left, 60, true) == old_poll(left, 60));
		CHECK(sweet_fb_pace_poll_us(left, 60, false) == old_poll(left, 60));
		CHECK(sweet_fb_pace_poll_us(left, 0, true) == old_poll(left, 0));
	}

	/* model */
	printf("model kicks/s (TE %.1f Hz), jitter 0/200/500 us:\n", 1e6 / 8291.0);
	const uint32_t copies[] = { 1600, 2100, 2500 };
	for (unsigned i = 0; i < 3; i++) {
		printf("  copy %u us: int1 running 60 %.1f %.1f %.1f | fb120 running 120 %.1f %.1f %.1f\n", copies[i],
		    model(0, 60, copies[i], 0), model(0, 60, copies[i], 200), model(0, 60, copies[i], 500),
		    model(1, 120, copies[i], 0), model(1, 120, copies[i], 200), model(1, 120, copies[i], 500));
	}
	CHECK(model(1, 120, 1600, 200) > 110.0);
	CHECK(model(1, 120, 1600, 200) >= model(0, 60, 1600, 200));
	CHECK(model(1, 120, 2100, 500) > model(0, 60, 2100, 500) + 20.0);  /* margin where copies run long or wakeups are late */
	CHECK(fits_one_te(SWEET_FB_POLL_WAITING_MAX_US, 200, 2100));     /* r3's worst measured copy 2.07 ms */
	CHECK(!fits_one_te(2000, 0, 1600));                               /* int1's 60 bound: not in one TE */
	printf("%s: %d checks, %d failures\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
