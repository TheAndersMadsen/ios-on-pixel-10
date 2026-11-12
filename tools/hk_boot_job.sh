#!/bin/bash
# (Stopgap; tools/hk_session.py runs a whole queue with queries, scoreboard diff and a checked return.)
# One physical boot as a debug session: Android -> fastboot -> live_boot (temporary `fastboot boot`) with
# screenshots + autoprobe while the UI is up -> park -> ramdump screen -> back to Android -> return check.
# Usage: tools/hk_boot_job.sh <image-name> <attempt-name> <mach-kernel> [wait-s] [extra-grep] [ui-script]
# Writes ~/hk-logs/<attempt-name>.summary.txt (the thing to read) and prints it at the end.
# End early (image with blazer_usbcon=2; docs/DEBUG-LOOP.md): HK_END_ON=REGEX ends the boot when the console matches,
# HK_END_AFTER=S ends it S seconds after the HOME marker; once, by the usbcon reset op (panic, park, RAM kept for the
# ramdump). Otherwise, and if the reset is refused, the kernel deadline ends it as before.
# HK_QUERIES='drivers; procs 50; ioreg CLASS 4; ...': on an end-on/end-after fire, before the reset, run tools/hkq.py
# batch through the live reader (needs the query gate in the image: hk_query=1 or hk_dbg bit 27); output <run>/queries.txt.
# HK_ABORT_ON=REGEX: a stop condition (e.g. a thermal limit) that ends the boot AT ONCE — no grace, no queries, no shot.
export PATH=$HOME/.local/share/phone-bridge/bin:$HOME/.local/bin:$PATH ANDROID_SERIAL=${ANDROID_SERIAL:?set ANDROID_SERIAL to the phone serial}
cd /srv/dev/repos/personal/hackios
IMG=research/images/$1/boot.img; NAME=$2; MACH=$3; WAIT=${4:-1080}
EXTRA=${5:-'SWEET BL|fixed keys|illegal PA|INVALID_PERSONA|userabort: lsd|registration_verified|varfs-overlay: .* applied|memorystatus_|escape CPU monitor|EXC_RESOURCE|panic'}
UI=${6:-}
END_ON=${HK_END_ON:-}; END_AFTER=${HK_END_AFTER:-}; ABORT_ON=${HK_ABORT_ON:-}; QUERIES=${HK_QUERIES:-}; ended=''
mkdir -p "$HOME/hk-logs"; OUT=$HOME/hk-logs/$NAME.summary.txt; : > "$OUT"
log(){ echo "$(date +%T) $*" | tee -a "$OUT"; }
[ -f "$IMG" ] && [ -f "$MACH" ] || { log "missing $IMG or $MACH"; exit 2; }

infb(){ fastboot devices 2>/dev/null | grep -q 56141; }
if ! infb; then
  if adb get-state 2>/dev/null | grep -q device; then log "adb reboot bootloader"; adb reboot bootloader; fi
  for i in $(seq 1 60); do infb && break; sleep 5; done
fi
infb || { log "NO FASTBOOT after 5 min; aborted"; exit 1; }

log "boot $1 as $NAME (wait $WAIT)"
uiargs=(); [ -n "$UI" ] && uiargs=(--ui-script "$UI")
{ [ -n "$END_ON" ] || [ -n "$END_AFTER" ] || [ -n "$ABORT_ON" ] || [ -n "$QUERIES" ]; } && uiargs+=(--sync-tools)  # the Mac's usbcon.py/hkq.py
bash tools/live_boot.sh "$IMG" "$NAME" --mach "$MACH" --wait "$WAIT" --sync-tools "${uiargs[@]}" \
  < <(sleep 7200) > "$HOME/hk-logs/$NAME.live.log" 2>&1 &
LB=$!
D=''
STARTMARK=$(mktemp); touch -d "-5 seconds" "$STARTMARK"   # only accept a run dir made by THIS job (an aborted earlier run can share the name)
for i in $(seq 1 60); do D=$(find research/laguna-usb-fix/attempts -maxdepth 1 -type d -name "live-*-$NAME" -newer "$STARTMARK" 2>/dev/null | sort | tail -1); [ -n "$D" ] && break; sleep 2; done; rm -f "$STARTMARK"
log "run dir: $D"
# probes: once Home is up, then every 5 min while the boot lives
shot=0; t0=$(date +%s); home=''
while kill -0 $LB 2>/dev/null; do
  sleep 10
  if [ -z "$home" ] && grep -aqE 'SPRINGBOARD|UI_READY' "$D/markers.txt" 2>/dev/null; then
    home=$(( $(date +%s) - t0 )); log "HOME marker at +${home}s"; sleep 45
  fi
  # the reader's own tools (LIVE_TOOLS: tools/mactools.py's verified copy outside the Mac checkout)
  sock=$(sed -n 's/^LIVE_SOCK=//p' "$D/live.env" | tail -1)
  lt=$(sed -n 's/^LIVE_TOOLS=//p' "$D/live.env" | tail -1)
  reset(){ mac repo --force -- python3 -I "${lt:+$lt/}tools/usbcon.py" --control-socket "$sock" --reset-now 2>&1 | tr '\n' ' ' | cut -c1-300; }
  # ABORT_ON first: a stop condition ends the boot AT ONCE, with no grace, no queries and no screenshot.
  if [ -z "$ended" ] && [ -n "$ABORT_ON" ] && grep -aqE -- "$ABORT_ON" "$D/console.txt" 2>/dev/null; then
    ended=1; log "ABORT /$ABORT_ON/: reset op -> $(reset)"; continue
  fi
  why=''
  if [ -z "$ended" ] && [ -n "$END_ON" ] && grep -aqE -- "$END_ON" "$D/console.txt" 2>/dev/null; then why="end-on /$END_ON/"; fi
  if [ -z "$ended" ] && [ -n "$END_AFTER" ] && [ -n "$home" ] && [ $(( $(date +%s) - t0 )) -ge $(( home + END_AFTER )) ]; then why="end-after ${END_AFTER}s"; fi
  if [ -n "$why" ]; then
    ended=1; timeout 30 bash tools/screenshot.sh "$D" --scale 2 --name end >> "$OUT" 2>&1 || true
    if [ -n "$QUERIES" ]; then          # hkq batch through the live reader, before the reset (query gate must be in the image)
      log "END $why: queries [$QUERIES]"
      timeout 300 mac repo --force -- python3 -I "${lt:+$lt/}tools/hkq.py" -s "$sock" -c "$D/usbcon/usbcon.log" \
        --timeout 25 batch "$QUERIES" > "$D/queries.txt" 2>&1 || true
      { echo "-- queries ($QUERIES)"; cut -c1-200 "$D/queries.txt" 2>/dev/null | tail -40; } >> "$OUT"
    fi
    log "END $why: reset op -> $(reset)"
    continue
  fi
  if [ -z "$UI" ] && [ -z "$ended" ] && [ -n "$home" ] && [ $(( $(date +%s) - t0 )) -ge $(( home + 45 + shot * 300 )) ]; then
    shot=$((shot+1))
    timeout 90 bash tools/screenshot.sh "$D" --scale 2 --name probe$shot >> "$OUT" 2>&1 || log "screenshot $shot failed"
  fi
done
wait $LB; log "live_boot rc=$?"
{
  bash tools/hk_autoprobe.sh "$D" "$EXTRA" 2>&1 | grep -v '^screenshot:'
  echo "-- markers"; cut -c1-160 "$D/markers.txt" 2>/dev/null | tail -25
  echo "-- CRASH tally"; grep -aoE 'CRASH [A-Za-z_.]+' "$D/console.txt" 2>/dev/null | sort | uniq -c | sort -rn | head -15
  echo "-- exec counts (respawn loops)"; grep -aoE 'exec [A-Za-z_.]+' "$D/console.txt" 2>/dev/null | sort | uniq -c | sort -rn | awk '$1>2' | head -15
  echo "-- panic"; grep -aiE 'panic\(|panicked|Kernel data abort|stackshot' "$D/console.txt" 2>/dev/null | head -5
  echo "-- console lines: $(wc -l < "$D/console.txt" 2>/dev/null); last:"; tail -3 "$D/console.txt" 2>/dev/null | cut -c1-200
  echo "-- screens: $(ls "$D"/screens/*.png 2>/dev/null | tr '\n' ' ')"
} >> "$OUT" 2>&1
A=$(ls -dt research/laguna-usb-fix/attempts/2*-"$NAME" 2>/dev/null | head -1)
[ -n "$A" ] && { timeout 120 bash tools/screenshot.sh --dump "$A" --allow-stale -o "$D/final-screen.png" >> "$OUT" 2>&1; python3 tools/boot-summary.py "$A" 2>&1 | tail -15 >> "$OUT"; }

# back to Android + return check (HK_STAY=1: stay parked in fastboot for the next boot)
[ "${HK_STAY:-0}" = 1 ] && { infb && log "staying in fastboot" || log "NOT in fastboot"; log DONE; exit 0; }
for i in $(seq 1 60); do infb && break; sleep 5; done
if infb; then
  # With force-fastboot on, `fastboot reboot` only parks again and adb never comes (2026-11-11, twice): off, read back, then reboot.
  fastboot oem force-fastboot off >/dev/null 2>&1
  if ! fastboot oem force-fastboot 2>&1 | grep -q 'force-fastboot off'; then
    log "force-fastboot does not read off: NOT rebooting (it would only park again). Phone stays in fastboot; use tools/hk_session.py --return"; log DONE; exit 1
  fi
  fastboot reboot >/dev/null 2>&1
  R=research/ios26-dualboot-r8/attempts/return-after-$NAME
  timeout 900 bash research/ios26-dualboot-r8/return-check.sh "$R" > "$HOME/hk-logs/$NAME.return.log" 2>&1
  log "return check: $(tail -3 "$HOME/hk-logs/$NAME.return.log" | tr '\n' ' ' | cut -c1-300)"
else
  log "phone not in fastboot after the boot; return check NOT run"
fi
log DONE
