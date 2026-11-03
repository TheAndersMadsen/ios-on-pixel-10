#!/usr/bin/env python3
"""HOST ONLY. Refusals of tools/image_tool_aud1.py's audio checks: each case is int1's recipe with one change and must stop
before the image directory is made (build() makes it only after the checks). Nothing is built.

    python3 -I research/ios26-audio-r1/tests/test_image_tool_aud1.py
Needs kernel.int1 (research/ios26-phaseb-r1/int/build) and the aud1 overlay (research/ios26-audio-r1/build/aud1-r1.ovl).
"""
import hashlib, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TOOL = REPO / 'research/ios26-audio-r1/tools/image_tool_aud1.py'
K = REPO / 'research/ios26-phaseb-r1/int/build/kernel.int1'
OV1 = REPO / 'research/ios26-phaseb-r1/int/overlays/int1-r1.ovl'
OVA = REPO / 'research/ios26-audio-r1/build/aud1-r1.ovl'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
BASE = ('blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 '
        'blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 MASK blazer_battery=1 blazer_mem=13 blazer_thermal=2 '
        'blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 '
        'blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 '
        'blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1')
M = 'hk_overlay=0xA0080081'
fails = checks = 0


def run(name, kernel, ov, args, want):
    global fails, checks
    checks += 1
    out = REPO / 'research/images' / name
    if out.exists():
        print(f'SKIP {name}: exists'); fails += 1; return
    cmd = [sys.executable, '-I', str(TOOL), 'image', name, '--kernel', str(kernel), '--kernel-sha', sha(kernel), '--phone-root',
           '--phone-route', 'ufsroot', '--qemu-run', 'overlay-1', '--window-base', '0x882000000', '--bootcpu', '0x200', '--cpus', '5',
           '--canvas', '1125x2511', '--var-overlay', str(ov), '--var-overlay-sha', sha(ov), '--phone-args', args,
           '--drop-diag', 'hk_fb_probe=1', '--drop-diag', 'hk_usertrace=1']
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    text = r.stdout + r.stderr
    good = r.returncode != 0 and want in text and not out.exists()
    if not good:
        fails += 1
        print(f'FAIL {name}: rc {r.returncode}, want {want!r}\n{text[-600:]}')
    else:
        print(f'ok   {name}: {want}')
    if out.exists():
        print(f'!!! {out} was made')


audio = BASE.replace('MASK', M) + ' blazer_audio=3 blazer_audio_rt=1'
run('test-aud1-no-cover-groups', K, OV1, audio, 'needs an overlay holding groups 24 and 25')
run('test-aud1-rt-alone', K, OVA, BASE.replace('MASK', M) + ' blazer_audio_rt=1', 'blazer_audio_rt=1 goes with blazer_audio=3')
run('test-aud1-mask-bit24', K, OVA, BASE.replace('MASK', 'hk_overlay=0xA1080081') + ' blazer_audio=3 blazer_audio_rt=1', 'must not hold bits 24/25')
run('test-aud1-pcm', K, OVA, audio + ' blazer_audio_pcm=1', 'blazer_audio_pcm')
run('test-aud1-bits1', K, OVA, BASE.replace('MASK', M) + ' blazer_audio=1', 'blazer_audio=1')
with tempfile.TemporaryDirectory(dir=REPO / 'research/ios26-audio-r1/build') as d:
    b = K.read_bytes()
    s = b'hk-audio-rt: audiomxd bootstrap 1200 -> %u ticks'
    assert b.count(s) == 1
    nk = Path(d) / 'kernel.no-rt'
    nk.write_bytes(b.replace(s, b'X' * len(s)))
    run('test-aud1-kernel-no-rt', nk, OVA, audio, 'no audio RT bootstrap adapter')
    s = b'/private/var/hkcover/hal'
    nk2 = Path(d) / 'kernel.no-hal'
    nk2.write_bytes(b.replace(s, b'/private/var/hkcover/xxx'))
    run('test-aud1-kernel-no-hal', nk2, OVA, audio, 'kernel lacks stage-1 audio')
print(f'image_tool_aud1 refusal test: {checks} cases, {fails} failed')
sys.exit(1 if fails else 0)
