# r3 vs r4 census diff + the added entries against the IPSW owner map and the tar's bytes. Lines split on \n only.
import tarfile, hashlib, json, sys
def load(p):
    d = {}
    for l in open(p, errors='surrogateescape', newline='\n'):
        k, *v = l.rstrip('\n').split('\t'); assert len(v) == 7, repr(l[:80]); d[k] = v
    return d
a = load('receipts/census-r3.tsv'); b = load('receipts/census-r4.tsv')
new = sorted(set(b) - set(a)); gone = sorted(set(a) - set(b)); ch = [k for k in a if k in b and a[k] != b[k]]
tops = sorted({k.split('/')[1] for k in new if k.startswith('Applications/')})
outside = [k for k in new if not (k.startswith('Applications/') and k.split('/')[1] in tops)]
own = {}
for l in open('apps/src-owners.tsv', errors='surrogateescape', newline='\n'):
    p, u, g, m = l.rstrip('\n').split('\t'); own['Applications/' + p] = (u, g, int(m, 8))
th = {}
t = tarfile.open('apps/apps-r4.tar')
for x in t:
    if x.isfile() and x.name.startswith('Applications/'):
        th[x.name] = hashlib.sha256(t.extractfile(x).read()).hexdigest()
bad = []
for k in new:
    mode, u, g, size, nl, mt, v = b[k]
    if k not in own: bad.append(('not in owner map', k)); continue
    if (u, g) != own[k][:2] or (int(mode, 8) & 0o7777) != own[k][2]: bad.append(('owner/mode', k, mode, u, g, own[k]))
    if k in th and th[k] != v: bad.append(('sha', k))
r = dict(r3_entries=len(a), r4_entries=len(b), added=len(new), removed=len(gone), changed=len(ch), changed_list=ch[:20],
         added_outside_new_bundles=outside[:20], new_bundles=tops, owner_map_entries=len(own), tar_files=len(th),
         added_vs_source_problems=bad[:20], added_vs_source_problem_count=len(bad))
json.dump(r, open('receipts/verify-r4.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in r.items() if k != 'new_bundles'}, indent=1)); print(' '.join(tops))
