#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * BCM4390 from the host's side: what comes after the PCI ID, up to firmware running with nothing talking to it yet. Own code; the order and values are stock's, read from Broadcom's DHD (GPL, facts only).
 * Sources: pixel10-aosp bcm4390/dhd_pcie.c, nciutils.c, dhd_custom_cis.c, bcmutils.c; GrapheneOS kernel_pixel_6.12@5940a317 for offsets. Literals: research/ios26-wifi-r1/tools/check_literals.py.
 *
 * Physical facts it stands on, Android on this phone, laguna-usb-fix/attempts 20261027-112139-loop and 20261027-191323-v63:
 *   BAR 0 0x60800000 64 KiB, BAR 2 0x60400000 4 MiB, BAR 4 0x60300000 1 MiB. Chip 0x4390 rev 5, PCIe core rev 133.
 *   5.9098 ASR workaround, CTO 0x8a058000, attach. FISCtrlStatus 0. "sysmem core is already up".
 *   5.9748 FLR, 79 ms. 6.1427 "config space 0x88 is 0x80080", FLR, 79 ms. 6.2214 ASR workaround and CTO again. 6.2301 "Using SINGLE image (size 2525692)".
 *   "ARM is out of reset and already in HALT". RAM 3276800 at 0x2a0000. "New varsize is 18268, length token(nvram_csm)=0xee2811d7". Seed "size 128, addr 5bb818".
 *   "FWSIG: bl=,0 fw=2a0000,2525692 sig=,0,0 stat=0,0 ram=2a0000,5bb818". 6.7343 "Took ARM out of HALT". 912 ms later "shared addr=0x5ae000". "FWSIG: Plain FW loaded".
 * The host test checks this file reaches those same numbers from the real NVRAM.
 *
 * Physical on iOS, 20261102-021907-wifi-stage2-r1: firmware's top word 0x48c2b0 35 ms after release, flags 0x109, IPC version 9, FWID right, console and ring pointers still 0 at 335 ms. So the first word it writes isn't ready.
 * dhd_pcie.c says why, "EWP new init sequence": firmware publishes a shared area, does wl up, collects its dumps, wl down, and only then rings the host. Android waits for that doorbell, which is its 912 ms.
 *
 * What it can do to the chip is bounded in blazer_pcie1.c: write_allowed and value_ok. Nothing here reaches BT's side: BAR 4 is assigned but never accessed, its window stays 0, BT_REG_ON is on the PMIC and is no business of this file. */
#include "blazer_hw_port.h"
#include "blazer_pcie1.h"

#define CFG_PA          0x60000000ULL   /* blazer_pcie1.c's CFG */
#define DBI_PA          0x3c800000ULL
#define ATU_PA          0x3cb00000ULL

/* The endpoint's config registers: pcicfg.h */
#define C_COMMAND       0x04u
#define  CMD_MEMORY     0x02u
#define  CMD_MASTER     0x04u           /* Stock has it on from before the load. The chip gets a host address only from blazer_bcm4390_ring.c */
#define  CMD_INTX_OFF   0x400u          /* As pci_enable_msi leaves it. Nothing here takes an interrupt */
#define C_BAR0_LO       0x10u
#define C_BAR0_HI       0x14u
#define C_BAR2_LO       0x18u
#define C_BAR2_HI       0x1cu
#define C_BAR4_LO       0x20u
#define C_BAR4_HI       0x24u
#define C_SSCTRL        0x88u
#define  SS_RESET_STATUS (1u << 13)     /* PCIE_SSRESET_STATUS_BIT */
#define  SS_COHERENT    0x300u          /* PCIE_BARCOHERENTACCEN_MASK: "CA7 requires coherent bits on" */
#define  SS_BP_ENABLE   0x800c0u        /* PCIE_SUBSYS_CTRL_BPACCESS_ENABLE */
#define  SS_BP_DISABLE  0x80080u
#define C_INT_STATUS    0x90u
#define C_INT_MASK      0x94u
#define  INT_CTO_SERR   ((1u << 16) | 4u)
#define C_DEV_CAP       0xb0u
#define  DEV_CAP_FLR    (1u << 28)
#define C_DEV_CTRL      0xb4u
#define  DEV_CTRL_FLR   (1u << 15)
#define C_PTM_CTRL      0x208u

/* The PCIe core's registers, in BAR 0 */
#define P_CTO           0x03cu          /* cpl_to_ctrl */
#define  CTO_VALUE      0x8a058000u     /* Physical: this exact value in Android's log */
#define P_IND_ADDR      0x120u
#define P_IND_DATA      0x124u
#define P_POWER_CTRL    0x1e8u          /* si_srpwr_request's register, as the PCIe core shows it */
#define  PWR_REQ_DMN0   (1u << 8)       /* SRPWR_DMN0_PCIE << SRPWR_REQON_SHIFT */
#define  PWR_REQ_DMN1   (1u << 9)       /* SRPWR_DMN1_ARMBPSD: ARM and the WL backplane */
#define  PWR_ST_DMN1    (1u << 17)      /* << SRPWR_STATUS_SHIFT */
#define  PWR_POLLS      200u
#define  PWR_POLL_US    100u
#define P_MBOX_INT      0xc30u          /* mailboxint: raw status, write 1 to clear */
#define P_MBOX_MASK     0xc34u
#define  MBOX_D2H       0xffffu         /* PCIE_MB_D2H_MB_MASK at rev >= 64 */
#define P_DAR_CLK       0xa08u
#define P_DAR_PWR       0xa0cu
#define P_DAR_ERRLOG    0xa60u
#define P_DAR_ERRADDR   0xa64u
#define P_DAR_MBINT     0xa68u
#define P_DAR_SEC       0xa74u
#define  SEC_SBOOT      0x2u            /* DAR_SEC_SBOOT_MASK */
#define BP_BAR1_WAR     0x4e0u          /* "WAR where the BAR1 window may not be sized properly" */

/* Backplane */
#define PMU_REG_ADDR    0x658u          /* RegulatorControlAddr */
#define PMU_REG_DATA    0x65cu
#define PMU_VREG11      0x0bu
#define PMU_KICKSTART   0x12000u
#define PMU_FIS         0x7b4u
#define  FIS_DONE       (1u << 1)       /* PMU_CLEAR_FIS_DONE_MASK */
#define CC_EROM_PTR     0xfcu
#define CHIP_4390       0x4390u
#define SOCI_NCI        6u
#define BP_OTP_START    0x1801115cu     /* cis_tuple_addr_ranges for 0x4390 */
#define BP_OTP_END      0x180111b3u
#define OTP_WORDS       ((BP_OTP_END - BP_OTP_START + 1) / 4)
#define TUPLE_START     0x80u
#define TUPLE_VENDOR    0x81u
#define TUPLE_BOARD     0x1bu

/* NCI's descriptor list: nciutils.c */
#define ID_END          0xffffffffu
#define ID_COREOFFSET(d) ((d) & 0x1fffu)
#define ID_IS_EROM(d)   (((d) >> 27) & 1u)
#define ID_MASTER(d)    (((d) >> 26) & 1u)
#define ID_NADDR(d)     (((d) >> 24) & 3u)
#define ID_WORDOFFSET(d) ((d) >> 28)
#define SP_64BIT        0x20u
#define SP_BOUND        0x40u
#define IFACE_COUNT(c)  (((c) >> 12) & 0xfu)
#define CORE_MAX        64u
#define OOBR_FIRST      0x140u          /* OOBR_CORE0_OFFSET + OOBR_COREINFO_OFFSET */
#define OOBR_CORE_SIZE  0x80u
#define CORE_ARMCA7     0x847u
#define CORE_PCIE2      0x83cu
#define CORE_CC         0x800u
#define DMP_CTRL_OFF    8u
#define SICF_CPUHALT    0x20u

/* The chip's RAM: "Temp fix for SOCI_NCI", dhd_pcie.c, and physical */
#define RAM_BASE        0x2a0000u
#define RAM_SIZE        3276800u
#define RAM_END         (RAM_BASE + RAM_SIZE)
#define TOKEN_ADDR      (RAM_END - 4u)
#define SEED_BYTES      128u
#define SEED_TYPE       0xfeedc0deu     /* DNGL_RTLV_TYPE_RNG_SIGNATURE. Its length word has no checksum: "firmware crashes if checksum is present" */
#define WIN_SIZE        P1_EP_BAR2_SIZE
#define CHUNK           0x10000u
#define SHARED_POLL_MS  1u
#define SHARED_WAIT_MS  5000u           /* Physical: 912 ms. Stock waits for a boot interrupt, then polls up to 2 s; nothing here is waiting on this but the log */
#define SHARED_TRAP     0x400u
#define SHARED_VERSION_MASK 0xffu
#define S_CONSOLE       20u
#define S_FWID          28u
#define S_RXBUFS        32u             /* total_lfrag_pkt_cnt, then max_host_rxbufs in the high half */
#define S_RXOFFSET      36u
#define S_H2D_MB        40u
#define S_D2H_MB        44u
#define S_RINGS         48u
#define S_FLAGS2        80u
#define S_FLAGS3        108u
#define S_EWP           128u
#define SHARED_LOG_WORDS 36u
#define EWP_LOG_WORDS   8u
#define CONSOLE_BYTES   1500u
#define CONSOLE_WAIT_MS 300u
#define FLR_WAIT_MS     70u             /* DHD_FUNCTION_LEVEL_RESET_DELAY */
#define FLR_GAP_MS      20u             /* MIN_REGOFF_TO_REGON_DELAY, between Android's two FLRs. Its real gap is 89 ms */
#define FLR_POLL_US     55u             /* DHD_SSRESET_STATUS_RETRY_DELAY */
#define FLR_POLLS       200u            /* DHD_SSRESET_STATUS_RETRIES */

static uint32_t page_of(uint32_t a) { return a & ~0xfffu; }

/* ---- Config and backplane ---- */

static int cfg_rd(struct p1 *p, uint32_t off, uint32_t *v) { return p1_rd(p, CFG_PA + off, v); }
static int cfg_wr(struct p1 *p, uint32_t off, uint32_t v) { return p1_wr(p, CFG_PA + off, v); }
static int pcie_rd(struct p1 *p, uint32_t off, uint32_t *v) { return p1_rd(p, P1_EP_BAR0 + P1_EP_PCIE + off, v); }
static int pcie_wr(struct p1 *p, uint32_t off, uint32_t v) { return p1_wr(p, P1_EP_BAR0 + P1_EP_PCIE + off, v); }

/* Moves the window only when it must. value_ok in blazer_pcie1.c refuses any page outside chipcommon, OTP, PMU and the descriptor tables */
static int
bp_rd(struct p1 *p, uint32_t addr, uint32_t *v)
{
	uint32_t page = page_of(addr);

	if (p->bar0_win != page) {
		int rc = cfg_wr(p, P1_C_BAR0_WIN, page);

		if (rc) {
			return rc;
		}
		p->bar0_win = page;
	}
	return p1_rd(p, P1_EP_BAR0 + (addr & 0xfffu), v);
}

/* ---- Stage CHIP: dhdpcie_dongle_attach, in stock's order, and the OTP read ---- */

static int
set_bars(struct p1 *p)
{
	static const struct { uint32_t lo, hi; uint64_t base; } bars[] = {
		{ C_BAR0_LO, C_BAR0_HI, P1_EP_BAR0 }, { C_BAR2_LO, C_BAR2_HI, P1_EP_BAR2 }, { C_BAR4_LO, C_BAR4_HI, P1_EP_BAR4 },
	};
	uint32_t v = 0;

	for (unsigned i = 0; i < sizeof(bars) / sizeof(bars[0]); i++) {
		if (cfg_wr(p, bars[i].lo, (uint32_t)bars[i].base) || cfg_wr(p, bars[i].hi, 0) || cfg_rd(p, bars[i].lo, &v)) {
			return (int)p->stop;
		}
		if ((v & ~0xfu) != (uint32_t)bars[i].base) {
			return p1_halt(p, P1_STOP_BAR, v);
		}
	}
	if (cfg_rd(p, C_COMMAND, &v) || cfg_wr(p, C_COMMAND, v | CMD_MEMORY)) {
		return (int)p->stop;
	}
	return 0;
}

static int
ep_assign(struct p1 *p)
{
	uint32_t bar0 = 0;

	/* The root port's bridge windows, as Linux assigned them on this phone: mem 0x60400000-0x609fffff, 64-bit prefetchable 0x60300000-0x603fffff */
	if (p1_wr(p, DBI_PA + 0x20, 0x60906040u) || p1_wr(p, DBI_PA + 0x24, 0x60316031u) || p1_wr(p, DBI_PA + 0x28, 0) || p1_wr(p, DBI_PA + 0x2c, 0)) {
		return (int)p->stop;
	}
	if (p->cfg.mem_atu) {
		/* Off by default. Stock has no outbound memory region: traffic outside region 0 goes untranslated. This is the second try if that reads dead. Region 1, memory, 1:1 on the FDT's window */
		if (p1_wr(p, ATU_PA + 0x208, 0x60200000u) || p1_wr(p, ATU_PA + 0x20c, 0) || p1_wr(p, ATU_PA + 0x210, 0x7fffffffu) || p1_wr(p, ATU_PA + 0x220, 0) ||
		    p1_wr(p, ATU_PA + 0x214, 0x60200000u) || p1_wr(p, ATU_PA + 0x218, 0) || p1_wr(p, ATU_PA + 0x200, 0) || p1_wr(p, ATU_PA + 0x204, 1u << 31)) {
			return (int)p->stop;
		}
	}
	if (set_bars(p) || cfg_rd(p, C_BAR0_LO, &bar0)) {
		return (int)p->stop;
	}
	p->ep_mem_on = true;
	p->bar0_win = 0xffffffffu;
	p->ops.log(p->ops.ctx, "chip: BARs set, BAR 0 reads 0x%08x, Android's 0x60800004, memory decode on. Next: first read through BAR 0, chipcommon's ID\n", bar0);
	return 0;
}

/* dhdpcie_chip_specific_init: "set asr_pfm_kickstart_en to avoid ASR crash during cold start", 4390 rev 2 or 5. Through the indirect pair in config space, then CTO. Every attach runs it: twice on Android, physical */
static int
chip_specific(struct p1 *p)
{
	if (p->chip_rev == 2 || p->chip_rev == 5) {
		if (cfg_wr(p, P1_C_BAR0_WIN, P1_BP_PMU)) {
			return (int)p->stop;
		}
		p->bar0_win = P1_BP_PMU;
		if (cfg_wr(p, C_SSCTRL, SS_BP_ENABLE) || cfg_wr(p, P1_C_IND_ADDR, PMU_REG_ADDR) || cfg_wr(p, P1_C_IND_DATA, PMU_VREG11) || cfg_wr(p, P1_C_IND_ADDR, PMU_REG_DATA) || cfg_wr(p, P1_C_IND_DATA, PMU_KICKSTART) ||
		    cfg_wr(p, P1_C_BAR0_WIN, P1_BP_CC) || cfg_wr(p, C_SSCTRL, SS_BP_DISABLE)) {
			return (int)p->stop;
		}
		p->bar0_win = P1_BP_CC;
		p->ops.log(p->ops.ctx, "chip: ASR workaround programmed\n");
	}
	if (cfg_wr(p, C_INT_MASK, INT_CTO_SERR) || pcie_wr(p, P_CTO, CTO_VALUE) || pcie_rd(p, P_CTO, &p->cto_ctrl)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "chip: completion timeout on, 0x%08x, Android's 0x8a058000\n", p->cto_ctrl);
	return 0;
}

/* si_srpwr_request: the ARM and backplane domain. On: waits for its status, as stock does */
#define power_request b4_power
int
b4_power(struct p1 *p, bool on)
{
	uint32_t v = 0;

	if (p1_rmw(p, P1_EP_BAR0 + P1_EP_PCIE + P_POWER_CTRL, PWR_REQ_DMN1, on ? PWR_REQ_DMN1 : 0)) {
		return (int)p->stop;
	}
	if (!on) {
		return 0;
	}
	for (unsigned i = 0; i < PWR_POLLS; i++) {
		if (pcie_rd(p, P_POWER_CTRL, &v)) {
			return (int)p->stop;
		}
		if (v & PWR_ST_DMN1) {
			return 0;
		}
		p->ops.delay_us(p->ops.ctx, PWR_POLL_US);
	}
	return p1_halt(p, P1_STOP_POWER_REQ, v);
}

static void
note_core(struct p1 *p, uint32_t info, uint32_t dmp, bool oobr)
{
	uint32_t id = info & 0xfffu, rev = (info >> 12) & 0xffu;

	if (id < 0xffu) {
		id |= 0x800u;
	}
	if (id == CORE_ARMCA7 && oobr && !p->arm_known) {
		p->arm_dmp = dmp;       /* dmpctrl exists only for OOBR cores */
		p->arm_rev = rev;
		p->arm_known = true;
	} else if (id == CORE_PCIE2) {
		p->bus_rev = rev;
	} else if (id == CORE_CC) {
		p->cc_rev = rev;
	}
}

/* nci_scan's walk, keeping only what's needed: a core's first interface says where its info is, all interfaces and their address words are stepped over. nci_check_extra_core: the OOBR table can hold cores with no list entry */
static int
walk_backplane(struct p1 *p)
{
	uint32_t ptr = 0, addr, d0 = 0, d1 = 0, next_oobr = OOBR_FIRST;

	if (bp_rd(p, P1_BP_CC + CC_EROM_PTR, &ptr)) {
		return (int)p->stop;
	}
	p->cc_erom2 = ptr & ~7u;
	if (p->cc_erom2 < P1_BP_CC || p->cc_erom2 >= 0x1a000000u) {
		return p1_halt(p, P1_STOP_NCI, ptr);
	}
	p->oobr_base = p->cc_erom2 & ~0x1fffu;
	p->erom1_base = p->cc_erom2 & ~0xfffu;
	p->ops.log(p->ops.ctx, "chip: descriptor list at 0x%08x, OOBR 0x%08x\n", p->cc_erom2, p->oobr_base);
	addr = p->cc_erom2;
	for (p->core_count = 0; p->core_count < CORE_MAX; p->core_count++) {
		uint32_t info = 0, ifc = 0, base, off, wordoffset = 0;

		if (bp_rd(p, addr, &d0)) {
			return (int)p->stop;
		}
		if (d0 == ID_END) {
			break;
		}
		if (bp_rd(p, addr + 4, &d1)) {
			return (int)p->stop;
		}
		off = ID_COREOFFSET(d1);
		base = ID_IS_EROM(d1) ? p->erom1_base : p->oobr_base;
		if (!ID_IS_EROM(d1)) {
			for (uint32_t o = next_oobr; o < off; o += OOBR_CORE_SIZE) {
				if (bp_rd(p, p->oobr_base + o, &info)) {
					return (int)p->stop;
				}
				note_core(p, info, p->oobr_base + o + DMP_CTRL_OFF, true);
			}
			next_oobr = off + OOBR_CORE_SIZE;
		}
		if (bp_rd(p, base + off, &info) || bp_rd(p, base + off + 4, &ifc)) {
			return (int)p->stop;
		}
		note_core(p, info, base + off + DMP_CTRL_OFF, !ID_IS_EROM(d1));
		if (IFACE_COUNT(ifc) == 0) {
			return p1_halt(p, P1_STOP_NCI, ifc);
		}
		for (uint32_t i = 0; i < IFACE_COUNT(ifc); i++) {
			uint32_t naddr;

			if (bp_rd(p, addr, &d0) || bp_rd(p, addr + 4, &d1)) {
				return (int)p->stop;
			}
			addr += 8;
			wordoffset = ID_WORDOFFSET(d1);
			if (ID_MASTER(d1)) {
				continue;
			}
			naddr = ID_NADDR(d1);
			if (wordoffset > 1) {
				naddr++;
			} else if (wordoffset == 0) {
				uint32_t a = 0;

				if (bp_rd(p, addr, &a)) {
					return (int)p->stop;
				}
				if (a != ID_END) {
					naddr++;
				}
			}
			for (uint32_t j = 0; j < naddr; j++) {
				uint32_t a = 0;

				if (bp_rd(p, addr, &a)) {
					return (int)p->stop;
				}
				addr += 4;
				addr += (a & SP_64BIT) ? 12 : (a & SP_BOUND) ? 4 : 0;
			}
		}
		if (wordoffset == 0) {
			p->core_count++;
			break;
		}
	}
	p->ops.log(p->ops.ctx, "chip: %u cores walked. chipcommon rev %u, Android's 79. PCIe rev %u, Android's 133. ARM CA7 rev %u, control at 0x%08x\n", p->core_count, p->cc_rev, p->bus_rev, p->arm_rev, p->arm_dmp);
	if (!p->arm_known) {
		return p1_halt(p, P1_STOP_NO_ARM, p->core_count);
	}
	return 0;
}

static int
read_arm(struct p1 *p)
{
	if (bp_rd(p, p->arm_dmp, &p->arm_ctrl)) {
		return (int)p->stop;
	}
	p->arm_halted = (p->arm_ctrl & SICF_CPUHALT) != 0;
	p->ops.log(p->ops.ctx, "chip: ARM control 0x%x: %s\n", p->arm_ctrl, p->arm_halted ? "halted, as Android finds it" : "NOT halted");
	return 0;
}

static int
coherent_on(struct p1 *p)
{
	uint32_t v = 0;

	/* "CA7 requires coherent bits on" */
	if (cfg_rd(p, C_SSCTRL, &v) || cfg_wr(p, C_SSCTRL, v | SS_COHERENT)) {
		return (int)p->stop;
	}
	return 0;
}

/* read_otp_from_bp, dhd_parse_board_information_bcm. Stock's choice of NVRAM comes from here */
static int
read_otp(struct p1 *p)
{
	uint32_t raw[OTP_WORDS];
	const uint8_t *b = (const uint8_t *)raw;
	uint32_t total = sizeof(raw), at = 0;

	p->nvram_index = P1_NVRAM_FALLBACK;
	for (uint32_t i = 0; i < OTP_WORDS; i++) {
		if (bp_rd(p, BP_OTP_START + i * 4, &raw[i])) {
			return (int)p->stop;
		}
	}
	p->ops.log(p->ops.ctx, "otp: %08x %08x %08x %08x %08x %08x\n", raw[0], raw[1], raw[2], raw[3], raw[4], raw[5]);
	p->otp_read = true;
	if (b[0] != TUPLE_START) {
		p->ops.log(p->ops.ctx, "otp: first tuple is 0x%02x, not 0x80: no VID\n", b[0]);
	} else {
		/* id, length, tag, data */
		while (at + 3 <= total && at + b[at + 1] + 2u <= total && (p->otp_vid_len == 0 || p->otp_boardtype == 0)) {
			uint32_t len = b[at + 1];

			if (b[at + 2] == TUPLE_VENDOR && len >= 1 && len - 1 <= sizeof(p->otp_vid)) {
				memcpy(p->otp_vid, &b[at + 3], len - 1);
				p->otp_vid_len = len - 1;
			} else if (b[at + 2] == TUPLE_BOARD && len >= 2) {
				p->otp_boardtype = b[at + 3];
			}
			at += len + 2;
		}
	}
	/* vid_naming_table_4390. Stock's table lengths are one more than the VID's: vid_length - 1 == vid_length read */
	if (p->otp_vid_len == 2) {
		uint8_t v0 = p->otp_vid[0], v1 = p->otp_vid[1];

		if (v0 == 0x11 && v1 == 0x73) {
			p->nvram_index = P1_NVRAM_7311;
		} else if (v0 == 0x21 && v1 == 0x73) {
			p->nvram_index = P1_NVRAM_7321;
		} else if ((v0 == 0x26 || v0 == 0x27) && v1 == 0x63) {
			p->nvram_index = P1_NVRAM_6327;
		}
	}
	p->ops.log(p->ops.ctx, "otp: VID %u bytes %02x %02x, board type 0x%02x. NVRAM %s. Android here used bcmdhd.cal_USI_G7BB_7311_V11\n", p->otp_vid_len, p->otp_vid[0], p->otp_vid[1], p->otp_boardtype,
	    p->cfg.nvram[p->nvram_index].name != NULL ? p->cfg.nvram[p->nvram_index].name : "(none)");
	return 0;
}

int
b4_chip(struct p1 *p)
{
	uint32_t w = 0;

	if (ep_assign(p)) {
		return (int)p->stop;
	}
	if (bp_rd(p, P1_BP_CC, &w)) {
		return (int)p->stop;
	}
	p->chip_word = w;
	p->chip_id = w & 0xffffu;
	p->chip_rev = (w >> 16) & 0xfu;
	p->chip_type = w >> 28;
	p->ops.log(p->ops.ctx, "chip: id word 0x%08x: chip 0x%x rev %u, type %u\n", w, p->chip_id, p->chip_rev, p->chip_type);
	if (p->chip_id != CHIP_4390 || p->chip_type != SOCI_NCI) {
		return p1_halt(p, P1_STOP_CHIP_ID, w);
	}
	if (chip_specific(p)) {
		return (int)p->stop;
	}
	if (pcie_rd(p, P_DAR_SEC, &p->dar_sec) || pcie_rd(p, P_DAR_CLK, &p->dar_clk) || pcie_rd(p, P_DAR_PWR, &p->dar_pwr)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "chip: DAR security 0x%x: SBOOT %u. DAR clock 0x%x, power 0x%x\n", p->dar_sec, (p->dar_sec & SEC_SBOOT) ? 1u : 0u, p->dar_clk, p->dar_pwr);
	if (power_request(p, true) || walk_backplane(p)) {
		return (int)p->stop;
	}
	/* "If FIS done bit is set, then clear it, set chip big hammer and return". Physical: 0 at attach. Our REG_ON was just low for 100 ms, so it should be */
	if (bp_rd(p, P1_BP_PMU + PMU_FIS, &p->fis)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "chip: FISCtrlStatus 0x%x, Android's 0\n", p->fis);
	if (p->fis & FIS_DONE) {
		return p1_halt(p, P1_STOP_FIS, p->fis);
	}
	if (coherent_on(p) || read_arm(p)) {
		return (int)p->stop;
	}
	return read_otp(p);
}

/* ---- Stage FW ---- */

/* The window onto the chip's RAM moves in 4 MiB steps: dhdpcie_bus_chkandshift_bpoffset */
static int
tcm_pa(struct p1 *p, uint32_t addr, uint64_t *pa)
{
	uint32_t win = addr & ~(WIN_SIZE - 1u);

	if (!p->bar1_set || p->bar1_win != win) {
		int rc = cfg_wr(p, P1_C_RAM_WIN, win);

		if (rc) {
			return rc;
		}
		p->bar1_win = win;
		p->bar1_set = true;
	}
	*pa = P1_EP_BAR2 + (addr - win);
	return 0;
}

int
b4_tcm_rd(struct p1 *p, uint32_t addr, uint32_t *v)
{
	uint64_t pa = 0;

	return tcm_pa(p, addr, &pa) ? (int)p->stop : p1_rd(p, pa, v);
}

int
b4_tcm_wr(struct p1 *p, uint32_t addr, uint32_t v)
{
	uint64_t pa = 0;

	return tcm_pa(p, addr, &pa) ? (int)p->stop : p1_wr(p, pa, v);
}

int
b4_tcm_wr16(struct p1 *p, uint32_t addr, uint16_t v)
{
	uint64_t pa = 0;

	return tcm_pa(p, addr, &pa) ? (int)p->stop : p1_wr16(p, pa, v);
}

#define tcm_rd b4_tcm_rd
#define tcm_wr b4_tcm_wr

/* Words, in chunks that don't cross a window. Reading each chunk's last word back pushes the posted writes through and finds a dead window early */
static int
tcm_write(struct p1 *p, uint32_t addr, const uint8_t *src, uint32_t bytes)
{
	if ((addr & 3u) != 0 || (bytes & 3u) != 0) {
		return p1_halt(p, P1_STOP_TCM, addr);
	}
	while (bytes != 0) {
		uint32_t room = WIN_SIZE - (addr & (WIN_SIZE - 1u)), n = bytes < CHUNK ? bytes : CHUNK, last, got = 0;
		uint64_t pa = 0;

		if (n > room) {
			n = room;
		}
		if (tcm_pa(p, addr, &pa)) {
			return (int)p->stop;
		}
		if (!p1_write_allowed(p, pa) || !p1_write_allowed(p, pa + n - 4)) {
			return p1_halt(p, P1_STOP_REFUSED_PA, addr);
		}
		if (p->ops.bulk32(p->ops.ctx, pa, src, n / 4) != 0) {
			return p1_halt(p, P1_STOP_FAULT, addr);
		}
		p->ops.barrier(p->ops.ctx);
		memcpy(&last, src + n - 4, 4);
		if (p1_rd(p, pa + n - 4, &got)) {
			return (int)p->stop;
		}
		if (got != last) {
			p->ops.log(p->ops.ctx, "fw: RAM at 0x%x reads 0x%08x, wrote 0x%08x\n", addr + n - 4, got, last);
			return p1_halt(p, P1_STOP_TCM, addr + n - 4);
		}
		addr += n;
		src += n;
		bytes -= n;
	}
	return 0;
}

/* The whole thing, as DHD does for NVRAM and the seed. For firmware too here: a first load should leave no doubt that the bytes got there */
static int
tcm_verify(struct p1 *p, uint32_t addr, const uint8_t *src, uint32_t bytes)
{
	for (uint32_t i = 0; i < bytes; i += 4) {
		uint32_t want, got = 0;

		memcpy(&want, src + i, 4);
		if (tcm_rd(p, addr + i, &got)) {
			return (int)p->stop;
		}
		if (got != want) {
			p->ops.log(p->ops.ctx, "fw: RAM at 0x%x reads 0x%08x, wrote 0x%08x\n", addr + i, got, want);
			return p1_halt(p, P1_STOP_TCM, addr + i);
		}
	}
	return 0;
}

/* dhd_bus_perform_flr with dhdpcie_config_save and _restore. What stock also restores (MSI, device and link control, L1 substates) is either unused here or never changed from its reset value */
static int
flr(struct p1 *p)
{
	uint32_t hdr[16], ptm = 0, ss = 0, ctl = 0, cap = 0;

	if (cfg_rd(p, C_DEV_CAP, &cap)) {
		return (int)p->stop;
	}
	if (!(cap & DEV_CAP_FLR)) {
		return p1_halt(p, P1_STOP_FLR, cap);
	}
	if (cfg_rd(p, C_PTM_CTRL, &ptm) || cfg_rd(p, C_SSCTRL, &ss)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "flr: %u: config 0x88 is 0x%x. Android's second reads 0x80080. Next: FLR\n", p->flrs + 1, ss);
	if (ss & SS_RESET_STATUS) {
		return p1_halt(p, P1_STOP_FLR, ss);
	}
	for (unsigned i = 1; i < 16; i++) {
		if (cfg_rd(p, i * 4, &hdr[i])) {
			return (int)p->stop;
		}
	}
	if (cfg_rd(p, C_DEV_CTRL, &ctl)) {
		return (int)p->stop;
	}
	p->ep_mem_on = false;   /* Decode is off until the restore: no BAR access can slip through */
	if (cfg_wr(p, C_DEV_CTRL, ctl | DEV_CTRL_FLR)) {
		return (int)p->stop;
	}
	p->ops.delay_us(p->ops.ctx, FLR_WAIT_MS * 1000);
	if (cfg_rd(p, C_DEV_CTRL, &ctl) || cfg_wr(p, C_DEV_CTRL, ctl & ~DEV_CTRL_FLR)) {
		return (int)p->stop;
	}
	for (unsigned i = 0;; i++) {
		if (cfg_rd(p, C_SSCTRL, &ss)) {
			return (int)p->stop;
		}
		if (!(ss & SS_RESET_STATUS)) {
			break;
		}
		if (i >= FLR_POLLS) {
			return p1_halt(p, P1_STOP_FLR, ss);
		}
		p->ops.delay_us(p->ops.ctx, FLR_POLL_US);
	}
	/* PTM, then the header from the revision word up, then the command word, then the windows */
	if (cfg_wr(p, C_PTM_CTRL, ptm)) {
		return (int)p->stop;
	}
	for (unsigned i = 2; i < 16; i++) {
		if (cfg_wr(p, i * 4, hdr[i])) {
			return (int)p->stop;
		}
	}
	if (cfg_wr(p, C_COMMAND, hdr[1]) || cfg_wr(p, P1_C_BAR0_WIN, P1_BP_CC) || cfg_wr(p, P1_C_RAM_WIN, 0)) {
		return (int)p->stop;
	}
	p->bar0_win = P1_BP_CC;
	p->bar1_win = 0;
	p->bar1_set = true;
	p->ep_mem_on = true;
	p->flrs++;
	p->ops.log(p->ops.ctx, "flr: %u: done, config 0x88 now 0x%x\n", p->flrs, ss);
	return 0;
}

/* process_nvram_vars's result, not its code. The caller first overwrites the last byte with a NUL; that NUL then goes through as an ordinary byte, unless a comment swallows it */
uint32_t
b4_nvram_process(const uint8_t *text, uint32_t size, uint8_t *out, uint32_t out_size)
{
	uint32_t n = 0, column = 0;
	bool skip = false;

	if (size == 0 || size > 0xffffff00u || size + 8 > out_size) {
		return 0;
	}
	for (uint32_t i = 0; i < size; i++) {
		uint8_t c = i + 1 == size ? 0 : text[i];

		if (c == '\r' || (skip && c != '\n')) {
			continue;
		}
		skip = false;
		if (c == '#') {
			skip = true;
			continue;
		}
		if (c == '\n') {
			if (column != 0) {
				out[n++] = 0;
				column = 0;
			}
			continue;
		}
		out[n++] = c;
		column++;
	}
	/* To a word. Then varsz is one more, which ROUNDUP makes one more word: all NUL */
	while ((n & 3u) != 0) {
		out[n++] = 0;
	}
	for (unsigned i = 0; i < 4; i++) {
		out[n++] = 0;
	}
	return n;
}

static int
load_nvram(struct p1 *p)
{
	const struct p1_image *img = &p->cfg.nvram[p->nvram_index];
	uint32_t words, n;

	if (img->data == NULL || p->cfg.nvram_buf == NULL) {
		return p1_halt(p, P1_STOP_NVRAM, p->nvram_index);
	}
	n = b4_nvram_process(img->data, img->size, p->cfg.nvram_buf, p->cfg.nvram_buf_size);
	if (n == 0 || n > RAM_SIZE / 8) {
		return p1_halt(p, P1_STOP_NVRAM, n);
	}
	p->var_size = n;
	p->var_addr = RAM_END - 4 - n;
	if (p->var_addr - 8 - SEED_BYTES < RAM_BASE + p->cfg.fw.size) {
		return p1_halt(p, P1_STOP_NVRAM, p->var_addr);
	}
	words = n / 4;
	p->token = (~words << 16) | (words & 0xffffu);
	p->ops.log(p->ops.ctx, "fw: NVRAM %s: %u bytes at 0x%x, token 0x%08x. Android, for 7311: 18268, 0x5bb8a0, 0xee2811d7\n", img->name, n, p->var_addr, p->token);
	if (tcm_write(p, p->var_addr, p->cfg.nvram_buf, n) || tcm_verify(p, p->var_addr, p->cfg.nvram_buf, n) || tcm_wr(p, TOKEN_ADDR, p->token)) {
		return (int)p->stop;
	}
	return 0;
}

/* dhdpcie_wrt_rnd, dhdpcie_download_rtlv: value, then length, then type, ending just under the NVRAM */
static int
load_seed(struct p1 *p)
{
	uint8_t seed[SEED_BYTES];
	uint32_t at = p->var_addr - 8 - SEED_BYTES;

	p->ops.random(p->ops.ctx, seed, SEED_BYTES);
	if (tcm_write(p, at, seed, SEED_BYTES) || tcm_verify(p, at, seed, SEED_BYTES) || tcm_wr(p, at + SEED_BYTES, SEED_BYTES) || tcm_wr(p, at + SEED_BYTES + 4, SEED_TYPE)) {
		return (int)p->stop;
	}
	p->ram_top = at;
	p->ops.log(p->ops.ctx, "fw: seed at 0x%x, Android's 0x5bb818 for 7311\n", at);
	return 0;
}

/* si_core_cflags(SICF_CPUHALT, 0): "for ARM CA7 it is enough if we clear bit5 in IO DMP ctrl register" */
static int
release_arm(struct p1 *p)
{
	uint32_t v = 0, want;

	if (bp_rd(p, p->arm_dmp, &v)) {
		return (int)p->stop;
	}
	want = v & ~SICF_CPUHALT;
	p->ops.log(p->ops.ctx, "fw: next: ARM out of halt, control 0x%x to 0x%x\n", v, want);
	if (p1_wr(p, P1_EP_BAR0 + (p->arm_dmp & 0xfffu), want)) {
		return (int)p->stop;
	}
	if (bp_rd(p, p->arm_dmp, &v)) {
		return (int)p->stop;
	}
	if (v != want) {
		return p1_halt(p, P1_STOP_ARM_RELEASE, v);
	}
	p->arm_released = true;
	return 0;
}

/* hnd_cons_t: vcons_in, vcons_out, then log: buf, buf_size, idx, out_idx. Only what wasn't printed by the last call */
int
b4_console(struct p1 *p)
{
	uint32_t buf = 0, size = 0, idx = 0, c = p->console_addr, start, have, line_bytes = 0;
	char line[120];
	unsigned n = 0;

	if (c < RAM_BASE || c > RAM_END - 32) {
		p->ops.log(p->ops.ctx, "fw: no console: 0x%x\n", c);
		return 0;
	}
	if (tcm_rd(p, c + 8, &buf) || tcm_rd(p, c + 12, &size) || tcm_rd(p, c + 16, &idx)) {
		return (int)p->stop;
	}
	/* Stage JOIN reads this every 2 s for as long as it runs: once is enough */
	if (p->cfg.stage < P1_STAGE_JOIN || !p->console_told) {
		p->console_told = true;
		p->ops.log(p->ops.ctx, "fw: console at 0x%x: buffer 0x%x, %u bytes, write index %u\n", c, buf, size, idx);
	}
	if (buf < RAM_BASE || buf >= RAM_END || size == 0 || size > RAM_END - buf || idx >= size) {
		return 0;
	}
	start = idx >= p->console_seen ? p->console_seen : 0;   /* It wrapped: what's before the index is newest */
	have = idx - start;
	if (have > CONSOLE_BYTES) {
		start = idx - CONSOLE_BYTES;
		have = CONSOLE_BYTES;
	}
	p->console_seen = idx;
	for (uint32_t i = 0; i < have; i++) {
		uint32_t a = buf + start + i, w = 0;
		char ch;

		if (tcm_rd(p, a & ~3u, &w)) {
			return (int)p->stop;
		}
		ch = (char)(w >> (8 * (a & 3u)));
		line_bytes++;
		if (ch == '\n' || n == sizeof(line) - 1) {
			line[n] = 0;
			if (n != 0) {
				b4_scrub_text(p, line);
				b4_console_note(p, line);
				p->ops.log(p->ops.ctx, "fw says: %s\n", line);
			}
			n = 0;
			line_bytes = 0;
		} else if (ch >= 32 && ch < 127) {
			line[n++] = ch;
		}
	}
	if (n != 0) {
		/* Half a line could end in half a name: with a network in the image it waits, and is read again whole */
		if (p->jn_scrub) {
			p->console_seen = idx - line_bytes;
			return 0;
		}
		line[n] = 0;
		b4_console_note(p, line);
		p->ops.log(p->ops.ctx, "fw says: %s\n", line);
	}
	return 0;
}

/* r5: "EL: 30 b8c8 <packet> <rxfrag>" is event_log2(0x30, 0xb8c8, ...) in pciedev_process_d2h_rxpyld (RAM 0x2c45f8 in .57.31; the same number in .57.30's console):
 * pciedev_process_rxpost_msg had no host RX buffer for a packet in dongle memory, and the packet was freed. Counted, and said once */
void
b4_console_note(struct p1 *p, const char *line)
{
	static const char tag[] = "EL: 30 b8c8 ";

	for (const char *c = line; *c != 0; c++) {
		unsigned i = 0;

		while (tag[i] != 0 && c[i] == tag[i]) {
			i++;
		}
		if (tag[i] == 0) {
			if (p->fw_rx_nobuf++ == 0) {
				p->ops.log(p->ops.ctx, "rx: the firmware dropped a packet for the host: no host RX buffer was queued (EL 30 b8c8)\n");
			}
			return;
		}
	}
}

/* dhdpcie_wait_readshared_area_addr, polled. Stock sleeps until the firmware's boot interrupt and reads the top word once, so it never sees an early one; here the top word's every change goes to the log.
 * Ready means the doorbell. With none in the time allowed, stock reads what's there and goes on, and so does this: the checks on the shared area below decide */
static int
wait_ready(struct p1 *p)
{
	uint32_t top = 0, last = p->token, mb = 0;
	uint64_t t0 = p->ops.now_us(p->ops.ctx);

	for (;;) {
		/* Time from the clock. Physical, wifi-stage3-r1: counting 1 ms sleeps said 751 where the firmware's own console said it had taken 900, the reads between them not counted */
		uint32_t ms = (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000);

		if (tcm_rd(p, TOKEN_ADDR, &top)) {
			return (int)p->stop;
		}
		if (top != last) {
			p->ops.log(p->ops.ctx, "fw: top word 0x%x, %u ms after release\n", top, ms);
			if (last == p->token) {
				p->early_top = top;
			}
			p->shared_ms = ms;
			last = top;
		}
		if (top == 0xffffffffu) {
			return p1_halt(p, P1_STOP_BAD_SHARED, top);
		}
		if (pcie_rd(p, P_MBOX_INT, &mb)) {
			return (int)p->stop;
		}
		if (mb & MBOX_D2H) {
			p->doorbell_seen = true;
			p->doorbell_ms = ms;
			p->mailbox = mb;
			p->ops.log(p->ops.ctx, "fw: boot doorbell, mailbox 0x%x, %u ms after release. Android: 912 ms\n", mb, ms);
			if (pcie_wr(p, P_MBOX_INT, mb & MBOX_D2H)) {
				return (int)p->stop;
			}
			break;
		}
		if (ms >= SHARED_WAIT_MS) {
			p->ops.log(p->ops.ctx, "fw: no boot doorbell in %u ms, mailbox 0x%x, top word 0x%x\n", ms, mb, top);
			break;
		}
		p->ops.delay_us(p->ops.ctx, SHARED_POLL_MS * 1000);
	}
	/* Read it again: the doorbell is what says it's final */
	if (tcm_rd(p, TOKEN_ADDR, &top)) {
		return (int)p->stop;
	}
	if (top == 0 || top == p->token) {
		return p1_halt(p, P1_STOP_NO_SHARED, top);
	}
	p->ops.log(p->ops.ctx, "fw: shared area at 0x%x. Android: 0x5ae000\n", top);
	if (top < RAM_BASE || top > RAM_END - 4 * SHARED_LOG_WORDS || (top & 3u) != 0) {
		return p1_halt(p, P1_STOP_BAD_SHARED, top);
	}
	p->shared_addr = top;
	return 0;
}

static int
read_shared(struct p1 *p)
{
	uint32_t addr = p->shared_addr, w[SHARED_LOG_WORDS];

	for (unsigned i = 0; i < SHARED_LOG_WORDS; i++) {
		if (tcm_rd(p, addr + i * 4, &w[i])) {
			return (int)p->stop;
		}
	}
	p->shared_flags = w[0];
	p->console_addr = w[S_CONSOLE / 4];
	p->fwid = w[S_FWID / 4];
	p->max_rxbufs = w[S_RXBUFS / 4] >> 16;
	p->rx_offset = w[S_RXOFFSET / 4];
	p->h2d_mb_ptr = w[S_H2D_MB / 4];
	p->d2h_mb_ptr = w[S_D2H_MB / 4];
	p->rings_info = w[S_RINGS / 4];
	p->shared_flags2 = w[S_FLAGS2 / 4];
	p->shared_flags3 = w[S_FLAGS3 / 4];
	p->ewp_info = w[S_EWP / 4];
	p->ops.log(p->ops.ctx, "fw: UP. Shared flags 0x%08x: IPC version %u, trap %u. FWID 0x%08x, the file's (27.10.1121.57.31, Android's) 01-765a5017\n", p->shared_flags, p->shared_flags & SHARED_VERSION_MASK, (p->shared_flags & SHARED_TRAP) ? 1u : 0u, p->fwid);
	for (unsigned i = 0; i < SHARED_LOG_WORDS; i += 4) {
		p->ops.log(p->ops.ctx, "fw: shared +%02x: %08x %08x %08x %08x\n", i * 4, w[i], w[i + 1], w[i + 2], w[i + 3]);
	}
	/* EWP's own struct: its state says whether the firmware's init ended. Its layout isn't in the headers here, so the words go to the log */
	if (p->ewp_info >= RAM_BASE && p->ewp_info <= RAM_END - 4 * EWP_LOG_WORDS) {
		uint32_t e[EWP_LOG_WORDS];

		for (unsigned i = 0; i < EWP_LOG_WORDS; i++) {
			if (tcm_rd(p, p->ewp_info + i * 4, &e[i])) {
				return (int)p->stop;
			}
		}
		p->ops.log(p->ops.ctx, "fw: EWP info at 0x%x: %08x %08x %08x %08x %08x %08x %08x %08x\n", p->ewp_info, e[0], e[1], e[2], e[3], e[4], e[5], e[6], e[7]);
	}
	return b4_console(p);
}

/* dhd_bus_dump_dar_registers and the interrupt status. On success to compare with Android's "dar_clk_ctrl(0xa08:0x50040) dar_pwr_ctrl(0xa0c:0x30000)"; on failure, the last evidence before the chip goes off. Keeps the stop that brought us here */
void
b4_diag(struct p1 *p)
{
	uint32_t stop = p->stop, detail = p->stop_detail, clk = 0xffffffffu, pwr = 0xffffffffu, err = 0xffffffffu, addr = 0xffffffffu, mb = 0xffffffffu, ints = 0xffffffffu, sec = 0xffffffffu;

	p->stop = P1_OK;
	(void)pcie_rd(p, P_DAR_CLK, &clk);
	(void)pcie_rd(p, P_DAR_PWR, &pwr);
	(void)pcie_rd(p, P_DAR_ERRLOG, &err);
	(void)pcie_rd(p, P_DAR_ERRADDR, &addr);
	(void)pcie_rd(p, P_DAR_MBINT, &mb);
	(void)pcie_rd(p, P_DAR_SEC, &sec);
	(void)cfg_rd(p, C_INT_STATUS, &ints);
	p->ops.log(p->ops.ctx, "fw: DAR clock 0x%x, power 0x%x, error log 0x%x at 0x%x, mailbox 0x%x, security 0x%x. Config interrupt status 0x%x%s\n", clk, pwr, err, addr, mb, sec, ints, p->stop != P1_OK ? " (a read was refused)" : "");
	p->stop = P1_OK;
	(void)b4_console(p);    /* Whatever it wrote since the last look */
	p->stop = stop;
	p->stop_detail = detail;
}

static int
fw_load(struct p1 *p)
{
	const struct p1_image *fw = &p->cfg.fw;
	uint32_t reset_vector = 0, v = 0;
	uint64_t t0;

	if (p->dar_sec & SEC_SBOOT) {
		return p1_halt(p, P1_STOP_SBOOT, p->dar_sec);
	}
	if (!p->arm_known || !p->arm_halted) {
		return p1_halt(p, P1_STOP_ARM_RUNNING, p->arm_ctrl);
	}
	if (fw->data == NULL || p->cfg.nvram_buf == NULL || fw->size < 4096 || (fw->size & 3u) != 0 || fw->size > RAM_SIZE - CHUNK) {
		return p1_halt(p, P1_STOP_FW_IMAGE, fw->size);
	}
	/* Android: FLR when its first attach ends, then another at the WBRC's "turn WLAN ON". Then a second attach */
	for (uint32_t i = 0; i < p->cfg.flr; i++) {
		if (i != 0) {
			p->ops.delay_us(p->ops.ctx, FLR_GAP_MS * 1000);
		}
		if (flr(p)) {
			return (int)p->stop;
		}
	}
	if (chip_specific(p) || power_request(p, true) || coherent_on(p) || read_arm(p)) {
		return (int)p->stop;
	}
	if (!p->arm_halted) {
		return p1_halt(p, P1_STOP_ARM_RUNNING, p->arm_ctrl);
	}
	/* The end of dhdpcie_dongle_attach. BAR1 size workaround, then: our request off, the common domain's "one time clearing", the WL domain asserted through DAR ("WAR to fix ARM cold boot") */
	if (pcie_wr(p, P_IND_ADDR, BP_BAR1_WAR) || pcie_rd(p, P_IND_DATA, &v) || pcie_wr(p, P_IND_DATA, v) || power_request(p, false) ||
	    p1_rmw(p, P1_EP_BAR0 + P1_EP_PCIE + P_POWER_CTRL, PWR_REQ_DMN0, 0) || p1_rmw(p, P1_EP_BAR0 + P1_EP_PCIE + P_DAR_PWR, PWR_REQ_DMN1, PWR_REQ_DMN1)) {
		return (int)p->stop;
	}
	/* __dhdpcie_bus_download_state, enter: both windows at 0. The ARM needs no reset: out of reset and halted, physical. The word the firmware will replace is cleared. Stock takes a power request around each access; one across the load does the same */
	if (cfg_wr(p, P1_C_RAM_WIN, 0) || cfg_wr(p, P1_C_BT_WIN, 0)) {
		return (int)p->stop;
	}
	p->bar1_win = 0;
	p->bar1_set = true;
	if (power_request(p, true) || tcm_wr(p, TOKEN_ADDR, 0)) {
		return (int)p->stop;
	}
	t0 = p->ops.now_us(p->ops.ctx);
	p->ops.log(p->ops.ctx, "fw: next: %s, %u bytes to 0x%x\n", fw->name, fw->size, RAM_BASE);
	if (tcm_write(p, RAM_BASE, fw->data, fw->size)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "fw: written in %u ms. Next: read all of it back\n", (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000));
	t0 = p->ops.now_us(p->ops.ctx);
	if (tcm_verify(p, RAM_BASE, fw->data, fw->size)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "fw: every word reads back, %u ms\n", (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000));
	memcpy(&reset_vector, fw->data, 4);
	/* Exit: vars, seed, then the reset vector at 0. No signature files: their names are empty on this phone, and the chip isn't secure */
	if (load_nvram(p) || load_seed(p)) {
		return (int)p->stop;
	}
	if (tcm_wr(p, 0, reset_vector) || tcm_rd(p, 0, &v)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "fw: vector 0x%08x at 0 reads 0x%08x\n", reset_vector, v);
	if (power_request(p, false) || tcm_rd(p, TOKEN_ADDR, &v)) {
		return (int)p->stop;
	}
	if (v != p->token) {
		return p1_halt(p, P1_STOP_TCM, v);
	}
	/* dhdpcie_bus_intr_enable: "the fw issues a boot interrupt to indicate its init is complete, hence ... interrupts need to be enabled here itself". Nothing takes it: INTx is off, MSI was never on, this polls the status */
	if (cfg_rd(p, C_COMMAND, &v) || cfg_wr(p, C_COMMAND, v | CMD_MASTER | CMD_INTX_OFF)) {
		return (int)p->stop;
	}
	p->bus_master_on = true;
	if (pcie_wr(p, P_MBOX_INT, MBOX_D2H) || pcie_wr(p, P_MBOX_MASK, MBOX_D2H)) {
		return (int)p->stop;
	}
	if (release_arm(p)) {
		return (int)p->stop;
	}
	return wait_ready(p) ? (int)p->stop : read_shared(p);
}

int
b4_fw(struct p1 *p)
{
	int rc = fw_load(p);

	if (p->ep_mem_on && (rc == P1_STOP_NO_SHARED || rc == P1_STOP_BAD_SHARED || rc == P1_STOP_ARM_RELEASE || (rc == 0 && p->arm_released))) {
		b4_diag(p);
	}
	return rc;
}

#endif /* BLAZER */
