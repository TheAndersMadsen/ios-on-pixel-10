#!/usr/bin/env python3
"""Decode the constant ObjC literal dictionaries (__DATA*,__objc_dictobj) of a standalone arm64e Mach-O: keys and values
resolved to CFString text, NSConstantIntegerNumber values, nested constant arrays/dicts. Host reading aid.

    objc_dicts.py MACHO [REGEX]      prints `0xADDR {key: value, ...}` for dictionaries whose text matches REGEX
Chained-fixup rebases are read as a 36-bit (64-bit-offset format) or 32-bit (auth) target offset from the image base;
binds (class isa pointers) are not resolved. Standard library only."""
import re, struct, sys

def load(path):
    b = open(path, 'rb').read()
    magic, _, _, _, nc, _, _, _ = struct.unpack_from('<IiiIIIII', b, 0)
    assert magic == 0xfeedfacf
    off, segs, sects = 32, [], {}
    for _ in range(nc):
        cmd, cs = struct.unpack_from('<II', b, off)
        if cmd == 0x19:
            name = b[off + 8:off + 24].split(b'\0')[0]
            vm, vs, fo, fs = struct.unpack_from('<QQQQ', b, off + 24)
            segs.append((vm, vs, fo, fs, name))
            ns = struct.unpack_from('<I', b, off + 64)[0]
            for k in range(ns):
                so = off + 72 + 80 * k
                sn = b[so:so + 16].split(b'\0')[0]
                a, sz, fo2 = struct.unpack_from('<QQI', b, so + 32)
                sects.setdefault(sn, []).append((a, sz, fo2))
        off += cs
    return b, segs, sects

def main():
    b, segs, sects = load(sys.argv[1]); rx = re.compile(sys.argv[2], re.I) if len(sys.argv) > 2 else None
    base = min(s[0] for s in segs if s[4] == b'__TEXT')
    def fo(va):
        for vm, vs, f, fs, _ in segs:
            if vm <= va < vm + fs:
                return f + va - vm
        return None
    def q(va):
        o = fo(va); return None if o is None else struct.unpack_from('<Q', b, o)[0]
    def ptr(raw):
        if raw is None: return None
        if raw >> 63:            # auth
            return None if (raw >> 62) & 1 else base + (raw & 0xffffffff)
        if (raw >> 62) & 1: return None   # bind
        return base + (raw & 0xfffffffff)
    def cstr(va):
        o = fo(va)
        if o is None: return None
        e = b.find(b'\0', o); return b[o:e].decode('utf-8', 'replace')
    ranges = {k: v for k, v in sects.items()}
    def inside(va, name):
        return any(a <= va < a + sz for a, sz, _ in ranges.get(name, []))
    def val(va, depth=0):
        if va is None: return '?'
        if inside(va, b'__cfstring'): return repr(cstr(ptr(q(va + 16))))
        if inside(va, b'__objc_intobj'):
            o = fo(va); enc = cstr(ptr(q(va + 8))) or '?'; v = struct.unpack_from('<q', b, o + 16)[0]
            return hex(v) if abs(v) > 9 else str(v)
        if inside(va, b'__objc_doubleobj') or inside(va, b'__objc_floatobj'):
            o = fo(va); return str(struct.unpack_from('<d' if inside(va, b'__objc_doubleobj') else '<f', b, o + 16 if inside(va, b'__objc_doubleobj') else 8)[0])
        if inside(va, b'__objc_arrayobj') and depth < 3:
            n = q(va + 8); items = ptr(q(va + 16))
            return '[' + ', '.join(val(ptr(q(items + 8 * i)), depth + 1) for i in range(n or 0)) + ']'
        if inside(va, b'__objc_dictobj') and depth < 3:
            return dct(va, depth + 1)
        return f'<{va:#x}>'
    def dct(va, depth=0):
        n = q(va + 16); ks = ptr(q(va + 24)); vs = ptr(q(va + 32))
        if not n or n > 64 or ks is None or vs is None: return '{?}'
        return '{' + ', '.join(f'{val(ptr(q(ks + 8 * i)), depth)}: {val(ptr(q(vs + 8 * i)), depth)}' for i in range(n)) + '}'
    for a, sz, _ in sects.get(b'__objc_dictobj', []):
        for va in range(a, a + sz, 40):
            t = dct(va)
            if rx is None or rx.search(t):
                print(f'{va:#x} {t}')

if __name__ == '__main__':
    main()
