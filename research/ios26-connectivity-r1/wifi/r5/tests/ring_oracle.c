/* SPDX-License-Identifier: MIT
 * HOST ONLY. W1 r5: the RX buffer supply. Includes the real r5 blazer_bcm4390_ring.c, so carve_all(), post_rx(), h2d_commit(), poll_ring(),
 * on_rx_item(), b4_rx_post_all() and b4_rx_witness() run unchanged against a fake chip RAM and a fake doorbell. No phone, QEMU or secret.
 *
 * What it pins (r5/FIX.md section 3):
 *   - the host memory fits: carve_all at stage JOIN uses less than B4_DMA_NEEDED, which is blazer_wifi.c's WIFI_DMA_BYTES (run.sh greps that);
 *     r4's 384 KiB is now refused (NO_DMA) instead of silently carving less;
 *   - b4_rx_post_all posts min(1024, max_host_rxbufs): 1024 for this firmware's 6783, fewer if the shared area asks for fewer, 1024 if it says 0;
 *   - every post is a valid host_rxbuf_post_t for pciedev_process_rxpost_msg: type 0x11, phase/epoch, unique id 0x400.., length 2048 (>= 0x7f8,
 *     below which that function halts the firmware), an address inside the RX area, no metadata; the ring never fills (depth 1088);
 *   - the H2D write index (host array, slot 1) and the doorbell (0xff000000 | 1 << 16 | wr) follow every post;
 *   - an RX completion gives its buffer back at once (repost of the same id), past index 1024 without RING_FULL;
 *   - the witness line carries the firmware's EL 30 b8c8 drop count.
 *
 *   ring_oracle      exit 0: every case passed */
#define _POSIX_C_SOURCE 200112L
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "blazer_bcm4390_ring.c"

static uint32_t *tcm;           /* RAM_BASE..RAM_END */
static uint32_t db_last, db_n, db_rxpost_n;
static char logbuf[1 << 16];
static size_t loglen;
static unsigned fails;

#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %s:%d: ", __func__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

int b4_tcm_rd(struct p1 *p, uint32_t a, uint32_t *v) { (void)p; if (a < RAM_BASE || a + 4 > RAM_END) abort(); *v = tcm[(a - RAM_BASE) / 4]; return 0; }
int b4_tcm_wr(struct p1 *p, uint32_t a, uint32_t v) { (void)p; if (a < RAM_BASE || a + 4 > RAM_END) abort(); tcm[(a - RAM_BASE) / 4] = v; return 0; }
int b4_tcm_wr16(struct p1 *p, uint32_t a, uint16_t v) { (void)p; if (a < RAM_BASE || a + 2 > RAM_END) abort(); memcpy((uint8_t *)tcm + (a - RAM_BASE), &v, 2); return 0; }
int p1_wr(struct p1 *p, uint64_t pa, uint32_t v)
{
	(void)p;
	if (pa == BAR0_PCIE + P_DB0) {
		db_last = v;
		db_n++;
		if ((v & 0xffff0000u) == (DB_WR_MAGIC | (uint32_t)B4_H2D_RXPOST << 16)) {
			db_rxpost_n++;
		}
		return 0;
	}
	abort();
}
int p1_rmw(struct p1 *p, uint64_t pa, uint32_t c, uint32_t s) { (void)p; (void)pa; (void)c; (void)s; abort(); }
int p1_halt(struct p1 *p, uint32_t code, uint32_t detail) { p->stop = code; p->stop_detail = detail; return (int)code; }
int b4_power(struct p1 *p, bool on) { (void)p; (void)on; abort(); }
int b4_scan(struct p1 *p) { (void)p; abort(); }
int b4_console(struct p1 *p) { (void)p; return 0; }
void b4_diag(struct p1 *p) { (void)p; }
void b4_on_event(struct p1 *p, const uint8_t *b, uint32_t n) { (void)p; (void)b; (void)n; abort(); }
void b4_net_rx(struct p1 *p, const uint8_t *b, uint32_t n) { (void)p; (void)b; (void)n; abort(); }
void b4_on_flow_created(struct p1 *p, int32_t s, uint32_t f) { (void)p; (void)s; (void)f; abort(); }
bool b4_ioctl_allowed(uint32_t cmd, const uint8_t *buf, uint32_t len, int level) { (void)cmd; (void)buf; (void)len; (void)level; abort(); }
int b4_gate_level(const struct p1 *p) { (void)p; abort(); }

static void
logf_(void *ctx, const char *fmt, ...)
{
	va_list ap;

	(void)ctx;
	va_start(ap, fmt);
	if (loglen < sizeof(logbuf)) {
		int n = vsnprintf(logbuf + loglen, sizeof(logbuf) - loglen, fmt, ap);

		if (n > 0) {
			loglen += (size_t)n < sizeof(logbuf) - loglen ? (size_t)n : sizeof(logbuf) - loglen - 1;
		}
	}
	va_end(ap);
}
static void sync_(void *ctx, void *va, uint32_t n) { (void)ctx; (void)va; (void)n; }

static struct p1 *
fresh(uint32_t dma_bytes, uint32_t max_rxbufs)
{
	struct p1 *p = calloc(1, sizeof(*p));
	void *va = NULL;

	if (posix_memalign(&va, 4096, dma_bytes)) {
		abort();
	}
	memset(tcm, 0, RAM_END - RAM_BASE);
	db_last = db_n = db_rxpost_n = 0;
	loglen = 0;
	logbuf[0] = 0;
	p->ops.log = logf_;
	p->ops.dma_sync = sync_;
	p->cfg.stage = P1_STAGE_JOIN;
	p->cfg.dma.va = va;
	p->cfg.dma.pa = 0x889d90000ull;
	p->cfg.dma.bytes = dma_bytes;
	p->max_submission = 43;         /* physical: "Flow rings 40, submission 43, completion 4" */
	p->max_completion = 4;
	p->h2d_w = 0x549400;            /* physical r3 ring info */
	p->h2d_r = 0x5494c0;
	p->d2h_w = 0x549580;
	p->d2h_r = 0x5495c0;
	p->idx_host = true;
	p->max_rxbufs = max_rxbufs;
	return p;
}

static void
case_memory(void)
{
	struct p1 *p = fresh(B4_DMA_NEEDED, 6783);

	CHECK(carve_all(p) == 0, "carve_all at 2.5 MiB: stop %u detail 0x%x", p->stop, p->stop_detail);
	CHECK(p->dma_used <= B4_DMA_NEEDED, "used 0x%x", p->dma_used);
	CHECK(p->ring[B4_H2D_RXPOST].depth == RX_BUFS + 64 && p->ring[B4_D2H_RX].depth == 1024, "depths %u %u", p->ring[B4_H2D_RXPOST].depth, p->ring[B4_D2H_RX].depth);
	CHECK(p->rx_buf != NULL && p->rx_pa + (uint64_t)RX_BUFS * RX_BUF_BYTES <= p->cfg.dma.pa + p->cfg.dma.bytes, "rx area");
	printf("memory: stage JOIN carves 0x%x of 0x%x bytes; RX area %u x %u at +0x%llx\n", p->dma_used, B4_DMA_NEEDED, RX_BUFS, RX_BUF_BYTES,
	    (unsigned long long)(p->rx_pa - p->cfg.dma.pa));
	p = fresh(0x60000, 6783);
	CHECK(carve_all(p) == (int)P1_STOP_NO_DMA, "r4's 384 KiB must be refused, got stop %u", p->stop);
}

static void
case_post(uint32_t max_rxbufs, uint32_t want)
{
	struct p1 *p = fresh(B4_DMA_NEEDED, max_rxbufs);
	struct b4_ring *r;
	uint32_t idx;

	CHECK(carve_all(p) == 0, "carve");
	CHECK(b4_rx_bufs_wanted(p) == want, "wanted %u, want %u", b4_rx_bufs_wanted(p), want);
	CHECK(b4_rx_post_all(p) == 0, "post: stop %u detail 0x%x", p->stop, p->stop_detail);
	r = &p->ring[B4_H2D_RXPOST];
	CHECK(p->rx_posted == want, "rx_posted %u", p->rx_posted);
	CHECK(r->wr == want, "ring wr %u", r->wr);
	memcpy(&idx, p->idx_arr[IDX_H2D_W] + B4_H2D_RXPOST * IDX_WORD, 4);
	CHECK(idx == want, "H2D write index in host memory %u", idx);
	CHECK(db_rxpost_n == want && db_last == (DB_WR_MAGIC | (uint32_t)B4_H2D_RXPOST << 16 | want), "doorbells %u, last 0x%x", db_rxpost_n, db_last);
	for (uint32_t i = 0; i < want; i++) {
		const uint8_t *s = r->va + i * r->item;
		uint64_t a = (uint64_t)get32(s, RX_POST_ADDR_AT) | (uint64_t)get32(s, RX_POST_ADDR_AT + 4) << 32;

		if (s[0] != MSG_RX_POST || get32(s, 4) != RX_ID_BASE + i || get16(s, RX_POST_LEN_AT) != RX_BUF_BYTES || get16(s, RX_POST_LEN_AT) < 0x7f8u ||
		    a != p->rx_pa + (uint64_t)i * RX_BUF_BYTES || get16(s, 8) != 0 || get32(s, 16) != 0 || get32(s, 20) != 0 || s[2] != 0 || s[3] != (uint8_t)((EPOCH_INIT + i) % EPOCH_MODULO)) {
			CHECK(0, "item %u: type 0x%x id 0x%x len %u addr 0x%llx phase %u epoch %u", i, s[0], get32(s, 4), get16(s, RX_POST_LEN_AT), (unsigned long long)a, s[2], s[3]);
			break;
		}
	}
	printf("post: max_host_rxbufs %u -> %u posted, %u doorbells, last 0x%08x\n", max_rxbufs, r->wr, db_rxpost_n, db_last);
}

static void
case_recycle_and_witness(void)
{
	struct p1 *p = fresh(B4_DMA_NEEDED, 6783);
	struct b4_ring *c;
	uint8_t *it;
	uint32_t x = 0, w = 1, rd = RX_BUFS;

	CHECK(carve_all(p) == 0 && b4_rx_post_all(p) == 0, "setup");
	/* The dongle has fetched all of them, then completes buffer 5 */
	memcpy(p->idx_arr[IDX_H2D_R] + B4_H2D_RXPOST * IDX_WORD, &rd, 4);
	c = &p->ring[B4_D2H_RX];
	it = c->va;
	it[0] = MSG_RX_CMPLT;
	it[3] = (uint8_t)(c->seq % EPOCH_MODULO);
	put32(it, 4, RX_ID_BASE + 5);
	put16(it, RX_DATA_LEN_AT, 120);
	for (uint32_t i = 0; i < c->item - 4; i += 4) {
		x ^= get32(it, i);
	}
	put32(it, c->item - 4, x);
	memcpy(p->idx_arr[IDX_D2H_W] + (B4_D2H_RX - B4_D2H_CTRL) * IDX_WORD, &w, 4);
	CHECK(poll_ring(p, B4_D2H_RX) == 0, "poll: stop %u detail 0x%x", p->stop, p->stop_detail);
	CHECK(p->rx_items == 1 && p->rx_bytes == 120, "items %u bytes %u", p->rx_items, p->rx_bytes);
	CHECK(p->ring[B4_H2D_RXPOST].wr == RX_BUFS + 1, "reposted past 1024: wr %u", p->ring[B4_H2D_RXPOST].wr);
	CHECK(get32(p->ring[B4_H2D_RXPOST].va + RX_BUFS * H2D_RXPOST_ITEM, 4) == RX_ID_BASE + 5, "the same buffer went back");
	p->fw_rx_nobuf = 4;
	CHECK(b4_rx_witness(p, "after method 1") == 0, "witness");
	CHECK(strstr(logbuf, "post ring written to 1025, the dongle has read to 1024 (some taken)") != NULL, "witness text: %s", logbuf);
	CHECK(strstr(logbuf, "Firmware drops for want of a host buffer (EL 30 b8c8): 4") != NULL, "witness drops: %s", logbuf);
	printf("recycle: completion of id 0x%x reposted at index %u; witness: %s", RX_ID_BASE + 5, RX_BUFS, strstr(logbuf, "rx: witness") ? strstr(logbuf, "rx: witness") : "?\n");
}

int
main(void)
{
	tcm = calloc(1, RAM_END - RAM_BASE);
	case_memory();
	case_post(6783, 1024);  /* this firmware, shared +0x22 0x1a7f (physical r3 dump), Android's "max_rxbufpost:6783" */
	case_post(100, 100);
	case_post(0, 1024);     /* no such field: stock's legacy path, here the plain 1024 */
	case_recycle_and_witness();
	printf(fails ? "ring_oracle: %u FAILED\n" : "ring_oracle: all cases passed\n", fails);
	return fails != 0;
}
