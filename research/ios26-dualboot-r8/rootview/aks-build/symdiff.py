#!/usr/bin/env python3
"""Symbol diff of two unstripped kernels: sizes from nm -n -m address deltas within a section."""
import subprocess, sys, re, collections
def syms(k):
    out = subprocess.run(["nm", "-n", "-m", k], capture_output=True, text=True).stdout.splitlines()
    rows = []
    for l in out:
        m = re.match(r"([0-9a-f]{16}) \(([^)]+)\) (?:non-)?external (?:\[[^\]]*\] )*(\S+)", l)
        if m: rows.append((int(m[1], 16), m[2], m[3]))
    d = {}; per = collections.Counter()
    for i, (a, sec, n) in enumerate(rows):
        nxt = next((b for b, s2, _ in rows[i+1:] if b > a), None)
        size = (nxt - a) if nxt and rows[i+1][1] == sec else None
        key = (sec, n); per[sec] += 1
        d.setdefault(key, size)
    return d, per
a, pa = syms(sys.argv[1]); b, pb = syms(sys.argv[2])
fa = [k for k in a if k[0] == "__TEXT_EXEC,__text"]; fb = [k for k in b if k[0] == "__TEXT_EXEC,__text"]
print(f"__TEXT_EXEC,__text symbols: {len(fa)} vs {len(fb)}")
print("removed:", sorted(set(a) - set(b)))
print("added:", sorted(set(b) - set(a)))
ch = [(k, a[k], b[k]) for k in set(a) & set(b) if a[k] != b[k] and k[0] == "__TEXT_EXEC,__text"]
print(f"__text size changes: {len(ch)}")
for k, x, y in sorted(ch): print(f"  {k[1]}: {x} -> {y}")
