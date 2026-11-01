#!/usr/bin/env python3
"""Host test of the power mode change. Needs out/ufs_test/ufs_replay.h from test_ufs_route.py. The expected order comes from the saved
Linux and vendor text, parsed here, never from tgl_ufs_host.c. A fake says nothing about hardware. Exit 0 only if all hold."""
import json, pathlib, re, shutil, subprocess, sys
S = pathlib.Path(__file__).resolve().parent; OUT = S/'out/ufs_test'; ROOT = next(q for q in S.parents if (q/'AGENTS.md').exists()); fails = []; checks = 0
F = ROOT/'research/laguna-usb-fix/native-fleet-20261031'
LX = F/'N881-g5-ufs-core-uic-ports/independent/linux-v6.6'; VN = F/'N873-g5-ufs-cold-start-source-port/vendor/private/google-modules/soc/rdo/drivers/ufs'
CC = 'cc'; BASE = [CC, '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-parameter']
SRC = ('tgl_ufs_route_test.c', 'tgl_ufs_link.c', 'tgl_ufs_host.c', 'tgl_ufs_handoff.c')
def ok(c, what):
    global checks; checks += 1
    if not c: fails.append(what); print('FAIL', what)
def build(name, on, d=S):
    e = OUT/name
    p = subprocess.run(BASE + [f'-DTGL_UFS_POWER_MODE={on}', f'-I{OUT}', f'-I{d}'] + [str(d/x) for x in SRC] + ['-o', str(e)], capture_output=True, text=True)
    if p.returncode: sys.exit(f'build {name}: ' + p.stderr[-2500:])
    return e
def run(e, sc):
    p = subprocess.run([str(e), sc, str(OUT/f'{e.name}.{sc}.rec'), str(OUT/f'{e.name}.{sc}.link')], capture_output=True, text=True, timeout=120)
    return p, p.stdout
def field(o, key, line='R'):
    m = re.search(rf'^{line} .*\b{key}=(-?\w+)', o, re.M); return m.group(1) if m else None
def trace(o): return re.findall(r'^T (.*)$', o, re.M)
# ---- Primary text ----
uni = (LX/'unipro.h').read_text(); core = (LX/'ufshcd.c').read_text(); vend = (VN/'ufs-google.c').read_text(); hci = (LX/'ufshci.h').read_text()
def D(n):
    m = re.search(rf'#define\s+{n}\s+(0[xX][0-9a-fA-F]+|\d+)', uni)
    if not m: sys.exit('not in unipro.h: ' + n)
    return int(m.group(1), 0)
def expected_sets(gear, lanes):
    """ufshcd_change_power_mode's DME_SETs, read off the function body in order, with the vendor's adapt in front."""
    body = core[re.search(r'static int ufshcd_change_power_mode\(struct ufs_hba \*hba,\s*struct ufs_pa_layer_attr \*pwr_mode\)\n\{', core).start():]; body = body[:body.index('\n}\n')]
    vals = dict(gear_rx=gear, gear_tx=gear, lane_rx=lanes, lane_tx=lanes, hs_rate=2, true=1)
    out = []
    for name, arg in re.findall(r'ufshcd_dme_set\(hba, UIC_ARG_MIB\((\w+)\),\s*([\w\->_]+)\)', body):
        a = arg.split('->')[-1]
        if a == 'false': continue
        v = vals[a] if a in vals else D(a)
        out.append((name, D(name) if not name.startswith('PA_PWRMODEUSERDATA') else D('PA_PWRMODEUSERDATA0') + int(name[-1]), v))
    if 'PA_INITIAL_ADAPT' not in vend[vend.index('/* Set Adapt */'):vend.index('/* Set Adapt */') + 400]: sys.exit('vendor adapt text moved')
    return [('PA_TXHSADAPTTYPE', D('PA_TXHSADAPTTYPE'), D('PA_INITIAL_ADAPT'))] + out
SETS = expected_sets(4, 2)
ok(len(SETS) == 17, f'17 SETs in the source order: {len(SETS)}')
ok([n for n, _, _ in SETS[:4]] == ['PA_TXHSADAPTTYPE', 'PA_RXGEAR', 'PA_ACTIVERXDATALANES', 'PA_RXTERMINATION'], 'adapt, then RX group')
# Negative control of this parser: a wrong gear or dropped row must differ from what the real source gives.
ok(expected_sets(3, 2) != SETS and expected_sets(4, 1) != SETS, 'parser sees gear and lanes')
ok(int(re.search(r'#define UIC_POWER_MODE\s+(0x\w+)', hci).group(1), 0) == 0x10, 'IS.UPMS bit from ufshci.h')
ok(re.search(r'PWR_LOCAL\s*=\s*0x01', hci) and re.search(r'UIC_POWER_MODE_CHANGE_REQ_STATUS_MASK\s+UFS_MASK\(0x7, 8\)', hci), 'UPMCRS field and PWR_LOCAL from ufshci.h')
ok(re.search(r'#define UIC_CMD_TIMEOUT\s+500', core), 'UIC_CMD_TIMEOUT 500 ms')
ok(re.search(r'\.gear_rx = UFS_HS_G5', vend) and re.search(r'\.lane_rx = UFS_LANE_2', vend) and re.search(r'\.hs_rate = PA_HS_MODE_B', vend), 'vendor wants 2 lanes, rate B, cap G5')
ok(re.search(r'UFS_VENDOR_SAMSUNG,\s*\.model = UFS_ANY_MODEL,\s*\.quirk = UFS_DEVICE_QUIRK_DELAY_BEFORE_LPM \|\s*UFS_DEVICE_QUIRK_HOST_PA_TACTIVATE', core), 'Samsung HOST_PA_TACTIVATE quirk in ufs_fixups')
# ---- The two builds ----
off = build('off', 0); on = build('on', 1)
p0, o0 = run(off, 'replay'); ok(p0.returncode == 0 and field(o0, 'rc') == '0' and field(o0, 'reads') == '21', 'gate off: same 21 reads, no violation')
ok('state=' not in o0 and not any(x.startswith('UIC 2 1571') for x in trace(o0)), 'gate off: no power mode change')
p1, o1 = run(on, 'replay'); ok(p1.returncode == 0, 'gate on: no violations: ' + o1[-400:] if p1.returncode else 'x')
ok(field(o1, 'rc') == '0' and field(o1, 'reads') == '33' and field(o1, 'state', 'P') == '3' and field(o1, 'hs', 'P') == '1' and field(o1, 'outcome', 'F') == '1', 'gate on: HS, 12 verified reads, handoff LIVE')
t0, t1 = trace(o0), trace(o1)
ok(t1[:len(t0)] == t0, 'gate on: everything up to the change is the trace the phone ran')
tail = t1[len(t0):]
def uicv(op, a, v=0): return f'UIC {op:x} {a:x} {v:x}'
MODE = [uicv(1, a) for a in (D('PA_PWRMODE'), D('PA_RXGEAR'), D('PA_TXGEAR'), D('PA_ACTIVERXDATALANES'), D('PA_ACTIVETXDATALANES'))]
CAPS = [uicv(1, D('PA_CONNECTEDRXDATALANES')), uicv(1, D('PA_CONNECTEDTXDATALANES')), uicv(1, D('PA_MAXRXHSGEAR')), uicv(3, D('PA_MAXRXHSGEAR'))]
TACT = [uicv(1, D('PA_GRANULARITY')), uicv(3, D('PA_GRANULARITY')), uicv(1, D('PA_TACTIVATE')), uicv(3, D('PA_TACTIVATE'))]
want = MODE + CAPS + TACT + [uicv(2, a, v) for _, a, v in SETS] + [uicv(2, D('PA_PWRMODE'), 0x11)] + MODE
ok(tail == want, f'change order from source text: {[x for x, y in zip(tail, want) if x != y][:3]} len {len(tail)} want {len(want)}')
ok(not [x for x in tail if not x.startswith('UIC ')], 'nothing but DME: no pad, SMC, HCE, HCLKDIV or TOP write')
FORBID = {0x8101, 0x8115, 0x8019, 0x8013, 0x8016, 0x810e, 0x810f, 0x8110, 0x8111, 0x8114, 0xd0c1}
ok(not [x for x in tail if int(x.split()[2], 16) in FORBID], 'no PHY calibration, patch or TX-EQ attribute')
# ---- Record ----
ids = dict(nonce='bdf582b45d69800af51a519354958306', epoch='0x202611012500')
d = subprocess.run([sys.executable, '-I', str(ROOT/'research/ufs-read-r2/decode_read.py'), str(OUT/'on.replay.rec'), ids['nonce'], ids['epoch'], '--raw-record'], capture_output=True, text=True)
ok(d.returncode == 0, 'decode_read.py, unmodified, reads the record: ' + d.stderr[-300:])
if not d.returncode:
    dd = json.loads(d.stdout)
    ok(dd['end']['dropped_entries'] == 0 and dd['end']['rc'] == 'OK', f"no entry dropped, sealed OK: {dd['end']['dropped_entries']} {dd['end']['rc']}")
    ok(sum(r['step'] == 17 for r in dd['reads']) == 12, 'twelve HS_VERIFY reads recorded')
    a = [(r['lba'], r['crc32']) for r in dd['reads'] if r['step'] == 'TARGET']; b = [(r['lba'], r['crc32']) for r in dd['reads'] if r['step'] == 17]
    ok(a == b and len(a) == 12, 'HS CRCs equal PWM CRCs, block for block')
    g = [x for x in dd['gates'] if x['where'] == 0x401]; ok(len(g) == 1 and g[0]['cr0'] == 0 and (g[0]['gbpa'] >> 8) & 7 == 1, 'DONE note: rc 0, UPMCRS PWR_LOCAL')
    n = {x['where']: x for x in dd['gates']}
    ok(n[0x402]['cr0'] == 0x55 and n[0x402]['cr0ack'] == 1 and n[0x405]['cr0'] == 0x11 and n[0x405]['cr0ack'] == 4 and n[0x405]['gbpa'] == 4, 'BEFORE and AFTER notes hold the mode')
    ok(any(x['where'] == 0x500 for x in dd['gates']), 'SMMU gate again before HS reads')
# ---- Scenarios: refusals leave PWM; failures leave no kernel on a broken link ----
for sc, rc, state, out in [('pmc_refused', '-27', '2', '2'), ('pmc_no_upms', '-27', '2', '2'), ('pmc_link_lost', '-27', '2', '2'), ('pmc_upmcrs_bad', '-27', '2', '2'),
                           ('peer_get_fail', '-8', '0', '2'), ('hs_crc', '-28', '2', '2'), ('hs_timeout', '-10', '2', '-1')]:
    p, o = run(on, sc); ok(p.returncode == 0, f'{sc}: no violation')
    ok(field(o, 'rc') == rc and field(o, 'state', 'P') == state and field(o, 'outcome', 'F') == out, f'{sc}: rc {field(o, "rc")} state {field(o, "state", "P")} outcome {field(o, "outcome", "F")}')
    if sc.startswith('pmc_') or sc == 'peer_get_fail': ok(field(o, 'reads') == '21', f'{sc}: no READ after a failed change')
for sc in ('gear3', 'one_lane'):
    p, o = run(on, sc); t = trace(o)
    ok(p.returncode == 0 and field(o, 'rc') == '0' and field(o, 'state', 'P') == '1' and field(o, 'hs', 'P') == '0' and field(o, 'reads') == '21' and field(o, 'outcome', 'F') == '1', f'{sc}: stays PWM, handoff LIVE')
    ok(not [x for x in t[len(t0):] if x.startswith('UIC 2 ') or x.startswith('UIC 4 ')], f'{sc}: refused before any SET')
p, o = run(on, 'replay'); ok(field(o, 'peer_sets', 'P') == '0', 'peer TActivate longer than host: no peer write')
p, o = run(on, 'tact_peer_low'); ok(field(o, 'peer_sets', 'P') == '1' and field(o, 'peer_tact', 'P') == '4' and p.returncode == 0, 'peer TActivate shorter: 3*16/16+1, as ufshcd.c')
# ---- Wire gate with the bound raised ----
g = (OUT/'gate.c').read_text().replace('i < 40;', 'i < 60;'); (OUT/'gate_on.c').write_text(g)
q = subprocess.run([CC, '-std=gnu11', '-O1', '-w', '-DTGL_UFS_POWER_MODE=1', f'-I{S}', str(OUT/'gate_on.c'), '-o', str(OUT/'gate_on')], capture_output=True, text=True); ok(q.returncode == 0, 'gate build ' + q.stderr[-300:])
g2 = subprocess.run([str(OUT/'gate_on')], capture_output=True, text=True); ok(g2.returncode == 0, 'wire gate, bound 44: ' + g2.stdout[-300:]); print(g2.stdout.strip())
# ---- Mutants ----
M = {'no adapt': ('{ PA_TXHSADAPTTYPE, PA_INITIAL_ADAPT }, ', ''), 'gear 3': ('#define HS_GEAR 4u', '#define HS_GEAR 3u'), 'one lane': ('#define HS_LANES 2u', '#define HS_LANES 1u'),
     'slow mode': ('#define PWR_FAST_BOTH 0x11u', '#define PWR_FAST_BOTH 0x22u'), 'rate A': ('#define PA_HS_MODE_B 2u', '#define PA_HS_MODE_B 1u'),
     'TX before RX': ('{ PA_RXGEAR, HS_GEAR }, { PA_ACTIVERXDATALANES, HS_LANES }, { PA_RXTERMINATION, 1 },\n        { PA_TXGEAR, HS_GEAR }, { PA_ACTIVETXDATALANES, HS_LANES }, { PA_TXTERMINATION, 1 },', '{ PA_TXGEAR, HS_GEAR }, { PA_ACTIVETXDATALANES, HS_LANES }, { PA_TXTERMINATION, 1 },\n        { PA_RXGEAR, HS_GEAR }, { PA_ACTIVERXDATALANES, HS_LANES }, { PA_RXTERMINATION, 1 },'),
     'wrong timeout': ('{ DME_LOCALFC0, 8191 }', '{ DME_LOCALFC0, 8190 }'), 'UPMCRS ignored': ('if (UPMCRS(hcs) == PWR_LOCAL) rc = 0;', 'rc = 0;'), 'UIC refusal ignored': ('if (a2 & 0xffu) break; /* refused: no UPMS will come */', ''),
     'link lost ignored': ('if (v & IS_FATAL) break;\n        if (v & IS_UCCS) {', 'if (v & IS_UCCS) {'), 'no timeout': ('if (us >= PMC_TIMEOUT_US) break;', 'if (polls > 200000u) return 0;'),
     'no CRC compare': ('if (crc != s->target_crc[i]) return TGL_UFSH_E_HS_CRC;', ''), 'no HS verify': ('if ((r = hs_verify(s))) return r;', ''), 'no TActivate': ('(r = tune_peer_tactivate(s)) || ', ''),
     'no mode note': ('if ((r = read_mode(s, TGL_UFSH_PMC_WHERE_BEFORE))) return r;', ''),
     'peer TActivate off by one': ('t_us / us[pg - 1u] + 1u', 't_us / us[pg - 1u]'), 'refusal gets a SET': ('if (reason) { o->pmc_state = 1;', 'if (reason) { (void)change_power_mode(s); o->pmc_state = 1;'),
     'skip checks lanes no more': ('if (rx != HS_LANES || tx != HS_LANES) reason = 1;\n    else if', 'if'), 'state not set': ('o->pmc_state = 3;', 'o->pmc_state = 2;'), 'gate not rerun': ('if ((r = smmu_gate(s, 0x500u))) return r;', ''),
     'change before reads': ('    if (!rc) rc = read_pass(s);\n#endif\n#if TGL_UFS_POWER_MODE\n    if (!rc) rc = tgl_ufsh_power_mode(s);', '    if (!rc) rc = tgl_ufsh_power_mode(s);\n    if (!rc) rc = read_pass(s);\n#endif\n#if TGL_UFS_POWER_MODE')}
def done_us(e, sc):
    d = subprocess.run([sys.executable, '-I', str(ROOT/'research/ufs-read-r2/decode_read.py'), str(OUT/f'{e.name}.{sc}.rec'), ids['nonce'], ids['epoch'], '--raw-record'], capture_output=True, text=True)
    g = [x for x in json.loads(d.stdout)['gates'] if x['where'] == 0x401] if not d.returncode else []
    return g[0]['gerror'] if g else None
# A refusal and a lost link end at once. Silence is what waits out the 500 ms.
for sc, fast in (('pmc_refused', 1), ('pmc_link_lost', 1), ('pmc_upmcrs_bad', 1), ('pmc_no_upms', 0)):
    run(on, sc); u = done_us(on, sc); ok(u is not None and (u < 1000 if fast else u >= 500000), f'{sc}: {u} us to the end of the wait')
def alive(e):
    p, o = run(e, 'replay')
    if p.returncode or field(o, 'rc') != '0' or field(o, 'state', 'P') != '3' or trace(o)[len(t0):] != want or field(o, 'reads') != '33': return False
    d = subprocess.run([sys.executable, '-I', str(ROOT/'research/ufs-read-r2/decode_read.py'), str(OUT/f'{e.name}.replay.rec'), ids['nonce'], ids['epoch'], '--raw-record'], capture_output=True, text=True)
    if d.returncode or not any(x['where'] == 0x500 for x in json.loads(d.stdout)['gates']): return False
    for sc, rc, st in [('pmc_refused', '-27', '2'), ('pmc_no_upms', '-27', '2'), ('pmc_link_lost', '-27', '2'), ('pmc_upmcrs_bad', '-27', '2'), ('hs_crc', '-28', '2')]:
        p, o = run(e, sc)
        if p.returncode or field(o, 'rc') != rc or field(o, 'state', 'P') != st: return False
    for sc in ('pmc_refused', 'pmc_link_lost'):
        run(e, sc); u = done_us(e, sc)
        if u is None or u >= 1000: return False
    for sc in ('gear3', 'one_lane'):
        p, o = run(e, sc)
        if p.returncode or field(o, 'state', 'P') != '1' or field(o, 'hs', 'P') != '0' or [x for x in trace(o)[len(t0):] if x.startswith(('UIC 2 ', 'UIC 4 '))]: return False
    p, o = run(e, 'tact_peer_low')
    return not p.returncode and field(o, 'peer_tact', 'P') == '4'
Ms = OUT/'mut_speed'; caught = 0
src = (S/'tgl_ufs_host.c').read_text()
for name, (a, b) in M.items():
    if src.count(a) != 1: sys.exit(f'mutant {name}: {src.count(a)} matches')
    shutil.rmtree(Ms, ignore_errors=True); Ms.mkdir()
    for x in SRC + ('tgl_ufs_link.h', 'tgl_ufs_host.h', 'tgl_ufs_handoff.h'): shutil.copy2(S/x, Ms/x)
    (Ms/'tgl_ufs_host.c').write_text(src.replace(a, b))
    e = OUT/'m'; q = subprocess.run([CC, '-std=gnu11', '-O1', '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-w', '-DTGL_UFS_POWER_MODE=1', f'-I{OUT}', f'-I{Ms}'] + [str(Ms/x) for x in SRC] + ['-o', str(e)], capture_output=True, text=True)
    if q.returncode: fails.append('mutant build ' + name + q.stderr[-200:]); continue
    if alive(e): fails.append('mutant survived: ' + name); print('survived', name)
    else: caught += 1
print(f'speed mutants {caught}/{len(M)} caught')
ok(caught == len(M), 'all mutants caught')
print(f'ufs speed host test: {checks} checks, {len(fails)} failed')
if fails: print('\n'.join(fails)); sys.exit(1)
