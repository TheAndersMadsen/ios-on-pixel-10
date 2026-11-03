/* SPDX-License-Identifier: MIT
 * Host test of blazer_torch_hw.c (hk-cam1): the exact file, against a register model of the MBA polled page, CLI7, the four pads,
 * the DesignWare I2C controller and an LM3644 (SNVSA52E register map, HWEN reset). The model tracks LED on-time in simulated time.
 *   cc -std=c11 -Wall -Wextra -Werror -DBLAZER_TORCH_HOST_TEST -I../xnu-src/bsd/dev test_blazer_torch.c -o t && ./t [--log]
 * Prints one PASS/FAIL line per case and "RESULT: PASS (n/n cases)". --log echoes the probe's own lines (the stage 4 case's are the
 * fixture for docs/probes.yaml's flash probe). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../xnu-src/bsd/dev/blazer_torch_hw.c"

struct sim {
	/* MBA */
	uint32_t mba_st, mba_ctl, mba_msg[4], lsio_state;
	/* CLI7, pads */
	uint32_t cli[3];
	uint32_t pad_dmux[4], pad_tx[4], pad_rx[4];     /* scl sda en strobe */
	uint32_t line_rx;                               /* what SCL/SDA read when muxed and the bus is idle */
	/* DW I2C */
	uint32_t ic_enable, ic_con, ic_tar, ic_regs[64], raw, abrt, rx[8], nrx, state, ptr, txn_nak;
	/* LM3644 */
	uint8_t reg[16];
	uint32_t id, chip_present, nak_after_writes, fault_on_torch, nak_flags_when_lit, chip_writes, wlog[64][2];
	bool hwen;
	/* time and LEDs */
	uint64_t now_us, on_us[2], cur_on_us[2], max_on_us[2];
	uint32_t both_on, bad_writes, mmio_writes_outside_mba;
	char log[16384];
	size_t loglen;
};
static struct sim S;
static int echo_log;

#define PADS_BASE_E 0x3a200000ULL
static int
pad_index(uint64_t pa, uint32_t *off)
{
	static const uint64_t base[4] = { PAD_SCL, PAD_SDA, PAD_EN, PAD_STROBE };

	for (int i = 0; i < 4; i++) {
		if (pa >= base[i] && pa < base[i] + 0x14) {
			*off = (uint32_t)(pa - base[i]);
			return i;
		}
	}
	return -1;
}

static void
chip_reset(void)
{
	static const uint8_t r[16] = { 0, 0x80, 0x01, 0xbf, 0x3f, 0xbf, 0x3f, 0x09, 0x1a, 0x08, 0, 0, 0, 0, 0, 0 };

	memcpy(S.reg, r, sizeof(r));
	S.reg[0x0c] = (uint8_t)S.id;
}

static bool led_on(int led) { return S.hwen && (S.reg[1] & 0x0c) == 0x08 && (S.reg[1] & (led ? 2 : 1)); }

static void
update_hwen(void)
{
	bool h = (S.pad_tx[2] & TX_OE) && (S.pad_tx[2] & TX_DOUT) && S.pad_dmux[2] == DMUX_GPIO;

	if (S.hwen && !h) {
		chip_reset();   /* HWEN low = shutdown/reset */
	}
	S.hwen = h;
}

static bool
chip_acks(void)
{
	return S.chip_present && S.hwen && S.cli[0] == CLI_IPTYPE_I2C && S.pad_dmux[0] == DMUX_CLI7 && S.pad_dmux[1] == DMUX_CLI7 && S.ic_enable &&
	    S.ic_tar == CHIP_ADDR && (S.nak_after_writes == 0 || S.chip_writes < S.nak_after_writes);
}

static void
chip_write_reg(uint32_t r, uint32_t v)
{
	if (S.chip_writes < 64) {
		S.wlog[S.chip_writes][0] = r;
		S.wlog[S.chip_writes][1] = v;
	}
	S.chip_writes++;
	if (r < 16 && r != 0x0a && r != 0x0b && r != 0x0c) {
		S.reg[r] = (uint8_t)v;
	}
	if (r == 1 && (v & 0x0c) == 0x08 && S.fault_on_torch) {
		S.reg[0x0a] |= (uint8_t)S.fault_on_torch;       /* fault: chip drops to standby itself */
		S.reg[1] &= ~0x0fu;
	}
}

static void
i2c_data(uint32_t w)
{
	if (S.state == 0) {
		S.txn_nak = !chip_acks();
	}
	if (w & CMD_READ) {
		if (S.nak_flags_when_lit && (S.ptr & 0xf) == 0x0a && led_on(0)) {
			S.txn_nak = 1;  /* the read fails, writes still work */
		}
		if (!S.txn_nak && S.nrx < 8) {
			uint32_t r = S.ptr & 0xf;

			S.rx[S.nrx++] = S.reg[r];
			if (r == 0x0a || r == 0x0b) {
				S.reg[r] = 0;   /* read clears */
			}
			S.ptr++;
		}
		S.state = 2;
	} else if (S.state == 0) {
		S.ptr = w & 0xff;
		S.state = 1;
	} else {
		if (!S.txn_nak) {
			chip_write_reg(S.ptr & 0xf, w & 0xff);
		}
		S.ptr++;
		S.state = 2;
	}
	if (w & CMD_STOP) {
		if (S.txn_nak) {
			S.raw |= INTR_ABRT;
			S.abrt = 1;     /* 7-bit address NAK */
		}
		S.raw |= INTR_STOP;
		S.state = 0;
	}
}

static int
m_read32(void *ctx, uint64_t pa, uint32_t *v)
{
	uint32_t off;
	int p;

	(void)ctx;
	if (pa == MBA_MAGIC_PA) { *v = MBA_MAGIC; return 0; }
	if (pa >= MBA_PAGE && pa < MBA_PAGE + MBA_MSG + 16) {
		off = (uint32_t)(pa - MBA_PAGE);
		*v = off == MBA_ST ? S.mba_st : off == MBA_CTL ? S.mba_ctl : off >= MBA_MSG ? S.mba_msg[(off - MBA_MSG) / 4] : 0;
		return 0;
	}
	if (pa >= CLI_CONF && pa < CLI_CONF + 12) { *v = S.cli[(pa - CLI_CONF) / 4]; return 0; }
	if ((p = pad_index(pa, &off)) >= 0) {
		if (off == P_DMUX) *v = S.pad_dmux[p];
		else if (off == P_TX) *v = S.pad_tx[p];
		else if (off == P_RX) *v = (p < 2 && S.pad_dmux[p] == DMUX_CLI7) ? S.line_rx : S.pad_rx[p];
		else *v = 0;
		return 0;
	}
	if (pa >= I2C && pa < I2C + 0x100) {
		off = (uint32_t)(pa - I2C);
		switch (off) {
		case IC_COMP_TYPE: *v = COMP_TYPE_DW; break;
		case IC_COMP_VERSION: *v = 0x3230312a; break;
		case IC_ENABLE: *v = S.ic_enable; break;
		case IC_EN_STATUS: *v = S.ic_enable; break;
		case IC_CON: *v = S.ic_con; break;
		case IC_STATUS: *v = ST_TFNF | (S.nrx ? ST_RFNE : 0); break;
		case IC_RAW_INTR: *v = S.raw; break;
		case IC_ABRT_SOURCE: *v = S.abrt; break;
		case IC_CLR_TX_ABRT: S.raw &= ~INTR_ABRT; *v = 0; break;
		case IC_CLR_STOP: S.raw &= ~INTR_STOP; *v = 0; break;
		case IC_DATA_CMD:
			*v = S.nrx ? S.rx[0] : 0;
			if (S.nrx) { memmove(S.rx, S.rx + 1, sizeof(S.rx) - sizeof(S.rx[0])); S.nrx--; }
			break;
		default: *v = S.ic_regs[off / 4]; break;
		}
		return 0;
	}
	return -1;
}

static int
m_write32(void *ctx, uint64_t pa, uint32_t v)
{
	uint32_t off;
	int p;

	(void)ctx;
	if (pa >= MBA_PAGE && pa < MBA_PAGE + MBA_MSG + 16) {
		off = (uint32_t)(pa - MBA_PAGE);
		if (off == MBA_ST) { if (v & 1) S.mba_st &= ~1u; }
		else if (off == MBA_CTL) S.mba_ctl = v;
		else if (off >= MBA_MSG) S.mba_msg[(off - MBA_MSG) / 4] = v;
		else if (off == MBA_GO && v == 1) {
			uint32_t w0 = S.mba_msg[0], w1 = S.mba_msg[1];

			S.mba_msg[0] = w0 | MBA_REPLY_BIT;
			S.mba_msg[1] = w0 == LPB_GET ? S.lsio_state : (w1 == I2C_CLK_RATE ? I2C_CLK_HZ : 0);
			S.mba_st |= 1;
		}
		return 0;
	}
	S.mmio_writes_outside_mba++;
	if (pa >= CLI_CONF && pa < CLI_CONF + 12) { S.cli[(pa - CLI_CONF) / 4] = v; return 0; }
	if ((p = pad_index(pa, &off)) >= 0) {
		if (off == P_DMUX) S.pad_dmux[p] = v;
		else if (off == P_TX) S.pad_tx[p] = v;
		else S.bad_writes++;
		update_hwen();
		return 0;
	}
	if (pa >= I2C && pa < I2C + 0x100) {
		off = (uint32_t)(pa - I2C);
		if (off == IC_ENABLE) S.ic_enable = v & 1;
		else if (off == IC_CON) S.ic_con = v;
		else if (off == IC_TAR) S.ic_tar = v;
		else if (off == IC_DATA_CMD) i2c_data(v);
		else S.ic_regs[off / 4] = v;
		return 0;
	}
	S.bad_writes++;
	return -1;
}

static void
m_smc(void *ctx, uint64_t fn, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t r[2])
{
	(void)ctx; (void)fn; (void)a1; (void)a2; (void)a3;
	r[0] = r[1] = 0;
}

static void
m_delay_us(void *ctx, uint32_t us)
{
	(void)ctx;
	S.now_us += us;
	if (led_on(0) && led_on(1)) S.both_on++;
	for (int l = 0; l < 2; l++) {
		if (led_on(l)) {
			S.on_us[l] += us;
			S.cur_on_us[l] += us;
			if (S.cur_on_us[l] > S.max_on_us[l]) S.max_on_us[l] = S.cur_on_us[l];
		} else {
			S.cur_on_us[l] = 0;
		}
	}
}

static void
m_log(void *ctx, const char *fmt, ...)
{
	va_list ap;
	int n;

	(void)ctx;
	n = snprintf(S.log + S.loglen, sizeof(S.log) - S.loglen, "blazer-torch: ");
	if (n > 0) S.loglen += (size_t)n;
	va_start(ap, fmt);
	n = vsnprintf(S.log + S.loglen, sizeof(S.log) - S.loglen, fmt, ap);
	va_end(ap);
	if (n > 0) S.loglen += (size_t)n;
	if (S.loglen >= sizeof(S.log)) S.loglen = sizeof(S.log) - 1;
}

static int cpm_depth, cpm_bad;
static void m_enter(void *ctx) { (void)ctx; if (cpm_depth++) cpm_bad++; }
static void m_exit(void *ctx) { (void)ctx; if (--cpm_depth) cpm_bad++; }

static const struct bt_ops OPS = { m_read32, m_write32, m_smc, m_delay_us, m_log, m_enter, m_exit, NULL };

/* The phone as torch-1-r1 found it: CLI7 "2,1,1", LSIO_E/S on. Pads: GPIO, EN low and not driven */
static void
sim_reset(void)
{
	memset(&S, 0, sizeof(S));
	S.lsio_state = 2;
	S.cli[0] = 2; S.cli[1] = 1; S.cli[2] = 1;
	for (int i = 0; i < 4; i++) S.pad_dmux[i] = DMUX_GPIO;
	S.pad_tx[2] = 0;        /* EN: input, low */
	S.pad_rx[0] = S.pad_rx[1] = 1;
	S.line_rx = 1;
	S.id = ID_LM3644;
	S.chip_present = 1;
	chip_reset();
	cpm_depth = cpm_bad = 0;
}

static int fails, cases;
#define CHECK(c) do { if (!(c)) { printf("    check failed: %s (line %d)\n", #c, __LINE__); ok = 0; } } while (0)

static int
restored(void)
{
	return S.cli[0] == 2 && S.cli[1] == 1 && S.cli[2] == 1 && S.pad_dmux[0] == DMUX_GPIO && S.pad_dmux[1] == DMUX_GPIO && S.pad_tx[2] == 0 &&
	    !S.hwen && S.ic_enable == 0 && !led_on(0) && !led_on(1) && cpm_depth == 0 && cpm_bad == 0;
}

static struct bt T;
static int
run(uint32_t stage, uint32_t ms)
{
	bt_init(&T, &OPS, stage, ms);
	return bt_run(&T);
}

static void
report(const char *name, int ok)
{
	cases++;
	if (!ok) fails++;
	printf("%s %s\n", ok ? "PASS" : "FAIL", name);
	if (echo_log || !ok) fputs(S.log, stdout);
}

static int
chip_writes_are(const uint32_t (*w)[2], uint32_t n)
{
	if (S.chip_writes != n) return 0;
	for (uint32_t i = 0; i < n; i++) if (S.wlog[i][0] != w[i][0] || S.wlog[i][1] != w[i][1]) return 0;
	return 1;
}

int
main(int argc, char **argv)
{
	int ok;
	echo_log = argc > 1 && !strcmp(argv[1], "--log");

	/* 1. Stage 1 on torch-1-r1's state: stop cli, pad inventory, nothing written but MBA */
	sim_reset(); ok = 1;
	CHECK(run(1, 0) == BT_STOP_CLI); CHECK(S.mmio_writes_outside_mba == 0); CHECK(restored()); CHECK(S.on_us[0] + S.on_us[1] == 0);
	CHECK(strstr(S.log, "cli was 2,1,1") && strstr(S.log, "pad inventory only"));
	report("stage1-uart-readonly", ok);

	/* 2. Stage 2 behaves as p1 did: no select */
	sim_reset(); ok = 1;
	CHECK(run(2, 0) == BT_STOP_CLI); CHECK(S.mmio_writes_outside_mba == 0); CHECK(restored());
	report("stage2-uart-unchanged", ok);

	/* 3. Stage 3: select, mux, ID read, no chip write, everything back */
	sim_reset(); ok = 1;
	CHECK(run(3, 0) == BT_OK); CHECK(T.answered && T.device_id == 0x02 && T.enable_reg == 0x80); CHECK(S.chip_writes == 0);
	CHECK(restored()); CHECK(S.on_us[0] + S.on_us[1] == 0);
	CHECK(strstr(S.log, "cli select uart -> i2c") && strstr(S.log, "pads muxed to cli7") && strstr(S.log, "chip answered: id register 0x2"));
	report("stage3-select-id", ok);

	/* 4. Stage 4: LED1 then LED2, 2000 ms each, never together, exact write list, everything back */
	sim_reset(); ok = 1;
	{
		static const uint32_t want[][2] = { {5, 8}, {1, 0x89}, {1, 0x80}, {6, 8}, {1, 0x8a}, {1, 0x80}, {5, 0xbf}, {6, 0x3f} };

		CHECK(run(4, 0) == BT_OK); CHECK(chip_writes_are(want, 8));
		if (!chip_writes_are(want, 8)) for (uint32_t i = 0; i < S.chip_writes && i < 64; i++) printf("    write %u: 0x%02x = 0x%02x\n", i, S.wlog[i][0], S.wlog[i][1]);
		CHECK(S.on_us[0] == 2000000 && S.on_us[1] == 2000000); CHECK(S.both_on == 0); CHECK(T.lit_ms[0] == 2000 && T.lit_ms[1] == 2000);
		CHECK(restored()); CHECK(S.reg[1] == 0x80 && S.reg[5] == 0xbf);
		CHECK(strstr(S.log, "led1 on: torch code 0x8, enable 0x89, for 2000 ms") && strstr(S.log, "led2 off: standby, 2000 ms lit, flags 0x0 0x0"));
	}
	report("stage4-torch-both-leds", ok);

	/* 5. LM3644TT id 0x04 is accepted, ms clamp 5000 */
	sim_reset(); S.id = ID_LM3644TT; chip_reset(); ok = 1;
	CHECK(run(4, 5000) == BT_OK); CHECK(S.on_us[0] == 5000000 && S.max_on_us[0] == 5000000); CHECK(restored());
	report("stage4-tt-5000ms", ok);

	/* 6. Unknown id: no chip write at all */
	sim_reset(); S.id = 0x03; chip_reset(); ok = 1;
	CHECK(run(4, 0) == BT_STOP_NOT_LM3644); CHECK(S.chip_writes == 0); CHECK(restored());
	report("stage4-unknown-id-no-write", ok);

	/* 7. Enable not at reset (strobe enabled, mode standby): no chip write */
	sim_reset(); S.reg[1] = 0xa0; ok = 1;
	/* the register resets on HWEN rising? It does not in the model: HWEN low resets; start state is "someone wrote it" */
	CHECK(run(4, 0) == BT_STOP_NOT_STANDBY); CHECK(S.chip_writes == 0); CHECK(restored() || S.reg[1] == 0x80);
	report("stage4-enable-not-reset-no-write", ok);

	/* 8. Fault flag (TSD) on LED1: stop flags, LED2 never lit, LED off */
	sim_reset(); S.fault_on_torch = 0x04; ok = 1;
	CHECK(run(4, 0) == BT_STOP_FLAGS); CHECK(S.on_us[1] == 0); CHECK(restored()); CHECK(T.stop_detail == 0x0400);
	CHECK(S.chip_writes >= 3 && S.wlog[1][1] == 0x89 && S.wlog[2][0] == 1 && S.wlog[2][1] == 0x80);    /* put_back's standby before EN drops */
	report("stage4-fault-flags", ok);

	/* 9. No chip on the bus: NAK, nothing written, all back */
	sim_reset(); S.chip_present = 0; ok = 1;
	CHECK(run(4, 0) == BT_STOP_NAK); CHECK(S.chip_writes == 0); CHECK(restored());
	report("stage4-no-chip-nak", ok);

	/* 10. Bus lines low once muxed (unpowered pull-up rail): no clock, all back */
	sim_reset(); S.line_rx = 0; ok = 1;
	CHECK(run(4, 0) == BT_STOP_LINES_LOW); CHECK(S.chip_writes == 0); CHECK(restored());
	report("stage4-lines-low", ok);

	/* 11. Pad in an unknown function: nothing muxed, word 0 back to UART */
	sim_reset(); S.pad_dmux[1] = 4; ok = 1;
	CHECK(run(4, 0) == BT_STOP_PAD_NOT_I2C); CHECK(S.cli[0] == 2 && S.pad_dmux[0] == DMUX_GPIO && S.pad_dmux[1] == 4); CHECK(S.chip_writes == 0);
	report("stage4-pad-unknown", ok);

	/* 12. Chip stops answering while LED1 is lit: standby write fails, EN low turns the LED off anyway */
	sim_reset(); S.nak_after_writes = 2; ok = 1;
	CHECK(run(4, 0) == BT_STOP_NAK); CHECK(restored()); CHECK(!led_on(0)); CHECK(S.on_us[0] >= 2000000 && S.on_us[0] < 2100000 && S.on_us[1] == 0);   /* + the NAK retries' 1 ms delays before EN drops */
	report("stage4-nak-while-lit-en-off", ok);

	/* 12b. Flags read fails while LED1 is lit, the chip still takes writes: put_back's standby turns it off before EN drops */
	sim_reset(); S.nak_flags_when_lit = 1; ok = 1;
	CHECK(run(4, 0) == BT_STOP_NAK); CHECK(restored());
	CHECK(S.chip_writes == 5 && S.wlog[1][1] == 0x89 && S.wlog[2][0] == 1 && S.wlog[2][1] == 0x80 && S.wlog[3][0] == 5 && S.wlog[3][1] == 0xbf && S.wlog[4][0] == 6);
	report("stage4-flags-nak-putback-standby", ok);

	/* 13. CLI already I2C: no select, word 0 stays 1 */
	sim_reset(); S.cli[0] = 1; ok = 1;
	CHECK(run(4, 0) == BT_OK); CHECK(S.cli[0] == 1); CHECK(!strstr(S.log, "cli select"));
	report("stage4-cli-already-i2c", ok);

	/* 14. LSIO_S off: stop before anything moves */
	sim_reset(); S.lsio_state = 1; ok = 1;
	CHECK(run(4, 0) == BT_STOP_LSIOE_OFF); CHECK(S.mmio_writes_outside_mba == 0);
	report("stage4-lsio-off", ok);

	/* 15. Gates: what the allowlists refuse */
	sim_reset(); ok = 1;
	bt_init(&T, &OPS, 3, 0); T.answered = true; T.enable_reg = 0x80;
	CHECK(!write_allowed(&T, R_ENABLE, 0x80)); CHECK(!data_word_allowed(&T, 0x208));     /* stage 3: nothing arms */
	bt_init(&T, &OPS, 4, 0); T.answered = true; T.enable_reg = 0x80;
	CHECK(write_allowed(&T, R_ENABLE, 0x89) && write_allowed(&T, R_TORCH1, TORCH_CODE));
	CHECK(!write_allowed(&T, R_ENABLE, 0x8b) && !write_allowed(&T, R_ENABLE, 0x8c) && !write_allowed(&T, R_ENABLE, 0x83));   /* both LEDs, flash, IR */
	for (uint32_t v = 0; v < 0x100; v++) {      /* the enable register: exactly three values, whatever the mode bits */
		CHECK(write_allowed(&T, R_ENABLE, v) == (v == 0x80 || v == 0x89 || v == 0x8a));
	}
	CHECK(!write_allowed(&T, R_TORCH1, 0x7f) && !write_allowed(&T, 0x03, 0x01) && !write_allowed(&T, 0x07, 0x80));          /* full torch, flash code, sw reset */
	CHECK(!write_allowed(&T, R_TORCH1, 0xbf));      /* a saved value only once saved */
	CHECK(!data_word_allowed(&T, 0x03) && !data_word_allowed(&T, 0x289) && data_word_allowed(&T, 0x0c) && data_word_allowed(&T, CMD_READ | CMD_STOP));
	T.armed_reg = R_ENABLE; T.armed_val = 0x89;
	CHECK(data_word_allowed(&T, 0x289) && !data_word_allowed(&T, 0x289));    /* one value per arming */
	T.enable_reg = 0x81;
	CHECK(!write_allowed(&T, R_ENABLE, 0x80));
	bt_init(&T, &OPS, 9, 100); CHECK(T.cfg.stage == 1 && T.cfg.torch_ms == BT_TORCH_MS_DEFAULT);
	bt_init(&T, &OPS, 4, 6000); CHECK(T.cfg.torch_ms == BT_TORCH_MS_DEFAULT);
	report("gates", ok);

	/* 16. Refused write never reaches the MMIO: wr() with a stage-3 chip value */
	sim_reset(); ok = 1;
	bt_init(&T, &OPS, 3, 0);
	CHECK(wr(&T, I2C + IC_DATA_CMD, 0x289) == BT_STOP_REFUSED_BYTE); CHECK(S.mmio_writes_outside_mba == 0);
	sim_reset(); bt_init(&T, &OPS, 4, 0);
	CHECK(wr(&T, CLI_CONF, 4) == BT_STOP_REFUSED_BYTE); CHECK(S.mmio_writes_outside_mba == 0);
	sim_reset(); bt_init(&T, &OPS, 2, 0);
	CHECK(wr(&T, CLI_CONF, 1) == BT_STOP_REFUSED_PA); CHECK(wr(&T, PAD_SCL + P_DMUX, 2) != 0); CHECK(S.mmio_writes_outside_mba == 0);
	report("refusals-before-mmio", ok);

	printf("RESULT: %s (%d/%d cases)\n", fails ? "FAIL" : "PASS", cases - fails, cases);
	return fails != 0;
}
