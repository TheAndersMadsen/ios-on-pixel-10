#!/usr/bin/env python3
"""From a cbdis.py listing, print each call to IOKit:_IOHIDServiceClientConformsTo (or another named callee) with the
last immediate moved into w1/x1 and w2/x2 before it, and the nearest preceding @"..." CFString. Host reading aid.

    conforms.py LISTING [CALLEE_SUBSTRING]
"""
import re, sys

callee = sys.argv[2] if len(sys.argv) > 2 else '_IOHIDServiceClientConformsTo'
lines = open(sys.argv[1]).read().splitlines()
for i, l in enumerate(lines):
    if callee not in l or ' bl\t' not in l:
        continue
    regs, cf = {}, None
    for j in range(i - 1, max(0, i - 40), -1):
        m = re.match(r'0x\w+: (mov|movz|orr)\s+[wx]([12]), (?:[wx]zr, )?#(0x[0-9a-f]+|\d+)', lines[j])
        if m and m.group(2) not in regs:
            regs[m.group(2)] = int(m.group(3), 0)
        if ' bl\t' in lines[j]:
            break
    for j in range(i - 1, max(0, i - 400), -1):
        m = re.search(r'@"([^"]+)"', lines[j])
        if m:
            cf = m.group(1); break
    print(l.split(':')[0], 'page', hex(regs['1']) if '1' in regs else '?', 'usage', hex(regs['2']) if '2' in regs else '?', '| near', cf)
