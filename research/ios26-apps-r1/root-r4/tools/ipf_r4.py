#!/usr/bin/env python3
"""tools/ios_partition_flash.py with its root pin set to ios26-phone-r4 instead of r3; the repo file is not edited.
  ipf_r4.py REPO sparse --root IMG --blocks N --out SIMG
  ipf_r4.py REPO check  <same args as ios_partition_flash.py check>      (receipt for r4; verify-stream: use the repo tool)
Everything else (table rules, sparse writer, phone_write expander, owner commands) is the repo's code."""
import json, sys
from pathlib import Path
REPO = Path(sys.argv[1]).resolve(); sys.path.insert(0, str(REPO / 'tools'))
import ios_partition_flash as M
R4 = 'a6574777105ffd3ec6083cdac519e9b584f78092cab1aed4240ab81822e96abc'
M.ROOT_SHA = R4
argv = sys.argv[2:]
try:
    if argv[0] == 'sparse':
        import argparse
        p = argparse.ArgumentParser(); p.add_argument('--root', required=True); p.add_argument('--blocks', type=int, required=True); p.add_argument('--out', required=True)
        a = p.parse_args(argv[1:])
        sha = M.sha_file(a.root); M.need(sha == R4, f'root sha256 is {sha}, not the pinned r4 {R4}')
        n = M.write_sparse(a.root, a.blocks, a.out); print('wrote', a.out, 'chunks', n, 'sha256', M.sha_file(a.out))
    elif argv[0] == 'check':
        import argparse
        c = argparse.ArgumentParser()
        for k in ('--head', '--tail', '--disk-guid', '--root'): c.add_argument(k, required=True)
        c.add_argument('--tail-lba', type=int, required=True); c.add_argument('--total-lbas', type=int, required=True)
        c.add_argument('--plan'); c.add_argument('--simg'); c.add_argument('--out')
        a = c.parse_args(argv[1:])
        rec = M.check(M.disk_from(a), a.disk_guid, a.root, root_sha=R4, plan_dir=a.plan, simg=a.simg)
        if a.out:
            o = Path(a.out); M.need(not o.exists(), f'{o} exists'); o.write_text(json.dumps(rec, indent=1) + '\n')
        print(json.dumps(rec, indent=1)); print('OK'); print(M.commands(rec, a))
    else:
        sys.exit('only sparse and check; verify-stream is the repo tool unchanged')
except M.Refused as e:
    sys.exit('refused: ' + str(e))
