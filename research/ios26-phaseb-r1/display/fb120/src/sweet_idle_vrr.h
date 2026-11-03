/* Native fixed-rate idle policy. Workloop owns actions; activity under fLock.
 * No hardware or XNU dependencies. hk_dpu bit 2 is the default-off gate.
 * Display power/AOD owns dark state: VRR sends no command while dark.
 */
#ifndef SWEET_IDLE_VRR_H
#define SWEET_IDLE_VRR_H
#include <stdint.h>
#include <stdbool.h>
#include "sweet_dpu_policy.h"
#define HK_VRR_IDLE_US 1500000u
#define HK_VRR_DWELL_US 1000000u
struct hk_vrr {
 bool on, low, dead, restore;
 uint32_t high_hz, low_hz, lows, highs, fails;
 uint64_t last_us, changed_us, epoch;
};
static inline void hk_vrr_init(struct hk_vrr *v, uint32_t bits, uint32_t hz, uint64_t now)
{
 *v = (struct hk_vrr){0};
 /* An explicit 10/30 or invalid busy rate cannot be silently overridden. */
 v->on = (bits & HK_DPU_VRR) && !(bits & ~HK_DPU_KNOWN) && (hz == 0 || hz == 60 || hz == 120);
 v->high_hz = hz == 60 ? 60 : 120;
 v->low_hz = (bits & HK_DPU_VRR10) ? 10 : 30;
 v->last_us = v->changed_us = now;
 v->restore = v->on; /* establish the busy rate; ABL state is not proof */
}
static inline void hk_vrr_activity(struct hk_vrr *v, uint64_t now)
{
 if (!v->on || v->dead) return;
 if (now > v->last_us) v->last_us = now;
 ++v->epoch;
 if (v->low) v->restore = true;
}
/* A queued frame prevents downshift even when pacing delays its kick. */
static inline enum sweet_vrr_act hk_vrr_step(const struct hk_vrr *v, uint64_t now,
 bool safe, bool queued, bool dark)
{
 if (!v->on || v->dead || !safe || dark) return SWEET_VRR_NONE;
 if (v->restore || (queued && v->low)) return SWEET_VRR_GO_HIGH;
 if (v->low || queued || now < v->last_us || now < v->changed_us) return SWEET_VRR_NONE;
 return now - v->last_us >= HK_VRR_IDLE_US && now - v->changed_us >= HK_VRR_DWELL_US ? SWEET_VRR_GO_LOW : SWEET_VRR_NONE;
}
static inline uint32_t hk_vrr_hz(const struct hk_vrr *v, enum sweet_vrr_act a)
{ return a == SWEET_VRR_GO_LOW ? v->low_hz : a == SWEET_VRR_GO_HIGH ? v->high_hz : 0; }
/* Failure is sticky, no retry storm; panel rate after a failed sequence is unknown.
 * Activity arriving during LOW is retained and restores on the next safe tick.
 */
static inline void hk_vrr_done(struct hk_vrr *v, enum sweet_vrr_act a, int rc, uint64_t now, uint64_t epoch)
{
 if (a == SWEET_VRR_NONE) return;
 if (rc) { v->dead = true; ++v->fails; return; }
 if (now > v->changed_us) v->changed_us = now;
 v->low = a == SWEET_VRR_GO_LOW;
 if (v->low) { ++v->lows; if (epoch != v->epoch) v->restore = true; }
 else { ++v->highs; if (epoch == v->epoch) v->restore = false; }
}
static inline uint32_t hk_vrr_wake_us(const struct hk_vrr *v, uint64_t now)
{
 if (!v->on || v->dead) return 0;
 if (v->restore) return 1000;
 if (v->low) return 0;
 uint64_t idle = now >= v->last_us ? now - v->last_us : 0;
 uint64_t dwell = now >= v->changed_us ? now - v->changed_us : 0;
 uint64_t a = idle < HK_VRR_IDLE_US ? HK_VRR_IDLE_US - idle : 0;
 uint64_t b = dwell < HK_VRR_DWELL_US ? HK_VRR_DWELL_US - dwell : 0;
 uint64_t left = a > b ? a : b;
 return left < 1000 ? 1000 : (uint32_t)left;
}
#endif
