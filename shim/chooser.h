#pragma once
#include <stdint.h>
#include "fdt.h"

/* A2 boot chooser (gate TGL_CHOOSER=1, default off). Runs at EL2 straight
 * after the FDT admission parse, before any display, USB, UFS, CPM, clock or
 * watchdog-quiesce work. Default and v1 only path: chain-load the stock
 * Android kernel carried in the image as a TGLLNX01 segment, FDT and initrd
 * exactly as ABL built them. docs/DUALBOOT.md, GOAL.md section 6. */

#define TGL_CHOOSER_SEG_MAGIC "TGLLNX01"
#define TGL_CHOOSER_SEG_HDR 64u
#define TGL_CHOOSER_ALIGN (UINT64_C(2) << 20)	/* arm64 Image: 2 MiB base */
#define TGL_CHOOSER_MAX_IMAGE (UINT64_C(256) << 20)
#define TGL_CHOOSER_TIMEOUT_MS 5000u
#define TGL_CHOOSER_KEY_GRACE_MS 3000u		/* countdown after the last key */

/* Stamp stages (TSHIMST2), 0x00c0.. unused elsewhere. */
#define TGL_STAGE_CHOOSER_ENTER	0x00c0u	/* arg = CurrentEL<<32 | SCTLR_EL2 */
#define TGL_STAGE_CHOOSER_SEG	0x00c1u	/* DONE arg = comp_len, REFUSED arg = reason */
#define TGL_STAGE_CHOOSER_PLACE	0x00c2u	/* DONE arg = chosen base */
#define TGL_STAGE_CHOOSER_MENU	0x00c3u	/* ENTER menu shown, arg = timeout ms */
#define TGL_STAGE_CHOOSER_KEY	0x00c4u	/* DONE arg = ms<<8 | key bits */
#define TGL_STAGE_CHOOSER_PICK	0x00c5u	/* DONE arg = ms<<8 | result<<4 | why */
#define TGL_STAGE_CHOOSER_LZ4	0x00c6u	/* ENTER/DONE arg = ms<<32 | out_len */
#define TGL_STAGE_CHOOSER_VERIFY 0x00c7u	/* DONE arg = image magic<<32 | csum lo */
#define TGL_STAGE_CHOOSER_JUMP	0x00c8u	/* ENTER arg = base; last stamp before Linux */
#define TGL_STAGE_CHOOSER_CSUM	0x00c9u	/* DONE arg = ms<<32 | csum lo */
#define TGL_STAGE_CHOOSER_MMU	0x00cau	/* DONE/REFUSED arg = wb<<32 | nc<<16 | refused */
#define TGL_STAGE_CHOOSER_UI	0x00cbu	/* DONE arg = render ms<<32 | cached */
#define TGL_STAGE_CHOOSER_DISPLAY 0x00ccu	/* DONE/REFUSED arg = ms<<32 | serror<<16 | dcs code */
#define TGL_STAGE_CHOOSER_RELEASE 0x00ceu	/* DONE/REFUSED arg = ms<<32 | serror<<16 | dcs code */
#define TGL_STAGE_CHOOSER_KEYS	0x00cdu	/* DONE/REFUSED arg = pad51 RXDATA<<32 | pad52 RXDATA at start */
#ifndef TGL_CHOOSER_KEYS
#define TGL_CHOOSER_KEYS 0
#endif
#ifndef TGL_CHOOSER_DISPLAY
#define TGL_CHOOSER_DISPLAY 0
#endif
#ifndef TGL_CHOOSER_MMU
#define TGL_CHOOSER_MMU 0
#endif
#ifndef TGL_CHOOSER_UI
#define TGL_CHOOSER_UI 0
#endif

struct tgl_chooser_seg {
	uint64_t comp_len, image_len, image_size, image_flags, csum;
	const uint8_t *data;
};

/* Pure helpers, host-tested in chooser_test.c. */
uint64_t tgl_chooser_csum64(const uint8_t *p, uint64_t n);
const char *tgl_chooser_seg_parse(const uint8_t *p, uint64_t avail,
	struct tgl_chooser_seg *out);
/* Lowest 2 MiB-aligned base whose [base, base+size) is inside one FDT RAM
 * range and clear of every reservation, alloc pool and live range. */
const char *tgl_chooser_place(const struct tgl_fdt_memory *m, uint64_t size,
	const struct tgl_range *live, unsigned live_count, uint64_t *base);

/* Menu state machine: entries Android (0) and iOS (1). */
enum { TGL_CHOOSE_PENDING = 0, TGL_CHOOSE_ANDROID = 1, TGL_CHOOSE_IOS = 2 };
enum { TGL_WHY_NONE = 0, TGL_WHY_TIMEOUT = 1, TGL_WHY_KEYS = 2, TGL_WHY_NO_IOS = 3 };
#define TGL_KEY_UP   1u
#define TGL_KEY_DOWN 2u
struct tgl_chooser_menu {
	unsigned sel, ios_available, result, why, presses;
	uint64_t deadline_ms, last_key_ms;
	unsigned prev_keys;
};
void tgl_chooser_menu_init(struct tgl_chooser_menu *s, uint64_t now_ms,
	unsigned ios_available);
/* keys = currently-held bits; edges are derived here. Returns result. */
unsigned tgl_chooser_menu_step(struct tgl_chooser_menu *s, uint64_t now_ms,
	unsigned keys);
/* chooser-v1-r13 (keys/DIAG-r13.md): keys = held bits now, seen = bits held at any sample since the last call
 * (taken while a redraw ran). A key pressed and released between two calls is fed as one press first.
 * Built with TGL_CHOOSER_KEYS_FIX (and on the host). */
unsigned tgl_chooser_menu_feed(struct tgl_chooser_menu *s, uint64_t now_ms,
	unsigned keys, unsigned seen);
#ifndef TGL_CHOOSER_KEYS_FIX
#define TGL_CHOOSER_KEYS_FIX 0
#endif
#ifndef TGL_CHOOSER_KEYS_DIAG
#define TGL_CHOOSER_KEYS_DIAG 0
#endif

/* Device entry. Returns only with a refusal reason; on success the stock
 * kernel owns the CPU. pat() keeps the ABL-armed watchdogs alive (never a
 * quiesce); keys() returns held key bits or 0 when the key gate is off. */
const char *tgl_chooser_run(uint64_t dtb, const struct tgl_fdt_memory *m,
	void (*pat)(void), unsigned (*keys)(void));
