#!/usr/bin/env python3
"""hk_session: one coordinator command for a queue of phone boots. The phone stays in fastboot between iOS boots and goes
back to Android once, at the end. docs/DEBUG-LOOP.md.

  tools/hk_session.py QUEUE_DIR [--results DIR] [--stay | --return-via stock|chooser] [--only REQ ...] [--redo REQ ...]
  tools/hk_session.py --return [--return-via stock|chooser] [--results DIR]     # only: phone back to Android + return check
  tools/hk_session.py QUEUE_DIR --check                                         # parse and validate the queue; no Mac, no phone

QUEUE_DIR holds <lane>-<n>.req files (/data/work/hk-fleet/BRIEF.md), KEY=VALUE, shell quoting, one or several per line:
  IMAGE=<name under research/images>   MACH=<unstripped kernel path, relative to the checkout or the Mac's absolute path>
  NAME=<attempt name>  WAIT=<s>  END_ON='<console regex that means the evidence is in>'  END_AFTER=<s after Home>
  EXPECT='<regex of decisive lines>'  QUERIES='<hkq queries when the end condition fires: drivers; procs; ioreg X 4; ...>'
  ABORT_ON='<console regex that must stop the boot at once, e.g. a thermal limit: no grace, no queries>'
  UI=<ui script | settings>  WHY=<one line, to the end of the line: the single question this boot answers>
Any other UPPERCASE= key (e.g. OWNER=<what the owner must do during the boot>) is free text to the end of its line: it is
printed when the request starts and in the report, nothing more.
With neither END_ON nor END_AFTER the boot ends --default-end-after seconds (90) after Home, never at the kernel deadline
by default. A request is pending while <results>/<req>/REPORT.md does not exist; requests run oldest file first. A request
with a final REPORT.md is moved to QUEUE_DIR/done/ (--keep-req leaves it).

For each pending request:
  1. preflight   the request itself; image and kernel on m1box (copied back from the Mac checkout when only there); once
                 per session: m1box's Mac-side tools placed on the Mac, hash-verified, outside its checkout (tools/mactools.py).
  2. to-fastboot from any state: a running iOS boot is ended by the usbcon reset op (`tools/hk to-fastboot`), Android is
                 rebooted to the bootloader (hk_cycle), fastboot is left alone. Never a cold reset.
  3. boot        tools/hk_cycle.py --stay-fastboot: live console, UI script, the --end-on / --end-after conditions; when one
                 fires: the hkq QUERIES, a screenshot, then the reset; park; ramdump; analysis. The cycle does not return to
                 Android: it checks that the phone is parked and leaves it there.
  4. score       tools/hk_score.py on the boot (score.json, score.md) and --diff / --baseline against the baseline
                 (default /data/work/hk-score/baseline.json): score-diff.txt, regression yes/no.
  5. report      <results>/<req>/REPORT.md (+ result.json, console.txt, markers.txt, queries.txt, expect.txt, screens/,
                 ramdump/, cycle/ = hk_cycle's own directory).
Then the next request, from fastboot. After the last one (or the first failure that leaves the phone anywhere else, or an
interrupt): the return to Android with the return check (tools/hk_cycle.py --return-only), unless --stay.

The return (also --return alone). Default --return-via stock: force-fastboot off, read back, then `fastboot boot` of the
stock boot image (research/ios26-dualboot-r8/truth/boot_b.img, sha256 checked): a temporary boot of stock Android that
passes the installed chooser by. --return-via chooser: `fastboot reboot` into the installed boot_b; never sent while
force-fastboot still reads on (it would only park again). Either way the wait names every state it sees and nothing else
is sent; see hk_cycle.py.

A request that cannot run for its own reasons (bad request, image check, kernel not in the image, END_* on a
blazer_usbcon=1 image, QUERIES without the query gate) gets a REPORT.md with verdict REFUSED and the queue goes on; the
phone is not touched for it. A failure of the surroundings (Mac unreachable, tools not verifiable, phone absent, in
recovery, or not parked after a boot) stops the queue; that request stays pending (ATTEMPT-<time>.md says why).

The LAST line printed is always "hk_session: phone: STATE (how it is known)".
Exit: 0 every request ran and the phone is where it should be (Android, return check PASS; or fastboot with --stay);
1 a request was refused or failed, or the return check failed; 2 usage; 3 the queue stopped early; 5 the phone is NOT where
it should be; 130 interrupted.

Test doubles (tools/test_hk_session.py): HK_SESSION_CYCLE, HK_SESSION_SCORE, HK_SESSION_HK, HK_SESSION_IMAGES, plus hk_cycle's own
HK_CYCLE_*.
"""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('IMAGE', 'MACH', 'NAME', 'WAIT', 'END_ON', 'END_AFTER', 'ABORT_ON', 'EXPECT', 'QUERIES', 'UI', 'WHY')
KEY_RX = re.compile(r'(?:(?<=\s)|^)([A-Z][A-Z0-9_]*)=')        # KEYS, or a lane's own key (e.g. OWNER=): kept, shown, not acted on
NAME_RX = re.compile(r'[A-Za-z0-9._-]+')
DEFAULT_BASELINE = '/data/work/hk-score/baseline.json'
# hk_cycle refusals that are the request's own (the queue goes on) versus the surroundings' (the queue stops).
OWN_REFUSALS = {'BAD_ARGS', 'IMAGE_CHECK_FAILED', 'KERNEL_MISMATCH', 'END_WITHOUT_CONSOLE', 'END_NEEDS_USBCON2', 'QUERIES_NEED_HKQ',
                'UI_WITHOUT_CONSOLE', 'UI_WITHOUT_INPUT', 'UI_RUNNER_MISSING', 'MAC_COPY_DIFFERS'}
EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_STOPPED, EXIT_PHONE, EXIT_INTERRUPTED = 0, 1, 2, 3, 5, 130


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


# ----------------------------------------------------------------------------------------------- requests
def parse_req(text):
    """A .req file -> ({KEY: value}, [errors]). KEY=value pairs, shell quoting; WHY runs to the end of its line."""
    out, errors = {}, []
    for ln, line in enumerate(text.splitlines(), 1):
        line = line.rstrip()
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        pos = 0
        while pos < len(line):
            if line[pos].isspace():
                pos += 1
                continue
            m = KEY_RX.match(line, pos)
            if not m:
                errors.append(f'line {ln}: expected one of {", ".join(KEYS)}= at: {line[pos:pos + 40]!r}')
                break
            key, pos = m.group(1), m.end()
            if key == 'WHY' or key not in KEYS:        # free text to the end of the line
                value, pos = line[pos:].strip(), len(line)
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
                    value = value[1:-1]
            else:
                lex = shlex.shlex(line[pos:], posix=True)
                lex.whitespace_split, lex.commenters = True, ''
                try:
                    value = lex.get_token() or ''
                except ValueError as e:
                    errors.append(f'line {ln}: {key}: {e}')
                    break
                # how far the lexer read: re-scan the raw text for the end of this one shell word
                pos = _word_end(line, pos)
            if key in out:
                errors.append(f'line {ln}: {key} given twice')
            out[key] = value
    return out, errors


def _word_end(line, pos):
    quote = None
    while pos < len(line):
        c = line[pos]
        if quote:
            if c == '\\' and quote == '"' and pos + 1 < len(line):
                pos += 1
            elif c == quote:
                quote = None
        elif c in '\'"':
            quote = c
        elif c == '\\' and pos + 1 < len(line):
            pos += 1
        elif c.isspace():
            break
        pos += 1
    return pos


def validate_req(stem, fields, errors, root=ROOT, mac_dir='Developer/personal/hackios', hkq=None):
    """Normalise one request. Returns (req dict, [errors]); a request with errors does not touch the phone."""
    errors = list(errors)
    req = dict(req=stem, raw=dict(fields))
    image = fields.get('IMAGE', '')
    if image.endswith('/boot.img'):
        image = image[:-len('/boot.img')]
    image = image.rstrip('/').rsplit('/', 1)[-1] if image.startswith(('research/images/', '/')) else image
    if not image or not NAME_RX.fullmatch(image):
        errors.append(f'IMAGE: a name under research/images is needed, not {fields.get("IMAGE")!r}')
    req['image'] = image
    req['image_dir'] = f"{os.environ.get('HK_SESSION_IMAGES', 'research/images').rstrip('/')}/{image}"
    mach = fields.get('MACH', '')
    marker = '/' + mac_dir.strip('/') + '/'
    if marker in mach:
        mach = mach.split(marker, 1)[1]
    elif mach.startswith(str(root) + '/'):
        mach = mach[len(str(root)) + 1:]
    if not mach or mach.startswith('/') or '..' in Path(mach).parts:
        errors.append(f'MACH: the unstripped kernel, as a path inside the checkout, is needed, not {fields.get("MACH")!r}')
    req['mach'] = mach
    name = fields.get('NAME') or stem
    if not NAME_RX.fullmatch(name):
        errors.append(f'NAME may use only A-Za-z0-9._-: {name!r}')
    req['name'] = name
    for key, lo, hi in (('WAIT', 30, 7200), ('END_AFTER', 0, 7200)):
        v = fields.get(key)
        if v in (None, ''):
            req[key.lower()] = None
            continue
        try:
            n = float(v)
        except ValueError:
            n = None
        if n is None or not lo <= n <= hi:
            errors.append(f'{key}: {lo}..{hi} seconds, not {v!r}')
        req[key.lower()] = int(n) if n is not None and key == 'WAIT' else n
    for key in ('END_ON', 'ABORT_ON', 'EXPECT'):
        v = fields.get(key) or None
        if v:
            try:
                re.compile(v)
            except re.error as e:
                errors.append(f'{key}: bad regex: {e}')
        req[key.lower()] = v
    q = fields.get('QUERIES') or None
    if q:
        try:
            (hkq or load_module('hkq', ROOT / 'tools/hkq.py')).parse_batch(q)
        except ValueError as e:
            errors.append(f'QUERIES: {e}')
    req['queries'] = q
    ui = fields.get('UI') or None
    if ui and ui != 'settings' and '..' in Path(ui).parts:
        errors.append(f'UI: a script path (inside the checkout or absolute on m1box), or settings: {ui!r}')
    req['ui'] = ui
    req['extra'] = {k: v for k, v in fields.items() if k not in KEYS}
    req['why'] = fields.get('WHY', '')
    if not req['why']:
        errors.append('WHY: one line saying which single question this boot answers')
    return req, errors


def load_queue(queue, root=ROOT, mac_dir='Developer/personal/hackios'):
    hkq = load_module('hkq', ROOT / 'tools/hkq.py')
    reqs = []
    for p in sorted(Path(queue).glob("*.req"), key=lambda p: (p.stat().st_mtime, p.name)):     # oldest first, as the coordinator queue
        if not NAME_RX.fullmatch(p.stem):
            reqs.append((dict(req=p.stem, raw={}, path=str(p)), [f'request file name may use only A-Za-z0-9._-: {p.name}']))
            continue
        fields, errors = parse_req(p.read_text(errors='replace'))
        req, errors = validate_req(p.stem, fields, errors, root, mac_dir, hkq)
        req['path'] = str(p)
        reqs.append((req, errors))
    return reqs


# ----------------------------------------------------------------------------------------------- the session
class Session:
    def __init__(self, args):
        self.a = args
        self.queue = Path(args.queue).resolve() if args.queue else None
        self.results = Path(args.results).resolve() if args.results else (self.queue.parent / 'results' if self.queue else None)
        self.cycle_tool = os.environ.get('HK_SESSION_CYCLE', str(ROOT / 'tools/hk_cycle.py'))
        self.score_tool = os.environ.get('HK_SESSION_SCORE', str(ROOT / 'tools/hk_score.py'))
        self.hk_tool = os.environ.get('HK_SESSION_HK', str(ROOT / 'tools/hk.py'))
        self.interrupts = 0
        self.child = None
        self.t0 = time.monotonic()
        self.rows = []              # one per request handled: dict(req, verdict, ...)
        self.stopped = None         # why the queue stopped early
        self.touched = False        # a cycle changed the phone's state in this session
        self.phone_line = None      # the last "phone: ..." line a child printed
        self.log_f = None
        self.hc = load_module('hk_cycle', ROOT / 'tools/hk_cycle.py')
        self.mac_dir = os.environ.get('HK_CYCLE_MAC_DIR') or 'Developer/personal/hackios'

    # ------------------------------------------------------------------ plumbing
    def log(self, msg):
        line = f'{datetime.datetime.now().strftime("%H:%M:%S")} +{time.monotonic() - self.t0:7.1f} {msg}'
        if self.log_f:
            self.log_f.write(line + '\n')
            self.log_f.flush()
        print(f'hk_session: {msg}', flush=True)

    def on_signal(self, signum, _frame):
        self.interrupts += 1
        print(f'\nhk_session: interrupt {self.interrupts} ({signal.Signals(signum).name}): the running step is told; no further '
              'request starts' + ('' if self.a.stay else '; the return to Android still runs (interrupt again to abandon it)'),
              file=sys.stderr, flush=True)
        if self.child and self.child.poll() is None:
            try:
                self.child.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    def run_child(self, cmd, out_path, bound, echo=True):
        """A child in its own session, output to out_path (and echoed); signals are forwarded by on_signal; bounded."""
        self.log('$ ' + ' '.join(shlex.quote(str(c)) for c in cmd))
        lines = []
        with open(out_path, 'ab') as fo:
            p = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 cwd=str(ROOT), start_new_session=True)
            self.child = p
            end = time.monotonic() + bound
            os.set_blocking(p.stdout.fileno(), False)
            buf = b''
            killed = False
            while True:
                chunk = p.stdout.read()
                if chunk:
                    fo.write(chunk)
                    fo.flush()
                    buf += chunk
                    *done, buf = buf.split(b'\n')
                    for raw in done:
                        text = raw.decode('utf-8', 'replace')
                        lines.append(text)
                        if echo:
                            print('  ' + text, flush=True)
                elif p.poll() is not None:
                    break
                else:
                    time.sleep(0.1)
                if time.monotonic() > end and not killed:
                    killed = True
                    self.log(f'child ran past its bound of {bound:.0f}s: stopping it')
                    for sig, grace in ((signal.SIGTERM, 60), (signal.SIGKILL, 10)):
                        try:
                            os.killpg(p.pid, sig)
                        except (ProcessLookupError, PermissionError):
                            pass
                        try:
                            p.wait(timeout=grace)
                            break
                        except subprocess.TimeoutExpired:
                            continue
            if buf:
                lines.append(buf.decode('utf-8', 'replace'))
            rc = p.wait()
            for s in (p.stdin, p.stdout):
                try:
                    s.close()
                except OSError:
                    pass
            self.child = None
        for text in lines:
            if re.match(r'hk_cycle: phone: ', text):
                self.phone_line = text[len('hk_cycle: '):]
        return (None if killed else rc), lines

    def passthrough(self):
        out = []
        if self.a.timeouts:
            out += ['--timeouts', self.a.timeouts]
        if self.a.poll is not None:
            out += ['--poll', str(self.a.poll)]
        return out

    # ------------------------------------------------------------------ one request
    def fetch_from_mac(self, rel, log_path):
        """A path of the checkout that only the Mac has (lanes build kernels and images there): copy it back, never over a file."""
        pb = os.environ.get('HK_CYCLE_PB', str(Path.home() / '.local/share/phone-bridge/bin'))
        mac = str(Path(pb) / 'mac')
        try:
            p = subprocess.run([mac, 'repo', '--force', '--back', rel, '--', 'true'], cwd=str(ROOT), stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=1800)
            Path(log_path).write_text(p.stdout + p.stderr)
            return p.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as e:
            Path(log_path).write_text(f'{e}\n')
            return False

    def prepare(self, req, rdir):
        """Image and kernel present on m1box (hk_cycle reads both). Returns [errors]."""
        errors = []
        img = ROOT / req['image_dir'] / 'boot.img'
        if not img.is_file():
            self.log(f"{req['req']}: {req['image_dir']} is not on m1box; copying it back from the Mac checkout")
            self.fetch_from_mac(req['image_dir'], rdir / 'fetch-image.out')
        if not img.is_file():
            errors.append(f"IMAGE: {req['image_dir']}/boot.img exists neither on m1box nor in the Mac checkout")
        mach = ROOT / req['mach']
        if not mach.is_file():
            self.log(f"{req['req']}: {req['mach']} is not on m1box; copying it back from the Mac checkout")
            self.fetch_from_mac(req['mach'], rdir / 'fetch-mach.out')
        if not mach.is_file():
            errors.append(f"MACH: {req['mach']} exists neither on m1box nor in the Mac checkout")
        if req.get('ui') and req['ui'] != 'settings' and not (ROOT / req['ui']).is_file():      # an absolute path stays itself
            errors.append(f"UI: no such script: {req['ui']}")
        return errors

    def to_fastboot_from_ios(self, rdir):
        """A running iOS boot (or the shim) is on USB: end it by the usbcon reset op. Returns (ok, detail)."""
        for attempt in range(1, 5):
            cmd = [sys.executable, '-I', self.hk_tool, '--json', 'to-fastboot', '--lock', self.a.lock, '--wait', str(self.a.to_fastboot_wait)]
            rc, lines = self.run_child(cmd, rdir / 'to-fastboot.out', self.a.to_fastboot_wait + 240, echo=False)
            text = '\n'.join(lines)
            doc = {}
            try:
                doc = json.loads(text[text.index('{'):text.rindex('}') + 1])
            except ValueError:
                pass
            err = doc.get('error') if isinstance(doc.get('error'), dict) else {}
            code = err.get('code') or doc.get('code') or ''
            msg = err.get('message') or doc.get('message') or (text.strip().splitlines() or ['no output'])[-1][:300]
            if rc == 0:
                return True, (doc.get('data') or doc).get('action', 'fastboot')
            if 'transient' in (code, err.get('reason')) or 'run hk to-fastboot again' in msg:
                self.log(f'to-fastboot: the shim is handing over ({msg[:120]}); again in 15 s ({attempt}/4)')
                time.sleep(min(15, (self.a.poll or 10) * 1.5))
                continue
            return False, f'{code or "rc " + str(rc)}: {msg}'
        return False, 'the shim gadget stayed up through four tries'

    def probe(self):
        """The phone's state now, read only (hk_cycle's own probe: fastboot devices, adb devices, the Mac's USB ids)."""
        ops = self.sdir / 'probe'
        ops.mkdir(parents=True, exist_ok=True)
        c = self.hc.Cycle(self.hc.parse_args(['--return-only', '--out', str(ops)] + self.passthrough()))
        c.out, c.tmp = ops, ops
        try:
            return c.phone_state(kill_at=99)
        except Exception as e:
            return f'unknown ({type(e).__name__}: {e})'

    def run_request(self, req, errors):
        stem = req['req']
        rdir = self.results / stem
        if rdir.exists() and stem in (self.a.redo or []):
            rdir.rename(self.results / f'{stem}.prev-{time.strftime("%Y%m%d-%H%M%S")}')
        rdir.mkdir(parents=True, exist_ok=True)
        row = dict(req=stem, name=req.get('name'), image=req.get('image'), why=req.get('why', ''), started=now_iso(), t0=time.monotonic(),
                   dir=str(rdir), timing={})
        self.rows.append(row)
        self.log(f"=== {stem}: {req.get('image')} as {req.get('name')}: {req.get('why', '')[:140]}")
        for k, v in (req.get('extra') or {}).items():
            self.log(f'{stem}: {k}: {v}')
        if not errors:
            errors = self.prepare(req, rdir)
        if errors:
            row.update(verdict='REFUSED', errors=[dict(state='BAD_REQUEST', detail=e) for e in errors], phone_touched=False)
            self.finish(req, row, final=True)
            return
        state = self.probe()
        row['state_before'] = state
        if state == 'ios':
            ok, detail = self.to_fastboot_from_ios(rdir)
            row['to_fastboot'] = detail
            self.touched = True
            if not ok:
                row.update(verdict='NOT_RUN', errors=[dict(state='TO_FASTBOOT_FAILED', detail=detail)])
                self.stopped = f'{stem}: the running iOS boot could not be ended: {detail}'
                self.finish(req, row, final=False)
                return
        cdir = rdir / 'cycle'
        if cdir.exists():
            cdir.rename(rdir / f'cycle.prev-{time.strftime("%Y%m%d-%H%M%S")}')
        cmd = [sys.executable, '-I', self.cycle_tool, '--image', req['image_dir'], '--mach', req['mach'], '--name', req['name'],
               '--out', str(cdir), '--stay-fastboot']
        if req.get('wait'):
            cmd += ['--deadline-wait', str(req['wait'])]
        if req.get('end_on'):
            cmd += ['--end-on', req['end_on'], '--end-grace', str(self.a.end_grace)]
        if req.get('end_after') is not None:
            cmd += ['--end-after', f"{req['end_after']:g}"]
        elif not req.get('end_on') and self.a.default_end_after >= 0:
            cmd += ['--end-after', f'{self.a.default_end_after:g}']       # never sit to the kernel deadline by default
            row['default_end_after'] = self.a.default_end_after
        if req.get('abort_on'):
            cmd += ['--abort-on', req['abort_on']]
        if req.get('queries'):
            cmd += ['--queries', req['queries']]
        if req.get('ui'):
            cmd += ['--ui', req['ui']]
        if self.a.skip_image_check:
            cmd.append('--skip-image-check')
        if self.a.cache:
            cmd += ['--cache', self.a.cache]
        cmd += self.passthrough()
        bound = 3 * (req.get('wait') or 1300) + 3600
        row['timing']['cycle_start'] = round(time.monotonic() - row['t0'], 1)
        rc, lines = self.run_child(cmd, rdir / 'cycle.out', bound)
        row['timing']['cycle_end'] = round(time.monotonic() - row['t0'], 1)
        row['cycle_rc'] = rc
        summary, report = {}, {}
        try:
            summary = json.loads((cdir / 'summary.json').read_text())
            report = json.loads((cdir / 'report.json').read_text())
        except (OSError, ValueError):
            pass
        ret = report.get('return') or {}
        row.update(verdict=summary.get('verdict') or f'NO_REPORT (hk_cycle rc {rc})', cycle=str(cdir), errors=report.get('errors', []),
                   phone=ret.get('state'), phone_touched=not ret.get('untouched', False) if report else None,
                   live_run=summary.get('live_run'), attempt=summary.get('attempt'), end=report.get('end'),
                   queries=report.get('queries'), home=summary.get('home'))
        if row['phone_touched'] is not False:
            self.touched = True
        refused_own = (row['verdict'] == 'REFUSED' and report.get('errors') and
                       all(e['state'] in OWN_REFUSALS for e in report['errors']))
        if row['verdict'] == 'REFUSED' and not refused_own:
            self.stopped = (f"{stem}: preflight refused for a reason outside the request: "
                            + '; '.join(f"{e['state']}: {e['detail'][:160]}" for e in report.get('errors', [])))
        elif not report:
            self.stopped = f'{stem}: hk_cycle left no report (rc {rc}); see {rdir / "cycle.out"}'
        elif row['verdict'] != 'REFUSED' and not ret.get('fastboot'):
            self.stopped = f"{stem}: after the boot the phone is {ret.get('state')}, not parked in fastboot"
        if report and row['verdict'] != 'REFUSED':
            self.evidence(req, row, rdir, cdir, report)
        self.finish(req, row, final=not self.stopped or bool(report and row['verdict'] != 'REFUSED'), report=report)

    def evidence(self, req, row, rdir, cdir, report):
        """Console, ramdump, queries, screenshots, EXPECT lines and the scoreboard into the result directory."""
        live = Path(row['live_run']) if row.get('live_run') else None
        att = Path(row['attempt']) if row.get('attempt') else None
        for src, dst in ((live and live / 'console.txt', 'console.txt'), (live and live / 'markers.txt', 'markers.txt'),
                         (cdir / 'queries.txt', 'queries.txt'), (att and att / 'reader.txt', 'reader.txt'),
                         (att and att / 'park-timeline.txt', 'park-timeline.txt')):
            if src and Path(src).is_file():
                shutil.copyfile(src, rdir / dst)
        if att and (att / 'ramdump').is_dir() and not (rdir / 'ramdump').exists():
            subprocess.run(['cp', '-a', '--reflink=auto', str(att / 'ramdump'), str(rdir / 'ramdump')], stdin=subprocess.DEVNULL)
        if (cdir / 'screens').is_dir():
            (rdir / 'screens').mkdir(exist_ok=True)
            for p in sorted((cdir / 'screens').glob('*.png')):
                shutil.copyfile(p, rdir / 'screens' / p.name)
        if (rdir / 'queries.txt').is_file() and '\nK tid=' in (rdir / 'queries.txt').read_text(errors='replace'):
            rc, out = self.tool([sys.executable, '-I', str(ROOT / 'tools/hkq_sym.py'), str(rdir / 'queries.txt'), '--mach', str(ROOT / req['mach'])], 180)
            (rdir / 'kthreads.txt').write_text(out)
            row['kthreads'] = [l[:200] for l in out.splitlines()[:14]]
        row['screens'] = sorted(p.name for p in (rdir / 'screens').glob('*.png')) if (rdir / 'screens').is_dir() else []
        row['ramdump'] = (rdir / 'ramdump/kernel.log').is_file()
        # EXPECT: the decisive lines, from the boot's own text (the larger of live console and ramdump, as hk_cycle chose)
        if req.get('expect'):
            text = ''
            for p in (cdir / 'analysis/boot.txt', rdir / 'console.txt'):
                if p.is_file():
                    text = p.read_text(errors='replace')
                    break
            rx = re.compile(req['expect'])
            hits = [l for l in text.splitlines() if rx.search(l)]
            (rdir / 'expect.txt').write_text('\n'.join(hits) + ('\n' if hits else ''))
            row['expect'] = dict(re=req['expect'], lines=len(hits), first=[h[:220] for h in hits[:12]])
        # the scoreboard
        boot = live if live and live.is_dir() else att if att and att.is_dir() else None
        t = time.monotonic()
        if boot:
            sc = row['score'] = {}
            for flag, name in (('--json', 'score.json'), ('--md', 'score.md')):
                p = self.tool([sys.executable, '-I', self.score_tool, str(boot), flag], 300)
                (rdir / name).write_text(p[1])
                sc[name] = p[0]
            base = self.a.baseline
            if base and Path(base).is_file():
                rc, out = self.tool([sys.executable, '-I', self.score_tool, str(boot), '--diff', base], 300)
                (rdir / 'score-diff.txt').write_text(out)
                rc2, out2 = self.tool([sys.executable, '-I', self.score_tool, str(boot), '--baseline', base, '--brief'], 300)
                (rdir / 'score-baseline.txt').write_text(out2)
                sc.update(diff_rc=rc, baseline=base, regressed=rc2 == 1, baseline_rc=rc2,
                          diff_head=[l[:200] for l in out.strip().splitlines()[:30]])
            else:
                sc.update(baseline=None, note=f'no baseline at {base}')
        row['timing']['score_s'] = round(time.monotonic() - t, 1)

    def tool(self, cmd, bound):
        try:
            p = subprocess.run(cmd, cwd=str(ROOT), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=bound)
            return p.returncode, p.stdout + (p.stderr if p.returncode not in (0, 1) else '')
        except subprocess.TimeoutExpired:
            return None, f'timed out after {bound}s\n'
        except OSError as e:
            return None, f'{e}\n'

    def finish(self, req, row, final, report=None):
        row['ended'] = now_iso()
        row['duration_s'] = round(time.monotonic() - row.pop('t0'), 1)
        rdir = Path(row['dir'])
        md = render_request(req, row, report or {})
        name = 'REPORT.md' if final else f'ATTEMPT-{time.strftime("%Y%m%d-%H%M%S")}.md'
        (rdir / name).write_text(md)
        (rdir / ('result.json' if final else 'attempt.json')).write_text(json.dumps(row, indent=1, default=str) + '\n')
        row['report'] = str(rdir / name)
        row['final'] = final
        src = Path(req.get('path') or '')
        if src.is_file():
            shutil.copyfile(src, rdir / src.name)
            if final and not self.a.keep_req:
                (src.parent / 'done').mkdir(exist_ok=True)
                src.replace(src.parent / 'done' / src.name)
        self.log(f"{row['req']}: {row['verdict']}" + ('' if final else ' (stays pending)') + f"; {rdir / name}")

    # ------------------------------------------------------------------ the end
    def return_to_android(self):
        out = self.sdir / 'return'
        cmd = [sys.executable, '-I', self.cycle_tool, '--return-only', '--return-via', self.a.return_via, '--out', str(out),
               '--name', 'session-return'] + self.passthrough()
        if self.a.no_return_check:
            cmd.append('--no-return-check')
        rc, _lines = self.run_child(cmd, self.sdir / 'return.out', 6 * 3600)
        try:
            rep = json.loads((out / 'report.json').read_text())
        except (OSError, ValueError):
            rep = {}
        self.ret = dict(rc=rc, verdict=rep.get('verdict') or f'NO_REPORT (rc {rc})', **{k: (rep.get('return') or {}).get(k) for k in
                        ('state', 'android', 'via_used', 'force_fastboot_off', 'wait', 'check', 'stock')},
                        errors=rep.get('errors', []), dir=str(out))
        return self.ret

    def main(self):
        a = self.a
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, self.on_signal)
        self.results.mkdir(parents=True, exist_ok=True)
        lock = open(self.results / '.session.lock', 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f'hk_session: another session is running on {self.results} (.session.lock held); nothing was done', file=sys.stderr)
            print('hk_session: phone: not probed (another hk_session owns it)')
            return EXIT_USAGE
        self.sdir = self.results / '_session' / time.strftime('%Y%m%d-%H%M%S')
        self.sdir.mkdir(parents=True, exist_ok=True)
        self.log_f = open(self.sdir / 'session.log', 'a')
        self.ret = None
        self.log(f'session {self.sdir}')
        pending = []
        if self.queue and not a.return_only:
            for req, errors in load_queue(self.queue, ROOT, self.mac_dir):
                stem = req['req']
                if a.only and stem not in a.only:
                    continue
                if (self.results / stem / 'REPORT.md').is_file() and stem not in (a.redo or []):
                    continue
                pending.append((req, errors))
            self.log(f'queue {self.queue}: {len(pending)} pending: {", ".join(r["req"] for r, _ in pending) or "none"}')
            if a.max:
                pending = pending[:a.max]
        for req, errors in pending:
            if self.interrupts:
                self.stopped = self.stopped or f"interrupted before {req['req']}"
                break
            self.run_request(req, errors)
            if self.stopped:
                self.log(f'queue stopped: {self.stopped}')
                break
        left = [r['req'] for r, _ in pending if not any(row['req'] == r['req'] for row in self.rows)]
        # ---- the end: back to Android once, unless told to stay
        want = 'fastboot' if a.stay else 'android'
        state_line = None
        if a.stay:
            st = self.probe()
            state_line = f"{st} ({'parked; left there (--stay): run tools/hk_session.py --return to go back to Android' if st == 'fastboot' else 'left as it is (--stay)'})"
            ok_phone = st == 'fastboot' or not self.touched
        elif a.return_only or self.touched:
            if self.interrupts >= 2:
                st = self.probe()
                state_line = f'{st} (the return to Android was abandoned by a second interrupt)'
                ok_phone = st == 'android'
            else:
                ret = self.return_to_android()
                ok_phone = bool(ret.get('android'))
                state_line = self.phone_line[len('phone: '):] if self.phone_line else f"{ret.get('state')} (hk_cycle --return-only: {ret['verdict']})"
        else:
            st = self.probe()
            state_line = f'{st} (not changed by this session)'
            ok_phone = True
        check = ((self.ret or {}).get('check') or {}).get('verdict')
        bad = [r for r in self.rows if r['verdict'] not in ('PASS', 'COMPLETE')]
        code = (EXIT_PHONE if not ok_phone else EXIT_INTERRUPTED if self.interrupts else EXIT_STOPPED if self.stopped else
                EXIT_FAIL if bad or (self.ret and check not in ('PASS', None) and not a.no_return_check) else EXIT_OK)
        doc = dict(schema='hk_session/1', started=self.rows[0]['started'] if self.rows else now_iso(), ended=now_iso(),
                   queue=str(self.queue) if self.queue else None, results=str(self.results), requests=self.rows, not_run=left,
                   stopped=self.stopped, interrupts=self.interrupts, want=want, phone=state_line, return_=self.ret, exit_code=code)
        (self.sdir / 'session.json').write_text(json.dumps(doc, indent=1, default=str) + '\n')
        (self.sdir / 'SESSION.md').write_text(render_session(doc))
        self.log(f'session summary: {self.sdir / "SESSION.md"}')
        for r in self.rows:
            print(f"hk_session: {r['req']}: {r['verdict']}  {r.get('report')}")
        if left:
            print(f"hk_session: not run (still pending): {', '.join(left)}")
        if self.stopped:
            print(f'hk_session: stopped early: {self.stopped}')
        print(f'hk_session: phone: {state_line}', flush=True)
        return code


# ----------------------------------------------------------------------------------------------- reports
def cell(s):
    return str(s).replace('|', '\\|').replace('\n', ' ')


def render_request(req, row, report):
    L = [f"# {row['req']}: {row['verdict']}", '']
    L.append(f"- **Question:** {row.get('why') or '(no WHY given)'}")
    raw = req.get('raw') or {}
    for k, v in (req.get('extra') or {}).items():
        L.append(f"- **{k}** (the request's own key; hk_session does not act on it): {v}")
    L.append('- Request: ' + ' '.join(f'{k}={shlex.quote(str(raw[k]))}' for k in KEYS if k in raw and k != 'WHY'))
    L.append(f"- Started {row.get('started')}, ended {row.get('ended')}, {row.get('duration_s')} s. Evidence class: "
             + ('PHYSICAL (this phone boot)' if row.get('live_run') or row.get('attempt') else 'HOST (the phone was not booted)'))
    phone = row.get('phone')
    if row.get('phone_touched') is False:
        L.append('- Phone: not touched for this request.')
    elif phone:
        L.append(f"- Phone after this request: **{phone}**" + (' (parked; the next request boots from here)' if phone == 'fastboot' else
                                                               ' (NOT parked in fastboot: the queue stops here)'))
    if row.get('state_before'):
        L.append(f"- Phone before: {row['state_before']}" + (f"; ended the running iOS boot: {row['to_fastboot']}" if row.get('to_fastboot') else ''))
    end = row.get('end') or {}
    if end:
        L.append(f"- Ended by: **{end.get('condition')}** ({cell(end.get('detail', ''))[:200]})"
                 + (f" at +{end['t']} s; reset {end.get('reset')}" + (f" sent at +{end['reset_t']} s" if end.get('reset_t') is not None else '')
                    if end.get('t') is not None else '')
                 + (f"; an early end was tried and did not take ({end['attempted'].get('condition')}, reset {end['attempted'].get('reset')})"
                    if end.get('attempted') else ''))
    if row.get('home') is not None:
        L.append(f"- Home reached: **{row['home']}**")
    if row.get('errors'):
        L += ['', '## Errors', ''] + [f"- `{e.get('state')}`" + (f" at +{e['t']} s" if e.get('t') is not None else '') + f": {e.get('detail')}"
                                      for e in row['errors']]
    ex = row.get('expect')
    if ex:
        L += ['', f"## EXPECT `{cell(ex['re'])[:160]}`: {ex['lines']} line(s)", '']
        L += ['```'] + ex['first'] + ['```', 'All of them: `expect.txt`.'] if ex['lines'] else ['**No line matched.**']
    q = row.get('queries')
    if q:
        L += ['', f"## Queries (hkq, at the end condition, before the reset): {q.get('ok')} of {q.get('asked')} rc 0", '',
              '| query | rc | lines | bytes | dropped | ms |', '|---|---|---|---|---|---|']
        for r in q.get('results', []):
            L.append(f"| {cell(r.get('query'))} | {r.get('rc', 'ERROR: ' + cell(r.get('error', ''))[:120])} | {r.get('lines', '')} | {r.get('bytes', '')} | "
                     f"{r.get('dropped', '')} | {r.get('ms', '')} |")
        L.append(f"\nOutput: `queries.txt` (batch rc {q.get('rc')}, {q.get('took_s')} s for the batch).")
    if row.get('kthreads'):
        L += ['', '## Kernel threads over the window (hkq kthreads, named by tools/hkq_sym.py; all: `kthreads.txt`)', '', '```'] + row['kthreads'] + ['```']
    t = report.get('timings') or {}
    an = report.get('analysis') or {}
    mk = an.get('markers') or {}
    if t or mk:
        L += ['', '## Timing', '', '| what | when |', '|---|---|']
        for k, label in (('preflight_start', 'preflight starts'), ('preflight_end', 'preflight done (phone in fastboot)'),
                         ('boot_start', 'boot step starts'), ('home', 'Home'), ('boot_end', 'boot step done (parked, ramdump pulled)')):
            if t.get(k) is not None:
                L.append(f'| {label} | +{t[k]} s (cycle clock) |')
        if end.get('t') is not None:
            L.append(f"| end condition fired | +{end['t']} s (cycle clock) |")
        if q:
            L.append(f"| queries done | +{round(q.get('t', 0) + (q.get('took_s') or 0), 1)} s (cycle clock) |")
        if end.get('reset_t') is not None:
            L.append(f"| reset op sent | +{end['reset_t']} s (cycle clock) |")
        for k in ('CONSOLE_CONNECTED', 'UI_READY', 'PANIC', 'CONSOLE_GONE', 'PARKED', 'BOOT_RC'):
            if k in mk:
                L.append(f"| live_boot {k} | +{mk[k].get('s')} s (live_boot clock) {cell(mk[k].get('detail', ''))[:80]} |")
        park = an.get('park') or {}
        if park:
            L.append(f"| console up -> park | {park.get('ep0_to_park_s')} s; reboot reason {park.get('abl_reboot_reason')}, "
                     f"RST_STAT {park.get('abl_rst_stat_terminal')} |")
            if park.get('note'):
                L.append(f"\n**{park['note']}**")
        if (row.get('timing') or {}).get('score_s') is not None:
            L.append(f"| scoreboard | {row['timing']['score_s']} s |")
        L.append(f"| whole request | {row.get('duration_s')} s |")
    sc = row.get('score')
    if sc:
        L += ['', '## Scoreboard (tools/hk_score.py)', '']
        if sc.get('baseline'):
            L.append(f"- Against `{sc['baseline']}`: **{'REGRESSION' if sc.get('regressed') else 'no regression'}** "
                     f"(--baseline rc {sc.get('baseline_rc')}); changes in `score-diff.txt`:")
            L += ['```'] + (sc.get('diff_head') or ['(no output)']) + ['```']
        else:
            L.append(f"- No diff: {sc.get('note')}")
        L.append('- This boot: `score.md`, `score.json`.')
    if row.get('screens'):
        L += ['', '## Screens', ''] + [f"![{n}](screens/{n})  " for n in row['screens']]
    L += ['', '## Files', '']
    L.append(f"- This directory: REPORT.md, result.json, console.txt, markers.txt, ramdump/ ({'kernel.log present' if row.get('ramdump') else 'NO kernel.log'}), "
             'queries.txt, expect.txt, score.*, screens/, cycle.out')
    if row.get('cycle'):
        L.append(f"- hk_cycle's own report (crashes, respawns, panics, symbols): `{row['cycle']}/report.md`")
    if row.get('live_run') or row.get('attempt'):
        L.append(f"- live run `{row.get('live_run')}`, attempt `{row.get('attempt')}`")
    return '\n'.join(L) + '\n'


def render_session(doc):
    L = [f"# hk_session {doc['started']} .. {doc['ended']}", '', f"- Queue `{doc['queue']}`, results `{doc['results']}`",
         f"- **Phone at the end: {doc['phone']}** (wanted: {doc['want']})"]
    if doc.get('stopped'):
        L.append(f"- **Stopped early:** {doc['stopped']}")
    if doc.get('not_run'):
        L.append(f"- Not run, still pending: {', '.join(doc['not_run'])}")
    ret = doc.get('return_')
    if ret:
        chk = ret.get('check') or {}
        w = ret.get('wait') or {}
        L.append(f"- Return to Android: **{ret.get('verdict')}**, route {ret.get('via_used')}, force-fastboot off {ret.get('force_fastboot_off')}, "
                 f"{w.get('s')} s from leaving fastboot, states seen: {' -> '.join(str(x['state']) + '@' + str(x['t']) + 's' for x in w.get('seen', [])) or '-'}; "
                 f"return check {chk.get('verdict', 'NOT RUN')}, bootreason `{chk.get('bootreason')}`, kernel {chk.get('kernel_code_base')}")
        L += [f"  - `{e.get('state')}`: {e.get('detail')}" for e in ret.get('errors', [])]
    L += ['', '| request | verdict | ended by | phone after | s | report |', '|---|---|---|---|---|---|']
    for r in doc['requests']:
        L.append(f"| {r['req']} | **{r['verdict']}** | {cell((r.get('end') or {}).get('condition', ''))} | {r.get('phone') or ('untouched' if r.get('phone_touched') is False else '?')} | "
                 f"{r.get('duration_s')} | `{r.get('report')}` |")
    return '\n'.join(L) + '\n'


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('queue', nargs='?', help='directory of .req files')
    p.add_argument('--results', help='results directory (default: <queue>/../results)')
    p.add_argument('--return', dest='return_only', action='store_true', help='only bring the phone back to Android, with the return check')
    p.add_argument('--stay', action='store_true', help='leave the phone parked in fastboot at the end (no return to Android)')
    p.add_argument('--return-via', choices=('stock', 'chooser'), default='stock', help='stock (default): fastboot boot of the stock '
                   'boot image, past the installed chooser; chooser: fastboot reboot into the installed boot_b')
    p.add_argument('--no-return-check', action='store_true')
    p.add_argument('--only', nargs='+', metavar='REQ', help='only these requests (file name without .req)')
    p.add_argument('--redo', nargs='+', metavar='REQ', help='run these again although they have a REPORT.md (the old result is renamed)')
    p.add_argument('--max', type=int, help='at most this many requests in this session')
    p.add_argument('--baseline', default=DEFAULT_BASELINE, help='hk_score baseline (boot dir or score json)')
    p.add_argument('--end-grace', type=float, default=5.0, help='seconds between an END_ON match and the queries/reset (default 5)')
    p.add_argument('--default-end-after', type=float, default=90, metavar='S', help='for a request with neither END_ON nor END_AFTER: '
                   'end S seconds after Home (default 90; -1: let the kernel deadline end it)')
    p.add_argument('--keep-req', action='store_true', help='do not move a finished request to QUEUE_DIR/done/')
    p.add_argument('--skip-image-check', action='store_true', help="skip the shared tools/image_tool.py check (an image built by a lane's forked tool)")
    p.add_argument('--lock', default='hk-session', help='phone lease name for tools/hk to-fastboot (default hk-session)')
    p.add_argument('--to-fastboot-wait', type=int, default=240)
    p.add_argument('--cache', help='dyld shared cache for symbols (passed to hk_cycle)')
    p.add_argument('--timeouts', help='passed to hk_cycle (k=v,...)')
    p.add_argument('--poll', type=float, help='passed to hk_cycle')
    p.add_argument('--check', action='store_true', help='parse and validate the queue, print it, touch nothing')
    a = p.parse_args(argv)
    if not a.queue and not a.return_only:
        p.error('give QUEUE_DIR, or --return')
    if a.queue and not Path(a.queue).is_dir():
        p.error(f'no such queue directory: {a.queue}')
    if a.return_only and a.stay:
        p.error('--return and --stay contradict each other')
    if a.return_only and not (a.results or a.queue):
        p.error('--return needs --results DIR (or the queue directory) for its report')
    return a


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    if a.check:
        bad = 0
        for req, errors in load_queue(a.queue):
            done = a.results and (Path(a.results) / req['req'] / 'REPORT.md').is_file()
            print(f"{req['req']}: {'INVALID' if errors else 'ok'}{' (done)' if done else ''}  image={req.get('image')} mach={req.get('mach')} "
                  f"name={req.get('name')} wait={req.get('wait')} end_on={req.get('end_on')!r} end_after={req.get('end_after')} "
                  f"queries={req.get('queries')!r} ui={req.get('ui')} expect={req.get('expect')!r}")
            print(f"    why: {req.get('why')}")
            for e in errors:
                print(f'    ERROR {e}')
                bad += 1
        return EXIT_FAIL if bad else EXIT_OK
    return Session(a).main()


if __name__ == '__main__':
    sys.exit(main())
