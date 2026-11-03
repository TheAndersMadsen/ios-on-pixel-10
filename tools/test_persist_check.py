#!/usr/bin/env python3
"""persist_check against a fake adb: a host directory laid out like the phone's /dev/block and /sys, and an `adb` that runs
the tool's own shell scripts with sh, with fake `su`, `id` and `getprop`. No device is ever touched."""
import contextlib, io, json, os, shlex, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; sys.path[:0] = [str(X)]
import persist_check as PC

FAKE_ADB = r'''#!/usr/bin/env python3
import os, subprocess, sys
root = os.environ['FAKE_PHONE']; args = sys.argv[1:]
with open(os.path.join(root, 'adb.log'), 'a') as f: f.write(repr(args) + '\n')
if args == ['get-state']: print(os.environ.get('FAKE_STATE', 'device')); sys.exit(0)
assert args[0] == 'shell' and len(args) == 2, args
cmd = args[1]
for a, b in (('/dev/block/', root + '/dev/block/'), ('/sys/class/block/', root + '/sys/class/block/'), ('/sys/block/', root + '/sys/block/'), ('[ -b ', '[ -f ')):
    cmd = cmd.replace(a, b)
env = dict(os.environ, PATH=os.path.join(root, 'bin') + ':' + os.environ['PATH'])
sys.exit(subprocess.run(['sh', '-c', cmd], env=env).returncode)
'''
# Small LUN 0 in the A6 order, and a second LUN with two bootloader partitions. Blocks of 4096.
LUN0 = [('persist', 6, 9), ('misc', 10, 11), ('boot_a', 12, 15), ('init_boot_a', 16, 17), ('vbmeta_a', 18, 18), ('boot_b', 19, 22),
        ('init_boot_b', 23, 24), ('vbmeta_b', 25, 25), ('super', 26, 33), ('userdata_exp.ai', 34, 41), ('userdata', 42, 61),
        ('ios_system', 62, 317), ('ios_data', 318, 318 + 4200 - 1)]
LUN0_BLOCKS = 318 + 4200 + 5
LUN1 = [('abl_a', 6, 7), ('abl_b', 8, 9)]
LUN1_BLOCKS = 16


class FakePhone:
    def __init__(self, d, letters=('sda', 'sdb'), uid=0):
        self.d = Path(d); self.letters = letters; self.uid = uid
        (self.d / 'bin').mkdir(parents=True, exist_ok=True)
        for name, body in (('su', '#!/bin/sh\n[ "$1" = -c ] && shift\nexec sh -c "$1"\n'), ('id', f'#!/bin/sh\necho "uid={uid}(x) gid={uid}(x)"\n'),
                           ('getprop', '#!/bin/sh\ncase "$1" in sys.boot_completed) echo 1;; ro.boot.slot_suffix) echo _b;; esac\n')):
            p = self.d / 'bin' / name; p.write_text(body); p.chmod(0o755)
        self.adb = self.d / 'adb'; self.adb.write_text(FAKE_ADB); self.adb.chmod(0o755)
        self.disk = {'lun0': bytearray(os.urandom(LUN0_BLOCKS * 4096)), 'lun1': bytearray(os.urandom(LUN1_BLOCKS * 4096))}
        self.write()

    def tables(self):
        return (('lun0', self.letters[0], LUN0, LUN0_BLOCKS), ('lun1', self.letters[1], LUN1, LUN1_BLOCKS))

    def write(self):
        """(Re)build /dev/block and /sys from the disk bytes; a partition node is a copy of its extent."""
        for sub in ('dev', 'sys'): shutil.rmtree(self.d / sub, ignore_errors=True)
        byname = self.d / 'dev/block/by-name'; byname.mkdir(parents=True)
        for c in ('class/block', 'block', 'devices'): (self.d / 'sys' / c).mkdir(parents=True)
        for key, dev, table, blocks in self.tables():
            (self.d / 'dev/block' / dev).write_bytes(self.disk[key])
            dd = self.d / 'sys/devices' / dev; dd.mkdir(); (dd / 'size').write_text(f'{blocks * 8}\n')
            (self.d / 'sys/class/block' / dev).symlink_to(f'../../devices/{dev}'); (self.d / 'sys/block' / dev).symlink_to(f'../devices/{dev}')
            (byname / dev).symlink_to(f'../{dev}')  # whole-disk by-name links exist on the phone too; no start file, skipped
            for i, (name, first, last) in enumerate(table, 1):
                node = f'{dev}{i}'
                (self.d / 'dev/block' / node).write_bytes(self.disk[key][first * 4096:(last + 1) * 4096])
                pd = dd / node; pd.mkdir(); (pd / 'start').write_text(f'{first * 8}\n'); (pd / 'size').write_text(f'{(last - first + 1) * 8}\n')
                (self.d / 'sys/class/block' / node).symlink_to(f'../../devices/{dev}/{node}')
                (byname / name).symlink_to(f'../{node}')

    def poke(self, key, block, data=b'\xa5'):
        self.disk[key][block * 4096:block * 4096 + len(data)] = data; self.write()

    def part_block(self, name, rel):
        return dict((n, f) for n, f, _ in LUN0 + LUN1)[name] + rel


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.phone = FakePhone(self.tmp / 'phone')
        ref = {n: (f, l) for n, f, l in LUN0}
        self.patches = [patch.object(PC, 'REFERENCE_LUN0', ref), patch.object(PC, 'REFERENCE_LUN0_BLOCKS', LUN0_BLOCKS), patch.object(PC, 'EDGE_BLOCKS', 3)]
        for p in self.patches: p.start()
        self.env = patch.dict(os.environ, FAKE_PHONE=str(self.phone.d), ANDROID_SERIAL='fake'); self.env.start()

    def fresh(self):
        """A new fake phone with new random bytes, for one subtest."""
        self.n = getattr(self, 'n', 0) + 1; self.phone = FakePhone(self.tmp / f'phone{self.n}'); os.environ['FAKE_PHONE'] = str(self.phone.d)

    def tearDown(self):
        self.env.stop()
        for p in self.patches: p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def snap(self, name, *extra, code=0):
        out = self.tmp / f'{name}.json'
        if code == 0 and out.exists(): out.unlink()
        with contextlib.redirect_stdout(io.StringIO()) as so, contextlib.redirect_stderr(io.StringIO()) as se:
            rc = PC.main(['snapshot', '--out', str(out), '--adb', str(self.phone.adb), *extra])
        self.assertEqual(rc, code, se.getvalue() + so.getvalue()); self.last_err = se.getvalue()
        return out

    def compare(self, before, after, control=None):
        with contextlib.redirect_stdout(io.StringIO()) as so:
            rc = PC.main(['compare', '--before', str(before), '--after', str(after)] + (['--control', str(control)] if control else []))
        out = so.getvalue(); return rc, json.loads(out[:out.rindex('}') + 1])


class Snapshot(Base):
    def test_regions(self):
        s = json.loads(self.snap('pre').read_text()); R = s['regions']
        self.assertEqual(R['gpt:lun0:head']['count'], 6); self.assertEqual(R['gpt:lun0:tail'], {**R['gpt:lun0:tail'], 'first': 318 + 4200, 'count': 5})
        self.assertEqual((R['gpt:disk-of-abl_a:head']['count'], R['gpt:disk-of-abl_a:tail']['count']), (6, 6))
        self.assertEqual({k: (R[k]['first'], R[k]['count'], R[k]['cls']) for k in R if k.startswith('ios_data')},
                         {'ios_data:block0': (0, 1, 'must'), 'ios_data:test': (1, 1, 'must'), 'ios_data:slots': (2, 4098, 'persist'), 'ios_data:rest': (4100, 100, 'must')})
        self.assertNotIn('part:userdata', R); self.assertEqual((R['part:userdata:head']['count'], R['part:userdata:tail']['first']), (3, 17))
        self.assertNotIn('part:ios_data', R)
        for k in ('part:ios_system', 'part:boot_a', 'part:boot_b', 'part:vbmeta_b', 'part:init_boot_a', 'part:super'): self.assertEqual(R[k]['cls'], 'must', k)
        for k in ('part:persist', 'part:misc', 'part:abl_a', 'part:abl_b'): self.assertEqual(R[k]['cls'], 'observed', k)
        # the hash is the phone's bytes: recompute one from the fake disk
        import hashlib
        b = self.phone.part_block('ios_system', 0)
        self.assertEqual(R['part:ios_system']['sha256'], hashlib.sha256(bytes(self.phone.disk['lun0'][b * 4096:(318) * 4096])).hexdigest())
        self.assertEqual(R['gpt:lun0:tail']['sha256'], hashlib.sha256(bytes(self.phone.disk['lun0'][-5 * 4096:])).hexdigest())
        self.assertEqual(s['slot'], '_b'); self.assertNotIn('fake', json.dumps(s))  # no serial in the snapshot

    def test_every_command_reads_by_name_and_only_reads(self):
        self.snap('pre'); log = (self.phone.d / 'adb.log').read_text().splitlines()
        cmds = [eval(l) for l in log]
        for c in cmds:
            if c[0] != 'shell': continue
            PC.read_only(c[1]); self.assertNotIn('of=', c[1])
            if 'sha256sum' in c[1]: self.assertIn('readlink -f /dev/block/by-name/', c[1]); self.assertNotRegex(c[1], r'/dev/block/sd[a-z]')

    def test_quick(self):
        R = json.loads(self.snap('q', '--quick').read_text())['regions']
        self.assertNotIn('part:persist', R); self.assertNotIn('part:abl_a', R); self.assertNotIn('gpt:disk-of-abl_a:head', R)
        for k in ('part:ios_system', 'part:boot_a', 'ios_data:slots', 'part:userdata:head', 'gpt:lun0:tail'): self.assertIn(k, R)

    def test_refusals(self):
        self.snap('pre'); self.snap('pre', code=3)                           # never overwrites
        with patch.dict(os.environ, ANDROID_SERIAL=''): self.snap('x', code=3)
        with patch.dict(os.environ, FAKE_STATE='recovery'): self.snap('y', code=3)
        with patch.object(PC, 'REFERENCE_LUN0', {**PC.REFERENCE_LUN0, 'ios_data': (318, 9999)}): self.snap('z', code=3)
        self.assertIn('not the A6 table', self.last_err)
        FakePhone.__init__(self.phone, self.phone.d, uid=2000); self.snap('w', code=3); self.assertIn('not root', self.last_err)
        for n in ('x', 'y', 'z', 'w'): self.assertFalse((self.tmp / f'{n}.json').exists())

    def test_short_read_refused(self):
        self.phone.write(); (self.phone.d / 'dev/block/sda12').write_bytes(b'\0' * 4096 * 255)  # ios_system node one block short
        self.snap('s', code=3); self.assertIn('read 1044480 bytes', self.last_err)

    def test_dry_run_runs_nothing(self):
        out = self.tmp / 'dry.json'
        with contextlib.redirect_stdout(io.StringIO()) as so:
            rc = PC.main(['snapshot', '--out', str(out), '--dry-run', '--adb', str(self.tmp / 'no-such-adb')])
        self.assertEqual(rc, 0); self.assertFalse(out.exists()); self.assertFalse((self.phone.d / 'adb.log').exists())
        text = so.getvalue(); lines = [l for l in text.splitlines() if not l.startswith('#')]
        self.assertTrue(all(shlex.split(l)[0].endswith('no-such-adb') for l in lines))
        for l in lines:
            if 'sha256sum' in l: PC.read_only(shlex.split(l)[-1]); self.assertIn('by-name', l)
        self.assertIn('ios_data:slots (persist, 4098 blocks)', text); self.assertIn('bs=4096 skip=2 count=4098', text)

    def test_dry_run_reference_is_a6(self):
        for p in self.patches: p.stop()
        try:
            with contextlib.redirect_stdout(io.StringIO()) as so: PC.main(['snapshot', '--out', str(self.tmp / 'd.json'), '--dry-run'])
        finally:
            for p in self.patches: p.start()
        t = so.getvalue()
        self.assertIn('# gpt:lun0:head (must, 6 blocks)', t); self.assertIn('# gpt:lun0:tail (must, 5 blocks)', t)
        self.assertIn('# ios_data:rest (must, 2094071 blocks)', t); self.assertIn('# part:ios_system (must, 6291456 blocks)', t)
        self.assertIn('# part:userdata:tail (observed, 16384 blocks)', t); self.assertIn('bs=4096 skip=18143002 count=16384', t)


class Compare(Base):
    def test_unchanged_pass(self):
        a = self.snap('a'); b = self.snap('b'); rc, r = self.compare(a, b)
        self.assertEqual((rc, r['verdict'], r['persist_written']), (0, 'PASS', False))

    def test_slots_written_pass(self):
        a = self.snap('a')
        self.phone.poke('lun0', self.phone.part_block('ios_data', 2)); self.phone.poke('lun0', self.phone.part_block('ios_data', 4099))
        rc, r = self.compare(a, self.snap('b')); self.assertEqual((rc, r['verdict'], r['persist_written']), (0, 'PASS', True))

    def test_must_changes_fail(self):
        for name, rel in (('ios_data', 0), ('ios_data', 1), ('ios_data', 4100), ('ios_data', 4199), ('ios_system', 0), ('ios_system', 255),
                          ('boot_b', 3), ('vbmeta_a', 0), ('init_boot_b', 1), ('super', 7)):
            with self.subTest(name=name, rel=rel):
                self.fresh(); a = self.snap('a'); self.phone.poke('lun0', self.phone.part_block(name, rel))
                rc, r = self.compare(a, self.snap('b')); self.assertEqual((rc, r['verdict']), (1, 'FAIL'))

    def test_gpt_changes_fail(self):
        for key, block in (('lun0', 0), ('lun0', 3), ('lun0', LUN0_BLOCKS - 1), ('lun0', LUN0_BLOCKS - 5), ('lun1', 1), ('lun1', LUN1_BLOCKS - 1)):
            with self.subTest(key=key, block=block):
                self.fresh(); a = self.snap('a'); self.phone.poke(key, block)
                rc, r = self.compare(a, self.snap('b')); self.assertEqual(rc, 1); self.assertTrue(any(f.startswith('gpt:') for f in r['fail']))

    def test_observed_review_and_churn(self):
        a = self.snap('a'); self.phone.poke('lun0', self.phone.part_block('userdata', 0)); self.phone.poke('lun0', self.phone.part_block('persist', 1))
        ctrl = self.snap('ctrl')
        rc, r = self.compare(a, ctrl); self.assertEqual((rc, r['verdict']), (2, 'REVIEW'))   # without a control nothing explains it
        self.phone.poke('lun0', self.phone.part_block('userdata', 0), b'\x5a'); self.phone.poke('lun0', self.phone.part_block('misc', 0))
        rc, r = self.compare(a, self.snap('post'), ctrl)
        self.assertEqual((rc, r['verdict']), (2, 'REVIEW')); self.assertEqual(sorted(r['churn']), ['part:persist', 'part:userdata:head'])
        self.assertEqual([x.split(':')[0] + ':' + x.split(':')[1] for x in r['review']], ['part:misc'])

    def test_churn_alone_passes(self):
        a = self.snap('a'); self.phone.poke('lun0', self.phone.part_block('userdata', 19)); ctrl = self.snap('ctrl')
        self.phone.poke('lun0', self.phone.part_block('userdata', 19), b'\x01'); rc, r = self.compare(a, self.snap('post'), ctrl)
        self.assertEqual((rc, r['verdict'], r['churn']), (0, 'PASS', ['part:userdata:tail']))

    def test_control_must_or_slots_change_fails(self):
        for name, rel in (('boot_a', 0), ('ios_data', 2)):
            with self.subTest(name=name):
                self.fresh(); a = self.snap('a'); self.phone.poke('lun0', self.phone.part_block(name, rel)); ctrl = self.snap('ctrl')
                rc, r = self.compare(a, self.snap('post'), ctrl); self.assertEqual(rc, 1); self.assertTrue(any('control run' in f for f in r['fail']))

    def test_lun_letters_swap_pass(self):
        a = self.snap('a'); self.phone.letters = ('sdb', 'sda'); self.phone.write()
        rc, r = self.compare(a, self.snap('b')); self.assertEqual((rc, r['verdict']), (0, 'PASS'))
        self.assertNotEqual(json.loads(a.read_text())['regions']['part:ios_system']['dev'], json.loads((self.tmp / 'b.json').read_text())['regions']['part:ios_system']['dev'])

    def test_layout_and_scope_fail(self):
        a = json.loads(self.snap('a').read_text()); b = json.loads(json.dumps(a))
        b['layout']['parts']['ios_data']['first'] += 1; self.assertEqual(PC.compare(a, b)['verdict'], 'FAIL')
        b = json.loads(json.dumps(a)); del b['regions']['part:boot_a']; self.assertEqual(PC.compare(a, b)['verdict'], 'FAIL')
        b = json.loads(json.dumps(a)); b['scope'] = 'quick'; self.assertEqual(PC.compare(a, b)['verdict'], 'FAIL')
        b = json.loads(json.dumps(a)); b['regions']['ios_data:slots']['count'] = 4099; self.assertEqual(PC.compare(a, b)['verdict'], 'FAIL')


class Guard(unittest.TestCase):
    def test_read_only(self):
        for s in ('dd if=/dev/zero of=/dev/block/sda37', 'echo 1 > /proc/x', 'dd if=x seek=1', 'dd if=x conv=fsync', 'blockdev --setrw x', 'sgdisk -Z x', 'reboot', 'cat x | tee y', 'cat x >> y'):
            with self.assertRaises(PC.Refused, msg=s): PC.read_only(s)
        PC.read_only(PC.LAYOUT_SCRIPT)
        for r in PC.plan(PC.reference_layout()): PC.read_only(PC.region_script(r))


if __name__ == '__main__':
    unittest.main()
