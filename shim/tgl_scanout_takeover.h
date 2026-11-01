/* SPDX-License-Identifier: MIT
 * First-stage side of research/scanout-kernel-r1. Needs hakios.scanout_takeover.h on the include path.
 * tgl_scanout_takeover_clear(): first thing in shim_main on EVERY boot, before any display work: this RAM survives a warm reset.
 * tgl_scanout_takeover_publish(): only after stages A-L and one kick reached FRM_DONE with nothing in flight, then continue to XNU. */
#ifndef TGL_SCANOUT_TAKEOVER_H
#define TGL_SCANOUT_TAKEOVER_H
#include "tensor_takeover.h"
#ifndef TGL_TAKEOVER_BASE
#define TGL_TAKEOVER_BASE ((volatile uint32_t *)(uintptr_t)HAKIOS_TAKEOVER_PA)
#endif
static inline void tgl_scanout_takeover_clear(void)
{
    for (uint32_t i = 0; i < HAKIOS_TAKEOVER_BYTES / 4; ++i) TGL_TAKEOVER_BASE[i] = 0;
#ifndef TGL_TAKEOVER_NO_BARRIER
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}
static inline void tgl_scanout_takeover_publish(uint32_t stages, uint32_t ref_hz, uint32_t tx_lp, uint32_t te_seen, uint32_t frames, uint32_t chip_id, uint32_t chip_rev)
{
    struct hakios_scanout_takeover r = { .magic = HAKIOS_TAKEOVER_MAGIC, .version = HAKIOS_TAKEOVER_VERSION, .struct_size = sizeof(r), .stages = stages, .width = 1280, .height = 2856,
        .ref_hz = ref_hz, .tx_lp = tx_lp, .te_seen = te_seen, .frames = frames, .chip_id = chip_id, .chip_rev = chip_rev };
    const uint32_t *w = (const uint32_t *)(const void *)&r;
    r.crc32 = hakios_takeover_crc(&r, sizeof(r) - sizeof(r.crc32));
    /* the magic words last, so a torn record has none */
    for (uint32_t i = 2; i < sizeof(r) / 4; ++i) TGL_TAKEOVER_BASE[i] = w[i];
#ifndef TGL_TAKEOVER_NO_BARRIER
    __asm__ volatile("dsb sy" ::: "memory");
#endif
    TGL_TAKEOVER_BASE[1] = w[1]; TGL_TAKEOVER_BASE[0] = w[0];
#ifndef TGL_TAKEOVER_NO_BARRIER
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}
#endif
