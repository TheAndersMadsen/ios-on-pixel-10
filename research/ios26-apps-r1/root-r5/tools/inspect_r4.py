# ro-run.sh IMG inspect_r4.py /m FILES_TSV BUNDLES_TSV : which r5 files/dirs exist in the image; what else the touched bundles lack
import os, sys, plistlib
m, ft, bt = sys.argv[1:4]
for l in open(ft):
    r = l.split('\t')[0]; parts = r.split('/')
    missing_dirs = [ '/'.join(parts[:i]) for i in range(1, len(parts)) if not os.path.isdir(os.path.join(m, *parts[:i]))]
    print('FILE', 'present' if os.path.lexists(os.path.join(m, r)) else 'absent', r, 'missing-dirs:', missing_dirs)
miss = {}
for l in open(bt):
    top, r, k, sz = l.rstrip('\n').split('\t')
    if not os.path.lexists(os.path.join(m, r)): miss.setdefault(top, []).append((r, k, int(sz)))
for top, v in sorted(miss.items()):
    print('BUNDLE', top, 'missing', len(v), 'bytes', sum(x[2] for x in v))
    for r, k, sz in v: print('   ', k, sz, r)
cr = os.path.join(m, 'Applications/MobilePhone.app/_CodeSignature/CodeResources')
if os.path.exists(cr):
    d = plistlib.load(open(cr, 'rb')); print('MobilePhone CodeResources files2 has Assets.car:', 'Assets.car' in d.get('files2', {}), 'files has:', 'Assets.car' in d.get('files', {}))
