#!/usr/bin/env python3
"""Grep the C strings (and __cfstring targets) of one image in an on-device dyld shared cache. Host reading aid.

    dsc_cstr.py CACHE IMAGE_SUBSTRING REGEX [--sections]

Prints `0xADDR section string` for every NUL-terminated printable string in the image's __TEXT,__cstring,
__TEXT,__oslogstring and __TEXT,__const sections that matches REGEX (Python re, case-insensitive).
Uses tools/live_profile.py's CacheImages (read-only). Standard library only.
"""
import importlib.util, re, struct, sys
from pathlib import Path

REPO = Path('/srv/dev/repos/personal/hackios')
spec = importlib.util.spec_from_file_location('live_profile', REPO / 'tools/live_profile.py')
LP = importlib.util.module_from_spec(spec); spec.loader.exec_module(LP)
WANT = {b'__cstring', b'__oslogstring', b'__const'}


def sections(cache, base):
    magic, _, _, _, nc, size, _, _ = struct.unpack('<IiiIIIII', cache.read(base, 32))
    assert magic == 0xfeedfacf
    cmds, off, out = cache.read(base + 32, size), 0, []
    for _ in range(nc):
        cmd, cs = struct.unpack_from('<II', cmds, off)
        if cmd == 0x19:
            seg = cmds[off + 8:off + 24].split(b'\0')[0]
            nsect = struct.unpack_from('<I', cmds, off + 64)[0]
            for k in range(nsect):
                so = off + 72 + 80 * k
                sect = cmds[so:so + 16].split(b'\0')[0]
                addr, sz = struct.unpack_from('<QQ', cmds, so + 32)
                out.append((seg, sect, addr, sz))
        off += cs
    return out


def main():
    cache, sub, rx = LP.CacheImages(sys.argv[1]), sys.argv[2], re.compile(sys.argv[3].encode(), re.I)
    hits = [(a, p) for a, p in cache.images if p.endswith('/' + sub) or p.endswith(sub)]
    if not hits:
        sys.exit(f'no image matching {sub}')
    for base, path in hits:
        print(f'# {path} @ {base:#x}')
        for seg, sect, addr, sz in sections(cache, base):
            if '--sections' in sys.argv:
                print(f'  {seg.decode()},{sect.decode()} {addr:#x} {sz:#x}')
            if seg != b'__TEXT' or sect not in WANT or sz > 64 << 20:
                continue
            data = cache.read(addr, sz)
            for m in re.finditer(rb'[\x20-\x7e\t]{3,}', data):
                if rx.search(m.group()):
                    print(f'{addr + m.start():#x} {sect.decode()} {m.group().decode()}')


if __name__ == '__main__':
    main()
