#!/usr/bin/env python3
"""Split an iOS boot's console into per-subsystem files, with timestamps. HOST ONLY: reads files, never a device.

Input, any of:
  - a ramdump kernel.log (research/laguna-usb-fix/attempts/<run>/ramdump/kernel.log): raw kernel lines. Only the
    current boot is read: the file ends at the first panic line (the deadline's too), at a second XNU banner, or at
    --max-bytes; older boots' residue after it is skipped (--whole reads all).
  - a live stream: tools/live_boot.sh's console.txt ("HH:MM:SS.mmm <line>"), usbcon.py's raw usbcon.log, or '-'
    (stdin, e.g. piped from usbcon.py).

Output directory (default <input>.hklog/, '-' input: ./hklog-<time>/), one line per input line, each prefixed by its
time: the live stream's wall time ("19:41:57.821"), or, in a ramdump, the boot time of the last anchor before it
("t>=120s": HKOBS t=, blazer-root's watch line; a lower bound, at most 10 s early):
  all.log                 everything, timestamped
  wifi.log bt.log net.log usb.log apps.log location.log proc.log status.log panic.log launchd.log display.log
  input.log power.log security.log other.log (no rule matched)
  hkl/<program>.log       each mirrored daemon's own lines (hk_logmirror.dylib's "HKL <prog>[pid] ...")
  summary.txt             line counts, the last HKOBS line of each subsystem, respawns and mirror drops (rewritten at
                          the end, and every 10 s with --follow)

A line can go to more than one file (an HKL line of wifid: hkl/wifid.log and wifi.log). Rules: SUBSYSTEMS below.

  python3 -I tools/hklog.py research/laguna-usb-fix/attempts/<run>/ramdump/kernel.log
  python3 -I tools/hklog.py --follow <live run>/console.txt            # until Ctrl-C, or --idle-exit N s
  mac ... python3 -I tools/usbcon.py ... | python3 -I tools/hklog.py --follow - -o /tmp/live1
  python3 -I tools/hklog.py --grep wifi research/.../kernel.log         # print one subsystem's lines, no files
"""
import argparse
import os
from pathlib import Path
import re
import sys
import time

# (file, regex on the line without its time prefix). Order matters only for 'other' (no rule matched).
DAEMONS_WIFI = r'wifid|WirelessRadioManagerd|wifianalyticsd|airportd|wifip2pd'
DAEMONS_BT = r'bluetoothd|BlueTool|bluetoothuserd|audiomxd'
DAEMONS_NET = r'configd|CommCenter|mDNSResponder|nesessionmanager|networkd|symptomsd|apsd'
DAEMONS_APPS = r'SpringBoard|MobilePhone|Preferences|lsd|tccd|runningboardd|backboardd|containermanagerd|iconservicesagent'
SUBSYSTEMS = [
    ('wifi', re.compile(r'^(blazer-wifi|blazer-pcie|blazer-apple80211|IO80211|AppleBCMWLAN)|^HKOBS \d+ \S+ t=\d+ (wifi|fw):'
                        rf'|^HKL ({DAEMONS_WIFI})\[|^hk_(env|deny): ({DAEMONS_WIFI})\b|\b({DAEMONS_WIFI})\[\d+'
                        r'|com\.apple\.(wifid|WirelessRadioManager|wifianalyticsd|wifip2pd|wifiFirmwareLoader)\b')),
    ('bt', re.compile(r'^(blazer-bt|btsk:|blazer-btuart)|^HKOBS \d+ \S+ t=\d+ bt:'
                      rf'|^HKL ({DAEMONS_BT})\[|^hk_(env|deny): ({DAEMONS_BT})\b|\b({DAEMONS_BT})\[\d+|com\.apple\.(bluetoothd|BlueTool)\b')),
    ('net', re.compile(r'^(blazer-usbnet|blazer-netstack|blazer-net)|IONetworkStack|InterfaceNamer'
                       rf'|^HKL ({DAEMONS_NET})\[|^hk_(env|deny): ({DAEMONS_NET})\b|com\.apple\.(configd|CommCenter)\b')),
    ('usb', re.compile(r'^(blazer-usbcon|TEGU USB|TGL USB)|^HKOBS \d+ \S+ t=\d+ usb:')),
    ('usbhost', re.compile(r'^(blazer-usbhost|blazer-dp)')),
    ('apps', re.compile(rf'^HKL ({DAEMONS_APPS})\[|^HK USTACK|^HKMAIN|^HKSTDERR|^SWEET Sandbox|^usertrap:|^userabort'
                        rf'|^hk_(env|deny): ({DAEMONS_APPS})\b|\(({DAEMONS_APPS})\)|\b(MobilePhone|Preferences)\[\d+')),
    ('location', re.compile(r'^HKL (locationd)\[|\blocationd\[\d+')),
    ('proc', re.compile(r'^HKOBS \d+ \S+ t=\d+ proc:|^hk_(env|deny|adaptive):|exited due to|exited with exit code'
                        r'|\bjob state = (exited|spawn failed)|\bservice state: (spawn scheduled|penalty box)|^CRASH|crash(ed)? loop')),
    ('status', re.compile(r'^HKOBS |^blazer-root: (watch|deadline)|^HK TOP|^HKBATT')),
    ('panic', re.compile(r'^panic\(|^Panicked |^Debugger called|^Backtrace|^Kernel Extensions in backtrace|^\s+lr: 0x')),
    ('launchd', re.compile(r'^com\.apple\.xpc\.launchd\||^xpcproxy\[|^launchd\[|^exec \S|^shared_region:|^libignition:')),
    ('display', re.compile(r'^(SWEET (FB|BL|SURF|DISPLAY)|tensor-dpu|hk_fb|IOK backboardd|sweetfb|HK FB)')),
    ('input', re.compile(r'^(blazer-touch|blazer-keys|blazer-haptic|blazer-power-key|SWEET (HID|PHYSICAL|TOUCH)|HK LIVE)')),
    ('power', re.compile(r'^(blazer-(gov|clock|thermal|battery|rtc|cpu)|SWEET CPU|HKBATT)')),
    ('security', re.compile(r'^(SWEET (AKS|AMFI|Sandbox|KEYSTORE)|FIPSPOST)')),
]
HKL_RE = re.compile(r'HKL ([^\[\]\s/]{1,32})\[(\d+)\] (.*)$')   # searched: the console can put other bytes before it
# An older image's direct mirror (hk_stderr_console, StandardErrorPath): libsystem_trace's DT-mode line, untagged
DT_RE = re.compile(r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+[-+]\d{4} ([^\[\]\s/]{1,32})\[(\d+):\d+\] ')
LIVE_STAMP = re.compile(r'^(\d\d:\d\d:\d\d\.\d{3}) (.*)$')
ANCHORS = [(re.compile(r'^HKOBS \d+ \S+ t=(\d+) '), 1.0), (re.compile(r'^blazer-root: watch t (\d+) ms'), 0.001)]
BANNER = re.compile(r'^Darwin Kernel Version ')
STATUS_LINE = re.compile(r'^HKOBS (\d+) (\S+) t=(\d+) (\w+): (.*)$')
PROC_ITEM = re.compile(r'(\S+) (\d+)/(\d+) (\S+)(?: l(\d+) d(\d+))?')
SAFE_NAME = re.compile(r'[^A-Za-z0-9_.+-]')


def program_of(text):
    """(program, pid) of a mirrored daemon's line: hk_logmirror's HKL tag, or an untagged DT-mode line. Else None"""
    m = HKL_RE.search(text) or DT_RE.match(text)
    return (m.group(1), m.group(2)) if m else None


def classify(text):
    """The subsystem files this line goes to (possibly several), and the mirrored program if any. An untagged DT-mode
    line is classified as if it carried the HKL tag."""
    pp = program_of(text)
    probe = text if pp is None or text.startswith('HKL ') else f'HKL {pp[0]}[{pp[1]}] ' + text
    out = [name for name, rx in SUBSYSTEMS if rx.search(probe) or (probe is not text and rx.search(text))]
    return out, (pp[0] if pp else None)


def parse_proc(text):
    """'configd 1/0 - l12 d0 lsd 3/2 s6' -> {name: (execs, exits, last, lines, dropped)}"""
    out = {}
    for m in PROC_ITEM.finditer(text):
        out[m.group(1)] = (int(m.group(2)), int(m.group(3)), m.group(4),
                           int(m.group(5)) if m.group(5) else None, int(m.group(6)) if m.group(6) else None)
    return out


class Splitter:
    def __init__(self, outdir, live=None, cut=True, max_bytes=None, keep=None):
        self.outdir = Path(outdir)
        self.live = live                # None: decide from the first lines
        self.cut = cut
        self.max_bytes = max_bytes
        self.keep = keep                # --grep: only this subsystem, to stdout
        self.files = {}
        self.counts = {}
        self.anchor = None
        self.seen_bytes = 0
        self.ended = None               # why the current boot ended (ramdump)
        self.banners = 0
        self.last_status = {}           # subsystem -> (seq, why, t, text)
        self.procs = {}
        self.hkl = {}                   # program -> (lines, set of pids)
        self.pending = b''
        if keep is None:
            self.outdir.mkdir(parents=True, exist_ok=True)

    def _file(self, rel):
        f = self.files.get(rel)
        if f is None:
            p = self.outdir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            f = self.files[rel] = open(p, 'a', encoding='utf-8', errors='replace')
        return f

    def _write(self, rel, line):
        self.counts[rel] = self.counts.get(rel, 0) + 1
        if self.keep is not None:
            if rel == self.keep + '.log' or rel == self.keep:
                sys.stdout.write(line)
            return
        self._file(rel).write(line)

    def feed_bytes(self, data, final=False):
        data = self.pending + data
        lines = data.split(b'\n')
        self.pending = b'' if final else lines.pop()
        for raw in lines:
            if self.ended is not None:
                return
            self.seen_bytes += len(raw) + 1
            self.feed_line(raw.replace(b'\x00', b'').decode('utf-8', 'replace').rstrip('\r'))
            if self.max_bytes is not None and self.seen_bytes >= self.max_bytes and self.cut:
                self.ended = f'--max-bytes {self.max_bytes}'

    def feed_line(self, line):
        if not line.strip():
            return
        m = LIVE_STAMP.match(line)
        if self.live is None:
            self.live = bool(m)
        if self.live and m:
            stamp, text = m.group(1), m.group(2)
        else:
            text = line
            stamp = None
        if not self.live and self.cut and BANNER.search(text):
            self.banners += 1
            if self.banners > 1:
                self.ended = 'second XNU banner (an older boot)'
                return
        for rx, scale in ANCHORS:
            a = rx.match(text)
            if a:
                self.anchor = int(a.group(1)) * scale
        if stamp is None:
            stamp = f't>={self.anchor:.0f}s' if self.anchor is not None else 't>=?'
        out = f'[{stamp}] {text}\n'
        subs, prog = classify(text)
        self._write('all.log', out)
        for s in subs:
            self._write(f'{s}.log', out)
        if prog:
            self._write(f'hkl/{SAFE_NAME.sub("_", prog)}.log', out)
            n, pids = self.hkl.get(prog, (0, set()))
            pids.add(program_of(text)[1])
            self.hkl[prog] = (n + 1, pids)
        if not subs and not prog:
            self._write('other.log', out)
        st = STATUS_LINE.match(text)
        if st:
            seq, why, t, sub, body = st.groups()
            if sub == 'proc':
                self.procs.update(parse_proc(body))
            else:
                self.last_status[sub] = (int(seq), why, int(t), body)
        if not self.live and self.cut and text.startswith('panic('):
            self.ended = 'panic line (the end of this boot; what follows is older)'

    def summary(self):
        lines = [f'hklog summary, {time.strftime("%Y-%m-%d %H:%M:%S")}', '']
        lines.append(f'input: {"live stream" if self.live else "ramdump/raw"}; {self.seen_bytes} bytes read'
                     + (f'; stopped: {self.ended}' if self.ended else ''))
        lines.append('')
        lines.append('lines per file:')
        for k in sorted(self.counts):
            lines.append(f'  {k:28} {self.counts[k]}')
        lines.append('')
        lines.append('last HKOBS status per subsystem:')
        for k in ('wifi', 'fw', 'bt', 'usb', 'con'):
            if k in self.last_status:
                seq, why, t, body = self.last_status[k]
                lines.append(f'  {k:5} #{seq} {why} t={t}: {body}')
        if self.procs:
            lines.append('')
            lines.append('programs with hk_env variables (last HKOBS proc lines): respawns = execs - 1')
            lines.append(f'  {"program":24} {"execs":>5} {"exits":>5} {"respawns":>8} {"last":>5} {"HKL lines":>9} {"dropped":>7}')
            for name, (e, x, last, ln, dr) in sorted(self.procs.items(), key=lambda kv: (-kv[1][0], kv[0])):
                lines.append(f'  {name:24} {e:5} {x:5} {max(e - 1, 0):8} {last:>5} {"" if ln is None else ln:>9} {"" if dr is None else dr:>7}')
        if self.hkl:
            lines.append('')
            lines.append('HKL lines seen here, per program (pids):')
            for name, (n, pids) in sorted(self.hkl.items(), key=lambda kv: -kv[1][0]):
                lines.append(f'  {name:24} {n:7}  pids {",".join(sorted(pids, key=int))}')
        return '\n'.join(lines) + '\n'

    def flush(self, write_summary=True):
        for f in self.files.values():
            f.flush()
        if write_summary and self.keep is None:
            tmp = self.outdir / 'summary.txt.tmp'
            tmp.write_text(self.summary())
            os.replace(tmp, self.outdir / 'summary.txt')

    def close(self):
        if self.pending:
            self.feed_bytes(b'', final=True)
        self.flush()
        for f in self.files.values():
            f.close()
        self.files.clear()


def follow(path, sp, poll=0.2, idle_exit=None, from_end=False, sleep=time.sleep, clock=time.monotonic, stop=None):
    """Read a growing file (or a pipe) as it grows. Ends on Ctrl-C, EOF of a pipe, idle_exit seconds with nothing new,
    or when stop() says so. A file that shrinks (a new run) is read again from its start."""
    last_new = clock()
    last_summary = clock()
    if path == '-':
        fd = sys.stdin.buffer
        while True:
            chunk = fd.read1(65536) if hasattr(fd, 'read1') else fd.read(65536)
            if not chunk:
                return 'end of input'
            sp.feed_bytes(chunk)
            if clock() - last_summary >= 10:
                sp.flush()
                last_summary = clock()
    while not os.path.exists(path):
        if idle_exit is not None and clock() - last_new >= idle_exit:
            return 'input never appeared'
        if stop is not None and stop():
            return 'stopped'
        sleep(poll)
    f = open(path, 'rb')
    pos = os.path.getsize(path) if from_end else 0
    f.seek(pos)
    while True:
        chunk = f.read(65536)
        if chunk:
            pos += len(chunk)
            sp.feed_bytes(chunk)
            last_new = clock()
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            size = pos
        if size < pos:
            f.close()
            f = open(path, 'rb')
            pos = 0
            sp.pending = b''
            continue
        if clock() - last_summary >= 10:
            sp.flush()
            last_summary = clock()
        if idle_exit is not None and clock() - last_new >= idle_exit:
            f.close()
            return f'idle {idle_exit} s'
        if stop is not None and stop():
            f.close()
            return 'stopped'
        sleep(poll)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('input', help="kernel.log, console.txt, usbcon.log, or '-' for stdin")
    p.add_argument('-o', '--out', help='output directory (default <input>.hklog)')
    p.add_argument('--follow', action='store_true', help='keep reading as the input grows (live stream)')
    p.add_argument('--from-end', action='store_true', help='with --follow: start at the current end of the file')
    p.add_argument('--idle-exit', type=float, help='with --follow: stop after this many seconds with nothing new')
    p.add_argument('--whole', action='store_true', help='ramdump: do not stop at the first panic / second banner')
    p.add_argument('--max-bytes', type=int, help="ramdump: stop after this many bytes (reader.txt's console zone 'used=')")
    p.add_argument('--live', choices=('auto', 'yes', 'no'), default='auto', help="input has 'HH:MM:SS.mmm ' stamps")
    p.add_argument('--grep', metavar='SUBSYSTEM', help='print one file\'s lines (wifi, bt, ..., or hkl/<prog>.log) to stdout, write nothing')
    a = p.parse_args(argv)
    out = a.out or (f'hklog-{time.strftime("%Y%m%d-%H%M%S")}' if a.input == '-' else a.input + '.hklog')
    live = {'auto': None, 'yes': True, 'no': False}[a.live]
    sp = Splitter(out, live=live, cut=not a.whole, max_bytes=a.max_bytes, keep=a.grep)
    why = 'end of file'
    try:
        if a.follow:
            why = follow(a.input, sp, idle_exit=a.idle_exit, from_end=a.from_end)
        else:
            with (sys.stdin.buffer if a.input == '-' else open(a.input, 'rb')) as f:
                while sp.ended is None:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    sp.feed_bytes(chunk)
    except KeyboardInterrupt:
        why = 'interrupted'
    sp.close()
    if a.grep is None:
        print(f'hklog: {out}: {sum(v for k, v in sp.counts.items() if k == "all.log")} lines ({why}'
              + (f'; boot ended: {sp.ended}' if sp.ended else '') + ')', file=sys.stderr)
        print(sp.summary(), end='', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
