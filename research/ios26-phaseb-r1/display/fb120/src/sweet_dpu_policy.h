/*
 * hk_dpu=<bits>: one short boot arg for the native display path. No XNU types: host-tested (research/ios26-dpu-r1/tests/host_dpu_policy.c).
 * Off (no arg, or 0): nothing here runs and every existing gate behaves as before.
 *
 *   0x01 ZC     zero copy: CoreAnimation's framebuffer surfaces scan out from where it drew them (hk_fb_flip=1), only what it says changed is
 *               cleaned or copied (hk_fb_dirty=1), and a flip no longer marks the panel buffer wholly stale. Every 256th flip is cleaned whole.
 *   0x02 VRR    LTPO idle: after SWEET_DPU_IDLE_US with no swap and nothing in flight, the panel goes to 30 Hz by DCS; the next swap brings it
 *               back before its kick. A failed DCS ends VRR for the boot.
 *   0x04 R120   tell CoreAnimation 120 Hz (as hk_fb_refresh=120). Honoured with flips running or the fast copy (hk_fb_fast=1); otherwise 60, as sweet_fb_refresh_decide.
 *   0x08 PROBE  read-only: log the DPU's output timing, TE and DSC registers at attach, for a later partial-update patch.
 *   0x10 VRR10  idle rate 10 Hz instead of 30.
 */
#ifndef SWEET_DPU_POLICY_H
#define SWEET_DPU_POLICY_H
#include <stdint.h>
#include <stdbool.h>

#define HK_DPU_ZC       0x01u
#define HK_DPU_VRR      0x02u
#define HK_DPU_R120     0x04u
#define HK_DPU_PROBE    0x08u
#define HK_DPU_VRR10    0x10u
#define HK_DPU_KNOWN    0x1fu

#define SWEET_DPU_IDLE_US      1500000u /* no swap for this long: idle */
#define SWEET_DPU_FLIP_HEAL    256u     /* every Nth flip of a slot cleans all of it, whatever CA said */
#define SWEET_DPU_VRR_LOGS     16u

/* Unknown bits refuse the whole arg: a typo must not turn on something else. */
static inline uint32_t
sweet_dpu_bits(uint32_t asked)
{
	return (asked & ~HK_DPU_KNOWN) != 0 ? 0 : asked;
}

/* The rate hk_fb_refresh would have been given. An explicit hk_fb_refresh wins. */
static inline uint32_t
sweet_dpu_refresh_ask(uint32_t bits, bool have_explicit, uint32_t explicit_rate)
{
	if (have_explicit) return explicit_rate;
	return (bits & HK_DPU_R120) ? 120u : 0u;
}

/* The panel's rate when busy: hk_panel_hz if it set one, else 120 (phone-fast-r2: TE every 8290 us under ABL). */
static inline uint32_t
sweet_dpu_vrr_high(uint32_t panel_hz)
{
	return (panel_hz == 120 || panel_hz == 60) ? panel_hz : 120u;
}

static inline uint32_t
sweet_dpu_vrr_low(uint32_t bits)
{
	return (bits & HK_DPU_VRR10) ? 10u : 30u;
}

/* Under fLock: a taken frame may consume accumulators only if no newer swap
 * was queued. Otherwise clean/copy it whole and leave damage for the pending
 * frame. A swap during the actual clean accumulates after this check/clear. */
static inline bool
sweet_dpu_damage_can_consume(uint64_t taken, uint64_t queued)
{
	return taken == queued;
}

/* ---- flips: whole clean when the slot is fresh, when a swap said nothing, when dirty tracking is off, and every SWEET_DPU_FLIP_HEAL-th flip of the slot. */
static inline bool
sweet_dpu_flip_whole(bool dirty_mode, bool slot_whole, bool fresh, uint32_t *since_heal)
{
	if (!dirty_mode || slot_whole || fresh) {
		*since_heal = 0;
		return true;
	}
	if (++*since_heal >= SWEET_DPU_FLIP_HEAL) {
		*since_heal = 0;
		return true;
	}
	return false;
}

/* ---- VRR. One thread (the framebuffer's workloop) steps it; swap() only stamps the time, under the framebuffer lock. */
enum sweet_vrr_act { SWEET_VRR_NONE = 0, SWEET_VRR_GO_LOW, SWEET_VRR_GO_HIGH };

struct sweet_vrr {
	bool     on, low, dead;
	uint32_t high_hz, low_hz;
	uint64_t last_us;       /* last swap, or the last rate change */
	uint32_t lows, highs, fails;
};

static inline void
sweet_vrr_init(struct sweet_vrr *v, uint32_t bits, uint32_t panel_hz, uint64_t now_us)
{
	v->on = (bits & HK_DPU_VRR) != 0;
	v->low = v->dead = false;
	v->high_hz = sweet_dpu_vrr_high(panel_hz);
	v->low_hz = sweet_dpu_vrr_low(bits);
	v->last_us = now_us;
	v->lows = v->highs = v->fails = 0;
}

static inline void
sweet_vrr_swap(struct sweet_vrr *v, uint64_t now_us)
{
	v->last_us = now_us;
}

/*
 * What to do now. kicking: a frame is about to be kicked (so nothing is in flight). idle_ok: nothing in flight, nothing queued, nothing held.
 * display_off: backboardd turned the display off and its black frame has landed, so there's no need to wait out the idle time.
 * Never GO_LOW with a frame waiting, never kick at the low rate.
 */
static inline enum sweet_vrr_act
sweet_vrr_step(const struct sweet_vrr *v, uint64_t now_us, bool kicking, bool idle_ok, bool display_off)
{
	if (!v->on || v->dead) return SWEET_VRR_NONE;
	if (kicking) return v->low ? SWEET_VRR_GO_HIGH : SWEET_VRR_NONE;
	if (v->low || !idle_ok) return SWEET_VRR_NONE;
	if (display_off) return SWEET_VRR_GO_LOW;
	return now_us >= v->last_us && now_us - v->last_us >= SWEET_DPU_IDLE_US ? SWEET_VRR_GO_LOW : SWEET_VRR_NONE;
}

/* The rate the action sends. */
static inline uint32_t
sweet_vrr_hz(const struct sweet_vrr *v, enum sweet_vrr_act a)
{
	return a == SWEET_VRR_GO_LOW ? v->low_hz : a == SWEET_VRR_GO_HIGH ? v->high_hz : 0;
}

/*
 * After the DCS. rc 0: the panel was told. Otherwise VRR stops for the boot; after a failed GO_HIGH the panel may stay at the low rate, which only
 * delays frames: still correct.
 */
static inline void
sweet_vrr_done(struct sweet_vrr *v, enum sweet_vrr_act a, int rc, uint64_t now_us)
{
	if (a == SWEET_VRR_NONE) return;
	if (rc != 0) {
		v->fails++;
		v->dead = true;
		return;
	}
	if (now_us > v->last_us) v->last_us = now_us;     /* a swap stamped while the DCS went out stays */
	if (a == SWEET_VRR_GO_LOW) { v->low = true; v->lows++; }
	else { v->low = false; v->highs++; }
}

/* Paced timer: microseconds until the idle drop is due; 0 for no need to wake. At least 1000. */
static inline uint32_t
sweet_vrr_wake_us(const struct sweet_vrr *v, uint64_t now_us)
{
	if (!v->on || v->dead || v->low) return 0;
	uint64_t el = now_us >= v->last_us ? now_us - v->last_us : 0;
	if (el >= SWEET_DPU_IDLE_US) return 1000u;
	uint64_t left = SWEET_DPU_IDLE_US - el;
	return left < 1000u ? 1000u : (uint32_t)left;
}

/* TE period at a rate, us, for hk_fb_te=2's alignment after a change. 0: unknown. */
static inline uint32_t
sweet_dpu_period_us(uint32_t hz)
{
	return hz == 0 ? 0 : 1000000u / hz;
}
#endif
