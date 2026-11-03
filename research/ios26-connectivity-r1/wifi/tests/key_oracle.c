/* SPDX-License-Identifier: MIT
 * HOST ONLY. How the key reaches the firmware (W1 r2). Includes the real blazer_bcm4390_join.c, so its static configure() and
 * set_key() run unchanged, against a recording b4_ioctl. Synthetic networks only, made here. Prints no key or name.
 *
 * What a7-wifi-join-r1 showed (physical): a bare PMK (WLC_SET_WSEC_PMK, flags 0) left the firmware's supplicant waiting for M1.
 * The firmware (fw_bcmdhd.bin_4390_b1 + .map: wlc_keymgmt_set_wsec_pmk, wlc_join_infra, wlc_sup_set_ssid, wlc_pmk_set_psk) and
 * Android (dmesg: "Passphrase set", then "pmk added") both put the passphrase first. These checks pin that order and format.
 *
 *   key_oracle      exit 0: every case passed
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "blazer_bcm4390_join.c"

/* ---- The world around the join, recorded ---- */

#define MAX_CALLS 64
struct call {
	uint32_t cmd;
	uint16_t len;
	uint8_t buf[512];
	bool wiped_after;       /* b4_wipe_ioctl came before the next ioctl */
};
static struct call calls[MAX_CALLS];
static unsigned ncalls, nwipes;
static int32_t refuse_flags = -1;       /* a WSEC_PMK with these flags gets this status */
static int32_t refuse_status;
static char logbuf[16384];
static size_t loglen;

int
p1_halt(struct p1 *p, uint32_t code, uint32_t detail)
{
	p->stop = code;
	p->stop_detail = detail;
	return (int)code;
}

int
b4_ioctl(struct p1 *p, uint32_t cmd, uint8_t *b, uint16_t l)
{
	if (ncalls >= MAX_CALLS || l > sizeof(calls[0].buf)) {
		abort();
	}
	calls[ncalls].cmd = cmd;
	calls[ncalls].len = l;
	memcpy(calls[ncalls].buf, b, l);
	calls[ncalls].wiped_after = false;
	ncalls++;
	p->ioc_status = 0;
	if (cmd == WLC_SET_WSEC_PMK && refuse_flags >= 0 && jn_get16(b, 2) == (uint32_t)refuse_flags) {
		p->ioc_status = refuse_status;
	}
	return 0;
}

void
b4_wipe_ioctl(struct p1 *p)
{
	(void)p;
	nwipes++;
	if (ncalls > 0) {
		calls[ncalls - 1].wiped_after = true;
	}
}

int b4_poll(struct p1 *p) { (void)p; abort(); }
int b4_read_counters(struct p1 *p, unsigned w) { (void)p; (void)w; abort(); }
int b4_flow_create(struct p1 *p, const uint8_t *s, const uint8_t *d) { (void)p; (void)s; (void)d; abort(); }
int b4_tx_post(struct p1 *p, const uint8_t *f, uint32_t n) { (void)p; (void)f; (void)n; abort(); }
uint32_t b4_tx_free(const struct p1 *p) { (void)p; abort(); }
int b4_console(struct p1 *p) { (void)p; abort(); }

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

/* ---- Blobs, as mkwifisecret.py makes them ---- */

static const char SSID[] = "hk-test-net";
static const char PASS[] = "not a real pass~";      /* 16: a space and a tilde, both legal */
static uint8_t PMK[32];

static void
blob(uint8_t *b, unsigned version, bool open, const char *pass)
{
	memset(b, 0, NB2_BYTES);
	memcpy(b, version == 2 ? "BWN2" : "BWN1", 4);
	b[4] = (uint8_t)version;
	b[NB_SSID_LEN] = sizeof(SSID) - 1;
	b[NB_FLAGS] = open ? NB_F_OPEN : 0;
	memcpy(b + NB_ABBREV, "DK", 2);
	memcpy(b + NB_CCODE, "DK", 2);
	memset(b + NB_REV, 0xff, 4);
	memcpy(b + NB_SSID, SSID, sizeof(SSID) - 1);
	if (!open) {
		memcpy(b + NB_PMK, PMK, 32);
	}
	if (version == 2 && pass != NULL) {
		b[NB2_PASS_LEN] = (uint8_t)strlen(pass);
		memcpy(b + NB2_PASS, pass, strlen(pass));
	}
}

/* ---- Checks ---- */

static unsigned failures;
#define CHECK(what, cond) do { if (!(cond)) { printf("FAIL %s: %s (line %d)\n", case_name, what, __LINE__); failures++; } } while (0)
static const char *case_name;

static void
reset(struct p1 *p, struct b4_network *net, bool armed)
{
	memset(p, 0, sizeof(*p));
	memset(calls, 0, sizeof(calls));
	ncalls = nwipes = 0;
	loglen = 0;
	logbuf[0] = 0;
	refuse_flags = -1;
	p->ops.log = logf_;
	p->cfg.net = net;
	p->cfg.join_armed = armed;
	p->jn_akm = AKM_PSK;
	p->jn_mfp = MFP_CAPABLE;
}

static bool
is_var(const struct call *c, const char *name)
{
	return c->cmd == WLC_SET_VAR && c->len > strlen(name) && memcmp(c->buf, name, strlen(name) + 1) == 0;
}

static bool
all_zero(const void *v, size_t n)
{
	const uint8_t *b = v;

	for (size_t i = 0; i < n; i++) {
		if (b[i] != 0) {
			return false;
		}
	}
	return true;
}

/* A WLC_SET_WSEC_PMK as stock sends it: sizeof(wsec_pmk_t) + 1 = 263 bytes, key_len, flags, key, opt_len 0, nothing else */
static void
check_pmk_call(const struct call *c, uint16_t flags, const uint8_t *key, uint32_t key_len)
{
	CHECK("ioctl is WLC_SET_WSEC_PMK", c->cmd == WLC_SET_WSEC_PMK && c->cmd == 268u);
	CHECK("263 bytes", c->len == 263);
	CHECK("key_len", jn_get16(c->buf, 0) == key_len);
	CHECK("flags", jn_get16(c->buf, 2) == flags);
	CHECK("key", memcmp(c->buf + 4, key, key_len) == 0);
	CHECK("nothing after the key, opt_len 0", all_zero(c->buf + 4 + key_len, 263 - 4 - key_len));
	CHECK("ioctl buffers wiped right after", c->wiped_after);
}

static bool
log_has(const char *s)
{
	return strstr(logbuf, s) != NULL;
}

static void
no_secret_in_log(void)
{
	CHECK("no passphrase in the log", !log_has(PASS) && !log_has("not a real"));
	CHECK("no name in the log", !log_has(SSID));
	CHECK("no passphrase length in the log", !log_has("passphrase given to the firmware, "));
}

int
main(void)
{
	uint8_t b[NB2_BYTES];
	struct b4_network net;
	struct p1 p;
	const char *bad;
	uint8_t ff[32];

	for (unsigned i = 0; i < 32; i++) {
		PMK[i] = (uint8_t)(0xa5 ^ (i * 7));
	}
	memset(ff, 0xff, sizeof(ff));

	case_name = "BWN2 armed: passphrase, then PMK";
	blob(b, 2, false, PASS);
	bad = b4_net_parse(b, NB2_BYTES, &net);
	CHECK("parses", bad == NULL);
	CHECK("pass kept", net.pass_len == strlen(PASS) && memcmp(net.pass, PASS, net.pass_len) == 0);
	reset(&p, &net, true);
	CHECK("configure ok", configure(&p) == 0 && p.stop == 0);
	{
		const char *order[] = { "wpa_auth", "auth", "sup_wpa", "wsec", "wpa_auth", "mfp" };
		unsigned i;

		CHECK("9 calls", ncalls == 9);
		for (i = 0; i < 6 && i < ncalls; i++) {
			CHECK(order[i], is_var(&calls[i], order[i]));
		}
		if (ncalls >= 9) {
			check_pmk_call(&calls[6], WSEC_PASSPHRASE, (const uint8_t *)PASS, (uint32_t)strlen(PASS));
			check_pmk_call(&calls[7], 0, PMK, 32);
			CHECK("roam_off last", is_var(&calls[8], "roam_off"));
		}
	}
	CHECK("passphrase wiped from the network", all_zero(net.pass, sizeof(net.pass)) && net.pass_len == 0);
	CHECK("PMK wiped from the network", all_zero(net.pmk, sizeof(net.pmk)));
	CHECK("two wipes of the ioctl buffers", nwipes == 2);
	CHECK("logs the passphrase step", log_has("join: passphrase given to the firmware: status 0\n"));
	CHECK("logs the PMK step", log_has("join: key given to the firmware, 32 bytes: status 0\n"));
	no_secret_in_log();

	case_name = "BWN1: the PMK alone, as r1";
	blob(b, 1, false, NULL);
	bad = b4_net_parse(b, NB_BYTES, &net);
	CHECK("parses", bad == NULL && net.pass_len == 0);
	reset(&p, &net, true);
	CHECK("configure ok", configure(&p) == 0);
	CHECK("8 calls", ncalls == 8);
	if (ncalls == 8) {
		check_pmk_call(&calls[6], 0, PMK, 32);
	}
	CHECK("no passphrase step", !log_has("passphrase"));

	case_name = "firmware refuses the passphrase, armed: stop, nothing more, all wiped";
	blob(b, 2, false, PASS);
	(void)b4_net_parse(b, NB2_BYTES, &net);
	reset(&p, &net, true);
	refuse_flags = WSEC_PASSPHRASE;
	refuse_status = -23;
	CHECK("configure stops", configure(&p) != 0 && p.stop == P1_STOP_SECURITY && p.stop_detail == (uint32_t)-23);
	CHECK("no PMK after the refusal", ncalls == 7);
	CHECK("pass and PMK wiped", all_zero(net.pass, sizeof(net.pass)) && all_zero(net.pmk, sizeof(net.pmk)));
	CHECK("refusal logged", log_has("join: passphrase given to the firmware: status -23\n"));
	no_secret_in_log();

	case_name = "firmware refuses the passphrase, dry run: said, and the PMK still goes";
	blob(b, 2, false, PASS);
	(void)b4_net_parse(b, NB2_BYTES, &net);
	reset(&p, &net, false);
	refuse_flags = WSEC_PASSPHRASE;
	refuse_status = -23;
	CHECK("configure ok", configure(&p) == 0 && p.stop == 0);
	CHECK("9 calls", ncalls == 9);
	if (ncalls == 9) {
		check_pmk_call(&calls[7], 0, PMK, 32);
	}

	case_name = "firmware refuses the PMK, armed: stop";
	blob(b, 2, false, PASS);
	(void)b4_net_parse(b, NB2_BYTES, &net);
	reset(&p, &net, true);
	refuse_flags = 0;
	refuse_status = -2;
	CHECK("configure stops", configure(&p) != 0 && p.stop == P1_STOP_SECURITY);
	CHECK("all wiped", all_zero(net.pass, sizeof(net.pass)) && all_zero(net.pmk, sizeof(net.pmk)));

	case_name = "no network in the image (dry run): one all-ones PMK, no passphrase";
	reset(&p, NULL, false);
	CHECK("configure ok", configure(&p) == 0);
	CHECK("8 calls", ncalls == 8);
	if (ncalls == 8) {
		check_pmk_call(&calls[6], 0, ff, 32);
	}

	case_name = "open BWN2 network: no key at all";
	blob(b, 2, true, NULL);
	bad = b4_net_parse(b, NB2_BYTES, &net);
	CHECK("parses", bad == NULL && net.open && net.pass_len == 0);
	reset(&p, &net, true);
	CHECK("configure ok", configure(&p) == 0);
	for (unsigned i = 0; i < ncalls; i++) {
		CHECK("no WSEC_PMK", calls[i].cmd != WLC_SET_WSEC_PMK);
	}

	/* ---- b4_net_parse on BWN2 ---- */
	{
		static const struct {
			const char *name;
			unsigned at;
			int value;      /* -1: leave */
			unsigned bytes;
			bool ok;
		} pc[] = {
			{ "good", 0, -1, NB2_BYTES, true },
			{ "pass 8", NB2_PASS_LEN, 8, NB2_BYTES, true },
			{ "pass 7", NB2_PASS_LEN, 7, NB2_BYTES, false },
			{ "pass 0, not open", NB2_PASS_LEN, 0, NB2_BYTES, false },
			{ "pass 64", NB2_PASS_LEN, 64, NB2_BYTES, false },
			{ "control char", NB2_PASS + 3, 0x1f, NB2_BYTES, false },
			{ "DEL", NB2_PASS + 3, 0x7f, NB2_BYTES, false },
			{ "high byte", NB2_PASS + 3, 0xc3, NB2_BYTES, false },
			{ "byte after the passphrase", NB2_PASS + 16, 'x', NB2_BYTES, false },
			{ "last pad byte", NB2_BYTES - 1, 1, NB2_BYTES, false },
			{ "version 1 with BWN2", 4, 1, NB2_BYTES, false },
			{ "176 bytes but BWN1", 3, '1', NB2_BYTES, false },
			{ "108 bytes of a BWN2", 0, -1, NB_BYTES, false },
			{ "177 bytes", 0, -1, NB2_BYTES + 1, false },
		};
		uint8_t big[NB2_BYTES + 1];

		for (unsigned i = 0; i < sizeof(pc) / sizeof(pc[0]); i++) {
			case_name = pc[i].name;
			memset(big, 0, sizeof(big));
			blob(big, 2, false, PASS);
			if (pc[i].value >= 0) {
				big[pc[i].at] = (uint8_t)pc[i].value;
			}
			/* A length case changes only the length: exactly that many printable bytes, zeros after */
			if (pc[i].at == NB2_PASS_LEN && pc[i].value > 0) {
				memset(big + NB2_PASS, 0, NB2_BYTES - NB2_PASS);
				memset(big + NB2_PASS, 'a', (size_t)pc[i].value);
			}
			bad = b4_net_parse(big, pc[i].bytes, &net);
			CHECK(pc[i].ok ? "accepted" : "refused", (bad == NULL) == pc[i].ok);
			if (bad != NULL) {
				CHECK("reason names no secret", strstr(bad, PASS) == NULL);
			}
		}
		case_name = "pass 63";
		blob(big, 2, false, "0123456789012345678901234567890123456789012345678901234567890 ~");
		bad = b4_net_parse(big, NB2_BYTES, &net);
		CHECK("accepted", bad == NULL && net.pass_len == 63);
		case_name = "open with a passphrase";
		blob(big, 2, true, "12345678");
		CHECK("refused", b4_net_parse(big, NB2_BYTES, &net) != NULL);
		case_name = "BWN2 without a PMK";
		blob(big, 2, false, PASS);
		memset(big + NB_PMK, 0, 32);
		CHECK("refused", b4_net_parse(big, NB2_BYTES, &net) != NULL);
	}

	/* ---- The handshake's failure says which kind it was ---- */
	case_name = "status names";
	CHECK("WAIT_M1 is 4", SUP_WAIT_M1 == 4u);

	if (failures == 0) {
		printf("key oracle: PASSED, 0 failures\n");
		return 0;
	}
	printf("key oracle: %u failures\n", failures);
	return 1;
}
