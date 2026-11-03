#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything.
# a7-ios-system-fb120  = a7-ios-system-int1's recipe (int/tools/mkimg_int1.sh) with kernel.fb120 and hk_fb_refresh=60 -> 120.
# a7-ios-system-fb120v = the same with hk_fb_refresh=121 (120 busy + LTPO idle 30 Hz; implies hk_fb_fence). Second test, only after fb120 passes.
# Everything else (overlay int1-r1, route, cores, canvas, window, drop-diag, other tokens and their order) is int1's.
set -eu
I=research/ios26-phaseb-r1/display/fb120; R=$I/receipts; mkdir -p $R
K=$I/build/kernel.fb120
KS=c2b3e7b30d60498858b05f165ce25c4f6e43f54aa1a0004dfa46c840f43488c0
OV=research/ios26-phaseb-r1/int/overlays/int1-r1.ovl
OVS=c440b6ea64759d09f5ddb75951f39f664b7080c15468e2884278faba7da7cf5e
TOOL=$I/tools/image_tool_fb120.py
printf '%s  %s\n%s  %s\n' $KS $K $OVS $OV | shasum -a 256 -c - | tee $R/inputs-verify.txt
shasum -a 256 $TOOL tools/image_tool.py research/ios26-phaseb-r1/int/tools/image_tool_int1.py | tee $R/image_tool.sha256
for pair in a7-ios-system-fb120:120 a7-ios-system-fb120v:121; do
  N=${pair%%:*}; RATE=${pair##*:}
  ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=$RATE hk_overlay=0xA0080081 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1 hk_ustack=Preferences,MobilePhone"
  [ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
  python3 -I $TOOL image $N --kernel $K --kernel-sha $KS \
   --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
   --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --drop-diag hk_fb_probe=1 --drop-diag hk_usertrace=1 > $R/image-build-$N.txt 2>&1 || { tail -40 $R/image-build-$N.txt; exit 1; }
  tail -3 $R/image-build-$N.txt
  python3 -I $TOOL check research/images/$N | tee $R/image-check-$N.txt
  python3 -I tools/image_tool.py check research/images/$N 2>&1 | sed 's/^/shared tools\/image_tool.py: /' | tee -a $R/image-check-$N.txt
  python3 -I - research/images/a7-ios-system-int1/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff-$N.txt
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
done
shasum -a 256 research/images/a7-ios-system-fb120/boot.img research/images/a7-ios-system-fb120/manifest.json research/images/a7-ios-system-fb120v/boot.img research/images/a7-ios-system-fb120v/manifest.json $K $K.unstripped $OV $TOOL $I/tools/mkimg_fb120.sh | tee $R/SHA256SUMS.mac
