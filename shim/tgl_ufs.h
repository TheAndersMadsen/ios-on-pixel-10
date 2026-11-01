#pragma once

#include <stdint.h>

/*
 * tgl_ufs — shim UFS probe ladder U0-U9 + honest-handoff cmdline gate
 * (P2 lane, 2026-10-28). Implements ufs-staging/PLAN.md + probe-ladder.md
 * (G4 spec) against the LIVE shim v3.9 source tree, with every constant
 * register-for-register the ones our kernel driver already enforces
 * (bsd/dev/hakios.blazer_ufs.c) — the ladder is a rehearsal of exactly
 * what XNU mode 1/2 will do after the handoff.
 *
 * Discipline (probe-ladder.md, non-negotiable): validate -> act -> bounded
 * wait -> stamp -> bail. One attempt per boot. All MMIO through the
 * fault-gated probe accessors. UIC completion alone may read IS 0x20 (W1C, not clear-on-read)
 * and acknowledge only UCCS bit 10. Error/status 0x38..0x48 and top CSR
 * 0x510 remain outside the read whitelist. A failed
 * ladder never leaves the host dirtier than a successful one: our own DMA
 * slab plus at most one doorbell ring per SCSI command.
 *
 * Failure posture (honest-handoff, PLAN.md 4.3): the ladder NEVER parks the
 * phone by itself. It returns a result; loader.c rewrites the payload
 * cmdline to the recovery profile (drop every blazer_ufs* token,
 * rd=ufsroot0 -> rd=md0) unless the U8 LIVE stamp exists for this boot.
 * XNU's own independent gate chain is the second lock.
 *
 * Host tests: tests/host_ufs.c + tests/host-ufs.sh (synthetic HCI + disk).
 */

/* G5 constants (laguna DT ufs@3c400000, blazer MP DTB; ROOT-TRANSPORT 5).
 * v3.9b (U1): these are FALLBACKS only — at boot the ladder's base + PSM
 * trio are driven from the ABL FDT's UFS node (fdt_find_ufs; the real DTB
 * carries ufs@3c400000 with exactly these values, so the runtime override
 * agrees with the constants when the tree is the expected one). */
#define TGL_UFS_HC_PA		UINT64_C(0x3c400000)
#define TGL_UFS_TOP_PA		UINT64_C(0x3c410000)
#define TGL_UFS_PHY_SRAM_PA	UINT64_C(0x3c700000)
#define TGL_UFS_PSM_HSIOS	UINT64_C(0x3c00b108)
#define TGL_UFS_PSM_HC		UINT64_C(0x3c00d210)
#define TGL_UFS_PSM_PHY		UINT64_C(0x3c00e108)

/* UFSHCI-standard offsets (same map as the kernel driver). */
#define UU_CAP			0x00u
#define UU_VER			0x08u
#define UU_AHIT			0x18u
#define UU_IS			0x20u
#define UU_IS_UCCS		(1u << 10)
/* IS.UHXS: the asynchronous UIC Hibern8-exit event
 * (linux-next include/ufs/ufshci.h:182 UIC_HIBERNATE_EXIT 0x20). W1C:
 * the H8-validate read only observes it, never clears it
 * (UFS-HANDOFF-AUDIT 400-403: preserve unrelated IS bits). */
#define UU_IS_UHXS		(1u << 5)
#define UU_IE			0x24u
#define UU_HCS			0x30u
#define UU_HCS_UICCMDRDY	(1u << 3)
/* HCS.UPMCRS: UIC power-mode-change request status, (HCS >> 8) & 7;
 * PWR_LOCAL = 1 is the post-change class (ufshci.h:220, 228). */
#define UU_HCS_UPMCRS_SHIFT	8u
#define UU_HCS_UPMCRS_MASK	0x7u
#define UU_UICCMD		0x90u
#define UU_UICCMDARG1		0x94u
#define UU_UICCMDARG2		0x98u
#define UU_UICCMDARG3		0x9cu
#define UU_DME_LINKSTARTUP	0x16u	/* 0x10 is DME_POWERON, not link startup */
/* Google Laguna's ufs-google.c uses a four-second UIC completion budget.
 * Preserve the original one-second diagnostic profile unless opted in. */
#ifndef TGL_UFS_UIC_TIMEOUT_SECONDS
#define TGL_UFS_UIC_TIMEOUT_SECONDS 1
#endif
#if TGL_UFS_UIC_TIMEOUT_SECONDS < 1 || TGL_UFS_UIC_TIMEOUT_SECONDS > 4
#error "TGL_UFS_UIC_TIMEOUT_SECONDS must be in 1..4"
#endif
#if defined(TGL_UFS_TEST_TIMER) && !defined(TGL_STAMP_HOST)
#error "TGL_UFS_TEST_TIMER is a host-only counter seam"
#endif
#ifdef TGL_UFS_TEST_TIMER
uint64_t tgl_ufs_test_counter_frequency(void);
uint64_t tgl_ufs_test_counter_now(void);
#endif
/* J2 read-only local-MIB snapshot, default OFF. Runs once on the captured
 * Laguna HCI 4.0/capability identity, idle legacy list and UIC-ready dead-link
 * path, before any depth change. Five DME_GETs only; no MIB/clock/reset/wake
 * writes. Each complete transaction shares one 500 ms timer/iteration budget.
 * Raw result/value stamps do not by themselves attest PHY/link readiness. */
#ifndef TGL_UFS_LOCAL_DME_DIAG
#define TGL_UFS_LOCAL_DME_DIAG 0
#endif
#if TGL_UFS_LOCAL_DME_DIAG != 0 && TGL_UFS_LOCAL_DME_DIAG != 1
#error "TGL_UFS_LOCAL_DME_DIAG must be 0 or 1"
#endif
/* Second local GET packet after legacy depth/prelink, before LINK_STARTUP. */
#ifndef TGL_UFS_LOCAL_DME_POST
#define TGL_UFS_LOCAL_DME_POST 0
#endif
#if TGL_UFS_LOCAL_DME_POST != 0 && TGL_UFS_LOCAL_DME_POST != 1
#error "TGL_UFS_LOCAL_DME_POST must be 0 or 1"
#endif
#if TGL_UFS_LOCAL_DME_POST && !TGL_UFS_LOCAL_DME_DIAG
#error "TGL_UFS_LOCAL_DME_POST requires TGL_UFS_LOCAL_DME_DIAG=1"
#endif
#define UU_LOCAL_DME_DIAG_CAP UINT32_C(0x53870f1f)
#define UU_LOCAL_DME_DIAG_STAMP_TAG UINT64_C(0x6000000000000000)
#define UU_LOCAL_DME_DIAG_POLLS 500000u
/* Isolated Laguna PRE_CHANGE experiment. One register per candidate:
 * 0 off, 1 observe HCLKDIV, 2 set HCLKDIV, 3 observe AXI VC, 4 set AXI VC.
 * 5 observes BOTH registers without writing either.
 * Mode 4 first observes and requires inherited HCLKDIV=0x190, so the AXI
 * change cannot silently combine with an earlier divider experiment.
 * No PHY, HCE, or CPM-domain change is implied by these opt-ins. */
#ifndef TGL_UFS_PRELINK_MODE
#define TGL_UFS_PRELINK_MODE 0
#endif
#if TGL_UFS_PRELINK_MODE < 0 || TGL_UFS_PRELINK_MODE > 5
#error "TGL_UFS_PRELINK_MODE must be in 0..5"
#endif
/* Separate causal profile: use exact UFS HSIO_S SMC clocks and selector-6
 * reset. Default 0 preserves the legacy physical profile byte for byte.
 * A synchronous firmware call is not software-timeout bounded; coordinator
 * must establish its recovery posture before any physical activation. */
#ifndef TGL_UFS_G5_DOMAIN
#define TGL_UFS_G5_DOMAIN 0
#endif
#if TGL_UFS_G5_DOMAIN != 0 && TGL_UFS_G5_DOMAIN != 1
#error "TGL_UFS_G5_DOMAIN must be 0 or 1"
#endif
#define UU_HCLKDIV              0xf8u
#define UU_HCLKDIV_VALUE        0xc8u
#define UU_TOP_AXI_VC           0x200u
#define UU_TOP_AXI_VC_VALUE     0x101u
#define UU_TOP_AXI_VC_MASK      0x707u
/* Single-variable reset omission diagnostic. Clock puts and admission stay
 * unchanged. A skipped request is not a successful reset acknowledgement. */
#ifndef TGL_UFS_SKIP_LEGACY_RESET
#define TGL_UFS_SKIP_LEGACY_RESET 0
#endif
#if TGL_UFS_SKIP_LEGACY_RESET != 0 && TGL_UFS_SKIP_LEGACY_RESET != 1
#error "TGL_UFS_SKIP_LEGACY_RESET must be 0 or 1"
#endif
#if TGL_UFS_SKIP_LEGACY_RESET && (!TGL_UFS_LOCAL_DME_DIAG || !TGL_UFS_LOCAL_DME_POST || TGL_UFS_G5_DOMAIN)
#error "TGL_UFS_SKIP_LEGACY_RESET requires DIAG=1 POST=1 G5_DOMAIN=0"
#endif
#define UU_LEGACY_RESET_SKIP_STAMP UINT64_C(0x534b495052535403) /* SKIPRST + id3 */

/* M2 HIBERN8-exit candidate (CL4 discriminator; ATTEMPTS.md 2026-10-28 M1
 * header pre-registered it pending the post-skip GET decode). The M1 capture
 * reads the four lane FSM selectors as 1 = M-PHY HIBERN8 at the moment
 * LINK_STARTUP completes result 1 in ~0.2 ms, and laguna ABL hands over only
 * after UIC 0x17 DME_HIBERNATE_ENTER plus a WLUN 0xd0 PowerDown
 * (UFS-HANDOFF-AUDIT.md 268-273, captured-binary disassembly; pixelios
 * gs101 docs/08-abl-ufs-shutdown.md). Linux's resume order ungates clocks,
 * then issues UIC 0x18 DME_HIBERN8_EXIT before any LINK work — literal 0x18
 * with zero args in ios-bluejay-rts shim.c:1254-1257. Default 0 keeps every
 * UIC command write LINK_STARTUP 0x16; enabling requires the DIAG/POST
 * evidence packet and the legacy domain, mirroring SKIP_LEGACY_RESET.
 * M3 composition additions inside this flag: the post-exit settle is a
 * counter-bounded u_settle_10ms (the volatile busy loop it replaces
 * consumed 4.3 s on the m2-hibern8 boot — F4 decode finding F2), and a
 * read-only IS.UHXS / HCS.UPMCRS observation packet (diag index 13,
 * phases 1/2/3) lands between the exit and the 8..12 POST GET packet so
 * any Hibern8 validation state is decodable, per F4's recommendation and
 * UFS-HANDOFF-AUDIT 400-403. Values gate nothing. */
#ifndef TGL_UFS_HIBERN8_EXIT
#define TGL_UFS_HIBERN8_EXIT 0
#endif
#if TGL_UFS_HIBERN8_EXIT != 0 && TGL_UFS_HIBERN8_EXIT != 1
#error "TGL_UFS_HIBERN8_EXIT must be 0 or 1"
#endif
#if TGL_UFS_HIBERN8_EXIT && (!TGL_UFS_LOCAL_DME_DIAG || !TGL_UFS_LOCAL_DME_POST || TGL_UFS_G5_DOMAIN)
#error "TGL_UFS_HIBERN8_EXIT requires DIAG=1 POST=1 G5_DOMAIN=0"
#endif
#define UU_DME_HIBERN8EXIT	0x18u	/* 0x17 = HIBERNATE_ENTER at ABL handoff */
#define UU_HIBERN8_EXIT_STAMP	UINT64_C(0x4838455849540000) /* ASCII "H8EXIT"+0000 */

/* M3 puts-guard candidate (the M2 decode's queued next step; ATTEMPTS.md
 * 2026-10-28). The M1/M2 captures bracket the DME_LAYER_EN 1->0 drop to
 * exactly the two LPCM clock-put pairs in the depth path: pre-puts local
 * GETs read [1,1,1,1,1] with DME_LAYER_EN (selector 0xd0000000) = 1, and
 * the post-depth packet reads [0,...] across a window whose only hardware
 * operations were those puts (ufs-clk DONE 0x300 / 0x1000, depth 0 and 1)
 * plus stamps. Omitting the puts before LINK_STARTUP tests whether DN
 * survives without them. Default 0 keeps every depth request; enabling
 * requires the DIAG/POST evidence packet and the legacy domain, mirroring
 * SKIP_LEGACY_RESET/HIBERN8_EXIT. A skipped request is not a clock
 * acknowledgement; tgl_cpm_init's own handshake stays armed (the refined
 * suspect if DN still drops). */
#ifndef TGL_UFS_SKIP_CLOCK_PUTS
#define TGL_UFS_SKIP_CLOCK_PUTS 0
#endif
#if TGL_UFS_SKIP_CLOCK_PUTS != 0 && TGL_UFS_SKIP_CLOCK_PUTS != 1
#error "TGL_UFS_SKIP_CLOCK_PUTS must be 0 or 1"
#endif
#if TGL_UFS_SKIP_CLOCK_PUTS && (!TGL_UFS_LOCAL_DME_DIAG || !TGL_UFS_LOCAL_DME_POST || TGL_UFS_G5_DOMAIN)
#error "TGL_UFS_SKIP_CLOCK_PUTS requires DIAG=1 POST=1 G5_DOMAIN=0"
#endif
#define UU_CLOCK_PUTS_SKIP_STAMP UINT64_C(0x505554534b495003) /* ASCII "PUTSKIP"+id3 */

/* M4 power-down-guard candidate (the m3-putsguard refutation's queued next
 * step; ATTEMPTS.md 2026-10-28 ledger row + F4 decode). The M3 capture
 * (img 5b51c305..., nonce 0x9167fdd21b7d94b6) still read the post-depth GET
 * packet [0,3,5,1,1] — DME_LAYER_EN dropped 1->0 with the clock puts AND the
 * legacy reset both omitted — across a window whose remaining in-ladder
 * power-state steps were the depth-1 PD pair (ufs-pd DONE 0x18) and the
 * Hibern8 exit. Omit the PD pair as well so the ladder runs on the inherited
 * power state alone; if DN still reads 0 the window analysis is confirmed
 * and the marker-only reading of the verify-only PD stamp stands (suspects
 * refine to cpm_init's handshake, the exit, the GET traffic, or the
 * ABL-handoff state). Default 0 keeps the depth-1 PD marker; enabling
 * requires the DIAG/POST evidence packet and the legacy domain, mirroring
 * SKIP_LEGACY_RESET/HIBERN8_EXIT/SKIP_CLOCK_PUTS. A skipped step is not a
 * power-state acknowledgement; values gate nothing. */
#ifndef TGL_UFS_SKIP_POWER_DOWN
#define TGL_UFS_SKIP_POWER_DOWN 0
#endif
#if TGL_UFS_SKIP_POWER_DOWN != 0 && TGL_UFS_SKIP_POWER_DOWN != 1
#error "TGL_UFS_SKIP_POWER_DOWN must be 0 or 1"
#endif
#if TGL_UFS_SKIP_POWER_DOWN && (!TGL_UFS_LOCAL_DME_DIAG || !TGL_UFS_LOCAL_DME_POST || TGL_UFS_G5_DOMAIN)
#error "TGL_UFS_SKIP_POWER_DOWN requires DIAG=1 POST=1 G5_DOMAIN=0"
#endif
#define UU_POWER_DOWN_SKIP_STAMP UINT64_C(0x5044534b49500018) /* ASCII "PDSKIP"+00+pd 0x18 */

/* UFS_LINK arg prefix for prelink evidence, distinct from UIC phase args. */
#define UU_PRELINK_STAMP_TAG    UINT64_C(0x5000000000000000)
#define UU_HCE			0x34u
#define UU_UTRLBA		0x50u
#define UU_UTRLBAU		0x54u
#define UU_UTRLDBR		0x58u
#define UU_UTRLCLR		0x5cu
#define UU_UTRLRSR		0x60u
#define UU_MEM_CFG		0x300u

/* Driver-mirrored gate bits. */
#define UU_HCS_DP		(1u << 0)
#define UU_HCS_UTRLRDY		(1u << 1)
#define UU_CAP_64AS		(1u << 24)
#define UU_MCQ_MODE_SELECT	(1u << 0)
#define UU_UTRD_CT_UFS		(1u << 28)
#define UU_UTRD_DD_IN		(2u << 25)
#define UU_UTRD_DD_NONE		(0u << 25)
#define UU_OCS_INVALID		0x0fu
#define UU_UPIU_COMMAND		0x01u
#define UU_UPIU_RESPONSE	0x21u
#define UU_UPIU_FLAG_READ	0x40u
#define UU_UPIU_IID_ONE		0x10u	/* Google Laguna sets IID to one */

/* DMA slab layout — the kernel driver's geometry, 4096-aligned .bss (the
 * shim runs MMU-off: VA is the PA). PA is stamped at U5 so the dump can
 * find descriptors. Driver: bounce 1 MiB, PRDT chunks 256 KiB. */
#define UU_DMA_UTRL		0x0000u		/* 32 B request list slot 0 */
#define UU_DMA_UCD		0x1000u		/* 512 B cmd + 512 B resp UPIU */
#define UU_DMA_BOUNCE		0x4000u		/* 1 MiB data bounce */
#define UU_BOUNCE_SIZE		(1u << 20)
#define UU_PRDT_CHUNK		(256u << 10)
#define UU_PRDT_MAX		(UU_BOUNCE_SIZE / UU_PRDT_CHUNK)
#define UU_DMA_SIZE		(UU_DMA_BOUNCE + UU_BOUNCE_SIZE)
#define UU_BLOCK		4096u
#define UU_G5_DMA_LIMIT		(1ULL << 36)
#define UU_TIMEOUT_POLLS	100u		/* 100 x ~10 ms <= 1 s + guard */
#define UU_MAX_GPT_ENTRIES	8192u		/* driver bound: bounce/128 */

/* Staging image contract (P2 builder: ufs-staging/build-staging-image.py).
 * APFS container superblock: NXSB magic at +0x20 of block 0, u32 block
 * size at +0x24, u64 block count at +0x28. Manifest block immediately
 * after the image blocks, magic "UFSSTG1". */
#define TGL_UFS_TARGET		"userdata_exp.ai"
#define TGL_UFS_STAGE_MAGIC_OFF	0x20u
#define TGL_UFS_STAGE_MAGIC	0x4253584eu /* ASCII "NXSB" as LE u32 */
#define TGL_UFS_STAGE_BSIZE_OFF	0x24u
#define TGL_UFS_STAGE_BLKS_OFF	0x28u
#define TGL_UFS_MANIFEST_MAGIC	UINT64_C(0x0031475453534655) /* "UFSSTG1\0" LE */
#ifndef TGL_UFS_STAGE_BLOCKS
#define TGL_UFS_STAGE_BLOCKS	604671u	/* system.apfs 637103e1..., 2.31 GiB */
#endif
#define TGL_UFS_STAGE_BYTES	((uint64_t)TGL_UFS_STAGE_BLOCKS * UU_BLOCK)

/* Stamp ids 0x0048..0x0054 live in tgl_stamp.h (canonical table; the G4
 * spec's 0x0030..0x003b seating collided with the R1 display block and
 * was re-seated — see the comment there). Reason code TGL_STAMP_R_UFS = 8
 * ("ufs-never-came-up") is in tgl_stamp.h too. */

/* Ladder result consumed by loader.c (honest handoff) and shim.c console. */
struct tgl_ufs_result {
	unsigned attempted;	/* ladder ran this boot (one-attempt latch) */
	unsigned live;		/* U8 reached: host left live and attested */
	unsigned steps;		/* bitmap, see TGL_STAGE_UFS_FIRST */
	unsigned failed_step;	/* 0 = none; else 1+index of first U-fail */
	uint32_t cap, ver, ahit, ie, hce, hcs, mem_cfg;
	uint32_t rsr, dbr;	/* UTRLRSR / UTRLDBR at U1 */
	uint32_t ba_lo, ba_hi;	/* UTRLBA/BAU at U1 (the prior list PA) */
	uint32_t psm[3];
	uint64_t prior_list_pa;	/* UTRLBA(U) seen before OUR takeover */
	uint64_t dma_pa;	/* our descriptor slab PA (stamped at U5) */
	uint64_t lun_last_lba;	/* U6: whole-LUN last LBA */
	uint32_t lun_block_size;
	uint64_t part_first_lba, part_last_lba;	/* U7: target entry range */
	uint64_t stage_blocks;	/* U7b: NXSB block count read back */
	uint32_t stage_block_size;
};

/* Run U0-U9 once. Never blocks unbounded, never parks, safe to call only
 * from shim_main after the EP0 console is up (U0 precondition). */
void tgl_ufs_probe_ladder(struct tgl_ufs_result *out);

/* v3.9b (U1, fix B): run the ladder inside the section guard. Returns 0
 * when the ladder completed normally (call tgl_ufs_result()), 1 when a
 * fault ANYWHERE inside it unwound here — the caller then finishes with
 * tgl_ufs_trap_fail(esr, far) and the boot continues on the recovery
 * profile. This is the make-it-never-brick guarantee: a probe can never
 * take the shim down. */
unsigned tgl_ufs_guarded_ladder(struct tgl_ufs_result *out);

/* v3.9b (U1, fix B): the guard-unwind fail path — records the ESR/FAR as
 * two TGL_STAGE_UFS_FIRST FAULT stamps, marks the ladder attempted+failed
 * (live=0, reason 8 "ufs-never-came-up"), latches the one-attempt latch.
 * Safe to call exactly once per boot; later calls return. */
void tgl_ufs_trap_fail(uint64_t esr, uint64_t far_val);

/* v3.9b (U1, fix A): override the UFSHCI base + PSM status trio from the
 * ABL FDT's UFS node (fdt_find_ufs). A zero or page-misaligned hc is
 * refused and the build-time fallback constants stay armed; absent PSM
 * tuples (0) keep their fallbacks individually. Call before the ladder. */
void tgl_ufs_set_regions(uint64_t hc, const uint64_t psm[3]);

/* Runtime bases (FDT override or fallback constants); host-test visible. */
uint64_t tgl_ufs_hc_base(void);

/* True after the first call of tgl_ufs_probe_ladder this boot (the
 * one-attempt-per-boot latch; a second call returns the cached result). */
unsigned tgl_ufs_attempted(void);

/* The cached result of this boot's ladder (all zeros before it ran). */
const struct tgl_ufs_result *tgl_ufs_result(void);

/* Honest handoff (PLAN.md 4.3): called by loader.c on the payload's
 * 608-byte cmdline BEFORE it is copied into boot_args.
 *   returns 0  cmdline admitted unchanged (ladder LIVE, or nothing to gate)
 *   returns 1  cmdline REWRITTEN to the recovery profile (tokens dropped,
 *              rd=ufsroot0 -> rd=md0); always length-shrinking
 *   returns -1 malformed (no NUL within 608): caller must refuse the boot
 * Rewrite is stamped (TGL_STAGE_UFS_LIVE REFUSED) so dumps see it. */
int tgl_ufs_cmdline_admit(char *cmdline, const struct tgl_ufs_result *r);

/* Descriptor slab PA accessor (also used by the host test harness). */
uintptr_t tgl_ufs_dma_pa(void);
