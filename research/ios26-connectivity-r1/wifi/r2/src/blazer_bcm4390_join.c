#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * BCM4390 from a passive scan to frames: country, MAC, the network's security, the join, the firmware's own 4-way handshake, the flow ring, and for blazer_wifi_net=1 the kernel's own DHCP, ARP and one ping.
 * One thread, polled, as blazer_bcm4390_ring.c. Own code; values and order are from Broadcom's DHD and its headers (GPL, facts only). Sources: bcm4390/wl_cfg80211.c wl_config_assoc_security, wl_set_wpa_version, wl_set_auth_type, wl_set_set_cipher, wl_set_key_mgmt, wl_cfg80211_set_mfp, wl_fillup_assoc_params, wl_handle_join, wl_cfg80211_sup_event_handler; dhd_linux.c dhd_optimised_preinit_ioctls; wldev_common.c wldev_set_country.
 *
 * What goes on the air, and only with cfg.join_armed, which only blazer_wifi_join=1 sets, and only with a network in the image (research/ios26-fleet/handoffs/wifi.md, "Exact frames"):
 *   the firmware's auth and association requests to one address on one channel, found by listening, the join's own scan being passive; EAPOL 2 and 4 from its supplicant; then what the stack sends, and for blazer_wifi_net=1 DHCP, ARP and ICMP built here.
 * Without it stage JOIN is a dry run: every setting goes to the firmware and it says what it thinks of them, and the join and every frame are refused by the gate (b4_ioctl_allowed, b4_tx_post). No probe request anywhere: no active scan can be expressed, so a hidden network can't be joined.
 *
 * The secret: the network's name and key reach here in cfg.net. The name is never logged, nor anything that would tell which of the networks heard it is. The key goes to the firmware as the passphrase (BWN2), which its supplicant needs, then as the 32-byte PMK made on the host; every copy here is wiped as soon as the firmware has it. An old BWN1 blob holds only the PMK. WPA3-only networks still aren't joined: no SAE settings are made. */
#include "blazer_hw_port.h"
#include "blazer_pcie1.h"

/* The record, as blazer_bcm4390_scan.c reads it. wl_bss_info_v109..116 agree on these */
#define BI_LENGTH       4u
#define BI_BSSID        8u
#define BI_CAP          16u
#define BI_SSID_LEN     18u
#define BI_SSID         19u
#define BI_CHANSPEC     72u
#define BI_RSSI         78u
#define BI_CTL_CH       88u
#define BI_IE_OFFSET    116u
#define BI_IE_LENGTH    120u
#define BI_FIXED        132u
#define CAP_PRIVACY     0x0010u         /* DOT11_CAP_PRIVACY */

/* The RSN element: 802.11's, by way of wpa.h */
#define IE_RSN          48u
#define RSN_VERSION     1u
#define SUITE_TKIP      2u
#define SUITE_CCMP      4u
#define AKM_PSK         2u
#define AKM_PSK_SHA256  6u
#define RSN_CAP_MFPR_B  0x40u           /* RSN_CAP_MFPR */
#define RSN_CAP_MFPC_B  0x80u           /* RSN_CAP_MFPC */

/* Security settings */
#define WPA_AUTH_OFF    0x0000u         /* WPA_AUTH_DISABLED */
#define WPA2_UNSPEC     0x0040u         /* WPA2_AUTH_UNSPECIFIED */
#define WPA2_PSK        0x0080u         /* WPA2_AUTH_PSK */
#define WPA2_PSK_SHA256 0x8000u         /* WPA2_AUTH_PSK_SHA256 */
#define WSEC_TKIP       0x0002u         /* TKIP_ENABLED */
#define WSEC_AES        0x0004u         /* AES_ENABLED */
#define MFP_CAPABLE     1u              /* WL_MFP_CAPABLE */
#define MFP_REQUIRED    2u              /* WL_MFP_REQUIRED */
#define PMK_BYTES       32u             /* WL_SUPP_PMK_LEN */
#define WSEC_PASSPHRASE 1u              /* wsec_pmk_t.flags: key is a passphrase. 0: a PMK */
#define PASS_MIN        8u              /* WSEC_MIN_PSK_LEN */
#define PASS_MAX        63u
#define PMK_IOCTL_BYTES 263u            /* sizeof(wsec_pmk_t) + 1, as stock's array */
#define PMK_KEY_AT      4u

/* wl_extjoin_params_v1, _v2, _v3 */
#define JP_SSID_LEN     4u
#define JP_SSID         8u
#define JP_SCAN         40u
#define JP_SCAN_NPROBES 44u
#define JP_SCAN_ACTIVE  48u
#define JP_SCAN_PASSIVE 52u
#define JP_SCAN_HOME    56u
#define JP_ASSOC        60u
#define JA_VERSION      0u
#define JA_BSSID        4u
#define JA_V1_NUM       12u
#define JA_V2_NUM       16u
#define JA_V3_NUM       20u
#define JS_PASSIVE      1u              /* DOT11_SCANTYPE_PASSIVE */
#define JOIN_DWELL_MS   400u            /* WL_SCAN_JOIN_PASSIVE_DWELL_TIME_MS */
#define JOIN_VER_AT     4u              /* wl_join_version_v1_t.join_ver_major */

/* Chanspec */
#define CS_BAND_MASK    0xc000u
#define CS_BAND_2G      0x0000u
#define CS_BAND_6G      0x4000u         /* This firmware's: physical, stage 4 */
#define CS_BW_20        0x1000u         /* WL_CHANSPEC_BW_20 */

/* Events */
#define E_SET_SSID      0u
#define E_AUTH          3u
#define E_DEAUTH        5u
#define E_DEAUTH_IND    6u
#define E_ASSOC         7u
#define E_REASSOC       9u
#define E_DISASSOC      11u
#define E_DISASSOC_IND  12u
#define E_LINK          16u
#define E_PSK_SUP       46u
#define EV_FLAG_LINK    0x01u           /* WLC_EVENT_MSG_LINK */
#define SUP_WAIT_M1     4u              /* WLC_SUP_KEYXCHANGE_WAIT_M1 */
#define SUP_KEYED       6u              /* WLC_SUP_KEYED */
#define SUP_TIMEOUT     7u              /* WLC_SUP_TIMEOUT */
#define SUP_WAIT_G1     10u             /* WLC_SUP_KEYXCHANGE_WAIT_G1 */
#define SUP_R_OTHER     0u              /* WLC_E_SUP_OTHER */
#define SUP_R_DEAUTH    14u             /* WLC_E_SUP_DEAUTH */
#define SUP_R_PTK       21u             /* WLC_E_SUP_PTK_UPDATE */
#define SUP_R_GTK       23u             /* WLC_E_SUP_GTK_UPDATE */

/* The blob tools/mkwifisecret.py makes: all little endian, no padding it doesn't name. BWN2 = BWN1 + the passphrase */
#define NB_MAGIC        "BWN1"
#define NB_VERSION      1u
#define NB2_MAGIC       "BWN2"
#define NB2_VERSION     2u
#define NB_SSID_LEN     24u
#define NB_FLAGS        25u
#define NB_ABBREV       26u
#define NB_CCODE        28u
#define NB_REV          32u
#define NB_MAC          36u
#define NB_SSID         44u
#define NB_PMK          76u
#define NB_BYTES        108u
#define NB2_PASS_LEN    108u
#define NB2_PASS        109u
#define NB2_BYTES       176u            /* 109 + 63, then 4 zero bytes */
#define NB_F_OPEN       0x01u
#define NB_F_MAC        0x02u

/* The firmware's text */
#define SCRUB_PIECE     3u              /* The shortest piece of the name taken out */
#define SCRUB_HEX_RUN   12u             /* An address with no separators */
#define SCRUB_MAC_TEXT  17u

/* What the dry run sets, with no network in the image: where Android starts, and a key that opens nothing */
static const char dry_code[3] = "XZ";

/* Timing */
#define JOIN_WAIT_MS    20000u
#define CONSOLE_EVERY_US 2000000u

/* Frames */
#define FRAME_MAX       1514u
#define ETH_HDR         14u
#define ET_IP           0x0800u
#define ET_ARP          0x0806u
#define IP_HDR          20u
#define UDP_HDR         8u
#define PROTO_ICMP      1u
#define PROTO_UDP       17u
#define DHCP_SERVER     67u
#define DHCP_CLIENT     68u
#define BOOTP_FIXED     236u
#define BOOTP_XID       4u
#define BOOTP_FLAGS     10u
#define BOOTP_YIADDR    16u
#define BOOTP_CHADDR    28u
#define BOOTP_MIN       300u            /* Some servers want no less */
#define DHCP_COOKIE     0x63825363u
#define OPT_MASK        1u
#define OPT_ROUTER      3u
#define OPT_DNS         6u
#define OPT_REQUESTED   50u
#define OPT_LEASE       51u
#define OPT_TYPE        53u
#define OPT_SERVER      54u
#define OPT_LIST        55u
#define OPT_END         255u
#define DH_DISCOVER     1u
#define DH_OFFER        2u
#define DH_REQUEST      3u
#define DH_ACK          5u
#define DH_NAK          6u
#define DHCP_RETRY_US   2000000u
#define DHCP_TRIES      30u
#define ARP_TRIES       16u
#define PING_RETRY_US   1000000u
#define PING_TRIES      8u
#define PING_ID         0x4877u
#define PING_DATA       32u
enum { IP_IDLE, IP_DISCOVER, IP_REQUEST, IP_ARP, IP_PING, IP_DONE };

static uint16_t jn_get16(const uint8_t *b, uint32_t at) { uint16_t v; memcpy(&v, b + at, 2); return v; }
static uint32_t jn_get32(const uint8_t *b, uint32_t at) { uint32_t v; memcpy(&v, b + at, 4); return v; }
static void jn_put16(uint8_t *b, uint32_t at, uint16_t v) { memcpy(b + at, &v, 2); }
static void jn_put32(uint8_t *b, uint32_t at, uint32_t v) { memcpy(b + at, &v, 4); }
static uint16_t jn_be16(const uint8_t *b, uint32_t at) { return (uint16_t)((uint16_t)b[at] << 8 | b[at + 1]); }
static uint32_t jn_be32(const uint8_t *b, uint32_t at) { return (uint32_t)b[at] << 24 | (uint32_t)b[at + 1] << 16 | (uint32_t)b[at + 2] << 8 | b[at + 3]; }
static void jn_pb16(uint8_t *b, uint32_t at, uint16_t v) { b[at] = (uint8_t)(v >> 8); b[at + 1] = (uint8_t)v; }
static void jn_pb32(uint8_t *b, uint32_t at, uint32_t v) { b[at] = (uint8_t)(v >> 24); b[at + 1] = (uint8_t)(v >> 16); b[at + 2] = (uint8_t)(v >> 8); b[at + 3] = (uint8_t)v; }

static bool
jn_same(const uint8_t *a, const uint8_t *b, uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) {
		if (a[i] != b[i]) {
			return false;
		}
	}
	return true;
}

/* Not memset: this one a compiler can't drop because nothing reads the bytes again */
static void
jn_wipe(void *where, uint32_t bytes)
{
	volatile uint8_t *b = where;

	for (uint32_t i = 0; i < bytes; i++) {
		b[i] = 0;
	}
}

static uint32_t
jn_iov(uint8_t *buf, uint32_t bytes, const char *name)
{
	uint32_t n = 0;

	memset(buf, 0, bytes);
	while (name[n] != 0 && n + 1 < bytes) {
		buf[n] = (uint8_t)name[n];
		n++;
	}
	return n + 1;
}

static int
set_int(struct p1 *p, const char *name, uint32_t value, int32_t *status)
{
	uint8_t b[32];
	uint32_t n = jn_iov(b, sizeof(b), name);

	jn_put32(b, n, value);
	if (b4_ioctl(p, WLC_SET_VAR, b, (uint16_t)(n + 4))) {
		return (int)p->stop;
	}
	*status = p->ioc_status;
	return 0;
}

/* ---- The secret's blob: read by the host test and the kernel alike ---- */

const char *
b4_net_parse(const uint8_t *blob, uint32_t bytes, struct b4_network *net)
{
	uint32_t ver, ssid_len, pass_len = 0;
	uint8_t flags;
	bool two;
	static const uint8_t none[6] = { 0 };

	if (blob == NULL || (bytes != NB_BYTES && bytes != NB2_BYTES)) {
		return "wrong size";
	}
	two = bytes == NB2_BYTES;
	if (!jn_same(blob, (const uint8_t *)(two ? NB2_MAGIC : NB_MAGIC), 4)) {
		return "wrong magic";
	}
	ver = jn_get32(blob, 4);
	if (ver != (two ? NB2_VERSION : NB_VERSION)) {
		return "wrong version";
	}
	ssid_len = blob[NB_SSID_LEN];
	flags = blob[NB_FLAGS];
	if (ssid_len == 0 || ssid_len > sizeof(net->ssid)) {
		return "name's length";
	}
	if ((flags & ~(NB_F_OPEN | NB_F_MAC)) != 0) {
		return "flags";
	}
	for (unsigned i = 0; i < 2; i++) {
		uint8_t a = blob[NB_ABBREV + i], c = blob[NB_CCODE + i];

		if (a < '0' || a > 'Z' || c < '0' || c > 'Z') {
			return "country";
		}
	}
	if ((flags & NB_F_MAC) && ((blob[NB_MAC] & 1u) != 0 || jn_same(blob + NB_MAC, none, 6))) {
		return "MAC address";
	}
	if (!(flags & NB_F_OPEN)) {
		bool any = false;

		for (unsigned i = 0; i < PMK_BYTES; i++) {
			any = any || blob[NB_PMK + i] != 0;
		}
		if (!any) {
			return "key";
		}
	}
	/* The passphrase: 8 to 63 printable ASCII characters (802.11i), nothing after it but zeros. None for an open network */
	if (two) {
		pass_len = blob[NB2_PASS_LEN];
		if ((flags & NB_F_OPEN) ? pass_len != 0 : (pass_len < PASS_MIN || pass_len > PASS_MAX)) {
			return "passphrase's length";
		}
		for (uint32_t i = 0; i < NB2_BYTES - NB2_PASS; i++) {
			uint8_t c = blob[NB2_PASS + i];

			if (i < pass_len ? (c < 0x20u || c > 0x7eu) : c != 0) {
				return "passphrase";
			}
		}
	}
	memset(net, 0, sizeof(*net));
	memcpy(net->ssid, blob + NB_SSID, ssid_len);
	net->ssid_len = (uint8_t)ssid_len;
	net->open = (flags & NB_F_OPEN) != 0;
	memcpy(net->pmk, blob + NB_PMK, PMK_BYTES);
	if (pass_len != 0) {
		memcpy(net->pass, blob + NB2_PASS, pass_len);
		net->pass_len = (uint8_t)pass_len;
	}
	net->have_mac = (flags & NB_F_MAC) != 0;
	memcpy(net->mac, blob + NB_MAC, 6);
	net->abbrev[0] = (char)blob[NB_ABBREV];
	net->abbrev[1] = (char)blob[NB_ABBREV + 1];
	net->ccode[0] = (char)blob[NB_CCODE];
	net->ccode[1] = (char)blob[NB_CCODE + 1];
	net->rev = (int32_t)jn_get32(blob, NB_REV);
	return NULL;
}

/* ---- Before the interface comes up ---- */

/* Stock's order: dhd_optimised_preinit_ioctls sets the address before CLM. Firmware's own (physical, stage 4) is a random local one */
int
b4_join_pre_clm(struct p1 *p)
{
	uint8_t b[32];
	uint32_t n;

	if (p->cfg.join_armed && p->cfg.net == NULL) {
		return p1_halt(p, P1_STOP_NO_NETWORK, 0);
	}
	p->jn_scrub = p->cfg.net != NULL;
	if (p->cfg.net == NULL || !p->cfg.net->have_mac) {
		return 0;
	}
	n = jn_iov(b, sizeof(b), "cur_etheraddr");
	memcpy(b + n, p->cfg.net->mac, 6);
	if (b4_ioctl(p, WLC_SET_VAR, b, (uint16_t)(n + 6))) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "join: MAC address set from the image: status %d, %02x:%02x:%02x:xx:xx:xx\n", p->ioc_status, p->cfg.net->mac[0], p->cfg.net->mac[1], p->cfg.net->mac[2]);
	if (p->ioc_status != 0) {
		return p1_halt(p, P1_STOP_MAC, (uint32_t)p->ioc_status);
	}
	memcpy(p->mac, p->cfg.net->mac, sizeof(p->mac));
	return 0;
}

/* What it can do, for the log: which of the features this stage and the next assume */
static int
read_caps(struct p1 *p)
{
	uint8_t *b = p->ioc_big;
	uint32_t n = 0;

	(void)jn_iov(b, 4096, "cap");
	if (b4_ioctl(p, WLC_GET_VAR, b, 4096)) {
		return (int)p->stop;
	}
	if (p->ioc_status != 0) {
		p->ops.log(p->ops.ctx, "join: cap: status %d\n", p->ioc_status);
		return 0;
	}
	while (n < p->ioc_got_len && b[n] != 0) {
		char line[100];
		uint32_t m = 0;

		while (n < p->ioc_got_len && b[n] != 0 && m + 1 < sizeof(line)) {
			line[m++] = (b[n] >= 32 && b[n] < 127) ? (char)b[n] : ' ';
			n++;
		}
		line[m] = 0;
		p->ops.log(p->ops.ctx, "join: cap: %s\n", line);
	}
	return 0;
}

/* wldev_set_country. The legacy pre-init sets it before WLC_UP too. Then en0, with the address that will be used */
int
b4_join_pre_up(struct p1 *p)
{
	uint8_t b[64];
	uint32_t n = jn_iov(b, sizeof(b), "country");
	const struct b4_network *net = p->cfg.net;
	char code[3] = { 0 };

	if (read_caps(p)) {
		return (int)p->stop;
	}
	code[0] = net != NULL ? net->ccode[0] : dry_code[0];
	code[1] = net != NULL ? net->ccode[1] : dry_code[1];
	b[n] = net != NULL ? (uint8_t)net->abbrev[0] : (uint8_t)dry_code[0];
	b[n + 1] = net != NULL ? (uint8_t)net->abbrev[1] : (uint8_t)dry_code[1];
	jn_put32(b, n + 4, net != NULL ? (uint32_t)net->rev : 0xffffffffu);
	b[n + 8] = (uint8_t)code[0];
	b[n + 9] = (uint8_t)code[1];
	if (b4_ioctl(p, WLC_SET_VAR, b, (uint16_t)(n + 12))) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "join: country %s%s: status %d\n", code, net != NULL ? "" : " (dry run's, no network in the image)", p->ioc_status);
	if (p->ioc_status != 0) {
		if (p->cfg.join_armed) {
			return p1_halt(p, P1_STOP_COUNTRY, (uint32_t)p->ioc_status);
		}
	} else {
		/* Read back, and logged: the CLM may have mapped it */
		(void)jn_iov(b, sizeof(b), "country");
		if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(b))) {
			return (int)p->stop;
		}
		if (p->ioc_status != 0) {
			return p->cfg.join_armed ? p1_halt(p, P1_STOP_COUNTRY, 2) : 0;
		}
		p->ops.log(p->ops.ctx, "join: country now: code %c%c, revision %d\n", b[8], b[9], (int32_t)jn_get32(b, 4));
		if (b[8] != (uint8_t)code[0] || b[9] != (uint8_t)code[1]) {
			/* The firmware went on with some other country's rules */
			if (p->cfg.join_armed) {
				return p1_halt(p, P1_STOP_COUNTRY, 3);
			}
		}
		p->country[0] = (char)b[8];
		p->country[1] = (char)b[9];
		p->country[2] = 0;
	}
	if (p->cfg.net_mode != 0 && p->ops.net_ready != NULL) {
		p->ops.net_ready(p->ops.ctx, p->mac);
	}
	return 0;
}

/* ---- What the scan heard ---- */

/* RSN: version, group suite, pairwise suites, AKM suites, capabilities. Lengths from the air: nothing past end is read. 0: not joinable */
static uint32_t
parse_rsn(const uint8_t *e, uint32_t len, uint8_t *group_tkip, uint8_t *akm, uint8_t *mfp)
{
	static const uint8_t oui[3] = { 0x00, 0x0f, 0xac };
	uint32_t at = 2, count;
	bool ccmp = false, psk = false, sha = false;

	if (len < 2 + 4 + 2 || (uint32_t)e[0] + ((uint32_t)e[1] << 8) != RSN_VERSION || !jn_same(e + at, oui, 3)) {
		return 0;
	}
	if (e[at + 3] == SUITE_TKIP) {
		*group_tkip = 1;
	} else if (e[at + 3] != SUITE_CCMP) {
		return 0;
	}
	at += 4;
	count = (uint32_t)e[at] + ((uint32_t)e[at + 1] << 8);
	at += 2;
	if (count > (len - at) / 4) {
		return 0;
	}
	for (uint32_t i = 0; i < count; i++, at += 4) {
		if (jn_same(e + at, oui, 3) && e[at + 3] == SUITE_CCMP) {
			ccmp = true;
		}
	}
	if (len - at < 2) {
		return 0;
	}
	count = (uint32_t)e[at] + ((uint32_t)e[at + 1] << 8);
	at += 2;
	if (count > (len - at) / 4) {
		return 0;
	}
	for (uint32_t i = 0; i < count; i++, at += 4) {
		if (jn_same(e + at, oui, 3)) {
			psk = psk || e[at + 3] == AKM_PSK;
			sha = sha || e[at + 3] == AKM_PSK_SHA256;
		}
	}
	*mfp = 0;
	if (len - at >= 2) {
		*mfp = (e[at] & RSN_CAP_MFPR_B) ? MFP_REQUIRED : (e[at] & RSN_CAP_MFPC_B) ? MFP_CAPABLE : 0;
	}
	if (!ccmp) {
		return 0;
	}
	/* wl_set_key_mgmt's choices: plain PSK if it's offered and the network doesn't insist, else PSK with SHA-256 */
	if (psk && *mfp != MFP_REQUIRED) {
		*akm = AKM_PSK;
	} else if (sha) {
		*akm = AKM_PSK_SHA256;
	} else {
		return 0;
	}
	return 1;
}

void
b4_join_heard(struct p1 *p, const uint8_t *bi, uint32_t bytes)
{
	const struct b4_network *net = p->cfg.net;
	uint32_t ie_off, ie_len, at, ssid_len = bi[BI_SSID_LEN];
	uint16_t cap;
	int16_t rssi = (int16_t)jn_get16(bi, BI_RSSI);
	uint8_t tkip = 0, akm = 0, mfp = 0;
	bool rsn = false, ok = false;

	if (net == NULL || bytes < BI_FIXED || ssid_len != net->ssid_len || ssid_len > sizeof(net->ssid) || !jn_same(bi + BI_SSID, net->ssid, ssid_len)) {
		return;
	}
	p->jn_seen++;
	cap = jn_get16(bi, BI_CAP);
	ie_off = jn_get16(bi, BI_IE_OFFSET);
	ie_len = jn_get32(bi, BI_IE_LENGTH);
	if (ie_off < BI_FIXED || ie_off > bytes || ie_len > bytes - ie_off) {
		p->jn_refused_security++;
		return;
	}
	for (at = ie_off; at + 2 <= ie_off + ie_len;) {
		uint32_t id = bi[at], len = bi[at + 1];

		if (len > ie_off + ie_len - at - 2) {
			break;
		}
		if (id == IE_RSN) {
			rsn = true;
			ok = parse_rsn(bi + at + 2, len, &tkip, &akm, &mfp) != 0;
			break;
		}
		at += 2 + len;
	}
	/* The secret file said what kind of network this is. A network that has come to look otherwise isn't that one */
	if (net->open) {
		ok = !rsn && !(cap & CAP_PRIVACY);
		akm = 0;
	}
	if (!ok) {
		p->jn_refused_security++;
		return;
	}
	if (!p->jn_found || rssi > p->jn_rssi) {
		p->jn_found = true;
		p->jn_rssi = rssi;
		memcpy(p->jn_bssid, bi + BI_BSSID, 6);
		p->jn_chanspec = jn_get16(bi, BI_CHANSPEC);
		p->jn_ctl = bi[BI_CTL_CH] != 0 ? bi[BI_CTL_CH] : (uint8_t)p->jn_chanspec;
		p->jn_group_tkip = tkip;
		p->jn_akm = akm;
		p->jn_mfp = mfp;
	}
}

static char jn_lower(char c) { return c >= 'A' && c <= 'Z' ? (char)(c + 32) : c; }
static bool jn_hex(char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'); }

static void
jn_mask(char *line, uint32_t bytes)
{
	for (uint32_t j = 0; j < bytes; j++) {
		line[j] = '#';
	}
}

/*
 * Firmware's text, once the image holds a network. What this firmware prints at a join isn't known, so it isn't matched exactly:
 * every address, whoever's, with or without separators; and every piece of the name of 3 bytes or more, in either case, wherever it starts, in case the firmware shortens it or a long line was cut through it.
 * Bytes outside ASCII never get here (b4_console drops them), so what shows of such a name is its ASCII pieces, and those go too. Not caught: pieces under 3 bytes, and the \xNN form of those bytes if the firmware escapes them.
 */
void
b4_scrub_text(const struct p1 *p, char *line)
{
	const struct b4_network *net = p->cfg.net;
	uint32_t n = 0, piece;

	if (!p->jn_scrub || net == NULL) {
		return;
	}
	while (line[n] != 0) {
		n++;
	}
	/* Addresses first, as a name's pieces could cut one in two */
	for (uint32_t i = 0; i + SCRUB_MAC_TEXT <= n; i++) {
		bool mac = true;

		for (uint32_t j = 0; j < SCRUB_MAC_TEXT; j++) {
			mac = mac && (j % 3 == 2 ? line[i + j] == ':' || line[i + j] == '-' : jn_hex(line[i + j]));
		}
		if (mac) {
			jn_mask(line + i, SCRUB_MAC_TEXT);
		}
	}
	for (uint32_t i = 0; i < n;) {
		uint32_t run = 0;

		while (i + run < n && jn_hex(line[i + run])) {
			run++;
		}
		if (run >= SCRUB_HEX_RUN) {
			jn_mask(line + i, run);
		}
		i += run != 0 ? run : 1;
	}
	piece = net->ssid_len < SCRUB_PIECE ? net->ssid_len : SCRUB_PIECE;
	for (uint32_t i = 0; i < n; i++) {
		uint32_t best = 0;

		for (uint32_t s = 0; s < net->ssid_len; s++) {
			uint32_t m = 0;

			while (i + m < n && s + m < net->ssid_len && jn_lower(line[i + m]) == jn_lower((char)net->ssid[s + m])) {
				m++;
			}
			if (m > best) {
				best = m;
			}
		}
		if (best != 0 && best >= piece) {
			jn_mask(line + i, best);
			i += best - 1;
		}
	}
}

/* ---- Events ---- */

bool
b4_join_event(struct p1 *p, uint32_t type, uint32_t status, uint32_t reason, uint32_t flags)
{
	const char *name = NULL;

	switch (type) {
	case E_SET_SSID:
		p->jn_set_ssid_seen = true;
		p->jn_set_ssid = status;
		name = "join's result";
		break;
	case E_AUTH:
		name = "auth";
		break;
	case E_ASSOC:
		name = "association";
		break;
	case E_REASSOC:
		name = "reassociation";
		break;
	case E_DEAUTH:
		name = "deauth sent";
		break;
	case E_DEAUTH_IND:
		name = "deauth by the network";
		break;
	case E_DISASSOC:
		name = "disassociation sent";
		break;
	case E_DISASSOC_IND:
		name = "disassociation by the network";
		break;
	case E_LINK:
		p->jn_link_events++;
		if (flags & EV_FLAG_LINK) {
			p->jn_link = true;
			p->jn_was_up = true;
		} else {
			p->jn_link = false;
			p->jn_keyed = false;
			p->jn_lost_reason = reason;
		}
		name = (flags & EV_FLAG_LINK) ? "link up" : "link down";
		break;
	case E_PSK_SUP:
		p->jn_sup_status = status;
		p->jn_sup_reason = reason;
		/* wl_cfg80211_sup_event_handler's cases. Keyed with a deauth as its reason: stock leaves that to the link event, and so does this */
		if ((status == SUP_KEYED || status == SUP_WAIT_G1) && reason == SUP_R_OTHER) {
			p->jn_keyed = true;
		} else if (status < SUP_WAIT_G1 && !(status == SUP_KEYED && reason == SUP_R_DEAUTH) && reason != SUP_R_OTHER && reason != SUP_R_PTK && reason != SUP_R_GTK) {
			p->jn_sup_failed = true;
		}
		name = "4-way handshake";
		break;
	default:
		return false;
	}
	if ((type == E_AUTH || type == E_ASSOC || type == E_REASSOC) && status != 0) {
		p->jn_fail_type = type;
		p->jn_fail_status = status;
		p->jn_fail_reason = reason;
	}
	/* Numbers only. An event's data can hold the name */
	p->ops.log(p->ops.ctx, "join: %s: status %u, reason %u\n", name, status, reason);
	return true;
}

/* ---- Security and the join: wl_config_assoc_security, wl_handle_join ---- */

/* A dry run: the same settings, a key that opens nothing, and the firmware's answers logged. Never a stop: finding out is the point */
static int
security_step(struct p1 *p, const char *name, uint32_t value)
{
	int32_t st = 0;

	if (set_int(p, name, value, &st)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "join: %s to 0x%x: status %d\n", name, value, st);
	if (st != 0 && p->cfg.join_armed) {
		return p1_halt(p, P1_STOP_SECURITY, (uint32_t)st);
	}
	return 0;
}

/* One wsec_pmk_t (key_len, flags, key[256], opt_len 0) by WLC_SET_WSEC_PMK. The copy on this stack and what went through the ioctl buffers are wiped either way */
static int
give_key(struct p1 *p, const uint8_t *key, uint32_t len, uint16_t flags, int32_t *status)
{
	uint8_t b[PMK_IOCTL_BYTES];

	memset(b, 0, sizeof(b));
	jn_put16(b, 0, (uint16_t)len);
	jn_put16(b, 2, flags);
	for (uint32_t i = 0; i < len; i++) {
		b[PMK_KEY_AT + i] = key != NULL ? key[i] : 0xff;
	}
	if (b4_ioctl(p, WLC_SET_WSEC_PMK, b, sizeof(b))) {
		jn_wipe(b, sizeof(b));
		b4_wipe_ioctl(p);
		return (int)p->stop;
	}
	*status = p->ioc_status;
	jn_wipe(b, sizeof(b));
	b4_wipe_ioctl(p);
	return 0;
}

/*
 * Android's order (wl_config_assoc_security, physical dmesg of 2026-11-03: "Passphrase set", then "pmk added"): the passphrase, then the PMK.
 * The passphrase, flags WSEC_PASSPHRASE, is what this firmware's supplicant runs on: wlc_keymgmt_set_wsec_pmk keeps it in its list
 * (wlc_pmk_add_passphrase), and at the join wlc_join_infra says "Start PSK to PMK conversion", wlc_sup_set_ssid hashes it with the
 * join's SSID on a timer and the M1 that came meanwhile is kept and answered (wlc_sup_pmk_notif_cb). A PMK alone, flags 0, goes to
 * wlc_sup_set_pmk and the join finds no passphrase: physical a7-wifi-join-r1 waited for M1 (status 4) until the network gave up (reason 15).
 * Stock's fallback when wsec_info is missing (wl_cfg80211_config_passphrase) is this same ioctl, so no new iovar.
 */
static int
set_key(struct p1 *p)
{
	struct b4_network *net = p->cfg.net;
	int32_t st = 0;
	int rc;

	if (net != NULL && net->pass_len != 0) {
		rc = give_key(p, net->pass, net->pass_len, WSEC_PASSPHRASE, &st);
		jn_wipe(net->pass, sizeof(net->pass));
		net->pass_len = 0;
		if (rc) {
			jn_wipe(net->pmk, sizeof(net->pmk));
			return rc;
		}
		/* Never its length: that says something about it */
		p->ops.log(p->ops.ctx, "join: passphrase given to the firmware: status %d\n", st);
		if (st != 0 && p->cfg.join_armed) {
			jn_wipe(net->pmk, sizeof(net->pmk));
			return p1_halt(p, P1_STOP_SECURITY, (uint32_t)st);
		}
	}
	/* With no network in the image: all ones, which opens nothing */
	rc = give_key(p, net != NULL ? net->pmk : NULL, PMK_BYTES, 0, &st);
	if (net != NULL) {
		jn_wipe(net->pmk, sizeof(net->pmk));
	}
	if (rc) {
		return rc;
	}
	p->ops.log(p->ops.ctx, "join: key given to the firmware, %u bytes: status %d\n", PMK_BYTES, st);
	if (st != 0 && p->cfg.join_armed) {
		return p1_halt(p, P1_STOP_SECURITY, (uint32_t)st);
	}
	return 0;
}

static int
configure(struct p1 *p)
{
	const struct b4_network *net = p->cfg.net;
	bool open = net != NULL && net->open;
	uint32_t wpa = p->jn_akm == AKM_PSK_SHA256 ? WPA2_PSK_SHA256 : WPA2_PSK;
	int32_t st = 0;

	if (security_step(p, "wpa_auth", open ? WPA_AUTH_OFF : (WPA2_PSK | WPA2_UNSPEC)) || security_step(p, "auth", 0)) {
		return (int)p->stop;
	}
	if (!open) {
		if (security_step(p, "sup_wpa", 1) || security_step(p, "wsec", WSEC_AES | (p->jn_group_tkip ? WSEC_TKIP : 0u)) || security_step(p, "wpa_auth", wpa)) {
			return (int)p->stop;
		}
		if (p->jn_mfp != 0 && security_step(p, "mfp", p->jn_mfp)) {
			return (int)p->stop;
		}
		if (set_key(p)) {
			return (int)p->stop;
		}
	} else if (security_step(p, "wsec", 0)) {
		return (int)p->stop;
	}
	/* Roaming's scans would be active ones, on its own say. Stock leaves it on; here it's off for the first joins. A failure is only said */
	if (set_int(p, "roam_off", 1, &st)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "join: roam_off to 1: status %d\n", st);
	return 0;
}

static int
read_join_ver(struct p1 *p)
{
	uint8_t b[64];

	(void)jn_iov(b, sizeof(b), "join_ver");
	if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(b))) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "join: join_ver: status %d, major %u\n", p->ioc_status, jn_get16(b, JOIN_VER_AT));
	if (p->ioc_status != 0 || jn_get16(b, JOIN_VER_AT) < 1 || jn_get16(b, JOIN_VER_AT) > 3) {
		if (p->cfg.join_armed) {
			return p1_halt(p, P1_STOP_JOIN_VERSION, jn_get16(b, JOIN_VER_AT));
		}
		p->join_ver = 0;
		return 0;
	}
	p->join_ver = jn_get16(b, JOIN_VER_AT);
	return 0;
}

/* wl_fillup_assoc_params, for a known address on a known channel. No scan of its own beyond listening there */
static int
send_join(struct p1 *p)
{
	const struct b4_network *net = p->cfg.net;
	uint8_t b[128];
	uint32_t n = jn_iov(b, sizeof(b), "join");
	uint8_t *j = b + n;
	uint32_t ver = p->join_ver, num_at = JP_ASSOC + (ver == 1 ? JA_V1_NUM : ver == 2 ? JA_V2_NUM : JA_V3_NUM);
	uint16_t chanspec = (uint16_t)((p->jn_chanspec & CS_BAND_MASK) | CS_BW_20 | p->jn_ctl);

	jn_put16(j, 0, (uint16_t)ver);
	jn_put32(j, JP_SSID_LEN, net->ssid_len);
	memcpy(j + JP_SSID, net->ssid, net->ssid_len);
	j[JP_SCAN] = JS_PASSIVE;
	jn_put32(j, JP_SCAN_NPROBES, 0xffffffffu);
	jn_put32(j, JP_SCAN_ACTIVE, 0xffffffffu);
	jn_put32(j, JP_SCAN_PASSIVE, JOIN_DWELL_MS);
	jn_put32(j, JP_SCAN_HOME, 0xffffffffu);
	jn_put16(j, JP_ASSOC + JA_VERSION, (uint16_t)ver);
	memcpy(j + JP_ASSOC + JA_BSSID, p->jn_bssid, 6);
	jn_put32(j, num_at, 1);
	jn_put16(j, num_at + 4, chanspec);
	p->jn_set_ssid_seen = false;
	p->jn_fail_type = 0;
	p->jn_tries++;
	/* The band, not the channel: stage 4's log lists the neighbours by channel, and the channel would say which of them this is */
	p->ops.log(p->ops.ctx, "join: next: try %u, %s GHz, RSSI %d, join version %u\n", p->jn_tries, (chanspec & CS_BAND_MASK) == CS_BAND_2G ? "2.4" : (chanspec & CS_BAND_MASK) == CS_BAND_6G ? "6" : "5", p->jn_rssi, ver);
	if (b4_ioctl(p, WLC_SET_VAR, b, (uint16_t)(n + num_at + 4 + 2))) {
		return (int)p->stop;
	}
	if (p->ioc_status != 0) {
		p->ops.log(p->ops.ctx, "join: refused: status %d\n", p->ioc_status);
		return p1_halt(p, P1_STOP_JOIN_REFUSED, (uint32_t)p->ioc_status);
	}
	return 0;
}

static int
join_wait(struct p1 *p)
{
	const struct b4_network *net = p->cfg.net;
	uint64_t t0 = p->ops.now_us(p->ops.ctx);

	for (;;) {
		uint32_t ms = (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000);

		if (b4_poll(p)) {
			return (int)p->stop;
		}
		if (p->jn_set_ssid_seen && p->jn_set_ssid != 0) {
			p->ops.log(p->ops.ctx, "join: failed: result %u. Auth or association: type %u, status %u, reason %u\n", p->jn_set_ssid, p->jn_fail_type, p->jn_fail_status, p->jn_fail_reason);
			return p1_halt(p, P1_STOP_JOIN_FAILED, p->jn_set_ssid);
		}
		/* No retries on a key that didn't work: the chip goes off, which ends the attempt on the air */
		if (p->jn_sup_failed || p->jn_sup_status == SUP_TIMEOUT) {
			/* WLC_SUP_KEYXCHANGE_WAIT_M1 (4): M1 never answered, so the firmware had no key to answer with. Past it (8 and on): M2 went out, most often with a wrong password's PMK */
			p->ops.log(p->ops.ctx, "join: the 4-way handshake failed: status %u, reason %u: %s\n", p->jn_sup_status, p->jn_sup_reason,
			    p->jn_sup_status == SUP_WAIT_M1 ? "the firmware never answered M1: it had no key it could use" : "most often a wrong password");
			return p1_halt(p, P1_STOP_JOIN_FAILED, 0x100u | p->jn_sup_reason);
		}
		if (p->jn_was_up && !p->jn_link && !p->jn_keyed) {
			p->ops.log(p->ops.ctx, "join: link went down before the keys, reason %u: most often a wrong password\n", p->jn_lost_reason);
			return p1_halt(p, P1_STOP_JOIN_FAILED, 0x200u | p->jn_lost_reason);
		}
		if (p->jn_link && p->jn_set_ssid_seen && (net->open || p->jn_keyed)) {
			p->jn_ms = ms;
			p->ops.log(p->ops.ctx, "join: joined in %u ms\n", ms);
			return 0;
		}
		if (ms >= JOIN_WAIT_MS) {
			p->ops.log(p->ops.ctx, "join: no end in %u ms: result seen %d, link %d, handshake %u/%u\n", ms, p->jn_set_ssid_seen, p->jn_link, p->jn_sup_status, p->jn_sup_reason);
			return p1_halt(p, P1_STOP_JOIN_TIMEOUT, ms);
		}
		p->ops.delay_us(p->ops.ctx, 1000);
	}
}

/* ---- blazer_wifi_net=1: an address, and proof that a frame gets to the gateway and back. Then en0 has it too ---- */

static uint16_t
ip_csum(const uint8_t *b, uint32_t n)
{
	uint32_t sum = 0;

	for (uint32_t i = 0; i + 1 < n; i += 2) {
		sum += jn_be16(b, i);
	}
	if (n & 1u) {
		sum += (uint32_t)b[n - 1] << 8;
	}
	while (sum >> 16) {
		sum = (sum & 0xffffu) + (sum >> 16);
	}
	return (uint16_t)~sum;
}

static uint32_t
ip_frame(struct p1 *p, uint8_t *f, const uint8_t *dst_mac, uint32_t src_ip, uint32_t dst_ip, uint8_t proto, uint32_t payload)
{
	memcpy(f, dst_mac, 6);
	memcpy(f + 6, p->mac, 6);
	jn_pb16(f, 12, ET_IP);
	f[14] = 0x45;
	f[15] = 0;
	jn_pb16(f, 16, (uint16_t)(IP_HDR + payload));
	jn_pb16(f, 18, (uint16_t)p->ip_tries);
	jn_pb16(f, 20, 0);
	f[22] = 64;
	f[23] = proto;
	jn_pb16(f, 24, 0);
	jn_pb32(f, 26, src_ip);
	jn_pb32(f, 30, dst_ip);
	jn_pb16(f, 24, ip_csum(f + ETH_HDR, IP_HDR));
	return ETH_HDR + IP_HDR + payload;
}

/* Sent through the flow ring like anything else, and made when the first frame needs it. Only one can wait for that */
static int
net_send(struct p1 *p, const uint8_t *frame, uint32_t bytes)
{
	if (bytes > FRAME_MAX || bytes < ETH_HDR) {
		p->rx_dropped++;
		return 0;
	}
	if (p->flow_state != 2) {
		if (p->tx_hold_len == 0) {
			memcpy(p->tx_hold, frame, bytes);
			p->tx_hold_len = bytes;
		}
		return p->flow_state == 0 ? b4_flow_create(p, p->mac, frame) : 0;
	}
	if (b4_tx_free(p) == 0) {
		return 0;
	}
	return b4_tx_post(p, frame, bytes);
}

static void
dhcp_option4(uint8_t *o, uint32_t *at, uint8_t code, uint32_t value)
{
	o[(*at)++] = code;
	o[(*at)++] = 4;
	jn_pb32(o, *at, value);
	*at += 4;
}

static int
dhcp_send(struct p1 *p, uint8_t type)
{
	static const uint8_t bcast[6] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
	uint8_t f[ETH_HDR + IP_HDR + UDP_HDR + BOOTP_MIN];
	uint8_t *u = f + ETH_HDR + IP_HDR, *d = u + UDP_HDR, *o = d + BOOTP_FIXED;
	uint32_t at = 0, n;

	memset(f, 0, sizeof(f));
	d[0] = 1;       /* BOOTREQUEST */
	d[1] = 1;       /* Ethernet */
	d[2] = 6;
	jn_pb32(d, BOOTP_XID, p->ip_xid);
	jn_pb16(d, BOOTP_FLAGS, 0x8000);        /* Answer by broadcast: no address yet to answer to */
	memcpy(d + BOOTP_CHADDR, p->mac, 6);
	jn_pb32(o, at, DHCP_COOKIE);
	at += 4;
	o[at++] = OPT_TYPE;
	o[at++] = 1;
	o[at++] = type;
	if (type == DH_REQUEST) {
		dhcp_option4(o, &at, OPT_REQUESTED, p->ip_offer);
		dhcp_option4(o, &at, OPT_SERVER, p->ip_server);
	}
	o[at++] = OPT_LIST;
	o[at++] = 3;
	o[at++] = OPT_MASK;
	o[at++] = OPT_ROUTER;
	o[at++] = OPT_DNS;
	o[at++] = OPT_END;
	jn_pb16(u, 0, DHCP_CLIENT);
	jn_pb16(u, 2, DHCP_SERVER);
	jn_pb16(u, 4, UDP_HDR + BOOTP_MIN);
	jn_pb16(u, 6, 0);       /* No checksum: IPv4 allows it */
	n = ip_frame(p, f, bcast, 0, 0xffffffffu, PROTO_UDP, UDP_HDR + BOOTP_MIN);
	p->ip_tries++;
	return net_send(p, f, n);
}

static int
arp_send(struct p1 *p)
{
	static const uint8_t bcast[6] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff };
	uint8_t f[ETH_HDR + 28];

	memset(f, 0, sizeof(f));
	memcpy(f, bcast, 6);
	memcpy(f + 6, p->mac, 6);
	jn_pb16(f, 12, ET_ARP);
	jn_pb16(f, 14, 1);
	jn_pb16(f, 16, ET_IP);
	f[18] = 6;
	f[19] = 4;
	jn_pb16(f, 20, 1);
	memcpy(f + 22, p->mac, 6);
	jn_pb32(f, 28, p->ip_addr);
	jn_pb32(f, 38, p->ip_gw);
	return net_send(p, f, sizeof(f));
}

static int
ping_send(struct p1 *p)
{
	uint8_t f[ETH_HDR + IP_HDR + 8 + PING_DATA];
	uint8_t *i = f + ETH_HDR + IP_HDR;

	memset(f, 0, sizeof(f));
	i[0] = 8;
	jn_pb16(i, 4, PING_ID);
	p->ping_seq++;
	jn_pb16(i, 6, (uint16_t)p->ping_seq);
	for (uint32_t k = 0; k < PING_DATA; k++) {
		i[8 + k] = (uint8_t)(0x20 + k);
	}
	jn_pb16(i, 2, ip_csum(i, 8 + PING_DATA));
	p->ping_sent_us = p->ops.now_us(p->ops.ctx);
	(void)ip_frame(p, f, p->gw_mac, p->ip_addr, p->ip_gw, PROTO_ICMP, 8 + PING_DATA);
	return net_send(p, f, sizeof(f));
}

/* Options from the air. Nothing past end is read */
static void
dhcp_parse(const uint8_t *o, uint32_t end, uint32_t *type, uint32_t *server, uint32_t *mask, uint32_t *router, uint32_t *lease)
{
	uint32_t at = 4;

	while (at < end) {
		uint32_t code = o[at], len;

		if (code == OPT_END) {
			return;
		}
		if (code == 0) {
			at++;
			continue;
		}
		if (at + 1 >= end) {
			return;
		}
		len = o[at + 1];
		if (len > end - at - 2) {
			return;
		}
		if (code == OPT_TYPE && len >= 1) {
			*type = o[at + 2];
		} else if (code == OPT_SERVER && len >= 4) {
			*server = jn_be32(o, at + 2);
		} else if (code == OPT_MASK && len >= 4) {
			*mask = jn_be32(o, at + 2);
		} else if (code == OPT_ROUTER && len >= 4) {
			*router = jn_be32(o, at + 2);
		} else if (code == OPT_LEASE && len >= 4) {
			*lease = jn_be32(o, at + 2);
		}
		at += 2 + len;
	}
}

static void
take_dhcp(struct p1 *p, const uint8_t *d, uint32_t n)
{
	uint32_t type = 0, server = 0, mask = 0, router = 0, lease = 0, yi;
	const uint8_t *o = d + BOOTP_FIXED;

	if (n < BOOTP_FIXED + 5 || d[0] != 2 || jn_be32(d, BOOTP_XID) != p->ip_xid || !jn_same(d + BOOTP_CHADDR, p->mac, 6) || jn_be32(o, 0) != DHCP_COOKIE) {
		return;
	}
	dhcp_parse(o, n - BOOTP_FIXED, &type, &server, &mask, &router, &lease);
	yi = jn_be32(d, BOOTP_YIADDR);
	if (type == DH_OFFER && p->ip_state == IP_DISCOVER && yi != 0 && yi != 0xffffffffu && server != 0) {
		p->ip_offer = yi;
		p->ip_server = server;
		p->ip_state = IP_REQUEST;
		p->ip_next_us = 0;
	} else if (type == DH_ACK && p->ip_state == IP_REQUEST && yi == p->ip_offer) {
		p->ip_addr = yi;
		p->ip_mask = mask != 0 ? mask : 0xffffff00u;
		p->ip_gw = router != 0 ? router : p->ip_server;
		p->ip_lease = lease;
		p->ip_state = IP_ARP;
		p->ip_tries = 0;
		p->ip_next_us = 0;
	} else if (type == DH_NAK && p->ip_state == IP_REQUEST) {
		p->ip_naks++;
		p->ip_state = IP_DISCOVER;
		p->ip_next_us = 0;
	}
}

/* Frames this stage is waiting for are its own. Everything else is for en0's stack, which also needs to answer the gateway's own ARP */
static bool
proof_takes(struct p1 *p, const uint8_t *f, uint32_t n)
{
	uint16_t et = jn_be16(f, 12);

	if (et == ET_ARP && p->ip_state == IP_ARP && n >= ETH_HDR + 28 && jn_be16(f, 20) == 2 && jn_be32(f, 28) == p->ip_gw && jn_be32(f, 38) == p->ip_addr) {
		memcpy(p->gw_mac, f + 22, 6);
		p->ip_state = IP_PING;
		p->ip_tries = 0;
		p->ip_next_us = 0;
		return true;
	}
	if (et != ET_IP || n < ETH_HDR + IP_HDR || (f[14] >> 4) != 4) {
		return false;
	}
	{
		uint32_t ihl = (uint32_t)(f[14] & 15u) * 4, ip_len = jn_be16(f, 16);
		const uint8_t *l = f + ETH_HDR + ihl;

		if (ihl < IP_HDR || ip_len < ihl || ip_len > n - ETH_HDR) {
			return false;
		}
		if (f[23] == PROTO_UDP && (p->ip_state == IP_DISCOVER || p->ip_state == IP_REQUEST)) {
			if (ip_len - ihl >= UDP_HDR && jn_be16(l, 0) == DHCP_SERVER && jn_be16(l, 2) == DHCP_CLIENT) {
				take_dhcp(p, l + UDP_HDR, ip_len - ihl - UDP_HDR);
				return true;
			}
			return false;
		}
		if (f[23] == PROTO_ICMP && p->ip_state == IP_PING && ip_len - ihl >= 8 && l[0] == 0 && jn_be16(l, 4) == PING_ID && jn_be16(l, 6) == (uint16_t)p->ping_seq && jn_be32(f, 26) == p->ip_gw) {
			p->ping_ms = (uint32_t)((p->ops.now_us(p->ops.ctx) - p->ping_sent_us) / 1000);
			p->ping_ok = true;
			p->ip_state = IP_DONE;
			return true;
		}
	}
	return false;
}

static int
proof_tick(struct p1 *p, uint64_t now)
{
	if (p->ip_state == IP_DONE || now < p->ip_next_us) {
		return 0;
	}
	switch (p->ip_state) {
	case IP_IDLE:
		p->ops.random(p->ops.ctx, &p->ip_xid, sizeof(p->ip_xid));
		p->ip_state = IP_DISCOVER;
		/* FALLTHROUGH */
	case IP_DISCOVER:
	case IP_REQUEST:
		if (p->ip_tries >= DHCP_TRIES) {
			p->ip_next_us = UINT64_MAX;
			return 0;
		}
		p->ip_next_us = now + DHCP_RETRY_US;
		return dhcp_send(p, p->ip_state == IP_DISCOVER ? DH_DISCOVER : DH_REQUEST);
	case IP_ARP:
		if (!p->ip_told) {
			p->ip_told = true;
			p->ops.log(p->ops.ctx, "net: address %u.%u.%u.%u, mask %u.%u.%u.%u, gateway %u.%u.%u.%u, lease %u s\n", p->ip_addr >> 24, (p->ip_addr >> 16) & 255u, (p->ip_addr >> 8) & 255u, p->ip_addr & 255u, p->ip_mask >> 24, (p->ip_mask >> 16) & 255u, (p->ip_mask >> 8) & 255u, p->ip_mask & 255u, p->ip_gw >> 24, (p->ip_gw >> 16) & 255u, (p->ip_gw >> 8) & 255u, p->ip_gw & 255u, p->ip_lease);
			if (p->ops.net_addr != NULL) {
				p->ops.net_addr(p->ops.ctx, p->ip_addr, p->ip_mask, p->ip_gw);
			}
		}
		if (p->ip_tries >= ARP_TRIES) {
			p->ip_next_us = UINT64_MAX;
			return 0;
		}
		p->ip_next_us = now + PING_RETRY_US;
		p->ip_tries++;
		return arp_send(p);
	case IP_PING:
		if (p->ping_seq >= PING_TRIES) {
			p->ip_next_us = UINT64_MAX;
			return 0;
		}
		p->ip_next_us = now + PING_RETRY_US;
		return ping_send(p);
	default:
		return 0;
	}
}

void
b4_net_rx(struct p1 *p, const uint8_t *f, uint32_t n)
{
	if (n < ETH_HDR || n > FRAME_MAX) {
		p->rx_dropped++;
		return;
	}
	p->rx_frames++;
	if (p->cfg.net_mode == 1 && proof_takes(p, f, n)) {
		return;
	}
	if (p->ops.net_rx != NULL) {
		p->ops.net_rx(p->ops.ctx, f, n);
	}
}

void
b4_on_flow_created(struct p1 *p, int32_t status, uint32_t ring)
{
	p->ops.log(p->ops.ctx, "net: flow ring: status %d, ring %u\n", status, ring);
	if (p->flow_state != 1 || status != 0 || ring != 2) {
		(void)p1_halt(p, P1_STOP_FLOW_RING, (uint32_t)status);
		return;
	}
	p->flow_state = 2;
}

/* ---- Frames ---- */

static int
net_pump(struct p1 *p)
{
	/* The frame that waited for the flow ring first: nothing overtakes it */
	if (p->flow_state == 2 && p->tx_hold_len != 0 && b4_tx_free(p) != 0) {
		uint32_t n = p->tx_hold_len;

		p->tx_hold_len = 0;
		if (b4_tx_post(p, p->tx_hold, n)) {
			return (int)p->stop;
		}
	}
	while (p->ops.net_tx != NULL && p->tx_hold_len == 0 && b4_tx_free(p) != 0 && p->flow_state != 1) {
		static uint8_t f[FRAME_MAX];
		uint32_t n = p->ops.net_tx(p->ops.ctx, f, sizeof(f));

		if (n == 0) {
			break;
		}
		if (net_send(p, f, n)) {
			return (int)p->stop;
		}
	}
	return 0;
}

static void
link_changed(struct p1 *p, bool up)
{
	if (p->net_on == up) {
		return;
	}
	p->net_on = up;
	p->ops.log(p->ops.ctx, "net: frames can %s\n", up ? "pass" : "no longer pass");
	if (p->ops.net_link != NULL) {
		p->ops.net_link(p->ops.ctx, up);
	}
}

static int
net_run(struct p1 *p)
{
	uint64_t t0 = p->ops.now_us(p->ops.ctx), next_console = t0 + CONSOLE_EVERY_US;
	uint64_t run_us = (uint64_t)p->cfg.net_run_s * 1000000u;

	link_changed(p, true);
	for (;;) {
		uint64_t now = p->ops.now_us(p->ops.ctx);

		if (b4_poll(p)) {
			return (int)p->stop;
		}
		/* No rejoin in this build: stock deletes its flow rings first, and that's untried here. The log says why, the chip goes off */
		if (!p->jn_link) {
			link_changed(p, false);
			p->ops.log(p->ops.ctx, "net: network lost, reason %u\n", p->jn_lost_reason);
			return p1_halt(p, P1_STOP_LINK_GONE, p->jn_lost_reason);
		}
		if ((p->cfg.net_mode == 1 && proof_tick(p, now)) || net_pump(p)) {
			return (int)p->stop;
		}
		if (now >= next_console) {
			next_console = now + CONSOLE_EVERY_US;
			if (b4_console(p)) {
				return (int)p->stop;
			}
		}
		if (run_us != 0 && now - t0 >= run_us) {
			break;
		}
		p->ops.delay_us(p->ops.ctx, 1000);
	}
	p->ops.log(p->ops.ctx, "net: %u frames in, %u out, %u bad TX status, %u dropped\n", p->rx_frames, p->tx_sent, p->tx_status_bad, p->rx_dropped);
	link_changed(p, false);
	if (p->cfg.net_mode == 1) {
		if (p->ip_addr == 0) {
			return p1_halt(p, P1_STOP_NO_ADDRESS, p->ip_tries);
		}
		if (!p->ping_ok) {
			return p1_halt(p, P1_STOP_NO_PING, p->ping_seq);
		}
		p->ops.log(p->ops.ctx, "net: gateway answered a ping in %u ms\n", p->ping_ms);
	}
	return 0;
}

/* ---- After the scan ---- */

int
b4_join_run(struct p1 *p)
{
	if (!p->cfg.join_armed) {
		/* Everything but the join. A key that opens nothing, and the gate would refuse the join if asked. Then the firmware's own word that the settings sent nothing either */
		if (read_join_ver(p) || configure(p) || b4_read_counters(p, 2) || b4_console(p)) {
			return (int)p->stop;
		}
		if (p->cnt_known[1] && p->cnt_known[2] && (p->cnt_frames[2] != p->cnt_frames[1] || p->cnt_probereq[2] != p->cnt_probereq[1] || p->cnt_probersp[2] != p->cnt_probersp[1])) {
			p->ops.log(p->ops.ctx, "join: the firmware counted transmits during the settings\n");
			return p1_halt(p, P1_STOP_TX_SEEN, p->cnt_frames[2] - p->cnt_frames[1]);
		}
		if (p->tx_items != 0) {
			return p1_halt(p, P1_STOP_TX_SEEN, p->tx_items);
		}
		p->dry_done = true;
		p->ops.log(p->ops.ctx, "join: dry run done: the join and every frame stay refused\n");
		return 0;
	}
	if (p->cfg.net == NULL) {
		return p1_halt(p, P1_STOP_NO_NETWORK, 1);
	}
	/* Counts only: which of the networks in the log it is stays unsaid */
	p->ops.log(p->ops.ctx, "join: the network was heard on %u records, %u of them not of the kind it should be\n", p->jn_seen, p->jn_refused_security);
	if (!p->jn_found) {
		return p1_halt(p, p->jn_seen != 0 ? P1_STOP_NET_SECURITY : P1_STOP_NOT_HEARD, p->jn_seen);
	}
	if (read_join_ver(p) || configure(p) || send_join(p) || join_wait(p)) {
		return (int)p->stop;
	}
	return net_run(p);
}

#endif /* BLAZER */
