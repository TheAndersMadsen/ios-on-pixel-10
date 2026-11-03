/* Volume and power keys for the chooser shim: debounced, read-only pad sampling.
 *
 * Wiring (research/ios26-dualboot-r8/keys/KEYS.md has every citation):
 *   stock FDT /gpio_keys (truth/fdt.dtb 88bb3e4e...): button-voldn gpios = <cpm_pinctrl 0x33 ACTIVE_LOW>,
 *     button-volup <0x34 ACTIVE_LOW>, button-power <0x30 ACTIVE_LOW>; cpm_pinctrl = pinctrl@5280000,
 *     reg 0x5280000 size 0x39000, gpio-line-names[48,51,52] = PMICM2AP_GSC_PWRON_OD_L, VOL_DN_L, VOL_UP_L.
 *   stock pinctrl.ko (vendor_boot_b 16K ramdisk, 12a0698c...): google_gpio_get reads
 *     base + pin.index * stride + reg2offset[4] and returns bit 0; reg2offset[4] = 0x10 (RXDATA),
 *     cpm stride = 0x1000, cpm pin 48/51/52 index = 48/51/52 (XCPM_GPI0, XCPM_GPI1, XCPM_EINT_12).
 *   physical keys-probe-r1 (20261102-004645): these RXDATA reads were safe with no CPM request;
 *     volume presses were seen, a power press was not.
 *
 * The module only reads. The reader is injected so a host test can mock MMIO; on the phone it is
 * probe_read32 (fault-guarded). Gate: TGL_KEYS_POLL (default 0: the .c is an empty translation unit). */
#ifndef KEYS_LAGUNA_H
#define KEYS_LAGUNA_H

#include <stdint.h>

#ifndef TGL_KEYS_POLL
#define TGL_KEYS_POLL 0
#endif

#define KEYS_PAD_BASE		UINT64_C(0x05280000)	/* FDT pinctrl@5280000 reg */
#define KEYS_PAD_STRIDE		0x1000u			/* pinctrl.ko cpm match data +0x40 -> +0x10 */
#define KEYS_PAD_RXDATA		0x10u			/* pinctrl.ko reg2offset[4] */
#define KEYS_PAD_POWER		48u			/* FDT button-power gpios 0x30 */
#define KEYS_PAD_VOL_DOWN	51u			/* FDT button-voldn gpios 0x33 */
#define KEYS_PAD_VOL_UP		52u			/* FDT button-volup gpios 0x34 */
#define KEYS_PAD_PA(n)		(KEYS_PAD_BASE + (uint64_t)(n) * KEYS_PAD_STRIDE + KEYS_PAD_RXDATA)
#define KEYS_LEVEL_BIT		1u			/* google_gpio_get: and w21, w21, #0x1 */
#define KEYS_UNREADABLE		0xffffffffu

/* Chooser stamp for a change of keys_poll()'s result (stage 0x00cf is unused in shim/ and tools/chooser_stamps.py).
 * arg = result<<48 | raw levels (keys_raw_levels)<<40 | bad run<<32 | clean samples. */
#define KEYS_STAGE_DB	0x00cfu

/* Result bits. VOL_UP/VOL_DOWN equal chooser.h TGL_KEY_UP/TGL_KEY_DOWN. */
#define KEYS_VOL_UP	1u
#define KEYS_VOL_DOWN	2u
#define KEYS_POWER	4u
#define KEYS_HELD_MASK	7u
#define KEYS_TIMEOUT	0x100u	/* timeout_ms passed with nothing held and no change: take the default (Android) */
#define KEYS_FAULT	0x200u	/* reads failed or kept reading as garbage: keys are off for good */

#define KEYS_UNKNOWN	0x80u	/* internal: no steady sample yet */

#define KEYS_DEBOUNCE_MS	20u	/* level must hold this long (Linux gpio-keys default is 5 ms; DT sets none) */
#define KEYS_BAD_LIMIT		64u	/* consecutive garbage samples before the fault latches */
#define KEYS_N			3u

typedef int (*keys_rd32_fn)(uintptr_t pa, uint32_t *v);	/* nonzero = completed read */

struct keys_state {
	keys_rd32_fn rd;
	unsigned want;			/* which keys to read; others are never touched */
	unsigned stable;		/* debounced pressed bits */
	unsigned live;			/* keys seen released at least once (a key held at start is no press) */
	unsigned cand;			/* raw pressed bits being debounced */
	unsigned fault;
	uint32_t bad, reads, samples;
	uint32_t raw[KEYS_N];		/* last RXDATA words, order: power, vol-down, vol-up */
	uint64_t cand_ms, quiet_ms, timeout_ms;
};

/* want = any of KEYS_VOL_UP|KEYS_VOL_DOWN|KEYS_POWER. timeout_ms = 0: never report KEYS_TIMEOUT. */
void keys_init(struct keys_state *s, keys_rd32_fn rd, unsigned want, uint64_t now_ms, uint64_t timeout_ms);
/* One sample. Returns debounced held bits (& want) | KEYS_TIMEOUT | KEYS_FAULT. */
unsigned keys_poll(struct keys_state *s, uint64_t now_ms);
/* raw[] packed as power bit0 | vol-down bit1 | vol-up bit2 (level, 1 = idle) for stamps. */
unsigned keys_raw_levels(const struct keys_state *s);

#endif
