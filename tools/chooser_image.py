#!/usr/bin/env python3
"""A2 boot chooser image: the hackios shim with TGL_CHOOSER=1 plus the stock
Android kernel as an embedded TGLLNX01 segment. HOST ONLY: no device access.

  chooser_image.py image NAME --stock-kernel truth/boot_b.img --stock-kernel-sha SHA256
                   [--ios-root ios_system] [--fdt truth/fdt.dtb]
  chooser_image.py check research/images/NAME

The boot image is the stock boot_b v4 header page with only kernel_size
changed (cmdline, os_version, signature_size as stock) and ramdisk_size 0, so ABL assembles init_boot_b, vendor
ramdisks and bootconfig as for a normal boot (the A3 discriminator). v1 has
the iOS entry disabled: choosing iOS shows "no iOS root yet" and continues to
Android. Output: research/images/NAME/{boot.img,manifest.json,SHA256SUMS,
build.log,shim.elf,arm64-symbols.txt,host-tests.txt,avb-verify.txt}."""
import argparse, hashlib, json, re, shutil, struct, subprocess, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; ROOT = X.parent
sys.path[:0] = [str(X)]
import image_tool as IT

SEG_MAGIC = b'TGLLNX01'; SEG_HDR = 64
CSUM_SEED, CSUM_MUL, M64 = 0xcbf29ce484222325, 0x100000001b3, (1 << 64) - 1
LZ4_LEGACY = b'\x02\x21\x4c\x18'
CHOOSER_FLAGS = '-DTGL_CHOOSER=1'
CHOOSER_SRC = 'chooser.c lz4.c'
WANT_SYMS = ('tgl_chooser_run', 'tgl_chooser_place', 'tgl_chooser_seg_parse', 'tgl_chooser_menu_step',
             'tgl_chooser_csum64', 'tgl_lz4_legacy_decode')
IOS_ROOTS = ('ios_system',)


def csum64(b):
    """Mirror of shim/chooser.c tgl_chooser_csum64."""
    h = CSUM_SEED
    padded = b + b'\0' * (-len(b) % 8)
    for (w,) in struct.iter_unpack('<Q', padded):
        h = ((h ^ w) * CSUM_MUL) & M64
    return h ^ len(b)


def parse_boot_v4(raw):
    if raw[:8] != b'ANDROID!': raise ValueError('not an Android boot image')
    ks, rs, osv, hs = struct.unpack_from('<IIII', raw, 8)
    hv = struct.unpack_from('<I', raw, 40)[0]
    if hv != 4: raise ValueError(f'boot header version {hv}, need 4')
    cmd = raw[44:44 + 1536]
    sig = struct.unpack_from('<I', raw, 1580)[0]
    return dict(kernel_size=ks, ramdisk_size=rs, os_version_raw=osv, header_size=hs, header_version=hv,
                cmdline=cmd.split(b'\0')[0].decode(), cmdline_raw=cmd, signature_size=sig, kernel=raw[4096:4096 + ks])


def image_header(img):
    if len(img) < 64 or img[56:60] != b'ARM\x64': raise ValueError('decoded kernel is not an arm64 Image')
    text_offset, image_size, flags = struct.unpack_from('<QQQ', img, 8)
    return dict(text_offset=text_offset, image_size=image_size, flags=flags)


def segment(lz4, image_len, image_size, flags):
    hdr = SEG_MAGIC + struct.pack('<QQQQQ', len(lz4), image_len, image_size, flags, csum64(lz4))
    hdr += struct.pack('<Q', csum64(hdr)) + b'\0' * 8
    assert len(hdr) == SEG_HDR
    return hdr + lz4 + b'\0' * (-len(lz4) % 8)


def stock_vbmeta(raw):
    """The signed vbmeta blob from a stock boot image's AVB footer (big-endian AvbFooter)."""
    f = raw[-64:]
    if f[:4] != b'AVBf': raise ValueError('stock image has no AVB footer')
    _, _, orig, off, size = struct.unpack('>IIQQQ', f[4:36])
    vb = raw[off:off + size]
    if vb[:4] != b'AVB0': raise ValueError('stock footer does not point at a vbmeta blob')
    return vb


def lz4_decode(lz4):
    with tempfile.TemporaryDirectory() as t:
        src = Path(t) / 'k.lz4'; src.write_bytes(lz4); dst = Path(t) / 'Image'
        subprocess.run(['lz4', '-d', '-q', '-f', str(src), str(dst)], check=True)
        return dst.read_bytes()


def run(cmd, log, **kw):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kw)
    log.write(f'$ {" ".join(map(str, cmd))}\n{r.stdout}\n')
    if r.returncode: IT.die(f'{cmd[0]} failed (see build.log)')
    return r.stdout


def build(a):
    out = IT.RUN / a.name
    if out.exists(): IT.die(f'{out} exists: an image is not rebuilt after handover. Use a new name')
    if a.ios_root not in IOS_ROOTS: IT.die(f'--ios-root must be one of {IOS_ROOTS}')
    stock_raw = Path(a.stock_kernel).read_bytes()
    if hashlib.sha256(stock_raw).hexdigest() != a.stock_kernel_sha: IT.die('stock boot image sha256 mismatch')
    st = parse_boot_v4(stock_raw)
    if st['kernel'][:4] != LZ4_LEGACY: IT.die('stock kernel is not an lz4 legacy stream')
    img = lz4_decode(st['kernel']); ih = image_header(img)
    if ih['text_offset'] != 0 or not ih['flags'] & 8: IT.die('stock Image must have text_offset 0 and the place-anywhere flag')
    seg = segment(st['kernel'], len(img), ih['image_size'], ih['flags'])
    out.mkdir(parents=True)
    log = (out / 'build.log').open('w')
    t = IT.scope(a.name)
    env = {**IT.os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'LLVM': str(IT.LLVM), 'HOSTCC': '/usr/bin/cc', 'TGL_UFS_HANDOFF': '0',
           'EXTRA_CFLAGS': CHOOSER_FLAGS, 'TGL_EXTRA_SRC': CHOOSER_SRC}
    run(['bash', str(t / 'build.sh')], log, env=env)
    shim = (t / 'out/Image').read_bytes()
    if struct.unpack_from('<Q', shim, 16)[0] != len(shim): IT.die('shim Image image_size != file length before the segment')
    blob = shim + b'\0' * (-len(shim) % 8)
    seg_off = len(blob); blob += seg
    blob = blob[:16] + struct.pack('<Q', len(blob)) + blob[24:]
    (out / 'kernel.bin').write_bytes(blob)
    # Host tests with the real A0 data: lz4 against the system lz4 oracle, chooser against the A0 FDT.
    with tempfile.TemporaryDirectory() as td:
        k = Path(td) / 'k.lz4'; k.write_bytes(st['kernel']); im = Path(td) / 'Image'; im.write_bytes(img)
        tests = run([str(t / 'out/lz4_test'), str(k), str(im)], log)
    tests += run([str(t / 'out/chooser_test')] + ([str(Path(a.fdt).resolve())] if a.fdt else []), log)
    for pat in (r'lz4 host test: \d+ checks, 0 failed', r'chooser host test: \d+ checks, 0 failed'):
        if not re.search(pat, tests): IT.die(f'host test line missing: {pat}')
    (out / 'host-tests.txt').write_text(tests)
    boot = out / 'boot.img'
    # The stock v4 header page verbatim, kernel_size replaced: every other field
    # (cmdline, os_version, ramdisk_size 0, signature_size) is what ABL sees on a normal boot.
    hdr = bytearray(stock_raw[:4096]); struct.pack_into('<I', hdr, 8, len(blob))
    if any(hdr[1584:]): IT.die('stock header page has bytes after the v4 header')
    boot.write_bytes(bytes(hdr) + blob + b'\0' * (-len(blob) % 4096))
    b = boot.read_bytes(); nh = parse_boot_v4(b)
    for f in ('ramdisk_size', 'os_version_raw', 'header_version', 'cmdline_raw', 'signature_size'):
        want = 0 if f == 'ramdisk_size' else st[f]
        if nh[f] != want: IT.die(f'boot header {f} {nh[f]!r} != {want!r}')
    if nh['kernel'] != blob: IT.die('kernel blob not embedded intact')
    if len(b) > IT.PARTITION - IT.FOOTER_ROOM: IT.die(f'boot image {len(b)} B does not fit the 64 MiB boot_b partition')
    if a.avb == 'stock':
        # chooser-v1-r1-t1: with the project test-key footer, KeyMint refused the /data key (-33).
        # vbmeta_b chains `boot`, so the boot footer's signed vbmeta (key, boot os_version,
        # security_patch, fingerprint) is part of the root of trust. Transplant it verbatim:
        # only its hash descriptor mismatches (tolerated on this unlocked phone, as for every
        # project image); everything KeyMint sees equals a normal boot.
        vb = stock_vbmeta(stock_raw)
        part = bytearray(IT.PARTITION); part[:len(b)] = b
        off = -(-len(b) // 4096) * 4096
        part[off:off + len(vb)] = vb
        part[-64:] = b'AVBf' + struct.pack('>IIQQQ', 1, 0, len(b), off, len(vb)) + b'\0' * 28
        boot.write_bytes(bytes(part))
        v = f'stock vbmeta transplanted: {len(vb)} B at {off}, sha256 {hashlib.sha256(vb).hexdigest()}; hash descriptor intentionally mismatches'
    else:
        avb, key = (IT.pin(IT.AVBTOOL), IT.pin(IT.AVBKEY))
        run([sys.executable, '-I', str(avb), 'add_hash_footer', '--image', str(boot), '--partition_name', 'boot', '--partition_size',
             str(IT.PARTITION), '--salt', IT.SALT, '--algorithm', 'SHA256_RSA4096', '--rollback_index', str(IT.ROLLBACK), '--key', str(key)], log)
        v = run([sys.executable, '-I', str(avb), 'verify_image', '--image', str(boot)], log)
        if 'Successfully verified sha256 hash' not in v: IT.die('AVB verify failed')
    (out / 'avb-verify.txt').write_text(v + '\n')
    shutil.copy2(t / 'out/shim.elf', out / 'shim.elf')
    nm = lambda *x: subprocess.run([str(IT.LLVM / 'llvm-nm'), *x, str(out / 'shim.elf')], capture_output=True, text=True, check=True).stdout
    if nm('-u').split(): IT.die('undefined symbols in shim')
    syms = nm(); (out / 'arm64-symbols.txt').write_text(syms)
    for s in WANT_SYMS:
        if not re.search(rf'^[0-9a-fA-F]+ [Tt] {s}$', syms, re.M): IT.die(f'shim lacks text symbol {s}')
    for s in ('tgl_dcs_guarded', 'tgl_fc_entry'):
        if re.search(rf'\s{s}$', syms, re.M): IT.die(f'{s} present in a chooser image')
    rec = dict(kind='chooser', version=1, avb_mode=a.avb, name=a.name, bootable=True, ios_entry=False, ios_root=a.ios_root,
               image=IT.sha(boot), image_bytes=boot.stat().st_size, kernel_blob=IT.sha(out / 'kernel.bin'), kernel_blob_bytes=len(blob),
               shim_bytes=len(shim), segment_offset=seg_off, segment_bytes=len(seg),
               stock=dict(boot_sha256=a.stock_kernel_sha, lz4_sha256=hashlib.sha256(st['kernel']).hexdigest(), lz4_bytes=len(st['kernel']),
                          image_sha256=hashlib.sha256(img).hexdigest(), image_len=len(img), image_size=ih['image_size'],
                          flags=hex(ih['flags']), csum64=hex(csum64(st['kernel'])), cmdline=st['cmdline'], os_version_raw=st['os_version_raw']),
               header=dict(version=4, ramdisk_size=0, cmdline=st['cmdline']), cflags=CHOOSER_FLAGS, extra_src=CHOOSER_SRC,
               stamp_nonce=(t / 'out/stamp-nonce.txt').read_text().strip(), keys='off (no pad read in v1)',
               tests=[l for l in tests.splitlines() if 'host test' in l or 'placement' in l],
               avb=v.strip().splitlines()[-1], shim_copy=IT.tree(IT.SHIM),
               tools={n: IT.sha(X / n) for n in ('chooser_image.py', 'image_tool.py')})
    (out / 'manifest.json').write_text(json.dumps(rec, indent=1, sort_keys=True) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{IT.sha(out / f)}  {f}\n' for f in ('boot.img', 'kernel.bin', 'manifest.json', 'shim.elf')))
    print(a.name, 'chooser v1', rec['image'], 'bytes', rec['image_bytes'], 'kernel blob', len(blob))
    return rec


def check(d):
    d = Path(d); m = json.loads((d / 'manifest.json').read_text())
    if m.get('kind') != 'chooser': sys.exit('not a chooser manifest')
    if IT.sha(d / 'boot.img') != m['image'] or IT.sha(d / 'kernel.bin') != m['kernel_blob']: sys.exit('MISMATCH image or kernel blob')
    b = (d / 'boot.img').read_bytes(); h = parse_boot_v4(b)
    if h['ramdisk_size'] != 0 or h['cmdline'] != m['header']['cmdline']: sys.exit('boot header differs from manifest')
    blob = h['kernel']
    if struct.unpack_from('<Q', blob, 16)[0] != len(blob): sys.exit('image_size does not cover the segment')
    seg = blob[m['segment_offset']:]
    comp, ilen, isz, flags, cs = struct.unpack_from('<QQQQQ', seg, 8)
    if seg[:8] != SEG_MAGIC or struct.unpack_from('<Q', seg, 48)[0] != csum64(seg[:48]): sys.exit('segment header invalid')
    lz4 = seg[SEG_HDR:SEG_HDR + comp]
    if hashlib.sha256(lz4).hexdigest() != m['stock']['lz4_sha256'] or csum64(lz4) != cs: sys.exit('stock kernel bytes differ')
    if ilen != m['stock']['image_len'] or isz != m['stock']['image_size']: sys.exit('segment sizes differ')
    if len(b) > IT.PARTITION: sys.exit('image larger than the boot partition')
    if m.get('avb_mode') == 'stock':
        f = b[-64:]; _, _, orig, off, size = struct.unpack('>IIQQQ', f[4:36])
        if f[:4] != b'AVBf' or b[off:off + size][:4] != b'AVB0' or 'sha256 ' + hashlib.sha256(b[off:off + size]).hexdigest() not in (d / 'avb-verify.txt').read_text():
            sys.exit('transplanted vbmeta differs from the record')
    print('OK', m['name'], 'chooser v1', m['image'])


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('image'); i.add_argument('name'); i.add_argument('--stock-kernel', required=True)
    i.add_argument('--stock-kernel-sha', required=True); i.add_argument('--ios-root', default='ios_system')
    i.add_argument('--avb', choices=('stock', 'test'), default='stock', help='stock: transplant the stock boot vbmeta (KeyMint sees a normal boot); test: project test-key footer (r1)')
    i.add_argument('--fdt', help='A0 /sys/firmware/fdt dump: placement host test on real data')
    i.add_argument('--chooser', action='store_true', help='accepted for the image_tool.py spelling')
    c = sub.add_parser('check'); c.add_argument('dir')
    a = ap.parse_args()
    build(a) if a.cmd == 'image' else check(a.dir)
