/* SPDX-License-Identifier: MIT
 * Host test of blazer_aks_wrap.inc with OpenSSL's HMAC-SHA256 standing in for XNU's cchmac.
 * Prints one known-answer blob (fixed secret/key) for test_reference.py to recompute independently. */
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <openssl/hmac.h>
#include <openssl/evp.h>
#include "blazer_aks_wrap.inc"

static int failures;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d %s\n", __FILE__, __LINE__, #c); failures++; } } while (0)

static void
host_hmac(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len, uint8_t out[32])
{
	unsigned int n = 32;

	HMAC(EVP_sha256(), key, (int)key_len, msg, msg_len, out, &n);
}

int
main(void)
{
	uint8_t secret[AW_SECRET], key[64], blob[128], back[64];
	uint32_t blen = 0, klen = 0;
	struct aw_ctx c, other, none;

	for (unsigned i = 0; i < sizeof(secret); i++) {
		secret[i] = (uint8_t)i;
	}
	for (unsigned i = 0; i < sizeof(key); i++) {
		key[i] = (uint8_t)(0xa0 + i);
	}
	memset(&none, 0, sizeof(none));
	CHECK(aw_init(&c, host_hmac, secret) == AW_OK);

	/* the observed shape: 32-byte key, system bag, 128-byte output capacity */
	CHECK(aw_wrap(&c, 0, 3, key, 32, blob, 128, &blen) == AW_OK);
	CHECK(blen == AW_OVERHEAD + 32 && blen <= 128);
	CHECK(blob[0] == 'h' && blob[1] == 'k' && blob[2] == 1 && blob[3] == 32);
	CHECK(memcmp(blob + AW_OVERHEAD, key, 32) != 0);
	printf("KAT class3 key32 ");
	for (uint32_t i = 0; i < blen; i++) {
		printf("%02x", blob[i]);
	}
	printf("\n");
	CHECK(aw_unwrap(&c, 0, 3, blob, blen, back, sizeof(back), &klen) == AW_OK);
	CHECK(klen == 32 && memcmp(back, key, 32) == 0);

	/* deterministic */
	{
		uint8_t again[128];
		uint32_t alen = 0;
		CHECK(aw_wrap(&c, 0, 3, key, 32, again, 128, &alen) == AW_OK && alen == blen && memcmp(again, blob, blen) == 0);
	}
	/* every class id round trips, sign-extended libaks ints and flags beyond the low 5 bits too */
	for (uint64_t cl = 1; cl < 32; cl++) {
		uint64_t with_flags = cl | 0x40000000ull;
		CHECK(aw_wrap(&c, 0, with_flags, key, 32, blob, 128, &blen) == AW_OK);
		CHECK(aw_unwrap(&c, 0, with_flags, blob, blen, back, 64, &klen) == AW_OK && memcmp(back, key, 32) == 0);
		CHECK(aw_unwrap(&c, 0, cl, blob, blen, back, 64, &klen) == AW_AUTH);
	}
	/* key sizes 1..64; 65 refused */
	for (uint32_t n = 1; n <= AW_KEY_MAX; n++) {
		CHECK(aw_wrap(&c, 0, 6, key, n, blob, 128, &blen) == AW_OK && blen == AW_OVERHEAD + n);
		memset(back, 0, sizeof(back));
		CHECK(aw_unwrap(&c, 0, 6, blob, blen, back, 64, &klen) == AW_OK && klen == n && memcmp(back, key, n) == 0);
	}
	CHECK(aw_wrap(&c, 0, 6, key, 65, blob, 128, &blen) == AW_BAD_ARG);
	CHECK(aw_wrap(&c, 0, 6, key, 0, blob, 128, &blen) == AW_BAD_ARG);

	/* refusals */
	CHECK(aw_wrap(&c, 0, 3, key, 32, blob, AW_OVERHEAD + 31, &blen) == AW_NO_SPACE);
	CHECK(aw_wrap(&c, 1, 3, key, 32, blob, 128, &blen) == AW_BAD_HANDLE);
	CHECK(aw_wrap(&c, (uint64_t)-1, 3, key, 32, blob, 128, &blen) == AW_BAD_HANDLE);
	CHECK(aw_wrap(&c, 0, 0, key, 32, blob, 128, &blen) == AW_BAD_CLASS);
	CHECK(aw_wrap(&c, 0, 0x20, key, 32, blob, 128, &blen) == AW_BAD_CLASS);
	CHECK(aw_wrap(&c, 0, 0x100000003ull, key, 32, blob, 128, &blen) == AW_BAD_CLASS);
	CHECK(aw_wrap(&none, 0, 3, key, 32, blob, 128, &blen) == AW_NOT_READY);
	CHECK(aw_unwrap(&none, 0, 3, blob, blen, back, 64, &klen) == AW_NOT_READY);

	/* tamper: every byte of the blob, each bit, must fail (header -> decode, rest -> auth) */
	CHECK(aw_wrap(&c, 0, 3, key, 32, blob, 128, &blen) == AW_OK);
	for (uint32_t i = 0; i < blen; i++) {
		for (int bit = 0; bit < 8; bit++) {
			int st;
			blob[i] ^= (uint8_t)(1u << bit);
			st = aw_unwrap(&c, 0, 3, blob, blen, back, 64, &klen);
			CHECK(st == (i < AW_HDR ? AW_DECODE : AW_AUTH) || (i == 3 && st == AW_DECODE));
			blob[i] ^= (uint8_t)(1u << bit);
		}
	}
	/* wrong handle/class at unwrap, truncated, padded, small output */
	CHECK(aw_unwrap(&c, 0, 4, blob, blen, back, 64, &klen) == AW_AUTH);
	CHECK(aw_unwrap(&c, 1, 3, blob, blen, back, 64, &klen) == AW_BAD_HANDLE);
	CHECK(aw_unwrap(&c, 0, 3, blob, blen - 1, back, 64, &klen) == AW_DECODE);
	CHECK(aw_unwrap(&c, 0, 3, blob, blen + 1, back, 64, &klen) == AW_DECODE);
	CHECK(aw_unwrap(&c, 0, 3, blob, AW_OVERHEAD, back, 64, &klen) == AW_DECODE);
	CHECK(aw_unwrap(&c, 0, 3, blob, blen, back, 31, &klen) == AW_NO_SPACE);
	/* a different secret (the next boot) cannot unwrap */
	secret[0] ^= 1;
	CHECK(aw_init(&other, host_hmac, secret) == AW_OK);
	CHECK(aw_unwrap(&other, 0, 3, blob, blen, back, 64, &klen) == AW_AUTH);
	/* a failed unwrap leaves the output untouched */
	memset(back, 0x5a, sizeof(back));
	CHECK(aw_unwrap(&other, 0, 3, blob, blen, back, 64, &klen) == AW_AUTH);
	for (unsigned i = 0; i < sizeof(back); i++) {
		CHECK(back[i] == 0x5a);
	}
	CHECK(strcmp(aw_status_name(AW_AUTH), "auth") == 0 && strcmp(aw_status_name(99), "?") == 0);

	printf(failures ? "FAILED %d\n" : "PASS\n", failures);
	return failures != 0;
}
