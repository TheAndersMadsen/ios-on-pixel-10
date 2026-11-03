/*
 * hackios: the Sandbox stand-in's answer to extension issue (MIT, original). No XNU types: the host test includes it.
 *
 * libsystem_sandbox (iOS 26 23G90, dsc-r6, the shared issue helper at 0x2a4413ea4 used by sandbox_extension_issue_*):
 *   buf = malloc(0x3ff0);
 *   if (flags & 1) { strlcpy(buf, "invalid", 0x3ff0); return buf; }          no syscall
 *   u64 args[7] = { a0, a1, a2, flags, buf, (s64)a4, a5 };
 *   if (__sandbox_ms("Sandbox", 5, args) != 0) { free(buf); return NULL; }
 *   return buf;                                                               the kernel wrote the token into buf
 * sandbox_extension_consume(token): strcmp(token, "invalid") == 0 -> return 0 with no syscall (op 6 never runs).
 *
 * Without a sandbox there is nothing to extend, so issue answers with libsandbox's own no-op token. Before this, op 5
 * returned ENOENT, every issue returned NULL, and callers without a NULL check (SafariCore
 * WBSSetUpAccessToAppDataContainerWithIdentifier -> sandbox_extension_consume) faulted in strcmp.
 */
#ifndef SWEET_SANDBOX_ISSUE_H
#define SWEET_SANDBOX_ISSUE_H

#define SSI_OP_ISSUE    5
#define SSI_ARG_WORDS   7               /* u64 words libsandbox passes for op 5 */
#define SSI_OUT_WORD    4               /* the caller's output buffer */
#define SSI_OUT_CAP     0x3ff0          /* its size (malloc'd by libsandbox, not passed) */

static const char ssi_token[] = "invalid";      /* with its NUL: 8 bytes */

/* 0 and *dst = where to write ssi_token (sizeof bytes); -1 if the call carries no output buffer. */
static inline int
ssi_issue_target(const unsigned long long args[SSI_ARG_WORDS], unsigned long long *dst)
{
	if (args[SSI_OUT_WORD] == 0) {
		return -1;
	}
	*dst = args[SSI_OUT_WORD];
	return 0;
}

#endif /* SWEET_SANDBOX_ISSUE_H */
