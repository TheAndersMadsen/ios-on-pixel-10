#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * BCM4390's host interface once the firmware has rung its boot doorbell: rings in host memory, host capabilities, host ready, buffers for it to answer into, the first ioctls. Stage SCAN's own part is blazer_bcm4390_scan.c.
 * One thread, polled, no interrupt. Own code; values and order are from Broadcom's DHD and its headers (GPL, facts only), IPC version 9, which stage 2 read off this phone. brcmfmac stops at 7.
 * Sources: bcm4390/dhd_msgbuf.c dhd_prot_init, dhd_set_host_cap, dhd_prot_ring_init, dhd_fillup_ioct_reqst, dhd_prot_process_ctrlbuf; dhd_pcie.c dhdpcie_readshared, dhd_bus_hostready; bcmpcie.h, bcmmsgbuf.h.
 *
 * Physical facts it stands on, Android on this phone, 20261027-112139-loop: "H2D DMA RD INDX : array size 172 = 4 * 43", "D2H DMA WR INDX : array size 16 = 4 * 4", "FW supports DAR ? N", "D2H sync mechanism is XORCSUM",
 * "GET_REVINFO device 0x4438, vendor 0x14e4, chipnum 0x4390", "Firmware version = wl0: Sep 17 2026 16:07:49 version 27.10.1121.57.30 (ge2638ec b1 release2) FWID 01-800a0c25".
 *
 * Where it differs from stock, on purpose: no deep sleep (HOSTCAP_DS_NO_OOB_DW, DHD's "Disable DS altogether"), no EDL or info rings, no iDMA, no flow rings, no extended trap buffer, no host SCBs, no CSO: each is another thing the chip could DMA to, and none is needed for an ioctl.
 *
 * Host memory: the chip is only ever told addresses from cfg.dma. Every buffer is flushed by address around every hand-over. The chip's RAM takes writes only inside the spans named here, once they've been read and checked (write_allowed). */
#include "blazer_hw_port.h"
#include "blazer_pcie1.h"

#define RAM_BASE        0x2a0000u       /* as blazer_bcm4390.c */
#define RAM_END         0x5c0000u
#define BAR0_PCIE       (P1_EP_BAR0 + P1_EP_PCIE)
#define P_DB0           0x140u          /* hosttodev0doorbell0 */
#define P_DB1           0x144u          /* hosttodev0doorbell1 */
#define P_DAR_PWR       0xa0cu
#define  PWR_REQ_DMN1   (1u << 9)
#define HOST_READY      0x12345678u     /* dhd_bus_hostready */
#define DB_WR_MAGIC     0xff000000u     /* DHD_WRPTR_UPDATE_H2D_DB_MAGIC */
#define DB_RD_MAGIC     0xdd000000u     /* DHD_RDPTR_UPDATE_H2D_DB_MAGIC */

/* pciedev_shared_t */
#define S_TRAP          4u
#define S_SCRATCH_LEN   52u
#define S_SCRATCH       56u
#define S_HOST_CAP      84u
#define S_HOST_CAP2     112u
#define F_VERSION       0xffu
#define F_ASSERT        0x200u
#define F_TRAP          0x400u
#define F_DMA_INDEX     0x10000u
#define F_SYNC_SEQNUM   0x20000u
#define F_SYNC_XORCSUM  0x40000u
#define F_2BYTE_INDEX   0x100000u
#define F_HOSTRDY       0x10000000u
#define D2H_FWHALT      0x10000000u     /* D2H_DEV_FWHALT */

/* Host capabilities */
#define CAP_HOSTRDY     0x00000400u
#define CAP_NO_OOB_DW   0x00001000u
#define CAP_UR_NO_TRAP  0x00800000u
#define CAP2_BAD_RECOVERY 0x00000200u   /* HOSTCAP2_TRAP_ON_BAD_RECOVERY. Physical: "set host_cap2 0x200" */

/* ring_info_t */
#define RI_RINGMEM      0u
#define RI_H2D_W        4u
#define RI_H2D_R        8u
#define RI_D2H_W        12u
#define RI_D2H_R        16u
#define RI_HOST_ADDRS   20u             /* h2d_w, h2d_r, d2h_w, d2h_r: 8 bytes each */
#define RI_MAX_1        52u             /* max_tx_flowrings, max_submission_queues */
#define RI_MAX_2        56u             /* max_completion_rings, max_vdevs */
/* ring_mem_t */
#define RM_SIZE         16u
#define RM_MAX_LEN      4u              /* max_item, len_items */
#define RM_BASE         8u

/* Work items */
#define MSG_GEN_STATUS  0x01u
#define MSG_FLOW_CREATE 0x03u
#define MSG_FLOW_CREATED 0x04u
#define MSG_TX_POST     0x0fu
#define MSG_TX_STATUS   0x10u
#define MSG_RING_STATUS 0x02u
#define MSG_IOCTL_REQ   0x09u
#define MSG_IOCTL_ACK   0x0au
#define MSG_RESP_POST   0x0bu
#define MSG_IOCTL_CMPLT 0x0cu
#define MSG_EVENT_POST  0x0du
#define MSG_WL_EVENT    0x0eu
#define MSG_RX_POST     0x11u
#define MSG_RX_CMPLT    0x12u
#define EPOCH_MODULO    253u
#define EPOCH_INIT      254u            /* D2H_EPOCH_INIT_VAL, H2D_EPOCH_INIT_VAL */
#define PHASE_INIT      0x80u           /* BCMPCIE_CMNHDR_PHASE_BIT_INIT */
#define IOCTL_REQ_ID    0xfffeu         /* DHD_IOCTL_REQ_PKTID */
#define RESP_ID_BASE    0x100u
#define EVENT_ID_BASE   0x200u
#define RX_ID_BASE      0x400u
#define TX_ID_BASE      0x800u

/* Sizes. Item lengths are bcmmsgbuf.h's, for IPC 7 and up. Depths are the host's to choose; these are enough for ioctls */
#define H2D_CTRL_ITEM   40u
#define H2D_RXPOST_ITEM 32u
#define D2H_CTRL_ITEM   24u
#define D2H_TX_ITEM     24u
#define D2H_RX_ITEM     40u
#define CTRL_DEPTH      64u             /* Holds every buffer the firmware can owe back, plus the ioctl in flight */
#define RX_POST_DEPTH   (RX_BUFS + 64u) /* r5: every buffer fits on the ring at once, so posting never waits on the dongle */
#define RX_CPL_DEPTH    1024u           /* r5: as many completions as buffers can be owed back */
#define RESP_BUFS       8u              /* DHD_FLOWRING_MAX_IOCTLRESPBUF_POST */
#define RESP_BUF_BYTES  8192u           /* DHD_FLOWRING_IOCTL_BUFPOST_PKTSZ */
#define EVENT_BUFS      32u             /* DHD_FLOWRING_MAX_EVENTBUF_POST */
#define EVENT_BUF_BYTES 2048u           /* DHD_FLOWRING_RX_BUFPOST_PKTSZ */
#define IOC_REQ_BYTES   8200u           /* IOCT_RETBUF_SIZE */
#define IOC_MAX_IN      2008u           /* MSGBUF_IOCTL_MAX_RQSTLEN: DHD_IOCTL_REQ_PKTBUFSZ less one control ring item */
#define RX_BUFS         1024u           /* r5. This firmware is split-RX mode 4 (_bcmsplitrx 1, _bcmsplitrx_mode 4 in the .bin): its MAC rx fill holds host buffers (nrxbufpost 384 on unit 0, 154 on unit 1, console),
                                         * and a packet for the host that is in dongle memory needs one more from the RX post queue, else pciedev_process_d2h_rxpyld drops it (EL 30 b8c8).
                                         * r1-r3 posted 64 and their consoles show those drops at every join. Stock posts max_host_rxbufs (6783 here); 1024 is above both units' fill with 486 over */
#define RX_BUF_BYTES    2048u           /* Physical, Android here: "RxBuf Post : 2048" */
#define SCRATCH_BYTES   8u              /* DMA_D2H_SCRATCH_BUF_LEN */
#define IDX_WORD        4u
#define IDX_MAX_RINGS   128u
#define TX_BUFS         16u             /* Payload only: the Ethernet header goes in the item. Enough to prove a path, not to fill one */
#define TX_BUF_BYTES    2048u
#define FLOW_DEPTH      64u
#define FLOW_ITEM       48u             /* H2DRING_TXPOST_BASE_ITEMSIZE: no TXPOST_EXT capability claimed */
#define FLOW_ID         2u              /* FLOWID_RESERVED, the first there is. Also its slot in the H2D index arrays */
#define ETH_HDR         14u
#define B4_DMA_NEEDED   0x280000u       /* r5: 2.5 MiB, for 1024 RX buffers. blazer_wifi.c's WIFI_DMA_BYTES */

/* What comes back */
#define EVENT_LEN_AT    12u             /* wlevent_req_msg_t.event_data_len */
#define RX_POST_LEN_AT  10u             /* host_rxbuf_post_t.data_buf_len */
#define RX_POST_ADDR_AT 24u             /* host_rxbuf_post_t.data_buf_addr */
#define RX_DATA_LEN_AT  14u             /* host_rxbuf_cmpl_t.data_len */
#define RX_DATA_OFF_AT  16u             /* host_rxbuf_cmpl_t.data_offset */
/* tx_flowring_create_request_t */
#define FC_DA           8u
#define FC_SA           14u
#define FC_TID          20u
#define FC_RING_ID      22u
#define FC_MAX_ITEMS    28u
#define FC_LEN_ITEM     30u
#define FC_RING_PTR     32u
/* host_txbuf_post_v1_t */
#define TP_ETH          8u
#define TP_FLAGS        22u
#define TP_SEG_CNT      23u
#define TP_DATA_ADDR    32u
#define TP_DATA_LEN     42u
#define TP_FRAME_802_3  0x01u           /* BCMPCIE_PKT_FLAGS_FRAME_802_3 */
#define ITEM_LOG_MAX    8u

/* Ioctls */
#define REV_BYTES       128u
#define REV_VENDOR      0u
#define REV_DEVICE      4u
#define REV_CHIPREV     12u
#define REV_CORE        16u
#define REV_CHIPNUM     44u
#define VER_BYTES       256u
#define WLC_VER_MAJOR   12u             /* The stock module reads them there */
#define WLC_VER_MINOR   14u

/* Timing */
#define POLL_MS         1u
#define IOCTL_WAIT_MS   5000u
#define ITEM_TRIES      500u
#define SETTLE_MS       300u
#define TRAP_WORDS      16u

_Static_assert(RESP_BUF_BYTES * RESP_BUFS + EVENT_BUF_BYTES * EVENT_BUFS + RX_BUF_BYTES * RX_BUFS + IOC_REQ_BYTES + (CTRL_DEPTH * (H2D_CTRL_ITEM + D2H_CTRL_ITEM + D2H_TX_ITEM) + RX_POST_DEPTH * H2D_RXPOST_ITEM + RX_CPL_DEPTH * D2H_RX_ITEM) + 12 * 4096 + 4 * IDX_WORD * IDX_MAX_RINGS < B4_DMA_NEEDED, "host memory");
_Static_assert(RESP_BUFS + EVENT_BUFS + 1 < CTRL_DEPTH && RX_BUFS < RX_POST_DEPTH && RX_BUFS <= RX_CPL_DEPTH, "a ring must hold everything that can be outstanding on it");
_Static_assert(RX_ID_BASE + RX_BUFS <= TX_ID_BASE && RX_BUF_BYTES >= 0x7f8u, "RX ids below TX ids; pciedev_process_rxpost_msg halts the firmware on a buffer under 2040 bytes");
_Static_assert(RESP_BUF_BYTES * RESP_BUFS + EVENT_BUF_BYTES * EVENT_BUFS + RX_BUF_BYTES * RX_BUFS + TX_BUF_BYTES * TX_BUFS + FLOW_DEPTH * FLOW_ITEM + IOC_REQ_BYTES + (CTRL_DEPTH * (H2D_CTRL_ITEM + D2H_CTRL_ITEM + D2H_TX_ITEM) + RX_POST_DEPTH * H2D_RXPOST_ITEM + RX_CPL_DEPTH * D2H_RX_ITEM) + 14 * 4096 + 4 * IDX_WORD * IDX_MAX_RINGS < B4_DMA_NEEDED, "host memory, stage JOIN");
_Static_assert(TX_BUFS < FLOW_DEPTH, "the flow ring must hold every TX buffer");
_Static_assert(RESP_BUFS + EVENT_BUFS + 2 < CTRL_DEPTH, "and a flow ring request on top");

static void put16(uint8_t *b, uint32_t at, uint16_t v) { memcpy(b + at, &v, 2); }
static void put32(uint8_t *b, uint32_t at, uint32_t v) { memcpy(b + at, &v, 4); }
static uint16_t get16(const uint8_t *b, uint32_t at) { uint16_t v; memcpy(&v, b + at, 2); return v; }
static uint32_t get32(const uint8_t *b, uint32_t at) { uint32_t v; memcpy(&v, b + at, 4); return v; }
static void sync_dma(struct p1 *p, void *va, uint32_t bytes) { p->ops.dma_sync(p->ops.ctx, va, bytes); }
static int ring_db(struct p1 *p, uint32_t reg, uint32_t v) { return p1_wr(p, BAR0_PCIE + reg, v); }

/* ---- Host memory ---- */

static uint8_t *
carve(struct p1 *p, uint32_t bytes, uint32_t align, uint64_t *pa)
{
	uint32_t at = (p->dma_used + align - 1) & ~(align - 1);

	if (at > p->cfg.dma.bytes || bytes > p->cfg.dma.bytes - at) {
		return NULL;
	}
	p->dma_used = at + bytes;
	*pa = p->cfg.dma.pa + at;
	return p->cfg.dma.va + at;
}

static int
carve_all(struct p1 *p)
{
	static const uint16_t items[B4_COMMON_RINGS] = { H2D_CTRL_ITEM, H2D_RXPOST_ITEM, D2H_CTRL_ITEM, D2H_TX_ITEM, D2H_RX_ITEM };
	static const uint16_t depths[B4_COMMON_RINGS] = { CTRL_DEPTH, RX_POST_DEPTH, CTRL_DEPTH, CTRL_DEPTH, RX_CPL_DEPTH };
	uint32_t arr[4];

	if (p->cfg.dma.va == NULL || p->cfg.dma.bytes < B4_DMA_NEEDED || (p->cfg.dma.pa & 0xfffu) != 0 || p->ops.dma_sync == NULL) {
		return p1_halt(p, P1_STOP_NO_DMA, p->cfg.dma.bytes);
	}
	arr[0] = arr[1] = p->max_submission * IDX_WORD;
	arr[2] = arr[3] = p->max_completion * IDX_WORD;
	p->dma_used = 0;
	memset(p->cfg.dma.va, 0, p->cfg.dma.bytes);
	for (unsigned i = 0; i < B4_COMMON_RINGS; i++) {
		struct b4_ring *r = &p->ring[i];

		r->depth = depths[i];
		r->item = items[i];
		r->wr = r->rd = 0;
		r->tries = 0;
		r->seq = EPOCH_INIT;
		r->phase = i >= B4_D2H_CTRL ? PHASE_INIT : 0;   /* dhd_prot_d2h_sync_init, _h2d_sync_init */
		r->va = carve(p, (uint32_t)r->depth * r->item, 4096, &r->pa);
		if (r->va == NULL) {
			return p1_halt(p, P1_STOP_NO_DMA, i);
		}
	}
	for (unsigned i = 0; i < 4; i++) {
		p->idx_arr[i] = carve(p, arr[i], 64, &p->idx_pa[i]);
		if (p->idx_arr[i] == NULL) {
			return p1_halt(p, P1_STOP_NO_DMA, 0x10 + i);
		}
	}
	p->ioc_req = carve(p, IOC_REQ_BYTES, 4096, &p->ioc_req_pa);
	p->resp_buf = carve(p, RESP_BUF_BYTES * RESP_BUFS, 4096, &p->resp_pa);
	p->event_buf = carve(p, EVENT_BUF_BYTES * EVENT_BUFS, 4096, &p->event_pa);
	p->rx_buf = carve(p, RX_BUF_BYTES * RX_BUFS, 4096, &p->rx_pa);
	if (p->ioc_req == NULL || p->resp_buf == NULL || p->event_buf == NULL || p->rx_buf == NULL || carve(p, SCRATCH_BYTES, 4096, &p->scratch_pa) == NULL) {
		return p1_halt(p, P1_STOP_NO_DMA, 0x20);
	}
	if (p->cfg.stage >= P1_STAGE_JOIN) {
		struct b4_ring *r = &p->ring[B4_FLOW_RING];

		r->depth = FLOW_DEPTH;
		r->item = FLOW_ITEM;
		r->wr = r->rd = 0;
		r->seq = EPOCH_INIT;
		r->phase = 0;           /* dhd_prot_flowrings_pool_fetch: from 0, as any H2D ring */
		r->va = carve(p, FLOW_DEPTH * FLOW_ITEM, 4096, &r->pa);
		p->tx_buf = carve(p, TX_BUF_BYTES * TX_BUFS, 4096, &p->tx_pa);
		if (r->va == NULL || p->tx_buf == NULL) {
			return p1_halt(p, P1_STOP_NO_DMA, 0x21);
		}
	}
	sync_dma(p, p->cfg.dma.va, p->cfg.dma.bytes);
	return 0;
}

/* ---- The chip's RAM: what the host owns in it ---- */

static bool
in_ram(uint32_t addr, uint32_t bytes)
{
	return addr >= RAM_BASE && addr < RAM_END && bytes <= RAM_END - addr && (addr & 3u) == 0;
}

static void
span(struct p1 *p, uint32_t addr, uint32_t bytes)
{
	if (p->tcm_w_n < sizeof(p->tcm_w) / sizeof(p->tcm_w[0])) {
		p->tcm_w[p->tcm_w_n].addr = addr;
		p->tcm_w[p->tcm_w_n].bytes = bytes;
		p->tcm_w_n++;
	}
}

/* dhdpcie_readshared: the checks, then dhd_fillup_ring_sharedptr_info */
static int
read_ring_info(struct p1 *p)
{
	uint32_t ri = p->rings_info, m1 = 0, m2 = 0, v = 0;

	/* First: a firmware stuck on its early shared area has no ring info and no sync flags either, and this is what's wrong with it */
	if (!in_ram(ri, 64) || (p->d2h_mb_ptr != 0 && !in_ram(p->d2h_mb_ptr, 4))) {
		return p1_halt(p, P1_STOP_RING_INFO, ri);
	}
	if ((p->shared_flags & F_VERSION) != 9) {
		p->ops.log(p->ops.ctx, "ring: IPC version %u, this was written for 9\n", p->shared_flags & F_VERSION);
	}
	if (!(p->shared_flags & F_SYNC_XORCSUM) || (p->shared_flags & F_SYNC_SEQNUM)) {
		return p1_halt(p, P1_STOP_SYNC_MODE, p->shared_flags);
	}
	if (p->shared_flags & F_2BYTE_INDEX) {
		return p1_halt(p, P1_STOP_INDEX_SIZE, p->shared_flags);
	}
	if (b4_tcm_rd(p, ri + RI_RINGMEM, &p->ringmem) || b4_tcm_rd(p, ri + RI_H2D_W, &p->h2d_w) || b4_tcm_rd(p, ri + RI_H2D_R, &p->h2d_r) || b4_tcm_rd(p, ri + RI_D2H_W, &p->d2h_w) ||
	    b4_tcm_rd(p, ri + RI_D2H_R, &p->d2h_r) || b4_tcm_rd(p, ri + RI_MAX_1, &m1) || b4_tcm_rd(p, ri + RI_MAX_2, &m2)) {
		return (int)p->stop;
	}
	p->max_flowrings = m1 & 0xffffu;
	p->max_submission = m1 >> 16;
	p->max_completion = m2 & 0xffffu;
	p->max_vdevs = m2 >> 16;
	p->ops.log(p->ops.ctx, "ring: info at 0x%x: ring memory 0x%x, H2D write 0x%x read 0x%x, D2H write 0x%x read 0x%x. Flow rings %u, submission %u, completion %u. Android: 43, 4\n", ri, p->ringmem, p->h2d_w, p->h2d_r, p->d2h_w, p->d2h_r, p->max_flowrings, p->max_submission, p->max_completion);
	if (!in_ram(p->ringmem, RM_SIZE * B4_COMMON_RINGS) || !in_ram(p->h2d_w, 3 * IDX_WORD) || !in_ram(p->h2d_r, 3 * IDX_WORD) || !in_ram(p->d2h_w, 3 * IDX_WORD) || !in_ram(p->d2h_r, 3 * IDX_WORD) ||
	    p->max_submission < 2 || p->max_submission > IDX_MAX_RINGS || p->max_completion < 3 || p->max_completion > IDX_MAX_RINGS) {
		return p1_halt(p, P1_STOP_RING_INFO, p->max_submission << 16 | p->max_completion);
	}
	/* Each must read as a ring nobody has touched, or these aren't ring addresses */
	if (b4_tcm_rd(p, p->h2d_w, &v)) {
		return (int)p->stop;
	}
	if (v != 0) {
		p->ops.log(p->ops.ctx, "ring: H2D control write index reads 0x%x before anything was sent\n", v);
	}
	p->tcm_w_n = 0;
	span(p, p->shared_addr + S_SCRATCH_LEN, 12);
	span(p, p->shared_addr + S_HOST_CAP, 4);
	span(p, p->shared_addr + S_HOST_CAP2, 4);
	span(p, ri + RI_HOST_ADDRS, 32);
	span(p, p->ringmem, RM_SIZE * B4_COMMON_RINGS);
	span(p, p->h2d_w, 3 * IDX_WORD);        /* The two common rings and flow 2 */
	span(p, p->h2d_r, 3 * IDX_WORD);
	span(p, p->d2h_w, 3 * IDX_WORD);
	span(p, p->d2h_r, 3 * IDX_WORD);
	if (p->d2h_mb_ptr != 0) {
		span(p, p->d2h_mb_ptr, 4);
	}
	return 0;
}

/* ---- Ring indices ---- */

enum { IDX_H2D_W, IDX_H2D_R, IDX_D2H_W, IDX_D2H_R };

static uint32_t
tcm_idx_addr(const struct p1 *p, unsigned which, unsigned slot)
{
	uint32_t base = which == IDX_H2D_W ? p->h2d_w : which == IDX_H2D_R ? p->h2d_r : which == IDX_D2H_W ? p->d2h_w : p->d2h_r;

	return base + slot * IDX_WORD;
}

static int
idx_get(struct p1 *p, unsigned which, unsigned slot, uint16_t *v)
{
	uint32_t w = 0;

	if (p->idx_host) {
		uint8_t *at = p->idx_arr[which] + slot * IDX_WORD;

		sync_dma(p, at, IDX_WORD);
		w = get32(at, 0);
	} else if (b4_tcm_rd(p, tcm_idx_addr(p, which, slot), &w)) {
		return (int)p->stop;
	}
	*v = (uint16_t)w;
	return 0;
}

static int
idx_set(struct p1 *p, unsigned which, unsigned slot, uint16_t v)
{
	if (p->idx_host) {
		uint8_t *at = p->idx_arr[which] + slot * IDX_WORD;

		put32(at, 0, v);
		sync_dma(p, at, IDX_WORD);
		return 0;
	}
	return b4_tcm_wr16(p, tcm_idx_addr(p, which, slot), v);
}

/* ---- H2D: dhd_prot_alloc_ring_space, dhd_prot_ring_write_complete ---- */

static unsigned h2d_index_slot(unsigned id) { return id == B4_FLOW_RING ? FLOW_ID : id; }

static uint8_t *
h2d_slot(struct p1 *p, unsigned id)
{
	struct b4_ring *r = &p->ring[id];
	uint16_t next = (uint16_t)(r->wr + 1 == r->depth ? 0 : r->wr + 1);
	uint8_t *s;

	if (next == r->rd) {
		if (idx_get(p, IDX_H2D_R, h2d_index_slot(id), &r->rd)) {
			return NULL;
		}
		if (r->rd >= r->depth || next == r->rd) {
			p1_halt(p, P1_STOP_RING_FULL, (uint32_t)r->rd << 16 | r->wr);
			return NULL;
		}
	}
	s = r->va + (uint32_t)r->wr * r->item;
	memset(s, 0, r->item);
	return s;
}

static void
h2d_header(struct b4_ring *r, uint8_t *s, uint8_t type, uint32_t id)
{
	s[0] = type;
	s[1] = 0;               /* if_id */
	s[2] = r->phase;
	s[3] = (uint8_t)(r->seq % EPOCH_MODULO);
	r->seq++;
	put32(s, 4, id);
}

static int
h2d_commit(struct p1 *p, unsigned id, uint8_t *s)
{
	struct b4_ring *r = &p->ring[id];

	sync_dma(p, s, r->item);
	r->wr++;
	if (r->wr == r->depth) {
		r->wr = 0;
		r->phase = r->phase ? 0 : PHASE_INIT;
	}
	if (idx_set(p, IDX_H2D_W, h2d_index_slot(id), r->wr)) {
		return (int)p->stop;
	}
	return ring_db(p, P_DB0, DB_WR_MAGIC | (uint32_t)id << 16 | r->wr);
}

static int
post_buffer(struct p1 *p, uint8_t type, uint32_t id, uint64_t pa, uint16_t bytes)
{
	struct b4_ring *r = &p->ring[B4_H2D_CTRL];
	uint8_t *s = h2d_slot(p, B4_H2D_CTRL);

	if (s == NULL) {
		return (int)p->stop;
	}
	h2d_header(r, s, type, id);
	put16(s, 8, bytes);
	put32(s, 16, (uint32_t)pa);
	put32(s, 20, (uint32_t)(pa >> 32));
	return h2d_commit(p, B4_H2D_CTRL, s);
}

static int
post_resp(struct p1 *p, uint32_t i)
{
	/* The buffer is the chip's to write until it comes back: nothing of ours left in the cache on top of it */
	sync_dma(p, p->resp_buf + i * RESP_BUF_BYTES, RESP_BUF_BYTES);
	return post_buffer(p, MSG_RESP_POST, RESP_ID_BASE + i, p->resp_pa + i * RESP_BUF_BYTES, RESP_BUF_BYTES);
}

static int
post_event(struct p1 *p, uint32_t i)
{
	sync_dma(p, p->event_buf + i * EVENT_BUF_BYTES, EVENT_BUF_BYTES);
	return post_buffer(p, MSG_EVENT_POST, EVENT_ID_BASE + i, p->event_pa + i * EVENT_BUF_BYTES, EVENT_BUF_BYTES);
}

/* dhd_prot_rxbuf_post_fill. No metadata buffer: dhd_prot_init's rx_metadata_offset is 0 */
static int
post_rx(struct p1 *p, uint32_t i)
{
	struct b4_ring *r = &p->ring[B4_H2D_RXPOST];
	uint64_t pa = p->rx_pa + i * RX_BUF_BYTES;
	uint8_t *s;

	sync_dma(p, p->rx_buf + i * RX_BUF_BYTES, RX_BUF_BYTES);
	s = h2d_slot(p, B4_H2D_RXPOST);
	if (s == NULL) {
		return (int)p->stop;
	}
	h2d_header(r, s, MSG_RX_POST, RX_ID_BASE + i);
	put16(s, RX_POST_LEN_AT, RX_BUF_BYTES);
	put32(s, RX_POST_ADDR_AT, (uint32_t)pa);
	put32(s, RX_POST_ADDR_AT + 4, (uint32_t)(pa >> 32));
	return h2d_commit(p, B4_H2D_RXPOST, s);
}

/* dhd_prot_flow_ring_create. Stock makes a station's ring when its first frame is ready, with that frame's destination, and everything of that priority goes on it */
int
b4_flow_create(struct p1 *p, const uint8_t *sa, const uint8_t *da)
{
	struct b4_ring *c = &p->ring[B4_H2D_CTRL], *f = &p->ring[B4_FLOW_RING];
	uint8_t *s;

	if (b4_gate_level(p) < B4_GATE_ARMED) {
		return p1_halt(p, P1_STOP_IOCTL_REFUSED, MSG_FLOW_CREATE);
	}
	s = h2d_slot(p, B4_H2D_CTRL);
	if (s == NULL) {
		return (int)p->stop;
	}
	h2d_header(c, s, MSG_FLOW_CREATE, 0);
	memcpy(s + FC_DA, da, 6);
	memcpy(s + FC_SA, sa, 6);
	s[FC_TID] = 0;
	put16(s, FC_RING_ID, FLOW_ID);
	put16(s, FC_MAX_ITEMS, FLOW_DEPTH);
	put16(s, FC_LEN_ITEM, FLOW_ITEM);
	put32(s, FC_RING_PTR, (uint32_t)f->pa);
	put32(s, FC_RING_PTR + 4, (uint32_t)(f->pa >> 32));
	p->flow_state = 1;
	return h2d_commit(p, B4_H2D_CTRL, s);
}

uint32_t
b4_tx_free(const struct p1 *p)
{
	uint32_t n = 0;

	for (uint32_t i = 0; i < TX_BUFS; i++) {
		if (!(p->tx_busy & (1u << i))) {
			n++;
		}
	}
	return n;
}

_Static_assert(TX_BUFS <= 32, "tx_busy is one word");

/* dhd_prot_txdata: the header in the item, the rest in a buffer of ours until its status comes back. Refused unless armed and the keys are in */
int
b4_tx_post(struct p1 *p, const uint8_t *frame, uint32_t bytes)
{
	struct b4_ring *r = &p->ring[B4_FLOW_RING];
	uint32_t i = 0, payload;
	uint64_t pa;
	uint8_t *s;

	if (b4_gate_level(p) < B4_GATE_ARMED || !p->net_on || p->flow_state != 2) {
		return p1_halt(p, P1_STOP_IOCTL_REFUSED, MSG_TX_POST);
	}
	if (bytes < ETH_HDR || bytes - ETH_HDR > TX_BUF_BYTES) {
		p->rx_dropped++;
		return 0;
	}
	while (i < TX_BUFS && (p->tx_busy & (1u << i))) {
		i++;
	}
	if (i == TX_BUFS) {
		return 0;               /* The callers look at b4_tx_free first. A protocol timer will try again */
	}
	payload = bytes - ETH_HDR;
	memcpy(p->tx_buf + i * TX_BUF_BYTES, frame + ETH_HDR, payload);
	sync_dma(p, p->tx_buf + i * TX_BUF_BYTES, payload);
	s = h2d_slot(p, B4_FLOW_RING);
	if (s == NULL) {
		return (int)p->stop;
	}
	pa = p->tx_pa + i * TX_BUF_BYTES;
	h2d_header(r, s, MSG_TX_POST, TX_ID_BASE + i);
	memcpy(s + TP_ETH, frame, ETH_HDR);
	s[TP_FLAGS] = TP_FRAME_802_3;   /* Priority 0 in its top bits */
	s[TP_SEG_CNT] = 1;
	put32(s, TP_DATA_ADDR, (uint32_t)pa);
	put32(s, TP_DATA_ADDR + 4, (uint32_t)(pa >> 32));
	put16(s, TP_DATA_LEN, (uint16_t)payload);
	p->tx_busy |= 1u << i;
	p->tx_sent++;
	return h2d_commit(p, B4_FLOW_RING, s);
}

/* The ioctl buffers can hold a key on the way past. Nothing is in flight here: the firmware writes a response buffer only for an ioctl */
void
b4_wipe_ioctl(struct p1 *p)
{
	memset(p->ioc_req, 0, IOC_REQ_BYTES);
	sync_dma(p, p->ioc_req, IOC_REQ_BYTES);
	for (uint32_t i = 0; i < RESP_BUFS; i++) {
		memset(p->resp_buf + i * RESP_BUF_BYTES, 0, 512);
		sync_dma(p, p->resp_buf + i * RESP_BUF_BYTES, 512);
	}
	memset(p->ioc_big, 0, sizeof(p->ioc_big));
}

/* r5: RX_BUFS, or fewer if the firmware's max_host_rxbufs (shared area) says so. Stock posts that many (dhd_prot_init's max_rxbufpost) */
uint32_t
b4_rx_bufs_wanted(const struct p1 *p)
{
	return p->max_rxbufs != 0 && p->max_rxbufs < RX_BUFS ? p->max_rxbufs : RX_BUFS;
}

int
b4_rx_post_all(struct p1 *p)
{
	uint32_t n = b4_rx_bufs_wanted(p);

	for (uint32_t i = 0; i < n; i++) {
		if (post_rx(p, i)) {
			return (int)p->stop;
		}
		p->rx_posted++;
	}
	return 0;
}

/* r4: did the dongle ever take an RX buffer? Read, never written: the RX post ring's read index is the dongle's (it moves as it fetches
 * our buffers), the RX completion ring's write index too. r1-r3 never had an RX item, and a data frame (M1 is the first) needs a host buffer */
int
b4_rx_witness(struct p1 *p, const char *when)
{
	uint16_t post_rd = 0, cpl_wr = 0;

	if (idx_get(p, IDX_H2D_R, h2d_index_slot(B4_H2D_RXPOST), &post_rd) || idx_get(p, IDX_D2H_W, B4_D2H_RX - B4_D2H_CTRL, &cpl_wr)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "rx: witness %s: post ring written to %u, the dongle has read to %u (%s); completion ring: dongle at %u, us at %u. Items %u, %u bytes, %u dropped. Firmware drops for want of a host buffer (EL 30 b8c8): %u\n", when,
	    p->ring[B4_H2D_RXPOST].wr, post_rd, post_rd == p->ring[B4_H2D_RXPOST].wr ? "all taken" : post_rd == 0 ? "none taken" : "some taken", cpl_wr, p->ring[B4_D2H_RX].rd,
	    p->rx_items, p->rx_bytes, p->rx_dropped, p->fw_rx_nobuf);
	return 0;
}

/* ---- D2H: dhd_prot_process_ctrlbuf, dhd_prot_d2h_sync_xorcsum ---- */

static int
on_completion(struct p1 *p, const uint8_t *it)
{
	uint8_t type = it[0];
	uint32_t req = get32(it, 4);
	int16_t status = (int16_t)get16(it, 8);

	switch (type) {
	case MSG_IOCTL_ACK:
		p->ioc_seen_ack++;
		if (p->ioc_state == 3) {
			p->ioc_state = 2;
		} else {
			p->ops.log(p->ops.ctx, "ioctl: ack with state %u\n", p->ioc_state);
		}
		if (status != 0) {
			p->ops.log(p->ops.ctx, "ioctl: ack status %d\n", status);
		}
		return 0;
	case MSG_IOCTL_CMPLT: {
		uint16_t len = get16(it, 12), trans = get16(it, 14);
		uint32_t cmd = get32(it, 16), i = req - RESP_ID_BASE;

		if (p->ioc_state != 2 || i >= RESP_BUFS || trans != p->ioc_trans || cmd != p->ioc_cmd || len > RESP_BUF_BYTES) {
			p->ops.log(p->ops.ctx, "ioctl: completion: state %u, request id 0x%x, trans %u (mine %u), cmd %u (mine %u), %u bytes\n", p->ioc_state, req, trans, p->ioc_trans, cmd, p->ioc_cmd, len);
			return p1_halt(p, P1_STOP_IOCTL_REPLY, req);
		}
		sync_dma(p, p->resp_buf + i * RESP_BUF_BYTES, len);
		p->ioc_got_len = len < p->ioc_out_len ? len : p->ioc_out_len;
		if (p->ioc_out != NULL) {
			memcpy(p->ioc_out, p->resp_buf + i * RESP_BUF_BYTES, p->ioc_got_len);
		}
		p->ioc_status = status;
		p->ioc_state = 0;
		return post_resp(p, i);
	}
	case MSG_WL_EVENT: {
		uint32_t i = req - EVENT_ID_BASE;
		uint16_t len = get16(it, EVENT_LEN_AT);
		uint8_t *b;

		p->events_seen++;
		if (i >= EVENT_BUFS) {
			return p1_halt(p, P1_STOP_IOCTL_REPLY, req);
		}
		b = p->event_buf + i * EVENT_BUF_BYTES;
		sync_dma(p, b, EVENT_BUF_BYTES);
		/* DMA RX offset from the shared area, as dhd_prot_event_process. The firmware's length isn't trusted past the buffer */
		if (p->rx_offset < EVENT_BUF_BYTES) {
			b4_on_event(p, b + p->rx_offset, len < EVENT_BUF_BYTES - p->rx_offset ? len : EVENT_BUF_BYTES - p->rx_offset);
		} else {
			p->ev_bad++;
		}
		return post_event(p, i);
	}
	case MSG_FLOW_CREATED:
		b4_on_flow_created(p, status, get16(it, 10));
		return (int)p->stop;
	case MSG_GEN_STATUS:
	case MSG_RING_STATUS:
		p->ops.log(p->ops.ctx, "ring: status item type %u: status %d, ring %u\n", type, status, get16(it, 10));
		return 0;
	default:
		p->other_seen++;
		p->ops.log(p->ops.ctx, "ring: item type %u, request id 0x%x: not handled\n", type, req);
		return 0;
	}
}

/* Every RX completion gives its buffer back, whatever it holds. With no association, a frame nobody wants here. Its bytes aren't read */
static int
on_rx_item(struct p1 *p, const uint8_t *it)
{
	uint32_t req = get32(it, 4), i = req - RX_ID_BASE;

	if (it[0] != MSG_RX_CMPLT || i >= RX_BUFS) {
		p->ops.log(p->ops.ctx, "ring: RX ring item type %u, request id 0x%x\n", it[0], req);
		return p1_halt(p, P1_STOP_BAD_ITEM, req);
	}
	p->rx_items++;
	p->rx_bytes += get16(it, RX_DATA_LEN_AT);
	if (p->rx_items <= ITEM_LOG_MAX) {
		p->ops.log(p->ops.ctx, "rx: item %u: status %d, %u bytes at offset %u\n", p->rx_items, (int16_t)get16(it, 8), get16(it, RX_DATA_LEN_AT), get16(it, RX_DATA_OFF_AT));
	}
	/* Only once there's a network: below stage JOIN, or before the keys, its bytes aren't read */
	if (p->net_on) {
		uint32_t off = get16(it, RX_DATA_OFF_AT), len = get16(it, RX_DATA_LEN_AT);

		if (off == 0) {
			off = p->rx_offset;     /* dhd_prot_process_msgbuf_rxcpl: its own offset, else the shared area's */
		}
		if (off < RX_BUF_BYTES && len != 0 && len <= RX_BUF_BYTES - off) {
			sync_dma(p, p->rx_buf + i * RX_BUF_BYTES, RX_BUF_BYTES);
			b4_net_rx(p, p->rx_buf + i * RX_BUF_BYTES + off, len);
		} else {
			p->rx_dropped++;
		}
	}
	return post_rx(p, i);
}

/* Below an armed join nothing sends a frame, so this should stay silent. Above it, a status gives its buffer back */
static int
on_tx_item(struct p1 *p, const uint8_t *it)
{
	uint32_t i = get32(it, 4) - TX_ID_BASE;

	p->tx_items++;
	if (p->tx_items <= ITEM_LOG_MAX) {
		p->ops.log(p->ops.ctx, "tx: completion item %u: type %u, request id 0x%x, status %d\n", p->tx_items, it[0], get32(it, 4), (int16_t)get16(it, 8));
	}
	if (p->net_on) {
		if (it[0] != MSG_TX_STATUS || i >= TX_BUFS || !(p->tx_busy & (1u << i))) {
			return p1_halt(p, P1_STOP_BAD_ITEM, get32(it, 4));
		}
		if (get16(it, 8) != 0) {
			p->tx_status_bad++;
		}
		p->tx_busy &= ~(1u << i);
		p->tx_done++;
	}
	return 0;
}

static int
poll_ring(struct p1 *p, unsigned id)
{
	struct b4_ring *r = &p->ring[id];
	unsigned slot = id - B4_D2H_CTRL;
	uint16_t w = 0;

	if (idx_get(p, IDX_D2H_W, slot, &w)) {
		return (int)p->stop;
	}
	if (w >= r->depth) {
		return p1_halt(p, P1_STOP_BAD_ITEM, w);
	}
	while (r->rd != w) {
		uint8_t *it = r->va + (uint32_t)r->rd * r->item;
		uint32_t x = 0;

		sync_dma(p, it, r->item);
		for (uint32_t i = 0; i < r->item; i += 4) {
			x ^= get32(it, i);
		}
		if (it[3] != (uint8_t)(r->seq % EPOCH_MODULO) || x != 0) {
			/* Index ahead of the item: DMA still landing. What XORCSUM is for. It stays unread until the next poll */
			if (++r->tries >= ITEM_TRIES) {
				p->ops.log(p->ops.ctx, "ring: item %u never landed: epoch %u, want %u, xor 0x%x: %08x %08x %08x %08x %08x %08x\n", r->rd, it[3], (uint8_t)(r->seq % EPOCH_MODULO), x,
				    get32(it, 0), get32(it, 4), get32(it, 8), get32(it, 12), get32(it, 16), get32(it, 20));
				return p1_halt(p, P1_STOP_BAD_ITEM, r->rd);
			}
			return 0;
		}
		r->seq++;
		r->tries = 0;
		if ((id == B4_D2H_CTRL ? on_completion(p, it) : id == B4_D2H_RX ? on_rx_item(p, it) : on_tx_item(p, it)) != 0) {
			return (int)p->stop;
		}
		r->rd = (uint16_t)(r->rd + 1 == r->depth ? 0 : r->rd + 1);
		if (idx_set(p, IDX_D2H_R, slot, r->rd)) {
			return (int)p->stop;
		}
		if (p->idx_host && ring_db(p, P_DB0, DB_RD_MAGIC | (uint32_t)id << 16 | r->rd)) {
			return (int)p->stop;
		}
	}
	return 0;
}

/* dhdpcie_read_handle_mb_data and the trap flag: the firmware saying it has stopped */
static int
check_alive(struct p1 *p)
{
	uint32_t f = 0, mb = 0;

	if (b4_tcm_rd(p, p->shared_addr, &f) || (p->d2h_mb_ptr != 0 && b4_tcm_rd(p, p->d2h_mb_ptr, &mb))) {
		return (int)p->stop;
	}
	if (mb != 0) {
		p->ops.log(p->ops.ctx, "ring: mailbox data 0x%x\n", mb);
		if (b4_tcm_wr(p, p->d2h_mb_ptr, 0)) {
			return (int)p->stop;
		}
	}
	if ((f & (F_TRAP | F_ASSERT)) || (mb & D2H_FWHALT)) {
		uint32_t t = 0;

		if (b4_tcm_rd(p, p->shared_addr + S_TRAP, &t)) {
			return (int)p->stop;
		}
		p->ops.log(p->ops.ctx, "ring: firmware stopped: flags 0x%x, mailbox 0x%x, trap at 0x%x\n", f, mb, t);
		if (in_ram(t, 4 * TRAP_WORDS)) {
			for (unsigned i = 0; i < TRAP_WORDS; i += 4) {
				uint32_t w[4] = { 0 };

				for (unsigned j = 0; j < 4; j++) {
					if (b4_tcm_rd(p, t + (i + j) * 4, &w[j])) {
						return (int)p->stop;
					}
				}
				p->ops.log(p->ops.ctx, "ring: trap +%02x: %08x %08x %08x %08x\n", i * 4, w[0], w[1], w[2], w[3]);
			}
		}
		(void)b4_console(p);
		return p1_halt(p, P1_STOP_FW_TRAP, f);
	}
	return 0;
}

int
b4_poll(struct p1 *p)
{
	if (poll_ring(p, B4_D2H_CTRL) || poll_ring(p, B4_D2H_TX) || poll_ring(p, B4_D2H_RX) || check_alive(p)) {
		return (int)p->stop;
	}
	return 0;
}

/* ---- Ioctl: dhd_fillup_ioct_reqst, dhd_msgbuf_wait_ioctl_cmplt ---- */

int
b4_ioctl(struct p1 *p, uint32_t cmd, uint8_t *buf, uint16_t len)
{
	struct b4_ring *r = &p->ring[B4_H2D_CTRL];
	uint8_t *s;

	/* The one way anything reaches the firmware. What isn't on the list doesn't go */
	if (!b4_ioctl_allowed(cmd, buf, len, b4_gate_level(p))) {
		return p1_halt(p, P1_STOP_IOCTL_REFUSED, cmd);
	}
	if (len > RESP_BUF_BYTES || (cmd == WLC_SET_VAR && len > IOC_MAX_IN)) {
		return p1_halt(p, P1_STOP_IOCTL_REFUSED, len);
	}
	memcpy(p->ioc_req, buf, len);
	sync_dma(p, p->ioc_req, len);
	s = h2d_slot(p, B4_H2D_CTRL);
	if (s == NULL) {
		return (int)p->stop;
	}
	h2d_header(r, s, MSG_IOCTL_REQ, IOCTL_REQ_ID);
	p->ioc_trans++;
	p->ioc_cmd = cmd;
	p->ioc_out = buf;
	p->ioc_out_len = len;
	p->ioc_got_len = 0;
	p->ioc_status = 0;
	p->ioc_state = 3;       /* MSGBUF_IOCTL_ACK_PENDING | MSGBUF_IOCTL_RESP_PENDING */
	put32(s, 8, cmd);
	put16(s, 12, p->ioc_trans);
	put16(s, 14, len < IOC_MAX_IN ? len : IOC_MAX_IN);
	put16(s, 16, len);
	put32(s, 24, (uint32_t)p->ioc_req_pa);
	put32(s, 28, (uint32_t)(p->ioc_req_pa >> 32));
	if (h2d_commit(p, B4_H2D_CTRL, s)) {
		return (int)p->stop;
	}
	for (uint32_t ms = 0; p->ioc_state != 0; ms += POLL_MS) {
		if (b4_poll(p)) {
			return (int)p->stop;
		}
		if (p->ioc_state == 0) {
			break;
		}
		if (ms >= IOCTL_WAIT_MS) {
			uint16_t rd = 0;

			(void)idx_get(p, IDX_H2D_R, B4_H2D_CTRL, &rd);
			p->ops.log(p->ops.ctx, "ioctl: cmd %u: no answer in %u ms, state %u. Control ring: chip's read index %u, mine %u, write %u\n", cmd, ms, p->ioc_state, rd, r->rd, r->wr);
			return p1_halt(p, P1_STOP_IOCTL_TIMEOUT, cmd);
		}
		p->ops.delay_us(p->ops.ctx, POLL_MS * 1000);
	}
	return 0;
}

static uint32_t
iovar_name(uint8_t *buf, uint32_t bytes, const char *name)
{
	uint32_t n = 0;

	memset(buf, 0, bytes);
	while (name[n] != 0 && n + 1 < bytes) {
		buf[n] = (uint8_t)name[n];
		n++;
	}
	return n;
}

static int
first_ioctls(struct p1 *p)
{
	uint8_t rev[REV_BYTES], ver[VER_BYTES], wlc[128];

	/* dhd_sync_with_dongle's own order */
	p->ops.log(p->ops.ctx, "ioctl: next: first one, wlc_ver\n");
	iovar_name(wlc, sizeof(wlc), "wlc_ver");
	if (b4_ioctl(p, WLC_GET_VAR, wlc, sizeof(wlc))) {
		return (int)p->stop;
	}
	p->wlc_major = get16(wlc, WLC_VER_MAJOR);
	p->wlc_minor = get16(wlc, WLC_VER_MINOR);
	p->ops.log(p->ops.ctx, "ioctl: wlc_ver: status %d, %u bytes back. Major %u, minor %u\n", p->ioc_status, p->ioc_got_len, p->wlc_major, p->wlc_minor);

	memset(rev, 0, sizeof(rev));
	if (b4_ioctl(p, WLC_GET_REVINFO, rev, sizeof(rev))) {
		return (int)p->stop;
	}
	p->rev_vendor = get32(rev, REV_VENDOR);
	p->rev_device = get32(rev, REV_DEVICE);
	p->rev_chiprev = get32(rev, REV_CHIPREV);
	p->rev_corerev = get32(rev, REV_CORE);
	p->rev_chipnum = get32(rev, REV_CHIPNUM);
	p->ops.log(p->ops.ctx, "ioctl: GET_REVINFO: status %d, device 0x%x, vendor 0x%x, chipnum 0x%x, chip rev %u, core rev %u. Android: 0x4438, 0x14e4, 0x4390\n", p->ioc_status, p->rev_device, p->rev_vendor, p->rev_chipnum, p->rev_chiprev, p->rev_corerev);
	if (p->ioc_status != 0 || p->rev_vendor != 0x14e4u || p->rev_chipnum != 0x4390u) {
		return p1_halt(p, P1_STOP_IOCTL_REPLY, p->rev_chipnum);
	}
	p->rev_ok = true;

	iovar_name(ver, sizeof(ver), "ver");
	if (b4_ioctl(p, WLC_GET_VAR, ver, sizeof(ver))) {
		return (int)p->stop;
	}
	if (p->ioc_status == 0) {
		uint32_t n = 0;

		while (n + 1 < sizeof(p->fw_ver) && n < p->ioc_got_len && ver[n] >= 32 && ver[n] < 127) {
			p->fw_ver[n] = (char)ver[n];
			n++;
		}
		p->fw_ver[n] = 0;
	}
	p->ops.log(p->ops.ctx, "ioctl: ver: status %d: %s\n", p->ioc_status, p->fw_ver);
	return 0;
}

/* ---- Bring-up: dhd_prot_init ---- */

static int
ring_init(struct p1 *p, unsigned id)
{
	struct b4_ring *r = &p->ring[id];
	uint32_t m = p->ringmem + id * RM_SIZE;

	/* In TCM either way: the index words start from 0 in both modes, as dhd_prot_ring_init writes them. A 16-bit pair is one word, written at once */
	if (b4_tcm_wr(p, m + RM_BASE, (uint32_t)r->pa) || b4_tcm_wr(p, m + RM_BASE + 4, (uint32_t)(r->pa >> 32)) || b4_tcm_wr(p, m + RM_MAX_LEN, (uint32_t)r->item << 16 | r->depth)) {
		return (int)p->stop;
	}
	if (id < B4_D2H_CTRL) {
		return b4_tcm_wr(p, tcm_idx_addr(p, IDX_H2D_W, id), 0) || b4_tcm_wr(p, tcm_idx_addr(p, IDX_H2D_R, id), 0) ? (int)p->stop : 0;
	}
	return b4_tcm_wr(p, tcm_idx_addr(p, IDX_D2H_W, id - B4_D2H_CTRL), 0) || b4_tcm_wr(p, tcm_idx_addr(p, IDX_D2H_R, id - B4_D2H_CTRL), 0) ? (int)p->stop : 0;
}

static int
rings_run(struct p1 *p)
{
	uint32_t cap, ver = p->shared_flags & F_VERSION;

	if (read_ring_info(p) || carve_all(p)) {
		return (int)p->stop;
	}
	/* The end of dhdpcie_readshared: "De-assert WL domain in DAR". Stock then requests the domain around each access; one request across all of this does the same */
	if (b4_power(p, true) || p1_rmw(p, BAR0_PCIE + P_DAR_PWR, PWR_REQ_DMN1, 0)) {
		return (int)p->stop;
	}
	p->idx_host = !p->cfg.idx_tcm && (p->shared_flags & F_DMA_INDEX) != 0;
	p->ops.log(p->ops.ctx, "ring: host memory at 0x%llx, 0x%x bytes, 0x%x used. Indices in %s. Next: host capabilities\n", p->cfg.dma.pa, p->cfg.dma.bytes, p->dma_used, p->idx_host ? "host memory, as Android" : "the chip's RAM");
	/* dhd_set_host_cap: "Disable DS altogether". The version is the lower of the two; this code is 9's */
	cap = (ver < 9 ? ver : 9) | CAP_NO_OOB_DW | CAP_UR_NO_TRAP;
	if (p->shared_flags & F_HOSTRDY) {
		cap |= CAP_HOSTRDY;
	}
	p->host_cap = cap;
	p->host_cap2 = CAP2_BAD_RECOVERY;
	if (b4_tcm_wr(p, p->shared_addr + S_HOST_CAP, p->host_cap) || b4_tcm_wr(p, p->shared_addr + S_HOST_CAP2, p->host_cap2)) {
		return (int)p->stop;
	}
	if (p->idx_host) {
		/* ring_info's four host addresses, in that order: H2D write, H2D read, D2H write, D2H read */
		for (unsigned i = 0; i < 4; i++) {
			if (b4_tcm_wr(p, p->rings_info + RI_HOST_ADDRS + i * 8, (uint32_t)p->idx_pa[i]) || b4_tcm_wr(p, p->rings_info + RI_HOST_ADDRS + i * 8 + 4, (uint32_t)(p->idx_pa[i] >> 32))) {
				return (int)p->stop;
			}
		}
	}
	for (unsigned i = 0; i < B4_COMMON_RINGS; i++) {
		if (ring_init(p, i)) {
			return (int)p->stop;
		}
	}
	if (b4_tcm_wr(p, p->shared_addr + S_SCRATCH, (uint32_t)p->scratch_pa) || b4_tcm_wr(p, p->shared_addr + S_SCRATCH + 4, (uint32_t)(p->scratch_pa >> 32)) || b4_tcm_wr(p, p->shared_addr + S_SCRATCH_LEN, SCRATCH_BYTES)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "ring: host_cap 0x%x, host_cap2 0x%x, rings set. Next: host ready\n", p->host_cap, p->host_cap2);
	if (p->shared_flags & F_HOSTRDY) {
		if (ring_db(p, P_DB1, HOST_READY)) {
			return (int)p->stop;
		}
		p->hostready_sent = true;
	}
	/* dhd_msgbuf_rxbuf_post_ioctlresp_bufs, _event_bufs */
	for (uint32_t i = 0; i < RESP_BUFS; i++) {
		if (post_resp(p, i)) {
			return (int)p->stop;
		}
		p->resp_posted++;
	}
	for (uint32_t i = 0; i < EVENT_BUFS; i++) {
		if (post_event(p, i)) {
			return (int)p->stop;
		}
		p->events_posted++;
	}
	p->ops.log(p->ops.ctx, "ring: %u ioctl buffers, %u event buffers posted. Control ring write index %u\n", p->resp_posted, p->events_posted, p->ring[B4_H2D_CTRL].wr);
	if (first_ioctls(p) || (p->cfg.stage >= P1_STAGE_SCAN && b4_scan(p))) {
		return (int)p->stop;
	}
	/* What it does next, for the log */
	for (uint32_t ms = 0; ms < SETTLE_MS; ms += POLL_MS) {
		if (b4_poll(p)) {
			return (int)p->stop;
		}
		p->ops.delay_us(p->ops.ctx, POLL_MS * 1000);
	}
	p->ops.log(p->ops.ctx, "ring: settled. Events %u, other items %u\n", p->events_seen, p->other_seen);
	return 0;
}

int
b4_rings(struct p1 *p)
{
	int rc = rings_run(p);

	/* Success or not, what the chip's registers and console say, while it's still on */
	b4_diag(p);
	return rc;
}

#endif /* BLAZER */
