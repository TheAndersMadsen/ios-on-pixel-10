#!/usr/bin/env bash
# live_boot.sh: tools/bootios exactly as hackios-boot runs it today, plus the live XNU console
# (tools/usbcon.py on the Mac) streamed to a timestamped file on m1box, with grep-able markers.
#
#   tools/live_boot.sh <image> <name> [--mach <kernel>] [--wait <s>] [--sync-tools] [--no-console] [--ui-test]
#
# Run on m1box from the hackios checkout. The phone must already be in fastboot, as for bootios.
# Writes research/laguna-usb-fix/attempts/live-<ts>-<name>/:
#   console.txt   every console/usbcon line, "<wall HH:MM:SS.mmm> <line>"
#   bootios.txt   hackios-boot's output, same stamps
#   markers.txt   "LIVEBOOT <wall> +<s> <MARK> <detail>" lines (also printed); see MARKS below
#   live.env      LIVE_SOCK / LIVE_RUN / LIVE_MAC_DIR / LIVE_MARKERS, for tools/ui_settings_test.py
#   usbcon/       the reader's raw stream (.log .times .json) and snapshots, copied back from the Mac
#
# Sharing the USB device: run-attempt's usb_log opens only 1209:0001 (the shim's gadget); usbcon opens only
# 1209:0002/0003 (XNU's gadget, after the shim's is gone). Neither claims an interface; both use EP0 control
# transfers. p29/p32 ran exactly this pair. usbcon's own lock (/tmp/hackios-usbcon-UID.lock on the Mac)
# allows one console reader; input/snapshot clients talk to it through LIVE_SOCK and never open USB.
# If the reader cannot start (lock held, socket name taken), the boot is NOT started.
#
# --sync-tools copies m1box's tools/usbcon.py over the Mac checkout's copy first (mac repo --overwrite);
# without it the Mac's own usbcon.py runs, and KEY/SWIPE/snapshot need the new one.
# --no-console runs hackios-boot alone (as today), still stamped.
# --ui-test also runs tools/ui_settings_test.py on this run (waits for UI_READY; output ui_test.out, report ui_test.json),
# with extra arguments from LIVE_UI_ARGS; it is stopped if the boot ends first.
# Env: USBCON_PY (Mac python with pyusb, default /tmp/tegu-venv/bin/python), LIVE_ATTEMPTS (default research/laguna-usb-fix/attempts).
set -euo pipefail
ROOT=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$ROOT"
PB=${LIVE_PB:-$HOME/.local/share/phone-bridge/bin}     # LIVE_PB/LIVE_MAC_DIR: test doubles only
export PATH="$PB:$PATH"

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
image='' name='' sync=0 console=1 uitest=0 boot_args=() wait=180
while [ $# -gt 0 ]; do
    case $1 in
        --mach) [ $# -ge 2 ] || usage; boot_args+=(--mach "$2"); shift 2;;
        --wait) [ $# -ge 2 ] || usage; wait=$2; boot_args+=(--wait "$2"); shift 2;;
        --sync-tools) sync=1; shift;;
        --no-console) console=0; shift;;
        --ui-test) uitest=1; shift;;
        -h|--help) usage;;
        -*) usage;;
        *) if [ -z "$image" ]; then image=$1; elif [ -z "$name" ]; then name=$1; else usage; fi; shift;;
    esac
done
[ -n "$image" ] && [ -n "$name" ] || usage
[ "$uitest" = 0 ] || [ "$console" = 1 ] || { echo "live_boot: --ui-test needs the console" >&2; exit 2; }
case $wait in ''|*[!0-9]*) echo "live_boot: --wait needs whole seconds" >&2; exit 2;; esac
case $name in *[!A-Za-z0-9._-]*) echo "live_boot: name may use only A-Za-z0-9._-" >&2; exit 2;; esac
[ -f "$image" ] || { echo "live_boot: image not found: $image" >&2; exit 2; }
image=$(realpath "$image")

ts=$(date +%Y%m%d-%H%M%S)
rel=${LIVE_ATTEMPTS:-research/laguna-usb-fix/attempts}/live-$ts-$name
case $rel in /*) RUN=$rel;; *) RUN=$ROOT/$rel;; esac
mkdir -p "$RUN"
SOCK=/tmp/hackios-live-$ts-$$.sock
MAC_DIR=${LIVE_MAC_DIR:-$(. "$HOME/.local/share/phone-bridge/lib.sh"; pb_mirror_of "$ROOT")}
MARKS=$RUN/markers.txt
: > "$MARKS"
T0=$(date +%s.%N)
cat > "$RUN/live.env" <<EOF
LIVE_RUN=$RUN
LIVE_NAME=$name
LIVE_SOCK=$SOCK
LIVE_MAC_DIR=$MAC_DIR
LIVE_MARKERS=$MARKS
LIVE_CONSOLE=$RUN/console.txt
LIVE_T0=$T0
EOF
echo "live_boot: run $RUN"
since() { python3 -c "import time;print(f'{time.time()-$T0:.1f}')"; }

# stamp KIND OUT: stdin lines -> OUT with a wall stamp; markers -> MARKS and stdout.
# MARKS (one-shot unless noted): CONSOLE_CONNECTED USB_CONFIGURED DISPLAY ROOT LAUNCHD BACKBOARDD SPRINGBOARD
# TOUCH_CLIENT BUTTON_CLIENT FRAMES UI_READY (all of SPRINGBOARD, TOUCH_CLIENT, BUTTON_CLIENT, FRAMES),
# repeating: APP <name>, CRASH <proc>, EXIT <service> <why>, INPUT <state> <command>, LIVE_DONE gen= result=,
# SNAPSHOT <png>, PANIC, DEADLINE, CONSOLE_GONE, CONSOLE_END, ATTEMPT_DIR, EP0_LIVE, PARKED, BOOT_RC.
STAMP_PY=$(cat <<'PY'
import json, re, sys, time
kind, out, marks, t0 = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
once = [
    ('CONSOLE_CONNECTED', r'^usbcon: connected: (.*)'),
    ('USB_CONFIGURED', r'blazer-usbcon: configured'),
    ('DISPLAY', r'tensor-dpu: attached: (.*)'),
    ('ROOT', r'(blazer-root: .*rooting on \S+|BSD root: \S+)'),
    ('LAUNCHD', r'com\.apple\.xpc\.launchd\|'),
    ('BACKBOARDD', r'Successfully spawned (backboardd)\['),
    ('SPRINGBOARD', r'Successfully spawned (SpringBoard)\['),
    ('TOUCH_CLIENT', r'SWEET HID: SweetHIDTouch open by'),
    ('BUTTON_CLIENT', r'SWEET HID: SweetHIDButtons open by'),
    # hk_top's frame count, or (without hk_top) SweetFramebuffer's nonzero swap rate
    ('FRAMES', r'HK TOP: t=(\d+) frames\+([1-9]\d*)|SWEET FB: rate swaps ([1-9][\d.]*/s|0\.[1-9]/s)'),
]
every = [
    ('APP', r'UIKitApplication:com\.apple\.(\w+)\[\w+\]\[[\w-]+\] \[\d+\]\) <Notice>: Successfully spawned'),
    ('CRASH', r'^CRASH (\S+)'),
    ('EXIT', r'\(user/501/com\.apple\.(\w+) \[\d+\]\) <Notice>: exited due to (SIG\w+|exit\([1-9]\d*\))'),
    ('LIVE_DONE', r'HK LIVE done (gen=\d+ result=\d+)'),
    ('PANIC', r'^panic\((.{0,120})'),
    ('DEADLINE', r'(blazer-root: deadline .{0,60})'),
    ('CONSOLE_GONE', r'^usbcon: (device gone .*|console unavailable .*)'),
    ('CONSOLE_END', r'^usbcon: end: (.*)'),
    ('ATTEMPT_DIR', r'^\[run-attempt\] attempt dir: (.*)'),
    ('EP0_LIVE', r'(EP0 live at watch t\+\d+s)'),
    ('PARKED', r'(PARKED in fastboot at watch t\+\d+s)'),
    ('ATTEMPT', r'^attempt: (.*)'),
]
once = [(m, re.compile(p)) for m, p in once]
every = [(m, re.compile(p)) for m, p in every]
seen = set()
fo = open(out, 'a', buffering=1)
fm = open(marks, 'a', buffering=1)

def mark(name, detail=''):
    now = time.time()
    line = f'LIVEBOOT {time.strftime("%H:%M:%S", time.localtime(now))}.{int(now % 1 * 1000):03d} +{now - t0:.1f} {name} {detail}'.rstrip()
    fm.write(line + '\n')
    print(line, flush=True)

for raw in sys.stdin.buffer:
    text = raw.decode(errors='replace').rstrip('\r\n')
    now = time.time()
    fo.write(f'{time.strftime("%H:%M:%S", time.localtime(now))}.{int(now % 1 * 1000):03d} {text}\n')
    body = re.sub(r'^\[\s*\d+\.\d+\] ', '', text)      # usbcon's own "[  12.34] " prefix
    for m, rx in once:
        if m not in seen:
            hit = rx.search(body)
            if hit:
                seen.add(m)
                mark(m, ' '.join(g for g in hit.groups() if g))
                if {'SPRINGBOARD', 'TOUCH_CLIENT', 'BUTTON_CLIENT', 'FRAMES'} <= seen and 'UI_READY' not in seen:
                    seen.add('UI_READY')
                    mark('UI_READY')
    for m, rx in every:
        hit = rx.search(body)
        if hit:
            mark(m, ' '.join(g for g in hit.groups() if g))
    if body.startswith('usbcon: input '):
        try:
            r = json.loads(body[len('usbcon: input '):])
            if r.get('state') == 'snapshot':
                mark('SNAPSHOT', r['snapshot'].get('png', ''))
            else:
                mark('INPUT', f"{r.get('state')} {json.dumps(r.get('command', {}), separators=(',', ':'))} {r.get('error', '')}")
        except (ValueError, KeyError, AttributeError):
            mark('INPUT', 'unparsed')
PY
)
stamp() { python3 -I -u -c "$STAMP_PY" "$1" "$2" "$MARKS" "$T0"; }
note() { echo "live_boot: $*" | stamp note "$RUN/console.txt"; echo "live_boot: $*"; }

# --- the Mac's usbcon.py
local_sha=$(sha256sum tools/usbcon.py | cut -d' ' -f1)
mac_sha=$(mac -- sh -c "shasum -a 256 $MAC_DIR/tools/usbcon.py 2>/dev/null | cut -d' ' -f1" || true)
if [ "$local_sha" != "$mac_sha" ]; then
    if [ "$sync" = 1 ]; then
        mac repo --force --sync tools/usbcon.py --overwrite -- true >/dev/null
        mac_sha=$(mac -- sh -c "shasum -a 256 $MAC_DIR/tools/usbcon.py | cut -d' ' -f1")
        [ "$local_sha" = "$mac_sha" ] || { echo "live_boot: could not sync tools/usbcon.py to the Mac" >&2; exit 2; }
        note "synced tools/usbcon.py to the Mac ($local_sha)"
    else
        note "warning: the Mac runs its own tools/usbcon.py (${mac_sha:-missing}), not m1box's ($local_sha); pass --sync-tools for KEY/SWIPE/snapshot"
    fi
fi
echo "usbcon_sha256=$mac_sha" >> "$RUN/live.env"

cpid='' cgid=''
# The reader runs in its own session (cgid): stopping it closes ssh, so the Mac's runner sends usbcon SIGTERM and
# usbcon writes its .json; the stamp filter (cpid) is outside that session and drains to EOF.
stop_console() {
    [ -n "$cpid" ] || return 0
    [ -n "$cgid" ] || cgid=$(cat "$RUN/.console.pgid" 2>/dev/null || true)
    if [ -n "$cgid" ]; then
        kill -TERM -- "-$cgid" 2>/dev/null || true
        for _ in $(seq 1 15); do kill -0 "$cpid" 2>/dev/null || break; sleep 1; done
        kill -KILL -- "-$cgid" 2>/dev/null || true
    fi
    wait "$cpid" 2>/dev/null || true
    cpid='' cgid=''
}
trap 'stop_console' EXIT
trap 'echo "live_boot: interrupted" >&2; exit 130' INT TERM

if [ "$console" = 1 ]; then
    # The reader outlives the whole boot window; it ends on its own 45 s after the gadget goes for good.
    ctimeout=$(( (wait > 300 ? wait : 300) + 20 + wait + 300 ))
    py=${USBCON_PY:-/tmp/tegu-venv/bin/python}
    note "console: $py tools/usbcon.py on the Mac, socket $SOCK, timeout ${ctimeout}s, raw stream $rel/usbcon/"
    rm -f "$RUN/.console.pgid"
    setsid bash -c 'echo $$ > "$5"; exec 2>&1; exec mac repo --force -- "$1" -u tools/usbcon.py --output "$2/usbcon.log" \
            --control-socket "$3" --timeout "$4" --gone-exit 45 --stats 30' \
        live-console "$py" "$rel/usbcon" "$SOCK" "$ctimeout" "$RUN/.console.pgid" | stamp console "$RUN/console.txt" &
    cpid=$!
    # A reader that can't start (lock held, socket taken, no pyusb) dies at once: don't boot without it.
    for _ in 1 2 3 4 5 6; do sleep 1; kill -0 "$cpid" 2>/dev/null || break; done
    if ! kill -0 "$cpid" 2>/dev/null; then
        tail -5 "$RUN/console.txt" >&2
        echo "live_boot: the console reader exited before the boot; not booting. See $RUN/console.txt" >&2
        cpid=''
        exit 3
    fi
    echo "LIVEBOOT $(date +%H:%M:%S.%3N) +$(since) CONSOLE_WAITING $SOCK" | tee -a "$MARKS"
fi
upid=''
if [ "$uitest" = 1 ]; then
    # shellcheck disable=SC2086  # LIVE_UI_ARGS is a word list by design
    python3 -I tools/ui_settings_test.py "$RUN" ${LIVE_UI_ARGS:-} > "$RUN/ui_test.out" 2>&1 &
    upid=$!
    echo "LIVEBOOT $(date +%H:%M:%S.%3N) +$(since) UI_TEST_STARTED pid $upid" | tee -a "$MARKS"
fi

# --- the boot, exactly as hackios-boot runs it
note "boot: hackios-boot $image $name ${boot_args[*]}"
set +e
# --force: the Mac checkout may lag m1box (uncommitted edits there block a pull); tools/bootios is the same file.
"$PB/mac-repo" --force --back-attempt -- env ANDROID_SERIAL="${ANDROID_SERIAL:-56141FDCH0009X}" tools/bootios "$image" "$name" "${boot_args[@]}" 2>&1 | stamp bootios "$RUN/bootios.txt"
rc=${PIPESTATUS[0]}
set -e
echo "LIVEBOOT $(date +%H:%M:%S.%3N) +$(since) BOOT_RC $rc" | tee -a "$MARKS"
if [ -n "$upid" ] && kill -0 "$upid" 2>/dev/null; then
    kill -TERM "$upid" 2>/dev/null || true
    echo "LIVEBOOT $(date +%H:%M:%S.%3N) +$(since) UI_TEST_STOPPED the boot ended before the walk finished" | tee -a "$MARKS"
fi
[ -z "$upid" ] || wait "$upid" 2>/dev/null || true

if [ -n "$cpid" ]; then
    # The phone parked: the reader sees its device go and stops within ~45 s. Give it 60.
    for _ in $(seq 1 60); do kill -0 "$cpid" 2>/dev/null || break; sleep 1; done
    stop_console
    mac repo --force --back "$rel/usbcon" -- true >/dev/null 2>&1 || note "warning: could not copy $rel/usbcon back from the Mac"
fi
attempt=$(sed -n 's/^.*\[run-attempt\] attempt dir: //p' "$RUN/bootios.txt" | tail -1)
{
    echo "LIVE_RUN=$RUN"
    echo "ATTEMPT=${attempt:-none}"
    echo "BOOT_RC=$rc"
} >> "$RUN/live.env"
echo "live_boot: run $RUN"
echo "live_boot: attempt ${attempt:-none}"
echo "live_boot: markers:"; sed 's/^/  /' "$MARKS"
[ ! -f "$RUN/ui_test.json" ] || echo "live_boot: ui test $(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['verdict'])" "$RUN/ui_test.json") ($RUN/ui_test.json)"
exit "$rc"
