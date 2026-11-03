import struct,sys,json
f=open(sys.argv[1],'rb'); f.seek(1024); vh=f.read(512)
F='>2sHIIIIIIIIIIIIIIIIIQ'
names='sig version attributes lastMountedVersion journalInfoBlock createDate modifyDate backupDate checkedDate fileCount folderCount blockSize totalBlocks freeBlocks nextAllocation rsrcClumpSize dataClumpSize nextCatalogID writeCount encodingsBitmap'.split()
v=dict(zip(names,struct.unpack_from(F,vh,0)))
v['sig']=v['sig'].decode()
def fork(off):
    lg,clump,tb=struct.unpack_from('>QII',vh,off)
    return {'logical':lg,'clump':clump,'blocks':tb,'ext':[e for e in (struct.unpack_from('>II',vh,off+16+8*i) for i in range(8)) if e[1]]}
for n,o in (('allocation',112),('extents',192),('catalog',272),('attributes',352),('startup',432)): v[n]=fork(o)
import os
sz=os.path.getsize(sys.argv[1]); f.seek(sz-1024); alt=f.read(512)
v['alt_at_end_matches']=alt==vh; v['image_bytes']=sz
print(json.dumps(v,indent=1))
