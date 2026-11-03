#!/usr/bin/env python3
"""Compare a fake-LUN medium after a run with its pristine copy, block by block (4096 B), and check that every changed
block lies inside the allowed LBA range.

    fakelun_diff.py PRISTINE.img RUN.img LAYOUT.json FIRST_ALLOWED_LBA LAST_ALLOWED_LBA

Prints JSON: changed block count, changed ranges (LBA), which partition each range is in, and verdict PASS only when
changed > 0 and every changed block is inside [FIRST, LAST]. Host only; reads both files once.
"""
import json, sys

B = 4096; CH = 64 << 20


def main():
    a, b, lay, lo, hi = sys.argv[1], sys.argv[2], json.load(open(sys.argv[3])), int(sys.argv[4]), int(sys.argv[5])
    parts = {k: lay[k] for k in ('userdata', 'ios_system', 'ios_data', 'primary', 'backup')}
    where = lambda l: next((k for k, (f, t) in parts.items() if f <= l <= t), 'unallocated')
    ranges, n, off = [], 0, 0
    with open(a, 'rb') as fa, open(b, 'rb') as fb:
        while True:
            x, y = fa.read(CH), fb.read(CH)
            if not x and not y:
                break
            if x != y:
                for i in range(0, max(len(x), len(y)), B):
                    if x[i:i + B] != y[i:i + B]:
                        l = (off + i) // B; n += 1
                        if ranges and ranges[-1][1] == l - 1:
                            ranges[-1][1] = l
                        else:
                            ranges.append([l, l])
            off += max(len(x), len(y))
    outside = [r for r in ranges if r[0] < lo or r[1] > hi]
    print(json.dumps({'changed_blocks': n, 'ranges': [[r[0], r[1], where(r[0]), where(r[1])] for r in ranges][:200],
                      'allowed': [lo, hi], 'outside_allowed': outside, 'bytes_compared': off,
                      'verdict': 'PASS' if n > 0 and not outside else ('NO_WRITES' if n == 0 else 'FAIL')}, indent=1))


if __name__ == '__main__':
    main()
