#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything. USBHOST.md.
# a7-ios-system-usbhost1 = a7-ios-system-obs1's recipe (live/obs/tools/mkimg_obs1.sh: rd=ufsroot0 from ios_system, 5 cores,
# bootcpu 0x200, canvas 1125x2511, window 0x882000000, --qemu-run overlay-1, overlay obs1-r1, --drop-diag) with only:
#   kernel    usbhost/build/kernel.usbhost1 (XNU hk-usbhost1 = hk-obs1 284121116f + patches/0001, tools/build_usbhost.py)
#   tool      usbhost/tools/image_tool_usbhost.py (int1's 728bdd21 + the blazer_usbhost allowlist and gate)
#   args      - blazer_usbcon=1 blazer_usbcon_ch9=1   (one controller, one owner: no live console in this boot)
#             + blazer_usbhost=1 (wait 90 s, window 150 s: the kernel's defaults; spelling them out would pass 1023 bytes)
#   deadline  300 (obs1: 900): host mode ends by ~250 s after XNU entry; the deadline panic ends the boot, ABL's ramdump
#             path brings USB back as a device and the result is read from the ramdump.
set -eu
U=research/ios26-phaseb-r1/usbhost; R=$U/receipts; mkdir -p $R
N=a7-ios-system-usbhost1
K=$U/build/kernel.usbhost1
OV=research/ios26-phaseb-r1/live/obs/overlays/obs1-r1.ovl
OVS=8b4fc793c5b18fecc5ed9cbc5b3a4cc5cecd4e1b7a16d58472829ca77e591cc3
TOOL=$U/tools/image_tool_usbhost.py
TOOLS=1057476dd99b0b872032192719fc03a21eae62121884a9387108a63ee46b5ea8
[ -f "$K" ] || { echo "no $K: run tools/build_usbhost.py first" >&2; exit 2; }
KS=$(shasum -a 256 $K | cut -d' ' -f1)
printf '%s  %s\n' $OVS $OV | shasum -a 256 -c - | tee $R/inputs-verify.txt
printf '%s  %s\n' $TOOLS $TOOL | shasum -a 256 -c - | tee -a $R/inputs-verify.txt
for s in 'blazer-usbhost: ENUM port %u speed %s dev %04x:%04x' 'blazer_usbhost_window' 'HKOBS %u %s t=%llu %s: %s'; do
  strings -a $K | grep -qF "$s" && echo "kernel has: $s" || { echo "kernel lacks: $s" >&2; exit 2; }
done | tee -a $R/inputs-verify.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1 hk_ustack=Preferences,MobilePhone blazer_usbhost=1"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
python3 -I $TOOL image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --phone-deadline 300 --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1 \
 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I $TOOL check research/images/$N | tee $R/image-check.txt
python3 -I - research/images/a7-ios-system-obs1/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"vs a7-ios-system-obs1: cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']}; tokens {len(ta)} -> {len(tb)}")
print(f"cmdline: -{sorted(set(ta) - set(tb))} +{sorted(set(tb) - set(ta))}")
assert not any(t.startswith(('blazer_usbcon', 'blazer_usbnet')) for t in tb), 'console token in a host-mode image'
assert b['cmdline_bytes'] <= 1023, 'cmdline over 1023 bytes'
print('CMDLINE', b['cmdline'])
PY
shasum -a 256 research/images/$N/boot.img research/images/$N/manifest.json $K $K.unstripped $OV $TOOL $U/tools/mkimg_usbhost.sh | tee $R/SHA256SUMS.image
