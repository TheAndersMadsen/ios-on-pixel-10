#!/usr/bin/env python3
"""HOST ONLY. compose_wifi_join.py against the real A7-r3 base overlay and the kernel-source oracle (build/kernel_oracle).
Synthetic networks only: a test name and password made here, in a private temp dir. No real secret is read.
r2: the composer writes BWN2 (PMK + passphrase) by default; BWN1 (PMK only) is what r1 carried. IEEE 802.11i-2004 H.4 vectors pin the PMK."""
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
        self.fields = WS.parse(secret(self.tmp, b'ssid=hk-test-net\npassword=not-a-real-password\ncountry=DK\n'))
        self.net = WS.blob(self.fields)          # BWN2, the default
        self.net1 = WS.blob(self.fields, 1)

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
        self.assertIn('wifi: network ok: ssid_len 11, open 0, have_mac 0, country DK/DK, rev -1, passphrase yes, mode 0600 uid 0 gid 0', out)
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

    def test_v1_password_never_in_blob(self):
        blob = C.compose(MK, BASE, self.net1)
        self.assertNotIn(b'not-a-real-password', blob)
        pmk = hashlib.pbkdf2_hmac('sha1', b'not-a-real-password', b'hk-test-net', 4096, 32)
        self.assertIn(pmk, blob)
        rc, out = oracle(blob)
        self.assertEqual(rc, 0, out)
        self.assertIn('passphrase no', out)

    def test_v2_layout(self):
        n = self.net
        self.assertEqual((len(n), n[:4], struct.unpack_from('<I', n, 4)[0]), (176, b'BWN2', 2))
        self.assertEqual(n[8:24] != self.net1[8:24], True)          # the salt is fresh each time
        self.assertEqual(n[24:108][:52], self.net1[24:108][:52])     # name, flags, country, rev, MAC, name bytes: as BWN1
        self.assertEqual(n[76:108], hashlib.pbkdf2_hmac('sha1', b'not-a-real-password', b'hk-test-net', 4096, 32))
        self.assertEqual(n[108], len(b'not-a-real-password'))
        self.assertEqual(n[109:109 + n[108]], b'not-a-real-password')
        self.assertEqual(n[109 + n[108]:], bytes(176 - 109 - n[108]))
        v = C.reader_view(MK, C.compose(MK, BASE, n))
        self.assertEqual((v['magic'], v['net_bytes'], v['has_passphrase']), ('BWN2', 176, True))

    def test_ieee_80211i_vectors(self):
        # IEEE 802.11i-2004 H.4.2/H.4.3, through the very code path the image uses
        vectors = [(b'password', b'IEEE', 'f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e'),
                   (b'ThisIsAPassword', b'ThisIsASSID', '0dc0d6eb90555ed6419756b9a15ec3e3209b63df707dd508d14581f8982721af'),
                   (b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', b'Z' * 32, None)]
        for pw, ssid, want in vectors[:2]:
            self.assertEqual(WS.pmk_of(pw, ssid).hex(), want)
            p = secret(self.tmp, b'ssid=' + ssid + b'\npassword=' + pw + b'\ncountry=DK\n')
            for version in (1, 2):
                b = WS.blob(WS.parse(p), version)
                self.assertEqual(b[76:108].hex(), want, (ssid, version))
                self.assertIn(bytes.fromhex(want), C.compose(MK, BASE, b))
        # The third: no published value to hand here, so stdlib PBKDF2 against an independent HMAC-SHA1 loop
        import hmac
        pw, ssid = vectors[2][0], vectors[2][1]
        def f(i):
            u = hmac.new(pw, ssid + struct.pack('>I', i), 'sha1').digest(); t = bytearray(u)
            for _ in range(4095):
                u = hmac.new(pw, u, 'sha1').digest(); t = bytearray(a ^ b for a, b in zip(t, u))
            return bytes(t)
        self.assertEqual(WS.pmk_of(pw, ssid), (f(1) + f(2))[:32])

    def test_secret_file_edges(self):
        # Exact bytes: no strip but the newline; a CR is refused, not kept
        for text in (b'ssid=hk-test-net\r\npassword=not-a-real-password\ncountry=DK\n',
                     b'ssid=hk-test-net\npassword=not-a-real-password\r\ncountry=DK\n'):
            with self.assertRaises(SystemExit):
                WS.parse(secret(self.tmp, text))
        f = WS.parse(secret(self.tmp, b'ssid=hk-test-net\npassword=not-a-real-password\ncountry=DK'))   # no final newline
        self.assertEqual(f['password'], b'not-a-real-password')
        f = WS.parse(secret(self.tmp, b'ssid=a b=c\npassword= spaced pass \ncountry=DK\n'))
        self.assertEqual((f['ssid'], f['password']), (b'a b=c', b' spaced pass '))
        self.assertEqual(WS.blob(f)[76:108], hashlib.pbkdf2_hmac('sha1', b' spaced pass ', b'a b=c', 4096, 32))
        for bad in (b'1234567', b'x' * 64, b'caf\xc3\xa9-pass'):
            with self.assertRaises(SystemExit):
                WS.blob(WS.parse(secret(self.tmp, b'ssid=x\npassword=' + bad + b'\ncountry=DK\n')))
        hexpsk = b'ab' * 32
        f = WS.parse(secret(self.tmp, b'ssid=x\npassword=' + hexpsk + b'\ncountry=DK\n'))
        self.assertEqual(WS.blob(f, 1)[76:108], bytes.fromhex(hexpsk.decode()))
        with self.assertRaises(SystemExit):
            WS.blob(f, 2)               # a 64-hex PSK is no passphrase

    def test_check_says_no_values(self):
        s = secret(self.tmp, b'ssid=hk-test-net\npassword=not-a-real-password\ncountry=DK\n')
        r = subprocess.run([sys.executable, '-I', str(C.MKWIFISECRET), 'check', str(s)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('file reads fine', r.stdout)
        self.assertIn('BWN2 possible: yes', r.stdout)
        for secret_bit in ('hk-test', 'not-a-real', '19', '11'):
            self.assertNotIn(secret_bit, r.stdout + r.stderr)

    def test_open_network_and_mac(self):
        for version in (1, 2):
            n = WS.blob(WS.parse(secret(self.tmp, b'ssid=open-one\ncountry=de\nmac=02:11:22:33:44:55\n')), version)
            rc, out = oracle(C.compose(MK, BASE, n))
            self.assertEqual(rc, 0, out)
            self.assertIn('open 1, have_mac 1, country DE/DE, rev -1, passphrase no', out)

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
        for bad in (self.net[:-1], b'XXXX' + self.net[4:], b'', b'BWN1' + self.net[4:], b'BWN2' + self.net1[4:]):
            with self.assertRaises(ValueError):
                C.compose(MK, BASE, bad)

    def test_kernel_rejects_damage(self):
        blob = bytearray(C.compose(MK, BASE, self.net))
        blob[-60] ^= 1                                   # inside the PMK: hash must catch it
        rc, out = oracle(bytes(blob))
        self.assertIn('hash differs', out)
        self.assertEqual(rc, 1)

    def test_kernel_rejects_bad_net_records(self):
        cases = {'zero key': (76, bytes(32)), 'country': (26, b'a!'), 'flags': (25, b'\x80'), 'name length': (24, b'\x00'),
                 'passphrase length': (108, b'\x07'), 'passphrase byte': (109, b'\x01'), 'tail': (175, b'\x01'), 'version': (4, b'\x01')}
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
