#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host + ARM64 object check for 0001-sweet-aks-wrap-unwrap.patch. No kernel link, guest or device.

1. Host test (ASan/UBSan, OpenSSL HMAC) and the independent Python known answer.
2. Six behaviour mutations of blazer_aks_wrap.inc must each fail the host test.
3. The patch applies to the release SweetKeyStore.cpp and reproduces candidate/ byte for byte.
4. SweetKeyStore.cpp compiled as XNU compiles it (the release build's own compile_commands entry,
   Mac paths mapped to m1box, Linux LLVM), three times: gate ON (BLAZER_AKS_WRAP=1), gate OFF
   (candidate without the define) and baseline. ON must define the wrap code and reference
   cchmac/ccsha256_ltc_di/read_random/PE_parse_boot_argn; OFF must have the baseline's exact text.
Writes receipts/ next to this tool.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[3]
XNU = ROOT / 'research/ios26-release-r1/work/xnu'
BUILD = ROOT / 'research/ios26-release-r1/work/build'
SDK = ROOT / 'research/ios26-kernel-r1/work'
MAC = '/Users/andersmadsen/Developer/personal/hackios'
LLVM = Path.home() / '.local/share/hackios-host/llvm/bin'
OUT = HERE / 'receipts'
WORK = Path(os.environ.get('AW_WORK', HERE / 'receipts/work'))
log = []


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(argv, ok=True, cwd=None, stdin=None):
    p = subprocess.run([str(x) for x in argv], capture_output=True, text=True, cwd=cwd, input=stdin)
    log.append(dict(argv=[str(x) for x in argv], cwd=str(cwd) if cwd else None, rc=p.returncode,
                    out=(p.stdout + p.stderr)[-4000:]))
    if ok is not None and (p.returncode == 0) != ok:
        raise SystemExit('unexpected rc %d: %s\n%s' % (p.returncode, ' '.join(map(str, argv))[:300], (p.stdout + p.stderr)[-3000:]))
    return p.stdout + p.stderr


def host_test(inc_dir, name, werror=True):
    exe = WORK / name
    run(['clang', '-std=c11', '-g', '-O1', '-Wall', '-Wextra', '-Werror' if werror else '-Wno-error', '-Wno-deprecated-declarations',
         '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(inc_dir),
         HERE / 'tests/test_aks_wrap.c', '-lcrypto', '-o', exe])
    p = subprocess.run([str(exe)], capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


MUTATIONS = {
    'tag-compare-skipped': ('if (diff != 0) {', 'if (0) {'),
    'class-not-bound': ('(uint8_t)(key_class >> (8 * i))', '(uint8_t)0'),
    'handle-not-checked': ('if (handle != AW_SYSTEM_BAG) {', 'if (0) {'),
    'class-zero-accepted': ('(key_class & 0x1fu) == 0', '0'),
    'keystream-one-block': ('block * 32 < len', 'block < 1'),
    'length-unchecked': ('in_len != AW_OVERHEAD + n', '0'),
}


def compile_args(src, defines, out):
    raw = (BUILD / 'obj/DEVELOPMENT_ARM64_BLAZER/iokit/DEVELOPMENT/SweetKeyStore.cpo.json').read_text()
    entry = json.JSONDecoder().raw_decode(raw)[0]
    args, i, a = [str(LLVM / 'clang')], 1, entry['arguments']
    while i < len(a):
        t = a[i]
        if t in ('-o', '-MF', '-MT', '-MQ', '-MJ'):
            i += 2
            continue
        if t in ('-MD', '-MMD', '-MP') or t.startswith('-MJ') or t.endswith('/SweetKeyStore.cpp'):
            i += 1
            continue
        # Apple clang only; none changes code generation for this file's checks.
        if t.startswith(('-mlinker-version', '-fno-odr-hash-protocols', '-mno-implicit-sme')):
            i += 1
            continue
        if t == '-Xclang' and i + 1 < len(a) and a[i + 1].startswith(('-clang-vendor-feature=', '-fno-odr-hash-protocols')):
            i += 2
            continue
        t = t.replace(MAC + '/research/ios26-release-r1/work/xnu', str(XNU))
        t = t.replace(MAC + '/research/ios26-release-r1/work/build', str(BUILD))
        t = t.replace(MAC + '/research/ios26-kernel-r1/work', str(SDK))
        args.append(t)
        i += 1
    cwd = entry['directory'].replace(MAC + '/research/ios26-release-r1/work/build', str(BUILD))
    # The candidate directory first, so the patched file's own include of blazer_aks_wrap.inc resolves.
    args[1:1] = ['-target', 'arm64-apple-macos27.0', '-I' + str(Path(src).parent), '-I' + str(XNU / 'iokit/Kernel/arm')]
    # Upstream LLVM lacks Apple clang's __builtin_xnu_types_compatible, used only inside a _Static_assert
    # (kalloc.h KALLOC_TYPE_ASSERT_COMPATIBLE_POINTER via OSDefineMetaClassAndStructors). Same for all three
    # objects; it changes no generated code. A real kernel build uses Apple clang (coordinator).
    args += ['-D__builtin_xnu_types_compatible(a,b)=1', '-D__builtin_xnu_type_signature(t)=""', '-D__builtin_xnu_type_summary(t)=0u']
    args += ['-D' + d for d in defines] + ['-o', str(out), str(src)]
    return args, cwd


def nm(obj):
    return run([LLVM / 'llvm-nm', '-g', obj])


def text_bytes(obj):
    out = run([LLVM / 'llvm-objdump', '-d', '--no-show-raw-insn', '--no-leading-addr', obj])
    return hashlib.sha256('\n'.join(l for l in out.splitlines() if not l.startswith(str(obj))).encode()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    r = {'schema': 'hackios.bluetooth.aks-wrap.check.v1', 'kind': 'host + ARM64 objects only; no kernel link, guest or device'}

    rc, out = host_test(HERE / 'src', 'test_aks_wrap')
    assert rc == 0 and out.strip().endswith('PASS'), out[-2000:]
    ref = run([sys.executable, '-I', HERE / 'tests/reference.py'], stdin=out)
    assert 'KAT PASS' in ref, ref
    r['host_test'] = 'PASS (ASan/UBSan)'
    r['kat'] = [l.split()[-1] for l in out.splitlines() if l.startswith('KAT ')][0]
    r['reference'] = 'PASS (independent Python HMAC-SHA256)'

    killed = {}
    for name, (old, new) in MUTATIONS.items():
        d = WORK / ('mut-' + name)
        d.mkdir()
        s = (HERE / 'src/blazer_aks_wrap.inc').read_text()
        assert s.count(old) >= 1, name
        (d / 'blazer_aks_wrap.inc').write_text(s.replace(old, new))
        rc, out = host_test(d, 'mut-' + name + '.exe', werror=False)  # must build; only a runtime FAIL kills it
        killed[name] = rc != 0
    assert all(killed.values()), killed
    r['mutations_rejected'] = killed

    sparse = WORK / 'apply'
    (sparse / 'iokit/Kernel/arm').mkdir(parents=True)
    shutil.copy(XNU / 'iokit/Kernel/arm/SweetKeyStore.cpp', sparse / 'iokit/Kernel/arm/')
    run(['git', 'init', '-q'], cwd=sparse)
    run(['git', 'apply', HERE / '0001-sweet-aks-wrap-unwrap.patch'], cwd=sparse)
    cand = HERE / 'candidate/iokit/Kernel/arm'
    for f in ('SweetKeyStore.cpp', 'blazer_aks_wrap.inc'):
        assert sha(sparse / 'iokit/Kernel/arm' / f) == sha(cand / f), f
    assert sha(cand / 'blazer_aks_wrap.inc') == sha(HERE / 'src/blazer_aks_wrap.inc')
    r['release_xnu_head'] = run(['git', '-C', XNU, 'rev-parse', 'HEAD']).strip()
    r['baseline_sha256'] = sha(XNU / 'iokit/Kernel/arm/SweetKeyStore.cpp')
    assert r['baseline_sha256'] == sha(HERE / 'baseline/SweetKeyStore.cpp')
    r['patch_sha256'] = sha(HERE / '0001-sweet-aks-wrap-unwrap.patch')
    r['candidate_sha256'] = {f: sha(cand / f) for f in ('SweetKeyStore.cpp', 'blazer_aks_wrap.inc')}
    r['patch_apply'] = 'PASS, reproduces candidate'

    objs = {}
    for label, src, defines in [('on', cand / 'SweetKeyStore.cpp', ['BLAZER_AKS_WRAP=1']),
                                ('off', cand / 'SweetKeyStore.cpp', []),
                                ('baseline', XNU / 'iokit/Kernel/arm/SweetKeyStore.cpp', [])]:
        o = WORK / ('SweetKeyStore.%s.o' % label)
        args, cwd = compile_args(src, defines, o)
        run(args, cwd=cwd)
        head = run([LLVM / 'llvm-readobj', '--file-headers', o])
        assert 'AArch64' in head or 'ARM64' in head, head[:400]
        syms = nm(o)
        allsyms = run([LLVM / 'llvm-nm', o])
        objs[label] = dict(sha256=sha(o), text_sha256=text_bytes(o), argv=args, cwd=cwd,
                           undefined=sorted(l.split()[-1] for l in syms.splitlines() if ' U ' in l),
                           local_text=sorted(l.split()[-1] for l in allsyms.splitlines() if re.search(r' [tT] ', l)))
        shutil.copy(o, OUT / o.name)
    on, off, base = objs['on'], objs['off'], objs['baseline']
    for s in ('_cchmac', '_ccsha256_ltc_di', '_read_random', '_PE_parse_boot_argn'):
        assert s in on['undefined'], (s, on['undefined'])
        assert s == '_PE_parse_boot_argn' or s not in off['undefined'], s  # baseline already parses boot-args
    assert not any(u.startswith('__Z6cchmac') for u in on['undefined']), 'cchmac must have C linkage'
    # aw_wrap/aw_unwrap/sweet_aks_wrap_call inline into externalMethod at -O2; the HMAC callback (taken
    # by address) stays a function, and the code's own strings must be in the ON object only.
    assert any('sweet_aks_hmac' in t for t in on['local_text']), on['local_text']
    assert not any('sweet_aks' in t and 'hmac' in t for t in off['local_text'])
    markers = [b'hackios aks wrap v1 mac', b'hackios aks wrap v1 enc', b'SWEET AKS: wrap/unwrap on', b'blazer_aks_wrap', b'refused: %s']
    for label in ('on', 'off', 'baseline'):
        data = (OUT / ('SweetKeyStore.%s.o' % label)).read_bytes()
        objs[label]['markers'] = {m.decode(): m in data for m in markers}
    assert all(objs['on']['markers'].values()) and not any(objs['off']['markers'].values()), objs
    assert off['text_sha256'] == base['text_sha256'], 'gate OFF text differs from baseline'
    assert on['text_sha256'] != base['text_sha256']
    r['arm64'] = {k: {x: v[x] for x in ('sha256', 'text_sha256', 'undefined', 'local_text', 'markers')} for k, v in objs.items()}
    r['arm64_argv'] = {k: v['argv'] for k, v in objs.items()}
    r['arm64_verdict'] = ('PASS: ON object has sweet_aks_hmac text, the wrap strings, C-linkage references to cchmac, '
                          'ccsha256_ltc_di, read_random; OFF object has none of them and its disassembly equals baseline')
    r['toolchain_shims'] = ['upstream LLVM, not Apple clang: -target arm64-apple-macos27.0',
                            '__builtin_xnu_types_compatible(a,b)=1, __builtin_xnu_type_signature(t)="", __builtin_xnu_type_summary(t)=0u '
                            '(kalloc_type metadata/static asserts only; identical for ON, OFF and baseline)',
                            'dropped Apple-only flags: -mlinker-version, -mno-implicit-sme, -Xclang -clang-vendor-feature=*, -Xclang -fno-odr-hash-protocols']
    r['toolchain'] = run([LLVM / 'clang', '--version']).splitlines()[0]
    r['not_proved'] = ['kernel link (cchmac/ccsha256_ltc_di are linked into the release kernel per its compile_commands; '
                       'a full link is the coordinator\'s build)', 'securityd accepting the blob format at runtime',
                       'bluetoothd startup past the keychain', 'any phone behaviour']
    (OUT / 'check.json').write_text(json.dumps(r, indent=2) + '\n')
    (OUT / 'commands.json').write_text(json.dumps(log, indent=2) + '\n')
    shutil.rmtree(WORK)
    print('PASS host test, KAT, %d mutations rejected, patch reproduces candidate, ARM64 ON/OFF objects' % len(killed))


if __name__ == '__main__':
    main()
