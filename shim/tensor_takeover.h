/*
 * The record a first stage leaves when it hands a running DSI host, panel and configured DPU to the
 * kernel's Tensor G5 scanout backend. The same header builds in the shim and in the kernel.
 *
 * It is the only thing that allows the kernel to read a DC9x00 register: an unpowered read is an
 * asynchronous reset no handler catches. The first stage zeroes this page first thing on every boot,
 * before any display work, because this RAM survives a warm reset; so a record here was written by
 * this boot, and only after the stages it names passed.
 */
#ifndef HAKIOS_SCANOUT_TAKEOVER_H
#define HAKIOS_SCANOUT_TAKEOVER_H

#include <stdint.h>

/* In the ramoops zone, which the loader excludes from XNU's RAM and the capture dumps: pmsg+0x33000 and up,
 * above the panic mirror's window at pmsg+0x30000 (0x2040 bytes), below the msgbuf header at pmsg+0x3f800. */
#define HAKIOS_TAKEOVER_PA      UINT64_C(0x95433000)
#define HAKIOS_TAKEOVER_BYTES   0x1000u
#define HAKIOS_TENSOR_TRACE_PA  UINT64_C(0x95434000)
#define HAKIOS_TENSOR_TRACE_BYTES 0x4000u

#define HAKIOS_TAKEOVER_MAGIC   UINT64_C(0x314f4b544e435348) /* "HSCNTKO1" */
#define HAKIOS_TAKEOVER_VERSION 1u

/* Each bit: this stage ran and its check passed, on this boot. */
#define HAKIOS_TK_TOP_ON        (1u << 0)  /* CPM says the DPU top domain is on */
#define HAKIOS_TK_DSI0_ON       (1u << 1)  /* LPCM DSI0 replied 0 */
#define HAKIOS_TK_FE0_ON        (1u << 2)  /* LPCM FE0 replied 0 */
#define HAKIOS_TK_HOST_STREAM   (1u << 3)  /* host and PHY in data-stream mode, MODE_STATUS 4 */
#define HAKIOS_TK_PANEL_ID      (1u << 4)  /* panel answered with google-bzea's ID */
#define HAKIOS_TK_DPU_READ      (1u << 5)  /* chip ID read as 0x9400 */
#define HAKIOS_TK_ISO_CLEAR     (1u << 6)  /* DSI0 isolation lifted */
#define HAKIOS_TK_DPU_CONFIG    (1u << 7)  /* DSC, output timing, command mode written */
#define HAKIOS_TK_PANEL_DSC     (1u << 8)  /* PPS and 0x9D 0x01 sent */
#define HAKIOS_TK_FRAME_DONE    (1u << 9)  /* a first-stage kick reached FRM_DONE, nothing is in flight */
#define HAKIOS_TK_REQUIRED      0x3ffu

struct hakios_scanout_takeover {
	uint64_t magic;
	uint32_t version;
	uint32_t struct_size;
	uint32_t stages;
	uint32_t width, height;         /* what the DSC and timing were programmed for */
	uint32_t ref_hz;                /* reference clock the shim's PHY table used */
	uint32_t tx_lp;                 /* 1: commands in LP, as display-dcs-r2 */
	uint32_t te_seen;               /* 1: TE reached the DPU before any pad write */
	uint32_t frames;                /* first-stage kicks done */
	uint32_t chip_id, chip_rev;
	uint32_t reserved[2];
	uint32_t crc32;                 /* IEEE, over everything before it */
};
_Static_assert(sizeof(struct hakios_scanout_takeover) == 64, "takeover record is 64 bytes");

static inline uint32_t
hakios_takeover_crc(const void *data, uint32_t bytes)
{
	const uint8_t *p = (const uint8_t *)data;
	uint32_t crc = 0xffffffffu;

	for (uint32_t i = 0; i < bytes; i++) {
		crc ^= p[i];
		for (unsigned b = 0; b < 8; b++) {
			crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1u)));
		}
	}
	return ~crc;
}

#endif /* HAKIOS_SCANOUT_TAKEOVER_H */
