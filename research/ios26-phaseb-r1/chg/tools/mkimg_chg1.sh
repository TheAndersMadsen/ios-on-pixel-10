#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything.   sh research/ios26-phaseb-r1/chg/tools/mkimg_chg1.sh KERNEL_SHA256
# a7-ios-system-chg1 = a7-ios-system-obs1's recipe exactly (live/obs/tools/mkimg_obs1.sh: route rd=ufsroot0, 5 cores, bootcpu 0x200,
# canvas 1125x2511, window 0x882000000, --qemu-run overlay-1, deadline 900, overlay obs1-r1, the same --drop-diag) with only:
#   kernel   research/ios26-phaseb-r1/chg/build/kernel.chg1 (XNU hk-chg1 = hk-obs1 2841211 + chg/xnu-src/0001-hk-chg1.patch)
#   args     + blazer_battery_chg=2 (report-only charger line), - hk_ustack=Preferences,MobilePhone (room: the line limit is 1023 B)
#   tool     chg/tools/image_tool_chg1.py = int1's private image tool + blazer_battery_chg=2 (needs the hk-chg1 kernel)
set -eu
O=research/ios26-phaseb-r1/chg; R=$O/receipts; mkdir -p $R
N=a7-ios-system-chg1
K=$O/build/kernel.chg1
KS=${1:?kernel sha256}
OV=research/ios26-phaseb-r1/live/obs/overlays/obs1-r1.ovl
OVS=8b4fc793c5b18fecc5ed9cbc5b3a4cc5cecd4e1b7a16d58472829ca77e591cc3
TOOL=$O/tools/image_tool_chg1.py
printf '%s  %s\n%s  %s\n' $KS $K $OVS $OV | shasum -a 256 -c - | tee $R/inputs-verify.txt
for s in "rules' libraries in one DYLD_INSERT_LIBRARIES" 'HKOBS %u %s t=%llu %s: %s' 'hk_conlim' 'blazer-battery: charger %u in=' 'charger reads %s'; do
  strings -a $K | grep -qF "$s" && echo "kernel has: $s" || { echo "kernel lacks: $s" >&2; exit 2; }
done | tee -a $R/inputs-verify.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 blazer_battery=1 blazer_battery_chg=2 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
shasum -a 256 $TOOL tools/image_tool.py | tee $R/image_tool.sha256
python3 -I $TOOL image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I $TOOL check research/images/$N | tee $R/image-check.txt
python3 -I - research/images/a7-ios-system-obs1/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"vs a7-ios-system-obs1: cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']} (len {len(b['cmdline'])}); tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if a['cmdline'] == b['cmdline'] else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:240]} -> {json.dumps(b.get(k), sort_keys=True)[:240]}")
print('CMDLINE', b['cmdline'])
PY
shasum -a 256 research/images/$N/boot.img research/images/$N/payload-usb.bin research/images/$N/manifest.json $K $K.unstripped $OV $TOOL $O/tools/mkimg_chg1.sh | tee $R/SHA256SUMS.image
