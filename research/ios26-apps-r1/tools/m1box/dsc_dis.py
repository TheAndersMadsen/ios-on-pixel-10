#!/usr/bin/env python3
"""Disassemble the function containing (or ending at) an unslid address in an on-device dyld cache and annotate
references: bl targets (nearest symbol), adrp+add/ldr targets as C strings, or as pointers to C strings
(ObjC selector refs). Uses tools/dsc_sym.py's helpers and llvm-mc. Reading aid only.

    dsc_dis.py CACHE UNSLID_ADDR [--end]    (--end: the address is a return address after a noreturn call)
"""
import bisect, re, struct, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dsc_sym as S

LLVM = Path('/home/anders/.local/share/hackios-host/llvm/bin')


def cstr(cache, addr, n=200):
    try:
        b = cache.read(addr, n)
    except Exception:
        return None
    e = b.find(b'\0')
    s = b[:e if e >= 0 else n]
    if len(s) >= 3 and all(32 <= c < 127 or c in (9, 10) for c in s):
        return s.decode()
    return None


def main():
    cache = S.LP.CacheImages(sys.argv[1]); u = int(sys.argv[2], 0); end_mode = '--end' in sys.argv
    probe = u - 4 if end_mode else u
    info = cache.who(probe); base = probe - info['image_offset']
    syms = S.image_symbols(cache, base); starts = [s[0] for s in syms]
    i = bisect.bisect_right(starts, probe) - 1
    start = syms[i][0]; stop = syms[i + 1][0] if i + 1 < len(syms) else probe + 4
    if stop - start > 0x4000: start = max(start, probe - 0x800)
    code = cache.read(start, stop - start)
    import tempfile, os
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / 'f.bin'; obj = Path(td) / 'f.o'; raw.write_bytes(code)
        subprocess.run([str(LLVM / 'llvm-objcopy'), '-I', 'binary', '-O', 'elf64-littleaarch64', '--rename-section', '.data=.text,code,alloc,load,readonly', str(raw), str(obj)], check=True)
        dis = subprocess.run([str(LLVM / 'llvm-objdump'), '-d', '--no-show-raw-insn', '--triple=arm64e-apple-ios', '--mattr=+pauth,+v8.5a', f'--adjust-vma={start:#x}', str(obj)], capture_output=True, text=True, check=True).stdout
    insns = []
    for l in dis.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+(.*)$', l)
        if m: insns.append((int(m[1], 16), m[2].split('//')[0].strip()))
    print(f'image {info["image"]} function {start:#x}..{stop:#x} ({syms[i][1]}) {len(insns)} insns')
    regs = {}
    for pc, ins in insns:
        note = ''
        m = re.match(r'adrp\s+(x\d+),\s*0x([0-9a-f]+)', ins)
        if m:
            regs[m[1]] = int(m[2], 16)
        m = re.match(r'add\s+(x\d+),\s*(x\d+),\s*#(0x[0-9a-f]+|\d+)', ins)
        if m and m[2] in regs:
            t = regs[m[2]] + int(m[3], 0); regs[m[1]] = t
            s = cstr(cache, t); note = f'  ; {t:#x} "{s}"' if s else f'  ; {t:#x}'
        m = re.match(r'ldr\s+(x\d+),\s*\[(x\d+),\s*#(0x[0-9a-f]+|\d+)\]', ins)
        if m and m[2] in regs:
            t = regs[m[2]] + int(m[3], 0)
            try:
                p = struct.unpack('<Q', cache.read(t, 8))[0] & 0xfffffffffff
                s = cstr(cache, p) if p else None
                note = f'  ; [{t:#x}] -> {p:#x}' + (f' "{s}"' if s else '')
            except Exception:
                pass
        m = re.match(r'b(l)?\s+0x([0-9a-f]+)', ins)
        if m:
            t = int(m[2], 16)
            j = bisect.bisect_right(starts, t) - 1
            nm = syms[j][1] if j >= 0 and t - syms[j][0] < 0x40 else None
            if not nm:
                ti = cache.who(t)
                nm = (ti['image'].rsplit('/', 1)[-1] + f'+{ti["image_offset"]:#x}') if ti else '?'
            note = f'  ; -> {t:#x} {nm}'
        print(f'{pc:#x}: {ins}{note}')
    cache.close()


if __name__ == '__main__':
    main()
