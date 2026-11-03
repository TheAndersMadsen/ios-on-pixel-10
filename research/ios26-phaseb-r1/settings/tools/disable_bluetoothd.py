#!/usr/bin/env python3
"""HOST ONLY. One overlay change for a7-ios-system-r8-settings: add com.apple.bluetoothd to launchd's disabled set.

Base: the r7-touch overlay (artwork-container-battery-observe-accel-skip-r1.ovl, f5d4c367...). Under hk_overlay=0xA0080081
the active /private/var/db/com.apple.xpc.launchd/disabled.plist is the group-7 record (159 labels, all True). bluetoothd
is not in it; it is refused at exec instead (group-31 hk_deny, EBADARCH). That keeps the job loaded: launchd registers its
15 MachServices, the spawn fails, the job goes to the penalty box, and a client's lookup still SUCCEEDS, so a message to
com.apple.server.bluetooth* is queued with no receiver and a reply-sync caller waits for ever. Labels in the disabled set are
not loaded; their lookups fail at once (launchd 'failed lookup ... error = 3'), as every other service Settings asks for
in the r7 log does. This moves bluetoothd into that set. Every other record stays byte-identical, hk_deny included.

    disable_bluetoothd.py BASE.ovl OUT.ovl      (refuses to overwrite OUT; prints a JSON report)

Decoder: research/ios26-overlay2-r1/tools/restore_cloudd.py decode() (the same walker its transform used).
"""
import argparse
import hashlib
import importlib.util
import json
import plistlib
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('rc', REPO / 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
RC = importlib.util.module_from_spec(spec); spec.loader.exec_module(RC)

BASE_SHA = 'f5d4c3676d1cf78c1b21036b784819d66425ce6bb55c27a46eee17f277412a97'
DISABLED = '/private/var/db/com.apple.xpc.launchd/disabled.plist'
LABEL = 'com.apple.bluetoothd'
MASK = 0xA0080081
GROUP = 7
sha = lambda b: hashlib.sha256(b).hexdigest()


def transform(blob):
    if sha(blob) != BASE_SHA:
        raise ValueError('base is not the r7-touch overlay f5d4c367')
    rows = RC.decode(blob)
    active = [i for i, r in enumerate(rows) if r[5] == DISABLED and MASK >> r[1] & 1]
    if active != [i for i, r in enumerate(rows) if r[5] == DISABLED and r[1] == GROUP] or len(active) != 1:
        raise ValueError('expected exactly one active disabled.plist record, in group 7')
    index = active[0]
    kind, bit, mode, uid, gid, path, data, _ = rows[index]
    if (kind, mode, uid, gid) != (ord('f'), 0o644, 0, 0):
        raise ValueError('unsafe plist metadata')
    before = plistlib.loads(data)
    if len(before) != 159 or LABEL in before or not all(v is True for v in before.values()):
        raise ValueError('unexpected disabled set')
    deny = [r[6] for r in rows if r[0] == ord('c') and r[5] == 'hk_deny' and MASK >> r[1] & 1]
    if deny != [b'bluetoothd']:
        raise ValueError('unexpected hk_deny rows')
    after = dict(before); after[LABEL] = True
    payload = plistlib.dumps(after, fmt=plistlib.FMT_XML, sort_keys=True)
    pb = path.encode()
    entry = struct.pack('<BB2xIIIII', kind, bit, mode, uid, gid, len(pb), len(payload)) + pb + b'\0'
    entry += b'\0' * (-len(entry) & 7)
    entry += payload
    entry += b'\0' * (-len(entry) & 7)
    body = b''.join(entry if i == index else r[7] for i, r in enumerate(rows))
    result = b'HKVAROV1' + struct.pack('<IIQ', len(body) + 24, len(rows), RC.fnv(body)) + body
    out = RC.decode(result)  # independent postconditions
    assert len(out) == len(rows)
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, out)) if i != index)
    got = plistlib.loads(out[index][6])
    assert got == after and set(got) - set(before) == {LABEL} and len(got) == 160
    return result, {'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'entries': len(rows),
                    'changed_entry': index, 'group_bit': GROUP, 'mask': hex(MASK), 'added_to_disabled': [LABEL],
                    'disabled_before': len(before), 'disabled_after': len(got), 'plist_bytes': [len(data), len(payload)],
                    'hk_deny_unchanged': deny[0].decode(), 'other_records_byte_identical': len(rows) - 1}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('base', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    result, report = transform(a.base.read_bytes())
    with a.output.open('xb') as f:
        f.write(result)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
