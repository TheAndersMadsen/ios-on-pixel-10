#!/usr/bin/env python3
"""Apply stable op-2 semantics to ABOUT's hk-int2-about worktree, or refine the first jb1 revision.

Usage: python3 -I apply_sandbox.py XNU_WORKTREE sweet_sandbox_check.h
"""
from pathlib import Path
import shutil
import sys

x, hdr = Path(sys.argv[1]), Path(sys.argv[2])
shutil.copyfile(hdr, x / "bsd/kern/sweet_sandbox_check.h")
p = x / "bsd/kern/sweet_amfi.c"
s = p.read_text()

OLD_ABOUT = '''/*
 * Op 2, sandbox_check: "is this process sandboxed?" (op NULL, type 0, its own pid) from a process whose embedded profile
 * names blastdoor answers yes, so BlastDoor's launch check passes (sweet_sandbox_check.h). Everything else stays 0.
 */
static unsigned int sweet_sandbox_self_logged;

static void
sweet_sandbox_check_self(struct proc *p, user_addr_t arg)
{
	unsigned long long a[SSC_ARG_WORDS], dst = 0, one = 1;
	char *profile;
	int yes;

	if (copyin(arg, a, sizeof(a)) != 0 || ssc_self_query(a, (long long)proc_pid(p), &dst) != 0) {
		return;
	}
	profile = IOCurrentTaskGetEntitlement(SSC_PROFILE_ENT);
	yes = ssc_profile_wants_sandbox(profile);
	if (yes && copyout(&one, (user_addr_t)dst, sizeof(one)) != 0) {
		yes = 0;
	}
	if (yes && sweet_sandbox_self_logged < 16) {
		char name[32];

		sweet_sandbox_self_logged++;
		proc_name(proc_pid(p), name, sizeof(name));
		printf("SWEET Sandbox: %s[%d] self-check: sandboxed (profile %s)\\n", name, proc_pid(p), profile);
	}
	if (profile != NULL) {
		kfree_data(profile, strlen(profile) + 1);
	}
}
'''

OLD_GENERALIZED = '''/*
 * Op 2 has two meanings in libsystem_sandbox. A real operation check is allowed by leaving its pre-zeroed result alone.
 * The op NULL, type 0, own-pid query instead asks "am I sandboxed?": answer yes when the main binary declares any nonempty
 * embedded sandbox profile. This is the semantic distinction, not a BlastDoor filename exception. Other pids and real
 * operations retain the permissive stand-in's existing answer. Bad user pointers are syscall errors, never an implicit allow.
 */
static unsigned int sweet_sandbox_self_logged;

static int
sweet_sandbox_check_self(struct proc *p, user_addr_t arg)
{
	unsigned long long a[SSC_ARG_WORDS], dst = 0, one = 1;
	char *profile;
	int error, yes;

	error = copyin(arg, a, sizeof(a));
	if (error != 0) {
		return error;
	}
	if (ssc_self_query(a, (long long)proc_pid(p), &dst) != 0) {
		return 0;
	}
	profile = IOCurrentTaskGetEntitlement(SSC_PROFILE_ENT);
	yes = ssc_profile_wants_sandbox(profile);
	if (yes) {
		error = copyout(&one, (user_addr_t)dst, sizeof(one));
	}
	if (error == 0 && yes && sweet_sandbox_self_logged < 64) {
		char name[32];

		sweet_sandbox_self_logged++;
		proc_name(proc_pid(p), name, sizeof(name));
		printf("SWEET Sandbox: %s[%d] self-check: sandboxed (profile %s)\\n", name, proc_pid(p), profile);
	}
	if (profile != NULL) {
		kfree_data(profile, strlen(profile) + 1);
	}
	return error;
}
'''

NEW = '''/*
 * Op 2 has two meanings in libsystem_sandbox. A real operation check writes an explicit zero (allowed). The op NULL,
 * type 0, own-pid query instead asks "am I sandboxed?": write one when the main binary declares any nonempty embedded
 * sandbox profile, zero otherwise. This is the ABI distinction, not a BlastDoor filename exception. Cross-pid queries
 * retain the permissive zero answer. Every successful call writes its result; bad user pointers are errors, never allow.
 */
static unsigned int sweet_sandbox_self_logged;

static int
sweet_sandbox_check_self(struct proc *p, user_addr_t arg)
{
	unsigned long long a[SSC_ARG_WORDS], dst = 0, answer = 0;
	int error, self;

	error = copyin(arg, a, sizeof(a));
	if (error != 0) {
		return error;
	}
	if (a[0] == 0) {
		return EINVAL;
	}
	self = ssc_self_query(a, (long long)proc_pid(p), &dst) == 0;
	if (self) {
		char *profile = IOCurrentTaskGetEntitlement(SSC_PROFILE_ENT);

		answer = ssc_profile_wants_sandbox(profile) ? 1 : 0;
		if (profile != NULL) {
			kfree_data(profile, strlen(profile) + 1);
		}
	}
	error = copyout(&answer, (user_addr_t)a[0], sizeof(answer));
	if (error == 0 && self && answer != 0 && sweet_sandbox_self_logged < 64) {
		char name[32];

		sweet_sandbox_self_logged++;
		proc_name(proc_pid(p), name, sizeof(name));
		printf("SWEET Sandbox: %s[%d] self-check: sandboxed\\n", name, proc_pid(p));
	}
	return error;
}
'''

if s.count(OLD_ABOUT) == 1:
    s = s.replace(OLD_ABOUT, NEW)
elif s.count(OLD_GENERALIZED) == 1:
    s = s.replace(OLD_GENERALIZED, NEW)
elif s.count(NEW) != 1:
    raise SystemExit("no recognized sandbox_check implementation")

old_call = '''	case SSC_OP_CHECK:
		sweet_sandbox_check_self(p, arg);
		return 0;
'''
new_call = '''	case SSC_OP_CHECK:
		return sweet_sandbox_check_self(p, arg);
'''
if old_call in s:
    assert s.count(old_call) == 1
    s = s.replace(old_call, new_call)
assert s.count(new_call) == 1

old_bool = '''			user_addr_t out[2];
			uint64_t zero = 0;
'''
new_bool = '''			user_addr_t out[2];
			uint8_t zero = 0;
'''
if old_bool in s:
    assert s.count(old_bool) == 1
    s = s.replace(old_bool, new_bool)
assert s.count(new_bool) == 1
p.write_text(s)
print("applied stable sandbox_check semantics and bool-width container outputs")
