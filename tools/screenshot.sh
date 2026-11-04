#!/usr/bin/env bash
# Save what the phone's screen shows as a PNG on m1box. Never boots, flashes or reboots anything.
#
# Live, during a boot started with tools/live_boot.sh (kernel with DBG3's snapshot, blazer_usbcon_snap=1):
#   tools/screenshot.sh [RUN_DIR | SOCKET] [--step N] [--name NAME] [--scale S] [-o OUT.png]
#     RUN_DIR: a live_boot run dir (its live.env names the socket); default: the newest attempts/*/live-*/ or
#     research/laguna-usb-fix/attempts/live-*/. Asks the running usbcon reader on the Mac for a snapshot
#     (requests 0x67/0x68, every N-th pixel, default 6 = 188x419; the kernel raises N until it fits 160 KiB),
#     copies the reader's .png/.rgb565/.json back and writes OUT (default RUN_DIR/screens/NAME-HHMMSS.png).
#
# After a boot parked in fastboot (kernel with hk_screen=N; ramdump already pulled by run-attempt):
#   tools/screenshot.sh --dump ATTEMPT_DIR|kernel.log [--allow-stale] [--scale S] [-o OUT.png]
#     Decodes the HKSCR1 record (360x803, last periodic/deadline/panic capture) with tools/fb_png.py.
#     Default OUT: ATTEMPT_DIR/screen.png.
#
# Prints the PNG's path last. Exit 0 saved; 2 usage; 3 no picture; 4 stale record or reader refused.
# research/ios26-phaseb-r1/live/SCREEN.md. SCREENSHOT_MAC: test double for the phone-bridge `mac` command.
set -euo pipefail
ROOT=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
MAC=${SCREENSHOT_MAC:-$HOME/.local/share/phone-bridge/bin/mac}
usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
target='' dump='' step=6 name=screen scale=1 out='' stale=()
while [ $# -gt 0 ]; do
    case $1 in
        --dump) [ $# -ge 2 ] || usage; dump=$2; shift 2;;
        --step) [ $# -ge 2 ] || usage; step=$2; shift 2;;
        --name) [ $# -ge 2 ] || usage; name=$2; shift 2;;
        --scale) [ $# -ge 2 ] || usage; scale=$2; shift 2;;
        -o|--output) [ $# -ge 2 ] || usage; out=$2; shift 2;;
        --allow-stale) stale=(--allow-stale); shift;;
        -h|--help) usage;;
        -*) usage;;
        *) [ -z "$target" ] || usage; target=$1; shift;;
    esac
done
case $scale in [1-8]) ;; *) echo 'screenshot: --scale 1..8' >&2; exit 2;; esac

if [ -n "$dump" ]; then
    [ -z "$target" ] || usage
    args=("$dump" --scale "$scale" "${stale[@]}")
    [ -z "$out" ] || args+=(-o "$out")
    exec python3 -I "$ROOT/tools/fb_png.py" "${args[@]}"
fi

case $step in ''|*[!0-9]*) echo 'screenshot: --step 1..64' >&2; exit 2;; esac
{ [ "$step" -ge 1 ] && [ "$step" -le 64 ]; } || { echo 'screenshot: --step 1..64' >&2; exit 2; }
[[ $name =~ ^[A-Za-z0-9_-]{1,24}$ ]] || { echo 'screenshot: --name is 1..24 of [A-Za-z0-9_-]' >&2; exit 2; }

sock='' run=''
if [ -z "$target" ]; then
    run=$(ls -1dt "$ROOT"/attempts/*/live-*/ "$ROOT"/research/laguna-usb-fix/attempts/live-*/ 2>/dev/null | head -1 || true)
    [ -n "$run" ] || { echo 'screenshot: no live_boot run found; give RUN_DIR or SOCKET' >&2; exit 2; }
    run=${run%/}
elif [ -d "$target" ]; then
    run=$(cd -P "$target" && pwd -P)
else
    sock=$target
fi
if [ -n "$run" ]; then
    [ -f "$run/live.env" ] || { echo "screenshot: $run has no live.env" >&2; exit 2; }
    sock=$(sed -n 's/^LIVE_SOCK=//p' "$run/live.env" | tail -1)
    [ -n "$sock" ] || { echo "screenshot: no LIVE_SOCK in $run/live.env" >&2; exit 2; }
fi
case $sock in /*) ;; *) echo "screenshot: socket must be an absolute Mac path: $sock" >&2; exit 2;; esac

stamp=$(date +%H%M%S)
reply=$(cd "$ROOT" && "$MAC" repo --force -- python3 -I tools/usbcon.py --control-socket "$sock" --snapshot \
            --snap-step "$step" --snap-name "$name" 2>/dev/null) && rc=0 || rc=$?
fields=$(printf '%s' "$reply" | python3 -I -c '
import json, sys
try:
    r = json.loads(sys.stdin.read() or "{}")
except ValueError:
    r = {}
s = r.get("snapshot") or {}
print(r.get("state", "unknown"), s.get("png", ""), s.get("width", 0), s.get("height", 0), s.get("step", 0),
      s.get("took_us", 0), (r.get("detail") or r.get("error") or "").replace(" ", "_") or "-")
')
read -r state png w h got_step took detail <<<"$fields"
if [ "$rc" != 0 ] || [ "$state" != snapshot ] || [ -z "$png" ]; then
    echo "screenshot: the reader did not take a snapshot (state $state: ${detail//_/ }); reply:" >&2
    printf '%s\n' "$reply" >&2
    exit 4
fi
# The reader names its files by absolute Mac path (live_boot runs it with --output under the Mac copy of the run dir, e.g.
# /Users/x/Developer/personal/hackios/attempts/<id>/live-*/usbcon/usbcon.log.snaps/0001-screen.png) or relative to the
# Mac checkout. Copy them back with `mac --cd MACDIR -- cat` (byte exact; `mac repo --back` refuses paths outside the
# tracked tree, such as attempts/): OUT.rgb565 and OUT.json beside OUT, which fb_png renders from the raw frame.
mac_dir=''
[ -z "$run" ] || mac_dir=$(sed -n 's/^LIVE_MAC_DIR=//p' "$run/live.env" | tail -1)
if [ -z "$mac_dir" ] && [ -f "$HOME/.local/share/phone-bridge/lib.sh" ]; then
    mac_dir=$(. "$HOME/.local/share/phone-bridge/lib.sh"; pb_mirror_of "$ROOT" || true)
fi
mac_dir=${mac_dir:-Developer/personal/hackios}
if [ -z "$out" ]; then
    dir=${run:-$ROOT}/screens
    out=$dir/$name-$stamp.png
fi
mkdir -p "$(dirname "$out")"
stem=${png%.png}
fetch() {   # MAC_PATH LOCAL
    if "$MAC" --cd "$mac_dir" -- cat "$1" > "$2.part" 2>/dev/null && [ -s "$2.part" ]; then mv "$2.part" "$2"; else rm -f "$2.part"; return 1; fi
}
fetch "$stem.rgb565" "${out%.png}.rgb565" || { echo "screenshot: could not copy $stem.rgb565 back from the Mac (dir $mac_dir)" >&2; exit 4; }
fetch "$stem.json" "${out%.png}.json" || true
size=$(stat -c %s "${out%.png}.rgb565")
[ "$size" = $((w * h * 2)) ] || { echo "screenshot: $stem.rgb565 is $size bytes, expected $((w * h * 2)) for ${w}x${h}" >&2; exit 4; }
python3 -I "$ROOT/tools/fb_png.py" --rgb565 "${out%.png}.rgb565" --size "${w}x${h}" --scale "$scale" -o "$out" >/dev/null
echo "screenshot: ${w}x${h} (step $got_step, kernel ${took} us) from $sock; reader copy $png (Mac)" >&2
echo "$out"
