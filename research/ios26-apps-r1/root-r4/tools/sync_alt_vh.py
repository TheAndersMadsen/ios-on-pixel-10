# copy the primary HFS+ volume header to the alternate one (image end - 1024), as macOS does on unmount
import os,sys
img=sys.argv[1]; f=open(img,'r+b'); f.seek(1024); vh=f.read(512)
assert vh[:2] in (b'H+',b'HX')
bs=int.from_bytes(vh[40:44],'big'); tb=int.from_bytes(vh[44:48],'big'); assert tb*bs==os.path.getsize(img)
attr=int.from_bytes(vh[4:8],'big'); assert attr&(1<<8) and not attr&(1<<11), hex(attr)
f.seek(tb*bs-1024); f.write(vh); f.flush(); os.fsync(f.fileno()); print('alternate header = primary, attributes', hex(attr))
