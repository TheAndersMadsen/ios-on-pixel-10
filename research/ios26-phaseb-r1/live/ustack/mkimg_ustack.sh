#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything.
# a7-ios-system-dbg4-ustack = a7-ios-system-r10-perf's recipe (research/ios26-phaseb-r1/perf/tools/run_mac.sh step 3: r9-apps-ufs's
# mkimg.sh ufs variant, overlay perf-r1 95701ed9) with kernel hk-ustack-dbg4 (e731e68 + hk_ustack), plus
# hk_ustack=Preferences,MobilePhone, minus the three tokens e731e68 does not read (blazer_aks_wrap, blazer_aks_usersession,
# blazer_persona_log: AKS branch only; the same three dbg1-net drops). USTACK.md.
set -e
D=research/ios26-phaseb-r1/live/ustack; R=$D/receipts
mkdir -p $R
N=a7-ios-system-dbg4-ustack
K=$D/build/kernel.dbg4-ustack
KS=a5d16a269bc9cc063e21d0dfc146d84e9ba0288381d6f84a7b69f1870b332e18
echo "$KS  $K" | shasum -a 256 -c -
OV=research/ios26-phaseb-r1/perf/overlays/perf-r1.ovl
OVS=95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55
echo "$OVS  $OV" | shasum -a 256 -c -
R10="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_log=1 blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_persona_log=1"
ARGS=$(echo "$R10" | tr ' ' '\n' | grep -v -x -e blazer_aks_wrap=1 -e blazer_aks_usersession=1 -e blazer_persona_log=1 | tr '\n' ' ')
ARGS="${ARGS}hk_ustack=Preferences,MobilePhone"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
grep -q "'hk_ustack'" tools/image_tool.py || python3 -I $D/tools/allow_ustack.py | tee $R/allow-ustack.txt
python3 -I tools/image_tool.py image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OV --var-overlay-sha $OVS --phone-args "$ARGS" --phone-deadline 300 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I tools/image_tool.py check research/images/$N > $R/image-check.txt 2>&1 && rc=0 || rc=$?
tail -5 $R/image-check.txt
python3 -I - research/images/a7-ios-system-r10-perf/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']} (len {len(b['cmdline'])}); tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:300]} -> {json.dumps(b.get(k), sort_keys=True)[:300]}")
PY
shasum -a 256 research/images/$N/boot.img $K $K.unstripped $OV tools/image_tool.py $D/mkimg_ustack.sh | tee $R/SHA256SUMS
exit $rc
