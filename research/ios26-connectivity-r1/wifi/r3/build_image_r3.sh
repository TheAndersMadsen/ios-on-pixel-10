#!/bin/sh
# Mac only, from the repo root. Builds the W1 r3 image from the kept secret (research/ios26-wifi-r1/secret/wifi.secret, mode 600).
# Prints sizes, hashes and yes/no facts only: never the name, the password or the PMK. Touches no phone.
#
#   sh research/ios26-connectivity-r1/wifi/r3/build_image_r3.sh [NAME]     build research/images/NAME (default a7-wifi-join-r3)
#   sh research/ios26-connectivity-r1/wifi/r3/build_image_r3.sh wipe       after the boot: delete the composed overlays and the images
#
# r3 = r2 (r2/build_image_r2.sh) with one change: kernel kernel.rootview-wifi-r3 (hk-wifi-join2 = hk-wifi-pass eef94c6 + the two-method join,
# r3/FIX.md). Overlay record BWN2 (PMK + passphrase), composed fresh from the kept secret. The boot line is r1's, byte for byte
# (receipts/w1-cmdline.txt, sha256 913ab8d9...): the methods need no boot argument. THE IMAGE HOLDS THE PASSWORD.
set -eu
K=research/ios26-dualboot-r8/rootview/kernel.rootview-wifi-r3
KSHA=6ebd1a64686859d3a885a5e7b35c42e625ed7adbdedcc3df59a0df091b81356c
SEC=research/ios26-wifi-r1/secret
CWJ=research/ios26-connectivity-r1/wifi/tools/compose_wifi_join.py
LINE_SHA=913ab8d96ab64794362ce967ddd6f7ac341d81528f765ae18c2cb99322669459
PA='blazer_touch=1 blazer_touch_bars=1 atm_diagnostic_config=0x400 blazer_ufs_multi=1 blazer_ufs_spin_us=300 blazer_ufs_hold=1 blazer_ssbs=3 hk_fb_scale=1 hk_fb_fast=1 hk_fb_refresh=60 hk_overlay=0xA0080081 hk_top=30 blazer_battery=1 blazer_mem=13 blazer_thermal=2 blazer_thermal_fast=1 blazer_thermal_panic_c=70 blazer_gov=1 blazer_gov_cap=16 blazer_gov_stages=15 blazer_gov_b=40 blazer_usbcon=1 blazer_usbcon_ch9=1 blazer_usbcon_input=1 blazer_rtc=1 blazer_rtc_bounds=1 blazer_battery_status=1 blazer_aks_log=1 blazer_wifi=1 blazer_wifi_stage=8 blazer_wifi_join=1'
s256() { shasum -a 256 "$1" | cut -d' ' -f1; }
die() { echo "build_image_r3: $*" >&2; exit 1; }
[ -f tools/image_tool.py ] && [ -d research/ios26-wifi-r1 ] || die 'run from the repo root on the Mac'
umask 077

if [ "${1:-}" = wipe ]; then
	for f in "$SEC"/a7-r3-wifi-join*.ovl; do [ -e "$f" ] && rm -f "$f" && echo "removed $f"; done
	for f in "$SEC"/a7-wifi-join-r*-image.log "$SEC"/a7-wifi-join-r*-check.log; do [ -e "$f" ] && rm -f "$f" && echo "removed $f"; done
	for d in research/images/a7-wifi-join-r*; do [ -d "$d" ] && rm -rf "$d" && echo "removed $d"; done
	python3 -I research/ios26-wifi-r1/tools/mkwifisecret.py wipe
	exit 0
fi
NAME=${1:-a7-wifi-join-r3}
OVL=$SEC/a7-r3-wifi-join-${NAME#a7-wifi-join-}.ovl
case "$NAME" in a7-wifi-join-r[0-9]*) ;; *) die "name: a7-wifi-join-rN";; esac
[ -e "research/images/$NAME" ] && die "research/images/$NAME exists (wipe it first)"

# 1. Kernel: the pinned build, with both methods in it
[ "$(s256 "$K")" = "$KSHA" ] || die "$K: sha256 is not the pinned $KSHA"
for t in 'join: passphrase given to the firmware' 'join: method 1: Android' 'join: method 2: r2' 'join: keyed by method %u' 'sup_wpa to 1 before the interface is up' 'the firmware never answered M1' 'the image holds a network' blazer_wifi_join; do
	LC_ALL=C grep -qaF "$t" "$K" || die "kernel lacks: $t"
done
echo "kernel ok: $KSHA"

# 2. The secret file: readable, LF line ends, a passphrase (not a 64-hex PSK). Yes/no only
python3 -I research/ios26-wifi-r1/tools/mkwifisecret.py check | sed 's/^/secret: /'
python3 -I research/ios26-wifi-r1/tools/mkwifisecret.py check | grep -q 'BWN2 possible: yes' || die 'BWN2 needs the passphrase itself in password='

# 3. Overlay: A7-r3's + one group-26 BWN2 record. The composer never overwrites; an existing one is reused if the reader checks pass
if [ -e "$OVL" ]; then
	echo "overlay: reusing $OVL"
else
	python3 -I "$CWJ" overlay --out "$OVL" | grep -E '"(bytes|sha256|blob|has_passphrase|records|net_bytes)"' | sed 's/^/overlay: /'
fi
python3 -I "$CWJ" check "$OVL" | grep -q '"net_bytes": 176' || die 'overlay: its network record is not BWN2'
OSHA=$(s256 "$OVL")
python3 -I "$CWJ" check "$OVL" | grep -q '"has_passphrase": true' || die 'overlay: no passphrase in its record'
python3 -I "$CWJ" check "$OVL" | grep -q '"applied_by_mask": false' || die 'overlay: group 26 would be applied'

# 4. The line, as r1's
[ "$(python3 -I "$CWJ" cmdline 2>/dev/null | tr -d '\n' | shasum -a 256 | cut -d' ' -f1)" = "$LINE_SHA" ] || die 'composer cmdline is not r1s'

# 5. Image (A7-READY step 6, r3's flags, as r1)
python3 -I tools/image_tool.py image "$NAME" --kernel "$K" --kernel-sha "$KSHA" \
	--phone-root --phone-route md0-mountroot --qemu-run overlay-1 --window-base 0x882000000 --bootcpu 0x200 --cpus 5 --canvas 1125x2511 \
	--var-overlay "$OVL" --var-overlay-sha "$OSHA" --phone-args "$PA" --phone-deadline 300 > "$SEC/$NAME-image.log" 2>&1 \
	|| { tail -5 "$SEC/$NAME-image.log"; die 'image_tool image failed'; }
python3 -I tools/image_tool.py check "research/images/$NAME" > "$SEC/$NAME-check.log" 2>&1 || { tail -5 "$SEC/$NAME-check.log"; die 'image_tool check failed'; }
chmod -R go-rwx "research/images/$NAME"
L=$(python3 -I -c 'import json,sys,hashlib; print(hashlib.sha256(json.load(open(sys.argv[1]))["cmdline"].encode()).hexdigest())' "research/images/$NAME/manifest.json")
[ "$L" = "$LINE_SHA" ] || die "manifest cmdline sha256 $L is not r1's $LINE_SHA"
echo "image: research/images/$NAME, mode 700, cmdline = r1's ($LINE_SHA)"
echo "boot.img sha256 $(s256 "research/images/$NAME/boot.img")"
echo "unstripped mach for bootios: $K.unstripped $(s256 "$K.unstripped")"
