/* SPDX-License-Identifier: MIT
 * The S5400 modem's first rungs on the Pixel 10 Pro: its control pads, PCIe0 (pcie@c500000) and the CP boot ROM's link.
 * Hardware-free: every access goes through struct m0_ops, so the host test runs this exact logic.
 * Design, sources and the stock order: research/ios26-modem-r1/MODEM.md. Same structure as blazer_pcie1.c (Wi-Fi's PCIe1).
 *
 * What this never does: load anything into the modem, touch CP shared/reserved memory (cp_rmem, cp_msi_rmem, cp_rmem_1,
 * cp_aoc_rmem), write the endpoint's config space, enable bus mastering, speak SPMI to the CP PMIC or S5910, or vote any
 * power domain or reset off. The only state it leaves changed after a run without hold: PCIe0's power vote and released
 * resets (as Wi-Fi leaves PCIe1's), and the phy_fw clock put. */
#ifndef BLAZER_MODEM_CORE_H
#define BLAZER_MODEM_CORE_H
#include "blazer_hw_port.h"

/* How far a run goes. Each stage adds one kind of change. blazer_modem=N, or hk_dbg bits 24..27 = N. 0: off */
enum {
	M0_STAGE_OFF = 0,
	M0_STAGE_READ,          /* 1: mailbox magic, four LPB GETs, reads of the CP pads and PCIe0's two pads. No change to anything */
	M0_STAGE_CTRL,          /* 2: + phy_fw clock put, PCIe0 power vote, three resets released, PHY SRAM status read. The modem stays off */
	M0_STAGE_PHY,           /* 3: + PHY table, app_hold_phy, root port registers. The modem stays off */
	M0_STAGE_LINK,          /* 4: + CP power-on GPIO sequence (stock power_on_cp from off), PERST, LTSSM gen 1, config reads of bus 1.
	                         *    The CP boot ROM answers with no firmware. Then CP off again and PERST low, unless hold */
	M0_STAGE_MAX = M0_STAGE_LINK,
};

enum m0_stop {
	M0_OK = 0, M0_STOP_REFUSED_PA, M0_STOP_REFUSED_FRAME, M0_STOP_FAULT, M0_STOP_MBA_MAGIC, M0_STOP_MBA_TIMEOUT, M0_STOP_MBA_REPLY,
	M0_STOP_HSIO_N_OFF, M0_STOP_HSIO_S_OFF, M0_STOP_CLOCK, M0_STOP_POWER_VOTE, M0_STOP_RESET_VOTE, M0_STOP_ALREADY_LIVE,
	M0_STOP_SRAM_INIT, M0_STOP_PHY_TABLE, M0_STOP_RC_DEAD, M0_STOP_NO_PCIE_CAP, M0_STOP_PAD, M0_STOP_CP_NOT_OFF,
	M0_STOP_LINK, M0_STOP_ATU, M0_STOP_LINK_LOST, M0_STOP_NO_ID, M0_STOP_WRONG_VENDOR,
	M0_STOP_COUNT,
};

/* What the run reached, furthest first wins. For the OBS line and the probe rows */
enum { M0_AT_NONE = 0, M0_AT_READ, M0_AT_CTRL, M0_AT_PHY, M0_AT_CP_ON, M0_AT_LINK, M0_AT_ID };

struct m0_ops {
	int (*read32)(void *ctx, uint64_t pa, uint32_t *value);         /* 0, or the address has no window */
	int (*write32)(void *ctx, uint64_t pa, uint32_t value);
	int (*write16)(void *ctx, uint64_t pa, uint16_t value);         /* PHY SRAM only, no barrier, as stock's writew_relaxed */
	void (*barrier)(void *ctx);
	void (*delay_us)(void *ctx, uint32_t us);
	uint64_t (*now_us)(void *ctx);
	void (*log)(void *ctx, const char *format, ...) __attribute__((format(printf, 2, 3)));
	void (*cpm_enter)(void *ctx);   /* around each polled frame: the shared CPM queue's lock (touch, thermal, Wi-Fi) */
	void (*cpm_exit)(void *ctx);
	void *ctx;
};

struct m0_cfg {
	uint32_t stage;
	bool hold;              /* hk_dbg bit 28 / blazer_modem_hold=1: on success leave the CP on in its ROM and the link up */
	bool force;             /* blazer_modem_force=1: go on though the controller reads as started or the CP pads as not off */
	const uint16_t *phy;    /* laguna_pcie_phy_fw.bin's values: word i goes to phy_sram + 2 * i. Same file for both controllers (pcie-google.c) */
	uint32_t phy_words;
};

/* One pad as found and as driven. Index into m0_pads[] */
enum {
	M0_PAD_NRESET, M0_PAD_DUMP_NOTI, M0_PAD_AP_ACTIVE, M0_PAD_PM_WRST, M0_PAD_CP_PWR, M0_PAD_CP_WRST,    /* hsios 2..7: outputs */
	M0_PAD_PARTIAL_RST,                                                                             /* lsioe 0x0e: output */
	M0_PAD_AP2CP_WAKEUP,                                                                            /* lsios 0x26: read only */
	M0_PAD_CP2AP_ACTIVE, M0_PAD_CP2AP_WAKEUP, M0_PAD_CP2AP_WRST,                                    /* cpm 0x0b 0x19 0x1a: read only */
	M0_PAD_CLKREQ, M0_PAD_PERST,                                                                    /* hsion 0, 2: PCIe0 */
	M0_PADS,
};

struct m0_pad {
	const char *name;
	uint64_t base;
	uint32_t pad;
	uint8_t domain;         /* which LPB state must read ON before any access: M0_DOM_* */
	bool out;               /* this code may drive it (stage LINK, or PERST/CLKREQ) */
};

enum { M0_DOM_HSIO_N, M0_DOM_HSIO_S, M0_DOM_LSIO_E, M0_DOM_LSIO_S, M0_DOM_CPM, M0_DOMS };

extern const struct m0_pad m0_pads[M0_PADS];

struct m0 {
	struct m0_ops ops;
	struct m0_cfg cfg;
	uint32_t stop, stop_detail, at;
	uint32_t dom_state[M0_DOMS];    /* LPB GET replies; CPM: 2 by definition (its own pads) */
	bool dom_on[M0_DOMS];
	uint32_t found[M0_PADS][4];     /* PARAM, DMUX, TX, RX as found */
	bool found_ok[M0_PADS], driven[M0_PADS];
	bool cp_off_found, cp_on, clock_on, domain_on, out_of_reset, sram_ready, phy_loaded, rc_ready, ltssm_on, link_up, atu_on, perst_driven;
	uint32_t pcie_cap, rc_id, ctl_status, pm_state, lnksta, attempts, link_us, cp_on_us;
	/* The result. ep_id = device << 16 | vendor; 0 until read */
	uint32_t ep_id, ep_class_rev, ep_subsys, ep_lnkcap, ep_cap;
	uint32_t cp2ap_after[3];        /* RX of CP2AP_ACTIVE, CP2AP_WAKEUP, CP2AP_WRST after the link */
	uint32_t frames;                /* mailbox frames sent */
};

void m0_init(struct m0 *m, const struct m0_ops *ops, const struct m0_cfg *cfg);
int m0_run(struct m0 *m);       /* up to cfg.stage. 0, or an M0_STOP_*. Always tidies what it drove, except on success with cfg.hold */
const char *m0_stop_name(uint32_t stop);
const char *m0_at_name(uint32_t at);
bool m0_read_allowed(const struct m0 *m, uint64_t pa);
bool m0_write_allowed(const struct m0 *m, uint64_t pa);
bool m0_is_cp_memory(uint64_t pa);       /* the CP's reserved regions: never named by this code; the test checks every access */

/* The answer stock Android reads here (physical, chooser-v1-r3-t1 dmesg: "pci 0000:01:00.0: [144d:a5a5] type 00 class 0x028000") */
#define M0_VENDOR_SAMSUNG       0x144du
#define M0_DEVICE_CP_ROM        0xa5a5u

#endif
