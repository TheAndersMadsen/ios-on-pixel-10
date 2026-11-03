# ro-run.sh IMG exe_check.py /m PATHS : restored paths whose enclosing bundle (any depth) has a Mach-O CFBundleExecutable
import os, sys, plistlib
m, pp = sys.argv[1:3]; hit = {}
for r in open(pp).read().split():
    p = r.split('/')
    for i in range(1, len(p)):
        a = '/'.join(p[:i])
        if not a.endswith(('.app', '.appex', '.framework', '.bundle', '.xpc')): continue
        ip = os.path.join(m, a, 'Info.plist'); exe = None
        try: exe = plistlib.load(open(ip, 'rb')).get('CFBundleExecutable')
        except Exception: pass
        if exe and os.path.isfile(os.path.join(m, a, exe)): hit.setdefault(a, 0); hit[a] += 1
print('bundles with an executable that gain files:', len(hit)); [print(' ', k, v) for k, v in sorted(hit.items())]
