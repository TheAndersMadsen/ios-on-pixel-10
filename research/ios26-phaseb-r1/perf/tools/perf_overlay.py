#!/usr/bin/env python3
"""HOST ONLY. The overlay for a7-ios-system-r10-perf, on top of settings-btdisabled-r1.ovl (ee7554b9...).

Four changes, every other record byte-identical (codec: ios26-overlay-r1/tools/mkoverlay.py pack/fnv1a/env_ok,
second walker: ios26-overlay2-r1/tools/restore_cloudd.py decode):

1. [14] group-7 disabled.plist: com.apple.bluetoothd taken out again (160 -> 159 labels). r8 showed that with no
   bluetoothd names registered, audiomxd retries com.apple.BTAudioHALPlugin.xpc / com.apple.bluetooth.xpc in a tight
   loop (~590k failed lookups in 5 min) and launchd spends ~28 s of CPU per 30 s answering them. Every boot with
   bluetoothd refused at exec (the hk_deny row, still present) has a quiet launchd and audiomxd. The record must come
   out byte-identical to r7-touch's (f5d4c367) record 14.
2. [42] group-31 hk_deny: 'bluetoothd' -> 'bluetoothd,Spotlight'. The Spotlight search app (UIKitApplication
   com.apple.Spotlight) burns one core (~31 s per 30 s) and grows past its 300 MB soft limit once the Home search is
   pulled down, in r8 and in the p29 runs; its sampled path is the dictation-button lock-state query (AKS sel 17),
   cause unknown. Refusing its exec removes it.
3. [39] hk_env: the Preferences rule gains ':/private/var/hk/hk_mainwatch.dylib' in DYLD_INSERT_LIBRARIES and
   ';HK_MAINWATCH=1' (the main-thread watch that tells starved / blocked / touches-not-delivered apart). Rule order
   and every other rule are unchanged.
4. Appended: /private/var/hk/hk_mainwatch.dylib (group 29, 0755, root:root), and
   /private/var/mobile/Library/Preferences/com.apple.Accessibility.plist (group 0, 0600, mobile:mobile, binary plist)
   with Reduce Transparency (EnhancedBackgroundContrastEnabled), Reduce Motion (ReduceMotionEnabled) and Prefer
   Cross-Fade Transitions (ReduceMotionReduceSlideTransitionsPreference) on. Key names are from libAccessibility's key
   table in the 23G90 dyld cache (dsc-r6 subcache .01).

    perf_overlay.py BASE.ovl DYLIB OUT.ovl     (refuses to overwrite OUT; prints a JSON report)
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

BASE_SHA = 'ee7554b9aba04d437992e3dbea73a9bdd5c444273b6cecd6fa3d9cfbf950a3ca'
R7_RECORD14_SHA = '6930d06f689d6872c658421d9da24eec5e6ba280ae8b93f4dd003d87777be131'  # disabled.plist in f5d4c367
MASK = 0xA0080081
DISABLED = '/private/var/db/com.apple.xpc.launchd/disabled.plist'
LIBRARY = '/private/var/hk/hk_mainwatch.dylib'
GATE = 'HK_MAINWATCH=1'
AXPLIST = '/private/var/mobile/Library/Preferences/com.apple.Accessibility.plist'
AX = {'EnhancedBackgroundContrastEnabled': True, 'ReduceMotionEnabled': True,
      'ReduceMotionReduceSlideTransitionsPreference': True}
DENY_BEFORE, DENY_AFTER = 'bluetoothd', 'bluetoothd,Spotlight'


def active(r):
    return MASK >> r[1] & 1


def extend_preferences(text):
    MK.env_ok(text)
    rules = text.split(',')
    hits = [i for i, r in enumerate(rules) if 'Preferences' in r.split(':', 1)[0].split('+')]
    if len(hits) != 1 or rules[hits[0]].split(':', 1)[0] != 'Preferences':
        raise ValueError('need exactly one rule for Preferences, and it must be Preferences alone')
    i = hits[0]
    variables = rules[i].split(':', 1)[1].split(';')
    keys = [v.split('=', 1)[0] for v in variables]
    if len(set(keys)) != len(keys) or 'HK_MAINWATCH' in keys or LIBRARY in rules[i]:
        raise ValueError('duplicate key or already composed')
    d = [j for j, k in enumerate(keys) if k == 'DYLD_INSERT_LIBRARIES']
    if len(d) != 1:
        raise ValueError('Preferences rule has no DYLD_INSERT_LIBRARIES')
    variables[d[0]] += ':' + LIBRARY
    variables.append(GATE)
    rules[i] = 'Preferences:' + ';'.join(variables)
    new = ','.join(rules)
    MK.env_ok(new)
    if len(new.encode()) + 1 > 1024 or max(len(v) for v in variables) + 1 > 384:
        raise ValueError('hk_env kernel bound (HK_RULES_MAX 1024, HK_VAR_MAX 384)')
    return new, i


def transform(blob, library):
    if sha(blob) != BASE_SHA:
        raise ValueError('base is not settings-btdisabled-r1 ee7554b9')
    if library[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('library is not a 64-bit Mach-O')
    rows = RC.decode(blob)
    if any(r[5] in (LIBRARY, AXPLIST) for r in rows):
        raise ValueError('already composed')
    out = {}

    # 1. disabled.plist
    dis = [i for i, r in enumerate(rows) if r[5] == DISABLED and active(r)]
    if dis != [14] or rows[14][1] != 7:
        raise ValueError('expected the active disabled.plist at record 14, group 7')
    k, g, m, u, gi, p, disabled_data, _ = rows[14]
    before = plistlib.loads(disabled_data)
    if len(before) != 160 or before.get('com.apple.bluetoothd') is not True:
        raise ValueError('unexpected disabled set')
    after = {key: v for key, v in before.items() if key != 'com.apple.bluetoothd'}
    payload = plistlib.dumps(after, fmt=plistlib.FMT_XML, sort_keys=True)
    if sha(payload) != R7_RECORD14_SHA:
        raise ValueError('re-enabled disabled.plist is not byte-identical to r7-touch record 14')
    out[14] = MK.pack(chr(k), g, m, u, gi, p, payload)

    # 2. hk_deny
    deny = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_deny' and active(r)]
    if deny != [42] or rows[42][6] != DENY_BEFORE.encode():
        raise ValueError('expected one active hk_deny (record 42) = bluetoothd')
    k, g, m, u, gi, p, _, _ = rows[42]
    MK.deny_ok(DENY_AFTER)  # exits on a bad name or a NEVER_DENY name
    out[42] = MK.pack(chr(k), g, m, u, gi, p, DENY_AFTER.encode())

    # 3. hk_env
    envs = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_env' and active(r)]
    if envs != [39]:
        raise ValueError('expected one active hk_env (record 39)')
    k, g, m, u, gi, p, data, _ = rows[39]
    env_text, rule = extend_preferences(data.decode('ascii'))
    out[39] = MK.pack(chr(k), g, m, u, gi, p, env_text.encode())
    if not any(r[0] == ord('d') and r[5] == '/private/var/hk' and active(r) and r[1] == g for r in rows):
        raise ValueError('no /private/var/hk directory in the env group')
    sb = [r for r in rows if r[5] == '/private/var/mobile/Library/Preferences/com.apple.springboard.plist' and active(r)]
    if len(sb) != 1 or sb[0][1:5] != (0, 0o600, 501, 501):
        raise ValueError('expected the active springboard.plist in group 0, 0600 mobile:mobile')

    # 4. appended files
    ax = plistlib.dumps(AX, fmt=plistlib.FMT_BINARY, sort_keys=True)
    extra = [MK.pack('f', g, 0o755, 0, 0, LIBRARY, library), MK.pack('f', 0, 0o600, 501, 501, AXPLIST, ax)]

    body = b''.join(out.get(i, r[7]) for i, r in enumerate(rows)) + b''.join(extra)
    result = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows) + 2, MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX:
        raise ValueError('too large')

    # independent postconditions with the second walker
    new = RC.decode(result)
    assert len(new) == len(rows) + 2
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, new)) if i not in out)
    assert all(a[:6] == b[:6] for i, (a, b) in enumerate(zip(rows, new)) if i in out)
    assert plistlib.loads(new[14][6]) == after and len(after) == 159 and sha(new[14][6]) == R7_RECORD14_SHA
    assert new[42][6] == DENY_AFTER.encode()
    old_rules, new_rules = data.decode().split(','), new[39][6].decode().split(',')
    assert [r for j, r in enumerate(old_rules) if j != rule] == [r for j, r in enumerate(new_rules) if j != rule]
    assert new[-2][5] == LIBRARY and new[-2][6] == library and new[-2][1:5] == (g, 0o755, 0, 0)
    assert new[-1][5] == AXPLIST and plistlib.loads(new[-1][6]) == AX and new[-1][1:5] == (0, 0o600, 501, 501)
    return result, {
        'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'records': len(new),
        'mask': hex(MASK), 'replaced': {
            '14 disabled.plist': f'160 -> 159 labels (-com.apple.bluetoothd), {len(disabled_data)} -> {len(payload)} B, '
                                 f'== r7-touch record 14 ({R7_RECORD14_SHA[:16]})',
            '42 hk_deny': f'{DENY_BEFORE} -> {DENY_AFTER}',
            '39 hk_env': {'old_preferences_rule': old_rules[rule], 'new_preferences_rule': new_rules[rule],
                          'bytes_with_NUL': len(env_text) + 1}},
        'appended': {LIBRARY: {'group': g, 'sha256': sha(library), 'bytes': len(library)},
                     AXPLIST: {'group': 0, 'sha256': sha(ax), 'bytes': len(ax), 'keys': AX}},
        'other_records_byte_identical': len(rows) - len(out)}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('base', type=Path)
    p.add_argument('library', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    result, report = transform(a.base.read_bytes(), a.library.read_bytes())
    with a.output.open('xb') as f:
        f.write(result)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
