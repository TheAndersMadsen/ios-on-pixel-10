#!/usr/bin/env python3
"""For a standalone Mach-O and its `llvm-objdump --macho -d` listing: find the functions that reference a log string
(adrp+add pairs resolving to it), then every `bl` to those functions with the immediates last moved into w1..w3 before
the call, and the nearest preceding C string reference (the caller's own log/name). Host reading aid.

    macho_usage_calls.py MACHO LISTING 'needle text in the callee log string'"""
import bisect, re, struct, sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from objc_dicts import load

def main():
    b, segs, sects = load(sys.argv[1]); lines = open(sys.argv[2]).read().splitlines(); needle = sys.argv[3].encode()
    def fo(va):
        for vm, vs, f, fs, _ in segs:
            if vm <= va < vm + fs: return f + va - vm
    def cstr(va):
        o = fo(va)
        if o is None: return None
        e = b.find(b'\0', o, o + 300); s = b[o:e] if e > 0 else b''
        return s.decode('utf-8', 'replace') if len(s) >= 4 and all(32 <= c < 127 for c in s) else None
    targets = set()
    for name in (b'__cstring', b'__oslogstring'):
        for a, sz, off in sects.get(name, []):
            data = b[off:off + sz]; i = data.find(needle)
            while i >= 0:
                s = data.rfind(b'\0', 0, i) + 1; targets.add(a + s); i = data.find(needle, i + 1)
    addr = []; refs = {}; adrp = {}
    pc_re = re.compile(r'^([0-9a-f]+):\t(\w+)(?:\t(.*))?$')
    parsed = []
    for l in lines:
        m = pc_re.match(l)
        if not m: continue
        pc = int(m.group(1), 16); op, args = m.group(2), m.group(3) or ''; parsed.append((pc, op, args))
    func_starts = [pc for i, (pc, op, args) in enumerate(parsed) if op == 'pacibsp']
    def func_of(pc): i = bisect.bisect_right(func_starts, pc) - 1; return func_starts[i] if i >= 0 else None
    callees = set(); strref = {}
    for i, (pc, op, args) in enumerate(parsed):
        if op == 'adrp':
            m = re.match(r'x(\d+), \S+ ; (0x[0-9a-f]+)', args)
            if m: adrp[m.group(1)] = int(m.group(2), 16)
        elif op == 'add':
            m = re.match(r'x(\d+), x(\d+), #(0x[0-9a-f]+|\d+)\b', args)
            if m and m.group(2) in adrp:
                t = adrp[m.group(2)] + int(m.group(3), 0)
                if t in targets: callees.add(func_of(pc))
                s = cstr(t)
                if s: strref[pc] = s
    print('callee functions:', [hex(c) for c in callees if c])
    strpcs = sorted(strref)
    for i, (pc, op, args) in enumerate(parsed):
        if op != 'bl': continue
        try: t = int(args.split()[0], 16)
        except ValueError: continue
        if t not in callees: continue
        regs = {}
        for j in range(i - 1, max(0, i - 30), -1):
            p2, o2, a2 = parsed[j]
            if o2 == 'bl': break
            m = re.match(r'w([1-3]), #(0x[0-9a-f]+|\d+)$', a2)
            if o2 in ('mov', 'movz') and m and m.group(1) not in regs: regs[m.group(1)] = int(m.group(2), 0)
        k = bisect.bisect_left(strpcs, pc) - 1
        near = strref[strpcs[k]][:90] if k >= 0 and pc - strpcs[k] < 0x2000 else None
        print(f'{pc:#x} -> {t:#x} w1={regs.get("1","?") if not isinstance(regs.get("1"),int) else hex(regs["1"])} w2={hex(regs["2"]) if isinstance(regs.get("2"),int) else "?"} w3={hex(regs["3"]) if isinstance(regs.get("3"),int) else "?"} | {near}')

if __name__ == '__main__':
    main()
