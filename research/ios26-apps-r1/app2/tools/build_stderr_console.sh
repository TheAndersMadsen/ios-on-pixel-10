#!/bin/sh
# Mac only (repo root). hk_stderr_console: host test (macOS arm64, console path = a temp file), then the device dylib
# (arm64e, iphoneos SDK, min 26.0, renegade pacstrip.py --sign, codesign --verify --strict), as perf/tools/build_mainwatch.sh.
set -eu
A=research/ios26-apps-r1/app2; OUT=$A/out; R=$A/receipts/stderr_console
mkdir -p $OUT $R
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
# 1. host test
xcrun clang -arch arm64 -O1 -Wall -Wextra -Werror -DHK_CONSOLE_PATH="\"$T/console\"" -dynamiclib $A/src/hk_stderr_console.c -o $T/t.dylib
xcrun clang -arch arm64 -O1 -Wall -Wextra -Werror $A/tests/test_stderr_console.c -o $T/drv
: > $T/console
DYLD_INSERT_LIBRARIES=$T/t.dylib $T/drv 2> $T/off.err; DYLD_INSERT_LIBRARIES=$T/t.dylib HK_STDERR_CONSOLE=0 $T/drv 2>> $T/off.err
OFFC=$(wc -c < $T/console | tr -d ' ')
DYLD_INSERT_LIBRARIES=$T/t.dylib HK_STDERR_CONSOLE=1 $T/drv 2> $T/on.err
{
  echo "gate off/0: stderr $(grep -c MARKER-STDERR $T/off.err) markers (want 2), console $OFFC B (want 0)"
  [ "$(grep -c MARKER-STDERR $T/off.err)" = 2 ] && [ "$OFFC" = 0 ] && echo "PASS off" || { echo "FAIL off"; exit 1; }
  echo "gate 1: stderr $(wc -c < $T/on.err | tr -d ' ') B (want 0); console:"; sed 's/^/  /' $T/console
  [ ! -s $T/on.err ] && grep -q '^HKSTDERR: drv\[[0-9]*\] stderr -> ' $T/console && grep -q '^MARKER-STDERR$' $T/console && echo "PASS on" || { echo "FAIL on"; exit 1; }
} > $R/host-test.txt; cat $R/host-test.txt
# 2. device dylib
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
IOS="xcrun clang -arch arm64e -isysroot $SDK -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror"
$IOS -dynamiclib $A/src/hk_stderr_console.c -install_name /private/var/hk/hk_stderr_console.dylib -o $OUT/hk_stderr_console.raw.dylib
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --sign -o $OUT/hk_stderr_console.dylib $OUT/hk_stderr_console.raw.dylib > $R/pacstrip.txt 2>&1
codesign --verify --strict $OUT/hk_stderr_console.dylib > $R/codesign-verify.txt 2>&1 && echo "codesign verify OK" >> $R/codesign-verify.txt
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --scan $OUT/hk_stderr_console.dylib > $R/pac-scan.txt 2>&1
file $OUT/hk_stderr_console.dylib > $R/file.txt
xcrun otool -L $OUT/hk_stderr_console.dylib > $R/otool-L.txt
xcrun vtool -show-build $OUT/hk_stderr_console.dylib > $R/build-version.txt
xcrun nm -u $OUT/hk_stderr_console.dylib > $R/nm-undefined.txt
cat $R/file.txt $R/otool-L.txt $R/nm-undefined.txt $R/codesign-verify.txt $R/pac-scan.txt
shasum -a 256 $A/src/hk_stderr_console.c $A/tests/test_stderr_console.c $OUT/hk_stderr_console.raw.dylib $OUT/hk_stderr_console.dylib | tee $R/SHA256SUMS
