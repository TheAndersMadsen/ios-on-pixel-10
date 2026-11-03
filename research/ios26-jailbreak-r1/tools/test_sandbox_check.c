/* Host test for sweet_sandbox_check.h. Build with tools/test_host.sh (ASan/UBSan). */
#include <stdio.h>
#include <string.h>
#include "sweet_sandbox_check.h"

static int fails, checks;
#define T(c) do { checks++; if (!(c)) { fails++; printf("FAIL line %d: %s\n", __LINE__, #c); } } while (0)

/* Model the kernel plus libsystem_sandbox. Start nonzero to prove every successful call writes an explicit result. */
static int
lib_check(long long pid, const char *op, unsigned long long type, long long self, const char *profile)
{
	unsigned long long result = ~0ULL, dst = 0, answer = 0;
	unsigned long long a[SSC_ARG_WORDS] = { (unsigned long long)&result, (unsigned long long)pid,
		(unsigned long long)op, type };
	if (a[0] == 0) {
		return -1;
	}
	if (ssc_self_query(a, self, &dst) == 0 && ssc_profile_wants_sandbox(profile)) {
		answer = 1;
	}
	memcpy((void *)a[0], &answer, sizeof(answer));
	return result != 0;
}

int
main(void)
{
	/* The special self-query is true for every process that declares an embedded profile. */
	T(lib_check(203, 0, 0, 203, "blastdoor-messages") == 1);
	T(lib_check(203, 0, 0, 203, "blastdoor-imagent") == 1);
	T(lib_check(203, 0, 0, 203, "tccd") == 1);
	T(lib_check(203, 0, 0, 203, "blastdoo") == 1);
	T(lib_check(203, 0, 0, 203, "com.apple.owner.profile") == 1);
	/* No declared profile is truthfully unsandboxed, including owner/ad-hoc code without one. */
	T(lib_check(203, 0, 0, 203, 0) == 0);
	T(lib_check(203, 0, 0, 203, "") == 0);
	/* Real operation checks remain explicitly allowed; only the special self-query can answer one. */
	T(lib_check(204, 0, 0, 203, "blastdoor-messages") == 0);    /* someone else's pid */
	T(lib_check(203, "mach-lookup", 0, 203, "blastdoor-messages") == 0);
	T(lib_check(203, "file-read-data", 0, 203, "tccd") == 0);
	T(lib_check(203, 0, 1, 203, "blastdoor-messages") == 0);    /* a filter */
	T(lib_check(-1, 0, 0, 203, "blastdoor-messages") == 0);
	/* pid is sign-extended (sxtw) in args[1]. */
	{
		unsigned long long r = 0, d = 0, a[4] = { (unsigned long long)&r, (unsigned long long)(long long)-5, 0, 0 };
		T(ssc_self_query(a, -5, &d) == 0 && d == (unsigned long long)&r);
	}
	/* No result pointer: the pure helper refuses it and the kernel model returns EINVAL/-1. */
	{
		unsigned long long d = 7, a[4] = { 0, 203, 0, 0 };
		T(ssc_self_query(a, 203, &d) == -1 && d == 7);
		T((a[0] == 0 ? -1 : 0) == -1);
	}
	printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
