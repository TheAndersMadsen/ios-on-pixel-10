#!/usr/bin/env python3
"""Apply the op-2 self-check answer to an XNU tree at hk-int1 (484717f): copy sweet_sandbox_check.h, edit sweet_amfi.c.
    python3 -I apply_ssc.py XNU_TREE HEADER
"""
import sys, shutil
from pathlib import Path
x, hdr = Path(sys.argv[1]), sys.argv[2]
shutil.copy2(hdr, x / 'bsd/kern/sweet_sandbox_check.h')
p = x / 'bsd/kern/sweet_amfi.c'
s = p.read_text()
def rep(old, new):
    global s
    assert s.count(old) == 1, old
    s = s.replace(old, new)
rep('#include "sweet_sandbox_issue.h"\n',
    '#include "sweet_sandbox_issue.h"\n#include "sweet_sandbox_check.h"\n#include <IOKit/IOBSD.h>\n')
rep('''static uint64_t sweet_sandbox_seen;
int sweet_sandbox_container_path(user_addr_t arg);   /* sweet_sandbox_container.c */
''', '''static uint64_t sweet_sandbox_seen;
int sweet_sandbox_container_path(user_addr_t arg);   /* sweet_sandbox_container.c */

/*
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
''')
rep('''	switch (call) {
	case 4:         /* container path (audit token / pid) */''', '''	switch (call) {
	case SSC_OP_CHECK:
		sweet_sandbox_check_self(p, arg);
		return 0;
	case 4:         /* container path (audit token / pid) */''')
p.write_text(s)
print('applied')
