#!/usr/bin/env python3
"""Decoder for one boot of the integrated route. Host only. Holds its own offsets; imports nothing from the C.
  decode_ufs_boot.py kernel.log out/ufs-ids.json       link record, read record (via decode_read.py), XNU test lines
  decode_ufs_boot.py --link-record file nonce epoch    one raw 256-byte link record
Compares XNU's printed CRCs with the shim's READ CRCs of the same boot. A missing record is a failed capture, not an
empty result. Every claim stays false unless its bytes are present."""
import json, pathlib, re, struct, subprocess, sys, zlib
AUX = 0x212000 + 86016 + 0xc00; SIZE = 256; COMMIT = 0x314b4e4c
STAGES = {1: 'ADMITTED', 3: 'DEVICE_ON', 4: 'ROUTE', 5: 'DONE', 6: 'FAULT', 7: 'START'}
ROOT = pathlib.Path(__file__).resolve().parents[1]
def link(b, nonce, epoch):
    if len(b) != SIZE: raise ValueError('size')
    if b[:8] != b'UFSLNKR1': raise ValueError('no link record in the slot')
    u = lambda o: struct.unpack_from('<I', b, o)[0]; i = lambda o: struct.unpack_from('<i', b, o)[0]; q = lambda o: struct.unpack_from('<Q', b, o)[0]; h = lambda o: struct.unpack_from('<H', b, o)[0]
    if u(8) != 3 or u(252) != COMMIT or u(248) != zlib.crc32(b[:248]): raise ValueError('version, commit or CRC')
    if (q(16), q(24)) != (nonce, epoch): raise ValueError('nonce/epoch: not this boot')
    n = b[168]
    return dict(stage=STAGES.get(u(44), u(44)), rc=i(40), route_rc=hex(u(60)), started_us=q(48), elapsed_us=u(56), psm=list(b[92:95]),
        device_on=dict(step=u(72), rc=i(76), native=i(84), smc_a0=hex(u(88)), power_to_refclk_us=u(132), refclk_to_resetb_us=u(136)),
        pads_pre=[[hex(u(96 + 12 * p + 4 * k)) for k in range(3)] for p in range(3)], pads_before=hex(b[166]), pads_after=hex(b[167]),
        hc=dict(cap=hex(u(140)), hce_before=hex(u(144)), hce_written=hex(u(148)), hce_after=hex(u(152)), is_before=hex(u(156)), ie_before=hex(u(160)), stops=b[164], starts=b[165]),
        link=dict(attempts=n, link_up=b[170], results=list(b[172:172 + n]), link_us=[u(180 + 4 * k) for k in range(n)], hcs=hex(u(196)), is_=hex(u(200)), arg2=hex(u(204))),
        diag_after_hce=[h(208 + 2 * k) for k in range(5)], diag_after_link=[h(218 + 2 * k) for k in range(5)], diag_bad=hex(h(228)), isr_aif=b[171], fault=dict(esr=hex(q(232)), far=hex(q(240))))
XRE = re.compile(rb'blazer-ufs-test: (\w+) lba (\d+) count (\d+) crc ([0-9a-f]{8})( [\w-]+)?')
def main():
    a = sys.argv[1:]
    if a[0] == '--link-record':
        print(json.dumps(link(pathlib.Path(a[1]).read_bytes(), int(a[2], 16), int(a[3], 16)), indent=1)); return
    log = pathlib.Path(a[0]).read_bytes(); ids = json.loads(pathlib.Path(a[1]).read_text())
    out = dict(claims=dict(link=False, read=False, xnu_took_over=False, xnu_crc_equal_shim=False, ufs_root=False))
    out['link_record'] = link(log[AUX:AUX + SIZE], int(ids['stamp_nonce'], 16), int(ids['epoch'], 16))
    out['claims']['link'] = out['link_record']['link']['link_up'] == 1
    r = subprocess.run([sys.executable, '-I', str(ROOT/'research/ufs-read-r2/decode_read.py'), a[0], ids['record_nonce'], ids['epoch']], capture_output=True, text=True)
    if r.returncode: out['read_error'] = r.stderr[-400:]; rd = None
    else: rd = json.loads(r.stdout); out['read_end'] = rd['end']; out['claims']['read'] = rd['end']['rc'] == 'OK' and rd['end']['read_blocks'] > 0
    x = [dict(kind=m.group(1).decode(), lba=int(m.group(2)), count=int(m.group(3)), crc=int(m.group(4), 16)) for m in XRE.finditer(log)]
    lines = [l.decode('latin1') for l in re.findall(rb'blazer-ufs[^\n\0]*', log)]
    out['xnu_lines'] = lines[:80]; out['xnu_reads'] = x
    out['claims']['xnu_took_over'] = any('read only, DMA at' in l for l in lines)
    if rd and x:
        first = rd['target']['first_lba'] if rd.get('target') else None
        shim = {(q['lun'], q['lba']): q['crc32'] for q in rd['reads']}
        cmp_ = []
        for e in x:
            if e['count'] != 1: continue
            key = (0, e['lba'] + first) if e['kind'] == 'part' else (0, e['lba'])
            if key in shim: cmp_.append(dict(kind=e['kind'], lba=e['lba'], xnu=e['crc'], shim=shim[key], equal=e['crc'] == shim[key]))
        out['xnu_vs_shim'] = cmp_
        out['claims']['xnu_crc_equal_shim'] = bool(cmp_) and all(c['equal'] for c in cmp_)
    print(json.dumps(out, indent=1))
main()
