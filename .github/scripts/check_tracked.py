#!/usr/bin/env python3
"""Refuse files this repository must never hold: images, dumps, firmware, Apple files, keys, and device identifiers.

Usage: check_tracked.py            check every file in the index (a pre-commit hook sees what would be committed)
       check_tracked.py --history  also check the name of every file in any commit, since a removed dump stays in history

A hit on a real need is fixed by changing this file in a reviewed commit. It's a net, not an audit: docs/LICENSING.md
lists what still needs a person's eyes.
"""
import re
import subprocess
import sys

BAD_NAME = re.compile(r'''(?ix)
    (^|/)(research|backup|dtb|recovery|ramdump)/          # local-only folders
  | \.(img|simg|bin|dtb|dtbo|hfs|apfs|ipsw|dmg|ipa|ovl|dump|dmp|core|signed|hcd|wmfw|pem|key|p12|mobileprovision)$
  | (^|/)(kernel|abl|abl_last|bootreason|last_kmsg|pstore)\.log(\.txt)?$
  | (^|/)(fw_bcmdhd|bcmdhd|rgx\.fw|aoc\.|kepler\.|seurat\.|cs35l|cs40l|synaptics\.img)   # firmware by name
  | (^|/)(kernelcache|dyld_shared_cache|sep-firmware|DeviceTree\.|iBoot|LLB)              # Apple's files by name
''')
# research/ stays local-only, except these text files the Phase B brief (research/ios26-phaseb-r1/RUN.md) requires in
# git: the run brief and ledger, the m1box QEMU rig, its calibration receipt and the ios_data negative-test receipt.
# Content checks below still apply to them; they are added with `git add -f` because .gitignore keeps research/.
RESEARCH_ALLOW = re.compile(r'''(?x)^research/(
    ios26-phaseb-r1/[A-Za-z0-9_.-]+\.md
  | ios26-apps-r1/tools/m1box/[A-Za-z0-9_.-]+\.(py|sh|md)
  | ios26-apps-r1/root-r4/((tools|receipts)/)?[A-Za-z0-9_.-]+\.(md|py|sh|txt|json)
  | ios26-apps-r1/usersession/((patches|xnu-src|tests|tools|receipts)/)?[A-Za-z0-9_.-]+\.(md|patch|inc|py|c|sh|json|txt)
  | ios26-apps-r1/receipts/(m1box-rig|l1-r16|h3-static-r12)/[A-Za-z0-9_.-]+\.md
  | ios26-phaseb-r1/home-budget/(data/)?[A-Za-z0-9_.-]+\.(md|py|json)
  | ios26-connectivity-r1/bluetooth/b2/((src|tests|tools|receipts|xnu-src)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh|txt|json|diff)
  | ios26-connectivity-r1/bluetooth/(aks-wrap/((src|tests|tools|receipts|baseline|candidate/iokit/Kernel/arm)/)?)?[A-Za-z0-9_.-]+\.(md|txt|patch|inc|cpp|c|py|json)
  | ios26-connectivity-r1/wifi/android-fw/[A-Za-z0-9_.-]+\.txt
  | ios26-connectivity-r1/wifi/r2/(src/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh)
  | ios26-wifi-r1/tools/mkwifisecret\.py
  | ios26-connectivity-r1/wifi/((tools|tests|receipts)/)?[A-Za-z0-9_.-]+\.(md|py|patch|c|sh|txt|meta)
  | ios26-phaseb-r1/perf/((src|tests|tools|receipts)/)?[A-Za-z0-9_.-]+\.(md|c|h|m|py|sh|txt|json)
  | ios26-apps-r1/crashes-r9/[A-Za-z0-9_.-]+\.(md|txt)
  | ios26-phaseb-r1/brightness/((test|ref)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|cpp|py|txt)
  | ios26-apps-r1/app2/((src|tests|tools|receipts|xnu-src)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|m|py|sh|txt|json|inc)
  | ios26-connectivity-r1/wifi/r4/((src|tests|receipts)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh|txt)
  | ios26-connectivity-r1/wifi/r3/((src|tests|receipts)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh|txt)
  | ios26-phaseb-r1/live/((screen|screen/(tools|tests|src|receipts)|ustack|ustack/(tools|tests|src|receipts|xnu-src))/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh|txt|json|inc)
  | ios26-phaseb-r1/pwr/((src|tests|tools|receipts|patches)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh|txt|json)
  | ios26-phaseb-r1/configd/((src|tests|tools|receipts|qemu)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh|txt|json)
  | ios26-phaseb-r1/int/((receipts|tools)/)?[A-Za-z0-9_.-]+\.(md|py|sh|txt|json|patch)
  | ios26-phaseb-r1/cc/((src|tools|tests|receipts)/)?[A-Za-z0-9_.-]+\.(md|c|h|m|py|sh|txt|json)
  | ios26-phaseb-r1/settings/((tools|receipts)/)?[A-Za-z0-9_.-]+\.(md|py|c|sh|json|txt)
  | ios26-phaseb-r1/touch/(test/(shim/IOKit/)?)?[A-Za-z0-9_.-]+\.(md|patch|sh|cpp|c|h|txt)
  | ios26-phaseb-r1/display/(test/)?[A-Za-z0-9_.-]+\.(md|patch|py|c)
  | ios26-sensors-r1/s2/((src|tests|tools|receipts|patches)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|sh|txt|json)
  | ios26-sensors-r1/((ios|android|tools/ios|mag-r1(/(patches|src|tests|tools|receipts))?)/)?[A-Za-z0-9_.-]+\.(md|patch|c|h|py|txt)
  | ios26-gpu-r1/m2/((src|tests|tools|receipts)/)?[A-Za-z0-9_.-]+\.(md|c|h|sh|py|txt|diff|json|log|patch)
  | ios26-gpu-r1/((src|tests|tools|receipts)/)?[A-Za-z0-9_.-]+\.(md|c|h|sh|py|txt|diff|json|log)
  | ios26-phaseb-r1/fast-start/[A-Za-z0-9_.-]+\.md
  | ios26-phaseb-r1/(verify|crashdoc)/[A-Za-z0-9_.-]+\.(md|txt|json)
  | ios26-phaseb-r1/qfarm/(receipts/)?[A-Za-z0-9_.-]+\.(md|txt|json)
  | ios26-phaseb-r1/live/(expect|receipts)/[A-Za-z0-9_.-]+\.(yaml|txt|json)
  | ios26-phaseb-r1/accel-wait/build-mac/(receipts/|overlays/)?[A-Za-z0-9_.-]+\.(c|py|sh|txt|json)
  | ios26-phaseb-r1/accel-wait/((src|test)/)?[A-Za-z0-9_.-]+\.(md|py|sh|c|h|tbd)
  | ios26-phaseb-r1/corebrightness/([a-z]+/)?[A-Za-z0-9_.-]+\.(md|patch|h|c|cpp|py)
  | ios26-dualboot-r8/keys/r1[23]-?(panel|diff)?/[A-Za-z0-9_.-]+\.(c|py|diff|txt|json|md)
  | ios26-dualboot-r8/keys/r12-(panel|diff)/[A-Za-z0-9_.-]+\.(c|py|diff|txt)
  | ios26-dualboot-r8/rootview/(aks-build/)?[A-Za-z0-9_.-]+\.(md|py|txt|out|log)
  | ios26-dualboot-r8/chooser-ios/receipts/(r0b?/|r2/|r3/)?[A-Za-z0-9_.-]+\.(txt|diff|json|sha256|c|sh)
  | ios26-dualboot-r8/ios-data-persist/(tools|receipts/int1-persist)/[A-Za-z0-9_.-]+\.(py|sh|txt|json|patch|md)
  | ios26-dualboot-r8/(ios-data-persist|keys|chooser-ios)/[A-Za-z0-9_.-]+\.(md|txt)
)$''')
# 15 digits alone is an IMEI's shape. Neighbouring word characters or a dot mean a longer number, hash or decimal.
IMEI = re.compile(rb'(?<![0-9A-Za-z_.])[0-9]{15}(?![0-9A-Za-z_])')
SERIAL = re.compile(rb'(?i)(androidboot\.serialno|ro\.serialno|serialno|imei|meid)["\']?\s*[=:]\s*["\']?[0-9A-Za-z]{6,}')
MAX_BYTES = 8 * 1024 * 1024


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True).stdout


def check_content(name, data):
    """Problems in one file's bytes."""
    found = []
    if len(data) > MAX_BYTES:
        found.append(f'{len(data)} bytes, over the {MAX_BYTES} limit')
    if b'\0' in data:
        found.append('binary: this repository tracks only text')
        return found
    for pattern, what in ((IMEI, '15-digit number, IMEI-style'), (SERIAL, 'looks like a device identifier')):
        for match in pattern.finditer(data):
            line = data.count(b'\n', 0, match.start()) + 1
            found.append(f'line {line}: {what}')  # the value itself stays out of the log
    return found


def main():
    problems = []
    names = git('ls-files', '-z').decode().split('\0')[:-1]
    for name in names:
        if BAD_NAME.search(name) and not RESEARCH_ALLOW.match(name):
            problems.append(f'{name}: name is on the never-commit list')
        for problem in check_content(name, git('show', f':{name}')):
            problems.append(f'{name}: {problem}')
    if '--history' in sys.argv:
        for name in sorted(set(git('log', '--all', '--format=', '--name-only', '-z').decode().split('\0'))):
            if name and name not in names and BAD_NAME.search(name) and not RESEARCH_ALLOW.match(name):
                problems.append(f'{name}: in history, on the never-commit list')
    print('\n'.join(problems) if problems else f'clean: {len(names)} files')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
