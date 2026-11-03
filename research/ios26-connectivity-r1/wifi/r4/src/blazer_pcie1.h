/* SPDX-License-Identifier: MIT
 * Wi-Fi's PCIe link on the Pixel 10 Pro, up to reading the endpoint's ID. Hardware-free: everything goes through struct p1_ops, so the host test runs this exact logic.
 * Design, evidence and the register list: research/ios26-wifi-r1/FINDINGS.md. */
#ifndef BLAZER_PCIE1_H
#define BLAZER_PCIE1_H
#include "blazer_hw_port.h"

/* How far a boot goes. Each stage adds one kind of change. blazer_wifi_stage=, default P1_STAGE_SCAN. */
enum {
	P1_STAGE_GATE = 0,      /* one mailbox GET and reads of four pads. No change to any block */
	P1_STAGE_CTRL,          /* + PCIe power vote, three resets released, PHY status read. The chip stays off */
	P1_STAGE_PHY,           /* + PHY table, last reset, root port registers. The chip stays off */
	P1_STAGE_LINK,          /* + REG_ON, PERST, LTSSM, one config read of bus 1 */
	P1_STAGE_CHIP,          /* + BARs, chip ID, ASR workaround, CTO, security register, backplane walk, OTP. Nothing loaded, ARM stays halted */
	P1_STAGE_FW,            /* + FLR, firmware and NVRAM into the chip's RAM, bus master, ARM released, wait for its boot doorbell, shared area and console read */
	P1_STAGE_RINGS,         /* + host memory: rings, host capabilities, host ready, buffers, first ioctls. Polled. blazer_bcm4390_ring.c */
	P1_STAGE_SCAN,          /* + RX buffers, CLM and TXCAP blobs, interface up, one passive scan, results logged. No join, no credentials, nothing asked to transmit. blazer_bcm4390_scan.c */
	P1_STAGE_JOIN,          /* + country, MAC, security, en0. Then, only with cfg.join_armed and a network: the join and frames. Never the default. blazer_bcm4390_join.c */
};

/* Where stock's kernel puts the endpoint's BARs on this phone: Android's log, inside the FDT's memory window */
#define P1_EP_BAR0      0x60800000ULL   /* 64 KiB: first 4 KiB is a window on the backplane, PCIe core at +0x2000 */
#define P1_EP_BAR2      0x60400000ULL   /* 4 MiB: the chip's RAM, through its own window */
#define P1_EP_BAR4      0x60300000ULL   /* 1 MiB: assigned as stock does. Stock's BT download window; never accessed here */
#define P1_EP_BAR0_SIZE 0x10000u
#define P1_EP_BAR2_SIZE 0x400000u
#define P1_EP_PCIE      0x2000u         /* PCI_16KB0_PCIREGS_OFFSET */
/* The endpoint's window registers, and the only pages they can name */
#define P1_C_BAR0_WIN   0x80u
#define P1_C_RAM_WIN    0x84u           /* DHD's BAR1 window: Linux's BAR 2 */
#define P1_C_BT_WIN     0x8cu           /* DHD's BAR2 window: Linux's BAR 4 */
#define P1_C_IND_ADDR   0x98u
#define P1_C_IND_DATA   0x9cu
#define P1_BP_CC        0x18000000u
#define P1_BP_OTP_PAGE  0x18011000u
#define P1_BP_PMU       0x18018000u
#define P1_OOBR_SPAN    0x4000u

enum p1_stop {
	P1_OK = 0, P1_STOP_REFUSED_PA, P1_STOP_REFUSED_FRAME, P1_STOP_FAULT, P1_STOP_MBA_MAGIC, P1_STOP_MBA_TIMEOUT, P1_STOP_MBA_REPLY,
	P1_STOP_HSIO_OFF, P1_STOP_POWER_VOTE, P1_STOP_RESET_VOTE, P1_STOP_AUX_CLOCK, P1_STOP_ALREADY_LIVE, P1_STOP_SRAM_INIT, P1_STOP_PHY_TABLE,
	P1_STOP_RC_DEAD, P1_STOP_NO_PCIE_CAP, P1_STOP_PAD, P1_STOP_LINK, P1_STOP_ATU, P1_STOP_LINK_LOST, P1_STOP_NO_ID, P1_STOP_WRONG_VENDOR,
	P1_STOP_BAR, P1_STOP_CHIP_ID, P1_STOP_POWER_REQ, P1_STOP_NCI, P1_STOP_NO_ARM, P1_STOP_FIS, P1_STOP_ARM_RUNNING, P1_STOP_SBOOT, P1_STOP_FLR, P1_STOP_FW_IMAGE, P1_STOP_NVRAM, P1_STOP_TCM,
	P1_STOP_ARM_RELEASE, P1_STOP_NO_SHARED, P1_STOP_BAD_SHARED,
	P1_STOP_NO_DMA, P1_STOP_RING_INFO, P1_STOP_INDEX_SIZE, P1_STOP_SYNC_MODE, P1_STOP_RING_FULL, P1_STOP_BAD_ITEM, P1_STOP_FW_TRAP, P1_STOP_IOCTL_TIMEOUT, P1_STOP_IOCTL_REPLY,
	P1_STOP_IOCTL_REFUSED, P1_STOP_CLM, P1_STOP_WL_UP, P1_STOP_SCAN_VERSION, P1_STOP_SCAN_START, P1_STOP_SCAN_TIMEOUT, P1_STOP_SCAN_ENDED, P1_STOP_SCAN_EMPTY, P1_STOP_TX_SEEN,
	P1_STOP_NO_NETWORK, P1_STOP_NOT_HEARD, P1_STOP_NET_SECURITY, P1_STOP_COUNTRY, P1_STOP_MAC, P1_STOP_JOIN_VERSION, P1_STOP_SECURITY, P1_STOP_JOIN_REFUSED, P1_STOP_JOIN_FAILED, P1_STOP_JOIN_TIMEOUT, P1_STOP_FLOW_RING, P1_STOP_LINK_GONE, P1_STOP_NO_ADDRESS, P1_STOP_NO_PING,
};

struct p1_ops {
	int (*read32)(void *ctx, uint64_t pa, uint32_t *value);         /* 0, or the address has no window */
	int (*write32)(void *ctx, uint64_t pa, uint32_t value);
	int (*write16)(void *ctx, uint64_t pa, uint16_t value);         /* No barrier: PHY SRAM only, as stock's writew_relaxed */
	void (*barrier)(void *ctx);
	int (*aux_clock_on)(void *ctx, uint64_t *a0, uint64_t *a1);     /* cfg.aux only. SIP call, not a register */
	void (*delay_us)(void *ctx, uint32_t us);
	uint64_t (*now_us)(void *ctx);
	void (*log)(void *ctx, const char *format, ...) __attribute__((format(printf, 2, 3)));
	void *ctx;
	int (*bulk32)(void *ctx, uint64_t pa, const void *src, uint32_t words); /* Aligned 32-bit stores, no barrier, inside one window */
	void (*random)(void *ctx, void *dst, uint32_t bytes);
	void (*cpm_enter)(void *ctx);   /* around each polled frame: cpmlock's lock. Touch and thermal share the channel */
	void (*cpm_exit)(void *ctx);
	void (*dma_sync)(void *ctx, void *va, uint32_t bytes);  /* clean and invalidate to PoC, by address: FlushPoC_DcacheRegion, as UFS */
	/* Stage JOIN: the interface above. None of these sees a key */
	void (*net_ready)(void *ctx, const uint8_t *mac);       /* The radio's address is final: en0 can exist */
	void (*net_link)(void *ctx, bool up);                   /* Frames can pass, keys in place. Or no longer */
	void (*net_rx)(void *ctx, const uint8_t *frame, uint32_t bytes);        /* A frame for the stack. Copied before it returns */
	uint32_t (*net_tx)(void *ctx, uint8_t *frame, uint32_t room);           /* One from the stack, or 0 */
	void (*net_addr)(void *ctx, uint32_t ip, uint32_t mask, uint32_t gateway);      /* blazer_wifi_net=1: what DHCP gave. Host order */
};

/* What's joined. Comes from the secret file by way of the image: tools/mkwifisecret.py, b4_net_parse. Its name and key are never logged, and the key is gone once the firmware has it */
struct b4_network {
	uint8_t ssid[32];
	uint8_t ssid_len;
	uint8_t pmk[32];
	/* BWN2: the passphrase too. This firmware's own supplicant makes its PMK from a passphrase and the join's SSID
	 * (wlc_join_infra -> wlc_sup_set_ssid -> wlc_pmk_set_psk); a bare PMK left it waiting for M1 (a7-wifi-join-r1) */
	uint8_t pass[63];
	uint8_t pass_len;       /* 0: BWN1, PMK only */
	bool open;              /* No password, and the network must have none either */
	bool have_mac;
	uint8_t mac[6];
	char abbrev[3], ccode[3];
	int32_t rev;            /* -1: the firmware's choice for that code */
};

struct p1_image {
	const char *name;
	const uint8_t *data;
	uint32_t size;
};

enum { P1_NVRAM_7311, P1_NVRAM_7321, P1_NVRAM_6327, P1_NVRAM_FALLBACK, P1_NVRAM_COUNT };

/* Physically contiguous host memory, all the chip is ever told about */
struct p1_dma {
	uint8_t *va;
	uint64_t pa;
	uint32_t bytes;
};

struct p1_cfg {
	uint32_t stage;
	uint32_t gen;           /* blazer_wifi_gen=, 1..3, default 1. FDT max-link-speed is 3 */
	bool hold;              /* blazer_wifi_hold=1: on success, leave the link up and the chip on */
	bool aux;               /* blazer_wifi_aux=1: also send the aux clock's SIP call. The shim's UFS route already did */
	bool force;             /* blazer_wifi_force=1: go on though the PHY or LTSSM reads as already started */
	const uint16_t *phy;    /* the PHY table: word i goes to phy_sram + 2 * i */
	uint32_t phy_words;
	uint32_t flr;           /* blazer_wifi_flr=0..2, default 2: Android's boot does two before it loads */
	bool mem_atu;           /* blazer_wifi_mem_atu=1: an outbound region for the BARs. Stock has none: child_ops isn't DesignWare's, so dw_pcie_iatu_setup never runs */
	struct p1_image fw;
	struct p1_image nvram[P1_NVRAM_COUNT];
	uint8_t *nvram_buf;     /* scratch for the processed NVRAM */
	uint32_t nvram_buf_size;
	struct p1_dma dma;      /* stage RINGS */
	struct p1_image clm;    /* stage SCAN: bcmdhd_clm.blob_4390_b1, what Android loads here */
	struct p1_image txcap;  /* stage SCAN: bcmdhd_txcap.blob_ROW, what Android loads here */
	bool join_armed;        /* stage JOIN: blazer_wifi_join=1. Without it the join and every frame stay refused, and stage JOIN is a dry run that sends nothing */
	struct b4_network *net; /* stage JOIN: NULL if the image holds none. Written to: the key is wiped when used */
	uint32_t net_mode;      /* 0: no interface. 1: en0, and the kernel takes an address and pings its gateway. 2: en0 for configd */
	uint32_t net_run_s;     /* How long frames flow before the chip goes off. 0: for good */
	bool idx_tcm;           /* blazer_wifi_idx_tcm=1: ring indices in the chip's RAM, DHD's fallback. Default: in host memory, Android's way, when the firmware offers it */
};

enum { B4_H2D_CTRL, B4_H2D_RXPOST, B4_D2H_CTRL, B4_D2H_TX, B4_D2H_RX, B4_COMMON_RINGS };
/* The one TX flow ring. This index is also its number on the doorbell (DHD_FLOWID_TO_RINGID of flow 2); in the index arrays it's slot 2 */
#define B4_FLOW_RING    B4_COMMON_RINGS
#define B4_ALL_RINGS    (B4_COMMON_RINGS + 1)

struct b4_ring {
	uint8_t *va;
	uint64_t pa;
	uint16_t depth, item, wr, rd;
	uint32_t seq, tries;    /* seq: the epoch the next item carries. tries: polls waiting for one item to land */
	uint8_t phase;
};

struct b4_span {
	uint32_t addr, bytes;
};

struct p1 {
	struct p1_ops ops;
	struct p1_cfg cfg;
	uint32_t stop, stop_detail;
	bool hsio_on, domain_on, out_of_reset, sram_ready, phy_loaded, rc_ready, ltssm_on, link_up, atu_on, reg_on_driven, perst_driven;
	uint32_t hsio_state;
	uint32_t pads[4][4];    /* CLKREQ, PERST, DEV_WAKE, REG_ON: PARAM, DMUX, TX, RX as found */
	uint32_t pcie_cap, rc_id;
	uint32_t ctl_status, pm_state, lnksta, attempts, link_us;
	uint32_t ep_id;         /* the result: device << 16 | vendor. 0 until read */
	/* The endpoint, from stage CHIP on */
	bool ep_mem_on, arm_known, arm_halted, otp_read, arm_released, bar1_set;
	uint32_t chip_word, chip_id, chip_rev, chip_type, dar_sec, dar_clk, dar_pwr, cto_ctrl, fis;
	uint32_t bar0_win, bar1_win;
	uint32_t cc_erom2, oobr_base, erom1_base, core_count, arm_dmp, arm_ctrl, arm_rev, bus_rev, cc_rev;
	uint8_t otp_vid[8];
	uint32_t otp_vid_len, otp_boardtype, nvram_index;
	uint32_t var_addr, var_size, token, ram_top, flrs;
	uint32_t shared_addr, shared_flags, shared_ms, fwid, console_addr, console_seen;
	/* What the firmware did after release: the top word's first value, its last, the boot doorbell */
	bool bus_master_on, doorbell_seen;
	uint32_t early_top, doorbell_ms, mailbox;
	/* The shared area as read after the doorbell */
	uint32_t shared_flags2, shared_flags3, rings_info, h2d_mb_ptr, d2h_mb_ptr, ewp_info, rx_offset, max_rxbufs;
	/* Ring info */
	uint32_t ringmem, h2d_w, h2d_r, d2h_w, d2h_r, max_flowrings, max_submission, max_completion, max_vdevs, host_cap, host_cap2;
	/* Host memory */
	uint32_t dma_used;
	uint64_t dma_err;
	bool idx_host, hostready_sent;
	struct b4_ring ring[B4_ALL_RINGS];
	uint8_t *idx_arr[4];    /* H2D write, H2D read, D2H write, D2H read */
	uint64_t idx_pa[4];
	uint8_t *ioc_req, *resp_buf, *event_buf, *rx_buf, *tx_buf;
	uint64_t ioc_req_pa, resp_pa, event_pa, rx_pa, tx_pa, scratch_pa;
	/* After release the chip's RAM takes writes only inside these */
	struct b4_span tcm_w[10];
	uint32_t tcm_w_n;
	/* The ioctl in flight */
	uint32_t ioc_state, ioc_cmd, ioc_out_len, ioc_got_len, ioc_seen_ack, resp_posted, events_posted, events_seen, other_seen;
	int32_t ioc_status;
	uint16_t ioc_trans;
	uint8_t *ioc_out;
	/* What the first ioctls said */
	uint32_t rev_vendor, rev_device, rev_chipnum, rev_chiprev, rev_corerev, wlc_major, wlc_minor;
	bool rev_ok;
	char fw_ver[120];
	/* Stage SCAN. rx_*, tx_items: what came back on the RX and TX completion rings */
	uint32_t rx_posted, rx_items, rx_bytes, tx_items;
	uint32_t preinit_status, axierror_addr, rxpost_size, scan_ver, up_ms;
	int32_t preinit_err;
	bool clm_loaded, txcap_loaded, wl_up, scan_running, scan_done;
	char country[4], clm_ver[80];
	/* Events: all seen, what couldn't be read, how many got a line of their own */
	uint32_t ev_bad, ev_other, ev_logged;
	uint32_t scan_status, scan_results, scan_bad, scan_nets, scan_more, scan_ms, scan_band[3];
	uint8_t scan_seen[128][6];
	/* The firmware's own transmit counters, [0] before the scan, [1] after. Summed over its slices */
	bool cnt_known[3];      /* Before the scan, after it, and at stage JOIN's dry run after the settings */
	uint32_t cnt_frames[3], cnt_probereq[3], cnt_probersp[3];
	uint8_t ioc_big[8192];  /* For the two long ioctls: a blob chunk's iovar, the counters */
	/* Stage JOIN. What was heard of the network to join */
	bool jn_found, jn_scrub;
	uint32_t jn_seen, jn_refused_security;
	uint8_t jn_bssid[6];
	uint16_t jn_chanspec;
	int16_t jn_rssi;
	uint8_t jn_ctl, jn_group_tkip, jn_akm, jn_mfp;
	/* r3: the pairwise TKIP the network offers (method 2's wsec), and the two best channels it was heard on, by RSSI (method 1's join, as Android's chan_cnt 2) */
	uint8_t jn_pair_tkip, jn_nchans, jn_method;
	uint16_t jn_chans[2];
	int16_t jn_chan_rssi[2];
	uint32_t join_ver, jn_tries;
	/* What the firmware has said about the join */
	bool jn_set_ssid_seen, jn_link, jn_keyed, jn_sup_failed, jn_was_up, net_on, console_told;
	uint32_t jn_set_ssid, jn_sup_status, jn_sup_reason, jn_fail_type, jn_fail_status, jn_fail_reason, jn_lost_reason, jn_link_events;
	uint32_t jn_ms;
	uint8_t mac[6];
	bool dry_done;
	/* The flow ring: 0 none, 1 asked for, 2 up */
	uint32_t flow_state, tx_busy, tx_sent, tx_status_bad, tx_done;
	uint32_t rx_frames, rx_dropped;
	/* r4: the firmware's receive counters at the last look (wl_cnt_wlc_t words, summed over its slices) */
	uint32_t rxc[8];
	bool rxc_ok;
	uint8_t tx_hold[1514];  /* The frame waiting for the flow ring */
	uint32_t tx_hold_len;
	/* blazer_wifi_net=1: the kernel's own DHCP, ARP and one ping */
	uint32_t ip_state, ip_xid, ip_addr, ip_mask, ip_gw, ip_server, ip_offer, ip_lease, ip_tries, ping_seq, ping_ms, ip_naks;
	uint64_t ip_next_us, ping_sent_us;
	uint8_t gw_mac[6];
	bool ip_told, ping_ok;
};

/* What may reach the firmware: 0 stages up to SCAN. 1 stage JOIN: settings, nothing sent. 2 armed: the join too. blazer_bcm4390_scan.c */
#define B4_GATE_PASSIVE 0
#define B4_GATE_DRY     1
#define B4_GATE_ARMED   2

/* Ioctl numbers more than one file needs */
#define WLC_UP          2u
#define WLC_GET_REVINFO 98u
#define WLC_GET_VAR     262u
#define WLC_SET_VAR     263u
#define WLC_SET_WSEC_PMK 268u
#define WLC_DISASSOC    52u
#define WLC_SET_PM      86u     /* r4: PM_OFF for the handshake, as wl_cfg80211_set_pm at the connect */

/* The guarded accesses, for blazer_bcm4390.c too. All stop the run on a refused address */
int p1_rd(struct p1 *p, uint64_t pa, uint32_t *v);
int p1_wr(struct p1 *p, uint64_t pa, uint32_t v);
int p1_rmw(struct p1 *p, uint64_t pa, uint32_t clear, uint32_t set);
int p1_wr16(struct p1 *p, uint64_t pa, uint16_t v);     /* The chip's RAM only: ring indices */
int p1_halt(struct p1 *p, uint32_t code, uint32_t detail);
bool p1_write_allowed(const struct p1 *p, uint64_t pa);

int b4_chip(struct p1 *p);      /* stage CHIP, after the link and the ID */
int b4_fw(struct p1 *p);        /* stage FW */
int b4_rings(struct p1 *p);     /* stage RINGS */
int b4_scan(struct p1 *p);      /* stage SCAN, called from inside stage RINGS's run, once the first ioctls have answered */
/* For blazer_bcm4390_scan.c */
int b4_ioctl(struct p1 *p, uint32_t cmd, uint8_t *buf, uint16_t len);   /* 0 means answered: the answer's in buf, the firmware's status in p->ioc_status. Refuses what b4_ioctl_allowed refuses */
int b4_poll(struct p1 *p);      /* All three completion rings, then the firmware's trap and mailbox state, once */
int b4_rx_post_all(struct p1 *p);
int b4_rx_witness(struct p1 *p, const char *when);   /* r4: the RX rings' indices, read only. blazer_bcm4390_ring.c */
bool b4_ioctl_allowed(uint32_t cmd, const uint8_t *buf, uint32_t len, int level);
int b4_gate_level(const struct p1 *p);
void b4_on_event(struct p1 *p, const uint8_t *frame, uint32_t bytes);   /* One event buffer's content, from the ring's completion */
/* blazer_bcm4390_join.c */
int b4_join_pre_clm(struct p1 *p);      /* MAC */
int b4_join_pre_up(struct p1 *p);       /* Country, en0 */
void b4_join_heard(struct p1 *p, const uint8_t *bi, uint32_t bytes);    /* One scan record */
int b4_join_run(struct p1 *p);          /* After the scan: dry run, or join and frames */
int b4_read_counters(struct p1 *p, unsigned when);      /* The firmware's own count of what it sent. blazer_bcm4390_scan.c */
int b4_rx_counters(struct p1 *p, const char *when);    /* r4: its receive counters, and what changed since the last look. blazer_bcm4390_scan.c */
bool b4_join_event(struct p1 *p, uint32_t type, uint32_t status, uint32_t reason, uint32_t flags);        /* true: it was one of the join's */
void b4_net_rx(struct p1 *p, const uint8_t *frame, uint32_t bytes);     /* A frame off the air, for the stage's own use or en0 */
void b4_scrub_text(const struct p1 *p, char *line);     /* The network's name and address out of the firmware's own words */
const char *b4_net_parse(const uint8_t *blob, uint32_t bytes, struct b4_network *net);  /* NULL, or what's wrong. Never quotes the blob */
/* blazer_bcm4390_ring.c, for the file above */
int b4_flow_create(struct p1 *p, const uint8_t *sa, const uint8_t *da);
int b4_tx_post(struct p1 *p, const uint8_t *frame, uint32_t bytes);     /* 0, or a stop */
uint32_t b4_tx_free(const struct p1 *p);
void b4_on_flow_created(struct p1 *p, int32_t status, uint32_t ring);
void b4_wipe_ioctl(struct p1 *p);       /* What last went through the ioctl buffers */
int b4_tcm_rd(struct p1 *p, uint32_t addr, uint32_t *v);
int b4_tcm_wr(struct p1 *p, uint32_t addr, uint32_t v);
int b4_tcm_wr16(struct p1 *p, uint32_t addr, uint16_t v);
int b4_console(struct p1 *p);
int b4_power(struct p1 *p, bool on);
void b4_diag(struct p1 *p);
/* Same result as DHD's process_nvram_vars and its caller: comments, blank lines and CRs gone, each line NUL ended, padded to a word, one more word of NUL. Returns what to send, or 0 if out_size is short */
uint32_t b4_nvram_process(const uint8_t *text, uint32_t size, uint8_t *out, uint32_t out_size);

void p1_init(struct p1 *p, const struct p1_ops *ops, const struct p1_cfg *cfg);
int p1_run(struct p1 *p);       /* up to cfg.stage. 0, or a P1_STOP_*. After REG_ON went high it always tidies up, except on success with cfg.hold */
const char *p1_stop_name(uint32_t stop);

#endif
