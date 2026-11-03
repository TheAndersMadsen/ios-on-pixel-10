#!/usr/bin/env python3
"""List IOMobileFramebuffer exported functions and the IOConnectCall selector each loads (mov w1,#imm before a bl)."""
import sys, struct, subprocess, tempfile, re
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S
LP = S.LP
c = LP.CacheImages(sys.argv[1])
img = [(a, p) for a, p in c.images if p.endswith('/IOMobileFramebuffer')]
print(img)
base = img[0][0]
syms = S.image_symbols(c, base)
pat = sys.argv[2] if len(sys.argv) > 2 else ''
LLVM = '/home/anders/.local/share/hackios-host/llvm/bin/llvm-objdump'
for i, (a, n) in enumerate(syms):
    if pat and not re.search(pat, n): continue
    end = syms[i + 1][0] if i + 1 < len(syms) else a + 0x200
    ln = min(end - a, 0x600)
    if ln <= 0: continue
    try: b = c.read(a, ln)
    except Exception: continue
    with tempfile.NamedTemporaryFile(suffix='.bin') as f:
        f.write(b); f.flush()
        out = subprocess.run([LLVM, '-D', '-b', 'binary', '--triple=arm64e-apple-ios', '--adjust-vma=%#x' % a, f.name], capture_output=True, text=True).stdout
    sels = re.findall(r'mov\s+w1, #(0x[0-9a-f]+|\d+)', out)
    print('%#x %-70s sel %s' % (a, n, ','.join(str(int(s, 0)) for s in sels)))
