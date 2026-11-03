/*
 * hk_bright: nits to the panel's DBV, no XNU types, host-tested. Curve inferred by research/ios26-bright-r1: gamma 2.2 with 16383 = 2250 nits
 * fits the numbers panel-gs-bmea.c (MIT) states within 1%; no light was ever measured. HKB_MAX_CAP keeps every value in the driver's normal band and far from
 * limits.md's "860 nits under UI: never". Below HKB_ACL_DBV the driver turns ACL off (bmea_acl_modes_manager), so hk_bright does too, once.
 */
#ifndef HK_BRIGHT_MAP_H
#define HK_BRIGHT_MAP_H
#include <stdint.h>
#define HKB_MIN_CAP   10u
#define HKB_MAX_CAP   140u /* measured expansion gate pending; preserve shim cap */
#define HKB_FLOOR_NITS 10u      /* iOS writes 0 for display off, and a thermal pass may write 1: never unreadable */
#define HKB_ACL_DBV   3726u
#define HKB_PERIOD_US 16000u    /* CoreBrightness sends every 8 ms in a drag (dada's record); the panel needs no more */
static const struct { uint16_t nits, dbv; } hkb_curve[] = {
	{ 1, 491 }, { 2, 672 }, { 5, 1020 }, { 10, 1397 }, { 20, 1914 }, { 35, 2469 }, { 50, 2904 }, { 75, 3491 }, { 100, 3979 }, { 140, 4636 }, { 150, 4784 }, { 200, 5453 }, { 250, 6035 }, { 300, 6556 }, { 400, 7472 }, { 500, 8269 }, { 600, 8984 }
};
#define HKB_N (sizeof hkb_curve / sizeof hkb_curve[0])
static inline uint32_t hkb_cap_ok(uint32_t cap) { return cap >= HKB_MIN_CAP && cap <= HKB_MAX_CAP; }
/* 16.16 nits, clamped to floor and cap. cap must have passed hkb_cap_ok. */
static inline uint16_t hkb_dbv_q16(uint32_t q16, uint32_t cap)
{
	uint64_t lo = (uint64_t)HKB_FLOOR_NITS << 16, hi = (uint64_t)cap << 16, v = q16;
	if (v < lo) v = lo;
	if (v > hi) v = hi;
	for (unsigned i = 1; i < HKB_N; i++) {
		uint64_t a = (uint64_t)hkb_curve[i - 1].nits << 16, b = (uint64_t)hkb_curve[i].nits << 16;
		if (v <= b) return (uint16_t)(hkb_curve[i - 1].dbv + (v - a) * (uint32_t)(hkb_curve[i].dbv - hkb_curve[i - 1].dbv) / (b - a));
	}
	return hkb_curve[HKB_N - 1].dbv;
}
/* iOS's "brightness", 0..65536 of the range, when it sends no nits (dada's record on iOS 16). DBV is about perceptual, so linear in DBV. */
static inline uint16_t hkb_dbv_frac(uint32_t frac, uint32_t cap)
{
	uint32_t lo = hkb_dbv_q16(0, cap), hi = hkb_dbv_q16((uint32_t)cap << 16, cap);
	if (frac > 65536u) frac = 65536u;
	return (uint16_t)(lo + (uint64_t)(hi - lo) * frac / 65536u);
}
/* The policy, one writer: others only leave a target. */
struct hkb_state { uint32_t cap, target, sent, nits_seen; uint64_t last_us; int dead, acl_off; };
enum { HKB_RC_OK = 0, HKB_RC_BUSY = 1 };        /* TDPU_OK, TDPU_BUSY; anything else ends hk_bright for this boot */
static inline void hkb_nits(struct hkb_state *s, uint32_t q16)
{
	if (!s->cap || q16 == 0) return;        /* dada's record: this key can stay 0 for a whole boot, while "brightness" still speaks */
	__atomic_store_n(&s->nits_seen, 1, __ATOMIC_RELAXED);
	__atomic_store_n(&s->target, (uint32_t)hkb_dbv_q16(q16, s->cap), __ATOMIC_RELAXED);
}
static inline void hkb_frac(struct hkb_state *s, uint32_t frac)
{
	if (!s->cap || __atomic_load_n(&s->nits_seen, __ATOMIC_RELAXED)) return;
	__atomic_store_n(&s->target, (uint32_t)hkb_dbv_frac(frac, s->cap), __ATOMIC_RELAXED);
}
static inline uint32_t hkb_wait_us(struct hkb_state *s, uint64_t now)
{
	uint32_t t = __atomic_load_n(&s->target, __ATOMIC_RELAXED);
	if (s->dead || t == 0 || t == s->sent) return 0;
	if (s->last_us == 0 || now - s->last_us >= HKB_PERIOD_US) return 1;
	return (uint32_t)(HKB_PERIOD_US - (now - s->last_us));
}
/* 1: a result to log in *rc. 0: nothing happened. */
static inline int hkb_step(struct hkb_state *s, uint64_t now, int (*acl_off)(void), int (*dbv)(uint16_t), int *rc)
{
	uint32_t t = __atomic_load_n(&s->target, __ATOMIC_RELAXED);
	int e = HKB_RC_OK;
	if (s->dead || t == 0 || t == s->sent) return 0;
	if (s->last_us != 0 && now - s->last_us < HKB_PERIOD_US) return 0;
	if (t < HKB_ACL_DBV && !s->acl_off) {
		e = acl_off();
		if (e == HKB_RC_OK) s->acl_off = 1;
	}
	if (e == HKB_RC_OK) e = dbv((uint16_t)t);
	if (e == HKB_RC_BUSY) return 0;         /* a frame went in flight: next tick */
	s->last_us = now;
	if (e != HKB_RC_OK) s->dead = 1; else s->sent = t;
	*rc = e;
	return 1;
}
#endif
