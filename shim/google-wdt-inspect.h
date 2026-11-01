#pragma once
#include <stdint.h>

/* Google source, kernel_pixel_6.6 fac4effc829311dabd53d2d0e8cc3090318e6453:
 * private/google-modules/soc/rdo/watchdog/google_wdt_local.h.
 * These are NOT S3C2410 WTCON registers. Inspection must preserve the
 * firmware watchdog; no write callback exists in this interface. */
#define TGL_GOOGLE_WDT_ID_OFFSET 0x00U
#define TGL_GOOGLE_WDT_ID_VALUE 0x00574454U
#define TGL_GOOGLE_WDT_CONTROL_OFFSET 0x08U
#define TGL_GOOGLE_WDT_VALUE_OFFSET 0x0cU
#define TGL_GOOGLE_WDT_KEY_OFFSET 0x10U
#define TGL_GOOGLE_WDT_ENABLE 0x01U
#define TGL_GOOGLE_WDT_KEY_ENABLE 0x04U
#define TGL_GOOGLE_WDT_EXPIRY_ACTION 0x08U

struct tgl_wdt_snapshot {
	uint32_t id, control, value;
};

static inline int tgl_google_wdt_inspect(uintptr_t base,
    uint32_t (*read32)(uintptr_t), struct tgl_wdt_snapshot *out)
{
	out->id = read32(base + TGL_GOOGLE_WDT_ID_OFFSET);
	out->control = 0;
	out->value = 0;
	if (out->id != TGL_GOOGLE_WDT_ID_VALUE) return 0;
	out->control = read32(base + TGL_GOOGLE_WDT_CONTROL_OFFSET);
	out->value = read32(base + TGL_GOOGLE_WDT_VALUE_OFFSET);
	return 1;
}
