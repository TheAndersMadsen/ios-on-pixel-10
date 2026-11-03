"""mkvariant.sh edit (r16, lane 1 diagnostic): mirror backboardd's os_log to the console (OS_ACTIVITY_DT_MODE=YES,
StandardErrorPath=/dev/console) in the launchd cache and its job plist. Base apps-logmirror-r14.img."""
import sys, plistlib, hashlib, json
from pathlib import Path
m = Path(sys.argv[1]); LABEL = 'com.apple.backboardd'
def patch(j):
    env = dict(j.get('EnvironmentVariables') or {}); env['OS_ACTIVITY_DT_MODE'] = 'YES'; j['EnvironmentVariables'] = env; j['StandardErrorPath'] = '/dev/console'
def rewrite(p, fn):
    raw = p.read_bytes(); fmt = plistlib.FMT_BINARY if raw.startswith(b'bplist') else plistlib.FMT_XML
    d = plistlib.loads(raw); fn(d); new = plistlib.dumps(d, fmt=fmt, sort_keys=False)
    with p.open('r+b') as f: f.write(new); f.truncate()
    return {'path': str(p.relative_to(m)), 'before': hashlib.sha256(raw).hexdigest(), 'after': hashlib.sha256(new).hexdigest()}
def cache(d):
    n = 0
    for k, j in d['LaunchDaemons'].items():
        if isinstance(j, dict) and j.get('Label') == LABEL: patch(j); n += 1
    assert n == 1, n
out = [rewrite(m / 'System/Library/xpc/launchd.plist', cache)]
f = m / 'System/Library/LaunchDaemons' / (LABEL + '.plist')
if f.exists(): out.append(rewrite(f, lambda j: (patch(j), j)[1]))
print(json.dumps(out, indent=1))
