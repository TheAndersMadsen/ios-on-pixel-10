#!/usr/bin/env python3
"""Host test of tgl_dcs.c's DPU stage on a fake bus, gate TGL_DCS_BRIGHT off and on. Literals against vendor source, traces against the code before the gate, the phone's handoff flow, a reset at every access of the write, mutants.
  test_dcs_bright.py          everything
  test_dcs_bright.py --quick  no mutants: what build.sh runs
  test_dcs_bright.py --golden <shim dir of the commit before the gate>   print the trace hashes for GOLDEN
A fake says nothing about hardware. Exit 0 only if all hold."""
import concurrent.futures as cf, hashlib, json, os, pathlib, re, shutil, struct, subprocess, sys
S = pathlib.Path(__file__).resolve().parent; OUT = S/'out/dcs_test'; ROOT = next(p for p in S.parents if (p/'AGENTS.md').exists())
sys.dont_write_bytecode = True; sys.path.insert(0, str(S))
import decode_dcs_bright as DB
fails = []; checks = 0
def ok(c, what):
    global checks; checks += 1
    if not c: fails.append(what); print('FAIL', what)
CC = ['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-unused-function', '-DTGL_DCS_HOSTTEST', '-DTGL_TAKEOVER_NO_BARRIER', '-DTGL_TAKEOVER_BASE=({ extern volatile uint32_t dcs_test_takeover[]; dcs_test_takeover; })']
R1, R2, R3 = ['-DTGL_FRAME_RUNG=1'], ['-DTGL_FRAME_RUNG=2'], ['-DTGL_FRAME_RUNG=3']; PHONE = R3 + ['-DTGL_DCS_HANDOFF=1']; ON = ['-DTGL_DCS_BRIGHT=1']
SRC_FILES = ('tgl_dcs.c', 'tgl_dcs.h', 'dcs_tables.h', 'frame_tables.h', 'tgl_scanout_takeover.h', 'tensor_takeover.h', 'tgl_dcs_bright_test.c')
def build(name, flags, d=S, inc=None):
    e = OUT/name
    p = subprocess.run(CC + flags + [f'-I{d}'] + ([f'-I{inc}'] if inc else []) + [str(d/'tgl_dcs.c'), str(S/'tgl_dcs_bright_test.c'), '-o', str(e)], capture_output=True, text=True)
    return (e, None) if not p.returncode else (None, p.stderr[-1500:])
def run(e, sc, rec=None, tr=None, timeout=120):
    return subprocess.run([str(e), sc] + ([str(rec)] if rec else []) + ([str(tr)] if tr else []), capture_output=True, text=True, timeout=timeout)
def result(p):
    m = re.search(r'^R rc=(-?\d+) dbv=(\w+) writes=(\d+)', p.stdout, re.M)
    return None if not m else dict(rc=int(m[1]), dbv=int(m[2], 16), writes=int(m[3]))
def dump(rec):
    raw = bytearray(4 << 20); b = pathlib.Path(rec).read_bytes(); raw[0x238000:0x238000 + len(b)] = b; return bytes(raw)
def trace_sha(t): return hashlib.sha256(pathlib.Path(t).read_bytes()).hexdigest()
# Trace of scenario ok on the code before the gate: commit e8cc6a0's tgl_dcs.c and tgl_dcs.h, this fake. Regenerate only if the DPU stage changes on purpose.
GOLDEN = {'r1': '4d20ac440d03f168135b611f4f0d9a52b3ab6ac1bc2b564c0a711ce5df8d1256', 'r2': '85c6e74a1b1a7faefe6010254f01c2495bd45fac3bec73e3b7e1009af73401b5', 'r3': '6379babe1fcd2a6e2b951fc4ce90b0448a8b2a259786301046c2ed5187774eea', 'phone': 'ea240b49a356f18c9c0908df8f5539ba394f429e891e1563caf5afa0bf94e77b'}
CONF = dict(r1=R1, r2=R2, r3=R3, phone=PHONE)
if '--golden' in sys.argv:
    OUT.mkdir(parents=True, exist_ok=True); d = pathlib.Path(sys.argv[sys.argv.index('--golden') + 1]).resolve()
    for k, f in CONF.items():
        e, err = build('golden_' + k, f, d)
        if not e: sys.exit(err)
        p = run(e, 'ok', OUT/'g.rec', OUT/'g.tr')
        print(k, trace_sha(OUT/'g.tr'), p.stdout.split('\n')[0])
    sys.exit(0)
QUICK = '--quick' in sys.argv
shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir(parents=True)
# ---- literals, against vendor source and the blazer FDT
V1 = ROOT/'research/workspace/sources/reference/grapheneos-panel-bmea-20261025/panel-gs-bmea.c'  # same bytes as research/display-frame-r1/sources/vendor
V2 = ROOT/'research/upstream/patch-scout-chips/pixel10-aosp/private/google-modules/display/panels/muzel/panel-gs-bmea.c'  # the pinned kernel source of the phone's line
GP = ROOT/'research/display-frame-r1/sources/gs_panel.c'; GD = ROOT/'research/display-frame-r1/sources/gs_panel_funcs_defaults.c'; DSIC = ROOT/'research/workspace/sources/linux-next/drivers/gpu/drm/drm_mipi_dsi.c'; DTB = ROOT/'research/laguna-foundation/kernel-blazer/devices/blazer/fdt/laguna.dtb'
C = (S/'tgl_dcs.c').read_text(); H = (S/'tgl_dcs.h').read_text()
for v in (V1, V2):
    t = v.read_text(); w = v.parent.name
    m = re.search(r'bmea_brt_configs\[\] = \{\s*\{\s*\.panel_rev = PANEL_REV_GE\(\(u32\)PANEL_REV_EVT1\),\s*\.default_brightness = (\d+), /\* dbv_for_140_nits \*/.*?\.nits = \{\s*\.min = (\d+),\s*\.max = (\d+),\s*\},\s*\.level = \{\s*\.min = (\d+),\s*\.max = (\d+),.*?\.hbm = \{\s*\.nits = \{\s*\.min = (\d+),\s*\.max = (\d+),\s*\},\s*\.level = \{\s*\.min = (\d+),\s*\.max = (\d+),', t, re.S)
    ok(m and tuple(map(int, m.groups())) == (4637, 1, 1450, 492, 13418, 1450, 2250, 13419, 16383), f'{w}: EVT1+ brightness config: default 4637, normal 492-13418 is 1-1450 nits, hbm to 16383 is 2250')
    ok('brightness = swab16(br);' in t and 'ret = gs_dcs_set_brightness(ctx, brightness);' in t, f'{w}: bmea_set_brightness swaps, then gs_dcs_set_brightness')
    ok(re.search(r'#define BMEA_ACL_ENHANCED_THRESHOLD_DBV 3726', t), f'{w}: ACL threshold')
    ok('DEFINE_BMEA_PANEL_DESC(gs_bzea, bzea_modes' in t and '{ .compatible = "google,gs-bzea", .data = &gs_bzea }' in t, f'{w}: this driver owns google,gs-bzea, not a sibling')
    ok('GS_DSI_CMD(MIPI_DCS_SET_DISPLAY_BRIGHTNESS, 0x12, 0xB1)' in t and '/* AOD Sun Mode, 150nit */' in t, f'{w}: the driver writes the level high byte first: 0x12B1 is its 150 nits')
    ok(re.search(r'u8 rev = \(\(build_code & 0xE0\) >> 3\) \| \(\(build_code & 0x0C\) >> 2\);', t), f'{w}: rev from the build code')
    ok(re.search(r'\.dbv_extra_frame = true', t), f'{w}: dbv_extra_frame')
    ok(re.search(r'unlock_cmd_f0', t[t.index('static int bmea_set_brightness'):t.index('static void bmea_wait_for_vsync_done')]) is None, f'{w}: 0x51 needs no test key')
t = V1.read_text(); ok('(brightness >> 8) & 0xFF,' in t and 'brightness & 0xFF);' in t, 'bmea_enable: high byte first')
g = GP.read_text(); ok(re.search(r'return mipi_dsi_dcs_set_display_brightness\(dsi, br\);', g), 'gs_dcs_set_brightness calls the Linux helper')
d = DSIC.read_text()
ok('u8 payload[2] = { brightness & 0xff, brightness >> 8 };' in d[d.index('int mipi_dsi_dcs_set_display_brightness(struct'):d.index('EXPORT_SYMBOL(mipi_dsi_dcs_set_display_brightness);')], 'Linux helper sends low byte first; with swab16, the high byte goes first on the wire')
ok(re.search(r'default:\s*msg\.type = MIPI_DSI_DCS_LONG_WRITE;', d), '3 bytes is a DCS long write, 0x39')
rc_ = GD.read_text(); ok(re.search(r'case 0x14:\s*ctx->panel_rev_id\.id = PANEL_REVID_MP;', rc_), 'rev 0x14 is MP')
ok(((0xa0 & 0xe0) >> 3 | (0xa0 & 0x0c) >> 2) == 0x14 and '{ 0x0a, 0xa0, 0xa1, 0x42 }' in C, 'this panel: id byte 0xa0 gives rev 0x14, MP, at or above EVT1')
if shutil.which('fdtget'):
    fg = lambda p, k: subprocess.run(['fdtget', str(DTB), p, k], capture_output=True, text=True).stdout.strip()
    ok(fg('/chosen/display/panel@0', 'brightness') == '4637' and fg('/chosen/display/panel@0', 'panel_name') == 'google-bzea' and fg('/chosen/display/panel@0', 'panel_id') == '0x42a1a00a', 'laguna.dtb: ABL reports 4637 for google-bzea 42a1a00a')
else: ok(False, 'fdtget missing')
ok('TGL_DCS_BRIGHT_DBV 4637u' in C and 'k_bright[3] = { 0x51, TGL_DCS_BRIGHT_DBV >> 8, TGL_DCS_BRIGHT_DBV & 0xff }' in C, 'patch literal: 4637, high byte first')
ok('di | len << 8 | HDR_LONG | d.tx_mode' in C and 'dcs_long(0x39, k_bright, 3)' in C, 'long write, in the mode stage F found')
# the decoder's constants against the header
def enum_of(first):
    m = re.search(r'enum \{ ' + first + r'( = \d+)?,(.*?)\};', H, re.S); names = [first] + [x.strip().split(' ')[0] for x in m[2].split(',') if x.strip()]
    start = int(m[1].split('=')[1]) if m[1] else 0
    return {n: start + i for i, n in enumerate(names)}
en = enum_of('DCS_N_TOP_STATE_BEFORE'); br = enum_of('DCS_BR_OK')
ok(all(en[a] == DB.N[b] for a, b in [('DCS_N_POWER_MODE', 'POWER_MODE'), ('DCS_N_ERR_COUNT', 'ERR_COUNT'), ('DCS_N_READ_FAIL', 'READ_FAIL'), ('DCS_N_INT_MAIN', 'INT_MAIN'), ('DCS_N_BRIGHTNESS', 'BRIGHTNESS'), ('DCS_N_BRIGHT_TARGET', 'TARGET'), ('DCS_N_BRIGHT_AT_WRITE', 'AT_WRITE'), ('DCS_N_BRIGHT_SETTLED', 'SETTLED'), ('DCS_N_BRIGHT_ERR_COUNT', 'ERR_AFTER'), ('DCS_N_BRIGHT_POWER', 'POWER_AFTER'), ('DCS_N_BRIGHT_RESULT', 'RESULT')]), 'decoder note ids match tgl_dcs.h')
ok(all(br['DCS_BR_' + v] == k for k, v in DB.RESULT.items()), 'decoder result names match tgl_dcs.h')
# Vendor's stated points against the curve the decoder reports. Every number but the top two comes from a comment or a config in the driver.
for dbv, n_ in [(492, 1), (673, 2), (1398, 10), (2904, 50), (4637, 140), (4785, 150), (13418, 1450), (16383, 2250)]: ok(abs(DB.nits(dbv) - n_) <= max(0.5, n_ * 0.01), f'curve at {dbv}: vendor {n_}, fit {DB.nits(dbv)}')
ok(abs(DB.nits(0x295e) - 861) < 2 and abs(DB.nits(0x11b3) - 133) < 2, 'ABL levels on the curve')
# ---- the code off and on
exes = {}
def need(name, flags):
    e, err = build(name, flags)
    if not e: sys.exit(f'build {name}: {err}')
    exes[name] = e; return e
with cf.ThreadPoolExecutor(8) as ex:
    for f in [ex.submit(need, k + '_' + g_, CONF[k] + (ON if g_ == 'on' else [])) for k in CONF for g_ in ('off', 'on')]: f.result()
# Gate off: exactly the bus trace of the code before the gate, in every configuration. No 0x51.
tr = {}
for k in CONF:
    p = run(exes[k + '_off'], 'ok', OUT/f'{k}_off.rec', OUT/f'{k}_off.tr')
    ok(not p.returncode and p.stdout.startswith('PASS'), f'{k} off: ok: ' + p.stdout[-300:] + p.stderr[-300:])
    ok(trace_sha(OUT/f'{k}_off.tr') == GOLDEN[k], f'{k} off: bus trace equals the code before the gate')
    r = result(p); ok(r and r['writes'] == 0 and r['dbv'] == 0x295e, f'{k} off: level untouched')
    d_ = DB.decode(dump(OUT/f'{k}_off.rec')); ok(not d_['gate_on'] and d_['result'] is None and d_['before'] == 0x295e and not d_['packets'], f'{k} off: record has no brightness result')
# Gate on: gate-off trace plus one run of accesses in stage G.
def parse(t): return pathlib.Path(t).read_text().splitlines()
for k in CONF:
    p = run(exes[k + '_on'], 'ok', OUT/f'{k}_on.rec', OUT/f'{k}_on.tr')
    ok(not p.returncode and p.stdout.startswith('PASS'), f'{k} on: ok: ' + p.stdout[-300:] + p.stderr[-300:])
    r = result(p); ok(r and r['writes'] == 1 and r['dbv'] == 4637 and r['rc'] == 0, f'{k} on: level {r}')
    a, b = parse(OUT/f'{k}_off.tr'), parse(OUT/f'{k}_on.tr'); i = 0
    while i < len(a) and i < len(b) and a[i] == b[i]: i += 1
    j = 0
    while j < len(a) - i and a[-1 - j] == b[-1 - j]: j += 1
    seg = b[i:len(b) - j]
    ok(i + j == len(a) and seg, f'{k} on: the only difference is one run of accesses')
    tx = [x for x in seg if x.startswith('W efd82c0 ')]; pl = [x for x in seg if x.startswith('W efd82c4 ')]
    ok(pl == ['W efd82c4 1d1251'], f'{k} on: payload word: 51 12 1d, one word {pl}')
    ok(tx[0] == 'W efd82c0 21000339', f'{k} on: first packet is the long write, LP, 3 bytes {tx[:1]}')
    # After it: 0x52 twice, 0x05, 0x0a, each with its return-size packet, in LP. Nothing else goes to the panel.
    ok(tx[1:] == ['W efd82c0 1000237', 'W efd82c0 11005206', 'W efd82c0 1000237', 'W efd82c0 11005206', 'W efd82c0 1000137', 'W efd82c0 11000506', 'W efd82c0 1000137', 'W efd82c0 11000a06'], f'{k} on: then only the read-backs {tx[1:]}')
    ok(not [x for x in seg if not re.match(r'[RW] efd8[0-9a-f]{3} ', x)], f'{k} on: the run touches only DSI host registers')
    ok(not [x for x in seg if x.startswith('W ') and not re.match(r'W efd82c[04] ', x)], f'{k} on: the run writes only CRI TX')
    d_ = DB.decode(dump(OUT/f'{k}_on.rec'))
    ok((d_['gate_on'], d_['before'], d_['target'], d_['at_write'], d_['settled'], d_['err_count'], d_['power_before'], d_['power_after'], d_['result']) == (True, 0x295e, 4637, 4637, 4637, 0, 0x9f, 0x9f, 'OK'), f'{k} on: record {d_}')
    ok(d_['packets'] == [dict(di='0x39', bytes='51121d', lp=True)], f'{k} on: record names the packet {d_["packets"]}')
    ok(d_['finished'] and d_['stop'] is None, f'{k} on: record finished')
# Scenarios: name -> (result, level after, writes, before, at write, settled, rc)
OKC = 0; G = 0x295e; T = 4637; ERR = {n: i for i, n in enumerate('OK REFUSED_PA FAULT SERROR BUDGET RECORD_FULL MAGIC MBA_TIMEOUT TOP_REPLY TOP_STATE LPCM_REPLY RATE DEAD_REG PHY_POLL MODE CRI_BUSY NO_PANEL_REPLY PANEL_ID DCS_REFUSED WDT GUARD_FAULT CHIP ISOLATION PPS NO_FRAME_DONE BAD_BUFFER SMMU_ON SMMU_ABORT FE_BUS'.split())}
SC = {'br_dim': ('OK', T, 1, 0x11b3, T, T, OKC), 'br_zero': ('OK', T, 1, 0, T, T, OKC), 'br_long_reply': ('OK', T, 1, G, T, T, OKC), 'br_ignored': ('MISMATCH', G, 1, G, G, G, OKC), 'br_late': ('OK', T, 1, G, G, T, OKC), 'br_never_latches': ('MISMATCH', G, 1, G, G, G, OKC),
      'br_no_readback': ('NO_READBACK', T, 1, G, None, None, OKC), 'br_settled_read_fails': ('NO_READBACK', T, 1, G, T, None, OKC), 'br_at_write_read_fails': ('OK', T, 1, G, None, T, OKC), 'br_before_read_fails': ('OK', T, 1, None, T, T, OKC), 'br_short_reply': ('NO_READBACK', T, 1, G, None, None, OKC),
      'br_ack_then_ok': ('OK', T, 1, G, None, T, OKC), 'br_int_flag': ('OK', T, 1, G, T, T, OKC), 'br_err_count': ('OK', T, 1, G, T, T, OKC), 'br_display_off': ('PANEL_NOT_UP', G, 0, G, None, None, OKC), 'br_sleep_in': ('PANEL_NOT_UP', G, 0, G, None, None, OKC),
      'neg_br_cri_stuck': (None, T, 1, G, None, None, ERR['CRI_BUSY']), 'neg_br_fault': (None, G, 0, G, None, None, ERR['FAULT']), 'neg_br_serror': (None, T, 1, G, None, None, ERR['SERROR']),
      'neg_br_fault_at_write_read': (None, T, 1, G, None, None, ERR['FAULT']), 'neg_br_fault_settled_read': (None, T, 1, G, T, None, ERR['FAULT']), 'neg_br_fault_err_read': (None, T, 1, G, T, T, ERR['FAULT']), 'neg_br_fault_power_read': (None, T, 1, G, T, T, ERR['FAULT'])}
OLD_OK = 'ok ok_phone_pps ok_top_already_on ok_slow_top ok_ref_76m ok_hs_fallback ok_first_ack ok_no_te ok_te_needs_pad ok_pad_set_no_te ok_stale_abl_pps ok_no_pps_read'.split()
OLD_NEG = 'neg_magic neg_mba_silent neg_top_reply neg_top_weird neg_top_never_on neg_dsi0_nack neg_prepare_nack neg_pix_minus3 neg_ref_rate neg_dead_reg neg_phy_ready neg_pll neg_mode neg_no_panel neg_wrong_id neg_cri_stuck_start neg_serror_dsi neg_fault neg_fe0_nack neg_chip neg_serror_dpu neg_iso_stuck neg_pps_mismatch neg_pps_byte88 neg_no_done'.split()
OLD_NEG1 = [n for n in OLD_NEG if n not in ('neg_iso_stuck', 'neg_pps_mismatch', 'neg_pps_byte88', 'neg_no_done')]
OLD3 = ['ok_smmu_abort', 'ok_underrun_first', 'ok_underrun_later', 'neg_smmu_on', 'neg_smmu_abort', 'neg_fe_bus', 'neg_no_fetch']
HANDOFF_SKIP = {'ok_underrun_first', 'ok_underrun_later', 'neg_fe_bus', 'neg_no_fetch'}
def scen_for(k):
    if k == 'r1': return ['ok', 'ok_top_already_on', 'ok_hs_fallback'] + OLD_NEG1
    if k == 'r2': return OLD_OK + OLD_NEG
    if k == 'r3': return OLD_OK + OLD_NEG + OLD3
    return [s for s in OLD_OK + OLD_NEG + OLD3 if s not in HANDOFF_SKIP]
def scenario(k, g_, s):
    p = run(exes[f'{k}_{g_}'], s, OUT/f'sc_{k}_{g_}_{s}.rec'); return k, g_, s, p
jobs = [(k, g_, s) for k in CONF for g_ in ('off', 'on') for s in scen_for(k)] + [(k, 'on', s) for k in CONF for s in SC] + [(k, g_, s) for k in CONF for g_ in ('off', 'on') for s in ('twice', 'allow')]
with cf.ThreadPoolExecutor(8) as ex: res = list(ex.map(lambda j: scenario(*j), jobs))
for k, g_, s, p in res:
    ok(not p.returncode and p.stdout.startswith('PASS'), f'{k} {g_} {s}: ' + p.stdout[-300:] + p.stderr[-300:])
    if s in SC and not p.returncode:
        want, lvl, wr_, be, at, se, rc = SC[s]; r = result(p); d_ = DB.decode(dump(OUT/f'sc_{k}_{g_}_{s}.rec'))
        ok(r['rc'] == rc and r['dbv'] == lvl and r['writes'] == wr_, f'{k} {s}: {r}')
        ok(d_['result'] == want and d_['before'] == be and d_['at_write'] == at and d_['settled'] == se, f'{k} {s}: record {d_["result"]} {d_["before"]} {d_["at_write"]} {d_["settled"]}')
        ok(d_['target'] == T, f'{k} {s}: target logged')
        if want and want != 'PANEL_NOT_UP': ok(d_['stop'] is None and d_['err_count'] == (3 if s == 'br_err_count' else 0) and d_['power_after'] == 0x9f, f'{k} {s}: the panel state after the write is on the record {d_}')
        if want == 'PANEL_NOT_UP': ok(d_['packets'] == [] and d_['stop'] is None, f'{k} {s}: no packet')
        if want is None: ok(d_['stop'] and d_['stop']['code'] == rc and d_['result'] is None, f'{k} {s}: a stop from the bus ends it, no result {d_["stop"]}')
# A panel not up keeps the whole later flow.
for k in CONF: ok(result(run(exes[k + '_on'], 'br_display_off'))['rc'] == 0, f'{k}: a dark panel still goes on')
# Physical: the real captures through this decoder. Each stage G read, before any write existed.
CAPS = {'205339-display-frame-r1a': 0x11b3, '205525-display-frame-r1b': 0x11b3, '210249-display-frame-r1c': 0x295e, '211212-display-frame-r1d': 0x295e, '220659-second-boot-r1': 0x295e, '221612-colour-r1': 0x295e, '232934-phone-preflight-r1': 0x295e}
replayed = 0
for n_, want in CAPS.items():
    cap = ROOT/'research/laguna-usb-fix/attempts'/('20261101-' + n_)/'ramdump/kernel.log'
    if cap.exists():
        d_ = DB.decode(cap.read_bytes()); replayed += 1
        ok(d_['before'] == want and not d_['gate_on'] and not d_['packets'] and d_['result'] is None and d_['power_before'] == 0x9f, f'capture {n_}: {d_["before"]}')
print(f'captures replayed: {replayed} of {len(CAPS)}')
good_ = dump(OUT/'phone_on.rec')
def refused(raw, ids=None):
    try: DB.decode(raw, ids=ids); return False
    except ValueError: return True
ok(refused(bytes(4 << 20)), 'decoder: no record refused')
ok(refused(good_, dict(stamp_nonce='0x1', record_nonce='00' * 16)), 'decoder: another boot refused')
ok(not refused(good_, dict(stamp_nonce=hex(0xb400000012345678), record_nonce=bytes(range(1, 17)).hex())), 'decoder: this boot accepted')
t_ = bytearray(good_); t_[0x238000 + 64 + 16 * 3 + 2] ^= 1; ok(DB.decode(bytes(t_))['entries'] == 3, 'decoder: a torn entry ends the record')
# Reset at every access of the write: the record names what was running, and the 0x51 is on the record before the panel has it.
a = parse(OUT/'phone_off.tr'); b = parse(OUT/'phone_on.tr'); i = 0
while a[i] == b[i]: i += 1
lens = len(b) - len(a); first = next(n for n, x in enumerate(parse(OUT/'phone_on.tr')) if x.startswith('W efd82c0 21000339'))
reset_points = 0
def die(n):
    rec = OUT/f'die_{n}.rec'; p = run(exes['phone_on'], f'die_{n}', rec); return n, rec, p
with cf.ThreadPoolExecutor(8) as ex: rs = list(ex.map(die, range(i + 1, i + lens + 2)))
for n, rec, p in rs:
    ok(not p.returncode and 'RESET-AT' in p.stdout, f'reset {n}: ' + p.stdout[-200:] + p.stderr[-200:])
    d_ = DB.decode(dump(rec)); wrote = int(re.search(r'br_writes=(\d+)', p.stdout)[1]); ok(not d_['finished'], f'reset {n}: not finished')
    ok(d_['target'] == T, f'reset {n}: target on the record before the write')
    if wrote: ok(d_['packets'] == [dict(di='0x39', bytes='51121d', lp=True)], f'reset {n}: write-ahead: the panel had the level and the record says so')
    reset_points += 1
print(f'reset points in the write: {reset_points}')
if QUICK:
    print(f'dcs bright host test (quick): {checks} checks, {len(fails)} failed')
    if fails: print('\n'.join(fails)); sys.exit(1)
    sys.exit(0)
# ---- mutants. Each one has to break a build or a check below.
def behaves(d, rung_flags, on):
    """None if this source passes everything the mutants are held to."""
    tag = pathlib.Path(d).name
    e, err = build(tag + '_x', rung_flags + (ON if on else []), d)
    if not e: return 'build: ' + err[-120:]
    def go(s, rec=None, tr=None):
        try: return run(e, s, rec, tr, timeout=60)
        except subprocess.TimeoutExpired: return None
    for s in ['allow', 'twice', 'ok'] + scen_for('r2' if rung_flags == R2 else 'phone' if rung_flags == PHONE else 'r3'):
        p = go(s)
        if p is None or p.returncode or not p.stdout.startswith('PASS'): return 'scenario ' + s
    rec = OUT/(tag + '.rec'); tr_ = OUT/(tag + '.tr')
    p = go('ok', rec, tr_); r = result(p); d_ = DB.decode(dump(rec))
    k = 'phone' if rung_flags == PHONE else 'r2' if rung_flags == R2 else 'r3'
    if not on:
        if trace_sha(tr_) != GOLDEN[k]: return 'gate off: trace differs from the code before the gate'
        return None
    if r['writes'] != 1 or r['dbv'] != T: return f'level {r}'
    if d_['packets'] != [dict(di='0x39', bytes='51121d', lp=True)]: return f'packet {d_["packets"]}'
    if (d_['before'], d_['target'], d_['at_write'], d_['settled'], d_['err_count'], d_['power_after'], d_['result']) != (G, T, T, T, 0, 0x9f, 'OK'): return f'record {d_}'
    for s, (want, lvl, wr_, be, at, se, rc) in SC.items():
        p = go(s, rec)
        if p is None or p.returncode or not p.stdout.startswith('PASS'): return 'scenario ' + s
        r = result(p); d_ = DB.decode(dump(rec))
        if r['rc'] != rc or r['dbv'] != lvl or r['writes'] != wr_: return f'{s}: {r}'
        if d_['result'] != want or d_['before'] != be or d_['at_write'] != at or d_['settled'] != se or d_['target'] != T: return f'{s}: record {d_["result"]}'
        if want is None and (not d_['stop'] or d_['stop']['code'] != rc): return f'{s}: stop {d_["stop"]}'
        if s == 'br_err_count' and d_['err_count'] != 3: return s
    return None
SRC = (S/'tgl_dcs.c').read_text(); HDR_T = (S/'tgl_dcs.h').read_text()
# Old mutants: research/display-frame-r1/tests/run_all.py's lists, verbatim. Off and on.
MUT = [('0x05272000', '0x05273000'), ('LPCM_DSI0_ON 0x01020001u', 'LPCM_DSI0_ON 0x01000001u'), ('LPCM_FE0_ON 0x01000001u', 'LPCM_FE0_ON 0x01010001u'), ('LPB_SET 0x05000002u', 'LPB_SET 0x05000001u'), ('PIX_PREPARE 0x00022302u', 'PIX_PREPARE 0x01022302u'), ('LPB_SSWRP_DPU 5u', 'LPB_SSWRP_DPU 4u'),
       ('DSI_CRI_TX_HDR 0x2c0u', 'DSI_CRI_TX_HDR 0x2c4u'), ('DSI_CRI_TX_PLD 0x2c4u', 'DSI_CRI_TX_PLD 0x2c8u'), ('DSI_CRI_RX_PLD 0x2ccu', 'DSI_CRI_RX_PLD 0x2d0u'), ('HDR_LONG (1u << 29)', 'HDR_LONG (1u << 30)'), ('HDR_RD (1u << 28)', 'HDR_RD (1u << 29)'), ('CORE_CRI_AVAIL (1u << 18)', 'CORE_CRI_AVAIL (1u << 17)'),
       ('{ 0x0a, 0xa0, 0xa1, 0x42 }', '{ 0x42, 0xa1, 0xa0, 0x0b }'), ('MODE_DATA_STREAM 4u', 'MODE_DATA_STREAM 3u'), ('if (b != want[i]) return stop_with', 'if (0) return stop_with'), ('v == 0 || v == 0xffffffffu', '0'), ('if (isr & (1u << 8))', 'if (0)'), ('v != old && (rc = wr', '(rc = wr'),
       ('k_b0opr[4] = { 0xb0, 0x01, 0x1a, 0x63 }', 'k_b0opr[4] = { 0xb0, 0x01, 0x1a, 0x64 }'), ('k_f0u[3] = { 0xf0, 0x5a, 0x5a }', 'k_f0u[3] = { 0xf0, 0x5a, 0x5b }'), ('if ((rc = dcs_long(0x39, k_fcl, 3)) || (rc = dcs_long(0x39, k_f0l, 3))) return rc;', ''), ('0x15u | 0x9du << 8', '0x15u | 0x9eu << 8'),
       ('if (v != VS_CHIP_ID_9400) return stop_with(DCS_C_CHIP, v);', ''), ('if (v & FR_ISO_DSI0) return stop_with(DCS_C_ISOLATION, v);', ''), ('(v & FR_ISO_DSI0) && (rc = wr(FR_DPU + FR_CLOCK_DOMAIN_ISOLATION, v & ~FR_ISO_DSI0))', '0'), ('(rc = stage_h()) || ', ''),
       ('if (pps_buf[i] != fr_pps[i]) return stop_with(DCS_C_PPS, i);', ';'), ('if ((rc = dcs_long(0x0a, fr_pps, 128))) return rc;', ''), ('if ((rc = reg_switch(1))) return rc;', ''), ('(rc = wr(FR_DPU + FR_OUTPUT0_SW_CONFIG, 1))', '0'), ('if (!hit) { (void)diag(); return stop_with(DCS_C_NO_FRAME_DONE, v); }', ''),
       ('if ((rc = wr(FR_DPU + FR_OUTPUT0, FR_OUTPUT0_WORK_MODE_CMD))) return rc;', ''), ('rmw_q(FR_OUTPUT0_CONFIG_COMMAND_OPT, FR_CMD_OPT_MASK, 0)', '0'), ('if ((rc = wr(FR_DPU + FR_POST_PROCESS_OUT, FR_POST_RESET))) return rc;', ''), ('(pattern >> (7u - i)) & 1u', '(pattern >> (6u - i)) & 1u'), ('uint32_t c = slot_white(s) ? 0xffffu : 0;', 'uint32_t c = 0xffffu;'),
       ('for (unsigned i = 0; i < sizeof fr_dsc / sizeof fr_dsc[0]; ++i) if ((rc = wr(FR_DPU + fr_dsc[i].off, fr_dsc[i].val))) return rc;', ''), ('for (unsigned i = 0; i < sizeof fr_cfg / sizeof fr_cfg[0]; ++i) if ((rc = wr(FR_DPU + fr_cfg[i].off, fr_cfg[i].val))) return rc;', ''), ('if (pa >= FR_DPU && pa < FR_DPU + 0x120000) return frame_off_ok((uint32_t)(pa - FR_DPU), wr);', 'if (pa >= FR_DPU && pa < FR_DPU + 0x120000) return 1;'), ('if ((rc = wr(FR_DPU + FR_OUTPUT0_START, 0))) return rc;', ''), ('PAD_DMUX_DPU_TE 0x2u', 'PAD_DMUX_DPU_TE 0x1u'), ('PAD_IE (1u << 8)', 'PAD_IE (1u << 3)'), ('PAD_OE (1u << 3)', 'PAD_OE (1u << 2)'), ('PAD_PUPD_PD 0x1u', 'PAD_PUPD_PD 0x2u'), ('PAD_DMUX 0x04u', 'PAD_DMUX 0x0cu'), ('if (hit) return 0;\n    if ((rc = pad_read', 'if ((rc = pad_read'), ('dcs_port_delay_us(PAD_OPEN_SETTLE_US);\n        if ((rc = wr(TE_PAD + PAD_TXDATA, (tx & ~(PAD_OE | PAD_PUPD_MASK)) | PAD_PUPD_PD))) return rc;', ''), ('if ((tx & PAD_OE) || (tx & PAD_PUPD_MASK) != PAD_PUPD_PD) {\n        if ((rc = wr(TE_PAD + PAD_TXDATA, tx & ~(PAD_OE | PAD_PUPD_MASK)))) return rc;', 'if ((tx & PAD_OE) || (tx & PAD_PUPD_MASK) != PAD_PUPD_PD) {')]
MUT3 = [('PPS_COMPARE_BYTES 89u', 'PPS_COMPARE_BYTES 88u'), ('PPS_COMPARE_BYTES 89u', 'PPS_COMPARE_BYTES 90u'), ('FB_B UINT64_C(0xf0e00000)', 'FB_B UINT64_C(0xf0e10000)'), ('LAYER_STRIDE (LAYER_W * 4u)', 'LAYER_STRIDE (LAYER_W * 4u + 64u)'), ('LAYER_X 320u', 'LAYER_X 321u'), ('frame_set_buffer(colour ? FB_A : FB_B, LAYER_STRIDE)', 'frame_set_buffer(FB_A, LAYER_STRIDE)'), ('c = y < 119u ? 0xffff0000u', 'c = y < 119u ? 0xff0000ffu'), ('dcs_port_civac(pa, (uint64_t)LAYER_H * LAYER_STRIDE);', ''), ('(gbpa & ~SMMU_GBPA_ABORT) | SMMU_GBPA_UPDATE', 'gbpa | SMMU_GBPA_UPDATE'), ('SMMU_GBPA_UPDATE (1u << 31)', 'SMMU_GBPA_UPDATE (1u << 30)'), ('(pa & 0xff) || (pa >> 40) || (stride & 0x3f) || !stride', '0'), ('if (ack & SMMU_CR0_EN) return stop_with(DCS_C_SMMU_ON, ack);', ''), ('if (!hit || (gbpa & SMMU_GBPA_ABORT)) return stop_with(DCS_C_SMMU_ABORT, gbpa);', ''), ('SMMU_GBPA 0x44u', 'SMMU_GBPA 0x48u'),
        ('if (fe & FR_FE_BUS_ERRORS) { (void)diag(); return stop_with(DCS_C_FE_BUS, fe); }', ''), ('if ((rc = wr(FR_DPU + FR_SH_PANEL0_POST_PRO_TP_ENABLE, 0))) return rc;', ''), ('if ((rc = rmw_q(FR_SH_LAYER0_CONFIG, FR_LAYER_CFG_MASK, FR_LAYER_CFG_XR24))) return rc;', ''), ('if ((rc = wr(FR_DPU + FR_SH_LAYER0_SIZE, w | h << FR_SIZE_H_SHIFT))) return rc;', ''), ('if ((rc = rmw_q(FR_LAYER0_CONFIG, FR_REG_SWITCH, on ? FR_REG_SWITCH : 0))) return rc;', ''), ('if ((rc = fill(FB_A, 1)) || (rc = fill(FB_B, 0))) return rc;', 'if ((rc = fill(FB_A, 1))) return rc;'), ('dcs_port_store64(pa + y * LAYER_STRIDE + x * 4u, v);', 'dcs_port_store64(pa + y * LAYER_W + x * 4u, v);')]
CALL = '#if TGL_DCS_BRIGHT\n    if ((rc = bright_set())) return rc;\n#endif\n'
# New mutants: (name, [(old, new), ...], file, configuration, gate on). File t is tgl_dcs.c, h is tgl_dcs.h.
NEW = [('bytes swapped', [('{ 0x51, TGL_DCS_BRIGHT_DBV >> 8, TGL_DCS_BRIGHT_DBV & 0xff }', '{ 0x51, TGL_DCS_BRIGHT_DBV & 0xff, TGL_DCS_BRIGHT_DBV >> 8 }')]), ('other level, inside the assert', [('TGL_DCS_BRIGHT_DBV 4637u', 'TGL_DCS_BRIGHT_DBV 4631u')]), ('other level, above the assert', [('TGL_DCS_BRIGHT_DBV 4637u', 'TGL_DCS_BRIGHT_DBV 10590u')]), ('below the ACL threshold', [('TGL_DCS_BRIGHT_DBV 4637u', 'TGL_DCS_BRIGHT_DBV 2737u')]),
       ('other command', [('k_bright[3] = { 0x51,', 'k_bright[3] = { 0x53,')]), ('short write type', [('dcs_long(0x39, k_bright, 3)', 'dcs_long(0x15, k_bright, 3)')]), ('allowlist open to any array', [('((b) == k_bright && (len) == 3 && (di) == 0x39)', '((len) == 3 && (di) == 0x39)')]), ('allowlist open to any type', [('((b) == k_bright && (len) == 3 && (di) == 0x39)', '((b) == k_bright && (len) == 3)')]), ('allowlist open to any length', [('((b) == k_bright && (len) == 3 && (di) == 0x39)', '((b) == k_bright && (di) == 0x39)')]),
       ('no write', [('if ((rc = dcs_long(0x39, k_bright, 3))) return rc;', '')]), ('written twice', [('if ((rc = dcs_long(0x39, k_bright, 3))) return rc;', 'if ((rc = dcs_long(0x39, k_bright, 3)) || (rc = dcs_long(0x39, k_bright, 3))) return rc;')]), ('write not called', [(CALL, '')]), ('written after the DPU is configured', [(CALL, ''), ('stage(DCS_S_L_PANEL_DSC);\n', 'stage(DCS_S_L_PANEL_DSC);\n#if TGL_DCS_BRIGHT\n    if ((rc = bright_set())) return rc;\n#endif\n')]), ('written after FE0 power', [(CALL, ''), ('stage(DCS_S_I_DPU_READ);\n', 'stage(DCS_S_I_DPU_READ);\n#if TGL_DCS_BRIGHT\n    if ((rc = bright_set())) return rc;\n#endif\n')]), ('written inside the test-key window', [(CALL, ''), ('if ((rc = dcs_long(0x39, k_f0u, 3)) || (rc = dcs_long(0x39, k_fcu, 3)) || (rc = dcs_long(0x39, k_b0opr, 4))) return rc;\n', 'if ((rc = dcs_long(0x39, k_f0u, 3)) || (rc = dcs_long(0x39, k_fcu, 3)) || (rc = dcs_long(0x39, k_b0opr, 4))) return rc;\n#if TGL_DCS_BRIGHT\n    { static int once; if (!once) { once = 1; if ((rc = bright_set())) return rc; } }\n#endif\n')]),
       ('panel state ignored', [('(panel_power & DCS_PM_UP) != DCS_PM_UP', '0')]), ('only display on checked', [('DCS_PM_UP 0x14u', 'DCS_PM_UP 0x04u')]), ('only sleep out checked', [('DCS_PM_UP 0x14u', 'DCS_PM_UP 0x10u')]), ('panel state not saved', [('    panel_power = b;\n', '')]), ('no target note', [('note(DCS_N_BRIGHT_TARGET, TGL_DCS_BRIGHT_DBV);', '')]), ('no result when skipped', [('{ note(DCS_N_BRIGHT_RESULT, DCS_BR_PANEL_NOT_UP); return 0; }', 'return 0;')]),
       ('no settle', [('dcs_port_delay_us(BRIGHT_SETTLE_US);', '')]), ('settle too short', [('BRIGHT_SETTLE_US 50000u', 'BRIGHT_SETTLE_US 5000u')]), ('no read at the write', [('if ((rc = bright_read(DCS_N_BRIGHT_AT_WRITE, &v, &ok))) return rc;', '')]), ('no settled read', [('if ((rc = bright_read(DCS_N_BRIGHT_SETTLED, &v, &ok))) return rc;', '')]), ('read-back always OK', [('!ok ? DCS_BR_NO_READBACK : v == TGL_DCS_BRIGHT_DBV ? DCS_BR_OK : DCS_BR_MISMATCH', 'DCS_BR_OK')]), ('mismatch reported as OK', [('v == TGL_DCS_BRIGHT_DBV ? DCS_BR_OK : DCS_BR_MISMATCH', 'DCS_BR_OK')]), ('no read-back reported as mismatch', [('!ok ? DCS_BR_NO_READBACK : ', '')]), ('no result note', [('note(DCS_N_BRIGHT_RESULT, !ok ? DCS_BR_NO_READBACK : v == TGL_DCS_BRIGHT_DBV ? DCS_BR_OK : DCS_BR_MISMATCH);', '')]), ('mismatch stops the boot', [('note(DCS_N_BRIGHT_RESULT, !ok ? DCS_BR_NO_READBACK : v == TGL_DCS_BRIGHT_DBV ? DCS_BR_OK : DCS_BR_MISMATCH);\n    return 0;', 'note(DCS_N_BRIGHT_RESULT, !ok ? DCS_BR_NO_READBACK : v == TGL_DCS_BRIGHT_DBV ? DCS_BR_OK : DCS_BR_MISMATCH);\n    return ok && v == TGL_DCS_BRIGHT_DBV ? 0 : stop_with(DCS_C_PPS, v);')]),
       ('read order swapped', [('*v = (uint32_t)b[0] << 8 | b[1]; *ok = 1;', '*v = (uint32_t)b[1] << 8 | b[0]; *ok = 1;')]), ('one byte counts as a read-back', [('if (!rc && n == 2) { *v', 'if (!rc && n >= 1) { *v')]), ('stale ok survives a failed read', [('    *ok = 0;\n    if (rc > 0) return rc;', '    if (rc > 0) return rc;')]), ('no read-back note', [('*ok = 1; note(id, *v); }', '*ok = 1; }')]), ('no error count after', [('if (!rc) note(DCS_N_BRIGHT_ERR_COUNT, b);', '')]), ('no power mode after', [('if (!rc) note(DCS_N_BRIGHT_POWER, b);', '')]), ('stop in the last read gets a result', [('if ((rc = dcs_read(0x0a, &b, 1, &n, d.tx_mode)) > 0) return rc;\n    if (!rc) note(DCS_N_BRIGHT_POWER, b);', 'rc = dcs_read(0x0a, &b, 1, &n, d.tx_mode);\n    if (!rc) note(DCS_N_BRIGHT_POWER, b);')]),
       ('written before the level is read', [(CALL, ''), ('if ((rc = dcs_read(0x52, b, 2, &n, d.tx_mode)) > 0) return rc;\n    if (!rc) note(DCS_N_BRIGHTNESS', '#if TGL_DCS_BRIGHT\n    if ((rc = bright_set())) return rc;\n#endif\n    if ((rc = dcs_read(0x52, b, 2, &n, d.tx_mode)) > 0) return rc;\n    if (!rc) note(DCS_N_BRIGHTNESS')]), ('panel state from the wrong read', [('    panel_power = b;\n', ''), ('    if (!rc) note(DCS_N_ERR_COUNT, b);\n', '    if (!rc) note(DCS_N_ERR_COUNT, b);\n#if TGL_DCS_BRIGHT\n    panel_power = b;\n#endif\n')])]
# Left out as equivalent: dropping a `return rc` after the write, a read-back or the error-count read, or in stage G. After a stop every access is refused, so the next call returns the same stop: same record, same bus.
def mk(name, pairs, hdr=None):
    d = OUT/('m_' + hashlib.sha1((name + repr(pairs)).encode()).hexdigest()[:10]); d.mkdir(exist_ok=True)
    for f in SRC_FILES: shutil.copy2(S/f, d/f)
    t = SRC
    for a, b in pairs:
        if t.count(a) < 1: return None, f'mutant {name}: no match for {a[:40]}'
        t = t.replace(a, b, 1)
    (d/'tgl_dcs.c').write_text(t)
    if hdr: (d/'tgl_dcs.h').write_text(HDR_T.replace(*hdr, 1))
    return d, None
jobs = []
for a, b in MUT: jobs.append(('old ' + a[:50], [(a, b)], R2, False, None)); jobs.append(('old+on ' + a[:50], [(a, b)], R2, True, None))
for a, b in MUT3: jobs.append(('old3 ' + a[:50], [(a, b)], R3, False, None)); jobs.append(('old3+on ' + a[:50], [(a, b)], R3, True, None))
for n, pairs in NEW: jobs.append(('new ' + n, pairs, PHONE, True, None))
jobs.append(('gate on by default', [], PHONE, False, ('#define TGL_DCS_BRIGHT 0', '#define TGL_DCS_BRIGHT 1')))
jobs.append(('gate on by default, rung 2', [], R2, False, ('#define TGL_DCS_BRIGHT 0', '#define TGL_DCS_BRIGHT 1')))
def job(j):
    name, pairs, fl, on, hdr = j
    d, err = mk(name, pairs, hdr)
    if err: return name, 'NOMATCH ' + err
    try: w = behaves(d, fl, on)
    except Exception as e: w = 'exception ' + repr(e)[:100]
    shutil.rmtree(d, ignore_errors=True)
    return name, w
with cf.ThreadPoolExecutor(8) as ex: mres = list(ex.map(job, jobs))
caught = 0
for name, w in mres:
    if w is None: fails.append('mutant survived: ' + name); print('survived', name)
    elif w.startswith('NOMATCH'): fails.append(w); print(w)
    else: caught += 1
print(f'mutants {caught}/{len(jobs)} caught (old {len(MUT)}+{len(MUT3)} off and on, new {len(NEW)}, gate 2)')
ok(caught == len(jobs), 'all mutants caught')
(OUT/'mutants.json').write_text(json.dumps(mres, indent=0))
print(f'dcs bright host test: {checks} checks, {len(fails)} failed')
if fails: print('\n'.join(fails)); sys.exit(1)
