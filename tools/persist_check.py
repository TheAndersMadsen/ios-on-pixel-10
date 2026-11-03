#!/usr/bin/env python3
"""Before/after hashes for the first physical ios_data persist test. READ ONLY: it never writes to the phone.

  persist_check.py snapshot --out FILE.json [--quick] [--dry-run] [--adb ADB]
  persist_check.py compare --before PRE.json --after POST.json [--control CTRL.json]

snapshot (Android booted, adb with su, ANDROID_SERIAL set): every hash is computed ON THE PHONE (`dd | sha256sum`); only
64-hex digests and dd's byte counts cross USB. Every region command resolves its partition by name again
(/dev/block/by-name), because the LUN letters change between boots (sda then sdb on 2026-11-03), and prints the extent
it found, which must equal the layout read at the start. LUN 0's table must be the A6 table (REFERENCE_LUN0) exactly.

Regions, in 4096-byte blocks:
  gpt:<disk>:head/tail   every disk that holds by-name partitions: the blocks before the first and after the last one
                         (LUN 0: LBA 0..5 and 31147003..31147007; the backup array and header)          must
  part:<name>            every partition in full, except the two below                                    must or observed
  part:userdata|userdata_exp.ai:head/tail  first and last 64 MiB (both are Android /data and change)      observed
  ios_data:block0        block 0, never written by the store                                              must
  ios_data:test          block 1, the test block (mode 2 only; the physical test runs mode 1)              must
  ios_data:slots         blocks 2..4099, the two slots: the only blocks allowed to change                  persist
  ios_data:rest          blocks 4100..end                                                                  must
must: the boot chain of both slots (boot, init_boot, vendor_boot, vendor_kernel_boot, dtbo, vbmeta*, pvmfw), super,
ios_system and the GPT. Any change fails. observed: everything else; Android and the bootloader write some of these
themselves, so a change is explained only if an Android-only control run (--control) changed the same region.
--quick: the GPT, the must partitions, userdata's edges and ios_data only.

compare: exit 0 PASS, 1 FAIL (a must region or the layout changed), 2 REVIEW (an observed region changed and no control
run explains it). It also says whether the persist slots were written. --dry-run prints every adb command and runs none.
"""
import argparse, hashlib, json, os, re, shlex, subprocess, sys, time
from pathlib import Path
sys.dont_write_bytecode = True

BLOCK, SECTOR, MiB = 4096, 512, 1 << 20
IOS_DATA, IOS_SYSTEM = 'ios_data', 'ios_system'
TEST_BLOCKS, SLOT_BLOCKS = 1, 2049                       # ios-data-persist/gen_table.py: table = ios_data blocks 1..4099
TABLE_FIRST, TABLE_BLOCKS = 1, TEST_BLOCKS + 2 * SLOT_BLOCKS
EDGE_BLOCKS = 64 * MiB // BLOCK
BIG_LIVE = ('userdata', 'userdata_exp.ai')
MUST_BASES = ('boot', 'init_boot', 'vendor_boot', 'vendor_kernel_boot', 'dtbo', 'vbmeta', 'vbmeta_system', 'vbmeta_vendor', 'pvmfw')
MUST_WHOLE = frozenset([f'{b}_{s}' for b in MUST_BASES for s in 'ab'] + ['super', IOS_SYSTEM])
# LUN 0 after A6 (attempts/a7-gpt-after-a6/sgdisk-p.txt): name, first LBA, last LBA. Anything else: stop.
REFERENCE_LUN0 = {n: (int(f), int(l)) for n, f, l in (r.split(':') for r in (
    'persist:6:32773 klog:32774:36869 misc:36870:37125 frp:37126:37253 efs:37254:53637 efs_backup:53638:70021 '
    'modem_userdata:70022:86405 trusty_persist:86406:102789 trusty_userdata:102790:135557 metadata:135558:151941 '
    'boot_a:151942:168325 init_boot_a:168326:170373 vendor_boot_a:170374:186757 vendor_kernel_boot_a:186758:203141 '
    'dtbo_a:203142:207237 vbmeta_a:207238:207253 vbmeta_system_a:207254:207269 vbmeta_vendor_a:207270:207285 '
    'pvmfw_a:207286:207541 modem_a:207542:284341 boot_b:284342:300725 init_boot_b:300726:302773 '
    'vendor_boot_b:302774:319157 vendor_kernel_boot_b:319158:335541 dtbo_b:335542:339637 vbmeta_b:339638:339653 '
    'vbmeta_system_b:339654:339669 vbmeta_vendor_b:339670:339685 pvmfw_b:339686:339941 modem_b:339942:416741 '
    'super:416742:2499557 ufs_internal:2499558:2500581 bl_data:2500582:2500837 userdata_exp.ai:2500838:4597989 '
    'userdata:4597990:22757375 ios_system:22757376:29048831 ios_data:29048832:31147002').split())}
REFERENCE_LUN0_BLOCKS = 31147008
RATE = 140e6  # bytes/s for estimates: A7 hashed ios_system (24 GiB) in 176 s on the phone

LAYOUT_SCRIPT = ('for l in /dev/block/by-name/*; do t=$(readlink -f $l); b=${t##*/}; '
                 'if [ -e /sys/class/block/$b/start ]; then d=$(readlink -f /sys/class/block/$b/..); '
                 'echo "PART ${l##*/} $t ${d##*/} $(cat /sys/class/block/$b/start) $(cat /sys/class/block/$b/size)"; fi; done; '
                 'for d in /sys/block/sd*; do echo "DISK ${d##*/} $(cat $d/size)"; done')


class Refused(Exception):
    pass


def need(ok, why):
    if not ok: raise Refused(why)


def read_only(script):
    """Every command this tool sends: no output file, no redirection at all, no seek or conv, nothing that changes state."""
    s = script
    bad = [w for w in ('of=', 'seek=', 'conv=', '>', 'tee', 'rm ', 'mv ', 'cp ', 'blockdev', 'sgdisk', 'setprop', 'reboot', 'mkfs', 'fastboot', 'truncate', 'mount')
           if w in s]
    need(not bad, f'command is not read-only ({bad}): {script}')
    return script


def dd_part(first, count):
    """bs 1 MiB when the range is 1 MiB aligned, else 4096."""
    per = MiB // BLOCK
    if first % per == 0 and count % per == 0: return f'bs={MiB} skip={first // per} count={count // per}'
    return f'bs={BLOCK} skip={first} count={count}'


def region_script(r):
    """One region: resolve by name now, print the extent found, hash on the phone."""
    if r['kind'] == 'disk':
        pre = (f'P=$(readlink -f /dev/block/by-name/{r["anchor"]}); B=${{P##*/}}; [ -b "$P" ] || {{ echo "NOPART {r["anchor"]}"; exit 3; }}; '
               'D=$(readlink -f /sys/class/block/$B/..); D=${D##*/}; echo "DISK /dev/block/$D $(cat /sys/block/$D/size)"; ')
        src = '/dev/block/$D'
    else:
        pre = (f'P=$(readlink -f /dev/block/by-name/{r["part"]}); B=${{P##*/}}; [ -b "$P" ] || {{ echo "NOPART {r["part"]}"; exit 3; }}; '
               'echo "EXT $P $(cat /sys/class/block/$B/start) $(cat /sys/class/block/$B/size)"; ')
        src = '$P'
    dd = f'bs={MiB}' if r.get('whole') else dd_part(r['first'], r['count'])
    # The digest is echoed after the whole pipeline ends, so dd's byte count (stderr) and it never share a line.
    return read_only(pre + f'H=$(dd if={src} {dd} | sha256sum); echo "SHA $H"')


def adb_argv(adb, script):
    return [adb, 'shell', f"su -c '{script}'"]


def parse_layout(text):
    parts, disks = {}, {}
    for line in text.splitlines():
        f = line.split()
        if f[:1] == ['PART'] and len(f) == 6:
            need(f[1] not in parts, f'by-name {f[1]} twice')
            parts[f[1]] = dict(dev=f[2], disk_dev=f[3], start=int(f[4]), size=int(f[5]))
        elif f[:1] == ['DISK'] and len(f) == 3:
            disks[f[1]] = int(f[2])
    need(parts and disks, 'no partitions or disks in the layout output')
    for n, p in parts.items():
        need(p['disk_dev'] in disks, f'{n} is on {p["disk_dev"]}, which has no size')
        need(p['start'] % 8 == 0 and p['size'] % 8 == 0, f'{n} is not whole 4096-byte blocks')
    # Disk keys that do not depend on the letter: lun0 holds ios_data, the others are named by their first partition.
    keys = {}
    for dev in sorted({p['disk_dev'] for p in parts.values()}):
        names = sorted(n for n, p in parts.items() if p['disk_dev'] == dev)
        keys[dev] = 'lun0' if IOS_DATA in names else f'disk-of-{names[0]}'
    need(list(keys.values()).count('lun0') == 1, 'ios_data must be on exactly one disk')
    out_parts = {n: dict(disk=keys[p['disk_dev']], dev=p['dev'], first=p['start'] // 8, blocks=p['size'] // 8) for n, p in parts.items()}
    out_disks = {keys[d]: dict(dev=d, blocks=disks[d] // 8) for d in keys}
    return dict(parts=out_parts, disks=out_disks)


def check_reference(layout):
    lun0 = {n: (p['first'], p['first'] + p['blocks'] - 1) for n, p in layout['parts'].items() if p['disk'] == 'lun0'}
    need(lun0 == REFERENCE_LUN0, 'LUN 0 is not the A6 table: ' + json.dumps({n: [lun0.get(n), REFERENCE_LUN0.get(n)] for n in sorted(set(lun0) | set(REFERENCE_LUN0)) if lun0.get(n) != REFERENCE_LUN0.get(n)}))
    need(layout['disks']['lun0']['blocks'] == REFERENCE_LUN0_BLOCKS, f"LUN 0 is {layout['disks']['lun0']['blocks']} blocks, not {REFERENCE_LUN0_BLOCKS}")
    d = layout['parts'][IOS_DATA]
    need(d['blocks'] >= TABLE_FIRST + TABLE_BLOCKS + 1, 'ios_data is smaller than the store')


def plan(layout, quick=False):
    """The regions for this layout, in reading order."""
    regs = []
    def add(key, cls, **k): regs.append(dict(key=key, cls=cls, **k))
    for dk in sorted(layout['disks'], key=lambda k: (k != 'lun0', k)):
        ps = {n: p for n, p in layout['parts'].items() if p['disk'] == dk}
        if quick and dk != 'lun0': continue
        lo = min(p['first'] for p in ps.values()); hi = max(p['first'] + p['blocks'] for p in ps.values()); total = layout['disks'][dk]['blocks']
        anchor = IOS_DATA if dk == 'lun0' else min(ps)
        if lo: add(f'gpt:{dk}:head', 'must', kind='disk', anchor=anchor, first=0, count=lo)
        if total > hi: add(f'gpt:{dk}:tail', 'must', kind='disk', anchor=anchor, first=hi, count=total - hi)
    for n in sorted(layout['parts'], key=lambda n: (layout['parts'][n]['disk'] != 'lun0', layout['parts'][n]['disk'], layout['parts'][n]['first'])):
        p = layout['parts'][n]; b = p['blocks']
        if n == IOS_DATA:
            add('ios_data:block0', 'must', kind='part', part=n, first=0, count=TABLE_FIRST)
            add('ios_data:test', 'must', kind='part', part=n, first=TABLE_FIRST, count=TEST_BLOCKS)
            add('ios_data:slots', 'persist', kind='part', part=n, first=TABLE_FIRST + TEST_BLOCKS, count=2 * SLOT_BLOCKS)
            add('ios_data:rest', 'must', kind='part', part=n, first=TABLE_FIRST + TABLE_BLOCKS, count=b - TABLE_FIRST - TABLE_BLOCKS)
        elif n in BIG_LIVE:
            e = min(EDGE_BLOCKS, b)
            add(f'part:{n}:head', 'observed', kind='part', part=n, first=0, count=e)
            add(f'part:{n}:tail', 'observed', kind='part', part=n, first=b - e, count=e)
        elif n in MUST_WHOLE:
            add(f'part:{n}', 'must', kind='part', part=n, first=0, count=b, whole=True)
        elif not quick:
            add(f'part:{n}', 'observed', kind='part', part=n, first=0, count=b, whole=True)
    for r in regs: need(r['count'] > 0, f"{r['key']} is empty")
    return regs


def parse_hash(out, r, layout):
    """EXT/DISK line must equal the layout; sha256 and byte count from the phone."""
    lines = out.splitlines()
    need(not any(l.startswith('NOPART') for l in lines), f"{r['key']}: partition not found by name: {out.strip()}")
    sha = [m.group(1) for m in (re.match(r'^SHA ([0-9a-f]{64})(\s+-)?\s*$', l) for l in lines) if m]
    nbytes = [int(m.group(1)) for m in (re.match(r'^(\d+) bytes', l) for l in lines) if m]
    need(len(sha) == 1 and len(nbytes) == 1, f"{r['key']}: no single sha256 and byte count in: {out.strip()[:400]}")
    if r['kind'] == 'disk':
        d = [l.split() for l in lines if l.startswith('DISK ')]
        disk = layout['disks'][r['key'].split(':')[1]]
        need(len(d) == 1 and int(d[0][2]) // 8 == disk['blocks'], f"{r['key']}: disk size changed since the layout: {d}")
        dev = d[0][1]
    else:
        e = [l.split() for l in lines if l.startswith('EXT ')]; p = layout['parts'][r['part']]
        need(len(e) == 1 and int(e[0][2]) // 8 == p['first'] and int(e[0][3]) // 8 == p['blocks'], f"{r['key']}: extent changed since the layout: {e}")
        dev = e[0][1]
    need(nbytes[0] == r['count'] * BLOCK, f"{r['key']}: read {nbytes[0]} bytes, expected {r['count'] * BLOCK}")
    return dict(sha256=sha[0], bytes=nbytes[0], dev=dev)


class Phone:
    def __init__(self, adb, dry):
        self.adb, self.dry, self.sent = adb, dry, 0

    def sh(self, script, timeout=120, root=True):
        argv = adb_argv(self.adb, read_only(script)) if root else [self.adb, 'shell', read_only(script)]
        self.sent += 1
        if self.dry:
            print(shlex.join(argv)); return None
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.stdout + r.stderr


def reference_layout():
    """For --dry-run: LUN 0 as A6 left it. Other LUNs are read from the phone at run time."""
    parts = {n: dict(disk='lun0', dev='/dev/block/sdX%d' % i, first=f, blocks=l - f + 1) for i, (n, (f, l)) in enumerate(sorted(REFERENCE_LUN0.items(), key=lambda x: x[1][0]), 1)}
    return dict(parts=parts, disks=dict(lun0=dict(dev='sdX', blocks=REFERENCE_LUN0_BLOCKS)))


def snapshot(a):
    out = Path(a.out)
    need(a.dry_run or not out.exists(), f'{out} exists')
    need(a.dry_run or os.environ.get('ANDROID_SERIAL'), 'set ANDROID_SERIAL: one phone, named')
    ph = Phone(a.adb, a.dry_run)
    if a.dry_run:
        print('# Preflight (read-only):'); print(shlex.join([a.adb, 'get-state']), '     # expect device')
        ph.sh('getprop sys.boot_completed', root=False); ph.sh('getprop ro.boot.slot_suffix', root=False); ph.sh('id')
        print('# Layout (by-name -> device, disk, sysfs start/size in 512-byte units):'); ph.sh(LAYOUT_SCRIPT)
        layout = reference_layout()
    else:
        st = subprocess.run([a.adb, 'get-state'], capture_output=True, text=True, timeout=30).stdout.strip()
        need(st == 'device', f'adb state is {st!r}: Android must be booted')
        need(ph.sh('getprop sys.boot_completed', root=False).strip() == '1', 'Android has not completed boot')
        slot = ph.sh('getprop ro.boot.slot_suffix', root=False).strip()
        need('uid=0' in ph.sh('id'), 'su is not root')
        layout = parse_layout(ph.sh(LAYOUT_SCRIPT, timeout=60))
        check_reference(layout)
    regs = plan(layout, a.quick)
    total = sum(r['count'] for r in regs) * BLOCK
    if a.dry_run:
        print(f'# {len(regs)} region hashes, {total / 2**30:.1f} GiB read on the phone, about {total / RATE / 60:.0f} min (LUN 0 only shown;')
        print('#  partitions on the other LUNs are found by the layout step and hashed whole, with the same command).')
    snap = dict(tool='persist_check', version=1, label=out.stem, scope='quick' if a.quick else 'full', time=None if a.dry_run else time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), layout=layout, regions={})
    t0 = time.time()
    for i, r in enumerate(regs, 1):
        if a.dry_run: print(f"# {r['key']} ({r['cls']}, {r['count']} blocks)")
        o = ph.sh(region_script(r), timeout=max(120, int(r['count'] * BLOCK / 40e6)))
        if a.dry_run: continue
        h = parse_hash(o, r, layout)
        snap['regions'][r['key']] = dict(cls=r['cls'], first=r['first'], count=r['count'], **h)
        print(f"[{i}/{len(regs)} {time.time() - t0:.0f}s] {r['key']} {h['sha256'][:16]} {r['cls']}", file=sys.stderr)
    if a.dry_run: return 0
    snap['slot'] = slot
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(snap, indent=1, sort_keys=True) + '\n')
    print(f'wrote {out}: {len(regs)} regions, {total} bytes hashed on the phone, sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}')
    return 0


def layout_key(s):
    return {n: (p['disk'], p['first'], p['blocks']) for n, p in s['layout']['parts'].items()}, {k: d['blocks'] for k, d in s['layout']['disks'].items()}


def compare(before, after, control=None):
    res = dict(fail=[], review=[], churn=[], persist_written=None, verdict=None)
    if layout_key(before) != layout_key(after): res['fail'].append('layout: partitions, extents or disks differ')
    if control is not None and layout_key(before) != layout_key(control): res['fail'].append('layout: the control run differs')
    if before.get('scope') != after.get('scope'): res['fail'].append(f"scope {before.get('scope')} vs {after.get('scope')}")
    B, A, C = before['regions'], after['regions'], (control or {}).get('regions')
    for k in sorted(set(B) | set(A)):
        if k not in B or k not in A: res['fail'].append(f'{k}: hashed only {"after" if k in A else "before"}'); continue
        b, x = B[k], A[k]
        if b['cls'] != x['cls'] or (b['first'], b['count']) != (x['first'], x['count']): res['fail'].append(f'{k}: region definition differs'); continue
        same = b['sha256'] == x['sha256']
        if C is not None and k in C and b['cls'] in ('must', 'persist') and C[k]['sha256'] != b['sha256']:
            res['fail'].append(f'{k}: {b["cls"]} region changed in the Android-only control run: something other than iOS wrote it, stop')
        if b['cls'] == 'persist': res['persist_written'] = not same
        elif same: continue
        elif b['cls'] == 'must': res['fail'].append(f"{k}: changed ({b['sha256'][:16]} -> {x['sha256'][:16]})")
        elif C is not None and k in C and C[k]['sha256'] != b['sha256']: res['churn'].append(k)
        else: res['review'].append(f"{k}: changed and no control run explains it ({b['sha256'][:16]} -> {x['sha256'][:16]})")
    res['verdict'] = 'FAIL' if res['fail'] else 'REVIEW' if res['review'] else 'PASS'
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('snapshot'); s.add_argument('--out', required=True); s.add_argument('--quick', action='store_true')
    s.add_argument('--dry-run', action='store_true'); s.add_argument('--adb', default='adb')
    c = sub.add_parser('compare'); c.add_argument('--before', required=True); c.add_argument('--after', required=True); c.add_argument('--control')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'snapshot': return snapshot(a)
        load = lambda p: json.loads(Path(p).read_text())
        r = compare(load(a.before), load(a.after), load(a.control) if a.control else None)
        print(json.dumps(r, indent=1))
        print(r['verdict'], '| ios_data slots', 'WRITTEN' if r['persist_written'] else 'UNCHANGED' if r['persist_written'] is False else 'not hashed')
        return {'PASS': 0, 'FAIL': 1, 'REVIEW': 2}[r['verdict']]
    except Refused as e:
        print('refused: ' + str(e), file=sys.stderr); return 3
    except subprocess.TimeoutExpired as e:
        print(f'refused: adb timed out: {e}', file=sys.stderr); return 3


if __name__ == '__main__':
    sys.exit(main())
