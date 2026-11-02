#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build original status observer and private receipts; no guest or root edits."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sections(path):
    data = path.read_bytes()
    magic, cpu, subtype, kind, commands = struct.unpack_from('<IiiII', data)
    assert magic == 0xfeedfacf and cpu == 0x100000c and subtype & 255 == 2
    cursor, result = 32, {}
    for _ in range(commands):
        command, size = struct.unpack_from('<II', data, cursor)
        if command == 0x19:
            count = struct.unpack_from('<I', data, cursor + 64)[0]
            for i in range(count):
                section = cursor + 72 + i * 80
                name, segment, address, length, offset = struct.unpack_from('<16s16sQQI', data, section)
                key = (segment.rstrip(b'\0').decode(), name.rstrip(b'\0').decode())
                flags = struct.unpack_from('<I', data, section + 64)[0]
                result[key] = dict(address=address, bytes=length, offset=offset, flags=flags)
        cursor += size
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pacstrip', type=Path, default=ROOT / 'research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py')
    a = parser.parse_args()
    out = a.output.resolve()
    namespace = (ROOT / 'research/ios26-connectivity-r1').resolve()
    if out == namespace or not out.is_relative_to(namespace) or out.exists():
        raise ValueError('use a new output under research/ios26-connectivity-r1')
    out.mkdir(parents=True)
    commands = []

    def run(argv, label, expect_failure=False):
        argv = list(map(str, argv))
        p = subprocess.run(argv, capture_output=True, text=True)
        (out / (label + '.log')).write_text(p.stdout + p.stderr)
        commands.append(dict(argv=argv, returncode=p.returncode))
        if expect_failure:
            assert p.returncode != 0 and 'Assertion' in p.stderr, label
        elif p.returncode != 0:
            raise RuntimeError(f'{label}: exit {p.returncode}; see saved log')
        return p.stdout

    source = HERE / 'trace.c'
    host = ['clang', '-std=c11', '-g', '-O1', '-Wall', '-Wextra', '-Werror', '-pthread', '-I' + str(HERE / 'tests')]
    for sanitizer, name in [('address,undefined', 'host'), ('thread', 'tsan')]:
        run(host + ['-fsanitize=' + sanitizer, HERE / 'tests/test_trace.c', '-o', out / name], name + '-build')
        run([out / name], name + '-test')

    original = source.read_text()
    mutations = dict(status=original.replace('return status;', 'return 0;'),
                     bound=original.replace('#define HKBTKC_LIMIT 64u', '#define HKBTKC_LIMIT 65u'),
                     opt_in=original.replace('strcmp(enabled, "1") != 0', 'strcmp(enabled, "1") == 0'))
    for label, changed in mutations.items():
        assert changed != original
        mutant = out / ('mutant-' + label + '.c')
        mutant.write_text(changed)
        test = out / ('test-' + label + '.c')
        test.write_text((HERE / 'tests/test_trace.c').read_text().replace('../trace.c', mutant.name))
        binary = out / ('test-' + label)
        run(host + [test, '-o', binary], label + '-mutant-build')
        run([binary], label + '-mutant-test', expect_failure=True)

    sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], 'sdk').strip()
    native = ['xcrun', '--sdk', 'iphoneos', 'clang', '-arch', 'arm64e', '-miphoneos-version-min=26.0',
              '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror']
    objects = {}
    expected = {'_hk_bt_SecItem' + name for name in ('CopyMatching', 'Add', 'Update', 'Delete')}
    for gate in (0, 1):
        obj = out / f'trace-gate{gate}.o'
        run(native + [f'-DHKBTKC_ENABLED={gate}', '-c', source, '-o', obj], f'object-{gate}')
        nm = run(['xcrun', 'llvm-nm', '-g', obj], f'nm-{gate}')
        text = {row.split()[-1] for row in nm.splitlines() if len(row.split()) == 3 and row.split()[-2] == 'T'}
        sec = sections(obj)
        if gate:
            interpose = [v for k,v in sec.items() if k[1] == '__interpose']
            assert expected <= text and len(interpose) == 1
            assert interpose[0]['bytes'] == 64 and interpose[0]['flags'] & 255 == 13
            assert all(' U _SecItem' + name in nm for name in ('CopyMatching', 'Add', 'Update', 'Delete'))
        else:
            assert not text and sec.get(('__TEXT', '__text'), {}).get('bytes', 0) == 0
        objects[str(gate)] = dict(sha256=sha(obj), text=sorted(text), sections={str(k): v for k,v in sec.items()})

    raw, dylib = out / 'hkbtkeychain.raw.dylib', out / 'hkbtkeychain.dylib'
    run(native + ['-dynamiclib', '-DHKBTKC_ENABLED=1', source, '-framework', 'Security', '-framework', 'CoreFoundation',
                  '-install_name', '/private/var/hk/hkbtkeychain.dylib', '-o', raw], 'dylib')
    run([sys.executable, '-I', a.pacstrip, '--sign', '-o', dylib, raw], 'pacstrip')
    run(['codesign', '--verify', '--strict', dylib], 'signature')
    sec = sections(dylib)
    interpose = [v for k,v in sec.items() if k[1] == '__interpose']
    # Apple's modern linker moves these pairs to __AUTH_CONST and emits a
    # regular section. dyld's forEachInterposingSection explicitly accepts
    # the section name under __DATA*/__AUTH* as well as S_INTERPOSING.
    assert len(interpose) == 1 and interpose[0]['bytes'] == 64
    assert any(k[1] == '__interpose' and
               (v['flags'] & 255 == 13 or k[0].startswith(('__DATA', '__AUTH')))
               for k,v in sec.items())
    dyld_ref = ROOT / 'research/upstream/reference/ios-upstream/dyld-1376.6/mach_o/UnsafeHeader.cpp'
    reference = dyld_ref.read_text()
    assert 'UnsafeHeader::forEachInterposingSection' in reference
    assert 'info.segmentName.starts_with("__AUTH")' in reference
    nm = run(['xcrun', 'llvm-nm', '-g', dylib], 'final-nm')
    assert all(name in nm for name in expected)

    spec = importlib.util.spec_from_file_location('bt_keychain_pacstrip', a.pacstrip)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = bytearray(dylib.read_bytes())
    remaining = []
    for start, end, _ in module.code_ranges(data, 0):
        for offset in range(start, end - 3, 4):
            word = struct.unpack_from('<I', data, offset)[0]
            replacement, category = module.rewrite_word(word)
            if replacement is not None and replacement != word:
                remaining.append((offset, category))
    assert not remaining
    report = dict(source_sha256=sha(source), test_sha256=sha(HERE / 'tests/test_trace.c'),
                  sdk=sdk, deployment_target='iOS 26.0', architecture='ARM64e', objects=objects,
                  dyld_section_reference=dict(path=str(dyld_ref), sha256=sha(dyld_ref),
                      url='https://github.com/apple-oss-distributions/dyld/blob/dyld-1376.6/mach_o/UnsafeHeader.cpp'),
                  dylib_sections={str(k):v for k,v in sec.items()},
                  dylib_sha256=sha(dylib), dylib_bytes=dylib.stat().st_size,
                  pacstrip_sha256=sha(a.pacstrip), pac_instructions_remaining=remaining,
                  host_asan_ubsan=True, host_tsan=True, mutations_rejected=list(mutations),
                  commands=commands, signature_verified=True,
                  runtime_loaded=False, real_security_api_execution=False, native_bluetooth=False,
                  guest_or_device_operation=False, root_or_firmware_write=False)
    (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('commands', 'objects')}, indent=2))


if __name__ == '__main__':
    main()
