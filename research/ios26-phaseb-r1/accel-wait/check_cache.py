#!/usr/bin/env python3
"""Re-derive every constant in src/hka_decide.h from the dyld cache and assert it. Prints PASS or raises.
    check_cache.py CACHE"""
import re, struct, sys
from pathlib import Path
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S
H = (Path(__file__).resolve().parent / 'src/hka_decide.h').read_text()
k = {m[1]: int(m[2], 16) for m in re.finditer(r'#define (HKA_\w+)\s+(?:UINT64_C\()?(0x[0-9a-f]+)', H)}
uuid = bytes(int(x, 16) for x in re.search(r'hka_qc_uuid\[16\] = \{([^}]*)\}', H)[1].split(','))
c = S.LP.CacheImages(sys.argv[1]); assert c.uuid.startswith('0f1ee332'), c.uuid
fnv = lambda b: __import__('functools').reduce(lambda h, x: ((h ^ x) * 0x100000001b3) & (2**64 - 1), b, 0xcbf29ce484222325)
base = next(a for a, p in c.images if p.endswith('/QuartzCore.framework/QuartzCore')); assert base == k['HKA_QC_BASE']
nc, size = struct.unpack_from('<II', c.read(base, 32), 16); cmds = c.read(base + 32, size); off = 0; secs = {}
for _ in range(nc):
    cmd, cs = struct.unpack_from('<II', cmds, off)
    if cmd == 0x1b: assert cmds[off + 8:off + 24] == uuid, 'QuartzCore UUID'
    if cmd == 0x19:
        ns = struct.unpack_from('<I', cmds, off + 64)[0]
        for j in range(ns):
            so = off + 72 + 80 * j; a, sz = struct.unpack_from('<QQ', cmds, so + 32)
            secs[(cmds[so + 16:so + 32].split(b'\0')[0].decode(), cmds[so:so + 16].split(b'\0')[0].decode())] = (a, sz)
    off += cs
inside = lambda t, s: secs[s][0] <= t < secs[s][0] + secs[s][1]
assert inside(k['HKA_PRED'], ('__DATA', '__bss')), 'predicate is not in __DATA,__bss'
assert inside(k['HKA_BLOCK_INVOKE_P'], ('__AUTH_CONST', '__const'))
assert fnv(c.read(k['HKA_WAIT_FN'], k['HKA_WAIT_LEN'])) == k['HKA_WAIT_FNV']
assert fnv(c.read(k['HKA_CREATE_FN'], k['HKA_CREATE_LEN'])) == k['HKA_CREATE_FNV']
assert (struct.unpack('<Q', c.read(k['HKA_BLOCK_INVOKE_P'], 8))[0] & 0x3ffffffff) + 0x180000000 == k['HKA_WAIT_FN']
assert struct.unpack('<I', c.read(k['HKA_BLOCK_INVOKE_P'] - 8, 4))[0] == 0x50000000, 'global block flags'
# The create function loads &pred and &block, and the wait loop's bound and sleep are what FINDINGS states.
w = struct.unpack(f'<{k["HKA_CREATE_LEN"] // 4}I', c.read(k['HKA_CREATE_FN'], k['HKA_CREATE_LEN']))
def adrp_add(i, pc):
    a, b = w[i], w[i + 1]; immlo = (a >> 29) & 3; immhi = (a >> 5) & 0x7ffff; imm = ((immhi << 2) | immlo) << 12
    if imm & (1 << 32): imm -= 1 << 33
    return (pc & ~0xfff) + imm + ((b >> 10) & 0xfff)
refs = {adrp_add(i, k['HKA_CREATE_FN'] + 4 * i) for i in range(len(w) - 1) if (w[i] & 0x9f000000) == 0x90000000 and (w[i + 1] & 0xffc00000) == 0x91000000}
assert k['HKA_PRED'] in refs and k['HKA_BLOCK_INVOKE_P'] - 0x10 in refs, [hex(x) for x in refs]
lw = struct.unpack(f'<{k["HKA_WAIT_LEN"] // 4}I', c.read(k['HKA_WAIT_FN'], k['HKA_WAIT_LEN']))
assert 0x7104aebf in lw, 'cmp w21, #0x12b'                       # loop bound 299 -> 301 tries
assert 0x5290d400 in lw and 0x72a00020 in lw, 'mov/movk w0, #100000'  # usleep(100000)
print(f'PASS cache {c.uuid}: QuartzCore {base:#x} uuid {uuid.hex()}, pred {k["HKA_PRED"]:#x} in __DATA,__bss, '
      f'block {k["HKA_BLOCK_INVOKE_P"] - 0x10:#x} -> {k["HKA_WAIT_FN"]:#x}, fingerprints, bound 0x12b, usleep 100000')
