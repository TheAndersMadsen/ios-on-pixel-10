/* SPDX-License-Identifier: MIT
 * HOST test of blazer_nfc_hw.c, the exact kernel logic, against a model: CPM mailbox, SMC, CLI words, the LSIO_E/HSIO_N/GDMC pads,
 * a DesignWare I2C master (TX FIFO flush on abort until CLR_TX_ABRT, STOP_DET, RX FIFO) and an ST21NFC that sends CORE_RESET_NTF
 * after power-up and answers the five allowed commands. The model refuses any write to an address it does not know.
 *   cc -std=c11 -DBLAZER -fsanitize=address,undefined -I../xnu-src/bsd/dev -I<xnu>/bsd/dev test_nfc_hw.c -o t && ./t */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "blazer_nfc_hw.c"

static int fails, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---------------- model ---------------- */
struct pk { uint32_t len; uint8_t b[64]; uint64_t due; };
static struct {
	uint64_t now;
	/* knobs */
	uint32_t en_dmux0, en_tx0, en_param0, irq_param0, cli0;
	bool stray_rsp, chip_present, nak_when_empty, lead_idle, loader, chatty, mba_dead, bus_busy, tag, init_err;
	uint32_t boot_us, tag_us;
	/* state */
	uint32_t en_dmux, en_tx, cli[3];
	uint32_t mba_st, mba_ctl, mba_msg[4];
	uint32_t ic_enable, ic_tar, ic_raw, ic_abrt, rx[512], rx_h, rx_t;
	bool xfer, xfer_read, flushing, powered, ntf_pending_boot;
	uint64_t power_at, off_at;
	uint32_t wbuf_len; uint8_t wbuf[64];
	struct pk q[64]; uint32_t qn; uint32_t cursor;
	/* records */
	uint32_t writes, en_writes, power_ons, power_offs, longest_off_us, tar_bad, sent_n, bus_in, bus_out, bus_depth, smc_n, frames;
	uint8_t sent[16][16]; uint32_t sent_len[16];
	bool bad_write; uint64_t bad_pa;
	uint32_t idle_reads_left;
	char log[65536]; size_t logn;
} M;

static void qpush(const uint8_t *b, uint32_t len, uint64_t delay)
{
	if (M.qn >= 64) return;
	struct pk *p = &M.q[M.qn++];
	p->len = len; memcpy(p->b, b, len); p->due = M.now + delay;
}
static bool q_ready(void) { return M.qn > 0 && M.q[0].due <= M.now; }
static void qpop(void) { memmove(&M.q[0], &M.q[1], (M.qn - 1) * sizeof(M.q[0])); M.qn--; M.cursor = 0; }

static const uint8_t reset_ntf_router[] = { 0x60, 0x00, 0x1e, 0x01, 0x00, 0x20, 0x02, 0x1a, 0x04, 0x00, 0x01, 0x30, 0x1e, 0x00, 0x01, 0x02, 0x03,
	0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x12, 0x34 };
static const uint8_t reset_ntf_loader[] = { 0x60, 0x00, 0x39, 0xa1, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

static void chip_power(bool on)
{
	if (on == M.powered) return;
	M.powered = on;
	if (on) {
		M.power_ons++;
		if (M.power_offs && M.now - M.off_at > M.longest_off_us) M.longest_off_us = (uint32_t)(M.now - M.off_at);
		M.qn = 0; M.cursor = 0;
		if (M.loader) qpush(reset_ntf_loader, sizeof(reset_ntf_loader), M.boot_us);
		else qpush(reset_ntf_router, sizeof(reset_ntf_router), M.boot_us);
	} else {
		M.power_offs++; M.off_at = M.now; M.qn = 0; M.cursor = 0;
	}
}
static void en_eval(void) { chip_power(M.en_dmux == 1 && (M.en_tx & 8) && (M.en_tx & 4)); }

static void chip_cmd(const uint8_t *b, uint32_t len)
{
	if (M.sent_n < 16) { memcpy(M.sent[M.sent_n], b, len < 16 ? len : 16); M.sent_len[M.sent_n] = len; }
	M.sent_n++;
	if (len >= 4 && b[0] == 0x20 && b[1] == 0x00) {
		const uint8_t r[] = { 0x40, 0x00, 0x01, 0x00 }; qpush(r, 4, 500);
		uint8_t n2[sizeof(reset_ntf_router)]; memcpy(n2, reset_ntf_router, sizeof(n2)); n2[3] = 0x02; qpush(n2, sizeof(n2), 3000);
	} else if (len == 5 && b[0] == 0x20 && b[1] == 0x01) {
		const uint8_t r[] = { 0x40, 0x01, 0x0b, 0x00, 0x1a, 0x1e, 0x00, 0x02, 0x00, 0x02, 0xff, 0x01, 0x00, 0x02 };
		uint8_t rr[sizeof(r)]; memcpy(rr, r, sizeof(r)); if (M.init_err) rr[3] = 0x03;
		if (M.stray_rsp) { const uint8_t x[] = { 0x4f, 0x01, 0x01, 0x05 }; qpush(x, 4, 300); }
		qpush(rr, sizeof(rr), 800);
		if (M.chatty) { const uint8_t e[] = { 0x60, 0x07, 0x01, 0xe0 }; for (int i = 0; i < 60; i++) qpush(e, 4, 900); }
	} else if (len == 5 && b[0] == 0x2f && b[1] == 0x02) {
		const uint8_t r[] = { 0x4f, 0x02, 0x01, 0x00 }; qpush(r, 4, 500);
	} else if (len >= 4 && b[0] == 0x21 && b[1] == 0x03) {
		const uint8_t r[] = { 0x41, 0x03, 0x01, 0x00 }; qpush(r, 4, 500);
		if (M.tag) {
			const uint8_t a[] = { 0x61, 0x05, 0x15, 0x01, 0x02, 0x04, 0x00, 0xff, 0x01, 0x0b, 0x44, 0x00, 0x07, 0x04, 0xa1, 0xb2, 0xc3, 0xd4, 0xe5, 0xf6, 0x01, 0x20, 0, 0 };
			qpush(a, sizeof(a), M.tag_us);
		}
		if (M.chatty) { const uint8_t e[] = { 0x61, 0x07, 0x01, 0x00 }; for (int i = 0; i < 60; i++) qpush(e, 4, 1000); }
	} else if (len == 4 && b[0] == 0x21 && b[1] == 0x06) {
		const uint8_t r[] = { 0x41, 0x06, 0x01, 0x00 }, d[] = { 0x61, 0x06, 0x02, 0x00, 0x00 }; qpush(r, 4, 500); qpush(d, 5, 900);
	} else {
		const uint8_t e[] = { 0x60, 0x07, 0x01, 0x05 }; qpush(e, 4, 100);
	}
}

static uint8_t chip_read_byte(void)
{
	if (M.idle_reads_left) { M.idle_reads_left--; return 0x7e; }
	if (!q_ready()) return 0x7e;
	uint8_t v = M.q[0].b[M.cursor++];
	return v;
}

#define PADP(base, p, r) ((base) + (uint64_t)(p) * 0x1000u + (r))
static uint64_t I2CR(uint32_t r) { return 0x3a331000ULL + r; }

static void i2c_data_cmd(uint32_t v)
{
	if (M.flushing) return;
	if (!M.xfer) {
		M.xfer = true; M.xfer_read = (v & 0x100) != 0; M.wbuf_len = 0;
		if (M.ic_tar != 0x08) M.tar_bad++;
		bool ack = M.chip_present && M.powered && M.ic_tar == 0x08;
		if (ack && M.xfer_read && M.nak_when_empty && !q_ready() && !M.idle_reads_left) ack = false;
		if (!ack) { M.ic_raw |= (1u << 6) | (1u << 9); M.ic_abrt = 1; M.flushing = true; M.xfer = false; return; }
		/* a header read at a packet boundary with lead_idle: one idle byte first, once */
		if (M.xfer_read && M.lead_idle && M.cursor == 0 && q_ready()) { M.idle_reads_left = 1; M.lead_idle = false; }
	}
	if (M.xfer_read) {
		if (M.rx_t - M.rx_h >= 64) { printf("model: RX FIFO overflow\n"); fails++; }
		M.rx[M.rx_t++ % 512] = chip_read_byte();
		if (v & 0x200) {
			M.xfer = false; M.ic_raw |= 1u << 9;
			if (M.qn && M.cursor >= M.q[0].len) qpop();
		}
	} else {
		if (M.wbuf_len < 64) M.wbuf[M.wbuf_len++] = (uint8_t)v;
		if (v & 0x200) { M.xfer = false; M.ic_raw |= 1u << 9; chip_cmd(M.wbuf, M.wbuf_len); }
	}
}

static int m_read32(void *ctx, uint64_t pa, uint32_t *v)
{
	(void)ctx;
	if (pa == 0x05250000ULL) { *v = 0x004d4241u; return 0; }
	if (pa >= 0x05272000ULL && pa < 0x05272200ULL) {
		uint32_t o = (uint32_t)(pa - 0x05272000ULL);
		*v = o == 8 ? M.mba_st : o == 4 ? M.mba_ctl : (o >= 0x100 && o < 0x110) ? M.mba_msg[(o - 0x100) / 4] : 0; return 0;
	}
	if (pa == 0x3a330000ULL) { *v = M.cli0; return 0; }
	if (pa == 0x3a330004ULL || pa == 0x3a330008ULL) { *v = M.cli[(pa - 0x3a330000ULL) / 4]; return 0; }
	if (pa == PADP(0x3a200000ULL, 16, 4) || pa == PADP(0x3a200000ULL, 17, 4)) { *v = 2; return 0; }
	if (pa == PADP(0x0c580000ULL, 1, 0)) { *v = M.en_param0; return 0; }
	if (pa == PADP(0x0c580000ULL, 1, 4)) { *v = M.en_dmux; return 0; }
	if (pa == PADP(0x0c580000ULL, 1, 8)) { *v = M.en_tx; return 0; }
	if (pa == PADP(0x0c580000ULL, 1, 0x10)) { *v = (M.en_tx & 8) ? (M.en_tx >> 2) & 1 : 0; return 0; }
	if (pa >= PADP(0x0c580000ULL, 3, 0) && pa <= PADP(0x0c580000ULL, 3, 0x10)) { *v = (pa & 0xff) == 0 ? 0x100 : (pa & 0xff) == 4 ? 1 : (pa & 0xff) == 0x10 ? M.powered : 1; return 0; }
	if (pa == PADP(0x06480000ULL, 3, 0)) { *v = M.irq_param0; return 0; }
	if (pa == PADP(0x06480000ULL, 3, 4)) { *v = 4; return 0; }
	if (pa == PADP(0x06480000ULL, 3, 8)) { *v = 1; return 0; }
	if (pa == PADP(0x06480000ULL, 3, 0x10)) { *v = (M.irq_param0 & 0x100) && M.powered && q_ready() ? 1 : 0; return 0; }
	if (pa >= 0x3a331000ULL && pa < 0x3a331100ULL) {
		uint32_t o = (uint32_t)(pa - 0x3a331000ULL);
		switch (o) {
		case 0xfc: *v = 0x44570140u; return 0;
		case 0xf8: *v = 0x3230312a; return 0;
		case 0x6c: *v = M.ic_enable; return 0;
		case 0x9c: *v = M.ic_enable & 1; return 0;
		case 0x04: *v = M.ic_tar; return 0;
		case 0x70: *v = 2 | (M.rx_t != M.rx_h ? 8 : 0) | (M.bus_busy ? 1 : 0); return 0;
		case 0x34: *v = M.ic_raw; return 0;
		case 0x80: *v = M.ic_abrt; return 0;
		case 0x54: M.ic_raw &= ~(1u << 6); M.flushing = false; *v = 0; return 0;
		case 0x60: M.ic_raw &= ~(1u << 9); *v = 0; return 0;
		case 0x10: *v = M.rx_t != M.rx_h ? M.rx[M.rx_h++ % 512] : 0; return 0;
		default: *v = 0; return 0;
		}
	}
	printf("model: read of unknown pa 0x%llx\n", (unsigned long long)pa); fails++;
	return -1;
}

static int m_write32(void *ctx, uint64_t pa, uint32_t v)
{
	(void)ctx;
	M.writes++;
	if (pa >= 0x05272000ULL && pa < 0x05272200ULL) {
		uint32_t o = (uint32_t)(pa - 0x05272000ULL);
		if (o == 8 && v == 1) M.mba_st = 0;
		else if (o == 4) M.mba_ctl = v;
		else if (o >= 0x100 && o < 0x110) M.mba_msg[(o - 0x100) / 4] = v;
		else if (o == 0 && v == 1) {
			M.frames++;
			if (M.mba_dead) return 0;
			uint32_t w0 = M.mba_msg[0], w1 = M.mba_msg[1];
			M.mba_msg[0] = w0 | 0x00400000u;
			M.mba_msg[1] = w0 == 0x05000003u ? 2 : w1 == 0x03140202u ? 200000000u : 0;
			M.mba_st = 1;
		}
		return 0;
	}
	if (pa == 0x3a330004ULL || pa == 0x3a330008ULL) { M.cli[(pa - 0x3a330000ULL) / 4] = v; return 0; }
	if (pa == PADP(0x0c580000ULL, 1, 4)) { M.en_writes++; M.en_dmux = v; en_eval(); return 0; }
	if (pa == PADP(0x0c580000ULL, 1, 8)) {
		M.en_writes++;
		if ((v & 8) && !(v & 4) && !(M.en_tx & 8) && (M.en_tx & 4) == 0 && M.powered) { /* driven low from on: fine */ }
		M.en_tx = v; en_eval(); return 0;
	}
	if (pa >= 0x3a331000ULL && pa < 0x3a331100ULL) {
		uint32_t o = (uint32_t)(pa - 0x3a331000ULL);
		switch (o) {
		case 0x6c: M.ic_enable = v; if (!(v & 1)) { M.xfer = false; } return 0;
		case 0x04: M.ic_tar = v; return 0;
		case 0x10: if (!(M.ic_enable & 1)) { printf("model: DATA_CMD with the controller off\n"); fails++; return 0; } i2c_data_cmd(v); return 0;
		case 0x00: case 0x1c: case 0x20: case 0x30: case 0x38: case 0x3c: return 0;
		default: break;
		}
	}
	M.bad_write = true; M.bad_pa = pa;
	printf("model: write of unknown pa 0x%llx = 0x%x\n", (unsigned long long)pa, v); fails++;
	return -1;
}

static void m_smc(void *ctx, uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t r[2]) { (void)ctx; (void)fn; (void)a1; (void)a2; (void)a3; M.smc_n++; r[0] = r[1] = 0; }
static void m_delay(void *ctx, uint32_t us) { (void)ctx; M.now += us; }
static void m_log(void *ctx, const char *f, ...)
{
	va_list a; (void)ctx;
	va_start(a, f);
	int k = vsnprintf(M.log + M.logn, sizeof(M.log) - M.logn, f, a);
	va_end(a);
	if (k > 0) M.logn += (size_t)k < sizeof(M.log) - M.logn ? (size_t)k : sizeof(M.log) - M.logn - 1;
}
static void m_bus_in(void *ctx) { (void)ctx; M.bus_in++; M.bus_depth++; }
static void m_bus_out(void *ctx) { (void)ctx; M.bus_out++; M.bus_depth--; }

static const struct nf_ops OPS = { .read32 = m_read32, .write32 = m_write32, .smc = m_smc, .delay_us = m_delay, .log = m_log,
	                           .bus_enter = m_bus_in, .bus_exit = m_bus_out };

static void reset_model(void)
{
	memset(&M, 0, sizeof(M));
	M.en_dmux0 = 1; M.en_tx0 = 0; M.en_param0 = 0x100; M.irq_param0 = 0x100; M.cli0 = 1;
	M.chip_present = true; M.boot_us = 5000; M.tag_us = 2500000;
}
static void start_model(void)
{
	M.en_dmux = M.en_dmux0; M.en_tx = M.en_tx0; M.cli[1] = 1; M.cli[2] = 1;
	en_eval();
	M.power_ons = 0; M.qn = 0; /* a chip that was on before the boot has nothing pending */
}

static struct nf N;
static int run(uint32_t stage, uint32_t listen)
{
	struct nf_cfg c = { .stage = stage, .listen_s = listen };
	start_model();
	nf_init(&N, &OPS, &c);
	return nf_run(&N);
}
static bool logged(const char *s) { return strstr(M.log, s) != NULL; }
static void end_state(const char *name)
{
	CHECK(M.ic_enable == 0 || M.writes == 0, "%s: controller left enabled", name);
	CHECK(M.bus_in == M.bus_out && M.bus_depth == 0, "%s: bus lock in %u out %u", name, M.bus_in, M.bus_out);
	CHECK(!M.bad_write, "%s: write to unknown pa 0x%llx", name, (unsigned long long)M.bad_pa);
	CHECK(M.tar_bad == 0, "%s: transfers to another address: %u", name, M.tar_bad);
	CHECK(M.en_tx == M.en_tx0 && M.en_dmux == M.en_dmux0, "%s: enable pad not restored: tx 0x%x dmux 0x%x", name, M.en_tx, M.en_dmux);
}

/* --emit SCENARIO: the console a phone boot would print for that model run (prefix and end line as blazer_nfc.c), for probe_eval */
static int emit(const char *what)
{
	reset_model();
	if (!strcmp(what, "tag")) M.tag = true;
	else if (!strcmp(what, "absent")) { M.chip_present = false; M.irq_param0 = 0; }
	else if (strcmp(what, "notag")) return 2;
	(void)run(4, 3);
	printf("com.apple.xpc.launchd|2026-11-03 00:00:00) boot-args = debug=0x8 blazer_haptic_tap=1 blazer_nfc=4 blazer_nfc_wait=30\n");
	printf("blazer-nfc: stage 4, starts in 60 s\n");
	for (char *l = M.log, *e; *l; l = e + 1) {
		e = strchr(l, '\n');
		if (!e) break;
		printf("blazer-nfc: %.*s\n", (int)(e - l), l);
	}
	printf("blazer-nfc: ends: %s, stage %u, chip %s, fw 0x%08x, ntfs %u, tags %u\n", nf_stop_name(N.stop), 4u,
	    N.fw_version || N.ntf_count ? "answered" : N.addr_ack ? "acked" : "silent", N.fw_version, N.ntf_count, N.tags);
	return 0;
}

int main(int argc, char **argv)
{
	int rc;

	if (argc == 3 && !strcmp(argv[1], "--emit")) return emit(argv[2]);

	/* 1: stage 1 is reads only */
	reset_model(); rc = run(1, 0);
	CHECK(rc == 0 && M.writes == 0 && M.frames == 0 && M.smc_n == 0 && M.bus_in == 0, "stage 1: rc %d writes %u frames %u", rc, M.writes, M.frames);
	CHECK(logged("chip enable not driven (off)") && logged("irq readable"), "stage 1 log:\n%s", M.log);

	/* 2: stage 2: power-up, the NTF, versions, pad back to off */
	reset_model(); rc = run(2, 0);
	CHECK(rc == 0, "stage 2 rc %d (%s)\n%s", rc, nf_stop_name(N.stop), M.log);
	CHECK(N.fw_version == 0x01301e00u && N.hw_version == 0x04 && N.nci_version == 0x20 && N.manuf == 0x02 && N.loader_version == 0x010203,
	    "stage 2 versions fw 0x%x hw 0x%x nci 0x%x manuf 0x%x loader 0x%x", N.fw_version, N.hw_version, N.nci_version, N.manuf, N.loader_version);
	CHECK(logged("chip st21nfc fw 0x01301e00 hw 0x04") && logged("address 0x08 acked, power-up reset ntf received"), "stage 2 log:\n%s", M.log);
	CHECK(M.sent_n == 0, "stage 2 sent %u commands", M.sent_n);
	CHECK(M.power_ons == 1 && !M.powered, "stage 2 power ons %u, powered at end %d", M.power_ons, M.powered);
	end_state("stage 2");

	/* 3: stage 3: CORE_RESET, its NTF, CORE_INIT; exactly two commands */
	reset_model(); rc = run(3, 0);
	CHECK(rc == 0 && logged("nci init ok: nci 0x20, fw 0x01301e00"), "stage 3 rc %d\n%s", rc, M.log);
	CHECK(M.sent_n == 2 && M.sent_len[0] == 4 && !memcmp(M.sent[0], "\x20\x00\x01\x01", 4) && M.sent_len[1] == 5 && !memcmp(M.sent[1], "\x20\x01\x02\x00\x00", 5),
	    "stage 3 commands: %u", M.sent_n);
	end_state("stage 3");

	/* 4: stage 4 with a tag 2.5 s in: technology and ID, then deactivate */
	reset_model(); M.tag = true; rc = run(4, 10);
	CHECK(rc == 0 && N.tags == 1 && logged("tag: nfc-a, protocol 0x4, id 04a1b2c3d4e5f6"), "stage 4 tag rc %d tags %u\n%s", rc, N.tags, M.log);
	CHECK(M.sent_n == 5 && M.sent[4][0] == 0x21 && M.sent[4][1] == 0x06 && logged("rf deactivated ntf"), "stage 4 tag: %u commands, last %02x %02x", M.sent_n, M.sent[4][0], M.sent[4][1]);
	CHECK(M.now < 8000000u, "stage 4 tag: stopped listening after the tag (t=%llu us)", (unsigned long long)M.now);
	end_state("stage 4 tag");

	/* 5: stage 4, no tag: listens the time, then deactivates */
	reset_model(); rc = run(4, 2);
	CHECK(rc == 0 && N.tags == 0 && logged("discovery: no tag") && M.sent_n == 5, "stage 4 no tag rc %d sent %u\n%s", rc, M.sent_n, M.log);
	CHECK(M.now >= 2000000u, "stage 4 no tag: listened only %llu us", (unsigned long long)M.now);
	end_state("stage 4 no tag");

	/* 6: IRQ input not enabled: polled reads, idle bytes when empty */
	reset_model(); M.irq_param0 = 0; rc = run(3, 0);
	CHECK(rc == 0 && logged("not readable, polled reads instead") && N.fw_version == 0x01301e00u, "polled/idle rc %d (%s)\n%s", rc, nf_stop_name(N.stop), M.log);
	end_state("polled idle");

	/* 7: polled, the chip NAKs while empty */
	reset_model(); M.irq_param0 = 0; M.nak_when_empty = true; rc = run(3, 0);
	CHECK(rc == 0 && N.fw_version == 0x01301e00u, "polled/nak rc %d (%s)\n%s", rc, nf_stop_name(N.stop), M.log);
	end_state("polled nak");

	/* 8: no chip */
	reset_model(); M.chip_present = false; M.irq_param0 = 0; rc = run(3, 0);
	CHECK(rc == NF_STOP_NAK && M.sent_n == 0 && logged("never acked"), "absent rc %d (%s)\n%s", rc, nf_stop_name(N.stop), M.log);
	end_state("absent");

	/* 9: enable found driven high: 30 ms low, then on; left on */
	reset_model(); M.en_tx0 = 0xc; rc = run(2, 0);
	CHECK(rc == 0 && M.power_offs == 1 && M.power_ons == 1 && M.longest_off_us >= 30000u && M.powered, "was on: rc %d offs %u ons %u off %u us powered %d",
	    rc, M.power_offs, M.power_ons, M.longest_off_us, M.powered);
	CHECK(logged("chip enable driven high (on)") && logged("after 30 ms low"), "was on log:\n%s", M.log);
	end_state("was on");

	/* 10: loader mode: no NCI command */
	reset_model(); M.loader = true; rc = run(3, 0);
	CHECK(rc == NF_STOP_LOADER && M.sent_n == 0 && logged("loader mode"), "loader rc %d sent %u", rc, M.sent_n);
	end_state("loader");

	/* 11: CORE_INIT status 3 */
	reset_model(); M.init_err = true; rc = run(4, 2);
	CHECK(rc == NF_STOP_NCI_STATUS && M.sent_n == 2 && (N.stop_detail & 0xff) == 3, "init error rc %d sent %u detail 0x%x", rc, M.sent_n, N.stop_detail);
	end_state("init error");

	/* 12: CPM dead: no I2C, no pad write */
	reset_model(); M.mba_dead = true; rc = run(4, 2);
	CHECK(rc == NF_STOP_MBA && M.en_writes == 0 && M.ic_enable == 0 && M.sent_n == 0, "mba dead rc %d en writes %u", rc, M.en_writes);
	end_state("mba dead");

	/* 13: bus busy (another master): stop after power-up, pad restored */
	reset_model(); M.bus_busy = true; rc = run(3, 0);
	CHECK(rc == NF_STOP_BUS_BUSY && M.sent_n == 0 && !M.powered, "busy rc %d powered %d", rc, M.powered);
	end_state("busy");

	/* 14: a leading idle byte before a header (the HAL's shift) */
	reset_model(); M.lead_idle = true; rc = run(3, 0);
	CHECK(rc == 0 && N.fw_version == 0x01301e00u, "lead idle rc %d (%s)\n%s", rc, nf_stop_name(N.stop), M.log);
	end_state("lead idle");

	/* 15: a chatty chip cannot hold the bus forever */
	reset_model(); M.chatty = true; rc = run(4, 3);
	CHECK(M.now < 60000000u, "chatty: ran %llu us", (unsigned long long)M.now);
	end_state("chatty");

	/* 16: the enable pad muxed to another function: never written */
	reset_model(); M.en_dmux0 = 2; rc = run(2, 0);
	CHECK(rc == NF_STOP_EN_PAD && M.en_writes == 0, "foreign mux rc %d en writes %u", rc, M.en_writes);
	end_state("foreign mux");

	/* 17: enable pad not muxed (0): set to GPIO, restored to 0 */
	reset_model(); M.en_dmux0 = 0; rc = run(2, 0);
	CHECK(rc == 0 && N.fw_version == 0x01301e00u, "mux 0 rc %d (%s)", rc, nf_stop_name(N.stop));
	end_state("mux 0");

	/* 18: bad stage, and keep=1 leaves the chip on */
	reset_model(); rc = run(5, 0);
	CHECK(rc == NF_STOP_STAGE && M.writes == 0, "stage 5 rc %d", rc);
	reset_model(); { struct nf_cfg c = { .stage = 2, .keep = 1 }; start_model(); nf_init(&N, &OPS, &c); rc = nf_run(&N); }
	CHECK(rc == 0 && M.powered && M.en_tx == 0xc, "keep: rc %d powered %d tx 0x%x", rc, M.powered, M.en_tx);

	/* 19: the refusals: a command above the stage, an address outside the list */
	reset_model(); start_model(); { struct nf_cfg c = { .stage = 3 }; nf_init(&N, &OPS, &c); }
	CHECK(send(&N, C_DISCOVER) == NF_STOP_REFUSED_CMD && M.sent_n == 0, "discover at stage 3 not refused");
	reset_model(); start_model(); { struct nf_cfg c = { .stage = 4 }; nf_init(&N, &OPS, &c); }
	CHECK(wr(&N, PADP(0x0c580000ULL, 6, 8), 0xc) == NF_STOP_REFUSED_PA && M.writes == 0, "eSE enable pad write not refused");
	reset_model(); start_model(); { struct nf_cfg c = { .stage = 4 }; nf_init(&N, &OPS, &c); }
	CHECK(wr(&N, PADP(0x06480000ULL, 3, 0), 0x100) == NF_STOP_REFUSED_PA, "IRQ pad write not refused");

	/* 20: a stray response (another GID/OID, status 5) before CORE_INIT's is not taken for it */
	reset_model(); M.stray_rsp = true; rc = run(3, 0);
	CHECK(rc == 0 && logged("unexpected packet mt 2 gid 15 oid 1"), "stray rsp rc %d (%s)", rc, nf_stop_name(N.stop));
	end_state("stray rsp");

	printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
