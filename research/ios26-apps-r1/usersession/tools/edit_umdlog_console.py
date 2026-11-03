"""mkvariant.sh edit (usersession r19, diagnostic, one variable: logging): usermanagerd's RotatingLog files
/var/logs/usermanagerd_init.log (the --init boot task) and /var/logs/usermanagerd.log (the daemon) become varfs
symlinks to /dev/console, so the boot task's own log reaches the console. Two lines appended to
private/var.skel.tsv (the varfs seed list, which already carries one 'l' entry). Base apps-logmirror-r14.img."""
import sys, hashlib, json
from pathlib import Path
m = Path(sys.argv[1]); tsv = m / 'private/var.skel.tsv'
raw = tsv.read_bytes(); text = raw.decode()
assert 'd\t755\t0\t0\t/private/var/logs' in text.split('\n')
add = ['l\t755\t0\t0\t/private/var/logs/usermanagerd_init.log\t/dev/console',
       'l\t755\t0\t0\t/private/var/logs/usermanagerd.log\t/dev/console']
for a in add: assert a.split('\t')[4] not in text
new = text.rstrip('\n') + '\n' + '\n'.join(add) + ('\n' if text.endswith('\n') else '')
with tsv.open('r+') as f: f.write(new); f.truncate()
print(json.dumps({'tsv_before': hashlib.sha256(raw).hexdigest(), 'tsv_after': hashlib.sha256(new.encode()).hexdigest(), 'added': add}, indent=1))
