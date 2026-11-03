# usage: census.py MOUNT OUT.tsv -- every entry: path type mode uid gid size nlink sha256/link (read-only)
import os,sys,stat,hashlib
m,out=sys.argv[1],sys.argv[2]
with open(out,'w',errors='surrogateescape') as o:
    for dp,dns,fns in os.walk(m):
        dns.sort()
        for n in sorted(dns+fns):
            fp=os.path.join(dp,n); rel=os.path.relpath(fp,m); st=os.lstat(fp)
            if stat.S_ISLNK(st.st_mode): v='l:'+os.readlink(fp)
            elif stat.S_ISREG(st.st_mode):
                h=hashlib.sha256()
                with open(fp,'rb') as f:
                    for b in iter(lambda:f.read(1<<20),b''): h.update(b)
                v=h.hexdigest()
            else: v=''
            o.write(f'{rel}\t{oct(st.st_mode)}\t{st.st_uid}\t{st.st_gid}\t{st.st_size if not stat.S_ISDIR(st.st_mode) else "-"}\t{st.st_nlink if not stat.S_ISDIR(st.st_mode) else "-"}\t{int(st.st_mtime) if not stat.S_ISDIR(st.st_mode) else "-"}\t{v}\n')
print('done',out)
