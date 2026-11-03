#!/usr/bin/env python3
"""HOST ONLY. compose_wifi_join.py against the real A7-r3 base overlay and the kernel-source oracle (build/kernel_oracle).
Synthetic networks only: a test name and password made here, in a private temp dir. No real secret is read."""
import hashlib, importlib.util, os, stat, struct, subprocess, sys, tempfile, unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / 'tools/compose_wifi_join.py'
ORACLE = HERE / 'build/kernel_oracle'
spec = importlib.util.spec_from_file_location('cwj', TOOL)
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)
MK = C.load(C.MKOVERLAY, 'mkoverlay')
WS = C.load(C.MKWIFISECRET, 'mkwifisecret')
BASE = C.BASE.read_bytes()


def secret(tmp, text, mode=0o600):
    p = Path(tmp) / 'wifi.secret'
    p.write_bytes(text)
    os.chmod(p, mode)
    return p


def oracle(blob, mask=C.R3_MASK):
    with tempfile.NamedTemporaryFile(suffix='.ovl', delete=False) as f:
        f.write(blob)
    try:
        r = subprocess.run([str(ORACLE), f.name, hex(mask)], capture_output=True, text=True)
    finally:
        os.unlink(f.name)
    return r.returncode, r.stdout + r.stderr


class Compose(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.chmod(self.tmp, 0o700)
        self.net = WS.blob(WS.parse(secret(self.tmp, b'ssid=hk-test-net\npassword=not-a-real-password\ncountry=DK\n')))

    def test_base_pinned_and_kernel_accepts_base(self):
        self.assertEqual(hashlib.sha256(BASE).hexdigest(), C.PINNED[C.BASE])
        rc, out = oracle(BASE)
        self.assertIn('varfs: ok', out)
        self.assertIn('0 network records', out)   # the r3 image holds no network today
        self.assertEqual(rc, 1)

    def test_composed_kernel_reader(self):
        blob = C.compose(MK, BASE, self.net)
        rc, out = oracle(blob)
        self.assertEqual(rc, 0, out)
        self.assertIn('group 26 applied no', out)
        self.assertIn('wifi: network ok: ssid_len 11, open 0, have_mac 0, country DK/DK, rev -1, mode 0600 uid 0 gid 0', out)
        self.assertNotIn('hk-test-net', out)
        self.assertNotIn('not-a-real-password', out)

    def test_base_records_byte_identical_and_in_order(self):
        blob = C.compose(MK, BASE, self.net)
        a, b = C.records(MK, BASE), C.records(MK, blob)
        self.assertEqual(len(b), len(a) + 1)
        self.assertEqual([r['raw'] for r in b[:-1]], [r['raw'] for r in a])
        self.assertEqual((b[-1]['kind'], b[-1]['group'], b[-1]['mode'], b[-1]['uid'], b[-1]['gid'], b[-1]['path']),
                         ('f', 26, 0o600, 0, 0, '/private/var/hkcover/wifi/net'))
        self.assertEqual(b[-1]['data'], self.net)
        self.assertEqual(blob[24:24 + len(BASE) - 24], BASE[24:])

    def test_password_never_in_blob(self):
        blob = C.compose(MK, BASE, self.net)
        self.assertNotIn(b'not-a-real-password', blob)
        pmk = hashlib.pbkdf2_hmac('sha1', b'not-a-real-password', b'hk-test-net', 4096, 32)
        self.assertIn(pmk, blob)

    def test_open_network_and_mac(self):
        n = WS.blob(WS.parse(secret(self.tmp, b'ssid=open-one\ncountry=de\nmac=02:11:22:33:44:55\n')))
        rc, out = oracle(C.compose(MK, BASE, n))
        self.assertEqual(rc, 0, out)
        self.assertIn('open 1, have_mac 1, country DE/DE', out)

    def test_mask_that_applies_group_26_fails(self):
        # Selected, the record is an hkcover entry with no cover head: varfs rejects the whole blob (real hkov_cover_check)
        rc, out = oracle(C.compose(MK, BASE, self.net), C.R3_MASK | (1 << 26))
        self.assertIn('varfs: REJECT covers: cover entry with no head before it in its group', out)
        self.assertEqual(rc, 1)

    def test_refuse_twice(self):
        once = C.compose(MK, BASE, self.net)
        with self.assertRaises(ValueError):
            C.compose(MK, once, self.net)

    def test_refuse_bad_blob(self):
        for bad in (self.net[:-1], b'XXXX' + self.net[4:], b''):
            with self.assertRaises(ValueError):
                C.compose(MK, BASE, bad)

    def test_kernel_rejects_damage(self):
        blob = bytearray(C.compose(MK, BASE, self.net))
        blob[-60] ^= 1                                   # inside the PMK: hash must catch it
        rc, out = oracle(bytes(blob))
        self.assertIn('hash differs', out)
        self.assertEqual(rc, 1)

    def test_kernel_rejects_bad_net_records(self):
        cases = {'zero key': (76, bytes(32)), 'country': (26, b'a!'), 'flags': (25, b'\x80'), 'name length': (24, b'\x00')}
        for name, (at, val) in cases.items():
            n = bytearray(self.net)
            n[at:at + len(val)] = val
            rc, out = oracle(C.compose(MK, BASE, bytes(n)))
            self.assertEqual(rc, 1, name)
            self.assertIn('network unusable', out, name)

    def test_secret_permissions_enforced(self):
        p = secret(self.tmp, b'ssid=x\npassword=12345678\ncountry=DK\n', 0o644)
        with self.assertRaises(SystemExit):
            WS.parse(p)

    def test_cmdline(self):
        line = C.cmdline(C.MANIFEST)
        toks = line.split(' ')
        self.assertLessEqual(len(line.encode()), 1023)
        for t in C.ADD:
            self.assertEqual(toks.count(t), 1)
        for t in C.DROP:
            self.assertNotIn(t, toks)
        self.assertIn('hk_overlay=0xA0080081', toks)
        self.assertIn('blazer_ufs_root=ios_system', toks)
        self.assertIn('cpus=5', toks)
        self.assertNotIn('hk_bright=140', line)
        import json
        base = json.loads(C.MANIFEST.read_text())['cmdline'].split(' ')
        self.assertEqual(toks[-1], 'blazer_bootcpu=0x200')
        self.assertEqual(toks[-4:-1], list(C.ADD))
        self.assertEqual([t for t in base if t not in C.DROP], [t for t in toks if t not in C.ADD])

    def test_cmdline_limit_enforced(self):
        with self.assertRaises(ValueError):
            C.join_line('x' * 990 + ' hk_present_trace=1 blazer_battery_receipt=1 hk_overlay=0xA0080081')

    def test_output_refuses_overwrite_and_is_private(self):
        s = secret(self.tmp, b'ssid=hk-test-net\npassword=not-a-real-password\ncountry=DK\n')
        out = Path(self.tmp) / 'out' / 'j.ovl'
        r = subprocess.run([sys.executable, '-I', str(TOOL), 'overlay', str(s), '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('hk-test-net', r.stdout + r.stderr)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        r2 = subprocess.run([sys.executable, '-I', str(TOOL), 'overlay', str(s), '--out', str(out)], capture_output=True, text=True)
        self.assertNotEqual(r2.returncode, 0)
        self.assertEqual(oracle(out.read_bytes())[0], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
