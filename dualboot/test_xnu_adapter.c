/* SPDX-License-Identifier: MIT
 * Actual adapter under modeled XNU/USB APIs and the REAL local N882 header.
 * No hardware, scheduler or concurrency proof is implied by this harness.
 */
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/hakios.blazer_ufs_exact.h>
#define TUNABLE(t, n, key, initial) static t n = initial
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define NSEC_PER_MSEC 1000000u
#define KERN_SUCCESS 0
typedef int thread_t;
typedef int wait_result_t;
static unsigned threads, reads, identity_reads;
static uint64_t now = 100;
static int return_code, thread_result;
static struct n882_receipt answer;
static uint8_t usb_output[384];
static uint32_t usb_bytes;

static void delay_for_interval(unsigned n, unsigned units) { (void)n; (void)units; }
static void thread_set_thread_name(thread_t t, const char *name) { (void)t; (void)name; }
static void thread_deallocate(thread_t t) { (void)t; }
static int kernel_thread_start(void (*fn)(void *, int), void *p, thread_t *t)
{
    (void)fn; (void)p; *t = 1; threads++; return thread_result;
}
static void blazer_mirror_ident(uint64_t *nonce, uint64_t *entry) { *nonce = 0x1234; *entry = 42; }
static void uc_put_words(const void *p, uint32_t n)
{
    assert(n <= sizeof(usb_output)); memcpy(usb_output, p, n); usb_bytes = n;
}
int n882_blazer_readback_lun(uint32_t *lun) { identity_reads++; *lun = 0; return 0; }
uint64_t n882_blazer_now_us(void) { return now; }
int n882_blazer_read10_exact(const struct n882_read10_request *req, struct n882_receipt *receipt)
{
    reads++;
    assert(req->abi == N882_ABI && req->block_bytes == 4096 && req->block_count == 1);
    assert(req->absolute_lba == 999 && req->deadline_us == now + N882_MAX_BUDGET_US);
    assert(req->destination_bytes == 4096);
    *receipt = answer;
    memset(req->destination, 0x6a, 4096);
    return return_code;
}
#include "xnu_usb_readback.inc"

static bool setup(unsigned type, unsigned request, unsigned value, unsigned index, unsigned length)
{
    bool ok = true; uint32_t n = 99;
    assert(hk_rb_usb_setup(type, request, value, index, length, length < 384 ? length : 384, &ok, &n));
    return ok;
}

int main(void)
{
    bool ok; uint32_t n;
    struct hk_rb_job job = { .generation=1, .lba=999, .lun=0 };
    for (unsigned mode = 0; mode < 4; mode++) {
        hk_rb_mode = mode; hk_rb_started = false; threads = 0;
        if (mode == 1) continue;
        hk_rb_start();
        assert(threads == 0 && reads == 0 && identity_reads == 0);
        assert(!setup(0xc0, HK_RB_INFO, HK_RB_MARKER, 1, HK_RB_HEADER));
    }
    hk_rb_mode = 1; thread_result = 1; hk_rb_start(); assert(!hk_rb_started);
    thread_result = 0; hk_rb_start(); assert(hk_rb_started);
    assert(setup(0xc0, HK_RB_INFO, HK_RB_MARKER, 1, HK_RB_HEADER));
    assert(usb_bytes == HK_RB_HEADER && usb_output[24] == HK_RB_UNAVAILABLE);
    assert(hk_rb_bind(&hk_rb, 0) == 0);
    assert(!hk_rb_usb_setup(0xc0, 0x90, 0, 0, 80, 80, &ok, &n));
    assert(!setup(0x40, HK_RB_INFO, HK_RB_MARKER, 1, HK_RB_HEADER));
    assert(!setup(0xc0, HK_RB_INFO, HK_RB_MARKER, 2, HK_RB_HEADER));
    assert(!setup(0xc0, HK_RB_INFO, HK_RB_MARKER, 1, HK_RB_HEADER-1));
    assert(!setup(0xc0, HK_RB_SELECT, 999, 0, 0));
    assert(!setup(0x40, HK_RB_SELECT, 999, 0, 1));
    assert(!setup(0xc0, HK_RB_DATA, 4096, 0, 384));
    assert(setup(0x40, HK_RB_SELECT, 999, 0, 0));
    assert(!setup(0x40, HK_RB_SELECT, 998, 0, 0));
    assert(reads == 0); /* EP0 setup never calls storage. */
    assert(hk_rb_take(&hk_rb, &job) == 0);
    answer.abi = N882_ABI; answer.dma_state = N882_DMA_RETURNED; answer.opcode = 0x28;
    answer.lun = 0; answer.lba = 999;
    answer.expected_bytes = answer.transferred_bytes = answer.copied_bytes = 4096;
    assert(hk_rb_read(&job) == 0);
    assert(hk_rb_finish(&hk_rb, &job, 0, hk_rb_scratch) == 0);
    assert(setup(0xc0, HK_RB_DATA, 0, 0, 384));
    assert(usb_bytes == 384 && usb_output[80] == 0x6a);
    assert(!setup(0xc0, HK_RB_DATA, 0, 1, 384));
    assert(!setup(0xc0, HK_RB_DATA, 0, 0, HK_RB_HEADER));
    /* Change each device-attested field: none can become exported success. */
#define REJECT(field, bad) do { __typeof__(answer.field) saved = answer.field; answer.field = (bad); \
    assert(hk_rb_read(&job) != 0); answer.field = saved; } while (0)
    REJECT(abi, 0); REJECT(status, -8); REJECT(decode_status, -16);
    REJECT(quarantined, 1); REJECT(dma_state, N882_DMA_RETAINED_CLEARED);
    REJECT(opcode, 0x2a); REJECT(lun, 1); REJECT(lba, 998);
    REJECT(expected_bytes, 0); REJECT(transferred_bytes, 4095);
    REJECT(copied_bytes, 4095); REJECT(residual_raw, 1);
    return_code = -8; assert(hk_rb_read(&job) != 0); return_code = 0;
    unsigned before = reads; now = UINT64_MAX;
    assert(hk_rb_read(&job) != 0 && reads == before);
    puts("actual XNU adapter gates, USB request validation and exact receipt refusal tests PASS");
    return 0;
}
