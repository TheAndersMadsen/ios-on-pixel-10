#!/usr/bin/env python3
"""Decode the chooser's TSHIMST2 stamps (stages 0x00c0..0x00cb) from a dump.

  chooser_stamps.py DUMP [--base 0x95200000] [--nonce 0x...]

DUMP is a ramdump of the ramoops region (fastboot capture or QEMU pmemsave)."""
import argparse, struct, sys
NAMES = {0xc0: 'enter', 0xc1: 'segment', 0xc2: 'place', 0xc3: 'menu', 0xc4: 'key', 0xc5: 'pick', 0xc6: 'lz4',
         0xc7: 'verify', 0xc8: 'jump', 0xc9: 'csum', 0xca: 'el2-map', 0xcb: 'ui', 0xcc: 'display', 0x01: 'entry', 0x02: 'cpu-state',
         0x03: 'wdt-survey', 0x04: 'fdt-parse'}
FLAGS = {1: 'ENTER', 2: 'DONE', 4: 'TIMEOUT', 8: 'FAULT', 16: 'REFUSED'}
STAMP_PA = 0x95430000


def decode(d, base, nonce=None):
    o = STAMP_PA - base
    h = d[o:o + 64]
    if h[:8] != b'TSHIMST2': return None, 'no TSHIMST2 header'
    n, count, seq, last, fl, freq, t0 = struct.unpack_from('<QIIIIQQ', h, 8)
    if nonce is not None and n != nonce: return None, f'nonce {n:#x} != {nonce:#x}'
    rows = []
    for i in range(min(count, 128)):
        sq, st, f, t, arg = struct.unpack_from('<IHHQQ', d, o + 64 + 24 * i)
        rows.append(dict(seq=sq, stage=st, name=NAMES.get(st & 0xff, f'{st:#06x}'), flags=FLAGS.get(f & 0x1f, hex(f)),
                         ms=round((t - t0) / freq * 1000, 1) if freq else None, arg=arg))
    return dict(nonce=n, count=count, freq=freq, rows=rows), None


def explain(r):
    a, nm = r['arg'], r['name']
    if nm == 'enter': return f'EL{a >> 32} SCTLR_EL2={a & 0xffffffff:#x}'
    if nm in ('lz4',) and r['flags'] == 'DONE': return f'{a >> 32} ms, {a & 0xffffffff} B'
    if nm == 'csum': return f'{a >> 32} ms'
    if nm == 'el2-map': return f'wb={a >> 32} nc={(a >> 16) & 0xffff} refused={a & 0xffff}'
    if nm == 'ui': return f'full draw {a >> 32} ms, cached={a & 1}'
    if nm == 'display': return f'{a >> 32} ms, serror={(a >> 16) & 1}, dcs code={a & 0xffff}' + (' (present)' if (a >> 40) & 1 else '')
    if nm == 'pick': return f'after {a >> 8} ms, result={(a >> 4) & 15} why={a & 15}'
    if nm == 'jump': return f'base={a & ((1 << 63) - 1):#x} cached={a >> 63}'
    return hex(a)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('dump'); ap.add_argument('--base', type=lambda s: int(s, 0), default=0x95200000)
    ap.add_argument('--nonce', type=lambda s: int(s, 0)); a = ap.parse_args()
    res, err = decode(open(a.dump, 'rb').read(), a.base, a.nonce)
    if err: sys.exit(err)
    print(f"nonce {res['nonce']:#x} stamps {res['count']} cntfrq {res['freq']}")
    for r in res['rows']:
        print(f"{r['seq']:4} {r['name']:11} {r['flags']:8} {r['ms']!s:>10} ms  {explain(r)}")
