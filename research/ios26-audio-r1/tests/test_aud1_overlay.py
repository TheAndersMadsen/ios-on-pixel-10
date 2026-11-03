#!/usr/bin/env python3
"""HOST ONLY. Tests for tools/aud1_overlay.py against the pinned inputs, with a walker of its own (not RC/MK).

    python3 -I research/ios26-audio-r1/tests/test_aud1_overlay.py
Checks: the merge's output decodes with this file's own parser; header size/count/fnv; int1's records other than [39]
byte-identical in place; [39] differs only in SpringBoard's DYLD_INSERT_LIBRARIES; s1b's groups 24/25 byte-identical
and in order; one tone record in group 29 with s1b's bytes; mask 0xA0080081 applies no record of groups 24/25; every
group-24/25 path is under its cover prefix; kernel limits (count 4096, 48 MiB, rules 1024, var 384); and refusals:
wrong pins, a doubled SpringBoard rule, int1 already holding group 24.
"""
import hashlib, importlib.util, os, struct, sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('aud1', os.environ.get('AUD1_TOOL') or REPO / 'research/ios26-audio-r1/tools/aud1_overlay.py')
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
INT1 = REPO / 'research/ios26-phaseb-r1/int/overlays/int1-r1.ovl'
S1B = REPO / 'research/ios26-audio-r1/inputs/audio-s1b.ovl'
fails = checks = 0


def ok(cond, what):
    global fails, checks
    checks += 1
    if not cond:
        fails += 1
        print('FAIL', what)


def fnv(b):
    h = 0xcbf29ce484222325
    for x in b:
        h = ((h ^ x) * 0x100000001b3) & (1 << 64) - 1
    return h


def walk(blob):
    """own parser, varfs_overlay.h layout: header 24 B, entries 24 B + path NUL pad8 + data pad8."""
    assert blob[:8] == b'HKVAROV1'
    size, count, h = struct.unpack_from('<IIQ', blob, 8)
    assert size == len(blob) and h == fnv(blob[24:])
    off, out = 24, []
    for _ in range(count):
        kind, grp, mode, uid, gid, pl, dl = struct.unpack_from('<BB2xIIIII', blob, off)
        p0 = off + 24
        path = blob[p0:p0 + pl].decode()
        assert blob[p0 + pl] == 0
        d0 = (p0 + pl + 1 + 7) & ~7
        data = blob[d0:d0 + dl]
        end = (d0 + dl + 7) & ~7
        out.append(dict(kind=chr(kind), group=grp, mode=mode, uid=uid, gid=gid, path=path, data=data, raw=blob[off:end]))
        off = end
    assert off == size
    return out


i1, sb = INT1.read_bytes(), S1B.read_bytes()
out, rep = A.merge(i1, sb)
base, s1b, new = walk(i1), walk(sb), walk(out)
ok(len(new) == 317 and rep['records'] == 317, 'record count 52 + 5 + 259 + 1')
ok(len(out) <= 48 << 20 and len(new) <= 4096, 'kernel limits HKOV_TOTAL_MAX / HKOV_COUNT_MAX')
ok(all(new[i]['raw'] == base[i]['raw'] for i in range(52) if i != 39), 'int1 records other than [39] byte-identical in place')
ok({k: new[39][k] for k in ('kind', 'group', 'mode', 'uid', 'gid', 'path')} ==
   {k: base[39][k] for k in ('kind', 'group', 'mode', 'uid', 'gid', 'path')}, '[39] header fields unchanged')
b39, n39 = base[39]['data'], new[39]['data']
ok(n39.replace(b'hkbattery.dylib:/private/var/hk/hkaudiotest.dylib;', b'hkbattery.dylib;') == b39, '[39] differs only by the tone path')
rules = {r.split(b':', 1)[0]: r for r in n39.split(b',')}
ok(rules[b'SpringBoard'].count(b'DYLD_INSERT_LIBRARIES=') == 1, 'SpringBoard has one DYLD_INSERT_LIBRARIES')
ok(b'DYLD_INSERT_LIBRARIES=/private/var/hk/hkbattery.dylib:/private/var/hk/hkaudiotest.dylib;' in rules[b'SpringBoard'], 'SpringBoard loads hkbattery then the tone client')
ok(all(rules[k] == r for k, r in {r.split(b':', 1)[0]: r for r in b39.split(b',')}.items() if k != b'SpringBoard'), 'other programs\' rules unchanged')
ok(len(n39) + 1 <= 1024 and all(len(v) + 1 <= 384 for r in n39.split(b',') for v in r.split(b':', 1)[1].split(b';')), 'HK_RULES_MAX / HK_VAR_MAX')
hal = [r for r in s1b if r['group'] == 24]
tun = [r for r in s1b if r['group'] == 25]
ok([r['raw'] for r in new[52:57]] == [r['raw'] for r in hal], 'group 24 byte-identical, in order')
ok([r['raw'] for r in new[57:316]] == [r['raw'] for r in tun], 'group 25 byte-identical, in order')
ok(all(r['path'].startswith('/private/var/hkcover/hal') or r['path'] == '/private/var/hkcover' for r in new if r['group'] == 24), 'group 24 under the HAL cover prefix')
ok(all(r['path'].startswith('/private/var/hkcover/tun') or r['path'] == '/private/var/hkcover' for r in new if r['group'] == 25), 'group 25 under the tunings cover prefix')
tone_src = [r for r in s1b if r['path'] == A.TONE_PATH and r['kind'] == 'f'][0]
t = new[-1]
ok(t['kind'] == 'f' and t['group'] == 29 and t['path'] == A.TONE_PATH and t['data'] == tone_src['data']
   and (t['mode'], t['uid'], t['gid']) == (tone_src['mode'], tone_src['uid'], tone_src['gid']), 'tone record: s1b bytes, group 29')
ok(hashlib.sha256(t['data']).hexdigest().startswith('9ac322067ddb1791'), 'tone dylib is audio-s1b.json\'s 9ac32206')
ok(not any(A.MASK >> r['group'] & 1 for r in new if r['group'] in (24, 25)), 'mask applies no group 24/25 record')
ok(sorted({r['group'] for r in new if A.MASK >> r['group'] & 1}) == [0, 7, 19, 29, 31], 'applied groups as in int1')
ok(new.index(t) > [r['path'] for r in new].index('/private/var/hk'), 'parent /private/var/hk (int1 [35]) before the tone file')
ok(not any(r['group'] in (26, 27) for r in new[52:]), 's1b groups 26/27 not taken')
# refusals
for what, args in (('int1 pin', (i1[:-1] + bytes([i1[-1] ^ 1]), sb)), ('s1b pin', (i1, sb[:-1] + bytes([sb[-1] ^ 1])))):
    try:
        A.merge(*args)
        ok(False, f'refuses {what}')
    except ValueError:
        ok(True, what)
saved = A.PIN['int1']
# an int1 with a doubled SpringBoard rule: the merge must refuse it
recs = [r['raw'] for r in base]
recs[39] = A.MK.pack('c', 29, 0, 0, 0, 'hk_env', b39 + b',' + A.SB_OLD[:-1])
body = b''.join(recs)
bad = A.MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(recs), fnv(body)) + body
A.PIN['int1'] = hashlib.sha256(bad).hexdigest()
try:
    A.merge(bad, sb)
    ok(False, 'refuses two SpringBoard hkbattery rules')
except ValueError:
    ok(True, 'two rules')
recs = [r['raw'] for r in base] + [A.MK.pack('d', 24, 0o755, 0, 0, '/private/var/hkcover', b'')]
body = b''.join(recs)
bad = A.MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(recs), fnv(body)) + body
A.PIN['int1'] = hashlib.sha256(bad).hexdigest()
try:
    A.merge(bad, sb)
    ok(False, 'refuses int1 with group 24')
except ValueError:
    ok(True, 'group 24 taken')
A.PIN['int1'] = saved
print(f'aud1 overlay host test: {checks} checks, {fails} failed; output {rep["output_sha256"]} {rep["bytes"]} B')
sys.exit(1 if fails else 0)
