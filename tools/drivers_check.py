#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""drivers_check.py [--xnu DIR] [CONFIG...]: the XNU tree's conf/files, config/MASTER* and bsd/dev/hakios.blazer_drivers.h agree
with config/hakios/*.drivers (every port file named by exactly one block, each built on its own hakios_<name> attribute, no
stale generated part), and every CONFIG (default: devices/blazer/configs/*) resolves (known drivers, requires met).
Idea: HakiOS tools/drivers-check.py (MIT); this port's layout. Exit 0 if all is well, 1 and the problems if not."""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hk_port_config as h  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--xnu')
    ap.add_argument('configs', nargs='*')
    a = ap.parse_args()
    xnu = h.xnu_dir(a.xnu)
    drivers, standard, problems = h.parse(xnu)
    if not problems:
        problems += h.check(xnu, drivers, standard)
        for c in a.configs or sorted(glob.glob(os.path.join(ROOT, 'devices', 'blazer', 'configs', '*'))):
            on, p = h.resolve(drivers, c)
            problems += ['%s: %s' % (os.path.basename(c), x) for x in p]
            if not p:
                print('%-18s %2d drivers: %s' % (os.path.basename(c), len(on), ' '.join(sorted(on))))
    print('\n'.join(problems) if problems else 'drivers_check OK: %d drivers, %d standard files (%s)' % (len(drivers), len(standard), xnu))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
