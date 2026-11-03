#!/usr/bin/env python3
"""Mac half of root-r5: copy the files r3's prune removed (PATHS, one root-relative path per line) out of the stock
23G90 OS volume (attached -readonly -nobrowse -owners on) into OUT/r5-files.tar. Data, owner, group, mode and mtime
only (tarfile writes no xattrs); every parent directory is in the tar too, with the stock metadata, so the m1box half
can create a missing directory exactly. Also lists the stock contents of each touched bundle (BUNDLES.tsv) so the
m1box half can report what else is missing in r4. Read-only for the dmg.
  python3 -I stage_r5_mac.py IPSW_DIR PATHS OUT_DIR"""
import hashlib, os, plistlib, stat, subprocess, sys, tarfile
IPSW, PATHS, OUT = map(os.path.abspath, sys.argv[1:4])
assert not os.path.exists(OUT), OUT
os.makedirs(OUT)
m = plistlib.load(open(os.path.join(IPSW, 'BuildManifest.plist'), 'rb'))['BuildIdentities'][0]['Manifest']
p = m['OS']['Info']['Path']; dmg = os.path.join(IPSW, p[:-4] if p.endswith('.aea') else p)
mnt = os.path.join(OUT, 'src-os'); os.makedirs(mnt)
subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noverify', '-noautofsck', '-owners', 'on',
                '-mountpoint', mnt, dmg], check=True, capture_output=True)
def sha(f):
    h = hashlib.sha256()
    with open(f, 'rb') as s:
        for b in iter(lambda: s.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
def bundle_of(rel):
    parts = rel.split('/'); best = None
    for i, x in enumerate(parts):
        if x.endswith(('.app', '.framework', '.appex')): best = '/'.join(parts[:i + 1])
    return best
try:
    rels = [l.strip() for l in open(PATHS) if l.strip()]
    t = tarfile.open(os.path.join(OUT, 'r5-files.tar'), 'w', format=tarfile.PAX_FORMAT)
    seen = set(); man = open(os.path.join(OUT, 'files.tsv'), 'w')
    for rel in rels:
        parts = rel.split('/')
        for i in range(1, len(parts) + 1):
            r = '/'.join(parts[:i])
            if r in seen: continue
            seen.add(r); src = os.path.join(mnt, r); st = os.lstat(src)
            ti = tarfile.TarInfo(r); ti.uid, ti.gid, ti.mode, ti.mtime = st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode), int(st.st_mtime)
            ti.uname = ti.gname = ''
            if stat.S_ISDIR(st.st_mode):
                ti.type = tarfile.DIRTYPE; t.addfile(ti)
            else:
                assert stat.S_ISREG(st.st_mode), (r, st)
                ti.size = st.st_size
                with open(src, 'rb') as f: t.addfile(ti, f)
                man.write(f'{r}\t{st.st_size}\t{st.st_uid}:{st.st_gid}\t{oct(stat.S_IMODE(st.st_mode))}\t{sha(src)}\t{st.st_ino}:{st.st_nlink}\n')
    t.close(); man.close()
    with open(os.path.join(OUT, 'bundles.tsv'), 'w') as b:
        for top in sorted({bundle_of(r) for r in rels} - {None}):
            for dp, dn, fn in os.walk(os.path.join(mnt, top)):
                for n in sorted(dn + fn):
                    q = os.path.join(dp, n); st = os.lstat(q); r = os.path.relpath(q, mnt)
                    k = 'd' if stat.S_ISDIR(st.st_mode) else 'l' if stat.S_ISLNK(st.st_mode) else 'f'
                    b.write(f'{top}\t{r}\t{k}\t{st.st_size if k == "f" else 0}\n')
    print('files', len(rels), 'tar entries', len(seen))
finally:
    subprocess.run(['hdiutil', 'detach', mnt], check=True, capture_output=True)
