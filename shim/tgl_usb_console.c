/* Laguna USB console integration for teguload v3.
 *
 * EP0 is DMA on DWC3, not PIO. Admission therefore reuses only the exact ABL
 * event allocation, after checking its live-FDT reservation, CPU access and
 * ownership. No new SMMU mapping, arbitrary DMA pool, DPU access or blind MMIO.
 */
#include "tgl_usb_console.h"
#include "console.h"
#include "laguna_usb.h"
#include "laguna_usb_config.h"
#include "laguna_usb_dma.h"
#include "tgl_cpm.h"
#include "tgl_stamp.h"
#include "probe.h"

#define GSNPSID 0xc120
#define GCTL 0xc110
#define DCTL 0xc704
#define GEVNTADRLO 0xc400
#define GEVNTADRHI 0xc404
#define GEVNTSIZ 0xc408
#define GCTL_PRTCAPDIR (3u << 12)
#define GCTL_PRTCAP_DEVICE (2u << 12)
#define USB2_CFG21_PHY_ENABLE (1u << 12)

static int io_read(void *context, uintptr_t base, uint32_t off, uint32_t *value)
{
    (void)context;
    return probe_read32(base + off, value) ? 0 : -1;
}

static int io_write(void *context, uintptr_t base, uint32_t off, uint32_t value)
{
    (void)context;
    return probe_write32(base + off, value) ? 0 : -1;
}

static void reboot_callback(void *context)
{
    (void)context;
    tgl_usb_reset_now();
}

/* CPU/device addresses are identical on the MMU-off device. A host test or a
 * future XNU adapter may override this mapping without changing admission. */
#ifndef TGL_USB_DMA_CPU
#define TGL_USB_DMA_CPU(pa) ((uintptr_t)(pa))
#endif

static int preflight_valid_dwc3_id(uint32_t id)
{
    return id == 0x33313130 || (id >> 16) == 0x5533 || (id >> 16) == 0x3332;
}

/* Warm-plausibility for the v3.5 skip decision: the Synopsys 0x333130xx /
 * 0x333131xx family (felix's model used 0x33313130) plus the families the
 * preflight validator already accepts. A warm controller must read as SOME
 * Synopsys ID; 0x0/0xffffffff means cold or absent. */
static int warm_plausible_id(uint32_t id)
{
    return preflight_valid_dwc3_id(id) ||
        (id >> 8) == 0x333130 || (id >> 8) == 0x333131;
}

static int preflight(uint64_t *event_addr, uint32_t *event_bytes)
{
    uint32_t id, gctl, hi, lo, size, power, cfg19, cfg21;
    tgl_stamp(TGL_STAGE_USB_PREFLIGHT, TGL_STAMP_F_ENTER, 0);
    /* Every read below stamps ITS VALUE (or FAULT): the next run answers
     * "which check refused and what the hardware actually returned". */
    if (!probe_read32(0x0c450000, &power)) {
        tgl_stamp(TGL_STAGE_USB_PWR, TGL_STAMP_F_FAULT, 0);
        return -1;
    }
    if (power == 0xffffffffu) {
        /* A-DT canary: the wrapper CSR shares the USB clock domain. All-ones
         * means the CPM resume did NOT take — refuse here, never touch
         * DWC3 (fail fast, save the photo window for the real evidence). */
        tgl_stamp(TGL_STAGE_USB_PWR, TGL_STAMP_F_REFUSED, power);
        tgl_stamp_reason(TGL_STAMP_R_CPM);
        return -1;
    }
    tgl_stamp(TGL_STAGE_USB_PWR, TGL_STAMP_F_DONE, power);
    if (!probe_read32(LAGUNA_USB_DWC3_BASE + GSNPSID, &id)) {
        tgl_stamp(TGL_STAGE_USB_GSNPSID, TGL_STAMP_F_FAULT, 0);
        return -1;
    }
    tgl_stamp(TGL_STAGE_USB_GSNPSID, TGL_STAMP_F_DONE, id);
    if (!probe_read32(LAGUNA_USB_DWC3_BASE + GCTL, &gctl)) {
        tgl_stamp(TGL_STAGE_USB_GCTL, TGL_STAMP_F_FAULT, 0);
        return -1;
    }
    tgl_stamp(TGL_STAGE_USB_GCTL, TGL_STAMP_F_DONE, gctl);
    if (!probe_read32(LAGUNA_USB_DWC3_BASE + GEVNTADRHI, &hi)) {
        tgl_stamp(TGL_STAGE_USB_EVT_HI, TGL_STAMP_F_FAULT, 0);
        return -1;
    }
    tgl_stamp(TGL_STAGE_USB_EVT_HI, TGL_STAMP_F_DONE, hi);
    /* A-ABL §8 fingerprint: DCTL bit31==0 (RUN_STOP cleared) + readable
     * registers = the warm world. Stamped so the dump distinguishes
     * "fastboot handoff" from "non-fastboot chain (USB powered off)". */
    uint32_t dctl;
    if (probe_read32(LAGUNA_USB_DWC3_BASE + DCTL, &dctl))
        tgl_stamp(TGL_STAGE_USB_DCTL, TGL_STAMP_F_DONE, dctl);
    else
        tgl_stamp(TGL_STAGE_USB_DCTL, TGL_STAMP_F_FAULT, 0);
    if (!probe_read32(LAGUNA_USB_DWC3_BASE + GEVNTADRLO, &lo) ||
        !probe_read32(LAGUNA_USB_DWC3_BASE + GEVNTSIZ, &size) ||
        !probe_read32(LAGUNA_USB2_CFG_BASE, &cfg19) ||
        !probe_read32(LAGUNA_USB2_CFG_BASE + 8, &cfg21))
        return -1;
    laguna_usb_log_hex("TGL USB: preflight GSNPSID", id);
    laguna_usb_log_hex("TGL USB: preflight GCTL", gctl);
    laguna_usb_log_hex("TGL USB: USB2 CFG19 retained", cfg19);
    laguna_usb_log_hex("TGL USB: USB2 CFG21", cfg21);
    laguna_usb_log_hex("TGL USB: inherited event HI", hi);
    laguna_usb_log_hex("TGL USB: inherited event LO", lo);
    laguna_usb_log_hex("TGL USB: inherited event size", size);
    if (!preflight_valid_dwc3_id(id)) {
        tgl_stamp(TGL_STAGE_USB_BADID, TGL_STAMP_F_REFUSED, id);
        return -2;
    }
    if ((gctl & GCTL_PRTCAPDIR) != GCTL_PRTCAP_DEVICE) {
        tgl_stamp(TGL_STAGE_USB_BADCAP, TGL_STAMP_F_REFUSED, gctl);
        return -2;
    }
    if (hi) {
        /* The hang-check: ABL must not have left an inherited event buffer. */
        tgl_stamp(TGL_STAGE_USB_EVTHANG, TGL_STAMP_F_REFUSED, hi);
        return -2;
    }
    if ((power & 3) != 0) { /* USB2 PMU must be D0; USB3 is irrelevant. */
        tgl_stamp(TGL_STAGE_USB_BADPWR, TGL_STAMP_F_REFUSED, power);
        return -3;
    }
    tgl_stamp(TGL_STAGE_USB_PREFLIGHT, TGL_STAMP_F_DONE, id);
    *event_addr = (uint64_t)hi << 32 | lo;
    *event_bytes = size & 0xffff;
    return 0;
}

int tgl_usb_console_start(const struct tgl_fdt_memory *memory)
{
    if (!memory) return LAGUNA_USB_ERR_ARGUMENT;
    laguna_usb_set_reboot_handler(reboot_callback, 0);
    laguna_usb_set_stamp_sink(tgl_failure_record);
    if (con_fb_pa)
        laguna_usb_set_framebuffer((const volatile uint8_t *)con_fb_pa,
            FB_W, FB_H, FB_STRIDE);

    /* v3.5 WARM-SKIP PATH (ABL-USB-STATE.md, disassembly-proven): on the
     * fastboot-boot handoff USB is WARM — clocks on, USB TOP domain on,
     * GCTL stays device-mode, registers identity-mapped, only
     * DCTL.RUN_STOP cleared. Probe the canary + GSNPSID FIRST: if the
     * Synopsys ID is plausible, skip the ENTIRE CPM phase (the PHY was
     * fastboot's own device moments ago) and go straight to preflight.
     * v34b evidence: the queue-geometry handshake read 0 words on both
     * sides (wrong region/protocol — DT mba-ctrl windows vs ABL's MBA
     * bases), so warm-first also avoids a guaranteed cold-path failure on
     * the fastboot route. Validate-first, bail-never-block. */
    const struct laguna_usb_board_ops *board = tgl_cpm_board_ops();
    tgl_stamp(TGL_STAGE_USB_WARM, TGL_STAMP_F_ENTER, 0);
    /* v3.6: probe BOTH wrapper CSRs (A-DT: usb2_cfg_csr 0xc450014 sits in
     * the same window as usbcs_host_cfg_csr 0xc450000 — if one reads 0 and
     * the other does not, the 0 is semantics, not a dead bus) and carry the
     * GSNPSID value in the verdict arg. Faulted reads record 0xffffffff. */
    uint32_t can0 = 0xffffffffu, can14 = 0xffffffffu, warm_id = 0;
    int can0_ok = probe_read32(0x0c450000, &can0);
    if (!can0_ok) can0 = 0xffffffffu;
    int can14_ok = probe_read32(0x0c450014, &can14);
    if (!can14_ok) can14 = 0xffffffffu;
    int id_ok = probe_read32(LAGUNA_USB_DWC3_BASE + GSNPSID, &warm_id);
    if (!id_ok) warm_id = 0;
    /* v3.8 FIX (v37 device run): the verdict used to require both wrapper
     * CSRs to read nonzero — but usbcs_host_cfg_csr (0xc450000) legitimately
     * reads 0 in device mode, so a perfectly warm controller was refused
     * cold (v37: gsnpsid=0x33313130 read fine, verdict NO, canary arg=0).
     * Per A-DT the DWC3 core runs on FIXED clocks — a plausible GSNPSID
     * ALONE proves the core is up. The canaries are diagnostics only. */
    int warm = id_ok && warm_id && warm_plausible_id(warm_id);
    /* Canary diagnostics (never gate): usbcs_host_cfg CSR value, then the
     * usb2_cfg_csr value packed with its address 0xc4500014. */
    tgl_stamp(TGL_STAGE_USB_PWR, can0_ok ? TGL_STAMP_F_DONE :
        TGL_STAMP_F_FAULT, can0);
    tgl_stamp(TGL_STAGE_USB_WARM, can14_ok ? TGL_STAMP_F_DONE :
        TGL_STAMP_F_FAULT, ((uint64_t)can14 << 32) | 0xc4500014u);
    int resume_requested;
    if (warm) {
        tgl_stamp(TGL_STAGE_USB_WARM, TGL_STAMP_F_DONE, warm_id);
        resume_requested = false; /* PHY was fastboot's own; do not re-resume */
    } else {
        /* NO verdict carries the gsnpsid value that said no (0 = the ID
         * read itself faulted). */
        tgl_stamp(TGL_STAGE_USB_WARM, TGL_STAMP_F_REFUSED, warm_id);
        /* v3.5 COLD PATH — MBA port (ABL-USB-STATE.md §5): 3 static
         * mailboxes (6/1/1 channels), 4-dword pointer messages
         * {0x1A000000|id, PA_lo, PA_hi, 0xb}, doorbell +0x18/+0x20 by
         * msg[0] bit21, response mask (w&0x7f400000)==0x1a400000|bit23.
         * The queue-geometry handshake is REMOVED (v34b: 0 words both
         * sides). All placeholders stamped; fail closed. */
        tgl_stamp(TGL_STAGE_CPM_FIRST, TGL_STAMP_F_ENTER, 0);
        int result = tgl_cpm_init();
        if (result) {
            tgl_stamp_reason(TGL_STAMP_R_CPM);
            return result;
        }
        tgl_stamp(TGL_STAGE_PHY_RESUME, TGL_STAMP_F_ENTER, 0);
        result = laguna_usb_board_resume(board);
        tgl_stamp(TGL_STAGE_PHY_RESUME,
            result ? TGL_STAMP_F_FAULT : TGL_STAMP_F_DONE,
            (uint32_t)(int32_t)result);
        if (result) {
            tgl_stamp_reason(TGL_STAMP_R_CPM);
            return result;
        }
        resume_requested = true;
    }

    uint64_t event_addr;
    uint32_t event_bytes;
    int result2 = preflight(&event_addr, &event_bytes);
    if (result2) return result2;
    if (!warm) {
        /* S7 of CPM-FIRST-SPEC §2 (cold path only): init|pwr|clk|rst|rdback
         * all green. */
        tgl_stamp(TGL_STAGE_CPM_FIRST, TGL_STAMP_F_DONE, 0x1f);
    }

    struct laguna_usb_dma_range live[TGL_FDT_MAX_RESERVED];
    if (memory->reserved_count > TGL_FDT_MAX_RESERVED) return LAGUNA_USB_ERR_DMA;
    for (unsigned i = 0; i < memory->reserved_count; i++) {
        live[i].base = memory->reserved[i].base;
        live[i].size = memory->reserved[i].size;
    }
    struct laguna_usb_dma_range avoid[8];
    unsigned avoid_count = 0;
    extern char _head[], _end[];
    avoid[avoid_count++] = (struct laguna_usb_dma_range){
        (uintptr_t)_head, (uintptr_t)_end - (uintptr_t)_head};
    /* The live FDT itself is a resident input. */
    /* memory does not retain its source PA, so the caller's DTB is recovered
     * from the handoff register in shim.c through this explicit range below. */
    extern uint64_t boot_regs[5];
    avoid[avoid_count++] = (struct laguna_usb_dma_range){boot_regs[0], memory->total_size};
    if (memory->initrd_fields == 3 && memory->initrd_end > memory->initrd_start)
        avoid[avoid_count++] = (struct laguna_usb_dma_range){
            memory->initrd_start, memory->initrd_end - memory->initrd_start};
    avoid[avoid_count++] = (struct laguna_usb_dma_range){0x95200000, 0x400000};
    avoid[avoid_count++] = (struct laguna_usb_dma_range){0x80000000, 0x10000000};
    if (con_fb_pa)
        avoid[avoid_count++] = (struct laguna_usb_dma_range){con_fb_pa, FB_STRIDE * FB_H};

    uint64_t dma;
    uint32_t dma_bytes;
    const char *why;
    tgl_stamp(TGL_STAGE_DMA_ADMIT, TGL_STAMP_F_ENTER, event_addr);
    if (laguna_usb_dma_admit(event_addr, event_bytes, live, memory->reserved_count,
        avoid, avoid_count, &dma, &dma_bytes, &why)) {
        laguna_usb_log(why);
        tgl_stamp(TGL_STAGE_DMA_ADMIT, TGL_STAMP_F_REFUSED, event_addr);
        return LAGUNA_USB_ERR_DMA;
    }
    tgl_stamp(TGL_STAGE_DMA_ADMIT, TGL_STAMP_F_DONE, dma);
    /* Prove CPU readability at both ends of the original allocation before
     * treating its DMA address as a CPU pointer. This is not an SMMU write. */
    uint32_t sample;
    if (!probe_read32((uintptr_t)dma, &sample) ||
        !probe_read32((uintptr_t)(dma + event_bytes - 4), &sample))
        return LAGUNA_USB_ERR_DMA;

    /* CPM init + the first resume already ran ABOVE on the cold path (clocks
     * before any DWC3 MMIO read); the warm path skips both. The resume-done
     * latch + resume_requested=false keep start() from re-resuming a warm
     * PHY; if the warm assumption was wrong (cfg21 PHY_ENABLE clear),
     * start() cascades to the MBA client and fails closed with stamps. */
    struct laguna_usb_config config = {
        .dwc3_base = LAGUNA_USB_DWC3_BASE,
        .usb2_cfg_base = LAGUNA_USB2_CFG_BASE,
        .usbdp_top_base = LAGUNA_USBDPTOP_BASE,
        .dma = TGL_USB_DMA_CPU(dma),
        .dma_pa = dma,
        .dma_bytes = dma_bytes,
        .dma_path_admitted = true,
        .read32 = io_read,
        .write32 = io_write,
        .board = board,
        .resume_requested = resume_requested,
    };
    return laguna_usb_start(&config);
}

void tgl_usb_console_service(void)
{
    if (!laguna_usb_running()) return;
    laguna_usb_poll();
    int c;
    while ((c = laguna_usb_getc()) >= 0)
        laguna_usb_log_hex("TGL USB RX byte", (unsigned)c);
}

static uint64_t usb_counter_frequency(void)
{
    uint64_t freq = 0;
#ifdef __aarch64__
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(freq));
#endif
    return freq ? freq : 38400000;
}

void tgl_usb_console_wait(unsigned seconds)
{
    if (!seconds || !laguna_usb_running()) return;
    tgl_stamp(TGL_STAGE_USB_WAIT, TGL_STAMP_F_ENTER, seconds);
    uint64_t start, now;
#ifdef __aarch64__
    __asm__ volatile("mrs %0, cntpct_el0" : "=r"(start));
#else
    start = 0;
#endif
    now = start;
    uint64_t budget = usb_counter_frequency() * seconds;
    uint64_t guard = 100000 + (uint64_t)seconds * 100000; /* dead-counter cap */
    while (now - start < budget && --guard) {
        tgl_usb_console_service();
        /* The firmware WDT is armed+pat during bring-up (v3.4 posture);
         * this loop can run 8-9 s without a console character, so feed
         * the dog here or the bark/bite lands mid-wait (v42 forensics:
         * FAULT 0x0 at pat+9.1 s exactly). */
        if (con_tick) con_tick();
#ifdef __aarch64__
        __asm__ volatile("isb\n\tmrs %0, cntpct_el0" : "=r"(now));
#else
        now += usb_counter_frequency() / 100 + 1;
        if (now - start >= budget) break;
#endif
    }
    tgl_stamp(TGL_STAGE_USB_WAIT, TGL_STAMP_F_DONE, laguna_usb_running());
}
