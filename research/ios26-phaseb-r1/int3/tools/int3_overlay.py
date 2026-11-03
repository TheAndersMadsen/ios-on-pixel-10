#!/usr/bin/env python3
"""HOST ONLY. The int3 overlay = int2-about-r1.ovl (edbd799a; int1-r1's 52 records + the three
hkcover covers ml-en/ax-punct/ax-vopron in group 19) with obs1's two record edits applied:
  [39] hk_env -> the 11-daemon hk_logmirror rule (OBS.md 2.1)
  [50] hk_stderr_console.dylib -> hk_logmirror.dylib (OBS.md 2.1)
obs_overlay.transform() preserves every other record byte-for-byte, so the three about covers
(records 52..64) survive unchanged. Result: 65 records, 4 covers (coreui-colour + the three),
[39] mirror rule, [50] logmirror. No boot-arg change (overlay only). Needs the int3/hk-obs1
kernel's DYLD merge (hk_env_for_program) for the Preferences/SpringBoard rules.

    int3_overlay.py ABOUT_OVL LOGMIRROR_DYLIB OUT     (refuses to overwrite OUT; prints JSON)
"""
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]
def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
OBS = load('obs_overlay', 'research/ios26-phaseb-r1/live/obs/tools/obs_overlay.py')
RC = load('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
sha = lambda b: hashlib.sha256(b).hexdigest()
ABOUT_SHA = 'edbd799a3bc1651b03e3e4eb0bec0024aac69a80a663541104052543a3f795af'

def build(about_blob, lib_blob):
    if sha(about_blob) != ABOUT_SHA:
        raise ValueError(f'base is not int2-about-r1 {ABOUT_SHA[:8]}')
    result, rep = OBS.transform(about_blob, lib_blob, base_sha=sha(about_blob))
    rows = RC.decode(result)
    covers = sorted(str(r[5]) for r in rows if r[0] == ord('l') and str(r[5]).endswith('.cover'))
    if len(covers) != 4:
        raise ValueError(f'expected 4 covers, got {covers}')
    # the 13 about cover records (52..64) must be byte-identical to the about base
    abase = RC.decode(about_blob)
    assert [r[7] for r in rows[52:]] == [r[7] for r in abase[52:]], 'about covers changed'
    assert str(rows[50][5]) == '/private/var/hk/hk_logmirror.dylib'
    rep.update({'input_about_sha256': sha(about_blob), 'covers': covers, 'records': len(rows)})
    return result, rep

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('about'); p.add_argument('library'); p.add_argument('output')
    a = p.parse_args()
    result, rep = build(Path(a.about).read_bytes(), Path(a.library).read_bytes())
    with open(a.output, 'xb') as f:
        f.write(result)
    rep['output_sha256'] = sha(result); rep['output'] = a.output
    print(json.dumps(rep, indent=2))

if __name__ == '__main__':
    main()
