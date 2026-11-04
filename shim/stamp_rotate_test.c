/* Host test of the warm-boot trail rotation in stamp.c (TGL_STAMP_ROTATE_FREE, chooser-ios WARM-r1).
 *
 * Bug class: an installed chooser keeps one stamp nonce across boots and DRAM survives a warm reset. One iOS session
 * (shim + XNU tegu_early on the same ring) fills all 128 slots, so every stamp of the next warm boot was dropped:
 * the trail of the boot that failed was empty. With the gate the trail starts over when fewer than
 * TGL_STAMP_ROTATE_FREE slots are free; a short boot (reset loop) still appends.
 *
 * Build (chooser_ios_image.py runs both):
 *   cc -DTGL_STAMP_HOST -DTGL_STAMP_HOST_CLOCK -DTGL_STAMP_NONCE=0x1122334455667788ULL -DTGL_STAMP_ROTATE_FREE=64 \
 *      stamp.c stamp_rotate_test.c          -> must PASS
 *   the same without -DTGL_STAMP_ROTATE_FREE  -> must FAIL (the cases detect the old behaviour) */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "tgl_stamp.h"

uint64_t tgl_stamp_host_cntvct, tgl_stamp_host_cntfrq = 38400000;

struct hdr { uint64_t magic, nonce; uint32_t count, seq, last_stage, flags; uint64_t freq, t0, tlast; uint32_t dropped, reason; };
struct slot { uint32_t seq; uint16_t stage, flags; uint64_t t, arg; };
static _Alignas(8) uint8_t ring[64 + TGL_STAMP_SLOTS * 24];
static struct hdr *H = (struct hdr *)(void *)ring;
static struct slot *S(unsigned i) { return (struct slot *)(void *)(ring + 64 + 24 * i); }
static int fails, checks;
#define CHECK(c, what) do { checks++; if (!(c)) { fails++; printf("FAIL %s: %s\n", what, #c); } } while (0)

/* A boot of n stamps after entry, then the reason it ended with. */
static void boot(unsigned n, unsigned reason, uint64_t t)
{
	tgl_stamp_host_cntvct = t;
	tgl_stamp_boot_entry();
	for (unsigned i = 0; i < n; i++) { tgl_stamp_host_cntvct += 1000; tgl_stamp(0x00c0u + (i % 9), TGL_STAMP_F_DONE, i); }
	if (reason) tgl_stamp_reason(reason);
}

int main(void)
{
	tgl_stamp_set_sink(ring);
	/* 1. a fresh channel: entry arg 0, count 1 + n */
	memset(ring, 0, sizeof ring);
	boot(20, 0, 1000000);
	CHECK(H->magic == TGL_STAMP_MAGIC && H->count == 21 && S(0)->arg == 0, "fresh channel");
	/* 2. a short re-entry (reset loop) appends: 21 + 1 + 20 = 42 slots, 128 - 42 >= 64 still free before it */
	boot(20, 0, 2000000);
	CHECK(H->count == 42 && S(21)->stage == TGL_STAGE_ENTRY && S(21)->arg == 0, "short re-entry appends");
	/* 3. an iOS-sized session saturates the ring and drops the rest */
	boot(200, TGL_STAMP_R_HANDOFF, 3000000);
	CHECK(H->count == TGL_STAMP_SLOTS && H->dropped > 0, "iOS session saturates");
	uint32_t old_dropped = H->dropped, old_last = H->last_stage, seq_before = H->seq;
	/* 4. the warm boot after it: its own trail exists, starting at slot 0, with the old summary in the entry arg */
	boot(25, 0, 50);	/* counter restarted below the old t0 */
	CHECK(H->count == 26, "warm boot keeps its own 26 stamps");
	CHECK(H->dropped == 0, "dropped reset for the new trail");
	CHECK(S(0)->stage == TGL_STAGE_ENTRY && (S(0)->arg >> 63) == 1, "entry stamp marks the rotation");
	CHECK(((S(0)->arg >> 48) & 0xff) == (TGL_STAMP_SLOTS & 0xff), "entry arg: old count");
	CHECK(((S(0)->arg >> 24) & 0xffffff) == old_dropped, "entry arg: old dropped");
	CHECK(((S(0)->arg >> 8) & 0xffff) == old_last, "entry arg: old last_stage");
	CHECK((S(0)->arg & 0xff) == TGL_STAMP_R_HANDOFF, "entry arg: old reason");
	CHECK(H->reason == TGL_STAMP_R_IN_PROGRESS, "reason re-armed in-progress");
	CHECK(H->t0 == 50, "t0 = this boot");
	CHECK(S(0)->seq == seq_before + 1 && H->seq == seq_before + 26, "seq continues across the rotation");
	CHECK(S(25)->arg == 24 && S(25)->stage == 0x00c0u + 24 % 9, "last stamp of the warm boot is in the ring");
	/* 5. another nonce's residue still re-arms from scratch (unchanged rule), entry arg 0 */
	H->nonce ^= 1;
	boot(3, 0, 70);
	CHECK(H->nonce == TGL_STAMP_NONCE && H->count == 4 && S(0)->arg == 0, "other nonce: fresh header, no rotation mark");
	printf("stamp rotate host test: %d checks, %d failed\n", checks, fails);
	return fails ? 1 : 0;
}
