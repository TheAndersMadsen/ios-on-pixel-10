#pragma once
#include <stdint.h>

/*
 * TSHIMST2 — shim early-evidence stamp channel (v3.3, S1 lane).
 *
 * Device-proven on 2026-10-27 (research/session-20261027-usbboot): the v3.2
 * channel correctly named usb-preflight as the death stage — but its 8-slot
 * ring saturated (16 stamps DROPPED, including the refusal stamp and two
 * ABL slot-ladder re-entries) and slots carried no per-stamp timestamp, so
 * "which check refused, what the hardware returned, and where 26 s went"
 * were all invisible. v2 ABI fixes all three:
 *   - originally 64 slots; now 128 within the same empirically clear
 *     pmsg+0x30000..+0x30FFF window (3136 bytes including the header)
 *   - every stamp carries its own cntvct timestamp
 *   - preflight stamps the VALUE of each MMIO read and each refusal branch
 *     gets a distinct stage id
 *
 * RAM-only writes, no MMIO in the stamp path, no loops beyond the constant
 * 64-byte init (DER Event 20 discipline).
 *
 * Layout (little-endian), ABI v2 ("TSHIMST2"):
 *   header 64 B at PA+0x00 (identical field layout to v1 — decoder shares it):
 *     0x00 magic "TSHIMST2"
 *     0x08 nonce     u64  (per-build, -DTGL_STAMP_NONCE=...)
 *     0x10 count     u32  (slots appended, saturates at TGL_STAMP_SLOTS)
 *     0x14 seq       u32  (last retained sequence; freezes at saturation)
 *     0x18 last_stage u32 (last stamped stage id)
 *     0x1c flags     u32  (last stamp flags)
 *     0x20 freq      u64  (cntfrq_el0 at entry; 0 on a host sink)
 *     0x28 t0        u64  (cntvct at entry)
 *     0x30 tlast     u64  (last retained time; focused filtering also updates it)
 *     0x38 dropped   u32  (stamps discarded after saturation)
 *     0x3c reason    u32  (terminal code: TGL_STAMP_R_*)
 *   slots: TGL_STAMP_SLOTS x 24 B at PA+0x40:
 *     +0x00 seq   u32
 *     +0x04 stage u16
 *     +0x06 flags u16
 *     +0x08 t     u64  (cntvct at this stamp; ms = (t-t0)/freq*1000)
 *     +0x10 arg   u64
 *   (v1 "TSHIMST1" dumps keep 8 x 16 B slots {seq,stage,flags,arg}; the
 *   decoder branches on the magic, so old dumps stay readable.)
 *
 * A stamp appends the slot BEFORE updating the header, so a torn header can
 * only understate the history. Same-nonce PSCI reset re-entry APPENDS: the
 * ABL slot ladder's repeated attempts each leave their full trail.
 */

#define TGL_STAMP_BASE		UINT64_C(0x95430000)	/* pmsg+0x30000 */
#define TGL_STAMP_SLOTS		128u	/* 64 B header + 128x24 B = 3136 B,
					 * inside the empirically clear
					 * pmsg+0x30000..0x30FFF window */
#define TGL_STAMP_MAGIC		UINT64_C(0x3254534d49485354) /* "TSHIMST2" */
#define TGL_STAMP_MAGIC_V1	UINT64_C(0x3154534d49485354) /* "TSHIMST1" (decoder only) */
#ifndef TGL_STAMP_NONCE
#define TGL_STAMP_NONCE		UINT64_C(0) /* build.sh injects the real one */
#endif

/* Stage ids. Enter-flags go on BEFORE every risky wait so a hang names the
 * wait it hung in; done-flags stamp the successful exit. */
#define TGL_STAGE_ENTRY		0x0001u	/* start.S, physical addressing */
#define TGL_STAGE_CPU_STATE	0x0002u	/* arg = CurrentEL<<28|SCTLR (MMU state) */
#define TGL_STAGE_WDT_SURVEY	0x0003u
#define TGL_STAGE_FDT_PARSE	0x0004u
#define TGL_STAGE_CONSOLE_INIT	0x0005u
#define TGL_STAGE_WDT_PAT	0x0006u
#define TGL_STAGE_USB_PREFLIGHT	0x0007u
#define TGL_STAGE_DMA_ADMIT	0x0008u
#define TGL_STAGE_CPM_ACK_ENTER	0x0009u	/* queue-init ACK wait entered */
#define TGL_STAGE_CPM_ACK_DONE	0x000au
#define TGL_STAGE_CPM_SEND	0x000bu	/* a clock/reset request wait entered */
#define TGL_STAGE_PHY_RESUME	0x000cu	/* board_resume/PHY enable entered */
#define TGL_STAGE_DWC3_HALT	0x000du	/* DSTS.DEVCTRLHLT wait entered */
#define TGL_STAGE_DWC3_RESET	0x000eu	/* CSFTRST wait entered */
#define TGL_STAGE_EP0_CONFIG	0x000fu	/* DEPSTARTCFG/SETEPCONFIG entered */
#define TGL_STAGE_EP0_READY	0x0010u	/* RUN_STOP set, gadget polling */
#define TGL_STAGE_USB_WAIT	0x0011u	/* diagnostic enumeration window */
#define TGL_STAGE_PAYLOAD	0x0012u	/* payload admission entered */
#define TGL_STAGE_HANDOFF	0x0013u	/* pre-XNU jump entered */
#define TGL_STAGE_WDT_QUIESCE	0x0014u	/* pre-handoff stop */
/* v3.3 preflight value-evidence ids (each MMIO read stamps ITS VALUE; each
 * refusal branch has a distinct id). */
#define TGL_STAGE_USB_PWR	0x0015u	/* arg = USB2 PMU power status */
#define TGL_STAGE_USB_GSNPSID	0x0016u	/* arg = DWC3 GSNPSID */
#define TGL_STAGE_USB_GCTL	0x0017u	/* arg = DWC3 GCTL */
#define TGL_STAGE_USB_EVT_HI	0x0018u	/* arg = inherited GEVNTADRHI */
#define TGL_STAGE_USB_BADID	0x0019u	/* refusal: foreign GSNPSID */
#define TGL_STAGE_USB_BADCAP	0x001au	/* refusal: PRTCAPDIR not device */
#define TGL_STAGE_USB_EVTHANG	0x001bu	/* refusal: stale event address (hi) */
#define TGL_STAGE_USB_BADPWR	0x001cu	/* refusal: USB2 PMU not D0 */
#define TGL_STAGE_CONSOLE_CLS	0x001du	/* full text-region paint completed */
/* v3.4 CPM-first ids (per research/laguna-usb-fix/CPM-FIRST-SPEC.md §6.3);
 * 0x0020 is reserved by that spec's table (0x001f -> 0x0021). */
#define TGL_STAGE_CPM_FIRST	0x001eu	/* ENTER before S1, DONE at S7 (bitmap) */
#define TGL_STAGE_CPM_GEO	0x001fu	/* mailbox geometry/state, arg tx<<16|rx */
#define TGL_STAGE_CPM_CLK	0x0021u	/* clock-gate req, arg id<<8|response */
#define TGL_STAGE_CPM_RST	0x0022u	/* reset-deassert req, arg id<<8|response */
/* v3.5 warm-first ids (per ABL-USB-STATE.md: fastboot handoff leaves USB
 * warm — clocks on, GCTL device-mode, GSNPSID readable; only DCTL.RUN_STOP
 * cleared). */
#define TGL_STAGE_USB_WARM	0x0023u	/* warm probe: DONE=YES arg=gsnpsid, REFUSED=NO */
#define TGL_STAGE_USB_DCTL	0x0024u	/* inherited DCTL fingerprint, arg=value */
#define TGL_STAGE_MBA_LIVE	0x0025u	/* 3-mailbox liveness, arg=readable bitmap */
#define TGL_STAGE_MBA_SEND	0x0026u	/* pointer-message send, arg=seq<<24|chan<<16|code */
#define TGL_STAGE_MBA_ACK	0x0027u	/* response wait/validation, arg=response word */
#define TGL_STAGE_EL_DROP	0x0028u	/* B1 entry contract: ENTER at EL2 before
				 * eret (arg = entry CurrentEL), DONE as the
				 * first EL1 action (arg = new EL << 28) */
#define TGL_STAGE_MBA_RESP0	0x0029u	/* first poll read of the send, arg=raw word */
#define TGL_STAGE_CPM_GEO2	0x002au	/* LPCM mailbox magic, arg=[0x05250000] */
/* v3.8 LPCM wire-evidence ids: full request echo + full in-place reply per
 * request (A-ABL3 diffs these against ABL's builder output). */
#define TGL_STAGE_LPCM_REQ0	0x002bu	/* arg = request dword0 (header) */
#define TGL_STAGE_LPCM_REQ1	0x002cu	/* arg = request dword1 (cmd) */
#define TGL_STAGE_LPCM_REPLY0	0x002du	/* arg = reply dword0 (type tag) */
#define TGL_STAGE_LPCM_REPLY1	0x002eu	/* arg = reply dword1 (status) */
#define TGL_STAGE_USB_LINK	0x002fu	/* link-state sample, arg=DCFG<<32|DSTS */
#define TGL_STAGE_CPM_PHY	0x0030u	/* USB2 PHY revive sequence (A-ABL3 §4) *//* R1 display-revive ids, reserved in /tmp/fleet/COORDINATION.md. Snapshot
 * ENTER arg=PA, DONE arg=read value; no snapshot value asserts scanout. */
#define TGL_STAGE_DISP_RECORD	0x0031u	/* 128-byte handoff build/seal */
#define TGL_STAGE_DISP_GATE	0x0032u	/* runtime tgl_disp_* gate + final verdict */
#define TGL_STAGE_DISP_POWER	0x0033u	/* queue/DPU power proof, arg=domains */
#define TGL_STAGE_DISP_SNAP	0x0034u	/* ENTER arg=DAIF<<32|domain bitmap */
#define TGL_STAGE_DISP_S1_ADDR_LO	0x0035u
#define TGL_STAGE_DISP_S1_ADDR_HI	0x0036u
#define TGL_STAGE_DISP_S2_CONFIG	0x0037u
#define TGL_STAGE_DISP_S2_SIZE	0x0038u
#define TGL_STAGE_DISP_S2_STRIDE	0x0039u
#define TGL_STAGE_DISP_S3_COORD0	0x003au
#define TGL_STAGE_DISP_S3_COORD1	0x003bu
#define TGL_STAGE_DISP_S4_MODE	0x003cu	/* mode_ctrl + mode_status */
#define TGL_STAGE_DISP_S4_STATUS	0x003du	/* core_status + phy_status */
#define TGL_STAGE_DISP_S5_PHY	0x003eu	/* G301 PHY_STS + PHY_CTRL0 */
#define TGL_STAGE_DISP_R1	0x003fu	/* DPU top -> DSI0 -> FE0 complete */
#define TGL_STAGE_DISP_R2	0x0040u	/* pixel put/reset + clock isolation */
#define TGL_STAGE_DISP_R3	0x0041u	/* source-equivalent FE0-L0 program */
#define TGL_STAGE_DISP_R4	0x0042u	/* shadow commit + outpath start */
#define TGL_STAGE_DISP_R5	0x0043u	/* DSI2H0 + CDPHY cold init */
#define TGL_STAGE_DISP_R6	0x0044u	/* gs-bzea panel init + read proof */
#define TGL_STAGE_DISP_R7	0x0045u	/* DPU SMMU identity mapping proof */
#define TGL_STAGE_DISP_LIVE	0x0046u	/* panel-visible A/B photo + refresh */
/* P2 UFS probe-ladder ids (2026-10-28; ufs-staging/probe-ladder.md block
 * re-seated from 0x0030-0x003b — CPM_PHY took 0x0030 and the R1 display
 * block took 0x0031..0x0046, so UFS continues at 0x0048). */
#define TGL_STAGE_UFS_FIRST	0x0048u	/* ENTER at U0 / DONE at U9; arg = step
				 * bitmap hci|clk|pd|link|tur|cap|gpt|live|
				 * stage (bits 0..8) */
#define TGL_STAGE_UFS_HCI	0x0049u	/* U1: arg = CAP raw; FAULT on dead host */
#define TGL_STAGE_UFS_HCS	0x004au	/* U1/U4: arg = HCS raw */
#define TGL_STAGE_UFS_CLK	0x004bu	/* U2: arg = clock_id<<8|response */
#define TGL_STAGE_UFS_RST	0x004cu	/* U3: arg = reset_id<<8|response */
#define TGL_STAGE_UFS_PD	0x004du	/* U3: verify-only PD marker */
#define TGL_STAGE_UFS_TUR	0x004eu	/* U5: arg = ocs<<24|resp0<<16|
				 * resp6<<8|resp7 */
#define TGL_STAGE_UFS_RDCAP	0x004fu	/* U6: arg = last_lba (u32) */
#define TGL_STAGE_UFS_RDCAP1	0x0050u	/* U6: arg = block_size */
#define TGL_STAGE_UFS_GPT	0x0051u	/* U7: arg = count<<16|entry_size */
#define TGL_STAGE_UFS_PART	0x0052u	/* U7: arg = matched idx<<16|first-lba */
#define TGL_STAGE_UFS_LIVE	0x0053u	/* U8 DONE = THE blazer_ufs_live=1
				 * attestation; arg = HCS<<16|DBR */
#define TGL_STAGE_UFS_STAGE	0x0054u	/* U7b staged-image validate; arg =
				 * manifest version<<8|components */
#define TGL_STAGE_UFS_LINK	0x0055u	/* v3.9c link startup: DONE after
				 * DME_LINKSTARTUP + DP/UTRLRDY; REFUSED
				 * arg = uf_uic_cmd rc */
/* Slot/header flag bits. */
#define TGL_STAMP_F_ENTER	0x0001u
#define TGL_STAMP_F_DONE	0x0002u
#define TGL_STAMP_F_TIMEOUT	0x0004u
#define TGL_STAMP_F_FAULT	0x0008u
#define TGL_STAMP_F_REFUSED	0x0010u

/* Header reason codes (header word 0x3c). */
#define TGL_STAMP_R_NONE	0u
#define TGL_STAMP_R_TIMEOUT	1u
#define TGL_STAMP_R_FAULT	2u
#define TGL_STAMP_R_USBFATAL	3u
#define TGL_STAMP_R_REFUSED	4u
#define TGL_STAMP_R_HANDOFF	5u
#define TGL_STAMP_R_CPM	6u	/* CPM/MBA never came up (CPM-FIRST-SPEC §6.3) */
#define TGL_STAMP_R_IN_PROGRESS	7u	/* armed at entry: any watchdog reset
				 * mid-bring-up decodes as in-progress +
				 * last_stage instead of reason=none (v35
				 * device run: WDT beat a wedged send and
				 * the reason word stayed 0). */
#define TGL_STAMP_R_UFS		8u	/* "ufs-never-came-up" (tgl_ufs.c) */

/* Initialize (or re-attach to) the header and stamp TGL_STAGE_ENTRY. Safe on
 * the earliest C-callable path: after stack+bss in start.S. */
void tgl_stamp_boot_entry(void);

/* Append one stamp. Never blocks, never reads device state. */
void tgl_stamp(unsigned stage, unsigned flags, uint64_t arg);

/* Mark the header with a terminal reason (hang/timeout/fault/handoff). */
void tgl_stamp_reason(unsigned reason);

/* Read back the terminal reason (0 = none): lets the generic terminal path
 * preserve a more specific reason an earlier phase already recorded. */
unsigned tgl_stamp_reason_get(void);

/* Global bring-up watchdog (v3.6): 1 once more than `seconds` have passed
 * since tgl_stamp_boot_entry armed the channel. Stage boundaries must bail
 * through their own fail paths when this fires — the firmware watchdog is
 * patted, so an alive-but-stuck bring-up would otherwise run forever. */
unsigned tgl_stamp_over_deadline(unsigned seconds);

/* B1 entry contract helpers (called from the EL1 continuation in start.S
 * right after the EL2→EL1 eret): DONE stamp with the new EL in arg, then
 * the final "jumping" reason before the I-cache invalidate + branch. */
void tgl_stamp_el_drop_done(void);
void tgl_stamp_reason_handoff(void);

/* v3.8 terminal-failure stamping: stamp the CURRENTLY FAILING stage (the
 * channel header's last_stage — set by the granular ENTER/FAULT stamps each
 * phase already writes) with FAULT + code, instead of a coarse section
 * label that misattributes the failure (v37: terminal said usb-warm while
 * phy-resume had failed). Returns the stage id it stamped. */
unsigned tgl_stamp_fail_current(uint64_t code);

/* Host-test sink: redirect the channel into caller-provided memory. Never
 * called by device code. */
void tgl_stamp_set_sink(volatile void *base);

/* Stage name for host tools/decoders (returns "unknown" beyond the table). */
const char *tgl_stage_name(unsigned stage);
