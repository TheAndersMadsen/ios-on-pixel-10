/* HOST: hk_logmirror_fmt.h. cc -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I ../src test_logmirror_fmt.c */
#include <stdio.h>
#include <stdlib.h>
#include "hk_logmirror_fmt.h"

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static const char *
fmt(const char *prog, int pid, const char *line, int cut)
{
	static char out[HKM_LINE_MAX];
	size_t n = strlen(line), at = hkm_message_at(line, n, prog);

	hkm_format(out, prog, pid, line + at, n - at, cut);
	return out;
}

int
main(void)
{
	/* the DT-mode line from app2 qemu-r26 */
	CHECK(strcmp(fmt("tccd", 33, "1969-12-31 16:02:03.933641-0800 tccd[33:730] [access] TCCDMainDatabase created", 0),
	    "HKL tccd[33] [access] TCCDMainDatabase created\n") == 0);
	/* a plain stderr line stays whole */
	CHECK(strcmp(fmt("lsd", 9, "plain words", 0), "HKL lsd[9] plain words\n") == 0);
	/* date but another program's head: only the date goes */
	CHECK(strcmp(fmt("lsd", 9, "2026-11-03 12:00:00.000001+0100 other[1:2] x", 0), "HKL lsd[9] other[1:2] x\n") == 0);
	/* not a pid in the brackets: kept */
	CHECK(strcmp(fmt("lsd", 9, "lsd[abc] y", 0), "HKL lsd[9] lsd[abc] y\n") == 0);
	/* head without the space after it: kept */
	CHECK(strcmp(fmt("lsd", 9, "lsd[1:2]", 0), "HKL lsd[9] lsd[1:2]\n") == 0);
	/* controls become '.', UTF-8 stays, trailing CR/space go, cut marked */
	CHECK(strcmp(fmt("p", 1, "a\x01" "b\xc3\xa6\t c \r", 1), "HKL p[1] a.b\xc3\xa6\t c~\n") == 0);
	/* never longer than the bound */
	{
		char big[2000];
		const char *o;

		memset(big, 'x', sizeof(big) - 1);
		big[sizeof(big) - 1] = 0;
		o = fmt("WirelessRadioManagerd", 123456, big, 0);
		CHECK(strlen(o) == HKM_LINE_MAX - 1 && o[strlen(o) - 1] == '\n' && o[strlen(o) - 2] == '~');
		CHECK(strncmp(o, "HKL WirelessRadioManagerd[123456] xxx", 37) == 0);
	}
	/* empty message after the head */
	CHECK(strcmp(fmt("p", 1, "", 0), "HKL p[1] \n") == 0);
	/* short date-like text is not stripped wrongly */
	CHECK(strcmp(fmt("p", 1, "2026-11-03", 0), "HKL p[1] 2026-11-03\n") == 0);
	/* parse */
	{
		uint32_t r = 99, b = 99;

		CHECK(hkm_parse(NULL, &r, &b) == 0 && hkm_parse("", &r, &b) == 0 && hkm_parse("0", &r, &b) == 0);
		CHECK(hkm_parse("1", &r, &b) == 1 && r == HKM_RATE && b == HKM_BURST);
		CHECK(hkm_parse("20", &r, &b) == 1 && r == 20 && b == HKM_BURST);
		CHECK(hkm_parse("20,200", &r, &b) == 1 && r == 20 && b == 200);
		CHECK(hkm_parse("00", &r, &b) == 1 && r == 0);          /* on, no per-program limit */
		CHECK(hkm_parse("5000", &r, &b) == 1 && r == HKM_RATE);  /* out of bounds: defaults */
		CHECK(hkm_parse("x", &r, &b) == 1 && r == HKM_RATE && b == HKM_BURST);
		CHECK(hkm_parse("4,0", &r, &b) == 1 && r == HKM_RATE && b == HKM_BURST);
		CHECK(hkm_parse("4,9x", &r, &b) == 1 && r == HKM_RATE);
	}
	/* bucket: burst, then rate; idle refills only to the burst */
	{
		struct hkm_bucket k = { .rate = 8, .burst = 64 };
		unsigned n = 0;

		for (int i = 0; i < 1000; i++) {
			n += hkm_take(&k, 1000000);
		}
		CHECK(n == 64);
		n = 0;
		for (uint64_t us = 1000000; us <= 11000000; us += 1000) {      /* 10 s, a line every ms */
			n += hkm_take(&k, us);
		}
		CHECK(n >= 79 && n <= 81);
		n = 0;
		for (int i = 0; i < 1000; i++) {
			n += hkm_take(&k, 1000000000);
		}
		CHECK(n == 64);
	}
	printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
