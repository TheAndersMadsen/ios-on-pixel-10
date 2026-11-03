#!/usr/bin/env python3
"""Mac half 2 of root-r5: SEALED_TAR (r4's own trees of the touched bundles) + FILES_TAR (the restored stock files)
-> re-sign with r3's pacstrip.sign (codesign -f -s -, identifier/entitlements/CS options kept and checked) every
signed bundle whose seal the restore breaks, deepest first, then codesign -v --deep. Baseline: the same verify on
r4's trees untouched. Writes OUT/changed.tar: only the files whose bytes the reseal changed (never an r4 hard link) (Mach-Os and
_CodeSignature/CodeResources), relative to the root; OUT/reseal.json.
  python3 -I reseal_r5_mac.py RENEGADE_DIR SEALED_TAR FILES_TAR OUT_DIR"""
import hashlib, json, os, plistlib, subprocess, sys, tarfile
REN, ST, FT, OUT = map(os.path.abspath, sys.argv[1:5])
sys.path.insert(0, REN)
import pacstrip
assert not os.path.exists(OUT), OUT
B, A = os.path.join(OUT, 'before'), os.path.join(OUT, 'after')
def untar(t, d, filt=None):
    os.makedirs(d, exist_ok=True)
    with tarfile.open(t) as x:
        for mm in x.getmembers():
            if filt and not filt(mm.name): continue
            mm.uid = mm.gid = os.getuid(); mm.mode |= 0o700 if mm.isdir() else 0o600
            x.extract(mm, d, filter='fully_trusted', set_attrs=True)
def unlink_hard(root):            # r3 hard-links identical seal files across bundles; a re-sign must not write
    n = 0                          # through a link into another bundle's seal, so every link becomes its own file
    for dp, dn, fn in os.walk(root):
        for x in fn:
            q = os.path.join(dp, x)
            if not os.path.islink(q) and os.lstat(q).st_nlink > 1:
                b = open(q, 'rb').read(); st = os.lstat(q); os.unlink(q)
                open(q, 'wb').write(b); os.chmod(q, st.st_mode & 0o7777); os.utime(q, ns=(st.st_atime_ns, st.st_mtime_ns)); n += 1
    return n
untar(ST, B); untar(ST, A)
shared = set()                     # r4 paths that are hard links (seal shared with other bundles): never replaced,
for dp, dn, fn in os.walk(B):      # since the Linux hfsplus driver miscounts links on unlink (fsck: incorrect
    for x in fn:                   # number of file hard links), so their bundles are not re-signed either
        q = os.path.join(dp, x)
        if not os.path.islink(q) and os.lstat(q).st_nlink > 1: shared.add(os.path.relpath(q, B))
links = unlink_hard(B), unlink_hard(A)
untar(FT, A, lambda n: True)
def bundles(root):
    out = []
    for dp, dn, fn in os.walk(root):
        if dp.endswith(('.app', '.appex', '.framework', '.xpc')) and os.path.isfile(os.path.join(dp, '_CodeSignature/CodeResources')):
            ip = os.path.join(dp, 'Info.plist'); exe = None
            if os.path.isfile(ip):
                exe = plistlib.load(open(ip, 'rb')).get('CFBundleExecutable')
            if exe and os.path.isfile(os.path.join(dp, exe)):
                out.append((os.path.relpath(dp, root), exe))
    return sorted(out, key=lambda b: (-b[0].count('/'), b[0]))
def cv(root, rel, deep=False):
    r = subprocess.run(['codesign', '-v'] + (['--deep'] if deep else []) + [os.path.join(root, rel)], capture_output=True, text=True)
    return r.returncode, r.stderr.strip()[-400:]
bl = bundles(B)
base = {b: cv(B, b) for b, _ in bl}
pre = {b: cv(A, b) for b, _ in bl}
signed, skipped = [], []
for b, exe in bl:                 # deepest first; a nested re-sign also invalidates the enclosing seal
    if os.path.join(b, '_CodeSignature/CodeResources') in shared or os.path.join(b, exe) in shared:
        skipped.append(b); continue
    if cv(A, b)[0]:
        pacstrip.sign(os.path.join(A, b, exe)); signed.append(os.path.join(b, exe))
post = {b: cv(A, b, deep=True) for b, _ in bl}
def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()
changed = []
for dp, dn, fn in os.walk(B):
    for n in fn:
        q = os.path.join(dp, n); r = os.path.relpath(q, B); a = os.path.join(A, r)
        if not os.path.islink(q) and sha(q) != sha(a):
            assert r not in shared, r
            changed.append((r, sha(q), sha(a)))
new_cs = []
for dp, dn, fn in os.walk(A):      # a reseal may create a seal file that r4 lacked
    for n in fn:
        r = os.path.relpath(os.path.join(dp, n), A)
        if '_CodeSignature' in r and not os.path.lexists(os.path.join(B, r)): new_cs.append(r)
with tarfile.open(os.path.join(OUT, 'changed.tar'), 'w', format=tarfile.PAX_FORMAT) as t:
    for r, _, _ in changed:
        ti = t.gettarinfo(os.path.join(A, r), arcname=r); ti.uid = ti.gid = 0; ti.uname = ti.gname = ''
        with open(os.path.join(A, r), 'rb') as f: t.addfile(ti, f)
rep = {'hard_links_broken_before_after': links, 'bundles': len(bl), 'baseline_r4_codesign_v_bad': {b: v for b, v in base.items() if v[0]},
       'after_restore_before_resign_bad': {b: v for b, v in pre.items() if v[0]},
       'resigned_deepest_first': signed, 'skipped_shared_hardlinked_seal': skipped, 'after_resign_codesign_v_deep_bad': {b: v for b, v in post.items() if v[0]},
       'changed_files': changed, 'new_seal_files_not_in_r4': new_cs}
json.dump(rep, open(os.path.join(OUT, 'reseal.json'), 'w'), indent=1)
print(json.dumps({k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in rep.items()}))
