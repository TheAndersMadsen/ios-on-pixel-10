#!/usr/bin/env python3
"""Run as root in the container with a copy of r4 mounted rw at MOUNT (hfsplus, nls=utf8, noatime).
1. FILES_TAR (stock 23G90 files r3's prune removed, with stock owner/mode/mtime): every file must be absent and is
   created as its own file (stock hard links are not recreated); directories that exist keep r4's metadata, missing
   ones are created with the stock metadata; existing parents get their r4 times back afterwards.
2. CHANGED_TAR (the Mac reseal's Mach-Os and _CodeSignature/CodeResources): every path must exist as a regular file;
   it is unlinked and written as a new file (so a hard-linked r3 seal shared with other bundles is NOT written
   through), owner/group/mode from r4's lstat, mtime from the tar.
  insert_r5.py MOUNT FILES_TAR[,FILES_TAR...] CHANGED_TAR[,CHANGED_TAR...] OUT.json"""
import json, os, sys, tarfile
m, ft, ct, outp = sys.argv[1:5]
def copy(t, x, q):
    with t.extractfile(x) as s, open(q, 'xb') as d:
        for b in iter(lambda: s.read(1 << 20), b''): d.write(b)
rep = {'created_files': 0, 'created_dirs': [], 'existing_dirs_kept': 0, 'replaced': []}
keep = {}
mk = []
for t, x in [(t, x) for t in map(tarfile.open, ft.split(',')) for x in t.getmembers()]:
    q = os.path.join(m, x.name)
    if x.isdir():
        if os.path.isdir(q):
            st = os.lstat(q); keep.setdefault(q, (st.st_atime_ns, st.st_mtime_ns)); rep['existing_dirs_kept'] += 1
        else:
            os.mkdir(q, 0o700); mk.append((q, x)); rep['created_dirs'].append(x.name)
        continue
    assert x.isfile(), x.name
    assert not os.path.lexists(q), ('exists', x.name)
    copy(t, x, q); os.chown(q, x.uid, x.gid); os.chmod(q, x.mode); os.utime(q, (x.mtime, x.mtime)); rep['created_files'] += 1
for q, x in reversed(mk):
    os.chown(q, x.uid, x.gid); os.chmod(q, x.mode); os.utime(q, (x.mtime, x.mtime))
for c, x in [(c, x) for c in map(tarfile.open, ct.split(',')) for x in c.getmembers()]:
    assert x.isfile(), x.name
    q = os.path.join(m, x.name); st = os.lstat(q)
    assert os.path.isfile(q) and not os.path.islink(q) and st.st_nlink == 1, (x.name, st.st_nlink)   # Linux hfsplus miscounts links on unlink
    par = os.path.dirname(q); pst = os.lstat(par); keep.setdefault(par, (pst.st_atime_ns, pst.st_mtime_ns))
    os.unlink(q); copy(c, x, q); os.chown(q, st.st_uid, st.st_gid); os.chmod(q, st.st_mode & 0o7777)
    os.utime(q, (x.mtime, x.mtime))
    rep['replaced'].append([x.name, st.st_nlink, st.st_size, x.size])
for q, (a, mt) in keep.items():
    os.utime(q, ns=(a, mt))
json.dump(rep, open(outp, 'w'), indent=1)
print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in rep.items()}))
