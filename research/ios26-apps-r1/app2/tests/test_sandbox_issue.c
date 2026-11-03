/*
 * Host test for sweet_sandbox_issue.h: a model of libsystem_sandbox's issue/consume (as disassembled, see the header)
 * over a fake kernel that copies in the 7 words and copies the token out exactly as sweet_sandbox_syscall does.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sweet_sandbox_issue.h"

static int fails, kernel_calls;
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL %s:%d %s\n", __FILE__, __LINE__, #c); fails++; } } while (0)

/* the kernel side: copyin(arg, a, 56); ssi_issue_target; copyout(ssi_token, dst, sizeof) */
static int
fake_syscall(int op, const unsigned long long *arg)
{
	unsigned long long a[SSI_ARG_WORDS], dst = 0;
	kernel_calls++;
	if (op != SSI_OP_ISSUE) {
		return 2;
	}
	memcpy(a, arg, sizeof(a));
	if (ssi_issue_target(a, &dst) != 0) {
		return 22;
	}
	memcpy((void *)(unsigned long)dst, ssi_token, sizeof(ssi_token));
	return 0;
}

/* libsandbox's issue helper */
static char *
lib_issue(unsigned long long a0, unsigned a1, unsigned long long a2, unsigned flags, int a4, unsigned a5, int nullbuf)
{
	char *buf = malloc(SSI_OUT_CAP);
	if (buf == NULL) {
		return NULL;
	}
	memset(buf, 0xa5, SSI_OUT_CAP);
	if (flags & 1) {
		strncpy(buf, "invalid", SSI_OUT_CAP);
		return buf;
	}
	unsigned long long args[7] = { a0, a1, a2, flags, nullbuf ? 0 : (unsigned long long)(unsigned long)buf, (unsigned long long)(long long)a4, a5 };
	if (fake_syscall(5, args) != 0) {
		free(buf);
		return NULL;
	}
	return buf;
}

/* libsandbox's consume: 0 for the no-op token without a syscall, else op 6 (our kernel: ENOENT -> -1) */
static long long
lib_consume(const char *token)
{
	if (strcmp(token, "invalid") == 0) {
		return 0;
	}
	return fake_syscall(6, NULL) == 0 ? 1 : -1;
}

int
main(void)
{
	CHECK(sizeof(ssi_token) == 8 && sizeof(ssi_token) <= SSI_OUT_CAP && memcmp(ssi_token, "invalid", 8) == 0);

	/* the token lands in word 4's buffer, whatever the other words hold, and consume takes it with no syscall */
	unsigned long long patterns[] = { 0, 1, 0xffffffffffffffffULL, 0x30000ULL };
	for (unsigned i = 0; i < 4; i++) {
		kernel_calls = 0;
		char *t = lib_issue(patterns[i], (unsigned)patterns[i], patterns[i], 0x30000 | (unsigned)(patterns[i] & 6), -1, 7, 0);
		CHECK(t != NULL && kernel_calls == 1);
		if (t) {
			CHECK(strcmp(t, "invalid") == 0);
			CHECK((unsigned char)t[8] == 0xa5);     /* nothing past the NUL is written */
			kernel_calls = 0;
			CHECK(lib_consume(t) == 0 && kernel_calls == 0);
			free(t);
		}
	}
	/* no output buffer: an error, not a write through NULL; libsandbox then returns NULL as before */
	CHECK(lib_issue(0, 0, 0, 0, 0, 0, 1) == NULL);
	unsigned long long a[7] = { 9, 9, 9, 9, 0, 9, 9 }, d = 0x1234;
	CHECK(ssi_issue_target(a, &d) == -1 && d == 0x1234);
	/* every other word is ignored; only word 4 is the target */
	for (unsigned w = 0; w < 7; w++) {
		unsigned long long b[7] = { 0 };
		b[w] = 0x1000 + w;
		int st = ssi_issue_target(b, &d);
		CHECK(w == SSI_OUT_WORD ? (st == 0 && d == 0x1004) : st == -1);
	}
	/* flag bit 0: libsandbox never calls the kernel */
	kernel_calls = 0;
	char *t = lib_issue(0, 0, 0, 1, 0, 0, 0);
	CHECK(t && strcmp(t, "invalid") == 0 && kernel_calls == 0);
	free(t);
	/* a real (non-no-op) token still goes to op 6, which stays ENOENT */
	CHECK(lib_consume("deadbeef;00") == -1);

	if (fails) {
		fprintf(stderr, "%d failures\n", fails);
		return 1;
	}
	printf("PASS test_sandbox_issue\n");
	return 0;
}
