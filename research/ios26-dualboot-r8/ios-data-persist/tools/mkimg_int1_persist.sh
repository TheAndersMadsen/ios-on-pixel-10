#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything.
# a7-ios-system-int1-persist = a7-ios-system-int1's recipe (research/ios26-phaseb-r1/int/tools/mkimg_int1.sh: same kernel, overlay,
# route, cores, bootcpu, canvas, window, deadline 900, --drop-diag) with these line changes only:
#   + blazer_persist=1 blazer_persist_period=15   (PHYSICAL-PLAN.md; admitted by --persist-ios-data for kernel.int1)
#   - blazer_usbcon=1 blazer_usbcon_ch9=1          (36 B: the live USB console; the plan reads the ramdump, and the chooser path has none)
#   hk_ustack=Preferences,MobilePhone -> hk_ustack=Preferences   (12 B: keep Settings' stacks, drop the Phone app's)
# 1018 + 42 - 48 = 1012 B (limit 1023). hk_ustack alone (34 B) or the usbcon pair alone (36 B) is not enough.
# Tool: ios-data-persist/tools/image_tool_int1_persist.py = int/tools/image_tool_int1.py + the two-kernel persist gate
# (the same patch as tools/image_tool.py's).
set -eu
D=research/ios26-dualboot-r8/ios-data-persist; R=$D/receipts/int1-persist; mkdir -p $R
I=research/ios26-phaseb-r1/int
N=a7-ios-system-int1-persist
K=$I/build/kernel.int1
KS=0d0c99b2cd7b1c71509c9cf52af34ca29c1856001fd077df41b6386bf243e9bf
OV=$I/overlays/int1-r1.ovl
OVS=c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e
TOOL=$D/tools/image_tool_int1_persist.py
printf '%s  %s\n%s  %s\n' $KS $K $OVS $OV | shasum -a 256 -c - | tee $R/inputs-verify.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1 hk_ustack=Preferences blazer_persist=1 blazer_persist_period=15"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
shasum -a 256 $TOOL $I/tools/image_tool_int1.py tools/image_tool.py | tee $R/image_tool.sha256
python3 -I $TOOL image $N --kernel $K --kernel-sha $KS --persist-ios-data \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I $TOOL check research/images/$N | tee $R/image-check.txt
python3 -I $D/tools/manifest_diff_int1_persist.py research/images/a7-ios-system-int1/manifest.json research/images/$N/manifest.json | tee $R/manifest-diff.txt
shasum -a 256 research/images/$N/boot.img research/images/$N/manifest.json research/images/$N/payload-usb.bin $K $OV $TOOL $D/tools/mkimg_int1_persist.sh $D/tools/manifest_diff_int1_persist.py | tee $R/SHA256SUMS
