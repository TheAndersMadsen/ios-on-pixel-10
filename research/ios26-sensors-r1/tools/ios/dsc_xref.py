#!/usr/bin/env python3
"""Find code in one dyld-cache image that references a C string: first the __cfstring entries (or pointer slots)
whose target is the string, then adrp+add/ldr pairs in __TEXT,__text that resolve to the string or one of those
entries. Prints `code_addr -> target (kind)`. Host reading aid; pair it with cbdis.py on the hits.

    dsc_xref.py CACHE IMAGE_SUBSTRING STRING
"""
import re, struct, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dsc_cstr as K

MASK, BASE = 0x3ffffffff, 0x180000000


def main():
    cache, sub, want = K.LP.CacheImages(sys.argv[1]), sys.argv[2], sys.argv[3].encode() + b'\0'
    base, path = next((a, p) for a, p in cache.images if p.endswith(sub))
    secs = K.sections(cache, base)
    targets = {}
    for seg, sect, addr, sz in secs:
        if seg == b'__TEXT' and sect in (b'__cstring', b'__oslogstring'):
            data = cache.read(addr, sz)
            for m in re.finditer(re.escape(want), data):
                if m.start() == 0 or data[m.start() - 1] == 0:
                    targets[addr + m.start()] = 'cstring'
    strs = set(targets)
    for seg, sect, addr, sz in secs:
        if sect in (b'__cfstring',) or (seg.startswith(b'__AUTH_CONST') or seg.startswith(b'__DATA_CONST')) and sect == b'__const':
            data = cache.read(addr, sz)
            step = 32 if sect == b'__cfstring' else 8
            for i in range(0, sz - step + 1, step):
                p = struct.unpack_from('<Q', data, i + (16 if sect == b'__cfstring' else 0))[0]
                if (p & MASK) + BASE in strs:
                    targets[addr + i] = sect.decode()
    print(f'# {path}: targets', {hex(k): v for k, v in targets.items()})
    for seg, sect, addr, sz in secs:
        if seg != b'__TEXT' or sect != b'__text':
            continue
        data = cache.read(addr, sz)
        regs = {}
        for i in range(0, sz, 4):
            ins = struct.unpack_from('<I', data, i)[0]
            pc = addr + i
            if ins & 0x9f000000 == 0x90000000:
                imm = ((ins >> 29) & 3) | (((ins >> 5) & 0x7ffff) << 2)
                if imm & (1 << 20):
                    imm -= 1 << 21
                regs[ins & 31] = (pc & ~0xfff) + (imm << 12)
                continue
            rn = (ins >> 5) & 31
            if rn in regs:
                if ins & 0xff800000 == 0x91000000:
                    t = regs[rn] + ((ins >> 10) & 0xfff)
                elif ins & 0xffc00000 == 0xf9400000:
                    t = regs[rn] + ((ins >> 10) & 0xfff) * 8
                else:
                    continue
                if t in targets:
                    print(f'{pc:#x} -> {t:#x} ({targets[t]})')


if __name__ == '__main__':
    main()
