#!/usr/bin/env python3
"""Run as root inside the container with the grown r4 image mounted rw at MOUNT (hfsplus, nls=utf8, noatime).
Adds TAR's Applications/<bundle> trees to MOUNT/Applications; owner/group/permission bits from OWNERS (lstat of the
IPSW's staged_system_apps, == r3's build map), mtimes from the tar. Refuses if any target name already exists.
  insert_apps.py MOUNT TAR OWNERS"""
import os, sys, tarfile
m, tarp, ownp = sys.argv[1:4]
own = {}
for l in open(ownp, encoding='utf-8', errors='surrogateescape'):
    p, u, g, mo = l.rstrip('\n').split('\t'); own[p] = (int(u), int(g), int(mo, 8))
apps = os.path.join(m, 'Applications')
t = tarfile.open(tarp)
mem = [x for x in t.getmembers() if x.name.startswith('Applications/') and x.name != 'Applications/']
tops = sorted({x.name.split('/')[1] for x in mem})
assert len(tops) == 49, len(tops)
clash = [b for b in tops if os.path.lexists(os.path.join(apps, b))]
assert not clash, clash
st_apps = os.lstat(apps)
n = {'d': 0, 'f': 0, 'l': 0}
dirs = []
for x in mem:
    rel = x.name[len('Applications/'):].rstrip('/')
    q = os.path.join(apps, rel)
    u, g, mo = own[rel]
    if x.isdir():
        os.mkdir(q, 0o700); dirs.append((q, x, u, g, mo)); n['d'] += 1; continue
    if x.issym():
        os.symlink(x.linkname, q); os.lchown(q, u, g); n['l'] += 1; continue
    assert x.isfile(), x.name
    with t.extractfile(x) as s, open(q, 'wb') as d:
        while True:
            b = s.read(1 << 20)
            if not b: break
            d.write(b)
    os.chown(q, u, g); os.chmod(q, mo); os.utime(q, (x.mtime, x.mtime)); n['f'] += 1
for q, x, u, g, mo in reversed(dirs):
    os.chown(q, u, g); os.chmod(q, mo); os.utime(q, (x.mtime, x.mtime))
assert n['d'] + n['f'] + n['l'] == len(own), (n, len(own))
os.utime(apps, ns=(st_apps.st_atime_ns, st_apps.st_mtime_ns))   # keep /Applications' own times
print('inserted', n, 'bundles', len(tops))
