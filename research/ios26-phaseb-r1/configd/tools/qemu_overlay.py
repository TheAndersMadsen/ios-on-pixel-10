#!/usr/bin/env python3
"""HOST ONLY. QEMU-only overlay for the configd A/B: perf-r1.ovl (95701ed9, a7-ios-system-r10-perf's and cfg1's overlay)
plus the hk_scwait probe in powerd. Two changes, every other record byte-identical:

1. [39] hk_env: the powerd rule gains ':/private/var/hk/hk_scwait.dylib' in DYLD_INSERT_LIBRARIES and ';HK_SCWAIT=1'.
2. Appended: /private/var/hk/hk_scwait.dylib (group 29, 0755, root:root).

Never for the phone image (cfg1 keeps perf-r1.ovl unchanged).

    qemu_overlay.py BASE.ovl DYLIB OUT.ovl     (refuses to overwrite OUT; prints a JSON report)
"""
import hashlib, importlib.util, json, struct, sys
from pathlib import Path
sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


MK = load('mkoverlay', 'research/ios26-overlay-r1/tools/mkoverlay.py')
RC = load('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
sha = lambda b: hashlib.sha256(b).hexdigest()
BASE_SHA = '95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55'
MASK = 0xA0080081
LIB, GATE, PROG = '/private/var/hk/hk_scwait.dylib', 'HK_SCWAIT=1', 'powerd'


def transform(blob, library):
    if sha(blob) != BASE_SHA: raise ValueError('base is not perf-r1.ovl 95701ed9')
    if library[:4] != b'\xcf\xfa\xed\xfe': raise ValueError('library is not a 64-bit Mach-O')
    rows = RC.decode(blob)
    if any(r[5] == LIB for r in rows): raise ValueError('already composed')
    envs = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_env' and MASK >> r[1] & 1 and r[1] == 29]
    if envs != [39]: raise ValueError('expected the group-29 hk_env at record 39')
    k, g, m, u, gi, p, data, _ = rows[39]
    rules = data.decode('ascii').split(',')
    hits = [i for i, r in enumerate(rules) if r.split(':', 1)[0] == PROG]
    if len(hits) != 1: raise ValueError('need exactly one powerd rule')
    var = rules[hits[0]].split(':', 1)[1].split(';')
    d = [j for j, v in enumerate(var) if v.startswith('DYLD_INSERT_LIBRARIES=')]
    if len(d) != 1: raise ValueError('powerd rule has no DYLD_INSERT_LIBRARIES')
    var[d[0]] += ':' + LIB; var.append(GATE)
    rules[hits[0]] = PROG + ':' + ';'.join(var)
    text = ','.join(rules); MK.env_ok(text)
    if len(text) + 1 > 1024 or max(len(v) for v in var) + 1 > 384: raise ValueError('hk_env kernel bound')
    out = {39: MK.pack(chr(k), g, m, u, gi, p, text.encode())}
    extra = MK.pack('f', 29, 0o755, 0, 0, LIB, library)
    body = b''.join(out.get(i, r[7]) for i, r in enumerate(rows)) + extra
    result = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows) + 1, MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX: raise ValueError('too large')
    new = RC.decode(result)
    assert len(new) == len(rows) + 1
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, new)) if i != 39)
    assert new[39][:6] == rows[39][:6] and new[39][6] == text.encode()
    old_r, new_r = data.decode().split(','), text.split(',')
    assert [r for j, r in enumerate(old_r) if j != hits[0]] == [r for j, r in enumerate(new_r) if j != hits[0]]
    assert new[-1][5] == LIB and new[-1][6] == library and new[-1][1:5] == (29, 0o755, 0, 0)
    return result, {'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'records': len(new),
                    'replaced': {'39 hk_env powerd': {'old': old_r[hits[0]], 'new': new_r[hits[0]], 'bytes_with_NUL': len(text) + 1}},
                    'appended': {LIB: {'group': 29, 'sha256': sha(library), 'bytes': len(library)}},
                    'other_records_byte_identical': len(rows) - 1}


if __name__ == '__main__':
    base, lib, outp = (Path(x) for x in sys.argv[1:4])
    result, report = transform(base.read_bytes(), lib.read_bytes())
    with outp.open('xb') as f: f.write(result)
    print(json.dumps(report, indent=2))
