#!/bin/sh
# Mac only (repo root). hk_mainwatch: host test (macOS arm64, -DHK_MAINWATCH_TEST, fake UIApplication), then the
# deployable dylib with accel-wait/build-mac/build.sh's steps: xcrun clang -arch arm64e (iphoneos SDK, min 26.0)
# -dynamiclib, renegade pacstrip.py --sign, codesign --verify --strict, and the usual inspection receipts.
# Writes only research/ios26-phaseb-r1/perf/{out,receipts}. HOST ONLY: boots nothing.
set -eu
REPO=$(pwd); P=research/ios26-phaseb-r1/perf; OUT=$P/out; R=$P/receipts/mainwatch
mkdir -p $OUT $R
# 1. host test
xcrun clang -arch arm64 -O1 -g -Wall -Wextra -Werror -DHK_MAINWATCH_TEST -dynamiclib $P/src/hk_mainwatch.c -lobjc -o $OUT/hk_mainwatch_test.dylib
xcrun clang -arch arm64 -O1 -g -Wall -Wextra -Werror -fobjc-arc -framework Foundation $P/tests/test_mainwatch.m -o $OUT/test_mainwatch
$OUT/test_mainwatch $OUT/hk_mainwatch_test.dylib off > $R/host-off.txt 2>&1
cat $R/host-off.txt
grep -q '^OFF orig 1 imp-unchanged 1$' $R/host-off.txt && ! grep -q HKMAIN $R/host-off.txt && echo 'PASS gate off: silent, sendEvent: untouched' | tee -a $R/host-off.txt
$OUT/test_mainwatch $OUT/hk_mainwatch_test.dylib > $R/host-run.txt 2>&1 &
PID=$!
# SIGSTOP the test for 5 s after its second drain starts, to see the gap line
while ! grep -q READY_FOR_STOP $R/host-run.txt 2>/dev/null; do sleep 0.2; done
sleep 2; kill -STOP $PID; sleep 5; kill -CONT $PID
wait $PID
python3 -I $P/tests/check_mainwatch.py $R/host-run.txt | tee $R/host-check.txt
# 2. device dylib
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
IOS="xcrun clang -arch arm64e -isysroot $SDK -miphoneos-version-min=26.0 -O2 -Wall -Wextra -Werror"
$IOS -c $P/src/hk_mainwatch.c -o $OUT/hk_mainwatch.arm64e.o
$IOS -dynamiclib $P/src/hk_mainwatch.c -install_name /private/var/hk/hk_mainwatch.dylib -lobjc -o $OUT/hk_mainwatch.raw.dylib
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --sign -o $OUT/hk_mainwatch.dylib $OUT/hk_mainwatch.raw.dylib > $R/pacstrip.txt 2>&1
codesign --verify --strict $OUT/hk_mainwatch.dylib > $R/codesign-verify.txt 2>&1
codesign -d --verbose=4 $OUT/hk_mainwatch.dylib > $R/codesign-details.txt 2>&1
python3 -I research/ios26-root-r1/build-r3/tools/renegade/pacstrip.py --scan $OUT/hk_mainwatch.dylib > $R/pac-scan.txt 2>&1
file $OUT/hk_mainwatch.arm64e.o $OUT/hk_mainwatch.raw.dylib $OUT/hk_mainwatch.dylib > $R/file.txt
xcrun otool -hv $OUT/hk_mainwatch.dylib > $R/header.txt
xcrun otool -L $OUT/hk_mainwatch.dylib > $R/otool-L.txt
xcrun vtool -show-build $OUT/hk_mainwatch.dylib > $R/build-version.txt
xcrun nm -m $OUT/hk_mainwatch.dylib > $R/nm-m.txt
xcrun nm -u $OUT/hk_mainwatch.dylib > $R/nm-undefined.txt
xcrun otool -tvV $OUT/hk_mainwatch.dylib > $R/disassembly.txt
xcrun clang --version > $R/clang-version.txt
echo "$SDK" > $R/sdk.txt
cat $R/file.txt $R/otool-L.txt $R/build-version.txt $R/codesign-verify.txt
shasum -a 256 $P/src/hk_mainwatch.c $P/tests/* $OUT/hk_mainwatch.arm64e.o $OUT/hk_mainwatch.raw.dylib $OUT/hk_mainwatch.dylib $OUT/hk_mainwatch_test.dylib | tee $R/SHA256SUMS
