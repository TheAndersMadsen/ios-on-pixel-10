#!/usr/bin/env python3
"""Exercise additive composition on the actual p29 overlay, including hgltrack."""
import argparse
import hashlib
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(ROOT/'tools'))
from paths import DEFAULT_OUTPUT, DEFAULT_BASE, DEFAULT_BASE_SHA, DEFAULT_MKOVERLAY, generated, module
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--output-dir',type=Path,default=DEFAULT_OUTPUT)
ap.add_argument('--base',type=Path,default=DEFAULT_BASE)
ap.add_argument('--base-sha',default=DEFAULT_BASE_SHA)
ap.add_argument('--mkoverlay',type=Path,default=DEFAULT_MKOVERLAY)
args=ap.parse_args()
OUTPUT=generated(args.output_dir)
(OUTPUT/'artifacts').mkdir(parents=True,exist_ok=True)
(OUTPUT/'receipts').mkdir(exist_ok=True)
C=module('compose',ROOT/'tools/compose.py')
C.configure(args.mkoverlay)
base=args.base.read_bytes()
base_sha=args.base_sha
lib=(OUTPUT/'build/hsampler.dylib').read_bytes()
old=C.records(base)
assert hashlib.sha256(base).hexdigest()==base_sha
paths={}
for mode in ('off','observe','verify','fast'):
    out,receipt=C.compose(base,base_sha,lib,0xA0080081,mode)
    rows=C.records(out)
    changed=[(a,b) for a,b in zip(old,rows) if a['raw']!=b['raw']]
    assert len(changed)==1 and changed[0][0]['path']=='hk_env'
    assert len(old)==43 and rows[-1]['data']==lib and len(rows)==44
    assert rows[-1]['group']==changed[0][1]['group']==29
    env=changed[0][1]['data'].decode()
    assert '/private/var/hk/hgltrack.dylib:/private/var/hk/hsampler.dylib' in env
    assert 'SpringBoard:FEATUREFLAGS_DISABLED=' in env
    assert ('HKSAMPLER=' not in env) if mode=='off' else ('HKSAMPLER='+mode in env)
    path=OUTPUT/'artifacts'/f'sampler-{mode}-{receipt["overlay_sha256"][:12]}.ovl'
    if path.exists(): assert path.read_bytes()==out
    else: path.write_bytes(out)
    path.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n')
    paths[mode]=str(path)
    print(f'{mode}: {receipt["overlay_sha256"]} {len(out)} bytes; 42records exact/1env extended/1file added, mask0xA0080081')
for base_hash,mask in (('0'*64,0xA0080081),(base_sha,1)):
    try:C.compose(base,base_hash,lib,mask,'verify')
    except ValueError:pass
    else:raise AssertionError('invalid base/mask accepted')
combined=C.extend_env('SpringBoard+backboardd:ONE=1;DYLD_INSERT_LIBRARIES=/a.dylib,other:X=2','verify')
assert 'SpringBoard:ONE=1;DYLD_INSERT_LIBRARIES=/a.dylib' in combined
assert 'backboardd:ONE=1;DYLD_INSERT_LIBRARIES=/a.dylib:/private/var/hk/hsampler.dylib;HKSAMPLER=verify' in combined
try:C.compose(out,C.sha(out),lib,0xA0080081,'fast')
except ValueError:pass
else:raise AssertionError('duplicate sampler injection accepted')
(OUTPUT/'receipts/current-overlays.json').write_text(json.dumps(paths,indent=2)+'\n')
kernel=OUTPUT/'build/kernel_overlay'
if not kernel.exists():
    raise RuntimeError('build.py must compile the actual kernel consumer first; no skipped consumer test')
if kernel.exists():
    log=[]
    for mode,path in paths.items():
        result=subprocess.run([str(kernel),path,mode],capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
        log.append(mode+': '+result.stdout)
    # Recreate the withdrawn integration error: append a second complete rule
    # while retaining the first DYLD variable. The true kernel consumer must
    # reject the resulting effective environment in this regression fixture.
    env=[r for r in old if r['kind']=='c' and r['path']=='hk_env' and (0xA0080081&(1<<r['group']))][0]
    body=base[24:]+C.MK.pack('f',29,0o755,0,0,C.LIBRARY,lib)
    body+=C.MK.pack('c',29,0,0,0,'hk_env',C.extend_env(env['data'].decode(),'verify').encode())
    bad=C.MK.MAGIC+struct.pack('<IIQ',24+len(body),len(old)+2,C.MK.fnv1a(body))+body
    with tempfile.NamedTemporaryFile(dir=OUTPUT/'build',suffix='.ovl') as tmp:
        tmp.write(bad);tmp.flush()
        result=subprocess.run([str(kernel),tmp.name,'verify'],capture_output=True,text=True)
    assert result.returncode!=0
    log.append('PASS: append-duplicate-env regression rejected by actual kernel rule consumer\n')
    (OUTPUT/'receipts/kernel-overlay.txt').write_text(''.join(log))
    print(''.join(log),end='')
print('PASS: actual p29 composition/grammar, non-env base preservation, off gate, shared program isolation, invalid base/mask/duplicate refusal')
