#!/usr/bin/env python3
"""A7: put the canonical iOS root on the GPT partition ios_system. HOST ONLY: never talks to a device.

  ios_partition_flash.py check --head lba-0-7.bin --tail lba-31146990-31147007.bin --tail-lba 31146990
        --total-lbas 31147008 --disk-guid GUID --root IMG [--plan DIR] [--simg SIMG] [--out RECEIPT.json]
  ios_partition_flash.py sparse --root IMG --blocks N --out SIMG
  ios_partition_flash.py verify-stream --receipt RECEIPT.json [--image-only] < bytes-from-adb-dd

check: the fresh GPT dump is read with tools/gpt_plan.py's strict reader. It must hold exactly one ios_system with the
hackios type GUID, inside the usable range, starting above userdata's last LBA and overlapping nothing. The root must
be the pinned image and must fit. --plan DIR: the dump must also be the table that plan wrote (gpt-new-primary.bin,
and one of the backup variants). --simg: that sparse file must expand to the root followed by zeros, covering exactly
ios_system. The output is the receipt and the owner's commands.

sparse: an Android sparse image of the whole partition. RAW chunks for the root, FILL-zero chunks for zero runs and
for the tail after the root. Flashing it leaves ios_system as the root followed by zeros (the zero-padded tail rule),
so the readback can hash the whole extent.

verify-stream: compares what `dd` of the ios_system extent streams through `adb exec-out` with the root plus the zero
tail, and names the first differing block. --image-only compares just the root's bytes (the raw-flash route, where the
tail keeps whatever was there before).

The only accepted target is ios_system. userdata, userdata_exp.ai (a member of Android's /data) and anything
naming blazer_persist are refused."""
import argparse, hashlib, json, struct, sys
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent
sys.path.insert(0, str(X))  # python3 -I leaves the script's folder off the path
import gpt_plan as G

LBA = G.LBA
TARGET = 'ios_system'
ROOT_SHA = '205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7'  # ios26-phone-r3, = image_tool.PHONE_ROOT_SHA
MiB = 1 << 20
SPARSE = struct.Struct('<IHHHHIIII'); CHUNK = struct.Struct('<HHII'); RAW, FILL = 0xCAC1, 0xCAC2
RAW_MAX = 65536  # blocks per RAW chunk (256 MiB): far below the format's 32-bit chunk size
Refused = G.Refused
need = G.need


def refuse_target(name):
    low = name.lower()
    need('blazer_persist' not in low, f'{name}: blazer_persist stays refused until the ios_data writer passes its QEMU negative test')
    need(low not in ('userdata', 'userdata_exp.ai') and not low.startswith('userdata'), f'{name} is Android storage (/data): never a target')
    need(name == TARGET, f'{name}: the only target is {TARGET}')


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while (b := f.read(4 * MiB)): h.update(b)
    return h.hexdigest()


def padded_sha(root, total_blocks):
    """sha256 of the root followed by zeros up to total_blocks: what the partition holds after the sparse flash."""
    h = hashlib.sha256(); n = 0
    with open(root, 'rb') as f:
        while (b := f.read(4 * MiB)): h.update(b); n += len(b)
    left = total_blocks * LBA - n; need(left >= 0, 'root larger than the partition'); z = bytes(4 * MiB)
    while left: k = min(left, len(z)); h.update(z[:k]); left -= k
    return h.hexdigest()


def check_table(disk, disk_guid, target=TARGET):
    """Strict table read, then the ios_system rules. Returns (table, ios_system entry, userdata entry)."""
    refuse_target(target)
    t = G.read_table(disk, disk_guid)
    used = [e for e in t['entries'] if e['type'].int]
    sysp = [e for e in used if e['name'] == target]
    need(sysp, f'no {target} in the GPT: run A6 first')
    need(len(sysp) == 1, f'{len(sysp)} entries named {target}')
    s = sysp[0]
    need(s['type'] == G.IOS_TYPE, f"{target} type GUID is {s['type']}, not the hackios {G.IOS_TYPE}")
    need(s['attrs'] == 0, f'{target} has attribute bits {s["attrs"]:#x}')
    ud = [e for e in used if e['name'] == 'userdata']
    need(len(ud) == 1, 'exactly one userdata entry required')
    ud = ud[0]
    need(s['first'] > ud['last'], f"{target} starts at {s['first']}, not above userdata's last LBA {ud['last']}")
    p = t['primary']
    need(p['first'] <= s['first'] <= s['last'] <= p['last'], f'{target} outside the usable range')
    for e in used:
        if e is not s:
            need(e['last'] < s['first'] or e['first'] > s['last'], f"{target} overlaps {e['name']}")
    return t, s, ud


def check_plan(disk, plan_dir, s):
    """The dump is exactly what gpt_plan wrote: primary LBA 1..5 and one backup variant, and the same ios_system extent."""
    d = Path(plan_dir); m = json.loads((d / 'plan.json').read_text())
    for f, v in m['files'].items():
        need(hashlib.sha256((d / f).read_bytes()).hexdigest() == v['sha256'], f'{f} differs from plan.json')
    prim = (d / 'gpt-new-primary.bin').read_bytes(); w = m['writes']
    need(disk.block(w['primary']['seek'], w['primary']['count']) == prim, 'the dump is not the planned primary table')
    back = disk.block(w['backup']['seek'], w['backup']['count'])
    variant = next((v for v in ('media', 'zero') if back == (d / f'gpt-new-backup-{v}.bin').read_bytes()), None)
    need(variant is not None, 'the dump is not either planned backup table')
    L = m['layout'][TARGET]
    need((L['first'], L['last']) == (s['first'], s['last']), f"{TARGET} {s['first']}..{s['last']} differs from the plan {L['first']}..{L['last']}")
    return dict(plan=str(d), backup_variant=variant)


def dd_args(first, blocks):
    """bs=1 MiB when the extent is 1 MiB aligned (8 MiB here), else 4096."""
    per = MiB // LBA
    if first % per == 0 and blocks % per == 0: return dict(bs=MiB, skip=first // per, count=blocks // per)
    return dict(bs=LBA, skip=first, count=blocks)


def check(disk, disk_guid, root, root_sha=ROOT_SHA, plan_dir=None, simg=None, target=TARGET):
    t, s, ud = check_table(disk, disk_guid, target)
    size = Path(root).stat().st_size
    need(size and size % LBA == 0, f'{root} is not whole 4096-byte blocks')
    rblocks = size // LBA; pblocks = s['last'] - s['first'] + 1
    need(rblocks <= pblocks, f'root is {rblocks} blocks, {target} only {pblocks}')
    got = sha_file(root)
    need(got == root_sha, f'root sha256 is {got}, not the pinned {root_sha}')
    rec = dict(scope='HOST check of a GPT dump; nothing was written to any device', target=target,
               lun=0, block_bytes=LBA, first_lba=s['first'], last_lba=s['last'], blocks=pblocks,
               unique_guid=str(s['unique']), type_guid=str(s['type']), entry_index=s['index'],
               userdata=dict(first=ud['first'], last=ud['last']), entries=len(t['entries']), pad_policy=t['pad_policy'],
               root=str(root), root_sha256=got, root_blocks=rblocks, tail_blocks=pblocks - rblocks,
               padded_sha256=padded_sha(root, pblocks), dd=dd_args(s['first'], pblocks), dd_root=dd_args(s['first'], rblocks),
               sysfs=dict(start_512=s['first'] * (LBA // 512), size_512=pblocks * (LBA // 512)))
    data = [e for e in t['entries'] if e['name'] == 'ios_data']
    rec['ios_data'] = dict(first=data[0]['first'], last=data[0]['last'], hackios_type=data[0]['type'] == G.IOS_TYPE) if len(data) == 1 else None
    if plan_dir: rec.update(check_plan(disk, plan_dir, s))
    if simg: rec['simg'] = check_simg(simg, rec)
    return rec


def write_sparse(root, blocks, out):
    """RAW for data, FILL 0 for zero runs and the tail. Exactly `blocks` blocks; no DONT_CARE (a hole keeps old bytes)."""
    out = Path(out); need(not out.exists(), f'{out} exists')
    size = Path(root).stat().st_size; need(size % LBA == 0, 'root is not whole blocks'); rb = size // LBA
    need(rb <= blocks, 'root larger than the partition')
    chunks = 0; zero = bytes(LBA)
    with open(root, 'rb') as f, open(out, 'wb') as o:
        o.write(SPARSE.pack(0xED26FF3A, 1, 0, SPARSE.size, CHUNK.size, LBA, blocks, 0, 0))
        run_kind, run = None, []          # pending RAW blocks, or a zero-run count

        def flush():
            nonlocal chunks, run_kind, run
            if run_kind == RAW:
                o.write(CHUNK.pack(RAW, 0, len(run), CHUNK.size + len(run) * LBA)); o.write(b''.join(run)); chunks += 1
            elif run_kind == FILL:
                o.write(CHUNK.pack(FILL, 0, run, CHUNK.size + 4)); o.write(b'\0' * 4); chunks += 1
            run_kind, run = None, []

        for _ in range(rb):
            b = f.read(LBA)
            if b == zero:
                if run_kind != FILL: flush(); run_kind, run = FILL, 0
                run += 1
            else:
                if run_kind != RAW or len(run) >= RAW_MAX: flush(); run_kind, run = RAW, []
                run.append(b)
        if blocks > rb:
            if run_kind != FILL: flush(); run_kind, run = FILL, 0
            run += blocks - rb
        flush()
        o.seek(0); o.write(SPARSE.pack(0xED26FF3A, 1, 0, SPARSE.size, CHUNK.size, LBA, blocks, chunks, 0))
    return chunks


def check_simg(simg, rec):
    """Expanded with phone_write.walk (independent reader, standard header only, DONT_CARE refused)."""
    import phone_write as PW
    try: w = PW.walk(simg, want_blocks=rec['blocks'])
    except PW.Bad as e: raise Refused(f'sparse image: {e}')
    need(w['sha256'] == rec['padded_sha256'], 'sparse image does not expand to the root plus a zero tail')
    return dict(path=str(simg), simg_sha256=w['simg_sha256'], chunks=w['chunks'], kinds=w['kinds'], expands_to=w['sha256'])


def verify_stream(stream, rec, image_only=False):
    """What the phone streamed against the root (and the zero tail). Never reads more than the extent plus one byte."""
    want_blocks = rec['root_blocks'] if image_only else rec['blocks']; total = want_blocks * LBA
    h = hashlib.sha256(); n = 0; first_bad = None; bad_blocks = 0
    with open(rec['root'], 'rb') as f:
        while n < total:
            d = stream.read(min(4 * MiB, total - n))
            if not d: break
            ref = f.read(len(d)); ref += bytes(len(d) - len(ref))
            if d != ref:
                for i in range(0, len(d), LBA):
                    if d[i:i + LBA] != ref[i:i + LBA]:
                        bad_blocks += 1
                        if first_bad is None: first_bad = (n + i) // LBA
            h.update(d); n += len(d)
    extra = bool(stream.read(1))
    want_sha = rec['root_sha256'] if image_only else rec['padded_sha256']
    probs = []
    if n != total: probs.append(f'stream is {n} bytes, extent is {total}')
    if extra: probs.append('stream is longer than the extent')
    if first_bad is not None: probs.append(f'{bad_blocks} blocks differ, first at partition block {first_bad} (LBA {rec["first_lba"] + first_bad})')
    if n == total and h.hexdigest() != want_sha: probs.append('sha256 differs')
    return dict(ok=not probs, bytes=n, sha256=h.hexdigest(), want_sha256=want_sha, image_only=image_only, problems=probs)


def commands(rec, a):
    """The owner's commands for this receipt. Attended: the flash. Everything else is a read."""
    d, r = rec['dd'], rec['dd_root']; simg = rec.get('simg', {}).get('path', '<SIMG from the sparse step>')
    part = f"0x{rec['blocks'] * LBA:x}"
    return '\n'.join([
        '# Preflight, in fastboot (read-only getvars):',
        f'fastboot getvar partition-size:{TARGET}     # expect {part}',
        f'fastboot getvar has-slot:{TARGET}           # expect no',
        f'fastboot getvar partition-type:{TARGET}     # any answer; record it',
        '# ATTENDED write, the only one (sparse: the root then zeros to the end of the partition):',
        f'fastboot flash {TARGET} {simg}',
        'fastboot reboot',
        '# In Android (read-only):',
        f"adb shell su -c 'readlink -f /dev/block/by-name/{TARGET}'     # expect /dev/block/sda{rec['entry_index']}",
        f"adb shell cat /sys/class/block/sda{rec['entry_index']}/start /sys/class/block/sda{rec['entry_index']}/size     # expect {rec['sysfs']['start_512']} and {rec['sysfs']['size_512']} (512-byte units)",
        f"adb exec-out su -c 'dd if=/dev/block/sda bs={d['bs']} skip={d['skip']} count={d['count']} 2>/dev/null' | python3 -I tools/ios_partition_flash.py verify-stream --receipt {a.out or 'RECEIPT.json'}",
        f"#   expect PASS, sha256 {rec['padded_sha256']}",
        '# Raw-flash route only (tail not zeroed): compare the root part alone:',
        f"#   adb exec-out su -c 'dd if=/dev/block/sda bs={r['bs']} skip={r['skip']} count={r['count']} 2>/dev/null' | python3 -I tools/ios_partition_flash.py verify-stream --receipt {a.out or 'RECEIPT.json'} --image-only",
    ])


def disk_from(a):
    return G.Disk(Path(a.head).read_bytes(), Path(a.tail).read_bytes(), a.tail_lba, a.total_lbas)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check')
    for k in ('--head', '--tail', '--disk-guid', '--root'): c.add_argument(k, required=True)
    c.add_argument('--tail-lba', type=int, required=True); c.add_argument('--total-lbas', type=int, required=True)
    c.add_argument('--plan'); c.add_argument('--simg'); c.add_argument('--out'); c.add_argument('--target', default=TARGET)
    s = sub.add_parser('sparse'); s.add_argument('--root', required=True); s.add_argument('--blocks', type=int, required=True); s.add_argument('--out', required=True)
    v = sub.add_parser('verify-stream'); v.add_argument('--receipt', required=True); v.add_argument('--image-only', action='store_true')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'check':
            rec = check(disk_from(a), a.disk_guid, a.root, plan_dir=a.plan, simg=a.simg, target=a.target)
            if a.out:
                o = Path(a.out); need(not o.exists(), f'{o} exists'); o.write_text(json.dumps(rec, indent=1) + '\n')
            print(json.dumps(rec, indent=1)); print('OK'); print(commands(rec, a))
        elif a.cmd == 'sparse':
            sha = sha_file(a.root); need(sha == ROOT_SHA, f'root sha256 is {sha}, not the pinned {ROOT_SHA}')
            n = write_sparse(a.root, a.blocks, a.out); print('wrote', a.out, 'chunks', n, 'sha256', sha_file(a.out))
        else:
            rec = json.loads(Path(a.receipt).read_text()); refuse_target(rec['target'])
            r = verify_stream(sys.stdin.buffer, rec, a.image_only); print(json.dumps(r)); print('PASS' if r['ok'] else 'FAIL')
            return 0 if r['ok'] else 1
    except Refused as e:
        sys.exit('refused: ' + str(e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
