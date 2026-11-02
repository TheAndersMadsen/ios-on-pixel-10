#!/usr/bin/env python3
"""Live XNU console over USB, from a kernel booted with blazer_usbcon=1 or 2.

Reads the XNU-MSGBUF mirror over EP0 from 1209:0002 "hackios XNU console" while iOS boots, and writes it to the
terminal with time since connect. Read-only on the phone unless --reset-after is given. Never touches 1209:0001, so
it runs beside tools/usb_log.py, which owns the shim's gadget. Run it with the runner's Python, TEGU_PYTHON, which
has pyusb.

    $TEGU_PYTHON -u tools/usbcon.py --output research/laguna-usb-fix/attempts/usbcon-NAME.log
    $TEGU_PYTHON -u tools/usbcon.py --output X.log --reset-after 300     # needs blazer_usbcon=2
    python3 -I tools/usbcon.py --verify X.log --dump ATTEMPT/ramdump/kernel.log

--output writes X.log, bytes at their stream offsets; X.log.times, one "seconds offset length" per read; X.log.json,
the summary. --drop REGEX only quiets the terminal: X.log keeps everything. --verify compares those bytes with both
stores in the capture after the reset: the RAM console, which holds the stream's first MiB, and the ring, its last.
"""
import argparse
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
    def __init__(self, args, backend, clock=time.monotonic, sleep=time.sleep, out=sys.stdout, err=sys.stderr):
        self.args, self.backend, self.clock, self.sleep = args, backend, clock, sleep
        self.out, self.err = out, err
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

    def step(self, device):
        """One read. Returns how long to wait before the next."""
        self.maybe_reset(device)
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
        result = 'timeout'
        try:
            while self.clock() < deadline:
                if device is None:
                    device = self.open_or_none()
                    if device is None:
                        if gone_at is not None and self.clock() - gone_at >= args.gone_exit:
                            result = 'device gone'
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
                    backend.dispose(device)
                    device = None
                    if not self.present():
                        gone_at = self.clock()
                        self.summary['disconnects'] += 1
                        self.summary['gone_times'].append(round(self.elapsed(), 3))
                        self.note(f'device gone at t={self.elapsed():.1f}s; offset {self.offset}. Waiting {args.gone_exit:.0f} s for it to come back')
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
    parser.add_argument('--verify', metavar='RAW', help='compare a finished --output with a capture; no USB')
    parser.add_argument('--dump', metavar='KERNEL_LOG', help='ramdump/kernel.log for --verify')
    args = parser.parse_args()
    if args.verify:
        if not args.dump:
            parser.error('--verify needs --dump')
        result = verify(args.verify, args.dump)
        print(json.dumps(result, indent=1))
        return 0 if result['ok'] else 1
    return Console(args, UsbBackend()).run()


if __name__ == '__main__':
    sys.exit(main())
