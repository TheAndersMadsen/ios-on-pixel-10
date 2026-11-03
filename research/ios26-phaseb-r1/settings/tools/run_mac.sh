#!/bin/sh
# Mac only (repo root): build the r8-settings overlay, decode-diff it, run the release-header consumer, then build and
# check a7-ios-system-r8-settings with a7-ios-system-r7-touch's recipe (A7-READY step 6, kernel.rootview-bl-touch) where
# only --var-overlay/--var-overlay-sha change. HOST ONLY: never boots anything.
set -eu
REPO=$(pwd); S=research/ios26-phaseb-r1/settings; R=$S/receipts
BASE=research/ios26-phaseb-r1/accel-wait/build-mac/overlays/artwork-container-battery-observe-accel-skip-r1.ovl
OVL=$S/overlays/settings-btdisabled-r1.ovl
CUO=research/ios26-opt-20261102/combined_ui_overlay
K=research/ios26-dualboot-r8/rootview/kernel.rootview-bl-touch
KSHA=cf9065990b76d038d4ca94d1bdda3d4a2f2f4d615edc9dbb7c67f9543d7b1452
mkdir -p $R $S/overlays $S/out
shasum -a 256 $BASE | tee $R/base.sha256
[ -e $OVL ] || python3 -I $S/tools/disable_bluetoothd.py $BASE $OVL > $R/transform.json
cat $R/transform.json
python3 -I research/ios26-phaseb-r1/accel-wait/build-mac/decode_diff.py $BASE $OVL | tee $R/decode-diff.txt
for h in kern/hk_exec_rules.h miscfs/ramfs/varfs_overlay.h miscfs/ramfs/varfs_tsv.h; do
  cmp -s "$CUO/inputs/r1/bsd/$h" "research/ios26-release-r1/work/xnu/bsd/$h" && echo "live == pinned $h" || echo "live DIFFERS from pinned $h"
done | tee $R/release-headers.txt
xcrun clang -arch arm64 -DBLAZER=1 -DARM64_BOARD_CONFIG_SWEET=1 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-sanitize-recover=all -idirafter "$CUO/inputs/r1/bsd" $S/tools/settings_consumer.c -o $S/out/settings_consumer
$S/out/settings_consumer $BASE $OVL | tee $R/consumer.txt
OSHA=$(shasum -a 256 $OVL | cut -d' ' -f1)
N=a7-ios-system-r8-settings
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
python3 -I tools/image_tool.py image $N --kernel $K --kernel-sha $KSHA \
 --phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OVL --var-overlay-sha $OSHA \
 --phone-args "blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 hk_present_trace=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_battery_receipt=1 hk_bright=140 blazer_aks_log=1" \
 --phone-deadline 300 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -5 $R/image-build.txt
python3 -I tools/image_tool.py check research/images/$N | tee $R/image-check.txt
python3 -I - research/images/a7-ios-system-r7-touch/manifest.json research/images/$N/manifest.json <<'EOF' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']}; tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:300]} -> {json.dumps(b.get(k), sort_keys=True)[:300]}")
EOF
shasum -a 256 research/images/$N/boot.img $OVL $S/tools/* tools/image_tool.py | tee $R/SHA256SUMS
