#!/usr/bin/env python3
"""Host tests for tools/hk.py with fakes only: no phone, no Mac, no network beyond 127.0.0.1.

    python3 -I tools/test_hk.py [-v]

Fakes: a phone-bridge dir (fastboot/adb/mac scripts), fake wrapped tools via HK_TOOL_<KEY>, a temp repo (HK_REPO) with
research/images and runner attempt dirs, a temp store (HK_STORE) and lock dir (HK_LOCKDIR), and an in-process TCP server
that speaks hk_shell's protocol (banner, `ios:/ # ` prompt, `[exit N]`), with or without the proposed put/kill builtins.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
HK = HERE / 'hk.py'
sys.path.insert(0, str(HERE))
import hk  # noqa: E402

PY = sys.executable


def write(p, text, mode=0o644):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    p.chmod(mode)
    return p


class ShellServer:
    """hk_shell's wire protocol (research/ios26-phaseb-r1/live/src/hk_shell.c conn_thread), plus HUB.md's put/kill."""

    def __init__(self, caps=('cd', 'pwd', 'setenv', 'help', 'exit'), procs=None):
        self.caps = list(caps)
        self.procs = procs if procs is not None else {120: 'wifid', 1: 'launchd'}
        self.files = {}
        self.next_pid = 500
        self.sock = socket.socket()
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.conn, args=(c,), daemon=True).start()

    def conn(self, c):
        f = c.makefile('rb')
        c.sendall(b'hk_shell: root command runner on native iOS (no /bin/sh on this root).\n')
        while True:
            c.sendall(b'ios:/ # ')
            line = f.readline()
            if not line:
                break
            argv = line.decode().strip().split()
            if not argv:
                continue
            cmd = argv[0]
            if cmd in ('exit', 'quit'):
                break
            if cmd == 'help':
                c.sendall(('builtins: ' + ' '.join(self.caps) + '; anything else is PATH-resolved and spawned.\n').encode())
            elif cmd == 'pwd':
                c.sendall(b'/\n')
            elif cmd == 'put' and 'put' in self.caps:
                remote, size, mode, sha = argv[1], int(argv[2]), argv[3], argv[4]
                data = f.read(size)
                got = hashlib.sha256(data).hexdigest()
                self.files[remote] = data
                c.sendall(f'[put ok {len(data)} {got}]\n'.encode() if got == sha else b'[put bad sha]\n')
            elif cmd == 'kill' and 'kill' in self.caps:
                pid = int(argv[-1])
                name = self.procs.pop(pid, None)
                if name:
                    self.procs[self.next_pid] = name      # launchd respawns it
                    self.next_pid += 1
                c.sendall(b'')
            elif cmd == 'ps':
                out = '  PID COMM\n' + ''.join(f'{p:5d} /usr/libexec/{n}\n' for p, n in sorted(self.procs.items()))
                c.sendall(out.encode() + b'[exit 0]\n')
            elif cmd == 'false':
                c.sendall(b'[exit 1]\n')
            else:
                c.sendall(f"ran {' '.join(argv)}\n[exit 0]\n".encode())
        c.close()

    def close(self):
        self.sock.close()


class HkTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='hk-test-'))
        self.repo = self.tmp / 'repo'
        self.store = self.tmp / 'store'
        self.locks = self.tmp / 'locks'
        self.pb = self.tmp / 'pb'
        self.fakes = self.tmp / 'fakes'
        self.state = self.tmp / 'phone-state'
        self.state.write_text('fastboot')
        self.env = dict(os.environ, HK_REPO=str(self.repo), HK_STORE=str(self.store), HK_LOCKDIR=str(self.locks),
                        HK_PB=str(self.pb), HK_HOLDER='tester', HK_LOCK='tester', HK_MAIN=str(self.tmp / 'no-main'), FAKE_STATE=str(self.state), FAKE_LOG=str(self.tmp / 'calls.log'))
        for k in list(self.env):
            if k.startswith(('HK_TOOL_', 'HK_ARGV_')) or k == 'HK_LOCK_TOKEN':
                del self.env[k]
        self.make_pb()
        self.make_image('a7-ios-system-wifi1', 'debug=0x8 cpus=5 blazer_deadline=900 blazer_wifi=1 hk_ustack=Preferences')
        # tool paths that must not fall back to the real checkout
        for key in hk.TOOLS:
            self.env['HK_TOOL_' + key.upper()] = str(self.fakes / f'missing-{key}')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- fixtures

    def make_pb(self):
        log = '"$FAKE_LOG"'
        write(self.pb / 'fastboot', f'''#!/bin/sh
echo "fastboot $*" >> {log}
case "$1" in
  devices) [ "$(cat "$FAKE_STATE")" = fastboot ] && printf 'SERIAL\\tfastboot\\n'; exit 0;;
  reboot) echo android > "$FAKE_STATE"; echo OKAY; exit 0;;
  oem) echo OKAY; exit 0;;
esac
exit 0
''', 0o755)
        write(self.pb / 'adb', f'''#!/bin/sh
echo "adb $*" >> {log}
echo "List of devices attached"
[ "$(cat "$FAKE_STATE")" = android ] && printf 'SERIAL\\tdevice\\n'
exit 0
''', 0o755)
        write(self.pb / 'mac', f'''#!/bin/sh
echo "mac $*" >> {log}
if [ "$1" = usb ]; then
  [ "$(cat "$FAKE_STATE")" = ios ] && echo "  1209:0003  hackios XNU console  (pid.codes)"
  exit 0
fi
exit 1
''', 0o755)

    def make_image(self, name, cmdline):
        d = self.repo / 'research/images' / name
        man = dict(name=name, image='ab' * 32, mach='cd' * 32, bootable=True, cmdline=cmdline, cpus=5,
                   var_overlay=dict(path='research/x.ovl', sha256='ef' * 32))
        write(d / 'manifest.json', json.dumps(man))
        (d / 'boot.img').write_bytes(b'ANDROID!' + b'\0' * 64)
        return d

    def make_runner(self, name, deadline=900, extra_log=b''):
        rd = self.repo / 'research/laguna-usb-fix/attempts' / f'20261103-120000-{name}'
        write(rd / 'meta.txt', f'attempt: {name}\nstarted: 2026-11-03 12:00:00 +0100\n'
                               f'image: /Users/x/Developer/personal/hackios/research/images/a7-ios-system-wifi1/boot.img\n'
                               f'image_sha256: {"ab" * 32}\n')
        write(rd / 'reader.txt', 'VERDICT: PANICKED | stage=none\n')
        (rd / 'ramdump').mkdir(parents=True, exist_ok=True)
        log = (b'\0' * 32 + b'HKL wifid[120] -- mirror on\nHKL wifid[120] joining net\nHKL lsd[57] other\n' + extra_log +
               f'panic(cpu 0 caller 0xfffffe00079fe060): blazer-root: deadline {deadline} s, stage pid1_exec\n'.encode())
        (rd / 'ramdump/kernel.log').write_bytes(log)
        return rd

    def fake_tool(self, key, body, suffix='.py'):
        p = write(self.fakes / f'{key}{suffix}', body, 0o755)
        self.env['HK_TOOL_' + key.upper()] = str(p)
        return p

    def hk(self, *args, env=None, code=None):
        e = dict(self.env)
        if env:
            e.update(env)
        r = subprocess.run([PY, '-I', str(HK), *args], capture_output=True, text=True, env=e, timeout=120)
        if code is not None:
            self.assertEqual(r.returncode, code, f'hk {args}: rc {r.returncode}\nstdout {r.stdout}\nstderr {r.stderr}')
        return r

    def hkj(self, *args, code=0, env=None):
        r = self.hk(*args, '--json', env=env, code=code)
        doc = json.loads(r.stdout)
        self.assertIn('schema', doc)
        self.assertTrue(doc['schema'].startswith('hk.'))
        self.assertEqual(doc['ok'], code == 0, doc)
        return doc

    # --- lease

    def test_lock_acquire_busy_release(self):
        a = self.hkj('lock', 'acquire', '--purpose', 'attended', '--ttl', '600', '--holder', 'agent-A')
        tok = a['token']
        st = self.hkj('lock', 'status')
        self.assertEqual(st['state'], 'held')
        self.assertEqual(st['lease']['holder'], 'agent-A')
        self.assertNotIn('token', st['lease'])
        busy = self.hkj('lock', 'acquire', '--holder', 'agent-B', code=4)
        self.assertEqual(busy['error'], 'phone_busy')
        self.assertEqual(busy['lease']['holder'], 'agent-A')
        # a phone command from another agent is refused, with the holder named
        aid = self.hkj('ingest', str(self.make_runner('a7-x')))['items'][0]['attempt']
        b = self.hkj('back', '--attempt', aid, code=4, env=dict(HK_HOLDER='agent-B'))
        self.assertIn('agent-A', b['message'])
        # the holder's token is inherited by its own nested commands
        again = self.hkj('lock', 'acquire', env=dict(HK_LOCK_TOKEN=tok))
        self.assertTrue(again['inherited'])
        self.hkj('lock', 'release', '--token', 'nope', code=4)
        self.hkj('lock', 'release', '--token', tok)
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')
        events = [json.loads(l)['event'] for l in (self.locks / 'hk-phone.events.jsonl').read_text().splitlines()]
        self.assertEqual(events[:2], ['acquire', 'release'])

    def test_lock_expiry_and_stale(self):
        t0 = time.time()
        self.hkj('lock', 'acquire', '--ttl', '60', '--holder', 'old', env=dict(HK_NOW=str(t0)))
        self.assertEqual(self.hkj('lock', 'status', env=dict(HK_NOW=str(t0 + 61)))['state'], 'expired')
        a = self.hkj('lock', 'acquire', '--holder', 'new', env=dict(HK_NOW=str(t0 + 61)))
        self.assertEqual(a['lease']['holder'], 'new')
        # pid-bound lease of a dead process on this host is stale and can be taken
        lease = json.loads((self.locks / hk.LEASE).read_text())
        p = subprocess.Popen(['true'])
        p.wait()
        lease.update(pid=p.pid, pid_bound=True, expires=time.time() + 999)
        (self.locks / hk.LEASE).write_text(json.dumps(lease))
        self.assertEqual(self.hkj('lock', 'status')['state'], 'stale')
        self.assertEqual(self.hkj('lock', 'acquire', '--holder', 'third')['lease']['holder'], 'third')

    def test_lock_break_rules(self):
        self.hkj('lock', 'acquire', '--holder', 'A')
        self.hkj('lock', 'break', '--reason', 'x', code=4)
        self.hkj('lock', 'break', '--force', code=2)
        self.assertEqual(self.hkj('lock', 'break', '--force', '--reason', 'owner said so')['broken'], 'held')
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')

    # --- tools that are not there yet

    def test_missing_tools_are_clean_json_errors(self):
        rd = self.make_runner('a7-x')
        self.hkj('ingest', str(rd))
        for args, tool in ((('probe', 'Wi-Fi'), 'probe'), (('crash',), 'crashdoc'), (('qemu', 'a7-ios-system-wifi1'), 'qemu'),
                           (('cycle', 'a7-ios-system-wifi1'), 'cycle'), (('boot', 'a7-ios-system-wifi1'), 'live_boot')):
            d = self.hkj(*args, code=3)
            self.assertEqual(d['error'], 'tool not present', d)
            self.assertEqual(d['reason'], 'tool_missing', d)
            self.assertEqual(d['tool'], tool)
            self.assertIn('owner', d)
        # no lease and no attempt are left behind by a refused boot
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')
        self.assertEqual(self.hkj('find')['count'], 1)
        t = self.hkj('tools')
        self.assertTrue(all(not x['present'] for x in t['tools']))

    # --- index, ingest, find

    def test_ingest_find_and_live_merge(self):
        rd = self.make_runner('a7-wifi-join-r9')
        live = self.repo / 'research/laguna-usb-fix/attempts/live-20261103-115955-a7-wifi-join-r9'
        write(live / 'live.env', f'LIVE_RUN={live}\nLIVE_NAME=a7-wifi-join-r9\nLIVE_SOCK=/tmp/x.sock\n'
                                 f'ATTEMPT=/Users/x/Developer/personal/hackios/research/laguna-usb-fix/attempts/{rd.name}\nBOOT_RC=0\n')
        write(live / 'markers.txt', 'LIVEBOOT 12:00:01.000 +1.0 CONSOLE_CONNECTED x\nLIVEBOOT 12:02:00.000 +120.0 UI_READY\n'
                                    'LIVEBOOT 12:10:00.000 +600.0 BOOT_RC 0\n')
        write(live / 'console.txt', '12:00:01.000 hello\n')
        d = self.hkj('ingest', str(rd), str(live))
        self.assertEqual(d['imported'], 1)
        self.assertEqual(d['items'][0]['attempt'], d['items'][1]['attempt'])
        again = self.hkj('ingest', str(rd))
        self.assertEqual(again['imported'], 0)
        f = self.hkj('find', '--feature', 'wifi', '--since', '2026-11-03', env=dict(HK_NOW=str(time.time())))
        self.assertEqual(f['count'], 1)
        r = f['attempts'][0]
        self.assertEqual(r['schema'], 'hk.index/1')
        self.assertEqual(r['end']['kind'], 'deadline')
        self.assertEqual(r['end']['seconds'], 900)
        self.assertEqual(r['reader'], 'PANICKED')
        self.assertIn('ustack', r['features'])
        self.assertIn('live', r['paths'])
        self.assertEqual(self.hkj('find', '--feature', 'gpu')['count'], 0)
        m = json.loads((self.store / r['id'] / 'manifest.json').read_text())
        self.assertEqual(m['schema'], 'hk.manifest/1')
        self.assertIn('UI_READY', m['result']['markers'])
        self.assertTrue((self.store / r['id'] / 'runner').is_symlink())
        self.assertTrue((self.store / '.gitignore').read_text().strip().endswith('*'))
        # find --since today relative to HK_NOW
        late = time.mktime(time.strptime('2026-11-05 10:00', '%Y-%m-%d %H:%M'))
        self.assertEqual(self.hkj('find', '--since', 'today', env=dict(HK_NOW=str(late)))['count'], 0)

    def test_features(self):
        self.assertIn('wifi', hk.features_of('a7-wifi-join-r2'))
        self.assertIn('chooser', hk.features_of('chooser-ios-int1'))
        self.assertIn('net', hk.features_of('x', 'blazer_usbnet=1 blazer_usbnet_direct=1'))
        self.assertIn('screen', hk.features_of('x', 'hk_screen=30'))
        self.assertNotIn('cpu', hk.features_of('a7-ios-system-r3', 'cpus=5'))

    # --- boot / cycle / back

    def test_boot_under_lease_and_attempt_layout(self):
        rd = self.make_runner('a7-ios-system-wifi1')
        self.fake_tool('live_boot', f'''#!/bin/sh
# fake live_boot.sh: needs the lease token, makes a live run under LIVE_ATTEMPTS
[ -n "$HK_LOCK_TOKEN" ] || {{ echo "no lease token"; exit 9; }}
grep -q "$HK_LOCK_TOKEN" "{self.locks}/hk-phone.lease.json" || {{ echo "token does not match the lease"; exit 9; }}
run="$LIVE_ATTEMPTS/live-20261103-120000-$2"
mkdir -p "$run"
printf 'LIVE_RUN=%s\\nLIVE_SOCK=/tmp/s\\nBOOT_RC=0\\n' "$run" > "$run/live.env"
printf 'LIVEBOOT 12:00:00.000 +1.0 UI_READY\\nLIVEBOOT 12:00:09.000 +9.0 BOOT_RC 0\\n' > "$run/markers.txt"
echo "12:00:00.000 console" > "$run/console.txt"
echo "args: $*"
echo "live_boot: run $run"
echo "live_boot: attempt /Users/x/Developer/personal/hackios/research/laguna-usb-fix/attempts/{rd.name}"
''', '.sh')
        d = self.hkj('boot', 'a7-ios-system-wifi1', '--mach', '/k.unstripped', '--wait', '60')
        a = self.store / d['attempt']
        m = json.loads((a / 'manifest.json').read_text())
        self.assertEqual(m['image']['name'], 'a7-ios-system-wifi1')
        self.assertEqual(m['image']['deadline'], 900)
        self.assertEqual(m['result']['rc'], 0)
        self.assertEqual(m['result']['end']['kind'], 'deadline')
        self.assertEqual(m['lease_holder'], 'tester')
        self.assertIn('--mach', m['command'])
        for sub in ('screens', 'probes', 'crashes', 'logs', 'runner', 'ramdump', 'live', 'console.txt'):
            self.assertTrue((a / sub).exists(), sub)
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')
        # logs by HKL program, from the ramdump (raw fallback: no hklog)
        lg = self.hkj('logs', 'wifid', '--attempt', d['attempt'])
        self.assertEqual(lg['file'], 'raw')
        self.assertEqual(len(lg['lines']), 2)
        self.assertTrue(all('HKL wifid[120]' in l for l in lg['lines']))

    def test_boot_refused_while_someone_holds_the_phone(self):
        self.fake_tool('live_boot', '#!/bin/sh\necho ran >> "$FAKE_LOG"\n', '.sh')
        self.hkj('lock', 'acquire', '--holder', 'owner-attended')
        d = self.hkj('boot', 'a7-ios-system-wifi1', code=4)
        self.assertEqual(d['lease']['holder'], 'owner-attended')
        self.assertFalse((self.tmp / 'calls.log').exists() and 'ran' in (self.tmp / 'calls.log').read_text())
        self.assertFalse(self.store.exists() and list(self.store.glob('2026*')))

    def test_cycle_reads_report(self):
        self.fake_tool('cycle', '''import sys, json, os, pathlib
a = sys.argv[1:]
out = pathlib.Path(a[a.index('--out') + 1]); out.mkdir(parents=True)
assert os.environ.get('HK_LOCK_TOKEN')
(out / 'report.json').write_text(json.dumps(dict(verdict='PASS', return_check_verdict='PASS', ui=dict(verdict='PASS'))))
print('hk_cycle: verdict PASS')
''')
        d = self.hkj('cycle', 'a7-ios-system-wifi1', '--ui', 'ui/x.ui', '--', '--no-shots')
        m = json.loads((self.store / d['attempt'] / 'manifest.json').read_text())
        self.assertEqual(m['result']['verdict'], 'PASS')
        self.assertEqual(m['result']['return_check'], 'PASS')
        self.assertEqual(m['result']['ui'], 'PASS')
        self.assertEqual(m['command'][-1], '--no-shots')

    def test_back_from_fastboot(self):
        rd = self.make_runner('a7-x')
        aid = self.hkj('ingest', str(rd))['items'][0]['attempt']
        self.fake_tool('return_check', '''#!/bin/sh
mkdir -p "$1"; echo '{"verdict": "PASS"}' > "$1/return-check.json"; echo PASS
''', '.sh')
        d = self.hkj('back', '--attempt', aid)
        self.assertEqual(d['verdict'], 'PASS')
        calls = (self.tmp / 'calls.log').read_text()
        self.assertIn('fastboot oem force-fastboot off', calls)
        self.assertIn('fastboot reboot', calls)
        self.assertNotIn('flash', calls)
        m = json.loads((self.store / aid / 'manifest.json').read_text())
        self.assertEqual(m['result']['return_check'], 'PASS')
        # in iOS, hk back refuses (never cold-reset a running boot)
        self.state.write_text('ios')
        self.assertEqual(self.hkj('back', '--attempt', aid, code=6)['error'], 'wrong_state')

    def test_state(self):
        for st, want in (('fastboot', 'fastboot'), ('android', 'android'), ('ios', 'ios'), ('off', 'off-or-unknown')):
            self.state.write_text(st)
            d = self.hkj('state', env=dict(HK_SHELL='tcp:127.0.0.1:1'))
            self.assertEqual(d['phone'], want)
        self.assertFalse(d['ios_shell'] if d['ios_shell'] is not None else False)
        self.hkj('installed', 'chooser-ios-int1', '--readback', 'aca7c0fc', '--source', 'LEDGER')
        d = self.hkj('state', '--no-phone')
        self.assertEqual(d['installed_boot_b']['readback'], 'aca7c0fc')
        self.assertEqual(d['phone'], 'skipped')

    # --- the iOS shell

    def test_shell_push_restart_without_builtins(self):
        srv = ShellServer()
        env = dict(HK_SHELL=f'tcp:127.0.0.1:{srv.port}')
        try:
            d = self.hkj('shell', 'ifconfig', 'en2', env=env)
            self.assertEqual(d['exit'], 0)
            self.assertIn('ran ifconfig en2', d['stdout'])
            self.hkj('shell', 'false', env=env, code=1)
            self.assertEqual(self.hkj('shell', 'pwd', env=env)['exit'], None)   # builtin: no [exit]
            f = write(self.tmp / 'x.dylib', 'bytes')
            self.assertEqual(self.hkj('push', str(f), '/private/var/hk/x.dylib', env=env, code=5)['error'], 'unsupported')
            self.assertEqual(self.hkj('restart', 'wifid', env=env, code=5)['error'], 'unsupported')
            self.hkj('push', str(f), '/System/x', env=env, code=2)
            self.assertEqual(self.hkj('lock', 'status')['state'], 'free')
        finally:
            srv.close()

    def test_shell_push_restart_with_builtins(self):
        srv = ShellServer(caps=('cd', 'pwd', 'setenv', 'help', 'exit', 'put', 'kill'))
        env = dict(HK_SHELL=f'tcp:127.0.0.1:{srv.port}')
        try:
            f = self.tmp / 'hk_fix.dylib'
            f.write_bytes(os.urandom(70000))
            d = self.hkj('push', str(f), '/private/var/hk/hk_fix.dylib', '--mode', '0755', env=env)
            self.assertTrue(d['verified'])
            self.assertEqual(srv.files['/private/var/hk/hk_fix.dylib'], f.read_bytes())
            r = self.hkj('restart', 'wifid', env=env)
            self.assertEqual(r['old_pids'], [120])
            self.assertTrue(r['respawned'])
            self.assertEqual(self.hkj('restart', 'nosuchd', env=env, code=6)['error'], 'not_running')
        finally:
            srv.close()

    def test_shell_down(self):
        self.assertEqual(self.hkj('shell', 'ps', env=dict(HK_SHELL='tcp:127.0.0.1:1'), code=6)['error'], 'shell_down')

    def test_transcript_parse(self):
        b, out, code = hk.parse_transcript('banner\nios:/ # line1\nline2\n[exit 3]\nios:/ # ')
        self.assertEqual((out, code), ('line1\nline2\n', 3))

    # --- queue

    def test_queue_admission_and_runner(self):
        self.fake_tool('cycle', '''import sys, json, pathlib
a = sys.argv[1:]
out = pathlib.Path(a[a.index('--out') + 1]); out.mkdir(parents=True)
(out / 'report.json').write_text(json.dumps(dict(verdict='FAIL', return_check_verdict='PASS')))
sys.exit(1)
''')
        q = self.hkj('queue', 'add', 'a7-ios-system-wifi1', 'ui/wifi.ui', 'expect/wifi.yaml', '--holder', 'agent-W')
        qid = q['item']['id']
        self.assertIsNone(q['item']['admitted'])
        ran = self.hkj('queue', 'run', '--once')
        self.assertEqual(ran['ran'], [])                      # not admitted: nothing runs
        self.hkj('queue', 'admit', qid, '--holder', 'owner')
        ran = self.hkj('queue', 'run', '--once')
        self.assertEqual(len(ran['ran']), 1)
        self.assertEqual(ran['ran'][0]['verdict'], 'FAIL')
        item = self.hkj('queue', 'show', qid)['item']
        self.assertEqual(item['state'], 'done')
        self.assertTrue(item['attempt'])
        m = json.loads((self.store / item['attempt'] / 'manifest.json').read_text())
        self.assertEqual(m['queue_id'], qid)
        self.assertIn('--ui', m['command'])
        self.assertEqual(self.hkj('queue', 'list')['counts']['done'], 1)
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')

    def test_queue_waits_when_phone_busy(self):
        self.fake_tool('cycle', 'import sys; sys.exit(0)\n')
        qid = self.hkj('queue', 'add', 'a7-ios-system-wifi1', '--admit')['item']['id']
        self.hkj('lock', 'acquire', '--holder', 'attended-owner')
        self.assertEqual(self.hkj('queue', 'run', '--once')['ran'], [])
        self.assertEqual(self.hkj('queue', 'show', qid)['item']['state'], 'pending')

    # --- wrapped analysis tools

    def test_crash_probe_qemu_wrappers(self):
        rd = self.make_runner('a7-x')
        aid = self.hkj('ingest', str(rd))['items'][0]['attempt']
        self.fake_tool('crashdoc', '''import sys, json, pathlib
a = sys.argv[1:]; out = pathlib.Path(a[a.index('--out') + 1])
(out / 'crashes.json').write_text(json.dumps(dict(signatures=[dict(sig='usertrap:backboardd@0x1e2746924', proc='backboardd',
    kind='usertrap', culprit=dict(text='CoreBrightness func+0x1'), incidents=7, status='open',
    hints=[dict(id='corebrightness-calibration')])])))
''')
        d = self.hkj('crash', '--attempt', aid)
        s = d['signatures'][0]
        self.assertEqual((s['proc'], s['count'], s['hint']), ('backboardd', 7, 'corebrightness-calibration'))
        rep = self.hkj('report', aid)
        self.assertEqual(rep['manifest']['result']['crash_signatures'][0]['sig'], 'usertrap:backboardd@0x1e2746924')
        self.assertTrue(Path(rep['report_md']).is_file())
        self.fake_tool('probe', 'import json, sys\nprint(json.dumps(dict(row=sys.argv[3], verdict="FAIL", why="no link-up")))\n')
        p = self.hkj('probe', 'Wi-Fi', '--attempt', aid)
        self.assertEqual(p['verdict'], 'FAIL')
        self.assertTrue((self.store / aid / 'probes' / 'Wi-Fi.json').is_file())
        self.fake_tool('qemu', '''import sys, json
a = sys.argv[1:]; open(a[a.index('--json') + 1], 'w').write(json.dumps(dict(verdict='PASS', run_dir='/tmp/q1')))
''')
        q = self.hkj('qemu', 'a7-ios-system-wifi1', '--', '--seconds', '60')
        self.assertEqual(q['verdict'], 'PASS')
        self.assertEqual(self.hkj('find', '--kind', 'qemu')['count'], 1)

    def test_argv_template_override(self):
        rd = self.make_runner('a7-x')
        aid = self.hkj('ingest', str(rd))['items'][0]['attempt']
        self.fake_tool('probe', 'import json, sys\nprint(json.dumps(dict(argv=sys.argv[1:], verdict="PASS")))\n')
        d = self.hkj('probe', 'Touch', '--attempt', aid,
                     env=dict(HK_ARGV_PROBE=json.dumps(['{tool}', '--json', '--row', '{row}', '{input}'])))
        self.assertEqual(d['result']['argv'][:3], ['--json', '--row', 'Touch'])

    def test_images_and_schema(self):
        d = self.hkj('images', '--feature', 'wifi')
        self.assertEqual([i['name'] for i in d['images']], ['a7-ios-system-wifi1'])
        s = self.hkj('schema')
        for k in ('state', 'lock', 'manifest', 'index', 'error', 'queue'):
            self.assertIn(k, s)


    # --- the phone lock: device commands refuse without it

    def make_live(self, name='a7-x'):
        run = self.tmp / 'live' / f'live-20261103-120500-{name}'
        write(run / 'live.env', f'LIVE_RUN={run}\nLIVE_SOCK=/tmp/s\n')
        write(run / 'console.txt', '12:05:00.000 console\n')
        return run

    def test_device_commands_refuse_without_lock(self):
        nolock = dict(HK_LOCK='')
        for key in ('live_boot', 'cycle', 'ui_run', 'return_check'):
            self.fake_tool(key, '#!/bin/sh\necho "ran $0" >> "$FAKE_LOG"\n', '.sh')
        aid = self.hkj('ingest', str(self.make_runner('a7-x')))['items'][0]['attempt']
        live = self.make_live()
        f = write(self.tmp / 'x.dylib', 'x')
        for args in (('boot', 'a7-ios-system-wifi1'), ('live', 'a7-ios-system-wifi1'), ('cycle', 'a7-ios-system-wifi1'),
                     ('ui', 'ui/x.ui', '--run', str(live)), ('back', '--attempt', aid),
                     ('push', str(f), '/private/var/hk/x.dylib'), ('restart', 'wifid')):
            d = self.hkj(*args, code=4, env=nolock)
            self.assertEqual(d['error'], 'lock_required', (args, d))
        log = self.tmp / 'calls.log'
        self.assertFalse(log.exists() and 'ran' in log.read_text(), 'a wrapped device tool ran without the lock')
        self.assertEqual(self.hkj('find')['count'], 1)       # no attempt was made by a refused boot/cycle
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')
        # read-only work needs no lock; ui --check (parse only) neither
        self.hkj('ui', 'ui/x.ui', '--check', env=nolock)
        self.hkj('logs', 'wifid', '--attempt', aid, env=nolock)

    def test_lock_by_name_inherited_by_device_commands(self):
        nolock = dict(HK_LOCK='', HK_HOLDER='')
        a = self.hkj('lock', 'acquire', 'coord', '--ttl', '600', '--purpose', 'r9 boot', env=nolock)
        self.assertEqual(a['lease']['holder'], 'coord')
        self.assertFalse(a['inherited'])
        self.assertTrue(self.hkj('lock', 'acquire', 'coord', env=nolock)['inherited'])   # same name: already held
        self.assertTrue(self.hkj('lock', 'check', 'coord', env=nolock)['holds'])
        self.assertEqual(self.hkj('lock', 'check', 'agent-B', code=4, env=nolock)['error'], 'not_holder')
        self.assertEqual(self.hkj('lock', 'check', code=4, env=dict(HK_LOCK='', HK_HOLDER='x'))['error'], 'not_holder')
        self.fake_tool('cycle', CYCLE_CHECKS_TOKEN)
        # another agent is refused, naming the holder; the holder (by --lock or HK_LOCK) runs
        b = self.hkj('cycle', 'a7-ios-system-wifi1', '--lock', 'agent-B', code=4, env=nolock)
        self.assertEqual((b['error'], b['lease']['holder']), ('phone_busy', 'coord'))
        r = self.hkj('cycle', 'a7-ios-system-wifi1', code=4, env=nolock)
        self.assertEqual(r['error'], 'lock_required')
        self.assertIn('coord', r['message'])
        self.assertEqual(self.hkj('cycle', 'a7-ios-system-wifi1', '--lock', 'coord', env=nolock)['result']['verdict'], 'PASS')
        self.hkj('cycle', 'a7-ios-system-wifi1', env=dict(nolock, HK_LOCK='coord'))
        # an inherited lease is not released by the command
        st = self.hkj('lock', 'status')
        self.assertEqual((st['state'], st['lease']['holder']), ('held', 'coord'))
        self.hkj('lock', 'release', 'agent-B', code=4, env=nolock)
        self.hkj('lock', 'release', code=2, env=nolock)
        self.hkj('lock', 'release', 'coord', env=nolock)
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')
        # free phone + --lock NAME: taken for the command and released after
        self.hkj('cycle', 'a7-ios-system-wifi1', '--lock', 'solo', env=nolock)
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')
        ev = [json.loads(l) for l in (self.locks / 'hk-phone.events.jsonl').read_text().splitlines()]
        self.assertEqual([e['holder'] for e in ev if e['event'] == 'acquire'], ['coord', 'solo'])

    def test_expired_lock_broken_with_note(self):
        t0 = time.time()
        self.hkj('lock', 'acquire', 'gone-agent', '--ttl', '60', env=dict(HK_NOW=str(t0)))
        r = self.hk('lock', 'acquire', 'next-agent', '--json', env=dict(HK_NOW=str(t0 + 100)), code=0)
        d = json.loads(r.stdout)
        self.assertEqual(d['reclaimed_from']['holder'], 'gone-agent')
        self.assertEqual(d['reclaimed_from']['state'], 'expired')
        self.assertIn('expired 40 s ago', d['reclaimed_from']['note'])
        self.assertIn('broke the expired phone lease of gone-agent', r.stderr)
        ev = [json.loads(l) for l in (self.locks / 'hk-phone.events.jsonl').read_text().splitlines()]
        rec = [e for e in ev if e['event'] == 'reclaimed-expired']
        self.assertEqual((rec[0]['holder'], rec[0]['by']), ('gone-agent', 'next-agent'))
        self.assertIn('expired', rec[0]['note'])

    # --- probe rows, status

    def fake_probe(self):
        self.fake_tool('probe', 'import json, sys\nd = ' + repr(PROBE_DOC) + FAKE_PROBE_TAIL)

    def fake_crashdoc(self):
        self.fake_tool('crashdoc', FAKE_CRASHDOC)

    def test_probe_rows_and_path(self):
        self.fake_probe()
        rd = self.make_runner('a7-y')
        d = self.hkj('probe', '--path', str(rd))
        self.assertEqual(d['counts'], {'partial': 1, 'works': 2, 'none': 1})
        self.assertIsNone(d['verdict'])
        self.assertEqual(d['inputs'], [str(rd.resolve())])
        one = self.hkj('probe', 'Wi-Fi', '--path', str(rd))      # same dir: the same attempt (idempotent import)
        self.assertEqual((one['verdict'], one['attempt']), ('partial', d['attempt']))
        self.assertEqual(one['rows'][0]['evidence'], ['k.log:9'])
        two = self.hkj('probe', 'wifi', 'touch', '--attempt', d['attempt'], '--qemu')
        self.assertEqual([r['id'] for r in two['rows']], ['wifi', 'touch'])
        self.assertTrue((self.store / d['attempt'] / 'probes' / 'all.json').is_file())
        self.assertEqual(self.hkj('find')['count'], 1)
        self.assertEqual(self.hkj('probe', '--path', str(self.tmp / 'nope'), code=3)['error'], 'no_path')
        txt = self.hk('probe', '--path', str(rd), code=0).stdout
        self.assertIn('4 rows: none 1, partial 1, works 2', txt)

    def test_status_newest_run(self):
        self.fake_probe()
        self.fake_crashdoc()
        old = self.make_runner('a7-old')
        new = self.repo / 'research/laguna-usb-fix/attempts/20261103-130000-a7-new'
        shutil.copytree(old, new)
        os.utime(old, (time.time() - 100, time.time() - 100))
        d = self.hkj('status')
        self.assertEqual(d['attempt'], '20261103-130000-a7-new')
        self.assertEqual(d['milestones']['probes'], {'home': 'works'})
        self.assertEqual(d['probes'], {'wifi': 'partial', 'touch': 'works', 'gps': None})
        self.assertEqual(d['reader'], 'PANICKED')
        self.assertEqual(d['end']['kind'], 'deadline')
        self.assertEqual(d['crashes'][0]['hint'], 'corebrightness-calibration')
        self.assertIn('--no-symbols', json.loads(Path(d['crashes_json']).read_text())['argv'])
        txt = self.hk('status', '--path', str(old), code=0).stdout
        self.assertIn('milestones: home', txt)
        self.assertIn('backboardd', txt)

    def test_status_degrades_when_tools_missing(self):
        rd = self.make_runner('a7-z')
        d = self.hkj('status', '--path', str(rd), code=3)
        self.assertEqual(sorted(e['tool'] for e in d['errors']), ['crashdoc', 'probe'])
        self.assertTrue(all(e['error'] == 'tool not present' for e in d['errors']))
        self.assertEqual(d['end']['kind'], 'deadline')                   # the rest still summarised
        self.assertEqual(self.hkj('status', '--path', str(rd), '--no-probe', '--no-crash')['errors'], [])

    def test_logs_obs_prefix_via_path(self):
        rd = self.make_runner('a7-l', extra_log=b'HKL wifid[121] scan done\nlaunchd: wifid[120] exited\n')
        d = self.hkj('logs', 'wifid', '--path', str(rd))
        self.assertEqual(d['total'], 4)
        self.assertTrue(all('wifid[' in l for l in d['lines']))
        self.assertEqual(self.hkj('logs', 'lsd', '--path', str(rd), '--grep', 'other')['total'], 1)

    def test_help_lists_every_subcommand(self):
        out = self.hk('--help', code=0).stdout
        for c in ('cycle', 'probe', 'crash', 'qemu', 'ui', 'logs', 'live', 'status', 'lock'):
            self.assertRegex(out, rf'\b{c}\b')
            self.hk(c, '--help', code=0)


CYCLE_CHECKS_TOKEN = """import sys, json, os, pathlib
a = sys.argv[1:]
out = pathlib.Path(a[a.index('--out') + 1]); out.mkdir(parents=True)
lease = json.loads(pathlib.Path(os.environ['HK_LOCKDIR'], 'hk-phone.lease.json').read_text())
assert os.environ.get('HK_LOCK_TOKEN') == lease['token'], 'child does not carry the holder token'
(out / 'summary.json').write_text(json.dumps(dict(verdict='PASS', return_check_verdict='PASS')))
"""
PROBE_DOC = dict(attempts=[dict(name='x')], rows=[
    dict(id='wifi', row='Wi-Fi', verdict='partial', milestone=False, phone_only=True, evidence=[dict(cite='k.log:9')],
         next=dict(test='join')),
    dict(id='touch', row='Touch', verdict='works', milestone=False, phone_only=True, evidence=[]),
    dict(id='gps', row='GPS', verdict=None, milestone=False, phone_only=True, evidence=[]),
    dict(id='home', row='Home screen', verdict='works', milestone=True, phone_only=True, evidence=[])])
FAKE_PROBE_TAIL = """
a = sys.argv[1:]
rows = [a[i + 1] for i, x in enumerate(a) if x == '--row']
d['rows'] = [r for r in d['rows'] if not rows or r['id'] in rows or r['row'] in rows]
d['argv'] = a
print(json.dumps(d))
"""
FAKE_CRASHDOC = """import sys, json, pathlib
a = sys.argv[1:]; out = pathlib.Path(a[a.index('--out') + 1])
(out / 'crashes.json').write_text(json.dumps(dict(schema='crashdoc/1', argv=a, signatures=[dict(sig='usertrap:backboardd@0x1',
    proc='backboardd', kind='usertrap', culprit=dict(text='CoreBrightness+0x1'), incidents=3, status='open',
    hints=[dict(id='corebrightness-calibration')])])))
"""


class RealToolsTest(unittest.TestCase):
    """hk over the real probe_eval.py and crashdoc.py of this checkout on a synthetic runner dir; no research/ needed."""

    def setUp(self):
        for t in (HERE / 'probe_eval.py', HERE / 'crashdoc.py', HERE.parent / 'docs/probes.yaml'):
            if not t.is_file():
                self.skipTest(f'{t} not in this checkout')
        self.tmp = Path(tempfile.mkdtemp(prefix='hk-real-'))
        self.env = dict(os.environ, HK_STORE=str(self.tmp / 'store'), HK_LOCKDIR=str(self.tmp / 'locks'),
                        HK_MAIN=str(self.tmp / 'no-main'), HK_LOCK='')
        for k in list(self.env):
            if k.startswith(('HK_TOOL_', 'HK_ARGV_')) or k == 'HK_LOCK_TOKEN':
                del self.env[k]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_probe_and_crash_on_synthetic_dump(self):
        rd = self.tmp / '20261103-120000-a7-synthetic'
        write(rd / 'meta.txt', 'attempt: a7-synthetic\nstarted: 2026-11-03 12:00:00 +0100\n')
        write(rd / 'reader.txt', 'VERDICT: PANICKED | stage=none\n')
        (rd / 'ramdump').mkdir()
        (rd / 'ramdump/kernel.log').write_bytes(
            b'Darwin Kernel Version 25.0.0\nHKL wifid[120] -- mirror on\n'
            b'panic(cpu 0 caller 0xfffffe00079fe060): blazer-root: deadline 900 s, stage pid1_exec\n')
        d = None
        for args in (('probe', '--path', str(rd)), ('crash', '--path', str(rd), '--no-symbols'),
                     ('status', '--path', str(rd))):
            r = subprocess.run([PY, '-I', str(HK), *args, '--json'], capture_output=True, text=True, env=self.env, timeout=300)
            self.assertEqual(r.returncode, 0, f'{args}: {r.stdout[-800:]} {r.stderr[-800:]}')
            d = json.loads(r.stdout)
            self.assertTrue(d['ok'])
        self.assertGreater(len(d['probes']) + len(d['milestones']['probes']), 10)
        self.assertTrue(Path(d['crashes_json']).is_file())


class DocsTest(unittest.TestCase):
    """The knowledge map and the playbook agree with hk."""

    def test_map_subsystems_known(self):
        root = HERE.parent
        mp = root / 'docs/debug/MAP.md'
        if not mp.is_file():
            self.skipTest('docs/debug/MAP.md not present')
        ids = re.findall(r'^SUBSYS: (\S+)', mp.read_text(), re.M)
        self.assertGreater(len(ids), 10)
        unknown = [i for i in ids if i not in hk.SUBSYSTEMS]
        self.assertEqual(unknown, [], 'MAP.md SUBSYS ids that hk find --feature does not know')

    def test_playbook_commands_exist(self):
        root = HERE.parent
        pb = root / 'docs/debug/AGENTS-PLAYBOOK.md'
        if not pb.is_file():
            self.skipTest('playbook not present')
        cmds = set(re.findall(r'`hk ([a-z]+)', pb.read_text()))
        sub = hk.parser()._subparsers._group_actions[0].choices
        self.assertEqual(sorted(c for c in cmds if c not in sub), [])


if __name__ == '__main__':
    unittest.main()
