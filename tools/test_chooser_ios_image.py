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


class Gates(unittest.TestCase):
    IOS = '-DTGL_ALL_DCS=1 -DTGL_FRAME_RUNG=3 -DTGL_DCS_HANDOFF=1'

    def test_keys_bring_the_r13_loop(self):
        f = T.chooser_cflags(self.IOS, True, False).split()
        for g in ('-DTGL_KEYS_POLL=1', '-DTGL_CHOOSER_KEYS_FIX=1', '-DTGL_MENU_ROW_HOOK=1', '-DTGL_DCS_PRESENT_QUIET=1'):
            self.assertIn(g, f)
        self.assertNotIn('-DTGL_CHOOSER_IOS_DEFAULT=1', f)
        self.assertNotIn('-DTGL_CHOOSER_KEYS=1', f)          # chooser_ios.c refuses chooser.c's raw key reads
        self.assertNotIn('-DTGL_CHOOSER_KEYS_POLL=1', f)
        self.assertEqual(T.KEYS_FLAGS, ' -DTGL_KEYS_POLL=1' + CI.KEYS_FIX_FLAGS)   # the same r13 gates as chooser-v1-r13
        self.assertIn('keys_laguna.c', T.chooser_src('tgl_all.c tgl_dcs.c', True).split())

    def test_no_keys_is_the_r1_build(self):
        # chooser-ios-r1(-ios): no r13 gate, so chooser_ios.c compiles to r1's bytes
        f = T.chooser_cflags(self.IOS, False, True)
        self.assertEqual(f, self.IOS + ' ' + T.CHOOSER_IOS_FLAGS + ' -DTGL_CHOOSER_IOS_DEFAULT=1')
        self.assertNotIn('keys_laguna.c', T.chooser_src('tgl_all.c tgl_dcs.c', False).split())
        self.assertEqual(T.menu_reference_flags(False), T.R11_MENU_FLAGS)

    def test_menu_reference_with_keys_is_r11_plus_quiet(self):
        self.assertEqual(T.menu_reference_flags(True).split(), T.R11_MENU_FLAGS.split() + ['-DTGL_DCS_PRESENT_QUIET=1'])

    def test_installable(self):
        self.assertTrue(T.installable(True, True, False))     # chooser-ios-r2: keys, default Android
        self.assertFalse(T.installable(True, True, True))     # chooser-ios-r2-ios: default iOS
        self.assertFalse(T.installable(True, False, False))   # chooser-ios-r1: no keys
        self.assertFalse(T.installable(False, True, False))   # test-* builds

    def test_key_symbols(self):
        for s in ('tgl_chooser_ios_menu_tick', 'chooser_menu_tick', 'keys_poll'):
            self.assertIn(s, T.KEYS_T)
            self.assertIn(s, T.KEYS_ONLY)
        self.assertNotIn('tgl_chooser_menu_feed', T.KEYS_ONLY)   # compiled with chooser.c's pure helpers; only the linker drops it without --keys


class LoopCheck(unittest.TestCase):
    # shape of chooser-ios-r2's tgl_chooser_run (llvm-objdump, linked shim): hook = chooser_menu_tick at 0x23d50,
    # tgl_menu_row_hook at 0x298060
    RUN = """
   23478:      \tadrp\tx10, 0x298000 <cios_ks>
   23498:      \tadrp\tx9, 0x23000 <tgl_chooser_run+0x398>
   2349c:      \tadd\tx9, x9, #0xd50
   234a4:      \tstr\tx9, [x10, #0x60]
   234ac:      \tmov\tw9, #0x3a98             // =15000
   23684:      \tbl\t0x24744 <tgl_menu_draw_band>
   236bc:      \tbl\t0x24744 <tgl_menu_draw_band>
   236e4:      \tbl\t0x29674 <tgl_dcsm_present>
"""

    def test_linked(self):
        self.assertEqual(T.r13_loop_linked(self.RUN, 0x23d50, 0x298060), 0)

    def test_refusals(self):
        self.assertIn('chooser_menu_tick', T.r13_loop_linked(self.RUN, 0x23d54, 0x298060))
        self.assertIn('row_hook', T.r13_loop_linked(self.RUN, 0x23d50, 0x298068))
        clobbered = self.RUN.replace('   2349c:', '   2349a:      \tmov\tx10, x2\n   2349c:')   # x10 no longer the hook page
        self.assertIn('row_hook', T.r13_loop_linked(clobbered, 0x23d50, 0x298060))
        self.assertIn('2 ways', T.r13_loop_linked(self.RUN.replace('   236bc:      \tbl\t0x24744 <tgl_menu_draw_band>', ''), 0x23d50, 0x298060))
        self.assertIn('present', T.r13_loop_linked(self.RUN.replace('tgl_dcsm_present', 'tgl_dcs_present'), 0x23d50, 0x298060))
        self.assertIn('hard end', T.r13_loop_linked(self.RUN.replace('#0x3a98', '#0x1388'), 0x23d50, 0x298060))


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
