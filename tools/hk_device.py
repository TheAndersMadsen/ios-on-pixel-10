#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Idea: HakiOS tools/hakios-device.py (a device directory that checks itself); this port's files, no code copied.
"""hk_device.py [--xnu DIR] [--device DIR] check [--no-evidence] | ladder

check   devices/blazer holds together:
          - device.conf parses; one `status` line per driver of the XNU tree's config/hakios, none for an unknown driver;
          - its ladder= equals the driver block's `ladder`;
          - every config under configs/ resolves (known drivers, requires met) and minimal.config is a subset of step1.config;
          - a `physical` line names an attempt that exists (research/laguna-usb-fix/attempts/<dir>) and its first quoted line
            is really in that attempt's console.txt / boot.log / ramdump (skip with --no-evidence);
          - `qemu` names an existing path, `compiled` needs no proof.
ladder  the drivers by ladder step with their state (what to turn on next).
XNU DIR as hk_port_config.py (--xnu, $HK_PORT_XNU, /data/work/hk-port-build/xnu)."""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hk_port_config as h  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ATTEMPTS = os.path.join(ROOT, 'research', 'laguna-usb-fix', 'attempts')
STATES = ('physical', 'qemu', 'compiled')
LINE = re.compile(r'^\s+status\s+([A-Z0-9_]+)\s+(\S+)\s+(.*)$')


def read_status(path):
    out, problems = {}, []
    for no, raw in enumerate(open(path, encoding='utf-8'), 1):
        if not raw.lstrip().startswith('status'):
            continue
        m = LINE.match(raw.rstrip('\n'))
        if not m:
            problems.append('device.conf:%d: malformed status line' % no)
            continue
        name, state, rest = m.groups()
        kv = dict(re.findall(r'(ladder|gate|proof|step)=(.*?)(?=\s+(?:ladder|gate|proof|step)=|$)', rest))
        if name in out:
            problems.append('device.conf:%d: %s has a second status line' % (no, name))
        out[name] = {'no': no, 'state': state, 'ladder': kv.get('ladder', '').strip(), 'gate': kv.get('gate', '').strip(),
                     'proof': kv.get('proof', '').strip(), 'step': kv.get('step', '').strip()}
    return out, problems


def unescape(s):
    return s.replace('\\"', '"')


def evidence_ok(proof):
    """(ok, why) for a physical proof: '<attempt dir> [(...)] "<line>" ...'."""
    m = re.match(r'(\S+)', proof)
    if not m:
        return False, 'no attempt named'
    att = os.path.join(ATTEMPTS, m.group(1))
    if not os.path.isdir(att):
        return False, 'attempt %s does not exist under research/laguna-usb-fix/attempts' % m.group(1)
    q = re.search(r'"((?:[^"\\]|\\.)*)"', proof)
    if not q:
        return False, 'no quoted console line'
    want = unescape(q.group(1)).encode()
    files = [os.path.join(att, f) for f in ('console.txt', 'boot.log', 'live.log', 'reader.txt')]
    files += glob.glob(os.path.join(att, 'ramdump', '*.log')) + glob.glob(os.path.join(att, 'ui_run.log'))
    for f in files:
        try:
            if want in open(f, 'rb').read():
                return True, os.path.relpath(f, ATTEMPTS)
        except OSError:
            pass
    return False, 'quoted line not found in %s (console.txt/boot.log/ramdump/*.log)' % m.group(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--xnu')
    ap.add_argument('--device', default=os.path.join(ROOT, 'devices', 'blazer'))
    ap.add_argument('cmd', choices=('check', 'ladder'))
    ap.add_argument('--no-evidence', action='store_true')
    a = ap.parse_args()
    xnu = h.xnu_dir(a.xnu)
    drivers, standard, problems = h.parse(xnu)
    if problems:
        print('\n'.join(problems))
        return 1
    status, problems = read_status(os.path.join(a.device, 'device.conf'))
    if a.cmd == 'ladder':
        steps = {}
        for n, d in drivers.items():
            steps.setdefault(d.ladder if d.ladder is not None else 99, []).append(n)
        for s in sorted(steps):
            print('step %s: %s' % (s if s != 99 else '-', '  '.join('%s[%s%s]' % (n, status.get(n, {}).get('state', '?'), '+ladder' if status.get(n, {}).get('step') else '') for n in sorted(steps[s]))))
        return 0
    for n in sorted(set(drivers) - set(status)):
        problems.append('device.conf: no status line for %s (%s)' % (n, drivers[n].line))
    for n, s in sorted(status.items()):
        where = 'device.conf:%d' % s['no']
        if n not in drivers:
            problems.append('%s: %s is not a driver of %s/config/hakios' % (where, n, xnu))
            continue
        if s['state'] not in STATES:
            problems.append('%s: %s state %r is not one of %s' % (where, n, s['state'], ', '.join(STATES)))
        want = str(drivers[n].ladder) if drivers[n].ladder is not None else '-'
        if s['ladder'] != want:
            problems.append('%s: %s ladder=%s, config/hakios says %s' % (where, n, s['ladder'], want))
        if not s['gate']:
            problems.append('%s: %s names no gate' % (where, n))
        if s['state'] == 'physical' and not a.no_evidence:
            ok, why = evidence_ok(s['proof'])
            if not ok:
                problems.append('%s: %s physical but %s' % (where, n, why))
        if s['step'] and not a.no_evidence:
            ok, why = evidence_ok(s['step'])
            if not ok:
                problems.append('%s: %s step= proof: %s' % (where, n, why))
            if s['state'] != 'physical':
                problems.append('%s: %s has a ladder-kernel proof but is not physical' % (where, n))
        if s['state'] == 'qemu':
            p = s['proof'].split()[0] if s['proof'] else ''
            if not os.path.exists(os.path.join(ROOT, p)):
                problems.append('%s: %s qemu proof path %r does not exist' % (where, n, p))
    cfgs = {}
    for c in sorted(glob.glob(os.path.join(a.device, 'configs', '*'))):
        on, p = h.resolve(drivers, c)
        cfgs[os.path.basename(c)] = on
        problems += ['configs/%s: %s' % (os.path.basename(c), x) for x in p]
    if 'minimal.config' in cfgs and 'step1.config' in cfgs and not cfgs['minimal.config'] <= cfgs['step1.config']:
        problems.append('configs: minimal.config is not contained in step1.config')
    phys = sum(1 for s in status.values() if s['state'] == 'physical')
    lad = sum(1 for s in status.values() if s['step'])
    print('\n'.join(problems) if problems else 'hk_device OK: %d drivers, %d status lines (%d physical, %d proven in their ladder kernel, evidence %s), %d configs' % (
        len(drivers), len(status), phys, lad, 'skipped' if a.no_evidence else 'found in the attempts', len(cfgs)))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
