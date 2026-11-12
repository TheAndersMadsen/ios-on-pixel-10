#!/usr/bin/env python3
"""hkq: ask a running blazer kernel for a read-only state dump, and print it from the live console.

The kernel side is XNU osfmk/kern/hk_query.c (branch hk-hkq), on only with hk_query=1 or hk_dbg bit 27 (0x08000000).
Three EP0 vendor requests (type 0xc0, IN, 96-byte HKQ1 receipt, osfmk/kern/hk_query_wire.h):
    0x71 ARG     wValue = two argument bytes, wIndex = their offset (0 clears first); 0 byte ends it
    0x72 RUN     wValue = query, wIndex = parameter (0 = default); reply carries the query's id
    0x73 STATUS  last query's id/state/rc/counts and the current argument; changes nothing
The dump itself arrives on the console as "HKQ <id> ..." lines, ending "HKQ <id> END <rc> lines= bytes= dropped= ms=".

This client never opens USB. It speaks to the running reader (tools/usbcon.py --output X.log --control-socket S) through
the reader's 'vendor' control op (usbcon.VENDOR_SERVED: exactly the requests the kernel serves), and reads the reader's raw
console file X.log. It runs where the reader runs (the Mac), from the same tools directory as the reader:

    tools/hkq.py -s /tmp/hackios-live.sock -c X.log procs [ROWS]
    tools/hkq.py -s ... -c ... ioreg AppleBCM4390 [--depth 4]
    tools/hkq.py -s ... -c ... drivers
    tools/hkq.py -s ... -c ... log 200
    tools/hkq.py -s ... -c ... mem
    tools/hkq.py -s ... -c ... ports SpringBoard [THREADS]       (or a pid)
    tools/hkq.py -s ... -c ... sysctl kern.osversion
    tools/hkq.py -s ... -c ... kthreads [WINDOW_MS]              (kernel with hk-loop-1; name the output with tools/hkq_sym.py)
    tools/hkq.py -s ... status
    tools/hkq.py -s ... -c ... batch 'drivers; procs; ioreg AppleBCM4390 4; log 200; sysctl kern.osversion'
HKQ_SOCKET and HKQ_CONSOLE stand in for -s and -c. batch runs the queries in order (the kernel admits one per second) and
prints each between "### hkq QUERY" and "### end QUERY rc=.. lines=.. bytes=.. dropped=.. ms=.." (or "### error QUERY: why");
one failing query does not stop the rest. Exit: 0 every query rc 0; 1 a query's rc was not 0; 3 a query timed out; 4 refused.

The vendor op (tools/usbcon.py validate_request / vendor_step):
    request  {"command": "vendor", "dir": "in", "req": 0x72, "value": V, "index": I, "length": 96}      type 0xc0
    reply    {"state": "vendor", "length": 96, "data": "<hex of the IN data stage>", ...}
    a STALL  {"state": "refused", "error": "vendor 0x72 stalled: the kernel does not serve it (or its gate is off)", ...}
A reader started from older tools refuses the op ("only tap ... are supported"); hkq says so and stops. There is no other
path: only the reader may open USB (tools/usbcon.py UsbOwnerLock).
"""
import argparse
import json
import os
import re
import struct
import sys
import time

REQ_ARG, REQ_RUN, REQ_STATUS = 0x71, 0x72, 0x73
WIRE = struct.Struct('<IHHQQIIHHHHIIIIII32s')
WIRE_FIELDS = ('magic', 'version', 'bytes', 'nonce', 'entry_t', 'result', 'id', 'query', 'param', 'state', 'rc',
               'lines', 'bytes_out', 'dropped', 'queries', 'rate_ms', 'arg_len', 'arg')
MAGIC, VERSION = 0x31514b48, 1
ARG_MAX = 31
ARG_RE = re.compile(r'[A-Za-z0-9._,:@-]{1,31}')
RESULTS = ('ok', 'unavailable', 'badarg', 'busy', 'rate', 'noarg')
STATES = ('idle', 'queued', 'running', 'done')
# name: (query id, needs an argument, parameter meaning, largest parameter)
QUERIES = {
    'procs': (1, False, 'rows', 400),
    'ioreg': (2, True, 'depth', 8),
    'drivers': (3, False, None, 0),
    'log': (4, False, 'lines', 400),
    'mem': (5, False, None, 0),
    'ports': (6, True, 'threads', 128),
    'sysctl': (7, True, None, 0),
    'kthreads': (8, False, 'window_ms', 2000),      # XNU hk-loop-1+: kernel_task threads' CPU time over a window (default 500 ms)
}
SYSCTL_TOPS = ('kern.', 'hw.', 'vm.', 'net.', 'debug.', 'machdep.')
VENDOR_COMMAND = 'vendor'
NO_VENDOR = ('the running reader has no vendor op for this request: it was started from older tools than this hkq '
             '(tools/usbcon.py VENDOR_SERVED). Start the reader and hkq from the same tools (tools/mactools.py); '
             'nothing else may open USB.')
assert WIRE.size == 96


class Refused(Exception):
    pass


def parse_wire(data):
    if len(data) != WIRE.size:
        raise ValueError(f'HKQ1 reply is {len(data)} bytes, expected {WIRE.size}')
    w = dict(zip(WIRE_FIELDS, WIRE.unpack(data)))
    if (w['magic'], w['version'], w['bytes']) != (MAGIC, VERSION, WIRE.size):
        raise ValueError('not an HKQ1 reply (magic/version/size)')
    if w['result'] >= len(RESULTS) or w['state'] >= len(STATES) or w['arg_len'] > ARG_MAX:
        raise ValueError('HKQ1 reply fields out of range')
    w['arg'] = w['arg'].split(b'\0', 1)[0].decode('ascii', 'replace')
    w['result_name'] = RESULTS[w['result']]
    w['state_name'] = STATES[w['state']]
    return w


def check_arg(query, arg):
    if not ARG_RE.fullmatch(arg):
        raise ValueError('argument must be 1..31 of [A-Za-z0-9._,:@-]')
    if query == 'sysctl':
        if not arg.startswith(SYSCTL_TOPS):
            raise ValueError('sysctl name must start with ' + ' '.join(SYSCTL_TOPS))
        if not re.fullmatch(r'[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)+', arg):
            raise ValueError('sysctl name: [A-Za-z0-9_] components separated by single dots')
    return arg


def arg_packets(arg):
    """(value, index) per ARG request: two bytes at even offsets, ending with a 0 byte."""
    raw = arg.encode('ascii') + b'\0'
    if len(raw) % 2:
        raw += b'\0'
    return [(raw[i] | raw[i + 1] << 8, i) for i in range(0, len(raw), 2)]


def vendor_request(code, value=0, index=0):
    """The reader's vendor-op request for one HKQ1 transfer (usbcon.validate_request's grammar)."""
    return dict(command=VENDOR_COMMAND, dir='in', req=code, value=value, index=index, length=WIRE.size)


def vendor_data(reply):
    """The IN data from the reader's vendor-op reply: {"state": "vendor", "length": N, "data": hex}."""
    v = reply.get('data')
    if reply.get('state') != 'vendor' or not isinstance(v, str):
        raise ValueError('vendor reply has no data')
    data = bytes.fromhex(v)
    if 'length' in reply and reply['length'] != len(data):
        raise ValueError('vendor reply length does not match its data')
    return data


def stalled(reply):
    """vendor_step's refusal for a STALL (errno 32): the kernel does not serve the request, or its gate is off."""
    return reply.get('state') == 'refused' and 'stalled' in str(reply.get('error', ''))


class Client:
    """One HKQ1 conversation through a transport: transport(request_dict) -> reply_dict."""

    def __init__(self, transport, sleep=time.sleep, clock=time.monotonic):
        self.transport, self.sleep, self.clock = transport, sleep, clock
        self.boot = None

    def request(self, code, value=0, index=0):
        reply = self.transport(vendor_request(code, value, index))
        if not isinstance(reply, dict):
            raise Refused('invalid reader reply')
        error = str(reply.get('error', ''))
        if reply.get('state') != 'vendor' or error:
            if 'only tap' in error or 'vendor request must be' in error or 'vendor dir must be' in error or 'length must be' in error:
                raise Refused(NO_VENDOR)
            if stalled(reply):
                raise Refused('the kernel stalled the request: no hk_query (needs hk_query=1 or hk_dbg bit 27, and a kernel with hk-hkq)')
            raise Refused(f'reader: {error or reply.get("state")}')
        try:
            w = parse_wire(vendor_data(reply))
        except ValueError as exc:
            raise Refused(f'reader reply unusable: {exc}') from exc
        boot = (w['nonce'], w['entry_t'])
        if self.boot is None:
            self.boot = boot
        elif boot != self.boot:
            raise Refused('the phone rebooted between requests (boot identity changed)')
        return w

    def status(self):
        return self.request(REQ_STATUS)

    def set_arg(self, arg):
        w = None
        for value, index in arg_packets(arg):
            w = self.request(REQ_ARG, value, index)
            if w['result'] != 0:
                raise Refused(f'ARG refused at offset {index}: {w["result_name"]}')
        if w['arg'] != arg or w['arg_len'] != len(arg):
            raise Refused(f'ARG mismatch: kernel holds {w["arg"]!r}')
        return w

    def run(self, query, param, wait_s=30):
        """RUN, waiting out RATE and BUSY. Returns the accepted receipt (its id is the query's)."""
        deadline = self.clock() + wait_s
        while True:
            w = self.request(REQ_RUN, query, param)
            if w['result'] == 0:
                return w
            if w['result_name'] not in ('rate', 'busy') or self.clock() >= deadline:
                raise Refused(f'RUN refused: {w["result_name"]}')
            self.sleep(max(0.05, w['rate_ms'] / 1000.0) if w['result_name'] == 'rate' else 0.5)


class ConsoleTail:
    """Lines appended to the reader's raw console file from a byte offset on. NULs (overrun holes) and CR dropped."""

    def __init__(self, path, start=None):
        self.path = path
        self.offset = os.path.getsize(path) if start is None else start
        self.partial = b''

    def lines(self):
        with open(self.path, 'rb') as f:
            f.seek(self.offset)
            data = f.read()
        self.offset += len(data)
        data = self.partial + data.replace(b'\0', b'').replace(b'\r', b'')
        *done, self.partial = data.split(b'\n')
        return [line.decode('utf-8', 'replace') for line in done]


END_RE = re.compile(r'^END (-?\d+) lines=(\d+) bytes=(\d+) dropped=(\d+) ms=(\d+)')


def pick(lines, qid):
    """This query's lines (prefix removed) and the END match if it is among them."""
    head = re.compile(r'^(?:\[[ 0-9.]*\] )?HKQ %d ' % qid)   # whole lines only; a terminal "[  t] " stamp is allowed
    out, end = [], None
    for line in lines:
        m = head.match(line)
        if m is None:
            continue
        body = line[m.end():]
        m = END_RE.match(body)
        if m:
            end = dict(rc=int(m[1]), lines=int(m[2]), bytes=int(m[3]), dropped=int(m[4]), ms=int(m[5]))
            break
        out.append(body)
    return out, end


def wait_dump(tail, qid, timeout, out, raw=False, sleep=time.sleep, clock=time.monotonic, client=None):
    deadline = clock() + timeout
    n = 0
    while True:
        body, end = pick(tail.lines(), qid)
        for line in body:
            out.write((f'HKQ {qid} ' if raw else '') + line + '\n')
            n += 1
        out.flush()
        if end is not None:
            return end, n
        if clock() >= deadline:
            state = None
            if client is not None:
                try:
                    s = client.status()
                    state = f'{s["state_name"]} id {s["id"]} lines {s["lines"]}'
                except (Refused, ValueError, OSError) as exc:
                    state = str(exc)
            return dict(rc=None, timeout=True, kernel=state), n
        sleep(0.1)


def run_query(client, console, name, arg, param, timeout, out, raw=False, sleep=time.sleep, clock=time.monotonic):
    query, needs_arg, _meaning, largest = QUERIES[name]
    if needs_arg:
        if arg is None:
            raise ValueError(f'{name} needs an argument')
        check_arg(name, arg)
    if not 0 <= param <= largest:
        raise ValueError(f'{name}: parameter must be 0..{largest}')
    client.status()                         # boot identity, and a clear refusal if hk_query is off
    if needs_arg:
        client.set_arg(arg)
    tail = ConsoleTail(console)             # from before RUN, so no line of this query is missed
    w = client.run(query, param)
    if needs_arg and w['arg'] != arg:
        raise Refused(f'argument changed under the RUN: {w["arg"]!r}')
    return wait_dump(tail, w['id'], timeout, out, raw, sleep, clock, client)


def parse_spec(words):
    """One query as words -> (name, arg, param), with hkq's CLI rules. Raises ValueError."""
    if not words or words[0] not in QUERIES:
        raise ValueError(f'unknown query {" ".join(words) or "(empty)"!r}: one of {", ".join(sorted(QUERIES))}')
    name, rest = words[0], list(words[1:])
    needs_arg, largest = QUERIES[name][1], QUERIES[name][3]
    arg, param = None, 0
    if needs_arg:
        if not rest:
            raise ValueError(f'{name} needs an argument')
        arg = check_arg(name, rest.pop(0))
    if rest:
        if not largest or not rest[0].isdigit() or len(rest) > 1:
            raise ValueError(f'{name}: ' + ('takes no parameter' if not largest else f'one number 0..{largest} may follow'))
        param = int(rest[0])
    if not 0 <= param <= largest:
        raise ValueError(f'{name}: parameter must be 0..{largest}')
    return name, arg, param


def parse_batch(text):
    """'drivers; procs 100; ioreg X 4' -> [(name, arg, param)]. Raises ValueError naming the bad query."""
    specs = [parse_spec(part.split()) for part in text.replace('\n', ';').split(';') if part.strip()]
    if not specs:
        raise ValueError('empty batch')
    if len(specs) > 32:
        raise ValueError('batch: at most 32 queries')
    return specs


def run_batch(client, console, specs, timeout, out, sleep=time.sleep, clock=time.monotonic):
    """Every query in order; a failing one does not stop the rest. Returns (exit code, [result per query])."""
    worst, results = 0, []
    for name, arg, param in specs:
        label = ' '.join(str(x) for x in (name, arg, param or None) if x is not None)
        out.write(f'### hkq {label}\n')
        try:
            end, n = run_query(client, console, name, arg, param, timeout, out, False, sleep, clock)
        except (Refused, OSError, ValueError) as exc:
            out.write(f'### error {label}: {exc}\n')
            results.append(dict(query=label, error=str(exc)))
            worst = max(worst, 4)
            if client.boot is None or 'rebooted' in str(exc) or 'stalled' in str(exc) or 'older tools' in str(exc):
                break                   # nothing will answer: do not hammer a reader that refuses
            continue
        if end.get('timeout'):
            out.write(f'### error {label}: no END line within {timeout:g} s ({n} lines seen); kernel says: {end.get("kernel")}\n')
            results.append(dict(query=label, error='timeout', lines_seen=n, kernel=end.get('kernel')))
            worst = max(worst, 3)
            continue
        out.write(f'### end {label} rc={end["rc"]} lines={end["lines"]} bytes={end["bytes"]} dropped={end["dropped"]} ms={end["ms"]}\n')
        results.append(dict(query=label, **end))
        worst = max(worst, 0 if end['rc'] == 0 else 1)
    out.flush()
    return worst, results


def socket_transport(path):
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    from usbcon import send_control    # local socket only; never touches USB
    return lambda request: send_control(path, request, timeout=15)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('-s', '--control-socket', default=os.environ.get('HKQ_SOCKET'), help='the running usbcon reader\'s socket')
    p.add_argument('-c', '--console', default=os.environ.get('HKQ_CONSOLE'), help='the reader\'s --output raw console file')
    p.add_argument('--timeout', type=float, default=30, help='seconds to wait for END (default 30)')
    p.add_argument('--depth', type=int, help='ioreg depth (1..8, default 3)')
    p.add_argument('--raw', action='store_true', help='keep the "HKQ <id> " prefix')
    p.add_argument('query', choices=sorted(QUERIES) + ['status', 'batch'])
    p.add_argument('arg', nargs='?', help="ioreg CLASS|NAME, ports PROC|PID, sysctl NAME; procs ROWS, log LINES; batch 'Q; Q ARG; ...'")
    p.add_argument('param', nargs='?', type=int, help='ports: thread rows')
    a = p.parse_args(argv)
    if not a.control_socket:
        p.error('need --control-socket (or HKQ_SOCKET) of the running tools/usbcon.py reader')
    name, arg, param = a.query, a.arg, a.param or 0
    if name == 'batch':
        if not a.console:
            p.error('need --console (or HKQ_CONSOLE): the reader\'s --output file')
        try:
            specs = parse_batch(arg or '')
        except ValueError as exc:
            p.error(str(exc))
        code, _results = run_batch(Client(socket_transport(a.control_socket)), a.console, specs, a.timeout, sys.stdout)
        return code
    if name in ('procs', 'log', 'kthreads') and arg is not None:
        if not arg.isdigit():
            p.error(f'{name} takes a number')
        param, arg = int(arg), None
    elif name == 'ioreg' and a.depth is not None:
        param = a.depth
    elif name in ('drivers', 'mem') and arg is not None:
        p.error(f'{name} takes no argument')
    client = Client(socket_transport(a.control_socket))
    try:
        if name == 'status':
            print(json.dumps(client.status(), indent=1))
            return 0
        if not a.console:
            p.error('need --console (or HKQ_CONSOLE): the reader\'s --output file')
        end, n = run_query(client, a.console, name, arg, param, a.timeout, sys.stdout, a.raw)
    except ValueError as exc:
        p.error(str(exc))
    except (Refused, OSError) as exc:
        print(f'hkq: {exc}', file=sys.stderr)
        return 4
    if end.get('timeout'):
        print(f'hkq: no END line within {a.timeout:.0f} s ({n} lines seen); kernel says: {end.get("kernel")}', file=sys.stderr)
        return 3
    print(f'hkq: rc {end["rc"]}, {end["lines"]} lines, {end["bytes"]} bytes, {end["dropped"]} dropped, {end["ms"]} ms',
          file=sys.stderr)
    return 0 if end['rc'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
