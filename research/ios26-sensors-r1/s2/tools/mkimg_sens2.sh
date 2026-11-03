#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything.
# a7-ios-system-sens2 = a7-ios-system-int1's recipe (research/ios26-phaseb-r1/int/tools/mkimg_int1.sh) with:
#   kernel   research/ios26-sensors-r1/s2/build/kernel.sens2 (XNU hk-int1-sens2 e8a5a0c = hk-int1 484717f + 0930 compass, S2.md)
#   overlay  int1-r1.ovl, unchanged
#   line     int1's - hk_ustack=Preferences,MobilePhone (diagnostic sampler, 34 B) + blazer_sensors=2 blazer_sensors_mag=1 (38 B): 1022 B
#   tool     research/ios26-sensors-r1/s2/tools/image_tool_sens2.py (image_tool_int1.py + the compass allow-list hunk)
set -eu
I=research/ios26-phaseb-r1/int; S=research/ios26-sensors-r1/s2; R=$S/receipts; mkdir -p $R
N=a7-ios-system-sens2
K=$S/build/kernel.sens2
KS=17cd597484b6d5bea4eb741ce97e404025f9eb6fae979530ee37e3dbdb959956
OV=$I/overlays/int1-r1.ovl
OVS=c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e
APP2=research/ios26-apps-r1/app2/overlays/app2-r1.ovl
CUO=research/ios26-opt-20261102/combined_ui_overlay
X=research/ios26-release-r1/work/xnu
TOOL=$S/tools/image_tool_sens2.py
printf '%s  %s\n%s  %s\n%s  %s\n' $KS $K $OVS $OV 0eb06481d31376b95684dbc6bc53a005adff7ae3e03e967a983f46e41605755e $APP2 | shasum -a 256 -c - | tee $R/inputs-verify.txt
for h in kern/hk_exec_rules.h miscfs/ramfs/varfs_overlay.h miscfs/ramfs/varfs_tsv.h; do
  git -C $X show hk-int1-sens2:bsd/$h | cmp -s "$CUO/inputs/r1/bsd/$h" - && echo "hk-int1-sens2 == pinned $h" || echo "hk-int1-sens2 DIFFERS from pinned $h"
done | tee $R/release-headers.txt
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
xcrun clang -arch arm64 -DBLAZER=1 -DARM64_BOARD_CONFIG_SWEET=1 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-sanitize-recover=all -idirafter "$CUO/inputs/r1/bsd" research/ios26-phaseb-r1/pwr/tools/pwr_consumer.c -o $T/pwr_consumer
echo "pwr_consumer.c: app2-r1 -> int1-r1 (int1 = pwr's transform applied to app2-r1)" | tee $R/consumer.txt
$T/pwr_consumer $APP2 $OV | tee -a $R/consumer.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1 blazer_sensors=2 blazer_sensors_mag=1"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
shasum -a 256 $TOOL tools/image_tool.py | tee $R/image_tool.sha256
python3 -I $TOOL image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I $TOOL check research/images/$N | tee $R/image-check.txt
python3 -I tools/image_tool.py check research/images/$N | sed 's/^/shared tools\/image_tool.py: /' | tee -a $R/image-check.txt
python3 -I - research/images/a7-ios-system-int1/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"vs a7-ios-system-int1: cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']} (len {len(b['cmdline'])}); tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}; common order same={[t for t in ta if t in tb] == [t for t in tb if t in ta]}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:240]} -> {json.dumps(b.get(k), sort_keys=True)[:240]}")
print('CMDLINE', b['cmdline'])
PY
shasum -a 256 research/images/$N/boot.img research/images/$N/manifest.json $K $K.unstripped $OV $TOOL $S/tools/mkimg_sens2.sh | tee $R/SHA256SUMS
