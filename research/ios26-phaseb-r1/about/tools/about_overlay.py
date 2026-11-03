#!/usr/bin/env python3
"""HOST ONLY. int2-about overlay = int1-r1 (c440b6ea, 52 records) + three hkcover covers in group 19 (bit 0x80000, already in
int1's hk_overlay=0xA0080081: no boot-arg change). Each cover mounts a ramfs over one read-only root directory, holding that
directory's stock 23G90 files, including the ones root r3's prune removed (FIX.md section 2):

  ml-en      /System/Library/PrivateFrameworks/MusicLibrary.framework/en.lproj
             MLSortMapTables.plist, SortingDetails.plist (NSBundle finds them in the current localisation), MLSections.plist
  ax-punct   /System/Library/PrivateFrameworks/AccessibilitySharedSupport.framework/AXSSPunctuationModel.momd
             VersionInfo.plist (same bytes as the root's), AXSSPunctuationModel.mom
  ax-vopron  .../AccessibilitySharedSupport.framework/VOPronunciationModel.momd   VersionInfo.plist, VOPronunciationModel.mom

Codec: ios26-overlay-r1/tools/mkoverlay.py (pack, fnv1a); decode with the second walker (restore_cloudd.decode).
    about_overlay.py INT1_OVL STOCK_DIR OUT        (refuses to overwrite OUT; prints JSON)
"""
import hashlib, importlib.util, json, struct, sys
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MK = load('mkoverlay', 'research/ios26-overlay-r1/tools/mkoverlay.py')
RC = load('rc', 'research/ios26-overlay2-r1/tools/restore_cloudd.py')
sha = lambda b: hashlib.sha256(b).hexdigest()
INT1 = 'c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e'
GROUP = 19
PF = 'System/Library/PrivateFrameworks'
COVERS = [
    ('ml-en', f'{PF}/MusicLibrary.framework/en.lproj', {
        'MLSortMapTables.plist': ('MusicLibrary.framework/MLSortMapTables.plist', '148e53436ca99c65bade925244058ecc1257f745d05929aebc4cbf681f5c014c'),
        'SortingDetails.plist': ('MusicLibrary.framework/SortingDetails.plist', '03bd240165c5bdf1c5e3db4ba5e1f91483c06430452514ac3c78ceeaf20e69f8'),
        'MLSections.plist': ('MusicLibrary.framework/en.lproj/MLSections.plist', '94b84f64a659101bccb7af28c9f7a6f8f68da8080ea04a51b78bc251535b3a3a')}),
    ('ax-punct', f'{PF}/AccessibilitySharedSupport.framework/AXSSPunctuationModel.momd', {
        'VersionInfo.plist': ('AccessibilitySharedSupport.framework/AXSSPunctuationModel.momd/VersionInfo.plist', '8c47bb03b7c58f7fcae1ffec7f8c1e77ceaf04eb749ef5d3339cbbcd1dfbdd44'),
        'AXSSPunctuationModel.mom': ('AccessibilitySharedSupport.framework/AXSSPunctuationModel.momd/AXSSPunctuationModel.mom', 'be65ed3dbb695221be50207ea65b017c73cfc56fbe77c64d3709c2f05f9f011d')}),
    ('ax-vopron', f'{PF}/AccessibilitySharedSupport.framework/VOPronunciationModel.momd', {
        'VersionInfo.plist': ('AccessibilitySharedSupport.framework/VOPronunciationModel.momd/VersionInfo.plist', 'aaeadeb44b0480e2982df9c061c62c34d8f8ff930f6ae188f5ecf18325ce6391'),
        'VOPronunciationModel.mom': ('AccessibilitySharedSupport.framework/VOPronunciationModel.momd/VOPronunciationModel.mom', 'a222edc158c5314c68eb117800c3facaba56503838f398f0b7ca7061941ad6ad')}),
]


def build(int1, stock):
    if sha(int1) != INT1:
        raise ValueError('base is not int1-r1 c440b6ea')
    base = RC.decode(int1)
    have = {r[5] for r in base}
    if '/private/var/hkcover' not in have:
        raise ValueError('int1 has no /private/var/hkcover dir record')
    heads = [r for r in base if r[0] == ord('l') and r[5].endswith('.cover')]
    new, rows = [], []
    for name, target, files in COVERS:
        head = f'/private/var/hkcover/{name}'
        if head in have or head + '.cover' in have:
            raise ValueError(f'{name} collides')
        new.append(MK.pack('l', GROUP, 0o755, 0, 0, head + '.cover', ('/' + target).encode()))
        new.append(MK.pack('d', GROUP, 0o755, 0, 0, head, b''))
        rows += [f'l g{GROUP} {head}.cover -> /{target}', f'd g{GROUP} {head}']
        for fn, (rel, want) in files.items():
            data = (Path(stock) / PF / rel).read_bytes()
            if sha(data) != want:
                raise ValueError(f'{rel} is not {want[:8]}')
            new.append(MK.pack('f', GROUP, 0o644, 0, 0, f'{head}/{fn}', data))
            rows.append(f'f g{GROUP} {head}/{fn} {len(data)} B {want[:12]}')
    if len(heads) + len(COVERS) > 8:
        raise ValueError('more than HKOV_COVERS_MAX covers')
    body = b''.join(r[7] for r in base) + b''.join(new)
    out = MK.MAGIC + struct.pack('<IIQ', 24 + len(body), len(base) + len(new), MK.fnv1a(body)) + body
    if len(out) > MK.TOTAL_MAX:
        raise ValueError('too large')
    dec = RC.decode(out)
    assert [r[7] for r in dec[:len(base)]] == [r[7] for r in base]      # int1's records, byte for byte, in order
    assert len(dec) == len(base) + len(new) and all(r[1] == GROUP for r in dec[len(base):])
    return out, {'base': INT1, 'output_sha256': sha(out), 'bytes': len(out), 'records': len(dec), 'added_bytes': len(out) - len(int1),
                 'covers_before': len(heads), 'covers_after': len(heads) + len(COVERS), 'appended': rows}


if __name__ == '__main__':
    src, stock, dst = sys.argv[1:4]
    if Path(dst).exists():
        raise SystemExit(f'{dst} exists, refusing')
    out, rep = build(Path(src).read_bytes(), stock)
    Path(dst).write_bytes(out)
    print(json.dumps(rep, indent=1))
