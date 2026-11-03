#!/bin/sh
# Mac only (repo root). HOST ONLY: never boots anything.
# a7-ios-system-bt2 = a7-ios-system-r10-perf's recipe (research/ios26-phaseb-r1/perf/tools/run_mac.sh step 3) with:
#   kernel   kernel.bt2 (XNU hk-bt-b2 9aa76a93, parent cc42295 = r10's kernel.rootview-bl-aks-us2 source)
#   overlay  bt2-r1.ovl (perf-r1 with bluetoothd off hk_deny, bluetoothd env BT_HCI_TRANSPORT=H4:POSIX;BT_CHIP=ACI~BT)
#   ADT      --bt-nub: arm-io/bluetooth, transport-encoding 7, local-mac-address 02:00:00:00:00:01 (placeholder)
#   line     - blazer_usbcon_input=1 blazer_aks_log=1 blazer_persona_log=1 (attended keyboard input, Spotlight AKS shape log,
#              apps-lane persona log: diagnostics), + blazer_wifi=1 blazer_wifi_stage=5 blazer_wifi_hold=1 (Wi-Fi firmware up and
#              held: the BT side waits for it) + blazer_bt=5 (HCI bridge). blazer_bt_tx is absent: the kernel takes 0 (gate closed).
# Built with the private copy tools/image_tool_bt2.py (the Mac's tools/image_tool.py acf48b98 + image_tool_bt2.diff).
set -eu
B=research/ios26-connectivity-r1/bluetooth/b2; R=$B/receipts
K=$B/build/kernel.bt2; KS=4cf8224f75767c6f65510de77bf5a8287a897703f234c0fbe5eb9297ef84eb6e
OVL=$B/overlays/bt2-r1.ovl; OSHA=ea452c37999941e88b19efc312a79fe30d7b4a107025a288f4d66e204dc40115
echo "$KS  $K" | shasum -a 256 -c -
echo "$OSHA  $OVL" | shasum -a 256 -c -
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_aks_usersession=1 blazer_wifi=1 blazer_wifi_stage=5 blazer_wifi_hold=1 blazer_bt=5"
N=${1:-a7-ios-system-bt2}
[ ! -e research/images/$N ] || { echo "refusing: research/images/$N exists" >&2; exit 2; }
python3 -I $B/tools/image_tool_bt2.py image $N --kernel $K --kernel-sha $KS --bt-nub \
 --phone-root --phone-route ufsroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
 --var-overlay $OVL --var-overlay-sha $OSHA --phone-args "$ARGS" --phone-deadline 300 > $R/image-build-$N.txt 2>&1 || { tail -40 $R/image-build-$N.txt; exit 1; }
tail -3 $R/image-build-$N.txt
python3 -I $B/tools/image_tool_bt2.py check research/images/$N | tee $R/image-check-$N.txt
python3 -I - research/images/a7-ios-system-r10-perf/manifest.json research/images/$N/manifest.json <<'EOF' | tee $R/manifest-diff-$N.txt
import json, sys
a, b = (json.load(open(p)) for p in sys.argv[1:3])
ta, tb = a['cmdline'].split(), b['cmdline'].split()
print(f"cmdline bytes {a['cmdline_bytes']} -> {b['cmdline_bytes']}; tokens {len(ta)} -> {len(tb)}")
print('cmdline identical' if ta == tb else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:300]} -> {json.dumps(b.get(k), sort_keys=True)[:300]}")
EOF
shasum -a 256 research/images/$N/boot.img $K $OVL $B/tools/image_tool_bt2.py tools/image_tool.py | tee $R/SHA256SUMS-$N
