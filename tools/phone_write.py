#!/usr/bin/env python3
"""Checks around the one write of a root to userdata_exp.ai. HOST ONLY: never talks to a device. handoffs/phone-write.md.

  phone_write.py check-simg SIMG IMG [--restore]   SIMG expands to exactly IMG's bytes; only standard chunks
  phone_write.py check-restore SIMG                staging.simg: standard, leaves the rest of the partition alone
  phone_write.py gpt ATTEMPT MANIFEST              the capture's GPT row: one target, expected place and size
  phone_write.py fullcheck ATTEMPT MANIFEST        the whole partition, CRC per 64 MiB and overall. The check that counts
  phone_write.py soak ATTEMPT MANIFEST             N passes all finished and read the same bytes
  phone_write.py readback ATTEMPT MANIFEST         capture's CRCs equal the root's blocks; exit 1 on any mismatch
  phone_write.py compare-image ATTEMPT MANIFEST IMG  same, against any image, for the blocks the boot read (restore check)"""
import hashlib, json, re, struct, subprocess, sys, zlib, importlib.util
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; ROOT = X.parent; R = ROOT/'research'
sys.path.insert(0, str(X))  # python3 -I leaves the script's folder off the path
BLOCK = 4096; TARGET = 'userdata_exp.ai'; FIRST, LAST = 2500838, 4597989; BLOCKS = LAST - FIRST + 1; BYTES = BLOCKS * BLOCK
SPARSE = struct.Struct('<IHHHHIIII'); CHUNK = struct.Struct('<HHII'); RAW, FILL, DONT_CARE = 0xCAC1, 0xCAC2, 0xCAC3
SAMPLES = 7; KERNEL_BLOCKS = (0, 1, 2, 3, 4096, 65536, 131072, 262144, 400000, 524288, 604000, 604671)
STAGING = R/'laguna-usb-fix/ufs-staging/staging.img'
class Bad(Exception): pass

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while (b := f.read(1 << 22)): h.update(b)
    return h.hexdigest()

def walk(path, other=None, allow_dont_care=False, want_blocks=BLOCKS):
    """Expand a sparse file independently of what wrote it. 'other': compare with these bytes as we go. No block is kept in memory."""
    out = hashlib.sha256(); kinds = {}
    with open(path, 'rb') as f:
        head = f.read(SPARSE.size)
        if len(head) < SPARSE.size: raise Bad('too short')
        magic, major, minor, fhdr, chdr, bs, total, chunks, _ = SPARSE.unpack(head)
        # The Oct 28 write used a non-standard header and wasn't there afterwards (HANDOFF.md): only this exact shape passes.
        if (magic, major, minor, fhdr, chdr, bs) != (0xED26FF3A, 1, 0, 28, 12, BLOCK): raise Bad(f'non-standard sparse header {magic:#x} {major} {minor} {fhdr} {chdr} {bs}')
        if total != want_blocks: raise Bad(f'{total} blocks, partition has {want_blocks}')
        cmp = open(other, 'rb') if other else None
        pos = 0
        for i in range(chunks):
            raw = f.read(CHUNK.size)
            if len(raw) < CHUNK.size: raise Bad('truncated chunk header')
            kind, rsvd, count, size = CHUNK.unpack(raw); kinds[kind] = kinds.get(kind, 0) + count
            if rsvd or not count or pos + count > total: raise Bad(f'chunk {i} shape')
            left = count * BLOCK
            if kind == RAW:
                if size != 12 + left: raise Bad(f'chunk {i} size')
                while left:
                    d = f.read(min(left, 1 << 22))
                    if not d: raise Bad('truncated data')
                    out.update(d); left -= len(d)
                    if cmp and cmp.read(len(d)) != d: raise Bad(f'bytes differ near block {pos}')
            elif kind == FILL:
                if size != 16: raise Bad(f'chunk {i} size')
                fill = f.read(4) * (1 << 20)
                while left:
                    d = fill[:min(left, 1 << 22)]; out.update(d); left -= len(d)
                    if cmp and cmp.read(len(d)) != d: raise Bad(f'bytes differ near block {pos}')
            elif kind == DONT_CARE:
                if size != 12: raise Bad(f'chunk {i} size')
                # A hole keeps whatever the partition held: the result would not be this image.
                if not allow_dont_care: raise Bad(f'DONT_CARE at block {pos}: the partition would keep old bytes there')
                if cmp: raise Bad('cannot compare a hole')
            else: raise Bad(f'unknown chunk {kind:#x}')
            pos += count
        if pos != total: raise Bad(f'covers {pos} of {total} blocks')
        if f.read(1): raise Bad('trailing data')
    if cmp:
        if cmp.read(1): raise Bad('image longer than the sparse file')
        cmp.close()
    return dict(blocks=total, chunks=chunks, kinds={hex(k): v for k, v in kinds.items()}, sha256=out.hexdigest(), simg_sha256=sha(path))

def block_crc(path, lba):
    with open(path, 'rb') as f:
        f.seek(lba * BLOCK); d = f.read(BLOCK)
    if len(d) != BLOCK: raise Bad(f'{path}: no block {lba}')
    return zlib.crc32(d), any(d)

def choose(img, want_sha):
    """Samples for this root: one non-zero block per stratum of the partition, picked from the root's hash so they can't be fitted to anything. Reads single blocks only."""
    if not want_sha or sha(img) != want_sha: sys.exit('refused: --readback-sha is not this image')
    if Path(img).stat().st_size != BYTES: sys.exit(f'refused: {img} is not exactly {BYTES} B')
    seed = bytes.fromhex(want_sha); out = []; span = BLOCKS // SAMPLES
    for i in range(SAMPLES):
        for attempt in range(4096):
            h = hashlib.sha256(seed + struct.pack('<II', i, attempt)).digest()
            n = 4 + i * span + int.from_bytes(h[:4], 'little') % (span - 8)
            if block_crc(img, n)[1]: out.append(n); break
        else: sys.exit(f'refused: stratum {i} looks empty')
    # One sample where this root is zero and the iOS 16 region isn't: it fails if the bootloader skipped a FILL chunk.
    fill = None
    if STAGING.exists():
        for attempt in range(1 << 17):
            n = 4 + int.from_bytes(hashlib.sha256(seed + b'fill' + struct.pack('<I', attempt)).digest()[:4], 'little') % 604000
            if not block_crc(img, n)[1] and block_crc(STAGING, n)[1]: fill = n; out[0] = n; break
    last = BLOCKS - 1
    if not block_crc(img, last)[1]: sys.exit('refused: last block is zero; expected the alternate HFS header')
    blocks = sorted({0, 1, 2, 3, last, *out, *KERNEL_BLOCKS})
    # 0..3 and the last hold volume headers, which the Oct/iOS 16 contents can't match.
    return dict(root=str(img), root_sha256=want_sha, fill_sample=fill, samples=out, last=last, shim_blocks=[0, 1, 2, 3, last, *out], kernel_blocks=list(KERNEL_BLOCKS),
                expected={str(n): block_crc(img, n)[0] for n in blocks})

def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); sys.modules[name] = m; s.loader.exec_module(m); return m

def shim_record(attempt, man):
    ids = man['ids']
    r = subprocess.run([sys.executable, '-I', str(R/'ufs-read-r3/decode_read.py'), str(Path(attempt)/'ramdump/kernel.log'), ids['record_nonce'], ids['epoch']], capture_output=True, text=True)
    if r.returncode: raise Bad('no shim read record of this image: ' + r.stderr.strip()[-160:])
    return json.loads(r.stdout)

def bound_text(attempt, nonce):
    """The mirror's text, only if XNUENT1 has this image's nonce. None when not bound."""
    rd = load('read_ramdump', ROOT/'tools/read-ramdump.py')
    d = (Path(attempt)/'ramdump/kernel.log').read_bytes()
    doc, text = rd._parse_msgbuf_mirror(d[rd.PMSG_OFF:rd.PMSG_OFF + rd.PMSG_SIZE], tail_count=1 << 21)
    pro = doc.get('entry_prologue') or {}
    if not pro.get('entry_valid') or pro.get('boot_nonce') != nonce or not text: return None
    return text

def kernel_crcs(attempt, nonce):
    """blazer-ufs-test lines of this boot. None when the log isn't bound to it."""
    text = bound_text(attempt, nonce)
    if text is None: return None
    if not re.search(r'blazer-ufs-test: done, 0 errors', text): raise Bad('kernel read test did not finish with 0 errors')
    return {int(a): int(b, 16) for a, b in re.findall(r'blazer-ufs-test: part lba (\d+) count 1 crc ([0-9a-f]{8})', text)}

def gpt_row(rec):
    rows = [p for p in rec.get('partitions', []) if p.get('target')]
    if len(rows) != 1: raise Bad(f'{len(rows)} GPT rows named {TARGET}')
    p = rows[0]
    if (p['lun'], p['first_lba'], p['last_lba'], p['name']) != (0, FIRST, LAST, TARGET): raise Bad(f'unexpected place: {p}')
    return p

def compare(rec, kernel, expected):
    """Every read this boot made of the partition against the root. All must be there and equal."""
    seen, bad = {}, []
    for r in rec.get('reads', []):
        if r.get('lun') == 0 and FIRST <= r.get('lba', -1) <= LAST:
            n = r['lba'] - FIRST
            if str(r.get('rc')) not in ('0', 'OK'): bad.append((n, 'shim read rc', r.get('rc')))
            seen.setdefault(n, []).append(r['crc32'])
    for n, crc in (kernel or {}).items(): seen.setdefault(n, []).append(crc)
    for n, crcs in seen.items():
        want = expected.get(str(n))
        if want is None: bad.append((n, 'not in the expected list', crcs))
        elif any(c != want for c in crcs): bad.append((n, 'differs', crcs, want))
    missing = [n for n in expected if int(n) not in seen]
    return dict(blocks=len(seen), reads=sum(map(len, seen.values())), bad=bad, missing=missing, ok=not bad and not missing and bool(seen))

REHEARSAL_WHOLE = 'd7b3b120'  # 20261101-230701-fullcheck-r3-before, partition unchanged since, if nothing was written
def soak_report(text, want, whole=REHEARSAL_WHOLE):
    """Every pass finished, each read the same bytes: all whole CRCs equal, and equal to the rehearsal's."""
    t = text.replace('\r\n', '\n')
    done = re.findall(r'^blazer-ufs-fullcheck: done, spans (\d+) blocks (\d+) whole crc ([0-9a-f]{8}), (\d+) ms$', t, re.M)
    err = re.search(r'^blazer-ufs-fullcheck: read error.*$', t, re.M)
    panic = re.search(r'^panic\(cpu \d+ caller 0x[0-9a-f]+\):\s*(.*)$', t, re.M)
    watch = re.findall(r'^blazer-root: watch t (\d+) ms stage (\S+)', t, re.M)
    probs = []
    if len(done) != want: probs.append(f'{len(done)} of {want} passes finished')
    if err: probs.append(err.group(0))
    wholes = sorted({d[2] for d in done})
    if len(wholes) > 1: probs.append(f'passes read different bytes: {wholes}')
    if wholes and wholes != [whole]: probs.append(f'whole crc {wholes[0]} is not the expected {whole}: partition changed, or reads differ')
    return dict(ok=not probs, passes=len(done), want=want, ms=[int(d[3]) for d in done], total_s=round(sum(int(d[3]) for d in done) / 1000), last_watch_s=round(int(watch[-1][0]) / 1000) if watch else None, last_stage=watch[-1][1] if watch else None, panic=panic.group(1) if panic else None, problems=probs)

def main(a):
    if a[:1] == ['check-simg']:
        print(json.dumps(dict(walk(a[1], other=a[2]), image_sha256=sha(a[2])))); return 0
    if a[:1] == ['check-restore']:
        print(json.dumps(walk(a[1], allow_dont_care=True))); return 0
    if a[:1] == ['gpt']:
        print(json.dumps(gpt_row(shim_record(a[1], json.loads(Path(a[2]).read_text()))))); return 0
    if a[:1] == ['readback']:
        man = json.loads(Path(a[2]).read_text()); rb = man.get('readback')
        if not rb: raise Bad('manifest is not a read-back image')
        rec = shim_record(a[1], man); gpt_row(rec)
        k = kernel_crcs(a[1], int(man['ids']['stamp_nonce'], 16))
        if k is None: raise Bad('kernel lines not bound to this image')
        res = compare(rec, k, rb['expected']); print(json.dumps(dict(res, root=rb['root_sha256'])))
        print('PASS' if res['ok'] else 'FAIL'); return 0 if res['ok'] else 1
    if a[:1] == ['fullcheck']:
        # The check that counts: every block. Run dir beside the manifest holds the image's list.
        import fullcheck as FC
        man = json.loads(Path(a[2]).read_text()); text = bound_text(a[1], int(man['ids']['stamp_nonce'], 16))
        if text is None: raise Bad('log not bound to this image')
        want = json.loads((Path(a[2]).parent/'fullcheck.json').read_text())
        res = FC.compare(text, want); print(json.dumps(dict(res, root=want['root_sha256'])))
        print('PASS' if res['ok'] else 'FAIL'); return 0 if res['ok'] else 1
    if a[:1] == ['soak']:
        man = json.loads(Path(a[2]).read_text()); text = bound_text(a[1], int(man['ids']['stamp_nonce'], 16))
        if text is None: raise Bad('log not bound to this image')
        res = soak_report(text, man['soak'], man.get('soak_whole') or REHEARSAL_WHOLE); print(json.dumps(res)); print('PASS' if res['ok'] else 'FAIL'); return 0 if res['ok'] else 1
    if a[:1] == ['compare-image']:
        man = json.loads(Path(a[2]).read_text()); rec = shim_record(a[1], man); gpt_row(rec)
        k = kernel_crcs(a[1], int(man['ids']['stamp_nonce'], 16))
        if k is None: raise Bad('kernel lines not bound to this image')
        lbas = {r['lba'] - FIRST for r in rec['reads'] if r['lun'] == 0 and FIRST <= r['lba'] <= LAST} | set(k)
        res = compare(rec, k, {str(n): block_crc(a[3], n)[0] for n in lbas}); print(json.dumps(res))
        print('PASS' if res['ok'] else 'FAIL'); return 0 if res['ok'] else 1
    sys.exit(__doc__)

if __name__ == '__main__':
    try: sys.exit(main(sys.argv[1:]))
    except Bad as e: sys.exit(f'FAIL: {e}')
