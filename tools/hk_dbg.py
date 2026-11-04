#!/usr/bin/env python3
"""Encode/decode the packed hk_dbg=0x... boot-arg (XNU hk-int2-ui osfmk/kern/hk_dbg.h).

    python3 -I tools/hk_dbg.py encode --input --snap --usertrace --ustack --crashinfo --screen 30 --top 30
    hk_dbg=0x1e1e1f
    python3 -I tools/hk_dbg.py decode 0x1e1e1f
    python3 -I tools/hk_dbg.py expand "<a whole command line>"     # the equivalent separate tokens and the bytes saved

Layout: bit 0 input (blazer_usbcon_input=1), 1 snap (blazer_usbcon_snap=1), 2 usertrace (hk_usertrace=1),
3 ustack (hk_ustack=Preferences,MobilePhone when no hk_ustack= is given), 4 crashinfo (hk_crashinfo=1, needs usertrace),
bits 8..15 hk_screen period (0, 1 or >= 10), bits 16..23 hk_top period (0 or 5..255).
"""
import argparse
import sys

FLAGS = (('input', 0x01, 'blazer_usbcon_input=1'), ('snap', 0x02, 'blazer_usbcon_snap=1'),
         ('usertrace', 0x04, 'hk_usertrace=1'), ('ustack', 0x08, 'hk_ustack=Preferences,MobilePhone'),
         ('crashinfo', 0x10, 'hk_crashinfo=1'))
KNOWN = 0x1f | 0xffff00


def encode(input=False, snap=False, usertrace=False, ustack=False, crashinfo=False, screen=0, top=0):
    if screen not in (0, 1) and not 10 <= screen <= 255:
        raise ValueError('screen period: 0, 1 or 10..255')
    if top and not 5 <= top <= 255:
        raise ValueError('top period: 0 or 5..255')
    if crashinfo and not usertrace:
        raise ValueError('crashinfo needs usertrace')
    v = sum(bit for (name, bit, _), on in zip(FLAGS, (input, snap, usertrace, ustack, crashinfo)) if on)
    v |= screen << 8 | top << 16
    if not v:
        raise ValueError('nothing to encode')
    return v


def token(v):
    return f'hk_dbg={v:#x}'


def decode(v):
    if v & ~KNOWN:
        raise ValueError(f'unknown bits {v & ~KNOWN:#x}')
    out = {name: bool(v & bit) for name, bit, _ in FLAGS}
    out.update(screen=v >> 8 & 0xff, top=v >> 16 & 0xff)
    return out


def tokens(v):
    """The separate tokens hk_dbg=v stands for."""
    d = decode(v)
    t = [tok for name, _, tok in FLAGS if d[name]]
    if d['screen']:
        t.append(f'hk_screen={d["screen"]}')
    if d['top']:
        t.append(f'hk_top={d["top"]}')
    return t


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('encode')
    for name, _, _ in FLAGS:
        e.add_argument(f'--{name}', action='store_true')
    e.add_argument('--screen', type=int, default=0)
    e.add_argument('--top', type=int, default=0)
    d = sub.add_parser('decode')
    d.add_argument('value')
    x = sub.add_parser('expand')
    x.add_argument('cmdline')
    a = p.parse_args()
    try:
        if a.cmd == 'encode':
            print(token(encode(a.input, a.snap, a.usertrace, a.ustack, a.crashinfo, a.screen, a.top)))
        elif a.cmd == 'decode':
            v = int(a.value.split('=')[-1], 16)
            print(decode(v))
            print(' '.join(tokens(v)))
        else:
            toks = a.cmdline.split()
            dbg = [t for t in toks if t.startswith('hk_dbg=')]
            if not dbg:
                print('no hk_dbg token')
                return 1
            sep = tokens(int(dbg[0].split('=')[1], 16))
            print(' '.join(sep))
            print(f'{len(dbg[0])} bytes instead of {len(" ".join(sep))} (+ separators): saves '
                  f'{len(" ".join(sep)) - len(dbg[0])} bytes; line {len(a.cmdline)} -> {len(a.cmdline) - len(dbg[0]) + len(" ".join(sep))} expanded')
    except ValueError as exc:
        print(f'hk_dbg: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
