#!/bin/sh
# Mac: build a7-ios-system-r9-apps (r7-touch recipe, md0-mountroot) and a7-ios-system-r9-apps-ufs (route ufsroot + blazer_persona_log=1)
set -e
K=research/ios26-apps-r1/usersession/build/kernel.rootview-bl-aks-us2
KS=$(shasum -a 256 $K | cut -d' ' -f1)
OV=research/ios26-phaseb-r1/accel-wait/build-mac/overlays/artwork-container-battery-observe-accel-skip-r1.ovl
OVS=f5d4c3676d1cf78c1b21036b784819d66425ce6bb55c27a46eee17f277412a97
BASE="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_log=1 blazer_aks_wrap=1 blazer_aks_usersession=1"
for v in md0 ufs; do
  if [ $v = md0 ]; then N=a7-ios-system-r9-apps; RT=md0-mountroot; X=""; else N=a7-ios-system-r9-apps-ufs; RT=ufsroot; X=" blazer_persona_log=1"; fi
  [ -e research/images/$N ] && { echo "$N exists, refusing"; exit 1; }
  python3 -I tools/image_tool.py image $N --kernel $K --kernel-sha $KS \
   --phone-root --phone-route $RT --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
   --var-overlay $OV --var-overlay-sha $OVS --phone-args "$BASE$X" --phone-deadline 300 > research/ios26-apps-r1/usersession/image-$N.out 2>&1 || { tail -20 research/ios26-apps-r1/usersession/image-$N.out; exit 1; }
  tail -2 research/ios26-apps-r1/usersession/image-$N.out
  python3 -I tools/image_tool.py check research/images/$N | tail -3
done
