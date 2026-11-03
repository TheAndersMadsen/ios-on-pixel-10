/* Host test of the report-only charger reader (hk-chg1): blazer_charger.h decoding against the vendor driver's get_* formulas,
 * and the real blazer_gauge.c run against a fake SPMI master that records every frame it sends.
 *   cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -DBLAZER_GAUGE_HOST -I tests -I <xnu>/iokit/Kernel/arm \
 *      tests/test_charger.c <xnu>/iokit/Kernel/arm/blazer_gauge.c -o /tmp/test_charger && /tmp/test_charger
 */
#include "host_shim.h"
#include "blazer_gauge.h"
#include "blazer_charger.h"
#include <regex.h>

uint32_t fake_spmi[0x300 / 4];
struct fake_frame fake_frames[4096];
unsigned fake_nframes;
uint16_t fake_gauge[256];
uint8_t fake_chg[256];
int fake_err_sid = -1, fake_err_reg = -1;
char fake_log[1 << 16];
size_t fake_log_len;
const char *fake_args[16];
static unsigned checks, fails;

#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; fprintf(stderr, "FAIL %s:%d: ", __FILE__, __LINE__); fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } } while (0)

int
printf_shim(const char *fmt, ...)
{
	va_list ap;
	int n;

	va_start(ap, fmt);
	n = vsnprintf(fake_log + fake_log_len, sizeof(fake_log) - fake_log_len, fmt, ap);
	va_end(ap);
	if (n > 0) {
		fake_log_len += (size_t)n;
		if (fake_log_len >= sizeof(fake_log)) {
			fake_log_len = sizeof(fake_log) - 1;
		}
	}
	return n;
}

void
IOSleep(unsigned ms)
{
	(void)ms;
}

void
panic(const char *fmt, ...)
{
	(void)fmt;
	fprintf(stderr, "panic\n");
	abort();
}

vm_offset_t
ml_io_map(vm_offset_t pa, vm_size_t size)
{
	(void)pa;
	(void)size;
	return (vm_offset_t)fake_spmi;
}

bool
PE_parse_boot_argn(const char *name, void *out, int size)
{
	size_t n = strlen(name);

	for (int i = 0; i < 16 && fake_args[i]; i++) {
		if (!strncmp(fake_args[i], name, n) && fake_args[i][n] == '=') {
			uint32_t v = (uint32_t)strtoul(fake_args[i] + n + 1, 0, 0);
			memcpy(out, &v, (size_t)size < sizeof(v) ? (size_t)size : sizeof(v));
			return true;
		}
	}
	return false;
}

void
delay(unsigned us)
{
	(void)us;
}

uint32_t
host_spmi_rd(uint32_t off)
{
	return fake_spmi[off / 4];
}

/* IRQ_STATUS is write-1-to-clear; a REQ_COMMAND word with bit 0 (new command) is one transfer, answered at once. */
void
host_spmi_wr(uint32_t off, uint32_t w)
{
	struct fake_frame f;
	uint32_t data = 0;

	if (off == 0x08) {
		fake_spmi[0x08 / 4] &= ~w;
		return;
	}
	fake_spmi[off / 4] = w;
	if (off != 0x10 || !(w & 1u)) {
		return;
	}
	f.op = (w >> 2) & 0x1fu;
	f.sid = (w >> 7) & 0xfu;
	f.bytes = ((w >> 11) & 0xfu) + 1u;
	f.reg = (w >> 15) & 0xffu;
	if (fake_nframes < 4096) {
		fake_frames[fake_nframes++] = f;
	}
	if (f.op != 3) {
		fake_spmi[0x08 / 4] = 1u | (1u << 3);   /* anything but a read: error, and the test fails on the opcode */
		return;
	}
	if (f.sid == 6) {
		data = fake_gauge[f.reg];
	} else if (f.sid == 3) {
		for (unsigned b = 0; b < f.bytes; b++) {
			data |= (uint32_t)fake_chg[(f.reg + b) & 0xffu] << (8 * b);
		}
	}
	fake_spmi[0x14 / 4] = data;
	fake_spmi[0x08 / 4] = 1u | (((int)f.sid == fake_err_sid && (int)f.reg == fake_err_reg) ? (1u << 2) : 0u);
}

/* Independent copies of the vendor's get_* functions, written from max77779_charger.c in uA/uV, for the decode check. */
static int
v_cc_ua(unsigned value)
{
	value &= 0x3f;
	if (value == 0) return 0;
	if (value < 3) return 133 * 1000;
	if (value >= 0x3C) return 4000 * 1000;
	return 133000 + ((int)value - 2) * 66670;
}

static int
v_cv_uv(unsigned value, int *uv)
{
	value &= 0x3f;
	if (value < 0x38) *uv = (4000 + (int)value * 10) * 1000;
	else if (value == 0x38) *uv = 3800 * 1000;
	else if (value == 0x39) *uv = 3900 * 1000;
	else return -1;
	return 0;
}

static int
v_icl_ua(unsigned value)
{
	int icl;

	value &= 0x7f;
	if (value == 0) icl = 0;
	else if (value > 3) icl = 100 + ((int)value - 3) * 25;
	else icl = 100;
	return icl * 1000;
}

static int
v_wicl_ua(unsigned value)
{
	value &= 0x7f;
	if (value == 0) return 0;
	if (value < 4) return 100000;
	return 125000 + ((int)value - 4) * 25000;
}

static void
test_decode(void)
{
	for (unsigned b = 0; b < 256; b++) {
		uint32_t mv;
		int uv;
		bool ok = blazer_charger_cv_mv((uint8_t)b, &mv);

		CHECK(blazer_charger_cc_ma((uint8_t)b) == (uint32_t)(v_cc_ua(b) / 1000), "cc %02x: %u vs %d", b, blazer_charger_cc_ma((uint8_t)b), v_cc_ua(b));
		CHECK(ok == (v_cv_uv(b, &uv) == 0), "cv valid %02x", b);
		if (ok) {
			CHECK(mv * 1000u == (uint32_t)uv, "cv %02x: %u vs %d", b, mv, uv);
		}
		CHECK(blazer_charger_icl_ma((uint8_t)b) * 1000u == (uint32_t)v_icl_ua(b), "icl %02x", b);
		CHECK(blazer_charger_wicl_ma((uint8_t)b) * 1000u == (uint32_t)v_wicl_ua(b), "wicl %02x", b);
	}
	/* Inputs: DTLS0 CHGIN bits 6:5, WCIN bits 4:3; 2 and 3 are valid (max77779_is_online). */
	for (unsigned c = 0; c < 4; c++) {
		for (unsigned w = 0; w < 4; w++) {
			struct blazer_charger_regs r = { .d0 = (uint8_t)(c << 5 | w << 3), .d1 = 0x01 };
			struct blazer_charger_view v;
			const char *want = c >= 2 ? (w >= 2 ? "both" : "usb") : (w >= 2 ? "wireless" : "none");

			blazer_charger_decode(&r, &v);
			CHECK(!strcmp(blazer_charger_in_name(&v), want), "in c%u w%u: %s", c, w, blazer_charger_in_name(&v));
			CHECK(v.charging == (c >= 2 || w >= 2), "charging c%u w%u", c, w);
		}
	}
	for (unsigned d = 0; d < 16; d++) {
		struct blazer_charger_regs r = { .d0 = 3 << 5, .d1 = (uint8_t)(0x30 | d) };
		struct blazer_charger_view v;

		blazer_charger_decode(&r, &v);
		CHECK(v.chg_dtls == d && v.bat_dtls == 3, "dtls %u", d);
		CHECK(v.charging == (d <= 3), "charging dtls %u", d);
		CHECK((blazer_charger_chg_name(d) != 0) == (d != 5 && d != 9 && d != 0xe && d != 0xf), "name %u", d);
	}
	{
		struct blazer_charger_regs r = { .cnfg00 = 0x25, .cnfg15 = 0x01, .chgin_i = 6024, .wcin_i = 0, .wcin_v = 8000 };
		struct blazer_charger_view v;

		blazer_charger_decode(&r, &v);
		CHECK(v.mode == 5 && v.cp_en && v.wdt_en, "cnfg00/15");
		CHECK(v.ichgin_ma == 999 && v.vwcin_mv == 5000, "adc %u %u", v.ichgin_ma, v.vwcin_mv);
	}
}

static void
seed(void)
{
	memset(fake_spmi, 0, sizeof(fake_spmi));
	fake_spmi[0] = 0x00010191u; /* ABL's CONTROL */
	memset(fake_gauge, 0, sizeof(fake_gauge));
	fake_gauge[0x21] = 0x5100;
	fake_gauge[0x07] = 89 << 8;
	fake_gauge[0x1a] = (uint16_t)(4334ull * 1000000 / 78125);  /* 4334 mV */
	fake_gauge[0x1c] = 600;  /* ~468 mA in */
	fake_gauge[0x1d] = 600;
	fake_gauge[0x1b] = 30 << 8;
	fake_gauge[0x3d] = 0;
	memset(fake_chg, 0xee, sizeof(fake_chg)); /* anything unread would show */
	fake_chg[0xb6] = 0xd8;
	fake_chg[0xb7] = 3 << 5;        /* CHGIN valid, WCIN absent */
	fake_chg[0xb8] = 0x31;          /* bat ok-ish, CC */
	fake_chg[0xb9] = 0x20;
	fake_chg[0xba] = 0x00;
	fake_chg[0xbc] = 0x05;          /* CHGR_BUCK_ON */
	fake_chg[0xbe] = 0x1c;          /* 133000 + 26 * 66670 = 1866 mA */
	fake_chg[0xc0] = 0x2d;          /* 4450 mV */
	fake_chg[0xc5] = 0x3f;          /* 100 + 60*25 = 1600 mA */
	fake_chg[0xc6] = 0x04;          /* 125 mA */
	fake_chg[0xcb] = 0x00;
	fake_chg[0x00] = 0x88; fake_chg[0x01] = 0x13;   /* 5000 * 166 uA = 830 mA */
	fake_chg[0x02] = 0x34; fake_chg[0x03] = 0x12;
	fake_chg[0x04] = 0x00; fake_chg[0x05] = 0x00;
	fake_chg[0x06] = 0x00; fake_chg[0x07] = 0x00;
	fake_nframes = 0;
	fake_log_len = 0;
	fake_log[0] = 0;
	fake_err_sid = fake_err_reg = -1;
}

/* blazer_gauge.c keeps file statics, so each mode runs in its own process. */
static int
run_mode(const char *chg, struct blazer_gauge_sample *out, unsigned samples)
{
	bool ok = true;

	seed();
	fake_args[0] = "blazer_battery=1";
	fake_args[1] = chg;
	fake_args[2] = 0;
	CHECK(blazer_gauge_start(), "start");
	for (unsigned i = 0; i < samples; i++) {
		ok = blazer_gauge_read(out) && ok;
	}
	return ok;
}

static bool
matches(const char *re, const char *s)
{
	regex_t r;
	bool m;

	if (regcomp(&r, re, REG_EXTENDED | REG_NOSUB)) {
		return false;
	}
	m = regexec(&r, s, 0, 0, 0) == 0;
	regfree(&r);
	return m;
}

static int
child(const char *which)
{
	struct blazer_gauge_sample s;
	unsigned sid3 = 0;

	memset(&s, 0, sizeof(s));
	if (!strcmp(which, "decode")) {
		test_decode();
	} else if (!strcmp(which, "chg0") || !strcmp(which, "chg1") || !strcmp(which, "chg2") || !strcmp(which, "chg3")) {
		const char *arg = !strcmp(which, "chg0") ? "x=0" : !strcmp(which, "chg1") ? "blazer_battery_chg=1" :
		    !strcmp(which, "chg2") ? "blazer_battery_chg=2" : "blazer_battery_chg=3";

		CHECK(run_mode(arg, &s, 2), "%s samples", which);
		for (unsigned i = 0; i < fake_nframes; i++) {
			struct fake_frame f = fake_frames[i];

			CHECK(f.op == 3, "%s frame %u opcode %u", which, i, f.op);
			CHECK(f.sid == 6 || f.sid == 3, "%s sid %u", which, f.sid);
			if (f.sid == 3) {
				sid3++;
				CHECK(f.reg != 0xb0 && f.reg != 0xb1 && f.reg != 0xb3 && f.reg != 0xb4, "%s read a latch/mask %02x", which, f.reg);
				if (!strcmp(which, "chg1")) {
					CHECK(f.reg >= 0xb6 && f.reg <= 0xb9 && f.bytes == 1, "chg1 reg %02x", f.reg);
				} else {
					bool named = (f.reg >= 0xb6 && f.reg <= 0xba && f.bytes == 1) || f.reg == 0xbc || f.reg == 0xbe || f.reg == 0xc0 ||
					    f.reg == 0xc5 || f.reg == 0xc6 || f.reg == 0xcb || ((f.reg <= 6 && !(f.reg & 1)) && f.bytes == 2);
					CHECK(named, "chg2 reg %02x bytes %u", f.reg, f.bytes);
				}
			}
		}
		/* What iOS is told: chg=2 must equal chg=0 (current-inferred, external stays true). */
		if (!strcmp(which, "chg0") || !strcmp(which, "chg2") || !strcmp(which, "chg3")) {
			CHECK(s.external && s.charging && !s.full && !s.charger_read, "%s published state %d %d %d %d", which, s.external, s.charging, s.full, s.charger_read);
		}
		if (!strcmp(which, "chg0") || !strcmp(which, "chg3")) {
			CHECK(sid3 == 0, "%s sent %u charger frames", which, sid3);
		}
		if (!strcmp(which, "chg3")) {
			CHECK(strstr(fake_log, "blazer_battery_chg=3 means nothing") != 0, "chg3 refusal line");
		}
		if (!strcmp(which, "chg1")) {
			CHECK(sid3 == 8 && s.charger_read, "chg1 frames %u", sid3);
		}
		if (!strcmp(which, "chg2")) {
			CHECK(sid3 == 2 * 15, "chg2 frames %u", sid3);
			CHECK(strstr(fake_log, "charger reads report only") != 0, "start line");
			/* The probe rows' patterns (docs/probes.yaml), POSIX form. */
			CHECK(matches("blazer-battery: charger 1 in=usb chg=cc mode=5 cp=0 wdt=0 cc=1866 mA cv=4450 mV icl=1600 mA wicl=125 mA ichgin=830 mA iwcin=0 mA vwcin=0 mV vchgin_raw=1234 ok=d8 dtls=60312000 bat=3", fake_log),
			    "line:\n%s", fake_log);
			CHECK(matches("blazer-battery: charger [0-9]+ in=(usb|wireless|both|none) chg=[a-z0-9-]+ ", fake_log), "probe pattern");
			CHECK(strstr(fake_log, "charger 2 in=usb") != 0, "second report");
		}
	} else if (!strcmp(which, "wireless")) {
		seed();
		fake_chg[0xb7] = 3 << 3;        /* WCIN valid only */
		fake_chg[0x04] = 0x58; fake_chg[0x05] = 0x02;   /* 600 * 166 uA = 99 mA */
		fake_chg[0x06] = 0x40; fake_chg[0x07] = 0x1f;   /* 8000 * 625 uV = 5000 mV */
		fake_chg[0xbc] = 0x0e;
		fake_args[0] = "blazer_battery=1"; fake_args[1] = "blazer_battery_chg=2"; fake_args[2] = 0;
		blazer_gauge_start();
		CHECK(blazer_gauge_read(&s), "wireless sample");
		CHECK(strstr(fake_log, "in=wireless chg=cc mode=e") != 0 && strstr(fake_log, "iwcin=99 mA vwcin=5000 mV") != 0, "wireless line:\n%s", fake_log);
	} else if (!strcmp(which, "adc-error")) {
		/* A charger frame answered with an error bit: no line, the gauge's sample stands, the controller is kept. */
		seed();
		fake_err_sid = 3;
		fake_err_reg = 0x04;
		fake_args[0] = "blazer_battery=1"; fake_args[1] = "blazer_battery_chg=2"; fake_args[2] = 0;
		blazer_gauge_start();
		CHECK(blazer_gauge_read(&s) && s.percent == 89, "gauge sample survives");
		CHECK(strstr(fake_log, "charger report 1 unread") != 0 && strstr(fake_log, "in=usb") == 0, "unread line");
		CHECK(!blazer_gauge_gave_up(), "controller kept");
		CHECK(blazer_gauge_read(&s), "second sample");
	} else if (!strcmp(which, "badcv")) {
		seed();
		fake_chg[0xc0] = 0x3a;
		fake_args[0] = "blazer_battery=1"; fake_args[1] = "blazer_battery_chg=2"; fake_args[2] = 0;
		blazer_gauge_start();
		CHECK(blazer_gauge_read(&s), "sample");
		CHECK(strstr(fake_log, "CHG_CV_PRM 3a has no voltage") != 0 && strstr(fake_log, "cv=0 mV") != 0, "badcv:\n%s", fake_log);
	} else {
		return 2;
	}
	printf("%s: %u checks, %u failed\n", which, checks, fails);
	fprintf(stderr, "%s: %u checks, %u failed\n", which, checks, fails);
	return fails != 0;
}

int
main(int argc, char **argv)
{
	static const char *const all[] = { "decode", "chg0", "chg1", "chg2", "chg3", "wireless", "adc-error", "badcv" };
	char cmd[4096];
	int bad = 0;

	if (argc == 2) {
		return child(argv[1]);
	}
	for (unsigned i = 0; i < sizeof(all) / sizeof(all[0]); i++) {
		snprintf(cmd, sizeof(cmd), "'%s' %s", argv[0], all[i]);
		bad |= system(cmd) != 0;
	}
	fprintf(stderr, bad ? "FAIL\n" : "PASS\n");
	return bad;
}
