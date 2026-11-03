#!/usr/bin/env python3
"""HOST ONLY. The overlay for a7-ios-system-obs1: int1-r1.ovl (c440b6ea..., a7-ios-system-int1's) with the log mirror
generalised. Two records change, every other record is byte-identical (codec: ios26-overlay-r1/tools/mkoverlay.py
pack/fnv1a/env_ok; second walker: ios26-overlay2-r1/tools/restore_cloudd.py decode):

1. [39] hk_env: app2's one-daemon rule "tccd:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_stderr_console.dylib;
   HK_STDERR_CONSOLE=1;OS_ACTIVITY_DT_MODE=YES" is replaced by one rule for the whole list (MIRROR below):
       <p1>+<p2>+...:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_logmirror.dylib;HK_LOGMIRROR=1;OS_ACTIVITY_DT_MODE=YES
   Programs with their own DYLD_INSERT_LIBRARIES (Preferences, SpringBoard) keep theirs: the hk-obs1 kernel gives them
   one variable holding both rules' libraries (bsd/kern/hk_env_merge.h). On an older kernel the first rule would win and
   those two would not be mirrored; tools/mkimg_obs1.sh refuses a kernel without the string "rules' libraries in one".
2. [50] /private/var/hk/hk_stderr_console.dylib -> /private/var/hk/hk_logmirror.dylib (same group 29, 0755 root), so
   nothing references a library that is no longer used.

The list is the programs that exist on the phone root (phone-r3, checked on the Mac's read-only attach, receipts/
root-daemons.txt): airportd is macOS-only and absent. bluetoothd stays denied by [42] on this image (int1 left Bluetooth
out); WirelessRadioManagerd is disabled by launchd's disabled.plist. Both cost only their name here and are mirrored on an
image that runs them.

    obs_overlay.py BASE.ovl DYLIB OUT.ovl [--programs a,b,c]   (refuses to overwrite OUT; prints a JSON report)
"""
import argparse, hashlib, importlib.util, json, struct, sys
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

BASE_SHA = 'c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e'   # int1-r1.ovl
MASK = 0xA0080081
OLD_LIB = '/private/var/hk/hk_stderr_console.dylib'
OLD_RULE = f'tccd:DYLD_INSERT_LIBRARIES={OLD_LIB};HK_STDERR_CONSOLE=1;OS_ACTIVITY_DT_MODE=YES'
LIBRARY = '/private/var/hk/hk_logmirror.dylib'
PROGRAMS = ['wifid', 'configd', 'bluetoothd', 'WirelessRadioManagerd', 'CommCenter', 'locationd', 'tccd', 'lsd',
            'SpringBoard', 'MobilePhone', 'Preferences']
ENV = f'DYLD_INSERT_LIBRARIES={LIBRARY};HK_LOGMIRROR=1;OS_ACTIVITY_DT_MODE=YES'


def rule(programs):
    return '+'.join(programs) + ':' + ENV


def active(r):
    return MASK >> r[1] & 1


def transform(blob, library, programs=PROGRAMS, base_sha=BASE_SHA):
    if sha(blob) != base_sha:
        raise ValueError(f'base is not {base_sha[:8]}')
    if library[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('library is not a 64-bit Mach-O')
    if len(set(programs)) != len(programs) or not programs:
        raise ValueError('programs: empty or repeated')
    rows = RC.decode(blob)
    envs = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_env' and active(r)]
    if envs != [39]:
        raise ValueError('expected one active hk_env (record 39)')
    libs = [i for i, r in enumerate(rows) if r[5] == OLD_LIB]
    if libs != [50]:
        raise ValueError(f'expected {OLD_LIB} at record 50')
    if any(r[5] == LIBRARY for r in rows):
        raise ValueError('already composed')
    k, g, m, u, gi, p, data, _ = rows[39]
    old = data.decode('ascii')
    parts = old.split(',')
    if parts.count(OLD_RULE) != 1:
        raise ValueError("int1's tccd mirror rule not found exactly once")
    kept = [x for x in parts if x != OLD_RULE]
    if any(set(x.split(':', 1)[0].split('+')) & {'HK_LOGMIRROR'} for x in kept) or 'HK_LOGMIRROR' in old:
        raise ValueError('a mirror rule exists already')
    new = ','.join(kept + [rule(programs)])
    MK.env_ok(new)
    if len(new.encode()) + 1 > 1024 or max(len(v) for v in ENV.split(';')) + 1 > 384:
        raise ValueError('hk_env kernel bound (HK_RULES_MAX 1024, HK_VAR_MAX 384)')
    lk, lg, lm, lu, lgi, lp, ldata, _ = rows[50]
    if (lk, lg, lm, lu, lgi) != (ord('f'), g, 0o755, 0, 0):
        raise ValueError('record 50 is not the group-29 0755 root file it should be')
    rep = {39: MK.pack(chr(k), g, m, u, gi, p, new.encode()), 50: MK.pack('f', lg, lm, lu, lgi, LIBRARY, library)}
    body = b''.join(rep.get(i, r[7]) for i, r in enumerate(rows))
    result = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows), MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX:
        raise ValueError('too large')
    out = RC.decode(result)
    assert len(out) == len(rows)
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, out)) if i not in (39, 50))
    assert out[39][:6] == rows[39][:6] and out[39][6].decode() == new
    assert out[39][6].decode().split(',')[:-1] == kept
    assert out[50][:5] == rows[50][:5] and out[50][5] == LIBRARY and out[50][6] == library
    return result, {
        'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'records': len(out), 'mask': hex(MASK),
        'replaced': {'39 hk_env': {'removed_rule': OLD_RULE, 'appended_rule': rule(programs), 'bytes_with_NUL': len(new) + 1,
                                   'before_bytes_with_NUL': len(old) + 1},
                     '50 library': {'from': OLD_LIB, 'to': LIBRARY, 'sha256': sha(library), 'bytes': len(library)}},
        'programs': programs, 'other_records_byte_identical': len(rows) - 2}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('base', type=Path)
    p.add_argument('library', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--programs', help='comma-separated list instead of the default set')
    a = p.parse_args()
    progs = a.programs.split(',') if a.programs else PROGRAMS
    result, report = transform(a.base.read_bytes(), a.library.read_bytes(), progs)
    with a.output.open('xb') as f:
        f.write(result)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
