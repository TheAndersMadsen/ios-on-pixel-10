/*
 * blazer_usbhost core: the DWC3 as a polled xHCI host on its USB2 root ports; enumerate one device, say what it is.
 * Own code. Register facts: the xHCI 1.2 specification; the DWC3 role switch from Linux drivers/usb/dwc3/core.c
 * __dwc3_set_mode/dwc3_set_prtcap (GPL, facts only); Tensor G5 facts from the FDT (research/ios26-dualboot-r8/truth/
 * fdt.dts) and Google's lga sources (dwc3-google.c, google-usb-phy-driver.c, google-eusb2-repeater.c; GPL, facts only).
 * Design and evidence: research/ios26-phaseb-r1/usbhost/USBHOST.md.
 *
 * No XNU types: the kernel file (osfmk/arm64/blazer_usbhost.c) and the host simulator test
 * (research/ios26-phaseb-r1/usbhost/tests/test_usbhost.c) both include this. The includer supplies:
 *   uh_rd(off), uh_wr(off, v)          32-bit DWC3/xHCI MMIO at 0x0c400000 (xHCI 0x0..0x7fff, DWC3 globals 0xc100+)
 *   uh_tca_rd(off), uh_dptop_rd(off)    read-only: usb_phy dptx_tca_regs 0x0c430000, dp_top_csr 0x0c637000
 *   uh_glue_rd(off)                     read-only: dwc3-lga usbcs_host_cfg_csr 0x0c450000 (HC_STATUS 0x0, HOST_CFG1 0x4)
 *   uh_dsb(), uh_sleep_ms(ms), uh_ticks(), uh_hz(), UH_SAY(...)
 *   struct uh_arena { uintptr_t va; uint64_t pa; } uh_mem: UH_ARENA_BYTES, 4 KiB aligned, below 4 GiB, uncached.
 *
 * What it writes, and nothing else: DWC3 DCTL (RUN_STOP off), DEVTEN, GEVNT* (device event buffer retired),
 * GUSB2PHYCFG.SUSPHY off (as blazer_usbcon), GCTL (CORESOFTRESET, PRTCAPDIR); then the xHCI's own operational,
 * runtime, doorbell and USB2 PORTSC registers; and its arena. Never: GUSB3PIPECTL, USB3 PORTSC, the PHY/TCA, dp_top_csr,
 * the repeater, the TCPC, the charger (VBUS), clocks, resets, power domains or the CPM. The USB3 root ports are
 * never powered, so nothing asks the combo PHY for SuperSpeed.
 *
 * VBUS: the phone does not source it here (that is the TCPC/charger, an owner decision). The attached device has to
 * be powered from elsewhere: USBHOST.md, test setup.
 */

#define UH_GCTL                 0xc110u
#define UH_GSNPSID              0xc120u
#define UH_GUCTL                0xc12cu
#define UH_GHWPARAMS0           0xc140u
#define UH_GFLADJ               0xc630u
#define UH_GUSB2PHYCFG          0xc200u
#define UH_GEVNTADRLO           0xc400u
#define UH_GEVNTADRHI           0xc404u
#define UH_GEVNTSIZ             0xc408u
#define UH_GEVNTCOUNT           0xc40cu
#define UH_DCTL                 0xc704u
#define UH_DEVTEN               0xc708u
#define UH_DSTS                 0xc70cu
#define UH_GCTL_CORESOFTRESET   (1u << 11)
#define UH_GCTL_PRTCAPDIR       (3u << 12)
#define UH_GCTL_PRTCAP_HOST     (1u << 12)
#define UH_GCTL_PRTCAP_DEVICE   (2u << 12)
#define UH_SUSPHY               (1u << 6)
#define UH_DCTL_RUN_STOP        (1u << 31)
#define UH_DSTS_DEVCTRLHLT      (1u << 22)
#define UH_EXPECT_ID            0x33313130u     /* every physical boot (blazer_usbcon UC_EXPECT_ID) */

/* xHCI capability registers */
#define XC_CAPLENGTH            0x00u   /* [7:0] CAPLENGTH, [31:16] HCIVERSION */
#define XC_HCSPARAMS1           0x04u
#define XC_HCSPARAMS2           0x08u
#define XC_HCCPARAMS1           0x10u
#define XC_DBOFF                0x14u
#define XC_RTSOFF               0x18u
/* operational, from CAPLENGTH */
#define XO_USBCMD               0x00u
#define XO_USBSTS               0x04u
#define XO_PAGESIZE             0x08u
#define XO_CRCR_LO              0x18u
#define XO_CRCR_HI              0x1cu
#define XO_DCBAAP_LO            0x30u
#define XO_DCBAAP_HI            0x34u
#define XO_CONFIG               0x38u
#define XO_PORTSC(n)            (0x400u + 0x10u * ((n) - 1u))   /* n from 1 */
/* runtime, interrupter 0 */
#define XR_IMAN                 0x20u
#define XR_ERSTSZ               0x28u
#define XR_ERSTBA_LO            0x30u
#define XR_ERSTBA_HI            0x34u
#define XR_ERDP_LO              0x38u
#define XR_ERDP_HI              0x3cu

#define USBCMD_RS               (1u << 0)
#define USBCMD_HCRST            (1u << 1)
#define USBSTS_HCH              (1u << 0)
#define USBSTS_HSE              (1u << 2)
#define USBSTS_CNR              (1u << 11)
#define USBSTS_HCE              (1u << 12)

#define PORTSC_CCS              (1u << 0)
#define PORTSC_PED              (1u << 1)
#define PORTSC_PR               (1u << 4)
#define PORTSC_PLS_MASK         (0xfu << 5)
#define PORTSC_PP               (1u << 9)
#define PORTSC_SPEED(v)         (((v) >> 10) & 0xfu)
#define PORTSC_PIC_MASK         (3u << 14)
#define PORTSC_CSC              (1u << 17)
#define PORTSC_PRC              (1u << 21)
#define PORTSC_CHANGES          (0x7fu << 17)   /* CSC PEC WRC OCC PRC PLC CEC: write 1 to clear */
#define PORTSC_WAKE_MASK        (7u << 25)
/* Linux xhci_port_state_to_neutral: keep only what a write must not change. PED (write 1 = disable) and every change
 * bit are left 0; the read-only bits are ignored on a write anyway. */
#define PORTSC_NEUTRAL(v)       ((v) & (PORTSC_PP | PORTSC_PIC_MASK | PORTSC_WAKE_MASK))

/* TRBs */
#define TRB_CYCLE               (1u << 0)
#define TRB_TC                  (1u << 1)       /* link: toggle cycle */
#define TRB_IOC                 (1u << 5)
#define TRB_IDT                 (1u << 6)
#define TRB_TYPE(t)             ((uint32_t)(t) << 10)
#define TRB_TYPE_OF(c)          (((c) >> 10) & 0x3fu)
#define TRB_SETUP               2u
#define TRB_DATA                3u
#define TRB_STATUS              4u
#define TRB_LINK                6u
#define TRB_ENABLE_SLOT         9u
#define TRB_ADDRESS_DEVICE      11u
#define TRB_EVALUATE_CONTEXT    13u
#define TRB_EV_TRANSFER         32u
#define TRB_EV_COMMAND          33u
#define TRB_EV_PORT             34u
#define TRB_DIR_IN              (1u << 16)
#define TRB_TRT_IN              (3u << 16)
#define CC_SUCCESS              1u
#define CC_SHORT_PACKET         13u

/* Arena, offsets in uh_mem. xHCI: rings and contexts 64-byte aligned, no ring crosses 64 KiB, scratchpad pages
 * PAGESIZE (4 KiB) aligned. The arena is exactly 64 KiB, so nothing crosses. */
#define UH_ARENA_BYTES          0x10000u
#define UA_DCBAA                0x0000u         /* 256 slots x 8 */
#define UA_SCRATCH_ARRAY        0x0800u         /* up to UH_SCRATCH_MAX x 8 */
#define UA_ERST                 0x0900u         /* one segment */
#define UA_CMD_RING             0x1000u
#define UA_EVT_RING             0x1400u
#define UA_INPUT_CTX            0x2000u         /* 33 x 64 */
#define UA_DEV_CTX              0x3000u         /* 32 x 64 */
#define UA_EP0_RING             0x3800u
#define UA_DESC                 0x3a00u         /* 256 bytes: device, configuration */
#define UA_STRING               0x3b00u         /* 256 bytes */
#define UA_SCRATCH_PAGES        0x4000u
#define UH_SCRATCH_MAX          12u             /* 0x4000 + 12 x 4 KiB = 0x10000 */
#define UH_CMD_TRBS             16u             /* last one is the link */
#define UH_EVT_TRBS             64u
#define UH_EP0_TRBS             16u
#define UH_MAX_SLOTS            4u
#define UH_DESC_BYTES           256u

#define UH_HALT_MS              100u    /* as blazer_usbcon */
#define UH_SOFTRESET_MS         100u    /* Linux __dwc3_set_mode: DWC_usb31 needs up to 50 ms, it waits 100 */
#define UH_CNR_MS               1000u
#define UH_HCRST_MS             1000u
#define UH_RUN_MS               100u
#define UH_CMD_MS               500u
#define UH_PORT_RESET_MS        500u
#define UH_XFER_MS              1000u
#define UH_POWER_SETTLE_MS      100u    /* xHCI 4.19.4: 20 ms minimum after PP; USB2 attach debounce is the device's */
#define UH_POLL_MS              10u

enum uh_why {
	UH_OK = 0, UH_REFUSED, UH_GADGET_STUCK, UH_SOFTRESET_STUCK, UH_NOT_HOST, UH_BAD_XHCI, UH_CNR, UH_HCRST, UH_NO_RUN,
	UH_HOST_ERROR, UH_SCRATCH, UH_NO_USB2, UH_NO_DEVICE, UH_PORT_RESET, UH_CMD_TIMEOUT, UH_CMD_FAILED, UH_XFER_TIMEOUT,
	UH_XFER_FAILED, UH_BAD_DESC,
};
static const char *const uh_why_name[] = {
	"ok", "refused", "gadget did not halt", "core soft reset stuck", "GCTL not host after the switch", "xHCI registers implausible",
	"controller not ready (CNR)", "HCRST stuck", "did not run (HCH)", "host system error", "too many scratchpad buffers",
	"no USB2 root port", "no device", "port reset", "command timeout", "command failed", "transfer timeout",
	"transfer failed", "bad descriptor",
};

struct uh_dev {
	uint16_t vid, pid, bcd_usb;
	uint8_t class, subclass, protocol, mps0, configs, iface_class, iface_subclass, iface_protocol, interfaces;
	char product[48];
};

static struct {
	uint32_t caplen, hciversion, hcs1, hcs2, hcc1, op, rt, db, csz, slots, ports, scratch;
	uint32_t u2_first, u2_count, u3_first, u3_count;
	uint32_t cmd_enq, cmd_cycle, evt_deq, evt_cycle, ep0_enq, ep0_cycle;
	uint32_t slot, port, speed;
	uint32_t last_cc, last_len, events;
	struct uh_dev dev;
	bool host;
} uh;

static inline volatile uint32_t *uh_m32(uint32_t off) { return (volatile uint32_t *)(uh_mem.va + off); }
static inline uint64_t uh_pa(uint32_t off) { return uh_mem.pa + off; }
static inline uint32_t uh_op_rd(uint32_t off) { return uh_rd(uh.op + off); }
static inline void uh_op_wr(uint32_t off, uint32_t v) { uh_wr(uh.op + off, v); }
static inline void uh_rt_wr(uint32_t off, uint32_t v) { uh_wr(uh.rt + off, v); }

static void
uh_zero(uint32_t off, uint32_t bytes)
{
	for (uint32_t i = 0; i < bytes; i += 4) {
		*uh_m32(off + i) = 0;
	}
}

static void
uh_trb_put(uint32_t off, uint64_t param, uint32_t status, uint32_t control)
{
	*uh_m32(off + 0) = (uint32_t)param;
	*uh_m32(off + 4) = (uint32_t)(param >> 32);
	*uh_m32(off + 8) = status;
	uh_dsb();
	*uh_m32(off + 12) = control;    /* the cycle bit last: the TRB is the controller's from here */
	uh_dsb();
}

static const char *
uh_speed_name(uint32_t speed)
{
	switch (speed) {
	case 1: return "full";
	case 2: return "low";
	case 3: return "high";
	case 4: return "super";
	default: return "unknown";
	}
}

static uint32_t
uh_mps0(uint32_t speed)
{
	return speed == 2 ? 8u : speed == 4 ? 512u : 64u;   /* Linux xhci_setup_addressable_virt_dev; FS starts at 64 */
}

/* --------------------------------------------------------------------------------------------- read-only survey */

/* The DP alt-mode map's first data point and the role switch's baseline. Every block read here is in usb_top_pd,
 * which is on whenever the gadget is (FDT usb_phy power-domains 0x4c0 = the wrapper's usb_top_pd). */
static void
uh_survey(void)
{
	UH_SAY("blazer-usbhost: survey GSNPSID %x GCTL %x DCTL %x DSTS %x GUSB2PHYCFG %x\n",
	    uh_rd(UH_GSNPSID), uh_rd(UH_GCTL), uh_rd(UH_DCTL), uh_rd(UH_DSTS), uh_rd(UH_GUSB2PHYCFG));
	/* GFLADJ: the FDT's snps,quirk-frame-length-adjustment = 0xa0 is the host's SOF timing, which Linux writes and this
	 * file does not (the next variable if a device misbehaves). Glue HC_STATUS [1:0]/[4:3]: U2/U3 PMU power state
	 * (dwc3-google.c; 0 = D0); HOST_CFG1 [5:4] the requested state. */
	UH_SAY("blazer-usbhost: survey GHWPARAMS0 %x GUCTL %x GFLADJ %x glue hc_status %x host_cfg1 %x\n",
	    uh_rd(UH_GHWPARAMS0), uh_rd(UH_GUCTL), uh_rd(UH_GFLADJ), uh_glue_rd(0x0), uh_glue_rd(0x4));
	/* TCA (Synopsys Type-C assist in the USB/DP combo PHY): CLK_RST 0x0, INTR_STS 0x8, GCFG 0x10, TCPC 0x14
	 * ([2:0] mux: 0 none, 1 USB, 2 DP, 3 USB+DP; [3] orientation; [4] valid), PSTATE 0x50..0x58. */
	UH_SAY("blazer-usbhost: survey TCA clk_rst %x intr_sts %x gcfg %x tcpc %x pstate %x %x %x\n",
	    uh_tca_rd(0x00), uh_tca_rd(0x08), uh_tca_rd(0x10), uh_tca_rd(0x14), uh_tca_rd(0x50), uh_tca_rd(0x54), uh_tca_rd(0x58));
	/* dp_top_csr USBCS_PHY_CFG1 0x28 ([16] typec_flip_invert, [17] sys_vbusvalid: Google sets it 1 for device, 0 for host),
	 * CFG2 0x2c ([16] phy_lane0_power_present, same rule), DP_CONFIG 0x10, AUX_CTRL 0x24. */
	UH_SAY("blazer-usbhost: survey dp_top cfg1 %x cfg2 %x dp_config %x aux_ctrl %x\n",
	    uh_dptop_rd(0x28), uh_dptop_rd(0x2c), uh_dptop_rd(0x10), uh_dptop_rd(0x24));
}

/* ------------------------------------------------------------------------------------------------ role switch */

/* Off the bus as a device, then core soft reset into host. Linux __dwc3_set_mode's order for DWC_usb31 before 1.90a:
 * gadget exit, event buffers cleaned up, GCTL.CORESOFTRESET for 100 ms, PRTCAPDIR = host. REFUSED writes nothing. */
static enum uh_why
uh_to_host(void)
{
	uint32_t id = uh_rd(UH_GSNPSID), gctl = uh_rd(UH_GCTL), ms;
	bool halted = false;

	if (id != UH_EXPECT_ID || (gctl & UH_GCTL_PRTCAPDIR) != UH_GCTL_PRTCAP_DEVICE) {
		UH_SAY("blazer-usbhost: refused, GSNPSID %x GCTL %x (expected %x, device mode)\n", id, gctl, UH_EXPECT_ID);
		return UH_REFUSED;
	}
	uh_wr(UH_DCTL, uh_rd(UH_DCTL) & ~UH_DCTL_RUN_STOP);
	for (ms = 0; ms < UH_HALT_MS; ms++) {
		uint32_t pending = uh_rd(UH_GEVNTCOUNT) & 0xfffc;
		if (pending) {
			uh_wr(UH_GEVNTCOUNT, pending);
		}
		if (uh_rd(UH_DSTS) & UH_DSTS_DEVCTRLHLT) {
			halted = true;
			break;
		}
		uh_sleep_ms(1);
	}
	UH_SAY("blazer-usbhost: gadget %s %u ms\n", halted ? "halted in" : "no halt after", ms);
	if (!halted) {
		/* The shim's gadget may still own its arena's DMA. Do not reset under it. Nothing else was written. */
		return UH_GADGET_STUCK;
	}
	/* Linux dwc3_event_buffers_cleanup: no more device events into the shim's arena. */
	uh_wr(UH_DEVTEN, 0);
	uh_wr(UH_GEVNTSIZ, 1u << 31);
	uh_wr(UH_GEVNTADRLO, 0);
	uh_wr(UH_GEVNTADRHI, 0);
	uh_wr(UH_GEVNTCOUNT, uh_rd(UH_GEVNTCOUNT) & 0xfffc);
	/* DRD controllers: SUSPHY off during a mode switch (Linux dwc3_set_prtcap). USB2 only, as blazer_usbcon. */
	uh_wr(UH_GUSB2PHYCFG, uh_rd(UH_GUSB2PHYCFG) & ~UH_SUSPHY);
	uh_wr(UH_GCTL, uh_rd(UH_GCTL) | UH_GCTL_CORESOFTRESET);
	uh_sleep_ms(UH_SOFTRESET_MS);
	uh_wr(UH_GCTL, uh_rd(UH_GCTL) & ~UH_GCTL_CORESOFTRESET);
	if (uh_rd(UH_GCTL) & UH_GCTL_CORESOFTRESET) {
		UH_SAY("blazer-usbhost: core soft reset stuck, GCTL %x\n", uh_rd(UH_GCTL));
		return UH_SOFTRESET_STUCK;
	}
	uh_wr(UH_GCTL, (uh_rd(UH_GCTL) & ~UH_GCTL_PRTCAPDIR) | UH_GCTL_PRTCAP_HOST);
	gctl = uh_rd(UH_GCTL);
	uh.host = true;         /* from here the controller is not the gadget the stamps described */
	UH_SAY("blazer-usbhost: host mode, GCTL %x, glue hc_status %x host_cfg1 %x\n", gctl, uh_glue_rd(0x0), uh_glue_rd(0x4));
	return (gctl & UH_GCTL_PRTCAPDIR) == UH_GCTL_PRTCAP_HOST ? UH_OK : UH_NOT_HOST;
}

/* ------------------------------------------------------------------------------------------------- xHCI bring-up */

static bool
uh_wait_sts(uint32_t mask, uint32_t want, unsigned ms_max)
{
	for (unsigned ms = 0; ms <= ms_max; ms++) {
		if ((uh_op_rd(XO_USBSTS) & mask) == want) {
			return true;
		}
		uh_sleep_ms(1);
	}
	return false;
}

/* Supported Protocol capabilities (xHCI 7.2): which root ports are USB2 and which USB3. */
static void
uh_protocols(void)
{
	uint32_t off = (uh.hcc1 >> 16) << 2;

	for (unsigned n = 0; off != 0 && off < 0x8000u && n < 32; n++) {
		uint32_t d0 = uh_rd(off);
		if ((d0 & 0xffu) == 2u) {
			uint32_t d2 = uh_rd(off + 8), first = d2 & 0xffu, count = (d2 >> 8) & 0xffu, major = d0 >> 24;
			if (major == 2u && uh.u2_count == 0) {
				uh.u2_first = first;
				uh.u2_count = count;
			} else if (major == 3u && uh.u3_count == 0) {
				uh.u3_first = first;
				uh.u3_count = count;
			}
		}
		if (((d0 >> 8) & 0xffu) == 0) {
			break;
		}
		off += ((d0 >> 8) & 0xffu) << 2;
	}
}

static enum uh_why
uh_xhci_start(void)
{
	uint32_t v = uh_rd(XC_CAPLENGTH);

	uh.caplen = v & 0xffu;
	uh.hciversion = v >> 16;
	uh.hcs1 = uh_rd(XC_HCSPARAMS1);
	uh.hcs2 = uh_rd(XC_HCSPARAMS2);
	uh.hcc1 = uh_rd(XC_HCCPARAMS1);
	uh.db = uh_rd(XC_DBOFF) & ~3u;
	uh.rt = uh_rd(XC_RTSOFF) & ~0x1fu;
	uh.op = uh.caplen;
	uh.slots = uh.hcs1 & 0xffu;
	uh.ports = uh.hcs1 >> 24;
	uh.scratch = (((uh.hcs2 >> 21) & 0x1fu) << 5) | (uh.hcs2 >> 27);
	uh.csz = (uh.hcc1 & (1u << 2)) ? 64u : 32u;
	uh_protocols();
	UH_SAY("blazer-usbhost: xhci %x caplen %u slots %u ports %u scratch %u csz %u ac64 %u ppc %u db %x rt %x\n",
	    uh.hciversion, uh.caplen, uh.slots, uh.ports, uh.scratch, uh.csz, uh.hcc1 & 1u, (uh.hcc1 >> 3) & 1u, uh.db, uh.rt);
	UH_SAY("blazer-usbhost: root ports usb2 %u+%u usb3 %u+%u\n", uh.u2_first, uh.u2_count, uh.u3_first, uh.u3_count);
	if (uh.caplen < 0x20u || uh.caplen > 0x80u || uh.hciversion < 0x100u || uh.slots == 0 || uh.ports == 0 ||
	    uh.db < 0x100u || uh.db >= 0x8000u || uh.rt < 0x100u || uh.rt >= 0x8000u) {
		return UH_BAD_XHCI;
	}
	if (uh.u2_count == 0 || uh.u2_first == 0 || uh.u2_first + uh.u2_count - 1u > uh.ports) {
		return UH_NO_USB2;
	}
	if (uh.scratch > UH_SCRATCH_MAX) {
		return UH_SCRATCH;
	}
	if (!uh_wait_sts(USBSTS_CNR, 0, UH_CNR_MS)) {
		return UH_CNR;
	}
	uh_op_wr(XO_USBCMD, uh_op_rd(XO_USBCMD) & ~USBCMD_RS);
	(void)uh_wait_sts(USBSTS_HCH, USBSTS_HCH, UH_RUN_MS);
	uh_op_wr(XO_USBCMD, USBCMD_HCRST);
	for (unsigned ms = 0; (uh_op_rd(XO_USBCMD) & USBCMD_HCRST) != 0; ms++) {
		if (ms >= UH_HCRST_MS) {
			return UH_HCRST;
		}
		uh_sleep_ms(1);
	}
	if (!uh_wait_sts(USBSTS_CNR, 0, UH_CNR_MS)) {
		return UH_CNR;
	}

	uh_zero(0, UH_ARENA_BYTES);
	/* Scratchpad: DCBAA[0] -> array of page pointers (xHCI 4.20). */
	for (uint32_t i = 0; i < uh.scratch; i++) {
		uint64_t page = uh_pa(UA_SCRATCH_PAGES + i * 0x1000u);
		*uh_m32(UA_SCRATCH_ARRAY + i * 8) = (uint32_t)page;
		*uh_m32(UA_SCRATCH_ARRAY + i * 8 + 4) = (uint32_t)(page >> 32);
	}
	if (uh.scratch) {
		*uh_m32(UA_DCBAA) = (uint32_t)uh_pa(UA_SCRATCH_ARRAY);
		*uh_m32(UA_DCBAA + 4) = (uint32_t)(uh_pa(UA_SCRATCH_ARRAY) >> 32);
	}
	/* Command ring: link TRB back to the start, toggle cycle. */
	uh.cmd_enq = 0;
	uh.cmd_cycle = 1;
	uh_trb_put(UA_CMD_RING + (UH_CMD_TRBS - 1u) * 16u, uh_pa(UA_CMD_RING), 0, TRB_TYPE(TRB_LINK) | TRB_TC);
	/* Event ring, one segment. */
	uh.evt_deq = 0;
	uh.evt_cycle = 1;
	*uh_m32(UA_ERST + 0) = (uint32_t)uh_pa(UA_EVT_RING);
	*uh_m32(UA_ERST + 4) = (uint32_t)(uh_pa(UA_EVT_RING) >> 32);
	*uh_m32(UA_ERST + 8) = UH_EVT_TRBS;
	uh_dsb();

	uh_op_wr(XO_CONFIG, (uh_op_rd(XO_CONFIG) & ~0xffu) | (uh.slots < UH_MAX_SLOTS ? uh.slots : UH_MAX_SLOTS));
	uh_op_wr(XO_DCBAAP_LO, (uint32_t)uh_pa(UA_DCBAA));
	uh_op_wr(XO_DCBAAP_HI, (uint32_t)(uh_pa(UA_DCBAA) >> 32));
	uh_op_wr(XO_CRCR_LO, (uint32_t)uh_pa(UA_CMD_RING) | 1u);    /* RCS = 1 */
	uh_op_wr(XO_CRCR_HI, (uint32_t)(uh_pa(UA_CMD_RING) >> 32));
	uh_rt_wr(XR_ERSTSZ, 1);
	uh_rt_wr(XR_ERDP_LO, (uint32_t)uh_pa(UA_EVT_RING));
	uh_rt_wr(XR_ERDP_HI, (uint32_t)(uh_pa(UA_EVT_RING) >> 32));
	uh_rt_wr(XR_ERSTBA_LO, (uint32_t)uh_pa(UA_ERST));
	uh_rt_wr(XR_ERSTBA_HI, (uint32_t)(uh_pa(UA_ERST) >> 32));
	uh_rt_wr(XR_IMAN, 1u);          /* clear IP; IE stays 0: this host polls */
	uh_op_wr(XO_USBCMD, USBCMD_RS); /* INTE 0, HSEE 0 */
	if (!uh_wait_sts(USBSTS_HCH, 0, UH_RUN_MS)) {
		return UH_NO_RUN;
	}
	UH_SAY("blazer-usbhost: running, USBSTS %x\n", uh_op_rd(XO_USBSTS));
	return UH_OK;
}

/* ------------------------------------------------------------------------------------------------ rings, events */

/* One event, or false after ms. Port status change events are counted and dropped here. */
static bool
uh_event(uint32_t want_type, uint32_t *param_lo, uint32_t *status, uint32_t *control, unsigned ms_max)
{
	for (unsigned ms = 0; ms <= ms_max;) {
		uint32_t off = UA_EVT_RING + uh.evt_deq * 16u;
		uint32_t c = *uh_m32(off + 12);
		if ((c & TRB_CYCLE) != uh.evt_cycle) {
			uint32_t sts = uh_op_rd(XO_USBSTS);
			if (sts & (USBSTS_HSE | USBSTS_HCE)) {
				UH_SAY("blazer-usbhost: host error, USBSTS %x\n", sts);
				return false;
			}
			uh_sleep_ms(1);
			ms++;
			continue;
		}
		uint32_t p = *uh_m32(off), s = *uh_m32(off + 8);
		uh.events++;
		if (++uh.evt_deq == UH_EVT_TRBS) {
			uh.evt_deq = 0;
			uh.evt_cycle ^= 1u;
		}
		uh_rt_wr(XR_ERDP_LO, (uint32_t)uh_pa(UA_EVT_RING + uh.evt_deq * 16u) | (1u << 3));   /* EHB: write 1 to clear */
		uh_rt_wr(XR_ERDP_HI, (uint32_t)(uh_pa(UA_EVT_RING) >> 32));
		if (TRB_TYPE_OF(c) == want_type) {
			*param_lo = p;
			*status = s;
			*control = c;
			return true;
		}
	}
	return false;
}

static enum uh_why
uh_command(uint64_t param, uint32_t control, uint32_t *slot_out)
{
	uint32_t off = UA_CMD_RING + uh.cmd_enq * 16u, p, s, c;
	uint64_t trb_pa = uh_pa(off);

	uh_trb_put(off, param, 0, control | uh.cmd_cycle);
	if (++uh.cmd_enq == UH_CMD_TRBS - 1u) {
		/* Hand the link TRB over with the current cycle, then toggle. */
		uint32_t link = UA_CMD_RING + (UH_CMD_TRBS - 1u) * 16u;
		*uh_m32(link + 12) = TRB_TYPE(TRB_LINK) | TRB_TC | uh.cmd_cycle;
		uh_dsb();
		uh.cmd_enq = 0;
		uh.cmd_cycle ^= 1u;
	}
	uh_wr(uh.db, 0);        /* host controller doorbell, target 0 */
	for (;;) {
		if (!uh_event(TRB_EV_COMMAND, &p, &s, &c, UH_CMD_MS)) {
			return UH_CMD_TIMEOUT;
		}
		if (p == (uint32_t)trb_pa) {
			break;
		}
	}
	uh.last_cc = s >> 24;
	if (slot_out) {
		*slot_out = c >> 24;
	}
	return uh.last_cc == CC_SUCCESS ? UH_OK : UH_CMD_FAILED;
}

static void
uh_ep0_put(uint64_t param, uint32_t status, uint32_t control)
{
	uh_trb_put(UA_EP0_RING + uh.ep0_enq * 16u, param, status, control | uh.ep0_cycle);
	if (++uh.ep0_enq == UH_EP0_TRBS - 1u) {
		uint32_t link = UA_EP0_RING + (UH_EP0_TRBS - 1u) * 16u;
		uh_trb_put(link, uh_pa(UA_EP0_RING), 0, TRB_TYPE(TRB_LINK) | TRB_TC | uh.ep0_cycle);
		uh.ep0_enq = 0;
		uh.ep0_cycle ^= 1u;
	}
}

/* A control IN transfer on EP0: SETUP, DATA (IN), STATUS (OUT, IOC). */
static enum uh_why
uh_control_in(uint8_t request_type, uint8_t request, uint16_t value, uint16_t index, uint16_t length, uint32_t buf_off)
{
	uint32_t p, s, c;
	uint64_t setup = (uint64_t)request_type | ((uint64_t)request << 8) | ((uint64_t)value << 16) |
	    ((uint64_t)index << 32) | ((uint64_t)length << 48);

	uh_zero(buf_off, (length + 3u) & ~3u);
	uh_ep0_put(setup, 8, TRB_TYPE(TRB_SETUP) | TRB_IDT | TRB_TRT_IN);
	uh_ep0_put(uh_pa(buf_off), length, TRB_TYPE(TRB_DATA) | TRB_DIR_IN);
	uh_ep0_put(0, 0, TRB_TYPE(TRB_STATUS) | TRB_IOC);
	uh_wr(uh.db + 4u * uh.slot, 1);         /* device slot doorbell, DCI 1 = EP0 */
	for (;;) {
		if (!uh_event(TRB_EV_TRANSFER, &p, &s, &c, UH_XFER_MS)) {
			return UH_XFER_TIMEOUT;
		}
		if ((c >> 24) == uh.slot) {
			break;
		}
	}
	uh.last_cc = s >> 24;
	uh.last_len = s & 0xffffffu;
	return uh.last_cc == CC_SUCCESS || uh.last_cc == CC_SHORT_PACKET ? UH_OK : UH_XFER_FAILED;
}

static inline uint8_t uh_b(uint32_t off) { return *(volatile uint8_t *)(uh_mem.va + off); }

/* ------------------------------------------------------------------------------------------------- one device */

static enum uh_why
uh_port_reset(uint32_t port)
{
	uint32_t v = uh_op_rd(XO_PORTSC(port));

	uh_op_wr(XO_PORTSC(port), PORTSC_NEUTRAL(v) | PORTSC_CSC | PORTSC_PR);  /* also acks the connect change */
	for (unsigned ms = 0; ms <= UH_PORT_RESET_MS; ms++) {
		v = uh_op_rd(XO_PORTSC(port));
		if ((v & PORTSC_PRC) && !(v & PORTSC_PR)) {
			uh_op_wr(XO_PORTSC(port), PORTSC_NEUTRAL(v) | PORTSC_PRC);
			UH_SAY("blazer-usbhost: port %u reset done, enabled %u, speed %s, PORTSC %x\n", port,
			    (v & PORTSC_PED) ? 1u : 0u, uh_speed_name(PORTSC_SPEED(v)), v);
			uh.speed = PORTSC_SPEED(v);
			return (v & PORTSC_PED) && (v & PORTSC_CCS) ? UH_OK : UH_PORT_RESET;
		}
		uh_sleep_ms(1);
	}
	UH_SAY("blazer-usbhost: port %u reset timeout, PORTSC %x\n", port, v);
	return UH_PORT_RESET;
}

static enum uh_why
uh_address(uint32_t port)
{
	uint32_t cs = uh.csz, ic = UA_INPUT_CTX;
	enum uh_why why = uh_command(0, TRB_TYPE(TRB_ENABLE_SLOT), &uh.slot);

	if (why != UH_OK) {
		UH_SAY("blazer-usbhost: enable slot: %s, cc %u\n", uh_why_name[why], uh.last_cc);
		return why;
	}
	if (uh.slot == 0 || uh.slot > UH_MAX_SLOTS) {
		UH_SAY("blazer-usbhost: enable slot gave slot %u\n", uh.slot);
		return UH_CMD_FAILED;
	}
	uh_zero(UA_INPUT_CTX, 33u * 64u);
	uh_zero(UA_DEV_CTX, 32u * 64u);
	uh_zero(UA_EP0_RING, UH_EP0_TRBS * 16u);
	uh.ep0_enq = 0;
	uh.ep0_cycle = 1;
	*uh_m32(ic + 4) = 0x3u;                                                 /* add A0 (slot), A1 (EP0) */
	*uh_m32(ic + cs + 0) = (uh.speed << 20) | (1u << 27);                   /* route 0, speed, context entries 1 */
	*uh_m32(ic + cs + 4) = port << 16;                                      /* root hub port number */
	*uh_m32(ic + 2u * cs + 4) = (3u << 1) | (4u << 3) | (uh_mps0(uh.speed) << 16);   /* CErr 3, control EP, MPS */
	*uh_m32(ic + 2u * cs + 8) = (uint32_t)uh_pa(UA_EP0_RING) | 1u;          /* TR dequeue, DCS 1 */
	*uh_m32(ic + 2u * cs + 12) = (uint32_t)(uh_pa(UA_EP0_RING) >> 32);
	*uh_m32(ic + 2u * cs + 16) = 8u;                                        /* average TRB length */
	*uh_m32(UA_DCBAA + uh.slot * 8u) = (uint32_t)uh_pa(UA_DEV_CTX);
	*uh_m32(UA_DCBAA + uh.slot * 8u + 4) = (uint32_t)(uh_pa(UA_DEV_CTX) >> 32);
	uh_dsb();
	why = uh_command(uh_pa(UA_INPUT_CTX), TRB_TYPE(TRB_ADDRESS_DEVICE) | (uh.slot << 24), NULL);
	/* Device context slot state [31:27] of dword 3, USB address [7:0]. */
	UH_SAY("blazer-usbhost: slot %u address device: %s, cc %u, address %u\n", uh.slot, uh_why_name[why], uh.last_cc,
	    *uh_m32(UA_DEV_CTX + 12) & 0xffu);
	return why;
}

static void
uh_string(uint8_t index)
{
	uint32_t n;

	uh.dev.product[0] = 0;
	if (index == 0 || uh_control_in(0x80, 6, (uint16_t)(0x0300u | index), 0x0409, 255, UA_STRING) != UH_OK) {
		return;
	}
	n = uh_b(UA_STRING);
	if (uh_b(UA_STRING + 1) != 3 || n < 2) {
		return;
	}
	uint32_t o = 0;
	for (uint32_t i = 2; i + 1 < n && o + 1 < sizeof(uh.dev.product); i += 2) {
		uint8_t lo = uh_b(UA_STRING + i), hi = uh_b(UA_STRING + i + 1);
		uh.dev.product[o++] = (hi == 0 && lo >= 0x20 && lo < 0x7f && lo != '"') ? (char)lo : '?';
	}
	uh.dev.product[o] = 0;
}

/* Full speed: EP0 was addressed with 64; a device with 8, 16 or 32 would end an 18-byte read after its first packet.
 * Read 8 bytes, and if bMaxPacketSize0 differs, Evaluate Context with the right one (Linux usb_ep0_reinit order). */
static enum uh_why
uh_fix_mps0(void)
{
	uint32_t cs = uh.csz, ic = UA_INPUT_CTX, mps;
	enum uh_why why;

	if (uh.speed != 1) {
		return UH_OK;
	}
	why = uh_control_in(0x80, 6, 0x0100, 0, 8, UA_DESC);
	if (why != UH_OK) {
		UH_SAY("blazer-usbhost: first 8 bytes: %s, cc %u\n", uh_why_name[why], uh.last_cc);
		return why;
	}
	mps = uh_b(UA_DESC + 7);
	if (mps != 8 && mps != 16 && mps != 32 && mps != 64) {
		UH_SAY("blazer-usbhost: bMaxPacketSize0 %u\n", mps);
		return UH_BAD_DESC;
	}
	if (mps == 64) {
		return UH_OK;
	}
	uh_zero(UA_INPUT_CTX, 33u * 64u);
	*uh_m32(ic + 4) = 0x2u;                                                 /* add A1 (EP0) */
	*uh_m32(ic + 2u * cs + 4) = (3u << 1) | (4u << 3) | (mps << 16);
	why = uh_command(uh_pa(UA_INPUT_CTX), TRB_TYPE(TRB_EVALUATE_CONTEXT) | (uh.slot << 24), NULL);
	UH_SAY("blazer-usbhost: ep0 max packet %u: %s, cc %u\n", mps, uh_why_name[why], uh.last_cc);
	return why;
}

static enum uh_why
uh_describe(uint32_t port)
{
	enum uh_why why = uh_fix_mps0();
	struct uh_dev *d = &uh.dev;

	if (why == UH_OK) {
		why = uh_control_in(0x80, 6, 0x0100, 0, 18, UA_DESC);           /* GET_DESCRIPTOR(DEVICE) */
	}

	if (why != UH_OK) {
		UH_SAY("blazer-usbhost: device descriptor: %s, cc %u\n", uh_why_name[why], uh.last_cc);
		return why;
	}
	if (uh_b(UA_DESC) < 18 || uh_b(UA_DESC + 1) != 1) {
		UH_SAY("blazer-usbhost: device descriptor bad, length %u type %u\n", uh_b(UA_DESC), uh_b(UA_DESC + 1));
		return UH_BAD_DESC;
	}
	d->bcd_usb = (uint16_t)(uh_b(UA_DESC + 2) | uh_b(UA_DESC + 3) << 8);
	d->class = uh_b(UA_DESC + 4);
	d->subclass = uh_b(UA_DESC + 5);
	d->protocol = uh_b(UA_DESC + 6);
	d->mps0 = uh_b(UA_DESC + 7);
	d->vid = (uint16_t)(uh_b(UA_DESC + 8) | uh_b(UA_DESC + 9) << 8);
	d->pid = (uint16_t)(uh_b(UA_DESC + 10) | uh_b(UA_DESC + 11) << 8);
	d->configs = uh_b(UA_DESC + 17);
	uint8_t iproduct = uh_b(UA_DESC + 15);
	UH_SAY("blazer-usbhost: ENUM port %u speed %s dev %04x:%04x usb %x.%02x class %02x/%02x/%02x mps0 %u configs %u\n",
	    port, uh_speed_name(uh.speed), d->vid, d->pid, d->bcd_usb >> 8, d->bcd_usb & 0xffu, d->class, d->subclass,
	    d->protocol, d->mps0, d->configs);

	/* Configuration 0's first interface, so a class-0 device still says what it is. Not fatal. */
	if (uh_control_in(0x80, 6, 0x0200, 0, UH_DESC_BYTES - 1u, UA_DESC) == UH_OK && uh_b(UA_DESC + 1) == 2) {
		uint32_t total = uh_b(UA_DESC + 2) | (uint32_t)uh_b(UA_DESC + 3) << 8;
		d->interfaces = uh_b(UA_DESC + 4);
		if (total > UH_DESC_BYTES - 1u) {
			total = UH_DESC_BYTES - 1u;
		}
		for (uint32_t o = uh_b(UA_DESC); o + 9 <= total && uh_b(UA_DESC + o) >= 2;) {
			if (uh_b(UA_DESC + o + 1) == 4) {
				d->iface_class = uh_b(UA_DESC + o + 5);
				d->iface_subclass = uh_b(UA_DESC + o + 6);
				d->iface_protocol = uh_b(UA_DESC + o + 7);
				UH_SAY("blazer-usbhost: ENUM port %u interfaces %u, first %02x/%02x/%02x, config bytes %u\n", port,
				    d->interfaces, d->iface_class, d->iface_subclass, d->iface_protocol, total);
				break;
			}
			o += uh_b(UA_DESC + o);
		}
	}
	uh_string(iproduct);
	if (uh.dev.product[0]) {
		UH_SAY("blazer-usbhost: ENUM port %u product \"%s\"\n", port, uh.dev.product);
	}
	return UH_OK;
}

/* Power the USB2 root ports only, wait for one connect, enumerate it. window_s bounds the wait. */
static enum uh_why
uh_enumerate(unsigned window_s)
{
	uint64_t t0 = uh_ticks(), last_say = t0;

	if (uh.hcc1 & (1u << 3)) {      /* PPC: ports start unpowered */
		for (uint32_t i = 0; i < uh.u2_count; i++) {
			uint32_t port = uh.u2_first + i, v = uh_op_rd(XO_PORTSC(port));
			uh_op_wr(XO_PORTSC(port), PORTSC_NEUTRAL(v) | PORTSC_PP);
		}
	}
	uh_sleep_ms(UH_POWER_SETTLE_MS);
	for (uint32_t i = 0; i < uh.u2_count; i++) {
		UH_SAY("blazer-usbhost: usb2 port %u PORTSC %x\n", uh.u2_first + i, uh_op_rd(XO_PORTSC(uh.u2_first + i)));
	}
	for (;;) {
		for (uint32_t i = 0; i < uh.u2_count; i++) {
			uint32_t port = uh.u2_first + i, v = uh_op_rd(XO_PORTSC(port));
			if (!(v & PORTSC_CCS)) {
				continue;
			}
			UH_SAY("blazer-usbhost: port %u connect after %u ms, PORTSC %x\n", port,
			    (unsigned)((uh_ticks() - t0) * 1000u / uh_hz()), v);
			uh_sleep_ms(UH_POWER_SETTLE_MS);        /* USB 2.0 7.1.7.3: 100 ms attach debounce before reset */
			enum uh_why why = uh_port_reset(port);
			if (why == UH_OK) {
				why = uh_address(port);
			}
			if (why == UH_OK) {
				why = uh_describe(port);
			}
			uh.port = port;
			return why;
		}
		uint64_t now = uh_ticks();
		if (now - t0 >= (uint64_t)window_s * uh_hz()) {
			break;
		}
		if (now - last_say >= 30u * uh_hz()) {
			last_say = now;
			UH_SAY("blazer-usbhost: waiting for a device, %u s, port %u PORTSC %x\n",
			    (unsigned)((now - t0) / uh_hz()), uh.u2_first, uh_op_rd(XO_PORTSC(uh.u2_first)));
		}
		uh_sleep_ms(UH_POLL_MS);
	}
	for (uint32_t i = 0; i < uh.u2_count; i++) {
		UH_SAY("blazer-usbhost: no device in %u s, port %u PORTSC %x\n", window_s, uh.u2_first + i,
		    uh_op_rd(XO_PORTSC(uh.u2_first + i)));
	}
	return UH_NO_DEVICE;
}

/* The whole run. Returns the first failure. Each failure has said its line. After a failure past uh_to_host the
 * controller stays in host mode: only the warm reset at the end of the boot (deadline panic) gives it back. */
static enum uh_why
uh_run(unsigned window_s)
{
	enum uh_why why;

	uh_survey();
	why = uh_to_host();
	if (why == UH_OK) {
		why = uh_xhci_start();
	}
	if (why == UH_OK) {
		why = uh_enumerate(window_s);
	}
	if (why == UH_OK) {
		UH_SAY("blazer-usbhost: PASS, port %u enumerated %04x:%04x, events %u, controller left in host mode until the end of the boot\n",
		    uh.port, uh.dev.vid, uh.dev.pid, uh.events);
	} else {
		UH_SAY("blazer-usbhost: stop: %s, events %u, controller %s\n", uh_why_name[why], uh.events,
		    uh.host ? "left in host mode until the end of the boot" : "untouched");
	}
	return why;
}
