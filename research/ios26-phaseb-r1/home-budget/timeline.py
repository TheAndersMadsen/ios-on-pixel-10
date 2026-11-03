#!/usr/bin/env python3
"""Home-budget timeline extractor (host only; reads text decoded by tools/read-ramdump.py --logs).

Kernel axis: every line gets the time of the closest preceding `blazer-root: watch t N ms`
(or `stage t N ms`) line, i.e. ms since the root watch started (~0.5 s after XNU entry on the
p32/A7 kernels). Lines can be emitted late, so a kernel-axis time is an upper bound for the
event and a lower bound only to the previous watch tick.
launchd lines also carry their own timestamp; offset = launchd_ts - kernel_axis is reported.
"""
import re, sys, json, datetime

WATCH = re.compile(r'blazer-root: (?:watch|stage) t (\d+) ms stage (\S+) reads (\d+) blocks (\d+) busy (\d+) ms')
LTS = re.compile(r'com\.apple\.xpc\.launchd\|(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d\.\d+)')
SPAWN = re.compile(r'Successfully spawned ([A-Za-z0-9_.\-]+)\[(\d+)\]')
EXIT = re.compile(r'\(([^ )]+)(?: \[(\d+)\])?\) <Notice>: exited due to ([^,]+), ran for (\d+)ms')
PUSH = re.compile(r'\(([^)]+)\) <Notice>: Service only ran for (\d+) seconds\. Pushing respawn out by (\d+) seconds')
CRASHN = re.compile(r'\(([^ )]+) \[(\d+)\]\) <Notice>: service has crashed (\d+) times')
HKTOP = re.compile(r'HK TOP: t=(\d+) frames\+(\d+) cpu_ms=(\d+): (.*)')

KEY = ['SpringBoard', 'backboardd', 'PosterBoard', 'lsd', 'runningboardd', 'logd', 'cfprefsd',
       'securityd', 'containermanagerd', 'akd', 'iconservicesagent', 'mediaremoted', 'powerd',
       'configd', 'usermanagerd', 'fairplayd.H2', 'mobileactivationd', 'CommCenter', 'locationd',
       'mediaanalysisd', 'spotlightknowledged', 'searchd']

def secs(m):
    y, mo, d, h, mi, s = m.groups()
    dt = datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=datetime.timezone.utc)
    return dt.timestamp() + float(s)

def parse(path):
    watch, events, offsets, top = [], [], [], []
    t = None
    for ln in open(path, errors='replace'):
        for m in WATCH.finditer(ln):
            t = int(m.group(1)) / 1000.0
            watch.append(dict(t=t, stage=m.group(2), reads=int(m.group(3)), blocks=int(m.group(4)), busy_ms=int(m.group(5))))
        lm = LTS.search(ln)
        ts = secs(lm) if lm else None
        if ts is not None and t is not None:
            offsets.append(ts - t)
        for rx, kind in ((SPAWN, 'spawn'), (EXIT, 'exit'), (PUSH, 'push'), (CRASHN, 'crashn')):
            m = rx.search(ln)
            if m:
                events.append(dict(kind=kind, g=m.groups(), kt=t, ts=ts))
        m = HKTOP.search(ln)
        if m:
            top.append(dict(t=int(m.group(1)), frames=int(m.group(2)), cpu_ms=int(m.group(3)), kt=t,
                            procs=m.group(4)[:400]))
    return watch, events, offsets, top

def main():
    path = sys.argv[1]
    watch, ev, off, top = parse(path)
    # offset estimate: launchd ts - kernel axis; minimum lag lines give the best anchor
    off_sorted = sorted(off)
    base = None
    if off_sorted:
        # kernel axis lags the event by 0..10 s; the launchd ts is >= axis. take the 95th pct
        base = off_sorted[int(len(off_sorted) * 0.95)] - 10.0 if len(off_sorted) > 20 else off_sorted[-1] - 10.0
    out = dict(file=path, watch=watch, top=top)
    first = {}
    spawns, exits, pushes = {}, {}, []
    for e in ev:
        if e['kind'] == 'spawn':
            name = e['g'][0]
            spawns.setdefault(name, []).append(e['kt'])
        elif e['kind'] == 'exit':
            name = e['g'][0].split('/')[-1].replace('com.apple.', '')
            exits.setdefault(name, []).append((e['kt'], e['g'][2], int(e['g'][3])))
        elif e['kind'] == 'push':
            pushes.append((e['kt'], e['g'][0], int(e['g'][2])))
    out['spawn_first_kt'] = {k: v[0] for k, v in spawns.items()}
    out['spawn_count'] = {k: len(v) for k, v in spawns.items()}
    out['exits'] = exits
    out['pushes'] = pushes
    out['n_offsets'] = len(off)
    out['offset_min_max'] = (off_sorted[0], off_sorted[-1]) if off_sorted else None
    json.dump(out, sys.stdout, indent=1, default=str)

if __name__ == '__main__':
    main()
