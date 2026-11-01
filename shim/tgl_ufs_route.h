/* SPDX-License-Identifier: MIT
 * The UFS boot route, in shim.c order. Gates, all build-time:
 *   TGL_UFS_ROUTE            link route replaces the legacy ladder (build.sh turns it on)
 *   TGL_UFS_POST_LINK        NOP, fDeviceInit, TUR, REPORT LUNS after link (build.sh turns it on)
 *   TGL_UFS_READ             GPT and target READ(10) after that (tgl_ufs_host.h, default on)
 *   TGL_UFS_SCSI_STATUS_ONLY phone's response=1 with CHECK CONDITION (tgl_ufs_host.h, default on)
 *   TGL_UFS_REFCLK_RELAX     refclk TX latch readback (tgl_ufs_link.h, default on)
 *   TGL_UFS_HANDOFF          XNU takes over: live attested, tokens admitted (default off)
 * There is no storage write command on this route. See the wire gate in tgl_ufs_host.c. */
#ifndef TGL_UFS_ROUTE_H
#define TGL_UFS_ROUTE_H
#include <stdint.h>
#include "fdt.h"
#ifndef TGL_UFS_ROUTE
#define TGL_UFS_ROUTE 0
#endif
#ifndef TGL_UFS_POST_LINK
#define TGL_UFS_POST_LINK 0
#endif
#ifndef TGL_UFS_HANDOFF
#define TGL_UFS_HANDOFF 0
#endif
/* Guarded link route. Nonzero: a fault unwound; call tgl_ufs_link_note_fault. */
unsigned tgl_ufs_route_link_guarded(const struct tgl_ufs_fdt_regions *regions);
/* Own guard bracket. Call only after the link route returned. Gates on HCS.DP itself, so a failed link costs reads. */
int tgl_ufs_route_after_link(void);
/* 1: DMA may still be live, the caller must not start a kernel. */
int tgl_ufs_route_must_park(void);
/* enum ufsh_outcome. <0: the caller must not start a kernel. One call per boot. */
int tgl_ufs_route_handoff(unsigned link_faulted);
#endif
