#!/usr/bin/env python3
"""Tests for tools/ios_partition_flash.py on synthetic 4096-byte-LBA GPTs built with gpt_plan's own writers.
HOST only. If research/ios26-dualboot-r8/truth and the option A plan are present, one test also checks the
table that plan would leave on the phone (planned bytes, not a device read)."""
import hashlib, io, json, os, struct, sys, tempfile, unittest, uuid, zlib
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpt_plan as G
import ios_partition_flash as F
import phone_write as PW

LBA = G.LBA
DISK = uuid.UUID('54494857-4345-4148-5045-4c204c554e31')
TOTAL = 4_000_000
BASIC = uuid.UUID('ebd0a0a2-b9e5-4433-87c0-68b6b72699c7')
REPO = Path(__file__).resolve().parent.parent


def layout(sys_blocks=G.GIB_LBAS, data_blocks=G.GIB_LBAS):
    """Like the phone after A6: 33 small entries, userdata_exp.ai, userdata, ios_system, ios_data at the end."""
    e = []; first = 6
    for i in range(33):
        e.append([BASIC, f'p{i}', first, first + 255]); first += 256
    e.append([BASIC, 'userdata_exp.ai', first, first + 4095]); first += 4096
    last = TOTAL - 6
    d0 = (last + 1 - data_blocks) // G.ALIGN_LBAS * G.ALIGN_LBAS; s0 = d0 - sys_blocks
    e.append([BASIC, 'userdata', first, s0 - 1])
    e.append([G.IOS_TYPE, 'ios_system', s0, d0 - 1])
    e.append([G.IOS_TYPE, 'ios_data', d0, last])
    return e


def disk(entries, attrs=None):
    n = len(entries); arr = bytearray()
    for t, name, f, l in entries:
        b = bytearray(G.entry_bytes(t, uuid.uuid4(), f, l, name))
        if attrs and name in attrs: struct.pack_into('<Q', b, 48, attrs[name])
        arr += b
    nblk = -(-len(arr) // LBA); assert nblk <= 4
    acrc = zlib.crc32(bytes(arr)); src = dict(first=6, last=TOTAL - 6, disk=DISK)
    ph = G.build_header(src, 1, TOTAL - 1, 2, n, acrc); bh = G.build_header(src, TOTAL - 1, 1, TOTAL - 5, n, acrc)
    arr4 = bytes(arr) + b'\0' * (4 * LBA - len(arr))
    head = b'\0' * LBA + ph + b'\0' * (LBA - 92) + arr4 + b'\0' * (2 * LBA)
    tail = b'\0' * (13 * LBA) + arr4 + bh + bytes(arr)[:LBA - 92]
    return G.Disk(head, tail, TOTAL - 18, TOTAL)


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); d = Path(cls.tmp.name)
        blocks = [os.urandom(LBA) if i % 3 else bytes(LBA) for i in range(96)] + [bytes(LBA)] * 4 + [os.urandom(LBA)]
        cls.root = d / 'root.img'; cls.root.write_bytes(b''.join(blocks))
        cls.sha = hashlib.sha256(cls.root.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_check(self, entries, **kw):
        return F.check(disk(entries, kw.pop('attrs', None)), str(DISK), self.root, kw.pop('root_sha', self.sha), **kw)

    def test_valid(self):
        r = self.run_check(layout())
        self.assertEqual(r['blocks'], G.GIB_LBAS); self.assertEqual(r['root_blocks'], 101)
        self.assertEqual(r['tail_blocks'], G.GIB_LBAS - 101)
        want = hashlib.sha256(self.root.read_bytes() + bytes((G.GIB_LBAS - 101) * LBA)).hexdigest()
        self.assertEqual(r['padded_sha256'], want)
        self.assertEqual(r['dd']['bs'], 1 << 20); self.assertEqual(r['dd']['skip'] * 256, r['first_lba'])
        self.assertEqual(r['dd_root']['bs'], LBA); self.assertEqual(r['dd_root']['count'], 101)
        self.assertTrue(r['ios_data']['hackios_type'])
        self.assertEqual(r['sysfs']['start_512'], r['first_lba'] * 8)

    def test_missing_refused(self):
        e = [x for x in layout() if x[1] != 'ios_system']
        with self.assertRaisesRegex(F.Refused, 'no ios_system'):
            self.run_check(e)

    def test_duplicate_refused(self):
        e = layout(); e[-1][1] = 'ios_system'
        with self.assertRaisesRegex(F.Refused, 'duplicate|2 entries'):
            self.run_check(e)

    def test_wrong_type_refused(self):
        e = layout(); e[-2][0] = BASIC
        with self.assertRaisesRegex(F.Refused, 'type GUID'):
            self.run_check(e)

    def test_attrs_refused(self):
        with self.assertRaisesRegex(F.Refused, 'attribute'):
            self.run_check(layout(), attrs={'ios_system': 1})

    def test_overlap_refused(self):
        e = layout(); e[-3][3] = e[-2][2] + 10          # userdata runs into ios_system
        with self.assertRaisesRegex(F.Refused, 'overlap|not above'):
            self.run_check(e)
        e = layout(); e[-2][3] = e[-1][2] + 1            # ios_system runs into ios_data
        with self.assertRaisesRegex(F.Refused, 'overlap'):
            self.run_check(e)

    def test_below_userdata_refused(self):
        e = layout(); s = e.pop(-2)                       # ios_system in a gap below userdata
        ud = e[-2]; s[2], s[3] = ud[2], ud[2] + 2047; ud[2] += 2048
        e.insert(-2, s)
        with self.assertRaisesRegex(F.Refused, 'not above userdata'):
            self.run_check(e)

    def test_too_small_refused(self):
        e = layout(); e[-2][3] = e[-2][2] + 99; e[-1][2] = e[-2][3] + 1    # 100 blocks < 101
        with self.assertRaisesRegex(F.Refused, 'only 100'):
            self.run_check(e)

    def test_wrong_root_hash_refused(self):
        with self.assertRaisesRegex(F.Refused, 'not the pinned'):
            self.run_check(layout(), root_sha=F.ROOT_SHA)
        with self.assertRaisesRegex(F.Refused, 'not the pinned'):
            self.run_check(layout(), root_sha='0' * 64)

    def test_android_targets_refused(self):
        for t in ('userdata', 'userdata_exp.ai', 'USERDATA', 'userdata_a', 'blazer_persist', 'ios_data', 'boot_b'):
            with self.assertRaises(F.Refused, msg=t):
                self.run_check(layout(), target=t)
        with self.assertRaisesRegex(F.Refused, 'Android'):
            F.refuse_target('userdata_exp.ai')
        with self.assertRaisesRegex(F.Refused, 'blazer_persist'):
            F.refuse_target('blazer_persist=1')

    def test_bad_crc_refused(self):
        d = disk(layout()); h = bytearray(d.head); h[2 * LBA + 70] ^= 1
        with self.assertRaisesRegex(F.Refused, 'CRC'):
            F.check(G.Disk(bytes(h), d.tail, TOTAL - 18, TOTAL), str(DISK), self.root, self.sha)

    def test_sparse_roundtrip(self):
        r = self.run_check(layout(sys_blocks=4096))
        with tempfile.TemporaryDirectory() as t:
            s = Path(t) / 'r.simg'; F.write_sparse(self.root, r['blocks'], s)
            w = PW.walk(s, want_blocks=r['blocks'])
            self.assertEqual(w['sha256'], r['padded_sha256']); self.assertNotIn('0xcac3', w['kinds'])
            self.assertEqual(sum(w['kinds'].values()), r['blocks'])
            self.assertEqual(F.check_simg(s, r)['expands_to'], r['padded_sha256'])
            self.assertEqual(self.run_check(layout(sys_blocks=4096), simg=s)['simg']['chunks'], w['chunks'])
            s2 = Path(t) / 'short.simg'; F.write_sparse(self.root, r['blocks'] - 1, s2)
            with self.assertRaises(F.Refused):
                F.check_simg(s2, r)
            with self.assertRaises(F.Refused):
                F.write_sparse(self.root, 100, Path(t) / 'x.simg')

    def test_verify_stream(self):
        r = self.run_check(layout(sys_blocks=4096))
        good = self.root.read_bytes() + bytes((r['blocks'] - r['root_blocks']) * LBA)
        self.assertTrue(F.verify_stream(io.BytesIO(good), r)['ok'])
        bad = bytearray(good); bad[2000 * LBA + 5] = 1
        v = F.verify_stream(io.BytesIO(bytes(bad)), r)
        self.assertFalse(v['ok']); self.assertIn('first at partition block 2000', ' '.join(v['problems']))
        bad = bytearray(good); bad[7 * LBA] ^= 0xff
        self.assertIn('block 7', ' '.join(F.verify_stream(io.BytesIO(bytes(bad)), r)['problems']))
        self.assertFalse(F.verify_stream(io.BytesIO(good[:-1]), r)['ok'])
        self.assertFalse(F.verify_stream(io.BytesIO(good + b'\0'), r)['ok'])
        self.assertTrue(F.verify_stream(io.BytesIO(self.root.read_bytes()), r, image_only=True)['ok'])
        self.assertFalse(F.verify_stream(io.BytesIO(self.root.read_bytes()), r)['ok'])

    def test_root_sha_matches_image_tool(self):
        src = (REPO / 'tools/image_tool.py').read_text()
        self.assertIn(f"PHONE_ROOT_SHA = '{F.ROOT_SHA}'", src)

    @unittest.skipUnless((REPO / 'research/ios26-dualboot-r8/truth/lba-0-7.bin').exists() and
                         (REPO / 'research/ios26-dualboot-r8/gpt-plan/option-a-ios24+8/plan.json').exists(), 'A0 truth / plan not here')
    def test_planned_option_a_table(self):
        """The table option A would leave (A0 dump with the planned LBA 1..5 and backup applied): host bytes, not a device read."""
        T0 = REPO / 'research/ios26-dualboot-r8/truth'; P = REPO / 'research/ios26-dualboot-r8/gpt-plan/option-a-ios24+8'
        head = bytearray((T0 / 'lba-0-7.bin').read_bytes()); tail = bytearray((T0 / 'lba-31146990-31147007.bin').read_bytes())
        head[LBA:6 * LBA] = (P / 'gpt-new-primary.bin').read_bytes()
        tail[13 * LBA:] = (P / 'gpt-new-backup-media.bin').read_bytes()
        d = G.Disk(bytes(head), bytes(tail), 31146990, 31147008)
        t, s, ud = F.check_table(d, str(DISK))
        self.assertEqual((s['first'], s['last']), (22757376, 29048831)); self.assertEqual(ud['last'], 22757375)
        self.assertEqual(F.check_plan(d, P, s)['backup_variant'], 'media')
        self.assertEqual(F.dd_args(s['first'], s['last'] - s['first'] + 1), dict(bs=1 << 20, skip=88896, count=24576))
        with self.assertRaisesRegex(F.Refused, 'planned primary'):   # the A0 table as found is not the plan's result
            F.check_plan(G.Disk((T0 / 'lba-0-7.bin').read_bytes(), bytes(tail), 31146990, 31147008), P, s)
        with self.assertRaisesRegex(F.Refused, 'no ios_system'):
            F.check_table(G.Disk((T0 / 'lba-0-7.bin').read_bytes(), (T0 / 'lba-31146990-31147007.bin').read_bytes(), 31146990, 31147008), str(DISK))


if __name__ == '__main__':
    unittest.main(verbosity=1)
