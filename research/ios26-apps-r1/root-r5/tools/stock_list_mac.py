#!/usr/bin/env python3
"""List every entry of the stock 23G90 OS volume (attached -readonly -nobrowse -owners on): path, type, size, uid:gid,
mode. Read-only for the dmg. Used to find what r3's prune removed (diff against an r4/r5 census on m1box).
  python3 -I stock_list_mac.py IPSW_DIR OUT.tsv"""
import os, plistlib, stat, subprocess, sys, tempfile
IPSW, OUT = map(os.path.abspath, sys.argv[1:3])
m = plistlib.load(open(os.path.join(IPSW, 'BuildManifest.plist'), 'rb'))['BuildIdentities'][0]['Manifest']
p = m['OS']['Info']['Path']; dmg = os.path.join(IPSW, p[:-4] if p.endswith('.aea') else p)
mnt = tempfile.mkdtemp()
subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noverify', '-noautofsck', '-owners', 'on', '-mountpoint', mnt, dmg], check=True, capture_output=True)
try:
    with open(OUT, 'w', errors='surrogateescape') as o:
        for dp, dn, fn in os.walk(mnt):
            dn.sort()
            for n in sorted(dn + fn):
                q = os.path.join(dp, n); st = os.lstat(q); r = os.path.relpath(q, mnt)
                k = 'd' if stat.S_ISDIR(st.st_mode) else 'l' if stat.S_ISLNK(st.st_mode) else 'f'
                o.write(f'{r}\t{k}\t{st.st_size if k == "f" else 0}\t{st.st_uid}:{st.st_gid}\t{oct(stat.S_IMODE(st.st_mode))}\n')
finally:
    subprocess.run(['hdiutil', 'detach', mnt], check=True, capture_output=True)
