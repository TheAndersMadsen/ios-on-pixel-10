#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Test tools/s1_accept.py on the gpu2 phone log (out of git; path as argv[1]) relabelled as rung 7: it must FAIL with gpu2's fault counts.
A synthetic clean boot (gpu2's log with every HWR-group entry removed from the trace and the S1 lines added) must PASS, and each corruption
of it (dropped TB line, wrapped, pointer past the words, unknown id, a second panic, a missing gate line, a KICK) must FAIL.
Usage: test_s1_accept.py <gpu2 reader.txt> <rgx_fwif_sf.h>"""
import re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'm2' / 'tools'))
import fwlog_decode
TOOL = Path(__file__).resolve().parents[1] / 'tools' / 's1_accept.py'
reader, sfh = sys.argv[1], sys.argv[2]
sfs = fwlog_decode.load_sf(sfh)
T = Path('/tmp/s1-accept-test'); T.mkdir(exist_ok=True)
fails = 0
def run(name, lines, want, must=()):
    global fails
    p = T / (name + '.txt'); p.write_text('\n'.join(lines) + '\n')
    r = subprocess.run([sys.executable, '-I', str(TOOL), str(p), sfh], capture_output=True, text=True)
    ok = (r.returncode == 0) == want and all(m in r.stdout for m in must)
    fails += not ok
    print(f'{"ok  " if ok else "BAD "} {name}: rc {r.returncode}' + ('' if ok else '\n' + r.stdout))

src = open(reader, encoding='latin-1').read().splitlines()
# gpu2's console only up to its own rung panic (the first copy), relabelled
st = next(i for i, l in enumerate(src) if 'HK GPUTA: rung 6 start' in l)
end = next(i for i in range(st, len(src)) if 'rung 6 PASS, boot ended on purpose' in src[i] and src[i].startswith('panic('))
g2 = [l.replace('rung 6 start', 'rung 7 start').replace('rung 6 PASS, boot ended', 'rung 7 S1 PASS, boot ended') for l in src[:end + 1]]
run('gpu2', g2, False, ('decoded: mmu_fault 2 lockup 1 failed_hw_poll 8 hwr_reset 1',))

# Clean synthetic: the trace without HWR-group entries, S1 lines added where the kernel prints them
h = next(i for i, l in enumerate(g2) if 'M2 fwlog: ptr' in l); e = next(i for i in range(h, len(g2)) if 'M2 fwlog: end' in g2[i])
words = []
for l in g2[h + 1:e]:
    m = re.search(r'M2 TB [0-9a-f]{4}: ((?:[0-9a-f]{8} ?){8})', l)
    if m: words += [int(w, 16) for w in m.group(1).split()]
ptr = int(re.search(r'ptr (\d+)', g2[h]).group(1)); keep, i = [], 0
while i < ptr:
    name, _, n, grp = sfs[words[i]]
    if grp != 'HWR' and 'HIT_LOCKUP' not in name: keep += words[i:i + 3 + n]
    i += 3 + n
pad = keep + [0] * (-len(keep) % 8)
tb = [f'HK GPUTA: M2 TB {j:04x}: ' + ' '.join(f'{w:08x}' for w in pad[j:j + 8]) for j in range(0, len(pad), 8)]
fw = [f'HK GPUTA: M2 fwlog: ptr {len(keep)} wrap 0, {len(keep)} words from 0'] + tb + ['HK GPUTA: M2 fwlog: end']
Z = 'mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 0 debug_dump 0 fw_faults 0 assert_empty 1; trace_valid 1 words 120 entries 20 other 20; hwr 0x1 ok; fwccb w 0 r 0 pending 0 fault_cmds 0'
clean = []
for i, l in enumerate(g2):
    if h <= i <= e:
        if i == h: clean += fw
        continue
    if 'HK GPUTA: SMC START -> 0x0' in l:
        clean += ['HK GPUTA: M3 COREMEM: sysinit_off=0x150 raw_heap=0xe1c0000000 section_off=0x13c000 devva=0x000000e1c013c000 lo=0xc013c000 hi=0x000000e1',
                  'HK GPUTA: M3 COREMEM forms: sysinit devva 0xe1c013c000; trusty fw_va 0xc013c000 and pa 0xba03c000 (SEND only, not sysinit); readback match']
    clean.append(l)
    if 'M2 boot: assert0 empty' in l: clean.append('HK GPUTA: M3 S1 boot: ' + Z)
    if 'M2 after-stateflags: assert0 empty' in l: clean.append('HK GPUTA: M3 S1 final: ' + Z)
    if 'M2 HEALTH PASS' in l: clean.append('HK GPUTA: M3 S1 PASS: clean firmware init and health; no client KICK issued')
run('clean', clean, True, ('decoded: mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 0 assert 0', 'S1 ACCEPT PASS'))
mirror = clean + clean          # the console mirror: counted once
run('clean+mirror', mirror, True)
ti = next(i for i, l in enumerate(clean) if 'M2 TB 0008' in l)
run('dropped-TB-line', clean[:ti] + clean[ti + 1:], False)
run('wrapped', [l.replace(' wrap 0, ', ' wrap 1, ') if 'M2 fwlog: ptr' in l else l for l in clean], False)
run('pointer-past-words', [re.sub(r'ptr \d+ wrap 0, \d+ words', f'ptr {len(pad) + 8} wrap 0, {len(pad) + 8} words', l) if 'M2 fwlog: ptr' in l else l for l in clean], False)
run('unknown-id', [l.replace('M2 TB 0000: ' + f'{keep[0]:08x}', 'M2 TB 0000: 7ff00000') for l in clean], False)
run('second-panic', clean[:-1] + ['panic(cpu 2 caller 0x0): something else'] + clean[-1:], False)
run('no-coremem-line', [l for l in clean if 'M3 COREMEM: sysinit_off' not in l], False)
run('fault-on-boot-line', [l.replace('M3 S1 boot: mmu_fault 0', 'M3 S1 boot: mmu_fault 1') for l in clean], False)
run('hwr-bad', [l.replace('hwr 0x1 ok', 'hwr 0xa BAD') if 'M3 S1 final' in l else l for l in clean], False)
run('no-s1-pass', [l for l in clean if 'M3 S1 PASS' not in l], False)
run('register-nonzero', [l.replace('MMU_FAULT_STATUS_META +0xe160 0x0000000000000000', 'MMU_FAULT_STATUS_META +0xe160 0x0000000000000001') for l in clean], False)
print(f'test_s1_accept: {fails} failed')
sys.exit(fails != 0)
