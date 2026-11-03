"""mkvariant.sh edit (r14): mirror os_log of lsd (com.apple.lsd, com.apple.lsd.system) and usermanagerd
(com.apple.mobile.usermanagerd) to the console: OS_ACTIVITY_DT_MODE=YES and StandardErrorPath=/dev/console, in the
launchd cache (launchd_unsecure_cache=1 reads it) and the job plists. Same edit as r11g (lsd) and r11h (usermanagerd)."""
import sys, plistlib, hashlib, json
from pathlib import Path
m = Path(sys.argv[1])
LABELS = ('com.apple.lsd', 'com.apple.lsd.system', 'com.apple.mobile.usermanagerd')
def patch(job):
    assert job.get('Label') in LABELS, job.get('Label')
    env = dict(job.get('EnvironmentVariables') or {}); env['OS_ACTIVITY_DT_MODE'] = 'YES'; job['EnvironmentVariables'] = env
    job['StandardErrorPath'] = '/dev/console'
def rewrite(p, fn):
    raw = p.read_bytes(); fmt = plistlib.FMT_BINARY if raw.startswith(b'bplist') else plistlib.FMT_XML
    d = plistlib.loads(raw); fn(d); new = plistlib.dumps(d, fmt=fmt, sort_keys=False)
    with p.open('r+b') as f: f.write(new); f.truncate()
    return {'path': str(p.relative_to(m)), 'before': hashlib.sha256(raw).hexdigest(), 'after': hashlib.sha256(new).hexdigest()}
def cache(d):
    n = 0
    for k, j in d['LaunchDaemons'].items():
        if isinstance(j, dict) and j.get('Label') in LABELS: patch(j); n += 1
    assert n == 3, n
ch = [rewrite(m / 'System/Library/xpc/launchd.plist', cache)]
for l in LABELS:
    f = m / 'System/Library/LaunchDaemons' / (l + '.plist')
    if f.exists(): ch.append(rewrite(f, patch))
print(json.dumps(ch, indent=1))
