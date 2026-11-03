#!/usr/bin/env python3
"""HOST ONLY. The overlay for a7-ios-system-app2, on top of perf-r1.ovl (95701ed9..., a7-ios-system-r10-perf's).

Three changes, every other record byte-identical (codec: ios26-overlay-r1/tools/mkoverlay.py pack/fnv1a/env_ok,
second walker: ios26-overlay2-r1/tools/restore_cloudd.py decode):

1. Appended dir /private/var/mobile/Library/TCC (group 0, 0755, mobile:mobile). The root's var.skel.tsv has no such
   directory (it has AddressBook, Preferences, ... next to it), so tccd (UserName mobile, '%s/TCC.db' under
   'Library/TCC') must create it on every boot. Stock iOS ships it.
2. [39] hk_env gains one rule, appended last: tccd:DYLD_INSERT_LIBRARIES=/private/var/hk/hk_stderr_console.dylib;
   HK_STDERR_CONSOLE=1;OS_ACTIVITY_DT_MODE=YES. The phone root (ios_system) is read only, so the job plist's
   StandardErrorPath cannot be set as in m1box/edit_logmirror_lsd_umd.py: the dylib points stderr at /dev/console and
   DT mode mirrors os_log there (AUTHREQ_*, "Granting ... via entitlement", "Failed to open database"). Every other
   rule is unchanged.
3. Appended file /private/var/hk/hk_stderr_console.dylib (group 29 like the other hk dylibs, 0755 root:root).

No TCC.db seed: tccd grants com.apple.private.tcc.allow services 'via entitlement' and does not store that answer
("Default Allow for: Client ... will not be stored in database"), so a DB row would not change MobilePhone's result.

    app2_overlay.py [--qemu] BASE.ovl DYLIB OUT.ovl     (refuses to overwrite OUT; prints a JSON report)
"""
import argparse, hashlib, importlib.util, json, struct, sys
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
QEMU_BASE_SHA = '61c38161efd809bdac15f9f167e5431a4f116b54bf42c7280411480fa37bea2a'  # hgltrack-rebuilt.ovl (QEMU r21-r25)
MASK = 0xA0080081
LIBRARY = '/private/var/hk/hk_stderr_console.dylib'
TCCDIR = '/private/var/mobile/Library/TCC'
RULE = f'tccd:DYLD_INSERT_LIBRARIES={LIBRARY};HK_STDERR_CONSOLE=1;OS_ACTIVITY_DT_MODE=YES'


def active(r):
    return MASK >> r[1] & 1


def transform(blob, library, base_sha=BASE_SHA):
    if sha(blob) != base_sha:
        raise ValueError(f'base is not {base_sha[:8]}')
    if library[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('library is not a 64-bit Mach-O')
    rows = RC.decode(blob)
    if any(r[5] in (LIBRARY, TCCDIR) for r in rows):
        raise ValueError('already composed')
    envs = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_env' and active(r)]
    if envs != [39]:
        raise ValueError('expected one active hk_env (record 39)')
    k, g, m, u, gi, p, data, _ = rows[39]
    old = data.decode('ascii')
    if any('tccd' in r.split(':', 1)[0].split('+') for r in old.split(',')):
        raise ValueError('a tccd rule exists already')
    new = old + ',' + RULE
    MK.env_ok(new)
    if len(new.encode()) + 1 > 1024 or max(len(v) for v in RULE.split(':', 1)[1].split(';')) + 1 > 384:
        raise ValueError('hk_env kernel bound (HK_RULES_MAX 1024, HK_VAR_MAX 384)')
    if not any(r[0] == ord('d') and r[5] == '/private/var/hk' and active(r) and r[1] == g for r in rows):
        raise ValueError('no /private/var/hk directory in the env group')
    if any(r[5].startswith(TCCDIR + '/') for r in rows):
        raise ValueError('overlay already has something under the TCC dir')
    rep = {39: MK.pack(chr(k), g, m, u, gi, p, new.encode())}
    extra = [MK.pack('d', 0, 0o755, 501, 501, TCCDIR, b''), MK.pack('f', g, 0o755, 0, 0, LIBRARY, library)]
    body = b''.join(rep.get(i, r[7]) for i, r in enumerate(rows)) + b''.join(extra)
    result = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows) + 2, MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX:
        raise ValueError('too large')
    out = RC.decode(result)
    assert len(out) == len(rows) + 2
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, out)) if i != 39)
    assert out[39][:6] == rows[39][:6] and out[39][6].decode() == new
    assert out[39][6].decode().split(',')[:-1] == old.split(',')
    assert out[-2][0] == ord('d') and out[-2][5] == TCCDIR and out[-2][1:5] == (0, 0o755, 501, 501)
    assert out[-1][5] == LIBRARY and out[-1][6] == library and out[-1][1:5] == (g, 0o755, 0, 0)
    return result, {
        'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'records': len(out), 'mask': hex(MASK),
        'replaced': {'39 hk_env': {'appended_rule': RULE, 'bytes_with_NUL': len(new) + 1}},
        'appended': {TCCDIR: {'kind': 'd', 'group': 0, 'mode': '0755', 'uid': 501, 'gid': 501},
                     LIBRARY: {'group': g, 'sha256': sha(library), 'bytes': len(library)}},
        'other_records_byte_identical': len(rows) - 1}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('base', type=Path)
    p.add_argument('library', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--qemu', action='store_true', help='base is the QEMU overlay hgltrack-rebuilt (61c38161), same three changes')
    a = p.parse_args()
    result, report = transform(a.base.read_bytes(), a.library.read_bytes(), QEMU_BASE_SHA if a.qemu else BASE_SHA)
    with a.output.open('xb') as f:
        f.write(result)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
