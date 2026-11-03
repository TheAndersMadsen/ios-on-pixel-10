#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything.
# a7-ios-system-dbg5-screen = a7-ios-system-r10-perf's recipe (as live/ustack/mkimg_ustack.sh: r9-apps-ufs's mkimg.sh ufs
# variant, overlay perf-r1 95701ed9) with kernel hk-screen-dbg5 (e731e68 + DBG3 0001 snapshot/KEY/SWIPE + 0002 hk_screen),
# plus blazer_usbcon_snap=1 hk_screen=30, minus the three tokens e731e68 does not read (blazer_aks_wrap,
# blazer_aks_usersession, blazer_persona_log: AKS branch only; dbg1-net and dbg4-ustack drop the same three). SCREEN.md.
set -e
D=research/ios26-phaseb-r1/live/screen; R=$D/receipts
mkdir -p $R
N=${N:-a7-ios-system-dbg5-screen}
K=$D/build/kernel.dbg5-screen
KS=8e22c1ff59caaef03cf0408c3ba8d3ad3e748513ad8eff807277b867ef565d82
echo "$KS  $K" | shasum -a 256 -c -
OV=research/ios26-phaseb-r1/perf/overlays/perf-r1.ovl
OVS=95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55
echo "$OVS  $OV" | shasum -a 256 -c -
R10="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_log=1 blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_persona_log=1"
ARGS=$(echo "$R10" | tr ' ' '\n' | grep -v -x -e blazer_aks_wrap=1 -e blazer_aks_usersession=1 -e blazer_persona_log=1 | tr '\n' ' ')
ARGS="${ARGS}blazer_usbcon_snap=1 hk_screen=30"
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
grep -q "'hk_screen'" tools/image_tool.py || python3 -I $D/tools/allow_screen.py | tee $R/allow-screen.txt
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
shasum -a 256 research/images/$N/boot.img $K $K.unstripped $OV tools/image_tool.py $D/mkimg_screen.sh | tee $R/SHA256SUMS
exit $rc
