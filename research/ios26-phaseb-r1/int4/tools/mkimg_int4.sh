#!/bin/sh
# m1box or Mac, repo root. HOST ONLY: never boots anything.
# a7-ios-system-int4 = a7-ios-system-int3's recipe (int3/tools/mkimg_int3.sh) with:
#   kernel   research/ios26-phaseb-r1/int4/build/kernel.int4 (XNU hk-int4 f6c8a68 = hk-int3 3dc7fec
#            + fb120 cd60b8d + ram-full 476c253 + chg1 ca39cb4, cherry-picked clean)
#   overlay  int3-r1.ovl unchanged (65 records, 4 covers + obs1 mirror); fb120/ram-full/chg1 are kernel-only
#   line     int3's (1000 B) with hk_fb_refresh=60->120 (+1 B), blazer_mem=13->16 (+0 B),
#            +blazer_battery_chg=2 after blazer_battery=1 (+21 B, chg1's position) = 1022 B
#   tool     int4/tools/image_tool_int4.py = image_tool_int2.py + the three allow-list/kernel checks
# Usage: mkimg_int4.sh
set -eu
A=research/ios26-phaseb-r1/int4; R=$A/receipts; mkdir -p $R
N=a7-ios-system-int4
K=$A/build/kernel.int4
KS=7b5e63287f2da99f346f634175f81c1fc5d1e68cd23e29ebe551b1fa6ada8c86
OV=research/ios26-phaseb-r1/int3/overlays/int3-r1.ovl
OVS=898740adf222a87498e7331860f47ed9b020ac84d8ff496c4d99e04c616db2f3
TOOL=$A/tools/image_tool_int4.py
printf '%s  %s\n%s  %s\n' $KS $K $OVS $OV | shasum -a 256 -c - | tee $R/inputs-verify.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=120 hk_overlay=0xA0080081 blazer_battery=1 blazer_battery_chg=2 blazer_mem=16 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1 hk_dbg=0x1e1e1f"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
shasum -a 256 $TOOL tools/image_tool.py | tee $R/image_tool.sha256
python3 -I $TOOL image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
echo "== image_tool_int4.py check ==" | tee $R/image-check.txt
python3 -I $TOOL check research/images/$N | tee -a $R/image-check.txt
echo "== shared tools/image_tool.py check ==" | tee -a $R/image-check.txt
python3 -I tools/image_tool.py check research/images/$N | sed 's/^/shared tools\/image_tool.py: /' | tee -a $R/image-check.txt
python3 -I - research/images/a7-ios-system-int3/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"vs a7-ios-system-int3: cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']} (len {len(b['cmdline'])}); tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:200]} -> {json.dumps(b.get(k), sort_keys=True)[:200]}")
print('CMDLINE_BYTES', b['cmdline_bytes'])
print('CMDLINE', b['cmdline'])
PY
shasum -a 256 research/images/$N/boot.img research/images/$N/manifest.json $K $K.unstripped $OV $TOOL $A/tools/mkimg_int4.sh | tee $R/SHA256SUMS
