#!/usr/bin/env python3
"""Read-only real-capture regressions + targeted journal/dump corruption tests.

python3 -I tools/test_live_profile.py
Private captures/Apple artifacts are optional; absent sources skip those tests.
Never uses USB or launches a guest. The replay oracle compiles the actual pure C
header once, with ASan/UBSan, not a second policy implementation.
"""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('live_profile', HERE / 'live_profile.py')
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
REPO = live.repo_path()
CAPTURES = REPO / 'research/ios26-fleet/resume-20261102'
ATTEMPTS = REPO / 'research/laguna-usb-fix/attempts'
MANIFESTS = REPO / 'research/ios26-bootchain-r1/run'
DUMPS = {n: ATTEMPTS / a / 'ramdump/kernel.log' for n, a in (
    ('live', '20261102-095609-phone-p29-live-r1'), ('profile', '20261102-101134-phone-p29-profile-r1'))}


def capture(test, name, symbols=None):
    path = CAPTURES / f'p29-{name}.raw'
    manifest = MANIFESTS / f'phone-p29-{name}-r1/manifest.json'
    if not path.exists() or not manifest.exists():
        test.skipTest('private p29 capture/manifest absent')
    schedule, _ = live.load_schedule(manifest, None)
    analyzer = live.Analyzer(symbols, schedule)
    journal = live.Journal(path)
    for off, data, host in journal.poll(final=True):
        analyzer.feed(off, data, host)
    return analyzer, journal


class CaptureTests(unittest.TestCase):
    def test_profile_real_trace_counts_and_kernel_clock(self):
        analyzer, journal = capture(self, 'profile')
        r = analyzer.report()
        self.assertEqual((r['script']['tokens_observed'], r['script']['done']['events']), (66, 1569))
        self.assertEqual(r['script']['state'], 'observed_complete')
        self.assertEqual(r['script']['errors'], [])
        self.assertEqual((r['script']['done']['max_late_us'], r['script']['done']['max_call_us']), (2216, 2021))
        # Token heads don't cover all events: never substitute their maximum for done's.
        self.assertEqual(r['script']['max_token_late_us'], 1173)
        self.assertEqual(r['windows'][0]['kernel_s'], [634, 635])
        self.assertIsNone(r['windows'][0]['start_s'])
        self.assertEqual(journal.bytes, 967660)
        w = next(w for w in r['windows'] if w['kernel_s'][0] == 814)
        self.assertEqual((w['start_s'], w['duration_bounds_s'], w['frames_delta']), ([784, 785], [29, 31], 160))
        self.assertEqual(w['cpu_ms_per_counter_increment']['backboardd[22]'], 294.125)
        self.assertNotIn('fps', w)
        self.assertTrue(w['script_may_overlap'])
        self.assertTrue(all(p['state'] == 'observed_complete' for p in r['phases']))

    def test_live_real_interleaved_top_and_single_abort_pid(self):
        analyzer, _ = capture(self, 'live')
        r = analyzer.report()
        self.assertEqual((r['script']['tokens_observed'], r['script']['done']['events']), (14, 169))
        w = next(w for w in r['windows'] if w['kernel_s'][0] == 1582)
        self.assertFalse(w['task_list_complete'])
        self.assertEqual((w['frames_delta'], w['cpu_ms']), (30, 40503))
        self.assertEqual(r['crash_report_lines']['backboardd'], 4)
        self.assertEqual(r['crash_affected_pids']['backboardd'], [22])
        self.assertIn(102, r['task_pids']['backboardd'])
        self.assertFalse(any(r['kind'] == 'crash' and r['name'] == 'backboardd' and r['pid'] == 102 for r in r['records']))

    def test_real_dump_reconstruction_has_exactly_one_copy_and_verified_epoch(self):
        for name in ('live', 'profile'):
            with self.subTest(name=name):
                analyzer, journal = capture(self, name)
                if not DUMPS[name].exists():
                    self.skipTest('private dump absent')
                summary = json.loads(Path(str(journal.raw) + '.json').read_text())
                expected = {k: summary['last_status'][k] for k in ('nonce', 'entry_t', 'hz')}
                verified = live.verify_capture(journal, DUMPS[name], expected)
                self.assertEqual(verified['compared_bytes'], journal.bytes)
                self.assertEqual(verified['not_read_before_reset'], 479)
                self.assertEqual([e['termination'] for e in verified['termination']], ['deadline_panic'])
                segments, metadata = live.decode_dump(DUMPS[name], expected)
                self.assertEqual(sum(len(data) for _, data in segments), metadata['total'])
                canonical = live.Analyzer(schedule=analyzer.schedule)
                for off, payload in segments:
                    canonical.feed(off, payload)
                self.assertEqual(canonical.report()['script']['tokens_observed'], len(analyzer.tokens))
                # All records completely received live are byte-position identical.
                fields = ('kind', 'offset', 'end_offset', 'seq', 'event', 'us', 'kernel_s')
                key = lambda r: {k: r[k] for k in fields if k in r}
                self.assertEqual([key(r) for r in analyzer.records],
                                 [key(r) for r in canonical.records if r['end_offset'] <= journal.end])
                self.assertEqual(canonical.gaps, [])
                self.assertEqual([e['termination'] for e in canonical.report()['termination']], ['deadline_panic'])

    def test_real_foreign_boot_and_corrupt_overlap_are_refused(self):
        analyzer, journal = capture(self, 'profile')
        if not all(p.exists() for p in DUMPS.values()):
            self.skipTest('private dumps absent')
        summary = json.loads(Path(str(journal.raw) + '.json').read_text())
        expected = {k: summary['last_status'][k] for k in ('nonce', 'entry_t', 'hz')}
        with self.assertRaisesRegex(ValueError, 'epoch mismatch'):
            live.verify_capture(journal, DUMPS['live'], expected)
        data = bytearray(DUMPS['live'].read_bytes())
        # Corrupt a byte in the duplicated head/tail overlap, rather than random garbage.
        first = 484924
        data[12 + len(live.STAGE0) + first + 12] ^= 1
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'corrupt.log'
            p.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'overlap mismatch'):
                live.decode_dump(p)
            p.write_bytes(data[:live.RING_OFF + 128])
            with self.assertRaisesRegex(ValueError, 'truncated inside'):
                live.decode_dump(p)

    def test_real_partial_script_reports_incomplete_phases_without_fabricated_idle(self):
        analyzer, _ = capture(self, 'profile')
        raw = (CAPTURES / 'p29-profile.raw').read_bytes()
        cutoff = analyzer.tokens[-2]['end_offset'] + 8
        partial = live.Analyzer(schedule=analyzer.schedule)
        partial.feed(0, raw[:cutoff])
        report = partial.report()
        self.assertEqual(report['script']['tokens_observed'], 65)
        self.assertIsNone(report['script']['done'])
        self.assertEqual(report['script']['state'], 'incomplete')
        self.assertEqual(report['phases'][-1]['state'], 'incomplete')
        self.assertIsNone(report['phases'][-1]['issue_span_s'][1])
        self.assertFalse(any('idle' in p['name'] for p in report['phases']))

    def test_real_follow_cli_and_offline_cli_agree(self):
        analyzer, journal = capture(self, 'profile')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            cmd = [sys.executable, '-I', str(HERE / 'live_profile.py'), '--raw', str(journal.raw),
                   '--manifest', str(MANIFESTS / 'phone-p29-profile-r1/manifest.json'), '--follow',
                   '--no-symbols', '--events', '--json', str(output)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            events = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(sum(e['kind'] == 'token' for e in events), 66)
            report = json.loads(output.read_text())
            self.assertEqual(report['script'], analyzer.report()['script'])
            self.assertEqual(report['source']['reads'], 3126)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name) / 'capture.raw'
        self.times = Path(str(self.raw) + '.times')

    def tearDown(self):
        self.tmp.cleanup()

    def test_partial_journal_commit_waits_then_reads_once(self):
        self.raw.write_bytes(b'hello\nworld\n')
        self.times.write_bytes(b'0.1\t0\t6\n0.2\t6')
        journal = live.Journal(self.raw)
        self.assertEqual(journal.poll(), [(0, b'hello\n', 0.1)])
        self.assertEqual(journal.poll(), [])
        with self.assertRaisesRegex(ValueError, 'missing newline'):
            journal.poll(final=True)
        with self.times.open('ab') as source:
            source.write(b'\t6\n')
        self.assertEqual(journal.poll(final=True), [(6, b'world\n', 0.2)])
        self.assertEqual(journal.poll(final=True), [])

    def test_committed_raw_truncation_and_replaced_epoch_fail(self):
        self.raw.write_bytes(b'hello\n')
        self.times.write_text('0.1\t0\t7\n')
        with self.assertRaisesRegex(ValueError, 'truncated relative'):
            live.Journal(self.raw).poll(final=True)
        self.times.write_text('0.1\t0\t6\n')
        journal = live.Journal(self.raw)
        journal.poll(final=True)
        self.raw.write_bytes(b'other\n')
        with self.assertRaisesRegex(ValueError, 'prefix changed'):
            journal.poll()
        self.raw.write_bytes(b'h')
        with self.assertRaisesRegex(ValueError, 'truncated while'):
            journal.poll()

    def test_clock_reset_overlap_nonfinite_and_negative_are_refused(self):
        self.raw.write_bytes(b'hello\nworld\n')
        for rows in ('1\t0\t6\n0\t6\t6\n', '1\t0\t6\n2\t0\t6\n', 'nan\t0\t6\n', '-1\t0\t6\n'):
            with self.subTest(rows=rows):
                self.times.write_text(rows)
                with self.assertRaisesRegex(ValueError, 'invalid .times'):
                    live.Journal(self.raw).poll(final=True)

    def test_sparse_holes_never_become_text_or_splice_a_line(self):
        line0 = b'HK UITRACE token seq=0 event=0 tok=0 op=h callback_us=1000000 begin_us=1000001 end_us=1000002 late_us=1\n'
        line1 = line0.replace(b'seq=0 event=0', b'seq=1 event=2').replace(b'100000', b'200000')
        cut = 37
        with self.raw.open('wb') as source:
            source.write(line0[:cut])
            source.seek(2048)
            source.write(line0[cut:] + line1)
        self.times.write_text(f'0.1\t0\t{cut}\n0.2\t2048\t{len(line0) - cut + len(line1)}\n')
        journal, analyzer = live.Journal(self.raw), live.Analyzer()
        for off, payload, host in journal.poll(final=True):
            analyzer.feed(off, payload, host)
        self.assertEqual([r['seq'] for r in analyzer.tokens], [1])
        report = analyzer.report()
        self.assertEqual(report['gaps'][0]['bytes'], 2048 - cut)
        self.assertEqual(report['script']['state'], 'incomplete')
        self.assertIn('missing trace sequences', report['script']['errors'])

    def test_partial_last_line_is_not_a_completed_event_and_clock_regression_fails(self):
        analyzer = live.Analyzer()
        analyzer.feed(0, b'HK TOP: t=600 frames+0 cpu_ms=10: launchd[1]=10\nHK TOP: t=630')
        self.assertEqual(len(analyzer.tops), 1)
        self.assertGreater(analyzer.report()['trailing_partial_bytes'], 0)
        with self.assertRaisesRegex(ValueError, 'clock moved backwards'):
            analyzer.line('HK TOP: t=30 frames+0 cpu_ms=10:', 100, 150, None)

    def test_brackets_do_not_cross_holes_and_repeated_dump_is_refused(self):
        analyzer = live.Analyzer()
        first = b'HK TOP: every 30 s\nHK TOP: t=600 frames+0 cpu_ms=0:\nexec SpringBoard\n'
        analyzer.feed(0, first)
        analyzer.feed(1000, b'fragment\nexec Preferences\nHK TOP: t=630 frames+0 cpu_ms=0:\n')
        report = analyzer.report()
        sb = next(r for r in report['records'] if r.get('name') == 'SpringBoard')
        prefs = next(r for r in report['records'] if r.get('name') == 'Preferences')
        self.assertEqual(sb['adjacent_kernel_stamps_s'], [600, None])
        self.assertEqual(prefs['adjacent_kernel_stamps_s'], [None, 631])
        with self.assertRaisesRegex(ValueError, 'second HK TOP start'):
            analyzer.line('HK TOP: every 30 s', 2000, 2010, None)

    def test_concurrent_writers_can_print_earlier_stamps_without_becoming_another_boot(self):
        analyzer = live.Analyzer()
        analyzer.feed(0, b'HK TOP: t=600 frames+0 cpu_ms=0:\nblazer-perf: t=598 example\nexec SpringBoard\nHK TOP: t=630 frames+0 cpu_ms=0:\n')
        self.assertEqual(len(analyzer.tops), 2)
        self.assertIn('out of order', analyzer.report()['warnings'][0]['reason'])

    def test_report_output_cannot_replace_capture_or_journal_sidecars(self):
        self.raw.write_bytes(b'HK TOP: every 30 s\n')
        self.times.write_text(f'0\t0\t{self.raw.stat().st_size}\n')
        before = self.times.read_bytes()
        result = subprocess.run([sys.executable, '-I', str(HERE / 'live_profile.py'), '--raw', str(self.raw),
                                 '--json', str(self.times), '--no-symbols'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertIn('must not overwrite', result.stderr)
        self.assertEqual(self.times.read_bytes(), before)


class SymbolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cache = REPO / 'research/ios26-debug-r1/mnt/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64e'
        dis = REPO / 'research/ios26-root-r1/apple/dis/QuartzCore.s'
        cls.symbols = live.Symbols(cache, dis) if cache.exists() and dis.exists() else None

    @classmethod
    def tearDownClass(cls):
        if cls.symbols:
            cls.symbols.close()

    def test_current_cache_without_symbols_resolves_three_real_sampler_pcs(self):
        if not self.symbols:
            self.skipTest('private cache/disassembly absent')
        analyzer, _ = capture(self, 'profile', self.symbols)
        samplers = [h['stack'][0] for h in analyzer.report()['hogs'] if 'image_sampler<' in h['stack'][0].get('symbol', '')]
        self.assertEqual([s['unslid'] for s in samplers], ['0x184129b58', '0x1841298f8', '0x1841298f8'])
        for symbol in samplers:
            self.assertEqual(symbol['status'], 'disassembly_label')
            self.assertIn('current cache', symbol['label_validation'])
            self.assertTrue(symbol['image'].endswith('/QuartzCore'))
        self.assertEqual(self.symbols.resolve(0x104bb1000, 0x1349c000, 0x104bb0000)['status'], 'main_relative_unresolved')
        self.assertEqual(self.symbols.resolve(0, 0x1349c000, 0x104bb0000)['status'], 'unresolved')

    def test_wrong_disassembly_bytes_and_addresses_outside_function_are_not_labels(self):
        if not self.symbols:
            self.skipTest('private cache/disassembly absent')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'QuartzCore.s'
            p.write_text('wrong function():\n0x184129b58:  00 00 00 00   nop\n')
            labels = live.Labels(p)
            self.assertIsNone(labels.lookup(0x184129b5c))
            symbols = live.Symbols.__new__(live.Symbols)
            symbols.cache, symbols.labels, symbols.memo = self.symbols.cache, labels, {}
            result = symbols.resolve(0x1975c5b58, 0x1349c000, 0x104bb0000)
            self.assertEqual(result['status'], 'cache_image_only')
            self.assertNotIn('symbol', result)
            self.assertIn('differ', result['label_rejected'])


class ReplayOracleTests(unittest.TestCase):
    def test_expectations_match_actual_current_c_replay_for_both_real_manifests(self):
        header = REPO / 'research/ios26-release-r1/work/xnu/iokit/Kernel/arm/hid/hk_ui_replay.h'
        if not header.exists():
            self.skipTest('current release pure replay source absent')
        code = '''#include <stdio.h>
#include "hk_ui_replay.h"
int main(int argc, char **argv) {
 struct hk_ui_script s; struct hk_ui_event e; unsigned seq=0, event=0, ms=0;
 hk_ui_canvas_h=2511;
 if (argc!=2 || !hk_ui_parse(argv[1], &s)) return 2;
 while (s.tok<s.n) {
  unsigned tok=s.tok, sub=s.sub; char op=s.t[tok].op;
  if (!hk_ui_next(&s,&e)) return 3;
  if (!sub) printf("%u %u %u %c %u\\n",seq++,event,tok,op,ms);
  event++; ms+=e.delay_ms;
 }
 printf("done %u %u %u\\n",seq,event,ms); return 0;
}'''
        with tempfile.TemporaryDirectory() as tmp:
            source, exe = Path(tmp) / 'oracle.c', Path(tmp) / 'oracle'
            source.write_text(code)
            built = subprocess.run(['cc', '-std=c11', '-fsanitize=address,undefined', '-I', str(header.parent), str(source), '-o', str(exe)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stderr)
            for name in ('profile', 'live'):
                manifest = MANIFESTS / f'phone-p29-{name}-r1/manifest.json'
                if not manifest.exists():
                    self.skipTest('private manifest absent')
                schedule, _ = live.load_schedule(manifest, None)
                result = subprocess.run([str(exe), schedule['value'].split('=', 1)[1]], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = result.stdout.splitlines()
                expected = [f"{r['seq']} {r['event']} {r['tok']} {r['op']} {r['nominal_ms']}" for r in schedule['executions']]
                expected.append(f"done {len(schedule['executions'])} {schedule['events']} {schedule['duration_ms']}")
                self.assertEqual(rows, expected)



class PresentationTests(unittest.TestCase):
    @staticmethod
    def event(seq=1, us=120, stage='layer_copy', gen=0, bytes_=16, rc=1, status=0, fe=0):
        return (f'HK PRESENT event v=1 seq={seq} us={us} stage={stage} id=1 swap=7 gen={gen} '
                f'queue_us=100 begin_us=110 bytes={bytes_} layer=0 plane=0 rc={rc} status={status} fe={fe} observed=3\n').encode()

    def test_observations_keep_bytes_stamps_and_no_input_causality(self):
        raw=(self.event()+self.event(2,130,'submitted',1,16,0)+
             self.event(3,150,'fetch_layer0',1,0,0,2,0x40))
        a=live.Analyzer()
        for at in range(0,len(raw),11):a.feed(at,raw[at:at+11],0.3)
        r=a.report();events=r['presentation']['observations']
        self.assertEqual([e['stage'] for e in events],['layer_copy','submitted','fetch_layer0'])
        self.assertEqual([e['us'] for e in events],[120,130,150])
        self.assertEqual(r['presentation']['glass_timing'],'unavailable')
        self.assertEqual(r['presentation']['input_causality'],'unavailable')
        for e in events:
            self.assertEqual(raw[e['offset']:e['end_offset']].count(b'\n'),1)
            self.assertEqual(e['host_received_s'],0.3)
            self.assertNotIn('fps',e)
            self.assertNotIn('touch_latency_us',e)

    def test_trace_lock_order_may_differ_from_console_order(self):
        a=live.Analyzer();a.feed(0,self.event(2,130)+self.event(1,120))
        self.assertEqual([e['seq'] for e in a.records],[2,1])
        self.assertTrue(a.report()['warnings'])
        with self.assertRaisesRegex(ValueError,'duplicate presentation'):
            a.feed(a.end,self.event(1,140))

    def test_success_needs_actual_boundary_evidence(self):
        for line in (self.event(us=109), self.event(stage='layer_copy',rc=0),
                     self.event(stage='layer_copy',bytes_=0),
                     self.event(stage='submitted',gen=1,rc=1),
                     self.event(stage='fetch_layer0',gen=1,bytes_=0,rc=0,status=0,fe=0x40),
                     self.event(stage='fetch_layer0',gen=1,bytes_=0,rc=0,status=2,fe=0),
                     self.event(stage='fetch_layer0',gen=1,bytes_=0,rc=0,status=2,fe=0x1040),
                     self.event(stage='fetch_layer0',gen=1,bytes_=0,rc=0,status=2,fe=0x40).replace(b'observed=3',b'observed=0')):
            with self.subTest(line=line),self.assertRaises(ValueError):live.Analyzer().feed(0,line)
        a=live.Analyzer();a.feed(0,self.event(stage='fetch_unproved',gen=1,bytes_=0,rc=0,status=2,fe=0))
        self.assertEqual(a.records[0]['stage'],'fetch_unproved')

    def test_config_counter_bounds_truncation_and_holes(self):
        config=b'HK PRESENT config v=1 us=90 every=32 events_max=448 reports_max=64 clock=mach_absolute_us glass=unavailable\n'
        a=live.Analyzer();a.feed(0,config)
        with self.assertRaisesRegex(ValueError,'second presentation config'):a.feed(a.end,config)
        values={k:0 for k in live.PRESENT_COUNTER_KEYS};values.update(seq=1,us=150,reports=1,events=448)
        line=lambda:('HK PRESENT counters v=1 '+' '.join(f'{k}={v}' for k,v in values.items())+'\n').encode()
        a=live.Analyzer();a.feed(0,line());self.assertEqual(a.records[0]['events'],448)
        values['events']=449
        with self.assertRaisesRegex(ValueError,'bounds'):live.Analyzer().feed(0,line())
        raw=self.event();a=live.Analyzer();a.feed(0,raw[:-1]);self.assertFalse(a.records)
        a.feed(len(raw)+10,b'incomplete\n'+self.event(2));self.assertEqual(len(a.records),1)
        self.assertTrue(a.gaps)
        a=live.Analyzer();a.feed(0,raw.replace(b'fe=0',b'fe=0garbage'))
        self.assertFalse(a.records);self.assertTrue(a.warnings)

    def test_raw_cli_uses_same_journal_epoch_and_offsets(self):
        raw=self.event()+self.event(2,150,'fetch_unproved',1,0,0,2,0)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'synthetic-host.raw';path.write_bytes(raw)
            Path(str(path)+'.times').write_text(f'0.25\t0\t{len(raw)}\n')
            epoch=dict(nonce=123,entry_t=456,hz=24000000)
            Path(str(path)+'.json').write_text(json.dumps(dict(bytes=len(raw),final_offset=len(raw),reads=1,last_status=epoch)))
            result=subprocess.run([sys.executable,'-I',str(HERE/'live_profile.py'),'--raw',str(path),'--no-symbols'],
                                  capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            r=json.loads(result.stdout)
            self.assertEqual(r['source']['epoch'],epoch)
            self.assertEqual([e['offset'] for e in r['presentation']['observations']],[0,len(self.event())])
            self.assertEqual(r['presentation']['observations'][1]['stage'],'fetch_unproved')


MANUAL_RAW = REPO / 'research/ios26-opt-20261102/parent/art-container-15m-r1.raw'
MANUAL_MANIFEST = MANIFESTS / 'phone-p29-art-container-15m-r1/manifest.json'
MANUAL_DUMP = ATTEMPTS / '20261102-115426-phone-p29-art-container-15m-r1/ramdump/kernel.log'


def finished_manual_capture(test):
    # This is an actual frozen, completed attempt, never an active p31r1 path.
    paths = (MANUAL_RAW, Path(str(MANUAL_RAW) + '.times'), Path(str(MANUAL_RAW) + '.json'),
             MANUAL_MANIFEST, MANUAL_DUMP)
    if not all(p.is_file() for p in paths):
        test.skipTest('completed private art-container capture/manifest/dump absent')
    expected = ('6fe8a0f73a180c4e879c1a22cbdc959a45cb6b3b545baef37ea53c1986c67028',
                '21bd7da7545247a57f4681b164131a9b5c39a1425e447be57c0d977d303b50a5')
    test.assertEqual((live.digest(MANUAL_RAW), live.digest(MANUAL_DUMP)), expected)
    summary = json.loads(paths[2].read_text())
    test.assertEqual((summary['bytes'], summary['final_offset'], summary['reads'], summary['end']),
                     (1450057, 1450057, 4563, 'timeout'))
    return summary


class ManualTests(unittest.TestCase):
    @staticmethod
    def manual_manifest(cmdline):
        return dict(name='synthetic-fixture', cmdline=cmdline, cmdline_bytes=len(cmdline.encode()),
                    ids=dict(stamp_nonce='0x0000000000000001'), image='1'*64,
                    mach='2'*64, payload='3'*64, adt='4'*64)

    def test_manual_nonce_binding_and_incomplete_manifest_refusal(self):
        for document in ({'cmdline':''}, dict(self.manual_manifest(''), ids={})):
            self.manifest.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'manual mode requires'):
                live.load_schedule(self.manifest, None, manual=True)
        source = {}
        live.bind_manual_manifest(source, 7)
        self.assertEqual(source['manifest_binding']['status'], 'pending_unverified')
        source = dict(epoch=dict(nonce=7))
        live.bind_manual_manifest(source, 7)
        self.assertEqual(source['manifest_binding']['status'], 'matched_stamp_nonce')
        with self.assertRaisesRegex(ValueError, 'nonce mismatch'):
            live.bind_manual_manifest(dict(epoch=dict(nonce=8)), 7)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.manifest = self.directory / 'manifest.json'
        self.manifest.write_text(json.dumps(self.manual_manifest('cpus=5 hk_top=30 hk_ui_trace=1')))
        self.raw = self.directory / 'fixture.raw'
        self.raw.write_bytes(b'HK TOP: every 30 s\nHK TOP: t=600 frames+12 cpu_ms=100: backboardd[22]=90\n')
        Path(str(self.raw) + '.times').write_text(f'0.25\t0\t{self.raw.stat().st_size}\n')

    def cli(self, *args):
        return subprocess.run([sys.executable, '-I', str(HERE / 'live_profile.py'),
                               '--raw', str(self.raw), '--manifest', str(self.manifest),
                               '--no-symbols', *args], capture_output=True, text=True, timeout=30)

    def test_strict_default_and_explicit_manual_have_distinct_admission(self):
        with self.assertRaisesRegex(ValueError, 'exactly one complete'):
            live.load_schedule(self.manifest, None)
        self.assertEqual(live.load_schedule(self.manifest, None, manual=True), (None, str(self.manifest)))
        self.assertEqual(self.cli().returncode, 2)
        result = self.cli('--manual')
        self.assertEqual(result.returncode, 0, result.stderr)
        r = json.loads(result.stdout)
        self.assertEqual(r['workload']['mode'], 'manual')
        self.assertEqual(r['workload']['control'], 'uncontrolled')
        self.assertEqual((r['script']['state'], r['script']['tokens_observed'], r['phases']), ('not_applicable', 0, []))
        self.assertNotIn('expected', r['script'])
        self.assertEqual(r['source']['capture_state'], 'provisional_no_final_summary')
        self.assertEqual(r['source']['manifest_sha256'], hashlib.sha256(self.manifest.read_bytes()).hexdigest())
        self.assertEqual(r['windows'][0]['frames_delta'], 12)
        for k in ('causal_speed_claim', 'fps', 'touch_to_glass'):
            self.assertEqual(r['workload'][k], 'unavailable')

    def test_manual_forbids_script_and_requires_manifest_even_for_dump(self):
        for manifest, script in ((None, None), (self.manifest, '1:h'), (self.manifest, '')):
            with self.subTest(manifest=manifest, script=script), self.assertRaisesRegex(ValueError, 'requires --manifest and forbids --script'):
                live.load_schedule(manifest, script, manual=True)
        with self.assertRaisesRegex(ValueError, 'cannot have a scripted schedule'):
            live.Analyzer(schedule=live.script_schedule('1:h'), manual=True)
        for args in (['--raw', str(self.raw)], ['--dump', 'unused-dump']):
            result = subprocess.run([sys.executable, '-I', str(HERE / 'live_profile.py'), *args,
                                     '--manual', '--no-symbols'], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertIn('requires --manifest', result.stderr)
        self.assertEqual(self.cli('--manual', '--script', '1:h').returncode, 2)

    def test_malformed_empty_bare_and_duplicate_manifest_tokens_are_not_manual(self):
        for value in ('hk_ui', 'hk_ui=', 'hk_ui=1:h', 'hk_ui=1:h hk_ui=',
                      'hk_ui=1:h hk_ui=1:h', 'hk_ui=1:h hk_ui', 'hk_ui=oops'):
            self.manifest.write_text(json.dumps(dict(cmdline='cpus=5 ' + value)))
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'exactly no hk_ui'):
                live.load_schedule(self.manifest, None, manual=True)
            if value != 'hk_ui=1:h':
                with self.subTest(strict=value), self.assertRaises(ValueError):
                    live.load_schedule(self.manifest, None)
        for document in ({}, {'cmdline': None}, {'cmdline': []}, {'cmdline': 1}, [], None):
            self.manifest.write_text(json.dumps(document))
            for manual in (False, True):
                with self.subTest(document=document, manual=manual), self.assertRaisesRegex(ValueError, 'cmdline must be a string'):
                    live.load_schedule(self.manifest, None, manual=manual)
        self.manifest.write_text('{')
        self.assertEqual(self.cli('--manual').returncode, 2)

    def test_scripted_mode_retains_schedule_checks_and_cannot_override_manifest(self):
        self.manifest.write_text(json.dumps(dict(cmdline='cpus=5 hk_ui=1:h')))
        schedule, _ = live.load_schedule(self.manifest, 'hk_ui=1:h')
        self.assertEqual(schedule, live.script_schedule('1:h'))
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            live.load_schedule(self.manifest, '2:h')
        with self.assertRaises(ValueError):
            live.load_schedule(None, '')
        a = live.Analyzer(schedule=schedule)
        a.feed(0, b'HK UITRACE token seq=0 event=0 tok=0 op=p callback_us=1 begin_us=2 end_us=3 late_us=0\n')
        self.assertIn('trace disagrees with manifest at seq=0', a.report()['script']['errors'])
        self.assertEqual(self.cli('--manual').returncode, 2)

    def test_runtime_replay_and_malformed_replay_are_manual_conflicts(self):
        for raw in (b'HK UI: 1 tokens, start in 1 s\n', b'HK UI: refused invalid\n',
                    b'HK UITRACE token seq=0 event=0 tok=0 op=h callback_us=1 begin_us=2 end_us=3 late_us=0\n',
                    b'HK UITRACE done us=4 events=2 tokens=1 max_late_us=0 max_call_us=1 drift_us=0\n',
                    b'HK UITRACE token damaged\n'):
            self.raw.write_bytes(raw)
            Path(str(self.raw) + '.times').write_text(f'0.25\t0\t{len(raw)}\n')
            with self.subTest(raw=raw):
                result = self.cli('--manual')
                self.assertEqual(result.returncode, 1, result.stderr)
                r = json.loads(result.stdout)
                self.assertEqual(r['script']['state'], 'conflict')
                self.assertIn('manual workload conflicts', r['script']['errors'][0])

    def test_manual_holes_partial_lines_and_summary_conflicts_stay_visible(self):
        first = self.raw.read_bytes()
        last = b'partial fragment\nHK TOP: t=630 frames+3 cpu_ms=20:\nHKAKSTRACE: ready'
        with self.raw.open('wb') as target:
            target.write(first)
            target.seek(1000)
            target.write(last)
        Path(str(self.raw) + '.times').write_text(f'0.25\t0\t{len(first)}\n1.0\t1000\t{len(last)}\n')
        summary = dict(bytes=len(first) + len(last), final_offset=1000 + len(last), reads=2,
                       lost_bytes=1000 - len(first), last_status=dict(nonce=1, entry_t=2, hz=3))
        sidecar = Path(str(self.raw) + '.json')
        sidecar.write_text(json.dumps(summary))
        result = self.cli('--manual')
        self.assertEqual(result.returncode, 0, result.stderr)
        r = json.loads(result.stdout)
        self.assertEqual(r['source']['capture_state'], 'final_summary')
        self.assertEqual(r['windows'][1]['coverage'], 'gap')
        self.assertEqual(r['gaps'][0]['bytes'], 1000 - len(first))
        self.assertGreater(r['trailing_partial_bytes'], 0)
        self.assertEqual(r['aks']['state'], 'unobserved')
        self.assertNotEqual(r['script']['state'], 'observed_complete')
        summary['lost_bytes'] = 0
        sidecar.write_text(json.dumps(summary))
        refused = self.cli('--manual')
        self.assertEqual(refused.returncode, 2)
        self.assertIn('summary/journal disagree', refused.stderr)

    def test_manual_output_cannot_replace_final_sidecar(self):
        sidecar = Path(str(self.raw) + '.json')
        sidecar.write_text('{}')
        result = self.cli('--manual', '--json', str(sidecar))
        self.assertEqual(result.returncode, 2)
        self.assertIn('must not overwrite', result.stderr)
        self.assertEqual(sidecar.read_text(), '{}')

    def test_actual_completed_manual_raw_and_dump_decode_without_invented_replay(self):
        summary = finished_manual_capture(self)
        with self.assertRaisesRegex(ValueError, 'exactly one complete'):
            live.load_schedule(MANUAL_MANIFEST, None)
        schedule, _ = live.load_schedule(MANUAL_MANIFEST, None, manual=True)
        a, journal = live.Analyzer(schedule=schedule, manual=True), live.Journal(MANUAL_RAW)
        for off, data, host in journal.poll(final=True):
            a.feed(off, data, host)
        epoch = {k: summary['last_status'][k] for k in ('nonce', 'entry_t', 'hz')}
        verified = live.verify_capture(journal, MANUAL_DUMP, epoch)
        self.assertEqual((verified['compared_bytes'], verified['uncomparable_live_bytes'], verified['not_read_before_reset']),
                         (1450057, 0, 1288))
        r = a.report()
        self.assertEqual((r['script']['state'], r['script']['errors'], r['phases'], len(r['windows'])),
                         ('not_applicable', [], [], 29))  # 30 HK TOP lines include the startup banner.
        self.assertEqual(r['aks']['state'], 'unobserved')
        canonical = live.Analyzer(manual=True)
        for off, data in live.decode_dump(MANUAL_DUMP, epoch)[0]:
            canonical.feed(off, data)
        key = lambda r: (r['kind'], r['offset'], r['end_offset'])
        self.assertEqual([key(r) for r in a.records],
                         [key(r) for r in canonical.records if r['end_offset'] <= journal.end])
        self.assertEqual([r['termination'] for r in canonical.report()['termination']], ['deadline_panic'])

    def test_manual_mode_cannot_hide_a_foreign_dump_epoch(self):
        summary = finished_manual_capture(self)
        journal = live.Journal(MANUAL_RAW)
        journal.poll(final=True)
        epoch = {k: summary['last_status'][k] for k in ('nonce', 'entry_t', 'hz')}
        epoch['nonce'] ^= 1
        with self.assertRaisesRegex(ValueError, 'epoch mismatch'):
            live.verify_capture(journal, MANUAL_DUMP, epoch)


class AKSTraceTests(unittest.TestCase):
    @staticmethod
    def observation(call=1, **changes):
        fields = dict(t_ms=600123, call=call, pid=123, tid=456, sel=17, handle_present=1, handle=0,
                      in_='1/0', in_type='inband', out_req='0/256', out_actual='0/82', out_type='descriptor',
                      emitted=82, wrote=81, tag='0x31', short_len=80, ret='0x0', user_state=1,
                      pc='0x1975c5b58', lr='0x1975c58f8', frames='2 0x1975c58f8 0x1975c4000')
        fields.update(changes)
        return ('HKAKSTRACE: ' + ' '.join(f'{k.removesuffix("_")}={v}' for k, v in fields.items()) + '\n').encode()

    def test_ready_and_unknown_lines_never_become_execution(self):
        a = live.Analyzer(manual=True)
        a.feed(0, (live.AKS_READY + '\nHKAKSTRACE: ready v=2 unknown=kept\n').encode())
        r = a.report()
        self.assertEqual((r['aks']['state'], r['aks']['execution_record_count']), ('ready_only', 0))
        self.assertEqual(r['aks']['unknown_records'][0]['detail'], 'HKAKSTRACE: ready v=2 unknown=kept')
        self.assertEqual(r['aks']['unknown_records'][0]['kind'], 'aks_unknown')
        with self.assertRaisesRegex(ValueError, 'second AKS ready'):
            a.feed(a.end, (live.AKS_READY + '\n').encode())

    def test_request_reported_write_der_headers_and_stack_are_independent(self):
        class NoGuessedSymbols:
            def resolve(self, *args):
                raise AssertionError('AKS must not guess the absent ASLR slide')
        raw = self.observation() + self.observation(2, out_type='inband', wrote=82, ret='0xe00002bd',
                                                   tag='0x7f', short_len=255)
        a = live.Analyzer(symbols=NoGuessedSymbols(), manual=True)
        for off in range(0, len(raw), 13):
            a.feed(off, raw[off:off + 13], 0.5)
        r = a.report()
        self.assertEqual(r['aks']['state'], 'execution_observed')
        self.assertIsNone(r['aks']['ready'])
        one, two = r['aks']['observations']
        self.assertEqual((one['out_req_struct'], one['out_actual_struct'], one['emitted'], one['wrote'], one['ret']),
                         (256, 82, 82, 81, '0x0'))
        self.assertEqual((two['ret'], two['tag'], two['short_len']), ('0xe00002bd', '0x7f', 255))
        self.assertEqual(one['kernel_s'], [600.123, 600.124])
        self.assertEqual(one['host_received_s'], 0.5)
        self.assertEqual(one['frames_count'], len(one['frames']))
        self.assertEqual([s['address'] for s in one['stack']], [one['pc'], one['lr'], *one['frames']])
        self.assertTrue(all(s['status'] == 'unresolved' and 'symbol' not in s for s in one['stack']))
        self.assertEqual(raw[one['offset']:one['end_offset']], self.observation())
        self.assertEqual(r['aks']['execution_record_count'], 2)
        self.assertEqual(r['aks']['last_sampled_call'], 2)

    def test_bounds_and_internal_state_conflicts_fail(self):
        cases = [dict(call=0), dict(call=9), dict(call=65537), dict(sel=18), dict(t_ms=0),
                 dict(frames='9 ' + ' '.join(['0x1'] * 9)),
                 dict(handle_present=2), dict(handle_present=0, handle=1), dict(user_state=2),
                 dict(user_state=0), dict(short_len=256), dict(tag='0x100')]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'AKS'):
                live.Analyzer().feed(0, self.observation(**changes))
        a = live.Analyzer()
        a.feed(0, self.observation(65536, user_state=0, pc='0x0', lr='0x0', frames='0', handle_present=0))
        self.assertEqual(a.report()['aks']['observations'][0]['frames'], [])

    def test_concurrent_print_order_is_legal_duplicate_call_is_not(self):
        a = live.Analyzer()
        a.feed(0, self.observation(16, t_ms=600500) + self.observation(2))
        self.assertEqual([r['call'] for r in a.records], [16, 2])
        self.assertTrue(a.warnings)
        with self.assertRaisesRegex(ValueError, 'duplicate AKS call'):
            a.feed(a.end, self.observation(2))

    def test_partial_unknown_interleaved_and_gap_records_are_not_fabricated(self):
        raw = self.observation()
        a = live.Analyzer()
        a.feed(0, raw[:-1])
        self.assertEqual(a.report()['aks']['execution_record_count'], 0)
        a.feed(len(raw) + 50, b'fragment\n' + self.observation(2))
        self.assertEqual([r['call'] for r in a.report()['aks']['observations']], [2])
        for damaged in (raw.replace(b'out_actual=0/82', b'out_actual=interleaved'),
                        b'HKAKSTRACE: future data\n'):
            a = live.Analyzer()
            a.feed(0, damaged)
            self.assertEqual(a.report()['aks']['state'], 'unobserved')
            self.assertEqual(a.report()['aks']['unknown_records'][0]['detail'], damaged.decode().rstrip('\n'))

    def test_damaged_frame_suffix_preserves_only_the_intact_header(self):
        for suffix in ('1 0x1 0x2', '8 0x1SWEET AKS: unrelated', '8 0x', '2 0x1 0x2 new_field=unknown', '2'):
            a = live.Analyzer()
            a.feed(0, self.observation(frames=suffix))
            r = a.report()
            self.assertEqual(r['aks']['state'], 'execution_prefix_observed')
            self.assertEqual((r['aks']['complete_record_count'], r['aks']['partial_record_count']), (0, 1))
            observation = r['aks']['observations'][0]
            self.assertEqual((observation['out_req_struct'], observation['out_actual_struct'], observation['wrote']), (256, 82, 81))
            self.assertEqual(observation['record_integrity'], 'prefix_only')
            self.assertFalse(observation['frames_complete'])
            self.assertEqual(observation['frames'], [])
            self.assertEqual(len(observation['stack']), 2)  # Only the intact PC/LR, no guessed cut hex.
            self.assertEqual(observation['unparsed_suffix'], suffix[suffix.index(' '):] if ' ' in suffix else '')
            self.assertTrue(r['warnings'])

    def test_interleaved_top_suffix_cannot_hide_aks_header(self):
        a = live.Analyzer(manual=True)
        a.feed(0, self.observation(frames='8 0x1HK TOP: t=600 frames+5 cpu_ms=10:'))
        report = a.report()
        self.assertEqual(report['aks']['execution_record_count'], 1)
        self.assertFalse(report['aks']['observations'][0]['frames_complete'])
        self.assertEqual(a.tops, [])
        a = live.Analyzer()
        a.feed(0, b'HKAKSTRACE: unknown HK TOP: t=600 frames+5 cpu_ms=10:\n')
        self.assertEqual(len(a.report()['aks']['unknown_records']), 1)

    def test_writer_impossible_frame_addresses_are_prefix_only(self):
        for frames in ('2 0x2495b030c 0x1', '1 0x1000000000000'):
            a = live.Analyzer()
            a.feed(0, self.observation(frames=frames))
            record = a.report()['aks']['observations'][0]
            self.assertFalse(record['frames_complete'])
            self.assertEqual(record['frames'], [])

    def test_completed_p31r1_actual_prefixes_are_not_full_frame_or_ready_only_claims(self):
        raw = REPO / 'research/ios26-opt-20261102/parent/p31r1-live-diag-r1.raw'
        dump = ATTEMPTS / '20261102-121918-phone-p31r1-live-diag-r1/ramdump/kernel.log'
        manifest = MANIFESTS / 'phone-p31r1-live-diag-r1/manifest.json'
        sidecar = Path(str(raw) + '.json')
        if not all(p.is_file() for p in (raw, Path(str(raw) + '.times'), sidecar, dump, manifest)):
            self.skipTest('completed private p31r1 final summary/manifest/dump absent; never read an active raw')
        summary = json.loads(sidecar.read_text())
        self.assertEqual((summary['bytes'], summary['reads'], summary['end']), (934831, 2920, 'device gone'))
        self.assertEqual(live.digest(raw), '14b73cb770a8ea22ae3e7ae0a938e984d89ebdbcdd3bd73932ff7d0db2267498')
        self.assertEqual(live.digest(dump), 'c3d2afef36e71e9700209d1f84124371cfb9b014bd81d0dc86b460149b1f79d1')
        schedule, _ = live.load_schedule(manifest, None, manual=True)
        a, journal = live.Analyzer(schedule=schedule, manual=True), live.Journal(raw)
        for off, data, host in journal.poll(final=True):
            a.feed(off, data, host)
        epoch = {k: summary['last_status'][k] for k in ('nonce', 'entry_t', 'hz')}
        verified = live.verify_capture(journal, dump, epoch)
        self.assertEqual((verified['compared_bytes'], verified['uncomparable_live_bytes'], verified['not_read_before_reset']),
                         (934831, 0, 479))
        r = a.report()
        self.assertEqual((r['script']['state'], r['script']['errors'], r['phases']), ('not_applicable', [], []))
        self.assertEqual((len(r['windows']), len(r['presentation']['observations']), len(r['presentation']['counters'])), (9, 28, 9))
        aks = r['aks']
        self.assertEqual(aks['state'], 'execution_prefix_observed')
        self.assertIsNotNone(aks['ready'])
        self.assertEqual((aks['execution_record_count'], aks['complete_record_count'], aks['partial_record_count']), (13, 0, 13))
        self.assertEqual(aks['last_sampled_call'], 256)
        self.assertEqual(aks['unknown_records'], [])
        self.assertEqual([o['call'] for o in aks['observations']], [1, 2, 3, 4, 5, 6, 7, 8, 16, 32, 64, 128, 256])
        for o in aks['observations']:
            self.assertEqual((o['pid'], o['out_req_struct'], o['out_actual_struct'], o['emitted'], o['wrote']), (142, 4096, 82, 82, 82))
            self.assertEqual((o['tag'], o['short_len'], o['pc'], o['lr']), ('0x31', 80, '0x2495accd4', '0x2495b030c'))
            self.assertEqual((o['frames_count'], o['frames_complete'], o['frames']), (8, False, []))
            self.assertEqual(len(o['stack']), 2)
            self.assertIsNotNone(o['unparsed_suffix'])
            self.assertTrue(all(s['status'] == 'unresolved' for s in o['stack']))

    def test_cli_events_and_summary_expose_real_fields_without_success_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.raw'
            path.write_bytes((live.AKS_READY + '\n').encode() + self.observation() + b'HKAKSTRACE: unknown\n')
            Path(str(path) + '.times').write_text(f'0.25\t0\t{path.stat().st_size}\n')
            manifest = Path(tmp) / 'manifest.json'
            manifest.write_text(json.dumps(ManualTests.manual_manifest('hk_top=30')))
            command = [sys.executable, '-I', str(HERE / 'live_profile.py'), '--raw', str(path),
                       '--manual', '--manifest', str(manifest), '--no-symbols']
            events = subprocess.run(command + ['--events'], capture_output=True, text=True, timeout=30)
            self.assertEqual(events.returncode, 0, events.stderr)
            self.assertEqual([json.loads(line)['kind'] for line in events.stdout.splitlines()],
                             ['aks_ready', 'aks_observation', 'aks_unknown'])
            summary = subprocess.run(command + ['--summary'], capture_output=True, text=True, timeout=30)
            self.assertEqual(summary.returncode, 0, summary.stderr)
            for phrase in ('MANUAL, uncontrolled', 'out_req=0/256', 'out_reported=0/82',
                           'emitted=82 wrote=81', 'DER not validated', 'ASLR unresolved'):
                self.assertIn(phrase, summary.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
