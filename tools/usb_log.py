#!/usr/bin/env python3
"""Wait for the temporary tegu USB diagnostic and retrieve its EP0 log."""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import stat
import time
import usb.core
import usb.util
from usb_keyboard import Keyboard


def run(keyboard):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=75)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--tail', type=int, default=0, metavar='BYTES',
                        help='skip the boot replay: start BYTES before the current end of the log')
    parser.add_argument('--interactive', action='store_true',
                        help='forward keyboard input; Ctrl+] leaves the client')
    parser.add_argument('--send', help='send one UTF-8 input packet (at most 64 bytes), once')
    parser.add_argument('--send-after', help='wait for this text in live output before sending')
    parser.add_argument('--send-delay', type=float, default=0,
                        help='seconds to wait after connection/output trigger before sending')
    args = parser.parse_args()
    if 'HACKIOS_CURRENT_FDT_ATTEMPT_DIR' in os.environ:
        if args.interactive or args.send is not None or args.send_after is not None or args.send_delay or args.tail or args.output:
            parser.error('current-FDT observation permits no keyboard/send/tail/output modes')
        gate = load_current_fdt_gate()
        context = gate.CurrentFDTContext(os.environ[gate.CURRENT_FDT_ENV], gate.inherited_lease_fd())
        try:
            run_current_fdt(context, find=lambda: usb.core.find(idVendor=0x1209, idProduct=0x0001),
                            identify=lambda d: usb.util.get_string(d, d.iProduct),
                            dispose=usb.util.dispose_resources)
        except BaseException as exc:
            try:
                context.retain({'event': 'terminal-failure', 'error_type': type(exc).__name__, 'error': str(exc),
                                'replay': 'FORBIDDEN; intent without return is UNKNOWN'})
            finally:
                raise SystemExit('Current-FDT terminal failure; capture-only reconciliation; no reopen/resend: ' + str(exc))
        return
    if args.interactive and (args.send is not None or args.send_after is not None or args.send_delay):
        parser.error('--interactive cannot be combined with scripted input options')
    if args.interactive:
        keyboard.enable()
    packet = args.send.encode() if args.send is not None else None
    if packet is not None and not 1 <= len(packet) <= 64:
        parser.error('--send must encode to 1..64 bytes')
    if args.send_after is not None and (packet is None or not 1 <= len(args.send_after.encode()) <= 4096):
        parser.error('--send-after requires --send and 1..4096 UTF-8 bytes')
    if not 0 <= args.send_delay < args.timeout or (args.send_delay and packet is None):
        parser.error('--send-delay requires --send and must be nonnegative and below --timeout')
    trigger = args.send_after.encode() if args.send_after is not None else None
    send_ready, watched = trigger is None, b''
    send_at = time.monotonic() + args.send_delay if send_ready else None
    deadline = time.monotonic() + args.timeout
    offset, observed, error = 0, False, None
    capacity, log_header = 65536, b''
    tailed = False
    if args.output:
        # Evidence may contain hardware-specific addresses; only ignored destinations.
        root = Path(__file__).resolve().parents[1]
        output = args.output.resolve()
        if not output.is_relative_to(root / 'research'):
            parser.error('--output must be beneath the repository research/ directory')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b'')
        # A stable tail -F target for observers; only the USB reader owns EP0.
        latest = root / 'research/tegu-live.log'
        if output != latest and (latest.is_symlink() or not latest.exists()):
            latest.unlink(missing_ok=True)
            latest.symlink_to(output.relative_to(root / 'research'))
    while time.monotonic() < deadline:
        device = usb.core.find(idVendor=0x1209, idProduct=0x0001)
        if device is None:
            if observed:
                if packet is not None:
                    sys.exit('Diagnostic disconnected before the input trigger; input was not sent.')
                print('\nDiagnostic disconnected.', file=sys.stderr)
                return
            time.sleep(0.2)
            continue
        try:
            # Identify this gadget before claiming/opening other devices sharing test IDs.
            if not observed and usb.util.get_string(device, device.iProduct) != 'Tegu USB diagnostic':
                time.sleep(0.2)
                continue
            if not observed:
                observed = True
                print('Tegu USB diagnostic connected.', file=sys.stderr)
                if args.interactive:
                    print('Interactive console: Ctrl+] leaves the client.', file=sys.stderr)
            if args.interactive:
                keys = keyboard.poll()
                if keys == b'' or (keys is not None and b'\x1d' in keys):
                    print('\nLeaving client; no reboot command sent.', file=sys.stderr)
                    return
                if keys:
                    try:
                        device.ctrl_transfer(0x40, 0x5b, 0, 0, keys, timeout=1000)
                    except usb.core.USBError as exc:
                        sys.exit(f'Keyboard transfer failed; not retrying ambiguous input: {exc}')
            if packet is not None and send_ready and time.monotonic() >= send_at:
                try:
                    device.ctrl_transfer(0x40, 0x5b, 0, 0, packet, timeout=1000)
                except usb.core.USBError as exc:
                    sys.exit(f'Input transfer failed; not retrying an ambiguous write: {exc}')
                packet = None
            if args.tail and not tailed:
                tailed = True
                capacity = 1048576
                offset = max(0, find_end(device, capacity) - args.tail)
                print(f'Tailing from log offset {offset}.', file=sys.stderr)
            if offset >= capacity:
                time.sleep(0.1)
                continue
            payload = bytes(device.ctrl_transfer(0xc0, 0x5a, offset & 0xffff, offset >> 16, 512, timeout=500))
            if payload:
                log_header = (log_header + payload)[-1024:]
                if b'TEGU USB: log32 1048576' in log_header:
                    capacity = 1048576
                if trigger is not None and not send_ready:
                    watched = (watched + payload)[-(len(trigger) + 512):]
                    send_ready = trigger in watched
                    if send_ready:
                        send_at = time.monotonic() + args.send_delay
                offset += len(payload)
                sys.stdout.write(payload.decode(errors='replace'))
                sys.stdout.flush()
                if args.output:
                    with output.open('ab') as f:
                        f.write(payload)
            else:
                time.sleep(0.1)
        except (usb.core.USBError, ValueError) as exc:
            error = exc
            if getattr(exc, 'errno', None) in (13, 3):
                sys.exit(f'USB access denied: {exc}. Host USB permissions are required for test ID 1209:0001.')
            time.sleep(0.1)
        finally:
            usb.util.dispose_resources(device)
    if not observed:
        sys.exit('No tegu diagnostic enumerated before timeout.')
    if not offset:
        sys.exit(f'Diagnostic appeared but no log was read: {error}')
    if packet is not None:
        sys.exit('Input was not sent: output trigger was not observed before timeout.')


def load_current_fdt_gate():
    # Fixed canonical entry point; the context then checks this guard's exact
    # receipt-bound source pin against the actual in-flight journal. No module
    # named by candidate/JSON/env is imported, and no sys.path shadow is used.
    path = Path(__file__).resolve().parents[1] / 'research/laguna-usb-fix/automation/device_gate.py'
    if path != path.resolve(strict=True):
        raise ValueError('noncanonical Gate import')
    spec = importlib.util.spec_from_file_location('_owned_current_fdt_gate', path)
    module = importlib.util.module_from_spec(spec)
    # Execute source bytes, not a cached pyc file.
    expected = os.environ.get('HACKIOS_CURRENT_FDT_GATE_SHA256', '')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as handle:
        before = os.fstat(handle.fileno())
        source = handle.read(1048577)
        after = os.fstat(handle.fileno())
    stamp = lambda st: (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or stamp(before) != stamp(after) or
            stamp(before) != stamp(path.lstat()) or len(source) > 1048576 or
            hashlib.sha256(source).hexdigest() != expected):
        raise ValueError('pinned canonical Gate source differs')
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def run_current_fdt(context, *, find, identify, dispose, sleep=time.sleep):
    """Opt-in branch of the ONE logger. All fixtures inject these interfaces.

    Discovery waits only before accepting the existing legacy diagnostic handle.
    No reconnect catch surrounds witness/read64; any error is terminal. The
    single RLock spans original raw 5a log AND the N646 observation.
    """
    context.start_once()  # durable latch before discovery/operation, never reset
    while not (context.directory / 'current-fdt-boot.json').exists():
        context.check('wait-boot', {})
        sleep(0.02)
    context.arm_boot_interval()
    # Waiting before the frozen start checks the underlying owner/deadline,
    # without weakening the per-read interval check or touching USB.
    while time.monotonic() < context.start:
        start, deadline = context.start, context.deadline
        del context.deadline
        try:
            context.check('wait-window', {})
        finally:
            context.start, context.deadline = start, deadline
        sleep(min(0.02, max(0, start-time.monotonic())))
    device = None
    while device is None:
        context.check('discover', {})
        candidate = find()
        if candidate is None:
            sleep(0.02)
            continue
        try:
            if identify(candidate) != 'Tegu USB diagnostic':
                dispose(candidate)
                continue
        except BaseException:
            dispose(candidate)
            raise
        device = candidate
    try:
        context.bind_handle(device)
        print('Tegu USB diagnostic connected.', file=sys.stderr)
        witness = bytearray()
        with context.lock:
            while True:
                payload = context.read_log(len(witness))
                if payload:
                    witness.extend(payload)
                    sys.stdout.write(payload.decode(errors='replace'))
                    sys.stdout.flush()
                elif context.reader.MARKER in witness and witness.endswith(b'\n'):
                    # Drain all currently available log bytes before parsing:
                    # duplicate/malformed witness occurrences are not hidden by
                    # stopping as soon as a matching first line appears.
                    break
                else:
                    sleep(0.02)
            # Set before the call, outside the legacy reconnect loop. The disk
            # latch also prevents a new process/Observation after a kill.
            context.retain({'event': 'one-shot-hook-entered'})
            context.collect(bytes(witness))
    finally:
        dispose(device)


def read_at(device, offset):
    return bytes(device.ctrl_transfer(0xc0, 0x5a, offset & 0xffff, offset >> 16, 512, timeout=500))


def find_end(device, capacity):
    """Binary-search the first offset that returns no log bytes."""
    head = read_at(device, 0)
    if b'TEGU USB: log32 1048576' in head or capacity < 1048576:
        capacity = max(capacity, 1048576)
    low, high = 0, capacity
    while high - low > 512:
        middle = (low + high) // 2
        if read_at(device, middle):
            low = middle
        else:
            high = middle
    return low


def main():
    with Keyboard() as keyboard:
        run(keyboard)


if __name__ == '__main__':
    main()
