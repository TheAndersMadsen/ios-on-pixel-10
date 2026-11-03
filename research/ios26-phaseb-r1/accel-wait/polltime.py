#!/usr/bin/env python3
"""Group backboardd IOAcceleratorES poll lines into bursts (one per backboardd process) and time each burst with the
interleaved launchd wall-clock stamps (`com.apple.xpc.launchd|<date> <hh:mm:ss.us>`, nearest preceding/following).
    polltime.py KERNEL_LOG [...]
A burst ends at an `exec backboardd`, a `blazer-root: watch t` restart below the previous value, or EOF. Counts are
per burst; the ramdump can hold the same boot twice (msgbuf + persistent console), which shows as a repeated burst."""
import re, sys
TS = re.compile(r'com\.apple\.xpc\.launchd\|\S+ (\d\d):(\d\d):(\d\d\.\d+)')
W = re.compile(r'blazer-root: (?:watch|stage) t (\d+) ms')
for path in sys.argv[1:]:
    print(f'== {path}')
    last_ts = None; bursts = []; cur = None; axis = 0.0
    for ln in open(path, 'rb').read().decode('latin-1').splitlines():
        for m in W.finditer(ln): axis = int(m[1]) / 1000
        m = None
        for m in TS.finditer(ln): pass
        if m: 
            last_ts = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
            if cur and cur['after'] is None and cur['n']: cur['pending'] = last_ts
        if 'exec backboardd' in ln or 'usertrap: backboardd' in ln:
            if cur: bursts.append(cur)
            cur = None
        if 'IOAcceleratorES' in ln and 'backboardd' in ln:
            if cur is None: cur = dict(n=0, first_ts=last_ts, first_axis=axis, after=None)
            cur['n'] += 1; cur['last_ts'] = last_ts; cur['last_axis'] = axis; cur['pending'] = None
        elif cur and cur['n'] and cur.get('pending') and cur['after'] is None and ('AGXAccelerator' in ln or 'display on' in ln):
            cur['after'] = ln.strip()[:60]
    if cur: bursts.append(cur)
    for b in bursts:
        span = (b['last_ts'] - b['first_ts']) if b['first_ts'] is not None and b['last_ts'] is not None else None
        print(f"  n={b['n']:4d} axis {b['first_axis']:.1f}..{b['last_axis']:.1f}  launchd-clock span "
              f"{span if span is None else round(span, 1)} s  next: {b['after']}")
