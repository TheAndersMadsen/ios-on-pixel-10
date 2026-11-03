"""Per-object diff of two shim build dirs (out/*.o). Lines that differ only in mov/movk immediates are counted as
nonce-class (stamp nonce, UFS epoch, record nonce are per-build -D constants); anything else is printed."""
import difflib, os, re, subprocess, sys
from pathlib import Path
L = os.path.expanduser('~/.local/share/hackios-host/llvm/bin/')
def dis(p):
    out = subprocess.run([L+'llvm-objdump', '-d', '-r', '--no-show-raw-insn', '--no-leading-addr', str(p)], capture_output=True, text=True, check=True).stdout
    return [l.strip() for l in out.splitlines()[2:] if l.strip()]
def data(p):
    return subprocess.run([L+'llvm-objdump', '-s', '-j', '.rodata', '-j', '.data', '-j', '.rodata.str1.1', str(p)], capture_output=True, text=True).stdout.splitlines()[2:]
A, B = Path(sys.argv[1]), Path(sys.argv[2]); show = sys.argv[3:] 
oa = {p.name for p in A.glob('*.o')}; ob = {p.name for p in B.glob('*.o')}
print('only in A:', sorted(oa - ob)); print('only in B:', sorted(ob - oa))
for n in sorted(oa & ob):
    a, b = dis(A/n), dis(B/n)
    if a == b and data(A/n) == data(B/n): print(f'{n}: identical'); continue
    d = [x for x in difflib.unified_diff(a, b, lineterm='', n=0) if not x.startswith(('---', '+++', '@@'))]
    real = [x for x in d if not re.match(r'^[-+](mov|movk)\s', x)]
    dd = data(A/n) != data(B/n)
    print(f'{n}: {len(d)} changed text lines, {len(d) - len(real)} mov/movk-immediate only, {len(real)} other; data {"DIFFERS" if dd else "same"}')
    if n in show: print('\n'.join(real[:400]))
