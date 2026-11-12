#!/usr/bin/env python3
"""Tests for tools/unixnu_record.py. Host only; reads docs/status.json and synthetic data.

Optional: set UNIXNU_CHECKER to UniXNU's scripts/porting-record.py to also run their checker
on the generated record (it reads its own components.toml next to the script)."""
import copy, json, os, pathlib, subprocess, sys, tempfile, tomllib, unittest
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import unixnu_record as U

STATUS = json.loads(U.STATUS.read_text())
REV = '0123456789abcdef0123456789abcdef01234567'


def areas(record):
    return {a['id']: a for a in record['area']}


class Record(unittest.TestCase):
    def test_current_status_is_valid(self):
        record = U.build(STATUS, {})
        U.validate(tomllib.loads(U.dump(record)), tomllib.loads(U.board_toml()))
        self.assertTrue(set(U.REQUIRED) <= set(areas(record)))

    def test_every_status_feature_lands_in_one_area(self):
        record = U.build(STATUS, {})
        text = json.dumps(record)
        for block in STATUS['blocks']:
            for name, _, _ in block['features']:
                self.assertIn(name + ':', text, name)

    def test_no_receipt_caps_at_implemented(self):
        cpu = areas(U.build(STATUS, {}))['cpu']
        self.assertEqual(cpu['status'], 'implemented')
        self.assertIn(U.PRIVATE, cpu['limits'])

    def test_device_receipt_promotes_only_areas_with_works(self):
        ev = {'kind': 'device', 'reference': 'docs/CPU.md', 'result': 'r', 'command': 'c', 'revision': REV}
        rec = areas(U.build(STATUS, {'cpu': [dict(ev)], 'cellular': [dict(ev)]}))
        self.assertEqual(rec['cpu']['status'], 'device-verified')
        self.assertNotIn(U.PRIVATE, rec['cpu']['limits'])
        self.assertEqual(rec['cellular']['status'], 'planned')

    def test_host_receipt(self):
        ev = {'kind': 'host', 'reference': 'docs/NATIVE-METAL.md', 'result': 'r', 'command': 'c', 'revision': REV}
        self.assertEqual(areas(U.build(STATUS, {'gpu': [ev]}))['gpu']['status'], 'host-verified')

    def test_only_open_or_out_is_planned(self):
        status = copy.deepcopy(STATUS)
        for block in status['blocks']:
            if block['name'] == 'CPU':
                block['features'] = [['X4 core', 'out', 'n'], ['Idle sleep', 'open', 'n']]
        self.assertEqual(areas(U.build(status, {}))['cpu']['status'], 'planned')

    def test_unknown_block_refused(self):
        status = copy.deepcopy(STATUS)
        status['blocks'].append({'name': 'Teleport', 'features': [['x', 'open', 'n']]})
        with self.assertRaises(SystemExit):
            U.build(status, {})

    def test_validate_rejects_bad_binding_and_identity(self):
        record = tomllib.loads(U.dump(U.build(STATUS, {})))
        board = tomllib.loads(U.board_toml())
        bad = copy.deepcopy(record)
        areas(bad)['cpu']['evidence'].append({'kind': 'device', 'reference': 'docs/CPU.md', 'result': 'r'})
        with self.assertRaises(ValueError):
            U.validate(bad, board)
        bad = copy.deepcopy(record)
        bad['device']['name'] = 'komodo'
        with self.assertRaises(ValueError):
            U.validate(bad, board)
        bad = copy.deepcopy(record)
        areas(bad)['cpu']['status'] = 'device-verified'
        with self.assertRaises(ValueError):
            U.validate(bad, board)

    def test_evidence_file_and_check_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            ev = tmp / 'ev.toml'
            ev.write_text(f'[[evidence]]\narea = "cpu"\nkind = "device"\nreference = "docs/CPU.md"\n'
                          f'result = "r"\ncommand = "c"\nrevision = "{REV}"\n')
            tool = [sys.executable, '-I', str(U.ROOT / 'tools' / 'unixnu_record.py'), str(tmp / 'out')]
            self.assertEqual(subprocess.run(tool + ['--check'], capture_output=True).returncode, 1)
            subprocess.run(tool + ['--evidence', str(ev)], check=True, capture_output=True)
            self.assertIn('device-verified', (tmp / 'out' / 'porting.toml').read_text())
            self.assertEqual(subprocess.run(tool + ['--check', '--evidence', str(ev)], capture_output=True).returncode, 0)
            ev.write_text('[[evidence]]\narea = "cpu"\nkind = "device"\nreference = "x"\nresult = "r"\n'
                          'command = "c"\nrevision = "abc"\n')
            self.assertNotEqual(subprocess.run(tool + ['--evidence', str(ev)], capture_output=True).returncode, 0)

    def test_claim_sets_level_and_needs_its_receipt(self):
        ev = {'kind': 'device', 'reference': 'docs/CPU.md', 'result': 'r', 'command': 'c', 'revision': REV}
        claims = {'gpu': {'area': 'gpu', 'status': 'implemented', 'findings': ['f'], 'limits': ['l'],
                          'next_action': ['n']},
                  'bluetooth': {'area': 'bluetooth', 'status': 'device-verified'}}
        rec = areas(U.build(STATUS, {'bluetooth': [dict(ev)], 'gpu': [dict(ev)]}, claims))
        self.assertEqual((rec['gpu']['status'], rec['gpu']['limits'], rec['gpu']['next_action']),
                         ('implemented', ['l'], ['n']))
        self.assertEqual(rec['gpu']['findings'][0], 'f')
        self.assertIn('README checklist', rec['gpu']['findings'][-1])
        self.assertEqual(rec['bluetooth']['status'], 'device-verified')
        bare = U.dump(U.build(STATUS, {}, {'cpu': {'area': 'cpu', 'status': 'device-verified'}}))
        with self.assertRaises(ValueError):
            U.validate(tomllib.loads(bare), tomllib.loads(U.board_toml()))
        with self.assertRaises(SystemExit):
            U.build(STATUS, {}, {'teleport': {'area': 'teleport', 'status': 'planned'}})

    def test_evidence_resolves_in_outdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / 'evidence').mkdir()
            (tmp / 'evidence' / 'boot.txt').write_text('receipt')
            ev = {'kind': 'device', 'reference': 'evidence/boot.txt', 'result': 'r', 'command': 'c', 'revision': REV}
            text = U.dump(U.build(STATUS, {'cpu': [ev]}))
            U.validate(tomllib.loads(text), tomllib.loads(U.board_toml()), (tmp, U.ROOT))
            with self.assertRaises(ValueError):
                U.validate(tomllib.loads(text), tomllib.loads(U.board_toml()))

    @unittest.skipUnless((U.ROOT / 'devices' / 'blazer' / 'receipts.toml').is_file(), 'no devices/blazer record')
    def test_devices_blazer_record_is_current(self):
        out = subprocess.run([sys.executable, '-I', str(U.ROOT / 'tools' / 'unixnu_record.py'),
                              str(U.ROOT / 'devices' / 'blazer'), '--check'], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_toml_text_has_no_dashes_they_forbid(self):
        self.assertNotIn('–', U.dump(U.build(STATUS, {})))

    @unittest.skipUnless(os.environ.get('UNIXNU_CHECKER'), 'UNIXNU_CHECKER not set')
    def test_unixnu_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            (tmp / 'board.toml').write_text(U.board_toml())
            (tmp / 'porting.toml').write_text(U.dump(U.build(STATUS, {})))
            blazer = U.ROOT / 'devices' / 'blazer'
            if (blazer / 'receipts.toml').is_file():
                for name in ('board.toml', 'porting.toml'):
                    (tmp / name).write_text((blazer / name).read_text())
                (tmp / 'evidence').symlink_to(blazer / 'evidence')
            for top in ('docs', 'shim', 'tools', 'adt', 'NOTES.md', 'README.md', 'HANDOFF.md'):
                if (U.ROOT / top).exists():
                    (tmp / top).symlink_to(U.ROOT / top)
            out = subprocess.run([sys.executable, '-I', os.environ['UNIXNU_CHECKER'], 'check', '--device', str(tmp)],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            self.assertIn('structured areas checked', out.stdout)


if __name__ == '__main__':
    unittest.main()
