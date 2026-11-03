#!/usr/bin/env python3
"""qemu_preflight host tests: boot-arg translation, console analysis and expect.yaml on synthetic run directories.
No QEMU, no phone."""
import json, sys, tempfile, unittest
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; sys.path[:0] = [str(X)]
import qemu_preflight as QP

INT1 = ('debug=0x8 serial=3 cpus=5 rd=ufsroot0 msgbuf=1048576 varfs=1 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=ios_system '
        'blazer_ufs_lun=0 blazer_deadline=900 sweetarm64e=1 blazer_touch=1 hk_overlay=0xA0080081 blazer_keys=1 hk_bright=140 '
        'blazer_netstack=1 hk_ustack=Preferences,MobilePhone blazer_bootcpu=0x200 blazer_newthing=1')

GOOD = '''TEGU-XNU EARLY 1: arm_init entered (MMU on)
blazer-root: stage t 422 ms stage pid1_exec reads 480 blocks 480 busy 10 ms max 2721 us last lba 3567972
varfs-overlay: mask 0xa0080081 of groups 0xfbffffff, 3 entries, 100 bytes, hash 00
varfs-overlay: f /private/var/a.plist 10 bytes
varfs-overlay: 1 applied
exec launchd
exec usermanagerd
exec SpringBoard
exec backboardd
SWEET FB: display on
exec PosterBoard
exec iconservicesagent
exec xpcproxy
exec xpcproxy
exec xpcproxy
exec xpcproxy
HK TOP: t=30 frames+0 cpu_ms=1: launchd[1]=1
blazer-netstack: published alone
'''


def run_dir(text, prog=True):
    d = Path(tempfile.mkdtemp()); (d/'console.log').write_text(text)
    if prog:
        n = len(text.encode()); (d/'progress.txt').write_text(''.join(f'{i} {n*i//10} 0\n' for i in range(11)))
    return d


SPEC = QP.load_expect([QP.DEFAULT_EXPECT])


class Translate(unittest.TestCase):
    def test_int1(self):
        extra, rows = QP.translate(INT1)
        act = {t: a for t, a, _ in rows}
        self.assertEqual(act['cpus=5'], 'harness'); self.assertEqual(act['rd=ufsroot0'], 'harness')
        for t in ('blazer_touch=1', 'blazer_keys=1', 'hk_bright=140', 'blazer_bootcpu=0x200', 'blazer_newthing=1'):
            self.assertEqual(act[t], 'drop', t); self.assertNotIn(t, extra.split())
        for t in ('varfs=1', 'blazer_deadline=900', 'hk_overlay=0xA0080081', 'blazer_netstack=1', 'hk_ustack=Preferences,MobilePhone'):
            self.assertIn(t, extra.split())
        self.assertIn('hk_usertrace=1', extra.split()); self.assertEqual(act['hk_usertrace=1'], 'add')
        why = dict((t, w) for t, _, w in rows)
        self.assertIn('not proven', why['blazer_newthing=1'])
        self.assertNotIn('cpus=', extra); self.assertNotIn('rd=', extra)

    def test_keep_drop_deadline(self):
        extra, _ = QP.translate(INT1, keep={'blazer_newthing'}, drop={'hk_ustack'}, deadline=1800)
        self.assertIn('blazer_newthing=1', extra.split()); self.assertNotIn('hk_ustack=Preferences,MobilePhone', extra)
        self.assertIn('blazer_deadline=1800', extra.split()); self.assertNotIn('blazer_deadline=900', extra.split())

    def test_route(self):
        flags, a = QP.harness_route(INT1); self.assertEqual(flags, ['--ufs-root', 'ios_system']); self.assertEqual(a['cpus'], '5')
        flags, _ = QP.harness_route('rd=md0 blazer_ufs_mountroot=1'); self.assertEqual(flags[0], '--route-md')


class Analyze(unittest.TestCase):
    def test_good(self):
        r = QP.analyze(run_dir(GOOD), expect=SPEC, args=QP.translate(INT1)[0])
        self.assertTrue(all(v['reached'] for v in r['milestones'].values()), r['milestones'])
        self.assertTrue(r['home_equivalent']['reached'])
        self.assertEqual(r['daemons']['xpcproxy']['respawns'], 0)
        self.assertEqual([x for x in r['findings'] if not x.startswith('note')], [])
        st = {e['id']: e['verdict'] for e in r['expect']}
        self.assertEqual(st['netstack-published'], 'PASS'); self.assertEqual(st['power-key-armed'], 'PHONE_ONLY')
        self.assertTrue(all(v in ('PASS', 'PHONE_ONLY') for v in st.values()), st)
        self.assertIn('evaluate', r['evaluator'])
        r2 = QP.analyze(run_dir(GOOD), expect=SPEC, args='varfs=1')
        self.assertEqual({e['id']: e['verdict'] for e in r2['expect']}['netstack-published'], 'N/A')

    def test_crash_loop(self):
        bad = GOOD + ''.join(f'usertrap: backboardd[{40+i}] exception 1 code 0x1 0x0: pc 0x1\nexec backboardd\n' for i in range(5))
        r = QP.analyze(run_dir(bad), expect=SPEC)
        self.assertEqual(r['daemons']['backboardd']['respawns'], 5); self.assertEqual(r['daemons']['backboardd']['crashes'], 5)
        self.assertFalse(r['home_equivalent']['reached'])
        self.assertTrue(any('crash loop: backboardd' in f for f in r['findings']))
        self.assertTrue(any(f.startswith('expect backboardd FAIL') for f in r['findings']))

    def test_truncated_comm(self):
        r = QP.analyze(run_dir(GOOD + 'exec mobile_obliterator\nusertrap: mobile_obliterat[6] exception 6 code 0x1 0x0\n'), expect=SPEC)
        self.assertEqual(r['daemons']['mobile_obliterator']['crashes'], 1); self.assertNotIn('mobile_obliterat', r['daemons'])

    def test_missing_daemon_and_panic(self):
        text = GOOD.replace('exec SpringBoard\n', '') + 'panic(cpu 0 caller 0xfffffe0007000000): boom\n'
        r = QP.analyze(run_dir(text), expect=SPEC)
        self.assertFalse(r['milestones']['SpringBoard']['reached']); self.assertEqual(len(r['panics']), 1)
        self.assertTrue(any('milestone not reached' in f and 'SpringBoard' in f for f in r['findings']))

    def test_deadline_is_not_a_fault(self):
        text = GOOD + 'panic(cpu 0 caller 0x1): blazer-root: deadline 900 s, stage x, 1 reads, 1 blocks, busy 1 ms, last lba 1 @x.c:1\n'
        r = QP.analyze(run_dir(text), expect={'expect': [], 'respawn_max': 2, 'respawn_allow': {}})
        self.assertEqual(r['panics'], []); self.assertIsNotNone(r['deadline_end'])
        self.assertEqual([x for x in r['findings'] if not x.startswith('note')], [])

    def test_bad_overlay(self):
        text = 'TEGU-XNU EARLY 1: x\npanic(cpu 0 caller 0x1): varfs-overlay: bad overlay at pa 0x1, 5 bytes: bad size/checksum @x.c:1\n'
        r = QP.analyze(run_dir(text), expect=SPEC)
        self.assertTrue(r['overlay']['bad']); self.assertTrue(any(f.startswith('overlay rejected') for f in r['findings']))

    def test_corrupt_overlay_file(self):
        d = Path(tempfile.mkdtemp()); o = d/'x.ovl'; o.write_bytes(b'HKVAROV1' + bytes(40))
        r = QP.analyze(run_dir(GOOD), overlay=str(o), mask=0xA0080081, expect=SPEC)
        self.assertTrue(any('does not decode on the host' in f for f in r['findings']))

    def test_shared_rows(self):
        spec = {'expect': [{'id': 'two-sb', 'values': [{'re': '^exec (SpringBoard)$', 'agg': 'count', 'min': 2}]},
                           {'id': 'opt', 'need': ['nothere'], 'required': False}], 'respawn_max': 2, 'respawn_allow': {}}
        r = QP.analyze(run_dir(GOOD), expect=spec)
        self.assertEqual([e['verdict'] for e in r['expect']], ['FAIL', 'FAIL'])
        self.assertEqual([f for f in r['findings'] if f.startswith('expect')], [f for f in r['findings'] if 'two-sb' in f])

    def test_baseline(self):
        base = QP.analyze(run_dir(GOOD), expect=SPEC)
        now = QP.analyze(run_dir(GOOD.replace('exec PosterBoard\n', '')), expect=SPEC)
        out = QP.compare(now, base)
        self.assertTrue(any('PosterBoard' in x for x in out))


class Images(unittest.TestCase):
    def test_chooser_follows_ios(self):
        d = Path(tempfile.mkdtemp()); ios = d/'ios'; ch = d/'ch'; ios.mkdir(); ch.mkdir()
        im = {'name': 'ios', 'image': 'aa', 'mach': 'bb', 'cmdline': INT1, 'var_overlay': None}
        (ios/'manifest.json').write_text(json.dumps(im))
        (ch/'manifest.json').write_text(json.dumps({'name': 'ch', 'kind': 'chooser-ios', 'default_entry': 'android',
                                                    'ios': {'dir': str(ios), 'image': 'aa', 'cmdline': INT1, 'name': 'ios'}}))
        info = QP.load_image(ch); self.assertTrue(info['chooser']); self.assertEqual(info['mach'], 'bb')
        (ch/'manifest.json').write_text(json.dumps({'name': 'ch', 'kind': 'chooser-ios', 'ios': {'dir': str(ios), 'image': 'zz', 'cmdline': INT1}}))
        with self.assertRaises(SystemExit): QP.load_image(ch)


if __name__ == '__main__':
    unittest.main()
