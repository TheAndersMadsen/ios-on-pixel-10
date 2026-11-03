#!/usr/bin/env python3
"""Find 8-byte cache pointers (34-bit runtime offset, any auth/high bits) to TARGET in every segment of one image.
    ptrref.py CACHE IMAGE TARGET"""
import struct, sys
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S
c = S.LP.CacheImages(sys.argv[1]); want = sys.argv[2]; T = int(sys.argv[3], 0) - 0x180000000
base = next(a for a, p in c.images if p.rsplit('/', 1)[-1] == want)
head = c.read(base, 32); nc, size = struct.unpack_from('<II', head, 16)
cmds = c.read(base + 32, size); off = 0
for _ in range(nc):
    cmd, cs = struct.unpack_from('<II', cmds, off)
    if cmd == 0x19:
        name = cmds[off + 8:off + 24].split(b'\0')[0].decode(); vm, vs = struct.unpack_from('<QQ', cmds, off + 24)
        if name != '__LINKEDIT' and name != '__TEXT':
            try: d = c.read(vm, vs)
            except Exception as e: print(name, 'unreadable', e); off += cs; continue
            for k in range(0, vs - 7, 8):
                (p,) = struct.unpack_from('<Q', d, k)
                if p and (p & 0x3ffffffff) == T: print(f'{name} {vm + k:#x}: {p:#x}')
    off += cs
