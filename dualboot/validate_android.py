#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the preparation contract with synthetic inputs and real ARM64 objects.

This does not stage a shim, build an image, read a phone or dispatch an OS.
All outputs go to a fresh directory under ignored research/.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FILES = ('android_handoff.c', 'android_handoff.h', 'android_reference_data.h',
         'test_android_handoff.c', 'validate_android.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(output, llvm):
    output = output.absolute()
    research = (ROOT/'research').resolve()
    if output.exists() or not output.parent.resolve().is_relative_to(research):
        raise ValueError('use a new output directory under ignored research/')
    cc = shutil.which('clang')
    if not cc or not all((llvm/n).is_file() for n in ('clang','llvm-nm','llvm-readelf')):
        raise ValueError('native clang and ARM64 LLVM tools required')
    pins = {n: sha(HERE/n) for n in FILES}
    output.mkdir(parents=True, exist_ok=False)
    commands = []

    def run(name, argv):
        argv = [str(x) for x in argv]
        p = subprocess.run(argv, cwd=ROOT, capture_output=True)
        for label, data in (('stdout',p.stdout),('stderr',p.stderr)):
            (output/(name+'.'+label)).write_bytes(data)
        commands.append(dict(name=name, argv=argv, exit_code=p.returncode,
            stdout_sha256=hashlib.sha256(p.stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(p.stderr).hexdigest()))
        (output/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if p.returncode:
            raise RuntimeError(name+' refused: '+p.stderr.decode(errors='replace')[:2000])
        return p.stdout.decode()

    results, objects = {}, {}
    for gate in (0,1):
        exe = output/('host-'+str(gate))
        run('host-build-'+str(gate), [cc,'-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
            '-fsanitize=address,undefined','-fno-omit-frame-pointer',
            '-DHK_ANDROID_HANDOFF='+str(gate),'-I',HERE,
            HERE/'android_handoff.c',HERE/'test_android_handoff.c','-o',exe])
        result = json.loads(run('host-run-'+str(gate),[exe]))
        if result['gate'] != gate or result['physical_acceptance'] is not False:
            raise ValueError('host fixture result/scope mismatch')
        if result['checks'] != (20482 if gate else 8):
            raise ValueError('host checks changed; review test output')
        results[str(gate)] = result
        obj = output/('arm64-'+str(gate)+'.o')
        run('arm64-build-'+str(gate),[llvm/'clang','-target','aarch64-none-elf',
            '-std=c11','-O2','-Wall','-Wextra','-Werror','-ffreestanding','-nostdlib',
            '-fno-pic','-fno-stack-protector','-fno-jump-tables','-mgeneral-regs-only',
            '-mstrict-align','-DHK_ANDROID_HANDOFF='+str(gate),'-I',HERE,
            '-c',HERE/'android_handoff.c','-o',obj])
        symbols = run('arm64-symbols-'+str(gate),[llvm/'llvm-nm','-S',obj])
        header = run('arm64-elf-'+str(gate),[llvm/'llvm-readelf','-h','-S','-r',obj])
        text = re.search(r'^([0-9a-f]+) ([0-9a-f]+) T hk_android_prepare$',symbols,re.M)
        if not text or 'AArch64' not in header or 'ABS64' in header or re.search(r'\bU ',symbols):
            raise ValueError('missing enabled ARM64 text or unsupported relocation/reference')
        text_bytes = int(text[2],16)
        if text_bytes <= (8 if gate else 0) or (not gate and text_bytes != 8):
            raise ValueError('unexpected ARM64 preparation code size')
        objects[str(gate)] = dict(sha256=sha(obj),bytes=obj.stat().st_size,
                                  hk_android_prepare_text_bytes=text_bytes)
    if pins != {n: sha(HERE/n) for n in FILES}:
        raise ValueError('source changed during verification')
    result = dict(schema=1,status='HOST_PASS',source_sha256=pins,host=results,
        arm64_objects=objects,commands_sha256=sha(output/'commands.json'),
        input_domain='owned synthetic fixtures only',default_gate=0,
        runtime_producer=False,android_dispatch=False,physical_acceptance=False,
        image_or_kernel_build=False,device_actions=False,root_index_writes=False)
    (output/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--llvm',type=Path,default=Path('/opt/homebrew/opt/llvm/bin'))
    a = p.parse_args()
    r = validate(a.output,a.llvm)
    print(json.dumps(dict(status=r['status'],host_checks={k:v['checks'] for k,v in r['host'].items()},
        arm64_text={k:v['hk_android_prepare_text_bytes'] for k,v in r['arm64_objects'].items()},
        android_dispatch=False,physical_acceptance=False)))


if __name__ == '__main__':
    main()
