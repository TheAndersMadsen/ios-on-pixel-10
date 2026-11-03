#!/usr/bin/env python3
"""Host test of tools/hklog.py. No device. Run: python3 -I tools/test_hklog.py"""
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('hklog', HERE / 'hklog.py')
hklog = importlib.util.module_from_spec(spec)
sys.modules['hklog'] = hklog
spec.loader.exec_module(hklog)

# The status lines as bsd/kern/hk_obs.c prints them, the mirror's as hk_logmirror.c does
RAMDUMP = '\n'.join([
    'TEGU-XNU STAGE0',
    'Darwin Kernel Version 25.5.0: test',
    'blazer-root: PAGE_SIZE 16384 mem 33b000000 at 882000000, deadline 900 s',
    'hk_env: wifid gets DYLD_INSERT_LIBRARIES=/private/var/hk/hk_logmirror.dylib',
    'HKL wifid[71] -- mirror on: os_log and stderr, 8 lines/s burst 64, 320 B a line',
    'HKL wifid[71] [WiFiManager] __WiFiManagerDeviceAttached: no interface',
    'HKL configd[40] [InterfaceNamer] *COMPLETE*',
    'HKL MobilePhone[300] [Contacts] access denied',
    'blazer-root: watch t 10003 ms stage pid1_exec reads 1 blocks 2 busy 3 ms max 4 us last lba 5',
    'HKOBS 1 tick t=10 wifi: off (no blazer_wifi=1)',
    'HKOBS 1 tick t=10 bt: off (no blazer_bt=)',
    'HKOBS 1 tick t=10 usb: console running, configured, host connected, stream 1000 B, served 900 B, backlog 100, reads 3, restarts 0, stalls 0, fails 0 | net off, rx 0 tx 0 frames, bad 0/0',
    'HKOBS 1 tick t=10 con: budget 2048 B/s burst 32768, ok 3 lines 120 B (not in the table 0), dropped 0 lines 0 B',
    'HKOBS 1 tick t=10 proc: wifid 1/0 - l2 d0 configd 1/0 - l1 d0 MobilePhone 3/2 s6 l1 d5 backboardd 2/1 s11',
    'blazer-bt: waiting for Wi-Fi firmware',
    'com.apple.xpc.launchd|2026-11-03 19:41:57.821459 (user/501/com.apple.wifid [71]) <Notice>: exited due to SIGABRT',
    '1969-12-31 16:02:03.933641-0800 tccd[33:730] [access] TCCDMainDatabase created',
    'something unclassified',
    'HKOBS 2 deadline t=900 proc: wifid 2/1 s6 l9 d0',
    'panic(cpu 0 caller 0xfffffe00079fe060): blazer-root: deadline 900 s',
    ' c.launchd|older residue',
    'HKL wifid[5] residue of an older boot',
    'Darwin Kernel Version 25.5.0: older',
]) + '\n'


def read(p):
    return Path(p).read_text() if Path(p).exists() else ''


class Split(unittest.TestCase):
    def run_split(self, text, *args):
        d = tempfile.mkdtemp()
        src = Path(d) / 'kernel.log'
        src.write_bytes(text.encode() if isinstance(text, str) else text)
        out = Path(d) / 'out'
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            self.assertEqual(hklog.main([str(src), '-o', str(out), *args]), 0)
        finally:
            sys.stderr = old
        return out, err.getvalue()

    def test_ramdump_files(self):
        out, err = self.run_split(RAMDUMP)
        self.assertIn('boot ended: panic line', err)
        wifi = read(out / 'wifi.log')
        self.assertIn('HKL wifid[71] [WiFiManager]', wifi)
        self.assertIn('HKOBS 1 tick t=10 wifi: off', wifi)
        self.assertIn('exited due to SIGABRT', wifi)           # launchd's line about wifid's job
        self.assertIn('exited due to SIGABRT', read(out / 'proc.log'))
        self.assertIn('blazer-bt: waiting', read(out / 'bt.log'))
        self.assertIn('*COMPLETE*', read(out / 'net.log'))
        self.assertIn('[Contacts] access denied', read(out / 'apps.log'))
        self.assertIn('usb: console running', read(out / 'usb.log'))
        self.assertEqual(read(out / 'other.log').count('\n'), 4)   # STAGE0, Darwin, PAGE_SIZE, "something unclassified"
        self.assertIn('something unclassified', read(out / 'other.log'))
        # per program
        self.assertEqual(read(out / 'hkl/wifid.log').count('\n'), 2)
        self.assertIn('[access] TCCDMainDatabase', read(out / 'hkl/tccd.log'))   # an old direct-mirror line
        self.assertIn('[access] TCCDMainDatabase', read(out / 'apps.log'))
        # older residue after the panic: not read
        allf = read(out / 'all.log')
        self.assertNotIn('residue', allf)
        self.assertTrue(allf.rstrip().endswith('blazer-root: deadline 900 s'))

    def test_timestamps(self):
        out, _ = self.run_split(RAMDUMP)
        lines = read(out / 'all.log').splitlines()
        self.assertTrue(lines[0].startswith('[t>=?] TEGU-XNU STAGE0'))
        self.assertTrue(any(x.startswith('[t>=10s] HKOBS 1 tick') for x in lines))
        self.assertTrue(any(x.startswith('[t>=10s] blazer-root: watch') for x in lines))
        self.assertTrue(any(x.startswith('[t>=900s] HKOBS 2 deadline') for x in lines))

    def test_summary(self):
        out, _ = self.run_split(RAMDUMP)
        s = read(out / 'summary.txt')
        self.assertIn('usb   #1 tick t=10: console running', s)
        self.assertIn('con   #1 tick t=10: budget 2048', s)
        # the last proc line wins per program: wifid from the deadline line, the others from tick 1
        rows = {r.split()[0]: r.split() for r in s.splitlines() if r.startswith('  ') and len(r.split()) >= 5 and r.split()[1].isdigit()}
        self.assertEqual(rows['wifid'][1:6], ['2', '1', '1', 's6', '9'])
        self.assertEqual(rows['MobilePhone'][1:7], ['3', '2', '2', 's6', '1', '5'])
        self.assertEqual(rows['backboardd'][1:5], ['2', '1', '1', 's11'])
        self.assertIn('wifid', s.split('HKL lines seen here')[1])

    def test_whole_and_max_bytes(self):
        out, err = self.run_split(RAMDUMP, '--whole')
        self.assertIn('residue of an older boot', read(out / 'hkl/wifid.log'))
        out, err = self.run_split(RAMDUMP, '--max-bytes', '60')
        self.assertIn('--max-bytes 60', err)
        self.assertNotIn('HKL', read(out / 'all.log'))

    def test_second_banner_ends(self):
        out, err = self.run_split('Darwin Kernel Version a\nHKL lsd[1] one\nDarwin Kernel Version b\nHKL lsd[2] two\n')
        self.assertIn('second XNU banner', err)
        self.assertEqual(read(out / 'hkl/lsd.log').count('\n'), 1)

    def test_live_stamps_kept_and_no_cut(self):
        text = '19:41:57.821 HKL lsd[9] a\n19:41:58.001 panic(cpu 0): x\n19:41:59.500 HKL lsd[9] after\n'
        out, _ = self.run_split(text)
        hk = read(out / 'hkl/lsd.log').splitlines()
        self.assertEqual(hk, ['[19:41:57.821] HKL lsd[9] a', '[19:41:59.500] HKL lsd[9] after'])

    def test_binary_and_nul_safe(self):
        out, _ = self.run_split(b'DBGC\xff\xfe: \x00\x00HKL lsd[1] ok\xe2\x80\x94\nHKL ../evil[2] x\n')
        self.assertIn('HKL lsd[1] ok—', read(out / 'hkl/lsd.log'))
        self.assertFalse(any('..' in p.name for p in (out / 'hkl').iterdir()))
        self.assertTrue(all(p.resolve().parent == (out / 'hkl').resolve() for p in (out / 'hkl').iterdir()))

    def test_grep(self):
        d = tempfile.mkdtemp()
        src = Path(d) / 'k.log'
        src.write_text(RAMDUMP)
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            hklog.main([str(src), '--grep', 'bt'])
        finally:
            sys.stdout = old
        self.assertEqual([x for x in buf.getvalue().splitlines() if x], ['[t>=10s] HKOBS 1 tick t=10 bt: off (no blazer_bt=)',
                                                                          '[t>=10s] blazer-bt: waiting for Wi-Fi firmware'])
        self.assertFalse((Path(d) / 'k.log.hklog').exists())

    def test_classify_and_proc_parse(self):
        self.assertEqual(hklog.classify('HKL bluetoothd[5] x'), (['bt'], 'bluetoothd'))
        self.assertEqual(hklog.classify('HKL locationd[5] x')[0], ['location'])
        self.assertEqual(hklog.classify('HKOBS 3 tick t=30 fw: line 4: wl0: up')[0], ['wifi', 'status'])
        self.assertEqual(hklog.parse_proc(' lsd 3/2 s6 l120 d4 x 1/0 -'), {'lsd': (3, 2, 's6', 120, 4), 'x': (1, 0, '-', None, None)})


class Follow(unittest.TestCase):
    def test_follow_growing_file_and_restart(self):
        d = tempfile.mkdtemp()
        src = Path(d) / 'console.txt'
        out = Path(d) / 'out'
        sp = hklog.Splitter(out)
        steps = [b'12:00:00.000 HKL lsd[1] one\n12:00:00.100 HKL lsd[1] tw',
                 b'o\n12:00:01.000 HKOBS 1 tick t=10 wifi: off\n',
                 None,                                    # the file is replaced by a shorter one: a new run
                 b'12:01:00.000 HKL lsd[2] new run\n']
        src.write_bytes(b'')
        state = {'i': 0, 't': 0.0}

        def sleep(_):
            i = state['i']
            state['i'] += 1
            state['t'] += 1
            if i < len(steps):
                if steps[i] is None:
                    src.write_bytes(b'')
                else:
                    with open(src, 'ab') as f:
                        f.write(steps[i])

        why = hklog.follow(str(src), sp, idle_exit=3, sleep=sleep, clock=lambda: state['t'])
        sp.close()
        self.assertEqual(why, 'idle 3 s')
        lines = read(out / 'hkl/lsd.log').splitlines()
        self.assertEqual(lines, ['[12:00:00.000] HKL lsd[1] one', '[12:00:00.100] HKL lsd[1] two', '[12:01:00.000] HKL lsd[2] new run'])
        self.assertIn('wifi: off', read(out / 'wifi.log'))
        self.assertIn('lsd', read(out / 'summary.txt'))

    def test_follow_waits_for_the_file(self):
        d = tempfile.mkdtemp()
        src = Path(d) / 'later.txt'
        sp = hklog.Splitter(Path(d) / 'o')
        state = {'t': 0.0}

        def sleep(_):
            state['t'] += 1
            if state['t'] == 2:
                src.write_bytes(b'12:00:00.000 HKL lsd[1] hi\n')

        why = hklog.follow(str(src), sp, idle_exit=5, sleep=sleep, clock=lambda: state['t'])
        sp.close()
        self.assertEqual(why, 'idle 5 s')
        self.assertIn('hi', read(Path(d) / 'o' / 'hkl/lsd.log'))

    def test_follow_pipe(self):
        d = tempfile.mkdtemp()
        r, w = os.pipe()
        out = Path(d) / 'o'

        def writer():
            with os.fdopen(w, 'wb') as f:
                f.write(b'HKL lsd[1] piped\n')
        t = threading.Thread(target=writer)
        t.start()
        old = sys.stdin
        sys.stdin = os.fdopen(r, 'r')
        try:
            sp = hklog.Splitter(out)
            why = hklog.follow('-', sp)
            sp.close()
        finally:
            sys.stdin.close()
            sys.stdin = old
        t.join()
        self.assertEqual(why, 'end of input')
        self.assertIn('piped', read(out / 'hkl/lsd.log'))


if __name__ == '__main__':
    unittest.main(verbosity=1)
