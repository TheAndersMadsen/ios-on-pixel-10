#!/usr/bin/env python3
"""List an ObjC class's instance methods (name -> IMP) from an on-device dyld cache. Host reading aid.

    objcmeth.py CACHE CLASS_ADDR [--ref] [--meta] [--sel-base ADDR]

Direct-selector method lists (flag 0x40000000) store name offsets from the cache's relative-selector base. For cache
0f1ee332 that base is 0x1fa27fde0 (the default here): found by solving one known selector (getBacklightCalibration: at
0x1fc39ee9d, from selref 0x1e7b78398) against CBBacklightNode's list; every other entry then decoded to a valid name.
"""
import struct, sys
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-phaseb-r1/corebrightness')
import cbdis as D

B = 0x180000000


SEL_BASE = 0x1fa27fde0


def main():
    global SEL_BASE
    if '--sel-base' in sys.argv:
        SEL_BASE = int(sys.argv[sys.argv.index('--sel-base') + 1], 0)
    c = D.S.LP.CacheImages(sys.argv[1]); a = int(sys.argv[2], 0)
    q = lambda x: struct.unpack('<Q', c.read(x, 8))[0]
    fix = lambda p: (p & 0x3ffffffff) + B
    cls = a if '--ref' not in sys.argv else fix(q(a))  # class address, or a classref with --ref
    if '--meta' in sys.argv:
        cls = fix(q(cls))
    ro = fix(q(cls + 32)) & ~7
    name = D.cstr(c, fix(q(ro + 24)))
    ml = q(ro + 32)
    print(f'# class {name} at {cls:#x} ro {ro:#x}')
    if not ml:
        return
    ml = fix(ml)
    ef, cnt = struct.unpack('<II', c.read(ml, 8))
    es = ef & 0xfffc
    for i in range(cnt):
        e = ml + 8 + i * es
        if ef & 0x80000000:
            no, to, io = struct.unpack('<iii', c.read(e, 12))
            if ef & 0x40000000:
                sel = D.cstr(c, SEL_BASE + no)  # offset from the relative-selector base
            else:
                sel = D.cstr(c, fix(q(e + no)))
            imp = e + 8 + io
        else:
            n, t, imp = struct.unpack('<QQQ', c.read(e, 24))
            sel, imp = D.cstr(c, fix(n)), fix(imp)
        print(f'{imp:#x} -[{name} {sel}]')


if __name__ == '__main__':
    main()
