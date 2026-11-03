#!/usr/bin/env python3
"""xref.py BIN ADDR...: for each ADDR, the enclosing function start (last pacibsp before it) and every BL/B to that start
in __text (vm 0x100003918, fileoff = vm - 0x100000000; bluetoothd r3)."""
import struct, sys
d = open(sys.argv[1], 'rb').read(); TS, TZ = 0x100003918, 0x864d9c
ins = struct.unpack_from('<%dI' % (TZ // 4), d, TS - 0x100000000)
def start(a):
    i = (a - TS) // 4
    while i > 0 and ins[i] != 0xd503237f: i -= 1
    return TS + 4 * i
calls = {}
for k, w in enumerate(ins):
    if (w & 0x7c000000) == 0x14000000:
        imm = w & 0x3ffffff
        if imm & (1 << 25): imm -= 1 << 26
        calls.setdefault(TS + 4 * k + 4 * imm, []).append((TS + 4 * k, 'bl' if w >> 31 else 'b'))
for a in sys.argv[2:]:
    s = start(int(a, 16))
    print(a, 'in fn', hex(s), 'callers:', ' '.join(f'{k}@{hex(c)}(fn {hex(start(c))})' for c, k in calls.get(s, [])))
