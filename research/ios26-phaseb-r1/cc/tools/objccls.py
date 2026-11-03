#!/usr/bin/env python3
"""Superclass chain and instance (or class, --meta) method names of an ObjC class in dyld cache dsc-r6.
Host reading aid.    objccls.py CACHE CLASS_ADDR [--meta]
Relative-selector base 0x1fa27fde0 as in corebrightness/objcmeth.py (same cache)."""
import struct, sys
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S
B, SEL_BASE = 0x180000000, 0x1fa27fde0
c = S.LP.CacheImages(sys.argv[1])
q = lambda x: struct.unpack('<Q', c.read(x, 8))[0]
fix = lambda p: (p & 0x3ffffffff) + B


def cstr(a):
    b = c.read(a, 200)
    return b[:b.find(b'\0')].decode('ascii', 'replace')


def name(cls):
    return cstr(fix(q((fix(q(cls + 32)) & ~7) + 24)))


def methods(cls):
    ro = fix(q(cls + 32)) & ~7
    ml = q(ro + 32); out = []
    if not ml:
        return out
    ml = fix(ml); ef, cnt = struct.unpack('<II', c.read(ml, 8)); es = ef & 0xfffc
    for i in range(cnt):
        e = ml + 8 + i * es
        if ef & 0x80000000:
            no, to, io = struct.unpack('<iii', c.read(e, 12))
            out.append((e + 8 + io, cstr(SEL_BASE + no) if ef & 0x40000000 else cstr(fix(q(e + no)))))
        else:
            n, t, imp = struct.unpack('<QQQ', c.read(e, 24))
            try:
                out.append((fix(imp), cstr(fix(n))))
            except ValueError:
                out.append((fix(imp), f'?sel {n:#x}'))
    return out


cls = int(sys.argv[2], 0)
chain, k = [], cls
while k and len(chain) < 12:
    chain.append(name(k)); sup = q(k + 8); k = fix(sup) if sup & 0x3ffffffff else 0
print('chain:', ' -> '.join(chain))
meta = '--meta' in sys.argv
for imp, sel in methods(fix(q(cls)) if meta else cls):
    print(f'{imp:#x} {"+" if meta else "-"}[{chain[0]} {sel}]')
