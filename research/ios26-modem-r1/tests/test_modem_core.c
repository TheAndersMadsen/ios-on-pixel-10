/* Host test for blazer_modem_core.c: a fake Pixel (CPM mailbox, PCIe0, the pads, an S5400 that links only when powered
 * in stock's order and PERST is high). Runs the exact core logic. Build: research/ios26-modem-r1/tests/run.sh */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "blazer_modem_core.h"

static int fails, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---- the fake hardware ---- */
#define NREG 4096
static struct { uint64_t pa; uint32_t v; } regs[NREG];
static int nregs;
static uint32_t *reg(uint64_t pa)
{
	for (int i = 0; i < nregs; i++) if (regs[i].pa == pa) return &regs[i].v;
	if (nregs >= NREG) { printf("too many regs\n"); exit(2); }
	regs[nregs].pa = pa; regs[nregs].v = 0;
	return &regs[nregs++].v;
}

struct hw {
	uint32_t lpb[64];               /* LPB state by id */
	uint32_t lpcm_reply;            /* reply word 1 for LPCM frames */
	bool cp_answers;                /* the CP ROM trains when powered */
	uint32_t ep_id;
	uint32_t frames[64][3]; int nframes;
	bool pd_on, rst_init, rst_pu, rst_perst, rst_app;
	uint64_t now_us;
	int writes, pad_writes, cfg_writes, phy_writes, cp_mem_access;
	/* every pad TX write in order: pad index, new TX */
	int tx_log[256][2]; int ntx;
	char log[65536]; size_t loglen;
	bool locked; int lock_errors;
} H;

static uint64_t pad_pa(int i, uint32_t r) { return m0_pads[i].base + (uint64_t)m0_pads[i].pad * 0x1000u + r; }
static int pad_index(uint64_t pa)
{
	for (int i = 0; i < M0_PADS; i++) { uint64_t b = pad_pa(i, 0); if (pa >= b && pa < b + 0x14) return i; }
	return -1;
}
static bool pad_high(int i) { uint32_t tx = *reg(pad_pa(i, 8)); return (tx & 8u) && (tx & 4u); }
static bool cp_powered(void)
{
	return pad_high(M0_PAD_PM_WRST) && pad_high(M0_PAD_CP_PWR) && pad_high(M0_PAD_NRESET) && pad_high(M0_PAD_CP_WRST);
}
static bool linked(void)
{
	return H.cp_answers && cp_powered() && pad_high(M0_PAD_PERST) && (*reg(0x0c520014ULL) & 1u) && H.pd_on && H.rst_app &&
	       *reg(0x0c550000ULL) != 0 /* table in */ && (*reg(0x0c520000ULL) & (1u << 23));
}

static int f_read32(void *ctx, uint64_t pa, uint32_t *v)
{
	(void)ctx;
	if (m0_is_cp_memory(pa)) H.cp_mem_access++;
	if (pa == 0x05250000ULL) { *v = 0x004d4241u; return 0; }
	if (pa == 0x0c520010ULL) { *v = (H.rst_init && H.rst_pu && H.rst_perst) ? 4u : 0; return 0; }
	if (pa == 0x0c520018ULL) { *v = linked() ? 0xc0u : 0; return 0; }
	if (pa == 0x0c500028ULL) { *v = linked() ? (0x11u << 3) : (0x02u << 3); return 0; }
	if (pa == 0x0c80072cULL) { *v = 0; return 0; }
	if (pa == 0x0c800000ULL) { *v = 0x0000144du | (0xecu << 16); return 0; }      /* some root port id */
	if (pa == 0x0c800034ULL) { *v = 0x40; return 0; }
	if (pa == 0x0c800040ULL) { *v = 0x00000010u; return 0; }                       /* EXP cap, end of list */
	if (pa == 0x0c800050ULL) { *v = linked() ? 0x00110000u : 0; return 0; }          /* LNKSTA: gen 1, x1 */
	if (pa >= 0x40000000ULL && pa < 0x40001000ULL) {
		uint32_t off = (uint32_t)(pa - 0x40000000ULL);
		if (!linked() || !(*reg(0x0cb00004ULL) & 0x80000000u)) { *v = 0xffffffffu; return 0; }
		switch (off) {
		case 0x00: *v = H.ep_id; return 0;
		case 0x08: *v = 0x02800000u | 0x03; return 0;
		case 0x2c: *v = 0x0000144du; return 0;
		case 0x34: *v = 0x40; return 0;
		case 0x40: *v = 0x00000010u; return 0;
		case 0x4c: *v = 0x00000024u; return 0;          /* gen 4, x2: "capable of 16 GT/s x2" */
		default: *v = 0; return 0;
		}
	}
	int p = pad_index(pa);
	if (p >= 0 && (pa & 0xfffu) == 0x10) { *v = (*reg(pad_pa(p, 8)) >> 2) & 1u; return 0; }
	*v = *reg(pa);
	return 0;
}

static void mailbox_go(void)
{
	uint32_t w0 = *reg(0x05272100ULL), w1 = *reg(0x05272104ULL), w2 = *reg(0x05272108ULL);
	if (!H.locked) H.lock_errors++;
	if (H.nframes < 64) { H.frames[H.nframes][0] = w0; H.frames[H.nframes][1] = w1; H.frames[H.nframes][2] = w2; H.nframes++; }
	*reg(0x05272100ULL) = w0 | 0x00400000u;
	if (w0 == 0x05000003u) {
		*reg(0x05272104ULL) = H.lpb[w1 & 63];
	} else {
		*reg(0x05272104ULL) = H.lpcm_reply;
		if (H.lpcm_reply == 0) {
			if (w1 == 0x01010201u) H.pd_on = true;
			if (w1 == 0x01020504u) H.rst_init = true;
			if (w1 == 0x01030504u) H.rst_pu = true;
			if (w1 == 0x01000504u) H.rst_perst = true;
			if (w1 == 0x01010504u) H.rst_app = true;
		}
	}
	*reg(0x05272008ULL) = 1;
}

static int f_write32(void *ctx, uint64_t pa, uint32_t v)
{
	(void)ctx;
	H.writes++;
	if (m0_is_cp_memory(pa)) H.cp_mem_access++;
	if (pa == 0x05272000ULL) { if (v == 1) mailbox_go(); return 0; }
	if (pa == 0x05272008ULL) { if (v == 1) *reg(pa) = 0; return 0; }
	int p = pad_index(pa);
	if (p >= 0) {
		H.pad_writes++;
		if ((pa & 0xfffu) == 8 && H.ntx < 256) { H.tx_log[H.ntx][0] = p; H.tx_log[H.ntx][1] = (int)v; H.ntx++; }
	}
	if (pa >= 0x40000000ULL && pa < 0x40100000ULL) H.cfg_writes++;
	*reg(pa) = v;
	return 0;
}

static int f_write16(void *ctx, uint64_t pa, uint16_t v)
{
	(void)ctx;
	if (pa < 0x0c550000ULL || pa >= 0x0c55a000ULL) return -1;
	H.phy_writes++;
	if (pa == 0x0c550000ULL) *reg(pa) = v ? v : 1;
	return 0;
}
static void f_barrier(void *ctx) { (void)ctx; }
static void f_delay(void *ctx, uint32_t us) { (void)ctx; H.now_us += us; }
static uint64_t f_now(void *ctx) { (void)ctx; return H.now_us; }
static void f_log(void *ctx, const char *fmt, ...)
{
	(void)ctx;
	va_list a; va_start(a, fmt);
	int n = vsnprintf(H.log + H.loglen, sizeof(H.log) - H.loglen, fmt, a);
	va_end(a);
	if (n > 0 && H.loglen + (size_t)n < sizeof(H.log)) H.loglen += (size_t)n;
}
static void f_enter(void *ctx) { (void)ctx; if (H.locked) H.lock_errors++; H.locked = true; }
static void f_exit(void *ctx) { (void)ctx; if (!H.locked) H.lock_errors++; H.locked = false; }

static const struct m0_ops OPS = { f_read32, f_write32, f_write16, f_barrier, f_delay, f_now, f_log, f_enter, f_exit, NULL };
static uint16_t phy[20480];

/* As found: CP off (outputs driven low), PCIe0 pads gpio not driven */
static void reset_hw(void)
{
	memset(&H, 0, sizeof(H));
	nregs = 0;
	H.lpb[0x17] = H.lpb[0x18] = H.lpb[0x1c] = H.lpb[0x1e] = 2;
	H.cp_answers = true;
	H.ep_id = 0xa5a5144du;
	for (int i = 0; i < M0_PADS; i++) {
		*reg(pad_pa(i, 0)) = 0x100;
		*reg(pad_pa(i, 4)) = 1;
		*reg(pad_pa(i, 8)) = m0_pads[i].out && i < M0_PAD_CLKREQ ? 0x8u : 0x0u;
	}
}

static uint32_t found_tx[M0_PADS], found_mux[M0_PADS], found_param[M0_PADS];
static void snap_found(void)
{
	for (int i = 0; i < M0_PADS; i++) { found_tx[i] = *reg(pad_pa(i, 8)); found_mux[i] = *reg(pad_pa(i, 4)); found_param[i] = *reg(pad_pa(i, 0)); }
}
static bool pads_as_found(void)
{
	for (int i = 0; i < M0_PADS; i++)
		if (*reg(pad_pa(i, 8)) != found_tx[i] || *reg(pad_pa(i, 4)) != found_mux[i] || *reg(pad_pa(i, 0)) != found_param[i]) {
			printf("  pad %s: tx 0x%x (found 0x%x) mux 0x%x (0x%x)\n", m0_pads[i].name, *reg(pad_pa(i, 8)), found_tx[i], *reg(pad_pa(i, 4)), found_mux[i]);
			return false;
		}
	return true;
}

static int run(struct m0 *m, uint32_t stage, bool hold)
{
	struct m0_cfg cfg = { .stage = stage, .hold = hold, .phy = phy, .phy_words = 20480 };
	snap_found();
	m0_init(m, &OPS, &cfg);
	return m0_run(m);
}

/* index of the first TX write to pad p with DOUT = high, at or after from; -1 if none */
static int tx_at(int p, bool high, int from)
{
	for (int k = from; k < H.ntx; k++) if (H.tx_log[k][0] == p && (((H.tx_log[k][1] & 0xc) == 0xc) == high) && (H.tx_log[k][1] & 8)) return k;
	return -1;
}

int main(void)
{
	static struct m0 m;
	for (int i = 0; i < 20480; i++) phy[i] = (uint16_t)(i * 7 + 1);

	/* 1. READ: four LPB GETs, every pad read, nothing but the mailbox written */
	reset_hw();
	CHECK(run(&m, M0_STAGE_READ, false) == 0, "read stage rc %u", m.stop);
	CHECK(H.nframes == 4, "frames %d", H.nframes);
	for (int k = 0; k < H.nframes; k++) CHECK(H.frames[k][0] == 0x05000003u, "frame %d not a GET", k);
	CHECK(H.pad_writes == 0 && H.cfg_writes == 0 && H.phy_writes == 0, "read stage wrote pads/cfg/phy");
	CHECK(m.cp_off_found, "CP off not seen");
	CHECK(strstr(H.log, "read: CP as found: off") != NULL, "no CP line");
	CHECK(strstr(H.log, "pad AP2CP_CP_PWR_ON (0x3c596000)") != NULL, "pad line address");
	for (int i = 0; i < M0_PADS; i++) CHECK(m.found_ok[i], "pad %d unread", i);
	CHECK(m.at == M0_AT_READ, "at %u", m.at);

	/* 2. CTRL: clock, vote, three resets; no pads, no PHY */
	reset_hw();
	CHECK(run(&m, M0_STAGE_CTRL, false) == 0, "ctrl rc %s", m0_stop_name(m.stop));
	CHECK(H.nframes == 9, "ctrl frames %d", H.nframes);
	CHECK(H.frames[4][1] == 0x00030502u && H.frames[4][2] == 1, "clock frame");
	CHECK(H.frames[5][1] == 0x01010201u, "vote frame 0x%x", H.frames[5][1]);
	CHECK(H.pad_writes == 0 && H.phy_writes == 0, "ctrl wrote pads %d phy %d", H.pad_writes, H.phy_writes);
	CHECK(H.lock_errors == 0, "lock errors");

	/* 3. PHY: table and root port; still no pads */
	reset_hw();
	CHECK(run(&m, M0_STAGE_PHY, false) == 0, "phy rc %s", m0_stop_name(m.stop));
	CHECK(H.phy_writes == 20480, "phy writes %d", H.phy_writes);
	CHECK(H.pad_writes == 0 && H.cfg_writes == 0, "phy stage pad/cfg writes");
	CHECK(H.frames[H.nframes - 1][1] == 0x01010504u, "app_hold last");

	/* 4. LINK: CP on in stock order after PERST low, link, ID; then CP off and pads as found */
	reset_hw();
	CHECK(run(&m, M0_STAGE_LINK, false) == 0, "link rc %s 0x%x\n%s", m0_stop_name(m.stop), m.stop_detail, H.log);
	CHECK(m.ep_id == 0xa5a5144du, "ep id 0x%x", m.ep_id);
	CHECK(m.at == M0_AT_ID, "at %s", m0_at_name(m.at));
	CHECK((m.ep_lnkcap & 0xf) == 4 && ((m.ep_lnkcap >> 4) & 0x3f) == 2, "ep lnkcap 0x%x", m.ep_lnkcap);
	CHECK(H.cfg_writes == 0, "endpoint config written");
	CHECK(H.cp_mem_access == 0, "CP memory touched");
	{
		int perst_lo = -1, a = tx_at(M0_PAD_PM_WRST, true, 0), b = tx_at(M0_PAD_CP_PWR, true, 0), c = tx_at(M0_PAD_NRESET, true, 0), d = tx_at(M0_PAD_CP_WRST, true, 0);
		int e = tx_at(M0_PAD_PERST, true, 0);
		for (int k = 0; k < H.ntx; k++) if (H.tx_log[k][0] == M0_PAD_PERST) { perst_lo = k; break; }
		CHECK(perst_lo >= 0 && perst_lo < a, "PERST low (%d) not before CP power (%d)", perst_lo, a);
		CHECK(a >= 0 && a < b && b < c && c < d, "on order %d %d %d %d", a, b, c, d);
		CHECK(e > d, "PERST high (%d) before CP_WRST (%d)", e, d);
		int w = tx_at(M0_PAD_CP_WRST, false, e), x = tx_at(M0_PAD_NRESET, false, e), y = tx_at(M0_PAD_CP_PWR, false, e), z = tx_at(M0_PAD_PM_WRST, false, e);
		CHECK(w > e && w < x && x < y && y < z, "off order %d %d %d %d", w, x, y, z);
	}
	CHECK(pads_as_found(), "pads not restored");
	CHECK(!m.cp_on && !m.link_up, "left on");
	CHECK(strstr(H.log, "id: 144d:a5a5 class 0x028000 rev 0x03") != NULL, "id line:\n%s", H.log);
	CHECK(H.lock_errors == 0, "lock errors");
	if (getenv("HK_MODEM_LOG")) {
		/* The console as blazer_modem.c prints it (prefix per line, its verdict format), for the probe rows */
		FILE *f = fopen(getenv("HK_MODEM_LOG"), "w");
		for (char *l = H.log, *nl; f && *l; l = nl + 1) {
			nl = strchr(l, '\n');
			if (!nl) break;
			fprintf(f, "blazer-modem: %.*s\n", (int)(nl - l), l);
		}
		if (f) {
			fprintf(f, "blazer-modem: verdict: PASS stage %u, at %s: PCIe0 link gen %u x%u, endpoint %04x:%04x%s, frames %u\n", 4u, m0_at_name(m.at),
			    m.lnksta & 0xfu, (m.lnksta >> 4) & 0x3fu, m.ep_id & 0xffffu, m.ep_id >> 16, ", CP off again", m.frames);
			fclose(f);
		}
	}

	/* 5. LINK + hold: CP left in its ROM, link up */
	reset_hw();
	CHECK(run(&m, M0_STAGE_LINK, true) == 0, "hold rc");
	CHECK(m.cp_on && m.link_up && cp_powered(), "hold did not hold");

	/* 6. CP found on: stop before driving any pad */
	reset_hw();
	*reg(pad_pa(M0_PAD_CP_PWR, 8)) = 0xc;
	CHECK(run(&m, M0_STAGE_LINK, false) == M0_STOP_CP_NOT_OFF, "not-off rc %s", m0_stop_name(m.stop));
	CHECK(pads_as_found(), "pads changed with the CP found on");
	for (int k = 0; k < H.ntx; k++) CHECK(H.tx_log[k][0] == M0_PAD_PERST, "pad %d written with the CP found on", H.tx_log[k][0]);

	/* 7. HSIO_N off: ctrl refuses, no LPCM frame */
	reset_hw();
	H.lpb[0x17] = 1;
	CHECK(run(&m, M0_STAGE_LINK, false) == M0_STOP_HSIO_N_OFF, "hsio_n rc %s", m0_stop_name(m.stop));
	for (int k = 0; k < H.nframes; k++) CHECK(H.frames[k][0] == 0x05000003u, "LPCM frame with HSIO_N off");
	CHECK(!m.found_ok[M0_PAD_PERST] && !m.found_ok[M0_PAD_CLKREQ], "HSIO_N pads read while off");

	/* 8. CP silent: four attempts, stop, everything back */
	reset_hw();
	H.cp_answers = false;
	CHECK(run(&m, M0_STAGE_LINK, false) == M0_STOP_LINK, "silent rc %s", m0_stop_name(m.stop));
	CHECK(m.attempts == 5, "attempts %u", m.attempts);
	CHECK(pads_as_found(), "pads after silent CP");
	CHECK(!cp_powered(), "CP left powered");

	/* 9. Wrong vendor */
	reset_hw();
	H.ep_id = 0x443814e4u;
	CHECK(run(&m, M0_STAGE_LINK, false) == M0_STOP_WRONG_VENDOR, "vendor rc %s", m0_stop_name(m.stop));
	CHECK(pads_as_found() && !cp_powered(), "after wrong vendor");

	/* 10. LSIO_E off: PARTIAL_RST never read nor written, link still comes */
	reset_hw();
	H.lpb[0x1c] = 1;
	CHECK(run(&m, M0_STAGE_LINK, false) == 0, "lsio_e rc %s", m0_stop_name(m.stop));
	CHECK(!m.found_ok[M0_PAD_PARTIAL_RST], "PARTIAL_RST read with LSIO_E off");
	for (int k = 0; k < H.ntx; k++) CHECK(H.tx_log[k][0] != M0_PAD_PARTIAL_RST, "PARTIAL_RST written");

	/* 11. Refused addresses, whatever the state */
	{
		struct m0 z; memset(&z, 0, sizeof(z)); z.cfg.stage = M0_STAGE_LINK; z.link_up = z.atu_on = z.rc_ready = z.out_of_reset = true;
		for (int d = 0; d < M0_DOMS; d++) z.dom_on[d] = true;
		CHECK(!m0_write_allowed(&z, 0xea400000ULL) && !m0_read_allowed(&z, 0xea410000ULL), "cp_rmem");
		CHECK(!m0_write_allowed(&z, 0xf6200000ULL) && !m0_write_allowed(&z, 0xe8000000ULL) && !m0_write_allowed(&z, 0x0900c000ULL), "cp rmem");
		CHECK(!m0_write_allowed(&z, 0x3c590008ULL) && !m0_write_allowed(&z, 0x3c598008ULL), "UFS pads 0/8");
		CHECK(!m0_write_allowed(&z, 0x3c59a008ULL) && !m0_write_allowed(&z, 0x3c59d008ULL), "Wi-Fi pads");
		CHECK(!m0_write_allowed(&z, 0x0c581008ULL) && !m0_read_allowed(&z, 0x0c581008ULL), "NFC pad hsion 1");
		CHECK(!m0_write_allowed(&z, 0x40000004ULL) && !m0_write_allowed(&z, 0x40000010ULL), "endpoint config write");
		CHECK(!m0_write_allowed(&z, 0x3be26008ULL), "AP2CP_WAKEUP is read only");
		CHECK(!m0_write_allowed(&z, 0x0528b008ULL), "CP2AP pads are read only");
		CHECK(!m0_write_allowed(&z, 0x3c596010ULL), "RX write");
		CHECK(m0_write_allowed(&z, 0x3c596008ULL), "CP_PWR TX should be writable at LINK");
		z.cfg.stage = M0_STAGE_PHY;
		CHECK(!m0_write_allowed(&z, 0x3c596008ULL), "CP pad writable before LINK");
		CHECK(!m0_write_allowed(&z, 0x40400000ULL) && !m0_read_allowed(&z, 0x40700000ULL), "BAR space");
	}

	/* 12. Off: nothing at all */
	reset_hw();
	CHECK(run(&m, M0_STAGE_OFF, false) == 0 && H.nframes == 0 && H.writes == 0, "off did something");

	/* 13. Mailbox reply refused (LPCM non-zero): stop at the clock, nothing driven */
	reset_hw();
	H.lpcm_reply = 0xfffffff3u;
	CHECK(run(&m, M0_STAGE_LINK, false) == M0_STOP_CLOCK, "lpcm refused rc %s", m0_stop_name(m.stop));
	CHECK(H.pad_writes == 0, "pads written after a refused frame");

	printf("%d checks, %d failures\n", checks, fails);
	return fails != 0;
}
