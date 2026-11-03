#!/usr/bin/env python3
"""Unit tests for tools/chooser_ios_image.py's pure parts: layout mirror, assembly, size budget. Host only."""
import struct, sys, unittest
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chooser_ios_image as T
import chooser_image as CI


def shim_image(end_off, payload):
    """What build.sh writes: Image padded to _end, then TEGUPLD1 n payload, image_size = length."""
    b = bytearray(end_off); b[56:60] = b'ARM\x64'
    b += T.ENV_MAGIC + struct.pack('<Q', len(payload)) + payload
    struct.pack_into('<Q', b, 16, len(b))
    return bytes(b)


def seg(n=100):
    lz4 = bytes((i * 7 + 1) & 0xff for i in range(n))
    return CI.segment(lz4, 4000, 8192, 0xa)


class Layout(unittest.TestCase):
    def test_every_payload_length_mod_8(self):
        for n in range(1, 17):
            pl = bytes(range(n))
            blob, off = T.assemble(shim_image(4096, pl), 4096, pl, seg())
            self.assertEqual(off % 8, 0)
            self.assertEqual(T.layout(blob, 4096), (4112, n, off))
            self.assertEqual(struct.unpack_from('<Q', blob, 16)[0], len(blob))
            self.assertEqual(blob[off:off + 8], CI.SEG_MAGIC)
            self.assertEqual(blob[4112:4112 + n], pl)

    def test_refusals(self):
        pl = b'x' * 24
        blob, off = T.assemble(shim_image(4096, pl), 4096, pl, seg())
        with self.assertRaises(ValueError): T.layout(blob, 4092)                       # _end not aligned
        b = bytearray(blob); b[4096] ^= 1
        with self.assertRaises(ValueError): T.layout(bytes(b), 4096)                   # no envelope
        b = bytearray(blob); struct.pack_into('<Q', b, 4104, len(b))
        with self.assertRaises(ValueError): T.layout(bytes(b), 4096)                   # length past image
        b = bytearray(blob); struct.pack_into('<Q', b, 4104, 0)
        with self.assertRaises(ValueError): T.layout(bytes(b), 4096)                   # empty payload
        b = bytearray(blob[:off + 63]); struct.pack_into('<Q', b, 16, len(b))
        with self.assertRaises(ValueError): T.layout(bytes(b), 4096)                   # no room for segment header
        b = bytearray(blob); struct.pack_into('<Q', b, 16, len(b) - 8)
        with self.assertRaises(ValueError): T.layout(bytes(b), 4096)                   # image_size short

    def test_assemble_refuses_a_foreign_envelope(self):
        pl = b'y' * 40
        img = shim_image(4096, pl)
        with self.assertRaises(ValueError): T.assemble(img, 4096, b'z' * 40, seg())    # other payload bytes
        with self.assertRaises(ValueError): T.assemble(img + b'\0' * 8, 4096, pl, seg())  # trailing bytes after the envelope
        with self.assertRaises(ValueError): T.assemble(img, 4088, pl, seg())           # wrong _end


class Budget(unittest.TestCase):
    def test_measured_inputs_fit(self):
        # host-measured 2026-11-03: rootview payload without overlay 25,416,256 B; boot_b lz4 20,437,225 B; r11 shim 2,740,224 B
        r = T.budget(2740224, 25416256, 20437225)
        self.assertEqual(r['segment'], 64 + 20437232)
        self.assertEqual(r['blob'], T.align8(2740224 + 16 + 25416256) + r['segment'])
        self.assertGreater(r['image_margin'], 16 << 20)
        self.assertGreater(r['blob_margin'], 40 << 20)
        self.assertGreater(r['blob_over_proven'], 0)    # larger than anything ABL has loaded for us: an attended step

    def test_limits(self):
        r = T.budget(3 << 20, 42 << 20, 20437225)      # a 42 MiB payload no longer fits the partition
        self.assertLess(r['image_margin'], 0)
        self.assertEqual(T.BLOB_LIMIT, 96 << 20)


if __name__ == '__main__':
    r = unittest.main(exit=False, verbosity=0).result
    print(f'chooser-ios tool test: {r.testsRun} tests, {len(r.failures) + len(r.errors)} failed')
    sys.exit(0 if r.wasSuccessful() else 1)
