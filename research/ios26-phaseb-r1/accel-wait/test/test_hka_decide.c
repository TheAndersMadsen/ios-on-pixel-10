/* Host test of hka_decide(): every refusal path and the apply/already/busy predicate states. */
#include <assert.h>
#include <stdio.h>
#include "hka_decide.h"

static struct hka_view good(uint64_t slide)
{
	struct hka_view v = {1, 1, HKA_QC_BASE + slide, slide, UINT64_C(0x8014000000000000) | ((HKA_WAIT_FN + slide) & HKA_PTR_MASK),
	                     HKA_WAIT_FNV, HKA_CREATE_FNV, 0};
	return v;
}

int main(void)
{
	const uint64_t slides[] = {0, 0xbaa4000, 0x141c0000, 0x1f7b4000};
	for (unsigned i = 0; i < 4; ++i) {
		uint64_t s = slides[i];
		struct hka_view v = good(s);
		assert(hka_decide(&v) == HKA_APPLY);
		v.pred = ~UINT64_C(0); assert(hka_decide(&v) == HKA_ALREADY);
		v.pred = 0x16b8f0810; assert(hka_decide(&v) == HKA_BUSY);
		v = good(s); v.have_image = 0; assert(hka_decide(&v) == HKA_NO_IMAGE);
		v = good(s); v.uuid_ok = 0; assert(hka_decide(&v) == HKA_BAD_UUID);
		v = good(s); v.header += 0x4000; assert(hka_decide(&v) == HKA_BAD_HEADER);
		v = good(s); v.block_invoke_raw += 4; assert(hka_decide(&v) == HKA_BAD_BLOCK);
		v = good(s); v.wait_fnv ^= 1; assert(hka_decide(&v) == HKA_BAD_CODE);
		v = good(s); v.create_fnv ^= 1; assert(hka_decide(&v) == HKA_BAD_CODE);
		v = good(s); v.block_invoke_raw = (HKA_WAIT_FN + s); assert(hka_decide(&v) == HKA_APPLY); /* unsigned pointer */
	}
	/* FNV-1a reference vector ("a" -> 0xaf63dc4c8601ec8c). */
	assert(hka_fnv("a", 1) == UINT64_C(0xaf63dc4c8601ec8c));
	printf("PASS hka_decide (4 slides x 10 cases), fnv reference\n");
	return 0;
}
