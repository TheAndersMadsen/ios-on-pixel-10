#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Mac only. Build and run tools/fw_layout_r1.c with measure_vendor.py's include set (every directory between a pvrsrvkm header and
the powervr root, plus pixel/lga/production). Writes receipts/fw-layout-r1.h and receipts/fw-layout-r1.json (argv, vendor HEAD)."""
from pathlib import Path
import json, subprocess
R = Path(__file__).resolve().parents[1]
ROOT = R.parents[1]
VENDOR = ROOT / 'research/ios26-metal-r1/dl-gos/private/google-modules/powervr'
inc = {VENDOR / 'pixel/lga/production'}
for p in (VENDOR / 'pvrsrvkm').rglob('*.h'):
    for parent in p.parents:
        if parent == VENDOR:
            break
        inc.add(parent)
(R / 'obj').mkdir(exist_ok=True); (R / 'receipts').mkdir(exist_ok=True)
argv = ['clang', '-std=gnu11', '-O0', *('-I' + str(p) for p in sorted(inc)), str(R / 'tools/fw_layout_r1.c'), '-o', str(R / 'obj/fw_layout_r1')]
run = subprocess.run(argv, capture_output=True, text=True)
head = subprocess.check_output(['git', '-C', str(VENDOR), 'rev-parse', 'HEAD'], text=True).strip()
(R / 'receipts/fw-layout-r1.json').write_text(json.dumps(dict(argv=[a.replace(str(ROOT) + '/', '') for a in argv], returncode=run.returncode, stderr=run.stderr, vendor_head=head), indent=1) + '\n')
if run.returncode:
    raise SystemExit(run.stderr)
out = subprocess.check_output([str(R / 'obj/fw_layout_r1')], text=True)
(R / 'receipts/fw-layout-r1.h').write_text(out)
print(out, end='')
