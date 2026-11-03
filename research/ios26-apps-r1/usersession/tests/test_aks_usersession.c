/* Host test for blazer_aks_usersession.inc (aks-wrap test style: asserts, ASan/UBSan, exit 0 = PASS). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "blazer_aks_usersession.inc"

static int fails;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

static int
run(unsigned sel, unsigned nin, unsigned long long a0, unsigned slen, const unsigned char *s, unsigned ocap, unsigned scap, struct aus_result *r)
{
	unsigned long long in[3] = { a0, 0, 0 };
	struct aus_call c = { sel, nin, in, slen, ocap, scap };
	memset(r, 0xa5, sizeof(*r));
	return aus_call(&c, s, r);
}

int
main(void)
{
	struct aus_result r;
	unsigned char bag[AUS_BAG_LEN], der[4] = { 0x30, 0x02, 0x04, 0x00 };
	unsigned sel;

	/* not ours: untouched answer, zero outputs */
	for (sel = 0; sel < 200; sel++) {
		int st = run(sel, 1, 0, 0, NULL, 1, 64, &r);
		if (!aus_is_selector(sel)) {
			CHECK(st == AUS_UNHANDLED && r.scalars_out == 0 && r.struct_out_len == 0);
		}
	}
	CHECK(run(10, 2, 0, 32, bag, 1, 128, &r) == AUS_UNHANDLED);   /* wrap stays with aks-wrap */
	CHECK(run(125, 0, 0, 0, NULL, 1, 64, &r) == AUS_UNHANDLED);   /* AKSIdentityGetPrimary: identity, not ours */

	/* create -> save -> load round trip */
	CHECK(run(2, 2, 0, 0, NULL, 1, 0, &r) == AUS_OK && r.scalars_out == 1 && r.scalar_out[0] == AUS_USER_HANDLE);
	CHECK(run(2, 2, 0, 0, NULL, 0, 0, &r) == AUS_BAD_ARG && r.scalars_out == 0);
	CHECK(run(3, 1, AUS_USER_HANDLE, 0, NULL, 0, 0x8000, &r) == AUS_OK && r.struct_out_len == AUS_BAG_LEN);
	memcpy(bag, r.struct_out, AUS_BAG_LEN);
	CHECK(memcmp(bag, "HKUSBAG1", 8) == 0 && bag[8] == AUS_USER_HANDLE);
	CHECK(run(3, 1, 0, 0, NULL, 0, 0x8000, &r) == AUS_BAD_ARG);           /* system bag is not saved here */
	CHECK(run(3, 1, AUS_USER_HANDLE, 0, NULL, 0, AUS_BAG_LEN - 1, &r) == AUS_NO_SPACE && r.struct_out_len == 0);
	CHECK(run(6, 0, 0, AUS_BAG_LEN, bag, 1, 0, &r) == AUS_OK && r.scalar_out[0] == AUS_USER_HANDLE && r.scalars_out == 1);
	/* load refuses anything else: every single-bit change, wrong length, no output slot */
	for (unsigned i = 0; i < AUS_BAG_LEN * 8; i++) {
		unsigned char t[AUS_BAG_LEN];
		memcpy(t, bag, sizeof(t)); t[i / 8] ^= (unsigned char)(1u << (i % 8));
		CHECK(run(6, 0, 0, AUS_BAG_LEN, t, 1, 0, &r) == AUS_BAD_ARG && r.scalars_out == 0);
	}
	CHECK(run(6, 0, 0, AUS_BAG_LEN - 1, bag, 1, 0, &r) == AUS_BAD_ARG);
	CHECK(run(6, 0, 0, AUS_BAG_LEN, NULL, 1, 0, &r) == AUS_BAD_ARG);
	CHECK(run(6, 0, 0, AUS_BAG_LEN, bag, 0, 0, &r) == AUS_BAD_ARG);

	/* persona keys */
	CHECK(run(96, 3, AUS_USER_HANDLE, sizeof(der), der, 0, 0, &r) == AUS_OK && r.scalars_out == 0 && r.struct_out_len == 0);
	CHECK(run(117, 3, AUS_USER_HANDLE, sizeof(der), der, 0, 0, &r) == AUS_OK);
	CHECK(run(96, 3, AUS_USER_HANDLE, 0, NULL, 0, 0, &r) == AUS_BAD_ARG);
	CHECK(run(96, 0, 0, sizeof(der), der, 0, 0, &r) == AUS_BAD_ARG);
	CHECK(run(97, 1, AUS_USER_HANDLE, 0, NULL, 0, 0x2000, &r) == AUS_OK && r.struct_out_len == 2 && r.struct_out[0] == 0x30 && r.struct_out[1] == 0);
	CHECK(run(97, 1, AUS_USER_HANDLE, 0, NULL, 0, 1, &r) == AUS_NO_SPACE && r.struct_out_len == 0);
	CHECK(run(97, 0, 0, 0, NULL, 0, 0x2000, &r) == AUS_BAD_ARG);
	CHECK(run(98, 3, AUS_USER_HANDLE, sizeof(der), der, 0, 0, &r) == AUS_OK);
	CHECK(run(65, 2, AUS_USER_HANDLE, sizeof(der), der, 0, 0, &r) == AUS_OK);
	CHECK(run(65, 0, 0, 0, NULL, 0, 0, &r) == AUS_BAD_ARG);
	CHECK(strcmp(aus_status_name(AUS_NO_SPACE), "no space") == 0);

	if (fails) { fprintf(stderr, "%d failures\n", fails); return 1; }
	puts("PASS test_aks_usersession");
	return 0;
}
