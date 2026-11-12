#!/usr/bin/env python3
"""Host tests for tools/hk_session.py with the existing doubles: test_hk_cycle's fake adb/fastboot/mac (one phone state
machine), fake live_boot.sh, screenshot.sh, return-check.sh; the REAL tools/hk_cycle.py and tools/mactools.py; a fake hk
(to-fastboot) and a fake hk_score. Never touches a device.  python3 -I tools/test_hk_session.py [-v]"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'tools/{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tc = load('test_hk_cycle')
hs = load('hk_session')
TOOL = ROOT / 'tools/hk_session.py'
CLQ = 'blazer_deadline=4 blazer_usbcon=2 blazer_usbcon_ch9=1 hk_dbg=0x7c1e1eff'

FAKE_HK = r'''
import fcntl, json, os, sys, time
STATE = os.environ['FAKE_PHONE']
f = open(STATE + '.lock', 'w'); fcntl.flock(f, fcntl.LOCK_EX)
st = json.load(open(STATE))
st['calls'].append(dict(tool='hk', args=sys.argv[1:], t=time.time(), mode=st['mode'], stdin_open=True))
how = st.get('hk_to_fastboot', 'ok')
if how == 'ok':
    st['mode'] = 'fastboot'; st['ff'] = True; st['park_at'] = None
    out, rc = dict(ok=True, data=dict(state='fastboot', action='usbcon reset op (reader)', ramdump_kept=True)), 0
else:
    out, rc = dict(ok=False, error=dict(code='reset_not_armed', message='the kernel stalled the reset request: this boot runs blazer_usbcon=1')), 6
json.dump(st, open(STATE + '.tmp', 'w')); os.replace(STATE + '.tmp', STATE)
print(json.dumps(out)); sys.exit(rc)
'''
FAKE_SCORE = r'''
import json, os, sys
a = sys.argv[1:]
with open(os.environ['FAKE_SCORE_LOG'], 'a') as f:
    f.write(json.dumps(a) + '\n')
if '--json' in a: print(json.dumps(dict(boot=a[0], subsystems=dict(wifi=dict(level=3)))))
elif '--md' in a: print('| subsystem | level |\n|---|---|\n| wifi | 3 |')
elif '--diff' in a: print('wifi: 2 -> 3 (+1) joined')
elif '--baseline' in a:
    bad = os.environ.get('FAKE_SCORE_REGRESS') == '1'
    print('REGRESSION gpu 9 -> 7' if bad else 'no regression'); sys.exit(1 if bad else 0)
'''


class Rig(tc.Rig):
    """test_hk_cycle's rig plus a queue, a results directory, the stock image and the session's own doubles."""
    def __init__(self, **state):
        state.setdefault('cmdline', CLQ)
        state.setdefault('park_after', 60)
        super().__init__(**state)
        self.queue, self.results = self.base / 'queue', self.base / 'results'
        self.queue.mkdir()
        self.script('hk.py', FAKE_HK)
        self.script('hk_score.py', FAKE_SCORE)
        self.stock = self.base / 'stock_boot_b.img'
        self.stock.write_bytes(b'stock boot image')
        self.baseline = self.base / 'baseline.json'
        self.baseline.write_text('{}')
        self.score_log = self.base / 'score.log'
        # hk_cycle is the real one, with the rig's fixed arguments added (the stock image of this rig, no image_tool, no cache)
        wrapper = self.bin / 'hk_cycle_wrapper.py'
        wrapper.write_text(f'''#!{sys.executable}
import os, sys
a = sys.argv[1:]
extra = ['--stock-boot', {str(self.stock)!r}, '--stock-boot-sha256', {hashlib.sha256(b"stock boot image").hexdigest()!r}]
if '--return-only' not in a:
    extra += ['--skip-image-check', '--no-shots', '--cache', '/nonexistent']
os.execv(sys.executable, [sys.executable, '-I', {str(ROOT / "tools/hk_cycle.py")!r}] + a + extra)
''')
        self.cycle = wrapper

    def req(self, stem, **kv):
        f = dict(IMAGE='a7-fake', MACH=str(self.mach.relative_to(ROOT)), NAME=f'a7-{stem}', WAIT='60', END_ON='exec Preferences$',
                 WHY=f'does {stem} work?')
        f.update(kv)
        text = '\n'.join(f"{k}='{v}'" if k not in ('WHY', 'IMAGE', 'MACH', 'NAME', 'WAIT') else f'{k}={v}' for k, v in f.items() if v is not None)
        (self.queue / f'{stem}.req').write_text(text + '\n')

    def session(self, *extra, timeout=240, more_timeouts='', **env):
        e = self.env()
        e.update(HK_SESSION_CYCLE=str(self.cycle), HK_SESSION_SCORE=str(self.bin / 'hk_score.py'), HK_SESSION_HK=str(self.bin / 'hk.py'),
                 HK_SESSION_IMAGES=str((self.base / 'images').relative_to(ROOT)), FAKE_SCORE_LOG=str(self.score_log))
        e.update(env)
        argv = [sys.executable, '-I', str(TOOL)]
        if '--return' not in extra:
            argv.append(str(self.queue))
        argv += ['--results', str(self.results), '--baseline', str(self.baseline), '--end-grace', '0.1', '--poll', '0.2',
                 '--timeouts', 'settle=0.5,park_wait=6,android_boot=6,to_fastboot=5,unknown_wait=1,boot_extra=10,return_absent=0,'
                 'return_ios=8,stay_park=5,repark=2' + more_timeouts, *extra]
        return subprocess.run(argv, env=e, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)

    def seq(self):
        return [(c['tool'], ' '.join(c['args'])) for c in self.phone()['calls'] if c['tool'] in ('fastboot', 'adb', 'hk')]

    def result(self, stem):
        return json.loads((self.results / stem / 'result.json').read_text())


class ParseTests(unittest.TestCase):
    def test_parse_req_forms(self):
        f, e = hs.parse_req("IMAGE=a7-x   MACH=research/k.unstripped\nNAME=a7-x-1  WAIT=120  END_ON='blazer-wifi: join: (joined|failed)' END_AFTER=30\n"
                            "# a comment\nEXPECT=\"a|b c\" QUERIES='drivers; ioreg IO80211Controller 4'  UI=ui/x.ui\n"
                            "ABORT_ON='max (6[0-9]) C'\nWHY=Does the join complete? It's the one question = here, with END_ON=x inside\n")
        self.assertEqual(e, [])
        self.assertEqual(f, dict(IMAGE='a7-x', MACH='research/k.unstripped', NAME='a7-x-1', WAIT='120',
                                 END_ON='blazer-wifi: join: (joined|failed)', END_AFTER='30', EXPECT='a|b c',
                                 QUERIES='drivers; ioreg IO80211Controller 4', UI='ui/x.ui', ABORT_ON='max (6[0-9]) C',
                                 WHY="Does the join complete? It's the one question = here, with END_ON=x inside"))
        f, e = hs.parse_req("IMAGE=a\nOWNER='When the console prints X, rotate the phone'\nWHY=q\n")
        self.assertEqual((e, f['OWNER']), ([], 'When the console prints X, rotate the phone'))
        self.assertEqual(hs.validate_req('s-1', dict(f, MACH='k'), [])[0]['extra'], dict(OWNER='When the console prints X, rotate the phone'))
        for bad in ('foo=1', 'IMAGE=a IMAGE=b', "END_ON='unterminated", 'stray words'):
            self.assertTrue(hs.parse_req(bad)[1], bad)

    def test_validate(self):
        ok = dict(IMAGE='a7-x', MACH='/Users/x/Developer/personal/hackios/research/k.unstripped', WHY='q', QUERIES='drivers')
        req, e = hs.validate_req('lane-1', ok, [])
        self.assertEqual(e, [])
        self.assertEqual((req['mach'], req['name'], req['image_dir']), ('research/k.unstripped', 'lane-1', 'research/images/a7-x'))
        for k, v in (('IMAGE', '../x'), ('MACH', '/etc/passwd'), ('MACH', None), ('NAME', 'a b'), ('WAIT', '5'), ('WAIT', 'soon'),
                     ('END_ON', '('), ('ABORT_ON', '['), ('EXPECT', '(?P<'), ('QUERIES', 'shell ls'), ('QUERIES', 'ioreg'), ('UI', '../../x.ui'),
                     ('WHY', None), ('END_AFTER', '-3')):
            f = dict(ok)
            f.pop(k) if v is None else f.update({k: v})
            self.assertTrue(hs.validate_req('lane-1', f, [])[1], (k, v))
        self.assertEqual(hs.validate_req('l', dict(ok, IMAGE='research/images/a7-x/boot.img'), [])[0]['image'], 'a7-x')

    def test_the_real_fleet_queue_format(self):
        f, e = hs.parse_req("IMAGE=a7-ios-system-power1-r1\nMACH=research/p/kernel.power1.unstripped\nNAME=a7-power1-r1\nWAIT=420\n"
                            "END_ON='blazer-gov: t=(1[5-9][0-9]|[2-9][0-9][0-9]) R[0-9] cap'\nEND_AFTER=90\nQUERIES='drivers'\n"
                            "ABORT_ON='blazer-thermal: poll [0-9]+ max (6[0-9]|[7-9][0-9]) C|SWEET CPU: cpu=[0-9]+ .*NOT alive'\nWHY=Does it run? Thermal abort: end at once.\n")
        req, e = hs.validate_req('power-1', f, e)
        self.assertEqual(e, [])
        self.assertEqual((req['wait'], req['end_after'], req['queries']), (420, 90.0, 'drivers'))


class ScoreTests(unittest.TestCase):
    def test_the_host_end_panic_is_a_planned_end(self):
        sc = load('hk_score')
        pre = 'panic(cpu 2 caller 0xfffffe0007993a10): '
        self.assertIsNone(sc.UNPLANNED_PANIC.search(pre + 'blazer-usbcon: the host asked to end this boot @blazer_usbcon.c:119'))
        self.assertIsNone(sc.UNPLANNED_PANIC.search(pre + 'blazer-root: deadline 900 s, stage pid1_exec'))
        self.assertIsNotNone(sc.UNPLANNED_PANIC.search(pre + 'Kernel data abort. at pc 0xfffffe0007000000'))
        self.assertIn('blazer-usbcon: the host asked to end this boot', (ROOT / 'docs/scoreboard.yaml').read_text())


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.rigs = []

    def tearDown(self):
        for r in self.rigs:
            r.close()

    def rig(self, **kw):
        r = Rig(**kw)
        self.rigs.append(r)
        return r

    def last(self, p):
        return p.stdout.strip().splitlines()[-1]

    def test_two_requests_stay_in_fastboot_and_return_once_at_the_end(self):
        r = self.rig(mode='android', boot_completed_at=0)
        r.req('wifi-1', QUERIES='drivers; procs 50', EXPECT='exec (SpringBoard|Preferences)$')
        r.req('gpu-2', END_ON=None, END_AFTER='0.5')
        p = r.session()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.last(p), 'hk_session: phone: android (boot completed; return check PASS)')
        seq = r.seq()
        boots = [i for i, c in enumerate(seq) if c[0] == 'fastboot' and c[1].startswith('boot ')]
        self.assertEqual(seq.count(('adb', 'reboot bootloader')), 1, 'Android is left once')
        self.assertEqual(seq.count(('fastboot', 'reboot')), 0, 'default return: the stock image, not the installed chooser')
        self.assertEqual(len(boots), 1, 'one fastboot boot by the session itself: the stock image at the end')
        self.assertIn('stock_boot_b.img', seq[boots[0]][1])
        self.assertEqual(seq.count(('fastboot', 'oem force-fastboot off')), 1)
        self.assertLess(seq.index(('fastboot', 'oem force-fastboot off')), boots[0])
        ph = r.phone()
        self.assertEqual([Path(b).parent.name for b in ph['booted'][:2]], ['a7-fake', 'a7-fake'])
        self.assertEqual(len(ph['booted']), 3)
        lb = [c for c in ph['calls'] if c['tool'] == 'live_boot']
        self.assertEqual([c['mode'] for c in lb], ['fastboot', 'fastboot'], 'the second boot starts from the park of the first')
        self.assertFalse(ph['ff'])
        self.assertNotIn('checkout_tool_used', ph)
        for stem in ('wifi-1', 'gpu-2'):
            d = r.results / stem
            for f in ('REPORT.md', 'result.json', 'console.txt', 'markers.txt', 'ramdump/kernel.log', 'score.json', 'score.md', 'score-diff.txt',
                      'cycle/report.md', f'{stem}.req'):
                self.assertTrue((d / f).is_file(), f'{stem}/{f}')
            self.assertEqual(r.result(stem)['phone'], 'fastboot')
            self.assertFalse((r.queue / f'{stem}.req').exists())
            self.assertTrue((r.queue / 'done' / f'{stem}.req').is_file())
        w = r.result('wifi-1')
        self.assertEqual((w['verdict'], w['queries']['ok'], w['end']['condition'], w['end']['reset']), ('COMPLETE', 2, 'end-on', 'reset'))
        self.assertEqual(w['expect']['lines'], 2)
        self.assertFalse(w['score']['regressed'])
        md = (r.results / 'wifi-1/REPORT.md').read_text()
        for needle in ('# wifi-1: COMPLETE', '**Question:** does wifi-1 work?', 'Ended by: **end-on**', '## Queries', '| procs 50 | 0 |',
                       '## Timing', 'reset op sent', '## Scoreboard', 'no regression', 'wifi: 2 -> 3', 'Phone after this request: **fastboot**',
                       '![end-', 'exec SpringBoard'):
            self.assertIn(needle, md)
        self.assertEqual(r.result('gpu-2')['end']['condition'], 'end-after')
        sess = json.loads(next((r.results / '_session').glob('*/session.json')).read_text())
        self.assertEqual((sess['exit_code'], sess['return_']['via_used'], sess['return_']['check']['verdict']), (0, 'stock', 'PASS'))
        self.assertEqual(len(r.score_log.read_text().splitlines()), 8)

    def test_stay_then_return_alone(self):
        r = self.rig()
        r.req('a-1')
        p = r.session('--stay')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('hk_session: phone: fastboot (parked; left there (--stay)', self.last(p))
        self.assertEqual(r.phone()['mode'], 'fastboot')
        self.assertTrue(r.phone()['ff'])
        p = r.session('--return', '--return-via', 'chooser')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.last(p), 'hk_session: phone: android (boot completed; return check PASS)')
        self.assertEqual(r.seq()[-40:].count(('fastboot', 'reboot')), 1)
        self.assertFalse(r.phone()['ff'])

    def test_run_queue_dropin_invocation_green_from_fastboot(self):
        """The exact command run_queue.sh's drop-in issues per request: `hk_session <queue> --results R --stay
        --skip-image-check --only <n>`, from a phone already parked in fastboot (where the 2026-11-11 serial-redaction
        bug misread the phone as usb-google). It must run the one request green and leave the phone parked."""
        r = self.rig(mode='fastboot')        # the rig default, but named here to mark the regression scenario
        r.req('loop-1', QUERIES='drivers; procs 50', ABORT_ON='blazer-therm: critical')
        r.req('gpu-2')                        # a second request that --only must NOT run
        p = r.session('--stay', '--skip-image-check', '--only', 'loop-1')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('hk_session: phone: fastboot (parked; left there (--stay)', self.last(p))
        self.assertNotIn('stopped early', p.stdout, 'no queue-stop on a healthy fastboot phone')
        self.assertEqual(r.result('loop-1')['verdict'], 'COMPLETE')
        self.assertEqual(r.result('loop-1')['phone'], 'fastboot')
        self.assertEqual(r.result('loop-1')['queries']['ok'], 2)
        self.assertFalse((r.results / 'gpu-2').exists(), '--only ran only loop-1')
        self.assertTrue((r.queue / 'gpu-2.req').is_file())
        self.assertEqual(r.phone()['mode'], 'fastboot')
        self.assertTrue(r.phone()['ff'])
        for f in r.results.rglob('*'):        # serials never reach a file
            if f.is_file():
                self.assertNotIn(tc.SERIAL, f.read_text(errors='replace'), f)

    def test_default_end_after_and_abort_on_reach_the_cycle(self):
        r = self.rig()
        r.req('p-1', END_ON=None, ABORT_ON='exec SpringBoard$', QUERIES='drivers')
        p = r.session('--stay', '--default-end-after', '30')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        res = r.result('p-1')
        self.assertEqual(res['end']['condition'], 'abort-on')
        self.assertEqual(res['default_end_after'], 30)
        self.assertIsNone(res['queries'])
        self.assertIn('Ended by: **abort-on**', (r.results / 'p-1/REPORT.md').read_text())

    def test_a_bad_request_is_refused_untouched_and_the_queue_goes_on(self):
        r = self.rig()
        r.req('a-1', END_ON='(', WHY=None)
        r.req('a-2', IMAGE='no-such-image')
        r.req('a-3', QUERIES='drivers', IMAGE='a7-noq')
        idir = r.base / 'images/a7-noq'                      # the same image without the query gate
        idir.mkdir()
        (idir / 'boot.img').write_bytes(r.image.read_bytes())
        (idir / 'manifest.json').write_text(json.dumps(dict(name='a7-noq', cmdline='blazer_deadline=4 blazer_usbcon=2 hk_dbg=0x741e1eff', kind='a7')))
        r.req('a-4')
        p = r.session('--stay')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual([r.result(s)['verdict'] for s in ('a-1', 'a-2', 'a-3', 'a-4')], ['REFUSED', 'REFUSED', 'REFUSED', 'COMPLETE'])
        self.assertIn('END_ON: bad regex', (r.results / 'a-1/REPORT.md').read_text())
        self.assertIn('WHY:', (r.results / 'a-1/REPORT.md').read_text())
        self.assertIn('exists neither on m1box nor in the Mac checkout', (r.results / 'a-2/REPORT.md').read_text())
        self.assertIn('QUERIES_NEED_HKQ', (r.results / 'a-3/REPORT.md').read_text())
        self.assertEqual(len(r.phone()['booted']), 1)
        self.assertIn('hk_session: phone: fastboot', self.last(p))

    def test_unverifiable_mac_tools_stop_the_queue_and_leave_the_request_pending(self):
        r = self.rig(mode='android', boot_completed_at=0, mac_tools_fail=True)
        r.req('a-1')
        r.req('a-2')
        p = r.session()
        self.assertEqual(p.returncode, hs.EXIT_STOPPED, p.stdout + p.stderr)
        self.assertFalse((r.results / 'a-1/REPORT.md').exists())
        self.assertTrue(list((r.results / 'a-1').glob('ATTEMPT-*.md')))
        self.assertTrue((r.queue / 'a-1.req').is_file() and (r.queue / 'a-2.req').is_file())
        self.assertFalse((r.results / 'a-2').exists())
        self.assertIn('MAC_TOOLS_FAILED', p.stdout)
        self.assertEqual(self.last(p), 'hk_session: phone: android (not changed by this session)')
        self.assertFalse([c for c in r.seq() if c[1].startswith(('reboot', 'boot', 'oem'))])
        st = r.phone()                                       # the bridge is back: the same queue runs
        st['mac_tools_fail'] = False
        r.state.write_text(json.dumps(st))
        p = r.session('--max', '1')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((r.results / 'a-1/REPORT.md').is_file())
        self.assertTrue((r.queue / 'a-2.req').is_file())

    def test_a_boot_that_never_parks_stops_the_queue_and_the_last_line_says_where_the_phone_is(self):
        r = self.rig(lb_hang=True, usbcon_mode='1')        # the reset is refused and the boot never ends by itself
        r.req('a-1', WAIT='30')
        r.req('a-2')
        p = r.session(more_timeouts=',boot_watch=1,boot_extra=1')
        self.assertEqual(p.returncode, hs.EXIT_PHONE, p.stdout + p.stderr)
        self.assertIn('stopped early: a-1: after the boot the phone is ios, not parked in fastboot', p.stdout)
        self.assertIn('not run (still pending): a-2', p.stdout)
        self.assertTrue(self.last(p).startswith('hk_session: phone: ios (NOT back in Android'), self.last(p))
        self.assertEqual(r.phone()['mode'], 'ios')           # never a cold reset, never a blind reboot
        self.assertEqual(r.result('a-1')['verdict'], 'PHONE_NOT_IN_FASTBOOT')
        self.assertFalse([c for c in r.seq() if c[1] in ('reboot',) or 'stock' in c[1]])

    def test_a_running_ios_boot_is_ended_first(self):
        r = self.rig(mode='ios', park_at=None)
        r.req('a-1')
        p = r.session('--stay')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        hk = [c for c in r.seq() if c[0] == 'hk']
        self.assertEqual(len(hk), 1)
        self.assertIn('to-fastboot --lock hk-session', hk[0][1])
        self.assertEqual(r.result('a-1')['state_before'], 'ios')
        self.assertIn('ended the running iOS boot: usbcon reset op (reader)', (r.results / 'a-1/REPORT.md').read_text())

    def test_an_ios_boot_that_cannot_be_ended_stops_everything_untouched(self):
        r = self.rig(mode='ios', park_at=None, hk_to_fastboot='refused')
        r.req('a-1')
        p = r.session('--stay')
        self.assertEqual(p.returncode, hs.EXIT_PHONE, p.stdout + p.stderr)
        self.assertIn('reset_not_armed', p.stdout)
        self.assertFalse((r.results / 'a-1/REPORT.md').exists())
        self.assertEqual(r.phone()['booted'], [])
        self.assertTrue(self.last(p).startswith('hk_session: phone: ios ('))

    def test_regression_against_the_baseline_is_in_the_report(self):
        r = self.rig()
        r.req('a-1')
        p = r.session('--stay', FAKE_SCORE_REGRESS='1')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(r.result('a-1')['score']['regressed'])
        self.assertIn('**REGRESSION**', (r.results / 'a-1/REPORT.md').read_text())

    def test_done_requests_are_skipped_and_redo_keeps_the_old_result(self):
        r = self.rig()
        r.req('a-1')
        self.assertEqual(r.session('--stay', '--keep-req').returncode, 0)
        n = len(r.phone()['booted'])
        p = r.session('--stay')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len(r.phone()['booted']), n)
        self.assertIn('0 pending', p.stdout)
        p = r.session('--stay', '--redo', 'a-1')
        self.assertEqual(len(r.phone()['booted']), n + 1, p.stdout)
        self.assertEqual(len(list(r.results.glob('a-1.prev-*'))), 1)

    def test_check_touches_nothing(self):
        r = self.rig()
        r.req('a-1')
        r.req('a-2', END_ON='(')
        p = r.session('--check')
        self.assertEqual(p.returncode, 1)
        self.assertIn('a-1: ok', p.stdout)
        self.assertIn('a-2: INVALID', p.stdout)
        self.assertEqual(r.phone()['calls'], [])


if __name__ == '__main__':
    unittest.main()
