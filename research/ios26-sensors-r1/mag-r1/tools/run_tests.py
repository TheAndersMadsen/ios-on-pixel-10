#!/usr/bin/env python3
"""Host tests and mutants for patch 0930 (compass). usage: run_tests.py PATCHED_XNU_DIR [SCRATCH]
PATCHED_XNU_DIR: an XNU tree (or a copy of its bsd/dev) with 0930 applied. Builds with ASan+UBSan:
  host_mag.c  (register-level, blazer_mag_hw.c alone)
  bench.c     (the existing sensor bench, unchanged, as a regression on the patched blazer_sensor_hw.c)
  bench_mag.c (bit-level: patched blazer_sensor_hw.c + blazer_mag_hw.c on pads 67, 68)
then applies each mutant to a copy and requires at least one of the three to fail."""
import os, shutil, subprocess, sys, tempfile
X = os.path.abspath(sys.argv[1]); D = X + '/bsd/dev' if os.path.isdir(X + '/bsd/dev') else X
T = os.path.dirname(os.path.abspath(__file__)) + '/../tests'; R = os.path.abspath(T + '/../../tests')
CC = ['clang', '-std=gnu11', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-include', 'stddef.h', '-Wno-format', '-Wno-macro-redefined']
FILES = ('blazer_sensor_hw.c', 'blazer_sensor_hw.h', 'blazer_mag_hw.c', 'blazer_mag_hw.h', 'blazer_hw_port.h', 'blazer_cpmq.h', 'blazer_cpmq.c')
MUT = [
 ('blazer_mag_hw.c', 'if (id != MAG_PRODUCT_ID) {', 'if (0) {', 'id unchecked'),
 ('blazer_mag_hw.c', 'const int32_t a[3] = { -c[1], -c[0], -c[2] };', 'const int32_t a[3] = { c[1], -c[0], -c[2] };', 'x sign'),
 ('blazer_mag_hw.c', 'const int32_t a[3] = { -c[1], -c[0], -c[2] };', 'const int32_t a[3] = { -c[0], -c[1], -c[2] };', 'axes not swapped'),
 ('blazer_mag_hw.c', '* 3125 / 512', '* 3125 / 500', 'units'),
 ('blazer_mag_hw.c', '(uint32_t)b[6 + i] >> 4', '((uint32_t)b[6 + i] & 0xf)', 'low nibble'),
 ('blazer_mag_hw.c', '(uint32_t)b[2 * i + 1] << 4', '(uint32_t)b[2 * i + 1] << 3', 'middle byte'),
 ('blazer_mag_hw.c', 'if (m->same_run >= MAG_STUCK_SAMPLES) {', 'if (0) {', 'stuck ignored'),
 ('blazer_mag_hw.c', 'if (flat) {', 'if (0) {', 'flat ignored'),
 ('blazer_mag_hw.c', 'if (!m->started || !m->pending) {', 'if (0) {', 'unstarted read'),
 ('blazer_mag_hw.c', 'm->bus.sleep_us(m->bus.ctx, MAG_SR_GAP_US);', ';', 'no tSR gap'),
 ('blazer_mag_hw.c', 'if (m->bus.write(m->bus.ctx, MAG_REG_CTRL0, MAG_CTRL0_DO_SET)) {', 'if (0) {', 'no SET'),
 ('blazer_mag_hw.h', '#define MAG_MEASURE             (MAG_CTRL0_AUTO_SR | MAG_CTRL0_TM_M)', '#define MAG_MEASURE             (MAG_CTRL0_TM_M)', 'no auto SR'),
 ('blazer_mag_hw.c', '	m->pending = true;\n	mag_decode(b, c);', '	mag_decode(b, c);', 'no next measure flag'),
 ('blazer_sensor_hw.c', '(value == MAG_W_SET || value == MAG_W_MEASURE)', '(value != 0)', 'write allowlist widened'),
 ('blazer_sensor_hw.c', '(reg == MAG_R_OUT && len == 9)', '(reg == MAG_R_OUT)', 'read length widened'),
 ('blazer_sensor_hw.c', '((reg == MAG_R_ID || reg == MAG_R_STATUS1) && len == 1)', '(len == 1)', 'read register widened'),
 ('blazer_sensor_hw.c', 'return addr == MAG_I2C_ADDR && s->bus_ready && (', 'return (addr == MAG_I2C_ADDR || addr == IMU_ADDR) && s->bus_ready && (', 'imu reachable in mag mode'),
 ('blazer_sensor_hw.c', 'return addr == MAG_I2C_ADDR && s->bus_ready && reg == MAG_R_CTRL0', 'return s->bus_ready && reg == MAG_R_CTRL0', 'write any address'),
 ('blazer_sensor_hw.c', '	s->accel_on = false;\n	s->bus_ready = false;', '	s->accel_on = false;', 'bus stays ready after down'),
 ('blazer_sensor_hw.c', '	} else if (mode == SNS_MODE_STREAM_MAG) {\n		s->pad_scl = PAD_I3C0_SCL;\n		s->pad_sda = PAD_I3C0_SDA;\n', '	} else if (mode == SNS_MODE_STREAM_MAG) {\n', 'mag on the imu pads'),
 ('blazer_sensor_hw.c', '	if (s->mode == SNS_MODE_STREAM_MAG) {\n		/* The part', '	if (0) {\n		/* The part', 'mag mode falls to the imu path'),
 ('blazer_sensor_hw.c', 'if (s->mode == SNS_MODE_STREAM) {\n		return addr == IMU_ADDR', 'if (s->mode >= SNS_MODE_STREAM) {\n		return addr == IMU_ADDR', 'imu writes in mag mode'),
]
def build(d):
    outs = []
    for name, srcs in (('host_mag', [f'{T}/host_mag.c']), ('bench', [f'{R}/bench.c', f'{R}/cpmq_tu.c']), ('bench_mag', [f'{T}/bench_mag.c', f'{R}/cpmq_tu.c'])):
        r = subprocess.run(CC + ['-I', d, '-o', f'{d}/{name}'] + srcs, capture_output=True, text=True)
        if r.returncode:
            return None, f'{name}: compile failed\n{r.stderr[-2000:]}'
        outs.append(name)
    return outs, ''
def run(d, outs):
    res = []
    for o in outs:
        r = subprocess.run([f'{d}/{o}'], capture_output=True, text=True, timeout=120)
        res.append((o, r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1:] or ['']))
    return res
def prep(base):
    d = tempfile.mkdtemp(dir=base)
    for f in FILES:
        shutil.copy(f'{D}/{f}', d)
    return d
base = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp()
os.makedirs(base, exist_ok=True)
d = prep(base); outs, err = build(d)
if not outs:
    sys.exit(err)
res = run(d, outs)
for o, rc, last in res:
    print(f'{o}: rc {rc}: {last[0]}')
if any(rc for _, rc, _ in res):
    sys.exit('baseline FAILED')
caught = 0
for f, a, b, why in MUT:
    d = prep(base); p = f'{d}/{f}'; t = open(p).read()
    assert t.count(a) == 1, (why, t.count(a))
    open(p, 'w').write(t.replace(a, b))
    outs, err = build(d)
    ok = outs is None or any(rc for _, rc, _ in run(d, outs))
    caught += ok
    print(f'mutant {why}: {"caught" if ok else "SURVIVED"}')
print(f'mutants {caught}/{len(MUT)} caught')
sys.exit(0 if caught == len(MUT) else 1)
