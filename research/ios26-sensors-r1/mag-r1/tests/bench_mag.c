/* Bit-level bench for patch 0930: blazer_sensor_hw.c (patched) + blazer_mag_hw.c against research/ios26-sensors-r1/tests/bench.c's fake CPM, PMIC, pads and I2C slave,
 * extended with an MMC5616WA register file at 0x30 (datasheet v1.7). Harness copied from bench.c; fakes are my reading of the sources and say nothing about the phone. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BLAZER 1
#include "blazer_sensor_hw.c"
#include "blazer_mag_hw.c"
#include "blazer_cpmq.h"
#define Q_REQ 0x05260000ULL
#define Q_RESP 0x05261000ULL
#define Q_DOORBELL 0u
#define Q_IRQ_CFG 4u
#define Q_IRQ_STATUS 8u
#define Q_OUTSTANDING 0x10u
#define Q_GLOBAL_WORDS(c) (MBA_MAGIC_PA + 0x10u + 4u * (c))
#define Q_MSG 0x100u
#define Q_ST_MSG 1u
#define Q_ST_ACK (1u << 8)
#define Q_INIT 0x100u
#define Q_TYPE_RESPONSE (2u << 29)

static struct world {
	int aoc_state, a32, ipc_move, ipc_magic, mba_magic_bad, mba_mute, q_mute, pmic_status, vsel_bad, rail_stuck_off, rail_18, rail_33, dmux, oe_entry;
	int ext_pull, sda_stuck, scl_stuck, nack_addr, nack_reg, nack_read, who, no_slave;
	uint32_t param[2], dm[2], tx[2], mba_st, mba_msg[4], req_st, resp_st, resp[64], rcur, qwords, req[64];
	/* slave */
	int scl, sda, sl_low, st, bitn, shift, reading, reg, rdidx;
	int bytes[64], nbytes, writes, starts;
	int rail_events[16], nrail;
	int pad_write_before_rails, pad_write_after_off, clocks_rails_off;
	int16_t accel[3];
	unsigned long reads, writes_mmio;
	int bad_page;
	int pad_writes;
	unsigned long sleep;
	int lock_depth, polled_unlocked, interleave, other_ok, owner_inside;
	uint32_t qtx; int qinit;
	uint32_t pscl, psda; int cur_addr; int present[128]; int16_t gyro[3];
	uint8_t mreg[256]; int mwrites[256][2], nmw, mid_bad;
} w;

static int powered(void) { return w.rail_18 && w.rail_33; }
static int pad_pulled_up(int i) { return (w.tx[i] & 3u) == 2u; }
static int line(int i) {
	if ((w.tx[i] & TX_OE) && !(w.tx[i] & TX_DOUT)) return 0;
	if (i == 0 && w.scl_stuck) return 0;
	if (i == 1 && (w.sda_stuck || w.sl_low)) return 0;
	return w.ext_pull || pad_pulled_up(i);
}
static uint8_t slave_byte(void) {
	if (w.cur_addr == 0x30) { uint8_t b = w.reg == 0x39 ? (uint8_t)(w.mid_bad ? 0x12 : 0x11) : w.mreg[(w.reg + w.rdidx) & 0xff]; w.rdidx++; return b; }
	if (w.cur_addr != 0x68) return 0x10;
	if (w.reg == 0x72) return (uint8_t)w.who;
	if (w.reg <= 11) { uint8_t b = w.rdidx < 6 ? ((uint8_t *)w.accel)[w.rdidx] : ((uint8_t *)w.gyro)[w.rdidx - 6]; w.rdidx++; return b; }
	return 0;
}
enum { S_IDLE, S_ADDR, S_ACK, S_REG, S_DATA_OUT, S_MACK, S_WVAL, S_NACKED };
static int ack_for;
static void slave_eval(void) {
	int scl = line(0), sda;
	/* slave holds SDA only while it decides; compute with its current hold */
	sda = line(1);
	if (w.no_slave || !powered()) { w.scl = scl; w.sda = sda; w.sl_low = 0; return; }
	if (w.scl && scl && w.sda && !sda) { w.st = S_ADDR; w.bitn = 0; w.shift = 0; w.starts++; w.sl_low = 0; }
	else if (w.scl && scl && !w.sda && sda) { w.st = S_IDLE; w.sl_low = 0; }
	else if (!w.scl && scl) { /* rising: sample */
		if (w.st == S_ADDR || w.st == S_REG || w.st == S_WVAL) { w.shift = w.shift << 1 | sda; w.bitn++; }
		else if (w.st == S_MACK) { w.reading = !sda; }
	} else if (w.scl && !scl) { /* falling: change */
		if (w.st == S_ACK) {
			w.sl_low = 0;
			if (ack_for == 1) { w.st = w.reading ? S_DATA_OUT : S_REG; w.bitn = 0; w.shift = 0; if (w.reading) { w.shift = slave_byte(); w.sl_low = !((w.shift >> 7) & 1); w.bitn = 1; } }
			else if (ack_for == 2) { w.st = S_WVAL; w.bitn = 0; w.shift = 0; }
			else if (ack_for == 3) { w.st = S_WVAL; w.bitn = 0; w.shift = 0; }
		} else if (w.st == S_MACK) {
			w.sl_low = 0;
			if (w.reading) { w.st = S_DATA_OUT; w.shift = slave_byte(); w.sl_low = !((w.shift >> 7) & 1); w.bitn = 1; } else w.st = S_NACKED;
		} else if (w.st == S_DATA_OUT) {
			if (w.bitn == 8) { w.sl_low = 0; w.st = S_MACK; }
			else { w.sl_low = !((w.shift >> (7 - w.bitn)) & 1); w.bitn++; }
		} else if ((w.st == S_ADDR || w.st == S_REG || w.st == S_WVAL) && w.bitn == 8) {
			int b = w.shift & 0xff, ack = 1;
			if (w.nbytes < 64) w.bytes[w.nbytes++] = b;
			if (w.st == S_ADDR) { w.reading = b & 1; w.cur_addr = b >> 1; ack = w.present[b >> 1] && !w.nack_addr && !(w.reading && w.nack_read); ack_for = 1; }
			else if (w.st == S_REG) { w.reg = b; w.rdidx = 0; ack = !w.nack_reg; ack_for = 2; }
			else { w.writes++; ack_for = 3; if (w.cur_addr == 0x30 && w.nmw < 256) { w.mwrites[w.nmw][0] = w.reg; w.mwrites[w.nmw][1] = b; w.nmw++; } }
			if (ack) { w.sl_low = 1; w.st = S_ACK; } else { w.st = S_NACKED; }
		}
	}
	w.scl = scl; w.sda = line(1);
}
static void poll_check(uint64_t pa) { if (pa >= MBA_PAGE && pa < MBA_PAGE + 0x1000 && !w.lock_depth) w.polled_unlocked++; }
static void queue_check(uint64_t pa) { if (pa >= Q_REQ && pa < Q_RESP + 0x1000 && !w.owner_inside) w.bad_page = 1; }
static int fake_rd(void *c, uint64_t pa, uint32_t *v) {
	(void)c; w.reads++; poll_check(pa); queue_check(pa);
	if (pa == MBA_MAGIC_PA) *v = w.mba_magic_bad ? 0 : MBA_MAGIC;
	else if (pa == Q_GLOBAL_WORDS(0) || pa == Q_GLOBAL_WORDS(1)) *v = w.qwords;
	else if (pa == MBA_PAGE + MBA_CTL) *v = 0;
	else if (pa == MBA_PAGE + MBA_ST) *v = w.mba_st;
	else if (pa >= MBA_PAGE + MBA_MSG && pa < MBA_PAGE + MBA_MSG + 16) *v = w.mba_msg[(pa - MBA_PAGE - MBA_MSG) / 4];
	else if (pa == LCPM_A32) *v = w.a32;
	else if (pa >= IPC && pa < IPC + 64) { static uint32_t n; *v = pa == IPC && w.ipc_magic ? IPC_MAGIC : w.ipc_move ? n++ : 0; }
	else if (pa == Q_REQ + Q_IRQ_STATUS) *v = w.req_st;
	else if (pa == Q_REQ + Q_IRQ_CFG || pa == Q_RESP + Q_IRQ_CFG) *v = 0;
	else if (pa == Q_REQ + Q_OUTSTANDING) *v = 0;
	else if (pa == Q_RESP + Q_IRQ_STATUS) *v = w.resp_st;
	else if (pa >= Q_RESP + Q_MSG && pa < Q_RESP + Q_MSG + 256) *v = w.resp[(pa - Q_RESP - Q_MSG) / 4];
	else if ((pa >> 12) == (PAD_PA(w.pscl) >> 12) || (pa >> 12) == (PAD_PA(w.psda) >> 12)) {
		int i = (pa >> 12) == (PAD_PA(w.psda) >> 12), o = (int)(pa & 0xfff);
		if (o == P_PARAM) *v = w.param[i]; else if (o == P_DMUX) *v = w.dm[i]; else if (o == P_TX) *v = w.tx[i]; else if (o == P_RX) *v = (uint32_t)line(i); else w.bad_page = 1;
	} else { w.bad_page = 1; printf("BAD READ %llx\n", (unsigned long long)pa); *v = 0; }
	return 0;
}
static void pmic_do(const uint32_t *m) {
	uint32_t ty = m[1] >> 24, c = (m[1] >> 16) & 0xff, id = m[1] & 0xffff, r = 0, dst = m[0] & 0xff, src = (m[0] >> 8) & 0xff;
	if (id == 0x50 && ty == PMIC_REGULATOR) { r = 77; w.other_ok++; }
	else {
		int *rail = id == LDO_1V8 ? &w.rail_18 : &w.rail_33;
		assert(ty == PMIC_REGULATOR);
		if (c == REG_GET_ENABLED) r = (uint32_t)*rail;
		else if (c == REG_GET_VSEL) r = w.vsel_bad ? 1 : id == LDO_1V8 ? SEL_1V8 : SEL_3V3;
		else if (c == REG_SET_ENABLE) { if (!w.rail_stuck_off) *rail = (int)m[2]; if (w.nrail < 16) w.rail_events[w.nrail++] = (int)(id << 1 | m[2]); if (!m[2] && (pad_pulled_up(0) || pad_pulled_up(1))) w.pad_write_after_off++; }
		else abort();
	}
	w.resp[w.rcur] = Q_TYPE_RESPONSE | (m[0] & 0x00f00000u) | dst << 8 | src;
	w.resp[w.rcur + 1] = (uint32_t)w.pmic_status << 24; w.resp[w.rcur + 2] = r; w.resp[w.rcur + 3] = 0;
	w.rcur = (w.rcur + 4) % w.qwords; w.resp_st |= Q_ST_MSG;
}
static int fake_wr(void *c, uint64_t pa, uint32_t v) {
	(void)c; w.writes_mmio++; poll_check(pa); queue_check(pa);
	if (pa == MBA_PAGE + MBA_ST) { if (v & 1) w.mba_st = 0; }
	else if (pa == MBA_PAGE + MBA_CTL) {}
	else if (pa >= MBA_PAGE + MBA_MSG && pa < MBA_PAGE + MBA_MSG + 16) w.mba_msg[(pa - MBA_PAGE - MBA_MSG) / 4] = v;
	else if (pa == MBA_PAGE + MBA_GO) { if (!w.mba_mute) { w.mba_msg[0] |= MBA_REPLY_BIT; assert(w.mba_msg[1] == 0); w.mba_msg[1] = (uint32_t)w.aoc_state; w.mba_st = 1; } }
	else if (pa == Q_REQ + Q_IRQ_STATUS) w.req_st &= ~v;
	else if (pa == Q_RESP + Q_IRQ_STATUS) w.resp_st &= ~v;
	else if (pa == Q_REQ + Q_IRQ_CFG || pa == Q_RESP + Q_IRQ_CFG) {}
	else if (pa >= Q_REQ + Q_MSG && pa < Q_REQ + Q_MSG + 256) w.req[(pa - Q_REQ - Q_MSG) / 4] = v;
	else if (pa == Q_REQ + Q_DOORBELL) {
		if (!w.q_mute) {
			w.req_st |= Q_ST_ACK;
			if (!w.qinit) { w.qinit = 1; w.rcur = 0; w.qtx = 0; assert(w.req[0] == Q_INIT); }
			else { pmic_do(&w.req[w.qtx]); w.qtx = (w.qtx + 4) % w.qwords; }
		}
	} else if ((pa >> 12) == (PAD_PA(w.pscl) >> 12) || (pa >> 12) == (PAD_PA(w.psda) >> 12)) {
		int i = (pa >> 12) == (PAD_PA(w.psda) >> 12), o = (int)(pa & 0xfff);
		w.pad_writes++;
		if (o == P_PARAM) w.param[i] = v;
		else if (o == P_TX) {
			if (!(w.rail_18 && w.rail_33) && (v & TX_OE)) w.clocks_rails_off++;
			if (!(w.rail_18 && w.rail_33) && (v & 3u) == 2u) w.pad_write_before_rails++;
			w.tx[i] = v;
			slave_eval();
		} else { printf("BAD PAD WRITE %llx\n", (unsigned long long)pa); w.bad_page = 1; }
	} else { w.bad_page = 1; printf("BAD WRITE %llx\n", (unsigned long long)pa); }
	return 0;
}
static void f_sleep(void *c, uint32_t us) { (void)c; w.sleep += us; }
static void f_log(void *c, const char *f, ...) { (void)c; (void)f; }
static void f_enter(void *c) { (void)c; assert(!w.owner_inside); w.lock_depth++; }
static void f_exit(void *c) { (void)c; w.lock_depth--; }
static void f_ms(void *c, uint32_t ms) { (void)c; w.sleep += ms * 1000; }
static void f_lock(void *c) { (void)c; assert(!w.lock_depth); w.owner_inside = 1; }
static void f_unlock(void *c) { (void)c; w.owner_inside = 0; }
static struct cpmq owner;
static int f_pmic(void *c, uint32_t word, uint32_t data, uint32_t reply[4]) {
	uint32_t body[3] = { word, data, 0 }, r[4];
	(void)c; assert(!w.lock_depth);
	if (w.interleave) { uint32_t tb[3] = { 0x01010050, 0, 0 }; int rc = cpmq_call(&owner, 0, 0x0a, tb, r, 1000, NULL); assert(rc == 0 && r[2] == 77); }
	return cpmq_call(&owner, 0, 0x0a, body, reply, 1000, NULL);
}
static const struct sns_ops ops = { fake_rd, fake_wr, f_sleep, f_sleep, f_log, f_pmic, f_enter, f_exit, NULL };
static void owner_fresh(void) { memset(&owner, 0, sizeof owner); owner.ops = (struct cpmq_ops){ .read32 = fake_rd, .write32 = fake_wr, .sleep_ms = f_ms, .lock = f_lock, .unlock = f_unlock, .log = f_log }; }
static void fresh(void) {
	memset(&w, 0, sizeof w);
	w.pscl = 35; w.psda = 36; w.present[0x68] = 1;
	w.aoc_state = 2; w.a32 = 0x10; w.qwords = 16; w.who = 0x8b;
	for (int i = 0; i < 2; i++) { w.param[i] = 0x100; w.dm[i] = DMUX_GPIO; w.tx[i] = 1; }
	w.scl = w.sda = 0;
	owner_fresh();
}
#define CHECK(c) do { if (!(c)) { printf("FAIL %s: %s (stop %s)\n", name, #c, sns_stop_name(s.stop)); exit(1); } } while (0)
static struct sns s;
static void go(enum sns_mode m) { sns_init(&s, &ops, m); (void)sns_run(&s); }
static void invariants(const char *name, int changed) {
	CHECK(!w.bad_page);
	CHECK(w.polled_unlocked == 0 && w.lock_depth == 0);
	CHECK(w.clocks_rails_off == 0);
	CHECK(w.pad_write_before_rails == 0);
	if (changed) {
		CHECK(w.tx[0] == 1 && w.tx[1] == 1 && w.param[0] == 0x100 && w.param[1] == 0x100);
	}
	CHECK(w.dm[0] == DMUX_GPIO || w.pad_writes == 0);
	CHECK(w.writes == 0);
	CHECK(w.pad_write_after_off == 0);
	CHECK(!(w.rail_18 || w.rail_33) || w.q_mute || w.rail_stuck_off);
}
struct sc { const char *name; int field_off; int val; uint32_t stop; int changed; };
#define F(x) offsetof(struct world, x)

static struct sns *bus_s;
static int b_read(void *c, uint32_t reg, uint8_t *out, uint32_t len) { (void)c; return sns_bus_read(bus_s, MAG_ADDR, reg, out, len); }
static int b_write(void *c, uint32_t reg, uint32_t v) { (void)c; return sns_bus_write(bus_s, MAG_ADDR, reg, v); }
static const struct mag_bus mbus = { b_read, b_write, f_sleep, f_log, NULL };
static void fresh_mag(void) {
	fresh(); w.pscl = 67; w.psda = 68; w.present[0x30] = 1; w.present[0x68] = 0;
	/* +0.5 G on part x, -0.25 G on y, null on z: 20-bit unsigned, null 524288 */
	uint32_t u[3] = { 524288 + 8192, 524288 - 4096, 524288 };
	for (int i = 0; i < 3; i++) { w.mreg[2 * i] = (uint8_t)(u[i] >> 12); w.mreg[2 * i + 1] = (uint8_t)(u[i] >> 4); w.mreg[6 + i] = (uint8_t)((u[i] & 0xf) << 4); }
	w.mreg[0x18] = 0x10;
}
int main(void) {
	const char *name;
	struct mag m;
	int32_t nt[3];

	/* the compass bus alone (rails off at entry: this run owns them) */
	name = "compass stream"; fresh_mag(); go(SNS_MODE_STREAM_MAG); CHECK(s.stop == SNS_OK && s.bus_ready && s.on_18 && s.on_33 && s.pad_scl == 67 && s.pad_sda == 68);
	bus_s = &s; CHECK(mag_start(&m, &mbus) == 0 && m.id == 0x11 && m.status_first == 0x10);
	CHECK(w.nmw == 2 && w.mwrites[0][0] == 0x1b && w.mwrites[0][1] == 0x08 && w.mwrites[1][0] == 0x1b && w.mwrites[1][1] == 0x21);
	for (int i = 0; i < 5; i++) { w.mreg[8] ^= 0x10; CHECK(mag_sample(&m, 0, nt)); }
	CHECK(nt[0] == 25000 && nt[1] == -50000 && (nt[2] == -6 || nt[2] == 0));
	CHECK(w.nmw == 7 && w.mwrites[6][1] == 0x21 && w.bytes[0] == 0x60);
	/* every frame on the wire addressed 0x30 only, never 0x7e (I3C switch) nor 0x68 */
	for (int i = 0; i < w.nbytes; i++) CHECK(w.bytes[i] != 0xfc && w.bytes[i] != 0xfd && w.bytes[i] != 0xd0);
	/* allowlist: other registers, other values, other addresses are refused and stop the bus */
	{ uint8_t b; struct sns keep = s; CHECK(sns_bus_read(&s, 0x30, 0x1c, &b, 1) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_write(&s, 0x30, 0x1c, 0x80) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_write(&s, 0x30, 0x1b, 0x40) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_write(&s, 0x30, 0x1a, 0x01) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_read(&s, 0x68, 0x72, &b, 1) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_read(&s, 0x68, 0x39, &b, 1) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_read(&s, 0x68, 0x00, &b, 9) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_read(&s, 0x30, 0x00, &b, 1) == SNS_STOP_REFUSED_I2C); s = keep;
	  CHECK(sns_bus_write(&s, 0x7e, 0x1b, 0x21) == SNS_STOP_REFUSED_I2C); s = keep; }
	sns_down(&s); CHECK(s.rails_off && s.pads_restored && !s.bus_ready);
	CHECK(w.tx[0] == 1 && w.tx[1] == 1 && w.param[0] == 0x100 && w.param[1] == 0x100 && !w.bad_page && w.polled_unlocked == 0 && w.pad_write_after_off == 0);
	{ uint8_t b; CHECK(sns_bus_read(&s, 0x30, 0x39, &b, 1) != 0); }

	/* rails already on (the IMU's): the compass leaves them on */
	name = "compass after imu"; fresh_mag(); w.rail_18 = w.rail_33 = 1; go(SNS_MODE_STREAM_MAG); CHECK(s.stop == SNS_OK && !s.on_18 && !s.on_33 && s.ldo18_was == 1);
	bus_s = &s; CHECK(mag_start(&m, &mbus) == 0); sns_down(&s); CHECK(w.rail_18 && w.rail_33 && s.pads_restored && w.nrail == 0);

	/* wrong id: no register write reaches the part */
	name = "compass id"; fresh_mag(); w.mid_bad = 1; go(SNS_MODE_STREAM_MAG); bus_s = &s; CHECK(mag_start(&m, &mbus) == MAG_STOP_ID && w.nmw == 0 && w.writes == 0); sns_down(&s); CHECK(s.rails_off && s.pads_restored);
	/* no part: NACK on the address stops at the id */
	name = "compass absent"; fresh_mag(); w.present[0x30] = 0; go(SNS_MODE_STREAM_MAG); bus_s = &s; CHECK(mag_start(&m, &mbus) == MAG_STOP_BUS && s.stop == SNS_STOP_NO_ACK_ADDR && w.nmw == 0); sns_down(&s); CHECK(s.rails_off && s.pads_restored);
	/* pad not GPIO at entry: nothing changes, no bus */
	name = "compass pad muxed"; fresh_mag(); w.dm[0] = 2; go(SNS_MODE_STREAM_MAG); CHECK(s.stop == SNS_STOP_PAD_NOT_GPIO && !s.bus_ready && w.nrail == 0 && w.pad_writes == 0);
	/* AoC woke mid-stream: still_idle stops */
	name = "compass aoc"; fresh_mag(); go(SNS_MODE_STREAM_MAG); bus_s = &s; CHECK(mag_start(&m, &mbus) == 0); w.dm[1] = 2; CHECK(!sns_still_idle(&s) && s.stop == SNS_STOP_AOC_WOKE); CHECK(!mag_sample(&m, 0, nt)); sns_down(&s);
	/* the IMU modes cannot reach the compass, and the compass mode cannot reach the IMU */
	name = "imu mode"; fresh(); go(SNS_MODE_STREAM); { uint8_t b; CHECK(s.stop == SNS_OK); CHECK(sns_bus_read(&s, 0x30, 0x39, &b, 1) == SNS_STOP_REFUSED_I2C); } sns_down(&s);
	name = "census i3c0"; fresh_mag(); go(SNS_MODE_CENSUS_I3C0); CHECK(s.stop == SNS_OK && s.census_seen == 1 && w.nmw == 0 && !s.bus_ready);
	printf("bench_mag ok\n");
	return 0;
}
