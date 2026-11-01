#pragma once

#include <stdint.h>
#include "laguna_usb.h"

struct laguna_usb_dma_range {
    uint64_t base, size;
};

/* Pure admission check for the original ABL DWC3 event allocation. It does
 * not probe memory, configure an SMMU, or claim that arbitrary RAM is DMA-able.
 * The accepted allocation is event_addr/event_bytes, capped at 16 KiB for this
 * driver. All ranges are half-open [base, base+size). */
int laguna_usb_dma_admit(uint64_t event_addr, uint32_t event_bytes,
    const struct laguna_usb_dma_range *live_reserved, unsigned live_count,
    const struct laguna_usb_dma_range *avoid, unsigned avoid_count,
    uint64_t *dma, uint32_t *dma_bytes, const char **why);
