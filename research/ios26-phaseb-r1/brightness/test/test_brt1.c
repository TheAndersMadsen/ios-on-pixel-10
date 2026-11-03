/* Host test for brt1's hk_bright_map.h additions and the cap invariant. clang -std=c11 -Wall -Wextra -Werror -I../ref test_brt1.c */
#include <stdio.h>
#include <stdlib.h>
#include "hk_bright_map.h"
static int fails, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)
static uint32_t max_dbv, ndbv, nacl;
static int fake_dbv(uint16_t v) { if (v > max_dbv) max_dbv = v; ndbv++; return v > 13418u ? -1 : 0; }
static int fake_acl(void) { nacl++; return 0; }
int main(void)
{
	const uint32_t cap = 140, top = hkb_dbv_q16(cap << 16, cap);
	/* 1. Cap: no request of any 32-bit value yields a DBV above the 140-nit level, through the real hkb_nits/hkb_step. */
	struct hkb_state s = { .cap = cap };
	uint64_t now = 1;
	for (uint64_t q = 1; q <= INT32_MAX; q += 9973) {
		hkb_nits(&s, (uint32_t)q);
		now += HKB_PERIOD_US;
		int rc; hkb_step(&s, now, fake_acl, fake_dbv, &rc);
	}
	hkb_nits(&s, INT32_MAX); now += HKB_PERIOD_US; { int rc; hkb_step(&s, now, fake_acl, fake_dbv, &rc); }
	CHECK(top == 4636, "top dbv %u", top);
	CHECK(max_dbv <= top, "max dbv %u > %u", max_dbv, top);
	CHECK(!s.dead, "dead");
	/* 2. The 16.16 properties: cap << 16 is cap nits for loadFixedFloat (int / 65536). */
	CHECK(((cap << 16) / 65536.0) == 140.0, "q16");
	CHECK((uint64_t)cap << 16 <= INT32_MAX, "fits signed32");
	/* 3. hkb_dbv_nits_x10 inverts hkb_dbv_q16 to 0.2 nit on 10..140. */
	for (uint32_t n = HKB_FLOOR_NITS; n <= cap; n++) {
		uint32_t d = hkb_dbv_q16(n << 16, cap), x = hkb_dbv_nits_x10(d);
		CHECK(x + 2 >= n * 10 && x <= n * 10 + 2, "nits %u dbv %u -> %u/10", n, d, x);
	}
	CHECK(hkb_dbv_nits_x10(0) == 10 && hkb_dbv_nits_x10(65535) == 6000, "ends");
	for (uint32_t d = 1; d < 9000; d++) CHECK(hkb_dbv_nits_x10(d) >= hkb_dbv_nits_x10(d - 1), "monotone at %u", d);
	/* 4. Log policy on a boot ramp (CoreBrightness's 140 -> 131 nits, as r4-bl..r9) then two slider sweeps. */
	uint32_t logs = 0, last = 0, lines_ramp = 0, lines_sweep = 0, extremes = 0;
	struct hkb_state t = { .cap = cap }; now = 1;
	#define SEND(q) do { hkb_nits(&t, (q)); now += HKB_PERIOD_US; int rc_ = 0; \
		if (hkb_step(&t, now, fake_acl, fake_dbv, &rc_) && hkb_log_due(logs, last, t.sent, rc_)) { logs++; last = t.sent; *ctr += 1; } } while (0)
	uint32_t *ctr = &lines_ramp;
	for (uint32_t q = 140u << 16; q > (131u << 16); q -= 2000) SEND(q);
	CHECK(lines_ramp == HKB_LOG_FIRST || logs < HKB_LOG_FIRST, "ramp lines %u", lines_ramp);
	ctr = &lines_sweep;
	for (int k = 0; k < 2; k++) {
		for (uint32_t n = 1400; n >= 100; n -= 3) SEND((n << 16) / 10);          /* 140 -> 10 nits */
		if (last < t.sent + HKB_LOG_STEP) extremes++; else printf("down end: last %u sent %u\n", last, t.sent);
		for (uint32_t n = 100; n <= 1400; n += 3) SEND((n << 16) / 10);          /* 10 -> 140 nits */
		if (last + HKB_LOG_STEP > t.sent) extremes++; else printf("up end: last %u sent %u\n", last, t.sent);
	}
	CHECK(lines_sweep >= 80 && lines_sweep <= 110, "sweep lines %u", lines_sweep);
	CHECK(extremes == 4, "sweep ends logged within one step: %u", extremes);
	CHECK(hkb_log_due(HKB_LOG_MAX, 0, 9999, 0) == 0 && hkb_log_due(HKB_LOG_MAX, 0, 0, -1) == 1, "max and failure");
	CHECK(hkb_log_due(HKB_LOG_FIRST, 4000, 4000 + HKB_LOG_STEP - 1, 0) == 0 && hkb_log_due(HKB_LOG_FIRST, 4000, 4000 - HKB_LOG_STEP, 0) == 1, "step");
	/* 5. ACL off once, on the first send below HKB_ACL_DBV (the sweep goes below 3726). */
	CHECK(t.acl_off == 1, "acl_off");
	printf("brt1 host test: %d checks, %d failed (sweep %u lines, ramp %u, max dbv %u)\n", checks, fails, lines_sweep, lines_ramp, max_dbv);
	return fails != 0;
}
