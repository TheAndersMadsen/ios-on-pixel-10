#!/usr/bin/env python3
"""HOST ONLY. The overlay for a7-ios-system-int1: perf-r1 (95701ed9) + pwr-r1's changes (d0804b36) + app2-r1's changes (0eb06481).

Both sources are perf-r1 with records replaced in place and records appended. This is a record-level 3-way merge over the base:
  - for each base record i (0..48): take the source that changed it; refuse if both changed it (none do: pwr [0], app2 [39]);
  - appended: app2's two (TCC dir, hk_stderr_console.dylib) first, then pwr's localtime last. So int1 = app2-r1's 51 records
    with pwr's [0] and pwr's appended record, i.e. pwr's own transform applied to app2-r1: pwr_consumer.c (app2-r1 -> int1) applies unchanged.
Codec: ios26-overlay-r1/tools/mkoverlay.py (pack/fnv1a/MAGIC); second walker ios26-overlay2-r1/tools/restore_cloudd.py (decode).

    int_overlay.py BASE PWR APP2 OUT          (refuses to overwrite OUT; prints a JSON report)
    int_overlay.py --diff A B                 (decode-diff: records keyed by (type, group, path), plus index moves)
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
PIN = {'base': '95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55',
       'pwr': 'd0804b36bb540b1e63eeda033654e252ff4da8359b5c0f1d6f6d1af631b27b97',
       'app2': '0eb06481d31376b95684dbc6bc53a005adff7ae3e03e967a983f46e41605755e'}
MASK = 0xA0080081


def split(base, src):
    """indices of replaced base records and the appended raw records of src (perf-r1 + in-place + appended)."""
    if len(src) < len(base):
        raise ValueError('source shorter than base')
    for i, (a, b) in enumerate(zip(base, src)):
        if a[7] != b[7] and a[:2] + a[5:6] != b[:2] + b[5:6]:
            raise ValueError(f'record {i}: type/group/path changed, not an in-place edit')
    return [i for i, (a, b) in enumerate(zip(base, src)) if a[7] != b[7]], src[len(base):]


def merge(bb, pb, ab):
    for k, blob in (('base', bb), ('pwr', pb), ('app2', ab)):
        if sha(blob) != PIN[k]:
            raise ValueError(f'{k} is not {PIN[k][:8]}')
    base, pwr, app2 = RC.decode(bb), RC.decode(pb), RC.decode(ab)
    pr, pa = split(base, pwr)
    ar, aa = split(base, app2)
    if set(pr) & set(ar):
        raise ValueError(f'both sources change {sorted(set(pr) & set(ar))}')
    keys = [(r[0], r[1], r[5]) for r in base + pa + aa]
    if len(set(keys)) != len(keys):
        raise ValueError('an appended record collides with another record')
    recs = [(pwr if i in pr else app2 if i in ar else base)[i][7] for i in range(len(base))] + [r[7] for r in aa] + [r[7] for r in pa]
    body = b''.join(recs)
    out = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(recs), MK.fnv1a(body)) + body
    if len(out) > MK.TOTAL_MAX:
        raise ValueError('too large')
    new = RC.decode(out)
    assert len(new) == len(base) + len(pa) + len(aa)
    # independent postconditions with the second walker: every record is the bytes of exactly the source that owns it
    assert all(new[i][7] == (pwr if i in pr else app2 if i in ar else base)[i][7] for i in range(len(base)))
    assert [r[7] for r in new[len(base):]] == [r[7] for r in aa + pa]
    assert new[0][7] == pwr[0][7] and new[39][7] == app2[39][7]
    return out, {'base': PIN['base'], 'pwr': PIN['pwr'], 'app2': PIN['app2'], 'output_sha256': sha(out), 'bytes': len(out),
                 'records': len(new), 'from_pwr_replaced': pr, 'from_app2_replaced': ar,
                 'appended': [f'[{len(base) + k}] {chr(r[0])} g{r[1]} {r[5]}' for k, r in enumerate(aa + pa)]}


def diff(a, b):
    ra, rb = RC.decode(a), RC.decode(b)
    ka = {(r[0], r[1], r[5]): (i, r) for i, r in enumerate(ra)}
    kb = {(r[0], r[1], r[5]): (i, r) for i, r in enumerate(rb)}
    if len(ka) != len(ra) or len(kb) != len(rb):
        raise ValueError('duplicate (type, group, path) keys: keyed diff not valid')
    same = moved = 0
    lines = []
    for k in sorted(set(ka) | set(kb), key=lambda k: (kb.get(k, ka.get(k))[0])):
        name = f'{chr(k[0])} g{k[1]} {k[2]}'
        if k not in kb:
            lines.append(f'ONLY-A [{ka[k][0]}] {name}')
        elif k not in ka:
            lines.append(f'ONLY-B [{kb[k][0]}] {name} {len(kb[k][1][6])} B sha256 {sha(kb[k][1][6])[:16]}')
        else:
            (ia, x), (ib, y) = ka[k], kb[k]
            if x[7] != y[7]:
                lines.append(f'DIFF [{ia}->{ib}] {name}: mode/uid/gid {oct(x[2])} {x[3]}:{x[4]} -> {oct(y[2])} {y[3]}:{y[4]}, '
                             f'{len(x[6])} -> {len(y[6])} B, sha256 {sha(x[6])[:16]} -> {sha(y[6])[:16]}')
            else:
                same += 1
                if ia != ib:
                    moved += 1
                    lines.append(f'MOVED [{ia}->{ib}] {name} (byte-identical)')
    head = f'A {sha(a)[:16]} ({len(ra)} records) vs B {sha(b)[:16]} ({len(rb)} records): {same} byte-identical ({moved} at a new index)'
    return '\n'.join([head] + lines)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--diff', action='store_true')
    p.add_argument('paths', nargs='+', type=Path)
    a = p.parse_args()
    if a.diff:
        print(diff(a.paths[0].read_bytes(), a.paths[1].read_bytes()))
        return
    base, pwr, app2, outp = a.paths
    out, rep = merge(base.read_bytes(), pwr.read_bytes(), app2.read_bytes())
    with outp.open('xb') as f:
        f.write(out)
    print(json.dumps(rep, indent=2))


if __name__ == '__main__':
    main()
