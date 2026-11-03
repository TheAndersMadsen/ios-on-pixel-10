#!/usr/bin/env python3
"""Host reading aid for the Control Center lane (dyld cache dsc-r6). Standard library only.

    ccsym.py CACHE images REGEX                 list images whose path matches
    ccsym.py CACHE syms IMAGE_REGEX NAME_REGEX  exported/global symbols of matching images
    ccsym.py CACHE str TEXT                     vm addresses of a C string (exact, NUL-terminated)
    ccsym.py CACHE xref IMAGE_REGEX TARGET      adrp+add/ldr references to TARGET inside the image's __TEXT
"""
import re, struct, sys
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S


def segs(c, base):
    h = c.read(base, 32); nc, size = struct.unpack_from('<II', h, 16)
    cmds = c.read(base + 32, size); off = 0; out = []
    for _ in range(nc):
        cmd, cs = struct.unpack_from('<II', cmds, off)
        if cmd == 0x19:
            name = cmds[off + 8:off + 24].split(b'\0')[0].decode()
            vm, vs = struct.unpack_from('<QQ', cmds, off + 24); out.append((name, vm, vs))
        off += cs
    return out


def main():
    c = S.LP.CacheImages(sys.argv[1]); op = sys.argv[2]
    if op == 'images':
        for a, p in c.images:
            if re.search(sys.argv[3], p): print(hex(a), p)
    elif op == 'syms':
        for a, p in c.images:
            if re.search(sys.argv[3], p):
                for v, n in S.image_symbols(c, a):
                    if re.search(sys.argv[4], n): print(hex(v), p.rsplit('/', 1)[-1], n)
    elif op == 'str':
        needle = b'\0' + sys.argv[3].encode() + b'\0'
        for lo, hi, fo, src in c.maps:
            src.seek(fo); data = src.read(hi - lo); i = data.find(needle)
            while i >= 0:
                print(hex(lo + i + 1)); i = data.find(needle, i + 1)
    elif op == 'xref':
        t = int(sys.argv[4], 0)
        for a, p in c.images:
            if not re.search(sys.argv[3], p): continue
            for name, vm, vs in segs(c, a):
                if name != '__TEXT': continue
                data = c.read(vm, vs)
                for i in range(0, len(data) - 8, 4):
                    w = struct.unpack_from('<I', data, i)[0]
                    if (w & 0x9f000000) != 0x90000000: continue
                    rd = w & 31; imm = ((w >> 29) & 3) | (((w >> 5) & 0x7ffff) << 2)
                    if imm & (1 << 20): imm -= 1 << 21
                    pg = ((vm + i) & ~0xfff) + (imm << 12)
                    if pg != t & ~0xfff: continue
                    for j in range(i + 4, min(i + 40, len(data) - 4), 4):
                        w2 = struct.unpack_from('<I', data, j)[0]
                        if (w2 & 0xffc00000) == 0x91000000 and ((w2 >> 5) & 31) == rd:
                            if pg + ((w2 >> 10) & 0xfff) == t: print(hex(vm + i), p.rsplit('/', 1)[-1], 'add')
                            break
                        if (w2 & 0xffc00000) == 0xf9400000 and ((w2 >> 5) & 31) == rd:
                            if pg + ((w2 >> 10) & 0xfff) * 8 == t: print(hex(vm + i), p.rsplit('/', 1)[-1], 'ldr')
                            break
    c.close()


if __name__ == '__main__':
    main()
