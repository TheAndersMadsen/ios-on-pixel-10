#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * Rung 1 of AoC bring-up: ask the GSA's AoC hardware manager, through Trusty, what state AoC is in. Nothing more.
 * Off unless boot-arg blazer_aoc=1. Runs once from a thread, at cpus=1 only, and ends the boot with a panic naming the result,
 * so the ring holds every line: needs blazer_panic=1 for the reset. No LOAD, no START, no carve-out, no AoC register, no rail.
 * The only hwmgr message this file can send is GET_STATE {1,0}, and aoc_smc refuses any SMC function not on its list.
 *
 * Trusty's build is the first thing asked and the first line logged.
 *
 * Protocol facts: GrapheneOS kernel_pixel_6.12 @5940a317, google-modules/trusty and soc/gs gsa (GPL-2.0, facts only, no code copied).
 * smcall.h is MIT. Polled client, one bound CPU, shared pages never reclaimed: method as ios-tegu's record on Tensor G4.
 * On this phone only GET_VERSION_STR has been sent (20261101-205756-touch-r1); everything after it here is new. */
#ifndef BLAZER_AOC_HOSTTEST
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>

extern void IOSleep(unsigned milliseconds);
extern void *IOMallocAligned(vm_size_t size, vm_offset_t alignment);
extern uint64_t kvtophys(vm_offset_t va);
#ifndef AOC_LOG
#define AOC_LOG(...) printf("HK AOC: " __VA_ARGS__)
#endif
#endif

#ifndef BLAZER_AOC_TRANSPORT
void blazer_aoc_start(void);
#endif

/* smcall.h */
#define AOC_SC_RESTART_LAST   0x3c000000u
#define AOC_SC_RESTART_FIQ    0x3c000002u
#define AOC_SC_NOP            0x3c000003u
#define AOC_FC_GET_VERSION    0xbc00000au
#define AOC_FC_API_VERSION    0xbc00000bu
#define AOC_SC_VIRTIO_DESCR   0x32000014u
#define AOC_SC_VIRTIO_START   0x32000015u
#define AOC_SC_VDEV_RESET     0x32000017u
#define AOC_NC_VDEV_KICK_VQ   0x32000019u
/* arm_ffa.h */
#define AOC_FFA_ERROR         0x84000060u
#define AOC_FFA_SUCCESS       0x84000061u
#define AOC_FFA_VERSION       0x84000063u
#define AOC_FFA_FEATURES      0x84000064u
#define AOC_FFA_RXTX_MAP64    0xc4000066u
#define AOC_FFA_RXTX_UNMAP    0x84000067u
#define AOC_FFA_ID_GET        0x84000069u
#define AOC_FFA_MEM_SHARE     0x84000073u
#define AOC_FFA_V1_0          0x10000u
#define AOC_FFA_V1_1          0x10001u
#define AOC_FFA_DENIED        (-6)
#define AOC_FFA_NORMAL_WB_IS  ((2u << 4) | (3u << 2) | 3u)
#define AOC_FFA_RO            1u
#define AOC_FFA_RW            2u
#define AOC_FFA_SECURE_OS     0x8000u
#define AOC_FFA_PAGE          4096u
/* sm_err.h */
#define AOC_ERR_UNDEFINED     (-1)
#define AOC_ERR_INTERRUPTED   (-3)
#define AOC_ERR_BUSY          (-5)
#define AOC_ERR_PANIC         (-11)
#define AOC_ERR_FIQ           (-12)
#define AOC_ERR_CPU_IDLE      (-13)
#define AOC_ERR_NOP_INTR      (-14)
#define AOC_ERR_NOP_DONE      (-15)

#define AOC_API_WANT          5
#define AOC_PAGE              16384u    /* XNU's page. Every shared buffer has its own */
#define AOC_RX_BUFS           8u
#define AOC_TX_BUFS           2u
#define AOC_VDEV_IPC          13u       /* VIRTIO_ID_TRUSTY_IPC */
#define AOC_RSC_VDEV          3u
#define AOC_LOCAL_ADDR        1024u
#define AOC_CTRL_ADDR         53u       /* TIPC_CTRL_ADDR */
#define AOC_CTRL_ONLINE       1u
#define AOC_CTRL_OFFLINE      2u
#define AOC_CTRL_CONN_REQ     3u
#define AOC_CTRL_CONN_RSP     4u
#define AOC_CTRL_DISC_REQ     5u
#ifndef AOC_PORT
#define AOC_PORT              "com.android.trusty.gsa.hwmgr.aoc"
#define AOC_PORT_REFUSED      "hwmgr port refused"
#endif
#define AOC_HWMGR_STATE_CMD   1u
#define AOC_HWMGR_RESP        0x80000000u
#define AOC_STATE_GET         0u
#define AOC_RETRY_MAX         200000u
#define AOC_ONLINE_MS         3000u
#define AOC_CONNECT_MS        5000u
#define AOC_REPLY_MS          5000u
#define AOC_POLL_MS           2u

struct aoc_vq {
	uint8_t *base;
	volatile uint8_t *avail, *used;
	uint32_t num, align, notifyid;
	uint16_t avail_idx, last_used;
};

static struct {
	uint32_t ffa_ver;
	uint16_t local_id;
	uint8_t *tx, *rx, *descr;
	uint64_t descr_handle;
	uint32_t descr_size, vdev_off, vdev_notify, msg_max;
	struct aoc_vq vq[2];            /* 0 rx, 1 tx */
	uint8_t *rxbuf[AOC_RX_BUFS], *txbuf[AOC_TX_BUFS];
	uint64_t rxh[AOC_RX_BUFS], txh[AOC_TX_BUFS];
	unsigned tx_next;
	uint32_t remote, conn_status, reply_len;
	bool online, conn_done, connected, reply_ready, dead;
	uint8_t reply[32];
	uint32_t smcs, nops;
} aoc;

/* A STOP is final: nothing more goes to the secure world in this boot. */
static const char *aoc_stop_reason;
static int
aoc_stop(const char *why)
{
	if (!aoc_stop_reason) {
		aoc_stop_reason = why;
		AOC_LOG("STOP %s (smcs %u nops %u)\n", why, aoc.smcs, aoc.nops);
	}
	aoc.dead = true;
	return -1;
}

#ifndef BLAZER_AOC_HOSTTEST
static void
aoc_smc8(uint64_t r[8])
{
	register uint64_t x0 __asm__("x0") = r[0];
	register uint64_t x1 __asm__("x1") = r[1];
	register uint64_t x2 __asm__("x2") = r[2];
	register uint64_t x3 __asm__("x3") = r[3];
	register uint64_t x4 __asm__("x4") = r[4];
	register uint64_t x5 __asm__("x5") = r[5];
	register uint64_t x6 __asm__("x6") = r[6];
	register uint64_t x7 __asm__("x7") = r[7];
	uint64_t daif;

	/* Interrupts masked across the call: a pending one makes Trusty return, and is taken after the restore. */
	__asm__ volatile ("mrs %[d], daif\n\tmsr daifset, #0xf\n\tdsb sy\n\tsmc #0\n\tmsr daif, %[d]"
	    : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7), [d] "=&r"(daif)
	    :
	    : "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory", "cc");
	r[0] = x0; r[1] = x1; r[2] = x2; r[3] = x3; r[4] = x4; r[5] = x5; r[6] = x6; r[7] = x7;
}

static uint64_t
aoc_now_ms(void)
{
	uint64_t ns;

	absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
	return ns / 1000000ULL;
}

static void *
aoc_page_alloc(uint32_t len)
{
	return IOMallocAligned(len, AOC_PAGE);
}

#define aoc_sleep_ms(ms) IOSleep(ms)
#define aoc_pa(va) kvtophys((vm_offset_t)(va))
#define aoc_barrier() __asm__ volatile ("dsb sy" : : : "memory")
#define aoc_dmb() __asm__ volatile ("dmb ish" : : : "memory")
#endif /* !BLAZER_AOC_HOSTTEST */

static bool
aoc_smc_allowed(uint32_t fn)
{
	switch (fn) {
	case AOC_SC_RESTART_LAST: case AOC_SC_RESTART_FIQ: case AOC_SC_NOP:
	case AOC_FC_GET_VERSION: case AOC_FC_API_VERSION:
	case AOC_SC_VIRTIO_DESCR: case AOC_SC_VIRTIO_START: case AOC_SC_VDEV_RESET:
	case AOC_FFA_VERSION: case AOC_FFA_FEATURES: case AOC_FFA_RXTX_MAP64: case AOC_FFA_RXTX_UNMAP:
	case AOC_FFA_ID_GET: case AOC_FFA_MEM_SHARE:
#ifdef AOC_SMC_EXTRA
	AOC_SMC_EXTRA
#endif
		return true;
	default:
		return false;
	}
}

static int
aoc_smc(uint64_t r[8])
{
	if (aoc.dead) {
		return -1;
	}
	if (!aoc_smc_allowed((uint32_t)r[0])) {
		return aoc_stop("function not on the list");
	}
	aoc.smcs++;
	aoc_smc8(r);
	return 0;
}

static int32_t
aoc_call32(uint32_t fn, uint32_t a0, uint32_t a1, uint32_t a2)
{
	uint64_t r[8] = { fn, a0, a1, a2, 0, 0, 0, 0 };

	if (aoc_smc(r)) {
		return AOC_ERR_PANIC;
	}
	return (int32_t)(uint32_t)r[0];
}

/* Std call, with the returns trusty.c handles. Bounded: running out is a STOP. */
static int32_t
aoc_std(uint32_t fn, uint32_t a0, uint32_t a1, uint32_t a2)
{
	int32_t ret = aoc_call32(fn, a0, a1, a2);
	unsigned tries = 0;

	for (;;) {
		if (aoc.dead) {
			return AOC_ERR_PANIC;
		}
		if (ret == AOC_ERR_PANIC) {
			aoc_stop("SM_ERR_PANIC, secure OS crashed");
			return ret;
		}
		if (++tries > AOC_RETRY_MAX) {
			aoc_stop("std call never finished");
			return AOC_ERR_PANIC;
		}
		if (ret == AOC_ERR_FIQ) {
			ret = aoc_call32(AOC_SC_RESTART_FIQ, 0, 0, 0);
		} else if (ret == AOC_ERR_INTERRUPTED) {
			ret = aoc_call32(AOC_SC_RESTART_LAST, 0, 0, 0);
		} else if (ret == AOC_ERR_CPU_IDLE) {
			aoc_sleep_ms(1);
			ret = aoc_call32(AOC_SC_RESTART_LAST, 0, 0, 0);
		} else if (ret == AOC_ERR_BUSY) {
			aoc_sleep_ms(1);
			ret = aoc_call32(fn, a0, a1, a2);
		} else {
			return ret;
		}
	}
}

static int32_t
aoc_nop(uint32_t a0, uint32_t a1, uint32_t a2)
{
	int32_t ret;
	unsigned n = 0;

	aoc.nops++;
	do {
		ret = aoc_std(AOC_SC_NOP, a0, a1, a2);
	} while (ret == AOC_ERR_NOP_INTR && ++n < 10000);
	return ret;
}

static void aoc_p16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void aoc_p32(uint8_t *p, uint32_t v) { for (unsigned i = 0; i < 4; i++) { p[i] = (uint8_t)(v >> (8 * i)); } }
static void aoc_p64(uint8_t *p, uint64_t v) { for (unsigned i = 0; i < 8; i++) { p[i] = (uint8_t)(v >> (8 * i)); } }
static uint16_t aoc_g16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t aoc_g32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }

static uint8_t *
aoc_page(uint32_t len)
{
	uint8_t *p;

	len = (len + AOC_PAGE - 1) & ~(AOC_PAGE - 1);
	p = aoc_page_alloc(len);
	if (p) {
		memset(p, 0, len);
	}
	return p;
}

/* Share whole pages, FF-A 1.0 or 1.1 layout as negotiated, one descriptor per contiguous run. Never reclaimed. */
static int
aoc_share(void *va, uint32_t len, uint8_t perm, uint64_t *handle)
{
	uint8_t *m = aoc.tx;
	const bool v11 = aoc.ffa_ver >= AOC_FFA_V1_1;
	const uint32_t emad = v11 ? 48u : 32u, comp = emad + 16u, cons = comp + 16u;
	uint32_t ranges = 0, run_pages = 0, total;
	uint64_t run_pa = 0;
	uint64_t r[8] = { 0 };

	memset(m, 0, AOC_FFA_PAGE);
	for (uint32_t off = 0; off < len; off += AOC_FFA_PAGE) {
		uint64_t pa = aoc_pa((uint8_t *)va + off);

		if (!pa) {
			return aoc_stop("no physical address for a shared page");
		}
		if (run_pages && pa == run_pa + (uint64_t)run_pages * AOC_FFA_PAGE) {
			run_pages++;
			continue;
		}
		if (run_pages) {
			aoc_p64(m + cons + ranges * 16, run_pa);
			aoc_p32(m + cons + ranges * 16 + 8, run_pages);
			ranges++;
		}
		run_pa = pa;
		run_pages = 1;
	}
	aoc_p64(m + cons + ranges * 16, run_pa);
	aoc_p32(m + cons + ranges * 16 + 8, run_pages);
	ranges++;
	aoc_p16(m + 0, aoc.local_id);
	if (v11) {
		aoc_p16(m + 2, AOC_FFA_NORMAL_WB_IS);
		aoc_p32(m + 24, 16);            /* emad_size */
		aoc_p32(m + 28, 1);             /* emad_count */
		aoc_p32(m + 32, emad);          /* emad_offset */
	} else {
		m[2] = AOC_FFA_NORMAL_WB_IS;
		aoc_p32(m + 28, 1);
	}
	aoc_p16(m + emad, AOC_FFA_SECURE_OS);
	m[emad + 2] = perm;
	aoc_p32(m + emad + 4, comp);
	aoc_p32(m + comp, len / AOC_FFA_PAGE);
	aoc_p32(m + comp + 4, ranges);
	total = cons + ranges * 16;
	aoc_barrier();
	r[0] = AOC_FFA_MEM_SHARE; r[1] = total; r[2] = total;
	if (aoc_smc(r)) {
		return -1;
	}
	if ((uint32_t)r[0] != AOC_FFA_SUCCESS) {
		AOC_LOG("MEM_SHARE %u bytes -> 0x%llx 0x%llx 0x%llx\n", len, r[0], r[1], r[2]);
		return aoc_stop("FFA_MEM_SHARE refused");
	}
	*handle = (r[2] & 0xffffffffULL) | (r[3] << 32);
	return 0;
}

static void
aoc_vq_kick(unsigned q)
{
	int32_t ret = aoc_nop(AOC_NC_VDEV_KICK_VQ, aoc.vdev_notify, aoc.vq[q].notifyid);

	if (ret != AOC_ERR_NOP_DONE && ret != 0 && !aoc.dead) {
		AOC_LOG("kick vq %u -> %d\n", q, ret);
	}
}

static void
aoc_vq_add(unsigned q, uint16_t desc, uint64_t handle, uint32_t len, uint16_t flags)
{
	struct aoc_vq *v = &aoc.vq[q];
	uint8_t *d = v->base + (uint32_t)desc * 16;

	aoc_p64(d, handle);
	aoc_p32(d + 8, len);
	aoc_p16(d + 12, flags);
	aoc_p16(d + 14, 0);
	((volatile uint16_t *)(v->avail + 4))[v->avail_idx % v->num] = desc;
	aoc_dmb();
	v->avail_idx++;
	*(volatile uint16_t *)(v->avail + 2) = v->avail_idx;
	aoc_barrier();
}

static void
aoc_rx_msg(const uint8_t *b, uint32_t len)
{
	uint32_t dst, mlen;
	const uint8_t *d = b + 16;

	if (len < 16) {
		return;
	}
	dst = aoc_g32(b + 4);
	mlen = aoc_g16(b + 12);
	if (mlen + 16 != len) {
		AOC_LOG("rx length %u, header says %u: dropped\n", len, mlen + 16);
		return;
	}
	if (dst == AOC_CTRL_ADDR) {
		uint32_t type, body;

		if (mlen < 8) {
			return;
		}
		type = aoc_g32(d);
		body = aoc_g32(d + 4);
		if (type == AOC_CTRL_ONLINE) {
			aoc.online = true;
			AOC_LOG("tipc online\n");
		} else if (type == AOC_CTRL_OFFLINE) {
			aoc.online = false;
			AOC_LOG("tipc offline\n");
		} else if (type == AOC_CTRL_CONN_RSP && body >= 20 && mlen >= 28) {
			aoc.conn_status = aoc_g32(d + 12);
			aoc.remote = aoc_g32(d + 16);
			aoc.conn_done = aoc_g32(d + 8) == AOC_LOCAL_ADDR;
			aoc.connected = aoc.conn_done && aoc.conn_status == 0;
			AOC_LOG("conn_rsp status %u remote %u max_size %u\n", aoc.conn_status, aoc.remote, aoc_g32(d + 20));
		} else if (type == AOC_CTRL_DISC_REQ) {
			aoc.connected = false;
			AOC_LOG("disconnected by Trusty\n");
		} else {
			AOC_LOG("ctrl type %u ignored\n", type);
		}
	} else if (dst == AOC_LOCAL_ADDR && aoc.connected) {
		aoc.reply_len = mlen;
		memcpy(aoc.reply, d, mlen < sizeof(aoc.reply) ? mlen : sizeof(aoc.reply));
		aoc.reply_ready = true;
	} else {
		AOC_LOG("message to %u dropped\n", dst);
	}
}

static void
aoc_poll(void)
{
	struct aoc_vq *rx = &aoc.vq[0], *tx = &aoc.vq[1];
	unsigned n = 0;

	aoc_dmb();
	while (rx->last_used != *(volatile uint16_t *)(rx->used + 2) && n < 64) {
		volatile uint8_t *e;
		uint32_t id, len;

		aoc_dmb();
		e = rx->used + 4 + (uint32_t)(rx->last_used % rx->num) * 8;
		id = *(volatile uint32_t *)e;
		len = *(volatile uint32_t *)(e + 4);
		rx->last_used++;
		n++;
		if (id >= AOC_RX_BUFS || len > aoc.msg_max) {
			aoc_stop("bad rx used entry");
			return;
		}
		aoc_rx_msg(aoc.rxbuf[id], len);
		aoc_vq_add(0, (uint16_t)id, aoc.rxh[id], aoc.msg_max, 2 /* VRING_DESC_F_WRITE */);
	}
	if (n) {
		aoc_vq_kick(0);
	}
	tx->last_used = *(volatile uint16_t *)(tx->used + 2);
}

/* Trusty only runs when called: NOPs give it the CPU. */
static bool
aoc_wait(volatile bool *flag, unsigned ms)
{
	const uint64_t end = aoc_now_ms() + ms;

	for (;;) {
		aoc_poll();
		if (*flag || aoc.dead) {
			return *flag;
		}
		if (aoc_now_ms() >= end) {
			return false;
		}
		(void)aoc_nop(0, 0, 0);
		aoc_poll();
		if (*flag || aoc.dead) {
			return *flag;
		}
		aoc_sleep_ms(AOC_POLL_MS);
	}
}

static int
aoc_send(uint32_t dst, const void *data, uint32_t len)
{
	struct aoc_vq *tx = &aoc.vq[1];
	unsigned t;
	uint8_t *b;

	if (len + 16 > aoc.msg_max) {
		return aoc_stop("message too long");
	}
	if ((uint16_t)(tx->avail_idx - tx->last_used) >= AOC_TX_BUFS) {
		return aoc_stop("tx ring stuck");
	}
	t = aoc.tx_next++ % AOC_TX_BUFS;
	b = aoc.txbuf[t];
	aoc_p32(b, AOC_LOCAL_ADDR);
	aoc_p32(b + 4, dst);
	aoc_p32(b + 8, 0);
	aoc_p16(b + 12, (uint16_t)len);
	aoc_p16(b + 14, 0);
	memcpy(b + 16, data, len);
	aoc_vq_add(1, (uint16_t)t, aoc.txh[t], len + 16, 0);
	aoc_vq_kick(1);
	return aoc.dead ? -1 : 0;
}

/* Fast calls only. Build first. */
static int
aoc_identify(void)
{
	char build[161];
	unsigned n = 0;
	int32_t len = aoc_call32(AOC_FC_GET_VERSION, 0xffffffffu, 0, 0), api;
	uint64_t r[8] = { AOC_FFA_VERSION, AOC_FFA_V1_1, 0, 0, 0, 0, 0, 0 };
	uint64_t f[8] = { AOC_FFA_FEATURES, AOC_FFA_MEM_SHARE, 0, 0, 0, 0, 0, 0 };
	uint64_t id[8] = { AOC_FFA_ID_GET, 0, 0, 0, 0, 0, 0, 0 };

	for (int32_t i = 0; len > 0 && i < len && n < sizeof(build) - 1; i++) {
		int32_t c = aoc_call32(AOC_FC_GET_VERSION, (uint32_t)i, 0, 0);

		if (c < 0) {
			break;
		}
		build[n++] = (c >= 32 && c < 127) ? (char)c : '?';
	}
	build[n] = 0;
	AOC_LOG("trusty build '%s' len %d\n", build, len);
	if (len <= 0) {
		return aoc_stop("Trusty gives no version");
	}
	api = aoc_call32(AOC_FC_API_VERSION, AOC_API_WANT, 0, 0);
	if (aoc_smc(r) || aoc_smc(f) || aoc_smc(id)) {
		return -1;
	}
	aoc.ffa_ver = (uint32_t)r[0];
	aoc.local_id = (uint16_t)id[2];
	AOC_LOG("api %d ffa 0x%x mem_share 0x%llx id_get 0x%llx local %u\n", api, aoc.ffa_ver, f[0], id[0], aoc.local_id);
	if (api != AOC_API_WANT) {
		return aoc_stop("Trusty API is not 5");
	}
	if ((aoc.ffa_ver >> 16) != 1 || (uint32_t)f[0] != AOC_FFA_SUCCESS || (uint32_t)id[0] != AOC_FFA_SUCCESS) {
		return aoc_stop("FF-A unusable");
	}
	if (aoc.ffa_ver > AOC_FFA_V1_1) {
		aoc.ffa_ver = AOC_FFA_V1_1;
	}
	return 0;
}

static int
aoc_rxtx_map(void)
{
	uint64_t r[8] = { AOC_FFA_RXTX_MAP64, aoc_pa(aoc.tx), aoc_pa(aoc.rx), 1, 0, 0, 0, 0 };

	if (aoc_smc(r)) {
		return -1;
	}
	if ((uint32_t)r[0] == AOC_FFA_ERROR && (int32_t)(uint32_t)r[2] == AOC_FFA_DENIED) {
		/* The bootloader may have left its own mailboxes mapped. */
		uint64_t u[8] = { AOC_FFA_RXTX_UNMAP, (uint64_t)aoc.local_id << 16, 0, 0, 0, 0, 0, 0 };

		if (aoc_smc(u)) {
			return -1;
		}
		AOC_LOG("rxtx was mapped: unmap -> 0x%llx\n", u[0]);
		r[0] = AOC_FFA_RXTX_MAP64; r[1] = aoc_pa(aoc.tx); r[2] = aoc_pa(aoc.rx); r[3] = 1;
		r[4] = r[5] = r[6] = r[7] = 0;
		if (aoc_smc(r)) {
			return -1;
		}
	}
	AOC_LOG("rxtx_map -> 0x%llx 0x%llx\n", r[0], r[2]);
	return (uint32_t)r[0] == AOC_FFA_SUCCESS ? 0 : aoc_stop("FFA_RXTX_MAP refused");
}

static int
aoc_parse_descr(void)
{
	const uint8_t *d = aoc.descr;
	uint32_t num;
	uint8_t *vd;

	if (aoc_g32(d) != 1 || (num = aoc_g32(d + 4)) > 16 || 16 + num * 4 > aoc.descr_size) {
		return aoc_stop("resource table refused");
	}
	for (uint32_t i = 0; i < num; i++) {
		uint32_t off = aoc_g32(d + 16 + i * 4);

		if (off + 4 + 24 + 2 * 20 > aoc.descr_size) {
			continue;
		}
		if (aoc_g32(d + off) == AOC_RSC_VDEV && aoc_g32(d + off + 4) == AOC_VDEV_IPC && d[off + 4 + 21] == 2 &&
		    off + 4 + 24 + 2 * 20 + aoc_g32(d + off + 4 + 16) <= aoc.descr_size) {
			aoc.vdev_off = off + 4;
		}
	}
	if (!aoc.vdev_off) {
		return aoc_stop("no trusty-ipc vdev");
	}
	vd = aoc.descr + aoc.vdev_off;
	aoc.vdev_notify = aoc_g32(vd + 4);
	aoc.msg_max = aoc_g32(vd + 16) >= 8 ? aoc_g32(vd + 24 + 2 * 20) : AOC_FFA_PAGE;
	AOC_LOG("vdev notify %u dfeatures 0x%x msg_max %u\n", aoc.vdev_notify, aoc_g32(vd + 8), aoc.msg_max);
	if (aoc.msg_max < 512 || aoc.msg_max > AOC_PAGE) {
		return aoc_stop("msg_max refused");
	}
	aoc_p32(vd + 12, 0);    /* gfeatures: the ipc driver asks for none */
	return 0;
}

static int
aoc_virtio_up(void)
{
	int32_t size, rs, st;
	uint8_t *vd;

	aoc.tx = aoc_page(AOC_FFA_PAGE);
	aoc.rx = aoc_page(AOC_FFA_PAGE);
	aoc.descr = aoc_page(AOC_FFA_PAGE);
	if (!aoc.tx || !aoc.rx || !aoc.descr) {
		return aoc_stop("no memory");
	}
	if (aoc_rxtx_map() || aoc_share(aoc.descr, AOC_PAGE, AOC_FFA_RW, &aoc.descr_handle)) {
		return -1;
	}
	size = aoc_std(AOC_SC_VIRTIO_DESCR, (uint32_t)aoc.descr_handle, (uint32_t)(aoc.descr_handle >> 32), AOC_PAGE);
	AOC_LOG("virtio descr handle 0x%llx -> %d\n", aoc.descr_handle, size);
	if (size < 16 || (uint32_t)size > AOC_PAGE) {
		return aoc_stop("VIRTIO_GET_DESCR failed");
	}
	aoc.descr_size = (uint32_t)size;
	if (aoc_parse_descr()) {
		return -1;
	}
	vd = aoc.descr + aoc.vdev_off;
	for (unsigned q = 0; q < 2; q++) {
		uint8_t *vr = vd + 24 + q * 20;
		struct aoc_vq *v = &aoc.vq[q];
		uint32_t used_off, bytes;
		uint64_t handle;

		v->align = aoc_g32(vr + 4);
		v->num = aoc_g32(vr + 8);
		v->notifyid = aoc_g32(vr + 12);
		if (!v->num || v->num > 1024 || (v->num & (v->num - 1)) || !v->align || (v->align & (v->align - 1)) || v->align > AOC_PAGE) {
			return aoc_stop("vring refused");
		}
		used_off = (v->num * 16 + 2 * (3 + v->num) + v->align - 1) & ~(v->align - 1);
		bytes = (used_off + 6 + 8 * v->num + AOC_PAGE - 1) & ~(AOC_PAGE - 1);
		v->base = aoc_page(bytes);
		if (!v->base) {
			return aoc_stop("no memory");
		}
		v->avail = v->base + v->num * 16;
		v->used = v->base + used_off;
		if (aoc_share(v->base, bytes, AOC_FFA_RW, &handle)) {
			return -1;
		}
		aoc_p32(vr + 0, (uint32_t)handle);
		aoc_p32(vr + 16, (uint32_t)(handle >> 32));
		AOC_LOG("vring %u num %u align %u notify %u handle 0x%llx\n", q, v->num, v->align, v->notifyid, handle);
	}
	if (aoc.vq[0].num < AOC_RX_BUFS) {
		return aoc_stop("rx ring too small");
	}
	for (unsigned i = 0; i < AOC_RX_BUFS; i++) {
		aoc.rxbuf[i] = aoc_page(AOC_PAGE);
		if (!aoc.rxbuf[i] || aoc_share(aoc.rxbuf[i], AOC_PAGE, AOC_FFA_RW, &aoc.rxh[i])) {
			return aoc_stop("rx buffer");
		}
		aoc_vq_add(0, (uint16_t)i, aoc.rxh[i], aoc.msg_max, 2);
	}
	for (unsigned i = 0; i < AOC_TX_BUFS; i++) {
		aoc.txbuf[i] = aoc_page(AOC_PAGE);
		if (!aoc.txbuf[i] || aoc_share(aoc.txbuf[i], AOC_PAGE, AOC_FFA_RO, &aoc.txh[i])) {
			return aoc_stop("tx buffer");
		}
	}
	rs = aoc_std(AOC_SC_VDEV_RESET, aoc.vdev_notify, 0, 0);
	vd[20] = 7;     /* ACKNOWLEDGE | DRIVER | DRIVER_OK */
	aoc_barrier();
	st = aoc_std(AOC_SC_VIRTIO_START, (uint32_t)aoc.descr_handle, (uint32_t)(aoc.descr_handle >> 32), aoc.descr_size);
	AOC_LOG("vdev reset -> %d, virtio start -> %d\n", rs, st);
	if (st != 0) {
		return aoc_stop("VIRTIO_START failed");
	}
	if (!aoc_wait(&aoc.online, AOC_ONLINE_MS)) {
		return aoc_stop("no tipc online in 3 s");
	}
	return 0;
}

static int
aoc_connect(void)
{
	static uint8_t m[8 + 256];

	memset(m, 0, sizeof(m));
	aoc_p32(m, AOC_CTRL_CONN_REQ);
	aoc_p32(m + 4, 256);
	memcpy(m + 8, AOC_PORT, sizeof(AOC_PORT));
	if (aoc_send(AOC_CTRL_ADDR, m, sizeof(m))) {
		return -1;
	}
	if (!aoc_wait(&aoc.conn_done, AOC_CONNECT_MS)) {
		return aoc_stop("no conn_rsp in 5 s");
	}
	return aoc.connected ? 0 : aoc_stop(AOC_PORT_REFUSED);
}

/* blazer_gpu_tipc.c includes everything above as its transport, BLAZER_AOC_TRANSPORT. Below is AoC's own. */
#ifndef BLAZER_AOC_TRANSPORT
/* Returns the state, or negative after a STOP. Strict as gsa_core.c: exactly 12 bytes. */
static int
aoc_get_state(void)
{
	uint8_t req[8];
	const uint64_t t0 = aoc_now_ms();
	uint32_t cmd, err, state;

	aoc_p32(req, AOC_HWMGR_STATE_CMD);
	aoc_p32(req + 4, AOC_STATE_GET);
	if (aoc_send(aoc.remote, req, sizeof(req))) {
		return -1;
	}
	if (!aoc_wait(&aoc.reply_ready, AOC_REPLY_MS)) {
		return aoc_stop("no GET_STATE reply in 5 s");
	}
	cmd = aoc_g32(aoc.reply);
	err = aoc_g32(aoc.reply + 4);
	state = aoc_g32(aoc.reply + 8);
	AOC_LOG("GET_STATE len %u cmd 0x%x err %u state %u in %llu ms\n", aoc.reply_len, cmd, err, state, aoc_now_ms() - t0);
	if (aoc.reply_len != 12 || cmd != (AOC_HWMGR_STATE_CMD | AOC_HWMGR_RESP) || err != 0 || state > 2) {
		return aoc_stop("bad GET_STATE reply");
	}
	return (int)state;
}

/* 0 for rung 1's pass. */
static int
aoc_rung1(void)
{
	int state;

	if (aoc_identify() || aoc_virtio_up() || aoc_connect()) {
		return -1;
	}
	state = aoc_get_state();
	if (state < 0) {
		return -1;
	}
	if (state != 0) {
		AOC_LOG("state %d: AoC has a predecessor. Not inactive, no LOAD or START on this phone until it's explained\n", state);
		aoc_stop("state is not 0");
		return -1;
	}
	AOC_LOG("rung 1 PASS state 0 (smcs %u nops %u)\n", aoc.smcs, aoc.nops);
	return 0;
}

#ifndef BLAZER_AOC_HOSTTEST
__dead2 static void
aoc_thread(void *arg __unused, wait_result_t wr __unused)
{
	int rc = aoc_rung1();

	/* Let the ring take the last lines, then end the boot: with blazer_panic=1 this is the reset path, physical. */
	IOSleep(200);
	if (rc == 0) {
		panic("HK AOC: rung 1 PASS, boot ended on purpose");
	}
	panic("HK AOC: rung 1 STOP: %s", aoc_stop_reason ? aoc_stop_reason : "unknown");
}

void
blazer_aoc_start(void)
{
	unsigned on = 0, cpus = 0;
	thread_t thread;

	if (!PE_parse_boot_argn("blazer_aoc", &on, sizeof(on)) || on != 1) {
		return;
	}
	if (!PE_parse_boot_argn("cpus", &cpus, sizeof(cpus)) || cpus != 1) {
		/* A restart must come from the core that was interrupted. Binding is for a later rung. */
		printf("HK AOC: refused, needs cpus=1\n");
		return;
	}
	if (kernel_thread_start(aoc_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
		printf("HK AOC: rung 1 start\n");
	}
}
#endif /* !BLAZER_AOC_HOSTTEST */
#endif /* !BLAZER_AOC_TRANSPORT */
#endif /* BLAZER */
