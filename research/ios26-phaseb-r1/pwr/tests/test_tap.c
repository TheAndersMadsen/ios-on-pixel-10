/* Host test: the tap feedback policy (blazer_haptic_tap.h), the exact header the kernel includes.
 *   cc -std=c11 -fsanitize=address,undefined -I <xnu>/bsd/dev test_tap.c && ./a.out */
#include <assert.h>
#include <stdio.h>
#include "blazer_haptic_tap.h"

static int checks;
#define CHECK(c) do { checks++; if (!(c)) { printf("FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int
main(void)
{
	struct hh_tap t = { 0 };

	/* first tap at any time plays, even at t = 0 */
	CHECK(hh_tap_due(&t, 0) == 1);
	hh_tap_done(&t, 0, 0);
	CHECK(t.sent == 1 && t.played && !t.off);
	/* inside the gap: skipped; at the gap: plays */
	CHECK(hh_tap_due(&t, HH_TAP_GAP_MS - 1) == 0);
	CHECK(t.skipped == 1);
	CHECK(hh_tap_due(&t, HH_TAP_GAP_MS) == 1);
	hh_tap_done(&t, HH_TAP_GAP_MS, 0);
	CHECK(t.sent == 2);
	/* EBUSY: skipped, no time stamp, still on */
	CHECK(hh_tap_due(&t, 10000) == 1);
	hh_tap_done(&t, 10000, HH_TAP_EBUSY);
	CHECK(!t.off && t.sent == 2 && t.last_ms == HH_TAP_GAP_MS && t.skipped == 2);
	CHECK(hh_tap_due(&t, 10001) == 1);
	/* any other error ends tap feedback for the boot */
	int errs[] = { 5 /* EIO */, 6 /* ENXIO */, 22 /* EINVAL */, 45 /* ENOTSUP */, -1 };
	for (unsigned i = 0; i < sizeof(errs) / sizeof(errs[0]); i++) {
		struct hh_tap e = { 0 };
		CHECK(hh_tap_due(&e, 5) == 1);
		hh_tap_done(&e, 5, errs[i]);
		CHECK(e.off && e.refused == 1 && e.sent == 0 && e.last_rc == errs[i]);
		CHECK(hh_tap_due(&e, 100000) == 0);
	}
	/* budget: exactly HH_TAP_MAX effects, then off */
	struct hh_tap b = { 0 };
	uint64_t now = 0;
	unsigned played = 0;
	for (unsigned i = 0; i < 2 * HH_TAP_MAX; i++, now += HH_TAP_GAP_MS) {
		if (hh_tap_due(&b, now)) {
			hh_tap_done(&b, now, 0);
			played++;
		}
	}
	CHECK(played == HH_TAP_MAX && b.sent == HH_TAP_MAX && b.off);
	CHECK(b.skipped == HH_TAP_MAX);
	/* a burst of 100 requests 1 ms apart gives one effect per gap */
	struct hh_tap r = { 0 };
	played = 0;
	for (uint64_t ms = 1000; ms < 1000 + 100; ms++) {
		if (hh_tap_due(&r, ms)) {
			hh_tap_done(&r, ms, 0);
			played++;
		}
	}
	CHECK(played == 1);
	/* clock wrap is not expected (mach time is monotonic); a smaller now inside the gap must not play */
	CHECK(hh_tap_due(&r, 1000 + 10) == 0);
	printf("tap policy host test: %d checks, 0 failed\n", checks);
	return 0;
}
