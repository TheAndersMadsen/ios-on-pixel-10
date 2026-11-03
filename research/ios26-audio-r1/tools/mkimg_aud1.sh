#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything. Takes /tmp/fleet/kernel-build-slot.lock while it builds (shared .work/contract);
# the XNU tree is not touched.
# a7-ios-system-aud1 = a7-ios-system-int1's recipe (research/ios26-phaseb-r1/int/tools/mkimg_int1.sh) with:
#   kernel   unchanged: research/ios26-phaseb-r1/int/build/kernel.int1 (hk-int1 484717f; holds 0900 hkcover + 1144 rt + 1145 pcm)
#   overlay  research/ios26-audio-r1/build/aud1-r1.ovl = int1-r1 + audio-s1b groups 24/25 + tone client in group 29 (aud1_overlay.py)
#   line     int1's - hk_ustack=Preferences,MobilePhone + blazer_audio=3 blazer_audio_rt=1 (1017 B of 1023); mask unchanged 0xA0080081
#   tool     research/ios26-audio-r1/tools/image_tool_aud1.py (int1's image_tool_int1.py 728bdd21 + the blazer_audio checks)
set -eu
A=research/ios26-audio-r1; R=$A/receipts/aud1; mkdir -p $R
N=a7-ios-system-aud1
K=research/ios26-phaseb-r1/int/build/kernel.int1
KS=0d0c99b2cd7b1c71509c9cf52af34ca29c1856001fd077df41b6386bf243e9bf
OV=$A/build/aud1-r1.ovl
OVS=89e72e571fd3aff7ac0b8d2a7e4adb314871a412a58a74803001a014f3f0f626
TOOL=$A/tools/image_tool_aud1.py
printf '%s  %s\n%s  %s\n' $KS $K $OVS $OV | shasum -a 256 -c - | tee $R/inputs-verify.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1 blazer_audio=3 blazer_audio_rt=1"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
shasum -a 256 $TOOL tools/image_tool.py | tee $R/image_tool.sha256
mkdir -p /tmp/fleet
exec 9>>/tmp/fleet/kernel-build-slot.lock
echo "waiting for /tmp/fleet/kernel-build-slot.lock"
# flock on the inherited fd 9: the lock belongs to the shell's open file and is held until this script exits
python3 -c 'import fcntl, time; t = time.time(); fcntl.flock(9, fcntl.LOCK_EX); print(f"lock held after {time.time() - t:.1f} s")'
if pgrep -x make >/dev/null; then echo "a make is running: refusing (build_int1.py's rule)" >&2; exit 3; fi
python3 -I $TOOL image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I $TOOL check research/images/$N | tee $R/image-check.txt
python3 -I tools/image_tool.py check research/images/$N | sed 's/^/shared tools\/image_tool.py: /' | tee -a $R/image-check.txt
python3 -I - research/images/a7-ios-system-int1/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"vs a7-ios-system-int1: cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']} (len {len(b['cmdline'])}); tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}; common order same={[t for t in ta if t in tb] == [t for t in tb if t in ta]}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:240]} -> {json.dumps(b.get(k), sort_keys=True)[:240]}")
print('CMDLINE', b['cmdline'])
PY
shasum -a 256 research/images/$N/boot.img research/images/$N/manifest.json research/images/$N/payload-usb.bin $K $OV $TOOL $A/tools/mkimg_aud1.sh | tee $R/SHA256SUMS
