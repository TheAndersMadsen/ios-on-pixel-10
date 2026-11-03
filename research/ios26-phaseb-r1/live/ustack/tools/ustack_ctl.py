#!/usr/bin/env python3
"""Ask a running hk_ustack kernel (hk-ustack-dbg4, blazer_usbcon=1 blazer_usbcon_input=1) to print one pid's user stacks.

    $TEGU_PYTHON research/ios26-phaseb-r1/live/ustack/tools/ustack_ctl.py PID ROUNDS    # Mac, 1..120 rounds, one per period
    $TEGU_PYTHON research/ios26-phaseb-r1/live/ustack/tools/ustack_ctl.py PID 0         # cancel that pid's request
    $TEGU_PYTHON research/ios26-phaseb-r1/live/ustack/tools/ustack_ctl.py --status

One vendor IN control transfer, 0xc0/0x70 (osfmk/kern/hk_ustack_wire.h, HUS1, 56 bytes), to the console gadget 1209:0002/0003
"hackios XNU console". Read-only on the phone: the kernel prints HK USTACK lines; no input, UI or task state changes.
It takes tools/usbcon.py's USB owner lock and refuses while a usbcon reader owns USB (read the lines with that reader, or
with the ramdump, then symbolicate with ustack_sym.py). The usbcon.py control socket does not carry this request yet (that
file has another owner's uncommitted HLI1 changes); a later --ustack there is the way to use it beside a live reader.
"""
import argparse
import fcntl
import json
import os
import stat
import struct
import sys

VID, PIDS, PRODUCT = 0x1209, (0x0002, 0x0003), 'hackios XNU console'
REQ, MAGIC = 0x70, 0x31535548
WIRE = struct.Struct('<IHHQQ8I')
FIELDS = ('magic', 'version', 'bytes', 'nonce', 'entry_t', 'result', 'pid', 'rounds_left', 'period_s', 'names', 'rounds',
          'lines', 'dropped')
RESULTS = ('ok', 'unsupported (no hk_ustack sampler: kernel without it, or neither hk_ustack= nor blazer_usbcon_input=1)',
           'badarg', 'notfound')
assert WIRE.size == 56


def parse(data):
    if len(data) != WIRE.size:
        raise ValueError(f'reply {len(data)} bytes, expected {WIRE.size}')
    r = dict(zip(FIELDS, WIRE.unpack(bytes(data))))
    if (r['magic'], r['version'], r['bytes']) != (MAGIC, 1, WIRE.size):
        raise ValueError('not an HUS1 reply')
    if r['result'] >= len(RESULTS):
        raise ValueError('unknown result')
    r['result_name'] = RESULTS[r['result']].split(' ')[0]
    return r


def request_args(pid, rounds):
    if not 1 <= pid <= 65535:
        raise ValueError('pid 1..65535')
    if not 0 <= rounds <= 120:
        raise ValueError('rounds 0 (cancel) or 1..120')
    return pid, rounds


def owner_lock():
    path = f'/tmp/hackios-usbcon-{os.getuid()}.lock'      # tools/usbcon.py UsbOwnerLock
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    s = os.fstat(fd)
    if s.st_uid != os.getuid() or not stat.S_ISREG(s.st_mode) or s.st_mode & 0o077:
        os.close(fd)
        raise ValueError('unsafe USB owner lock file')
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise ValueError('a usbcon reader owns USB; stop it first or wait for usbcon.py --ustack')
    return fd


def transfer(value, index):
    import usb.core
    import usb.util
    dev = next((d for p in PIDS for d in [usb.core.find(idVendor=VID, idProduct=p)] if d is not None), None)
    if dev is None:
        raise ValueError('no hackios XNU console on USB')
    try:
        if usb.util.get_string(dev, dev.iProduct) != PRODUCT:
            raise ValueError('USB device is not the hackios XNU console')
        return parse(dev.ctrl_transfer(0xc0, REQ, value, index, WIRE.size, timeout=2000))
    finally:
        usb.util.dispose_resources(dev)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pid', type=int, nargs='?')
    ap.add_argument('rounds', type=int, nargs='?')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args(argv)
    try:
        if a.status:
            if a.pid is not None:
                ap.error('--status takes no pid')
            value, index = 0, 0
        else:
            if a.pid is None or a.rounds is None:
                ap.error('PID ROUNDS, or --status')
            value, index = request_args(a.pid, a.rounds)
        fd = owner_lock()
        try:
            r = transfer(value, index)
        finally:
            os.close(fd)
    except ValueError as exc:
        print(json.dumps(dict(state='refused', error=str(exc))), file=sys.stderr)
        return 4
    except Exception as exc:                              # USB errors: say so, never retry
        print(json.dumps(dict(state='unknown', error=f'{type(exc).__name__}: {exc}')), file=sys.stderr)
        return 4
    print(json.dumps(r, indent=1))
    return 0 if r['result'] == 0 else 3


if __name__ == '__main__':
    sys.exit(main())
