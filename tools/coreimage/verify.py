#!/usr/bin/env python3
"""Verify the bounded CoreImage QEMU experiment; never accept context creation alone."""
import argparse
import hashlib
import json
from pathlib import Path
import re

CASE = re.compile(r'HKCI: CASE (\w+) context=(\d+) sw=(\d+) gl=(\d+) identity=(\d+) invert=(\d+)')
LABELS = {'default', 'request_gpu', 'request_cpu', 'reference_cpu_2'}
ROOT = '205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7'
KERNEL = '5aad89780e798d730aa00372dd17568917cc81d97fc231df0fcf1a9fda80fca8'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_log(text, patched):
    require('REFUSED' not in text and 'HKCI: PIXELS' not in text and 'EXCEPTION' not in text,
        'probe refusal, bad pixels or exception')
    require(len(re.findall(r'HKCI: BEGIN ', text)) == 1, 'expected one probe execution')
    require(re.search(rf'HKCI: BEGIN pid=\d+ patched={int(patched)} isWidget={int(patched)}\b', text),
        'wrong runtime patch/value')
    require('HKCI: INPUT constant_red=1 space=1 format=264' in text, 'invalid input/reference format')
    rows = CASE.findall(text)
    require(len(rows) == 4 and {r[0] for r in rows} == LABELS, 'missing/duplicate probe cases')
    cases = {r[0]:tuple(map(int,r[1:])) for r in rows}
    for name, values in cases.items():
        expected = (1,1,0,1,1) if patched or name == 'reference_cpu_2' else (0,0,0,0,0)
        require(values == expected, f'{name}: expected {expected}, observed {values}')
    require(text.count('HKCI: END observers restored') == 1, 'observers were not restored')
    require(not re.search(r'panic\(cpu', text), 'kernel panic')
    return cases


def verify(work, control_name='control-r3', candidate_name='widget-r3'):
    clone = json.loads((work/'receipts/widget-root.json').read_text())
    require(clone.get('only_planned_changes') is True and clone.get('source_unchanged') is True,
        'clone has no complete isolation receipt')
    require(clone['source_sha256'] == ROOT, 'wrong source root')
    changes = clone['changes']
    require(len(changes) == 2 and [c['kind'] for c in changes] == ['isWidget','page_hash'],
        'extra clone changes')
    require(changes[0]['before'] == '688127f0085944f9' and
        changes[0]['after'] == '20008052c0035fd6', 'wrong instruction edit')
    signature = json.loads((work/'receipts/widget-signature.json').read_text())
    require(signature == {'pages_checked':5318, 'invalid':0}, 'signature verification failed')
    arms = {}
    intents = []
    for name, patched in ((control_name,False),(candidate_name,True)):
        run = work/'runs'/name
        intent = json.loads((run/'intent.json').read_text())
        result = json.loads((run/'exit.json').read_text())
        require(intent['kernel_sha'] == KERNEL, f'{name}: unexpected kernel')
        require(intent['root_sha'] == (clone['output_sha256'] if patched else ROOT), f'{name}: wrong root')
        require(result.get('exit') == 0 and result.get('root_unchanged') is True, f'{name}: incomplete/changed input')
        require(not result.get('error') and not result.get('log_bytes_lost'), f'{name}: error or log loss')
        data = (run/'console.log').read_bytes()
        text = data.decode(errors='replace')
        cases = check_log(text,patched)
        arms[name] = {'patched':patched, 'cases':cases,
            'console_sha256':hashlib.sha256(data).hexdigest(), 'root_sha256':intent['root_sha'],
            'root_unchanged':True, 'elapsed_host_seconds':result['elapsed']}
        args = re.sub(r'\bepoch=\d+', 'epoch=<clock>', intent['args'])
        intents.append(args)
    require(intents[0] == intents[1], 'guest boot arguments differ beyond clock epoch')
    launch = json.loads((work/'receipts/launch-r3.json').read_text())
    overlays = [cmd[cmd.index('--var-overlay')+1] for cmd in launch.values()]
    require(len(set(overlays)) == 1, 'probe overlays differ')
    overlay = hashlib.sha256(Path(overlays[0]).read_bytes()).hexdigest()
    require(overlay == json.loads((work/'receipts/probe-r3.json').read_text())['overlay_sha256'],
        'probe overlay changed')
    return {'ok':True, 'scope':'QEMU constant-color CoreImage context/identity/invert/guard checks',
        'kernel_sha256':KERNEL, 'overlay_sha256':overlay, 'runs':arms,
        'physical_result':None, 'bitmap_input_result':'earlier probe failed; cause not isolated',
        'missing_icons_fixed':None, 'performance_result':None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.work)
    if args.output:
        with args.output.open('x') as f:
            json.dump(result,f,indent=2); f.write('\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
