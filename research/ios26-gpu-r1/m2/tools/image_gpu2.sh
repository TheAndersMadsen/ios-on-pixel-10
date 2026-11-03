#!/bin/bash
# SPDX-License-Identifier: MIT
# Mac checkout root. a7-ios-system-gpu2 = a7-ios-system-r6-gpu's recipe (PLAN.md section 3, image_r6.sh: r3's line without hk_bright=140) with
# three changes, all M2's: kernel.gpu-m2-r1 (d30f785 + rung 6), --cpus 1 (the Trusty GPU rung refuses any other), and blazer_gpu=3 replaced by
# blazer_gpu_tipc=6 (tipc refuses any blazer_gpu on the line; rung 6 runs blazer_gpu=3's survey itself). Thermal limits as r6:
# blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70, governor cap 16. The boot ends seconds after bsd_init with the rung's panic.
set -euo pipefail
K=research/ios26-gpu-r1/artifacts/kernel.gpu-m2-r1
KSHA=$(shasum -a 256 $K | cut -d' ' -f1)
[ "$KSHA" = 039204c0b23201b76d99e6c99d5465fe5274600537a91e665ff52e2b8911faaf ] || { echo "STOP: kernel sha $KSHA"; exit 1; }
python3 -I research/ios26-gpu-r1/m2/tools/image_tool_m2.py image a7-ios-system-gpu2 --kernel $K --kernel-sha $KSHA \
 --phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 1 --canvas 1125x2511 \
 --var-overlay research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl \
 --var-overlay-sha 7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58 \
 --phone-args "blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 hk_present_trace=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_battery_receipt=1 blazer_aks_log=1 blazer_gpu_tipc=6" \
 --phone-deadline 300
python3 -I research/ios26-gpu-r1/m2/tools/image_tool_m2.py check research/images/a7-ios-system-gpu2
