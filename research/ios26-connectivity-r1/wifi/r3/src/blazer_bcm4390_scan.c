#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * BCM4390 from its first ioctls to one passive scan: RX buffers, CLM and TXCAP blobs, interface up, the scan, what it heard, and the firmware's own transmit counters either side of it.
 * One thread, polled, as blazer_bcm4390_ring.c. Own code; values and order are from Broadcom's DHD and its headers (GPL, facts only), and from Android's log on this phone.
 * Sources: bcm4390/dhd_common.c dhd_download_blob, dhd_apply_default_clm, _txcap; dhd_linux.c dhd_optimised_preinit_ioctls; dhd_cfg80211.c wl_dongle_up; wl_cfg80211.c __wl_cfg80211_up; wl_cfgscan.c wl_scan_prep, wl_run_escan, wl_escan_handler; bcmevent.c; wlioctl.h, wlioctl_defs.h, wlioctl_counters.h, bcmevent.h, bcmeth.h.
 *
 * Physical facts it stands on, Android on this phone, 20261027-112139-loop: "preinit_status IOVAR present", "RxBuf Post : 2048", "This FW is not included CLM data" then "CLM download succeeded" then WLC_E_COUNTRY_CODE_CHANGED to US, "txcap blob file : bcmdhd_txcap.blob_ROW", "axierror_logbuf_addr : 0x54f094", "CLM version = Google.BJ5".
 *
 * What it's for: the radio listens once. Nothing here joins, carries a key or asks for a frame to be sent.
 * - b4_ioctl_allowed is the one gate: an ioctl not on its list doesn't go, and an active escan can't be expressed. Going further than this file means changing that list.
 *   r3: armed, the join may also be Android's (wildcard address, 1-2 channels, its join scan's few probes for the one name), and a disassociation may follow it.
 * - The scan is passive by its flag, and its two flags against follow-up active scans are set: 6 GHz channels learned from RNR or FILS, and multi-link. No SSID, no channel list, no RNR request.
 * - The firmware's transmit counters are read either side, as a witness on the phone.
 *
 * What comes over the air is not to be trusted: SSIDs are logged as printable ASCII only and always as arguments, lengths are checked against the buffer before anything is read. BSSIDs are logged with their top half masked, so a log says what was heard without being a location fix. */
#include "blazer_hw_port.h"
#include "blazer_pcie1.h"

/* wl_dload_data_t: flag, dload_type, len, crc, data */
#define DL_HDR_BYTES    12u
#define DL_CHUNK        1408u           /* MAX_CHUNK_LEN */
#define DL_FLAG_VER     0x1000u         /* DLOAD_HANDLER_VER << DLOAD_FLAG_VER_SHIFT */
#define DL_FLAG_BEGIN   0x0002u
#define DL_FLAG_END     0x0004u
#define DL_TYPE_BLOB    2u              /* DL_TYPE_CLM, for TXCAP as well: dhd_download_blob */

/* wl_country_t */
#define CC_REV_AT       4u
#define CC_CODE_AT      8u
#define CC_NONE         "#n"            /* WL_CCODE_NULL_COUNTRY: no CLM data in the firmware */

/* eventmsgs_ext_t */
#define EVM_VER         1u              /* EVENTMSGS_VER */
#define EVM_SET_MASK    3u              /* EVENTMSGS_SET_MASK */
#define EVM_MASK_AT     4u
#define EVM_MASK_LEN    52u             /* WL_EVENTING_MASK_EXT_LEN */

/* wl_escan_params_v2, _v3, _v4 */
#define ESC_ACTION      4u
#define ESC_SYNC        6u
#define ESC_PARAMS      8u
#define ESC_START       1u              /* WL_SCAN_ACTION_START */
#define ESC_SYNC_ID     0x4b1du         /* Ours to choose: comes back in each result */
/* wl_scan_params_v2, _v3, _v4 */
#define SP_LENGTH       2u
#define SP_SSID_LEN     4u
#define SP_BSSID        40u
#define SP_BSS_TYPE     46u
#define SP_SCAN_TYPE    48u
#define SP3_NPROBES     52u
#define SP3_ACTIVE      56u
#define SP3_PASSIVE     60u
#define SP3_HOME        64u
#define SP3_CHANNEL_NUM 68u
#define SP3_BYTES       72u
#define SP4_TYPE_EXT    52u
#define SP4_NPROBES     56u
#define SP4_ACTIVE      60u
#define SP4_PASSIVE     64u
#define SP4_HOME        68u
#define SP4_CHANNEL_NUM 72u
#define SP4_BYTES       76u
#define BSSTYPE_ANY     2u              /* DOT11_BSSTYPE_ANY */
#define SF_PASSIVE      0x001u          /* WL_SCANFLAGS_PASSIVE */
#define SF_NO_6G_FOLLOW 0x100u          /* WL_SCANFLAGS_NO_6GHZ_FOLLOWUP */
#define SFX_NO_ML_FOLLOW 0x2u           /* WL_SCANFLAGS_EXT_NOMLOFOLLOWUP */
#define SF_NEVER        0x803cu         /* PROHIBITED, OFFCHAN, HOTSPOT (ANQP), SWTCHAN, LISTEN */
#define ESCAN_IOVAR     "escan"
#define PASSIVE_MS      130u            /* DHD_SCAN_PASSIVE_TIME */

/* wl_extjoin_params_v1, _v2, _v3 */
#define JP_SSID_LEN     4u
#define JP_SCAN         40u
#define JP_ASSOC        60u
#define JA_FLAGS        2u
#define JA_BSSID        4u
#define JA_BSSID_CNT    10u
#define JA_V1_NUM       12u
#define JA_V2_NUM       16u
#define JA_V3_NUM       20u
#define JS_PASSIVE      1u              /* DOT11_SCANTYPE_PASSIVE */
#define JS_DEFAULT      0u              /* "0 use default": r3 method 1, stock's join that isn't targeted */
#define JP_SCAN_NPROBES 44u
#define JP_SCAN_ACTIVE  48u
#define JP_SCAN_PASSIVE 52u
#define JP_SCAN_HOME    56u
#define JW_MAX_CHANS    2u              /* Android's chan_cnt:2 */
#define JW_ACTIVE_MS    80u             /* WL_BCAST_SCAN_JOIN_ACTIVE_DWELL_TIME_MS */
#define JW_NPROBES      4u              /* 80 / WL_SCAN_JOIN_PROBE_INTERVAL_MS */
#define JW_PASSIVE_MS   400u            /* WL_SCAN_JOIN_PASSIVE_DWELL_TIME_MS */

/* The frame in an event buffer: ether_header, bcmeth_hdr_t, wl_event_msg_t, data. The event's own fields are big endian */
#define ETHER_TYPE_AT   12u
#define ETHER_TYPE_BRCM 0x886cu
#define BCM_SUBTYPE_AT  14u
#define BCM_SUBTYPE     0x8001u         /* BCMILCP_SUBTYPE_VENDOR_LONG */
#define BCM_OUI_AT      19u
#define BCM_USR_AT      22u
#define BCM_USR_EVENT   1u              /* BCMILCP_BCM_SUBTYPE_EVENT */
#define EV_FLAGS_AT     26u
#define EV_TYPE_AT      28u
#define EV_STATUS_AT    32u
#define EV_REASON_AT    36u
#define EV_DATALEN_AT   44u
#define EV_DATA_AT      72u             /* sizeof(bcm_event_t) */
#define E_COUNTRY       47u             /* WLC_E_COUNTRY_CODE_CHANGED */
#define E_ESCAN         69u             /* WLC_E_ESCAN_RESULT */
#define ST_SUCCESS      0u              /* WLC_E_STATUS_SUCCESS */
#define ST_PARTIAL      8u              /* WLC_E_STATUS_PARTIAL */

/* wl_escan_result_v109_t, then one wl_bss_info_v109_t. Little endian */
#define ER_BUFLEN       0u
#define ER_SYNC         8u
#define ER_COUNT        10u
#define ER_BSS          12u
#define BI_LENGTH       4u
#define BI_BSSID        8u
#define BI_CAP          16u
#define BI_SSID_LEN     18u
#define BI_SSID         19u
#define BI_CHANSPEC     72u
#define BI_RSSI         78u
#define BI_CTL_CH       88u
#define BI_MIN_BYTES    132u            /* sizeof(wl_bss_info_v109_t). Every later one extends it: the fields above are at these offsets in all of 109 to 116 */
#define SSID_MAX        32u

/* Chanspec: WL_CHANSPEC_BAND_* */
#define CS_BAND_MASK    0xc000u
#define CS_BAND_2G      0x0000u
#define CS_BAND_6G      0x4000u
#define CS_BAND_5G      0xc000u

/* The counters iovar: wl_cnt_info_t, then xtlv tuples, each padded to 4 */
#define CNT_HDR         4u
#define CNT_TUPLE_HDR   4u
#define CNT_WLC         0x100u          /* WL_CNT_XTLV_WLC: wl_cnt_wlc_t, all uint32 */
#define CNT_W_FRAMES    0u              /* txframe */
#define CNT_W_PROBEREQ  172u            /* txprobereq */
#define CNT_W_PROBERSP  174u            /* txprobersp */
#define CNT_RAW_WORDS   4u

/* Status words */
#define E_BUSY          (-16)           /* BCME_BUSY */
#define E_NOTREADY      (-25)           /* BCME_NOTREADY */

/* Timing and limits */
#define SCAN_WAIT_MS    60000u          /* About 100 channels at 130 ms is 13 s, one radio at a time */
#define SCAN_TRIES      3u
#define SCAN_RETRY_MS   500u
#define CONSOLE_MS      1000u
#define SCAN_LOG_MAX    64u             /* Lines for networks. The rest are counted */
#define EV_LOG_MAX      40u             /* Lines for events other than scan results */

static void sc_put16(uint8_t *b, uint32_t at, uint16_t v) { memcpy(b + at, &v, 2); }
static void sc_put32(uint8_t *b, uint32_t at, uint32_t v) { memcpy(b + at, &v, 4); }
static uint16_t sc_get16(const uint8_t *b, uint32_t at) { uint16_t v; memcpy(&v, b + at, 2); return v; }
static uint32_t sc_get32(const uint8_t *b, uint32_t at) { uint32_t v; memcpy(&v, b + at, 4); return v; }
static uint16_t sc_be16(const uint8_t *b, uint32_t at) { return (uint16_t)((uint16_t)b[at] << 8 | b[at + 1]); }
static uint32_t sc_be32(const uint8_t *b, uint32_t at) { return (uint32_t)b[at] << 24 | (uint32_t)b[at + 1] << 16 | (uint32_t)b[at + 2] << 8 | b[at + 3]; }

static bool
sc_same(const uint8_t *a, const uint8_t *b, uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) {
		if (a[i] != b[i]) {
			return false;
		}
	}
	return true;
}

/* ---- The gate ---- */

static const struct {
	uint32_t cmd;
	const char *name;
	int level;              /* The lowest gate level it's allowed at. B4_GATE_ARMED: only that sends anything, and only the join and the frames after it do */
	bool is_scan, is_join;
} ioc_list[] = {
	{ WLC_GET_REVINFO, NULL }, { WLC_UP, NULL },
	{ WLC_GET_VAR, "wlc_ver" }, { WLC_GET_VAR, "ver" }, { WLC_GET_VAR, "preinit_status" }, { WLC_GET_VAR, "rxbufpost_sz" }, { WLC_GET_VAR, "axierror_logbuf_addr" }, { WLC_GET_VAR, "cur_etheraddr" },
	{ WLC_GET_VAR, "country" }, { WLC_GET_VAR, "clmver" }, { WLC_GET_VAR, "clmload_status" }, { WLC_GET_VAR, "txcapload_status" }, { WLC_GET_VAR, "event_msgs_ext" }, { WLC_GET_VAR, "scan_ver" }, { WLC_GET_VAR, "counters" },
	{ WLC_SET_VAR, "clmload" }, { WLC_SET_VAR, "txcapload" }, { WLC_SET_VAR, "event_msgs_ext" }, { WLC_SET_VAR, "bus:host_access" }, { WLC_SET_VAR, ESCAN_IOVAR, B4_GATE_PASSIVE, true },
	/* Settings: none of these sends anything by itself */
	{ WLC_GET_VAR, "cap", B4_GATE_DRY }, { WLC_GET_VAR, "join_ver", B4_GATE_DRY }, { WLC_SET_VAR, "country", B4_GATE_DRY }, { WLC_SET_VAR, "cur_etheraddr", B4_GATE_DRY }, { WLC_SET_VAR, "roam_off", B4_GATE_DRY },
	{ WLC_SET_VAR, "wpa_auth", B4_GATE_DRY }, { WLC_SET_VAR, "auth", B4_GATE_DRY }, { WLC_SET_VAR, "sup_wpa", B4_GATE_DRY }, { WLC_SET_VAR, "wsec", B4_GATE_DRY }, { WLC_SET_VAR, "mfp", B4_GATE_DRY }, { WLC_SET_WSEC_PMK, NULL, B4_GATE_DRY },
	/* r3 method 1, Android's: wsec_info (algos, the passphrase with the SSID, sae_pwe), join_pref, and the band it joined on. Settings too */
	{ WLC_SET_VAR, "wsec_info", B4_GATE_DRY }, { WLC_SET_VAR, "join_pref", B4_GATE_DRY }, { WLC_GET_VAR, "chanspec", B4_GATE_DRY },
	/* The ones that go on the air: the join, and between r3's two methods the disassociation */
	{ WLC_SET_VAR, "join", B4_GATE_ARMED, false, true }, { WLC_DISASSOC, NULL, B4_GATE_ARMED },
};

static bool
same_name(const uint8_t *buf, uint32_t len, const char *name)
{
	uint32_t i = 0;

	for (; i < len && name[i] != 0; i++) {
		if (buf[i] != (uint8_t)name[i]) {
			return false;
		}
	}
	return i < len && name[i] == 0 && buf[i] == 0;
}

/* Only what wl_scan_prep would build for a passive scan of everything: one start, no SSID, no channel list, and none of the flags that turn it into something else */
static bool
escan_passive(const uint8_t *e, uint32_t len)
{
	const uint8_t *sp = e + ESC_PARAMS;
	uint32_t ver, type;

	if (len < ESC_PARAMS + SP3_BYTES) {
		return false;
	}
	ver = sc_get32(e, 0);
	type = sc_get32(sp, SP_SCAN_TYPE);
	if (ver < 2 || ver > 4 || sc_get16(e, ESC_ACTION) != ESC_START || sc_get32(sp, SP_SSID_LEN) != 0 || !(type & SF_PASSIVE) || !(type & SF_NO_6G_FOLLOW) || (type & SF_NEVER) != 0) {
		return false;
	}
	if (ver == 4) {
		return len >= ESC_PARAMS + SP4_BYTES && sc_get32(sp, SP4_TYPE_EXT) == SFX_NO_ML_FOLLOW && sc_get32(sp, SP4_CHANNEL_NUM) == 0;
	}
	return sc_get32(sp, SP3_CHANNEL_NUM) == 0;
}

/* r3 method 1, only as wl_fillup_assoc_params fills a join that isn't targeted: one named network, the wildcard address, one or two channels,
 * the join scan's default type, at most 4 probes in 80 ms per channel, 400 ms passive, home time default. No flags, no BSSID list */
static bool
join_wildcard(const uint8_t *j, uint32_t len)
{
	uint32_t ver, num_at, num;
	const uint8_t *b = j + JP_ASSOC + JA_BSSID;

	if (len < JP_ASSOC + JA_V1_NUM + 6) {
		return false;
	}
	ver = sc_get16(j, 0);
	if (ver < 1 || ver > 3) {
		return false;
	}
	num_at = JP_ASSOC + (ver == 1 ? JA_V1_NUM : ver == 2 ? JA_V2_NUM : JA_V3_NUM);
	if (len < num_at + 4) {
		return false;
	}
	num = sc_get32(j, num_at);
	if (num < 1 || num > JW_MAX_CHANS || len != num_at + 4 + 2 * num || sc_get32(j, JP_SSID_LEN) == 0 || sc_get32(j, JP_SSID_LEN) > SSID_MAX) {
		return false;
	}
	if (j[JP_SCAN] != JS_DEFAULT || sc_get32(j, JP_SCAN_NPROBES) > JW_NPROBES || sc_get32(j, JP_SCAN_ACTIVE) > JW_ACTIVE_MS || sc_get32(j, JP_SCAN_PASSIVE) != JW_PASSIVE_MS ||
	    sc_get32(j, JP_SCAN_HOME) != 0xffffffffu) {
		return false;
	}
	for (unsigned i = 0; i < 6; i++) {
		if (b[i] != 0xff) {
			return false;
		}
	}
	for (uint32_t i = 0; i < num; i++) {
		if (sc_get16(j, num_at + 4 + 2 * i) == 0) {
			return false;
		}
	}
	return sc_get16(j, JP_ASSOC + JA_FLAGS) == 0 && sc_get16(j, JP_ASSOC + JA_BSSID_CNT) == 0;
}

/* Only a join for one named network at one address on one channel, finding it by listening. wl_extjoin_params_v1..3: all but the last fields the same */
static bool
join_targeted(const uint8_t *j, uint32_t len)
{
	uint32_t ver, num_at, want;
	const uint8_t *b = j + JP_ASSOC + JA_BSSID;
	bool any = false;

	if (len < JP_ASSOC + JA_V1_NUM + 6) {
		return false;
	}
	ver = sc_get16(j, 0);
	if (ver < 1 || ver > 3) {
		return false;
	}
	num_at = JP_ASSOC + (ver == 1 ? JA_V1_NUM : ver == 2 ? JA_V2_NUM : JA_V3_NUM);
	want = num_at + 4 + 2;
	if (len != want || sc_get32(j, JP_SSID_LEN) == 0 || sc_get32(j, JP_SSID_LEN) > SSID_MAX || j[JP_SCAN] != JS_PASSIVE) {
		return false;
	}
	for (unsigned i = 0; i < 6; i++) {
		any = any || b[i] != 0;
	}
	return any && (b[0] & 1u) == 0 && sc_get16(j, JP_ASSOC + JA_FLAGS) == 0 && sc_get16(j, JP_ASSOC + JA_BSSID_CNT) == 0 && sc_get32(j, num_at) == 1;
}

int
b4_gate_level(const struct p1 *p)
{
	if (p->cfg.stage < P1_STAGE_JOIN) {
		return B4_GATE_PASSIVE;
	}
	return p->cfg.join_armed ? B4_GATE_ARMED : B4_GATE_DRY;
}

bool
b4_ioctl_allowed(uint32_t cmd, const uint8_t *buf, uint32_t len, int level)
{
	for (unsigned i = 0; i < sizeof(ioc_list) / sizeof(ioc_list[0]); i++) {
		if (ioc_list[i].cmd != cmd || ioc_list[i].level > level) {
			continue;
		}
		if (ioc_list[i].name == NULL) {
			return true;
		}
		if (same_name(buf, len, ioc_list[i].name)) {
			if (ioc_list[i].is_join) {
				return join_targeted(buf + sizeof("join"), len - (uint32_t)sizeof("join")) || join_wildcard(buf + sizeof("join"), len - (uint32_t)sizeof("join"));
			}
			return !ioc_list[i].is_scan || escan_passive(buf + sizeof(ESCAN_IOVAR), len - (uint32_t)sizeof(ESCAN_IOVAR));
		}
	}
	return false;
}

/* ---- Small things ---- */

static uint32_t
iov_name(uint8_t *buf, uint32_t bytes, const char *name)
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
get_u32(struct p1 *p, const char *name, uint32_t *v, int32_t *status)
{
	uint8_t b[64];

	(void)iov_name(b, sizeof(b), name);
	if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(b))) {
		return (int)p->stop;
	}
	*status = p->ioc_status;
	*v = sc_get32(b, 0);
	return 0;
}

/* To one line of printable ASCII, for anything the firmware or the air said. A double quote goes too, so a line can't be made to look like another */
static void
to_text(char *out, uint32_t out_bytes, const uint8_t *in, uint32_t in_bytes)
{
	uint32_t n = 0;

	for (uint32_t i = 0; i < in_bytes && in[i] != 0 && n + 1 < out_bytes; i++) {
		out[n++] = (in[i] >= 32 && in[i] < 127 && in[i] != '"') ? (char)in[i] : '?';
	}
	out[n] = 0;
}

/* ---- Events: stock's is_wlc_event_frame, wl_escan_handler ---- */

static void
on_network(struct p1 *p, const uint8_t *bi, uint32_t bi_bytes)
{
	uint32_t ssid_len = bi[BI_SSID_LEN];
	uint16_t cs = sc_get16(bi, BI_CHANSPEC);
	char ssid[SSID_MAX + 1];
	unsigned band;
	bool hidden = true;

	if (p->scan_results == 0) {
		p->ops.log(p->ops.ctx, "scan: first result, record version %u, %u bytes. Stock reads them as 109\n", sc_get32(bi, 0), sc_get32(bi, BI_LENGTH));
	}
	p->scan_results++;
	if (p->cfg.stage >= P1_STAGE_JOIN) {
		b4_join_heard(p, bi, bi_bytes);
	}
	if (ssid_len > SSID_MAX) {
		p->scan_bad++;
		return;
	}
	for (uint32_t i = 0; i < p->scan_nets && i < sizeof(p->scan_seen) / sizeof(p->scan_seen[0]); i++) {
		if (sc_same(p->scan_seen[i], bi + BI_BSSID, 6)) {
			return;
		}
	}
	if (p->scan_nets >= sizeof(p->scan_seen) / sizeof(p->scan_seen[0])) {
		p->scan_more++;
		return;
	}
	memcpy(p->scan_seen[p->scan_nets], bi + BI_BSSID, 6);
	p->scan_nets++;
	band = (cs & CS_BAND_MASK) == CS_BAND_2G ? 0 : (cs & CS_BAND_MASK) == CS_BAND_5G ? 1 : 2;
	p->scan_band[band]++;
	/* From stage JOIN on nothing about any network is logged one by one: the one to join is among them */
	if (p->scan_nets > SCAN_LOG_MAX || p->cfg.stage >= P1_STAGE_JOIN) {
		return;
	}
	for (uint32_t i = 0; i < ssid_len; i++) {
		if (bi[BI_SSID + i] != 0) {
			hidden = false;
		}
	}
	to_text(ssid, sizeof(ssid), bi + BI_SSID, ssid_len);
	p->ops.log(p->ops.ctx, "scan: %u: \"%s\", xx:xx:xx:%02x:%02x:%02x, channel %u, %s GHz, chanspec 0x%04x, RSSI %d, capability 0x%x\n", p->scan_nets, hidden ? "(hidden)" : ssid,
	    bi[BI_BSSID + 3], bi[BI_BSSID + 4], bi[BI_BSSID + 5], bi[BI_CTL_CH] != 0 ? bi[BI_CTL_CH] : (uint32_t)(cs & 0xffu), band == 0 ? "2.4" : band == 1 ? "5" : "6", cs, (int16_t)sc_get16(bi, BI_RSSI), sc_get16(bi, BI_CAP));
}

static void
on_escan(struct p1 *p, uint32_t status, const uint8_t *d, uint32_t bytes)
{
	if (!p->scan_running) {
		p->ev_other++;
		return;
	}
	if (status != ST_PARTIAL) {
		/* The last event of a scan may carry nothing past its status */
		if (bytes >= ER_COUNT && sc_get16(d, ER_SYNC) != ESC_SYNC_ID) {
			p->ops.log(p->ops.ctx, "scan: an end, status %u, for sync id 0x%x, not ours\n", status, sc_get16(d, ER_SYNC));
			p->ev_other++;
			return;
		}
		p->scan_status = status;
		p->scan_done = true;
		return;
	}
	if (bytes < ER_BSS + BI_MIN_BYTES || sc_get16(d, ER_SYNC) != ESC_SYNC_ID) {
		p->scan_bad++;
		return;
	}
	{
		uint32_t buflen = sc_get32(d, ER_BUFLEN), bi_len = sc_get32(d, ER_BSS + BI_LENGTH);

		if (buflen > bytes || buflen < ER_BSS + BI_MIN_BYTES || sc_get16(d, ER_COUNT) != 1 || bi_len != buflen - ER_BSS) {
			p->scan_bad++;
			return;
		}
		on_network(p, d + ER_BSS, bi_len);
	}
}

void
b4_on_event(struct p1 *p, const uint8_t *f, uint32_t bytes)
{
	static const uint8_t oui[3] = { 0x00, 0x10, 0x18 };     /* BRCM_OUI */
	uint32_t type, status, data_len;

	if (bytes < EV_DATA_AT || sc_be16(f, ETHER_TYPE_AT) != ETHER_TYPE_BRCM || sc_be16(f, BCM_SUBTYPE_AT) != BCM_SUBTYPE || !sc_same(f + BCM_OUI_AT, oui, sizeof(oui))) {
		p->ev_bad++;
		return;
	}
	if (sc_be16(f, BCM_USR_AT) != BCM_USR_EVENT) {
		p->ev_other++;  /* BCMILCP_BCM_SUBTYPE_DNGLEVENT: the firmware's health events, for stock's logs */
		return;
	}
	type = sc_be32(f, EV_TYPE_AT);
	status = sc_be32(f, EV_STATUS_AT);
	data_len = sc_be32(f, EV_DATALEN_AT);
	if (p->cfg.stage >= P1_STAGE_JOIN && b4_join_event(p, type, status, sc_be32(f, EV_REASON_AT), sc_be16(f, EV_FLAGS_AT))) {
		return;
	}
	if (data_len > bytes - EV_DATA_AT) {
		p->ev_bad++;
		return;
	}
	if (type == E_ESCAN) {
		on_escan(p, status, f + EV_DATA_AT, data_len);
		return;
	}
	p->ev_other++;
	if (p->ev_logged < EV_LOG_MAX) {
		p->ev_logged++;
		if (type == E_COUNTRY) {
			char cc[8];

			to_text(cc, sizeof(cc), f + EV_DATA_AT, data_len);
			p->ops.log(p->ops.ctx, "event: country code changed to %s. Android, after its CLM: US\n", cc);
		} else {
			p->ops.log(p->ops.ctx, "event: type %u, status %u, reason %u, %u bytes\n", type, status, sc_be32(f, EV_REASON_AT), data_len);
		}
	}
}

/* ---- Blobs: dhd_download_blob, dhd_download_2_dongle ---- */

static int
blob_load(struct p1 *p, const char *iovar, const char *status_iovar, const struct p1_image *img, bool *ok)
{
	uint8_t *b = p->ioc_big;
	uint32_t done = 0, chunks = 0;
	uint16_t flag = DL_FLAG_BEGIN;
	uint64_t t0 = p->ops.now_us(p->ops.ctx);

	*ok = false;
	p->ops.log(p->ops.ctx, "blob: next: %s, %u bytes, by %s\n", img->name != NULL ? img->name : "?", img->size, iovar);
	if (img->data == NULL || img->size == 0) {
		return 0;
	}
	while (done < img->size) {
		uint32_t chunk = img->size - done < DL_CHUNK ? img->size - done : DL_CHUNK;
		uint32_t at = iov_name(b, sizeof(p->ioc_big), iovar);

		if (done + chunk == img->size) {
			flag |= DL_FLAG_END;
		}
		sc_put16(b, at, (uint16_t)(DL_FLAG_VER | flag));
		sc_put16(b, at + 2, DL_TYPE_BLOB);
		sc_put32(b, at + 4, chunk);
		sc_put32(b, at + 8, 0);
		memcpy(b + at + DL_HDR_BYTES, img->data + done, chunk);
		if (b4_ioctl(p, WLC_SET_VAR, b, (uint16_t)(at + ((DL_HDR_BYTES + chunk + 7u) & ~7u)))) {
			return (int)p->stop;
		}
		chunks++;
		if (p->ioc_status != 0) {
			uint32_t st = 0;
			int32_t err = p->ioc_status, st_err = 0;

			if (get_u32(p, status_iovar, &st, &st_err)) {
				return (int)p->stop;
			}
			p->ops.log(p->ops.ctx, "blob: %s: chunk %u, offset %u: status %d. %s reads %u, status %d\n", iovar, chunks, done, err, status_iovar, st, st_err);
			return 0;
		}
		flag &= (uint16_t)~DL_FLAG_BEGIN;
		done += chunk;
	}
	*ok = true;
	p->ops.log(p->ops.ctx, "blob: %s took all of it: %u chunks, %u ms\n", iovar, chunks, (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000));
	return 0;
}

/* dhd_check_current_clm_data's read. The ccode says whether the firmware has CLM data at all */
static int
read_country(struct p1 *p, bool *has_clm)
{
	uint8_t b[64];
	char abbrev[8], code[8];

	*has_clm = false;
	(void)iov_name(b, sizeof(b), "country");
	if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(b))) {
		return (int)p->stop;
	}
	if (p->ioc_status != 0) {
		p->ops.log(p->ops.ctx, "country: status %d\n", p->ioc_status);
		return 0;
	}
	to_text(abbrev, 4, b, 4);
	to_text(code, 4, b + CC_CODE_AT, 4);
	p->ops.log(p->ops.ctx, "country: abbreviation %s, revision %d, code %s\n", abbrev, (int32_t)sc_get32(b, CC_REV_AT), code);
	*has_clm = code[0] != 0 && !sc_same((const uint8_t *)code, (const uint8_t *)CC_NONE, sizeof(CC_NONE));
	if (*has_clm) {
		memcpy(p->country, code, sizeof(p->country));
	}
	return 0;
}

static int
load_clm_txcap(struct p1 *p)
{
	uint8_t b[256];
	bool has = false;

	if (read_country(p, &has)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "blob: firmware %s CLM data of its own. Android, here: none\n", has ? "has" : "has no");
	if (blob_load(p, "clmload", "clmload_status", &p->cfg.clm, &p->clm_loaded)) {
		return (int)p->stop;
	}
	if (!p->clm_loaded) {
		return p1_halt(p, P1_STOP_CLM, 1);
	}
	if (read_country(p, &has)) {
		return (int)p->stop;
	}
	if (!has) {
		return p1_halt(p, P1_STOP_CLM, 2);     /* As stock: fail the bring-up */
	}
	/* Stock goes on if this one fails, and TX power caps don't matter to a radio that doesn't send */
	if (blob_load(p, "txcapload", "txcapload_status", &p->cfg.txcap, &p->txcap_loaded)) {
		return (int)p->stop;
	}
	(void)iov_name(b, sizeof(b), "clmver");
	if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(b))) {
		return (int)p->stop;
	}
	if (p->ioc_status == 0) {
		to_text(p->clm_ver, sizeof(p->clm_ver), b, p->ioc_got_len);
		p->ops.log(p->ops.ctx, "blob: clmver: %s. Android's reads: Google.BJ5\n", p->clm_ver);
	} else {
		p->ops.log(p->ops.ctx, "blob: clmver: status %d\n", p->ioc_status);
	}
	return 0;
}

/* The firmware's pre-init sets its own mask, stock's optimised path relies on it. Here it's read, and the one bit this needs is added if it isn't there */
static int
event_mask(struct p1 *p)
{
	uint8_t b[256], m[EVM_MASK_LEN];
	uint32_t n = iov_name(b, sizeof(b), "event_msgs_ext"), have;

	b[n] = EVM_VER;
	b[n + 2] = EVM_MASK_LEN;
	if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(b))) {
		return (int)p->stop;
	}
	if (p->ioc_status != 0) {
		p->ops.log(p->ops.ctx, "event: mask: status %d. Going on without knowing\n", p->ioc_status);
		return 0;
	}
	have = b[2] < EVM_MASK_LEN ? b[2] : EVM_MASK_LEN;
	memset(m, 0, sizeof(m));
	memcpy(m, b + EVM_MASK_AT, have);
	p->ops.log(p->ops.ctx, "event: mask, %u bytes, starts %02x %02x %02x %02x %02x %02x %02x %02x %02x. Scan results %s\n", have, m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8],
	    (m[E_ESCAN / 8] & (1u << (E_ESCAN % 8))) ? "on" : "off: turning them on");
	if (m[E_ESCAN / 8] & (1u << (E_ESCAN % 8))) {
		return 0;
	}
	m[E_ESCAN / 8] |= (uint8_t)(1u << (E_ESCAN % 8));
	n = iov_name(b, sizeof(b), "event_msgs_ext");
	b[n] = EVM_VER;
	b[n + 1] = EVM_SET_MASK;
	b[n + 2] = EVM_MASK_LEN;
	memcpy(b + n + EVM_MASK_AT, m, sizeof(m));
	if (b4_ioctl(p, WLC_SET_VAR, b, (uint16_t)(n + EVM_MASK_AT + sizeof(m)))) {
		return (int)p->stop;
	}
	if (p->ioc_status != 0) {
		p->ops.log(p->ops.ctx, "event: setting the mask: status %d\n", p->ioc_status);
	}
	return 0;
}

/* wl_dongle_up, with WLAN_ACCEL_BOOT, as stock's build: first the firmware is told it may use host memory, and a failure there is only logged */
static int
wl_up(struct p1 *p)
{
	uint8_t b[32];
	uint32_t n = iov_name(b, sizeof(b), "bus:host_access");
	uint64_t t0;

	sc_put32(b, n, 1);
	if (b4_ioctl(p, WLC_SET_VAR, b, (uint16_t)(n + 4))) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "up: bus:host_access to 1: status %d. Next: WLC_UP\n", p->ioc_status);
	memset(b, 0, sizeof(b));
	t0 = p->ops.now_us(p->ops.ctx);
	if (b4_ioctl(p, WLC_UP, b, 4)) {
		return (int)p->stop;
	}
	p->up_ms = (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000);
	p->ops.log(p->ops.ctx, "up: status %d, %u ms\n", p->ioc_status, p->up_ms);
	if (p->ioc_status != 0) {
		return p1_halt(p, P1_STOP_WL_UP, (uint32_t)p->ioc_status);
	}
	p->wl_up = true;
	return 0;
}

/* ---- The firmware's own count of what it sent ---- */

int
b4_read_counters(struct p1 *p, unsigned when)
{
	uint8_t *b = p->ioc_big;
	uint32_t at = CNT_HDR, end, tuples = 0;

	p->cnt_known[when] = false;
	(void)iov_name(b, sizeof(p->ioc_big), "counters");
	if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(p->ioc_big))) {
		return (int)p->stop;
	}
	if (p->ioc_status != 0 || p->ioc_got_len < CNT_HDR) {
		p->ops.log(p->ops.ctx, "tx: counters: status %d, %u bytes\n", p->ioc_status, p->ioc_got_len);
		return 0;
	}
	end = CNT_HDR + (uint32_t)sc_get16(b, 2);
	if (end > p->ioc_got_len) {
		end = p->ioc_got_len;
	}
	p->ops.log(p->ops.ctx, "tx: counters %s: version %u, %u bytes\n", when == 0 ? "before the scan" : when == 1 ? "after the scan" : "after the settings", sc_get16(b, 0), end);
	p->cnt_frames[when] = p->cnt_probereq[when] = p->cnt_probersp[when] = 0;
	while (at + CNT_TUPLE_HDR <= end) {
		uint32_t id = sc_get16(b, at), len = sc_get16(b, at + 2), d = at + CNT_TUPLE_HDR;
		uint32_t w[CNT_RAW_WORDS] = { 0 };

		if (len > end - d) {
			break;
		}
		for (unsigned i = 0; i < CNT_RAW_WORDS && (i + 1) * 4 <= len; i++) {
			w[i] = sc_get32(b, d + i * 4);
		}
		p->ops.log(p->ops.ctx, "tx: tuple 0x%x, %u bytes: %08x %08x %08x %08x\n", id, len, w[0], w[1], w[2], w[3]);
		if (id == CNT_WLC && len >= (CNT_W_PROBERSP + 1) * 4) {
			p->cnt_known[when] = true;
			p->cnt_frames[when] += sc_get32(b, d + CNT_W_FRAMES * 4);
			p->cnt_probereq[when] += sc_get32(b, d + CNT_W_PROBEREQ * 4);
			p->cnt_probersp[when] += sc_get32(b, d + CNT_W_PROBERSP * 4);
		}
		tuples++;
		at = d + ((len + 3u) & ~3u);
	}
	if (p->cnt_known[when]) {
		p->ops.log(p->ops.ctx, "tx: %u tuples. Data frames %u, probe requests %u, probe responses %u\n", tuples, p->cnt_frames[when], p->cnt_probereq[when], p->cnt_probersp[when]);
	} else {
		p->ops.log(p->ops.ctx, "tx: %u tuples, no wlc counters among them\n", tuples);
	}
	return 0;
}

/* ---- The scan: wl_scan_prep, wl_run_escan ---- */

static uint16_t
scan_build(uint8_t *b, uint32_t bytes, uint32_t ver)
{
	uint32_t n = iov_name(b, bytes, ESCAN_IOVAR);
	uint8_t *e = b + n, *sp = e + ESC_PARAMS;
	bool v4 = ver == 4;

	sc_put32(e, 0, ver);
	sc_put16(e, ESC_ACTION, ESC_START);
	sc_put16(e, ESC_SYNC, ESC_SYNC_ID);
	sc_put16(sp, 0, (uint16_t)ver);
	sc_put16(sp, SP_LENGTH, v4 ? SP4_BYTES : SP3_BYTES);
	memset(sp + SP_BSSID, 0xff, 6);
	sp[SP_BSS_TYPE] = BSSTYPE_ANY;
	sc_put32(sp, SP_SCAN_TYPE, SF_PASSIVE | SF_NO_6G_FOLLOW);
	if (v4) {
		sc_put32(sp, SP4_TYPE_EXT, SFX_NO_ML_FOLLOW);
	}
	sc_put32(sp, v4 ? SP4_NPROBES : SP3_NPROBES, 0xffffffffu);
	sc_put32(sp, v4 ? SP4_ACTIVE : SP3_ACTIVE, 0xffffffffu);
	sc_put32(sp, v4 ? SP4_PASSIVE : SP3_PASSIVE, PASSIVE_MS);
	sc_put32(sp, v4 ? SP4_HOME : SP3_HOME, 0xffffffffu);
	return (uint16_t)(n + ESC_PARAMS + (v4 ? SP4_BYTES : SP3_BYTES));
}

static int
scan_start(struct p1 *p)
{
	uint8_t b[128];

	(void)iov_name(b, sizeof(b), "scan_ver");
	if (b4_ioctl(p, WLC_GET_VAR, b, sizeof(b))) {
		return (int)p->stop;
	}
	/* wl_scan_version_t: scan_ver_major at 4 */
	p->scan_ver = sc_get16(b, 4);
	p->ops.log(p->ops.ctx, "scan: scan_ver: status %d, major %u\n", p->ioc_status, p->scan_ver);
	if (p->ioc_status != 0 || p->scan_ver < 2 || p->scan_ver > 4) {
		return p1_halt(p, P1_STOP_SCAN_VERSION, p->scan_ver);
	}
	p->scan_running = true;
	for (uint32_t t = 1;; t++) {
		uint16_t len = scan_build(b, sizeof(b), p->scan_ver);

		p->ops.log(p->ops.ctx, "scan: next: passive, every channel, %u ms each, no follow-ups\n", PASSIVE_MS);
		if (b4_ioctl(p, WLC_SET_VAR, b, len)) {
			return (int)p->stop;
		}
		if (p->ioc_status == 0) {
			return 0;
		}
		p->ops.log(p->ops.ctx, "scan: try %u: status %d\n", t, p->ioc_status);
		if ((p->ioc_status != E_BUSY && p->ioc_status != E_NOTREADY) || t >= SCAN_TRIES) {
			return p1_halt(p, P1_STOP_SCAN_START, (uint32_t)p->ioc_status);
		}
		for (uint32_t ms = 0; ms < SCAN_RETRY_MS; ms++) {
			if (b4_poll(p)) {
				return (int)p->stop;
			}
			p->ops.delay_us(p->ops.ctx, 1000);
		}
	}
}

static int
scan_wait(struct p1 *p)
{
	uint64_t t0 = p->ops.now_us(p->ops.ctx);
	uint32_t next_console = CONSOLE_MS;

	while (!p->scan_done) {
		uint32_t ms = (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000);

		if (b4_poll(p)) {
			return (int)p->stop;
		}
		if (p->scan_done) {
			break;
		}
		if (ms >= SCAN_WAIT_MS) {
			p->ops.log(p->ops.ctx, "scan: no end in %u ms: %u results, %u networks, %u unreadable\n", ms, p->scan_results, p->scan_nets, p->scan_bad);
			return p1_halt(p, P1_STOP_SCAN_TIMEOUT, p->scan_results);
		}
		/* What it says as it goes: its console is a ring, and an 8 KiB one won't hold a whole scan */
		if (ms >= next_console) {
			next_console = ms + CONSOLE_MS;
			if (b4_console(p)) {
				return (int)p->stop;
			}
		}
		p->ops.delay_us(p->ops.ctx, 1000);
	}
	p->scan_ms = (uint32_t)((p->ops.now_us(p->ops.ctx) - t0) / 1000);
	p->scan_running = false;
	return 0;
}

int
b4_scan(struct p1 *p)
{
	uint32_t v = 0;
	int32_t err = 0;
	uint8_t mac[64];

	/* dhd_sync_with_dongle: the size, then the buffers */
	if (get_u32(p, "rxbufpost_sz", &v, &err)) {
		return (int)p->stop;
	}
	p->rxpost_size = v & 0xffffu;
	p->ops.log(p->ops.ctx, "rx: rxbufpost_sz: status %d, %u. Android: 2048\n", err, p->rxpost_size);
	if (b4_rx_post_all(p)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "rx: %u buffers posted\n", p->rx_posted);
	/* dhd_preinit_ioctls: which of stock's two routes. This is the short one. Read, for the log */
	if (get_u32(p, "preinit_status", &p->preinit_status, &p->preinit_err)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "preinit: preinit_status: status %d, value %u. Android's is present\n", p->preinit_err, p->preinit_status);
	if (get_u32(p, "axierror_logbuf_addr", &p->axierror_addr, &err)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "preinit: axierror_logbuf_addr: status %d, 0x%x. Android: 0x54f094 with its shared area at 0x5ae000. This one's at 0x%x\n", err, p->axierror_addr, p->shared_addr);
	/* Read, never set. A radio that doesn't send has no use for one, and the first three bytes are enough to tell whose it is */
	(void)iov_name(mac, sizeof(mac), "cur_etheraddr");
	if (b4_ioctl(p, WLC_GET_VAR, mac, sizeof(mac))) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "preinit: firmware's own MAC address: status %d, %02x:%02x:%02x:xx:xx:xx\n", p->ioc_status, mac[0], mac[1], mac[2]);
	/* A failed/short GET can leave the request name in mac. Only a complete
	 * successful response may supply the address used by en0/discovery. */
	memset(p->mac, 0, sizeof(p->mac));
	if (p->ioc_status == 0 && p->ioc_got_len >= sizeof(p->mac)) {
		memcpy(p->mac, mac, sizeof(p->mac));
	}
	if (p->cfg.stage >= P1_STAGE_JOIN && b4_join_pre_clm(p)) {
		return (int)p->stop;
	}
	if (load_clm_txcap(p) || (p->cfg.stage >= P1_STAGE_JOIN && b4_join_pre_up(p)) || event_mask(p) || wl_up(p)) {
		return (int)p->stop;
	}
	if (b4_read_counters(p, 0) || b4_console(p) || scan_start(p) || scan_wait(p)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "scan: ended, status %u, %u ms: %u results, %u networks: %u on 2.4 GHz, %u on 5 GHz, %u on 6 GHz, %u more past the table, %u unreadable. Events: %u others, %u unreadable\n", p->scan_status, p->scan_ms,
	    p->scan_results, p->scan_nets, p->scan_band[0], p->scan_band[1], p->scan_band[2], p->scan_more, p->scan_bad, p->ev_other, p->ev_bad);
	if (b4_read_counters(p, 1) || b4_console(p)) {
		return (int)p->stop;
	}
	p->ops.log(p->ops.ctx, "rx: %u items back, %u bytes in them. tx: %u completion items\n", p->rx_items, p->rx_bytes, p->tx_items);
	if (p->cnt_known[0] && p->cnt_known[1] && (p->cnt_frames[1] != p->cnt_frames[0] || p->cnt_probereq[1] != p->cnt_probereq[0] || p->cnt_probersp[1] != p->cnt_probersp[0])) {
		return p1_halt(p, P1_STOP_TX_SEEN, p->cnt_probereq[1] - p->cnt_probereq[0]);
	}
	if (p->tx_items != 0) {
		return p1_halt(p, P1_STOP_TX_SEEN, p->tx_items);
	}
	if (p->scan_status != ST_SUCCESS) {
		return p1_halt(p, P1_STOP_SCAN_ENDED, p->scan_status);
	}
	if (p->scan_nets == 0) {
		return p1_halt(p, P1_STOP_SCAN_EMPTY, p->scan_results);
	}
	return p->cfg.stage >= P1_STAGE_JOIN ? b4_join_run(p) : 0;
}

#endif /* BLAZER */
