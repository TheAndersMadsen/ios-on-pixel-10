#!/usr/bin/env python3
"""HOST ONLY: add hk_accel_once.dylib to the A7/r3 overlay (artwork-container-battery-observe-r1, 7d610456...).

One record changes: the selected hk_env. Inside it only the backboardd rule changes, in place (rule order kept):
DYLD_INSERT_LIBRARIES gains ':/private/var/hk/hk_accel_once.dylib' and ';HK_ACCEL_ONCE=<mode>' is appended.
One file record is appended (group of the env record, 0755, root:root). Every other record is byte-identical.
Codec: research/ios26-overlay-r1/tools/mkoverlay.py (pack/fnv1a/env_ok), the same as every existing composer.
Writes build-mac/overlays/ only; refuses to overwrite.
"""
import hashlib
import importlib.util
import json
import struct
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
BASE = REPO / 'research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl'
LIB = HERE / 'out/hk_accel_once.dylib'
MKOVERLAY = REPO / 'research/ios26-overlay-r1/tools/mkoverlay.py'
PINNED = {
    BASE: '7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58',
    MKOVERLAY: 'e658e67be7b8d2caa36e37a5e690ab60d5ac45b3bbe7a7d70121e48e98813573',
    LIB: 'c1a41d7d5832b59056dc3b9df014de54b5d88ab6a8b1a2eab11a79b8e701a39e',
}
MASK = 0xA0080081
LIBRARY = '/private/var/hk/hk_accel_once.dylib'
GATE = 'HK_ACCEL_ONCE'
OUT = HERE / 'overlays'

spec = importlib.util.spec_from_file_location('mkoverlay', MKOVERLAY)
MK = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MK)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def records(b):
    """Same walk as sampler/tools/compose.py records()."""
    if len(b) < 24 or b[:8] != MK.MAGIC:
        raise ValueError('bad header')
    size, count, h = struct.unpack_from('<IIQ', b, 8)
    if size != len(b) or size > MK.TOTAL_MAX or MK.fnv1a(b[24:]) != h:
        raise ValueError('bad size/checksum')
    p, out = 24, []
    for _ in range(count):
        start = p
        kind, group, mode, uid, gid, plen, dlen = struct.unpack_from('<BB2xIIIII', b, p)
        p += 24
        if plen >= MK.PATH_MAX or p + plen >= size or b[p + plen] != 0:
            raise ValueError('bad path')
        path = b[p:p + plen].decode()
        p = (p + plen + 8) & ~7
        if p + dlen > size:
            raise ValueError('bad data size')
        data = b[p:p + dlen]
        p = (p + dlen + 7) & ~7
        if group > 31 or p > size:
            raise ValueError('bad group')
        out.append(dict(kind=chr(kind), group=group, mode=mode, uid=uid, gid=gid, path=path, data=data, raw=b[start:p]))
    if p != size:
        raise ValueError('trailing bytes')
    return out


def extend_env(text, mode):
    MK.env_ok(text)
    rules = text.split(',')
    hits = [i for i, r in enumerate(rules) if 'backboardd' in r.split(':', 1)[0].split('+')]
    if len(hits) != 1 or rules[hits[0]].split(':', 1)[0] != 'backboardd':
        raise ValueError('need exactly one rule, and it must be backboardd alone')
    i = hits[0]
    variables = rules[i].split(':', 1)[1].split(';')
    keys = [v.split('=', 1)[0] for v in variables]
    if len(set(keys)) != len(keys) or GATE in keys or LIBRARY in rules[i]:
        raise ValueError('duplicate key or already composed')
    d = [j for j, k in enumerate(keys) if k == 'DYLD_INSERT_LIBRARIES']
    if len(d) != 1:
        raise ValueError('backboardd rule has no DYLD_INSERT_LIBRARIES')
    variables[d[0]] += ':' + LIBRARY
    variables.append(GATE + '=' + mode)
    rules[i] = 'backboardd:' + ';'.join(variables)
    new = ','.join(rules)
    MK.env_ok(new)
    if len(new.encode()) >= 1024 or max(len(v) for v in variables) + 1 > 384:
        raise ValueError('hk_env kernel bound')
    return new, i


def compose(base, library, mode):
    rows = records(base)
    sel = [r for r in rows if MASK & (1 << r['group'])]
    envs = [(i, r) for i, r in enumerate(rows) if r['kind'] == 'c' and r['path'] == 'hk_env' and MASK & (1 << r['group'])]
    if len(envs) != 1 or any(r['path'] == LIBRARY for r in rows):
        raise ValueError('ambiguous or already composed')
    if not any(r['kind'] == 'd' and r['path'] == '/private/var/hk' for r in sel):
        raise ValueError('no /private/var/hk directory in the selected groups')
    ei, env = envs[0]
    text, rule_index = extend_env(env['data'].decode('ascii'), mode)
    repl = MK.pack('c', env['group'], env['mode'], env['uid'], env['gid'], 'hk_env', text.encode())
    body = b''.join(repl if j == ei else r['raw'] for j, r in enumerate(rows))
    body += MK.pack('f', env['group'], 0o755, 0, 0, LIBRARY, library)
    blob = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(rows) + 1, MK.fnv1a(body)) + body
    if len(blob) > MK.TOTAL_MAX:
        raise ValueError('too large')
    after = records(blob)
    assert len(after) == len(rows) + 1
    assert all(a['raw'] == b['raw'] for j, (a, b) in enumerate(zip(rows, after)) if j != ei)
    assert after[-1]['data'] == library and after[-1]['path'] == LIBRARY
    old_rules, new_rules = env['data'].decode().split(','), text.split(',')
    assert [r for j, r in enumerate(old_rules) if j != rule_index] == [r for j, r in enumerate(new_rules) if j != rule_index]
    return blob, dict(base=str(BASE.relative_to(REPO)), base_sha256=sha(base), library=LIBRARY,
                      library_sha256=sha(library), library_bytes=len(library), mode=mode, mask=hex(MASK),
                      env_record_index=ei, env_group=env['group'], backboardd_rule_index=rule_index,
                      old_backboardd_rule=old_rules[rule_index], new_backboardd_rule=new_rules[rule_index],
                      hk_env_bytes_with_NUL=len(text) + 1, records=len(after), preserved_records=len(rows) - 1,
                      replaced_records=1, appended_records=1, overlay_sha256=sha(blob), bytes=len(blob), hk_env=text)


def main():
    for path, want in PINNED.items():
        got = sha(path.read_bytes())
        if got != want:
            raise SystemExit(f'input drift: {path} {got} != {want}')
    OUT.mkdir(exist_ok=True)
    base, lib = BASE.read_bytes(), LIB.read_bytes()
    summary = {}
    for mode in ('probe', 'skip'):
        out = OUT / ('artwork-container-battery-observe-accel-r1.ovl' if mode == 'probe' else
                     'artwork-container-battery-observe-accel-skip-r1.ovl')
        if out.exists():
            raise SystemExit(f'{out} exists; choose a new name')
        blob, receipt = compose(base, lib, mode)
        out.write_bytes(blob)
        out.chmod(0o444)
        out.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n')
        summary[out.name] = dict(sha256=receipt['overlay_sha256'], bytes=receipt['bytes'],
                                 new_backboardd_rule=receipt['new_backboardd_rule'])
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
