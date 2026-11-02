#!/usr/bin/env python3
"""A4 storage plan for the Pixel 10 Pro LUN0 GPT (4096-byte LBAs). HOST ONLY.

Reads the A0 raw dumps, verifies the table strictly, and emits a new table
that keeps every entry byte-identical except `userdata` (same first LBA, new
last LBA) and two appended entries `ios_system` and `ios_data` (fresh unique
GUIDs, the project type GUID, 8 MiB-aligned starts). Output bytes exist only
for LBA 1..5 (primary header + array) and the last five LBAs (backup array +
header); the tool refuses to produce a byte for any other LBA.

  gpt_plan.py plan --head lba-0-7.bin --tail lba-31146990-31147007.bin --tail-lba 31146990
                   --total-lbas 31147008 --disk-guid GUID --ios-system-gib 24 --ios-data-gib 8 --out DIR
  gpt_plan.py verify --head ... --tail ... --tail-lba ... --total-lbas ... --disk-guid GUID --out DIR

`plan` writes gpt-new-primary.bin (LBA 1..5), gpt-new-backup-media.bin and
gpt-new-backup-zero.bin (last 5 LBAs; the backup header block's tail either
repeats the entry array prefix as observed on this media, or is UEFI zero),
gpt-old-*.bin (the same LBAs as found, for the no-op proof and rollback) and
plan.json. `verify` re-reads DIR and refuses any difference from the old
table other than the intended ones."""
import argparse, hashlib, json, struct, sys, uuid, zlib
from pathlib import Path

LBA = 4096
ENTRY = 128
HDR = 92
ALIGN_LBAS = (8 << 20) // LBA            # 8 MiB
GIB_LBAS = (1 << 30) // LBA
# hackios iOS-owned partition type: uuid5(URL, 'hackios:ios-owned-partition'); no OS knows it.
IOS_TYPE = uuid.uuid5(uuid.NAMESPACE_URL, 'hackios:ios-owned-partition')
NEW_NAMES = ('ios_system', 'ios_data')


class Refused(Exception):
    pass


def need(c, why):
    if not c:
        raise Refused(why)


def crc(b):
    return zlib.crc32(b) & 0xffffffff


def parse_header(blk, my_lba):
    need(len(blk) == LBA, 'short header block')
    need(blk[:8] == b'EFI PART', f'no GPT signature at LBA {my_lba}')
    rev, hs, hcrc = struct.unpack_from('<III', blk, 8)
    need(rev == 0x10000 and hs == HDR, 'unexpected GPT revision or header size')
    h = bytearray(blk[:HDR]); h[16:20] = b'\0' * 4
    need(crc(bytes(h)) == hcrc, f'header CRC mismatch at LBA {my_lba}')
    need(blk[20:24] == b'\0' * 4, 'header reserved field nonzero')
    cur, alt, first, last = struct.unpack_from('<QQQQ', blk, 24)
    disk = uuid.UUID(bytes_le=bytes(blk[56:72]))
    elba, n, esz, acrc = struct.unpack_from('<QIII', blk, 72)
    need(cur == my_lba, f'header at LBA {my_lba} claims LBA {cur}')
    need(esz == ENTRY, 'entry size is not 128')
    return dict(cur=cur, alt=alt, first=first, last=last, disk=disk, entries_lba=elba, count=n, array_crc=acrc,
                pad=bytes(blk[HDR:]))


def parse_entries(arr, n):
    out = []
    for i in range(n):
        e = arr[i * ENTRY:(i + 1) * ENTRY]
        t = uuid.UUID(bytes_le=bytes(e[:16])); u = uuid.UUID(bytes_le=bytes(e[16:32]))
        f, l, at = struct.unpack_from('<QQQ', e, 32)
        name = e[56:128].decode('utf-16le').split('\0')[0]
        out.append(dict(index=i + 1, type=t, unique=u, first=f, last=l, attrs=at, name=name, raw=bytes(e)))
    return out


class Disk:
    """The A0 dumps: blocks [0, len(head)) and [tail_lba, total)."""

    def __init__(self, head, tail, tail_lba, total):
        need(len(head) % LBA == 0 and len(tail) % LBA == 0, 'dump not a whole number of 4096-byte blocks')
        need(len(head) >= 6 * LBA, 'head dump must cover LBA 0..5')
        need(tail_lba + len(tail) // LBA == total, 'tail dump does not end at the last LBA')
        need(len(tail) >= 5 * LBA, 'tail dump must cover the last 5 LBAs')
        self.head, self.tail, self.tail_lba, self.total = head, tail, tail_lba, total

    def block(self, lba, n=1):
        if lba + n <= len(self.head) // LBA:
            return self.head[lba * LBA:(lba + n) * LBA]
        need(lba >= self.tail_lba and lba + n <= self.total, f'LBA {lba} not in the dumps')
        o = (lba - self.tail_lba) * LBA
        return self.tail[o:o + n * LBA]


def read_table(disk, disk_guid):
    """Strict read of both copies. Returns the table and the observed backup padding policy."""
    total = disk.total
    p = parse_header(disk.block(1), 1)
    need(p['alt'] == total - 1, 'primary header alternate LBA is not the last LBA')
    b = parse_header(disk.block(total - 1), total - 1)
    need(b['alt'] == 1, 'backup header alternate LBA is not 1')
    need(str(p['disk']) == disk_guid and str(b['disk']) == disk_guid, 'disk GUID differs from the expected one')
    for k in ('first', 'last', 'count', 'array_crc'):
        need(p[k] == b[k], f'primary and backup header differ in {k}')
    need(p['entries_lba'] == 2, 'primary entries not at LBA 2')
    asz = p['count'] * ENTRY
    nblk = -(-asz // LBA)
    need(b['entries_lba'] + nblk <= total - 1, 'backup array overlaps backup header')
    parr = disk.block(2, nblk)[:asz]; barr = disk.block(b['entries_lba'], nblk)[:asz]
    need(crc(parr) == p['array_crc'], 'primary entry array CRC mismatch')
    need(crc(barr) == b['array_crc'], 'backup entry array CRC mismatch')
    need(parr == barr, 'primary and backup entry arrays differ')
    need(p['first'] > 2 + nblk - 1 and p['first'] >= 6, 'first usable LBA overlaps the primary array')
    need(p['last'] < b['entries_lba'], 'last usable LBA overlaps the backup array')
    need(not any(p['pad']), 'nonzero primary header padding')
    # Observed on this media (A0): the backup header block's bytes 92.. repeat the entry array prefix.
    if not any(b['pad']):
        pad_policy = 'zero'
    else:
        need(b['pad'] == parr[:len(b['pad'])], 'backup header padding is neither zero nor the entry array prefix')
        pad_policy = 'entry-prefix'
    ents = parse_entries(parr, p['count'])
    used = sorted((e for e in ents if e['type'].int), key=lambda e: e['first'])
    for e in used:
        need(p['first'] <= e['first'] <= e['last'] <= p['last'], f"{e['name']} outside the usable range")
    for x, y in zip(used, used[1:]):
        need(x['last'] < y['first'], f"{x['name']} overlaps {y['name']}")
    names = [e['name'] for e in used]
    need(len(set(names)) == len(names), 'duplicate partition names')
    need(len({e['unique'] for e in used}) == len(used), 'duplicate unique GUIDs')
    return dict(primary=p, backup=b, entries=ents, array_blocks=nblk, pad_policy=pad_policy,
                backup_pad_len=len(b['pad']))


def build_header(src, cur, alt, elba, count, array_crc):
    h = bytearray(HDR)
    h[:8] = b'EFI PART'
    struct.pack_into('<III', h, 8, 0x10000, HDR, 0)
    struct.pack_into('<QQQQ', h, 24, cur, alt, src['first'], src['last'])
    h[56:72] = src['disk'].bytes_le
    struct.pack_into('<QIII', h, 72, elba, count, ENTRY, array_crc)
    struct.pack_into('<I', h, 16, crc(bytes(h)))
    return bytes(h)


def entry_bytes(type_guid, unique, first, last, name):
    e = bytearray(ENTRY)
    e[:16] = type_guid.bytes_le; e[16:32] = unique.bytes_le
    struct.pack_into('<QQQ', e, 32, first, last, 0)
    n = name.encode('utf-16le'); need(len(n) <= 72, 'name too long')
    e[56:56 + len(n)] = n
    return bytes(e)


def plan(disk, disk_guid, sys_gib, data_gib, guids=None):
    t = read_table(disk, disk_guid)
    p = t['primary']; total = disk.total
    ents = t['entries']
    need(all(e['type'].int for e in ents), 'table has an empty slot: this plan assumes a full table')
    need(all(e['name'] not in NEW_NAMES for e in ents), 'ios_* already present')
    ud = [e for e in ents if e['name'] == 'userdata']
    need(len(ud) == 1, 'exactly one userdata entry required')
    ud = ud[0]
    need(ud['last'] == p['last'], 'userdata does not end at the last usable LBA')
    need(sys_gib >= 1 and data_gib >= 1, 'iOS partitions must be at least 1 GiB')
    data_lbas = data_gib * GIB_LBAS; sys_lbas = sys_gib * GIB_LBAS
    d0 = (p['last'] + 1 - data_lbas) // ALIGN_LBAS * ALIGN_LBAS
    s0 = d0 - sys_lbas
    need(s0 % ALIGN_LBAS == 0 and d0 % ALIGN_LBAS == 0, 'alignment')
    new_ud_last = s0 - 1
    need(new_ud_last > ud['first'] + 8 * GIB_LBAS, 'userdata would be smaller than 8 GiB')
    count = len(ents) + 2
    nblk = -(-count * ENTRY // LBA)
    need(2 + nblk <= p['first'], 'new primary array overlaps the first usable LBA')
    # Keep the backup array where it is (no byte outside the last 5 LBAs is written).
    belba = t['backup']['entries_lba']
    need(belba + nblk <= total - 1, 'new backup array overlaps the backup header')
    g = guids or (uuid.uuid4(), uuid.uuid4())
    need(len(set(g)) == 2 and all(x not in {e['unique'] for e in ents} for x in g), 'new GUIDs not unique')
    arr = bytearray()
    for e in ents:
        if e is ud:
            r = bytearray(e['raw']); struct.pack_into('<Q', r, 40, new_ud_last); arr += r
        else:
            arr += e['raw']
    arr += entry_bytes(IOS_TYPE, g[0], s0, d0 - 1, 'ios_system')
    arr += entry_bytes(IOS_TYPE, g[1], d0, p['last'], 'ios_data')
    acrc = crc(bytes(arr))
    parr_blocks = bytes(arr) + b'\0' * ((p['first'] - 2) * LBA - len(arr))     # LBA 2..first-1
    phdr = build_header(p, 1, total - 1, 2, count, acrc)
    primary = phdr + b'\0' * (LBA - HDR) + parr_blocks
    need(len(primary) == (p['first'] - 1) * LBA, 'primary length')
    barr_blocks = bytes(arr) + b'\0' * ((total - 1 - belba) * LBA - len(arr))
    bhdr = build_header(p, total - 1, 1, belba, count, acrc)
    tail_pad = LBA - HDR
    backup_media = barr_blocks + bhdr + bytes(arr)[:tail_pad] + b'\0' * (tail_pad - min(tail_pad, len(arr)))
    backup_zero = barr_blocks + bhdr + b'\0' * tail_pad
    old_primary = disk.block(1, p['first'] - 1)
    old_backup = disk.block(belba, total - belba)
    need(len(backup_media) == len(old_backup) == len(backup_zero), 'backup length')
    layout = dict(userdata=(ud['first'], new_ud_last), ios_system=(s0, d0 - 1), ios_data=(d0, p['last']))
    return dict(table=t, primary=primary, backup_media=backup_media, backup_zero=backup_zero,
                old_primary=old_primary, old_backup=old_backup, primary_lba=1, backup_lba=belba,
                layout=layout, guids=[str(x) for x in g], count=count, array=bytes(arr))


def check_new(disk, disk_guid, primary, backup, primary_lba, backup_lba):
    """Strictly re-read old dumps and the new bytes; refuse anything but the intended change."""
    t = read_table(disk, disk_guid)
    total = disk.total
    need(primary_lba == 1 and len(primary) == (t['primary']['first'] - 1) * LBA, 'primary bytes must be exactly LBA 1..first-1')
    need(backup_lba == t['backup']['entries_lba'] and backup_lba + len(backup) // LBA == total, 'backup bytes must be exactly the backup array LBAs + header')
    need(primary_lba >= 1 and primary_lba + len(primary) // LBA <= t['primary']['first'], 'byte inside the usable range (primary side)')
    need(backup_lba > t['primary']['last'], 'byte inside the usable range (backup side)')
    head = disk.block(0) + primary + disk.head[(1 + len(primary) // LBA) * LBA:]
    tail = disk.tail[:(backup_lba - disk.tail_lba) * LBA] + backup
    nd = Disk(head, tail, disk.tail_lba, total)
    n = read_table(nd, disk_guid)
    old = {e['name']: e for e in t['entries']}
    new = {e['name']: e for e in n['entries']}
    need(set(new) - set(old) == set(NEW_NAMES), 'new table adds something other than ios_system and ios_data')
    need(set(old) <= set(new), 'new table drops an entry')
    for i, e in enumerate(t['entries']):
        ne = n['entries'][i]
        if e['name'] == 'userdata':
            r = bytearray(e['raw']); r[40:48] = ne['raw'][40:48]
            need(bytes(r) == ne['raw'], 'userdata changed beyond its last LBA')
            need(ne['last'] < e['last'] and ne['first'] == e['first'], 'userdata must keep its first LBA and shrink')
        else:
            need(ne['raw'] == e['raw'], f"entry {e['name']} is not byte-identical")
    for nm in NEW_NAMES:
        e = new[nm]
        need(e['type'] == IOS_TYPE and e['attrs'] == 0, f'{nm} type/attributes')
        need(e['first'] % ALIGN_LBAS == 0, f'{nm} not 8 MiB aligned')
        need(e['first'] > new['userdata']['last'], f'{nm} not after userdata')
    need(new['ios_data']['last'] == t['primary']['last'], 'ios_data must end at the last usable LBA')
    for k in ('first', 'last', 'disk'):
        need(n['primary'][k] == t['primary'][k], f'header {k} changed')
    return n


def load(a):
    return Disk(Path(a.head).read_bytes(), Path(a.tail).read_bytes(), a.tail_lba, a.total_lbas)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def cmd_plan(a):
    disk = load(a)
    r = plan(disk, a.disk_guid, a.ios_system_gib, a.ios_data_gib)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=False)
    files = {'gpt-new-primary.bin': r['primary'], 'gpt-new-backup-media.bin': r['backup_media'],
             'gpt-new-backup-zero.bin': r['backup_zero'], 'gpt-old-primary.bin': r['old_primary'],
             'gpt-old-backup.bin': r['old_backup']}
    for f, b in files.items():
        (out / f).write_bytes(b)
    for variant in ('media', 'zero'):
        check_new(disk, a.disk_guid, r['primary'], r[f'backup_{variant}'], r['primary_lba'], r['backup_lba'])
    lay = {k: dict(first=v[0], last=v[1], lbas=v[1] - v[0] + 1, gib=round((v[1] - v[0] + 1) / GIB_LBAS, 3)) for k, v in r['layout'].items()}
    rec = dict(scope='HOST plan from A0 dumps; nothing written to any device', total_lbas=disk.total, lba_bytes=LBA,
               disk_guid=a.disk_guid, old_entries=len(r['table']['entries']), new_entries=r['count'],
               observed_backup_padding=r['table']['pad_policy'], ios_type_guid=str(IOS_TYPE), new_unique_guids=r['guids'],
               layout=lay, writes=dict(primary=dict(seek=r['primary_lba'], count=len(r['primary']) // LBA),
                                       backup=dict(seek=r['backup_lba'], count=len(r['backup_media']) // LBA)),
               files={f: dict(sha256=sha(b), bytes=len(b)) for f, b in files.items()},
               verified=['strict old table', 'new table strict re-read (both padding variants)', 'only intended changes'])
    (out / 'plan.json').write_text(json.dumps(rec, indent=1) + '\n')
    (out / 'SHA256SUMS').write_text(''.join(f'{sha(b)}  {f}\n' for f, b in files.items()))
    print(json.dumps(lay)); print('wrote', out)


def cmd_verify(a):
    disk = load(a); d = Path(a.out); m = json.loads((d / 'plan.json').read_text())
    for f, v in m['files'].items():
        need(sha((d / f).read_bytes()) == v['sha256'], f'{f} hash differs from plan.json')
    p = (d / 'gpt-new-primary.bin').read_bytes()
    for variant in ('media', 'zero'):
        n = check_new(disk, a.disk_guid, p, (d / f'gpt-new-backup-{variant}.bin').read_bytes(),
                      m['writes']['primary']['seek'], m['writes']['backup']['seek'])
    need(disk.block(1, len(p) // LBA) == (d / 'gpt-old-primary.bin').read_bytes(), 'old primary copy differs from the dump')
    print('OK', d, 'entries', len(n['entries']), 'padding', n['pad_policy'])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('plan', 'verify'):
        s = sub.add_parser(name)
        s.add_argument('--head', required=True); s.add_argument('--tail', required=True)
        s.add_argument('--tail-lba', type=int, required=True); s.add_argument('--total-lbas', type=int, required=True)
        s.add_argument('--disk-guid', required=True); s.add_argument('--out', required=True)
        if name == 'plan':
            s.add_argument('--ios-system-gib', type=int, required=True); s.add_argument('--ios-data-gib', type=int, required=True)
    a = ap.parse_args(argv)
    try:
        cmd_plan(a) if a.cmd == 'plan' else cmd_verify(a)
    except Refused as e:
        sys.exit('refused: ' + str(e))


if __name__ == '__main__':
    main()
