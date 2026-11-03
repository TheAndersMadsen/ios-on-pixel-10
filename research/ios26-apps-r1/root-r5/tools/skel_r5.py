#!/usr/bin/env python3
"""r5's var.skel.tsv edit: after the /private/var/mobile/Media/Photos row add
  d 755 501 501 /private/var/mobile/Media/iTunes_Control
  d 755 501 501 /private/var/mobile/Media/iTunes_Control/iTunes
(int3 PHYSICAL: Preferences/About aborts in MusicLibrary with NSGenericException 'iTunesControlDoesNotExist
/private/var/mobile/Media/iTunes_Control does not exist'; the stock OS volume has no such directory either, it is made at
runtime on a stock phone. Mode 755 and owner mobile are INFERENCE.) Writes OUT_TAR holding private/var.skel.tsv (0:0 0644).
  skel_r5.py IN_var.skel.tsv OUT_TAR"""
import io, sys, tarfile, time
src, out = sys.argv[1:3]
lines = open(src, newline='\n').read().split('\n')
assert lines[-1] == '' and not any('iTunes_Control' in l for l in lines)
i = lines.index('d\t750\t501\t501\t/private/var/mobile/Media/Photos')
lines[i + 1:i + 1] = ['d\t755\t501\t501\t/private/var/mobile/Media/iTunes_Control',
                      'd\t755\t501\t501\t/private/var/mobile/Media/iTunes_Control/iTunes']
b = '\n'.join(lines).encode()
with tarfile.open(out, 'w', format=tarfile.PAX_FORMAT) as t:
    ti = tarfile.TarInfo('private/var.skel.tsv'); ti.size = len(b); ti.mode = 0o644; ti.mtime = int(time.time())
    t.addfile(ti, io.BytesIO(b))
print('rows', len(lines) - 1, 'sha256 of new file:', __import__('hashlib').sha256(b).hexdigest())
