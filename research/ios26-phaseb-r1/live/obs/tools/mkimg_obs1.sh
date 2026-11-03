#!/bin/sh
# Mac, repo root. HOST ONLY: never boots anything.
# a7-ios-system-obs1 = a7-ios-system-int1's recipe exactly (int/tools/mkimg_int1.sh: r9-apps-ufs route rd=ufsroot0, 5 cores,
# bootcpu 0x200, canvas 1125x2511, window 0x882000000, --qemu-run overlay-1, deadline 900, the same --phone-args and
# --drop-diag, the same private image tool int/tools/image_tool_int1.py) with only:
#   kernel   research/ios26-phaseb-r1/live/obs/build/kernel.obs1 (XNU hk-obs1 = hk-int1 484717f + 0001-hk-obs1.patch)
#   overlay  research/ios26-phaseb-r1/live/obs/overlays/obs1-r1.ovl (int1-r1 + the mirror rule list + hk_logmirror.dylib)
# The command line is int1's, byte for byte (hk-obs1 needs no argument: HKOBS lines and the console budget are on by default).
set -eu
O=research/ios26-phaseb-r1/live/obs; R=$O/receipts; mkdir -p $R
N=a7-ios-system-obs1
K=$O/build/kernel.obs1
KS=b8f00379d9a9f7a51e2b49a322d8ec6d661e7c36c997bab3f31f8a3335cd53c4
OV=$O/overlays/obs1-r1.ovl
OVS=8b4fc793c5b18fecc5ed9cbc5b3a4cc5cecd4e1b7a16d58472829ca77e591cc3
TOOL=research/ios26-phaseb-r1/int/tools/image_tool_int1.py
TOOLS=728bdd21
printf '%s  %s\n%s  %s\n' $KS $K $OVS $OV | shasum -a 256 -c - | tee $R/inputs-verify.txt
shasum -a 256 $TOOL | tee -a $R/inputs-verify.txt | grep -q "^$TOOLS" || { echo "image tool is not int1's ($TOOLS...)" >&2; exit 2; }
# the overlay's mirror list relies on the kernel's DYLD merge and the HKOBS module
for s in "rules' libraries in one DYLD_INSERT_LIBRARIES" 'HKOBS %u %s t=%llu %s: %s' 'hk_conlim'; do
  strings -a $K | grep -qF "$s" && echo "kernel has: $s" || { echo "kernel lacks: $s" >&2; exit 2; }
done | tee -a $R/inputs-verify.txt
ARGS="blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 hk_bright=140 blazer_aks_wrap=1 blazer_keys=1 blazer_power_key=1 blazer_key_delivery=1 blazer_haptic_tap=1 blazer_netstack=1 hk_ustack=Preferences,MobilePhone"
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
print('cmdline identical' if a['cmdline'] == b['cmdline'] else f"cmdline DIFFERS: -{sorted(set(ta)-set(tb))} +{sorted(set(tb)-set(ta))}")
for k in sorted(set(a) | set(b)):
    if a.get(k) != b.get(k):
        print(f"{k}: {json.dumps(a.get(k), sort_keys=True)[:240]} -> {json.dumps(b.get(k), sort_keys=True)[:240]}")
print('CMDLINE', b['cmdline'])
PY
shasum -a 256 research/images/$N/boot.img research/images/$N/payload-usb.bin research/images/$N/manifest.json $K $K.unstripped $OV $TOOL $O/tools/mkimg_obs1.sh | tee $R/SHA256SUMS.image
