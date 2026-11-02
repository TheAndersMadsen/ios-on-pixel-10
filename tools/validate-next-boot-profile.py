#!/usr/bin/env python3
"""Validate an additive pinned root/command-line profile before any build writes."""
import argparse, hashlib, json, re
from pathlib import Path

def load_profile(path, mach):
    d = json.loads(Path(path).read_text())
    keys = {'schema_version','root_path','root_size_bytes','root_sha256','tag',
            'mem_size','cmdline','mach_sha256'}
    if not isinstance(d,dict) or set(d) not in (keys,keys|{'adt_path','adt_sha256'}) or d['schema_version']!=1:
        raise ValueError('invalid profile schema')
    for k in ('root_path','root_sha256','tag','mem_size','cmdline','mach_sha256'):
        if not isinstance(d[k],str) or not d[k] or any(c in d[k] for c in '\r\n\0'):
            raise ValueError('invalid profile field '+k)
    for k in ('root_sha256','mach_sha256'):
        if not re.fullmatch('[0-9a-f]{64}',d[k]): raise ValueError('invalid SHA256 '+k)
    if not re.fullmatch('[A-Za-z0-9._-]{1,80}',d['tag']): raise ValueError('invalid tag')
    if type(d['root_size_bytes']) is not int or d['root_size_bytes']<=0:
        raise ValueError('invalid root size')
    mem = int(d['mem_size'],0)
    if not 0<mem<=0x180000000 or mem%0x4000: raise ValueError('invalid memory window')
    if len(d['cmdline'].encode())>=1024: raise ValueError('command line exceeds payload field')
    root=Path(d['root_path'])
    if not root.is_absolute() or not root.is_file(): raise ValueError('root must be an absolute regular file')
    b=root.read_bytes()
    if len(b)!=d['root_size_bytes'] or hashlib.sha256(b).hexdigest()!=d['root_sha256']:
        raise ValueError('root pin mismatch')
    if hashlib.sha256(Path(mach).read_bytes()).hexdigest()!=d['mach_sha256']:
        raise ValueError('kernel pin mismatch')
    adt_path = ''
    if 'adt_path' in d:
        adt_path = d['adt_path']
        if not isinstance(adt_path,str) or any(c in adt_path for c in '\r\n\0') or not Path(adt_path).is_absolute():
            raise ValueError('invalid ADT path')
        if not isinstance(d['adt_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',d['adt_sha256']):
            raise ValueError('invalid ADT hash')
        if hashlib.sha256(Path(adt_path).read_bytes()).hexdigest()!=d['adt_sha256']:
            raise ValueError('ADT pin mismatch')
    return [str(root),d['tag'],str(len(b))+':'+d['root_sha256'],hex(mem),d['cmdline'],adt_path,'VALIDATED']

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('profile');p.add_argument('mach');a=p.parse_args()
    try: lines=load_profile(a.profile,a.mach)
    except (ValueError,OSError,KeyError,TypeError) as e: p.exit(2,str(e)+'\n')
    print('\n'.join(lines))
if __name__=='__main__':main()
