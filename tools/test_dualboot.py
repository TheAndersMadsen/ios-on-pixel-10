#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Synthetic GPTs and end-to-end host protocol against the actual C readback core."""
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dualboot', ROOT/'tools/dualboot.py')
d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)


def disk_image(blocks=512):
    disk = bytearray(blocks*d.BLOCK)
    disk[510:512] = b'\x55\xaa'; disk[450] = 0xee
    struct.pack_into('<II', disk, 454, 1, blocks-1)
    entries = bytearray(128*128)
    for i, (name, first, last) in enumerate((('userdata', 6, 255), ('darwin', 256, 399))):
        at = i*128
        entries[at:at+16] = uuid.UUID(int=1).bytes_le
        entries[at+16:at+32] = uuid.UUID(int=i+2).bytes_le
        struct.pack_into('<QQQ', entries, at+32, first, last, 0)
        text = name.encode('utf-16-le'); entries[at+56:at+56+len(text)] = text
    for at, alternate, array in ((1, blocks-1, 2), (blocks-1, 1, blocks-5)):
        header = bytearray(d.BLOCK)
        d.GPT.pack_into(header, 0, b'EFI PART', 0x10000, 92, 0, 0, at, alternate,
                        6, blocks-6, uuid.UUID(int=9).bytes_le, array, 128, 128, zlib.crc32(entries))
        struct.pack_into('<I', header, 16, zlib.crc32(header[:92]))
        disk[at*d.BLOCK:(at+1)*d.BLOCK] = header
        disk[array*d.BLOCK:array*d.BLOCK+len(entries)] = entries
    return disk


PLANNED_LBAS = sorted([0, 1, 511] + list(range(2, 6)) + list(range(507, 511)))
PLANNED_READS = len(PLANNED_LBAS)


class MemoryReader:
    def __init__(self, disk):
        self.disk = disk
        self.total_blocks = len(disk)//d.BLOCK
    def read(self, lba, count=1):
        return bytes(self.disk[lba*d.BLOCK:(lba+count)*d.BLOCK])


def fix_header(disk, at):
    base = at*d.BLOCK
    struct.pack_into('<I', disk, base+16, 0)
    struct.pack_into('<I', disk, base+16, zlib.crc32(disk[base:base+92]))


def fix_arrays(disk):
    # Mirror changed primary entries and repair their independently stored CRCs.
    data = disk[2*d.BLOCK:6*d.BLOCK]
    disk[-5*d.BLOCK:-d.BLOCK] = data
    for at in (1, 511):
        struct.pack_into('<I', disk, at*d.BLOCK+88, zlib.crc32(data)); fix_header(disk, at)


class GptTests(unittest.TestCase):
    def test_valid_and_preserved(self):
        disk = disk_image(); before = bytes(disk)
        report, _ = d.inspect_gpt(MemoryReader(disk))
        self.assertTrue(report['gpt_copies_match'])
        self.assertFalse(report['storage_isolation_proven'])
        self.assertFalse(report['full_data_backup'])
        self.assertEqual([p['name'] for p in report['partitions']], ['userdata', 'darwin'])
        self.assertEqual(disk, before)

    def test_crc_and_truncation(self):
        for at in (510, d.BLOCK+16, 511*d.BLOCK+16, 2*d.BLOCK+60, 507*d.BLOCK+60):
            with self.subTest(at=at):
                disk = disk_image(); disk[at] ^= 1
                with self.assertRaises(d.Refused): d.inspect_gpt(MemoryReader(disk))
        with self.assertRaises(d.Refused): d.parse_header(b'\0'*91, 1, 512)

    def test_recomputed_but_invalid_geometry(self):
        for offset, value, fmt in ((24, 2, '<Q'), (32, 500, '<Q'), (40, 2, '<Q'),
                                   (48, 511, '<Q'), (72, 6, '<Q'), (80, 0, '<I'),
                                   (80, 4097, '<I'), (84, 192, '<I')):
            with self.subTest(offset=offset):
                disk = disk_image(); struct.pack_into(fmt, disk, d.BLOCK+offset, value)
                fix_header(disk, 1)
                with self.assertRaises(d.Refused): d.inspect_gpt(MemoryReader(disk))

    def test_valid_crcs_do_not_hide_overlap_or_aliases(self):
        mutations = [lambda x: struct.pack_into('<Q', x, 2*d.BLOCK+128+32, 255),
                     lambda x: struct.pack_into('<Q', x, 2*d.BLOCK+32, 5),
                     lambda x: x.__setitem__(slice(2*d.BLOCK+128+16, 2*d.BLOCK+128+32), x[2*d.BLOCK+16:2*d.BLOCK+32]),
                     lambda x: x.__setitem__(slice(2*d.BLOCK+128+56, 2*d.BLOCK+128+128), x[2*d.BLOCK+56:2*d.BLOCK+128])]
        for mutate in mutations:
            disk = disk_image(); mutate(disk); fix_arrays(disk)
            with self.assertRaises(d.Refused): d.inspect_gpt(MemoryReader(disk))

    def test_snapshot_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'capture'
            d.capture_gpt(MemoryReader(disk_image()), out)
            reader = d.SnapshotReader(out)
            report, _ = d.inspect_gpt(reader)
            self.assertEqual(report['partitions'], reader.manifest['partitions'])
            with self.assertRaises(d.Refused): reader.read(20)
            data = bytearray((out/'primary-entries.raw').read_bytes()); data[1] ^= 1
            (out/'primary-entries.raw').write_bytes(data)
            with self.assertRaises(d.Refused): d.SnapshotReader(out)

    def test_snapshot_no_path_traversal_or_holes(self):
        for bad in ('../escape', '/tmp/escape', '.', '..', ''):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)/'capture'; d.capture_gpt(MemoryReader(disk_image()), out)
                m = json.loads((out/'capture.json').read_text()); m['segments'][0]['file'] = bad
                (out/'capture.json').write_text(json.dumps(m))
                with self.assertRaises(d.Refused): d.SnapshotReader(out)

    def test_changing_table_no_capture_claim(self):
        class Changing(MemoryReader):
            calls = 0
            def read(self, lba, count=1):
                self.calls += 1
                if self.calls > 5: return b'\0'*(count*d.BLOCK)
                return super().read(lba, count)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'capture'
            with self.assertRaises(d.Refused): d.capture_gpt(Changing(disk_image()), out)
            self.assertFalse((out/'capture.json').exists())
            failure = json.loads((out/'failure.json').read_text())
            self.assertFalse(failure['ok'])
            self.assertFalse(failure['gpt_copies_match'])
            self.assertGreater(len(failure['observations']), 0)
            for observation in failure['observations']:
                self.assertEqual(d.sha((out/observation['file']).read_bytes()), observation['sha256'])

    def test_rejected_first_block_is_retained_without_read_retry(self):
        class Counted(MemoryReader):
            calls = 0
            def read(self, lba, count=1):
                self.calls += 1
                return super().read(lba, count)
        disk = disk_image(); struct.pack_into('<I', disk, 458, 0xffffffff)
        source = Counted(disk)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'failed'
            with self.assertRaises(d.Refused): d.capture_gpt(source, out)
            failure = json.loads((out/'failure.json').read_text())
            # Raw capture before parsing: the fixed plan (PMBR, both headers, both
            # declared 4-block arrays) is read exactly once; no retry, no second pass.
            self.assertEqual(source.calls, PLANNED_READS)
            self.assertEqual(len(failure['observations']), PLANNED_READS)
            self.assertEqual(sorted(o['lba'] for o in failure['observations']), PLANNED_LBAS)
            self.assertEqual((out/failure['observations'][0]['file']).read_bytes(), disk[:d.BLOCK])
            self.assertFalse((out/'capture.json').exists())
            with self.assertRaises(OSError): d.SnapshotReader(out)

    def test_saturated_pmbr_requires_explicit_matching_review_hash(self):
        disk = disk_image(); struct.pack_into('<I', disk, 458, 0xffffffff)
        source = MemoryReader(disk); reviewed = d.sha(disk[:d.BLOCK])
        for review in (None, '0'*64, 'bad'):
            with self.assertRaises(d.Refused): d.inspect_gpt(source, review)
        report, _ = d.inspect_gpt(source, reviewed)
        self.assertEqual(report['protective_mbr']['policy'], 'reviewed-linux-saturated')
        for sectors in (0, 100, 510, 512, 4095, 0xfffffffe):
            changed = bytearray(disk); struct.pack_into('<I', changed, 458, sectors)
            with self.assertRaises(d.Refused): d.inspect_gpt(MemoryReader(changed), d.sha(changed[:d.BLOCK]))
        # A reviewed saturated PMBR does not rescue bad GPT CRCs or geometry.
        disk[d.BLOCK+16] ^= 1
        with self.assertRaises(d.Refused): d.inspect_gpt(MemoryReader(disk), reviewed)

    def test_observation_corruption_and_saturated_snapshot_opt_in(self):
        disk = disk_image(); struct.pack_into('<I', disk, 458, 0xffffffff)
        reviewed = d.sha(disk[:d.BLOCK])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'capture'
            result = d.capture_gpt(MemoryReader(disk), out, reviewed_pmbr_sha256=reviewed)
            reader = d.SnapshotReader(out)
            with self.assertRaises(d.Refused): d.inspect_gpt(reader)
            self.assertTrue(d.inspect_gpt(reader, reviewed)[0]['gpt_copies_match'])
            file = out/result['observations'][0]['file']
            bad = bytearray(file.read_bytes()); bad[-1] ^= 1; file.write_bytes(bad)
            with self.assertRaises(d.Refused): d.SnapshotReader(out)

    def test_regular_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'image'; path.write_bytes(disk_image())
            link = Path(tmp)/'link'; link.symlink_to(path)
            fifo = Path(tmp)/'fifo'; os.mkfifo(fifo)
            for invalid in (link, fifo, Path(tmp)):
                with self.assertRaises((OSError, d.Refused)): d.ImageReader(invalid)
            reader = d.ImageReader(path)
            try: self.assertTrue(d.inspect_gpt(reader)[0]['gpt_copies_match'])
            finally: reader.close()

    def test_android_fstab_expansion_is_shared(self):
        fstab = b'/dev/block/by-name/userdata /data f2fs defaults wait,device=zoned:/dev/block/by-name/zoned_device,device=exp_alias:/dev/block/by-name/userdata_exp.ai\n'
        result = d.fstab_owners(fstab)
        self.assertEqual(result['live_alias_state'], 'unknown')
        self.assertIn(dict(role='exp_alias', name='userdata_exp.ai'), result['data_mounts'][0]['devices'])
        with self.assertRaises(d.Refused): d.fstab_owners(b'# no ownership evidence\n')


class CountedReader(MemoryReader):
    def __init__(self, disk):
        super().__init__(disk); self.lbas = []
    def read(self, lba, count=1):
        self.lbas.extend(range(lba, lba+count))
        return super().read(lba, count)


def pack_backup_padding(disk, start=92, source=None):
    """r5a shape: CRC-valid backup header followed by entry bytes in its reserved padding."""
    base = 511*d.BLOCK
    array = bytes(disk[507*d.BLOCK:511*d.BLOCK]) if source is None else source
    disk[base+start:base+d.BLOCK] = array[:d.BLOCK-start]


class AcquisitionTests(unittest.TestCase):
    def capture_failure(self, disk):
        source = CountedReader(disk)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'capture'
            with self.assertRaises(d.Refused) as caught: d.capture_gpt(source, out)
            self.assertFalse((out/'capture.json').exists())
            failure = json.loads((out/'failure.json').read_text())
            for o in failure['observations']:
                self.assertEqual(d.sha((out/o['file']).read_bytes()), o['sha256'])
                self.assertEqual((out/o['file']).read_bytes(), bytes(disk[o['lba']*d.BLOCK:(o['lba']+1)*d.BLOCK]))
            self.assertEqual(len(source.lbas), len(set(source.lbas)), 'no block read twice after a failure')
            return str(caught.exception), failure, source

    def test_valid_complete_gpt_reads_plan_then_confirms_once(self):
        source = CountedReader(disk_image())
        with tempfile.TemporaryDirectory() as tmp:
            report = d.capture_gpt(source, Path(tmp)/'capture')
        self.assertTrue(report['gpt_copies_match'])
        self.assertEqual(sorted(source.lbas[:PLANNED_READS]), PLANNED_LBAS)
        self.assertEqual(sorted(source.lbas[PLANNED_READS:]), PLANNED_LBAS)
        self.assertEqual(len(source.lbas), 2*PLANNED_READS)
        self.assertEqual([n.get('declared_array_lba') for n in report['acquisition']], [2, 507])

    def test_r5a_packed_backup_padding_still_refused_with_complete_arrays(self):
        disk = disk_image(); pack_backup_padding(disk)
        error, failure, source = self.capture_failure(disk)
        self.assertEqual(error, 'nonzero GPT reserved block padding')
        self.assertEqual(sorted(source.lbas), PLANNED_LBAS)
        diag = {x['header_lba']: x for x in failure['diagnostics']}
        self.assertEqual(diag[1]['padding_nonzero_bytes'], 0)
        self.assertGreater(diag[511]['padding_nonzero_bytes'], 0)
        self.assertTrue(diag[511]['padding_equals_array_prefix_of_header_1'])
        self.assertTrue(diag[511]['padding_equals_array_prefix_of_header_511'])
        self.assertEqual(diag[511]['acceptance'], 'NONE: diagnostic only')

    def test_stale_offset_or_foreign_padding_is_distinguished_and_refused(self):
        foreign = bytearray(disk_image()[507*d.BLOCK:511*d.BLOCK]); foreign[40] ^= 1
        for start, source in ((96, None), (92, bytes(foreign))):
            with self.subTest(start=start):
                disk = disk_image(); pack_backup_padding(disk, start, source)
                error, failure, _ = self.capture_failure(disk)
                self.assertEqual(error, 'nonzero GPT reserved block padding')
                diag = {x['header_lba']: x for x in failure['diagnostics']}
                self.assertFalse(diag[511]['padding_equals_array_prefix_of_header_1'])

    def test_bad_array_crc_and_mismatched_copies(self):
        disk = disk_image(); disk[507*d.BLOCK+60] ^= 1
        self.assertEqual(self.capture_failure(disk)[0], 'GPT array CRC mismatch')
        disk = disk_image(); struct.pack_into('<Q', disk, 507*d.BLOCK+128+40, 398)
        array = bytes(disk[507*d.BLOCK:511*d.BLOCK])
        struct.pack_into('<I', disk, 511*d.BLOCK+88, zlib.crc32(array)); fix_header(disk, 511)
        self.assertIn(self.capture_failure(disk)[0], ('GPT copies disagree', 'GPT entry copies differ'))

    def test_unusable_header_location_is_not_read(self):
        cases = (lambda x: x.__setitem__(511*d.BLOCK+20, x[511*d.BLOCK+20] ^ 1),           # header CRC
                 lambda x: (struct.pack_into('<Q', x, 511*d.BLOCK+72, 509), fix_header(x, 511)),  # overlaps N-1
                 lambda x: (struct.pack_into('<Q', x, 511*d.BLOCK+72, 1), fix_header(x, 511)),    # overlaps LBA1
                 lambda x: (struct.pack_into('<I', x, 511*d.BLOCK+80, 9000), fix_header(x, 511)))  # >1 MiB
        for i, mutate in enumerate(cases):
            with self.subTest(case=i):
                disk = disk_image(); mutate(disk)
                _, failure, source = self.capture_failure(disk)
                self.assertTrue(set(source.lbas) <= set(PLANNED_LBAS))
                self.assertTrue(all(0 <= l < 512 for l in source.lbas))
                self.assertIn('not acquired', failure['acquisition'][1]['declared_array'])

    def test_truncated_block_and_unacquired_reads(self):
        class Short(MemoryReader):
            def read(self, lba, count=1): return super().read(lba, count)[:-1] if lba == 511 else super().read(lba, count)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(d.Refused): d.capture_gpt(Short(disk_image()), Path(tmp)/'c')
        acquired = d.AcquiredReader(512, {0: b'\0'*d.BLOCK})
        with self.assertRaises(d.Refused): acquired.read(1)
        self.assertIsNone(d.declared_array(b'\0'*91, 512))


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('cc'): raise unittest.SkipTest('host C compiler unavailable')
        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name)
        (path/'wrapper.c').write_text('''
#include "readback.h"
static struct hk_rb_session s;
void start(unsigned enabled) { hk_rb_init(&s, enabled, 0x1234, 42); (void)hk_rb_bind(&s, 0); }
int select_block(unsigned lba) { return hk_rb_select(&s, lba); }
int complete(const unsigned char *p, int result) {
 struct hk_rb_job j; if (hk_rb_take(&s, &j)) return -1;
 return hk_rb_finish(&s, &j, result, p);
}
size_t wire(unsigned info, unsigned offset, unsigned char *out, size_t cap) {
 return hk_rb_packet(&s, info, offset, out, cap);
}
''')
        subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                        '-I'+str(ROOT/'dualboot'), str(ROOT/'dualboot/readback.c'),
                        str(path/'wrapper.c'), '-o', str(path/'core.so')], check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(path/'core.so'))
        cls.lib.start.argtypes = [ctypes.c_uint]
        cls.lib.select_block.argtypes = [ctypes.c_uint]
        cls.lib.complete.argtypes = [ctypes.c_void_p, ctypes.c_int]
        cls.lib.wire.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t]
        cls.lib.wire.restype = ctypes.c_size_t

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def device(self, corruption=None):
        lib = self.lib; lib.start(1)
        class Device:
            disk = disk_image()
            lba = None
            def ctrl_transfer(self, typ, req, value, index, length, timeout):
                if req == d.SELECT:
                    self.lba = value | index << 16
                    if lib.select_block(self.lba): raise d.Refused('device select refused')
                    block = self.disk[self.lba*d.BLOCK:(self.lba+1)*d.BLOCK]
                    lib.complete(ctypes.create_string_buffer(bytes(block)), -99 if corruption == 'error' else 0)
                    return 0
                out = ctypes.create_string_buffer(length)
                n = lib.wire(req == d.INFO, value if req == d.DATA else 0, out, length)
                data = bytearray(out.raw[:n])
                if req == d.DATA and corruption == 'bytes': data[-1] ^= 1
                if req == d.DATA and corruption == 'generation': data[48] ^= 1
                if req == d.DATA and corruption == 'nonce': data[32] ^= 1
                if req == d.DATA and corruption == 'offset': data[68] ^= 1
                if req == d.DATA and corruption == 'short': data.pop()
                return data
        return Device()

    def test_real_c_core_usb_to_gpt_snapshot(self):
        reader = d.UsbReader(self.device(), 0x1234, 512)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'capture'
            result = d.capture_gpt(reader, out)
            self.assertEqual(result['boot_identity'], dict(nonce=0x1234, entry=42, lun=0))
            report, _ = d.inspect_gpt(d.SnapshotReader(out))
            self.assertEqual(report['partitions'], result['partitions'])

    def test_corrupt_receipts_fail(self):
        for case in ('bytes', 'generation', 'nonce', 'offset', 'short', 'error'):
            with self.subTest(case=case), self.assertRaises(d.Refused):
                d.UsbReader(self.device(case), 0x1234, 512).read(1)

    def test_wrong_boot_and_out_of_bounds(self):
        with self.assertRaises(d.Refused): d.UsbReader(self.device(), 0x4321, 512).read(1)
        for lba, count in ((-1, 1), (512, 1), (511, 2), (0, 0)):
            with self.assertRaises(d.Refused): d.UsbReader(self.device(), 0x1234, 512).read(lba, count)


class ImageGateTests(unittest.TestCase):
    def test_readback_requires_readonly_console_and_no_persist(self):
        import sys
        sys.path.insert(0, str(ROOT/'tools'))
        import image_tool
        valid = 'blazer_usbcon=1 blazer_usb_readback=1'
        self.assertEqual(image_tool.phone_extra(valid), valid.split())
        for invalid in ('blazer_usb_readback=1', 'blazer_usbcon=2 blazer_usb_readback=1',
                        valid+' blazer_persist=1', valid+' blazer_persist_period=30',
                        valid+' blazer_usb_readback=1', 'blazer_usbcon=1 blazer_usb_readback=2'):
            with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                image_tool.phone_extra(invalid)


if __name__ == '__main__': unittest.main()
