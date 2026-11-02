#!/usr/bin/env python3
"""Add sampler injection to an existing RAM overlay without rebuilding its data.

All input records except the selected hk_env are preserved byte for byte.
Extend that rule in place: kernel exec rules APPEND; a second rule is not an
override. No new mask bit and no root writes.
Default mode off: dylib loads but its constructor has no HKSAMPLER enable value.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from paths import DEFAULT_MKOVERLAY, DEFAULT_OUTPUT, generated, module

MK = None
LIBRARY = '/private/var/hk/hsampler.dylib'


def configure(path=DEFAULT_MKOVERLAY):
    global MK
    MK = module('mkoverlay', path)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def records(b):
    if MK is None:
        configure()
    if len(b) < 24 or b[:8] != MK.MAGIC:
        raise ValueError('invalid overlay header')
    size, count, hash_ = struct.unpack_from('<IIQ', b, 8)
    if size != len(b) or size > MK.TOTAL_MAX or MK.fnv1a(b[24:]) != hash_:
        raise ValueError('invalid overlay size/checksum')
    p = 24
    out = []
    for _ in range(count):
        start = p
        kind, group, mode, uid, gid, plen, dlen = struct.unpack_from('<BB2xIIIII', b, p)
        p += 24
        if plen >= MK.PATH_MAX or p+plen >= size or b[p+plen] != 0:
            raise ValueError('invalid record path')
        path = b[p:p+plen].decode()
        p = (p+plen+8) & ~7
        if p+dlen > size:
            raise ValueError('invalid record size')
        data = b[p:p+dlen]
        p = (p+dlen+7) & ~7
        if group > 31 or p > size:
            raise ValueError('invalid record group')
        out.append(dict(kind=chr(kind), group=group, mode=mode, uid=uid, gid=gid,
                        path=path, data=data, raw=b[start:p]))
    if p != size:
        raise ValueError('trailing bytes')
    return out


def extend_env(text, mode):
    if MK is None:
        configure()
    MK.env_ok(text)
    rules = []
    backboardd = []
    for rule in text.split(','):
        progs, variables = rule.split(':', 1)
        programs = progs.split('+')
        if 'backboardd' in programs:
            backboardd.extend(variables.split(';'))
            programs.remove('backboardd')
            if programs:
                rules.append('+'.join(programs)+':'+variables)
        else:
            rules.append(rule)
    settings = {}
    for item in backboardd:
        key, value = item.split('=', 1)
        if key in settings:
            raise ValueError('ambiguous duplicate backboardd environment variable')
        settings[key] = value
    libraries = settings.get('DYLD_INSERT_LIBRARIES', '').split(':')
    libraries = [x for x in libraries if x]
    if LIBRARY in libraries:
        raise ValueError('sampler already injected')
    libraries.append(LIBRARY)
    settings['DYLD_INSERT_LIBRARIES'] = ':'.join(libraries)
    settings.pop('HKSAMPLER', None)
    if mode != 'off':
        settings['HKSAMPLER'] = mode
    rules.append('backboardd:'+';'.join(k+'='+v for k, v in settings.items()))
    result = ','.join(rules)
    MK.env_ok(result)
    if len(result.encode()) >= 1024:
        raise ValueError('hk_env kernel limit exceeded')
    return result


def compose(base, base_sha, library, mask, mode):
    if sha(base) != base_sha:
        raise ValueError('base hash mismatch')
    rows = records(base)
    chosen = [r for r in rows if mask & (1 << r['group'])]
    envs = [r for r in chosen if r['kind'] == 'c' and r['path'] == 'hk_env']
    if not envs:
        raise ValueError('selected base has no hk_env')
    if len(envs) != 1:
        raise ValueError('need exactly one selected hk_env; reconcile existing rule composition first')
    if any(r['path'] == LIBRARY for r in rows):
        raise ValueError('sampler path already exists')
    if not any(r['kind'] == 'd' and r['path'] == '/private/var/hk' for r in chosen):
        raise ValueError('selected base lacks library directory')
    env = envs[-1]
    text = extend_env(env['data'].decode(), mode)
    replacement = MK.pack('c', env['group'], env['mode'], env['uid'], env['gid'], 'hk_env', text.encode())
    body = b''.join(replacement if r is env else r['raw'] for r in rows)
    body += MK.pack('f', env['group'], 0o755, 0, 0, LIBRARY, library)
    output = MK.MAGIC + struct.pack('<IIQ', 24+len(body), len(rows)+1, MK.fnv1a(body)) + body
    if len(output) > MK.TOTAL_MAX:
        raise ValueError('overlay too large')
    new = records(output)
    for before, after in zip(rows, new):
        if before is not env:
            assert before['raw'] == after['raw']
    receipt = dict(base_sha256=base_sha, overlay_sha256=sha(output), dylib_sha256=sha(library),
                   mask=hex(mask), mode=mode, group=env['group'], bytes=len(output),
                   preserved_records=len(rows)-1, modified_records=1, appended_records=1, hk_env=text,
                   selected_base_records=[dict(path=r['path'], kind=r['kind'], group=r['group'],
                                               sha256=sha(r['raw'])) for r in chosen])
    return output, receipt


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--base-sha', required=True)
    ap.add_argument('--library', type=Path, default=DEFAULT_OUTPUT/'build/hsampler.dylib')
    ap.add_argument('--mkoverlay', type=Path, default=DEFAULT_MKOVERLAY)
    ap.add_argument('--mask', type=lambda x:int(x, 0), default=0xA0080081)
    ap.add_argument('--mode', choices=('off', 'observe', 'verify', 'fast'), default='off')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output = generated(args.output)
    configure(args.mkoverlay)
    out, receipt = compose(args.base.read_bytes(), args.base_sha, args.library.read_bytes(), args.mask, args.mode)
    if args.output.exists() or args.output.with_suffix('.json').exists():
        raise ValueError('output exists; choose a new name')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(out)
    args.output.with_suffix('.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k != 'selected_base_records'}, indent=2))


if __name__ == '__main__':
    main()
