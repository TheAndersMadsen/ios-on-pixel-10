#!/usr/bin/env python3
"""One table of every stage of one all-r1 or all-r1-safe boot. Host only; reads only.
  all_decode.py <ramdump kernel.log> <manifest.json> [--json]
  all_decode.py --selftest
Runs the existing decoders unmodified (ufs-read-r2 decode_read, ufs-root-r1 decode_root, ufs-speed-r1 decode_speed's timing) and the relocated copy of decode_dcs, and adds the sealed stage record.
A stage marked ENTER with no later mark is where the boot stopped, if nothing after it ran. Every other row says what its own record says. Any record of another build is refused, by nonce."""
import importlib.util, json, pathlib, re, struct, subprocess, sys
sys.dont_write_bytecode = True
X = pathlib.Path(__file__).resolve().parent; R = X.parent/'research'
DR = R/'ufs-read-r2/decode_read.py'; DB = R/'ufs-root-r1/tools/decode_root.py'; DS = R/'ufs-speed-r1/tools/decode_speed.py'; DD = R/'display-frame-r1/tools/decode_dcs.py'; DCS_PA = 0x95438000  # shim/tgl_dcs.h: the decoder's own PA is the record's iOS 16 place
BASE = 0x95200000; ALL_PA = 0x955f0000; ALL_MAGIC = 0x31304754534c4c41
NAMES = {1: 'UFS link and PWM reads', 2: 'UFS and handoff done', 3: 'PHY check', 4: 'HS change', 5: 'HS verify', 6: 'PWM relink', 8: 'touch probe', 9: 'DPU frame', 10: 'jump to XNU'}
STATES = {1: 'ENTER', 2: 'DONE', 3: 'FAILED', 5: 'FELL_THROUGH'}
def load(p, n):
    s = importlib.util.spec_from_file_location(n, p); m = importlib.util.module_from_spec(s); sys.modules[n] = m; s.loader.exec_module(m); return m
def marks(raw, ids):
    o = ALL_PA - BASE
    if len(raw) < o + 0x1000 or struct.unpack_from('<Q', raw, o)[0] != ALL_MAGIC: return None, 'no stage record'
    nonce = struct.unpack_from('<Q', raw, o + 8)[0]; want = int(ids['stamp_nonce'], 16)
    if nonce != want or raw[o + 24:o + 40].hex() != ids['record_nonce']: return None, 'stage record of another build'
    n = struct.unpack_from('<I', raw, o + 40)[0]
    if n > (0x1000 - 64) // 16: return None, 'stage count corrupt'
    out = []
    for i in range(n):
        idst, val, t = struct.unpack_from('<IiQ', raw, o + 64 + i * 16)
        out.append(dict(id=idst & 0xffff, name=NAMES.get(idst & 0xffff, idst & 0xffff), state=STATES.get(idst >> 16, idst >> 16), val=val, t_us=None if t == (1 << 64) - 1 else t))
    return out, None
def last_of(ms, i):
    r = [m for m in ms if m['id'] == i]; return r[-1] if r else None
def refclk_signature(n, fail):
    """Tegu's HS failure while PWM worked: PMC rejected HCS[10:8]=5, IS 0x415, or line reset and replay timeout in the UEC words."""
    c = n.get('change') or {}
    a = c.get('upmcrs') == 5 or c.get('is_') == '0x415'
    b = bool(fail) and (fail.get('uecpa') == 0x80000010 or fail.get('uecdl') == 0x80000002)
    return a or b
FLAGS = {'-DTGL_UFS_POWER_MODE=1': 'hs_gear4', '-DTGL_UFS_PHY_CHECK=1': 'phy_check', '-DTGL_UFS_PWM_FALLBACK=1': 'pwm_fallback', '-DTGL_UFS_WDT_GUARD=1': 'wdt_guard', '-DTGL_ALL_DCS=1': 'dpu_frame', '-DTGL_ALL_TOUCH=1': 'touch_probe'}
def features(man):
    # ui-integrate manifests list features. image_tool's may have only the shim's cflags, which are what was built.
    if 'features' in man: return set(man['features'])
    if 'cflags' in man: return {FLAGS[c] for c in man['cflags'].split() if c in FLAGS}
    sys.exit('manifest has neither features nor cflags')
def rows(raw, path, man):
    ids = man['ids']; on = features(man); T = []
    def add(stage, gate, result, ev=''): T.append((stage, gate, result, ev))
    ms, why = marks(raw, ids); ms_list = ms or []
    add('stage record', 'TGL_ALL_STAGES' if {'phy_check', 'pwm_fallback', 'dpu_frame'} & on else 'none', 'OK' if ms is not None else 'ABSENT', why or f'{len(ms_list)} marks; last: ' + (f"{ms_list[-1]['name']} {ms_list[-1]['state']}" if ms_list else 'none'))
    r = subprocess.run([sys.executable, '-I', str(DR), str(path), ids['record_nonce'], ids['epoch']], capture_output=True, text=True)
    S = load(DS, 'decode_speed_lib')
    rec = json.loads(r.stdout) if r.returncode == 0 else None
    if rec is None:
        add('UFS PWM reads', 'always', 'NO_RECORD', r.stderr.strip()[-120:])
        n = {}; s = dict(hs_n=0, pwm_n=0, crc_equal=0, crc_differ=0)
    else:
        n, s = S.notes(rec), S.shim(rec); e = rec.get('end', {})
        add('UFS link and PWM reads', 'always', 'OK' if s['pwm_n'] else 'NO_READS', f"{s['pwm_n']} target reads, median {s.get('pwm_us')} us; end rc {e.get('rc')}; dropped {e.get('dropped_entries')}")
    g = {x['where']: [x['cr0'], x['cr0ack'], x['gbpa'], x['gerror'], x['gerrorn']] for x in (rec or {}).get('gates', []) if x['where'] >= 0x400}
    if 0x406 in g:
        p0, p1, p2 = g[0x406], g.get(0x407, [None] * 5), g.get(0x408, [None] * 5); top = p0[0]
        add('PHY check', 'TGL_UFS_PHY_CHECK', 'RECORDED', f"TOP+0x100 {top:#x} EXT_LD_DONE {bool(top & 0x100000)} INIT_DONE {bool(top & 0x200000)}; refclk pad param {p0[1]:#x} dmux {p0[2]:#x} tx {p0[3]:#x}; 0x8101={p1[0]} 0x8115={p1[1]} 0x8019={p1[2]},{p1[3]} 0x8013={p1[4]},{p2[0]}; failed mask {p2[1]:#x}")
    else: add('PHY check', 'TGL_UFS_PHY_CHECK', 'NOT_RUN' if 'phy_check' in on else 'OFF', '')
    fail = None
    if 0x409 in g:
        w = g[0x409]; fail = dict(why=w[0] - (1 << 32) if w[0] >= 1 << 31 else w[0], uecpa=w[1], uecdl=w[2], is_=w[3], hcs=w[4])
    c = n.get('change'); a = n.get('after', {}); sig = refclk_signature(n, fail)
    if 'skipped' in n: hs = f"REFUSED_STILL_PWM ({n['skipped']})"
    elif not c: hs = 'NOT_ATTEMPTED' if 'hs_gear4' in on else 'OFF'
    elif c['rc'] or c['upmcrs'] != 1: hs = 'PMC_FAILED'
    elif (a.get('rxgear'), a.get('txgear'), a.get('rxlanes'), a.get('txlanes')) != (4, 4, 2, 2): hs = 'MODE_DIFFERS'
    else: hs = 'HS_G4_2L'
    add('HS change', 'TGL_UFS_POWER_MODE', hs, (f"rc {c['rc']} upmcrs {c['upmcrs']} IS {c['is_']} HCS {c['hcs']} {c['us']} us; before {n.get('before')} after {a}" if c else '') + ('; REFCLK SIGNATURE: suspect refclk first, no PHY tuning' if sig else ''))
    if s['hs_n']: add('HS verify', 'TGL_UFS_POWER_MODE', 'CRC_EQUAL' if s['crc_equal'] == 12 and not s['crc_differ'] else 'CRC_DIFFERS_OR_SHORT', f"{s['crc_equal']}/12 equal, {s['crc_differ']} differ, {s['hs_failed']} failed, median {s.get('hs_us')} us; UEC {s.get('uec')}")
    else: add('HS verify', 'TGL_UFS_POWER_MODE', 'NOT_RUN' if 'hs_gear4' in on else 'OFF', '')
    pv = [x for x in (rec or {}).get('reads', []) if x['step'] == 19]
    if 0x40b in g:
        e_ = g[0x40b]; add('PWM fallback', 'TGL_UFS_PWM_FALLBACK', 'FELL_BACK_PWM_OK' if e_[0] == 0 else 'FALLBACK_FAILED', f"first error {fail and fail['why']}; UECPA {fail and hex(fail['uecpa'])} UECDL {fail and hex(fail['uecdl'])}; {len(pv)} reads compared; result {e_[0] - (1 << 32) if e_[0] >= 1 << 31 else e_[0]}; PA after {g.get(0x40a)}")
    else: add('PWM fallback', 'TGL_UFS_PWM_FALLBACK', 'NOT_NEEDED' if 'pwm_fallback' in on else 'OFF', '')
    q = None
    rr = subprocess.run([sys.executable, '-I', str(DB), str(path), str(pathlib.Path(man['_ids_path']))], capture_output=True, text=True)
    if rr.returncode == 0: q = json.loads(rr.stdout)
    if 'touch_probe' in on: add('touch probe', 'TGL_ALL_TOUCH', (last_of(ms_list, 8) or {}).get('state', 'NOT_RUN'), 'decode with snapshot/touch-r1/tools/decode_tp.py')
    else: add('touch probe', 'TGL_ALL_TOUCH', 'OFF', 'left out: answer captured, PMIC stage reset the phone')
    if 'dpu_frame' in on:
        try:
            D = load(DD, 'decode_dcs_lib'); D.PA = DCS_PA
            d = D.decode(raw, ids); add('DPU frame', 'TGL_ALL_DCS', str(d.get('verdict') or d.get('result')), f"mark {(last_of(ms_list, 9) or {}).get('state')}; " + json.dumps(d.get('claims', {}))[:200])
        except (SystemExit, Exception) as ex:
            add('DPU frame', 'TGL_ALL_DCS', 'NO_RECORD', f"mark {(last_of(ms_list, 9) or {}).get('state', 'never entered')}; {str(ex)[:120]}")
    else: add('DPU frame', 'TGL_ALL_DCS', 'OFF', 'all-r1-safe')
    jump = last_of(ms_list, 10)
    add('jump to XNU', 'always', 'ENTERED' if jump else ('NOT_REACHED' if ms is not None else 'UNKNOWN'), f"t {jump['t_us']} us" if jump else '')
    text = S.mirror(raw); x = S.xnu(text)
    for st in ('window', 'takeover', 'test', 'rootdev', 'apfs_system', 'mounted', 'pid1_exec', 'md1_mounted', 'init', 'launchd_ios', 'cache_map', 'hello', 'xpcproxy'):
        v = (q or {}).get('stages', {}).get(st) if q else None
        if v is None and q: v = (q.get('reached') or {}).get(st) if isinstance(q.get('reached'), dict) else None
        if q is not None: add('xnu: ' + st, 'kernel', 'YES' if v else ('?' if v is None else 'NO'), '')
    pats = (('xnu: SpringBoard exec', r'posix_spawn[^\n]*SpringBoard[^\n]* = 0|SpringBoard\[\d+\]'), ('xnu: backboardd exec', r'posix_spawn[^\n]*backboardd[^\n]* = 0|backboardd\[\d+\]'), ('xnu: frame to RAM', r'swap \d+|MiniIOMobileFramebuffer[^\n]*(?:swap|show)'), ('xnu: scanout seam', r'scanout[^\n]*'))
    for nm, pat in pats:
        m = re.findall(pat, text); add(nm, 'kernel', 'YES' if m else 'NO', f'{len(m)} lines')
    panic = (q or {}).get('panic'); m = re.search(r'blazer-root: deadline (\d+) s[^\n]*', raw.decode('latin1'))
    add('end of boot', 'kernel', 'OWN_DEADLINE' if m else ('PANIC' if panic else 'NONE_SEEN'), (m.group(0) if m else str(panic))[:160])
    add('storage speed', 'info', f"{x.get('ms_per_block', '?')} ms/block", f"{x.get('blocks', '?')} blocks, busy {x.get('busy_s', '?')} s; 16x1 {round(16 * x['single_gap_ms'], 2) if 'single_gap_ms' in x else '?'} ms against 1x16 {x.get('multi16_est_ms', '?')} ms, from log spacing; mount to hello {x.get('mount_to_hello_s', '?')} s")
    return T, ms_list
def show(T):
    w = [max(len(str(r[i])) for r in T) for i in range(3)]
    print(f"{'stage':{w[0]}} | {'gate':{w[1]}} | {'result':{w[2]}} | evidence")
    for r in T: print(f"{r[0]:{w[0]}} | {r[1]:{w[1]}} | {r[2]:{w[2]}} | {r[3]}")
def stopped(ms):
    if not ms: return None
    m = ms[-1]
    return m['name'] if m['state'] == 'ENTER' and m['id'] != 10 else None
def main(path, mpath, js=False):
    man = json.loads(pathlib.Path(mpath).read_text()); man['_ids_path'] = str(pathlib.Path(mpath).with_name('ufs-ids.json'))
    raw = pathlib.Path(path).read_bytes(); T, ms = rows(raw, path, man)
    if js: print(json.dumps(dict(rows=T, marks=ms), indent=1)); return
    show(T); s = stopped(ms)
    if s: print(f'\nLAST STAGE ENTERED WITH NO END: {s}. A reset or hang here is the first suspect.')
def selftest():
    ids = dict(stamp_nonce=hex(0xb400000012345678), epoch=hex(0x202611012500), record_nonce=bytes(range(1, 17)).hex())
    def mk(seq, nonce=ids['stamp_nonce']):
        raw = bytearray(4 << 20); o = ALL_PA - BASE
        struct.pack_into('<QQQ', raw, o, ALL_MAGIC, int(nonce, 16), 1); raw[o + 24:o + 40] = bytes.fromhex(ids['record_nonce']); struct.pack_into('<I', raw, o + 40, len(seq))
        for i, (a, st, v) in enumerate(seq): struct.pack_into('<IiQ', raw, o + 64 + i * 16, a | st << 16, v, 1000 + i)
        return bytes(raw)
    m, e = marks(mk([(1, 1, 0), (4, 1, 0)]), ids); assert e is None and stopped(m) == 'HS change'
    m, e = marks(mk([(1, 1, 0), (2, 2, 0), (9, 1, 0)]), ids); assert stopped(m) == 'DPU frame'
    m, e = marks(mk([(9, 1, 0), (9, 5, 23), (10, 1, 0)]), ids); assert stopped(m) is None and last_of(m, 9)['state'] == 'FELL_THROUGH' and last_of(m, 9)['val'] == 23
    m, e = marks(mk([(1, 1, 0)], nonce=hex(5)), ids); assert m is None and 'another build' in e
    m, e = marks(bytes(4 << 20), ids); assert m is None
    assert refclk_signature(dict(change=dict(upmcrs=5, is_='0x10')), None) and refclk_signature({}, dict(uecpa=0x80000010, uecdl=0))
    assert not refclk_signature(dict(change=dict(upmcrs=1, is_='0x10')), dict(uecpa=0, uecdl=0))
    # Real capture, negative control for the stage record: ufs-speed-r1 on the phone had HS and no stage record.
    A = R/'laguna-usb-fix/attempts/20261101-204627-ufs-speed-r1/ramdump/kernel.log'; I = R/'ufs-speed-r1/run/speed/ufs-ids.json'
    if A.exists():
        i = json.loads(I.read_text()); man = dict(ids=i, features=['hs_gear4'], _ids_path=str(I)); T, ms = rows(A.read_bytes(), A, man); d = {r[0]: r for r in T}
        assert d['stage record'][2] == 'ABSENT' and d['HS change'][2] == 'HS_G4_2L' and d['HS verify'][2] == 'CRC_EQUAL', [d['stage record'], d['HS change'], d['HS verify']]
        show(T)
    assert features(dict(cflags='-DTGL_UFS_POWER_MODE=1 -DTGL_ALL_STAGES=1')) == {'hs_gear4'} and features(dict(features=['x'], cflags='-DTGL_ALL_DCS=1')) == {'x'}
    A = R/'laguna-usb-fix/attempts/20261101-215924-first-boot-r1/ramdump/kernel.log'; I = R/'ios26-bootchain-r1/run/first-boot-r1/manifest.json'
    if A.exists() and I.exists():
        T, ms = rows(A.read_bytes(), A, dict(json.loads(I.read_text()), _ids_path=str(I.parent/'ufs-ids.json'))); d = {r[0]: r for r in T}
        assert d['stage record'][2] == 'OK' and d['HS change'][2] == 'HS_G4_2L' and d['HS verify'][2] == 'CRC_EQUAL', T
    print('selftest: stage marks, nonce refusal, refclk signature, and the speed capture as negative control pass')
if __name__ == '__main__':
    a = sys.argv[1:]
    if a and a[0] == '--selftest': selftest()
    elif len(a) >= 2: main(a[0], a[1], '--json' in a)
    else: sys.exit(__doc__)
