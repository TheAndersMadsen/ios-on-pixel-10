#!/usr/bin/env python3
"""One unattended iOS test cycle on the phone, from m1box, ending in one report. research/ios26-phaseb-r1/live/HARNESS.md.

  tools/hk_cycle.py --image research/images/X[/boot.img] --mach K.unstripped [--ui SCRIPT.ui|settings]
                    [--expect EXPECT.yaml] [--deadline-wait S] [--out DIR] [--name NAME]
  tools/hk_cycle.py --report-only CYCLE_DIR [--expect EXPECT.yaml]      # re-run the analysis and the report; no device

Steps (each bounded, each recorded in cycle.log and report.json):
  1. preflight   arguments, image check (image_tool / chooser_ios_image), kernel UUID in the image, the Mac reachable,
                 the image and kernel on the Mac (synced if missing, refused if different unless --overwrite-mac),
                 the phone's state (android / fastboot / recovery / ios / unknown); Android is rebooted to fastboot.
  2. boot        bootios mode (A7 images): tools/live_boot.sh (run-attempt: AVB gate, force-fastboot on, fastboot boot,
                 live console, park, ramdump). plain mode (chooser images, which fail the AVB gate): force-fastboot on,
                 the usbcon reader, bare `fastboot boot`, own park watch and tools/capture-fastboot.py on the Mac.
                 With --ui, the UI runner drives the live boot; live screenshots every --shot-every s (blazer_usbcon_snap=1).
  3. park        wait for the deadline or panic reset to fastboot, pull the ramdump, decode the hk_screen PNG.
  4. return      force-fastboot off, fastboot reboot, wait for boot_completed, research/ios26-dualboot-r8/return-check.sh.
  5. analysis    expectations (pass/fail per feature), usertraps/userabort/HKMAIN stalls symbolicated against the dyld
                 cache (dsc_sym.py), hk_ustack summary (ustack_sym.py), respawns, crashes, panics.
  6. report      DIR/report.md (screenshots inline) and DIR/report.json.

Ctrl-C (or SIGTERM/SIGHUP): 1st stops the UI and screenshots, the boot still runs to its park and its ramdump is pulled;
2nd abandons the boot (no ramdump); the return to Android always runs; 3rd abandons the return (the phone is left as is).
Never cold-resets the phone (a power+volume-down reset wipes RAM): an iOS boot is always left to end at its kernel deadline.

Exit: 0 all required expectations PASS and the return check PASS; 1 an expectation or the return check failed;
2 usage; 3 preflight refused (phone untouched or back in Android); 4 boot/park/capture error; 5 the phone is NOT back
in Android (needs the owner); 130 interrupted (after the return).

Test doubles (tools/test_hk_cycle.py): HK_CYCLE_PB (directory with adb/fastboot/mac), HK_CYCLE_LIVE_BOOT,
HK_CYCLE_SCREENSHOT, HK_CYCLE_RETURN_CHECK, HK_CYCLE_CAPTURE_PY, HK_CYCLE_MAC_DIR, HK_CYCLE_USBCON_CMD.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import mmap
import os
from pathlib import Path
import re
import shlex
import signal
import struct
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = '/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e'
DSC_SYM = ROOT / 'research/ios26-apps-r1/tools/m1box/dsc_sym.py'
USTACK_SYM = ROOT / 'research/ios26-phaseb-r1/live/ustack/tools/ustack_sym.py'
LIVE_PROFILE = ROOT / 'tools/live_profile.py'
CRASHDOC = ROOT / 'tools/crashdoc.py'          # CRASHDOC: boot segmentation, symbolication, crashes.json
PROBE_EVAL = ROOT / 'tools/probe_eval.py'      # VERIFY: the one row-verdict evaluator (docs/probes.yaml)

# Every bound, in seconds. --timeouts k=v,k=v overrides (the host tests shrink them).
TIMEOUTS = dict(
    probe=25,            # one adb/fastboot/mac status call
    mac=60,              # one small mac command (sha, HEAD)
    sync=1200,           # copying an image to the Mac
    image_check=180,
    to_fastboot=150,     # adb reboot bootloader -> fastboot devices
    ff=30,               # fastboot oem force-fastboot on/off and its readback
    fb_boot=240,         # plain mode: fastboot boot (upload + boot)
    settle=20,           # plain mode: after fastboot boot, before a park can count
    boot_watch=300,      # run-attempt's own watch floor (bootios: watch = max(300, wait))
    boot_extra=900,      # live_boot's own bound = wait + watch + this
    console_start=10,    # plain mode: the reader must still run after this
    capture=900,         # plain mode: capture-fastboot.py on the Mac
    reader=240,          # read-ramdump.py
    shot=120,            # one live screenshot
    shot_start=30,       # after DISPLAY/CONSOLE_CONNECTED, before the first screenshot
    ui=3600,             # the UI runner
    park_wait=1500,      # return: an iOS boot still running, wait this long for its deadline park
    android_boot=420,    # fastboot reboot -> sys.boot_completed=1
    return_check=900,
    analysis=600,        # ustack_sym.py
    unknown_wait=90,     # preflight: phone state unknown, wait this long for it to show up
)
EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_PREFLIGHT, EXIT_BOOT, EXIT_NOT_ANDROID, EXIT_INTERRUPTED = 0, 1, 2, 3, 4, 5, 130


class Refused(Exception):
    """A step refused or failed with a named error state."""
    def __init__(self, state, detail, code=EXIT_PREFLIGHT):
        super().__init__(f'{state}: {detail}')
        self.state, self.detail, self.code = state, detail, code


class Interrupted(Exception):
    pass


def now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cmdline_args(cmdline):
    out = {}
    for tok in (cmdline or '').split():
        k, _, v = tok.partition('=')
        out[k] = v
    return out


def mach_uuid(path):
    with open(path, 'rb') as f:
        head = f.read(0x10000)
    if len(head) < 32 or struct.unpack_from('<I', head)[0] != 0xfeedfacf:
        raise ValueError(f'not a 64-bit Mach-O: {path}')
    off = 32
    for _ in range(struct.unpack_from('<I', head, 16)[0]):
        if off + 8 > len(head):
            break
        cmd, size = struct.unpack_from('<II', head, off)
        if cmd == 0x1b:
            return head[off + 8:off + 24]
        if size < 8:
            break
        off += size
    raise ValueError(f'no LC_UUID in {path}')


def image_has(image, needle):
    with open(image, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        return data.find(needle) >= 0


# ----------------------------------------------------------------------------------------------- expectations
def load_expect(path):
    text = Path(path).read_text()
    try:
        doc = json.loads(text)
    except ValueError:
        try:
            import yaml
        except ImportError as e:
            raise ValueError(f'{path}: not JSON and PyYAML is missing') from e
        doc = yaml.safe_load(text)
    if isinstance(doc, dict) and 'expect' not in doc and isinstance(doc.get('probes'), list):
        doc['expect'] = doc['probes']           # docs/probes.yaml spelling
    if not isinstance(doc, dict) or not isinstance(doc.get('expect'), list):
        raise ValueError(f'{path}: needs a top-level "expect:" (or "probes:") list')
    seen = set()
    for i, row in enumerate(doc['expect']):
        if not isinstance(row, dict) or not row.get('id'):
            raise ValueError(f'{path}: expect[{i}] needs an id')
        if row['id'] in seen:
            raise ValueError(f'{path}: duplicate id {row["id"]}')
        seen.add(row['id'])
        unknown = set(row) - {'id', 'feature', 'need', 'any', 'forbid', 'values', 'marker', 'ui', 'needs_input',
                              'required', 'note', 'source', 'readme', 'scope'}
        if unknown:
            raise ValueError(f'{path}: {row["id"]}: unknown keys {sorted(unknown)}')
        for key in ('need', 'any', 'forbid'):
            for rx in row.get(key) or []:
                re.compile(rx)
        for v in row.get('values') or []:
            if not isinstance(v, dict) or 're' not in v or re.compile(v['re']).groups < 1:
                raise ValueError(f'{path}: {row["id"]}: values need re: with one group')
        if row.get('source', 'boot') not in ('boot', 'live', 'dump'):
            raise ValueError(f'{path}: {row["id"]}: source is boot, live or dump')
    return doc


DEVLINE = re.compile(r'^(\S+)(\s+(?:fastboot|device|recovery|sideload|rescue|unauthorized|offline|bootloader)\b)', re.M)


def redact(text):
    """Device serials never reach a file (they stay out of git): device-list rows and the known ANDROID_SERIAL."""
    s = os.environ.get('ANDROID_SERIAL')
    if s and len(s) >= 6:
        text = text.replace(s, 'SERIAL')
    text = DEVLINE.sub(lambda m: m.group(0) if m.group(1) in ('List', 'SERIAL') else 'SERIAL' + m.group(2), text)
    return re.sub(r'(serial(?:no)?[ :=]+)[A-Za-z0-9]{8,}', r'\1SERIAL', text, flags=re.I)


def first_match(rx, texts):
    r = re.compile(rx, re.M)
    for src, text in texts:
        m = r.search(text)
        if m:
            line_start = text.rfind('\n', 0, m.start()) + 1
            line_end = text.find('\n', m.end())
            return src, text[line_start:line_end if line_end >= 0 else len(text)][:220]
    return None


def evaluate(doc, sources, markers, ui):
    """sources: {'live': text, 'dump': text}; markers: set of marker names; ui: {'ran': bool, 'steps': {name: ok}}."""
    rows = []
    for row in doc['expect']:
        src = row.get('source', 'boot')
        texts = [(k, sources[k]) for k in (('live', 'dump') if src == 'boot' else (src,)) if sources.get(k)]
        r = dict(id=row['id'], feature=row.get('feature', row['id']), required=row.get('required', True),
                 note=row.get('note', ''), evidence=[], missing=[], forbidden=[])
        if not texts and not row.get('ui') and not row.get('marker'):
            r['verdict'] = 'NO_DATA'
            rows.append(r)
            continue
        for rx in row.get('forbid') or []:
            hit = first_match(rx, texts)
            if hit:
                r['forbidden'].append(dict(re=rx, source=hit[0], line=hit[1]))
        for rx in row.get('need') or []:
            hit = first_match(rx, texts)
            (r['evidence'].append(dict(re=rx, source=hit[0], line=hit[1])) if hit else r['missing'].append(rx))
        if row.get('any'):
            hits = [(rx, first_match(rx, texts)) for rx in row['any']]
            got = [(rx, h) for rx, h in hits if h]
            if got:
                r['evidence'].append(dict(re=got[0][0], source=got[0][1][0], line=got[0][1][1]))
            else:
                r['missing'].append('any of: ' + ' | '.join(row['any']))
        for v in row.get('values') or []:
            nums = []
            for _, text in texts:
                for m in re.finditer(v['re'], text, re.M):
                    try:
                        nums.append(float(m.group(1)))
                    except (TypeError, ValueError):
                        pass
            agg = v.get('agg', 'max')
            val = (max(nums) if agg == 'max' else min(nums) if agg == 'min' else nums[-1] if agg == 'last'
                   else len(nums) if agg == 'count' else None) if (nums or agg == 'count') else None
            ok = val is not None and ('min' not in v or val >= v['min']) and ('max' not in v or val <= v['max'])
            desc = f"{agg}({v['re']}) = {val}" + (f" >= {v['min']}" if 'min' in v else '') + (f" <= {v['max']}" if 'max' in v else '')
            (r['evidence'] if ok else r['missing']).append(desc if not ok else dict(re=v['re'], source='value', line=desc))
        if row.get('marker'):
            (r['evidence'].append(dict(re='marker', source='markers', line=row['marker'])) if row['marker'] in markers
             else r['missing'].append('marker ' + row['marker']))
        if row.get('ui'):
            step = ui.get('steps', {}).get(row['ui'])
            if step is True:
                r['evidence'].append(dict(re='ui', source='ui', line=f"step {row['ui']} ok"))
            else:
                r['missing'].append(f"ui step {row['ui']} " + ('not run' if step is None else 'failed'))
        if r['forbidden']:
            r['verdict'] = 'FAIL'
        elif not r['missing']:
            r['verdict'] = 'PASS'
        elif row.get('needs_input') and not (ui.get('ran') or ui.get('attended')):
            r['verdict'] = 'NOT_EXERCISED'
        else:
            r['verdict'] = 'FAIL'
        rows.append(r)
    return rows


# ----------------------------------------------------------------------------------------------- console analysis
USERTRAP = re.compile(r'^usertrap: (?P<name>[^\s\[]+)\[(?P<pid>\d+)\] exception (?P<exc>\d+) code (?P<code>\S+) (?P<addr>\S+): '
                      r'pc (?P<pc>0x[0-9a-f]+) lr (?P<lr>0x[0-9a-f]+) sp \S+, shared cache slide (?P<slide>0x[0-9a-f]+)'
                      r'(?:, main header (?P<main>0x[0-9a-f]+))?', re.M)
USERTRAP_FROM = re.compile(r'^usertrap:\s+called from (0x[0-9a-f]+)')
USERABORT = re.compile(r'^userabort: (?P<name>[^\s\[]+)\[(?P<pid>\d+)\] aborts, shared cache slide (?P<slide>0x[0-9a-f]+); '
                       r'called from:(?P<frames>(?: 0x[0-9a-f]+)*)', re.M)
CRASHLINE = re.compile(r'CRASH (?P<name>\S+) reason (?P<reason>.{0,60})$', re.M)
EXITSIG = re.compile(r'\((?:[^\s()]*/)?(?P<svc>[^/\s()]+) \[(?P<pid>\d+)\]\).*exited due to (?P<why>SIG\w+|exit\([1-9]\d*\))', re.M)
EXEC = re.compile(r'(?:^|\s)exec ([^\s/]+)$', re.M)
SPAWN = re.compile(r'Successfully spawned ([^\s\[]+)\[(\d+)\]', re.M)
CRASHED_TIMES = re.compile(r'\((?:[^\s()]*/)?([^/\s()]+) \[\d+\]\).*service has crashed (\d+) times in a row', re.M)
PANIC = re.compile(r'^panic\((?P<body>.{0,240})', re.M)
HKMAIN = re.compile(r'^HKMAIN: (?P<name>[^\s\[]+)\[(?P<pid>\d+)\] t=(?P<t>\d+) pings=(?P<pings>\d+) wait=(?P<wait>\d+) '
                    r'state=(?P<state>\S+) ev touch=(?P<touch>\d+) press=(?P<press>\d+) other=(?P<other>\d+) stalls=(?P<stalls>\d+)', re.M)
HKSTALL = re.compile(r'^HKMAIN: stall (?P<ms>\d+) ms pc (?P<pc>0x[0-9a-f]+) lr (?P<lr>0x[0-9a-f]+) sp \S+ dsc_slide (?P<slide>0x[0-9a-f]+)'
                     r' main_slide (?P<main>0x[0-9a-f]+)', re.M)
LIVE_STAMP = re.compile(r'^\d\d:\d\d:\d\d\.\d{3} ')
USBCON_STAMP = re.compile(r'^\[\s*\d+\.\d+\] ')
MARKER = re.compile(r'^LIVEBOOT (?P<wall>\S+) \+(?P<s>[\d.]+) (?P<name>[A-Z_]+)(?: (?P<detail>.*))?$')


class Symbolizer:
    """dsc_sym.py's lookup, in process, one cache load for the whole report."""
    def __init__(self, cache):
        self.cache_path, self.cache, self.mod, self.memo, self.error = cache, None, None, {}, None
        if not cache or not Path(cache).is_file():
            self.error = f'no dyld cache at {cache}'
            return
        try:
            self.mod = load_module('dsc_sym', DSC_SYM)
            self.cache = self.mod.LP.CacheImages(cache)
        except Exception as e:     # a broken cache must not stop the report
            self.error = f'cache unusable: {e}'

    @property
    def uuid(self):
        return self.cache.uuid if self.cache else None

    def name(self, addr, slide, main=None):
        if isinstance(addr, str):
            addr = int(addr, 16)
        slide = int(slide, 16) if isinstance(slide, str) else (slide or 0)
        if main:
            m = int(main, 16) if isinstance(main, str) else main
            if m <= addr < m + 0x10000000:
                return f'main+{addr - m:#x}'
        if not self.cache:
            return f'{addr:#x}'
        u = addr - slide
        try:
            info = self.cache.who(u) if u > 0 else None
        except Exception:
            info = None
        if not info:
            return f'{addr:#x} (not in cache)'
        base = u - info['image_offset']
        syms = self.memo.get(base)
        if syms is None:
            try:
                syms = self.memo[base] = self.mod.image_symbols(self.cache, base)
            except Exception:
                syms = self.memo[base] = []
        img = info['image'].rsplit('/', 1)[-1]
        lo, hi = 0, len(syms)
        while lo < hi:
            mid = (lo + hi) // 2
            if syms[mid][0] <= u:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return f'{img}+{info["image_offset"]:#x}'
        value, sym = syms[lo - 1]
        return f'{img} {sym}+{u - value:#x}'

    def close(self):
        if self.cache:
            self.cache.close()


def strip_live(text):
    out = []
    for line in text.replace('\r', '').splitlines():
        line = LIVE_STAMP.sub('', line, count=1)
        out.append(USBCON_STAMP.sub('', line, count=1))
    return '\n'.join(out)


def dump_text(kernel_log):
    """The current boot's console text from a ramdump kernel.log (live_profile.decode_dump), or (None, why)."""
    try:
        lp = load_module('live_profile', LIVE_PROFILE)
        segments, meta = lp.decode_dump(kernel_log)
    except Exception as e:
        return None, f'no current-boot text in the dump: {e}'
    text = b''.join(data for _, data in segments).decode('utf-8', 'replace').replace('\r', '')
    return text, dict(bytes=len(text), ring_from=meta.get('ring_from'), head_omitted=meta.get('unproved_head_omitted'),
                      nonce=hex(meta['epoch']['nonce']))


def analyse_console(text, sym):
    crashes, by = [], {}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = USERTRAP.match(line)
        if m:
            frames = [m['pc'], m['lr']]
            for nxt in lines[i + 1:i + 9]:
                f = USERTRAP_FROM.match(nxt)
                if not f:
                    break
                frames.append(f.group(1))
            crashes.append(dict(kind='usertrap', name=m['name'], pid=int(m['pid']), what=f"exception {m['exc']} code {m['code']} {m['addr']}",
                                slide=m['slide'], main=m['main'], frames=frames[:8]))
            continue
        m = USERABORT.match(line)
        if m:
            crashes.append(dict(kind='userabort', name=m['name'], pid=int(m['pid']), what='abort', slide=m['slide'], main=None,
                                frames=m['frames'].split()[:8]))
    for c in crashes:
        c['symbols'] = [sym.name(a, c['slide'], c['main']) for a in c['frames']]
        key = (c['kind'], c['name'], c['symbols'][0] if c['symbols'] else '')
        g = by.setdefault(key, dict(kind=c['kind'], name=c['name'], what=c['what'], count=0, pids=[], top=c['symbols'][:6]))
        g['count'] += 1
        if c['pid'] not in g['pids']:
            g['pids'].append(c['pid'])
    crash_lines = {}
    for m in CRASHLINE.finditer(text):
        k = (m['name'], m['reason'].strip())
        crash_lines[k] = crash_lines.get(k, 0) + 1
    exits = {}
    for m in EXITSIG.finditer(text):
        k = (m['svc'], m['why'])
        exits[k] = exits.get(k, 0) + 1
    execs = {}
    for m in EXEC.finditer(text):
        execs[m.group(1)] = execs.get(m.group(1), 0) + 1
    spawns = {}
    for m in SPAWN.finditer(text):
        spawns[m.group(1)] = spawns.get(m.group(1), 0) + 1
    crashed_times = {}
    for m in CRASHED_TIMES.finditer(text):
        crashed_times[m.group(1)] = max(crashed_times.get(m.group(1), 0), int(m.group(2)))
    names = set(execs) | set(spawns)
    respawns = sorted(((n, max(execs.get(n, 0), spawns.get(n, 0)) - 1) for n in names
                       if max(execs.get(n, 0), spawns.get(n, 0)) > 1 and n != 'xpcproxy'), key=lambda x: -x[1])
    panics = []
    for m in PANIC.finditer(text):
        body = m['body']
        panics.append(dict(kind='deadline' if 'blazer-root: deadline' in body else 'panic', line=body[:240]))
    hkmain = {}
    for m in HKMAIN.finditer(text):
        hkmain[f"{m['name']}[{m['pid']}]"] = {k: m[k] for k in ('t', 'pings', 'wait', 'state', 'touch', 'press', 'other', 'stalls')}
    stalls = {}
    for m in HKSTALL.finditer(text):
        k = (sym.name(m['pc'], m['slide'], m['main']), sym.name(m['lr'], m['slide'], m['main']))
        s = stalls.setdefault(k, dict(pc=k[0], lr=k[1], count=0, max_ms=0))
        s['count'] += 1
        s['max_ms'] = max(s['max_ms'], int(m['ms']))
    return dict(
        crashes=sorted(by.values(), key=lambda g: -g['count']),
        crash_lines=[dict(name=k[0], reason=k[1], count=v) for k, v in sorted(crash_lines.items(), key=lambda kv: -kv[1])],
        exits=[dict(service=k[0], why=k[1], count=v) for k, v in sorted(exits.items(), key=lambda kv: -kv[1])],
        respawns=[dict(name=n, respawns=r, crashed_in_a_row=crashed_times.get(n)) for n, r in respawns],
        execs=dict(sorted(execs.items(), key=lambda kv: -kv[1])[:40]),
        panics=panics, hkmain=hkmain, hkmain_stalls=sorted(stalls.values(), key=lambda s: -s['count'])[:12],
        ustack_lines=text.count('HK USTACK:'), lines=text.count('\n') + 1)


def home_rule(markers, sources):
    """Home reached? UI_READY alone misses real boots (the int1 live run: no SPRINGBOARD marker, because launchd's
    'Successfully spawned SpringBoard' line is not in the console; 'exec SpringBoard' is). Rule (interim, until
    UIDRIVE.md's wait_home): UI_READY, or SpringBoard exec'd + touch client + button client + frames."""
    if 'UI_READY' in markers:
        return dict(home=True, rule='UI_READY marker')
    text = '\n'.join(sources.values())
    have = dict(springboard='SPRINGBOARD' in markers or re.search(r'(?:^|\s)exec SpringBoard$', text, re.M) is not None,
                touch='TOUCH_CLIENT' in markers or 'SWEET HID: SweetHIDTouch open by' in text,
                buttons='BUTTON_CLIENT' in markers or 'SWEET HID: SweetHIDButtons open by' in text,
                frames='FRAMES' in markers or re.search(r'HK TOP: t=\d+ frames\+[1-9]|SWEET FB: rate swaps (?:[1-9][\d.]*|0\.[1-9])/s', text) is not None)
    return dict(home=all(have.values()), rule='exec SpringBoard + touch + buttons + frames', parts=have)


def read_markers(path):
    out = []
    try:
        for line in Path(path).read_text(errors='replace').splitlines():
            m = MARKER.match(line)
            if m:
                out.append(dict(name=m['name'], s=float(m['s']), wall=m['wall'], detail=m['detail'] or ''))
    except OSError:
        pass
    return out


# ----------------------------------------------------------------------------------------------- the cycle
class Cycle:
    def __init__(self, args):
        self.args = args
        self.t = dict(TIMEOUTS)
        for kv in filter(None, (args.timeouts or '').split(',')):
            k, _, v = kv.partition('=')
            if k not in self.t:
                raise SystemExit(f'hk_cycle: unknown timeout {k}; known: {", ".join(self.t)}')
            self.t[k] = float(v)
        self.poll = args.poll
        pb = os.environ.get('HK_CYCLE_PB', str(Path.home() / '.local/share/phone-bridge/bin'))
        self.env = dict(os.environ, PATH=pb + os.pathsep + os.environ.get('PATH', ''))
        self.adb, self.fastboot, self.mac = (str(Path(pb) / n) if (Path(pb) / n).exists() else n for n in ('adb', 'fastboot', 'mac'))
        self.live_boot = os.environ.get('HK_CYCLE_LIVE_BOOT', str(ROOT / 'tools/live_boot.sh'))
        self.screenshot = os.environ.get('HK_CYCLE_SCREENSHOT', str(ROOT / 'tools/screenshot.sh'))
        self.return_check = os.environ.get('HK_CYCLE_RETURN_CHECK', str(ROOT / 'research/ios26-dualboot-r8/return-check.sh'))
        self.mac_dir = os.environ.get('HK_CYCLE_MAC_DIR') or self._mirror()
        self.interrupts = 0
        self.lock = threading.RLock()
        self.children = set()
        self.boot_done = threading.Event()
        self.touched = False          # the phone's state was changed by this cycle
        self.ff_armed = False         # force-fastboot was (or may have been) armed by this cycle
        self.report = dict(schema=1, tool='tools/hk_cycle.py', tool_sha256=sha256(__file__), started=now_iso(),
                           steps=[], errors=[], phone_states=[], screenshots=[], timings={})
        self.t0 = time.monotonic()
        self.out = None
        self.log_f = None
        self.seq = 0

    # ------------------------------------------------------------------ plumbing
    def _mirror(self):
        for m in os.environ.get('PB_MIRRORS', '/srv/dev/repos/personal/hackios=Developer/personal/hackios').split():
            loc, _, mac = m.partition('=')
            if str(ROOT) == loc or str(ROOT).startswith(loc + '/'):
                return mac + str(ROOT)[len(loc):]
        return 'Developer/personal/hackios'

    def since(self):
        return round(time.monotonic() - self.t0, 1)

    def log(self, msg, quiet=False):
        line = f'{datetime.datetime.now().strftime("%H:%M:%S")} +{self.since():7.1f} {msg}'
        with self.lock:
            if self.log_f:
                self.log_f.write(line + '\n')
                self.log_f.flush()
        if not quiet:
            print(f'hk_cycle: {msg}', flush=True)

    def step(self, name, **kw):
        rec = dict(step=name, t=self.since(), wall=now_iso(), **kw)
        self.report['steps'].append(rec)
        self.log(f'[{name}] ' + ' '.join(f'{k}={v}' for k, v in kw.items()))
        return rec

    def error(self, state, detail):
        self.report['errors'].append(dict(state=state, detail=detail, t=self.since()))
        self.log(f'ERROR {state}: {detail}')

    def on_signal(self, signum, _frame):
        self.interrupts += 1
        what = {1: 'stopping the UI and screenshots; the boot runs on to its park and ramdump (Ctrl-C again abandons the boot)',
                2: 'abandoning the boot; returning the phone to Android (Ctrl-C again abandons the return)',
                }.get(self.interrupts, 'abandoning the return: the phone is left as it is')
        print(f'\nhk_cycle: interrupt {self.interrupts} ({signal.Signals(signum).name}): {what}', file=sys.stderr, flush=True)
        if self.log_f:
            self.log(f'interrupt {self.interrupts}: {what}', quiet=True)

    def check_interrupt(self, level):
        if self.interrupts >= level:
            raise Interrupted(f'interrupt level {self.interrupts}')

    def kill(self, p, grace=5):
        """Stop a child started in its own session: TERM to its process group, then KILL. Never pattern kills."""
        if p.poll() is not None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            p.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def spawn(self, cmd, out_path, env=None, cwd=None, pipe_stdout=False):
        """stdin stays an open pipe for the child's whole life (the bridge's stdin watchdog stops the remote command
        when stdin closes). Own session: a terminal Ctrl-C reaches only hk_cycle, which decides."""
        fo = None if pipe_stdout else open(out_path, 'ab')
        p = subprocess.Popen([str(c) for c in cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE if pipe_stdout else fo,
                             stderr=subprocess.STDOUT, cwd=str(cwd or ROOT), env=env or self.env, start_new_session=True)
        if fo:
            fo.close()
        with self.lock:
            self.children.add(p)
        return p

    def reap(self, p):
        with self.lock:
            self.children.discard(p)
        for s in (p.stdin, p.stdout):
            try:
                s and s.close()
            except OSError:
                pass

    def run(self, cmd, timeout, label, kill_at=3, env=None, cwd=None, check_text=None):
        """Bounded child. Returns (rc or None on timeout, output text). Ctrl-C at level >= kill_at kills it and raises."""
        self.seq += 1
        out_path = self.tmp / f'{self.seq:03d}-{label}.out'
        self.log(f'$ {" ".join(shlex.quote(str(c)) for c in cmd)}  (bound {timeout:.0f}s)', quiet=True)
        p = self.spawn(cmd, out_path, env=env, cwd=cwd)
        end = time.monotonic() + timeout
        rc = None
        try:
            while True:
                try:
                    rc = p.wait(timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if self.interrupts >= kill_at:
                    self.kill(p)
                    raise Interrupted(label)
                if time.monotonic() > end:
                    self.log(f'{label}: timed out after {timeout:.0f}s, stopping it')
                    self.kill(p)
                    rc = None
                    break
        finally:
            self.reap(p)
        text = out_path.read_text(errors='replace') if out_path.exists() else ''
        red = redact(text)
        if red != text:
            out_path.write_text(red)
        text = red
        self.log(f'  -> rc={rc} {text.strip().splitlines()[-1][:160] if text.strip() else ""}', quiet=True)
        return rc, text

    def sleep(self, seconds, kill_at=3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.check_interrupt(kill_at)
            time.sleep(min(0.25, max(0.0, end - time.monotonic())))

    # ------------------------------------------------------------------ phone state
    def serial_ok(self, line):
        s = os.environ.get('ANDROID_SERIAL')
        return not s or line.split()[0] == s

    def phone_state(self, kill_at=3):
        rc, out = self.run([self.fastboot, 'devices'], self.t['probe'], 'fastboot-devices', kill_at=kill_at)
        if rc == 0 and any(re.search(r'\sfastboot\s*$', l) and self.serial_ok(l) for l in out.splitlines() if l.strip()):
            return 'fastboot'
        rc, out = self.run([self.adb, 'devices'], self.t['probe'], 'adb-devices', kill_at=kill_at)
        for l in out.splitlines():
            parts = l.split()
            if len(parts) >= 2 and parts[0] != 'List' and self.serial_ok(l):
                if parts[1] == 'device':
                    return 'android'
                if parts[1] in ('recovery', 'sideload', 'rescue'):
                    return 'recovery'
                if parts[1] in ('unauthorized', 'offline'):
                    return 'android-' + parts[1]
        rc, out = self.run([self.mac, 'usb'], self.t['probe'], 'mac-usb', kill_at=kill_at)
        if re.search(r'\b1209:000[123]\b', out):
            return 'ios'
        if re.search(r'\b18d1:', out):
            return 'usb-google'          # a Google USB id without adb/fastboot: booting
        return 'unknown'

    def note_state(self, state, why):
        self.report['phone_states'].append(dict(t=self.since(), state=state, why=why))
        self.log(f'phone: {state} ({why})')
        return state

    def boot_completed(self, kill_at=3):
        rc, out = self.run([self.adb, 'shell', 'getprop', 'sys.boot_completed'], self.t['probe'], 'boot-completed', kill_at=kill_at)
        return rc == 0 and out.strip().endswith('1')

    def wait_for(self, want, bound, kill_at, label, also=()):
        """Poll phone_state until it is in want (or also); returns the state or the last state seen at the bound."""
        end = time.monotonic() + bound
        st = None
        while True:
            st = self.phone_state(kill_at=kill_at)
            if st in want or st in also:
                return st
            if time.monotonic() > end:
                return st
            self.sleep(self.poll, kill_at)

    def force_fastboot(self, on, kill_at):
        word = 'on' if on else 'off'
        rc, out = self.run([self.fastboot, 'oem', 'force-fastboot', word], self.t['ff'], f'ff-{word}', kill_at=kill_at)
        rc2, out2 = self.run([self.fastboot, 'oem', 'force-fastboot'], self.t['ff'], 'ff-read', kill_at=kill_at)
        state = re.search(r'force-fastboot (on|off)', out2)
        ok = rc == 0 and state is not None and state.group(1) == word
        self.step('force-fastboot', want=word, rc=rc, readback=state.group(1) if state else 'unknown', ok=ok)
        return ok

    # ------------------------------------------------------------------ 1. preflight
    def preflight(self):
        a = self.args
        img = Path(a.image)
        image = img / 'boot.img' if img.is_dir() else img
        if not image.is_file():
            raise Refused('BAD_ARGS', f'image not found: {image}', EXIT_USAGE)
        image = image.resolve()
        idir = image.parent
        mach = Path(a.mach).resolve() if a.mach else None
        if mach and not mach.is_file():
            raise Refused('BAD_ARGS', f'kernel not found: {mach}', EXIT_USAGE)
        for p in [image] + ([mach] if mach else []):
            try:
                p.relative_to(ROOT)
            except ValueError:
                raise Refused('BAD_ARGS', f'{p} is outside the checkout {ROOT}; the Mac mirror cannot see it', EXIT_USAGE)
        manifest = {}
        if (idir / 'manifest.json').is_file():
            manifest = json.loads((idir / 'manifest.json').read_text())
        kind = str(manifest.get('kind', ''))
        chooser = kind.startswith('chooser') or idir.name.startswith('chooser')
        cmdline = (manifest.get('ios') or {}).get('cmdline', '') if chooser else manifest.get('cmdline', '')
        cargs = cmdline_args(cmdline)
        mode = a.mode if a.mode != 'auto' else ('plain' if chooser else 'bootios')
        cold_safe = 'TGL_USB_DISABLE=1' in json.dumps(manifest.get('cflags', ''))
        console = cargs.get('blazer_usbcon') == '1' and not cold_safe and not a.no_console
        snap = console and cargs.get('blazer_usbcon_snap') == '1'
        deadline = int(cargs['blazer_deadline']) if cargs.get('blazer_deadline', '').isdigit() else None
        wait = a.deadline_wait or ((deadline + 180) if deadline else 1200)
        info = dict(image=str(image.relative_to(ROOT)), image_dir=str(idir.relative_to(ROOT)), image_sha256=sha256(image),
                    image_name=manifest.get('name', idir.name), kind=kind or 'a7', mode=mode, chooser=chooser,
                    mach=str(mach.relative_to(ROOT)) if mach else None, mach_sha256=sha256(mach) if mach else None,
                    deadline_s=deadline, wait_s=wait, console=console, live_snapshots=snap,
                    live_input=cargs.get('blazer_usbcon_input') == '1', hk_screen=cargs.get('hk_screen'),
                    hk_ustack=cargs.get('hk_ustack'), cold_safe=cold_safe, cmdline_bytes=len(cmdline))
        self.report['image'] = info
        self.image, self.idir, self.mach = image, idir, mach
        self.step('args', **{k: info[k] for k in ('image', 'mode', 'deadline_s', 'wait_s', 'console', 'live_snapshots')})

        if a.ui:
            if not console:
                raise Refused('UI_WITHOUT_CONSOLE', 'the UI runner needs the live usbcon console (blazer_usbcon=1, not cold-safe)')
            if not info['live_input'] and not a.force_ui:
                raise Refused('UI_WITHOUT_INPUT', 'the image has no blazer_usbcon_input=1, so live input is refused by the '
                              'kernel; drop --ui or pass --force-ui (snapshots only)')
            self.ui_cmd = self.ui_command()
        if self.expect_doc and self.expect_doc.get('image') and self.expect_doc['image'] != info['image_name']:
            self.log(f"warning: {a.expect} is written for {self.expect_doc['image']}, this image is {info['image_name']}")

        # image check
        if not a.skip_image_check:
            tool = 'tools/chooser_ios_image.py' if chooser else 'tools/image_tool.py'
            if not (ROOT / tool).is_file():
                raise Refused('IMAGE_CHECK_FAILED', f'{tool} is missing')
            rc, out = self.run([sys.executable, '-I', str(ROOT / tool), 'check', str(idir)], self.t['image_check'], 'image-check', kill_at=1)
            ok = rc == 0 and re.search(r'^OK .*bootable', out, re.M) is not None
            info['image_check'] = (out.strip().splitlines() or ['(no output)'])[-1][:300]
            self.step('image-check', tool=tool, ok=ok, line=info['image_check'])
            if not ok:
                raise Refused('IMAGE_CHECK_FAILED', info['image_check'])
        if mach:
            try:
                uuid = mach_uuid(mach)
            except ValueError as e:
                raise Refused('KERNEL_MISMATCH', str(e))
            if not image_has(image, uuid):
                raise Refused('KERNEL_MISMATCH', f'{mach.name} (UUID {uuid.hex()}) is not the kernel in {image}')
            info['mach_uuid'] = uuid.hex()
        if mode == 'bootios' and not mach:
            raise Refused('BAD_ARGS', 'bootios mode needs --mach (the panic decode and symbols use it)', EXIT_USAGE)

        # the Mac
        rc, out = self.run([self.mac, '--cd', self.mac_dir, '--', 'git', 'rev-parse', 'HEAD'], self.t['mac'], 'mac-head', kill_at=1)
        if rc != 0:
            raise Refused('MAC_UNREACHABLE', (out.strip().splitlines() or ['no output'])[-1][:200])
        mac_head = out.strip().split()[-1] if out.strip() else ''
        here = subprocess.run(['git', '-C', str(ROOT), '--no-optional-locks', 'rev-parse', 'HEAD'], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=30).stdout.strip()
        info['m1box_head'], info['mac_head'] = here, mac_head
        if here and mac_head and here != mac_head:
            self.log(f'note: the Mac checkout is at {mac_head[:10]}, m1box at {here[:10]}; every mac repo call uses --force')
        if mode == 'bootios':     # plain mode: the fastboot wrapper stages the image itself
            for p in [image] + ([mach] if mach else []):
                self.ensure_on_mac(p)

        # the phone
        st = self.note_state(self.phone_state(kill_at=1), 'preflight')
        if st == 'unknown' or st == 'usb-google' or st.startswith('android-'):
            st = self.note_state(self.wait_for({'android', 'fastboot', 'ios', 'recovery'}, self.t['unknown_wait'], 1, 'unknown'),
                                 'preflight, after waiting')
        if st == 'ios':
            if not a.busy_wait:
                raise Refused('PHONE_IN_IOS', 'an iOS boot is running (USB 1209:000x); let it end at its deadline, or pass '
                              '--busy-wait S to wait for its park. A cold reset would wipe its RAM')
            st = self.note_state(self.wait_for({'fastboot', 'android'}, a.busy_wait, 1, 'busy'), 'after --busy-wait')
            if st == 'fastboot':
                self.ff_armed = True       # it parked: force-fastboot was on for that boot
        if st == 'recovery':
            raise Refused('PHONE_IN_RECOVERY', 'the phone is in recovery: the owner chooses "Try again" (never factory reset)')
        if st == 'android':
            if not os.environ.get('ANDROID_SERIAL'):
                self.pick_serial('adb')
            self.touched = True
            rc, _ = self.run([self.adb, 'reboot', 'bootloader'], self.t['probe'], 'adb-reboot-bootloader', kill_at=1)
            self.step('to-fastboot', rc=rc)
            st = self.note_state(self.wait_for({'fastboot'}, self.t['to_fastboot'], 1, 'to-fastboot'), 'after adb reboot bootloader')
        if st != 'fastboot':
            raise Refused('PHONE_UNKNOWN' if st in ('unknown', 'usb-google') else 'PHONE_NOT_FASTBOOT', f'phone state {st}')
        if not os.environ.get('ANDROID_SERIAL'):
            self.pick_serial('fastboot')
        rc, out = self.run([self.fastboot, 'getvar', 'product'], self.t['probe'], 'getvar-product', kill_at=1)
        if rc != 0 or 'product:' not in out:
            raise Refused('FASTBOOT_UNRESPONSIVE', (out.strip().splitlines() or ['no output'])[-1][:200])
        self.step('preflight-ok', product=re.search(r'product:\s*(\S+)', out).group(1))

    def pick_serial(self, tool):
        cmd = [self.adb, 'devices'] if tool == 'adb' else [self.fastboot, 'devices']
        rc, out = self.run(cmd, self.t['probe'], f'{tool}-serial', kill_at=1)
        want = 'device' if tool == 'adb' else 'fastboot'
        serials = [l.split()[0] for l in out.splitlines() if len(l.split()) >= 2 and l.split()[1] == want and l.split()[0] != 'List']
        if len(serials) != 1:
            raise Refused('SERIAL_AMBIGUOUS', f'{len(serials)} {tool} devices; set ANDROID_SERIAL')
        os.environ['ANDROID_SERIAL'] = self.env['ANDROID_SERIAL'] = serials[0]
        self.report['image']['serial_hash'] = hashlib.sha256(serials[0].encode()).hexdigest()[:12]

    def ensure_on_mac(self, p):
        rel = str(p.relative_to(ROOT))
        local = sha256(p)
        def mac_sha():
            rc, out = self.run([self.mac, '--cd', self.mac_dir, '--', 'sh', '-c', f'shasum -a 256 {shlex.quote(rel)} 2>/dev/null || true'],
                               self.t['mac'], 'mac-sha', kill_at=1)
            m = re.search(r'\b([0-9a-f]{64})\b', out)
            return m.group(1) if m else None
        remote = mac_sha()
        if remote == local:
            self.step('mac-copy', path=rel, state='same')
            return
        if remote and not self.args.overwrite_mac:
            raise Refused('MAC_COPY_DIFFERS', f'the Mac has a different {rel} ({remote[:12]} vs {local[:12]}); the boot would use '
                          'the Mac\'s. Rebuild under a new name, or pass --overwrite-mac')
        cmd = [self.mac, 'repo', '--force', '--sync', rel] + (['--overwrite'] if remote else []) + ['--', 'true']
        rc, out = self.run(cmd, self.t['sync'], 'mac-sync', kill_at=1)
        after = mac_sha()
        self.step('mac-copy', path=rel, state='synced' if after == local else 'FAILED', rc=rc)
        if after != local:
            raise Refused('MAC_SYNC_FAILED', f'{rel}: the Mac copy is {after} after the sync')

    def ui_command(self):
        a = self.args
        if a.ui == 'settings':
            return [sys.executable, '-I', str(ROOT / 'tools/ui_settings_test.py'), '{run}']
        script = Path(a.ui).resolve()
        if not script.is_file():
            raise Refused('BAD_ARGS', f'UI script not found: {a.ui}', EXIT_USAGE)
        self.ui_script = script
        if a.ui_cmd:
            return shlex.split(a.ui_cmd)
        runner = ROOT / 'tools/ui_run.py'
        if not runner.is_file():
            raise Refused('UI_RUNNER_MISSING', 'tools/ui_run.py (agent UIDRV) is not in this checkout; pass --ui-cmd '
                          '"python3 -I path/ui_run.py {run} {script}" or --ui settings')
        # ui_run.py takes `run script` and writes <run>/ui_run.json itself (no --json flag; see UIDRIVE.md).
        return [sys.executable, '-I', str(runner), '{run}', '{script}']

    # ------------------------------------------------------------------ 2./3. boot, live, park
    def boot(self):
        info = self.report['image']
        self.touched = True
        self.ff_armed = True
        self.report['timings']['boot_start'] = self.since()
        if info['mode'] == 'bootios':
            self.boot_live_boot()
        else:
            self.boot_plain()
        self.report['timings']['boot_end'] = self.since()

    def start_side_workers(self):
        if self.side_started or not self.live_run:
            return
        self.side_started = True
        info = self.report['image']
        if info['live_snapshots'] and not self.args.no_shots:
            threading.Thread(target=self.shot_worker, name='shots', daemon=True).start()
        elif info['console'] and not self.args.no_shots:
            self.log('no live screenshots: the image has no blazer_usbcon_snap=1')
        if self.args.ui:
            threading.Thread(target=self.ui_worker, name='ui', daemon=True).start()

    def follow_markers(self, line):
        m = MARKER.match(line.strip())
        if not m:
            return
        name = m['name']
        self.markers_seen[name] = self.since()
        if name in ('EP0_LIVE', 'CONSOLE_CONNECTED', 'UI_READY', 'PARKED', 'PANIC', 'DEADLINE', 'CONSOLE_GONE', 'BOOT_RC'):
            self.log(f'marker {name} {m["detail"] or ""}'.rstrip())

    def boot_live_boot(self):
        info, a = self.report['image'], self.args
        name = self.name
        cmd = [self.live_boot, str(self.image), name, '--mach', str(self.mach), '--wait', str(info['wait_s'])]
        if not a.no_sync_tools:
            cmd.append('--sync-tools')
        if not info['console']:
            cmd.append('--no-console')
        bound = info['wait_s'] + max(self.t['boot_watch'], info['wait_s']) + self.t['boot_extra']
        self.step('boot', how='live_boot.sh', bound=bound)
        out_path = self.out / 'live_boot.out'
        p = self.spawn(cmd, out_path, pipe_stdout=True)
        self.boot_proc = p
        lines = []

        def reader():
            with open(out_path, 'a', buffering=1) as fo:
              try:
                for raw in p.stdout:
                    line = raw.decode('utf-8', 'replace').rstrip('\n')
                    fo.write(line + '\n')
                    lines.append(line)
                    m = re.match(r'live_boot: run (\S+)', line)
                    if m and not self.live_run:
                        self.live_run = Path(m.group(1))
                        self.log(f'live run {self.live_run}')
                        self.start_side_workers()
                    self.follow_markers(line)
              except (ValueError, OSError):      # the pipe was closed under us at the end
                pass
        rt = threading.Thread(target=reader, name='live_boot-out', daemon=True)
        rt.start()
        end = time.monotonic() + bound
        rc = None
        stopping = False
        try:
            while True:
                try:
                    rc = p.wait(timeout=0.5)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if self.interrupts >= 2 and not stopping:
                    stopping = True
                    self.error('INTERRUPTED', 'boot abandoned at the second interrupt: live_boot stopped, no ramdump from it')
                    self.term_then_kill(p, 40)
                if time.monotonic() > end and not stopping:
                    stopping = True
                    self.error('BOOT_TIMEOUT', f'live_boot ran past {bound:.0f}s; stopped')
                    self.term_then_kill(p, 40)
        finally:
            rt.join(timeout=10)
            self.reap(p)
            self.boot_done.set()
        info['boot_rc'] = rc
        env = self.read_env(self.live_run / 'live.env') if self.live_run else {}
        attempt = env.get('ATTEMPT') or next((l.split('attempt dir: ', 1)[1] for l in reversed(lines) if 'attempt dir: ' in l), None)
        self.attempt = self.local_path(attempt) if attempt and attempt != 'none' else None
        self.step('boot-end', rc=rc, live_run=str(self.live_run) if self.live_run else None,
                  attempt=str(self.attempt) if self.attempt else None)
        if rc == 3:
            raise Refused('CONSOLE_REFUSED', 'the usbcon reader did not start (lock held, socket taken or no pyusb); the boot was '
                          'not started', EXIT_BOOT)
        if rc not in (0, None) and not self.attempt:
            raise Refused('BOOT_FAILED', f'live_boot rc {rc} and no attempt directory (tail: {" | ".join(lines[-3:])[:300]})', EXIT_BOOT)

    def term_then_kill(self, p, grace):
        """live_boot traps TERM and stops its own console reader; give it time, then the group."""
        try:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.kill(p, grace=5)
        except ProcessLookupError:
            pass

    def local_path(self, p):
        """An attempt directory named in Mac terms -> the copy mac repo --back-attempt made on m1box."""
        p = str(p).strip()
        marker = '/' + self.mac_dir.strip('/') + '/'
        if marker in p:
            return ROOT / p.split(marker, 1)[1]
        q = Path(p)
        return q if q.is_absolute() else ROOT / q

    @staticmethod
    def read_env(path):
        out = {}
        try:
            for line in Path(path).read_text().splitlines():
                k, sep, v = line.partition('=')
                if sep:
                    out[k] = v
        except OSError:
            pass
        return out

    def stamp_filter(self):
        """live_boot.sh's own marker filter (STAMP_PY), so plain mode writes the same console.txt/markers.txt."""
        text = Path(ROOT / 'tools/live_boot.sh').read_text() if (ROOT / 'tools/live_boot.sh').is_file() else ''
        m = re.search(r"STAMP_PY=\$\(cat <<'PY'\n(.*?)\nPY\n\)", text, re.S)
        return m.group(1) if m else None

    def boot_plain(self):
        info, a = self.report['image'], self.args
        ts = time.strftime('%Y%m%d-%H%M%S')
        run = self.out / f'live-{ts}-{self.name}'
        run.mkdir(parents=True, exist_ok=True)
        self.live_run = run
        rel = run.relative_to(ROOT)
        sock = f'/tmp/hackios-live-{ts}-{os.getpid()}.sock'
        markers = run / 'markers.txt'
        markers.touch()
        t0 = time.time()
        (run / 'live.env').write_text(f'LIVE_RUN={run}\nLIVE_NAME={self.name}\nLIVE_SOCK={sock}\nLIVE_MAC_DIR={self.mac_dir}\n'
                                      f'LIVE_MARKERS={markers}\nLIVE_CONSOLE={run}/console.txt\nLIVE_T0={t0}\n')
        self.step('boot', how='plain fastboot boot', wait=info['wait_s'])
        if not self.force_fastboot(True, kill_at=2):
            raise Refused('FORCE_FASTBOOT_FAILED', 'could not arm force-fastboot: a deadline reset would not park', EXIT_BOOT)
        console = None
        if info['console']:
            py = os.environ.get('USBCON_PY', '/tmp/tegu-venv/bin/python')
            ctimeout = int(info['wait_s'] + 600)
            cmd = (shlex.split(os.environ['HK_CYCLE_USBCON_CMD']) if os.environ.get('HK_CYCLE_USBCON_CMD') else
                   [self.mac, 'repo', '--force', '--', py, '-u', 'tools/usbcon.py', '--output', f'{rel}/usbcon/usbcon.log',
                    '--control-socket', sock, '--timeout', str(ctimeout), '--gone-exit', '45', '--stats', '30'])
            if not a.no_sync_tools:
                self.run([self.mac, 'repo', '--force', '--sync', 'tools/usbcon.py', '--overwrite', '--', 'true'], self.t['sync'],
                         'sync-usbcon', kill_at=2)
            filt = self.stamp_filter()
            p = self.spawn(cmd, run / 'usbcon.out', pipe_stdout=True)
            if filt:
                stamp = subprocess.Popen([sys.executable, '-I', '-u', '-c', filt, 'console', str(run / 'console.txt'), str(markers), str(t0)],
                                         stdin=p.stdout, stdout=open(run / 'stamp.out', 'ab'), stderr=subprocess.STDOUT,
                                         start_new_session=True)
            else:
                stamp = subprocess.Popen(['tee', '-a', str(run / 'console.txt')], stdin=p.stdout, stdout=subprocess.DEVNULL,
                                         start_new_session=True)
            console = (p, stamp)
            self.sleep(self.t['console_start'], kill_at=2)
            if p.poll() is not None:
                self.reap(p)
                raise Refused('CONSOLE_REFUSED', 'the usbcon reader exited before the boot (lock held, socket taken, no pyusb); '
                              f'not booting. {(run / "console.txt")}', EXIT_BOOT)
            self.start_side_workers()
        try:
            boot_t = time.monotonic()
            rc, out = self.run([self.fastboot, 'boot', str(self.image)], self.t['fb_boot'], 'fastboot-boot', kill_at=2)
            self.step('fastboot-boot', rc=rc, line=(out.strip().splitlines() or [''])[-1][:200])
            if rc != 0:
                raise Refused('BOOT_FAILED', f'fastboot boot rc {rc}', EXIT_BOOT)
            self.sleep(self.t['settle'], kill_at=2)
            left, outcome = False, None
            end = boot_t + info['wait_s'] + self.t['settle']
            while time.monotonic() < end:
                st = self.phone_state(kill_at=2)
                if st != 'fastboot':
                    left = True
                if st == 'fastboot' and (left or time.monotonic() - boot_t > 90):
                    outcome = 'park'
                elif st == 'android' and self.boot_completed(kill_at=2):
                    outcome = 'android'
                elif st == 'recovery':
                    outcome = 'recovery'
                if outcome:
                    break
                self.sleep(self.poll, kill_at=2)
            self.step('plain-outcome', outcome=outcome or 'no-park', after_s=round(time.monotonic() - boot_t, 1))
            info['plain_outcome'] = outcome or 'no-park'
            if outcome == 'park':
                self.markers_seen['PARKED'] = self.since()
                self.capture_plain()
            elif not outcome:
                self.error('NO_PARK', f'no park, Android or recovery within {info["wait_s"]}s of the boot')
        finally:
            self.boot_done.set()
            if console:
                p, stamp = console
                if p.poll() is None:
                    for _ in range(int(60 / 0.5)):          # the reader stops ~45 s after the gadget goes
                        if p.poll() is not None:
                            break
                        time.sleep(0.5)
                    self.kill(p, grace=15)
                self.reap(p)
                try:
                    stamp.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    stamp.kill()
                self.run([self.mac, 'repo', '--force', '--back', f'{rel}/usbcon', '--', 'true'], self.t['mac'] * 3, 'usbcon-back', kill_at=3)

    def capture_plain(self):
        ts = time.strftime('%Y%m%d-%H%M%S')
        att = self.out / f'{ts}-{self.name}'
        att.mkdir(parents=True, exist_ok=True)
        rel = att.relative_to(ROOT)
        cap = os.environ.get('HK_CYCLE_CAPTURE_PY', 'python3')
        rc, out = self.run([self.mac, 'repo', '--force', '--back', str(rel), '--', cap, 'tools/capture-fastboot.py', f'{rel}/ramdump',
                            '--diagnostics'], self.t['capture'], 'capture', kill_at=2)
        (att / 'capture.log').write_text(out)
        self.attempt = att
        k = att / 'ramdump/kernel.log'
        self.step('capture', rc=rc, kernel_log=k.is_file())
        if not k.is_file():
            self.error('CAPTURE_FAILED', f'capture-fastboot rc {rc}, no ramdump/kernel.log')
            return
        if self.mach:
            reader = ROOT / 'research/laguna-ramdump/reader/read-ramdump.py'
            rc, out = self.run([sys.executable, str(reader), str(k), '--mach', str(self.mach), '--dump-base', '0x95200000',
                                '--logs', '--tail', '65536'], self.t['reader'], 'read-ramdump', kill_at=3)
            (att / 'reader.txt').write_text(out)

    def shot_worker(self):
        try:
            start = None
            while not self.boot_done.is_set() and self.interrupts < 1:
                if any(k in self.markers_seen for k in ('DISPLAY', 'CONSOLE_CONNECTED')) or self.markers_from_file('DISPLAY'):
                    start = time.monotonic()
                    break
                time.sleep(1)
            if start is None:
                return
            if self.boot_done.wait(self.t['shot_start']):
                return
            n = 0
            while not self.boot_done.is_set() and self.interrupts < 1 and n < self.args.max_shots:
                if self.markers_from_file('PARKED', 'PANIC', 'DEADLINE', 'CONSOLE_GONE', 'CONSOLE_END'):
                    break
                n += 1
                t = self.since()
                path = self.out / 'screens' / f'live-{n:03d}-{int(t):05d}s.png'
                path.parent.mkdir(exist_ok=True)
                rc, out = self.run([self.screenshot, str(self.live_run), '--name', f'c{n:03d}', '--step', str(self.args.shot_step),
                                    '-o', str(path)], self.t['shot'], f'shot{n}', kill_at=1)
                ok = rc == 0 and path.is_file()
                self.report['screenshots'].append(dict(t=t, kind='live', path=str(path.relative_to(self.out)) if ok else None, ok=ok,
                                                       detail=(out.strip().splitlines() or [''])[-1][:160]))
                if self.boot_done.wait(self.args.shot_every):
                    break
        except Interrupted:
            pass
        except Exception as e:     # never let a screenshot take the cycle down
            self.log(f'screenshot worker stopped: {e}')

    def markers_from_file(self, *names):
        if not self.live_run:
            return False
        got = {m['name'] for m in read_markers(self.live_run / 'markers.txt')}
        return any(n in got for n in names)

    def ui_worker(self):
        ui = self.report.setdefault('ui', dict(ran=False))
        try:
            json_path = self.out / 'ui' / 'ui_run.json'
            json_path.parent.mkdir(exist_ok=True)
            subst = dict(run=str(self.live_run), script=str(getattr(self, 'ui_script', '')), json=str(json_path), out=str(json_path.parent))
            cmd = [c.format(**subst) for c in self.ui_cmd]
            ui.update(cmd=cmd, started=self.since())
            self.step('ui-start', cmd=' '.join(cmd))
            rc, out = self.run(cmd, min(self.t['ui'], self.report['image']['wait_s'] + 600), 'ui', kill_at=1)
            (self.out / 'ui' / 'ui.out').write_text(out)
            ui.update(ran=True, rc=rc, ended=self.since())
            self.step('ui-end', rc=rc)
        except Interrupted:
            ui.update(ran=True, rc=None, interrupted=True)
            self.step('ui-end', interrupted=True)
        except Exception as e:
            ui.update(error=str(e))
            self.log(f'ui worker failed: {e}')

    # ------------------------------------------------------------------ post-park
    def post_park(self):
        att = self.attempt
        if not att or not (att / 'ramdump/kernel.log').is_file():
            return
        path = self.out / 'screens' / 'hk_screen.png'
        path.parent.mkdir(exist_ok=True)
        rc, out = self.run([self.screenshot, '--dump', str(att), '-o', str(path)], self.t['shot'], 'hk-screen', kill_at=3)
        meta = None
        rc2, j = self.run([sys.executable, '-I', str(ROOT / 'tools/fb_png.py'), str(att), '--json', '-o', str(self.tmp / 'fbpng.png')],
                          self.t['shot'], 'fb-png-json', kill_at=3)
        try:
            meta = json.loads(j[j.find('{'):]) if '{' in j else None
        except ValueError:
            meta = None
        ok = rc == 0 and path.is_file()
        self.report['screenshots'].append(dict(t=self.since(), kind='hk_screen', ok=ok, path='screens/hk_screen.png' if ok else None,
                                               detail=('stale record (previous boot)' if rc == 4 else 'no HKSCR1 record' if rc == 3
                                                       else (out.strip().splitlines() or [''])[-1][:160]),
                                               record=meta))

    # ------------------------------------------------------------------ 4. return to Android
    def return_to_android(self):
        ret = self.report['return'] = dict(start=self.since())
        if not self.touched:
            st = self.note_state(self.phone_state(kill_at=3), 'return (phone untouched by this cycle)')
            ret.update(state=st, action='none: the cycle never changed the phone, no boot, no return check', untouched=True,
                       android=st == 'android')
            return
        st = self.note_state(self.phone_state(kill_at=3), 'return')
        if st in ('ios', 'unknown', 'usb-google') or st.startswith('android-'):
            self.log(f'waiting up to {self.t["park_wait"]:.0f}s for the iOS boot to end at its deadline (no cold reset: it wipes RAM)')
            st = self.note_state(self.wait_for({'fastboot', 'android', 'recovery'}, self.t['park_wait'], 3, 'park-wait'), 'return, after waiting')
        if st == 'android' and self.ff_armed:
            # e.g. a chooser boot that went on to Android: force-fastboot is still on, so disarm it from fastboot
            if self.boot_completed(kill_at=3):
                self.run([self.adb, 'reboot', 'bootloader'], self.t['probe'], 'adb-reboot-bootloader', kill_at=3)
                st = self.note_state(self.wait_for({'fastboot'}, self.t['to_fastboot'], 3, 'to-fastboot'), 'to disarm force-fastboot')
        if st == 'fastboot':
            ok = self.force_fastboot(False, kill_at=3)
            ret['force_fastboot_off'] = ok
            if not ok:
                self.error('FORCE_FASTBOOT_ON', 'force-fastboot could not be turned off; rebooting anyway (a later reboot will park)')
            rc, _ = self.run([self.fastboot, 'reboot'], self.t['ff'], 'fastboot-reboot', kill_at=3)
            self.step('fastboot-reboot', rc=rc)
            self.sleep(min(10, self.poll * 2), kill_at=3)
            st = self.wait_for({'android', 'recovery'}, self.t['android_boot'], 3, 'android-boot', also=())
        if st == 'android':
            end = time.monotonic() + self.t['android_boot']
            while not self.boot_completed(kill_at=3):
                if time.monotonic() > end:
                    break
                self.sleep(self.poll, kill_at=3)
            done = self.boot_completed(kill_at=3)
            st = self.note_state('android' if done else 'android-booting', 'after the reboot')
        ret.update(state=st, android=st == 'android', end=self.since())
        if st == 'recovery':
            self.error('PHONE_IN_RECOVERY', 'Android came up in recovery: the owner chooses "Try again" (never factory reset)')
        elif st != 'android':
            self.error('RETURN_FAILED', f'the phone is {st}, not Android')
        if st == 'android' and not self.args.no_return_check:
            self.run_return_check(ret)

    def run_return_check(self, ret):
        d = self.out / 'return-check'
        rc, out = self.run(['bash', self.return_check, str(d)], self.t['return_check'], 'return-check', kill_at=3)
        (self.out / 'return-check.out').write_text(out)
        try:
            r = json.loads((d / 'return-check.json').read_text())
        except (OSError, ValueError):
            r = {}
        ret['check'] = dict(rc=rc, verdict=r.get('verdict', 'NO RESULT'), kernel_code_base=r.get('kernel_code_base'),
                            failed=[k for k, v in r.items() if v is False])
        self.step('return-check', verdict=ret['check']['verdict'])

    # ------------------------------------------------------------------ 5./6. analysis and report
    def analyse(self):
        an = self.report['analysis'] = {}
        sources = {}
        adir = self.out / 'analysis'
        adir.mkdir(exist_ok=True)
        if self.live_run and (self.live_run / 'console.txt').is_file():
            sources['live'] = strip_live((self.live_run / 'console.txt').read_text(errors='replace'))
            an['live'] = dict(bytes=len(sources['live']), path=str(self.live_run / 'console.txt'))
        k = self.attempt / 'ramdump/kernel.log' if self.attempt else None
        if k and k.is_file():
            text, meta = dump_text(k)
            an['dump'] = meta if text is not None else dict(error=meta)
            if text is not None:
                sources['dump'] = text
        else:
            an['dump'] = dict(error='no ramdump/kernel.log')
        for name, text in sources.items():
            (adir / f'{name}.txt').write_text(text)
        timeline = self.attempt / 'park-timeline.txt' if self.attempt else None
        if timeline and timeline.is_file():
            pt = self.read_env_colon(timeline)
            an['park'] = {k: pt.get(k) for k in ('ep0_to_park_s', 'boot_to_park_wall_s', 'abl_reboot_reason', 'abl_rst_stat_terminal',
                                                  'autonomy', 'capture_rc')}
            if 'Cold Reset' in (pt.get('abl_rst_stat_terminal') or ''):
                an['park']['note'] = ('cold reset: RAM was wiped, the dump holds no current boot; only the live console counts')
        reader = self.attempt / 'reader.txt' if self.attempt else None
        if reader and reader.is_file():
            v = re.search(r'^VERDICT: .*$', reader.read_text(errors='replace'), re.M)
            an['reader_verdict'] = v.group(0)[:400] if v else None
        primary = max(sources, key=lambda s: len(sources[s])) if sources else None
        an['primary'] = primary
        sym = Symbolizer(self.args.cache)
        an['symbols'] = dict(cache=self.args.cache, uuid=sym.uuid, error=sym.error)
        try:
            if primary:
                (adir / 'boot.txt').write_text(sources[primary])
                an.update(analyse_console(sources[primary], sym))
        finally:
            sym.close()
        if primary and an.get('ustack_lines') and USTACK_SYM.is_file():
            rc, out = self.run([sys.executable, '-I', str(USTACK_SYM), str(adir / 'boot.txt'), '--cache', self.args.cache, '--summary',
                                '--main-only'], self.t['analysis'], 'ustack-sym', kill_at=99)
            (adir / 'ustack-summary.txt').write_text(out)
            an['ustack_summary'] = dict(rc=rc, path='analysis/ustack-summary.txt', head=out.strip().splitlines()[:40])
        markers = read_markers(self.live_run / 'markers.txt') if self.live_run else []
        an['markers'] = {}
        for m in markers:
            an['markers'].setdefault(m['name'], dict(s=m['s'], wall=m['wall'], detail=m['detail'][:160], count=0))['count'] += 1
        an['home'] = home_rule(an['markers'], sources)
        if an['home']['home']:
            an['markers'].setdefault('HOME', dict(s=None, wall=None, detail=an['home']['rule'], count=1))
        ui = self.report.get('ui', dict(ran=False))
        ui['steps'] = ui.get('steps') or self.ui_steps()
        ui['attended'] = bool(self.args.attended)
        self.report['ui'] = ui
        self.crashdoc(an, adir)
        if self.expect_doc:
            rows, how = self.probe_eval(sources, adir, set(an['markers']), ui)
            self.report['expectations'], an['evaluator'] = rows, how

    def crashdoc(self, an, adir):
        """tools/crashdoc.py on this attempt (and the live console): this boot's crash signatures, symbolicated, with hints."""
        paths = [str(p) for p in (self.attempt, self.live_run) if p and Path(p).is_dir()]
        if not paths or not CRASHDOC.is_file():
            an['crashdoc'] = dict(error='no attempt/live run' if not paths else 'tools/crashdoc.py missing')
            return
        out = adir / 'crashdoc'
        symargs = ['--cache', self.args.cache] if Path(self.args.cache).is_file() else ['--no-symbols']
        rc, text = self.run([sys.executable, '-I', str(CRASHDOC)] + paths + ['--out', str(out)] + symargs,
                            self.t['analysis'], 'crashdoc', kill_at=99)
        try:
            doc = json.loads((out / 'crashes.json').read_text())
        except (OSError, ValueError):
            an['crashdoc'] = dict(error=f'rc {rc}: ' + ((text.strip().splitlines() or ['no output'])[-1])[:200])
            return
        own = {s.get('own_boot') for s in doc.get('sources', []) if s.get('own_boot')}
        sigs = []
        for g in doc.get('signatures', []):
            mine = sum(n for b, n in (g.get('boots') or {}).items() if b in own)
            if not mine:
                continue
            ex = g.get('example') or {}
            sigs.append(dict(sig=g['sig'], kind=g.get('kind'), proc=g.get('proc'), crash=g.get('crash'), this_boot=mine,
                             all_boots=g.get('incidents'), status=g.get('status'),
                             top=[f.get('text') or f.get('addr') for f in (ex.get('frames') or [])[:4]],
                             hints=[h.get('id') + ': ' + h.get('cause', '')[:160] for h in g.get('hints') or []]))
        sigs.sort(key=lambda g: (not g['crash'], -g['this_boot']))
        an['crashdoc'] = dict(rc=rc, md='analysis/crashdoc/crashes.md', json='analysis/crashdoc/crashes.json', own_boots=sorted(own),
                              cache=doc.get('cache'), signatures=sigs, residue_signatures=len(doc.get('signatures', [])) - len(sigs))

    def probe_eval(self, sources, adir, markers, ui):
        """Row verdicts from VERIFY's tools/probe_eval.py when present (the one evaluator); the built-in matcher only until then.
        Contract: probe_eval.py ATTEMPT_DIR... --probes FILE --json (stdout)
        -> {"attempts", "rows":[{"id","verdict","evidence",...}]}. Any failure falls back, and the report says which ran."""
        builtin = evaluate(self.expect_doc, sources, markers, ui)
        if not PROBE_EVAL.is_file() or self.args.builtin_eval:
            return builtin, 'hk_cycle built-in (interim: tools/probe_eval.py ' + ('not present)' if not PROBE_EVAL.is_file() else 'skipped)')
        # Real tools/probe_eval.py (VERIFY): attempt dir(s) positionally, --probes PROBES, --json to stdout ->
        # {"attempts":[...], "rows":[{id, verdict, evidence, ...}]}. Only usable when --expect is a probes.yaml-shaped
        # file; a HARNESS per-cycle expect file is a different schema, so that case falls through to the built-in matcher.
        attempt_dirs = [str(d) for d in (self.live_run, getattr(self, 'runner_dir', None)) if d]
        if not attempt_dirs:
            return builtin, 'hk_cycle built-in (no attempt dir for probe_eval)'
        out = adir / 'probe_eval.json'
        cmd = [sys.executable, '-I', str(PROBE_EVAL), *attempt_dirs,
               '--probes', str(Path(self.report['expect']).resolve()), '--json']
        rc, text = self.run(cmd, self.t['analysis'], 'probe-eval', kill_at=99)
        try:
            out.write_text(text)
            rows = json.loads(text)['rows']
            want = {r['id']: r for r in builtin}
            merged = []
            for r in rows:
                base = dict(want.get(r['id'], dict(feature=r.get('feature', r['id']), required=True, note='')))
                base.update(evidence=[], missing=[], forbidden=[])
                base.update({k: v for k, v in r.items() if k in base or k == 'verdict'})
                base['id'] = r['id']
                merged.append(base)
            return merged, f'tools/probe_eval.py (rc {rc})'
        except (OSError, ValueError, KeyError, TypeError) as e:
            self.log(f'probe_eval unusable ({e}); using the built-in matcher')
            return builtin, f'hk_cycle built-in (probe_eval.py failed: {str(e)[:120]})'

    @staticmethod
    def read_env_colon(path):
        out = {}
        for line in Path(path).read_text(errors='replace').splitlines():
            k, sep, v = line.partition(':')
            if sep:
                out[k.strip()] = v.strip()
        return out

    def ui_steps(self):
        """The UI runner's per-step result, from its JSON (ui_run.json, or ui_settings_test's ui_test.json)."""
        for p in [self.out / 'ui/ui_run.json'] + ([self.live_run / 'ui_run.json', self.live_run / 'ui_test.json'] if self.live_run else []):
            try:
                doc = json.loads(Path(p).read_text())
            except (OSError, ValueError):
                continue
            steps = {}
            for s in doc.get('steps', []):
                name = s.get('name') or s.get('step') or s.get('id')
                if name:
                    ok = s.get('ok')
                    if ok is None:
                        ok = str(s.get('verdict', s.get('result', ''))).upper() in ('PASS', 'OK')
                    steps[str(name)] = bool(ok)
            self.report.setdefault('ui', {}).update(json=str(p), verdict=doc.get('verdict'))
            return steps
        return {}

    def verdict(self):
        r = self.report
        exp = r.get('expectations') or []
        req = [e for e in exp if e.get('required', True)]
        ret = r.get('return', {})
        check = (ret.get('check') or {}).get('verdict', 'NOT RUN')
        errors = [e for e in r['errors'] if e['state'] != 'INTERRUPTED']
        if ret.get('untouched') and r['errors']:
            v = 'REFUSED'                     # preflight said no before the phone was changed
        elif not ret.get('android'):
            v = 'PHONE_NOT_IN_ANDROID'
        elif any(e['verdict'] == 'FAIL' for e in req) or check not in ('PASS', 'NOT RUN'):
            v = 'FAIL'
        elif errors:
            v = 'ERROR'
        elif r['errors']:
            v = 'INTERRUPTED'
        elif not exp:
            v = 'COMPLETE' if check == 'PASS' else 'INCOMPLETE'
        elif all(e['verdict'] == 'PASS' for e in req) and check == 'PASS':
            v = 'PASS'
        else:
            v = 'INCOMPLETE'
        r['verdict'] = v
        r['return_check_verdict'] = check
        return v

    def write_report(self):
        r = self.report
        r['ended'] = now_iso()
        r['duration_s'] = self.since()
        tmp = self.out / 'report.json.tmp'
        tmp.write_text(json.dumps(r, indent=1, default=str) + '\n')
        tmp.replace(self.out / 'report.json')
        (self.out / 'report.md').write_text(render_md(r))
        self.write_summary()
        self.log(f'report: {self.out / "report.md"}')

    def write_summary(self, code=None):
        """summary.json: the small stable record HUB (tools/hk cycle) reads. Schema hk_cycle.summary/1."""
        r = self.report
        rows = r.get('expectations') or []
        counts = {}
        for e in rows:
            counts[e['verdict']] = counts.get(e['verdict'], 0) + 1
        an = r.get('analysis') or {}
        cd = an.get('crashdoc') or {}
        s = dict(schema='hk_cycle.summary/1', name=r.get('name'), verdict=r.get('verdict'), exit_code=code,
                 started=r.get('started'), ended=r.get('ended'), duration_s=r.get('duration_s'),
                 image=(r.get('image') or {}).get('image'), image_sha256=(r.get('image') or {}).get('image_sha256'),
                 mode=(r.get('image') or {}).get('mode'), errors=[e['state'] for e in r.get('errors', [])],
                 android=bool((r.get('return') or {}).get('android')), return_check=r.get('return_check_verdict'),
                 home=(an.get('home') or {}).get('home'), evaluator=an.get('evaluator'),
                 rows={e['id']: e['verdict'] for e in rows}, row_counts=counts,
                 crash_signatures=[g['sig'] for g in cd.get('signatures', []) if g.get('crash')],
                 panics=[p['kind'] for p in an.get('panics', [])],
                 report_md='report.md', report_json='report.json',
                 screenshots=[s['path'] for s in r.get('screenshots', []) if s.get('ok')])
        (self.out / 'summary.json').write_text(json.dumps(s, indent=1, default=str) + '\n')

    # ------------------------------------------------------------------ main
    def main(self):
        a = self.args
        self.expect_doc = load_expect(a.expect) if a.expect else None
        self.name = a.name or (Path(a.image).name if Path(a.image).is_dir() else Path(a.image).parent.name)
        if not re.fullmatch(r'[A-Za-z0-9._-]+', self.name):
            raise SystemExit('hk_cycle: --name may use only A-Za-z0-9._-')
        ts = time.strftime('%Y%m%d-%H%M%S')
        self.out = Path(a.out).resolve() if a.out else ROOT / 'research/hk-cycles' / f'{ts}-{self.name}'
        self.out.mkdir(parents=True, exist_ok=True)
        self.tmp = self.out / 'cmd'
        self.tmp.mkdir(exist_ok=True)
        self.log_f = open(self.out / 'cycle.log', 'a')
        self.report.update(name=self.name, out=str(self.out), argv=sys.argv[1:], expect=a.expect, timeouts=self.t)
        self.live_run = self.attempt = None
        self.side_started = False
        self.markers_seen = {}
        self.boot_proc = None
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(s, self.on_signal)
        self.log(f'cycle {self.out}')
        code = EXIT_OK
        try:
            try:
                self.report['timings']['preflight_start'] = self.since()
                self.preflight()
                self.report['timings']['preflight_end'] = self.since()
                self.check_interrupt(1)
                self.boot()
                self.post_park()
            except Refused as e:
                self.error(e.state, e.detail)
                code = e.code
            except Interrupted as e:
                self.error('INTERRUPTED', str(e))
                code = EXIT_INTERRUPTED
            except Exception as e:      # a bug must still return the phone
                self.error('INTERNAL', f'{type(e).__name__}: {e}')
                code = EXIT_BOOT
            finally:
                self.boot_done.set()
            if self.interrupts < 3:
                try:
                    self.return_to_android()
                except Interrupted:
                    self.error('INTERRUPTED', 'the return to Android was abandoned (third interrupt)')
                    self.report.setdefault('return', {}).update(android=False, abandoned=True)
                except Exception as e:
                    self.error('INTERNAL', f'return: {type(e).__name__}: {e}')
                    self.report.setdefault('return', {}).update(android=False)
            else:
                self.report['return'] = dict(android=False, abandoned=True)
            with self.lock:
                left = list(self.children)
            for p in left:
                self.kill(p)
            try:
                self.analyse()
            except Exception as e:
                self.error('ANALYSIS', f'{type(e).__name__}: {e}')
        finally:
            v = self.verdict()
            self.write_report()
        if v == 'REFUSED':
            pass                                  # the refusal's own code; the phone was not changed
        elif not self.report.get('return', {}).get('android'):
            code = EXIT_NOT_ANDROID
        elif self.interrupts:
            code = EXIT_INTERRUPTED
        elif code == EXIT_OK and v not in ('PASS', 'COMPLETE'):
            code = EXIT_FAIL if v in ('FAIL', 'INCOMPLETE') else EXIT_BOOT
        self.write_summary(code)
        print(f'hk_cycle: verdict {v}; return check {self.report["return_check_verdict"]}; report {self.out / "report.md"}')
        return code

    def report_only(self):
        """Re-run the analysis and the report of an existing cycle directory; touches no device."""
        a = self.args
        self.out = Path(a.report_only).resolve()
        self.tmp = self.out / 'cmd'
        self.tmp.mkdir(exist_ok=True)
        self.log_f = open(self.out / 'cycle.log', 'a')
        old = json.loads((self.out / 'report.json').read_text())
        self.report.update({k: v for k, v in old.items() if k not in ('analysis', 'expectations', 'verdict')})
        self.expect_doc = load_expect(a.expect or old.get('expect')) if (a.expect or old.get('expect')) else None
        self.report['expect'] = a.expect or old.get('expect')
        live = next((s['live_run'] for s in old.get('steps', []) if s.get('live_run')), None)
        att = next((s['attempt'] for s in old.get('steps', []) if s.get('attempt')), None)
        if not live:
            live = next(iter(sorted(self.out.glob('live-*'))), None)
        if not att:
            att = next((p.parent.parent for p in sorted(self.out.glob('*/ramdump/kernel.log'))), None)
        self.live_run = Path(live) if live else None
        self.attempt = Path(att) if att else None
        self.analyse()
        v = self.verdict()
        self.write_report()
        code = EXIT_OK if v in ('PASS', 'COMPLETE') else EXIT_FAIL
        self.write_summary(code)
        print(f'hk_cycle: verdict {v}; report {self.out / "report.md"}')
        return code


# ----------------------------------------------------------------------------------------------- report.md
def md_cell(s):
    return str(s).replace('|', '\\|').replace('\n', ' ')


def ev_cell(x):
    if isinstance(x, dict):
        return f"{x.get('source', '')}: `{md_cell(x.get('line', x))[:140]}`"
    return f'`{md_cell(x)[:140]}`'


def render_md(r):
    img = r.get('image', {})
    ret = r.get('return', {})
    an = r.get('analysis', {})
    L = [f"# hk_cycle {r.get('name', '')}: {r.get('verdict', '?')}", '']
    L.append(f"- Image: `{img.get('image')}` sha256 `{(img.get('image_sha256') or '')[:16]}…` ({img.get('kind')}, mode {img.get('mode')})")
    if img.get('mach'):
        L.append(f"- Kernel: `{img.get('mach')}` sha256 `{(img.get('mach_sha256') or '')[:16]}…`")
    L.append(f"- Deadline {img.get('deadline_s')} s, wait {img.get('wait_s')} s, console {img.get('console')}, live snapshots "
             f"{img.get('live_snapshots')}, live input {img.get('live_input')}")
    L.append(f"- Started {r.get('started')}, ended {r.get('ended')}, {r.get('duration_s')} s; expectations `{r.get('expect')}`")
    L.append(f"- Return to Android: **{'yes' if ret.get('android') else 'NO'}**, return check **{r.get('return_check_verdict')}**"
             + (f" (failed: {', '.join((ret.get('check') or {}).get('failed', []))})" if (ret.get('check') or {}).get('failed') else ''))
    L.append('- Evidence class: PHYSICAL (this phone boot); analysis is of its console and ramdump.')
    if r.get('errors'):
        L += ['', '## Errors', '']
        L += [f"- `{e['state']}` at +{e['t']} s: {e['detail']}" for e in r['errors']]
    if r.get('expectations') is not None:
        L += ['', '## Expectations', '', '| id | feature | verdict | evidence / missing |', '|---|---|---|---|']
        for e in r['expectations']:
            ev = '; '.join(ev_cell(x) for x in (e.get('evidence') or [])[:2])
            miss = '; '.join(f"missing `{md_cell(m)[:100]}`" for m in (e.get('missing') or [])[:3])
            bad = '; '.join('FORBIDDEN ' + ev_cell(x) for x in (e.get('forbidden') or [])[:2])
            verdict = e['verdict'] + ('' if e.get('required', True) else ' (info)')
            L.append(f"| {e['id']} | {md_cell(e['feature'])} | **{verdict}** | {' '.join(filter(None, [bad, ev, miss]))} |")
        notes = [e for e in r['expectations'] if e.get('note')]
        if notes:
            L += [''] + [f"- {e['id']}: {e['note']}" for e in notes]
    shots = [s for s in r.get('screenshots', []) if s.get('ok')]
    if r.get('screenshots'):
        L += ['', '## Screens', '']
        for s in r['screenshots']:
            label = 'hk_screen (post-mortem, last capture)' if s['kind'] == 'hk_screen' else f"live +{s['t']:.0f} s"
            if s.get('ok'):
                rec = s.get('record') or {}
                extra = f" (reason {rec.get('reason_name', rec.get('reason'))}, seq {rec.get('seq')}, {rec.get('identity', '')})" if rec.get('reason') else ''
                L.append(f"**{label}**{extra}  \n![{label}]({s['path']})  ")
            else:
                L.append(f"- {label}: none ({s.get('detail')})")
        if not shots:
            L.append('(no picture was captured)')
    L += ['', '## Timings', '', '| what | t (s since start) |', '|---|---|']
    for k, v in r.get('timings', {}).items():
        L.append(f'| {k} | {v} |')
    for k, m in (an.get('markers') or {}).items():
        if k in ('CONSOLE_CONNECTED', 'EP0_LIVE', 'DISPLAY', 'ROOT', 'LAUNCHD', 'SPRINGBOARD', 'TOUCH_CLIENT', 'FRAMES', 'UI_READY',
                 'PANIC', 'DEADLINE', 'PARKED', 'CONSOLE_GONE', 'BOOT_RC'):
            L.append(f"| live_boot {k} | +{m['s']} (live_boot clock) {md_cell(m['detail'])[:80]} |")
    if an.get('park'):
        p = an['park']
        L.append(f"| EP0 → park | {p.get('ep0_to_park_s')} |")
        L += ['', f"Park: reboot reason {p.get('abl_reboot_reason')}, RST_STAT {p.get('abl_rst_stat_terminal')}, autonomy {p.get('autonomy')}"
              + (f". **{p['note']}**" if p.get('note') else '')]
    L += ['', '## Phone states', '']
    L += [f"- +{s['t']} s {s['state']} ({s['why']})" for s in r.get('phone_states', [])]
    L += ['', '## Console', '']
    home = an.get('home') or {}
    L.append(f"- Home: **{home.get('home')}** ({home.get('rule')}{', ' + str(home.get('parts')) if home.get('parts') else ''})")
    L.append(f"- Row verdicts by: {an.get('evaluator')}")
    L.append(f"- Sources: live {(an.get('live') or {}).get('bytes', 0)} B, dump {(an.get('dump') or {}).get('bytes', (an.get('dump') or {}).get('error'))}; "
             f"counts below from **{an.get('primary')}**. Reader: `{md_cell(an.get('reader_verdict') or '-')[:300]}`")
    sym = an.get('symbols') or {}
    L.append(f"- Symbols: dyld cache `{sym.get('cache')}` uuid {sym.get('uuid')}" + (f" ({sym['error']})" if sym.get('error') else '')
             + '. Nearest exported symbol; a large +off means a local symbol and only the image is certain.')
    if an.get('panics'):
        L += ['', '### Panics', ''] + [f"- {p['kind']}: `{md_cell(p['line'])[:220]}`" for p in an['panics'][:5]]
    cd = an.get('crashdoc') or {}
    if cd.get('signatures') is not None:
        L += ['', f"### Crashes in this boot (tools/crashdoc.py, boots {', '.join(cd.get('own_boots') or [])}; "
              f"{cd.get('residue_signatures', 0)} older-boot signatures left out; full: `{cd.get('md')}`)", '']
        if cd['signatures']:
            L += ['| signature | this boot | status | top frames | hints |', '|---|---|---|---|---|']
            for g in cd['signatures'][:25]:
                L.append(f"| {'**' if g['crash'] else ''}{md_cell(g['sig'])[:90]}{'**' if g['crash'] else ''} | {g['this_boot']} | "
                         f"{md_cell(g.get('status') or '')[:60]} | {'<br>'.join(md_cell(t) for t in g['top'])} | "
                         f"{'<br>'.join(md_cell(h) for h in g['hints'])} |")
        else:
            L.append('(none)')
    elif an.get('crashes'):
        L += ['', f"### Crashes (built-in grep; crashdoc: {cd.get('error')})", '', '| proc | kind | count | pids | top frames |', '|---|---|---|---|---|']
        for c in an['crashes'][:20]:
            L.append(f"| {c['name']} | {c['kind']} {md_cell(c['what'])[:40]} | {c['count']} | {' '.join(map(str, c['pids'][:6]))} | "
                     f"{'<br>'.join(md_cell(s) for s in c['top'][:4])} |")
    if an.get('crash_lines'):
        L += ['', '### CRASH lines', '', '| proc | reason | count |', '|---|---|---|']
        L += [f"| {c['name']} | {md_cell(c['reason'])} | {c['count']} |" for c in an['crash_lines'][:15]]
    if an.get('respawns'):
        L += ['', '### Respawns (exec / spawn count − 1)', '', '| proc | respawns | crashed in a row |', '|---|---|---|']
        L += [f"| {x['name']} | {x['respawns']} | {x['crashed_in_a_row'] or ''} |" for x in an['respawns'][:15]]
    if an.get('exits'):
        L += ['', '### Abnormal exits', ''] + [f"- {x['service']}: {x['why']} ×{x['count']}" for x in an['exits'][:15]]
    if an.get('hkmain') or an.get('hkmain_stalls'):
        L += ['', '### HKMAIN (main-thread watch)', '']
        for k, v in (an.get('hkmain') or {}).items():
            L.append(f"- {k} last: t={v['t']} pings={v['pings']} wait={v['wait']} touch={v['touch']} press={v['press']} stalls={v['stalls']}")
        for s in an.get('hkmain_stalls') or []:
            L.append(f"- stall ×{s['count']} (max {s['max_ms']} ms): pc `{s['pc']}` lr `{s['lr']}`")
    if an.get('ustack_summary'):
        L += ['', '### hk_ustack main threads (ustack_sym.py --summary --main-only)', '', '```']
        L += an['ustack_summary']['head'] + ['```', f"Full: `{an['ustack_summary']['path']}`"]
    ui = r.get('ui') or {}
    if ui.get('cmd') or ui.get('steps'):
        L += ['', '## UI', '', f"- Runner: `{' '.join(ui.get('cmd') or [])}` rc {ui.get('rc')}, verdict {ui.get('verdict')}"]
        L += [f"- {k}: {'ok' if v else 'FAILED'}" for k, v in (ui.get('steps') or {}).items()]
    L += ['', '## Files', '', f"- Cycle: `{r.get('out')}` (cycle.log, cmd/ per-command output, analysis/, screens/, return-check/)"]
    for s in r.get('steps', []):
        if s.get('live_run') or s.get('attempt'):
            L.append(f"- live run `{s.get('live_run')}`, attempt `{s.get('attempt')}`")
    return '\n'.join(L) + '\n'


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--image', help='research/images/X (directory) or its boot.img')
    p.add_argument('--mach', help='the image kernel, .unstripped (symbols; its UUID must be in the image)')
    p.add_argument('--ui', help="UI script for tools/ui_run.py, or 'settings' for tools/ui_settings_test.py")
    p.add_argument('--ui-cmd', help='UI runner command with {run} {script} {json} {out} (default: tools/ui_run.py {run} {script}; it writes {run}/ui_run.json)')
    p.add_argument('--builtin-eval', action='store_true', help="use hk_cycle's own matcher even if tools/probe_eval.py exists")
    p.add_argument('--attended', action='store_true', help='someone used the phone by hand: rows that need input count as exercised')
    p.add_argument('--force-ui', action='store_true', help='run the UI script although the image lacks blazer_usbcon_input=1')
    p.add_argument('--expect', help='expectations (YAML or JSON), e.g. research/ios26-phaseb-r1/live/expect/int1.yaml')
    p.add_argument('--deadline-wait', type=int, help='seconds to wait for the park after the console appears (default: the '
                   "image's blazer_deadline + 180, else 1200)")
    p.add_argument('--name', help='attempt name (default: the image directory name)')
    p.add_argument('--out', help='cycle directory (default research/hk-cycles/<ts>-<name>)')
    p.add_argument('--mode', choices=('auto', 'bootios', 'plain'), default='auto',
                   help='bootios: live_boot.sh/run-attempt (A7 images); plain: bare fastboot boot (chooser images); auto by manifest')
    p.add_argument('--busy-wait', type=int, default=0, help='if an iOS boot is running at the start, wait this long for its park')
    p.add_argument('--overwrite-mac', action='store_true', help='replace a different Mac copy of the image/kernel')
    p.add_argument('--no-sync-tools', action='store_true', help="run the Mac's own tools/usbcon.py")
    p.add_argument('--no-console', action='store_true')
    p.add_argument('--no-shots', action='store_true', help='no periodic live screenshots')
    p.add_argument('--shot-every', type=float, default=60)
    p.add_argument('--shot-step', type=int, default=8)
    p.add_argument('--max-shots', type=int, default=40)
    p.add_argument('--skip-image-check', action='store_true')
    p.add_argument('--no-return-check', action='store_true')
    p.add_argument('--cache', default=DEFAULT_CACHE, help='dyld shared cache for symbols')
    p.add_argument('--poll', type=float, default=10, help='phone state poll interval, seconds')
    p.add_argument('--timeouts', help='override bounds, k=v,...: ' + ','.join(f'{k}={v}' for k, v in TIMEOUTS.items()))
    p.add_argument('--report-only', metavar='CYCLE_DIR', help='redo analysis and report of a finished cycle; no device')
    a = p.parse_args(argv)
    if not a.report_only and not a.image:
        p.error('--image is required (or --report-only DIR)')
    return a


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    c = Cycle(a)
    try:
        return c.report_only() if a.report_only else c.main()
    except Refused as e:
        print(f'hk_cycle: {e.state}: {e.detail}', file=sys.stderr)
        return e.code
    except ValueError as e:
        print(f'hk_cycle: {e}', file=sys.stderr)
        return EXIT_USAGE


if __name__ == '__main__':
    sys.exit(main())
