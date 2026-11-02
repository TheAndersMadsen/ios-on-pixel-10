#!/usr/bin/env python3
"""Whole-image check of userdata_exp.ai: CRC list from the raw image, compared with what the phone logged. Host only.
  fullcheck.py compute IMG OUT.json [--mask TABLE.json] [--test-block TABLE.json A|B]
  fullcheck.py compare LOG_TEXT LIST.json     text with blazer-ufs-fullcheck lines; exit 1 and names the span on a mismatch
--mask: what a kernel logs under blazer_ufs_fullcheck=2: the persist table's blocks not hashed, everything else compared.
--test-block: what a kernel with no mask logs after blazer_persist=2 wrote that pattern: the image with that one block changed.
TABLE.json: research/ios26-persist-r1/tools/build_table.py."""
import json, re, struct, sys, zlib
from pathlib import Path
sys.dont_write_bytecode = True
BLOCK = 4096; SPAN = 16384
def table_mask(path):
    t = json.loads(Path(path).read_text())
    return dict(extents=t['extents'], blocks=t['table_blocks'], table_crc=t['table_crc'])
def pattern(rel, which):
    """The bytes of bp_pattern_fill in hakios.blazer_persist_disk.inc."""
    salt = 0xA5A5A5A5 if which else 0x5A5A5A5A
    return b''.join(struct.pack('<I', ((rel * 0x01000193) ^ (i * 0x9E3779B1) ^ salt) & 0xffffffff) for i in range(BLOCK // 4))
def test_block(path, letter):
    """{block: bytes} for a known write of the test block. The CRC in the table is the host's own, so this can't drift from it."""
    t = json.loads(Path(path).read_text()); b = t['test_block']; d = pattern(b, 'AB'.index(letter))
    if zlib.crc32(d) != t[f'pattern_{letter.lower()}_crc']: raise ValueError('pattern differs from the table')
    return {b: d}
def compute(img, mask=None, overlay=None):
    """Same definition as the kernel: standard CRC32 of each 64 MiB span, and of the whole. 64 MiB read at a time: memory stays small.
    mask: table_mask(); those blocks aren't hashed, though they count in their span's size. overlay: {block: bytes}, replacing the image's."""
    spans = []; whole = 0; first = 0; ext = sorted(mask['extents']) if mask else []; overlay = overlay or {}
    with open(img, 'rb') as f:
        while (d := f.read(SPAN * BLOCK)):
            if len(d) % BLOCK: raise ValueError('image is not whole blocks')
            n = len(d) // BLOCK; end = first + n; crc = 0; at = first
            for b, data in overlay.items():
                if len(data) != BLOCK: raise ValueError('overlay is not one block')
                if first <= b < end: d = d[:(b - first) * BLOCK] + data + d[(b - first + 1) * BLOCK:]
            for a, c in ext + [(end, 0)]:
                if a + c <= at or a >= end:
                    if a != end: continue
                if a > at:
                    piece = d[(at - first) * BLOCK:(min(a, end) - first) * BLOCK]; crc = zlib.crc32(piece, crc); whole = zlib.crc32(piece, whole)
                at = max(at, min(end, a + c))
            spans.append(dict(first=first, blocks=n, crc=crc)); first += n
    r = dict(blocks=first, spans=spans, whole=whole)
    if mask: r['mask'] = dict(blocks=mask['blocks'], table_crc=mask['table_crc'])
    if overlay: r['overlay'] = sorted(overlay)
    return r
SPAN_LINE = re.compile(r'^blazer-ufs-fullcheck: span (\d+) first (\d+) blocks (\d+) crc ([0-9a-f]{8})$', re.M)
DONE = re.compile(r'^blazer-ufs-fullcheck: done, spans (\d+) blocks (\d+) whole crc ([0-9a-f]{8}), (\d+) ms$', re.M)
ERROR = re.compile(r'^blazer-ufs-fullcheck: read error lba (\d+) count (\d+) error (-?\d+)', re.M)
MASKED = re.compile(r'^blazer-ufs-fullcheck: masked (\d+) blocks, table crc ([0-9a-f]{8})$', re.M)
def compare(text, want):
    """A dict with ok and problems. Passing needs the done line, every span, in order, and equal CRCs: anything absent fails."""
    bad = []
    text = text.replace('\r\n', '\n')  # the kernel's message buffer ends these lines with CRLF
    m = ERROR.search(text)
    if m: bad.append(f'read error at partition block {m.group(1)}, error {m.group(3)}')
    mk = MASKED.search(text); wm = want.get('mask')  # a masked pass only compares with a list masked the same way
    if wm and (not mk or (int(mk.group(1)), int(mk.group(2), 16)) != (wm['blocks'], wm['table_crc'])): bad.append(f"list masks {wm['blocks']} blocks, table {wm['table_crc']:08x}; log says {mk.group(0) if mk else 'no mask'}")
    if mk and not wm: bad.append(f'log is masked, list is not: {mk.group(0)}')
    got = [(int(a), int(b), int(c), int(d, 16)) for a, b, c, d in SPAN_LINE.findall(text)]
    if not m and len(got) != len(want['spans']): bad.append(f"{len(got)} spans logged, {len(want['spans'])} expected")
    differ = []
    for i, s in enumerate(want['spans']):
        if i >= len(got): break
        n, first, blocks, crc = got[i]
        if (n, first, blocks) != (i, s['first'], s['blocks']): bad.append(f'span {i}: logged as {n} at {first} for {blocks}')
        elif crc != s['crc']: differ.append(i); bad.append(f"span {i}, blocks {first}..{first + blocks - 1}: phone {crc:08x}, image {s['crc']:08x}")
    d = DONE.search(text); ms = None
    if not d: bad.append('no done line: the pass did not finish')
    else:
        ms = int(d.group(4))
        if int(d.group(2)) != want['blocks'] or int(d.group(1)) != len(want['spans']): bad.append(f'done line: {d.group(1)} spans, {d.group(2)} blocks')
        if int(d.group(3), 16) != want['whole']: bad.append(f"whole crc: phone {d.group(3)}, image {want['whole']:08x}")
    return dict(ok=not bad, spans=len(got), differ=differ, problems=bad, ms=ms)
if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['compute']:
        o = a[3:]; mask = overlay = None
        if o[:1] == ['--mask']: mask = table_mask(o[1]); o = o[2:]
        if o[:1] == ['--test-block']: overlay = test_block(o[1], o[2]); o = o[3:]
        if o: sys.exit(__doc__)
        Path(a[2]).write_text(json.dumps(compute(a[1], mask, overlay)) + '\n')
    elif a[:1] == ['compare']:
        r = compare(Path(a[1]).read_text(errors='replace'), json.loads(Path(a[2]).read_text())); print(json.dumps(r)); print('PASS' if r['ok'] else 'FAIL'); sys.exit(0 if r['ok'] else 1)
    else: sys.exit(__doc__)
