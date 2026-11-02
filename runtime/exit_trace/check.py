#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Test and stage an exit observer without editing or linking the release tree."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'changed source anchor: {old!r}')
    return text.replace(old, new, 1)


def run(args, out, label, cwd=None, expected=0):
    p = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, text=True)
    (out / (label + '.log')).write_text(p.stdout + p.stderr)
    if p.returncode != expected:
        raise RuntimeError(f'{label}: exit {p.returncode}; see {out / (label + ".log")}')
    return p.stdout


def recipe(base, layer, name):
    release = base.parent.parent
    rec = release / f'work/build/obj/DEVELOPMENT_ARM64_BLAZER/{layer}/DEVELOPMENT/{name}.o.json'
    return json.JSONDecoder().raw_decode(rec.read_text())[0]


def compile_one(rec, source, target, gate):
    args, i = [], 0
    original = rec['arguments']
    while i < len(original):
        arg = original[i]
        if arg in ('-MD', '-MMD', '-MP', '-w'):
            i += 1
            continue
        if arg in ('-MF', '-MT', '-MJ', '-MQ', '-o'):
            if arg == '-o':
                args.extend(['-o', str(target)])
            i += 2
            continue
        if arg.startswith('-MJ'):
            i += 1
            continue
        if arg == rec['file']:
            arg = str(source)
        args.append(arg)
        i += 1
    args.extend(['-UBLAZER', f'-DBLAZER={gate}', '-Werror=invalid-noreturn'])
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True, help='read-only XNU source checkout')
    parser.add_argument('--output', type=Path, required=True, help='new ignored connectivity receipt directory')
    a = parser.parse_args()
    base, out = a.base.resolve(), a.output.resolve()
    namespace = (ROOT / 'research/ios26-connectivity-r1').resolve()
    if out == namespace or not out.is_relative_to(namespace) or out.exists():
        raise ValueError('use a new subdirectory under research/ios26-connectivity-r1')
    if out.is_relative_to(base) or base.is_relative_to(out):
        raise ValueError('output overlaps the release source')

    paths = ('bsd/kern/kern_exit.c', 'osfmk/conf/files.arm64')
    originals = {name: (base / name).read_text() for name in paths}
    changed = dict(originals)
    anchor = '__attribute__((noreturn))\nvoid\nexit(proc_t p, struct exit_args *uap, int *retval)\n{\n'
    before = '#if defined(BLAZER) && BLAZER\nextern void blazer_exit_trace(struct proc *, int);\n#endif\n\n'
    after = '#if defined(BLAZER) && BLAZER\n\tblazer_exit_trace(p, (int)uap->rval);\n#endif\n'
    changed[paths[0]] = once(changed[paths[0]], anchor, before + anchor + after)
    anchor = 'osfmk/arm64/hk_user_trace.c\tstandard\n'
    changed[paths[1]] = once(changed[paths[1]], anchor, anchor + 'osfmk/arm64/blazer_exit_trace.c\tstandard\n')
    new_path = 'osfmk/arm64/blazer_exit_trace.c'
    changed[new_path] = (HERE / 'blazer_exit_trace.c').read_text()
    out.mkdir(parents=True)
    for name, text in changed.items():
        p = out / 'xnu' / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    patch = ''.join(''.join(difflib.unified_diff(originals.get(name, '').splitlines(True), text.splitlines(True),
                    fromfile='a/' + name if name in originals else '/dev/null', tofile='b/' + name))
                    for name, text in changed.items())
    (out / 'exit-trace.patch').write_text(patch)
    run(['git', 'apply', '--check', '--whitespace=error', out / 'exit-trace.patch'], out, 'apply', cwd=base)

    host = ['clang', '-std=c11', '-g', '-O1', '-Wall', '-Wextra', '-Werror', '-pthread',
            '-I' + str(HERE / 'tests'), HERE / 'tests/test_exit_trace.c']
    run(host + ['-fsanitize=address,undefined', '-o', out / 'test'], out, 'host-build')
    run([out / 'test'], out, 'host-test')
    run(host + ['-fsanitize=thread', '-o', out / 'test-tsan'], out, 'tsan-build')
    run([out / 'test-tsan'], out, 'tsan-test')

    objects = {}
    for name, gate, expected in [('observer', 1, '_blazer_exit_trace'), ('observer-off', 0, None),
                                 ('kern_exit', 1, '_exit'), ('kern_exit-off', 0, '_exit')]:
        source = out / 'xnu' / (paths[0] if name.startswith('kern_exit') else new_path)
        rec = recipe(base, 'bsd', 'kern_exit') if name.startswith('kern_exit') else recipe(base, 'osfmk', 'hk_user_trace')
        target = out / (name + '.o')
        args = compile_one(rec, source, target, gate)
        run(args, out, name + '-build', cwd=rec['directory'])
        file = run(['file', target], out, name + '-file')
        nm = run(['nm', '-g', target], out, name + '-nm')
        dis = run(['xcrun', 'llvm-objdump', '-d', '--no-show-raw-insn', target], out, name + '-disassembly')
        assert 'arm64' in file and (expected is None or any(row.split()[-2:] == ['T', expected] for row in nm.splitlines()))
        if name == 'observer':
            assert ' U _backtrace_user' in nm and ' U _vm_shared_region_get' in nm
            assert '\tret' in dis and 'hk_exit_trace' not in nm
        if name == 'observer-off':
            assert not nm.strip() and not dis.split('Disassembly of section')[1:]
        if name.startswith('kern_exit'):
            assert any(row.split()[-2:] == ['T', '_exit1'] for row in nm.splitlines())
            relocs = run(['xcrun', 'llvm-objdump', '-r', target], out, name + '-relocations')
            assert '_exit1' in relocs and '_thread_exception_return' in relocs
            assert (' U _blazer_exit_trace' in nm) == bool(gate)
        objects[name] = dict(BLAZER=gate, sha256=digest(target), file=file.strip(), command=args,
                             expected_symbol=expected)

    # A caller's accidental noreturn annotation must be diagnosed at compilation.
    mutant = out / 'mutant.c'
    mutant.write_text('#define BLAZER 1\n#define HKET_HOST_TEST 1\n' + changed[new_path].replace(
        'void\nblazer_exit_trace(struct proc *p, int status)',
        '__attribute__((noreturn)) void\nblazer_exit_trace(struct proc *p, int status)'))
    args = ['clang', '-std=c11', '-O2', '-Werror=invalid-noreturn', '-I' + str(HERE / 'tests'),
            '-c', mutant, '-o', out / 'mutant.o']
    p = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    (out / 'noreturn-mutant.log').write_text(p.stdout + p.stderr)
    assert p.returncode != 0 and 'should not return' in p.stderr
    report = dict(base=str(base), base_commit=run(['git', 'rev-parse', 'HEAD'], out, 'base-commit', cwd=base).strip(),
                  base_sha256={name: hashlib.sha256(text.encode()).hexdigest() for name, text in originals.items()},
                  staged_sha256={name: hashlib.sha256(text.encode()).hexdigest() for name, text in changed.items()},
                  patch_sha256=digest(out / 'exit-trace.patch'), objects=objects,
                  host_asan_ubsan=True, host_tsan=True, noreturn_mutant_rejected=True,
                  linked=False, booted=False, radio_operation=False)
    assert all((base / name).read_text() == text for name, text in originals.items()), 'release changed during qualification'
    (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('objects', 'staged_sha256')}, indent=2))


if __name__ == '__main__':
    main()
