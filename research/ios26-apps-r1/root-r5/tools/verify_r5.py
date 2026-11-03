# r4 vs r5 census diff, checked against the two inputs (run from root-r5 on m1box):
#   added   == the restored stock files (path, owner, mode, size, sha256 from files/files.tsv + files/r5b-files.tsv, the Mac's lstat)
#   changed == exactly the reseal's files (sha256 from files/reseal.json) + private/var.skel.tsv (files/skel.tar), owner/mode as in r4
#   removed == 0; everything else identical in path, type, mode, uid, gid, size, nlink, mtime, sha256
import json, sys
def load(p):
    d = {}
    for l in open(p, errors='surrogateescape', newline='\n'):
        k, *v = l.rstrip('\n').split('\t'); assert len(v) == 7, repr(l[:80]); d[k] = v
    return d
a = load('../root-r4/receipts/census-r4.tsv'); b = load('receipts/census-r5.tsv')
new = sorted(set(b) - set(a)); gone = sorted(set(a) - set(b)); ch = sorted(k for k in a if k in b and a[k] != b[k])
stock = {}
for l in open('files/files.tsv').readlines() + open('files/r5b-files.tsv').readlines():
    r, size, ug, mode, sha, ino = l.rstrip('\n').split('\t'); u, g = ug.split(':'); stock[r] = (u, g, int(mode, 8), size, sha)
rs = {r: s1 for r, s0, s1 in json.load(open('files/reseal.json'))['changed_files']}
import hashlib, tarfile
rs['private/var.skel.tsv'] = hashlib.sha256(tarfile.open('files/skel.tar').extractfile('private/var.skel.tsv').read()).hexdigest()
bad = []
for k in new:
    mode, u, g, size, nl, mt, v = b[k]
    if k not in stock: bad.append(('added, not a restored file', k)); continue
    su, sg, sm, ss, sh = stock[k]
    if (u, g, int(mode, 8) & 0o7777, size, v, nl) != (su, sg, sm, ss, sh, '1'): bad.append(('added differs from stock', k, b[k], stock[k]))
for k in ch:
    if k not in rs: bad.append(('changed, not a reseal file', k, a[k], b[k])); continue
    if b[k][6] != rs[k] or b[k][:3] != a[k][:3] or b[k][4] != '1': bad.append(('reseal mismatch', k, a[k], b[k]))
r = dict(r4_entries=len(a), r5_entries=len(b), added=len(new), removed=len(gone), changed=len(ch), changed_list=ch,
         restored_expected=len(stock), reseal_expected=len(rs), missing_restored=sorted(set(stock) - set(new)),
         missing_reseal=sorted(set(rs) - set(ch)), problems=bad[:20], problem_count=len(bad))
json.dump(r, open('receipts/verify-r5.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in r.items() if k != 'changed_list'}, indent=1))
