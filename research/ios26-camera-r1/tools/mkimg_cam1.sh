#!/bin/sh
# Mac, repo root. HOST ONLY: builds and checks research/images/a7-ios-system-cam1, boots nothing.
# = a7-ios-system-r3's recipe (A7-READY.md step 6 minus hk_bright=140; 5 cores, deadline 300) with kernel.cam1 and one more token,
# blazer_torch=4 (cmdline 999 -> 1014 B of 1023). image_tool_cam1.py = the Mac's tools/image_tool.py (sha pinned below) with X pointed
# back at tools/ and one PHONE_ALLOWED line for blazer_torch / blazer_torch_ms / blazer_torch_delay. Shared tools/image_tool.py is untouched.
#   sh research/ios26-camera-r1/tools/mkimg_cam1.sh KERNEL_SHA256
set -eu
C=research/ios26-camera-r1
K=$C/build/kernel.cam1
KSHA=$1
BASE_TOOL_SHA=acf48b98b63cbec5bac5c6cbf94cdfa50637f61978a212db893afeb3b42804cb
OVL=research/ios26-opt-20261102/combined_ui_overlay/artifacts/artwork-container-battery-observe-r1.ovl
OVL_SHA=7d610456642614367cb4262576efdf05fd751ebc480720e4d669e1882a820f58
NAME=a7-ios-system-cam1
mkdir -p $C/receipts

[ "$(shasum -a 256 $K | cut -d' ' -f1)" = "$KSHA" ] || { echo "kernel.cam1 is not $KSHA"; exit 1; }
[ "$(shasum -a 256 tools/image_tool.py | cut -d' ' -f1)" = "$BASE_TOOL_SHA" ] || { echo "tools/image_tool.py is not $BASE_TOOL_SHA: re-derive the copy"; exit 1; }
for s in 'cli select uart -> i2c' 'blazer-torch: summary stage %u'; do
  grep -q -a "$s" $K || { echo "kernel.cam1 lacks '$s'"; exit 1; }
done

python3 -I - "$C/tools/image_tool_cam1.py" <<'EOF'
import sys
s = open('tools/image_tool.py').read()
a = "X = Path(__file__).resolve().parent; ROOT = X.parent;"
b = "X = Path(__file__).resolve().parents[3]/'tools'; ROOT = X.parent;"
c = "PHONE_ALLOWED.update({'blazer_gpu': r'blazer_gpu=3'})\n"
d = c + ("# research/ios26-camera-r1 (hk-cam1): flash LED stages; 4 lights the torch at 12 mA for blazer_torch_ms on LED1 then LED2\n"
         "PHONE_ALLOWED.update({'blazer_torch': r'blazer_torch=[1-4]', 'blazer_torch_ms': r'blazer_torch_ms=([5-9][0-9]{2}|[1-4][0-9]{3}|5000)',"
         " 'blazer_torch_delay': r'blazer_torch_delay=([3-9][0-9]|[1-5][0-9]{2}|600)'})\n")
assert s.count(a) == 1 and s.count(c) == 1
open(sys.argv[1], 'w').write(s.replace(a, b).replace(c, d))
EOF
shasum -a 256 tools/image_tool.py $C/tools/image_tool_cam1.py | tee $C/receipts/image_tool.sha256
diff tools/image_tool.py $C/tools/image_tool_cam1.py > $C/receipts/image_tool_cam1.diff || true

rm -rf research/images/$NAME
python3 -I $C/tools/image_tool_cam1.py image $NAME --kernel $K --kernel-sha $KSHA \
 --phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OVL --var-overlay-sha $OVL_SHA \
 --phone-args "blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 hk_present_trace=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_battery_receipt=1 blazer_aks_log=1 blazer_torch=4" \
 --phone-deadline 300 2>&1 | tee $C/receipts/image-build.txt
python3 -I $C/tools/image_tool_cam1.py check research/images/$NAME 2>&1 | tee $C/receipts/image-check.txt
python3 -I - research/images/$NAME/manifest.json research/images/a7-ios-system-r3/manifest.json <<'EOF' | tee research/ios26-camera-r1/receipts/cmdline-diff.txt
import json, sys
a = json.load(open(sys.argv[1]))['cmdline'].split(); b = json.load(open(sys.argv[2]))['cmdline'].split()
print('cam1 bytes', len(' '.join(a)), 'r3 bytes', len(' '.join(b)))
print('only in cam1:', [t for t in a if t not in b]); print('only in r3:', [t for t in b if t not in a])
EOF
shasum -a 256 research/images/$NAME/boot.img research/images/$NAME/payload-usb.bin | tee $C/receipts/SHA256SUMS.image
