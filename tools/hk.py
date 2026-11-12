#!/usr/bin/env python3
"""hk: one CLI over the hackios debug tools, for people and for parallel LLM agents. Standard library only.

Every subcommand prints concise text, or one JSON document with --json (stable schemas: `hk schema`, and
research/ios26-phaseb-r1/hub/HUB.md). Progress of long steps goes to stderr; stdout carries only the result.

  phone + lease  hk state | hk to-fastboot | hk lock status|acquire NAME|check|renew|release NAME|break
  boot           hk boot IMAGE (= hk live, tools/live_boot.sh) | hk cycle IMAGE (tools/hk_cycle.py) | hk back
  while booted   hk ui SCRIPT | hk shot | hk shell CMD | hk push LOCAL REMOTE | hk restart DAEMON
  analysis       hk status | hk logs [PROC] | hk stacks PROC | hk crash | hk probe [ROW…] | hk report ATTEMPT | hk note ATTEMPT TEXT
                 hk timeline [ATTEMPT] | hk diff A [B] | hk triage [ATTEMPT] (-> attempts/<id>/TRIAGE.md)
                 (status/logs/stacks/crash/probe take --attempt ID or --path RUN_DIR; default the newest)
  catalogue      hk images | hk find | hk ingest | hk tools | hk schema
  shared phone   hk queue add|list|show|admit|cancel|run
  QEMU           hk qemu IMAGE_DIR [args for tools/qemu_preflight.py]

Phone rule: one holder of the device and usbcon at a time (lease file $HK_LOCKDIR/hk-phone.lease.json, default /tmp/fleet).
Anything that changes the phone or owns usbcon (boot, live, cycle, back, ui input, push, restart) REFUSES (exit 4,
lock_required) unless the caller names itself: --lock NAME or HK_LOCK=NAME (held by NAME: inherited; free: taken for the
command), or HK_LOCK_TOKEN (set for every child hk runs). `hk lock acquire NAME --ttl S` holds it across commands; an expired
lease (or a pid-bound one whose process died) is broken by the next acquire, with a note in hk-phone.events.jsonl.
Read-only work (status, logs, crash, stacks of a dump, probe, find, images, report, state, shot through the running reader)
needs no lease.

Exit codes: 0 ok; 1 ran, verdict FAIL; 2 usage; 3 a needed tool/input is not present (yet); 4 phone busy (lease held);
5 unsupported by the phone side (e.g. hk_shell lacks a builtin); 6 phone not in the needed state; 130 interrupted.

Environment (test doubles and overrides): HK_REPO (tools checkout), HK_STORE (attempt store, default the main checkout's
attempts/), HK_LOCKDIR (default /tmp/fleet), HK_PB (phone-bridge bin), HK_TOOL_<KEY> (path of a wrapped tool),
HK_ARGV_<KEY> (JSON argv template for a wrapped tool), HK_SHELL (mac | tcp:HOST:PORT), HK_SHELL_ADDR (192.168.77.2:2222),
HK_HOLDER (default holder name), HK_LOCK (holder name, = --lock), HK_LOCK_TOKEN (inherited lease), HK_NOW (epoch seconds, for tests).
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

sys.dont_write_bytecode = True

VERSION = 1
HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get('HK_REPO') or HERE.parent).resolve()
MAIN_CHECKOUT = Path(os.environ.get('HK_MAIN', '/srv/dev/repos/personal/hackios'))
RUNNER_ATTEMPTS = 'research/laguna-usb-fix/attempts'
CYCLES = 'research/hk-cycles'
IMAGES = 'research/images'


def store_dir():
    s = os.environ.get('HK_STORE')
    if s:
        return Path(s)
    base = MAIN_CHECKOUT if (MAIN_CHECKOUT / 'tools').is_dir() else REPO
    return base / 'attempts'


def lock_dir():
    return Path(os.environ.get('HK_LOCKDIR', '/tmp/fleet'))


def pb_dir():
    return Path(os.environ.get('HK_PB', str(Path.home() / '.local/share/phone-bridge/bin')))


def now():
    return float(os.environ.get('HK_NOW')) if os.environ.get('HK_NOW') else time.time()


def iso(t=None):
    return dt.datetime.fromtimestamp(now() if t is None else t).astimezone().isoformat(timespec='seconds')


# ------------------------------------------------------------------------------------------------------------- errors / output

class HkError(Exception):
    def __init__(self, code, error, message, **extra):
        super().__init__(message)
        self.code, self.error, self.message, self.extra = code, error, message, extra


def emit(args, schema, data, text, code=0):
    """One result. data: dict (JSON); text: list of lines or a string (text mode)."""
    if getattr(args, 'json', False):
        doc = {'schema': f'hk.{schema}/{VERSION}', 'ok': code == 0}
        doc.update(data)
        print(json.dumps(doc, indent=1, default=str, sort_keys=False))
    else:
        if isinstance(text, str):
            text = [text]
        for line in text:
            print(line)
    return code


def progress(msg):
    print(f'hk: {msg}', file=sys.stderr, flush=True)


# ------------------------------------------------------------------------------------------------------------- wrapped tools

# key: (repo-relative path, owner, what). Interfaces are documented in HUB.md section 4.
TOOLS = {
    'live_boot':   ('tools/live_boot.sh', 'DBG3', 'boot + live console + markers'),
    'bootios':     ('tools/bootios', 'runner', 'bare boot through run-attempt.sh'),
    'cycle':       ('tools/hk_cycle.py', 'HARNESS', 'one unattended cycle: preflight, boot, park, return, analysis'),
    'probe':       ('tools/probe_eval.py', 'VERIFY', 'README-row verdicts from docs/probes.yaml'),
    'crashdoc':    ('tools/crashdoc.py', 'CRASHDOC', 'crash census, signatures, causes -> crashes.json'),
    'qemu':        ('tools/qemu_preflight.py', 'QFARM', 'QEMU preflight of a phone image'),
    'ui_run':      ('tools/ui_run.py', 'UIDRV', 'UI script runner on a live boot'),
    'ui_settings': ('tools/ui_settings_test.py', 'DBG3', 'the fixed Settings walk'),
    'screenshot':  ('tools/screenshot.sh', 'DBG5', 'live usbcon snapshot / post-mortem HKSCR1'),
    'fb_png':      ('tools/fb_png.py', 'DBG5', 'HKSCR1 / RGB565 to PNG'),
    'hklog':       ('tools/hklog.py', 'OBS', 'console split per subsystem and HKL program'),
    'ustack_sym':  ('research/ios26-phaseb-r1/live/ustack/tools/ustack_sym.py', 'DBG4', 'hk_ustack symbolication'),
    'stamps':      ('tools/decode-shim-stamps.py', 'shim', 'TSHIMST stamps'),
    'read_ramdump': ('tools/read-ramdump.py', 'runner', 'raw dump reader'),
    'image_tool':  ('tools/image_tool.py', 'images', 'iOS image build/check'),
    'chooser_tool': ('tools/chooser_ios_image.py', 'dual boot', 'chooser image build/check'),
    'return_check': ('research/ios26-dualboot-r8/return-check.sh', 'dual boot', 'Android return check'),
    'backlog':     ('tools/backlog.py', 'BACKLOG', 'probe + crash census -> assignable backlog items'),
}
# Default argv templates for tools whose interface is still settling. {tool} expands to the interpreter + path.
ARGV = {
    'probe': ['{tool}', '{inputs}', '{row_args}', '{qemu_args}', '--json'],   # list values expand in place
    'ui_run': ['{tool}', '{run}', '{script}'],          # writes <run>/ui_run.json itself
    'crashdoc': ['{tool}', '{input}', '--out', '{out}'],
    'qemu': ['{tool}', '{image}', '--json', '{json}'],
}


TOOL_MISSING = 'tool not present'      # the error value of a missing wrapped tool (exit 3)


def tool_path(key):
    env = os.environ.get('HK_TOOL_' + key.upper())
    if env:
        return Path(env)
    rel, _, _ = TOOLS[key]
    p = REPO / rel
    if not p.exists() and (MAIN_CHECKOUT / rel).exists():
        p = MAIN_CHECKOUT / rel
    return p


def tool_cmd(key):
    p = tool_path(key)
    if not p.exists():
        rel, owner, what = TOOLS[key]
        raise HkError(3, TOOL_MISSING, f'{rel} is not present yet (owner {owner}: {what})',
                      tool=key, path=str(p), owner=owner, reason='tool_missing')
    if p.suffix == '.py':
        return [sys.executable, '-I', str(p)]
    if not os.access(p, os.X_OK):
        return ['bash', str(p)] if p.suffix == '.sh' or p.read_bytes()[:20].startswith(b'#!/usr/bin/env bash') or \
            p.read_bytes()[:12].startswith(b'#!/bin/bash') else ['sh', str(p)]
    return [str(p)]


def tool_argv(key, **subst):
    """argv from HK_ARGV_<KEY> (JSON list) or ARGV[key]; '{tool}' expands to tool_cmd(key)."""
    tmpl = ARGV[key]
    env = os.environ.get('HK_ARGV_' + key.upper())
    if env:
        tmpl = json.loads(env)
    out = []
    for item in tmpl:
        if item == '{tool}':
            out += tool_cmd(key)
        elif item.startswith('{') and item.endswith('}') and isinstance(subst.get(item[1:-1]), list):
            out += [str(x) for x in subst[item[1:-1]]]
        else:
            out.append(item.format(**subst))
    return out


def run(cmd, timeout=None, env=None, log=None, echo=False, input_bytes=None, cwd=None):
    """Run cmd in its own process group with stdin from /dev/null (never inherit stdin: ssh/mac children eat it).
    On timeout or Ctrl-C only that group is killed (never pkill: a pattern can match your own shell).
    Returns (rc, stdout text)."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    stdin = subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL
    p = subprocess.Popen(cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=full_env,
                         start_new_session=True, cwd=cwd)
    chunks = []
    fh = open(log, 'ab') if log else None

    def pump():
        for raw in iter(p.stdout.readline, b''):
            chunks.append(raw)
            if fh:
                fh.write(raw)
                fh.flush()
            if echo:
                sys.stderr.write(raw.decode(errors='replace'))
                sys.stderr.flush()

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    try:
        if input_bytes is not None:
            p.stdin.write(input_bytes)
            p.stdin.close()
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        killpg(p)
        t.join(5)
        if fh:
            fh.close()
        return 124, b''.join(chunks).decode(errors='replace')
    except KeyboardInterrupt:
        killpg(p, signal.SIGINT)
        raise
    t.join(10)
    if fh:
        fh.close()
    return p.returncode, b''.join(chunks).decode(errors='replace')


def killpg(p, sig=signal.SIGTERM):
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(p.pid, sig)
    with contextlib.suppress(Exception):
        p.wait(10)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(p.pid, signal.SIGKILL)


def pb(name):
    p = pb_dir() / name
    if not p.exists():
        raise HkError(3, TOOL_MISSING, f'phone-bridge {name} not found in {pb_dir()}', tool=name, path=str(p),
                      reason='tool_missing')
    return str(p)


# ------------------------------------------------------------------------------------------------------------- phone lease

LEASE = 'hk-phone.lease.json'
DEFAULT_TTL = 1800


def holder_name(args=None):
    h = getattr(args, 'holder', None) or os.environ.get('HK_HOLDER')
    return h or f"{os.environ.get('USER', 'user')}@{socket.gethostname()}:{os.getpid()}"


@contextlib.contextmanager
def lease_guard():
    d = lock_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / 'hk-phone.lease.lock', 'a+') as g:
        fcntl.flock(g, fcntl.LOCK_EX)
        try:
            yield d / LEASE
        finally:
            fcntl.flock(g, fcntl.LOCK_UN)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lease_read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def lease_state(lease):
    """free | held | expired | stale (pid-bound holder process gone on this host)."""
    if not lease or lease.get('released'):
        return 'free'
    if lease.get('expires', 0) <= now():
        return 'expired'
    if lease.get('pid_bound') and lease.get('host') == socket.gethostname() and not pid_alive(lease.get('pid', 0)):
        return 'stale'
    return 'held'


def lease_event(kind, lease, **extra):
    rec = dict(t=iso(), event=kind, holder=(lease or {}).get('holder'), purpose=(lease or {}).get('purpose'),
               attempt=(lease or {}).get('attempt'), **extra)
    with contextlib.suppress(OSError):
        with open(lock_dir() / 'hk-phone.events.jsonl', 'a') as f:
            f.write(json.dumps(rec) + '\n')


def public_lease(lease):
    if not lease:
        return None
    pub = {k: v for k, v in lease.items() if k != 'token'}
    pub['remaining_s'] = round(lease.get('expires', 0) - now(), 1)
    return pub


def lease_acquire(holder, purpose, ttl=DEFAULT_TTL, pid_bound=False, attempt=None, wait=0.0):
    deadline = time.monotonic() + wait
    while True:
        with lease_guard() as path:
            cur = lease_read(path)
            st = lease_state(cur)
            tok = os.environ.get('HK_LOCK_TOKEN')
            if st == 'held' and tok and cur.get('token') == tok:
                return cur, False                         # inherited: the caller already holds it
            if st != 'held':
                reclaimed = None
                if st in ('expired', 'stale'):
                    why = (f"expired {now() - cur.get('expires', 0):.0f} s ago" if st == 'expired' else
                           f"holder pid {cur.get('pid')} is gone on {cur.get('host')}")
                    reclaimed = dict(holder=cur.get('holder'), purpose=cur.get('purpose'), state=st, note=why, by=holder)
                    lease_event('reclaimed-' + st, cur, by=holder, note=why)
                    progress(f"broke the {st} phone lease of {cur.get('holder')} ({why}); logged in "
                             f"{lock_dir() / 'hk-phone.events.jsonl'}")
                lease = dict(schema=f'hk.lease/{VERSION}', holder=holder, purpose=purpose, token=uuid.uuid4().hex,
                             host=socket.gethostname(), pid=os.getpid(), pid_bound=pid_bound, acquired=now(),
                             acquired_iso=iso(), renewed=now(), expires=now() + ttl, ttl=ttl, attempt=attempt,
                             reclaimed_from=reclaimed)
                tmp = path.with_suffix('.tmp')
                tmp.write_text(json.dumps(lease, indent=1) + '\n')
                tmp.replace(path)
                lease_event('acquire', lease)
                return lease, True
        if time.monotonic() >= deadline:
            raise HkError(4, 'phone_busy', f"the phone lease is held by {cur.get('holder')} ({cur.get('purpose')}) for "
                          f"{cur.get('expires', 0) - now():.0f} s more", lease=public_lease(cur))
        time.sleep(min(5.0, max(0.1, deadline - time.monotonic())))


def lease_renew(token, ttl=None):
    with lease_guard() as path:
        cur = lease_read(path)
        if not cur or cur.get('token') != token or lease_state(cur) not in ('held', 'expired'):
            raise HkError(4, 'not_holder', 'this token does not hold the phone lease', lease=public_lease(cur))
        cur['renewed'] = now()
        cur['expires'] = now() + (ttl or cur.get('ttl', DEFAULT_TTL))
        path.write_text(json.dumps(cur, indent=1) + '\n')
        return cur


def lease_release(token, note=''):
    with lease_guard() as path:
        cur = lease_read(path)
        if not cur or cur.get('token') != token:
            raise HkError(4, 'not_holder', 'this token does not hold the phone lease', lease=public_lease(cur))
        cur['released'] = now()
        path.write_text(json.dumps(cur, indent=1) + '\n')
        lease_event('release', cur, note=note)
        return cur


def caller_lock_name(args=None):
    """The lease holder name the caller claims: --lock NAME or HK_LOCK."""
    return getattr(args, 'lock', None) or os.environ.get('HK_LOCK') or None


def lock_cmd_name(args):
    """hk lock NAME: the positional, else --lock, --holder, HK_LOCK, HK_HOLDER."""
    return (args.name or getattr(args, 'lock', None) or getattr(args, 'holder', None) or os.environ.get('HK_LOCK') or
            os.environ.get('HK_HOLDER') or None)


def caller_holds(args=None):
    """(lease, how) if the caller holds the live lease (by HK_LOCK_TOKEN or by --lock/HK_LOCK name), else (lease, None)."""
    with lease_guard() as path:
        cur = lease_read(path)
    if lease_state(cur) != 'held':
        return cur, None
    tok, name = os.environ.get('HK_LOCK_TOKEN'), caller_lock_name(args)
    if tok and cur.get('token') == tok:
        return cur, 'token'
    if name and cur.get('holder') == name:
        return cur, 'name'
    return cur, None


@contextlib.contextmanager
def phone_lease(args, purpose, ttl=DEFAULT_TTL, attempt=None):
    """Hold the phone lease for a with-block. Device commands refuse unless the caller names itself: it already holds the
    lease (HK_LOCK_TOKEN, or --lock NAME / HK_LOCK equal to the holder: inherited, not released here), or it passes
    --lock NAME / HK_LOCK and the phone is free (taken pid-bound under NAME for the block, renewed every ttl/3)."""
    cur, how = caller_holds(args)
    name = caller_lock_name(args)
    if how:
        lease, mine = cur, False
    elif not name and not getattr(args, 'lock_auto', False):
        st = lease_state(cur)
        raise HkError(4, 'lock_required', 'this command touches the phone: hold the phone lease first (hk lock acquire '
                      'NAME, then --lock NAME or HK_LOCK=NAME, or HK_LOCK_TOKEN)' +
                      (f"; it is held by {cur.get('holder')} ({cur.get('purpose')})" if st == 'held' else ''),
                      lease=public_lease(cur) if st == 'held' else None)
    else:
        lease, mine = lease_acquire(name or holder_name(args), purpose, ttl=ttl, pid_bound=True, attempt=attempt,
                                    wait=float(getattr(args, 'lock_wait', 0) or 0))
    stop = threading.Event()
    if mine:
        def renew():
            while not stop.wait(max(5.0, ttl / 3)):
                with contextlib.suppress(HkError):
                    lease_renew(lease['token'], ttl)
        threading.Thread(target=renew, daemon=True).start()
    old = os.environ.get('HK_LOCK_TOKEN')
    os.environ['HK_LOCK_TOKEN'] = lease['token']
    try:
        yield lease
    finally:
        stop.set()
        if old is None:
            os.environ.pop('HK_LOCK_TOKEN', None)
        else:
            os.environ['HK_LOCK_TOKEN'] = old
        if mine:
            with contextlib.suppress(HkError):
                lease_release(lease['token'], note=purpose)


def cmd_lock(args):
    a = args.lock_cmd
    if a == 'status':
        with lease_guard() as path:
            cur = lease_read(path)
        st = lease_state(cur)
        data = dict(state=st, lease=public_lease(cur) if st != 'free' else None)
        txt = f'phone lease: {st}' + (f" — {cur['holder']} ({cur.get('purpose')}), {cur['expires'] - now():.0f} s left"
                                      if st == 'held' else '')
        return emit(args, 'lock', data, txt)
    if a == 'acquire':
        holder = lock_cmd_name(args) or holder_name(args)
        cur, how = caller_holds(argparse.Namespace(lock=holder))
        if how == 'name':                                  # the same name again: the caller already holds it
            lease, mine = cur, False
        else:
            lease, mine = lease_acquire(holder, args.purpose or 'manual', ttl=args.ttl, wait=args.wait)
        data = dict(state='held', token=lease['token'], lease=public_lease(lease), inherited=not mine,
                    reclaimed_from=lease.get('reclaimed_from'))
        return emit(args, 'lock', data, [f"{'acquired' if mine else 'already held'} by {lease['holder']} "
                                         f"({lease.get('expires', 0) - now():.0f} s left)",
                                         f"export HK_LOCK={lease['holder']}   # or HK_LOCK_TOKEN={lease['token']}"])
    if a == 'check':
        name = lock_cmd_name(args)
        cur, how = caller_holds(argparse.Namespace(lock=name))
        st = lease_state(cur)
        data = dict(state=st, holds=bool(how), by=how, lease=public_lease(cur) if st != 'free' else None)
        if how:
            return emit(args, 'lock', data, f"you hold the phone lease ({cur['holder']}, by {how})")
        raise HkError(4, 'lock_required' if st != 'held' else 'not_holder',
                      'the caller does not hold the phone lease' + (f" (held by {cur.get('holder')})" if st == 'held' else
                                                                     f' (it is {st})'), **data)
    tok = args.token or os.environ.get('HK_LOCK_TOKEN')
    if a in ('renew', 'release') and not tok:
        name = lock_cmd_name(args)
        cur, how = caller_holds(argparse.Namespace(lock=name)) if name else (None, None)
        if how:
            tok = cur['token']
        else:
            raise HkError(4 if name else 2, 'not_holder' if name else 'usage',
                          f'hk lock {a}: ' + (f"{name} does not hold the phone lease" if name else
                                              f'needs the holder NAME (hk lock {a} NAME, HK_LOCK) or --token / HK_LOCK_TOKEN'),
                          lease=public_lease(cur) if lease_state(cur) == 'held' else None)
    if a == 'renew':
        lease = lease_renew(tok, args.ttl)
        return emit(args, 'lock', dict(state='held', lease=public_lease(lease)), f"renewed, {args.ttl} s")
    if a == 'release':
        lease = lease_release(tok, note=args.purpose or '')
        return emit(args, 'lock', dict(state='free', lease=public_lease(lease)), 'released')
    if a == 'break':
        with lease_guard() as path:
            cur = lease_read(path)
            st = lease_state(cur)
            if st == 'held' and not args.force:
                raise HkError(4, 'phone_busy', f"held by {cur['holder']}, {cur['expires'] - now():.0f} s left; "
                              'break needs --force and a --reason', lease=public_lease(cur))
            if not args.reason:
                raise HkError(2, 'usage', 'hk lock break needs --reason')
            if cur:
                cur['released'] = now()
                cur['broken'] = dict(by=holder_name(args), reason=args.reason, state=st)
                path.write_text(json.dumps(cur, indent=1) + '\n')
            lease_event('break', cur, by=holder_name(args), reason=args.reason, was=st)
        return emit(args, 'lock', dict(state='free', broken=st), f'lease broken (was {st})')
    raise HkError(2, 'usage', 'hk lock status|acquire|check|renew|release|break')


# ------------------------------------------------------------------------------------------------------------- index + attempts

FEATURE_NAME_RULES = [
    ('chooser', r'chooser'), ('wifi', r'wifi|bcmdhd'), ('bt', r'bluetooth|-b\d-|btsk|-bt\d'), ('net', r'usbnet|netstack|-net\b|cfg\d'),
    ('shell', r'shell|dbg2|live-r'), ('display', r'bright|-bl\b|backlight|display|dpu'), ('gpu', r'gpu'),
    ('input', r'touch|keys|uidrive|-ui\b|pwr'), ('screen', r'screen|dbg5'), ('ustack', r'ustack|dbg4'), ('obs', r'obs\d|logmirror'),
    ('apps', r'apps|persona|usersession|registration'), ('storage', r'persist|ios-data|flash|ufs|gpt'), ('power', r'pwr|batt|power'),
    ('cpu', r'cpu|dvfs|gov'), ('perf', r'perf|fast-start|accel'), ('settings', r'settings|configd|cfg'),
    ('compositor', r'backboardd|compositor|container|cc\d|flatmat'), ('security', r'aks|amfi|sep'), ('audio', r'audio|aud\d'),
    ('sensors', r'sens'), ('integration', r'\bint\d|-int\d'), ('dualboot', r'chooser|return|boot_b|install'),
    ('charger', r'chg\d|charg'), ('modem', r'modem|cellular|gnss|s5400'), ('usbhost', r'usbhost|otg|dpalt|-dp\d'),
    ('camera', r'cam\d|camera|torch'),  # research/ios26-camera-r1
    ('nfc', r'nfc'),  # research/ios26-nfc-r1
]
FEATURE_TOKEN_RULES = [
    ('wifi', r'^blazer_wifi'), ('bt', r'^blazer_bt'), ('net', r'^blazer_(usbnet|netstack|net)'), ('screen', r'^(hk_screen|blazer_usbcon_snap)'),
    ('ustack', r'^hk_ustack'), ('input', r'^(blazer_usbcon_input|blazer_touch|hk_ui)'), ('display', r'^(hk_bright|hk_fb|sweetfb)'),
    ('gpu', r'^blazer_gpu'), ('storage', r'^(blazer_persist|blazer_ufs_fake)'), ('security', r'^blazer_aks'), ('audio', r'^blazer_audio'),
    ('sensors', r'^blazer_sensors'), ('perf', r'^hk_top'), ('apps', r'^blazer_persona'), ('usb', r'^blazer_usbcon'),
    ('charger', r'^blazer_battery_chg'), ('modem', r'^blazer_modem'), ('usbhost', r'^blazer_(usbhost|dp)'),
    ('camera', r'^blazer_(torch|cam)'),  # research/ios26-camera-r1
    ('nfc', r'^blazer_nfc'),  # research/ios26-nfc-r1
]
SUBSYSTEMS = sorted({f for f, _ in FEATURE_NAME_RULES} | {f for f, _ in FEATURE_TOKEN_RULES} | {'shim', 'xnu', 'qemu'})


def features_of(name, cmdline=''):
    out = set()
    low = (name or '').lower()
    for f, rx in FEATURE_NAME_RULES:
        if re.search(rx, low):
            out.add(f)
    for tok in (cmdline or '').split():
        key = tok.split('=', 1)[0]
        for f, rx in FEATURE_TOKEN_RULES:
            if re.search(rx, key):
                out.add(f)
    return sorted(out)


def index_path():
    return store_dir() / 'index.jsonl'


def ensure_store():
    s = store_dir()
    s.mkdir(parents=True, exist_ok=True)
    gi = s / '.gitignore'
    if not gi.exists():
        gi.write_text('# hk attempt store: device dumps and console logs, never for git\n*\n')
    return s


def index_append(rec):
    ensure_store()
    with open(index_path(), 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(json.dumps(rec, sort_keys=True, default=str) + '\n')
        fcntl.flock(f, fcntl.LOCK_UN)


def index_load():
    """Last record per id wins (the index is append-only)."""
    recs = {}
    try:
        with open(index_path()) as f:
            for line in f:
                with contextlib.suppress(ValueError):
                    r = json.loads(line)
                    if 'id' in r:
                        recs[r['id']] = r
    except OSError:
        pass
    return sorted(recs.values(), key=lambda r: (r.get('created_t', 0), r['id']))


def safe_name(s):
    return re.sub(r'[^A-Za-z0-9._-]', '-', s)[:80] or 'attempt'


def attempt_dir(aid):
    return store_dir() / aid


def manifest_path(aid):
    return attempt_dir(aid) / 'manifest.json'


def load_manifest(aid):
    try:
        return json.loads(manifest_path(aid).read_text())
    except (OSError, ValueError):
        raise HkError(3, 'no_attempt', f'no attempt {aid} in {store_dir()}', attempt=aid)


def git_rev(path):
    rc, out = run(['git', '-C', str(path), '--no-optional-locks', 'rev-parse', 'HEAD'], timeout=10)
    rev = out.strip() if rc == 0 else None
    rc, out = run(['git', '-C', str(path), '--no-optional-locks', 'status', '--porcelain', '-uno'], timeout=20)
    return dict(rev=rev, dirty_tracked=len(out.splitlines()) if rc == 0 else None)


def resolve_image(arg):
    """IMAGE (dir, boot.img, or bare name under research/images) -> (dir, boot.img, manifest dict)."""
    p = Path(arg)
    cands = [p, REPO / IMAGES / arg, MAIN_CHECKOUT / IMAGES / arg]
    for c in cands:
        if c.is_file() and c.name.endswith('.img'):
            d = c.parent
            break
        if c.is_dir():
            d = c
            break
    else:
        raise HkError(3, 'no_image', f'image not found: {arg}', image=arg)
    d = d.resolve()
    boot = d / 'boot.img' if (d / 'boot.img').exists() else (p if p.is_file() else d / 'boot.img')
    man = {}
    with contextlib.suppress(OSError, ValueError):
        man = json.loads((d / 'manifest.json').read_text())
    return d, boot, man


def image_summary(d, man):
    ios = man.get('ios') if isinstance(man.get('ios'), dict) else {}
    cmd = man.get('cmdline') or ios.get('cmdline') or ''
    dl = re.search(r'\bblazer_deadline=(\d+)', cmd)
    ov = man.get('var_overlay') if isinstance(man.get('var_overlay'), dict) else {}
    return dict(name=man.get('name') or d.name, dir=str(d), sha256=man.get('image'), kernel_sha256=man.get('mach'),
                kind=man.get('kind') or ('chooser' if d.name.startswith('chooser') else 'ios'),
                bootable=man.get('bootable'), installable=man.get('installable'), cmdline=cmd, cpus=man.get('cpus'),
                deadline=int(dl.group(1)) if dl else None, overlay=ov.get('path'), overlay_sha256=ov.get('sha256'),
                features=features_of(man.get('name') or d.name, cmd))


def new_attempt(name, kind, argv, image=None, mach=None, queue_id=None, extra=None):
    ensure_store()
    ts = dt.datetime.fromtimestamp(now()).strftime('%Y%m%d-%H%M%S')
    aid = f'{ts}-{safe_name(name)}'
    n = 1
    while attempt_dir(aid).exists():
        n += 1
        aid = f'{ts}-{safe_name(name)}-{n}'
    d = attempt_dir(aid)
    for sub in ('screens', 'probes', 'crashes', 'logs'):
        (d / sub).mkdir(parents=True, exist_ok=True)
    m = dict(schema=f'hk.manifest/{VERSION}', id=aid, name=name, kind=kind, created=iso(), created_t=now(),
             created_by=holder_name(), agent=os.environ.get('HK_AGENT'), command=argv, queue_id=queue_id,
             image=image, kernel=dict(mach=str(mach) if mach else None, sha256=(image or {}).get('kernel_sha256')),
             cmdline=(image or {}).get('cmdline'), features=(image or {}).get('features', []),
             git=dict(m1box=git_rev(REPO)), owner_actions=[], paths={}, result={})
    if extra:
        m.update(extra)
    write_manifest(m)
    return m


def write_manifest(m):
    m['updated'] = iso()
    p = manifest_path(m['id'])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(m, indent=1, default=str) + '\n')
    tmp.replace(p)
    index_append(index_record(m))


def index_record(m):
    r = m.get('result') or {}
    img = m.get('image') or {}
    return dict(schema=f'hk.index/{VERSION}', id=m['id'], name=m.get('name'), kind=m.get('kind'), created=m.get('created'),
                created_t=m.get('created_t'), image=img.get('name'), image_sha256=img.get('sha256'),
                kernel_sha256=(m.get('kernel') or {}).get('sha256'), features=m.get('features') or [],
                verdict=r.get('verdict'), rc=r.get('rc'), end=r.get('end'), reader=r.get('reader'), crashes=r.get('crash_signatures'),
                return_check=r.get('return_check'), ui=r.get('ui'), queue_id=m.get('queue_id'),
                dir=str(attempt_dir(m['id'])), paths=m.get('paths') or {})


def rel_link(target, link):
    """A symlink attempts/<id>/<name> -> target (relative when possible)."""
    target = Path(target)
    with contextlib.suppress(FileExistsError, OSError):
        if link.is_symlink() or link.exists():
            return
        try:
            link.symlink_to(os.path.relpath(target, link.parent))
        except ValueError:
            link.symlink_to(target)


def latest_attempt(kind=None):
    recs = [r for r in index_load() if not kind or r.get('kind') == kind]
    if not recs:
        raise HkError(3, 'no_attempt', f'no attempts in {index_path()} (hk ingest --all imports the old runs)')
    return recs[-1]['id']


def attempt_of(args):
    """--attempt ID, or --path DIR (a runner, live_boot, hk_cycle or QEMU run dir: imported, idempotent), or the latest."""
    path = getattr(args, 'path', None)
    if path:
        if not Path(path).exists():
            raise HkError(3, 'no_path', f'{path} does not exist', path=str(path))
        return ingest_one(path)[0]
    return getattr(args, 'attempt', None) or latest_attempt()


def runner_dir(m):
    p = (m.get('paths') or {}).get('runner')
    return Path(p) if p else None


def kernel_log(m):
    for key in ('ramdump',):
        p = (m.get('paths') or {}).get(key)
        if p and Path(p).is_file():
            return Path(p)
    r = runner_dir(m)
    if r and (r / 'ramdump/kernel.log').is_file():
        return r / 'ramdump/kernel.log'
    c = (m.get('paths') or {}).get('cycle')
    if c:
        for k in Path(c).glob('**/ramdump/kernel.log'):
            return k
    return None


def console_log(m):
    p = (m.get('paths') or {}).get('live') or discover_live(m)
    if p and (Path(p) / 'console.txt').is_file():
        return Path(p) / 'console.txt'
    return None


def discover_live(m):
    """The live_boot run dir inside attempts/<id>/ (hk boot points LIVE_ATTEMPTS there). hk boot records paths.live only
    when live_boot returns, so while the boot runs (or after the boot command was killed) the manifest has none."""
    d = attempt_dir(m['id'])
    cands = [p.parent for p in d.glob('live-*/live.env')]
    if (d / 'live' / 'live.env').is_file():
        cands.append((d / 'live').resolve())
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def runner_of_live(live):
    """The runner dir a live_boot run used: live.env ATTEMPT=, else its ATTEMPT_DIR marker (a Mac path), mapped to m1box."""
    live = Path(live)
    rp = map_runner_path(read_kv(live / 'live.env', '=').get('ATTEMPT', ''))
    if rp:
        return rp
    for mk in read_markers(live / 'markers.txt'):
        if mk['name'] == 'ATTEMPT_DIR':
            rp = map_runner_path(mk['detail'])
            if rp:
                return rp
    return None


def crash_src(m):
    """What crashdoc reads for an attempt: the runner dir when it holds the ramdump (reader.txt/meta.txt add the nonce),
    else the ramdump file, else the live console (a boot still running, or a live run whose runner dir has no dump)."""
    k = kernel_log(m)
    r = runner_dir(m)
    if k and r and str(k).startswith(str(r) + '/'):
        return r
    return k or console_log(m) or r


def map_runner_path(text):
    """A Mac path the runner printed (…/research/laguna-usb-fix/attempts/X) -> the m1box copy."""
    if not text or text.startswith('none'):
        return None
    base = Path(text.strip()).name
    for root in (REPO, MAIN_CHECKOUT):
        cand = root / RUNNER_ATTEMPTS / base
        if cand.is_dir():
            return cand
    p = Path(text.strip())
    return p if p.is_dir() else None


def read_kv(path, sep=':'):
    out = {}
    with contextlib.suppress(OSError):
        for line in Path(path).read_text(errors='replace').splitlines():
            if sep in line and not line.startswith(' '):
                k, v = line.split(sep, 1)
                out[k.strip()] = v.strip()
    return out


MARKER_RE = re.compile(r'^LIVEBOOT (\S+) \+(\S+) (\S+) ?(.*)$')


def read_markers(path):
    out = []
    with contextlib.suppress(OSError):
        for line in Path(path).read_text(errors='replace').splitlines():
            m = MARKER_RE.match(line)
            if m:
                out.append(dict(wall=m[1], s=float(m[2]) if m[2].replace('.', '', 1).isdigit() else None, name=m[3],
                                detail=m[4]))
    return out


END_RE = re.compile(rb'panic\(cpu \d+ caller 0x[0-9a-f]+\): (blazer-root: deadline (\d+) s[^\n\x00]{0,120}|[^\n\x00]{0,160})')


def dump_end(klog):
    """How the newest boot in a ramdump ended: deadline N / panic text / None. The ring holds residue of older boots, so
    the first panic line in file order is taken (hklog and crashdoc split boots precisely; this is a quick look)."""
    try:
        data = Path(klog).read_bytes()
    except OSError:
        return None
    m = END_RE.search(data)
    if not m:
        return None
    if m.group(2):
        return dict(kind='deadline', seconds=int(m.group(2)), line=m.group(1).decode(errors='replace')[:200])
    line = m.group(1).decode(errors='replace')[:200]
    # usbcon reset op (hk to-fastboot, hk_cycle --end-*): the host ended this boot on purpose, not a crash
    return dict(kind='host-end' if 'the host asked to end this boot' in line else 'panic', line=line)


def finalize_from_paths(m):
    """Fill result/paths from what the runner, live_boot and hk_cycle left."""
    paths, r = m.setdefault('paths', {}), m.setdefault('result', {})
    d = attempt_dir(m['id'])
    if not paths.get('live') and m.get('kind', 'phone') == 'phone':
        live = discover_live(m)
        if live:
            paths['live'] = str(live)
    if paths.get('live') and not paths.get('runner'):
        rp = runner_of_live(paths['live'])
        if rp:
            paths['runner'] = str(rp)
    if paths.get('runner'):
        rd = Path(paths['runner'])
        rel_link(rd, d / 'runner')
        if (rd / 'ramdump/kernel.log').is_file():
            paths['ramdump'] = str(rd / 'ramdump/kernel.log')
            rel_link(rd / 'ramdump', d / 'ramdump')
        pt = read_kv(rd / 'park-timeline.txt')
        if pt:
            r['park'] = {k: pt[k] for k in ('mode', 'ep0_to_park_s', 'boot_to_park_wall_s', 'capture_rc') if k in pt}
        with contextlib.suppress(OSError):
            v = re.search(r'^VERDICT: (\S+)', (rd / 'reader.txt').read_text(errors='replace'), re.M)
            if v:
                r['reader'] = v.group(1)
        meta = read_kv(rd / 'meta.txt')
        if meta.get('image_sha256'):
            r['booted_image_sha256'] = meta['image_sha256']
    if paths.get('live'):
        ld = Path(paths['live'])
        rel_link(ld / 'console.txt', d / 'console.txt')
        mk = read_markers(ld / 'markers.txt')
        r['markers'] = sorted({x['name'] for x in mk})
        for x in mk:
            if x['name'] == 'BOOT_RC':
                with contextlib.suppress(ValueError):
                    r['rc'] = int(x['detail'].split()[0])
        for f in ('ui_test.json', 'ui_run.json'):
            with contextlib.suppress(OSError, ValueError):
                r['ui'] = json.loads((ld / f).read_text()).get('verdict')
    if paths.get('cycle'):
        cd = Path(paths['cycle'])
        for f in ('summary.json', 'report.json'):
            with contextlib.suppress(OSError, ValueError):
                rep = json.loads((cd / f).read_text())
                r['verdict'] = rep.get('verdict', r.get('verdict'))
                ret = rep.get('return') or {}
                r['return_check'] = rep.get('return_check_verdict') or (ret.get('check') or {}).get('verdict') or r.get('return_check')
                if isinstance(rep.get('ui'), dict):
                    r['ui'] = rep['ui'].get('verdict', r.get('ui'))
                for k in ('attempt', 'attempt_dir'):
                    if rep.get(k) and not paths.get('runner'):
                        mp = map_runner_path(str(rep[k]))
                        if mp:
                            paths['runner'] = str(mp)
                break
    k = kernel_log(m)
    if k:
        r['end'] = dump_end(k)
    rc = d / 'return' / 'return-check.json'
    with contextlib.suppress(OSError, ValueError):
        r['return_check'] = json.loads(rc.read_text()).get('verdict')
    cj = d / 'crashes' / 'crashes.json'
    if cj.is_file():
        r['crash_signatures'] = crash_brief(cj)[:20]
    return m


def cmd_note(args):
    m = finalize_from_paths(load_manifest(args.attempt))
    m.setdefault('owner_actions', []).append(dict(t=iso(), by=holder_name(args), text=' '.join(args.text)))
    write_manifest(m)
    return emit(args, 'note', dict(attempt=m['id'], owner_actions=m['owner_actions']), f"noted on {m['id']}")


# ------------------------------------------------------------------------------------------------------------- state

def phone_probe(timeout=25):
    """android | recovery | android-unauthorized | fastboot | ios | usb-google | off-or-unknown (hk_cycle's order)."""
    detail = {}
    try:
        rc, out = run([pb('fastboot'), 'devices'], timeout=timeout)
        detail['fastboot'] = out.strip()[:300]
        if rc == 0 and any(re.search(r'\sfastboot\s*$', l) for l in out.splitlines()):
            return 'fastboot', detail
        rc, out = run([pb('adb'), 'devices'], timeout=timeout)
        detail['adb'] = out.strip()[:300]
        for l in out.splitlines():
            parts = l.split()
            if len(parts) >= 2 and parts[0] != 'List':
                if parts[1] == 'device':
                    return 'android', detail
                if parts[1] in ('recovery', 'sideload', 'rescue'):
                    return 'recovery', detail
                if parts[1] in ('unauthorized', 'offline'):
                    return 'android-' + parts[1], detail
        rc, out = run([pb('mac'), 'usb'], timeout=timeout)
        detail['usb'] = ' '.join(re.findall(r'\b(?:1209|18d1):[0-9a-f]{4}\b', out))
        if re.search(r'\b1209:000[23]\b', out):
            return 'ios', detail
        if re.search(r'\b1209:0001\b', out):
            return 'shim', detail
        if re.search(r'\b18d1:', out):
            return 'usb-google', detail
        return 'off-or-unknown', detail
    except HkError as e:
        detail['error'] = e.message
        return 'unknown', detail


# hk state's one-word answer, from phone_probe's finer one, with how it knows.
STATES = ('android', 'fastboot', 'ios-live', 'shim', 'recovery', 'absent')


def phone_class(phone, detail):
    """(state, how): one of STATES (or unknown / skipped when the bridge could not be asked) and the evidence."""
    usb = detail.get('usb') or ''
    if phone == 'fastboot':
        return 'fastboot', '`fastboot devices` lists it'
    if phone == 'android':
        return 'android', '`adb devices` lists it as device'
    if phone.startswith('android-'):
        return 'android', f"`adb devices` lists it as {phone.split('-', 1)[1]} (accept the USB-debugging prompt on the phone)"
    if phone == 'usb-google':
        return 'android', f'no adb or fastboot answer, but a Google USB id on the Mac ({usb}): Android or the bootloader is starting'
    if phone == 'recovery':
        return 'recovery', '`adb devices` lists it in recovery/sideload/rescue'
    if phone == 'ios':
        return 'ios-live', f'the usbcon gadget is on the Mac\'s USB ({usb}): an iOS kernel is running'
    if phone == 'shim':
        return 'shim', f"the shim's own gadget 1209:0001 is on the Mac's USB ({usb})"
    if phone == 'off-or-unknown':
        return 'absent', 'no adb, no fastboot and no 1209:/18d1: id on the Mac\'s USB: off, hung without USB, or the cable'
    if phone == 'skipped':
        return 'skipped', '--no-phone'
    return 'unknown', detail.get('error') or 'the phone bridge could not be asked'


LIVE_STALE_S = float(os.environ.get('HK_LIVE_STALE_S', 180))


def active_live_run():
    """The newest live_boot run whose boot has not ended (live.env without BOOT_RC)."""
    cands = []
    for root in {store_dir(), REPO / RUNNER_ATTEMPTS, MAIN_CHECKOUT / RUNNER_ATTEMPTS}:
        cands += list(root.glob('live-*/live.env')) + list(root.glob('*/live-*/live.env'))
    for env in sorted(cands, key=lambda p: p.stat().st_mtime, reverse=True):
        kv = read_kv(env, '=')
        con = env.parent / 'console.txt'
        fresh = con.is_file() and time.time() - con.stat().st_mtime < LIVE_STALE_S
        if 'BOOT_RC' not in kv and fresh:
            return env.parent, kv
    return None, {}


def installed_record():
    try:
        return json.loads((store_dir() / 'installed.json').read_text())
    except (OSError, ValueError):
        return None


def cmd_state(args):
    phone, detail = ('skipped', {}) if args.no_phone else phone_probe()
    shell = None
    if phone == 'ios' and not args.no_phone:
        try:
            shell = shell_run('pwd', timeout=8)['exit'] is not None
        except HkError:
            shell = False
    with lease_guard() as path:
        lease = lease_read(path)
    live, kv = active_live_run()
    recent = index_load()[-args.last:]
    state, how = phone_class(phone, detail)
    data = dict(state=state, how=how, phone=phone, phone_detail=detail, ios_shell=shell, lease=dict(state=lease_state(lease),
                lease=public_lease(lease) if lease_state(lease) == 'held' else None),
                installed_boot_b=installed_record(), live_run=str(live) if live else None,
                live_sock=kv.get('LIVE_SOCK'), recent=[dict(id=r['id'], verdict=r.get('verdict'), end=r.get('end'),
                                                             features=r.get('features')) for r in recent],
                queue=queue_counts())
    ib = installed_record() or {}
    txt = [f'{state}  ({how})', f'phone: {phone}' + (f" (ios shell {'up' if shell else 'down'})" if shell is not None else ''),
           f"lease: {data['lease']['state']}" + (f" by {lease['holder']} ({lease.get('purpose')})" if data['lease']['lease'] else ''),
           f"boot_b (recorded, not read from the phone): {ib.get('image', '?')} readback {ib.get('readback', '?')} ({ib.get('when', '?')})",
           f'live run: {live or "none"}', f"queue: {data['queue']}"]
    txt += [f"  {r['id']}  {r.get('verdict') or '-'}  {(r.get('end') or {}).get('kind', '')}" for r in recent]
    return emit(args, 'state', data, txt)


def cmd_installed(args):
    rec = dict(image=args.image, readback=args.readback, when=args.when or iso(), by=holder_name(args), source=args.source)
    ensure_store()
    (store_dir() / 'installed.json').write_text(json.dumps(rec, indent=1) + '\n')
    return emit(args, 'installed', rec, f"recorded boot_b = {args.image} ({args.readback})")


# ------------------------------------------------------------------------------------------------------------- to-fastboot
# Owner rule: end a boot the moment its evidence is in and boot the next image, from any phone state. docs/DEBUG-LOOP.md.

TO_FB_POLL_S = float(os.environ.get('HK_TO_FB_POLL_S', 3.0))
COLD_RESET = ('Owner: hold power + volume-down until the bootloader (fastboot) screen shows (about 10-20 s). WARNING: that is a '
              'COLD reset: RAM is wiped, so the ramdump of whatever was running is lost. Use it only when nothing answers.')


def wait_state(want, bound, steps):
    """Poll until phone_class is in want; returns the last state."""
    end = time.monotonic() + bound
    while True:
        phone, detail = phone_probe()
        state, how = phone_class(phone, detail)
        if state in want or time.monotonic() >= end:
            steps.append(dict(step='wait', want=sorted(want), state=state, how=how))
            return state
        time.sleep(TO_FB_POLL_S)


def usbcon_reply(out):
    with contextlib.suppress(ValueError):
        if '{' in out:
            return json.loads(out[out.find('{'):out.rfind('}') + 1])
    return {}


def mac_usbcon(kv=None, steps=None):
    """The usbcon.py to run on the Mac: the live run's own (LIVE_TOOLS in live.env), else m1box's current tools placed by
    tools/mactools.py (hash-verified, outside the Mac checkout). Only if that cannot be done, the Mac checkout's
    tools/usbcon.py, which `mac repo` refuses to run when it differs from m1box's."""
    tools = (kv or {}).get('LIVE_TOOLS')
    if not tools:
        try:
            spec = importlib.util.spec_from_file_location('mactools', Path(__file__).resolve().parent / 'mactools.py')
            mt = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mt)
            tools = mt.ensure(pb('mac'))['dir']
        except Exception as e:      # MacToolsError, a missing file: say so and use the checkout's copy
            if steps is not None:
                steps.append(dict(step='mactools', error=str(e)[:300], fallback='tools/usbcon.py of the Mac checkout'))
    return f'{tools}/tools/usbcon.py' if tools else 'tools/usbcon.py'


def reset_ios(steps):
    """End the running iOS boot by the usbcon reset op: through the running reader's socket, else a short-lived reader.
    Returns how (socket|reader). Raises HkError when the kernel refuses (blazer_usbcon=1) or the answer is unclear."""
    live, kv = active_live_run()
    sock = kv.get('LIVE_SOCK')
    if sock:
        rc, out = run([pb('mac'), 'repo', '--force', '--', 'python3', '-I', mac_usbcon(kv, steps), '--control-socket', sock,
                       '--reset-now'], timeout=90, cwd=str(REPO))
        r = usbcon_reply(out)
        steps.append(dict(step='reset op', via=sock, live_run=str(live), rc=rc, reply=r or out.strip()[-300:]))
        if r.get('state') == 'reset':
            return 'socket'
        if r.get('state') == 'refused':
            raise HkError(6, 'reset_not_armed', f"the reader refused the reset: {r.get('error')}. This boot ends at its deadline; "
                          'or, losing its ramdump: ' + COLD_RESET, steps=steps)
        gone = re.search(r'Errno (2|61|111)\b|No such file|Connection refused', str(r.get('error', '')) + out)
        if not gone:
            raise HkError(6, 'reset_unknown', f"reset op answer unclear (rc {rc}): {r.get('error') or out.strip()[-200:]}; "
                          'not repeated: run hk state in a minute', steps=steps)
        progress(f'the reader of {live} is gone ({sock}); starting a short-lived one')
    py = os.environ.get('USBCON_PY', '/tmp/tegu-venv/bin/python')
    rc, out = run([pb('mac'), 'repo', '--force', '--', py, '-u', mac_usbcon(None, steps), '--quiet', '--timeout', '45',
                   '--gone-exit', '5', '--stats', '3600', '--reset-after', '0'], timeout=120, cwd=str(REPO))
    steps.append(dict(step='short-lived reader --reset-after 0', rc=rc, out=out.strip()[-400:]))
    if 'reset accepted' in out:
        return 'reader'
    if 'another usbcon reader owns USB' in out:
        raise HkError(4, 'reader_busy', 'another usbcon reader owns the phone\'s USB but no live run names its socket; '
                      'find its live.env (LIVE_SOCK) and run tools/usbcon.py --control-socket SOCK --reset-now', steps=steps)
    if re.search(r'reset failed .*(Errno 32|[Pp]ipe)', out):
        raise HkError(6, 'reset_not_armed', 'the kernel stalled the reset request: this boot runs blazer_usbcon=1. It ends at '
                      'its deadline; or, losing its ramdump: ' + COLD_RESET, steps=steps)
    raise HkError(6, 'reset_unknown', f'the short-lived reader did not report an accepted reset (rc {rc}): '
                  f"{(out.strip().splitlines() or ['no output'])[-1][:200]}; not repeated", steps=steps)


def cmd_to_fastboot(args):
    """Bring the phone to fastboot from whatever it is doing, the fast way that keeps RAM where there is one."""
    phone, detail = phone_probe()
    start, how = phone_class(phone, detail)
    steps = [dict(step='state', state=start, how=how)]
    data = dict(start=start, how=how, steps=steps, ramdump_kept=None)
    if start == 'fastboot':
        return emit(args, 'to-fastboot', dict(data, state='fastboot', action='none'), f'fastboot already ({how})')
    if start == 'unknown':
        raise HkError(3, 'bridge_down', f'cannot tell the phone state: {how}', **data)
    if start == 'absent':
        raise HkError(6, 'owner_action', f'the phone is absent ({how}). {COLD_RESET}', **data)
    if start == 'recovery':
        raise HkError(6, 'owner_action', 'the phone is in recovery: the owner picks "Reboot to bootloader" on it (never factory '
                      'reset)', **data)
    if start == 'shim':
        raise HkError(6, 'transient', "the shim's gadget is up: within seconds it hands to XNU (ios-live) or chain-loads "
                      'Android; run hk to-fastboot again in 10-30 s', **data)
    with phone_lease(args, 'to-fastboot', ttl=int(args.wait) + 300):
        action = []
        state = start
        if state == 'ios-live':
            via = reset_ios(steps)
            action.append(f'usbcon reset op ({via})')
            data['ramdump_kept'] = True
            state = wait_state({'fastboot', 'android'}, args.wait, steps)
            if state == 'android':
                data['ramdump_kept'] = False
                progress('the boot ended but came back in Android: force-fastboot was off, so no park and no ramdump; '
                         'going on to fastboot')
        if state == 'android':
            rc, out = run([pb('adb'), 'reboot', 'bootloader'], timeout=60)
            steps.append(dict(step='adb reboot bootloader', rc=rc, out=out.strip()[-200:]))
            action.append('adb reboot bootloader')
            state = wait_state({'fastboot'}, args.wait, steps)
    data.update(state=state, action=' then '.join(action))
    if state != 'fastboot':
        raise HkError(6, 'not_fastboot', f"after {data['action']} the phone is {state}, not fastboot", **data)
    txt = [f"{start} -> fastboot by {data['action']}"]
    if data['ramdump_kept']:
        txt.append('the boot parked with RAM intact: pull the ramdump (capture-fastboot) before booting the next image')
    return emit(args, 'to-fastboot', data, txt)


# ------------------------------------------------------------------------------------------------------------- boot / cycle / back

# ------------------------------------------------------------------------------------------------------------- boot post-hooks
# Owner rule: every boot gets a screenshot, a probe and a diagnosis. hk boot / hk cycle run AutoBoot beside the boot:
# a picture at UI_READY (attempts/<id>/screens/ui-ready.png), one every --shot-every s, and hk triage when the boot ends.

AUTO_POLL_S = float(os.environ.get('HK_AUTO_POLL_S', 2.0))
AUTO_RETRY_S = float(os.environ.get('HK_AUTO_RETRY_S', 15.0))
AUTO_FIRST_S = float(os.environ.get('HK_AUTO_FIRST_S', 30.0))   # first periodic picture after the console connects (hk_cycle's shot_start)
END_MARKERS = {'BOOT_RC', 'CONSOLE_GONE', 'PARKED', 'PANIC', 'DEADLINE'}
SHOT_BUSY = re.compile(r'busy|expired|in flight|deadline|not ?ready|timed? ?out', re.I)


def cmdline_tokens(cmdline):
    out = {}
    for tok in (cmdline or '').split():
        k, _, v = tok.partition('=')
        out[k] = v
    return out


def boot_gates(cmdline):
    """What a command line lets the host do live: usbcon console, snapshots (blazer_usbcon_snap=1 or hk_dbg bit 1), live
    input (blazer_usbcon_input=1 or hk_dbg bit 0), and the ramdump's HKSCR1 period (hk_screen= or hk_dbg bits 8..15)."""
    t = cmdline_tokens(cmdline)
    dbg = 0
    with contextlib.suppress(ValueError):
        dbg = int(t.get('hk_dbg') or '0', 0)
    console = t.get('blazer_usbcon') in ('1', '2')
    screen = 0
    with contextlib.suppress(ValueError):
        screen = int(t.get('hk_screen') or '0', 0)
    return dict(console=console, snap=console and (t.get('blazer_usbcon_snap') == '1' or bool(dbg & 0x02)),
                input=console and (t.get('blazer_usbcon_input') == '1' or bool(dbg & 0x01)),
                screen=screen or (dbg >> 8 & 0xff))


def ui_run_active(markers_path):
    """A UI script owns the snapshot path between UIRUN START and its END/STOP (its own pictures pace it)."""
    active = False
    with contextlib.suppress(OSError):
        for line in Path(markers_path).read_text(errors='replace').splitlines():
            g = TAGGED_RE.match(line)
            if g and g.group(1) == 'UIRUN':
                if g.group(4) == 'START':
                    active = True
                elif g.group(4) in ('END', 'STOP'):
                    active = False
    return active


class AutoBoot(threading.Thread):
    """Beside a running boot: find its live run, take the UI_READY picture and the periodic ones. Never raises; every
    picture (or why there was none) goes to attempts/<id>/screens/auto.jsonl."""

    def __init__(self, aid, gates, every=120.0, step=8, shots=True, find_live=None, started=None):
        super().__init__(name='hk-auto', daemon=True)
        self.aid, self.gates, self.every, self.step, self.shots = aid, gates, every, step, shots
        self.find_live = find_live
        self.started = time.time() if started is None else started
        self.stop_ev = threading.Event()
        self.records, self.live, self.notes = [], None, []
        self.screens = attempt_dir(aid) / 'screens'

    def note(self, text):
        self.notes.append(text)
        progress(f'hk auto: {text}')

    def locate(self):
        if self.live is None and self.find_live:
            with contextlib.suppress(Exception):
                self.live = self.find_live()
        return self.live

    def shot(self, name, out):
        """One live picture through tools/screenshot.sh. One retry when the reader was busy (a UI step's own picture)."""
        rec = dict(name=name, t=round(time.time() - self.started, 1), png=None)
        for attempt in (1, 2):
            try:
                rc, o = run(tool_cmd('screenshot') + [str(self.live), '--name', safe_name(name)[:24], '--step', str(self.step),
                                                      '-o', str(out)], timeout=90)
            except HkError as e:
                rec.update(rc=e.code, error=e.message)
                break
            rec.update(rc=rc, out=o.strip()[-200:])
            if rc == 0 and out.is_file():
                rec['png'] = str(out)
                break
            if attempt == 1 and SHOT_BUSY.search(o or '') and not self.stop_ev.wait(AUTO_RETRY_S):
                continue
            break
        rec['ok'] = bool(rec['png'])
        self.records.append(rec)
        with contextlib.suppress(OSError):
            self.screens.mkdir(parents=True, exist_ok=True)
            with open(self.screens / 'auto.jsonl', 'a') as f:
                f.write(json.dumps(rec) + '\n')
        self.note(f"{name}: {rec['png'] or 'no picture (rc %s) %s' % (rec.get('rc'), (rec.get('out') or rec.get('error') or '')[-120:])}")
        return rec

    def run(self):
        try:
            self.loop()
        except Exception as e:          # a picture never takes the boot down
            self.note(f'stopped: {e!r}')

    def loop(self):
        if not self.shots:
            return
        if not self.gates.get('snap'):
            self.note('no live pictures: the image has no blazer_usbcon_snap=1 (or hk_dbg bit 1); the dump picture follows the boot'
                      if self.gates.get('screen') else 'no live pictures: no blazer_usbcon_snap=1 and no hk_screen in this image')
            return
        ui_done, next_at, n = False, None, 0
        while not self.stop_ev.wait(AUTO_POLL_S):
            live = self.locate()
            if not live:
                continue
            marks = {m['name']: m for m in read_markers(Path(live) / 'markers.txt')}
            if END_MARKERS & set(marks):
                return
            if next_at is None and ('CONSOLE_CONNECTED' in marks or 'DISPLAY' in marks):
                next_at = time.time() + AUTO_FIRST_S
            if not ui_done and 'UI_READY' in marks:
                ui_done = True
                self.shot('ui-ready', self.screens / 'ui-ready.png')
                if next_at is not None:
                    next_at = max(next_at, time.time() + (self.every or 0))
                continue
            if self.every and next_at is not None and time.time() >= next_at:
                next_at = time.time() + self.every
                if ui_run_active(Path(live) / 'markers.txt'):
                    continue
                n += 1
                t0 = read_kv(Path(live) / 'live.env', '=').get('LIVE_T0')
                rel = int(time.time() - float(t0)) if t0 and t0.replace('.', '', 1).isdigit() else int(time.time() - self.started)
                self.shot(f'auto-{n:03d}', self.screens / f'auto-{n:03d}-t{rel:04d}.png')

    def finish(self, m):
        """After the boot: stop, take the dump picture when nothing live was saved, then triage. Returns the summary."""
        self.stop_ev.set()
        self.join(timeout=120)
        out = dict(shots=self.records, notes=self.notes)
        if self.shots and not any(r['ok'] for r in self.records) and self.gates.get('screen') and kernel_log(m):
            src = runner_dir(m) or kernel_log(m).parent.parent
            png = self.screens / 'dump.png'
            with contextlib.suppress(HkError):
                rc, o = run(tool_cmd('screenshot') + ['--dump', str(src), '-o', str(png)], timeout=120)
                out['dump_shot'] = dict(rc=rc, png=str(png) if rc == 0 and png.is_file() else None, out=o.strip()[-200:])
        return out


def auto_enabled(args):
    return not getattr(args, 'no_auto', False) and os.environ.get('HK_AUTO', '1') != '0'


def start_auto(args, m, find_live, every):
    if not auto_enabled(args):
        return None
    gates = boot_gates((m.get('image') or {}).get('cmdline') or m.get('cmdline') or '')
    a = AutoBoot(m['id'], gates, every=every, step=getattr(args, 'shot_step', 8), shots=not getattr(args, 'no_shots', False),
                 find_live=find_live)
    a.start()
    return a


def finish_auto(args, auto, m):
    """Stop the picture thread and run triage on what the boot left. Errors are reported, never raised."""
    if auto is None:
        return None
    out = auto.finish(m)
    if not getattr(args, 'no_triage', False):
        progress(f"hk auto: triage {m['id']}")
        try:
            data, _, errors = triage_attempt(m['id'])
            out['triage'] = dict(md=data['triage_md'], prev=data['prev'], errors=[e['message'] for e in errors])
        except HkError as e:
            out['triage'] = dict(md=None, errors=[e.message])
        except Exception as e:                   # noqa: BLE001 - a broken analysis must not lose the boot's result
            out['triage'] = dict(md=None, errors=[f'triage failed: {e!r}'])
    with contextlib.suppress(OSError):
        (attempt_dir(m['id']) / 'auto.json').write_text(json.dumps(out, indent=1) + '\n')
    return out


def auto_lines(auto):
    if not auto:
        return []
    ok = [r['png'] for r in auto['shots'] if r['ok']]
    L = [f"pictures: {len(ok)} of {len(auto['shots'])}" + (f" (first {ok[0]})" if ok else '')]
    L += [f'auto: {n}' for n in auto['notes'] if n.startswith('no live')]
    if auto.get('dump_shot'):
        L.append(f"dump picture: {auto['dump_shot']['png'] or 'none'}")
    t = auto.get('triage')
    if t:
        L.append(f"triage: {t['md'] or 'failed'}" + (f" ({len(t['errors'])} errors)" if t['errors'] else ''))
    return L


def add_auto_args(q, every):
    g = q.add_argument_group('post-hooks (owner rule: every boot gets a picture, a probe and a diagnosis)')
    g.add_argument('--no-auto', action='store_true', help='no pictures and no triage (also HK_AUTO=0)')
    g.add_argument('--no-shots', action='store_true', help='no live pictures from hk (triage still runs)')
    g.add_argument('--no-triage', action='store_true', help='no hk triage at the end')
    g.add_argument('--shot-every', type=float, default=every, help=f'seconds between periodic pictures (0: UI_READY only; default {every:g})')
    g.add_argument('--shot-step', type=int, default=8, help='snapshot step (every Nth pixel; default 8 = 160x357, ~10 s)')


def boot_ttl(args, extra=900):
    return int(getattr(args, 'wait', 0) or 1200) + extra


def cmd_boot(args):
    d, boot, man = resolve_image(args.image)
    img = image_summary(d, man)
    name = args.name or img['name']
    lb = tool_cmd('live_boot')
    if not args.mach:
        progress('warning: no --mach; panic symbols come from the runner default (wrong for current builds)')
    with phone_lease(args, f"boot {name}", ttl=boot_ttl(args)) as lease:
        m = new_attempt(name, 'phone', sys.argv, image=img, mach=args.mach, queue_id=getattr(args, 'queue_id', None),
                        extra=dict(lease_holder=lease['holder']))
        ad = attempt_dir(m['id'])
        argv = lb + [str(boot), safe_name(name)]
        if args.mach:
            argv += ['--mach', args.mach]
        argv += ['--wait', str(args.wait)]
        argv += ['--sync-tools'] if args.sync_tools else []
        argv += ['--no-console'] if args.no_console else []
        argv += ['--ui-test'] if args.ui_test else []
        m['command'] = argv
        write_manifest(m)
        progress(f"attempt {m['id']}: {' '.join(shlex.quote(a) for a in argv)}")
        auto = start_auto(args, m, lambda: discover_live(m), getattr(args, 'shot_every', 120))
        try:
            rc, out = run(argv, env=dict(LIVE_ATTEMPTS=str(ad)), log=ad / 'hk-boot.log', echo=not args.json)
        finally:
            if auto:
                auto.stop_ev.set()
    live = re.findall(r'^live_boot: run (\S+)', out, re.M)
    att = re.findall(r'^live_boot: attempt (\S+)', out, re.M) or re.findall(r'^attempt: (\S+)', out, re.M)
    if live:
        m['paths']['live'] = live[-1]
        rel_link(live[-1], ad / 'live')
    if att:
        rp = map_runner_path(att[-1])
        if rp:
            m['paths']['runner'] = str(rp)
    m['result']['rc'] = rc
    finalize_from_paths(m)
    m['result'].setdefault('verdict', 'BOOTED' if rc == 0 else 'BOOT_FAILED')
    write_manifest(m)
    post = finish_auto(args, auto, m)
    return emit(args, 'boot', dict(attempt=m['id'], dir=str(ad), rc=rc, result=m['result'], paths=m['paths'], auto=post),
                [f"attempt {m['id']} rc {rc}", f"dir {ad}", f"markers: {' '.join(m['result'].get('markers', []))}",
                 f"end: {m['result'].get('end')}"] + auto_lines(post) +
                ['next: hk back (return to Android + check), hk crash, hk report'],
                0 if rc == 0 else 1)


def cmd_cycle(args):
    d, boot, man = resolve_image(args.image)
    img = image_summary(d, man)
    name = args.name or img['name']
    cyc = tool_cmd('cycle')
    with phone_lease(args, f'cycle {name}', ttl=boot_ttl(args, 2400)) as lease:
        m = new_attempt(name, 'phone', sys.argv, image=img, mach=args.mach, queue_id=getattr(args, 'queue_id', None),
                        extra=dict(lease_holder=lease['holder']))
        ad = attempt_dir(m['id'])
        out_dir = ad / 'cycle'
        argv = cyc + ['--image', str(d), '--name', safe_name(name), '--out', str(out_dir)]
        for opt in ('mach', 'ui', 'expect'):
            if getattr(args, opt, None):
                argv += ['--' + opt, getattr(args, opt)]
        if args.deadline_wait:
            argv += ['--deadline-wait', str(args.deadline_wait)]
        for opt in ('end_on', 'end_grace', 'end_after', 'end_on_idle'):
            if getattr(args, opt, None) is not None:
                argv += ['--' + opt.replace('_', '-'), str(getattr(args, opt))]
        argv += list(args.extra or [])
        m['command'] = argv
        m['paths']['cycle'] = str(out_dir)
        write_manifest(m)
        progress(f"attempt {m['id']}: {' '.join(shlex.quote(a) for a in argv)}")
        started = time.time()
        # hk_cycle takes its own periodic pictures (--shot-every there); hk adds the UI_READY one.
        auto = start_auto(args, m, lambda: discover_live(m) or cycle_live(out_dir, started), 0)
        try:
            rc, out = run(argv, log=ad / 'hk-cycle.log', echo=not args.json)
        finally:
            if auto:
                auto.stop_ev.set()
    for pat, key in ((r'live run (\S+)', 'live'), (r'attempt dir: (\S+)', 'runner'), (r'^attempt: (\S+)', 'runner')):
        for hit in re.findall(pat, out, re.M)[-1:]:
            if key == 'runner':
                rp = map_runner_path(hit)
                if rp:
                    m['paths']['runner'] = str(rp)
            elif Path(hit).is_dir():
                m['paths']['live'] = hit
    m['result']['rc'] = rc
    finalize_from_paths(m)
    m['result'].setdefault('verdict', {0: 'PASS', 1: 'FAIL', 3: 'REFUSED', 5: 'PHONE_NOT_IN_ANDROID'}.get(rc, f'rc {rc}'))
    write_manifest(m)
    post = finish_auto(args, auto, m) if rc != 3 else None        # a refused cycle booted nothing
    return emit(args, 'cycle', dict(attempt=m['id'], dir=str(ad), rc=rc, result=m['result'], paths=m['paths'], auto=post),
                [f"attempt {m['id']} verdict {m['result'].get('verdict')} (hk_cycle rc {rc})",
                 f"report {out_dir / 'report.md'}"] + auto_lines(post), 0 if rc == 0 else 1)


def cycle_live(out_dir, started):
    """hk_cycle's live run: the one its log names, else the newest live run that started after the cycle did."""
    with contextlib.suppress(OSError):
        for hit in reversed(re.findall(r'live run (\S+)', Path(out_dir, 'cycle.log').read_text(errors='replace'))):
            if Path(hit).is_dir():
                return Path(hit)
    live, _ = active_live_run()
    if live and (Path(live) / 'live.env').stat().st_mtime >= started - 5:
        return Path(live)
    return None


def cmd_back(args):
    """Return to Android: force-fastboot off + fastboot reboot (the installed chooser times out to Android), then the
    read-only return check into attempts/<id>/return/."""
    aid = attempt_of(args)
    m = finalize_from_paths(load_manifest(aid))       # a killed hk boot left paths={}: don't write that back over the index
    out = attempt_dir(aid) / 'return'
    steps = []
    with phone_lease(args, f'back {aid}', ttl=1200, attempt=aid):
        st, _ = phone_probe()
        steps.append(dict(step='state', state=st))
        if st == 'fastboot':
            for cmd in (['oem', 'force-fastboot', 'off'], ['reboot']):
                rc, o = run([pb('fastboot')] + cmd, timeout=60)
                steps.append(dict(step='fastboot ' + ' '.join(cmd), rc=rc, out=o.strip()[-300:]))
                if rc != 0:
                    raise HkError(6, 'fastboot_failed', f"fastboot {' '.join(cmd)} rc {rc}", steps=steps)
        elif st not in ('android', 'usb-google', 'off-or-unknown'):
            raise HkError(6, 'wrong_state', f'phone is {st}; hk back runs from fastboot (park) or Android. An iOS boot '
                          'ends at its own deadline: never cold-reset it (RAM, and so the ramdump, is lost)', steps=steps)
        rc, o = run(tool_cmd('return_check') + [str(out)], timeout=900, log=attempt_dir(aid) / 'hk-back.log')
        steps.append(dict(step='return-check', rc=rc))
    verdict = None
    with contextlib.suppress(OSError, ValueError):
        verdict = json.loads((out / 'return-check.json').read_text()).get('verdict')
    m['result']['return_check'] = verdict or f'rc {rc}'
    write_manifest(m)
    ok = bool(verdict) and verdict.startswith('PASS')
    return emit(args, 'back', dict(attempt=aid, verdict=verdict, steps=steps, dir=str(out)),
                [f'return check: {verdict}', f'{out}'], 0 if ok else 1)


# ------------------------------------------------------------------------------------------------------------- live: ui / shot

def need_live(args):
    run_dir = getattr(args, 'run', None)
    if run_dir:
        kv = read_kv(Path(run_dir) / 'live.env', '=')
        return Path(run_dir), kv
    live, kv = active_live_run()
    if not live:
        raise HkError(6, 'no_live_run', 'no live boot is running (start one with hk boot / hk cycle)')
    return live, kv


def attempt_for_live(live):
    for r in reversed(index_load()):
        if (r.get('paths') or {}).get('live') == str(live) or str(live).startswith(r.get('dir', '\0') + '/'):
            return r['id']
    return None


def cmd_ui(args):
    if args.check:
        rc, o = run(tool_cmd('ui_run') + ['--check', args.run or '.', args.script], timeout=60)
        return emit(args, 'ui', dict(check=True, rc=rc, out=o.strip()[-2000:]), o.strip().splitlines() or [f'rc {rc}'],
                    0 if rc == 0 else 1)
    live, kv = need_live(args)
    aid = attempt_for_live(live)
    out = (attempt_dir(aid) if aid else live) / 'ui'
    out.mkdir(parents=True, exist_ok=True)
    jpath = out / f"ui-{time.strftime('%H%M%S')}.json"
    if args.script == 'settings':
        argv = tool_cmd('ui_settings') + [str(live)]
    else:
        argv = tool_argv('ui_run', run=str(live), script=args.script, json=str(jpath), out=str(out))
    with phone_lease(args, f'ui {args.script}', ttl=1800, attempt=aid):
        rc, o = run(argv, log=out / 'hk-ui.log', echo=not args.json, env=dict(LIVE_RUN=str(live), HK_ATTEMPT=aid or ''))
    doc = None
    for p in (jpath, live / 'ui_run.json', live / 'ui_test.json'):
        with contextlib.suppress(OSError, ValueError):
            doc = json.loads(p.read_text())
            break
    verdict = (doc or {}).get('verdict')
    if aid:
        m = load_manifest(aid)
        m['result']['ui'] = verdict
        write_manifest(m)
    return emit(args, 'ui', dict(attempt=aid, live_run=str(live), rc=rc, verdict=verdict, report=doc),
                f'ui {args.script}: {verdict} (rc {rc})', 0 if rc == 0 else 1)


def cmd_shot(args):
    aid = None
    if args.dump or args.attempt:
        aid = attempt_of(args)
        m = load_manifest(aid)
        src = runner_dir(m) or (kernel_log(m).parent.parent if kernel_log(m) else None)
        if not src:
            raise HkError(3, 'no_dump', f'{aid} has no ramdump')
        outp = Path(args.output) if args.output else attempt_dir(aid) / 'screens' / 'dump.png'
        outp.parent.mkdir(parents=True, exist_ok=True)
        argv = tool_cmd('screenshot') + ['--dump', str(src), '-o', str(outp)] + (['--allow-stale'] if args.allow_stale else [])
        mode = 'dump'
    else:
        live, _ = need_live(args)
        aid = attempt_for_live(live)
        name = safe_name(args.name or 'shot')
        outp = Path(args.output) if args.output else \
            (attempt_dir(aid) if aid else live) / 'screens' / f"{name}-{time.strftime('%H%M%S')}.png"
        outp.parent.mkdir(parents=True, exist_ok=True)
        argv = tool_cmd('screenshot') + [str(live), '--name', name, '--step', str(args.step), '-o', str(outp)]
        mode = 'live'
    rc, o = run(argv, timeout=180)
    ok = rc == 0 and outp.is_file()
    return emit(args, 'shot', dict(attempt=aid, mode=mode, png=str(outp) if ok else None, rc=rc, out=o.strip()[-400:]),
                str(outp) if ok else f'no picture (rc {rc}): {o.strip()[-200:]}', 0 if ok else (3 if rc == 3 else 1))


# ------------------------------------------------------------------------------------------------------------- logs / stacks

HKL_RE = re.compile(r'HKL ([^\[\]\s/]{1,32})\[(\d+)\] (.*)$')
LIVE_STAMP = re.compile(r'^(\d\d:\d\d:\d\d\.\d{3}) (.*)$')


def split_logs(m, src):
    """hklog's per-subsystem split of src into attempts/<id>/logs/<src-kind>/ (cached by source size+mtime)."""
    kind = 'live' if src.name == 'console.txt' else 'dump'
    out = attempt_dir(m['id']) / 'logs' / kind
    stamp = out / '.hk-source'
    key = f'{src} {src.stat().st_size} {int(src.stat().st_mtime)}'
    if stamp.is_file() and stamp.read_text() == key and (out / 'all.log').is_file():
        return out
    try:
        argv = tool_cmd('hklog') + [str(src), '-o', str(out)]
    except HkError:
        return None
    if out.exists():
        shutil.rmtree(out)
    rc, _ = run(argv, timeout=300)
    if rc != 0 or not (out / 'all.log').is_file():
        return None
    stamp.write_text(key)
    return out


def raw_lines(src):
    data = src.read_bytes()
    return [s.decode(errors='replace') for s in re.findall(rb'[\x20-\x7e\t]{6,}', data)]


def cmd_logs(args):
    if args.live:
        live, _ = need_live(args)
        src = live / 'console.txt'
        m = None
        aid = attempt_for_live(live)
        if aid:
            m = load_manifest(aid)
    else:
        aid = attempt_of(args)
        m = load_manifest(aid)
        src = console_log(m) if args.source == 'live' else (kernel_log(m) or console_log(m))
    if not src or not src.is_file():
        raise HkError(3, 'no_log', f'{aid}: no console or ramdump log')
    split = split_logs(m, src) if (m and not args.live) else None
    if split and args.proc and (split / 'hkl' / f'{args.proc}.log').is_file():
        lines, used = (split / 'hkl' / f'{args.proc}.log').read_text(errors='replace').splitlines(), f'hkl/{args.proc}.log'
    elif split and args.sub:
        f = split / f'{args.sub}.log'
        if not f.is_file():
            raise HkError(3, 'no_subsystem', f'no {args.sub}.log (have: {", ".join(sorted(p.stem for p in split.glob("*.log")))})')
        lines, used = f.read_text(errors='replace').splitlines(), f'{args.sub}.log'
    elif split:
        lines, used = (split / 'all.log').read_text(errors='replace').splitlines(), 'all.log'
    else:
        lines = raw_lines(src) if src.name != 'console.txt' else src.read_text(errors='replace').splitlines()
        used = 'raw'
    if args.proc and used != f'hkl/{args.proc}.log':
        rx = re.compile(rf'(HKL {re.escape(args.proc)}\[|\b{re.escape(args.proc)}\[\d+|\({re.escape(args.proc)}\)|com\.apple\.{re.escape(args.proc)}\b)')
        lines = [l for l in lines if rx.search(l)]
    if args.grep:
        rx = re.compile(args.grep)
        lines = [l for l in lines if rx.search(l)]
    total = len(lines)
    lines = lines[-args.tail:] if args.tail else lines
    return emit(args, 'logs', dict(attempt=aid, source=str(src), split=str(split) if split else None, file=used, total=total,
                                   lines=lines), lines or [f'(no lines; source {src}, {used})'])


def cmd_stacks(args):
    if args.live:
        res = shell_run(args.live_cmd.format(proc=args.proc), timeout=120)
        return emit(args, 'stacks', dict(mode='live', proc=args.proc, **res), res['stdout'].splitlines(),
                    0 if res['exit'] == 0 else 1)
    aid = attempt_of(args)
    m = load_manifest(aid)
    src = kernel_log(m) or console_log(m)
    if not src:
        raise HkError(3, 'no_log', f'{aid}: no log with HK USTACK lines')
    argv = tool_cmd('ustack_sym') + [str(src), '--proc', args.proc] + ([] if args.full else ['--summary'])
    rc, out = run(argv, timeout=600)
    lines = out.splitlines()
    (attempt_dir(aid) / 'logs').mkdir(exist_ok=True)
    (attempt_dir(aid) / 'logs' / f'stacks-{safe_name(args.proc)}.txt').write_text(out)
    if not any('HK USTACK' in l or 'r=' in l for l in lines) and rc == 0:
        progress('no HK USTACK lines for this process: the image needs hk_ustack=NAME (USTACK.md)')
    return emit(args, 'stacks', dict(mode='dump', attempt=aid, proc=args.proc, rc=rc, lines=lines), lines, 0 if rc == 0 else 1)


# ------------------------------------------------------------------------------------------------------------- crashes

def crash_brief(cj):
    try:
        doc = json.loads(Path(cj).read_text())
    except (OSError, ValueError):
        return []
    sigs = doc.get('signatures') if isinstance(doc, dict) else doc
    out = []
    for s in sigs or []:
        if isinstance(s, dict):
            hint = s.get('hints') or s.get('hint') or s.get('cause')
            if isinstance(hint, list):
                hint = ','.join(h.get('id', '?') if isinstance(h, dict) else str(h) for h in hint)
            elif isinstance(hint, dict):
                hint = hint.get('id')
            cul = s.get('culprit')
            loc = s.get('loc') or (cul.get('text') or cul.get('loc') if isinstance(cul, dict) else cul)
            out.append(dict(sig=s.get('sig') or s.get('signature') or s.get('id'), proc=s.get('proc') or s.get('process'),
                            kind=s.get('kind'), crash=s.get('crash'), loc=loc,
                            count=s.get('incidents') or s.get('count') or s.get('events'), status=s.get('status'), hint=hint))
    return out


def cmd_crash(args):
    if args.since or args.all:
        ids = [r['id'] for r in filter_index(args)]
        if not ids:
            raise HkError(3, 'no_attempt', 'no attempts match')
        out = ensure_store() / 'census' / dt.datetime.fromtimestamp(now()).strftime('%Y%m%d-%H%M%S')
        inputs = []
        for aid in ids:
            m = load_manifest(aid)
            src = crash_src(m)
            if src:
                inputs.append(str(src))
        aid = None
    else:
        aid = attempt_of(args)
        m = load_manifest(aid)
        src = crash_src(m)
        if not src:
            raise HkError(3, 'no_log', f'{aid}: nothing to read')
        inputs = [str(src)]
        out = attempt_dir(aid) / 'crashes'
    out.mkdir(parents=True, exist_ok=True)
    argv = tool_argv('crashdoc', input=inputs[0], out=str(out))
    if len(inputs) > 1:
        i = argv.index(inputs[0])
        argv[i + 1:i + 1] = inputs[1:]
    if args.no_symbols:
        argv.append('--no-symbols')
    rc, o = run(argv, timeout=1800, log=out / 'hk-crashdoc.log')
    sigs = crash_brief(out / 'crashes.json')
    if aid:
        m = load_manifest(aid)
        m['result']['crash_signatures'] = sigs[:20]
        write_manifest(m)
    txt = [f"{s.get('count') or '?':>4}  {s.get('sig')}  {s.get('loc') or ''}  [{s.get('hint') or 'no known cause'}]  {(s.get('status') or '')[:60]}"
           for s in sigs] or [f'no crash signatures (crashdoc rc {rc}; {out})']
    return emit(args, 'crash', dict(attempt=aid, inputs=inputs, rc=rc, out=str(out), signatures=sigs,
                                    crashes_json=str(out / 'crashes.json'), crashes_md=str(out / 'crashes.md')),
                txt + [f'details: {out / "crashes.md"}'], 0 if rc == 0 else 1)


# ------------------------------------------------------------------------------------------------------------- iOS shell

PROMPT_RE = re.compile(r'ios:[^\n]* # ')
EXIT_RE = re.compile(r'^\[exit (-?\d+)\]$', re.M)
# Runs on the Mac (the ECM link is Mac <-> phone). argv: host port timeout mode [args]; mode cmd LINE | put REMOTE MODE FILE.
MAC_CLIENT = r'''
import socket, sys, hashlib, os
host, port, to, mode = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
s = socket.create_connection((host, port), timeout=to)
if mode == "cmd":
    s.sendall(sys.argv[5].encode() + b"\nexit\n")
else:
    remote, perm, path = sys.argv[5], sys.argv[6], sys.argv[7]
    data = open(path, "rb").read()
    s.sendall(("put %s %d %s %s\n" % (remote, len(data), perm, hashlib.sha256(data).hexdigest())).encode() + data + b"exit\n")
out = b""
while True:
    try:
        b = s.recv(65536)
    except socket.timeout:
        break
    if not b:
        break
    out += b
sys.stdout.write(out.decode(errors="replace"))
'''


def shell_target():
    addr = os.environ.get('HK_SHELL_ADDR', '192.168.77.2:2222')
    host, port = addr.rsplit(':', 1)
    return host, int(port)


def shell_raw(mode, payload, timeout=60):
    """Send one request (cmd line, or put) to hk_shell and return the raw transcript."""
    t = os.environ.get('HK_SHELL', 'mac')
    if t.startswith('tcp:'):
        _, host, port = t.split(':', 2)
        try:
            s = socket.create_connection((host, int(port)), timeout=min(timeout, 10))
        except OSError as e:
            raise HkError(6, 'shell_down', f'hk_shell not reachable at {host}:{port}: {e}')
        s.settimeout(timeout)
        if mode == 'cmd':
            s.sendall(payload.encode() + b'\nexit\n')
        else:
            remote, perm, path = payload
            data = Path(path).read_bytes()
            s.sendall(f'put {remote} {len(data)} {perm} {hashlib.sha256(data).hexdigest()}\n'.encode() + data + b'exit\n')
        chunks = []
        while True:
            try:
                b = s.recv(65536)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
        s.close()
        return b''.join(chunks).decode(errors='replace')
    host, port = shell_target()
    if mode == 'cmd':
        argv = [pb('mac'), '--', '/usr/bin/python3', '-c', MAC_CLIENT, host, str(port), str(timeout), 'cmd', payload]
    else:
        remote, perm, path = payload
        argv = [pb('mac'), '--put', str(path), '--', '/usr/bin/python3', '-c', MAC_CLIENT, host, str(port), str(timeout),
                'put', remote, perm, str(path)]
    rc, out = run(argv, timeout=timeout + 30)
    if rc != 0 and not PROMPT_RE.search(out):
        raise HkError(6, 'shell_down', f'hk_shell not reachable at {host}:{port} from the Mac (rc {rc}): {out.strip()[-200:]}')
    return out


def parse_transcript(raw):
    """banner, prompt, output..., [exit N], prompt -> (banner, output, exit or None for builtins)."""
    parts = PROMPT_RE.split(raw)
    banner = parts[0] if parts else ''
    body = parts[1] if len(parts) > 1 else ''
    m = list(EXIT_RE.finditer(body))
    code = int(m[-1].group(1)) if m else None
    if m:
        body = body[:m[-1].start()]
    return banner, body, code


def shell_run(line, timeout=60):
    raw = shell_raw('cmd', line, timeout)
    if not PROMPT_RE.search(raw):
        raise HkError(6, 'shell_down', 'no hk_shell prompt (is the DBG2 shell in this image and the ECM link up?)', raw=raw[-300:])
    banner, out, code = parse_transcript(raw)
    with contextlib.suppress(OSError):
        ensure_store()
        with open(store_dir() / 'shell.jsonl', 'a') as f:
            f.write(json.dumps(dict(t=iso(), by=holder_name(), cmd=line, exit=code)) + '\n')
    return dict(cmd=line, stdout=out, exit=code, banner=banner.strip()[:400])


def shell_caps(timeout=20):
    """Builtins advertised by `help` (DBG2's hk_shell lists them on one line)."""
    res = shell_run('help', timeout)
    words = set(re.findall(r'[a-z][a-z0-9_-]*', (res['stdout'] + ' ' + res['banner']).split('builtins:', 1)[-1]))
    return words


def cmd_shell(args):
    line = ' '.join(shlex.quote(a) if re.search(r'\s', a) else a for a in args.command)
    if not line:
        raise HkError(2, 'usage', 'hk shell CMD...')
    res = shell_run(line, timeout=args.timeout)
    return emit(args, 'shell', res, res['stdout'].rstrip('\n').splitlines() + ([f"[exit {res['exit']}]"] if res['exit'] is not None else []),
                0 if res['exit'] in (0, None) else 1)


def cmd_push(args):
    src = Path(args.local)
    if not src.is_file():
        raise HkError(2, 'usage', f'no such file: {src}')
    if not args.remote.startswith('/private/var/'):
        raise HkError(2, 'usage', 'the root is read only; push targets must be under /private/var/ (e.g. /private/var/hk/)')
    with phone_lease(args, f'push {args.remote}', ttl=600):
        if 'put' not in shell_caps():
            raise HkError(5, 'unsupported', "hk_shell has no 'put' builtin yet (waiting on DBG2; protocol in HUB.md 4.2)")
        raw = shell_raw('put', (args.remote, args.mode, str(src)), timeout=args.timeout)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    m = re.search(r'\[put ok (\d+) ([0-9a-f]{64})\]', raw)
    ok = bool(m) and m.group(2) == sha
    return emit(args, 'push', dict(local=str(src), remote=args.remote, bytes=src.stat().st_size, sha256=sha, verified=ok,
                                   reply=raw.strip()[-300:]),
                f"{'pushed' if ok else 'push FAILED'} {src} -> {args.remote} ({sha[:12]})", 0 if ok else 1)


def pids_of(name, timeout=30):
    res = shell_run('ps -Ao pid,comm', timeout)
    pids = []
    for l in res['stdout'].splitlines():
        parts = l.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and (parts[1].strip() == name or parts[1].strip().endswith('/' + name)):
            pids.append(int(parts[0]))
    return pids


def cmd_restart(args):
    with phone_lease(args, f'restart {args.daemon}', ttl=600):
        if 'kill' not in shell_caps():
            raise HkError(5, 'unsupported', "hk_shell has no 'kill' builtin yet and the root has no kill/launchctl "
                          '(waiting on DBG2; HUB.md 4.2)')
        before = pids_of(args.daemon)
        if not before:
            raise HkError(6, 'not_running', f'{args.daemon} is not running')
        for pid in before:
            shell_run(f'kill -{args.signal} {pid}')
        after, t0 = [], time.monotonic()
        while time.monotonic() - t0 < args.wait:
            after = [p for p in pids_of(args.daemon) if p not in before]
            if after:
                break
            time.sleep(1)
    ok = bool(after)
    return emit(args, 'restart', dict(daemon=args.daemon, old_pids=before, new_pids=after, respawned=ok),
                f"{args.daemon}: {before} -> {after or 'not respawned within %d s' % args.wait}", 0 if ok else 1)


# ------------------------------------------------------------------------------------------------------------- probe / report

def probe_inputs(m):
    """What probe_eval reads for an attempt: the hk_cycle dir, the runner dir and the live run (each one 'attempt' to it;
    it keeps the best verdict per row), else the bare kernel.log."""
    paths = m.get('paths') or {}
    out = [paths[k] for k in ('cycle', 'runner', 'live') if paths.get(k) and Path(paths[k]).is_dir()]
    if not out and kernel_log(m):
        out = [str(kernel_log(m))]
    return out


def probe_rows(doc):
    """probe_eval --json ({attempts, rows[]}) -> compact rows. An older single-verdict document passes through."""
    if not isinstance(doc, dict) or not isinstance(doc.get('rows'), list):
        return None
    return [dict(id=r.get('id'), row=r.get('row'), verdict=r.get('verdict'), milestone=bool(r.get('milestone')),
                 phone_only=bool(r.get('phone_only')), attempt=r.get('attempt'),
                 evidence=[e.get('cite') if isinstance(e, dict) else e for e in (r.get('evidence') or [])][:3],
                 next=(r.get('next') or {}).get('test') if isinstance(r.get('next'), dict) else None)
            for r in doc['rows']]


def run_probe(inputs, rows=(), qemu=False, attempt='', probes=None):
    """(rc, doc, compact rows | None, raw tail). Raises tool_missing before running anything. probes: a probe file other
    than docs/probes.yaml (hk probes)."""
    argv = tool_argv('probe', inputs=list(inputs), input=inputs[0] if inputs else '', row=rows[0] if rows else '',
                     row_args=[x for r in rows for x in ('--row', r)], qemu_args=['--qemu'] if qemu else [],
                     attempt=attempt)
    if probes:
        argv += ['--probes', str(probes)]
    rc, out = run(argv, timeout=600)
    doc = None
    with contextlib.suppress(ValueError):
        doc = json.loads(out[out.index('{'):]) if '{' in out else None
    return rc, doc, probe_rows(doc), None if doc else out[-2000:]


# ------------------------------------------------------------------------------------------------------------- image probe files

PROBE_FILE_GLOBS = ('research/*.probes.yaml', 'research/*/*.probes.yaml', 'research/*/*/*.probes.yaml',
                    'research/*/*/*/*.probes.yaml', 'research/*/*/*/*/*.probes.yaml')
HEADER_IMAGE = re.compile(r'(?<![\w-])a7-[A-Za-z0-9][\w.-]*[A-Za-z0-9]')


def image_norm(name):
    """a7-ios-system-int5-wifi-r1 / a7-int5-wifi-r1 / int5-wifi-r1 -> int5-wifi-r1 (probe file headers use both spellings)."""
    n = Path(str(name or '')).name
    n = re.sub(r'^\d{8}-\d{6}-', '', n)
    n = re.sub(r'^a7-', '', n)
    return re.sub(r'^ios-system-', '', n)


def probe_files():
    """Every *.probes.yaml under research/ (this checkout, then the main one), with the image names its header comment
    gives: the convention is '# <name>: ... for a7-ios-system-<image>' and a live-<...>-a7-<image> usage line."""
    seen, out = set(), []
    for root in dict.fromkeys((REPO, MAIN_CHECKOUT)):
        for g in PROBE_FILE_GLOBS:
            for f in sorted(root.glob(g)):
                rel = str(f.relative_to(root))
                if rel in seen or '/attempts/' in rel:
                    continue
                seen.add(rel)
                head = []
                with contextlib.suppress(OSError):
                    with open(f, errors='replace') as fh:
                        for line in fh:
                            if not line.startswith('#'):
                                if line.strip():
                                    break
                                continue
                            head.append(line)
                images = sorted({image_norm(x) for x in HEADER_IMAGE.findall(''.join(head))})
                out.append(dict(path=str(f), rel=rel, stem=f.name[:-len('.probes.yaml')], images=images,
                                title=(head[0][1:].strip() if head else '')[:120]))
    return out


def probes_for_image(names, files=None):
    """The probe files for an image (or attempt) name, best first: [(file, rule)]. Rules, in order: the image dir's own
    probes (manifest "probes" or a *.probes.yaml beside boot.img); a header naming the image; the longest header image
    that is a dash-prefix of it (int4-softblur-r1 -> int4); the file stem as one of its dash tokens (bt3)."""
    files = probe_files() if files is None else files
    names = [n for n in dict.fromkeys(names) if n]
    for n in names:
        d = REPO / IMAGES / Path(n).name
        if not d.is_dir():
            d = MAIN_CHECKOUT / IMAGES / Path(n).name
        own = []
        with contextlib.suppress(OSError, ValueError):
            p = json.loads((d / 'manifest.json').read_text()).get('probes')
            for x in ([p] if isinstance(p, str) else p or []):
                cand = Path(x) if Path(x).is_absolute() else (d / x if (d / x).is_file() else REPO / x)
                if cand.is_file():
                    own.append(cand)
        own += sorted(d.glob('*.probes.yaml')) if d.is_dir() else []
        if own:
            return [(dict(path=str(f), rel=str(f), stem=f.name.split('.probes.yaml')[0], images=[image_norm(n)], title=''),
                     'image dir') for f in dict.fromkeys(own)]
    norms = [image_norm(n) for n in names]
    exact = [(f, 'header names ' + n) for n in norms for f in files if n in f['images']]
    if exact:
        return list({f['path']: (f, why) for f, why in exact}.values())
    best = None
    for n in norms:
        for f in files:
            for i in f['images']:
                if n.startswith(i + '-') and (best is None or len(i) > best[0]):
                    best = (len(i), i, n)
    if best:
        return [(f, f'family {best[1]} (of {best[2]})') for f in files if best[1] in f['images']]
    tok = [(f, f'stem {f["stem"]} in {n}') for n in norms for f in files if f['stem'] in n.split('-')]
    return list({f['path']: (f, why) for f, why in tok}.values())


def attempt_image_names(m):
    return [(m.get('image') or {}).get('name'), m.get('name'), m.get('id')]


def image_probe_rows(m, errors, fresh=False):
    """The image's own probe file over an attempt (cached in attempts/<id>/probes/image-<stem>.json). None: no file."""
    found = probes_for_image(attempt_image_names(m))
    if not found:
        return None
    f, why = found[0]
    pj = attempt_dir(m['id']) / 'probes' / f"image-{safe_name(f['stem'])}.json"
    if not fresh:
        with contextlib.suppress(OSError, ValueError):
            j = json.loads(pj.read_text())
            if j.get('probes') == f['path'] and j.get('summary') is not None:
                return dict(probes=f['rel'], rule=why, rows=j['summary'])
    inputs = probe_inputs(m)
    if not inputs:
        return dict(probes=f['rel'], rule=why, rows=None)
    try:
        rc, doc, compact, raw = run_probe(inputs, attempt=m['id'], probes=f['path'])
    except HkError as e:
        errors.append(dict(error=e.error, message=e.message, attempt=m['id'], **e.extra))
        return dict(probes=f['rel'], rule=why, rows=None)
    if compact is None:
        errors.append(dict(error='probe_failed', message=f"probe_eval --probes {f['rel']} rc {rc}: {(raw or '')[-160:]}",
                           attempt=m['id']))
        return dict(probes=f['rel'], rule=why, rows=None)
    pj.parent.mkdir(parents=True, exist_ok=True)
    pj.write_text(json.dumps(dict(probes=f['path'], rule=why, inputs=inputs, rc=rc, summary=compact), indent=1) + '\n')
    return dict(probes=f['rel'], rule=why, rows=compact)


def cmd_probes(args):
    """hk probes IMAGE: the probe file(s) for an image family, run over that image's newest attempt (or --attempt)."""
    files = probe_files()
    if args.list or not args.image:
        rows = []
        for f in files:
            rows.append(dict(probes=f['rel'], images=f['images'], title=f['title']))
        if args.image:
            hits = probes_for_image([args.image], files)
            rows = [dict(probes=f['rel'], images=f['images'], rule=why) for f, why in hits]
        return emit(args, 'probes', dict(image=args.image, files=rows),
                    [f"{r['probes']:<64} {' '.join(r['images']) or '-'}" + (f"  [{r['rule']}]" if r.get('rule') else '')
                     for r in rows] or ['no probe files'])
    m = None
    if args.attempt or args.path:
        m = finalize_from_paths(load_manifest(attempt_of(args)))
    else:
        want = {args.image, Path(args.image).name}
        norm = image_norm(args.image)
        recs = [r for r in index_load() if r.get('image') in want or image_norm(r.get('image') or '') == norm
                or image_norm(r.get('name') or '') == norm]
        recs = [r for r in recs if has_evidence(r) and manifest_path(r['id']).is_file()]
        if recs:
            m = finalize_from_paths(load_manifest(recs[-1]['id']))
    hits = probes_for_image([args.image] + (attempt_image_names(m) if m and (args.attempt or args.path) else []), files)
    if not hits:
        raise HkError(3, 'no_probes', f'no *.probes.yaml names {args.image} (hk probes --list shows every file and its images)',
                      image=args.image)
    if not args.all_matches:
        hits = hits[:1]
    if m is None:
        raise HkError(3, 'no_attempt', f'no attempt of {args.image} with evidence; pass --attempt or --path',
                      probes=[f['rel'] for f, _ in hits])
    inputs = [args.run] if args.run else probe_inputs(m)
    if not inputs:
        raise HkError(3, 'no_log', f"{m['id']}: nothing to evaluate")
    out, txt, worst = [], [], 0
    for f, why in hits:
        rc, doc, compact, raw = run_probe(inputs, list(args.row or []), qemu=args.qemu, attempt=m['id'], probes=f['path'])
        worst = max(worst, rc)
        counts = {}
        for r in compact or []:
            counts[r['verdict'] or 'none'] = counts.get(r['verdict'] or 'none', 0) + 1
        pd = attempt_dir(m['id']) / 'probes'
        pd.mkdir(parents=True, exist_ok=True)
        if compact is not None and not args.row:
            (pd / f"image-{safe_name(f['stem'])}.json").write_text(json.dumps(dict(probes=f['path'], rule=why, inputs=inputs, rc=rc,
                                                                                   summary=compact), indent=1) + '\n')
        out.append(dict(probes=f['rel'], rule=why, rc=rc, counts=counts, rows=compact, raw=raw))
        txt.append(f"# {f['rel']} [{why}] over {m['id']}")
        txt += [f"{(r['verdict'] or '-'):<8} {r['id']:<26} {r['row'] or ''}" for r in compact or []]
        if compact is None:
            txt.append(f'probe_eval rc {rc}: {(raw or "")[-300:]}')
        else:
            txt.append(f"{len(compact)} rows: " + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
    return emit(args, 'probes', dict(image=args.image, attempt=m['id'], inputs=inputs, results=out), txt, 0 if worst == 0 else 1)


def cmd_probe(args):
    rows = list(args.row or [])
    if args.live:
        aid = None
        live, _ = need_live(args)
        inputs = [str(live)]
    else:
        aid = attempt_of(args)
        m = load_manifest(aid)
        inputs = probe_inputs(m)
        if not inputs:
            raise HkError(3, 'no_log', f'{aid}: nothing to evaluate')
    rc, doc, compact, raw = run_probe(inputs, rows, qemu=args.qemu, attempt=aid or '')
    if compact is not None:
        verdict = compact[0]['verdict'] if len(rows) == 1 and len(compact) == 1 else None
    else:
        verdict = doc.get('verdict') if isinstance(doc, dict) else None
    tag = rows[0] if len(rows) == 1 else 'all'
    if aid:
        pd = attempt_dir(aid) / 'probes'
        pd.mkdir(parents=True, exist_ok=True)
        (pd / f'{safe_name(tag)}.json').write_text(json.dumps(dict(row=tag, rows=rows, inputs=inputs, rc=rc, verdict=verdict,
                                                                     summary=compact, result=doc, raw=raw), indent=1) + '\n')
    counts = {}
    for r in compact or []:
        counts[r['verdict'] or 'none'] = counts.get(r['verdict'] or 'none', 0) + 1
    if compact is not None and len(rows) != 1:
        txt = [f"{(r['verdict'] or '-'):<8} {r['id']:<24} {r['row'] or ''}" for r in compact if r['verdict'] or args.verbose]
        txt.append(f"{len(compact)} rows: " + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())) + f' ({aid or inputs[0]})')
    else:
        txt = [f'{tag}: {verdict or "no verdict"} (probe_eval rc {rc})']
    return emit(args, 'probe', dict(attempt=aid, row=rows[0] if len(rows) == 1 else None, rows_asked=rows, inputs=inputs,
                                    rc=rc, verdict=verdict, counts=counts, rows=compact, result=doc if compact is None else None,
                                    raw=raw), txt, 0 if rc == 0 else 1)


# ------------------------------------------------------------------------------------------------------------- status

def latest_run_dir():
    """The newest run directory on disk: runner attempts, live runs, hk_cycle dirs, hk attempts (by mtime)."""
    cands = []
    for root in {REPO / RUNNER_ATTEMPTS, MAIN_CHECKOUT / RUNNER_ATTEMPTS, REPO / CYCLES, MAIN_CHECKOUT / CYCLES}:
        if root.is_dir():
            cands += [x for x in root.iterdir() if x.is_dir() and (RUNNER_NAME.match(x.name.replace('live-', '', 1)) or
                                                                   (x / 'report.json').is_file())]
    for r in index_load()[-50:]:
        d = attempt_dir(r['id'])
        if d.is_dir():
            cands.append(d)
    if not cands:
        return None
    return max(cands, key=lambda x: x.stat().st_mtime)


def cmd_status(args):
    """One-screen summary of a run: image, end, reader, milestones (live markers + milestone probes), README-row probes,
    crash signatures. Defaults to the newest run dir. Wrapped tools that are missing become entries in errors[] (exit 3)."""
    if args.attempt or args.path:
        aid = attempt_of(args)
    else:
        newest = latest_run_dir()
        if newest is None:
            raise HkError(3, 'no_attempt', 'no run directories and no attempts (hk ingest --all)')
        sd = store_dir().resolve()
        aid = newest.name if newest.resolve().parent == sd else ingest_one(newest)[0]
    m = finalize_from_paths(load_manifest(aid))
    write_manifest(m)
    r, errors = m.get('result') or {}, []
    probes = None
    if not args.no_probe:
        inputs = probe_inputs(m)
        if inputs:
            try:
                rc, doc, compact, raw = run_probe(inputs, attempt=aid)
                probes = dict(rc=rc, rows=compact) if compact is not None else dict(rc=rc, raw=raw)
                pd = attempt_dir(aid) / 'probes'
                pd.mkdir(parents=True, exist_ok=True)
                (pd / 'all.json').write_text(json.dumps(dict(row='all', inputs=inputs, rc=rc, summary=compact), indent=1) + '\n')
            except HkError as e:
                errors.append(dict(error=e.error, message=e.message, **e.extra))
    crashes = r.get('crash_signatures')
    cj = attempt_dir(aid) / 'crashes' / 'crashes.json'
    if crashes is None and not args.no_crash:
        src = crash_src(m)
        if src:
            out = attempt_dir(aid) / 'crashes'
            out.mkdir(parents=True, exist_ok=True)
            try:
                argv = tool_argv('crashdoc', input=str(src), out=str(out)) + ['--no-symbols']
                run(argv, timeout=900, log=out / 'hk-crashdoc.log')
                crashes = crash_brief(cj)[:20]
                m['result']['crash_signatures'] = crashes
                write_manifest(m)
            except HkError as e:
                errors.append(dict(error=e.error, message=e.message, **e.extra))
    rows = (probes or {}).get('rows') or []
    milestones = dict(markers=r.get('markers') or [],
                      probes={x['id']: x['verdict'] for x in rows if x['milestone']})
    readme = {x['id']: x['verdict'] for x in rows if not x['milestone']}
    counts = {}
    for v in readme.values():
        counts[v or 'none'] = counts.get(v or 'none', 0) + 1
    img = m.get('image') or {}
    end = r.get('end') or {}
    data = dict(attempt=aid, dir=str(attempt_dir(aid)), name=m.get('name'), image=img.get('name'), features=m.get('features'),
                verdict=r.get('verdict'), rc=r.get('rc'), reader=r.get('reader'), end=end, ui=r.get('ui'),
                return_check=r.get('return_check'), milestones=milestones, probes=readme, probe_counts=counts,
                crashes=crashes or [], crashes_json=str(cj) if cj.is_file() else None, paths=m.get('paths'), errors=errors)
    ms = [k for k, v in milestones['probes'].items() if v]
    txt = [f"{aid}  image {img.get('name') or '-'}  verdict {r.get('verdict') or '-'}  reader {r.get('reader') or '-'}",
           f"end: {end.get('kind', '-')} {end.get('line', '')[:120]}",
           f"milestones: {' '.join(milestones['markers'] + ms) or '-'}",
           'probes: ' + (', '.join(f'{k} {v}' for k, v in sorted(counts.items())) or '-') +
           (('  works: ' + ' '.join(k for k, v in readme.items() if v == 'works')) if counts.get('works') else ''),
           f"crashes: {len(crashes or [])} signatures" + ''.join(f"\n  {c.get('count') or '?':>4}  {c.get('sig')}  "
                                                                  f"[{c.get('hint') or 'no known cause'}]"
                                                                  for c in (crashes or [])[:8])]
    txt += [f"error: {e['message']}" for e in errors]
    return emit(args, 'status', data, txt, 3 if errors else 0)


def cmd_report(args):
    aid = attempt_of(args)
    m = finalize_from_paths(load_manifest(aid))
    write_manifest(m)
    d = attempt_dir(aid)
    probes = {}
    for p in sorted((d / 'probes').glob('*.json')):
        with contextlib.suppress(OSError, ValueError):
            j = json.loads(p.read_text())
            probes[j.get('row', p.stem)] = (j.get('result') or {}).get('verdict') if isinstance(j.get('result'), dict) else None
    screens = sorted(str(p) for p in (d / 'screens').glob('*.png'))
    r = m.get('result') or {}
    img = m.get('image') or {}
    lines = [f"# {aid}", '', f"- image: {img.get('name')} {str(img.get('sha256') or '')[:12]}  kernel {str((m.get('kernel') or {}).get('sha256') or '')[:12]}",
             f"- features: {', '.join(m.get('features') or [])}", f"- verdict: {r.get('verdict')}  rc {r.get('rc')}",
             f"- end: {(r.get('end') or {}).get('line', '-')}", f"- markers: {' '.join(r.get('markers') or [])}",
             f"- ui: {r.get('ui')}  return check: {r.get('return_check')}",
             f"- owner actions: {'; '.join(a['text'] for a in m.get('owner_actions') or []) or '-'}", '', '## Crashes']
    lines += [f"- {s.get('count')}x {s.get('sig')} {s.get('loc') or ''} [{s.get('hint') or 'no known cause'}]" for s in r.get('crash_signatures') or []] or ['- (none recorded; run hk crash)']
    lines += ['', '## Probes'] + ([f'- {k}: {v}' for k, v in probes.items()] or ['- (none; hk probe ROW)'])
    lines += ['', '## Screens'] + ([f'![]({s})' for s in screens] or ['- (none)'])
    lines += ['', '## Paths'] + [f'- {k}: {v}' for k, v in (m.get('paths') or {}).items()]
    cyc = (m.get('paths') or {}).get('cycle')
    if cyc and (Path(cyc) / 'report.md').is_file():
        lines += [f"- hk_cycle report: {Path(cyc) / 'report.md'}"]
    (d / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    return emit(args, 'report', dict(attempt=aid, manifest=m, probes=probes, screens=screens, report_md=str(d / 'REPORT.md')), lines)


# ------------------------------------------------------------------------------------------------------------- images / find / ingest

def cmd_images(args):
    roots = [REPO / IMAGES] + ([MAIN_CHECKOUT / IMAGES] if MAIN_CHECKOUT != REPO else [])
    seen, rows = set(), []
    used = {}
    for r in index_load():
        if r.get('image'):
            used.setdefault(r['image'], []).append(r['id'])
    for root in roots:
        for man in sorted(root.glob('*/manifest.json')):
            if man.parent.name in seen:
                continue
            seen.add(man.parent.name)
            with contextlib.suppress(OSError, ValueError):
                s = image_summary(man.parent, json.loads(man.read_text()))
                s['built'] = iso(man.stat().st_mtime)
                s['attempts'] = used.get(s['name'], [])
                if args.feature and args.feature not in s['features']:
                    continue
                if args.name and not re.search(args.name, s['name']):
                    continue
                s.pop('cmdline') if not args.cmdline else None
                rows.append(s)
    rows.sort(key=lambda s: s['built'])
    txt = [f"{s['built'][:16]}  {s['name']:<34} {str(s['sha256'] or '')[:8]}  {s['kind']:<7} dl={s['deadline']}  "
           f"{','.join(s['features'])}  ({len(s['attempts'])} attempts)" for s in rows]
    return emit(args, 'images', dict(images=rows), txt or ['(no images)'])


def parse_since(s):
    if not s:
        return None
    base = dt.datetime.fromtimestamp(now())
    midnight = base.replace(hour=0, minute=0, second=0, microsecond=0)
    if s == 'today':
        return midnight.timestamp()
    if s == 'yesterday':
        return (midnight - dt.timedelta(days=1)).timestamp()
    m = re.fullmatch(r'(\d+)([mhd])', s)
    if m:
        return now() - int(m[1]) * {'m': 60, 'h': 3600, 'd': 86400}[m[2]]
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        raise HkError(2, 'usage', f'--since: today, yesterday, Nm/Nh/Nd or an ISO date, not {s!r}')


def filter_index(args):
    since = parse_since(getattr(args, 'since', None))
    until = parse_since(getattr(args, 'until', None))
    out = []
    for r in index_load():
        t = r.get('created_t') or 0
        if since and t < since or until and t >= until:
            continue
        if getattr(args, 'feature', None) and args.feature not in (r.get('features') or []):
            continue
        if getattr(args, 'image', None) and not re.search(args.image, r.get('image') or ''):
            continue
        if getattr(args, 'name', None) and not re.search(args.name, r.get('name') or r['id']):
            continue
        if getattr(args, 'verdict', None) and not re.search(args.verdict, str(r.get('verdict')), re.I):
            continue
        if getattr(args, 'kind', None) and r.get('kind') != args.kind:
            continue
        if getattr(args, 'crash', None) and not any(re.search(args.crash, json.dumps(c)) for c in r.get('crashes') or []):
            continue
        out.append(r)
    return out


def cmd_find(args):
    rows = filter_index(args)
    if args.limit:
        rows = rows[-args.limit:]
    txt = [f"{r['id']:<48} {r.get('kind') or '-':<6} {str(r.get('verdict') or '-'):<12} {(r.get('end') or {}).get('kind', '-'):<8} "
           f"{r.get('reader') or '-':<10} "
           f"{','.join(r.get('features') or [])}" for r in rows]
    return emit(args, 'find', dict(count=len(rows), attempts=rows), txt or ['(no attempts match)'])


RUNNER_NAME = re.compile(r'^(\d{8}-\d{6})-(.+)$')


def ingest_one(path):
    """Import an existing runner attempt dir, live_boot run dir or hk_cycle dir as an hk attempt (idempotent by source)."""
    p = Path(path).resolve()
    known = {}
    for r in index_load():
        for v in (r.get('paths') or {}).values():
            known[str(v)] = r['id']
    if str(p) in known:
        return known[str(p)], False
    paths, name, created, kind, img = {}, p.name, None, 'phone', None
    if (p / 'meta.txt').is_file():
        owner = live_owner_of_runner(p)
        if owner:                       # its live_boot run was imported first (the runner copy reached m1box later)
            m = load_manifest(owner)
            m['paths']['runner'] = str(p)
            write_manifest(finalize_from_paths(m))
            return owner, False
        meta = read_kv(p / 'meta.txt')
        name = meta.get('attempt', name)
        paths['runner'] = str(p)
        with contextlib.suppress(ValueError):
            created = dt.datetime.strptime(meta.get('started', ''), '%Y-%m-%d %H:%M:%S %z').timestamp()
        imgp = meta.get('image', '')
        imgname = Path(imgp).parent.name if imgp else None
        if imgname:
            with contextlib.suppress(HkError):
                d, _, man = resolve_image(imgname)
                img = image_summary(d, man)
        if img is None and imgname:
            img = dict(name=imgname, sha256=meta.get('image_sha256'), features=features_of(imgname))
    elif (p / 'live.env').is_file():
        kv = read_kv(p / 'live.env', '=')
        name = kv.get('LIVE_NAME', name)
        paths['live'] = str(p)
        rp = runner_of_live(p)
        if rp:
            if str(rp) in known:
                aid = known[str(rp)]
                m = load_manifest(aid)
                m['paths']['live'] = str(p)
                write_manifest(finalize_from_paths(m))
                return aid, False
            paths['runner'] = str(rp)
            meta = read_kv(rp / 'meta.txt')
            imgname = Path(meta.get('image', '')).parent.name
            if imgname:
                with contextlib.suppress(HkError):
                    d, _, man = resolve_image(imgname)
                    img = image_summary(d, man)
        if img is None:                 # no runner copy on m1box: bootios.txt names the image ("HH:MM:SS.mmm image:  PATH")
            with contextlib.suppress(OSError):
                hit = re.search(r'^\S+ image:\s+(\S+)', (p / 'bootios.txt').read_text(errors='replace'), re.M)
                if hit:
                    imgname = Path(hit.group(1)).parent.name
                    try:
                        d, _, man = resolve_image(imgname)
                        img = image_summary(d, man)
                    except HkError:
                        img = dict(name=imgname, features=features_of(imgname))
    elif (p / 'report.json').is_file() or (p / 'summary.json').is_file():
        paths['cycle'] = str(p)
        with contextlib.suppress(OSError, ValueError):
            rep = json.loads((p / 'report.json').read_text())
            imgname = Path(str((rep.get('image') or {}).get('dir') or (rep.get('image') or {}).get('path') or '')).name
            if imgname:
                with contextlib.suppress(HkError):
                    d, _, man = resolve_image(imgname)
                    img = image_summary(d, man)
    elif (p / 'intent.json').is_file() or (p / 'preflight.json').is_file():
        kind = 'qemu'
        paths['qemu'] = str(p)
    elif (p / 'ramdump/kernel.log').is_file() or (p / 'kernel.log').is_file():
        # a bare ramdump harvest (no runner meta.txt): still a boot's evidence for crash census and timelines
        paths['harvest'] = str(p)
        paths['ramdump'] = str(p / 'ramdump/kernel.log' if (p / 'ramdump/kernel.log').is_file() else p / 'kernel.log')
    else:
        raise HkError(3, 'unknown_dir', f'{p}: not a runner, live_boot, hk_cycle or QEMU run directory')
    return _ingest_make(name, paths, created, kind, img, p)


def live_owner_of_runner(p):
    """The attempt whose live run (with no runner yet) names runner dir p in live.env or its ATTEMPT_DIR marker."""
    for r in reversed(index_load()):
        paths = r.get('paths') or {}
        if paths.get('live') and not paths.get('runner'):
            rp = runner_of_live(paths['live'])
            if rp and rp.resolve() == p:
                return r['id']
    return None


def refresh_store():
    """Re-finalize phone attempts that still lack a runner dir (it is synced to m1box after the live run ends), or that
    have no paths at all (a live boot whose hk boot never returned). Returns the ids whose paths changed."""
    changed = []
    for r in index_load():
        paths = r.get('paths') or {}
        if r.get('kind', 'phone') != 'phone' or paths.get('runner'):
            continue
        if paths and not paths.get('live'):
            continue
        with contextlib.suppress(HkError):
            m = load_manifest(r['id'])
            before = json.dumps(m.get('paths'), sort_keys=True)
            m = finalize_from_paths(m)
            if json.dumps(m.get('paths'), sort_keys=True) != before:
                write_manifest(m)
                changed.append(r['id'])
    return changed


def _ingest_make(name, paths, created, kind, img, p):
    m_rx = RUNNER_NAME.match(p.name.replace('live-', '', 1))
    if created is None and m_rx:
        with contextlib.suppress(ValueError):
            created = dt.datetime.strptime(m_rx[1], '%Y%m%d-%H%M%S').timestamp()
    created = created or p.stat().st_mtime
    aid = (p.name if m_rx and not p.name.startswith('live-') else
           dt.datetime.fromtimestamp(created).strftime('%Y%m%d-%H%M%S') + '-' + safe_name(name))
    if attempt_dir(aid).exists():
        aid += '-imp'
    d = attempt_dir(aid)
    for sub in ('screens', 'probes', 'crashes', 'logs'):
        (d / sub).mkdir(parents=True, exist_ok=True)
    m = dict(schema=f'hk.manifest/{VERSION}', id=aid, name=name, kind=kind, created=iso(created), created_t=created,
             created_by='hk ingest', imported_from=str(p), command=None, image=img,
             kernel=dict(mach=None, sha256=(img or {}).get('kernel_sha256')), cmdline=(img or {}).get('cmdline'),
             features=(img or {}).get('features') or features_of(name), git={}, owner_actions=[], paths=paths, result={})
    if kind == 'qemu':
        m['features'] = sorted(set(m['features']) | {'qemu'})
    write_manifest(finalize_from_paths(m))
    return aid, True


def cmd_ingest(args):
    paths = [Path(x) for x in args.paths]
    if args.all:                        # runner and hk_cycle dirs first, so each live run joins its runner's attempt
        bases = list(dict.fromkeys(b.resolve() for b in (MAIN_CHECKOUT, REPO) if b.is_dir()))
        for base in bases:
            for root in (base / RUNNER_ATTEMPTS, base / CYCLES):
                if root.is_dir():
                    paths += sorted(x for x in root.iterdir() if x.is_dir() and not x.name.startswith('live-'))
        for base in bases:
            root = base / RUNNER_ATTEMPTS
            if root.is_dir():
                paths += sorted(x for x in root.iterdir() if x.is_dir() and x.name.startswith('live-'))
    since = parse_since(args.since)
    done, skipped = [], []
    updated = refresh_store() if args.all else []
    for p in paths:
        if since and p.stat().st_mtime < since:
            continue
        try:
            aid, new = ingest_one(p)
            done.append(dict(path=str(p), attempt=aid, new=new))
        except HkError as e:
            if args.all and e.error == 'unknown_dir':
                skipped.append(str(p))          # --all walks every dir; scratch dirs are not errors
            else:
                done.append(dict(path=str(p), error=e.message))
    if args.all:
        updated += [x for x in refresh_store() if x not in updated]
    n = sum(1 for x in done if x.get('new'))
    return emit(args, 'ingest', dict(imported=n, items=done, updated=updated, skipped=skipped),
                [f"{x.get('attempt') or 'ERR'}  {x['path']}  {x.get('error', '')}"
                 for x in done if args.verbose or x.get('new') or x.get('error')]
                + [f'updated {a}' for a in updated] + ([f'skipped {s}' for s in skipped] if args.verbose else [])
                + [f'{n} new, {len(updated)} updated, {len(done)} seen, {len(skipped)} skipped (not run dirs)'])


def cmd_tools(args):
    rows = []
    for k, (rel, owner, what) in TOOLS.items():
        p = tool_path(k)
        rows.append(dict(key=k, path=str(p), present=p.exists(), owner=owner, what=what,
                         argv=json.loads(os.environ['HK_ARGV_' + k.upper()]) if os.environ.get('HK_ARGV_' + k.upper()) else ARGV.get(k)))
    txt = [f"{'ok ' if r['present'] else '-- '} {r['key']:<13} {r['owner']:<9} {r['path']}" for r in rows]
    return emit(args, 'tools', dict(tools=rows), txt)


# ------------------------------------------------------------------------------------------------------------- queue

def qdir(state):
    d = ensure_store() / 'queue' / state
    d.mkdir(parents=True, exist_ok=True)
    return d


QSTATES = ('pending', 'running', 'done', 'cancelled')


def queue_counts():
    root = store_dir() / 'queue'
    return {s: len(list((root / s).glob('*.json'))) if (root / s).is_dir() else 0 for s in QSTATES}


def q_find(qid):
    for s in QSTATES:
        p = store_dir() / 'queue' / s / f'{qid}.json'
        if p.is_file():
            return s, p, json.loads(p.read_text())
    raise HkError(3, 'no_queue_item', f'no queue item {qid}')


def q_move(p, item, state):
    item['state'] = state
    item.setdefault('history', []).append(dict(t=iso(), state=state, by=holder_name()))
    dst = qdir(state) / p.name
    dst.write_text(json.dumps(item, indent=1) + '\n')
    if dst != p:
        p.unlink()
    return dst


def cmd_queue(args):
    a = args.queue_cmd
    if a == 'add':
        d, boot, man = resolve_image(args.image)
        qid = dt.datetime.fromtimestamp(now()).strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
        item = dict(schema=f'hk.queue/{VERSION}', id=qid, image=str(d), image_sha256=man.get('image'), ui=args.ui,
                    expect=args.expect, mach=args.mach, name=args.name, mode=args.mode, deadline_wait=args.deadline_wait,
                    note=args.note, by=holder_name(args), added=iso(), admitted=None, state='pending', history=[])
        if args.admit:
            item['admitted'] = dict(by=holder_name(args), t=iso())
        (qdir('pending') / f'{qid}.json').write_text(json.dumps(item, indent=1) + '\n')
        return emit(args, 'queue', dict(item=item), f"queued {qid} ({'admitted' if args.admit else 'awaiting admission: hk queue admit ' + qid})")
    if a == 'list':
        rows = []
        for s in QSTATES if args.all else ('pending', 'running'):
            for p in sorted(qdir(s).glob('*.json')):
                with contextlib.suppress(ValueError):
                    rows.append(json.loads(p.read_text()))
        txt = [f"{r['id']}  {r['state']:<9} {'admitted' if r.get('admitted') else 'NOT-ADMITTED':<12} {Path(r['image']).name}  "
               f"ui={r.get('ui')}  {r.get('attempt') or ''} {r.get('verdict') or ''}" for r in rows]
        return emit(args, 'queue', dict(items=rows, counts=queue_counts()), txt or ['(queue empty)'])
    if a == 'show':
        s, p, item = q_find(args.qid)
        return emit(args, 'queue', dict(item=item), json.dumps(item, indent=1))
    if a == 'admit':
        s, p, item = q_find(args.qid)
        if s != 'pending':
            raise HkError(2, 'usage', f'{args.qid} is {s}')
        item['admitted'] = dict(by=holder_name(args), t=iso(), note=args.note)
        p.write_text(json.dumps(item, indent=1) + '\n')
        return emit(args, 'queue', dict(item=item), f'admitted {args.qid}')
    if a == 'cancel':
        s, p, item = q_find(args.qid)
        if s == 'running':
            raise HkError(4, 'running', f'{args.qid} is running; it ends at its own deadline')
        q_move(p, item, 'cancelled')
        return emit(args, 'queue', dict(item=item), f'cancelled {args.qid}')
    if a == 'run':
        return queue_run(args)
    raise HkError(2, 'usage', 'hk queue add|list|show|admit|cancel|run')


def queue_run(args):
    """The single runner: oldest admitted pending item first, one at a time, the lease held per item."""
    results = []
    while True:
        items = sorted(qdir('pending').glob('*.json'))
        nxt = None
        for p in items:
            item = json.loads(p.read_text())
            if item.get('admitted'):
                nxt = (p, item)
                break
        if not nxt:
            if args.once or not args.follow:
                break
            time.sleep(args.poll)
            continue
        p, item = nxt
        rp = q_move(p, item, 'running')
        sub = argparse.Namespace(image=item['image'], name=item.get('name'), mach=item.get('mach'), ui=item.get('ui'),
                                 expect=item.get('expect'), deadline_wait=item.get('deadline_wait'), extra=[], json=True,
                                 holder=args.holder or 'hk-queue-runner', lock_wait=args.lock_wait, queue_id=item['id'],
                                 lock=caller_lock_name(args) or args.holder or 'hk-queue-runner',
                                 wait=item.get('deadline_wait') or 1200, sync_tools=True, no_console=False,
                                 ui_test=item.get('ui') == 'settings', no_auto=False, no_shots=False, no_triage=False,
                                 shot_every=120 if item.get('mode') == 'boot' else 0, shot_step=8)
        progress(f"queue: running {item['id']} ({item.get('mode')})")
        buf = []
        try:
            with contextlib.redirect_stdout(_Tee(buf)):
                rc = (cmd_cycle if item.get('mode') == 'cycle' else cmd_boot)(sub)
            doc = json.loads(''.join(buf)) if buf else {}
            item.update(attempt=doc.get('attempt'), rc=rc, verdict=(doc.get('result') or {}).get('verdict'))
            if item.get('mode') == 'boot' and not args.no_back:
                bns = argparse.Namespace(attempt=doc.get('attempt'), json=True, holder=sub.holder, lock_wait=args.lock_wait,
                                         lock=sub.lock)
                buf2 = []
                with contextlib.redirect_stdout(_Tee(buf2)):
                    cmd_back(bns)
                item['return_check'] = json.loads(''.join(buf2)).get('verdict') if buf2 else None
        except HkError as e:
            item.update(rc=e.code, verdict='ERROR', error=e.message)
            if e.code == 4:                                # busy: put it back, try later
                q_move(rp, item, 'pending')
                if args.once:
                    break
                time.sleep(args.poll)
                continue
        q_move(rp, item, 'done')
        results.append(dict(id=item['id'], attempt=item.get('attempt'), verdict=item.get('verdict'), rc=item.get('rc')))
        if args.once:
            break
    return emit(args, 'queue', dict(ran=results, counts=queue_counts()),
                [f"{r['id']} -> {r['attempt']} {r['verdict']}" for r in results] or ['nothing admitted to run'])


class _Tee:
    def __init__(self, buf):
        self.buf = buf

    def write(self, s):
        self.buf.append(s)
        return len(s)

    def flush(self):
        pass


# ------------------------------------------------------------------------------------------------------------- qemu

def cmd_qemu(args):
    d, _, man = resolve_image(args.image)
    img = image_summary(d, man)
    tool_cmd('qemu')                                   # refuse before an attempt exists
    m = new_attempt(f"qemu-{img['name']}", 'qemu', sys.argv, image=img)
    m['features'] = sorted(set(m['features']) | {'qemu'})
    jpath = attempt_dir(m['id']) / 'qemu.json'
    argv = tool_argv('qemu', image=str(d), json=str(jpath)) + list(args.extra or [])
    m['command'] = argv
    rc, out = run(argv, log=attempt_dir(m['id']) / 'hk-qemu.log', echo=not args.json)
    doc = None
    with contextlib.suppress(OSError, ValueError):
        doc = json.loads(jpath.read_text())
    m['result'] = dict(rc=rc, verdict=(doc or {}).get('verdict') or {0: 'PASS', 1: 'FAIL', 2: 'SETUP_ERROR'}.get(rc, f'rc {rc}'))
    run_dir = (doc or {}).get('run_dir') or (doc or {}).get('run')
    if run_dir:
        m['paths']['qemu'] = str(run_dir)
    write_manifest(m)
    return emit(args, 'qemu', dict(attempt=m['id'], rc=rc, verdict=m['result']['verdict'], result=doc),
                f"QEMU {img['name']}: {m['result']['verdict']} ({attempt_dir(m['id'])})", 0 if rc == 0 else 1)


# ------------------------------------------------------------------------------------------------------------- schema

# ------------------------------------------------------------------------------------------------------------- timeline / diff / triage

# One event table for timeline, diff and triage. Live console lines are "HH:MM:SS.mmm [ uptime] text"; a ramdump has
# "[ uptime] text" only. kind: what the line says about the boot (filters: hk timeline --kind).
EVENT_RX = (
    ('panic', re.compile(r'panic\(cpu \d+ caller')),
    ('deadline', re.compile(r'blazer-root: deadline \d+ s')),
    ('crash', re.compile(r'\bCRASH \S+|\busertrap: |\buserabort: |exited due to (?:SIG\w+|exit\([1-9]\d*\))|exec: SIGKILL to')),
    ('physical', re.compile(r'\btcm: finger \d+ down|blazer-keys: volume (?:up|down) pressed|blazer-power-key: pressed')),
    ('input', re.compile(r'HK LIVE dispatch gen=\d+ edge=down|HK LIVE done gen=\d+ result=[1-9]|usbcon: input \{"state":"(?:refused|unknown)')),
    ('exec', re.compile(r'(?:^|\] )exec (\S+)')),
    ('stall', re.compile(r'HKMAIN: stall|HKMAIN: gap \d{5,} ms')),
)
EXEC_NOISE = {'xpcproxy'}
EXEC_KEEP = 3              # exec lines per process kept in a timeline; the rest are counted (respawns)
WALL_RE = re.compile(r'^(\d\d):(\d\d):(\d\d)\.(\d{3}) (.*)$')
UPTIME_RE = re.compile(r'^\[ *(\d+\.\d+)\] (.*)$')
TAGGED_RE = re.compile(r'^(LIVEBOOT|UIRUN) (\d\d:\d\d:\d\d\.\d{3}) \+(-?[\d.]+) (\S+) ?(.*)$')
MARKER_SKIP = {'CRASH', 'INPUT', 'SNAPSHOT'}       # the console lines say the same, with more detail


def sod(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def classify(text):
    for kind, rx in EVENT_RX:
        hit = rx.search(text)
        if hit:
            if kind == 'exec':
                return kind, hit.group(1)
            return kind, None
    return None, None


def boot_lines(m):
    """(source kind, lines, T0 seconds-of-day or None). The live console when there is one (it has wall times), else
    the ramdump up to its first panic line (hklog's rule: what follows is residue of older boots)."""
    con = console_log(m)
    if con:
        t0 = None
        live = con.parent
        kv = read_kv(live / 'live.env', '=')
        with contextlib.suppress(ValueError, KeyError):
            lt = dt.datetime.fromtimestamp(float(kv['LIVE_T0']))
            t0 = lt.hour * 3600 + lt.minute * 60 + lt.second + lt.microsecond / 1e6
        return 'live', con.read_text(errors='replace').splitlines(), t0
    k = kernel_log(m)
    if k:
        lines = raw_lines(k)
        for i, l in enumerate(lines):
            if 'panic(cpu' in l:
                lines = lines[:i + 1]
                break
        return 'dump', lines, None
    return None, [], None


def boot_events(m):
    """Every classified event of an attempt's boot, sorted by t (s since LIVE_T0 on a live console, kernel uptime in a
    dump). Also returns exec counts per process (respawns) and how t is measured."""
    src, lines, t0 = boot_lines(m)
    events, execs = [], {}
    first_wall = None

    def rel(wall_s):
        nonlocal first_wall
        base = t0 if t0 is not None else first_wall
        if base is None:
            first_wall = base = wall_s
        d = wall_s - base
        return d + 86400 if d < -43200 else d

    for line in lines:
        wall, t, text = None, None, line
        w = WALL_RE.match(line)
        if w:
            wall, text = line[:12], w.group(5)
            t = rel(sod(*w.groups()[:4]))
        u = UPTIME_RE.match(text)
        if u:
            text = u.group(2)
            if t is None:
                t = float(u.group(1))
        kind, proc = classify(text)
        if not kind:
            continue
        if kind == 'exec':
            if proc in EXEC_NOISE:
                continue
            execs[proc] = execs.get(proc, 0) + 1
            if execs[proc] > EXEC_KEEP:
                continue
        events.append(dict(t=None if t is None else round(t, 2), wall=wall, src=src, kind=kind, text=text.strip()[:240]))
    live = (m.get('paths') or {}).get('live') or discover_live(m)
    if live:
        tagged = []
        for f in (Path(live) / 'markers.txt',):
            with contextlib.suppress(OSError):
                tagged += f.read_text(errors='replace').splitlines()
        for line in tagged:
            g = TAGGED_RE.match(line)
            if not g:
                continue
            who, wall, t, name, detail = g.groups()
            if who == 'LIVEBOOT' and name in MARKER_SKIP:
                continue
            kind = 'milestone' if who == 'LIVEBOOT' else 'ui'
            if who == 'UIRUN' and name not in ('START', 'STEP', 'ACTION', 'OCR', 'PHYSICAL', 'MARK', 'RECOVERY', 'END', 'STOP',
                                               'NOTE', 'HOME'):
                continue
            events.append(dict(t=float(t), wall=wall, src='markers', kind=kind, text=f'{name} {detail}'.strip()[:240]))
    events.sort(key=lambda e: (e['t'] is None, e['t'] or 0))
    return dict(source=src, clock='s since LIVE_T0' if src == 'live' else 'kernel uptime s', events=events,
                respawns={p: n for p, n in sorted(execs.items(), key=lambda x: -x[1]) if n > 1})


def timeline_text(e):
    t = '        ?' if e['t'] is None else f"{e['t']:+9.1f}"
    return f"{t}  {e['wall'] or '            '}  {e['kind']:<9} {e['text'][:170]}"


def cmd_timeline(args):
    aid = args.attempt_pos or attempt_of(args)
    m = finalize_from_paths(load_manifest(aid))
    tl = boot_events(m)
    if tl['source'] is None:
        raise HkError(3, 'no_log', f'{aid}: no live console and no ramdump')
    kinds = set(args.kind.split(',')) if args.kind else None
    ev = [e for e in tl['events'] if (not kinds or e['kind'] in kinds) and (not args.grep or re.search(args.grep, e['text']))
          and (args.since_t is None or (e['t'] is not None and e['t'] >= args.since_t))
          and (args.until_t is None or (e['t'] is not None and e['t'] <= args.until_t))]
    total = len(ev)
    if args.limit:
        ev = ev[-args.limit:]
    out = attempt_dir(aid) / 'timeline.txt'
    lines = [timeline_text(e) for e in ev]
    resp = [f"respawns (exec count, first {EXEC_KEEP} shown above): " +
            ', '.join(f'{p} {n}' for p, n in tl['respawns'].items())] if tl['respawns'] else []
    with contextlib.suppress(OSError):
        out.write_text(f"# {aid} timeline ({tl['source']}; t = {tl['clock']})\n" + '\n'.join(lines + resp) + '\n')
    return emit(args, 'timeline', dict(attempt=aid, source=tl['source'], clock=tl['clock'], total=total, events=ev,
                                       respawns=tl['respawns'], file=str(out)),
                [f"# {aid}: {total} events ({tl['source']}; t = {tl['clock']})"] + lines + resp)


# ------------------------------------------------------------------------------------------------------------- watch

CRASH_PROC_RE = re.compile(r'\bCRASH (?P<c>[^\s\[]+)|\buser(?:trap|abort): (?P<u>[^\s\[]+)\[(?P<up>\d+)\]|'
                           r'exec: SIGKILL to (?P<k>[^\s\[]+)\[(?P<kp>\d+)\]|(?P<e>[^\s\[]+)\[(?P<ep>\d+)\] exited due to')
TOP_RE = re.compile(r'HK TOP: t=(\d+) frames\+(\d+) cpu_ms=(\d+): (.*)$')
TOP_PROC_RE = re.compile(r'([^\s\[]+)\[(\d+)\]=(\d+)')
WATCH_MILESTONES = ('EP0_LIVE', 'CONSOLE_CONNECTED', 'DISPLAY', 'ROOT', 'LAUNCHD', 'USB_CONFIGURED', 'SPRINGBOARD',
                    'TOUCH_CLIENT', 'BUTTON_CLIENT', 'FRAMES', 'UI_READY', 'PARKED', 'PANIC', 'DEADLINE', 'CONSOLE_GONE', 'BOOT_RC')


class WatchState:
    """A running boot's console, read incrementally (only the new bytes each frame), plus its markers and pictures."""

    def __init__(self, live, attempt=None):
        self.live, self.attempt = Path(live), attempt
        self.offset, self.partial = 0, b''
        self.lines = 0
        self.crash_lines, self.crash_pids = {}, {}
        self.execs, self.counts = {}, dict(physical=0, input=0, stall=0)
        self.top, self.top_n, self.end, self.last_line = None, 0, None, ''
        self.probe, self.probe_at, self.probe_file = None, 0.0, None

    def feed(self, data):
        data = self.partial + data
        cut = data.rfind(b'\n') + 1
        self.partial = data[cut:]
        for raw in data[:cut].splitlines():
            line = raw.decode('utf-8', 'replace')
            self.lines += 1
            text = line
            w = WALL_RE.match(text)
            if w:
                text = w.group(5)
            u = UPTIME_RE.match(text)
            if u:
                text = u.group(2)
            if text.strip():
                self.last_line = line[:200]
            t = TOP_RE.search(text)
            if t:
                self.top_n += 1
                self.top = dict(t=int(t[1]), frames=int(t[2]), cpu_ms=int(t[3]), wall=line[:12] if w else None,
                                procs=[dict(proc=p, pid=int(pid), ms=int(ms)) for p, pid, ms in TOP_PROC_RE.findall(t[4])][:8])
                continue
            kind, proc = classify(text)
            if kind in ('panic', 'deadline'):
                self.end = self.end or dict(kind=kind, line=text.strip()[:200])
            elif kind == 'crash':
                c = CRASH_PROC_RE.search(text)
                if c:
                    if c['c']:
                        self.crash_lines[c['c']] = self.crash_lines.get(c['c'], 0) + 1
                    else:
                        name, pid = next((c[a], c[b]) for a, b in (('u', 'up'), ('k', 'kp'), ('e', 'ep')) if c[a])
                        self.crash_pids.setdefault(name, set()).add(pid)
            elif kind == 'exec' and proc not in EXEC_NOISE:
                self.execs[proc] = self.execs.get(proc, 0) + 1
            elif kind in self.counts:
                self.counts[kind] += 1

    def poll(self):
        con = self.live / 'console.txt'
        with contextlib.suppress(OSError):
            size = con.stat().st_size
            if size < self.offset:                    # rewritten: start over
                self.__init__(self.live, self.attempt)
            with open(con, 'rb') as f:
                f.seek(self.offset)
                data = f.read()
            self.offset += len(data)
            self.feed(data)

    def crashes(self):
        names = set(self.crash_lines) | set(self.crash_pids)
        return sorted(({'proc': n, 'count': max(self.crash_lines.get(n, 0), len(self.crash_pids.get(n, ())))} for n in names),
                      key=lambda x: (-x['count'], x['proc']))

    def pictures(self, n=1):
        roots = [self.live / 'screens', self.live / 'ui'] + list(self.live.glob('usbcon/*.snaps'))
        if self.attempt:
            roots.insert(0, attempt_dir(self.attempt) / 'screens')
        pngs = [p for r in roots if r.is_dir() for p in r.glob('*.png')]
        return [str(p) for p in sorted(pngs, key=lambda p: p.stat().st_mtime, reverse=True)[:n]]

    def run_probes(self, every, m=None):
        """The image's probe file (else docs/probes.yaml) over the live run, at most every `every` s."""
        if every <= 0 or time.time() - self.probe_at < every:
            return
        self.probe_at = time.time()
        names = attempt_image_names(m) if m else []
        img = read_kv(self.live / 'bootios.txt').get('image', '')
        if img:
            names.append(Path(img).parent.name)
        names.append(read_kv(self.live / 'live.env', '=').get('LIVE_NAME'))
        found = probes_for_image(names)
        self.probe_file = found[0][0]['rel'] if found else 'docs/probes.yaml'
        inputs = [str(self.live)] + ([str(runner_dir(m))] if m and runner_dir(m) and runner_dir(m).is_dir() else [])
        try:
            rc, doc, compact, raw = run_probe(inputs, attempt=self.attempt or '', probes=found[0][0]['path'] if found else None)
            self.probe = compact if compact is not None else dict(error=f'probe_eval rc {rc}: {(raw or "")[-160:]}')
        except HkError as e:
            self.probe = dict(error=e.message)

    def snapshot(self, now_t=None):
        now_t = time.time() if now_t is None else now_t
        kv = read_kv(self.live / 'live.env', '=')
        marks = read_markers(self.live / 'markers.txt')
        first = {}
        for x in marks:
            first.setdefault(x['name'], x)
        con = self.live / 'console.txt'
        age = now_t - con.stat().st_mtime if con.is_file() else None
        t0 = kv.get('LIVE_T0')
        el = now_t - float(t0) if t0 and t0.replace('.', '', 1).isdigit() else None
        state = 'ended' if 'BOOT_RC' in kv or 'BOOT_RC' in first else \
            'stale' if age is None or age > LIVE_STALE_S else 'running'
        ui = state == 'running' and ui_run_active(self.live / 'markers.txt')
        if state == 'ended' and 'BOOT_RC' in first and first['BOOT_RC']['s'] is not None:
            el = first['BOOT_RC']['s']
        elif state == 'stale' and el is not None and age is not None:
            el -= age                                 # when the console last moved
        return dict(live=str(self.live), attempt=self.attempt, name=kv.get('LIVE_NAME'), state=state,
                    elapsed_s=None if el is None else round(el, 1), console_lines=self.lines, console_bytes=self.offset,
                    console_age_s=None if age is None else round(age, 1), last_line=self.last_line,
                    milestones=[dict(name=k, t=first[k]['s'], detail=first[k]['detail'][:80]) for k in WATCH_MILESTONES if k in first],
                    missing=[k for k in ('CONSOLE_CONNECTED', 'LAUNCHD', 'SPRINGBOARD', 'UI_READY') if k not in first],
                    ui_run=ui, crashes=self.crashes(), respawns={p: n for p, n in sorted(self.execs.items(), key=lambda x: -x[1])
                                                                  if n > EXEC_KEEP},
                    counts=self.counts, top=self.top, end=self.end, probes_file=self.probe_file, probes=self.probe,
                    pictures=self.pictures(3))


def watch_text(s):
    el = '-' if s['elapsed_s'] is None else f"{s['elapsed_s']:.0f}s"
    L = [f"hk watch {s['attempt'] or s['live']}  [{s['state'].upper()}]  t+{el}  console {s['console_lines']} lines, "
         f"{s['console_bytes'] // 1024} KiB, last write {s['console_age_s']}s ago" + ('  UI SCRIPT RUNNING' if s['ui_run'] else '')]
    if s['end']:
        L.append(f"END {s['end']['kind']}: {s['end']['line']}")
    L += ['', 'milestones: ' + '  '.join(f"{x['name']} +{x['t']:.0f}" if x['t'] is not None else x['name'] for x in s['milestones'])]
    if s['missing']:
        L.append('not yet: ' + ' '.join(s['missing']))
    c = s['counts']
    L.append(f"crashes: {sum(x['count'] for x in s['crashes'])} in {len(s['crashes'])} procs  " +
             '  '.join(f"{x['proc']} x{x['count']}" for x in s['crashes'][:8]))
    if s['respawns']:
        L.append('respawns: ' + '  '.join(f'{p} {n}' for p, n in list(s['respawns'].items())[:8]))
    L.append(f"input: {c['input']} live ops  PHYSICAL: {c['physical']} touches/buttons  stalls: {c['stall']}")
    t = s['top']
    if t:
        L.append(f"HK TOP t={t['t']} frames+{t['frames']} cpu_ms={t['cpu_ms']}: " +
                 ' '.join(f"{p['proc']}={p['ms']}" for p in t['procs'][:6]))
    p = s['probes']
    L += ['', f"probes ({s['probes_file'] or 'not run yet'}):"]
    if isinstance(p, dict):
        L.append(f"  {p['error']}")
    for r in p or [] if isinstance(p, list) else []:
        mark = {'works': 'PASS', 'broken': 'FAIL', 'partial': 'PART'}.get(r['verdict'], ' -- ')
        L.append(f"  {mark:<4} {r['id']:<26} {(r['row'] or '')[:90]}")
    L += ['', 'latest picture: ' + (s['pictures'][0] if s['pictures'] else 'none'), f"last line: {s['last_line']}"]
    return L


def watch_html(s, out):
    import html as H
    rows = ''.join(f"<tr class='{H.escape(str(r['verdict']))}'><td>{H.escape(str(r['verdict'] or '-'))}</td><td>{H.escape(r['id'])}</td>"
                   f"<td>{H.escape(r['row'] or '')}</td></tr>" for r in (s['probes'] if isinstance(s['probes'], list) else []))
    pic = ''
    if s['pictures']:
        rel = os.path.relpath(s['pictures'][0], Path(out).parent)
        pic = f"<img src='{H.escape(rel)}?{int(time.time())}' style='max-height:90vh;float:right;margin-left:1em'>"
    body = H.escape('\n'.join(watch_text(s)))
    doc = (f"<!doctype html><meta charset=utf-8><meta http-equiv=refresh content=3><title>hk watch {H.escape(str(s['attempt']))}</title>"
           "<style>body{font:13px ui-monospace,monospace;background:#111;color:#ddd}pre{white-space:pre-wrap}"
           "td{padding:1px 8px}.works td:first-child{color:#6c6}.partial td:first-child{color:#db6}.broken td:first-child{color:#e66}</style>"
           f"{pic}<pre>{body}</pre><table>{rows}</table>")
    tmp = Path(str(out) + '.tmp')
    tmp.write_text(doc)
    tmp.replace(out)


def watch_target(args):
    """(live dir, attempt id or None, manifest or None) for hk watch."""
    if args.run:
        live = Path(args.run)
        aid = attempt_for_live(live)
    else:
        aid = args.attempt_pos or args.attempt
        if not aid:
            live, _ = active_live_run()
            if live:
                return Path(live), attempt_for_live(live) or None, None
            aid = latest_attempt()
        m = finalize_from_paths(load_manifest(aid))
        live = (m.get('paths') or {}).get('live')
        if not live:
            raise HkError(3, 'no_log', f'{aid}: no live run (hk watch follows a live_boot console)')
        return Path(live), aid, m
    return live, aid, load_manifest(aid) if aid and manifest_path(aid).is_file() else None


def cmd_watch(args):
    live, aid, m = watch_target(args)
    if not (live / 'live.env').is_file():
        raise HkError(3, 'no_log', f'{live} is not a live_boot run (no live.env)')
    ws = WatchState(live, aid)
    html_out = None
    if args.html is not None:
        html_out = Path(args.html) if args.html else (attempt_dir(aid) if aid else live) / 'watch.html'
    once = args.once or args.json
    tty = sys.stdout.isatty() and not once
    t_end = time.time() + args.max_s if args.max_s else None
    try:
        while True:
            ws.poll()
            if not args.no_probe:
                ws.run_probes(args.probe_every if not once else 0.001, m)
            s = ws.snapshot()
            if html_out:
                with contextlib.suppress(OSError):
                    watch_html(s, html_out)
            s['html'] = str(html_out) if html_out else None
            if once:
                break
            text = '\n'.join(watch_text(s) + ([f'html: {html_out}'] if html_out else []))
            sys.stdout.write(('\x1b[H\x1b[2J' if tty else '\n') + text + '\n')
            sys.stdout.flush()
            if s['state'] != 'running' or (t_end and time.time() >= t_end):
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    if once:
        return emit(args, 'watch', s, watch_text(s) + ([f'html: {html_out}'] if html_out else []))
    return 0


def family_key(name):
    n = re.sub(r'^a7-(ios-system-)?', '', name or '')
    n = re.sub(r'-(confirm|live|dbg|ui|imp)$', '', n)
    prev = None
    while prev != n:
        prev = n
        n = re.sub(r'(-r\d+[a-z]?|-s\d+[a-z]?|\d+[a-z]?)$', '', n)
    return n


def has_evidence(r):
    """Paths in the record, or a live run inside the attempt dir (a boot whose hk process never returned has paths={})."""
    paths = r.get('paths') or {}
    if paths.get('live') or paths.get('ramdump') or paths.get('runner'):
        return True
    return r.get('kind', 'phone') == 'phone' and 'id' in r and any(attempt_dir(r['id']).glob('live-*/console.txt'))


def previous_same_family(aid):
    """The newest earlier phone attempt with evidence: same image, else same image family, else same name family."""
    recs = index_load()
    me = next((r for r in recs if r['id'] == aid), None)
    if not me:
        return None
    earlier = [r for r in recs if (r.get('created_t') or 0) < (me.get('created_t') or 0) and r['id'] != aid
               and r.get('kind', 'phone') == 'phone' and has_evidence(r) and manifest_path(r['id']).is_file()]
    same = [r for r in earlier if me.get('image') and r.get('image') == me.get('image')]
    if same:
        return same[-1]['id']
    keys = {family_key(me.get('name') or me['id'])} | ({family_key(me['image'])} if me.get('image') else set())
    fam = [r for r in earlier if family_key(r.get('name') or r['id']) in keys or (r.get('image') and family_key(r['image']) in keys)]
    return fam[-1]['id'] if fam else None


def cached_or_run_probes(m, errors, fresh=False):
    aid = m['id']
    pj = attempt_dir(aid) / 'probes' / 'all.json'
    if not fresh:
        with contextlib.suppress(OSError, ValueError):
            j = json.loads(pj.read_text())
            if j.get('summary') is not None:
                return j['summary']
    inputs = probe_inputs(m)
    if not inputs:
        return []
    try:
        rc, doc, compact, raw = run_probe(inputs, attempt=aid)
    except HkError as e:
        errors.append(dict(error=e.error, message=e.message, attempt=aid, **e.extra))
        return None
    pj.parent.mkdir(parents=True, exist_ok=True)
    pj.write_text(json.dumps(dict(row='all', inputs=inputs, rc=rc, summary=compact), indent=1) + '\n')
    return compact


def cached_or_run_crashes(m, errors, fresh=False):
    aid = m['id']
    cj = attempt_dir(aid) / 'crashes' / 'crashes.json'
    if cj.is_file() and not fresh:
        return crash_brief(cj)
    src = crash_src(m)
    if not src:
        return []
    out = attempt_dir(aid) / 'crashes'
    out.mkdir(parents=True, exist_ok=True)
    try:
        run(tool_argv('crashdoc', input=str(src), out=str(out)) + ['--no-symbols'], timeout=900, log=out / 'hk-crashdoc.log')
    except HkError as e:
        errors.append(dict(error=e.error, message=e.message, attempt=aid, **e.extra))
        return None
    sigs = crash_brief(cj)
    m['result']['crash_signatures'] = sigs[:20]
    write_manifest(m)
    return sigs


def subsystem_counts(m):
    src = console_log(m) or kernel_log(m)
    if not src:
        return {}
    try:
        split = split_logs(m, src)
    except HkError:
        return {}
    if not split:
        return {}
    out = {}
    for f in sorted(split.glob('*.log')) + sorted(split.glob('hkl/*.log')):
        with contextlib.suppress(OSError):
            out[str(f.relative_to(split))[:-4]] = sum(1 for _ in open(f, 'rb'))
    return out


def attempt_facts(aid, errors, fresh=False, subsystems=True):
    m = finalize_from_paths(load_manifest(aid))
    write_manifest(m)
    r = m.get('result') or {}
    tl = boot_events(m)
    first = {}
    for e in tl['events']:
        key = None
        if e['kind'] == 'milestone':
            key = e['text'].split()[0]
        elif e['kind'] in ('panic', 'deadline'):
            key = e['kind'].upper()
        elif e['kind'] == 'exec' and e['text'].split()[-1] in ('SpringBoard', 'backboardd', 'Preferences', 'MobilePhone'):
            key = 'exec ' + e['text'].split()[-1]
        if key and key not in first and e['t'] is not None:
            first[key] = e['t']
    crashes_by_proc = {}
    for e in tl['events']:
        if e['kind'] == 'crash':
            p = re.search(r'CRASH (\S+)|usertrap: (\S+)|userabort: (\S+)|\(\S*?([A-Za-z]+)\[\d+\]\)', e['text'])
            name = next((g for g in (p.groups() if p else ()) if g), 'other')
            crashes_by_proc[name] = crashes_by_proc.get(name, 0) + 1
    return dict(id=aid, name=m.get('name'), image=(m.get('image') or {}).get('name'), verdict=r.get('verdict'),
                reader=r.get('reader'), end=r.get('end'), ui=r.get('ui'), markers=r.get('markers') or [],
                source=tl['source'], clock=tl['clock'], first=first, respawns=tl['respawns'],
                physical=sum(1 for e in tl['events'] if e['kind'] == 'physical'),
                crash_lines=crashes_by_proc,
                probes=cached_or_run_probes(m, errors, fresh), crashes=cached_or_run_crashes(m, errors, fresh),
                subsystems=subsystem_counts(m) if subsystems else {}), m


def diff_facts(a, b):
    """What changed from attempt a to attempt b (b is usually the newer)."""
    pa = {x['id']: x['verdict'] for x in a['probes'] or []}
    pb = {x['id']: x['verdict'] for x in b['probes'] or []}
    probes = [dict(id=k, a=pa.get(k), b=pb.get(k)) for k in sorted(set(pa) | set(pb)) if pa.get(k) != pb.get(k)]
    ca = {c['sig']: c for c in a['crashes'] or [] if c.get('sig')}
    cb = {c['sig']: c for c in b['crashes'] or [] if c.get('sig')}
    crashes = dict(new=[dict(sig=s, count=cb[s].get('count'), hint=cb[s].get('hint')) for s in cb if s not in ca],
                   gone=[dict(sig=s, count=ca[s].get('count')) for s in ca if s not in cb],
                   changed=[dict(sig=s, a=ca[s].get('count'), b=cb[s].get('count')) for s in cb
                            if s in ca and ca[s].get('count') != cb[s].get('count')])
    resp = [dict(proc=p, a=a['respawns'].get(p, 0), b=b['respawns'].get(p, 0))
            for p in sorted(set(a['respawns']) | set(b['respawns'])) if a['respawns'].get(p, 0) != b['respawns'].get(p, 0)]
    subs = []
    for k in sorted(set(a['subsystems']) | set(b['subsystems'])):
        x, y = a['subsystems'].get(k, 0), b['subsystems'].get(k, 0)
        if x != y and (max(x, y) >= 20 and abs(y - x) >= max(10, 0.25 * max(x, y)) or min(x, y) == 0):
            subs.append(dict(file=k, a=x, b=y))
    tl = [dict(event=k, a=a['first'].get(k), b=b['first'].get(k),
               delta=None if a['first'].get(k) is None or b['first'].get(k) is None else round(b['first'][k] - a['first'][k], 1))
          for k in sorted(set(a['first']) | set(b['first']), key=lambda k: b['first'].get(k, a['first'].get(k, 1e9)))]
    head = {k: dict(a=a.get(k), b=b.get(k)) for k in ('image', 'verdict', 'reader', 'ui', 'source', 'physical')
            if a.get(k) != b.get(k)}
    head['end'] = dict(a=(a.get('end') or {}).get('line'), b=(b.get('end') or {}).get('line'))
    markers = dict(only_a=sorted(set(a['markers']) - set(b['markers'])), only_b=sorted(set(b['markers']) - set(a['markers'])))
    return dict(head=head, markers=markers, probes=probes, crashes=crashes, respawns=resp, subsystems=subs, timeline=tl,
                crash_lines=dict(a=a['crash_lines'], b=b['crash_lines']))


def diff_text(a, b, d):
    t = [f"diff {a['id']} -> {b['id']}"]
    for k, v in d['head'].items():
        if v['a'] != v['b']:
            t.append(f"  {k}: {v['a']} -> {v['b']}")
    if d['markers']['only_a'] or d['markers']['only_b']:
        t.append(f"markers: lost {' '.join(d['markers']['only_a']) or '-'}; new {' '.join(d['markers']['only_b']) or '-'}")
    t.append(f"probes: {len(d['probes'])} changed" + ''.join(f"\n  {p['id']:<26} {p['a'] or '-'} -> {p['b'] or '-'}"
                                                           for p in d['probes']))
    c = d['crashes']
    t.append(f"crash signatures: {len(c['new'])} new, {len(c['gone'])} gone, {len(c['changed'])} count changes")
    t += [f"  new  {x['count'] or '?':>4}x {x['sig']}  [{x.get('hint') or 'no known cause'}]" for x in c['new']]
    t += [f"  gone {x['count'] or '?':>4}x {x['sig']}" for x in c['gone']]
    t += [f"  {x['a']} -> {x['b']}  {x['sig']}" for x in c['changed']]
    if d['respawns']:
        t.append('respawns (exec count): ' + ', '.join(f"{x['proc']} {x['a']}->{x['b']}" for x in d['respawns']))
    if d['subsystems']:
        t.append('subsystem lines: ' + ', '.join(f"{x['file']} {x['a']}->{x['b']}" for x in d['subsystems']))
    t.append(f"timeline (first t, {b['clock']}):")
    for x in d['timeline']:
        a_, b_ = ('-' if x['a'] is None else f"{x['a']:.1f}"), ('-' if x['b'] is None else f"{x['b']:.1f}")
        t.append(f"  {x['event']:<28} {a_:>8} -> {b_:>8}" + (f"  ({x['delta']:+.1f})" if x['delta'] else ''))
    return t


def cmd_diff(args):
    errors = []
    b_id = args.b
    a_id = args.a
    if not b_id:                                     # hk diff X: X against the previous boot of its family
        b_id = a_id
        a_id = previous_same_family(b_id)
        if not a_id:
            raise HkError(3, 'no_attempt', f'no earlier attempt of the same family as {b_id}; name both: hk diff A B')
    a, _ = attempt_facts(a_id, errors, args.fresh, subsystems=not args.no_subsystems)
    b, _ = attempt_facts(b_id, errors, args.fresh, subsystems=not args.no_subsystems)
    d = diff_facts(a, b)
    txt = diff_text(a, b, d) + [f"error: {e['message']}" for e in errors]
    return emit(args, 'diff', dict(a=a_id, b=b_id, **d, errors=errors), txt, 3 if errors else 0)


def run_backlog(m, out_dir, errors):
    inputs = probe_inputs(m)
    if not inputs:
        return None
    try:
        argv = tool_cmd('backlog') + inputs + ['--out', str(out_dir / 'BACKLOG.md'), '--json', str(out_dir / 'backlog.json')]
    except HkError as e:
        errors.append(dict(error=e.error, message=e.message, **e.extra))
        return None
    rc, o = run(argv, timeout=1800, log=out_dir / 'hk-backlog.log')
    with contextlib.suppress(OSError, ValueError):
        doc = json.loads((out_dir / 'backlog.json').read_text())
        return doc.get('items') if isinstance(doc, dict) else doc
    errors.append(dict(error='backlog_failed', message=f'backlog.py rc {rc}: {o.strip()[-200:]}'))
    return None


def cmd_triage(args):
    """crashdoc + probe_eval + diff vs the previous same-family boot + backlog -> attempts/<id>/TRIAGE.md."""
    aid = args.attempt_pos or attempt_of(args)
    data, L, errors = triage_attempt(aid, prev=args.prev, fresh=args.fresh, no_backlog=args.no_backlog)
    return emit(args, 'triage', data, [f"triage: {data['triage_md']}"] + L[2:6] + [f"error: {e['message']}" for e in errors],
                3 if errors else 0)


def triage_attempt(aid, prev=None, fresh=False, no_backlog=False):
    """TRIAGE.md for one attempt. Returns (data, markdown lines, errors); hk boot / hk cycle call it when a boot ends."""
    errors = []
    me, m = attempt_facts(aid, errors, fresh)
    prev_id = prev or previous_same_family(aid)
    prev = d = None
    if prev_id:
        prev, _ = attempt_facts(prev_id, errors, fresh)
        d = diff_facts(prev, me)
    tdir = attempt_dir(aid) / 'triage'
    tdir.mkdir(parents=True, exist_ok=True)
    backlog = None if no_backlog else run_backlog(m, tdir, errors)
    image_probes = image_probe_rows(m, errors, fresh)
    tl = boot_events(m)
    new_sigs = {x['sig'] for x in (d or {}).get('crashes', {}).get('new', [])} if d else None
    open_c = [c for c in me['crashes'] or [] if 'open' in str(c.get('status') or '') or c.get('status') is None]
    probes = me['probes'] or []
    works = [p['id'] for p in probes if p['verdict'] == 'works']
    regress = [p for p in (d or {}).get('probes', []) if p['a'] in ('works', 'partial') and p['b'] not in ('works', 'partial')]
    gains = [p for p in (d or {}).get('probes', []) if p['b'] == 'works' and p['a'] != 'works']
    end = (me.get('end') or {}).get('line') or '-'
    L = [f"# Triage {aid}", '',
         f"- image {me['image'] or '-'}; verdict {me['verdict'] or '-'}; reader {me['reader'] or '-'}; ui {me['ui'] or '-'}",
         f"- end: {end}", f"- evidence: {me['source'] or 'none'} ({me['clock']}); previous same-family boot: {prev_id or 'none'}",
         f"- markers: {' '.join(me['markers']) or '-'}"]
    if me['physical']:
        phys = [e for e in tl['events'] if e['kind'] == 'physical']
        L.append(f"- PHYSICAL input during the boot: {me['physical']} touch/button events (first {phys[0]['wall'] or phys[0]['t']}): "
                 'UI results after it are not the script\'s alone')
    L += ['', '## Crashes', '']
    if me['crashes'] is None:
        L.append('- crashdoc unavailable (see errors)')
    for c in me['crashes'] or []:
        tag = ' **NEW**' if new_sigs is not None and c['sig'] in new_sigs else ''
        L.append(f"- {c.get('count') or '?'}x `{c['sig']}` {c.get('loc') or ''} [{c.get('hint') or 'no known cause'}] "
                 f"{(c.get('status') or '')[:60]}{tag}")
    if me['crashes'] == []:
        L.append('- none')
    if d and d['crashes']['gone']:
        L.append('- gone since ' + prev_id + ': ' + ', '.join(f"`{x['sig']}`" for x in d['crashes']['gone']))
    L += ['', '## Probes', '', f"- works ({len(works)}): {' '.join(works) or '-'}"]
    if d:
        L.append('- regressions vs previous: ' + (', '.join(f"{p['id']} {p['a']}->{p['b'] or '-'}" for p in regress) or 'none'))
        L.append('- newly working: ' + (', '.join(p['id'] for p in gains) or 'none'))
    if image_probes:
        L += ['', f"## Image probes ({image_probes['probes']})", '']
        L += [f"- {(r['verdict'] or '-'):<8} {r['id']}: {r['row'] or ''}" for r in image_probes['rows'] or []]
        if image_probes['rows'] == []:
            L.append('- no rows')
    if me['respawns']:
        L += ['', '## Respawns (exec count)', '', '- ' + ', '.join(f'{p} {n}' for p, n in me['respawns'].items())]
    if d:
        L += ['', f'## Diff vs {prev_id}', '', '```'] + diff_text(prev, me, d) + ['```']
    if backlog:
        hot = {p['id'] for p in regress} | {p['id'] for p in probes if p['verdict'] == 'partial'}

        def rank(i):
            iid = str(i.get('id'))
            r = 0 if iid.startswith('crash:') else 1 if iid.startswith('probe:') and iid[6:] in hot else \
                2 if iid.startswith('finding:') else 3
            return r, {'high': 0, 'med': 1, 'low': 2}.get(i.get('severity'), 3), iid

        def nxt_text(n):
            return (n.get('test') or '-') if isinstance(n, dict) else (n or '-')
        items = sorted((i for i in backlog if isinstance(i, dict)), key=rank)
        L += ['', '## Backlog: this boot\'s crashes, its partial or regressed probes, then findings (all: triage/BACKLOG.md)', '']
        L += [f"- [{i.get('severity')}] {i.get('id')}: {i.get('title')} — owner {i.get('owner') or 'UNASSIGNED'}; "
              f"next: {str(nxt_text(i.get('next')))[:200]}" for i in items if rank(i)[0] < 3][:15]
    nxt = []
    for c in open_c[:5]:
        proc = c.get('proc') or (str(c['sig']).split(':')[1].split('@')[0] if ':' in str(c['sig']) else None)
        if proc and proc != 'kernel':
            nxt.append(f"hk logs {proc} --attempt {aid}   # then hk stacks {proc} (needs hk_ustack={proc} in the image)")
    if regress:
        nxt.append(f"hk probe {' '.join(p['id'] for p in regress)} --attempt {aid} --verbose")
    nxt.append(f"hk timeline {aid} --kind crash,physical,ui,milestone")
    L += ['', '## Next', ''] + [f'- `{x}`' for x in dict.fromkeys(nxt)]
    if errors:
        L += ['', '## Errors', ''] + [f"- {e['message']}" for e in errors]
    md = attempt_dir(aid) / 'TRIAGE.md'
    md.write_text('\n'.join(L) + '\n')
    data = dict(attempt=aid, prev=prev_id, triage_md=str(md), facts={k: v for k, v in me.items() if k != 'subsystems'},
                diff=d, image_probes=image_probes, backlog=(backlog or [])[:50], errors=errors)
    return data, L, errors


SCHEMAS = {
    'error': 'ok=false, error ("tool not present" (reason tool_missing)|phone_busy|lock_required|not_holder|no_attempt|no_image|no_log|no_live_run|shell_down|'
             'unsupported|wrong_state|fastboot_failed|usage|...), message, code (exit status), plus context (tool, path, owner, lease)',
    'state': 'state (android|fastboot|ios-live|shim|recovery|absent, or unknown|skipped), how (the evidence), '
             'phone (android|recovery|android-unauthorized|android-offline|fastboot|ios|shim|usb-google|off-or-unknown|unknown|skipped), '
             'phone_detail, ios_shell (bool|null), lease {state, lease}, installed_boot_b (recorded), live_run, live_sock, recent[], queue{}',
    'lock': 'state (free|held|expired|stale), lease {holder, purpose, host, pid, pid_bound, acquired, expires, remaining_s, attempt, '
            'reclaimed_from}, token + inherited + reclaimed_from (acquire), holds + by (token|name) (check)',
    'status': 'attempt, dir, name, image, features[], verdict, rc, reader, end, ui, return_check, milestones {markers[], probes{id: '
              'verdict}}, probes {id: verdict}, probe_counts{}, crashes[], crashes_json, paths, errors[]',
    'boot': 'attempt, dir, rc, result, paths', 'cycle': 'attempt, dir, rc, result, paths',
    'back': 'attempt, verdict (return-check verdict), steps[], dir',
    'to-fastboot': 'start (as hk.state state), how, state (final), action (none|usbcon reset op (socket|reader)|adb reboot '
                   'bootloader, joined by then), ramdump_kept (bool|null), steps[]; errors owner_action|transient|reset_not_armed|'
                   'reset_unknown|reader_busy|not_fastboot|bridge_down',
    'ui': 'attempt, live_run, rc, verdict, report (the UI runner JSON)', 'shot': 'attempt, mode (live|dump), png, rc, out',
    'logs': 'attempt, source, split, file, total, lines[]', 'stacks': 'mode (dump|live), attempt, proc, rc, lines[] | stdout, exit',
    'crash': 'attempt, inputs[], rc, out, signatures[{proc, kind, loc, count, status, hint}], crashes_json, crashes_md',
    'shell': 'cmd, stdout, exit (null for builtins), banner', 'push': 'local, remote, bytes, sha256, verified, reply',
    'restart': 'daemon, old_pids[], new_pids[], respawned', 'probe': 'attempt, row, rows_asked[], inputs[], rc, verdict (one row), counts{}, rows[{id, row, verdict, milestone, '
             'phone_only, attempt, evidence[], next}]',
    'report': 'attempt, manifest, probes{}, screens[], report_md', 'images': 'images[{name, dir, sha256, kernel_sha256, kind, '
              'bootable, installable, cpus, deadline, overlay, features[], built, attempts[]}]',
    'find': 'count, attempts[hk.index records]', 'ingest': 'imported, items[{path, attempt, new | error}], updated[], skipped[]',
    'queue': 'item | items[], counts{} | ran[]', 'qemu': 'attempt, rc, verdict, result', 'tools': 'tools[{key, path, present, owner, what, argv}]',
    'note': 'attempt, owner_actions[]', 'installed': 'image, readback, when, by, source',
    'manifest': 'attempts/<id>/manifest.json: id, name, kind (phone|qemu), created, created_t, created_by, agent, command[], '
                'queue_id, image {name, dir, sha256, kernel_sha256, kind, cmdline, deadline, overlay, features}, kernel {mach, sha256}, '
                'cmdline, features[], git {m1box {rev, dirty_tracked}}, owner_actions[{t, by, text}], paths {runner, live, cycle, '
                'ramdump, qemu}, result {rc, verdict, markers[], end {kind, seconds, line}, park, ui, return_check, '
                'crash_signatures[]}, updated',
    'index': 'attempts/index.jsonl, append-only, last line per id wins: id, name, kind, created, created_t, image, image_sha256, '
             'kernel_sha256, features[], verdict, rc, end, crashes, return_check, ui, queue_id, dir, paths',
    'lease': '/tmp/fleet/hk-phone.lease.json; events in /tmp/fleet/hk-phone.events.jsonl',
    'timeline': 'attempt, source (live|dump), clock, total, events[{t, wall, src, kind (panic|deadline|crash|physical|input|exec|'
                'stall|milestone|ui), text}], respawns{proc: exec count}, file (attempts/<id>/timeline.txt)',
    'diff': 'a, b, head{field: {a, b}}, markers{only_a, only_b}, probes[{id, a, b}], crashes{new[], gone[], changed[]}, '
            'respawns[{proc, a, b}], subsystems[{file, a, b}], timeline[{event, a, b, delta}], crash_lines{a, b}, errors[]',
    'triage': 'attempt, prev, triage_md, facts{verdict, end, markers, first{event: t}, respawns, physical, probes[], crashes[]}, '
              'diff (as hk.diff, null without a previous boot), image_probes{probes, rule, rows[]} (null: no image probe file), '
              'backlog[], errors[]',
    'boot': 'attempt, dir, rc, result, paths, auto (null with --no-auto) {shots[{name, t, png, ok, rc}], notes[], dump_shot, '
            'triage{md, prev, errors[]}}; also attempts/<id>/auto.json and screens/auto.jsonl',
    'probes': 'with IMAGE: image, attempt, inputs[], results[{probes, rule, rc, counts{verdict: n}, rows[] (as hk.probe), raw}]; '
              '--list: image, files[{probes, images[], title|rule}]',
    'watch': 'live, attempt, name, state (running|stale|ended), elapsed_s, console_lines, console_bytes, console_age_s, last_line, '
             'milestones[{name, t, detail}], missing[], ui_run, crashes[{proc, count}], respawns{proc: n}, counts{physical, '
             'input, stall}, top{t, frames, cpu_ms, wall, procs[{proc, pid, ms}]}, end{kind, line}, probes_file, probes[] | '
             '{error}, pictures[], html',
}


def cmd_schema(args):
    keys = [args.name] if args.name else list(SCHEMAS)
    for k in keys:
        if k not in SCHEMAS:
            raise HkError(2, 'usage', f'no schema {k}; have {", ".join(SCHEMAS)}')
    return emit(args, 'schema', {k: SCHEMAS[k] for k in keys}, [f'hk.{k}/{VERSION}: {SCHEMAS[k]}' for k in keys])


# ------------------------------------------------------------------------------------------------------------- argparse

def parser():
    p = argparse.ArgumentParser(prog='hk', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--json', action='store_true', help='one JSON document on stdout')
    common.add_argument('--holder', help='lease holder name (default HK_HOLDER or user@host:pid)')
    common.add_argument('--lock-wait', type=float, default=0, help='wait up to S seconds for the phone lease')
    common.add_argument('--lock', metavar='NAME', help='phone lease holder name (default HK_LOCK): device commands refuse '
                        'without it or HK_LOCK_TOKEN; held by NAME = inherited, free = taken for the command')
    sp = p.add_subparsers(dest='cmd', required=True)

    def add(name, fn, help, aliases=()):
        q = sp.add_parser(name, parents=[common], help=help, aliases=list(aliases))
        q.set_defaults(fn=fn)
        return q

    q = add('state', cmd_state, 'phone state, lease, installed boot_b, live run, recent attempts')
    q.add_argument('--no-phone', action='store_true', help='do not ask the bridge (records only)')
    q.add_argument('--last', type=int, default=5)
    q = add('to-fastboot', cmd_to_fastboot, 'bring the phone to fastboot from any state (android: adb; ios-live: usbcon reset '
            'op, RAM kept; absent: what the owner does)')
    q.add_argument('--wait', type=float, default=150, help='seconds to wait for fastboot after each action (default 150)')
    q = add('lock', cmd_lock, 'the phone lease (one owner of the device and usbcon)')
    q.add_argument('lock_cmd', choices=['status', 'acquire', 'check', 'renew', 'release', 'break'])
    q.add_argument('name', nargs='?', help='holder name (acquire/check/renew/release); default --lock, HK_LOCK, HK_HOLDER')
    q.add_argument('--ttl', type=int, default=DEFAULT_TTL)
    q.add_argument('--purpose')
    q.add_argument('--token')
    q.add_argument('--wait', type=float, default=0)
    q.add_argument('--reason')
    q.add_argument('--force', action='store_true')
    for name, aliases in (('boot', ['live']),):
        q = add(name, cmd_boot, 'live boot via tools/live_boot.sh, into attempts/<id>/', aliases)
        q.add_argument('image')
        q.add_argument('--name')
        q.add_argument('--mach')
        q.add_argument('--wait', type=int, default=1200)
        q.add_argument('--sync-tools', action='store_true')
        q.add_argument('--no-console', action='store_true')
        q.add_argument('--ui-test', action='store_true')
        add_auto_args(q, 120)
    q = add('cycle', cmd_cycle, 'one full unattended cycle via tools/hk_cycle.py')
    q.add_argument('image')
    q.add_argument('--name')
    q.add_argument('--mach')
    q.add_argument('--ui')
    q.add_argument('--expect')
    q.add_argument('--deadline-wait', type=int)
    q.add_argument('--end-on', metavar='REGEX', help='hk_cycle --end-on: end the boot at the first matching console line')
    q.add_argument('--end-grace', type=float, metavar='S')
    q.add_argument('--end-after', type=float, metavar='S', help='hk_cycle --end-after: end S seconds after Home')
    q.add_argument('--end-on-idle', type=float, metavar='S', help='hk_cycle --end-on-idle')
    add_auto_args(q, 0)
    q.epilog = ('arguments after -- go to hk_cycle.py unchanged. hk takes the UI_READY picture and triages; '
                'the periodic pictures are hk_cycle\'s own (-- --shot-every S / --no-shots)')
    q = add('back', cmd_back, 'return to Android and run the return check')
    q.add_argument('--attempt')
    q = add('ui', cmd_ui, 'run a UI script on the live boot (tools/ui_run.py; "settings" = ui_settings_test.py)')
    q.add_argument('script')
    q.add_argument('--run', help='live_boot run dir (default: the running one)')
    q.add_argument('--check', action='store_true', help='only parse the script (no phone, no lease)')
    q = add('shot', cmd_shot, 'screenshot: live (usbcon snapshot) or --dump (HKSCR1 from the ramdump)')
    q.add_argument('--dump', action='store_true')
    q.add_argument('--attempt')
    q.add_argument('--run')
    q.add_argument('--name')
    q.add_argument('--step', type=int, default=6)
    q.add_argument('--allow-stale', action='store_true')
    q.add_argument('-o', '--output', help='PNG path (default attempts/<id>/screens/NAME-HHMMSS.png)')
    q = add('logs', cmd_logs, 'console lines: per HKL program (OBS mirror), subsystem, regex')
    q.add_argument('proc', nargs='?')
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir instead of --attempt (imported into the index)')
    q.add_argument('--sub', help='hklog subsystem: wifi bt net usb apps location proc status panic launchd display input power security other')
    q.add_argument('--grep')
    q.add_argument('--tail', type=int, default=200)
    q.add_argument('--live', action='store_true')
    q.add_argument('--run')
    q.add_argument('--source', choices=['dump', 'live'], default='dump')
    q = add('stacks', cmd_stacks, 'user stacks of a process (hk_ustack in the dump, or spindump over the shell)')
    q.add_argument('proc')
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir instead of --attempt')
    q.add_argument('--full', action='store_true')
    q.add_argument('--live', action='store_true')
    q.add_argument('--live-cmd', default='spindump {proc} 2 -stdout')
    q = add('crash', cmd_crash, 'crash census via tools/crashdoc.py', ['crashes'])
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir instead of --attempt (imported into the index)')
    q.add_argument('--since')
    q.add_argument('--all', action='store_true')
    q.add_argument('--feature')
    q.add_argument('--no-symbols', action='store_true')
    q = add('shell', cmd_shell, 'run one command in the iOS root shell (hk_shell over the USB network)')
    q.add_argument('--timeout', type=int, default=60)
    q.add_argument('command', nargs=argparse.REMAINDER)
    q = add('push', cmd_push, 'copy a file to /private/var on the running iOS (needs hk_shell put)')
    q.add_argument('local')
    q.add_argument('remote')
    q.add_argument('--mode', default='0644')
    q.add_argument('--timeout', type=int, default=120)
    q = add('restart', cmd_restart, 'kill a daemon so launchd respawns it (needs hk_shell kill)')
    q.add_argument('daemon')
    q.add_argument('--signal', default='TERM')
    q.add_argument('--wait', type=int, default=30)
    q = add('probe', cmd_probe, 'README-row verdicts via tools/probe_eval.py (docs/probes.yaml); all rows by default')
    q.add_argument('row', nargs='*', help='probe ids or README row names (default: all)')
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir (runner/live/hk_cycle/QEMU) instead of --attempt; imported into the index')
    q.add_argument('--qemu', action='store_true', help='skip phone_only probes')
    q.add_argument('--verbose', action='store_true', help='text: also rows with no verdict')
    q.add_argument('--live', action='store_true')
    q.add_argument('--run')
    q = add('probes', cmd_probes, "the image family's own probe file (int5.probes.yaml, sweep1.probes.yaml, ...) over its newest attempt")
    q.add_argument('image', nargs='?', help='image name or dir (a7-ios-system-int5), or an attempt name; none: --list')
    q.add_argument('--list', action='store_true', help='only show which probe files match (no evaluation)')
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir instead of the newest attempt of the image (imported into the index)')
    q.add_argument('--run', help='evaluate this live run dir only (a boot still running)')
    q.add_argument('--row', action='append', help='only these probe ids (repeatable)')
    q.add_argument('--qemu', action='store_true', help='skip phone_only probes')
    q.add_argument('--all-matches', action='store_true', help='every matching file, not only the best')
    q = add('report', cmd_report, 'one attempt as REPORT.md + JSON')
    q.add_argument('attempt', nargs='?')
    q = add('status', cmd_status, 'summary of the newest run (or --attempt/--path): milestones, probes, crashes')
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir (imported into the index)')
    q.add_argument('--no-probe', action='store_true')
    q.add_argument('--no-crash', action='store_true', help='do not run crashdoc when no census is cached')
    q = add('timeline', cmd_timeline, 'one boot as time-ordered events: milestones, UI steps, input, physical touches, crashes, panics')
    q.add_argument('attempt_pos', nargs='?', metavar='ATTEMPT')
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir (imported into the index)')
    q.add_argument('--kind', help='comma list: milestone,ui,input,physical,crash,panic,deadline,exec,stall')
    q.add_argument('--grep')
    q.add_argument('--since-t', type=float, help='only events at t >= S')
    q.add_argument('--until-t', type=float, help='only events at t <= S')
    q.add_argument('--limit', type=int, default=0, help='last N events')
    q = add('diff', cmd_diff, 'two boots side by side: probe verdicts, crash census, respawns, subsystem lines, timeline')
    q.add_argument('a', metavar='A', help='the older attempt (with no B: the newer one, against its previous same-family boot)')
    q.add_argument('b', metavar='B', nargs='?')
    q.add_argument('--fresh', action='store_true', help='re-run probe_eval and crashdoc instead of using cached results')
    q.add_argument('--no-subsystems', action='store_true', help='skip the hklog split (faster)')
    q = add('triage', cmd_triage, 'crashdoc + probe_eval + diff vs the previous same-family boot + backlog -> TRIAGE.md')
    q.add_argument('attempt_pos', nargs='?', metavar='ATTEMPT')
    q.add_argument('--attempt')
    q.add_argument('--path', help='a run dir (imported into the index)')
    q.add_argument('--prev', help='compare with this attempt instead of the previous same-family boot')
    q.add_argument('--fresh', action='store_true')
    q.add_argument('--no-backlog', action='store_true')
    q = add('watch', cmd_watch, 'live dashboard of a running boot: milestones, crashes, respawns, HK TOP, probe rows, latest picture')
    q.add_argument('attempt_pos', nargs='?', metavar='ATTEMPT', help='default: the running live boot, else the newest attempt')
    q.add_argument('--attempt')
    q.add_argument('--run', help='a live_boot run dir')
    q.add_argument('--once', action='store_true', help='one frame and exit (--json implies it)')
    q.add_argument('--interval', type=float, default=2.0, help='seconds between frames (default 2)')
    q.add_argument('--probe-every', type=float, default=20.0, help='re-run the probe file at most this often (default 20 s)')
    q.add_argument('--no-probe', action='store_true')
    q.add_argument('--html', nargs='?', const='', metavar='PATH', help='also write a self-refreshing HTML page '
                   '(default attempts/<id>/watch.html)')
    q.add_argument('--max-s', type=float, default=0, help='stop after S seconds (default: when the boot ends)')
    q = add('note', cmd_note, 'record an owner action on an attempt')
    q.add_argument('attempt')
    q.add_argument('text', nargs='+')
    q = add('images', cmd_images, 'built images, their features and attempts')
    q.add_argument('--feature')
    q.add_argument('--name')
    q.add_argument('--cmdline', action='store_true')
    q = add('find', cmd_find, 'query attempts/index.jsonl')
    for o in ('--feature', '--since', '--until', '--image', '--name', '--verdict', '--crash'):
        q.add_argument(o)
    q.add_argument('--kind', choices=['phone', 'qemu'])
    q.add_argument('--limit', type=int, default=0)
    q = add('ingest', cmd_ingest, 'import existing runner/live/cycle/QEMU run dirs into the index')
    q.add_argument('paths', nargs='*')
    q.add_argument('--all', action='store_true')
    q.add_argument('--since')
    q.add_argument('--verbose', action='store_true')
    q = add('installed', cmd_installed, 'record what boot_b holds (a record; hk never reads or writes boot_b)')
    q.add_argument('image')
    q.add_argument('--readback', required=True)
    q.add_argument('--when')
    q.add_argument('--source', default='owner')
    q = add('queue', cmd_queue, 'shared phone queue: add, list, show, admit, cancel, run')
    q.add_argument('queue_cmd', choices=['add', 'list', 'show', 'admit', 'cancel', 'run'])
    q.add_argument('image', nargs='?')
    q.add_argument('ui', nargs='?')
    q.add_argument('expect', nargs='?')
    q.add_argument('--mach')
    q.add_argument('--name')
    q.add_argument('--mode', choices=['cycle', 'boot'], default='cycle')
    q.add_argument('--deadline-wait', type=int)
    q.add_argument('--note')
    q.add_argument('--admit', action='store_true', help='admitted at once (phone owner / coordinator only)')
    q.add_argument('--all', action='store_true')
    q.add_argument('--once', action='store_true')
    q.add_argument('--follow', action='store_true', help='keep running, polling for admitted items')
    q.add_argument('--poll', type=float, default=30)
    q.add_argument('--no-back', action='store_true')
    q = add('qemu', cmd_qemu, 'QEMU preflight of an image via tools/qemu_preflight.py')
    q.add_argument('image')
    q.epilog = 'arguments after -- go to qemu_preflight.py unchanged'
    add('tools', cmd_tools, 'wrapped tools: present or not yet')
    q = add('schema', cmd_schema, 'JSON schemas')
    q.add_argument('name', nargs='?')
    return p


PASSTHROUGH = ('cycle', 'qemu')       # commands whose arguments after -- go to the wrapped tool


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p = parser()
    extra = None
    if argv[:1] and argv[0] in PASSTHROUGH and '--' in argv:     # hk cycle IMAGE [hk options] -- [hk_cycle.py options]
        i = argv.index('--')
        argv, extra = argv[:i], argv[i + 1:]
    args = p.parse_args(argv)
    if args.cmd in PASSTHROUGH:
        args.extra = extra or []
    if args.cmd == 'queue':
        if args.queue_cmd == 'add' and not args.image:
            p.error('hk queue add IMAGE [UI] [EXPECT]')
        if args.queue_cmd in ('show', 'admit', 'cancel'):
            if not args.image:
                p.error(f'hk queue {args.queue_cmd} QID')
            args.qid = args.image
    for attr in ('extra', 'command'):
        v = getattr(args, attr, None)
        if isinstance(v, list):
            if v[:1] == ['--']:
                v = v[1:]
            while v and v[-1] == '--json':             # `hk shell ps --json`: the flag is hk's, not the phone's
                v = v[:-1]
                args.json = True
            setattr(args, attr, v)
    try:
        return args.fn(args)
    except HkError as e:
        data = dict(error=e.error, message=e.message, code=e.code, **e.extra)
        if getattr(args, 'json', False):
            print(json.dumps(dict(schema=f'hk.error/{VERSION}', ok=False, **data), indent=1, default=str))
        else:
            print(f'hk {args.cmd}: {e.message}', file=sys.stderr)
        return e.code
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
