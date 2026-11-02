#!/usr/bin/env python3
"""Live XNU console over USB, from a kernel booted with blazer_usbcon=1 or 2.

Reads the XNU-MSGBUF mirror over EP0 from 1209:0002 "hackios XNU console" while iOS boots, and writes it to the
terminal with time since connect. Read-only unless --reset-after or an explicit local TAP/HOME request is given. Never touches 1209:0001, so
it runs beside tools/usb_log.py, which owns the shim's gadget. Run it with the runner's Python, TEGU_PYTHON, which
has pyusb.

    $TEGU_PYTHON -u tools/usbcon.py --output research/laguna-usb-fix/attempts/usbcon-NAME.log
    $TEGU_PYTHON -u tools/usbcon.py --output X.log --reset-after 300     # needs blazer_usbcon=2
    python3 -I tools/usbcon.py --verify X.log --dump ATTEMPT/ramdump/kernel.log

Optional attended live input (needs blazer_usbcon_input=1, no hk_ui/sweethidtest):
    $TEGU_PYTHON -u tools/usbcon.py --output X.log --control-socket /tmp/hackios-live.sock
    python3 -I tools/usbcon.py --control-socket /tmp/hackios-live.sock --tap 147 274
    python3 -I tools/usbcon.py --control-socket /tmp/hackios-live.sock --home
    python3 -I tools/usbcon.py --control-socket /tmp/hackios-live.sock --input-status
Only the reader opens USB. A dispatched receipt means both HID dispatch calls returned;
it does not certify queue acceptance, visible UI response, or touch-to-glass latency.
Ambiguous transfers are never automatically retried.

--output writes X.log, bytes at their stream offsets; X.log.times, one "seconds offset length" per read; X.log.json,
the summary. --drop REGEX only quiets the terminal: X.log keeps everything. --verify compares those bytes with both
stores in the capture after the reset: the RAM console, which holds the stream's first MiB, and the ring, its last.
"""
import argparse
import fcntl
import os
import socket
import stat
import json
from pathlib import Path
import re
import struct
import sys
import time

VID, PID = 0x1209, 0x0002
PRODUCT = 'hackios XNU console'
REQ_READ, REQ_STATUS, REQ_RESET = 0x5a, 0x5f, 0x5c
RESET_VALUE, RESET_INDEX = 0x5447, 1
READ_LEN = 512
TRANSFER_TIMEOUT_MS = 2000      # past any scheduling gap we expect; the kernel gives up on a transfer at 5 s
IDLE_S = 0.1                    # nothing new: read again after this. Sets the console's lag and part of the phone's cost
STATUS_EVERY_S = 1.0
HANG_SAY_S = 15.0               # the kernel restarts a stuck transfer by 5 s and is back in under 10
LOST_MARGIN = 65536             # after an overrun, restart this far inside the ring (at most a quarter of it), so the writer doesn't lap us again
# osfmk/arm64/blazer_usbcon_core.inc, struct uc_status.
STATUS = struct.Struct('<IIQQQIIIIIIQQ')
STATUS_MAGIC = 0x314e4355
STATUS_FIELDS = ('magic', 'ring', 'total', 'nonce', 'entry_t', 'hz', 'polls', 'events', 'reads', 'restarts', 'stalls', 'runtime', 'up')
# Capture layout, dump base 0x95200000: tools/read-ramdump.py, osfmk/arm64/tegu_early.c.
DUMP_HEADER_OFF = 0x9543f800 - 0x95200000
DUMP_RING_OFF = 0x95440000 - 0x95200000
DUMP_HEADER = struct.Struct('<16sIIQQIIQII')
DUMP_MAGIC = b'XNU-MSGBUF v2'
DUMP_CONSOLE_SIG = 0x43474244   # osfmk/arm64/tegu_early.c: sig, start, used, then bytes
DUMP_CONSOLE_HEADER = struct.Struct('<III')


# Optional HLI1 control ABI; the 0x5a/0x5f/0x5c protocol above stays byte-for-byte.
INPUT = struct.Struct('<IHHQQ12I')
INPUT_MAGIC = 0x31494c48
INPUT_FIELDS = ('magic', 'version', 'size', 'nonce', 'entry_t', 'generation', 'ticket',
                'phase', 'result', 'op', 'x', 'y', 'width', 'height', 'capabilities', 'interval_ms', 'hold_ms')
REQ_INPUT, REQ_ARM, REQ_TAP, REQ_HOME = 0x60, 0x61, 0x62, 0x63
INPUT_RESULTS = ('ok', 'unsupported', 'notready', 'busy', 'stale', 'badarg', 'rate',
                 'expired', 'nomem', 'cancelled', 'failed')
INPUT_PHASES = ('idle', 'armed', 'staged', 'queued', 'down', 'dispatched', 'refused')


def parse_input(data):
    if len(data) != INPUT.size:
        raise ValueError(f'input reply size {len(data)}, expected {INPUT.size}')
    s = dict(zip(INPUT_FIELDS, INPUT.unpack(data)))
    if (s['magic'], s['version'], s['size']) != (INPUT_MAGIC, 1, INPUT.size):
        raise ValueError('unsupported input ABI')
    if s['phase'] >= len(INPUT_PHASES) or s['result'] >= len(INPUT_RESULTS):
        raise ValueError('unknown input phase/result')
    return s


class UsbOwnerLock:
    """Every reader uses the same process lock; command clients never open USB."""
    def __init__(self, path=None):
        self.path = path or f'/tmp/hackios-usbcon-{os.getuid()}.lock'

    def __enter__(self):
        path = self.path
        self.fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            s = os.fstat(self.fd)
            if s.st_uid != os.getuid() or not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077:
                raise ValueError('unsafe USB owner lock file')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(self.fd)
            raise
        return self

    def __exit__(self, *_):
        os.close(self.fd)


class ControlServer:
    """Nonblocking local ingress, one bounded request. No client code executes here."""
    def __init__(self, path, clock=time.monotonic):
        self.path, self.clock = str(path), clock
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client = None
        self.buffer = b''
        self.busy = False
        self.bound = None
        try:
            # Refuse an occupied or stale name, never unlink another reader's socket.
            self.listener.bind(self.path)
            self.bound = os.stat(self.path).st_ino
            os.chmod(self.path, 0o600)
            self.listener.listen(1)
            self.listener.setblocking(False)
        except Exception:
            self.close()
            raise

    def reply(self, reply):
        if self.client is not None:
            try:
                data = json.dumps(reply, separators=(',', ':')).encode() + b'\n'
                self.client.send(data)  # bounded to well below a Unix socket send buffer
            except OSError:
                pass
            self.client.close()
        self.client, self.buffer, self.busy = None, b'', False

    def poll(self):
        if self.client is None:
            try:
                self.client, _ = self.listener.accept()
                self.client.setblocking(False)
                self.until = self.clock() + 2
            except BlockingIOError:
                return None
        if self.busy:
            return None
        if self.clock() >= self.until:
            self.reply(dict(state='refused', error='local request expired'))
            return None
        try:
            data = self.client.recv(257 - len(self.buffer))
        except BlockingIOError:
            return None
        if not data:
            self.reply(dict(state='refused', error='empty local request'))
            return None
        self.buffer += data
        if len(self.buffer) > 256:
            self.reply(dict(state='refused', error='local request too long'))
            return None
        if b'\n' not in self.buffer:
            return None
        try:
            envelope = json.loads(self.buffer)
            if not isinstance(envelope, dict) or set(envelope) != {'request', 'expires_ns'}:
                raise ValueError('request and expires_ns envelope required')
            expires = envelope['expires_ns']
            now = int(self.clock() * 1_000_000_000)
            if type(expires) is not int or not now < expires <= now + 5_000_000_000:
                raise ValueError('local request expired or invalid deadline')
            request = envelope['request']
            if not isinstance(request, dict):
                raise ValueError('object required')
            if request == {'command': 'home'} or request == {'command': 'status'}:
                pass
            elif set(request) == {'command', 'x', 'y'} and request['command'] == 'tap':
                if any(type(request[k]) is not int or not 0 <= request[k] <= 65535 for k in ('x', 'y')):
                    raise ValueError('tap needs unsigned 16-bit integer coordinates')
            else:
                raise ValueError('only tap x y, home, and status are supported')
        except (ValueError, TypeError) as exc:
            self.reply(dict(state='refused', error=str(exc)))
            return None
        self.busy = True
        return dict(request=request, expires_ns=expires)

    def close(self):
        self.reply(dict(state='refused', error='console owner stopped', ambiguous=True))
        self.listener.close()
        if self.bound is not None:
            try:
                if os.stat(self.path).st_ino == self.bound:
                    os.unlink(self.path)
            except FileNotFoundError:
                pass


def send_control(path, request):
    """Local socket only. Never discover a USB device from a command invocation."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(15)
        client.connect(str(path))
        envelope = dict(request=request, expires_ns=time.monotonic_ns() + 5_000_000_000)
        client.sendall(json.dumps(envelope).encode() + b'\n')
        reply = b''
        while b'\n' not in reply and len(reply) <= 4096:
            data = client.recv(4096 - len(reply) + 1)
            if not data:
                break
            reply += data
        if len(reply) > 4096 or not reply.endswith(b'\n'):
            raise ValueError('incomplete local control receipt; do not retry an ambiguous action')
        result = json.loads(reply)
        if not isinstance(result, dict):
            raise ValueError('invalid local control receipt')
        return result


class Gone(Exception):
    pass


def is_timeout(exc):
    return type(exc).__name__ == 'USBTimeoutError' or getattr(exc, 'errno', None) in (60, 110)


class UsbBackend:
    """pyusb, imported here so --verify and the tests need none of it."""

    def __init__(self):
        import usb.core
        import usb.util
        self.core, self.util = usb.core, usb.util
        self.error = usb.core.USBError

    def find(self):
        return self.core.find(idVendor=VID, idProduct=PID)

    def open(self):
        device = self.find()
        if device is None:
            return None
        try:
            product = self.util.get_string(device, device.iProduct)
        except ValueError:      # pyusb: no string readable yet, while it enumerates
            product = None
        if product != PRODUCT:
            self.dispose(device)
            return None
        return device

    def dispose(self, device):
        self.util.dispose_resources(device)


def parse_status(data):
    if len(data) != STATUS.size:
        raise ValueError(f'status is {len(data)} bytes, expected {STATUS.size}')
    status = dict(zip(STATUS_FIELDS, STATUS.unpack(data)))
    if status['magic'] != STATUS_MAGIC:
        raise ValueError(f'status magic {status["magic"]:#x}')
    return status


class Console:
    def __init__(self, args, backend, clock=time.monotonic, sleep=time.sleep, out=sys.stdout, err=sys.stderr, controller=None):
        self.args, self.backend, self.clock, self.sleep = args, backend, clock, sleep
        self.out, self.err = out, err
        self.controller = controller
        self.control = None
        self.t0 = None                  # first connect
        self.offset = 0
        self.boot = None
        self.status = None
        self.status_at = None
        self.reset_sent = False
        self.line_start = True
        self.raw = self.times = None
        self.summary = dict(connects=0, disconnects=0, bytes=0, reads=0, empty_reads=0, timeouts=0, errors=0, lost_bytes=0, lost_events=[], reset=None,
                            max_read_gap_s=0.0, connect_times=[], gone_times=[], end=None)
        self.last_read_at = None
        self.silent_since = None        # first timeout of a streak: the thread isn't answering, though the device is there
        self.silence_said = False
        self.drop = [re.compile(pattern) for pattern in (getattr(args, 'drop', None) or [])]
        self.pending = ''               # part of a line, for --drop
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.raw = open(path, 'wb')
            self.times = open(str(path) + '.times', 'w')

    def note(self, text):
        print(f'usbcon: {text}', file=self.err, flush=True)

    def elapsed(self):
        return self.clock() - self.t0 if self.t0 is not None else 0.0

    def show(self, payload):
        text = payload.decode(errors='replace').replace('\r', '')
        if self.args.quiet:
            return
        if self.drop:   # whole lines only, so a pattern can't miss across two reads
            text = self.pending + text
            cut = text.rfind('\n') + 1
            text, self.pending = text[:cut], text[cut:]
            text = ''.join(line for line in text.splitlines(keepends=True) if not any(d.search(line) for d in self.drop))
        parts = []
        for piece in text.splitlines(keepends=True):
            if self.line_start:
                parts.append(f'[{self.elapsed():8.2f}] ')
            parts.append(piece)
            self.line_start = piece.endswith('\n')
        self.out.write(''.join(parts))
        self.out.flush()

    def record(self, payload):
        if self.raw:
            self.raw.seek(self.offset)
            self.raw.write(payload)
            self.raw.flush()
            self.times.write(f'{self.elapsed():.3f}\t{self.offset}\t{len(payload)}\n')
            self.times.flush()
        self.show(payload)
        self.offset += len(payload)
        self.summary['bytes'] += len(payload)
        self.summary['reads'] += 1
        now = self.clock()
        if self.last_read_at is not None:
            self.summary['max_read_gap_s'] = max(self.summary['max_read_gap_s'], round(now - self.last_read_at, 3))
        self.last_read_at = now

    def read_status(self, device):
        status = parse_status(bytes(device.ctrl_transfer(0xc0, REQ_STATUS, 0, 0, READ_LEN, timeout=TRANSFER_TIMEOUT_MS)))
        self.status, self.status_at = status, self.clock()
        return status

    def stat_line(self):
        s = self.status
        if not s:
            return
        cpu = 100.0 * s['runtime'] / s['up'] if s['up'] else 0.0
        self.note(f't={self.elapsed():.0f}s total={s["total"]} behind={max(0, s["total"] - self.offset)} reads={s["reads"]} polls={s["polls"]} events={s["events"]} '
                  f'restarts={s["restarts"]} stalls={s["stalls"]} thread_cpu={cpu:.2f}%')

    def on_connect(self, device):
        if self.t0 is None:
            self.t0 = self.clock()
            self.summary['connect_wall'] = time.strftime('%Y-%m-%d %H:%M:%S %z')
        self.summary['connects'] += 1
        self.summary['connect_times'].append(round(self.elapsed(), 3))
        status = self.read_status(device)
        boot = (status['nonce'], status['entry_t'])
        if self.boot is not None and boot != self.boot:
            raise StopIteration('another boot appeared; this reader stays with its own. Start a new one')
        if self.boot is None:
            self.boot = boot
            self.note(f'connected: nonce {status["nonce"]:#x}, entry {status["entry_t"]:#x}, stream {status["total"]} bytes, ring {status["ring"]}')
        else:
            self.note(f'back after a restart at t={self.elapsed():.1f}s, offset {self.offset} of {status["total"]}, restarts {status["restarts"]}')

    def maybe_reset(self, device):
        after = self.args.reset_after
        if after is None or self.reset_sent or self.elapsed() < after:
            return
        self.reset_sent = True      # once only: a failed transfer is ambiguous, and repeating ends nothing it hasn't
        try:
            device.ctrl_transfer(0x40, REQ_RESET, RESET_VALUE, RESET_INDEX, None, timeout=TRANSFER_TIMEOUT_MS)
            self.summary['reset'] = f'accepted at t={self.elapsed():.1f}s'
            self.note(self.summary['reset'] + '; the phone panics, resets, and parks')
        except self.backend.error as exc:
            self.summary['reset'] = f'failed at t={self.elapsed():.1f}s: {exc}'
            self.note(self.summary['reset'] + '. A stall means blazer_usbcon=1: end this boot another way')

    def control_reply(self, state, error=None, **extra):
        reply = dict(state=state, ui_observed=False, **extra)
        if error:
            reply['error'] = error
        if self.control:
            reply['command'] = self.control['request']
            if self.control.get('reply'):
                reply['input'] = self.control['reply']
        self.summary.setdefault('controls', []).append(reply)
        self.note('input ' + json.dumps(reply, separators=(',', ':')))
        self.controller.reply(reply)
        self.control = None

    def control_step(self, device):
        if self.controller is None:
            return
        envelope = self.controller.poll()
        if envelope:
            self.control = dict(request=envelope['request'], phase='probe',
                                send_until=envelope['expires_ns'] / 1_000_000_000,
                                until=self.clock() + 10, next=0)
        c = self.control
        if c is None or self.clock() < c['next']:
            return
        if self.clock() >= c['until']:
            self.control_reply('unknown', 'input receipt deadline; do not repeat the action', ambiguous=c['phase'] in ('commit', 'wait'))
            return
        phase = c['phase']
        # Keep the caller's original freshness bound. After commit we only
        # collect its receipt; expiry never resends or cancels a delivered pair.
        if phase in ('probe', 'arm', 'commit') and self.clock() >= c['send_until']:
            self.control_reply('refused', 'local request expired before action', ambiguous=False)
            return
        if phase in ('probe', 'wait'):
            req, value, index = REQ_INPUT, 0, 0
        elif phase == 'arm':
            req, value, index = REQ_ARM, c['ticket'] & 65535, c['ticket'] >> 16
        else:
            req = REQ_TAP if c['request']['command'] == 'tap' else REQ_HOME
            value, index = c['request'].get('x', 0), c['request'].get('y', 0)
        try:
            s = parse_input(bytes(device.ctrl_transfer(0xc0, req, value, index, INPUT.size, timeout=TRANSFER_TIMEOUT_MS)))
        except self.backend.error as exc:
            unsupported = phase == 'probe' and getattr(exc, 'errno', None) == 32
            self.control_reply('refused' if unsupported else 'unknown', 'unsupported kernel input ABI' if unsupported else str(exc),
                               ambiguous=phase in ('commit', 'wait'))
            return
        except ValueError as exc:
            self.control_reply('unknown', str(exc), ambiguous=phase in ('commit', 'wait'))
            return
        c['reply'] = s
        if (s['nonce'], s['entry_t']) != self.boot:
            self.control_reply('refused', 'stale boot identity', ambiguous=phase in ('commit', 'wait'))
            return
        if not s['capabilities'] & 1:
            self.control_reply('refused', 'unsupported: blazer_usbcon_input=1 is required')
            return
        if s['result'] and not (phase == 'probe' and s['phase'] == 6):
            self.control_reply('refused', INPUT_RESULTS[s['result']])
            return
        if phase == 'probe':
            if c['request']['command'] == 'status':
                self.control_reply('status')
                return
            cap = 16 if c['request']['command'] == 'tap' else 8
            if not s['capabilities'] & cap:
                self.control_reply('refused', 'notready: service/client missing, or scripted replay owns input')
                return
            if c['request']['command'] == 'tap' and (c['request']['x'] >= s['width'] or c['request']['y'] >= s['height']):
                self.control_reply('refused', 'tap outside the current canvas')
                return
            c.update(phase='arm', ticket=s['ticket'], previous=s['generation'])
        elif phase == 'arm':
            if s['phase'] != 1 or s['generation'] != c['previous'] + 1:
                self.control_reply('refused', 'arm generation/phase mismatch')
                return
            c.update(phase='commit', generation=s['generation'])
        else:
            if s['generation'] != c['generation']:
                self.control_reply('unknown', 'generation changed; no automatic retry', ambiguous=True)
                return
            if phase == 'commit':
                if s['phase'] != 2 or (s['op'], s['x'], s['y']) != (req, value, index):
                    self.control_reply('unknown', 'commit receipt mismatch', ambiguous=True)
                    return
                c['phase'] = 'wait'
            elif s['phase'] == 5:
                self.control_reply('dispatched')
                return
            elif s['phase'] not in (2, 3, 4):
                self.control_reply('unknown', 'unexpected completion phase', ambiguous=True)
                return
            c['next'] = self.clock() + 0.1

    def step(self, device):
        """One read. Returns how long to wait before the next."""
        self.maybe_reset(device)
        self.control_step(device)
        offset = self.offset
        payload = bytes(device.ctrl_transfer(0xc0, REQ_READ, offset & 0xffff, (offset >> 16) & 0xffff, READ_LEN, timeout=TRANSFER_TIMEOUT_MS))
        if self.silence_said:
            self.note(f'answering again at t={self.elapsed():.0f}s')
        self.silent_since, self.silence_said = None, False
        if payload:
            self.record(payload)
            return 0.0
        self.summary['empty_reads'] += 1
        now = self.clock()
        if self.status_at is None or now - self.status_at >= STATUS_EVERY_S:
            status = self.read_status(device)
            if status['total'] - self.offset > status['ring']:
                skip_to = status['total'] - status['ring'] + min(LOST_MARGIN, status['ring'] // 4)
                lost = skip_to - self.offset
                self.summary['lost_bytes'] += lost
                self.summary['lost_events'].append(dict(t=round(self.elapsed(), 3), offset=self.offset, lost=lost))
                self.out.write(f'\n[{self.elapsed():8.2f}] [usbcon: {lost} bytes overwritten before they could be read]\n')
                self.out.flush()
                self.offset = skip_to
                self.line_start = True
                return 0.0
            if status['total'] > self.offset:
                return 0.0
        return IDLE_S

    def run(self):
        args, backend = self.args, self.backend
        start = self.clock()
        deadline = start + args.timeout
        device, gone_at, next_stats = None, None, start
        gone_reason = 'device gone'
        result = 'timeout'
        try:
            while self.clock() < deadline:
                if device is None:
                    if self.controller and self.controller.poll():
                        self.controller.reply(dict(state='refused', error='notready: kernel console not connected', ui_observed=False))
                    device = self.open_or_none()
                    if device is None:
                        if gone_at is not None and self.clock() - gone_at >= args.gone_exit:
                            result = gone_reason
                            break
                        self.sleep(0.2)
                        continue
                    try:
                        self.on_connect(device)
                    except self.backend.error as exc:
                        self.fail(exc)
                        backend.dispose(device)
                        device = None
                        self.sleep(0.2)
                        continue
                    gone_at = None
                try:
                    wait = self.step(device)
                except self.backend.error as exc:
                    if self.fail(exc):
                        continue    # a timeout: same device, same offset, and the next read asks again
                    if self.control:
                        self.control_reply('unknown', 'USB disconnected; no automatic retry', ambiguous=True)
                    backend.dispose(device)
                    device = None
                    # Enumeration can briefly retain a dead handle after reset.
                    # Bound reopening even when find() still reports that handle.
                    gone_at = self.clock()
                    if not self.present():
                        gone_reason = 'device gone'
                        self.summary['disconnects'] += 1
                        self.summary['gone_times'].append(round(self.elapsed(), 3))
                        self.note(f'device gone at t={self.elapsed():.1f}s; offset {self.offset}. Waiting {args.gone_exit:.0f} s for it to come back')
                    else:
                        gone_reason = 'console unavailable'
                        self.note(f'console unavailable at t={self.elapsed():.1f}s; offset {self.offset}. Waiting {args.gone_exit:.0f} s to reopen')
                    self.sleep(0.2)
                    continue
                if self.clock() >= next_stats:
                    next_stats = self.clock() + args.stats
                    self.stat_line()
                if wait:
                    self.sleep(wait)
            if self.t0 is None:
                result = 'never connected'
        except StopIteration as stop:
            result = str(stop)
            self.note(result)
        except ValueError as bad:   # a status that isn't ours: wrong kernel, so reading on would be guessing
            result = f'bad reply: {bad}'
            self.note(result)
        finally:
            if device is not None:
                backend.dispose(device)
            self.finish(result)
        return 0 if self.summary['connects'] else 3

    def present(self):
        try:
            return self.backend.find() is not None
        except self.backend.error:
            return False

    def open_or_none(self):
        try:
            return self.backend.open()
        except self.backend.error as exc:
            if getattr(exc, 'errno', None) in (13, 3):
                raise SystemExit(f'USB access denied: {exc}')
            return None

    def fail(self, exc):
        """True for a timeout. Anything else means reopen."""
        if is_timeout(exc):
            self.summary['timeouts'] += 1
            now = self.clock()
            if self.silent_since is None:
                self.silent_since = now - TRANSFER_TIMEOUT_MS / 1000
            quiet = now - self.silent_since
            self.summary['max_silence_s'] = max(self.summary.get('max_silence_s', 0.0), round(quiet, 3))
            if quiet >= HANG_SAY_S and not self.silence_said:
                self.silence_said = True
                self.note(f'no answer for {quiet:.0f} s at t={self.elapsed():.0f}s, device still on the bus: the thread is not being scheduled. '
                          'Hard hang or a long masked section; a boot that is merely slow still answers. Last line above is the last the kernel got out')
            return True
        self.summary['errors'] += 1
        return False

    def finish(self, result):
        if self.control:
            self.control_reply('unknown', 'console stopped; no automatic retry', ambiguous=True)
        self.summary['end'] = result
        self.summary['final_offset'] = self.offset
        self.summary['elapsed_s'] = round(self.elapsed(), 3)
        if self.status:
            s = self.status
            self.summary['last_status'] = {k: v for k, v in s.items() if k != 'magic'}
            self.summary['thread_cpu_percent'] = round(100.0 * s['runtime'] / s['up'], 3) if s['up'] else None
        if self.raw:
            self.raw.close()
            self.times.close()
            Path(str(self.args.output) + '.json').write_text(json.dumps(self.summary, indent=1) + '\n')
        self.note(f'end: {result}. {self.summary["bytes"]} bytes, {self.summary["connects"]} connects, {self.summary["timeouts"]} timeouts, '
                  f'{self.summary["lost_bytes"]} lost; last offset {self.offset}')


def dump_ring(raw):
    """(stream position of the first retained byte, retained bytes, stream total) from a capture."""
    if len(raw) < DUMP_RING_OFF:
        raise ValueError(f'capture is {len(raw)} bytes: too short for the mirror')
    magic, _seq, _flags, _msgbufp, _bufc, size, _write, total, tail_off, tail_len = DUMP_HEADER.unpack_from(raw, DUMP_HEADER_OFF)
    if magic.rstrip(b'\0') != DUMP_MAGIC:
        raise ValueError(f'no {DUMP_MAGIC.decode()} header in this capture')
    if not 0 < size <= 0x100000 or tail_len > size or tail_off >= size or total < tail_len:
        raise ValueError(f'mirror header makes no sense: size {size} tail {tail_off}+{tail_len} total {total}')
    if tail_off != (total - tail_len) % size:
        raise ValueError('mirror header disagrees with itself')
    ring = raw[DUMP_RING_OFF:DUMP_RING_OFF + size]
    if tail_off + tail_len <= size:
        linear = ring[tail_off:tail_off + tail_len]
    else:
        linear = ring[tail_off:] + ring[:tail_len - (size - tail_off)]
    if len(linear) != tail_len:
        raise ValueError('capture is too short for the ring')
    return total - tail_len, linear, total


def dump_console(raw, live):
    """The RAM console as (bytes, how far it leads the stream). It holds the stream's first MiB, after the kernel's STAGE0 mark.
    (b'', 0) if it isn't there, or doesn't begin with what the host read."""
    sig, _start, used = DUMP_CONSOLE_HEADER.unpack_from(raw, 0)
    if sig != DUMP_CONSOLE_SIG or used > len(raw) - DUMP_CONSOLE_HEADER.size or not live:
        return b'', 0
    console = raw[DUMP_CONSOLE_HEADER.size:DUMP_CONSOLE_HEADER.size + used]
    skew = console.find(live[:64], 0, 256)
    return (console[skew:], skew) if skew >= 0 else (b'', 0)


def verify(raw_path, dump_path):
    """Live bytes against the capture's two stores. Pass: at least one byte compared, none differs. Bytes in neither store
    are the ones only the live console has."""
    live = Path(raw_path).read_bytes()
    raw = Path(dump_path).read_bytes()
    first, linear, total = dump_ring(raw)
    ranges = [(int(o), int(n)) for _t, o, n in (line.split('\t') for line in Path(str(raw_path) + '.times').read_text().splitlines())]
    console, skew = dump_console(raw, live[:64] if ranges and ranges[0][0] == 0 else b'')
    compared = mismatched = only_live = live_end = 0
    first_bad = None

    def check(start, got, want):
        nonlocal mismatched, first_bad
        if got != want:
            bad = [i for i in range(len(got)) if got[i] != want[i]]
            mismatched += len(bad)
            first_bad = min(first_bad, start + bad[0]) if first_bad is not None else start + bad[0]

    for offset, length in ranges:
        end = offset + length
        live_end = max(live_end, end)
        a, b = max(offset, first), min(end, total)          # ring
        ring_bytes = max(0, b - a)
        if ring_bytes:
            check(a, live[a:b], linear[a - first:b - first])
        c, d = offset, min(end, len(console), max(offset, first) if ring_bytes else end)    # console, for what the ring no longer has
        console_bytes = max(0, d - c)
        if console_bytes:
            check(c, live[c:d], console[c:d])
        compared += ring_bytes + console_bytes
        only_live += length - ring_bytes - console_bytes
    return dict(ok=compared > 0 and mismatched == 0, compared=compared, mismatched=mismatched, first_mismatch=first_bad, live_end=live_end, stream_total=total,
                not_read_before_reset=max(0, total - live_end), ring_from=first, console_bytes=len(console), console_leads_by=skew,
                capture_lost=max(0, first - len(console)), only_the_live_console_has=only_live)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--timeout', type=float, default=2400, help='seconds to run; default 2400, past the 2100 s runner window')
    parser.add_argument('--gone-exit', type=float, default=30, help='end this many seconds after the device goes; a restart takes under 10')
    parser.add_argument('--output', help='raw stream file; also .times and .json')
    parser.add_argument('--quiet', action='store_true', help='nothing on stdout')
    parser.add_argument('--stats', type=float, default=30, help='seconds between status lines on stderr')
    parser.add_argument('--drop', action='append', metavar='REGEX', help="terminal only, repeatable, e.g. --drop '^com\\.apple\\.xpc\\.launchd.*<Notice>'; --output keeps all")
    parser.add_argument('--reset-after', type=float, metavar='SECONDS', help='end the boot this long after the first connect: panic, reset, park. Needs blazer_usbcon=2')
    parser.add_argument('--control-socket', metavar='PATH', help='owner serves bounded local TAP/HOME requests on this private socket')
    control = parser.add_mutually_exclusive_group()
    control.add_argument('--tap', nargs=2, type=int, metavar=('X', 'Y'), help='send canvas-pixel TAP to the running owner; no USB in this process')
    control.add_argument('--home', action='store_true', help='send HOME to the running owner; no USB in this process')
    control.add_argument('--input-status', action='store_true', help='query HLI1 status through the running owner')
    parser.add_argument('--verify', metavar='RAW', help='compare a finished --output with a capture; no USB')
    parser.add_argument('--dump', metavar='KERNEL_LOG', help='ramdump/kernel.log for --verify')
    args = parser.parse_args()
    if args.tap is not None or args.home or args.input_status:
        if not args.control_socket:
            parser.error('input commands need --control-socket of the existing reader')
        if args.verify or args.reset_after is not None:
            parser.error('input client cannot verify or reset')
        request = dict(command='tap', x=args.tap[0], y=args.tap[1]) if args.tap else dict(command='home' if args.home else 'status')
        try:
            result = send_control(args.control_socket, request)
        except (OSError, ValueError) as exc:
            print(json.dumps(dict(state='unknown', error=str(exc), ambiguous=True)), file=sys.stderr)
            return 4
        print(json.dumps(result, indent=1))
        return 0 if result.get('state') in ('dispatched', 'status') else 4
    if args.verify:
        if not args.dump:
            parser.error('--verify needs --dump')
        result = verify(args.verify, args.dump)
        print(json.dumps(result, indent=1))
        return 0 if result['ok'] else 1
    try:
        with UsbOwnerLock():
            controller = ControlServer(args.control_socket) if args.control_socket else None
            try:
                return Console(args, UsbBackend(), controller=controller).run()
            finally:
                if controller:
                    controller.close()
    except BlockingIOError:
        parser.error('another usbcon reader owns USB; use its --control-socket')
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    sys.exit(main())
