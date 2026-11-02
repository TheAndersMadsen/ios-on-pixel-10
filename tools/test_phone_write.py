#!/usr/bin/env python3
"""Host tests of phone_write.py. Uses the real first-boot-r1 capture and staging.img as positive control, when present."""
import json, struct, sys, tempfile, unittest, zlib
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; sys.path.insert(0, str(X))
import phone_write as P
BS = 4096
def simg(chunks, total, header=None):
    n = len(chunks); o = bytearray(P.SPARSE.pack(*(header or (0xED26FF3A, 1, 0, 28, 12, BS)), total, n, 0))
    for k, c, d in chunks:
        o += P.CHUNK.pack(k, 0, c, {P.RAW: 12 + c * BS, P.FILL: 16, P.DONT_CARE: 12}[k]) + d
    return bytes(o)
class Sparse(unittest.TestCase):
    def run_it(self, s, img=None, **k):
        d = tempfile.mkdtemp(); a = Path(d)/'s'; a.write_bytes(s); b = None
        if img is not None: b = Path(d)/'i'; b.write_bytes(img)
        return P.walk(a, other=b, want_blocks=3, **k)
    GOOD = [(P.RAW, 1, b'A' * BS), (P.FILL, 2, bytes(4))]; IMG = b'A' * BS + bytes(2 * BS)
    def test_exact(self): self.assertEqual(self.run_it(simg(self.GOOD, 3), self.IMG)['blocks'], 3)
    def test_one_byte_differs(self):
        with self.assertRaises(P.Bad): self.run_it(simg(self.GOOD, 3), b'B' + self.IMG[1:])
    def test_longer_image(self):
        with self.assertRaises(P.Bad): self.run_it(simg(self.GOOD, 3), self.IMG + b'x')
    def test_hole_refused(self):
        with self.assertRaises(P.Bad): self.run_it(simg([(P.RAW, 1, b'A' * BS), (P.DONT_CARE, 2, b'')], 3), self.IMG)
    def test_hole_allowed_for_restore(self): self.assertEqual(self.run_it(simg([(P.RAW, 1, b'A' * BS), (P.DONT_CARE, 2, b'')], 3), allow_dont_care=True)['chunks'], 2)
    def test_nonstandard_header(self):
        with self.assertRaises(P.Bad): self.run_it(simg(self.GOOD, 3, (0xED26FF3A, 1, 0, 32, 12, BS)), self.IMG)
    def test_wrong_size(self):
        with self.assertRaises(P.Bad): self.run_it(simg([(P.RAW, 1, b'A' * BS)], 1))
    def test_trailing(self):
        with self.assertRaises(P.Bad): self.run_it(simg(self.GOOD, 3) + b'x', self.IMG)
class Compare(unittest.TestCase):
    def rec(self, n, c, rc=0): return {'reads': [dict(lun=0, lba=P.FIRST + n, crc32=c, rc=rc)]}
    def test_ok(self): self.assertTrue(P.compare(self.rec(5, 9), {5: 9}, {'5': 9})['ok'])
    def test_bad_crc(self): self.assertFalse(P.compare(self.rec(5, 8), None, {'5': 9})['ok'])
    def test_missing(self): self.assertEqual(P.compare(self.rec(5, 9), None, {'5': 9, '6': 1})['missing'], ['6'])
    def test_other_lun_ignored(self): self.assertFalse(P.compare({'reads': [dict(lun=1, lba=P.FIRST, crc32=9, rc=0)]}, None, {'0': 9})['ok'])
    def test_failed_read(self): self.assertFalse(P.compare(self.rec(5, 9, rc=3), None, {'5': 9})['ok'])
    def test_gpt(self):
        row = dict(target=True, lun=0, first_lba=P.FIRST, last_lba=P.LAST, name=P.TARGET)
        self.assertEqual(P.gpt_row({'partitions': [row]}), row)
        with self.assertRaises(P.Bad): P.gpt_row({'partitions': [row, row]})
        with self.assertRaises(P.Bad): P.gpt_row({'partitions': [dict(row, first_lba=1)]})
class Real(unittest.TestCase):
    """Physical capture: the phone held the iOS 16 region. It must match staging.img and must not match the iOS 26 root."""
    A = P.R/'laguna-usb-fix/attempts/20261101-215924-first-boot-r1'; M = P.R/'ios26-bootchain-r1/run/first-boot-r1/manifest.json'; S = P.R/'laguna-usb-fix/ufs-staging/staging.img'
    def setUp(self):
        if not all(p.exists() for p in (self.A, self.M, self.S)): self.skipTest('capture absent')
        self.man = json.loads(self.M.read_text()); self.rec = P.shim_record(self.A, self.man); self.k = P.kernel_crcs(self.A, int(self.man['ids']['stamp_nonce'], 16))
    def want(self, img):
        lbas = {r['lba'] - P.FIRST for r in self.rec['reads'] if r['lun'] == 0 and P.FIRST <= r['lba'] <= P.LAST} | set(self.k)
        return {str(n): P.block_crc(img, n)[0] for n in lbas}
    def test_gpt_row(self): self.assertEqual(P.gpt_row(self.rec)['index'], 33)
    def test_matches_what_was_on_the_phone(self):
        r = P.compare(self.rec, self.k, self.want(self.S)); self.assertTrue(r['ok'], r); self.assertEqual(r['blocks'], 12)
    def test_differs_from_another_root(self):
        o = P.R/'ios26-root-r1/build2/ios26-phone-r1.img'
        if not o.exists(): self.skipTest('root gone')
        self.assertFalse(P.compare(self.rec, self.k, self.want(o))['ok'])
    def test_fullcheck_fails_on_a_boot_without_it(self):
        import fullcheck as F
        t = P.bound_text(self.A, int(self.man['ids']['stamp_nonce'], 16)); r = F.compare(t, dict(blocks=1, whole=0, spans=[dict(first=0, blocks=1, crc=0)]))
        self.assertFalse(r['ok'])
    def test_other_nonce_unbound(self): self.assertIsNone(P.kernel_crcs(self.A, 1))
class Soak(unittest.TestCase):
    D = 'blazer-ufs-fullcheck: done, spans 128 blocks 2097152 whole crc %s, 139000 ms\r\n'
    def test_all_equal(self):
        r = P.soak_report(self.D % P.REHEARSAL_WHOLE * 9 + 'blazer-root: watch t 1300000 ms stage fullcheck reads 1 blocks 1\r\npanic(cpu 0 caller 0x1):  bsd_init: cannot mount ufsroot0, errno = 22\r\n', 9)
        self.assertTrue(r['ok'], r); self.assertEqual((r['passes'], r['last_watch_s'], r['total_s']), (9, 1300, 1251)); self.assertIn('cannot mount', r['panic'])
    def test_expected_whole(self):
        self.assertTrue(P.soak_report(self.D % '4f2b32c0' * 9, 9, '4f2b32c0')['ok']); self.assertFalse(P.soak_report(self.D % P.REHEARSAL_WHOLE * 9, 9, '4f2b32c0')['ok'])
    def test_short(self): self.assertFalse(P.soak_report(self.D % P.REHEARSAL_WHOLE * 8, 9)['ok'])
    def test_passes_differ(self): self.assertFalse(P.soak_report(self.D % P.REHEARSAL_WHOLE * 8 + self.D % 'deadbeef', 9)['ok'])
    def test_read_error(self): self.assertFalse(P.soak_report(self.D % P.REHEARSAL_WHOLE * 9 + 'blazer-ufs-fullcheck: read error lba 5 count 1 error 5, stopping\n', 9)['ok'])
class Rehearsal(unittest.TestCase):
    """Physical: 20261101-230701-fullcheck-r3-before. The phone logged the whole partition. Spans inside the iOS 16 region must equal staging.img."""
    A = P.R/'laguna-usb-fix/attempts/20261101-230701-fullcheck-r3-before'; M = P.R/'ios26-bootchain-r1/run/fullcheck-r3/manifest.json'; S = Real.S
    def setUp(self):
        if not all(p.exists() for p in (self.A, self.M, self.S)): self.skipTest('capture absent')
        import fullcheck as F; self.F = F
        self.t = P.bound_text(self.A, int(json.loads(self.M.read_text())['ids']['stamp_nonce'], 16))
    def test_whole_pass_logged(self):
        r = self.F.compare(self.t, json.loads((self.M.parent/'fullcheck.json').read_text()))
        self.assertEqual(r['spans'], 128); self.assertEqual(r['ms'], 139099); self.assertFalse(r['ok']); self.assertGreater(len(r['differ']), 100)
    def test_kernel_crc_equals_host_crc_on_real_blocks(self):
        lines = self.F.SPAN_LINE.findall(self.t.replace('\r\n', '\n')); same = 0
        with open(self.S, 'rb') as f:
            for n, first, blocks, crc in lines[:36]:
                same += zlib.crc32(f.read(16384 * BS)) == int(crc, 16)
        self.assertEqual(same, 36)
if __name__ == '__main__': unittest.main()
