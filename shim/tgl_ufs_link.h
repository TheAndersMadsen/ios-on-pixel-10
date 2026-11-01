/* SPDX-License-Identifier: GPL-2.0-only */
/* UFS link route: device-on, HCE cycle, pre-link, LINK. Physically exercised as pass B of ufs-link-r2 and
 * ufs-read-r2. There it always ran after a failed pass A; here it runs first, which has not been booted.
 * No calibration, firmware, TOP+0x510, CPM mailbox, PHY reset, list base, doorbell or DMA exists on this route.
 * Record layout: shim/decode_ufs_boot.py, which holds its own offsets. */
#ifndef TGL_UFS_LINK_H
#define TGL_UFS_LINK_H
#include <stddef.h>
#include <stdint.h>

/* ufs-link-r1 stopped on the refclk pad: its TXDATA write reads back 0, and link still came up (ufs-link-r2).
 * 1: record that latch and go on, for that pad only. 0: strict readback, the route stops there. */
#ifndef TGL_UFS_REFCLK_RELAX
#define TGL_UFS_REFCLK_RELAX 1
#endif

#define TGL_UFS_LINK_RECORD_BYTES 256u
#define TGL_UFS_LINK_RECORD_VERSION 3u
#define TGL_UFS_LINK_MAGIC UINT64_C(0x31524b4e4c534655) /* "UFSLNKR1" */
#define TGL_UFS_LINK_COMMIT UINT32_C(0x314b4e4c)
#define TGL_UFS_LINK_MAX_BUDGET_US UINT64_C(20000000)
#define TGL_UFS_LINK_MAX_ATTEMPTS 4u /* 1 + DME_LINKSTARTUP_RETRIES, ufshcd.c */

enum tgl_ufs_link_rc {
    TGL_UFS_LINK_OK = 0, TGL_UFS_LINK_OFF = 1, TGL_UFS_LINK_E_ARG = -1, TGL_UFS_LINK_E_ONCE = -2,
    TGL_UFS_LINK_E_RESOURCE = -5, TGL_UFS_LINK_E_PG = -6, TGL_UFS_LINK_E_CLOCK = -7,
    TGL_UFS_LINK_E_DEVICE_ON = -9, TGL_UFS_LINK_E_LINK = -10, TGL_UFS_LINK_E_OUTPUT = -11,
    TGL_UFS_LINK_E_FAULT = -12, TGL_UFS_LINK_E_PSM = -13, TGL_UFS_LINK_E_DECOUPLE = -14
};
enum tgl_ufs_link_stage {
    TGL_UFS_LINK_S_NONE, TGL_UFS_LINK_S_ADMITTED, TGL_UFS_LINK_S_DEVICE_ON = 3,
    TGL_UFS_LINK_S_ROUTE, TGL_UFS_LINK_S_DONE, TGL_UFS_LINK_S_FAULT, TGL_UFS_LINK_S_START
};
/* What the FDT said. The parser is the shim's, in fdt.c. */
struct tgl_ufs_link_facts {
    uint64_t hc, hc_bytes, top, top_bytes;
    unsigned named;             /* reg-names is "ufs_hc", "ufs_top", ... */
    unsigned ah8_pg, swh8_pg;   /* shipped ufs.ko sets TOP PG bits for these: route lacks them */
    unsigned decouple_ufs_en;   /* stock path sends a PMIC write this route lacks */
};
struct tgl_ufs_link_request {
    unsigned enable;
    uint64_t epoch, nonce, budget_us;
    struct tgl_ufs_link_facts facts;
};
int tgl_ufs_link_run(const struct tgl_ufs_link_request *);
int tgl_ufs_link_last_rc(void);
/* all-r1: the first link's clocks and power stay; device reset, HCE cycle and link again. Once per boot, after tgl_ufs_link_run succeeded. */
int tgl_ufs_link_relink(void);
/* Guard unwind: seals the record as FAULT, no MMIO. */
void tgl_ufs_link_note_fault(uint64_t esr, uint64_t far_value);

/* Strong imports: tgl_ufs_route.c on target, the fake in tgl_ufs_route_test.c on host. Each returns zero only
 * after a completed access. Pad which: 0 reset (HSIOS 0), 1 power (HSIOS 8), 2 refclk (HSIOS_STBY 1).
 * Pad off: 0 PARAM, 4 DMUX, 8 TXDATA, 0x10 RXDATA (reset and power only). */
int tgl_ufs_port_hc_rd(uint32_t off, uint32_t *v);
int tgl_ufs_port_hc_wr(uint32_t off, uint32_t v);
int tgl_ufs_port_top_wr(uint32_t off, uint32_t v);
int tgl_ufs_port_psm(unsigned which, uint32_t *v); /* 0 hsios, 1 ufs_hc, 2 ufs_phy; read only */
int tgl_ufs_port_pad_rd(unsigned which, uint32_t off, uint32_t *v);
int tgl_ufs_port_pad_wr(unsigned which, uint32_t off, uint32_t v);
int tgl_ufs_port_clk_on(uint32_t clock, uint64_t *a0, uint64_t *a1);
int tgl_ufs_port_now(uint64_t *t);
int tgl_ufs_port_delay(uint32_t min_us, uint32_t max_us);
int tgl_ufs_port_publish(const uint8_t rec[TGL_UFS_LINK_RECORD_BYTES]);
void tgl_ufs_port_invalidate(void);
uint32_t tgl_ufs_port_isr(void);
#endif
