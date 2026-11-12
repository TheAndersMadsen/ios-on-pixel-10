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
import unittest.mock

HERE = Path(__file__).resolve().parent
HK = HERE / 'hk.py'
sys.path.insert(0, str(HERE))
import hk  # noqa: E402

PY = sys.executable


def struct_pack_rgb565(pixels):
    import struct
    return struct.pack(f'<{len(pixels)}H', *pixels)


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
                        HK_PB=str(self.pb), HK_HOLDER='tester', HK_LOCK='tester', HK_MAIN=str(self.tmp / 'no-main'), HK_AUTO_POLL_S='0.1', HK_AUTO_RETRY_S='0.2', FAKE_STATE=str(self.state), FAKE_LOG=str(self.tmp / 'calls.log'))
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
        for c in ('cycle', 'probe', 'crash', 'qemu', 'ui', 'logs', 'live', 'status', 'lock', 'timeline', 'diff', 'triage'):
            self.assertRegex(out, rf'\b{c}\b')
            self.hk(c, '--help', code=0)

    # --- 2026-11-04 lane TOOLS: live attempts, late runner dirs, screenshots, timeline/diff/triage

    def wall(self, t):
        lt = time.localtime(t)
        return time.strftime('%H:%M:%S', lt) + f'.{int(t % 1 * 1000):03d}'

    def make_live_run(self, parent, name, ts, t0, console, markers=(), image=None, runner=None):
        live = parent / f'live-{ts}-{name}'
        write(live / 'live.env', f'LIVE_RUN={live}\nLIVE_NAME={name}\nLIVE_SOCK=/tmp/x.sock\nLIVE_MAC_DIR=Developer/personal/hackios\n'
                                 f'LIVE_T0={t0}\n')
        write(live / 'console.txt', ''.join(f'{self.wall(t0 + t)} [{t:9.2f}] {text}\n' for t, text in console))
        mk = [f'LIVEBOOT {self.wall(t0 + 7)} +7.0 ATTEMPT_DIR /Users/x/Developer/personal/hackios/research/laguna-usb-fix/'
              f'attempts/{runner}'] if runner else []
        mk += [f'{who} {self.wall(t0 + t)} +{t:.1f} {text}' for who, t, text in markers]
        write(live / 'markers.txt', '\n'.join(mk) + '\n')
        if image:
            write(live / 'bootios.txt', f'{self.wall(t0)} image:  /Users/x/Developer/personal/hackios/research/images/{image}/boot.img\n')
        return live

    def test_mid_boot_attempt_reads_its_live_console(self):
        """hk boot records paths only when live_boot returns: a running (or killed) boot used to say 'nothing to read'."""
        self.fake_crashdoc()
        aid, t0 = '20261104-033817-a7-int4-confirm', time.time() - 600
        d = self.store / aid
        write(d / 'manifest.json', json.dumps(dict(schema='hk.manifest/1', id=aid, name='a7-int4-confirm', kind='phone',
                                                   created_t=t0, paths={}, result={})))
        write(self.store / 'index.jsonl', json.dumps(dict(id=aid, kind='phone', created_t=t0, paths={})) + '\n')
        self.make_live_run(d, 'a7-int4-confirm', aid[:15], t0, [(40, 'exec SpringBoard'), (60, 'CRASH recentsd reason ns 1')],
                       runner='20261103-120000-a7-late')
        st = self.hkj('status', '--attempt', aid, '--no-probe')
        self.assertTrue(st['paths']['live'].endswith(f'live-{aid[:15]}-a7-int4-confirm'))
        self.assertNotIn('runner', st['paths'])                        # the runner copy is not on m1box yet
        c = self.hkj('crash', '--attempt', aid)
        self.assertTrue(c['inputs'][0].endswith('console.txt'), c['inputs'])
        rd = self.make_runner('a7-late')                                # synced after the boot
        i = self.hkj('ingest', '--all')
        self.assertIn(aid, i['updated'])
        self.assertEqual(i['imported'], 0)                              # joined, not a second attempt
        c = self.hkj('crash', '--attempt', aid)
        self.assertEqual(c['inputs'], [str(rd)])

    def test_ingest_all_joins_late_runner_and_skips_scratch(self):
        self.make_image('a7-ios-system-int4', 'debug=0x8 blazer_deadline=900')
        root = self.repo / 'research/laguna-usb-fix/attempts'
        t0 = time.time() - 3600
        live = self.make_live_run(root, 'a7-j', '20261103-115955', t0, [(40, 'exec SpringBoard')],
                              image='a7-ios-system-int4', runner='20261103-120000-a7-j')
        write(root / '20261028-095321-audit' / 'notes.txt', 'scratch\n')
        harvest = root / '20261029-v25-harvest-c1'
        write(harvest / 'kernel.log', 'HKL wifid[120] up\npanic(cpu 0 caller 0x1): blazer-root: deadline 900 s, stage x\n')
        a = self.hkj('ingest', '--all')
        self.assertEqual(a['imported'], 2)
        self.assertEqual(a['skipped'], [str(root / '20261028-095321-audit')])
        self.assertFalse([x for x in a['items'] if x.get('error')])
        rec = {r['paths'].get('live') or r['paths'].get('harvest'): r for r in self.hkj('find')['attempts']}
        self.assertEqual(rec[str(live)]['image'], 'a7-ios-system-int4')        # from bootios.txt
        self.assertEqual(rec[str(harvest)]['end']['kind'], 'deadline')
        rd = self.make_runner('a7-j')
        b = self.hkj('ingest', '--all')
        self.assertEqual(b['imported'], 0)
        f = self.hkj('find')['attempts']
        self.assertEqual(len(f), 2)
        joined = [r for r in f if r['paths'].get('live') == str(live)][0]
        self.assertEqual(joined['paths']['runner'], str(rd))

    def test_screenshot_copies_back_an_absolute_mac_path(self):
        """The reader replies with /Users/<me>/Developer/personal/hackios/attempts/...: copy it back with mac -- cat."""
        macroot = self.tmp / 'machome'
        snap = 'Developer/personal/hackios/attempts/A/live-A/usbcon/usbcon.log.snaps/0001-shot'
        write(macroot / (snap + '.rgb565'), '')
        (macroot / (snap + '.rgb565')).write_bytes(struct_pack_rgb565([0xffff, 0x0000, 0xf800, 0x07e0]))
        write(macroot / (snap + '.json'), '{"seq": 1}')
        mac = write(self.fakes / 'fake-mac', f'''#!/bin/sh
echo "$*" >> "$FAKE_LOG"
if [ "$1" = repo ]; then
  printf '%s\\n' '{{"state":"snapshot","snapshot":{{"png":"/Users/x/{snap}.png","width":2,"height":2,"step":6,"took_us":5}}}}'
  exit 0
fi
if [ "$1" = --cd ] && [ "$3" = -- ] && [ "$4" = cat ]; then
  cat "{macroot}${{5#/Users/x}}"; exit $?
fi
exit 1
''', 0o755)
        live = self.make_live_run(self.repo / 'research/laguna-usb-fix/attempts', 'a7-s', '20261103-115955', time.time(), [])
        self.env['HK_TOOL_SCREENSHOT'] = str(HERE / 'screenshot.sh')
        out = self.tmp / 'out' / 'home.png'
        d = self.hkj('shot', '--run', str(live), '-o', str(out), env=dict(SCREENSHOT_MAC=str(mac)))
        self.assertEqual(d['png'], str(out))
        self.assertEqual(out.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(out.with_suffix('.rgb565').stat().st_size, 8)
        self.assertEqual(out.with_suffix('.json').read_text(), '{"seq": 1}')
        self.assertTrue(os.access(HERE / 'screenshot.sh', os.X_OK))

    def make_family(self):
        """Two boots of one family: int3 (older) and int4 (newer, with hands on the phone and a recentsd respawn loop)."""
        self.make_image('a7-ios-system-int3', 'debug=0x8 blazer_deadline=900')
        self.make_image('a7-ios-system-int4', 'debug=0x8 blazer_deadline=900')
        root = self.repo / 'research/laguna-usb-fix/attempts'
        t0 = time.time() - 7200
        a = self.make_live_run(root, 'a7-int3', '20261103-100000', t0,
                           [(41, 'exec SpringBoard'), (42, 'exec backboardd'), (90, 'usertrap: Photos[300] pc 0x1')],
                           markers=[('LIVEBOOT', 41.0, 'SPRINGBOARD SpringBoard'), ('LIVEBOOT', 70.0, 'UI_READY')],
                           image='a7-ios-system-int3')
        t1 = time.time() - 3600
        b = self.make_live_run(root, 'a7-int4-confirm', '20261103-110000', t1,
                           [(40, 'exec SpringBoard'), (41, 'exec backboardd'), (100, 'blazer-touch: tcm: finger 0 down at 1, 2'),
                            (110, 'HK LIVE dispatch gen=5 edge=down op=98 x=170 y=279 us=1'),
                            (120, 'blazer-keys: volume down pressed'), (120.1, 'blazer-power-key: pressed'),
                            (130, 'exec recentsd'), (131, 'CRASH recentsd reason ns 1'), (132, 'exec recentsd'),
                            (133, 'exec xpcproxy'), (134, 'exec xpcproxy')],
                           markers=[('LIVEBOOT', 40.0, 'SPRINGBOARD SpringBoard'), ('LIVEBOOT', 65.0, 'UI_READY'),
                                    ('UIRUN', 109.0, 'ACTION tap --tap 170 279 -> dispatched'),
                                    ('LIVEBOOT', 131.0, 'CRASH recentsd')],
                           image='a7-ios-system-int4')
        ing = self.hkj('ingest', str(a), str(b))
        return [x['attempt'] for x in ing['items']]

    def test_timeline(self):
        _, b = self.make_family()
        d = self.hkj('timeline', b)
        kinds = [e['kind'] for e in d['events']]
        self.assertEqual(d['source'], 'live')
        self.assertEqual(kinds.count('physical'), 3)
        self.assertEqual(kinds.count('input'), 1)
        self.assertNotIn('xpcproxy', json.dumps(d['events']))
        self.assertEqual(d['respawns'], {'recentsd': 2})
        self.assertEqual([e['t'] for e in d['events']], sorted(e['t'] for e in d['events']))
        sb = [e for e in d['events'] if e['text'] == 'exec SpringBoard'][0]
        self.assertAlmostEqual(sb['t'], 40.0, places=0)
        self.assertEqual(sum(1 for e in d['events'] if 'CRASH recentsd' in e['text']), 1)   # the marker repeats the console
        f = self.hkj('timeline', b, '--kind', 'physical', '--since-t', '115')
        self.assertEqual([e['text'][:11] for e in f['events']], ['blazer-keys', 'blazer-powe'])
        self.assertTrue((self.store / b / 'timeline.txt').is_file())
        self.assertIn('respawns', self.hk('timeline', b, code=0).stdout)

    def test_diff_and_previous_of_family(self):
        self.fake_probe()
        self.fake_crashdoc()
        a, b = self.make_family()
        write(self.store / a / 'crashes' / 'crashes.json', json.dumps(dict(signatures=[
            dict(sig='usertrap:Photos@0x1', proc='Photos', incidents=1, status='open'),
            dict(sig='usertrap:backboardd@0x1', proc='backboardd', incidents=1, status='open')])))
        d = self.hkj('diff', a, b, '--no-subsystems')
        self.assertEqual((d['a'], d['b']), (a, b))
        self.assertEqual([x['sig'] for x in d['crashes']['gone']], ['usertrap:Photos@0x1'])
        self.assertEqual(d['crashes']['changed'], [dict(sig='usertrap:backboardd@0x1', a=1, b=3)])
        self.assertIn(dict(proc='recentsd', a=0, b=2), d['respawns'])
        self.assertEqual(d['head']['image'], dict(a='a7-ios-system-int3', b='a7-ios-system-int4'))
        tl = {x['event']: x for x in d['timeline']}
        self.assertAlmostEqual(tl['UI_READY']['delta'], -5.0, places=0)
        self.assertAlmostEqual(tl['exec SpringBoard']['delta'], -1.0, places=0)
        self.assertEqual(self.hkj('diff', b, '--no-subsystems')['a'], a)        # B alone: its previous same-family boot
        self.assertEqual(self.hkj('diff', a, code=3)['error'], 'no_attempt')     # nothing earlier
        self.assertIn('crash signatures: 0 new, 1 gone, 1 count changes', self.hk('diff', a, b, '--no-subsystems', code=0).stdout)

    def test_triage_writes_triage_md(self):
        self.fake_probe()
        self.fake_crashdoc()
        a, b = self.make_family()
        r = self.hkj('triage', b, code=3)                              # backlog.py missing: still written, error listed
        self.assertEqual(r['prev'], a)
        self.assertEqual(r['errors'][0]['tool'], 'backlog')
        md = (self.store / b / 'TRIAGE.md').read_text()
        for want in ('# Triage', 'PHYSICAL input during the boot: 3', 'recentsd 2', f'## Diff vs {a}', 'hk logs backboardd',
                     'hk timeline'):
            self.assertIn(want, md)
        self.fake_tool('backlog', '''import json, sys
a = sys.argv[1:]
json.dump(dict(items=[dict(id='probe:wifi', severity='med', title='Wi-Fi', next=dict(test='join a network')),
                      dict(id='probe:gps', severity='high', title='GPS (no verdict in this boot)'),
                      dict(id='crash:c1aa', severity='high', title='userabort:recentsd', owner='UNASSIGNED')]),
          open(a[a.index('--json') + 1], 'w'))
''')
        r = self.hkj('triage', b)
        self.assertEqual(r['errors'], [])
        md = (self.store / b / 'TRIAGE.md').read_text()
        self.assertIn('[high] crash:c1aa: userabort:recentsd — owner UNASSIGNED', md)
        self.assertIn('[med] probe:wifi: Wi-Fi — owner UNASSIGNED; next: join a network', md)   # partial in this boot
        self.assertLess(md.index('crash:c1aa'), md.index('probe:wifi'))
        self.assertNotIn('probe:gps', md)                               # not this boot's evidence
        self.assertEqual(self.hkj('triage', b, '--no-backlog', '--prev', a)['prev'], a)



    # --- 2026-11-04 lane TOOLS-2: boot post-hooks, hk probes, hk watch

    FAKE_SHOT = """#!/bin/sh
# fake screenshot.sh: the first call is refused busy (a UI step's picture in flight), later ones save a PNG
echo "shot $*" >> "$FAKE_LOG"
n=$(grep -c '^shot ' "$FAKE_LOG")
out=''
while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
if [ "$n" = 1 ]; then echo 'screenshot: reader refused: busy' >&2; exit 4; fi
mkdir -p "$(dirname "$out")"; printf '\\211PNG\\r\\n\\032\\n' > "$out"; echo "$out"
"""

    def fake_live_boot(self, body_after_ready='sleep 1.2'):
        self.fake_tool('live_boot', f"""#!/bin/sh
run="$LIVE_ATTEMPTS/live-20261104-050000-$2"
mkdir -p "$run"
printf 'LIVE_RUN=%s\\nLIVE_NAME=%s\\nLIVE_SOCK=/tmp/s\\nLIVE_T0=%s\\n' "$run" "$2" "$(date +%s)" > "$run/live.env"
echo "05:00:00.000 [    0.10] exec launchd" > "$run/console.txt"
printf 'LIVEBOOT 05:00:01.000 +1.0 CONSOLE_CONNECTED nonce 1\\n' > "$run/markers.txt"
sleep 0.4
printf 'LIVEBOOT 05:01:00.000 +60.0 UI_READY\\n' >> "$run/markers.txt"
{body_after_ready}
printf 'LIVEBOOT 05:10:00.000 +600.0 BOOT_RC 0\\n' >> "$run/markers.txt"
echo BOOT_RC=0 >> "$run/live.env"
echo "live_boot: run $run"
""", '.sh')

    def test_boot_post_hooks_picture_at_ui_ready_periodic_and_triage(self):
        self.make_image('a7-ios-system-int5', 'debug=0x8 blazer_deadline=900 blazer_usbcon=1 hk_dbg=0x1e1e1f')
        self.fake_live_boot()
        self.fake_tool('screenshot', self.FAKE_SHOT, '.sh')
        d = self.hkj('boot', 'a7-ios-system-int5', '--mach', '/k', '--shot-every', '0.3', env=dict(HK_AUTO_FIRST_S='0.6'))
        a = self.store / d['attempt']
        self.assertTrue((a / 'screens' / 'ui-ready.png').is_file())
        shots = d['auto']['shots']
        self.assertEqual(shots[0]['name'], 'ui-ready')
        self.assertTrue(shots[0]['ok'], shots[0])                              # retried once after "busy"
        self.assertTrue(any(s['name'].startswith('auto-') and s['ok'] for s in shots), shots)
        self.assertTrue(list((a / 'screens').glob('auto-001-t*.png')))
        calls = [l for l in (self.tmp / 'calls.log').read_text().splitlines() if l.startswith('shot ')]
        self.assertIn('--step 8', calls[0])
        self.assertEqual(len((a / 'screens' / 'auto.jsonl').read_text().splitlines()), len(shots))
        self.assertEqual(d['auto']['triage']['md'], str(a / 'TRIAGE.md'))     # crashdoc/probe missing: still written
        self.assertTrue((a / 'TRIAGE.md').is_file())
        self.assertTrue((a / 'auto.json').is_file())
        self.assertEqual(d['rc'], 0)
        self.assertIn('pictures: ', self.hk('boot', 'a7-ios-system-int5', '--mach', '/k', '--no-triage', code=0).stdout)

    def test_boot_post_hooks_opt_out_and_no_snapshot_gate(self):
        self.fake_live_boot('sleep 0.3')
        self.fake_tool('screenshot', self.FAKE_SHOT, '.sh')
        d = self.hkj('boot', 'a7-ios-system-wifi1', '--mach', '/k', '--no-auto')
        self.assertIsNone(d['auto'])
        self.assertFalse((self.store / d['attempt'] / 'TRIAGE.md').exists())
        d = self.hkj('boot', 'a7-ios-system-wifi1', '--mach', '/k', env=dict(HK_AUTO='0'))
        self.assertIsNone(d['auto'])
        # the image has no usbcon snapshot gate: no live picture is asked for, triage still runs
        d = self.hkj('boot', 'a7-ios-system-wifi1', '--mach', '/k')
        self.assertEqual(d['auto']['shots'], [])
        self.assertIn('no live pictures', ' '.join(d['auto']['notes']))
        self.assertTrue((self.store / d['attempt'] / 'TRIAGE.md').is_file())
        self.assertFalse((self.tmp / 'calls.log').exists() and 'shot ' in (self.tmp / 'calls.log').read_text())
        # --no-triage keeps the pictures
        self.make_image('a7-ios-system-int5', 'blazer_usbcon=1 blazer_usbcon_snap=1')
        d = self.hkj('boot', 'a7-ios-system-int5', '--mach', '/k', '--no-triage', '--shot-every', '0')
        self.assertNotIn('triage', d['auto'])
        self.assertEqual([s['name'] for s in d['auto']['shots']], ['ui-ready'])

    def test_boot_gates_and_ui_run_window(self):
        g = hk.boot_gates('blazer_usbcon=1 hk_dbg=0x1e1e1f')
        self.assertEqual(g, dict(console=True, snap=True, input=True, screen=0x1e))
        self.assertFalse(hk.boot_gates('blazer_usbcon_snap=1')['snap'])          # no console, no snapshot
        self.assertTrue(hk.boot_gates('blazer_usbcon=2 blazer_usbcon_snap=1')['snap'])
        self.assertEqual(hk.boot_gates('hk_screen=30 hk_dbg=junk')['screen'], 30)
        mk = write(self.tmp / 'markers.txt', 'UIRUN 05:00:00.000 +1.0 START 3 steps\n')
        self.assertTrue(hk.ui_run_active(mk))
        write(mk, 'UIRUN 05:00:00.000 +1.0 START 3 steps\nUIRUN 05:00:09.000 +9.0 END PASS\n')
        self.assertFalse(hk.ui_run_active(mk))

    def make_probe_files(self):
        write(self.repo / 'research/r1/int5/int5.probes.yaml',
              '# INT5: one probe file for a7-ios-system-int5 / a7-ios-system-int5-wifi-r1 (x).\n'
              '#   probe_eval.py --probes x <fastboot attempt> <live-...-a7-int5>\nversion: 1\nprobes: []\n')
        write(self.repo / 'research/r1/int4/int4.probes.yaml',
              '# int4: every feature merged into a7-ios-system-int4.\n#   live-<...>-a7-int4\n\nversion: 1\nprobes: []\n')
        write(self.repo / 'research/r2/b3/bt3.probes.yaml', '# bt3: phone acceptance rows.\nversion: 1\nprobes: []\n')
        write(self.repo / 'research/r2/w2/w2.probes.yaml', '# W2: one probe file for a7-wifi-w2-r1.\nversion: 1\nprobes: []\n')

    def test_probes_finds_the_image_family_file(self):
        self.make_probe_files()
        with unittest.mock.patch.dict(os.environ, self.env):
            for repo_attr in ('REPO', 'MAIN_CHECKOUT'):
                setattr(hk, '_saved_' + repo_attr, getattr(hk, repo_attr))
            hk.REPO, hk.MAIN_CHECKOUT = self.repo, self.tmp / 'no-main'
            try:
                def best(*names):
                    hits = hk.probes_for_image(list(names))
                    return (hits[0][0]['stem'], hits[0][1].split()[0]) if hits else None
                self.assertEqual(best('a7-ios-system-int5'), ('int5', 'header'))
                self.assertEqual(best('a7-ios-system-int5-wifi-r1'), ('int5', 'header'))
                self.assertEqual(best('a7-ios-system-int4-softblur-r3'), ('int4', 'family'))
                self.assertEqual(best('a7-int4-confirm'), ('int4', 'family'))
                self.assertEqual(best('a7-ios-system-bt3'), ('bt3', 'stem'))
                self.assertEqual(best('20261104-030612-a7-wifi-w2-r1'), ('w2', 'header'))
                self.assertIsNone(best('a7-ios-system-jb1'))
                own = write(self.repo / 'research/images/a7-ios-system-int5/own.probes.yaml', 'version: 1\nprobes: []\n')
                self.assertEqual(hk.probes_for_image(['a7-ios-system-int5'])[0], (unittest.mock.ANY, 'image dir'))
                own.unlink()
            finally:
                hk.REPO, hk.MAIN_CHECKOUT = hk._saved_REPO, hk._saved_MAIN_CHECKOUT
        lst = self.hkj('probes', '--list')
        self.assertEqual(len(lst['files']), 4)
        self.assertEqual(self.hkj('probes', 'a7-ios-system-int4-r9', '--list')['files'][0]['rule'], 'family int4 (of int4-r9)')
        self.assertEqual(self.hkj('probes', 'a7-ios-system-int5', code=3)['error'], 'no_attempt')
        self.assertEqual(self.hkj('probes', 'a7-ios-system-jb1', code=3)['error'], 'no_probes')
        # run over the image's newest attempt; probe_eval gets --probes
        self.fake_tool('probe', 'import json, sys\nd = ' + repr(PROBE_DOC) +
                       f'\njson.dump(sys.argv[1:], open({str(self.tmp / "probe-argv.json")!r}, "w"))' + FAKE_PROBE_TAIL)
        self.make_image('a7-ios-system-int5', 'blazer_usbcon=1')
        live = self.make_live_run(self.repo / 'research/laguna-usb-fix/attempts', 'a7-int5', '20261104-050000', time.time() - 900,
                                  [(40, 'exec SpringBoard')], image='a7-ios-system-int5')
        aid = self.hkj('ingest', str(live))['items'][0]['attempt']
        r = self.hkj('probes', 'a7-ios-system-int5')
        self.assertEqual(r['attempt'], aid)
        res = r['results'][0]
        self.assertTrue(res['probes'].endswith('int5/int5.probes.yaml'))
        self.assertEqual(res['counts'], dict(partial=1, works=2, none=1))
        argv = json.loads((self.tmp / 'probe-argv.json').read_text())
        self.assertEqual(argv[argv.index('--probes') + 1], str(self.repo / 'research/r1/int5/int5.probes.yaml'))
        cached = json.loads((self.store / aid / 'probes' / 'image-int5.json').read_text())
        self.assertTrue(cached['probes'].endswith('int5.probes.yaml'))
        self.assertEqual(self.hkj('probes', 'a7-ios-system-int5', '--row', 'wifi')['results'][0]['rows'][0]['id'], 'wifi')
        # triage shows the image probe rows
        self.hkj('triage', aid, '--no-backlog', code=3)
        md = (self.store / aid / 'TRIAGE.md').read_text()
        self.assertIn('## Image probes (research/r1/int5/int5.probes.yaml)', md)
        self.assertIn('partial  wifi: Wi-Fi', md)

    def test_watch_one_frame_text_json_html(self):
        self.fake_probe()
        self.make_image('a7-ios-system-int4', 'blazer_usbcon=1')
        self.make_probe_files()
        t0 = time.time() - 300
        con = [(40, 'exec SpringBoard'), (41, 'exec backboardd'),
               (50, 'HK TOP: t=200 frames+770 cpu_ms=99250: SpringBoard[28]=35333 iconservicesagen[95]=24703 lsd[82]=4449'),
               (60, 'userabort: recentsd[1939] reason ns 1'), (60.1, 'CRASH recentsd'), (61, 'userabort: recentsd[1941] x'),
               (62, 'exec: SIGKILL to InputUI[1186] (x)'), (70, 'blazer-touch: tcm: finger 0 down at 1, 2'),
               (71, 'HK LIVE dispatch gen=5 edge=down op=98 x=1 y=2 us=1'), (72, 'HKMAIN: stall 900 ms Preferences')]
        con += [(80 + i, 'exec fairplayd.H2') for i in range(6)]
        live = self.make_live_run(self.repo / 'research/laguna-usb-fix/attempts', 'a7-int4-x', '20261104-050000', t0, con,
                                  markers=[('LIVEBOOT', 41.0, 'CONSOLE_CONNECTED nonce 1'), ('LIVEBOOT', 43.0, 'SPRINGBOARD SpringBoard'),
                                           ('LIVEBOOT', 70.0, 'UI_READY'), ('UIRUN', 90.0, 'START 3 steps')],
                                  image='a7-ios-system-int4')
        aid = self.hkj('ingest', str(live))['items'][0]['attempt']
        write(self.store / aid / 'screens' / 'ui-ready.png', 'png')
        w = self.hkj('watch', aid, '--html')
        self.assertEqual(w['state'], 'running')
        self.assertTrue(w['ui_run'])
        self.assertEqual([m['name'] for m in w['milestones']], ['CONSOLE_CONNECTED', 'SPRINGBOARD', 'UI_READY'])
        self.assertEqual(w['missing'], ['LAUNCHD'])
        self.assertEqual(w['crashes'], [dict(proc='recentsd', count=2), dict(proc='InputUI', count=1)])
        self.assertEqual(w['respawns'], {'fairplayd.H2': 6})
        self.assertEqual(w['counts'], dict(physical=1, input=1, stall=1))
        self.assertEqual(w['top']['frames'], 770)
        self.assertEqual(w['top']['procs'][0], dict(proc='SpringBoard', pid=28, ms=35333))
        self.assertTrue(w['probes_file'].endswith('int4/int4.probes.yaml'))
        self.assertEqual({r['id']: r['verdict'] for r in w['probes']}['touch'], 'works')
        self.assertEqual(w['pictures'][0], str(self.store / aid / 'screens' / 'ui-ready.png'))
        html = Path(w['html']).read_text()
        self.assertIn("src='screens/ui-ready.png?", html)
        self.assertIn('http-equiv=refresh', html)
        txt = self.hk('watch', '--run', str(live), '--once', '--no-probe', code=0).stdout
        for want in ('[RUNNING]', 'UI SCRIPT RUNNING', 'recentsd x2', 'fairplayd.H2 6', 'PHYSICAL: 1', 'HK TOP t=200 frames+770',
                     'latest picture: '):
            self.assertIn(want, txt)
        # a boot that ended: the frame loop stops by itself
        with open(live / 'markers.txt', 'a') as f:
            f.write(f'LIVEBOOT {self.wall(t0 + 600)} +600.0 BOOT_RC 0\n')
        r = self.hk('watch', aid, '--interval', '0.1', '--no-probe', code=0)
        self.assertEqual(r.stdout.count('hk watch '), 1)
        self.assertIn('[ENDED]  t+600s', r.stdout)

    def test_watch_state_reads_only_new_bytes(self):
        live = self.make_live_run(self.tmp, 'a7-w', '20261104-050000', time.time(), [(1, 'exec launchd')])
        ws = hk.WatchState(live)
        ws.poll()
        self.assertEqual(ws.execs, {'launchd': 1})
        with open(live / 'console.txt', 'a') as f:
            f.write('05:00:02.000 [    2.00] userabort: Pho')          # half a line: nothing yet
        ws.poll()
        self.assertEqual(ws.crashes(), [])
        with open(live / 'console.txt', 'a') as f:
            f.write('tos[300] pc 0x1\n')
        ws.poll()
        self.assertEqual(ws.crashes(), [dict(proc='Photos', count=1)])
        self.assertEqual(ws.lines, 2)

    def test_note_and_back_keep_the_live_paths_of_a_killed_boot(self):
        """bt3 (2026-11-04): hk boot never returned (paths={}), hk back wrote that manifest back over the index."""
        aid, t0 = '20261104-041625-a7-bt3', time.time() - 600
        d = self.store / aid
        write(d / 'manifest.json', json.dumps(dict(schema='hk.manifest/1', id=aid, name='a7-bt3', kind='phone', created_t=t0,
                                                   image=dict(name='a7-ios-system-bt3'), paths={}, result={})))
        write(self.store / 'index.jsonl', json.dumps(dict(id=aid, kind='phone', created_t=t0, paths={})) + '\n')
        live = self.make_live_run(d, 'a7-bt3', aid[:15], t0, [(40, 'exec SpringBoard')])
        self.hkj('note', aid, 'owner', 'looked')
        rec = [r for r in self.hkj('find')['attempts'] if r['id'] == aid][0]
        self.assertEqual(rec['paths']['live'], str(live))


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


class ToFastbootTest(unittest.TestCase):
    """hk state's classes and hk to-fastboot's every branch, on a fake phone-bridge (adb, fastboot, mac incl. usbcon).
    HkTest's fixtures, without re-running HkTest's own tests."""
    tearDown, make_pb, make_image, fake_tool, hk, hkj = (HkTest.tearDown, HkTest.make_pb, HkTest.make_image, HkTest.fake_tool,
                                                         HkTest.hk, HkTest.hkj)

    def setUp(self):
        HkTest.setUp(self)
        self.env.update(HK_TO_FB_POLL_S='0.05', FAKE_RESET='ok', FAKE_READER='ok', FAKE_PARK_TO='fastboot')
        log = '"$FAKE_LOG"'
        write(self.pb / 'adb', f"""#!/bin/sh
echo "adb $*" >> {log}
echo "List of devices attached"
st=$(cat "$FAKE_STATE")
[ "$st" = android ] && printf 'SERIAL\\tdevice\\n'
[ "$st" = recovery ] && printf 'SERIAL\\trecovery\\n'
[ "$st" = unauth ] && printf 'SERIAL\\tunauthorized\\n'
if [ "$1" = reboot ] && [ "$st" = android ]; then echo fastboot > "$FAKE_STATE"; fi
exit 0
""", 0o755)
        write(self.pb / 'mac', f"""#!/bin/sh
echo "mac $* [cwd $(pwd)]" >> {log}
st=$(cat "$FAKE_STATE")
if [ "$1" = usb ]; then
  [ "$st" = ios ] && echo "  1209:0002  hackios XNU console  (pid.codes)"
  [ "$st" = shim ] && echo "  1209:0001  hackios shim  (pid.codes)"
  exit 0
fi
case "$*" in
  *--reset-now*)
    case "$FAKE_RESET" in
      ok) echo "$FAKE_PARK_TO" > "$FAKE_STATE"; echo '{{"state": "reset", "mode": 2}}'; exit 0;;
      refused) echo '{{"state": "refused", "error": "reset not armed: this boot runs blazer_usbcon=1", "ambiguous": false}}'; exit 4;;
      gone) echo '{{"state": "unknown", "error": "[Errno 2] No such file or directory", "ambiguous": true}}' >&2; exit 4;;
      odd) echo '{{"state": "unknown", "error": "timed out", "ambiguous": true}}'; exit 4;;
    esac;;
  *--reset-after*)
    case "$FAKE_READER" in
      ok) echo "$FAKE_PARK_TO" > "$FAKE_STATE"; echo "usbcon: connected: nonce 0x1"; echo "usbcon: reset accepted at t=0.0s (reset-after); the phone panics, resets, and parks"; exit 0;;
      stall) echo "usbcon: reset failed at t=0.0s (reset-after): [Errno 32] Pipe error. A stall means blazer_usbcon=1"; exit 0;;
      busy) echo "usbcon.py: error: another usbcon reader owns USB; use its --control-socket"; exit 2;;
    esac;;
esac
exit 1
""", 0o755)

    def live_run(self):
        run = self.store / 'x' / 'live-20261111-000000-t'
        write(run / 'live.env', 'LIVE_RUN=x\nLIVE_SOCK=/tmp/hackios-live-test.sock\n')
        write(run / 'console.txt', 'boot\n')
        return run

    def calls(self):
        p = self.tmp / 'calls.log'
        return p.read_text() if p.exists() else ''

    def tofb(self, code=0, **env):
        return self.hkj('to-fastboot', '--wait', '5', code=code, env=env or None)

    def test_state_classes_and_how(self):
        for st, want in (('fastboot', 'fastboot'), ('android', 'android'), ('unauth', 'android'), ('ios', 'ios-live'),
                         ('shim', 'shim'), ('recovery', 'recovery'), ('off', 'absent')):
            self.state.write_text(st)
            d = self.hkj('state', env=dict(HK_SHELL='tcp:127.0.0.1:1'))
            self.assertEqual(d['state'], want, st)
            self.assertTrue(d['how'])
        self.state.write_text('ios')
        self.assertIn('1209:0002', self.hkj('state', env=dict(HK_SHELL='tcp:127.0.0.1:1'))['how'])
        r = self.hk('state', env=dict(HK_SHELL='tcp:127.0.0.1:1'), code=0)
        self.assertTrue(r.stdout.startswith('ios-live  ('), r.stdout)

    def test_fastboot_does_nothing(self):
        d = self.tofb()
        self.assertEqual((d['start'], d['state'], d['action']), ('fastboot', 'fastboot', 'none'))
        self.assertNotIn('reboot', self.calls())

    def test_android_reboots_to_bootloader(self):
        self.state.write_text('android')
        d = self.tofb()
        self.assertEqual(d['state'], 'fastboot')
        self.assertEqual(d['action'], 'adb reboot bootloader')
        self.assertIn('adb reboot bootloader', self.calls())
        self.assertEqual(self.hkj('lock', 'status')['state'], 'free')

    def test_android_refused_while_someone_holds_the_phone(self):
        self.state.write_text('android')
        self.hkj('lock', 'acquire', '--holder', 'owner-attended')
        self.assertEqual(self.tofb(code=4)['error'], 'phone_busy')
        self.assertNotIn('adb reboot', self.calls())

    def test_ios_live_with_reader_uses_the_socket(self):
        self.state.write_text('ios')
        self.live_run()
        d = self.tofb()
        self.assertEqual(d['state'], 'fastboot')
        self.assertEqual(d['action'], 'usbcon reset op (socket)')
        self.assertTrue(d['ramdump_kept'])
        c = self.calls()
        self.assertIn('--control-socket /tmp/hackios-live-test.sock --reset-now', c)
        self.assertIn(f'[cwd {self.repo}]', c)
        self.assertNotIn('--reset-after', c)
        self.assertNotIn('adb reboot', c)

    def test_ios_live_mode1_is_refused_cleanly(self):
        self.state.write_text('ios')
        self.live_run()
        d = self.tofb(code=6, FAKE_RESET='refused')
        self.assertEqual(d['error'], 'reset_not_armed')
        self.assertIn('deadline', d['message'])
        self.assertIn('COLD', d['message'])
        self.state.write_text('ios')
        d = self.tofb(code=6, FAKE_RESET='odd')
        self.assertEqual(d['error'], 'reset_unknown')
        self.assertNotIn('--reset-after', self.calls())      # an unclear answer is never followed by a second reset

    def test_ios_live_stale_socket_falls_back_to_a_short_reader(self):
        self.state.write_text('ios')
        self.live_run()
        d = self.tofb(FAKE_RESET='gone')
        self.assertEqual(d['action'], 'usbcon reset op (reader)')
        self.assertIn('--reset-after 0', self.calls())

    def test_ios_live_without_reader(self):
        self.state.write_text('ios')
        d = self.tofb()
        self.assertEqual(d['action'], 'usbcon reset op (reader)')
        self.assertNotIn('--reset-now', self.calls())
        for reader, code, err in (('stall', 6, 'reset_not_armed'), ('busy', 4, 'reader_busy')):
            self.state.write_text('ios')
            self.assertEqual(self.tofb(code=code, FAKE_READER=reader)['error'], err)

    def test_ios_live_that_comes_back_in_android_goes_on_to_fastboot(self):
        self.state.write_text('ios')
        d = self.tofb(FAKE_PARK_TO='android')
        self.assertEqual(d['state'], 'fastboot')
        self.assertFalse(d['ramdump_kept'])
        self.assertEqual(d['action'], 'usbcon reset op (reader) then adb reboot bootloader')

    def test_absent_recovery_shim_need_the_owner_or_time(self):
        for st, err in (('off', 'owner_action'), ('recovery', 'owner_action'), ('shim', 'transient')):
            self.state.write_text(st)
            d = self.tofb(code=6)
            self.assertEqual(d['error'], err, st)
        self.state.write_text('off')
        d = self.tofb(code=6)
        self.assertIn('power + volume-down', d['message'])
        self.assertIn('ramdump', d['message'])
        self.assertNotRegex(self.calls(), r'adb reboot|fastboot (reboot|oem)|reset')

    def test_cycle_passes_end_options(self):
        self.fake_tool('cycle', """import sys, json, pathlib
a = sys.argv[1:]
out = pathlib.Path(a[a.index('--out') + 1]); out.mkdir(parents=True)
(out / 'report.json').write_text(json.dumps(dict(verdict='PASS', return_check_verdict='PASS', argv=a)))
print('hk_cycle: verdict PASS')
""")
        d = self.hkj('cycle', 'a7-ios-system-wifi1', '--end-on', 'wifi: joined', '--end-grace', '3')
        m = json.loads((self.store / d['attempt'] / 'manifest.json').read_text())
        cmd = ' '.join(m['command'])
        self.assertIn('--end-on wifi: joined', cmd)
        self.assertIn('--end-grace 3.0', cmd)


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
