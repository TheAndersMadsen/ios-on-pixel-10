#!/bin/sh
# HOST: hk_logmirror injected into a test program, console = a temp file. Linux (LD_PRELOAD) or macOS (DYLD_INSERT_LIBRARIES,
# with real os_log lines under OS_ACTIVITY_DT_MODE=YES). Prints PASS/FAIL lines; exit 1 on any FAIL.
set -u
D=$(cd "$(dirname "$0")" && pwd); S=$D/../src
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CC=${CC:-cc}
if [ "$(uname)" = Darwin ]; then
  CC="xcrun clang -arch arm64"; LIB=$T/m.dylib; INJ=DYLD_INSERT_LIBRARIES
  $CC -O1 -Wall -Wextra -Werror -DHK_CONSOLE_PATH="\"$T/console\"" -dynamiclib "$S/hk_logmirror.c" -I "$S" -o $LIB || exit 1
else
  LIB=$T/m.so; INJ=LD_PRELOAD
  $CC -O1 -Wall -Wextra -Werror -fPIC -shared -pthread -DHK_CONSOLE_PATH="\"$T/console\"" "$S/hk_logmirror.c" -I "$S" -o $LIB || exit 1
fi
$CC -O1 -Wall -Wextra -Werror "$D/logmirror_drv.c" -o $T/drv || exit 1
F=0
ok() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; F=1; fi; }
run() { : > $T/console; env $INJ=$LIB "$@" $T/drv $MODE $N 2> $T/err > $T/out; echo $? > $T/rc; }
c() { grep -c "$1" $T/console; }
MODE=lines N=10 run HK_LOGMIRROR=0;   ok "gate 0: console empty, stderr untouched" '[ ! -s $T/console ] && [ $(grep -c MARKER $T/err) = 10 ]'
MODE=lines N=10 run;                  ok "no gate: console empty" '[ ! -s $T/console ] && [ $(grep -c MARKER $T/err) = 10 ]'
MODE=lines N=10 run HK_LOGMIRROR=1;   ok "gate 1: banner + 10 tagged lines, stderr empty" '[ $(c "^HKL drv\[[0-9]*\] -- mirror on: os_log and stderr, 8 lines/s burst 64, 320 B a line$") = 1 ] && [ $(c "^HKL drv\[[0-9]*\] MARKER [0-9]$") = 10 ] && [ ! -s $T/err ]'
ok "gate 1: pid in the tag is the program's" 'P=$(sed -n "s/^HKL drv\[\([0-9]*\)\] MARKER 0$/\1/p" $T/console); [ -n "$P" ]'
MODE=lines N=500 run HK_LOGMIRROR=1;  ok "default budget: 500 fast lines -> the burst of 64" '[ $(c "MARKER") = 64 ]'
MODE=lines N=500 run HK_LOGMIRROR=00; ok "HK_LOGMIRROR=00: no per-program limit, all 500" '[ $(c "MARKER") = 500 ]'
MODE=lines N=300 run HK_LOGMIRROR=5,10; ok "HK_LOGMIRROR=5,10: 10 lines" '[ $(c "MARKER") = 10 ] && grep -q "5 lines/s burst 10" $T/console'
START=$(date +%s); MODE=flood N=300000 run HK_LOGMIRROR=1; END=$(date +%s)
ok "flood: 300000 lines never block the program (rc 0, < 10 s)" '[ $(cat $T/rc) = 0 ] && [ $((END-START)) -lt 10 ] && [ $(c MARKER) -le 70 ]'
if [ "$(uname)" = Darwin ]; then
  MODE=oslog N=5 run HK_LOGMIRROR=1 OS_ACTIVITY_DT_MODE=YES
  ok "os_log under DT mode: 5 tagged lines, date and head dropped" '[ $(c "^HKL drv\[[0-9]*\] .*OSLOG-MARKER [0-4]$") = 5 ] && ! grep -q "OSLOG-MARKER.*[0-9]\{4\}-[0-9][0-9]-[0-9][0-9] " $T/console'
  sed -n '/OSLOG-MARKER 0/p' $T/console | head -1 | sed 's/^/  sample: /'
  MODE=closefrom N=5 run HK_LOGMIRROR=1
  ok "the program closes the reader's fd: no SIGPIPE, rc 0" '[ $(cat $T/rc) = 0 ] && grep -q survived $T/out'
else
  echo "SKIP os_log and SIGPIPE checks (macOS only)"
fi
exit $F
