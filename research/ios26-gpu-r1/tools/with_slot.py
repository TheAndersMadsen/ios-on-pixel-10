#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Mac only. Take the fleet's kernel build slot (/tmp/fleet/kernel-build-slot.lock) without waiting, then exec the command with the
locked fd inherited, so the slot is held until the command exits. Busy slot (another owner building): exit 75, nothing run."""
import fcntl, os, sys
fd = os.open('/tmp/fleet/kernel-build-slot.lock', os.O_RDWR | os.O_CREAT, 0o644)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    print('STOP: kernel build slot busy', file=sys.stderr)
    sys.exit(75)
os.set_inheritable(fd, True)
os.environ['HK_SLOT_HELD'] = '1'
os.execvp(sys.argv[1], sys.argv[1:])
