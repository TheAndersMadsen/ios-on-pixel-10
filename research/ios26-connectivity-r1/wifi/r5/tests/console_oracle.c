/* SPDX-License-Identifier: MIT
 * HOST ONLY. W1 r5: the console counter. Links the real r5 blazer_bcm4390.c, so b4_console() reads a fake hnd_cons_t through the real BAR2
 * window code and feeds every whole line to the real b4_console_note(). The lines are r3's own console lines (physical,
 * research/laguna-usb-fix/attempts/20261103-203419-a7-wifi-join-r3, method 1 and method 2), so the count it must reach is r3's: 13.
 *
 *   console_oracle   exit 0: every case passed */
#define _POSIX_C_SOURCE 200112L
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "blazer_pcie1.h"

#define RAM_BASE 0x2a0000u
#define RAM_END  0x5c0000u
#define CONS     0x585b54u      /* r3: "console at 0x585b54: buffer 0x54a658, 8192 bytes" */
#define CBUF     0x54a658u
#define CSIZE    8192u

static uint8_t ram[RAM_END - RAM_BASE];
static uint32_t win = 0xffffffffu;
static char logbuf[1 << 16];
static size_t loglen;
static unsigned fails;

#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL %d: ", __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

int p1_wr(struct p1 *p, uint64_t pa, uint32_t v) { (void)p; if (pa == 0x60000000ull + P1_C_RAM_WIN) { win = v; return 0; } abort(); }     /* config space: the RAM window */
int p1_rd(struct p1 *p, uint64_t pa, uint32_t *v)
{
	uint64_t a;

	(void)p;
	if (pa < P1_EP_BAR2 || pa + 4 > P1_EP_BAR2 + P1_EP_BAR2_SIZE || win == 0xffffffffu) {
		abort();
	}
	a = win + (pa - P1_EP_BAR2);
	if (a < RAM_BASE || a + 4 > RAM_END) {
		abort();
	}
	memcpy(v, ram + (a - RAM_BASE), 4);
	return 0;
}
int p1_wr16(struct p1 *p, uint64_t pa, uint16_t v) { (void)p; (void)pa; (void)v; abort(); }
int p1_rmw(struct p1 *p, uint64_t pa, uint32_t c, uint32_t s) { (void)p; (void)pa; (void)c; (void)s; abort(); }
int p1_halt(struct p1 *p, uint32_t code, uint32_t detail) { p->stop = code; p->stop_detail = detail; return (int)code; }
bool p1_write_allowed(const struct p1 *p, uint64_t pa) { (void)p; (void)pa; return false; }
void b4_scrub_text(const struct p1 *p, char *line) { (void)p; (void)line; }
int b4_gate_level(const struct p1 *p) { (void)p; abort(); }
bool b4_ioctl_allowed(uint32_t cmd, const uint8_t *buf, uint32_t len, int level) { (void)cmd; (void)buf; (void)len; (void)level; abort(); }
void b4_net_rx(struct p1 *p, const uint8_t *b, uint32_t n) { (void)p; (void)b; (void)n; abort(); }
void b4_on_event(struct p1 *p, const uint8_t *b, uint32_t n) { (void)p; (void)b; (void)n; abort(); }
void b4_on_flow_created(struct p1 *p, int32_t s, uint32_t f) { (void)p; (void)s; (void)f; abort(); }
int b4_scan(struct p1 *p) { (void)p; abort(); }

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

static uint32_t at;

static void
put_console(const char *text)
{
	size_t n = strlen(text);
	uint32_t w;

	memcpy(ram + (CBUF - RAM_BASE) + at, text, n);
	at += (uint32_t)n;
	w = CBUF; memcpy(ram + (CONS - RAM_BASE) + 8, &w, 4);
	w = CSIZE; memcpy(ram + (CONS - RAM_BASE) + 12, &w, 4);
	memcpy(ram + (CONS - RAM_BASE) + 16, &at, 4);
}

static unsigned
count(const char *hay, const char *needle)
{
	unsigned n = 0;

	for (const char *c = hay; (c = strstr(c, needle)) != NULL; c++) {
		n++;
	}
	return n;
}

int
main(void)
{
	struct p1 *p = calloc(1, sizeof(*p));

	p->ops.log = logf_;
	p->cfg.stage = P1_STAGE_JOIN;
	p->console_addr = CONS;
	/* r3, method 1: the join scan, then the join */
	put_console("000.912385335 EL: 30 1f08\n001.106773950 [DSA]: set profile idx 1:1\n"
	    "007.925154416 EL: 30 b8c8 473eac 0\n007.929004448 EL: 30 b8c8 472fa4 0\n007.929476350 EL: 30 b8c8 46fed0 0\n"
	    "007.948435500 EL: 30 b8c8 46fea8 0\n007.949036581 EL: 30 b8c8 46fd5c 0\n007.969069211 EL: 30 b8c8 472834 0\n"
	    "007.970230129 EL: 30 b8c8 47285c 0\n007.989471826 EL: 30 b8c8 4703a8 0\n007.991162688 EL: 30 b8c8 46fed0 0\n"
	    "008.150399140 Start PSK to PMK conversion 0\n008.151632550 EL: 30 b8c8 471478 0\n008.155908839 EL: 30 b8c8 46f39c 0\n"
	    "008.156232398 EL: 30 b8c8 471288 0\n008.175547343 EL: 30 b8c8 470f48 0\n");
	CHECK(b4_console(p) == 0, "console 1: stop %u", p->stop);
	CHECK(p->fw_rx_nobuf == 13, "method 1: %u, want 13", p->fw_rx_nobuf);
	/* Not a drop: other tags and formats (b8c0 is another event in the same function, RAM 0x2c45da in .57.31, not this drop), and a b8c8 that isn't tag 0x30 */
	put_console("000.350479908 EL: e6 d838\n014.204882391 BTCX override IPC err:3, c:0, ovd:0 WLAN:5, BTCX:1\nEL: 31 b8c8 1 0\nEL: 30 b8c0\n");
	CHECK(b4_console(p) == 0 && p->fw_rx_nobuf == 13, "non-drops counted: %u", p->fw_rx_nobuf);
	/* r3, method 2 */
	put_console("014.206534871 Start PSK to PMK conversion 0\n014.207633999 EL: 30 b8c8 4ff32c 0\n014.212936376 EL: 30 b8c8 4ff2f4 0\n"
	    "014.213320761 EL: 30 b8c8 4ff284 0\n014.230884123 EL: 30 b8c8 46ed9c 0\n");
	CHECK(b4_console(p) == 0 && p->fw_rx_nobuf == 17, "method 2: %u, want 17", p->fw_rx_nobuf);
	CHECK(count(logbuf, "rx: the firmware dropped a packet for the host: no host RX buffer was queued (EL 30 b8c8)") == 1, "said once:\n%s", logbuf);
	CHECK(count(logbuf, "fw says: ") == 25, "every line still logged: %u", count(logbuf, "fw says: "));
	printf("console: r3's lines -> %u drops (13 in method 1, 4 in method 2), said once, all %u lines logged\n", p->fw_rx_nobuf, count(logbuf, "fw says: "));
	printf(fails ? "console_oracle: %u FAILED\n" : "console_oracle: all cases passed\n", fails);
	return fails != 0;
}
