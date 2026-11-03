/* ARM64 codegen check of the 0001 patch's sweet_bl_calibration() body against minimal stand-ins for the libkern/IOKit
 * calls it makes (same signatures as XNU's OSData::withBytes, OSDictionary::withCapacity/setObject, OSNumber::withNumber,
 * IORegistryEntry::setProperty, IOLog). Not the kernel build: proves the hunk is well-formed C++ that emits the calls. */
#include <stdint.h>
#include <stddef.h>
extern "C" void IOLog(const char *fmt, ...);
struct OSObject { void release() const; };
struct OSData : OSObject { static OSData *withBytes(const void *bytes, unsigned int numBytes); };
struct OSNumber : OSObject { static OSNumber *withNumber(unsigned long long value, unsigned int numberOfBits); };
struct OSDictionary : OSObject { static OSDictionary *withCapacity(unsigned int capacity); bool setObject(const char *aKey, const OSObject *anObject); };
struct IOService { bool setProperty(const char *aKey, OSObject *anObject); };
#include "hk_bright_calib.h"
#define static
/* extracted verbatim from 0001-hk-bright-backlight-calibration.patch */
static void
sweet_bl_calibration(IOService *bl, uint32_t cap)
{
	int32_t mt[HKB_MT_MAX], cb[HKB_CB_N];
	unsigned n = hkb_marketing_q16(cap, mt, HKB_MT_MAX);
	if (n < 2) {
		return;
	}
	hkb_calibration_q16(cap, mt, n, cb);
	OSData *table = OSData::withBytes(mt, n * sizeof(mt[0]));
	if (table) {
		bl->setProperty("backlight-marketing-table", table);
		table->release();
	}
	OSDictionary *d = OSDictionary::withCapacity(HKB_CB_N);
	for (unsigned i = 0; d && i < HKB_CB_N; i++) {
		OSNumber *v = OSNumber::withNumber((uint32_t)cb[i], 32);
		if (v) {
			d->setObject(hkb_calib_keys[i], v);
			v->release();
		}
	}
	if (d) {
		bl->setProperty("backlight-calibration-parameters", d);
		d->release();
	}
	IOLog("SWEET BL: calibration %u table entries, mid %d/65536 nits\n", n, cb[HKB_CB_LMIDPANEL]);
}
