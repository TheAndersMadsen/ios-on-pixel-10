#!/usr/bin/env python3
"""Find b/bl to a target and adrp+add of it (function-pointer uses, e.g. dispatch_once blocks) in one image's __TEXT.
    blref.py CACHE IMAGE TARGET"""
import struct, sys
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S
c = S.LP.CacheImages(sys.argv[1]); want = sys.argv[2]; T = int(sys.argv[3], 0)
base = next(a for a, p in c.images if p.rsplit('/', 1)[-1] == want); c.who(base)
lo, hi, _ = next(s for s in c.segments[base] if s[2] == '__TEXT')
code = c.read(lo, hi - lo); n = len(code) // 4; ws = struct.unpack(f'<{n}I', code[:n * 4])
for i, w in enumerate(ws):
    pc = lo + i * 4
    if (w & 0x7c000000) == 0x14000000:
        off = w & 0x3ffffff
        if off & (1 << 25): off -= 1 << 26
        if pc + off * 4 == T: print(f'{pc:#x} {"bl" if w >> 31 else "b"}')
    elif (w & 0x9f000000) == 0x90000000:
        rd = w & 31; immlo = (w >> 29) & 3; immhi = (w >> 5) & 0x7ffff
        imm = ((immhi << 2) | immlo) << 12
        if imm & (1 << 32): imm -= 1 << 33
        page = (pc & ~0xfff) + imm
        for j in range(i + 1, min(i + 9, n)):
            v = ws[j]
            if (v & 0xffc00000) == 0x91000000 and ((v >> 5) & 31) == rd:
                if page + ((v >> 10) & 0xfff) == T: print(f'{pc:#x} adrp+add')
                break
