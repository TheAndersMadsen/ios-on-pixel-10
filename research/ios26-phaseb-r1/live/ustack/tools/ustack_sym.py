#!/usr/bin/env python3
"""Symbolicate hk_ustack console lines (kernel hk-ustack-dbg4, boot-arg hk_ustack=) against the dyld shared cache.

    python3 -I research/ios26-phaseb-r1/live/ustack/tools/ustack_sym.py KERNEL_LOG [--cache /data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e]
        [--proc Preferences] [--pid N] [--main-only] [--root DIR] [--xnu research/ios26-release-r1/work/xnu] [--summary]

Reads `HK USTACK:` / `HK USIMG:` lines (a ramdump kernel.log, a usbcon.py --output log, or anything with them in it; other text
is ignored). For each process round it prints the header, then every printed thread: state, block_hint by name (osfmk/kern/
block_hint.h), the syscall in x16 by name (bsd/kern/syscalls.master, osfmk/kern/syscall_sw.c), then pc, lr and each fp-chain
return address as `image symbol+off`:
  - inside the shared cache (addr - slide in the cache): dsc_sym.py's nearest exported symbol of the containing image (local
    symbols are not in the cache without its .symbols file: a large +off means only the image is certain);
  - otherwise, the nearest image base at or below it from the HK USIMG list (dyld's list, non-cache images only), or main=
    from the header: `Preferences+0x1234`. With --root DIR (an extracted root), that image's own LC_SYMTAB names it.
`same:` lines are expanded to "unchanged since last round" per tid. --summary prints, per pid, the main thread's state and
top frame per round (blocked at one place vs moving). Standard library only; reads nothing but the files named.
"""
import argparse
import bisect
import importlib.util
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
DEFAULT_CACHE = '/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e'


def load_dsc_sym():
    spec = importlib.util.spec_from_file_location('dsc_sym', REPO / 'research/ios26-apps-r1/tools/m1box/dsc_sym.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


HDR = re.compile(r'HK USTACK: (?P<name>\S+)\[(?P<pid>\d+)\] r=(?P<r>\d+) t=(?P<t>[\d.]+) threads=(?P<threads>\d+) susp=(?P<susp>-?\d+)'
                 r' slide=(?P<slide>0x[0-9a-f]+) main=(?P<main>0x[0-9a-f]+) dsc=(?P<dsc>0x[0-9a-f]+) cpu\+=(?P<cpu>\d+)')
THR = re.compile(r'HK USTACK: (?P<name>\S+)\[(?P<pid>\d+)\] r=(?P<r>\d+) tid=(?P<tid>\d+) i=(?P<i>\d+) st=(?P<st>\S+)'
                 r' hint=(?P<hint>0x[0-9a-f]+) pri=(?P<pri>-?\d+) cpu\+=(?P<cpu>\d+) sw\+=(?P<sw>\d+) off=(?P<off>\d+)'
                 r' x16=(?P<x16>-?\d+) x0=(?P<x0>0x[0-9a-f]+)(?: name=(?P<tname>\S+))? pc=(?P<pc>0x[0-9a-f]+) lr=(?P<lr>0x[0-9a-f]+)'
                 r' sp=(?P<sp>0x[0-9a-f]+) fp:(?P<fp>(?: 0x[0-9a-f]+)*)')
SAME = re.compile(r'HK USTACK: (?P<name>\S+)\[(?P<pid>\d+)\] r=(?P<r>\d+) same:(?P<tids>(?: \d+)+)')
IMG = re.compile(r'HK USIMG: (?P<name>\S+)\[(?P<pid>\d+)\] n=(?P<n>\d+) (?:dyld=(?P<dyld>0x[0-9a-f]+)|(?P<base>0x[0-9a-f]+) (?P<path>\S+))')


def block_hints(xnu):
    out = {}
    p = Path(xnu) / 'osfmk/kern/block_hint.h'
    if p.exists():
        for m in re.finditer(r'kThreadWait(\w+)\s*=\s*(0x[0-9a-fA-F]+)', p.read_text()):
            out[int(m.group(2), 16)] = m.group(1)
    return out


def syscalls(xnu):
    out = {}
    p = Path(xnu) / 'bsd/kern/syscalls.master'
    if p.exists():
        for line in p.read_text(errors='replace').splitlines():
            m = re.match(r'(\d+)\s+\w+\s+\w+\s+\{\s*[^}]*?\b(\w+)\s*\(', line)
            if m and m.group(2) not in ('nosys', 'enosys'):
                out.setdefault(int(m.group(1)), m.group(2))     # first of an #if/#else pair
    p = Path(xnu) / 'osfmk/kern/syscall_sw.c'
    if p.exists():
        for line in p.read_text(errors='replace').splitlines():
            m = re.match(r'\s*/\*\s*(\d+)\s*\*/\s*MACH_TRAP\((\w+)', line)
            if m and m.group(2) != 'kern_invalid':
                out.setdefault(-int(m.group(1)), m.group(2))
    return out


class MachO:
    """Non-cache image from --root: its own symbol table (locals included)."""
    def __init__(self, data):
        magic, _, _, _, nc, size, _, _ = struct.unpack_from('<IiiIIIII', data, 0)
        if magic != 0xfeedfacf:
            raise ValueError('not a 64-bit Mach-O')
        off, text_vm, symtab = 32, 0, None
        for _ in range(nc):
            cmd, cs = struct.unpack_from('<II', data, off)
            if cmd == 0x19 and data[off + 8:off + 24].split(b'\0')[0] == b'__TEXT':
                text_vm = struct.unpack_from('<Q', data, off + 24)[0]
            elif cmd == 0x2:
                symtab = struct.unpack_from('<IIII', data, off + 8)
            off += cs
        self.syms = []
        if symtab:
            symoff, nsyms, stroff, strsize = symtab
            for k in range(nsyms):
                strx, ntype, _, _, value = struct.unpack_from('<IBBHQ', data, symoff + 16 * k)
                if ntype & 0xe0 or (ntype & 0x0e) != 0x0e or not value:
                    continue
                end = data.find(b'\0', stroff + strx)
                self.syms.append((value - text_vm, data[stroff + strx:end].decode('utf-8', 'replace')))
        self.syms.sort()
        self.starts = [s[0] for s in self.syms]

    def name(self, off):
        i = bisect.bisect_right(self.starts, off) - 1
        return (self.syms[i][1], off - self.syms[i][0]) if i >= 0 else (None, None)


class Symbolizer:
    def __init__(self, cache_path, root=None):
        self.ds = load_dsc_sym()
        self.cache = self.ds.LP.CacheImages(cache_path)
        self.memo, self.root, self.macho = {}, Path(root) if root else None, {}

    def close(self):
        self.cache.close()

    def cache_name(self, unslid):
        info = self.cache.who(unslid) if unslid > 0 else None
        if not info:
            return None
        base = unslid - info['image_offset']
        syms = self.memo.get(base)
        if syms is None:
            syms = self.memo[base] = self.ds.image_symbols(self.cache, base)
        i = bisect.bisect_right([s[0] for s in syms], unslid) - 1
        img = info['image'].rsplit('/', 1)[-1]
        if i < 0:
            return f'{img}+{info["image_offset"]:#x}'
        return f'{img} {syms[i][1]}+{unslid - syms[i][0]:#x}'

    def image_name(self, path, off):
        if self.root is None:
            return None
        if path not in self.macho:
            try:
                self.macho[path] = MachO((self.root / path.lstrip('/')).read_bytes())
            except (OSError, ValueError, struct.error):
                self.macho[path] = None
        m = self.macho[path]
        if m is None:
            return None
        sym, d = m.name(off)
        return f'{sym}+{d:#x}' if sym else None

    def name(self, addr, proc):
        slide = proc['slide']
        if slide is not None:
            n = self.cache_name(addr - slide)
            if n:
                return n
        bases = proc['images']
        i = bisect.bisect_right([b for b, _ in bases], addr) - 1
        if i >= 0 and addr - bases[i][0] < 0x40000000:
            base, path = bases[i]
            short = path.rsplit('/', 1)[-1]
            sym = self.image_name(path, addr - base)
            return f'{short}+{addr - base:#x}' + (f' {sym}' if sym else '')
        return '?'


def parse(lines, want_proc=None, want_pid=None):
    """Yields events in order: ('hdr', d), ('thr', d), ('same', d), ('img', d)."""
    for line in lines:
        for kind, rx in (('thr', THR), ('hdr', HDR), ('same', SAME), ('img', IMG)):
            m = rx.search(line)
            if m:
                d = m.groupdict()
                if (want_proc and d['name'] != want_proc) or (want_pid and int(d['pid']) != want_pid):
                    break
                yield kind, d
                break


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('log')
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--proc')
    ap.add_argument('--pid', type=int)
    ap.add_argument('--main-only', action='store_true', help='only i=0 (the first thread, the main thread)')
    ap.add_argument('--root', help='extracted iOS root: symbolize non-cache images from their own symbol tables')
    ap.add_argument('--xnu', default=str(REPO / 'research/ios26-release-r1/work/xnu'), help='for block_hint and syscall names')
    ap.add_argument('--summary', action='store_true', help='per pid: main thread state and top frames per round')
    a = ap.parse_args(argv)
    hints, calls = block_hints(a.xnu), syscalls(a.xnu)
    sym = Symbolizer(a.cache, a.root)
    print(f'cache {a.cache} uuid {sym.cache.uuid}')
    procs, summary = {}, {}
    with open(a.log, errors='replace') as f:
        for kind, d in parse(f, a.proc, a.pid):
            pid = int(d['pid'])
            p = procs.setdefault(pid, dict(name=d['name'], slide=None, main=None, images=[], last={}))
            if kind == 'img':
                if d.get('base'):
                    b = int(d['base'], 16)
                    if (b, d['path']) not in p['images']:
                        p['images'].append((b, d['path']))
                        p['images'].sort()
                continue
            if kind == 'hdr':
                p['slide'], p['main'] = int(d['slide'], 16), int(d['main'], 16)
                if p['main'] and not any(b == p['main'] for b, _ in p['images']):
                    p['images'].append((p['main'], d['name']))
                    p['images'].sort()
                if not a.summary:
                    print(f"\n== {d['name']}[{pid}] round {d['r']} t={d['t']} s  threads={d['threads']} susp={d['susp']}"
                          f" cpu+={d['cpu']} ms  slide={d['slide']} main={d['main']}")
                continue
            if kind == 'same':
                if not a.summary and not a.main_only:
                    print(f"   unchanged since the last round: tids{d['tids']}")
                continue
            tid, idx = int(d['tid']), int(d['i'])
            if a.main_only and idx != 0:
                continue
            hint = int(d['hint'], 16)
            x16 = int(d['x16'])
            frames = [int(d['pc'], 16), int(d['lr'], 16)] + [int(x, 16) for x in d['fp'].split()]
            names = [sym.name(x, p) for x in frames]
            if a.summary:
                if idx == 0:
                    top = next((n for n in names[1:] if n != '?' and 'libsystem_kernel' not in n), names[0])
                    summary.setdefault(pid, []).append((d['r'], d['st'], hints.get(hint, hex(hint)), d['cpu'], d['sw'], d['off'],
                                                        calls.get(x16, x16), names[0], top))
                continue
            print(f"  tid {tid} i={idx}{' (main)' if idx == 0 else ''}{' ' + d['tname'] if d.get('tname') else ''}: st={d['st']}"
                  f" wait={hints.get(hint, hex(hint))} pri={d['pri']} cpu+={d['cpu']} ms sw+={d['sw']} off={d['off']} ms"
                  f" x16={x16}({calls.get(x16, '?')}) x0={d['x0']}")
            for label, x, n in zip(['pc', 'lr'] + [f'#{k}' for k in range(len(frames) - 2)], frames, names):
                print(f'    {label:>3} {x:#014x}  {n}')
    if a.summary:
        for pid, rows in summary.items():
            print(f"\n== {procs[pid]['name']}[{pid}] main thread per round")
            for r, st, wait, cpu, sw, off, call, pcn, top in rows:
                print(f'  r={r:>4} st={st:<3} wait={wait:<16} cpu+={cpu:>5} sw+={sw:>5} off={off:>7} ms  {call}  pc {pcn}  <- {top}')
    sym.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
