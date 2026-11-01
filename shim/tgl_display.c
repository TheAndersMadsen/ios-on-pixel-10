/* Cold display record + fail-closed S1-S5/R1-R7 ladder (R1 display-revive).
 *
 * Safety invariants:
 *  - the baseline builds only a CRC'd RAM record; all CPM/display MMIO is off;
 *  - correlated CPM power completion is required before the first DPU read;
 *  - snapshots are diagnostic only and never authorize scanout or PA reuse;
 *  - the ladder latches after one attempt and stops at the first refusal;
 *  - live flags require R1-R7 AND an external A/B panel-photo proof.
 *
 * The frozen 128-byte handoff has no snapshot payload space. Raw register
 * values therefore stay in tgl_display_snapshot and TSHIMST2; reserved[] stays
 * zero so the linked XNU validator's single-bit-corruption contract is kept.
 */
#include "tgl_display.h"
#include "console.h"
#include "probe.h"
#include "tgl_cpm.h"
#include "tgl_stamp.h"

#define DPU_PA UINT64_C(0x0ee00000)
#define DSI2H0_PA UINT64_C(0x0efd8000)
#define CDPHY0_REGBANK_PA UINT64_C(0x0efd8800)
#define EXPECTED_FB_PA UINT64_C(0xf0000000)

#define DSI_MODE_CTRL 0x18u
#define DSI_MODE_STATUS 0x1cu
#define DSI_CORE_STATUS 0x20u
#define DSI_PHY_STATUS 0x108u
#define CDPHY_STATUS 0x24u
#define CDPHY_CTRL0 0x28u

#define SNAP_S1 0x01u
#define SNAP_S2 0x02u
#define SNAP_S3 0x04u
#define SNAP_S4 0x08u
#define SNAP_S5 0x10u
#define SNAP_ALL 0x1fu

static struct tgl_display_handoff record;
static struct tgl_display_snapshot snapshot;
static const struct tgl_display_dsi0_config dsi0_config = {
    .lanes = 4, .max_data_lanes = 4, .is_cphy = 0, .clk_type = 1,
    .mode_ctrl = 3, .auto_calc_en = 1, .ppi_width = 1, .high_speed = 1,
    .bta = 1, .eotp = 1, .tear_effect = 1, .channel = 0, .scrambling = 0,
    .vid_mode_type = 2, .datarate = 1390,
    .lp2hs_time = 0x009b00d4, .hs2lp_time = 0x006a80cc,
    .sys_clk = 400000, .phy_clk = 1200000, .ipi_clk = 75000, .lptx_clk = 20000,
    .hs_en = { 1, 1, 1, 0, 1, 1 },
};
static const struct tgl_display_panel_config panel_config = {
    .id = 0x42a1a00a, .revision = 0x05010000,
    .width = 1280, .height = 2856, .datarate = 1390,
    /* panel-gs-bmea.c: BZEA_WQHD_DSC is mandatory; a raw RGB stream is not a
     * valid substitute for the PPS/init command sequence. */
    .dsc_required = 1, .dsc_count = 2, .slice_width = 640, .slice_height = 24,
    .bits_per_component = 8, .bits_per_pixel = 128,
    .reset_timing_ms = { -1, -1, 10, 10 },
};
static unsigned record_ready, revive_attempted, last_result;

#ifndef TGL_DISPLAY_HOSTTEST
static int default_read32(uintptr_t pa, uint32_t *value)
{
    return probe_read32(pa, value) ? 0 : -1;
}

static void default_delay_us(unsigned us)
{
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    uint64_t freq, now, end;
    if (!us || us > 10000) return;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
    if (!freq) freq = 38400000;
    __asm__ volatile("mrs %0, cntvct_el0" : "=r"(now));
    end = now + (freq * us + 999999) / 1000000;
    uint64_t guard = 512 + (uint64_t)us * 512;
    do {
        __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(now));
    } while (now < end && --guard);
#else
    (void)us;
#endif
}

static int default_pixel_clocks(void)
{
    if (tgl_cpm_init()) return -1;
    return tgl_cpm_display_pixel_clocks();
}

static int default_unsupported(void)
{
    return TGL_DISPLAY_UNSUPPORTED;
}

static int default_fe0(uint64_t pa)
{
    (void)pa;
    return TGL_DISPLAY_UNSUPPORTED;
}

static int default_smmu(uint64_t pa, uint64_t size)
{
    (void)pa; (void)size;
    return TGL_DISPLAY_UNSUPPORTED;
}
static int default_dsi(const struct tgl_display_dsi0_config *config)
{
    (void)config;
    return TGL_DISPLAY_UNSUPPORTED;
}
static int default_panel(const struct tgl_display_panel_config *config)
{
    (void)config;
    return TGL_DISPLAY_UNSUPPORTED;
}

static int default_photo(uint32_t *refresh)
{
    (void)refresh;
    return TGL_DISPLAY_NEEDS_LIVENESS_PROOF;
}
#else
static struct tgl_display_test_ops test_ops;
#endif

struct display_ops {
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
static struct display_ops ops;
static unsigned ops_ready;

static void ops_init(void)
{
    if (ops_ready) return;
    ops_ready = 1;
#ifndef TGL_DISPLAY_HOSTTEST
    ops.power_on = tgl_display_power_on;
    ops.read32 = default_read32;
    ops.delay_us = default_delay_us;
    ops.pixel_clocks = default_pixel_clocks;
    ops.clock_domain_reset = default_unsupported;
    ops.fe0_program = default_fe0;
    ops.commit_and_start = default_unsupported;
    ops.dsi0_cdphy_init = default_dsi;
    ops.panel_init = default_panel;
    ops.smmu_identity_map = default_smmu;
    ops.photo_liveness = default_photo;
#endif
}

#ifdef TGL_DISPLAY_HOSTTEST
void tgl_display_test_reset(const struct tgl_display_test_ops *new_ops)
{
    volatile uint8_t *r = (volatile uint8_t *)&record;
    volatile uint8_t *s = (volatile uint8_t *)&snapshot;
    for (unsigned i = 0; i < sizeof(record); ++i) r[i] = 0;
    for (unsigned i = 0; i < sizeof(snapshot); ++i) s[i] = 0;
    record_ready = revive_attempted = last_result = 0;
    ops_ready = 1;
    if (new_ops) test_ops = *new_ops;
    else {
        volatile uint8_t *p = (volatile uint8_t *)&test_ops;
        for (unsigned i = 0; i < sizeof(test_ops); ++i) p[i] = 0;
    }
    ops.power_on = test_ops.power_on;
    ops.read32 = test_ops.read32;
    ops.delay_us = test_ops.delay_us;
    ops.pixel_clocks = test_ops.pixel_clocks;
    ops.clock_domain_reset = test_ops.clock_domain_reset;
    ops.fe0_program = test_ops.fe0_program;
    ops.commit_and_start = test_ops.commit_and_start;
    ops.dsi0_cdphy_init = test_ops.dsi0_cdphy_init;
    ops.panel_init = test_ops.panel_init;
    ops.smmu_identity_map = test_ops.smmu_identity_map;
    ops.photo_liveness = test_ops.photo_liveness;
}
#endif

static uint32_t display_crc(const struct tgl_display_handoff *h)
{
    const uint8_t *bytes = (const uint8_t *)h;
    uint32_t crc = UINT32_C(0xffffffff);
    for (unsigned i = 0; i < sizeof(*h); ++i) {
        crc ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit) {
            uint32_t mask = (uint32_t)-(int32_t)(crc & 1u);
            crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & mask);
        }
    }
    return ~crc;
}

static void display_seal(void)
{
    record.magic = TGL_DISPLAY_HANDOFF_MAGIC;
    record.version = TGL_DISPLAY_HANDOFF_VERSION;
    record.struct_size = TGL_DISPLAY_HANDOFF_SIZE;
    record.reserved[0] = record.reserved[1] = record.reserved[2] = 0;
    record.crc32 = 0;
    record.crc32 = display_crc(&record);
}

static void set_producer(const char *name)
{
    for (unsigned i = 0; i < sizeof(record.producer); ++i)
        record.producer[i] = 0;
    for (unsigned i = 0; i + 1 < sizeof(record.producer) && name[i]; ++i)
        record.producer[i] = (uint8_t)name[i];
}

static void build_record(uint64_t fb_pa)
{
    if (record_ready) return;
    record_ready = 1;
    record.flags = 0;
    record.cpu_pa = record.reserve_pa = fb_pa;
    record.cpu_size = record.reserve_size = (uint64_t)FB_STRIDE * FB_H;
    record.dpu_iova = 0;
    record.width = FB_W;
    record.height = FB_H;
    record.stride = FB_STRIDE;
    record.pixel_format = TGL_DISPLAY_PIXEL_XR24;
    record.refresh_millihz = 0;
    record.mapping_kind = TGL_DISPLAY_MAPPING_NONE;
    record.cache_kind = TGL_DISPLAY_CACHE_WC;
    record.commit_generation = 1;
    set_producer("shim-cold");
    /* A-TIME proved this exact bank-0 allocation. Other candidates are not
     * promoted by association: they produce a deliberately invalid record. */
    if (fb_pa == EXPECTED_FB_PA && record.cpu_size == UINT64_C(0xdf2000))
        record.flags = TGL_DISPLAY_F_COLD_SAFE;
    display_seal();
    tgl_stamp(TGL_STAGE_DISP_RECORD, TGL_STAMP_F_DONE,
        ((uint64_t)(uint32_t)record.flags << 32) | record.crc32);
}

const struct tgl_display_handoff *tgl_display_record(void) { return &record; }
const struct tgl_display_snapshot *tgl_display_snapshot(void) { return &snapshot; }

void tgl_display_set_reserved(int reserved)
{
    if (!record_ready || reserved || !(record.flags & TGL_DISPLAY_F_RESERVED)) return;
    uint64_t was_live = record.flags & (TGL_DISPLAY_F_DPU_CONFIGURED |
        TGL_DISPLAY_F_SCANOUT_LIVE);
    record.flags &= ~(TGL_DISPLAY_F_RESERVED | TGL_DISPLAY_F_DPU_IOVA_VALID |
        TGL_DISPLAY_F_DPU_CONFIGURED | TGL_DISPLAY_F_POWER_RETAINED |
        TGL_DISPLAY_F_IOMMU_RETAINED | TGL_DISPLAY_F_SCANOUT_LIVE);
    if (was_live) {
        record.dpu_iova = 0;
        record.mapping_kind = TGL_DISPLAY_MAPPING_NONE;
        record.refresh_millihz = 0;
        record.commit_generation++;
        set_producer("shim-cold");
    }
    display_seal();
    tgl_stamp(TGL_STAGE_DISP_RECORD, TGL_STAMP_F_REFUSED, record.flags);
}

void tgl_display_export(uintptr_t destination)
{
    volatile uint8_t *d = (volatile uint8_t *)destination;
    const uint8_t *s = (const uint8_t *)&record;
    for (unsigned i = 0; i < sizeof(record); ++i) d[i] = s[i];
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}

static int snap_read(unsigned stage, uintptr_t pa, uint32_t *out)
{
    tgl_stamp(stage, TGL_STAMP_F_ENTER, pa);
    if (!ops.read32 || ops.read32(pa, out)) {
        tgl_stamp(stage, TGL_STAMP_F_FAULT, pa);
        return -1;
    }
    tgl_stamp(stage, TGL_STAMP_F_DONE, *out);
    return 0;
}

static uint64_t daif_mask(void)
{
    uint64_t daif = 0;
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    __asm__ volatile("mrs %0, daif" : "=r"(daif));
    __asm__ volatile("msr daifset, #0xf\n\tisb" ::: "memory");
#endif
    return daif;
}

static void daif_restore(uint64_t daif)
{
#if defined(__aarch64__) && !defined(TGL_DISPLAY_HOSTTEST)
    __asm__ volatile("msr daif, %0\n\tisb" :: "r"(daif) : "memory");
#else
    (void)daif;
#endif
}

static int display_snapshot(uint32_t domains)
{
    uint32_t lo, hi;
    if ((domains & TGL_DISPLAY_DOMAIN_SNAPSHOT) != TGL_DISPLAY_DOMAIN_SNAPSHOT ||
        !ops.read32) return -1;
    snapshot.captured = 0;
    uint64_t daif = daif_mask();
    tgl_stamp(TGL_STAGE_DISP_SNAP, TGL_STAMP_F_ENTER,
        (daif << 32) | domains);
    int rc = -1;
    /* S1: source-specified EX address words; they remain DMA/IOVA evidence,
     * never a CPU-PA or mapping proof. */
    if (snap_read(TGL_STAGE_DISP_S1_ADDR_LO, DPU_PA + 0x18060, &lo)) goto out;
    if (snap_read(TGL_STAGE_DISP_S1_ADDR_HI, DPU_PA + 0x18064, &hi)) goto out;
    snapshot.fe0_ex_address = ((uint64_t)hi << 32) | lo;
    snapshot.captured |= SNAP_S1;
    /* S2: MAIN config/size/stride, not the active/shadow bank selector. */
    if (snap_read(TGL_STAGE_DISP_S2_CONFIG, DPU_PA + 0x18088,
        &snapshot.fe0_config)) goto out;
    if (snap_read(TGL_STAGE_DISP_S2_SIZE, DPU_PA + 0x1805c,
        &snapshot.fe0_size)) goto out;
    if (snap_read(TGL_STAGE_DISP_S2_STRIDE, DPU_PA + 0x18044,
        &snapshot.fe0_stride)) goto out;
    snapshot.captured |= SNAP_S2;
    /* S3: two bounded samples. Advancing coordinates are still not sufficient
     * for SCANOUT_LIVE; the required proof is panel-visible A/B alternation. */
    if (snap_read(TGL_STAGE_DISP_S3_COORD0, DPU_PA + 0xb6068,
        &snapshot.outpath0_coord_a)) goto out;
    if (ops.delay_us) ops.delay_us(1000);
    if (snap_read(TGL_STAGE_DISP_S3_COORD1, DPU_PA + 0xb6068,
        &snapshot.outpath0_coord_b)) goto out;
    snapshot.captured |= SNAP_S3;
    /* S4: DSI2H0 mode/core/link state (read-only registers). */
    if (snap_read(TGL_STAGE_DISP_S4_MODE, DSI2H0_PA + DSI_MODE_CTRL,
        &snapshot.dsi_mode_ctrl)) goto out;
    if (snap_read(TGL_STAGE_DISP_S4_MODE, DSI2H0_PA + DSI_MODE_STATUS,
        &snapshot.dsi_mode_status)) goto out;
    if (snap_read(TGL_STAGE_DISP_S4_STATUS, DSI2H0_PA + DSI_CORE_STATUS,
        &snapshot.dsi_core_status)) goto out;
    if (snap_read(TGL_STAGE_DISP_S4_STATUS, DSI2H0_PA + DSI_PHY_STATUS,
        &snapshot.dsi_phy_status)) goto out;
    snapshot.captured |= SNAP_S4;
    /* S5: G301 APB PHY_STS/PHY_CTRL0. PHY_READY/PLL_LOCK are only diagnostic
     * here; no power or liveness flag is inferred from them. */
    if (snap_read(TGL_STAGE_DISP_S5_PHY, CDPHY0_REGBANK_PA + CDPHY_STATUS,
        &snapshot.cdphy_status)) goto out;
    if (snap_read(TGL_STAGE_DISP_S5_PHY, CDPHY0_REGBANK_PA + CDPHY_CTRL0,
        &snapshot.cdphy_ctrl0)) goto out;
    snapshot.captured |= SNAP_S5;
    rc = 0;
out:
    daif_restore(daif);
    tgl_stamp(TGL_STAGE_DISP_SNAP, rc ? TGL_STAMP_F_FAULT : TGL_STAMP_F_DONE,
        snapshot.captured);
    return rc;
}

static int unsupported_if_null(int (*fn)(void))
{
    return fn ? fn() : TGL_DISPLAY_UNSUPPORTED;
}

static int revive_r2(void)
{
    /* ABL dual-id discipline: put(cmd 02,seq05,aux1) before reset(cmd04,
     * deassert). tgl_cpm_display_pixel_clocks admits only 01/07 and 02/08. */
    if (!ops.pixel_clocks || ops.pixel_clocks()) return -1;
    return unsupported_if_null(ops.clock_domain_reset);
}

static int display_revive(void)
{
    int rc;
    uint32_t refresh = 0;
    tgl_stamp(TGL_STAGE_DISP_R2, TGL_STAMP_F_ENTER, 0);
    rc = revive_r2();
    tgl_stamp(TGL_STAGE_DISP_R2, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)rc);
    if (rc) return rc;

    tgl_stamp(TGL_STAGE_DISP_R3, TGL_STAMP_F_ENTER, record.cpu_pa);
    rc = ops.fe0_program ? ops.fe0_program(record.cpu_pa) : TGL_DISPLAY_UNSUPPORTED;
    tgl_stamp(TGL_STAGE_DISP_R3, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)rc);
    if (rc) return rc;

    tgl_stamp(TGL_STAGE_DISP_R4, TGL_STAMP_F_ENTER, 0);
    rc = unsupported_if_null(ops.commit_and_start);
    tgl_stamp(TGL_STAGE_DISP_R4, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)rc);
    if (rc) return rc;

    tgl_stamp(TGL_STAGE_DISP_R5, TGL_STAMP_F_ENTER, UINT64_C(0x56e));
    rc = ops.dsi0_cdphy_init ? ops.dsi0_cdphy_init(&dsi0_config) :
        TGL_DISPLAY_UNSUPPORTED;
    tgl_stamp(TGL_STAGE_DISP_R5, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)rc);
    if (rc) return rc;

    tgl_stamp(TGL_STAGE_DISP_R6, TGL_STAMP_F_ENTER, UINT64_C(0x42a1a00a));
    rc = ops.panel_init ? ops.panel_init(&panel_config) : TGL_DISPLAY_UNSUPPORTED;
    tgl_stamp(TGL_STAGE_DISP_R6, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)rc);
    if (rc) return rc;

    tgl_stamp(TGL_STAGE_DISP_R7, TGL_STAMP_F_ENTER, record.cpu_pa);
    rc = ops.smmu_identity_map ? ops.smmu_identity_map(record.cpu_pa,
        record.cpu_size) : TGL_DISPLAY_UNSUPPORTED;
    tgl_stamp(TGL_STAGE_DISP_R7, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        (uint32_t)rc);
    if (rc) return rc;

    /* No software register read substitutes for the panel photograph. */
    tgl_stamp(TGL_STAGE_DISP_LIVE, TGL_STAMP_F_ENTER, 0);
    rc = ops.photo_liveness ? ops.photo_liveness(&refresh) :
        TGL_DISPLAY_NEEDS_LIVENESS_PROOF;
    if (rc || refresh < 1000 || refresh > 240000) {
        tgl_stamp(TGL_STAGE_DISP_LIVE, TGL_STAMP_F_REFUSED, refresh);
        return rc ? rc : TGL_DISPLAY_NEEDS_LIVENESS_PROOF;
    }
    record.dpu_iova = record.cpu_pa;
    record.mapping_kind = TGL_DISPLAY_MAPPING_IDENTITY;
    record.refresh_millihz = refresh;
    record.flags = TGL_DISPLAY_F_LIVE_PROVEN;
    record.commit_generation++;
    set_producer("shim-revive");
    display_seal();
    tgl_stamp(TGL_STAGE_DISP_LIVE, TGL_STAMP_F_DONE,
        ((uint64_t)refresh << 32) | (uint32_t)record.flags);
    return TGL_DISPLAY_LIVE;
}

void tgl_display_console_init(const struct tgl_fdt_memory *memory,
    uint64_t framebuffer_pa)
{
    ops_init();
    build_record(framebuffer_pa);
    if (!memory) return;
    unsigned flags = memory->display_flags;
    tgl_stamp(TGL_STAGE_DISP_GATE, TGL_STAMP_F_DONE, flags);
    if (!(flags & (TGL_FDT_DISP_SNAP | TGL_FDT_DISP_REVIVE))) {
        last_result = TGL_DISPLAY_DISABLED;
        return;
    }
    if (revive_attempted) {
        last_result = TGL_DISPLAY_ALREADY_ATTEMPTED;
        tgl_stamp(TGL_STAGE_DISP_GATE, TGL_STAMP_F_REFUSED, last_result);
        return;
    }
    revive_attempted = 1; /* latch BEFORE any mailbox or display access */

    uint32_t domains = 0;
    tgl_stamp(TGL_STAGE_DISP_POWER, TGL_STAMP_F_ENTER, 0);
    int rc = ops.power_on ? ops.power_on(&domains) : TGL_DISPLAY_POWER_FAILED;
    tgl_stamp(TGL_STAGE_DISP_POWER, rc ? TGL_STAMP_F_REFUSED : TGL_STAMP_F_DONE,
        ((uint64_t)(uint32_t)rc << 32) | domains);
    if (rc || (domains & TGL_DISPLAY_DOMAIN_SNAPSHOT) != TGL_DISPLAY_DOMAIN_SNAPSHOT) {
        last_result = TGL_DISPLAY_POWER_FAILED;
        return;
    }
    if (flags & TGL_FDT_DISP_REVIVE)
        tgl_stamp(TGL_STAGE_DISP_R1, TGL_STAMP_F_DONE, domains);

    if (display_snapshot(domains)) {
        last_result = TGL_DISPLAY_SNAPSHOT_FAILED;
        return;
    }
    if (!(flags & TGL_FDT_DISP_REVIVE)) {
        last_result = TGL_DISPLAY_OK;
        return;
    }
    last_result = display_revive();
    tgl_stamp(TGL_STAGE_DISP_GATE, last_result == TGL_DISPLAY_LIVE ?
        TGL_STAMP_F_DONE : TGL_STAMP_F_REFUSED, (uint32_t)last_result);
}

/* Minimal bounded ADT walker: patch only mkadt's zero /chosen placeholder. */
struct adt_patch {
    uint32_t size, nodes;
    uint64_t record_pa;
    int found, malformed, occupied;
};
static uint32_t adt32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
        (uint32_t)p[3] << 24;
}
static int adt_bytes(const uint8_t *p, uint32_t n, const char *s)
{
    unsigned i = 0;
    while (s[i]) {
        if (i >= n || p[i] != (uint8_t)s[i]) return 0;
        ++i;
    }
    return i < n && p[i] == 0;
}
static int adt_span(const struct adt_patch *c, uint32_t off, uint32_t bytes)
{
    return off <= c->size && bytes <= c->size - off;
}
static int adt_walk_one(struct adt_patch *c, uint8_t *base, uint32_t off,
    unsigned depth, uint32_t *next)
{
    if (!c || c->malformed || c->found || depth > 12 || ++c->nodes > 1024 ||
        !adt_span(c, off, 8)) {
        if (c && !c->found) c->malformed = 1;
        return -1;
    }
    uint32_t np = adt32(base + off), nc = adt32(base + off + 4);
    uint32_t p = off + 8, handoff = 0;
    int chosen = 0;
    if (np > 256 || nc > 256) { c->malformed = 1; return -1; }
    for (uint32_t i = 0; i < np; ++i) {
        if (!adt_span(c, p, 36)) { c->malformed = 1; return -1; }
        uint32_t raw = adt32(base + p + 32), len = raw & 0x7fffffffU;
        if (len > UINT32_MAX - 3) { c->malformed = 1; return -1; }
        uint32_t padded = (len + 3) & ~3U;
        if (!adt_span(c, p + 36, padded)) { c->malformed = 1; return -1; }
        const uint8_t *name = base + p, *value = base + p + 36;
        if (depth == 1 && adt_bytes(name, 32, "name") &&
            adt_bytes(value, len, "chosen")) chosen = 1;
        if (depth == 1 && adt_bytes(name, 32, "laguna-display-handoff")) {
            if (len != 16) { c->malformed = 1; return -1; }
            handoff = p + 36;
        }
        p += 36 + padded;
    }
    if (chosen && handoff) {
        for (unsigned i = 0; i < 16; ++i) if (base[handoff + i]) c->occupied = 1;
        if (c->occupied) return -1;
        uint64_t values[2] = { c->record_pa, TGL_DISPLAY_HANDOFF_SIZE };
        const uint8_t *v = (const uint8_t *)values;
        for (unsigned i = 0; i < 16; ++i) base[handoff + i] = v[i];
        c->found = 1;
        if (next) *next = p;
        return 0;
    }
    for (uint32_t i = 0; i < nc && !c->found; ++i)
        if (adt_walk_one(c, base, p, depth + 1, &p)) return -1;
    if (next) *next = p;
    return c->malformed || c->occupied ? -1 : 0;
}

int tgl_display_adt_publish(uintptr_t adt, uint32_t size, uint64_t record_pa)
{
    if (!adt || size < 8 || !record_pa) return TGL_DISPLAY_ADT_MALFORMED;
    struct adt_patch c = { .size = size, .record_pa = record_pa };
    uint32_t next = 0;
    uint8_t *base = (uint8_t *)adt;
    if (adt_walk_one(&c, base, 0, 0, &next)) {
        if (c.occupied) return TGL_DISPLAY_ADT_OCCUPIED;
        return c.found ? 0 : TGL_DISPLAY_ADT_MALFORMED;
    }
    return c.found ? 0 : TGL_DISPLAY_ADT_NOT_FOUND;
}
