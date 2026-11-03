#!/usr/bin/env python3
"""keys_laguna: host test on mocked MMIO, then ARM64 objects with the gates on and off, inspected.

  python3 -I shim/test_keys.py          (LLVM=<dir with clang, llvm-nm, llvm-objdump, llvm-readelf>)

Checks: the mocked-MMIO host test passes (ASan/UBSan); keys_laguna.o for AArch64 with TGL_KEYS_POLL=1
defines keys_init/keys_poll/keys_raw_levels, has no ABS64 relocation, makes no direct MMIO access (only
the injected reader, blr) and builds the RXDATA PA 0x052b0010; with the gate off it is empty; chooser.c
with TGL_CHOOSER_KEYS_POLL=1 references keys_poll and defines chooser_keys_db, refuses the hook without
TGL_CHOOSER_KEYS, and compiles to the same symbols as before when the hook gate is off."""
import os, re, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLVM = Path(os.environ.get('LLVM', Path.home() / '.local/share/hackios-host/llvm/bin'))
HOSTCC = os.environ.get('HOSTCC', 'cc')
XFLAGS = ['-target', 'aarch64-unknown-none-elf', '-O2', '-ffreestanding', '-nostdlib', '-fno-pic', '-mgeneral-regs-only',
          '-mstrict-align', '-fno-stack-protector', '-fno-jump-tables', '-Wall', '-Wextra', '-Werror']
CHOOSER_KEYS = ['-DTGL_CHOOSER=1', '-DTGL_CHOOSER_KEYS=1', '-DTGL_STAMP_NONCE=0x1ULL']
fails = 0


def ok(c, m):
    global fails
    print(('ok   ' if c else 'FAIL ') + m)
    fails += not c


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def xcc(src, out, flags):
    r = sh([str(LLVM / 'clang'), *XFLAGS, *flags, '-c', str(HERE / src), '-o', str(out)], cwd=HERE)
    return r


def syms(o):
    return {l.split()[-1]: l.split()[-2] for l in sh([str(LLVM / 'llvm-nm'), str(o)]).stdout.splitlines() if l.strip()}


with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    r = sh([HOSTCC, '-O1', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-DTGL_KEYS_POLL=1',
            '-o', str(t / 'kt'), 'keys_laguna.c', 'keys_laguna_test.c'], cwd=HERE)
    ok(r.returncode == 0, 'host test builds' + (': ' + r.stderr if r.returncode else ''))
    if r.returncode == 0:
        r = sh([str(t / 'kt')])
        print('     ' + r.stdout.strip().splitlines()[-1])
        ok(r.returncode == 0, 'host test on mocked MMIO passes')

    o = t / 'keys_on.o'
    r = xcc('keys_laguna.c', o, ['-DTGL_KEYS_POLL=1'])
    ok(r.returncode == 0, 'AArch64 keys_laguna.o, TGL_KEYS_POLL=1' + (': ' + r.stderr if r.returncode else ''))
    if r.returncode == 0:
        hdr = sh([str(LLVM / 'llvm-readelf'), '-h', str(o)]).stdout
        ok('AArch64' in hdr, 'object machine is AArch64')
        s = syms(o)
        ok(all(s.get(n) == 'T' for n in ('keys_init', 'keys_poll', 'keys_raw_levels')), f'defines keys_init/poll/raw_levels: {s}')
        ok(not [n for n, k in s.items() if k == 'U'], 'no undefined symbols (reader is injected)')
        rel = sh([str(LLVM / 'llvm-readelf'), '-r', str(o)]).stdout
        ok('ABS64' not in rel, 'no ABS64 relocation (shim image contract)')
        dis = sh([str(LLVM / 'llvm-objdump'), '-d', '--no-show-raw-insn', str(o)]).stdout
        ok('blr' in dis, 'pad reads go through the injected reader (blr)')
        ok(re.search(r'mov\s+w\d+, #0x10\b', dis) and re.search(r'movk\s+w\d+, #0x52b, lsl #16', dis),
           'builds RXDATA PA 0x052b0010 (pad 48 base; 51/52 add 0x3000/0x4000)')

    o = t / 'keys_off.o'
    r = xcc('keys_laguna.c', o, [])
    ok(r.returncode == 0 and not syms(o), 'gate off: keys_laguna.o is empty')

    o = t / 'chooser_hook.o'
    r = xcc('chooser.c', o, CHOOSER_KEYS + ['-DTGL_KEYS_POLL=1', '-DTGL_CHOOSER_KEYS_POLL=1'])
    ok(r.returncode == 0, 'chooser.o with TGL_CHOOSER_KEYS_POLL=1' + (': ' + r.stderr if r.returncode else ''))
    if r.returncode == 0:
        s = syms(o)
        ok(s.get('keys_poll') == 'U' and s.get('keys_init') == 'U' and s.get('chooser_keys_db') == 't',
           'hook calls keys_init/keys_poll and defines chooser_keys_db')
    r = xcc('chooser.c', t / 'bad.o', ['-DTGL_CHOOSER=1', '-DTGL_STAMP_NONCE=0x1ULL', '-DTGL_KEYS_POLL=1', '-DTGL_CHOOSER_KEYS_POLL=1'])
    ok(r.returncode != 0 and 'TGL_CHOOSER_KEYS_POLL needs' in r.stderr, 'hook without TGL_CHOOSER_KEYS refuses to build')
    r = xcc('chooser.c', t / 'plain.o', CHOOSER_KEYS)
    s = syms(t / 'plain.o') if r.returncode == 0 else {}
    ok(r.returncode == 0 and not {'keys_init', 'keys_poll', 'keys_raw_levels', 'chooser_keys_db'} & set(s) and 'chooser_keys_start' in s,
       'hook gate off: chooser.o has no keys_laguna reference (r8 path unchanged)')

print(f'test_keys: {"PASS" if not fails else f"{fails} FAIL"}')
sys.exit(1 if fails else 0)
