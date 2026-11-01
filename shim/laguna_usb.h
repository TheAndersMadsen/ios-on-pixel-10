#ifndef LAGUNA_USB_H
#define LAGUNA_USB_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LAGUNA_USB_LOG_CAPACITY (1024u * 1024u)
#define LAGUNA_USB_DMA_BYTES 0x4000u
#define LAGUNA_USB_DMA_MIN_BYTES 0x0c0u
#define LAGUNA_USB_STAMP_SLOTS 8u
#define LAGUNA_USB_STAMP_MAGIC 0x4c47u /* "LG" in wIndex */

/* CPM LPB service IDs come from the captured live FDT. The board callbacks
 * below are semantic operations, not permission to turn an ID into an MMIO
 * address. Implement them with the source-reviewed CPM/mailbox transport. */
enum laguna_usb_clock_id {
    LAGUNA_USB_CLOCK_USBC_NON_STICKY = 0x07,
    LAGUNA_USB_CLOCK_USBC_STICKY = 0x08,
    LAGUNA_USB_CLOCK_U2PHY_APB = 0x0e,
    LAGUNA_USB_CLOCK_USB2_PHY_RESET = 0x11,
};

enum laguna_usb_reset_id {
    LAGUNA_USB_RESET_USB_TOP_CSR = 0x06,
    LAGUNA_USB_RESET_U2PHY_APB = 0x09,
    LAGUNA_USB_RESET_USBC_NON_STICKY = 0x0a,
    LAGUNA_USB_RESET_USBC_STICKY = 0x0b,
    LAGUNA_USB_RESET_USBC_DRD_BUS = 0x0c,
    LAGUNA_USB_RESET_USB2_PHY = 0x0d,
    LAGUNA_USB_RESET_USB3DP_PHY = 0x0e, /* USB3 only; not touched by USB2. */
};

struct laguna_usb_board_ops {
    void *context;

    /* Establish sswrp_hsio_n_pd -> hsio_n_usb_pd (subdomain 0) ->
     * hsio_n_usb_psw_pd (subdomain 5), and the fixed USB rails. This callback
     * must be idempotent and must report firmware errors, never fake success. */
    int (*power_on)(void *context);

    /* CPM clock/reset provider: lpcm-id 5 (HSION). Enable/deassert only the
     * named ID. Return 0 on confirmed success, negative on any failure. */
    int (*clock_enable)(void *context, uint32_t clock_id);
    int (*reset_deassert)(void *context, uint32_t reset_id);

    /* Optional reset query: 1 asserted, 0 deasserted, negative unknown. */
    int (*reset_status)(void *context, uint32_t reset_id);

    /* Preserve the detected Type-C orientation while ensuring the TUSB2E11
     * repeater at I2C10/0x3e, its rails, and peripheral role are ready. */
    int (*repeater_peripheral)(void *context);
};

struct laguna_usb_config {
    uintptr_t dwc3_base;       /* live FDT: 0x0c400000, length 0xd060 */
    uintptr_t usb2_cfg_base;   /* live FDT: 0x0c450014, length 0x0c */
    uintptr_t usbdp_top_base;  /* live FDT: 0x0c637000, length 0xa0 */

    /* One physically contiguous, 4 KiB-aligned, 16 KiB DMA allocation. CPU and
     * device addresses differ behind an IOMMU. MMU-off shim identity mappings
     * may use dma == dma_pa, but only after the DMA path is actually admitted. */
    uintptr_t dma;
    uint64_t dma_pa;
    /* Actual admitted allocation size, not a maximum to probe or zero. The
     * built-in arena is 16 KiB, while an inherited ABL event buffer may be
     * smaller. Data reads are capped at min(512, dma_bytes - 0x80). */
    uint32_t dma_bytes;
    bool dma_path_admitted;

    /* Optional fault-gated accessors. NULL selects direct volatile MMIO.
     * Nonzero callback status aborts the operation and blocks later writes. */
    int (*read32)(void *context, uintptr_t base, uint32_t offset, uint32_t *value);
    int (*write32)(void *context, uintptr_t base, uint32_t offset, uint32_t value);
    void *io_context;

    /* NULL means inherited-warm-handoff only. No CPM/repeater cold resume is
     * attempted. If PHY_ENABLE is clear (or a queried reset is asserted), the
     * start fails closed rather than inventing firmware-provider writes. */
    const struct laguna_usb_board_ops *board;
    /* Set when the caller deliberately wants the source-backed clock/reset
     * sequence even if PHY_ENABLE is already set (e.g. first console boot). */
    bool resume_requested;
};

enum laguna_usb_error {
    LAGUNA_USB_OK = 0,
    LAGUNA_USB_ERR_ARGUMENT = -1,
    LAGUNA_USB_ERR_DMA = -2,
    LAGUNA_USB_ERR_ID = -3,
    LAGUNA_USB_ERR_MODE = -4,
    LAGUNA_USB_ERR_PROVIDER = -5,
    LAGUNA_USB_ERR_RESET_TIMEOUT = -6,
    LAGUNA_USB_ERR_ENDPOINT = -7,
    LAGUNA_USB_ERR_HALT_TIMEOUT = -8,
    LAGUNA_USB_ERR_BUSY = -9,
    LAGUNA_USB_ERR_MMIO = -10,
};

/* Append-only byte stream used by the existing Tegu host reader. Logging works
 * before controller start, so early shim messages are replayed after EP0 is up. */
void laguna_usb_putc(uint8_t byte);
void laguna_usb_write(const void *bytes, size_t length);
void laguna_usb_log(const char *line);
void laguna_usb_log_hex(const char *label, uint64_t value);
int laguna_usb_getc(void);
uint32_t laguna_usb_dropped_bytes(void);

void laguna_usb_set_reboot_handler(void (*handler)(void *context), void *context);
/* A sink is an array of eight RAM words (for example tgl_failure_record).
 * Request 0x5e can write only an indexed word, never an arbitrary address. */
void laguna_usb_set_stamp_sink(volatile uint64_t slots[LAGUNA_USB_STAMP_SLOTS]);
void laguna_usb_set_framebuffer(const volatile uint8_t *pixels,
    uint32_t width, uint32_t height, uint32_t row_bytes);

/* Start the polled EP0-only gadget. All provider/DMA admission must be honest;
 * no storage or partition operation exists in this module. */
int laguna_usb_start(const struct laguna_usb_config *config);
/* Run the board power/clock/reset/repeater resume sequence once, standalone.
 * Idempotent: laguna_usb_start repeats it internally. v3.3 uses this to clock
 * the USB domain BEFORE any DWC3/PHY MMIO read (cold ABL handoff order fix). */
int laguna_usb_board_resume(const struct laguna_usb_board_ops *board);
/* In-image 16 KiB DMA storage for the MMU-off standalone shim only. The caller
 * still has to prove the controller can DMA to its physical address. */
uintptr_t laguna_usb_builtin_dma(void);
void laguna_usb_poll(void);
bool laguna_usb_running(void);
bool laguna_usb_transfer_active(void);

#endif /* LAGUNA_USB_H */
