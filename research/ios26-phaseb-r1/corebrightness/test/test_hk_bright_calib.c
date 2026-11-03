/* Host test for hk_bright_calib.h. Reproduces what CoreBrightness (cache 0f1ee332) does with the two properties:
 * loadIOFixedArray: int32 / 65536 (__TEXT+0xe4280), getBacklightCalibration: integerValue / 65536 per key (__TEXT+0x154760),
 * and the marketing-table lookup at __TEXT+0x169810 (index x * (n - 1), linear). */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "hk_bright_calib.h"

static float lut(const float *t, unsigned n, float x)
{
	float pos = x * (float)(n - 1);
	unsigned i = (unsigned)pos;
	if (i >= n - 1) return t[n - 1];
	return t[i] + (t[i + 1] - t[i]) * (pos - (float)i);
}

int main(void)
{
	for (uint32_t cap = HKB_MIN_CAP + 1; cap <= HKB_MAX_CAP; cap++) {
		int32_t mt[HKB_MT_MAX], cb[HKB_CB_N];
		unsigned n = hkb_marketing_q16(cap, mt, HKB_MT_MAX);
		assert(n >= 2 && n <= HKB_MT_MAX);
		float t[HKB_MT_MAX];
		for (unsigned i = 0; i < n; i++) {
			t[i] = (float)mt[i] / 65536.0f;
			if (i) assert(mt[i] > mt[i - 1]);
		}
		assert(t[0] == (float)HKB_FLOOR_NITS && t[n - 1] == (float)cap);
		hkb_calibration_q16(cap, mt, n, cb);
		float c[HKB_CB_N];
		for (unsigned i = 0; i < HKB_CB_N; i++) {
			assert(cb[i] > 0);
			c[i] = (float)cb[i] / 65536.0f;
		}
		/* the values the fallback would have taken from the table at 0, 0.5, 1 */
		assert(c[HKB_CB_LMINPANEL] == lut(t, n, 0.0f));
		assert(c[HKB_CB_LMAXPANEL] == lut(t, n, 1.0f));
		float mid = lut(t, n, 0.5f);
		assert(c[HKB_CB_LMIDPANEL] - mid < 0.001f && mid - c[HKB_CB_LMIDPANEL] < 0.001f);
		assert(c[HKB_CB_LMINPANEL] < c[HKB_CB_LMIDPANEL] && c[HKB_CB_LMIDPANEL] <= c[HKB_CB_LMAXPANEL]);
		assert(c[HKB_CB_IMID] < c[HKB_CB_IMAX] && c[HKB_CB_IMAX] <= c[HKB_CB_IHWMAX]);
		if (cap == 140) {
			printf("cap 140: table");
			for (unsigned i = 0; i < n; i++) printf(" %g", t[i]);
			printf("\ncap 140: calibration");
			for (unsigned i = 0; i < HKB_CB_N; i++) printf(" %s=%g (0x%x)", hkb_calib_keys[i], c[i], (unsigned)cb[i]);
			printf("\n");
		}
	}
	assert(hkb_marketing_q16(HKB_FLOOR_NITS, (int32_t[4]){0}, 4) == 0);
	printf("PASS caps %u..%u\n", HKB_MIN_CAP + 1, HKB_MAX_CAP);
	return 0;
}
