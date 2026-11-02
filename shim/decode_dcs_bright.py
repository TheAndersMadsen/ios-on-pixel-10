#!/usr/bin/env python3
"""What stage G did to the panel's brightness, from a ramdump. Host only; holds its own constants, checked against tgl_dcs.h by test_dcs_bright.py.
  decode_dcs_bright.py <ramdump/kernel.log> [--ids <run>/ufs-ids.json] [--dump-base 0x95200000]
A record survives a warm reset, so without --ids a stale one from an earlier boot can't be told apart. With --ids, another build's record is refused, exit 1.
Register values only. No register measures light: the nits field is the vendor's scale, inferred, and only film or the owner's eye says what the glass did."""
import json, pathlib, struct, sys
RECORD_PA = (0x95438000, 0x9542a000); SIZE = 0x6000; HDR = 64; ESZ = 16; K_NOTE = 6; K_STOP = 7; K_WR = 4
DSI_TX_HDR, DSI_TX_PLD = 0x0efd82c0, 0x0efd82c4
N = dict(POWER_MODE=13, ERR_COUNT=15, READ_FAIL=21, INT_MAIN=25, BRIGHTNESS=36, TARGET=63, AT_WRITE=64, SETTLED=65, ERR_AFTER=66, POWER_AFTER=67, RESULT=68)
RESULT = {1: 'OK', 2: 'MISMATCH', 3: 'NO_READBACK', 4: 'PANEL_NOT_UP'}
DBV_MAX, NITS_MAX = 16383, 2250  # panel-gs-bmea.c bmea_brt_configs, EVT1 and later: top of the hbm band. Gamma 2.2 fits its values: 492 is 1, 4637 is 140, 13418 is 1450.
def nits(dbv): return round(NITS_MAX * (dbv / DBV_MAX) ** 2.2, 1)
def decode(raw, base=0x95200000, ids=None):
    for pa in RECORD_PA:
        off = pa - base; b = raw[off:off + SIZE]
        if b[:8] == b'FRMR1LOG': break
    else: raise ValueError('no display record: failed capture, or the stage never started')
    nonce = struct.unpack_from('<Q', b, 8)[0]; seal = nonce & 0xffffffff
    if ids and (nonce != int(ids['stamp_nonce'], 16) or b[16:32].hex() != ids['record_nonce']): raise ValueError('record is from another boot: nonce %016x' % nonce)
    notes = {}; ent = 0; stop = None; packets = []; pld = []
    for i in range((len(b) - HDR) // ESZ):
        w0, a, v, s = struct.unpack_from('<4I', b, HDR + i * ESZ)
        if not (w0 or a or v or s): break
        if s != (w0 ^ a ^ v ^ seal) or (w0 >> 16) != i: break
        ent += 1; kind = (w0 >> 8) & 0xff
        if kind == K_NOTE: notes.setdefault(a, []).append(v)
        if kind == K_STOP: stop = dict(code=a, detail=hex(v), stage=w0 & 0xff)
        if kind == K_WR and a == DSI_TX_PLD: pld.append(v)
        if kind == K_WR and a == DSI_TX_HDR:
            di = v & 0xff; ln = (v >> 8) & 0xffff; data = b''.join(struct.pack('<I', x) for x in pld)[:ln] if di in (0x39, 0x0a) else b''; pld = []
            if di == 0x39 and data[:1] == b'\x51': packets.append(dict(di=hex(di), bytes=data.hex(), lp=bool(v >> 24 & 1)))
    final, fseal = struct.unpack_from('<II', b, 48)
    one = lambda k: notes[N[k]][0] if N[k] in notes else None
    out = dict(record_pa=hex(pa), nonce='%016x' % nonce, entries=ent, finished=fseal == (final ^ seal ^ 0x444f4e45), final=final, stop=stop, gate_on=N['TARGET'] in notes, before=one('BRIGHTNESS'), target=one('TARGET'), at_write=one('AT_WRITE'), settled=one('SETTLED'),
               err_count=one('ERR_AFTER'), power_before=one('POWER_MODE'), power_after=one('POWER_AFTER'), result=RESULT.get(one('RESULT'), one('RESULT')), packets=packets)
    for k in ('before', 'target', 'at_write', 'settled'):
        if out[k] is not None: out[k + '_nits_inferred'] = nits(out[k]) if out[k] <= DBV_MAX else None
    return out
def main():
    a = sys.argv[1:]; base = 0x95200000; ids = None
    if '--dump-base' in a: i = a.index('--dump-base'); base = int(a[i + 1], 16); del a[i:i + 2]
    if '--ids' in a: i = a.index('--ids'); ids = json.loads(pathlib.Path(a[i + 1]).read_text()); del a[i:i + 2]
    try: d = decode(pathlib.Path(a[0]).read_bytes(), base, ids)
    except ValueError as e: print('REFUSED:', e); sys.exit(1)
    for k in ('before', 'target', 'at_write', 'settled', 'err_count', 'power_before', 'power_after'):
        if d[k] is not None: d[k] = hex(d[k])
    print(json.dumps(d, indent=1))
if __name__ == '__main__': main()
