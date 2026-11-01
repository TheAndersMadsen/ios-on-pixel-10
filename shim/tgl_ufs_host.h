/* SPDX-License-Identifier: MIT
 * One bounded pass from a working LINK to the GPT and the first blocks of userdata_exp.ai. Ran on the phone as
 * research/ufs-read-r2 (attempt 20261101-185202), same frames and record format; decode_read.py reads the record.
 * Runs: post-change DME, list install, NOP OUT, fDeviceInit, TUR, REPORT LUNS, then with TGL_UFS_READ per LU TUR,
 * READ CAPACITY(10), READ(10) of the GPT; READ(10) of the target's first blocks and samples; list stop.
 * Storage commands are READ only, one block per doorbell, at most TGL_UFSH_MAX_READ_BLOCKS in the boot.
 * Issues no WRITE, UNMAP, FORMAT, SYNCHRONIZE CACHE, START STOP, or any query write but fDeviceInit: the wire gate
 * in tgl_ufs_host.c refuses them before the doorbell, and nothing composes them. */
#ifndef TGL_UFS_HOST_H
#define TGL_UFS_HOST_H
#include <stddef.h>
#include <stdint.h>

/* 0: stop after REPORT LUNS, no storage command. */
#ifndef TGL_UFS_READ
#define TGL_UFS_READ 1
#endif
/* ufs-postlink-r1 stopped here: the phone answers TUR with response=1 and CHECK CONDITION. Linux decides from the
 * SCSI status alone (ufshcd.c:5378-5384). 1: same, byte 6 stays in the record. 0: nonzero response is fatal. */
#ifndef TGL_UFS_SCSI_STATUS_ONLY
#define TGL_UFS_SCSI_STATUS_ONLY 1
#endif

#define TGL_UFSH_ARENA_BYTES 0x4000u
#define TGL_UFSH_ARENA_ALIGN 0x4000u
#define TGL_UFSH_RECORD_BYTES 0x2000u
#define TGL_UFSH_RECORD_HEADER 64u
#define TGL_UFSH_MAGIC UINT64_C(0x0031524452534655) /* "UFSRDR1\0" */
#define TGL_UFSH_VERSION 2u
#define TGL_UFSH_BLOCK_BYTES 4096u
#define TGL_UFSH_MAX_READ_BLOCKS 32u /* 128 KiB in the whole boot, enforced at the doorbell */
#define TGL_UFSH_LU_ENTRY_BLOCKS 16u /* 512 GPT entries per LU */
#define TGL_UFSH_TARGET_BLOCKS 4u    /* first blocks of the partition */
#define TGL_UFSH_MANIFEST_BLOCK 604671u /* UFSSTG1 block of the staged region, build-staging-image.py */
#define TGL_UFSH_SAMPLE_BLOCKS 7u /* partition-relative, TGL_UFSH_SAMPLE_LBAS: same blocks as ufs-read-r2, compared by XNU's test */
#define TGL_UFSH_GPT_READ_BLOCKS (TGL_UFSH_MAX_READ_BLOCKS - TGL_UFSH_TARGET_BLOCKS - 1u - TGL_UFSH_SAMPLE_BLOCKS) /* target's share is reserved */
#define TGL_UFSH_ARENA_MIN UINT64_C(0x80000000) /* ufs-dma-r1: bank 0, proven region */
#define TGL_UFSH_ARENA_END UINT64_C(0x8af00000) /* first bank-0 reservation */
#define TGL_UFSH_MAX_BUDGET_US UINT64_C(20000000) /* same bound as W1, below the 29 s WDT floor */

enum tgl_ufsh_rc {
    TGL_UFSH_OK = 0, TGL_UFSH_OFF = 1,
    TGL_UFSH_E_ARG = -1, TGL_UFSH_E_ONCE = -2, TGL_UFSH_E_NO_DEVICE = -3, TGL_UFSH_E_STATE = -4,
    TGL_UFSH_E_SMMU = -5, TGL_UFSH_E_PORT = -6, TGL_UFSH_E_BUDGET = -7, TGL_UFSH_E_UIC = -8,
    TGL_UFSH_E_NOT_READY = -9, TGL_UFSH_E_TIMEOUT = -10, TGL_UFSH_E_FATAL = -11, TGL_UFSH_E_OCS = -12,
    TGL_UFSH_E_PROTOCOL = -13, TGL_UFSH_E_QUERY = -14, TGL_UFSH_E_INIT = -15, TGL_UFSH_E_SCSI = -16,
    TGL_UFSH_E_LUNS = -17, TGL_UFSH_E_DENIED = -18, TGL_UFSH_E_STOP = -19, TGL_UFSH_E_FAULT = -20,
    TGL_UFSH_E_CPU = -21, TGL_UFSH_E_NOT_FOUND = -22, TGL_UFSH_E_NODATA = -23, TGL_UFSH_E_GUARD = -24,
    TGL_UFSH_E_CAP = -25, TGL_UFSH_E_GPT = -26
};
enum tgl_ufsh_phase {
    TGL_UFSH_P_NONE, TGL_UFSH_P_PREFLIGHT, TGL_UFSH_P_POST_CHANGE, TGL_UFSH_P_LISTS, TGL_UFSH_P_NOP,
    TGL_UFSH_P_SET_INIT, TGL_UFSH_P_POLL_INIT, TGL_UFSH_P_TUR, TGL_UFSH_P_REPORT_LUNS, TGL_UFSH_P_UNIT,
    TGL_UFSH_P_STOP, TGL_UFSH_P_DONE, TGL_UFSH_P_LU_TUR, TGL_UFSH_P_READ_CAP, TGL_UFSH_P_GPT, TGL_UFSH_P_TARGET
};
enum tgl_ufsh_entry { TGL_UFSH_T_PRE = 1, TGL_UFSH_T_UIC = 2, TGL_UFSH_T_CMD = 3, TGL_UFSH_T_DATA = 4,
    TGL_UFSH_T_END = 5, TGL_UFSH_T_GATE = 6, TGL_UFSH_T_READ = 7, TGL_UFSH_T_LU = 8, TGL_UFSH_T_PART = 9, TGL_UFSH_T_HDR = 10 };

/* All ports return 0 only on completion. The engine never touches MMIO directly. */
struct tgl_ufsh_ports {
    void *ctx;
    int (*hc_rd)(void *, uint32_t off, uint32_t *);
    int (*hc_wr)(void *, uint32_t off, uint32_t);
    int (*smmu_rd)(void *, uint32_t off, uint32_t *);
    int (*now_us)(void *, uint64_t *);
    int (*delay_us)(void *, uint32_t min_us, uint32_t max_us);
    /* DSB; DC CIVAC over the whole arena; DSB, in BOTH directions: UFS is treated as non-coherent.
     * for_device=1 before the doorbell, for_device=0 after it reads 0. */
    int (*sync)(void *, unsigned for_device);
    int (*rec_write)(void *, uint32_t off, const uint8_t *, uint32_t);
};
struct tgl_ufsh_request {
    unsigned enable;           /* 0: nothing is read, written or recorded */
    uint64_t epoch;
    uint8_t nonce[16];
    volatile uint8_t *arena;   /* TGL_UFSH_ARENA_BYTES, CPU view */
    uint64_t arena_bus;        /* identity PA, measured bypass, aligned */
    uint64_t budget_us;        /* whole pass, 1..TGL_UFSH_MAX_BUDGET_US */
    unsigned post_change_done; /* 1 only if the link code already ran TActivate + CPORT */
    uint32_t sctlr, currentel, ctr; /* measured by the caller, recorded; M must be 0 */
};
struct tgl_ufsh_lu {
    int rc;                   /* 0, or why this LU was given up. The pass goes on to the next LU unless terminal */
    uint32_t lun, stage, sense, ua, max_lba, block_bytes;
    uint32_t gpt_ok, entries_crc_ok, truncated, entry_lba, num_entries, entry_size, used, target_bad;
};
struct tgl_ufsh_result {
    int rc;
    unsigned phase, dma_started, quarantined, lists_stopped;
    uint32_t flag_reads, flag_us, tur_attempts, ua_seen, sense; /* key<<16|asc<<8|ascq */
    uint32_t list_len, lun_count;
    uint8_t luns[8];
    uint32_t read_blocks, target_found, target_lun, target_first, target_last, target_dups;
    uint32_t target_nxsb, target_manifest;
    struct tgl_ufsh_lu lu[8];
};
/* One attempt per boot. If result.quarantined is 1, DMA may still be live: do not jump to XNU. */
int tgl_ufsh_run(const struct tgl_ufsh_request *, const struct tgl_ufsh_ports *, struct tgl_ufsh_result *);
/* Guard unwind path: seals the record, no MMIO. Keeps DMA quarantined if it had started. */
void tgl_ufsh_note_fault(const struct tgl_ufsh_ports *, struct tgl_ufsh_result *, uint64_t esr, uint64_t far_value);
#endif
