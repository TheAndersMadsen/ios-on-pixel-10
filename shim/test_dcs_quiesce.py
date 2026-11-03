#!/usr/bin/env python3
"""Host test of the chooser display release, gate TGL_DCS_QUIESCE off and on (chooser-v1-r10).
Checks: every literal in dpu_quiesce.h against the stock vs_drm.ko listing when it is present, the release order and
values on a fake bus, and that the gate off keeps r9's release (no DPU access before the first power-off).
A fake says nothing about hardware. Exit 0 only if all hold."""
import hashlib, pathlib, re, subprocess, sys
S = pathlib.Path(__file__).resolve().parent
ROOT = next(p for p in S.parents if (p / 'AGENTS.md').exists())
OUT = S / 'out/dcs_quiesce_test'
LISTING = ROOT / 'research/ios26-dualboot-r8/display-handback/vs_drm.stock.dis'
MODULE = ROOT / 'research/ios26-dualboot-r8/display-handback/vs_drm.ko.stock'
MODULE_SHA = '92e482bead3a12611f8fd890b8e60727d6875a973b79a1a71239268da110cf40'
CC = ['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=undefined', '-Wall', '-Wextra', '-Werror',
      '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-unused-but-set-variable', '-DTGL_DCS_HOSTTEST', '-DTGL_TAKEOVER_NO_BARRIER',
      '-DTGL_TAKEOVER_BASE=({ extern volatile uint32_t dcs_test_takeover[]; dcs_test_takeover; })',
      '-DTGL_FRAME_RUNG=3', '-DTGL_DCS_MENU=1']
SCEN = ['ok', 'layer_off', 'layer_settles', 'layer_busy', 'be_settles', 'be_busy', 'no_fe0']
fails, checks = [], 0


def ok(c, what):
    global checks
    checks += 1
    if not c:
        fails.append(what)
        print('FAIL', what)


def listing_has(addr, pattern):
    """The instruction at ADDR in the stock listing matches PATTERN."""
    for line in LISTING.read_text(errors='replace').splitlines():
        m = re.match(r'^\s*([0-9a-f]+):\s+(.*)$', line)
        if m and int(m.group(1), 16) == addr:
            return re.search(pattern, m.group(2)) is not None
    return False


# ---- literals against the phone's module (skipped with a note when research/ is absent)
if LISTING.exists() and MODULE.exists():
    ok(hashlib.sha256(MODULE.read_bytes()).hexdigest() == MODULE_SHA, 'vs_drm.ko.stock is the phone module')
    for addr, pat, what in [
        (0x30e80, r'mov\s+w8, #0x6', 'iso: bits 1|2'), (0x30e88, r'mov\s+w10, #0x8', 'iso: bit 3'),
        (0x30e90, r'mov\s+w1, #0x248', 'iso: low half of 0x80248'), (0x30e9c, r'movk\s+w1, #0x8, lsl #16', 'iso: high half'),
        (0x37324, r'ldr\s+x8, \[x0, #0x28\]', 'be idle: gpcsr base at dc_hw+0x28'),
        (0x37358, r'mov\s+w9, #0x107c', 'be idle: ctl offset'), (0x3735c, r'mov\s+w0, #0x2', 'be idle: ctl low'),
        (0x37360, r'movk\s+w0, #0x100, lsl #16', 'be idle: ctl high'), (0x37374, r'mov\s+w9, #0x1084', 'be idle: status offset'),
        (0x37384, r'tbz\s+w0, #0xe', 'be idle: busy bit 14'), (0x37388, r'mov\s+w8, #0xe100', 'be idle: timeout low'),
        (0x37390, r'movk\s+w8, #0x5f5, lsl #16', 'be idle: timeout 100 ms'), (0x373a8, r'mov\s+w1, #0x64', 'be idle: sleep 100 us'),
        (0x32c70, r'mov\s+w1, #0x80008', 'be status addr'), (0x32c74, r'mov\s+w2, #-0xe001', 'be status 0xffff1fff'),
        (0x32c84, r'mov\s+w2, #0xff3f', 'be status1 low'), (0x32c90, r'movk\s+w2, #0xfff1, lsl #16', 'be status1 high'),
        (0x35878, r'mov\s+w1, #0x8a54', 'layer0 dma st low'), (0x35884, r'movk\s+w1, #0x1, lsl #16', 'layer0 dma st 0x18a54'),
        (0x358dc, r'add\s+w1, w23, #0x4', 'layer0 coord = st + 4'), (0x358ec, r'and\s+w8, w22, #0x1f', 'idle mask 0x1f'),
        (0x358fc, r'cmp\s+w8, #0x18', 'idle value 0x18'),
    ]:
        ok(listing_has(addr, pat), f'stock listing {addr:#x}: {what}')
    tr = subprocess.run([sys.executable, '-I', str(LISTING.parent / 'trace_calls.py'), str(LISTING), 'dc_hw_disable_all_be_interrupts', 'dc_hw_reset_all_be_interrupts'], capture_output=True, text=True).stdout
    for a1, a2 in [('0x80004', '0x0'), ('0x80018', '0x0'), ('0xb60b4', '0x0'), ('0xb6178', '0x0'), ('0x8001c', '0xfff1ff3f'), ('0x80028', '0xfff1ff3f')]:
        ok(re.search(rf'dc_write\s+a0=\S+ a1={a1} a2={a2}\b', tr) is not None, f'stock dc_write({a1}, {a2})')
    ok(re.search(r'dc_write\s+a0=\S+ a1=0x80014 a2=-0xe001', tr) is not None, 'stock dc_write(0x80014, 0xffff1fff)')
else:
    print('note: stock listing absent; literal checks skipped (research/ is local)')

# ---- the header says what the tests check
H = (S / 'dpu_quiesce.h').read_text()
for name, val in [('Q_GPCSR', 'UINT64_C(0x0ef90000)'), ('Q_BE_DBG_CTL', '0x107cu'), ('Q_BE_DBG_CTL_VAL', '0x01000002u'), ('Q_BE_DBG_STATUS', '0x1084u'),
                  ('Q_L0_DMA_ST', '0x018a54u'), ('Q_L0_DMA_COORD', '0x018a58u'), ('Q_OUTPUT0_START', '0x0b6000u'), ('Q_CLOCK_DOMAIN_ISOLATION', '0x080248u'),
                  ('Q_ISO_ALL', '0xfu'), ('Q_BE_W0_MASK', '0xffff1fffu'), ('Q_BE_W1_MASK', '0xfff1ff3fu')]:
    ok(re.search(rf'#define {name}\s+{re.escape(val)}', H) is not None, f'dpu_quiesce.h {name} = {val}')
fdt = ROOT / 'research/ios26-dualboot-r8/truth/fdt.dts'
if fdt.exists():
    t = fdt.read_text(errors='replace')
    ok('ranges = <0x00 0x00 0xec00000 0x400000>;' in t and 'reg = <0x200000 0x120000 0x390000 0x10000>;' in t and 'reg-names = "dpu-fe-be", "dpu-gpcsr";' in t,
       'FDT: dpu-fe-be 0x0ee00000, dpu-gpcsr 0x0ef90000')

# ---- every LPCM frame the shim sends, rebuilt from the vendor's FIELD_PREP masks (send_lpcm_mail)
PC = ROOT / 'research/ios26-webscout-r1/dl-gos-6.12/repo/private/google-modules/soc/rdo/power-controller/power_controller_main.c'
if PC.exists():
    pc = PC.read_text()
    def mask(name):
        m = re.search(rf'#define {name} GENMASK\((\d+), (\d+)\)', pc); return int(m[2])
    sh = {k: mask(k) for k in ('POWER_ON_BITFIELD', 'PD_ID_BITFIELD', 'SSWRP_ID_BITFIELD', 'REQ_ID_BITFIELD')}
    req = int(re.search(r'#define LPCM_CMD_SET_GEN_PD (\d+)', pc)[1])
    frame = lambda pd, on, sswrp=0: req << sh['REQ_ID_BITFIELD'] | sswrp << sh['SSWRP_ID_BITFIELD'] | pd << sh['PD_ID_BITFIELD'] | on << sh['POWER_ON_BITFIELD']
    C2 = (S / 'tgl_dcs.c').read_text()
    val = lambda n: int(re.search(rf'#define {n} (0x[0-9a-f]+)u', C2)[1], 16)
    for name, want in (('LPCM_FE0_ON', frame(0, 1)), ('LPCM_DSI0_ON', frame(2, 1)), ('LPCM_FE0_OFF', frame(0, 0)), ('LPCM_DSI0_OFF', frame(2, 0))):
        ok(val(name) == want, f'{name} = {val(name):#010x}, vendor fields give {want:#010x}')
else:
    print('note: vendor power_controller_main.c absent; LPCM field check skipped')

# ---- fake bus, gate off and on
OUT.mkdir(parents=True, exist_ok=True)
for gate in (False, True):
    exe = OUT / ('on' if gate else 'off')
    p = subprocess.run(CC + (['-DTGL_DCS_QUIESCE=1'] if gate else []) + [f'-I{S}', str(S / 'tgl_dcs_quiesce_test.c'), '-o', str(exe)], capture_output=True, text=True)
    ok(p.returncode == 0, f'build gate={gate}: {p.stderr[-800:]}')
    if p.returncode:
        continue
    for s in SCEN:
        r = subprocess.run([str(exe), s], capture_output=True, text=True, timeout=60)
        print(f'gate={"on " if gate else "off"} {r.stdout.strip()}')
        ok(r.returncode == 0, f'gate={gate} {s}: {r.stdout[-400:]}{r.stderr[-400:]}')

print(f'{checks} checks, {len(fails)} failed')
sys.exit(1 if fails else 0)
