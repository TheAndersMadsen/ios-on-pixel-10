#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""HOST ONLY. The B2 overlay, on top of a7-ios-system-r10-perf's perf-r1.ovl (95701ed9...). Two records change, every other
record stays byte-identical (codec: ios26-overlay-r1/tools/mkoverlay.py pack/fnv1a/deny_ok/env_ok, second walker:
ios26-overlay2-r1/tools/restore_cloudd.py decode):

  [42] group-31 hk_deny  'bluetoothd,Spotlight' -> 'Spotlight'   (bluetoothd runs; Spotlight stays refused, perf/FIX.md 2)
  [39] group-29 hk_env   + ',bluetoothd:BT_HCI_TRANSPORT=H4:POSIX;BT_CHIP=ACI~BT'   (PLAN.md 2; '~' is a space in a value)

Optional extra rules for later variants (each one more variable): --env 'PROG:KEY=VAL;...' appends a rule for a program that
has none yet, --file GROUP:MODE:UID:GID:PATH:SRC appends a file.

    bt2_overlay.py BASE.ovl OUT.ovl [--env RULE]... [--file SPEC]...     (refuses to overwrite OUT; prints a JSON report)
"""
import argparse
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[5]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MK = load('mkoverlay', 'research/ios26-overlay-r1/tools/mkoverlay.py')
RC = load('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
sha = lambda b: hashlib.sha256(b).hexdigest()

BASE_SHA = '95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55'  # perf-r1.ovl, r10-perf's overlay
MASK = 0xA0080081
DENY_BEFORE, DENY_AFTER = 'bluetoothd,Spotlight', 'Spotlight'
BT_RULE = 'bluetoothd:BT_HCI_TRANSPORT=H4:POSIX;BT_CHIP=ACI~BT'


def active(r):
    return MASK >> r[1] & 1


def progs(rule):
    return rule.split(':', 1)[0].split('+')


def transform(blob, extra_env=(), extra_files=()):
    if sha(blob) != BASE_SHA:
        raise ValueError('base is not perf-r1.ovl 95701ed9')
    rows = RC.decode(blob)
    out = {}
    deny = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_deny' and active(r)]
    if deny != [42] or rows[42][6] != DENY_BEFORE.encode() or rows[42][1] != 31:
        raise ValueError('expected one active hk_deny (record 42, group 31) = bluetoothd,Spotlight')
    k, g, m, u, gi, p, _, _ = rows[42]
    MK.deny_ok(DENY_AFTER)
    out[42] = MK.pack(chr(k), g, m, u, gi, p, DENY_AFTER.encode())

    envs = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_env' and active(r)]
    if envs != [39] or rows[39][1] != 29:
        raise ValueError('expected one active hk_env (record 39, group 29)')
    k, g, m, u, gi, p, data, _ = rows[39]
    old = data.decode('ascii')
    MK.env_ok(old)
    have = {q for r in old.split(',') for q in progs(r)}
    added = [BT_RULE, *extra_env]
    for r in added:
        MK.env_ok(r)
        if have & set(progs(r)):
            raise ValueError(f'{progs(r)} already has a rule')
        have |= set(progs(r))
    new = ','.join([old, *added])
    MK.env_ok(new)
    if len(new.encode()) + 1 > 1024 or max(len(v) for r in new.split(',') for v in r.split(':', 1)[1].split(';')) + 1 > 384:
        raise ValueError('hk_env kernel bound (HK_RULES_MAX 1024, HK_VAR_MAX 384)')
    out[39] = MK.pack(chr(k), g, m, u, gi, p, new.encode())

    appended = []
    for spec in extra_files:
        grp, mode, uid, gid, path, src = spec.split(':', 5)
        if any(r[5] == path for r in rows):
            raise ValueError(f'{path} already in the overlay')
        data_f = Path(src).read_bytes()
        appended.append((int(grp), int(mode, 8), int(uid), int(gid), path, data_f))
    extra = [MK.pack('f', *a) for a in appended]
    body = b''.join(out.get(i, r[7]) for i, r in enumerate(rows)) + b''.join(extra)
    result = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows) + len(extra), MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX:
        raise ValueError('too large')

    back = RC.decode(result)
    assert len(back) == len(rows) + len(extra)
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, back)) if i not in out)
    assert all(a[:6] == b[:6] for i, (a, b) in enumerate(zip(rows, back)) if i in out)
    assert back[42][6] == DENY_AFTER.encode()
    assert back[39][6].decode().split(',')[:len(old.split(','))] == old.split(',')
    assert [r for r in back if r[0] == ord('c') and r[5] == 'hk_deny' and active(r) and b'bluetoothd' in r[6].split(b',')] == []
    for a, b in zip(appended, back[len(rows):]):
        assert b[1:5] == a[:4] and b[5] == a[4] and b[6] == a[5]
    return result, {
        'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'records': len(back), 'mask': hex(MASK),
        'replaced': {'42 hk_deny (group 31)': f'{DENY_BEFORE} -> {DENY_AFTER}',
                     '39 hk_env (group 29)': {'added_rules': added, 'bytes_with_NUL': len(new) + 1}},
        'appended': {a[4]: {'group': a[0], 'mode': oct(a[1]), 'uid': a[2], 'gid': a[3], 'sha256': sha(a[5]), 'bytes': len(a[5])} for a in appended},
        'other_records_byte_identical': len(rows) - len(out)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--env', action='append', default=[])
    ap.add_argument('--file', action='append', default=[])
    a = ap.parse_args()
    result, report = transform(a.base.read_bytes(), a.env, a.file)
    with a.output.open('xb') as f:
        f.write(result)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
