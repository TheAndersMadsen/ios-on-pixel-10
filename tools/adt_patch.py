#!/usr/bin/env python3
"""Declarative ADT patch layer + identity/capability manifest (research/ios26-phaseb-r1/goal-pool/
HACKINTOSH-REUSE.md section 2.4; the OpenCore ACPI->Add / DeviceProperties / PlatformInfo model).

mkadt.build() makes the platform core in code (memory, CPUs, GIC, timers, fbcon, DPU, pram, NVRAM,
the donor /product merge), then applies adt/patches/NN-<subsys>.yaml in file-name order. Each entry
carries its own reason, lane and evidence; an entry that cannot apply (missing parent, missing
anchor, node already present, unknown field) refuses the build, and an entry left out by `when` or by
its min/max build is recorded as skipped, never silently dropped. adt/identity.yaml is the single
table of who we claim to be (iPhone12,3 / D421AP) and which of that model's capabilities we claim vs
actually provide; patch entries tagged `capability:` must agree with it.

  adt_patch.py lint                         parse + schema-check adt/ (patches, identity)
  adt_patch.py show [--qemu] [--headless] [--gate=NAME]   what would apply, in order
  adt_patch.py verify IMAGE_DIR             the image's recorded patch set is present in its laguna.adt
  adt_patch.py regress IMAGE_DIR [...]      rebuild the image's ADT with its own random-seed: byte-identical?
  adt_patch.py gaps [--plist P] CONSOLE...  missing-ADT-node / launchd device-tree-gate table (markdown)

An entry with `gate: NAME` applies only when the build enables that gate (mkadt.build(gates=...), an
image_tool flag such as --bt-nub); enabling a gate that no entry carries refuses the build.

Value types: u32, u64 (int or list), str (C string), strs (list of C strings), pad32 (string padded
to 32 bytes), bytes (hex), sha384 (digest of the UTF-8 text), empty. A value `$identity.<key>` takes the
identity manifest's value.
"""
import hashlib, json, os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt as ADT  # noqa: E402
import miniyaml  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
ADT_DIR = os.path.join(ROOT, 'adt')
PATCH_DIR = os.path.join(ADT_DIR, 'patches')
IDENTITY_FILE = os.path.join(ADT_DIR, 'identity.yaml')
TARGET_BUILD = '23G90'   # the iOS 26 userland every image carries (BuildManifest of the root)
SCHEMA = 1

OPS = {'set', 'add-node', 'delete-node', 'delete-prop'}
COMMON = {'id', 'op', 'path', 'reason', 'lane', 'gate', 'evidence', 'capability', 'when', 'min_build',
          'max_build', 'status'}
FIELDS = {'set': COMMON | {'prop', 'type', 'value', 'after', 'before'},
          'delete-prop': COMMON | {'prop'},
          'add-node': COMMON | {'props', 'after', 'before', 'phandle'},
          'delete-node': COMMON}
TYPES = {'u32', 'u64', 'str', 'strs', 'pad32', 'bytes', 'sha384', 'empty'}
WHEN_KEYS = {'qemu', 'headless', 'disp0', 'nvram'}
STATUS = {'verified', 'inference'}
CAP_PROVIDE = {'yes', 'partial', 'no'}
CAP_CLAIM = {'yes', 'no', 'implicit'}


class PatchError(SystemExit):
    pass


def die(msg):
    raise PatchError(f'adt_patch: {msg}')


def _read(path):
    with open(path, 'rb') as f:
        return f.read()


def sha(path):
    return hashlib.sha256(_read(path)).hexdigest()


def rel(path):
    return os.path.relpath(path, ROOT)


# ---------------------------------------------------------------- identity / capability manifest

def load_identity(path=IDENTITY_FILE):
    doc = miniyaml.load(path)
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        die(f'{rel(path)}: schema must be {SCHEMA}')
    extra = set(doc) - {'schema', 'identity', 'syscfg', 'capabilities'}
    if extra:
        die(f'{rel(path)}: unknown top-level keys {sorted(extra)}')
    ident = doc.get('identity')
    need = {'model', 'compatible', 'target_type', 'target_sub_type', 'platform_name', 'chip_id', 'board_id',
            'canvas', 'scale', 'manufacturer', 'ecid'}
    if not isinstance(ident, dict) or need - set(ident):
        die(f'{rel(path)}: identity lacks {sorted(need - set(ident or {}))}')
    caps, seen = doc.get('capabilities') or [], set()
    for c in caps:
        cid = c.get('id')
        miss = {'id', 'model_has', 'provide', 'claim', 'notes'} - set(c)
        if miss:
            die(f'{rel(path)}: capability {cid!r} lacks {sorted(miss)}')
        unknown = set(c) - {'id', 'model_has', 'provide', 'claim', 'notes', 'evidence', 'adt', 'gestalt', 'lane', 'status'}
        if unknown:
            die(f'{rel(path)}: capability {cid!r} has unknown keys {sorted(unknown)}')
        if cid in seen:
            die(f'{rel(path)}: duplicate capability {cid!r}')
        seen.add(cid)
        if c['provide'] not in CAP_PROVIDE or c['claim'] not in CAP_CLAIM or not isinstance(c['model_has'], bool):
            die(f'{rel(path)}: capability {cid!r}: provide in {sorted(CAP_PROVIDE)}, claim in {sorted(CAP_CLAIM)}, model_has bool')
        if c.get('status', 'verified') not in STATUS:
            die(f'{rel(path)}: capability {cid!r}: status in {sorted(STATUS)}')
    return dict(identity=ident, syscfg=doc.get('syscfg') or {}, capabilities={c['id']: c for c in caps},
                path=path, sha256=sha(path))


def identity_tuple(ident):
    """The mkadt.IDENTITY shape (tuples where mkadt had tuples)."""
    i = dict(ident['identity'])
    i['compatible'] = tuple(i['compatible'])
    i['canvas'] = tuple(i['canvas'])
    return i


# ---------------------------------------------------------------- patch files

def build_key(b):
    m = re.fullmatch(r'(\d+)([A-Z])(\d+)([a-z]?)', str(b))
    if not m:
        die(f'bad iOS build {b!r}')
    return int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)


def _check_entry(e, where, ident):
    if not isinstance(e, dict):
        die(f'{where}: entry is not a mapping')
    eid, op = e.get('id'), e.get('op')
    if not eid or not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', str(eid)):
        die(f'{where}: entry id {eid!r} must be lower-case [a-z0-9.-]')
    if op not in OPS:
        die(f'{where}: {eid}: op {op!r} not in {sorted(OPS)}')
    unknown = set(e) - FIELDS[op]
    if unknown:
        die(f'{where}: {eid}: unknown fields {sorted(unknown)} for op {op}')
    for f in ('path', 'reason'):
        if not e.get(f):
            die(f'{where}: {eid}: {f} is required')
    if not str(e['path']).startswith('/'):
        die(f'{where}: {eid}: path must be absolute (/chosen, /arm-io/wdt)')
    if op in ('set', 'delete-prop') and not e.get('prop'):
        die(f'{where}: {eid}: {op} needs prop')
    if op == 'set':
        _check_value(e, f'{where}: {eid}')
    if op == 'add-node':
        if e['path'] == '/':
            die(f'{where}: {eid}: cannot add the root')
        for p in e.get('props') or []:
            if not isinstance(p, dict) or set(p) - {'name', 'type', 'value'} or not p.get('name'):
                die(f'{where}: {eid}: props items are {{name, type, value}}')
            _check_value(p, f'{where}: {eid}: {p["name"]}')
    if 'after' in e and 'before' in e:
        die(f'{where}: {eid}: after and before are exclusive')
    w = e.get('when')
    if w is not None and (not isinstance(w, dict) or set(w) - WHEN_KEYS or not all(isinstance(v, bool) for v in w.values())):
        die(f'{where}: {eid}: when is a mapping of {sorted(WHEN_KEYS)} to true/false')
    for k in ('min_build', 'max_build'):
        if k in e:
            build_key(e[k])
    if e.get('status', 'verified') not in STATUS:
        die(f'{where}: {eid}: status in {sorted(STATUS)}')
    cap = e.get('capability')
    if cap is not None and ident is not None and cap not in ident['capabilities']:
        die(f'{where}: {eid}: capability {cap!r} is not in adt/identity.yaml')


def _check_value(p, where):
    t = p.get('type')
    if t not in TYPES:
        die(f'{where}: type {t!r} not in {sorted(TYPES)}')
    if t != 'empty' and 'value' not in p:
        die(f'{where}: value is required')


def load_patch_file(path, ident=None):
    doc = miniyaml.load(path)
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        die(f'{rel(path)}: schema must be {SCHEMA}')
    extra = set(doc) - {'schema', 'subsystem', 'description', 'entries'}
    if extra:
        die(f'{rel(path)}: unknown top-level keys {sorted(extra)}')
    if not doc.get('subsystem') or not isinstance(doc.get('entries'), list) or not doc['entries']:
        die(f'{rel(path)}: needs subsystem and a non-empty entries list')
    for e in doc['entries']:
        _check_entry(e, rel(path), ident)
    return doc


def load_patches(patch_dir=PATCH_DIR, ident=None):
    names = sorted(n for n in os.listdir(patch_dir) if not n.startswith('.'))
    bad = [n for n in names if not re.fullmatch(r'\d\d-[a-z0-9-]+\.yaml', n)]
    if bad:
        die(f'{rel(patch_dir)}: unexpected files {bad} (NN-<subsys>.yaml only)')
    files, ids, targets = [], {}, {}
    for n in names:
        p = os.path.join(patch_dir, n)
        doc = load_patch_file(p, ident)
        for e in doc['entries']:
            if e['id'] in ids:
                die(f'duplicate entry id {e["id"]!r} in {n} and {ids[e["id"]]}')
            ids[e['id']] = n
            t = (e['path'], e.get('prop'), e.get('gate'))
            if t in targets:
                die(f'{e["id"]} and {targets[t]} both edit {e["path"]}{":" + e["prop"] if e.get("prop") else ""} (one entry per target)')
            targets[t] = e['id']
        files.append(dict(path=p, name=n, sha256=sha(p), doc=doc))
    return files


# ---------------------------------------------------------------- values and tree edits

def resolve(v, ident):
    if isinstance(v, str) and v.startswith('$identity.'):
        k = v[len('$identity.'):]
        src = dict(ident['identity'], **ident['syscfg']) if ident else {}
        if k not in src:
            die(f'unknown identity reference {v}')
        return src[k]
    if isinstance(v, list):
        return [resolve(x, ident) for x in v]
    return v


def encode(t, v, ident=None):
    v = resolve(v, ident)
    seq = v if isinstance(v, list) else [v]
    try:
        if t == 'u32':
            return struct.pack('<%dI' % len(seq), *seq)
        if t == 'u64':
            return struct.pack('<%dQ' % len(seq), *seq)
        if t == 'str':
            return str(v).encode() + b'\0'
        if t == 'strs':
            return b''.join(str(x).encode() + b'\0' for x in seq)
        if t == 'pad32':
            b = str(v).encode()
            if len(b) > 31:
                raise ValueError('longer than 31 bytes')
            return b.ljust(32, b'\0')
        if t == 'bytes':
            return bytes.fromhex(str(v).replace(' ', '').replace(':', ''))
        if t == 'sha384':
            return hashlib.sha384(str(v).encode()).digest()
        if t == 'empty':
            return b''
    except (struct.error, ValueError, TypeError) as e:
        die(f'cannot encode {v!r} as {t}: {e}')
    die(f'unknown type {t}')


def find(root, path):
    n = root
    for part in [p for p in path.split('/') if p]:
        n = next((c for c in n.children if c.name == part), None)
        if n is None:
            return None
    return n


def _split(path):
    parent, _, name = path.rstrip('/').rpartition('/')
    return parent or '/', name


def _anchor(names, e, what):
    """Index to insert at among `names` (prop or child names) given after/before; None = append."""
    for key, off in (('after', 1), ('before', 0)):
        if key in e:
            for a in (e[key] if isinstance(e[key], list) else [e[key]]):
                if a in names:
                    return names.index(a) + off
            die(f'{e["id"]}: no {what} {e[key]!r} to place {key}')
    return None


def _skip(e, ctx):
    if e.get('gate') and e['gate'] not in (ctx.get('gates') or ()):
        return f'gate {e["gate"]} off'
    for k, want in (e.get('when') or {}).items():
        if bool(ctx.get(k)) != want:
            return f'when {k}={str(want).lower()}'
    b = build_key(ctx.get('build', TARGET_BUILD))
    if 'min_build' in e and b < build_key(e['min_build']):
        return f'build < {e["min_build"]}'
    if 'max_build' in e and b > build_key(e['max_build']):
        return f'build > {e["max_build"]}'
    return None


def apply_entry(root, e, ident, slots, fresh):
    op, path = e['op'], e['path']
    if op in ('set', 'delete-prop'):
        n = find(root, path)
        if n is None:
            die(f'{e["id"]}: no node {path}')
        names = [k for k, _, _ in n.props]
        if op == 'delete-prop':
            if e['prop'] not in names:
                die(f'{e["id"]}: {path} has no {e["prop"]}')
            n.props = [p for p in n.props if p[0] != e['prop']]
            return
        val = encode(e['type'], e.get('value'), ident)
        if e['prop'] in names:
            if 'after' in e or 'before' in e:
                die(f'{e["id"]}: {path}:{e["prop"]} exists; a placement only applies to a new property')
            n.props = [(k, f, val if k == e['prop'] else v) for k, f, v in n.props]
            return
        at = _anchor(names, e, 'property')
        n.props.insert(len(n.props) if at is None else at, (e['prop'], 0, val))
        return
    parent_path, name = _split(path)
    parent = find(root, parent_path)
    if parent is None:
        die(f'{e["id"]}: no parent {parent_path}')
    kids = [c.name for c in parent.children]
    if op == 'delete-node':
        if name not in kids:
            die(f'{e["id"]}: no node {path} to delete')
        parent.children = [c for c in parent.children if c.name != name]
        return
    if name in kids:
        die(f'{e["id"]}: {path} already exists (set its properties instead)')
    node = ADT.Node()
    node.props = [('name', 0, name.encode() + b'\0')]
    if e.get('phandle', True):
        ph = slots.pop(path.lstrip('/'), None)
        if ph is None:
            ph = fresh()
        node.props.append(('AAPL,phandle', 0, struct.pack('<I', ph)))
    for p in e.get('props') or []:
        node.props.append((p['name'], 0, encode(p['type'], p.get('value'), ident)))
    at = _anchor(kids, e, 'sibling')
    parent.children.insert(len(parent.children) if at is None else at, node)


def apply(root, ctx, slots=None, files=None, ident=None):
    """Apply the patch set to an mkadt tree. slots: {'arm-io/wdt': phandle} reserved by mkadt in its
    historical phandle order, so a converted node keeps the number it had as code; nodes with no slot
    get fresh phandles after the highest in use. Returns the record image_tool stores in manifest.json."""
    ident = ident or load_identity()
    files = files if files is not None else load_patches(ident=ident)
    slots = dict(slots or {})
    used = [struct.unpack('<I', v)[0] for v in _all_props(root, 'AAPL,phandle')] + list(slots.values())
    nxt = [max(used or [0]) + 1]

    def fresh():
        v = nxt[0]
        nxt[0] += 1
        return v

    applied, skipped, caps_used = [], [], {}
    for f in files:
        for e in f['doc']['entries']:
            why = _skip(e, ctx)
            if why:
                skipped.append(dict(id=e['id'], file=f['name'], why=why))
                continue
            cap = e.get('capability')
            if cap and ident['capabilities'][cap]['claim'] == 'no':
                die(f'{e["id"]}: tagged capability {cap!r}, which adt/identity.yaml says we do not claim')
            apply_entry(root, e, ident, slots, fresh)
            applied.append(e['id'])
            if cap:
                caps_used.setdefault(cap, []).append(e['id'])
    known = {e.get('gate') for f in files for e in f['doc']['entries']}
    stray = sorted(set(ctx.get('gates') or ()) - known)
    if stray:
        die(f'gates {stray} enabled, but no patch entry carries them')
    return dict(schema=SCHEMA, build=ctx.get('build', TARGET_BUILD), gates=sorted(ctx.get('gates') or ()),
                identity=dict(path=rel(ident['path']), sha256=ident['sha256']),
                files={rel(f['path']): f['sha256'] for f in files}, applied=applied, skipped=skipped,
                unused_slots=sorted(slots), capability_report=capability_report(ident, caps_used))


def _all_props(n, key):
    for k, _, v in n.props:
        if k == key:
            yield v
    for c in n.children:
        yield from _all_props(c, key)


def capability_report(ident, caps_used):
    """overclaim: the model has it, we do not provide it, yet userland is told it exists (the CommCenter
    case). hidden: we provide it, but do not claim it (the UI never shows it). unbacked: claim 'yes' with
    no applied ADT entry carrying it."""
    out = dict(overclaim=[], hidden=[], unbacked=[])
    for cid, c in ident['capabilities'].items():
        if c['model_has'] and c['provide'] == 'no' and c['claim'] != 'no':
            out['overclaim'].append(cid)
        if c['provide'] != 'no' and c['claim'] == 'no':
            out['hidden'].append(cid)
        if c['claim'] == 'yes' and not caps_used.get(cid):
            out['unbacked'].append(cid)
    return out


# ---------------------------------------------------------------- image checks

def _expected(e, ident):
    """(kind, path, prop, bytes|None) facts an applied entry leaves in the ADT."""
    if e['op'] == 'set':
        return [('prop', e['path'], e['prop'], encode(e['type'], e.get('value'), ident))]
    if e['op'] == 'delete-prop':
        return [('noprop', e['path'], e['prop'], None)]
    if e['op'] == 'delete-node':
        return [('nonode', e['path'], None, None)]
    return [('node', e['path'], None, None)] + [('prop', e['path'], p['name'], encode(p['type'], p.get('value'), ident))
                                                for p in e.get('props') or []]


def verify_blob(blob, rec):
    """Check an image's laguna.adt against its manifest adt_patches record. Returns (problems, notes)."""
    root, _ = ADT.parse(blob)
    probs, notes = [], []
    cur = {p: sha(os.path.join(ROOT, p)) for p in rec['files'] if os.path.exists(os.path.join(ROOT, p))}
    changed = sorted(p for p in rec['files'] if cur.get(p) != rec['files'][p])
    ipath = os.path.join(ROOT, rec['identity']['path'])
    if changed or not os.path.exists(ipath) or sha(ipath) != rec['identity']['sha256']:
        notes.append(f'patch set changed since the build ({", ".join(changed) or "identity"}): '
                     'checked only that the recorded ids are present')
        return probs, notes
    ident = load_identity(ipath)
    entries = {e['id']: e for p in rec['files'] for e in load_patch_file(os.path.join(ROOT, p), ident)['entries']}
    unknown = [i for i in rec['applied'] if i not in entries]
    if unknown:
        probs.append(f'record names unknown entries {unknown}')
    accounted = set(rec['applied']) | {s['id'] for s in rec['skipped']}
    unused = sorted(set(entries) - accounted)
    if unused:
        probs.append(f'entries neither applied nor recorded as skipped: {unused}')
    for i in rec['applied']:
        if i not in entries:
            continue
        for kind, path, prop, val in _expected(entries[i], ident):
            n = find(root, path)
            if kind == 'node' and n is None:
                probs.append(f'{i}: node {path} missing')
            elif kind == 'nonode' and n is not None:
                probs.append(f'{i}: node {path} still present')
            elif kind == 'prop' and (n is None or n.prop(prop) != val):
                probs.append(f'{i}: {path}:{prop} differs')
            elif kind == 'noprop' and n is not None and n.prop(prop) is not None:
                probs.append(f'{i}: {path}:{prop} still present')
    return probs, notes


def verify_image(d):
    m = json.loads(_read(os.path.join(d, 'manifest.json')))
    rec = m.get('adt_patches')
    if rec is None:
        return None, ['image predates the ADT patch layer (no adt_patches record)']
    return verify_blob(_read(os.path.join(d, 'laguna.adt')), rec)


def image_build_kwargs(m):
    """mkadt.build arguments that image_tool.build() passes for an image manifest (image_tool.py: the
    mkadt.build call). headless/disp0 follow --phone-root/--first-boot/--second-boot/--soak; --phone-root
    also forces gamut sRGB (image_tool: `a.dpu = True; a.gamut = 'sRGB'`), which the manifest does not record."""
    cpu_order = m.get('cpu_order')
    return dict(headless=bool(m.get('first_boot') or m.get('phone_root') or m.get('soak') is not None),
                disp0=bool(m.get('second_boot') or m.get('phone_root')), cpus=m.get('cpus', 1),
                canvas=tuple(m['adt_facts']['canvas']) if m.get('adt_facts', {}).get('canvas') else None,
                gamut=m.get('gamut') or ('sRGB' if m.get('phone_root') else None), boot_mpidr=int(m['bootcpu'], 16) if m.get('bootcpu') else 0,
                cpu_order=cpu_order, phys_base=int(m['window_base'], 16) if m.get('window_base') else None,
                gates=tuple(m.get('adt_patches', {}).get('gates') or (['bt_nub'] if m.get('bt_nub') else [])))


def regress_image(d, mkadt=None):
    """Rebuild the image's ADT with today's mkadt + patch layer and the image's own random-seed."""
    if mkadt is None:
        import mkadt
    blob = _read(os.path.join(d, 'laguna.adt'))
    root, _ = ADT.parse(blob)
    seed = find(root, '/chosen').prop('random-seed')
    m = json.loads(_read(os.path.join(d, 'manifest.json')))
    kw = image_build_kwargs(m)
    new = ADT.serialize(mkadt.build(seed=seed, **kw))
    new += b'\0' * (-len(new) % 8)
    return blob, new, kw


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


# ---------------------------------------------------------------- console gap finder

_PATH_NONE = re.compile(r'IOK ([A-Za-z0-9_.+-]+): path (IODeviceTree:/[^\s]*) -> none')
_NAME_NONE = re.compile(r'IOK ([A-Za-z0-9_.+-]+): matching1? <dict ID="0"><key>IONameMatch</key><string ID="1">([^<]+)</string>.*?-> (none|0 found)')
_LOOKUP = re.compile(r'HKL ([A-Za-z0-9_.+-]+)\[\d+\].*?service named ([A-Za-z0-9_.-]+) was invalidated: Connection init failed at lookup')
_BOOTSTRAP = re.compile(r'HKL ([A-Za-z0-9_.+-]+)\[\d+\] bootstrap_look_up of ([A-Za-z0-9_.-]+)(?: server)? failed')
# MobileWiFi logs the server by its nickname; the mach name is in wifid's strings (HOST: 23G90 /usr/sbin/wifid has
# "com.apple.wifi.manager" and "Making WiFi Manager available for all to see"; not a plist MachService, so wifid
# registers it at run time: INFERENCE on the mechanism).
LOOKUP_ALIASES = {'WiFiManager': 'com.apple.wifi.manager'}
RUNTIME_OWNERS = {'com.apple.wifi.manager': 'com.apple.wifid (registered at run time; wifid strings, HOST)'}
_MISSING_EXE = re.compile(r"launchd\|.*?\((?:[a-z]+/\d+/)?([A-Za-z0-9_.-]+) \[\d+\]\) <Error>: Missing executable")
GATE_KEYS = ('_LimitLoadToDeviceTree', '_LimitLoadFromDeviceTree', 'LimitLoadToHardware', 'LimitLoadFromHardware')


def scan_consoles(paths):
    """Observed (PHYSICAL) signals: registry paths that resolved to none, IONameMatch with no match,
    mach lookups that failed, launchd missing-executable jobs. {kind: {key: {procs, consoles}}}."""
    out = {'adt_path': {}, 'name_match': {}, 'lookup': {}, 'missing_exe': {}}
    for p in paths:
        tag = os.path.basename(os.path.dirname(p)) or p
        text = _read(p).decode('utf-8', 'replace')
        for rx, kind in ((_PATH_NONE, 'adt_path'), (_NAME_NONE, 'name_match'), (_LOOKUP, 'lookup'), (_BOOTSTRAP, 'lookup')):
            for m in rx.finditer(text):
                key = LOOKUP_ALIASES.get(m.group(2), m.group(2)) if kind == 'lookup' else m.group(2)
                d = out[kind].setdefault(key, dict(procs=set(), consoles=set()))
                d['procs'].add(m.group(1))
                d['consoles'].add(tag)
        for m in _MISSING_EXE.finditer(text):
            d = out['missing_exe'].setdefault(m.group(1), dict(procs={'launchd'}, consoles=set()))
            d['consoles'].add(tag)
    return out


def launchd_gates(plist_path):
    """{label: {gate_key: value, 'mach': [services], 'program': path}} for every LaunchDaemon with a
    device-tree / hardware gate, and a service -> label map for all of them."""
    import plistlib
    p = plistlib.loads(_read(plist_path))
    gates, owner = {}, {}
    for k, v in p.get('LaunchDaemons', {}).items():
        lab = v.get('Label', k)
        for s in (v.get('MachServices') or {}):
            owner[s] = lab
        g = {kk: v[kk] for kk in GATE_KEYS if kk in v}
        if g:
            g['program'] = v.get('Program') or (v.get('ProgramArguments') or [''])[0]
            g['mach'] = sorted(v.get('MachServices') or {})
            g['disabled'] = bool(v.get('Disabled'))
            gates[lab] = g
    return gates, owner


def dt_gate_names(val):
    vals = val if isinstance(val, list) else [val]
    return [str(x) for x in vals]


def adt_has(root, name):
    """launchd's _LimitLoadToDeviceTree names: 'node' (anywhere in the tree, INFERENCE: matched by node
    name) or 'node:property' (property on that node). True/False."""
    node, _, prop = name.partition(':')
    stack = [root]
    while stack:
        n = stack.pop()
        if n.name == node and (not prop or n.prop(prop) is not None):
            return True
        stack.extend(n.children)
    return False


def main(argv):
    if len(argv) < 2 or argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    cmd = argv[1]
    if cmd == 'lint':
        ident = load_identity()
        files = load_patches(ident=ident)
        n = sum(len(f['doc']['entries']) for f in files)
        gated = sorted({e['gate'] for f in files for e in f['doc']['entries'] if e.get('gate')})
        inf = sum(e.get('status') == 'inference' for f in files for e in f['doc']['entries'])
        print(f'adt lint: {len(files)} patch files, {n} entries ({inf} inference), gates {gated}, '
              f'{len(ident["capabilities"])} capabilities: OK')
        return 0
    if cmd == 'show':
        ident = load_identity()
        ctx = dict(qemu='--qemu' in argv, headless='--headless' in argv, build=TARGET_BUILD,
                   gates=[a.split('=', 1)[1] for a in argv if a.startswith('--gate=')])
        for f in load_patches(ident=ident):
            for e in f['doc']['entries']:
                why = _skip(e, ctx)
                print(f'{f["name"]:24} {e["id"]:36} {e["op"]:11} {e["path"]}{":" + e["prop"] if e.get("prop") else ""}'
                      f'{"  SKIP " + why if why else ""}')
        return 0
    if cmd == 'verify':
        probs, notes = verify_image(argv[2])
        for n in notes:
            print('note:', n)
        if probs:
            print('MISMATCH adt_patches:', '; '.join(probs))
            return 1
        print('adt_patches: OK' if probs is not None else 'adt_patches: none recorded')
        return 0
    if cmd == 'regress':
        rc = 0
        for d in argv[2:]:
            old, new, kw = regress_image(d)
            same = old == new
            print(f'{d}: {"BYTE-IDENTICAL" if same else "DIFFERS"} old={hashlib.sha256(old).hexdigest()} '
                  f'new={hashlib.sha256(new).hexdigest()} bytes={len(old)}/{len(new)}'
                  f'{"" if same else " first diff at " + str(first_diff(old, new))}')
            rc |= not same
        return rc
    if cmd == 'gaps':
        plist = None
        if '--plist' in argv:
            i = argv.index('--plist')
            plist = argv[i + 1]
            argv = argv[:i] + argv[i + 2:]
        adt_path = None
        if '--adt' in argv:
            i = argv.index('--adt')
            adt_path = argv[i + 1]
            argv = argv[:i] + argv[i + 2:]
        print(gaps_markdown(scan_consoles(argv[2:]), plist, adt_path))
        return 0
    die(f'unknown command {cmd}')


def gaps_markdown(obs, plist=None, adt_path=None):
    root = ADT.parse(_read(adt_path))[0] if adt_path else None
    lines = ['### Observed in console (PHYSICAL): registry paths that resolved to `none`', '',
             '| IODeviceTree path | looked up by | consoles |', '|---|---|---|']
    for k in sorted(obs['adt_path']):
        d = obs['adt_path'][k]
        lines.append(f'| `{k}` | {", ".join(sorted(d["procs"]))} | {len(d["consoles"])} |')
    lines += ['', '### Observed: IONameMatch with no match', '', '| name | by |', '|---|---|']
    for k in sorted(obs['name_match']):
        lines.append(f'| `{k}` | {", ".join(sorted(obs["name_match"][k]["procs"]))} |')
    if plist:
        gates, owner = launchd_gates(plist)
        lines += ['', '### launchd device-tree / hardware gates (HOST, from the root\'s launchd.plist)', '',
                  '| job | gate | value | satisfied by our ADT | mach services looked up in console |', '|---|---|---|---|---|']
        for lab in sorted(gates):
            g = gates[lab]
            for key in GATE_KEYS:
                if key not in g:
                    continue
                val = g[key]
                sat = '' if root is None else (
                    ('yes' if any(adt_has(root, n) for n in dt_gate_names(val)) else 'NO') if key == '_LimitLoadToDeviceTree' else
                    ('NO (blocked)' if any(adt_has(root, n) for n in dt_gate_names(val)) else 'yes') if key == '_LimitLoadFromDeviceTree' else 'n/a')
                seen = [s for s in g['mach'] if s in obs['lookup']]
                lines.append(f'| {lab} | {key} | `{json.dumps(val)[:90]}` | {sat} | {", ".join(seen)} |')
        lines += ['', '### Failed mach lookups (PHYSICAL) and the launchd job that owns them (HOST)', '',
                  '| service | owner job | DT/hardware gate on owner | looked up by |', '|---|---|---|---|']
        for s in sorted(obs['lookup']):
            lab = owner.get(s) or RUNTIME_OWNERS.get(s, '(no LaunchDaemon: agent, app or not in this root)')
            g = gates.get(lab.split(' ')[0])
            gate = ', '.join(f'{k}={json.dumps(g[k])[:60]}' for k in GATE_KEYS if g and k in g) or '-'
            lines.append(f'| `{s}` | {lab} | {gate} | {", ".join(sorted(obs["lookup"][s]["procs"]))} |')
    if obs['missing_exe']:
        lines += ['', '### launchd missing-executable jobs (PHYSICAL)', '']
        lines += [f'- `{k}` ({len(v["consoles"])} consoles)' for k, v in sorted(obs['missing_exe'].items())]
    return '\n'.join(lines)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
