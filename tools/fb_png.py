#!/usr/bin/env python3
"""Framebuffer pictures to PNG. Host only; reads files, never a device.

  fb_png.py DUMP [-o OUT.png] [--allow-stale] [--scale N] [--json]
      DUMP: a ramdump kernel.log (4 MiB from 0x95200000; tools/capture-fastboot.py) or an attempt directory
      (uses <dir>/ramdump/kernel.log, writes <dir>/screen.png by default). Decodes the hk_screen record
      (HKSCR1 at pmsg+0x150000, PA 0x95550000) that XNU writes with hk_screen=N at the deadline, at panic and
      every N s. Refuses a record whose XNUENT1 identity is not this dump's (previous boot residue) unless
      --allow-stale.
  fb_png.py --rgb565 FILE --size WxH [-o OUT.png]
      A usbcon snapshot's raw .rgb565 (blazer_usbcon_snap, requests 0x67/0x68).
  fb_png.py --bgra FILE [--size 1280x2856] [--stride 5120] [--crop 1125x2511] [--width 360] [-o OUT.png]
      A raw BGRA panel buffer (e.g. a QEMU memory dump of 0xf0000000); downscaled the way the kernel does it.

--swap-rb swaps red and blue (if colours look wrong; the panel buffer is BGRA, B in the lowest byte).
--scale N enlarges by N (nearest) for viewing. Exit 0 written, 2 usage, 3 no record or invalid, 4 stale.
research/ios26-phaseb-r1/live/SCREEN.md.
"""
import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

RAMOOPS_PA = 0x95200000
DUMP_BYTES = 0x400000
SCREEN_PA = 0x95550000
SCREEN_OFF = SCREEN_PA - RAMOOPS_PA             # 0x350000 in kernel.log
SCREEN_CAP = 0x955F0000 - SCREEN_PA
XNUENT_OFF = 0x9543F840 - RAMOOPS_PA            # msgbuf v2 header + 0x40 (tools/read-ramdump.py MSGBUF_ENTRY)
MAGIC = b'HKSCR1\0\0'
HDR = struct.Struct('<8s14I2Q4QIIQ')
HDR_FIELDS = ('magic', 'version', 'hdr_bytes', 'seq', 'reason', 'width', 'height', 'format', 'flags', 'src_w', 'src_h',
              'step_q16', 'took_us', 'data_bytes', 'data_crc', 'cntvct', 'freq', 'ent_magic', 'ent_nonce', 'ent_entry_t',
              'ent_handoff_t', 'src_stride', 'reserved0', 'reserved1')
assert HDR.size == 128
REASONS = {1: 'panic', 2: 'periodic', 3: 'deadline'}
FLAG_ON, FLAG_BOX, FLAG_NOPIC = 1, 2, 4
ENT = struct.Struct('<8sQQQQIIQQ')              # XNUENT1: magic nonce entry_t init_t freq flags reserved handoff_t trailing


class RecordError(Exception):
    pass


def png(rgb, width, height, scale=1):
    """8-bit RGB rows (bytes, width*3 each) to PNG. No dependencies."""
    if len(rgb) != width * height * 3:
        raise ValueError('pixel buffer does not match its size')
    rows = bytearray()
    for y in range(height):
        line = rgb[y * width * 3:(y + 1) * width * 3]
        if scale > 1:
            line = b''.join(line[x * 3:x * 3 + 3] * scale for x in range(width))
        for _ in range(scale):
            rows.append(0)
            rows += line

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    w, h = width * scale, height * scale
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(rows), 9)) + chunk(b'IEND', b''))


def rgb565_to_rgb(raw, width, height, swap_rb=False):
    if len(raw) != width * height * 2:
        raise ValueError(f'{len(raw)} bytes is not {width}x{height} RGB565')
    lut = []
    for v in range(65536):
        r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
        r, g, b = (r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)
        lut.append(bytes((b, g, r) if swap_rb else (r, g, b)))
    return b''.join(lut[v] for (v,) in struct.iter_unpack('<H', raw))


# The kernel's sampler (xnu-src/osfmk/arm64/hk_screen_pure.inc), for raw buffers and as the tests' reference.
def dims(sw, sh, out_w):
    if not (0 < sw <= 0x8000 and 0 < sh <= 0x8000 and out_w > 0):
        return None
    out_w = min(out_w, sw, 640) & ~1
    if not out_w:
        return None
    step = (sw << 16) // out_w
    h = (sh << 16) // step
    return (out_w, h, step) if h else None


def tap(i, step, limit):
    return min((i * step + step // 2) >> 16, limit - 1)


def to565(p):
    return ((p >> 8) & 0xF800) | ((p >> 5) & 0x07E0) | ((p >> 3) & 0x001F)


def downscale(words, stride_words, sw, sh, out_w, box=True):
    """words: the picture's BGRA pixels as u32 (B lowest), row pitch stride_words. Returns (w, h, RGB565 bytes)."""
    d = dims(sw, sh, out_w)
    if d is None:
        raise ValueError('cannot downscale that')
    ow, oh, step = d
    xs = [tap(x, step, sw) for x in range(ow)]
    out = bytearray()
    for oy in range(oh):
        sy = tap(oy, step, sh)
        sy1 = min(sy + 1, sh - 1)
        r0, r1 = sy * stride_words, sy1 * stride_words
        for sx in xs:
            if not box:
                v = to565(words[r0 + sx])
            else:
                sx1 = min(sx + 1, sw - 1)
                a, b, c, e = words[r0 + sx], words[r0 + sx1], words[r1 + sx], words[r1 + sx1]
                lo = (a & 0xFF00FF) + (b & 0xFF00FF) + (c & 0xFF00FF) + (e & 0xFF00FF) + 0x20002
                hi = ((a >> 8) & 0xFF00FF) + ((b >> 8) & 0xFF00FF) + ((c >> 8) & 0xFF00FF) + ((e >> 8) & 0xFF00FF) + 0x20002
                v = to565(((lo >> 2) & 0xFF00FF) | (((hi >> 2) & 0xFF00FF) << 8))
            out += struct.pack('<H', v)
    return ow, oh, bytes(out)


def parse_record(dump):
    """dump: kernel.log bytes. Returns (header dict, RGB565 rows). Raises RecordError."""
    if len(dump) < SCREEN_OFF + HDR.size:
        raise RecordError(f'dump is {len(dump)} bytes; the record is at {SCREEN_OFF:#x} (needs the 4 MiB kernel.log)')
    h = dict(zip(HDR_FIELDS, HDR.unpack_from(dump, SCREEN_OFF)))
    if h['magic'] != MAGIC:
        raise RecordError('no HKSCR1 record (hk_screen off, no capture yet, or cut short)')
    if (h['version'], h['hdr_bytes'], h['format']) != (1, HDR.size, 1):
        raise RecordError(f"unknown record version {h['version']}/{h['hdr_bytes']}/{h['format']}")
    h['reason_name'] = REASONS.get(h['reason'], str(h['reason']))
    h['no_picture'] = bool(h['flags'] & FLAG_NOPIC)
    h['scanout_on'] = bool(h['flags'] & FLAG_ON)
    h['box'] = bool(h['flags'] & FLAG_BOX)
    if h['data_bytes'] != h['width'] * h['height'] * 2 or HDR.size + h['data_bytes'] > SCREEN_CAP:
        raise RecordError(f"size {h['width']}x{h['height']} does not match {h['data_bytes']} bytes")
    start = SCREEN_OFF + HDR.size
    data = bytes(dump[start:start + h['data_bytes']])
    if len(data) != h['data_bytes']:
        raise RecordError('dump ends inside the record')
    crc = zlib.crc32(data) & 0xffffffff
    if crc != h['data_crc']:
        raise RecordError(f"pixel crc {crc:#010x} != recorded {h['data_crc']:#010x} (torn or overwritten)")
    return h, data


def identity(dump, h):
    """'fresh' when the record carries this dump's XNUENT1 nonce/entry/handoff; else why not."""
    if len(dump) < XNUENT_OFF + ENT.size:
        return 'unknown: dump too short for XNUENT1'
    magic, nonce, entry_t, _init, _freq, _flags, _res, handoff_t, _trail = ENT.unpack_from(dump, XNUENT_OFF)
    if magic != b'XNUENT1\0':
        return 'unknown: no XNUENT1 in this dump'
    if h['ent_magic'] != struct.unpack('<Q', b'XNUENT1\0')[0]:
        return 'stale: the record has no XNUENT1 identity'
    if (h['ent_nonce'], h['ent_entry_t'], h['ent_handoff_t']) != (nonce, entry_t, handoff_t):
        return (f"stale: record nonce {h['ent_nonce']:#x} entry {h['ent_entry_t']:#x}, "
                f"this boot nonce {nonce:#x} entry {entry_t:#x}")
    if h['cntvct'] < entry_t:
        return 'stale: captured before this boot entered XNU'
    h['t_since_entry_s'] = round((h['cntvct'] - entry_t) / h['freq'], 3) if h['freq'] else None
    return 'fresh'


def parse_size(text):
    try:
        w, h = (int(v) for v in text.lower().split('x'))
    except ValueError:
        raise argparse.ArgumentTypeError(f'size must be WxH: {text}')
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(f'size must be positive: {text}')
    return w, h


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog='\n'.join(__doc__.splitlines()[1:]))
    p.add_argument('dump', nargs='?', type=Path, help='kernel.log or attempt directory')
    p.add_argument('-o', '--output', type=Path)
    p.add_argument('--allow-stale', action='store_true')
    p.add_argument('--rgb565', type=Path)
    p.add_argument('--bgra', type=Path)
    p.add_argument('--size', type=parse_size)
    p.add_argument('--stride', type=int)
    p.add_argument('--crop', type=parse_size)
    p.add_argument('--width', type=int, default=360)
    p.add_argument('--point', action='store_true', help='--bgra: point samples, not 2x2 averages')
    p.add_argument('--swap-rb', action='store_true')
    p.add_argument('--scale', type=int, default=1, choices=range(1, 9), metavar='1..8')
    p.add_argument('--json', action='store_true', help='print the record header as JSON')
    a = p.parse_args(argv)
    if sum(x is not None for x in (a.dump, a.rgb565, a.bgra)) != 1:
        p.error('give one of DUMP, --rgb565 FILE, --bgra FILE')
    info = {}
    if a.rgb565:
        if not a.size:
            p.error('--rgb565 needs --size WxH')
        w, h = a.size
        raw = a.rgb565.read_bytes()
        out = a.output or a.rgb565.with_suffix('.png')
    elif a.bgra:
        fw, fh = a.size or (1280, 2856)
        stride = a.stride or fw * 4
        cw, ch = a.crop or (fw, fh)
        if stride % 4 or stride < cw * 4 or cw > fw or ch > fh:
            p.error('--stride/--crop do not fit the buffer')
        data = a.bgra.read_bytes()
        if len(data) < stride * (ch - 1) + cw * 4:
            p.error(f'{a.bgra} is {len(data)} bytes, too short for {cw}x{ch} at stride {stride}')
        words = struct.unpack_from(f'<{len(data) // 4}I', data)
        w, h, raw = downscale(words, stride // 4, cw, ch, a.width, box=not a.point)
        out = a.output or a.bgra.with_suffix('.png')
        info = dict(source=str(a.bgra), src_w=cw, src_h=ch, stride=stride, width=w, height=h)
    else:
        path = a.dump
        default_out = None
        if path.is_dir():
            default_out = path / 'screen.png'
            path = path / 'ramdump' / 'kernel.log'
        try:
            dump = path.read_bytes()
        except OSError as exc:
            print(f'fb_png: {exc}', file=sys.stderr)
            return 3
        try:
            hdr, raw = parse_record(dump)
        except RecordError as exc:
            print(f'fb_png: {path}: {exc}', file=sys.stderr)
            return 3
        state = identity(dump, hdr)
        hdr['identity'] = state
        info = {k: v for k, v in hdr.items() if k not in ('magic', 'reserved0', 'reserved1')}
        info['source'] = str(path)
        if not state.startswith('fresh') and not a.allow_stale:
            print(f'fb_png: {path}: record is not from this boot ({state}); --allow-stale to write it anyway',
                  file=sys.stderr)
            if a.json:
                print(json.dumps(info, indent=1))
            return 4
        if hdr['no_picture']:
            print(f"fb_png: {path}: capture {hdr['seq']} ({hdr['reason_name']}) had no picture "
                  '(scanout never attached, or a flipped client surface)', file=sys.stderr)
            if a.json:
                print(json.dumps(info, indent=1))
            return 3
        w, h = hdr['width'], hdr['height']
        out = a.output or default_out or path.with_name('screen.png')
    try:
        rgb = rgb565_to_rgb(raw, w, h, a.swap_rb)
    except ValueError as exc:
        print(f'fb_png: {exc}', file=sys.stderr)
        return 3
    out.write_bytes(png(rgb, w, h, a.scale))
    info.update(png=str(out), png_width=w * a.scale, png_height=h * a.scale)
    if a.json:
        print(json.dumps(info, indent=1))
    else:
        extra = ''
        if 'reason_name' in info:
            extra = (f" capture {info['seq']} {info['reason_name']}, {info['identity']}, "
                     f"t+{info.get('t_since_entry_s')} s, took {info['took_us']} us, scanout {'on' if info['scanout_on'] else 'off'}")
        print(f'fb_png: wrote {out} ({w * a.scale}x{h * a.scale}){extra}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
