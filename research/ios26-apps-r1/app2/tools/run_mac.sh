#!/bin/sh
# Mac only (repo root). HOST ONLY: never boots anything.
# 1. verify kernel, dylib and overlay against their m1box hashes; release-header consumer on perf-r1 -> app2-r1;
# 2. build and check a7-ios-system-app2 with a7-ios-system-r10-perf's exact recipe (ios26-phaseb-r1/perf/tools/run_mac.sh,
#    itself r9-apps-ufs's) where only --kernel/--kernel-sha and --var-overlay/--var-overlay-sha change;
# 3. print the cmdline and manifest diff against r10-perf.
set -eu
A=research/ios26-apps-r1/app2; R=$A/receipts
BASE=research/ios26-phaseb-r1/perf/overlays/perf-r1.ovl
OVL=$A/overlays/app2-r1.ovl
K=$A/build/kernel.rootview-bl-app2
KS=b875e3e30d643b5b82965e6a6470dd9a4017a6e57a33e73a859b6e594dcb0d13
OSHA=0eb06481d31376b95684dbc6bc53a005adff7ae3e03e967a983f46e41605755e
CUO=research/ios26-opt-20261102/combined_ui_overlay
X=research/ios26-release-r1/work/xnu
printf '%s  %s\n%s  %s\n%s  %s\n%s  %s\n' $KS $K $OSHA $OVL 95701ed9bf56e7e7b13d9b50af02d05daf007206fc10ad5aed861879ee883e55 $BASE \
  a630a41b80d15a2726105217d1c81d66d9348ccc0198bc7ec5b93f34e62d5837 $A/out/hk_stderr_console.dylib | shasum -a 256 -c - | tee $R/inputs-verify.txt
for h in kern/hk_exec_rules.h miscfs/ramfs/varfs_overlay.h miscfs/ramfs/varfs_tsv.h; do
  git -C $X show hk-sandbox-token:bsd/$h | cmp -s "$CUO/inputs/r1/bsd/$h" - && echo "hk-sandbox-token == pinned $h" || echo "hk-sandbox-token DIFFERS from pinned $h"
done | tee $R/release-headers.txt
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
xcrun clang -arch arm64 -DBLAZER=1 -DARM64_BOARD_CONFIG_SWEET=1 -O1 -g -Wall -Wextra -Werror \
  -fsanitize=address,undefined -fno-sanitize-recover=all -idirafter "$CUO/inputs/r1/bsd" $A/tools/app2_consumer.c -o $T/consumer
$T/consumer $BASE $OVL | tee $R/consumer.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_log=1 blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_persona_log=1"
N=a7-ios-system-app2
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
shasum -a 256 tools/image_tool.py | tee $R/image_tool.sha256
python3 -I tools/image_tool.py image $N --kernel $K --kernel-sha $KS \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OVL --var-overlay-sha $OSHA --phone-args "$ARGS" --phone-deadline 300 > $R/image-build.txt 2>&1 || { tail -40 $R/image-build.txt; exit 1; }
tail -3 $R/image-build.txt
python3 -I tools/image_tool.py check research/images/$N | tee $R/image-check.txt
python3 -I - research/images/a7-ios-system-r10-perf/manifest.json research/images/$N/manifest.json <<'PY' | tee $R/manifest-diff.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']}; tokens {len(ta)} -> {len(tb)}")
print('cmdline identical (same tokens, same order)' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))} order_same={[t for t in ta if t in tb] == [t for t in tb if t in ta]}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:300]} -> {json.dumps(b.get(k), sort_keys=True)[:300]}")
PY
shasum -a 256 research/images/$N/* $OVL $K $A/out/hk_stderr_console.dylib $A/tools/app2_overlay.py $A/tools/app2_consumer.c $A/tools/run_mac.sh tools/image_tool.py | tee $R/SHA256SUMS
