"""mkvariant.sh edit (B2 QEMU diagnostic, one variable: logging): mirror bluetoothd's and BlueTool's os_log to the console
(OS_ACTIVITY_DT_MODE=YES, StandardErrorPath=/dev/console) in the launchd cache and their job plists. Same method as
research/ios26-apps-r1/tools/m1box/edit_logmirror_backboardd.py. Base apps-logmirror-r14.img. QEMU only."""
import sys, plistlib, hashlib, json
from pathlib import Path
m = Path(sys.argv[1]); LABELS = ('com.apple.bluetoothd', 'com.apple.BlueTool')
def patch(j):
    env = dict(j.get('EnvironmentVariables') or {}); env['OS_ACTIVITY_DT_MODE'] = 'YES'; j['EnvironmentVariables'] = env; j['StandardErrorPath'] = '/dev/console'
def rewrite(p, fn):
    raw = p.read_bytes(); fmt = plistlib.FMT_BINARY if raw.startswith(b'bplist') else plistlib.FMT_XML
    d = plistlib.loads(raw); fn(d); new = plistlib.dumps(d, fmt=fmt, sort_keys=False)
    with p.open('r+b') as f: f.write(new); f.truncate()
    return {'path': str(p.relative_to(m)), 'before': hashlib.sha256(raw).hexdigest(), 'after': hashlib.sha256(new).hexdigest()}
def cache(d):
    for label in LABELS:
        n = 0
        for k, j in d['LaunchDaemons'].items():
            if isinstance(j, dict) and j.get('Label') == label: patch(j); n += 1
        assert n == 1, (label, n)
out = [rewrite(m / 'System/Library/xpc/launchd.plist', cache)]
for label in LABELS:
    f = m / 'System/Library/LaunchDaemons' / (label + '.plist')
    if f.exists(): out.append(rewrite(f, lambda j: (patch(j), j)[1]))
print(json.dumps(out, indent=1))
