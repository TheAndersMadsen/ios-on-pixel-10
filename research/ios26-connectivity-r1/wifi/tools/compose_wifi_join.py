#!/usr/bin/env python3
"""HOST ONLY. Inputs for the first Wi-Fi join boot (W1) on the A7-r3 line: kernel ddf874fb, root ios_system, 5 cores.

  compose_wifi_join.py overlay [SECRET] [--out OVL]   A7-r3 overlay + the owner's network as one group-26 record
  compose_wifi_join.py cmdline                        the r3 line, minus two trace tokens, plus the join tokens
  compose_wifi_join.py check OVL                      what the kernel's reader (blazer_wifi_net_secret) will see

overlay: base artwork-container-battery-observe-r1.ovl (7d610456..., A7-r3's var_overlay). Every base record is kept
byte for byte and in order. One file record is appended: group 26, 0600 root:root, /private/var/hkcover/wifi/net, data =
mkwifisecret.py's 108-byte BWN1 blob (PMK, never the password). Group 26 is not in hk_overlay=0xA0080081, so varfs never
applies it; blazer_wifi_net.c reads it once after pid 1 exists and zeroes it in place. The header count, length and
fnv1a are recomputed. Output is mode 0600 under research/ios26-wifi-r1/secret/ (git-ignored, 0700). Nothing secret is
printed: only sizes and SHA-256s. Refuses to overwrite.

cmdline: XNU and the shim take at most 1023 bytes (pexpert/arm64/boot.h BOOT_LINE_LENGTH 1024). r3's line is 999 bytes;
the join tokens add 50. Dropped: hk_present_trace=1 (sweet_present_trace.inc: IOLog only) and blazer_battery_receipt=1
(SweetBattery.cpp: receipt lines only). Both are logging; dropping them also leaves more msgbuf for the Wi-Fi lines.
blazer_wifi_net is left at its default, 1 when joining (blazer_wifi.c). blazer_wifi_run stays 120 s, then the chip goes off.
"""
import argparse, hashlib, importlib.util, json, os, struct, sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
BASE = REPO / 'research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl'
MANIFEST = REPO / 'research/images/a7-ios-system-r3/manifest.json'
MKOVERLAY = REPO / 'research/ios26-overlay-r1/tools/mkoverlay.py'
MKWIFISECRET = REPO / 'research/ios26-wifi-r1/tools/mkwifisecret.py'
SECRET_DIR = REPO / 'research/ios26-wifi-r1/secret'
PINNED = {
    BASE: '7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58',
    MKOVERLAY: 'e658e67be7b8d2caa36e37a5e690ab60d5ac45b3bbe7a7d70121e48e98813573',
    MKWIFISECRET: '730029b2e69924ea2e580f02cf141a4df5faddffb63c7df58c8e47b6319af9c5',
}
R3_CMDLINE_SHA = '840fc51c70788c74c1d853ede4569bb86ec6e3385f20ddb7486371e1482d5917'
R3_MASK = 0xA0080081
GROUP = 26
PATH = '/private/var/hkcover/wifi/net'
NB_BYTES = 108
LINE_MAX = 1023
DROP = ('hk_present_trace=1', 'blazer_battery_receipt=1')
ADD = ('blazer_wifi=1', 'blazer_wifi_stage=8', 'blazer_wifi_join=1')
# Tokens the join boot must not carry: they change what the radio does or where frames go
FORBID = ('blazer_wifi_idx_tcm', 'blazer_wifi_mem_atu', 'blazer_wifi_force', 'blazer_wifi_hold', 'blazer_wifi_net=2',
          'blazer_usbnet', 'blazer_wifi_ios')


def die(msg):
    sys.exit(f'compose_wifi_join: {msg}')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def load(path, name, pinned=True):
    if pinned and sha(path.read_bytes()) != PINNED[path]:
        die(f'{path.name}: sha256 differs from the pin')
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def records(mk, b):
    """The blob's records as raw slices, checked like varfs_overlay.h hkov_check."""
    if len(b) < 24 or b[:8] != mk.MAGIC:
        raise ValueError('bad header')
    size, count, h = struct.unpack_from('<IIQ', b, 8)
    if size != len(b) or size > mk.TOTAL_MAX or size & 7 or mk.fnv1a(b[24:]) != h or count == 0:
        raise ValueError('bad size/count/checksum')
    p, out = 24, []
    for _ in range(count):
        start = p
        if size - p < 24:
            raise ValueError('entry past the end')
        kind, group, mode, uid, gid, plen, dlen = struct.unpack_from('<BB2xIIIII', b, p)
        p += 24
        if plen == 0 or plen >= mk.PATH_MAX or p + plen >= size or b[p + plen] != 0:
            raise ValueError('bad path')
        path = b[p:p + plen].decode()
        p = (p + plen + 8) & ~7
        if p + dlen > size or group > 31 or chr(kind) not in 'dflxc':
            raise ValueError('bad entry')
        data = b[p:p + dlen]
        p = (p + dlen + 7) & ~7
        out.append(dict(kind=chr(kind), group=group, mode=mode, uid=uid, gid=gid, path=path, data=data, raw=b[start:p]))
    if p != size:
        raise ValueError('trailing bytes')
    return out


def compose(mk, base, net_blob):
    """base bytes + one group-26 file record. Pure: the tests drive it with synthetic blobs."""
    if len(net_blob) != NB_BYTES or net_blob[:4] != b'BWN1':
        raise ValueError('network blob: not a 108-byte BWN1 record')
    recs = records(mk, base)
    if any(r['group'] == GROUP for r in recs):
        raise ValueError(f'base already uses group {GROUP}')
    if any(r['path'] == PATH for r in recs):
        raise ValueError(f'base already has {PATH}')
    if R3_MASK & (1 << GROUP):
        raise ValueError('group 26 would be applied by the r3 mask')
    body = b''.join(r['raw'] for r in recs) + mk.pack('f', GROUP, 0o600, 0, 0, PATH, net_blob)
    out = struct.pack('<8sIIQ', mk.MAGIC, 24 + len(body), len(recs) + 1, mk.fnv1a(body)) + body
    if len(out) > mk.TOTAL_MAX:
        raise ValueError('too large')
    return out


def cmdline(manifest):
    m = json.loads(Path(manifest).read_text())
    line = m['cmdline']
    if sha(line.encode()) != R3_CMDLINE_SHA:
        die('A7-r3 manifest cmdline differs from the pin')
    return join_line(line)


def join_line(line):
    toks = line.split(' ')
    for d in DROP:
        if toks.count(d) != 1:
            raise ValueError(f'{d}: expected once in the base line')
    if any(t.startswith('blazer_wifi') for t in toks):
        raise ValueError('base line already has Wi-Fi tokens')
    if f'hk_overlay=0x{R3_MASK:X}' not in toks:
        raise ValueError('base line has another overlay mask')
    toks = [t for t in toks if t not in DROP]
    # image_tool appends --phone-args, then blazer_bootcpu= (from --bootcpu) last: the Wi-Fi tokens go before it
    at = len(toks) - 1 if toks[-1].startswith('blazer_bootcpu=') else len(toks)
    toks[at:at] = list(ADD)
    out = ' '.join(toks)
    if any(f in out for f in FORBID):
        raise ValueError('forbidden token')
    if len(out.encode()) > LINE_MAX:
        raise ValueError(f'{len(out)} bytes, limit {LINE_MAX}')
    return out


def reader_view(mk, blob):
    """What blazer_wifi_net_secret finds: first group-26 'f' record at PATH. Returns lengths and flags only."""
    hits = [r for r in records(mk, blob) if r['group'] == GROUP and r['kind'] == 'f' and r['path'] == PATH]
    if len(hits) != 1:
        raise ValueError(f'{len(hits)} network records')
    d = hits[0]['data']
    return dict(records=len(records(mk, blob)), net_bytes=len(d), magic=d[:4].decode('ascii', 'replace'),
                ssid_len=d[24], flags=d[25], country=d[26:28].decode('ascii', 'replace'), mode=oct(hits[0]['mode']),
                applied_by_mask=bool(R3_MASK & (1 << GROUP)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    o = sub.add_parser('overlay')
    o.add_argument('secret', nargs='?', default=str(SECRET_DIR / 'wifi.secret'))
    o.add_argument('--out', default=str(SECRET_DIR / 'a7-r3-wifi-join.ovl'))
    sub.add_parser('cmdline')
    c = sub.add_parser('check')
    c.add_argument('ovl')
    a = ap.parse_args()
    mk = load(MKOVERLAY, 'mkoverlay')
    if a.cmd == 'cmdline':
        line = cmdline(MANIFEST)
        print(line)
        print(f'# {len(line.encode())} bytes, sha256 {sha(line.encode())}', file=sys.stderr)
        return
    if a.cmd == 'check':
        print(json.dumps(reader_view(mk, Path(a.ovl).read_bytes()), indent=1))
        return
    ws = load(MKWIFISECRET, 'mkwifisecret')
    out = Path(a.out)
    if out.exists():
        die(f'{out} exists; refusing to overwrite')
    base = BASE.read_bytes()
    if sha(base) != PINNED[BASE]:
        die('base overlay sha256 differs')
    net = ws.blob(ws.parse(Path(a.secret)))   # parse() refuses a secret file readable by others
    blob = compose(mk, base, net)
    out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(blob)
    v = reader_view(mk, blob)
    print(json.dumps(dict(out=str(out), bytes=len(blob), sha256=sha(blob), base_sha256=PINNED[BASE],
                          records=v['records'], net_bytes=v['net_bytes'], group=GROUP, mask=hex(R3_MASK)), indent=1))


if __name__ == '__main__':
    main()
