#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Owned AOSP-produced fixtures and malformed extent/fragment regressions."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import android_bootset as a


class BootsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.folder = Path(cls.tmp.name)
        cls.unpacker = ROOT/'third_party/aosp_bootimg/unpack_bootimg.py'
        for name, data in [('kernel', b'OWNED-KERNEL'*711), ('ramdisk', b'OWNED-RAMDISK'*113),
                           ('platform', b'PLATFORM'*37), ('recovery', b'RECOVERY'*41),
                           ('dtb', b'OWNED-DTB'*43), ('config', b'owned.option=1\n')]:
            (cls.folder/name).write_bytes(data)

        def pack(args):
            subprocess.run([sys.executable, '-I', str(ROOT/'tools/mkbootimg.py'), '--header_version', '4', *args],
                           check=True, capture_output=True)
        cls.boot = cls.folder/'boot.img'
        pack(['--kernel', str(cls.folder/'kernel'), '--ramdisk', str(cls.folder/'ramdisk'), '-o', str(cls.boot)])
        cls.init_boot = cls.folder/'init_boot.img'
        pack(['--ramdisk', str(cls.folder/'ramdisk'), '-o', str(cls.init_boot)])
        cls.vendor = cls.folder/'vendor_boot.img'
        pack(['--pagesize', '2048', '--vendor_boot', str(cls.vendor), '--dtb', str(cls.folder/'dtb'),
              '--vendor_bootconfig', str(cls.folder/'config'), '--ramdisk_name', 'platform', '--ramdisk_type', 'platform',
              '--board_id0', '7', '--vendor_ramdisk_fragment', str(cls.folder/'platform'),
              '--ramdisk_name', 'recovery', '--ramdisk_type', 'recovery', '--board_id0', '8',
              '--vendor_ramdisk_fragment', str(cls.folder/'recovery')])

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def inspect(self, data, role='vendor_boot'):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'input'; p.write_bytes(data)
            with a.regular_open(p) as f: return a.inspect_image(f, role, len(data))

    def test_aosp_components_and_unchanged_inputs(self):
        paths = [('boot', self.boot), ('init_boot', self.init_boot), ('vendor_boot', self.vendor)]
        before = [a.digest(p.read_bytes()) for _, p in paths]
        with tempfile.TemporaryDirectory() as tmp:
            result = a.inventory(paths, 'a', self.unpacker, Path(tmp)/'out')
            self.assertTrue(all(x['aosp_checked'] for x in result['images']))
            self.assertFalse(result['ready_for_android_dispatch'])
            self.assertFalse(result['complete_recovery_backup'])
            v = result['images'][2]
            self.assertEqual([(f['name'], f['type'], f['board_id'][0]) for f in v['fragments']],
                             [('platform', 1, 7), ('recovery', 2, 8)])
            self.assertEqual((Path(tmp)/'out/vendor_boot/bootconfig').read_bytes(), (self.folder/'config').read_bytes())
        self.assertEqual(before, [a.digest(p.read_bytes()) for _, p in paths])

    def test_role_mismatch_and_unknown_version(self):
        for data, role in ((self.boot.read_bytes(), 'init_boot'), (self.init_boot.read_bytes(), 'boot'),
                           (self.boot.read_bytes(), 'vendor_boot'), (self.vendor.read_bytes(), 'boot')):
            with self.assertRaises(a.Refused): self.inspect(data, role)
        boot = bytearray(self.boot.read_bytes()); struct.pack_into('<I', boot, 40, 3)
        with self.assertRaises(a.Refused): self.inspect(boot, 'boot')

    def test_truncated_headers_and_sections(self):
        for p, role in ((self.boot, 'boot'), (self.vendor, 'vendor_boot')):
            data = p.read_bytes(); parsed = self.inspect(data, role)
            ends = [part['offset']+part['size'] for part in parsed['components'] if part['size']]
            for end in [7, 44, 1583 if role == 'boot' else 2127, *[x-1 for x in ends]]:
                with self.subTest(role=role, end=end), self.assertRaises(a.Refused): self.inspect(data[:end], role)

    def test_fragment_table_arithmetic_and_overlap(self):
        data = self.vendor.read_bytes(); parsed = self.inspect(data)
        table = next(x['offset'] for x in parsed['components'] if x['name'] == 'vendor_ramdisk_table')
        for offset, value in ((2112, 1), (2116, 4097), (2120, 0), (2124, 0xffffffff),
                              (table, 0xffffffff), (table+4, 0xffffffff), (table+8, 4),
                              (table+108+4, 0), (2096, 4096), (12, 3000)):
            bad = bytearray(data); struct.pack_into('<I', bad, offset, value)
            with self.subTest(offset=offset), self.assertRaises(a.Refused): self.inspect(bad)

    def test_unsafe_or_duplicate_fragment_names(self):
        data = self.vendor.read_bytes(); parsed = self.inspect(data)
        table = next(x['offset'] for x in parsed['components'] if x['name'] == 'vendor_ramdisk_table')
        for name in (b'../../escape', b'/tmp/escape', b'has space', b'\xff'):
            bad = bytearray(data); bad[table+12:table+44] = name.ljust(32, b'\0')
            with self.assertRaises(a.Refused): self.inspect(bad)
        bad = bytearray(data); bad[table+108+12:table+108+44] = bad[table+12:table+44]
        with self.assertRaises(a.Refused): self.inspect(bad)

    def test_signature_extent_and_reserved_fields(self):
        for offset, value in ((8, 0xffffffff), (12, 0xffffffff), (20, 0), (24, 1), (1580, 0xffffffff)):
            bad = bytearray(self.boot.read_bytes()); struct.pack_into('<I', bad, offset, value)
            with self.assertRaises(a.Refused): self.inspect(bad, 'boot')
        # An owned signature blob tests extraction, not AVB cryptography.
        valid = bytearray(self.boot.read_bytes())
        # The AOSP producer reserves a zero-filled signature slot by default.
        old_size = struct.unpack_from('<I', valid, 1580)[0]
        self.assertGreater(old_size, 0)
        at = len(valid)-old_size
        valid[at:at+len(b'OWNED-SIGNATURE'*13)] = b'OWNED-SIGNATURE'*13
        struct.pack_into('<I', valid, 1580, len(b'OWNED-SIGNATURE'*13))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'boot-with-signature'; p.write_bytes(valid)
            result = a.inventory([('boot', p)], 'a', self.unpacker, Path(tmp)/'out')
            self.assertTrue(result['images'][0]['aosp_checked'])
            self.assertEqual((Path(tmp)/'out/boot/boot_signature').read_bytes(), b'OWNED-SIGNATURE'*13)

    def test_pinned_oracle_and_opaque_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'wrong'; p.write_text('raise RuntimeError("must not execute")\n')
            with self.assertRaises(a.Refused): a.aosp_module(p)
        opaque = self.inspect(b'owned opaque metadata', 'vbmeta')
        self.assertFalse(opaque['structural_validation'])
        self.assertFalse(opaque['aosp_checked'])

    def test_no_devices_symlinks_duplicate_roles_or_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); link = root/'link'; link.symlink_to(self.boot)
            fifo = root/'fifo'; os.mkfifo(fifo)
            for p in (link, fifo, root):
                with self.assertRaises((OSError, a.Refused)): a.inventory([('boot', p)], 'a', self.unpacker, root/(p.name+'-out'))
            with self.assertRaises(a.Refused): a.inventory([('boot', self.boot)]*2, 'a', self.unpacker, root/'duplicates')
            out = root/'exists'; out.mkdir(); (out/'keep').write_text('preserved')
            with self.assertRaises(a.Refused): a.inventory([('boot', self.boot)], 'a', self.unpacker, out)
            self.assertEqual((out/'keep').read_text(), 'preserved')


if __name__ == '__main__': unittest.main()
