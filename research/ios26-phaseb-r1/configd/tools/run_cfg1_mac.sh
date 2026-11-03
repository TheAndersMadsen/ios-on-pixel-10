#!/bin/sh
# Mac only (repo root). HOST ONLY: never boots anything.
# a7-ios-system-cfg1 = a7-ios-system-r10-perf's recipe (perf/tools/run_mac.sh step 3) with two changes:
#   kernel kernel.rootview-bl-aks-us2 (d7f47431) -> kernel.rootview-bl-aks-us2-ns1 (hk-netstack-cfg1), and
#   phone-args: + blazer_netstack=1, - blazer_persona_log=1 (log-only; the 1023-byte shim line has no room for both).
# The overlay stays perf-r1.ovl (95701ed9, HKMAIN watch in Preferences, hk_deny bluetoothd,Spotlight); decode-diffed
# against itself as proof. Then image check, and the cmdline/manifest diff against r10-perf.
set -eu
C=research/ios26-phaseb-r1/configd; R=$C/receipts
KS=${1:?usage: run_cfg1_mac.sh KERNEL_SHA256}
K=$C/build/kernel.rootview-bl-aks-us2-ns1
OVL=research/ios26-phaseb-r1/perf/overlays/perf-r1.ovl
OSHA=95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55
R10=research/images/a7-ios-system-r10-perf
mkdir -p $R
echo "$KS  $K" | shasum -a 256 -c -
echo "$OSHA  $OVL" | shasum -a 256 -c - | tee $R/overlay.sha256
python3 -I - $R10/manifest.json "$OSHA" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1])); assert m['var_overlay']['sha256'] == sys.argv[2], 'r10 used another overlay'; print('r10 overlay == perf-r1.ovl')
EOF
python3 -I research/ios26-phaseb-r1/accel-wait/build-mac/decode_diff.py $OVL $OVL | tee $R/decode-diff.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_log=1 blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_netstack=1"
N=a7-ios-system-cfg1
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
python3 -I $C/tools/image_tool_cfg1.py image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OVL --var-overlay-sha $OSHA --phone-args "$ARGS" --phone-deadline 300 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I $C/tools/image_tool_cfg1.py check research/images/$N | tee $R/image-check.txt
python3 -I - $R10/manifest.json research/images/$N/manifest.json <<'EOF' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']}; tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
print('token order otherwise same' if [t for t in tb if t in ta] == ta else 'token order CHANGED')
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:300]} -> {json.dumps(b.get(k), sort_keys=True)[:300]}")
EOF
shasum -a 256 research/images/$N/boot.img $K $OVL $C/tools/run_cfg1_mac.sh $C/tools/image_tool_cfg1.py $C/tools/image_tool.r10.py | tee $R/SHA256SUMS
