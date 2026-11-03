#!/usr/bin/env python3
"""Chooser with the iOS branch: ONE boot image whose menu picks stock Android or iOS. HOST ONLY: no device access.

  chooser_ios_image.py image NAME --ios-image research/images/IOS --stock-kernel truth/boot_b.img --stock-kernel-sha SHA
                       [--fdt truth/fdt.dtb] [--keys] [--default-ios]
  chooser_ios_image.py image test-NAME --payload payload-usb.bin ...   host check only: bootable=false
  chooser_ios_image.py check research/images/NAME
  chooser_ios_image.py budget --payload P --stock-kernel K [--shim-bytes N]

Kernel blob (the boot image's kernel, an arm64 Image that ABL loads as is):
  [shim Image, padded to _end] ["TEGUPLD1" u64 n] [payload-usb.bin, n B, from a checked image_tool dir]
  [pad to 8] [TGLLNX01 segment: stock boot_b lz4 kernel] ; image_size at +16 covers all of it.
The boot image is the stock boot_b v4 header with only kernel_size changed and ramdisk_size 0, and the stock
vbmeta transplanted (chooser_image.py's A3/r3 contract), so the Android branch boots exactly as chooser-v1-r11.
The shim is built with the iOS image's own cflags/sources (the direct iOS path after the menu is that image's
shim) plus TGL_CHOOSER_IOS and the r11 chooser gates; tgl_dcs.c is built twice (shim/tgl_dcs_menu.c).
--default-ios: the countdown ends on iOS (attended test of the iOS branch before keys); never installable.
research/ios26-dualboot-r8/chooser-ios/DESIGN.md."""
import argparse, hashlib, json, os, re, shutil, struct, subprocess, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; ROOT = X.parent
sys.path[:0] = [str(X)]
import image_tool as IT
import chooser_image as CI

ENV_MAGIC = b'TEGUPLD1'
LOAD_PA = 0x80000000          # where ABL put the chooser kernel blob (chooser_test.c, r1 stamps)
INITRD_PA = 0x86000000        # A0 FDT linux,initrd-start for a normal boot (chooser_test.c)
BLOB_LIMIT = INITRD_PA - LOAD_PA   # inference: the blob must end below ABL's ramdisk (96 MiB)
PROVEN_BLOB = 28 * 1024 * 1024     # largest kernel blob ABL has loaded for us: the A7 iOS image (shim + 25 MB payload), rounded down
CHOOSER_IOS_FLAGS = '-DTGL_CHOOSER=1 -DTGL_CHOOSER_IOS=1 -DTGL_CHOOSER_MMU=1 -DTGL_CHOOSER_UI=1 -DTGL_CHOOSER_DISPLAY=1'
CHOOSER_IOS_SRC = 'chooser_ios.c lz4.c el2_mmu.c menu_ui.c tgl_dcs_menu.c'
WANT_T = ('tgl_chooser_run', 'tgl_chooser_ios_admit', 'tgl_chooser_ios_layout', 'tgl_chooser_ios_action', 'tgl_chooser_seg_parse',
          'tgl_chooser_menu_step', 'tgl_chooser_place', 'tgl_chooser_csum64', 'tgl_lz4_legacy_decode', 'tgl_el2_build', 'tgl_el2_mmu_on',
          'tgl_menu_draw', 'tgl_menu_draw_band', 'tgl_dcsm_guarded', 'tgl_dcsm_present', 'tgl_dcsm_release', 'tgl_dcs_guarded', 'tgl_dcs_run',
          'loader_boot', 'tegu_el_drop_and_jump', 'tgl_ufsh_power_mode', 'tgl_ufs_link_relink', 'tgl_all_mark', 'shim_main')
NOT_PRESENT = ('tgl_dcs_release', 'tgl_dcs_present', 'tgl_dcsm_handoff')  # the iOS instance must stay the HANDOFF build
QUIESCE_MARKS = ('#0xef9, lsl #16', '#0x107c', '#0xee8, lsl #16', '#-0xe001', '#0xfff1, lsl #16')  # chooser_image.py
# image_tool's iOS shim gates (DPU on): the HANDOFF display instance and the direct iOS path.
IOS_NEEDS = ('-DTGL_ALL_DCS=1', '-DTGL_FRAME_RUNG=3', '-DTGL_DCS_HANDOFF=1')


def align8(n): return n + (-n % 8)


def layout(blob, end_off):
    """Python mirror of tgl_chooser_ios_layout: (payload_off, n, seg_off) or raise ValueError."""
    if end_off % 8: raise ValueError('_end not 8-byte aligned')
    isz = struct.unpack_from('<Q', blob, 16)[0]
    if isz != len(blob): raise ValueError(f'image_size {isz} != blob {len(blob)}')
    if end_off > isz or isz - end_off < 16: raise ValueError('no room for an XNU envelope')
    if blob[end_off:end_off + 8] != ENV_MAGIC: raise ValueError('no XNU envelope after _end')
    n = struct.unpack_from('<Q', blob, end_off + 8)[0]
    if not n or n > isz - end_off - 16: raise ValueError('XNU envelope past image_size')
    seg = align8(end_off + 16 + n)
    if seg > isz or isz - seg < CI.SEG_HDR: raise ValueError('no Android segment after the XNU envelope')
    return end_off + 16, n, seg


def assemble(shim_with_env, end_off, payload, seg):
    """Append the segment to build.sh's Image (which already holds the envelope) and raise image_size."""
    if struct.unpack_from('<Q', shim_with_env, 16)[0] != len(shim_with_env): raise ValueError('Image image_size != its length')
    if shim_with_env[end_off:end_off + 8] != ENV_MAGIC or struct.unpack_from('<Q', shim_with_env, end_off + 8)[0] != len(payload) \
            or shim_with_env[end_off + 16:end_off + 16 + len(payload)] != payload or len(shim_with_env) != end_off + 16 + len(payload):
        raise ValueError('envelope at _end does not hold the payload exactly')
    blob = shim_with_env + b'\0' * (-len(shim_with_env) % 8)
    seg_off = len(blob); blob += seg
    blob = blob[:16] + struct.pack('<Q', len(blob)) + blob[24:]
    if layout(blob, end_off)[2] != seg_off: raise ValueError('segment offset differs from the shim rule')
    return blob, seg_off


def budget(shim_bytes, payload_bytes, lz4_bytes, vbmeta_bytes=4096):
    """Rows for the size budget: the 64 MiB boot partition, the AVB footer room, ABL's kernel load gap."""
    seg_bytes = CI.SEG_HDR + align8(lz4_bytes)
    blob = align8(shim_bytes + 16 + payload_bytes) + seg_bytes
    image = 4096 + blob + (-blob % 4096)
    return dict(shim=shim_bytes, envelope=16 + payload_bytes, segment=seg_bytes, blob=blob, boot_image=image,
                partition=IT.PARTITION, image_limit=IT.PARTITION - IT.FOOTER_ROOM, image_margin=IT.PARTITION - IT.FOOTER_ROOM - image - vbmeta_bytes,
                blob_limit=BLOB_LIMIT, blob_margin=BLOB_LIMIT - blob, blob_over_proven=blob - PROVEN_BLOB)


def text_identity(llvm, shim_dir, ios_cflags):
    """Compile tgl_dcs.c three ways and compare .text/.rodata: the renamed menu instance must equal an r11-gated build,
    and the iOS instance under the chooser gates must equal the iOS image's build. Fixed nonce values on all sides."""
    base = ['-target', 'aarch64-unknown-none-elf', '-O2', '-ffreestanding', '-nostdlib', '-fno-pic', '-mgeneral-regs-only', '-mstrict-align',
            '-fno-stack-protector', '-fno-jump-tables', '-w', '-DTGL_STAMP_NONCE=0x1234ULL', '-DTGL_UFS_EPOCH=1ULL', '-DTGL_UFS_RECORD_NONCE={0}',
            '-DTGL_UFS_ROUTE=1', '-DTGL_UFS_POST_LINK=1', '-DTGL_UFS_HANDOFF=1', '-DTGL_STAMP_UFS_FOCUS=1']
    ios = ios_cflags.split()
    r11 = '-DTGL_CHOOSER=1 -DTGL_CHOOSER_MMU=1 -DTGL_CHOOSER_UI=1 -DTGL_CHOOSER_DISPLAY=1 -DTGL_DCS_MENU=1 -DTGL_FRAME_RUNG=3 -DTGL_DCS_QUIESCE=1'.split()
    both = ios + CHOOSER_IOS_FLAGS.split()
    out = {}
    with tempfile.TemporaryDirectory() as t:
        def obj(name, src, flags):
            o = Path(t) / f'{name}.o'
            subprocess.run([str(llvm / 'clang'), *base, *flags, '-c', str(shim_dir / src), '-o', str(o)], check=True)
            h = {}
            for sec in ('.text', '.rodata'):
                b = Path(t) / f'{name}{sec}'
                subprocess.run([str(llvm / 'llvm-objcopy'), '-O', 'binary', '-j', sec, str(o), str(b)], check=True)
                h[sec] = hashlib.sha256(b.read_bytes()).hexdigest()
            return h
        out['menu_r11'] = obj('r11', 'tgl_dcs.c', r11)
        out['menu_instance'] = obj('menu', 'tgl_dcs_menu.c', both)
        out['ios_alone'] = obj('ios', 'tgl_dcs.c', ios)
        out['ios_instance'] = obj('iosc', 'tgl_dcs.c', both)
    out['menu_equal'] = out['menu_r11'] == out['menu_instance']
    out['ios_equal'] = out['ios_alone'] == out['ios_instance']
    return out


def ios_source(a):
    """(payload bytes, record, iOS cflags, iOS extra_src, bootable) from a checked image_tool dir, or a raw test payload."""
    if a.ios_image:
        d = Path(a.ios_image); m = json.loads((d / 'manifest.json').read_text())
        for f, k in (('boot.img', 'image'), ('payload-usb.bin', 'payload'), ('laguna.adt', 'adt')):
            if IT.sha(d / f) != m[k]: IT.die(f'iOS image {d}: {f} differs from its manifest')
        payload = (d / 'payload-usb.bin').read_bytes()
        if IT.contract_check(d / 'payload-usb.bin') != m['plan']: IT.die('iOS payload plan differs from its manifest')
        if not m.get('bootable'): IT.die(f'iOS image {m["name"]} is not bootable: use test-* with --payload for host checks')
        if not m.get('phone_root'): IT.die('iOS image is not a --phone-root image')
        rec = dict(name=m['name'], dir=str(d.resolve()), image=m['image'], payload=m['payload'], payload_bytes=len(payload), mach=m['mach'],
                   cmdline=m['cmdline'], bootcpu=m.get('bootcpu'), cpus=m.get('cpus', 1), window_base=m.get('window_base'))
        return payload, rec, m['cflags'], m['extra_src'], True
    if not a.name.startswith('test-'): IT.die('--payload builds host-check images only: name them test-*')
    p = Path(a.payload); payload = p.read_bytes(); plan = IT.contract_check(p)
    cflags = IT.SHIM_FLAGS + ' ' + IT.DPU_FLAGS + (' ' + IT.FC_FLAGS if a.bootcpu else '')
    src = 'tgl_all.c tgl_dcs.c' + (' ' + IT.FC_SRC if a.bootcpu else '')
    rec = dict(name=None, dir=None, payload=IT.sha(p), payload_bytes=len(payload), plan=plan, path=str(p.resolve()), bootcpu=a.bootcpu)
    return payload, rec, cflags, src, False


def build(a):
    out = IT.RUN / a.name
    if out.exists(): IT.die(f'{out} exists: an image is not rebuilt after handover. Use a new name')
    if bool(a.ios_image) == bool(a.payload): IT.die('give exactly one of --ios-image and --payload')
    payload, ios, ios_cflags, ios_src, ios_bootable = ios_source(a)
    for f in IOS_NEEDS:
        if f not in ios_cflags.split(): IT.die(f'iOS shim lacks {f}: the iOS path needs the DPU handoff build')
    if 'tgl_dcs.c' not in ios_src.split(): IT.die('iOS shim sources lack tgl_dcs.c')
    stock_raw = Path(a.stock_kernel).read_bytes()
    if hashlib.sha256(stock_raw).hexdigest() != a.stock_kernel_sha: IT.die('stock boot image sha256 mismatch')
    st = CI.parse_boot_v4(stock_raw)
    if st['kernel'][:4] != CI.LZ4_LEGACY: IT.die('stock kernel is not an lz4 legacy stream')
    img = CI.lz4_decode(st['kernel']); ih = CI.image_header(img)
    if ih['text_offset'] != 0 or not ih['flags'] & 8: IT.die('stock Image must have text_offset 0 and the place-anywhere flag')
    seg = CI.segment(st['kernel'], len(img), ih['image_size'], ih['flags'])
    vb = CI.stock_vbmeta(stock_raw)
    plan = budget(3 << 20, len(payload), len(st['kernel']), len(vb))
    if plan['image_margin'] < 0 or plan['blob_margin'] < 0: IT.die(f'size budget fails before building: {plan}')

    out.mkdir(parents=True)
    log = (out / 'build.log').open('w')
    t = IT.scope(a.name)
    cflags = ios_cflags + ' ' + CHOOSER_IOS_FLAGS + (' -DTGL_CHOOSER_IOS_DEFAULT=1' if a.default_ios else '') + (' -DTGL_KEYS_POLL=1' if a.keys else '')
    src = ios_src + ' ' + CHOOSER_IOS_SRC + (' keys_laguna.c' if a.keys else '')
    llvm = Path(os.environ.get('LLVM', str(IT.LLVM)))
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'LLVM': str(llvm), 'HOSTCC': os.environ.get('HOSTCC', '/usr/bin/cc'), 'TGL_UFS_HANDOFF': '1',
           'TGL_TOOLCHAIN': 'llvm', 'EXTRA_CFLAGS': cflags, 'TGL_EXTRA_SRC': src}
    pl_file = out / 'payload-usb.bin'; pl_file.write_bytes(payload)
    CI.run(['bash', str(t / 'build.sh'), str(pl_file)], log, env=env)
    shim = (t / 'out/Image').read_bytes()
    nm = lambda *x: subprocess.run([str(llvm / 'llvm-nm'), *x, str(t / 'out/shim.elf')], capture_output=True, text=True, check=True).stdout
    syms = nm()
    m_end = re.search(r'^([0-9a-fA-F]+) [A-Za-z] _end$', syms, re.M); m_head = re.search(r'^([0-9a-fA-F]+) [A-Za-z] _head$', syms, re.M)
    if not m_end or not m_head or int(m_head.group(1), 16) != 0: IT.die('shim _head/_end symbols missing')
    end_off = int(m_end.group(1), 16)
    try: blob, seg_off = assemble(shim, end_off, payload, seg)
    except ValueError as e: IT.die(str(e))
    (out / 'kernel.bin').write_bytes(blob)

    # Host tests on real data: build.sh already ran chooser_test, lz4, el2 mmu, menu preview and the UFS/stage suites.
    tests = (t / 'out').joinpath('chooser_ios_test')
    CI.run([env['HOSTCC'], '-O1', '-Wall', '-Wextra', '-DTGL_CHOOSER_HOST', '-o', str(tests), 'chooser_ios.c', 'fdt.c', 'chooser_ios_test.c'], log, cwd=t)
    targs = [str(Path(a.fdt).resolve()), str(pl_file), str(len(st['kernel'])), str(end_off)] if a.fdt else []
    test_out = CI.run([str(tests), *targs], log)
    with tempfile.TemporaryDirectory() as td:
        k = Path(td) / 'k.lz4'; k.write_bytes(st['kernel']); im = Path(td) / 'Image'; im.write_bytes(img)
        test_out += CI.run([str(t / 'out/lz4_test'), str(k), str(im)], log)
    test_out += CI.run([str(t / 'out/chooser_test')] + ([str(Path(a.fdt).resolve())] if a.fdt else []), log)
    test_out += CI.run([sys.executable, '-I', str(t / 'test_dcs_quiesce.py')], log)
    test_out += CI.run([sys.executable, '-I', str(X / 'test_chooser_ios_image.py')], log)
    log.flush(); blog = (out / 'build.log').read_text()
    for pat in (r'chooser-ios host test: \d+ checks, 0 failed', r'lz4 host test: \d+ checks, 0 failed', r'chooser host test: \d+ checks, 0 failed',
                r'ufs route host test: \d+ checks, 0 failed', r'all-stage host test: \d+ checks, 0 failed', r'el2 mmu host test: \d+ checks, 0 failed'):
        if not re.search(pat, test_out + blog): IT.die(f'host test line missing: {pat}')
    if a.fdt and 'A0 admit: ' not in test_out: IT.die('real-data admission test did not run')
    (out / 'host-tests.txt').write_text(test_out)

    # ARM64 linked-image evidence: symbols, the hook, the quiesce in the menu release only, and source-level gate isolation.
    shutil.copy2(t / 'out/shim.elf', out / 'shim.elf'); (out / 'arm64-symbols.txt').write_text(syms)
    if nm('-u').split(): IT.die('undefined symbols in shim')
    for s in WANT_T + (('tgl_fc_entry', 'tgl_fastcore_handoff') if '-DTGL_FASTCORE=1' in ios_cflags.split() else ()) + (('keys_poll', 'keys_init') if a.keys else ()):
        if not re.search(rf'^[0-9a-fA-F]+ [Tt] {s}$', syms, re.M): IT.die(f'shim lacks text symbol {s}')
    if not re.search(r'^[0-9a-fA-F]+ [Rr] tgl_chooser_picked_ios$', syms, re.M): IT.die('handback sentinel missing')
    for s in NOT_PRESENT + (() if a.keys else ('keys_poll',)):
        if re.search(rf'\s{s}$', syms, re.M): IT.die(f'{s} present: wrong display instance or keys gate')
    objdump = lambda sym: subprocess.run([str(llvm / 'llvm-objdump'), '-d', '-r', '--no-show-raw-insn', f'--disassemble-symbols={sym}', str(out / 'shim.elf')],
                                         capture_output=True, text=True, check=True).stdout
    rel = objdump('tgl_dcsm_release'); (out / 'release-disasm.txt').write_text(rel)
    miss = [mk for mk in QUIESCE_MARKS if mk not in rel]
    if miss: IT.die(f'tgl_dcsm_release lacks the quiesce constants {miss}')
    if '#0xef9, lsl #16' in objdump('tgl_dcs_run'): IT.die('the iOS display instance touches GPCSR (quiesce leaked into the HANDOFF build)')
    sm = objdump('shim_main')
    if not re.search(r'bl\s+0x[0-9a-f]+ <tgl_chooser_run>', sm): IT.die('shim_main does not call tgl_chooser_run')
    ident = text_identity(llvm, t, ios_cflags)
    if not ident['menu_equal']: IT.die('menu display instance differs from the r11-gated tgl_dcs.c build')
    if not ident['ios_equal']: IT.die('iOS display instance changes under the chooser gates')

    boot = out / 'boot.img'
    hdr = bytearray(stock_raw[:4096]); struct.pack_into('<I', hdr, 8, len(blob))
    if any(hdr[1584:]): IT.die('stock header page has bytes after the v4 header')
    b = bytes(hdr) + blob + b'\0' * (-len(blob) % 4096)
    nh = CI.parse_boot_v4(b)
    for f in ('ramdisk_size', 'os_version_raw', 'header_version', 'cmdline_raw', 'signature_size'):
        want = 0 if f == 'ramdisk_size' else st[f]
        if nh[f] != want: IT.die(f'boot header {f} {nh[f]!r} != {want!r}')
    if nh['kernel'] != blob: IT.die('kernel blob not embedded intact')
    part = bytearray(IT.PARTITION); part[:len(b)] = b
    off = -(-len(b) // 4096) * 4096
    if off + len(vb) > IT.PARTITION - 64 or len(b) > IT.PARTITION - IT.FOOTER_ROOM: IT.die('boot image + vbmeta do not fit the 64 MiB boot partition')
    part[off:off + len(vb)] = vb
    part[-64:] = b'AVBf' + struct.pack('>IIQQQ', 1, 0, len(b), off, len(vb)) + b'\0' * 28
    boot.write_bytes(bytes(part))
    v = f'stock vbmeta transplanted: {len(vb)} B at {off}, sha256 {hashlib.sha256(vb).hexdigest()}; hash descriptor intentionally mismatches'
    (out / 'avb-verify.txt').write_text(v + '\n')

    real = budget(len(shim) - 16 - len(payload), len(payload), len(st['kernel']), len(vb))
    bootable = ios_bootable and not a.name.startswith('test-')
    rec = dict(kind='chooser-ios', version=1, name=a.name, bootable=bootable, installable=bootable and not a.default_ios and bool(a.keys),
               default_entry='ios' if a.default_ios else 'android', keys_read=bool(a.keys), ios=ios,
               image=IT.sha(boot), image_bytes=boot.stat().st_size, kernel_blob=IT.sha(out / 'kernel.bin'), kernel_blob_bytes=len(blob),
               end_off=end_off, payload_off=end_off + 16, payload_bytes=len(payload), payload_sha256=IT.sha(pl_file), segment_offset=seg_off, segment_bytes=len(seg),
               budget=real, text_identity=ident, avb_mode='stock', avb=v,
               stock=dict(boot_sha256=a.stock_kernel_sha, lz4_sha256=hashlib.sha256(st['kernel']).hexdigest(), lz4_bytes=len(st['kernel']),
                          image_sha256=hashlib.sha256(img).hexdigest(), image_len=len(img), image_size=ih['image_size'], flags=hex(ih['flags']),
                          csum64=hex(CI.csum64(st['kernel'])), cmdline=st['cmdline'], os_version_raw=st['os_version_raw']),
               header=dict(version=4, ramdisk_size=0, cmdline=st['cmdline']), cflags=cflags, extra_src=src,
               compiler=subprocess.run([str(llvm / 'clang'), '--version'], capture_output=True, text=True).stdout.splitlines()[0],
               linker=subprocess.run([str(llvm / 'ld.lld'), '--version'], capture_output=True, text=True).stdout.splitlines()[0],
               stamp_nonce=(t / 'out/stamp-nonce.txt').read_text().strip(),
               tests=[l for l in test_out.splitlines() if 'host test' in l or 'A0 ' in l or 'placement' in l],
               shim_copy=IT.tree(IT.SHIM), tools={n: IT.sha(X / n) for n in ('chooser_ios_image.py', 'chooser_image.py', 'image_tool.py')})
    log.close()
    (out / 'manifest.json').write_text(json.dumps(rec, indent=1, sort_keys=True) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{IT.sha(out / f)}  {f}\n' for f in ('boot.img', 'kernel.bin', 'payload-usb.bin', 'manifest.json', 'shim.elf')))
    print(a.name, 'chooser-ios', 'bootable' if bootable else 'NOT BOOTABLE', rec['image'], 'blob', len(blob), 'image margin', real['image_margin'], 'blob margin', real['blob_margin'])
    return rec


def check(d):
    d = Path(d); m = json.loads((d / 'manifest.json').read_text())
    if m.get('kind') != 'chooser-ios': sys.exit('not a chooser-ios manifest')
    for f, k in (('boot.img', 'image'), ('kernel.bin', 'kernel_blob'), ('payload-usb.bin', 'payload_sha256')):
        if IT.sha(d / f) != m[k]: sys.exit(f'MISMATCH {f}')
    b = (d / 'boot.img').read_bytes(); h = CI.parse_boot_v4(b)
    if len(b) != IT.PARTITION or h['ramdisk_size'] != 0 or h['cmdline'] != m['header']['cmdline']: sys.exit('boot header differs from manifest')
    blob = h['kernel']
    try: poff, n, seg_off = layout(blob, m['end_off'])
    except ValueError as e: sys.exit(f'layout: {e}')
    if seg_off != m['segment_offset'] or hashlib.sha256(blob[poff:poff + n]).hexdigest() != m['payload_sha256']: sys.exit('payload or segment offset differs')
    seg = blob[seg_off:]
    comp, ilen, isz, flags, cs = struct.unpack_from('<QQQQQ', seg, 8)
    if seg[:8] != CI.SEG_MAGIC or struct.unpack_from('<Q', seg, 48)[0] != CI.csum64(seg[:48]): sys.exit('segment header invalid')
    lz4 = seg[CI.SEG_HDR:CI.SEG_HDR + comp]
    if hashlib.sha256(lz4).hexdigest() != m['stock']['lz4_sha256'] or CI.csum64(lz4) != cs: sys.exit('stock kernel bytes differ')
    if len(blob) > BLOB_LIMIT: sys.exit('kernel blob reaches ABL\'s initrd')
    f = b[-64:]; _, _, orig, off, size = struct.unpack('>IIQQQ', f[4:36])
    if f[:4] != b'AVBf' or b[off:off + size][:4] != b'AVB0' or 'sha256 ' + hashlib.sha256(b[off:off + size]).hexdigest() not in m['avb']:
        sys.exit('transplanted vbmeta differs from the record')
    if m['ios'].get('dir'):
        ios = Path(m['ios']['dir'])
        if IT.sha(ios / 'payload-usb.bin') != m['payload_sha256']: sys.exit('payload differs from the named iOS image')
    print('OK', m['name'], 'chooser-ios', 'bootable' if m['bootable'] else 'NOT BOOTABLE', 'default', m['default_entry'],
          'installable' if m['installable'] else 'not installable', m['image'])


def budget_cmd(a):
    payload = Path(a.payload).stat().st_size
    raw = Path(a.stock_kernel).read_bytes()
    lz4 = len(CI.parse_boot_v4(raw)['kernel']) if raw[:8] == b'ANDROID!' else len(raw)
    r = budget(a.shim_bytes, payload, lz4)
    w = max(map(len, r))
    for k, v in r.items(): print(f'{k:<{w}}  {v:>12,}  ({v / 1048576:7.2f} MiB)')
    return r


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('image'); i.add_argument('name')
    i.add_argument('--ios-image', help='a checked, bootable image_tool --phone-root directory (research/images/NAME)')
    i.add_argument('--payload', help='host checks only (name test-*): a payload-usb.bin, built with the default iOS shim flags')
    i.add_argument('--bootcpu', help='with --payload: build the fastcore shim as for --bootcpu')
    i.add_argument('--stock-kernel', required=True); i.add_argument('--stock-kernel-sha', required=True)
    i.add_argument('--fdt', help='A0 /sys/firmware/fdt dump: admission and placement host tests on real data')
    i.add_argument('--keys', action='store_true', help='volume keys via shim/keys_laguna.c (TGL_KEYS_POLL)')
    i.add_argument('--default-ios', action='store_true', help='countdown ends on iOS: attended iOS-branch test image, never installable')
    c = sub.add_parser('check'); c.add_argument('dir')
    g = sub.add_parser('budget'); g.add_argument('--payload', required=True); g.add_argument('--stock-kernel', required=True)
    g.add_argument('--shim-bytes', type=int, default=3 << 20)
    a = ap.parse_args()
    {'image': build, 'check': lambda a: check(a.dir), 'budget': budget_cmd}[a.cmd](a)
