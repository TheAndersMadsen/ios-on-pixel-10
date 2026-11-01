#!/usr/bin/env python3
"""Host test of all-r1's UFS additions: PHY check and PWM fallback, real engines on the route fake. Needs out/ufs_test/ufs_replay.h and gate.c from test_ufs_route.py.
A fake says nothing about hardware. Exit 0 only if all hold."""
import json, pathlib, re, shutil, subprocess, sys
S = pathlib.Path(__file__).resolve().parent; OUT = S/'out/ufs_test'; ROOT = next(p for p in S.parents if (p/'AGENTS.md').exists()); fails = []; checks = 0
CC = ['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-parameter']
GATES = ['-DTGL_UFS_POWER_MODE=1', '-DTGL_UFS_PHY_CHECK=1', '-DTGL_UFS_PWM_FALLBACK=1']
SRC = ('tgl_ufs_route_test.c', 'tgl_ufs_link.c', 'tgl_ufs_host.c', 'tgl_ufs_handoff.c')
IDS = dict(nonce='bdf582b45d69800af51a519354958306', epoch='0x202611012500')
def ok(c, what):
    global checks; checks += 1
    if not c: fails.append(what); print('FAIL', what)
def build(name, d=S):
    e = OUT/name
    p = subprocess.run(CC + GATES + [f'-I{OUT}', f'-I{d}'] + [str(d/x) for x in SRC] + ['-o', str(e)], capture_output=True, text=True)
    if p.returncode: return None, p.stderr[-1500:]
    return e, ''
def run(e, sc):
    p = subprocess.run([str(e), sc, str(OUT/f'{e.name}.{sc}.rec'), str(OUT/f'{e.name}.{sc}.link')], capture_output=True, text=True, timeout=120)
    return p, p.stdout
def field(o, key, line='R'):
    m = re.search(rf'^{line} .*\b{key}=(-?\w+)', o, re.M); return m.group(1) if m else None
def trace(o): return re.findall(r'^T (.*)$', o, re.M)
def rec(e, sc):
    d = subprocess.run([sys.executable, '-I', str(ROOT/'research/ufs-read-r2/decode_read.py'), str(OUT/f'{e.name}.{sc}.rec'), IDS['nonce'], IDS['epoch'], '--raw-record'], capture_output=True, text=True)
    return json.loads(d.stdout) if not d.returncode else None
FALLBACK = ['pmc_refused', 'pmc_no_upms', 'pmc_link_lost', 'pmc_upmcrs_bad', 'hs_crc']
def behaves(e):
    """What every mutant must break at least one of."""
    p, o = run(e, 'replay')
    if p.returncode or field(o, 'rc') != '0' or field(o, 'state', 'P') != '3' or field(o, 'reads') != '33' or field(o, 'relinks', 'B') != '0': return 'replay'
    t = trace(o)
    if 'MARK 4 1' not in t or t.index('MARK 4 1') > next(i for i, x in enumerate(t) if x.startswith('UIC 2 15d4')): return 'PMC mark not sealed before the first SET'
    r = rec(e, 'replay')
    if not r or not {0x406, 0x407, 0x408} <= {g['where'] for g in r['gates']}: return 'PHY notes'
    for sc in ('phy_init_clear', 'top_fault'):
        p, o = run(e, sc)
        if p.returncode or field(o, 'state', 'P') != '3': return 'PHY check must never refuse: ' + sc
    want_real = None
    for sc in FALLBACK:
        p, o = run(e, sc)
        if p.returncode or field(o, 'rc') != '0' or field(o, 'state', 'P') != '4' or field(o, 'outcome', 'F') != '1' or field(o, 'hs', 'P') != '0' or field(o, 'relinks', 'B') != '1': return 'fallback ' + sc
        ra = int(field(o, 'real_at'))
        if ra < 4: return 'fallback skipped the bring-up frames: ' + sc
    p, o = run(e, 'pmc_refused')
    if field(o, 'reads') != '33' or field(o, 'first', 'B') != '-27': return 'reads or first error'
    r = rec(e, 'pmc_refused')
    if not r or not any(g['where'] == 0x409 for g in r['gates']) or sum(x['step'] == 19 for x in r['reads']) != 12: return 'fallback record'
    if r['end']['dropped_entries'] != 0: return 'fallback record dropped entries'
    for sc in ('relink_fail', 'fb_crc'):
        p, o = run(e, sc)
        if p.returncode or field(o, 'state', 'P') != '2' or field(o, 'outcome', 'F') != '2' or field(o, 'rc') not in ('-27', '-28'): return 'failed fallback must stay DOWN: ' + sc
    p, o = run(e, 'hs_timeout')
    if p.returncode or field(o, 'relinks', 'B') != '0' or field(o, 'outcome', 'F') != '-1': return 'READ hang: no reset under possible DMA'
    r = rec(e, 'hs_timeout')
    if r and any(g['where'] == 0x409 for g in r['gates']): return 'READ hang: the fallback must not even start'
    p, o = run(e, 'peer_get_fail')
    if p.returncode or field(o, 'state', 'P') != '1' or field(o, 'rc') != '0' or field(o, 'outcome', 'F') != '1' or field(o, 'relinks', 'B') != '0': return 'failed read before any SET stays at PWM, live'
    for sc in ('gear3', 'one_lane'):
        p, o = run(e, sc)
        if p.returncode or field(o, 'state', 'P') != '1' or field(o, 'relinks', 'B') != '0' or field(o, 'outcome', 'F') != '1': return sc
    return None
e, err = build('all')
if not e: sys.exit('build: ' + err)
why = behaves(e); ok(why is None, f'behaviour: {why}')
_, o = run(e, 'replay'); t = trace(o)
off, err = build('all')
# Everything before the change is the trace the phone ran, gate for gate, with marks and the check's reads taken out.
base = S/'out/ufs_test/on'
if base.exists():
    _, ob = run(base, 'replay'); tb = trace(ob)
    strip = lambda x: [y for y in x if not y.startswith(('MARK', 'TOPRD')) and not re.match(r'UIC 1 (8101|8115|8019|8013) ', y)]
    ok(strip(t) == tb, f'HS boot: the trace ufs-speed-r1 ran on the phone, plus marks and reads only ({len(strip(t))} vs {len(tb)})')
FORBID_SET = {0x8101, 0x8115, 0x8019, 0x8013, 0x8016, 0x810e, 0x810f, 0x8110, 0x8111, 0x8114, 0xd0c1}
ok(not [x for x in t if x.startswith(('UIC 2 ', 'UIC 4 ')) and int(x.split()[2], 16) in FORBID_SET], 'no PHY attribute is ever SET')
_, o2 = run(e, 'pmc_refused'); t2 = trace(o2)
ok(not [x for x in t2 if x.startswith(('UIC 2 ', 'UIC 4 ')) and int(x.split()[2], 16) in FORBID_SET], 'fallback: no PHY attribute is ever SET')
ok(sum(x.startswith('SMC') for x in t2) == 2, 'fallback: no second clock vote')
# Wire gate on the same bound source, gates on.
g = (OUT/'gate.c').read_text().replace('i < 40;', 'i < 60;'); (OUT/'gate_all.c').write_text(g)
q = subprocess.run(['cc', '-std=gnu11', '-O1', '-w'] + GATES + [f'-I{S}', str(OUT/'gate_all.c'), '-o', str(OUT/'gate_all')], capture_output=True, text=True); ok(q.returncode == 0, 'gate build ' + q.stderr[-300:])
g2 = subprocess.run([str(OUT/'gate_all')], capture_output=True, text=True); ok(g2.returncode == 0, 'wire gate, bound 56: ' + g2.stdout[-300:]); print(g2.stdout.strip())
src = (S/'tgl_ufs_host.c').read_text()
ok(not re.search(r'define (SCSI|OP)_(WRITE|UNMAP|SYNC)', src), 'no storage write opcode defined')
M = {'no reset low': ('tgl_ufs_link.c', 'rc = apply_pad(1u << 0, PARAM_DRV_MASK | PARAM_IE, 1u | PARAM_IE, TX_PUPD_MASK | TX_OE | TX_DOUT, TX_OE, PAD_RESET);\n    if (!rc && tgl_ufs_port_delay', 'rc = 0;\n    if (!rc && tgl_ufs_port_delay'),
     'verify not compared': ('tgl_ufs_host.c', 'if (crc != s->target_crc[i]) { r = TGL_UFSH_E_HS_CRC; goto out; }', ''),
     'fallback under possible DMA': ('tgl_ufs_host.c', 'if (rc && o->pmc_state == 2 && !s->inflight && !o->quarantined) rc = pwm_fallback(s, rc);', 'if (rc && o->pmc_state == 2) rc = pwm_fallback(s, rc);'),
     'state not set': ('tgl_ufs_host.c', 'o->pmc_state = 4;', ''),
     'lists not stopped': ('tgl_ufs_host.c', 'if ((r = stop_lists(s))) { o->quarantined = 1; goto out; }', ''),
     'lists not installed': ('tgl_ufs_host.c', 'if ((r = install_lists(s))) goto out;', ''),
     'no fDeviceInit': ('tgl_ufs_host.c', '(r = nop(s)) || (r = device_init(s))', '(r = nop(s))'),
     'no NOP': ('tgl_ufs_host.c', '(r = smmu_gate(s, 0x600u)) || (r = nop(s)) ||', '(r = smmu_gate(s, 0x600u)) ||'),
     'failure reported as success': ('tgl_ufs_host.c', 'return r ? why : 0;', 'return 0;'),
     'no check reads': ('tgl_ufs_host.c', '    phy_check(s);\n', ''),
     'PMC mark gone': ('tgl_ufs_host.c', 'mark(s, TGL_UFSH_MARK_PMC, 1, 0);', ''),
     'no fail note': ('tgl_ufs_host.c', 'pmc_note(s, TGL_UFSH_PMC_WHERE_FAIL, (uint32_t)why, uec[0], uec[1], is, hcs);', ''),
     'no read at PWM': ('tgl_ufs_host.c', 'for (uint32_t i = 0; i < s->target_n; i++, n++) {', 'for (uint32_t i = 0; i < 0u; i++, n++) {'),
     'failed GET ends the UFS route': ('tgl_ufs_host.c', 'if (rc == TGL_UFSH_E_UIC && o->pmc_state == 0 && o->phase == TGL_UFSH_P_PMC && !s->inflight) { o->pmc_state = 1; pmc_note(s, TGL_UFSH_PMC_WHERE_SKIP, 3, 0, 0, 0, 0); rc = 0; }', '')}
Ms = OUT/'mut_all'; caught = 0
for name, (f, a, b) in M.items():
    t_ = (S/f).read_text()
    if t_.count(a) != 1: sys.exit(f'mutant {name}: {t_.count(a)} matches')
    shutil.rmtree(Ms, ignore_errors=True); Ms.mkdir()
    for x in SRC + ('tgl_ufs_link.h', 'tgl_ufs_host.h', 'tgl_ufs_handoff.h'): shutil.copy2(S/x, Ms/x)
    (Ms/f).write_text(t_.replace(a, b))
    m, err = build('m', Ms)
    if not m: fails.append('mutant build ' + name + err[-200:]); continue
    try: w = behaves(m)
    except Exception as ex: w = repr(ex)[:80]
    if w is None: fails.append('mutant survived: ' + name); print('survived', name)
    else: caught += 1
print(f'all-stage mutants {caught}/{len(M)} caught')
ok(caught == len(M), 'all mutants caught')
print(f'all-stage host test: {checks} checks, {len(fails)} failed')
if fails: print('\n'.join(fails)); sys.exit(1)
