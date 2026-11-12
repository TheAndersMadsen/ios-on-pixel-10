#!/usr/bin/env python3
"""Host test of tools/hkq.py against a fake kernel (a model of osfmk/kern/hk_query.c's control path), a fake reader
socket and a console file. No USB. Run: python3 -I tools/test_hkq.py"""
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import types
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('hkq', HERE / 'hkq.py')
hkq = importlib.util.module_from_spec(spec)
sys.modules['hkq'] = hkq
spec.loader.exec_module(hkq)
sys.path.insert(0, str(HERE))
import usbcon     # noqa: E402  the real reader: its grammar (validate_request) and its vendor step answer every test request

ARGCH = set(b'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._,:@-')


class FakeKernel:
    """hk_query's EP0 side: ARG/RUN/STATUS -> HKQ1 receipt, and the worker's console lines into a file."""

    def __init__(self, console, on=True, rate_first=0, lines=None, rc=0, nonce=0x1234, emit=True):
        self.console, self.on, self.rate_first, self.rc, self.emit = console, on, rate_first, rc, emit
        self.arg, self.ended = b'', False
        self.id = self.query = self.param = self.state = self.queries = 0
        self.nonce, self.entry = nonce, 0x99
        self.lines = lines if lines is not None else ['first', 'second  with  spaces', 'third']
        self.log = []
        self.base_rc, self.rc_for = rc, {}       # rc_for: query number -> rc of that query

    def wire(self, result):
        return hkq.WIRE.pack(hkq.MAGIC, 1, 96, self.nonce, self.entry, result, self.id, self.query, self.param,
                             self.state, self.rc if self.state == 3 else 0, len(self.lines), 0, 0, self.queries, 1000,
                             len(self.arg), self.arg.ljust(32, b'\0'))

    def control(self, req, value, index):
        self.log.append((req, value, index))
        if req == hkq.REQ_ARG:
            c = [value & 255, value >> 8]
            if index % 2 or index > 30 or (index and (index != len(self.arg) or self.ended)) or (c[0] == 0 and c[1]):
                self.arg, self.ended = b'', False
                return self.wire(2)
            if index == 0:
                self.arg, self.ended = b'', False
            for ch in c:
                if ch == 0:
                    break
                if ch not in ARGCH or len(self.arg) >= 31:
                    self.arg = b''
                    return self.wire(2)
                self.arg += bytes([ch])
            self.ended = 0 in c
            return self.wire(0)
        if req == hkq.REQ_RUN:
            if self.rate_first:
                self.rate_first -= 1
                return self.wire(4)
            self.id += 1
            self.query, self.param, self.state = value, index, 3
            self.rc = self.rc_for.get(value, self.base_rc)
            self.queries += 1
            if self.emit:
                self.write_dump()
            return self.wire(0)
        return self.wire(0 if value == 0 and index == 0 else 2)

    def write_dump(self):
        i = self.id
        text = f'unrelated line\nHKQ {i + 7} not ours\nHKQ {i} {hkq.QUERIES and "q"}{self.query} param={self.param}\n'
        for line in self.lines:
            text += f'HKQ {i} {line}\nkernel: noise between\n'
        text += f'xHKQ {i} injected mid-line\nHKQ {i} END {self.rc} lines={len(self.lines) + 1} bytes=99 dropped=0 ms=3\nHKQ {i} after end\n'
        data = text.encode()
        with open(self.console, 'ab') as f:   # two writes, split mid-line, like the reader's chunks
            f.write(data[:37])
            f.write(b'\0\0' + data[37:])


class FakeUSBError(Exception):
    def __init__(self, text, errno=None):
        super().__init__(text)
        self.errno = errno


class FakeDevice:
    """The reader's USB device: XNU blazer_usbcon_core.inc uc_setup for 0x71..0x73 (type 0xc0, wLength 96, gate on), else STALL."""

    def __init__(self, kernel):
        self.kernel = kernel

    def ctrl_transfer(self, rtype, request, value, index, length, timeout=0):
        if rtype != 0xc0 or not 0x71 <= request <= 0x73 or length != 96 or not self.kernel.on:
            raise FakeUSBError('[Errno 32] Pipe error', 32)
        return self.kernel.control(request, value, index)


def transport_for(kernel, mode='ok'):
    """hkq's request through the REAL reader code: usbcon.validate_request, then usbcon.Console.vendor_step on a fake device.
    The client can therefore not drift from the reader's op again (it once did: 'request' vs 'req', no 'dir')."""
    sink = types.SimpleNamespace(replies=[])
    sink.reply = sink.replies.append
    con = usbcon.Console(types.SimpleNamespace(output=None), types.SimpleNamespace(error=FakeUSBError), err=io.StringIO(),
                         controller=sink)
    device = FakeDevice(kernel)

    def transport(request):
        if mode == 'novendor':      # a reader started from tools older than the vendor op
            return dict(state='refused', error='only tap x y, swipe x y x2 y2 ms, key NAME, home, status and snapshot are supported')
        try:
            usbcon.validate_request(request)
        except ValueError as exc:   # ControlServer's answer to a request outside the grammar
            return dict(state='refused', error=str(exc), ambiguous=False)
        con.control = dict(request=request, send_until=con.clock() + 5)
        con.vendor_step(device, con.control)
        return json.loads(json.dumps(sink.replies[-1]))
    return transport


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.console = os.path.join(self.tmp.name, 'X.log')
        Path(self.console).write_bytes(b'boot noise\nHKQ 1 END 0 lines=0 bytes=0 dropped=0 ms=0 (an old boot)\n')
        self.slept = []

    def tearDown(self):
        self.tmp.cleanup()

    def query(self, kernel, name, arg=None, param=0, mode='ok', timeout=5):
        client = hkq.Client(transport_for(kernel, mode), sleep=self.slept.append)
        out = io.StringIO()
        end, n = hkq.run_query(client, self.console, name, arg, param, timeout, out, sleep=lambda s: None)
        return end, n, out.getvalue()


class TestPure(unittest.TestCase):
    def test_wire_size(self):
        self.assertEqual(hkq.WIRE.size, 96)

    def test_arg_packets(self):
        self.assertEqual(hkq.arg_packets('ab'), [(0x6261, 0), (0, 2)])
        self.assertEqual(hkq.arg_packets('abc'), [(0x6261, 0), (0x63, 2)])
        self.assertEqual(len(hkq.arg_packets('x' * 31)), 16)
        for n in range(1, 32):
            packets = hkq.arg_packets('q' * n)
            self.assertEqual([i for _, i in packets], list(range(0, 2 * len(packets), 2)))
            self.assertTrue(packets[-1][0] >> 8 == 0)

    def test_check_arg(self):
        for good in ('IOService', 'AppleARMPE@0', 'kern.osversion', 'SpringBoard', '312'):
            hkq.check_arg('ioreg', good)
        for bad in ('', 'a b', 'x' * 32, 'a/b', 'é'):
            with self.assertRaises(ValueError):
                hkq.check_arg('ioreg', bad)
        hkq.check_arg('sysctl', 'hw.ncpu')
        for bad in ('security.mac', 'kern', 'kern..x', 'kern.x-y', 'kern.x.'):
            with self.assertRaises(ValueError):
                hkq.check_arg('sysctl', bad)

    def test_parse_wire(self):
        k = FakeKernel('/dev/null')
        w = hkq.parse_wire(k.wire(0))
        self.assertEqual((w['result_name'], w['state_name']), ('ok', 'idle'))
        with self.assertRaises(ValueError):
            hkq.parse_wire(k.wire(0)[:95])
        bad = bytearray(k.wire(0))
        bad[0] ^= 1
        with self.assertRaises(ValueError):
            hkq.parse_wire(bytes(bad))
        with self.assertRaises(ValueError):
            hkq.parse_wire(k.wire(9))

    def test_vendor_request_is_the_readers_grammar(self):
        for code in (hkq.REQ_ARG, hkq.REQ_RUN, hkq.REQ_STATUS):
            r = hkq.vendor_request(code, 0x4241, 30)
            usbcon.validate_request(r)
            self.assertEqual(r, dict(command='vendor', dir='in', req=code, value=0x4241, index=30, length=96))
            self.assertEqual(usbcon.VENDOR_SERVED[code], hkq.WIRE.size)
        self.assertEqual(sorted(usbcon.VENDOR_SERVED), [0x70, 0x71, 0x72, 0x73])     # 0x70 is hk_ustack's, not hkq's

    def test_vendor_data(self):
        self.assertEqual(hkq.vendor_data(dict(state='vendor', length=2, data='0a0b')), b'\n\x0b')
        for bad in (dict(state='vendor'), dict(state='vendor', length=3, data='0a0b'), dict(state='refused', data='0a0b'),
                    dict(state='vendor', data=[1, 2])):
            with self.assertRaises(ValueError, msg=bad):
                hkq.vendor_data(bad)
        self.assertTrue(hkq.stalled(dict(state='refused', error='vendor 0x73 stalled: the kernel does not serve it (or its gate is off)')))
        self.assertFalse(hkq.stalled(dict(state='unknown', error='vendor 0x73: timeout; do not repeat blindly')))

    def test_kthreads_spec_and_symbolizer(self):
        self.assertEqual(hkq.parse_batch('kthreads; kthreads 1000'), [('kthreads', None, 0), ('kthreads', None, 1000)])
        with self.assertRaises(ValueError):
            hkq.parse_batch('kthreads 2001')
        spec2 = importlib.util.spec_from_file_location('hkq_sym', HERE / 'hkq_sym.py')
        sym = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(sym)
        text = ('HKQ 4 kthreads window_us=500000 threads=3 sampled=3 (K ...)\n'
                'HKQ 4 K tid=9 cpu_us=0 cpu_ms=1 st=W pri=80 hint=none cont=0xfffffe0007000010 name=sleeper\n'
                'HKQ 4 K tid=301 cpu_us=48000 cpu_ms=9120 st=W pri=81 hint=none cont=0xfffffe0007000104 name=SweetFramebuffer present\n'
                'K tid=5 cpu_us=0 cpu_ms=3 st=R pri=0 hint=none cont=0x0 name=-\n')
        dumps = sym.parse(text)
        self.assertEqual((dumps[0][0], len(dumps[0][1])), (500000, 3))
        out = sym.render(dumps, [(0xfffffe0007000000, '_a'), (0xfffffe0007000100, '_present_continue')])
        rows = [l for l in out.splitlines() if 'SweetFramebuffer' in l or ' 5  ' in l or 'sleeper' in l]
        self.assertIn('present_continue+0x4', rows[0])            # busiest first, named
        self.assertIn('  9.6 ', rows[0])                          # 48 ms of a 500 ms window
        self.assertEqual(len(rows), 2)                            # the thread that neither ran nor is runnable is left out
        self.assertEqual(sym.name_of(0xfffffe0007000104, []), '0xfffffe0007000104')

    def test_parse_batch(self):
        self.assertEqual(hkq.parse_batch('drivers; procs 100;ioreg AppleBCM4390 4 ; log 200; ports 42; sysctl kern.osversion;'),
                         [('drivers', None, 0), ('procs', None, 100), ('ioreg', 'AppleBCM4390', 4), ('log', None, 200),
                          ('ports', '42', 0), ('sysctl', 'kern.osversion', 0)])
        for bad in ('', ' ; ', 'shell ls', 'ioreg', 'drivers 3', 'procs many', 'procs 401', 'sysctl kern.panic x y', 'ioreg a b',
                    'sysctl debug..x', ';'.join(['mem'] * 33)):
            with self.assertRaises(ValueError, msg=bad):
                hkq.parse_batch(bad)

    def test_pick(self):
        lines = ['HKQ 3 a', '[   1.20] HKQ 3 b', 'xHKQ 3 c', 'HKQ 33 d', 'HKQ 3 END 0 lines=2 bytes=9 dropped=0 ms=1', 'HKQ 3 e']
        body, end = hkq.pick(lines, 3)
        self.assertEqual(body, ['a', 'b'])
        self.assertEqual(end['rc'], 0)


class TestFlow(Base):
    def test_procs(self):
        k = FakeKernel(self.console)
        end, n, out = self.query(k, 'procs')
        self.assertEqual(end['rc'], 0)
        self.assertEqual(out.splitlines(), ['q1 param=0', 'first', 'second  with  spaces', 'third'])
        self.assertEqual([r for r, _, _ in k.log], [hkq.REQ_STATUS, hkq.REQ_RUN])

    def test_ioreg_arg_on_wire(self):
        k = FakeKernel(self.console)
        end, n, out = self.query(k, 'ioreg', 'AppleBCM4390', 4)
        self.assertEqual(k.arg, b'AppleBCM4390')
        args = [(v, i) for r, v, i in k.log if r == hkq.REQ_ARG]
        self.assertEqual(args, hkq.arg_packets('AppleBCM4390'))
        self.assertEqual(k.log[-1], (hkq.REQ_RUN, 2, 4))
        self.assertIn('q2 param=4', out)

    def test_sysctl_odd_length(self):
        k = FakeKernel(self.console)
        self.query(k, 'sysctl', 'hw.ncpu')
        self.assertEqual(k.arg, b'hw.ncpu')

    def test_rate_retry(self):
        k = FakeKernel(self.console, rate_first=2)
        end, _, _ = self.query(k, 'drivers')
        self.assertEqual(end['rc'], 0)
        self.assertEqual(self.slept, [1.0, 1.0])

    def test_rc_nonzero(self):
        k = FakeKernel(self.console, rc=3)
        end, _, _ = self.query(k, 'ports', 'nosuchproc')
        self.assertEqual(end['rc'], 3)

    def test_kernel_off_stall(self):
        k = FakeKernel(self.console, on=False)
        with self.assertRaisesRegex(hkq.Refused, 'hk_query=1'):
            self.query(k, 'mem')

    def test_batch_runs_every_query_and_survives_a_bad_one(self):
        k = FakeKernel(self.console)
        client = hkq.Client(transport_for(k), sleep=self.slept.append)
        out = io.StringIO()
        specs = hkq.parse_batch('mem; sysctl kern.nosuch; procs 5')
        k.rc_for = {7: 2}                      # the sysctl query ends rc 2 (ENOENT)
        code, results = hkq.run_batch(client, self.console, specs, 5, out, sleep=lambda s: None)
        text = out.getvalue()
        self.assertEqual(code, 1, text)
        self.assertEqual([r.get('rc') for r in results], [0, 2, 0], results)
        self.assertEqual([l for l in text.splitlines() if l.startswith('### ')][::2], ['### hkq mem', '### hkq sysctl kern.nosuch', '### hkq procs 5'])
        self.assertRegex(text, r'### end sysctl kern\.nosuch rc=2 lines=\d+ bytes=\d+ dropped=\d+ ms=\d+')

    def test_batch_stops_when_the_kernel_stalls(self):
        k = FakeKernel(self.console)
        k.on = False
        out = io.StringIO()
        code, results = hkq.run_batch(hkq.Client(transport_for(k)), self.console, hkq.parse_batch('mem; procs; drivers'), 5, out,
                                      sleep=lambda s: None)
        self.assertEqual(code, 4)
        self.assertEqual(len(results), 1, results)          # one refusal is the answer for all
        self.assertIn('### error mem: the kernel stalled the request', out.getvalue())

    def test_no_vendor_op(self):
        k = FakeKernel(self.console)
        with self.assertRaisesRegex(hkq.Refused, 'older tools'):
            self.query(k, 'mem', mode='novendor')

    def test_reboot_between(self):
        k = FakeKernel(self.console)
        client = hkq.Client(transport_for(k))
        client.status()
        k.nonce += 1
        with self.assertRaisesRegex(hkq.Refused, 'rebooted'):
            client.status()

    def test_timeout_reports_kernel_state(self):
        k = FakeKernel(self.console, emit=False)
        clock = iter(range(0, 1000)).__next__
        client = hkq.Client(transport_for(k))
        out = io.StringIO()
        end, n = hkq.run_query(client, self.console, 'log', None, 50, 5, out, sleep=lambda s: None, clock=clock)
        self.assertTrue(end['timeout'])
        self.assertIn('done id 1', end['kernel'])

    def test_bad_param(self):
        k = FakeKernel(self.console)
        with self.assertRaises(ValueError):
            self.query(k, 'log', None, 401)
        with self.assertRaises(ValueError):
            self.query(k, 'ioreg', None)


class FakeReader:
    """The reader's control socket (tools/usbcon.py ControlServer's envelope), serving vendor requests from a FakeKernel."""

    def __init__(self, path, kernel):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(4)
        self.kernel, self.requests = kernel, []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = b''
                while not data.endswith(b'\n'):
                    data += conn.recv(4096)
                env = json.loads(data)
                assert set(env) == {'request', 'expires_ns'}
                self.requests.append(env['request'])
                reply = transport_for(self.kernel)(env['request'])
                conn.sendall(json.dumps(reply).encode() + b'\n')

    def close(self):
        self.server.close()


class TestCli(Base):
    def test_main_end_to_end(self):
        sock = os.path.join(self.tmp.name, 's.sock')
        k = FakeKernel(self.console)
        reader = FakeReader(sock, k)
        try:
            old = sys.stdout
            sys.stdout = io.StringIO()
            try:
                rc = hkq.main(['-s', sock, '-c', self.console, 'ports', 'SpringBoard', '32'])
                out = sys.stdout.getvalue()
            finally:
                sys.stdout = old
        finally:
            reader.close()
        self.assertEqual(rc, 0)
        self.assertIn('first', out)
        self.assertEqual(k.arg, b'SpringBoard')
        self.assertEqual(k.log[-1], (hkq.REQ_RUN, 6, 32))
        self.assertTrue(all(r['command'] == 'vendor' for r in reader.requests))

    def test_main_status(self):
        sock = os.path.join(self.tmp.name, 's.sock')
        reader = FakeReader(sock, FakeKernel(self.console))
        try:
            old = sys.stdout
            sys.stdout = io.StringIO()
            try:
                rc = hkq.main(['-s', sock, 'status'])
                out = json.loads(sys.stdout.getvalue())
            finally:
                sys.stdout = old
        finally:
            reader.close()
        self.assertEqual((rc, out['magic']), (0, hkq.MAGIC))


if __name__ == '__main__':
    unittest.main()
