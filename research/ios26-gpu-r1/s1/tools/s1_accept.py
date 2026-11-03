#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host acceptance for one blazer_gpu_tipc=7 (M3 S1) phone boot, COREMEM-INIT.md section 5.3. HOST ONLY.
Usage: python3 -I s1_accept.py <attempt>/reader.txt (or ramdump/kernel.log) <pvrsrvkm/include/rgx_fwif_sf.h>
Takes ONE boot window: from the first 'HK GPUTA: rung 7 start' to the first rung-7 'boot ended on purpose' / STOP panic after it, so the
mirrored console copy and older boots in the ram dump are never counted. Inside it, the first 'M2 fwlog' group is decoded strictly (every
entry a known id from the vendor header, entries end exactly at the pointer, no wrap); any malformed/truncated/unknown input is a FAIL, never 0.
Prints 'mmu_fault N lockup N ...' from the decoded entries, every gate, and 'S1 ACCEPT PASS' or 'S1 ACCEPT FAIL'."""
import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'm2' / 'tools'))
import fwlog_decode  # noqa: E402  (load_sf only: reads the vendor header at run time)

FAULTS = {'mmu_fault': ('RGXFW_SF_HWR_MMU_FAULT_EVENT', 'RGXFW_SF_HWR_CORE_MMU_FAULT', 'RGXFW_SF_HWR_CORE_MMU_FAULT_S7'),
          'lockup': ('RGXFW_SF_MAIN_HWR_HIT_LOCKUP', 'RGXFW_SF_MAIN_HWR_HIT_LOCKUP_DM', 'RGXFW_SF_MAIN_HWR_HIT_LOCKUP_DEPRECATED'),
          'failed_hw_poll': ('RGXFW_SF_HWR_FAILED_HW_POLL',), 'hwr_reset': ('RGXFW_SF_HWR_START_HW_RESET',),
          'assert': ('RGXFW_SF_MAIN_ASSERT_FAILED',)}
ZERO_LINE = 'mmu_fault 0 lockup 0 failed_hw_poll 0 hwr_reset 0 debug_dump 0 fw_faults 0 assert_empty 1; trace_valid 1'

def window(lines):
    s = next((i for i, l in enumerate(lines) if 'HK GPUTA: rung 7 start' in l), None)
    if s is None:
        return None
    e = next((i for i in range(s, len(lines)) if re.search(r'HK GPUTA: rung 7 (S1 PASS, boot ended on purpose|STOP:)', lines[i]) and 'panic(' in lines[i]), None)
    return lines[s:(e + 1 if e is not None else len(lines))], e is not None

def decode(win, sfs):
    """Strict: (ok, reason, entries[(name, args)])"""
    hdr = next((i for i, l in enumerate(win) if 'M2 fwlog: ptr' in l), None)
    if hdr is None:
        return False, 'no M2 fwlog group', []
    m = re.search(r'M2 fwlog: ptr (\d+) wrap (\d+), (\d+) words from (\d+)', win[hdr])
    if not m:
        return False, 'bad fwlog header', []
    ptr, wrap, n, start = map(int, m.groups())
    if wrap or start or n != ptr or ptr == 0:
        return False, f'trace not a whole unwrapped log (ptr {ptr} wrap {wrap} n {n} start {start})', []
    words, expect = [], 0
    for l in win[hdr + 1:]:
        if 'M2 fwlog: end' in l:
            break
        t = re.search(r'M2 TB ([0-9a-f]{4}): ((?:[0-9a-f]{8} ?){8})\s*$', l)
        if not t:
            continue
        if int(t.group(1), 16) != expect:
            return False, f'TB line offset {t.group(1)} where {expect:04x} expected (dropped or mirrored line)', []
        words += [int(w, 16) for w in t.group(2).split()]
        expect += 8
    else:
        return False, 'no M2 fwlog: end', []
    if len(words) < ptr:
        return False, f'{len(words)} words printed, pointer {ptr}', []
    i, out = 0, []
    while i < ptr:
        w = words[i]
        if w not in sfs:
            return False, f'word {i}: 0x{w:08x} is not a known log id', out
        name, _, e, _ = sfs[w]
        if i + 3 + e > ptr:
            return False, f'word {i}: {name} truncated at the pointer', out
        out.append((name, words[i + 3:i + 3 + e]))
        i += 3 + e
    return True, f'{len(out)} entries, {ptr} words', out

def main():
    lines = open(sys.argv[1], encoding='latin-1', errors='replace').read().splitlines()
    sfs = fwlog_decode.load_sf(sys.argv[2])
    w = window(lines)
    gates = []
    def gate(name, ok, detail=''):
        gates.append(ok)
        print(f'{"PASS" if ok else "FAIL"} {name}{": " + detail if detail else ""}')
    if not w:
        gate('rung 7 start in the log', False)
        print('S1 ACCEPT FAIL'); return 1
    win, ended = w
    text = '\n'.join(win)
    first = lambda pat: next((i for i, l in enumerate(win) if re.search(pat, l)), None)
    ok, why, ents = decode(win, sfs)
    gate('firmware trace decoded strictly', ok, why)
    counts = {k: sum(1 for nm, _ in ents if nm in v) for k, v in FAULTS.items()}
    print('decoded: ' + ' '.join(f'{k} {v}' for k, v in counts.items()) + ('' if ok else ' (INVALID TRACE: counts are not zero-evidence)'))
    gate('no fault entries in the decoded trace', ok and not any(counts.values()))
    kccb = [a for nm, a in ents if nm == 'RGXFW_SF_MTS_KCCBCMD_EXEC']
    rtn = [a for nm, a in ents if nm == 'RGXFW_SF_MTS_KCCBCMD_RTN_VALUE']
    gate('firmware executed exactly HEALTH (slot 0) then STATEFLAGS (slot 1)', [(a[0], a[1]) for a in kccb] == [(0, 0x2abc006f), (1, 0x2abc00ce)], str([(a[0], hex(a[1])) for a in kccb]))
    gate('STATEFLAGS return value 1 in the trace', [1, 1] in [a[:2] for a in rtn], str(rtn))
    c, smc = first(r'M3 COREMEM: sysinit_off=0x150 raw_heap=0xe1c0000000 section_off=0x13c000 devva=0x000000e1c013c000 lo=0xc013c000 hi=0x000000e1$'), first(r'HK GPUTA: SMC START -> 0x0$')
    gate('M3 COREMEM readback line before SMC START -> 0x0', c is not None and smc is not None and c < smc and 'readback match' in text)
    gate('SEND_FIRMWARE_IMAGE result 0', first(r'SEND_FIRMWARE_IMAGE len 8 cmd 0x1 result 0 in') is not None)
    gate('shared data to +0x239000', first(r'shared data written: main heap to \+0x239000$') is not None)
    gate('M2 boot: started 1', first(r'M2 boot: started 1 ') is not None)
    b, f = first(r'M3 S1 boot: '), first(r'M3 S1 final: ')
    gate('M3 S1 boot line all zero, trace valid', b is not None and ZERO_LINE in win[b] and ' hwr 0x1 ok;' in win[b], win[b].strip() if b is not None else 'missing')
    gate('M3 S1 final line all zero, trace valid', f is not None and ZERO_LINE in win[f] and ' hwr 0x1 ok;' in win[f], win[f].strip() if f is not None else 'missing')
    gate('STATEFLAGS_CTRL return 0x1', first(r'M2 STATEFLAGS_CTRL: slot 1 read in \d+ ms; return 0x1 ') is not None)
    gate('M2 HEALTH PASS', first(r'M2 HEALTH PASS: STATEFLAGS_CTRL executed') is not None)
    for reg in ('MMU_FAULT_STATUS_PM', 'MMU_FAULT_STATUS1', 'MMU_FAULT_STATUS2', 'MMU_FAULT_STATUS_META'):
        gate(f'{reg} zero', first(rf'blazer-gpu: reg {reg} \+0x[0-9a-f]+ 0x0000000000000000$') is not None)
    gate('timer runs, 18-register survey', first(r'blazer-gpu: CLOCK_RUNS ') is not None and first(r'blazer-gpu: survey done, 18 registers') is not None)
    gate('M3 S1 PASS line', first(r'M3 S1 PASS: clean firmware init and health; no client KICK issued') is not None)
    gate('only the deliberate rung 7 S1 PASS panic ends the window', ended and 'rung 7 S1 PASS, boot ended on purpose' in win[-1] and
         sum('panic(' in l for l in win) == 1, win[-1].strip()[:120])
    gate('no client KICK', not any(nm == 'RGXFW_SF_MTS_KCCBCMD_EXEC' and a[1] == 0x2abc0065 for nm, a in ents) and 'M3 S1 FAIL' not in text)
    print('S1 ACCEPT ' + ('PASS' if all(gates) else 'FAIL'))
    return 0 if all(gates) else 1

if __name__ == '__main__':
    sys.exit(main())
