#!/usr/bin/env python3
"""Mac half of root-r4: the IPSW's /private/var/staged_system_apps -> OUT/Applications, with r3's own copy semantics
(prune_copy: data and mode only, no xattrs, no HFS compression, hard links kept; here WITHOUT prune.decide() and
WITHOUT loctable slimming, so every bundle is as Apple shipped it) and r3's own macho stage (mkroot-full.py
macho_worker: pacstrip rewrite of every Mach-O, then pacstrip.sign = codesign -f -s - keeping identifier,
entitlements and CS options, verified). Runs r3's renegade copy (build-r3/tools/renegade), unmodified.

  python3 -I stage_apps_mac.py RENEGADE_DIR IPSW_DIR OUT_DIR
Writes OUT_DIR/Applications/*.app, OUT_DIR/src-owners.tsv (lstat of the owners-on mount), OUT_DIR/macho.json,
OUT_DIR/files.tsv (relpath, type, sha256/link target, inode group). Read-only for the IPSW dmg (hdiutil -readonly)."""
import hashlib, json, os, plistlib, shutil, stat, subprocess, sys, time, unicodedata
from collections import Counter
from multiprocessing import Pool
REN, IPSW, OUT = map(os.path.abspath, sys.argv[1:4])
sys.path.insert(0, REN)
import pacstrip  # noqa: E402  r3's rewriter + signer
MAGICS = (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf')

def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)

def os_dmg():
    m = plistlib.load(open(os.path.join(IPSW, 'BuildManifest.plist'), 'rb'))['BuildIdentities'][0]['Manifest']
    p = m['OS']['Info']['Path']
    return os.path.join(IPSW, p[:-4] if p.endswith('.aea') else p)

def worker(path):            # mkroot-full.py macho_worker, macOS branch, verbatim logic
    try:
        with open(path, 'rb') as f:
            if f.read(4) not in MAGICS:
                return path, None, None
        buf = bytearray(open(path, 'rb').read())
        orig = bytes(buf)
        counts, fj = Counter(), []
        for base in pacstrip.slices(buf):
            pacstrip.process_slice(buf, base, True, False, os.path.basename(path), counts, fj)
        if bytes(buf) == orig:
            return path, 'clean', dict(counts)
        os.chmod(path, os.stat(path).st_mode | 0o200)
        with open(path, 'wb') as f:
            f.write(buf)
        old = pacstrip.sign(path)
        new = pacstrip.cs_identity(path)
        counts = dict(counts)
        counts['__ident'] = [old, new]
        return path, 'rewritten', counts
    except BaseException as e:
        return path, 'FAILED: ' + str(e)[:300], None

def main():
    assert not os.path.exists(OUT), f'{OUT} exists'
    os.makedirs(OUT)
    dmg = os_dmg()
    mnt = os.path.join(OUT, 'src-os')
    os.makedirs(mnt)
    log('attach', dmg)
    subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noverify', '-noautofsck', '-owners', 'on',
                    '-mountpoint', mnt, dmg], check=True, capture_output=True)
    try:
        src = os.path.join(mnt, 'private/var/staged_system_apps')
        dst = os.path.join(OUT, 'Applications')
        os.makedirs(dst)
        owners, inodes, n, links = [], {}, 0, 0
        for r, ds, fs in os.walk(src):
            ds.sort(); fs.sort()
            rel = os.path.relpath(r, src); rel = '' if rel == '.' else rel
            dr = os.path.join(dst, rel) if rel else dst
            os.makedirs(dr, exist_ok=True)
            st = os.lstat(r)
            if rel:
                owners.append((rel, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)))
            os.chmod(dr, stat.S_IMODE(st.st_mode) | 0o700)
            for name in list(ds) + fs:
                p = os.path.join(r, name); q = os.path.join(dr, name); cr = (rel + '/' + name) if rel else name
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    owners.append((cr, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)))
                    os.symlink(os.readlink(p), q)
                    if name in ds:
                        ds.remove(name)
                elif stat.S_ISREG(st.st_mode):
                    owners.append((cr, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)))
                    k = (st.st_dev, st.st_ino)
                    if k in inodes:
                        os.link(inodes[k], q); links += 1; continue
                    shutil.copyfile(p, q)          # data only (COPYFILE_DATA): no xattrs, no decmpfs, no ACL
                    os.chmod(q, stat.S_IMODE(st.st_mode) | 0o200)
                    inodes[k] = q; n += 1
                elif not stat.S_ISDIR(st.st_mode):
                    sys.exit(f'unexpected file type {p}')
        log(f'copied {n} files, {links} extra hard links, {len(os.listdir(dst))} bundles')
        with open(os.path.join(OUT, 'src-owners.tsv'), 'w') as f:
            for rel, u, g, m in owners:
                f.write(f'{unicodedata.normalize("NFD", rel)}\t{u}\t{g}\t{m:o}\n')
    finally:
        subprocess.run(['hdiutil', 'detach', mnt], check=False, capture_output=True)
        os.rmdir(mnt)
    # macho stage, as r3's (same worker, Pool, hard-link relink)
    inode_first, linkl, files = {}, [], []
    for r, ds, fs in os.walk(dst):
        for f in fs:
            p = os.path.join(r, f); st = os.lstat(p)
            if not stat.S_ISREG(st.st_mode) or st.st_size < 32:
                continue
            k = (st.st_dev, st.st_ino)
            if k in inode_first:
                linkl.append((inode_first[k], p)); continue
            inode_first[k] = p; files.append(p)
    log(f'{len(files)} regular files ({len(linkl)} extra hard links) to inspect')
    stats, failed, totals, rewritten, idents = Counter(), [], Counter(), set(), {}
    with Pool(8) as pool:
        for p, status, counts in pool.imap_unordered(worker, files, chunksize=16):
            if status is None:
                continue
            stats[status.split(':')[0]] += 1
            if status.startswith('FAILED'):
                failed.append((p, status))
            elif status == 'rewritten':
                rewritten.add(p)
                idents[os.path.relpath(p, dst)] = counts.pop('__ident')
                totals.update(counts)
    relinked = 0
    for first, other in linkl:
        if first in rewritten:
            os.unlink(other); os.link(first, other); relinked += 1
    bad = [k for k, (o, nw) in idents.items() if o and (not nw or o[0] != nw[0] or o[1] != nw[1])]
    log(f'macho: {dict(stats)}, {relinked} hard links re-linked; rewritten classes {dict(totals)}; identity mismatches {len(bad)}')
    # re-scan: nothing left to rewrite
    left = Counter()
    for p in files:
        with open(p, 'rb') as f:
            if f.read(4) not in MAGICS:
                continue
        buf = bytearray(open(p, 'rb').read()); c = Counter()
        for base in pacstrip.slices(buf):
            pacstrip.process_slice(buf, base, False, False, os.path.basename(p), c, [])
        left.update({k: v for k, v in c.items() if v})
    log('re-scan (dry) counts:', dict(left))
    json.dump({'os_dmg': dmg, 'stats': dict(stats), 'classes': dict(totals), 'relinked': relinked, 'failed': failed,
               'identity_mismatch': bad, 'rescan': dict(left), 'identities': idents},
              open(os.path.join(OUT, 'macho.json'), 'w'), indent=1, sort_keys=True)
    with open(os.path.join(OUT, 'files.tsv'), 'w') as f:
        ino = {}
        for r, ds, fs in os.walk(dst):
            ds.sort()
            for name in sorted(ds + fs):
                p = os.path.join(r, name); rel = os.path.relpath(p, dst); st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    f.write(f'{rel}\tl\t{os.readlink(p)}\t\n')
                elif stat.S_ISDIR(st.st_mode):
                    f.write(f'{rel}\td\t\t\n')
                else:
                    h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
                    g = ino.setdefault(st.st_ino, len(ino))
                    f.write(f'{rel}\tf\t{h}\t{g}\n')
    if failed:
        sys.exit(f'{len(failed)} Mach-O failures')
    log('done')

if __name__ == '__main__':
    main()
