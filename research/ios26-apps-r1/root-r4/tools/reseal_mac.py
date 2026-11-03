#!/usr/bin/env python3
"""Second, ordered signing pass over OUT/Applications (Mac): every Mach-O that the macho stage rewrote (macho.json
identities) is signed again with r3's pacstrip.sign, sequentially, deepest path first, so that nested bundles
(PlugIns/*.appex, Frameworks) are final before the enclosing bundle's resource seal is computed. Code bytes are not
touched again; identifier/team/entitlements/CS options are preserved and checked by pacstrip.sign.
  python3 -I reseal_mac.py RENEGADE_DIR OUT_DIR"""
import json, os, subprocess, sys
REN, OUT = map(os.path.abspath, sys.argv[1:3])
sys.path.insert(0, REN)
import pacstrip
apps = os.path.join(OUT, 'Applications')
ids = json.load(open(os.path.join(OUT, 'macho.json')))['identities']
paths = sorted(ids, key=lambda p: (-p.count('/'), p))
for rel in paths:
    pacstrip.sign(os.path.join(apps, rel))
bad = []
for b in sorted(os.listdir(apps)):
    r = subprocess.run(['codesign', '-v', '--deep', os.path.join(apps, b)], capture_output=True, text=True)
    if r.returncode:
        bad.append((b, r.stderr.strip()[-300:]))
json.dump({'resigned': len(paths), 'order': 'deepest first', 'codesign_v_deep_bad': bad},
          open(os.path.join(OUT, 'reseal.json'), 'w'), indent=1)
print('resigned', len(paths), 'bundles failing codesign -v --deep:', len(bad), bad[:5])
