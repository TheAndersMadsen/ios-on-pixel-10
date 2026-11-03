# leafRecords / nodes of the catalog and attributes B-trees and VH counters (raw, no mount)
import struct,sys,json
r={}
for img in sys.argv[1:]:
    f=open(img,'rb'); f.seek(1024); vh=f.read(512)
    bs=struct.unpack_from('>I',vh,40)[0]; o={}
    for n,off in (('catalog',272),('attributes',352),('extents',192)):
        s,c=struct.unpack_from('>II',vh,off+16)
        f.seek(s*bs); node=f.read(512)
        depth,root,leaf,first,last,nsize,maxk,total,free=struct.unpack_from('>HIIIIHHII',node,14)
        o[n]={'leafRecords':leaf,'totalNodes':total,'freeNodes':free,'depth':depth}
    o['fileCount'],o['folderCount']=struct.unpack_from('>II',vh,32)
    o['totalBlocks'],o['freeBlocks']=struct.unpack_from('>II',vh,44)
    r[img]=o
print(json.dumps(r,indent=1))
