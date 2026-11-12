#!/usr/bin/env python3
"""mactools: the Mac-side tools of the boot path as a versioned, hash-verified copy OUTSIDE the Mac checkout.

Why. The phone is on the Mac's USB, so tools/bootios, tools/usbcon.py, tools/hkq.py, tools/capture-fastboot.py and
tools/usb_log.py run there. They used to run from the Mac checkout, which sits on its own commit with its own uncommitted
edits: `mac repo` refuses to run a tool whose Mac copy differs from m1box's ("the Mac's tools/usbcon.py differs ... pass
--overwrite"), and --overwrite destroys the Mac's edits. Two boots were lost to that on 2026-11-11. Now m1box's copies go
to ~/.cache/hackios-tools/<id>/tools/ on the Mac, where <id> is the first 16 hex digits of the sha256 over the bundle's
"sha256  path" lines. A directory is never edited after it verifies: a changed tool gets a new <id>. The Mac checkout's
files are neither read nor written.

    python3 -I tools/mactools.py ensure            # install if needed, verify every file by sha256, print the Mac directory
    python3 -I tools/mactools.py ensure --json     # {"dir", "id", "files": {path: sha256}, "installed": [...], "pruned": [...]}
    python3 -I tools/mactools.py show              # the local bundle: id and file hashes; talks to nothing

Callers run `mac repo --force -- python3 -I <dir>/tools/usbcon.py ...` in the Mac checkout as before (attempt directories
and images stay there); a path outside the m1box checkout is passed through by `mac repo` untouched. tools/bootios run
from <dir> finds research/laguna-usb-fix/run-attempt.sh in the current directory (the Mac checkout).
A live run records the directory as LIVE_TOOLS in live.env, so every client of that reader (reset, screenshot, hkq, UI
input) speaks the reader's own version.

HK_MAC_TOOLS=<Mac dir> skips everything and uses that directory (test doubles; a hand-made copy).
HK_MACTOOLS_MAC=<path> is the `mac` command (default ~/.local/share/phone-bridge/bin/mac).
Exit: 0 ok; 3 the Mac cannot be reached; 4 a file would not verify after its copy.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
# Everything the boot path runs on the Mac from tools/. run-attempt.sh and what it calls stay the Mac checkout's (research/).
BUNDLE = ('tools/bootios', 'tools/usbcon.py', 'tools/hkq.py', 'tools/capture-fastboot.py', 'tools/usb_log.py')
REMOTE_BASE = '.cache/hackios-tools'        # relative to the Mac home
KEEP = 12                                   # bundle directories kept on the Mac (each about 100 KiB)
CHUNK = 60000                               # base64 characters per `part` call: far below any argv limit
EXIT_OK, EXIT_UNREACHABLE, EXIT_VERIFY = 0, 3, 4

# Runs on the Mac (python3 >= 3.8, no third-party module). argv: op base id ...; prints one JSON object.
INSTALLER = r'''
import base64, gzip, hashlib, json, os, shutil, sys, time
op, base, bid = sys.argv[1:4]
home = os.path.expanduser('~')
root = os.path.join(home, base, bid)
def sha(p):
    try:
        with open(p, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None
def inside(rel):
    p = os.path.normpath(os.path.join(root, rel))
    if not p.startswith(root + os.sep):
        raise SystemExit('path escapes the bundle: ' + rel)
    return p
if op == 'verify':
    files = dict((rel, sha(inside(rel))) for rel in sys.argv[4:])
    if os.path.isdir(root):
        os.utime(root, None)
    print(json.dumps(dict(dir=root, files=files)))
elif op == 'part':
    rel, token, n, data = sys.argv[4], sys.argv[5], int(sys.argv[6]), sys.argv[7]
    p = inside(rel) + '.part.' + token
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb' if n == 0 else 'ab') as f:
        f.write(base64.b64decode(data))
    print(json.dumps(dict(ok=True, part=n)))
elif op == 'commit':
    rel, token, want, mode = sys.argv[4], sys.argv[5], sys.argv[6], int(sys.argv[7], 8)
    p = inside(rel)
    part = p + '.part.' + token
    with open(part, 'rb') as f:
        packed = f.read()
    os.unlink(part)
    try:
        raw = gzip.decompress(packed)
    except Exception as exc:
        print(json.dumps(dict(ok=False, error='the copy is not intact: %s' % exc)))
        sys.exit(1)
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        print(json.dumps(dict(ok=False, error='sha256 %s, expected %s' % (got, want))))
        sys.exit(1)
    tmp = p + '.tmp.' + token
    with open(tmp, 'wb') as f:
        f.write(raw)
    os.chmod(tmp, mode)
    os.replace(tmp, p)
    print(json.dumps(dict(ok=True, sha256=got)))
elif op == 'prune':
    keep, top, gone = int(sys.argv[4]), os.path.join(home, base), []
    dirs = [d for d in os.listdir(top) if len(d) == 16 and all(c in '0123456789abcdef' for c in d) and os.path.isdir(os.path.join(top, d))]
    dirs.sort(key=lambda d: os.path.getmtime(os.path.join(top, d)), reverse=True)
    for d in dirs[keep:]:
        if d != bid and time.time() - os.path.getmtime(os.path.join(top, d)) > 86400:
            shutil.rmtree(os.path.join(top, d), ignore_errors=True)
            gone.append(d)
    print(json.dumps(dict(ok=True, pruned=gone)))
else:
    raise SystemExit('unknown op ' + op)
'''


class MacToolsError(Exception):
    def __init__(self, message, code=EXIT_VERIFY):
        super().__init__(message)
        self.code = code


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def bundle(root=ROOT, files=BUNDLE):
    """(id, {rel: sha256}) of the local bundle. Raises MacToolsError when a file is missing."""
    hashes = {}
    for rel in files:
        p = Path(root) / rel
        if not p.is_file():
            raise MacToolsError(f'{rel} is missing from {root}', EXIT_VERIFY)
        hashes[rel] = sha256(p)
    text = ''.join(f'{hashes[rel]}  {rel}\n' for rel in sorted(hashes))
    return hashlib.sha256(text.encode()).hexdigest()[:16], hashes


def default_mac():
    return os.environ.get('HK_MACTOOLS_MAC') or str(Path.home() / '.local/share/phone-bridge/bin/mac')


def _call(mac, op, bid, *args, timeout=60, env=None):
    """One installer call on the Mac (`mac -- CMD` is plain ssh: no stdin watchdog). Returns its JSON."""
    cmd = [mac, '--', 'python3', '-I', '-c', INSTALLER, op, REMOTE_BASE, bid, *[str(a) for a in args]]
    try:
        p = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise MacToolsError(f'the Mac did not answer the {op} call within {timeout} s', EXIT_UNREACHABLE)
    except OSError as exc:
        raise MacToolsError(f'cannot run {mac}: {exc}', EXIT_UNREACHABLE)
    line = next((l for l in reversed(p.stdout.splitlines()) if l.startswith('{')), '')
    try:
        return json.loads(line)
    except ValueError:
        tail = (p.stderr.strip() or p.stdout.strip() or 'no output').splitlines()[-1][:300]
        raise MacToolsError(f'{op} on the Mac failed (rc {p.returncode}): {tail}',
                            EXIT_UNREACHABLE if op == 'verify' else EXIT_VERIFY)


def ensure(mac=None, root=ROOT, files=BUNDLE, timeout=60, env=None, keep=KEEP):
    """Install the bundle on the Mac if any file is missing or different, verify every file, return
    {'dir': absolute Mac directory, 'id', 'files', 'installed', 'pruned'}. Raises MacToolsError."""
    preset = (env or os.environ).get('HK_MAC_TOOLS')
    if preset:
        return dict(dir=preset.rstrip('/'), id='preset', files={}, installed=[], pruned=[], preset=True)
    mac = mac or default_mac()
    bid, hashes = bundle(root, files)
    rels = sorted(hashes)
    seen = _call(mac, 'verify', bid, *rels, timeout=timeout, env=env)
    todo = [rel for rel in rels if seen['files'].get(rel) != hashes[rel]]
    token = f'{os.getpid()}-{os.urandom(4).hex()}'
    for rel in todo:
        p = Path(root) / rel
        data = base64.b64encode(gzip.compress(p.read_bytes(), mtime=0)).decode()
        for n, off in enumerate(range(0, max(len(data), 1), CHUNK)):
            _call(mac, 'part', bid, rel, token, n, data[off:off + CHUNK], timeout=timeout, env=env)
        mode = '555' if os.access(p, os.X_OK) else '444'
        r = _call(mac, 'commit', bid, rel, token, hashes[rel], mode, timeout=timeout, env=env)
        if not r.get('ok'):
            raise MacToolsError(f'{rel}: the Mac copy did not verify: {r.get("error")}')
    if todo:
        seen = _call(mac, 'verify', bid, *rels, timeout=timeout, env=env)
        bad = [rel for rel in rels if seen['files'].get(rel) != hashes[rel]]
        if bad:
            raise MacToolsError(f'after the copy the Mac still has other bytes for: {", ".join(bad)} (in {seen.get("dir")})')
    pruned = []
    if todo:
        try:
            pruned = _call(mac, 'prune', bid, keep, timeout=timeout, env=env).get('pruned', [])
        except MacToolsError:
            pass                    # housekeeping only
    return dict(dir=seen['dir'], id=bid, files=hashes, installed=todo, pruned=pruned)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('command', choices=('ensure', 'show'))
    p.add_argument('--mac', help='the phone-bridge `mac` command')
    p.add_argument('--json', action='store_true')
    p.add_argument('--timeout', type=float, default=60)
    a = p.parse_args(argv)
    try:
        if a.command == 'show':
            bid, hashes = bundle()
            if a.json:
                print(json.dumps(dict(id=bid, files=hashes, remote=f'~/{REMOTE_BASE}/{bid}'), indent=1))
            else:
                print(f'{bid}  ~/{REMOTE_BASE}/{bid}')
                for rel in sorted(hashes):
                    print(f'{hashes[rel]}  {rel}')
            return EXIT_OK
        r = ensure(a.mac, timeout=a.timeout)
    except MacToolsError as exc:
        print(f'mactools: {exc}', file=sys.stderr)
        return exc.code
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        if r['installed']:
            print(f"mactools: installed {', '.join(r['installed'])} in {r['dir']}", file=sys.stderr)
        print(r['dir'])
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
