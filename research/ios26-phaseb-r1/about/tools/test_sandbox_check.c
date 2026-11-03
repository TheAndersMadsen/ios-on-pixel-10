/* Host test for sweet_sandbox_check.h: cc -I../src -fsanitize=address,undefined test_sandbox_check.c && ./a.out */
#include <stdio.h>
#include <string.h>
#include "sweet_sandbox_check.h"

static int fails, checks;
#define T(c) do { checks++; if (!(c)) { fails++; printf("FAIL line %d: %s\n", __LINE__, #c); } } while (0)

/* What libsandbox's sandbox_check does with the answer (0x2a4413afc..0x2a4413b10): result != 0. */
static int
lib_check(long long pid, const char *op, unsigned long long type, long long self, const char *profile)
{
	unsigned long long result = 0, dst = 0;
	unsigned long long a[SSC_ARG_WORDS] = { (unsigned long long)&result, (unsigned long long)pid,
		(unsigned long long)op, type };
	if (ssc_self_query(a, self, &dst) == 0 && ssc_profile_wants_sandbox(profile)) {
		unsigned long long one = 1;
		memcpy((void *)dst, &one, sizeof(one));
	}
	return result != 0;
}

int
main(void)
{
	/* BlastDoor's own launch check: sandbox_check(getpid(), NULL, 0) == 1 */
	T(lib_check(203, 0, 0, 203, "blastdoor-messages") == 1);
	T(lib_check(203, 0, 0, 203, "blastdoor-imagent") == 1);
	/* every other shape keeps the old "allowed / not sandboxed" */
	T(lib_check(203, 0, 0, 203, 0) == 0);                       /* no embedded profile */
	T(lib_check(203, 0, 0, 203, "tccd") == 0);                  /* another profile */
	T(lib_check(203, 0, 0, 203, "blastdoo") == 0);              /* prefix must be whole */
	T(lib_check(204, 0, 0, 203, "blastdoor-messages") == 0);    /* someone else's pid */
	T(lib_check(203, "mach-lookup", 0, 203, "blastdoor-messages") == 0);    /* a real operation */
	T(lib_check(203, 0, 1, 203, "blastdoor-messages") == 0);    /* a filter */
	T(lib_check(-1, 0, 0, 203, "blastdoor-messages") == 0);
	/* pid is sign-extended (sxtw) in args[1] */
	{
		unsigned long long r = 0, d = 0, a[4] = { (unsigned long long)&r, (unsigned long long)(long long)-5, 0, 0 };
		T(ssc_self_query(a, -5, &d) == 0 && d == (unsigned long long)&r);
	}
	/* no result pointer: nothing to write */
	{
		unsigned long long d = 7, a[4] = { 0, 203, 0, 0 };
		T(ssc_self_query(a, 203, &d) == -1 && d == 7);
	}
	printf("%s: %d checks, %d failed\n", fails ? "FAIL" : "PASS", checks, fails);
	return fails != 0;
}
