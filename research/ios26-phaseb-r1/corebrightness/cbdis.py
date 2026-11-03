#!/usr/bin/env python3
"""Disassemble a fixed range of an on-device dyld cache (no function-boundary guessing) and annotate:
adrp+add/ldr targets as C strings or CFStrings, bl targets through arm64e stubs to the exported name in the
target image. Host reading aid only (CoreBrightness backboardd crash, A7).

    cbdis.py CACHE START_UNSLID [LENGTH]       (default: scan from START to the next pacibsp after a ret)
"""
import bisect, re, struct, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, '/srv/dev/repos/personal/hackios/research/ios26-apps-r1/tools/m1box')
import dsc_sym as S

LLVM = Path('/home/anders/.local/share/hackios-host/llvm/bin')
MASK = 0x3ffffffff  # dyld cache v5 chained pointer: 34-bit runtime offset from the cache base
CACHE_BASE = 0x180000000
_symcache = {}


def cstr(c, a, n=160):
    try:
        b = c.read(a, n)
    except Exception:
        return None
    e = b.find(b'\0'); s = b[:e if e >= 0 else n]
    return s.decode() if len(s) >= 2 and all(32 <= x < 127 for x in s) else None


def cfstr(c, a):
    try:
        isa, flags, p, ln = struct.unpack('<QQQQ', c.read(a, 32))
    except Exception:
        return None
    if (flags >> 32) or not (0 < ln < 512):
        return None
    for q in (p & MASK, (p & MASK) + CACHE_BASE):
        s = cstr(c, q, ln + 1)
        if s and len(s) == ln:
            return '@"' + s + '"'
    return None


def name_at(c, t):
    info = c.who(t)
    if not info:
        return None
    base = t - info['image_offset']
    syms = _symcache.get(base)
    if syms is None:
        syms = _symcache[base] = S.image_symbols(c, base)
    starts = [s[0] for s in syms]
    j = bisect.bisect_right(starts, t) - 1
    img = info['image'].rsplit('/', 1)[-1]
    if j >= 0 and t == syms[j][0]:
        return f'{img}:{syms[j][1]}'
    return f'{img}+{info["image_offset"]:#x}'


def adrp_imm(w, pc):
    immlo = (w >> 29) & 3; immhi = (w >> 5) & 0x7ffff
    imm = ((immhi << 2) | immlo) << 12
    if imm & (1 << 32): imm -= 1 << 33
    return (pc & ~0xfff) + imm


def stub_target(c, t, depth=0):
    try:
        w = struct.unpack('<4I', c.read(t, 16))
    except Exception:
        return None
    # objc_msgSend selector stub: adrp x1 ; ldr x1,[x1,#off] ; adrp x17 ; add x17 ...
    if (w[0] & 0x9f00001f) == 0x90000001 and (w[1] & 0xffc003ff) == 0xf9400021:
        sref = adrp_imm(w[0], t) + ((w[1] >> 10) & 0xfff) * 8
        try:
            p = struct.unpack('<Q', c.read(sref, 8))[0]
            return 'objc_msgSend [' + (cstr(c, (p & MASK) + CACHE_BASE) or hex(p)) + ']'
        except Exception:
            return None
    # branch island: adrp x16 ; add x16,x16,#imm ; br x16
    if (w[0] & 0x9f00001f) == 0x90000010 and (w[1] & 0xffc003ff) == 0x91000210 and w[2] == 0xd61f0200:
        dst = adrp_imm(w[0], t) + ((w[1] >> 10) & 0xfff)
        return (depth < 3 and stub_target(c, dst, depth + 1)) or name_at(c, dst) or f'{dst:#x}'
    # adrp x17 ; add x17,x17,#imm ; ldr x16,[x17] ; braa x16,x17
    if (w[0] & 0x9f00001f) != 0x90000011 or (w[1] & 0xffc003ff) != 0x91000231:
        return None
    immlo = (w[0] >> 29) & 3; immhi = (w[0] >> 5) & 0x7ffff
    imm = ((immhi << 2) | immlo) << 12
    if imm & (1 << 32): imm -= 1 << 33
    got = (t & ~0xfff) + imm + ((w[1] >> 10) & 0xfff)
    try:
        p = struct.unpack('<Q', c.read(got, 8))[0]
    except Exception:
        return None
    for q in (p & MASK, (p & MASK) + CACHE_BASE):
        n = name_at(c, q)
        if n and ':' in n:
            return n
    return f'got {got:#x} -> {p:#x}'


def main():
    c = S.LP.CacheImages(sys.argv[1]); start = int(sys.argv[2], 0)
    length = int(sys.argv[3], 0) if len(sys.argv) > 3 else None
    if length is None:
        a = start + 4
        while True:
            (w,) = struct.unpack('<I', c.read(a, 4))
            if w == 0xd503237f and a != start:
                break
            a += 4
        length = a - start
    code = c.read(start, length)
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / 'f.bin'; obj = Path(td) / 'f.o'; raw.write_bytes(code)
        subprocess.run([str(LLVM / 'llvm-objcopy'), '-I', 'binary', '-O', 'elf64-littleaarch64', '--rename-section',
                        '.data=.text,code,alloc,load,readonly', str(raw), str(obj)], check=True)
        dis = subprocess.run([str(LLVM / 'llvm-objdump'), '-d', '--no-show-raw-insn', '--triple=arm64e-apple-ios',
                              '--mattr=+pauth,+v8.5a', f'--adjust-vma={start:#x}', str(obj)],
                             capture_output=True, text=True, check=True).stdout
    print(f'# {name_at(c, start)} range {start:#x}..{start + length:#x}')
    regs = {}
    for l in dis.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+(.*)$', l)
        if not m:
            continue
        pc, ins = int(m[1], 16), re.sub(r'\s*<[^>]*>', '', m[2].split('//')[0].strip())
        note = ''
        m = re.match(r'adrp\s+(x\d+),\s*0x([0-9a-f]+)', ins)
        if m: regs[m[1]] = int(m[2], 16)
        m = re.match(r'add\s+(x\d+),\s*(x\d+),\s*#(0x[0-9a-f]+|\d+)$', ins)
        if m and m[2] not in regs:
            regs.pop(m[1], None)
        if m and m[2] in regs:
            t = regs[m[2]] + int(m[3], 0); regs[m[1]] = t
            s = cfstr(c, t) or (lambda v: f'"{v}"' if v else None)(cstr(c, t))
            note = f'  ; {t:#x} {s or ""}'
        m = re.match(r'ldr\s+(x\d+),\s*\[(x\d+),\s*#(0x[0-9a-f]+|\d+)\]', ins)
        if m and m[2] in regs and m[2] != 'sp':
            t = regs[m[2]] + int(m[3], 0)
            try:
                p = struct.unpack('<Q', c.read(t, 8))[0]
                if p == 0 or (p >> 52) == 0 and (p & MASK) + CACHE_BASE == CACHE_BASE:
                    raise ValueError('null')
                q = p & MASK
                s = None
                for qq in (q, q + CACHE_BASE):
                    if qq == CACHE_BASE: break  # cache header, not a pointer target
                    s = cfstr(c, qq) or cstr(c, qq) or (name_at(c, qq) if c.who(qq) else None)
                    if s: break
                note = f'  ; [{t:#x}] {s or hex(p)}'
            except Exception:
                pass
            regs.pop(m[1], None)
        m = re.match(r'(\w+)\s+(x\d+),', ins)
        if m and m[1] not in ('adrp', 'add', 'str', 'stur', 'stp', 'strb', 'sturb', 'cbz', 'cbnz', 'tbz', 'tbnz', 'cmp'):
            regs.pop(m[2], None)  # any other write ends what we knew about the register
        m = re.match(r'b(l)?\s+0x([0-9a-f]+)$', ins)
        if m:
            t = int(m[2], 16)
            if m[1]:
                note = f'  ; -> {t:#x} ' + (stub_target(c, t) or name_at(c, t) or '?')
        print(f'{pc:#x}: {ins}{note}')


if __name__ == '__main__':
    main()
