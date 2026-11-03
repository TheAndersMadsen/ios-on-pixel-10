/*
 * hackios: the Sandbox stand-in's answer to "is this process sandboxed?" (MIT, original). No XNU types: the host test includes it.
 *
 * libsystem_sandbox (iOS 26 23G90, dsc-r6): sandbox_check(pid, op, type, ...) fills a struct and calls __sandbox_ms("Sandbox", 2).
 * Its helper initializes a u64 result to zero, passes { &result, (s64)pid, op, filter_type, ... }, and returns result != 0 after a
 * successful syscall. Thus a real operation check is allowed when the kernel leaves result zero. The special op == NULL, type == 0
 * self-query uses the same result to mean "this process is sandboxed"; leaving it zero makes BlastDoor's Sandbox.swift fatalError.
 *
 * A process with a nonempty com.apple.private.sandbox.profile:embedded entitlement has declared a sandbox profile. Answer 1 for its
 * self-query regardless of the profile's name. Owner code without that entitlement remains truthfully unsandboxed. Real operation
 * checks and cross-pid queries keep the permissive stand-in's existing zero result.
 */
#ifndef SWEET_SANDBOX_CHECK_H
#define SWEET_SANDBOX_CHECK_H

#define SSC_OP_CHECK            2
#define SSC_ARG_WORDS           4               /* result pointer, pid, operation, filter type */
#define SSC_PROFILE_ENT         "com.apple.private.sandbox.profile:embedded"

/* 0 and *dst = where to write a u64 1, for a self "am I sandboxed" query; -1 for anything else. */
static inline int
ssc_self_query(const unsigned long long args[SSC_ARG_WORDS], long long self_pid, unsigned long long *dst)
{
	if (args[0] == 0 || args[2] != 0 || args[3] != 0 || (long long)args[1] != self_pid) {
		return -1;
	}
	*dst = args[0];
	return 0;
}

/* A nonempty embedded profile declares a sandbox; NULL and the empty string do not. */
static inline int
ssc_profile_wants_sandbox(const char *profile)
{
	return profile != 0 && profile[0] != 0;
}

#endif /* SWEET_SANDBOX_CHECK_H */
