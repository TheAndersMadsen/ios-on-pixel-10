#include "laguna_usb_dma.h"

static const struct laguna_usb_dma_range allowed[] = {
    {0xbe000000, 0x01000000}, /* abl@be000000: ABL's own USB arena. */
    {0x09010000, 0x00040000}, /* xhci_dma@9010000 */
    {0x09050000, 0x0000c000}, /* xhci_dma_buffer@9050000 */
    {0x97000000, 0x00400000}, /* xhci_dma_dram@97000000 */
};

static int contains(struct laguna_usb_dma_range outer, uint64_t base, uint64_t size)
{
    return base >= outer.base && size <= outer.size &&
        base - outer.base <= outer.size - size;
}

static int overlaps(uint64_t a_base, uint64_t a_size, struct laguna_usb_dma_range b)
{
    return a_base < b.base + b.size && b.base < a_base + a_size;
}

static int exact_live_range(uint64_t base, uint64_t size,
    const struct laguna_usb_dma_range *live, unsigned count)
{
    for (unsigned i = 0; i < count; i++)
        if (live[i].base == base && live[i].size == size) return 1;
    return 0;
}

int laguna_usb_dma_admit(uint64_t event_addr, uint32_t event_bytes,
    const struct laguna_usb_dma_range *live_reserved, unsigned live_count,
    const struct laguna_usb_dma_range *avoid, unsigned avoid_count,
    uint64_t *dma, uint32_t *dma_bytes, const char **why)
{
    if (!dma || !dma_bytes || !why) return -1;
    *dma = 0; *dma_bytes = 0; *why = "arguments";
    if (!event_addr || (event_addr & 4095) || event_bytes < LAGUNA_USB_DMA_MIN_BYTES ||
        (event_bytes & 3) || event_addr > UINT64_MAX - event_bytes) {
        *why = "bad event buffer geometry";
        return -1;
    }
    int admitted = 0;
    for (unsigned i = 0; i < sizeof(allowed) / sizeof(allowed[0]); i++) {
        if (!contains(allowed[i], event_addr, event_bytes) ||
            !exact_live_range(allowed[i].base, allowed[i].size, live_reserved, live_count))
            continue;
        admitted = 1;
        break;
    }
    if (!admitted) {
        *why = "event buffer outside approved live ABL/xHCI reservation";
        return -1;
    }
    for (unsigned i = 0; i < avoid_count; i++) {
        if (!avoid[i].size) continue;
        if (avoid[i].base > UINT64_MAX - avoid[i].size ||
            overlaps(event_addr, event_bytes, avoid[i])) {
            *why = "event buffer overlaps live image/input";
            return -1;
        }
    }
    *dma = event_addr;
    *dma_bytes = event_bytes < LAGUNA_USB_DMA_BYTES ? event_bytes : LAGUNA_USB_DMA_BYTES;
    *why = 0;
    return 0;
}
