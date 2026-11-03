import re, subprocess, sys
L = '/home/anders/.local/share/hackios-host/llvm/bin/llvm-objdump'
def norm(elf, f):
    out = subprocess.run([L, '-d', '--no-show-raw-insn', f'--disassemble-symbols={f}', elf], capture_output=True, text=True).stdout
    lines = []
    for l in out.splitlines():
        m = re.match(r'^\s+[0-9a-f]+:\s+(.*)$', l)
        if not m: continue
        i = re.sub(r'\s+', ' ', m.group(1)).strip()
        i = re.sub(r'0x[0-9a-f]+ <([\w.]+)(\+0x[0-9a-f]+)?>', r'<\1\2>', i)
        if i.startswith('adrp'): i = re.sub(r', 0x[0-9a-f]+.*$', ', PAGE', i)
        i = re.sub(r'(\[x\d+, )#0x[0-9a-f]+\]', r'\1#LO12]', i)
        i = re.sub(r'^(add x\d+, x\d+), #0x[0-9a-f]+$', r'\1, #LO12', i)
        lines.append(i)
    return lines
a, b = sys.argv[1], sys.argv[2]
for f in sys.argv[3:]:
    x, y = norm(a, f), norm(b, f)
    d = [(p, q) for p, q in zip(x, y) if p != q]
    print(f'{f}: {len(x)} vs {len(y)} instructions, {len(d)} differ after address/page normalisation', d[:6])
