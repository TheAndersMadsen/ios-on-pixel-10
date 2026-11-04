#!/usr/bin/env python3
"""Host tests for tools/ui_run.py and tools/hk_dbg.py. No USB, no Mac, no phone: a fake usbcon client with a screen model,
a fake console.txt, a fake clock and a fake tesseract.

    python3 -I tools/test_ui_run.py
"""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hk_dbg  # noqa: E402
import ui_run  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
W, H = 24, 54          # tiny snapshot frames; src stays 1125x2511


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


def frame(level, pattern=0):
    """An RGB565 frame: grey level 0..31 with a pattern stripe so screens differ."""
    px = []
    for y in range(H):
        for x in range(W):
            v = level if (y + pattern * 7) % 9 else max(0, level - 20)
            px.append(v << 11 | (v * 2) << 5 | v)
    return struct.pack(f'<{W * H}H', *px)


class FakePhone:
    """usbcon --control-socket client as the runner sees it, plus the console that live_boot writes."""

    def __init__(self, tmp, clock, console_lines=(), lit=True, stall_s=0.0, change_on_tap=True, refuse_first=None,
                 caps=('enabled', 'buttons', 'touch', 'button_client', 'touch_client', 'key', 'swipe', 'tap_hold'), snap=True,
                 hands_on_tap=()):
        self.tmp, self.clock = Path(tmp), clock
        self.mac = self.tmp / 'mac'
        self.mac.mkdir()
        self.console = self.tmp / 'console.txt'
        self.console.write_text(''.join(l + '\n' for l in console_lines))
        self.screen = 1 if lit else 0
        self.lit = lit
        self.changed_at = None
        self.stall_s = stall_s
        self.change_on_tap = change_on_tap
        self.refuse_first = refuse_first
        self.caps, self.snap = list(caps), snap
        self.calls = []
        self.nsnap = 0
        self.hands_on_tap = list(hands_on_tap)     # console lines a person causes right after the next tap

    def emit(self, line):
        with open(self.console, 'a') as f:
            f.write(f'12:00:00.000 [  1.00] {line}\n')

    def visible(self):
        if self.changed_at is not None and self.clock() < self.changed_at:
            return self.screen - 1
        return self.screen

    def call(self, *argv, timeout=60):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == '--input-status':
            return dict(state='status', capabilities=self.caps, canvas=[1125, 2511])
        if argv[0] == '--snapshot':
            if not self.snap:
                return dict(state='refused', error='unsupported kernel snapshot ABI')
            self.nsnap += 1
            name = argv[argv.index('--snap-name') + 1]
            rel = f'snaps/{self.nsnap:04d}-{name}'
            (self.mac / 'snaps').mkdir(exist_ok=True)
            v = self.visible()
            raw = frame(28 if self.lit else 0, v)
            (self.mac / (rel + '.rgb565')).write_bytes(raw)
            (self.mac / (rel + '.png')).write_bytes(b'\x89PNG fake')
            return dict(state='snapshot', snapshot=dict(png=rel + '.png', width=W, height=H, step=int(argv[-1]),
                                                        src_w=1125, src_h=2511, size=len(raw)))
        if self.refuse_first and argv[0] == self.refuse_first[0]:
            state, err = self.refuse_first[1]
            self.refuse_first = None
            return dict(state=state, error=err, ambiguous=state == 'unknown')
        if argv[0] in ('--tap', '--swipe', '--home', '--key'):
            if argv[0] != '--tap' or self.change_on_tap:
                self.screen += 1
                self.changed_at = self.clock() + self.stall_s
            if argv[0] == '--tap' and argv[1:3] == ['692', '1780']:
                self.emit('exec Preferences')
            if argv[0] == '--tap' and argv[1:3] == ['172', '2340']:
                self.emit('exec MobilePhone')
            self.emit('HK LIVE done gen=1 result=0')
            if argv[0] == '--tap' and self.hands_on_tap:
                for line in self.hands_on_tap:
                    self.emit(line)
                self.hands_on_tap = []
            return dict(state='dispatched')
        raise AssertionError(argv)

    def fetch(self, paths, dest):
        for p in paths:
            src = self.mac / p
            if src.exists():
                shutil.copy(src, Path(dest) / src.name)


READY = ['12:00:00.000 [  0.10] exec SpringBoard',                    # no launchd "Successfully spawned" line (int1 route)
         '12:00:00.000 [  2.00] SWEET HID: SweetHIDTouch open by IOHIDEventServiceUserClient -> 1',
         '12:00:00.000 [  2.00] SWEET HID: SweetHIDButtons open by IOHIDEventServiceUserClient -> 1',
         '12:00:00.000 [ 25.00] SWEET FB: rate swaps 13.0/s kicks 12.6/s max_gap_us 4176709 changed 0,0 1125x2511 unsaid 77',
         '12:00:00.000 [ 30.00] HK USTACK: Preferences[147] main st 0x1 pc 0x2']


class Args:
    def __init__(self, script='t.ui', **kw):
        self.script, self.no_snap, self.stop_on_fail, self.home_timeout = script, False, False, 840
        self.tesseract, self.python = 'tesseract', 'python3'
        self.__dict__.update(kw)


def runner(tmp, phone, clock, **kw):
    run = Path(tmp) / 'run'
    run.mkdir()
    env = dict(LIVE_RUN=str(run), LIVE_SOCK='/tmp/x.sock', LIVE_MAC_DIR='d', LIVE_MARKERS=str(run / 'markers.txt'),
               LIVE_CONSOLE=str(phone.console), LIVE_T0=str(clock()))
    return ui_run.Runner(Args(**kw), env, phone, clock=clock, sleep=clock.sleep)


def actions(phone):
    return [c for c in phone.calls if c[0] in ('--tap', '--swipe', '--home', '--key')]


class ScriptTests(unittest.TestCase):
    def test_shipped_script_parses(self):
        steps = ui_run.parse_script((ROOT / 'ui/settings_about_phone.ui').read_text())
        cmds = [s[1] for s in steps]
        self.assertEqual(cmds[0], 'wait_home')
        self.assertIn('tap_text', cmds)
        self.assertGreaterEqual(cmds.count('shot'), 15)
        for _, cmd, args, _ in steps:
            if cmd == 'tap':
                self.assertFalse(ui_run.edge_band(*args), args)       # no shipped tap is an edge gesture

    def test_grammar(self):
        s = ui_run.parse_script('tap 1 2 hold=160 expect=same  # c\nswipe 1 2 3 4 ms=200\ntap_text "About This" fallback=3,4\nmark hello world\n')
        self.assertEqual(s[0][1:], ('tap', [1, 2], {'hold': '160', 'expect': 'same'}))
        self.assertEqual(s[2][2], ['About This'])
        self.assertEqual(s[3][2], ['hello world'])
        for bad in ('frob 1', 'tap 1', 'tap a b', 'tap 1 2 colour=red', 'key mute', 'shot ../x', 'tap 1 2 expect=maybe',
                    'swipe 1 2 3', 'tap_text "unterminated'):
            with self.assertRaises(ValueError, msg=bad):
                ui_run.parse_script(bad)

    def test_edge_band_matches_kernel(self):
        # SWEET_TOUCH_EDGE_PX 59 panel px; canvas = panel x 1125/1280
        self.assertTrue(ui_run.edge_band(51, 1000) and ui_run.edge_band(562, 2460))
        self.assertFalse(ui_run.edge_band(52, 1000) or ui_run.edge_band(110, 200) or ui_run.edge_band(1012, 2350))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clock = Clock()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_wait_home_without_launchd_spawn_line_unlocks(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        r = runner(self.tmp, phone, self.clock)
        rc = r.main(ui_run.parse_script('wait_home\n'))
        self.assertEqual(rc, 0)
        self.assertEqual(r.steps[0]['state'], 'HOME')
        self.assertEqual([a[0] for a in actions(phone)], ['--swipe', '--home'])
        self.assertEqual(actions(phone)[0][1:5], ['562', '2490', '562', '1300'])

    def test_wait_home_times_out_naming_what_is_missing(self):
        phone = FakePhone(self.tmp, self.clock, READY[:3])           # no frames
        r = runner(self.tmp, phone, self.clock)
        rc = r.main(ui_run.parse_script('wait_home timeout=100\ntap 500 500\n'))
        self.assertEqual(rc, 2)
        self.assertIn('frames', r.steps[0]['state'])
        self.assertEqual(actions(phone), [])                         # nothing sent, and the walk stopped
        self.assertEqual(json.loads((Path(self.tmp) / 'run/ui_run.json').read_text())['verdict'], 'NOT_RUN')

    def test_wait_home_animated_screen_goes_on_after_a_minute(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        phone.visible = lambda: phone.nsnap          # every read differs
        r = runner(self.tmp, phone, self.clock)
        self.assertEqual(r.main(ui_run.parse_script('wait_home\n')), 0)
        self.assertIn('never still', (Path(self.tmp) / 'run/ui_run.log').read_text())

    def test_wait_home_dark_screen_is_not_ready(self):
        phone = FakePhone(self.tmp, self.clock, READY, lit=False)
        r = runner(self.tmp, phone, self.clock)
        self.assertEqual(r.main(ui_run.parse_script('wait_home timeout=200\n')), 2)
        self.assertIn('dark', r.steps[0]['state'])

    def test_wait_home_quiet_window_restarts_on_backboardd_crash(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        r = runner(self.tmp, phone, self.clock)
        sleep = self.clock.sleep
        fired = []

        def crash_once(s):
            if not fired and self.clock.now > 1004:
                fired.append(1)
                phone.emit('CRASH backboardd reason ns 1')
            sleep(s)
        r.sleep = crash_once
        r.main(ui_run.parse_script('wait_home\n'))
        log = (Path(self.tmp) / 'run/ui_run.log').read_text()
        self.assertIn('quiet window restarts', log)

    def test_full_shipped_script_passes_and_collects(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        r = runner(self.tmp, phone, self.clock, tesseract=self.fake_tesseract({'General': (60, 150), 'About': (60, 40),
                                                                                    'Version': (40, 100)}))
        rc = r.main(ui_run.parse_script((ROOT / 'ui/settings_about_phone.ui').read_text()))
        report = json.loads((Path(self.tmp) / 'run/ui_run.json').read_text())
        self.assertEqual(rc, 0, [(s['line'], s['cmd'], s.get('state')) for s in report['steps'] if s['verdict'] != 'PASS'])
        taps = [a for a in actions(phone) if a[0] == '--tap']
        # OCR centre (60,150) in a 4x upscaled 24x54 frame -> canvas (60/4*1125/24, 150/4*2511/54)
        self.assertIn(['--tap', str(int(60 * 1125 / 24 / 4)), str(int(150 * 2511 / 54 / 4))], taps)
        self.assertEqual(taps[0], ['--tap', '692', '1780'])
        shots = [s for s in report['steps'] if s['cmd'] == 'shot']
        self.assertTrue(all(Path(s['png']).exists() for s in shots))
        self.assertIn('HK USTACK', (Path(self.tmp) / 'run/ustack.txt').read_text())
        self.assertIn('| PASS |', (Path(self.tmp) / 'run/ui_run.md').read_text())
        self.assertIn('UIRUN', (Path(self.tmp) / 'run/markers.txt').read_text())

    def fake_tesseract(self, words):
        """A tesseract stand-in printing TSV word boxes (in the upscaled PNG's pixels) for the given words."""
        path = Path(self.tmp) / 'tesseract'
        rows = ['level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext']
        for i, (text, (cx, cy)) in enumerate(words.items()):
            rows.append(f'5\t1\t{i + 1}\t1\t1\t1\t{cx - 10}\t{cy - 4}\t20\t8\t91.0\t{text}')
        path.write_text('#!/bin/sh\ncat <<"EOF"\n' + '\n'.join(rows) + '\nEOF\n')
        path.chmod(0o755)
        return str(path)

    def test_tap_waits_out_a_stalled_compositor_without_retapping(self):
        phone = FakePhone(self.tmp, self.clock, READY, stall_s=12)    # p31r1: 11.8 s presentation gaps
        r = runner(self.tmp, phone, self.clock)
        rc = r.main(ui_run.parse_script('tap 500 500 verify=30\n'))
        self.assertEqual(rc, 0)
        self.assertEqual(len(actions(phone)), 1)
        self.assertGreaterEqual(r.steps[0]['changed'], ui_run.CHANGE_MIN)

    def test_dispatched_tap_without_change_gets_one_recorded_recovery(self):
        phone = FakePhone(self.tmp, self.clock, READY, change_on_tap=False)
        r = runner(self.tmp, phone, self.clock)
        rc = r.main(ui_run.parse_script('tap 500 500 retry=1 verify=6\n'))
        self.assertEqual(rc, 1)
        self.assertEqual([a[0] for a in actions(phone)], ['--tap', '--home', '--tap'])
        self.assertEqual(r.steps[0]['recovery'], 1)
        self.assertIn('RECOVERY', (Path(self.tmp) / 'run/ui_run.log').read_text())

    def test_edge_tap_refused_locally(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        r = runner(self.tmp, phone, self.clock)
        self.assertEqual(r.main(ui_run.parse_script('tap 10 1000\n')), 1)
        self.assertEqual(actions(phone), [])
        self.assertIn('edge band', r.steps[0]['error'])
        r2 = runner(tempfile.mkdtemp(dir=self.tmp), phone, self.clock)
        self.assertEqual(r2.main(ui_run.parse_script('tap 10 1000 edge=ok\n')), 0)

    def test_clean_refusal_retried_ambiguous_never(self):
        phone = FakePhone(self.tmp, self.clock, READY, refuse_first=('--tap', ('refused', 'rate')))
        r = runner(self.tmp, phone, self.clock)
        self.assertEqual(r.main(ui_run.parse_script('tap 500 500\n')), 0)
        self.assertEqual(len(actions(phone)), 2)
        phone2 = FakePhone(tempfile.mkdtemp(dir=self.tmp), self.clock, READY,
                           refuse_first=('--tap', ('unknown', 'input receipt deadline; do not repeat the action')))
        r2 = runner(tempfile.mkdtemp(dir=self.tmp), phone2, self.clock)
        self.assertEqual(r2.main(ui_run.parse_script('tap 500 500\nhome\n')), 1)
        self.assertEqual([a[0] for a in actions(phone2)], ['--tap', '--home'])   # not retried; the walk went on

    def test_hold_option_reaches_the_client(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        r = runner(self.tmp, phone, self.clock)
        r.main(ui_run.parse_script('tap 500 500 hold=400\n'))
        self.assertEqual(actions(phone)[0], ['--tap', '500', '500', '--hold', '400'])

    def test_no_snapshots_falls_back_to_receipts_and_console(self):
        phone = FakePhone(self.tmp, self.clock, READY, snap=False)
        r = runner(self.tmp, phone, self.clock)
        rc = r.main(ui_run.parse_script('wait_home\ntap 692 1780 app=Preferences\nshot x\n'))
        self.assertEqual(rc, 0, r.steps)
        self.assertEqual(r.steps[0]['state'], 'HOME_NOSNAP')
        self.assertTrue(r.steps[1]['app'])

    def test_sigterm_still_writes_the_report(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        r = runner(self.tmp, phone, self.clock)

        def stop(_s):
            raise ui_run.Stopped()
        r.sleep = stop
        self.assertEqual(r.main(ui_run.parse_script('sleep 5\n')), 1)
        self.assertEqual(json.loads((Path(self.tmp) / 'run/ui_run.json').read_text())['verdict'], 'FAIL')

    def test_gray_png_and_find_text(self):
        png = ui_run.gray_png(frame(20), W, H, 3)
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', png[16:24]), (W * 3, H * 3))
        words = [('About', 10, 100, 40, 10, 90.0, ('1', '1', '1')), ('Software', 10, 300, 60, 10, 90.0, ('2', '1', '1')),
                 ('Update', 75, 300, 50, 10, 90.0, ('2', '1', '1')), ('About', 10, 900, 40, 10, 90.0, ('3', '1', '1'))]
        self.assertEqual(ui_run.find_text(words, 'software update'), [(67.5, 305.0)])
        self.assertEqual(len(ui_run.find_text(words, 'about')), 2)
        self.assertEqual(ui_run.find_text(words, 'about', 'top', 1000), [(30.0, 105.0)])


class LaneToolsTests(unittest.TestCase):
    """2026-11-04 fixes: hands on the phone, cheap polls, OCR that reads the phone's frames."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clock = Clock()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_physical_buttons_during_a_tap_mark_it_interfered(self):
        # int4-confirm 03:46:13: volume down + power held by hand -> power-off / Emergency SOS screen
        hands = ['blazer-keys: volume down pressed', 'SWEET PHYSICAL: epoch=3 key=2 usage=0xea down clients=1 callback',
                 'blazer-power-key: pressed']
        phone = FakePhone(self.tmp, self.clock, READY, hands_on_tap=hands)
        r = runner(self.tmp, phone, self.clock)
        rc = r.main(ui_run.parse_script('tap 692 1780\nshot x\n'))
        self.assertEqual(rc, 1)
        self.assertEqual(r.steps[0]['verdict'], 'FAIL')
        self.assertIn('INTERFERED', r.steps[0]['state'])
        self.assertEqual(len(r.steps[0]['physical']), 2)
        report = json.loads((Path(self.tmp) / 'run/ui_run.json').read_text())
        self.assertEqual(report['physical_input'][0]['count'], 2)
        self.assertIn('PHYSICAL 2', (Path(self.tmp) / 'run/ui_run.log').read_text())
        self.assertIn('Physical input', (Path(self.tmp) / 'run/ui_run.md').read_text())

    def test_real_touch_on_the_glass_is_reported_injected_is_not(self):
        phone = FakePhone(self.tmp, self.clock, READY,
                          hands_on_tap=['blazer-touch: tcm: finger 0 down at 40496, 44737',
                                        'blazer-haptic: SWEET HID: touch 0 down at 790,1948 (1 clients)'])
        r = runner(self.tmp, phone, self.clock)
        r.main(ui_run.parse_script('tap 500 500\ntap 500 500\n'))
        self.assertEqual([s['verdict'] for s in r.steps], ['FAIL', 'PASS'])     # HK LIVE lines alone are not physical
        self.assertFalse(ui_run.RX['physical'].search('HK LIVE dispatch gen=5 edge=down op=98 x=170 y=279'))
        self.assertTrue(ui_run.RX['physical'].search('03:45:43.547 [  404.38] tcm: finger 0 down at 45924, 31125'))

    def test_polls_are_step_16_and_shots_step_8(self):
        phone = FakePhone(self.tmp, self.clock, READY)
        r = runner(self.tmp, phone, self.clock)
        r.main(ui_run.parse_script('tap 500 500\nshot x\nswipe 562 1900 562 800\nhome\n'))
        steps = {}
        for c in phone.calls:
            if c[0] == '--snapshot':
                steps.setdefault(c[2].split('-', 1)[1], set()).add(c[-1])
        self.assertEqual(steps['pre'], {str(ui_run.POLL_STEP)})
        self.assertEqual(steps['after'], {str(ui_run.POLL_STEP)})
        self.assertEqual(steps['x'], {str(ui_run.SNAP_STEP)})
        self.assertEqual(steps['home'], {str(ui_run.POLL_STEP)})
        r2 = runner(tempfile.mkdtemp(dir=self.tmp), phone, self.clock, poll_step=8)
        self.assertEqual(r2.poll_step, 8)

    def test_ocr_tolerant_match(self):
        self.assertTrue(ui_run.near('Wi-Fl', 'wi-fi'))           # what tesseract read on the int2-ui Wi-Fi page
        self.assertTrue(ui_run.near('Genera1', 'general'))
        self.assertTrue(ui_run.near('Versiom', 'version'))
        self.assertFalse(ui_run.near('Edit', 'exit'))            # short words must match exactly (after look-alikes)
        self.assertFalse(ui_run.near('Phone', 'Photos'))
        words = [('Wi-Fl', 10, 100, 40, 10, 90.0, ('1', '1', '1'))]
        self.assertEqual(ui_run.find_text(words, 'Wi-Fi'), [(30.0, 105.0)])

    def test_gray_png_inverts_a_dark_screen_and_scales_smoothly(self):
        import zlib
        dark = frame(2)
        png = ui_run.gray_png(dark, W, H, 4)
        self.assertEqual(struct.unpack('>II', png[16:24]), (W * 4, H * 4))
        i = png.index(b'IDAT')
        n = struct.unpack('>I', png[i - 4:i])[0]
        rows = zlib.decompress(png[i + 4:i + 4 + n])
        self.assertGreater(sum(rows) / len(rows), 128)           # light ground: tesseract reads dark text best

    def test_ocr_reads_real_phone_frames(self):
        """HOST OCR of PHYSICAL frames from the int2-ui boot (research/, not in CI; skipped without it or tesseract)."""
        base = ROOT / 'research/laguna-usb-fix/attempts/live-20261103-224007-a7-int2-ui/ui'
        if not shutil.which('tesseract') or not (base / '0027-027-ocr.rgb565').is_file():
            self.skipTest('no tesseract or no int2-ui frames')
        for name, w, h, text in (('0027-027-ocr', 188, 419, 'Wi-Fi'), ('0010-010-settings', 141, 314, 'General')):
            png = Path(self.tmp) / f'{name}.png'
            png.write_bytes(ui_run.gray_png((base / f'{name}.rgb565').read_bytes(), w, h, ui_run.OCR_SCALE))
            self.assertTrue(ui_run.find_text(ui_run.ocr_words(png), text), name)


class HkDbgTests(unittest.TestCase):
    def test_int2_token(self):
        v = hk_dbg.encode(input=True, snap=True, usertrace=True, ustack=True, crashinfo=True, screen=30, top=30)
        self.assertEqual(hk_dbg.token(v), 'hk_dbg=0x1e1e1f')
        self.assertEqual(hk_dbg.tokens(v), ['blazer_usbcon_input=1', 'blazer_usbcon_snap=1', 'hk_usertrace=1',
                                            'hk_ustack=Preferences,MobilePhone', 'hk_crashinfo=1', 'hk_screen=30', 'hk_top=30'])
        self.assertEqual(hk_dbg.token(hk_dbg.encode(input=True)), 'hk_dbg=0x1')

    def test_refusals(self):
        for kw in (dict(screen=5), dict(top=3), dict(crashinfo=True), dict()):
            with self.assertRaises(ValueError):
                hk_dbg.encode(**kw)
        with self.assertRaises(ValueError):
            hk_dbg.decode(0x20)

    def test_layout_matches_kernel_header(self):
        """Compile the uidrive C test against the kernel's hk_dbg.h and compare its printed layout."""
        cc = shutil.which('cc')
        if not cc:
            self.skipTest('no cc')
        src = ROOT / 'research/ios26-phaseb-r1/live/uidrive'
        if not (src / 'test/test_tap_hold.c').is_file():
            self.skipTest('research/ uidrive sources absent (CI)')
        out = Path(tempfile.mkdtemp()) / 't'
        subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', src / 'xnu-src/osfmk/arm64', '-I', src / 'xnu-src/osfmk',
                        src / 'test/test_tap_hold.c', '-o', out], check=True)
        text = subprocess.run([out], capture_output=True, text=True, check=True).stdout
        line = [l for l in text.splitlines() if l.startswith('HKDBG ')][0]
        got = dict(kv.split('=') for kv in line.split()[1:])
        names = dict(input='INPUT', snap='SNAP', usertrace='UTRACE', ustack='USTACK', crashinfo='CRASHINFO')
        self.assertEqual({n: str(b) for n, b, _ in hk_dbg.FLAGS}, {n: got[k] for n, k in names.items()})
        self.assertEqual((got['SCREEN_SHIFT'], got['TOP_SHIFT'], got['NAMES']), ('8', '16', 'Preferences,MobilePhone'))
        self.assertIn('PASS: 0 failures', text)


if __name__ == '__main__':
    unittest.main()
