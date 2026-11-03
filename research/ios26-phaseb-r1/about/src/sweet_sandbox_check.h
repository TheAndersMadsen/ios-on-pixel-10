/*
 * hackios: the Sandbox stand-in's answer to "is this process sandboxed?" (MIT, original). No XNU types: the host test includes it.
 *
 * libsystem_sandbox (iOS 26 23G90, dsc-r6): sandbox_check(pid, op, type, ...) (0x2a4413b70) fills a struct and calls the
 * shared helper 0x2a44138e8, which does
 *   u64 result = 0;  args[0] = &result;  args[1] = (s64)pid;  args[2] = op (NULL stays NULL);  args[3] = filter type;
 *   if (__sandbox_ms("Sandbox", 2, args) != 0) return -1;
 *   return result != 0;
 * So a check reports "denied" (or, with op NULL and type 0, "this pid is sandboxed") only if the kernel writes a nonzero
 * u64 through args[0]. The stand-in never did, so every process looked unsandboxed.
 *
 * BlastDoor/Sandbox.swift (BlastDoor 0x218a63fb4) traps on that at launch: sandbox_check(getpid(), NULL, 0) != 1 ->
 * fatalError("BlastDoor cannot run unsandboxed.") -> brk #1 -> SIGTRAP (MessagesBlastDoorService, int1 boots).
 * Only self-queries with op NULL and type 0, from a process whose embedded profile names blastdoor, get "sandboxed":
 * every other check keeps the old answer.
 */
#ifndef SWEET_SANDBOX_CHECK_H
#define SWEET_SANDBOX_CHECK_H

#define SSC_OP_CHECK            2
#define SSC_ARG_WORDS           4               /* result pointer, pid, operation, filter type */
#define SSC_PROFILE_ENT         "com.apple.private.sandbox.profile:embedded"
#define SSC_PROFILE_PREFIX      "blastdoor"     /* blastdoor-messages, blastdoor-... */
#define SSC_PROFILE_PREFIX_LEN  9

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

/* Does this embedded profile name a BlastDoor sandbox? NULL is no. */
static inline int
ssc_profile_wants_sandbox(const char *profile)
{
	if (profile == 0) {
		return 0;
	}
	for (unsigned i = 0; i < SSC_PROFILE_PREFIX_LEN; i++) {
		if (profile[i] != SSC_PROFILE_PREFIX[i]) {
			return 0;
		}
	}
	return 1;
}

#endif /* SWEET_SANDBOX_CHECK_H */
