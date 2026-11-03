#!/usr/bin/env python3
"""Find every occurrence of a byte string in the mapped dyld cache and name the containing image.
    strfind.py CACHE STRING [--exact]   (--exact: require a NUL before and after, i.e. a whole C string)"""
import mmap, sys
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S

c = S.LP.CacheImages(sys.argv[1]); pat = sys.argv[2].encode(); exact = '--exact' in sys.argv
for lo, hi, off, src in c.maps:
    m = mmap.mmap(src.fileno(), 0, access=mmap.ACCESS_READ)
    i = m.find(pat, off, off + (hi - lo))
    while i >= 0:
        ok = not exact or (m[i - 1] == 0 and m[i + len(pat)] == 0)
        if ok:
            a = lo + i - off; w = c.who(a)
            e = m.find(b'\0', i); s = m[i:e][:100]
            print(f'{a:#x} {w["image"].rsplit("/",1)[-1] if w else "?"} {w["segment"] if w else ""} {s!r}')
        i = m.find(pat, i + 1, off + (hi - lo))
