#!/bin/bash
# Mac checkout root. a7-ios-system-r3 recipe (A7-READY step 6 minus hk_bright=140, kernel.rootview) with only the kernel changed to
# kernel.gpu-survey-r1 (7227fe7 + blazer_gpu=3) and blazer_gpu=3 appended.
set -euo pipefail
K=research/ios26-gpu-r1/artifacts/kernel.gpu-survey-r1
python3 -I tools/image_tool.py image a7-ios-system-r6-gpu --kernel $K \
 --kernel-sha 361315b02a60732a19a6769528ab0ab41c005c9e2ae734998b9954553635526d \
 --phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl \
 --var-overlay-sha 7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58 \
 --phone-args "blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 hk_present_trace=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_battery_receipt=1 blazer_aks_log=1 blazer_gpu=3" \
 --phone-deadline 300
python3 -I tools/image_tool.py check research/images/a7-ios-system-r6-gpu
