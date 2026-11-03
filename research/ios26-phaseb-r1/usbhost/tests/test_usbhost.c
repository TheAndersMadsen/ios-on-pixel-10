/*
 * Host test for blazer_usbhost_core.inc: a small xHCI + DWC3 model (registers, command/event/EP0 rings in a fake arena,
 * one USB2 and one USB3 root port, a scripted device) and the scenarios that matter on the phone.
 * cc -std=c11 -fsanitize=address,undefined -I../xnu-src test_usbhost.c -o test_usbhost && ./test_usbhost
 * HOST evidence only: the model is written from the xHCI 1.2 spec, not from this controller.
 */
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ------------------------------------------------------------------ includer contract */
struct uh_arena { uintptr_t va; uint64_t pa; };
static struct uh_arena uh_mem;
static uint64_t now_us;
static char out[65536];
static size_t out_len;

static uint32_t sim_rd(uint32_t off);
static void sim_wr(uint32_t off, uint32_t v);
static uint32_t uh_rd(uint32_t off) { return sim_rd(off); }
static void uh_wr(uint32_t off, uint32_t v) { sim_wr(off, v); }
static uint32_t tca_reads, dptop_reads;
static uint32_t uh_tca_rd(uint32_t off) { tca_reads++; return 0x1000u + off; }
static uint32_t uh_dptop_rd(uint32_t off) { dptop_reads++; return 0x2000u + off; }
static uint32_t glue_reads;
static uint32_t uh_glue_rd(uint32_t off) { glue_reads++; return off == 0 ? 0u : 0x8u; }
static void uh_dsb(void) {}
static void sim_tick(void);
static void uh_sleep_ms(unsigned ms) { for (unsigned i = 0; i < ms; i++) { now_us += 1000; sim_tick(); } }
static uint64_t uh_ticks(void) { return now_us; }
static uint64_t uh_hz(void) { return 1000000; }
#define UH_SAY(...) do { out_len += (size_t)snprintf(out + out_len, sizeof(out) - out_len, __VA_ARGS__); } while (0)

#include "blazer_usbhost_core.inc"

/* ------------------------------------------------------------------ the model */
#define ARENA_PA        0xbee00000ull
#define OP              0x20u
#define RT              0x800u
#define DB              0x1000u
#define XECP            0x600u
#define NPORTS          2u      /* 1: USB2, 2: USB3 */

static uint8_t arena[UH_ARENA_BYTES] __attribute__((aligned(4096)));

struct device {
	bool present;
	uint32_t speed, mps0, connect_after_ms;
	uint8_t dev_desc[18];
	uint8_t cfg_desc[64];
	uint32_t cfg_len;
	const char *product;
};

static struct {
	/* DWC3 */
	uint32_t gsnpsid, gctl, dctl, dsts, devten, gevntsiz, gevntlo, gevnthi, gevntcount, gusb2phycfg;
	bool never_halt;
	unsigned halt_after;
	/* xHCI */
	uint32_t hcs1, hcs2, hcc1, usbcmd, usbsts, config, crcr_lo, crcr_hi, dcbaap_lo, dcbaap_hi;
	uint32_t iman, erstsz, erstba_lo, erstba_hi, erdp_lo, erdp_hi;
	uint32_t portsc[NPORTS + 1];
	uint64_t power_at_us[NPORTS + 1];
	unsigned hcrst_reads;
	/* rings */
	uint64_t cmd_deq; uint32_t cmd_ccs;
	uint64_t evt_enq; uint32_t evt_pcs; uint32_t evt_index;
	uint64_t ep0_deq; uint32_t ep0_ccs; uint32_t ep0_mps;
	uint32_t slot_enabled, address;
	uint8_t setup[8];
	uint32_t data_done;
	uint32_t address_cc;
	/* checks */
	unsigned writes, bad, forbidden, ped_writes, usb3_port_writes, doorbells;
	struct device dev;
} S;

static void bad(const char *what) { S.bad++; fprintf(stderr, "  model: %s\n", what); }
static uint8_t *pa2va(uint64_t pa, uint32_t n)
{
	if (pa < ARENA_PA || pa + n > ARENA_PA + UH_ARENA_BYTES) { bad("DMA outside the arena"); return NULL; }
	return arena + (pa - ARENA_PA);
}
static uint32_t m32(uint64_t pa) { uint8_t *p = pa2va(pa, 4); uint32_t v = 0; if (p) memcpy(&v, p, 4); return v; }
static void w32(uint64_t pa, uint32_t v) { uint8_t *p = pa2va(pa, 4); if (p) memcpy(p, &v, 4); }
static uint64_t m64(uint64_t pa) { return m32(pa) | (uint64_t)m32(pa + 4) << 32; }

static void post_event(uint64_t param, uint32_t status, uint32_t control)
{
	uint64_t seg = m64(((uint64_t)S.erstba_hi << 32) | S.erstba_lo);
	uint32_t size = m32((((uint64_t)S.erstba_hi << 32) | S.erstba_lo) + 8);
	if (S.erstsz != 1 || size == 0) { bad("event ring not set up"); return; }
	uint64_t at = seg + 16ull * S.evt_index;
	w32(at, (uint32_t)param); w32(at + 4, (uint32_t)(param >> 32)); w32(at + 8, status);
	w32(at + 12, (control & ~1u) | S.evt_pcs);
	if (++S.evt_index == size) { S.evt_index = 0; S.evt_pcs ^= 1; }
}

static void do_commands(void)
{
	for (int guard = 0; guard < 64; guard++) {
		uint32_t c = m32(S.cmd_deq + 12);
		if ((c & 1u) != S.cmd_ccs) return;
		uint32_t type = (c >> 10) & 0x3f;
		uint64_t here = S.cmd_deq;
		if (type == TRB_LINK) {
			S.cmd_deq = m64(here);
			if (c & TRB_TC) S.cmd_ccs ^= 1;
			continue;
		}
		S.cmd_deq += 16;
		uint32_t cc = 1, slot = c >> 24;
		uint32_t cs = (S.hcc1 & 4) ? 64 : 32;
		if (type == TRB_ENABLE_SLOT) {
			slot = ++S.slot_enabled;
		} else if (type == TRB_ADDRESS_DEVICE) {
			uint64_t ic = m64(here);
			uint64_t dcbaa = ((uint64_t)S.dcbaap_hi << 32) | S.dcbaap_lo;
			uint64_t dev = m64(dcbaa + 8ull * slot);
			uint32_t add = m32(ic + 4), s0 = m32(ic + cs), s1 = m32(ic + cs + 4), e1 = m32(ic + 2 * cs + 4);
			uint64_t deq = m64(ic + 2 * cs + 8);
			if (slot != S.slot_enabled) bad("address device: wrong slot");
			if (add != 3) bad("address device: add flags");
			if (((s0 >> 20) & 0xf) != S.dev.speed) bad("address device: speed");
			if ((s0 >> 27) != 1) bad("address device: context entries");
			if ((s1 >> 16) != 1) bad("address device: root port");
			if (((e1 >> 3) & 7) != 4) bad("address device: ep type");
			if (((e1 >> 1) & 3) != 3) bad("address device: CErr");
			if (!(deq & 1)) bad("address device: DCS");
			if (dev == 0) bad("address device: DCBAA entry");
			S.ep0_mps = e1 >> 16;
			S.ep0_deq = deq & ~0xfull;
			S.ep0_ccs = 1;
			cc = S.address_cc ? S.address_cc : 1;
			if (cc == 1 && dev) { S.address = 5; w32(dev + 12, (2u << 27) | S.address); }
		} else if (type == TRB_EVALUATE_CONTEXT) {
			uint64_t ic = m64(here);
			if (m32(ic + 4) != 2) bad("evaluate context: add flags");
			S.ep0_mps = m32(ic + 2 * cs + 4) >> 16;
		} else {
			bad("unknown command");
			cc = 5;
		}
		post_event(here, cc << 24, TRB_TYPE(TRB_EV_COMMAND) | (slot << 24));
	}
	bad("command ring runaway");
}

static uint32_t string_desc(uint8_t *buf)
{
	uint32_t n = 2;
	for (const char *p = S.dev.product; *p && n + 2 <= 64; p++) { buf[n++] = (uint8_t)*p; buf[n++] = 0; }
	buf[0] = (uint8_t)n; buf[1] = 3;
	return n;
}

static void do_ep0(void)
{
	for (int guard = 0; guard < 64; guard++) {
		uint32_t c = m32(S.ep0_deq + 12);
		if ((c & 1u) != S.ep0_ccs) return;
		uint32_t type = (c >> 10) & 0x3f;
		uint64_t here = S.ep0_deq;
		if (type == TRB_LINK) {
			S.ep0_deq = m64(here);
			if (c & TRB_TC) S.ep0_ccs ^= 1;
			continue;
		}
		S.ep0_deq += 16;
		if (type == TRB_SETUP) {
			if (!(c & TRB_IDT) || m32(here + 8) != 8) bad("setup TRB");
			uint32_t lo = m32(here), hi = m32(here + 4);
			memcpy(S.setup, &lo, 4); memcpy(S.setup + 4, &hi, 4);
		} else if (type == TRB_DATA) {
			uint8_t src[256] = {0};
			uint32_t n = 0, want = m32(here + 8) & 0x1ffff;
			uint16_t value = (uint16_t)(S.setup[2] | S.setup[3] << 8), wlen = (uint16_t)(S.setup[6] | S.setup[7] << 8);
			if (!(c & TRB_DIR_IN)) bad("data TRB not IN");
			if (S.setup[0] != 0x80 || S.setup[1] != 6) bad("not GET_DESCRIPTOR");
			if (value == 0x0100) { memcpy(src, S.dev.dev_desc, 18); n = 18; }
			else if (value == 0x0200) { memcpy(src, S.dev.cfg_desc, S.dev.cfg_len); n = S.dev.cfg_len; }
			else if ((value >> 8) == 3 && S.dev.product) n = string_desc(src);
			else bad("unexpected descriptor");
			if (n > wlen) n = wlen;
			if (n > want) n = want;
			/* Packets of the device's size; a packet shorter than the host's MPS ends the data stage. */
			if (S.dev.mps0 < S.ep0_mps && n > S.dev.mps0) n = S.dev.mps0;
			uint8_t *dst = pa2va(m64(here), want);
			if (dst) memcpy(dst, src, n);
			S.data_done = n;
		} else if (type == TRB_STATUS) {
			if (c & TRB_DIR_IN) bad("status stage should be OUT after an IN data stage");
			if (c & TRB_IOC) post_event(here, 1u << 24, TRB_TYPE(TRB_EV_TRANSFER) | (S.slot_enabled << 24) | (1u << 16));
		} else {
			bad("unexpected EP0 TRB");
		}
	}
	bad("ep0 ring runaway");
}

static void sim_tick(void)
{
	/* Device attach after power. */
	if ((S.portsc[1] & PORTSC_PP) && S.dev.present && !(S.portsc[1] & PORTSC_CCS) &&
	    now_us - S.power_at_us[1] >= 1000ull * S.dev.connect_after_ms) {
		S.portsc[1] |= PORTSC_CCS | PORTSC_CSC;
		S.portsc[1] = (S.portsc[1] & ~(0xfu << 10)) | (S.dev.speed << 10);
	}
}

static uint32_t sim_rd(uint32_t off)
{
	switch (off) {
	case UH_GSNPSID: return S.gsnpsid;
	case UH_GCTL: return S.gctl;
	case UH_DCTL: return S.dctl;
	case UH_DSTS:
		if (!(S.dctl & UH_DCTL_RUN_STOP) && !S.never_halt && S.halt_after-- == 0) S.dsts |= UH_DSTS_DEVCTRLHLT;
		return S.dsts;
	case UH_GEVNTCOUNT: return S.gevntcount;
	case UH_GUSB2PHYCFG: return S.gusb2phycfg;
	case UH_GHWPARAMS0: return 0x2020400au;
	case UH_GUCTL: return 0x0c808010u;
	case UH_GFLADJ: return 0x00a00000u;
	case XC_CAPLENGTH: return 0x01100000u | OP;
	case XC_HCSPARAMS1: return S.hcs1;
	case XC_HCSPARAMS2: return S.hcs2;
	case XC_HCCPARAMS1: return S.hcc1;
	case XC_DBOFF: return DB;
	case XC_RTSOFF: return RT;
	case XECP + 0: return 0x02000402u;              /* protocol, next 4 dwords, USB 2 */
	case XECP + 8: return 0x00000101u;              /* port 1, count 1 */
	case XECP + 16: return 0x03000002u;             /* protocol, last, USB 3 */
	case XECP + 24: return 0x00000102u;             /* port 2, count 1 */
	case OP + XO_USBCMD:
		if ((S.usbcmd & USBCMD_HCRST) && ++S.hcrst_reads >= 3) {
			S.usbcmd &= ~USBCMD_HCRST;
			for (unsigned p = 1; p <= NPORTS; p++) S.portsc[p] = 0;
		}
		return S.usbcmd;
	case OP + XO_USBSTS: return S.usbsts;
	case OP + XO_CONFIG: return S.config;
	}
	if (off >= OP + 0x400 && off < OP + 0x400 + 0x10 * NPORTS && ((off - OP - 0x400) & 0xf) == 0) {
		unsigned p = (off - OP - 0x400) / 0x10 + 1;
		if (S.portsc[p] & PORTSC_PR) {          /* the reset completes on the next look */
			S.portsc[p] &= ~PORTSC_PR;
			if (S.portsc[p] & PORTSC_CCS) S.portsc[p] |= PORTSC_PED;
			S.portsc[p] |= PORTSC_PRC;
		}
		return S.portsc[p];
	}
	if (off >= XECP && off < XECP + 0x40) return 0;
	bad("read of an unmodelled register");
	fprintf(stderr, "  read %#x\n", off);
	return 0;
}

static void sim_wr(uint32_t off, uint32_t v)
{
	S.writes++;
	switch (off) {
	case UH_GCTL: S.gctl = v; return;
	case UH_DCTL: S.dctl = v; return;
	case UH_DEVTEN: S.devten = v; return;
	case UH_GEVNTSIZ: S.gevntsiz = v; return;
	case UH_GEVNTADRLO: S.gevntlo = v; return;
	case UH_GEVNTADRHI: S.gevnthi = v; return;
	case UH_GEVNTCOUNT: S.gevntcount -= v & S.gevntcount; return;
	case UH_GUSB2PHYCFG: S.gusb2phycfg = v; return;
	case OP + XO_USBCMD:
		if ((S.gctl & UH_GCTL_PRTCAPDIR) != UH_GCTL_PRTCAP_HOST) bad("xHCI written outside host mode");
		S.usbcmd = v;
		if (v & USBCMD_HCRST) { S.hcrst_reads = 0; S.usbsts = USBSTS_HCH; }
		else if (v & USBCMD_RS) {
			S.usbsts &= ~USBSTS_HCH;
			S.cmd_deq = (((uint64_t)S.crcr_hi << 32) | S.crcr_lo) & ~0x3full;
			S.cmd_ccs = S.crcr_lo & 1;
			S.evt_pcs = 1; S.evt_index = 0;
		} else S.usbsts |= USBSTS_HCH;
		return;
	case OP + XO_USBSTS: S.usbsts &= ~v; return;
	case OP + XO_CONFIG: S.config = v; return;
	case OP + XO_CRCR_LO: S.crcr_lo = v; return;
	case OP + XO_CRCR_HI: S.crcr_hi = v; return;
	case OP + XO_DCBAAP_LO: S.dcbaap_lo = v; return;
	case OP + XO_DCBAAP_HI: S.dcbaap_hi = v; return;
	case RT + XR_IMAN: S.iman = v; return;
	case RT + XR_ERSTSZ: S.erstsz = v; return;
	case RT + XR_ERSTBA_LO: S.erstba_lo = v; return;
	case RT + XR_ERSTBA_HI: S.erstba_hi = v; return;
	case RT + XR_ERDP_LO: S.erdp_lo = v; return;
	case RT + XR_ERDP_HI: S.erdp_hi = v; return;
	case DB: S.doorbells++; do_commands(); return;
	}
	if (off > DB && off < DB + 4 * 256) {
		S.doorbells++;
		if ((off - DB) / 4 != S.slot_enabled || v != 1) bad("doorbell target");
		do_ep0();
		return;
	}
	if (off >= OP + 0x400 && off < OP + 0x400 + 0x10 * NPORTS) {
		unsigned p = (off - OP - 0x400) / 0x10 + 1;
		if (p != 1) { S.usb3_port_writes++; bad("USB3 root port written"); return; }
		if (v & PORTSC_PED) S.ped_writes++;
		uint32_t old = S.portsc[p];
		S.portsc[p] = (old & ~(PORTSC_CHANGES & v)) & ~(PORTSC_PP | PORTSC_PR);
		S.portsc[p] |= v & (PORTSC_PP | PORTSC_PR);
		if ((v & PORTSC_PP) && !(old & PORTSC_PP)) S.power_at_us[p] = now_us;
		if (!(v & PORTSC_PP) && (old & PORTSC_PP)) bad("port power dropped");
		return;
	}
	S.forbidden++;
	bad("write to a register outside the contract");
	fprintf(stderr, "  write %#x = %#x\n", off, v);
}

/* ------------------------------------------------------------------ scenarios */
static unsigned checks, failures;
#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; printf("FAIL %s:%d: ", __func__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static void reset(void)
{
	memset(&S, 0, sizeof(S));
	memset(&uh, 0, sizeof(uh));
	memset(arena, 0xa5, sizeof(arena));
	uh_mem.va = (uintptr_t)arena;
	uh_mem.pa = ARENA_PA;
	out_len = 0; out[0] = 0;
	now_us = 1000000;
	S.gsnpsid = UH_EXPECT_ID;
	S.gctl = UH_GCTL_PRTCAP_DEVICE | 0x00000004u;
	S.dctl = UH_DCTL_RUN_STOP;
	S.gevntcount = 8;
	S.gevntlo = 0xbe000000u;
	S.gusb2phycfg = 0x40u | 0x8u;
	S.halt_after = 3;
	S.hcs1 = (2u << 24) | (1u << 8) | 64u;          /* 2 ports, 64 slots */
	S.hcs2 = (2u << 27);                            /* 2 scratchpad buffers */
	S.hcc1 = ((XECP / 4) << 16) | (1u << 3) | 1u;   /* xECP, PPC, AC64; CSZ 0 */
	S.usbsts = USBSTS_HCH;
	tca_reads = dptop_reads = glue_reads = 0;
}

static void device_hs_storage(void)
{
	static const uint8_t dd[18] = { 18, 1, 0x00, 0x02, 0, 0, 0, 64, 0x81, 0x07, 0x81, 0x55, 0x00, 0x01, 1, 2, 3, 1 };
	static const uint8_t cd[32] = { 9, 2, 32, 0, 1, 1, 0, 0x80, 50, 9, 4, 0, 0, 2, 8, 6, 0x50, 0,
		7, 5, 0x81, 2, 0, 2, 0, 7, 5, 0x02, 2, 0, 2, 0 };
	S.dev.present = true; S.dev.speed = 3; S.dev.mps0 = 64; S.dev.connect_after_ms = 1500;
	memcpy(S.dev.dev_desc, dd, 18); memcpy(S.dev.cfg_desc, cd, 32); S.dev.cfg_len = 32;
	S.dev.product = "Cruzer \"Blade\"";
}

static void device_fs_keyboard(void)
{
	static const uint8_t dd[18] = { 18, 1, 0x10, 0x01, 0, 0, 0, 8, 0x6d, 0x04, 0x1c, 0xc3, 0x00, 0x49, 1, 2, 0, 1 };
	static const uint8_t cd[34] = { 9, 2, 34, 0, 1, 1, 0, 0xa0, 50, 9, 4, 0, 0, 1, 3, 1, 1, 0,
		9, 0x21, 0x11, 1, 0, 1, 0x22, 65, 0, 7, 5, 0x81, 3, 8, 0, 10 };
	S.dev.present = true; S.dev.speed = 1; S.dev.mps0 = 8; S.dev.connect_after_ms = 200;
	memcpy(S.dev.dev_desc, dd, 18); memcpy(S.dev.cfg_desc, cd, 34); S.dev.cfg_len = 34;
	S.dev.product = "USB Keyboard";
}

static bool has(const char *needle) { return strstr(out, needle) != NULL; }

static void test_hs_storage(void)
{
	reset(); device_hs_storage();
	enum uh_why why = uh_run(10);
	CHECK(why == UH_OK, "why %s\n%s", uh_why_name[why], out);
	CHECK(has("blazer-usbhost: ENUM port 1 speed high dev 0781:5581 usb 2.00 class 00/00/00 mps0 64 configs 1\n"), "%s", out);
	CHECK(has("blazer-usbhost: ENUM port 1 interfaces 1, first 08/06/50, config bytes 32\n"), "%s", out);
	CHECK(has("blazer-usbhost: ENUM port 1 product \"Cruzer ?Blade?\"\n"), "quote sanitised: %s", out);
	CHECK(has("blazer-usbhost: PASS, port 1 enumerated 0781:5581"), "%s", out);
	CHECK(has("blazer-usbhost: gadget halted in"), "%s", out);
	CHECK(has("blazer-usbhost: root ports usb2 1+1 usb3 2+1\n"), "%s", out);
	CHECK((S.gctl & UH_GCTL_PRTCAPDIR) == UH_GCTL_PRTCAP_HOST, "gctl %x", S.gctl);
	CHECK(!(S.gctl & UH_GCTL_CORESOFTRESET), "soft reset left set");
	CHECK(S.gevntlo == 0 && S.gevnthi == 0 && S.gevntsiz == (1u << 31) && S.devten == 0, "device event buffer not retired");
	CHECK(!(S.gusb2phycfg & UH_SUSPHY) && (S.gusb2phycfg & 0x8u), "SUSPHY: %x", S.gusb2phycfg);
	CHECK(S.bad == 0 && S.forbidden == 0 && S.ped_writes == 0 && S.usb3_port_writes == 0, "model complaints %u", S.bad);
	CHECK(tca_reads == 7 && dptop_reads == 4 && glue_reads == 4, "survey reads %u %u %u", tca_reads, dptop_reads, glue_reads);
	CHECK(has("blazer-usbhost: survey GHWPARAMS0 2020400a GUCTL c808010 GFLADJ a00000 glue hc_status 0 host_cfg1 8\n"), "%s", out);
	CHECK(S.config == 4, "MaxSlotsEn %u", S.config);
	CHECK(m64(ARENA_PA + UA_DCBAA) == ARENA_PA + UA_SCRATCH_ARRAY, "scratchpad array");
	CHECK(m64(ARENA_PA + UA_SCRATCH_ARRAY + 8) == ARENA_PA + UA_SCRATCH_PAGES + 0x1000, "scratchpad page 1");
	CHECK(S.address == 5, "address %u", S.address);
}

static void test_fs_keyboard_mps8(void)
{
	reset(); device_fs_keyboard();
	S.hcc1 |= 1u << 2;      /* 64-byte contexts */
	enum uh_why why = uh_run(10);
	CHECK(why == UH_OK, "why %s\n%s", uh_why_name[why], out);
	CHECK(has("blazer-usbhost: ep0 max packet 8: ok, cc 1\n"), "%s", out);
	CHECK(S.ep0_mps == 8, "ep0 mps %u", S.ep0_mps);
	CHECK(has("dev 046d:c31c usb 1.10 class 00/00/00 mps0 8 configs 1\n"), "%s", out);
	CHECK(has("first 03/01/01"), "%s", out);
	CHECK(has("csz 64"), "%s", out);
	CHECK(S.bad == 0 && S.forbidden == 0 && S.ped_writes == 0, "model complaints %u", S.bad);
}

static void test_fs_without_fix_would_truncate(void)
{
	/* The model's truncation is real: with EP0 at 64 a mps-8 device gives 8 bytes of an 18-byte descriptor. */
	reset(); device_fs_keyboard();
	CHECK(uh_to_host() == UH_OK && uh_xhci_start() == UH_OK, "%s", out);
	uh_op_wr(XO_PORTSC(1), PORTSC_PP);
	uh_sleep_ms(400);
	CHECK(uh_port_reset(1) == UH_OK && uh_address(1) == UH_OK, "%s", out);
	CHECK(uh_control_in(0x80, 6, 0x0100, 0, 18, UA_DESC) == UH_OK, "%s", out);
	CHECK(S.data_done == 8, "data %u", S.data_done);
}

static void test_no_device(void)
{
	reset();
	enum uh_why why = uh_run(3);
	CHECK(why == UH_NO_DEVICE, "why %s", uh_why_name[why]);
	CHECK(has("blazer-usbhost: no device in 3 s, port 1 PORTSC"), "%s", out);
	CHECK(has("blazer-usbhost: stop: no device, events 0, controller left in host mode until the end of the boot\n"), "%s", out);
	CHECK(S.bad == 0 && S.forbidden == 0, "model complaints %u", S.bad);
}

static void test_wrong_id_writes_nothing(void)
{
	reset(); device_hs_storage();
	S.gsnpsid = 0x5533290au;
	enum uh_why why = uh_run(3);
	CHECK(why == UH_REFUSED, "why %s", uh_why_name[why]);
	CHECK(S.writes == 0, "writes %u", S.writes);
	CHECK(has("controller untouched\n"), "%s", out);
}

static void test_host_already_refused(void)
{
	reset();
	S.gctl = UH_GCTL_PRTCAP_HOST;
	CHECK(uh_run(3) == UH_REFUSED && S.writes == 0, "writes %u", S.writes);
}

static void test_gadget_stuck(void)
{
	reset(); S.never_halt = true;
	enum uh_why why = uh_run(3);
	CHECK(why == UH_GADGET_STUCK, "why %s", uh_why_name[why]);
	CHECK(S.writes >= 1 && (S.gctl & UH_GCTL_PRTCAPDIR) == UH_GCTL_PRTCAP_DEVICE && S.gevntlo == 0xbe000000u,
	    "only DCTL and event acks may be written: writes %u gctl %x", S.writes, S.gctl);
	CHECK(has("blazer-usbhost: gadget no halt after 100 ms\n") && has("controller untouched"), "%s", out);
}

static void test_too_many_scratchpads(void)
{
	reset(); S.hcs2 = (13u << 27);
	CHECK(uh_run(3) == UH_SCRATCH, "%s", out);
	CHECK(S.usbcmd == 0, "xHCI command written before the refusal");
}

static void test_address_fails(void)
{
	reset(); device_hs_storage(); S.address_cc = 4;
	enum uh_why why = uh_run(10);
	CHECK(why == UH_CMD_FAILED, "why %s", uh_why_name[why]);
	CHECK(has("address device: command failed, cc 4"), "%s", out);
}

static void test_ring_wrap(void)
{
	reset(); device_hs_storage();
	CHECK(uh_run(10) == UH_OK, "%s", out);
	/* 70 more transfers: the EP0 ring (15 TRBs + link) wraps 14 times, the event ring (64) once. */
	for (int i = 0; i < 70; i++) {
		memset(arena + UA_DESC, 0, 18);
		enum uh_why why = uh_control_in(0x80, 6, 0x0100, 0, 18, UA_DESC);
		if (why != UH_OK || arena[UA_DESC + 8] != 0x81 || arena[UA_DESC + 10] != 0x81) {
			CHECK(0, "transfer %d: %s", i, uh_why_name[why]);
			break;
		}
	}
	CHECK(uh.evt_cycle == 0 && uh.events >= 64, "event ring did not wrap: events %u", uh.events);
	/* 20 more commands wrap the command ring (15 + link). */
	for (int i = 0; i < 20; i++) {
		uint32_t slot;
		if (uh_command(0, TRB_TYPE(TRB_ENABLE_SLOT), &slot) != UH_OK) { CHECK(0, "command %d", i); break; }
	}
	CHECK(uh.cmd_cycle == 0, "command ring did not wrap");
	CHECK(S.bad == 0 && S.forbidden == 0, "model complaints %u", S.bad);
}

int main(void)
{
	test_hs_storage();
	test_fs_keyboard_mps8();
	test_fs_without_fix_would_truncate();
	test_no_device();
	test_wrong_id_writes_nothing();
	test_host_already_refused();
	test_gadget_stuck();
	test_too_many_scratchpads();
	test_address_fails();
	test_ring_wrap();
	printf("test_usbhost: %u checks, %u failed\n", checks, failures);
	reset(); device_hs_storage(); (void)uh_run(10);
	printf("--- sample console (HS storage) ---\n%s", out);
	return failures != 0;
}
