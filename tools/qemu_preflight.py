#!/usr/bin/env python3
"""QEMU pre-flight for a phone image: run the closest rig equivalent of a built phone image and report regressions
(crash loop, missing daemon, overlay parse failure, panic) before a phone boot is spent. QEMU ONLY: it never touches the
phone and its results are QEMU results (TCG, 1 CPU, no Tensor hardware).

  qemu_preflight.py IMAGE_DIR [--seconds N] [--expect FILE ...] [--root IMG] [--keep TOKEN] [--drop KEY] [--dry]
  qemu_preflight.py IMAGE_DIR --analyze RUN_DIR [--expect FILE ...] [--baseline RUN_DIR]

IMAGE_DIR is a directory written by tools/image_tool.py (a7-ios-system-*) or tools/chooser_ios_image.py (chooser-ios-*;
its iOS branch is followed to the image it embeds). Derivation, all recorded in RUN_DIR/preflight.json:
  kernel   the file whose sha256 equals the manifest's `mach` (the same XNU build the payload carries). The phone build
           boots on the rig as is (mkadt --qemu ADT; rig runs aud1-q-r1, cfg1-qemu-*, s2-sens2-* used phone kernels),
           so nothing is rebuilt; if no file matches, the tool stops and names the hash to build.
  overlay  manifest var_overlay, sha256 checked.
  root     the bytes flashed to ios_system (research/ios26-root-r1/build-r3/ios26-phone-r3.img on the rig), mapped as
           the UFS fake LUN (blazer_ufs_fake=PA blazer_ufs_fake_size=N, added by the harness) instead of the real LUN.
  line     the image's cmdline translated: route/cpus/console tokens come from the harness, QEMU-proven tokens are kept,
           phone-hardware and unproven tokens are dropped and listed, observability tokens are added (listed).
Then research/ios26-apps-r1/tools/qemu-ufsroot.py runs it for N host seconds (TCG, shared slot lock; HACKIOS_QEMU_SLOTS
caps the number of guests on the host, default 3) and the console is analysed: milestones, exec/respawn counts per
daemon, crash events, panics, the overlay records applied, and the expect.yaml patterns.

expect file: the shared probe rows (VERIFY docs/probes.yaml schema, evaluated by tools/probe_eval.py; until that exists by
HARNESS's tools/hk_cycle.py evaluate(), same rows): id, feature, need/any/forbid (regex lists), values ({re, agg, min, max}),
required, note, source. Rows with phone_only: true (or ui/needs_input) are listed as PHONE_ONLY and not evaluated in QEMU;
if_arg: TOKEN rows are N/A unless the QEMU line holds TOKEN. Top-level respawn_max / respawn_allow bound the per-daemon
respawns (exec count - 1). Default file tools/qemu_preflight.expect.yaml; IMAGE_DIR/expect.yaml is added when present.
Exit status: 0 PASS, 1 FAIL (a finding or an expect item failed), 2 setup error.
"""
import argparse, glob, hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path
sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parent.parent
RIG = Path(os.environ.get('HACKIOS_QEMU_RIG', '/data/hackios-qemu'))
HARNESS = RIG/'research/ios26-apps-r1/tools/qemu-ufsroot.py'
RUNS = RIG/'research/ios26-apps-r1/runs'
DEFAULT_ROOT = RIG/'research/ios26-root-r1/build-r3/ios26-phone-r3.img'
DEFAULT_EXPECT = REPO/'tools/qemu_preflight.expect.yaml'
SLOTS_CAP = 6

# Tokens the harness writes itself (qemu-ufsroot.py ARGS): replaced, the phone value is reported.
HARNESS_OWNED = {'debug', 'serial', 'cpus', 'rd', 'blazer_ufs', 'blazer_ufs_live', 'blazer_ufs_root', 'blazer_ufs_lun',
                 'rootfstype', 'msgbuf', 'launchd_disable_all_timeouts', 'epoch', 'blazer_ufs_fake', 'blazer_ufs_fake_size'}
# Every key below appears in at least one rig run's intent.json (runs/*/intent.json, 2026-11-03): proven to boot in QEMU.
QEMU_PROVEN = {'autounlock', 'blazer_aks_usersession', 'blazer_aks_wrap', 'blazer_audio', 'blazer_audio_rt', 'blazer_deadline',
               'blazer_netstack', 'blazer_panic', 'blazer_persona_log', 'blazer_sensors', 'blazer_sensors_keep',
               'blazer_sensors_mag', 'hk_env', 'hk_fb_scanout', 'hk_overlay', 'hk_top', 'hk_ui_trace', 'hk_usertrace',
               'ignition_level', 'interrupt-masked-debug-mode', 'launchd_unsecure_cache', 'sched_preemption_disable_debug_mode',
               'sweetarm64e', 'sweetfb_hz', 'sweetfb_noconsole', 'unentitled_ios_sim_launch', 'varfs', 'wdt'}
# Software-only tokens not yet seen on the rig: kept (they are part of the recipe and touch no Tensor block), flagged.
SOFTWARE = {'atm_diagnostic_config': 'ATM diagnostics config (software)',
            'hk_ustack': 'user-stack sampler on process names (hk_ustack.c starts on names alone, INT1.md)'}
# Phone hardware: dropped. Prefix match on the key.
PHONE_ONLY = [('blazer_touch', 'touch controller (SPI/Laguna)'), ('blazer_ufs_multi', 'real UFS host queueing'),
              ('blazer_ufs_spin', 'real UFS host polling'), ('blazer_ufs_hold', 'real UFS link hold'),
              ('blazer_ufs_mountroot', 'phone md0 route'), ('blazer_ssbs', 'Tensor CPU SSBS errata'),
              ('hk_fb_scale', 'DPU scaler'), ('hk_fb_fast', 'DPU fast path'), ('hk_fb_refresh', 'DPU refresh'),
              ('hk_fb_probe', 'DPU probe'), ('blazer_battery', 'fuel gauge / PMIC'), ('blazer_mem', 'phone DRAM map'),
              ('blazer_thermal', 'Tensor thermal sensors'), ('blazer_gov', 'Tensor DVFS governor'),
              ('blazer_usbcon', 'DWC3 USB gadget console'), ('blazer_rtc', 'PMIC RTC'), ('hk_bright', 'panel backlight / DCS'),
              ('blazer_keys', 'GPIO volume keys'), ('blazer_power_key', 'PMIC power key'), ('blazer_key_delivery', 'key HID delivery (needs blazer_keys)'),
              ('blazer_haptic', 'haptics driver (CS40L)'), ('blazer_bootcpu', 'phone boot cluster id'), ('blazer_gpu', 'Mali GPU'),
              ('blazer_wifi', 'BCM4390 PCIe'), ('blazer_usbnet', 'USB network gadget'), ('blazer_bt', 'Bluetooth UART'),
              ('blazer_persist', 'ios_data persist needs a GPT fake LUN (--root fakelun image, --keep)'),
              ('blazer_ufs_fake_lun', 'GPT fake LUN (--root fakelun image, --keep)')]
# Added for QEMU observability (research/ios26-apps-r1/usersession/tools/runq.sh TAIL): crash decode, CPU top, no watchdog.
QEMU_ADD = ['sched_preemption_disable_debug_mode=0', 'wdt=-1', 'hk_usertrace=1', 'hk_top=30']

PANIC = re.compile(r'panic\(cpu|Debugger message|Please go to|Synchronous exception|kernel trap|halt_all_cpus|Waiting for root')
DEADLINE = re.compile(r'blazer-root: deadline (\d+) s')
EXEC = re.compile(r'(?:^|[^\w\n])exec ([\w.+-]+)[ \t]*$')
USERTRAP = re.compile(r'usertrap: ([\w.+ -]+?)\[(\d+)\] exception (\d+)')
USERABORT = re.compile(r'userabort: ([\w.+ -]+?)\[(\d+)\] aborts')
CRASH = re.compile(r'CRASH ([\w.+-]+) reason ns (\d+) code (\S+)')
LEXIT = re.compile(r'\(([^ )]+)(?: \[(\d+)\])?\) <Notice>: exited due to ([^,|]+)')
OVL_MASK = re.compile(r'varfs-overlay: mask (0x[0-9a-f]+) of groups (0x[0-9a-f]+), (\d+) entries')
OVL_REC = re.compile(r'varfs-overlay: ([fdlc]) (\S+)')
OVL_APPLIED = re.compile(r'varfs-overlay: (\d+) applied')
OVL_BAD = re.compile(r'varfs-overlay: (bad overlay|hk_overlay=0x[0-9a-f]+ (?:needs|and no|, this overlay))')
HKTOP = re.compile(r'HK TOP: t=(\d+) frames\+(\d+)')
MULTI_OK = {'xpcproxy'}   # one exec per XPC launch by design

# Milestones in boot order. QEMU proxies for the phone's Home: TCG draws no Home frame (apps PLAN r21-r25: fb-final is the
# Apple logo), so "Home equivalent" = the phone's Home-time daemons up (home-budget BUDGET.md section 4) and UI stable.
MILESTONES = [('kernel', 'XNU arm_init', r'TEGU-XNU EARLY 1:'),
              ('root', 'root mounted, pid 1 exec', r'blazer-root: stage t \d+ ms stage pid1_exec'),
              ('overlay', 'var overlay applied', r'varfs-overlay: \d+ applied'),
              ('launchd', 'launchd', r'(?:^|[^\w\n])exec launchd[ \t]*$'),
              ('usermanagerd', 'boot tasks: usermanagerd', r'(?:^|[^\w\n])exec usermanagerd[ \t]*$'),
              ('backboardd', 'backboardd', r'(?:^|[^\w\n])exec backboardd[ \t]*$'),
              ('SpringBoard', 'SpringBoard', r'(?:^|[^\w\n])exec SpringBoard[ \t]*$'),
              ('display', 'SWEET FB display on', r'SWEET FB: display on'),
              ('PosterBoard', 'PosterBoard (phone: first frame ~10 s)', r'(?:^|[^\w\n])exec PosterBoard[ \t]*$'),
              ('iconservicesagent', 'iconservicesagent (phone: Home-time)', r'(?:^|[^\w\n])exec iconservicesagent[ \t]*$')]
HOME_NEEDS = ['launchd', 'backboardd', 'SpringBoard', 'PosterBoard', 'iconservicesagent']
UI_STABLE = ['backboardd', 'SpringBoard']


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''): h.update(b)
    return h.hexdigest()


def die(msg, code=2):
    print(f'qemu_preflight: {msg}', file=sys.stderr); sys.exit(code)


# ---------------------------------------------------------------- image -> recipe
def load_image(d):
    d = Path(d).resolve(); m = json.loads((d/'manifest.json').read_text()); info = {'dir': str(d), 'name': m.get('name', d.name)}
    if m.get('kind') == 'chooser-ios':
        ios = m['ios']; info.update(chooser=True, default_entry=m.get('default_entry'), chooser_image=m.get('image'))
        sub = Path(ios['dir'])
        if not sub.is_dir(): sub = REPO/'research/images'/ios['name']
        im = json.loads((sub/'manifest.json').read_text())
        if im.get('image') != ios.get('image') or im.get('cmdline') != ios.get('cmdline'):
            die(f"chooser {d.name}: embedded iOS image {ios.get('image', '?')[:12]} does not match {sub}/manifest.json")
        info['ios_dir'] = str(sub); m = im
    for k in ('mach', 'cmdline'):
        if not m.get(k): die(f'{d}: manifest has no {k!r}; not an image_tool phone image')
    info.update(image=m.get('image'), mach=m['mach'], cmdline=m['cmdline'], var_overlay=m.get('var_overlay'), route=m.get('route'),
                phone_root=m.get('phone_root'), cpus=m.get('cpus'))
    return info


def kernel_candidates():
    roots = [REPO/'research', RIG/'research']; skip = {'runs', '.git', 'xnu', 'xnu-src', 'obj', 'work', 'ramdump', 'artifacts', 'images'}
    pat = re.compile(r'^kernel[\w.+-]*$')
    for r in roots:
        for dp, dn, fn in os.walk(r):
            dn[:] = [x for x in dn if x not in skip]
            for f in fn:
                if pat.match(f) and not f.endswith('.unstripped'):
                    p = Path(dp)/f
                    try:
                        if p.stat().st_size > 8 << 20: yield p
                    except OSError: pass


def find_kernel(want, hint=None):
    cache_p = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'hackios-qemu-preflight-kernels.json'
    try: cache = json.loads(cache_p.read_text())
    except (OSError, ValueError): cache = {}
    cands = ([Path(hint)] if hint else []) + list(kernel_candidates()); hit = None
    for p in cands:
        st = p.stat(); key = f'{p.resolve()}|{st.st_size}|{int(st.st_mtime)}'
        h = cache.get(key) or sha(p); cache[key] = h
        if h == want: hit = p.resolve(); break
    try: cache_p.parent.mkdir(parents=True, exist_ok=True); cache_p.write_text(json.dumps(cache))
    except OSError: pass
    return hit


def kernel_version(p):
    m = re.search(rb'Darwin Kernel Version [^\x00]{10,200}', Path(p).read_bytes())
    return m[0].decode('latin1') if m else None


def translate(cmdline, keep=(), drop=(), deadline=None, add=QEMU_ADD):
    """phone cmdline -> (qemu extra args, table). The harness supplies route, cpus and the fake LUN."""
    kept, rows, seen = [], [], set()
    for t in cmdline.split():
        k = t.split('=', 1)[0]; seen.add(k)
        if k in drop: rows.append((t, 'drop', 'dropped by --drop')); continue
        if k in HARNESS_OWNED: rows.append((t, 'harness', 'set by qemu-ufsroot.py (cpus=1, rd=ufsroot0 on the fake LUN)')); continue
        if k == 'blazer_deadline' and deadline:
            kept.append(f'blazer_deadline={deadline}'); rows.append((t, 'changed', f'blazer_deadline={deadline} (--deadline)')); continue
        if k in keep or t in keep: kept.append(t); rows.append((t, 'keep', 'kept by --keep')); continue
        if k in QEMU_PROVEN: kept.append(t); rows.append((t, 'keep', 'QEMU-proven')); continue
        if k in SOFTWARE: kept.append(t); rows.append((t, 'keep-new', SOFTWARE[k] + '; first use on the rig')); continue
        why = next((w for p, w in PHONE_ONLY if k.startswith(p)), None)
        rows.append((t, 'drop', f'phone-only: {why}' if why else 'not proven on the rig (unknown to the pre-flight; --keep to try)'))
    for t in add:
        k = t.split('=', 1)[0]
        if k not in seen and k not in drop: kept.append(t); rows.append((t, 'add', 'QEMU observability (runq.sh TAIL)'))
    return ' '.join(kept), rows


def harness_route(cmdline):
    a = dict(t.split('=', 1) for t in cmdline.split() if '=' in t)
    if a.get('rd') not in ('ufsroot0', 'md0'): die(f"route rd={a.get('rd')} has no rig equivalent")
    flags = []
    if a.get('rd') == 'md0' and a.get('blazer_ufs_mountroot') == '1': flags.append('--route-md')
    elif a.get('rd') == 'md0': die('rd=md0 ramdisk images are not phone-root images; run qemu-ufsroot.py --ramdisk-root by hand')
    flags += ['--ufs-root', a.get('blazer_ufs_root', 'ios_system')]
    return flags, a


# ---------------------------------------------------------------- analysis
def load_console(run):
    raw = (Path(run)/'console.log').read_bytes() if (Path(run)/'console.log').exists() else b''
    prog = []
    try:
        with open(Path(run)/'progress.txt') as pf:
            for l in pf:
                x = l.split()
                if len(x) >= 2: prog.append((float(x[0]), int(x[1])))
    except OSError: pass
    lines, off, j, out = raw.split(b'\n'), 0, 0, []
    for l in lines:
        off += len(l)+1
        while j < len(prog) and prog[j][1] < off: j += 1
        host = prog[j][0] if j < len(prog) else (prog[-1][0] if prog else None)
        out.append((host, l.decode('latin1').rstrip('\r')))
    return out


def overlay_rows(path, mask):
    """Decoded overlay records (kind, group bit, path) via the second walker; None if the decoder is missing."""
    rc = REPO/'research/ios26-overlay2-r1/tools/restore_cloudd.py'
    if not rc.exists() or not path: return None
    import importlib.util
    s = importlib.util.spec_from_file_location('hk_rc', rc); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return [(chr(r[0]), r[1], r[5]) for r in m.decode(Path(path).read_bytes()) if (mask >> r[1]) & 1]


def analyze(run, overlay=None, mask=None, expect=(), deadline=None, args=''):
    L = load_console(run); res = {'run': str(run), 'console_lines': len(L)}
    try: res['exit'] = json.loads((Path(run)/'exit.json').read_text())
    except (OSError, ValueError): res['exit'] = None
    res['last_host_s'] = next((h for h, _ in reversed(L) if h is not None), None)
    ms = {}
    for key, label, pat in MILESTONES:
        r = re.compile(pat); hit = next(((h, l) for h, l in L if r.search(l)), None)
        ms[key] = {'label': label, 'reached': bool(hit), 'host_s': hit[0] if hit else None}
    res['milestones'] = ms
    # exec counts and crash events per name
    execs, crashes = {}, {}
    def crash(name, kind, t, detail):
        crashes.setdefault(name, []).append({'kind': kind, 'host_s': t, 'detail': detail})
    for h, l in L:
        m = EXEC.search(l)
        if m: execs.setdefault(m[1], []).append(h)
        for rx, kind in ((USERTRAP, 'usertrap'), (USERABORT, 'userabort'), (CRASH, 'CRASH'), (LEXIT, 'exited')):
            m = rx.search(l)
            if m: crash(m[1].strip(), kind, h, l.strip()[:160])
    full = sorted(execs)
    def canon(n):   # p_comm is 16 bytes: usertrap names are truncated, exec names are not
        if n in execs or len(n) < 15: return n
        return next((x for x in full if x.startswith(n)), n)
    crashes2 = {}
    for n, v in crashes.items(): crashes2.setdefault(canon(n), []).extend(v)
    daemons = {}
    for n in sorted(set(execs) | set(crashes2)):
        e = len(execs.get(n, [])); c = crashes2.get(n, [])
        daemons[n] = {'execs': e, 'respawns': 0 if n in MULTI_OK else max(0, e-1), 'crashes': len(c),
                      'crash_kinds': sorted({x['kind'] for x in c}), 'first_crash': c[0]['detail'] if c else None}
    res['daemons'] = daemons
    # panics: the deadline panic is the recipe's own end, not a fault
    pan = [(h, l.strip()[:200]) for h, l in L if PANIC.search(l)]
    dl = [(h, l) for h, l in L if DEADLINE.search(l)]
    res['deadline_end'] = {'host_s': dl[0][0], 'line': dl[0][1].strip()[:200]} if dl else None
    res['panics'] = [{'host_s': h, 'line': l} for h, l in pan if not DEADLINE.search(l)]
    if dl and pan and not res['panics']: res['panics_note'] = 'only the blazer_deadline panic'
    # overlay
    ov = {'mask_line': None, 'applied': None, 'bad': [], 'missing': []}
    for h, l in L:
        m = OVL_MASK.search(l)
        if m and not ov['mask_line']: ov['mask_line'] = l.strip()[:200]; ov['mask'] = m[1]; ov['entries'] = int(m[3])
        m = OVL_APPLIED.search(l)
        if m and ov['applied'] is None: ov['applied'] = int(m[1])
        if OVL_BAD.search(l): ov['bad'].append(l.strip()[:200])
    listed = {m[2] for _, l in L for m in [OVL_REC.search(l)] if m}
    try: rows = overlay_rows(overlay, mask) if overlay and mask is not None else None
    except ValueError as e: rows = None; ov['host_decode_error'] = str(e)
    if rows is not None:
        # group 19 is hkcover (applied by hkcover, not listed per record)
        want = [(k, b, p) for k, b, p in rows if b != 19]
        ov['expected_listed'] = len(want)
        ov['missing'] = [f'{k} {p}' for k, b, p in want if p not in listed and p.split()[0] not in listed]
    res['overlay'] = ov
    tops = [(int(m[1]), int(m[2])) for _, l in L for m in [HKTOP.search(l)] if m]
    res['hk_top'] = {'samples': len(tops), 'frames': sum(f for _, f in tops)}
    # home equivalent
    stable = all(daemons.get(n, {}).get('respawns', 0) == 0 and daemons.get(n, {}).get('crashes', 0) == 0 for n in UI_STABLE)
    reached = all(ms[k]['reached'] for k in HOME_NEEDS)
    res['home_equivalent'] = {'reached': reached and stable and not res['panics'],
                              'host_s': max((ms[k]['host_s'] or 0) for k in HOME_NEEDS) if reached else None,
                              'needs': HOME_NEEDS, 'ui_stable': stable,
                              'note': 'QEMU proxy: Home-time daemons spawned, backboardd/SpringBoard never respawned or crashed, no panic. TCG draws no Home frame.'}
    res['expect'] = run_expect(L, daemons, expect, args); res['evaluator'] = (expect or {}).get('evaluator')
    res['findings'] = findings(res, expect, deadline)
    return res


def shared_evaluator():
    """Return an evaluator accepting the pre-flight's (doc, sources, markers, ui) call.

    VERIFY's newer probe_eval.evaluate(paths, rows, ...) is a public attempt-file API, not the old in-memory
    hk_cycle API. Do not select it merely by name: its two-positional-argument signature raises after a guest has
    already run. A future probe_eval implementation is usable here only if it accepts the same four arguments.
    """
    import importlib.util
    import inspect
    for name, p in (('probe_eval', REPO/'tools/probe_eval.py'), ('hk_cycle', REPO/'tools/hk_cycle.py')):
        if not p.exists():
            continue
        s = importlib.util.spec_from_file_location(f'qp_{name}', p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
        if not hasattr(m, 'evaluate'):
            continue
        fn = m.evaluate
        params = list(inspect.signature(fn).parameters.values())
        positional = [x for x in params if x.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        if len(positional) < 4 and not any(x.kind == inspect.Parameter.VAR_POSITIONAL for x in params):
            continue
        return f'{p.relative_to(REPO)} evaluate (sha {sha(p)[:16]})', fn
    return None, None


PHONE_ONLY_KEYS = ('phone_only',)


def is_phone_only(row):
    return bool(row.get('phone_only')) or row.get('scope') == 'phone' or bool(row.get('ui')) or bool(row.get('needs_input'))


def load_expect(paths):
    """Shared probe rows (id, feature, need, any, forbid, values, marker, ui, needs_input, required, note, source,
    phone_only); later files replace rows by id. Top-level respawn_max / respawn_allow are the pre-flight's crash-loop bounds."""
    import yaml
    spec = {'respawn_max': 2, 'respawn_allow': {}, 'expect': [], 'sources': []}
    for p in paths:
        y = yaml.safe_load(Path(p).read_text()) or {}
        rows = y.get('expect', y.get('probes'))
        if not isinstance(rows, list): die(f'{p}: needs a top-level "expect:" (or "probes:") list')
        spec['sources'].append(str(p))
        if 'respawn_max' in y: spec['respawn_max'] = int(y['respawn_max'])
        spec['respawn_allow'].update(y.get('respawn_allow') or {})
        for e in rows:
            if not isinstance(e, dict) or not e.get('id'): die(f'{p}: every row needs an id')
            for k in ('need', 'any', 'forbid'):
                for rx in e.get(k) or []: re.compile(rx)
            spec['expect'] = [x for x in spec['expect'] if x['id'] != e['id']] + [e]
    return spec


def run_expect(L, daemons, spec, args=''):
    """QEMU rows through the shared evaluator; phone-only rows are listed, not evaluated; if_arg rows need that token."""
    rows = (spec or {}).get('expect', []); out, todo = [], []
    for e in rows:
        if is_phone_only(e): out.append({'id': e['id'], 'feature': e.get('feature', e['id']), 'verdict': 'PHONE_ONLY', 'note': e.get('note', '')}); continue
        if e.get('if_arg') and e['if_arg'] not in args.split():
            out.append({'id': e['id'], 'feature': e.get('feature', e['id']), 'verdict': 'N/A', 'note': f"needs {e['if_arg']}"}); continue
        todo.append({k: v for k, v in e.items() if k not in PHONE_ONLY_KEYS + ('if_arg', 'scope')})
    name, ev = shared_evaluator()
    if todo and not ev: die('no shared evaluator (tools/probe_eval.py or tools/hk_cycle.py) to run the expect rows')
    text = '\n'.join(l for _, l in L)
    got = {r['id']: r for r in (ev({'expect': todo}, {'live': text, 'dump': text}, set(), {'ran': False, 'steps': {}}) if todo else [])}
    if spec is not None: spec['evaluator'] = name
    order = {e['id']: i for i, e in enumerate(rows)}
    return sorted(out + list(got.values()), key=lambda r: order.get(r['id'], 0))


def findings(res, spec, deadline):
    f = []
    for p in res['panics']: f.append(f"panic at host {p['host_s']} s: {p['line']}")
    ov = res['overlay']
    if ov['bad']: f.append('overlay rejected: ' + ov['bad'][0])
    if ov.get('host_decode_error'): f.append(f"overlay does not decode on the host either: {ov['host_decode_error']}")
    if ov.get('expected_listed') is not None:
        if ov['applied'] is None: f.append('overlay: no "varfs-overlay: N applied" line')
        if ov['applied'] is not None and ov['applied'] < ov['expected_listed']:
            f.append(f"overlay: kernel applied {ov['applied']} of {ov['expected_listed']} in-mask records; not listed: {ov['missing'][:5]}")
        elif ov['missing']:   # the count is authoritative; the per-record print can be missing (int1/aud1: hgltrack.dylib)
            f.append(f"note (not a fault): applied count {ov['applied']} matches; {len(ov['missing'])} record(s) without a listing line: {ov['missing'][:5]}")
    for k, v in res['milestones'].items():
        if not v['reached']: f.append(f"milestone not reached in {res.get('last_host_s')} s: {k} ({v['label']})")
    allow = (spec or {}).get('respawn_allow', {}); cap = (spec or {}).get('respawn_max', 2)
    for n, d in res['daemons'].items():
        lim = allow.get(n, cap)
        if d['respawns'] > lim: f.append(f"crash loop: {n} exec {d['execs']}x (respawns {d['respawns']} > {lim}), crashes {d['crashes']} {d['crash_kinds']}")
    for e in res['expect']:
        if e['verdict'] in ('FAIL', 'NO_DATA') and e.get('required', True):
            why = '; '.join([f"forbidden: {x['line']}" for x in e.get('forbidden', [])] + [f'missing: {x}' for x in e.get('missing', [])])
            f.append(f"expect {e['id']} {e['verdict']}: {why[:300]}")
    if res.get('deadline_end'): f.append(f"note (not a fault): the recipe's blazer_deadline ended the guest at host {res['deadline_end']['host_s']} s")
    return f


def compare(res, base):
    out = []
    for k, v in base['milestones'].items():
        if v['reached'] and not res['milestones'][k]['reached']: out.append(f'milestone lost vs baseline: {k}')
    for n, d in res['daemons'].items():
        b = base['daemons'].get(n, {'respawns': 0, 'crashes': 0})
        if d['respawns'] >= b['respawns']+2 or (d['crashes'] and not b['crashes']):
            out.append(f"{n}: respawns {b['respawns']} -> {d['respawns']}, crashes {b['crashes']} -> {d['crashes']}")
    for n, b in base['daemons'].items():
        if b['execs'] and n not in res['daemons'] and n not in MULTI_OK: out.append(f'daemon missing vs baseline: {n}')
    return out


def report_text(pre, res):
    o = []
    w = o.append
    w(f"QEMU pre-flight: {pre['image']['name']}  (QEMU/TCG evidence only; nothing touched the phone)")
    if pre['image'].get('chooser'): w(f"  chooser image -> iOS branch {Path(pre['image']['ios_dir']).name} (chooser default {pre['image'].get('default_entry')})")
    w(f"  kernel  {pre['kernel']['path']}  sha {pre['kernel']['sha'][:16]}  ({pre['kernel']['rebuild']})")
    if pre['kernel'].get('version'): w(f"          {pre['kernel']['version'][:110]}")
    if pre.get('overlay'): w(f"  overlay {pre['overlay']['path']}  sha {pre['overlay']['sha'][:16]}  mask {pre['overlay']['mask']:#x}")
    w(f"  root    {pre['root']}  (fake UFS LUN, read-only)")
    w(f"  run     {res['run']}  host {res.get('last_host_s')} s of {pre.get('seconds')} s; exit {json.dumps(res.get('exit'))}")
    w('  boot-args translation:')
    for t, a, why in pre['translation']:
        if a != 'keep' or 'proven' not in why: w(f'    {a:8s} {t:40s} {why}')
    w(f"    keep     {sum(1 for _, a, why in pre['translation'] if a == 'keep' and 'proven' in why)} QEMU-proven tokens")
    w('  milestones (host s):')
    for k, v in res['milestones'].items(): w(f"    {'OK ' if v['reached'] else '-- '} {k:18s} {v['host_s'] if v['host_s'] is not None else '':>7}  {v['label']}")
    h = res['home_equivalent']
    w(f"    {'OK ' if h['reached'] else '-- '} {'Home equivalent':18s} {h['host_s'] if h['host_s'] is not None else '':>7}  (UI stable: {h['ui_stable']}; {h['note']})")
    w(f"  HK TOP samples {res['hk_top']['samples']}, frames {res['hk_top']['frames']}")
    ov = res['overlay']; w(f"  overlay: {ov.get('mask_line')}; applied {ov['applied']}; expected listed {ov.get('expected_listed')}; missing {len(ov['missing'])}; rejected {len(ov['bad'])}")
    w('  respawns / crashes (daemons with exec > 1 or a crash event):')
    rows = [(n, d) for n, d in res['daemons'].items() if d['respawns'] or d['crashes']]
    for n, d in sorted(rows, key=lambda x: (-x[1]['respawns'], -x[1]['crashes'], x[0])):
        w(f"    {n:28s} exec {d['execs']:3d} respawns {d['respawns']:3d} crashes {d['crashes']:3d} {','.join(d['crash_kinds'])}")
    if not rows: w('    none')
    w(f"  daemons exec'd: {sum(1 for d in res['daemons'].values() if d['execs'])}")
    w(f"  panics: {len(res['panics'])}" + (f"; deadline end at host {res['deadline_end']['host_s']} s" if res.get('deadline_end') else ''))
    for p in res['panics'][:3]: w(f"    {p['line']}")
    w(f"  expect ({res.get('evaluator')}):")
    for e in res['expect']:
        ev = (e.get('evidence') or [{}])[0].get('line', '') if e['verdict'] == 'PASS' else '; '.join([x['line'] for x in e.get('forbidden', [])] + [str(x) for x in e.get('missing', [])])
        w(f"    {e['verdict']:10s} {e['id']:26s} {('' if e.get('required', True) else '(optional) ')}{str(ev)[:110]}")
    if res.get('baseline'): w('  vs baseline: ' + ('; '.join(res['baseline']) or 'no regressions'))
    fails = [x for x in res['findings'] if not x.startswith('note')] + (res.get('baseline') or [])
    w('  findings: ' + ('none' if not res['findings'] else ''))
    for x in res['findings']: w(f'    - {x}')
    w(f"VERDICT: {'FAIL' if fails else 'PASS'} ({len(fails)} finding(s))")
    return '\n'.join(o), bool(fails)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('image', type=Path); ap.add_argument('--seconds', type=int, default=600)
    ap.add_argument('--expect', type=Path, action='append'); ap.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    ap.add_argument('--kernel', type=Path, help='kernel file (sha must equal the manifest mach)'); ap.add_argument('--overlay', type=Path, help='override the overlay (negative tests); recorded')
    ap.add_argument('--keep', action='append', default=[]); ap.add_argument('--drop', action='append', default=[])
    ap.add_argument('--deadline', type=int); ap.add_argument('--name'); ap.add_argument('--window-gib', type=int)
    ap.add_argument('--wait', type=int, default=1800, help='seconds to wait for a QEMU slot'); ap.add_argument('--dry', action='store_true')
    ap.add_argument('--analyze', type=Path, help='analyse an existing run directory instead of running'); ap.add_argument('--baseline', type=Path)
    ap.add_argument('--json', type=Path, help='also write the result JSON here')
    a = ap.parse_args()
    img = load_image(a.image)
    exp_paths = a.expect or ([img['dir'] + '/expect.yaml'] if Path(img['dir'], 'expect.yaml').exists() else []) + ([DEFAULT_EXPECT] if DEFAULT_EXPECT.exists() else [])
    spec = load_expect(exp_paths)
    # kernel
    kp = find_kernel(img['mach'], a.kernel)
    if not kp: die(f"no kernel file with sha256 {img['mach']} under {REPO/'research'} or {RIG/'research'}: copy the phone build "
                   f"(the image's XNU branch, unchanged; it boots on the rig as is) or build that branch and pass --kernel", 2)
    pre = {'image': img, 'kernel': {'path': str(kp), 'sha': img['mach'], 'version': kernel_version(kp),
                                    'rebuild': 'not needed: phone build runs on the rig ADT'}, 'expect': spec['sources'],
           'tool_sha': sha(__file__), 'expect_sha': {str(p): sha(p) for p in spec['sources']}}
    ov = img.get('var_overlay'); mask = None
    if ov or a.overlay:
        op = a.overlay or next((p for p in (REPO/ov['path'], RIG/'research'/Path(ov['path']).relative_to('research')) if p.exists()), None)
        if not op: die(f"overlay {ov['path']} not found")
        osha = sha(op)
        if not a.overlay and osha != ov['sha256']: die(f"overlay {op} sha {osha[:16]} != manifest {ov['sha256'][:16]}")
        mask = int(next((t.split('=')[1] for t in img['cmdline'].split() if t.startswith('hk_overlay=')), '0'), 16)
        pre['overlay'] = {'path': str(Path(op).resolve()), 'sha': osha, 'mask': mask, 'override': bool(a.overlay), 'manifest_sha': ov['sha256'] if ov else None}
    flags, phone = harness_route(img['cmdline'])
    extra, table = translate(img['cmdline'], set(a.keep), set(a.drop), a.deadline)
    pre.update(translation=table, qemu_args=extra, root=str(a.root.resolve()), seconds=a.seconds,
               phone_deadline=phone.get('blazer_deadline'), phone_cpus=phone.get('cpus'))
    if a.analyze:
        run = a.analyze.resolve()
    else:
        if not a.root.exists(): die(f'root {a.root} missing')
        rgib = -(-a.root.stat().st_size >> 30); win = a.window_gib or max(12, rgib+5)
        name = a.name or f"qf-{img['name']}-{time.strftime('%m%d-%H%M%S')}"; run = RUNS/name
        slots = min(int(os.environ.get('HACKIOS_QEMU_SLOTS', SLOTS_CAP)), SLOTS_CAP)
        cmd = [sys.executable, '-I', str(HARNESS), name, '--kernel', str(kp), '--root', str(a.root.resolve()), '--window-gib', str(win),
               '--runtime', str(a.seconds), '--idle', '0', '--wait', str(a.wait), '--slots', str(slots), *flags, '--args', extra]
        if pre.get('overlay'): cmd[cmd.index('--args'):cmd.index('--args')] = ['--var-overlay', pre['overlay']['path']]
        if a.dry: cmd.insert(cmd.index('--args'), '--dry')
        pre['harness_cmd'] = cmd; pre['harness_sha'] = sha(HARNESS); pre['started'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        print(f'qemu_preflight: {name}: {a.seconds} s on the rig (slots cap {slots})', file=sys.stderr)
        r = subprocess.run(cmd, cwd=str(HARNESS.parent.parent), capture_output=True, text=True)
        pre['harness_stdout'] = r.stdout[-2000:]; pre['harness_rc'] = r.returncode
        if r.returncode and not (run/'console.log').exists():
            if run.exists(): (run/'preflight.json').write_text(json.dumps(pre, indent=1)+'\n')
            die(f'harness rc {r.returncode}: {r.stderr[-800:]}')
        (run/'preflight.json').write_text(json.dumps(pre, indent=1)+'\n')
        if a.dry: print(json.dumps({'dry': True, 'run': str(run), 'cmd': cmd, 'translation': table}, indent=1)); return 0
    res = analyze(run, pre.get('overlay', {}).get('path'), mask, spec, a.deadline, extra)
    if a.baseline:
        bp = json.loads((a.baseline/'preflight-result.json').read_text()) if (a.baseline/'preflight-result.json').exists() else analyze(a.baseline, None, None, spec)
        res['baseline'] = compare(res, bp); res['baseline_run'] = str(a.baseline)
    text, failed = report_text(pre, res)
    out = {'preflight': pre, 'result': res, 'verdict': 'FAIL' if failed else 'PASS'}
    try:
        (run/'preflight-result.json').write_text(json.dumps(res, indent=1)+'\n'); (run/'preflight-report.txt').write_text(text+'\n')
    except OSError: pass
    if a.json: a.json.write_text(json.dumps(out, indent=1)+'\n')
    print(text)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
