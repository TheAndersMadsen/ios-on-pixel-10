/*
 * tgl_ufs — UFS probe ladder U0-U9 + honest-handoff cmdline gate.
 * See tgl_ufs.h for the contract; probe-ladder.md for the G4 spec this
 * implements (stamp ids re-seated 0x0030..0x003b -> 0x0048..0x0054 after
 * the R1 display block took 0x0031..0x0046 — P2 correction, 2026-10-28).
 *
 * Every SCSI/UFSHCI constant here is deliberately identical to the kernel
 * driver bsd/dev/hakios.blazer_ufs.c (single-slot legacy list, doorbell
 * bit 0, IID_ONE, OCS_INVALID, 256 KiB PRDT chunks, 1 MiB bounce, success
 * chain OCS 0 + resp 0x21 + tag + status 0): the ladder is a rehearsal of
 * exactly what XNU mode 2 will do after us, and a failed probe leaves the
 * host no dirtier than a successful one.
 *
 * Depth layering (probe-ladder.md U2/U3, one layer per boot): a DEAD U1
 * arms the CPM clocks (U2) and, only while still dead, the phy_rst
 * deassert (U3), each re-reading the whitelist afterwards — one boot
 * learns one depth, stamps name the exact layer that worked or failed.
 * A LIVE U1 never gets gated: U2/U3 are skipped unconditionally.
 */
#include "tgl_ufs.h"
#include "probe.h"
#include "tgl_stamp.h"
#include "tgl_cpm.h"
#include "laguna_usb.h"
#include "guard.h"

/* Per-descriptor LPCM seq byte (tgl_cpm.c wire truth; DEVICE-VALIDATE for
 * the LSIO/lpcm-0x06 domain — the only wire-proven seq is hsio's 0x05). */
#define TGL_UFS_LPCM_SEQ	0x05u
/* lpcm 0x06 (LSIO) ids from the laguna DT (probe-ladder.md 0). */
#define TGL_UFS_CLK_GPIO_REF	0x03u
#define TGL_UFS_CLK_AUX		0x10u
#define TGL_UFS_RST_PHY		0x03u

static struct {
	unsigned attempted;
	struct tgl_ufs_result r;
	/* v3.9b (U1): runtime region bases — FDT-driven (fix A) with the
	 * DT-verified constants as fallback. ufs.trap_latched makes the
	 * guard-unwind fail path one-shot (fix B). */
	uint64_t hc_pa;
	uint64_t psm_pa[3];
	unsigned trap_latched;
} ufs = {
	.hc_pa = TGL_UFS_HC_PA,
	.psm_pa = { TGL_UFS_PSM_HSIOS, TGL_UFS_PSM_HC, TGL_UFS_PSM_PHY },
};

uint64_t tgl_ufs_hc_base(void) { return ufs.hc_pa; }

void tgl_ufs_set_regions(uint64_t hc, const uint64_t psm[3])
{
	/* Refuse obviously-wrong overrides; the fallback constants stay
	 * armed (they equal the authoritative blazer MP DTB values, so the
	 * expected-tree override is a no-op in practice). */
	if (!hc || (hc & 0xfffu)) return;
	ufs.hc_pa = hc;
	if (psm) {
		if (psm[0]) ufs.psm_pa[0] = psm[0];
		if (psm[1]) ufs.psm_pa[1] = psm[1];
		if (psm[2]) ufs.psm_pa[2] = psm[2];
	}
}

/* ---- freestanding helpers (shim has no libc) -------------------------- */

static int u_seq(const uint8_t *a, const char *b, unsigned cap)
{
	for (unsigned i = 0; i < cap; i++) {
		if (a[i] != (uint8_t)b[i]) return (int)a[i] - (int)(uint8_t)b[i];
		if (!a[i]) return 0;
	}
	return 0;
}

static void *u_copy(void *d, const void *s, unsigned n)
{
	uint8_t *dd = d;
	const uint8_t *ss = s;
	while (n--) *dd++ = *ss++;
	return d;
}

/* clang lowers small byte loops to these even under -ffreestanding; the
 * shim has no libc, so provide the ABI symbols (device build fix). */
void *memcpy(void *d, const void *s, unsigned long n)
{
	return u_copy(d, s, (unsigned)n);
}

void *memset(void *d, int c, unsigned long n)
{
	uint8_t *dd = d;
	while (n--) *dd++ = (uint8_t)c;
	return d;
}

/* Bounded ~10 ms spin (aarch64). Compiles to nothing on the host, where
 * the synthetic device completes synchronously and the doorbell poll
 * below exits on its first iteration. The poll's own iteration guard
 * keeps a frozen arch timer from becoming an infinite wait on device. */
static void u_delay_10ms(void)
{
#if defined(__aarch64__) && !defined(TGL_STAMP_HOST)
	for (volatile unsigned i = 0; i < 400000u; i++) ;
#endif
}

#if TGL_UFS_HIBERN8_EXIT /* settle helper: the ladder's exit block below
 * keeps the bare '#if TGL_UFS_HIBERN8_EXIT' spelling the structural
 * suite anchors index() on */
/* Counter-bounded Hibern8-exit settle (F4 defect fix, m2-hibern8 decode
 * finding F2): the u_delay_10ms() call this replaces was an uncalibrated
 * volatile 400000-iteration busy loop that consumed 4.3 s of the ladder on
 * hardware (stamp gap 14222.8 -> 18536.3, ~430x its nominal settle). Same
 * deadline discipline as uf_uic_wait: read cntfrq_el0/cntpct_el0, wait
 * until cntpct >= start + ceil(10 ms * freq), with the same iteration
 * guard so a frozen timer cannot extend the wait indefinitely. Host:
 * no-op, mirroring u_delay_10ms (the synthetic device completes
 * synchronously); TGL_UFS_TEST_TIMER drives the counter seam. */
static void u_settle_10ms(void)
{
#if (defined(__aarch64__) && !defined(TGL_STAMP_HOST)) || \
    defined(TGL_UFS_TEST_TIMER)
	uint64_t freq, ticks, start, now;
#ifdef TGL_UFS_TEST_TIMER
	freq = tgl_ufs_test_counter_frequency();
	start = tgl_ufs_test_counter_now();
#else
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(start));
#endif
	if (!freq) freq = UINT64_C(38400000);
	ticks = freq / 100 + (freq % 100 ? 1 : 0); /* ceil(freq * 10 ms) */
	for (unsigned i = 0; i < 1000000u; i++) {
#ifdef TGL_UFS_TEST_TIMER
		now = tgl_ufs_test_counter_now();
#else
		__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(now));
#endif
		if (now - start >= ticks) return;
#ifndef TGL_UFS_TEST_TIMER
		__asm__ volatile("yield");
#endif
	}
#endif
}
#endif /* TGL_UFS_HIBERN8_EXIT */

/* ---- MMIO (fault-gated, probe.c discipline) --------------------------- */

static int uf_rd(uint32_t off, uint32_t *v)
{
	return probe_read32((uintptr_t)(ufs.hc_pa + off), v) ? 0 : -1;
}

static int uf_wr(uint32_t off, uint32_t v)
{
	return probe_write32((uintptr_t)(ufs.hc_pa + off), v) ? 0 : -1;
}

/* ---- EP0 evidence ------------------------------------------------------ */

static void uf_log(const char *line)
{
	laguna_usb_log(line);
}

static void uf_hex(char *buf, unsigned cap, const char *label, uint64_t v)
{
	static const char digits[] = "0123456789abcdef";
	unsigned p = 0;
	while (label[p] && p + 1 < cap) { buf[p] = label[p]; p++; }
	if (p + 2 < cap) {
		buf[p++] = '=';
		buf[p++] = '0';
		buf[p++] = 'x';
		int t = 60;
		if (!(v >> 32)) t = 28;
		for (; t >= 0 && p + 1 < cap; t -= 4)
			buf[p++] = digits[(v >> t) & 0xf];
	}
	buf[p] = 0;
}

static void uf_line(char *buf, unsigned cap, const char *label, uint64_t v)
{
	uf_hex(buf, cap, label, v);
	laguna_usb_log(buf);
}

/* ---- descriptor slab --------------------------------------------------- */

/* 1 MiB + 16 KiB of shim .bss. MMU-off identity (VA == PA); PA is stamped
 * at U5-ENTER and in the U9 trail so the ramdump can find descriptors.
 * Image budget: the file grows by this much after build.sh's truncate;
 * against the 64 MiB ABL cap with a ~15 MiB payload this is nothing. */
static uint8_t ufs_dma[UU_DMA_SIZE] __attribute__((aligned(4096)));

uintptr_t tgl_ufs_dma_pa(void)
{
	return (uintptr_t)ufs_dma;
}

struct ufs_utrd {
	uint32_t dw0, dw1, dw2, dw3;
	uint32_t ucdba, ucdbau;
	uint32_t resp;
	uint32_t prdt;
};

/* ---- single SCSI command: felix wire shape, driver constants ----------- */

static int uf_scsi(const uint8_t *cdb, unsigned cdb_len, uint32_t len,
    unsigned tag)
{
	volatile struct ufs_utrd *t = (volatile struct ufs_utrd *)
	    (ufs_dma + UU_DMA_UTRL);
	volatile uint8_t *ucd = ufs_dma + UU_DMA_UCD;
	uint64_t ucd_pa = (uint64_t)(uintptr_t)ufs_dma + UU_DMA_UCD;
	uint64_t list_pa = (uint64_t)(uintptr_t)ufs_dma + UU_DMA_UTRL;

	/* Shim whitelist: TUR, READ CAPACITY(10), READ(10) — mirroring the
	 * driver's even-stricter rule (no WRITE/UNMAP/QUERY is ever built). */
	if ((cdb_len != 6 && cdb_len != 10) ||
	    (cdb[0] != 0x00 && cdb[0] != 0x25 && cdb[0] != 0x28) ||
	    len > UU_BOUNCE_SIZE) return -1;

	for (unsigned i = 0; i < sizeof(struct ufs_utrd) / 4; i++)
		((volatile uint32_t *)t)[i] = 0;
	for (unsigned i = 0; i < 1024; i++) ucd[i] = 0;

	ucd[0] = UU_UPIU_COMMAND;
	ucd[1] = len ? UU_UPIU_FLAG_READ : 0;
	ucd[2] = 0; /* LUN 0 */
	ucd[3] = (uint8_t)tag;
	ucd[4] = UU_UPIU_IID_ONE;
	ucd[12] = (uint8_t)(len >> 24);
	ucd[13] = (uint8_t)(len >> 16);
	ucd[14] = (uint8_t)(len >> 8);
	ucd[15] = (uint8_t)len;
	u_copy((void *)(ucd + 16), cdb, cdb_len);

	t->dw0 = UU_UTRD_CT_UFS | (len ? UU_UTRD_DD_IN : UU_UTRD_DD_NONE);
	t->dw2 = UU_OCS_INVALID;
	t->ucdba = (uint32_t)ucd_pa;
	t->ucdbau = (uint32_t)(ucd_pa >> 32);
	t->resp = (512u / 4) << 16 | (512u / 4);
	if (len) {
		uint32_t n = 0;
		for (uint32_t done = 0; done < len; done += UU_PRDT_CHUNK, n++) {
			uint32_t chunk = len - done < UU_PRDT_CHUNK ?
			    len - done : UU_PRDT_CHUNK;
			volatile uint32_t *pr = (volatile uint32_t *)
			    (ufs_dma + UU_DMA_UCD + 1024 + n * 16);
			uint64_t pa = (uint64_t)(uintptr_t)ufs_dma +
			    UU_DMA_BOUNCE + done;
			pr[0] = (uint32_t)pa;
			pr[1] = (uint32_t)(pa >> 32);
			pr[2] = 0;
			pr[3] = chunk - 1;
		}
		t->prdt = (1024u / 4) << 16 | n;
	}

	/* Redundant pre-ring check (driver ufs_scsi line 191-197 shape). */
	if ((ucd[0] & 0x3f) != UU_UPIU_COMMAND || ucd[4] != UU_UPIU_IID_ONE ||
	    (ucd[16] != 0x00 && ucd[16] != 0x25 && ucd[16] != 0x28) ||
	    (len && (t->dw0 & UU_UTRD_DD_IN) != UU_UTRD_DD_IN)) return -1;

	/* Never ring unless our list is still the one in the host (driver
	 * line 203-208). dsb sy lives inside probe_begin/probe_end. */
	uint32_t ba = 0, bau = 0, rsr = 0, dbr = 0;
	if (uf_rd(UU_UTRLBA, &ba) || uf_rd(UU_UTRLBAU, &bau) ||
	    uf_rd(UU_UTRLRSR, &rsr) || uf_rd(UU_UTRLDBR, &dbr)) return -2;
	if (ba != (uint32_t)list_pa || bau != (uint32_t)(list_pa >> 32) ||
	    !(rsr & 1) || dbr != 0) return -3;

	if (uf_wr(UU_UTRLDBR, 1)) return -4;
	for (unsigned i = 0; i < UU_TIMEOUT_POLLS; i++) {
		if (uf_rd(UU_UTRLDBR, &dbr)) return -5;
		if (!(dbr & 1)) {
			/* Response UPIU offset differs across UFSHCI generations/
			 * driver conventions: the reference driver struct places
			 * resp at +512, the spec slot layout at +128. Accept the
			 * first offset whose bytes are a valid RESPONSE UPIU for
			 * our tag (r0 = 0x21). Stamp the chosen offset so the
			 * next boot decodes it. */
			__asm__ volatile("dsb sy; isb");
			static const unsigned rsp_offs[2] = { 512, 128 };
			uint8_t r0 = 0, r6 = 0xff, r7 = 0xff;
			uint32_t ocs = t->dw2 & 0xff;
			unsigned chosen = 0;
			for (unsigned k = 0; k < 2; k++) {
				unsigned o = rsp_offs[k];
				uint8_t a = ucd[o], tagb = ucd[o + 3],
				    s = ucd[o + 6], st = ucd[o + 7];
				if (a == UU_UPIU_RESPONSE && tagb == (uint8_t)tag &&
				    s == 0 && (st == 0 ||
				    (cdb[0] == 0x00 && st == 0x02))) {
					r0 = a; r6 = s; r7 = st; chosen = o;
					break;
				}
				if (a == UU_UPIU_RESPONSE && chosen == 0) {
					/* valid RESPONSE but wrong tag/status —
					 * remember it for the stamp */
					if (r6 == 0xff) { r6 = s; r7 = st; chosen = o; }
				}
			}
			uint64_t arg = (uint64_t)chosen << 32 |
			    (uint64_t)ocs << 24 |
			    (uint64_t)r0 << 16 | (uint64_t)r6 << 8 | r7;
			/* Driver success chain (ufs_scsi line 225-231), incl.
			 * accepting status 0x02 on TUR as unit attention. */
			int ok = ocs == 0 && r0 == UU_UPIU_RESPONSE &&
			    ucd[chosen + 3] == (uint8_t)tag &&
			    r6 == 0 &&
			    (r7 == 0 || (cdb[0] == 0x00 && r7 == 0x02));
			tgl_stamp(TGL_STAGE_UFS_TUR,
			    ok ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED, arg);
			return ok ? 0 : -6;
		}
		u_delay_10ms();
	}
	(void)uf_wr(UU_UTRLCLR, 1); /* clear ONLY our slot (driver line 213) */
	tgl_stamp(TGL_STAGE_UFS_TUR, TGL_STAMP_F_TIMEOUT,
	    (uint64_t)cdb[0] << 24 | tag);
	return -7;
}

/* UIC polling uses an architectural 1..4-second deadline plus an iteration
 * guard. The old volatile 400000-iteration delay has no wall-clock bound
 * with caches/MMU off, so it cannot establish the UIC completion deadline.
 * A hung MMIO transaction still needs the armed firmware watchdog. */
static int uf_uic_wait(uint32_t off, uint32_t mask, uint32_t *last)
{
#if (defined(__aarch64__) && !defined(TGL_STAMP_HOST)) || defined(TGL_UFS_TEST_TIMER)
	uint64_t start, now, freq;
#ifdef TGL_UFS_TEST_TIMER
	freq = tgl_ufs_test_counter_frequency();
	start = tgl_ufs_test_counter_now();
#else
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(start));
#endif
	if (!freq) freq = UINT64_C(38400000);
#endif
	for (unsigned i = 0; i < 1000000u * TGL_UFS_UIC_TIMEOUT_SECONDS; i++) {
		if (uf_rd(off, last)) return -1;
		if (*last & mask) return 0;
#if (defined(__aarch64__) && !defined(TGL_STAMP_HOST)) || defined(TGL_UFS_TEST_TIMER)
#ifdef TGL_UFS_TEST_TIMER
		now = tgl_ufs_test_counter_now();
#else
		__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(now));
#endif
		if (now - start >= freq * TGL_UFS_UIC_TIMEOUT_SECONDS) break;
#ifndef TGL_UFS_TEST_TIMER
		__asm__ volatile("yield");
#endif
#endif
	}
	return -2;
}

/* UFSHCI UIC handshake, independently pinned to Google's Laguna driver
 * ufs-google.c:848-919 and gs101 shim/ufsinit.c:47-66. UICCMD is 0x90,
 * not transfer-list run/stop 0x60; completion is IS.UCCS, not HCS ready
 * becoming clear; ARG2 low byte is the result (ZERO alone is success).
 * IS is W1C. Read it only here and clear only UCCS, never unrelated bits. */
static int uf_uic_cmd(uint8_t op, uint32_t a1, uint32_t a2, uint32_t a3)
{
	uint32_t s = 0;
	int rc;
	/* Keep v3p9-ufs5 phase args decodable, but flags contain only DONE:
	 * phase<<4 used to overlap REFUSED and corrupt flag interpretation.
	 * arg layout: phase<<24 | op<<16 | code/result. */
#define UFUIC_STAMP(phase, code) \
	tgl_stamp(TGL_STAGE_UFS_LINK, TGL_STAMP_F_DONE, \
	    (uint64_t)(((phase) << 24) | ((op) << 16) | \
	    ((uint32_t)(code) & 0xffff)))
	UFUIC_STAMP(1, 0);
	rc = uf_uic_wait(UU_HCS, UU_HCS_UICCMDRDY, &s);
	if (rc) { UFUIC_STAMP(2, rc == -1 ? 0xf001 : 0xf002); return rc; }
	UFUIC_STAMP(2, 0);
	if (uf_wr(UU_UICCMDARG1, a1) || uf_wr(UU_UICCMDARG2, a2) ||
	    uf_wr(UU_UICCMDARG3, a3) || uf_wr(UU_IS, UU_IS_UCCS) ||
	    uf_wr(UU_UICCMD, op)) {
		UFUIC_STAMP(3, 0xf003); return -3;
	}
	UFUIC_STAMP(3, 0);
	rc = uf_uic_wait(UU_IS, UU_IS_UCCS, &s);
	if (rc == -1) { UFUIC_STAMP(4, 0xf004); return -4; }
	if (rc) { UFUIC_STAMP(5, 0xf005); return -5; }
	if (uf_rd(UU_UICCMDARG2, &s)) {
		UFUIC_STAMP(4, 0xf006); return -6;
	}
	if (uf_wr(UU_IS, UU_IS_UCCS)) {
		UFUIC_STAMP(4, 0xf007); return -7;
	}
	UFUIC_STAMP(4, s & 0xff);
	return (int)(s & 0xff);
#undef UFUIC_STAMP
}

#if TGL_UFS_LOCAL_DME_DIAG
/* Source-backed local GET packet. Dedicated helper keeps LINKSTARTUP's
 * original timeout/transaction byte-identical when this opt-in is absent. */
struct uf_dme_budget { uint64_t start, ticks; unsigned polls; };

static uint64_t uf_dme_now(void)
{
#ifdef TGL_UFS_TEST_TIMER
	return tgl_ufs_test_counter_now();
#elif defined(__aarch64__) && !defined(TGL_STAMP_HOST)
	uint64_t now;
	__asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(now));
	return now;
#else
	return 0; /* host without a timer still has the global iteration cap */
#endif
}

static void uf_dme_budget_begin(struct uf_dme_budget *b)
{
	uint64_t freq = UINT64_C(38400000);
#ifdef TGL_UFS_TEST_TIMER
	freq = tgl_ufs_test_counter_frequency();
#elif defined(__aarch64__) && !defined(TGL_STAMP_HOST)
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
#endif
	if (!freq) freq = UINT64_C(38400000);
	b->start = uf_dme_now();
	b->ticks = freq / 2 + freq % 2; /* ceil(freq * 500 ms), no overflow */
	b->polls = 0;
}

static int uf_dme_expired(const struct uf_dme_budget *b)
{
	return uf_dme_now() - b->start >= b->ticks;
}

static int uf_dme_wait(struct uf_dme_budget *b, uint32_t off,
    uint32_t mask, uint32_t *last)
{
	while (b->polls++ < UU_LOCAL_DME_DIAG_POLLS) {
		if (uf_rd(off, last)) return -1;
		/* Check elapsed time even if this sample has the desired bit.
		 * Ready and completion waits consume the SAME transaction budget. */
		if (uf_dme_expired(b)) return -2;
		if (*last & mask) return 0;
#if defined(__aarch64__) && !defined(TGL_STAMP_HOST)
		__asm__ volatile("yield");
#endif
	}
	return -2;
}

static void uf_dme_diag_stamp(unsigned flags, unsigned phase,
    unsigned index, uint32_t value)
{
	tgl_stamp(TGL_STAGE_UFS_LINK, flags, UU_LOCAL_DME_DIAG_STAMP_TAG |
	    (uint64_t)phase << 56 | (uint64_t)index << 52 | value);
}

static int uf_dme_diag_error(unsigned index, unsigned flags,
    unsigned code, uint32_t off)
{
	uf_dme_diag_stamp(flags, 4, index, (uint32_t)code << 16 | off);
	return -1;
}

static int uf_dme_diag_get(unsigned index, uint32_t selector)
{
	struct uf_dme_budget budget;
	uint32_t status = 0, value = 0;
	int rc;

	uf_dme_diag_stamp(TGL_STAMP_F_ENTER, 1, index, selector);
	uf_dme_budget_begin(&budget);
	rc = uf_dme_wait(&budget, UU_HCS, UU_HCS_UICCMDRDY, &status);
	if (rc) return uf_dme_diag_error(index,
	    rc == -1 ? TGL_STAMP_F_FAULT : TGL_STAMP_F_TIMEOUT,
	    rc == -1 ? 1 : 2, UU_HCS);
	if (uf_wr(UU_UICCMDARG1, selector) ||
	    uf_wr(UU_UICCMDARG2, 0) || uf_wr(UU_UICCMDARG3, 0) ||
	    uf_wr(UU_IS, UU_IS_UCCS) || uf_wr(UU_UICCMD, 0x01u))
		return uf_dme_diag_error(index, TGL_STAMP_F_FAULT, 3, UU_UICCMD);
	rc = uf_dme_wait(&budget, UU_IS, UU_IS_UCCS, &status);
	if (rc) return uf_dme_diag_error(index,
	    rc == -1 ? TGL_STAMP_F_FAULT : TGL_STAMP_F_TIMEOUT,
	    rc == -1 ? 4 : 5, UU_IS);
	if (uf_rd(UU_UICCMDARG2, &status))
		return uf_dme_diag_error(index, TGL_STAMP_F_FAULT, 6, UU_UICCMDARG2);
	if (uf_rd(UU_UICCMDARG3, &value))
		return uf_dme_diag_error(index, TGL_STAMP_F_FAULT, 7, UU_UICCMDARG3);
	if (uf_wr(UU_IS, UU_IS_UCCS))
		return uf_dme_diag_error(index, TGL_STAMP_F_FAULT, 8, UU_IS);
	if (uf_dme_expired(&budget))
		return uf_dme_diag_error(index, TGL_STAMP_F_TIMEOUT, 9, UU_IS);
	/* Preserve the full ARG2/ARG3 words. For a nonzero low-byte result,
	 * ARG3 remains raw invalid data and is explicitly marked REFUSED. */
	unsigned flags = (status & 0xffu) ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE;
	uf_dme_diag_stamp(flags, 2, index, status);
	uf_dme_diag_stamp(flags, 3, index, value);
	return 0; /* a completed MIB refusal is evidence, not a packet timeout */
}

static int uf_local_dme_diag_at(const struct tgl_ufs_result *r, unsigned base)
{
	unsigned why = 0;
	if (ufs.hc_pa != TGL_UFS_HC_PA) why |= 1u;
	if (r->cap != UU_LOCAL_DME_DIAG_CAP) why |= 2u;
	if (r->ver != 0x400u) why |= 4u;
	if (!(r->hce & 1u)) why |= 8u;
	if (!(r->hcs & UU_HCS_UICCMDRDY)) why |= 16u;
	if (r->mem_cfg & UU_MCQ_MODE_SELECT) why |= 32u;
	if (r->dbr) why |= 64u;
	if (why) {
		uf_dme_diag_stamp(TGL_STAMP_F_REFUSED, 0, 15, why);
		return -1;
	}
	for (unsigned i = 0; i < 5; i++) {
		/* Literals are independently checked by the numeric host model.
		 * D000 layer, TX FSM lanes0/1, RX FSM lanes4/5. No static pointers. */
		uint32_t selector = i == 0 ? UINT32_C(0xd0000000) :
		    i <= 2 ? UINT32_C(0x00410000) + i - 1 :
		    UINT32_C(0x00c10004) + i - 3;
		if (uf_dme_diag_get(base + i, selector)) return -1;
	}
	return 0;
}
static int uf_local_dme_diag(const struct tgl_ufs_result *r)
{
	return uf_local_dme_diag_at(r, 0);
}
#endif

#if TGL_UFS_PRELINK_MODE
/* Google LGA PRE_CHANGE order source: ufs-google.c:1451-1480,
 * lga/ufs-platform.h:30-34 and lga/ufs-regs-gen.h:23,302.
 * Only these in-range registers are admitted. The DT top window ends at
 * +0x504; SRAM_APB_MODE +0x510 and a full PHY sequence are NOT admitted. */
static void uf_prelink_stamp(unsigned flags, unsigned phase, uint32_t off,
    uint32_t value)
{
	tgl_stamp(TGL_STAGE_UFS_LINK, flags, UU_PRELINK_STAMP_TAG |
	    (uint64_t)phase << 52 | (uint64_t)TGL_UFS_PRELINK_MODE << 48 |
	    (uint64_t)off << 32 | value);
}

static int uf_prelink_setup(const struct tgl_ufs_result *r)
{
	uint32_t off, expected, mask, before = 0, after = 0;
	uintptr_t pa;
	/* Exact board/register-map gate. Custom HC bases cannot silently use
	 * the fixed Laguna TOP fallback; no writes on unsupported/busy state.
	 * Called only on the existing dead-host path, never on a warm link. */
	if (ufs.hc_pa != TGL_UFS_HC_PA || r->ver != 0x400u || !r->cap ||
	    !(r->hce & 1u) || !(r->hcs & UU_HCS_UICCMDRDY) ||
	    (r->mem_cfg & UU_MCQ_MODE_SELECT) || r->dbr) {
		uf_prelink_stamp(TGL_STAMP_F_REFUSED, 0, 0, 1);
		return -1;
	}
#if TGL_UFS_PRELINK_MODE == 4
	/* Isolate the AXI-only experiment from the earlier HCLKDIV test.
	 * A manual reset is not proof that the prior 0xc8 write was undone.
	 * Observe the physically captured baseline 0x190; refuse otherwise. */
	uf_prelink_stamp(TGL_STAMP_F_ENTER, 1, UU_HCLKDIV, 0);
	if (!probe_read32((uintptr_t)(ufs.hc_pa + UU_HCLKDIV), &before)) {
		uf_prelink_stamp(TGL_STAMP_F_FAULT, 1, UU_HCLKDIV, 0);
		return -2;
	}
	uf_prelink_stamp(TGL_STAMP_F_DONE, 1, UU_HCLKDIV, before);
	if (before != 0x190u) {
		uf_prelink_stamp(TGL_STAMP_F_REFUSED, 1, UU_HCLKDIV, before);
		return -6;
	}
#endif
#if TGL_UFS_PRELINK_MODE == 5
	/* One inspection profile can rule out already-correct inherited
	 * settings without making either functional change. Independent
	 * before-access stamps and fault gates apply to each selected read. */
	for (unsigned i = 0; i < 2; i++) {
		off = i ? UU_TOP_AXI_VC : UU_HCLKDIV;
		pa = (uintptr_t)((i ? TGL_UFS_TOP_PA : ufs.hc_pa) + off);
		uf_prelink_stamp(TGL_STAMP_F_ENTER, 1, off, 0);
		if (!probe_read32(pa, &before)) {
			uf_prelink_stamp(TGL_STAMP_F_FAULT, 1, off, 0);
			return -2;
		}
		uf_prelink_stamp(TGL_STAMP_F_DONE, 1, off, before);
	}
	(void)expected; (void)mask; (void)after;
	return 0;
#else
#if TGL_UFS_PRELINK_MODE <= 2
	off = UU_HCLKDIV; expected = UU_HCLKDIV_VALUE; mask = 0xffffu;
	pa = (uintptr_t)(ufs.hc_pa + off);
#else
	off = UU_TOP_AXI_VC; expected = UU_TOP_AXI_VC_VALUE;
	mask = UU_TOP_AXI_VC_MASK;
	pa = (uintptr_t)(TGL_UFS_TOP_PA + off);
#endif
	uf_prelink_stamp(TGL_STAMP_F_ENTER, 1, off, 0);
	if (!probe_read32(pa, &before)) {
		uf_prelink_stamp(TGL_STAMP_F_FAULT, 1, off, 0);
		return -2;
	}
	uf_prelink_stamp(TGL_STAMP_F_DONE, 1, off, before);
#if TGL_UFS_PRELINK_MODE == 2 || TGL_UFS_PRELINK_MODE == 4
	/* Match Google's complete register write, with a bounded one-shot
	 * readback. Every risky access has an ENTER stamp beforehand. */
	uf_prelink_stamp(TGL_STAMP_F_ENTER, 2, off, expected);
	if (!probe_write32(pa, expected)) {
		uf_prelink_stamp(TGL_STAMP_F_FAULT, 2, off, expected);
		return -3;
	}
	uf_prelink_stamp(TGL_STAMP_F_ENTER, 3, off, 0);
	if (!probe_read32(pa, &after)) {
		uf_prelink_stamp(TGL_STAMP_F_FAULT, 3, off, 0);
		return -4;
	}
	if ((after & mask) != expected) {
		uf_prelink_stamp(TGL_STAMP_F_REFUSED, 3, off, after);
		return -5;
	}
	uf_prelink_stamp(TGL_STAMP_F_DONE, 3, off, after);
#else
	(void)expected; (void)mask; (void)after;
#endif
	return 0;
#endif /* single-register modes */
}
#endif

static int uf_read_blocks(uint64_t lba, uint32_t count, uint32_t tag)
{
	uint8_t cdb[10] = {
		0x28, 0,
		(uint8_t)(lba >> 24), (uint8_t)(lba >> 16),
		(uint8_t)(lba >> 8), (uint8_t)lba,
		0, (uint8_t)(count >> 8), (uint8_t)count, 0
	};

	if (!count || lba > UINT32_MAX || count > UU_BOUNCE_SIZE / UU_BLOCK)
		return -1;
	return uf_scsi(cdb, 10, count * UU_BLOCK, tag);
}

/* ---- gates ------------------------------------------------------------- */

static int uf_gate(const struct tgl_ufs_result *r)
{
	return r->cap != 0 && r->ver >= 0x200 && r->ver < 0x500 &&
	    (r->hce & 1) &&
	    (r->hcs & (UU_HCS_DP | UU_HCS_UTRLRDY)) ==
	    (UU_HCS_DP | UU_HCS_UTRLRDY) &&
	    !(r->mem_cfg & UU_MCQ_MODE_SELECT);
}

static int uf_whitelist(struct tgl_ufs_result *r)
{
	r->cap = r->ver = r->ahit = r->ie = r->hcs = r->hce =
	    r->mem_cfg = r->rsr = r->dbr = 0;
	if (uf_rd(UU_CAP, &r->cap) || uf_rd(UU_VER, &r->ver) ||
	    uf_rd(UU_AHIT, &r->ahit) || uf_rd(UU_IE, &r->ie) ||
	    uf_rd(UU_HCS, &r->hcs) || uf_rd(UU_HCE, &r->hce) ||
	    uf_rd(UU_UTRLBA, &r->ba_lo) || uf_rd(UU_UTRLBAU, &r->ba_hi) ||
	    uf_rd(UU_UTRLDBR, &r->dbr) || uf_rd(UU_UTRLRSR, &r->rsr) ||
	    uf_rd(UU_MEM_CFG, &r->mem_cfg)) return -1;
	if (!probe_read32((uintptr_t)ufs.psm_pa[0], &r->psm[0])) r->psm[0] = 0;
	if (!probe_read32((uintptr_t)ufs.psm_pa[1], &r->psm[1])) r->psm[1] = 0;
	if (!probe_read32((uintptr_t)ufs.psm_pa[2], &r->psm[2])) r->psm[2] = 0;
	r->prior_list_pa = (uint64_t)r->ba_hi << 32 | r->ba_lo;
	return 0;
}

/* Driver ufs_take_over shape: program OUR single-slot list, readback-gated. */
static int uf_take_over(struct tgl_ufs_result *r)
{
	uint64_t list_pa = (uint64_t)(uintptr_t)ufs_dma + UU_DMA_UTRL;
	uint32_t ba = 0, bau = 0, rsr = 0;

	/* 36-bit reach hard limit; above 4 GiB additionally needs CAP_64AS
	 * (driver line 327-331). */
	uint64_t end = (uint64_t)(uintptr_t)ufs_dma + UU_DMA_SIZE;
	if (end > UU_G5_DMA_LIMIT ||
	    (end > UINT64_C(0x100000000) && !(r->cap & UU_CAP_64AS))) {
		uf_line((char[48]){0}, 48, "UFS DMA not addressable", end);
		return -1;
	}
	if (uf_wr(UU_IE, 0)) return -2;		/* polled completion only */
	if (uf_wr(UU_UTRLRSR, 0)) return -2;
	if (uf_wr(UU_UTRLBA, (uint32_t)list_pa)) return -2;
	if (uf_wr(UU_UTRLBAU, (uint32_t)(list_pa >> 32))) return -2;
	if (uf_wr(UU_UTRLRSR, 1)) return -2;
	if (uf_rd(UU_UTRLBA, &ba) || uf_rd(UU_UTRLBAU, &bau) ||
	    uf_rd(UU_UTRLRSR, &rsr)) return -3;
	if (ba != (uint32_t)list_pa || bau != (uint32_t)(list_pa >> 32) ||
	    !(rsr & 1)) return -4;		/* host did not take the list */
	return 0;
}

#if TGL_UFS_G5_DOMAIN
static int uf_g5_domain_clock(uint32_t id)
{
	struct tgl_cpm_ufs_clock_reply reply;
	/* Full-width raw a0/a1, in order, follow the ENTER(id) marker.
	 * Do not pack/truncate firmware errors into the old status byte. */
	tgl_stamp(TGL_STAGE_UFS_CLK, TGL_STAMP_F_ENTER,
	    UINT64_C(0x534d430600000000) | id);
	int rc = tgl_cpm_ufs_clock_enable(id, &reply);
	unsigned flags = rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE;
	tgl_stamp(TGL_STAGE_UFS_CLK, flags, reply.a0);
	tgl_stamp(TGL_STAGE_UFS_CLK, flags, reply.a1);
	return rc;
}
#endif

/* U2/U3 depth layer (dead-host path only): LPCM 0x06 clock puts, then the
 * phy_rst deassert. Each request rides the proven tgl_cpm.c LPCM frame;
 * byte1 stays the hsio seq 0x05 — the LSIO-domain descriptor seq (and the
 * G4 spec's byte1=6 encoding) is DEVICE-VALIDATE open; a NACK lands in the
 * LPCM_REQ/REPLY stamps and decides the next boot's frame. */
static int uf_depth_layer(unsigned want_rst)
{
	char line[48];
	int rc;

	/* The warm USB path never runs tgl_cpm_init; the depth layer is the
	 * only UFS consumer of the LPCM service, so bring the client up here
	 * (idempotent, stamp-covered, one attempt per boot downstream). */
	if (tgl_cpm_init()) {
		uf_log("UFS: CPM/LPCM client unavailable; no depth layer");
		return -1;
	}

#if TGL_UFS_SKIP_CLOCK_PUTS
	/* Intentional omission, not a clock-enable rc=0. M3, one variable vs
	 * m2-hibern8: the M1/M2 decodes bracket the DME_LAYER_EN 1->0 drop to
	 * these two LPCM puts (depth 0 and 1), so omit both and let
	 * LINK_STARTUP run against whatever DN the handoff left. The POST
	 * guard below still refuses takeover/SCSI even if LINK succeeds;
	 * tgl_cpm_init above keeps its own handshake (the refined suspect if
	 * DN still drops). rc stays unset on skip compositions: the only
	 * remaining consumer is the reset path, which the paired
	 * SKIP_LEGACY_RESET composition returns from before reading it. */
	(void)rc;
	tgl_stamp(TGL_STAGE_UFS_CLK, TGL_STAMP_F_REFUSED,
	    UU_CLOCK_PUTS_SKIP_STAMP);
	uf_log("UFS: clock puts skipped (diagnostic)");
#else
#if TGL_UFS_G5_DOMAIN
	rc = uf_g5_domain_clock(TGL_UFS_CLK_GPIO_REF);
#else
	rc = tgl_cpm_lpcm_put(TGL_UFS_CLK_GPIO_REF);
#endif
	tgl_stamp(TGL_STAGE_UFS_CLK, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
	    (uint64_t)TGL_UFS_CLK_GPIO_REF << 8 | (uint32_t)(rc & 0xff));
	if (rc) return -1;
#if TGL_UFS_G5_DOMAIN
	rc = uf_g5_domain_clock(TGL_UFS_CLK_AUX);
#else
	rc = tgl_cpm_lpcm_put(TGL_UFS_CLK_AUX);
#endif
	tgl_stamp(TGL_STAGE_UFS_CLK, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
	    (uint64_t)TGL_UFS_CLK_AUX << 8 | (uint32_t)(rc & 0xff));
	if (rc) return -1;
#endif
	if (!want_rst) return 0;
#if TGL_UFS_SKIP_POWER_DOWN
	/* Intentional omission, not a power-state rc=0. M4, one variable vs
	 * m3-putsguard: M3's post-depth GETs still read DME_LAYER_EN 0 with the
	 * puts and the legacy reset both omitted, so this PD pair is the last
	 * in-ladder power-state step besides the exit itself. Omit it too; the
	 * POST guard below still refuses takeover/SCSI even if LINK succeeds.
	 * The step is a verify-only marker today (no proven PD read address),
	 * so this branch changes stamps only — an M4 DN=0 decode would confirm
	 * the window analysis and shift suspicion to cpm_init/the exit/GET
	 * traffic; no rc is claimed either way. */
	tgl_stamp(TGL_STAGE_UFS_PD, TGL_STAMP_F_REFUSED, UU_POWER_DOWN_SKIP_STAMP);
	uf_log("UFS: power-down pair skipped (diagnostic)");
#else
	/* PD pair sswrp-0x18: verify-only TODAY — the DT gives phandles
	 * (0x4a6/0x43d), not a read register; no proven read address means
	 * no invented read (fleet rule: no unverified assumed facts). */
	tgl_stamp(TGL_STAGE_UFS_PD, TGL_STAMP_F_DONE, UINT64_C(0x18));
#endif
#if TGL_UFS_G5_DOMAIN
	tgl_stamp(TGL_STAGE_UFS_RST, TGL_STAMP_F_ENTER, UINT64_C(0x01030604));
	rc = tgl_cpm_ufs_phy_reset_deassert();
	tgl_stamp(TGL_STAGE_UFS_RST, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
	    UINT64_C(0x5253540600000000) | (uint32_t)rc);
#else
#if TGL_UFS_SKIP_LEGACY_RESET
	/* Intentional omission, not firmware reset rc=0. POST guard below still
	 * refuses takeover/SCSI even if LINK succeeds or the host is warm. */
	tgl_stamp(TGL_STAGE_UFS_RST, TGL_STAMP_F_REFUSED, UU_LEGACY_RESET_SKIP_STAMP);
	uf_log("UFS: legacy PHY reset skipped (diagnostic)");
	return 0;
#else
	rc = tgl_cpm_lpcm_reset_deassert(TGL_UFS_RST_PHY);
#endif
#endif
	tgl_stamp(TGL_STAGE_UFS_RST, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
	    (uint64_t)TGL_UFS_RST_PHY << 8 | (uint32_t)(rc & 0xff));
	(void)uf_line(line, sizeof(line), "UFS depth rst rc", (uint64_t)(uint32_t)rc);
	return rc;
}

void tgl_ufs_probe_ladder(struct tgl_ufs_result *out)
{
	struct tgl_ufs_result *r = &ufs.r;
	uint8_t cdb_tur[6] = {0};
	uint8_t cdb_cap[10] = {0x25, 0};
	unsigned bitmap = 0;
	char line[112];

	if (ufs.attempted || ufs.trap_latched) { *out = ufs.r; return; } /* one attempt per boot */
	ufs.attempted = 1;
	for (unsigned i = 0; i < sizeof(*r); i++) ((uint8_t *)r)[i] = 0;
	r->dma_pa = (uint64_t)(uintptr_t)ufs_dma;
	tgl_stamp(TGL_STAGE_UFS_FIRST, TGL_STAMP_F_ENTER, r->dma_pa);

	/* U0 preconditions (CPM/EP0 up) are the caller's contract; U1 now. */
	if (uf_whitelist(r)) {
		tgl_stamp(TGL_STAGE_UFS_HCI, TGL_STAMP_F_FAULT, r->cap);
		uf_log("UFS: HCI register reads faulted");
		goto fail;
	}
	tgl_stamp(TGL_STAGE_UFS_HCI,
	    uf_gate(r) ? TGL_STAMP_F_DONE : TGL_STAMP_F_FAULT,
	    (uint64_t)r->cap << 32 | r->ver);
	tgl_stamp(TGL_STAGE_UFS_HCS, TGL_STAMP_F_DONE, (uint64_t)r->hcs << 32 | r->hce);

	if (!uf_gate(r)) {
#if TGL_UFS_LOCAL_DME_DIAG
		/* Observe inherited state before legacy or explicit-domain depth
		 * requests. A fault/timeout refuses this ladder, never LINKSTARTUP. */
		if (uf_local_dme_diag(r)) goto fail;
#endif
#if TGL_UFS_G5_DOMAIN
		/* Admit this independent G5 experiment only on the captured
		 * readable legacy/idle host. A custom base/unknown version or
		 * foreign outstanding DMA is not a secure-clock prerequisite. */
		if (ufs.hc_pa != TGL_UFS_HC_PA || r->ver != 0x400u || !r->cap ||
		    !(r->hce & 1u) || (r->mem_cfg & UU_MCQ_MODE_SELECT) || r->dbr) {
			tgl_stamp(TGL_STAGE_UFS_CLK, TGL_STAMP_F_REFUSED,
			    UINT64_C(0x534d43060000ffff));
			goto fail;
		}
#endif
		/* U1 dead -> U2 clocks, re-read; still dead -> U3 rst, re-read.
		 * Bounded: two LPCM round-trips (~200 ms class each) + reads. */
		uf_line(line, sizeof(line), "UFS U1 dead ver", r->ver);
		if (uf_depth_layer(0)) goto fail;
		if (uf_whitelist(r)) goto fail;
		tgl_stamp(TGL_STAGE_UFS_HCS, TGL_STAMP_F_DONE,
		    (uint64_t)r->hcs << 32 | r->hce);
		if (!uf_gate(r)) {
			if (uf_depth_layer(1)) goto fail;
			if (uf_whitelist(r)) goto fail;
			if (!uf_gate(r)) {
				/* v3.9c (link startup): after a cold UFS
				 * power-up the PA link is DOWN — HCS.DP/
				 * UTRLRDY only set once DME_LINKSTARTUP
				 * completes. The ABL's own driver does this
				 * step in its full initialization (device
				 * truth v3p9-ufs3: HCS = 0x108 = UICCMDRDY
				 * only). Only entered when the gate is
				 * still closed — an already-up link never
				 * takes this path. */
#if TGL_UFS_PRELINK_MODE
				if (uf_prelink_setup(r)) goto fail;
#endif
#if TGL_UFS_HIBERN8_EXIT
				/* M2, one variable vs m1-skipreset: ABL left the
				 * UniPro link in HIBERN8 (UIC 0x17 enter at handoff)
				 * and the lane FSM GETs still read 1 at the LINK16
				 * attempt (m1 seq 78-98), so mirror Linux's resume
				 * order and request DME_HIBERN8_EXIT (UIC 0x18, zero
				 * args) before the first LINK_STARTUP. Same UIC form
				 * as LINKSTARTUP; uf_uic_cmd's own phase stamps carry
				 * the op byte 0x18 (0x01180000..0x041800rr), distinct
				 * from LINK16's 0x16. The ENTER/outcome pair below
				 * packs the documented H8EXIT marker in bits 63..16
				 * and the raw rc in bits 15..0. A completed nonzero
				 * result refuses the ladder: the device was not in
				 * HIBERN8 (or the local DME rejected the exit) — the
				 * pre-registered refutation of the inherited-state
				 * reading. Placed before the second GET packet so
				 * indices 8..12 read the post-exit lane FSM state. */
				tgl_stamp(TGL_STAGE_UFS_LINK, TGL_STAMP_F_ENTER,
				    UU_HIBERN8_EXIT_STAMP);
				int hrc = uf_uic_cmd(UU_DME_HIBERN8EXIT, 0, 0, 0);
				tgl_stamp(TGL_STAGE_UFS_LINK,
				    hrc ? TGL_STAMP_F_REFUSED :
				    TGL_STAMP_F_DONE,
				    (UU_HIBERN8_EXIT_STAMP & ~UINT64_C(0xffff)) |
				    ((uint64_t)(uint32_t)hrc & 0xffff));
				uf_line(line, sizeof(line), "UFS h8 exit rc",
				    (uint64_t)(uint32_t)hrc);
				if (hrc) goto fail;
				/* bluejay resume precedent: settle between the
				 * completed exit and the next UIC work — now
				 * the counter-bounded u_settle_10ms, not the
				 * busy loop that consumed 4.3 s on m2-hibern8
				 * (kept INSIDE this same HIBERN8_EXIT flag: the
				 * settle belongs to the exit this flag adds). */
				u_settle_10ms();
#if TGL_UFS_LOCAL_DME_DIAG
				/* F4 recommendation (M2 decode uncertainty 3):
				 * make "exit succeeded" an observed event, not
				 * just rc=0. Read-only observation packet right
				 * before the 8..12 POST GETs: the asynchronous
				 * IS.UHXS event bit (UU_IS_UHXS 0x20, W1C —
				 * read, never cleared here) and HCS.UPMCRS =
				 * (HCS>>8)&7 (PWR_LOCAL=1 expected class;
				 * linux-next include/ufs/ufshci.h:181-182,220,
				 * 228; UFS-HANDOFF-AUDIT 400-403). Diag index
				 * 13, phases 1/2/3 = ENTER (0x00300020 packs
				 * IS 0x20 + HCS 0x30) / IS raw / HCS raw; the
				 * values gate nothing. A faulted read refuses
				 * the ladder like every DIAG fault above; an
				 * ABSENT UHXS is recorded, not refused — the
				 * audit's fresh-event validator contract is a
				 * decode-time judgment, not a shim gate. */
				{
					uint32_t is_v = 0, hcs_v = 0;
					uf_dme_diag_stamp(TGL_STAMP_F_ENTER, 1,
					    13, (uint32_t)UU_IS |
					    (uint32_t)UU_HCS << 16);
					if (uf_rd(UU_IS, &is_v)) {
						uf_dme_diag_stamp(
						    TGL_STAMP_F_FAULT, 1, 13,
						    (uint32_t)UU_IS);
						goto fail;
					}
					uf_dme_diag_stamp(TGL_STAMP_F_DONE, 2,
					    13, is_v);
					if (uf_rd(UU_HCS, &hcs_v)) {
						uf_dme_diag_stamp(
						    TGL_STAMP_F_FAULT, 3, 13,
						    (uint32_t)UU_HCS);
						goto fail;
					}
					uf_dme_diag_stamp(TGL_STAMP_F_DONE, 3,
					    13, hcs_v);
				}
#endif
#endif
#if TGL_UFS_LOCAL_DME_POST
				/* Fresh exact admission after unchanged depth/prelink work.
				 * Indices 8..12 distinguish this packet without extra stamps. */
				if (uf_whitelist(r)) goto fail;
				if (uf_local_dme_diag_at(r, 8)) goto fail;
#endif
				int lrc = uf_uic_cmd(UU_DME_LINKSTARTUP,
				    0, 0, 0);
				tgl_stamp(TGL_STAGE_UFS_LINK,
				    lrc ? TGL_STAMP_F_REFUSED :
				    TGL_STAMP_F_DONE,
				    (uint64_t)(uint32_t)lrc);
				uf_line(line, sizeof(line), "UFS link rc",
				    (uint64_t)(uint32_t)lrc);
				if (lrc) goto fail;
				for (unsigned i = 0; i < UU_TIMEOUT_POLLS;
				    i++) {
					struct tgl_ufs_result rr = *r;
					if (uf_whitelist(&rr)) goto fail;
					if (uf_gate(&rr)) { *r = rr; break; }
					u_delay_10ms();
				}
				if (!uf_gate(r)) {
					uf_log("UFS: link up, gate still closed");
					goto fail;
				}
			}
		}
		uf_log("UFS: host came up after depth layer");
	}
#if TGL_UFS_LOCAL_DME_POST
	/* Observation-only profile: even a warm host or successful LINK must
	 * stop before list ownership, DMA doorbells or SCSI commands. */
	uf_dme_diag_stamp(TGL_STAMP_F_REFUSED, 0, 14, UINT32_C(0x504f5354));
	uf_log("UFS: POST diagnostic complete; refusing list takeover and SCSI");
	goto fail;
#endif
	bitmap |= 1u << 0 | 1u << 3; /* hci + link */
	uf_line(line, sizeof(line), "UFS hcs", r->hcs);
	uf_line(line, sizeof(line), "UFS hce", r->hce);
	uf_line(line, sizeof(line), "UFS prior-list", r->prior_list_pa);

	{
		int err = uf_take_over(r);
		if (err) {
			uf_line(line, sizeof(line), "UFS takeover fail", (uint64_t)-err);
			tgl_stamp(TGL_STAGE_UFS_HCS, TGL_STAMP_F_REFUSED, r->hcs);
			goto fail;
		}
	}

	/* U5: TUR x10, 100 ms apart (unit attention + LUN "becoming ready" —
	 * right after phy calibration the LUN can report not-ready for
	 * seconds; 3 back-to-back tries were too eager on real silicon). */
	{
		unsigned tur_ok = 0;
		for (unsigned i = 0; i < 10; i++) {
			if (i) {
				for (unsigned d = 0; d < 10; d++) u_delay_10ms();
			}
			if (uf_scsi(cdb_tur, 6, 0, i + 1) == 0) { tur_ok = 1; break; }
		}
		if (!tur_ok) {
			uf_log("UFS: TUR failed x10");
			goto fail;
		}
		bitmap |= 1u << 4;
	}

	/* U6: READ CAPACITY(10), 8 B data-in. */
	{
		uint8_t *b = ufs_dma + UU_DMA_BOUNCE;
		if (uf_scsi(cdb_cap, 10, 8, 10)) {
			uf_log("UFS: READ CAPACITY failed");
			goto fail;
		}
		r->lun_last_lba = ((uint64_t)b[0] << 24) | ((uint64_t)b[1] << 16) |
		    ((uint64_t)b[2] << 8) | b[3];
		r->lun_block_size = ((uint32_t)b[4] << 24) | ((uint32_t)b[5] << 16) |
		    ((uint32_t)b[6] << 8) | b[7];
		tgl_stamp(TGL_STAGE_UFS_RDCAP, TGL_STAMP_F_DONE,
		    (uint32_t)r->lun_last_lba);
		tgl_stamp(TGL_STAGE_UFS_RDCAP1, TGL_STAMP_F_DONE, r->lun_block_size);
		if (r->lun_block_size != UU_BLOCK) {
			uf_line(line, sizeof(line), "UFS bad block size",
			    r->lun_block_size);
			goto fail;
		}
		bitmap |= 1u << 5;
		uf_line(line, sizeof(line), "UFS RDCAP lba", r->lun_last_lba);
	}

	/* U7: GPT walk + the first live partition-name survey (every name +
	 * LBA range over EP0). */
	{
		uint8_t *b = ufs_dma + UU_DMA_BOUNCE;
		if (uf_read_blocks(1, 1, 11)) {
			uf_log("UFS: GPT LBA1 read failed");
			goto fail;
		}
		if (u_seq(b, "EFI PART", 8)) {
			uf_log("UFS: no GPT header on LUN 0");
			tgl_stamp(TGL_STAGE_UFS_GPT, TGL_STAMP_F_FAULT, 0);
			goto fail;
		}
		uint64_t entry_lba = 0;
		uint32_t count = 0, entry_size = 0;
		u_copy(&entry_lba, b + 72, 8);
		u_copy(&count, b + 80, 4);
		u_copy(&entry_size, b + 84, 4);
		unsigned gpt_ok = count && count <= UU_MAX_GPT_ENTRIES &&
		    entry_size == 128;
		tgl_stamp(TGL_STAGE_UFS_GPT,
		    gpt_ok ? TGL_STAMP_F_DONE : TGL_STAMP_F_FAULT,
		    (uint64_t)count << 16 | entry_size);
		if (!gpt_ok) {
			uf_log("UFS: unsupported GPT geometry");
			goto fail;
		}
		uint32_t blocks = (count * entry_size + UU_BLOCK - 1) / UU_BLOCK;
		if (uf_read_blocks(entry_lba, blocks, 12)) {
			uf_log("UFS: GPT entries read failed");
			goto fail;
		}
		int found = -1;
		for (uint32_t i = 0; i < count; i++) {
			const uint8_t *e = b + i * entry_size;
			char name[37];
			unsigned c2;
			for (c2 = 0; c2 < 36; c2++) {
				uint16_t ch = (uint16_t)(e[56 + 2 * c2] |
				    e[57 + 2 * c2] << 8);
				if (!ch || ch > 0x7f) break;
				name[c2] = (char)ch;
			}
			name[c2] = 0;
			uint64_t first = 0, last = 0;
			u_copy(&first, e + 32, 8);
			u_copy(&last, e + 40, 8);
			/* one EP0 line per entry: name + LBA range */
			unsigned p = 0;
			const char *pre = "GPT: ";
			while (pre[p]) { line[p] = pre[p]; p++; }
			for (unsigned k = 0; name[k] && p + 1 < sizeof(line); k++)
				line[p++] = name[k];
			line[p++] = ' ';
			unsigned keep = p;
			uf_hex(line + keep, sizeof(line) - keep, "first", first);
			while (line[p]) p++;
			if (p + 1 < sizeof(line)) line[p++] = ' ';
			uf_hex(line + p, sizeof(line) - p, "last", last);
			laguna_usb_log(line);
			if (!u_seq((const uint8_t *)name, TGL_UFS_TARGET, sizeof(name)))
				found = (int)i;
		}
		if (found < 0) {
			uf_log("UFS: " TGL_UFS_TARGET " NOT found (survey above)");
			tgl_stamp(TGL_STAGE_UFS_PART, TGL_STAMP_F_REFUSED, count);
			goto fail;
		}
		const uint8_t *e = b + (uint32_t)found * entry_size;
		u_copy(&r->part_first_lba, e + 32, 8);
		u_copy(&r->part_last_lba, e + 40, 8);
		if (r->part_last_lba < r->part_first_lba ||
		    r->part_last_lba - r->part_first_lba + 1 <
		    (uint64_t)TGL_UFS_STAGE_BLOCKS + 2) {
			uf_log("UFS: target too small for staging image");
			tgl_stamp(TGL_STAGE_UFS_PART, TGL_STAMP_F_REFUSED,
			    (uint64_t)(uint32_t)found << 16);
			goto fail;
		}
		tgl_stamp(TGL_STAGE_UFS_PART, TGL_STAMP_F_DONE,
		    (uint64_t)(uint32_t)found << 16 |
		    (uint32_t)r->part_first_lba);
		bitmap |= 1u << 6;
	}

	/* U7b (P2 addition): staged-image validate. Structural only — NXSB
	 * magic/geometry at block 0 + the UFSSTG1 manifest block right after
	 * the image. The full sha256 is a STAGING-TIME gate (builder +
	 * coordinator's region-exact readback digest); hashing 2.31 GiB in a
	 * bounded bring-up window would blow the 90 s deadline. */
	{
		uint8_t *b = ufs_dma + UU_DMA_BOUNCE;
		if (uf_read_blocks(r->part_first_lba, 1, 13)) {
			uf_log("UFS: staging block 0 read failed");
			goto fail;
		}
		uint32_t magic = 0;
		u_copy(&magic, b + TGL_UFS_STAGE_MAGIC_OFF, 4);
		u_copy(&r->stage_block_size, b + TGL_UFS_STAGE_BSIZE_OFF, 4);
		u_copy(&r->stage_blocks, b + TGL_UFS_STAGE_BLKS_OFF, 8);
		if (magic != TGL_UFS_STAGE_MAGIC || r->stage_block_size != UU_BLOCK ||
		    r->stage_blocks != TGL_UFS_STAGE_BLOCKS) {
			uf_log("UFS: not the pinned NXSB staging image");
			tgl_stamp(TGL_STAGE_UFS_STAGE, TGL_STAMP_F_REFUSED,
			    r->stage_blocks << 16 | r->stage_block_size);
			goto fail;
		}
		if (uf_read_blocks(r->part_first_lba + r->stage_blocks, 1, 14)) {
			uf_log("UFS: manifest block read failed");
			goto fail;
		}
		uint64_t mmagic = 0;
		uint32_t mver = 0, mcount = 0;
		u_copy(&mmagic, b, 8);
		u_copy(&mver, b + 8, 4);
		u_copy(&mcount, b + 12, 4);
		if (mmagic != TGL_UFS_MANIFEST_MAGIC || mver != 1 || mcount < 1) {
			uf_log("UFS: bad UFSSTG1 manifest");
			tgl_stamp(TGL_STAGE_UFS_STAGE, TGL_STAMP_F_REFUSED,
			    (uint64_t)mver << 8 | mcount);
			goto fail;
		}
		uint64_t c_off = 0, c_size = 0;
		u_copy(&c_off, b + 56, 8);
		u_copy(&c_size, b + 64, 8);
		if (c_off != 0 || c_size != r->stage_blocks * UU_BLOCK) {
			uf_log("UFS: manifest/image geometry mismatch");
			tgl_stamp(TGL_STAGE_UFS_STAGE, TGL_STAMP_F_REFUSED,
			    c_size >> 16);
			goto fail;
		}
		tgl_stamp(TGL_STAGE_UFS_STAGE, TGL_STAMP_F_DONE,
		    (uint64_t)mver << 8 | mcount);
		bitmap |= 1u << 8;
		uf_line(line, sizeof(line), "UFS staged blocks", r->stage_blocks);
	}

	/* U8: leave live — no HCE toggle, no RSR/CLR/IE writes, descriptors
	 * left in the documented slab; final readback + THE attestation. */
	{
		uint32_t dbr = 0, hcs2 = 0;
		int rr = uf_rd(UU_UTRLDBR, &dbr);
		rr |= uf_rd(UU_HCS, &hcs2);
		r->live = !rr && dbr == 0 &&
		    (hcs2 & (UU_HCS_DP | UU_HCS_UTRLRDY)) ==
		    (UU_HCS_DP | UU_HCS_UTRLRDY);
#if TGL_UFS_HANDOFF
		r->live = 0;
#endif
		tgl_stamp(TGL_STAGE_UFS_LIVE,
		    r->live ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED,
		    (uint64_t)hcs2 << 16 | dbr);
		bitmap |= 1u << 7;
		uf_log(r->live ? "UFS: LIVE (host left for XNU mode 2)" :
		    "UFS: not clean at leave-live");
	}

	/* U9: whole-trail EP0 block + DONE. */
	uf_line(line, sizeof(line), "UFS trail cap", (uint64_t)r->cap << 32 | r->ver);
	uf_line(line, sizeof(line), "UFS trail psm", ((uint64_t)r->psm[0] << 32) |
	    ((uint64_t)r->psm[1] << 16) | r->psm[2]);
	uf_line(line, sizeof(line), "UFS dma-slab", r->dma_pa);
	uf_line(line, sizeof(line), "UFS part-first", r->part_first_lba);

	r->steps = bitmap;
	r->attempted = 1;
	ufs.r = *r;
	tgl_stamp(TGL_STAGE_UFS_FIRST, TGL_STAMP_F_DONE, bitmap);
	if (!r->live) tgl_stamp_reason(TGL_STAMP_R_UFS);
	*out = *r;
	return;

fail:
	r->steps = bitmap;
	r->attempted = 1;
	ufs.r = *r;
	tgl_stamp(TGL_STAGE_UFS_FIRST, TGL_STAMP_F_REFUSED, bitmap);
	tgl_stamp_reason(TGL_STAMP_R_UFS);
	uf_log("UFS: ladder failed; handoff omits blazer_ufs tokens");
	*out = *r;
}

unsigned tgl_ufs_attempted(void)
{
	return ufs.attempted;
}

const struct tgl_ufs_result *tgl_ufs_result(void)
{
	return &ufs.r;
}

/* ---- v3.9b (U1) fix B: guard wrapper + trap-fail ----------------------- */

/* Tiny wrapper so the guard's saved LR resumes INSIDE it: on unwind this
 * returns 1 to shim_main immediately after tgl_guard_arm() (the ladder
 * call is skipped); a normal run disarms and returns 0. */
unsigned tgl_ufs_guarded_ladder(struct tgl_ufs_result *out)
{
	tgl_guard_arm();
	tgl_ufs_probe_ladder(out);
	tgl_guard_armed = 0;
	return tgl_guard_esr != 0;
}

void tgl_ufs_trap_fail(uint64_t esr, uint64_t far_val)
{
	struct tgl_ufs_result *r = &ufs.r;

	if (ufs.trap_latched) return; /* one trap record per boot */
	ufs.trap_latched = 1;
	for (unsigned i = 0; i < sizeof(*r); i++) ((uint8_t *)r)[i] = 0;
	r->dma_pa = (uint64_t)(uintptr_t)ufs_dma;
	r->attempted = 1;
	r->live = 0;
	/* Two FAULT stamps (ESR then FAR) under the ladder stage — the dump
	 * reads as ENTER, ENTER(dma), FAULT(esr), FAULT(far), REFUSED. */
	tgl_stamp(TGL_STAGE_UFS_FIRST, TGL_STAMP_F_FAULT, esr);
	tgl_stamp(TGL_STAGE_UFS_FIRST, TGL_STAMP_F_FAULT, far_val);
	tgl_stamp(TGL_STAGE_UFS_FIRST, TGL_STAMP_F_REFUSED, 0);
	tgl_stamp_reason(TGL_STAMP_R_UFS);
	uf_log("UFS: fault inside ladder; guard unwind, honest md0 handoff");
}

#if TGL_UFS_HANDOFF
#include "tgl_ufs_handoff.h"
void tgl_ufs_handoff_commit(int outcome, unsigned lun, uint32_t step, uint32_t hcs)
{
	ufs.r.attempted = 1;
	ufs.r.live = outcome == UFSH_LIVE;
	ufs.r.proven_lun = lun;
	ufs.attempted = 1;
	tgl_stamp(TGL_STAGE_UFS_LIVE,
	    outcome == UFSH_LIVE ? TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED,
	    (uint64_t)hcs << 32 | (uint64_t)step << 8 | (uint8_t)outcome);
}
#endif

/* ---- honest-handoff cmdline gate (PLAN.md 4.3) ------------------------- */

static int u_prefix(const char *tok, const char *pre)
{
	while (*pre) {
		if (*tok++ != *pre++) return 0;
	}
	return 1;
}

int tgl_ufs_cmdline_admit(char *cmdline, const struct tgl_ufs_result *r)
{
	unsigned len = 0, changed = 0, out = 0;
	char tmp[TGL_UFS_CMDLINE_BYTES];

	while (len < TGL_UFS_CMDLINE_BYTES && cmdline[len]) len++;
	if (len >= TGL_UFS_CMDLINE_BYTES) return -1; /* unterminated: caller refuses the boot */
#if TGL_UFS_HANDOFF
	/* Lists are stopped and the DMA is over, so a mismatch only loses the root. */
	if (r && r->live && ufsh_cmdline_ok(cmdline, r->proven_lun)) return 0;
#else
	if (r && r->live) return 0; /* U8 attestation present: admit as-is */
#endif

	for (unsigned i = 0; i <= len; ) {
		unsigned j = i;
		while (j < len && cmdline[j] != ' ') j++;
		unsigned toklen = j - i;
		if (toklen) {
			const char *tok = cmdline + i;
			if (u_prefix(tok, "blazer_ufs")) {
				changed = 1; /* token dropped */
			} else {
				const char *repl = 0;
				unsigned rlen = 0;
				if (toklen == 11 && u_prefix(tok, "rd=ufsroot0")) {
					repl = "rd=md0";
					rlen = 6;
					changed = 1;
				}
				if (out && out + 1 < sizeof(tmp)) tmp[out++] = ' ';
				if (out + (repl ? rlen : toklen) >= sizeof(tmp))
					return -1; /* unreachable: shrink-only */
				if (repl)
					for (unsigned k = 0; k < rlen; k++)
						tmp[out++] = repl[k];
				else
					for (unsigned k = 0; k < toklen; k++)
						tmp[out++] = tok[k];
			}
		}
		if (j >= len) break;
		i = j + 1;
	}
	if (!changed) return 0;
	if (out >= TGL_UFS_CMDLINE_BYTES) return -1;
	u_copy(cmdline, tmp, out);
	cmdline[out] = 0;
	tgl_stamp(TGL_STAGE_UFS_LIVE, TGL_STAMP_F_REFUSED, out);
	{
		char linebuf[640];
		unsigned p = 0;
		const char *pre = "UFS handoff rewrite: ";
		while (pre[p]) { linebuf[p] = pre[p]; p++; }
		for (unsigned k = 0; k < out && p + 1 < sizeof(linebuf); k++)
			linebuf[p++] = cmdline[k];
		linebuf[p] = 0;
		laguna_usb_log(linebuf);
	}
	return 1;
}
