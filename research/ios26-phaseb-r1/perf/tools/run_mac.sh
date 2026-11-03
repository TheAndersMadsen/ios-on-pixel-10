#!/bin/sh
# Mac only (repo root). HOST ONLY: never boots anything.
# 1. verify the hk_mainwatch build (tools/build_mainwatch.sh) against its receipt;
# 2. compose the perf overlay on top of settings-btdisabled-r1 (ee7554b9), decode-diff it, run the release-header consumer;
# 3. build and check a7-ios-system-r10-perf with a7-ios-system-r9-apps-ufs's exact recipe
#    (ios26-apps-r1/usersession/mkimg.sh, ufs variant) where only --var-overlay/--var-overlay-sha change;
# 4. print the cmdline and manifest diff against r9-apps-ufs.
set -eu
REPO=$(pwd); P=research/ios26-phaseb-r1/perf; R=$P/receipts
BASE=research/ios26-phaseb-r1/settings/overlays/settings-btdisabled-r1.ovl
BASESHA=ee7554b9aba04d437992e3dbea73a9bdd5c444273b6cecd6fa3d9cfbf950a3ca
LIB=$P/out/hk_mainwatch.dylib
OVL=$P/overlays/perf-r1.ovl
CUO=research/ios26-opt-20261102/combined_ui_overlay
mkdir -p $R $P/overlays $P/out
# 1
grep -E 'src/hk_mainwatch.c|out/hk_mainwatch.dylib' $R/mainwatch/SHA256SUMS | shasum -a 256 -c - | tee $R/mainwatch-verify.txt
# 2
echo "$BASESHA  $BASE" | shasum -a 256 -c - | tee $R/base.sha256
[ -e $OVL ] || python3 -I $P/tools/perf_overlay.py $BASE $LIB $OVL > $R/transform.json
cat $R/transform.json
python3 -I research/ios26-phaseb-r1/accel-wait/build-mac/decode_diff.py $BASE $OVL | tee $R/decode-diff.txt
for h in kern/hk_exec_rules.h miscfs/ramfs/varfs_overlay.h miscfs/ramfs/varfs_tsv.h; do
  cmp -s "$CUO/inputs/r1/bsd/$h" "research/ios26-release-r1/work/xnu/bsd/$h" && echo "live == pinned $h" || echo "live DIFFERS from pinned $h"
done | tee $R/release-headers.txt
xcrun clang -arch arm64 -DBLAZER=1 -DARM64_BOARD_CONFIG_SWEET=1 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-sanitize-recover=all -idirafter "$CUO/inputs/r1/bsd" $P/tools/perf_consumer.c -o $P/out/perf_consumer
$P/out/perf_consumer $BASE $OVL | tee $R/consumer.txt
OSHA=$(shasum -a 256 $OVL | cut -d' ' -f1)
# 3: r9-apps-ufs recipe (mkimg.sh, v=ufs), overlay swapped
K=research/ios26-apps-r1/usersession/build/kernel.rootview-bl-aks-us2
KS=d7f47431164650c96cbab32dde384a288c321f67adcaf69f37eccc3116133186
echo "$KS  $K" | shasum -a 256 -c -
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_log=1 blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_persona_log=1"
N=a7-ios-system-r10-perf
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
python3 -I tools/image_tool.py image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OVL --var-overlay-sha $OSHA --phone-args "$ARGS" --phone-deadline 300 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I tools/image_tool.py check research/images/$N | tee $R/image-check.txt
# 4
python3 -I - research/images/a7-ios-system-r9-apps-ufs/manifest.json research/images/$N/manifest.json <<'EOF' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']}; tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:300]} -> {json.dumps(b.get(k), sort_keys=True)[:300]}")
EOF
shasum -a 256 research/images/$N/boot.img $OVL $LIB $P/tools/perf_overlay.py $P/tools/perf_consumer.c $P/tools/run_mac.sh tools/image_tool.py | tee $R/SHA256SUMS
