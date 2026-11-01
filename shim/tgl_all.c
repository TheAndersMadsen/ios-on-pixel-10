/* SPDX-License-Identifier: MIT
 * Header 64 bytes: magic, stamp nonce, epoch, record nonce[16], count (u32, written last per entry). Entries 16 bytes: id u16, state u16, val i32, boot us u64. */
#include "tgl_all.h"
extern int tgl_stamp_boot_us(uint64_t *);
#define CAP ((TGL_ALL_RECORD_BYTES - 64u) / 16u)
static inline volatile uint8_t *rec(void) { return (volatile uint8_t *)(uintptr_t)TGL_ALL_RECORD_PA; }
static void clean(uintptr_t a, unsigned n)
{
    uint64_t ctr, line, p;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
    line = UINT64_C(4) << ((ctr >> 16) & 0xfu);
    __asm__ volatile("dsb sy" ::: "memory");
    for (p = a & ~(line - 1u); p < a + n; p += line) __asm__ volatile("dc civac, %0" :: "r"(p) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
}
static void put32(unsigned o, uint32_t v) { *(volatile uint32_t *)(void *)(rec() + o) = v; }
static void put64(unsigned o, uint64_t v) { put32(o, (uint32_t)v); put32(o + 4u, (uint32_t)(v >> 32)); }
static unsigned count, open;
void tgl_all_begin(uint64_t stamp_nonce, const uint8_t record_nonce[16], uint64_t epoch)
{
    for (unsigned i = 0; i < TGL_ALL_RECORD_BYTES; i += 4u) put32(i, 0);
    put64(8, stamp_nonce); put64(16, epoch);
    for (unsigned i = 0; i < 16u; i++) rec()[24u + i] = record_nonce[i];
    put64(0, TGL_ALL_MAGIC);
    clean(TGL_ALL_RECORD_PA, TGL_ALL_RECORD_BYTES);
    open = 1;
}
void tgl_all_mark(unsigned id, unsigned state, int32_t val)
{
    uint64_t t = 0;
    if (!open || count >= CAP) return;
    if (tgl_stamp_boot_us(&t)) t = UINT64_MAX;
    unsigned o = 64u + count * 16u;
    put32(o, (uint32_t)id | (uint32_t)state << 16); put32(o + 4u, (uint32_t)val); put64(o + 8u, t);
    count++;
    put32(40, count);
    clean(TGL_ALL_RECORD_PA + o, 16u);
    clean(TGL_ALL_RECORD_PA + 40u, 4u);
}
