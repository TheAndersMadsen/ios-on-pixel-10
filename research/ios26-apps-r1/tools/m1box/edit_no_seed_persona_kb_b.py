"""mkvariant.sh edit (r15b, one variable): no seeded persona manifest in /private/var: remove
private/var.skel/keybags/persona.kb and its line in private/var.skel.tsv (the varfs seed list), so usermanagerd --init
writes its manifest to a path that does not exist. Base apps-logmirror-r14.img. Nothing is added."""
import sys, os, plistlib, hashlib, json
from pathlib import Path
m = Path(sys.argv[1]); p = m / 'private/var.skel/keybags/persona.kb'; tsv = m / 'private/var.skel.tsv'
raw = p.read_bytes(); assert plistlib.loads(raw) == {'UsePersonaGenerationID': 1, 'UsePersonaManifestVersion': 1, 'UserPersonaDictionary': {}}
lines = tsv.read_text().split('\n'); drop = [l for l in lines if l.endswith('\t/private/var/keybags/persona.kb')]
assert drop == ['f\t600\t0\t0\t/private/var/keybags/persona.kb'], drop
before = hashlib.sha256(tsv.read_bytes()).hexdigest()
with tsv.open('r+') as f: f.write('\n'.join(l for l in lines if l not in drop)); f.truncate()
p.unlink()
print(json.dumps({'removed_file': 'private/var.skel/keybags/persona.kb', 'file_sha256': hashlib.sha256(raw).hexdigest(), 'removed_tsv_line': drop[0],
                  'tsv_before': before, 'tsv_after': hashlib.sha256(tsv.read_bytes()).hexdigest(), 'keybags_after': sorted(os.listdir(p.parent))}, indent=1))
