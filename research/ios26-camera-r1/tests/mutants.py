#!/usr/bin/env python3
"""Mutants of blazer_torch_hw.c (hk-cam1): each must make tests/test_blazer_torch.c fail. HOST ONLY.
    python3 -I tests/mutants.py WORKDIR      (from research/ios26-camera-r1)"""
import os, subprocess, sys
SRC = 'xnu-src/bsd/dev/blazer_torch_hw.c'
M = [
    ('torch code full scale', '#define TORCH_CODE      0x08u', '#define TORCH_CODE      0x7fu'),
    ('both LEDs allowed', 'val == (ENABLE_RESET | EN_MODE_TORCH | EN_LED2);', 'val == (ENABLE_RESET | EN_MODE_TORCH | EN_LED2) || val == 0x8b;'),
    ('flash mode allowed', 'return val == ENABLE_RESET ||', 'return val == 0x8d || val == ENABLE_RESET ||'),
    ('no standby in put_back', '(void)chip_write(t, R_ENABLE, ENABLE_RESET);\n\t\tcleanup_result', 'cleanup_result'),
    ('no standby after hold', 'if (read_flags(t, &f1, &f2) || chip_write(t, R_ENABLE, ENABLE_RESET)) {', 'if (read_flags(t, &f1, &f2)) {'),
    ('EN restore skipped', 'if (t->en_moved) {', 'if (0) {'),  # the drive-low-then-release order itself is not observable in the model
    ('cli word 0 not restored', 'if (wr(t, CLI_CONF, t->cli[0]) == 0 &&', 'if (0 &&'),
    ('pads not restored', 'if (wr(t, pads[i], want) == 0 &&', 'if (0 &&'),
    ('no id check', 'if (t->device_id != ID_LM3644 && t->device_id != ID_LM3644TT) {', 'if (0) {'),
    ('no enable-reset check', 'if (t->enable_reg != ENABLE_RESET) {\n\t\treturn halt(t, BT_STOP_NOT_STANDBY', 'if (0) {\n\t\treturn halt(t, BT_STOP_NOT_STANDBY'),
    ('no disarm', '\t\tt->armed_reg = t->armed_val = ARM_NONE;         /* one value per arming */\n', ''),
    ('stage 3 arms', 'if (t->cfg.stage < BT_STAGE_TORCH ||', 'if (t->cfg.stage < BT_STAGE_SELECT ||'),
    ('select in stage 2', 't->cli[0] == CLI_IPTYPE_UART && t->cfg.stage >= BT_STAGE_SELECT', 't->cli[0] == CLI_IPTYPE_UART && t->cfg.stage >= BT_STAGE_ID'),
    ('fault flags ignored', 'if ((f1 & F1_FAULTS) || (f2 & F2_FAULTS)) {', 'if (0) {'),
    ('unknown pad muxed', 'if (was != DMUX_GPIO && was != 0) {', 'if (0) {'),
    ('hold unbounded clamp', 't->cfg.torch_ms = torch_ms >= BT_TORCH_MS_MIN && torch_ms <= BT_TORCH_MS_MAX ? torch_ms : BT_TORCH_MS_DEFAULT;', 't->cfg.torch_ms = torch_ms ? torch_ms : BT_TORCH_MS_DEFAULT;'),
]
work = sys.argv[1]
base = open(SRC).read()
caught = 0
for name, a, b in M:
    if base.count(a) != 1:
        print(f'BAD MUTANT {name}: anchor count {base.count(a)}'); sys.exit(2)
    d = f'{work}/m'; os.makedirs(f'{d}/xnu-src/bsd/dev', exist_ok=True); os.makedirs(f'{d}/tests', exist_ok=True)
    open(f'{d}/{SRC}', 'w').write(base.replace(a, b))
    for f in ('blazer_torch_hw.h', 'blazer_hw_port.h'):
        open(f'{d}/xnu-src/bsd/dev/{f}', 'w').write(open(f'xnu-src/bsd/dev/{f}').read())
    open(f'{d}/tests/t.c', 'w').write(open('tests/test_blazer_torch.c').read())
    r = subprocess.run(['cc', '-std=c11', '-w', '-DBLAZER_TORCH_HOST_TEST', f'-I{d}/xnu-src/bsd/dev', f'{d}/tests/t.c', '-o', f'{d}/t'], capture_output=True, text=True)
    if r.returncode:
        print(f'BUILD FAIL {name}: {r.stderr[:300]}'); sys.exit(2)
    r = subprocess.run([f'{d}/t'], capture_output=True, text=True, timeout=60)
    hit = r.returncode != 0
    caught += hit
    print(('caught ' if hit else 'MISSED ') + name + ('' if not hit else '  (' + ', '.join(l.split()[1] for l in r.stdout.splitlines() if l.startswith('FAIL')) + ')'))
print(f'mutants {caught}/{len(M)} caught')
sys.exit(caught != len(M))
