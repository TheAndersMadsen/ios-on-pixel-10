#!/usr/bin/env python3
"""Compare two hackios QEMU console logs (ramoops mirror) for calibration: early-boot milestone order, when launchd and
the UI daemons first appear (guest clock), marker counts up to a common guest-time cutoff, boot tasks run, first fault.
usage: compare.py REF.log RUN.log [--cutoff SECONDS]"""
import re, sys
TS = re.compile(rb'\|(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)')
def gtime(line):
    m = TS.search(line)
    if not m: return None
    h, mi, s = m[1].split(b' ')[1].split(b':'); return int(h)*3600+int(mi)*60+float(s)
def load(p):
    lines = open(p, 'rb').read().split(b'\n'); last = 0.0; out = []
    for l in lines:
        t = gtime(l)
        if t is not None: last = t
        out.append((last, l))
    return out
def progress(p):
    """harness progress.txt next to the log: host-elapsed seconds, console bytes, uart bytes (one line a second)."""
    try: return [(float(a), int(b)) for a, b, *_ in (l.split() for l in open(p.rsplit('/', 1)[0]+'/progress.txt'))]
    except OSError: return []
def first(lines, pat, prog=()):
    r = re.compile(pat); off = 0
    for t, l in lines:
        if r.search(l):
            host = next((h for h, n in prog if n >= off+len(l)), None)
            return t, host, l[:140].decode('latin1')
        off += len(l)+1
    return None, None, None
fmt = lambda t: '   none' if t is None else '%7.1f' % t
def main():
    cutoff = 300.0
    if '--cutoff' in sys.argv: cutoff = float(sys.argv[sys.argv.index('--cutoff')+1])
    A, B = load(sys.argv[1]), load(sys.argv[2]); PA, PB = progress(sys.argv[1]), progress(sys.argv[2])
    early = lambda L: [l.decode('latin1').strip() for _, l in L if l.startswith(b'TEGU-XNU EARLY')]
    ea, eb = early(A), early(B)
    print(f'early milestones: ref {len(ea)} run {len(eb)} same-order-prefix {sum(1 for x, y in zip(ea, eb) if x == y)}')
    if ea != eb:
        for i, (x, y) in enumerate(zip(ea, eb)):
            if x != y: print(f'  first divergence at {i}: ref={x!r} run={y!r}'); break
    print('last guest time: ref %.1f s, run %.1f s' % (A[-1][0], B[-1][0]))
    print('first occurrence, guest clock (host wall clock when progress.txt exists):')
    for name, pat in [('launchd first', rb'com\.apple\.xpc\.launchd\|'), ('usermanagerd', rb'usermanagerd\[\d|\((?:com\.apple\.)?usermanagerd\) <'), ('lsd', rb'\blsd\[\d'), ('backboardd', rb'backboardd\[\d|\(com\.apple\.backboardd\) <'), ('SpringBoard', rb'SpringBoard\[\d'),
                      ('persona miss', rb'Unable to find persona'), ('panic', rb'panic\(cpu'), ('exception', rb'Synchronous exception|kernel trap|Debugger message')]:
        ta, ha, la = first(A, pat, PA); tb, hb, lb = first(B, pat, PB)
        print(f'  {name:14s} ref {fmt(ta)} s (host {fmt(ha)}) | run {fmt(tb)} s (host {fmt(hb)})')
        if name in ('panic', 'exception') and (la or lb): print('   ref:', la); print('   run:', lb)
    print(f'marker counts up to guest {cutoff:.0f} s:')
    for name, pat in [('persona miss', rb'Unable to find persona'), ('backboardd', rb'backboardd\[\d|\(com\.apple\.backboardd\) <'), ('SpringBoard', rb'SpringBoard\[\d'), ('lsd', rb'\blsd\[\d'), ('Doing boot task', rb'Doing boot task'), ('Skipping boot-task', rb'Skipping boot-task'), ('panic', rb'panic\(cpu'), ('exception', rb'Synchronous exception')]:
        r = re.compile(pat); ca = sum(1 for t, l in A if t <= cutoff and r.search(l)); cb = sum(1 for t, l in B if t <= cutoff and r.search(l))
        print(f'  {name:20s} ref {ca:5d}  run {cb:5d}')
    bt = lambda L: [(re.search(rb'\((\S+?)\) <', l) or [b'', b'?'])[1].decode('latin1') for _, l in L if b'Doing boot task' in l]
    print('boot tasks ref:', bt(A)); print('boot tasks run:', bt(B))
    subj = lambda L: list(dict.fromkeys(re.search(rb'\((\S+?)\) <', l)[1].decode('latin1') for _, l in L if re.search(rb'\((\S+?)\) <', l)))[:20]
    sa, sb = subj(A), subj(B); print('first 20 daemons ref:', sa); print('first 20 daemons run:', sb); print('daemon order same:', sa == sb)
if __name__ == '__main__': main()
