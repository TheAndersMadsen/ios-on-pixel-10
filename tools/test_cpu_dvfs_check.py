#!/usr/bin/env python3
"""Synthetic DVFS identity/level/unit failures; no firmware, dumps, or device access."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cpu_dvfs_check as C

SOURCE = '''struct rung { int x; } gov_ladder[] = {
 { 20, 533, { 64, 69 }, 0, 13, 7 },
 { 13, 1536, { 229, 239 }, 17, 7, 3 },
 { 0, 3052, { 1098, 1081 }, 8, 7, 3 },
};
static const uint8_t gov_dom_top[GOV_DOMAINS] = { 0, 2, 1 };
'''
DTS = 'cpufreq-clk-domain = <0x101 0x1020203>;\n' + '\n'.join(
    f'cpu@{core << 8:x} {{\n dvfs-helper-domain-name = "{C.CPU_DOMAINS[1 if core < 5 else 2][1]}";\n}};'
    for core in range(2, 7))


def fixture():
    domains = [dict(id=i, name='unused' + str(i), level_count=0, levels=[]) for i in range(39)]
    for _, (ident, name) in C.CPU_DOMAINS.items():
        opps = [dict(level=i, mhz=0, supported=0, sw_override=0, mv=0) for i in range(24)]
        for level, mhz in ((20, 533), (13, 1536), (0, 3052)):
            opps[level].update(mhz=mhz, supported=1, mv=16383)
        domains[ident] = dict(id=ident, name=name, level_count=24, levels=opps)
    return dict(domains=domains, domain_count=39, finished=True, table_complete=True,
                verdict='LEVELS_AND_TABLE', torn_at=None, faults=[], stop=None, rule_broken=[])


class DVFSTests(unittest.TestCase):
    def test_explicit_levels_survive_frequency_sort(self):
        report = fixture()
        for domain in report['domains']:
            domain['levels'].reverse()
        result = C.validate(report, SOURCE, DTS)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['physical_acceptance'])
        self.assertFalse(result['clock_cap_change_authorized'])
        self.assertEqual([(x['explicit_level'], x['hz'], x['khz']) for x in result['checked'][:3]],
                         [(20, 533000000, 533000), (13, 1536000000, 1536000), (0, 3052000000, 3052000)])

    def test_bad_domain_identity(self):
        for field, value in (('id', 35), ('name', 'cpu1g1'), ('level_count', 25)):
            report = fixture(); report['domains'][34][field] = value
            self.assertFalse(C.validate(report, SOURCE, DTS)['ok'])
        report = fixture(); report['domains'][0]['name'] = 'cpu1g0'
        self.assertFalse(C.validate(report, SOURCE, DTS)['ok'])
        report = fixture(); report['domains'][34], report['domains'][35] = report['domains'][35], report['domains'][34]
        self.assertTrue(C.validate(report, SOURCE, DTS)['ok'])  # list position is not a domain ID

    def test_bad_levels_and_units(self):
        for field, value in (('level', 21), ('mhz', 533000), ('mhz', 533000000),
                             ('mhz', -1), ('mhz', 0), ('mhz', True), ('supported', 0),
                             ('supported', 2), ('mv', 16384), ('sw_override', 2)):
            report = fixture(); report['domains'][34]['levels'][20][field] = value
            with self.subTest(field=field, value=value): self.assertFalse(C.validate(report, SOURCE, DTS)['ok'])
        report = fixture(); report['domains'][34]['levels'].pop()
        self.assertFalse(C.validate(report, SOURCE, DTS)['ok'])
        report = fixture(); report['domains'][34]['levels'][0]['supported'] = 0
        report['domains'][34]['levels'][0]['sw_override'] = 1
        self.assertFalse(C.validate(report, SOURCE, DTS)['ok'])  # override-only never admits an OPP

    def test_bad_source(self):
        for source in (SOURCE.replace('20, 533', '20, 534'), SOURCE.replace('13, 1536', '12, 1536'),
                       SOURCE.replace('{ 0, 2, 1 }', '{ 0, 2, 2 }'),
                       SOURCE.replace('20, 533', '13, 533'), SOURCE.replace('20, 533', '20, unknown'), ''):
            self.assertFalse(C.validate(fixture(), source, DTS)['ok'])

    def test_bad_topology(self):
        for dts in (DTS.replace('0x1020203', '0x1010203'), DTS.replace('cpu1g0', 'cpu1g1'),
                    DTS.replace('cpu@200', 'cpu@100'), '', DTS.replace('0x101 ', '0x100000000 ')):
            self.assertFalse(C.validate(fixture(), SOURCE, dts)['ok'])

    def test_incomplete_protocol(self):
        for field, value in (('finished', False), ('table_complete', False), ('torn_at', 1),
                             ('faults', [1]), ('stop', {'code': 'bad'}),
                             ('rule_broken', ['bad']), ('verdict', 'TABLE_ONLY'), ('domain_count', 48)):
            report = fixture(); report[field] = value
            self.assertFalse(C.validate(report, SOURCE, DTS)['ok'])
        for report in ({}, None, [], dict(domains=None)):
            self.assertFalse(C.validate(report, SOURCE, DTS)['ok'])

    def test_changed_decoder_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            decoder = Path(tmp) / 'changed.py'
            decoder.write_text('raise RuntimeError("must not execute")')
            run = subprocess.run([sys.executable, '-I', C.__file__, '--decoder', str(decoder),
                                  '--capture', 'missing', '--ids', 'missing', '--source', 'missing', '--dts', 'missing'],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn('decoder source identity changed', run.stdout)
            self.assertNotIn('RuntimeError', run.stderr)


if __name__ == '__main__':
    unittest.main()
