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
X = Path(__file__).resolve().parents[3]/'tools'; ROOT = X.parent; R = ROOT/'research'; SHIM = ROOT/'shim'  # ios26-audio-r1/tools/image_tool_aud1.py: int1's image_tool_int1.py (728bdd21) + blazer_audio/blazer_audio_rt (ios26-audio-r1/PLAN.md), run from here
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
UFS = 'lagunapanicdump=2 blazer_psci_reset=1 msgbuf=1048576 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=ios_system blazer_ufs_lun=0 blazer_ufs_deadline=1500'
SHIM_FLAGS = '-DTGL_UFS_POWER_MODE=1 -DTGL_UFS_PHY_CHECK=1 -DTGL_ALL_STAGES=1 -DTGL_UFS_PWM_FALLBACK=1 -DTGL_UFS_WDT_GUARD=1'
DPU_FLAGS = '-DTGL_ALL_DCS=1 -DTGL_FRAME_RUNG=3 -DTGL_DCS_HANDOFF=1 -DTGL_DCS_BRIGHT=1'
# Tensor G4 addresses tegu's start.s and early marks write with the MMU off. Writing them here hits unknown RAM on this phone.
PHONE_ROOT_SHA = '205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7'  # ios26-phone-r3, must be staged in ios_system (GOAL.md A7)
# userdata_exp.ai is a member of Android's /data since 2026-11-02: no recipe may name it as the iOS root.
# One by one, with source: PHONE-ROOT.md. Debug-off settings are out: a phone boot that needs one adds it, a one-boot change.
QEMU_RUN_DIRS = ('ios26-qemu-r1', 'ios26-blazer-r1', 'ios26-native-r1', 'ios26-overlay-r1')  # folders holding runs/<name>
PHONE_ROUTES = {'ufsroot': 'rd=ufsroot0', 'md0-mountroot': 'rd=md0 blazer_ufs_mountroot=1'}  # handoffs/kernel-ios26.md decides; md0-mountroot needs blazer's c2
PHONE_ARGS = ('debug=0x8 serial=3 cpus=1 ROUTE msgbuf=1048576 varfs=1 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=ios_system blazer_ufs_lun=0 blazer_deadline=1800 '
              'launchd_unsecure_cache=1 unentitled_ios_sim_launch=1 ignition_level=1 launchd_disable_all_timeouts=1 sweetarm64e=1 autounlock=0 '
              'interrupt-masked-debug-mode=0 blazer_panic=1 hk_usertrace=1 hk_fb_scanout=1 hk_fb_probe=1 sweetfb_noconsole=1 sweetfb_hz=60')  # masked-mode off: parent's decision 23:36, PHONE-ROOT.md
TOUCH_ARG = 'blazer_touch=1'
BOOTCPUS = ('0x200', '0x300', '0x500')  # ios26-fastcore-r1: the A725s speed-probe-r3 ran. Shim and mkadt refuse any other. --cpus up to 5 adds the other A725s
FC_FLAGS, FC_SRC = '-DTGL_FASTCORE=1', 'tgl_fastcore.c tgl_fastcore_s.S'
CPU_AUDIT_FLAGS, CPU_AUDIT_SRC = '-DTGL_CPU_AUDIT=1', 'tgl_cpu_audit.c'
# The existing cpu_fast0773 common-health plan, frozen to reviewed p30. This
# profile admits no new clock level and is separate from the lowered-trip probe.
CPU_HEALTH_KERNEL_SHA = '9bbc57038f46622e8faa2ac2d04fd595184a305d959bf8ee8c5202e825e74e55'
CPU_HEALTH_OVERLAY_SHA = '61c38161efd809bdac15f9f167e5431a4f116b54bf42c7280411480fa37bea2a'
CPU_HEALTH_ARGS = ('blazer_touch=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_cost=1 '
                   'blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 '
                   'hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 hk_crashinfo=1 blazer_battery=1 '
                   'blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 '
                   'blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 hk_ui_trace=1 '
                   'blazer_usbcon=1 blazer_usbcon_ch9=1 hk_ui=90:h,w5,l,r,x5 blazer_gov_verify=1 '
                   'blazer_gov_floors=1 blazer_thermal_required=262 blazer_gov_health=1')
CPU_HEALTH_KEYS = {'blazer_gov_verify', 'blazer_gov_floors', 'blazer_thermal_required', 'blazer_gov_health'}

def cpu_health_profile(a):
    """One source-bound cap16 health configuration, not a general token allowlist."""
    if not getattr(a, 'cpu_health', False): return False
    if (not a.phone_root or a.bootcpu != '0x200' or a.cpus != 5 or
        a.kernel_sha != CPU_HEALTH_KERNEL_SHA or a.phone_route != 'md0-mountroot' or
        a.qemu_run != 'overlay-1' or a.canvas != PHONE_CANVAS or
        getattr(a, 'cpu_order', None) is not None or
        getattr(a, 'window_base', None) != '0x882000000' or a.phone_deadline != 300 or
        not a.var_overlay or a.var_overlay_sha != CPU_HEALTH_OVERLAY_SHA):
        die('--cpu-health requires reviewed p30, five A725s/bootcpu0x200, window882, pinned overlay, canvas and deadline300; docs/CPU.md')
    if any(getattr(a, k, None) for k in ('cpu_audit', 'cpu_order', 'first_boot', 'second_boot',
            'test_kernel', 'preflight', 'touch', 'dpu', 'md0', 'md1', 'args', 'gamut',
            'legacy_base', 'fullcheck', 'readback', 'readback_sha', 'persist',
            'persist_table', 'expect_test_block', 'soak_whole')) or getattr(a, 'soak', None) is not None or a.route != 'ufs':
        die('--cpu-health cannot combine another profile or experiment')
    if a.phone_args:
        phone_extra(a.phone_args, cpu_health=True)
    a.phone_args = CPU_HEALTH_ARGS
    return True

def cpu_health_line():
    c = PHONE_ARGS.replace('ROUTE', PHONE_ROUTES['md0-mountroot'])
    return set_cpus(c, 5).replace('blazer_deadline=1800', 'blazer_deadline=300') + ' ' + CPU_HEALTH_ARGS + ' blazer_bootcpu=0x200'

def check_cpu_health(m, blob, payload):
    """Bind the profile to actual ADT/payload bytes and the pinned inputs again."""
    record = m.get('cpu_health')
    actual_line = payload[mkpayload.CMDLINE:mkpayload.SEG_TABLE].split(b'\0', 1)[0].decode('ascii', errors='replace')
    if not record:
        if any(t.split('=')[0] in CPU_HEALTH_KEYS for t in (m['cmdline'] + ' ' + actual_line).split()):
            die('CPU health tokens without the dedicated profile receipt')
        return
    expected = dict(version=1, cap=16, required_mask=262, high_clock=False,
                    stepdown_probe=False, physical_acceptance=False)
    if (not isinstance(record, dict) or record != {**expected, 'kernel_path': record.get('kernel_path')} or
        any(type(record[k]) is not type(v) for k, v in expected.items()) or
        not isinstance(record['kernel_path'], str) or not record['kernel_path']):
        die('CPU health profile receipt differs')
    if (m['mach'] != CPU_HEALTH_KERNEL_SHA or m['bootcpu'] != '0x200' or m.get('cpus') != 5 or
        m.get('cpu_order') is not None or not m.get('phone_root') or m.get('route') != 'ufs' or
        m['cmdline'] != cpu_health_line() or actual_line != m['cmdline'] or
        m['cmdline_bytes'] != len(cpu_health_line().encode())):
        die('CPU health kernel/topology/command line differs')
    facts = adt_facts(blob)
    nodes = next(n for n in ADT.parse(blob)[0].children if n.name == 'cpus').children
    regs = [struct.unpack('<I', n.prop('reg'))[0] for n in nodes]
    if (facts != m['adt_facts'] or facts['dram'] != ['0x882000000', '0x100000000'] or
        facts['canvas'] != [1125, 2511] or facts['boot_reg'] != 0x200 or
        regs != [0x200, 0x300, 0x400, 0x500, 0x600] or m.get('window_base') != '0x882000000' or
        [n.prop('state') for n in nodes] != [b'running\0'] + [b'stopped\0'] * 4 or
        [struct.unpack('<I', n.prop('cpu-id'))[0] for n in nodes] != list(range(5))):
        die('CPU health ADT/memory context differs')
    check_cpu_line(blob, m['cmdline'])
    kernel = pin((Path(record['kernel_path']), CPU_HEALTH_KERNEL_SHA))
    ov = m.get('var_overlay')
    if not isinstance(ov, dict) or ov.get('sha256') != CPU_HEALTH_OVERLAY_SHA:
        die('CPU health overlay receipt differs')
    overlay = pin((Path(ov['path']), CPU_HEALTH_OVERLAY_SHA))
    # Rebuild through the real payload producer: a manifest assertion alone must
    # not hide a different kernel, line, overlay or memory placement in the image.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        adt_file = Path(tmp)/'laguna.adt'; adt_file.write_bytes(blob)
        try: rebuilt, _ = mkpayload.build(kernel, adt_file, cpu_health_line(), None, None, False, overlay)
        except ValueError as e: die(str(e))
    if rebuilt != payload: die('CPU health embedded payload differs from pinned inputs')

def cpu_audit_profile(a):
    """Only cpu0 register reads on the proven five-A725, 533 MHz route. docs/CPU.md."""
    if not getattr(a, 'cpu_audit', False): return False
    if (not a.phone_root or a.bootcpu != '0x200' or a.cpus != 5 or
        getattr(a, 'cpu_order', None) is not None or getattr(a, 'phone_deadline', None) != 300 or
        a.first_boot or a.second_boot or a.test_kernel or a.preflight):
        die('--cpu-audit needs --phone-root --bootcpu 0x200 --cpus 5 --phone-deadline 300')
    extra = set(phone_extra(a.phone_args))
    allowed = {'blazer_thermal=2', 'blazer_thermal_panic_c=70', 'blazer_smp_report=1',
               'blazer_smp_test=1', 'blazer_usbcon=1', 'blazer_usbcon_ch9=1'}
    if not extra <= allowed or not {'blazer_thermal=2', 'blazer_thermal_panic_c=70',
                                    'blazer_smp_report=1', 'blazer_smp_test=1'} <= extra:
        die('--cpu-audit needs armed thermal70 + SMP report/self-test, baseline clocks and no other experiments')
    if a.touch or a.var_overlay or a.var_overlay_sha or a.args or a.md0 or a.md1 or a.dpu:
        die('--cpu-audit: no touch/overlay/other profile')
    return True
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
                 'blazer_wifi': r'blazer_wifi=1', 'blazer_wifi_stage': r'blazer_wifi_stage=[0-8]', 'blazer_wifi_join': r'blazer_wifi_join=1', 'blazer_wifi_run': r'blazer_wifi_run=[0-9]{1,3}', 'blazer_wifi_gen': r'blazer_wifi_gen=[1-3]', 'blazer_wifi_delay': r'blazer_wifi_delay=[0-9]{1,3}', 'blazer_wifi_end': r'blazer_wifi_end=[0-9]{1,4}', 'blazer_wifi_hold': r'blazer_wifi_hold=1', 'blazer_wifi_aux': r'blazer_wifi_aux=1', 'blazer_wifi_force': r'blazer_wifi_force=1',
                 'blazer_usbcon': r'blazer_usbcon=[12]', 'blazer_usbcon_input': r'blazer_usbcon_input=1', 'blazer_touch': r'blazer_touch=1', 'blazer_touch_bars': r'blazer_touch_bars=1', 'touch_flip': r'touch_flip=[123]',
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
PHONE_ALLOWED.update({'blazer_aks_trace': r'blazer_aks_trace=1', 'hk_present_trace': r'hk_present_trace=1'})
PHONE_ALLOWED.update({'blazer_battery_chg': r'blazer_battery_chg=1', 'blazer_aoc': r'blazer_aoc=1'})  # handoffs/battery.md: the charger's frames, off unless asked; parent, aoc
# A7 (GOAL.md): the tokens phone-p32-combined-ui-r1 booted with physically (research/ios26-opt-20261102/combined_p32/image-build.json),
# same patterns as research/ios26-bootchain-r1/image_tool.py, which built that image. Persistence stays refused in build().
PHONE_ALLOWED.update({'hk_fb_refresh': r'hk_fb_refresh=(60|120)', 'hk_bright': r'hk_bright=[0-9]{2,3}', 'blazer_aks_log': r'blazer_aks_log=1', 'blazer_aks_wrap': r'blazer_aks_wrap=1',
                      'blazer_aks_usersession': r'blazer_aks_usersession=1', 'blazer_persona_log': r'blazer_persona_log=1',  # research/ios26-apps-r1/usersession/PLAN.md
                      'blazer_gov': r'blazer_gov=1', 'blazer_gov_cap': r'blazer_gov_cap=(18|16|13)', 'blazer_gov_stages': r'blazer_gov_stages=(1|3|5|7|9|11|13|15)',
                      'blazer_gov_b': r'blazer_gov_b=(3[0-9]|4[0-9]|5[0-5])', 'blazer_thermal_fast': r'blazer_thermal_fast=1',
                      'blazer_battery_status': r'blazer_battery_status=1', 'blazer_battery_receipt': r'blazer_battery_receipt=1'})
# research/ios26-gpu-r1/PLAN.md: stage 1 plus a read-only register survey (blazer_gpu=3). Not 1 or 2 here; tipc refuses any blazer_gpu.
PHONE_ALLOWED.update({'blazer_gpu': r'blazer_gpu=3'})
# research/ios26-phaseb-r1/live/SCREEN.md: the glass into the dumped ramoops zone; DBG3's usbcon framebuffer snapshot.
PHONE_ALLOWED.update({'hk_screen': r'hk_screen=(0|1|[1-9][0-9]|[1-9][0-9]{2,3})', 'hk_screen_box': r'hk_screen_box=[01]',
                      'blazer_usbcon_snap': r'blazer_usbcon_snap=1'})
# research/ios26-phaseb-r1/live/USTACK.md: read-only kernel sampler, user stacks of up to 4 named processes on the console.
PHONE_ALLOWED.update({'hk_ustack': r'hk_ustack=[A-Za-z0-9._-]{1,16}(,[A-Za-z0-9._-]{1,16}){0,3}', 'hk_ustack_s': r'hk_ustack_s=([1-9]|[1-9][0-9]|[1-5][0-9][0-9]|600)',
                      'hk_ustack_n': r'hk_ustack_n=[1-9][0-9]{0,3}', 'hk_ustack_max': r'hk_ustack_max=[1-9][0-9]{0,5}'})
# research/ios26-phaseb-r1/live/NET.md: kernel IPv4 192.168.77.2/24 on en2 over the USB gadget (CDC-ECM 1209:0003), no default route.
PHONE_ALLOWED.update({'blazer_usbnet': r'blazer_usbnet=1', 'blazer_usbnet_direct': r'blazer_usbnet_direct=1'})
PHONE_ALLOWED.update({'blazer_netstack': r'blazer_netstack=1'})  # research/ios26-phaseb-r1/configd/FIX.md: IONetworkStack alone
# research/ios26-audio-r1/PLAN.md A1: stage-1 audio on int1's kernel. blazer_audio=3: hkcover puts the overlay's group 24 (BlazerAudio.driver)
# and 25 (D421 tunings) over the root's HAL and tunings directories and makes /dev/blazer-audio, which caps and discards (no sink, no amp,
# no AoC). blazer_audio_rt=1: audiomxd's own 1200-tick realtime bootstrap raised to XNU's minimum (0903). blazer_audio_pcm stays refused.
PHONE_ALLOWED.update({'blazer_audio': r'blazer_audio=3', 'blazer_audio_rt': r'blazer_audio_rt=1'})
PHONE_EXACT_INT1 = ('blazer_power_key=1', 'blazer_key_delivery=1', 'blazer_haptic_tap=1')  # research/ios26-phaseb-r1/pwr/PLAN.md
DROP_DIAG = ('hk_fb_probe=1', 'hk_usertrace=1')  # --drop-diag: base-line diagnostics a full line may give up (pwr/PLAN.md; int/INT1.md)
PHONE_CANVAS = '1125x2511'  # native's request, the only other size the phone ADT can have
# validation_disables: kconfig.md, osfmk/kern/debug.c. atm_diagnostic_config: mine.md, osfmk/atm/atm.c:60. hk_fb_*: render's names.
PHONE_EXACT = ('blazer_fast_first=1', 'blazer_smp_report=1', 'blazer_smp_report=2', 'blazer_smp_test=1', 'blazer_ssbs=1', 'blazer_ssbs=3', 'validation_disables=0x39d64', 'atm_diagnostic_config=0x400', 'hk_fb_scale=1', 'hk_fb_scale=2', 'hk_fb_filter=1', 'blazer_ufs_multi=1', 'blazer_cs_nohash=1', 'blazer_rtc=1', 'blazer_keys=1', 'blazer_haptic=1', 'blazer_haptic=3', 'hk_bench=1', 'hk_amu=1', 'hk_pmu=1', 'hk_pmu=2', 'hk_fb_fast=1', 'blazer_ic_va=1', 'hk_fb_bench=2', 'blazer_ufs_spin_us=300', 'blazer_ufs_cost=1', 'blazer_ufs_hold=1', 'blazer_battery=1', 'blazer_battery=2', 'hk_fb_period=1', 'hk_fb_te=1', 'hk_fb_te=2', 'hk_panel_hz=120', 'hk_panel_hz=60', 'hk_panel_hz=30', 'hk_panel_hz=10', 'hk_panel_off=1')  # last two: mine.md
PHONE_EXACT += ('blazer_rtc_bounds=1',)  # A7: p32's line, as research/ios26-bootchain-r1/image_tool.py
PHONE_EXACT += PHONE_EXACT_INT1
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
def phone_extra(text, *, cpu_health=False):
    """Validated tokens for --phone-args. Refuses anything off the list, and repeats: PE_parse takes one value."""
    toks = (text or '').split(); names = [t.split('=', 1)[0] for t in toks]
    if len(set(names)) != len(names): die(f'repeated token in --phone-args: {text}')
    if cpu_health:
        if sorted(toks) != sorted(CPU_HEALTH_ARGS.split()): die('--cpu-health arguments differ from the frozen common configuration')
        return toks
    for t, n in zip(toks, names):
        if t not in PHONE_EXACT and not (n in PHONE_ALLOWED and re.fullmatch(PHONE_ALLOWED[n], t)): die(f'--phone-args: {t} is not on the list')
    if 'blazer_usb_readback=1' in toks:
        if 'blazer_usbcon=1' not in toks: die('readback requires blazer_usbcon=1')
        if any(n.startswith('blazer_persist') for n in names): die('readback capture cannot enable persistence writes')
    return toks
# --persist-ios-data: the one gate for blazer_persist on the phone (research/ios26-dualboot-r8/ios-data-persist/PHYSICAL-PLAN.md).
# Admitted only for this kernel: release tree 7227fe7 = dd000c8 (persist writes only to the GPT-resolved ios_data) + the
# ios_system root view. QEMU NEGATIVE-r1 ran this tree plus the fake-LUN patch (off without blazer_ufs_fake_lun); A7 booted
# this exact kernel from ios_system physically. Mode 1 and a period in the kernel's own range (15..3600) only.
PERSIST_KERNEL_SHA = 'ddf874fb41cf4871f39336a1bb3a7c77686d6f075e2fd8b7260a86707bd0b5f3'  # research/ios26-dualboot-r8/rootview/kernel.rootview
PERSIST_KERNEL_NEEDS = (b'blazer-persist: ios_data at LBA', b'refused root "%s": userdata')
PERSIST_KERNEL_REFUSED = {
    '052d00f8680e1632fb680f62ecf2369457d10f82a3e4384eb93f6203606eafc8': 'kernel.p32-iosdata-dd000c8 predates 7227fe7: its root view is pinned to the 8 GiB userdata_exp.ai extent, so it cannot root on ios_system (A7-READY section 3)',
    '3563a0406a24d51080f1afd41a22447a5baf57d243ca062e264d28b57f5b6e7e': 'kernel.fakelun-b228c4f carries the QEMU fake-LUN mode: QEMU only'}
PERSIST_PERIOD = r'blazer_persist_period=(1[5-9]|[2-9][0-9]|[1-9][0-9]{2}|[12][0-9]{3}|3[0-5][0-9]{2}|3600)'
def persist_ios_data(a, c):
    """None unless --persist-ios-data. Then every condition or die; returns the record for the manifest."""
    if not getattr(a, 'persist_ios_data', False): return None
    why = PERSIST_KERNEL_REFUSED.get(a.kernel_sha)
    if why: die(f'--persist-ios-data: {why}')
    if a.kernel_sha != PERSIST_KERNEL_SHA or sha(a.kernel) != PERSIST_KERNEL_SHA: die(f'--persist-ios-data: kernel must be {PERSIST_KERNEL_SHA} (kernel.rootview, dd000c8 + 7227fe7)')
    buf = Path(a.kernel).read_bytes()
    if any(t not in buf for t in PERSIST_KERNEL_NEEDS) or b'blazer_ufs_fake_lun' in buf: die('--persist-ios-data: kernel lacks the ios_data writer or the userdata refusal, or carries the QEMU fake-LUN mode')
    if not a.phone_root or a.preflight or a.test_kernel or a.first_boot or a.second_boot or a.soak is not None or a.fullcheck or a.readback \
            or getattr(a, 'persist', None) or getattr(a, 'persist_table', None) or getattr(a, 'expect_test_block', None):
        die('--persist-ios-data goes with --phone-root alone: no preflight, test kernel, first/second boot, soak, fullcheck, readback or --persist')
    toks = c.split()
    roots = [t for t in toks if t.startswith('blazer_ufs_root=')]
    if roots != ['blazer_ufs_root=ios_system'] or toks.count('blazer_ufs_lun=0') != 1: die(f'--persist-ios-data needs exactly blazer_ufs_root=ios_system on LUN 0, line has {roots}')
    if any(t.startswith(('blazer_ufs_test', 'blazer_ufs_fake', 'rootrw', 'rw', 'blazer_usb_readback')) for t in toks): die('--persist-ios-data: a test, fake, read-write or readback token is on the line')
    p = [t for t in toks if re.match(r'blazer_persist(_\w+)?=', t)]
    if 'blazer_persist=1' not in p: die('--persist-ios-data needs blazer_persist=1 in --phone-args')
    bad = [t for t in p if t != 'blazer_persist=1' and not re.fullmatch(PERSIST_PERIOD, t)]
    if bad or len(p) != len(set(t.split('=')[0] for t in p)): die(f'--persist-ios-data admits blazer_persist=1 and blazer_persist_period=15..3600 only, not {bad or p}')
    return dict(kernel_sha256=PERSIST_KERNEL_SHA, tokens=p, target='ios_data', root='ios_system', plan='research/ios26-dualboot-r8/ios-data-persist/PHYSICAL-PLAN.md')
def check_persist(m):
    """check: a line with blazer_persist must carry the gate's record, for the pinned kernel and ios_system, and agree with it."""
    toks = m.get('cmdline', '').split(); p = [t for t in toks if re.match(r'blazer_persist(_\w+)?=', t)]; rec = m.get('persist_ios_data')
    if not p and not rec: return
    if not rec or m.get('mach') != PERSIST_KERNEL_SHA or rec.get('kernel_sha256') != PERSIST_KERNEL_SHA or rec.get('tokens') != p \
            or [t for t in toks if t.startswith('blazer_ufs_root=')] != ['blazer_ufs_root=ios_system'] or 'blazer_persist=1' not in p:
        sys.exit('MISMATCH persist: blazer_persist on the line without the --persist-ios-data record, kernel or ios_system root')
    print('persist ios_data:', ' '.join(p), 'kernel', PERSIST_KERNEL_SHA[:16])
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
        return ('debug=0x8 serial=3 cpus=1 rd=md0 blazer_ufs_mountroot=1 msgbuf=1048576 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=ios_system '
                f'blazer_ufs_lun=0 blazer_ufs_test=1 blazer_ufs_fullcheck={a.soak} blazer_deadline=1500 blazer_panic=1')
    if a.phone_root:  # read-only HFSX root on UFS, RAM /private/var from varfs: PHONE-ROOT.md
        return PHONE_ARGS.replace('ROUTE', PHONE_ROUTES[a.phone_route]) + (' ' + TOUCH_ARG if getattr(a, 'touch', False) else '') + ''.join(' ' + t for t in phone_extra(getattr(a, 'phone_args', None), cpu_health=getattr(a, 'cpu_health', False)))
    if a.first_boot:  # blazer's contract; the root was userdata_exp.ai on LUN 0 in 20261101-201914-ufs-root-r2, now ios_system
        return 'debug=0x8 serial=3 cpus=1 rd=md0 msgbuf=1048576 blazer_ufs=2 blazer_ufs_live=1 blazer_ufs_root=ios_system blazer_ufs_lun=0 blazer_ufs_test=1 ' + (f"blazer_ufs_deadline=1200 blazer_ufs_fullcheck={2 if getattr(a, 'persist_table', None) else 1}" + (f" blazer_persist={a.persist}" if getattr(a, 'persist', None) else '') if getattr(a, 'fullcheck', None) else 'blazer_ufs_deadline=300') + ' unentitled_ios_sim_launch=1' + (' ' + SECOND_ARGS if a.second_boot else '')
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
    toks = [t for t in phone_extra(a.phone_args, cpu_health=getattr(a, 'cpu_health', False)) if t.startswith('hk_overlay=')]
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
    health = cpu_health_profile(a)
    audit = cpu_audit_profile(a)
    if a.soak is not None:
        if not name.startswith('soak-') or a.first_boot or a.second_boot or a.phone_root or a.dpu or a.md0 or a.md1 or a.args or a.route != 'ufs': die('--soak: name soak-*, no other profile')
        if b'blazer-ufs-fullcheck: pass' not in Path(a.kernel).read_bytes(): die('kernel has no soak passes')
    ov = check_overlay(a)
    # Two multi-core shapes, never both. --cpu-order: XNU boots on cpu0, cores in that order, smp's. --bootcpu --cpus: boots on an A725, cpu0 parked and not in the ADT, fastcore's.
    order = cpu_order(a.cpu_order) if getattr(a, 'cpu_order', None) is not None else None
    if order:
        if a.bootcpu: die('--cpu-order and --bootcpu: --bootcpu parks cpu0, which --cpu-order needs. For a fast boot core, --bootcpu --cpus. handoffs/smp.md')
        if a.cpus != 1: die('--cpu-order sets cpus=N from its length: no --cpus')
    if 'blazer_fast_first=1' in phone_extra(getattr(a, 'phone_args', None), cpu_health=health) and not order: die('blazer_fast_first=1 goes with --cpu-order: on --bootcpu --cpus the cores are alike, handoffs/fastcore.md section 0')
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
        for t in phone_extra(a.phone_args, cpu_health=health):
            if t.split('=')[0].encode() not in buf: die(f'kernel does not read {t}')
        extra = phone_extra(a.phone_args, cpu_health=health)
        # research/ios26-connectivity-r1/wifi/PLAN.md W1: THIS TRANSMITS. Stage 8 with the owner's network in overlay group 26, never applied
        if 'blazer_wifi_join=1' in extra:
            if not {'blazer_wifi=1', 'blazer_wifi_stage=8'} <= set(extra): die('blazer_wifi_join=1 needs blazer_wifi=1 blazer_wifi_stage=8')
            if not ov or 26 not in ov['groups'] or ov['mask'] >> 26 & 1: die('blazer_wifi_join=1 needs an overlay holding group 26 (compose_wifi_join.py) and an hk_overlay mask without bit 26')
            if b'the image holds a network' not in buf: die('kernel has no Wi-Fi network reader')
        elif any(t.startswith('blazer_wifi_run=') for t in extra): die('blazer_wifi_run goes with blazer_wifi_join=1')
        if any(x.startswith('blazer_usbnet') for x in extra):
            if not {'blazer_usbnet=1', 'blazer_usbnet_direct=1'} <= set(extra) or not any(x.startswith('blazer_usbcon=') for x in extra): die('USB network: blazer_usbnet=1 blazer_usbnet_direct=1 with blazer_usbcon (NET.md)')
            if b'arp/icmp frames' not in buf: die('kernel has no blazer_usbnet ARP/ICMP log (hk-usbnet-dbg1)')
        if any(x.startswith('hk_ustack') for x in extra) and b'HK USTACK: every %u s' not in buf: die('kernel has no hk_ustack (hk-ustack-dbg4)')
        if any(x.startswith('hk_screen') for x in extra) and b'HK SCREEN: on, record' not in buf: die('kernel has no hk_screen (hk-screen-dbg5)')
        if 'blazer_usbcon_snap=1' in extra and b'blazer_usbcon_snap' not in buf: die('kernel has no usbcon snapshot (DBG3 0001)')
        if 'blazer_keys=1' in extra and b'blazer-keys: polling pads' not in buf: die('kernel holds keys until keys-probe-r1 passes: handoffs/cpmlock.md')
        if 'blazer_power_key=1' in extra and 'blazer_keys=1' not in extra: die('blazer_power_key=1 goes with blazer_keys=1')
        if 'blazer_key_delivery=1' in extra and ('blazer_keys=1' not in extra or 'blazer_power_key=1' not in extra or b'blazer-keys: delivery requires reviewed power lifecycle' not in buf):
            die('blazer_key_delivery=1: needs blazer_keys=1 blazer_power_key=1 and a kernel built with BLAZER_KEY_DELIVERY=1 (pwr/PLAN.md)')
        if 'blazer_haptic_tap=1' in extra and (any(t.startswith('blazer_haptic=') for t in extra) or b'blazer-haptic: tap feedback on' not in buf or b'native ROM service ready' not in buf):
            die('blazer_haptic_tap=1: alone (it implies the ID-only stage and the service) and a kernel built with BLAZER_HAPTIC_SERVICE=1 (pwr/PLAN.md)')
        if 'blazer_netstack=1' in extra and b'blazer-netstack: published alone' not in buf: die('kernel has no blazer_netstack (hk-netstack-cfg1, configd/FIX.md)')
        if 'blazer_audio=3' in extra:  # ios26-audio-r1/PLAN.md A1
            if not ov or not {24, 25} <= set(ov['groups']): die('blazer_audio=3 needs an overlay holding groups 24 and 25 (aud1_overlay.py): hkcover panics without them')
            if ov['mask'] >> 24 & 3: die('blazer_audio=3: hk_overlay must not hold bits 24/25, hkcover groups are never applied to /private/var')
            if 'varfs=1' not in PHONE_ARGS.split(): die('blazer_audio=3 needs varfs=1 on the line')
            for s_ in (b'hkcover: blazer_audio=0x%x needs varfs=1', b'/private/var/hkcover/hal', b'blazer-audio: /dev/blazer-audio, cap %u of 32768, %s', b'_blazer_audio_pcm_bind'):
                if s_ not in buf: die(f'kernel lacks stage-1 audio ({s_.decode()}): 0900/1144/1145')
        if 'blazer_audio_rt=1' in extra:
            if 'blazer_audio=3' not in extra: die('blazer_audio_rt=1 goes with blazer_audio=3')
            if b'hk-audio-rt: audiomxd bootstrap 1200 -> %u ticks' not in buf: die('kernel has no audio RT bootstrap adapter (0903)')
        if any(t.startswith('blazer_audio_pcm') for t in extra): die('blazer_audio_pcm: no AoC consumer exists; refused (ios26-audio-r1/PLAN.md)')
        if 'blazer_netstack=1' in extra and any(t.startswith(('blazer_usbnet=', 'blazer_wifi_net=')) for t in extra): die('blazer_netstack=1 is the stand-in alone: not with blazer_usbnet/blazer_wifi_net')
        if any(t.startswith('blazer_thermal_panic_c=') for t in extra) and 'blazer_thermal=2' not in extra: die('blazer_thermal_panic_c needs blazer_thermal=2')
        if getattr(a, 'phone_deadline', None) not in (None, 300, 1800, 3600): die('--phone-deadline: 300, 1800 or 3600')
        if getattr(a, 'phone_deadline', None) == 3600 and ('blazer_thermal=2' not in extra or a.bootcpu): die('--phone-deadline 3600: power.md, needs the armed guard, blazer_thermal=2, and no --bootcpu')
        if getattr(a, 'phone_deadline', None) == 3600 and order: die('--phone-deadline 3600: power.md, not with --cpu-order')
        if getattr(a, 'phone_deadline', None) == 1800 and (a.bootcpu or order) and (order or a.cpus != 1 or 'blazer_thermal=1' not in extra): die('--phone-deadline 1800 on a fast core: limits.md P1b, one A725 with blazer_thermal=1. Several cores stay at 900')
        if a.phone_route == 'md0-mountroot' and b'rooting on ufsroot0' not in buf: die('kernel lacks the md0-mountroot route (blazer 0530)')
    if a.touch and not a.phone_root: die('--touch goes with --phone-root')
    if a.phone_args and not a.phone_root: die('--phone-args goes with --phone-root')
    if a.touch and 'blazer_touch' in [t.split('=')[0] for t in phone_extra(a.phone_args, cpu_health=health)]: die('blazer_touch given twice')
    p_mode, p_table, p_expect = getattr(a, 'persist', None), getattr(a, 'persist_table', None), getattr(a, 'expect_test_block', None)
    if p_mode or p_table or p_expect:  # handoffs/persist.md: the fullcheck line only
        if not (a.first_boot and getattr(a, 'fullcheck', None)) or a.second_boot: die('--persist, --persist-table, --expect-test-block go with --first-boot --fullcheck')
        if p_mode == 2 and not p_table: die('--persist 2 writes the test block: the pass after it must skip the table')
        if (p_mode or p_table) and b'blazer_persist' not in Path(a.kernel).read_bytes(): die('kernel has no blazer_persist')
        if p_expect and (p_mode or p_table): die('--expect-test-block is for a kernel with no mask, after the test')
    epoch = int(time.time()); c = cmdline(a, epoch)
    if 'userdata_exp.ai' in c: die('command line names userdata_exp.ai, a member of Android /data: bind ios_system (GOAL.md A7)')
    persist = persist_ios_data(a, c)  # None unless --persist-ios-data, which dies on anything but its one profile
    if re.search(r'(^|\s)blazer_persist(_\w+)?=', c) and not persist: die('blazer_persist is bound at compile time to LBA 2500838 (userdata_exp.ai, now Android /data): no persistence until the ios_data writer exists (GOAL.md A7)')
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
    if audit: c += ' blazer_cpu0_audit=1'
    for t in getattr(a, 'drop_diag', None) or []:
        if t not in DROP_DIAG or not a.phone_root: die(f'--drop-diag: one of {DROP_DIAG}, with --phone-root')
        if c.split().count(t) != 1: die(f'--drop-diag: {t} is not once on the line')
        c = ' '.join(x for x in c.split() if x != t)
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
    if audit:
        env['EXTRA_CFLAGS'] += ' ' + CPU_AUDIT_FLAGS
        env['TGL_EXTRA_SRC'] += ' ' + CPU_AUDIT_SRC
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
    if audit: want += ['tgl_cpu_audit_configure', 'tgl_cpu_audit_prepare']
    for sym in want:
        if not re.search(rf'\s{sym}$', syms, re.M): die(f'shim lacks {sym}')
        if health and not re.search(rf'^[0-9a-fA-F]+ [Tt] {sym}$', syms, re.M):
            die(f'CPU health shim lacks executable text for {sym}')
    if not a.dpu and re.search(r'\stgl_dcs_guarded$', syms, re.M): die('DPU stage present though off')
    if not a.bootcpu and re.search(r'\stgl_fc_entry$', syms, re.M): die('fastcore present though off')
    if not audit and re.search(r'\stgl_cpu_audit_prepare$', syms, re.M): die('CPU audit present though off')
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
               shim_copy=tree(SHIM), tools={n: sha(Path(__file__).resolve() if n == 'image_tool.py' else X/n) for n in ('adt.py', 'image_tool.py', 'mkadt.py', 'mkbootimg.py', 'mkpayload.py')})
    if window != PHYS: rec['window_base'] = hex(window)
    if getattr(a, 'drop_diag', None): rec['dropped_diag'] = list(a.drop_diag)
    if persist: rec['persist_ios_data'] = persist
    if audit: rec['cpu_audit'] = dict(mode=1, core=0, read_only=True, a520_support_accepted=False)
    if many: rec.update(cpus=len(order) if order else a.cpus, **({'cpu_order': order} if order else {}))  # no shape, no new keys
    if health:
        rec['cpu_health'] = dict(version=1, cap=16, required_mask=262, high_clock=False,
                                stepdown_probe=False, physical_acceptance=False, kernel_path=str(Path(a.kernel).resolve()))
        check_cpu_health(rec, blob, raw)
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


def _cpu_artifact_require(condition, reason):
    if not condition: die('CPU health artifact: ' + reason)


def _cpu_check_elf(data):
    _cpu_artifact_require(data[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', data, 18)[0] == 183,
            'shim is not AArch64 ELF64 LE')
    shoff = struct.unpack_from('<Q', data, 40)[0]
    entsize, number, namesidx = struct.unpack_from('<3H', data, 58)
    _cpu_artifact_require(entsize == 64 and shoff+number*64 <= len(data), 'invalid ELF sections')
    rows = [struct.unpack_from('<II4QII2Q', data, shoff+i*64) for i in range(number)]
    names = data[rows[namesidx][4]:rows[namesidx][4]+rows[namesidx][5]]
    sections, symbols = {}, {}
    for r in rows:
        end = names.find(b'\0', r[0])
        name = names[r[0]:end].decode()
        if r[1] != 8:
            _cpu_artifact_require(r[4]+r[5] <= len(data), 'ELF section exceeds file')
            sections[name] = dict(data=data[r[4]:r[4]+r[5]], address=r[3], flags=r[2])
        if r[1] == 2:
            strings = rows[r[6]]
            strings = data[strings[4]:strings[4]+strings[5]]
            for at in range(r[4], r[4]+r[5], 24):
                ix, info, _, si, va, sz = struct.unpack_from('<IBBHQQ', data, at)
                end = strings.find(b'\0', ix)
                nm = strings[ix:end].decode()
                if nm and si and si < number:
                    sr = rows[si]
                    start = sr[4]+va-sr[3]
                    symbols[nm] = dict(address=va, size=sz, data=data[start:start+sz], info=info,
                                       executable=bool(sr[2] & 4),first_instruction=data[start:start+4])
    return sections, symbols


def _cpu_check_elf_text(symbols,names):
    for name in names:
        _cpu_artifact_require(name in symbols, 'shim executable definition missing: '+name)
        s = symbols[name]
        # Hand-written assembly entries may be GLOBAL/NOTYPE with size zero.
        # Section permissions and actual instruction bytes, not type/size alone,
        # establish that they are executable definitions.
        _cpu_artifact_require(s['info'] & 15 in (0,2) and s['executable'] and len(s['first_instruction']) == 4 and
                any(s['first_instruction']), 'shim executable text absent: '+name)


def _cpu_check_literal(code, wanted):
    """Find one local MOVZ/MOVK literal sequence, allowing interleaved registers.

    This identifies compiled literals only, not runtime register values/dataflow.
    The pinned full executable and embedded section checks provide byte identity.
    """
    work = {}
    for off in range(0, len(code)-3, 4):
        ins = struct.unpack_from('<I', code, off)[0]
        kind = ins & 0x7f800000
        reg, shift = ins & 31, ((ins >> 21) & 3)*16
        if kind == 0x52800000:  # MOVZ W/X
            work[reg] = [((ins >> 5) & 0xffff) << shift, off, [off]]
        elif kind == 0x72800000 and reg in work and off-work[reg][1] <= 64:
            work[reg][0] = (work[reg][0] & ~(0xffff << shift)) | (((ins >> 5) & 0xffff) << shift)
            work[reg][2].append(off)
        else:
            continue
        if work[reg][0] == wanted:
            return dict(value=hex(wanted), register=reg, instruction_offsets=work[reg][2])
    die(f'CPU health artifact: compiled shim literal absent: {hex(wanted)}')


def check_cpu_health_artifact(directory, manifest, payload):
    """Bind the frozen profile to the loader-selected boot bytes and shim IDs.

    ELF/literal checks reuse this project's MIT GPT-context preflight. Literal
    presence is compiled identity evidence, not runtime control-flow proof.
    """
    if not manifest.get('cpu_health'): return
    require = _cpu_artifact_require
    raw = (directory/'boot.img').read_bytes()
    elf_bytes = (directory/'shim.elf').read_bytes()
    require(len(raw) >= 4096 and raw[:8] == b'ANDROID!', 'Android header missing')
    require(struct.unpack_from('<I', raw, 40)[0] == 4 and
            struct.unpack_from('<I', raw, 20)[0] == 1584, 'expected bounded Android v4 header')
    kernel_bytes = struct.unpack_from('<I', raw, 8)[0]
    require(64 <= kernel_bytes <= len(raw)-4096, 'kernel extent exceeds image')
    kernel = raw[4096:4096+kernel_bytes]
    require(kernel[56:60] == b'ARM\x64', 'ARM64 Image header missing')
    require(len(elf_bytes) >= 64, 'truncated ELF header')
    try:
        sections, symbols = _cpu_check_elf(elf_bytes)
        _cpu_check_elf_text(symbols, ('_head','tgl_stamp_boot_entry','shim_main'))
        require('_end' in symbols and symbols['_head']['address'] == 0, 'shim end/head absent')
        end = symbols['_end']['address']
        require(64 <= end <= kernel_bytes-16, 'shim envelope outside kernel')
        require(kernel[end:end+8] == b'TEGUPLD1', 'loader-selected envelope missing')
        length = struct.unpack_from('<Q',kernel,end+8)[0]
        require(length == len(payload) and end+16+length == kernel_bytes and
                struct.unpack_from('<Q',kernel,16)[0] == kernel_bytes,
                'ARM64 Image/envelope extent differs')
        require(kernel[end+16:end+16+length] == payload, 'embedded payload differs from checked sidecar')
        phoff = struct.unpack_from('<Q',elf_bytes,32)[0]
        stride,count = struct.unpack_from('<HH',elf_bytes,54)
        require(stride == 56 and 0 < count <= 64 and phoff+stride*count <= len(elf_bytes), 'invalid ELF load table')
        loads = 0
        for i in range(count):
            kind,flags,offset,address,pa,size,memsize,align = struct.unpack_from('<II6Q',elf_bytes,phoff+i*stride)
            if kind != 1: continue
            require(size <= memsize and offset+size <= len(elf_bytes) and address+memsize <= end, 'ELF load outside shim')
            actual = bytearray(kernel[address:address+size])
            expected = elf_bytes[offset:offset+size]
            if address <= 16 and address+size >= 24:
                actual[16-address:24-address] = expected[16-address:24-address]
            require(bytes(actual) == expected, 'embedded shim differs from initialized ELF load')
            loads += 1
        require(loads > 0, 'ELF has no loads')
        ids = manifest.get('ids')
        require(isinstance(ids,dict) and ids == json.loads((directory/'ufs-ids.json').read_text()), 'manifest/build identities disagree')
        require(type(ids.get('handoff')) is int and ids['handoff'] == 1, 'wrong handoff identity')
        require(isinstance(ids.get('stamp_nonce'),str) and re.fullmatch(r'0x[0-9a-f]{16}',ids['stamp_nonce']), 'invalid stamp nonce')
        nonce,epoch = int(ids['stamp_nonce'],16),int(ids['epoch'],16)
        require(0 < nonce < 2**64 and 0 < epoch < 2**64, 'nonce/epoch outside bounds')
        record = bytes.fromhex(ids['record_nonce'])
        require(len(record) == 16 and record == hashlib.sha256(ids['stamp_nonce'].encode()+b'record').digest()[:16], 'record identity derivation differs')
        require('shim_main.all_nonce' in symbols and symbols['shim_main.all_nonce']['data'] == record, 'compiled record nonce differs')
        _cpu_check_literal(symbols['tgl_stamp_boot_entry']['data'],nonce)
        _cpu_check_literal(symbols['shim_main']['data'],epoch)
    except (KeyError,ValueError,IndexError,struct.error,UnicodeError) as exc:
        die('CPU health artifact: malformed ELF/identity: '+str(exc))


def check(d):
    d = Path(d); m = json.loads((d/'manifest.json').read_text()); bad = [f for f, k in (('boot.img', 'image'), ('payload-usb.bin', 'payload'), ('laguna.adt', 'adt')) if sha(d/f) != m[k]]
    if bad: sys.exit(f'MISMATCH {bad}')
    if struct.unpack_from('<I', (d/'payload-usb.bin').read_bytes()[:12], 8)[0] == 1:
        print('payload version 1: built before the 1024-byte line; hashes only, this shim source validates version 2')
    elif contract_check(d/'payload-usb.bin') != m['plan']: sys.exit('plan differs')
    if 'cpus' in m: check_cpu_line((d/'laguna.adt').read_bytes(), m['cmdline'])
    check_cpu_health(m, (d/'laguna.adt').read_bytes(), (d/'payload-usb.bin').read_bytes())
    check_cpu_health_artifact(d, m, (d/'payload-usb.bin').read_bytes())
    check_persist(m)
    print('OK', m['name'], 'bootable' if m['bootable'] else 'NOT BOOTABLE', m['image'])

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('image'); i.add_argument('name'); i.add_argument('--kernel', required=True); i.add_argument('--kernel-sha', required=True)
    i.add_argument('--cpu-audit', action='store_true', help='read-only cpu0 firmware audit on baseline five A725s; docs/CPU.md')
    i.add_argument('--cpu-health', action='store_true', help='frozen p30 cap16 common health acceptance profile; supplies exact phone arguments; docs/CPU.md')
    i.add_argument('--drop-diag', action='append', help=f'with --phone-root: drop this base-line diagnostic, one of {DROP_DIAG}')
    i.add_argument('--route', choices=['ufs', 'md'], default='ufs'); i.add_argument('--md0'); i.add_argument('--md1'); i.add_argument('--cpus', type=int, default=1); i.add_argument('--cpu-order', help='cores for cpus=N in logical order, e.g. 5,6,2,3,4,1,0. handoffs/smp.md'); i.add_argument('--dpu', action='store_true')
    i.add_argument('--canvas'); i.add_argument('--gamut'); i.add_argument('--args'); i.add_argument('--test-kernel', action='store_true'); i.add_argument('--legacy-base', action='store_true'); i.add_argument('--phone-root', action='store_true', help='PHONE-ROOT.md: --route ufs on ios26-phone-r1'); i.add_argument('--soak', type=int, help='N read-only passes, not a phone-run image; 0: the not-live line'); i.add_argument('--preflight', action='store_true', help='--phone-root line on the old partition content, labelled, not bootable'); i.add_argument('--touch', action='store_true', help='--phone-root plus blazer_touch=1, nothing else'); i.add_argument('--phone-deadline', type=int, help='1800, or 3600 with blazer_thermal=2: handoffs/cpmlock.md'); i.add_argument('--soak-whole', help='whole crc the passes must give, hex'); i.add_argument('--phone-args', help='extra tokens for --phone-root, allow-list only'); i.add_argument('--var-overlay', help='overlay file for hk_overlay=MASK'); i.add_argument('--var-overlay-sha'); i.add_argument('--bootcpu', help='0x200, 0x300 or 0x500: run XNU on that core, ios26-fastcore-r1. Parent only, after speed-probe-r3'); i.add_argument('--qemu-run'); i.add_argument('--phone-route'); i.add_argument('--readback', help='root image: sample its blocks for read-back'); i.add_argument('--readback-sha'); i.add_argument('--fullcheck', help='same root as --readback: read all of it and log CRCs'); i.add_argument('--persist-ios-data', action='store_true', help='admit blazer_persist=1 [blazer_persist_period=15..3600] for the pinned kernel.rootview on ios_system only: ios-data-persist/PHYSICAL-PLAN.md'); i.add_argument('--persist', type=int, choices=[2, 3], help='with --fullcheck: blazer_persist=N, handoffs/persist.md'); i.add_argument('--persist-table', help='table.json: the pass skips its blocks, blazer_ufs_fullcheck=2, and so does the list'); i.add_argument('--expect-test-block', help='TABLE.json:A or :B: the list for a kernel with no mask after blazer_persist=2 wrote that pattern'); i.add_argument('--window-base', choices=(hex(PHYS), '0x882000000'), help='kernel RAM base, handoffs/ram.md'); i.add_argument('--second-boot', action='store_true', help='first-boot contract plus shim DPU stage, disp0 and the scanout arguments'); i.add_argument('--first-boot', action='store_true', help="blazer's first phone boot contract: headless ADT, md0 only, fixed base and command line")
    c = sub.add_parser('check'); c.add_argument('dir')
    a = ap.parse_args()
    build(a) if a.cmd == 'image' else check(a.dir)
