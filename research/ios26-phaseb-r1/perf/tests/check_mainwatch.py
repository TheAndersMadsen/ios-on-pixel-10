#!/usr/bin/env python3
"""HOST: check the stderr of test_mainwatch (see test_mainwatch.m). Exit 0 and print PASS lines, or exit 1."""
import re
import sys

text = open(sys.argv[1]).read()
fails, checks = [], 0


def check(ok, what):
    global checks
    checks += 1
    print(('PASS ' if ok else 'FAIL ') + what)
    if not ok:
        fails.append(what)


block = int(re.search(r'BLOCK_FN 0x([0-9a-f]+)', text).group(1), 16)
check(re.search(r'HKMAIN: test_mainwatch\[\d+\] watching the main thread', text) is not None, 'constructor started the watcher')
check('HKMAIN: sendEvent: counted for UIApplication (UIApplication\'s)' in text, 'sendEvent: hooked on the app class')
check('ORIG 5' in text, 'original sendEvent: ran for all 5 events')
stalls = re.findall(r'HKMAIN: stall (\d+) ms pc 0x[0-9a-f]+ lr 0x[0-9a-f]+ sp 0x[0-9a-f]+ dsc_slide 0x[0-9a-f]+ main_slide 0x[0-9a-f]+\nHKMAIN: frames((?: 0x[0-9a-f]+)+)', text)
check(1 <= len(stalls) <= 2, f'stall samples during the 8 s block: {len(stalls)}')
check(all(3000 <= int(ms) <= 9000 for ms, _ in stalls), 'stall ages within 3..9 s')
hit = any(block <= int(f, 16) < block + 64 for _, fr in stalls for f in fr.split())
check(hit, 'a stall frame returns into block_main')
beats = re.findall(r'HKMAIN: test_mainwatch\[\d+\] t=(\d+) pings=(\d+) wait=(\d+) state=(-?\d+) ev touch=(\d+) press=(\d+) other=(\d+) stalls=(\d+)', text)
check(len(beats) >= 2, f'heartbeats: {len(beats)}')
last = beats[-1] if beats else None
check(last is not None and last[4:7] == ('3', '1', '1'), 'last heartbeat counts touch=3 press=1 other=1')
check(last is not None and last[3] == '1', 'state read from applicationState (1)')
check(any(int(b[2]) >= 3000 for b in beats), 'a heartbeat during the block shows wait >= 3000 ms')
check(all(int(b[1]) <= int(b[0]) + 3 for b in beats), 'about one main-queue ping per second (no busy loop)')
check(last is not None and int(last[2]) < 1500, 'main queue drains again after the block (wait < 1.5 s)')
check(re.search(r'HKMAIN: gap (\d+) ms', text) is not None, 'SIGSTOP/SIGCONT reported as a gap')
check('DONE' in text, 'test ran to the end')
print(f'{"PASS" if not fails else "FAIL"} hk_mainwatch host test: {checks} checks, {len(fails)} failed')
sys.exit(1 if fails else 0)
