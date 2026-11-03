#!/usr/bin/env python3
"""Find code references (adrp + add/ldr pairs, within 8 instructions) to target addresses inside one cache image's
__TEXT segment. Prints the referencing pc and the nearest preceding exported symbol. Host reading aid only.
    xref.py CACHE IMAGE_SUBSTRING TARGET [TARGET...]"""
import bisect, struct, sys
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S

c = S.LP.CacheImages(sys.argv[1]); want = sys.argv[2]; targets = {int(t, 0) for t in sys.argv[3:]}
base = next(a for a, p in c.images if p.endswith('/' + want) or p.rsplit('/', 1)[-1] == want)
c.who(base)
lo, hi, _ = next(s for s in c.segments[base] if s[2] == '__TEXT')
code = c.read(lo, hi - lo); n = len(code) // 4
ws = struct.unpack(f'<{n}I', code[:n * 4])
syms = S.image_symbols(c, base); starts = [s[0] for s in syms]
for i, w in enumerate(ws):
    if (w & 0x9f000000) != 0x90000000:
        continue
    rd = w & 31; pc = lo + i * 4
    immlo = (w >> 29) & 3; immhi = (w >> 5) & 0x7ffff
    imm = ((immhi << 2) | immlo) << 12
    if imm & (1 << 32): imm -= 1 << 33
    page = (pc & ~0xfff) + imm
    for j in range(i + 1, min(i + 9, n)):
        v = ws[j]
        if (v & 0xffc00000) == 0x91000000 and ((v >> 5) & 31) == rd:      # add xd, xn, #imm12
            t = page + ((v >> 10) & 0xfff)
        elif (v & 0xffc00000) == 0xf9400000 and ((v >> 5) & 31) == rd:    # ldr xt, [xn, #imm*8]
            t = page + ((v >> 10) & 0xfff) * 8
        else:
            continue
        if t in targets:
            k = bisect.bisect_right(starts, pc) - 1
            nm = f'{syms[k][1]}+{pc - syms[k][0]:#x}' if k >= 0 else '?'
            print(f'{pc:#x} -> {t:#x}  near {nm}')
        break
