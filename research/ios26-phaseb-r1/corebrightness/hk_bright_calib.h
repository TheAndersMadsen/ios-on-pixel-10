/*
 * hk_bright: the two AppleARMBacklight properties CoreBrightness needs before it builds its Display (no XNU types, host-tested).
 * iOS 26 dyld cache 0f1ee332, static: Display init (CoreBrightness __TEXT+0x164c1c) sends -[CBBacklightNode getBacklightCalibration:],
 * which reads "backlight-calibration-parameters" (a dictionary of 16.16 integers) with IORegistryEntrySearchCFProperty(IOService plane,
 * recursive|parents) from the matched backlight-control service. On NO it runs a fallback that interpolates the "backlight-marketing-table"
 * (CFData of int32 16.16 nits) before that table is loaded: ctx+0x48 is still NULL and backboardd faults at __TEXT+0x169924.
 * research/ios26-phaseb-r1/corebrightness/FINDINGS.md.
 * Values are a self-consistent model, not panel data: nits floor..cap on hk_bright_map.h's curve points, current linear in nits.
 */
#ifndef HK_BRIGHT_CALIB_H
#define HK_BRIGHT_CALIB_H
#include <stdint.h>
#include "hk_bright_map.h"

#define HKB_MT_MAX      (HKB_N + 2u)
#define HKB_IMAX_MA     20u     /* model current at cap, mA; only ratios matter to CoreBrightness's Lmin/Lmid/Lmax use */

/* backlight-marketing-table: ascending 16.16 nits, HKB_FLOOR_NITS, the curve points strictly between, cap. Returns the count (>= 2). */
static inline unsigned hkb_marketing_q16(uint32_t cap, int32_t *out, unsigned max)
{
	unsigned n = 0;
	if (max < 2 || cap <= HKB_FLOOR_NITS) return 0;
	out[n++] = (int32_t)(HKB_FLOOR_NITS << 16);
	for (unsigned i = 0; i < HKB_N && n < max - 1; i++) {
		if (hkb_curve[i].nits > HKB_FLOOR_NITS && hkb_curve[i].nits < cap) out[n++] = (int32_t)((uint32_t)hkb_curve[i].nits << 16);
	}
	out[n++] = (int32_t)(cap << 16);
	return n;
}

/* CoreBrightness's own lookup at x = 0.5 (index x * (n - 1), linear between neighbours), so Lmid equals what the fallback would derive. */
static inline int32_t hkb_marketing_mid_q16(const int32_t *t, unsigned n)
{
	unsigned i = (n - 1) / 2;
	if ((n - 1) % 2 == 0 || i + 1 >= n) return t[i];
	return (int32_t)(((int64_t)t[i] + t[i + 1]) / 2);
}

/* backlight-calibration-parameters, in the order -[CBBacklightNode getBacklightCalibration:] stores them (calib+0x00..0x20). */
enum { HKB_CB_IMAX, HKB_CB_IMID, HKB_CB_IHWMAX, HKB_CB_LMAXPROD, HKB_CB_LMIDPROD, HKB_CB_LMINPROD, HKB_CB_LMAXPANEL, HKB_CB_LMIDPANEL,
	HKB_CB_LMINPANEL, HKB_CB_N };
static const char *const hkb_calib_keys[HKB_CB_N] = {
	"current-for-max-backlight", "current-for-mid-backlight", "hardware-max-current-limit",
	"lMaxProduct", "lMidProduct", "lMinProduct", "lMaxPanel", "lMidPanel", "lMinPanel",
};

static inline void hkb_calibration_q16(uint32_t cap, const int32_t *t, unsigned n, int32_t out[HKB_CB_N])
{
	int32_t lmax = (int32_t)(cap << 16), lmin = t[0], lmid = hkb_marketing_mid_q16(t, n);
	int32_t imax = (int32_t)(HKB_IMAX_MA << 16);
	out[HKB_CB_IMAX] = imax;
	out[HKB_CB_IMID] = (int32_t)((int64_t)imax * lmid / lmax);
	out[HKB_CB_IHWMAX] = imax;
	out[HKB_CB_LMAXPROD] = out[HKB_CB_LMAXPANEL] = lmax;
	out[HKB_CB_LMIDPROD] = out[HKB_CB_LMIDPANEL] = lmid;
	out[HKB_CB_LMINPROD] = out[HKB_CB_LMINPANEL] = lmin;
}
#endif
