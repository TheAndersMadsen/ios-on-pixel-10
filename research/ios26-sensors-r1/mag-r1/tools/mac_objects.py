#!/usr/bin/env python3
"""Compile patch 0930's files with the release build's exact per-object commands (build/obj/.../*.o.json), on the Mac,
without touching the release tree: sources are copies under OUT, objects are written under OUT.

    mac_objects.py RELEASE_WORK OUT PATCHED_DIR
RELEASE_WORK: research/ios26-release-r1/work (holds xnu/ and build/obj/). PATCHED_DIR: holds the patched files at their xnu paths.
Prints each object's sha256 and its defined/undefined symbols of interest."""
import hashlib, json, os, shutil, subprocess, sys
W, OUT, P = (os.path.abspath(a) for a in sys.argv[1:4])
X, O = f'{W}/xnu', f'{W}/build/obj/DEVELOPMENT_ARM64_BLAZER'
JOBS = [  # (patched source, json of the object the build made for it, or of a sibling in the same directory)
    ('bsd/dev/blazer_sensors.c', 'bsd/DEVELOPMENT/blazer_sensors.o.json'),
    ('bsd/dev/blazer_sensor_hw.c', 'bsd/DEVELOPMENT/blazer_sensor_hw.o.json'),
    ('bsd/dev/blazer_mag_hw.c', 'bsd/DEVELOPMENT/blazer_sensor_hw.o.json'),
    ('iokit/Kernel/arm/hid/SweetHID.cpp', 'iokit/DEVELOPMENT/SweetHID.cpo.json'),
    ('iokit/KernelConfigTables.cpp', 'iokit/DEVELOPMENT/KernelConfigTables.cpo.json'),
]
KEYS = ('mag_', 'sns_bus', 'compass', 'Compass', 'sweet_hid_', 'blazer_sensors_init', 'sns_run', 'SweetHIDAccel5start', 'delay_for_interval', 'PE_parse_boot_argn')
os.makedirs(OUT, exist_ok=True)
for d in ('bsd/dev', 'iokit/Kernel/arm', 'osfmk/arm64'):   # SweetHID.cpp includes ../../../../osfmk/arm64/hk_live_input.h     # whole directories, so "" includes next to each source resolve to copies
    shutil.copytree(f'{X}/{d}', f'{OUT}/src/{d}', dirs_exist_ok=True)
os.makedirs(f'{OUT}/src/iokit', exist_ok=True)
for rel, _ in JOBS:
    shutil.copy(f'{P}/{rel}', f'{OUT}/src/{rel}')
for h in ('blazer_mag_hw.h', 'blazer_sensor_hw.h'):
    shutil.copy(f'{P}/bsd/dev/{h}', f'{OUT}/src/bsd/dev/{h}')
ok = True
for rel, js in JOBS:
    j = json.loads(open(f'{O}/{js}').read().strip().rstrip(','))   # compile_commands fragments end with ","
    args = list(j['arguments'])
    src = f'{OUT}/src/{rel}'
    obj = f'{OUT}/obj/{os.path.basename(rel).rsplit(".", 1)[0]}.o'
    os.makedirs(os.path.dirname(obj), exist_ok=True)
    args[args.index(j['file'])] = src
    args[args.index('-o') + 1] = obj
    drop_next = False
    clean = []
    for a in args:
        if drop_next:
            drop_next = False
            continue
        if a in ('-MF', '-MT', '-MQ'):
            drop_next = True
            continue
        if a in ('-MD', '-MMD') or a.startswith('-MF') or a.startswith('-MT'):
            continue
        clean.append(a)
    r = subprocess.run(clean, cwd=j['directory'], capture_output=True, text=True)
    if r.returncode:
        ok = False
        print(f'FAIL {rel}\n{r.stderr[-3000:]}')
        continue
    h = hashlib.sha256(open(obj, 'rb').read()).hexdigest()
    nm = subprocess.run(['nm', '-m', obj], capture_output=True, text=True).stdout.splitlines()
    print(f'OK {rel} -> {obj} sha256 {h}')
    for line in nm:
        if any(k in line for k in KEYS):
            print('   ', line.strip())
    strs = subprocess.run(['strings', '-a', obj], capture_output=True, text=True).stdout.splitlines()
    print('    strings:', [s for s in strs if 'compass' in s.lower() or 'blazer_sensors_mag' in s][:10])
sys.exit(0 if ok else 1)
