#!/usr/bin/env python3
"""Crash census over phone boot dumps: find, split by boot, symbolicate, group by signature, attach known causes.

    python3 -I tools/crashdoc.py ATTEMPT_DIR_OR_LOG [...] [--out DIR] [--cache DSC] [--no-symbols]

Inputs: an attempt directory (`ramdump/kernel.log`, else `kernel.log`, else `console.txt`; `reader.txt` and `meta.txt` beside it
add the TSHIMST2 nonce, verdict and start time), a parent directory of attempts (every child that has a log), or a bare log.

1. Events. `usertrap:` (header + `called from` + `xN ->` lines), `userabort:` (+ the `|proc| *** Terminating app ...` reason and
   the `First throw call stack`), launchd `exited due to` / `exited with exit reason`, `exec: SIGKILL to ... reason namespace`
   (watchdogs), `CRASH proc reason ns`, kernel `panic(cpu ...)`, `HKMAIN: stall` (+ `HKMAIN: frames`), and the standard abort
   messages (`Assertion failed`, `BUG IN CLIENT OF`, Swift `Fatal error`).
2. Boots. A ramdump is a ring: the newest boot first, then residue of older boots (and Android), and the 4 MiB file holds two
   copies (console zone and the pmsg msgbuf mirror). Each NUL-separated region is cut into fragments at boot banners
   (`TEGU-XNU STAGE0`, `Darwin Kernel Version`, `Linux version`), at a change of dyld shared-cache slide and at a launchd
   wall-clock jump (whole-hour jumps are time-zone changes and are not cuts). Fragments are joined into one boot when they share
   the slide or an exact unique line (a launchd line with its microsecond time stamp, a panic line, a usertrap header with sp).
   Two different slides never join. The fragment that holds reader.txt's msgbuf tail is the attempt's own boot and gets its
   TSHIMST2 nonce; everything else is residue and is attributed to its own boot, never to the attempt. Events are deduplicated
   per boot, so the second copy and residue in later dumps do not count twice.
3. Symbols (dyld cache, default dsc-r6 0f1ee332; slide from the event line): unslid = addr - slide, the containing image, and
   the function from LC_FUNCTION_STARTS. It is named by the exported nlist at that start, else by the local-name table below
   (seeded from today's disassembly), else `func_<unslid start>` with the nearest export. Main-binary frames are `Proc+off`
   from `main header` (usertrap) or 0x100000000 + `main_slide` (HKMAIN). Return addresses are looked up at addr - 4.
4. Signatures: process + unslid culprit pc. Culprit = pc for usertraps; for aborts, stalls and throw stacks the first frame
   outside the abort/runloop machinery images (libsystem_*, libc++abi, libobjc, CoreFoundation, Foundation, libdispatch,
   libswiftCore). Each signature gets counts per boot (distinct pids), first/last seen, and a status: `open` (in the latest boot
   that ran the process), `not seen since` (the process ran in N later boots without it) or `not exercised since`.
5. Output `crashes.md` and `crashes.json` in --out, with the cause hints (HINTS) that match each signature.

Host only, standard library only. Reads nothing but the named files and the dyld cache.
"""
import argparse
import bisect
import collections
import datetime as dt
import hashlib
import importlib.util
import json
import re
import statistics
import struct
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
DEFAULT_CACHE = '/data/hackios-qemu/dsc-r6/dyld_shared_cache_arm64e'

# --------------------------------------------------------------------------------------------------------------------------
# Known causes (seeded from 2026-11-03 findings). Matching: every given key must match.
#   proc: regex on the process / launchd label; loc: exact culprit location; any_loc: location of any frame;
#   sym: substring of any symbolicated frame; text: regex on the message / reason; kind: event kind.
HINTS = [
    dict(id='corebrightness-calibration', kind='usertrap', any_loc='0x1e2746924',
         cause='Missing backlight calibration: with hk_bright=140 our AppleARMBacklight has no backlight-calibration-parameters, '
               'so CoreBrightness Display init (0x1e2741c1c) takes the fallback and its lookup 0x1e2746810 reads the still-NULL '
               'marketing table at 0x1e2746924. Fix: patch 0001-hk-bright-backlight-calibration (calibration + marketing table), '
               'or drop hk_bright=140.',
         ref='research/ios26-phaseb-r1/corebrightness/FINDINGS.md'),
    dict(id='mobilephone-contacts-tcc', proc=r'^MobilePhone$', loc='MobilePhone+0x1e2bc0',
         cause='Contacts TCC: +[CNContactStore contactStore] returns nil because tccd does not report kTCCServiceAddressBook '
               'authorized; favoritesDataSource.getter force-unwraps it (brk #1). Next: mirror tccd (F2), then seed TCC (F3).',
         ref='research/ios26-apps-r1/crashes-r9/FINDINGS.md'),
    dict(id='preferences-sandbox-token', proc=r'^Preferences$', kind='usertrap', sym='sandbox_extension_consume',
         cause='NULL sandbox token: our Sandbox stand-in returns ENOENT for op 5 (extension issue), so containermanagerd hands '
               'out NULL tokens and SafariCore WBSSetUpAccessToAppDataContainerWithIdentifier passes NULL to '
               'sandbox_extension_consume. Fix F1: op 5 copies out libsandbox\'s no-op token "invalid".',
         ref='research/ios26-apps-r1/crashes-r9/FINDINGS.md'),
    dict(id='configd-ionetworkstack', sym='SCDynamicStoreNotifyWait',
         cause='Main thread waits in SCNetworkInterfaceCopyAll -> _SCDynamicStoreNotifyWait for Plugin:InterfaceNamer; configd '
               'writes it only once an IONetworkStack exists (or after its 300 s WaitStackTimeout). Our kernel publishes '
               'IONetworkStack only with blazer_usbnet=2 / blazer_wifi_net=2.',
         ref='research/ios26-phaseb-r1/configd/FIX.md'),
    dict(id='backboardd-nsurl-container', text=r'initFileURLWithPath:\]: nil string parameter',
         cause='BaseBoard BSSystemSharedDirectoryForIdentifier got NULL from container_system_path_for_identifier '
               '(containermanagerd not ready); phone-side timing, QEMU never reproduces it. hk_container_ready is the fix.',
         ref='research/ios26-apps-r1/receipts/l1-r16/LANE1.md'),
    dict(id='preferences-launch-watchdog', proc=r'Preferences', text=r'8badf00d',
         cause='runningboard launch watchdog (0x8badf00d): Settings did not finish launching in time. In r10 HKMAIN showed the '
               'main thread in _SCDynamicStoreNotifyWait (see configd-ionetworkstack).',
         ref='research/ios26-phaseb-r1/configd/FIX.md'),
    dict(id='about-preferences-medialibrary', proc=r'^Preferences$', kinds=('crash', 'userabort', 'exit'),
         text=r'code 0x6|SIGABRT', context=r'kTCCServiceMediaLibrary|generic_extension="invalid"',
         cause='Settings > About: Preferences aborts (SIGABRT) right after tccd answers its kTCCServiceMediaLibrary request '
               'with generic_extension="invalid" (no usable sandbox extension). ABOUT finding, int1.',
         ref='ABOUT (int1), coordinator update 2026-11-03'),
    dict(id='axui-punctuation-model', proc=r'^AccessibilityUI', kinds=('crash', 'userabort', 'exit'),
         cause='AccessibilityUIServer crash loop: the root build\'s prune deleted AXSSPunctuationModel.momd, so the CoreData model '
               'load throws (abort culprit CoreData 0x185bff6c0) on every respawn. Fix: keep the .momd in the root build. '
               'ABOUT finding, int1; matched by process for earlier boots of the same root.',
         ref='ABOUT (int1), coordinator update 2026-11-03'),
    dict(id='blastdoor-sandbox-check', proc=r'^MessagesBlastDoo', kinds=('crash', 'usertrap', 'userabort', 'exit'),
         cause='MessagesBlastDoorService SIGTRAP: Swift fatalError in Sandbox.swift after sandbox_check, because the SWEET '
               'sandbox stub returns 0 for every op. New in int1, launched via callservicesd/CallKit.',
         ref='ABOUT (int1), coordinator update 2026-11-03'),
    dict(id='blazer-deadline', kind='panic', text=r'blazer-root: deadline|boot ended on purpose',
         cause='Intended end-of-boot timer (blazer_deadline), not a crash: the boot was cut here. A 300 s deadline ends the '
               'boot before Home on a slow start.',
         ref='research/ios26-phaseb-r1/A7.md'),
]

# Local (non-exported) functions named by today's disassembly (unslid, dsc-r6 0f1ee332).
LOCAL_NAMES = {
    0x1e2746810: 'CoreBrightness Display_lut (marketing-table lookup) [local]',
    0x1e2741c1c: 'CoreBrightness Display_init [local]',
    0x2a440b050: 'libsystem_platform strcmp-like (redacted) [local]',
    0x19075c400: 'BaseBoard _BSSystemSharedResourcesDirectoryForCurrentProcess caller -> -[NSURL initFileURLWithPath:] [local]',
}

# Images whose frames are abort / exception / runloop machinery, skipped when picking the culprit frame.
MACHINERY = ('libsystem_kernel.dylib', 'libsystem_c.dylib', 'libsystem_pthread.dylib', 'libsystem_platform.dylib',
             'libc++abi.dylib', 'libobjc.A.dylib', 'libdyld.dylib', 'CoreFoundation', 'Foundation', 'libdispatch.dylib',
             'libswiftCore.dylib', 'libsystem_malloc.dylib', 'libsystem_trace.dylib')

# CRASH lines: ns 2 (OS_REASON_SIGNAL) code = signal number.
CRASH_CODES = {4: 'SIGILL', 5: 'SIGTRAP', 6: 'SIGABRT', 9: 'SIGKILL', 10: 'SIGBUS', 11: 'SIGSEGV'}
CONTEXT_LINES = 30      # lines before an event searched for CONTEXT_RX
CONTEXT_RX = re.compile(r'kTCCServiceMediaLibrary|generic_extension="invalid"|AXSSPunctuationModel|Sandbox\.swift|sandbox_check')

EXC_NAMES = {1: 'EXC_BAD_ACCESS', 2: 'EXC_BAD_INSTRUCTION', 3: 'EXC_ARITHMETIC', 5: 'EXC_SOFTWARE', 6: 'EXC_BREAKPOINT',
             10: 'EXC_CRASH', 11: 'EXC_RESOURCE', 12: 'EXC_GUARD'}

# --------------------------------------------------------------------------------------------------------------------------
H = r'0x[0-9a-fA-F]+'
RX = dict(
    stage0=re.compile(r'TEGU-XNU STAGE0'),
    darwin=re.compile(r'Darwin Kernel Version \d'),
    linux=re.compile(r'Linux version \d+\.\d+'),
    slide=re.compile(rf'(?:shared cache slide|dsc_slide|HGLTRACK:.*?slide|HKACCEL:.*?slide) ({H})|HK USTACK: .*? slide=({H})'),
    launchd=re.compile(r'com\.apple\.xpc\.launchd\|(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{6})'),
    bootargs=re.compile(r'<Notice>: boot-args = (.*)'),
    usertrap=re.compile(rf'usertrap: (?P<proc>[^\s\[\]]+)\[(?P<pid>\d+)\] exception (?P<exc>\d+) code (?P<c0>{H}) (?P<c1>{H}): '
                        rf'pc (?P<pc>{H}) lr (?P<lr>{H}) sp (?P<sp>{H}), shared cache slide (?P<slide>{H}), '
                        rf'main header (?P<main>{H})'),
    ut_from=re.compile(rf'usertrap:   called from ({H})'),
    ut_reg=re.compile(r'usertrap:   (x\d+|lr|fp|sp) -> (.*)'),
    userabort=re.compile(rf'userabort: (?P<proc>[^\s\[\]]+)\[(?P<pid>\d+)\] aborts, shared cache slide (?P<slide>{H}); '
                         r'called from:(?P<rest>.*)'),
    exited=re.compile(r'com\.apple\.xpc\.launchd\|(?P<ts>\S+ \S+) \((?P<label>.+?) \[(?P<pid>\d+)\]\) <\w+>: '
                      r'(?P<what>exited due to (?P<why>[^,]+)|exited with exit reason \((?P<ns>[^)]*)\)(?P<tail>[^,]*))'),
    kill=re.compile(r'exec: SIGKILL to (?P<proc>[^\s\[\]]+)\[(?P<pid>\d+)\] from (?P<by>[^\s\[\]]+)\[\d+\], '
                    rf'reason namespace (?P<ns>\d+) code (?P<code>{H})'),
    crash=re.compile(rf'CRASH (?P<proc>\S+) reason ns (?P<ns>\d+) code (?P<code>{H}): (?P<why>.*)'),
    panic=re.compile(rf'panic\(cpu \d+ caller ({H})\): (?P<msg>.*)'),
    terminating=re.compile(r"\|(?P<proc>[^|]+)\| \*\*\* Terminating app due to uncaught exception '(?P<name>[^']*)', "
                           r"reason: '(?P<reason>.*)"),
    firstthrow=re.compile(r'\|(?P<proc>[^|]+)\| \*\*\* First throw call stack:'),
    message=re.compile(r'(?:\|(?P<proc>[^|]+)\| )?(?P<msg>(?:Assertion failed: |BUG IN CLIENT OF |[\w./]+:\d+: Fatal error: |'
                       r'Fatal error: |\*\*\* Assertion failure in ).*)'),
    hk_watch=re.compile(r'HKMAIN: (?P<proc>[^\s\[\]]+)\[(?P<pid>\d+)\] (?:watching|t=)'),
    hk_stall=re.compile(rf'HKMAIN: stall (?P<ms>\d+) ms pc (?P<pc>{H}) lr (?P<lr>{H}) sp (?P<sp>{H}) dsc_slide (?P<slide>{H}) '
                        rf'main_slide (?P<mslide>{H})'),
    hk_frames=re.compile(r'HKMAIN: frames((?: 0x[0-9a-fA-F]+)+)'),
    userland=re.compile(r'com\.apple\.xpc\.launchd\||usertrap: |userabort: |^SWEET |^HK |^exec |^CRASH |HGLTRACK:|HKACCEL:'),
    guard=re.compile(r'\[(?P<proc>[^\s:\]]+):(?P<pid>\d+)\] (?P<what>EXC_GUARD AST: .*)'),
    livecrash=re.compile(r'^LIVEBOOT (?P<t>\S+) \+[\d.]+ CRASH (?P<proc>\S+)\s*$'),
    hk_top=re.compile(r'HK TOP: t=(\d+) frames\+\d+ cpu_ms=\d+'),
    pname=re.compile(r'(?:^|[\s(:|])([A-Za-z][\w.+-]{1,40})\[(\d{1,6})\]'),
    pexec=re.compile(r'^exec ([\w.+-]{2,60})\s*$'),
)
HEX = re.compile(r'0x[0-9a-fA-F]+')
DECAY_RATIO = 0.10      # share of non-printable characters above which a fragment is binary data or decayed RAM


def valid_slide(s):
    return s is not None and s % 0x4000 == 0 and 0 < s < 0x80000000


def ts_parse(s):
    try:
        return dt.datetime.strptime(s, '%Y-%m-%d %H:%M:%S.%f')
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------------------------------
# Inputs

class Source:
    """One log file: lines numbered as in `tr -d '\\0' < log`, region cuts where NUL runs were."""

    def __init__(self, path, attempt=None, meta=None):
        self.path = Path(path)
        self.attempt = attempt or self.path.stem
        self.meta = meta or {}
        data = self.path.read_bytes()
        cuts, removed, pieces, last = set(), 0, [], 0
        for m in re.finditer(rb'\x00+', data):
            pieces.append(data[last:m.start()])
            if m.end() - m.start() >= 16:
                cuts.add(m.start() - removed)
            removed += m.end() - m.start()
            last = m.end()
        pieces.append(data[last:])
        text = b''.join(pieces)
        self.lines, self.region_start = [], set()
        cutl = sorted(cuts)
        pos, ci = 0, 0
        for raw in text.split(b'\n'):
            end = pos + len(raw)
            starts_region = False
            while ci < len(cutl) and cutl[ci] <= end:
                starts_region = True     # a cut before or inside this line
                ci += 1
            if starts_region or not self.lines:
                self.region_start.add(len(self.lines))
            self.lines.append(raw.decode('utf-8', 'replace'))
            pos = end + 1
        self.sha256 = hashlib.sha256(data).hexdigest()


def read_reader(path):
    out = {}
    if not path.exists():
        return out
    text = path.read_text(errors='replace')
    m = re.search(r'TSHIMST2 nonce=(0x[0-9a-f]+)', text)
    if m:
        out['nonce'] = m.group(1)
    m = re.search(r'^VERDICT: (\S+)', text, re.M)
    if m:
        out['verdict'] = m.group(1)
    i = text.find('----- XNU msgbuf tail -----')
    if i >= 0:
        section = text[i:].splitlines()[1:]
        end = next((k for k, l in enumerate(section) if l.startswith('-----')), len(section))
        # the last lines of the ring are the current boot's newest output; early-boot lines are common to every boot
        tail = [l for l in section[:end] if len(l) >= 24 and not l.startswith('TEGU-XNU EARLY')]
        out['tail'] = tail[-40:]
    return out


def read_markers(path):
    """tools/live_boot.sh markers.txt: the console nonce and LIVEBOOT CRASH lines."""
    out = {}
    if path.exists():
        text = path.read_text(errors='replace')
        m = re.search(r'CONSOLE_CONNECTED nonce (0x[0-9a-f]+)', text)
        if m:
            out['nonce'] = m.group(1)
        out['crashes'] = re.findall(r'^LIVEBOOT (\S+) \+[\d.]+ CRASH (\S+)', text, re.M)
    return out


def read_meta(path):
    out = {}
    if path.exists():
        for line in path.read_text(errors='replace').splitlines():
            k, _, v = line.partition(':')
            if k in ('attempt', 'started', 'image_sha256') and v.strip():
                out[k] = v.strip()
    return out


LOG_NAMES = ('ramdump/kernel.log', 'kernel.log', 'console.txt', 'markers.txt')


def attempt_log(d):
    for n in LOG_NAMES:
        p = d / n
        if p.is_file() and p.stat().st_size:
            return p
    return None


def collect(paths):
    """-> [(log path, attempt name, attempt dir or None)]"""
    out = []
    for p in map(Path, paths):
        if p.is_file():
            d = p.parent.parent if p.parent.name == 'ramdump' else p.parent
            out.append((p, d.name, d))
        elif p.is_dir():
            log = attempt_log(p)
            if log:
                out.append((log, p.name, p))
            else:
                for c in sorted(p.iterdir()):
                    if c.is_dir() and attempt_log(c):
                        out.append((attempt_log(c), c.name, c))
        else:
            raise SystemExit(f'crashdoc: no such file or directory: {p}')
    return out


def attempt_time(name, meta):
    m = re.search(r'(\d{8})-(\d{6})', name)
    s = meta.get('started')
    if s:
        try:
            return dt.datetime.strptime(s, '%Y-%m-%d %H:%M:%S %z').astimezone(dt.timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass
    if m:   # attempt dirs are named in host local time (+0100 on 2026-11-03)
        return dt.datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S') - dt.timedelta(hours=1)
    return None


# --------------------------------------------------------------------------------------------------------------------------
# Fragments and boots

class Fragment:
    def __init__(self, src, start):
        self.src, self.start, self.end = src, start, start   # [start, end) line indexes
        self.slide = None
        self.os = None
        self.banner = False
        self.times = []
        self.fps = set()
        self.boot = None
        self.decayed = False

    @property
    def ref(self):
        return f'{self.src.attempt}:{self.start + 1}-{self.end}'


def fingerprint(line):
    for key in ('launchd', 'panic'):
        m = RX[key].search(line)
        if m:
            return line[m.start():m.start() + 120]
    m = RX['usertrap'].search(line)
    if m:
        return m.group(0)
    m = RX['hk_stall'].search(line)
    if m:
        return m.group(0)
    return None


def nonprint_ratio(lines):
    n = bad = 0
    for l in lines:
        n += len(l) + 1
        bad += sum(1 for ch in l if ch == '\ufffd' or (ord(ch) < 32 and ch != '\t') or 127 <= ord(ch) < 160)
    return bad / n if n else 0.0


def split_fragments(src):
    frags, cur = [], None
    prev_norm, tz_off = None, dt.timedelta(0)
    last_stage0 = -10**9
    after_panic = False

    def cut(i):
        nonlocal cur, prev_norm, tz_off
        if cur is not None:
            cur.end = i
            if cur.end > cur.start:
                frags.append(cur)
        cur = Fragment(src, i)
        prev_norm, tz_off = None, dt.timedelta(0)

    for i, line in enumerate(src.lines):
        if i in src.region_start:
            cut(i)
            after_panic = False
        if after_panic and RX['userland'].search(line):
            cut(i)      # a panic ends its boot: userland text after it is an older boot's residue
            after_panic = False
        if RX['stage0'].search(line):
            cut(i); last_stage0 = i; cur.banner = True; cur.os = 'xnu'
        elif RX['darwin'].search(line):
            if i - last_stage0 > 80 or cur.start != last_stage0:
                cut(i)
            cur.banner = True; cur.os = 'xnu'
        elif RX['linux'].search(line):
            cut(i); cur.banner = True; cur.os = 'android'
        m = RX['launchd'].search(line)
        if m:
            t = ts_parse(m.group(1))
            if t is not None:
                if prev_norm is not None:
                    d = (t + tz_off - prev_norm).total_seconds()
                    r = abs(d) % 3600
                    if abs(d) > 60 and (r < 120 or r > 3480) and abs(d) <= 14 * 3600:
                        tz_off -= dt.timedelta(hours=round(d / 3600))     # time-zone change, same boot
                    elif d < -60 or d > 1800:
                        cut(i)
                prev_norm = t + tz_off
                cur.times.append(t)
        m = RX['slide'].search(line)
        if m:
            s = int(m.group(1) or m.group(2), 16)
            if valid_slide(s):
                if cur.slide is not None and s != cur.slide:
                    cut(i)      # a launchd time jump usually cut earlier; otherwise the new slide opens a fragment
                if cur.slide is None:
                    cur.slide = s
        if RX['panic'].search(line):
            after_panic = True
        fp = fingerprint(line)
        if fp:
            cur.fps.add(fp)
        if cur.os is None and ('usertrap:' in line or 'com.apple.xpc.launchd' in line or 'SWEET ' in line):
            cur.os = 'xnu'
    if cur is not None:
        cur.end = len(src.lines)
        if cur.end > cur.start:
            frags.append(cur)
    for f in frags:
        f.decayed = nonprint_ratio(src.lines[f.start:f.end]) > DECAY_RATIO
        if f.os is None and any('Booting Linux' in l or re.match(r'^\[\s*\d+\.\d{6}\]', l)
                                for l in src.lines[f.start:min(f.end, f.start + 200)]):
            f.os = 'android'
    return frags


class Boot:
    def __init__(self, idx):
        self.idx = idx
        self.frags = []
        self.slide = None
        self.nonce = None
        self.current_in = []
        self.events = []
        self.procs = set()
        self.id = None

    @property
    def os(self):
        oses = {f.os for f in self.frags if f.os}
        return 'xnu' if 'xnu' in oses else (oses.pop() if oses else 'unknown')

    @property
    def decayed(self):
        return all(f.decayed for f in self.frags)

    def time(self):
        ts = sorted(t for f in self.frags for t in f.times if t.year >= 2020)    # 1970 = phone clock not yet set
        if ts:
            return ts[len(ts) // 2]       # median: robust to the few time-zone-shifted launchd lines
        for a, t in self.current_in:
            if t:
                return t
        return None

    def lines(self):
        for f in self.frags:
            for i in range(f.start, f.end):
                yield f, i, f.src.lines[i]


class DSU:
    def __init__(self, n):
        self.p = list(range(n))
        self.slide = [None] * n

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return True
        if self.slide[a] is not None and self.slide[b] is not None and self.slide[a] != self.slide[b]:
            return False        # different slides are different boots, whatever a fingerprint says
        self.p[b] = a
        self.slide[a] = self.slide[a] if self.slide[a] is not None else self.slide[b]
        return True


def build_boots(frags):
    frags = [f for f in frags if not f.decayed]     # binary or decayed text joins no boot (counted per source)
    dsu = DSU(len(frags))
    for i, f in enumerate(frags):
        dsu.slide[i] = f.slide
    by_slide = collections.defaultdict(list)
    for i, f in enumerate(frags):
        if f.slide is not None and not f.decayed:
            by_slide[f.slide].append(i)
    for idx in by_slide.values():
        for j in idx[1:]:
            dsu.union(idx[0], j)
    by_fp = collections.defaultdict(list)
    for i, f in enumerate(frags):
        if f.decayed:
            continue
        for fp in f.fps:
            by_fp[fp].append(i)
    for idx in by_fp.values():
        for j in idx[1:]:
            dsu.union(idx[0], j)
    # A fragment with no slide (e.g. the msgbuf mirror's copy of a boot's last minutes) joins a slid boot from the same file
    # when its launchd times touch that boot's time span, and only when exactly one boot qualifies.
    def span(idxs):
        ts = sorted(t for k in idxs for t in frags[k].times)
        if not ts:
            return None
        med = ts[len(ts) // 2]
        ts = [t for t in ts if abs((t - med).total_seconds()) < 3 * 3600]     # drop time-zone-shifted lines
        return ts[0], ts[-1]
    comps = collections.defaultdict(list)
    for i in range(len(frags)):
        comps[dsu.find(i)].append(i)
    slid = {r: (span(ix), {frags[k].src.path for k in ix}) for r, ix in comps.items() if dsu.slide[r] is not None}
    pad = dt.timedelta(seconds=120)
    for r, ix in list(comps.items()):
        if dsu.slide[r] is not None:
            continue
        sp = span(ix)
        if sp is None:
            continue
        paths = {frags[k].src.path for k in ix}
        cands = [q for q, (qs, qp) in slid.items() if qs and qp & paths and qs[0] - pad <= sp[1] and sp[0] <= qs[1] + pad]
        if len(cands) == 1:
            dsu.union(cands[0], r)
    groups = collections.defaultdict(list)
    for i in range(len(frags)):
        groups[dsu.find(i)].append(frags[i])
    boots = []
    for g in groups.values():
        b = Boot(len(boots))
        b.frags = sorted(g, key=lambda f: (f.src.attempt, f.start))
        b.slide = next((f.slide for f in g if f.slide is not None), None)
        for f in g:
            f.boot = b
        boots.append(b)
    return boots


def mark_current(src, frags, reader, when):
    """The fragment holding reader.txt's msgbuf tail (else the fragment at line 1 if it opens with a banner) is the attempt's
    own boot."""
    own = None
    frags = [f for f in frags if f.boot is not None]
    tail = reader.get('tail') or []
    if tail:
        tailset = set(tail)
        best = max(frags, key=lambda f: sum(1 for i in range(f.start, f.end) if src.lines[i] in tailset), default=None)
        if best and sum(1 for i in range(best.start, best.end) if src.lines[i] in tailset) >= 3:
            own = best
    if own is None and frags and frags[0].banner and frags[0].start == 0:
        own = frags[0]
    if own is None and frags and src.path.name in ('console.txt', 'markers.txt'):
        own = max(frags, key=lambda f: f.end - f.start)      # a live console (tools/live_boot.sh) records one boot
    if own is not None:
        b = own.boot
        b.current_in.append((src.attempt, when))
        if reader.get('nonce') and not b.nonce:
            b.nonce = reader['nonce']
    return own


# --------------------------------------------------------------------------------------------------------------------------
# Symbols

def uleb_starts(data, base):
    out, a, i = [], base, 0
    while i < len(data):
        v = sh = 0
        while True:
            c = data[i]; i += 1
            v |= (c & 0x7f) << sh; sh += 7
            if not c & 0x80 or i >= len(data):
                break
        if v == 0:
            break
        a += v
        out.append(a)
    return out


class Symbolizer:
    def __init__(self, cache_path=None):
        self.cache = None
        self.path = cache_path
        self.uuid = None
        self.err = None
        self.images = {}
        if cache_path:
            try:
                spec = importlib.util.spec_from_file_location('live_profile', TOOLS / 'live_profile.py')
                lp = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(lp)
                self.cache = lp.CacheImages(cache_path)
                self.uuid = self.cache.uuid
            except Exception as e:      # no cache: addresses stay unnamed, everything else still works
                self.err = f'{type(e).__name__}: {e}'
                self.cache = None

    def close(self):
        if self.cache:
            self.cache.close()

    def image(self, base):
        img = self.images.get(base)
        if img is not None:
            return img
        c = self.cache
        syms, starts = [], []
        try:
            _, _, _, _, nc, size, _, _ = struct.unpack('<IiiIIIII', c.read(base, 32))
            cmds = c.read(base + 32, size)
            off, linkedit, symtab, fstarts, text = 0, None, None, None, base
            for _ in range(nc):
                cmd, cs = struct.unpack_from('<II', cmds, off)
                if cmd == 0x19:
                    name = cmds[off + 8:off + 24].split(b'\0')[0]
                    vm, _, fo, _ = struct.unpack_from('<QQQQ', cmds, off + 24)
                    if name == b'__LINKEDIT':
                        linkedit = (vm, fo)
                    elif name == b'__TEXT':
                        text = vm
                elif cmd == 0x2:
                    symtab = struct.unpack_from('<IIII', cmds, off + 8)
                elif cmd == 0x26:
                    fstarts = struct.unpack_from('<II', cmds, off + 8)
                off += cs
            if linkedit:
                at = lambda fo: linkedit[0] + (fo - linkedit[1])
                if symtab:
                    symoff, nsyms, stroff, strsize = symtab
                    raw = c.read(at(symoff), nsyms * 16)
                    strs = c.read(at(stroff), strsize)
                    for k in range(nsyms):
                        strx, ntype, _, _, value = struct.unpack_from('<IBBHQ', raw, k * 16)
                        if ntype & 0xe0 or (ntype & 0x0e) != 0x0e or not value:
                            continue
                        e = strs.find(b'\0', strx)
                        syms.append((value, strs[strx:e].decode('utf-8', 'replace')))
                if fstarts and fstarts[1]:
                    starts = uleb_starts(c.read(at(fstarts[0]), fstarts[1]), text)
        except (ValueError, struct.error, IndexError):
            pass
        syms = sorted(x for x in syms if x[1] != '<redacted>')      # local symbols are redacted in the shipped cache
        img = self.images[base] = dict(syms=syms, sym_addrs=[s[0] for s in syms], byaddr=dict(syms), starts=starts)
        return img

    def cache_frame(self, u, ret):
        """Name an unslid cache address. ret: a return address (look up the call at u - 4)."""
        if not self.cache:
            return None
        probe = u - 4 if ret else u
        try:
            info = self.cache.who(probe) if probe > 0 else None
        except ValueError:
            info = None
        if not info:
            return None
        base = probe - info['image_offset']
        img = self.image(base)
        short = info['image'].rsplit('/', 1)[-1]
        out = dict(image=short, image_path=info['image'], image_off=u - base, func=None, func_start=None, off=None, how=None)
        i = bisect.bisect_right(img['starts'], probe) - 1
        fs = img['starts'][i] if i >= 0 else None
        j = bisect.bisect_right(img['sym_addrs'], probe) - 1
        ns = img['syms'][j] if j >= 0 else None
        if fs is not None:
            out['func_start'] = fs
            out['off'] = u - fs
            if fs in img['byaddr']:
                out['func'], out['how'] = img['byaddr'][fs], 'export'
            elif ns and ns[0] >= fs:
                out['func'], out['func_start'], out['off'], out['how'] = ns[1], ns[0], u - ns[0], 'export'
            elif fs in LOCAL_NAMES:
                out['func'], out['how'] = LOCAL_NAMES[fs], 'known-local'
            else:
                out['func'], out['how'] = f'func_{fs:x}', 'function-start'
                if ns:
                    out['nearest'] = f'{ns[1]}+{u - ns[0]:#x}'
        elif ns:
            out['func'], out['func_start'], out['off'], out['how'] = ns[1], ns[0], u - ns[0], 'nearest-export'
        return out

    def frame(self, addr, slide, main=None, proc=None, ret=False):
        f = dict(addr=f'{addr:#x}')
        if slide is not None:
            u = addr - slide
            c = self.cache_frame(u, ret)
            if c:
                f.update(c)
                f['unslid'] = f'{u:#x}'
                f['loc'] = f'{u:#x}'
                f['text'] = f"{c['image']} {c['func']}+{c['off']:#x}" if c['func'] else f"{c['image']}+{c['image_off']:#x}"
                return f
            if self.cache is None and 0x180000000 <= u < 0x300000000:
                f['unslid'] = f['loc'] = f'{u:#x}'
                f['text'] = f'cache {u:#x} (no symbols)'
                return f
        if main is not None and main <= addr < main + 0x10000000:
            f['image'] = proc or 'main'
            f['image_off'] = addr - main
            f['loc'] = f"{f['image']}+{addr - main:#x}"
            f['text'] = f['loc']
            return f
        f['loc'] = None
        f['text'] = f'? {addr:#x}' + (' (outside the cache: main binary or a non-cache image)' if 0x100000000 <= addr < 0x180000000 else '')
        return f


def culprit(frames, skip_first=0):
    for f in frames[skip_first:]:
        if f.get('loc') and f.get('image') not in MACHINERY:
            return f
    return next((f for f in frames if f.get('loc')), frames[0] if frames else None)


# --------------------------------------------------------------------------------------------------------------------------
# Events

def hexes(s):
    """Hex tokens of a frame list. Console interleaving glues the next message onto a frame ('0x1c96b95b0com.apple...'):
    user addresses have at most 9 hex digits, so a longer token followed by a letter is cut back to 9."""
    out = []
    for m in re.finditer(r'0x([0-9a-fA-F]+)([A-Za-z]?)', s):
        digits = m.group(1)
        if len(digits) > 9 and (m.group(2) or m.end() < len(s) and s[m.end()].isalpha()):
            digits = digits[:9]
        out.append(int(digits, 16))
    return out


def parse_events(boot, sym):
    """Events of one boot, deduplicated (the dump holds two copies, and residue repeats across dumps)."""
    seen, out = set(), []
    lines = [(f, i, l) for f, i, l in boot.lines() if not f.decayed]

    def add(key, ev, f, i):
        ev['ref'] = f'{f.src.attempt}:{i + 1}'
        if ev['kind'] in ('usertrap', 'userabort', 'crash'):
            last_ev[ev['proc'][:16]] = n        # also for a duplicate copy: its CRASH / exit lines follow it
        if ev['kind'] in ('usertrap', 'userabort'):
            last_trap[ev['proc'][:16]] = n
        if key in seen:
            return None
        seen.add(key)
        ev['boot'] = boot
        ctx = set()
        for (ff, _, l) in lines[max(0, n - CONTEXT_LINES):n + 1]:
            if ff is f:
                ctx.update(m.group(0) for m in CONTEXT_RX.finditer(l))
        if ctx:
            ev['context'] = sorted(ctx)
        out.append(ev)
        return ev

    last_ev, last_trap, guard, last_fp = {}, {}, {}, None

    hk_proc = {}
    names = collections.defaultdict(collections.Counter)
    for f, i, line in lines:
        for m in RX['pname'].finditer(line):
            if m.group(1) not in ('xpcproxy', 'handler', 'launchd'):     # exec trampolines and "exc handler[pid]"
                names[int(m.group(2))][m.group(1)] += 1
    pidname = {pid: c.most_common(1)[0][0] for pid, c in names.items()}
    for n, (f, i, line) in enumerate(lines):
        fp = fingerprint(line)
        if fp:
            last_fp = fp
        for m in RX['pname'].finditer(line):
            boot.procs.add(m.group(1))
        m = RX['pexec'].match(line)
        if m:
            boot.procs.add(m.group(1))
        window = [l for (ff, _, l) in lines[n + 1:n + 60] if ff is f]

        m = RX['usertrap'].search(line)
        if m:
            d = m.groupdict()
            slide, main = int(d['slide'], 16), int(d['main'], 16)
            regs, chain = {}, []
            for l in window:
                if RX['usertrap'].search(l):
                    break
                mm = RX['ut_from'].search(l)
                if mm:
                    chain.append(int(mm.group(1), 16))
                    continue
                mm = RX['ut_reg'].search(l)
                if mm:
                    regs[mm.group(1)] = mm.group(2)
            pc, lr = int(d['pc'], 16), int(d['lr'], 16)
            frames = [sym.frame(pc, slide, main, d['proc'])] + [sym.frame(a, slide, main, d['proc'], ret=True)
                                                                for a in [lr] + chain]
            exc = int(d['exc'])
            ev = dict(kind='usertrap', proc=d['proc'], pid=int(d['pid']), slide=f'{slide:#x}', main=f'{main:#x}',
                      exception=f'{exc} {EXC_NAMES.get(exc, "")}'.strip(), code=f"{d['c0']} {d['c1']}",
                      regs=regs, frames=frames, culprit=frames[0])
            for l in window[:40]:
                mm = RX['crash'].search(l)
                if mm and mm.group('proc') == d['proc']:
                    ev['crash_reason'] = f"ns {mm.group('ns')} code {mm.group('code')}"
                    break
            add(('usertrap', d['proc'], d['pid'], d['pc'], d['sp']), ev, f, i)
            continue

        m = RX['userabort'].search(line)
        if m:
            d = m.groupdict()
            slide = int(d['slide'], 16)
            addrs = hexes(d['rest'])
            if len(addrs) < 20:     # the list was cut by interleaved console text: its rest starts a later line
                for l in window[:30]:
                    mm = re.match(r'^\s*((?:0x[0-9a-fA-F]+\s*){2,})', l)
                    if mm and not RX['userabort'].search(l):
                        addrs += hexes(mm.group(1))
                        break
            addrs = [a for a in addrs if a]
            frames = [sym.frame(a, slide, None, d['proc'], ret=True) for a in addrs]
            ev = dict(kind='userabort', proc=d['proc'], pid=int(d['pid']), slide=f'{slide:#x}', frames=frames,
                      culprit=culprit(frames))
            back = [l for (ff, _, l) in lines[max(0, n - 60):n] if ff is f]
            for l in reversed(back):
                mm = RX['terminating'].search(l)
                if mm and mm.group('proc') == d['proc']:
                    ev['exception'] = mm.group('name')
                    ev['reason'] = mm.group('reason').rstrip("'")
                    break
            for k, l in enumerate(back):
                mm = RX['firstthrow'].search(l)
                if mm and mm.group('proc') == d['proc']:
                    blob = ' '.join(x for x in back[k + 1:k + 12])
                    blob = blob[blob.find('(') + 1:] if '(' in blob else blob
                    blob = blob.split(')')[0]
                    ta = [a for a in hexes(blob) if a > 0x100000000]
                    if ta:
                        ev['throw'] = [sym.frame(a, slide, None, d['proc'], ret=True) for a in ta]
                        ev['culprit'] = culprit(ev['throw'])
            for l in window[:40]:
                mm = RX['crash'].search(l)
                if mm and mm.group('proc') == d['proc']:
                    ev['crash_reason'] = f"ns {mm.group('ns')} code {mm.group('code')}"
                    break
            add(('userabort', d['proc'], d['pid'], tuple(addrs[:8])), ev, f, i)
            continue

        m = RX['exited'].search(line)
        if m:
            d = m.groupdict()
            label = d['label']
            proc = label.rsplit('/', 1)[-1]
            proc = re.sub(r'^UIKitApplication:', '', proc)
            proc = re.sub(r'\[[0-9a-f]+\](\[rb-legacy\])?$', '', proc)
            why = d['why'].strip() if d['why'] else f"exit reason ({d['ns']})"
            pname = pidname.get(int(d['pid']), proc)
            keys = {pname[:16].lower(), proc.rsplit('.', 1)[-1][:16].lower()}
            # the exit of a crash recorded just above (CRASH/usertrap lines precede launchd's exit line)
            linked = any(n - at <= 200 for k, at in last_ev.items() if k.lower() in keys)
            ev = dict(kind='exit', proc=pidname.get(int(d['pid']), proc), label=proc, pid=int(d['pid']), why=why, ts=d['ts'],
                      benign=bool(re.fullmatch(r'exit\(0\)', why) or 'during teardown' in why), linked=linked)
            add(('exit', label, d['pid'], why), ev, f, i)
            continue

        m = RX['kill'].search(line)
        if m:
            d = m.groupdict()
            ev = dict(kind='kill', proc=d['proc'], pid=int(d['pid']),
                      message=f"SIGKILL by {d['by']} ns {d['ns']} code {d['code']}")
            add(('kill', d['proc'], d['pid'], d['code']), ev, f, i)
            continue

        m = RX['panic'].search(line)
        if m:
            msg = m.group('msg').strip()
            ev = dict(kind='panic', proc='kernel', pid=0, message=msg, caller=m.group(1))
            add(('panic', msg), ev, f, i)
            continue

        m = RX['hk_watch'].search(line)
        if m:
            hk_proc = dict(proc=m.group('proc'), pid=int(m.group('pid')))
        m = RX['hk_stall'].search(line)
        if m:
            d = m.groupdict()
            slide, mslide = int(d['slide'], 16), int(d['mslide'], 16)
            main = 0x100000000 + mslide
            chain = []
            for l in window[:3]:
                mm = RX['hk_frames'].search(l)
                if mm:
                    chain = hexes(mm.group(1))
                    break
            proc = hk_proc.get('proc', '?')
            frames = [sym.frame(int(d['pc'], 16), slide, main, proc)] + \
                     [sym.frame(a, slide, main, proc, ret=True) for a in [int(d['lr'], 16)] + chain]
            ev = dict(kind='stall', proc=proc, pid=hk_proc.get('pid', 0), slide=f'{slide:#x}', main=f'{main:#x}',
                      stall_ms=int(d['ms']), frames=frames, culprit=culprit(frames))
            add(('stall', proc, hk_proc.get('pid'), d['ms'], d['pc']), ev, f, i)
            continue

        m = RX['guard'].search(line)
        if m:
            guard[m.group('proc')[:16]] = (int(m.group('pid')), m.group('what'))
            continue

        m = RX['crash'].search(line) or RX['livecrash'].search(line)
        if m:
            d = m.groupdict()
            p16 = d['proc'][:16]
            if n - last_trap.get(p16, -10**9) > 40:     # no usertrap/userabort for it just before: a crash on its own
                code = d.get('code')
                ev = dict(kind='crash', proc=d['proc'], pid=0,
                          crash_reason=f"ns {d['ns']} code {code}" if code else 'LIVEBOOT CRASH marker',
                          message=f"CRASH {d['proc']}" + (f" code {code} ({CRASH_CODES.get(int(code, 16), '?')})" if code else ''))
                g = guard.pop(p16, None)
                if g:
                    ev['pid'], ev['guard'] = g
                add(('crash', d['proc'], code, line if d.get('t') or re.match(r'^\d\d:\d\d:\d\d', line) else None,
                     ev['pid'] or last_fp), ev, f, i)
            continue

        m = RX['message'].search(line)
        if m and 'usertrap' not in line:
            proc = (m.group('proc') or '?').strip()
            msg = m.group('msg').strip()
            ev = dict(kind='message', proc=proc, pid=0, message=msg)
            add(('message', proc, msg), ev, f, i)
            continue

        m = RX['terminating'].search(line)
        if m:
            # an uncaught exception without a userabort line nearby is still recorded
            follow = any(RX['userabort'].search(l) for l in window[:40])
            if not follow:
                ev = dict(kind='message', proc=m.group('proc'), pid=0,
                          message=f"uncaught {m.group('name')}: {m.group('reason').rstrip(chr(39))}")
                add(('message', m.group('proc'), ev['message']), ev, f, i)
    boot.events = out
    return out


# --------------------------------------------------------------------------------------------------------------------------
# Signatures

def norm_msg(s):
    """Message signature: numbers become N, hex values 0x_ (pids, counts and addresses vary per incident)."""
    s = re.sub(r'0x[0-9a-fA-F]+', '\0', s)
    s = re.sub(r'\d+', 'N', s).replace('\0', '0x_')
    return s[:160]


def signature(ev):
    k, p = ev['kind'], ev['proc']
    if k in ('usertrap', 'userabort', 'stall'):
        c = ev.get('culprit') or {}
        loc = (c.get('loc') or c.get('addr')) if c else 'frames-lost'
        extra = ''
        if k == 'userabort' and ev.get('reason'):
            extra = ' | ' + norm_msg(ev['reason'])[:80]
        return f'{k}:{p}@{loc}{extra}'
    if k == 'exit':
        return f"{'exit-of-crash' if ev.get('linked') else 'exit'}:{ev['label']}:{ev['why'].split(' | ')[0] if 'SIG' in ev['why'] else ev['why']}"
    if k == 'crash':
        return f"crash:{p}:{ev['crash_reason']}"          # signal codes stay exact
    if k == 'kill':
        return f"kill:{p}:{ev['message']}"                # by whom + namespace + code; no pid in it
    if k in ('panic', 'message'):
        return f"{k}:{p}:{norm_msg(ev['message'])}"
    return f'{k}:{p}'


def hint_match(h, ev):
    texts = ' '.join(filter(None, [ev.get('message'), ev.get('reason'), ev.get('why'), ev.get('crash_reason')]))
    frames = (ev.get('frames') or []) + (ev.get('throw') or [])
    if 'kind' in h and h['kind'] != ev['kind']:
        return False
    if 'kinds' in h and ev['kind'] not in h['kinds']:
        return False
    if 'context' in h and not any(re.search(h['context'], c) for c in ev.get('context', [])):
        return False
    if 'proc' in h and not re.search(h['proc'], ev.get('label') or ev['proc']) and not re.search(h['proc'], ev['proc']):
        return False
    if 'loc' in h and (ev.get('culprit') or {}).get('loc') != h['loc'] and \
            not any(f.get('loc') == h['loc'] for f in frames[:1]):
        return False
    if 'any_loc' in h and not any(f.get('loc') == h['any_loc'] for f in frames):
        return False
    if 'sym' in h and not any(h['sym'] in (f.get('func') or '') for f in frames):
        return False
    if 'text' in h and not re.search(h['text'], texts):
        return False
    return True


def hint_for(sig):
    """Hints that match at least one event of the signature, with how many events they match."""
    out = []
    for h in HINTS:
        k = sum(1 for ev in sig['events'] if hint_match(h, ev))
        if k:
            out.append(dict(h, matched=k, of=len(sig['events'])))
    return out


def boot_label(b):
    if b.current_in:
        names = sorted({a for a, _ in b.current_in})
        return re.sub(r'^\d{8}-\d{6}-', '', names[0]) + (f' (+{len(names) - 1})' if len(names) > 1 else '')
    t = b.time()
    tag = 'android' if b.os == 'android' else 'residue'
    return f"{tag}@{t.strftime('%m-%d %H:%M') if t else '?'}"


def analyse(sources, sym):
    frags = []
    per_src = []
    for src, reader, when in sources:
        fs = split_fragments(src)
        frags += fs
        per_src.append((src, fs, reader, when))
    boots = build_boots(frags)
    owns = {}
    for src, fs, reader, when in per_src:
        owns[src.attempt] = mark_current(src, fs, reader, when)
    epoch = dt.datetime(1970, 1, 1)
    boots.sort(key=lambda b: (b.time() or epoch, b.idx))
    for n, b in enumerate(boots):
        b.id = f'B{n + 1:02d}'
        parse_events(b, sym)
    # signatures
    sigs = collections.OrderedDict()
    for b in boots:
        for ev in b.events:
            s = signature(ev)
            ev['sig'] = s
            g = sigs.setdefault(s, dict(sig=s, kind=ev['kind'], proc=ev['proc'], example=ev, events=[], boots=collections.OrderedDict()))
            g['events'].append(ev)
            g['boots'].setdefault(b.id, set()).add(ev.get('pid') or ev['ref'])
    order = [b.id for b in boots]
    byid = {b.id: b for b in boots}
    for g in sigs.values():
        ids = list(g['boots'])
        g['first'], g['last'] = ids[0], ids[-1]
        g['incidents'] = sum(len(v) for v in g['boots'].values())
        later = [byid[x] for x in order[order.index(g['last']) + 1:] if byid[x].os == 'xnu' and not byid[x].decayed]
        pfx = g['proc'][:16]
        ran = [b for b in later if any(p.startswith(pfx) or pfx.startswith(p[:16]) for p in b.procs if len(p) >= 4)] \
            if g['kind'] != 'panic' else later
        if g['kind'] == 'panic':
            ran = later
        if not later:
            g['status'] = 'open (latest boot)'
        elif not ran:
            g['status'] = f'not exercised since ({len(later)} later boots did not run {g["proc"]})'
        else:
            g['status'] = f'not seen since: {len(ran)} later boot(s) ran {g["proc"]} without it' + \
                          (' (likely fixed)' if len(ran) >= 2 and g['kind'] != 'panic' else '')
        g['ran_later'] = [b.id for b in ran]
        g['hints'] = hint_for(g)
    # a signature can vanish while the process keeps crashing another way: say so
    crashy = ('usertrap', 'userabort', 'crash', 'kill')
    for g in sigs.values():
        if g['kind'] not in crashy or not g.get('ran_later'):
            continue
        later = set(g['ran_later'])
        other = [h for h in sigs.values() if h is not g and h['kind'] in crashy and h['proc'][:16] == g['proc'][:16]
                 and later & set(h['boots'])]
        if other:
            g['also'] = [h['sig'] for h in other]
            g['status'] += f"; but {g['proc']} still fails later as " + ', '.join(h['sig'][:60] for h in other[:3])
    return boots, list(sigs.values()), per_src, owns


# --------------------------------------------------------------------------------------------------------------------------
# Output

BOOTARG_KEYS = ('cpus', 'blazer_deadline', 'hk_bright', 'rd', 'blazer_usbnet', 'blazer_wifi_net', 'hk_container_ready')


def boot_args(b):
    for _, _, l in b.lines():
        m = RX['bootargs'].search(l)
        if m:
            return m.group(1)
    return None


SCHEMA = 'crashdoc/1'
FRAME_KEYS = ('addr', 'unslid', 'loc', 'text', 'image', 'func', 'how', 'nearest')
EVENT_KEYS = ('kind', 'proc', 'pid', 'label', 'ref', 'ts', 'slide', 'main', 'exception', 'code', 'crash_reason', 'reason',
              'message', 'why', 'benign', 'linked', 'stall_ms', 'regs', 'guard', 'context')


def sig_id(sig):
    """Stable across runs and inputs: a hash of the signature string."""
    return hashlib.sha1(sig.encode()).hexdigest()[:10]


def frame_json(f):
    return {k: f.get(k) for k in FRAME_KEYS}


def event_json(ev):
    out = {k: ev.get(k) for k in EVENT_KEYS}
    out['boot'] = ev['boot'].id
    out['frames'] = [frame_json(f) for f in ev.get('frames') or []]
    out['throw'] = [frame_json(f) for f in ev.get('throw') or []]
    out['culprit'] = frame_json(ev['culprit']) if ev.get('culprit') else None
    return out


def is_crash(g):
    if g['kind'] == 'exit':
        # signal exits count unless every one is the exit of a crash already recorded (usertrap/userabort/CRASH)
        return not g['example']['benign'] and 'SIG' in g['example']['why'] and not g['example'].get('linked')
    return g['kind'] != 'panic' or not any(h['id'] == 'blazer-deadline' for h in g['hints'])


def to_json(boots, sigs, per_src, owns, sym):
    """Schema crashdoc/1 (documented in research/ios26-phaseb-r1/crashdoc/CRASHDOC.md). Keys are always present (null or
    empty when unknown); new keys may be added, existing ones keep their meaning."""
    jb = []
    for b in boots:
        ba = boot_args(b)
        t = b.time()
        jb.append(dict(id=b.id, label=boot_label(b), os=b.os, slide=f'{b.slide:#x}' if b.slide is not None else None,
                       nonce=b.nonce, current_in=sorted({a for a, _ in b.current_in}),
                       seen_in=sorted({f.src.attempt for f in b.frags}),
                       time=t.isoformat(sep=' ') if t else None,
                       fragments=[f.ref for f in b.frags], decayed=b.decayed,
                       boot_args={k: v for k, v in re.findall(r'(\w+)=(\S+)', ba or '') if k in BOOTARG_KEYS},
                       events=len(b.events)))
    js = []
    for n, g in enumerate(sigs):
        g['n'] = n
        g['id'] = sig_id(g['sig'])
        js.append(dict(id=g['id'], sig=g['sig'], kind=g['kind'], proc=g['proc'], crash=is_crash(g),
                       culprit=frame_json(g['example']['culprit']) if g['example'].get('culprit') else None,
                       incidents=g['incidents'], boots={k: len(v) for k, v in g['boots'].items()},
                       first=g['first'], last=g['last'], status=g['status'], also=g.get('also', []),
                       hints=[dict(id=h['id'], cause=h['cause'], ref=h['ref'], matched=h['matched'], of=h['of'])
                              for h in g['hints']],
                       example=event_json(g['example']), refs=sorted({e['ref'] for e in g['events']})[:12]))
    byboot = collections.defaultdict(list)
    for g in sigs:
        for bid, pids in g['boots'].items():
            byboot[bid].append((g, len(pids)))
    srcs = []
    for src, fs, reader, when in per_src:
        own = owns.get(src.attempt)
        bid = own.boot.id if own else None
        crashes = [dict(id=g['id'], sig=g['sig'], kind=g['kind'], proc=g['proc'], count=k, new=g['first'] == bid,
                        hints=[h['id'] for h in g['hints']])
                   for g, k in byboot.get(bid, []) if is_crash(g)]
        srcs.append(dict(attempt=src.attempt, path=str(src.path), sha256=src.sha256, nonce=reader.get('nonce'),
                         verdict=reader.get('verdict'), own_boot=bid,
                         boots=sorted({f.boot.id for f in fs if f.boot}), fragments=len(fs),
                         decayed_fragments=sum(1 for f in fs if f.decayed),
                         own_crashes=sorted(crashes, key=lambda c: -c['count'])))
    summary = dict(sources=len(per_src), boots=len(boots), signatures=len(sigs),
                   crash_signatures=sum(1 for g in sigs if is_crash(g)),
                   open=[g['id'] for g in sigs if is_crash(g) and g['status'].startswith('open')],
                   unexplained=[g['id'] for g in sigs if is_crash(g) and not g['hints']])
    return dict(schema=SCHEMA, tool='tools/crashdoc.py', cache=dict(path=sym.path, uuid=sym.uuid, error=sym.err),
                summary=summary, sources=srcs, boots=jb, signatures=js)


def md_table(rows, head):
    out = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    for r in rows:
        out.append('| ' + ' | '.join(str(x).replace('|', '\\|').replace('\n', ' ') for x in r) + ' |')
    return out


def where(g):
    ev = g['example']
    c = ev.get('culprit')
    if c:
        return f"`{c.get('loc') or c.get('addr')}` {c.get('text', '')}"
    return (ev.get('message') or ev.get('why') or '')[:90]


def to_md(doc, sigs, boots):
    byb = {b['id']: b for b in doc['boots']}
    L = ['# crashdoc: crash signatures by boot', '',
         f"Generated by `tools/crashdoc.py`. Dyld cache uuid `{(doc['cache']['uuid'] or 'none')[:8]}`"
         + (f" (symbols unavailable: {doc['cache']['error']})" if doc['cache']['error'] else '') + '. '
         'Evidence: phone ramdump / console text (PHYS); names are host symbolication of the dyld cache. '
         'Counts are distinct pids per boot after de-duplication of copies and residue.', '']
    crash = [g for g in sigs if is_crash(g)]
    L += ['## Signatures (crashes, aborts, stalls, watchdog kills, signal exits)', '']
    rows = []
    for g in sorted(crash, key=lambda g: (-g['incidents'], g['sig'])):
        per = ', '.join(f"{byb[k]['label']}×{len(v)}" for k, v in g['boots'].items())
        rows.append([f"S{g['n']:02d}", g['kind'], g['proc'], where(g), g['incidents'], per, byb[g['first']]['label'],
                     byb[g['last']]['label'], g['status'], '; '.join(h['id'] for h in g['hints']) or '-'])
    L += md_table(rows, ['sig', 'kind', 'process', 'culprit (unslid)', 'n', 'per boot', 'first', 'last', 'status', 'known cause'])
    L += ['', '## Known causes matched', '']
    for h in HINTS:
        m = [f"S{g['n']:02d}" + (f" ({k['matched']}/{k['of']})" if k['matched'] != k['of'] else '')
             for g in sigs for k in g['hints'] if k['id'] == h['id']]
        if m:
            L.append(f"- **{h['id']}** ({', '.join(m)}): {h['cause']} (`{h['ref']}`)")
    L += ['', '## Boots', '']
    rows = []
    for b in doc['boots']:
        if not b['events'] and (b['os'] != 'xnu' or not (b['slide'] or b['time'])):
            continue        # header stubs and binary residue: still in crashes.json
        rows.append([b['id'], b['label'], b['os'], b['slide'] or '-', b['nonce'] or '-', b['time'] or '-',
                     ' '.join(f'{k}={v}' for k, v in b['boot_args'].items()) or '-',
                     ', '.join(re.sub(r'^\d{8}-\d{6}-', '', s) for s in b['seen_in']), b['events'],
                     'decayed' if b['decayed'] else ''])
    L += md_table(rows, ['boot', 'label', 'os', 'dsc slide', 'nonce', 'launchd time (median)', 'boot-args', 'seen in dumps',
                         'events', ''])
    L += ['', '## Inputs', '']
    rows = [[s['attempt'], s['nonce'] or '-', s['verdict'] or '-', s['own_boot'] or '-', ' '.join(s['boots']),
             s['fragments'], s['decayed_fragments'] or ''] for s in doc['sources']]
    L += md_table(rows, ['attempt', 'TSHIMST2 nonce', 'verdict', 'own boot', 'boots in dump', 'fragments', 'decayed'])
    L += ['', '## Signature details', '']
    for g in sorted(crash, key=lambda g: g['n']):
        ev = g['example']
        L.append(f"### S{g['n']:02d} {g['kind']} {g['proc']}")
        L.append('')
        L.append(f"- id `{g['id']}`, signature `{g['sig']}`; {g['incidents']} incidents; status: {g['status']}")
        for k in ('exception', 'code', 'crash_reason', 'reason', 'message', 'why', 'stall_ms', 'guard', 'context', 'slide', 'main'):
            if ev.get(k) not in (None, '', {}):
                L.append(f'- {k}: `{ev[k]}`')
        if ev.get('regs'):
            L.append('- registers: ' + ', '.join(f'{k} -> {v}' for k, v in ev['regs'].items()))
        L.append(f"- example: `{ev['ref']}` (boot {ev['boot'].id} {byb[ev['boot'].id]['label']}); refs: "
                 + ', '.join(f'`{r}`' for r in sorted({e['ref'] for e in g['events']})[:6]))
        for h in g['hints']:
            L.append(f"- known cause **{h['id']}** (matches {h['matched']}/{h['of']} events): {h['cause']} (`{h['ref']}`)")
        for title, key in (('frames', 'frames'), ('first throw', 'throw')):
            if ev.get(key):
                L.append(f'- {title}:')
                L.append('')
                L.append('```')
                for k, f in enumerate(ev[key][:24]):
                    L.append(f"{k:>3} {f['addr']:>14} {f.get('unslid', ''):>13}  {f['text']}"
                             + (f"  (nearest {f['nearest']})" if f.get('nearest') else ''))
                L.append('```')
        L.append('')
    exits = [g for g in sigs if g['kind'] == 'exit' and not is_crash(g)]
    panics = [g for g in sigs if g['kind'] == 'panic' and not is_crash(g)]
    L += ['## Other launchd exits (exit codes, teardown kills)', '']
    rows = [[g['proc'], g['example']['why'], g['incidents'], len(g['boots']), g['status']]
            for g in sorted(exits, key=lambda g: -g['incidents'])]
    L += md_table(rows, ['label', 'why', 'n', 'boots', 'status'])
    L += ['', '## Intended panics (deadline)', '']
    rows = [[', '.join(byb[k]['label'] for k in g['boots']), g['example']['message'][:120]] for g in panics]
    L += md_table(rows, ['boots', 'message'])
    L.append('')
    return '\n'.join(L)


def run(paths, cache=DEFAULT_CACHE):
    """-> (doc, markdown). Library entry for hk_cycle / hk crash."""
    sources = []
    for log, attempt, d in collect(paths):
        meta = read_meta(d / 'meta.txt') if d else {}
        reader = read_reader(d / 'reader.txt') if d else {}
        markers = read_markers(d / 'markers.txt') if d else {}
        if markers.get('nonce') and not reader.get('nonce'):
            reader['nonce'] = markers['nonce']
        src = Source(log, attempt, meta)
        sources.append((src, reader, attempt_time(attempt, meta)))
    sym = Symbolizer(cache)
    try:
        boots, sigs, per_src, owns = analyse(sources, sym)
        doc = to_json(boots, sigs, per_src, owns, sym)
        md = to_md(doc, sigs, boots)
    finally:
        sym.close()
    return doc, md


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--out', help='directory for crashes.md and crashes.json (default: . unless --json)')
    ap.add_argument('--json', action='store_true', help='print crashes.json (schema crashdoc/1) on stdout')
    ap.add_argument('--cache', default=DEFAULT_CACHE)
    ap.add_argument('--no-symbols', action='store_true')
    ap.add_argument('--print', action='store_true', help='also print the signature table')
    a = ap.parse_args(argv)
    doc, md = run(a.paths, None if a.no_symbols else a.cache)
    text = json.dumps(doc, indent=1, default=str) + '\n'
    out = Path(a.out) if a.out else (None if a.json else Path('.'))
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
        (out / 'crashes.json').write_text(text)
        (out / 'crashes.md').write_text(md)
    if a.json:
        sys.stdout.write(text)
    else:
        sm = doc['summary']
        print(f"crashdoc: {sm['sources']} logs, {sm['boots']} boots, {sm['signatures']} signatures "
              f"({sm['crash_signatures']} crash-like, {len(sm['unexplained'])} without a known cause) -> {out}/crashes.md")
        if a.print:
            print(md.split('## Known causes')[0])
    return 0


if __name__ == '__main__':
    sys.exit(main())
