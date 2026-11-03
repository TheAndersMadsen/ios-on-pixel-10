#!/usr/bin/env python3
"""Name the frames of a userabort backtrace against an on-device dyld shared cache (no .symbols subcache needed).

    dsc_sym.py CACHE SLIDE ADDR [ADDR...]

For each slid address: unslid = addr - slide; the containing image (tools/live_profile.py CacheImages); then the
nearest preceding defined symbol from that image's own LC_SYMTAB (exported/global nlists stay in the cache's
linkedit; local symbols live in the absent .symbols file). The distance is printed: a large one means the real
function is a local (static or ObjC method) symbol and only the image is certain. Standard library only.
"""
import bisect
import importlib.util
import struct
import sys
from pathlib import Path

REPO = Path('/srv/dev/repos/personal/hackios')
spec = importlib.util.spec_from_file_location('live_profile', REPO / 'tools/live_profile.py')
LP = importlib.util.module_from_spec(spec); spec.loader.exec_module(LP)

N_STAB, N_TYPE, N_SECT = 0xe0, 0x0e, 0x0e


def image_symbols(cache, base):
    head = cache.read(base, 32)
    magic, _, _, _, nc, size, _, _ = struct.unpack('<IiiIIIII', head)
    assert magic == 0xfeedfacf, hex(magic)
    cmds = cache.read(base + 32, size)
    off, linkedit, symtab, text_vm = 0, None, None, None
    for _ in range(nc):
        cmd, cs = struct.unpack_from('<II', cmds, off)
        if cmd == 0x19:
            name = cmds[off + 8:off + 24].split(b'\0')[0]
            vm, vmsize, fo, fs = struct.unpack_from('<QQQQ', cmds, off + 24)
            if name == b'__LINKEDIT':
                linkedit = (vm, fo)
            if name == b'__TEXT':
                text_vm = vm
        elif cmd == 0x2:
            symtab = struct.unpack_from('<IIII', cmds, off + 8)
        off += cs
    if not (linkedit and symtab):
        return []
    symoff, nsyms, stroff, strsize = symtab
    lvm, lfo = linkedit
    at = lambda fileoff: lvm + (fileoff - lfo)
    raw = cache.read(at(symoff), nsyms * 16)
    strs = cache.read(at(stroff), strsize)
    out = []
    for i in range(nsyms):
        strx, ntype, nsect, _, value = struct.unpack_from('<IBBHQ', raw, i * 16)
        if ntype & N_STAB or (ntype & N_TYPE) != N_SECT or not value:
            continue
        end = strs.find(b'\0', strx)
        out.append((value, strs[strx:end].decode('utf-8', 'replace')))
    out.sort()
    return out


def main():
    cache = LP.CacheImages(sys.argv[1])
    slide = int(sys.argv[2], 0)
    print(f'cache uuid {cache.uuid}')
    memo = {}
    for a in sys.argv[3:]:
        addr = int(a, 0)
        u = addr - slide
        info = cache.who(u) if u > 0 else None
        if not info:
            print(f'{addr:#x} unslid {u:#x}: not in cache'); continue
        base = u - info['image_offset']
        syms = memo.get(base)
        if syms is None:
            syms = memo[base] = image_symbols(cache, base)
        i = bisect.bisect_right([s[0] for s in syms], u) - 1
        name, dist = (syms[i][1], u - syms[i][0]) if i >= 0 else ('?', None)
        img = info['image'].rsplit('/', 1)[-1]
        print(f'{addr:#x} unslid {u:#x}  {img} {info["segment"]}+{info["image_offset"]:#x}  nearest {name} +{dist:#x}' if dist is not None else f'{addr:#x} {img} (no symbol)')
    cache.close()


if __name__ == '__main__':
    main()
