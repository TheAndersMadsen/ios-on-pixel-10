#!/bin/bash
# SPDX-License-Identifier: MIT
# Mac checkout root. a7-ios-system-gpu3 = a7-ios-system-gpu2's recipe (m2/tools/image_gpu2.sh) with exactly two changes: kernel.gpu-m3-s1 (58f0893 + rung 7 S1,
# s1/tools/build_s1.sh) and blazer_gpu_tipc=6 replaced by blazer_gpu_tipc=7 (research/ios26-gpu-native-r1/COREMEM-INIT.md, LIVE-EVIDENCE.md section 6).
# Everything else as gpu2: --cpus 1, thermal guard blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70, governor cap 16, deadline 300,
# blazer_panic reset, live USB console, M2 firmware log and register dumps. No hk_dbg token: the boot ends after bsd_init with the rung panic.
set -euo pipefail
K=research/ios26-gpu-r1/artifacts/kernel.gpu-m3-s1
KSHA=$(shasum -a 256 $K | cut -d' ' -f1)
[ "$KSHA" = 4462f88675dbf310076064e89888ae77cbc736ed8f6a573098bade763ab2bfa3 ] || { echo "STOP: kernel sha $KSHA"; exit 1; }
python3 -I research/ios26-gpu-r1/s1/tools/image_tool_s1.py image a7-ios-system-gpu3 --kernel $K --kernel-sha $KSHA \
 --phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 1 --canvas 1125x2511 \
 --var-overlay research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl \
 --var-overlay-sha 7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58 \
 --phone-args "blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 hk_present_trace=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_battery_receipt=1 blazer_aks_log=1 blazer_gpu_tipc=7" \
 --phone-deadline 300
python3 -I research/ios26-gpu-r1/s1/tools/image_tool_s1.py check research/images/a7-ios-system-gpu3
