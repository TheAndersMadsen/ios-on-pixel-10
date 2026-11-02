#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run host checks and optionally build BOTH real BLAZER-enabled XNU ARM64 objects.

python3 -I dualboot/validate.py
python3 -I dualboot/validate.py --base research/ios26-release-r1/work/xnu \
    --fixture research/ios26-dualboot-r2/stage-rN --objects
The fixture is made by tools/stage_dualboot_readback.py. Never edits release.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', type=Path)
    p.add_argument('--fixture', type=Path)
    p.add_argument('--objects', action='store_true')
    a = p.parse_args()
    out = ROOT/'research/ios26-dualboot-r2/receipts'
    out.mkdir(parents=True, exist_ok=True)
    compiler = os.environ.get('CC', 'cc')
    flags = ['-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined']
    run([compiler, *flags, ROOT/'dualboot/readback.c', ROOT/'dualboot/test_readback.c', '-o', out/'test-readback'])
    run([out/'test-readback'])
    run([sys.executable, '-W', 'error::ResourceWarning', '-I', ROOT/'tools/test_dualboot.py'])
    if a.base:
        base = a.base.resolve()
        run([compiler, *flags, '-I'+str(ROOT/'dualboot/testinclude'), '-I'+str(base/'bsd'),
             ROOT/'dualboot/test_xnu_adapter.c', '-o', out/'test-xnu-adapter'])
        run([out/'test-xnu-adapter'])
    if not a.objects:
        return
    if not a.base or not a.fixture:
        p.error('--objects requires --base and --fixture')
    manifest = json.loads((a.fixture/'stage.json').read_text())
    for name, digest in manifest['base_sha256'].items():
        if hashlib.sha256((base/name).read_bytes()).hexdigest() != digest:
            raise ValueError('base changed since staging; make a new fixture')
    for name, digest in manifest['staged_sha256'].items():
        if hashlib.sha256((a.fixture/'xnu'/name).read_bytes()).hexdigest() != digest:
            raise ValueError('fixture source changed since staging')
    stage = a.fixture.resolve()/'xnu'
    out = a.fixture.resolve()/'arm64'; out.mkdir(exist_ok=True)
    commands = base.parent/'build/obj/DEVELOPMENT_ARM64_BLAZER'
    nm = Path('/opt/homebrew/opt/llvm/bin/llvm-nm')
    records = {}
    for rel, symbols in {
        'osfmk/arm64/blazer_usbcon.c': ['_hk_rb_worker', '_hk_rb_select', '_hk_rb_finish', '_hk_rb_packet', '_blazer_usbcon_start'],
        'bsd/dev/hakios.blazer_ufs.c': ['_n882_blazer_readback_lun', '_n882_blazer_read10_exact', '_hakios_blazer_ufs_init']
    }.items():
        name = Path(rel).stem
        hits = list(commands.rglob(name+'.o.json'))
        if len(hits) != 1: raise ValueError(f'{name}: expected one recorded command, got {len(hits)}')
        j = json.JSONDecoder().raw_decode(hits[0].read_text())[0]
        args, command, i = j['arguments'], [], 0
        while i < len(args):
            t = args[i]
            if t in ('-MF', '-MT', '-MJ', '-MQ'): i += 2; continue
            if t in ('-MD', '-MMD', '-MP'): i += 1; continue
            if t == j['file']: command.append(str(stage/rel)); i += 1; continue
            if t == '-o': command += ['-o', str(out/(name+'.o'))]; i += 2; continue
            command.append(t); i += 1
        comp = rel.split('/')[0]
        # Preserve component order: bsd/kern/ast.h must not shadow osfmk/kern/ast.h.
        command[1:1] = ['-DBLAZER=1', '-I'+str(stage/comp), '-I'+str(stage/Path(rel).parent),
                        '-I'+str(base/comp), '-I'+str(base/Path(rel).parent),
                        '-I'+str(a.fixture.resolve()/'export/bsd')]
        (out/(name+'.flags.json')).write_text(json.dumps(command, indent=2)+'\n')
        result = subprocess.run(command, cwd=j['directory'], capture_output=True, text=True)
        (out/(name+'.stderr')).write_text(result.stderr)
        if result.returncode:
            print(result.stderr[-8000:], file=sys.stderr); result.check_returncode()
        data = (out/(name+'.o')).read_bytes()
        # Mach-O 64 little endian, CPU_TYPE_ARM64. An empty gated unit cannot pass symbols below.
        if data[:8] != bytes.fromhex('cffaedfe0c000001'): raise ValueError('not an ARM64 Mach-O object')
        names = run([nm, '-a', out/(name+'.o')], capture_output=True, text=True).stdout
        (out/(name+'.nm')).write_text(names)
        for symbol in symbols:
            matches = [line for line in names.splitlines() if line.split()[-1:] == [symbol]]
            if not matches or any(' U ' in line for line in matches): raise ValueError('missing definition '+symbol)
        records[rel] = dict(sha256=hashlib.sha256(data).hexdigest(), symbols=symbols, BLAZER=1)
        print(name+': ARM64 object and expected definitions PASS')
    (out/'objects.json').write_text(json.dumps(records, indent=2)+'\n')


if __name__ == '__main__': main()
