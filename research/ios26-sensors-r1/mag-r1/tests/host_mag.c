/* Host test for blazer_mag_hw.c: the exact file against a register-level MMC5616WA model built from the v1.7 datasheet.
 * The model is my reading of the document; it says nothing about the phone. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BLAZER 1
#include "blazer_mag_hw.c"

static struct {
	uint8_t id, status1;
	int32_t field[3];               /* counts, signed, in the part's axes */
	int measuring, measured, set_done, writes_other, reads_other, bus_fail_at, ops, flat, freeze;
	unsigned long t_us, t_trigger;
	int early_read;
	int nwrites; uint8_t wlog[64][2];
} f;
static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL line %d: %s\n", __LINE__, #c); } } while (0)

static void out_bytes(uint8_t b[9])
{
	if (f.flat) { memset(b, f.flat == 1 ? 0x00 : 0xff, 9); return; }
	for (int i = 0; i < 3; i++) {
		uint32_t u = (uint32_t)(f.field[i] + MAG_NULL_COUNT) & 0xfffffu;
		b[2 * i] = (uint8_t)(u >> 12); b[2 * i + 1] = (uint8_t)(u >> 4);
		b[6 + i] = (uint8_t)((u & 0xf) << 4);
	}
	b[6] |= 0x3; /* fifo_usage bits: must be ignored */
	b[7] |= 0x1; /* fifo_empty: must be ignored */
}
static int f_read(void *c, uint32_t reg, uint8_t *out, uint32_t len)
{
	(void)c;
	if (++f.ops == f.bus_fail_at) return 99;
	if (reg == MAG_REG_PRODUCT_ID && len == 1) { *out = f.id; return 0; }
	if (reg == MAG_REG_STATUS1 && len == 1) { *out = f.status1; return 0; }
	if (reg == MAG_REG_XOUT0 && len == 9) {
		if (!f.measured || f.t_us - f.t_trigger < 6600) f.early_read++;
		out_bytes(out); f.measured = 0;
		if (!f.freeze) f.field[0]++;     /* noise: the next sample differs */
		return 0;
	}
	f.reads_other++; return 98;
}
static int f_write(void *c, uint32_t reg, uint32_t v)
{
	(void)c;
	if (++f.ops == f.bus_fail_at) return 99;
	if (f.nwrites < 64) { f.wlog[f.nwrites][0] = (uint8_t)reg; f.wlog[f.nwrites][1] = (uint8_t)v; f.nwrites++; }
	if (reg == MAG_REG_CTRL0 && v == MAG_CTRL0_DO_SET) { f.set_done = 1; return 0; }
	if (reg == MAG_REG_CTRL0 && v == MAG_MEASURE) { f.measured = 1; f.t_trigger = f.t_us; return 0; }
	f.writes_other++; return 0;
}
static void f_sleep(void *c, uint32_t us) { (void)c; f.t_us += us; }
static void f_log(void *c, const char *fmt, ...) { (void)c; (void)fmt; }
static const struct mag_bus bus = { f_read, f_write, f_sleep, f_log, NULL };
static void fresh(void) { memset(&f, 0, sizeof f); f.id = MAG_PRODUCT_ID; f.status1 = 0x10; }

int main(void)
{
	struct mag m;
	int32_t nt[3], c[3];
	uint8_t b[9];

	/* decode: null field, extremes, the low nibbles, fifo bits ignored */
	memset(b, 0, 9); b[0] = 0x80; b[2] = 0x80; b[4] = 0x80; mag_decode(b, c); CHECK(c[0] == 0 && c[1] == 0 && c[2] == 0);
	memset(b, 0, 9); b[6] = 0x0f; mag_decode(b, c); CHECK(c[0] == -MAG_NULL_COUNT && c[1] == -MAG_NULL_COUNT);
	memset(b, 0xff, 9); mag_decode(b, c); CHECK(c[0] == 524287 && c[1] == 524287 && c[2] == 524287);
	memset(b, 0, 9); b[0] = 0x80; b[1] = 0x00; b[6] = 0x10; b[2] = 0x80; b[7] = 0x0f; b[4] = 0x80; b[8] = 0xf0; mag_decode(b, c); CHECK(c[0] == 1 && c[1] == 0 && c[2] == 15);
	memset(b, 0, 9); b[0] = 0x80; b[1] = 0x01; b[2] = 0x80; b[4] = 0x80; mag_decode(b, c); CHECK(c[0] == 16);
	/* units: 1 G on part x is 100000 nT; transform -2 -1 -3 */
	c[0] = MAG_COUNTS_PER_GAUSS; c[1] = 0; c[2] = 0; mag_to_ios_nt(c, 0, nt); CHECK(nt[0] == 0 && nt[1] == -100000 && nt[2] == 0);
	c[0] = 0; c[1] = MAG_COUNTS_PER_GAUSS; c[2] = 0; mag_to_ios_nt(c, 0, nt); CHECK(nt[0] == -100000 && nt[1] == 0 && nt[2] == 0);
	c[0] = 0; c[1] = 0; c[2] = -MAG_COUNTS_PER_GAUSS / 2; mag_to_ios_nt(c, 0, nt); CHECK(nt[2] == 50000);
	c[0] = 512; c[1] = -512; c[2] = 1; mag_to_ios_nt(c, 0, nt); CHECK(nt[0] == 3125 && nt[1] == -3125 && nt[2] == -6);
	c[0] = 0; c[1] = MAG_COUNTS_PER_GAUSS; c[2] = MAG_COUNTS_PER_GAUSS; mag_to_ios_nt(c, 5, nt); CHECK(nt[0] == 100000 && nt[1] == 0 && nt[2] == 100000);
	c[0] = 524287; c[1] = -524288; c[2] = 524287; mag_to_ios_nt(c, 0, nt); CHECK(nt[0] == 3200000 && nt[1] == -3199993 && nt[2] == -3199993);
	/* earth field ~50 uT = 0.5 G = 8192 counts */
	c[0] = 8192; c[1] = 0; c[2] = 0; mag_to_ios_nt(c, 0, nt); CHECK(nt[1] == -50000);

	/* start: id, status logged, one SET, then a measurement; nothing else written */
	fresh(); CHECK(mag_start(&m, &bus) == 0 && m.started && m.pending && m.id == 0x11 && m.status_first == 0x10);
	CHECK(f.nwrites == 2 && f.wlog[0][0] == 0x1b && f.wlog[0][1] == 0x08 && f.wlog[1][0] == 0x1b && f.wlog[1][1] == 0x21);
	CHECK(f.t_us >= MAG_POWER_ON_US + MAG_SR_GAP_US && f.writes_other == 0 && f.reads_other == 0);
	/* stream: pipelined, each read follows a trigger by at least the caller's gap */
	f.field[0] = 8192; f.field[1] = -4096; f.field[2] = 100;
	for (int i = 0; i < 200; i++) {
		f.t_us += 100000;
		CHECK(mag_sample(&m, 0, nt));
		if (i == 0) CHECK(nt[0] == 25000 && nt[1] == -50000 && nt[2] == -610);
	}
	CHECK(m.samples == 200 && f.early_read == 0 && f.writes_other == 0 && f.reads_other == 0 && f.nwrites == 64);
	for (int i = 2; i < 64; i++) CHECK(f.wlog[i][0] == 0x1b && f.wlog[i][1] == 0x21);
	/* the caller's gap is the only timing: a too-early call is visible to the model */
	f.t_us += 1000; (void)mag_sample(&m, 0, nt); CHECK(f.early_read == 1);

	/* wrong id: no write at all */
	fresh(); f.id = 0x10; CHECK(mag_start(&m, &bus) == MAG_STOP_ID && f.nwrites == 0 && !m.started);
	CHECK(!mag_sample(&m, 0, nt) && m.stop == MAG_STOP_ID);
	fresh(); f.id = 0xff; CHECK(mag_start(&m, &bus) == MAG_STOP_ID && f.nwrites == 0);
	/* bus failures at each step stop for good, no retry */
	for (int at = 1; at <= 6; at++) {
		fresh(); f.bus_fail_at = at;
		int r = mag_start(&m, &bus);
		if (at <= 4) { CHECK(r == MAG_STOP_BUS && !m.started); }
		else {
			CHECK(r == 0); f.t_us += 100000;
			CHECK(!mag_sample(&m, 0, nt) && m.stop == MAG_STOP_BUS);
			int ops = f.ops; f.t_us += 100000; CHECK(!mag_sample(&m, 0, nt) && f.ops == ops);
		}
	}
	/* rails gone: all 00 or all ff stops */
	fresh(); CHECK(mag_start(&m, &bus) == 0); f.flat = 1; f.t_us += 100000; CHECK(!mag_sample(&m, 0, nt) && m.stop == MAG_STOP_FLAT);
	fresh(); CHECK(mag_start(&m, &bus) == 0); f.flat = 2; f.t_us += 100000; CHECK(!mag_sample(&m, 0, nt) && m.stop == MAG_STOP_FLAT && m.stop_detail == 0xff);
	/* frozen output: 50 identical samples in a row stop */
	fresh(); CHECK(mag_start(&m, &bus) == 0); f.freeze = 1; f.field[0] = 77;
	int n = 0; while (n < 100) { f.t_us += 100000; if (!mag_sample(&m, 0, nt)) break; n++; }
	CHECK(m.stop == MAG_STOP_STUCK && n == (int)MAG_STUCK_SAMPLES);
	/* an unstarted mag reads nothing */
	memset(&m, 0, sizeof m); m.bus = bus; fresh(); CHECK(!mag_sample(&m, 0, nt) && m.stop == MAG_STOP_NOT_STARTED && f.ops == 0);
	CHECK(strcmp(mag_stop_name(MAG_STOP_ID), "product id is not 0x11") == 0 && strcmp(mag_stop_name(99), "?") == 0);

	printf("host_mag: %d checks, %d failed\n", checks, failures);
	return failures != 0;
}
