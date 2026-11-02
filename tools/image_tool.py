#!/usr/bin/env python3
"""One command from a kernel Mach-O to a fastboot-bootable image for iOS 26. HOST ONLY: no device access, no storage writes.

  image_tool.py image NAME --kernel K --kernel-sha SHA256 [--route ufs|md] [--md0 F --md1 F] [--cpus N] [--dpu]
                [--canvas WxH] [--gamut sRGB] [--args "..."] [--test-kernel]
  image_tool.py check research/images/NAME      re-verify a finished image against its manifest

Output: research/images/NAME/{boot.img,payload-usb.bin,laguna.adt,manifest.json,SHA256SUMS,avb-verify.txt,build.log,shim.elf}.
A run directory is never overwritten: an image is not rebuilt after handover. Every build has fresh nonces and a fresh random-seed.
--test-kernel: layout tests with a kernel that must not boot on the phone. Names the image test-*, and the manifest says bootable=false."""
import argparse, array, hashlib, json, os, re, shutil, struct, subprocess, sys, time
from pathlib import Path
sys.dont_write_bytecode = True
X = Path(__file__).resolve().parent; ROOT = X.parent; R = ROOT/'research'; SHIM = ROOT/'shim'
RUN = R/'images'; WORK = RUN/'.work'  # images and scratch stay under research/, which git ignores
sys.path[:0] = [str(X)]
import adt as ADT, mkadt, mkpayload
LLVM = Path('/opt/homebrew/opt/llvm/bin')
AVBTOOL = (R/'native-20261024/reuse/felix-working-source/baremetal_loader/avbtool.py', 'e5a664a38db623da00f080219bc0ee60a640a9dc4a872803616fae4938ac749b')
AVBKEY = (R/'laguna-usb-fix/keys/test-rsa4096.pem', '4ef896cb9405b22449ecfa41d155a556ba7c049c26892f4dee4544e4c2a24440')
SALT = '666bb996ba0b27623969515f883297de04eaad27d148950c5f24ce0e47c1cc54'; ROLLBACK = 1791158400
PARTITION = 67108864; FOOTER_ROOM = 1 << 20
PHYS, SIZE = 0xa00000000, 0x100000000; FB = 0xf0000000
# Boot arguments. tegu's userland set from scripts/build-boot-image.sh; ours from ui-integrate-r1. blazer_* names are provisional until kernel-blazer.
USER = 'unentitled_ios_sim_launch=1 ignition_level=1 launchd_unsecure_cache=1 sweetarm64e=1 launchd_disable_all_timeouts=1 autounlock=0 sweetfb_noconsole=1 kern.jetsam_critical_threshold=1'
UFS = 'lagunapanicdump=2 blazer_psci_reset=1 msgbuf=1048576 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=userdata_exp.ai blazer_ufs_lun=0 blazer_ufs_deadline=1500'
SHIM_FLAGS = '-DTGL_UFS_POWER_MODE=1 -DTGL_UFS_PHY_CHECK=1 -DTGL_ALL_STAGES=1 -DTGL_UFS_PWM_FALLBACK=1 -DTGL_UFS_WDT_GUARD=1'
DPU_FLAGS = '-DTGL_ALL_DCS=1 -DTGL_FRAME_RUNG=3 -DTGL_DCS_HANDOFF=1 -DTGL_DCS_BRIGHT=1'
# Tensor G4 addresses tegu's start.s and early marks write with the MMU off. Writing them here hits unknown RAM on this phone.
PHONE_ROOT_SHA = '205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7'  # ios26-phone-r3, must be staged in userdata_exp.ai
# One by one, with source: PHONE-ROOT.md. Debug-off settings are out: a phone boot that needs one adds it, a one-boot change.
QEMU_RUN_DIRS = ('ios26-qemu-r1', 'ios26-blazer-r1', 'ios26-native-r1', 'ios26-overlay-r1')  # folders holding runs/<name>
PHONE_ROUTES = {'ufsroot': 'rd=ufsroot0', 'md0-mountroot': 'rd=md0 blazer_ufs_mountroot=1'}  # handoffs/kernel-ios26.md decides; md0-mountroot needs blazer's c2
PHONE_ARGS = ('debug=0x8 serial=3 cpus=1 ROUTE msgbuf=1048576 varfs=1 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=userdata_exp.ai blazer_ufs_lun=0 blazer_deadline=1800 '
              'launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 launchd_disable_all_timeouts=1 sweetarm64e=1 autounlock=0 '
              'interrupt-masked-debug-mode=0 blazer_panic=1 hk_usertrace=1 hk_fb_scanout=1 hk_fb_probe=1 sweetfb_noconsole=1 sweetfb_hz=60')  # masked-mode off: parent's decision 23:36, PHONE-ROOT.md
TOUCH_ARG = 'blazer_touch=1'
BOOTCPUS = ('0x200', '0x300', '0x500')  # ios26-fastcore-r1: the A725s speed-probe-r3 ran. Shim and mkadt refuse any other. --cpus up to 5 adds the other A725s
FC_FLAGS, FC_SRC = '-DTGL_FASTCORE=1', 'tgl_fastcore.c tgl_fastcore_s.S'
# handoffs/smp.md. Cores for cpus=N, logical order. cpu7 is refused: X4 REVIDR 0x3, 3076789 not fixed, until its control bits are read (parent's rule).
CPU_ORDER_MAX_CORE = 6
def cpu_order(text):
    try: o = [int(x, 10) for x in text.split(',')]
    except ValueError: die(f'--cpu-order {text}: core numbers, comma separated')
    if len(o) < 2 or len(set(o)) != len(o) or 0 not in o or not all(0 <= c <= CPU_ORDER_MAX_CORE for c in o): die(f'--cpu-order {text}: 2 or more of cores 0-{CPU_ORDER_MAX_CORE}, once each, with the boot core 0')
    return o
FC_DEADLINE = 'blazer_deadline=900'
# The only tokens the phone line can gain. Whole token must match. Add exact args from kconfig.md, overlay.md to PHONE_EXACT when the parent names them.
PHONE_ALLOWED = {# handoffs/wifi.md
                 # handoffs/ram.md. blazer_mem above 4 needs ram 0760 in the kernel; 13 clamps to the map's top
                 'blazer_mem': r'blazer_mem=([5-9]|1[0-3])', 'blazer_mem_test': r'blazer_mem_test=(64|4096)', 'blazer_mem_report': r'blazer_mem_report=1',
                 'blazer_wifi': r'blazer_wifi=1', 'blazer_wifi_stage': r'blazer_wifi_stage=[0-3]', 'blazer_wifi_gen': r'blazer_wifi_gen=[1-3]', 'blazer_wifi_delay': r'blazer_wifi_delay=[0-9]{1,3}', 'blazer_wifi_end': r'blazer_wifi_end=[0-9]{1,4}', 'blazer_wifi_hold': r'blazer_wifi_hold=1', 'blazer_wifi_aux': r'blazer_wifi_aux=1', 'blazer_wifi_force': r'blazer_wifi_force=1',
                 'blazer_usbcon': r'blazer_usbcon=[12]', 'blazer_touch': r'blazer_touch=1', 'blazer_touch_bars': r'blazer_touch_bars=1', 'touch_flip': r'touch_flip=[123]',
                 # handoffs/cpmlock.md. Each its own boot, in that order. The panic limit is the kernel's own range, 30..102
                 'blazer_thermal': r'blazer_thermal=[12]', 'blazer_thermal_panic_c': r'blazer_thermal_panic_c=(3[0-9]|[4-9][0-9]|10[0-2])', 'blazer_keys': r'blazer_keys=1',
                 'blazer_sensors': r'blazer_sensors=[123]', 'blazer_sensors_flip': r'blazer_sensors_flip=[0-7]',
                 'hk_clk': r'hk_clk=([6-9]|[1-9][0-9]|[1-5][0-9][0-9]|600)',  # handoffs/dramclk.md
                 'hk_top': r'hk_top=([5-9]|[1-9][0-9]|[1-5][0-9][0-9]|600)', 'hk_ui': r'hk_ui=[0-9]+:[a-z0-9.,]+',
                 # handoffs/overlay.md. hk_overlay: nonzero, and only once the image carries an overlay (build() checks), or the kernel panics by design.
                 'hk_overlay': r'hk_overlay=(0x[0-9a-fA-F]{1,8}|[1-9][0-9]{0,9})', 'hk_deny': r'hk_deny=[A-Za-z0-9._+-]+(,[A-Za-z0-9._+-]+)*',
                 'hk_env': r'hk_env=[A-Za-z0-9._-]+(\+[A-Za-z0-9._-]+)*:[A-Za-z_][A-Za-z0-9_]*=[^\s;,:]*(;[A-Za-z_][A-Za-z0-9_]*=[^\s;,:]*)*(,[A-Za-z0-9._-]+(\+[A-Za-z0-9._-]+)*:[A-Za-z_][A-Za-z0-9_]*=[^\s;,:]*(;[A-Za-z_][A-Za-z0-9_]*=[^\s;,:]*)*)*'}
# handoffs/persist.md. Not 2: that mode needs blazer_ufs_test=1, which this line doesn't have. The kernel bounds the period.
PHONE_ALLOWED.update({'blazer_persist': r'blazer_persist=[13]', 'blazer_persist_period': r'blazer_persist_period=[1-9][0-9]{1,3}', 'blazer_persist_selftest': r'blazer_persist_selftest=1', 'blazer_persist_fresh': r'blazer_persist_fresh=1'})
# docs/DUALBOOT.md: read-only native metadata capture; no host reset/persist mode.
PHONE_ALLOWED.update({'blazer_usb_readback': r'blazer_usb_readback=1', 'blazer_usbcon_ch9': r'blazer_usbcon_ch9=1'})
PHONE_ALLOWED.update({'blazer_battery_chg': r'blazer_battery_chg=1', 'blazer_aoc': r'blazer_aoc=1'})  # handoffs/battery.md: the charger's frames, off unless asked; parent, aoc
PHONE_CANVAS = '1125x2511'  # native's request, the only other size the phone ADT can have
# validation_disables: kconfig.md, osfmk/kern/debug.c. atm_diagnostic_config: mine.md, osfmk/atm/atm.c:60. hk_fb_*: render's names.
PHONE_EXACT = ('blazer_fast_first=1', 'blazer_smp_report=1', 'blazer_smp_report=2', 'blazer_smp_test=1', 'blazer_ssbs=1', 'blazer_ssbs=3', 'validation_disables=0x39d64', 'atm_diagnostic_config=0x400', 'hk_fb_scale=1', 'hk_fb_scale=2', 'hk_fb_filter=1', 'blazer_ufs_multi=1', 'blazer_cs_nohash=1', 'blazer_rtc=1', 'blazer_keys=1', 'blazer_haptic=1', 'blazer_haptic=3', 'hk_bench=1', 'hk_amu=1', 'hk_pmu=1', 'hk_pmu=2', 'hk_fb_fast=1', 'blazer_ic_va=1', 'hk_fb_bench=2', 'blazer_ufs_spin_us=300', 'blazer_ufs_cost=1', 'blazer_ufs_hold=1', 'blazer_battery=1', 'blazer_battery=2', 'hk_fb_period=1', 'hk_fb_te=1', 'hk_fb_te=2', 'hk_panel_hz=120', 'hk_panel_hz=60', 'hk_panel_hz=30', 'hk_panel_hz=10', 'hk_panel_off=1')  # last two: mine.md
def set_cpus(c, n):
    """The line it was, with cpus=N. Both multi-core shapes come through here."""
    if len(re.findall(r'(?<!\S)cpus=1(?!\S)', c)) != 1: die('line has no single cpus=1')
    return re.sub(r'(?<!\S)cpus=1(?!\S)', f'cpus={n}', c)
def check_cpu_line(blob, line):
    """The kernel keeps the first N-1 nodes plus the boot core: a count that differs from the ADT drops cores with no message."""
    nodes = next(n for n in ADT.parse(blob)[0].children if n.name == 'cpus').children; said = [t for t in line.split() if t.startswith('cpus=')]
    if said != [f'cpus={len(nodes)}']: die(f'line says {said}, ADT has {len(nodes)} CPU nodes')
    if any(n.prop('cluster-type') != b'\0\0\0\0' for n in nodes): die('cluster-type must stay 0: MAX_CPU_CLUSTERS is 1')
    if 0x700 in [struct.unpack('<I', n.prop('reg'))[0] for n in nodes]: die('X4 in the ADT: refused, handoffs/smp.md')
def phone_extra(text):
    """Validated tokens for --phone-args. Refuses anything off the list, and repeats: PE_parse takes one value."""
    toks = (text or '').split(); names = [t.split('=', 1)[0] for t in toks]
    if len(set(names)) != len(names): die(f'repeated token in --phone-args: {text}')
    for t, n in zip(toks, names):
        if t not in PHONE_EXACT and not (n in PHONE_ALLOWED and re.fullmatch(PHONE_ALLOWED[n], t)): die(f'--phone-args: {t} is not on the list')
    if 'blazer_usb_readback=1' in toks:
        if 'blazer_usbcon=1' not in toks: die('readback requires blazer_usbcon=1')
        if any(n.startswith('blazer_persist') for n in names): die('readback capture cannot enable persistence writes')
    return toks
PHONE_KERNEL_NEEDS = (b'ramfs', b'hk_fb_scanout', b'var.skel')
SECOND_ARGS = 'hk_fb_scanout=1 sweetfb_noconsole=1 hk_fb_probe=1'  # parent, STATUS 2026-11-01
FIRST_MD0 = (R/'laguna-usb-fix/native-fleet-20261031/N419-ioctl-phone-package/admission/artifacts/root.hfs', '3cd4dcb5a505783157d5a1612916e6834ee270edd1139d0c830022986a462780')
G4_WRITES = {0xfd3ff000: 'tegu RAM console, start.s'}

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        while (b := f.read(1 << 22)): h.update(b)
    return h.hexdigest()
def die(m): sys.exit('refused: ' + m)
def pin(item):
    p, want = item
    if not p.exists() or sha(p) != want: die(f'{p} missing or not the pinned file')
    return p

def g4_literals(buf, segs):
    """Find MOV64-style immediates: a movz and movk of the same register building a listed address, within 4 instructions."""
    found = {}
    for s in segs:
        if not s['name'].startswith('__TEXT_EXEC') or not s['filesize']: continue
        w = array.array('I'); w.frombytes(bytes(buf[s['fileoff']:s['fileoff'] + (s['filesize'] & ~3)]))
        for addr, why in G4_WRITES.items():
            lo, hi = addr & 0xffff, addr >> 16
            for rd in range(31):
                mz, mk = 0xd2800000 | lo << 5 | rd, 0xf2a00000 | hi << 5 | rd
                for i, x in enumerate(w):
                    if x == mk and mz in w[max(0, i - 4):i + 5]:
                        found[hex(addr)] = why; break
    return found

def check_kernel(path, want_sha, test):
    if sha(path) != want_sha: die(f'kernel hash is {sha(path)}, not {want_sha}')
    buf = Path(path).read_bytes(); m = mkpayload.parse_macho(bytearray(buf))
    if m['entry'] is None: die('kernel has no LC_UNIXTHREAD')
    is12377 = re.search(rb'xnu-12377', buf) is not None
    g4 = g4_literals(buf, m['segs'])
    why = ([] if is12377 else ['no xnu-12377 version string']) + [f'Tensor G4 write {a}: {w}' for a, w in g4.items()]
    if why and not test: die('kernel not bootable on this phone: ' + '; '.join(why))
    return dict(xnu12377=is12377, g4_writes=g4, not_bootable_because=why)

def cmdline(a, epoch):
    if getattr(a, 'soak', None) is not None:  # read-only, never a phone-run kernel. 0: what the shim's rewrite leaves when UFS isn't live
        if a.soak == 0: return 'debug=0x8 serial=3 cpus=1 rd=md0 msgbuf=1048576 blazer_deadline=300 blazer_panic=1'
        return ('debug=0x8 serial=3 cpus=1 rd=md0 blazer_ufs_mountroot=1 msgbuf=1048576 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=userdata_exp.ai '
                f'blazer_ufs_lun=0 blazer_ufs_test=1 blazer_ufs_fullcheck={a.soak} blazer_deadline=1500 blazer_panic=1')
    if a.phone_root:  # read-only HFSX root on UFS, RAM /private/var from varfs: PHONE-ROOT.md
        return PHONE_ARGS.replace('ROUTE', PHONE_ROUTES[a.phone_route]) + (' ' + TOUCH_ARG if getattr(a, 'touch', False) else '') + ''.join(' ' + t for t in phone_extra(getattr(a, 'phone_args', None)))
    if a.first_boot:  # blazer's contract, verbatim. userdata_exp.ai on LUN 0: physical, 20261101-201914-ufs-root-r2
        return 'debug=0x8 serial=3 cpus=1 rd=md0 msgbuf=1048576 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=userdata_exp.ai blazer_ufs_lun=0 blazer_ufs_test=1 ' + (f"blazer_ufs_deadline=1200 blazer_ufs_fullcheck={2 if getattr(a, 'persist_table', None) else 1}" + (f" blazer_persist={a.persist}" if getattr(a, 'persist', None) else '') if getattr(a, 'fullcheck', None) else 'blazer_ufs_deadline=300') + ' unentitled_ios_sim_launch=1' + (' ' + SECOND_ARGS if a.second_boot else '')
    root = 'rd=ufsroot0 rootfstype=hfs' if a.route == 'ufs' else 'rd=md0 blazer_ufs_mountroot=1'
    c = f'debug=0x8 serial=3 cpus={a.cpus} keepsyms=1 -noprogress {root} {USER} {UFS} epoch={epoch}'
    if a.args: c += ' ' + a.args
    if 'virtio' in c or 'blazer_ufs_fake' in c: die('test-only token in command line')
    if len(c) >= mkpayload.BOOT_LINE_LENGTH: die(f'command line {len(c)} bytes, shim limit {mkpayload.BOOT_LINE_LENGTH - 1}')
    return c

def overlay_groups(blob):
    """Group bits of a HKVAROV1 overlay, walking it as varfs_overlay.h does. Dies on anything the kernel would panic on."""
    if blob[:8] != b'HKVAROV1' or len(blob) < 24: die('overlay: bad magic')
    total, count, h = struct.unpack_from('<IIQ', blob, 8)
    if total != len(blob): die(f'overlay: header says {total} B, file has {len(blob)}')
    f = 0xcbf29ce484222325
    for b in blob[24:]: f = ((f ^ b) * 0x100000001b3) & (2**64 - 1)
    if f != h: die('overlay: hash differs')
    off = 24; groups = set()
    for _ in range(count):
        if off + 24 > total: die('overlay: truncated entry')
        group = blob[off + 1]; plen, dlen = struct.unpack_from('<II', blob, off + 16)
        off = (off + 24 + plen + 1 + 7) & ~7; off = (off + dlen + 7) & ~7; groups.add(group)
    if off != total: die('overlay: bytes after the last entry')
    return groups

def check_overlay(a):
    """hk_overlay and the file go together, or the boot panics or the file does nothing. Every mask bit must name a group: else the kernel panics before launchd."""
    toks = [t for t in phone_extra(a.phone_args) if t.startswith('hk_overlay=')]
    if not a.var_overlay:
        if toks: die('hk_overlay needs --var-overlay: the kernel panics with no overlay in the image')
        if a.var_overlay_sha: die('--var-overlay-sha without --var-overlay')
        return None
    if not a.phone_root: die('--var-overlay goes with --phone-root')
    if not toks: die('--var-overlay needs hk_overlay= in --phone-args: otherwise nothing reads it')
    if not a.var_overlay_sha or sha(a.var_overlay) != a.var_overlay_sha: die('--var-overlay-sha is not this file')
    blob = Path(a.var_overlay).read_bytes(); groups = overlay_groups(blob); mask = int(toks[0].split('=')[1], 0)
    extra = [b for b in range(32) if mask >> b & 1 and b not in groups]
    if extra: die(f'hk_overlay={mask:#x}: bits {extra} name no group in this overlay; it has {sorted(groups)}')
    return dict(path=str(a.var_overlay), sha256=a.var_overlay_sha, bytes=len(blob), mask=mask, groups=sorted(groups))

def scope(name):
    s = WORK/'scope'/name; shutil.rmtree(s, ignore_errors=True); (s/'tools').mkdir(parents=True)
    shutil.copy2(X/'mkbootimg.py', s/'tools/mkbootimg.py')
    t = s/'shim'; shutil.copytree(SHIM, t, ignore=shutil.ignore_patterns('out', '__pycache__'))
    x = t/'test_ufs_route.py'; v = x.read_text()
    if v.count('ROOT = S.parent\n') != 1: die('test_ufs_route.py changed: fix scope()')
    x.write_text(v.replace('ROOT = S.parent\n', "ROOT = next(p for p in S.parents if (p/'AGENTS.md').exists())\n"))
    return t

def contract_check(payload):
    """Run the shim's own tgl_payload_validate on the bytes: tool and shim must agree."""
    d = WORK/'contract'; d.mkdir(parents=True, exist_ok=True)
    src = d/'c.c'; exe = d/f'c{os.getpid()}'
    src.write_text('''#include <stdio.h>
#include <stdlib.h>
#include "payload.h"
int main(int c, char **v) { FILE *f = fopen(v[1], "rb"); fseek(f, 0, SEEK_END); long n = ftell(f); rewind(f);
 void *b = aligned_alloc(16, (n + 15) & ~15L); fread(b, 1, n, f); struct tgl_payload_view w;
 const char *e = tgl_payload_validate((uintptr_t)b, n, 0, 0, &w);
 if (e) { printf("REFUSED %s\\n", e); return 1; }
 printf("{\\"adt_pa\\":\\"0x%llx\\",\\"boot_args_pa\\":\\"0x%llx\\",\\"top\\":\\"0x%llx\\",\\"entry_pa\\":\\"0x%llx\\"}\\n", (unsigned long long)w.adt_pa, (unsigned long long)w.ba_pa, (unsigned long long)w.top, (unsigned long long)w.entry_pa); return 0; }
''')
    subprocess.run(['/usr/bin/cc', '-w', '-O1', f'-I{SHIM}', str(src), '-o', str(exe)], check=True)
    r = subprocess.run([str(exe), str(payload)], capture_output=True, text=True); exe.unlink()
    if r.returncode: die('shim validator: ' + r.stdout.strip())
    return json.loads(r.stdout)

def adt_facts(blob):
    root, _ = ADT.parse(blob)
    if b'TrustCache' in blob: die('ADT has a TrustCache: the kernel has a stand-in library and no such support')
    ch = {c.name: c for c in root.children}
    if 'product' not in ch: die('ADT has no /product')
    c = ch['chosen']; u = lambda n, k: struct.unpack('<I', n.prop(k))[0]
    if c.prop('laguna-display-handoff') != b'\0' * 16: die('shim refuses an ADT with no zero laguna-display-handoff')
    f = dict(model=root.prop('model').rstrip(b'\0').decode(), compatible=root.prop('compatible').decode().split('\0')[:-1], chip_id=hex(u(c, 'chip-id')),
             tuple=[u(c, k) for k in ('certificate-production-status', 'effective-production-status-ap', 'certificate-security-mode', 'effective-security-mode-sep')],
             home_button_type=u(ch['buttons'], 'home-button-type'), dram=[hex(struct.unpack('<Q', c.prop(k))[0]) for k in ('dram-base', 'dram-size')],
             seed_sha256=hashlib.sha256(c.prop('random-seed')).hexdigest(), ctrr=u(c, 'kernel-ctrr-to-be-enabled'))
    disp = next((x for x in ch['arm-io'].children if x.name == 'disp0'), None); f['canvas'] = disp and [u(disp, 'canvas-width'), u(disp, 'canvas-height')]
    f['boot_reg'] = u(next(n for n in ch['cpus'].children if n.prop('state') == b'running\0'), 'reg')  # the first node, unless --cpu-order
    fb = ch.get('sweet-fbcon'); f['fb'] = fb and [hex(struct.unpack('<2Q', fb.prop('reg'))[0]), u(fb, 'width'), u(fb, 'height')]
    return f

def build(a):
    name = ('test-' + a.name) if a.test_kernel and not a.name.startswith('test-') else a.name
    out = RUN/name
    if out.exists(): die(f'{out} exists: an image is not rebuilt after handover. Use a new name')
    if a.soak is not None:
        if not name.startswith('soak-') or a.first_boot or a.second_boot or a.phone_root or a.dpu or a.md0 or a.md1 or a.args or a.route != 'ufs': die('--soak: name soak-*, no other profile')
        if b'blazer-ufs-fullcheck: pass' not in Path(a.kernel).read_bytes(): die('kernel has no soak passes')
    ov = check_overlay(a)
    # Two multi-core shapes, never both. --cpu-order: XNU boots on cpu0, cores in that order, smp's. --bootcpu --cpus: boots on an A725, cpu0 parked and not in the ADT, fastcore's.
    order = cpu_order(a.cpu_order) if getattr(a, 'cpu_order', None) is not None else None
    if order:
        if a.bootcpu: die('--cpu-order and --bootcpu: --bootcpu parks cpu0, which --cpu-order needs. For a fast boot core, --bootcpu --cpus. handoffs/smp.md')
        if a.cpus != 1: die('--cpu-order sets cpus=N from its length: no --cpus')
    if 'blazer_fast_first=1' in phone_extra(getattr(a, 'phone_args', None)) and not order: die('blazer_fast_first=1 goes with --cpu-order: on --bootcpu --cpus the cores are alike, handoffs/fastcore.md section 0')
    if a.phone_root:
        if a.first_boot or a.second_boot or a.dpu or a.md0 or a.md1 or a.args or a.gamut or a.route != 'ufs' or (a.cpus != 1 and not a.bootcpu): die('--phone-root is the recipe as written: no other options')
        if a.canvas not in (None, PHONE_CANVAS): die(f'--phone-root takes only --canvas {PHONE_CANVAS}')
        if a.phone_route not in PHONE_ROUTES: die(f'--phone-root needs --phone-route, one of {sorted(PHONE_ROUTES)}')
        if a.preflight:
            # Boot-only, on whatever the partition holds. Labelled, never bootable: the real image still needs --qemu-run.
            if a.qemu_run or not name.startswith('phone-preflight-'): die('--preflight: name phone-preflight-*, no --qemu-run')
        elif not a.qemu_run or not any((R/d/'runs'/a.qemu_run).is_dir() for d in QEMU_RUN_DIRS): die('--phone-root needs --qemu-run NAME: the QEMU run the parent accepted')
        a.dpu = True; a.gamut = 'sRGB'
    if a.second_boot:
        if a.first_boot or a.dpu: die('--second-boot already means the first-boot contract plus the DPU stage')
        a.first_boot = a.dpu = True; given_dpu = True
    else: given_dpu = False
    if a.first_boot:
        if (a.dpu and not given_dpu) or a.canvas or a.gamut or a.args or (a.cpus != 1 and not a.bootcpu): die('--first-boot is the contract as written: no other options')
        a.route, a.md0 = 'md', a.md0 or str(FIRST_MD0[0])
        if sha(a.md0) != FIRST_MD0[1]: die('--first-boot md0 must be the pinned compact root')
    if a.route == 'md' and not a.md0: die('--route md needs --md0')
    if a.route == 'ufs' and (a.md0 or a.md1): die('--route ufs takes no md images')
    avb, key = pin(AVBTOOL), pin(AVBKEY)
    k = check_kernel(a.kernel, a.kernel_sha, a.test_kernel)
    if a.phone_root:
        buf = Path(a.kernel).read_bytes(); miss = [t.decode() for t in PHONE_KERNEL_NEEDS if t not in buf]
        if miss: die(f'kernel lacks what the phone root needs: {miss}')
        if a.touch and b'blazer_touch' not in buf: die('kernel has no blazer_touch')
        if ov and b'HKVarOverlay' not in buf: die('kernel does not read HKVarOverlay')
        for t in phone_extra(a.phone_args):
            if t.split('=')[0].encode() not in buf: die(f'kernel does not read {t}')
        extra = phone_extra(a.phone_args)
        if 'blazer_keys=1' in extra and b'blazer-keys: polling pads' not in buf: die('kernel holds keys until keys-probe-r1 passes: handoffs/cpmlock.md')
        if any(t.startswith('blazer_thermal_panic_c=') for t in extra) and 'blazer_thermal=2' not in extra: die('blazer_thermal_panic_c needs blazer_thermal=2')
        if getattr(a, 'phone_deadline', None) not in (None, 300, 1800, 3600): die('--phone-deadline: 300, 1800 or 3600')
        if getattr(a, 'phone_deadline', None) == 3600 and ('blazer_thermal=2' not in extra or a.bootcpu): die('--phone-deadline 3600: power.md, needs the armed guard, blazer_thermal=2, and no --bootcpu')
        if getattr(a, 'phone_deadline', None) == 3600 and order: die('--phone-deadline 3600: power.md, not with --cpu-order')
        if getattr(a, 'phone_deadline', None) == 1800 and (a.bootcpu or order) and (order or a.cpus != 1 or 'blazer_thermal=1' not in extra): die('--phone-deadline 1800 on a fast core: limits.md P1b, one A725 with blazer_thermal=1. Several cores stay at 900')
        if a.phone_route == 'md0-mountroot' and b'rooting on ufsroot0' not in buf: die('kernel lacks the md0-mountroot route (blazer 0530)')
    if a.touch and not a.phone_root: die('--touch goes with --phone-root')
    if a.phone_args and not a.phone_root: die('--phone-args goes with --phone-root')
    if a.touch and 'blazer_touch' in [t.split('=')[0] for t in phone_extra(a.phone_args)]: die('blazer_touch given twice')
    p_mode, p_table, p_expect = getattr(a, 'persist', None), getattr(a, 'persist_table', None), getattr(a, 'expect_test_block', None)
    if p_mode or p_table or p_expect:  # handoffs/persist.md: the fullcheck line only
        if not (a.first_boot and getattr(a, 'fullcheck', None)) or a.second_boot: die('--persist, --persist-table, --expect-test-block go with --first-boot --fullcheck')
        if p_mode == 2 and not p_table: die('--persist 2 writes the test block: the pass after it must skip the table')
        if (p_mode or p_table) and b'blazer_persist' not in Path(a.kernel).read_bytes(): die('kernel has no blazer_persist')
        if p_expect and (p_mode or p_table): die('--expect-test-block is for a kernel with no mask, after the test')
    epoch = int(time.time()); c = cmdline(a, epoch)
    if a.bootcpu:  # the same line plus the token. --first-boot and --second-boot lines also get the reset path and the per-core report
        if a.bootcpu not in BOOTCPUS or not 1 <= a.cpus <= 5: die(f'--bootcpu: one of {BOOTCPUS}, at cpus 1 to 5')
        if b'blazer_bootcpu' not in Path(a.kernel).read_bytes(): die('kernel has no blazer_bootcpu gate')
        if a.cpus != 1:  # fastcore 0703, smp 0722. Without them the kernel panics at its boot-core check, or has no SMP fixes
            if b'CPUs, cpu0 parked in the shim' not in Path(a.kernel).read_bytes() or b'blazer_smp_test' not in Path(a.kernel).read_bytes(): die('--bootcpu --cpus: kernel lacks fastcore 0703 or smp 0722')
            c = set_cpus(c, a.cpus)
        c += f' blazer_bootcpu={a.bootcpu}' + (' blazer_panic=1 blazer_smp_report=1' if a.first_boot else '')
    if order:  # same limits as a faster boot core: power.md's don't carry over
        if not (a.phone_root or a.first_boot): die('--cpu-order goes with --phone-root or --first-boot')
        buf = Path(a.kernel).read_bytes()
        if b'blazer_fast_first' not in buf or b'blazer_smp_test' not in buf: die('kernel has no 0722 or 0724')
        c = set_cpus(c, len(order))
        if a.first_boot: c += ' blazer_panic=1 blazer_smp_report=1 blazer_smp_test=1 blazer_smp_panic=0'  # the check: it ends by panicking on logical 0, a secondary
    pd = getattr(a, 'phone_deadline', None)
    if pd in (300, 3600) and not a.phone_root: die('--phone-deadline goes with --phone-root')
    if a.phone_root:  # handoffs/limits.md. 300: handoffs/persist.md, a stage boot that ends by itself, shorter than any limit. Default on either fast shape: 900
        if c.count('blazer_deadline=1800') != 1: die('phone line has no single 1800 s deadline')
        c = c.replace('blazer_deadline=1800', f'blazer_deadline={pd}' if pd else FC_DEADLINE if a.bootcpu or order else 'blazer_deadline=1800')
    if len(c) >= mkpayload.BOOT_LINE_LENGTH: die(f'command line {len(c)} bytes, shim limit {mkpayload.BOOT_LINE_LENGTH - 1}')
    out.mkdir(parents=True)
    if a.fullcheck:
        if not a.first_boot or a.second_boot: die('--fullcheck goes with --first-boot')
        if a.fullcheck != a.readback: die('--fullcheck and --readback name the same root')
        if b'blazer-ufs-fullcheck' not in Path(a.kernel).read_bytes(): die('kernel has no fullcheck mode')
    rb = None
    if a.readback:
        if not a.first_boot or a.second_boot: die('--readback goes with --first-boot: it boots the proven kernel and md0')
        import phone_write as PW
        rb = PW.choose(a.readback, a.readback_sha)
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'LLVM': str(LLVM), 'HOSTCC': '/usr/bin/cc', 'TGL_UFS_HANDOFF': '1',
           'EXTRA_CFLAGS': SHIM_FLAGS + (' ' + DPU_FLAGS if a.dpu else '') + (' ' + FC_FLAGS if a.bootcpu else ''), 'TGL_EXTRA_SRC': 'tgl_all.c' + (' tgl_dcs.c' if a.dpu else '') + (' ' + FC_SRC if a.bootcpu else '')}
    window = int(getattr(a, 'window_base', None) or hex(PHYS), 16)  # handoffs/ram.md
    if rb: env['EXTRA_CFLAGS'] += f" -DTGL_UFSH_MANIFEST_BLOCK={rb['last']}u -DTGL_UFSH_SAMPLE_LIST=" + ','.join(f'{n}u' for n in rb['samples'])
    root = mkadt.build(headless=a.first_boot or a.phone_root or a.soak is not None, disp0=a.second_boot or a.phone_root, cpus=a.cpus, canvas=tuple(map(int, a.canvas.split('x'))) if a.canvas else None, gamut=a.gamut, boot_mpidr=int(a.bootcpu, 16) if a.bootcpu else 0, cpu_order=order, phys_base=window)
    blob = ADT.serialize(root); blob += b'\0' * (-len(blob) % 8)
    facts = adt_facts(blob); (out/'laguna.adt').write_bytes(blob)
    if facts['boot_reg'] != int(a.bootcpu or '0', 16): die('ADT reg and --bootcpu differ')
    many = order or (a.bootcpu and a.cpus != 1)
    if many: check_cpu_line(blob, c)
    pl = out/'payload-usb.bin'
    try: raw, info = mkpayload.build(a.kernel, out/'laguna.adt', c, a.md0, a.md1, a.legacy_base, a.var_overlay)
    except ValueError as e: die(str(e))
    if not a.test_kernel:  # 12377 kernel: blazer's values. slide 0, TTBR1 range T1SZ 17, nothing that must survive below the mach header
        vb, text = int(info['virt_base'], 16), int(info['segs'][0][1], 16)
        if vb != (text & ~(mkpayload.L2_BLOCK - 1)) or text >> 41 != (1 << 23) - 1: die(f"virt base {info['virt_base']} or __TEXT {hex(text)} outside the 12377 large-memory contract")
        if int(info['entry'], 16) < text: die('entry below __TEXT')
    if len(raw) > PARTITION - FOOTER_ROOM: die(f'payload {len(raw)} B does not fit the {PARTITION} B boot image')
    pl.write_bytes(raw); plan = contract_check(pl)
    if ov:
        placed = int(info['var_overlay'][0], 16); text_pa = window + int(info['segs'][0][1], 16) - int(info['virt_base'], 16)
        if not (text_pa < placed and placed + int(info['var_overlay'][1], 16) <= int(plan['adt_pa'], 16)): die(f"overlay at {info['var_overlay']} isn't above the kernel and below the ADT")
        if raw.find(Path(a.var_overlay).read_bytes()) < 0: die('overlay bytes not in the payload')
    t = scope(name)
    with (out/'build.log').open('w') as log: subprocess.run(['bash', str(t/'build.sh'), str(pl)], check=True, env=env, stdout=log, stderr=subprocess.STDOUT)
    img = out/'boot.img'; shutil.copy2(t/'out/shim-boot-laguna.img', img)
    subprocess.run([sys.executable, '-I', str(avb), 'add_hash_footer', '--image', str(img), '--partition_name', 'boot', '--partition_size', str(PARTITION), '--salt', SALT, '--algorithm', 'SHA256_RSA4096', '--rollback_index', str(ROLLBACK), '--key', str(key)], check=True)
    with (out/'avb-verify.txt').open('w') as v: subprocess.run([sys.executable, '-I', str(avb), 'verify_image', '--image', 'boot.img'], cwd=out, check=True, stdout=v, stderr=subprocess.STDOUT)
    avbt = (out/'avb-verify.txt').read_text()
    if 'Successfully verified sha256 hash' not in avbt: die('AVB verify failed')
    for f in ('ufs-ids.json', 'shim.elf'): shutil.copy2(t/'out'/f, out/f)
    nm = lambda *x: subprocess.run([str(LLVM/'llvm-nm'), *x, str(out/'shim.elf')], capture_output=True, text=True, check=True).stdout
    if nm('-u').split(): die('undefined symbols in shim')
    syms = nm(); want = ['tgl_ufsh_power_mode', 'tgl_ufs_link_relink', 'tgl_all_mark'] + (['tgl_dcs_guarded'] if a.dpu else []) + (['tgl_fc_entry', 'tgl_fastcore_handoff'] if a.bootcpu else [])
    for sym in want:
        if not re.search(rf'\s{sym}$', syms, re.M): die(f'shim lacks {sym}')
    if not a.dpu and re.search(r'\stgl_dcs_guarded$', syms, re.M): die('DPU stage present though off')
    if not a.bootcpu and re.search(r'\stgl_fc_entry$', syms, re.M): die('fastcore present though off')
    log = (out/'build.log').read_text()
    tests = {k: re.search(p, log) for k, p in dict(route=r'ufs route host test: \d+ checks, 0 failed', route_mutants=r'mutants \d+/\d+ caught', speed=r'ufs speed host test: \d+ checks, 0 failed', stages=r'all-stage host test: \d+ checks, 0 failed').items()}
    miss = [k for k, m in tests.items() if not m]
    if miss: die(f'shim test lines missing: {miss}')
    img_b = img.read_bytes(); at = img_b.find(b'TEGUPLD1')
    if at < 0 or struct.unpack_from('<Q', img_b, at + 8)[0] != len(raw) or img_b[at + 16:at + 16 + len(raw)] != raw: die('payload not embedded intact')
    ids = json.loads((out/'ufs-ids.json').read_text())
    rec = dict(bootcpu=a.bootcpu, var_overlay=dict(ov, placed=info.get('var_overlay')) if ov else None, soak_whole=a.soak_whole, preflight=bool(a.preflight), soak=a.soak, fullcheck=bool(a.fullcheck), readback=rb, phone_root=a.phone_root, first_boot=a.first_boot, second_boot=a.second_boot, name=name, bootable=not a.test_kernel and a.soak is None and not a.preflight and not k['not_bootable_because'], kernel=k, mach=sha(a.kernel), route=a.route, cmdline=c, cmdline_bytes=len(c), epoch=epoch, ids=ids, adt=sha(out/'laguna.adt'), adt_facts=facts,
               donor=mkadt.D421AP_SHA256, md0=sha(a.md0) if a.md0 else None, md1=sha(a.md1) if a.md1 else None, image=sha(img), image_bytes=img.stat().st_size, payload=sha(pl), payload_bytes=len(raw), margin_bytes=PARTITION - FOOTER_ROOM - len(raw),
               virt_base=info['virt_base'], entry=info['entry'], kernel_end=info['kernel_end'], fixups=info['fixups'], segs=info['segs'], plan=plan, dpu=a.dpu, cflags=env['EXTRA_CFLAGS'], extra_src=env['TGL_EXTRA_SRC'],
               tests={k: m.group(0) for k, m in tests.items()}, avb=avbt.strip().splitlines()[-1], decode=f'python3 -I tools/all_decode.py <attempt>/ramdump/kernel.log research/images/{name}/manifest.json',
               shim_copy=tree(SHIM), tools={n: sha(X/n) for n in ('adt.py', 'image_tool.py', 'mkadt.py', 'mkbootimg.py', 'mkpayload.py')})
    if window != PHYS: rec['window_base'] = hex(window)
    if many: rec.update(cpus=len(order) if order else a.cpus, **({'cpu_order': order} if order else {}))  # no shape, no new keys
    if a.fullcheck:
        import fullcheck as FC
        mask = FC.table_mask(p_table) if p_table else None
        overlay = FC.test_block(*p_expect.rsplit(':', 1)) if p_expect else None
        (out/'fullcheck.json').write_text(json.dumps(dict(FC.compute(a.fullcheck, mask, overlay), root_sha256=a.readback_sha)) + '\n')
    (out/'manifest.json').write_text(json.dumps(rec, indent=1, sort_keys=True) + '\n')
    (out/'SHA256SUMS').write_text(''.join(f'{sha(out/f)}  {f}\n' for f in ('boot.img', 'payload-usb.bin', 'laguna.adt', 'manifest.json')))
    print(name, 'bootable' if rec['bootable'] else 'NOT BOOTABLE', rec['image'], 'payload', len(raw), 'margin', rec['margin_bytes']); print(rec['decode'])
    return rec

def tree(d):
    h = hashlib.sha256()
    for p in sorted(Path(d).rglob('*')):
        if p.is_file() and 'out' not in p.relative_to(d).parts and '__pycache__' not in p.parts: h.update(p.relative_to(d).as_posix().encode() + b'\0' + p.read_bytes())
    return h.hexdigest()

def check(d):
    d = Path(d); m = json.loads((d/'manifest.json').read_text()); bad = [f for f, k in (('boot.img', 'image'), ('payload-usb.bin', 'payload'), ('laguna.adt', 'adt')) if sha(d/f) != m[k]]
    if bad: sys.exit(f'MISMATCH {bad}')
    if struct.unpack_from('<I', (d/'payload-usb.bin').read_bytes()[:12], 8)[0] == 1:
        print('payload version 1: built before the 1024-byte line; hashes only, this shim source validates version 2')
    elif contract_check(d/'payload-usb.bin') != m['plan']: sys.exit('plan differs')
    if 'cpus' in m: check_cpu_line((d/'laguna.adt').read_bytes(), m['cmdline'])
    print('OK', m['name'], 'bootable' if m['bootable'] else 'NOT BOOTABLE', m['image'])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('image'); i.add_argument('name'); i.add_argument('--kernel', required=True); i.add_argument('--kernel-sha', required=True)
    i.add_argument('--route', choices=['ufs', 'md'], default='ufs'); i.add_argument('--md0'); i.add_argument('--md1'); i.add_argument('--cpus', type=int, default=1); i.add_argument('--cpu-order', help='cores for cpus=N in logical order, e.g. 5,6,2,3,4,1,0. handoffs/smp.md'); i.add_argument('--dpu', action='store_true')
    i.add_argument('--canvas'); i.add_argument('--gamut'); i.add_argument('--args'); i.add_argument('--test-kernel', action='store_true'); i.add_argument('--legacy-base', action='store_true'); i.add_argument('--phone-root', action='store_true', help='PHONE-ROOT.md: --route ufs on ios26-phone-r1'); i.add_argument('--soak', type=int, help='N read-only passes, not a phone-run image; 0: the not-live line'); i.add_argument('--preflight', action='store_true', help='--phone-root line on the old partition content, labelled, not bootable'); i.add_argument('--touch', action='store_true', help='--phone-root plus blazer_touch=1, nothing else'); i.add_argument('--phone-deadline', type=int, help='1800, or 3600 with blazer_thermal=2: handoffs/cpmlock.md'); i.add_argument('--soak-whole', help='whole crc the passes must give, hex'); i.add_argument('--phone-args', help='extra tokens for --phone-root, allow-list only'); i.add_argument('--var-overlay', help='overlay file for hk_overlay=MASK'); i.add_argument('--var-overlay-sha'); i.add_argument('--bootcpu', help='0x200, 0x300 or 0x500: run XNU on that core, ios26-fastcore-r1. Parent only, after speed-probe-r3'); i.add_argument('--qemu-run'); i.add_argument('--phone-route'); i.add_argument('--readback', help='root image: sample its blocks for read-back'); i.add_argument('--readback-sha'); i.add_argument('--fullcheck', help='same root as --readback: read all of it and log CRCs'); i.add_argument('--persist', type=int, choices=[2, 3], help='with --fullcheck: blazer_persist=N, handoffs/persist.md'); i.add_argument('--persist-table', help='table.json: the pass skips its blocks, blazer_ufs_fullcheck=2, and so does the list'); i.add_argument('--expect-test-block', help='TABLE.json:A or :B: the list for a kernel with no mask after blazer_persist=2 wrote that pattern'); i.add_argument('--window-base', choices=(hex(PHYS), '0x882000000'), help='kernel RAM base, handoffs/ram.md'); i.add_argument('--second-boot', action='store_true', help='first-boot contract plus shim DPU stage, disp0 and the scanout arguments'); i.add_argument('--first-boot', action='store_true', help="blazer's first phone boot contract: headless ADT, md0 only, fixed base and command line")
    c = sub.add_parser('check'); c.add_argument('dir')
    a = ap.parse_args()
    build(a) if a.cmd == 'image' else check(a.dir)
