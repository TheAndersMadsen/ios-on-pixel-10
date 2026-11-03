/* SPDX-License-Identifier: MIT
 * B2 host test: the candidate blazer_bt_gate.c, the exact kernel file, built with BG_HOST_TEST.
 * Checks the five-entry Broadcom vendor list and its parameter rules, that every other vendor opcode and the
 * firmware/UART opcodes stay local, and that nothing changed for the standard table at levels 0..3.
 *   cc -DBG_HOST_TEST -I<candidate> test_gate_b2.c <candidate>/blazer_bt_gate.c
 */
#include <stdio.h>
#include <string.h>
#include "blazer_bt_gate.h"

static int fails, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

static enum bg_verdict
cmd(uint16_t op, const uint8_t *p, uint8_t plen, int level, uint8_t *rep, uint32_t *rlen, enum bg_why *why)
{
	uint8_t pkt[260];
	uint16_t o;

	pkt[0] = 1; pkt[1] = (uint8_t)op; pkt[2] = (uint8_t)(op >> 8); pkt[3] = plen;
	if (plen) memcpy(pkt + 4, p, plen);
	return bg_check(pkt, 4u + plen, level, rep, rlen, &o, why);
}

static void
expect_local(uint16_t op, const uint8_t *p, uint8_t plen, int level, uint8_t status, enum bg_why w)
{
	uint8_t rep[16];
	uint32_t rlen;
	enum bg_why why;
	enum bg_verdict v = cmd(op, p, plen, level, rep, &rlen, &why);

	CHECK(v == BG_LOCAL, "0x%04x plen %u level %d: verdict %d, want LOCAL", op, plen, level, v);
	CHECK(why == w, "0x%04x: why %d, want %d", op, why, w);
	CHECK(rlen == 7 && rep[0] == 4 && rep[1] == 0x0e && rep[4] == (uint8_t)op && rep[5] == (uint8_t)(op >> 8) && rep[6] == status,
	    "0x%04x: reply %u bytes, status %02x, want complete with %02x", op, rlen, rlen == 7 ? rep[6] : 0xff, status);
}

static void
expect_send(uint16_t op, const uint8_t *p, uint8_t plen, int level)
{
	uint8_t rep[16];
	uint32_t rlen;
	enum bg_why why;
	enum bg_verdict v = cmd(op, p, plen, level, rep, &rlen, &why);

	CHECK(v == BG_SEND && why == BG_WHY_NONE && rlen == 0, "0x%04x plen %u level %d: verdict %d why %d, want SEND", op, plen, level, v, why);
}

int
main(void)
{
	static const uint8_t six[6] = { 1, 2, 3, 4, 5, 6 };
	static const uint8_t baud4m[6] = { 0, 0, 0x00, 0x09, 0x3d, 0x00 };    /* le32 4,000,000 */
	static const uint8_t baud3m[6] = { 0, 0, 0xc0, 0xc6, 0x2d, 0x00 };    /* le32 3,000,000 */
	static const uint8_t baud4m_bad[6] = { 1, 0, 0x00, 0x09, 0x3d, 0x00 };
	uint8_t sleep_off[12] = { 0 }, sleep_on[12] = { 1 };

	for (int level = 0; level <= 3; level++) {
		/* the list */
		expect_send(0xfc01, six, 6, level);
		expect_send(0xfc18, baud4m, 6, level);
		expect_send(0xfc27, sleep_off, 12, level);
		expect_send(0xfc6e, NULL, 0, level);
		expect_send(0xfc79, NULL, 0, level);
		CHECK(bg_level_needed(0xfc01) == 0 && bg_level_needed(0xfc79) == 0, "listed vendor level");
		/* listed, wrong parameters: Command Disallowed, never sent */
		expect_local(0xfc01, six, 5, level, 0x0c, BG_WHY_VPARAM);
		expect_local(0xfc18, baud3m, 6, level, 0x0c, BG_WHY_VPARAM);
		expect_local(0xfc18, baud4m_bad, 6, level, 0x0c, BG_WHY_VPARAM);
		expect_local(0xfc18, baud4m, 5, level, 0x0c, BG_WHY_VPARAM);
		expect_local(0xfc27, sleep_on, 12, level, 0x0c, BG_WHY_VPARAM);
		expect_local(0xfc27, NULL, 0, level, 0x0c, BG_WHY_VPARAM);
		expect_local(0xfc6e, six, 1, level, 0x0c, BG_WHY_VPARAM);
		expect_local(0xfc79, six, 1, level, 0x0c, BG_WHY_VPARAM);
		/* firmware download, launch, UART clock and every other vendor opcode: Unknown, never sent */
		static const uint16_t never[] = { 0xfc2e, 0xfc4c, 0xfc4e, 0xfc45, 0xfc00, 0xfc02, 0xfc1c, 0xfc1e, 0xfc3b, 0xfc5a, 0xfc6d, 0xfd00, 0xffff };
		for (unsigned i = 0; i < sizeof(never) / sizeof(never[0]); i++) {
			expect_local(never[i], NULL, 0, level, 0x01, BG_WHY_VENDOR);
			expect_local(never[i], six, 6, level, 0x01, BG_WHY_VENDOR);
			CHECK(bg_level_needed(never[i]) == BG_LEVEL_MAX + 1, "0x%04x level needed", never[i]);
		}
		/* standard table unchanged: reset and version pass at 0, advertising only at 2, inquiry only at 3, test never */
		expect_send(0x0c03, NULL, 0, level);
		expect_send(0x1001, NULL, 0, level);
		if (level < 2) {
			uint8_t rep[16]; uint32_t rlen; enum bg_why why;
			CHECK(cmd(0x200a, sleep_on, 1, level, rep, &rlen, &why) == BG_LOCAL && why == BG_WHY_LEVEL, "adv enable below 2");
		} else {
			expect_send(0x200a, sleep_on, 1, level);
		}
		if (level < 3) {
			uint8_t rep[16]; uint32_t rlen; enum bg_why why;
			CHECK(cmd(0x0401, six, 5, level, rep, &rlen, &why) == BG_LOCAL && why == BG_WHY_LEVEL && rep[1] == 0x0f, "inquiry below 3: status event");
		}
		expect_local(0x1802, NULL, 0, level, 0x01, BG_WHY_UNSUPPORTED);
		expect_local(0x201e, NULL, 0, level, 0x01, BG_WHY_UNSUPPORTED);
	}
	/* every vendor opcode: only the five can be sent, at any level, with any of a few parameter shapes */
	for (uint32_t ocf = 0; ocf < 0x400; ocf++) {
		uint16_t op = (uint16_t)(0xfc00 | ocf);
		int listed = op == 0xfc01 || op == 0xfc18 || op == 0xfc27 || op == 0xfc6e || op == 0xfc79;
		const uint8_t *shapes[] = { NULL, six, baud4m, sleep_off };
		const uint8_t lens[] = { 0, 6, 6, 12 };

		for (int level = 0; level <= 3; level++) {
			for (unsigned k = 0; k < 4; k++) {
				uint8_t rep[16]; uint32_t rlen; enum bg_why why;
				enum bg_verdict v = cmd(op, shapes[k], lens[k], level, rep, &rlen, &why);

				if (!listed) {
					CHECK(v == BG_LOCAL && why == BG_WHY_VENDOR, "unlisted 0x%04x sent", op);
				} else {
					CHECK(v == BG_SEND || (v == BG_LOCAL && why == BG_WHY_VPARAM), "listed 0x%04x: %d/%d", op, v, why);
				}
			}
		}
	}
	/* out-of-range levels collapse to 0 */
	expect_send(0xfc79, NULL, 0, 7);
	expect_send(0xfc79, NULL, 0, -1);
	printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
