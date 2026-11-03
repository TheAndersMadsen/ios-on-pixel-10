#!/usr/bin/env python3
"""Host tests for tools/fb_png.py and the kernel's hk_screen record (research/ios26-phaseb-r1/live/screen).

  python3 -I tools/test_fb_png.py

Synthetic framebuffers only. When a C compiler is present it also builds test/test_hk_screen.c (the kernel's own
hk_screen_pure.inc, under ASan/UBSan), and checks that the records it writes decode to exactly what fb_png.py's
Python model of the sampler computes from the same panel buffer.
"""
import importlib.util
import io
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCREEN = REPO / 'research/ios26-phaseb-r1/live/screen'
spec = importlib.util.spec_from_file_location('fb_png', HERE / 'fb_png.py')
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)


def read_png(path):
    """(width, height, RGB bytes) of an 8-bit RGB, filter-0 PNG as fb_png writes it."""
    data = Path(path).read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, w = 8, b'', None
    while pos < len(data):
        n, kind = struct.unpack_from('>I4s', data, pos)
        body = data[pos + 8:pos + 8 + n]
        assert struct.unpack_from('>I', data, pos + 8 + n)[0] == zlib.crc32(kind + body) & 0xffffffff
        if kind == b'IHDR':
            w, h, depth, ctype = struct.unpack_from('>IIBB', body)
            assert (depth, ctype) == (8, 2)
        elif kind == b'IDAT':
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    rows = bytearray()
    for y in range(h):
        line = raw[y * (w * 3 + 1):(y + 1) * (w * 3 + 1)]
        assert line[0] == 0
        rows += line[1:]
    return w, h, bytes(rows)


def picture(w, h):
    """BGRA words, B lowest: red rises left to right, green top to bottom, a blue checkerboard."""
    return [(0xe0 if ((x // 7 + y // 9) & 1) else 0x10) | ((y * 255 // (h - 1)) << 8) | ((x * 255 // (w - 1)) << 16)
            | 0xff000000 for y in range(h) for x in range(w)]


def make_dump(words, stride_words, sw, sh, out_w=360, box=True, reason=3, nonce=0x55, entry=1000, handoff=900,
              rec_nonce=None, cntvct=2000, nopic=False):
    dump = bytearray(fb.DUMP_BYTES)
    struct.pack_into('<8sQQQQIIQQ', dump, fb.XNUENT_OFF, b'XNUENT1\0', nonce, entry, entry, 38400000, 7, 0, handoff, 0)
    if nopic:
        w = h = step = 0
        rows = b''
    else:
        w, h, rows = fb.downscale(words, stride_words, sw, sh, out_w, box)
        step = fb.dims(sw, sh, out_w)[2]
    flags = (fb.FLAG_ON | (fb.FLAG_BOX if box else 0)) | (fb.FLAG_NOPIC if nopic else 0)
    hdr = fb.HDR.pack(fb.MAGIC, 1, 128, 1, reason, w, h, 1, flags, sw, sh, step, 1234, len(rows),
                      zlib.crc32(rows) & 0xffffffff, cntvct, 38400000, struct.unpack('<Q', b'XNUENT1\0')[0],
                      nonce if rec_nonce is None else rec_nonce, entry, handoff, stride_words * 4, 0, 0)
    dump[fb.SCREEN_OFF:fb.SCREEN_OFF + 128] = hdr
    dump[fb.SCREEN_OFF + 128:fb.SCREEN_OFF + 128 + len(rows)] = rows
    return dump, w, h, rows


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fb.main([str(a) for a in args])
    return rc, out.getvalue(), err.getvalue()


class Sampler(unittest.TestCase):
    def test_dims_match_the_kernel(self):
        self.assertEqual(fb.dims(1125, 2511, 360), (360, 803, 204800))
        self.assertEqual(fb.dims(1280, 2856, 360)[:2], (360, 803))
        self.assertIsNone(fb.dims(0, 10, 360))
        self.assertEqual(fb.dims(301, 10, 360)[0], 300)

    def test_channel_order(self):
        self.assertEqual(fb.to565(0xff0000ff), 0x001f)       # B lowest byte
        self.assertEqual(fb.to565(0xffff0000), 0xf800)
        rgb = fb.rgb565_to_rgb(struct.pack('<3H', 0xf800, 0x07e0, 0x001f), 3, 1)
        self.assertEqual(rgb, bytes((255, 0, 0, 0, 255, 0, 0, 0, 255)))
        self.assertEqual(fb.rgb565_to_rgb(struct.pack('<H', 0xf800), 1, 1, swap_rb=True), bytes((0, 0, 255)))

    def test_box_average(self):
        words = [0xff000000, 0xff0000ff, 0xff0000ff, 0xff0000ff]       # 2x2: one black, three blue (255)
        w, h, rows = fb.downscale(words, 2, 2, 2, 2)
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(struct.unpack('<H', rows[:2])[0], fb.to565(0xff0000bf))    # (0+255*3+2)//4 = 191 -> 5 bits 23


class Record(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='fb_png_'))
        self.sw, self.sh = 150, 334
        self.words = picture(self.sw, self.sh)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write(self, dump, name='kernel.log'):
        p = self.tmp / name
        p.write_bytes(dump)
        return p

    def test_fresh_record_to_png(self):
        dump, w, h, rows = make_dump(self.words, self.sw, self.sw, self.sh, out_w=60)
        rc, out, err = run([self.write(dump), '-o', self.tmp / 's.png'])
        self.assertEqual(rc, 0, err)
        self.assertIn('fresh', out)
        pw, ph, rgb = read_png(self.tmp / 's.png')
        self.assertEqual((pw, ph), (w, h))
        self.assertEqual(rgb, fb.rgb565_to_rgb(rows, w, h))
        # Picture sense: top-left is dark, bottom-right has red and green up.
        self.assertLess(rgb[0], 40)
        self.assertGreater(rgb[-3], 200)
        self.assertGreater(rgb[-2], 200)

    def test_scale(self):
        dump, w, h, _ = make_dump(self.words, self.sw, self.sw, self.sh, out_w=60)
        rc, _, err = run([self.write(dump), '-o', self.tmp / 's.png', '--scale', '3'])
        self.assertEqual(rc, 0, err)
        self.assertEqual(read_png(self.tmp / 's.png')[:2], (w * 3, h * 3))

    def test_attempt_directory(self):
        dump, w, h, _ = make_dump(self.words, self.sw, self.sw, self.sh, out_w=60)
        (self.tmp / 'att/ramdump').mkdir(parents=True)
        (self.tmp / 'att/ramdump/kernel.log').write_bytes(dump)
        rc, _, err = run([self.tmp / 'att'])
        self.assertEqual(rc, 0, err)
        self.assertEqual(read_png(self.tmp / 'att/screen.png')[:2], (w, h))

    def test_stale_refused_unless_allowed(self):
        dump, *_ = make_dump(self.words, self.sw, self.sw, self.sh, out_w=60, rec_nonce=0x77)
        p = self.write(dump)
        rc, _, err = run([p, '-o', self.tmp / 's.png'])
        self.assertEqual(rc, 4)
        self.assertIn('stale', err)
        self.assertFalse((self.tmp / 's.png').exists())
        rc, _, _ = run([p, '-o', self.tmp / 's.png', '--allow-stale'])
        self.assertEqual(rc, 0)

    def test_captured_before_entry_is_stale(self):
        dump, *_ = make_dump(self.words, self.sw, self.sw, self.sh, out_w=60, cntvct=10)
        self.assertEqual(run([self.write(dump), '-o', self.tmp / 's.png'])[0], 4)

    def test_absent_torn_short(self):
        self.assertEqual(run([self.write(bytes(fb.DUMP_BYTES))])[0], 3)
        dump, *_ = make_dump(self.words, self.sw, self.sw, self.sh, out_w=60)
        dump[fb.SCREEN_OFF + 200] ^= 0xff
        rc, _, err = run([self.write(dump, 'torn.log')])
        self.assertEqual(rc, 3)
        self.assertIn('crc', err)
        self.assertEqual(run([self.write(bytes(0x1000), 'short.log')])[0], 3)

    def test_no_picture(self):
        dump, *_ = make_dump(self.words, self.sw, self.sw, self.sh, nopic=True)
        rc, _, err = run([self.write(dump)])
        self.assertEqual(rc, 3)
        self.assertIn('no picture', err)

    def test_rgb565_input(self):
        rows = struct.pack('<4H', 0xf800, 0x07e0, 0x001f, 0xffff)
        p = self.tmp / 'snap.rgb565'
        p.write_bytes(rows)
        rc, _, err = run(['--rgb565', p, '--size', '2x2', '-o', self.tmp / 'snap.png'])
        self.assertEqual(rc, 0, err)
        self.assertEqual(read_png(self.tmp / 'snap.png'), (2, 2, bytes((255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255))))
        rc, _, err = run(['--rgb565', p, '--size', '3x2'])
        self.assertEqual(rc, 3)
        self.assertIn('not 3x2', err)

    def test_bgra_panel_buffer(self):
        # The picture at the origin of a wider buffer with junk outside it, as under hk_fb_scale=1.
        stride_w = self.sw + 30
        buf = bytearray()
        for y in range(self.sh + 20):
            for x in range(stride_w):
                buf += struct.pack('<I', self.words[y * self.sw + x] if x < self.sw and y < self.sh else 0x5a5a5a5a)
        p = self.tmp / 'panel.bgra'
        p.write_bytes(buf)
        rc, _, err = run(['--bgra', p, '--size', f'{stride_w}x{self.sh + 20}', '--crop', f'{self.sw}x{self.sh}',
                          '--width', '60', '-o', self.tmp / 'panel.png'])
        self.assertEqual(rc, 0, err)
        _, w, h, rows = make_dump(self.words, self.sw, self.sw, self.sh, out_w=60)
        self.assertEqual(read_png(self.tmp / 'panel.png'), (w, h, fb.rgb565_to_rgb(rows, w, h)))


@unittest.skipUnless(shutil.which('cc'), 'no C compiler')
class KernelWriter(unittest.TestCase):
    """The kernel's hk_screen_pure.inc writes the record; fb_png.py's model of the sampler must agree bit for bit."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='hk_screen_'))
        exe = cls.tmp / 'test_hk_screen'
        cc = ['cc', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(SCREEN / 'xnu-src/osfmk/arm64'),
              str(SCREEN / 'test/test_hk_screen.c'), '-o', str(exe)]
        r = subprocess.run(cc + ['-fsanitize=address,undefined'], capture_output=True, text=True)
        if r.returncode:
            r = subprocess.run(cc, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.run_out = subprocess.run([str(exe), str(cls.tmp)], capture_output=True, text=True)
        data = (cls.tmp / 'panel.bgra').read_bytes()
        cls.panel = struct.unpack(f'<{len(data) // 4}I', data)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_c_unit_passes(self):
        self.assertEqual(self.run_out.returncode, 0, self.run_out.stdout + self.run_out.stderr)
        self.assertIn('PASS: 0 failures', self.run_out.stdout)

    def check(self, name, box):
        rc, out, err = run([self.tmp / name, '-o', self.tmp / (name + '.png'), '--json'])
        self.assertEqual(rc, 0, err)
        w, h, rows = fb.downscale(self.panel, 1280, 1125, 2511, 360, box)
        self.assertEqual((w, h), (360, 803))
        self.assertEqual(read_png(self.tmp / (name + '.png')), (w, h, fb.rgb565_to_rgb(rows, w, h)))
        self.assertIn('"identity": "fresh"', out)

    def test_box_record_matches_model(self):
        self.check('kernel-box.log', True)

    def test_point_record_matches_model(self):
        self.check('kernel-point.log', False)

    def test_other_boot_is_stale(self):
        self.assertEqual(run([self.tmp / 'kernel-stale.log', '-o', self.tmp / 'x.png'])[0], 4)



FAKE_MAC = r"""#!/usr/bin/env python3
# Test double for phone-bridge `mac repo --force [--back P]... -- CMD...`, run from the fake checkout.
import json, os, struct, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ['FAKE_MAC_LOG'])
log.write_text(log.read_text() + ' '.join(args) + '\n' if log.exists() else ' '.join(args) + '\n')
cmd = args[args.index('--') + 1:]
if '--snapshot' not in cmd:
    sys.exit(0)
mode = os.environ.get('FAKE_MAC_MODE', 'ok')
if mode == 'refuse':
    print(json.dumps(dict(state='refused', error='snapshot unavailable', ui_observed=False)))
    sys.exit(4)
name = cmd[cmd.index('--snap-name') + 1]
stem = Path('research/laguna-usb-fix/attempts/live-x/usbcon/usbcon.log.snaps') / f'0001-{name}'
stem.parent.mkdir(parents=True, exist_ok=True)
w, h = 4, 2
stem.with_suffix('.rgb565').write_bytes(struct.pack('<8H', *([0xf800] * 4 + [0x001f] * 4)))
stem.with_suffix('.png').write_bytes(b'png')
stem.with_suffix('.json').write_text('{}')
print(json.dumps(dict(state='snapshot', ui_observed=False, snapshot=dict(png=str(stem) + '.png', width=w, height=h,
                                                                          step=int(cmd[cmd.index('--snap-step') + 1]), took_us=77))))
"""


@unittest.skipUnless(shutil.which('bash'), 'no bash')
class Screenshot(unittest.TestCase):
    """tools/screenshot.sh against a fake checkout and a fake `mac`; nothing leaves the temp dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='screenshot_'))
        (self.tmp / 'tools').mkdir()
        for f in ('screenshot.sh', 'fb_png.py'):
            shutil.copy(HERE / f, self.tmp / 'tools' / f)
        self.mac = self.tmp / 'mac'
        self.mac.write_text(FAKE_MAC)
        self.mac.chmod(0o755)
        self.run_dir = self.tmp / 'research/laguna-usb-fix/attempts/live-x'
        self.run_dir.mkdir(parents=True)
        (self.run_dir / 'live.env').write_text('LIVE_RUN=x\nLIVE_SOCK=/tmp/hackios-live-1.sock\n')
        self.env = dict(PATH='/usr/bin:/bin', HOME=str(self.tmp), SCREENSHOT_MAC=str(self.mac),
                        FAKE_MAC_LOG=str(self.tmp / 'mac.log'))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def sh(self, *args, **env):
        return subprocess.run(['bash', str(self.tmp / 'tools/screenshot.sh'), *map(str, args)], capture_output=True,
                              text=True, env=dict(self.env, **env), cwd=self.tmp)

    def test_live_newest_run(self):
        r = self.sh('--name', 'home', '--step', '7', '--scale', '2')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = Path(r.stdout.strip().splitlines()[-1])
        self.assertTrue(out.name.startswith('home-') and out.parent == self.run_dir / 'screens', out)
        self.assertEqual(read_png(out), (8, 4, bytes((255, 0, 0)) * 16 + bytes((0, 0, 255)) * 16))
        calls = (self.tmp / 'mac.log').read_text()
        self.assertIn('--control-socket /tmp/hackios-live-1.sock --snapshot --snap-step 7 --snap-name home', calls)
        self.assertIn('--back research/laguna-usb-fix/attempts/live-x/usbcon/usbcon.log.snaps/0001-home.rgb565', calls)

    def test_live_refused(self):
        r = self.sh(self.run_dir, FAKE_MAC_MODE='refuse')
        self.assertEqual(r.returncode, 4)
        self.assertIn('refused', r.stderr)

    def test_bad_arguments(self):
        self.assertEqual(self.sh('--step', '0').returncode, 2)
        self.assertEqual(self.sh('--name', 'a b').returncode, 2)
        self.assertEqual(self.sh('relative.sock').returncode, 2)

    def test_dump(self):
        dump, w, h, _ = make_dump(picture(150, 334), 150, 150, 334, out_w=60)
        (self.tmp / 'att/ramdump').mkdir(parents=True)
        (self.tmp / 'att/ramdump/kernel.log').write_bytes(dump)
        r = self.sh('--dump', self.tmp / 'att')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(read_png(self.tmp / 'att/screen.png')[:2], (w, h))
        dump, *_ = make_dump(picture(150, 334), 150, 150, 334, out_w=60, rec_nonce=1)
        (self.tmp / 'att/ramdump/kernel.log').write_bytes(dump)
        self.assertEqual(self.sh('--dump', self.tmp / 'att', '-o', self.tmp / 'y.png').returncode, 4)
        self.assertEqual(self.sh('--dump', self.tmp / 'att', '-o', self.tmp / 'y.png', '--allow-stale').returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
