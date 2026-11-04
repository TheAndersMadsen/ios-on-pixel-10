/* TSHIMST1 stamp writer — see tgl_stamp.h.
 *
 * Device contract: exactly one destination (the S1-claimed pmsg window at PA
 * 0x95430000), writes only, no loops that depend on device state, no MMIO.
 * Runs with the MMU off (VA==PA) and keeps working unchanged after
 * mmu_enable-style identity maps: 0x95430000 stays Device/RAM-mapped either
 * way. Every store is followed by dsb so the record is visible to a later
 * ramdump even if the next instruction never completes.
 */
#include <stdint.h>
#include "tgl_stamp.h"

#ifdef __aarch64__
#define stamp_dsb() __asm__ volatile("dsb sy" ::: "memory")
#else
#define stamp_dsb() __asm__ volatile("" ::: "memory")
#endif

struct tgl_stamp_header {
	uint64_t magic, nonce;
	uint32_t count, seq, last_stage, flags;
	uint64_t freq, t0, tlast;
	uint32_t dropped, reason;
};
struct tgl_stamp_slot {
	uint32_t seq;
	uint16_t stage, flags;
	uint64_t t, arg;
};

_Static_assert(sizeof(struct tgl_stamp_header) == 64, "TSHIMST header size");
_Static_assert(sizeof(struct tgl_stamp_slot) == 24, "TSHIMST2 slot size");

#ifdef TGL_STAMP_HOST
/* Host tests redirect the channel with tgl_stamp_set_sink(). */
static volatile uint8_t *tshim_channel;
void tgl_stamp_set_sink(volatile void *base)
{
	tshim_channel = (volatile uint8_t *)base;
}
#define STAMP_BASE() ((uintptr_t)tshim_channel)
#else
void tgl_stamp_set_sink(volatile void *base)
{
	(void)base; /* the device channel is fixed; refusing keeps the ABI honest */
}
#define STAMP_BASE() ((uintptr_t)TGL_STAMP_BASE)
#endif

#ifdef TGL_STAMP_HOST_CLOCK
#ifndef TGL_STAMP_HOST
#error "TGL_STAMP_HOST_CLOCK is host-only"
#endif
/* Host tests drive the arch timer (stamp_deadline_test.c). */
extern uint64_t tgl_stamp_host_cntvct, tgl_stamp_host_cntfrq;
#endif

static uint64_t stamp_counter(void)
{
#if defined(TGL_STAMP_HOST_CLOCK)
	return tgl_stamp_host_cntvct;
#elif defined(__aarch64__)
	uint64_t now;
	__asm__ volatile("mrs %0, cntvct_el0" : "=r"(now));
	return now;
#else
	return 0;
#endif
}

static uint64_t stamp_frequency(void)
{
#if defined(TGL_STAMP_HOST_CLOCK)
	return tgl_stamp_host_cntfrq;
#elif defined(__aarch64__)
	uint64_t freq;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
	return freq;
#else
	return 0;
#endif
}

#ifdef TGL_STAMP_UFS_FOCUS
/* Diagnostic-only compaction; no change to the channel ABI or default.
 * Retain the first complete LPCM wire echo, and identical-value geometry
 * summaries once per boot. Error flags and unexpected reply values always
 * win over compaction. The high-level CPM/UFS request outcomes stay intact. */
static unsigned focus_seen;
static uint64_t focus_geometry[4];

static int stamp_focus_keep(unsigned stage, unsigned flags, uint64_t arg)
{
	unsigned bit, index;
	if (flags & (TGL_STAMP_F_FAULT | TGL_STAMP_F_REFUSED |
	    TGL_STAMP_F_TIMEOUT)) return 1;
	if (flags == TGL_STAMP_F_DONE && arg <= UINT32_MAX &&
	    stage >= TGL_STAGE_LPCM_REQ0 && stage <= TGL_STAGE_LPCM_REPLY1) {
		/* Reply words are emitted as DONE before envelope/status
		 * validation in tgl_cpm.c:277-278. Keep anomalous values too. */
		if (stage == TGL_STAGE_LPCM_REPLY1 && arg != 0) return 1;
		if (stage == TGL_STAGE_LPCM_REPLY0 && (arg & 0xffu) != 0 &&
		    (arg & 0xffu) != 2 && (arg & 0xffu) != 3) return 1;
		bit = 1u << (stage - TGL_STAGE_LPCM_REQ0);
		if (focus_seen & bit) return 0;
		focus_seen |= bit;
		return 1;
	}
	if (stage == TGL_STAGE_CPM_GEO && flags == TGL_STAMP_F_ENTER && arg == 0)
		index = 0;
	else if (stage == TGL_STAGE_CPM_GEO && flags == TGL_STAMP_F_DONE)
		index = 1;
	else if (stage == TGL_STAGE_MBA_LIVE && flags == TGL_STAMP_F_DONE)
		index = 2;
	else if (stage == TGL_STAGE_CPM_GEO2 && flags == TGL_STAMP_F_DONE)
		index = 3;
	else {
		/* laguna_usb.c:505 packs setup type/request/length into
		 * 24 bits. Current coarse waits are 8 and 1 seconds
		 * (tgl_usb_console.c:313, shim.c); retain 0..255 seconds.
		 * laguna_usb.c:575 encodes packet DONE as 0x8000|n,
		 * with n<=512 (UD_DATA_MAX). Preserve 0x8001 because it
		 * also denotes !ok, although its flags are only DONE.
		 * Coarse DONE is running=0/1 and never matches this range. */
		if (stage == TGL_STAGE_USB_WAIT &&
		    ((flags == TGL_STAMP_F_ENTER && arg >= 0x100u &&
		    arg <= 0xffffffu) ||
		    (flags == TGL_STAMP_F_DONE && arg >= 0x8000u &&
		    arg <= 0x8200u && arg != 0x8001u))) return 0;
		return 1;
	}
	bit = 1u << (4 + index);
	if ((focus_seen & bit) && focus_geometry[index] == arg) return 0;
	focus_seen |= bit;
	focus_geometry[index] = arg;
	return 1;
}
#endif

/* One stamp, expressed on raw bytes: header fields first-initialized, slot
 * appended before count/seq advance. No allocation, no loops. */
static void stamp_write(unsigned stage, unsigned flags, uint64_t arg)
{
	volatile struct tgl_stamp_header *h =
	    (volatile struct tgl_stamp_header *)STAMP_BASE();
	if (!STAMP_BASE() || h->magic != TGL_STAMP_MAGIC || h->nonce != TGL_STAMP_NONCE)
		return; /* not initialized: a stamp can never initialize halfway */
#ifdef TGL_STAMP_UFS_FOCUS
	if (!stamp_focus_keep(stage, flags, arg)) {
		/* Keep current-stage context even for intentionally omitted
		 * detail: fail_current must still name the failing operation.
		 * Intentional filtering is not ring overflow (dropped stays 0). */
		h->last_stage = stage;
		h->flags = flags;
		h->tlast = stamp_counter();
		stamp_dsb();
		return;
	}
#endif
	if (h->count < TGL_STAMP_SLOTS) {
		volatile struct tgl_stamp_slot *s =
		    (volatile struct tgl_stamp_slot *)(STAMP_BASE() + 0x40 +
			(uintptr_t)h->count * 24);
		uint32_t seq = h->seq + 1;
		uint64_t now = stamp_counter();
		s->arg = arg;
		s->flags = (uint16_t)flags;
		s->stage = (uint16_t)stage;
		s->t = now;
		stamp_dsb();
		s->seq = seq; /* slot becomes valid only with its seq */
		stamp_dsb();
		h->count = h->count + 1;
		h->seq = seq;
		h->tlast = now;
	} else {
		h->dropped = h->dropped + 1;
	}
	h->last_stage = stage;
	h->flags = flags;
	stamp_dsb();
}

/* Per-boot deadline origin (.bss, zeroed by start.S on every entry). The
 * header t0 belongs to the FIRST boot of this nonce and survives a reset
 * with the trail; measuring the bring-up deadline from it made every
 * same-nonce re-entry fail its first bringup_gate (parkqual1/2,
 * 2026-10-28: fdt-parse FAULT arg=&"post-wdt-survey"). */
static uint64_t boot_t0, boot_freq;

void tgl_stamp_boot_entry(void)
{
	volatile struct tgl_stamp_header *h =
	    (volatile struct tgl_stamp_header *)STAMP_BASE();
	uint64_t entry_arg = 0;
	boot_t0 = stamp_counter();
	boot_freq = stamp_frequency();
	if (!STAMP_BASE()) return;
#if defined(TGL_STAMP_ROTATE_FREE) && TGL_STAMP_ROTATE_FREE > 0
	/* chooser-ios WARM-r1 (TGL_CHOOSER_WARM builds): an installed image keeps one nonce across boots, DRAM survives a
	 * warm reset, and one iOS session (shim + XNU tegu_early on this ring) fills all TGL_STAMP_SLOTS. The next warm
	 * boot's stamps were then all dropped. With fewer than TGL_STAMP_ROTATE_FREE free slots the trail starts over
	 * for this boot: count, dropped and reason reset, t0 = now, seq continues. The entry stamp's arg records what
	 * was there: bit 63 set, bits 55:48 old count, 47:24 old dropped, 23:8 old last_stage, 7:0 old reason.
	 * A short failing boot (a reset loop) still appends, as before. */
	if (h->magic == TGL_STAMP_MAGIC && h->nonce == TGL_STAMP_NONCE &&
	    h->count + TGL_STAMP_ROTATE_FREE > TGL_STAMP_SLOTS) {
		entry_arg = UINT64_C(1) << 63 | (uint64_t)(h->count & 0xffu) << 48 |
		    (uint64_t)(h->dropped & 0xffffffu) << 24 |
		    (uint64_t)(h->last_stage & 0xffffu) << 8 | (h->reason & 0xffu);
		h->count = 0;
		stamp_dsb();
		h->dropped = 0;
		h->freq = stamp_frequency();
		h->t0 = stamp_counter();
		h->reason = TGL_STAMP_R_IN_PROGRESS;
		stamp_dsb();
	}
#endif
	if (h->magic != TGL_STAMP_MAGIC || h->nonce != TGL_STAMP_NONCE) {
		/* Fresh channel: a mismatched nonce means the residue belongs to
		 * another build, so it must not be read as this boot's history. */
		for (unsigned i = 0; i < 64; i++)
			((volatile uint8_t *)STAMP_BASE())[i] = 0;
		stamp_dsb();
		h->magic = TGL_STAMP_MAGIC;
		h->nonce = TGL_STAMP_NONCE;
		h->freq = stamp_frequency();
		h->t0 = stamp_counter();
		/* v3.6: arm the terminal reason as IN-PROGRESS immediately, so
		 * a watchdog reset during bring-up decodes as in-progress +
		 * last_stage (the v35 run's reason=none left the wedge
		 * unattributed). Reason 0 then exists only before entry. */
		h->reason = TGL_STAMP_R_IN_PROGRESS;
		stamp_dsb();
	}
#ifdef TGL_STAMP_UFS_FOCUS
	/* A real re-entry clears BSS too; reset the summary state explicitly
	 * so host replay and same-nonce re-entry preserve one summary/boot. */
	focus_seen = 0;
#endif
	/* Same nonce: a PSCI-reset re-entry appends to the surviving trail. */
	stamp_write(TGL_STAGE_ENTRY, TGL_STAMP_F_ENTER, entry_arg);
}

void tgl_stamp(unsigned stage, unsigned flags, uint64_t arg)
{
	stamp_write(stage, flags, arg);
}

void tgl_stamp_reason(unsigned reason)
{
	volatile struct tgl_stamp_header *h =
	    (volatile struct tgl_stamp_header *)STAMP_BASE();
	if (!STAMP_BASE() || h->magic != TGL_STAMP_MAGIC || h->nonce != TGL_STAMP_NONCE)
		return;
	h->reason = reason; /* header word 0x3c is the terminal code */
	stamp_dsb();
}

unsigned tgl_stamp_reason_get(void)
{
	volatile struct tgl_stamp_header *h =
	    (volatile struct tgl_stamp_header *)STAMP_BASE();
	if (!STAMP_BASE() || h->magic != TGL_STAMP_MAGIC || h->nonce != TGL_STAMP_NONCE)
		return 0;
	return h->reason;
}

unsigned tgl_stamp_over_deadline(unsigned seconds)
{
	volatile struct tgl_stamp_header *h =
	    (volatile struct tgl_stamp_header *)STAMP_BASE();
	if (!STAMP_BASE() || h->magic != TGL_STAMP_MAGIC || h->nonce != TGL_STAMP_NONCE)
		return 0;
	uint64_t freq = boot_freq, t0 = boot_t0;
	if (!freq) return 0;
	uint64_t now = stamp_counter();
	return (now - t0) / freq >= seconds;
}

void tgl_stamp_el_drop_done(void)
{
#ifdef __aarch64__
	uint64_t el = 0;
	__asm__ volatile("mrs %0, CurrentEL" : "=r"(el));
	tgl_stamp(TGL_STAGE_EL_DROP, TGL_STAMP_F_DONE, el << 28);
#else
	tgl_stamp(TGL_STAGE_EL_DROP, TGL_STAMP_F_DONE, UINT64_C(4) << 28);
#endif
}

void tgl_stamp_reason_handoff(void)
{
	tgl_stamp_reason(TGL_STAMP_R_HANDOFF);
}

unsigned tgl_stamp_last_stage(void)
{
	volatile struct tgl_stamp_header *h =
	    (volatile struct tgl_stamp_header *)STAMP_BASE();
	if (!STAMP_BASE() || h->magic != TGL_STAMP_MAGIC || h->nonce != TGL_STAMP_NONCE)
		return 0;
	return h->last_stage;
}

unsigned tgl_stamp_fail_current(uint64_t code)
{
	unsigned stage = tgl_stamp_last_stage();
	if (!stage) stage = TGL_STAGE_ENTRY;
	tgl_stamp(stage, TGL_STAMP_F_FAULT, code);
	return stage;
}

const char *tgl_stage_name(unsigned stage)
{
	switch (stage) {
	case TGL_STAGE_ENTRY: return "entry";
	case TGL_STAGE_CPU_STATE: return "cpu-state(mmu-off evidence)";
	case TGL_STAGE_WDT_SURVEY: return "wdt-survey";
	case TGL_STAGE_FDT_PARSE: return "fdt-parse";
	case TGL_STAGE_CONSOLE_INIT: return "console-init";
	case TGL_STAGE_WDT_PAT: return "wdt-pat";
	case TGL_STAGE_USB_PREFLIGHT: return "usb-preflight";
	case TGL_STAGE_DMA_ADMIT: return "dma-admit";
	case TGL_STAGE_CPM_ACK_ENTER: return "cpm-ack-wait";
	case TGL_STAGE_CPM_ACK_DONE: return "cpm-ack-done";
	case TGL_STAGE_CPM_SEND: return "cpm-send-wait";
	case TGL_STAGE_PHY_RESUME: return "phy-resume";
	case TGL_STAGE_DWC3_HALT: return "dwc3-halt-wait";
	case TGL_STAGE_DWC3_RESET: return "dwc3-reset-wait";
	case TGL_STAGE_EP0_CONFIG: return "ep0-config";
	case TGL_STAGE_EP0_READY: return "ep0-ready";
	case TGL_STAGE_USB_WAIT: return "usb-enum-wait";
	case TGL_STAGE_PAYLOAD: return "payload-admit";
	case TGL_STAGE_HANDOFF: return "pre-xnu-handoff";
	case TGL_STAGE_WDT_QUIESCE: return "wdt-quiesce-late";
	case TGL_STAGE_USB_PWR: return "usb-pwr-status";
	case TGL_STAGE_USB_GSNPSID: return "usb-gsnpsid";
	case TGL_STAGE_USB_GCTL: return "usb-gctl";
	case TGL_STAGE_USB_EVT_HI: return "usb-evt-hi";
	case TGL_STAGE_USB_BADID: return "usb-refused-bad-id";
	case TGL_STAGE_USB_BADCAP: return "usb-refused-prtcap";
	case TGL_STAGE_USB_EVTHANG: return "usb-refused-stale-evt";
	case TGL_STAGE_USB_BADPWR: return "usb-refused-not-d0";
	case TGL_STAGE_CONSOLE_CLS: return "console-paint-done";
	case TGL_STAGE_CPM_FIRST: return "cpm-first";
	case TGL_STAGE_CPM_GEO: return "cpm-geo";
	case TGL_STAGE_CPM_CLK: return "cpm-clk";
	case TGL_STAGE_CPM_RST: return "cpm-rst";
	case TGL_STAGE_USB_WARM: return "usb-warm";
	case TGL_STAGE_USB_DCTL: return "usb-dctl";
	case TGL_STAGE_MBA_LIVE: return "mba-live";
	case TGL_STAGE_MBA_SEND: return "mba-send";
	case TGL_STAGE_MBA_ACK: return "mba-ack";
	case TGL_STAGE_MBA_RESP0: return "mba-resp0";
	case TGL_STAGE_EL_DROP: return "el-drop";
	case TGL_STAGE_CPM_GEO2: return "cpm-geo2";
	case TGL_STAGE_LPCM_REQ0: return "lpcm-req0";
	case TGL_STAGE_LPCM_REQ1: return "lpcm-req1";
	case TGL_STAGE_LPCM_REPLY0: return "lpcm-reply0";
	case TGL_STAGE_LPCM_REPLY1: return "lpcm-reply1";
	case TGL_STAGE_USB_LINK: return "usb-link";
	case TGL_STAGE_CPM_PHY: return "cpm-phy";
	case TGL_STAGE_DISP_RECORD: return "disp-record";
	case TGL_STAGE_DISP_GATE: return "disp-gate";
	case TGL_STAGE_DISP_POWER: return "disp-power";
	case TGL_STAGE_DISP_SNAP: return "disp-snap";
	case TGL_STAGE_DISP_S1_ADDR_LO: return "disp-s1-addr-lo";
	case TGL_STAGE_DISP_S1_ADDR_HI: return "disp-s1-addr-hi";
	case TGL_STAGE_DISP_S2_CONFIG: return "disp-s2-config";
	case TGL_STAGE_DISP_S2_SIZE: return "disp-s2-size";
	case TGL_STAGE_DISP_S2_STRIDE: return "disp-s2-stride";
	case TGL_STAGE_DISP_S3_COORD0: return "disp-s3-coord0";
	case TGL_STAGE_DISP_S3_COORD1: return "disp-s3-coord1";
	case TGL_STAGE_DISP_S4_MODE: return "disp-s4-mode";
	case TGL_STAGE_DISP_S4_STATUS: return "disp-s4-status";
	case TGL_STAGE_DISP_S5_PHY: return "disp-s5-phy";
	case TGL_STAGE_DISP_R1: return "disp-revive-r1";
	case TGL_STAGE_DISP_R2: return "disp-revive-r2";
	case TGL_STAGE_DISP_R3: return "disp-revive-r3";
	case TGL_STAGE_DISP_R4: return "disp-revive-r4";
	case TGL_STAGE_DISP_R5: return "disp-revive-r5";
	case TGL_STAGE_DISP_R6: return "disp-revive-r6";
	case TGL_STAGE_DISP_R7: return "disp-revive-r7";
	case TGL_STAGE_DISP_LIVE: return "disp-live-proof";
	case TGL_STAGE_UFS_FIRST: return "ufs-ladder";
	case TGL_STAGE_UFS_HCI: return "ufs-hci";
	case TGL_STAGE_UFS_HCS: return "ufs-hcs";
	case TGL_STAGE_UFS_CLK: return "ufs-clk";
	case TGL_STAGE_UFS_RST: return "ufs-rst";
	case TGL_STAGE_UFS_PD: return "ufs-pd";
	case TGL_STAGE_UFS_TUR: return "ufs-tur";
	case TGL_STAGE_UFS_RDCAP: return "ufs-rdcap";
	case TGL_STAGE_UFS_RDCAP1: return "ufs-rdcap1";
	case TGL_STAGE_UFS_GPT: return "ufs-gpt";
	case TGL_STAGE_UFS_PART: return "ufs-part";
	case TGL_STAGE_UFS_LIVE: return "ufs-live";
	case TGL_STAGE_UFS_STAGE: return "ufs-stage";
	default: return "unknown";
	}
}

/* Microseconds on the same counter and boot origin as the stamps. No new timer setup. */
int tgl_stamp_boot_us(uint64_t *out)
{
	uint64_t n = stamp_counter(), f = boot_freq;
	if (!out || !f || f > UINT64_MAX / 1000000 || n < boot_t0) return -1;
	uint64_t ticks = n - boot_t0, seconds = ticks / f;
	if (seconds >= 90) return -1;
	*out = seconds * 1000000 + (ticks % f) * 1000000 / f;
	return 0;
}
