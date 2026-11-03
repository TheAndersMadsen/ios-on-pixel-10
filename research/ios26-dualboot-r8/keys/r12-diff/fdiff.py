"""Per-function diff of two shim.elf files: addresses normalised (adrp/adr/branch targets), symbol names kept."""
import re, subprocess, sys, os
L = os.path.expanduser('~/.local/share/hackios-host/llvm/bin/')
def funcs(p):
    out = subprocess.run([L+'llvm-objdump', '-d', '--no-show-raw-insn', '--no-leading-addr', p], capture_output=True, text=True, check=True).stdout
    f = {}; cur = None
    for l in out.splitlines():
        m = re.match(r'^[0-9a-f]+ <(.+)>:$', l) or re.match(r'^<(.+)>:$', l)
        if m: cur = m.group(1); f[cur] = []; continue
        if cur and l.strip():
            l = re.sub(r'0x[0-9a-f]+ <', '<', l)
            l = re.sub(r'<([^>+]+)\+0x[0-9a-f]+>', r'<\1+X>', l)
            l = re.sub(r'^(\s*adrp?\s+\w+,\s*)0x[0-9a-f]+', r'\1ADDR', l)
            f[cur].append(l.strip())
    return f
def sections(p):
    out = subprocess.run([L+'llvm-readelf', '-S', '-W', p], capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if re.search(r'\]\s+\.', l)]
a, b = funcs(sys.argv[1]), funcs(sys.argv[2])
only_a = sorted(set(a) - set(b)); only_b = sorted(set(b) - set(a))
diff = sorted(k for k in set(a) & set(b) if a[k] != b[k])
print('functions', len(a), len(b)); print('only in A:', only_a); print('only in B:', only_b); print('differ:', diff)
for k in diff:
    import difflib
    d = [x for x in difflib.unified_diff(a[k], b[k], lineterm='', n=0) if not x.startswith(('---', '+++', '@@'))]
    print(f'== {k}: {len(d)} changed lines'); print('\n'.join(d[:int(sys.argv[3]) if len(sys.argv) > 3 else 12]))
