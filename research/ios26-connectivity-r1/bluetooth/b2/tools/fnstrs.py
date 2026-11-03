#!/usr/bin/env python3
"""fnstrs.py DIS.txt BIN LO HI: C strings and CFStrings that adrp+add in [LO,HI] point at (bluetoothd r3 layout)."""
import re, struct, sys
lines = open(sys.argv[1]).read().split('\n'); d = open(sys.argv[2], 'rb').read(); lo, hi = int(sys.argv[3], 16), int(sys.argv[4], 16)
pend = {}
for l in lines:
    m = re.match(r'\s*([0-9a-f]+):\s+(\S+)\s+(.*)', l)
    if not m: continue
    a = int(m[1], 16)
    if a < lo or a > hi: continue
    op, arg = m[2], m[3]
    mm = re.match(r'(x\d+), 0x([0-9a-f]+)', arg)
    if op == 'adrp' and mm: pend[mm[1]] = int(mm[2], 16); continue
    mm = re.match(r'(x\d+), (x\d+), #0x([0-9a-f]+)', arg)
    if op == 'add' and mm and mm[2] in pend:
        t = pend[mm[2]] + int(mm[3], 16) - 0x100000000
        if 0x91e550 <= t < 0xafbe08:
            e = d.find(b'\0', t); print(hex(a), d[t:e][:100])
        elif 0xafbe08 <= t < 0xb40000:
            p = struct.unpack_from('<Q', d, t + 16)[0] & 0xfffffffff; n = struct.unpack_from('<Q', d, t + 24)[0]
            print(hex(a), '@', d[p:p + min(n, 100)])
    if op.startswith('bl') and 'x' not in arg[:1]: pass
