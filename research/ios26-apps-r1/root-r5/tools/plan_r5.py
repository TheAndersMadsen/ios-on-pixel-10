# ro-run.sh R4 plan_r5.py /m BUNDLES_TSV OUTDIR : RESTORE = stock entries of the touched bundles absent in r4
# (restore-paths.txt, parents first); SEALED = outermost bundles in r4 with _CodeSignature that contain a restored
# path (sealed.txt); their r4 trees -> sealed-r4.tar (data+owner+mode+mtime, no xattrs) for the Mac reseal.
import os, sys, tarfile
m, bt, out = sys.argv[1:4]
rest = []
for l in open(bt):
    top, r, k, sz = l.rstrip('\n').split('\t')
    if not os.path.lexists(os.path.join(m, r)) and r not in rest: rest.append(r)
rest.sort(key=lambda r: (r.count('/'), r))
def sealed_of(r):
    p = r.split('/'); outer = None
    for i in range(1, len(p)):
        a = '/'.join(p[:i])
        if a.endswith(('.app', '.appex', '.framework')) and os.path.isfile(os.path.join(m, a, '_CodeSignature/CodeResources')):
            outer = outer or a
    return outer
sealed = sorted({s for s in map(sealed_of, rest) if s})
open(os.path.join(out, 'restore-paths.txt'), 'w').write(''.join(r + '\n' for r in rest))
open(os.path.join(out, 'sealed.txt'), 'w').write(''.join(s + '\n' for s in sealed))
t = tarfile.open(os.path.join(out, 'sealed-r4.tar'), 'w', format=tarfile.PAX_FORMAT)
for s in sealed: t.add(os.path.join(m, s), arcname=s, recursive=True)
t.close()
print('restore', len(rest), 'sealed', sealed)
