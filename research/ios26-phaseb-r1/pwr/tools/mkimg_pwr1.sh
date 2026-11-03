#!/bin/sh
# m1box, from the repository root. a7-ios-system-pwr1 = a7-ios-system-r10-perf's recipe (ios26-apps-r1/usersession/mkimg.sh,
# ufs variant, as perf/tools/run_mac.sh) with three changes:
#   kernel   research/ios26-phaseb-r1/pwr/build/kernel.pwr1 (hk-pwr1: e731e68 + aks-usersession picks + keys 0001 + haptics 0832 + tap)
#   overlay  research/ios26-phaseb-r1/pwr/overlays/pwr-r1.ovl (perf-r1 - SBDontLockEver + localtime -> Europe/Copenhagen)
#   deadline 900 s (the tool default for --bootcpu with 5 cores; 1800 is refused there): time for the attended checklist
#   line     + blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1
#            - hk_top=30 blazer_aks_log=1 blazer_aks_usersession=1 blazer_persona_log=1 (phone args) and hk_fb_probe=1 (--drop-diag)
set -e
N=a7-ios-system-pwr1
P=research/ios26-phaseb-r1/pwr
R=$P/receipts
K=$P/build/kernel.pwr1
KS=$(sha256sum $K | cut -d' ' -f1)
OV=$P/overlays/pwr-r1.ovl
OVS=d0804b36bb540b1e63eeda033654e252ff4da8359b5c0f1d6f6d1af631b27b97
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1"
[ -e research/images/$N ] && { echo "$N exists, refusing"; exit 1; }
[ "$(sha256sum $OV | cut -d' ' -f1)" = $OVS ] || { echo "overlay hash differs"; exit 1; }
TGL_TOOLCHAIN=llvm LLVM=$HOME/.local/share/hackios-host/llvm/bin python3 -I tools/image_tool.py image $N --kernel $K --kernel-sha $KS \
  --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
  --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --drop-diag hk_fb_probe=1 > $R/image-build.txt 2>&1 \
  || { tail -30 $R/image-build.txt; exit 1; }
tail -2 $R/image-build.txt
LLVM=$HOME/.local/share/hackios-host/llvm/bin python3 -I tools/image_tool.py check research/images/$N | tee $R/image-check.txt
