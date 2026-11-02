#!/usr/bin/env python3
"""Sequential local object/dylib/host checks; never invokes a device or kernel build."""
import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from paths import (ROOT, REPO, DEFAULT_OUTPUT, DEFAULT_BINARY, DEFAULT_DISASSEMBLY,
                   DEFAULT_PACSTRIP, DEFAULT_MKOVERLAY, DEFAULT_XNU, generated, module)

commands = []


def run(argv, log=None):
    argv = [str(x) for x in argv]
    r = subprocess.run(argv, cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    commands.append(dict(argv=argv, returncode=r.returncode))
    if log:
        (RECEIPTS/log).write_text(r.stdout)
    if r.returncode:
        print(r.stdout)
        raise RuntimeError(argv)
    return r.stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sections(path):
    """Section bytes/relocations for distinguishing code from path-bearing DWARF."""
    data = path.read_bytes()
    magic, cpu, subtype, kind, ncmds = struct.unpack_from('<IiiII', data)
    assert magic == 0xfeedfacf and cpu == 0x100000c and subtype & 0xff == 2
    p, result = 32, {}
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, p)
        if cmd == 0x19:
            count = struct.unpack_from('<I', data, p+64)[0]
            for i in range(count):
                q = p+72+80*i
                name, segment, _, length, offset, _, reloc, nreloc, flags = struct.unpack_from('<16s16sQQIIIII', data, q)
                key = (segment.rstrip(b'\0').decode(), name.rstrip(b'\0').decode())
                contents = b'' if flags & 0xff in (1, 12, 18) else data[offset:offset+length]
                result[key] = (contents, data[reloc:reloc+8*nreloc])
        p += size
    return kind, result


def compare(before, after):
    kind, old = sections(before)
    new_kind, new = sections(after)
    assert kind == new_kind
    changed = sorted('/'.join(k) for k in old.keys() | new.keys() if old.get(k) != new.get(k))
    text_equal = {k:v for k,v in old.items() if k[0]=='__TEXT'} == {k:v for k,v in new.items() if k[0]=='__TEXT'}
    return dict(before=str(before), after=str(after), before_sha256=sha(before), after_sha256=sha(after),
                byte_identical=before.read_bytes()==after.read_bytes(),
                text_sections_and_relocations_identical=text_equal, changed_sections=changed)


def main():
    global BUILD, RECEIPTS
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument('--binary', type=Path, default=DEFAULT_BINARY)
    ap.add_argument('--disassembly', type=Path, default=DEFAULT_DISASSEMBLY)
    ap.add_argument('--pacstrip', type=Path, default=DEFAULT_PACSTRIP)
    ap.add_argument('--mkoverlay', type=Path, default=DEFAULT_MKOVERLAY)
    ap.add_argument('--xnu', type=Path, default=DEFAULT_XNU)
    ap.add_argument('--base', type=Path, default=None)
    ap.add_argument('--base-sha', default=None)
    ap.add_argument('--llvm-bin', type=Path, default=Path('/opt/homebrew/opt/llvm/bin'))
    ap.add_argument('--compare-original', type=Path, help='read-only original sampler tree for byte/object comparison')
    args = ap.parse_args()
    output = generated(args.output_dir)
    BUILD, RECEIPTS = output/'build', output/'receipts'
    BUILD.mkdir(parents=True, exist_ok=True); RECEIPTS.mkdir(exist_ok=True)
    identity, comparisons, object_evidence = {}, {}, {}
    if args.compare_original:
        args.compare_original = args.compare_original.resolve()
        for relative in ('src/hsampler.c','src/hsampler.h','src/hs_hook.c',
                         'tests/differential.c','tests/kernel_overlay.c'):
            old, new = args.compare_original/relative, ROOT/relative
            assert old.read_bytes() == new.read_bytes(), relative
            identity[relative] = dict(original_sha256=sha(old), proposed_sha256=sha(new),
                                      bytes=new.stat().st_size, byte_identical=True)
        (BUILD/'original').mkdir(exist_ok=True)
    run([sys.executable, '-B', ROOT/'tools/prepare.py', '--binary', args.binary.resolve(),
         '--disassembly', args.disassembly.resolve(), '--output-dir', output], 'prepare.txt')
    sdk = run(['xcrun','--sdk','iphoneos','--show-sdk-path']).strip()
    common = ['xcrun','clang','-arch','arm64e','-isysroot',sdk,'-miphoneos-version-min=26.0',
              '-O3','-Wall','-Wextra','-Werror','-I',ROOT/'src','-I',BUILD]
    objects = []
    for gate in (0,1):
        for source in ('hsampler','hs_hook'):
            out = BUILD/f'{source}.gate{gate}.arm64e.o'
            run(common+[f'-DHK_SAMPLER_NEON={gate}','-c',ROOT/f'src/{source}.c','-o',out])
            syms = run([args.llvm_bin/'llvm-nm','--defined-only',out])
            (RECEIPTS/f'{source}.gate{gate}.symbols.txt').write_text(syms)
            text = {s.split()[-1] for s in syms.splitlines() if len(s.split())>=3 and s.split()[-2] in ('t','T')}
            kind, object_sections = sections(out)
            assert kind == 1, 'expected ARM64e object'
            expected = (['_hs_prepare','_hs_try','_hs_render','_hs_projective_axes','_hs_selfcheck','_hs_projective_selfcheck']
                        if source=='hsampler' else ['_hs_backboardd_sampler','_hs_backboardd_projective'])
            if gate:
                assert set(expected) <= text, (out, text)
                objects.append(out)
            else:
                assert not any(s.startswith('_hs_') for s in text), (out, text)
                assert not object_sections.get(('__TEXT','__text'), (b'',b''))[0]
            object_evidence[out.name] = dict(sha256=sha(out), gate=gate, architecture='ARM64e', text_symbols=sorted(text))
            if args.compare_original:
                baseline = BUILD/'original'/out.name
                run(common+[f'-DHK_SAMPLER_NEON={gate}','-c',args.compare_original/f'src/{source}.c','-o',baseline])
                pair = compare(baseline, out)
                assert pair['byte_identical'], pair
                archived = args.compare_original/'build'/out.name
                pair['delivered'] = compare(archived, out)
                assert pair['delivered']['byte_identical'], pair
                comparisons[out.name] = pair
                if gate:
                    # This diagnostic pair deliberately adds DWARF. It is not
                    # used for the production dylib or for pixel acceptance.
                    debug_old, debug_new = BUILD/'original'/f'{source}.debug.o', BUILD/f'{source}.debug.o'
                    for src, dst in ((args.compare_original/f'src/{source}.c',debug_old),
                                     (ROOT/f'src/{source}.c',debug_new)):
                        run(common+['-DHK_SAMPLER_NEON=1','-g','-c',src,'-o',dst])
                    debug_pair = compare(debug_old, debug_new)
                    assert debug_pair['text_sections_and_relocations_identical'], debug_pair
                    assert all(s.startswith('__DWARF/') for s in debug_pair['changed_sections']), debug_pair
                    comparisons[f'{source}.debug.o'] = debug_pair
    raw = BUILD/'hsampler.raw'
    run(common+['-dynamiclib','-install_name','/private/var/hk/hsampler.dylib',*objects,'-o',raw])
    run([sys.executable,'-B',args.pacstrip.resolve(),
         '--sign','-o',BUILD/'hsampler.dylib',raw],'pacstrip.txt')
    run(['codesign','--verify','--strict',BUILD/'hsampler.dylib'],'codesign.txt')
    dis = run([args.llvm_bin/'llvm-objdump','--macho','--disassemble',BUILD/'hsampler.dylib'])
    (RECEIPTS/'dylib.disassembly.txt').write_text(dis)
    assert not re.search(r'\b(?:blraa|blrab|braa|brab)(?:z)?\b|\b(?:retaa|retab|ldraa|ldrab)\b',dis)
    assert 'sqrdmulh' in dis and '_hs_render' in dis and '_hs_backboardd_projective' in dis
    strip = module('sampler_pacstrip', args.pacstrip)
    binary = bytearray((BUILD/'hsampler.dylib').read_bytes())
    remaining = []
    for start, end, _ in strip.code_ranges(binary, 0):
        for offset in range(start, end-3, 4):
            word = struct.unpack_from('<I', binary, offset)[0]
            replacement, category = strip.rewrite_word(word)
            if replacement is not None and replacement != word:
                remaining.append((offset, category))
    assert not remaining, remaining
    if args.compare_original:
        pair = compare(args.compare_original/'build/hsampler.dylib', BUILD/'hsampler.dylib')
        assert pair['text_sections_and_relocations_identical'], pair
        comparisons['hsampler.dylib'] = pair
    for sanitizer in (True,False):
        exe=BUILD/('differential-asan' if sanitizer else 'differential-release')
        host=['xcrun','clang','-arch','arm64','-DHK_SAMPLER_NEON=1','-DHS_HOOK_TEST=1','-O3',
              '-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-variable',
              '-I',ROOT/'src','-I',BUILD]
        if sanitizer:
            host += ['-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer','-g']
        run(host+[ROOT/'src/hsampler.c',ROOT/'src/hs_hook.c',ROOT/'tests/differential.c','-o',exe])
        result = run([exe,args.binary.resolve()],exe.name+'.txt')
        assert '80072 differential spans, 74148 eligible spans' in result
        print(result,end='')
    run(['xcrun','clang','-arch','arm64','-DBLAZER=1','-O2','-Wall','-Wextra','-Werror',
         '-fsanitize=address,undefined','-fno-sanitize-recover=all',
         '-idirafter',args.xnu.resolve()/'bsd',
         ROOT/'tests/kernel_overlay.c','-o',BUILD/'kernel_overlay'])
    overlay = [sys.executable,'-B',ROOT/'tests/overlay.py','--output-dir',output,'--mkoverlay',args.mkoverlay.resolve()]
    if args.base:
        overlay += ['--base',args.base.resolve()]
    if args.base_sha:
        overlay += ['--base-sha',args.base_sha]
    print(run(overlay,'overlay.txt'),end='')
    files=[ROOT/'src/hsampler.c',ROOT/'src/hsampler.h',ROOT/'src/hs_hook.c',*objects,BUILD/'hsampler.dylib']
    inputs = [args.binary,args.disassembly,args.pacstrip,args.pacstrip.parent/'renegade_platform.py',args.mkoverlay,
              *(args.xnu/'bsd'/s for s in ('miscfs/ramfs/varfs_overlay.h','miscfs/ramfs/varfs_tsv.h','kern/hk_exec_rules.h'))]
    (RECEIPTS/'build.json').write_text(json.dumps(dict(commands=commands,
        files={str(p):sha(p) for p in files}, external_inputs={str(p.resolve()):sha(p) for p in inputs},
        source_identity=identity, objects=object_evidence, comparisons=comparisons),indent=2)+'\n')
    print('PASS: gate-on ARM64e symbols, gate-off absent, signed dylib, no authenticated branch opcodes')


if __name__=='__main__':
    main()
