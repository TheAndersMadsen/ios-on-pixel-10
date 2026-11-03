#!/usr/bin/env python3
"""Read-only audit admission and capture verification; no phone or Apple data."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cpu_audit as C
import image_tool as T
from test_decode_shim_stamps import build_blob as _build_blob


def build_blob(trail, **changes):
    return _build_blob(trail, **dict(dict(reason=5), **changes))

REG = (1 << 9) | (1 << 38)
TRAIL = [(i + 1, *row) for i, row in enumerate([
    (0xe6, 1, 0x200), (0xe7, 1, 0x81000000), (0xe8, 2, 0x410fd801), (0xe9, 2, 8),
    (0xea, 2, 0x30c50830), (0xeb, 2, 3), (0xec, 1, 0), (0xec, 2, REG), (0xe7, 2, 0),
    (0xe6, 2, 0x8875), (0xe6, 2, 0x410fd871), (0xe6, 2, 0x81000200),
    (0xe6, 2, 1), (0xe6, 2, 0x800000000), (0x28, 2, 0x40000000)])]
MANIFEST = dict(cpu_audit=dict(mode=1, core=0, read_only=True, a520_support_accepted=False),
                ids=dict(stamp_nonce='0xfeedface1234'),
                cmdline='cpus=5 blazer_cpu0_audit=1 blazer_bootcpu=0x200 blazer_deadline=300',
                cflags='-DTGL_CPU_AUDIT=1', extra_src='tgl_cpu_audit.c')

MANIFEST2 = copy.deepcopy(MANIFEST)
MANIFEST2['cpu_audit']['mode'] = 2
MANIFEST2['cmdline'] = MANIFEST['cmdline'].replace('blazer_cpu0_audit=1', 'blazer_cpu0_audit=2')


class AuditTests(unittest.TestCase):
    def profile(self, **changes):
        values = dict(cpu_audit=True, phone_root=True, bootcpu='0x200', cpus=5, cpu_order=None,
                      phone_deadline=300, first_boot=False, second_boot=False, test_kernel=False,
                      preflight=False, phone_args='blazer_thermal=2 blazer_thermal_panic_c=70 blazer_smp_report=1 blazer_smp_test=1',
                      touch=False, var_overlay=None, var_overlay_sha=None, args=None, md0=None, md1=None, dpu=False)
        values.update(changes)
        return SimpleNamespace(**values)

    def test_profile(self):
        self.assertTrue(T.cpu_audit_profile(self.profile()))
        self.assertFalse(T.cpu_audit_profile(SimpleNamespace()))
        cases = [dict(bootcpu=None), dict(bootcpu='0x300'), dict(cpus=7), dict(cpus=1),
                 dict(cpu_order='5,6,2,3,4,1,0'), dict(phone_deadline=None), dict(phone_deadline=900),
                 dict(phone_root=False), dict(first_boot=True), dict(second_boot=True),
                 dict(preflight=True), dict(test_kernel=True), dict(touch=True), dict(dpu=True),
                 dict(var_overlay='x'), dict(md0='x'), dict(phone_args='blazer_thermal=1'),
                 dict(phone_args=self.profile().phone_args + ' blazer_persist=1'),
                 dict(phone_args=self.profile().phone_args + ' blazer_gpu_tipc=5')]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(SystemExit):
                T.cpu_audit_profile(self.profile(**change))
        for token in ('blazer_cpu0_audit=1', 'blazer_cpu0_audit=2', 'blazer_cpu0_off=2'):
            with self.assertRaises(SystemExit): T.phone_extra(token)

    def test_actual_c(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            exe = str(Path(tmp) / 'audit')
            subprocess.run(['/usr/bin/cc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-DTGL_FASTCORE=1', '-DTGL_CPU_AUDIT=1',
                            '-DTGL_CPU_AUDIT_HOST=1', '-DTGL_FC_HOST=1', '-I' + str(root / 'shim'),
                            str(root / 'tools/test_cpu_audit.c'), str(root / 'shim/tgl_cpu_audit.c'),
                            str(root / 'shim/tgl_fastcore.c'), '-o', exe], check=True)
            output = subprocess.check_output([exe], text=True)
            records = json.loads(next(line[6:] for line in output.splitlines() if line.startswith('TRACE ')))
            # The real EL-drop continuation is assembly; model its last stamp/header only.
            records.append([0x28, 2, 0x40000000])
            trail = [(i + 1, *record) for i, record in enumerate(records)]
            result = C.verify(build_blob(trail), MANIFEST)
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['a520_support_accepted'])
            # Mode 2: the actual C's Errata ABI records decode, and still accept nothing.
            records = json.loads(next(line[7:] for line in output.splitlines() if line.startswith('TRACE2 ')))
            records.append([0x28, 2, 0x40000000])
            trail = [(i + 1, *record) for i, record in enumerate(records)]
            result = C.verify(build_blob(trail), MANIFEST2)
            self.assertTrue(result['ok'], result)
            self.assertFalse(result['a520_support_accepted'])
            abi = result['errata_abi']
            self.assertEqual(abi['version_text'], '1.0')
            self.assertEqual(abi['errata']['3685825'], 'affected')
            self.assertEqual(abi['errata']['2630792'], 'not-affected')
            self.assertEqual(len(abi['errata']), 7)
            # A mode-2 trail under a mode-1 manifest (and the reverse) is refused.
            self.assertFalse(C.verify(build_blob(trail), MANIFEST)['ok'])
            self.assertFalse(C.verify(build_blob(TRAIL), MANIFEST2)['ok'])

    def test_mode2_firmware_without_abi(self):
        em = [(0xed, 1, 0), (0xed, 2, 0xffffffffffffffff)]
        trail = [(i + 1, *row) for i, row in enumerate([r[1:] for r in TRAIL[:8]] + em + [r[1:] for r in TRAIL[8:]])]
        result = C.verify(build_blob(trail), MANIFEST2)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['errata_abi']['version_text'], 'not-supported')
        self.assertEqual(result['errata_abi']['errata'], {})
        # A hang inside the SMC leaves only the ENTER: incomplete, never a verdict.
        trail = [(i + 1, *row) for i, row in enumerate([r[1:] for r in TRAIL[:8]] + em[:1] + [r[1:] for r in TRAIL[8:]])]
        self.assertFalse(C.verify(build_blob(trail), MANIFEST2)['ok'])

    def test_pass_is_only_a_prerequisite(self):
        result = C.verify(build_blob(TRAIL), MANIFEST)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['a520_support_accepted'])

    def test_missing_bits(self):
        for bit in (9, 38):
            trail = list(TRAIL); trail[7] = (8, 0xec, 2, REG & ~(1 << bit))
            result = C.verify(build_blob(trail), MANIFEST)
            self.assertTrue(result['audit_complete']); self.assertFalse(result['ok'])

    def test_bad_capture(self):
        for idx in range(len(TRAIL)):
            trail = list(TRAIL); del trail[idx]
            with self.subTest(missing=idx): self.assertFalse(C.verify(build_blob(trail), MANIFEST)['ok'])
        for idx, field, value in ((0, 3, 0x100), (2, 3, 0x410fd871), (3, 3, 4),
                                  (4, 3, 0x30c51830), (6, 3, 1), (8, 3, 1), (8, 2, 0x10),
                                  (11, 3, 0x81000300), (12, 3, 0), (13, 3, 0x800000100)):
            trail = list(TRAIL); row = list(trail[idx]); row[field] = value; trail[idx] = tuple(row)
            with self.subTest(idx=idx, value=value): self.assertFalse(C.verify(build_blob(trail), MANIFEST)['ok'])
        self.assertFalse(C.verify(build_blob(TRAIL, nonce=1), MANIFEST)['ok'])
        self.assertFalse(C.verify(build_blob(TRAIL, count=129), MANIFEST)['ok'])
        self.assertFalse(C.verify(build_blob(TRAIL, abi=1), MANIFEST)['ok'])
        self.assertFalse(C.verify(b'', MANIFEST)['ok'])
        self.assertFalse(C.verify(build_blob(TRAIL, reason=1), MANIFEST)['ok'])
        repeated = TRAIL + [(16, 0xe7, 1, 0)]
        self.assertFalse(C.verify(build_blob(repeated), MANIFEST)['ok'])

    def test_bad_manifest(self):
        for key in ('cpu_audit', 'cflags', 'extra_src', 'ids', 'cmdline'):
            man = copy.deepcopy(MANIFEST); del man[key]
            with self.subTest(key=key): self.assertFalse(C.verify(build_blob(TRAIL), man)['ok'])
        man = copy.deepcopy(MANIFEST); man['cmdline'] += ' cpus=7'
        self.assertFalse(C.verify(build_blob(TRAIL), man)['ok'])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / 'capture'; man = Path(tmp) / 'manifest.json'
            raw.write_bytes(build_blob(TRAIL)); man.write_text(json.dumps(MANIFEST))
            run = subprocess.run([sys.executable, '-I', str(Path(C.__file__)), str(raw), str(man)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertFalse(json.loads(run.stdout)['a520_support_accepted'])


if __name__ == '__main__':
    unittest.main()
