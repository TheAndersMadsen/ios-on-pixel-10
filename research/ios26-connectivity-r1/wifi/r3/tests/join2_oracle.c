/* SPDX-License-Identifier: MIT
 * HOST ONLY. W1 r3: two join methods in one boot. Includes the real blazer_bcm4390_join.c (r3/src), so its static method1(), method2(),
 * send_join(), join_wait(), part(), join_tries() and b4_join_run() run unchanged, and links the real blazer_bcm4390_scan.c, so every ioctl is
 * put to the real gate (b4_ioctl_allowed at the level the boot would have). The firmware is a script: statuses per iovar, events per try.
 * Synthetic networks only, made here. Prints no key or name.
 *
 * What it pins:
 *   - method 1 is Android's order and bytes (physical dmesg ios26-dualboot-r8/attempts/return-after-restore 13.62-13.69 s; bcm4390/wl_cfg80211.c);
 *   - method 2 is r2's order with mfp 0 and wsec from the network's RSN IE, after a clear and the deletion of method 1's passphrase entry;
 *   - method 2 runs only when method 1 didn't key: refused setting, refused join, failed handshake or no end; a disassociation only after a join;
 *   - the log names the method that keyed; r2's stop codes when both fail;
 *   - the passphrase and PMK leave cfg.net on every way out, every ioctl copy is wiped, and no name, passphrase or length is logged;
 *   - sup_wpa 1 goes before the interface is up; the gate takes all of it when armed and the join and disassociation never in a dry run.
 *
 *   join2_oracle      exit 0: every case passed
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "blazer_bcm4390_join.c"

/* ---- The world around the join, recorded ---- */

#define MAX_CALLS 160
struct call {
	uint32_t cmd;
	uint16_t len;
	uint8_t buf[8192];
	bool wiped_after;       /* b4_wipe_ioctl came before the next ioctl */
};
static struct call calls[MAX_CALLS];
static unsigned ncalls, nwipes, gate_refusals;

/* Firmware statuses: an iovar by name (and, for wsec_info, by TLV type), a WSEC_PMK by flags, the join by try */
static const char *refuse_var;
static int32_t refuse_wsi_type = -1;
static int32_t refuse_status;
static int32_t refuse_pmk_flags = -1;
static int32_t refuse_join_try = -1;

/* Events: per try, delivered one per b4_poll. 'part_events': what comes in after the disassociation */
struct ev { uint32_t type, status, reason, flags; };
#define MAX_EV 8
static struct ev script[3][MAX_EV];
static unsigned script_n[3], script_at[3];
static struct ev part_script[MAX_EV];
static unsigned part_n, part_at;
static bool after_disassoc;
static bool drop_link_in_net;   /* net_run's first poll: the link goes, so b4_join_run returns after keying */
static uint64_t clock_us;
static unsigned polls;

static char logbuf[65536];
static size_t loglen;

int
p1_halt(struct p1 *p, uint32_t code, uint32_t detail)
{
	if (p->stop == 0) {
		p->stop = code;
		p->stop_detail = detail;
	}
	return (int)p->stop;
}

static bool
named(const uint8_t *b, uint16_t l, const char *name)
{
	size_t n = strlen(name);

	return l > n && memcmp(b, name, n + 1) == 0;
}

int
b4_ioctl(struct p1 *p, uint32_t cmd, uint8_t *b, uint16_t l)
{
	if (ncalls >= MAX_CALLS || l > sizeof(calls[0].buf)) {
		abort();
	}
	/* The real gate, at the level the boot would be at (stage JOIN) */
	if (!b4_ioctl_allowed(cmd, b, l, p->cfg.join_armed ? B4_GATE_ARMED : B4_GATE_DRY)) {
		gate_refusals++;
		return p1_halt(p, P1_STOP_IOCTL_REFUSED, cmd);
	}
	calls[ncalls].cmd = cmd;
	calls[ncalls].len = l;
	memcpy(calls[ncalls].buf, b, l);
	calls[ncalls].wiped_after = false;
	ncalls++;
	p->ioc_status = 0;
	p->ioc_got_len = 0;
	if (cmd == WLC_SET_VAR && refuse_var != NULL && named(b, l, refuse_var)) {
		if (strcmp(refuse_var, "wsec_info") != 0 || refuse_wsi_type < 0 || jn_get16(b, 10 + WSI_HDR) == (uint32_t)refuse_wsi_type) {
			p->ioc_status = refuse_status;
		}
	}
	if (cmd == WLC_SET_WSEC_PMK && refuse_pmk_flags >= 0 && jn_get16(b, 2) == (uint32_t)refuse_pmk_flags) {
		p->ioc_status = refuse_status;
	}
	if (cmd == WLC_SET_VAR && named(b, l, "join") && refuse_join_try >= 0 && p->jn_tries == (uint32_t)refuse_join_try) {
		p->ioc_status = -1;
	}
	if (cmd == WLC_DISASSOC) {
		after_disassoc = true;
	}
	if (cmd == WLC_GET_VAR && named(b, l, "country")) {
		memset(b, 0, l);
		b[8] = 'D';
		b[9] = 'K';
	}
	if (cmd == WLC_GET_VAR && named(b, l, "join_ver")) {
		memset(b, 0, l);
		jn_put16(b, JOIN_VER_AT, 3);
	}
	if (cmd == WLC_GET_VAR && named(b, l, "chanspec")) {
		memset(b, 0, l);
		jn_put16(b, 0, 0xd030);
	}
	if (cmd == WLC_GET_VAR && named(b, l, "counters")) {
		memset(b, 0, l);
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

int
b4_poll(struct p1 *p)
{
	unsigned t = p->jn_tries;

	polls++;
	if (p->net_on && drop_link_in_net) {
		p->jn_link = false;
		return 0;
	}
	if (after_disassoc && part_at < part_n) {
		struct ev *e = &part_script[part_at++];

		(void)b4_join_event(p, e->type, e->status, e->reason, e->flags);
		return 0;
	}
	if (t >= 1 && t <= 2 && !(t == 1 && after_disassoc) && script_at[t] < script_n[t]) {
		struct ev *e = &script[t][script_at[t]++];

		(void)b4_join_event(p, e->type, e->status, e->reason, e->flags);
	}
	return 0;
}

int b4_flow_create(struct p1 *p, const uint8_t *s, const uint8_t *d) { (void)p; (void)s; (void)d; abort(); }
int b4_tx_post(struct p1 *p, const uint8_t *f, uint32_t n) { (void)p; (void)f; (void)n; abort(); }
uint32_t b4_tx_free(const struct p1 *p) { (void)p; return 0; }
int b4_console(struct p1 *p) { (void)p; return 0; }
int b4_rx_post_all(struct p1 *p) { (void)p; abort(); }

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

static uint64_t now_(void *ctx) { (void)ctx; return clock_us; }
static void delay_(void *ctx, uint32_t us) { (void)ctx; clock_us += us; }

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

/* A wl_bss_info record as the scan hands it to b4_join_heard: the name, an address, a chanspec, RSSI, and an RSN IE */
static uint32_t
record(uint8_t *bi, const char *ssid, uint8_t last, uint16_t chanspec, int16_t rssi, uint8_t group, uint8_t pair2, uint8_t caps)
{
	uint32_t at = BI_FIXED, ie;

	memset(bi, 0, 256);
	bi[BI_BSSID] = 0x02;
	bi[BI_BSSID + 5] = last;
	jn_put16(bi, BI_CAP, CAP_PRIVACY);
	bi[BI_SSID_LEN] = (uint8_t)strlen(ssid);
	memcpy(bi + BI_SSID, ssid, strlen(ssid));
	jn_put16(bi, BI_CHANSPEC, chanspec);
	jn_put16(bi, BI_RSSI, (uint16_t)rssi);
	bi[BI_CTL_CH] = (uint8_t)chanspec;
	jn_put16(bi, BI_IE_OFFSET, BI_FIXED);
	ie = at;
	bi[at++] = IE_RSN;
	bi[at++] = 0;
	bi[at++] = 1; bi[at++] = 0;                                     /* version */
	bi[at++] = 0; bi[at++] = 0x0f; bi[at++] = 0xac; bi[at++] = group;
	bi[at++] = pair2 ? 2 : 1; bi[at++] = 0;
	bi[at++] = 0; bi[at++] = 0x0f; bi[at++] = 0xac; bi[at++] = SUITE_CCMP;
	if (pair2) {
		bi[at++] = 0; bi[at++] = 0x0f; bi[at++] = 0xac; bi[at++] = pair2;
	}
	bi[at++] = 1; bi[at++] = 0;
	bi[at++] = 0; bi[at++] = 0x0f; bi[at++] = 0xac; bi[at++] = AKM_PSK;
	bi[at++] = caps; bi[at++] = 0;
	bi[ie + 1] = (uint8_t)(at - ie - 2);
	jn_put32(bi, BI_IE_LENGTH, at - BI_FIXED);
	jn_put32(bi, BI_LENGTH, at);
	return at;
}

/* ---- Checks ---- */

static unsigned failures, cases;
static const char *case_name;
#define CHECK(what, cond) do { if (!(cond)) { printf("FAIL %s: %s (line %d)\n", case_name, what, __LINE__); failures++; } } while (0)

static struct b4_network net;
static struct p1 p;

static void
reset(struct b4_network *n, bool armed)
{
	memset(&p, 0, sizeof(p));
	memset(calls, 0, sizeof(calls));
	ncalls = nwipes = gate_refusals = polls = 0;
	loglen = 0;
	logbuf[0] = 0;
	refuse_var = NULL;
	refuse_wsi_type = -1;
	refuse_pmk_flags = -1;
	refuse_join_try = -1;
	memset(script, 0, sizeof(script));
	memset(script_n, 0, sizeof(script_n));
	memset(script_at, 0, sizeof(script_at));
	part_n = part_at = 0;
	after_disassoc = false;
	drop_link_in_net = true;
	clock_us = 1000000;
	p.ops.log = logf_;
	p.ops.now_us = now_;
	p.ops.delay_us = delay_;
	p.cfg.stage = P1_STAGE_JOIN;
	p.cfg.net = n;
	p.cfg.join_armed = armed;
	p.cfg.net_mode = 1;
	cases++;
}

/* The scan heard the network: 2.4 GHz -43 (best, as r2's log), 5 GHz -50, another 2.4 GHz record -60 on the first channel */
static void
heard(uint8_t group, uint8_t pair2, uint8_t caps)
{
	uint8_t bi[256];
	uint32_t n;

	n = record(bi, SSID, 1, 0x1006, -43, group, pair2, caps);
	b4_join_heard(&p, bi, n);
	n = record(bi, SSID, 2, 0xd030, -50, group, pair2, caps);
	b4_join_heard(&p, bi, n);
	n = record(bi, SSID, 3, 0x1006, -60, group, pair2, caps);
	b4_join_heard(&p, bi, n);
	n = record(bi, "someone-else", 4, 0xd024, -30, group, pair2, caps);
	b4_join_heard(&p, bi, n);
}

static void
keys(unsigned t)
{
	struct ev e[] = { { E_AUTH, 0, 0, 0 }, { E_ASSOC, 0, 0, 0 }, { E_LINK, 0, 0, EV_FLAG_LINK }, { E_SET_SSID, 0, 0, 0 }, { E_PSK_SUP, SUP_KEYED, 0, 0 } };

	memcpy(script[t], e, sizeof(e));
	script_n[t] = 5;
}

/* As r1 and r2, physical: auth, association, link, result 0, then WAIT_M1 with reason 14 and the network's deauth 15 */
static void
waits_m1(unsigned t)
{
	struct ev e[] = { { E_AUTH, 0, 0, 0 }, { E_LINK, 0, 0, EV_FLAG_LINK }, { E_ASSOC, 0, 0, 0 }, { E_SET_SSID, 0, 0, 0 }, { E_PSK_SUP, SUP_WAIT_M1, SUP_R_DEAUTH, 0 }, { E_DEAUTH_IND, 0, 15, 0 } };

	memcpy(script[t], e, sizeof(e));
	script_n[t] = 6;
}

static bool
is_var(unsigned i, const char *name)
{
	return i < ncalls && calls[i].cmd == WLC_SET_VAR && named(calls[i].buf, calls[i].len, name);
}

static bool
is_get(unsigned i, const char *name)
{
	return i < ncalls && calls[i].cmd == WLC_GET_VAR && named(calls[i].buf, calls[i].len, name);
}

static uint32_t
int_of(unsigned i)
{
	return jn_get32(calls[i].buf, (uint32_t)strlen((const char *)calls[i].buf) + 1);
}

static bool
int_var(unsigned i, const char *name, uint32_t v)
{
	return is_var(i, name) && calls[i].len == strlen(name) + 1 + 4 && int_of(i) == v;
}

static int
find(unsigned from, uint32_t cmd, const char *name)
{
	for (unsigned i = from; i < ncalls; i++) {
		if (calls[i].cmd == cmd && (name == NULL || named(calls[i].buf, calls[i].len, name))) {
			return (int)i;
		}
	}
	return -1;
}

static unsigned
count(uint32_t cmd, const char *name)
{
	unsigned n = 0;

	for (unsigned i = 0; i < ncalls; i++) {
		n += calls[i].cmd == cmd && (name == NULL || named(calls[i].buf, calls[i].len, name));
	}
	return n;
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

static bool
log_has(const char *s)
{
	return strstr(logbuf, s) != NULL;
}

static void
no_secret(void)
{
	CHECK("no passphrase in the log", !log_has(PASS) && !log_has("not a real"));
	CHECK("no name in the log", !log_has(SSID) && !log_has("hk-test"));
	CHECK("no passphrase length in the log", !log_has("passphrase given to the firmware, ") && !log_has("16 bytes"));
	CHECK("passphrase gone from cfg.net", all_zero(net.pass, sizeof(net.pass)) && net.pass_len == 0);
	CHECK("PMK gone from cfg.net", all_zero(net.pmk, sizeof(net.pmk)));
	CHECK("the gate took every ioctl", gate_refusals == 0);
}

/* A wsec_info call: name, wl_wsec_info_t version 1 with one TLV of this type and length */
static const uint8_t *
wsi(unsigned i, uint16_t type, uint16_t len)
{
	const uint8_t *b = calls[i].buf + 10;

	if (!is_var(i, "wsec_info") || calls[i].len != 10 + WSI_HDR + WSI_TLV_HDR + len || b[0] != 1 || b[1] != 0 || b[2] != 0 || b[3] != 1 ||
	    jn_get16(b, 4) != type || jn_get16(b, 6) != len) {
		return NULL;
	}
	return b + 8;
}

static bool
algos(unsigned i, uint32_t a, uint32_t m)
{
	const uint8_t *d = wsi(i, WSI_BSS_ALGOS, 8);

	return d != NULL && jn_get32(d, 0) == a && jn_get32(d, 4) == m && calls[i].wiped_after;
}

/* wl_cfg80211_config_passphrase's wl_wsec_info_pmk_info_t: version 0x100, len/next/flags/lifetime/akm 0, action, SSID at 36, passphrase after it, padded to 4 */
static bool
pass_entry(unsigned i, uint8_t action)
{
	uint32_t sl = sizeof(SSID) - 1, pl = sizeof(PASS) - 1, size = (36 + sl + pl + 3) & ~3u;
	const uint8_t *d = wsi(i, WSI_BSS_PMK_PASS, (uint16_t)size);

	if (d == NULL) {
		return false;
	}
	return jn_get16(d, 0) == 0x0100 && all_zero(d + 2, 11) && d[13] == action && d[14] == 0 && d[15] == 0 &&
	       jn_get16(d, 16) == sl && jn_get16(d, 18) == 36 && all_zero(d + 20, 12) && jn_get16(d, 32) == pl && jn_get16(d, 34) == 36 + sl &&
	       memcmp(d + 36, SSID, sl) == 0 && memcmp(d + 36 + sl, PASS, pl) == 0 && all_zero(d + 36 + sl + pl, size - 36 - sl - pl) && calls[i].wiped_after;
}

static bool
pmk_call(unsigned i, uint16_t flags, const uint8_t *key, uint32_t len)
{
	const struct call *c = &calls[i];

	return i < ncalls && c->cmd == WLC_SET_WSEC_PMK && c->len == 263 && jn_get16(c->buf, 0) == len && jn_get16(c->buf, 2) == flags &&
	       memcmp(c->buf + 4, key, len) == 0 && all_zero(c->buf + 4 + len, 263 - 4 - len) && c->wiped_after;
}

static bool
join_pref_android(unsigned i)
{
	static const uint8_t want[64] = {
		2, 62, 0, 5,
		0x00, 0x0f, 0xac, 0x18, 0, 0, 0, 0, 0, 0, 0, 0,
		0x00, 0x0f, 0xac, 0x08, 0, 0, 0, 0, 0, 0, 0, 0,
		0x00, 0x0f, 0xac, 0x02, 0, 0, 0, 0, 0, 0, 0, 0,
		0x00, 0x50, 0xf2, 0x02, 0, 0, 0, 0, 0, 0, 0, 0,
		0x00, 0x0f, 0xac, 0x06, 0, 0, 0, 0, 0, 0, 0, 0,
	};

	return is_var(i, "join_pref") && calls[i].len == 10 + 64 && memcmp(calls[i].buf + 10, want, 64) == 0;
}

static bool
join_pref_clear(unsigned i)
{
	return is_var(i, "join_pref") && calls[i].len == 10;
}

/* wl_cfg80211_clear_security, from i: wsec 0, auth 0, wpa_auth 0, join_pref with nothing, algos 0 over the AES mask */
static bool
clear_at(unsigned i)
{
	return int_var(i, "wsec", 0) && int_var(i + 1, "auth", 0) && int_var(i + 2, "wpa_auth", 0) && join_pref_clear(i + 3) && algos(i + 4, 0, 0x1c010);
}

/* The join, v3: SSID, scan params, assoc params. wild: Android's */
static void
check_join(unsigned i, bool wild)
{
	const uint8_t *j = calls[i].buf + 5;
	uint32_t num_at = JP_ASSOC + JA_V3_NUM, nch = wild ? 2 : 1;
	static const uint8_t ff[6] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
	static const uint8_t best[6] = { 0x02, 0, 0, 0, 0, 1 };

	CHECK("a join", is_var(i, "join"));
	CHECK("its length", calls[i].len == 5 + num_at + 4 + 2 * nch);
	CHECK("version 3", jn_get16(j, 0) == 3 && jn_get16(j, JP_ASSOC) == 3);
	CHECK("the name", jn_get32(j, JP_SSID_LEN) == sizeof(SSID) - 1 && memcmp(j + JP_SSID, SSID, sizeof(SSID) - 1) == 0);
	CHECK("assoc flags 0, bssid_cnt 0", jn_get16(j, JP_ASSOC + 2) == 0 && jn_get16(j, JP_ASSOC + 10) == 0);
	CHECK("channel count", jn_get32(j, num_at) == nch);
	if (wild) {
		CHECK("any address", memcmp(j + JP_ASSOC + JA_BSSID, ff, 6) == 0);
		CHECK("scan: default type, 4 probes, 80 ms active, 400 ms passive, home default", j[JP_SCAN] == 0 && jn_get32(j, JP_SCAN_NPROBES) == 4 &&
		    jn_get32(j, JP_SCAN_ACTIVE) == 80 && jn_get32(j, JP_SCAN_PASSIVE) == 400 && jn_get32(j, JP_SCAN_HOME) == 0xffffffffu);
		CHECK("channels: best first, each once", jn_get16(j, num_at + 4) == 0x1006 && jn_get16(j, num_at + 6) == 0xd030);
	} else {
		CHECK("the best record's address", memcmp(j + JP_ASSOC + JA_BSSID, best, 6) == 0);
		CHECK("scan: passive, r2's", j[JP_SCAN] == JS_PASSIVE && jn_get32(j, JP_SCAN_NPROBES) == 0xffffffffu && jn_get32(j, JP_SCAN_ACTIVE) == 0xffffffffu &&
		    jn_get32(j, JP_SCAN_PASSIVE) == 400);
		CHECK("its channel", jn_get16(j, num_at + 4) == 0x1006);
	}
}

/* Method 1's settings from i, armed with BWN2. Returns the index after its PMK */
static unsigned
check_method1(unsigned i)
{
	CHECK("roam on first", int_var(i, "roam_off", 0));
	CHECK("clear_security", clear_at(i + 1));
	CHECK("wpa_auth 0xc0", int_var(i + 6, "wpa_auth", 0xc0));
	CHECK("auth 0", int_var(i + 7, "auth", 0));
	CHECK("multi-AKM wpa_auth 0x2048080", int_var(i + 8, "wpa_auth", 0x2048080));
	CHECK("mfp 1", int_var(i + 9, "mfp", 1));
	CHECK("wsec 6", int_var(i + 10, "wsec", 6));
	CHECK("algos 0x14014/0x1c010", algos(i + 11, 0x14014, 0x1c010));
	CHECK("join_pref, 5 tuples", join_pref_android(i + 12));
	CHECK("passphrase by wsec_info, ADD, with the name", pass_entry(i + 13, PI_ADD));
	{
		const uint8_t *d = wsi(i + 14, WSI_BSS_SAE_PWE, 4);

		CHECK("sae_pwe 3", d != NULL && jn_get32(d, 0) == 3);
	}
	CHECK("PMK, flags 0", pmk_call(i + 15, 0, PMK, 32));
	return i + 16;
}

static unsigned
check_method2(unsigned i, uint32_t wsec, uint32_t mfp)
{
	CHECK("clear_security", clear_at(i));
	CHECK("method 1's entry deleted", pass_entry(i + 5, PI_DEL));
	CHECK("wpa_auth 0xc0", int_var(i + 6, "wpa_auth", 0xc0));
	CHECK("auth 0", int_var(i + 7, "auth", 0));
	CHECK("sup_wpa 1", int_var(i + 8, "sup_wpa", 1));
	CHECK("wsec from the RSN IE", int_var(i + 9, "wsec", wsec));
	CHECK("wpa_auth 0x80", int_var(i + 10, "wpa_auth", 0x80));
	CHECK("mfp", int_var(i + 11, "mfp", mfp));
	CHECK("passphrase, WSEC_PMK flags 1", pmk_call(i + 12, WSEC_PASSPHRASE, (const uint8_t *)PASS, sizeof(PASS) - 1));
	CHECK("PMK, flags 0", pmk_call(i + 13, 0, PMK, 32));
	CHECK("roam_off 1", int_var(i + 14, "roam_off", 1));
	return i + 15;
}

static void
armed_bwn2(void)
{
	uint8_t b[NB2_BYTES];

	blob(b, 2, false, PASS);
	if (b4_net_parse(b, NB2_BYTES, &net) != NULL) {
		abort();
	}
	reset(&net, true);
}

int
main(void)
{
	unsigned i;
	int k;

	for (unsigned n = 0; n < 32; n++) {
		PMK[n] = (uint8_t)(0xa5 ^ (n * 7));
	}

	/* ---- 1. Method 1 keys: Android's order, nothing of method 2, the log says so ---- */
	case_name = "method 1 keys";
	armed_bwn2();
	heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
	keys(1);
	k = b4_join_run(&p);
	CHECK("ends at the link check after keying (net_run ran)", k == P1_STOP_LINK_GONE && p.jn_keyed);
	CHECK("join_ver first", is_get(0, "join_ver"));
	i = check_method1(1);
	check_join(i, true);
	CHECK("then the band", is_get(i + 1, "chanspec"));
	CHECK("one join, no disassociation, no method 2", count(WLC_SET_VAR, "join") == 1 && count(WLC_DISASSOC, NULL) == 0 && count(WLC_SET_VAR, "sup_wpa") == 0 && !log_has("method 2:"));
	CHECK("keyed by method 1 logged", log_has("join: keyed by method 1: Android's order"));
	CHECK("try line", log_has("join: next: try 1, method 1, any address, 2 channels: 2.4 GHz and 5 GHz, RSSI -43, join version 3\n"));
	CHECK("band line", log_has("join: on 5 GHz\n"));
	CHECK("heard line", log_has("on 2 channels\n"));
	no_secret();

	/* ---- 2. Method 1 waits for M1 as r1/r2 did: disassociate, then method 2 keys ---- */
	case_name = "method 1 waits for M1, method 2 keys";
	armed_bwn2();
	heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
	waits_m1(1);
	keys(2);
	/* What may come after the disassociation, from the first association: none of it may count against method 2 */
	part_script[0] = (struct ev){ E_DEAUTH, 0, 3, 0 };
	part_script[1] = (struct ev){ E_LINK, 0, 3, 0 };
	part_script[2] = (struct ev){ E_PSK_SUP, SUP_WAIT_M1, SUP_R_DEAUTH, 0 };
	part_n = 3;
	k = b4_join_run(&p);
	CHECK("keyed by 2, net_run ran", k == P1_STOP_LINK_GONE && p.jn_keyed && p.jn_method == 2 && p.jn_tries == 2);
	i = check_method1(1);
	check_join(i, true);
	k = find(i + 1, WLC_DISASSOC, NULL);
	CHECK("a disassociation right after method 1's join", k == (int)i + 1);
	if (k > 0) {
		CHECK("scb_val: reason 3, no address", calls[k].len == 10 && jn_get32(calls[k].buf, 0) == 3 && all_zero(calls[k].buf + 4, 6));
		i = check_method2((unsigned)k + 1, WSEC_AES, 0);
		check_join(i, false);
		CHECK("then the band", is_get(i + 1, "chanspec") && ncalls == i + 2);
	}
	CHECK("failure of 1 said, with what it would have stopped with", log_has("join: the 4-way handshake failed: status 4, reason 14: the firmware never answered M1") &&
	    log_has("join: method 1 did not key (stop it would have been ") && log_has(", detail 0x10e). Next: method 2\n"));
	CHECK("its events waited for", log_has("join: method 1 over: disassociate: status 0. Next: 1500 ms of its events\n") && part_at == 3);
	CHECK("keyed by method 2 logged", log_has("join: keyed by method 2: r2's order, no mfp, wsec from the RSN IE\n") && !log_has("keyed by method 1"));
	CHECK("try lines", log_has("join: next: try 2, method 2, 2.4 GHz, RSSI -43, join version 3\n"));
	no_secret();

	/* ---- 3. Both fail: r2's stop and detail ---- */
	case_name = "both fail";
	armed_bwn2();
	heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
	waits_m1(1);
	waits_m1(2);
	k = b4_join_run(&p);
	CHECK("r2's stop: JOIN_FAILED, 0x10e", k == P1_STOP_JOIN_FAILED && p.stop_detail == 0x10e);
	CHECK("two joins, one disassociation", count(WLC_SET_VAR, "join") == 2 && count(WLC_DISASSOC, NULL) == 1);
	CHECK("no keyed line", !log_has("keyed by"));
	no_secret();

	/* ---- 4. Method 1 never ends: its timeout, then method 2 ---- */
	case_name = "method 1 no end";
	armed_bwn2();
	heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
	script[1][0] = (struct ev){ E_AUTH, 0, 0, 0 };
	script_n[1] = 1;
	keys(2);
	k = b4_join_run(&p);
	CHECK("method 2 keys after method 1's 20 s", k == P1_STOP_LINK_GONE && p.jn_method == 2 && log_has("join: no end in 20000 ms"));
	CHECK("one disassociation", count(WLC_DISASSOC, NULL) == 1);
	no_secret();

	/* ---- 5. A refusal in method 1's settings: no join for it, no disassociation, method 2 ---- */
	{
		static const struct { const char *var; int32_t type; const char *said; } r[] = {
			{ "wpa_auth", -1, "join: method 1 refused at wpa_auth: status -23. Next: method 2\n" },
			{ "mfp", -1, "join: method 1 refused at mfp: status -23" },
			{ "wsec_info", WSI_BSS_ALGOS, "join: method 1 refused at wsec_info algos: status -23" },
			{ "join_pref", -1, "join: method 1 refused at join_pref: status -23" },
			{ "wsec_info", WSI_BSS_PMK_PASS, "join: method 1 refused at the passphrase: status -23" },
		};

		for (unsigned n = 0; n < sizeof(r) / sizeof(r[0]); n++) {
			case_name = r[n].said;
			armed_bwn2();
			heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
			keys(1);
			refuse_var = r[n].var;
			refuse_wsi_type = r[n].type;
			refuse_status = -23;
			/* clear_security's own calls are refused too (wpa_auth 0, join_pref, algos): only said. Method 2 stops on a refused wpa_auth or mfp, armed, as r2 */
			k = b4_join_run(&p);
			CHECK("said", log_has(r[n].said));
			CHECK("method 1 sent no join", find(0, WLC_SET_VAR, "join") < 0 || p.jn_tries == 1);
			CHECK("no disassociation", count(WLC_DISASSOC, NULL) == 0);
			CHECK("method 2 ran", log_has("join: method 2: r2's order"));
			if (strcmp(r[n].var, "wpa_auth") == 0) {
				CHECK("method 2's refused wpa_auth stops, armed", k == P1_STOP_SECURITY);
			} else if (strcmp(r[n].var, "mfp") == 0) {
				CHECK("method 2's refused mfp stops, armed", k == P1_STOP_SECURITY);
			} else {
				CHECK("method 2 joined (script 1 is its)", p.jn_tries == 1 && count(WLC_SET_VAR, "join") == 1 && k == P1_STOP_LINK_GONE && p.jn_method == 2);
			}
			no_secret();
		}
	}

	/* ---- 6. Method 1's PMK refused, then its join refused: method 2 either way ---- */
	case_name = "method 1's PMK refused";
	armed_bwn2();
	heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
	keys(1);
	refuse_pmk_flags = 0;
	refuse_status = -5;
	k = b4_join_run(&p);
	CHECK("said; method 2's PMK refused too stops it", log_has("join: method 1 refused at the PMK: status -5") && k == P1_STOP_SECURITY && count(WLC_SET_VAR, "join") == 0);
	no_secret();

	case_name = "method 1's join refused";
	armed_bwn2();
	heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
	keys(2);
	refuse_join_try = 1;
	k = b4_join_run(&p);
	CHECK("method 2 keys, no disassociation", k == P1_STOP_LINK_GONE && p.jn_method == 2 && count(WLC_DISASSOC, NULL) == 0 && log_has("join: refused: status -1\n"));
	no_secret();

	case_name = "method 2's join refused: r2's stop";
	armed_bwn2();
	heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
	waits_m1(1);
	refuse_join_try = 2;
	k = b4_join_run(&p);
	CHECK("JOIN_REFUSED", k == P1_STOP_JOIN_REFUSED);
	no_secret();

	/* ---- 7. Method 2's wsec and mfp from the RSN IE ---- */
	{
		static const struct { const char *name; uint8_t group, pair2, caps; uint32_t wsec, mfp; } w[] = {
			{ "CCMP only, MFPC: wsec 4, mfp 0", SUITE_CCMP, 0, RSN_CAP_MFPC_B, WSEC_AES, 0 },
			{ "TKIP group: wsec 6", SUITE_TKIP, 0, 0, WSEC_AES | WSEC_TKIP, 0 },
			{ "TKIP pairwise too: wsec 6", SUITE_CCMP, SUITE_TKIP, 0, WSEC_AES | WSEC_TKIP, 0 },
		};

		for (unsigned n = 0; n < sizeof(w) / sizeof(w[0]); n++) {
			case_name = w[n].name;
			armed_bwn2();
			heard(w[n].group, w[n].pair2, w[n].caps);
			waits_m1(1);
			keys(2);
			k = b4_join_run(&p);
			k = find(0, WLC_DISASSOC, NULL);
			CHECK("method 2 after a disassociation", k > 0);
			if (k > 0) {
				(void)check_method2((unsigned)k + 1, w[n].wsec, w[n].mfp);
			}
			no_secret();
		}
	}

	/* ---- 8. Dry run: both methods' settings, no join, no disassociation, all through the gate at DRY ---- */
	case_name = "dry run with a network";
	{
		uint8_t b[NB2_BYTES];

		blob(b, 2, false, PASS);
		(void)b4_net_parse(b, NB2_BYTES, &net);
		reset(&net, false);
		heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
		k = b4_join_run(&p);
		CHECK("done", k == 0 && p.dry_done && log_has("join: dry run done"));
		i = check_method1(1);
		(void)check_method2(i, WSEC_AES, 0);
		CHECK("no join, no disassociation", count(WLC_SET_VAR, "join") == 0 && count(WLC_DISASSOC, NULL) == 0);
		no_secret();
	}
	case_name = "dry run, no network: all-ones keys, no passphrase";
	{
		uint8_t ff[32];

		memset(ff, 0xff, sizeof(ff));
		reset(NULL, false);
		k = b4_join_run(&p);
		CHECK("done", k == 0 && p.dry_done);
		CHECK("two all-ones PMKs, no passphrase anywhere", count(WLC_SET_WSEC_PMK, NULL) == 2 && pmk_call((unsigned)find(0, WLC_SET_WSEC_PMK, NULL), 0, ff, 32) &&
		    log_has("join: no passphrase in the image: method 1 gives the PMK alone\n"));
		for (unsigned n = 0; n < ncalls; n++) {
			CHECK("no passphrase entry", wsi(n, WSI_BSS_PMK_PASS, 0) == NULL && !(is_var(n, "wsec_info") && jn_get16(calls[n].buf, 14) == WSI_BSS_PMK_PASS));
		}
		CHECK("gate", gate_refusals == 0);
	}

	/* ---- 9. The gate itself ---- */
	{
		uint8_t b[128];
		uint32_t n;

		case_name = "gate";
		armed_bwn2();
		heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
		p.join_ver = 3;
		{
			bool r;

			(void)send_join(&p, true, &r);
		}
		memcpy(b, calls[0].buf, calls[0].len);
		n = calls[0].len;
		CHECK("Android's join, armed", b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		CHECK("not in a dry run", !b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_DRY));
		b[5 + JP_SCAN] = JS_PASSIVE;
		CHECK("wildcard with r2's passive scan: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		b[5 + JP_SCAN] = 0;
		jn_put32(b, 5 + JP_SCAN_NPROBES, 5);
		CHECK("5 probes: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		jn_put32(b, 5 + JP_SCAN_NPROBES, 4);
		jn_put32(b, 5 + JP_SCAN_ACTIVE, 81);
		CHECK("81 ms: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		jn_put32(b, 5 + JP_SCAN_ACTIVE, 80);
		b[5 + JP_ASSOC + JA_BSSID + 5] = 0xfe;
		CHECK("a half-wildcard address: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		b[5 + JP_ASSOC + JA_BSSID + 5] = 0xff;
		jn_put32(b, 5 + JP_ASSOC + JA_V3_NUM, 3);
		jn_put16(b, n, 0xd095);
		CHECK("3 channels, the right length: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n + 2, B4_GATE_ARMED));
		CHECK("3 channels, 2's length: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		jn_put32(b, 5 + JP_ASSOC + JA_V3_NUM, 2);
		jn_put16(b, 5 + JP_ASSOC + 2, 1);
		CHECK("assoc flags: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		jn_put16(b, 5 + JP_ASSOC + 2, 0);
		CHECK("back to Android's: yes", b4_ioctl_allowed(WLC_SET_VAR, b, n, B4_GATE_ARMED));
		CHECK("one byte longer: no", !b4_ioctl_allowed(WLC_SET_VAR, b, n + 1, B4_GATE_ARMED));
		memset(b, 0, 10);
		CHECK("disassociation armed", b4_ioctl_allowed(WLC_DISASSOC, b, 10, B4_GATE_ARMED));
		CHECK("never in a dry run", !b4_ioctl_allowed(WLC_DISASSOC, b, 10, B4_GATE_DRY));
		(void)jn_iov(b, sizeof(b), "wsec_info");
		CHECK("wsec_info dry", b4_ioctl_allowed(WLC_SET_VAR, b, 20, B4_GATE_DRY));
		CHECK("wsec_info not before stage JOIN", !b4_ioctl_allowed(WLC_SET_VAR, b, 20, B4_GATE_PASSIVE));
		(void)jn_iov(b, sizeof(b), "join_pref");
		CHECK("join_pref dry", b4_ioctl_allowed(WLC_SET_VAR, b, 10, B4_GATE_DRY));
		(void)jn_iov(b, sizeof(b), "chanspec");
		CHECK("chanspec read, dry", b4_ioctl_allowed(WLC_GET_VAR, b, 32, B4_GATE_DRY));
		CHECK("chanspec set: no", !b4_ioctl_allowed(WLC_SET_VAR, b, 32, B4_GATE_ARMED));
		CHECK("WLC_SET_SSID (26) still never", !b4_ioctl_allowed(26, b, 32, B4_GATE_ARMED));
	}

	/* ---- 10. Channels heard: best first, each once, two at most ---- */
	{
		uint8_t bi[256];
		uint32_t n;

		case_name = "channels";
		armed_bwn2();
		n = record(bi, SSID, 1, 0x1001, -70, SUITE_CCMP, 0, 0);
		b4_join_heard(&p, bi, n);
		CHECK("one", p.jn_nchans == 1 && p.jn_chans[0] == 0x1001);
		n = record(bi, SSID, 2, 0xd024, -60, SUITE_CCMP, 0, 0);
		b4_join_heard(&p, bi, n);
		CHECK("better goes first", p.jn_nchans == 2 && p.jn_chans[0] == 0xd024 && p.jn_chans[1] == 0x1001);
		n = record(bi, SSID, 3, 0x1001, -50, SUITE_CCMP, 0, 0);
		b4_join_heard(&p, bi, n);
		CHECK("the same channel, better: it moves up, no duplicate", p.jn_nchans == 2 && p.jn_chans[0] == 0x1001 && p.jn_chans[1] == 0xd024 && p.jn_chan_rssi[0] == -50);
		n = record(bi, SSID, 4, 0xd095, -55, SUITE_CCMP, 0, 0);
		b4_join_heard(&p, bi, n);
		CHECK("a third, between: the worst goes", p.jn_nchans == 2 && p.jn_chans[0] == 0x1001 && p.jn_chans[1] == 0xd095);
		n = record(bi, SSID, 5, 0xd09d, -90, SUITE_CCMP, 0, 0);
		b4_join_heard(&p, bi, n);
		CHECK("a worse one: not kept", p.jn_chans[1] == 0xd095);
		n = record(bi, SSID, 6, 0x1001, -80, SUITE_CCMP, 0, RSN_CAP_MFPR_B);
		b4_join_heard(&p, bi, n);
		CHECK("best record's still r2's", p.jn_bssid[5] == 3 && p.jn_rssi == -50);
	}

	/* ---- 11. sup_wpa before the interface is up ---- */
	{
		uint8_t b[NB2_BYTES];

		case_name = "sup_wpa before up";
		blob(b, 2, false, PASS);
		(void)b4_net_parse(b, NB2_BYTES, &net);
		reset(&net, true);
		CHECK("pre_up ok", b4_join_pre_up(&p) == 0);
		k = find(0, WLC_SET_VAR, "sup_wpa");
		CHECK("sup_wpa 1 after the country", k > find(0, WLC_SET_VAR, "country") && int_var((unsigned)k, "sup_wpa", 1));
		CHECK("said", log_has("join: sup_wpa to 1 before the interface is up: status 0\n"));
		case_name = "sup_wpa refused before up: only said";
		reset(&net, true);
		refuse_var = "sup_wpa";
		refuse_status = -23;
		CHECK("pre_up ok", b4_join_pre_up(&p) == 0 && p.stop == 0 && log_has("before the interface is up: status -23"));
		case_name = "open network: no sup_wpa";
		blob(b, 2, true, NULL);
		(void)b4_net_parse(b, NB2_BYTES, &net);
		reset(&net, true);
		CHECK("pre_up ok, no sup_wpa", b4_join_pre_up(&p) == 0 && find(0, WLC_SET_VAR, "sup_wpa") < 0);
	}

	/* ---- 12. BWN1: method 1 gives the PMK alone; method 2 as r1 ---- */
	{
		uint8_t b[NB2_BYTES];

		case_name = "BWN1";
		blob(b, 1, false, NULL);
		(void)b4_net_parse(b, NB_BYTES, &net);
		reset(&net, true);
		heard(SUITE_CCMP, 0, RSN_CAP_MFPC_B);
		waits_m1(1);
		keys(2);
		k = b4_join_run(&p);
		CHECK("method 2 keys", k == P1_STOP_LINK_GONE && p.jn_method == 2);
		CHECK("no passphrase anywhere", count(WLC_SET_WSEC_PMK, NULL) == 2 && log_has("join: no passphrase in the image"));
		CHECK("PMK gone", all_zero(net.pmk, sizeof(net.pmk)));
	}

	/* ---- 13. Not heard: wiped too ---- */
	case_name = "not heard";
	armed_bwn2();
	k = b4_join_run(&p);
	CHECK("NOT_HEARD, nothing sent", k == P1_STOP_NOT_HEARD && ncalls == 0);
	no_secret();

	if (failures == 0) {
		printf("join2 oracle: PASSED, %u cases, 0 failures\n", cases);
		return 0;
	}
	printf("join2 oracle: %u failures in %u cases\n", failures, cases);
	return 1;
}
