#pragma once

#include <stdint.h>
#include "fdt.h"

/* M5/DPU-INIT v1 wire ABI. Do not repurpose reserved[] for snapshots: the
 * consumer requires those words to be zero and rejects unknown flag bits. */
#define TGL_DISPLAY_HANDOFF_SIZE 128u
#define TGL_DISPLAY_HANDOFF_CRC_OFFSET 112u
#define TGL_DISPLAY_HANDOFF_MAGIC UINT64_C(0x313030505344474c) /* LGDSP001 */
#define TGL_DISPLAY_HANDOFF_VERSION 1u

#define TGL_DISPLAY_F_CPU_PA_VALID       (UINT64_C(1) << 0)
#define TGL_DISPLAY_F_DPU_IOVA_VALID     (UINT64_C(1) << 1)
#define TGL_DISPLAY_F_LINEAR_32BPP       (UINT64_C(1) << 2)
#define TGL_DISPLAY_F_PHYS_CONTIGUOUS    (UINT64_C(1) << 3)
#define TGL_DISPLAY_F_RESERVED           (UINT64_C(1) << 4)
#define TGL_DISPLAY_F_DPU_CONFIGURED     (UINT64_C(1) << 5)
#define TGL_DISPLAY_F_POWER_RETAINED     (UINT64_C(1) << 6)
#define TGL_DISPLAY_F_IOMMU_RETAINED     (UINT64_C(1) << 7)
#define TGL_DISPLAY_F_SCANOUT_LIVE       (UINT64_C(1) << 8)
#define TGL_DISPLAY_F_COLD_SAFE (TGL_DISPLAY_F_CPU_PA_VALID | \
    TGL_DISPLAY_F_LINEAR_32BPP | TGL_DISPLAY_F_PHYS_CONTIGUOUS | \
    TGL_DISPLAY_F_RESERVED)
#define TGL_DISPLAY_F_LIVE_PROVEN (TGL_DISPLAY_F_COLD_SAFE | \
    TGL_DISPLAY_F_DPU_IOVA_VALID | TGL_DISPLAY_F_DPU_CONFIGURED | \
    TGL_DISPLAY_F_POWER_RETAINED | TGL_DISPLAY_F_IOMMU_RETAINED | \
    TGL_DISPLAY_F_SCANOUT_LIVE)

#define TGL_DISPLAY_MAPPING_NONE 0u
#define TGL_DISPLAY_MAPPING_IDENTITY 1u
#define TGL_DISPLAY_CACHE_WC 1u
#define TGL_DISPLAY_PIXEL_XR24 UINT32_C(0x34325258)

#define TGL_DISPLAY_DOMAIN_TOP (1u << 0)
#define TGL_DISPLAY_DOMAIN_DSI0 (1u << 1)
#define TGL_DISPLAY_DOMAIN_FE0 (1u << 2)
#define TGL_DISPLAY_DOMAIN_SNAPSHOT \
    (TGL_DISPLAY_DOMAIN_TOP | TGL_DISPLAY_DOMAIN_DSI0 | TGL_DISPLAY_DOMAIN_FE0)

struct tgl_display_handoff {
    uint64_t magic;
    uint32_t version, struct_size;
    uint64_t flags;
    uint64_t cpu_pa, cpu_size, dpu_iova, reserve_pa, reserve_size;
    uint32_t width, height, stride, pixel_format;
    uint32_t refresh_millihz, mapping_kind, cache_kind, commit_generation;
    uint8_t producer[16];
    uint32_t crc32, reserved[3];
};

_Static_assert(sizeof(struct tgl_display_handoff) == TGL_DISPLAY_HANDOFF_SIZE,
    "display handoff wire size");
_Static_assert(__builtin_offsetof(struct tgl_display_handoff, crc32) ==
    TGL_DISPLAY_HANDOFF_CRC_OFFSET, "display handoff CRC offset");

struct tgl_display_snapshot {
    uint64_t fe0_ex_address;
    uint32_t fe0_config, fe0_size, fe0_stride;
    uint32_t outpath0_coord_a, outpath0_coord_b;
    uint32_t dsi_mode_ctrl, dsi_mode_status, dsi_core_status, dsi_phy_status;
    uint32_t cdphy_status, cdphy_ctrl0;
    uint32_t captured;
};

/* Authoritative live-DT parameters supplied to the R5 provider. No timing or
 * mode is guessed from the ABL log lines. */
struct tgl_display_dsi0_config {
    uint32_t lanes, max_data_lanes, is_cphy, clk_type, mode_ctrl, auto_calc_en;
    uint32_t ppi_width, high_speed, bta, eotp, tear_effect, channel, scrambling;
    uint32_t vid_mode_type, datarate, lp2hs_time, hs2lp_time;
    uint32_t sys_clk, phy_clk, ipi_clk, lptx_clk;
    uint8_t hs_en[6]; /* vfp,vbp,vsa,hfp,hbp,hsa */
};
struct tgl_display_panel_config {
    uint32_t id, revision, width, height, datarate;
    uint32_t dsc_required, dsc_count, slice_width, slice_height;
    uint32_t bits_per_component, bits_per_pixel;
    int32_t reset_timing_ms[4];
};

enum tgl_display_result {
    TGL_DISPLAY_OK = 0,
    TGL_DISPLAY_DISABLED,
    TGL_DISPLAY_ALREADY_ATTEMPTED,
    TGL_DISPLAY_POWER_FAILED,
    TGL_DISPLAY_SNAPSHOT_FAILED,
    TGL_DISPLAY_UNSUPPORTED,
    TGL_DISPLAY_NEEDS_LIVENESS_PROOF,
    TGL_DISPLAY_LIVE,
    TGL_DISPLAY_ADT_NOT_FOUND,
    TGL_DISPLAY_ADT_MALFORMED,
    TGL_DISPLAY_ADT_OCCUPIED,
};

/* Build the conservative record on every physical-board boot. Runtime FDT
 * bootargs tgl_disp_snap=1 / tgl_disp_revive=1 then permit ONE gated attempt.
 * Revive implies the S1-S5 snapshot. Default-off performs no display/CPM MMIO. */
void tgl_display_console_init(const struct tgl_fdt_memory *memory,
    uint64_t framebuffer_pa);

/* Reservation is re-checked after payload placement is known. Overlap with
 * the XNU allocator or a resident input clears RESERVED; it never promotes a
 * buffer to DPU_CONFIGURED/SCANOUT_LIVE. */
void tgl_display_set_reserved(int reserved);

/* Copy the finalized 128-byte record into the reserved boot_args metadata page
 * and publish {record_pa,128} in mkadt's zero-valued /chosen placeholder. */
void tgl_display_export(uintptr_t destination);
int tgl_display_adt_publish(uintptr_t adt, uint32_t size, uint64_t record_pa);

const struct tgl_display_handoff *tgl_display_record(void);
const struct tgl_display_snapshot *tgl_display_snapshot(void);

/* Actual queue-mode DPU top/DSI0/FE0 power implementation (R1). */
int tgl_display_power_on(uint32_t *proven_domains);

#ifdef TGL_DISPLAY_HOSTTEST
struct tgl_display_test_ops {
    int (*power_on)(uint32_t *domains);
    int (*read32)(uintptr_t pa, uint32_t *value);
    void (*delay_us)(unsigned us);
    int (*pixel_clocks)(void);
    int (*clock_domain_reset)(void);
    int (*fe0_program)(uint64_t framebuffer_pa);
    int (*commit_and_start)(void);
    int (*dsi0_cdphy_init)(const struct tgl_display_dsi0_config *config);
    int (*panel_init)(const struct tgl_display_panel_config *config);
    int (*smmu_identity_map)(uint64_t pa, uint64_t size);
    int (*photo_liveness)(uint32_t *refresh_millihz);
};
void tgl_display_test_reset(const struct tgl_display_test_ops *ops);
void tgl_display_power_test_reset(void);
#endif
