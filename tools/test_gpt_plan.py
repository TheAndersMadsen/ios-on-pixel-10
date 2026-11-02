#!/usr/bin/env python3
"""Tests for tools/gpt_plan.py on synthetic 4096-byte-LBA disks built like the
Pixel LUN0 table (35 full entries, userdata last, backup header padding that
repeats the entry array). Optional real-data test: set GPT_PLAN_A0 to the A0
truth directory."""
import os, struct, sys, unittest, uuid, zlib
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpt_plan as G

LBA = G.LBA
DISK = uuid.UUID('54494857-4345-4148-5045-4c204c554e31')
TOTAL = 4_000_000
BASIC = uuid.UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')


def table(n=35, ud_first=100_000, media_pad=True, overlap=False):
    ents = bytearray()
    first = 6
    for i in range(n - 1):
        last = first + 255
        if overlap and i == 3: last += 300
        ents += G.entry_bytes(BASIC, uuid.uuid4(), first, last, f'p{i}')
        first = first + 256
    ents += G.entry_bytes(BASIC, uuid.uuid4(), ud_first, TOTAL - 6, 'userdata')
    acrc = zlib.crc32(bytes(ents))
    src = dict(first=6, last=TOTAL - 6, disk=DISK)
    ph = G.build_header(src, 1, TOTAL - 1, 2, n, acrc)
    bh = G.build_header(src, TOTAL - 1, 1, TOTAL - 5, n, acrc)
    arr4 = bytes(ents) + b'\0' * (4 * LBA - len(ents))
    head = b'\0' * LBA + ph + b'\0' * (LBA - 92) + arr4 + b'\0' * (2 * LBA)    # LBA 0..7
    pad = bytes(ents)[:LBA - 92] if media_pad else b''
    pad += b'\0' * (LBA - 92 - len(pad))
    tail = b'\0' * (13 * LBA) + arr4 + bh + pad                                  # 18 blocks to TOTAL
    return bytearray(head), bytearray(tail)


def disk(head, tail):
    return G.Disk(bytes(head), bytes(tail), TOTAL - 18, TOTAL)


def refix_header(buf, off, arr_crc=None):
    h = bytearray(buf[off:off + 92])
    if arr_crc is not None: struct.pack_into('<I', h, 88, arr_crc)
    h[16:20] = b'\0' * 4
    struct.pack_into('<I', h, 16, zlib.crc32(bytes(h)))
    buf[off:off + 92] = h


class T(unittest.TestCase):
    def ok(self, **kw):
        h, t = table(**kw)
        return disk(h, t), G.plan(disk(h, t), str(DISK), 1, 1)

    def test_valid_rewrite_both_variants(self):
        d, r = self.ok()
        self.assertEqual(r['table']['pad_policy'], 'entry-prefix')
        for v in ('media', 'zero'):
            n = G.check_new(d, str(DISK), r['primary'], r[f'backup_{v}'], 1, TOTAL - 5)
            self.assertEqual(len(n['entries']), 37)
            self.assertEqual(n['pad_policy'], 'entry-prefix' if v == 'media' else 'zero')
        self.assertEqual(len(r['primary']), 5 * LBA)
        self.assertEqual(len(r['backup_media']), 5 * LBA)
        lay = r['layout']
        self.assertEqual(lay['ios_data'][1], TOTAL - 6)
        self.assertEqual(lay['userdata'][1] + 1, lay['ios_system'][0])
        self.assertEqual(lay['ios_system'][1] + 1, lay['ios_data'][0])

    def test_alignment(self):
        _, r = self.ok()
        for k in ('ios_system', 'ios_data'):
            self.assertEqual(r['layout'][k][0] % G.ALIGN_LBAS, 0)
        self.assertEqual((r['layout']['ios_system'][1] + 1 - r['layout']['ios_system'][0]), G.GIB_LBAS)

    def test_overlap_refused(self):
        h, t = table(overlap=True)
        with self.assertRaisesRegex(G.Refused, 'overlaps'):
            G.plan(disk(h, t), str(DISK), 1, 1)

    def test_crc_refused(self):
        h, t = table(); h[2 * LBA + 60] ^= 1
        with self.assertRaisesRegex(G.Refused, 'CRC'):
            G.plan(disk(h, t), str(DISK), 1, 1)
        h, t = table(); h[LBA + 40] ^= 1
        with self.assertRaisesRegex(G.Refused, 'header CRC'):
            G.plan(disk(h, t), str(DISK), 1, 1)

    def test_header_mismatch_refused(self):
        h, t = table()
        off = 17 * LBA
        struct.pack_into('<Q', t, off + 48, TOTAL - 7)   # backup last usable differs
        refix_header(t, off)
        with self.assertRaisesRegex(G.Refused, 'differ in last'):
            G.plan(disk(h, t), str(DISK), 1, 1)

    def test_truncated_refused(self):
        h, t = table()
        with self.assertRaises(G.Refused):
            G.Disk(bytes(h[:5 * LBA]), bytes(t), TOTAL - 18, TOTAL)
        with self.assertRaises(G.Refused):
            G.Disk(bytes(h), bytes(t[:-LBA]), TOTAL - 18, TOTAL)
        with self.assertRaises(G.Refused):
            G.Disk(bytes(h[:-100]), bytes(t), TOTAL - 18, TOTAL)

    def test_wrong_disk_guid_refused(self):
        h, t = table()
        with self.assertRaisesRegex(G.Refused, 'disk GUID'):
            G.plan(disk(h, t), str(uuid.uuid4()), 1, 1)

    def test_byte_outside_allowed_lbas_refused(self):
        d, r = self.ok()
        with self.assertRaisesRegex(G.Refused, 'exactly LBA 1'):
            G.check_new(d, str(DISK), r['primary'] + b'\0' * LBA, r['backup_media'], 1, TOTAL - 5)
        with self.assertRaisesRegex(G.Refused, 'exactly LBA 1'):
            G.check_new(d, str(DISK), r['primary'], r['backup_media'], 2, TOTAL - 5)
        with self.assertRaisesRegex(G.Refused, 'backup bytes'):
            G.check_new(d, str(DISK), r['primary'], b'\0' * LBA + r['backup_media'], 1, TOTAL - 6)

    def test_tampered_other_entry_refused(self):
        d, r = self.ok()
        p = bytearray(r['primary'])
        arr = bytearray(r['array']); struct.pack_into('<Q', arr, 2 * 128 + 40, 5000)   # change p2 last LBA
        acrc = zlib.crc32(bytes(arr))
        p[LBA:LBA + len(arr)] = arr; refix_header(p, 0, acrc)
        b = bytearray(r['backup_zero']); b[:len(arr)] = arr; refix_header(b, 4 * LBA, acrc)
        with self.assertRaisesRegex(G.Refused, 'byte-identical|overlaps'):
            G.check_new(d, str(DISK), bytes(p), bytes(b), 1, TOTAL - 5)

    def test_foreign_padding_refused(self):
        h, t = table(); t[17 * LBA + 200] ^= 0xff
        with self.assertRaisesRegex(G.Refused, 'padding'):
            G.plan(disk(h, t), str(DISK), 1, 1)

    def test_zero_padding_accepted(self):
        h, t = table(media_pad=False)
        self.assertEqual(G.plan(disk(h, t), str(DISK), 1, 1)['table']['pad_policy'], 'zero')

    def test_too_big_refused(self):
        h, t = table()
        with self.assertRaisesRegex(G.Refused, 'smaller than 8 GiB'):
            G.plan(disk(h, t), str(DISK), 6, 6)

    def test_existing_ios_refused(self):
        d, r = self.ok()
        nd = G.Disk(bytes(d.block(0)) + r['primary'] + d.head[6 * LBA:], d.tail[:13 * LBA] + r['backup_zero'], TOTAL - 18, TOTAL)
        with self.assertRaisesRegex(G.Refused, 'empty slot|already present'):
            G.plan(nd, str(DISK), 1, 1)

    @unittest.skipUnless(os.environ.get('GPT_PLAN_A0'), 'set GPT_PLAN_A0 to the A0 truth dir')
    def test_real_a0(self):
        a0 = Path(os.environ['GPT_PLAN_A0'])
        d = G.Disk((a0 / 'lba-0-7.bin').read_bytes(), (a0 / 'lba-31146990-31147007.bin').read_bytes(), 31146990, 31147008)
        for s, dd, ud_gib in ((24, 8, 69.27), (24, 16, 61.27)):
            r = G.plan(d, '54494857-4345-4148-5045-4c204c554e31', s, dd)
            G.check_new(d, '54494857-4345-4148-5045-4c204c554e31', r['primary'], r['backup_media'], 1, 31147003)
            u = r['layout']['userdata']
            self.assertAlmostEqual((u[1] - u[0] + 1) / G.GIB_LBAS, ud_gib, places=1)
            self.assertEqual(u[0], 4597990)


if __name__ == '__main__':
    unittest.main(verbosity=1)
