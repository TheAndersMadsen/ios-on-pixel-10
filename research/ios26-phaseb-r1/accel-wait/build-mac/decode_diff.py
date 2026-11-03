#!/usr/bin/env python3
"""HOST ONLY: decode base and new overlay with ios26-overlay2-r1/tools/restore_cloudd.py decode() (a second,
independent walker) and print every record that differs. Usage: decode_diff.py BASE NEW [DYLIB]"""
import hashlib, importlib.util, sys
from pathlib import Path
sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('rc', REPO / 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
RC = importlib.util.module_from_spec(spec); spec.loader.exec_module(RC)
sha = lambda b: hashlib.sha256(b).hexdigest()
a, b = (Path(x).read_bytes() for x in sys.argv[1:3])
ra, rb = RC.decode(a), RC.decode(b)
print(f'base {sha(a)} {len(a)} B {len(ra)} records')
print(f'new  {sha(b)} {len(b)} B {len(rb)} records')
same = diff = 0
for i in range(max(len(ra), len(rb))):
    x = ra[i] if i < len(ra) else None
    y = rb[i] if i < len(rb) else None
    if x and y and x[7] == y[7]:
        same += 1; continue
    diff += 1
    for tag, r in (('-', x), ('+', y)):
        if r is None: print(f'{tag} [{i}] (absent)'); continue
        k, g, m, u, gi, p, d, raw = r
        shown = d.decode() if k == ord('c') else f'{len(d)} B sha256 {sha(d)}'
        print(f'{tag} [{i}] {chr(k)} group={g} mode={m:o} uid={u} gid={gi} {p}: {shown}')
print(f'identical raw records: {same}; differing: {diff}')
if len(sys.argv) > 3:
    lib = Path(sys.argv[3]).read_bytes()
    assert rb[-1][6] == lib, 'appended data is not the dylib'
    print(f'appended record data == {sys.argv[3]} ({sha(lib)})')
