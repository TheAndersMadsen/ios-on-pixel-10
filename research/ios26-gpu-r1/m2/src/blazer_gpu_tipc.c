#if defined(BLAZER)
/* SPDX-License-Identifier: MIT
 * The GPU firmware route, one rung a boot. Off unless boot-arg blazer_gpu_tipc=N. Runs once from a thread at cpus=1, and ends the boot with a panic naming the result.
 * =1: log Trusty's build, connect to the GPU TA, send PING, read the reply. No firmware, no carve-out, no GPU register, no vote.
 * =4: =2, then the shared firmware data, GPU on, SMC START, poll bFirmwareStarted and the connection. =5: =4, then one HEALTH_CHECK on the KCCB. The boot ends within seconds: nothing stops the firmware; the reset does. No job, no load.
 * =6 (M2, ios26-gpu-r1/M2.md): =4 with the firmware's own trace log switched on (the TRACEBUF stock fills when a log type is set), then the firmware's view
 *     printed from shared memory before any kick (OS runtime flags, CR poll, fault and assert buffers, FWCCB), then the commands in stock's order and shape:
 *     HEALTH_CHECK as RGXFWHealthCheckCmd sends it (consumption only: stock reserves no return slot for it and waits on none), then STATEFLAGS_CTRL with no
 *     flag change, whose return slot stock waits on (RGXFWSetFwConfigFlags: RGXSendCommandAndGetKCCBSlot + RGXWaitForKCCBSlotUpdate). PASS is CMD_EXECUTED there.
 *     After them: the view again, the firmware log as raw words (decoded on the host against rgx_fwif_sf.h), and blazer_gpu=3's 18 REE registers.
 * =2: log the build, check our firmware file, put it in the carve-out, send SEND_FIRMWARE_IMAGE once, read the reply. No START, no vote, no GPU register:
 *     stock sends this before its first power-on (pvrsrv.c: RGXInit, then PVRSRVSetDevicePowerStateKM). After the send, nothing here reads or writes the carve-out: the TA may protect it.
 * Transport: blazer_aoc.c's polled client, the same SMC list, compiled a second time with its own port and log prefix. One owner of Trusty's virtio per boot,
 * so this refuses to run with blazer_aoc or blazer_gpu on the line.
 * Protocol facts: gpu_secure_protocol.h, gpu_secure.c, GrapheneOS kernel_pixel_6.12 @5940a317 (GPL-2.0, facts only, no code copied). */
#define BLAZER_AOC_TRANSPORT 1
#define AOC_PORT              "com.android.trusty.pixel_gpu"
#define AOC_PORT_REFUSED      "pixel_gpu port refused"
#define AOC_SMC_EXTRA         case 0x33000000u: case 0x33000001u: case 0xc300000cu:    /* SMC_SC_SHARED_LOG_VERSION, _ADD. trusty-log.h, MIT. SMC_OEM_GPU_CONTROL, gpu_secure_protocol.h: =4,5 only */
#ifndef AOC_LOG
#define AOC_LOG(...) printf("HK GPUTA: " __VA_ARGS__)
#endif
#include "blazer_aoc.c"
#include "blazer_gpu_fwif.h"
#if defined(BLAZER_GPU_FW_DIAGNOSTIC) && BLAZER_GPU_FW_DIAGNOSTIC
#include "hmfw_diagnostic.h"
#include "hmfw_vendor_layout.h"
static unsigned gta_diag_wanted;
#endif
#include "hmfw_m2_layout.h"

#ifndef BLAZER_AOC_HOSTTEST
#include <machine/machine_routines.h>
extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern int blazer_gpu_power_on(vm_offset_t *rgx_out);
extern void blazer_gpu_survey_live(void);
#define gta_survey() blazer_gpu_survey_live()
#define gta_shared_map() ((volatile uint8_t *)ml_io_map((vm_offset_t)(GTA_CARVEOUT_PA + GF_MAIN_HEAP_OFF), GF_RAW_SIZE - GF_MAIN_HEAP_OFF))
#define gta_power_on(rgx) blazer_gpu_power_on(rgx)
#define gta_mts_kick(rgx, v) do { *(volatile uint32_t *)((rgx) + GTA_CR_MTS_SCHEDULE) = (v); __asm__ volatile ("dsb sy" : : : "memory"); } while (0)
#define gta_carveout_map() ((volatile uint32_t *)ml_io_map((vm_offset_t)GTA_CARVEOUT_PA, GTA_PRIVATE_SIZE))
/* blazer_gpu_fw.c: size as 8 bytes, 8 of padding, then the file */
extern const uint8_t blazer_gpu_fw[];
#endif

#define GTA_REQ_PING      0u      /* first of GPU_SECURE_CMDS */
#define GTA_RSP_LEN       8u      /* gpu_secure_rsp_base_t: command, result. gpu_secure_on_msg wants exactly this */

enum { GTA_PASS = 0, GTA_ANSWERED_ERROR = 1, GTA_STOPPED = -1 };

/* PASS: reply {PING, 0}. ANSWERED_ERROR: the TA is alive and refused PING in the right shape, a result worth having, and no reason to send anything else here. */
static int
gta_ping(void)
{
	static const uint8_t req[8] = { GTA_REQ_PING, 0, 0, 0, 0, 0, 0, 0 };
	const uint64_t t0 = aoc_now_ms();
	uint32_t cmd, result;

	if (aoc_send(aoc.remote, req, sizeof(req))) {
		return GTA_STOPPED;
	}
	if (!aoc_wait(&aoc.reply_ready, AOC_REPLY_MS)) {
		aoc_stop(aoc.connected ? "no PING reply in 5 s" : "TA closed the channel on PING");
		return GTA_STOPPED;
	}
	cmd = aoc_g32(aoc.reply);
	result = aoc_g32(aoc.reply + 4);
	AOC_LOG("PING len %u cmd 0x%x result %u in %llu ms\n", aoc.reply_len, cmd, result, aoc_now_ms() - t0);
	if (aoc.reply_len != GTA_RSP_LEN || cmd != GTA_REQ_PING) {
		aoc_stop("bad PING reply");
		return GTA_STOPPED;
	}
	return result == 0 ? GTA_PASS : GTA_ANSWERED_ERROR;
}

/* Rung 2. The layout is stock's, from RGXInitAllocFWImgMem's order and rgx_heaps_configure's heaps (config_kernel.h, lga production): each heap filled from its bottom, FwImage after coremem code.
 * Bottom-up is inferred. Aligned to 16 KiB, which also suits a 4 KiB host. */
#define GTA_CARVEOUT_PA    0xb9f00000ULL    /* FDT gpu_fw@b9f00000 */
#define GTA_PRIVATE_SIZE   0x200000u        /* SECURE_FW_MEM_SIZE */
#define GTA_OFF_CODE       0x0u
#define GTA_OFF_CCODE      0x30000u
#define GTA_OFF_BODY       0x3c000u
#define GTA_OFF_HDR        0x90000u
#define GTA_OFF_CODE_END   0x130000u        /* RGX_FW_CODE_SECTION_SIZE */
#define GTA_OFF_DATA       0x130000u
#define GTA_OFF_CDATA      0x13c000u
#define GTA_OFF_RODATA     0x1e0000u        /* + RGX_FW_DATA_SECTION_SIZE */
#define GTA_FWVA_HEAP      0xc0000000u      /* RGXFW_FW_HEAP_BASE_CACHED, gpu_secure.c */
#define GTA_REQ_SEND       1u
#define GTA_SEND_VERSION   1u               /* GPU_SECURE_REQ_FIRMWARE_VERSION_25_2 */
#define GTA_REQ_LEN        512u             /* sizeof(gpu_secure_req_firmware_t) */
#define GTA_USE_TF_A       1u               /* GPU_SECURE_TF_A */
#define GTA_HOST_SHIFT     12u              /* What the stock kernel sends if its PAGE_SHIFT is 12: inferred. Our sections suit 14 too */
#define GTA_SEND_MS        30000u           /* GPU_SECURE_TIMEOUT_MS */
#define GTA_HDR_SIZE       0x1000u          /* LGA_IMAGE_HEADER_SIZE */
#define GTA_HDR_VERSION    1u               /* LGA_IMAGE_HEADER_VERSION */
#define GTA_HDR_MAGIC_OFF  0x864u           /* LGA_IMAGE_HEADER_MAGIC_OFFSET */
#define GTA_HDR_MAGIC      0x46555047u      /* GPUF */
#define GTA_INFO_FROM_END  4096u            /* FW_BLOCK_SIZE */
#define GTA_FOOT_FROM_END  0x800u           /* PIXEL_FOOTER_AREA_OFFSET_FROM_END */
#define GTA_FOOT_MAGIC     0x1BADD00Du      /* PIXEL_FOOTER_MAGIC */
#define GTA_FW_ABI         41u              /* FW_ABI_VERSION */
#define GTA_BVNC_LO        0x099004bcu      /* rgx_bvnc_table_km.h, 71.2.2448.1212 */
#define GTA_BVNC_HI        0x00470002u
#define GTA_FW_MAJ         26u
#define GTA_FW_MIN         1u
/* From the file's own layout table, by RGX_FW_SECTION_TYPE. A different file is a STOP, not a new layout */
#define GTA_SZ_CODE        0x30000u
#define GTA_SZ_DATA        0xa000u
#define GTA_SZ_RODATA      0x3000u
#define GTA_SZ_CCODE       0xc000u
#define GTA_SZ_CDATA       0x4840u

struct gta_fw {
	const uint8_t *hdr, *body;
	uint32_t hdr_size, body_size;
};

/* Pure: nothing goes out until the file is the one all this was read from. Returns the failed check, or NULL */
static const char *
gta_fw_check(const uint8_t *file, uint32_t len, struct gta_fw *out)
{
	uint32_t sizes[6] = { 0, 0, 0, 0, 0, 0 };
	uint32_t entry, hlen, n, es;
	const uint8_t *img, *body, *info, *foot;

	if (len < 4 || (entry = aoc_g32(file)) != len - 4 || (entry & 3) || entry < GTA_HDR_SIZE + GTA_INFO_FROM_END) {
		return "catalogue entry size";
	}
	img = file + 4;
	if (aoc_g32(img) != GTA_HDR_VERSION || aoc_g32(img + GTA_HDR_MAGIC_OFF) != GTA_HDR_MAGIC) {
		return "image header";
	}
	foot = img + entry - GTA_FOOT_FROM_END;
	if (aoc_g32(foot) != GTA_FW_ABI || aoc_g32(foot + 4) != GTA_FOOT_MAGIC) {
		return "footer ABI";
	}
	body = img + GTA_HDR_SIZE;
	info = img + entry - GTA_INFO_FROM_END;
	hlen = aoc_g32(info + 4);
	n = aoc_g32(info + 8);
	es = aoc_g32(info + 12);
	if (aoc_g32(info) != 3 || hlen < 0x30 || es != 24 || n == 0 || n > 8 || hlen + n * es > GTA_INFO_FROM_END) {
		return "FW info header";
	}
	if (aoc_g32(info + 16) != GTA_BVNC_LO || aoc_g32(info + 20) != GTA_BVNC_HI) {
		return "BVNC";
	}
	if (aoc_g16(info + 32) != GTA_FW_MAJ || aoc_g16(info + 34) != GTA_FW_MIN) {
		return "FW version";
	}
	for (uint32_t i = 0; i < n; i++) {
		const uint8_t *e = info + hlen + i * es;
		uint32_t type = aoc_g32(e + 4);

		if (type == 0 || type > 5) {
			return "section type";
		}
		sizes[type] += aoc_g32(e + 16);
	}
	if (sizes[1] != GTA_SZ_CODE || sizes[2] != GTA_SZ_DATA || sizes[3] != GTA_SZ_RODATA || sizes[4] != GTA_SZ_CCODE || sizes[5] != GTA_SZ_CDATA) {
		return "section sizes";
	}
	out->hdr = img;
	out->hdr_size = GTA_HDR_SIZE;
	out->body = body;
	out->body_size = entry - GTA_HDR_SIZE;
	if (GTA_OFF_BODY + out->body_size > GTA_OFF_HDR || GTA_OFF_HDR + GTA_HDR_SIZE > GTA_OFF_CODE_END) {
		return "body does not fit";
	}
	return NULL;
}

static void
gta_put_mem(uint8_t *m, uint32_t off, uint32_t fw_va, uint32_t size)
{
	aoc_p64(m, GTA_CARVEOUT_PA + off);
	aoc_p32(m + 8, fw_va);
	aoc_p32(m + 12, size);
}

/* Word writes: the carve-out is mapped as device memory, so no cache maintenance and nothing the TA can miss */
static void
gta_copy(volatile uint32_t *to, const uint8_t *from, uint32_t len)
{
	for (uint32_t i = 0; i < len; i += 4) {
		to[i / 4] = (uint32_t)from[i] | (uint32_t)(i + 1 < len ? from[i + 1] : 0) << 8 |
		    (uint32_t)(i + 2 < len ? from[i + 2] : 0) << 16 | (uint32_t)(i + 3 < len ? from[i + 3] : 0) << 24;
	}
}

static uint32_t gta_result;

/* Sent once. PASS: reply {SEND, 0}. The TA holds this as received: a second send in a boot is refused by it (string, static) */
static int
gta_send_firmware(const struct gta_fw *fw)
{
	static uint8_t req[GTA_REQ_LEN];
	volatile uint32_t *c = gta_carveout_map();
	const uint64_t t0 = aoc_now_ms();
	uint32_t cmd;

	if (!c) {
		aoc_stop("cannot map the carve-out");
		return GTA_STOPPED;
	}
	for (uint32_t i = 0; i < GTA_PRIVATE_SIZE / 4; i++) {
		c[i] = 0;       /* stock: PVRSRV_MEMALLOCFLAG_ZERO_ON_ALLOC. Writes only; the carve-out is never read */
	}
	gta_copy(c + GTA_OFF_BODY / 4, fw->body, fw->body_size);
	gta_copy(c + GTA_OFF_HDR / 4, fw->hdr, fw->hdr_size);
	aoc_barrier();
	AOC_LOG("carve-out written: body %u at +0x%x, header %u at +0x%x\n", fw->body_size, GTA_OFF_BODY, fw->hdr_size, GTA_OFF_HDR);
	memset(req, 0, sizeof(req));
	aoc_p32(req, GTA_REQ_SEND);
	aoc_p32(req + 4, GTA_SEND_VERSION);
	gta_put_mem(req + 8, GTA_OFF_BODY, 0, fw->body_size);
	gta_put_mem(req + 24, GTA_OFF_HDR, 0, fw->hdr_size);
	gta_put_mem(req + 40, GTA_OFF_CODE, 0, GTA_SZ_CODE);
	gta_put_mem(req + 56, GTA_OFF_DATA, 0, GTA_SZ_DATA);
	gta_put_mem(req + 72, GTA_OFF_RODATA, 0, GTA_SZ_RODATA);
	gta_put_mem(req + 88, GTA_OFF_CCODE, GTA_FWVA_HEAP + GTA_OFF_CCODE, GTA_SZ_CCODE);
	gta_put_mem(req + 104, GTA_OFF_CDATA, GTA_FWVA_HEAP + GTA_OFF_CDATA, (GTA_SZ_CDATA + 0xfffu) & ~0xfffu);
	aoc_p32(req + 120, GTA_USE_TF_A);
	aoc_p32(req + 124, GTA_HOST_SHIFT);
	if (aoc_send(aoc.remote, req, sizeof(req))) {
		return GTA_STOPPED;
	}
	if (!aoc_wait(&aoc.reply_ready, GTA_SEND_MS)) {
		aoc_stop(aoc.connected ? "no SEND_FIRMWARE_IMAGE reply in 30 s" : "TA closed the channel on SEND_FIRMWARE_IMAGE");
		return GTA_STOPPED;
	}
	cmd = aoc_g32(aoc.reply);
	gta_result = aoc_g32(aoc.reply + 4);
	AOC_LOG("SEND_FIRMWARE_IMAGE len %u cmd 0x%x result %u in %llu ms\n", aoc.reply_len, cmd, gta_result, aoc_now_ms() - t0);
	if (aoc.reply_len != GTA_RSP_LEN || cmd != GTA_REQ_SEND) {
		aoc_stop("bad SEND_FIRMWARE_IMAGE reply");
		return GTA_STOPPED;
	}
	return gta_result == 0 ? GTA_PASS : GTA_ANSWERED_ERROR;
}

static void gta_log_add(void);
static void gta_log_dump(void);

/* Rungs 4, 5. Facts: rgxfwutils.c RGXSetupFwOsData, RGXSetupFwSysData, RGXSetupCCB, RGXSendCommandRaw; rgxpower.c RGXPostPowerState; gpu_secure.c; rgx_heap_firmware.h. Offsets: blazer_gpu_fwif.h.
 * The TEE maps all firmware heaps (RGXPremapHostHeaps, "done by TEE"). Config heap at its fixed place, the firmware computes it. Everything else from the bottom of the main heap, 4 KiB apart.
 * Left zero against stock, each named: config flags, trace, signature buffers, register config, OPP table, BVNC feature flags, timer arrays. No fabric vote, no SLC set-up. Each is a next thing to try. */
#define GTA_VA_CACHED      0xc0000000u      /* RGXRISCVFW_SHARED_CACHED_DATA0_BASE */
#define GTA_VA_UNCACHED    0x40000000u      /* RGXRISCVFW_SHARED_UNCACHED_DATA0_BASE */
#define GTA_SH_CONN        ((uint32_t)GF_CONFIG_HEAP_OFF)
#define GTA_SH_OSINIT      ((uint32_t)(GF_CONFIG_HEAP_OFF + GF_CONFIG_GRAN))
#define GTA_SH_SYSINIT     ((uint32_t)(GF_CONFIG_HEAP_OFF + 2 * GF_CONFIG_GRAN))
#define GTA_CORE_HZ        300000000u       /* FDT init-frequency-hz */
#define GTA_SOC_HZ         38400000u        /* GTC_FREQUENCY_HZ, sources_copts.bzl */
#define GTA_APM_MS         60000u           /* Stock's FDT says 1 ms. Long here: nothing below handles a power-off request. Ours */
#define GTA_SPU_MASK       3u               /* NUM_SPU 2 */
#define GTA_RAC_MASK       3u               /* SPU0, SPU1 RAC_PRESENT */
#define GTA_OS_READY       1u               /* RGXFW_CONNECTION_OS_READY */
#define GTA_FW_ACTIVE      2u               /* RGXFW_CONNECTION_FW_ACTIVE */
#define GTA_SMC_GPU        0xc300000cu
#define GTA_SMC_START      1u
#define GTA_CR_MTS_SCHEDULE 0xb00u          /* rgx_cr_defs_km.h */
#define GTA_KICK_GP        0u               /* RGXFWIF_DM_GP & ~DM_CLRMSK, RGXSendCommandRaw */
#define GTA_START_MS       1000u
#define GTA_ACTIVE_MS      3000u
#define GTA_HEALTH_MS      1000u
/* Rung 6 (M2). The trace buffer is stock's default size; the groups are the ones whose messages name KCCB slots, driver state, power, HWR and faults */
#define GTA_TB_DW          ((uint32_t)HMFV2_TB_DEFAULT_DW)
#define GTA_LOG_M2         ((uint32_t)(HMFV2_LOG_TYPE_TRACE | HMFV2_LOG_M2_GROUPS))
#define GTA_TB_PRINT_DW    4096u            /* at most 512 lines of the log in the kernel log */
#define GTA_CMD_STATEFLAGS ((uint32_t)HMFV2_CMD_STATEFLAGS)
#define GTA_EXEC_MS        1000u
#define GTA_QUIET_MS       50u              /* after a command stock waits on nothing for: let a return value land, if the firmware writes one */

static volatile uint8_t *gs;
static uint32_t gs_next;
static struct { uint32_t kctl, kccb, rtn, fctl, fccb, sysdata, tbuf, tbdata; } gsh;

static void gs_w32(uint32_t off, uint32_t v) { *(volatile uint32_t *)(void *)(gs + (off - (uint32_t)GF_MAIN_HEAP_OFF)) = v; }
static uint32_t gs_r32(uint32_t off) { return *(volatile uint32_t *)(void *)(gs + (off - (uint32_t)GF_MAIN_HEAP_OFF)); }
static void gs_w64(uint32_t off, uint64_t v) { gs_w32(off, (uint32_t)v); gs_w32(off + 4, (uint32_t)(v >> 32)); }

static void
gs_zero(uint32_t off, uint32_t len)
{
	for (uint32_t i = 0; i < len; i += 4) {
		gs_w32(off + i, 0);
	}
}

/* Carve-out offset of a zeroed block */
static uint32_t
gs_alloc(uint32_t len)
{
	uint32_t off = gs_next;

	gs_next = (off + len + 0xfffu) & ~0xfffu;
	gs_zero(off, (len + 3u) & ~3u);
	return off;
}

static uint32_t
gs_ptr(uint32_t si, uint32_t len)
{
	uint32_t off = gs_alloc(len);

	gs_w32(si, GTA_VA_UNCACHED | off);
	return off;
}

/* Returns 0, or the main heap ran out: can't, by sizes, and checked */
static int
gta_shared_init(bool m2)
{
	static const uint32_t km[] = GF_ALIGN_KM;
	const uint32_t os = GTA_SH_OSINIT, si = GTA_SH_SYSINIT;
	uint32_t a, rc, fault;

	gs = gta_shared_map();
	if (!gs) {
		aoc_stop("cannot map the shared heap");
		return -1;
	}
	gs_next = (uint32_t)GF_MAIN_HEAP_OFF;
	gs_zero(GTA_SH_CONN, GF_SZ_RGXFWIF_CONNECTION_CTL);
	gs_zero(os, GF_SZ_RGXFWIF_OSINIT);
	gs_zero(si, GF_SZ_RGXFWIF_SYSINIT);
	/* OS data, in stock's order */
	gs_ptr(os + GF_OI_sRGXFWIfHWRInfoBufCtl, GF_SZ_RGXFWIF_HWRINFOBUF);
	gsh.kctl = gs_ptr(os + GF_OI_psKernelCCBCtl, GF_SZ_RGXFWIF_CCB_CTL);
	gsh.kccb = gs_ptr(os + GF_OI_psKernelCCB, (1u << GF_KCCB_LOG2) * GF_SZ_RGXFWIF_KCCB_CMD);
	gs_w32(gsh.kctl + GF_CCB_MASK, (1u << GF_KCCB_LOG2) - 1);
	gsh.rtn = gs_ptr(os + GF_OI_psKernelCCBRtnSlots, (1u << GF_KCCB_LOG2) * 4u);
	gsh.fctl = gs_ptr(os + GF_OI_psFirmwareCCBCtl, GF_SZ_RGXFWIF_CCB_CTL);
	gsh.fccb = gs_ptr(os + GF_OI_psFirmwareCCB, (1u << GF_FWCCB_LOG2) * GF_SZ_RGXFWIF_FWCCB_CMD);
	gs_w32(gsh.fctl + GF_CCB_MASK, (1u << GF_FWCCB_LOG2) - 1);
	gs_ptr(os + GF_OI_sFwOsData, GF_SZ_RGXFWIF_OSDATA);
	gs_w32(os + GF_OI_ui32HWRDebugDumpLimit, 1);
	gs_ptr(os + GF_OI_sGpuUtilFWCtl, GF_SZ_RGXFWIF_GPU_UTIL_FW);
	gs_ptr(os + GF_OI_sHwPerfRuntimeCfg, GF_SZ_RGXFWIF_RUNTIME_HWPERFCFG);
	gs_ptr(os + GF_OI_sHwPerfData, GF_SZ_RGXFWIF_HWPERFDATA);
	gs_ptr(os + GF_OI_sHWPerfCtl, GF_SZ_RGXFWIF_HWPERF_CTL);
	/* System data */
	fault = gs_alloc(0x1000);
	for (uint32_t i = 0; i < 0x1000; i += 4) {
		gs_w32(fault + i, 0xdeadbeefu);
	}
	gs_w64(si + GF_SI_sFaultPhysAddr, GTA_CARVEOUT_PA + fault);
	gs_w64(si + GF_SI_sPDSExecBase, GF_PDSCODE_BASE);
	gs_w64(si + GF_SI_sUSCExecBase, GF_USCCODE_BASE);
	gs_w64(si + GF_SI_sFBCDCStateTableBase, GF_FBCDC_BASE);
	gs_w64(si + GF_SI_sFBCDCLargeStateTableBase, GF_FBCDC_LARGE_BASE);
	gs_w64(si + GF_SI_sTextureHeapBase, GF_TEXTURE_BASE);
	gs_w64(si + GF_SI_sPDSIndirectHeapBase, GF_PDS_INDIRECT_BASE);
	gsh.tbuf = gs_ptr(si + GF_SI_sTraceBufCtl, GF_SZ_RGXFWIF_TRACEBUF);
	if (m2) {
		/* RGXSetupFwSysData then RGXTraceBufferInitOnDemandResources: log type, one buffer per firmware thread, its size. Written before START */
		gsh.tbdata = gs_ptr(gsh.tbuf + HMFV2_TB_BUFFER0, GTA_TB_DW * 4u);
		gs_w32(gsh.tbuf + HMFV2_TB_SIZE_DW, GTA_TB_DW);
		gs_w32(gsh.tbuf + HMFV2_TB_LOG_TYPE, GTA_LOG_M2);
	}
	gsh.sysdata = gs_ptr(si + GF_SI_sFwSysData, GF_SZ_RGXFWIF_SYSDATA);
	a = gs_ptr(si + GF_SI_sAlignChecks, (uint32_t)sizeof(km) + (GF_ALIGN_UM_MAX + 2u) * 4u);
	gs_w32(a, (uint32_t)(sizeof(km) / sizeof(km[0])));
	for (uint32_t i = 0; i < sizeof(km) / sizeof(km[0]); i++) {
		gs_w32(a + 4 + i * 4, km[i]);
	}
	rc = gs_ptr(si + GF_SI_sRuntimeCfg, GF_SZ_RGXFWIF_RUNTIME_CFG);
	gs_w32(rc + GF_RC_ui32ActivePMLatencyms, GTA_APM_MS);
	gs_w32(rc + GF_RC_bActivePMLatencyPersistant, 1);
	gs_w32(rc + GF_RC_ui32CoreClockSpeed, GTA_CORE_HZ);
	gs_w32(rc + GF_RC_ui32SOCClockSpeed, GTA_SOC_HZ);
	gs_w32(rc + GF_RC_ui32HCSDeadlineMS, (uint32_t)GF_HCS_MS);
	gs_w32(rc + GF_RC_ui32WdgPeriodUs, (uint32_t)GF_WDG_US);
	gs_w32(rc + GF_RC_ui32PowUnitsState, GTA_SPU_MASK);
	gs_w32(rc + GF_RC_ui32RACUnitsState, GTA_RAC_MASK);
	gs_w32(si + GF_SI_ui32InitialCoreClockSpeed, GTA_CORE_HZ);
	gs_w32(si + GF_SI_ui32InitialSOCClockSpeed, GTA_SOC_HZ);
	gs_w32(si + GF_SI_ui32InitialActivePMLatencyms, GTA_APM_MS);
	gs_w32(si + GF_SI_ui32MarkerVal, 1);
	gs_w32(GTA_SH_CONN + GF_CC_OS, GTA_OS_READY);
	aoc_barrier();
	AOC_LOG("shared data written: main heap to +0x%x\n", gs_next);
	if (gs_next > (uint32_t)GF_CONFIG_HEAP_OFF) {
		aoc_stop("shared data overran the main heap");
		return -1;
	}
	return 0;
}

static bool
gs_wait_nonzero(uint32_t off, uint32_t ms)
{
	const uint64_t end = aoc_now_ms() + ms;

	while (gs_r32(off) == 0) {
		if (aoc_now_ms() >= end) {
			return false;
		}
		aoc_sleep_ms(1);
	}
	return true;
}

static void
gta_fw_state(void)
{
	AOC_LOG("fw: started %u ts 0x%x conn fw %u os %u; kccb w %u r %u; fwccb w %u r %u; sysdata 0x%x 0x%x; comp bvnc 0x%x 0x%x\n",
	    gs_r32(GTA_SH_SYSINIT + GF_SI_bFirmwareStarted), gs_r32(GTA_SH_SYSINIT + GF_SI_ui32FirmwareStartedTimeStamp),
	    gs_r32(GTA_SH_CONN + GF_CC_FW), gs_r32(GTA_SH_CONN + GF_CC_OS),
	    gs_r32(gsh.kctl + GF_CCB_W), gs_r32(gsh.kctl + GF_CCB_R), gs_r32(gsh.fctl + GF_CCB_W), gs_r32(gsh.fctl + GF_CCB_R),
	    gs_r32(gsh.sysdata), gs_r32(gsh.sysdata + 4),
	    gs_r32(GTA_SH_OSINIT + GF_OI_sRGXCompChecks), gs_r32(GTA_SH_OSINIT + GF_OI_sRGXCompChecks + 4));
}

#if defined(BLAZER_GPU_FW_DIAGNOSTIC) && BLAZER_GPU_FW_DIAGNOSTIC
/* Original MIT diagnostic hook. Reads only the existing uncached shared map;
 * no FWCCB index, ack, power, clock, SMC or firmware content is changed. */
static int
gta_diag_read(void *ctx, uint32_t off, uint32_t *out)
{
	(void)ctx;
	const uint32_t bytes = (uint32_t)(GF_RAW_SIZE - GF_MAIN_HEAP_OFF);
	if (!gs || (off & 3u) || off > bytes - 4u) return -1;
	aoc_barrier();
	*out = gs_r32((uint32_t)GF_MAIN_HEAP_OFF + off);
	return 0;
}
static void
gta_diag_snapshot(const char *reason)
{
	if (gta_diag_wanted != 1 || !gs) return;
	struct hmfd_snapshot snapshot;
	const uint32_t base = (uint32_t)GF_MAIN_HEAP_OFF;
	const struct hmfd_reader reader = { NULL, gta_diag_read };
	const struct hmfd_layout layout = {
		(uint32_t)GF_RAW_SIZE - base, gsh.fctl - base, gsh.fccb - base, 1u << GF_FWCCB_LOG2
	};
	(void)hmfd_capture(&reader, &layout, &snapshot);
	hmfd_dump(&snapshot, reason);
	const struct { const char *name; uint32_t off; } meta[] = {
		{"health.flags", gsh.kccb + HMFV_CMD_FLAGS},
		{"health.return0", gsh.rtn},
		{"sys.pow", gsh.sysdata + HMFV_SYS_POW_STATE},
		{"sys.fw_faults", gsh.sysdata + HMFV_SYS_FW_FAULTS},
		{"sys.hwr_flags", gsh.sysdata + HMFV_SYS_HWR_FLAGS},
		{"comp.updated", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_UPDATED},
		{"comp.hw_layout", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_HW_LAYOUT},
		{"comp.hw_bvnc_lo", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_HW_BVNC},
		{"comp.hw_bvnc_hi", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_HW_BVNC + 4},
		{"comp.fw_layout", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_FW_LAYOUT},
		{"comp.fw_bvnc_lo", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_FW_BVNC},
		{"comp.fw_bvnc_hi", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_FW_BVNC + 4},
		{"comp.ddk_version", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_DDK_VERSION},
		{"comp.ddk_build", GTA_SH_OSINIT + GF_OI_sRGXCompChecks + HMFV_COMP_DDK_BUILD},
	};
	for (unsigned i = 0; i < sizeof(meta)/sizeof(meta[0]); i++) {
		uint32_t word;
		if (meta[i].off < base || gta_diag_read(NULL, meta[i].off - base, &word)) {
			printf("HK GPUTA DIAG: %s unavailable (bounds/read)\n", meta[i].name);
		} else printf("HK GPUTA DIAG: %s=0x%x\n", meta[i].name, word);
	}
	printf("HK GPUTA DIAG: layout=lga26.1 ABI41; comp fields valid only if updated; diagnostic does not establish readiness\n");
}
#else
#define gta_diag_snapshot(reason) ((void)0)
#endif

/* One command on a fresh ring. Consumption is not execution: require the
 * return slot CMD_EXECUTED bit as RGXWaitForKCCBSlotUpdate does. */
static int
gta_health(vm_offset_t rgx)
{
	const uint64_t end = aoc_now_ms() + GTA_HEALTH_MS;

	/* This bounded rung owns slot zero only. Never overwrite a live ring. */
	if (gs_r32(gsh.kctl + GF_CCB_W) != 0 || gs_r32(gsh.kctl + GF_CCB_R) != 0) {
		aoc_stop("KCCB not fresh before health check");
		return GTA_STOPPED;
	}
	gs_w32(gsh.rtn, 0); /* RGXFWIF_KCCB_RTN_SLOT_NO_RESPONSE */
	aoc_barrier();
	gs_w32(gsh.kccb + GF_KC_TYPE, (uint32_t)GF_CMD_HEALTH);
	aoc_barrier();
	gs_w32(gsh.kctl + GF_CCB_W, 1);
	aoc_barrier();
	gta_mts_kick(rgx, GTA_KICK_GP);
	while (gs_r32(gsh.kctl + GF_CCB_R) != 1) {
		if (aoc_now_ms() >= end) {
			gta_fw_state();
			gta_diag_snapshot("health-read-timeout");
			aoc_stop("no KCCB read in 1 s");
			return GTA_STOPPED;
		}
		aoc_sleep_ms(1);
	}
	/* Same deadline bounds consumption and completion together. Shared heap
	 * uses the existing uncached mapping; barriers order device observations. */
	while (!(gs_r32(gsh.rtn) & 1u)) {
		if (aoc_now_ms() >= end) {
			gta_fw_state();
			gta_diag_snapshot("health-execution-timeout");
			aoc_stop("no KCCB execution in 1 s");
			return GTA_STOPPED;
		}
		aoc_sleep_ms(1);
	}
	aoc_barrier();
	AOC_LOG("health return slot 0x%x\n", gs_r32(gsh.rtn));
	/* HEALTH_CHECK has no cleanup result. Refuse every extra status bit. */
	if (gs_r32(gsh.rtn) != 1u) {
		gta_diag_snapshot("health-return-status");
		aoc_stop("KCCB health execution status unexpected");
		return GTA_STOPPED;
	}
	gta_fw_state();
	if (gs_r32(gsh.fctl + GF_CCB_W) != gs_r32(gsh.fctl + GF_CCB_R)) {
		gta_diag_snapshot("health-fwccb-pending");
		AOC_LOG("fwccb entry 0: 0x%x 0x%x 0x%x 0x%x\n", gs_r32(gsh.fccb), gs_r32(gsh.fccb + 4), gs_r32(gsh.fccb + 8), gs_r32(gsh.fccb + 12));
		aoc_stop("FWCCB not empty after the health check");
		return GTA_STOPPED;
	}
	return GTA_PASS;
}

/* Rung 6 (M2). Reads of our own uncached shared map only, except gta_kccb's two stock-shaped commands and the survey's REE register reads */
static const char *const gta_os_state_name[8] = { "OFFLINE", "READY", "ACTIVE", "GRACEFUL_OFFLOAD", "FORCED_OFFLOAD", "COOLDOWN", "6?", "7?" };

/* A firmware-written C string, read as words (device memory), printable ASCII only, always terminated */
static void
gta_m2_str(uint32_t off, uint32_t max, char *out)
{
	uint32_t n = 0;

	for (uint32_t i = 0; i < max; i += 4) {
		uint32_t w = gs_r32(off + i);

		for (uint32_t b = 0; b < 4 && i + b < max; b++) {
			char c = (char)(w >> (8 * b));

			if (c == 0) {
				out[n] = 0;
				return;
			}
			out[n++] = (c >= 32 && c < 127) ? c : '?';
		}
	}
	out[n] = 0;
}

static void
gta_m2_filebuf(const char *when, const char *what, unsigned idx, uint32_t base)
{
	char path[HMFV2_ASSERT_BYTES + 1], info[HMFV2_ASSERT_BYTES + 1];
	const uint32_t line = gs_r32(base + 2u * (uint32_t)HMFV2_ASSERT_BYTES);   /* ui32LineNum: TB_ASSERT0_LINE - TB_ASSERT0_PATH */

	gta_m2_str(base, HMFV2_ASSERT_BYTES, path);
	gta_m2_str(base + HMFV2_ASSERT_BYTES, HMFV2_ASSERT_BYTES, info);
	if (line == 0 && path[0] == 0 && info[0] == 0) {
		AOC_LOG("M2 %s: %s%u empty\n", when, what, idx);
		return;
	}
	AOC_LOG("M2 %s: %s%u line %u path \"%s\" info \"%s\"\n", when, what, idx, line, path, info);
}

/* The firmware's view of us, at one moment. Never acks, consumes or writes anything */
static void
gta_m2_state(const char *when)
{
	const uint32_t sd = gsh.sysdata, tb = gsh.tbuf;
	uint32_t os[8], faults;

	aoc_barrier();
	AOC_LOG("M2 %s: started %u ts 0x%x; kccb w %u r %u rtn0 0x%x rtn1 0x%x; fwccb w %u r %u; conn fw %u os %u\n", when,
	    gs_r32(GTA_SH_SYSINIT + GF_SI_bFirmwareStarted), gs_r32(GTA_SH_SYSINIT + GF_SI_ui32FirmwareStartedTimeStamp),
	    gs_r32(gsh.kctl + GF_CCB_W), gs_r32(gsh.kctl + GF_CCB_R), gs_r32(gsh.rtn), gs_r32(gsh.rtn + 4),
	    gs_r32(gsh.fctl + GF_CCB_W), gs_r32(gsh.fctl + GF_CCB_R), gs_r32(GTA_SH_CONN + GF_CC_FW), gs_r32(GTA_SH_CONN + GF_CC_OS));
	for (unsigned i = 0; i < 8; i++) {
		os[i] = gs_r32(sd + HMFV2_SYS_OS_RUNTIME_FLAGS0 + 4u * i);
	}
	AOC_LOG("M2 %s: sys cfg 0x%x ext 0x%x pow %u; os0 rt 0x%x state %s fl_ok %u; os1-7 rt 0x%x 0x%x 0x%x 0x%x 0x%x 0x%x 0x%x\n", when,
	    gs_r32(sd + HMFV2_SYS_CONFIG_FLAGS), gs_r32(sd + HMFV2_SYS_CONFIG_FLAGS_EXT), gs_r32(sd + HMFV2_SYS_POW_STATE),
	    os[0], gta_os_state_name[os[0] & (uint32_t)HMFV2_OS_STATE_MASK], (os[0] >> 3) & 1u, os[1], os[2], os[3], os[4], os[5], os[6], os[7]);
	faults = gs_r32(sd + HMFV2_SYS_FW_FAULTS);
	AOC_LOG("M2 %s: sys fw_faults %u; cr poll addr 0x%x mask 0x%x count %u; hwr 0x%x; sysflags 0x%x; ts0 %u\n", when, faults,
	    gs_r32(sd + HMFV2_SYS_CR_POLL_ADDR0), gs_r32(sd + HMFV2_SYS_CR_POLL_MASK0), gs_r32(sd + HMFV2_SYS_CR_POLL_COUNT0),
	    gs_r32(sd + HMFV2_SYS_HWR_FLAGS), gs_r32(sd + HMFV2_SYS_FLAGS), gs_r32(sd + HMFV2_SYS_TS_MIRROR0));
	for (uint32_t i = 0; i < faults && i < (uint32_t)HMFV2_FAULTINFO_MAX; i++) {
		const uint32_t fi = sd + HMFV2_SYS_FAULT_INFO0 + i * (HMFV2_SYS_FAULT_INFO1 - HMFV2_SYS_FAULT_INFO0);

		AOC_LOG("M2 %s: fault%u data 0x%08x%08x\n", when, i, gs_r32(fi + (HMFV2_SYS_FAULT_INFO0_DATA - HMFV2_SYS_FAULT_INFO0) + 4),
		    gs_r32(fi + (HMFV2_SYS_FAULT_INFO0_DATA - HMFV2_SYS_FAULT_INFO0)));
		gta_m2_filebuf(when, "fault", i, fi + (HMFV2_SYS_FAULT_INFO0_PATH - HMFV2_SYS_FAULT_INFO0));
	}
	AOC_LOG("M2 %s: trace type 0x%x size %u ptr %u wrap %u flags 0x%x buf 0x%x\n", when, gs_r32(tb + HMFV2_TB_LOG_TYPE), gs_r32(tb + HMFV2_TB_SIZE_DW),
	    gs_r32(tb + HMFV2_TB_TRACE_POINTER0), gs_r32(tb + HMFV2_TB_WRAP0), gs_r32(tb + HMFV2_TB_FLAGS), gs_r32(tb + HMFV2_TB_BUFFER0));
	gta_m2_filebuf(when, "assert", 0, tb + HMFV2_TB_ASSERT0_PATH);
	gta_diag_snapshot(when);
}

/* The firmware's own log, raw: 8 words a line, offset in words. Its format strings are rgx_fwif_sf.h's, decoded on the host (m2/tools/fwlog_decode.py) */
static void
gta_m2_fwlog(void)
{
	const uint32_t ptr = gs_r32(gsh.tbuf + HMFV2_TB_TRACE_POINTER0), wrap = gs_r32(gsh.tbuf + HMFV2_TB_WRAP0);
	uint32_t start, count;

	if (gsh.tbdata == 0 || ptr > GTA_TB_DW) {
		AOC_LOG("M2 fwlog: none (ptr %u wrap %u)\n", ptr, wrap);
		return;
	}
	count = wrap ? GTA_TB_DW : ptr;
	if (count > GTA_TB_PRINT_DW) {
		count = GTA_TB_PRINT_DW;
	}
	start = (ptr + GTA_TB_DW - count) % GTA_TB_DW;
	AOC_LOG("M2 fwlog: ptr %u wrap %u, %u words from %u\n", ptr, wrap, count, start);
	for (uint32_t i = 0; i < count; i += 8) {
		uint32_t w[8] = { 0, 0, 0, 0, 0, 0, 0, 0 };

		for (uint32_t j = 0; j < 8 && i + j < count; j++) {
			w[j] = gs_r32(gsh.tbdata + 4u * ((start + i + j) % GTA_TB_DW));
		}
		AOC_LOG("M2 TB %04x: %08x %08x %08x %08x %08x %08x %08x %08x\n", (start + i) % GTA_TB_DW, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7]);
	}
	AOC_LOG("M2 fwlog: end\n");
}

enum { GTA_K_EXECUTED = 0, GTA_K_CONSUMED = 1, GTA_K_UNREAD = 2, GTA_K_NOT_EXECUTED = 3, GTA_K_BAD = 4 };

/* One command in the next slot of our own fresh ring, as RGXSendCommandRaw writes it: return slot reset first when the caller will wait on it, the
 * command (type, zero flags, zero data), write offset, MTS kick for DM GP. Consumption within 1 s, then CMD_EXECUTED within 1 s if stock waits on it */
static int
gta_kccb(vm_offset_t rgx, uint32_t slot, uint32_t type, bool wait_rtn, const char *name)
{
	const uint32_t cmd = gsh.kccb + slot * GF_SZ_RGXFWIF_KCCB_CMD;
	uint64_t t0, end, t_read;
	uint32_t rtn;

	if (gs_r32(gsh.kctl + GF_CCB_W) != slot || gs_r32(gsh.kctl + GF_CCB_R) != slot) {
		AOC_LOG("M2 %s: ring not at slot %u (w %u r %u)\n", name, slot, gs_r32(gsh.kctl + GF_CCB_W), gs_r32(gsh.kctl + GF_CCB_R));
		return GTA_K_BAD;
	}
	gs_w32(gsh.rtn + 4u * slot, 0); /* RGXFWIF_KCCB_RTN_SLOT_NO_RESPONSE */
	aoc_barrier();
	gs_zero(cmd, GF_SZ_RGXFWIF_KCCB_CMD);
	gs_w32(cmd + GF_KC_TYPE, type);
	aoc_barrier();
	gs_w32(gsh.kctl + GF_CCB_W, slot + 1u);
	aoc_barrier();
	t0 = aoc_now_ms();
	gta_mts_kick(rgx, GTA_KICK_GP);
	end = t0 + GTA_HEALTH_MS;
	while (gs_r32(gsh.kctl + GF_CCB_R) != slot + 1u) {
		if (aoc_now_ms() >= end) {
			AOC_LOG("M2 %s: slot %u NOT READ in %u ms (r %u)\n", name, slot, GTA_HEALTH_MS, gs_r32(gsh.kctl + GF_CCB_R));
			return GTA_K_UNREAD;
		}
		aoc_sleep_ms(1);
	}
	t_read = aoc_now_ms();
	end = t_read + (wait_rtn ? GTA_EXEC_MS : GTA_QUIET_MS);
	while (!((rtn = gs_r32(gsh.rtn + 4u * slot)) & (uint32_t)HMFV2_RTN_EXECUTED) && aoc_now_ms() < end) {
		aoc_sleep_ms(1);
	}
	aoc_barrier();
	rtn = gs_r32(gsh.rtn + 4u * slot);
	AOC_LOG("M2 %s: slot %u read in %llu ms; return 0x%x after %llu ms more (%s)\n", name, slot, t_read - t0, rtn, aoc_now_ms() - t_read,
	    wait_rtn ? "stock waits on it" : "stock waits on nothing");
	if (rtn & (uint32_t)HMFV2_RTN_EXECUTED) {
		return GTA_K_EXECUTED;
	}
	return wait_rtn ? GTA_K_NOT_EXECUTED : GTA_K_CONSUMED;
}

static int
gta_m2(vm_offset_t rgx)
{
	int h, e = GTA_K_BAD;
	bool sent = false;

	AOC_LOG("M2: stock order: started, HEALTH_CHECK (consumption), STATEFLAGS_CTRL (execution); log type 0x%x, %u words\n", GTA_LOG_M2, GTA_TB_DW);
	gta_m2_state("boot");
	h = gta_kccb(rgx, 0, (uint32_t)GF_CMD_HEALTH, false, "HEALTH_CHECK");
	gta_m2_state("after-health");
	if (h != GTA_K_UNREAD && h != GTA_K_BAD) {
		/* Never a second command behind one the firmware has not read */
		sent = true;
		e = gta_kccb(rgx, 1, GTA_CMD_STATEFLAGS, true, "STATEFLAGS_CTRL");
		gta_m2_state(e == GTA_K_EXECUTED ? "after-stateflags" : "stateflags-fail");
	}
	gta_m2_fwlog();
	gta_survey();
	if (e == GTA_K_EXECUTED) {
		AOC_LOG("M2 HEALTH PASS: STATEFLAGS_CTRL executed (CMD_EXECUTED), HEALTH_CHECK %s\n", h == GTA_K_EXECUTED ? "executed" : "consumed");
		return GTA_PASS;
	}
	AOC_LOG("M2 HEALTH FAIL: HEALTH_CHECK %s, STATEFLAGS_CTRL %s\n",
	    h == GTA_K_UNREAD ? "unread" : h == GTA_K_BAD ? "ring not fresh" : h == GTA_K_EXECUTED ? "executed" : "consumed",
	    !sent ? "not sent" : e == GTA_K_UNREAD ? "unread" : e == GTA_K_NOT_EXECUTED ? "read, not executed" : "ring not fresh");
	aoc_stop(h == GTA_K_UNREAD ? "HEALTH_CHECK not read in 1 s" : h == GTA_K_BAD ? "KCCB not fresh" :
	    e == GTA_K_NOT_EXECUTED ? "STATEFLAGS_CTRL read, not executed in 1 s" : e == GTA_K_UNREAD ? "STATEFLAGS_CTRL not read in 1 s" : "KCCB not fresh");
	return GTA_STOPPED;
}

static int
gta_rung4(const uint8_t *file, uint32_t len, unsigned rung)
{
	const bool health = rung == 5;
	uint64_t r[8] = { GTA_SMC_GPU, GTA_SMC_START, 0, 0, 0, 0, 0, 0 };
	struct gta_fw fw;
	vm_offset_t rgx = 0;
	const char *bad;
	int rc;

	if (aoc_identify()) {
		return GTA_STOPPED;
	}
	bad = gta_fw_check(file, len, &fw);
	if (bad) {
		AOC_LOG("firmware file refused: %s\n", bad);
		aoc_stop("firmware file refused");
		return GTA_STOPPED;
	}
	if (aoc_virtio_up()) {
		return GTA_STOPPED;
	}
	gta_log_add();
	if (aoc_connect()) {
		return GTA_STOPPED;
	}
	rc = gta_send_firmware(&fw);
	if (rc != GTA_PASS) {
		(void)aoc_nop(0, 0, 0);
		gta_log_dump();
		if (rc == GTA_ANSWERED_ERROR) {
			AOC_LOG("REFUSED result %u: nothing started\n", gta_result);
		}
		return rc;
	}
	if (gta_shared_init(rung == 6)) {
		return GTA_STOPPED;
	}
	if (gta_power_on(&rgx) != 0) {
		aoc_stop("GPU did not power on");
		return GTA_STOPPED;
	}
	if (aoc_smc(r)) {
		return GTA_STOPPED;
	}
	AOC_LOG("SMC START -> 0x%llx\n", r[0]);
	if ((uint32_t)r[0] != 0) {
		(void)aoc_nop(0, 0, 0);
		gta_log_dump();
		aoc_stop("SMC START refused");
		return GTA_STOPPED;
	}
	rc = GTA_PASS;
	if (!gs_wait_nonzero(GTA_SH_SYSINIT + GF_SI_bFirmwareStarted, GTA_START_MS)) {
		aoc_stop("bFirmwareStarted not set in 1 s");
		rc = GTA_STOPPED;
	} else {
		const uint64_t end = aoc_now_ms() + GTA_ACTIVE_MS;

		/* rgxpower.c: the kernel waits for this, and may have to kick once for it. Without a kick here: =5 kicks.
		 * =6 does not wait: with RGX_NUM_DRIVERS_SUPPORTED 1 (lga production) KM_GET_FW_CONNECTION is the constant ACTIVE, stock never reads the field */
		if (rung == 6) {
			rc = gta_m2(rgx);
		}
		while (rung == 4 && gs_r32(GTA_SH_CONN + GF_CC_FW) != GTA_FW_ACTIVE && aoc_now_ms() < end) {
			aoc_sleep_ms(1);
		}
		if (rung == 4 && gs_r32(GTA_SH_CONN + GF_CC_FW) != GTA_FW_ACTIVE) {
			AOC_LOG("firmware started, connection not active in 3 s\n");
		}
		if (health) {
			rc = gta_health(rgx);
		}
	}
	gta_fw_state();
	(void)aoc_nop(0, 0, 0);
	gta_log_dump();
	if (rc == GTA_PASS) {
		AOC_LOG("rung %u PASS, firmware running (smcs %u)\n", rung, aoc.smcs);
	}
	return rc;
}

static int
gta_rung2(const uint8_t *file, uint32_t len)
{
	struct gta_fw fw;
	const char *bad;
	int rc;

	if (aoc_identify()) {
		return GTA_STOPPED;
	}
	bad = gta_fw_check(file, len, &fw);
	if (bad) {
		AOC_LOG("firmware file refused: %s\n", bad);
		aoc_stop("firmware file refused");
		return GTA_STOPPED;
	}
	AOC_LOG("firmware file ok: %u bytes, ABI %u, 26.1\n", len, GTA_FW_ABI);
	if (aoc_virtio_up()) {
		return GTA_STOPPED;
	}
	gta_log_add();
	if (aoc_connect()) {
		return GTA_STOPPED;
	}
	rc = gta_send_firmware(&fw);
	(void)aoc_nop(0, 0, 0);
	gta_log_dump();
	if (rc == GTA_PASS) {
		AOC_LOG("rung 2 PASS, TA took the image (smcs %u nops %u)\n", aoc.smcs, aoc.nops);
	} else if (rc == GTA_ANSWERED_ERROR) {
		AOC_LOG("rung 2 REFUSED, result %u (smcs %u nops %u)\n", gta_result, aoc.smcs, aoc.nops);
	}
	return rc;
}

/* Trusty's own log, as trusty-log.c registers it: a ring shared with the secure side. Read here to get the TA's reason in its own words. Failing to get it is a line, not a STOP.
 * Stock only reads it after add; nothing about the GPU changes. Never removed, as every shared page here. */
#define GTA_LOG_BYTES      (3u * AOC_PAGE)
#define GTA_LOG_HDR        12u      /* struct log_rb: alloc, put, sz */
#define GTA_LOG_API        1u       /* TRUSTY_LOG_API_VERSION */

static uint8_t *gta_log;

static void
gta_log_add(void)
{
	uint64_t handle = 0;
	int32_t ret = aoc_std(0x33000000u, GTA_LOG_API, 0, 0);

	if (ret != (int32_t)GTA_LOG_API) {
		AOC_LOG("TA log: version %d, no log\n", ret);
		return;
	}
	gta_log = aoc_page(GTA_LOG_BYTES);
	if (!gta_log || aoc_share(gta_log, GTA_LOG_BYTES, AOC_FFA_RW, &handle)) {
		gta_log = NULL;
		return;
	}
	ret = aoc_std(0x33000001u, (uint32_t)handle, (uint32_t)(handle >> 32), GTA_LOG_BYTES);
	AOC_LOG("TA log: add -> %d\n", ret);
	if (ret < 0) {
		gta_log = NULL;
	}
}

static void
gta_log_dump(void)
{
	char line[200];
	uint32_t put, alloc, sz, get, n = 0;

	/* Reads shared memory only, no call: a STOP or a secure panic is when this matters most */
	if (!gta_log) {
		return;
	}
	aoc_dmb();
	put = *(volatile uint32_t *)(void *)(gta_log + 4);
	aoc_dmb();
	alloc = *(volatile uint32_t *)(void *)gta_log;
	sz = *(volatile uint32_t *)(void *)(gta_log + 8);
	AOC_LOG("TA log: alloc %u put %u sz %u\n", alloc, put, sz);
	if (sz == 0 || (sz & (sz - 1)) || sz > GTA_LOG_BYTES - GTA_LOG_HDR || put - (alloc > sz ? alloc - sz : 0) > sz) {
		return;
	}
	get = alloc > sz ? alloc - sz : 0;
	for (; get != put; get++) {
		char c = (char)*(volatile uint8_t *)(gta_log + GTA_LOG_HDR + (get & (sz - 1)));

		if (c == '\n' || n == sizeof(line) - 1) {
			line[n] = 0;
			AOC_LOG("TA| %s\n", line);
			n = 0;
			if (c == '\n') {
				continue;
			}
		}
		line[n++] = (c >= 32 && c < 127) ? c : '?';
	}
	if (n) {
		line[n] = 0;
		AOC_LOG("TA| %s\n", line);
	}
}

static int
gta_rung1(bool with_log)
{
	int rc;

	if (aoc_identify() || aoc_virtio_up()) {
		return GTA_STOPPED;
	}
	if (with_log) {
		gta_log_add();
	}
	if (aoc_connect()) {
		return GTA_STOPPED;
	}
	rc = gta_ping();
	if (rc == GTA_PASS) {
		AOC_LOG("rung 1 PASS (smcs %u nops %u)\n", aoc.smcs, aoc.nops);
	} else if (rc == GTA_ANSWERED_ERROR) {
		AOC_LOG("rung 1 ANSWERED, PING refused (smcs %u nops %u)\n", aoc.smcs, aoc.nops);
	}
	if (with_log) {
		(void)aoc_nop(0, 0, 0);
		gta_log_dump();
	}
	return rc;
}

#ifndef BLAZER_AOC_HOSTTEST
static unsigned gta_rung_wanted;

__dead2 static void
gta_thread(void *arg __unused, wait_result_t wr __unused)
{
	const unsigned rung = gta_rung_wanted;
	int rc = rung >= 4 ? gta_rung4(blazer_gpu_fw + 16, (uint32_t)*(const uint64_t *)(const void *)blazer_gpu_fw, rung) :
	    rung == 2 ? gta_rung2(blazer_gpu_fw + 16, (uint32_t)*(const uint64_t *)(const void *)blazer_gpu_fw) : gta_rung1(rung == 3);

	IOSleep(200);
	if (rc == GTA_PASS) {
		panic("HK GPUTA: rung %u PASS, boot ended on purpose", rung);
	}
	if (rc == GTA_ANSWERED_ERROR) {
		panic("HK GPUTA: rung %u ANSWERED, boot ended on purpose", rung);
	}
	panic("HK GPUTA: rung %u STOP: %s", rung, aoc_stop_reason ? aoc_stop_reason : "unknown");
}

void blazer_gpu_tipc_start(void);

void
blazer_gpu_tipc_start(void)
{
	unsigned on = 0, cpus = 0, other = 0;
	thread_t thread;

	if (!PE_parse_boot_argn("blazer_gpu_tipc", &on, sizeof(on)) || on < 1 || on > 6) {
		return;
	}
	gta_rung_wanted = on;
#if defined(BLAZER_GPU_FW_DIAGNOSTIC) && BLAZER_GPU_FW_DIAGNOSTIC
	if (on == 5) {
		(void)PE_parse_boot_argn("blazer_gpu_tipc_diag", &gta_diag_wanted, sizeof(gta_diag_wanted));
	}
	if (on == 6) {
		gta_diag_wanted = 1;    /* M2 always captures the FWCCB, read-only */
	}
#endif
	if (!PE_parse_boot_argn("cpus", &cpus, sizeof(cpus)) || cpus != 1) {
		printf("HK GPUTA: refused, needs cpus=1\n");
		return;
	}
	if (PE_parse_boot_argn("blazer_aoc", &other, sizeof(other)) || PE_parse_boot_argn("blazer_gpu", &other, sizeof(other))) {
		printf("HK GPUTA: refused, one Trusty client and one new variable per boot\n");
		return;
	}
	if (kernel_thread_start(gta_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
		printf("HK GPUTA: rung %u start\n", on);
	}
}
#endif /* !BLAZER_AOC_HOSTTEST */
#endif /* BLAZER */
