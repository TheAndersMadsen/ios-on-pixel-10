#!/usr/bin/env python3
"""Run a UI test script against a live boot started by tools/live_boot.sh. Runs on m1box; never opens USB.

    python3 -I tools/ui_run.py <live_boot run dir> ui/settings_about_phone.ui
    tools/live_boot.sh <boot.img> <name> --wait 1080 --sync-tools --ui-script ui/settings_about_phone.ui   # all in one

Every action goes to the running usbcon reader on the Mac (LIVE_SOCK in live.env) via `mac -- python tools/usbcon.py
--control-socket ...`; screenshots are the reader's framebuffer snapshots (blazer_usbcon_snap=1 or hk_dbg bit 1), copied
back to <run>/ui/. Coordinates are CANVAS pixels (1125x2511 on the phone; snapshot pixel x step = canvas pixel).

Script (one command per line, '#' comments, key=value options; research/ios26-phaseb-r1/live/uidrive/UIDRIVE.md):
    wait_home [timeout=S] [unlock=yes|no]           the wait_home rule (UIDRIVE.md section 0)
    tap X Y [hold=MS] [expect=change|same|any] [app=NAME] [settle=S] [verify=S] [retry=0|1] [edge=ok]
    tap_text "TEXT" [fallback=X,Y] [nth=N] [region=top|bottom|all] + tap options   (tesseract OCR on a step-6 snapshot)
    check_text "TEXT" [region=...]                  OCR check only, no input
    swipe X Y X2 Y2 [ms=300] [expect=...] [settle=S]
    home [settle=S]  |  key power|volup|voldown|home [settle=S]
    wait_app NAME [timeout=S]                       console: launchd spawn of UIKitApplication:com.apple.NAME or "exec NAME"
    shot NAME  |  sleep S  |  mark TEXT
Options on any line: on_fail=stop|continue (default continue; --stop-on-fail flips the default).

Each step logs one STEP line (verdict, receipt, change fraction, PNG) to <run>/ui_run.log and the live_boot markers, and
<run>/ui_run.json + ui_run.md get the full record. At the end the stack sampler and crash output of the whole boot is
collected from console.txt into <run>/ustack.txt and <run>/crashes.txt.

Reliability rules (UIDRIVE.md section 3): a tap waits for a stable screen first, is refused inside the 52 px edge band
(the kernel would mark it FromEdgeTip, a system gesture) unless edge=ok, and is verified by polling snapshots for up to
verify=S seconds (compositor stalls of several seconds were seen in p31r1). Clean refusals (rate, busy, notready) are
retried; ambiguous receipts never. retry=1 allows one recorded recovery (HOME, then the same tap) after a dispatched tap
whose expected change or app never came.

Exit 0: every step PASS; 1: a step failed; 2: setup problem (no live.env, never ready).
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import signal
import struct
import subprocess
import sys
import time
import zlib

PB = Path(os.environ.get('LIVE_PB', Path.home() / '.local/share/phone-bridge/bin'))
RETRY_ERRORS = ('rate', 'busy', 'notready', 'local request expired before action', 'arm generation/phase mismatch')
CANVAS = (1125, 2511)
EDGE = 52                   # SWEET_TOUCH_EDGE_PX 59 panel px x 1125/1280, rounded up
SNAP_STEP = 8               # 141x314 (88.5 KB): `shot` evidence and the wait_home picture
POLL_STEP = 16              # 70x157 (22 KB): pre/after/ready polls. The reader moves ~8.5 KB/s over EP0 (int4-confirm:
                            # 9.1..10.6 s per step-8 snapshot), so a step-16 poll costs ~2.6 s instead of ~10.5 s
OCR_STEP = 6                # 188x419: the finest step that fits the kernel's 160 KiB buffer
OCR_SCALE = 4               # bilinear upscale for tesseract (nearest-neighbour blocks read as noise)
CHANGE_MIN = 0.02           # fraction of pixels for "the screen changed"
STABLE_MAX = 0.01           # and for "the screen is still"
LIT_MIN = 0.05              # fraction of pixels with luma > 32 for "something is on the glass"
LIT_MOVING_S = 60           # lit but never still this long: go on anyway (an animated screen)
HOME_TIMEOUT_T0 = 840       # seconds after LIVE_T0: inside the image's 900 s deadline
QUIET_S = 20
UNLOCK_SWIPE = (562, 2490, 562, 1300, 300)

# console.txt is "<HH:MM:SS.mmm> [ uptime] <line>" (live_boot's stamp + usbcon's prefix)
RX = dict(
    touch=re.compile(r'SWEET HID: SweetHIDTouch open by'),
    buttons=re.compile(r'SWEET HID: SweetHIDButtons open by'),
    springboard=re.compile(r'\bexec SpringBoard\b|Successfully spawned \(?SpringBoard\)?\['),
    frames=re.compile(r'HK TOP: t=\d+ frames\+([1-9]\d*)|SWEET FB: rate swaps ([1-9][\d.]*|0\.\d*[1-9]\d*)/s'),
    ui_crash=re.compile(r'\bCRASH (SpringBoard|backboardd)\b|\(user/501/com\.apple\.(SpringBoard|backboardd) \[\d+\]\) <Notice>: exited due to|\[system/com\.apple\.(backboardd)'
                        r' \[\d+\]\) <Notice>: exited due to'),
    crash=re.compile(r'\bCRASH (\S+)|usertrap: (\S+)|exited due to (SIG\w+|exit\([1-9]\d*\))'),
    live_done=re.compile(r'HK LIVE done gen=(\d+) result=(\d+)'),
    ustack=re.compile(r'HK USTACK'),
    panic=re.compile(r'panic\(|blazer-root: deadline'),
    # Hands on the phone: real panel touches (the injected ones log only "HK LIVE dispatch") and the physical buttons.
    # int4-confirm 03:46:13: volume down + power held 10 s gave the power-off/Emergency SOS screen mid-walk.
    physical=re.compile(r'\btcm: finger \d+ down|blazer-keys: volume (?:up|down) pressed|blazer-power-key: pressed'),
)


def app_rx(name):
    n = re.escape(name)
    return re.compile(rf'UIKitApplication:com\.apple\.{n}\[\w+\]\[[\w-]+\] \[\d+\]\) <Notice>: (Successfully spawned|service spawned)|\bexec {n}\b')


def read_env(path):
    path = Path(path)
    env_file = path / 'live.env' if path.is_dir() else path
    env = {}
    for line in env_file.read_text().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            env[k] = v
    return env


def parse_script(text):
    """[(lineno, cmd, args, opts)]. Raises ValueError with the line number."""
    steps = []
    arity = dict(wait_home=0, tap=2, tap_text=1, check_text=1, swipe=4, home=0, key=1, wait_app=1, shot=1, sleep=1, mark=None)
    for no, raw in enumerate(text.splitlines(), 1):
        try:
            words = shlex.split(raw, comments=True)
        except ValueError as exc:
            raise ValueError(f'line {no}: {exc}')
        if not words:
            continue
        cmd, rest = words[0], words[1:]
        if cmd not in arity:
            raise ValueError(f'line {no}: unknown command {cmd!r}')
        args = [w for w in rest if '=' not in w]
        opts = dict(w.split('=', 1) for w in rest if '=' in w)
        if cmd == 'mark':
            args = [' '.join(rest)]
            opts = {}
        n = arity[cmd]
        if n is not None and len(args) != n:
            raise ValueError(f'line {no}: {cmd} takes {n} argument(s), got {args}')
        if cmd in ('tap', 'swipe'):
            try:
                args = [int(a) for a in args]
            except ValueError:
                raise ValueError(f'line {no}: {cmd} coordinates must be integers')
        if cmd == 'sleep':
            args = [float(args[0])]
        if cmd == 'key' and args[0] not in ('power', 'volup', 'voldown', 'home'):
            raise ValueError(f'line {no}: key must be power, volup, voldown or home')
        if cmd == 'shot' and not re.fullmatch(r'[A-Za-z0-9_-]{1,24}', args[0]):
            raise ValueError(f'line {no}: shot name must be 1..24 of [A-Za-z0-9_-]')
        bad = set(opts) - {'timeout', 'unlock', 'hold', 'expect', 'app', 'settle', 'verify', 'retry', 'edge', 'fallback', 'nth',
                           'region', 'ms', 'on_fail'}
        if bad:
            raise ValueError(f'line {no}: unknown option(s) {sorted(bad)}')
        if opts.get('expect', 'change') not in ('change', 'same', 'any'):
            raise ValueError(f'line {no}: expect must be change, same or any')
        if opts.get('on_fail', 'continue') not in ('stop', 'continue'):
            raise ValueError(f'line {no}: on_fail must be stop or continue')
        steps.append((no, cmd, args, opts))
    return steps


def edge_band(x, y, canvas=CANVAS):
    w, h = canvas
    return x < EDGE or x > w - 1 - EDGE or y < EDGE or y > h - 1 - EDGE


def rgb565_stats(prev, cur):
    """(changed fraction vs prev or None, lit fraction)."""
    px = struct.unpack(f'<{len(cur) // 2}H', cur)
    lit = 0
    for p in px:
        r, g, b = (p >> 11) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31
        if (r * 3 + g * 6 + b) // 10 > 32:
            lit += 1
    if prev is None or len(prev) != len(cur):
        return None, lit / len(px)
    q = struct.unpack(f'<{len(prev) // 2}H', prev)
    n = 0
    for a, b in zip(q, px):
        if a != b and (abs((a >> 11) - (b >> 11)) > 3 or abs(((a >> 5) & 63) - ((b >> 5) & 63)) > 7 or abs((a & 31) - (b & 31)) > 3):
            n += 1
    return n / len(px), lit / len(px)


def luma(raw, w, h):
    px = struct.unpack(f'<{w * h}H', raw)
    return [(((p >> 11) * 255 // 31) * 3 + (((p >> 5) & 63) * 255 // 63) * 6 + (p & 31) * 255 // 31) // 10 for p in px]


def upscale(gray, w, h, scale):
    """Bilinear upscale (separable: rows, then columns). Returns the scaled rows as bytes."""
    def taps(n):
        out = []
        for i in range(n * scale):
            f = min(max((i + 0.5) / scale - 0.5, 0.0), n - 1.0)
            a = int(f)
            b = min(a + 1, n - 1)
            out.append((a, b, f - a))
        return out
    tx, ty = taps(w), taps(h)
    wide = []
    for y in range(h):
        row = gray[y * w:(y + 1) * w]
        wide.append([row[a] + (row[b] - row[a]) * t for a, b, t in tx])
    rows = []
    for a, b, t in ty:
        ra, rb = wide[a], wide[b]
        rows.append(bytes(int(u + (v - u) * t) for u, v in zip(ra, rb)))
    return rows


def gray_png(raw, w, h, scale):
    """Grayscale PNG of an RGB565 frame for tesseract (no PIL on m1box): bilinear upscale, and dark text on a light
    ground (a dark-mode screen is inverted). Nearest-neighbour blocks of a step-6 frame OCR as noise (int2-ui Wi-Fi page:
    nothing; bilinear x4: "Wi-Fl", "edit", "General")."""
    gray = luma(raw, w, h)
    if sum(gray) / len(gray) < 128:
        gray = [255 - v for v in gray]
    rows = [b'\0' + r for r in upscale(gray, w, h, scale)]

    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w * scale, h * scale, 8, 0, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b''.join(rows), 6)) + chunk(b'IEND', b''))


OCR_CONFUSIONS = str.maketrans({'l': 'i', '1': 'i', '|': 'i', '!': 'i', '0': 'o', '5': 's', '8': 'b'})


def ocr_norm(word):
    return word.lower().strip('.,:;>_—-\'"`').translate(OCR_CONFUSIONS)


def near(a, b):
    """OCR-tolerant word match: equal after normalising look-alike glyphs, or one edit apart for words of 5+ letters."""
    a, b = ocr_norm(a), ocr_norm(b)
    if a == b:
        return True
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 1


def ocr_words(png_path, tesseract='tesseract'):
    """[(text, left, top, width, height, conf, line_key)] from tesseract's TSV, in the PNG's pixels."""
    r = subprocess.run([tesseract, str(png_path), '-', '--psm', '11', 'tsv'], capture_output=True, text=True, timeout=60)
    words = []
    for row in r.stdout.splitlines()[1:]:
        f = row.split('\t')
        if len(f) == 12 and f[11].strip():
            words.append((f[11].strip(), int(f[6]), int(f[7]), int(f[8]), int(f[9]), float(f[10]), (f[2], f[3], f[4])))
    return words


def find_text(words, text, region='all', height=None):
    """Centres (x, y) of every match of text (one or more words, case-insensitive, adjacent on one OCR line)."""
    want = text.lower().split()
    hits = []
    for i in range(len(words)):
        seq = words[i:i + len(want)]
        if len(seq) == len(want) and all(near(w[0], t) for w, t in zip(seq, want)) and \
                len({w[6] for w in seq}) == 1:
            left, top = seq[0][1], min(w[2] for w in seq)
            right, bottom = seq[-1][1] + seq[-1][3], max(w[2] + w[4] for w in seq)
            cx, cy = (left + right) / 2, (top + bottom) / 2
            if height and region == 'top' and cy > height / 2 or height and region == 'bottom' and cy < height / 2:
                continue
            hits.append((cx, cy))
    return sorted(hits, key=lambda p: p[1])


class Stopped(Exception):
    pass


def on_term(_signum, _frame):
    raise Stopped()


class MacClient:
    """usbcon client calls on the Mac, through the running reader's socket. Replaceable in tests."""

    def __init__(self, env, python):
        self.env, self.python = env, python

    def call(self, *argv, timeout=60):
        cmd = [str(PB / 'mac'), '--cd', self.env['LIVE_MAC_DIR'], '--', self.python, '-I', 'tools/usbcon.py',
               '--control-socket', self.env['LIVE_SOCK'], *argv]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return dict(state='unknown', error='client timeout', ambiguous=True)
        text = r.stdout.strip() or r.stderr.strip()
        try:
            return json.loads(text[text.index('{'):])
        except ValueError:
            return dict(state='unknown', error=f'unreadable receipt: {text[-300:]}', ambiguous=True)

    def fetch(self, mac_paths, dest):
        args = [str(PB / 'mac'), '--cd', self.env['LIVE_MAC_DIR']]
        for p in mac_paths:
            args += ['--get', p]
        subprocess.run(args + ['--', 'true'], cwd=dest, capture_output=True, timeout=120)


class Runner:
    def __init__(self, args, env, client, clock=time.time, sleep=time.sleep):
        self.args, self.env, self.client, self.clock, self.sleep = args, env, client, clock, sleep
        self.run = Path(env['LIVE_RUN'])
        self.console_path = Path(env.get('LIVE_CONSOLE', self.run / 'console.txt'))
        self.t0 = float(env.get('LIVE_T0', clock()))
        self.ui = self.run / 'ui'
        self.ui.mkdir(exist_ok=True)
        self.log = open(self.run / 'ui_run.log', 'a', buffering=1)
        self.steps, self.shots = [], []
        self.snap_ok, self.prev_raw, self.nshot = not args.no_snap, None, 0
        self.prev_by_step = {}           # baseline per snapshot step: frames of different steps never compare
        self.poll_step = int(getattr(args, 'poll_step', POLL_STEP) or POLL_STEP)
        self.physical_seen = 0           # console offset up to which physical input has been reported
        self.physical = []
        self.snap_fails = 0
        self.capabilities, self.canvas = [], list(CANVAS)
        self.last_action = 0.0

    # --- evidence
    def say(self, text):
        now = self.clock()
        line = f'UIRUN {time.strftime("%H:%M:%S", time.localtime(now))}.{int(now % 1 * 1000):03d} +{now - self.t0:.1f} {text}'
        print(line, flush=True)
        self.log.write(line + '\n')
        if self.env.get('LIVE_MARKERS'):
            with open(self.env['LIVE_MARKERS'], 'a') as m:
                m.write(line + '\n')

    def console(self, start=0):
        try:
            with open(self.console_path, 'rb') as f:
                f.seek(start)
                data = f.read()
        except OSError:
            return [], start
        return data.decode(errors='replace').splitlines(), start + len(data)

    def console_end(self):
        try:
            return self.console_path.stat().st_size
        except OSError:
            return 0

    def grep(self, rx, start=0):
        lines, _ = self.console(start)
        return [l for l in lines if rx.search(l)]

    # --- device
    def status(self):
        s = self.client.call('--input-status')
        if s.get('state') == 'status':
            self.capabilities, self.canvas = s.get('capabilities', []), s.get('canvas') or list(CANVAS)
        return s

    def act(self, name, *argv):
        """An input action. Retries only clean refusals; never an ambiguous one."""
        for attempt in range(1, 5):
            gap = self.clock() - self.last_action
            if gap < 0.3:
                self.sleep(0.3 - gap)
            t = self.clock()
            receipt = self.client.call(*argv)
            self.last_action = self.clock()
            state = receipt.get('state')
            self.say(f'ACTION {name} {" ".join(argv)} -> {state} {receipt.get("error", "")}'.rstrip())
            if state == 'dispatched':
                return dict(state=state, t=t, attempts=attempt, receipt=receipt)
            retry = state == 'refused' and not receipt.get('ambiguous') and any(e in receipt.get('error', '') for e in RETRY_ERRORS)
            if not retry or attempt == 4:
                return dict(state=state, t=t, attempts=attempt, receipt=receipt)
            self.sleep(1.0)

    def snapshot(self, name, step=SNAP_STEP, baseline=True):
        """Take, fetch and measure one snapshot. Returns meta (with raw bytes in meta['_raw']) or None."""
        if not self.snap_ok:
            return None
        self.nshot += 1
        label = re.sub(r'[^A-Za-z0-9_-]', '-', f'{self.nshot:03d}-{name}')[:32]
        r = self.client.call('--snapshot', '--snap-name', label, '--snap-step', str(step))
        if r.get('state') != 'snapshot':
            self.say(f'SNAPSHOT {label} unavailable: {r.get("error", r.get("state"))}')
            self.snap_fails += 1
            # "unavailable" (a flipped client surface) can pass; an unsupported kernel or three in a row cannot.
            if 'unsupported' in str(r.get('error', '')) or 'pipe' in str(r.get('error', '')).lower() or self.snap_fails >= 3:
                self.snap_ok = False
                self.say('NOTE no snapshots on this boot: steps are judged on receipts and console evidence only')
            return None
        self.snap_fails = 0
        meta = dict(r['snapshot'])
        png = meta['png']
        self.client.fetch([png, png[:-4] + '.rgb565'], self.ui)
        local = self.ui / Path(png).name
        raw_path = Path(str(local)[:-4] + '.rgb565')
        try:
            raw = raw_path.read_bytes()
        except OSError:
            self.say(f'SNAPSHOT {label} taken on the Mac ({png}) but not copied back')
            return None
        meta.update(name=name, label=label, local_png=str(local) if local.exists() else None, _raw=raw, t=self.clock())
        prev = self.prev_by_step.get(step) if baseline else None
        meta['changed'], meta['lit'] = rgb565_stats(prev, raw)
        if baseline:
            self.prev_by_step[step] = raw
            if step == SNAP_STEP:
                self.prev_raw = raw
            self.shots.append({k: v for k, v in meta.items() if k != '_raw'})
        return meta

    def stable(self, timeout=10.0):
        """Wait for two consecutive snapshots that differ by less than STABLE_MAX. Returns the last meta (or None)."""
        end = self.clock() + timeout
        last = self.snapshot('pre', step=self.poll_step)
        while last and self.clock() < end:
            if last['changed'] is not None and last['changed'] < STABLE_MAX:
                return last
            self.sleep(2.0)
            last = self.snapshot('pre', step=self.poll_step)
        return last

    # --- steps
    def record(self, no, cmd, args, opts, ok, **detail):
        r = dict(line=no, cmd=cmd, args=args, opts=opts, verdict='PASS' if ok else 'FAIL', **detail)
        self.steps.append(r)
        png = detail.get('png') or ''
        ch = detail.get('changed')
        self.say(f'STEP {len(self.steps):02d} line {no} {cmd} {" ".join(map(str, args))} {r["verdict"]} '
                 f'state={detail.get("state", "-")} changed={"n/a" if ch is None else f"{ch:.3f}"} '
                 f'crashes={len(detail.get("crashes", []))} {png}'.rstrip())
        return ok

    def after(self, start, expect, settle, verify, baseline_raw, app=None):
        """Wait settle, then poll snapshots (vs baseline_raw) until the expectation holds or verify s pass."""
        self.sleep(settle)
        end = self.clock() + verify
        app_hits = []
        meta = None
        while True:
            if app:
                app_hits = self.grep(app_rx(app), start)
            meta = self.snapshot('after', step=self.poll_step)
            changed = None
            if meta is not None and baseline_raw is not None:
                changed, _ = rgb565_stats(baseline_raw, meta['_raw'])
            seen = (expect == 'any' or changed is None or (changed >= CHANGE_MIN) == (expect == 'change'))
            if app:
                # a resident app comes back without a new launch line: the launch line or a screen change will do;
                # without snapshots only the launch line counts.
                seen = bool(app_hits) or (changed is not None and changed >= CHANGE_MIN)
            if seen or self.clock() >= end:
                return meta, changed, seen, app_hits
            self.sleep(3.0)

    def touch_step(self, no, cmd, args, opts, argv, x, y):
        expect = opts.get('expect', 'change')
        settle = float(opts.get('settle', 2))
        verify = float(opts.get('verify', 15))
        app = opts.get('app')
        if cmd != 'swipe' and edge_band(x, y, self.canvas) and opts.get('edge') != 'ok':
            return self.record(no, cmd, args, opts, False, state='refused-local',
                               error=f'{x},{y} is inside the {EDGE} px edge band (FromEdgeTip: a system gesture); add edge=ok')
        tries = 1 + int(opts.get('retry', 0))
        for attempt in range(tries):
            pre = self.stable() if cmd != 'swipe' else self.snapshot('pre', step=self.poll_step)
            baseline = pre['_raw'] if pre else self.prev_by_step.get(self.poll_step)
            start = self.console_end()
            r = self.act(cmd, *argv)
            if r['state'] != 'dispatched':
                return self.record(no, cmd, args, opts, False, state=r['state'], receipt=r['receipt'], attempts=r['attempts'])
            meta, changed, seen, app_hits = self.after(start, expect, settle, verify, baseline, app)
            physical = self.grep(RX['physical'], start)
            ok = seen and not physical
            detail = dict(state='dispatched' if not physical else 'INTERFERED (physical input during the step)',
                          receipt=r['receipt'], attempts=r['attempts'], changed=changed,
                          app=app_hits[:3], png=meta and meta.get('local_png'), crashes=self.grep(RX['crash'], start)[:20],
                          live_done=self.grep(RX['live_done'], start)[:4], recovery=attempt, physical=physical[:6])
            if physical:
                return self.record(no, cmd, args, opts, False, **detail)
            if ok or attempt == tries - 1:
                return self.record(no, cmd, args, opts, ok, **detail)
            self.say(f'RECOVERY line {no}: dispatched {cmd} without the expected {"app " + app if app else "change"}: HOME, then the same {cmd} once')
            self.act('recovery-home', '--home')
            self.sleep(3)

    def ocr(self, region):
        meta = self.snapshot('ocr', step=OCR_STEP, baseline=False)
        if not meta:
            return None, []
        scale = OCR_SCALE
        png = self.ui / f'{meta["label"]}-gray.png'
        png.write_bytes(gray_png(meta['_raw'], meta['width'], meta['height'], scale))
        words = ocr_words(png, self.args.tesseract)
        meta['scale'] = scale
        return meta, words

    def text_point(self, text, opts):
        meta, words = self.ocr(opts.get('region', 'all'))
        if not meta:
            return None, 'no snapshot for OCR'
        hits = find_text(words, text, opts.get('region', 'all'), meta['height'] * meta['scale'])
        nth = int(opts.get('nth', 1))
        if len(hits) < nth:
            seen = ' '.join(w[0] for w in words)[:200]
            return None, f'"{text}" not found by OCR (saw: {seen})'
        cx, cy = hits[nth - 1]
        kx = meta['src_w'] / meta['width'] / meta['scale']
        ky = meta['src_h'] / meta['height'] / meta['scale']
        return (int(cx * kx), int(cy * ky)), f'OCR {len(hits)} match(es), using #{nth}'

    def wait_home(self, no, args, opts):
        deadline = self.t0 + float(opts.get('timeout', self.args.home_timeout))
        need = ('touch', 'buttons', 'springboard', 'frames')
        missing = list(need)
        while self.clock() < deadline:
            lines, _ = self.console()
            missing = [k for k in need if not any(RX[k].search(l) for l in lines)]
            if not missing:
                break
            if any(RX['panic'].search(l) for l in lines):
                return self.record(no, 'wait_home', args, opts, False, state='NOT_READY panic/deadline in the console')
            self.sleep(2)
        else:
            return self.record(no, 'wait_home', args, opts, False, state=f'NOT_READY console: {",".join(missing)}')
        self.say('HOME console conditions met (touch, buttons, SpringBoard, frames)')
        # quiet: no SpringBoard/backboardd crash for QUIET_S
        quiet_from = self.clock()
        mark = self.console_end()
        while self.clock() - quiet_from < QUIET_S and self.clock() < deadline:
            self.sleep(2)
            if self.grep(RX['ui_crash'], mark):
                self.say('HOME SpringBoard/backboardd crashed: quiet window restarts')
                quiet_from, mark = self.clock(), self.console_end()
        s = self.status()
        if s.get('state') == 'status':
            self.say(f'STATUS capabilities={",".join(self.capabilities)} canvas={self.canvas}')
            while not {'touch_client', 'button_client'} <= set(self.capabilities) and self.clock() < deadline:
                self.sleep(3)
                self.status()
        else:
            self.say(f'STATUS {s.get("state")} {s.get("error", "")}: no live input on this boot')
            return self.record(no, 'wait_home', args, opts, False, state='NOT_READY no live input', receipt=s)
        if not self.screen_ready(deadline):
            return self.record(no, 'wait_home', args, opts, False, state='NOT_READY screen dark or never still')
        if opts.get('unlock', 'yes') == 'yes':
            x, y, x2, y2, ms = UNLOCK_SWIPE
            if 'swipe' in self.capabilities:
                self.act('unlock-swipe', '--swipe', str(x), str(y), str(x2), str(y2), '--ms', str(ms))
                self.sleep(3)
            self.act('unlock-home', '--home')
            self.sleep(3)
            if not self.screen_ready(deadline):
                return self.record(no, 'wait_home', args, opts, False, state='NOT_READY screen after unlock')
        meta = self.snapshot('home')
        verdict = 'HOME' if self.snap_ok else 'HOME_NOSNAP'
        return self.record(no, 'wait_home', args, opts, True, state=verdict, png=meta and meta.get('local_png'),
                           lit=meta and meta.get('lit'))

    def screen_ready(self, deadline):
        if not self.snap_ok:
            self.sleep(20)
            return True
        lit_since = None
        while self.clock() < deadline:
            a = self.snapshot('ready', step=self.poll_step)
            if not self.snap_ok:
                self.sleep(20)
                return True
            if a and a['lit'] >= LIT_MIN:
                lit_since = lit_since or self.clock()
                self.sleep(5)
                b = self.snapshot('ready', step=self.poll_step)
                if b and b['lit'] >= LIT_MIN and b['changed'] is not None and b['changed'] < STABLE_MAX:
                    return True
                if self.clock() - lit_since >= LIT_MOVING_S:
                    self.say(f'NOTE screen lit but never still for {LIT_MOVING_S} s (animation?): going on')
                    return True
            else:
                lit_since = None
            self.sleep(3)
        return False

    def step(self, no, cmd, args, opts):
        if cmd == 'wait_home':
            return self.wait_home(no, args, opts)
        if cmd == 'sleep':
            self.sleep(args[0])
            return self.record(no, cmd, args, opts, True)
        if cmd == 'mark':
            self.say(f'MARK {args[0]}')
            return True
        if cmd == 'shot':
            meta = self.snapshot(args[0])
            return self.record(no, cmd, args, opts, meta is not None or not self.snap_ok, png=meta and meta.get('local_png'),
                               changed=meta and meta.get('changed'), state='snapshot' if meta else 'no snapshot')
        if cmd == 'wait_app':
            end = self.clock() + float(opts.get('timeout', 30))
            while self.clock() < end:
                hits = self.grep(app_rx(args[0]))
                if hits:
                    return self.record(no, cmd, args, opts, True, app=hits[:3])
                self.sleep(1)
            return self.record(no, cmd, args, opts, False, state='no launch line')
        if cmd in ('home', 'key'):
            argv = ['--home'] if cmd == 'home' else ['--key', args[0]]
            pre = self.prev_by_step.get(self.poll_step)
            start = self.console_end()
            r = self.act(cmd, *argv)
            self.sleep(float(opts.get('settle', 3)))
            meta = self.snapshot(cmd, step=self.poll_step)
            changed = rgb565_stats(pre, meta['_raw'])[0] if meta and pre else None
            physical = self.grep(RX['physical'], start)
            return self.record(no, cmd, args, opts, r['state'] == 'dispatched' and not physical,
                               state=r['state'] if not physical else 'INTERFERED (physical input during the step)',
                               receipt=r['receipt'], changed=changed, png=meta and meta.get('local_png'),
                               crashes=self.grep(RX['crash'], start)[:20], physical=physical[:6])
        if cmd == 'tap':
            x, y = args
            argv = ['--tap', str(x), str(y)] + (['--hold', opts['hold']] if 'hold' in opts else [])
            return self.touch_step(no, cmd, args, opts, argv, x, y)
        if cmd == 'swipe':
            x, y, x2, y2 = args
            return self.touch_step(no, cmd, args, opts, ['--swipe', str(x), str(y), str(x2), str(y2), '--ms', opts.get('ms', '300')], x, y)
        if cmd in ('tap_text', 'check_text'):
            point, why = self.text_point(args[0], opts)
            self.say(f'OCR "{args[0]}": {point} ({why})')
            if cmd == 'check_text':
                return self.record(no, cmd, args, opts, point is not None, state=why)
            if point is None and 'fallback' in opts:
                point = tuple(int(v) for v in opts['fallback'].split(','))
                self.say(f'OCR fallback {point}')
            if point is None:
                return self.record(no, cmd, args, opts, False, state=why)
            argv = ['--tap', str(point[0]), str(point[1])] + (['--hold', opts['hold']] if 'hold' in opts else [])
            return self.touch_step(no, cmd, args + [f'{point[0]},{point[1]}'], opts, argv, *point)
        raise AssertionError(cmd)

    def main(self, steps):
        self.say(f'START {len(steps)} steps, socket {self.env.get("LIVE_SOCK")} run {self.run}')
        rc = 0
        try:
            rc = self.walk(steps)
        except Stopped:
            self.say('STOPPED by SIGTERM (live_boot: the boot ended before the walk finished)')
            rc = 1
        return self.finish(rc)

    def physical_scan(self, no):
        """Report hands on the phone since the last scan: the walk's results after that are not the script's alone."""
        lines, end = self.console(self.physical_seen)
        self.physical_seen = end
        hits = [l for l in lines if RX['physical'].search(l)]
        if hits:
            self.physical.append(dict(line=no, count=len(hits), first=hits[0].strip()[:160], last=hits[-1].strip()[:160]))
            self.say(f'PHYSICAL {len(hits)} touch/button event(s) on the phone during line {no} (not injected): {hits[0].strip()[:120]}')
        return hits

    def walk(self, steps):
        rc = 0
        self.physical_seen = self.console_end()
        for no, cmd, args, opts in steps:
            ok = self.step(no, cmd, args, opts)
            self.physical_scan(no)
            if not ok:
                rc = 1
                stop = opts.get('on_fail', 'stop' if self.args.stop_on_fail else 'continue') == 'stop' or cmd == 'wait_home'
                if stop:
                    self.say(f'STOP after line {no}')
                    if cmd == 'wait_home':
                        rc = 2
                    break
            if self.grep(RX['panic']):
                self.say('STOP the boot panicked or hit its deadline')
                rc = 1
                break
        return rc

    def finish(self, rc):
        lines, _ = self.console()
        (self.run / 'ustack.txt').write_text('\n'.join(l for l in lines if RX['ustack'].search(l)) + '\n')
        (self.run / 'crashes.txt').write_text('\n'.join(l for l in lines if RX['crash'].search(l)) + '\n')
        verdict = {0: 'PASS', 1: 'FAIL', 2: 'NOT_RUN'}[rc]
        report = dict(run=str(self.run), script=str(self.args.script), rc=rc, verdict=verdict, capabilities=self.capabilities,
                      canvas=self.canvas, steps=self.steps, snapshots=self.shots, physical_input=self.physical,
                      ustack_lines=sum(1 for l in lines if RX['ustack'].search(l)),
                      crash_lines=sum(1 for l in lines if RX['crash'].search(l)))
        (self.run / 'ui_run.json').write_text(json.dumps(report, indent=1, default=str) + '\n')
        md = [f'# ui_run {verdict}: {self.args.script}', '', f'run `{self.run}`', '',
              '| # | line | step | verdict | state | changed | screenshot |', '|---|---|---|---|---|---|---|']
        for i, s in enumerate(self.steps, 1):
            ch = s.get('changed')
            png = s.get('png')
            md.append(f'| {i} | {s["line"]} | `{s["cmd"]} {" ".join(map(str, s["args"]))}` | {s["verdict"]} | {s.get("state", "")} | '
                      f'{"" if ch is None else f"{ch:.3f}"} | {f"![]({Path(png).relative_to(self.run)})" if png else ""} |')
        md += ['', f'stack sampler lines: {report["ustack_lines"]} (`ustack.txt`); crash lines: {report["crash_lines"]} (`crashes.txt`)', '']
        if self.physical:
            md += ['## Physical input during the walk (someone touched the glass or pressed a button)', '']
            md += [f'- line {x["line"]}: {x["count"]} event(s), first `{x["first"]}`' for x in self.physical] + ['']
        (self.run / 'ui_run.md').write_text('\n'.join(md))
        self.say(f'END {verdict} rc={rc} steps={len(self.steps)} pass={sum(s["verdict"] == "PASS" for s in self.steps)} '
                 f'report {self.run / "ui_run.json"}')
        self.log.close()
        return rc


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('run', help='live_boot run directory (or its live.env)')
    p.add_argument('script', help='.ui script')
    p.add_argument('--home-timeout', type=float, default=HOME_TIMEOUT_T0, help='wait_home default: seconds after LIVE_T0')
    p.add_argument('--stop-on-fail', action='store_true')
    p.add_argument('--no-snap', action='store_true')
    p.add_argument('--poll-step', type=int, default=POLL_STEP, help=f'snapshot step of pre/after/ready polls (default {POLL_STEP}; '
                   f'{SNAP_STEP} = the old full-size polls, ~4x slower)')
    p.add_argument('--check', action='store_true', help='parse the script and exit')
    p.add_argument('--tesseract', default=os.environ.get('TESSERACT', 'tesseract'))
    p.add_argument('--python', default=os.environ.get('USBCON_PY', 'python3'), help='Mac python for the client')
    args = p.parse_args()
    try:
        steps = parse_script(Path(args.script).read_text())
    except (OSError, ValueError) as exc:
        print(f'ui_run: {args.script}: {exc}', file=sys.stderr)
        return 2
    if args.check:
        for s in steps:
            print(*s)
        return 0
    env = read_env(args.run)
    for key in ('LIVE_RUN', 'LIVE_SOCK', 'LIVE_MAC_DIR'):
        if key not in env:
            p.error(f'{key} missing from live.env')
    signal.signal(signal.SIGTERM, on_term)
    return Runner(args, env, MacClient(env, args.python)).main(steps)


if __name__ == '__main__':
    sys.exit(main())
