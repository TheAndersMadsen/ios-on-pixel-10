#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * S5400 modem rungs 0..3: pads, PCIe0 controller, CP power-on from off, the CP boot ROM's gen 1 link and its config ID.
 * Own code. The order is stock's, read from the vendor CPIF (modem_ctrl_s5100.c power_on_cp/gpio_power_offon_cp,
 * s5100_poweron_pcie with LINK_MODE_MIN_SPEED_BOOTING) and google-pcie as blazer_pcie1.c already follows it (GPL, facts only).
 * Physical facts it stands on (Android 16 on this phone, research/ios26-dualboot-r8/attempts/chooser-v1-r3-t1/android/dmesg.txt):
 *   8.034742 SET GPIO AP2CP_CP_WRST_N = 0 (dup 1) ... 8.067140 AP2CP_CP_WRST_N = 1: CP power-on from the off state, 32 ms
 *   8.305563 "google-pcie c500000.pcie: Link up", 8.314724 "[144d:a5a5] type 00 class 0x028000", 8.324753 "PCIe gen1 linkup with CP ROM succeed."
 * Everything before BL1 (set_cp_rom_boot_img) needs no firmware: that is where this file stops. */
#include "blazer_hw_port.h"
#include "blazer_modem_core.h"

/* Polled CPM channel, as blazer_pcie1.c (touch's sequence, physical) */
#define MBA_MAGIC_PA    0x05250000ULL
#define MBA_MAGIC       0x004d4241u
#define MBA_PAGE        0x05272000ULL
#define MBA_GO          0x00u
#define MBA_CTL         0x04u
#define MBA_ST          0x08u
#define MBA_MSG         0x100u
#define MBA_CTL_BIT24   0x01000000u
#define MBA_REPLY_BIT   0x00400000u
#define MBA_POLLS       1001u
#define MBA_POLL_US     200u

#define LPB_GET         0x05000003u
#define LPB_ST_ON       2u
/* LPB ids = FDT sswrp-id (HSIO_S 0x18 = 24 is physical in blazer_pcie1.c, LSIO_N 29 too) */
#define LPB_HSIO_N      0x17u
#define LPB_HSIO_S      0x18u
#define LPB_LSIO_E      0x1cu
#define LPB_LSIO_S      0x1eu

#define LPCM_HDR        0x08000000u
/* Byte 0 command, byte 1 LPCM selector (sswrp for power, lpcm-id for clocks/resets), byte 2 id, byte 3 on/deassert */
#define PD_PCIE0_ON     0x01010201u     /* power, LPCM_GENPD_SSWRP_HSIO_N 2 (lga_cpm_mappings.c), hsio_n_pcie_pd subdomain-id 1, on. PCIe1's 0x01010101 is physical */
#define CLK_PHYFW_PUT   0x00030502u     /* put, lpcm 5, hsion_phy_fw_clk clock-id 3, aux 1: the shim's lpcm_put form (USB clocks, physical) */
#define CLK_PHYFW_AUX   1u
#define RST0_INIT       0x01020504u     /* reset, lpcm 5 (hsion_resets), FDT reset 2 "init", deassert */
#define RST0_POWER_UP   0x01030504u     /* reset 3 */
#define RST0_PERST      0x01000504u     /* reset 0 */
#define RST0_APP_HOLD   0x01010504u     /* reset 1 */

/* FDT reg-names of pcie@c500000 */
#define SII             0x0c500000ULL
#define TOP             0x0c520000ULL
#define PHY_SRAM        0x0c550000ULL
#define PHY_SRAM_SIZE   0xa000u
#define DBI             0x0c800000ULL
#define ATU             0x0cb00000ULL
#define CFG             0x40000000ULL
#define CFG_SIZE        0x100000u

/* Same IP and driver as PCIe1 (compatible "google,lga-pcie"): the register offsets are blazer_pcie1.c's */
#define T_PHY_CFG1      0x00u
#define  PG_MODE_EN     (1u << 0)
#define  SRAM_EXT_LD    (1u << 23)
#define T_PHY_STATUS1   0x10u
#define  SRAM_INIT_DONE (1u << 2)
#define T_CTL_CFG1      0x14u
#define  LTSSM_ENABLE   (1u << 0)
#define T_CTL_STATUS1   0x18u
#define  LINKUP         (3u << 6)
#define T_AXI_QOS       0x24u
#define  AXI_VC_MASK    0x3fu
#define  AXI_VC_1       0x09u
#define T_PIPE_STATUS   0x70u
#define S_PM_STATE      0x28u
#define  PM_LTSSM(v)    (((v) >> 3) & 0x3fu)
#define LTSSM_L0        0x11u
#define LTSSM_L2_IDLE   0x15u

#define D_ID            0x00u
#define D_COMMAND       0x04u
#define  CMD_ENABLE     0x107u
#define D_BAR0          0x10u
#define D_BAR1          0x14u
#define D_BUSES         0x18u
#define  BUSES_0_1_FF   0x00ff0100u
#define D_CAP_PTR       0x34u
#define  CAP_ID_EXP     0x10u
#define  E_LNKCAP       0x0cu
#define  E_LNKCTL       0x10u
#define  E_LNKCTL2      0x30u
#define D_LINK_CTRL     0x710u
#define  LC_DLE         (1u << 5)
#define  LC_FLM         (1u << 7)
#define  LC_LANES_MASK  (0x3fu << 16)
#define  LC_1_LANE      (1u << 16)
#define D_DEBUG1        0x72cu
#define  IN_TRAINING    (1u << 29)
#define D_P_RX_Q        0x748u
#define  P_CREDIT_MASK  0xfffu
#define  P_CREDITS      0x51u           /* FDT google,posted-rx-q-data-credits, both controllers */
#define D_WIDTH_SPEED   0x80cu
#define  WS_WIDTH_MASK  (0x1fu << 8)
#define  WS_1_LANE      (1u << 8)
#define  WS_SPEED_CHANGE (1u << 17)
#define D_GEN3          0x890u
#define  GEN3_EQ_OFF    (1u << 16)      /* FDT google,skip-link-equalization */
#define D_MISC1         0x8bcu
#define  DBI_RO_WR      (1u << 0)

#define A_CTRL1         0x00u
#define  A_TYPE_CFG0    4u
#define A_CTRL2         0x04u
#define  A_ENABLE       (1u << 31)
#define A_BASE_LO       0x08u
#define A_BASE_HI       0x0cu
#define A_LIMIT_LO      0x10u
#define A_TARGET_LO     0x14u
#define  A_BUS_1        (1u << 24)
#define A_TARGET_HI     0x18u
#define A_LIMIT_HI      0x20u
#define ATU_POLLS       5u
#define ATU_POLL_US     9000u

/* Pads: one 4 KiB page each (pinctrl-lga.c LGA_PIN_SIZE), PARAM/DMUX/TX/RX at 0/4/8/0x10 */
#define PAD_STRIDE      0x1000u
#define P_PARAM         0x00u
#define P_DMUX          0x04u
#define P_TX            0x08u
#define P_RX            0x10u
#define DMUX_GPIO       0x01u           /* f0 = *_gpio on every pad used here (pinctrl-lga.c), DMUX = function + 1 as on PCIe1's pads */
#define DMUX_PCIE0      0x02u           /* XHSION_PCIE0_CLKREQN0 f1 = hsion_pcie0 */
#define PARAM_DRV_MASK  0x0fu           /* FDT drive-strength 0 */
#define PARAM_IE        (1u << 8)       /* FDT input-enable */
#define TX_PUPD_MASK    0x03u           /* FDT bias-disable */
#define TX_DOUT         (1u << 2)
#define TX_OE           (1u << 3)

#define HSION_BASE      0x0c580000ULL   /* pinctrl hsion, size 0xc000 */
#define HSIOS_BASE      0x3c590000ULL   /* pinctrl hsios, size 0xf000. Pads 0 and 8 are UFS's, 0x0a..0x0d Wi-Fi's: never named here */
#define LSIOE_BASE      0x3a200000ULL   /* size 0x20000 */
#define LSIOS_BASE      0x3be00000ULL   /* size 0x37000 */
#define CPM_PAD_BASE    0x05280000ULL   /* size 0x39000; read physically by keys-probe-r1 */

const struct m0_pad m0_pads[M0_PADS] = {
	[M0_PAD_NRESET]       = { "AP2CP_NRESET",       HSIOS_BASE,   0x02, M0_DOM_HSIO_S, true },
	[M0_PAD_DUMP_NOTI]    = { "AP2CP_DUMP_NOTI",    HSIOS_BASE,   0x03, M0_DOM_HSIO_S, true },
	[M0_PAD_AP_ACTIVE]    = { "AP2CP_AP_ACTIVE",    HSIOS_BASE,   0x04, M0_DOM_HSIO_S, true },
	[M0_PAD_PM_WRST]      = { "AP2CP_PM_WRST_N",    HSIOS_BASE,   0x05, M0_DOM_HSIO_S, true },
	[M0_PAD_CP_PWR]       = { "AP2CP_CP_PWR_ON",    HSIOS_BASE,   0x06, M0_DOM_HSIO_S, true },
	[M0_PAD_CP_WRST]      = { "AP2CP_CP_WRST_N",    HSIOS_BASE,   0x07, M0_DOM_HSIO_S, true },
	[M0_PAD_PARTIAL_RST]  = { "AP2CP_PARTIAL_RST_N", LSIOE_BASE,  0x0e, M0_DOM_LSIO_E, true },
	[M0_PAD_AP2CP_WAKEUP] = { "AP2CP_WAKEUP",       LSIOS_BASE,   0x26, M0_DOM_LSIO_S, false },
	[M0_PAD_CP2AP_ACTIVE] = { "CP2AP_PHONE_ACTIVE", CPM_PAD_BASE, 0x0b, M0_DOM_CPM,    false },
	[M0_PAD_CP2AP_WAKEUP] = { "CP2AP_WAKEUP",       CPM_PAD_BASE, 0x19, M0_DOM_CPM,    false },
	[M0_PAD_CP2AP_WRST]   = { "CP2AP_CP_WRST_N",    CPM_PAD_BASE, 0x1a, M0_DOM_CPM,    false },
	[M0_PAD_CLKREQ]       = { "PCIE0_CLKREQ",       HSION_BASE,   0x00, M0_DOM_HSIO_N, true },
	[M0_PAD_PERST]        = { "PCIE0_PERST",        HSION_BASE,   0x02, M0_DOM_HSIO_N, true },
};

/* Timings. Stock's, from the vendor source and Android's log */
#define CP_OFF_PWR_MS   30u             /* gpio_power_off_cp: CP_PWR 0, wait 30 */
#define CP_OFF_PM_MS    50u             /* PM_WRST 0, wait 50 */
#define CP_ON_STEP_MS   10u             /* gpio_power_offon_cp: PM_WRST 1, CP_PWR 1, NRESET 1: 10 ms each, then CP_WRST 1 */
#define CP_ROM_MS       2u              /* Android: CP_WRST 1 at 8.067140, register_pcie at 8.069083 */
#define SRAM_POLLS      100u
#define SRAM_POLL_US    100u
#define PERST_US        20000u          /* FDT google,perst-delay-us of pcie@c500000 */
#define LINK_ATTEMPTS   4u
#define LINK_POLLS      1000u
#define LINK_POLL_US    100u            /* 100 ms an attempt. Android: about 236 ms from register_pcie to "Link up", PERST included */
#define ID_WAIT_MS      100u
#define ID_TRIES        10u
#define ID_RETRY_MS     100u

static int
halt(struct m0 *m, uint32_t code, uint32_t detail)
{
	if (m->stop == M0_OK) {
		m->stop = code;
		m->stop_detail = detail;
		m->ops.log(m->ops.ctx, "stopped: %s, detail 0x%x\n", m0_stop_name(code), detail);
	}
	return (int)m->stop;
}

const char *
m0_stop_name(uint32_t stop)
{
	static const char *const names[M0_STOP_COUNT] = {
		"ok", "refused address", "refused frame", "no window", "mailbox magic", "mailbox timeout", "mailbox reply",
		"HSIO_N domain not on", "HSIO_S domain not on", "phy_fw clock put", "PCIe0 power vote", "reset vote", "controller already live",
		"PHY SRAM never ready", "PHY table size", "root port reads dead", "no PCIe capability", "pad readback", "CP not off as found",
		"link never came up", "ATU never enabled", "link dropped", "no ID from the endpoint", "not Samsung",
	};
	return stop < M0_STOP_COUNT ? names[stop] : "?";
}

const char *
m0_at_name(uint32_t at)
{
	static const char *const names[] = { "none", "read", "ctrl", "phy", "cp-on", "link", "id" };
	return at < sizeof(names) / sizeof(names[0]) ? names[at] : "?";
}

static bool in(uint64_t pa, uint64_t base, uint64_t size) { return pa >= base && pa - base < size; }
static uint64_t pad_reg(uint32_t i, uint32_t reg) { return m0_pads[i].base + (uint64_t)m0_pads[i].pad * PAD_STRIDE + reg; }

/* cp_rmem 0xea400000+0xc00000, cp_msi_rmem 0xf6200000+0x1000, cp_rmem_1 0xe8000000+0x2000000, cp_aoc_rmem 0x0900c000+0x3000 (FDT reserved-memory) */
bool
m0_is_cp_memory(uint64_t pa)
{
	return in(pa, 0xea400000ULL, 0xc00000u) || in(pa, 0xf6200000ULL, 0x1000u) || in(pa, 0xe8000000ULL, 0x2000000u) || in(pa, 0x0900c000ULL, 0x3000u);
}

/* Which pad, if any, this address is in. reg: which of its registers */
static int
pad_of(uint64_t pa, uint32_t *reg)
{
	for (int i = 0; i < M0_PADS; i++) {
		uint64_t b = pad_reg((uint32_t)i, 0);

		if (pa == b + P_PARAM || pa == b + P_DMUX || pa == b + P_TX || pa == b + P_RX) {
			*reg = (uint32_t)(pa - b);
			return i;
		}
	}
	return -1;
}

static bool
endpoint_cfg_read_ok(uint32_t off)
{
	/* Read only, never written: ID, class/rev, header type, subsystem, capability pointer, and the capability list in the header page */
	return off == 0x00 || off == 0x08 || off == 0x0c || off == 0x2c || off == 0x34 || (off >= 0x40 && off < 0x100 && (off & 3u) == 0);
}

bool
m0_read_allowed(const struct m0 *m, uint64_t pa)
{
	uint32_t reg = 0;
	int pad;

	if (m0_is_cp_memory(pa)) {
		return false;
	}
	if (pa == MBA_MAGIC_PA || pa == MBA_PAGE + MBA_CTL || pa == MBA_PAGE + MBA_ST || in(pa, MBA_PAGE + MBA_MSG, 16)) {
		return true;
	}
	if ((pad = pad_of(pa, &reg)) >= 0) {
		return m->dom_on[m0_pads[pad].domain];
	}
	if (pa == TOP + T_PHY_CFG1 || pa == TOP + T_PHY_STATUS1 || pa == TOP + T_CTL_CFG1 || pa == TOP + T_CTL_STATUS1 || pa == TOP + T_AXI_QOS || pa == TOP + T_PIPE_STATUS) {
		return m->out_of_reset;
	}
	if (pa == SII + S_PM_STATE || in(pa, DBI, 0xd00) || in(pa, ATU, 0x24)) {
		return m->rc_ready;
	}
	if (in(pa, CFG, 0x1000)) {
		return m->link_up && m->atu_on && endpoint_cfg_read_ok((uint32_t)(pa - CFG));
	}
	return false;
}

bool
m0_write_allowed(const struct m0 *m, uint64_t pa)
{
	uint32_t reg = 0;
	int pad;

	if (m0_is_cp_memory(pa)) {
		return false;
	}
	if (pa == MBA_PAGE + MBA_GO || pa == MBA_PAGE + MBA_CTL || pa == MBA_PAGE + MBA_ST || in(pa, MBA_PAGE + MBA_MSG, 16)) {
		return true;
	}
	if ((pad = pad_of(pa, &reg)) >= 0) {
		/* Output pads only, never RX, only from stage LINK, only with their domain on */
		return m0_pads[pad].out && reg != P_RX && m->dom_on[m0_pads[pad].domain] && m->cfg.stage >= M0_STAGE_LINK;
	}
	if (pa == TOP + T_PHY_CFG1 || pa == TOP + T_AXI_QOS) {
		return m->out_of_reset && m->cfg.stage >= M0_STAGE_PHY;
	}
	if (pa == TOP + T_CTL_CFG1) {
		return m->rc_ready && m->cfg.stage >= M0_STAGE_LINK;
	}
	if (pa == DBI + D_COMMAND || pa == DBI + D_BAR0 || pa == DBI + D_BAR1 || pa == DBI + D_BUSES || pa == DBI + D_LINK_CTRL || pa == DBI + D_P_RX_Q ||
	    pa == DBI + D_WIDTH_SPEED || pa == DBI + D_GEN3 || pa == DBI + D_MISC1 ||
	    (m->pcie_cap != 0 && (pa == DBI + m->pcie_cap + E_LNKCAP || pa == DBI + m->pcie_cap + E_LNKCTL2))) {
		return m->rc_ready && m->cfg.stage >= M0_STAGE_PHY;
	}
	if (pa == ATU + A_CTRL1 || pa == ATU + A_CTRL2 || pa == ATU + A_BASE_LO || pa == ATU + A_BASE_HI || pa == ATU + A_LIMIT_LO || pa == ATU + A_TARGET_LO ||
	    pa == ATU + A_TARGET_HI || pa == ATU + A_LIMIT_HI) {
		return m->link_up;
	}
	return false;   /* No endpoint config write, no BAR, no CP memory, no other pad */
}

static int
rd(struct m0 *m, uint64_t pa, uint32_t *v)
{
	if (m->stop != M0_OK) {
		return (int)m->stop;
	}
	if (!m0_read_allowed(m, pa)) {
		return halt(m, M0_STOP_REFUSED_PA, (uint32_t)pa);
	}
	if (m->ops.read32(m->ops.ctx, pa, v) != 0) {
		return halt(m, M0_STOP_FAULT, (uint32_t)pa);
	}
	return 0;
}

static int
wr(struct m0 *m, uint64_t pa, uint32_t v)
{
	if (m->stop != M0_OK) {
		return (int)m->stop;
	}
	if (!m0_write_allowed(m, pa)) {
		return halt(m, M0_STOP_REFUSED_PA, (uint32_t)pa);
	}
	if (m->ops.write32(m->ops.ctx, pa, v) != 0) {
		return halt(m, M0_STOP_FAULT, (uint32_t)pa);
	}
	return 0;
}

static int
rmw(struct m0 *m, uint64_t pa, uint32_t clear, uint32_t set)
{
	uint32_t v = 0, n;
	int rc = rd(m, pa, &v);

	if (rc) {
		return rc;
	}
	n = (v & ~clear) | set;
	return n != v ? wr(m, pa, n) : 0;
}

/* Every frame this file can send. Nothing that turns anything off */
static bool
frame_allowed(const struct m0 *m, uint32_t w0, uint32_t w1, uint32_t w2)
{
	if (w0 == LPB_GET) {
		return w2 == 0 && (w1 == LPB_HSIO_N || w1 == LPB_HSIO_S || w1 == LPB_LSIO_E || w1 == LPB_LSIO_S);
	}
	if (w0 != LPCM_HDR || !m->dom_on[M0_DOM_HSIO_N] || m->cfg.stage < M0_STAGE_CTRL) {
		return false;
	}
	if (w1 == CLK_PHYFW_PUT) {
		return w2 == CLK_PHYFW_AUX;
	}
	if (w2 != 0) {
		return false;
	}
	if (w1 == PD_PCIE0_ON || w1 == RST0_INIT || w1 == RST0_POWER_UP || w1 == RST0_PERST) {
		return true;
	}
	return w1 == RST0_APP_HOLD && m->cfg.stage >= M0_STAGE_PHY;
}

static int
mba_locked(struct m0 *m, uint32_t w0, uint32_t w1, uint32_t w2, uint32_t r[4])
{
	uint32_t v = 0, ctl = 0;
	unsigned n = 0;

	if (m->stop != M0_OK) {
		return (int)m->stop;
	}
	if (!frame_allowed(m, w0, w1, w2)) {
		return halt(m, M0_STOP_REFUSED_FRAME, w1);
	}
	m->frames++;
	if (wr(m, MBA_PAGE + MBA_ST, 1) || rd(m, MBA_PAGE + MBA_ST, &v) || rd(m, MBA_PAGE + MBA_CTL, &ctl) || wr(m, MBA_PAGE + MBA_CTL, ctl | MBA_CTL_BIT24) ||
	    wr(m, MBA_PAGE + MBA_MSG, w0) || wr(m, MBA_PAGE + MBA_MSG + 4, w1) || wr(m, MBA_PAGE + MBA_MSG + 8, w2) || wr(m, MBA_PAGE + MBA_MSG + 12, 0) ||
	    wr(m, MBA_PAGE + MBA_GO, 1) || rd(m, MBA_PAGE + MBA_ST, &v)) {
		return (int)m->stop;
	}
	while (!(v & 1u)) {
		if (++n >= MBA_POLLS) {
			return halt(m, M0_STOP_MBA_TIMEOUT, w1);
		}
		m->ops.delay_us(m->ops.ctx, MBA_POLL_US);
		if (rd(m, MBA_PAGE + MBA_ST, &v)) {
			return (int)m->stop;
		}
	}
	for (unsigned i = 0; i < 4; i++) {
		if (rd(m, MBA_PAGE + MBA_MSG + 4 * i, &r[i])) {
			return (int)m->stop;
		}
	}
	if (wr(m, MBA_PAGE + MBA_ST, 1) || rd(m, MBA_PAGE + MBA_ST, &v)) {
		return (int)m->stop;
	}
	if (r[0] != (w0 | MBA_REPLY_BIT)) {
		return halt(m, M0_STOP_MBA_REPLY, r[0]);
	}
	return 0;
}

static int
mba(struct m0 *m, uint32_t w0, uint32_t w1, uint32_t w2, uint32_t r[4])
{
	int rc;

	if (m->ops.cpm_enter != NULL) {
		m->ops.cpm_enter(m->ops.ctx);
	}
	rc = mba_locked(m, w0, w1, w2, r);
	if (m->ops.cpm_exit != NULL) {
		m->ops.cpm_exit(m->ops.ctx);
	}
	return rc;
}

static int
lpcm(struct m0 *m, uint32_t w1, uint32_t w2, uint32_t bad_stop)
{
	uint32_t r[4] = {0};
	int rc = mba(m, LPCM_HDR, w1, w2, r);

	if (rc) {
		return rc;
	}
	if (r[1] != 0) {
		return halt(m, bad_stop, r[1]);
	}
	return 0;
}

static void ms(struct m0 *m, uint32_t n) { m->ops.delay_us(m->ops.ctx, n * 1000u); }

/* ---- Stage READ ---- */

static int
read_pad(struct m0 *m, int i)
{
	static const uint32_t regs[4] = { P_PARAM, P_DMUX, P_TX, P_RX };
	uint32_t *o = m->found[i];

	for (unsigned k = 0; k < 4; k++) {
		if (rd(m, pad_reg((uint32_t)i, regs[k]), &o[k])) {
			return (int)m->stop;
		}
	}
	m->found_ok[i] = true;
	m->ops.log(m->ops.ctx, "pad %s (0x%llx) param 0x%x dmux 0x%x tx 0x%x rx 0x%x: %s\n", m0_pads[i].name, (unsigned long long)pad_reg((uint32_t)i, 0),
	    o[0], o[1], o[2], o[3], !(o[2] & TX_OE) ? "not driven" : (o[2] & TX_DOUT) ? "driven high" : "driven low");
	return 0;
}

/* Off: not driven, or driven low. What gpio_power_off_cp leaves, and the precondition for stock's power_on_cp from STATE_OFFLINE */
static bool
pad_low(const struct m0 *m, int i)
{
	return m->found_ok[i] && (!(m->found[i][2] & TX_OE) || !(m->found[i][2] & TX_DOUT));
}

static int
stage_read(struct m0 *m)
{
	static const struct { uint32_t id; int dom; const char *name; } doms[] = {
		{ LPB_HSIO_N, M0_DOM_HSIO_N, "HSIO_N" }, { LPB_HSIO_S, M0_DOM_HSIO_S, "HSIO_S" }, { LPB_LSIO_E, M0_DOM_LSIO_E, "LSIO_E" }, { LPB_LSIO_S, M0_DOM_LSIO_S, "LSIO_S" },
	};
	uint32_t v = 0, r[4];

	if (rd(m, MBA_MAGIC_PA, &v)) {
		return (int)m->stop;
	}
	if (v != MBA_MAGIC) {
		return halt(m, M0_STOP_MBA_MAGIC, v);
	}
	for (unsigned i = 0; i < sizeof(doms) / sizeof(doms[0]); i++) {
		memset(r, 0, sizeof(r));
		if (mba(m, LPB_GET, doms[i].id, 0, r)) {
			return (int)m->stop;
		}
		m->dom_state[doms[i].dom] = r[1];
		m->dom_on[doms[i].dom] = r[1] == LPB_ST_ON;
		m->ops.log(m->ops.ctx, "read: %s state %u%s\n", doms[i].name, r[1], r[1] == LPB_ST_ON ? "" : ": its pads stay unread");
	}
	m->dom_state[M0_DOM_CPM] = LPB_ST_ON;
	m->dom_on[M0_DOM_CPM] = true;
	for (int i = 0; i < M0_PADS; i++) {
		if (m->dom_on[m0_pads[i].domain] && read_pad(m, i)) {
			return (int)m->stop;
		}
	}
	m->cp_off_found = pad_low(m, M0_PAD_NRESET) && pad_low(m, M0_PAD_PM_WRST) && pad_low(m, M0_PAD_CP_PWR) && pad_low(m, M0_PAD_CP_WRST);
	m->ops.log(m->ops.ctx, "read: CP as found: %s\n", m->cp_off_found ? "off (power, resets low)" : "NOT off, or a pad unread");
	m->at = M0_AT_READ;
	return 0;
}

/* ---- Stage CTRL: google_pcie runtime_resume's first half, for pcie@c500000 ---- */

static int
stage_ctrl(struct m0 *m)
{
	uint32_t v = 0, cfg1 = 0, ctl = 0, st = 0;

	if (!m->dom_on[M0_DOM_HSIO_N]) {
		return halt(m, M0_STOP_HSIO_N_OFF, m->dom_state[M0_DOM_HSIO_N]);
	}
	m->ops.log(m->ops.ctx, "ctrl: next: phy_fw clock put (lpcm 5 clock 3)\n");
	if (lpcm(m, CLK_PHYFW_PUT, CLK_PHYFW_AUX, M0_STOP_CLOCK)) {
		return (int)m->stop;
	}
	m->clock_on = true;
	m->ops.log(m->ops.ctx, "ctrl: next: PCIe0 power vote (HSIO_N subdomain 1)\n");
	if (lpcm(m, PD_PCIE0_ON, 0, M0_STOP_POWER_VOTE)) {
		return (int)m->stop;
	}
	m->domain_on = true;
	m->ops.log(m->ops.ctx, "ctrl: PCIe0 domain voted on. Next: resets init, power_up, perst\n");
	if (lpcm(m, RST0_INIT, 0, M0_STOP_RESET_VOTE) || lpcm(m, RST0_POWER_UP, 0, M0_STOP_RESET_VOTE) || lpcm(m, RST0_PERST, 0, M0_STOP_RESET_VOTE)) {
		return (int)m->stop;
	}
	m->out_of_reset = true;
	m->ops.log(m->ops.ctx, "ctrl: resets released. Next: first read of PCIe0, top + 0x10\n");
	for (unsigned i = 0;; i++) {
		if (rd(m, TOP + T_PHY_STATUS1, &v)) {
			return (int)m->stop;
		}
		if (v & SRAM_INIT_DONE) {
			m->ops.log(m->ops.ctx, "ctrl: PHY SRAM ready after %u polls, status 0x%x\n", i, v);
			break;
		}
		if (i >= SRAM_POLLS) {
			return halt(m, M0_STOP_SRAM_INIT, v);
		}
		m->ops.delay_us(m->ops.ctx, SRAM_POLL_US);
	}
	m->sram_ready = true;
	if (rd(m, TOP + T_PHY_CFG1, &cfg1) || rd(m, TOP + T_CTL_CFG1, &ctl) || rd(m, TOP + T_CTL_STATUS1, &st)) {
		return (int)m->stop;
	}
	m->ops.log(m->ops.ctx, "ctrl: PHY cfg 0x%x, LTSSM enable reg 0x%x, status 0x%x\n", cfg1, ctl, st);
	if (((cfg1 & SRAM_EXT_LD) != 0 || (ctl & LTSSM_ENABLE) != 0) && !m->cfg.force) {
		return halt(m, M0_STOP_ALREADY_LIVE, cfg1);
	}
	m->at = M0_AT_CTRL;
	return 0;
}

/* ---- Stage PHY: the PHY table, app_hold_phy, then dw_pcie_setup_rc and stock's poweron writes, as blazer_pcie1.c ---- */

static int
stage_phy(struct m0 *m)
{
	uint32_t v = 0, at = 0, lnkcap = 0;

	if (m->cfg.phy == NULL || m->cfg.phy_words * 2 != PHY_SRAM_SIZE) {
		return halt(m, M0_STOP_PHY_TABLE, m->cfg.phy_words);
	}
	if (!m->sram_ready) {
		return halt(m, M0_STOP_REFUSED_PA, (uint32_t)PHY_SRAM);
	}
	m->ops.log(m->ops.ctx, "phy: next: table, %u words, first 0x%04x, last 0x%04x\n", m->cfg.phy_words, m->cfg.phy[0], m->cfg.phy[m->cfg.phy_words - 1]);
	for (uint32_t i = 0; i < m->cfg.phy_words; i++) {
		if (m->ops.write16(m->ops.ctx, PHY_SRAM + 2 * (uint64_t)i, m->cfg.phy[i]) != 0) {
			return halt(m, M0_STOP_FAULT, (uint32_t)(PHY_SRAM + 2 * i));
		}
	}
	m->ops.barrier(m->ops.ctx);
	m->phy_loaded = true;
	if (rmw(m, TOP + T_PHY_CFG1, 0, SRAM_EXT_LD) || rmw(m, TOP + T_PHY_CFG1, 0, PG_MODE_EN)) {
		return (int)m->stop;
	}
	m->ops.log(m->ops.ctx, "phy: table in, PHY told. Next: reset app_hold_phy\n");
	if (lpcm(m, RST0_APP_HOLD, 0, M0_STOP_RESET_VOTE) || rmw(m, TOP + T_AXI_QOS, AXI_VC_MASK, AXI_VC_1)) {
		return (int)m->stop;
	}
	m->rc_ready = true;
	if (rd(m, DBI + D_ID, &m->rc_id)) {
		return (int)m->stop;
	}
	if (m->rc_id == 0 || m->rc_id == 0xffffffffu) {
		return halt(m, M0_STOP_RC_DEAD, m->rc_id);
	}
	if (rd(m, DBI + D_CAP_PTR, &v)) {
		return (int)m->stop;
	}
	at = v & 0xfcu;
	for (unsigned i = 0; at != 0 && i < 48; i++) {
		if (rd(m, DBI + at, &v)) {
			return (int)m->stop;
		}
		if ((v & 0xffu) == CAP_ID_EXP) {
			m->pcie_cap = at;
			break;
		}
		at = (v >> 8) & 0xfcu;
	}
	if (m->pcie_cap == 0) {
		return halt(m, M0_STOP_NO_PCIE_CAP, v);
	}
	if (rd(m, DBI + m->pcie_cap + E_LNKCAP, &lnkcap)) {
		return (int)m->stop;
	}
	m->ops.log(m->ops.ctx, "rc: id 0x%08x, PCIe capability at 0x%x, lnkcap 0x%08x. Next: set up for gen 1 x1 (stock's CP ROM boot mode)\n", m->rc_id, m->pcie_cap, lnkcap);
	if (rmw(m, DBI + D_MISC1, 0, DBI_RO_WR) ||
	    rmw(m, DBI + m->pcie_cap + E_LNKCTL2, 0xfu, 1u) || rmw(m, DBI + m->pcie_cap + E_LNKCAP, 0xfu, 1u) ||
	    rmw(m, DBI + D_LINK_CTRL, LC_FLM | LC_LANES_MASK, LC_DLE | LC_1_LANE) || rmw(m, DBI + D_WIDTH_SPEED, WS_WIDTH_MASK, WS_1_LANE) ||
	    rmw(m, DBI + m->pcie_cap + E_LNKCAP, 0x3fu << 4, 1u << 4) ||
	    wr(m, DBI + D_BAR0, 4) || wr(m, DBI + D_BAR1, 0) || rmw(m, DBI + D_BUSES, 0x00ffffffu, BUSES_0_1_FF) || rmw(m, DBI + D_COMMAND, 0xffffu, CMD_ENABLE) ||
	    wr(m, DBI + D_BAR0, 0) || rmw(m, DBI + D_WIDTH_SPEED, 0, WS_SPEED_CHANGE) || rmw(m, DBI + D_MISC1, DBI_RO_WR, 0) ||
	    rmw(m, DBI + D_GEN3, 0, GEN3_EQ_OFF) || rmw(m, DBI + D_P_RX_Q, P_CREDIT_MASK, P_CREDITS)) {
		return (int)m->stop;
	}
	m->ops.log(m->ops.ctx, "rc: set up\n");
	m->at = M0_AT_PHY;
	return 0;
}

/* ---- Stage LINK ---- */

/* pinctrl_select_state's order: mux, PARAM, TX, each only if it changes; read back */
static int
pad_set(struct m0 *m, int i, uint32_t mux, bool out, bool high)
{
	uint32_t want = (out ? TX_OE : 0) | (out && high ? TX_DOUT : 0), mask = TX_PUPD_MASK | TX_OE | (out ? TX_DOUT : 0), v = 0;

	if (!m0_pads[i].out) {
		return halt(m, M0_STOP_REFUSED_PA, (uint32_t)pad_reg((uint32_t)i, P_TX));
	}
	m->driven[i] = true;
	if (rmw(m, pad_reg((uint32_t)i, P_DMUX), 0xffffffffu, mux) || rmw(m, pad_reg((uint32_t)i, P_PARAM), PARAM_DRV_MASK | PARAM_IE, PARAM_IE) ||
	    rmw(m, pad_reg((uint32_t)i, P_TX), mask, want)) {
		return (int)m->stop;
	}
	if (rd(m, pad_reg((uint32_t)i, P_DMUX), &v)) {
		return (int)m->stop;
	}
	if (v != mux) {
		return halt(m, M0_STOP_PAD, (uint32_t)i << 16 | v);
	}
	if (rd(m, pad_reg((uint32_t)i, P_TX), &v)) {
		return (int)m->stop;
	}
	if ((v & mask) != want) {
		return halt(m, M0_STOP_PAD, (uint32_t)i << 16 | v);
	}
	return 0;
}

static int
gpio(struct m0 *m, int i, bool high, uint32_t wait_ms)
{
	if (pad_set(m, i, DMUX_GPIO, true, high)) {
		return (int)m->stop;
	}
	if (wait_ms) {
		ms(m, wait_ms);
	}
	return 0;
}

/* modem_ctrl_s5100.c power_on_cp, from STATE_OFFLINE: AP_ACTIVE 1, DUMP_NOTI 0, PARTIAL_RST 1; gpio_power_offon_cp (S5910 build,
 * no CP_WRESET_WA): the off half (from off: no change, so no waits), then PM_WRST 1, CP_PWR 1, NRESET 1 with 10 ms each, CP_WRST 1.
 * Android's log has exactly this: CP_WRST 0 and PM_WRST 0 are "dup", and 32 ms from there to CP_WRST 1. The S5910 clock buffer's
 * SPMI sequence runs there only when the CP was ever powered (cp_ever_powered_on): never on a first boot, so not here. */
static int
cp_power_on(struct m0 *m)
{
	uint64_t t0;

	if (!m->cp_off_found && !m->cfg.force) {
		return halt(m, M0_STOP_CP_NOT_OFF, (m->found[M0_PAD_CP_PWR][2] & 0xffu) << 8 | (m->found[M0_PAD_CP_WRST][2] & 0xffu));
	}
	m->ops.log(m->ops.ctx, "cp: next: AP_ACTIVE 1, DUMP_NOTI 0%s\n", m->dom_on[M0_DOM_LSIO_E] ? ", PARTIAL_RST_N 1" : " (LSIO_E off: PARTIAL_RST_N left)");
	if (gpio(m, M0_PAD_AP_ACTIVE, true, 0) || gpio(m, M0_PAD_DUMP_NOTI, false, 0)) {
		return (int)m->stop;
	}
	if (m->dom_on[M0_DOM_LSIO_E] && gpio(m, M0_PAD_PARTIAL_RST, true, 0)) {
		return (int)m->stop;
	}
	/* The off half, as stock: each pad to its off level; the wait only if the level changed (it is low already from off) */
	if (gpio(m, M0_PAD_NRESET, false, 0) || gpio(m, M0_PAD_CP_WRST, false, 0) ||
	    gpio(m, M0_PAD_CP_PWR, false, pad_low(m, M0_PAD_CP_PWR) ? 0 : CP_OFF_PWR_MS) || gpio(m, M0_PAD_PM_WRST, false, pad_low(m, M0_PAD_PM_WRST) ? 0 : CP_OFF_PM_MS)) {
		return (int)m->stop;
	}
	m->ops.log(m->ops.ctx, "cp: next: PM_WRST_N 1, CP_PWR_ON 1, NRESET 1, CP_WRST_N 1 (10 ms steps)\n");
	t0 = m->ops.now_us(m->ops.ctx);
	m->cp_on = true;
	if (gpio(m, M0_PAD_PM_WRST, true, CP_ON_STEP_MS) || gpio(m, M0_PAD_CP_PWR, true, CP_ON_STEP_MS) || gpio(m, M0_PAD_NRESET, true, CP_ON_STEP_MS) ||
	    gpio(m, M0_PAD_CP_WRST, true, CP_ROM_MS)) {
		return (int)m->stop;
	}
	m->cp_on_us = (uint32_t)(m->ops.now_us(m->ops.ctx) - t0);
	m->ops.log(m->ops.ctx, "cp: powered, %u us. The CP boot ROM runs; PERST still low\n", m->cp_on_us);
	m->at = M0_AT_CP_ON;
	return 0;
}

static int
ltssm_set(struct m0 *m, bool on)
{
	int rc = rmw(m, TOP + T_CTL_CFG1, on ? 0 : LTSSM_ENABLE, on ? LTSSM_ENABLE : 0);

	if (rc == 0) {
		m->ltssm_on = on;
	}
	return rc;
}

static int
link_is_up(struct m0 *m, bool *up)
{
	uint32_t dbg = 0;

	if (rd(m, TOP + T_CTL_STATUS1, &m->ctl_status) || rd(m, SII + S_PM_STATE, &m->pm_state) || rd(m, DBI + D_DEBUG1, &dbg)) {
		return (int)m->stop;
	}
	*up = (m->ctl_status & LINKUP) == LINKUP && !(dbg & IN_TRAINING) && PM_LTSSM(m->pm_state) >= LTSSM_L0 && PM_LTSSM(m->pm_state) < LTSSM_L2_IDLE;
	return 0;
}

static int
train(struct m0 *m)
{
	uint32_t pipe = 0, sta = 0;
	bool up = false;

	/* CLKREQ to the controller, input: the CP drives it. As Wi-Fi, just before the link */
	if (pad_set(m, M0_PAD_CLKREQ, DMUX_PCIE0, false, false)) {
		return (int)m->stop;
	}
	for (m->attempts = 1; m->attempts <= LINK_ATTEMPTS; m->attempts++) {
		uint64_t t0;

		m->ops.log(m->ops.ctx, "link: attempt %u. Next: PERST high, %u us, LTSSM on\n", m->attempts, PERST_US);
		m->perst_driven = true;
		if (gpio(m, M0_PAD_PERST, true, 0)) {
			return (int)m->stop;
		}
		m->ops.delay_us(m->ops.ctx, PERST_US);
		if (ltssm_set(m, true)) {
			return (int)m->stop;
		}
		t0 = m->ops.now_us(m->ops.ctx);
		for (unsigned i = 0; i < LINK_POLLS; i++) {
			if (link_is_up(m, &up)) {
				return (int)m->stop;
			}
			if (up) {
				break;
			}
			m->ops.delay_us(m->ops.ctx, LINK_POLL_US);
		}
		m->link_us = (uint32_t)(m->ops.now_us(m->ops.ctx) - t0);
		if (up) {
			break;
		}
		if (rd(m, TOP + T_PIPE_STATUS, &pipe)) {
			return (int)m->stop;
		}
		m->ops.log(m->ops.ctx, "link: attempt %u failed after %u us: status 0x%x, pm 0x%x (LTSSM 0x%x), pipe 0x%x\n", m->attempts, m->link_us, m->ctl_status, m->pm_state,
		    PM_LTSSM(m->pm_state), pipe);
		if (gpio(m, M0_PAD_PERST, false, 0) || ltssm_set(m, false)) {
			return (int)m->stop;
		}
		m->ops.delay_us(m->ops.ctx, PERST_US);
	}
	if (!up) {
		return halt(m, M0_STOP_LINK, m->pm_state);
	}
	m->link_up = true;
	if (rd(m, DBI + m->pcie_cap + E_LNKCTL, &sta)) {
		return (int)m->stop;
	}
	m->lnksta = sta >> 16;
	m->ops.log(m->ops.ctx, "link: UP, attempt %u, %u us after LTSSM on: gen %u, x%u, status 0x%x, pm 0x%x\n", m->attempts, m->link_us, m->lnksta & 0xfu, (m->lnksta >> 4) & 0x3fu,
	    m->ctl_status, m->pm_state);
	m->at = M0_AT_LINK;
	return 0;
}

static int
map_bus_1(struct m0 *m)
{
	uint32_t v = 0;

	if (wr(m, ATU + A_BASE_LO, (uint32_t)CFG) || wr(m, ATU + A_BASE_HI, 0) || wr(m, ATU + A_LIMIT_LO, (uint32_t)CFG + CFG_SIZE - 1) || wr(m, ATU + A_LIMIT_HI, 0) ||
	    wr(m, ATU + A_TARGET_LO, A_BUS_1) || wr(m, ATU + A_TARGET_HI, 0) || wr(m, ATU + A_CTRL1, A_TYPE_CFG0) || wr(m, ATU + A_CTRL2, A_ENABLE)) {
		return (int)m->stop;
	}
	for (unsigned i = 0; i < ATU_POLLS; i++) {
		if (rd(m, ATU + A_CTRL2, &v)) {
			return (int)m->stop;
		}
		if (v & A_ENABLE) {
			m->atu_on = true;
			return 0;
		}
		m->ops.delay_us(m->ops.ctx, ATU_POLL_US);
	}
	return halt(m, M0_STOP_ATU, v);
}

/* Identity: config reads only. The S5400's ROM has no IMEI or serial to give; none is asked for or logged */
static int
read_identity(struct m0 *m)
{
	uint32_t id = 0xffffffffu, v = 0, at;
	bool up = false;

	ms(m, ID_WAIT_MS);
	if (map_bus_1(m)) {
		return (int)m->stop;
	}
	for (unsigned i = 0; i < ID_TRIES; i++) {
		if (link_is_up(m, &up)) {
			return (int)m->stop;
		}
		if (!up) {
			return halt(m, M0_STOP_LINK_LOST, m->pm_state);
		}
		if (rd(m, CFG, &id)) {
			return (int)m->stop;
		}
		if (id != 0xffffffffu && id != 0xffff0001u && id != 0) {
			break;
		}
		ms(m, ID_RETRY_MS);
	}
	m->ops.log(m->ops.ctx, "id: read 0x%08x\n", id);
	if (id == 0xffffffffu || id == 0xffff0001u || id == 0) {
		return halt(m, M0_STOP_NO_ID, id);
	}
	if ((id & 0xffffu) != M0_VENDOR_SAMSUNG) {
		return halt(m, M0_STOP_WRONG_VENDOR, id);
	}
	m->ep_id = id;
	m->at = M0_AT_ID;
	if (rd(m, CFG + 0x08, &m->ep_class_rev) || rd(m, CFG + 0x2c, &m->ep_subsys) || rd(m, CFG + 0x34, &v)) {
		return (int)m->stop;
	}
	at = v & 0xfcu;
	for (unsigned i = 0; at >= 0x40 && i < 48; i++) {
		if (rd(m, CFG + at, &v)) {
			return (int)m->stop;
		}
		if ((v & 0xffu) == CAP_ID_EXP) {
			m->ep_cap = at;
			if (at + E_LNKCAP < 0x100 && rd(m, CFG + at + E_LNKCAP, &m->ep_lnkcap)) {
				return (int)m->stop;
			}
			break;
		}
		at = (v >> 8) & 0xfcu;
	}
	for (int k = 0; k < 3; k++) {
		if (rd(m, pad_reg((uint32_t)(M0_PAD_CP2AP_ACTIVE + k), P_RX), &m->cp2ap_after[k])) {
			return (int)m->stop;
		}
	}
	m->ops.log(m->ops.ctx, "id: %04x:%04x class 0x%06x rev 0x%02x subsys 0x%08x, endpoint lnkcap gen %u x%u%s\n", id & 0xffffu, id >> 16, m->ep_class_rev >> 8,
	    m->ep_class_rev & 0xffu, m->ep_subsys, m->ep_lnkcap & 0xfu, (m->ep_lnkcap >> 4) & 0x3fu,
	    (id >> 16) == M0_DEVICE_CP_ROM ? ": S5400 CP boot ROM, as Android reads it" : ": Samsung, but Android reads device a5a5 here");
	m->ops.log(m->ops.ctx, "cp: after link: CP2AP_PHONE_ACTIVE rx 0x%x, CP2AP_WAKEUP rx 0x%x, CP2AP_CP_WRST_N rx 0x%x\n", m->cp2ap_after[0], m->cp2ap_after[1], m->cp2ap_after[2]);
	return 0;
}

static int
stage_link(struct m0 *m)
{
	if (!m->rc_ready || !m->dom_on[M0_DOM_HSIO_S]) {
		return halt(m, m->rc_ready ? M0_STOP_HSIO_S_OFF : M0_STOP_REFUSED_PA, m->dom_state[M0_DOM_HSIO_S]);
	}
	/* PERST held low before the CP gets power, as stock's off link */
	m->perst_driven = true;
	if (gpio(m, M0_PAD_PERST, false, 0)) {
		return (int)m->stop;
	}
	if (cp_power_on(m) || train(m)) {
		return (int)m->stop;
	}
	return read_identity(m);
}

/* Write a driven pad back to what it was found as: TX's OE/DOUT/PUPD, PARAM's drive/IE, then DMUX */
static int
pad_restore(struct m0 *m, int i)
{
	const uint32_t *o = m->found[i];

	if (!m->driven[i] || !m->found_ok[i]) {
		return 0;
	}
	if (rmw(m, pad_reg((uint32_t)i, P_TX), TX_PUPD_MASK | TX_OE | TX_DOUT, o[2] & (TX_PUPD_MASK | TX_OE | TX_DOUT)) ||
	    rmw(m, pad_reg((uint32_t)i, P_PARAM), PARAM_DRV_MASK | PARAM_IE, o[0] & (PARAM_DRV_MASK | PARAM_IE)) || rmw(m, pad_reg((uint32_t)i, P_DMUX), 0xffffffffu, o[1])) {
		return (int)m->stop;
	}
	m->driven[i] = false;
	return 0;
}

/* After a failure, and after success unless held. Link first (PERST, LTSSM, as stock), then the CP off in gpio_power_off_cp's order with its
 * waits, then every pad this run drove back to what it found. Power vote, resets and the clock stay: nothing is voted off */
static void
tidy(struct m0 *m)
{
	uint32_t stop = m->stop, detail = m->stop_detail, bad = 0;
	static const int order[] = { M0_PAD_PERST, M0_PAD_CLKREQ, M0_PAD_CP_WRST, M0_PAD_NRESET, M0_PAD_CP_PWR, M0_PAD_PM_WRST, M0_PAD_PARTIAL_RST, M0_PAD_DUMP_NOTI, M0_PAD_AP_ACTIVE };

	m->stop = M0_OK;
	if (m->perst_driven && gpio(m, M0_PAD_PERST, false, 0)) {
		bad |= 1;
	}
	m->stop = M0_OK;
	if (m->ltssm_on && ltssm_set(m, false)) {
		bad |= 2;
	}
	m->stop = M0_OK;
	if (m->perst_driven) {
		m->ops.delay_us(m->ops.ctx, PERST_US);
	}
	if (m->cp_on) {
		if (gpio(m, M0_PAD_CP_WRST, false, 0)) {
			bad |= 4;
		}
		m->stop = M0_OK;
		if (gpio(m, M0_PAD_NRESET, false, 0)) {
			bad |= 4;
		}
		m->stop = M0_OK;
		if (gpio(m, M0_PAD_CP_PWR, false, CP_OFF_PWR_MS)) {
			bad |= 4;
		}
		m->stop = M0_OK;
		if (gpio(m, M0_PAD_PM_WRST, false, CP_OFF_PM_MS)) {
			bad |= 4;
		}
		m->stop = M0_OK;
		m->cp_on = false;
	}
	for (unsigned k = 0; k < sizeof(order) / sizeof(order[0]); k++) {
		if (pad_restore(m, order[k])) {
			bad |= 8;
		}
		m->stop = M0_OK;
	}
	m->link_up = m->atu_on = false;
	m->perst_driven = false;
	m->ops.log(m->ops.ctx, "tidy: PERST low, LTSSM off, CP off (CP_WRST, NRESET, CP_PWR 30 ms, PM_WRST 50 ms), pads as found, errors 0x%x\n", bad);
	m->stop = stop;
	m->stop_detail = detail;
}

void
m0_init(struct m0 *m, const struct m0_ops *ops, const struct m0_cfg *cfg)
{
	memset(m, 0, sizeof(*m));
	m->ops = *ops;
	m->cfg = *cfg;
	if (m->cfg.stage > M0_STAGE_MAX) {
		m->cfg.stage = M0_STAGE_MAX;
	}
}

int
m0_run(struct m0 *m)
{
	int rc = 0;
	bool any = false;

	if (m->cfg.stage == M0_STAGE_OFF) {
		return 0;
	}
	rc = stage_read(m);
	if (rc == 0 && m->cfg.stage >= M0_STAGE_CTRL) {
		rc = stage_ctrl(m);
	}
	if (rc == 0 && m->cfg.stage >= M0_STAGE_PHY) {
		rc = stage_phy(m);
	}
	if (rc == 0 && m->cfg.stage >= M0_STAGE_LINK) {
		rc = stage_link(m);
	}
	for (int i = 0; i < M0_PADS; i++) {
		any |= m->driven[i];
	}
	if ((rc != 0 || !m->cfg.hold) && (any || m->ltssm_on || m->cp_on)) {
		tidy(m);
	}
	return (int)m->stop;
}

#endif /* BLAZER */
