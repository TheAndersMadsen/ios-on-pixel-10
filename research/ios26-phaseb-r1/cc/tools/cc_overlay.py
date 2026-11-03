#!/usr/bin/env python3
"""HOST ONLY. Overlay cc1-r1 = int1-r1 (c440b6ea..., 52 records) with two changes, every other record byte-identical:

1. [39] hk_env: the SpringBoard rule's DYLD_INSERT_LIBRARIES gains ':/private/var/hk/hk_flatmat.dylib' and the rule
   gains ';HK_FLATMAT=1'. Rule order and every other rule are unchanged.
2. Appended [52]: /private/var/hk/hk_flatmat.dylib (group 29 = the env group, 0755, root:root).

Codec: ios26-overlay-r1/tools/mkoverlay.py (pack/fnv1a/env_ok); second walker: ios26-overlay2-r1/tools/restore_cloudd.py.

    cc_overlay.py BASE.ovl DYLIB OUT.ovl     (refuses to overwrite OUT; prints a JSON report)
"""
import argparse, hashlib, importlib.util, json, struct, sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


MK = load('mkoverlay', 'research/ios26-overlay-r1/tools/mkoverlay.py')
RC = load('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
sha = lambda b: hashlib.sha256(b).hexdigest()
BASE_SHA = 'c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e'
DYLIB_SHA = '66f49f7bf4c456b1f937acae9cfdd281e3ce0b59cb01ff78ae05991f6f0f55c5'
MASK = 0xA0080081
LIBRARY = '/private/var/hk/hk_flatmat.dylib'
GATE = 'HK_FLATMAT=1'


def extend_springboard(text):
    MK.env_ok(text)
    rules = text.split(',')
    hits = [i for i, r in enumerate(rules) if r.split(':', 1)[0] == 'SpringBoard']
    if len(hits) != 1:
        raise ValueError('need exactly one SpringBoard rule')
    i = hits[0]
    variables = rules[i].split(':', 1)[1].split(';')
    keys = [v.split('=', 1)[0] for v in variables]
    if len(set(keys)) != len(keys) or 'HK_FLATMAT' in keys or LIBRARY in rules[i]:
        raise ValueError('duplicate key or already composed')
    d = [j for j, k in enumerate(keys) if k == 'DYLD_INSERT_LIBRARIES']
    if len(d) != 1:
        raise ValueError('SpringBoard rule has no DYLD_INSERT_LIBRARIES')
    variables[d[0]] += ':' + LIBRARY
    variables.append(GATE)
    rules[i] = 'SpringBoard:' + ';'.join(variables)
    new = ','.join(rules)
    MK.env_ok(new)
    if len(new.encode()) + 1 > 1024 or max(len(v) for v in variables) + 1 > 384:
        raise ValueError('hk_env kernel bound (HK_RULES_MAX 1024, HK_VAR_MAX 384)')
    return new, i


def transform(blob, library):
    if sha(blob) != BASE_SHA:
        raise ValueError('base is not int1-r1 c440b6ea')
    if sha(library) != DYLIB_SHA or library[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('library is not hk_flatmat 66f49f7b')
    rows = RC.decode(blob)
    if len(rows) != 52 or any(r[5] == LIBRARY for r in rows):
        raise ValueError('unexpected base or already composed')
    act = lambda r: MASK >> r[1] & 1
    envs = [i for i, r in enumerate(rows) if r[0] == ord('c') and r[5] == 'hk_env' and act(r)]
    if envs != [39]:
        raise ValueError('expected one active hk_env (record 39)')
    k, g, m, u, gi, p, data, _ = rows[39]
    if not any(r[0] == ord('d') and r[5] == '/private/var/hk' and act(r) and r[1] == g for r in rows):
        raise ValueError('no /private/var/hk directory in the env group')
    env_text, rule = extend_springboard(data.decode('ascii'))
    out = {39: MK.pack(chr(k), g, m, u, gi, p, env_text.encode())}
    extra = [MK.pack('f', g, 0o755, 0, 0, LIBRARY, library)]
    body = b''.join(out.get(i, r[7]) for i, r in enumerate(rows)) + b''.join(extra)
    result = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows) + 1, MK.fnv1a(body)) + body
    if len(result) > MK.TOTAL_MAX:
        raise ValueError('too large')
    new = RC.decode(result)
    assert len(new) == 53
    assert all(a[7] == b[7] for i, (a, b) in enumerate(zip(rows, new)) if i != 39)
    assert new[39][:6] == rows[39][:6]
    old_rules, new_rules = data.decode().split(','), new[39][6].decode().split(',')
    assert [r for j, r in enumerate(old_rules) if j != rule] == [r for j, r in enumerate(new_rules) if j != rule]
    assert new[-1][5] == LIBRARY and new[-1][6] == library and new[-1][1:5] == (g, 0o755, 0, 0) and act(new[-1])
    return result, {
        'base_sha256': sha(blob), 'output_sha256': sha(result), 'bytes': len(result), 'records': len(new),
        'mask': hex(MASK),
        'replaced': {'39 hk_env': {'old_springboard_rule': old_rules[rule], 'new_springboard_rule': new_rules[rule],
                                   'bytes_with_NUL': len(env_text) + 1}},
        'appended': {f'52 {LIBRARY}': {'group': g, 'sha256': sha(library), 'bytes': len(library)}},
        'other_records_byte_identical': len(rows) - 1}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base', type=Path); ap.add_argument('library', type=Path); ap.add_argument('output', type=Path)
    a = ap.parse_args()
    result, report = transform(a.base.read_bytes(), a.library.read_bytes())
    with a.output.open('xb') as f:
        f.write(result)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
