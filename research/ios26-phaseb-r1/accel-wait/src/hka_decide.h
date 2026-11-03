/* hk_accel_once: decision logic, no OS types (host-testable). MIT, hackios.
 *
 * QuartzCore (dyld cache 0f1ee332, QuartzCore UUID 8f1e0b3f...) creates its Metal device in a function at unslid
 * 0x184215998 that first runs dispatch_once(&pred@0x1e9ccc3d0, block@0x1ee991a20). The block (invoke 0x184215a0c)
 * polls IOServiceGetMatchingServices(IOServiceMatching("IOAcceleratorES")) 301 times with usleep(100000) between
 * tries and discards the result. Completing that once predicate before QuartzCore uses it skips the wait only.
 */
#ifndef HKA_DECIDE_H
#define HKA_DECIDE_H
#include <stdint.h>

#define HKA_QC_BASE        UINT64_C(0x183ed3000)   /* QuartzCore mach header, unslid */
#define HKA_PRED           UINT64_C(0x1e9ccc3d0)   /* QuartzCore __DATA,__bss dispatch_once_t */
#define HKA_BLOCK_INVOKE_P UINT64_C(0x1ee991a30)   /* __AUTH_CONST global block literal + 0x10 (invoke) */
#define HKA_WAIT_FN        UINT64_C(0x184215a0c)   /* block invoke: the poll loop */
#define HKA_WAIT_LEN       0xe8u
#define HKA_WAIT_FNV       UINT64_C(0xfb4e10f62002b5fb)
#define HKA_CREATE_FN      UINT64_C(0x184215998)   /* once + MTLCreateSystemDefaultDevice */
#define HKA_CREATE_LEN     0x74u
#define HKA_CREATE_FNV     UINT64_C(0xe36463c047268227)
#define HKA_PTR_MASK       UINT64_C(0x0000007fffffffff) /* same arithmetic strip as runtime/ca_sampler hs_hook.c */

static const uint8_t hka_qc_uuid[16] = {0x8f,0x1e,0x0b,0x3f,0xad,0xd6,0x37,0x10,0xa7,0x90,0x00,0x93,0x33,0x59,0x7a,0xb4};

enum hka_verdict {
	HKA_APPLY = 0,      /* all checks pass, predicate 0: complete it */
	HKA_ALREADY,        /* predicate already done (~0): nothing to do */
	HKA_BUSY,           /* predicate neither 0 nor ~0: someone is inside the once; untouched */
	HKA_NO_IMAGE,       /* QuartzCore not loaded */
	HKA_BAD_UUID,
	HKA_BAD_HEADER,     /* header address != base + slide */
	HKA_BAD_BLOCK,      /* block literal does not point at the wait function */
	HKA_BAD_CODE,       /* fingerprint of either function differs */
};

static inline uint64_t hka_fnv(const void *p, uint32_t n)
{
	const uint8_t *b = (const uint8_t *)p; uint64_t h = UINT64_C(0xcbf29ce484222325);
	for (uint32_t i = 0; i < n; ++i) h = (h ^ b[i]) * UINT64_C(0x100000001b3);
	return h;
}

struct hka_view {
	int have_image;
	int uuid_ok;
	uint64_t header, slide;
	uint64_t block_invoke_raw;     /* *(u64 *)(HKA_BLOCK_INVOKE_P + slide) */
	uint64_t wait_fnv, create_fnv; /* fingerprints of the code at + slide */
	uint64_t pred;                 /* *(u64 *)(HKA_PRED + slide) */
};

static inline enum hka_verdict hka_decide(const struct hka_view *v)
{
	if (!v->have_image) return HKA_NO_IMAGE;
	if (!v->uuid_ok) return HKA_BAD_UUID;
	if (v->header != HKA_QC_BASE + v->slide) return HKA_BAD_HEADER;
	if ((v->block_invoke_raw & HKA_PTR_MASK) != ((HKA_WAIT_FN + v->slide) & HKA_PTR_MASK)) return HKA_BAD_BLOCK;
	if (v->wait_fnv != HKA_WAIT_FNV || v->create_fnv != HKA_CREATE_FNV) return HKA_BAD_CODE;
	if (v->pred == ~UINT64_C(0)) return HKA_ALREADY;
	if (v->pred != 0) return HKA_BUSY;
	return HKA_APPLY;
}

static inline const char *hka_name(enum hka_verdict d)
{
	static const char *const n[] = {"apply", "already", "busy", "no-image", "bad-uuid", "bad-header", "bad-block", "bad-code"};
	return (unsigned)d < sizeof n / sizeof n[0] ? n[d] : "?";
}
#endif
