#!/usr/bin/env python3
"""Host tests for the declarative ADT patch layer (tools/adt_patch.py, tools/miniyaml.py, adt/).

Needs no research/: mkadt builds from a synthetic donor here, and the golden hashes below were made with
mkadt.py ad0f50ed (the last version with every node hard-coded) from the same donor and seed, so a pass
proves mkadt + adt/patches still emit those exact bytes. The real-image regressions (int4 and the other
ad0f50ed images) run when research/images is present and skip otherwise.
"""
import hashlib, json, os, plistlib, re, shutil, struct, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import adt  # noqa: E402
import adt_patch as P  # noqa: E402
import miniyaml as Y  # noqa: E402

ROOT = os.path.normpath(os.path.join(HERE, '..'))
INT4 = os.path.join(ROOT, 'research/images/a7-ios-system-int4')
INT5 = os.path.join(ROOT, 'research/images/a7-ios-system-int5')
SEED = bytes((i * 7) % 251 + 1 for i in range(256))
# mkadt.py ad0f50ed, synthetic donor below, SEED (research/ios26-phaseb-r1/adt-patch/RECEIPTS.md)
GOLDEN = [
    (dict(), '784065b205241f305d8497856c8eac12834eb520b26621d6f357e86b74adea88'),
    (dict(qemu=True), '73c7ffccb8159f365690cc55632d5708ec30a3c2e74ebd6b5dd73cadc74f20b0'),
    (dict(headless=True, disp0=True, cpus=5, boot_mpidr=0x200, phys_base=0x882000000, canvas=(1125, 2511), gamut='sRGB'),
     '9548bb7c71f7116ca8c6ffb3a9bafa63cec13bd319243846355fc2d7c2e0f8c0'),
    (dict(nvram=True), '53ea9bc263401c2f9bea574badb49281cf1bf4410606b8c6de24774b6d3d47ac'),
    (dict(qemu=True, phys_base=0x80000000, mem_size=0x80000000, cpu_order=[7, 0]),
     '8a262088273d31f04039d0dd20ce779b0d89e64eacfe3f21012e7c7116594abb'),
    (dict(product_children='all'), 'c7879fb82c0abe57b41df89d981cfa474c0654077a32ef451565dfde647a71fc'),
    (dict(headless=True), '9e0b0320ebb2c0e879851453c2dff0c2cb1e898e0c0821105d920b357eb40057'),
]


def N(name, props=(), kids=()):
    x = adt.Node()
    x.props = [('name', 0, name.encode() + b'\0')] + list(props)
    x.children = list(kids)
    return x


def synthetic_donor(path):
    prod = N('product', [('AAPL,phandle', 0, struct.pack('<I', 9)), ('artwork-display-gamut', 0, b'P3\0'),
                         ('product-name', 0, b'Synthetic\0'), ('placeholder', 1, b'\0' * 4)],
             [N('haptics', [('closed-loop', 0, struct.pack('<I', 1))]), N('camera', [('rear-burst', 0, b'\1\0\0\0')])])
    with open(path, 'wb') as f:
        f.write(adt.serialize(N('device-tree', [], [N('chosen'), prod])))


def tree():
    ph = lambda v: ('AAPL,phandle', 0, struct.pack('<I', v))
    return N('device-tree', [ph(1), ('compatible', 0, b'x\0')],
             [N('chosen', [ph(2), ('a', 0, b'A'), ('c', 0, b'C')]), N('arm-io', [ph(3)], [N('gic', [ph(4)])]), N('product', [ph(5)])])


def write(d, name, text):
    p = os.path.join(d, name)
    with open(p, 'w') as f:
        f.write(text)
    return p


class TempDir(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='adtpatch-')
        self.addCleanup(shutil.rmtree, self.d)


class MiniYAML(unittest.TestCase):
    def test_subset(self):
        v = Y.loads('''
# comment
a: 1
b: 0x10   # trailing
c: "q # not a comment"
d: [x, "y,z", 3]
e:
  - id: one
    k: v
  - plain
f:
- 1
- 2
g: 'it''s'
h: true
i: null
j: "#size-cells"
k: iPhone12,3
''')
        self.assertEqual(v, dict(a=1, b=16, c='q # not a comment', d=['x', 'y,z', 3], e=[dict(id='one', k='v'), 'plain'],
                                 f=[1, 2], g="it's", h=True, i=None, j='#size-cells', k='iPhone12,3'))

    def test_refusals(self):
        for bad in ('a: 1\na: 2', 'a:\n\tb: 1', 'a: &x 1', 'a: {b: 1}', 'a: |\n  x', 'a: b: c', 'a: [x, [y]]',
                    'a: 1\n---\nb: 2', 'a: "open', 'a:\n  b: 1\n c: 2'):
            with self.assertRaises(Y.YAMLError, msg=bad):
                Y.loads(bad)


class Schema(TempDir):
    def setUp(self):
        super().setUp()
        self.ident = P.load_identity()

    def entries(self, body):
        p = write(self.d, '10-t.yaml', 'schema: 1\nsubsystem: t\nentries:\n' + body)
        return P.load_patch_file(p, self.ident)

    def test_repo_files_lint(self):
        files = P.load_patches(ident=self.ident)
        self.assertGreaterEqual(len(files), 5)
        ids = [e['id'] for f in files for e in f['doc']['entries']]
        self.assertEqual(len(ids), len(set(ids)))
        for f in files:
            for e in f['doc']['entries']:
                self.assertTrue(e['reason'] and e.get('lane'), e['id'])

    def test_identity_matches_mkadt(self):
        import mkadt
        self.assertEqual(mkadt.IDENTITY, dict(compatible=('D421AP', 'iPhone12,3'), model='iPhone12,3', target_type='D421',
                                              target_sub_type='D421AP', platform_name='t8030', chip_id=0x8030, board_id=0x06,
                                              canvas=(1125, 2436), scale=3, manufacturer='Apple Inc.', ecid=0x4c47413100000001))

    def test_entry_refusals(self):
        bad = [
            '  - id: x\n    op: frob\n    path: /\n    reason: r\n',
            '  - id: x\n    op: set\n    path: /chosen\n    prop: p\n    type: u32\n    value: 1\n',          # no reason
            '  - id: x\n    op: set\n    path: chosen\n    prop: p\n    type: u32\n    value: 1\n    reason: r\n',
            '  - id: x\n    op: set\n    path: /c\n    prop: p\n    type: float\n    value: 1\n    reason: r\n',
            '  - id: x\n    op: set\n    path: /c\n    prop: p\n    type: u32\n    reason: r\n',             # no value
            '  - id: x\n    op: set\n    path: /c\n    prop: p\n    type: u32\n    value: 1\n    reason: r\n    colour: red\n',
            '  - id: x\n    op: add-node\n    path: /c/n\n    reason: r\n    after: a\n    before: b\n',
            '  - id: x\n    op: add-node\n    path: /c/n\n    reason: r\n    when:\n      fast: true\n',
            '  - id: x\n    op: add-node\n    path: /c/n\n    reason: r\n    capability: teleport\n',
            '  - id: x\n    op: add-node\n    path: /c/n\n    reason: r\n    min_build: soon\n',
            '  - id: X\n    op: delete-node\n    path: /c\n    reason: r\n',
        ]
        for b in bad:
            with self.assertRaises(SystemExit, msg=b):
                self.entries(b)

    def test_duplicate_ids_and_targets(self):
        e = '  - id: x\n    op: delete-node\n    path: /c\n    reason: r\n'
        write(self.d, '10-a.yaml', 'schema: 1\nsubsystem: a\nentries:\n' + e)
        write(self.d, '20-b.yaml', 'schema: 1\nsubsystem: b\nentries:\n' + e)
        with self.assertRaises(SystemExit):
            P.load_patches(self.d, self.ident)
        os.remove(os.path.join(self.d, '20-b.yaml'))
        write(self.d, '20-b.yaml', 'schema: 1\nsubsystem: b\nentries:\n' + e.replace('id: x', 'id: y'))
        with self.assertRaises(SystemExit):
            P.load_patches(self.d, self.ident)
        os.remove(os.path.join(self.d, '20-b.yaml'))
        write(self.d, 'b.yaml', 'schema: 1\n')
        with self.assertRaises(SystemExit):
            P.load_patches(self.d, self.ident)


class Apply(TempDir):
    def setUp(self):
        super().setUp()
        self.ident = P.load_identity()

    def run_patch(self, body, ctx=None, slots=None, root=None, auto_reason=True):
        if auto_reason:
            body = re.sub(r'(  - id: [^\n]+\n)', r'\1    reason: r\n', body)
        write(self.d, '10-t.yaml', 'schema: 1\nsubsystem: t\nentries:\n' + body)
        root = root or tree()
        rec = P.apply(root, ctx or {}, slots=slots, files=P.load_patches(self.d, self.ident), ident=self.ident)
        return root, rec

    def test_set_insert_replace_delete(self):
        root, rec = self.run_patch('''  - id: b
    op: set
    path: /chosen
    prop: b
    type: u32
    value: [1, 2]
    after: a
  - id: a
    op: set
    path: /chosen
    prop: a
    type: str
    value: $identity.model
  - id: c
    op: delete-prop
    path: /chosen
    prop: c
  - id: d
    op: set
    path: /
    prop: m
    type: pad32
    value: $identity.serial_number
    before: compatible
''')
        ch = P.find(root, '/chosen')
        self.assertEqual([k for k, _, _ in ch.props], ['name', 'AAPL,phandle', 'a', 'b'])
        self.assertEqual(ch.prop('a'), b'iPhone12,3\0')
        self.assertEqual(ch.prop('b'), struct.pack('<2I', 1, 2))
        self.assertEqual(root.props[2][0], 'm')
        self.assertEqual(root.prop('m'), b'LGA00BLAZER1'.ljust(32, b'\0'))
        self.assertEqual(rec['applied'], ['b', 'a', 'c', 'd'])

    def test_add_node_slots_and_fresh_phandles(self):
        root, rec = self.run_patch('''  - id: w
    op: add-node
    path: /arm-io/wdt
    after: gic
    props:
      - name: no-pmu
        type: u32
        value: 1
  - id: n
    op: add-node
    path: /arm-io/new
    before: gic
  - id: q
    op: add-node
    path: /quiet
    phandle: false
    props:
      - name: e
        type: empty
''', slots={'arm-io/wdt': 7, 'buttons': 8})
        aio = P.find(root, '/arm-io')
        self.assertEqual([c.name for c in aio.children], ['new', 'gic', 'wdt'])
        self.assertEqual(P.find(root, '/arm-io/wdt').prop('AAPL,phandle'), struct.pack('<I', 7))
        self.assertEqual(P.find(root, '/arm-io/new').prop('AAPL,phandle'), struct.pack('<I', 9))  # after slot 8
        self.assertIsNone(P.find(root, '/quiet').prop('AAPL,phandle'))
        self.assertEqual(P.find(root, '/quiet').prop('e'), b'')
        self.assertEqual(rec['unused_slots'], ['buttons'])

    def test_refused_edits(self):
        for body in ('  - id: x\n    op: set\n    path: /nope\n    prop: p\n    type: u32\n    value: 1\n    reason: r\n',
                     '  - id: x\n    op: set\n    path: /chosen\n    prop: p\n    type: u32\n    value: 1\n    after: zz\n    reason: r\n',
                     '  - id: x\n    op: set\n    path: /chosen\n    prop: a\n    type: u32\n    value: 1\n    after: c\n    reason: r\n',
                     '  - id: x\n    op: add-node\n    path: /chosen\n    reason: r\n',
                     '  - id: x\n    op: add-node\n    path: /no/such\n    reason: r\n',
                     '  - id: x\n    op: delete-node\n    path: /ghost\n    reason: r\n',
                     '  - id: x\n    op: delete-prop\n    path: /chosen\n    prop: zz\n    reason: r\n',
                     '  - id: x\n    op: set\n    path: /chosen\n    prop: p\n    type: u32\n    value: 0x100000000\n    reason: r\n',
                     '  - id: x\n    op: set\n    path: /chosen\n    prop: p\n    type: str\n    value: $identity.nothing\n    reason: r\n',
                     '  - id: x\n    op: add-node\n    path: /t\n    capability: torch\n    reason: r\n'):   # torch: claim no
            with self.assertRaises(SystemExit, msg=body):
                self.run_patch(body, auto_reason=False)

    def test_when_gate_and_build_range(self):
        body = '''  - id: q
    op: add-node
    path: /q
    when:
      qemu: true
  - id: g
    op: add-node
    path: /g
    gate: demo
  - id: old
    op: add-node
    path: /old
    max_build: 22A100
  - id: new
    op: add-node
    path: /new
    min_build: 23G90
'''
        root, rec = self.run_patch(body, ctx=dict(qemu=False))
        self.assertEqual(rec['applied'], ['new'])
        self.assertEqual({s['id']: s['why'] for s in rec['skipped']},
                         {'q': 'when qemu=true', 'g': 'gate demo off', 'old': 'build > 22A100'})
        root, rec = self.run_patch(body, ctx=dict(qemu=True, gates=['demo']))
        self.assertEqual(rec['applied'], ['q', 'g', 'new'])
        self.assertEqual(rec['gates'], ['demo'])
        with self.assertRaises(SystemExit):
            self.run_patch(body, ctx=dict(gates=['typo']))

    def test_capability_report(self):
        rep = P.capability_report(self.ident, {'wifi': ['x'], 'buttons': ['y'], 'display': ['z'], 'activation': ['a'],
                                               'data-protection': ['d']})
        self.assertIn('cellular', rep['overclaim'])
        self.assertNotIn('faceid', rep['overclaim'])
        self.assertEqual(rep['unbacked'], [])
        self.assertIn('wifi', P.capability_report(self.ident, {})['unbacked'])


class Mkadt(TempDir):
    def setUp(self):
        super().setUp()
        self.donor = os.path.join(self.d, 'donor.adt')
        synthetic_donor(self.donor)
        import mkadt
        self.mkadt = mkadt

    def build(self, **k):
        rec = {}
        b = adt.serialize(self.mkadt.build(seed=SEED, donor=self.donor, record=rec, **k))
        return b, rec

    def test_golden_bytes_from_hardcoded_mkadt(self):
        for k, want in GOLDEN:
            b, rec = self.build(**k)
            self.assertEqual(hashlib.sha256(b).hexdigest(), want, k)
            self.assertEqual(rec['unused_slots'], [], k)
            self.assertFalse(rec['skipped'] and any(s['why'].startswith('when') for s in rec['skipped']), k)

    def test_gates_change_only_their_nodes(self):
        base, _ = self.build()
        b, rec = self.build(gates=['wifid_wlan', 'bt_nub'])
        self.assertNotEqual(base, b)
        root = adt.parse(b)[0]
        aio = P.find(root, '/arm-io')
        self.assertEqual([c.name for c in aio.children][-3:], ['disp0', 'wlan', 'bluetooth'])
        self.assertEqual(P.find(root, '/arm-io/wlan').prop('device_type'), b'wlan\0')
        self.assertIsNone(P.find(root, '/arm-io/bluetooth').prop('AAPL,phandle'))
        self.assertTrue(P.adt_has(root, 'wlan'))
        self.assertFalse(P.adt_has(adt.parse(base)[0], 'wlan'))
        self.assertIn('arm-io.wlan', rec['applied'])
        self.assertEqual(rec['gates'], ['bt_nub', 'wifid_wlan'])
        phs = [struct.unpack('<I', v)[0] for v in P._all_props(root, 'AAPL,phandle')]
        self.assertEqual(len(phs), len(set(phs)))
        with self.assertRaises(SystemExit):
            self.build(gates=['wifid-wlan'])

    def test_verify_blob(self):
        b, rec = self.build(gates=['bt_nub'])
        rec = json.loads(json.dumps(rec))
        self.assertEqual(P.verify_blob(b, rec), ([], []))
        root = adt.parse(b)[0]
        root.children = [c for c in root.children if c.name != 'buttons']
        P.find(root, '/chosen').props = [(k, f, b'\x09\0\0\0' if k == 'chip-id' else v) for k, f, v in P.find(root, '/chosen').props]
        probs, _ = P.verify_blob(adt.serialize(root), rec)
        self.assertTrue(any('buttons' in p for p in probs) and any('chip-id' in p for p in probs), probs)
        rec2 = dict(rec, skipped=[])
        probs, _ = P.verify_blob(b, rec2)
        self.assertTrue(any('neither applied nor recorded' in p for p in probs), probs)
        rec3 = dict(rec, files={k: '0' * 64 for k in rec['files']})
        probs, notes = P.verify_blob(b, rec3)
        self.assertEqual(probs, [])
        self.assertTrue(notes and 'changed since the build' in notes[0])


class Gaps(TempDir):
    def test_scan_and_table(self):
        con = write(self.d, 'console.txt', '\n'.join([
            '03:41:00.1 [ 1.0] HKL SpringBoard[28] x IOK SpringBoard: path IODeviceTree:/arm-io/isp -> none',
            '03:41:00.1 [ 1.0] IOK backboardd: path IODeviceTree:/core-brightness -> none',
            '03:41:00.2 [ 1.0] IOK SpringBoard: matching1 <dict ID="0"><key>IONameMatch</key><string ID="1">als</string><key>IOServiceNotificationUser</key><true/></dict> -> none',
            '03:41:00.3 [ 1.0] HKL Preferences[572] bootstrap_look_up of WiFiManager server failed',
            '03:41:00.4 [ 1.0] HKL MobilePhone[9] [Connection] Error: "The connection to service named com.apple.kvsd was invalidated: Connection init failed at lookup with error 3"',
            "launchd|1970-01-01 01:16:35.623547 (user/501/com.apple.bluetoothd [63]) <Error>: Missing executable detected. Job: 'com.apple.bluetoothd'",
        ]))
        obs = P.scan_consoles([con])
        self.assertEqual(sorted(obs['adt_path']), ['IODeviceTree:/arm-io/isp', 'IODeviceTree:/core-brightness'])
        self.assertEqual(sorted(obs['name_match']), ['als'])
        self.assertEqual(sorted(obs['lookup']), ['com.apple.kvsd', 'com.apple.wifi.manager'])
        self.assertEqual(sorted(obs['missing_exe']), ['com.apple.bluetoothd'])
        pl = os.path.join(self.d, 'launchd.plist')
        jobs = ({'LaunchDaemons': {
            'w': {'Label': 'com.apple.wifid', '_LimitLoadToDeviceTree': ['wlan', 'marconi-wifi'], 'Program': '/usr/sbin/wifid', 'MachServices': {'com.apple.wifi-xpc': True}},
            'f': {'Label': 'com.apple.spaceattributiond', '_LimitLoadToDeviceTree': ['filesystems:e-apfs'], 'MachServices': {}},
            'k': {'Label': 'com.apple.syncdefaultsd', 'MachServices': {'com.apple.kvsd': True}}}})
        with open(pl, 'wb') as f:
            plistlib.dump(jobs, f)
        a = os.path.join(self.d, 'x.adt')
        with open(a, 'wb') as f:
            f.write(adt.serialize(N('device-tree', [], [N('arm-io', [], [N('wlan')]), N('filesystems', [('apfs', 0, b'')])])))
        md = P.gaps_markdown(obs, pl, a)
        self.assertIn('| com.apple.wifid | _LimitLoadToDeviceTree | `["wlan", "marconi-wifi"]` | yes |', md)
        self.assertIn('| com.apple.spaceattributiond | _LimitLoadToDeviceTree | `["filesystems:e-apfs"]` | NO |', md)
        self.assertIn('| `com.apple.kvsd` | com.apple.syncdefaultsd | - | MobilePhone |', md)
        self.assertIn('| `com.apple.wifi.manager` | com.apple.wifid (registered at run time', md)


@unittest.skipUnless(os.path.exists(os.path.join(INT4, 'laguna.adt')) and os.path.exists(os.path.join(ROOT, 'research/ios26-root-r1/apple/dt/DeviceTree.d421ap.bin')),
                     'research/images or the D421AP donor absent (CI)')
class RealImages(unittest.TestCase):
    def test_int4_byte_identical(self):
        old, new, kw = P.regress_image(INT4)
        self.assertEqual(hashlib.sha256(old).hexdigest(), 'e2472776f07c82e2d9c232bfa1377bc516d5d3c4044f133bbc17f149e9d9c8a6')
        self.assertEqual(old, new)

    @unittest.skipUnless(os.path.exists(os.path.join(INT5, 'laguna.adt')), 'int5 absent')
    def test_int5_bt_nub_byte_identical(self):
        old, new, kw = P.regress_image(INT5)
        self.assertEqual(kw['gates'], ('bt_nub',))
        self.assertEqual(old, new)


if __name__ == '__main__':
    unittest.main(verbosity=1)
