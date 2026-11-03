#!/usr/bin/env python3
"""Host tests for tools/hk_cycle.py: fake adb/fastboot/mac (one shared phone state machine), a fake live_boot.sh, fake
screenshot.sh and return-check.sh. Never touches a device.  python3 -I tools/test_hk_cycle.py [-v]"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/hk_cycle.py'
spec = importlib.util.spec_from_file_location('hk_cycle', TOOL)
hc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hc)
lp_spec = importlib.util.spec_from_file_location('live_profile', ROOT / 'tools/live_profile.py')
lp = importlib.util.module_from_spec(lp_spec)
lp_spec.loader.exec_module(lp)

UUID = bytes(range(16))
SERIAL = 'FAKESER1AL99'

# ------------------------------------------------------------------------------------------- the fake phone
PHONE = r'''
import fcntl, hashlib, json, os, select, sys, time
from pathlib import Path
STATE = os.environ['FAKE_PHONE']
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
f = open(STATE + '.lock', 'w'); fcntl.flock(f, fcntl.LOCK_EX)
st = json.load(open(STATE))
now = time.time()
def advance():
    if st['mode'] == 'ios' and st.get('park_at') and now >= st['park_at']:
        st['mode'] = st.get('ios_ends', 'fastboot'); st['park_at'] = None
        if st['mode'] == 'android': st['boot_completed_at'] = now
advance()
try:
    stdin_open = not select.select([0], [], [], 0)[0]       # an open pipe with nothing written is not readable
except (OSError, ValueError):
    stdin_open = False
st['calls'].append(dict(tool=tool, args=args, t=now, mode=st['mode'], stdin_open=stdin_open))
out, err, rc = '', '', 0
S = st['serial']
if tool == 'fastboot':
    a = [x for x in args if x not in ('-s', S)]
    if a == ['devices']:
        out = f'{S}\tfastboot\n' if st['mode'] == 'fastboot' else ''
    elif st['mode'] != 'fastboot':
        err, rc = '< waiting for any device >\n', 1
        if a[:1] != ['devices']: time.sleep(0.2)
    elif a == ['getvar', 'product']:
        err = 'product: laguna\nFinished.\n'
    elif a[:2] == ['oem', 'force-fastboot'] and len(a) == 3:
        st['ff'] = a[2] == 'on'; err = 'OKAY\n'
    elif a == ['oem', 'force-fastboot']:
        err = f"(bootloader) force-fastboot {'on' if st['ff'] else 'off'}\nOKAY\n"
    elif a[:1] == ['boot']:
        st['mode'] = 'ios'; st['park_at'] = now + st.get('park_after', 2); st['booted'].append(a[1]); err = 'Booting OKAY\n'
    elif a == ['reboot']:
        if st['ff']:
            st['mode'] = 'fastboot'
        else:
            st['mode'] = st.get('reboot_to', 'android'); st['boot_completed_at'] = now + 0.5
        err = 'Rebooting OKAY\n'
    else:
        err, rc = f'fake fastboot: unsupported {a}\n', 1
elif tool == 'adb':
    if args == ['devices']:
        out = 'List of devices attached\n' + ({'android': f'{S}\tdevice\n', 'recovery': f'{S}\trecovery\n'}.get(st['mode'], ''))
    elif st['mode'] not in ('android',):
        err, rc = 'adb: no devices/emulators found\n', 1
    elif args == ['reboot', 'bootloader']:
        st['mode'] = 'fastboot'
    elif args == ['shell', 'getprop', 'sys.boot_completed']:
        out = '1\n' if now >= st.get('boot_completed_at', 0) else '\n'
    elif args == ['get-state']:
        out = 'device\n'
    else:
        err, rc = f'fake adb: unsupported {args}\n', 1
elif tool == 'mac':
    if args[:1] == ['usb']:
        out = ('  1209:0002  hackios XNU console [ios-laguna]  (480 Mb/s)\n' if st['mode'] == 'ios' else
               '  18d1:4ee0  Pixel 10 Pro [Google]  (480 Mb/s)\n' if st['mode'] in ('android', 'fastboot', 'recovery') else '')
    elif args[:1] == ['--cd'] and args[3:] == ['git', 'rev-parse', 'HEAD']:
        out = st.get('mac_head', 'a' * 40) + '\n'
        if st.get('mac_down'): out, err, rc = '', 'phone-bridge: tunnel to anders-macbook-pro is down\n', 1
    elif args[:1] == ['--cd'] and args[3:5] == ['sh', '-c']:
        rel = args[5].split("'")[1] if "'" in args[5] else args[5].split()[3]
        if rel in st['mac_files']: out = f"{st['mac_files'][rel]}  {rel}\n"
    elif args[:1] == ['repo']:
        i = args.index('--')
        opts, cmd = args[1:i], args[i + 1:]
        for j, o in enumerate(opts):
            if o == '--sync':
                rel = opts[j + 1]
                if rel not in st['mac_files'] or '--overwrite' in opts:
                    st['mac_files'][rel] = hashlib.sha256(Path(st['root'], rel).read_bytes()).hexdigest()
        if cmd and len(cmd) > 1 and cmd[1] == 'tools/capture-fastboot.py':
            if st['mode'] != 'fastboot':
                err, rc = 'not in fastboot\n', 1
            else:
                d = Path(st['root'], cmd[2]); d.mkdir(parents=True, exist_ok=True)
                (d / 'kernel.log').write_bytes(Path(st['dump']).read_bytes()); out = 'captured kernel.log\n'
    else:
        err, rc = f'fake mac: unsupported {args}\n', 1
json.dump(st, open(STATE + '.tmp', 'w')); os.replace(STATE + '.tmp', STATE)
sys.stdout.write(out); sys.stderr.write(err); sys.exit(rc)
'''

LIVE_BOOT = r'''
import json, os, sys, time, signal
from pathlib import Path
STATE = os.environ['FAKE_PHONE']
def load(): return json.load(open(STATE))
def save(st): json.dump(st, open(STATE + '.tmp', 'w')); os.replace(STATE + '.tmp', STATE)
image, name = sys.argv[1], sys.argv[2]
st = load()
st['calls'].append(dict(tool='live_boot', args=sys.argv[1:], t=time.time(), mode=st['mode'], stdin_open=True)); save(st)
if st.get('lb_rc') == 3:
    print('live_boot: the console reader exited before the boot; not booting.'); sys.exit(3)
run = Path(st['root'], st['live_dir'], f'live-x-{name}'); run.mkdir(parents=True, exist_ok=True)
(run / 'live.env').write_text(f'LIVE_RUN={run}\nLIVE_SOCK=/tmp/fake.sock\nLIVE_T0={time.time()}\n')
print(f'live_boot: run {run}', flush=True)
stop = []
signal.signal(signal.SIGTERM, lambda *a: stop.append(1))
st = load(); st['mode'] = 'ios'; st['ff'] = True; st['park_at'] = None if st.get('lb_hang') else time.time() + st.get('park_after', 2)
st['booted'].append(image); save(st)
lines = st['console'].splitlines()
with open(run / 'console.txt', 'w') as c, open(run / 'markers.txt', 'w') as m:
    for l in lines:
        c.write('12:00:00.000 ' + l + '\n')
    m.write('LIVEBOOT 12:00:00.100 +1.0 CONSOLE_CONNECTED nonce 0x1\nLIVEBOOT 12:00:00.200 +1.2 DISPLAY layer 0\n')
    m.write('LIVEBOOT 12:00:01.000 +2.0 TOUCH_CLIENT\n')
print('LIVEBOOT 12:00:00.100 +1.0 CONSOLE_CONNECTED nonce 0x1', flush=True)
while not stop:
    st = load()
    if st['mode'] == 'ios' and st.get('park_at') and time.time() >= st['park_at']:
        st['mode'] = 'fastboot'; st['park_at'] = None; save(st)
    if st['mode'] == 'fastboot':
        break
    time.sleep(0.1)
if stop:
    print('live_boot: interrupted'); sys.exit(130)
att = Path(st['root'], st['live_dir'], f'20261103-000000-{name}')
(att / 'ramdump').mkdir(parents=True, exist_ok=True)
(att / 'ramdump/kernel.log').write_bytes(Path(st['dump']).read_bytes())
(att / 'park-timeline.txt').write_text('ep0_to_park_s: 2\nabl_reboot_reason: 0xbab9\nabl_rst_stat_terminal: 0x3 - Fatal Error SW\n')
mac_att = f"/Users/x/{st['mac_dir']}/{att.relative_to(st['root'])}"
print(f'[run-attempt] attempt dir: {mac_att}')
print('LIVEBOOT 12:00:05.000 +5.0 PARKED PARKED in fastboot at watch t+3s', flush=True)
with open(run / 'live.env', 'a') as e:
    e.write(f'ATTEMPT={mac_att}\nBOOT_RC=0\n')
sys.exit(0)
'''

SCREENSHOT = r'''
import sys, zlib, struct
from pathlib import Path
a = sys.argv[1:]
out = a[a.index('-o') + 1]
def chunk(k, b): return struct.pack('>I', len(b)) + k + b + struct.pack('>I', zlib.crc32(k + b) & 0xffffffff)
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\0\0\0')) + chunk(b'IEND', b'')
Path(out).write_bytes(png); print(out)
'''

RETURN_CHECK = r'''
import json, os, sys
from pathlib import Path
st = json.load(open(os.environ['FAKE_PHONE']))
o = Path(sys.argv[1]); o.mkdir(parents=True, exist_ok=True)
v = 'PASS' if st['mode'] == 'android' and not st['ff'] else 'FAIL: boot_completed'
(o / 'return-check.json').write_text(json.dumps(dict(verdict=v, boot_completed=v == 'PASS', kernel_code_base='0xc9c00000')))
print(v)
'''

USBCON = r'''
import sys, time
print('usbcon: connected: nonce 0x1, entry 0x2, stream 10 bytes, ring 1048576', flush=True)
print('SWEET HID: SweetHIDTouch open by backboardd', flush=True)
time.sleep(1.5)
print('usbcon: end: device gone', flush=True)
'''

CONSOLE = '''\
blazer-root: ufsroot0, rooting on ufsroot0
exec launchd
exec SpringBoard
SWEET HID: SweetHIDTouch open by backboardd
SWEET HID: SweetHIDButtons open by backboardd
HK TOP: t=60 frames+12 cpu_ms=10:
exec Preferences
HKMAIN: Preferences[300] t=10 pings=9 wait=0 state=0 ev touch=3 press=0 other=0 stalls=0
exec AccessibilityUIServer
exec AccessibilityUIServer
exec AccessibilityUIServer
blazer-rtc: publish want 1 calendar 1 usec 1 gap_s 1 repaired 0 ok 1 sample_up 1 ms
'''
DUMP_EXTRA = 'panic(cpu 0 caller 0xfffffe0000000000): blazer-root: deadline 900 s, stage pid1_exec\n'

EXPECT = '''\
name: fake
probes:
  - id: boot.home
    feature: Home
    need: ['(?:^|\\s)exec SpringBoard$']
    marker: HOME
  - id: S
    feature: Settings touched
    values:
      - {re: 'HKMAIN: Preferences\\[\\d+\\] .* ev touch=(\\d+)', agg: max, min: 1}
  - id: T
    feature: RTC
    need: ['blazer-rtc: publish .* ok 1']
    forbid: ['localtime link invalid']
  - id: K
    feature: keys
    need: ['SWEET PHYSICAL: .* usage=0xe9']
    needs_input: true
    required: false
  - id: end
    feature: deadline
    need: ['^panic\\(.*blazer-root: deadline']
    source: dump
    required: false
'''


def synthetic_dump(text, nonce=0x1234):
    raw = bytearray(0x400000)
    body = text.encode()
    size = 0x100000
    raw[lp.HDR_OFF:lp.HDR_OFF + lp.MIRROR.size] = lp.MIRROR.pack(b'XNU-MSGBUF v2', 1, 0, 0, 0, size, len(body), len(body), 0, len(body))
    raw[lp.HDR_OFF + 0x40:lp.HDR_OFF + 0x40 + lp.ENTRY.size] = lp.ENTRY.pack(b'XNUENT1', nonce, 100, 0, 24000000, 7, 0, 0, 0)
    raw[lp.RING_OFF:lp.RING_OFF + len(body)] = body
    return bytes(raw)


def fake_mach(uuid=UUID):
    cmd = struct.pack('<II', 0x1b, 24) + uuid
    return struct.pack('<IiiIIIII', 0xfeedfacf, 0x0100000c, 0, 2, 1, len(cmd), 0, 0) + cmd


class Rig:
    """A temporary image/kernel/cycle area inside the checkout (the tool refuses paths the Mac mirror cannot see)."""
    def __init__(self, chooser=False, mode='fastboot', cmdline=None, **state):
        self.base = Path(tempfile.mkdtemp(prefix='.test-', dir=ROOT / 'research/hk-cycles' if (ROOT / 'research/hk-cycles').is_dir()
                                          else (ROOT / 'research/hk-cycles').mkdir(parents=True) or ROOT / 'research/hk-cycles'))
        self.bin = Path(tempfile.mkdtemp(prefix='hkc-bin-'))
        idir = self.base / ('images/chooser-fake' if chooser else 'images/a7-fake')
        idir.mkdir(parents=True)
        self.image = idir / 'boot.img'
        self.image.write_bytes(b'ANDROID!' + b'\0' * 4096 + UUID + b'\0' * 4096)
        self.mach = self.base / 'kernel.fake.unstripped'
        self.mach.write_bytes(fake_mach())
        cl = cmdline or 'blazer_deadline=4 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_snap=1 hk_screen=30'
        man = dict(kind='chooser-ios', name='chooser-fake', ios=dict(cmdline=cl)) if chooser else dict(name='a7-fake', cmdline=cl)
        (idir / 'manifest.json').write_text(json.dumps(man))
        self.dump = self.base / 'dump.bin'
        self.dump.write_bytes(synthetic_dump(CONSOLE + DUMP_EXTRA))
        self.expect = self.base / 'expect.yaml'
        self.expect.write_text(EXPECT)
        self.state = self.base / 'phone.json'
        st = dict(mode=mode, ff=False, serial=SERIAL, calls=[], booted=[], mac_files={}, root=str(ROOT), park_after=2,
                  dump=str(self.dump), console=CONSOLE, live_dir=str(self.base.relative_to(ROOT)), mac_dir='Developer/personal/hackios')
        st.update(state)
        self.state.write_text(json.dumps(st))
        for name in ('adb', 'fastboot', 'mac'):
            self.script(name, PHONE)
        self.script('live_boot.sh', LIVE_BOOT)
        self.script('screenshot.sh', SCREENSHOT)
        self.script('usbcon', USBCON)
        self.script('return-check.sh', '#!/bin/bash\nexec "%s" "%s" "$@"\n' % (sys.executable, self.bin / 'rc.py'), raw=True)
        (self.bin / 'rc.py').write_text(RETURN_CHECK)
        self.out = self.base / 'cycle'

    def script(self, name, body, raw=False):
        p = self.bin / name
        p.write_text(body if raw else f'#!{sys.executable}\n' + body)
        p.chmod(0o755)

    def env(self):
        e = dict(os.environ)
        e.pop('ANDROID_SERIAL', None)
        e.update(HK_CYCLE_PB=str(self.bin), HK_CYCLE_LIVE_BOOT=str(self.bin / 'live_boot.sh'), HK_CYCLE_SCREENSHOT=str(self.bin / 'screenshot.sh'),
                 HK_CYCLE_RETURN_CHECK=str(self.bin / 'return-check.sh'), HK_CYCLE_MAC_DIR='Developer/personal/hackios',
                 HK_CYCLE_USBCON_CMD=f'{sys.executable} {self.bin / "usbcon"}', FAKE_PHONE=str(self.state))
        return e

    def argv(self, *extra, expect=True):
        a = [sys.executable, '-I', str(TOOL), '--image', str(self.image.parent), '--mach', str(self.mach), '--out', str(self.out),
             '--skip-image-check', '--poll', '0.2', '--shot-every', '0.5', '--cache', '/nonexistent',
             '--timeouts', 'settle=0.5,shot_start=0.2,console_start=0.5,park_wait=6,android_boot=6,to_fastboot=5,unknown_wait=1,boot_extra=10']
        if expect:
            a += ['--expect', str(self.expect)]
        return a + list(extra)

    def run(self, *extra, expect=True, timeout=90):
        return subprocess.run(self.argv(*extra, expect=expect), env=self.env(), capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)

    def phone(self):
        return json.loads(self.state.read_text())

    def report(self):
        return json.loads((self.out / 'report.json').read_text())

    def summary(self):
        return json.loads((self.out / 'summary.json').read_text())

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)
        shutil.rmtree(self.bin, ignore_errors=True)


FORBIDDEN = ('flash', 'erase', 'format', 'set_active', '--set-active', 'flashing', 'wipe-super', 'update')


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.rigs = []

    def tearDown(self):
        for r in self.rigs:
            r.close()

    def rig(self, **kw):
        r = Rig(**kw)
        self.rigs.append(r)
        return r

    def assert_safe(self, r):
        calls = r.phone()['calls']
        for c in calls:
            if c['tool'] in ('fastboot', 'adb'):
                self.assertFalse(set(c['args']) & set(FORBIDDEN), c)
                self.assertTrue(c['stdin_open'], f'stdin closed for {c}')
        return calls

    def test_bootios_cycle_from_android_passes_and_returns(self):
        r = self.rig(mode='android', boot_completed_at=0)
        p = r.run()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep, summ = r.report(), r.summary()
        self.assertEqual(rep['verdict'], 'PASS')
        self.assertEqual(summ['schema'], 'hk_cycle.summary/1')
        self.assertEqual(summ['rows'], {'boot.home': 'PASS', 'S': 'PASS', 'T': 'PASS', 'K': 'NOT_EXERCISED', 'end': 'PASS'})
        self.assertTrue(summ['android'])
        self.assertEqual(summ['return_check'], 'PASS')
        self.assertTrue(summ['home'])
        ph = r.phone()
        self.assertEqual(ph['mode'], 'android')
        self.assertFalse(ph['ff'], 'force-fastboot must be off at the end')
        calls = self.assert_safe(r)
        seq = [(c['tool'], ' '.join(c['args'])) for c in calls]
        self.assertIn(('adb', 'reboot bootloader'), seq)
        lb = next(c for c in calls if c['tool'] == 'live_boot')
        self.assertIn('--wait', lb['args'])
        self.assertEqual(lb['args'][lb['args'].index('--wait') + 1], '184')       # blazer_deadline 4 + 180
        i_off = seq.index(('fastboot', 'oem force-fastboot off'))
        i_reboot = seq.index(('fastboot', 'reboot'))
        self.assertLess(i_off, i_reboot)
        md = (r.out / 'report.md').read_text()
        self.assertIn('![', md)
        self.assertIn('screens/hk_screen.png', md)
        self.assertTrue((r.out / 'screens/hk_screen.png').is_file())
        self.assertTrue(any(s['kind'] == 'live' and s['ok'] for s in rep['screenshots']))
        self.assertTrue(rep['analysis']['respawns'] and rep['analysis']['respawns'][0]['name'] == 'AccessibilityUIServer')
        # serials never reach a file
        for f in r.out.rglob('*'):
            if f.is_file():
                self.assertNotIn(SERIAL, f.read_text(errors='replace'), f)

    def test_phone_in_ios_is_refused_untouched(self):
        r = self.rig(mode='ios')
        p = r.run()
        self.assertEqual(p.returncode, hc.EXIT_PREFLIGHT, p.stdout + p.stderr)
        rep = r.report()
        self.assertEqual(rep['verdict'], 'REFUSED')
        self.assertEqual(rep['errors'][0]['state'], 'PHONE_IN_IOS')
        changed = [c for c in r.phone()['calls'] if c['tool'] in ('adb', 'fastboot') and c['args'] not in (['devices'],)]
        self.assertEqual(changed, [])

    def test_kernel_not_in_image_is_refused(self):
        r = self.rig()
        r.mach.write_bytes(fake_mach(b'\xee' * 16))
        p = r.run()
        self.assertEqual(p.returncode, hc.EXIT_PREFLIGHT)
        self.assertEqual(r.report()['errors'][0]['state'], 'KERNEL_MISMATCH')
        self.assertEqual(r.phone()['booted'], [])

    def test_image_check_failure_is_refused(self):
        r = self.rig()
        argv = [a for a in r.argv() if a != '--skip-image-check']
        p = subprocess.run(argv, env=r.env(), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, hc.EXIT_PREFLIGHT, p.stdout + p.stderr)
        self.assertEqual(r.report()['errors'][0]['state'], 'IMAGE_CHECK_FAILED')

    def test_different_mac_copy_refused_then_overwritten(self):
        r = self.rig()
        st = r.phone()
        st['mac_files'][str(r.image.relative_to(ROOT))] = '0' * 64
        r.state.write_text(json.dumps(st))
        p = r.run()
        self.assertEqual(p.returncode, hc.EXIT_PREFLIGHT)
        self.assertEqual(r.report()['errors'][0]['state'], 'MAC_COPY_DIFFERS')
        shutil.rmtree(r.out)
        p = r.run('--overwrite-mac')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertNotEqual(r.phone()['mac_files'][str(r.image.relative_to(ROOT))], '0' * 64)

    def test_mac_down_is_refused(self):
        r = self.rig(mac_down=True)
        p = r.run()
        self.assertEqual(p.returncode, hc.EXIT_PREFLIGHT)
        self.assertEqual(r.report()['errors'][0]['state'], 'MAC_UNREACHABLE')

    def test_console_refused_returns_to_android(self):
        r = self.rig(mode='android', lb_rc=3)
        p = r.run()
        self.assertEqual(p.returncode, hc.EXIT_BOOT, p.stdout + p.stderr)
        rep = r.report()
        self.assertEqual(rep['errors'][0]['state'], 'CONSOLE_REFUSED')
        self.assertTrue(rep['return']['android'])
        self.assertEqual(r.phone()['mode'], 'android')
        self.assert_safe(r)

    def test_never_parks_leaves_ios_and_says_so(self):
        r = self.rig(lb_hang=True)
        argv = r.argv('--deadline-wait', '1')
        argv[argv.index('--timeouts') + 1] = argv[argv.index('--timeouts') + 1].replace('boot_extra=10', 'boot_extra=1,boot_watch=1')
        p = subprocess.run(argv, env=r.env(), capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, hc.EXIT_NOT_ANDROID, p.stdout + p.stderr)
        rep = r.report()
        self.assertIn('BOOT_TIMEOUT', [e['state'] for e in rep['errors']])
        self.assertEqual(rep['verdict'], 'PHONE_NOT_IN_ANDROID')
        self.assertEqual(r.phone()['mode'], 'ios')       # never a cold reset

    def test_ctrl_c_twice_abandons_boot_and_still_returns(self):
        r = self.rig(lb_hang=True)
        st = r.phone()
        st['park_after'] = 1
        r.state.write_text(json.dumps(st))
        p = subprocess.Popen(r.argv(), env=r.env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, stdin=subprocess.DEVNULL)
        lines = []
        for line in p.stdout:
            lines.append(line)
            if 'live run' in line:
                break
        time.sleep(0.5)
        p.send_signal(signal.SIGINT)
        time.sleep(0.5)
        # the fake iOS boot "reaches its deadline" so the return can proceed
        st = r.phone()
        st['park_at'] = time.time() + 1
        r.state.write_text(json.dumps(st))
        p.send_signal(signal.SIGINT)
        out = p.communicate(timeout=90)[0]
        self.assertEqual(p.returncode, hc.EXIT_INTERRUPTED, ''.join(lines) + out)
        rep = r.report()
        self.assertTrue(rep['return']['android'])
        self.assertEqual(r.phone()['mode'], 'android')
        self.assertFalse(r.phone()['ff'])
        self.assertIn('INTERRUPTED', [e['state'] for e in rep['errors']])

    def test_plain_mode_chooser_parks_captures_returns(self):
        r = self.rig(chooser=True)
        p = r.run('--no-sync-tools')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        rep = r.report()
        self.assertEqual(rep['image']['mode'], 'plain')
        calls = self.assert_safe(r)
        seq = [(c['tool'], ' '.join(c['args'])) for c in calls]
        self.assertIn(('fastboot', 'oem force-fastboot on'), seq)
        self.assertLess(seq.index(('fastboot', 'oem force-fastboot on')), [i for i, s in enumerate(seq) if s[1].startswith('boot ')][0])
        self.assertTrue(any(s[0] == 'mac' and 'tools/capture-fastboot.py' in s[1] for s in seq))
        self.assertTrue(list(r.out.glob('*/ramdump/kernel.log')))
        self.assertEqual(r.phone()['mode'], 'android')
        live = next(r.out.glob('live-*'))
        self.assertIn('SweetHIDTouch', (live / 'console.txt').read_text())

    def test_plain_chooser_to_android_disarms_force_fastboot(self):
        r = self.rig(chooser=True, ios_ends='android')
        p = r.run('--no-sync-tools')
        rep = r.report()
        self.assertEqual(rep['image']['plain_outcome'], 'android', p.stdout)
        ph = r.phone()
        self.assertFalse(ph['ff'])
        self.assertEqual(ph['mode'], 'android')
        seq = [(c['tool'], ' '.join(c['args'])) for c in ph['calls']]
        i_boot = [i for i, s in enumerate(seq) if s[1].startswith('boot ')][0]
        self.assertIn(('adb', 'reboot bootloader'), seq[i_boot:])

    def test_report_only_reanalyses(self):
        r = self.rig()
        self.assertEqual(r.run().returncode, 0)
        (r.out / 'report.md').unlink()
        p = subprocess.run([sys.executable, '-I', str(TOOL), '--report-only', str(r.out), '--cache', '/nonexistent'],
                           env=r.env(), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue((r.out / 'report.md').is_file())
        self.assertEqual(r.summary()['verdict'], 'PASS')
        # a required row that needs input and got none keeps the cycle INCOMPLETE (exit 1), never PASS
        strict = r.base / 'strict.yaml'
        strict.write_text(EXPECT.replace('    required: false\n', '', 1))
        p = subprocess.run([sys.executable, '-I', str(TOOL), '--report-only', str(r.out), '--expect', str(strict), '--cache', '/nonexistent'],
                           env=r.env(), capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, hc.EXIT_FAIL, p.stdout + p.stderr)
        self.assertEqual(r.summary()['verdict'], 'INCOMPLETE')
        self.assertEqual(r.summary()['rows']['K'], 'NOT_EXERCISED')


class UnitTests(unittest.TestCase):
    def doc(self, rows):
        return dict(expect=rows)

    def test_evaluate_kinds(self):
        src = dict(live='a 1\nHKMAIN: x touch=5\nbad thing\n', dump='')
        rows = hc.evaluate(self.doc([
            dict(id='need', need=['^a \\d$']),
            dict(id='forbid', need=['^a'], forbid=['bad']),
            dict(id='val', values=[dict(re='touch=(\\d+)', agg='max', min=6)]),
            dict(id='input', need=['nothere'], needs_input=True),
            dict(id='marker', marker='HOME'),
            dict(id='any', any=['zzz', 'touch=']),
            dict(id='dumponly', need=['^a'], source='dump'),
        ]), src, {'HOME'}, dict(ran=False))
        v = {r['id']: r['verdict'] for r in rows}
        self.assertEqual(v, dict(need='PASS', forbid='FAIL', val='FAIL', input='NOT_EXERCISED', marker='PASS', any='PASS', dumponly='NO_DATA'))
        rows = hc.evaluate(self.doc([dict(id='input', need=['nothere'], needs_input=True)]), src, set(), dict(ran=True))
        self.assertEqual(rows[0]['verdict'], 'FAIL')

    def test_load_expect_rejects_bad_rows(self):
        d = Path(tempfile.mkdtemp())
        try:
            for body in ['probes:\n  - id: a\n    nope: 1\n', 'probes:\n  - feature: x\n', 'probes:\n  - id: a\n  - id: a\n',
                         "probes:\n  - id: a\n    values: [{re: 'x'}]\n", 'nothing: 1\n']:
                (d / 'e.yaml').write_text(body)
                with self.assertRaises(ValueError, msg=body):
                    hc.load_expect(d / 'e.yaml')
        finally:
            shutil.rmtree(d)

    def test_shipped_expect_files_parse(self):
        for f in sorted((ROOT / 'research/ios26-phaseb-r1/live/expect').glob('*.yaml')):
            doc = hc.load_expect(f)
            self.assertTrue(doc['expect'], f)

    def test_home_rule_without_ui_ready(self):
        text = 'exec SpringBoard\nSWEET HID: SweetHIDTouch open by b\nSWEET HID: SweetHIDButtons open by b\nSWEET FB: rate swaps 0.2/s\n'
        self.assertTrue(hc.home_rule({}, dict(live=text))['home'])
        self.assertFalse(hc.home_rule({}, dict(live=text.replace('exec SpringBoard', '')))['home'])
        self.assertTrue(hc.home_rule({'UI_READY': {}}, {})['home'])

    def test_redact(self):
        os.environ.pop('ANDROID_SERIAL', None)
        self.assertEqual(hc.redact('List of devices attached\nABCDEF123\tdevice\n'), 'List of devices attached\nSERIAL\tdevice\n')
        self.assertEqual(hc.redact('X1Y2' + 'Z3W4\tfastboot\n'), 'SERIAL\tfastboot\n')
        self.assertIn('serial' 'no: SERIAL', hc.redact('serial' 'no: ' + '1234' + 'ABCD99'))

    def test_dump_text_and_console_analysis(self):
        d = Path(tempfile.mkdtemp())
        try:
            text = CONSOLE + 'usertrap: MobilePhone[415] exception 6 code 0x1 0x10052ebc0: pc 0x10052ebc0 lr 0x10052eb64 sp 0x16fab2c50, ' \
                'shared cache slide 0xec70000, main header 0x10034c000\r\nusertrap:   called from 0x10052eacc\n' + DUMP_EXTRA
            (d / 'kernel.log').write_bytes(synthetic_dump(text))
            t, meta = hc.dump_text(d / 'kernel.log')
            self.assertNotIn('\r', t)
            a = hc.analyse_console(t, hc.Symbolizer('/nonexistent'))
            self.assertEqual(a['crashes'][0]['name'], 'MobilePhone')
            self.assertEqual(a['crashes'][0]['top'][:3], ['main+0x1e2bc0', 'main+0x1e2b64', 'main+0x1e2acc'])
            self.assertEqual(a['panics'][0]['kind'], 'deadline')
            self.assertEqual(a['respawns'][0], dict(name='AccessibilityUIServer', respawns=2, crashed_in_a_row=None))
            self.assertEqual(a['hkmain']['Preferences[300]']['touch'], '3')
            (d / 'kernel.log').write_bytes(b'\0' * 0x400000)
            self.assertIsNone(hc.dump_text(d / 'kernel.log')[0])
        finally:
            shutil.rmtree(d)

    @unittest.skipUnless((ROOT / 'research/laguna-usb-fix/attempts/20261103-205514-a7-ios-system-int1/ramdump/kernel.log').is_file(),
                         'int1 physical dump not on this host')
    def test_int1_rows_on_the_real_int1_dump(self):
        t, _ = hc.dump_text(ROOT / 'research/laguna-usb-fix/attempts/20261103-205514-a7-ios-system-int1/ramdump/kernel.log')
        src = dict(dump=t)
        home = hc.home_rule({}, src)
        self.assertTrue(home['home'])
        rows = {r['id']: r['verdict'] for r in hc.evaluate(hc.load_expect(ROOT / 'research/ios26-phaseb-r1/live/expect/int1.yaml'),
                                                            src, {'HOME'}, dict(ran=False, attended=True))}
        for k in ('boot.root', 'boot.home', 'T', 'Bt', 'H', 'Ph', 'ustack', 'end.deadline'):
            self.assertEqual(rows[k], 'PASS', k)
        self.assertEqual(rows['S'], 'FAIL')        # CRASH Preferences in that boot (PHYSICAL 20261103-205514)


if __name__ == '__main__':
    unittest.main()
