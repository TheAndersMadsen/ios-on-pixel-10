#pragma once
#include <stdint.h>
#include "chooser.h"

/* Chooser iOS branch (gate TGL_CHOOSER_IOS=1, needs TGL_CHOOSER=1; default off).
 * research/ios26-dualboot-r8/chooser-ios/DESIGN.md.
 *
 * One boot image carries, after the shim's _end:
 *   _end:      "TEGUPLD1" u64 n, then n bytes of the TEGUXNU payload (image_tool's payload-usb.bin, unchanged)
 *   align 8:   "TGLLNX01" segment (stock Android lz4 kernel, chooser.c format)
 * and _head+16 (image_size) covers both. tgl_payload_embedded() (payload.h) finds the envelope
 * exactly as on a direct iOS boot; chooser.c already skips it to find the segment.
 *
 * tgl_chooser_run (chooser_ios.c) shows the menu with the iOS entry live when the envelope
 * validates. Android: the chooser.c chain-load, unchanged in logic. iOS: give the display back
 * as ABL left it (the r11 release), turn the EL2 MMU and caches off with the data cleaned to PoC,
 * then return TGL_CHOOSER_PICKED_IOS. shim_main then runs the direct iOS path from "console init"
 * on (USB, UFS, the display handoff ladder, payload admission, EL2->EL1 drop), with the watchdogs
 * still armed and patted, exactly as a fastboot boot of the iOS image. */

#ifndef TGL_CHOOSER_IOS
#define TGL_CHOOSER_IOS 0
#endif
/* Attended test images only: the countdown ends on iOS instead of Android when the entry is live.
 * chooser_ios_image.py records it in the manifest and refuses to mark such an image installable. */
#ifndef TGL_CHOOSER_IOS_DEFAULT
#define TGL_CHOOSER_IOS_DEFAULT 0
#endif

/* Stamp stage, unused elsewhere (0x00c0..0x00ce chooser, 0x00cf keys_laguna.h, 0x00d0 DCS). */
#define TGL_STAGE_CHOOSER_IOS	0x00bfu	/* ENTER arg = payload bytes; DONE/REFUSED: see chooser_ios.c */
/* DONE-stamp sub-steps of TGL_STAGE_CHOOSER_IOS (arg bits 63:56). */
#define TGL_IOS_STEP_ADMIT	1u	/* arg low = payload bytes, or refusal text */
#define TGL_IOS_STEP_RELEASE	2u	/* arg low = ms<<16 | dcs code */
#define TGL_IOS_STEP_MMU_OFF	3u	/* arg low = SCTLR_EL2 after */
#define TGL_IOS_STEP_HANDBACK	4u	/* last chooser stamp before shim_main's iOS path */

struct tgl_chooser_ios_layout {
	uint64_t env_off;	/* offset of "TEGUPLD1" from _head (= _end offset) */
	uint64_t payload_off;	/* offset of the TEGUXNU bytes (env_off + 16) */
	uint64_t payload_bytes;
	uint64_t seg_off;	/* offset of "TGLLNX01", 8-aligned after the payload */
};

/* Pure, host-tested (chooser_ios_test.c). head = the loaded Image, image_size = its header
 * field, end_off = _end - _head. Refuses unless the envelope is at end_off, fits, and a
 * TGLLNX01 header fits after it. Reads only [head, head + image_size). */
const char *tgl_chooser_ios_layout(const uint8_t *head, uint64_t image_size, uint64_t end_off,
	struct tgl_chooser_ios_layout *out);

/* Pure: layout, then the shim's own tgl_payload_validate on the payload bytes, then the
 * placement facts loader.c refuses later (tgl_handoff_inputs/tgl_handoff_window with the
 * shim code extent, window clear of the whole loaded image and of the ramoops zone, metadata
 * clear of the initrd). head_pa = where head is in physical memory (the same on the phone;
 * the host test passes the FDT-side address). 0 = the iOS entry may be offered. */
const char *tgl_chooser_ios_admit(const uint8_t *head, uint64_t head_pa, uint64_t image_size,
	uint64_t end_off, uint64_t dtb, const struct tgl_fdt_memory *m,
	struct tgl_chooser_ios_layout *out);

/* What the chooser does with a menu result. Never IOS unless the entry was admitted. */
enum { TGL_IOS_ACT_ANDROID = 1, TGL_IOS_ACT_XNU = 2 };
unsigned tgl_chooser_ios_action(unsigned result, unsigned ios_available);

/* Initial selection for the menu: 1 (iOS) only with TGL_CHOOSER_IOS_DEFAULT and an admitted entry. */
unsigned tgl_chooser_ios_initial_sel(unsigned ios_available, unsigned default_ios);

/* tgl_chooser_run's return value when iOS was picked and the CPU is handed back to shim_main.
 * Any other return (including 0) is a refusal and shim_main resets. */
extern const char tgl_chooser_picked_ios[];
#define TGL_CHOOSER_PICKED_IOS tgl_chooser_picked_ios
