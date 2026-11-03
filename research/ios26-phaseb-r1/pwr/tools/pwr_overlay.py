#!/usr/bin/env python3
"""HOST ONLY. The overlay for a7-ios-system-pwr1, on top of perf-r1.ovl (95701ed9..., a7-ios-system-r10-perf's).

Two changes, every other record byte-identical (codec: ios26-overlay-r1/tools/mkoverlay.py pack/fnv1a,
second walker: ios26-overlay2-r1/tools/restore_cloudd.py decode):

1. [0] group-0 com.apple.springboard.plist: SBDontLockEver removed, every other key and value unchanged
   (binary plist, as the base). With it, SpringBoard never locks, so the side button cannot show the lock
   screen (opt-buttons_integration.md, "Power UI follow-up is HELD"). SBAutoLockTime -1, SBDisableIdleSleep and
   SBDontDimOrLockOnAC stay, so nothing locks by itself: only the side button does.
2. Appended (group 0, l 0755 root:root, the seed's own mode and owner): /private/var/db/timezone/localtime ->
   /var/db/timezone/zoneinfo/Europe/Copenhagen. The root's /private/var.skel.tsv seeds it to US/Pacific (line 184),
   so the RTC's correct UTC is shown nine hours early. tzinit re-points /var/db/timezone/zoneinfo at
   /usr/share/zoneinfo.default on every boot ("Unable to locate data; resetting to system partition", r9) and resets
   localtime only when it does not resolve to a zone (its strings: "localtime link invalid; resetting to %s").
   Europe/Copenhagen is the owner Mac's /etc/localtime and exists in zoneinfo.default.

    pwr_overlay.py BASE.ovl OUT.ovl     (refuses to overwrite OUT; prints a JSON report)
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


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MK = load('mkoverlay', 'research/ios26-overlay-r1/tools/mkoverlay.py')
RC = load('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
sha = lambda b: hashlib.sha256(b).hexdigest()

BASE_SHA = '95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55'
MASK = 0xA0080081
SB = '/private/var/mobile/Library/Preferences/com.apple.springboard.plist'
LOCALTIME = '/private/var/db/timezone/localtime'
ZONE = 'Europe/Copenhagen'
TARGET = '/var/db/timezone/zoneinfo/' + ZONE


def active(r):
    return MASK >> r[1] & 1


def transform(blob):
    if sha(blob) != BASE_SHA:
        raise ValueError('base is not perf-r1 95701ed9')
    rows = RC.decode(blob)
    if any(r[5] == LOCALTIME for r in rows):
        raise ValueError('already composed')
    out = {}

    # 1. springboard.plist, the one active copy
    sb = [i for i, r in enumerate(rows) if r[5] == SB and active(r)]
    if sb != [0] or rows[0][1:5] != (0, 0o600, 501, 501) or rows[0][6][:8] != b'bplist00':
        raise ValueError('expected the active springboard.plist at record 0, group 0, 0600 mobile:mobile, binary')
    k, g, m, u, gi, p, data, _ = rows[0]
    before = plistlib.loads(data)
    if before.get('SBDontLockEver') is not True or before.get('SBShowBatteryPercentage') is not True:
        raise ValueError('unexpected springboard.plist')
    after = {key: v for key, v in before.items() if key != 'SBDontLockEver'}
    payload = plistlib.dumps(after, fmt=plistlib.FMT_BINARY, sort_keys=True)
    out[0] = MK.pack(chr(k), g, m, u, gi, p, payload)

    # 2. localtime
    extra = [MK.pack('l', 0, 0o755, 0, 0, LOCALTIME, TARGET.encode())]

    body = b''.join(out.get(i, r[7]) for i, r in enumerate(rows)) + b''.join(extra)
    result = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows) + len(extra), MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX:
        raise ValueError('too large')

    # independent postconditions with the second walker
    new = RC.decode(result)
    assert len(new) == len(rows) + 1
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, new)) if i not in out)
    assert new[0][:6] == rows[0][:6]
    got = plistlib.loads(new[0][6])
    assert got == after and 'SBDontLockEver' not in got and set(before) - set(got) == {'SBDontLockEver'}
    assert all(got[key] == before[key] for key in got)
    assert got['SBAutoLockTime'] == -1 and got['SBDisableIdleSleep'] is True and got['SBDontDimOrLockOnAC'] is True
    assert new[-1][0] == ord('l') and new[-1][5] == LOCALTIME and new[-1][6] == TARGET.encode()
    assert new[-1][1:5] == (0, 0o755, 0, 0)
    # the other springboard.plist copies stay in their inactive groups
    assert [i for i, r in enumerate(new) if r[5] == SB and active(r)] == [0]
    return result, {
        'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'records': len(new),
        'mask': hex(MASK),
        'replaced': {'0 springboard.plist': f'-SBDontLockEver, {len(before)} -> {len(after)} keys, '
                                            f'{len(data)} -> {len(payload)} B, sha256 {sha(payload)}'},
        'appended': {LOCALTIME: {'group': 0, 'type': 'l', 'target': TARGET}},
        'other_records_byte_identical': len(rows) - len(out)}


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
