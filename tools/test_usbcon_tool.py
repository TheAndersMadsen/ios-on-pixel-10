#!/usr/bin/env python3
"""Host test of tools/usbcon.py against a fake device. No pyusb, no USB. Run: python3 -I tools/test_usbcon_tool.py"""
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
spec = importlib.util.spec_from_file_location('usbcon', HERE / 'usbcon.py')
usbcon = importlib.util.module_from_spec(spec)
sys.modules['usbcon'] = usbcon
spec.loader.exec_module(usbcon)


class FakeUSBError(Exception):
    def __init__(self, text, errno=None):
        super().__init__(text)
        self.errno = errno


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakePhone:
    """The kernel's request semantics, as in blazer_usbcon_core.inc."""

    def __init__(self, clock, ring=4096, mode=2):
        self.clock, self.ring, self.mode = clock, ring, mode
        self.stream = bytearray()
        self.script = []        # (time, function)
        self.present = True
        self.nonce, self.entry = 0xabc, 0x1
        self.reset_accepted_at = None
        self.requests = []
        self.restarts = 0
        self.timeout_next = 0

    def emit(self, data):
        self.stream += data

    def tick(self):
        while self.script and self.script[0][0] <= self.clock.now:
            self.script.pop(0)[1]()

    def status_bytes(self):
        return struct.pack('<IIQQQIIIIIIQQ', usbcon.STATUS_MAGIC, self.ring, len(self.stream), self.nonce, self.entry, 38400000, 1, 2, 3, self.restarts, 0, 50, 10000)

    def ctrl_transfer(self, rtype, request, value, index, data, timeout=0):
        self.tick()
        self.requests.append((rtype, request, value, index))
        self.clock.now += 0.004
        if not self.present:
            raise FakeUSBError('no device', 19)
        if self.timeout_next:
            self.timeout_next -= 1
            self.clock.now += timeout / 1000
            raise FakeUSBError('timed out', 60)
        if rtype == 0xc0 and request == usbcon.REQ_READ:
            pos = value | index << 16
            total = len(self.stream)
            if pos >= total or total - pos > self.ring:
                return b''
            return bytes(self.stream[pos:pos + min(384, data)])
        if rtype == 0xc0 and request == usbcon.REQ_STATUS:
            return self.status_bytes()
        if rtype == 0x40 and request == usbcon.REQ_RESET:
            assert (value, index) == (usbcon.RESET_VALUE, usbcon.RESET_INDEX)
            if self.mode != 2:
                raise FakeUSBError('pipe', 32)
            self.reset_accepted_at = self.clock.now
            self.script.insert(0, (self.clock.now + 0.01, self.vanish))
            return 0
        raise AssertionError(f'unexpected request {rtype:#x} {request:#x}')

    def vanish(self):
        self.present = False


class FakeBackend:
    error = FakeUSBError

    def __init__(self, phone):
        self.phone = phone
        self.opens = 0

    def find(self):
        self.phone.tick()
        return self.phone if self.phone.present else None

    def open(self):
        device = self.find()
        if device is not None:
            self.opens += 1
        return device

    def dispose(self, device):
        pass


def make(phone, clock, output=None, timeout=100, **over):
    args = types.SimpleNamespace(timeout=timeout, gone_exit=30, output=output, quiet=False, stats=10, reset_after=None)
    for key, value in over.items():
        setattr(args, key, value)
    out, err = io.StringIO(), io.StringIO()
    return usbcon.Console(args, FakeBackend(phone), clock=clock, sleep=clock.sleep, out=out, err=err), out, err


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clock = FakeClock()

    def tearDown(self):
        self.tmp.cleanup()

    def test_never_connected(self):
        phone = FakePhone(self.clock)
        phone.present = False
        console, _, err = make(phone, self.clock, timeout=5)
        self.assertEqual(console.run(), 3)
        self.assertIn('never connected', err.getvalue())

    def test_reads_everything_with_time_prefix_and_ends_when_gone(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'early line\r\nsecond ')
        phone.script = [(self.clock.now + 3, lambda: phone.emit(b'part\nthird\n')), (self.clock.now + 9, phone.vanish)]
        path = self.dir / 'x.log'
        console, out, err = make(phone, self.clock, output=str(path))
        self.assertEqual(console.run(), 0)
        self.assertEqual(path.read_bytes(), bytes(phone.stream))
        text = out.getvalue()
        lines = text.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].endswith('] early line'))
        self.assertTrue(lines[1].endswith('] second part'))     # one prefix per line, across reads
        self.assertNotIn('\r', text)
        summary = json.loads((self.dir / 'x.log.json').read_text())
        self.assertEqual(summary['bytes'], len(phone.stream))
        self.assertEqual(summary['end'], 'device gone')
        self.assertEqual(summary['disconnects'], 1)
        self.assertAlmostEqual(summary['thread_cpu_percent'], 0.5)
        offsets = [int(l.split('\t')[1]) for l in (self.dir / 'x.log.times').read_text().splitlines()]
        self.assertEqual(offsets[0], 0)

    def test_large_burst_no_idle_between_reads(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(bytes(range(256)) * 40)
        phone.script = [(self.clock.now + 2, phone.vanish)]
        path = self.dir / 'x.log'
        console, _, _ = make(phone, self.clock, output=str(path))
        console.run()
        self.assertEqual(path.read_bytes(), bytes(phone.stream))

    def test_offset_over_64k_splits_across_value_and_index(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'x' * 70000)
        phone.script = [(self.clock.now + 2, phone.vanish)]
        console, _, _ = make(phone, self.clock, quiet=True)
        console.run()
        self.assertEqual(console.offset, 70000)
        self.assertTrue(any(i == 1 for t, r, v, i in phone.requests if r == usbcon.REQ_READ))

    def test_overrun_reported_and_skipped(self):
        phone = FakePhone(self.clock, ring=8192)
        phone.emit(b'a' * 100000)
        phone.script = [(self.clock.now + 5, phone.vanish)]
        console, out, _ = make(phone, self.clock, quiet=True)
        console.run()
        self.assertGreater(console.summary['lost_bytes'], 0)
        self.assertIn('overwritten', out.getvalue())
        self.assertEqual(console.offset, 100000)

    def test_timeouts_retry_same_offset(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'one\n')
        phone.script = [(self.clock.now + 12, phone.vanish)]
        console, _, _ = make(phone, self.clock, quiet=True)
        phone.timeout_next = 0
        def later():
            phone.timeout_next = 2
            phone.emit(b'two\n')
        phone.script.insert(0, (self.clock.now + 1, later))
        console.run()
        self.assertEqual(console.summary['timeouts'], 2)
        self.assertEqual(console.offset, 8)

    def test_silence_named_once_and_cleared(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'one\n')
        def freeze():
            phone.timeout_next = 12
        def thaw():
            phone.emit(b'two\n')
        phone.script = [(self.clock.now + 1, freeze), (self.clock.now + 40, thaw), (self.clock.now + 45, phone.vanish)]
        console, _, err = make(phone, self.clock, quiet=True)
        console.run()
        text = err.getvalue()
        self.assertEqual(text.count('no answer for'), 1)
        self.assertIn('answering again', text)
        self.assertGreaterEqual(console.summary['max_silence_s'], 15)
        self.assertEqual(console.offset, 8)

    def test_restart_keeps_offset(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'before\n')
        def back():
            phone.present = True
            phone.restarts = 1
            phone.emit(b'after\n')
        phone.script = [(self.clock.now + 2, phone.vanish), (self.clock.now + 5, back), (self.clock.now + 8, phone.vanish)]
        path = self.dir / 'x.log'
        console, _, err = make(phone, self.clock, output=str(path))
        console.run()
        self.assertEqual(path.read_bytes(), b'before\nafter\n')
        self.assertEqual(console.summary['connects'], 2)
        self.assertIn('back after a restart', err.getvalue())

    def test_new_boot_stops_this_reader(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'boot one\n')
        def other():
            phone.present = True
            phone.entry = 0x2
            phone.stream = bytearray(b'boot two\n')
        phone.script = [(self.clock.now + 2, phone.vanish), (self.clock.now + 5, other)]
        path = self.dir / 'x.log'
        console, _, err = make(phone, self.clock, output=str(path))
        console.run()
        self.assertEqual(path.read_bytes(), b'boot one\n')
        self.assertIn('another boot', err.getvalue())

    def test_reset_after_once_only(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'x\n')
        console, _, err = make(phone, self.clock, reset_after=5, quiet=True)
        self.assertEqual(console.run(), 0)
        sent = [r for r in phone.requests if r[1] == usbcon.REQ_RESET]
        self.assertEqual(len(sent), 1)
        self.assertGreaterEqual(phone.reset_accepted_at, 105)
        self.assertIn('accepted', console.summary['reset'])

    def test_reset_refused_in_mode_1_says_so_and_keeps_reading(self):
        phone = FakePhone(self.clock, ring=1 << 20, mode=1)
        phone.emit(b'x\n')
        phone.script = [(self.clock.now + 9, lambda: phone.emit(b'y\n')), (self.clock.now + 12, phone.vanish)]
        console, _, err = make(phone, self.clock, reset_after=5, quiet=True)
        console.run()
        self.assertIn('blazer_usbcon=1', err.getvalue())
        self.assertEqual(console.offset, 4)
        self.assertEqual(len([r for r in phone.requests if r[1] == usbcon.REQ_RESET]), 1)

    def test_foreign_status_stops_cleanly(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.status_bytes = lambda: b'\0' * usbcon.STATUS.size
        console, _, err = make(phone, self.clock, quiet=True)
        console.run()
        self.assertIn('bad reply', console.summary['end'])

    def test_no_output_path_writes_nothing(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'x\n')
        phone.script = [(self.clock.now + 1, phone.vanish)]
        console, out, _ = make(phone, self.clock)
        console.run()
        self.assertIn('x', out.getvalue())
        self.assertEqual(list(self.dir.iterdir()), [])

    # verify

    def test_drop_quiets_the_terminal_not_the_file(self):
        phone = FakePhone(self.clock, ring=1 << 20)
        phone.emit(b'keep one\nnoise ha')
        phone.script = [(self.clock.now + 1, lambda: phone.emit(b'lf a line\nkeep two\n')), (self.clock.now + 3, phone.vanish)]
        path = self.dir / 'x.log'
        console, out, _ = make(phone, self.clock, output=str(path), drop=['^noise'])
        console.run()
        self.assertEqual(path.read_bytes(), bytes(phone.stream))
        text = out.getvalue()
        self.assertIn('keep one', text)
        self.assertIn('keep two', text)
        self.assertNotIn('noise', text)
        self.assertNotIn('half', text)      # a pattern can't be missed across two reads

    def fake_dump(self, stream, size=0x100000):
        total = len(stream)
        tail_len = min(total, size)
        tail_off = (total - tail_len) % size
        raw = bytearray(0x400000)
        struct.pack_into('<16sIIQQIIQII', raw, usbcon.DUMP_HEADER_OFF, b'XNU-MSGBUF v2', 1, 0, 0, 0, size, total % size, total, tail_off, tail_len)
        for i, byte in enumerate(stream[-tail_len:] if tail_len else b''):
            raw[usbcon.DUMP_RING_OFF + (tail_off + i) % size] = byte
        # The RAM console: STAGE0 mark, then the stream, until it fills.
        console = (b'TEGU-XNU STAGE0\n' + stream)[:1048563]
        struct.pack_into('<III', raw, 0, 0x43474244, len(console), len(console))
        raw[12:12 + len(console)] = console
        return bytes(raw)

    def live_files(self, stream, reads):
        path = self.dir / 'live.log'
        with open(path, 'wb') as f, open(str(path) + '.times', 'w') as t:
            for offset, length in reads:
                f.seek(offset)
                f.write(stream[offset:offset + length])
                t.write(f'1.0\t{offset}\t{length}\n')
        return path

    def test_verify_pass_with_lag(self):
        stream = bytes((i * 3) & 255 for i in range(10000))
        path = self.live_files(stream, [(0, 384), (384, 384), (768, 5000)])
        dump = self.dir / 'k.log'
        dump.write_bytes(self.fake_dump(stream))
        result = usbcon.verify(path, dump)
        self.assertTrue(result['ok'])
        self.assertEqual(result['compared'], 5768)
        self.assertEqual(result['not_read_before_reset'], 10000 - 5768)

    def test_verify_fail_names_first_byte(self):
        stream = bytes((i * 3) & 255 for i in range(5000))
        path = self.live_files(stream, [(0, 5000)])
        raw = bytearray(path.read_bytes())
        raw[1234] ^= 1
        path.write_bytes(raw)
        dump = self.dir / 'k.log'
        dump.write_bytes(self.fake_dump(stream))
        result = usbcon.verify(path, dump)
        self.assertFalse(result['ok'])
        self.assertEqual(result['first_mismatch'], 1234)
        self.assertEqual(result['mismatched'], 1)

    def test_verify_wrapped_ring(self):
        stream = bytes((i * 5) & 255 for i in range(0x100000 + 70000))
        path = self.live_files(stream, [(0, 2000), (0x100000 + 60000, 10000)])
        dump = self.dir / 'k.log'
        dump.write_bytes(self.fake_dump(stream))
        result = usbcon.verify(path, dump)
        self.assertTrue(result['ok'])
        self.assertEqual(result['compared'], 12000)         # the head against the console, the tail against the ring
        self.assertEqual(result['ring_from'], 70000)
        self.assertEqual(result['console_leads_by'], 16)
        self.assertEqual(result['only_the_live_console_has'], 0)

    def test_verify_counts_what_only_the_live_console_has(self):
        stream = bytes((i * 7) & 255 for i in range(3000000))
        path = self.live_files(stream, [(i, 4096) for i in range(0, len(stream) - 4096, 4096)])
        dump = self.dir / 'k.log'
        dump.write_bytes(self.fake_dump(stream))
        result = usbcon.verify(path, dump)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['capture_lost'], 3000000 - 1048576 - 1048547)
        self.assertGreater(result['only_the_live_console_has'], 800000)

    def test_verify_catches_a_bad_byte_in_the_console_part(self):
        stream = bytes((i * 7) & 255 for i in range(3000000))
        path = self.live_files(stream, [(i, 4096) for i in range(0, len(stream) - 4096, 4096)])
        data = bytearray(path.read_bytes())
        data[5000] ^= 1
        path.write_bytes(data)
        dump = self.dir / 'k.log'
        dump.write_bytes(self.fake_dump(stream))
        result = usbcon.verify(path, dump)
        self.assertFalse(result['ok'])
        self.assertEqual(result['first_mismatch'], 5000)

    def test_verify_no_overlap_is_not_a_pass(self):
        stream = bytes(range(256)) * 16384
        path = self.live_files(stream, [(1500000, 2000)])       # in neither store
        dump = self.dir / 'k.log'
        dump.write_bytes(self.fake_dump(stream))
        result = usbcon.verify(path, dump)
        self.assertFalse(result['ok'])
        self.assertEqual(result['only_the_live_console_has'], 2000)

    def test_verify_refuses_a_foreign_dump(self):
        dump = self.dir / 'k.log'
        dump.write_bytes(bytes(0x400000))
        with self.assertRaises(ValueError):
            usbcon.dump_ring(dump.read_bytes())

    def test_real_capture_parses_and_verifies(self):
        """A real phone capture, read-only: the ring parser agrees with the phone's own text, and a live file cut from it passes."""
        capture = REPO / 'research/laguna-usb-fix/attempts/20261101-232934-phone-preflight-r1/ramdump/kernel.log'
        if not capture.exists():
            self.skipTest('capture not on disk')
        raw = capture.read_bytes()
        first, linear, total = usbcon.dump_ring(raw)
        self.assertEqual(first, 0)
        self.assertEqual(len(linear), total)
        self.assertIn(b'blazer-root', linear)
        self.assertIn(b'cannot mount ufsroot0', linear)
        path = self.live_files(linear, [(i, 384) for i in range(0, min(total, 50000) - 384, 384)])
        self.assertTrue(usbcon.verify(path, capture)['ok'])
        data = bytearray(path.read_bytes())
        data[100] ^= 0x20
        path.write_bytes(data)
        self.assertFalse(usbcon.verify(path, capture)['ok'])


if __name__ == '__main__':
    unittest.main(verbosity=1)
