/* SPDX-License-Identifier: MIT
 * Shim -> XNU UFS takeover contract, research/ufs-root-handoff-r1 on the integrated route, gate TGL_UFS_HANDOFF.
 * Sequence and refusal classes follow N911 HANDOFF-INTERFACE.md. No DMA, no
 * command, no HCE, clock, pad or power write: stopping both lists is the only
 * effect. Never ran on a phone. */
#ifndef TGL_UFS_HANDOFF_H
#define TGL_UFS_HANDOFF_H
#include <stdint.h>

/* UFSHCI offsets; same map as bsd/dev/hakios.blazer_ufs.c. */
#define UFSH_AHIT     0x18u
#define UFSH_IS       0x20u /* W1C, not clear-on-read; read only here */
#define UFSH_HCS      0x30u
#define UFSH_UTRLDBR  0x58u
#define UFSH_UTRLRSR  0x60u
#define UFSH_UTMRLDBR 0x78u
#define UFSH_UTMRLRSR 0x80u
#define UFSH_HCS_READY 0x3u /* DP | UTRLRDY: what ufs_take_over requires */
/* Linux DEVICE_FATAL(11), CONTROLLER_FATAL(16), SYSTEM_BUS_FATAL(17), CRYPTO_FATAL(18) */
#define UFSH_IS_FATAL 0x00070800u

enum ufsh_outcome {
    UFSH_NO_DMA = 0, /* the host never had a list from us: rd=md0 route, no MMIO done */
    UFSH_LIVE = 1,   /* lists stopped, arena closed, read proven: XNU may take over */
    UFSH_DOWN = 2,   /* lists stopped, arena closed, not usable: rd=md0 route */
    UFSH_HALT = -1   /* DMA may still write memory: do not start any kernel */
};

/* Facts the route already holds. All zero means nothing happened. */
struct ufsh_evidence {
    unsigned dma_opened;   /* a list base was ever written, or the arena opened */
    unsigned read_match;   /* READ pass finished and the target located; no image required */
    unsigned faulted;      /* guard unwound during the route */
    unsigned quarantined;  /* engine quarantined */
    unsigned retained;     /* a command's DMA state is not RETURNED */
    unsigned aux_clk_held; /* clocks proven on by the read; nothing released them */
    unsigned lun;          /* LUN the proven read used */
};

/* A nonzero return from a port means the access itself is untrustworthy. */
struct ufsh_ports {
    void *ctx;
    int (*read32)(void *ctx, uint32_t offset, uint32_t *value);
    int (*write32)(void *ctx, uint32_t offset, uint32_t value);
    int (*arena_close)(void *ctx); /* called only after both lists stopped and doorbells idle */
};

struct ufsh_record {
    uint32_t step; /* last step entered, for the stamp */
    uint32_t utrldbr, utmrldbr, utrlrsr, utmrlrsr, ahit, hcs, is;
    unsigned arena_closed;
};

/* Call once, immediately after the route ends and before the arena deadline. */
int ufsh_finalize(const struct ufsh_evidence *, const struct ufsh_ports *,
    struct ufsh_record *);

/* 1 only if the kernel will use the LUN that was proven, for a route the
 * userland supports: blazer_ufs=2, blazer_ufs_live=1, blazer_ufs_root=NAME,
 * rd=ufsroot0 or rd=md0, and blazer_ufs_lun=<lun> (absent means 0, as in XNU). */
int ufsh_cmdline_ok(const char *cmdline, unsigned lun);
#endif
